"""procmods_ui widgets under tests/_tk_stub.py: only proves the module imports and every widget class constructs and runs its handlers
without raising.  It does NOT show what the windows look like: that has never been checked on a real display."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
STUBBED = tk_stub.install()

import devmode
import procmods as pm
import procspec
import procmods_ui_model as M
from tests.test_procmods_ui_model import Base, REG

procspec._fmt = lambda v, u: f'{v:g} {u}'


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class WidgetStubTests(Base):
    def setUp(self):
        super().setUp()
        import procmods_ui
        self.ui = procmods_ui
        self.unlock()

    def test_import_and_construct_window(self):
        win = self.ui.ModifyWindow(object.__new__(self.ui.tk.Tk) if False else self.ui.tk.Tk(), self.model)
        self.assertEqual(sorted(win.tabs), sorted(self.model.visible_tabs()))
        for tab in win.tabs.values():
            tab.reload()
        win.update_header()
        win.update_buttons()

    def test_handlers_do_not_raise(self):
        win = self.ui.ModifyWindow(self.ui.tk.Tk(), self.model)
        win.scope.set('model')
        win.scope_changed()
        self.assertEqual(self.model.scope, 'model')
        win.apply()                                          # nothing staged
        win.cancel()
        self.model.stage_param('settle', 5)
        win.apply()                                          # reason missing: message, no write
        self.assertIn('reason', win.message.get())
        self.assertEqual(self.store.entries(), [])
        win.lock.lock()
        win.refresh()
        self.assertFalse(self.model.editable)

    def test_unlock_dialog_constructs_and_submits(self):
        self.lock.lock()
        dlg = self.ui.UnlockDialog(self.ui.tk.Tk(), self.lock)
        dlg.pw.set('correct horse')
        dlg.submit()
        self.assertTrue(dlg.ok)
        self.assertEqual(dlg.pw.get(), '')                   # the entry is wiped after use

    def test_first_use_dialog(self):
        dm = devmode.DevMode(self.dir / 'fresh.json', clock=self.clock, wall=self.clock, iterations=1000)
        lock = M.DevLock(dm)
        dlg = self.ui.UnlockDialog(self.ui.tk.Tk(), lock)
        dlg.pw.set('long enough pw'); dlg.pw2.set('different')
        dlg.submit()
        self.assertFalse(dlg.ok)
        dlg.pw.set('long enough pw'); dlg.pw2.set('long enough pw')
        dlg.submit()
        self.assertTrue(dlg.ok)
        self.assertTrue(lock.unlocked)

    def test_shell_hook_and_chips(self):
        calls = []

        class FakeShell:
            root = self.ui.tk.Tk()

            def add_action(self, text, cmd, **kw):
                calls.append(('action', text))
                return object()

            def set_modified(self, n):
                calls.append(('mod', n))

            def set_devmode(self, on):
                calls.append(('dev', on))
        hook = self.ui.attach_to_shell(FakeShell(), lambda: self.ctx, self.lock)
        self.assertIn(('action', 'Modify procedure'), calls)
        self.assertIn(('mod', 0), calls)
        self.assertIn(('dev', True), calls)
        self.model.stage_param('settle', 5); self.model.set_reason('param', 'settle', 'r'); self.model.apply()
        hook.refresh()
        self.assertEqual(calls[-2], ('mod', 1))

    def test_real_shell_chips_under_stub(self):
        import ui_shell
        sh = object.__new__(ui_shell.Shell)
        sh.chip_frame = self.ui.tk.Frame()
        self.assertIsNone(sh.set_modified(0))                # nothing when unmodified
        self.assertIsNotNone(sh.set_modified(3))
        sh.set_modified(0)
        sh.set_devmode(True); sh.set_devmode(False)

    def test_manager_window(self):
        win = self.ui.open_manager_changes(self.ui.tk.Tk(), '34465A', self.store, self.lock)
        self.assertEqual(list(win.tabs), ['Changes'])

    def test_every_tab_class_has_a_kind_matching_the_model(self):
        for name, cls in self.ui.TAB_CLASSES.items():
            self.assertIn(name, M.TABS)


class ModelCountsTests(Base):
    def test_model_counts(self):
        self.unlock()
        m = self.model
        m.set_scope('model')
        m.stage_param('settle', 8); m.set_reason('param', 'settle', 'r'); m.apply(confirmed=True)
        self.assertEqual(M.model_counts(self.store), {'34465a': 1})
        self.assertEqual(M.model_counts(None), {})


if __name__ == '__main__':
    unittest.main()
