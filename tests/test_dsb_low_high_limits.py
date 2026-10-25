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
        row = next(r for r in points(g, 'dcv') if r['nominal'].startswith('10') and 'mV' in r['nominal'])
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


def stored(g):
    """Everything about the sheet that is stored (a limit cell must never change any of it)."""
    return json.dumps(g.ds.to_dict(), sort_keys=True, default=str)


class LimitCellsAreReadOnly(unittest.TestCase):
    """The Low / High limit cells show what the tolerance calculator works out and cannot be typed in: no 'Type the limits myself', no typed-limit path."""

    def setUp(self):
        self.g = grid(fx.dmm_34461a_like())
        self.row = next(r for r in points(self.g, 'dcv') if r['nominal'] == '5.00000 V')
        self.key = self.row['key']
        self.fn, self.p = self.g.point_of(self.key)

    def test_the_limit_columns_are_not_editable_and_the_hint_names_the_calculator(self):
        for col in ('low', 'high'):
            ok, why = self.g.cell_editable(self.key, col)
            self.assertFalse(ok)
            self.assertEqual(why, M.LIMITS_HINT)
        self.assertIn('tolerance calculator', M.LIMITS_HINT)
        self.assertEqual(M.EDIT_COLS, ('function', 'nominal'))
        blank = next(r['key'] for r in self.g.rows() if r['kind'] == 'blank')
        self.assertFalse(self.g.cell_editable(blank, 'low')[0])

    def test_typing_anything_in_a_limit_cell_changes_nothing(self):
        before = stored(self.g)
        for col in ('low', 'high'):
            for text in ('4.95', '5050 mV', '4.9 to 5.1', '±5 mV', '0.05 % of reading', 'abc', '-1'):
                res = self.g.commit_cell(text, self.key, col, move='stay')
                self.assertFalse(res.ok, (col, text))
                self.assertEqual(res.message, M.LIMITS_HINT)
        self.assertEqual(stored(self.g), before)
        self.assertEqual(self.p.overrides, {})

    def test_delete_on_a_limit_cell_does_not_clear_the_tolerance(self):
        before = stored(self.g)
        for col in ('low', 'high'):
            self.g.select(self.key, col)
            res = self.g.clear_cell()
            self.assertFalse(res.ok)
            self.assertEqual(res.message, M.LIMITS_HINT)
        self.assertEqual(stored(self.g), before)

    def test_the_typed_limit_code_is_gone(self):
        for name in ('_edit_limit', '_typed_pair', 'is_statement'):
            self.assertFalse(hasattr(M.GridModel, name), name)
        self.assertNotIn('typed', self.g.blank_form())

    def test_tab_skips_the_limit_cells(self):
        self.g.select(self.key, 'nominal')
        self.g.tab()
        self.assertEqual(self.g.sel_col, 'function')
        self.assertNotEqual(self.g.sel_key, self.key)

    def test_the_edit_bar_still_shows_the_calculated_limit(self):
        self.g.select(self.key, 'low')
        self.assertEqual(self.g.cell_text(), self.row['low'])

    def test_the_calculator_changes_the_displayed_limits_and_undo_brings_them_back(self):
        before = (self.row['low'], self.row['high'])
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'])
        form['plus'].update(iv='0.1')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(limit_si(self.g, self.g.row(self.key)), (self.p.nominal * D('0.999'), self.p.nominal * D('1.001')))
        self.assertTrue(self.g.undo().ok)
        self.assertEqual((self.g.row(self.key)['low'], self.g.row(self.key)['high']), before)


class StoredTypedLimitsStillWork(unittest.TestCase):
    """An old sheet may hold a stored Low / High pair (Point.overrides): it is read, judged and printed as before, shown with a marker, and can be cleared
    (or replaced by the calculator).  Nothing is dropped silently."""

    def setUp(self):
        self.g = grid(dsb_golden.sheets()['dmm_typed_limits'])
        self.fn = self.g.ds.function('dcv')
        self.p = self.fn.points[2]                                    # typed 4.9 .. 5.2 for the 1y period
        self.key = f'p:dcv:{self.p.id}'

    def test_it_is_shown_as_the_stored_pair_with_a_marker_flag(self):
        row = self.g.row(self.key)
        self.assertEqual(row['limits_from'], 'typed')
        self.assertEqual((shown_si(self.g, row, 'low'), shown_si(self.g, row, 'high')), (D('4.9'), D('5.2')))
        st = self.g.panel_state(self.key)
        self.assertTrue(st['typed_limits'])
        self.assertEqual(st['note'], M.TYPED_LIMITS_NOTE)
        self.assertFalse(self.g.panel_state(points(self.g, 'dcv')[-1]['key'])['typed_limits'])

    def test_it_cannot_be_edited_in_the_cell(self):
        before = stored(self.g)
        self.assertFalse(self.g.commit_cell('4.5', self.key, 'low', move='stay').ok)
        self.assertEqual(stored(self.g), before)

    def test_clear_typed_limits_removes_the_pair_of_the_period_on_show_only(self):
        self.p.overrides['90d'] = {'low': '1', 'high': '2'}           # another period's pair is stored data: it must stay
        res = self.g.clear_typed_limits(self.key)
        self.assertTrue(res.ok, res.message)
        self.assertNotIn('1y', self.p.overrides)
        self.assertEqual(self.p.overrides['90d'], {'low': '1', 'high': '2'})
        self.assertNotEqual(self.g.row(self.key)['limits_from'], 'typed')
        self.assertFalse(self.g.clear_typed_limits(self.key).ok)       # nothing left to clear
        self.assertTrue(self.g.undo().ok)
        self.assertEqual(self.g.ds.function('dcv').points[2].overrides['1y'], {'low': '4.9', 'high': '5.2'})

    def test_calc_replaces_the_pair_and_says_so(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'])
        form['plus'].update(iv='0.1')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertIn('typed limits of this row were replaced', res.message)
        self.assertNotIn('1y', self.p.overrides)
        self.assertEqual(self.g.row(self.key)['limits_from'], 'formula')

    def test_calc_with_no_tolerance_given_keeps_the_pair(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=[])
        self.assertFalse(self.g.calc_row(self.key, form).ok)
        self.assertEqual(self.p.overrides['1y'], {'low': '4.9', 'high': '5.2'})

    def test_a_row_with_one_stored_limit_is_still_an_error(self):
        g = grid(fx.dmm_34461a_like())
        row = next(r for r in points(g, 'dcv') if r['nominal'] == '5.00000 V')
        p = g.point_of(row['key'])[1]
        p.overrides['1y'] = {'low': '4.9', 'high': ''}
        g._bump()
        self.assertIn('limit_open', [x['code'] for x in g.problems()])
        self.assertEqual(g.row(row['key'])['level'], 'error')


class InspectorPath(unittest.TestCase):
    def setUp(self):
        self.g = grid(fx.dmm_34461a_like())
        self.row = next(r for r in points(self.g, 'dcv') if r['nominal'] == '5.00000 V')
        self.key = self.row['key']
        self.fn, self.p = self.g.point_of(self.key)

    def test_panel_state_carries_the_limit_boxes_and_no_typed_mode(self):
        st = self.g.panel_state(self.key)
        form = st['form']
        self.assertNotIn('typed', form)
        self.assertFalse(st['typed_limits'])
        self.assertEqual((form['low'], form['high']), (self.row['low'], self.row['high']))

    def test_the_limit_boxes_are_ignored_by_calc(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'], low='1', high='2')
        form['plus'].update(iv='0.05')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertIn('Low limit', res.message)
        self.assertNotIn('±', res.message)
        self.assertEqual(self.p.overrides, {})
        self.assertEqual(limit_si(self.g, self.g.row(self.key)), (self.p.nominal * D('0.9995'), self.p.nominal * D('1.0005')))

    def test_several_rows_at_once_get_their_limits_from_the_tolerance(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'], multi=True, nominal='6', multi_high='9', multi_n='3')
        form['plus'].update(iv='0.1')
        res = self.g.calc_row(self.key, form)
        self.assertTrue(res.ok, res.message)
        self.assertIn('rows added', res.message)

    def test_asymmetric_formula_shows_both_computed_limits(self):
        form = self.g.panel_state(self.key)['form']
        form.update(types=['iv'], asym=True)
        form['plus'].update(iv='1')
        form['minus'].update(iv='2')
        self.assertTrue(self.g.calc_row(self.key, form).ok)
        lo, hi = limit_si(self.g, self.g.row(self.key))
        self.assertEqual((lo, hi), (self.p.nominal * D('0.98'), self.p.nominal * D('1.01')))
        self.assertTrue(self.g.row(self.key)['formula'].startswith('1 %'))


class BareNumberIsInTheUnitShown(unittest.TestCase):
    """A bare number typed in a NOMINAL cell is taken in the unit the row shows: 5 on a mV row is 5 mV (not 5 V).  An explicit unit stays as typed."""

    def setUp(self):
        self.g = grid(fx.dmm_34461a_like())

    def row(self, nominal):
        return next(r for r in points(self.g, 'dcv') if r['nominal'] == nominal)

    def nominal_of(self, key):
        return self.g.point_of(key)[1].nominal

    def test_5_on_a_mV_row_is_5_mV(self):
        r = self.row('50.0000 mV')
        res = self.g.commit_cell('5', r['key'], 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('0.005'))
        self.assertEqual(self.g.row(res.detail)['nominal'], '5.0000 mV')       # zero padded to the range resolution (100 nV on the 100 mV range)

    def test_explicit_units_stay_as_typed(self):
        r = self.row('50.0000 mV')
        res = self.g.commit_cell('0.02 V', r['key'], 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('0.02'))
        r = self.row('5.00000 V')
        res = self.g.commit_cell('4950 mV', r['key'], 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('4.95'))

    def test_5_on_a_volt_row_is_5_V(self):
        r = self.row('10.0000 V')
        res = self.g.commit_cell('7', r['key'], 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('7'))

    def test_a_new_row_follows_the_functions_display_unit(self):
        fn = self.g.ds.function('dcv')
        self.assertEqual(self.g.bare_unit(fn), '')                   # automatic: a bare number is the base unit, as it always was
        fn.display_unit = 'm'
        self.assertEqual(self.g.bare_unit(fn), 'mV')
        self.assertEqual(self.g.blank_form(fn)['units'], 'mV')
        self.g._bump()
        self.assertTrue(self.g.set_target_function('DC volts').ok)
        key = next(r['key'] for r in self.g.rows() if r['kind'] == 'blank')
        res = self.g.commit_cell('3', key, 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('0.003'))

    def test_the_range_display_unit_wins(self):
        fn = self.g.ds.function('dcv')
        fn.range('r10').display_unit = 'm'
        self.g._bump()
        r = self.row('5000.00 mV')
        res = self.g.commit_cell('4000', r['key'], 'nominal', move='stay')
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.nominal_of(res.detail), D('4'))

    def test_the_inspector_units_box_agrees(self):
        r = self.row('50.0000 mV')
        form = self.g.panel_state(r['key'])['form']
        self.assertEqual(form['units'], 'mV')
        form.update(nominal='5', types=['iv'])
        form['plus'].update(iv='0.1')
        res = self.g.calc_row(r['key'], form)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.g.point_of(self.g.sel_key)[1].nominal, D('0.005'))      # the row's id follows its value


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
