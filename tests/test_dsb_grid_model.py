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


def rows_kind(g, i):
    return g.rows()[i]['kind']


class BlankSheetTests(Base):
    def test_blank_sheet_looks_like_a_template(self):
        rows = self.g.rows()
        self.assertGreaterEqual(len(rows), M.MIN_ROWS)
        self.assertTrue(all(r['kind'] == 'blank' for r in rows))
        self.assertEqual([r['n'] for r in rows[:3]], [1, 2, 3])
        self.assertEqual([c['title'] for c in M.GRID_COLUMNS],
                         ['STEP NUM', 'FUNCTION TESTED', 'NOMINAL VALUE', 'AS FOUND', 'AS LEFT', 'Out of Tol', 'LOW LIMIT', 'HIGH LIMIT'])
        self.assertTrue(all(not r['problem'] for r in rows))             # no row is flagged on an empty sheet

    def test_adding_a_function_puts_the_cursor_on_the_empty_row_under_its_heading(self):
        self.assertEqual(self.g.sel_key, 'b:0')                          # a blank sheet starts on its first spare row
        self.assertTrue(self.g.add_function('ACV'))
        rows = self.g.rows()
        self.assertEqual([r['kind'] for r in rows[:3]], ['header', 'blank', 'blank'])
        self.assertEqual(self.g.row_index(), 1)                          # row 2 (the empty row under the heading), not row 3
        self.assertEqual(self.g.sel_key, f'e:{self.g.fid}')
        self.assertEqual(self.g.sel_col, 'nominal')
        self.assertTrue(self.g.add_function('DCV'))                      # a second section: again the row under ITS heading
        self.assertEqual(rows_kind(self.g, self.g.row_index() - 1), 'header')
        self.assertEqual(self.g.sel_key, f'e:{self.g.fid}')

    def test_a_new_section_or_the_handheld_template_puts_the_cursor_under_the_heading(self):
        self.assertTrue(self.g.add_section('DC volts'))
        self.assertEqual(self.g.sel_key, f'e:{self.g.fid}')
        self.assertEqual(rows_kind(self.g, self.g.row_index() - 1), 'header')
        self.assertTrue(self.g.add_section('AC volts'))
        self.assertEqual(rows_kind(self.g, self.g.row_index() - 1), 'header')
        self.assertEqual(self.g.sel_col, 'nominal')
        g2 = M.GridModel(self.store)
        self.assertTrue(g2.add_handheld_functions())
        self.assertEqual((g2.row_index(), g2.sel_key), (1, f'e:{g2.fid}'))

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
        row = g.sel_key
        self.assertEqual(g.nav('Tab'), 'moved')
        self.assertEqual(g.sel_col, 'function')                    # Tab skips the read-only columns (the limits too): first cell of the next row
        self.assertNotEqual(g.sel_key, row)
        self.assertEqual(g.nav('ISO_Left_Tab'), 'moved')
        self.assertEqual((g.sel_key, g.sel_col), (row, 'nominal'))
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
        self.assertEqual(self.g.limits_display(fn, p), 'Low limit -15.0035 V, High limit 25.0035 V')         # nominal -/+ (0.05 % of 5 V + 0.01 % of 10 V + 20 V)
        row = self.g.row(key)
        self.assertEqual((row['low'], row['high']), ('-15.0035 V', '25.0035 V'))

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


class ViewColumnsTests(Base):
    """The on-screen grid has no As Found / As Left / Out of Tol columns (view only); the printed sheet still has them."""

    def test_screen_columns_are_step_function_nominal_low_high(self):
        self.assertEqual(M.COL_KEYS, ('step', 'function', 'nominal', 'low', 'high'))
        self.assertEqual(M.EDIT_COLS, ('function', 'nominal'))                # the two limit columns are read-only displays
        self.assertEqual(len(M.GridGeometry().widths), 5)
        self.assertNotIn('tol', M.COL_KEYS)                           # no +/- tolerance column next to the limits

    def test_printed_sheet_keeps_the_template_columns(self):
        self.dcv_row('5 V')
        self.g.calc_row(next(r['key'] for r in self.g.rows() if r['kind'] == 'point'), self.form(next(r['key'] for r in self.g.rows() if r['kind'] == 'point'), iv='0.05'))
        view = self.g.print_view()
        self.assertEqual(view['columns'], ['STEP NUM', 'FUNCTION TESTED', 'NOMINAL VALUE', 'AS FOUND', 'AS LEFT', 'Out of Tol', 'LOW LIMIT', 'HIGH LIMIT'])
        point = next(r for r in view['rows'] if r['kind'] == 'point')
        self.assertEqual(len(point['cells']), 8)
        self.assertEqual(point['cells'][3:6], ['', '', ''])
        self.assertTrue(point['cells'][6] and point['cells'][7] and '±' not in ''.join(point['cells']))
        out = Path(self.tmp.name) / 'blank.pdf'
        try:
            res = self.g.write_sheet_pdf(out)
        except ImportError:
            return
        if res.ok:
            self.assertTrue(out.exists())

    def test_navigation_and_selection_work_with_five_columns(self):
        key = self.dcv_row('5 V')
        g = self.g
        g.select(key, 'step')
        g.nav('Right')
        self.assertEqual(g.sel_col, 'function')
        g.nav('End')
        self.assertEqual(g.sel_col, 'high')
        g.nav('Right')
        self.assertEqual(g.sel_col, 'high')                          # stops at the last column
        g.nav('Home')
        self.assertEqual(g.sel_col, 'step')
        g.select(key, 'low')
        g.tab()                                                      # from a read-only limit cell: the next cell you can type in is the first one of the next row
        self.assertEqual(g.sel_col, 'function')
        g.select(key, 'nominal')
        g.tab()                                                      # Tab from the last editable cell goes to the first one of the next row
        self.assertEqual(g.sel_col, 'function')
        geo = M.GridGeometry(widths=[90, 270, 240, 160, 160], row_h=28, head_h=38, num_w=44)
        self.assertEqual(geo.col_at(44 + 90 + 270 + 240 + 5), 3)
        self.assertEqual(geo.col_at(44 + 90 + 270 + 240 + 160 + 5), 4)
        self.assertIsNone(geo.col_at(44 + 920 + 1))
        geo.fit(1000)
        self.assertEqual(len(geo.widths), 5)

    def test_row_dicts_still_carry_the_blank_columns(self):
        self.dcv_row('5 V')
        r = next(r for r in self.g.rows() if r['kind'] == 'point')
        self.assertTrue(all(k in r for k in ('found', 'left', 'oot')))


class HandheldTemplateTests(Base):
    def test_a_new_sheet_is_blank_by_default(self):
        self.assertEqual(self.g.ds.functions, [])
        self.assertEqual(M.DatasheetList(self.store).new().ds.functions, [])

    def test_template_adds_the_handheld_sections_once(self):
        res = self.g.add_handheld_functions()
        self.assertTrue(res.ok, res.message)
        kinds = [f.kind for f in self.g.ds.functions]
        self.assertEqual(kinds, list(M.GridModel.HANDHELD_KINDS))
        self.assertTrue(all(t['present'] for t in self.g.handheld_template()))
        self.assertEqual(sum(r['kind'] == 'header' for r in self.g.rows()), len(M.GridModel.HANDHELD_KINDS))
        again = self.g.add_handheld_functions()
        self.assertFalse(again.ok)
        self.assertEqual(len(self.g.ds.functions), len(M.GridModel.HANDHELD_KINDS))
        self.assertTrue(self.g.undo().ok)                              # one undo step
        self.assertEqual(self.g.ds.functions, [])

    def test_template_keeps_existing_sections_and_rows(self):
        self.dcv_row('5 V')
        before = [f.id for f in self.g.ds.functions]
        self.assertTrue(self.g.add_handheld_functions().ok)
        self.assertEqual(self.g.ds.functions[0].id, before[0])
        self.assertEqual(len(self.g.ds.functions[0].points), 1)
        self.assertEqual(sum(f.kind == 'DCV' for f in self.g.ds.functions), 1)

    def test_list_new_with_handheld_and_rows_can_be_typed(self):
        g = M.DatasheetList(self.store).new(handheld=True)
        self.assertEqual(len(g.ds.functions), len(M.GridModel.HANDHELD_KINDS))
        self.assertTrue(g.dirty)
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
        self.assertTrue(g.set_target_function('DC volts').ok)
        res = g.commit_cell('5 V')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(len(g.ds.function(next(f.id for f in g.ds.functions if f.kind == 'DCV')).points), 1)

    def test_only_named_kinds_and_only_handheld_kinds(self):
        self.assertTrue(self.g.add_handheld_functions(['ACV', 'SCOPE_BW']).ok)
        self.assertEqual([f.kind for f in self.g.ds.functions], ['ACV'])


class EmptySectionTests(Base):
    """An empty section ('no rows yet') is a WARNING: the sheet saves as runnable and the run skips it.  Everything else stays blocking."""

    def filled_template(self):
        self.g.set_header(make='Acme', model='DM-1', title='DM-1 PV')
        self.assertTrue(self.g.add_handheld_functions().ok)
        dcv = next(f for f in self.g.ds.functions if f.kind == 'DCV')
        self.g.select(f'e:{dcv.id}', 'nominal')
        self.assertTrue(self.g.set_target_function('DC volts').ok)
        self.assertTrue(self.g.commit_cell('5 V').ok)
        key = next(r['key'] for r in self.g.rows() if r['kind'] == 'point')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.05')).ok)
        return dcv, key

    def levels(self):
        return sorted({(p['code'], p['level']) for p in self.g.problems()})

    def test_core_validate_makes_the_empty_section_messages_warnings(self):
        self.g.set_target_function('DC volts')
        fn = self.g.ds.functions[0] if self.g.ds.functions else self.g._function_for(self.g.resolve_function('DC volts'))
        found = {(p.code, p.level) for p in db.validate(self.g.ds) if getattr(p, 'where', '').startswith(fn.id)}
        self.assertEqual(found, {('no_ranges', 'warn'), ('no_spec', 'warn'), ('no_points', 'warn')})

    def test_filled_row_without_tolerance_is_still_an_error(self):
        self.dcv_row('5 V')
        codes = {(p['code'], p['level']) for p in self.g.problems()}
        self.assertIn(('no_spec', 'error'), codes)
        self.assertGreater(self.g.problem_counts()['errors'], 0)

    def test_template_with_one_filled_section_has_no_errors_and_one_grouped_warning(self):
        self.filled_template()
        self.assertEqual(self.g.problem_counts(), dict(errors=0, warnings=1))
        self.assertEqual(self.g.problem_summary(), '1 warning.')
        rows = self.g.problem_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['level'], rows[0]['code']), ('warn', 'empty_sections'))
        self.assertIn('9 sections have no test rows yet and are skipped when the sheet runs', rows[0]['text'])
        self.assertTrue(rows[0]['key'].startswith('h:'))
        self.assertIsNotNone(rows[0]['row'])

    def test_no_redundant_per_section_messages(self):
        self.filled_template()
        self.assertEqual({p['code'] for p in self.g.problems()}, {'no_points'})

    def test_one_empty_section_is_listed_on_its_own(self):
        self.g.set_header(make='Acme', model='DM-1', title='DM-1 PV')
        self.assertTrue(self.g.add_handheld_functions(['DCV', 'ACV']).ok)
        dcv = self.g.ds.functions[0]
        self.g.select(f'e:{dcv.id}', 'nominal')
        self.g.set_target_function('DC volts')
        self.assertTrue(self.g.commit_cell('5 V').ok)
        key = next(r['key'] for r in self.g.rows() if r['kind'] == 'point')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.05')).ok)
        rows = self.g.problem_rows()
        self.assertEqual([r['code'] for r in rows], ['no_points'])
        self.assertIn('AC volts', rows[0]['text'])
        self.assertEqual(self.g.problem_counts(), dict(errors=0, warnings=1))

    def test_errors_list_first_and_other_errors_stay_blocking(self):
        self.filled_template()
        key = next(r['key'] for r in self.g.rows() if r['kind'] == 'point')
        self.g.select(key, 'nominal')
        self.assertTrue(self.g.commit_cell('5 V').ok)                    # same value again: no change
        self.g.set_header(make='')                                       # a header error
        c = self.g.problem_counts()
        self.assertEqual(c['errors'], 1)
        rows = self.g.problem_rows()
        self.assertEqual([r['level'] for r in rows], ['error', 'warn'])
        res = self.g.save_sheet()
        self.assertFalse(res.ok)
        self.assertTrue(res.detail.get('needs_draft'))

    def test_a_sheet_with_no_test_row_anywhere_is_blocked(self):
        self.g.set_header(make='Acme', model='DM-1', title='DM-1 PV')
        self.assertTrue(self.g.add_handheld_functions().ok)
        rows = self.g.problem_rows()
        self.assertEqual([r['code'] for r in rows], ['no_test_rows', 'empty_sections'])
        self.assertEqual(self.g.problem_counts(), dict(errors=1, warnings=1))
        self.assertFalse(self.g.save_sheet().ok)

    def test_saves_as_runnable_and_the_runnable_spec_has_no_empty_section(self):
        dcv, key = self.filled_template()
        res = self.g.save_sheet()
        self.assertTrue(res.ok, res.message)
        entry = self.store.entries()[0]
        self.assertEqual(entry['tag'], 'user-built')
        spec = json.loads(Path(entry['spec_path']).read_text())
        self.assertEqual(len(spec['steps']), 1)
        self.assertEqual({s['dsb']['function'] for s in spec['steps']}, {dcv.id})
        self.assertEqual(spec['dsb']['engine']['points'], 1)

    def test_the_blank_printout_still_lists_empty_section_headings(self):
        """Unchanged on purpose: the blank datasheet (preview / PDF) prints each section heading, filled or not, so the template can be filled in by hand."""
        self.filled_template()
        view = self.g.print_view()
        self.assertEqual(sum(r['kind'] == 'header' for r in view['rows']), len(M.GridModel.HANDHELD_KINDS))
        self.assertEqual(sum(r['kind'] == 'point' for r in view['rows']), 1)


class InspectorAutoTests(unittest.TestCase):
    below = 1150

    def should(self, width, manual=False, is_open=True):
        return M.inspector_should_be_open(width, self.below, manual, is_open)

    def test_threshold_is_1150(self):
        self.assertEqual(M.INSPECTOR_COLLAPSE_BELOW, 1150)

    def test_narrow_closes_wide_opens(self):
        self.assertFalse(self.should(1000))
        self.assertFalse(self.should(1149, is_open=False))
        self.assertTrue(self.should(1150, is_open=False))
        self.assertTrue(self.should(1400, is_open=False))
        self.assertTrue(self.should(1400))

    def test_a_manual_choice_is_never_overridden(self):
        self.assertTrue(self.should(900, manual=True, is_open=True))
        self.assertFalse(self.should(1600, manual=True, is_open=False))

    def test_a_window_not_on_screen_yet_changes_nothing(self):
        self.assertTrue(self.should(1, is_open=True))
        self.assertFalse(self.should(1, is_open=False))


class AutomationLineTests(Base):
    def test_counts_from_the_matcher_and_the_sentence(self):
        self.dcv_row('5 V')
        key = next(r['key'] for r in self.g.rows() if r['kind'] == 'point')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.05')).ok)
        self.g.match_result = _FakeMatch(self.g.ds.functions[0].id, dict(points=10, assigned=8, uncovered=2, manual=1, automatable=6, unverified=2))
        self.g.match_rev, self.g.match_period = self.g._rev, self.g.period
        c = self.g.automation_counts()
        self.assertEqual(c, dict(points=10, ok=4, unverified=2, uncovered=2, by_hand=2))
        line = self.g.automation_line()
        self.assertIn('4 run automatically', line)
        self.assertIn('2 run automatically but their commands are not yet verified', line)
        self.assertIn('2 set by hand', line)
        self.assertIn('2 not covered', line)

    def test_no_counts_while_the_sheet_has_problems(self):
        self.g.set_target_function('DC volts')
        self.assertIsNone(self.g.automation_counts(compute=False))
        self.assertIn('not worked out yet', self.g.automation_line(compute=False))


class CursorAfterChoosingFunctionTests(Base):
    def test_cursor_on_empty_row_under_new_heading(self):
        g = self.g
        self.assertTrue(g.set_target_function('DC volts').ok)
        row = g.selected_row()
        self.assertEqual(row['key'], f'e:{g.fid}')
        self.assertEqual(g.sel_col, 'nominal')
        rows = g.rows()
        self.assertEqual([r['kind'] for r in rows[:2]], ['header', row['kind']])


class ToleranceFromAboveTests(Base):
    def test_blank_row_takes_tolerance_without_touching_sheet(self):
        g = self.g
        key = self.dcv_row('5 V')
        self.assertIsNone(g.tolerance_form_above('b:0'))                   # the row above has no tolerance yet
        f = dict(self.form(key))
        f['types'] = ['iv']
        f['plus'] = dict(f['plus'], iv='0.05')
        self.assertTrue(g.calc_row(key, f).ok)
        before = g._snapshot()
        got = g.tolerance_form_above(next(r['key'] for r in g.rows() if r['kind'] == 'blank'))
        self.assertIsNotNone(got)
        self.assertEqual(got['plus']['iv'], '0.05')
        self.assertEqual(g._snapshot(), before)

    def test_borrowed_tolerance_lives_in_the_panel_state_until_calc(self):
        g = self.g
        key = self.dcv_row('5 V')
        f = dict(self.form(key))
        f['types'] = ['iv']
        f['plus'] = dict(f['plus'], iv='0.05')
        self.assertTrue(g.calc_row(key, f).ok)
        blank = next(r['key'] for r in g.rows() if r['kind'] == 'blank')
        g.select(blank, 'nominal')
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '')
        self.assertTrue(g.use_tolerance_above().ok)
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')          # survives any redraw
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')
        form = g.panel_state()['form']
        form['nominal'] = '10'
        self.assertTrue(g.calc_row(form=form).ok)
        self.assertIsNone(g.borrowed_tol)
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '')

    def test_use_tolerance_says_so_when_nothing_is_above(self):
        self.assertTrue(self.g.set_target_function('DC volts').ok)
        res = self.g.use_tolerance_above()
        self.assertFalse(res.ok)

    def test_sign_only_on_dc_nominals(self):
        g = self.g
        self.assertTrue(g.set_target_function('AC volts').ok)
        g.select('b:0', 'nominal')
        self.assertTrue(g.commit_cell('4 V @ 4 Hz').ok)
        row = next(r for r in g.rows() if r['kind'] == 'point')
        self.assertEqual(row['nominal'], '4 V @ 4 Hz')
        g2 = M.GridModel(self.store)
        self.assertTrue(g2.set_target_function('DC volts').ok)
        g2.select('b:0', 'nominal')
        self.assertTrue(g2.commit_cell('4 V').ok)
        self.assertEqual(next(r for r in g2.rows() if r['kind'] == 'point')['nominal'], '+4 V')


class _FakeMatch:
    def __init__(self, fid, total):
        self._fid, self._t = fid, total

    def summary(self):
        return {self._fid: dict(self._t)}


from unittest import mock  # noqa: E402,F401
