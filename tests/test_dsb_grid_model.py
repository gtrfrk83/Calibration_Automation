"""The grid model (datasheet_builder_ui_model.GridModel / GridGeometry) and the per-row spec added to the core (Point.spec).  No tkinter."""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import datasheet_builder as db  # noqa: E402
import datasheet_builder_specs as dbs  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.store = M.Storage(t / 'u', t / 'r.sqlite3', who='tester')
        self.g = M.GridModel(self.store)

    def dcv_row(self, nominal='5 V'):
        """A DC volts section with one row; returns its key."""
        g = self.g
        self.assertTrue(g.set_target_function('DC volts').ok)
        g.select('b:0', 'nominal')
        res = g.commit_cell(nominal)
        self.assertTrue(res.ok, res.message)
        return next(r['key'] for r in g.rows() if r['kind'] == 'point')

    def form(self, key, **plus):
        f = self.g.panel_state(key)['form']
        f['types'] = plus.pop('types', ['iv'])
        f['plus'].update(plus)
        return f


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.geo = M.GridGeometry(widths=[100, 200], row_h=30, head_h=40, num_w=44)

    def test_columns_and_rows_from_pixels(self):
        g = self.geo
        self.assertEqual(g.col_at(-1), None)
        self.assertEqual(g.col_at(10), -1)
        self.assertEqual(g.col_at(44), 0)
        self.assertEqual(g.col_at(144), 1)
        self.assertIsNone(g.col_at(344))
        self.assertEqual(g.row_at(10, 5), -1)
        self.assertEqual(g.row_at(40, 5), 0)
        self.assertEqual(g.row_at(40 + 30 * 4, 5), 4)
        self.assertIsNone(g.row_at(40 + 30 * 5, 5))
        self.assertEqual(g.row_at(40, 5, top=60), 2)             # scrolled two rows

    def test_box_visible_and_scroll_limits(self):
        g = self.geo
        self.assertEqual(g.box(2, 1, top=0), (144, 100, 344, 130))
        self.assertEqual(g.visible(0, 160, 20), (0, 5))
        self.assertEqual(g.max_top(20, 160), 20 * 30 - 120)
        self.assertEqual(g.max_top(2, 160), 0)
        self.assertEqual(g.top_for(10, 0, 160), 11 * 30 - 120)   # brings row 10 into view
        self.assertEqual(g.top_for(1, 0, 160), 0)                # already visible: unchanged
        self.assertEqual(g.top_for(0, 90, 160), 0)

    def test_fit_scales_but_stays_in_bounds(self):
        g = self.geo
        g.fit(10_000)
        self.assertEqual(g.widths, [180, 360])
        g.fit(10)
        self.assertEqual(g.widths, [60, 120])


class BlankSheetTests(Base):
    def test_blank_sheet_looks_like_a_template(self):
        rows = self.g.rows()
        self.assertGreaterEqual(len(rows), M.MIN_ROWS)
        self.assertTrue(all(r['kind'] == 'blank' for r in rows))
        self.assertEqual([r['n'] for r in rows[:3]], [1, 2, 3])
        self.assertEqual([c['title'] for c in M.GRID_COLUMNS],
                         ['STEP NUM', 'FUNCTION TESTED', 'NOMINAL VALUE', 'AS FOUND', 'AS LEFT', 'Out of Tol', 'CALIBRATION TOLERANCE'])
        self.assertTrue(all(not r['problem'] for r in rows))             # no row is flagged on an empty sheet

    def test_typing_a_value_without_a_function_says_what_to_do(self):
        self.g.select('b:0', 'nominal')
        res = self.g.commit_cell('5 V')
        self.assertFalse(res.ok)
        self.assertIn('Choose what this row tests', res.message)
        self.assertFalse(self.g.dirty)

    def test_unknown_function_lists_what_can_be_typed(self):
        res = self.g.set_target_function('frobnicate')
        self.assertFalse(res.ok)
        self.assertIn('DC volts', res.message)
        self.assertNotIn('expression', res.message.lower())


class RowEditingTests(Base):
    def test_first_value_creates_the_section_range_and_point(self):
        key = self.dcv_row('5 V')
        fn, p = self.g.point_of(key)
        self.assertEqual(fn.kind, 'DCV')
        self.assertEqual(p.nominal, Decimal(5))
        self.assertEqual(fn.range(p.range_id).full_scale, Decimal(10))      # the next decade up
        kinds = [r['kind'] for r in self.g.rows()[:3]]
        self.assertEqual(kinds, ['header', 'point', 'blank'])

    def test_si_scaling_is_display_only(self):
        key = self.dcv_row('250 mV')
        fn, p = self.g.point_of(key)
        self.assertEqual(p.nominal, Decimal('0.25'))
        self.assertEqual(self.g.cell_text(key, 'nominal').lstrip('+'), '250 mV')
        self.assertIsInstance(p.nominal, Decimal)

    def test_bad_value_is_refused_with_a_plain_message_and_nothing_changes(self):
        key = self.dcv_row('5 V')
        before = json.dumps(self.g.ds.to_dict(), sort_keys=True)
        res = self.g.commit_cell('five volts', key, 'nominal')
        self.assertFalse(res.ok)
        self.assertEqual(json.dumps(self.g.ds.to_dict(), sort_keys=True), before)

    def test_undo_of_the_last_cell_edit(self):
        key = self.dcv_row('5 V')
        self.g.commit_cell('6 V', key, 'nominal')
        self.assertTrue(self.g.can_undo)
        self.assertTrue(self.g.undo().ok)
        self.assertEqual(self.g.cell_text(key, 'nominal').lstrip('+'), '5 V')
        self.assertTrue(self.g.redo().ok)

    def test_locked_sheet_refuses_edits(self):
        key = self.dcv_row('5 V')
        self.g.set_locked(True)
        ok, why = self.g.cell_editable(key, 'nominal')
        self.assertFalse(ok)
        self.assertTrue(why)
        res = self.g.commit_cell('6 V', key, 'nominal')
        self.assertFalse(res.ok)
        self.g.set_locked(False)
        self.assertTrue(self.g.cell_editable(key, 'nominal')[0])

    def test_read_only_columns_cannot_be_edited(self):
        key = self.dcv_row('5 V')
        for col in ('step', 'found', 'left', 'oot'):
            self.assertFalse(self.g.cell_editable(key, col)[0], col)

    def test_clear_row_and_remark_and_run(self):
        key = self.dcv_row('5 V')
        self.assertTrue(self.g.set_remark(key, 'short leads').ok)
        self.assertIn('*', next(r for r in self.g.rows() if r['key'] == key)['step'])
        self.assertTrue(self.g.set_run(key, False).ok)
        self.assertFalse(self.g.point_of(key)[1].enabled)
        self.assertTrue(self.g.clear_row(key).ok)
        self.assertIsNone(self.g.point_of(key)[1])

    def test_add_section_inserts_a_new_header(self):
        self.dcv_row('5 V')
        res = self.g.add_section('AC volts')
        self.assertTrue(res.ok, res.message)
        self.assertEqual([r['function'] for r in self.g.rows() if r['kind'] == 'header'], ['DC volts', 'AC volts'])


class KeyboardTests(Base):
    def test_arrows_tab_enter(self):
        key = self.dcv_row('5 V')
        g = self.g
        g.select(key, 'function')
        self.assertEqual(g.nav('Right'), 'moved')
        self.assertEqual(g.sel_col, 'nominal')
        self.assertEqual(g.nav('Tab'), 'moved')
        self.assertEqual(g.sel_col, 'tol')                         # Tab skips the read-only columns
        self.assertEqual(g.nav('ISO_Left_Tab'), 'moved')
        self.assertEqual(g.sel_col, 'nominal')
        self.assertEqual(g.nav('Return'), 'edit')
        self.assertEqual(g.nav('F9'), '')
        n = len(g.rows())
        g.select(g.rows()[-1]['key'])
        g.nav('Down')                                                # down from the last row adds an empty row
        self.assertEqual(len(g.rows()), n + 1)

    def test_enter_in_the_bar_moves_down(self):
        key = self.dcv_row('5 V')
        res = self.g.commit_cell('6 V', key, 'nominal', move='down')
        self.assertTrue(res.ok)
        self.assertNotEqual(self.g.sel_key, key)


class CalcTests(Base):
    def test_calc_with_percent_range_and_floor(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv', 'fs', 'floor'], iv='0.05', fs='0.01', floor='20')
        f['units'] = 'V'
        res = self.g.calc_row(key, f)
        self.assertTrue(res.ok, res.message)
        fn, p = self.g.point_of(key)
        self.assertIsNotNone(p.spec)
        # 0.05 % of 5 V + 0.01 % of 10 V + 20 V
        self.assertEqual(self.g.tol_display(fn, p), '±20.0035 V')

    def test_calc_uses_decimals_not_floats(self):
        key = self.dcv_row('1 V')
        f = self.form(key, iv='0.1', types=['iv'])
        self.g.calc_row(key, f)
        fn, p = self.g.point_of(key)
        lim = fn.limit_for(p, self.g.period)
        self.assertIsInstance(lim.high, Decimal)
        self.assertEqual(lim.high - Decimal(1), Decimal('0.001'))

    def test_round_trip_into_the_boxes(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv', 'fs'], iv='0.05', fs='0.01')
        self.g.calc_row(key, f)
        back = self.g.panel_state(key)['form']
        self.assertEqual(sorted(back['types']), ['fs', 'iv'])
        self.assertEqual((back['plus']['iv'], back['plus']['fs']), ('0.05', '0.01'))

    def test_missing_box_names_the_box(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv', 'floor'], iv='0.05', floor='')
        res = self.g.calc_row(key, f)
        self.assertFalse(res.ok)
        self.assertIn('Floor', res.message)

    def test_asymmetric_sides(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv'], iv='0.05')
        f['asym'] = True
        f['minus'] = dict(self.g.blank_side(), iv='0.1')
        res = self.g.calc_row(key, f)
        self.assertTrue(res.ok, res.message)
        fn, p = self.g.point_of(key)
        lim = fn.limit_for(p, self.g.period)
        self.assertEqual((Decimal(5) - lim.low, lim.high - Decimal(5)), (Decimal('0.005'), Decimal('0.0025')))

    def test_multiple_test_points_lo_to_high(self):
        key = self.dcv_row('1 V')
        f = self.form(key, iv='0.05')
        f.update(multi=True, multi_high='9 V', multi_n='5', multi_mode='span')
        res = self.g.calc_row(key, f)
        self.assertTrue(res.ok, res.message)
        pts = [p for fn in self.g.ds.functions for p in fn.points]
        self.assertEqual(len(pts), 5)
        self.assertEqual(sorted(p.nominal for p in pts), [Decimal(x) for x in (1, 3, 5, 7, 9)])

    def test_multiple_points_step_in_units_and_cap(self):
        key = self.dcv_row('1 V')
        f = self.form(key, iv='0.05')
        f.update(multi=True, multi_high='4 V', multi_n='1', multi_mode='units')
        self.assertTrue(self.g.calc_row(key, f).ok)
        self.assertEqual(len([p for fn in self.g.ds.functions for p in fn.points]), 4)
        f2 = self.form(key, iv='0.05')
        f2.update(multi=True, multi_high='1000000 V', multi_n='0.001', multi_mode='units')
        res = self.g.calc_row(key, f2)
        self.assertFalse(res.ok)                                        # too many rows: refused, with a message

    def test_recalc_all_and_copy_tolerance(self):
        key = self.dcv_row('1 V')
        self.g.calc_row(key, self.form(key, iv='0.05'))
        self.g.select(key)
        self.g.select('b:0')
        res = self.g.recalc_all()
        self.assertTrue(res.ok, res.message)
        self.assertIsInstance(self.g.would_overwrite(key), int)


class CoreCompatTests(Base):
    def build_saved(self):
        key = self.dcv_row('5 V')
        self.g.calc_row(key, self.form(key, iv='0.05'))
        self.assertTrue(self.g.set_header(make='Acme', model='DM-1', title='DM-1 PV').ok)
        return key

    def test_point_spec_round_trips_and_older_files_still_load(self):
        key = self.build_saved()
        d = self.g.ds.to_dict()
        again = db.Datasheet.from_dict(json.loads(json.dumps(d)))
        self.assertEqual(again.to_dict(), d)
        fn, p = self.g.point_of(key)
        self.assertIn('spec', [pt for f in d['functions'] for pt in f['points']][0])
        old = json.loads(json.dumps(d))
        for f in old['functions']:
            for pt in f['points']:
                pt.pop('spec', None)
        loaded = db.Datasheet.from_dict(old)
        self.assertIsNone(loaded.functions[0].points[0].spec)          # no spec field is fine: the function table governs

    def test_save_and_export_runnable_spec(self):
        self.build_saved()
        res = self.g.save_sheet()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.store.entries()[0]['tag'], 'user-built')
        self.assertEqual(self.g.problem_counts()['errors'], 0)

    def test_save_with_a_problem_needs_a_draft(self):
        self.dcv_row('5 V')                                            # no tolerance yet
        res = self.g.save_sheet()
        self.assertFalse(res.ok)
        self.assertTrue(res.detail.get('needs_draft'))
        self.assertTrue(self.g.save_sheet(as_draft=True).ok)

    def test_problem_summary_is_plain(self):
        self.dcv_row('5 V')
        text = self.g.problem_summary()
        self.assertTrue(text)
        rows = self.g.problem_rows()
        self.assertTrue(rows)
        for r in rows:
            self.assertNotIn('expression model', r['text'].lower())


class PrintTests(Base):
    def test_print_view_is_blank_template(self):
        key = self.dcv_row('5 V')
        self.g.calc_row(key, self.form(key, iv='0.05'))
        v = self.g.print_view()
        self.assertIn('BLANK', v['notice'])
        point_rows = [r for r in v['rows'] if r['kind'] == 'point']
        self.assertEqual(len(point_rows), 1)
        self.assertEqual(point_rows[0]['cells'][3:6], ['', '', ''])      # As Found, As Left, Out of Tol stay empty

    def test_pdf_is_written(self):
        key = self.dcv_row('5 V')
        self.g.calc_row(key, self.form(key, iv='0.05'))
        out = Path(self.tmp.name) / 'sheet.pdf'
        res = self.g.write_sheet_pdf(str(out))
        if 'reportlab' in res.message:
            self.skipTest('reportlab is not installed')
        self.assertTrue(res.ok, res.message)
        self.assertTrue(out.read_bytes().startswith(b'%PDF'))


if __name__ == '__main__':
    unittest.main()
