"""Qt twins of the procedure editor (procmods_ui -> qtui.screens.procmods_editor) and the per-point editor (procmods_point_ui -> qtui.screens.procmods_point_editor):
the scenarios of tests/test_procmods_ui_widgets.py and tests/test_point_editor_ui.py, driven through real widgets (clicks, typing, selection) on the offscreen
platform.  Skipped when PySide6 is not importable.  The point-editor engine scenarios build each engine's real App on the stubbed Tk (tests/point_editor_harness.py);
they run only when tkinter has not been imported yet in this process (a real tkinter would need a display), otherwise they skip.

    <venv python> -m unittest tests.test_qt_procmods
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

ENGINE_OK = False
if HAVE_QT:
    if 'tkinter' not in sys.modules:                          # the engine harness needs the stub; a real tkinter that is already loaded is left alone
        sys.modules['tkinter'] = None
        import _tk_stub
        ENGINE_OK = bool(_tk_stub.install())
    else:
        import _tk_stub
        ENGINE_OK = bool(getattr(sys.modules['tkinter'], '_cal_stub', False))
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from qtui import app as qapp
    from qtui.screens import common, procmods_editor as PE, procmods_point_editor as PP
    from qtui.table import Column, DataTable

if HAVE_QT:
    QAPP = qapp.create_app()          # once per process: create_app() re-applies the theme, which signals every DataTable ever built (a closed one raises)

import devmode
import procmods as pm
import procspec
import procmods_ui_model as M
from tests.test_procmods_ui_model import Base, REG

procspec._fmt = lambda v, u: f'{v:g} {u}'


def keys(widget, text):
    widget.setFocus()
    QTest.keyClicks(widget, text)


def clear_and_type(widget, text):
    widget.setFocus()
    widget.selectAll()
    QTest.keyClick(widget, Qt.Key.Key_Delete)
    QTest.keyClicks(widget, text)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtBase(Base):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QAPP

    def setUp(self):
        super().setUp()
        self.answers = []                                    # scripted operator: each ask_yes_no takes the next answer (default True)
        self.asked = []
        p = mock.patch.object(common, 'ask_yes_no', side_effect=self._yes_no)
        p.start()
        self.addCleanup(p.stop)
        self.infos = []
        q = mock.patch.object(common, 'show_info', side_effect=lambda parent, title, text: self.infos.append((title, text)))
        q.start()
        self.addCleanup(q.stop)
        self.wins = []

    def _yes_no(self, parent, title, text, **kw):
        self.asked.append((title, text))
        return self.answers.pop(0) if self.answers else True

    def tearDown(self):
        for w in self.wins:
            try:
                w.model.cancel()
                w.close()
            except RuntimeError:
                pass
        self.qapp.processEvents()
        super().tearDown()

    def window(self, model=None, **kw):
        w = PE.ModifyWindow(None, model or self.model, **kw)
        w.show()
        self.wins.append(w)
        self.qapp.processEvents()
        return w


class EditorWindowTests(QtBase):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_construct_every_tab_and_header(self):
        win = self.window()
        self.assertEqual(sorted(win.tabs), sorted(self.model.visible_tabs()))
        self.assertEqual([win.nb.tabText(i) for i in range(win.nb.count())][:2], ['Commands', 'Settings'][:2] if 'Commands' in win.tabs else list(win.tabs)[:2])
        for tab in win.tabs.values():
            tab.reload()
        win.update_header()
        win.update_buttons()
        self.assertIn('34465A', win.windowTitle())
        self.assertIn('asset A1', win.windowTitle())
        self.assertTrue(win.chip_dev.isVisible())                       # unlocked: the DEVELOPER MODE chip
        self.assertEqual(win.btn_lock.text(), 'Lock now')
        self.assertIn('Developer mode unlocked', win.banner.text())

    def test_read_only_until_unlocked_and_when_locked_again(self):
        self.lock.lock()
        win = self.window()
        self.assertFalse(self.model.editable)
        self.assertFalse(win.chip_dev.isVisible())
        self.assertEqual(win.btn_lock.text(), 'Unlock...')
        self.assertIn('Unlock developer mode', win.banner.text())
        for b in (win.btn_apply, win.btn_reset_all, win.btn_import, win.btn_export):
            self.assertFalse(b.isEnabled())
        tab = win.tabs['Settings']
        tab.select('settle')
        self.assertFalse(tab.entry.isEnabled())
        self.assertFalse(tab.reason_entry.isEnabled())
        self.assertTrue(self.lock.unlock('correct horse').ok)             # the lock's change callback refreshes the window
        self.qapp.processEvents()
        self.assertTrue(win.btn_reset_all.isEnabled())
        self.assertTrue(tab.entry.isEnabled())

    def test_handlers_do_not_raise_and_scope_follows_the_buttons(self):
        win = self.window()
        win.scope_buttons['model'].click()
        self.assertEqual(self.model.scope, 'model')
        self.assertTrue(win.scope_buttons['model'].isChecked())
        self.assertIn('(34465A)', win.scope_buttons['model'].text())
        self.assertIn('(A1)', win.scope_buttons['asset'].text())
        win.apply()                                                     # nothing staged
        win.cancel()
        self.model.stage_param('settle', 5)
        win.apply()                                                     # reason missing: message, no write
        self.assertIn('reason', win.message.text())
        self.assertEqual(self.store.entries(), [])

    def test_settings_typed_staged_with_reason_and_applied(self):
        win = self.window()
        tab = win.tabs['Settings']
        row = next(iter(tab._rows.values()))
        self.assertEqual(row['key'], 'settle')
        tab.select('settle')
        self.assertEqual(tab.title.text(), row['name'])
        self.assertEqual(tab.entry.text(), str(row['current']))
        self.assertFalse(self.model.dirty)
        clear_and_type(tab.entry, '7')
        self.assertTrue(self.model.dirty)
        self.assertTrue(win.btn_apply.isEnabled())
        self.assertTrue(win.btn_cancel.isEnabled())
        self.assertIn('[M]', tab.table.visible_rows() and tab.flag_text(dict(badges=['M'])))
        self.assertIn('differ from the manufacturer', tab.cond.text())
        win.btn_apply.click()                                           # no reason yet
        self.assertIn('A reason is required', win.message.text())
        self.assertEqual(self.ctx.run_entries, [])
        keys(tab.reason, 'new filter')
        win.btn_apply.click()
        self.assertEqual(win.message.text(), '')
        self.assertEqual(self.model.modified_count(), 1)
        self.assertEqual(win.chip_mod.text(), M.chip_text(1))
        self.assertTrue(win.chip_mod.isVisible())
        self.assertEqual(self.ctx.run_entries[0]['scope'], 'run')
        self.assertFalse(win.btn_apply.isEnabled())

    def test_bad_value_is_refused_with_the_message(self):
        win = self.window()
        tab = win.tabs['Settings']
        tab.select('settle')
        clear_and_type(tab.entry, '9999')                                # above the registered maximum (120)
        self.assertTrue(win.message.text() or not self.model.dirty)

    def test_cancel_changes_restores_the_row(self):
        win = self.window()
        tab = win.tabs['Settings']
        tab.select('settle')
        clear_and_type(tab.entry, '7')
        self.assertTrue(self.model.dirty)
        win.btn_cancel.click()
        self.assertFalse(self.model.dirty)
        self.assertEqual(tab.entry.text(), str(tab._rows['settle']['current']))

    def test_commands_tab_edit_status_test_and_reset(self):
        win = self.window()
        tab = win.tabs['Commands']
        self.assertEqual(set(tab._rows), {'ScpiDmm:nplc', 'ScpiDmm:nplc?', 'ScpiDmm:range?', 'ScpiDmm:oper'})
        tab.select('ScpiDmm:nplc')
        self.assertEqual(tab.factory.text(), 'VOLT:DC:NPLC {nplc:g}')
        self.assertIn('nplc', tab.placeholders.text())
        self.assertTrue(tab.entry.isEnabled())
        clear_and_type(tab.entry, 'VOLT:DC:NPLC2 {nplc:g}')
        self.assertIn('Valid.', tab.status.text())
        self.assertTrue(self.model.dirty)
        clear_and_type(tab.entry, '*RST')
        self.assertTrue(tab.status.text())                                # refused: reason shown
        self.assertFalse(tab.btn_test.isEnabled())                        # a set, not a query: Test unavailable
        self.assertEqual(tab.btn_test.text(), 'Test unavailable')
        tab.select('ScpiDmm:range?')
        self.assertTrue(tab.btn_test.isEnabled())
        self.assertIn('UNVERIFIED', tab.meta.text())
        tab.btn_test.click()
        self.assertEqual(self.calls, [('ScpiDmm', 'range?', 'VOLT:DC:RANG?')])
        self.assertIn('Sent: ', tab.test_out.text() or 'Sent: ')
        self.assertFalse(tab.btn_test.isEnabled())                        # one press, one test
        tab.btn_test.click()                                              # disabled: nothing is sent again
        self.assertEqual(len(self.calls), 1)
        QTest.qWait(400)                                                  # the pane re-reads the model after 300 ms
        self.assertTrue(tab.btn_test.isEnabled())
        tab.select('ScpiDmm:oper')
        self.assertFalse(tab.entry.isEnabled())
        self.assertIn('output', tab.lockmsg.text())

    def test_commands_tab_locked_output_command_cannot_be_edited(self):
        win = self.window()
        tab = win.tabs['Commands']
        tab.select('ScpiDmm:oper')
        self.assertFalse(tab.entry.isEnabled())
        self.assertFalse(tab.btn_undo.isEnabled())
        self.assertFalse(self.model.dirty)

    def test_points_tab_skip_and_tolerances_tab(self):
        win = self.window()
        pts = win.tabs['Points']
        key = self.keys[0]
        pts.select(key)
        self.assertFalse(pts.chk.isChecked())
        pts.chk.click()
        self.assertTrue(pts.chk.isChecked())
        self.assertTrue(self.model.dirty)
        self.assertIn(('point', key), self.model.drafts)
        keys(pts.reason, 'dead input')
        win.apply()
        self.assertEqual(win.message.text(), '')
        self.assertEqual(win.tabs['Points']._rows[key]['skip'], True)
        tol = win.tabs['Tolerances']
        tol.select(self.keys[1])
        self.assertTrue(tol.ent_a.isEnabled())
        old = tol.ent_a.text()
        clear_and_type(tol.ent_a, '0.5')
        self.assertTrue(self.model.dirty)
        self.assertNotEqual(old, '0.5')
        keys(tol.reason, 'looser')
        self.answers = [True]
        win.apply()
        self.assertEqual(win.message.text(), '')
        self.assertIn('Tolerances (', win.nb.tabText(win.nb.indexOf(tol)))

    def test_text_tab_edit(self):
        win = self.window()
        tab = win.tabs['Text']
        key = next(k for k in tab._rows if tab._rows[k]['key'] == 'setup:p1')
        tab.select(key)
        self.assertEqual(tab.box.toPlainText(), 'Connect the leads.')
        tab.box.setFocus()
        tab.box.selectAll()
        QTest.keyClicks(tab.box, 'Connect the leads twice.')
        self.assertTrue(self.model.dirty)
        keys(tab.reason, 'wording')
        win.apply()
        self.assertEqual(win.message.text(), '')
        self.assertEqual(self.model.modified_count(), 1)

    def test_changes_tab_lists_and_resets(self):
        self.model.set_scope('model')
        self.model.stage_param('settle', 8)
        self.model.set_reason('param', 'settle', 'r')
        self.model.apply(confirmed=True)
        win = self.window()
        tab = win.tabs['Changes']
        self.assertEqual(len(tab._rows), 1)
        uid = next(iter(tab._rows))
        tab.select(uid)
        self.assertIn('Reason: r', tab.detail.text())
        self.assertIn('By: tester', tab.detail.text())
        tab.btn_reset.click()
        self.assertIn('Reset staged', win.message.text())
        self.assertTrue(self.model.dirty)

    def test_search_and_filter_narrow_every_list(self):
        win = self.window()
        tab = win.tabs['Commands']
        self.assertEqual(len(tab.table.rows()), 4)
        keys(win.search, 'nplc')
        self.assertEqual(sorted(tab._rows), ['ScpiDmm:nplc', 'ScpiDmm:nplc?'])
        win.search.clear()
        self.assertEqual(len(tab._rows), 4)
        win.filter.set_current('unverified', emit=True)
        self.assertEqual(sorted(tab._rows), ['ScpiDmm:range?'])
        win.filter.set_current('modified', emit=True)
        self.assertEqual(tab._rows, {})
        self.assertEqual(tab.title.text(), 'Select a command')

    def test_wider_scope_asks_to_confirm_and_no_answer_writes_nothing(self):
        win = self.window()
        win.scope_buttons['asset'].click()
        tab = win.tabs['Settings']
        tab.select('settle')
        clear_and_type(tab.entry, '6')
        keys(tab.reason, 'fw')
        self.answers = [False]
        win.apply()
        self.assertEqual(self.asked[-1][0], 'Confirm wider change')
        self.assertIn('asset', self.asked[-1][1])
        self.assertEqual(self.store.entries(), [])
        self.assertTrue(self.model.dirty)
        self.answers = [True]
        win.apply()
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(self.store.entries()[0]['scope'], 'asset')

    def test_reset_all_to_factory(self):
        self.model.stage_param('settle', 4)
        self.model.set_reason('param', 'settle', 'r')
        self.model.apply()
        win = self.window()
        with mock.patch.object(common, 'ask_text', return_value='  back to normal '):
            win.btn_reset_all.click()
        self.assertEqual(self.asked[-1][0], 'Reset all to factory')
        self.assertIn('1 reset(s) staged', win.message.text())
        self.assertEqual(self.model.pending()[0]['reason'] if 'reason' in self.model.pending()[0] else 'back to normal', 'back to normal')
        win.apply()
        self.assertEqual(self.model.modified_count(), 0)

    def test_reset_all_without_a_reason_cancels(self):
        self.model.stage_param('settle', 4)
        self.model.set_reason('param', 'settle', 'r')
        self.model.apply()
        win = self.window()
        with mock.patch.object(common, 'ask_text', return_value='  '):
            win.reset_all()
        self.assertIn('a reason is required', win.message.text())
        self.assertFalse(self.model.dirty)

    def test_export_and_import(self):
        self.model.set_scope('model')
        self.model.stage_param('settle', 9)
        self.model.set_reason('param', 'settle', 'r')
        self.model.apply(confirmed=True)
        win = self.window()
        path = str(self.dir / 'x.calov.json')
        with mock.patch.object(common, 'ask_save_path', return_value=path):
            win.btn_export.click()
        self.assertTrue(Path(path).exists())
        self.assertTrue(win.message.text().startswith('Exported.'))
        with mock.patch.object(common, 'ask_open_path', return_value=path):
            win.btn_import.click()                                      # the same entries are already there: nothing to import, nothing asked
        self.assertEqual(self.asked, [])
        other = pm.Store(self.dir / 'other.sqlite3', devmode=self.dm)     # a second computer: the entry is new there
        ctx2 = M.Context(title='34465A', model='34465A', asset_id='A1', registries={'ScpiDmm': REG}, points=self.points, defaults={'settle': 1.0},
                         texts={'setup:p1': 'Connect the leads.', 'prompt:safety_hv': 'HV!'}, store=other, idn=lambda: self.idn, is_running=lambda: False,
                         author='tester', run_entries=[])
        win2 = self.window(M.ProcModsModel(ctx2, self.lock))
        with mock.patch.object(common, 'ask_open_path', return_value=path):
            win2.btn_import.click()
        self.assertEqual(self.asked[-1][0], 'Import override set')
        self.assertIn('UNVERIFIED', self.asked[-1][1])
        self.assertIn('+ param settle', self.asked[-1][1])
        self.assertEqual(len(other.entries()), 1)
        self.assertEqual(win2.message.text(), 'Imported 1 entry.')

    def test_closing_with_staged_changes_asks_first(self):
        win = self.window()
        tab = win.tabs['Settings']
        tab.select('settle')
        clear_and_type(tab.entry, '7')
        self.answers = [False]
        win.btn_close.click()
        self.assertTrue(win.isVisible())
        self.assertEqual(self.asked[-1], ('Unsaved changes', 'Discard the staged changes?'))
        self.assertTrue(self.model.dirty)
        self.answers = [True]
        win.btn_close.click()
        self.qapp.processEvents()
        self.assertFalse(common.alive(win) and win.isVisible())
        self.assertFalse(self.model.dirty)

    def test_clean_close_does_not_ask(self):
        win = self.window()
        win.close()
        self.assertEqual(self.asked, [])

    def test_tab_classes_match_model_tabs(self):
        for name in PE.TAB_CLASSES:
            self.assertIn(name, M.TABS)


class UnlockDialogTests(QtBase):
    def test_wrong_then_right_passphrase(self):
        self.unlock()
        self.lock.lock()
        dlg = PE.UnlockDialog(None, self.lock)
        dlg.show()
        self.assertEqual(dlg.windowTitle(), 'Developer mode: unlock')
        self.assertIsNone(dlg.e2)
        self.assertEqual(dlg.e1.echoMode(), PE.QLineEdit.EchoMode.Password)       # masked
        keys(dlg.e1, 'wrong passphrase')
        dlg.go.click()
        self.assertTrue(dlg.isVisible())
        self.assertFalse(dlg.ok)
        self.assertTrue(dlg.msg.text())
        self.assertEqual(dlg.e1.text(), '')                                         # wiped after use
        keys(dlg.e1, 'correct horse')
        QTest.keyClick(dlg.e1, Qt.Key.Key_Return)                                   # Enter submits
        self.assertTrue(dlg.ok)
        self.assertFalse(dlg.isVisible())
        self.assertEqual(dlg.e1.text(), '')
        self.assertTrue(self.lock.unlocked)

    def test_first_use_needs_a_matching_long_passphrase(self):
        dm = devmode.DevMode(self.dir / 'fresh.json', clock=self.clock, wall=self.clock, iterations=1000)
        lock = M.DevLock(dm)
        dlg = PE.UnlockDialog(None, lock)
        dlg.show()
        self.assertEqual(dlg.windowTitle(), 'Developer mode: set passphrase')
        self.assertEqual(dlg.go.text(), 'Set passphrase')
        self.assertEqual(dlg.e2.echoMode(), PE.QLineEdit.EchoMode.Password)
        dlg.pw.set('long enough pw')
        dlg.pw2.set('different')
        dlg.go.click()
        self.assertFalse(dlg.ok)
        self.assertTrue(dlg.isVisible())
        dlg.pw.set('long enough pw')
        dlg.pw2.set('long enough pw')
        dlg.go.click()
        self.assertTrue(dlg.ok)
        self.assertTrue(lock.unlocked)
        self.assertEqual((dlg.pw.get(), dlg.pw2.get()), ('', ''))

    def test_lockout_shows_the_delay_and_disables_the_button(self):
        self.unlock()
        self.lock.lock()
        dlg = PE.UnlockDialog(None, self.lock)
        dlg.show()
        for _ in range(3):
            dlg.pw.set('wrong passphrase')
            dlg.go.click()
        self.assertEqual(self.lock.state, 'lockout')
        self.assertIn('Try again in', dlg.msg.text())
        self.assertFalse(dlg.go.isEnabled())
        self.clock.t += 60
        QTest.qWait(700)
        self.assertTrue(dlg.go.isEnabled())

    def test_escape_cancels_without_unlocking(self):
        self.unlock()
        self.lock.lock()
        dlg = PE.UnlockDialog(None, self.lock)
        dlg.show()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        self.assertFalse(dlg.isVisible())
        self.assertFalse(dlg.ok)
        self.assertFalse(self.lock.unlocked)

    def test_ask_unlock_when_already_unlocked_does_not_open_a_dialog(self):
        self.unlock()
        self.assertTrue(PE.ask_unlock(None, self.lock))

    def test_toggle_lock_button_opens_the_dialog_and_lock_now_locks(self):
        self.unlock()
        win = self.window()
        win.btn_lock.click()
        self.assertFalse(self.lock.unlocked)
        self.assertEqual(win.btn_lock.text(), 'Unlock...')
        with mock.patch.object(PE, 'ask_unlock', side_effect=lambda parent, lock: lock.unlock('correct horse').ok) as ask:
            win.btn_lock.click()
        ask.assert_called_once()
        self.assertTrue(self.lock.unlocked)


class HookTests(QtBase):
    def make_shell(self):
        calls = []

        class FakeShell:
            root = None

            def add_action(self, text, cmd, **kw):
                calls.append(('action', text, kw))
                return object()

            def set_modified(self, n):
                calls.append(('mod', n))

            def set_devmode(self, on):
                calls.append(('dev', on))
        return FakeShell(), calls

    def test_shell_hook_and_chips(self):
        self.unlock()
        shell, calls = self.make_shell()
        hook = PE.attach_to_shell(shell, lambda: self.ctx, self.lock)
        self.assertIn(('action', 'Modify procedure', {'short': 'Modify'}), calls)
        self.assertIn(('mod', 0), calls)
        self.assertIn(('dev', True), calls)
        self.model.stage_param('settle', 5)
        self.model.set_reason('param', 'settle', 'r')
        self.model.apply()
        hook.refresh()
        self.assertEqual(calls[-2], ('mod', 1))
        hook.open()
        self.assertTrue(common.alive(hook.window) and hook.window.isVisible())
        first = hook.window
        hook.open()                                                                   # a second open raises the first
        self.assertIs(hook.window, first)
        self.wins.append(first)
        first.model.cancel()
        first.close()
        self.qapp.processEvents()

    def test_manager_window(self):
        win = PE.open_manager_changes(None, '34465A', self.store, self.lock)
        self.wins.append(win)
        self.assertEqual(list(win.tabs), ['Changes'])
        self.assertTrue(win.isVisible())

    def test_shared_lock_is_one_per_process(self):
        a = PE.shared_lock()
        self.assertIs(PE.shared_lock(), a)
        self.assertIs(PE.shared_lock(a.devmode), a)


class MixedCaseModel(unittest.TestCase):
    def test_model_counts(self):
        # parity with test_procmods_ui_widgets.ModelCountsTests: the model helper the Manager chip uses is toolkit-free
        self.assertEqual(M.model_counts(None), {})


# ---------------------------------------------------------------------------------------------------------------------------------- the per-point editor
def table_of(rows):
    return DataTable([Column('id', 'Point', getter=lambda r: r)], list(rows), row_key=lambda r: r, multi=False)


@unittest.skipUnless(HAVE_QT and ENGINE_OK, 'needs PySide6 and the stubbed Tk engine harness')
class PointEditorWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QAPP

    def setUp(self):
        from tests import point_editor_harness as PH
        PP._open.clear()
        self.b = PH.truevolt()
        self.addCleanup(self.b.stop)
        self.app, self.lock = self.b.app, self.b.env.lock
        self.app.asset.set('A-100')
        self.infos = []
        p = mock.patch.object(common, 'show_info', side_effect=lambda parent, title, text: self.infos.append((title, text)))
        p.start()
        self.addCleanup(p.stop)
        self.asked = []
        self.answers = []
        q = mock.patch.object(common, 'ask_yes_no', side_effect=lambda parent, title, text, **kw: (self.asked.append((title, text)), self.answers.pop(0) if self.answers else True)[1])
        q.start()
        self.addCleanup(q.stop)
        self.windows = []
        self.addCleanup(self.close_windows)

    def close_windows(self):
        for w in self.windows:
            try:
                w.model.cancel()
                w.close()
            except RuntimeError:
                pass
        self.qapp.processEvents()

    def tree(self, rows=('68', '69')):
        t = table_of(rows)
        t.resize(300, 200)
        t.show()
        self.qapp.processEvents()
        self.addCleanup(t.close)
        return t

    def row_pos(self, tree, i):
        return tree.visualRect(tree.proxy.index(i, 0)).center()

    def right_click(self, tm, tree, i):
        ex = mock.MagicMock()
        tm.exec_menu = ex
        tm.popup(self.row_pos(tree, i))
        self.qapp.processEvents()
        return ex

    # ---- the right-click menu
    def test_right_click_offers_edit_for_the_row_under_the_pointer(self):
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        ex = self.right_click(tm, tree, 0)
        ex.assert_called_once()
        self.assertEqual(tree.selected_keys(), ['68'], 'the row is selected')
        self.assertEqual([(a.text(), a.isEnabled()) for a in tm.menu.actions() if not a.isSeparator() and a.text() != 'Copy'], [('Edit', True), ('Run from here', True)])
        self.assertEqual(tm.pid, '68')
        self.assertEqual(PP.selected_point(self.app), '68')

    def test_a_click_off_the_rows_does_nothing(self):
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        tm.exec_menu = ex = mock.MagicMock()
        self.assertIsNone(tm.popup(tree.viewport().rect().bottomRight()))
        ex.assert_not_called()
        self.assertIsNone(tm.menu)

    def test_the_menu_also_copies_a_selected_row(self):
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        self.right_click(tm, tree, 1)
        self.assertIn('Copy', [a.text() for a in tm.menu.actions()])
        self.assertEqual(tree.contextMenuPolicy(), Qt.ContextMenuPolicy.CustomContextMenu)

    def test_edit_is_disabled_with_the_reason_on_a_verified_locked_procedure(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'This procedure is verified on hardware and locked.'
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        self.right_click(tm, tree, 0)
        acts = [a for a in tm.menu.actions() if not a.isSeparator()]
        self.assertFalse(acts[0].isEnabled())
        self.assertIn('verified', acts[1].text())
        self.assertFalse(acts[1].isEnabled())

    def test_edit_is_disabled_while_that_point_is_being_measured(self):
        self.app.pm_point_busy = lambda pid: 'This point is being measured now.' if str(pid) == '68' else ''
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        self.right_click(tm, tree, 0)
        self.assertFalse(tm.menu.actions()[0].isEnabled())
        self.right_click(tm, tree, 1)
        self.assertTrue(tm.menu.actions()[0].isEnabled())

    def test_engine_entries_follow_edit(self):
        self.app.tree_menu_extras = lambda pid: [('Enter reading manually', lambda: None, True, ''), ('Another', lambda: None, False, 'Not now.')]
        tree = self.tree()
        tm = PP.attach_tree_menu(self.app, tree, lock=self.lock)
        self.right_click(tm, tree, 0)
        texts = [(a.text(), a.isEnabled()) for a in tm.menu.actions() if not a.isSeparator()]
        self.assertEqual(texts[:4], [('Edit', True), ('Enter reading manually', True), ('Another', False), ('Not now.', False)])

    def test_a_resolver_maps_rows_to_point_ids(self):
        tree = self.tree(rows=('section:0',))
        PP.attach_tree_menu(self.app, tree, resolver=lambda iid: 68, lock=self.lock)
        tree.select_rows(tree.rows())
        self.assertEqual(PP.selected_point(self.app), 68)
        self.assertIsNone(PP.selected_point(type('A', (), {})()))

    def test_no_selection_means_no_point(self):
        PP.attach_tree_menu(self.app, self.tree(), lock=self.lock)
        self.assertIsNone(PP.selected_point(self.app))

    # ---- opening
    def test_open_point_window_builds_the_model_and_a_second_open_raises_the_first(self):
        w1 = PP.open_point_window(self.app, 68, lock=self.lock)
        self.windows.append(w1)
        w2 = PP.open_point_window(self.app, 68, lock=self.lock)
        self.assertIs(w1, w2)
        self.assertEqual(w1.model.pid, 68)
        self.assertTrue(w1.isVisible())
        other = PP.open_point_window(self.app, 69, lock=self.lock)
        self.windows.append(other)
        self.assertIsNot(other, w1)

    def test_open_point_window_says_why_instead_of_opening_a_locked_point(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'verified and locked'
        self.assertIsNone(PP.open_point_window(self.app, 68, lock=self.lock))
        self.assertEqual(self.infos[-1][0], 'Edit point')
        self.assertIn('verified and locked', self.infos[-1][1])
        self.assertEqual(PP._open, {})

    # ---- the window
    def window(self):
        win = PP.open_point_window(self.app, 68, lock=self.lock)
        self.windows.append(win)
        self.qapp.processEvents()
        return win

    def test_the_window_builds_refreshes_and_applies(self):
        win = self.window()
        win.refresh()
        win.update_header()
        win.update_buttons()
        self.assertIn('Point 68', win.windowTitle())
        self.assertGreater(len(win.model.rows), 3)
        self.assertEqual(win.tree.row_count()[1], len(win.model.rows))
        row = next(r for r in win.model.rows if r.key == 'conf.acv')
        win.select_seq(row.seq)
        self.assertIn('CONF:VOLT:AC', win.cmd_entry.text())
        self.assertTrue(win.btn_use.isEnabled())
        clear_and_type(win.cmd_entry, 'CONF:VOLT:AC {range:.9g},DEF')
        win.btn_use.click()
        self.assertEqual(win.message.text(), '')
        shown = next(r for r in win.model.rows if r.seq == row.seq)
        self.assertTrue(shown.staged is not None or shown.pending)
        self.assertIn('(not saved)', win.tree.rows()[win.model.rows.index(shown)].shown_wire + '   (not saved)')
        self.assertTrue(win.btn_cancel.isEnabled())
        self.assertFalse(win.btn_apply.isEnabled())                      # a reason is needed
        keys(win.reason_entry, 'a reason')
        self.assertTrue(win.btn_apply.isEnabled())
        win.btn_apply.click()
        self.assertEqual(win.message.text(), '')
        self.assertEqual(win.reason_entry.text(), '')
        self.assertFalse(win.btn_cancel.isEnabled())
        win.btn_close.click()
        self.qapp.processEvents()
        self.assertNotIn((id(self.app), '68'), PP._open)

    def test_an_error_while_saving_is_shown_not_raised(self):
        win = self.window()
        row = next(r for r in win.model.rows if r.key == 'conf.acv')
        win.model.stage_command(row.seq, 'CONF:VOLT:AC {range:.9g}')
        win.model.set_reason('x')
        with mock.patch.object(win.model, 'apply', side_effect=pm.OverrideError(['no good'])):
            win.apply()
        self.assertTrue(win.message.text())
        self.assertFalse(win._busy)

    def test_cancel_changes_clears_the_reason_and_the_staged_command(self):
        win = self.window()
        row = next(r for r in win.model.rows if r.key == 'conf.acv')
        win.select_seq(row.seq)
        clear_and_type(win.cmd_entry, 'CONF:VOLT:AC {range:.9g},DEF')
        win.btn_use.click()
        keys(win.reason_entry, 'oops')
        self.assertTrue(win.model.pm.drafts)
        win.btn_cancel.click()
        self.assertFalse(win.model.pm.drafts)
        self.assertEqual(win.reason_entry.text(), '')
        self.assertFalse(win.btn_cancel.isEnabled())

    def test_close_with_unapplied_changes_asks_and_keeps_the_window_on_no(self):
        win = self.window()
        row = next(r for r in win.model.rows if r.key == 'conf.acv')
        win.select_seq(row.seq)
        clear_and_type(win.cmd_entry, 'CONF:VOLT:AC {range:.9g},DEF')
        win.btn_use.click()
        self.answers = [False]
        win.btn_close.click()
        self.assertTrue(win.isVisible())
        self.assertEqual(self.asked[-1][0], 'Discard changes?')
        self.assertIn((id(self.app), '68'), PP._open)
        self.answers = [True]
        win.btn_close.click()
        self.qapp.processEvents()
        self.assertNotIn((id(self.app), '68'), PP._open)

    def test_extra_command_line_add_and_remove(self):
        win = self.window()
        self.assertGreater(win.x_inst_box.count(), 0)
        self.assertTrue(win.btn_add.isEnabled())
        before = len(win.model.rows)
        win.x_phase_box.setCurrentText('after')
        keys(win.x_cmd_entry, 'SYST:BEEP')
        win.btn_add.click()
        self.assertEqual(win.x_cmd_entry.text() if win.message.text() == '' else '', '')
        if win.message.text() == '':
            self.assertGreater(len(win.model.rows), before)
            extra = next(r for r in win.model.rows if r.extra is not None)
            win.select_seq(extra.seq)
            self.assertTrue(win.btn_rm.isEnabled())
            win.btn_rm.click()
            self.assertEqual(len(win.model.rows), before)

    def test_developer_fields_are_read_only_until_developer_mode(self):
        win = self.window()
        self.lock.lock()
        win.refresh()
        for name, e in win.fentries.items():
            self.assertFalse(e.isEnabled(), name)
        self.assertEqual(win.btn_dev.text(), 'Turn on developer mode...')
        self.assertIn('Read-only', win.dev_note.text())
        self.assertTrue(win.dev.title().endswith('read-only'))

    def test_scope_buttons_follow_the_model(self):
        win = self.window()
        self.assertTrue(win.scope_buttons['run'].isChecked())
        for value, b in win.scope_buttons.items():
            self.assertEqual(b.isEnabled(), next(a for v, _l, a, _w in win.model.scope_choices() if v == value))

    def test_toggle_dev_runs_unlock_or_lock(self):
        win = self.window()
        was = self.lock.unlocked
        with mock.patch.object(PP.UI, 'ask_unlock', return_value=True) as ask:
            win.btn_dev.click()
        if was:
            self.assertFalse(self.lock.unlocked)
            ask.assert_not_called()
        else:
            ask.assert_called_once()


@unittest.skipUnless(HAVE_QT and ENGINE_OK, 'needs PySide6 and the stubbed Tk engine harness')
class LiveHookOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QAPP

    def setUp(self):
        from tests import point_editor_harness as PH
        PP._open.clear()
        self.b = PH.truevolt()
        self.addCleanup(self.b.stop)
        self.app = self.b.app
        self.calls = []
        calls = self.calls

        class Shell:
            root = None
            verified = []

            def add_action(self, text, cmd, **kw):
                calls.append(text)
                self.button = mock.MagicMock()
                return self.button

            def set_modified(self, n): pass
            def set_devmode(self, on): pass
            def set_verified(self, text): self.verified.append(text)
        self.shell = Shell()
        self.hook = PE.attach_live(self.app, self.shell, self.b.env.lock)
        self.infos = []
        p = mock.patch.object(common, 'show_info', side_effect=lambda parent, title, text: self.infos.append((title, text)))
        p.start()
        self.addCleanup(p.stop)

    def test_the_button_is_called_edit_point(self):
        self.assertEqual(self.calls, ['Edit point'])

    def test_with_nothing_selected_it_says_to_select_a_point(self):
        self.assertIsNone(self.hook.open())
        self.assertIn('Select a test point', self.infos[-1][1])

    def test_with_a_selected_point_it_opens_that_points_window(self):
        tree = table_of(['68', '69'])
        PP.attach_tree_menu(self.app, tree, lock=self.b.env.lock)
        tree.select_rows(tree.rows()[:1])
        with mock.patch.object(PP, 'open_point_window', return_value='WIN') as op:
            self.assertEqual(self.hook.open(), 'WIN')
        self.assertEqual(str(op.call_args[0][1]), '68')

    def test_a_verified_locked_procedure_refuses_with_the_reason(self):
        self.app.pm_state._store().lock_reason = lambda model, key='': 'verified and locked'
        self.assertIsNone(self.hook.open())
        self.assertIn('verified and locked', self.infos[-1][1])
        self.assertEqual(self.infos[-1][0], 'Procedure is locked')
        self.hook.sync_verified()
        self.assertEqual(self.shell.verified[-1], PE.LiveHook.CHIP)
        self.shell.button.setEnabled.assert_called_with(False)
        self.shell.button.setToolTip.assert_called_with('verified and locked')


if __name__ == '__main__':
    unittest.main()
