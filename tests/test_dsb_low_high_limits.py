"""The Datasheet Builder shows a tolerance as its LOW LIMIT and HIGH LIMIT (absolute values), not as a +/- error.  This is a display change: what is stored
and what judges a reading must not move.  Covers the grid / Inspector model, the limit wording of the run window, the report headings and a golden check of
the limits, the runnable spec and the PASS / FAIL verdicts of the sample sheets before / after.  No tkinter (tests/_tk_stub.py stands in).
Run:  python -m unittest tests.test_dsb_low_high_limits"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import _tk_stub  # noqa: E402
_tk_stub.install()
import dsb_fixtures as fx  # noqa: E402
import dsb_golden  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import datasheet_builder_ui_model as M  # noqa: E402
import handheld_dmm as hh  # noqa: E402

D = Decimal


_TMPS = []


def grid(ds):
    tmp = tempfile.TemporaryDirectory()
    _TMPS.append(tmp)
    t = Path(tmp.name)
    return M.GridModel(M.Storage(t / 'u', t / 'r.sqlite3', who='tester'), ds)


def tearDownModule():
    while _TMPS:
        _TMPS.pop().cleanup()


def points(g, fid=None):
    return [r for r in g.rows() if r['kind'] == 'point' and (fid is None or r['fid'] == fid)]


def limit_si(g, row):
    """(low, high) of a row from the core, SI Decimals."""
    fn, p = g.point_of(row['key'])
    lim = fn.limit_for(p, g.period, g.ds)
    return lim.low, lim.high


def shown_si(g, row, col):
    """The number a limit cell shows, read back as SI (the cell text carries its own unit and prefix)."""
    fn, p = g.point_of(row['key'])
    return db.parse_quantity(row[col], fn.unit or None)


class Golden(unittest.TestCase):
    def test_limits_spec_steps_and_verdicts_are_what_they_were_before_the_display_change(self):
        want = json.loads((HERE / 'dsb_golden_limits.json').read_text(encoding='utf-8'))
        have = dsb_golden.golden()
        self.assertEqual(sorted(have), sorted(want))
        for name in want:
            self.assertEqual(have[name], want[name], f'{name}: a limit, a spec step or a PASS / FAIL verdict changed')

    def test_the_golden_sheets_cover_symmetric_asymmetric_typed_and_one_sided(self):
        sheets = dsb_golden.sheets()
        def lim(ds, fn, p):
            try:
                return fn.limit_for(p, '1y', ds)
            except db.DsError:
                return None
        asym = sum(1 for ds in sheets.values() for fn in ds.functions for p in fn.points
                   if lim(ds, fn, p) is not None and lim(ds, fn, p).minus is not None and lim(ds, fn, p).minus != lim(ds, fn, p).plus)
        typed = sum(1 for ds in sheets.values() for fn in ds.functions for p in fn.points if p.overrides)
        one_sided = sum(1 for ds in sheets.values() for fn in ds.functions if any(e.mode != 'both' for e in fn.spec))
        self.assertTrue(asym > 5 and typed >= 5 and one_sided >= 1, (asym, typed, one_sided))

    def test_spec_tol_text_is_unchanged_because_procmods_hashes_it(self):
        """A procedure modification stays attached to a point through procmods.point_hash, which includes tol_text: the saved text must not move."""
        spec = dsp.export_spec(fx.dmm_34461a_like()).spec
        step = next(s for s in spec['steps'] if s['id'] == 'dcv.r10.+5')
        self.assertEqual(step['tol_text'], '±(0.004 % of reading + 0.0035 % of range) = ±550 µV')


class GridShowsLimits(unittest.TestCase):
    def test_every_row_of_every_sample_sheet_shows_low_and_high_equal_to_the_core_limits(self):
        n = 0
        for name, ds in dsb_golden.sheets().items():
            g = grid(ds)
            for row in points(g):
                fn, p = g.point_of(row['key'])
                try:
                    lo, hi = limit_si(g, row)
                except db.DsError:
                    continue
                if fn.info.get('passfail'):
                    continue
                one_sided = fn.limit_for(p, g.period, g.ds).one_sided
                if one_sided:                                          # 'at least -3 dB': the engine's bound is not shown as a limit
                    self.assertIn('no limit', (row['low'], row['high']), (name, row['key']))
                    self.assertEqual(shown_si(g, row, 'low') if row['high'] == 'no limit' else shown_si(g, row, 'high'), lo if row['high'] == 'no limit' else hi)
                    continue
                self.assertEqual(shown_si(g, row, 'low'), lo, (name, row['key']))
                self.assertEqual(shown_si(g, row, 'high'), hi, (name, row['key']))
                self.assertNotIn('±', row['low'] + row['high'])
                n += 1
        self.assertGreater(n, 250)

    def test_example_9_95_and_10_05_volts(self):
        ds = db.Datasheet('Acme', 'X1', 'x')
        ds.set_periods([('1y', '1 year')], '1y')
        f = ds.add_function('DCV')
        f.add_range('100', '1e-4')
        ds.set_spec(f, '0.5 % of reading')
        db.add_point(f, 10)
        row = points(grid(ds))[0]
        self.assertEqual((row['low'], row['high']), ('9.9500 V', '10.0500 V'))      # same exact digits, padded to the 100 uV resolution

    def test_asymmetric_and_typed_limits_are_shown_as_they_are(self):
        sheets = dsb_golden.sheets()
        g = grid(sheets['dmm_typed_limits'])
        rows = {r['pid']: r for r in points(g, 'dcv')}
        pid = g.ds.function('dcv').points[2].id
        self.assertEqual((shown_si(g, rows[pid], 'low'), shown_si(g, rows[pid], 'high')), (D('4.9'), D('5.2')))
        self.assertEqual(rows[pid]['limits_from'], 'typed')
        self.assertEqual(rows[pid]['formula'], '')
        g = grid(sheets['dmm_asymmetric'])
        fn = g.ds.function('dcv')
        row = next(r for r in points(g, 'dcv') if r['pid'] == fn.points[3].id)
        lim = fn.limit_for(fn.points[3], '1y', g.ds)
        self.assertNotEqual(lim.minus, lim.plus)
        self.assertEqual((shown_si(g, row, 'low'), shown_si(g, row, 'high')), (lim.low, lim.high))
        self.assertEqual(row['limits_from'], 'formula')
        self.assertIn('2 % of reading', row['formula'])

    def test_display_scaling_follows_the_row_not_the_error(self):
        g = grid(fx.dmm_34461a_like())
        row = next(r for r in points(g, 'dcv') if r['nominal'].startswith('+10') and 'mV' in r['nominal'])
        self.assertTrue(row['low'].endswith('mV') and row['high'].endswith('mV'), (row['low'], row['high']))
        zero = next(r for r in points(g, 'dcv') if r['nominal'].startswith('0.'))
        self.assertTrue(zero['low'].startswith('-') and not zero['high'].startswith('-'), (zero['low'], zero['high']))

    def test_pass_fail_rows_say_so_and_have_no_limits(self):
        g = grid(fx.dmm_34461a_like())
        g.add_handheld_functions()
        res = g.set_target_function('Continuity')
        self.assertTrue(res.ok, res.message)
        g.select(next(r['key'] for r in g.rows() if r['kind'] == 'blank' and r['fid'] == 'cont'), 'nominal')
        self.assertTrue(g.commit_cell('10 ohm').ok)
        row = points(g, 'cont')[0]
        self.assertEqual((row['low'], row['high']), ('Beeper on', ''))

    def test_print_view_has_low_and_high_columns_and_no_plus_minus(self):
        g = grid(fx.dmm_34461a_like())
        view = g.print_view()
        self.assertEqual(view['columns'][-2:], ['LOW LIMIT', 'HIGH LIMIT'])
        self.assertNotIn('CALIBRATION TOLERANCE', view['columns'])
        for r in view['rows']:
            self.assertEqual(len(r['cells']), 8)
            self.assertNotIn('±', ''.join(r['cells']))

    def test_the_status_line_hint_names_the_statement_but_the_grid_does_not(self):
        g = grid(fx.dmm_34461a_like())
        key = points(g, 'dcv')[3]['key']
        g.select(key, 'low')
        fn, p = g.point_of(key)
        g.calc_row(key, dict(g.panel_state(key)['form'], types=['iv'], plus=dict(g.blank_side(), iv='0.05')))
        st = g.panel_state(key)
        self.assertIn('0.05 % of reading', st['note'])
        self.assertIn('Limits calculated from', st['note'])
        row = g.row(key)
        self.assertNotIn('%', row['low'] + row['high'])


class EditingLimitCells(unittest.TestCase):
    def setUp(self):
        self.g = grid(fx.dmm_34461a_like())
        self.row = next(r for r in points(self.g, 'dcv') if r['nominal'] == '+5.00000 V')
        self.key = self.row['key']
        self.fn, self.p = self.g.point_of(self.key)

    def now(self):
        return self.g.row(self.key)

    def test_typing_a_number_in_low_types_that_limit_and_keeps_the_high_one(self):
        before = limit_si(self.g, self.now())
        res = self.g.commit_cell('4.95', self.key, 'low', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(limit_si(self.g, self.now()), (D('4.95'), before[1]))
        self.assertEqual(self.p.overrides['1y'], {'low': '4.95', 'high': db.fmt(before[1])})     # stored as the typed pair (absolute SI strings)
        self.assertEqual(self.now()['limits_from'], 'typed')
        self.assertIsNone(self.p.spec)                                # the function's table is not touched
        self.assertEqual(self.p.overrides.get('90d'), None)           # only the period on show

    def test_typing_a_number_in_high_with_a_unit(self):
        res = self.g.commit_cell('5050 mV', self.key, 'high', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(limit_si(self.g, self.now())[1], D('5.05'))

    def test_enter_on_a_calculated_cell_without_changing_it_does_not_turn_it_into_typed_limits(self):
        text = self.g.cell_text(self.key, 'low')
        res = self.g.commit_cell(text, self.key, 'low', move='stay')
        self.assertTrue(res.ok)
        self.assertIn('No change', res.message)
        self.assertEqual(self.p.overrides, {})
        self.assertEqual(self.now()['limits_from'], 'formula')

    def test_low_to_high_types_both(self):
        res = self.g.commit_cell('4.9 to 5.2 V', self.key, 'low', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(limit_si(self.g, self.now()), (D('4.9'), D('5.2')))

    def test_a_plus_minus_value_is_a_symmetric_tolerance_as_before(self):
        res = self.g.commit_cell('±5 mV', self.key, 'high', move='stay')
        self.assertTrue(res.ok, res.message)
        lo, hi = limit_si(self.g, self.now())
        nominal = self.p.nominal
        self.assertEqual((lo, hi), (nominal - D('0.005'), nominal + D('0.005')))
        self.assertIsNotNone(self.p.spec)
        self.assertEqual(self.p.spec.exprs['1y'].printed, '±5 mV')
        self.assertEqual(self.p.overrides, {})
        self.assertEqual(self.now()['limits_from'], 'formula')
        self.assertNotIn('±', self.now()['low'] + self.now()['high'])

    def test_a_formula_typed_in_a_limit_cell_sets_the_tolerance_statement(self):
        res = self.g.commit_cell('0.05 % of reading + 2 counts', self.key, 'low', move='stay')
        self.assertTrue(res.ok, res.message)
        res_counts = self.fn.range(self.p.range_id).resolution
        tol = self.p.nominal * D('0.0005') + 2 * res_counts
        self.assertEqual(limit_si(self.g, self.now()), (self.p.nominal - tol, self.p.nominal + tol))
        self.assertEqual(self.now()['formula'], '0.05 % of reading + 2 counts')

    def test_a_formula_after_typed_limits_replaces_them(self):
        self.g.commit_cell('4.9 to 5.2', self.key, 'low', move='stay')
        self.assertEqual(self.now()['limits_from'], 'typed')
        self.g.commit_cell('0.1 % of reading', self.key, 'high', move='stay')
        self.assertEqual(self.now()['limits_from'], 'formula')
        self.assertEqual(self.p.overrides, {})

    def test_negative_numbers_are_limits_not_statements(self):
        self.assertFalse(M.GridModel.is_statement('-3'))
        self.assertFalse(M.GridModel.is_statement('-3 mV'))
        self.assertFalse(M.GridModel.is_statement('+4.99 V'))
        self.assertTrue(M.GridModel.is_statement('±3 mV'))
        self.assertTrue(M.GridModel.is_statement('0.01 %'))
        self.assertTrue(M.GridModel.is_statement('2 counts'))
        self.assertTrue(M.GridModel.is_statement('max(0.01 %, 50 uV)'))

    def test_delete_clears_both_limits(self):
        self.g.commit_cell('4.9 to 5.2', self.key, 'low', move='stay')
        self.g.select(self.key, 'high')
        res = self.g.clear_cell()
        self.assertTrue(res.ok, res.message)
        self.assertIn('both limits', res.message)
        self.assertEqual(self.p.overrides, {})

    def test_bad_text_changes_nothing_and_says_what_to_type(self):
        before = (dict(self.p.overrides), self.p.spec)
        res = self.g.commit_cell('abc', self.key, 'low', move='stay')
        self.assertFalse(res.ok)
        self.assertEqual((dict(self.p.overrides), self.p.spec), before)

    def test_inverted_limits_are_flagged_on_the_row(self):
        self.g.commit_cell('6', self.key, 'low', move='stay')
        row = self.now()
        self.assertEqual(row['level'], 'error')
        self.assertEqual(set(row['bad']) & {'low', 'high'}, {'low', 'high'})

    def test_undo_brings_the_calculated_limits_back(self):
        before = (self.now()['low'], self.now()['high'])
        self.g.commit_cell('4.9', self.key, 'low', move='stay')
        self.assertNotEqual((self.now()['low'], self.now()['high']), before)
        self.assertTrue(self.g.undo().ok)
        self.assertEqual((self.now()['low'], self.now()['high']), before)

    def test_a_new_row_with_only_one_limit_typed_is_an_error_until_the_other_is_typed(self):
        g = grid(db.Datasheet('A', 'B', 'c'))
        self.assertTrue(g.set_target_function('DC volts').ok)
        g.select('b:0', 'nominal')
        self.assertTrue(g.commit_cell('5 V').ok)
        key = points(g)[0]['key']
        res = g.commit_cell('4.9', key, 'low', move='stay')
        self.assertTrue(res.ok, res.message)
        row = g.row(key)
        self.assertEqual((row['low'], row['high']), ('4.9 V', 'open'))
        self.assertIn('limit_open', [p['code'] for p in g.problems()])
        self.assertEqual(row['level'], 'error')
        self.assertTrue(g.commit_cell('5.1', key, 'high', move='stay').ok)
        self.assertNotIn('limit_open', [p['code'] for p in g.problems()])
        self.assertEqual((g.row(key)['low'], g.row(key)['high']), ('4.9 V', '5.1 V'))

    def test_percent_units_function_takes_a_percent_limit(self):
        ds = db.Datasheet('A', 'B', 'c')
        ds.set_periods([('1y', '1 year')], '1y')
        f = ds.add_function('PCT')
        f.add_range('100', '0.1')
        ds.set_spec(f, '0.5 % of reading')
        db.add_point(f, 50)
        g = grid(ds)
        key = points(g)[0]['key']
        res = g.commit_cell('49 %', key, 'low', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(limit_si(g, g.row(key))[0], D('49'))


class InspectorPath(unittest.TestCase):
    def setUp(self):
        self.g = grid(fx.dmm_34461a_like())
        self.row = next(r for r in points(self.g, 'dcv') if r['nominal'] == '+5.00000 V')
        self.key = self.row['key']
        self.fn, self.p = self.g.point_of(self.key)

    def test_panel_state_carries_the_limit_boxes(self):
        form = self.g.panel_state(self.key)['form']
        self.assertFalse(form['typed'])
        self.assertEqual((form['low'], form['high']), (self.row['low'], self.row['high']))

    def test_typed_form_stores_the_pair_and_both_boxes_are_needed(self):
        form = self.g.panel_state(self.key)['form']
        form.update(typed=True, low='4.9', high='')
        res = self.g.calc_row(self.key, form)
        self.assertFalse(res.ok)
        self.assertIn('both', res.message)
        self.assertEqual(self.p.overrides, {})
        form.update(high='5.2')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertIn('Low limit 4.90000 V, High limit 5.20000 V', res.message)
        self.assertEqual(limit_si(self.g, self.g.row(self.key)), (D('4.9'), D('5.2')))
        self.assertTrue(self.g.panel_state(self.key)['form']['typed'])

    def test_unticking_and_calc_goes_back_to_a_calculated_tolerance(self):
        form = self.g.panel_state(self.key)['form']
        form.update(typed=True, low='4.9', high='5.2')
        self.g.calc_row(self.key, form)
        form = self.g.panel_state(self.key)['form']
        form.update(typed=False, types=['iv'])
        form['plus'].update(iv='0.1')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.p.overrides, {})
        self.assertEqual(self.g.row(self.key)['limits_from'], 'formula')
        self.assertEqual(limit_si(self.g, self.g.row(self.key)), (self.p.nominal * D('0.999'), self.p.nominal * D('1.001')))

    def test_calc_without_touching_the_limit_boxes_calculates_as_before(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'])
        form['plus'].update(iv='0.05')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertIn('Low limit', res.message)
        self.assertNotIn('±', res.message)
        self.assertEqual(self.p.overrides, {})

    def test_several_rows_at_once_need_a_tolerance_not_typed_limits(self):
        form = self.g.panel_state(self.key)['form']
        form.update(typed=True, low='1', high='2', multi=True, multi_high='9', multi_n='3')
        res = self.g.calc_row(self.key, form)
        self.assertFalse(res.ok)
        self.assertIn('Type the limits myself', res.message)

    def test_asymmetric_formula_shows_both_computed_limits(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'], asym=True)
        form['plus'].update(iv='1')
        form['minus'].update(iv='2')
        self.assertTrue(self.g.calc_row(self.key, form).ok)
        lo, hi = limit_si(self.g, self.g.row(self.key))
        self.assertEqual((lo, hi), (self.p.nominal * D('0.98'), self.p.nominal * D('1.01')))
        self.assertTrue(self.g.row(self.key)['formula'].startswith('1 %'))


class RunWindowAndReport(unittest.TestCase):
    def test_limit_line_shows_low_and_high_for_a_datasheet_builder_step(self):
        spec = dsp.export_spec(fx.dmm_34461a_like()).spec
        step = next(s for s in spec['steps'] if s['id'] == 'dcv.r10.+5')
        line = hh.limit_line(step)
        self.assertEqual(line, 'Low limit 4.99650 V, High limit 5.00350 V  (from 0.0040 % of reading + 0.0035 % of range)'.replace('4.99650', step['low']).replace('5.00350', step['high']))
        self.assertNotIn('±', line)
        self.assertIn(step['low'], line)
        self.assertIn(step['high'], line)
        self.assertTrue(step['tol_text'].startswith('±('), 'the saved text is unchanged')

    def test_limit_line_for_typed_limits_and_for_other_specs(self):
        typed = dsb_golden.sheets()['dmm_typed_limits']
        spec = dsp.export_spec(typed).spec
        fn = typed.function('dcv')
        pid = next(pid for pid in (p.id for p in fn.points) if typed.function('dcv').point(pid).overrides)
        step = next(s for s in spec['steps'] if s['id'] == pid)
        if step.get('tol_text'):
            self.assertIn('typed limits', hh.limit_line(step))
        shipped = {'tol_text': 'Table 2: 4.9 to 5.1 V   (published specification: ±(1 % of reading + 2 counts))', 'low': '4.9', 'high': '5.1', 'display_unit': 'V'}
        self.assertEqual(hh.limit_line(shipped), shipped['tol_text'])               # a shipped spec keeps its own wording
        self.assertEqual(hh.limit_line({}), '')

    def test_report_headings_for_limits_only_when_asked(self):
        import report_pdf
        self.assertEqual(report_pdf.LIMIT_HEADINGS, {'Tolerance -': 'Low Limit', 'Tolerance +': 'High Limit'})
        self.assertEqual(report_pdf.COLUMNS[2:4], ('Tolerance -', 'Tolerance +'))        # the row keys (snapshots, history, every engine) did not change
        import shutil
        import subprocess
        if not shutil.which('pdftotext'):
            self.skipTest('pdftotext is not installed')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rows = [report_pdf.cert_row('Test point', 5.0, 4.9, 5.1, 'V', reading=5.0)]

        def head(details):
            path = Path(tmp.name) / f'r{len(details)}.pdf'
            report_pdf.write_calibration_pdf(str(path), rows, header=[('Instrument', 'X')], details=details, record_history=False)
            out = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout
            return next(line for line in out.splitlines() if 'Nominal' in line and 'UOM' in line), out
        other, _ = head({})
        self.assertIn('Tolerance -', other)                                           # every other procedure's report is exactly as before
        self.assertIn('Tolerance +', other)
        dsb, text = head({'limit_labels': True})
        self.assertIn('Low Limit', dsb)
        self.assertIn('High Limit', dsb)
        self.assertIn('4.9', text)
        self.assertIn('5.1', text)


if __name__ == '__main__':
    unittest.main()
