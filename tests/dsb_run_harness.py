"""Headless harness for the user-built datasheet runtime (tests/test_dsb_runtime*.py).  Not a test module.

No tkinter is installed where the suite runs, so tests/_tk_stub.py stands in for it (as the other engine tests do) and the window code that
builds widgets (ui_theme / ui_shell) is replaced by mocks.  What RUNS is the real code: handheld_dmm.App + dsb_runtime.DsbApp (the point loop, reset
before the first point, routing, worker threads, judging, checkpoint, report rows and the PDF writer) against the simulated benches
(drivers/simulated*.py).  Only the modal dialogs are scripted: the 'operator' types readings and presses Continue through Harness.reader /
Harness.on_confirm.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub  # noqa: E402

_tk_stub.install()
import tkinter as _tk  # noqa: E402

if not isinstance(getattr(_tk, 'TclError', None), type) or not issubclass(_tk.TclError, BaseException):
    _tk.TclError = type('TclError', (Exception,), {})          # the stub's TclError is not an exception class; ui_theme catches it

import drivers  # noqa: E402
import handheld_dmm as hh  # noqa: E402
import run_queue_engine  # noqa: E402
import tds2000c_verification as tds  # noqa: E402
import ui_shell  # noqa: E402
import ui_theme as ui  # noqa: E402
import labregistry  # noqa: E402
import dsb_runtime as rt  # noqa: E402


class _FakeProgress:
    """Stands in for run_queue_ui.QueueProgress: records what the engine shows."""

    def __init__(self, harness):
        self.h = harness
        self.closed = False

    def update(self, heading, fraction, rows, finished=False, note=''):
        self.h.progress_log.append(('update', heading, fraction, [dict(r) for r in rows], finished))

    def close(self):
        self.closed = True


class FakeRoot:
    """tk.Tk() stand-in: after() queues callbacks; Harness.pump runs them on the main thread."""

    def __init__(self):
        self.q = []

    def after(self, _ms, fn=None, *a):
        if fn is not None:
            self.q.append((fn, a))
        return len(self.q)

    def __getattr__(self, name):
        return lambda *a, **k: None


class Harness:
    def __init__(self, home=None):
        self.home = Path(home or tempfile.mkdtemp())
        self.patches = []
        self.dialogs = []                   # ('confirm', title, heading, steps) / ('reading', point id, mode) / ('box', kind, title)
        self.readings = {}                  # point id -> text the operator types (or a callable p -> text)
        self.default_reading = None         # callable(p) -> text for points not in `readings`
        self.on_confirm = None              # callable(title, heading, steps, facts) -> bool|None, may act on the simulated bench
        self.box_answer = {'askyesno': True, 'askyesnocancel': True}
        self.queue_readings = {}            # (asset, point id) -> text | callable(p) the operator types for that meter in a run-queue reading window
        self.queue_default = None           # callable(p, asset) -> text for the meters / points not in queue_readings
        self.queue_no_reading = set()       # (asset, point id) the operator marks 'No reading'
        self.queue_action = {}              # point id -> 'skip' | 'stop' in the run-queue reading window
        self.progress_log = []              # ('update', heading, fraction, rows, finished) of the run-queue progress window
        self.fill = getattr(self, 'fill', False)
        self.root = FakeRoot()
        self.app = None

    # ---- environment -------------------------------------------------------------------------------------------------------------
    def start(self):
        env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.home / 'data'), 'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        env.start()
        self.patches.append(env)
        for obj, name, val in ((ui, 'apply_theme', mock.MagicMock()), (ui, 'fit_window', mock.MagicMock()), (ui, 'polish', mock.MagicMock()),
                               (ui_shell, 'Shell', mock.MagicMock()), (ui_shell, 'results_table', mock.MagicMock()),
                               (ui_shell, 'small_window', mock.MagicMock()), (labregistry, 'attach', mock.MagicMock()),
                               (ui, 'confirm_steps', self._confirm), (hh, 'ask_reading', self._ask_reading), (hh, 'ask_readings', self._ask_readings),
                               (run_queue_engine.QueueMixin, 'queue_progress_factory', staticmethod(lambda *a, _h=self, **k: _FakeProgress(_h))),
                               (tds, 'SLEEP_SCALE', 0), (hh.IO, '_wait', staticmethod(lambda seconds, cancel=None: None))):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.patches.append(p)
        for name in ('askyesno', 'askyesnocancel', 'askokcancel'):
            p = mock.patch.object(hh.messagebox, name, lambda *a, _n=name, **k: self._box(_n, a), create=True)
            p.start()
            self.patches.append(p)
        for name in ('showinfo', 'showwarning', 'showerror'):
            p = mock.patch.object(hh.messagebox, name, lambda *a, _n=name, **k: self.dialogs.append(('box', _n, a[0] if a else '', a[1] if len(a) > 1 else '')), create=True)
            p.start()
            self.patches.append(p)
        import drivers.fluke_5790b as f5790
        p = mock.patch.object(f5790.time, 'sleep', lambda s: None)       # the 5790B settle poll; the pump keeps its own sleeps
        p.start()
        self.patches.append(p)
        return self

    def stop(self):
        for p in reversed(self.patches):
            p.stop()
        self.patches = []

    # ---- scripted operator -----------------------------------------------------------------------------------------------------------
    def _confirm(self, parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, **_layout):
        self.dialogs.append(('confirm', title, heading, [s if isinstance(s, str) else ' '.join(s) for s in steps]))
        if self.on_confirm is not None:
            r = self.on_confirm(title, heading, steps, facts)
            if r is not None:
                return r
        return True

    def _box(self, kind, args):
        self.dialogs.append(('box', kind, args[0] if args else '', args[1] if len(args) > 1 else ''))
        return self.box_answer[kind] if kind in self.box_answer else True

    def _ask_reading(self, parent, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                     limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None):
        self.dialogs.append(('reading', p['id'], mode, device))
        if mode == 'numeric':
            val = self.readings.get(p['id'])
            if val is None and self.default_reading:
                val = self.default_reading(p)
            if callable(val):
                val = val(p)
            if val is None:
                return dict(action='stop', text='', ann=False, yes=None)
            if validate:
                validate(val)
            return dict(action='record', text=val, ann=False, yes=None)
        ans = self.readings.get(p['id'], True)
        return dict(action='record', text='', ann=False, yes=bool(ans))

    def _ask_readings(self, parent, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                      source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading=''):
        """The run-queue reading window: one box per meter.  The scripted operator types queue_readings[(asset, point id)], else the per-point
        reading / default reading of a single-meter run, else (virtual bench) presses 'Fill with a simulated reading'."""
        self.dialogs.append(('readings', p['id'], [m[0] for m in meters]))
        action = self.queue_action.get(p['id'])
        if action:
            return dict(action=action, texts={}, no_reading=[])
        texts, none = {}, []
        for idx, (key, _label, _serial) in enumerate(meters):
            if (key, p['id']) in self.queue_no_reading:
                texts[key] = None
                none.append(key)
                continue
            val = self.queue_readings.get((key, p['id']))
            if val is None and self.queue_default:
                val = self.queue_default(p, key)
            if val is None:
                val = self.readings.get(p['id'])
            if val is None and self.default_reading:
                val = self.default_reading(p)
            if callable(val):
                val = val(p)
            if val is None and self.fill and demo_fill is not None:
                val = demo_fill(idx)
            if val is None:
                return dict(action='stop', texts={}, no_reading=[])
            judge(key, val)
            texts[key] = val
        return dict(action='record', texts=texts, no_reading=none)

    # ---- app -----------------------------------------------------------------------------------------------------------------------------
    def make_app(self, spec, demo=False, io=None, period=None):
        factory = (lambda: io) if io is not None else None
        self.app = rt.DsbApp(self.root, spec, demo=demo, io_factory=factory, period=period)
        self.app.asset.set('A-100')
        self.app.serial.set('S-1')
        if io is not None:
            self.app.io = io
        return self.app

    def pump(self, seconds=60):
        """Run the 'main thread' callbacks until the run is finished (or nothing is left and no worker is alive)."""
        end = time.time() + seconds
        app = self.app
        while time.time() < end:
            if self.root.q:
                fn, a = self.root.q.pop(0)
                fn(*a)
                continue
            workers = [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon]
            if not workers:
                break
            time.sleep(0.002)
        return not app.busy

    def run_all(self):
        self.app.run_all()
        return self.pump()


def typed_nominal(p, offset=0.0):
    """The reading a perfect meter shows for point p, in the display unit, padded by the engine's own rule."""
    text = f'{p["nominal"] / p["factor"] + offset:.9g}'
    return text


def wire(io):
    """Commands written to any instrument, in order: [(instrument label, text)]."""
    return [(inst, text) for _ts, inst, d, text in io.log.entries if d == '>>']
