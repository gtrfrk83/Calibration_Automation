"""The Qt Manager (qtui/screens/manager.py): construction on a throw-away database, the table against what the Tk Manager lists, find / category / views, the card,
the menus, Run / Try in demo mode through a fake launcher, the verified-on-hardware flow and its info popup, the row menu, the hosted-panel registry, the helper
dialogs (verified, register, package preview, MDD preview, Find instruments) and the CALSUITE_UI toolkit switch.  Skipped when PySide6 is not importable.

Run (separate processes are faster):  python -m unittest tests.test_qt_manager"""
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
_DATA = tempfile.mkdtemp(prefix='qt_manager_data_')
_OLD_DATA = os.environ.get('CALSUITE_DATA')
os.environ['CALSUITE_DATA'] = _DATA                    # the registries of this process are throw-away ones

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

import dsb_manager  # noqa: E402
import manager_model as mm  # noqa: E402
import procedure_menu  # noqa: E402
import procscan  # noqa: E402
import ui_port  # noqa: E402
import verified as V  # noqa: E402

if HAVE_QT:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
    from qtui import app
    from qtui.screens import PANELS, manager_dialogs as dialogs
    from qtui.screens.manager import ManagerWindow


def tearDownModule():
    if _OLD_DATA is None:
        os.environ.pop('CALSUITE_DATA', None)
    else:
        os.environ['CALSUITE_DATA'] = _OLD_DATA


class FakeLauncher:
    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, args, cwd=None):
        if self.fail:
            raise self.fail
        self.calls.append((list(args), cwd))


def expected_rows(db, base, view):
    """What the Tk Manager's refresh() puts in its table for a view (its SQL and its classification, restated here): [(id, name, mfr, model, category)]."""
    scanned = {p.launcher_name.casefold(): p for p in procscan.procs(base)}
    with sqlite3.connect(db) as conn:
        rows = conn.execute('SELECT id,name,manufacturer,model,category,script_path FROM procedures WHERE enabled=1 ORDER BY manufacturer,model,name').fetchall()
    out = []
    for id_, name, mfr, model, cat, script in rows:
        proc = scanned.get(Path(script).name.casefold())
        kind = proc.effective_kind if proc is not None else procscan.classify(name, cat)
        if kind == view:
            out.append((str(id_), name, mfr, model, cat))
    return out


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAVE_QT:
            raise unittest.SkipTest('PySide6 is not installed')
        cls.app = app.create_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.registry = V.Registry(self.t / 'verified.sqlite3', seed=False)
        self.core = mm.ManagerCore(db=self.t / 'procedures.sqlite3', registry=self.registry)
        self.launcher = FakeLauncher()
        self.win = ManagerWindow(self.core, launcher=self.launcher, panels={})
        self.win.resize(1300, 820)
        self.win.show()
        self.addCleanup(self.close_window)
        self.pump()
        self.boxes = []                                    # the message boxes the Manager raised (title, text)
        patches = [mock.patch.object(dialogs, 'message', side_effect=lambda parent, kind, title, text, detail='': self.boxes.append((kind, title, text))),
                   mock.patch.object(dialogs, 'ask_yes_no', return_value=True)]
        self.msg, self.yesno = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])

    def pump(self, n=3):
        for _ in range(n):
            self.app.processEvents()

    def close_window(self):
        self.win.close()
        self.win.deleteLater()
        self.pump()

    def select(self, name):
        row = next(r for r in self.win.table.rows() if r.name == name)
        self.win.table.select_rows([row])
        self.pump()
        return row

    def type_search(self, text):
        self.win.search.setText(text)
        self.win.search.flush()
        self.pump()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ListAndFind(QtCase):
    def test_table_equals_the_tk_managers_rows_in_each_view(self):
        for kind, _title in mm.VIEW_TABS:
            self.win.select_view(kind)
            self.pump()
            got = [(r.iid, r.name, r.manufacturer, r.model, r.category) for r in self.win.table.rows() if not r.user]
            self.assertEqual(got, expected_rows(self.core.db, self.core.base, kind), kind)
        self.win.select_view(procscan.KIND_VERIFICATION)
        self.assertGreater(len(self.win.table.rows()), 20)

    def test_the_three_views_hold_the_adjustments_apart(self):
        self.win.select_view(procscan.KIND_ADJUSTMENT)
        self.pump()
        names = [r.name for r in self.win.table.rows()]
        self.assertEqual(len(names), 3)
        self.assertTrue(all('Adjust' in n for n in names))
        self.assertFalse(self.win.adjust_note.isHidden())
        self.assertEqual(self.win.status.get().split()[0:3], ['3', 'of', '3'])
        self.win.select_view(procscan.KIND_VERIFICATION)
        self.assertTrue(self.win.adjust_note.isHidden())

    def test_columns_and_headings(self):
        heads = [self.win.table.source_model.headerData(i, Qt.Orientation.Horizontal) for i in range(6)]
        self.assertEqual(heads, ['Procedure', 'Manufacturer', 'Model', 'Category', 'Status', 'Verified on hardware'])
        r = self.win.table.rows()[0]
        self.assertEqual((r.status, r.verified), ('Ready', 'Not verified'))

    def test_find_narrows_the_list_and_clear_restores_it(self):
        total = len(self.win.table.rows())
        self.type_search('keithley')
        rows = self.win.table.rows()
        self.assertTrue(rows and len(rows) < total)
        self.assertTrue(all('keithley' in ' '.join((r.name, r.manufacturer, r.model, r.category)).lower() for r in rows))
        self.assertIn(f'{len(rows)} of {total}', self.win.status.get())
        QTest.mouseClick(self.win.btn_clear, Qt.MouseButton.LeftButton)
        self.pump()
        self.assertEqual((self.win.search.text(), self.win.category, len(self.win.table.rows())), ('', mm.ALL_CATEGORIES, total))

    def test_category_filter_and_its_list_belong_to_the_view(self):
        cats = [self.win.category_box.itemText(i) for i in range(self.win.category_box.count())]
        self.assertEqual(cats[0], mm.ALL_CATEGORIES)
        self.assertIn('Digital Multimeter', cats)
        self.win.category_box.setCurrentText('Digital Multimeter')
        self.win.refresh()
        self.assertTrue(all(r.category == 'Digital Multimeter' for r in self.win.table.rows()))
        self.win.select_view(procscan.KIND_ADJUSTMENT)
        self.pump()
        self.assertEqual(self.win.category, mm.ALL_CATEGORIES)               # the category list belongs to the view

    def test_no_match_here_but_in_another_tab_says_so(self):
        self.type_search('guided adjustment')
        self.assertEqual(self.win.table.rows(), [])
        self.assertIn('No procedures match in this tab.', self.win.table.empty_text)
        self.assertIn('in the Adjustments tab', self.win.table.empty_text)
        self.type_search('zzzz-nothing')
        self.assertEqual(self.win.table.empty_text, mm.EMPTY_LIBRARY)
        self.assertFalse(self.win.btn_run.isEnabled())
        self.assertEqual(self.win.d_name.text(), 'No procedure selected')

    def test_ctrl_f_focuses_the_find_box_on_the_procedures_tab(self):
        self.win.select_tab('asset_history')
        self.win.focus_search()
        self.assertEqual(self.win.tabs.currentIndex(), 0)
        self.assertTrue(self.win.search.hasFocus() or self.win.search.isAncestorOf(QApplication.focusWidget()) or QApplication.focusWidget() is self.win.search)

    def test_selection_survives_a_refresh(self):
        self.select('Keithley 2000 Performance Verification')
        self.win.refresh()
        self.assertEqual(self.win.table.selected_rows()[0].name, 'Keithley 2000 Performance Verification')

    def test_user_built_datasheets_are_listed_after_the_library_rows(self):
        row = dict(iid='ds:abc', uid='abc', name='My datasheet', manufacturer='ACME', model='X1', category='User-built', tag='user-built', script='Procedures/generic.py',
                   spec_path=str(self.t / 'spec.json'), description='', version=3, kind='verification')
        with mock.patch.object(dsb_manager, 'user_rows', return_value=[row]):
            self.win.refresh()
        last = self.win.table.rows()[-1]
        self.assertEqual((last.iid, last.name, last.user), ('ds:abc', 'My datasheet', True))
        self.assertIn('[user-built]', last.status)
        self.assertEqual(last.status, 'Missing  [user-built]')                  # its script / spec file is not here


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Card(QtCase):
    def test_card_follows_the_selection(self):
        self.select('Keithley 2000 Performance Verification')
        self.assertEqual(self.win.d_name.text(), 'Keithley 2000 Performance Verification')
        self.assertIn('Keithley 2000', self.win.d_sub.text())
        self.assertIn('Digital Multimeter', self.win.d_sub.text())
        self.assertIn('Keithley_2000_Verification.py', self.win.d_path.text())
        self.assertEqual(self.win.d_pill.text(), 'Ready to run')
        self.assertEqual(self.win.d_pill.kind(), 'good')
        self.assertTrue(self.win.btn_run.isEnabled() and self.win.btn_demo.isEnabled())
        self.select('Agilent 33220A Performance Verification')
        self.assertEqual(self.win.d_name.text(), 'Agilent 33220A Performance Verification')

    def test_card_buttons_and_texts_are_the_tk_ones(self):
        self.select('Keithley 2000 Performance Verification')
        self.assertEqual(self.win.btn_run.text(), '▶ Run')
        self.assertEqual(self.win.btn_demo.text(), 'Try in demo mode')
        self.assertEqual(self.win.fast_demo_box.text(), 'Fast demo (no windows)')
        self.assertEqual(self.win.btn_run.toolTip(), mm.RUN_TIP)
        self.assertEqual(self.win.btn_demo.toolTip(), mm.DEMO_EXPLANATION)
        self.assertEqual((self.win.btn_verify.text(), self.win.btn_lock.text()), ('Mark verified...', 'Unlock...'))
        self.assertEqual((self.win.btn_verify.isEnabled(), self.win.btn_lock.isEnabled()), (True, False))
        self.assertEqual(self.win.d_ver.text(), 'NOT VERIFIED ON HARDWARE')
        self.assertEqual(self.win.btn_ver_info.toolTip(), 'Show the full verification record')

    def test_run_demo_and_the_verify_buttons_are_pinned_inside_the_card(self):
        card = self.win.card
        for w in (self.win.btn_run, self.win.btn_demo, self.win.fast_demo_box, self.win.btn_verify, self.win.btn_lock, self.win.btn_ver_info):
            self.assertTrue(card.isAncestorOf(w))
            self.assertFalse(self.win.card_scroll.isAncestorOf(w))               # never inside the scrolling part
        self.assertTrue(self.win.card_scroll.isAncestorOf(self.win.d_name))

    def test_a_missing_script_disables_run_and_demo(self):
        row = next(r for r in self.win.table.rows() if r.name == 'Keithley 2000 Performance Verification')
        with mock.patch.object(self.core, 'script_file', side_effect=lambda s: self.t / 'gone.py'), mock.patch.object(mm, 'script_file', lambda b, s: self.t / 'gone.py'):
            self.win.table.select_rows([row])
            self.win.refresh_details()
            self.assertEqual((self.win.d_pill.text(), self.win.d_pill.kind()), ('Script file not found', 'bad'))
            self.assertFalse(self.win.btn_run.isEnabled() or self.win.btn_demo.isEnabled())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Menus(QtCase):
    def test_menu_bar_has_file_library_help_in_that_order(self):
        titles = [a.text().replace('&', '') for a in self.win.menuBar().actions()]
        self.assertEqual(titles, ['File', 'Library', 'Help'])
        self.assertIn('&Library', [a.text() for a in self.win.menuBar().actions()])           # Alt+L

    def test_library_menu_items_are_the_tk_ones(self):
        texts = [a.text() if not a.isSeparator() else None for a in self.win.library_menu.actions()]
        self.assertEqual(texts[:3], ['Import Mudcats datasheet (.mdd)...', 'Import procedure package...', 'Register procedure...'])
        self.assertEqual((texts[3], texts[5], texts[6], texts[7]), (None, 'Library folder...', None, 'Remove from library'))
        self.assertTrue(texts[4].startswith('Library folder: '))
        self.assertFalse(self.win.library_info.isEnabled())

    def test_library_info_line_and_remove_state_refresh_when_the_menu_opens(self):
        with mock.patch('packages.get_library_dir', return_value='/lab/library'):
            self.win.refresh_library_menu()
        self.assertEqual(self.win.library_info.text(), 'Library folder: /lab/library')
        self.assertTrue(self.win.library_actions['remove'].isEnabled())
        self.type_search('zzzz-nothing')
        self.win.refresh_library_menu()
        self.assertFalse(self.win.library_actions['remove'].isEnabled())
        self.assertIn(mm.LIBRARY_NOT_SET, self.win.library_info.text())

    def test_help_menu_items_and_f1(self):
        texts = [a.text() for a in self.win.help_menu.actions() if not a.isSeparator()]
        self.assertEqual(texts[:4], ['About Calibration Suite', 'Open my data folder', 'Import data from another copy...', 'Save diagnostic log for support'])
        self.assertIn('Appearance', texts)
        self.assertEqual(self.win.help_actions['about'].shortcut().toString(), 'F1')
        self.assertEqual([a.text() for a in self.win.appearance_menu.actions()], ['Dark', 'Light'])          # both themes are offered (light enabled 2026-10-24)
        self.win.help_actions['about'].trigger()
        self.assertEqual(self.boxes[-1][1], 'About Calibration Suite')
        self.assertIn('Your data folder:', self.boxes[-1][2])

    def test_window_title_follows_the_suite_pattern(self):
        self.assertEqual(self.win.windowTitle(), 'Calibration Suite  |  Calibration Procedure Manager  |  ' + mm.VERSION)

    def test_header_db_chip_and_status_bar(self):
        self.assertEqual(self.win.title_label.text(), 'Calibration Procedure Manager')
        self.assertEqual(self.win.db_chip.text(), 'Database: procedures.sqlite3')
        self.assertEqual(self.win.btn_find.text(), 'Find instruments...')
        self.assertEqual(self.win.version_label.text(), mm.VERSION)

    def test_main_tabs_and_their_status_texts(self):
        self.assertEqual([self.win.tabs.tabText(i) for i in range(self.win.tabs.count())], ['Procedures', 'Asset History', 'Standards Specs', 'Datasheet Builder'])
        self.assertEqual([self.win.view_bar.tabText(i) for i in range(3)], ['Automated Calibrations', 'Manual Calibrations', 'Adjustments'])
        for key in ('asset_history', 'standards_specs', 'datasheet_builder', 'procedures'):
            self.win.select_tab(key)
            self.assertEqual(self.win.status.get(), mm.TAB_STATUS[key])
        self.assertEqual(mm.TAB_STATUS['asset_history'], 'Every exported PDF report is recorded here. Double-click a test point to see its drift across reports.')

    def test_exit_closes_the_window(self):
        self.win.act_exit.trigger()
        self.assertFalse(self.win.isVisible())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RunAndDemo(QtCase):
    NAME = 'Keithley 2000 Performance Verification'

    def script(self):
        return str((ROOT / 'Procedures' / 'Keithley_2000_Verification.py').resolve())

    def test_run_launches_the_script_without_flags(self):
        self.select(self.NAME)
        QTest.mouseClick(self.win.btn_run, Qt.MouseButton.LeftButton)
        self.assertEqual(self.launcher.calls, [([sys.executable, self.script()], str(Path(self.script()).parent))])
        self.assertEqual(self.win.status.get(), f'Launched {self.NAME}.')

    def test_demo_adds_demo_and_fast_demo_adds_fast_demo(self):
        self.select(self.NAME)
        QTest.mouseClick(self.win.btn_demo, Qt.MouseButton.LeftButton)
        self.assertEqual(self.launcher.calls[-1][0], [sys.executable, self.script(), '--demo'])
        self.assertEqual(self.win.status.get(), f'Launched {self.NAME} in demo mode.')
        self.win.fast_demo_box.setChecked(True)
        QTest.mouseClick(self.win.btn_demo, Qt.MouseButton.LeftButton)
        self.assertEqual(self.launcher.calls[-1][0], [sys.executable, self.script(), '--demo', '--fast-demo'])
        QTest.mouseClick(self.win.btn_run, Qt.MouseButton.LeftButton)                  # the fast flag only goes with --demo
        self.assertEqual(self.launcher.calls[-1][0], [sys.executable, self.script()])

    def test_double_click_and_enter_run_the_selected_procedure(self):
        row = self.select(self.NAME)
        self.win.table.rowActivated.emit(row)
        self.assertEqual(len(self.launcher.calls), 1)
        QTest.keyClick(self.win.table, Qt.Key.Key_Return)
        self.assertEqual(len(self.launcher.calls), 2)

    def test_the_launch_arguments_are_the_tk_managers(self):
        """manager_model.launch_args is what Calibration_Procedure_Manager._launch builds (same flags, same order, cwd = the script's folder)."""
        args, cwd = self.core.launch_args('Procedures/Keithley_2000_Verification.py', True, True, asset='A-1', extra=['--spec', 'x.json'])
        self.assertEqual(args, [sys.executable, self.script(), '--demo', '--fast-demo', '--asset', 'A-1', '--spec', 'x.json'])
        self.assertEqual(cwd, str(ROOT / 'Procedures'))
        self.assertIsNone(self.core.launch_args('Procedures/nope.py', False))

    def test_a_missing_script_is_reported_and_nothing_is_started(self):
        self.core.launch_args = lambda *a, **k: None
        self.select(self.NAME)
        self.win.run_selected()
        self.assertEqual(self.launcher.calls, [])
        self.assertEqual(self.boxes[-1][1], 'Procedure not found')
        self.assertIn('Register its new location if it was moved.', self.boxes[-1][2])

    def test_a_failed_launch_is_reported(self):
        self.launcher.fail = OSError('no python')
        self.select(self.NAME)
        self.win.run_selected()
        self.assertEqual(self.boxes[-1][:2], ('error', 'Launch failed'))
        self.assertNotIn('Launched', self.win.status.get())

    def test_user_built_datasheet_runs_with_its_spec(self):
        spec = self.t / 'spec.json'
        spec.write_text('{}')
        row = dict(iid='ds:u1', uid='u1', name='My datasheet', manufacturer='ACME', model='X1', category='User-built', tag='user-built',
                   script='Procedures/Keithley_2000_Verification.py', spec_path=str(spec), description='', version=2, kind='verification')
        with mock.patch.object(dsb_manager, 'user_rows', return_value=[row]):
            self.win.refresh()
            self.select('My datasheet')
            self.win.run_selected(demo=True)
        self.assertEqual(self.launcher.calls[-1][0], [sys.executable, self.script(), '--demo', '--spec', str(spec)])
        self.assertEqual(self.win.status.get(), 'Launched My datasheet in demo mode.')

    def test_nothing_selected_asks_to_select(self):
        self.type_search('zzzz-nothing')
        self.win.run_selected()
        self.assertEqual(self.boxes[-1][1], 'Select a procedure')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class VerifiedFlow(QtCase):
    NAME = 'Keithley 2000 Performance Verification'
    FORM = {'who': 'Mike', 'on_date': '2026-10-20', 'note': 'ran on the bench', 'hardware': '34465A s/n 1'}

    def test_mark_verified_locks_and_updates_the_card_and_the_table(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=self.FORM) as ask:
            QTest.mouseClick(self.win.btn_verify, Qt.MouseButton.LeftButton)
        entry, status = ask.call_args[0][1:3]
        self.assertEqual((entry.name, status.kind), (self.NAME, 'none'))
        self.assertIn('is marked verified on hardware (2026-10-20) and locked against edits.', self.win.status.get())
        self.assertEqual(self.win.d_ver.text(), 'VERIFIED ON HARDWARE 2026-10-20 - LOCKED')
        self.assertEqual((self.win.btn_verify.isEnabled(), self.win.btn_lock.isEnabled()), (False, True))
        self.assertEqual(self.win.table.selected_rows()[0].verified, 'Verified 2026-10-20  [locked]')
        self.assertEqual(self.win.btn_lock.text(), 'Unlock...')

    def test_cancelled_form_changes_nothing(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=None):
            self.win.mark_verified()
        self.assertEqual(self.win.d_ver.text(), 'NOT VERIFIED ON HARDWARE')

    def test_unlock_then_lock_again(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=self.FORM):
            self.win.mark_verified()
        with mock.patch.object(dialogs, 'ask_unlock', return_value={'who': 'Mike', 'reason': 'a wrong limit to fix'}):
            self.win.toggle_lock()
        self.assertIn('is unlocked for editing; the reason is recorded.', self.win.status.get())
        self.assertEqual(self.win.d_ver.text(), 'VERIFIED 2026-10-20 - UNLOCKED FOR EDITING')
        self.assertEqual((self.win.btn_verify.text(), self.win.btn_lock.text()), ('Verify again...', 'Lock again'))
        with mock.patch.object(dialogs, 'ask_text', return_value='Mike'):
            self.win.toggle_lock()
        self.assertTrue(self.win.status.get().endswith('is locked again.'))
        self.assertEqual(self.win.d_ver.text(), 'VERIFIED ON HARDWARE 2026-10-20 - LOCKED')

    def test_a_locked_procedure_cannot_be_removed(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=self.FORM):
            self.win.mark_verified()
        self.win.remove()
        self.assertEqual(self.boxes[-1][1], 'Verified and locked')
        self.yesno.assert_not_called()

    def test_info_button_opens_the_record_popup_and_toggles(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=self.FORM):
            self.win.mark_verified()
        QTest.mouseClick(self.win.btn_ver_info, Qt.MouseButton.LeftButton)
        pop = self.win._ver_pop
        self.assertIsNotNone(pop)
        self.assertTrue(pop.isVisible())
        text = pop.box.toPlainText()
        self.assertIn('Verified on hardware by Mike on 2026-10-20.', text)
        self.assertIn('Run on: 34465A s/n 1', text)
        self.assertIn('Note: ran on the bench', text)
        self.assertTrue(pop.box.isReadOnly())
        self.assertIs(self.win.show_verified_details(), None)               # a second press closes it
        self.assertFalse(pop.isVisible())

    def test_info_popup_text_for_an_unverified_procedure(self):
        self.select(self.NAME)
        pop = self.win.show_verified_details()
        self.assertIn('Not marked as verified on hardware.', pop.box.toPlainText())
        pop.close()

    def test_verify_error_is_shown_not_raised(self):
        self.select(self.NAME)
        with mock.patch.object(dialogs, 'ask_mark', return_value=self.FORM), \
                mock.patch.object(self.core, 'mark_verified', side_effect=V.VerifyError('disk full')):
            self.assertIsNone(self.win.mark_verified())
        self.assertEqual(self.boxes[-1], ('error', 'Not recorded', 'disk full'))

    def test_the_verified_dialogs_validate_inside_and_return_the_form(self):
        self.select(self.NAME)
        entry, status = self.core.ver_status(self.win._selected_row())

        def drive():
            dlg = dialogs._last['dialog']
            dlg.edits['who'].setText('')
            dlg.button('ok').click()                                                # refused: stays open, explained inside
            self.assertTrue(dlg.isVisible())
            self.assertTrue(dlg.error.text())
            dlg.edits['who'].setText('Mike')
            dlg.edits['on_date'].setText('2026-10-20')
            dlg.button('ok').click()
        QTimer.singleShot(50, drive)
        got = dialogs.ask_mark(self.win, entry, status)
        self.assertEqual((got['who'], got['on_date']), ('Mike', '2026-10-20'))

        def cancel():
            dialogs._last['dialog'].button('cancel').click()
        QTimer.singleShot(50, cancel)
        self.assertIsNone(dialogs.ask_unlock(self.win, entry, status))

        def unlock():
            dlg = dialogs._last['dialog']
            dlg.edits['who'].setText('Mike')
            dlg.edits['reason'].setText('')
            dlg.button('ok').click()
            self.assertTrue(dlg.error.text())
            dlg.edits['reason'].setText('fix a wrong limit')
            dlg.button('ok').click()
        QTimer.singleShot(50, unlock)
        self.assertEqual(dialogs.ask_unlock(self.win, entry, status), {'who': 'Mike', 'reason': 'fix a wrong limit'})


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RowMenu(QtCase):
    NAME = 'Keithley 2000 Performance Verification'

    def test_row_menu_entries_are_procedure_menus(self):
        self.select(self.NAME)
        menu = self.win.build_row_menu()
        got = [a.text() if not a.isSeparator() else None for a in menu.actions()]
        want = [e.label if e else None for e in self.win.row_menu_items()]
        self.assertEqual(got, want)
        self.assertIn('Readiness check (no hardware)...', got)
        self.assertIn(procedure_menu.DEMO_LABEL, got)
        enabled = {a.data(): a.isEnabled() for a in menu.actions() if not a.isSeparator()}
        self.assertTrue(enabled[procedure_menu.RUN] and enabled[procedure_menu.DEMO] and enabled[procedure_menu.READINESS])
        self.assertTrue(enabled[procedure_menu.VERIFY] and not enabled[procedure_menu.LOCK])             # the card buttons' own rules
        self.assertTrue(enabled[procedure_menu.REMOVE])

    def test_menu_actions_call_the_manager_handlers(self):
        self.select(self.NAME)
        menu = self.win.build_row_menu()
        by = {a.data(): a for a in menu.actions() if not a.isSeparator()}
        by[procedure_menu.RUN].trigger()
        by[procedure_menu.DEMO].trigger()
        self.assertEqual([c[0][2:] for c in self.launcher.calls], [[], ['--demo']])
        by[procedure_menu.COPY_NAME].trigger()
        self.assertEqual(QApplication.clipboard().text(), self.NAME)
        self.assertEqual(self.win.status.get(), 'Copied the procedure name to the clipboard.')
        by[procedure_menu.COPY_PATH].trigger()
        self.assertTrue(QApplication.clipboard().text().endswith('Keithley_2000_Verification.py'))

    def test_right_click_selects_the_row_and_posts_the_menu(self):
        table = self.win.table
        index = table.model().index(2, 0)
        pos = table.visualRect(index).center()
        menu = self.win._row_menu_pointer(pos)
        self.assertIsNotNone(menu)
        self.assertEqual(table.selected_rows()[0], table.row_of(index))
        self.assertIs(self.win._row_menu, menu)
        menu.close()

    def test_keyboard_menu_opens_on_the_selected_row(self):
        self.select(self.NAME)
        menu = self.win._row_menu_pointer(QPoint(-5, -5))                       # no row there: the keyboard path uses the selected row
        self.assertIsNotNone(menu)
        menu.close()

    def test_readiness_check_runs_the_tool_in_a_subprocess_and_shows_its_output(self):
        self.select(self.NAME)
        done = types.SimpleNamespace(stdout='READY: all good\n', stderr='')
        with mock.patch('subprocess.run', return_value=done) as run:
            self.win.readiness_check()
            self.assertEqual(self.win.status.get(), f'Readiness check of {self.NAME} ...')
            t = self.win._readiness_thread
            t.join(5)
            for _ in range(40):
                self.pump()
                if self.win._readiness_window is not None:
                    break
                QTest.qWait(50)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[1:], [str(ROOT / 'tools' / 'readiness_check.py'), self.win._selected_row()[0].__str__()])
        self.assertEqual(run.call_args[1]['timeout'], 300)
        self.assertEqual(self.win._readiness_window.text_box.toPlainText(), 'READY: all good\n')
        self.assertEqual(self.win.status.get(), 'Readiness check finished.')
        self.win._readiness_window.close()

    def test_readiness_check_without_the_tool_says_so(self):
        self.select(self.NAME)
        with mock.patch.object(self.core, 'readiness_command', return_value=None):
            self.win.readiness_check()
        self.assertEqual(self.boxes[-1][:2], ('info', 'Readiness check'))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LibraryActions(QtCase):
    def test_register_a_script_then_remove_it(self):
        script = self.t / 'My_Test_Procedure.py'
        script.write_text('print(1)\n')
        self.type_search('')

        def drive():
            dlg = dialogs._last['dialog']
            self.assertEqual(dlg.edits['Procedure name'].text(), 'My Test Procedure')
            dlg.edits['Manufacturer'].setText('ACME')
            dlg.edits['Model'].setText('Z9')
            dlg.edits['Category'].setText('Digital Multimeter')
            dlg.button('save').click()
        with mock.patch.object(dialogs, 'pick_open_file', return_value=str(script)):
            QTimer.singleShot(50, drive)
            self.win.add()
        self.assertEqual(self.win.status.get(), 'Registered "My Test Procedure".')
        self.assertIn('My Test Procedure', [r.name for r in self.win.table.rows()])
        with sqlite3.connect(self.core.db) as conn:
            self.assertEqual(conn.execute("SELECT manufacturer,model,script_path FROM procedures WHERE name='My Test Procedure'").fetchone(), ('ACME', 'Z9', str(script.resolve())))
        self.select('My Test Procedure')
        self.win.remove()
        self.assertEqual(self.yesno.call_args[0][1:], ('Remove from library', 'Remove "My Test Procedure" from the procedure library?\n\nThe Python script will not be deleted.'))
        self.assertEqual(self.win.status.get(), 'Removed "My Test Procedure" from the library (script file kept).')
        self.assertNotIn('My Test Procedure', [r.name for r in self.win.table.rows()])

    def test_registering_twice_and_a_missing_name_are_refused_inside_the_form(self):
        script = self.t / 'Twice.py'
        script.write_text('print(1)\n')
        calls = []

        def save(*a):
            calls.append(a)
            raise sqlite3.IntegrityError('dup')

        def drive():
            dlg = dialogs._last['dialog']
            dlg.edits['Procedure name'].setText('')
            dlg.button('save').click()
            self.assertEqual(self.boxes[-1][1], 'Missing name')
            dlg.edits['Procedure name'].setText('Twice')
            dlg.button('save').click()
            self.assertEqual(self.boxes[-1][1], 'Already registered')
            dlg.button('cancel').click()
        QTimer.singleShot(50, drive)
        self.assertIsNone(dialogs.ask_register(self.win, script, str(script), save))
        self.assertEqual(len(calls), 1)

    def test_remove_without_confirmation_keeps_the_row(self):
        self.select('Keithley 2000 Performance Verification')
        self.yesno.return_value = False
        n = len(self.win.table.rows())
        self.win.remove()
        self.assertEqual(len(self.win.table.rows()), n)

    def test_library_folder_menu_item_updates_the_info_line(self):
        with mock.patch.object(dialogs, 'choose_library_folder', return_value='/lab/lib'), mock.patch('packages.get_library_dir', return_value='/lab/lib'):
            self.win.library_actions['folder'].trigger()
            self.assertEqual(self.win.library_info.text(), 'Library folder: /lab/lib')

    def test_import_package_flow_asks_then_installs_then_refreshes(self):
        import packages
        self.win.refresh = mock.Mock()
        pv = types.SimpleNamespace(zip_sha256='abc', ok=True)
        res = types.SimpleNamespace(name='K2', version='2', written=['a', 'b'])
        with mock.patch.object(dialogs, 'choose_package', return_value='/x/p.zip'), mock.patch.object(packages, 'inspect', return_value=pv) as insp, \
                mock.patch.object(dialogs, 'ask_install', return_value=True), mock.patch.object(packages, 'install', return_value=res) as inst, \
                mock.patch.object(dialogs, 'show_result') as show:
            self.win.import_package()
        insp.assert_called_once()
        self.assertEqual(inst.call_args[1]['expected_sha256'], 'abc')
        self.win.refresh.assert_called_once()
        self.assertEqual(self.win.status.get(), 'Imported K2 version 2 (2 file(s) written).')
        show.assert_called_once()

    def test_declined_package_is_not_imported(self):
        import packages
        with mock.patch.object(dialogs, 'choose_package', return_value='/x/p.zip'), mock.patch.object(packages, 'inspect', return_value=types.SimpleNamespace(zip_sha256='x')), \
                mock.patch.object(dialogs, 'ask_install', return_value=False), mock.patch.object(packages, 'install') as inst:
            self.win.import_package()
        inst.assert_not_called()
        self.assertEqual(self.win.status.get(), 'Package not imported.')

    def test_mdd_import_opens_the_preview_and_selects_the_new_manual_procedure(self):
        from mdd_synth import write_mdd
        mdd = write_mdd(self.t / 'x.mdd')
        spec_root, archive = self.t / 'specs', self.t / 'arch'
        reg = None
        pv = dialogs.open_mdd_preview(self.win, str(mdd), on_created=self.win._mdd_procedure_created, status=self.win.status.set,
                                      registry=reg, spec_root=spec_root, archive_to=archive)
        self.assertIsNotNone(pv)
        self.assertTrue(pv.dialog.isVisible())
        self.assertEqual(self.win.table.rows() and len([r for r in self.win.table.rows() if r.user]), 0)          # nothing created before approval
        self.assertIn('Converted', [pv.grid.source_model.columns[6].getter(r) for r in pv.grid.rows()])
        self.assertTrue(any('NOT converted' in t for t in pv.pill_texts))
        self.assertIsNone(next((r for r in dsb_manager.user_rows(spec_root) if r['kind'] == 'manual'), None))
        real_rows = dsb_manager.user_rows
        with mock.patch.object(dsb_manager, 'user_rows', side_effect=lambda root=None, db=None: real_rows(spec_root)):
            pv.create_btn.click()
            self.pump()
        self.assertEqual(self.win.view_kind, procscan.KIND_MANUAL)
        self.assertIn('Created the manual calibration', self.boxes[-1][2])
        self.assertTrue(any(r.user for r in self.win.table.rows()))
        self.assertIs(self.win.table.selected_rows()[0].user, True)
        self.assertFalse(pv.dialog.isVisible())

    def test_mdd_import_of_a_bad_file_shows_the_reason(self):
        bad = self.t / 'bad.mdd'
        bad.write_text('not a datasheet')
        self.assertIsNone(dialogs.open_mdd_preview(self.win, str(bad)))
        self.assertEqual(self.boxes[-1][:2], ('error', 'Cannot import datasheet'))

    def test_restore_previous_needs_a_managed_script_with_a_backup(self):
        self.select('Keithley 2000 Performance Verification')
        self.win.restore_previous()
        self.assertEqual(self.boxes[-1][1], 'No backups')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class HostedPanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def make(self, panels):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core = mm.ManagerCore(db=Path(tmp.name) / 'p.sqlite3', registry=V.Registry(Path(tmp.name) / 'v.sqlite3', seed=False))
        win = ManagerWindow(core, launcher=FakeLauncher(), panels=panels)
        win.resize(1200, 800)
        win.show()
        self.addCleanup(win.close)
        return win

    def test_registry_names_the_three_panels(self):
        self.assertEqual(PANELS, {'asset_history': 'qtui.screens.asset_history:AssetHistoryPanel', 'standards_specs': 'qtui.screens.standards_specs:StandardsSpecsPanel',
                                  'datasheet_builder': 'qtui.screens.datasheet_builder:DatasheetBuilderPanel'})

    def test_missing_modules_show_a_not_built_yet_state_and_the_shell_works(self):
        win = self.make({'asset_history': 'qtui.screens.no_such_a:A', 'standards_specs': 'qtui.screens.no_such_b:B', 'datasheet_builder': 'qtui.screens.no_such_c:C'})
        self.assertEqual(win.panels, {})
        for key, title in (('asset_history', 'Asset History'), ('standards_specs', 'Standards Specs'), ('datasheet_builder', 'Datasheet Builder')):
            self.assertEqual(win._panel_notes[key].title_label.text(), f'{title} is not built yet')
            win.select_tab(key)
        win.select_tab('procedures')
        self.assertGreater(len(win.table.rows()), 20)

    def test_a_registered_panel_is_hosted_refreshed_on_tab_change_and_can_save(self):
        from PySide6.QtWidgets import QLabel, QWidget
        seen = {}

        class Panel(QWidget):
            def __init__(self, parent=None, on_saved=None, status=None):
                super().__init__(parent)
                seen.update(on_saved=on_saved, status=status, refreshed=0)
                QLabel('panel', self)

            def refresh(self):
                seen['refreshed'] += 1

        mod = types.ModuleType('qt_manager_fake_panels')
        mod.Panel = Panel
        sys.modules['qt_manager_fake_panels'] = mod
        self.addCleanup(sys.modules.pop, 'qt_manager_fake_panels', None)
        win = self.make({'asset_history': 'qt_manager_fake_panels:Panel', 'standards_specs': 'qtui.screens.no_such_b:B', 'datasheet_builder': 'qt_manager_fake_panels:Panel'})
        self.assertIsInstance(win.panels['asset_history'], Panel)
        self.assertIs(win.history_panel, win.panels['asset_history'])
        before = seen['refreshed']
        win.select_tab('asset_history')
        self.assertEqual(seen['refreshed'], before + 1)
        win.select_tab('datasheet_builder')
        self.assertEqual(seen['refreshed'], before + 2)
        self.assertEqual(win.status.get(), mm.TAB_STATUS['datasheet_builder'])
        seen['status']('hello from a panel')                                      # the status object works as a callable and as .set / .get
        self.assertEqual(win.status.get(), 'hello from a panel')
        seen['status'].set('again')
        self.assertEqual(win.status.get(), 'again')
        win.refresh = mock.Mock()
        seen['on_saved']()
        win.refresh.assert_called_once()                                          # a saved datasheet refreshes the Procedures list

    def test_a_panel_that_fails_to_build_does_not_take_the_manager_down(self):
        class Bad:
            def __init__(self, parent=None):
                raise RuntimeError('boom')
        mod = types.ModuleType('qt_manager_bad_panel')
        mod.Bad = Bad
        sys.modules['qt_manager_bad_panel'] = mod
        self.addCleanup(sys.modules.pop, 'qt_manager_bad_panel', None)
        win = self.make({'asset_history': 'qt_manager_bad_panel:Bad', 'standards_specs': 'qtui.screens.no_such_b:B', 'datasheet_builder': 'qtui.screens.no_such_c:C'})
        self.assertIn('RuntimeError: boom', win._panel_notes['asset_history'].text_label.text())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PackageDialogs(QtCase):
    def test_install_button_stays_disabled_until_the_box_is_ticked(self):
        import packages
        pv = types.SimpleNamespace(ok=True, zip_name='K2.zip', in_library=True, errors=[], warnings=['Careful'], proc_id='K2', name='Keithley 2000', version='2',
                                   installed_version='1', author='me', origin='/lib/K2.zip', zip_sha256='ab' * 32, status_text='Not verified', will_unlock=False, mark=None,
                                   affected=[], requires=[], files=[types.SimpleNamespace(path='Procedures/a.py', size=1234, state='replace'),
                                                                   types.SimpleNamespace(path='Procedures/b.json', size=50, state='new')])
        seen = {}

        def drive():
            dlg = dialogs._last['dialog']
            seen['enabled0'] = dlg.install.isEnabled()
            seen['rows'] = [(r.path, dlg.table.source_model.columns[2].getter(r)) for r in dlg.table.rows()]
            seen['kv'] = dict(dlg.rows)
            dlg.confirm.setChecked(True)
            seen['enabled1'] = dlg.install.isEnabled()
            dlg.install.click()
        QTimer.singleShot(50, drive)
        self.assertTrue(dialogs.ask_install(self.win, pv))
        self.assertEqual((seen['enabled0'], seen['enabled1']), (False, True))
        self.assertEqual(seen['rows'], [('Procedures/a.py', 'REPLACES installed file'), ('Procedures/b.json', 'New')])
        self.assertEqual(seen['kv']['Version'], '2   (installed: 1)')
        self.assertIn('inside the lab', seen['kv']['Origin'])
        self.assertTrue(packages.CODE_WARNING)

    def test_a_refused_package_has_no_install_button(self):
        pv = types.SimpleNamespace(ok=False, zip_name='bad.zip', in_library=None, errors=['not a zip'], warnings=[], proc_id='', files=[])

        def drive():
            dlg = dialogs._last['dialog']
            self.assertIsNone(dlg.install)
            dlg.button('close').click()
        QTimer.singleShot(50, drive)
        self.assertFalse(dialogs.ask_install(self.win, pv))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class FindInstruments(QtCase):
    def test_scan_lists_results_and_remember_works(self):
        import instrument_scan as S
        from tests.test_instrument_scan import FakeRM, IDN_3458
        from qtui.screens import find_instruments as FI
        rm = FakeRM({'GPIB1::22::INSTR': dict(replies=IDN_3458), 'GPIB1::9::INSTR': dict(replies={})}, listed=['GPIB1::INTFC', 'GPIB1::22::INSTR', 'GPIB1::9::INSTR'])
        memory = S.ResourceMemory(self.t / 'lab.sqlite3', workstation='WS-1')
        w = FI.open_find_instruments(self.win, memory=memory, scanner_factory=lambda pa, gl: S.Scanner(lambda: rm, probe_all_gpib=pa, go_local=gl),
                                     serial_ports=lambda: ['COM3'])
        self.addCleanup(w.close)
        self.assertEqual(w.windowTitle(), 'Find instruments')
        self.assertFalse(w.btn_remember.isEnabled())
        QTest.mouseClick(w.btn_scan, Qt.MouseButton.LeftButton)
        for _ in range(100):
            self.pump()
            if w.report is not None:
                break
            QTest.qWait(50)
        self.assertIsNotNone(w.report)
        rows = w.table.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].values[0].startswith('GPIB1::22'))               # identified first
        self.assertEqual(rows[0].values[2], '3458A')
        self.assertIn('1 instrument identified', w.status.text())
        self.assertEqual([w.port_box.itemText(i) for i in range(w.port_box.count())], ['COM3'])
        w.table.select_rows([rows[0]])
        self.pump()
        self.assertTrue(w.btn_copy.isEnabled() and w.btn_remember.isEnabled())
        QTest.mouseClick(w.btn_copy, Qt.MouseButton.LeftButton)
        self.assertEqual(QApplication.clipboard().text(), rows[0].hit.resource)
        QTest.mouseClick(w.btn_remember, Qt.MouseButton.LeftButton)
        self.assertTrue(w.status.text().startswith('Remembered GPIB1::22::INSTR for this workstation.'))
        self.assertTrue(w.btn_forget.isEnabled())
        QTest.mouseClick(w.btn_forget, Qt.MouseButton.LeftButton)
        self.assertEqual(w.status.text(), 'Forgotten.')
        w.table.select_rows([w.table.rows()[1]])
        self.pump()
        self.assertFalse(w.btn_remember.isEnabled())                                # a silent resource cannot be remembered

    def test_the_status_bar_button_opens_the_window(self):
        with mock.patch('qtui.screens.find_instruments.open_find_instruments', return_value='W') as o:
            QTest.mouseClick(self.win.btn_find, Qt.MouseButton.LeftButton)
        o.assert_called_once_with(self.win)
        self.assertEqual(self.win.find_window, 'W')


class ToolkitSwitch(unittest.TestCase):
    """ui_port.select_toolkit / CALSUITE_UI (needs no Qt)."""

    def test_name_from_the_environment_defaults_to_tk(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CALSUITE_UI', None)
            self.assertEqual(ui_port.toolkit_name(), 'tk')
            os.environ['CALSUITE_UI'] = ' QT '
            self.assertEqual(ui_port.toolkit_name(), 'qt')
            os.environ['CALSUITE_UI'] = 'gtk'
            self.assertEqual(ui_port.toolkit_name(), 'tk')
        self.assertEqual(ui_port.toolkit_name('qt'), 'qt')

    def test_qt_without_a_qt_port_falls_back_to_tk(self):
        fake_tk = types.ModuleType('ui_port_tk')
        fake_tk.TkUiPort = lambda: types.SimpleNamespace(name='tk-port')
        old = ui_port.set_ui(None)
        try:
            with mock.patch.dict(sys.modules, {'ui_port_tk': fake_tk, 'ui_port_qt': None}):
                with self.assertRaises(ImportError):                                  # select_toolkit is strict: the launcher must know
                    ui_port.select_toolkit('qt')
                ui_port.set_ui(None)
                with mock.patch.dict(os.environ, {'CALSUITE_UI': 'qt'}):              # an engine started on its own falls back to Tk with a note
                    self.assertEqual(ui_port.get_ui().name, 'tk-port')
        finally:
            ui_port.set_ui(old)

    def test_qt_port_is_used_when_it_exists(self):
        class QtUiPort:
            pass
        QtUiPort.__module__ = 'ui_port_qt'
        fake_qt = types.ModuleType('ui_port_qt')
        fake_qt.QtUiPort = QtUiPort
        old = ui_port.set_ui(None)
        try:
            with mock.patch.dict(sys.modules, {'ui_port_qt': fake_qt}):
                self.assertIsInstance(ui_port.select_toolkit('qt'), QtUiPort)          # returns the installed port
                self.assertIsInstance(ui_port.get_ui(), QtUiPort)
                ui_port.set_ui(None)
                with mock.patch.dict(os.environ, {'CALSUITE_UI': 'qt'}):
                    self.assertIsInstance(ui_port.get_ui(), QtUiPort)               # an engine started on its own gets the same choice
        finally:
            ui_port.set_ui(old)


class ModelRules(unittest.TestCase):
    def test_no_tk_in_the_model_or_the_qt_screens(self):
        import ast
        for path in [ROOT / 'manager_model.py', ROOT / 'Calibration_Procedure_Manager_qt.py', *sorted((ROOT / 'qtui' / 'screens').glob('*.py'))]:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                for n in names:
                    self.assertNotIn(n.split('.')[0], {'tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk', 'branding', 'instrument_scan_ui', 'mdd_import_ui', 'packages_ui',
                                                       'verified_ui'}, f'{path.name} imports {n}')

    def test_the_tk_manager_registers_through_the_shared_init_db(self):
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertIn('manager_model.init_db(DB, BASE', src)

    def test_init_db_registers_the_scan_in_list_order_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as d:
            core = mm.ManagerCore(db=Path(d) / 'p.sqlite3')
            core.init_db()
            with sqlite3.connect(core.db) as conn:
                first = conn.execute('SELECT name,manufacturer,model,category,script_path,description FROM procedures ORDER BY id').fetchall()
            core.init_db()
            with sqlite3.connect(core.db) as conn:
                self.assertEqual(conn.execute('SELECT name,manufacturer,model,category,script_path,description FROM procedures ORDER BY id').fetchall(), first)
            self.assertEqual([r[0] for r in first], [p.registration[0] for p in procscan.procs(ROOT)])


if __name__ == '__main__':
    unittest.main()
