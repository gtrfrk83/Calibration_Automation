"""Operator-prompt characterization: the exact sequence of prompts an engine shows (kind, title, text, buttons, answer consumed).  Not a test module.

The golden transcripts in tests/golden/engine_*.json lock the INSTRUMENT I/O only; none of them sees a dialog.  This module records the dialogs, in one
canonical form, from two vantage points so a port of an engine from Tk to ui_port (see NOTES.md 'UiPort') can be proven prompt-for-prompt identical:

  * `TkLevelHarness`: patches the Tk calls themselves (tkinter.messagebox / filedialog / simpledialog, ui_theme.confirm_steps, report_dialog.ask_details).
    Works on the engine as it is TODAY (before a port) and after it (TkUiPort calls the same functions).
  * `PortHarness`: installs a ui_port.ScriptedUiPort; the engine must reach every prompt through the port (a prompt that still goes through a Tk call is
    not recorded there, so the two sequences differ and the test fails).

Canonical record (a dict, JSON-able; None fields are left out):
    {'kind': 'info' | 'warning' | 'error' | 'ask_yes_no' | 'ask_ok_cancel' | 'ask_retry_cancel' | 'ask_yes_no_cancel' |
             'ask_number' | 'ask_text' | 'choose_file' | 'save_file' | 'operator_prompt' | 'report_details',
     'title': str, 'text': str, 'buttons': [...], 'answer': <what the scripted operator returned>, ...kind-specific fields}
`buttons` is the button set the dialog offers (info: ['OK'], ask_yes_no: ['Yes', 'No'], operator_prompt: [ok, cancel] as given).  The parent window is never
recorded.  Fixtures live in tests/golden_ui/ (NOT tests/golden/: `python -m tests.golden_capture --update` deletes every file in tests/golden/ it does not
know).  Rewrite one with:   python -m tests.ui_prompt_capture --update <scenario set>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import virtual_harness as VH  # noqa: E402  (installs the tkinter stub)
import live_editor_harness as LH  # noqa: E402
import ui_port  # noqa: E402
from ui_port import Answers, operator_record, plain, record  # noqa: E402  (the canonical form is defined once, next to ScriptedUiPort)

GOLDEN_UI = ROOT / 'tests' / 'golden_ui'

TK_KIND = {'showinfo': 'info', 'showwarning': 'warning', 'showerror': 'error', 'askyesno': 'ask_yes_no', 'askokcancel': 'ask_ok_cancel',
           'askretrycancel': 'ask_retry_cancel', 'askyesnocancel': 'ask_yes_no_cancel'}


# ---------------------------------------------------------------------------------------------------------------------------------------
class TkLevelHarness(VH.VHarness):
    """VHarness (stubbed Tk, simulated benches) whose Tk dialog functions are replaced by recorders in the canonical form."""

    def __init__(self, answers=None, home=None):
        super().__init__(home)
        self.prompts = []
        self.answers = answers or Answers()

    def start(self):
        super().start()
        import tkinter
        import report_dialog
        mb, fd, sd = tkinter.messagebox, tkinter.filedialog, tkinter.simpledialog
        pats = []
        for name, kind in TK_KIND.items():
            if kind in ('info', 'warning', 'error'):
                pats.append((mb, name, self._mk_show(kind)))
            else:
                pats.append((mb, name, self._mk_ask(kind)))
        pats += [(fd, 'askopenfilename', self._file('choose_file')), (fd, 'asksaveasfilename', self._file('save_file')),
                 (sd, 'askfloat', self._simple('ask_number')), (sd, 'askinteger', self._simple('ask_number')), (sd, 'askstring', self._simple('ask_text')),
                 (report_dialog, 'ask_details', self._details), (VH.hh.ui, 'confirm_steps', self._confirm)]
        for obj, name, val in pats:
            p = mock.patch.object(obj, name, val, create=True)
            p.start()
            self.patches.append(p)
        return self

    # the recorders -------------------------------------------------------------------------------------------------------------------
    def _mk_show(self, kind):
        def show(title='', message='', *a, **k):
            self.prompts.append(record(kind, title, message, None))
        return show

    def _mk_ask(self, kind):
        def ask(title='', message='', *a, **k):
            rec = record(kind, title, message, None, icon=k.get('icon'), default=k.get('default'))
            ans = self.answers.for_(rec, self.box_answer.get({v: n for n, v in TK_KIND.items()}[kind], True))
            self.prompts.append(dict(rec, answer=plain(ans)))
            return ans
        return ask

    def _file(self, kind):
        def choose(*a, **k):
            opts = {n: k.get(n) for n in ('defaultextension', 'filetypes', 'initialfile', 'title') if k.get(n) is not None}
            rec = record(kind, '', '', None, options=opts)
            ans = self.answers.for_(rec, self.answers.save_path if kind == 'save_file' else self.answers.open_path)
            self.prompts.append(dict(rec, answer=plain(ans)))
            return ans
        return choose

    def _simple(self, kind):
        def ask(title='', prompt='', *a, **k):
            rec = record(kind, title, prompt, None, initial=k.get('initialvalue'), masked=True if k.get('show') else None)
            ans = self.answers.for_(rec, None)
            self.prompts.append(dict(rec, answer=('<masked>' if k.get('show') and ans else plain(ans))))          # a typed secret is never recorded
            return ans
        return ask

    def _details(self, parent, procedure=''):
        rec = record('report_details', procedure, '', None)
        ans = self.answers.for_(rec, None)
        self.prompts.append(dict(rec, answer=plain(ans)))
        return ans

    def _confirm(self, parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, **_layout):
        rec = operator_record(title, heading, steps, facts, caution, ok, cancel, image, None, **_layout)
        r = super()._confirm(parent, title, heading, steps, facts, caution, ok, cancel, image, **_layout)     # VHarness bookkeeping (dialogs, on_confirm)
        ans = self.answers.for_(rec, r)
        self.prompts.append(dict(rec, answer=plain(ans)))
        return ans

    def _ask_reading_v(self, parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                       limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
        """handheld_dmm.ask_reading (not in UiPort yet: the handheld work package adds it): recorded as kind 'ask_reading'."""
        ans = super()._ask_reading_v(parent, p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate, phase, limit_s, on_expire,
                                     device, source, demo_fill)
        self.prompts.append(record('ask_reading', f'point {p["id"]}', out_text, ans, mode=mode, device=device, source=source, unit=unit, phase=phase or None,
                                   question=question, annunciator=bool(annunciator), fill_offered=demo_fill is not None, note=out_note))
        return ans

    def _box(self, kind, args):                     # unused here (the Tk functions are replaced above) but keeps VHarness helpers consistent
        return self.box_answer.get(kind, True)


class PortHarness(TkLevelHarness):
    """The same scripted operator behind ui_port.ScriptedUiPort: every prompt must arrive through the port.  The Tk-level recorders stay installed underneath: a
    prompt that bypasses the port lands in `.prompts` (the scenarios assert it stays empty), a prompt through the port lands in `.port.prompts`."""

    def start(self):
        super().start()
        self.port = ui_port.ScriptedUiPort(self.answers)
        self._old_ui = ui_port.set_ui(self.port)
        return self

    def stop(self):
        ui_port.set_ui(self._old_ui)
        super().stop()


# ---------------------------------------------------------------------------------------------------------------------------------------
# scenarios.  Each takes a harness class and returns {scenario name: [canonical prompt records]}.
# ---------------------------------------------------------------------------------------------------------------------------------------
def _run_a34410a(make_harness):
    import agilent34410a_verification as A
    out = {}

    def new(answers=None, **settings):
        hn = make_harness(answers)
        hn.start()
        a = A.App(hn.root, demo=True, fast_demo=settings.pop('fast', False))
        a.asset.set('A-1'); a.serial.set('S-1')
        for k, v in settings.items():
            getattr(a, k).set(v)
        hn.app = a
        return hn, a

    def prompts(hn):
        return hn.port.prompts if hasattr(hn, 'port') else hn.prompts

    def done(name, hn):
        out[name] = prompts(hn)
        bypassed = hn.prompts if hasattr(hn, 'port') else []
        hn.stop()
        assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'

    # 1. a whole virtual run (warm-up prompt, every wiring prompt with its steps / facts / caution / image, the high-voltage questions)
    hn, a = new()
    assert hn.run_all()
    done('virtual_run_5560A_gpib', hn)

    # 2. the optional tests too (capacitance standard prompt), calibrator 5522A on USB
    hn, a = new(cal_model='Fluke 5522A', interface='USB', include_optional=True)
    a.cal_model.set('Fluke 5522A')
    assert hn.run_all()
    done('virtual_run_5522A_usb_optional', hn)

    # 3. the operator refuses the first high-voltage question: the run stops
    hn, a = new(Answers([lambda r: False if r.get('title') == 'HIGH VOLTAGE' else None]))
    hn.run_all()
    done('high_voltage_refused', hn)

    # 4. the operator cancels the warm-up prompt: the run does not start
    hn, a = new(Answers([lambda r: False if r.get('title') == 'Before the verification' else None]))
    hn.run_all()
    done('warmup_cancelled', hn)

    # 5. the small dialogs, one by one
    hn, a = new()
    a.asset.set('')
    a.execute(a.active_points()[:1])                       # no instrument ID -> warning
    a.asset.set('A-1')
    a.tree.selection.return_value = ()                     # Rerun Selected with nothing selected -> info
    a.rerun()
    a.export_pdf()                                         # nothing recorded yet -> info
    a.test_connections()                                   # virtual: connects the simulated bench -> info 'Connected (DEMO)'
    a._error(RuntimeError('boom'))                         # a measurement failure -> error
    a.busy = True
    hn.answers.rules.append(lambda r: False if r.get('title') == 'Active run' else None)
    a.on_close()                                           # busy: 'Stop and close?' -> No (stays open)
    hn.answers.rules.clear()
    a.busy = False
    done('dialogs_misc', hn)

    # 6. export with results: details window cancelled, then details + a file name left empty; load: file dialog cancelled
    hn, a = new()
    assert hn.run_all() is True
    hn.prompts.clear() if not hasattr(hn, 'port') else hn.port.prompts.clear()
    a.export_pdf()                                         # report details -> None (cancelled)
    hn.answers.rules.append(lambda r: {} if r['kind'] == 'report_details' else None)
    a.export_pdf()                                         # report details given, save-as cancelled ('')
    a.load()                                               # open-file cancelled ('')
    done('export_and_load_cancelled', hn)
    return out


def _run_f8808a(make_harness):
    """Fluke 8808A verification: no engine golden transcript exists for it (only the driver ones), so this is its prompt characterization."""
    import re
    import fluke8808a_verification as E
    from drivers.simulated_8808a import make_8808a_bench
    out = {}

    def new(answers=None, cal='Fluke 5522A', io=True, demo=False):
        hn = make_harness(answers)
        env = LH.Env()
        hn.start()
        patch = mock.patch('time.sleep', side_effect=lambda s: None)
        patch.start()
        hn.patches.append(patch)
        E.configure()
        a = E.App(hn.root, '8808A', demo=demo)
        hn.app = a
        a.asset.set('A-8808'); a.serial.set('SN')
        a.cal_model.set(cal)
        st = a.pm_state
        st.store, st.devmode = env.store, env.dm
        hn.env = env
        if io:
            bench, ct, dt = make_8808a_bench(E.CALIBRATORS[cal][0], True)
            a.io = E.IO('sim', 'sim', cal, 9600, transports=(dt, ct), mods=a.pm_state)
            a.io.is_manual = a.is_manual

            def operator(rec):                              # the technician connects the stated standard for a 'Your own standard' prompt
                if rec['kind'] == 'operator_prompt' and rec['title'].startswith('Your own standard'):
                    p = E.POINTS[int(re.search(r'Point (\d+)', rec['text']).group(1)) - 1]
                    if p['kind'] == 'FREQ':
                        bench.external = ('V', p['amplitude'], p['nominal'])
                    else:
                        bench.external = ({'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A'}[p['kind']], p['nominal'], p.get('frequency') or 0.0)
                elif rec['kind'] == 'operator_prompt':
                    bench.external = None
                return None
            hn.answers.rules.insert(0, operator)
        return hn, a

    def prompts(hn):
        return hn.port.prompts if hasattr(hn, 'port') else hn.prompts

    def done(name, hn):
        out[name] = prompts(hn)
        bypassed = hn.prompts if hasattr(hn, 'port') else []
        hn.stop(); hn.env.close()
        assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'

    hn, a = new()
    a.execute(a.active_points())
    assert hn.pump(180)
    done('run_5522A_all_points', hn)

    hn, a = new(cal='Fluke 5560A')
    a.execute(a.active_points())
    assert hn.pump(180)
    done('run_5560A_all_points', hn)

    hn, a = new(Answers([lambda r: False if r.get('title') == 'HIGH VOLTAGE' else None]))
    a.warm_confirmed = True
    a.execute([p for p in E.POINTS if p['ref'] == 'T3-2 #16'])
    hn.pump(30)
    done('high_voltage_refused', hn)

    hn, a = new(Answers([lambda r: False if r.get('title') == 'Warm-up' else None]))
    a.execute(a.active_points()[:3])
    hn.pump(30)
    done('warmup_refused', hn)

    hn, a = new(io=False, demo=True)
    a.asset.set('')
    a.execute(a.active_points()[:1])                       # no instrument ID -> warning
    a.asset.set('A-8808')
    a.tree.selection.return_value = ()
    a.rerun()
    a.export_pdf()
    a.test_connections()                                   # demo -> 'Demo mode' info
    a._error(RuntimeError('boom'))
    a.busy = True
    hn.answers.rules.append(lambda r: False if r.get('title') == 'Active run' else None)
    a.on_close()
    hn.answers.rules.clear()
    a.busy = False
    done('dialogs_misc', hn)
    return out


def _run_handheld(make_harness):
    """handheld_dmm.App on the virtual bench (not the fast demo): the Fluke 77 Series IV, a 110-series meter (117) and the 87V.  The Fill button answers the
    reading windows (the virtual operator).  ask_reading is recorded at the Tk level only (it has no UiPort method yet)."""
    import handheld_dmm as hh
    out = {}
    for key, model, spec in (('77iv', '77IV', 'fluke_77iv_pv.json'), ('117', '117', 'fluke_110_series_pv.json'), ('87v', '87V', 'fluke_87v_pv.json')):
        hn = make_harness(None)
        hn.start()
        app = hh.App(hn.root, model, demo=True, spec=hh.load_spec(spec), fast_demo=False)
        app.asset.set('A-1'); app.serial.set('S-1')
        app.demo_failures = None
        app.demo_failures_on = False
        hn.app = app
        assert hn.run_all(), key
        out[f'virtual_run_{key}'] = hn.port.prompts if hasattr(hn, 'port') else hn.prompts
        hn.stop()
    return out


def _run_adjustments(make_harness):
    """Fluke 8808A and Keithley 2000 ADJUSTMENT launchers (no engine golden transcript): the first dialogs of a demo (virtual bench) adjustment record, driven
    like the operator would: connect, start the record, unlock / enter the calibration mode, the first steps, then Abort.  ask_value (their own value-entry window,
    not in UiPort yet) is recorded as kind 'ask_value' and answers with the pre-filled default.  The calibration code is masked in the record."""
    out = {}
    for key, modname in (('f8808a_adj', 'Fluke_8808A_Adjustment'), ('k2000_adj', 'Keithley_2000_Adjustment')):
        mod = __import__(modname)
        hn = make_harness(None)
        hn.start()
        from drivers.simulated_k2000_cal import SIM_CODE
        hn.answers.rules.append(lambda r: SIM_CODE if r['kind'] == 'ask_text' and r['title'] == 'Calibration code' else None)

        def ask_value(self, title, prompt, default, _hn=hn):
            _hn.prompts.append(record('ask_value', title, prompt, default))
            return default
        p = mock.patch.object(mod.App, 'ask_value', ask_value, create=True)
        p.start(); hn.patches.append(p)
        app = mod.App(hn.root, demo=True)
        hn.app = app
        app.connect()                                      # no instrument ID -> warning
        app.asset.set('A-1'); app.serial.set('S-1'); app.tech.set('T')
        app.connect()
        app.start_record()
        (app.unlock if modname.startswith('Keithley') else app.enter_calibration)()
        for _ in range(8):
            if app.session and app.session.next_step():
                app.run_next(); hn.pump(20)
        app.abort(ask=True)
        app.on_close()
        out[f'{key}_first_steps_then_abort'] = hn.port.prompts if hasattr(hn, 'port') else hn.prompts
        hn.stop()
    return out


SCENARIOS = {'a34410a': _run_a34410a, 'f8808a': _run_f8808a, 'handheld': _run_handheld, 'adjustments': _run_adjustments}


# ---- WP-W (WaveSurfer 4104HD): the scenario lives in tests/ui_prompt_capture_ws.py (append-only block; other packages add their own lines below / above) --------------
from ui_prompt_capture_ws import _run_wavesurfer  # noqa: E402
SCENARIOS['wavesurfer'] = _run_wavesurfer


def capture(name, harness_class=TkLevelHarness):
    return SCENARIOS[name](lambda answers=None: harness_class(answers))


def fixture_path(name):
    return GOLDEN_UI / f'ui_prompts_{name}.json'


def dumps(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != '--update':
        print(__doc__)
        print('Nothing written. Re-run with --update <name> ... (' + ', '.join(SCENARIOS) + ') to rewrite tests/golden_ui/ui_prompts_<name>.json (review the git diff).')
        return 0
    GOLDEN_UI.mkdir(exist_ok=True)
    for name in argv[1:] or list(SCENARIOS):
        fixture_path(name).write_text(dumps(capture(name)), encoding='utf-8')
        print('wrote', fixture_path(name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
