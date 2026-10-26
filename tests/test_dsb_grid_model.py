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
import dsb_coil  # noqa: E402
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


class ViewColumnsTests(Base):
    """The on-screen grid has no As Found / As Left / Out of Tol columns (view only); the printed sheet still has them."""

    def test_screen_columns_are_function_nominal_low_high_standard_uncertainty(self):
        self.assertEqual(M.COL_KEYS, ('function', 'nominal', 'low', 'high', 'standard', 'unc'))         # no STEP NUM on screen
        self.assertEqual(M.EDIT_COLS, ('function', 'nominal'))                # the limit, standard and uncertainty columns are not typed in
        self.assertEqual(len(M.GridGeometry().widths), 6)
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

    def test_navigation_and_selection_work_with_six_columns(self):
        key = self.dcv_row('5 V')
        g = self.g
        g.select(key, 'function')
        g.nav('Right')
        self.assertEqual(g.sel_col, 'nominal')
        g.nav('End')
        self.assertEqual(g.sel_col, 'unc')
        g.nav('Right')
        self.assertEqual(g.sel_col, 'unc')                           # stops at the last column
        g.nav('Home')
        self.assertEqual(g.sel_col, 'function')
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
        g.select(key, 'standard')                                    # the STANDARD and UNCERTAINTY cells can be selected but not typed in
        self.assertFalse(g.cell_editable()[0])
        g.select(key, 'unc')
        self.assertFalse(g.cell_editable()[0])
        g.tab()
        self.assertEqual(g.sel_col, 'function')                      # Tab skips them

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


class DeepDiveFixTests(Base):
    """Regression tests for what the datasheet builder deep dive found."""

    def blank_key(self):
        return next(r['key'] for r in self.g.rows() if r['kind'] == 'blank')

    def test_a_comma_inside_a_number_is_refused_not_misread(self):
        g = self.g
        self.dcv_row('5 V')
        for text in ('1,000 V', '1,5 V', '2,5'):
            g.select(self.blank_key(), 'nominal')
            res = g.commit_cell(text)
            self.assertFalse(res.ok, text)
            self.assertIn('comma', res.message.lower())
        self.assertEqual(len([r for r in g.rows() if r['kind'] == 'point']), 1)

    def test_a_signal_level_is_refused_on_a_function_without_one(self):
        g = self.g
        self.dcv_row('5 V')
        g.select(self.blank_key(), 'nominal')
        res = g.commit_cell('1 V, level 2 V')
        self.assertFalse(res.ok)

    def test_a_new_row_does_not_change_the_resolution_of_the_range(self):
        g = self.g
        key = self.dcv_row('5.0000 V')
        f = dict(self.form(key))
        f['types'] = ['calc']
        f['plus'] = dict(f['plus'], calc='0.05 % of reading + 2 counts')
        f['decs'] = '4'
        self.assertTrue(g.calc_row(key, f).ok)
        first = next(r for r in g.rows() if r['kind'] == 'point')
        limits = (first['low'], first['high'])
        blank = self.blank_key()
        g.select(blank, 'nominal')
        f2 = dict(g.panel_state()['form'], nominal='1.0', types=['calc'])
        f2['plus'] = dict(f2['plus'], calc='0.05 % of reading + 2 counts')
        f2['decs'] = ''                                   # (the sheet's last calculation, 4 decimals, is what a new row starts with: type nothing here)
        res = g.calc_row(None, f2)
        self.assertTrue(res.ok, res.message)
        self.assertIn('keeps its resolution', res.message)
        first = next(r for r in g.rows() if r['kind'] == 'point' and r['nominal'].startswith('5'))
        self.assertEqual((first['low'], first['high']), limits)

    def test_locked_sheet_refuses_every_change_and_undo(self):
        g = self.g
        key = self.dcv_row('5 V')
        g.set_locked(True)
        before = g._snapshot()
        for res in (g.set_header(make='X'), g.add_section('DC volts') if hasattr(g, 'add_section') else g.set_header(model='Y'), g.undo(), g.redo(),
                    g.remove_point(g.ds.functions[0].id, g.ds.functions[0].points[0].id)):
            self.assertFalse(res.ok)
            self.assertIn('locked', res.message)
        self.assertEqual(g._snapshot(), before)
        g.set_locked(False)
        self.assertTrue(g.undo().ok)

    # ---- the second round of fixes
    def points(self):
        return [r for r in self.g.rows() if r['kind'] == 'point']

    def test_the_point_id_follows_an_edited_value_and_its_waiver_and_standard_go_with_it(self):
        g = self.g
        key = self.dcv_row('5 V')
        fn, p = g.point_of(key)
        g.ds.assignments[p.id] = 'ABC'
        import datasheet_builder_rules as rules
        rules.set_waiver(g.ds, [p.id], 'other', 'test reason')
        self.assertTrue(g.commit_cell('3 V', key, 'nominal', move='stay').ok)
        fn, p = g.point_of(g.sel_key)
        self.assertEqual(p.nominal, Decimal(3))
        self.assertTrue(p.id.endswith('+3'))
        self.assertEqual(g.ds.assignments.get(p.id), 'ABC')
        self.assertIn(p.id, rules.waivers(g.ds))
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('5 V').ok)                    # the old value can be added again
        new = [q for q in fn.points if q.nominal == Decimal(5)][0]
        self.assertNotIn(new.id, rules.waivers(g.ds))

    def test_a_deleted_rows_waiver_does_not_come_back_with_the_same_value(self):
        import datasheet_builder_rules as rules
        g = self.g
        key = self.dcv_row('5 V')
        fn, p = g.point_of(key)
        rules.set_waiver(g.ds, [p.id], 'other', 'test reason')
        self.assertTrue(g.clear_row(key).ok)
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('5 V').ok)
        self.assertEqual(rules.waivers(g.ds), {})

    def test_a_row_alone_on_its_range_goes_back_to_the_smaller_range(self):
        g = self.g
        self.dcv_row('5 V')
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('50 V').ok)                   # adds the 100 V range
        key = next(r['key'] for r in self.points() if r['nominal'] == '50 V')
        self.assertTrue(g.commit_cell('6 V', key, 'nominal', move='stay').ok)
        fn, p = g.point_of(g.sel_key)
        self.assertEqual(fn.range(p.range_id).full_scale, Decimal(10))

    def test_a_borrowed_tolerance_does_not_follow_to_another_section(self):
        g = self.g
        key = self.dcv_row('5 V')
        self.assertTrue(g.calc_row(key, self.form(key, iv='0.05')).ok)
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.use_tolerance_above().ok)
        self.assertTrue(g.borrowed_tol)
        g.set_target_function('Frequency')
        self.assertFalse(g.borrowed_tol)

    def test_several_rows_are_rounded_carry_remark_and_run_flag_and_count_properly(self):
        g = self.g
        self.dcv_row('1 V')
        g.select(self.blank_key(), 'nominal')
        f = dict(g.panel_state()['form'], nominal='0', multi=True, multi_high='1', multi_n='7', multi_mode='span', remark='from span', run=False,
                 types=['floor'])
        f['plus'] = dict(f['plus'], floor='1 mV')
        res = g.calc_row(None, f)
        self.assertTrue(res.ok, res.message)
        fn = g.ds.functions[0]
        self.assertTrue(all(len(q.nominal.as_tuple().digits) <= 12 for q in fn.points))
        made = [q for q in fn.points if q.note == 'from span']
        self.assertTrue(made)
        self.assertTrue(all(not q.enabled for q in made))
        g.select(self.blank_key(), 'nominal')
        f = dict(g.panel_state()['form'], nominal='2', multi=True, multi_high='3', multi_n='1', multi_mode='units', types=['floor'])
        f['plus'] = dict(f['plus'], floor='1 mV')
        g.set_target_function('DC volts')
        f['multi_n'] = '1 V'
        res = g.calc_row(None, f)
        self.assertTrue(res.ok, res.message)
        self.assertNotIn('1 rows', res.message)

    def test_several_rows_above_the_full_scale_are_refused_before_any_row_is_made(self):
        g = self.g
        self.dcv_row('1 V')
        g.select(self.blank_key(), 'nominal')
        before = len(self.points())
        f = dict(g.panel_state()['form'], nominal='1', multi=True, multi_high='50', multi_n='5', multi_mode='span', types=['fs', 'floor'], fs_scale='10')
        f['plus'] = dict(f['plus'], fs='0.01', floor='1 mV')
        res = g.calc_row(None, f)
        self.assertFalse(res.ok)
        self.assertIn('F.S.', res.message)
        self.assertEqual(len(self.points()), before)

    def test_absurd_numbers_and_bad_frequencies_are_refused_in_plain_words(self):
        g = self.g
        self.dcv_row('5 V')
        g.set_target_function('AC volts')
        for text, word in (('1 V @ -5 Hz', 'above 0'), ('1 V @ 0 Hz', 'above 0'), ('1e999 V @ 1 kHz', 'too large'), ('1 V @ 1e999 Hz', 'too large')):
            g.select(self.blank_key(), 'nominal')
            res = g.commit_cell(text)
            self.assertFalse(res.ok, text)
            self.assertIn(word, res.message, text)
        key = self.dcv_row('5 V') if False else next(r['key'] for r in self.points() if r['nominal'] == '5 V')
        for iv, word in (('5 % of reading - 2 mV', 'number only'), ('1e999', 'too large')):
            res = g.calc_row(key, self.form(key, iv=iv))
            self.assertFalse(res.ok, iv)
            self.assertIn(word, res.message)

    def test_a_missing_asymmetrical_floor_names_its_side(self):
        g = self.g
        key = self.dcv_row('5 V')
        f = self.form(key, types=['floor'], floor='')
        f['asym'] = True
        f['plus']['floor'], f['minus']['floor'] = '1 mV', ''
        self.assertIn('Low', g.calc_row(key, f).message)
        f['plus']['floor'], f['minus']['floor'] = '', '1 mV'
        self.assertIn('High', g.calc_row(key, f).message)

    def test_a_db_tolerance_shows_short_limits(self):
        g = self.g
        key = self.dcv_row('5 V')
        self.assertTrue(g.calc_row(key, self.form(key, types=['db'], db='0.5')).ok)
        row = self.points()[0]
        self.assertLessEqual(len(row['low']), 14)
        self.assertLessEqual(len(row['high']), 14)

    def test_save_of_an_unchanged_sheet_makes_no_new_version(self):
        g = self.g
        g.set_header(make='A', model='B', title='C')
        key = self.dcv_row('5 V')
        self.assertTrue(g.calc_row(key, self.form(key, iv='1')).ok)
        first = g.save()
        self.assertTrue(first.ok, first.message)
        again = g.save()
        self.assertTrue(again.ok)
        self.assertIn('Nothing has changed', again.message)
        self.assertEqual(len(g.storage.versions(g.ds.uid)), 1)

    def test_undo_of_a_delete_puts_the_cursor_back_on_the_deleted_line(self):
        g = self.g
        self.dcv_row('5 V')
        g.select(self.blank_key(), 'nominal')
        g.commit_cell('6 V')
        key = next(r['key'] for r in self.points() if r['nominal'] == '5 V')
        g.select(key, 'nominal')
        self.assertTrue(g.clear_row(key).ok)
        self.assertTrue(g.undo().ok)
        self.assertEqual(g.sel_key, key)

    def test_a_unit_on_a_function_without_one_is_refused(self):
        g = self.g
        g.set_target_function('Check')
        g.select(self.blank_key(), 'nominal')
        res = g.commit_cell('5 V')
        self.assertFalse(res.ok)
        self.assertIn('no unit', res.message)

    def test_shift_tab_onto_a_heading_lands_on_its_name(self):
        g = self.g
        self.dcv_row('5 V')
        g.select(next(r['key'] for r in self.points()), 'nominal')
        g.select(col='function')
        g.tab(back=True)
        self.assertEqual(g.row()['kind'], 'header')
        self.assertEqual(g.sel_col, 'function')

    def test_second_review_fixes(self):
        import datasheet_builder_rules as rules
        g = self.g
        k5 = self.dcv_row('5 V')
        g.select(self.blank_key(), 'nominal')
        g.commit_cell('7 V')
        k7 = next(r['key'] for r in self.points() if r['nominal'] == '7 V')
        # an explicit F.S. is kept when Calc is pressed twice
        f = self.form(k7, types=['fs'], fs='0.01')
        f['fs_scale'] = '100'
        self.assertTrue(g.calc_row(k7, f).ok)
        k7 = g.sel_key if g.point_of(g.sel_key)[1] is not None else k7
        rid = lambda: g.point_of(next(r['key'] for r in self.points() if r['nominal'] == '7 V'))[1].range_id
        first = rid()
        self.assertTrue(g.calc_row(next(r['key'] for r in self.points() if r['nominal'] == '7 V'), f).ok)
        self.assertEqual(rid(), first)
        # F.S. of zero, negative or below the value is refused
        key = next(r['key'] for r in self.points() if r['nominal'] == '5 V')
        for bad in ('0', '-10', '4'):
            f2 = self.form(key, types=['fs'], fs='0.01')
            f2['fs_scale'] = bad
            self.assertFalse(g.calc_row(key, f2).ok, bad)
        # the same value on another range is another row
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('5 V').ok is False)          # same range: still a duplicate
        # undo of a re-key puts the cursor back on a row that exists
        g.select(key, 'nominal')
        self.assertTrue(g.commit_cell('2.5 V', key, 'nominal', move='stay').ok)
        self.assertTrue(g.undo().ok)
        self.assertIsNotNone(g.row(g.sel_key))
        # a locked sheet refuses Load version
        g.set_locked(True)
        self.assertFalse(g.load_version(1).ok)

    def pkey(self):
        return next(r['key'] for r in self.g.rows() if r['kind'] == 'point')

    def test_vpp_typed_in_the_test_point_stays_vpp_and_is_not_converted(self):
        g = self.g
        g.set_target_function('Frequency')
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('1 kHz, level 1 Vpp').ok)
        p = g.ds.functions[0].points[0]
        self.assertEqual((float(p.amplitude), p.settings.get('waveform')), (1.0, 'square'))     # 1 volt peak to peak, as typed
        row = next(r for r in g.rows() if r['kind'] == 'point')
        self.assertIn('level 1 Vpp', g.cell_text(self.pkey(), 'nominal'))
        self.assertTrue(g.commit_cell('1 kHz, level 500 mVpp', self.pkey(), 'nominal', move='stay').ok)
        p = g.ds.functions[0].points[0]
        self.assertEqual(float(p.amplitude), 0.5)
        self.assertIn('level 500 mVpp', g.cell_text(self.pkey(), 'nominal'))
        self.assertTrue(g.commit_cell('1 kHz, level 1 V', self.pkey(), 'nominal', move='stay').ok)    # plain V is the rms sine
        self.assertNotIn('waveform', g.ds.functions[0].points[0].settings)
        self.assertIn('level 1 V', g.cell_text(self.pkey(), 'nominal'))
        self.assertNotIn('Vpp', g.cell_text(self.pkey(), 'nominal'))

    def test_a_square_wave_level_is_kept_shown_and_survives_edit_and_reload(self):
        g = self.g
        g.set_target_function('Frequency')
        g.select(self.blank_key(), 'nominal')
        self.assertTrue(g.commit_cell('1 kHz, level 1 V square').ok)
        fn = g.ds.functions[0]
        p = fn.points[0]
        self.assertEqual(p.settings.get('waveform'), 'square')
        row = next(r for r in g.rows() if r['kind'] == 'point')
        self.assertEqual(row['badge'], '')                                                # no tag in the sheet any more
        self.assertIn('level 1 Vpp', row['nominal'])                                      # the cell itself says Vpp
        self.assertIn('level 1 Vpp', g.cell_text(row['key'], 'nominal'))                  # shown as peak to peak, never converted to rms
        self.assertIn(row['status'], ('good', 'warn', 'bad', 'off'))
        self.assertEqual(g.panel_state(next(r['key'] for r in g.rows() if r['kind'] == 'point'))['form']['level'], '1 Vpp')
        key = next(r['key'] for r in g.rows() if r['kind'] == 'point')
        self.assertTrue(g.commit_cell('1 kHz, level 1 V', key, 'nominal', move='stay').ok)       # sine again: nothing stored
        self.assertNotIn('waveform', g.ds.functions[0].points[0].settings)
        self.assertTrue(g.commit_cell('2 kHz, level 2 V sine', g.sel_key, 'nominal', move='stay').ok)
        self.assertNotIn('waveform', g.ds.functions[0].points[0].settings)
        import datasheet_builder as dbm
        back = dbm.Datasheet.from_json(g.ds.to_json())
        self.assertEqual(back.functions[0].points[0].settings, g.ds.functions[0].points[0].settings)


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
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')          # a new row starts with the sheet's last calculation (sticky default)
        g.ds.options.pop('last_calc')
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '')
        self.assertTrue(g.use_tolerance_above().ok)
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')          # survives any redraw
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')
        form = g.panel_state()['form']
        form['nominal'] = '10'
        self.assertTrue(g.calc_row(form=form).ok)
        self.assertIsNone(g.borrowed_tol)
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
        self.assertEqual(g.panel_state()['form']['plus']['iv'], '0.05')          # the Calc just made is now the sheet's last one

    def test_use_tolerance_says_so_when_nothing_is_above(self):
        self.assertTrue(self.g.set_target_function('DC volts').ok)
        res = self.g.use_tolerance_above()
        self.assertFalse(res.ok)

    def test_no_plus_sign_on_any_nominal(self):
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
        self.assertEqual(next(r for r in g2.rows() if r['kind'] == 'point')['nominal'], '4 V')


class _FakeMatch:
    def __init__(self, fid, total):
        self._fid, self._t = fid, total

    def summary(self):
        return {self._fid: dict(self._t)}


from unittest import mock  # noqa: E402,F401


# ------------------------------------------------------------------------------------------------------------------------ new in this branch
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_rules as rules  # noqa: E402
import uncertainty as unc_mod  # noqa: E402
from tests.test_dsb_ui_model import REG  # noqa: E402


class MatcherBase(Base):
    def setUp(self):
        super().setUp()
        self.matcher = dm.Matcher(REG)
        self.g = M.GridModel(self.store, matcher_factory=lambda: self.matcher)

    def points(self):
        return [r for r in self.g.rows() if r['kind'] == 'point']

    def dcv_series(self, low='1 V', high='9 V', n='5', iv='0.05', **extra):
        key = self.dcv_row(low)
        f = self.form(key, iv=iv)
        f.update(multi=True, multi_high=high, multi_n=n, multi_mode='span', **extra)
        res = self.g.calc_row(key, f)
        self.assertTrue(res.ok, res.message)
        return [r['key'] for r in self.points()]


class TemplatesModelTests(Base):
    def test_template_is_one_undo_step_and_never_doubles(self):
        g = self.g
        self.assertEqual(g.ds.functions, [])
        self.assertTrue(g.add_template('Handheld multimeter sections').ok)
        n = len(g.ds.functions)
        self.assertEqual(n, len(M.GridModel.HANDHELD_KINDS))
        self.assertFalse(g.add_template('Handheld multimeter sections').ok)       # all there: refused, nothing doubled
        self.assertEqual(len(g.ds.functions), n)
        self.assertFalse(g.add_template('No such template').ok)
        self.assertTrue(g.undo().ok)
        self.assertEqual(g.ds.functions, [])                                     # ONE undo step takes the whole template out

    def test_sections_the_sheet_already_has_stay_as_they_are(self):
        key = self.dcv_row('5 V')
        before = len(self.g.point_of(key)[0].points)
        self.assertTrue(self.g.add_template('Handheld multimeter sections').ok)
        self.assertEqual(sum(f.kind == 'DCV' for f in self.g.ds.functions), 1)
        self.assertEqual(len(self.g.point_of(key)[0].points), before)


class ConductanceTests(Base):
    def conductance(self, text):
        self.assertTrue(self.g.set_target_function('Conductance').ok)
        self.g.select(next(r['key'] for r in self.g.rows() if r['kind'] == 'blank'), 'nominal')
        res = self.g.commit_cell(text)
        self.assertTrue(res.ok, res.message)
        return [r['key'] for r in self.g.rows() if r['kind'] == 'point'][-1]

    def test_units_drop_down_lists_pS_to_S_and_typing_nS_stores_si(self):
        key = self.conductance('5 nS')
        self.assertEqual(self.g.panel_state(key)['unit_choices'], ['pS', 'nS', 'µS', 'mS', 'S'])
        self.assertEqual(M.unit_choices('S'), ['pS', 'nS', 'µS', 'mS', 'S'])
        _fn, p = self.g.point_of(key)
        self.assertEqual(p.nominal, Decimal('5e-9'))

    def test_limits_for_nS_and_mS_rows(self):
        k1 = self.conductance('5 nS')
        f = self.form(k1, types=['iv', 'floor'], iv='1', floor='0.5 nS')
        self.assertTrue(self.g.calc_row(k1, f).ok)
        k2 = self.conductance('2 mS')
        f = self.form(k2, types=['iv', 'floor'], iv='1', floor='0.5 µS')
        self.assertTrue(self.g.calc_row(k2, f).ok)
        by = {r['nominal']: r for r in self.g.rows() if r['kind'] == 'point'}
        self.assertEqual((by['5 nS']['low'], by['5 nS']['high']), ('4.45 nS', '5.55 nS'))          # 1 % of 5 nS + 0.5 nS
        self.assertEqual((by['2 mS']['low'], by['2 mS']['high']), ('1.9795 mS', '2.0205 mS'))      # 1 % of 2 mS + 0.5 µS
        fn, p = self.g.point_of(k1)
        lim = fn.limit_for(p, self.g.period)
        self.assertEqual((lim.low, lim.high), (Decimal('4.45e-9'), Decimal('5.55e-9')))            # exact Decimal maths, only the display is scaled


class NoStepColumnTests(Base):
    def test_rows_carry_step_internally_but_the_screen_has_no_such_column(self):
        self.dcv_row('5 V')
        self.assertNotIn('step', M.COL_KEYS)
        self.assertTrue([r for r in self.g.rows() if r['kind'] == 'point'][0]['step'])
        self.assertEqual(self.g.print_view()['columns'][0], 'STEP NUM')


class MultiRowIndependenceTests(MatcherBase):
    """Owner bug: rows made together by 'Multiple Test Points' all changed when ONE of them was brought back into the calculator to change its resolution
    (the resolution lived on the shared range).  A row's own resolution is its own (Point.resolution)."""

    def test_changing_the_resolution_of_one_row_leaves_the_others_alone(self):
        keys = self.dcv_series(decs='3')
        g = self.g
        before = {r['key']: (r['nominal'], r['low'], r['high']) for r in self.points()}
        fn = g.ds.functions[0]
        self.assertEqual({q.resolution for q in fn.points}, {None})
        k = keys[2]
        f = g.panel_state(k)['form']
        f.update(decs='5', auto_res=True)
        res = g.calc_row(k, f)
        self.assertTrue(res.ok, res.message)
        self.assertIn('of its own', res.message)
        after = {r['key']: (r['nominal'], r['low'], r['high']) for r in self.points()}
        for other in keys:
            if other != k:
                self.assertEqual(after[other], before[other], other)             # every other row of the run: same value, same limits
        self.assertNotEqual(after[k], before[k])                               # the changed row has its 5 decimals
        _fn, p = g.point_of(k)
        self.assertEqual(p.resolution, Decimal('0.00001'))
        self.assertEqual([q.resolution for q in fn.points if q.id != p.id], [None] * (len(fn.points) - 1))
        self.assertTrue(g.undo().ok)
        self.assertEqual({r['key']: (r['nominal'], r['low'], r['high']) for r in self.points()}, before)           # one undo step

    def test_calc_on_one_row_changes_only_that_row(self):
        keys = self.dcv_series()
        g = self.g
        before = {r['key']: (r['low'], r['high']) for r in self.points()}
        k = keys[3]
        f = g.panel_state(k)['form']
        f['plus'] = dict(f['plus'], iv='0.2')
        self.assertTrue(g.calc_row(k, f).ok)
        after = {r['key']: (r['low'], r['high']) for r in self.points()}
        self.assertEqual([x for x in keys if after[x] != before[x]], [k])
        specs = [g.point_of(x)[1].spec for x in keys[1:]]
        self.assertEqual(len({id(sp) for sp in specs}), len(specs))                 # no two rows share one SpecEntry object

    def test_row_resolution_survives_save_and_load_and_old_files_are_unchanged(self):
        keys = self.dcv_series()
        g = self.g
        f = g.panel_state(keys[2])['form']
        f.update(decs='4', auto_res=True)
        self.assertTrue(g.calc_row(keys[2], f).ok)
        pid = g.point_of(keys[2])[1].id
        data = json.loads(g.ds.to_json())
        pts = {p['id']: p for fn in data['functions'] for p in fn['points']}
        self.assertEqual([k for k, p in pts.items() if 'resolution' in p], [pid])    # written only where set: files made before are unchanged
        again = db.Datasheet.from_json(g.ds.to_json())
        self.assertEqual(again.functions[0].point(pid).resolution, Decimal('0.0001'))

    def test_giving_a_row_its_ranges_resolution_again_drops_its_own(self):
        keys = self.dcv_series(decs='3')
        g = self.g
        f = g.panel_state(keys[2])['form']
        f.update(decs='5', auto_res=True)
        self.assertTrue(g.calc_row(keys[2], f).ok)
        f = g.panel_state(keys[2])['form']
        f.update(decs='3', auto_res=True)
        self.assertTrue(g.calc_row(keys[2], f).ok)
        self.assertIsNone(g.point_of(keys[2])[1].resolution)

    def test_the_ranges_page_still_changes_the_whole_range(self):
        keys = self.dcv_series(decs='3')
        g = self.g
        f = g.panel_state(keys[2])['form']
        f.update(decs='5', auto_res=True)
        self.assertTrue(g.calc_row(keys[2], f).ok)
        fn = g.ds.functions[0]
        rid = g.point_of(keys[3])[1].range_id
        self.assertTrue(g.edit_range(fn.id, rid, resolution='0.01').ok)               # an explicit range-wide action
        self.assertEqual(fn.resolution_of(g.point_of(keys[3])[1]), Decimal('0.01'))
        self.assertEqual(fn.resolution_of(g.point_of(keys[2])[1]), Decimal('0.00001'))   # the row that has its own keeps it


class CalcMemoryTests(MatcherBase):
    """Owner request: the last tolerance calculation is kept: the boxes keep what was typed, each row remembers its own, a new row starts with the last one."""

    def test_boxes_keep_what_was_typed_after_calc(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv', 'floor'], iv='0.050', floor='0.0020 V')
        f.update(decs='4', auto_res=True)
        self.assertTrue(self.g.calc_row(key, f).ok)
        got = self.g.panel_state(key)['form']
        self.assertEqual(got['plus']['iv'], '0.050')                              # not rewritten to 0.05
        self.assertEqual(got['plus']['floor'], '0.0020 V')                        # not rewritten to 2 mV
        self.assertEqual(got['types'], ['iv', 'floor'])
        self.assertEqual(got['decs'], '4')

    def test_multiple_rows_settings_are_kept_and_each_row_has_its_own_copy(self):
        keys = self.dcv_series(low='1 V', high='9 V', n='5', iv='0.050')
        g = self.g
        got = g.panel_state(keys[2])['form']
        self.assertEqual((got['multi_mode'], got['multi_n'], got['multi_high']), ('span', '5', '9 V'))
        self.assertFalse(got['multi'])                                            # generating again is an action, not a setting
        calcs = [g.point_of(k)[1].calc for k in keys if g.point_of(k)[1].calc]
        self.assertGreaterEqual(len(calcs), 4)
        self.assertEqual(len({id(c) for c in calcs}), len(calcs))                 # separate dicts, nothing shared
        f = g.panel_state(keys[3])['form']
        f['plus'] = dict(f['plus'], iv='0.2')
        self.assertTrue(g.calc_row(keys[3], f).ok)
        self.assertEqual(g.panel_state(keys[3])['form']['plus']['iv'], '0.2')
        self.assertEqual(g.panel_state(keys[2])['form']['plus']['iv'], '0.050')    # the neighbour still shows its own

    def test_new_row_starts_with_the_last_calculation(self):
        key = self.dcv_row('5 V')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.07')).ok)
        self.g.select(self.next_blank(), 'nominal')
        self.assertEqual(self.g.panel_state()['form']['plus']['iv'], '0.07')
        self.assertTrue(self.g.commit_cell('6 V').ok)                              # typed straight in the sheet
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.09')).ok)       # a later Calc becomes the new default
        self.g.select(self.next_blank(), 'nominal')
        self.assertEqual(self.g.panel_state()['form']['plus']['iv'], '0.09')

    def next_blank(self):
        return next(r['key'] for r in self.g.rows() if r['kind'] == 'blank')

    def test_calculation_is_part_of_the_same_undo_step_and_saved_with_the_sheet(self):
        key = self.dcv_row('5 V')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.07')).ok)
        again = db.Datasheet.from_json(self.g.ds.to_json())
        _fn, p = self.g.point_of(key)
        self.assertEqual(again.functions[0].point(p.id).calc['plus']['iv'], '0.07')
        self.assertEqual(again.options['last_calc']['form']['plus']['iv'], '0.07')
        self.assertTrue(self.g.undo().ok)
        self.assertNotIn('last_calc', self.g.ds.options)
        self.assertIsNone(self.g.point_of(key)[1].calc)

    def test_limits_are_worked_out_exactly_as_before(self):
        key = self.dcv_row('5 V')
        f = self.form(key, types=['iv', 'floor'], iv='0.050', floor='0.0020 V')
        self.assertTrue(self.g.calc_row(key, f).ok)
        row = self.points_of()[0]
        self.assertEqual((row['low'], row['high']), ('4.9955 V', '5.0045 V'))      # 0.05 % of 5 V + 2 mV, exact Decimal maths

    def points_of(self):
        return [r for r in self.g.rows() if r['kind'] == 'point']

    def test_a_stale_calculation_is_not_shown_once_the_tolerance_changed_elsewhere(self):
        key = self.dcv_row('5 V')
        self.assertTrue(self.g.calc_row(key, self.form(key, iv='0.07')).ok)
        _fn, p = self.g.point_of(key)
        p.spec = M.copy_spec(p.spec)
        p.spec.exprs[self.g.period] = db.parse_expr('0.5 % of reading', 'V')       # edited on another page
        self.g._rev += 1
        self.g._rows_cache = None
        self.assertEqual(self.g.panel_state(key)['form']['plus']['iv'], '0.5')     # shows the real tolerance, not the old text


class StandardColumnsTests(MatcherBase):
    def setUp(self):
        super().setUp()
        self.keys = self.dcv_series(iv='0.05')            # keys[0] is the 1 V row that existed first and has no tolerance; the other four have one
        self.g.add_template('Handheld multimeter sections')

    def cells(self, key):
        r = self.g.row(key)
        return r['standard'], r['unc']

    def test_blank_until_worked_out_then_filled_and_cached(self):
        g = self.g
        self.assertFalse(g.standard_columns_ready())
        self.assertEqual(self.cells(self.keys[2]), ('', ''))
        self.assertTrue(g.refresh_standard_columns())
        self.assertFalse(g.refresh_standard_columns())                            # cached for this version of the sheet
        std, unc = self.cells(self.keys[2])
        fn, p = g.point_of(self.keys[2])
        a = g._grid_result().assignments[p.id]
        self.assertEqual(unc, unc_mod.format_value(a.uncertainty, fn.unit))        # formatted like the report
        self.assertEqual(std, a.standard)
        self.assertIn('k = 2', g.row(self.keys[2])['unc_tip'])
        g.select(self.keys[3], 'nominal')
        self.assertTrue(g.standard_columns_ready())                                # moving about keeps the cache
        g.clear_row(self.keys[1])
        self.assertFalse(g.standard_columns_ready())                                # an edit makes them blank again until re-worked-out

    def test_headings_and_kinds_without_uncertainty_show_nothing(self):
        g = self.g
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank' and r['fid'] and g.ds.function(r['fid']).kind == 'DIODE'), 'nominal')
        self.assertTrue(g.commit_cell('0.5 V').ok)
        g.refresh_standard_columns()
        seen = 0
        for r in g.rows():
            if r['kind'] == 'header':
                self.assertEqual((r['standard'], r['unc']), ('', ''))
            if r['kind'] == 'point' and g.ds.function(r['fid']).kind == 'DIODE':
                seen += 1
                self.assertEqual((r['standard'], r['unc'], r['unc_tip']), ('', '', ''))
        self.assertEqual(seen, 1)

    def test_row_without_limits_is_blank_with_the_reason(self):
        g = self.g
        g.refresh_standard_columns()
        row = g.row(self.keys[0])
        self.assertEqual(row['unc'], '')
        self.assertIn('fix this row first', row['unc_tip'])

    def test_choose_a_standard_for_one_point_in_one_undo_step(self):
        g = self.g
        g.refresh_standard_columns()
        k = self.keys[2]
        choices = g.standard_choices(k)
        self.assertEqual(choices[0]['label'], 'Automatic (best fit)')
        covering = [c for c in choices if c['scope'] == 'point' and c['value'] not in ('', 'MANUAL')]
        self.assertGreaterEqual(len(covering), 2)
        auto = self.cells(k)[0]
        other = next(c for c in covering if c['value'] != auto)
        _fn, p = g.point_of(k)
        res = g.choose_standard(k, other['value'])
        self.assertTrue(res.ok, res.message)
        self.assertEqual(g.ds.assignments[p.id], other['value'])                     # exactly what the Automation page writes
        g.refresh_standard_columns()
        std, unc = self.cells(k)
        self.assertEqual(std, other['value'] + ' (chosen)')
        self.assertTrue(unc)
        self.assertTrue(g.row(k)['std_hand'])
        self.assertTrue(g.undo().ok)                                                 # ONE step
        self.assertNotIn(p.id, g.ds.assignments)
        g.refresh_standard_columns()
        self.assertEqual(self.cells(k)[0], auto)
        self.assertTrue(g.choose_standard(k, other['value']).ok)
        self.assertTrue(g.choose_standard(k, '').ok)                                 # Automatic again
        self.assertNotIn(p.id, g.ds.assignments)

    def test_same_as_the_automation_page(self):
        g = self.g
        g.refresh_standard_columns()
        k = self.keys[2]
        _fn, p = g.point_of(k)
        want = next(c['value'] for c in g.standard_choices(k) if c['scope'] == 'point' and c['value'] not in ('', 'MANUAL') and c['value'] != self.cells(k)[0])
        other = M.GridModel(self.store, db.Datasheet.from_json(g.ds.to_json()), matcher_factory=lambda: self.matcher)
        self.assertTrue(other.set_assignment(p.id, want).ok)
        self.assertTrue(g.choose_standard(k, want).ok)
        self.assertEqual(other.ds.assignments, g.ds.assignments)

    def test_a_standard_that_does_not_cover_the_point_is_refused(self):
        g = self.g
        g.refresh_standard_columns()
        res = g.choose_standard(self.keys[2], 'NO-SUCH-STANDARD')
        self.assertFalse(res.ok)
        self.assertEqual(g.ds.assignments, {})

    def test_set_for_the_whole_section_from_the_heading(self):
        g = self.g
        g.refresh_standard_columns()
        head = next(r['key'] for r in g.rows() if r['kind'] == 'header' and r['function'] == 'DC volts')
        choices = g.standard_choices(head)
        self.assertTrue(all(c['scope'] == 'section' for c in choices))
        self.assertTrue(any(c['label'].startswith('Set for the whole section:') for c in choices))
        std = next(c['value'] for c in choices if c['value'] not in ('', 'MANUAL'))
        n_before = len(g._undo)
        res = g.choose_standard(head, std)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(len(g._undo), n_before + 1)                                  # one undo step for the whole section
        pids = {p.id for p in g.ds.function(g.row(head)['fid']).points if p.enabled}
        self.assertEqual({k for k, v in g.ds.assignments.items() if v == std}, pids)
        g.refresh_standard_columns()
        for r in g.rows():
            if r['kind'] == 'point' and r['unc']:
                self.assertEqual(r['standard'], std + ' (chosen)')
        self.assertTrue(g.undo().ok)
        self.assertEqual(g.ds.assignments, {})
        self.assertTrue(g.choose_standard(self.keys[2], std, scope='section').ok)       # also offered from a point row
        self.assertEqual(len(g.ds.assignments), len(pids))

    def test_blank_by_waiver_says_so_in_the_tooltip(self):
        g = self.g
        g.refresh_standard_columns()
        k = self.keys[2]
        _fn, p = g.point_of(k)
        self.assertTrue(g.choose_standard(k, 'MANUAL').ok)
        g.refresh_standard_columns()
        self.assertEqual(g.row(k)['unc'], '')                                         # never zero
        self.assertEqual(g.row(k)['standard'], 'MANUAL')
        self.assertIn('none: blank', g.row(k)['unc_tip'])
        self.assertNotIn('waived', g.row(k)['unc_tip'])
        self.assertTrue(g._do('waive', lambda: rules.set_waiver(g.ds, [p.id], 'other', 'own standard, certified')).ok)
        g.refresh_standard_columns()
        self.assertEqual(g.row(k)['unc'], '')
        self.assertIn('waived', g.row(k)['unc_tip'])
        self.assertIn('own standard, certified', g.row(k)['unc_tip'])

    def test_the_printed_sheet_does_not_change(self):
        g = self.g
        before = json.dumps(g.print_view(), sort_keys=True, default=str)
        g.refresh_standard_columns()
        self.assertEqual(json.dumps(g.print_view(), sort_keys=True, default=str), before)
        std = next(c['value'] for c in g.standard_choices(self.keys[2]) if c['scope'] == 'point' and c['value'] not in ('', 'MANUAL'))
        g.choose_standard(self.keys[2], std)
        g.refresh_standard_columns()
        self.assertEqual(json.dumps(g.print_view(), sort_keys=True, default=str), before)
        self.assertNotIn('STANDARD', g.print_view()['columns'])
        self.assertNotIn('UNCERTAINTY', g.print_view()['columns'])

    def test_a_matcher_that_fails_leaves_the_cells_blank_and_the_sheet_working(self):
        class Broken:
            def match(self, *a, **k):
                raise RuntimeError('no standards database')
        g = M.GridModel(self.store, db.Datasheet.from_json(self.g.ds.to_json()), matcher_factory=Broken)
        self.assertTrue(g.refresh_standard_columns())
        r = [r for r in g.rows() if r['kind'] == 'point'][2]
        self.assertEqual((r['standard'], r['unc']), ('', ''))
        self.assertIn('could not be loaded', r['unc_tip'])


if __name__ == '__main__':
    unittest.main()


class TemperatureSensorTests(MatcherBase):
    """Temperature is sourced as a thermocouple type or an RTD: chosen per point, required, and it decides the standard's rows and the scope CMC."""

    def temp_rows(self, n=1, nominal='100 degC'):
        g = self.g
        self.assertTrue(g.set_target_function('Temperature (simulated)').ok)
        for i in range(n):
            g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
            self.assertTrue(g.commit_cell(nominal if i == 0 else f'{100 + 10 * i} degC').ok)
        keys = [r['key'] for r in self.points()]
        for k in keys:
            f = g.panel_state(k)['form']
            f['types'] = ['floor']
            f['plus']['floor'] = '1 degC'
            self.assertTrue(g.calc_row(k, f).ok)
        return keys

    def cell(self, k):
        self.g.refresh_standard_columns()
        r = self.g.row(k)
        return r['standard'], r['unc'], r['function']

    def test_a_new_temperature_section_assumes_no_sensor(self):
        k = self.temp_rows()[0]
        fn, p = self.g.point_of(k)
        self.assertNotIn('tc_type', fn.settings)
        self.assertNotIn('sensor', p.settings)
        self.assertEqual(self.g.panel_state(k)['form']['sensor'], '')
        std, unc, func = self.cell(k)
        self.assertEqual((std, unc), ('', ''))                                    # blank with the reason, never zero and never Type K
        self.assertIn('sensor not chosen', func)
        self.assertIn('how the temperature is sourced', self.g.row(k)['unc_tip'])
        self.assertTrue(self.g.panel_state(k)['fields']['sensor'])

    def test_choices_include_thermocouples_and_rtds(self):
        keys = [k for k, _l in self.g.panel_state(self.temp_rows()[0])['sensors']]
        for want in ('K', 'J', 'T', 'Pt385-100', 'Pt385-1000', 'Cu427-10', 'PtNi385-120'):
            self.assertIn(want, keys)

    def test_the_choice_moves_the_standard_and_the_uncertainty(self):
        k = self.temp_rows()[0]
        seen = {}
        for s in ('K', 'T', 'Pt385-100'):
            self.assertTrue(self.g.set_sensor(k, s).ok)
            seen[s] = self.cell(k)
        self.assertEqual(seen['K'][0], '5560A')                                   # the 5560A sheet (rebuilt from the manual) covers every thermocouple and wins on TUR
        self.assertEqual(seen['T'][0], '5560A')
        self.assertEqual(seen['Pt385-100'][0], '5522A')                           # RTD rows exist on the 5522A / 5520A only
        self.assertIn('Type K', seen['K'][2])
        self.assertIn('Pt 385, 100', seen['Pt385-100'][2])                         # the scope's own label
        self.assertEqual(len({v[1] for v in seen.values()}), 3)                  # three different numbers: not Type K's for everything
        self.assertTrue(all(v[1] for v in seen.values()))

    def test_non_k_sensors_are_set_by_hand_and_a_point_outside_every_standard_is_blank(self):
        k = self.temp_rows()[0]
        _fn, p = self.g.point_of(k)
        self.g.set_sensor(k, 'Pt385-100')
        self.g.refresh_standard_columns()
        a = self.g._grid_result().assignments[p.id]
        self.assertEqual((a.status, a.cap_kind, a.automation), ('assigned', 'TEMP_OTHER', 'manual'))
        self.assertIn('by hand', self.g.row(k)['standard_tip'])
        self.assertTrue(self.g.row(k)['unc'])                                      # the scope now has RTD lines: a figure, never blank
        hot = self.temp_rows_at('2000 degC')                                       # far above every simulation row of every standard
        self.g.set_sensor(hot, 'Pt385-100')
        std, unc, _f = self.cell(hot)
        self.assertEqual(unc, '')
        self.assertIn('none covers', std)

    def temp_rows_at(self, nominal):
        g = self.g
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
        self.assertTrue(g.commit_cell(nominal).ok)
        k = [r['key'] for r in self.points()][-1]
        f = g.panel_state(k)['form']
        f['types'], f['plus']['floor'] = ['floor'], '1 degC'
        self.assertTrue(g.calc_row(k, f).ok)
        return k

    def test_every_sensor_uses_its_own_scope_line_and_the_larger_of_cmc_and_budget(self):
        sc = unc_mod.load()
        k = self.temp_rows()[0]
        _fn, p = self.g.point_of(k)
        for key, _label in unc_mod.sensor_types(sc):
            self.g.set_sensor(k, key)
            self.g.refresh_standard_columns()
            a = self.g._grid_result().assignments[p.id]
            if a.status != 'assigned':
                continue
            cand = next(c for c in a.candidates if c.standard == a.standard)
            want = sc.temperature(100, tc=key)
            self.assertEqual(cand.cmc, want, key)                                  # that sensor's scope line (None where the scope has none)
            if want is not None:
                self.assertGreaterEqual(a.uncertainty, want, key)                 # never below the lab's CMC

    def test_one_undo_step_for_a_point_and_for_a_section(self):
        keys = self.temp_rows(3)
        def sensors():                                                              # undo puts back a copy of the sheet: look the section up again
            return [q.settings.get('sensor') for q in self.g.point_of(keys[0])[0].points]
        self.assertTrue(self.g.set_sensor(keys[1], 'J').ok)
        self.assertEqual(sensors(), [None, 'J', None])
        self.assertTrue(self.g.undo().ok)
        self.assertEqual(sensors(), [None, None, None])
        self.assertTrue(self.g.set_sensor(keys[0], 'Cu427-10', 'section').ok)
        self.assertEqual(set(sensors()), {'Cu427-10'})
        self.assertTrue(self.g.undo().ok)
        self.assertEqual(sensors(), [None, None, None])
        self.assertTrue(self.g.redo().ok)
        self.assertEqual(set(sensors()), {'Cu427-10'})

    def test_multiple_rows_each_get_their_own_copy_of_the_choice(self):
        k = self.temp_rows()[0]
        f = self.g.panel_state(k)['form']
        f.update(sensor='T', multi=True, multi_high='140 degC', multi_n='3', multi_mode='span')
        f['types'] = ['floor']
        f['plus']['floor'] = '1 degC'
        self.assertTrue(self.g.calc_row(k, f).ok)
        fn, _p = self.g.point_of(k)
        self.assertGreaterEqual(len(fn.points), 3)
        self.assertEqual([q.settings.get('sensor') for q in fn.points], ['T'] * len(fn.points))
        self.assertTrue(self.g.set_sensor(self.points()[1]['key'], 'S').ok)       # changing one leaves the rest
        fn, _p = self.g.point_of(k)
        self.assertEqual([q.settings.get('sensor') for q in fn.points].count('T'), len(fn.points) - 1)

    def test_old_sheets_with_tc_type_keep_working(self):
        k = self.temp_rows(2)[0]
        fn, _p = self.g.point_of(k)
        fn.settings['tc_type'] = 'J'                                               # an old sheet: the letter on the section
        self.assertEqual(self.g.panel_state(k)['form']['sensor'], 'J')
        _std, unc, func = self.cell(k)
        self.assertIn('Type J', func)
        self.assertTrue(unc)
        chk = self.g.sheet_check(dry_run=False)
        self.assertEqual([f for f in chk.findings if f.code == 'sensor_not_chosen'], [])

    def test_the_sheet_check_blocks_until_every_point_has_a_sensor_and_jumps_to_the_row(self):
        keys = self.temp_rows(2)
        self.g.set_sensor(keys[0], 'K')
        chk = self.g.sheet_check(dry_run=False)
        bad = [f for f in chk.findings if f.code == 'sensor_not_chosen']
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].level, rules.ERROR)
        self.assertEqual(bad[0].key, keys[1])                                      # jumps to the first row without a sensor
        self.g.set_sensor(keys[1], 'J')
        chk = self.g.sheet_check(dry_run=False)
        self.assertEqual([f for f in chk.findings if f.code == 'sensor_not_chosen'], [])

    def test_the_choice_is_saved_and_loaded(self):
        k = self.temp_rows()[0]
        self.g.set_sensor(k, 'PtNi385-120')
        fn, p = self.g.point_of(k)
        back = db.Datasheet.from_dict(self.g.ds.to_dict())
        self.assertEqual(back.function(fn.id).point(p.id).settings['sensor'], 'PtNi385-120')

    def test_scope_cmc_follows_the_sensor(self):
        sc = unc_mod.load()
        self.assertEqual(dm._scope_temperature(sc, 100, 'K'), sc.temperature(100, tc='K'))
        self.assertEqual(dm._scope_temperature(sc, 100, 'Pt385-100'), sc.temperature(100, tc='Pt385-100'))
        self.assertNotEqual(sc.temperature(100, tc='K'), sc.temperature(100, tc='Pt385-100'))


class CoilModelTests(MatcherBase):
    """A clamp-meter current row driven through the 50-turn coil (dsb_coil): chosen per row or per section, one undo step, copied by multiple rows, shown in the columns."""

    def aci_rows(self, n=2, values=('500 A @ 50 Hz', '300 A @ 50 Hz', '100 A @ 50 Hz')):
        g = self.g
        label = next(c['label'] for c in g.function_choices() if c['kind'] == 'ACI' and not c['fid'])
        self.assertTrue(g.set_target_function(label).ok)
        for v in values[:n]:
            g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
            self.assertTrue(g.commit_cell(v).ok, v)
        keys = [r['key'] for r in self.points()]
        for k in keys:
            f = g.panel_state(k)['form']
            f['types'], f['plus']['iv'] = ['iv'], '1'
            self.assertTrue(g.calc_row(k, f).ok)
        return keys

    def coils(self, key):
        return [dsb_coil.is_coil(*(lambda fp: (fp[0], q))(self.g.point_of(key))) for q in self.g.point_of(key)[0].points]

    def test_a_current_row_offers_the_choice_and_other_rows_do_not(self):
        k = self.aci_rows(1)[0]
        self.assertTrue(self.g.panel_state(k)['fields']['coil'])
        self.assertFalse(self.g.panel_state(k)['form']['coil'])

    def test_a_voltage_row_has_no_coil_choice(self):
        dcv = self.dcv_row('5 V')
        self.assertFalse(self.g.panel_state(dcv)['fields']['coil'])
        self.assertFalse(self.g.set_coil(dcv, True).ok)

    def test_one_row_one_undo_step_and_the_section_button(self):
        keys = self.aci_rows(3)
        self.assertTrue(self.g.set_coil(keys[1], True).ok)
        self.assertEqual(self.coils(keys[0]), [False, True, False])
        self.assertIn('Coil, ', self.g.row(keys[1])['function'])
        self.assertNotIn('Coil, ', self.g.row(keys[0])['function'])
        self.assertTrue(self.g.undo().ok)
        self.assertEqual(self.coils(keys[0]), [False, False, False])
        self.assertTrue(self.g.set_coil(keys[0], True, 'section').ok)
        self.assertEqual(self.coils(keys[0]), [True, True, True])
        self.assertTrue(self.g.undo().ok)                                         # the whole section is ONE step
        self.assertEqual(self.coils(keys[0]), [False, False, False])
        self.assertTrue(self.g.redo().ok)
        self.assertEqual(self.coils(keys[0]), [True, True, True])
        head = next(r['key'] for r in self.g.rows() if r['kind'] == 'header' and r['fid'] == self.g.point_of(keys[0])[0].id)
        self.assertTrue(self.g.set_coil(head, False).ok)                           # a heading clears the whole section
        self.assertEqual(self.coils(keys[0]), [False, False, False])

    def test_a_new_row_in_a_coil_section_is_a_coil_row_and_the_flag_is_saved(self):
        keys = self.aci_rows(1)
        self.assertTrue(self.g.set_coil(keys[0], True, 'section').ok)
        g = self.g
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank'), 'nominal')
        self.assertTrue(g.commit_cell('200 A @ 50 Hz').ok)
        self.assertEqual(self.coils(keys[0]), [True, True])
        k2 = [r['key'] for r in self.points()][1]
        self.assertTrue(g.panel_state(k2)['form']['coil'])
        back = db.Datasheet.from_dict(g.ds.to_dict())
        self.assertEqual([dsb_coil.is_coil(back.function('aci'), q) for q in back.function('aci').points], [True, True])

    def test_multiple_rows_each_get_their_own_copy_of_the_flag(self):
        k = self.aci_rows(1)[0]
        f = self.g.panel_state(k)['form']
        f.update(coil=True, multi=True, multi_high='900 A', multi_n='3', multi_mode='span')
        self.assertTrue(self.g.calc_row(k, f).ok)
        fn = self.g.point_of(k)[0]
        self.assertGreaterEqual(len(fn.points), 3)
        self.assertEqual([dsb_coil.is_coil(fn, q) for q in fn.points], [True] * len(fn.points))
        self.assertTrue(self.g.set_coil(self.points()[1]['key'], False).ok)       # changing one leaves the rest
        fn = self.g.point_of(k)[0]
        self.assertEqual([dsb_coil.is_coil(fn, q) for q in fn.points].count(True), len(fn.points) - 1)

    def test_the_columns_show_the_coil_and_the_calibrator_and_the_coils_uncertainty(self):
        keys = self.aci_rows(2)
        self.assertTrue(self.g.set_coil(keys[0], True, 'section').ok)
        self.g.refresh_standard_columns()
        k500 = next(r['key'] for r in self.points() if r['nominal'].startswith('500'))
        r = self.g.row(k500)
        a = self.g._grid_result().assignments[self.g.point_of(k500)[1].id]
        self.assertTrue(r['standard'].endswith(' + coil'))
        self.assertTrue(r['standard'].startswith(a.standard))
        self.assertIn(dsb_coil.LABEL, r['standard_tip'])
        self.assertIn(dsb_coil.LABEL, r['unc_tip'])
        self.assertEqual(a.unc_standard, dsb_coil.MODEL)
        self.assertEqual(r['unc'], unc_mod.format_value(a.uncertainty, 'A'))
        self.assertEqual(r['unc'], '5.0 A')                                       # AC 500 A at 50 Hz
        std_list = [c['label'] for c in self.g.standard_choices(keys[0])]
        self.assertFalse([x for x in std_list if 'COIL' in x.upper()])           # never in the calibrator picker

    def test_a_coil_row_does_not_change_the_other_rows_or_the_automation(self):
        keys = self.aci_rows(2)
        self.g.refresh_standard_columns()
        before = {k: (self.g.row(k)['standard'], self.g.row(k)['unc']) for k in keys}
        self.assertTrue(self.g.set_coil(keys[0], True).ok)
        self.g.refresh_standard_columns()
        self.assertEqual((self.g.row(keys[1])['standard'], self.g.row(keys[1])['unc']), before[keys[1]])
        a = self.g._grid_result().assignments[self.g.point_of(keys[0])[1].id]
        self.assertTrue(a.can_automate)                                            # the calibrator still sources it
