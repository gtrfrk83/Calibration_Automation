"""Headless harness for the in-run procedure editor (tests/test_beta_live_editor*.py).  Not a test module.

No tkinter is installed where the suite runs, so tests/_tk_stub.py stands in for it and the widget builders (ui_theme / ui_shell) are mocks.
What RUNS is the real code: each engine's App (point loop, reset before the first point, worker threads, recording, checkpoint) against the
simulated benches (drivers/simulated*.py), with procmods_engine's mixin and a throw-away override store.  Only the modal dialogs are scripted.
The Tk windows themselves (procmods_ui) are constructed under the stub only: they have never been looked at on a screen.
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
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub  # noqa: E402

_tk_stub.install()
import tkinter as _tk  # noqa: E402

if not isinstance(getattr(_tk, 'TclError', None), type) or not issubclass(_tk.TclError, BaseException):
    _tk.TclError = type('TclError', (Exception,), {})

import devmode  # noqa: E402
import procmods  # noqa: E402
import procmods_engine  # noqa: E402
import procmods_ui_model as M  # noqa: E402
import ui_shell  # noqa: E402
import ui_theme as ui  # noqa: E402
import labregistry  # noqa: E402


class FakeRoot:
    """tk.Tk() stand-in: after() queues callbacks; EngineHarness.pump runs them on the 'main thread'."""

    def __init__(self):
        self.q = []

    def after(self, _ms, fn=None, *a):
        if fn is not None:
            self.q.append((fn, a))
        return len(self.q)

    def __getattr__(self, name):
        return lambda *a, **k: None


class Env:
    """A throw-away override store, a devmode with an unlocked session (the only way to create overrides), a DevLock for the editor model."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.t = [1000.0]
        clock = lambda: self.t[0]
        self.dm = devmode.DevMode(self.dir / 'devmode.json', clock=clock, wall=clock, iterations=1000)
        self.session = self.dm.set_passphrase('correct horse battery')
        self.lock = M.DevLock(self.dm, clock=clock)
        self.lock.session = self.session
        self.store = procmods.Store(self.dir / 'overrides.sqlite3', devmode=self.dm)

    def close(self):
        self.tmp.cleanup()


class EngineHarness:
    """Patches the UI builders, builds an engine App on a FakeRoot and pumps its main-thread callbacks."""

    def __init__(self, env=None):
        self.env = env or Env()
        self.home = Path(tempfile.mkdtemp())
        self.patches = []
        self.dialogs = []                    # ('confirm', title, heading, steps) / ('box', kind, title, text)
        self.on_confirm = None               # callable(title, heading, steps, facts) -> bool|None
        self.on_point = None                 # callable(app) called on the main thread every time a new point is about to start
        self.box_answer = {}
        self.root = FakeRoot()
        self.app = None

    # ---- environment -------------------------------------------------------------------------------------------------------------
    def start(self, *modules):
        env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.home / 'data'), 'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        env.start()
        self.patches.append(env)
        for obj, name, val in ((ui, 'apply_theme', mock.MagicMock()), (ui, 'fit_window', mock.MagicMock()), (ui, 'polish', mock.MagicMock()),
                               (ui_shell, 'Shell', mock.MagicMock()), (ui_shell, 'results_table', mock.MagicMock()),
                               (ui_shell, 'small_window', mock.MagicMock()), (labregistry, 'attach', mock.MagicMock()),
                               (ui, 'confirm_steps', self._confirm)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.patches.append(p)
        for mod in modules:
            mb = mod.messagebox
            for name in ('askyesno', 'askyesnocancel', 'askokcancel'):
                p = mock.patch.object(mb, name, lambda *a, _n=name, **k: self._box(_n, a), create=True)
                p.start()
                self.patches.append(p)
            for name in ('showinfo', 'showwarning', 'showerror'):
                p = mock.patch.object(mb, name, lambda *a, _n=name, **k: self.dialogs.append(('box', _n, a[0] if a else '', a[1] if len(a) > 1 else '')),
                                      create=True)
                p.start()
                self.patches.append(p)
        return self

    def stop(self):
        for p in reversed(self.patches):
            p.stop()
        self.patches = []
        self.env.close()

    # ---- scripted operator ---------------------------------------------------------------------------------------------------------
    def _confirm(self, parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None):
        self.dialogs.append(('confirm', title, heading, [s if isinstance(s, str) else ' '.join(s) for s in steps]))
        if self.on_confirm is not None:
            r = self.on_confirm(title, heading, steps, facts)
            if r is not None:
                return r
        return True

    def _box(self, kind, args):
        self.dialogs.append(('box', kind, args[0] if args else '', args[1] if len(args) > 1 else ''))
        return self.box_answer.get(kind, True)

    # ---- the editor, as the operator would use it ---------------------------------------------------------------------------------
    def model(self, app=None):
        """A ProcModsModel exactly as procmods_ui.LiveHook.open() builds it (the Context comes from the engine)."""
        app = app or self.app
        ctx = app.pm_live_context()
        ctx.store = self.env.store
        return M.ProcModsModel(ctx, self.env.lock)

    def edit(self, model, reason='fix', scope='run'):
        """Apply whatever is staged in `model` with the same reason; returns the ApplyResult."""
        model.set_scope(scope)
        for kind, target in list(model.drafts):
            model.set_reason(kind, target, reason)
        return model.apply(confirmed=True)

    # ---- pumping ---------------------------------------------------------------------------------------------------------------------
    def pump(self, seconds=60, until=None):
        """Run main-thread callbacks until the run is finished, `until()` is true, or nothing is left and no worker is alive."""
        end = time.time() + seconds
        app = self.app
        while time.time() < end:
            if until is not None and until():
                return True
            if self.root.q:
                fn, a = self.root.q.pop(0)
                fn(*a)
                continue
            workers = [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon]
            if not workers:
                break
            time.sleep(0.002)
        return not getattr(app, 'busy', False)
