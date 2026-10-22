"""datasheet_builder_ui widgets under tests/_tk_stub.py: only proves the module imports, every widget class constructs and every handler runs and
reaches the controller without raising.  It does NOT show what the windows look like: that has never been checked on a real display.
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
import specmanager as sm  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402


@unittest.skipUnless(STUBBED, 'real tkinter present: the stub test would need a display')
class WidgetStubTests(unittest.TestCase):
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
        self.factory = lambda: self.matcher
        self.tk = ui_mod.tk
        self.called_on_saved = []
        self.panel = ui_mod.DatasheetBuilderPanel(self.tk.Frame(), self.store, on_saved=lambda: self.called_on_saved.append(1), status=self.tk.StringVar(),
                                                  matcher_factory=self.factory)

    def tearDown(self):
        self.tmp.cleanup()

    def sel(self, *ids):
        return mock.patch.object(self.ui, 'selected', return_value=tuple(ids))

    # ---- the whole flow, through the page handlers
    def build_through_widgets(self):
        win = self.panel.new()
        self.assertIsInstance(win, self.ui.EditorWindow)
        header, funcs, ranges, spec, points, auto, review = win.pages
        header.make.set('Acme'), header.mdl.set('DM-1'), header.title.set('DM-1 PV'), header.notes.set('n')
        header.commit()
        self.assertEqual((win.model.ds.make, win.model.ds.title), ('Acme', 'DM-1 PV'))
        header.reload()
        win.go(1)
        funcs.reload()
        self.assertIn('DC volts (V)', ' '.join(funcs.kinds))
        funcs.kind_var.set(next(k for k, v in funcs.kinds.items() if v == 'DCV'))
        self.assertTrue(funcs.add())
        fid = win.model.fid
        win.go(2)
        ranges.reload()
        ranges.bulk.set('100 mV, 1 V, 10 V')
        self.assertTrue(ranges.add_many())
        ranges.fs.set('10 V'), ranges.res.set('10 uV')
        with self.sel('r10'):
            self.assertTrue(ranges.change())
        win.go(3)
        spec.reload()
        spec.period_vars['1y'].set('0.05 % of reading + 0.01 % of range')
        spec.range_var.set('All ranges')
        spec.update_example()
        self.assertTrue(spec.add())
        win.go(4)
        points.reload()
        dlg = self.ui.RuleDialog(win, win.model, fid)
        dlg.v['type'].set('Percent of range'), dlg.v['percents'].set('10, 50, 100'), dlg.bipolar.set(True)
        dlg.ok()
        self.assertIsNotNone(dlg.outcome, dlg.msg.get())
        points.reload()
        self.assertEqual(len(win.model.fn(fid).points), 18)
        return win, fid

    def test_construct_every_class_and_run_the_flow(self):
        win, fid = self.build_through_widgets()
        review = win.pages[6]
        auto = win.pages[5]
        win.go(5)
        auto.run()
        self.assertTrue(win.model.match_fresh())
        self.assertIn('18 of 18', auto.summary.get())
        with self.sel('dcv.r10.+5'):
            auto.picked()
            auto.choice.set(next(lab for v, lab in auto._choices if v == '5522A'))
            self.assertTrue(auto.apply_choice())
        self.assertEqual(win.model.ds.assignments, {'dcv.r10.+5': '5522A'})
        auto.clear()
        self.assertEqual(win.model.ds.assignments, {})
        self.ui.DriversWindow(win, win.model)
        win.go(6)
        review.reload()
        self.assertTrue(review.save())
        self.assertEqual(self.called_on_saved, [1])
        self.assertIn('user-built', review.result.get())
        self.assertFalse(win.model.dirty)
        self.assertEqual(self.store.entries()[0]['tag'], 'user-built')
        self.ui.VersionsWindow(win, self.store, win.model.ds.uid, editor=win)
        self.assertTrue(win.close())

    def test_navigation_undo_and_problem_jump(self):
        win, fid = self.build_through_widgets()
        self.assertTrue(win.go(5))                                   # points exist, so the automation step opens
        win.model.remove_spec_entry(fid, 0)
        win.refresh()
        self.assertGreater(win.model.problem_counts()['errors'], 0)
        win.go(6)
        review = win.pages[6]
        review.reload()
        with self.sel('0'):
            review.go_to()
        self.assertNotEqual(win.model.step, 6)
        win.undo()
        win.redo()
        win.next(), win.back()
        win.go(3)
        with self.sel('0'):
            win.open_problem()
        win.go(6)
        self.assertFalse(review.save())                              # gated by errors
        self.assertTrue(review.save_draft())
        win.close()                                                  # the stub answers yes to the "unsaved changes" question when dirty

    def test_header_and_functions_handlers(self):
        win = self.panel.new()
        header, funcs = win.pages[0], win.pages[1]
        header.preset.set('90d  (90 days)')
        self.assertTrue(header.add_preset())
        header.custom_id.set('2y'), header.custom_label.set('Two years')
        self.assertTrue(header.add_custom())
        with self.sel('90d'):
            self.assertTrue(header.make_default())
            self.assertTrue(header.remove())
        header.outward.set(True)
        header.set_rounding()
        self.assertEqual(win.model.ds.options['limit_rounding'], 'outward')
        header.reload()
        self.assertFalse(header.make_default())                      # nothing selected under the stub
        funcs.reload()
        for kind in ('DCV', 'ACV', 'GEN_AMPL', 'TEMP'):
            funcs.kind_var.set(next(k for k, v in funcs.kinds.items() if v == kind))
            self.assertTrue(funcs.add())
        with self.sel('acv'):
            funcs.picked()
        funcs.d_name.set('AC volts (rms)')
        self.assertTrue(funcs.apply())
        self.assertEqual(win.model.fn('acv').name, 'AC volts (rms)')
        funcs.move(-1)
        funcs.remove()
        self.assertEqual(len(win.model.ds.functions), 3)
        win.model.undo()

    def test_ranges_spec_points_handlers(self):
        win, fid = self.build_through_widgets()
        ranges, spec, points = win.pages[2], win.pages[3], win.pages[4]
        win.go(2)
        ranges.decimals.set('5'), ranges.dec_prefix.set('')
        ranges.use_decimals()
        self.assertEqual(ranges.res.get(), '10 µV')
        ranges.decimals.set('x')
        ranges.use_decimals()
        ranges.fs.set('50 V'), ranges.res.set('1 mV')
        self.assertTrue(ranges.add())
        with self.sel('r50'):
            ranges.picked()
            self.assertTrue(ranges.remove())
        with self.sel('r10'):
            self.assertTrue(ranges.remove())                         # asks (stub: yes) and removes with its points
        ranges.reload()
        win.model.undo()
        win.go(3)
        spec.reload()
        for key in spec.helper_buttons:
            spec.insert(key)
        spec.focus_key = '1y'
        spec.insert('pct_reading')
        spec.mode.set(M_MODE('low_only'))
        spec.bound.set('3')
        self.assertTrue(spec.add())
        with self.sel('1'):
            spec.picked()
            self.assertTrue(spec.change())
            with mock.patch.object(self.ui.simpledialog, 'askstring', return_value='1 V, 10 V'):
                self.assertTrue(spec.copy())
            self.assertTrue(spec.remove())
        win.go(4)
        points.reload()
        with self.sel('dcv.r10.+5'):
            points.picked()
            with mock.patch.object(self.ui.simpledialog, 'askstring', return_value='4.99 V, 5.01 V'):
                self.assertTrue(points.override())
            self.assertTrue(points.toggle_point())
            self.assertTrue(points.toggle_point())
        self.assertTrue(win.model.fn(fid).point('dcv.r10.+5').overrides)
        pd = self.ui.PointDialog(win, win.model, fid)
        pd.nominal.set('7 V')
        pd.ok()
        self.assertIsNotNone(pd.outcome, pd.msg.get())
        pd2 = self.ui.PointDialog(win, win.model, fid, pd.outcome.message and 'dcv.r10.+7')
        pd2.label.set('seven')
        pd2.ok()
        self.assertIsNotNone(pd2.outcome, pd2.msg.get())
        bad = self.ui.PointDialog(win, win.model, fid)
        bad.nominal.set('abc')
        bad.ok()
        self.assertIsNone(bad.outcome)
        self.assertTrue(bad.msg.get())
        with self.sel('dcv.r10.+7'):
            self.assertTrue(points.remove_point())
        rid = win.model.rule_rows(fid)[0]['id']
        with self.sel(rid):
            self.assertTrue(points.toggle_rule())
            self.assertTrue(points.toggle_rule())
            self.assertTrue(points.remove_rule())
        points.recalculate()
        points.only_problems.set(True)
        points.reload()

    def test_dialog_launchers_and_pickers_run(self):
        win, fid = self.build_through_widgets()
        points, funcs, ranges, spec, header = win.pages[4], win.pages[1], win.pages[2], win.pages[3], win.pages[0]
        win.go(4)
        points.add_rule(), points.add_point()                         # the dialogs open (the stub's wait_window returns at once)
        with self.sel('dcv.r10.+5'):
            points.edit_point()
        rid = win.model.rule_rows(fid)[0]['id']
        with self.sel(rid):
            points.edit_rule()
        points.period_var.set('1y')
        points.period_picked()
        with self.sel('dcv.r10.+5'):
            points.picked()
        self.assertFalse(points.edit_point())                         # nothing selected
        self.assertFalse(points.edit_rule())
        self.assertFalse(points.override())
        with self.sel('dcv'):
            funcs.picked()
        funcs.reload_detail()
        with self.sel('r10'):
            ranges.picked()
        ranges.fbar.var.set(next(iter(ranges.fbar.ids)))
        ranges.fbar.picked()
        self.assertFalse(ranges.change())
        self.assertFalse(ranges.remove())
        self.assertFalse(spec.change() and spec.remove())
        spec.fbar.var.set(self.ui.ALL_FUNCTIONS)
        win.pages[5].fbar.var.set(self.ui.ALL_FUNCTIONS)
        win.pages[5].fbar.picked()
        win.pages[5].reload()
        self.assertEqual(win.pages[5].fbar.fid, '')                   # the choice survives a redraw
        win.pages[5].fbar.var.set(next(iter(win.pages[5].fbar.ids)))
        win.pages[5].fbar.picked()
        self.assertEqual(win.pages[5].fbar.fid, fid)
        win.model.fid = fid
        header.preset.set('')
        self.assertFalse(header.add_preset())

    def test_rule_dialog_edit_and_errors(self):
        win, fid = self.build_through_widgets()
        rid = win.model.rule_rows(fid)[0]['id']
        dlg = self.ui.RuleDialog(win, win.model, fid, rid)
        self.assertEqual(dlg.v['percents'].get(), '10, 50, 100')
        dlg.v['percents'].set('100')
        dlg.ok()
        self.assertIsNotNone(dlg.outcome)
        self.assertEqual(len(win.model.fn(fid).points), 6)
        dlg2 = self.ui.RuleDialog(win, win.model, fid)
        dlg2.v['type'].set('Typed points'), dlg2.v['values'].set('5 apples')
        dlg2.layout()
        dlg2.ok()
        self.assertIsNone(dlg2.outcome)
        self.assertTrue(dlg2.msg.get())
        dlg2.destroy()

    def test_ac_rule_dialog_defaults_to_a_frequency_list(self):
        win = self.panel.new()
        win.model.add_function('ACV')
        win.model.add_range(win.model.fid, '10 V', '10 uV')
        dlg = self.ui.RuleDialog(win, win.model, win.model.fid)
        self.assertEqual(dlg.v['freq_mode'].get(), 'Frequency list')
        self.assertNotIn('No frequency', [lab for _k, lab in dlg.freq_pairs])

    def test_panel_list_actions(self):
        win, fid = self.build_through_widgets()
        win.pages[6].save()
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
        with mock.patch.object(self.ui.filedialog, 'askopenfilename', return_value=''):
            self.assertIsNone(self.panel.import_())
        with self.sel(uid):
            self.assertTrue(self.panel.delete_or_restore())
            self.assertEqual(len(self.panel._rows), 2)
            self.panel.show_deleted.set(True)
            self.panel.toggle_deleted()
            self.assertEqual(len(self.panel._rows), 3)
            self.assertIsNone(self.panel.open_selected())            # a deleted one cannot be opened
            self.assertTrue(self.panel.delete_or_restore())          # restore
            self.assertTrue(self.panel.history())
        self.panel.search.set('nothing here')
        self.panel.apply_search()
        self.assertEqual(self.panel._rows, {})
        self.assertGreaterEqual(len(self.called_on_saved), 3)

    def test_panel_actions_without_selection_say_so(self):
        for fn in (self.panel.open_selected, self.panel.duplicate, self.panel.delete_or_restore, self.panel.history, self.panel.export):
            self.assertIsNone(fn())
            self.assertIn('Select a datasheet', self.panel.message.get())

    def test_versions_window(self):
        win, fid = self.build_through_widgets()
        win.pages[6].save()
        win.model.add_point(fid, '7 V')
        win.pages[6].save()
        vw = self.ui.VersionsWindow(win, self.store, win.model.ds.uid, editor=win, panel=self.panel)
        with self.sel('1'):
            self.assertTrue(vw.load_here())
            self.assertEqual(len(win.model.fn(fid).points), 18)
            self.assertTrue(vw.open_new())
            with mock.patch.object(self.ui.filedialog, 'asksaveasfilename', return_value=str(self.t / 'v1.json')):
                self.assertTrue(vw.export())
        vw.open_new()                                                # nothing selected
        self.assertIn('Select a version', vw.msg.get())

    def test_automation_without_standards_loaded_reports(self):
        win, fid = self.build_through_widgets()
        win.model.matcher_factory = lambda: (_ for _ in ()).throw(RuntimeError('no standards'))
        win.model._matcher = None
        win.go(5)
        res = win.pages[5].run()
        self.assertFalse(res)
        self.assertIn('no standards', win.pages[5].summary.get())

    def test_shell_free_helpers(self):
        self.assertEqual(self.ui.selected(object()), ())
        self.assertEqual(self.ui.label_of([('a', 'A'), ('b', 'B')], 'b'), 'B')
        self.assertEqual(self.ui.value_of([('a', 'A'), ('b', 'B')], 'B'), 'b')
        self.assertEqual(self.ui.value_of([('a', 'A')], 'zzz'), 'a')


def M_MODE(key):
    import datasheet_builder_ui as u
    return u.MODE_LABELS[key]


if __name__ == '__main__':
    unittest.main()
