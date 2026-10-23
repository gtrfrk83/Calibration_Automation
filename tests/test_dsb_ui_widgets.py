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
        win.lock_v.set('Locked')
        win.lock_chosen()
        win.model.select(key, 'nominal')
        win.sync()
        self.assertFalse(win.model.cell_editable()[0])
        win.lock_v.set('Edit Mode')
        win.lock_chosen()
        self.assertTrue(win.model.cell_editable()[0])

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

    # ---- layout B: inspector, status line, Run buttons, handheld template
    def test_inspector_follows_the_selected_row_and_hides(self):
        win, key = self.build()
        box = win.panel_box
        self.assertIsInstance(box, self.ui.Inspector)
        self.assertIs(self.ui.SpecPanel, self.ui.Inspector)
        win.model.select(key, 'tol')
        win.sync()
        self.assertEqual(box.v['func'].get(), 'DC volts')
        self.assertTrue(box.types['iv'].get())
        header = next(r['key'] for r in win.model.rows() if r['kind'] == 'header')
        win.model.select(header, 'function')
        win.sync()                                                    # a section heading: the panel shows only the section rules
        self.assertIn('section heading', win.status.get())
        win.toggle_inspector()
        self.assertFalse(win._insp_open)
        win.toggle_inspector()
        self.assertTrue(win._insp_open)

    def test_one_status_line_carries_messages_then_row_problems(self):
        win, key = self.build()
        win.model.select(key, 'nominal')
        win.sync()
        win.bar_v.set('abc')
        win.commit_bar('down')
        self.assertTrue(win.status.get().startswith('Cannot do that'))
        win.model.select(key, 'step')
        win.sync()                                                    # moving the selection clears the old message
        self.assertFalse(win.status.get().startswith('Cannot do that'))
        win.sheet_key(Ev('x', 'x'))
        self.assertEqual(win.status.get(), win.issue.get())

    def answers(self, **by_title):
        """askyesno stand-in: answers by dialog title (default True) and records (title, message, kwargs)."""
        seen = []

        def fake(title, message, **kw):
            seen.append((title, message, kw))
            return by_title.get(title, True)
        fake.seen = seen
        return fake

    def test_run_saves_then_launches_and_demo_adds_demo(self):
        win, key = self.build()
        calls = []
        win.launcher = lambda entry, demo=False: calls.append((entry['spec_path'], demo))
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=False) as ask:
            self.assertIsNone(win.run_sheet(True))                     # unsaved: asks, and "no" saves and runs nothing
            self.assertTrue(ask.called)
        self.assertEqual(calls, [])
        self.assertTrue(win.model.dirty)
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            res = win.run_sheet(True)
        self.assertTrue(res.ok, res.message)
        self.assertFalse(win.model.dirty)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1])
        self.assertTrue(calls[0][0].endswith('.json'))
        self.assertIn('demo', win.status.get())
        fake = self.answers()
        with mock.patch.object(self.ui.messagebox, 'askyesno', fake):   # saved and unchanged: real run asks only the real-run question
            self.assertTrue(win.run_sheet(False).ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments'])
        self.assertEqual(calls[1][1], False)

    def test_run_on_real_instruments_asks_first_default_no_and_demo_never_asks(self):
        win, key = self.build()
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        # unsaved sheet: the real-run question comes first; answering No stops everything (no save, no launch)
        fake = self.answers(**{'Run on real instruments': False})
        with mock.patch.object(self.ui.messagebox, 'askyesno', fake):
            res = win.run_sheet(False)
        self.assertFalse(res.ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments'])
        title, message, kw = fake.seen[0]
        self.assertEqual(message, f'Run {win.model.ds.title} on real instruments? The calibrator will be driven from this program.')
        self.assertEqual(kw.get('default'), 'no')
        self.assertTrue(win.model.dirty)
        self.assertEqual(calls, [])
        # Yes: then the save question, then it launches
        fake = self.answers()
        with mock.patch.object(self.ui.messagebox, 'askyesno', fake):
            self.assertTrue(win.run_sheet(False).ok)
        self.assertEqual([s[0] for s in fake.seen], ['Run on real instruments', 'Save before running'])
        self.assertEqual(calls, [False])
        # demo: no real-run question at all
        fake = self.answers()
        with mock.patch.object(self.ui.messagebox, 'askyesno', fake):
            self.assertTrue(win.run_sheet(True).ok)
        self.assertEqual(fake.seen, [])
        self.assertEqual(calls, [False, True])

    def resize(self, win, width):
        win._window_size(type('E', (), dict(widget=win, width=width, height=700))())

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

    def test_ctrl_i_is_a_hand_choice_too(self):
        win = self.new_window()
        win.toggle_inspector()
        self.assertFalse(win._insp_open)
        self.resize(win, 1500)
        self.assertFalse(win._insp_open)

    def build_from_template(self):
        """A handheld-template sheet with ONE row filled (DC volts); the nine other sections stay empty."""
        with mock.patch.object(self.ui, 'ask_new_sheet', return_value=True):
            win = self.panel.new()
        win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
        win.commit_header()
        dcv = next(f for f in win.model.ds.functions if f.kind == 'DCV')
        win.model.select(f'e:{dcv.id}', 'nominal')
        win.model.set_target_function('DC volts')
        win.sync()
        res = self.type_cell(win, '5 V')
        self.assertTrue(res.ok, res.message)
        key = next(r['key'] for r in win.model.rows() if r['kind'] == 'point')
        win.model.select(key, 'tol')
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
        self.assertIn('9 sections', rows[0]['text'])
        self.assertIn('skipped', rows[0]['text'])
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(demo)
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            res = win.run_sheet(True)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(calls, [True])
        entry = self.store.entries()[0]
        spec = json.loads(Path(entry['spec_path']).read_text())
        self.assertEqual(len(spec['steps']), 1)                       # only the filled section reaches the runnable spec

    def test_empty_section_row_says_it_is_skipped(self):
        win, key = self.build_from_template()
        head = next(r for r in win.model.rows() if r['kind'] == 'header' and r['fid'] != win.model.point_of(key)[0].id)
        self.assertIn('skipped when the sheet runs', head['problem'])
        self.assertEqual(head['level'], 'warn')

    def test_run_never_launches_a_sheet_with_problems(self):
        win = self.new_window()
        win.function_chosen(self.dcv_label(win))
        self.type_cell(win, '5 V')                                    # a row without a tolerance: an error
        self.assertGreater(win.model.problem_counts()['errors'], 0)
        calls = []
        win.launcher = lambda entry, demo=False: calls.append(entry)
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            res = win.run_sheet(False)
        self.assertFalse(res.ok)
        self.assertEqual(calls, [])
        self.assertIn('problems', res.message)

    def test_launch_process_uses_the_managers_command_line(self):
        import dsb_manager
        seen = {}
        dsb_manager.launch_process(dict(spec_path='/x/y.json'), demo=True, popen=lambda args, cwd=None: seen.update(args=args, cwd=cwd))
        self.assertEqual(seen['args'][1:], [str(dsb_manager.BASE / dsb_manager.LAUNCHER), '--spec', '/x/y.json', '--demo'])
        self.assertTrue(seen['cwd'].endswith('Procedures'))

    def test_new_sheet_is_blank_unless_the_template_is_chosen(self):
        win = self.panel.new()                                        # the stub dialog is not answered: blank, as before
        self.assertEqual(win.model.ds.functions, [])
        with mock.patch.object(self.ui, 'ask_new_sheet', return_value=True):
            tpl = self.panel.new()
        self.assertEqual(len(tpl.model.ds.functions), len(M.GridModel.HANDHELD_KINDS))
        with mock.patch.object(self.ui, 'ask_new_sheet', return_value=None):
            self.assertIsNone(self.panel.new())                       # cancelled

    def test_more_menu_add_handheld_functions(self):
        win = self.new_window()
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=False):
            self.assertIsNone(win.add_handheld())
        self.assertEqual(win.model.ds.functions, [])
        with mock.patch.object(self.ui.messagebox, 'askyesno', return_value=True):
            self.assertTrue(win.add_handheld().ok)
            self.assertFalse(win.add_handheld().ok)                   # nothing left to add
        self.assertEqual(len(win.model.ds.functions), len(M.GridModel.HANDHELD_KINDS))

    def test_helpers(self):
        self.assertEqual(self.ui.selected(object()), ())
        self.assertEqual(self.ui.label_of([('a', 'A'), ('b', 'B')], 'b'), 'B')
        self.assertEqual(self.ui.value_of([('a', 'A'), ('b', 'B')], 'B'), 'b')


if __name__ == '__main__':
    unittest.main()
