"""Worker of tools/readiness_check.py: one whole run of ONE procedure on the simulated bench, no hardware, recorded as plain JSON.

Not for direct use.  `python tools/readiness_check.py <procedure>` starts this in a fresh interpreter (module-level engine state such as
truevolt_verification.configure() must not leak from one procedure into the next) and reads the JSON back.

What it does, in order:
  1. a throw-away HOME / CALSUITE_DATA (nothing reaches the real lab registry, Asset History or ~/.calibration_suite/command_log.txt),
     a stand-in for tkinter (tests/_tk_stub.py; the real windows are never built) and the scripted-operator harness the tests already use
     (tests/virtual_harness.py: modal dialogs answered, 'Fill with a simulated reading' pressed);
  2. the procedure's OWN launcher is run exactly as `python Procedures/<id>.py --demo` would (runpy), so the engine, model, spec and options
     are the ones the Manager would start; the App it builds is picked up and run to the end (Run All);
  3. the EXISTING run log is the evidence: every line the drivers add to a CommandLog (drivers/transport.py) is copied, in order, into one
     timeline together with every dialog the operator would have seen.  Nothing is logged by this tool itself and no logging system is added.
Engine-specific set-up (which model the TDS scope asks for, the non-demo bench of the 8808A ...) mirrors the engine's own tests.
"""
from __future__ import annotations

import gc
from collections import Counter
import json
import os
import runpy
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_S = 240

TIMELINE = []            # ('cmd', label, direction, text) | ('dlg', kind, title, detail)
CLASSES = {}             # instrument label -> 'module:Class'
PM_PARAMS = []           # (name, default)
DIAGRAM_MISSES = []      # text: what was looked for
OPENED = set()           # spec / limit JSON files (relative to the suite folder) read once the launcher's main() started (App construction and the run)
OPENED_IMPORT = set()    # ... read while the modules were being imported (module-level defaults)
PHASE = ['import']
LOG_VIRTUAL = {}         # instrument label -> was its CommandLog marked virtual (a demo log must never reach the shared evidence file)


def _stub_tkinter():
    """Always the stub, even where a real tkinter is installed: the real widgets need a display and a main loop."""
    for name in [n for n in sys.modules if n == 'tkinter' or n.startswith('tkinter.')]:
        del sys.modules[name]
    sys.modules['tkinter'] = None                     # makes `import tkinter` fail inside _tk_stub.install(), which then installs the stubs
    sys.path.insert(0, str(ROOT / 'tests'))
    import _tk_stub
    _tk_stub.install()
    _tk_stub._Dummy.__setitem__ = lambda self, key, value: None          # widget['values'] = [...] in the older launchers
    _tk_stub._Dummy.__getitem__ = lambda self, key: ''
    import tkinter as tk
    if not isinstance(getattr(tk, 'TclError', None), type) or not issubclass(tk.TclError, BaseException):
        tk.TclError = type('TclError', (Exception,), {})
    return tk


def _install_recorders():
    """Copy every CommandLog line into TIMELINE, remember which driver class sits behind each label, record every tunable asked for."""
    from drivers import base, transport
    orig_add = transport.CommandLog.add

    def add(self, direction, text, instrument=''):
        TIMELINE.append(('cmd', instrument, direction, text))
        LOG_VIRTUAL[instrument] = bool(getattr(self, 'virtual', False)) and LOG_VIRTUAL.get(instrument, True)
        return orig_add(self, direction, text, instrument)
    transport.CommandLog.add = add

    orig_init = base.Instrument.__init__

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        CLASSES[self.label] = f'{type(self).__module__}:{type(self).__name__}'
    base.Instrument.__init__ = init

    import procmods_engine
    orig_param = procmods_engine.ProcModsMixin.pm_param

    def pm_param(self, name, default, point=None):
        PM_PARAMS.append((name, default))
        return orig_param(self, name, default, point)
    procmods_engine.ProcModsMixin.pm_param = pm_param

    import builtins
    import pathlib
    root = str(ROOT)

    def note(path):
        try:
            text = os.path.abspath(str(path))
            if text.startswith(root) and text.lower().endswith('.json'):
                (OPENED if PHASE[0] == 'run' else OPENED_IMPORT).add(os.path.relpath(text, root).replace(os.sep, '/'))
        except Exception:
            pass
    orig_open = builtins.open

    def open_(file, *a, **k):
        if isinstance(file, (str, os.PathLike)):
            note(file)
        return orig_open(file, *a, **k)
    builtins.open = open_
    for name in ('read_text', 'read_bytes'):
        orig = getattr(pathlib.Path, name)

        def reader(self, *a, _orig=orig, **k):
            note(self)
            return _orig(self, *a, **k)
        setattr(pathlib.Path, name, reader)

    import hookups
    orig_image = hookups.image_path

    def image_path(meter, cal, group):
        path = orig_image(meter, cal, group)
        if path is None:
            DIAGRAM_MISSES.append(f'hook_{meter}_{cal}_{group}.png')
        return path
    hookups.image_path = image_path


def _make_harness(vh):
    class RHarness(vh.VHarness):
        """VHarness that also puts every dialog on the timeline (in order with the commands)."""

        def _confirm(self, parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, **layout):
            miss = ''
            for f in facts or ():
                if isinstance(f, (list, tuple)) and len(f) > 1 and str(f[0]).lower() == 'diagram' and 'not installed' in str(f[1]):
                    miss = str(f[1])
                    DIAGRAM_MISSES.append(miss.replace('not installed (expected ', '').rstrip(')'))
            TIMELINE.append(('dlg', 'confirm', str(title), str(heading)))
            return super()._confirm(parent, title, heading, steps, facts, caution, ok, cancel, image, **layout)

        def _box(self, kind, args):
            TIMELINE.append(('dlg', 'box:' + kind, str(args[0]) if args else '', str(args[1])[:200] if len(args) > 1 else ''))
            return super()._box(kind, args)

        def _ask_reading_v(self, parent, p, total, *a, **k):
            TIMELINE.append(('dlg', 'reading', str(p.get('id')), ''))
            return super()._ask_reading_v(parent, p, total, *a, **k)

        def _ask_readings(self, parent, p, total, *a, **k):
            TIMELINE.append(('dlg', 'reading', str(p.get('id')), ''))
            return super()._ask_readings(parent, p, total, *a, **k)
    return RHarness


class _Marked(dict):
    """The engine's result store, with a 'pt' mark on the timeline whenever a point is recorded (so output states can be told apart per point)."""

    def __setitem__(self, key, value):
        TIMELINE.append(('pt', str(key)))
        super().__setitem__(key, value)


def _mark_points(app):
    for name in ('found', 'results'):
        store = getattr(app, name, None)
        if isinstance(store, dict) and not isinstance(store, _Marked):
            try:
                setattr(app, name, _Marked(store))
            except Exception:
                pass
            return


def _find_app():
    import reset_startup
    apps = [o for o in gc.get_objects() if isinstance(o, reset_startup.AppResetMixin)]
    return apps[-1] if apps else None


def _simple(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _point_list(app):
    for name in ('points', 'POINTS'):
        pts = getattr(app, name, None)
        if isinstance(pts, list) and pts and isinstance(pts[0], dict):
            return pts
    mod = sys.modules.get(type(app).__module__)
    pts = getattr(mod, 'POINTS', None)
    return pts if isinstance(pts, list) else []


def _standard_of(app):
    for attr in ('calibrator_model', 'standard_for'):
        fn = getattr(app, attr, None)
        if callable(fn):
            try:
                return fn() if attr == 'calibrator_model' else None
            except Exception:
                pass
    return getattr(app, 'cal_key', None) or '5560A'


def _should_have(app, p) -> bool:
    """Is this point supposed to print an uncertainty?  The engine's own rule when it has one (handheld has_uncertainty), else the Datasheet
    Builder's: a kind that is in the CMC table, sourced by a calibrator, not a zero-offset / no-source / typed-standard / no_uncertainty point."""
    fn = getattr(app, 'has_uncertainty', None)
    if callable(fn):
        try:
            if p.get('test') not in (None, 'numeric', 'beeper'):       # handheld yes / no checks (VoltAlert, display) print no uncertainty row
                return False
            return bool(fn(p))
        except Exception:
            return False
    import datasheet_builder_rules as dbr
    if p.get('no_uncertainty') or p.get('zero_offset') or p.get('source') in ('none', 'manual') or p.get('manual') or p.get('is_manual'):
        return False
    is_manual = getattr(app, 'is_manual', None)           # 8808A: a point the selected calibrator cannot make is measured against the technician's own standard
    if callable(is_manual):
        try:
            if is_manual(p):
                return False
        except Exception:
            pass
    return p.get('kind') in dbr.SHOULD_HAVE_KINDS


def _covered(app, p):
    """Does the lab's scope of accreditation (CMC table) cover this point?  None = cannot tell.  A blank Uncertainty is expected where it does not."""
    try:
        import report_pdf
        sc = report_pdf.scope()
        if sc is None:
            return None
        a = p.get('applied')
        if a:                                           # handheld: the source value is in 'applied'
            kind = 'OHM2' if p.get('kind') == 'OHM' else p.get('kind')
            nominal, freq, rng = a.get('value'), a.get('frequency'), None
        else:
            kind, nominal, freq, rng = p.get('kind'), p.get('nominal'), p.get('frequency'), p.get('range')
        return sc.dmm(kind, nominal, rng, freq) is not None
    except Exception:
        return None


def _report_facts(app):
    """For the uncertainty / TAR / TUR check: each report row with the point it came from.  Never raises."""
    out = dict(rows=[], note='')
    try:
        fn = getattr(app, 'certificate_rows_and_points', None)
        if fn is not None:
            rows, pts = fn()
        else:
            rows = app.certificate_rows()
            pts = _point_list(app)
            if len(pts) != len(rows):
                pts = []
    except Exception as exc:
        out['note'] = f'report rows not available: {type(exc).__name__}: {exc}'
        return out
    if not pts:
        out['note'] = 'the engine gives no point for each report row: uncertainty not checked'
    std = _standard_of(app)
    out['standard'] = std
    for i, row in enumerate(rows):
        p = pts[i] if i < len(pts) else None
        rec = dict(description=str(row.get('Description', ''))[:80], uncertainty=str(row.get('Uncertainty', '') or ''), section=str(row.get('Section', '')))
        if p is not None:
            rec.update(kind=p.get('kind'), pid=_simple(p.get('id')), should=_should_have(app, p))
            if rec['should'] and not rec['uncertainty']:
                rec['covered'] = _covered(app, p)
            rec['tar'] = rec['tur'] = None
            cf = getattr(app, 'certificate_fields', None)
            try:
                if callable(cf):
                    f = cf(p)
                else:
                    import tartur_wiring
                    f = tartur_wiring.point_fields(p, std)
                rec['tar'], rec['tur'] = str(f.get('TAR', '') or ''), str(f.get('TUR', '') or '')
            except Exception as exc:
                rec['tar'] = rec['tur'] = None
                rec['ratio_error'] = f'{type(exc).__name__}'
        out['rows'].append(rec)
    return out


def _setup_and_run(hn, app, proc):
    """Engine-specific part: what the tests of that engine do to run it to the end on its simulated bench.  Returns a note ('' = ran)."""
    import virtualbench
    from unittest import mock as _m
    app.asset.set('A-READY')
    try:
        app.serial.set('S-READY')
    except Exception:
        pass
    hn.app = app
    engine = (proc.get('engine') or [''])[0]
    name = proc['id']
    if engine == 'fluke8808a_verification.py':
        return _run_8808a(hn, app)
    if engine == 'tds2000c_verification.py':
        app.v_model.set('2024C')
        app.run_all()
        ok = hn.pump_poll(TIMEOUT_S)
    elif engine == 'mdo4000c_verification.py':
        from tkinter import simpledialog
        with _m.patch.object(simpledialog, 'askstring', lambda *a, **k: k.get('initialvalue'), create=True):
            app.run_all()
            ok = hn.pump_poll(TIMEOUT_S)
    elif engine == 'fgen_verification.py':
        from tkinter import simpledialog
        with _m.patch.object(simpledialog, 'askfloat', lambda *a, **k: k.get('initialvalue'), create=True):
            app.run_all()
            ok = hn.pump(TIMEOUT_S)
    else:
        app.run_all()
        ok = hn.pump(TIMEOUT_S)
    return '' if ok else 'the run did not finish within the time limit'


def _run_8808a(hn, app):
    """The 8808A App has no virtual bench: its test builds the simulated bench by hand and runs execute() (tests/test_beta_8808a.py)."""
    import fluke8808a_verification as E
    from drivers.simulated_8808a import make_8808a_bench
    cal = 'Fluke 5522A'
    app.cal_model.set(cal)
    bench, ct, dt = make_8808a_bench(E.CALIBRATORS[cal][0], True)
    app.io = E.IO('sim', 'sim', cal, 9600, transports=(dt, ct), mods=app.pm_state)
    app.io.is_manual = app.is_manual
    app.io.log.virtual = True

    def operator(title, heading, steps, facts):
        import re
        if title.startswith('Your own standard'):
            p = E.POINTS[int(re.search(r'Point (\d+)', heading).group(1)) - 1]
            if p['kind'] == 'FREQ':
                bench.external = ('V', p['amplitude'], p['nominal'])
            else:
                bench.external = ({'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A'}[p['kind']], p['nominal'], p.get('frequency') or 0.0)
        else:
            bench.external = None
        return True
    hn.on_confirm = operator
    app.execute(app.active_points())
    return '' if hn.pump(TIMEOUT_S) else 'the run did not finish within the time limit'


def run(proc: dict) -> dict:
    """proc: the sidecar fields {id, launcher, engine ...}.  Returns the JSON-able record."""
    t0 = time.time()
    home = tempfile.mkdtemp(prefix='readiness_')
    os.environ.update(CALSUITE_DATA=os.path.join(home, 'data'), HOME=home, USERPROFILE=home)
    tk = _stub_tkinter()
    sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures'), str(ROOT / 'tests')]
    result = dict(ok=False, error='', note='', procedure=proc['id'])
    try:
        import virtual_harness as vh
        import virtualbench
        _install_recorders()
        H = _make_harness(vh)
        hn = H().start()
        hn.root.mainloop = lambda *a, **k: None          # a launcher's main() ends with root.mainloop(): the harness pumps instead
        launcher = ROOT / proc['launcher']
        argv = [str(launcher)]
        engine = (proc.get('engine') or [''])[0]
        if engine != 'fluke8808a_verification.py':      # the 8808A App has no virtual bench: it is built without --demo and given a simulated one
            argv.append('--demo')
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(tk, 'Tk', lambda *a, **k: (PHASE.__setitem__(0, 'run'), hn.root)[1], create=True), \
                mock.patch.object(threading, 'excepthook', lambda a: TIMELINE.append(('dlg', 'thread-error', str(a.exc_type.__name__), str(a.exc_value)[:300]))):
            OPENED.clear()
            OPENED_IMPORT.clear()                         # only what the procedure itself reads (the harness imported other engines before this)
            PHASE[0] = 'import'
            runpy.run_path(str(launcher), run_name='__main__')
        app = _find_app()
        if app is None:
            result['error'] = 'the launcher did not build an App (no window object found)'
            return _finish(result, t0)
        result['app_class'] = f'{type(app).__module__}.{type(app).__name__}'
        _mark_points(app)
        with mock.patch.object(threading, 'excepthook', lambda a: TIMELINE.append(('dlg', 'thread-error', str(a.exc_type.__name__), ''.join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))[-600:]))):
            note = _setup_and_run(hn, app, proc)
        result['note'] = note
        result['virtual'] = bool(getattr(app, 'virtual', False))
        pts = _point_list(app)
        result['points'] = len(pts)
        res = getattr(app, 'results', None)
        if res is None:
            res = getattr(app, 'found', None)
        result['results'] = len(res) if res is not None else None
        keys = {str(k) for k in (res or {})}
        skipped = Counter((str(p.get('kind')), str(p.get('section') or p.get('group') or '')) for p in pts if p.get('id') is not None and str(p.get('id')) not in keys)
        result['skipped'] = [[k[0], k[1], n] for k, n in skipped.most_common(12)]
        result['synthetic_ok'] = all(r.get('synthetic', True) for r in res.values()) if isinstance(res, dict) and res and getattr(app, 'virtual', False) else None
        result['report'] = _report_facts(app)
        result['ok'] = True
    except BaseException as exc:                     # a crash is a finding, not a crash of the tool
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['trace'] = traceback.format_exc()[-1500:]
    return _finish(result, t0)


def _finish(result, t0):
    result.update(timeline=TIMELINE, classes=CLASSES, opened=sorted(OPENED), opened_import=sorted(OPENED_IMPORT), log_virtual=LOG_VIRTUAL, pm_params=sorted({(n, repr(d)) for n, d in PM_PARAMS}), diagram_misses=sorted(set(DIAGRAM_MISSES)),
                  seconds=round(time.time() - t0, 1))
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    proc = json.loads(argv[0])
    out = run(proc)
    sys.stdout.write('\n@@READINESS@@' + json.dumps(out, default=str) + '\n')


if __name__ == '__main__':
    import faulthandler
    faulthandler.dump_traceback_later(TIMEOUT_S + 60, exit=True)
    main()
