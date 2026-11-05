"""Tolerance expression terms added for the Datasheet Builder: 'of setting / output / nominal', 'of span', per-degC terms with a stated band, rss(...)."""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import datasheet_builder as db  # noqa: E402


def tol(text, reading=5, fs=10, span=20, ambient=None, unit='V'):
    e = db.parse_expr(text, unit=unit)
    return e, e.evaluate(db.Ctx(D(reading), D(fs), D('0.0001'), None, D(span), None if ambient is None else D(ambient)))


class Bases(unittest.TestCase):
    def test_setting_output_nominal_are_the_reading_basis(self):
        for word in ('setting', 'output', 'nominal', 'programmed value', 'set value'):
            _e, t = tol(f'0.5 % of {word} + 2 mV')
            self.assertEqual(t.plus, D('0.027'), word)

    def test_span_is_twice_full_scale_on_a_bipolar_range_and_full_scale_on_a_unipolar_one(self):
        _e, t = tol('0.1 % of span', span=20)
        self.assertEqual(t.plus, D('0.02'))
        _e, t = tol('100 ppm of span', span=10)
        self.assertEqual(t.plus, D('0.001'))

    def test_span_needs_a_range(self):
        e = db.parse_expr('0.1 % of span', unit='V')
        with self.assertRaises(db.ExprError):
            e.evaluate(db.Ctx(D(5)))


class TempCo(unittest.TestCase):
    def test_nothing_inside_the_band_and_the_excess_outside_it(self):
        _e, t = tol('0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC', ambient=23)
        self.assertEqual(t.plus, D('0.001'))
        _e, t = tol('0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC', ambient=35)     # 7 degC beyond: 0.001 + 0.0002 * 7
        self.assertEqual(t.plus, D('0.0024'))
        _e, t = tol('0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC', ambient=15)     # 3 degC below
        self.assertEqual(t.plus, D('0.0016'))

    def test_ppm_and_fixed_forms(self):
        _e, t = tol('2 ppm of range / degC outside 18 to 28 C', ambient=35)
        self.assertEqual(t.plus, D('0.00014'))
        _e, t = tol('5 uV per degC outside 18 to 28 degC', ambient=35)
        self.assertEqual(t.plus, D('0.000035'))

    def test_no_lab_temperature_means_no_contribution(self):
        _e, t = tol('2 ppm of range / degC outside 18 to 28 C')
        self.assertEqual(t.plus, D(0))

    def test_the_band_is_required_and_never_guessed(self):
        with self.assertRaises(db.ExprError) as cm:
            db.parse_expr('2 ppm/degC', unit='V', default_basis='reading')
        self.assertEqual(cm.exception.code, 'ambiguous_band')

    def test_round_trip_keeps_the_band(self):
        e = db.parse_expr('2 ppm/degC outside 18 to 28 degC', unit='V', default_basis='range')
        r = db.Expr.from_dict(e.to_dict())
        self.assertEqual(r.text('V'), e.text('V'))
        self.assertIn('18', r.text('V'))


class Rss(unittest.TestCase):
    def test_root_sum_square(self):
        _e, t = tol('rss(3 mV, 4 mV)')
        self.assertEqual(t.plus, D('0.005'))
        _e, t = tol('rss(0.3 % of reading, 1 mV)')
        self.assertAlmostEqual(float(t.plus), (0.015 ** 2 + 0.001 ** 2) ** 0.5, places=12)

    def test_round_trip(self):
        e = db.parse_expr('rss(3 mV, 4 mV)', unit='V')
        self.assertEqual(db.Expr.from_dict(e.to_dict()).evaluate(db.Ctx(D(1))).plus, D('0.005'))


if __name__ == '__main__':
    unittest.main()


class InADatasheet(unittest.TestCase):
    def _sheet(self, spec_text, ambient=None):
        ds = db.Datasheet(make='X', model='Y', title='t')
        fn = ds.add_function('DCV')
        fn.add_range('10', '0.0001')
        fn.add_spec({'1y': spec_text})
        p = db.add_point(fn, 5, range_id=fn.ranges[0].id)
        if ambient is not None:
            ds.options['ambient_c'] = str(ambient)
        return ds, fn, p

    def test_the_lab_temperature_option_reaches_the_limits(self):
        spec = '0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC'
        ds, fn, p = self._sheet(spec, ambient=35)
        self.assertEqual(fn.limit_for(p, '1y', ds).plus, D('0.0024'))
        ds, fn, p = self._sheet(spec, ambient=23)
        self.assertEqual(fn.limit_for(p, '1y', ds).plus, D('0.001'))

    def test_validate_warns_when_no_lab_temperature_is_set(self):
        ds, fn, p = self._sheet('0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC')
        codes = [x.code for x in db.validate(ds)]
        self.assertIn('tc_ambient', codes)
        ds, fn, p = self._sheet('0.02 % rdg + 0.002 % FS per degC outside 18 to 28 degC', ambient=23)
        self.assertNotIn('tc_ambient', [x.code for x in db.validate(ds)])

    def test_a_span_term_in_a_sheet(self):
        ds, fn, p = self._sheet('0.1 % of span')
        self.assertEqual(fn.limit_for(p, '1y', ds).plus, D('0.02'))        # bipolar 10 V range: span 20 V
