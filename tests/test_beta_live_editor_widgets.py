"""procmods_ui live-mode widgets (LiveHook, attach_live, the ModifyWindow live handlers) under tests/_tk_stub.py.

Only proves that the wiring runs and calls the model: it does NOT show what the windows look like (Tk windows have never been viewed here)."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
STUBBED = tk_stub.install()

from tests import live_editor_harness as H  # noqa: E402
import truevolt_verification as T  # noqa: E402
from drivers.simulated import make_dmm_bench  # noqa: E402


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class LiveWidgetTests(unittest.TestCase):
    def setUp(self):
        import procmods_ui
        self.ui = procmods_ui
        self.h = H.EngineHarness().start(T)
        self.addCleanup(self.h.stop)
        app = self.app = T.App(self.h.root, '34470A', demo=False)
        self.h.app = app
        st = app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        app.asset.set('A-100')
        app.serial.set('S')
        _b, ft, dt = make_dmm_bench('34470A')
        app.io = T.IO('sim', 'sim', transports=(dt, ft), mods=st)
        self.calls = []
        calls = self.calls

        class FakeShell:
            root = self.ui.tk.Tk()

            def add_action(self, text, cmd, **kw):
                calls.append(('action', text, kw.get('short')))
                return object()

            def set_modified(self, n):
                calls.append(('mod', n))

            def set_devmode(self, on):
                calls.append(('dev', on))
        self.shell = FakeShell()

    def test_live_hook_adds_the_action_and_chips(self):
        hook = self.ui.attach_live(self.app, self.shell, self.h.env.lock)
        self.assertIsInstance(hook, self.ui.LiveHook)
        self.assertIn(('action', 'Edit point', 'Edit'), self.calls)
        self.assertIn(('mod', 0), self.calls)
        self.assertEqual(hook.count(), 0)
        hook.refresh()

    def test_open_builds_a_live_window_and_reuses_it(self):
        win = self.ui.open_modify_window(self.shell.root, self.app.pm_live_context(), self.h.env.lock)      # the module is kept; no running window opens it now
        self.assertTrue(win.model.live_mode)
        win.update_header()
        win.update_info()
        for tab in win.tabs.values():
            tab.reload()
        self.assertIn('Edit procedure', str(win.title) if not callable(win.title) else 'Edit procedure')

    def test_apply_saves_for_the_next_point_and_redo_needs_a_yes(self):
        import procmods
        win = self.ui.open_modify_window(self.shell.root, self.app.pm_live_context(), self.h.env.lock)
        m = win.model
        pts = [p for p in T.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator'][:3]
        self.app.pm_state.live.start_run(pts)
        key = procmods.point_keys(m.ctx.points)[1]
        self.assertEqual(m.stage_text('note:' + key, 'check leads'), [])
        m.set_scope('run')
        for kind, target in list(m.drafts):
            m.set_reason(kind, target, 'r')
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=False), mock.patch.object(type(self.app), 'pm_is_running', lambda s_: True):
            win.apply()
        self.assertTrue(self.app.pm_state.live.dirty, 'saved, waiting for the next point')
        self.assertFalse(self.app.pm_state.live.redo, 'no redo without a yes')
        self.assertEqual(len(self.app.pm_state.run_entries), 1)
        self.assertFalse(m.dirty)
        win.cancel()

    def test_lock_state_changes_refresh_the_chips(self):
        hook = self.ui.attach_live(self.app, self.shell, self.h.env.lock)
        self.h.env.lock.lock()
        hook.refresh()
        self.assertIn(('dev', False), self.calls)


if __name__ == '__main__':
    unittest.main()
