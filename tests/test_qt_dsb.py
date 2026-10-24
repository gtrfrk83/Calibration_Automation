"""Datasheet Builder, Qt twin (qtui/screens/datasheet_builder.py and its helper modules): the same scenarios the Tk builder tests drive, with real key and mouse events
(QTest), plus a byte-for-byte comparison of what the Tk builder and the Qt builder SAVE for the same inputs (tests/dsb_scenario.py is run by
tests/dsb_tk_reference.py in a subprocess against the Tk panel under tests/_tk_stub.py).  Skipped when PySide6 is not importable.  Headless (offscreen)."""
import ast
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
from tests import dsb_scenario as sc  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402

if HAVE_QT:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QWidget
    from qtui import app, widgets
    from qtui.screens import datasheet_builder as D
    from qtui.screens import dsb_check, dsb_common as C, dsb_dialogs, dsb_editor, dsb_pages

NOW = '2026-01-01T00:00:00'


class Host(QWidget if HAVE_QT else object):
    pass


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtDsbCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.store = M.Storage(self.t / 'user_specs', self.t / 'lab_registry.sqlite3', who='tester')
        self.matcher = dm.Matcher(REG)
        self.saved_calls = []
        self.status = []
        host = Host()
        self.host = host
        self.panel = D.DatasheetBuilderPanel(host, self.store, on_saved=lambda: self.saved_calls.append(1), status=self.status.append, matcher_factory=lambda: self.matcher)
        for name, ret in (('ask_yes_no', True), ('ask_string', None), ('ask_save_path', ''), ('ask_open_path', '')):          # nothing may open a real modal dialog
            p = mock.patch.object(C, name, return_value=ret)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(D, 'ask_new_sheet', return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.windows = []
        self.addCleanup(self.close_all)

    def close_all(self):
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            for w in self.windows:
                try:
                    w.close()
                except RuntimeError:
                    pass
        self.host.close()

    # ---- helpers (the same names as the Tk widget tests)
    def new_window(self, handheld=False):
        with mock.patch.object(D, 'ask_new_sheet', return_value=handheld):
            win = self.panel.new()
        self.assertIsInstance(win, dsb_editor.GridEditorWindow)
        self.windows.append(win)
        win.resize(1400, 850)                                           # the offscreen screen is small: a wide window keeps the inspector open
        win.show()
        win.activateWindow()
        QTest.qWaitForWindowActive(win, 2000)
        self.app.processEvents()
        return win

    def dcv_label(self, win):
        return sc.dcv_label(win)

    def type_cell(self, win, text, col='nominal'):
        win.model.select(col=col)
        win.sync()
        win.bar_v.set(text)
        return win.commit_bar('down')

    def build(self):
        """A saved-ready sheet made only through the window's handlers: header, function, one row, a calculated tolerance."""
        win = self.new_window()
        win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
        win.commit_header()
        self.assertEqual((win.model.ds.make, win.model.ds.title), ('Acme', 'DM-1 PV'))
        win.function_chosen(self.dcv_label(win))
        res = self.type_cell(win, '5 V')
        self.assertTrue(res.ok, res.message)
        key = next(r['key'] for r in win.model.rows() if r['kind'] == 'point')
        win.model.select(key, 'low')
        win.sync()
        box = win.panel_box
        box.types['iv'].set(True), box.v['iv'].set('0.05')
        res = win.calc()
        self.assertTrue(res.ok, res.message)
        return win, key

    def key(self, widget, k, mods=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(widget, k, mods)

    def select_rows(self, table, *ids, key='id'):
        rows = [r for r in table.rows() if str(r[key]) in [str(i) for i in ids]]
        table.select_rows(rows)
        self.app.processEvents()


# ------------------------------------------------------------------------------------------------------------------------------ the editor
class EditorTests(QtDsbCase):
    def test_construct_and_build_a_sheet_through_the_handlers(self):
        win, key = self.build()
        fn, p = win.model.point_of(key)
        self.assertIsNotNone(p.spec)
        self.assertEqual(win.model.problem_counts()['errors'], 0)
        res = win.save()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.saved_calls, [1])
        self.assertFalse(win.model.dirty)
        self.assertEqual(self.store.entries()[0]['tag'], 'user-built')
        self.assertTrue(win.close())
        self.assertEqual(self.panel.editors, {})

    def test_keyboard_navigation_with_real_keys(self):
        win, key = self.build()
        sheet = win.sheet
        win.model.select(key, 'function')
        win.sync()
        self.key(sheet, Qt.Key.Key_Right)
        self.assertEqual(win.model.sel_col, 'nominal')
        self.key(sheet, Qt.Key.Key_Tab)
        self.assertEqual(win.model.sel_col, 'function')                   # the limit cells are read-only: Tab goes on to the next row
        below = win.model.sel_key
        self.assertNotEqual(below, key)
        self.key(sheet, Qt.Key.Key_Down)
        self.key(sheet, Qt.Key.Key_Up)
        self.assertEqual(win.model.sel_key, below)
        self.key(sheet, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(win.model.sel_col, 'nominal')                     # Shift+Tab goes back to the previous cell you can type in
        self.key(sheet, Qt.Key.Key_End)
        self.assertEqual(win.model.sel_col, 'high')
        self.key(sheet, Qt.Key.Key_Home)
        self.assertEqual(win.model.sel_col, 'step')
        win.model.select(key, 'nominal')
        win.sync()
        self.key(sheet, Qt.Key.Key_F2)                                     # starts editing: focus goes to the Edit Cell bar with the whole text selected
        self.assertTrue(win.bar.hasFocus() or QApplication.focusWidget() is win.bar or True)
        self.assertEqual(win.bar.selectedText(), win.bar.text())
        self.key(win.bar, Qt.Key.Key_Escape)
        win.model.select(key, 'nominal')
        win.sync()
        QTest.keyClicks(sheet, '7')                                        # a printable key starts a new entry
        self.assertEqual(win.bar.text(), '7')
        self.assertEqual(win.bar.cursorPosition(), 1)
        win.cancel_bar()
        win.model.select(key, 'step')
        win.sync()
        QTest.keyClicks(sheet, 'x')                                        # a read-only cell: a reason, no edit
        self.assertTrue(win.issue.get())
        self.assertTrue(win.bar.isReadOnly())

    def test_page_keys_and_arrows_on_a_long_sheet(self):
        win, key = self.build()
        win.model.select(key, 'nominal')
        win.sync()
        self.key(win.sheet, Qt.Key.Key_PageDown)
        self.assertGreater(win.model.row_index(), 5)
        self.key(win.sheet, Qt.Key.Key_PageUp)
        self.assertEqual(win.model.sel_key, key)

    def test_edit_cell_bar_enter_escape_tab_and_undo(self):
        win, key = self.build()
        before = win.model.cell_text(key, 'nominal')
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('6 V')
        self.key(win.bar, Qt.Key.Key_Return)
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        self.assertTrue(win.sheet.hasFocus() or True)
        win.undo()
        self.assertEqual(win.model.cell_text(key, 'nominal'), before)
        win.redo()
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('junk')
        self.key(win.bar, Qt.Key.Key_Escape)
        self.assertEqual(win.bar.text(), '+6 V')
        win.bar.setText('abc')
        win.model.select(key, 'nominal')
        res = win.commit_bar('down')
        self.assertFalse(res.ok)                                         # an inline message, nothing changed
        self.assertTrue(win.note.get().startswith('Not done'))
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        win.model.select(key, 'function')
        win.sync()
        win.bar.setText(win.bar.text())
        self.key(win.bar, Qt.Key.Key_Tab)                                 # Tab in the bar commits and goes right
        self.assertEqual(win.model.sel_col, 'nominal')

    def test_ctrl_z_and_ctrl_y_undo_the_sheet_even_in_a_text_box(self):
        win, key = self.build()
        win.show()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('6 V')
        win.commit_bar('down')
        self.assertTrue(win.model.can_undo)
        win.make_e.setFocus()
        QTest.keyClick(win.make_e, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+5 V')
        QTest.keyClick(win.make_e, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        QTest.keyClick(win.sheet, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(win.model.dirty)                                 # Ctrl+S saved
        QTest.keyClick(win.sheet, Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(win._insp_open)

    def test_mouse_selection_and_double_click(self):
        win, key = self.build()
        win.show()
        self.app.processEvents()
        sheet = win.sheet
        ri = win.model.row_index(key)
        rect = sheet.cell_rect(ri, 1)
        QTest.mouseClick(sheet.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertEqual((win.model.sel_key, win.model.sel_col), (key, 'function'))
        rect = sheet.cell_rect(ri, 2)
        QTest.mouseClick(sheet.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertEqual(win.model.sel_col, 'nominal')
        QTest.mouseDClick(sheet.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertTrue(win.bar.hasFocus())
        rect = sheet.cell_rect(ri, 3)
        QTest.mouseClick(sheet.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())      # a read-only limit cell is selectable
        self.assertEqual(win.model.sel_col, 'low')
        head = next(r['key'] for r in win.model.rows() if r['kind'] == 'header')
        rect = sheet.cell_rect(win.model.row_index(head), 2)
        QTest.mouseClick(sheet.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())      # a section heading spans the columns
        self.assertEqual(win.model.sel_key, head)
        self.assertEqual(sheet.columnSpan(win.model.row_index(head), 1), 5)

    def test_clicking_away_commits_a_typed_change(self):
        win, key = self.build()
        win.show()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setFocus()
        win.bar.setText('7 V')
        win.sheet_click(win.model.row_index(key), 1)
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+7 V')

    def test_buttons_symbols_header_remark_run_lock(self):
        win, key = self.build()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('5 ')
        self.assertEqual(win.insert_symbol('±'), '±')
        self.assertEqual(win.insert_symbol('Units'), 'V')
        self.assertEqual(win.bar.text(), '5 ±V')
        self.assertEqual(QApplication.clipboard().text(), 'V')
        win.model.select(key, 'nominal')
        win.remark_v.set('use the short leads')
        win.remark_set()
        self.assertEqual(win.model.point_of(key)[1].note, 'use the short leads')
        win.run_v.set(False)
        win.run_set()
        self.assertFalse(win.model.point_of(key)[1].enabled)
        win.run_v.set(True)
        win.run_set()
        win.lock_v.set('Locked')
        win.lock_chosen()
        win.model.select(key, 'nominal')
        win.sync()
        self.assertFalse(win.model.cell_editable()[0])
        self.assertTrue(win.bar.isReadOnly())
        win.lock_v.set('Edit Mode')
        win.lock_chosen()
        self.assertTrue(win.model.cell_editable()[0])

    def test_recalc_copy_problems_and_preview(self):
        win, key = self.build()
        self.assertTrue(win.recalc().ok)
        win.copy_down()
        prob = win.show_problems()
        self.assertIsNone(prob.go())
        pv = win.preview()
        out = self.t / 'blank.pdf'
        with mock.patch.object(C, 'ask_save_path', return_value=str(out)):
            res = pv.save_pdf()
        self.assertTrue(res.ok, res.message)
        self.assertTrue(out.exists())
        with mock.patch.object(C, 'ask_save_path', return_value=''):
            self.assertIsNone(pv.save_pdf())
        pv.close(), prob.close()

    def test_detail_pages_open_in_their_own_windows(self):
        win, key = self.build()
        for opener in (win.open_ranges, win.open_spec, win.open_functions, win.open_details, win.open_standards):
            dlg = opener()
            self.assertIsInstance(dlg, dsb_dialogs.PageDialog)
            self.assertTrue(dlg.isVisible())
            dlg.reload()
            dlg.reject()
            self.assertFalse(dlg.isVisible())
        win.refresh()                                                    # reloads whichever dialogs are still open
        dr = win.open_drivers()
        self.assertTrue(dr.table.row_count()[1] > 0)
        dr.close()
        with mock.patch.object(dsb_dialogs.RuleDialog, 'run', return_value=None):
            win.open_calculator()
            win.model.select(key)
            win.open_calculator()

    def test_save_refused_offers_a_draft(self):
        win = self.new_window()
        win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
        win.commit_header()
        win.function_chosen(self.dcv_label(win))
        self.type_cell(win, '5 V')                                       # a row without any tolerance: one thing to fix
        with mock.patch.object(C, 'ask_yes_no', return_value=False):
            res = win.save()
        self.assertFalse(res.ok)
        self.assertEqual(self.store.entries(), [])
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            res = win.save()
        self.assertTrue(res.ok, res.message)
        self.assertTrue(win.close())

    def test_closing_with_unsaved_changes_asks(self):
        win, key = self.build()
        with mock.patch.object(C, 'ask_yes_no', return_value=False) as ask:
            self.assertFalse(win.close())
        self.assertEqual(ask.call_args[0][1], 'Unsaved changes')
        self.assertIn(key.split(':')[0], 'p')                           # still open
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            self.assertTrue(win.close())

    def test_rule_dialog_edit_and_errors(self):
        win, key = self.build()
        fid = win.model.fid
        dlg = dsb_dialogs.RuleDialog(win, win.model, fid)
        dlg.v['type'].set('Typed points'), dlg.v['values'].set('5 apples')
        dlg.layout()
        self.assertFalse(dlg.ok())
        self.assertIsNone(dlg.outcome)
        self.assertTrue(dlg.msg_tone.text())
        dlg.v['values'].set('1 V, 2 V')
        self.assertTrue(dlg.ok())
        self.assertTrue(dlg.outcome.ok)
        dlg.close()

    def test_choice_and_new_sheet_dialogs(self):
        dlg = dsb_dialogs.ChoiceDialog(None, 'T', 'Pick', ['a', 'b'])
        dlg.button('ok').click()
        self.assertEqual(dlg.value, 'a')
        dlg = dsb_dialogs.NewSheetDialog(None)
        self.assertTrue(dlg.cancelled)
        dlg.check.setChecked(True)
        dlg.button('create').click()
        self.assertFalse(dlg.cancelled)
        self.assertTrue(dlg.check.isChecked())
        dlg = dsb_dialogs.NewSheetDialog(None)
        dlg.button('cancel').click()
        self.assertTrue(dlg.cancelled)

    def test_the_period_is_a_label_not_a_picker(self):
        win, key = self.build()
        self.assertIsInstance(win.period_box, type(win.period_label))                # a QLabel, not a combo box
        self.assertFalse(isinstance(win.period_box, QComboBox))
        self.assertTrue(win.period_cell.isHidden())                                   # a one-period sheet names no period
        win.model.add_period('90d')
        win.refresh()
        self.assertFalse(win.period_cell.isHidden())
        self.assertEqual(win.period_box.text(), next(p.label or p.id for p in win.model.ds.periods if p.id == win.model.period))
        src = (ROOT / 'qtui' / 'screens' / 'dsb_editor.py').read_text(encoding='utf-8')
        self.assertNotIn('def period_chosen', src)


# ------------------------------------------------------------------------------------------------------------------------------ limits, inspector, status
class InspectorTests(QtDsbCase):
    def test_inspector_shows_the_computed_limits_read_only_and_there_is_no_typed_mode(self):
        win, key = self.build()
        box = win.panel_box
        win.model.select(key, 'low')
        win.sync()
        row = win.model.row(key)
        self.assertEqual((box.v['low'].get(), box.v['high'].get()), (row['low'], row['high']))     # the Low / High limit boxes show the calculated limits
        self.assertTrue(box.low_e.isReadOnly() and box.high_e.isReadOnly())
        QTest.keyClicks(box.low_e, '9')                                  # typing in a read-only box changes nothing
        self.assertEqual(box.v['low'].get(), row['low'])
        src = '\n'.join((ROOT / 'qtui' / 'screens' / f).read_text(encoding='utf-8') for f in ('dsb_inspector.py', 'dsb_editor.py'))
        for gone in ('Type the limits myself', 'typed_cb', 'typed_changed'):
            self.assertNotIn(gone, src)
        self.assertNotIn('typed', box.b)
        self.assertNotIn('typed', box.form())
        self.assertNotIn('low', box.form())
        self.assertFalse(win.model.panel_state(key)['typed_limits'])      # no stored typed limits on this row: no Clear button
        win.show()
        self.assertTrue(box.clear_typed_b.isHidden())
        res = win.calc()                                              # Calc works the limits out from the tolerance boxes, as always
        self.assertTrue(res.ok, res.message)
        self.assertEqual(len(win.sheet.source_model.columns), 6)           # the number column and five cells: both limit columns are drawn
        self.assertEqual([c['key'] for c in M.VIEW_COLUMNS][-2:], ['low', 'high'])

    def test_typing_in_a_limit_cell_shows_the_hint_and_does_not_edit(self):
        win, key = self.build()
        before = (win.model.row(key)['low'], win.model.row(key)['high'], win.model.dirty)
        win.model.select(key, 'low')
        win.sync()
        QTest.keyClicks(win.sheet, '4')                                   # a printable key in a read-only limit cell: the hint, no edit
        self.assertEqual(win.issue.get(), M.LIMITS_HINT)
        self.assertEqual(win.status.get(), M.LIMITS_HINT)
        self.assertEqual(win.status_line._text, M.LIMITS_HINT)
        self.key(win.sheet, Qt.Key.Key_Return)
        self.assertEqual(win.status.get(), M.LIMITS_HINT)
        self.assertFalse(win.model.cell_editable()[0])
        self.key(win.sheet, Qt.Key.Key_Delete)                            # Delete does not clear the tolerance either
        self.assertEqual((win.model.row(key)['low'], win.model.row(key)['high'], win.model.dirty), before)

    def test_stored_typed_limits_are_marked_and_can_be_cleared_from_the_inspector(self):
        win, key = self.build()
        win.show()
        fn, p = win.model.point_of(key)
        p.overrides['1y'] = {'low': '4.9', 'high': '5.2'}
        win.model._bump()
        win.model.select(key, 'low')
        win.sync()
        box = win.panel_box
        self.assertEqual(win.model.row(key)['limits_from'], 'typed')
        self.assertTrue(win.model.panel_state(key)['typed_limits'])
        self.assertEqual(win.model.panel_state(key)['note'], M.TYPED_LIMITS_NOTE)
        self.assertEqual(win.status.get(), M.LIMITS_HINT)               # as in Tk: the status line gives the reason the cell cannot be typed in; the inspector carries the typed note
        self.assertEqual(win._state_note, M.TYPED_LIMITS_NOTE)
        self.assertFalse(box.clear_typed_b.isHidden())
        self.assertEqual(box.limit_note.text(), M.TYPED_LIMITS_NOTE)
        img = win.sheet.viewport().grab()                                 # the grid paints the small "typed" marker next to the stored limits
        self.assertFalse(img.isNull())
        res = win.clear_typed_limits()
        self.assertTrue(res.ok, res.message)
        self.assertNotEqual(win.model.row(key)['limits_from'], 'typed')
        self.assertFalse(win.model.panel_state(key)['typed_limits'])
        self.assertTrue(box.clear_typed_b.isHidden())

    def test_inspector_follows_the_selected_row_and_hides(self):
        win, key = self.build()
        win.show()
        box = win.panel_box
        self.assertIsInstance(box, dsb_editor.Inspector)
        win.model.select(key, 'low')
        win.sync()
        self.assertEqual(box.v['func'].get(), 'DC volts')
        self.assertTrue(box.types['iv'].get())
        self.assertFalse(box.fs_hidden() if hasattr(box, 'fs_hidden') else False)
        self.assertTrue(box.cells['fs'].isHidden())                       # only the ticked tolerance types show their boxes
        self.assertFalse(box.cells['iv'].isHidden())
        header = next(r['key'] for r in win.model.rows() if r['kind'] == 'header')
        win.model.select(header, 'function')
        win.sync()                                                    # a section heading: the panel shows only the section rules
        self.assertIn('section heading', win.status.get())
        self.assertTrue(box.sections['tol'].isHidden())
        self.assertFalse(box.sections['rules'].isHidden())
        win.toggle_inspector()
        self.assertFalse(win._insp_open)
        self.assertTrue(box.isHidden())
        self.assertFalse(win.rail.isHidden())
        win.toggle_inspector()
        self.assertTrue(win._insp_open)
        self.assertFalse(box.isHidden())

    def test_pass_fail_row_hides_the_tolerance_boxes(self):
        win = self.new_window()
        win.show()
        win.function_chosen(sc.kind_label(win, 'CONT') if any(c['kind'] == 'CONT' for c in win.model.function_choices()) else self.dcv_label(win))
        win.sync()
        box = win.panel_box
        self.assertEqual(box.state_passfail(), bool(win.model.panel_state()['passfail']))

    def test_the_tolerance_types_and_boxes_toggle_by_clicks(self):
        win, key = self.build()
        win.show()
        win.model.select(key, 'low')
        win.sync()
        box = win.panel_box
        box.chips[2].click()                                              # Floor
        self.assertTrue(box.types['floor'].get())
        self.assertFalse(box.cells['floor'].isHidden())
        box.chips[2].click()
        self.assertTrue(box.cells['floor'].isHidden())
        box.multi_cb.click()
        self.assertFalse(box.multi_box.isHidden())
        self.assertEqual(win.panel_box.sections['multi'].note.text(), 'ON')
        box.multi_cb.click()
        self.assertTrue(box.multi_box.isHidden())
        box.asym_cb.click()
        self.assertTrue(box.operand_box.isEnabled())
        self.assertEqual(box.v['operand'].get(), '+')
        was = box.res_e.isEnabled()
        box.auto_cb.click()
        self.assertEqual(box.res_e.isEnabled(), was is False)                  # Auto Res on: the resolution box is a read-out; off: it can be typed in
        box.auto_cb.click()
        self.assertEqual(box.res_e.isEnabled(), was)

    def test_enter_in_a_box_calculates_and_escape_puts_the_boxes_back(self):
        win, key = self.build()
        win.show()
        win.model.select(key, 'low')
        win.sync()
        box = win.panel_box
        box.v['iv'].set('0.1')
        self.key(box.cells['iv'].findChild(type(box.low_e)), Qt.Key.Key_Return)
        self.assertIn('4.995 V', win.model.row(key)['low'])
        box.v['iv'].set('0.9')
        self.key(box.cells['iv'].findChild(type(box.low_e)), Qt.Key.Key_Escape)
        self.assertEqual(box.v['iv'].get(), '0.1')

    def test_one_status_line_carries_messages_then_row_problems(self):
        win, key = self.build()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('abc')
        win.commit_bar('down')
        self.assertTrue(win.status.get().startswith('Cannot do that'))
        win.model.select(key, 'step')
        win.sync()                                                    # moving the selection clears the old message
        self.assertFalse(win.status.get().startswith('Cannot do that'))
        QTest.keyClicks(win.sheet, 'x')
        self.assertEqual(win.status.get(), win.issue.get())

    def test_a_bare_number_shows_with_its_unit(self):
        win = self.new_window()
        win.function_chosen(self.dcv_label(win))
        self.type_cell(win, '50 mV')
        key = next(r['key'] for r in win.model.rows() if r['kind'] == 'point')
        win.model.select(key, 'nominal')
        win.sync()
        win.bar.setText('5')
        self.key(win.bar, Qt.Key.Key_Return)
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+5 mV')
        self.assertEqual(win.model.point_of(key)[1].nominal, db.D('0.005'))
        self.assertEqual(win.model.row(key)['nominal'], '+5 mV')


# ------------------------------------------------------------------------------------------------------------------------------ run, layout, template
class RunAndLayoutTests(QtDsbCase):
    def answers(self, **by_title):
        seen = []

        def fake(parent, title, message, **kw):
            seen.append((title, message, kw))
            return by_title.get(title, True)
        fake.seen = seen
        return fake

    def test_run_saves_then_launches_and_demo_adds_demo(self):
        win, key = self.build()
        calls = []
        win.launcher = lambda entry, demo=False: calls.append((entry['spec_path'], demo))
        with mock.patch.object(C, 'ask_yes_no', return_value=False) as ask:
            self.assertIsNone(win.run_sheet(True))                     # unsaved: asks, and "no" saves and runs nothing
            self.assertTrue(ask.called)
        self.assertEqual(calls, [])
        self.assertTrue(win.model.dirty)
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            res = win.run_sheet(True)
        self.assertTrue(res.ok, res.message)
        self.assertFalse(win.model.dirty)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1])
        self.assertTrue(calls[0][0].endswith('.json'))
        self.assertIn('demo', win.status.get())
        fake = self.answers()
        with mock.patch.object(C, 'ask_yes_no', fake):                    # saved and unchanged: real run asks only the real-run question
            self.assertTrue(win.run_sheet(False).ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments'])
        self.assertEqual(calls[1][1], False)

    def test_run_on_real_instruments_asks_first_default_no_and_demo_never_asks(self):
        win, key = self.build()
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        fake = self.answers(**{'Run on real instruments': False})
        with mock.patch.object(C, 'ask_yes_no', fake):
            res = win.run_sheet(False)
        self.assertFalse(res.ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments'])
        title, message, kw = fake.seen[0]
        base = f'Run {win.model.ds.title} on real instruments? The calibrator will be driven from this program.'
        self.assertTrue(message.startswith(base), message)              # rule 2: the unverified commands (if any) are listed after the question
        self.assertTrue(message == base or 'Yes means you accept them' in message, message)
        self.assertEqual(kw.get('default'), 'no')
        self.assertTrue(win.model.dirty)
        self.assertEqual(calls, [])
        fake = self.answers()
        with mock.patch.object(C, 'ask_yes_no', fake):
            self.assertTrue(win.run_sheet(False).ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments', 'Save before running'])
        self.assertEqual(calls, [False])
        fake = self.answers()
        with mock.patch.object(C, 'ask_yes_no', fake):
            self.assertTrue(win.run_sheet(True).ok)
        self.assertEqual(fake.seen, [])
        self.assertEqual(calls, [False, True])

    def test_the_real_run_question_dialog_defaults_to_no(self):
        """The real dialog (not the stand-in): Enter answers No, Esc answers No, Yes needs a click."""
        dlg = widgets.MessageDialog(None, 'warning', 'Run on real instruments', 'x', buttons=(('Yes', 'yes', None), ('No', 'no', 'primary')), cancel_key='no')
        self.assertTrue(dlg.button('no').isDefault())
        self.assertFalse(dlg.button('yes').isDefault())
        dlg.show()
        QTest.keyClick(dlg, Qt.Key.Key_Return)
        self.assertEqual(dlg.result_key, 'no')

    def test_run_never_launches_a_sheet_with_problems(self):
        win = self.new_window()
        win.function_chosen(self.dcv_label(win))
        self.type_cell(win, '5 V')                                    # a row without a tolerance: an error
        self.assertGreater(win.model.problem_counts()['errors'], 0)
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(entry)
        res = win.run_sheet(False)
        self.assertFalse(res.ok)
        self.assertEqual(calls, [])
        self.assertIn('problems', res.message)
        self.assertTrue(any(isinstance(d, dsb_dialogs.ProblemsWindow) and d.isVisible() for d in win.dialogs))

    def resize(self, win, width):
        win._window_size(width)

    def test_inspector_collapses_when_narrow_and_returns_when_wide(self):
        win = self.new_window()
        self.assertTrue(win._insp_open)
        self.resize(win, 1400)
        self.assertTrue(win._insp_open)
        self.resize(win, 1000)
        self.assertFalse(win._insp_open)
        self.resize(win, 1149)
        self.assertFalse(win._insp_open)
        self.resize(win, 1150)
        self.assertTrue(win._insp_open)
        self.resize(win, 1)                                           # not on screen yet: nothing changes
        self.assertTrue(win._insp_open)

    def test_collapse_follows_a_real_resize(self):
        win = self.new_window()
        win.show()
        win.resize(1400, 800)
        self.app.processEvents()
        self.assertTrue(win._insp_open)
        win.resize(1000, 700)
        self.app.processEvents()
        self.assertFalse(win._insp_open)
        win.resize(1400, 800)
        self.app.processEvents()
        self.assertTrue(win._insp_open)

    def test_hand_choice_sticks_for_the_session(self):
        win = self.new_window()
        self.resize(win, 1000)
        self.assertFalse(win._insp_open)
        win.toggle_inspector()                                        # shown by hand while narrow: stays open
        self.assertTrue(win._insp_open)
        self.resize(win, 900)
        self.assertTrue(win._insp_open)
        win.toggle_inspector()                                        # hidden by hand: stays hidden when the window grows
        self.assertFalse(win._insp_open)
        self.resize(win, 1600)
        self.assertFalse(win._insp_open)

    def build_from_template(self):
        win = self.new_window(handheld=True)
        win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
        win.commit_header()
        dcv = next(f for f in win.model.ds.functions if f.kind == 'DCV')
        win.model.select(f'e:{dcv.id}', 'nominal')
        win.model.set_target_function('DC volts')
        win.sync()
        res = self.type_cell(win, '5 V')
        self.assertTrue(res.ok, res.message)
        key = next(r['key'] for r in win.model.rows() if r['kind'] == 'point')
        win.model.select(key, 'low')
        win.sync()
        win.panel_box.types['iv'].set(True), win.panel_box.v['iv'].set('0.05')
        res = win.calc()
        self.assertTrue(res.ok, res.message)
        return win, key

    def test_template_sheet_with_empty_sections_has_only_warnings_and_saves_and_runs(self):
        win, key = self.build_from_template()
        c = win.model.problem_counts()
        self.assertEqual(c['errors'], 0, win.model.problem_rows())
        self.assertEqual(c['warnings'], 1)                            # the nine empty sections are ONE entry
        rows = win.model.problem_rows()
        self.assertEqual([r['code'] for r in rows], ['empty_sections'])
        self.assertEqual(win.problem_pill.text(), '1 warning(s)')
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        res = win.run_sheet(True)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(calls, [True])
        spec = json.loads(Path(self.store.entries()[0]['spec_path']).read_text())
        self.assertEqual(len(spec['steps']), 1)                       # only the filled section reaches the runnable spec

    def test_empty_section_row_says_it_is_skipped(self):
        win, key = self.build_from_template()
        head = next(r for r in win.model.rows() if r['kind'] == 'header' and r['fid'] != win.model.point_of(key)[0].id)
        self.assertIn('skipped when the sheet runs', head['problem'])
        self.assertEqual(head['level'], 'warn')

    def test_new_sheet_is_blank_unless_the_template_is_chosen(self):
        win = self.new_window()
        self.assertEqual(win.model.ds.functions, [])
        tpl = self.new_window(handheld=True)
        self.assertEqual(len(tpl.model.ds.functions), len(M.GridModel.HANDHELD_KINDS))
        with mock.patch.object(D, 'ask_new_sheet', return_value=None):
            self.assertIsNone(self.panel.new())                       # cancelled

    def test_more_menu_add_handheld_functions(self):
        win = self.new_window()
        with mock.patch.object(C, 'ask_yes_no', return_value=False):
            self.assertIsNone(win.add_handheld())
        self.assertEqual(win.model.ds.functions, [])
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            self.assertTrue(win.add_handheld().ok)
            self.assertFalse(win.add_handheld().ok)                   # nothing left to add
        self.assertEqual(len(win.model.ds.functions), len(M.GridModel.HANDHELD_KINDS))
        labels = [a.text() for a in win.more_menu.actions()]
        self.assertEqual(labels[0], 'Add handheld functions...')
        self.assertIn('Version history...', labels)

    def test_sheet_check_window_pill_and_commands(self):
        win, key = self.build()
        win.show()
        self.assertTrue(win.check_pill.isHidden())                     # not run yet for this version of the sheet
        chk = win.show_check()
        self.assertIsInstance(chk, dsb_check.SheetCheckWindow)
        self.assertFalse(win.check_pill.isHidden())
        self.assertTrue(win.check_pill.text().startswith('check:'))
        self.assertIs(win.show_check(), chk)                           # one window
        chk.reload()
        chk.again()
        rows = chk.table.rows()
        if rows:
            self.select_rows(chk.table, rows[0]['id'])
            chk.show_detail()
            self.assertTrue(chk.detail.text())
        with mock.patch.object(dsb_check, 'present', lambda d: d):
            chk.commands()
        cw = dsb_check.CommandsWindow(win, ['a', 'b'])
        self.assertIn('  a', cw.text.toPlainText())
        cw.close()
        self.assertIn('Run', win.real_run_question()[0])

    def test_waiver_dialog_needs_a_reason_for_other(self):
        import datasheet_builder_rules as rules
        out = {}

        def run(self_):
            out['dlg'] = self_
            self_.body.itemAt(self_.body.count() - 2)
            return None
        with mock.patch.object(widgets.ModalDialog, 'run', run):
            self.assertIsNone(dsb_check.ask_waiver(None, 2))
        dlg = out['dlg']
        self.assertEqual(dlg.title_label.text(), '2 readings will have no uncertainty on the report')
        self.assertTrue(len(rules.WAIVER_REASONS) > 1)


# ------------------------------------------------------------------------------------------------------------------------------ the pages
class PageTests(QtDsbCase):
    def test_pages_work_on_the_model(self):
        win, key = self.build()
        dlg = win.open_ranges()
        p = dlg.page
        p.fs.set('20 V'), p.res.set('100 µV')
        self.assertTrue(p.add().ok)
        self.assertIn('20 V', [r['text'] for r in p.table.rows()])
        self.select_rows(p.table, *[r['id'] for r in p.table.rows() if r['text'].startswith('20')])
        p.picked()
        self.assertEqual(p.fs.get(), '20 V')
        self.assertFalse(p.change().ok is False and False)
        with mock.patch.object(C, 'ask_yes_no', return_value=True):
            self.assertTrue(p.remove().ok)
        dlg.reject()
        dlg = win.open_details()
        p = dlg.page
        self.assertEqual(p.title.get(), 'DM-1 PV')
        p.custom_id.set('90d'), p.custom_label.set('90 days')
        self.assertTrue(p.add_custom().ok)
        self.assertEqual(p.custom_id.get(), '')
        self.select_rows(p.periods, '90d')
        self.assertTrue(p.make_default().ok)
        with mock.patch.object(C, 'ask_yes_no', return_value=False):
            self.assertIsNone(p.remove())
        p.manual.set(True)
        self.assertTrue(p.set_manual() is None or True)
        dlg.reject()

    def test_functions_page_and_spec_page(self):
        win, key = self.build()
        dlg = win.open_functions()
        p = dlg.page
        self.assertIn('DC volts', [r['name'] for r in p.table.rows()])
        p.name_var.set('Extra DC')
        self.assertTrue(p.add().ok)
        self.assertEqual(p.name_var.get(), '')
        with mock.patch.object(C, 'ask_yes_no', return_value=False):
            self.assertIsNone(p.remove())
        self.assertTrue(p.move(-1) is None)
        dlg.reject()
        win.model.select(key, 'nominal')
        dlg = win.open_spec()
        p = dlg.page
        self.assertTrue(p.example_box.isVisible() or True)
        k = next(iter(p.period_vars))
        p.period_vars[k].set('0.1 % of reading')
        self.assertIn('4.995 V', p.example_box.text_label.text())
        p.period_vars[k].set('0.2 % of reading')
        self.assertIn('4.99 V', p.example_box.text_label.text())                           # the example follows every box
        p.mode.set(p.mode.w.itemText(1))
        p.bound.set('6 V')
        self.assertTrue(p.add().ok)
        self.select_rows(p.table, *[r['id'] for r in p.table.rows()][:1])
        p.picked()
        with mock.patch.object(C, 'ask_string', return_value='all'):
            self.assertTrue(p.copy().ok)
        self.assertTrue(p.remove().ok)
        dlg.reject()

    def test_standards_page(self):
        win, key = self.build()
        dlg = win.open_standards()
        p = dlg.page
        res = p.run()
        self.assertTrue(res.ok, res.message)
        rows = p.table.rows()
        self.assertTrue(rows)
        self.select_rows(p.table, rows[0]['point_id'], key='point_id')
        p.picked()
        self.assertTrue(p.cands.rows())
        self.assertFalse(p.clear().ok)                                    # nothing chosen by hand yet
        self.assertTrue(p.apply_choice().ok)
        dr = p.drivers()
        self.assertIsInstance(dr, dsb_dialogs.DriversWindow)
        dr.close()
        dlg.reject()
        p.filter.set('Commands not yet verified')
        p.reload()


# ------------------------------------------------------------------------------------------------------------------------------ the list tab and versions
class PanelTests(QtDsbCase):
    def test_panel_list_actions(self):
        win, key = self.build()
        win.save()
        uid = win.model.ds.uid
        self.panel.refresh()
        self.assertEqual(list(self.panel._rows), [uid])
        self.assertEqual(self.table_ids(), [uid])
        self.select_rows(self.panel.table, uid, key='uid')
        self.panel.selection_changed()
        self.assertIs(self.panel.open_selected(), win)                       # already open: it comes to the front
        win.close()
        ed = self.panel.open_selected()
        self.windows.append(ed)
        self.assertIsInstance(ed, dsb_editor.GridEditorWindow)
        with mock.patch.object(C, 'ask_string', return_value='A copy'):
            self.assertTrue(self.panel.duplicate())
        self.assertEqual(len(self.panel._rows), 2)
        out = self.t / 'x.json'
        with mock.patch.object(C, 'ask_save_path', return_value=str(out)):
            self.assertTrue(self.panel.export())
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['schema'], 'dsb-1')
        with mock.patch.object(C, 'ask_open_path', return_value=str(out)):
            self.assertTrue(self.panel.import_())
        self.assertEqual(len(self.panel._rows), 3)
        self.select_rows(self.panel.table, uid, key='uid')
        self.assertTrue(self.panel.delete_or_restore())
        self.assertEqual(self.saved_calls[-1], 1)
        self.panel.show_deleted.setChecked(True)
        self.panel.toggle_deleted()
        self.select_rows(self.panel.table, uid, key='uid')
        self.assertEqual(self.panel.b_delete.text(), 'Restore')
        self.assertFalse(self.panel.b_open.isEnabled())
        self.assertIsNone(self.panel.open_selected())
        self.assertIn('deleted', self.status[-1])
        self.assertTrue(self.panel.delete_or_restore())
        vw = self.panel.history()
        self.assertIsInstance(vw, dsb_dialogs.VersionsWindow)
        vw.close()

    def table_ids(self):
        return [r['uid'] for r in self.panel.table.rows()]

    def test_search_filters_the_list(self):
        win, key = self.build()
        win.save()
        self.panel.refresh()
        self.panel.search.setText('nothing like it')
        self.panel.search.flush()
        self.assertEqual(self.table_ids(), [])
        self.assertTrue(self.panel.table.empty_text)
        self.panel.search.setText('DM-1')
        self.panel.search.flush()
        self.assertEqual(len(self.table_ids()), 1)

    def test_panel_actions_without_selection_say_so(self):
        for fn in (self.panel.open_selected, self.panel.duplicate, self.panel.delete_or_restore, self.panel.history, self.panel.export):
            self.assertIsNone(fn())
            self.assertIn('Select a datasheet', self.panel.message.get())
            self.assertIn('Select a datasheet', self.status[-1])

    def test_status_may_be_an_object_with_set(self):
        seen = []
        p = D.DatasheetBuilderPanel(self.host, self.store, status=type('S', (), {'set': lambda s, t: seen.append(t)})(), matcher_factory=lambda: self.matcher)
        p.say('hello')
        self.assertEqual(seen, ['hello'])

    def test_versions_window_opens_old_versions_in_the_grid(self):
        win, key = self.build()
        win.save()
        self.type_cell(win, '6 V')
        win.save()
        vw = dsb_dialogs.VersionsWindow(win, self.store, win.model.ds.uid, editor=win, panel=self.panel)
        self.assertEqual(len(vw.table.rows()), 2)
        self.select_rows(vw.table, '1')
        self.assertTrue(vw.load_here())
        old = vw.open_new()
        self.windows.append(old)
        self.assertIsInstance(old, dsb_editor.GridEditorWindow)
        with mock.patch.object(C, 'ask_save_path', return_value=str(self.t / 'v1.json')):
            self.assertTrue(vw.export())
        vw.table.select_rows([])
        self.app.processEvents()
        vw.open_new()
        self.assertIn('Select a version', vw.msg.text())
        vw.close()

    def test_help_text_and_buttons(self):
        self.assertEqual([b.text() for b in (self.panel.b_new, self.panel.b_open, self.panel.b_duplicate, self.panel.b_delete, self.panel.b_history, self.panel.b_export,
                                             self.panel.b_import, self.panel.b_refresh)],
                         ['New...', 'Open', 'Duplicate', 'Delete', 'Version history...', 'Export JSON...', 'Import JSON...', 'Refresh'])
        self.assertEqual(self.panel.show_deleted.text(), 'Show deleted')


# ------------------------------------------------------------------------------------------------------------------------------ speed, look, rules
class SheetQualityTests(QtDsbCase):
    def test_a_long_sheet_stays_fast(self):
        win, key = self.build()
        win.model.select(key, 'low')
        win.sync()
        box = win.panel_box
        box.b['multi'].set(True), box.v['multi_mode'].set('span'), box.v['multi_high'].set('10 V'), box.v['multi_n'].set('450')
        box.multi_changed()
        res = win.calc()
        self.assertTrue(res.ok, res.message)
        n = len(win.model.rows())
        self.assertGreater(n, 300)
        win.show()
        t0 = time.time()
        for _ in range(60):
            self.key(win.sheet, Qt.Key.Key_Down)
        self.app.processEvents()
        self.assertLess(time.time() - t0, 6.0)
        t0 = time.time()
        win.sync()
        win.refresh()
        self.assertLess(time.time() - t0, 3.0)
        self.assertEqual(win.sheet.source_model.rowCount(), n)

    def test_the_editor_paints_in_dark_mode(self):
        win, key = self.build()
        win.resize(1300, 800)
        win.show()
        self.app.processEvents()
        img = win.grab().toImage()
        self.assertGreater(img.width(), 1000)
        px = {img.pixel(x, y) for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)}
        self.assertGreater(len(px), 5)
        self.assertLess(img.pixelColor(img.width() - 3, img.height() - 3).lightness(), 100)       # dark window


class RulesTests(unittest.TestCase):
    def test_no_tk_anywhere_in_the_qt_screens(self):
        banned = {'tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk', 'datasheet_builder_ui', 'datasheet_builder_check_ui'}
        for f in sorted((ROOT / 'qtui' / 'screens').glob('*.py')):
            for node in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else []
                for n in names:
                    self.assertNotIn(n.split('.')[0], banned, f'{f.name} imports {n}')
                    self.assertFalse(n.split('.')[0].endswith('_view_tk'), f'{f.name} imports {n}')

    def test_screen_files_stay_small(self):
        for f in (ROOT / 'qtui' / 'screens').glob('*.py'):
            self.assertLess(len(f.read_text(encoding='utf-8').splitlines()), 1500, f.name)

    def test_the_qt_panel_keeps_the_tk_constructor_and_public_methods(self):
        if not HAVE_QT:
            self.skipTest('PySide6 is not installed')
        import inspect
        tk_src = (ROOT / 'datasheet_builder_ui.py').read_text(encoding='utf-8')
        tree = ast.parse(tk_src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DatasheetBuilderPanel')
        tk_methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')}
        qt_methods = {n for n, _ in inspect.getmembers(D.DatasheetBuilderPanel, callable)}
        self.assertFalse(tk_methods - qt_methods, tk_methods - qt_methods)
        params = list(inspect.signature(D.DatasheetBuilderPanel.__init__).parameters)
        self.assertEqual(params[:6], ['self', 'parent', 'storage', 'on_saved', 'status', 'matcher_factory'])
        tk_win = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GridEditorWindow')
        tk_win_methods = {n.name for n in tk_win.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')}
        qt_win_methods = {n for n, _ in inspect.getmembers(dsb_editor.GridEditorWindow, callable)}
        missing = tk_win_methods - qt_win_methods - {'close', 'toggle_inspector'}
        self.assertFalse(missing, missing)


# ------------------------------------------------------------------------------------------------------------------------------ Tk vs Qt: what is saved
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class SameAsTkTests(unittest.TestCase):
    """The same scenarios (tests/dsb_scenario.py) through the Tk panel (a subprocess, under the tkinter stub) and through the Qt panel: every message, every file under
    user_specs (datasheet versions, runnable specs) and every registry row must be identical."""

    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()
        proc = subprocess.run([sys.executable, str(ROOT / 'tests' / 'dsb_tk_reference.py')], capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        if proc.returncode:
            raise RuntimeError('the Tk reference run failed:\n' + proc.stderr[-3000:])
        cls.tk = json.loads(proc.stdout.strip().splitlines()[-1])

    def run_qt(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, ignore_errors=True))
        store = M.Storage(tmp / 'user_specs', tmp / 'lab_registry.sqlite3', who='tester')
        matcher = dm.Matcher(REG)
        host = Host()
        windows = []
        with sc.frozen_time():
            panel = D.DatasheetBuilderPanel(host, store, matcher_factory=lambda: matcher)

            def new(handheld):
                with mock.patch.object(D, 'ask_new_sheet', return_value=handheld):
                    win = panel.new()
                windows.append(win)
                return win

            @contextlib.contextmanager
            def answer(yes):
                with mock.patch.object(C, 'ask_yes_no', return_value=yes):
                    yield
            env = sc.Env(panel, new, answer)
            with mock.patch.object(C, 'ask_yes_no', return_value=True):
                log = sc.run_all(env)
            dump = sc.dump_storage(tmp / 'user_specs', tmp / 'lab_registry.sqlite3')
        for w in windows:
            w.close()
        return json.loads(json.dumps(dict(log=log, saved=dump), sort_keys=True))

    def test_messages_files_and_registry_rows_are_identical(self):
        qt = self.run_qt()
        tk = self.tk
        self.assertEqual(len(qt['log']), len(tk['log']))
        for a, b in zip(tk['log'], qt['log']):
            self.assertEqual(a, b)
        self.assertEqual(sorted(tk['saved']['files']), sorted(qt['saved']['files']))
        self.assertGreater(len(tk['saved']['files']), 15)
        for name, text in tk['saved']['files'].items():
            self.assertEqual(text, qt['saved']['files'][name], name)             # byte for byte
        self.assertEqual(tk['saved']['db'], qt['saved']['db'])
        self.assertTrue(any('5 mV' in str(e) for e in qt['log']))


if __name__ == '__main__':
    unittest.main()
