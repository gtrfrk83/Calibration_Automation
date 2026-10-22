"""datasheet_builder_ui widgets under tests/_tk_stub.py: only proves the module imports, every widget class constructs and every handler runs and
reaches the model without raising.  It does NOT show what the windows look like: that has never been checked on a real display.
(The file name sorts after test_beta on purpose: installing the stub earlier would turn test_beta's import error into running tests.)"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
tk_stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tk_stub)
STUBBED = tk_stub.install()

import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402


class Ev:
    """A key or mouse event as Tk would give it."""

    def __init__(self, keysym='', char='', state=0, x=0, y=0):
        self.keysym, self.char, self.state, self.x, self.y, self.delta = keysym, char, state, x, y, 0


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class GridWidgetStubTests(unittest.TestCase):
    def setUp(self):
        import datasheet_builder_ui as ui_mod
        self.ui = ui_mod
        patcher = mock.patch.object(ui_mod.ui, 'fit_window')          # window sizing needs screen metrics, which the stub does not have
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.store = M.Storage(self.t / 'user_specs', self.t / 'lab_registry.sqlite3', who='tester')
        self.matcher = dm.Matcher(REG)
        self.tk = ui_mod.tk
        self.called_on_saved = []
        self.panel = ui_mod.DatasheetBuilderPanel(self.tk.Frame(), self.store, on_saved=lambda: self.called_on_saved.append(1), status=self.tk.StringVar(),
                                                  matcher_factory=lambda: self.matcher)

    def tearDown(self):
        self.tmp.cleanup()

    def sel(self, *ids):
        return mock.patch.object(self.ui, 'selected', return_value=tuple(ids))

    def new_window(self):
        win = self.panel.new()
        self.assertIsInstance(win, self.ui.GridEditorWindow)
        return win

    def dcv_label(self, win):
        return next(c['label'] for c in win.model.function_choices() if c['kind'] == 'DCV' and not c['fid'])

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
        win.model.select(key, 'tol')
        win.sync()
        box = win.panel_box
        box.types['iv'].set(True), box.v['iv'].set('0.05')
        res = win.calc()
        self.assertTrue(res.ok, res.message)
        return win, key

    # ---- the flow
    def test_construct_and_build_a_sheet_through_the_handlers(self):
        win, key = self.build()
        fn, p = win.model.point_of(key)
        self.assertIsNotNone(p.spec)
        self.assertEqual(win.model.problem_counts()['errors'], 0)
        res = win.save()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.called_on_saved, [1])
        self.assertFalse(win.model.dirty)
        self.assertEqual(self.store.entries()[0]['tag'], 'user-built')
        self.assertTrue(win.close())

    def test_keyboard_navigation_and_typing_start_editing(self):
        win, key = self.build()
        win.model.select(key, 'function')
        self.assertEqual(win.sheet_key(Ev('Right')), 'break')
        self.assertEqual(win.model.sel_col, 'nominal')
        self.assertEqual(win.sheet_key(Ev('Tab')), 'break')
        self.assertEqual(win.model.sel_col, 'tol')
        self.assertEqual(win.sheet_key(Ev('Down')), 'break')
        self.assertEqual(win.sheet_key(Ev('Up')), 'break')
        self.assertEqual(win.sheet_key(Ev('Return')), 'break')           # starts editing: focus goes to the Edit Cell bar
        win.model.select(key, 'nominal')
        win.sync()
        self.assertEqual(win.sheet_key(Ev('7', '7')), 'break')
        self.assertEqual(win.bar_v.get(), '7')
        self.assertIsNone(win.sheet_key(Ev('c', 'c', state=0x4)))        # Ctrl+C is left alone
        win.model.select(key, 'step')
        win.sync()
        self.assertEqual(win.sheet_key(Ev('x', 'x')), 'break')           # a read-only cell: a reason, no edit
        self.assertTrue(win.issue.get())

    def test_edit_cell_bar_enter_escape_and_undo(self):
        win, key = self.build()
        before = win.model.cell_text(key, 'nominal')
        win.model.select(key, 'nominal')
        win.sync()
        win.bar_v.set('6 V')
        win.commit_bar('down')
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        win.undo()
        self.assertEqual(win.model.cell_text(key, 'nominal'), before)
        win.redo()
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')
        win.model.select(key, 'nominal')
        win.sync()
        win.bar_v.set('junk')
        win.cancel_bar()
        self.assertEqual(win.bar_v.get(), '+6 V')
        win.bar_v.set('abc')
        win.model.select(key, 'nominal')
        res = win.commit_bar('down')
        self.assertFalse(res.ok)                                         # an inline message, nothing changed
        self.assertTrue(win.note.get().startswith('Not done'))
        self.assertEqual(win.model.cell_text(key, 'nominal'), '+6 V')

    def test_mouse_selection_and_scroll(self):
        win, key = self.build()
        geo = win.sheet.geo
        x, y, _x1, _y1 = geo.box(1, 2)
        win.sheet._click(Ev(x=x + 3, y=y + 3))
        self.assertEqual(win.model.sel_col, 'nominal')
        win.sheet.scroll_cmd('scroll', 1, 'units')
        win.sheet.scroll_cmd('moveto', '0.0')
        win.sheet.redraw()

    def test_buttons_symbols_header_delete_remark_run_lock(self):
        win, key = self.build()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar_v.set('5 ')
        self.assertEqual(win.insert_symbol('±'), '±')
        self.assertEqual(win.insert_symbol('Units'), 'V')
        win.model.select(key, 'nominal')
        win.remark_v.set('use the short leads')
        win.remark_set()
        self.assertEqual(win.model.point_of(key)[1].note, 'use the short leads')
        win.run_v.set(False)
        win.run_set()
        self.assertFalse(win.model.point_of(key)[1].enabled)
        win.run_v.set(True)
        win.run_set()
        with mock.patch.object(self.ui, 'ask_choice', return_value='AC volts'):
            res = win.insert_header()
        self.assertTrue(res.ok, res.message)
        with mock.patch.object(self.ui, 'ask_choice', return_value=None):
            self.assertIsNone(win.insert_header())
        win.lock_v.set('Locked')
        win.lock_chosen()
        win.model.select(key, 'nominal')
        win.sync()
        self.assertFalse(win.model.cell_editable()[0])
        win.lock_v.set('Edit Mode')
        win.lock_chosen()
        self.assertTrue(win.model.cell_editable()[0])
        win.model.select(key, 'nominal')
        res = win.delete_row()
        self.assertTrue(res.ok, res.message)
        self.assertIsNone(win.model.point_of(key)[1])

    def test_recalc_copy_problems_and_preview(self):
        win, key = self.build()
        self.assertTrue(win.recalc().ok)
        win.copy_down()
        win.show_problems()
        prob = self.ui.ProblemsWindow(win)
        self.assertIsNone(prob.go())
        pv = win.preview()
        out = self.t / 'blank.pdf'
        with mock.patch.object(self.ui.filedialog, 'asksaveasfilename', return_value=str(out)):
            res = pv.save_pdf()
        self.assertTrue(res.ok, res.message)
        self.assertTrue(out.exists())
        with mock.patch.object(self.ui.filedialog, 'asksaveasfilename', return_value=''):
            self.assertIsNone(pv.save_pdf())

    def test_detail_pages_open_in_their_own_windows(self):
        win, key = self.build()
        for opener in (win.open_ranges, win.open_spec, win.open_functions, win.open_details, win.open_standards):
            dlg = opener()
            dlg.reload()
            dlg.close()
        win.refresh()                                                    # reloads whichever dialogs are still open
        self.ui.DriversWindow(win, win.model)
        win.open_calculator()
        win.model.select(key)
        win.open_calculator()

    def test_save_refused_offers_a_draft(self):
        win = self.new_window()
        win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
        win.commit_header()
        win.function_chosen(self.dcv_label(win))
        self.type_cell(win, '5 V')                                       # a row without any tolerance: one thing to fix
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=False):
            res = win.save()
        self.assertFalse(res.ok)
        self.assertEqual(self.store.entries(), [])
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            res = win.save()
        self.assertTrue(res.ok, res.message)
        win.close()

    def test_choice_dialog(self):
        dlg = self.ui.ChoiceDialog(self.tk.Frame(), 'T', 'Pick', ['a', 'b'])
        dlg.ok()
        self.assertEqual(dlg.value, 'a')

    def test_rule_dialog_edit_and_errors(self):
        win, key = self.build()
        fid = win.model.fid
        dlg = self.ui.RuleDialog(win, win.model, fid)
        dlg.v['type'].set('Typed points'), dlg.v['values'].set('5 apples')
        dlg.layout()
        dlg.ok()
        self.assertIsNone(dlg.outcome)
        self.assertTrue(dlg.msg.get())
        dlg.destroy()

    # ---- list tab and versions
    def test_panel_list_actions(self):
        win, key = self.build()
        win.save()
        uid = win.model.ds.uid
        self.panel.refresh()
        self.assertEqual(list(self.panel._rows), [uid])
        with self.sel(uid):
            self.panel.selection_changed()
            self.assertTrue(self.panel.open_selected())
            with mock.patch.object(self.ui.simpledialog, 'askstring', return_value='A copy'):
                self.assertTrue(self.panel.duplicate())
        self.assertEqual(len(self.panel._rows), 2)
        out = self.t / 'x.json'
        with self.sel(uid), mock.patch.object(self.ui.filedialog, 'asksaveasfilename', return_value=str(out)):
            self.assertTrue(self.panel.export())
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['schema'], 'dsb-1')
        with mock.patch.object(self.ui.filedialog, 'askopenfilename', return_value=str(out)):
            self.assertTrue(self.panel.import_())
        self.assertEqual(len(self.panel._rows), 3)
        with self.sel(uid):
            self.assertTrue(self.panel.delete_or_restore())
            self.panel.show_deleted.set(True)
            self.panel.toggle_deleted()
            self.assertIsNone(self.panel.open_selected())
            self.assertTrue(self.panel.delete_or_restore())
            self.assertTrue(self.panel.history())

    def test_panel_actions_without_selection_say_so(self):
        for fn in (self.panel.open_selected, self.panel.duplicate, self.panel.delete_or_restore, self.panel.history, self.panel.export):
            self.assertIsNone(fn())
            self.assertIn('Select a datasheet', self.panel.message.get())

    def test_versions_window_opens_old_versions_in_the_grid(self):
        win, key = self.build()
        win.save()
        win.type = None
        self.type_cell(win, '6 V')
        win.save()
        vw = self.ui.VersionsWindow(win, self.store, win.model.ds.uid, editor=win, panel=self.panel)
        with self.sel('1'):
            self.assertTrue(vw.load_here())
            self.assertIsInstance(vw.open_new(), self.ui.GridEditorWindow)
            with mock.patch.object(self.ui.filedialog, 'asksaveasfilename', return_value=str(self.t / 'v1.json')):
                self.assertTrue(vw.export())
        vw.open_new()
        self.assertIn('Select a version', vw.msg.get())

    def test_helpers(self):
        self.assertEqual(self.ui.selected(object()), ())
        self.assertEqual(self.ui.label_of([('a', 'A'), ('b', 'B')], 'b'), 'B')
        self.assertEqual(self.ui.value_of([('a', 'A'), ('b', 'B')], 'B'), 'b')


if __name__ == '__main__':
    unittest.main()
