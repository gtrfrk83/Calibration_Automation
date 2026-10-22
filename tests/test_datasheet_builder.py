"""Datasheet Builder core: quantities, exact expression evaluation (hand-worked examples), parser, serialisation, calculator, limits, validation.
No tkinter.   Run:  python -m unittest tests.test_datasheet_builder"""
import json
import os
import re
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import datasheet_builder as db  # noqa: E402
import dsb_fixtures as fx  # noqa: E402


def ctx(reading, fs=None, res=None, f=None):
    return db.Ctx(D(str(reading)), None if fs is None else D(str(fs)), None if res is None else D(str(res)), None if f is None else D(str(f)))


class Quantities(unittest.TestCase):
    def test_parse(self):
        for text, unit, want in [('10 mV', 'V', '0.01'), ('5 kΩ', 'ohm', '5000'), ('1.5uF', 'F', '0.0000015'), ('250', 'V', '250'),
                                 ('2 MHz', 'Hz', '2000000'), ('100 µA', 'A', '0.0001'), ('5 k', 'ohm', '5000'), ('-3 dB', 'dB', '-3'), ('1e3', None, '1000')]:
            self.assertEqual(db.parse_quantity(text, unit), D(want), text)

    def test_wrong_unit_is_an_error(self):
        with self.assertRaises(db.DsError) as c:
            db.parse_quantity('5 mA', 'V')
        self.assertEqual(c.exception.code, 'unit')
        with self.assertRaises(db.DsError):
            db.parse_quantity('abc')

    def test_mega_versus_milli_is_case_sensitive(self):
        self.assertEqual(db.parse_quantity('1 MHz', 'Hz'), D(1000000))
        self.assertEqual(db.parse_quantity('1 mHz', 'Hz'), D('0.001'))

    def test_dec_rejects_nan_and_floats_keep_shortest_repr(self):
        self.assertEqual(db.dec(0.1), D('0.1'))
        for bad in ('nan', 'inf', None, True, 'x'):
            with self.assertRaises(db.DsError):
                db.dec(bad)

    def test_display_scaling_is_display_only(self):
        self.assertEqual(db.format_si(D('0.0035'), 'V'), '3.5 mV')
        self.assertEqual(db.format_si(D('20000'), 'ohm'), '20 kΩ')
        self.assertEqual(db.format_si(D('5'), 'V', decimals=3), '5.000 V')
        self.assertEqual(db.format_si(D('0.0001'), 'A'), '100 µA')
        self.assertEqual(db.format_si(D('25'), 'degC'), '25 °C')
        self.assertEqual(db.fmt(D('1E+3')), '1000')
        self.assertEqual(db.fmt(D('0.0010')), '0.001')


class Expressions(unittest.TestCase):
    def test_percent_reading_plus_percent_range_worked_example(self):
        # 0.05 % of 5.000 V = 0.0025 V; 0.01 % of the 10 V range = 0.001 V; total 0.0035 V
        e = db.parse_expr('0.05 % of reading + 0.01 % of range', 'V')
        t = e.evaluate(ctx(5, 10))
        self.assertEqual((t.minus, t.plus), (D('0.0035'), D('0.0035')))

    def test_counts_use_the_range_resolution(self):
        # 0.5 % of 0.18 V = 0.0009 V; 3 counts of 0.0001 V = 0.0003 V; total 0.0012 V
        t = db.parse_expr('0.5 % rdg + 3 digits', 'V').evaluate(ctx('0.18', res='0.0001'))
        self.assertEqual(t.plus, D('0.0012'))

    def test_ppm_and_absolute_terms(self):
        # 20 ppm of 10 V = 0.0002 V; + 0.5 mV = 0.0005 V; total 0.0007 V
        t = db.parse_expr('20 ppm of reading + 0.5 mV', 'V').evaluate(ctx(10))
        self.assertEqual(t.plus, D('0.0007'))
        # ppm of range: 3 ppm of a 100 V range = 0.0003 V
        self.assertEqual(db.parse_expr('3 ppm of range', 'V').evaluate(ctx(1, 100)).plus, D('0.0003'))

    def test_all_terms_summed(self):
        # 0.1 % of 2 V = 0.002; 0.05 % of 10 V = 0.005; 10 uV = 0.00001; 2 counts of 0.00001 = 0.00002 -> 0.00703
        e = db.parse_expr('0.1 % of reading + 0.05 % of range + 10 uV + 2 counts', 'V')
        self.assertEqual(e.evaluate(ctx(2, 10, '0.00001')).plus, D('0.00703'))

    def test_max_and_min(self):
        # greater of 0.01 % of a 10 V range (0.001 V) and 50 uV -> 0.001 V;  smaller -> 0.00005 V
        mx = db.parse_expr('max(0.01 % of range, 50 uV)', 'V')
        mn = db.parse_expr('min(0.01 % of range, 50 uV)', 'V')
        self.assertEqual(mx.evaluate(ctx(1, 10)).plus, D('0.001'))
        self.assertEqual(mn.evaluate(ctx(1, 10)).plus, D('0.00005'))

    def test_negative_reading_uses_magnitude(self):
        self.assertEqual(db.parse_expr('1 % of reading', 'V').evaluate(ctx(-5)).plus, D('0.05'))

    def test_db_is_a_ratio_on_the_reading_and_asymmetric(self):
        # 0.5 dB (amplitude) on 1 V: +(10^0.025 - 1) = 0.05925372517..., -(1 - 10^-0.025) = 0.05593912371...
        t = db.parse_expr('0.5 dB', 'V').evaluate(ctx(1))
        self.assertAlmostEqual(float(t.plus), 0.0592537251772889, 14)
        self.assertAlmostEqual(float(t.minus), 0.0559391237140766, 14)
        self.assertFalse(t.symmetric)
        # power basis: 10^(0.05) - 1 = 0.1220184543...
        tp = db.Term('db', '0.5', 'power').evaluate(ctx(1))
        self.assertAlmostEqual(float(tp.plus), 0.1220184543019633, 14)

    def test_db_function_unit_means_fixed_decibels(self):
        t = db.parse_expr('0.1 dB', 'dB').evaluate(ctx(0))
        self.assertEqual((t.minus, t.plus), (D('0.1'), D('0.1')))

    def test_exact_decimal_no_float_noise(self):
        # 0.1 + 0.2 style sums stay exact
        e = db.Expr('sum', [db.Term('abs', '0.1'), db.Term('abs', '0.2')])
        self.assertEqual(e.evaluate(ctx(0)).plus, D('0.3'))

    def test_missing_context_is_an_error(self):
        with self.assertRaises(db.ExprError) as c:
            db.parse_expr('1 % of range', 'V').evaluate(ctx(1))
        self.assertEqual(c.exception.code, 'missing_context')
        with self.assertRaises(db.ExprError):
            db.parse_expr('2 counts', 'V').evaluate(ctx(1, 10))

    def test_parser_never_guesses(self):
        for text, code in [('0.05 %', 'ambiguous_basis'), ('5', 'ambiguous_unit'), ('', 'empty'), ('banana', 'syntax'), ('0.5 mA', 'unit')]:
            with self.assertRaises(db.ExprError) as c:
                db.parse_expr(text, 'V')
            self.assertEqual(c.exception.code, code, text)
        # an explicit default basis is the caller's decision
        self.assertEqual(db.parse_expr('0.05 %', 'V', default_basis='reading').evaluate(ctx(100)).plus, D('0.05'))

    def test_printed_text_is_kept_and_human_text_regenerates(self):
        e = db.parse_expr('±(0.5 % rdg + 3 digits)', 'V')
        self.assertEqual(e.printed, '±(0.5 % rdg + 3 digits)')
        self.assertEqual(e.text('V'), '±(0.5 % of reading + 3 counts)')
        self.assertEqual(db.parse_expr('max(0.01 % of range, 50 uV)', 'V').text('V'), '±max(0.01 % of range, 50 µV)')

    def test_serialisation_round_trip(self):
        for text in ('0.05 % of reading + 0.01 % of range', 'max(0.01 % of range, 50 uV)', '0.5 dB', '20 ppm of reading + 2 counts + 1 mV'):
            e = db.parse_expr(text, 'V')
            e2 = db.Expr.from_dict(json.loads(json.dumps(e.to_dict())))
            self.assertEqual(e2.to_dict(), e.to_dict())
            c = ctx(3, 10, '0.0001')
            self.assertEqual(e2.evaluate(c), e.evaluate(c))

    def test_bad_expression_dicts(self):
        for d in ({'op': 'power', 'items': []}, {'op': 'sum', 'items': [{'t': 'wat', 'v': '1'}]}, {'op': 'sum', 'items': [{'t': 'abs', 'v': '-1'}]},
                  {'op': 'sum', 'items': ['x']}):
            with self.assertRaises(db.ExprError):
                db.Expr.from_dict(d)
        with self.assertRaises(db.ExprError):
            db.Expr('sum', []).evaluate(ctx(1))


class ShippedSpecCrossCheck(unittest.TestCase):
    """The expression engine reproduces, string for string, the limits the project's own builder wrote for the Klein MM325 (build_mm325.py:
    exact Decimal, nominal -/+ tolerance, no rounding)."""

    def test_mm325_limits(self):
        spec = json.loads((HERE.parent / 'specs' / 'klein_mm325_pv.json').read_text(encoding='utf-8'))
        checked = 0
        for s in spec['steps']:
            expr = db.parse_expr(s['accuracy'], s['base_unit'])
            factor = D(str(s['factor']))
            res = D(re.search(r'\+ \d+ \u00d7 ([\d.]+) ', s['tol_text']).group(1)) * factor      # the count size printed in the step's own tolerance text
            nominal = D(str(s['nominal']))
            tol = expr.evaluate(db.Ctx(nominal, None, res)).plus
            self.assertEqual(db.fmt((nominal - tol) / factor), db.fmt(D(s['low'])), s['id'])
            self.assertEqual(db.fmt((nominal + tol) / factor), db.fmt(D(s['high'])), s['id'])
            checked += 1
        self.assertEqual(checked, 18)


class Model(unittest.TestCase):
    def test_round_trip_of_every_fixture(self):
        for mk in (fx.dmm_34461a_like, fx.acv_bands_sheet, fx.generator_33220a_like, fx.scope_tds2000c_like):
            ds = mk()
            d = json.loads(ds.to_json())
            ds2 = db.Datasheet.from_json(json.dumps(d))
            self.assertEqual(ds2.to_dict(), ds.to_dict(), mk.__name__)
            for (fa, pa), (fb, pb) in zip(ds.all_points(), ds2.all_points()):
                if db.KINDS[fa.kind].get('passfail'):
                    continue
                for per in ds.period_ids():
                    self.assertEqual(fa.limit_for(pa, per, ds).__dict__, fb.limit_for(pb, per, ds2).__dict__)

    def test_not_a_datasheet(self):
        for bad in ('[]', '{"schema": "other"}', 'not json', '{"schema": "dsb-1", "functions": [{"id": "x"}]}'):
            with self.assertRaises(db.DsError):
                db.Datasheet.from_json(bad)

    def test_kinds_have_units_and_existing_names(self):
        self.assertEqual(db.KINDS['SCOPE_BW']['legacy'], 'BW')
        self.assertEqual(db.KINDS['SCOPE_TRIGGER']['legacy'], 'TRIG')
        for k in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'FREQ', 'PERIOD', 'TEMP', 'DIODE', 'CONT', 'SCOPE_GAIN', 'SCOPE_BW', 'SCOPE_TIMEBASE',
                  'SCOPE_TRIGGER', 'GEN_AMPL', 'GEN_FREQ', 'GEN_OFFSET'):
            self.assertIn(k, db.KINDS)
        self.assertEqual(db.KINDS['GEN_AMPL']['direction'], 'source')
        self.assertEqual(db.KINDS['SCOPE_GAIN']['direction'], 'measure')

    def test_functions_and_ranges(self):
        ds = db.Datasheet('A', 'B', 'C')
        fn = ds.add_function('DCV')
        fn.add_range(10, '0.0001')
        fn.add_range(1)
        self.assertEqual([r.id for r in fn.ranges], ['r1', 'r10'])           # kept ascending
        with self.assertRaises(db.DsError):
            fn.add_range(10)
        self.assertEqual(ds.add_function('DCV').id, 'dcv2')
        with self.assertRaises(db.DsError):
            ds.add_function('NOPE')
        self.assertEqual(fn.range_for(5).id, 'r10')
        self.assertIsNone(fn.range_for(50))


class Limits(unittest.TestCase):
    def sheet(self):
        ds = db.Datasheet('A', 'B', 'C')
        ds.set_periods([('90d', '90 days'), ('1y', '1 year')], '1y')
        fn = ds.add_function('DCV')
        fn.add_range(10, '0.0001')
        ds.set_spec(fn, {'90d': '0.03 % of reading', '1y': '0.05 % of reading + 0.01 % of range'})
        return ds, fn

    def test_limit_around_nominal_and_accept_text(self):
        ds, fn = self.sheet()
        p = db.add_point(fn, 5)
        lim = fn.limit_for(p, '1y', ds)
        self.assertEqual((lim.low, lim.high), (D('4.9965'), D('5.0035')))
        self.assertTrue(lim.symmetric)
        self.assertEqual(lim.accept_text('V'), 'Accept if 4.9965 V <= reading <= 5.0035 V')
        l90 = fn.limit_for(p, '90d', ds)
        self.assertEqual((l90.low, l90.high), (D('4.9985'), D('5.0015')))
        self.assertEqual(fn.tol_text(p, '1y', ds), '±(0.05 % of reading + 0.01 % of range) = ±3.5 mV')

    def test_asymmetric(self):
        ds, fn = self.sheet()
        fn.spec.clear()
        e = db.SpecEntry({'90d': db.parse_expr('1 %', 'V', 'reading'), '1y': db.parse_expr('1 %', 'V', 'reading')},
                         exprs_minus={'90d': db.parse_expr('2 %', 'V', 'reading'), '1y': db.parse_expr('2 %', 'V', 'reading')})
        fn.spec.append(e)
        p = db.add_point(fn, 5)
        lim = fn.limit_for(p, '1y', ds)
        self.assertEqual((lim.low, lim.high), (D('4.9'), D('5.05')))
        self.assertFalse(lim.symmetric)

    def test_one_sided_with_bound(self):
        ds, fn = self.sheet()
        fn.spec.clear()
        ds.set_spec(fn, '3 V', mode='low_only', bound='3')
        p = db.add_point(fn, 0)
        lim = fn.limit_for(p, '1y', ds)
        self.assertEqual((lim.low, lim.high), (D('-3'), D('3')))
        self.assertTrue(lim.one_sided and lim.bound_used)
        self.assertIsNone(db.Limit(D(0), D(-3), None).tolerance)

    def test_override_wins_and_is_per_period(self):
        ds, fn = self.sheet()
        p = db.add_point(fn, 5)
        db.set_override(fn, p.id, '1y', low='4.99', high='5.01')
        self.assertEqual((fn.limit_for(p, '1y', ds).low, fn.limit_for(p, '1y', ds).source), (D('4.99'), 'override'))
        self.assertEqual(fn.limit_for(p, '90d', ds).source, 'spec')
        db.clear_override(fn, p.id, '1y')
        self.assertEqual(fn.limit_for(p, '1y', ds).source, 'spec')

    def test_specificity_range_beats_general_and_band_beats_none(self):
        ds = db.Datasheet('A', 'B', 'C')
        ds.set_periods([('1y', 'y')], '1y')
        fn = ds.add_function('ACV')
        fn.add_range(1, '0.00001')
        fn.add_range(10, '0.0001')
        ds.set_spec(fn, '1 % of reading')                                             # general
        ds.set_spec(fn, '2 % of reading', range_id='r10')                            # range specific
        ds.set_spec(fn, '3 % of reading', range_id='r10', f_lo='1000', f_hi='2000')  # range + band
        p1 = db.add_point(fn, '0.5', 'r1', 100)
        p2 = db.add_point(fn, '5', 'r10', 100)
        p3 = db.add_point(fn, '5', 'r10', 1500)
        self.assertEqual(fn.limit_for(p1, '1y', ds).plus, D('0.005'))
        self.assertEqual(fn.limit_for(p2, '1y', ds).plus, D('0.1'))
        self.assertEqual(fn.limit_for(p3, '1y', ds).plus, D('0.15'))

    def test_band_border_uses_the_tighter_and_flags_it(self):
        ds = db.Datasheet('A', 'B', 'C')
        ds.set_periods([('1y', 'y')], '1y')
        fn = ds.add_function('ACV')
        fn.add_range(10, '0.0001')
        ds.set_spec(fn, '1 % of reading', f_lo='10', f_hi='1000')
        ds.set_spec(fn, '2 % of reading', f_lo='1000', f_hi='2000')
        p = db.add_point(fn, 5, None, 1000)
        lim = fn.limit_for(p, '1y', ds)
        self.assertEqual(lim.plus, D('0.05'))
        self.assertTrue(lim.ambiguous)
        self.assertIn('spec_border', [x.code for x in db.validate(ds)])

    def test_no_spec_is_an_error_not_a_guess(self):
        ds, fn = self.sheet()
        fn.spec.clear()
        p = db.add_point(fn, 5)
        with self.assertRaises(db.DsError) as c:
            fn.limit_for(p, '1y', ds)
        self.assertEqual(c.exception.code, 'no_spec')

    def test_limit_rounding_policies(self):
        ds, fn = self.sheet()
        fn.ranges[0].resolution = D('0.001')
        p = db.add_point(fn, 5)
        exact = fn.limit_for(p, '1y', ds)
        self.assertEqual((exact.low, exact.high), (D('4.9965'), D('5.0035')))        # exact, like build_mm325.py
        ds.options['limit_rounding'] = 'outward'
        out = fn.limit_for(p, '1y', ds)
        self.assertEqual((out.low, out.high), (D('4.996'), D('5.004')))               # low down, high up: never tighter
        self.assertTrue(out.low <= exact.low and out.high >= exact.high)


class Calculator(unittest.TestCase):
    def fn(self):
        ds = db.Datasheet('A', 'B', 'C')
        fn = ds.add_function('DCV')
        for fs in (1, 10, 100):
            fn.add_range(fs, D(fs) / 100000)
        return ds, fn

    def test_percent_of_range_bipolar_and_zero(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('p', 'percent_of_range', {'percents': ['10', '100'], 'bipolar': True, 'zero': True}, range_ids=['r10']))
        rep = db.regenerate(fn)
        self.assertEqual([p.nominal for p in fn.points], [D(-10), D(-1), D(0), D(1), D(10)])
        self.assertEqual(len(rep.added), 5)
        self.assertEqual(fn.points[3].id, 'dcv.r10.+1')

    def test_zero_and_full(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('z', 'zero_and_full', {'bipolar': True}, range_ids=['r1']))
        db.regenerate(fn)
        self.assertEqual(sorted(p.nominal for p in fn.points), [D(-1), D(0), D(1)])

    def test_fixed_goes_to_the_smallest_range_and_reports_what_fits_nowhere(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('f', 'fixed', {'values': ['0.5 V', '5 V', '50 V', '500 V']}))
        rep = db.regenerate(fn)
        self.assertEqual([(p.range_id, p.nominal) for p in fn.points], [('r1', D('0.5')), ('r10', D(5)), ('r100', D(50))])
        self.assertEqual(rep.skipped, [('500', 'outside_ranges')])

    def test_linear_log_and_125(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('l', 'linear', {'start': '2', 'stop': '10', 'count': 5}, range_ids=['r10']))
        db.regenerate(fn)
        self.assertEqual([p.nominal for p in fn.points], [D(2), D(4), D(6), D(8), D(10)])
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('g', 'log', {'start': '1', 'stop': '100', 'per_decade': 1}))
        db.regenerate(fn)
        self.assertEqual([p.nominal for p in fn.points], [D(1), D(10), D(100)])
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('s', 'decade_125', {'start': '1', 'stop': '50'}))
        db.regenerate(fn)
        self.assertEqual([p.nominal for p in fn.points], [D(1), D(2), D(5), D(10), D(20), D(50)])

    def test_log_count_keeps_three_significant_digits(self):
        got = db._steps_log('1', '1000', count=4)
        self.assertEqual(got, [D(1), D(10), D(100), D(1000)])
        got = db._steps_log('1', '10', count=3)
        self.assertEqual(got, [D(1), D('3.16'), D(10)])

    def test_dedupe_sort_and_stable_ids(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('a', 'fixed', {'values': ['5', '1', '5', '5.0']}))
        fn.add_rule(db.PointRule('b', 'fixed', {'values': ['5 V']}))
        db.regenerate(fn)
        self.assertEqual([p.id for p in fn.points], ['dcv.r1.+1', 'dcv.r10.+5'])
        ids = [p.id for p in fn.points]
        db.regenerate(fn)
        self.assertEqual([p.id for p in fn.points], ids)                     # regenerating changes nothing

    def test_frequency_modes(self):
        ds = db.Datasheet('A', 'B', 'C')
        fn = ds.add_function('ACV')
        fn.add_range(10, '0.0001')
        ds.set_spec(fn, '1 % of reading', f_lo='10', f_hi='1000')
        ds.set_spec(fn, '2 % of reading', f_lo='1000', f_hi='100000')
        fn.add_rule(db.PointRule('e', 'percent_of_range', {'percents': ['50']}, frequencies={'mode': 'bands', 'at': 'edges'}))
        db.regenerate(fn)
        self.assertEqual([p.frequency for p in fn.points], [D(10), D(1000), D(100000)])
        fn.rules[0].frequencies = {'mode': 'bands', 'at': 'mid'}
        db.regenerate(fn)
        self.assertEqual(sorted(p.frequency for p in fn.points if p.origin.startswith('rule')), [D(100), D(10000)])
        fn.rules[0].frequencies = {'mode': 'log', 'start': '10', 'stop': '1000', 'per_decade': 1}
        db.regenerate(fn)
        self.assertEqual([p.frequency for p in fn.points], [D(10), D(100), D(1000)])
        fn.rules[0].frequencies = {'mode': 'list', 'values': ['1 kHz', '50 Hz']}
        db.regenerate(fn)
        self.assertEqual([p.frequency for p in fn.points], [D(50), D(1000)])

    def test_ac_function_needs_a_frequency_rule(self):
        ds = db.Datasheet('A', 'B', 'C')
        fn = ds.add_function('ACV')
        fn.add_range(10)
        fn.add_rule(db.PointRule('x', 'percent_of_range', {'percents': ['50']}))
        with self.assertRaises(db.DsError) as c:
            db.regenerate(fn)
        self.assertEqual(c.exception.code, 'rule_frequency')

    def test_frequency_sweep_with_amplitude(self):
        ds = db.Datasheet('A', 'B', 'C')
        fn = ds.add_function('SCOPE_BW')
        fn.add_range(10)
        fn.add_rule(db.PointRule('b', 'frequency_sweep', {'nominal': '0'}, frequencies={'mode': 'list', 'values': ['50 MHz', '100 MHz']}, amplitude='3 V'))
        db.regenerate(fn)
        self.assertEqual([(p.nominal, p.frequency, p.amplitude) for p in fn.points], [(D(0), D(50000000), D(3)), (D(0), D(100000000), D(3))])

    def test_user_edits_survive_regeneration_and_removed_rule_points_go(self):
        ds, fn = self.fn()
        fn.add_rule(db.PointRule('p', 'percent_of_range', {'percents': ['50', '100']}, range_ids=['r10']))
        db.regenerate(fn)
        manual = db.add_point(fn, '2.5', 'r10')
        edited = db.edit_point(fn, 'dcv.r10.+5', label='mid', nominal='5.1')           # the id never changes
        self.assertEqual(edited.id, 'dcv.r10.+5')
        self.assertEqual(edited.nominal, D('5.1'))
        fn.rules[0].params['percents'] = ['100']
        rep = db.regenerate(fn)
        ids = {p.id for p in fn.points}
        self.assertIn(manual.id, ids)
        self.assertIn('dcv.r10.+5', ids)                                              # edited -> kept (as a manual point)
        self.assertIn('dcv.r10.+5', rep.orphaned)
        self.assertEqual(fn.point('dcv.r10.+5').origin, 'user')
        fn.rules[0].params['percents'] = []
        rep = db.regenerate(fn)
        self.assertIn('dcv.r10.+10', rep.removed)                                     # untouched rule point dropped

    def test_hand_editing(self):
        ds, fn = self.fn()
        p = db.add_point(fn, '3 V')
        self.assertEqual((p.range_id, p.edited, p.origin), ('r10', True, 'user'))
        with self.assertRaises(db.DsError):
            db.add_point(fn, '3 V')                                                    # duplicate
        with self.assertRaises(db.DsError) as c:
            db.add_point(fn, 500)
        self.assertEqual(c.exception.code, 'no_range')
        with self.assertRaises(db.DsError):
            db.edit_point(fn, p.id, id='x')
        db.remove_point(fn, p.id)
        self.assertEqual(fn.points, [])
        with self.assertRaises(db.DsError):
            db.remove_point(fn, 'nope')


class Validation(unittest.TestCase):
    def codes(self, ds, level=None):
        return {p.code for p in db.validate(ds) if level in (None, p.level)}

    def test_good_fixtures_have_no_errors(self):
        for mk in (fx.dmm_34461a_like, fx.acv_bands_sheet, fx.generator_33220a_like, fx.scope_tds2000c_like):
            self.assertEqual(db.errors(db.validate(mk())), [], mk.__name__)

    def test_problems_carry_codes_levels_and_are_cmdreg_problems(self):
        import cmdreg
        ds = db.Datasheet()
        probs = db.validate(ds)
        self.assertTrue(all(isinstance(p, cmdreg.Problem) and p.code and p.level in ('error', 'warn') for p in probs))
        self.assertTrue({'no_make', 'no_model', 'no_functions'} <= {p.code for p in probs})

    def test_validate_never_changes_the_datasheet(self):
        ds = fx.dmm_34461a_like()
        ds.functions[0].ranges[0].resolution = D(-1)
        before = json.dumps(ds.to_dict(), sort_keys=True)
        db.validate(ds)
        self.assertEqual(json.dumps(ds.to_dict(), sort_keys=True), before)

    def test_structure_problems(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        fn.ranges[1].full_scale = D('0.05')                       # not ascending
        fn.ranges[2].resolution = D(0)
        fn.ranges[3].id = fn.ranges[4].id
        ds.default_period = 'nope'
        c = self.codes(ds, 'error')
        self.assertTrue({'range_order', 'range_resolution', 'dup_range', 'default_period'} <= c, c)

    def test_point_problems(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        fn.points[0].nominal = D(5000)                            # outside its range
        fn.points[1].id = fn.points[2].id                         # duplicate id
        a = ds.function('acv')
        a.points[0].frequency = None                              # AC without frequency
        c = self.codes(ds, 'error')
        self.assertTrue({'point_outside_range', 'dup_point_id', 'no_frequency'} <= c, c)

    def test_spec_problems(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        fn.spec[0].exprs.pop('90d')
        fn.spec[0].f_lo, fn.spec[0].f_hi = D(5), D(1)
        fn.spec.append(db.SpecEntry({'90d': db.parse_expr('1 %', 'V', 'reading'), '1y': db.parse_expr('1 %', 'V', 'reading')}, range_id='r999'))
        c = self.codes(ds, 'error')
        self.assertTrue({'spec_missing_period', 'spec_band_inverted', 'spec_range_unknown'} <= c, c)

    def test_expression_that_cannot_evaluate(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        fn.ranges[0].resolution = None                            # counts need a resolution
        fn.spec[0].exprs['1y'] = db.parse_expr('2 counts', 'V')
        self.assertIn('expr_eval', self.codes(ds, 'error'))

    def test_missing_function_data(self):
        ds = db.Datasheet('A', 'B', 'C')
        ds.add_function('DCV')
        c = self.codes(ds)
        self.assertTrue({'no_ranges', 'no_spec', 'no_points'} <= c, c)

    def test_direction_rules(self):
        ds = fx.generator_33220a_like()
        ds.function('gen_ampl').direction = 'measure'
        s = fx.scope_tds2000c_like()
        s.function('scope_gain').direction = 'source'
        self.assertIn('bad_direction', self.codes(ds, 'error'))
        self.assertIn('bad_direction', self.codes(s, 'error'))

    def test_inverted_and_override_problems(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        p = fn.points[0]
        p.overrides['1y'] = {'low': '5', 'high': '4'}
        c = self.codes(ds, 'error')
        self.assertTrue({'limit_inverted', 'override_inverted'} <= c, c)
        p.overrides = {'5y': {'low': '1', 'high': '2'}}
        self.assertIn('override_period', self.codes(ds, 'warn'))

    def test_unit_mismatch_in_a_spec_term(self):
        with self.assertRaises(db.ExprError):
            db.parse_expr('5 mA', 'V')

    def test_rule_errors_surface_as_problems(self):
        ds = fx.dmm_34461a_like()
        ds.function('dcv').rules[0].range_ids = ['r999']
        self.assertTrue(any(p.code.startswith('rule') for p in db.validate(ds)))

    def test_unknown_assignment_point_warns(self):
        ds = fx.dmm_34461a_like()
        ds.assignments['nope'] = '5522A'
        self.assertIn('assignment_unknown_point', self.codes(ds, 'warn'))


if __name__ == '__main__':
    unittest.main()
