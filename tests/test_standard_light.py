"""Light standard sheet (specs/standards/a2la_light_standard.json, written by specs/build_light_standard.py): the laboratory's own A2LA CMC for light
measurement (scope 1888.03 rev. 07/07/2026, printed p. 45 of 47, section X. Optical Quantities) used as the uncertainty of the lab's radiometer standards.

Run:  python -m unittest tests.test_standard_light
"""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_light_standard as bl  # noqa: E402
import specmanager as sm  # noqa: E402
import specmanager_view as view  # noqa: E402
import tartur  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'a2la_light_standard.json')
MODEL = 'A2LA-LIGHT'
# kind -> (printed range text, upper limit, stored unit, CMC as printed in percent)
PRINTED = {'FC': ('(0 to 3000) FC', 3000.0, 'FC', '2.9'), 'LUX': ('(0 to 35 000) lux', 35000.0, 'lux', '2.9'),
           'LAMBERT': ('(0 to 100 000) La', 100000.0, 'La', '2.9'), 'UVIRR': ('(0 to 3000) µW/cm²', 3000.0, 'uW/cm2', '5.0')}


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(MODEL, cls.db)
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)

    def test_sheet_parses_and_has_four_rows(self):
        self.assertIsNotNone(self.s)
        self.assertEqual(len(self.s.rows), 4)
        self.assertEqual(sorted(r['kind'] for r in self.s.rows), sorted(PRINTED))
        self.assertEqual(len(self.data['functions']), 4)
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])

    def test_ranges_units_and_printed_text_as_on_the_scope(self):
        for r in self.s.rows:
            printed, hi, unit, pct = PRINTED[r['kind']]
            with self.subTest(kind=r['kind']):
                self.assertEqual((r['amp_lo'], r['amp_hi'], r['unit']), (0.0, hi, unit))        # stored as printed, nothing converted
                self.assertEqual(r['direction'], 'output')
                self.assertEqual(len(r['specs']), 1)
                self.assertEqual(r['specs'][0]['period'], '1 yr')
        printed = {rng['kind']: rng['printed'] for f in self.data['functions'] for rng in f['ranges']}
        self.assertEqual(printed, {k: v[0] for k, v in PRINTED.items()})
        self.assertEqual(self.data['functions'][3]['ranges'][0]['unit'], 'uW/cm2')              # ASCII-safe stored unit; the micro sign only in printed / view text

    def test_cmc_values_are_percent_of_reading_without_float_error(self):
        for r in self.s.rows:
            sp = r['specs'][0]
            printed = PRINTED[r['kind']][3]
            with self.subTest(kind=r['kind']):
                self.assertEqual(sp['rel'], float(Decimal(printed) / Decimal(100)))             # exact decimal conversion, not 2.9 * 0.01
                self.assertEqual((sp['abs'], sp['fs_rel'], sp['fs_value']), (0.0, 0.0, 0.0))    # percent of reading only (scope footnote 5)
                self.assertEqual(sp['raw'], f'[1 yr] Accuracy: +/-({printed} % I.V.)')
        self.assertEqual(self.s.rows[0]['specs'][0]['rel'], 0.029)
        self.assertNotEqual(2.9 * 1e-2, 0.029)           # what parse_spec alone would have stored (binary float), which the builder avoids

    def test_confidence_95_divisor_2_and_wording(self):
        self.assertEqual(self.s.info['confidence_pct'], 95.0)
        d, why = self.s.divisor()
        self.assertEqual(d, 2.0)
        self.assertIn('95', why)
        self.assertIn('approximately the 95 % level, usually k = 2', self.data['standard']['confidence_text'])
        self.assertIn('approximately the 95 % level', ' '.join(self.data['notes'].values()))
        self.assertIsNone(self.s.info['divisor'])
        self.assertEqual(self.s.period, '1 yr')

    def test_verification_status_is_recorded(self):
        self.assertTrue(bl.VERIFIED_AGAINST_IMAGE)
        self.assertIn('RENDERED PAGE IMAGE', self.data['notes']['2'])
        self.assertFalse([p for p in self.data['problems'] if 'UNVERIFIED' in p['what']])
        self.assertEqual(self.data['standard']['revision'], '07/07/2026')
        self.assertIn('1888.03', self.data['standard']['reference'])

    def test_listing_and_name_lookup(self):
        self.assertIn(MODEL, [x['model'] for x in sm.standards(self.db)])
        row = next(x for x in sm.standards(self.db) if x['model'] == MODEL)
        self.assertEqual(row['rows'], 4)
        self.assertEqual(row['description'], 'Light measurement (A2LA scope CMC, radiometer standards)')
        self.assertEqual(sm.standard('A2LA-LIGHT radiometer', self.db).model, MODEL)
        self.assertEqual(sm.standard('Fluke 5522A', self.db).model, '5522A')                   # the new model captures no other name

    def test_builder_reproduces_the_shipped_sheet(self):
        fresh = bl.build()
        for d in (fresh, self.data):
            d['standard'].pop('built')
        self.assertEqual(fresh, self.data)

    def test_classify_keeps_light_functions_apart(self):
        for name, kind in (('Light [White] (FC)', 'FC'), ('Light [White] (lux)', 'LUX'), ('Light [White] (La)', 'LAMBERT'),
                           ('Light [Black @ 365 nm] (uW/cm2)', 'UVIRR')):
            self.assertEqual(sm.classify(name)[0], kind)
        self.assertEqual(sm.classify('Voltage, DC')[0], 'DCV')

    def test_lookup_in_each_unit_is_its_own(self):
        h = self.s.lookup('LUX', 10000.0)
        self.assertAlmostEqual(h.limit, 290.0, 9)
        self.assertEqual(h.row['unit'], 'lux')
        self.assertAlmostEqual(self.s.lookup('FC', 1000.0).limit, 29.0, 9)
        self.assertAlmostEqual(self.s.lookup('LAMBERT', 50000.0).limit, 1450.0, 9)
        self.assertAlmostEqual(self.s.lookup('UVIRR', 1000.0).limit, 50.0, 9)
        self.assertIsNone(self.s.lookup('LUX', 35001.0))                                        # no extrapolation
        self.assertIsNone(self.s.lookup('DCV', 1.0))

    def test_budget_for_a_lux_point_is_the_cmc(self):
        b = ub.build('LUX', 10000.0, 'lux', standard=self.s, scope=None)
        self.assertAlmostEqual(b.hit.limit, 290.0, 9)
        self.assertAlmostEqual(b.components[0].u, 145.0, 9)                                      # CMC / 2
        self.assertAlmostEqual(b.emu, 290.0, 9)                                                  # k = 2 gives back the expanded CMC
        self.assertEqual(b.reported, 290.0)
        b = ub.build('UVIRR', 1000.0, 'uW/cm2', standard=self.s, scope=None)
        self.assertAlmostEqual(b.emu, 50.0, 9)

    def test_tartur_for_a_lux_point_uses_2_9_percent(self):
        r = tartur.compute({'kind': 'LUX', 'unit': 'lux', 'nominal': 10000.0}, 9000.0, 11000.0, standard=MODEL)
        self.assertAlmostEqual(r['tolerance'], 1000.0, 9)
        self.assertAlmostEqual(r['accuracy'], 290.0, 6)
        self.assertAlmostEqual(r['uncertainty'], 290.0, 6)
        self.assertAlmostEqual(r['tar'], 1000.0 / 290.0, 6)
        self.assertAlmostEqual(r['tur'], 1000.0 / 290.0, 6)
        self.assertEqual(tartur.format_ratio(r['tur']), '3.4:1')
        # tolerance in a different unit is never divided by a lux uncertainty
        self.assertIsNone(tartur.compute({'kind': 'LUX', 'unit': 'FC', 'nominal': 10000.0}, 9000.0, 11000.0, standard=MODEL)['tur'])
        # no standard given: the scope file has no light entry, so blank (nothing invented)
        self.assertIsNone(tartur.compute({'kind': 'LUX', 'unit': 'lux', 'nominal': 10000.0}, 9000.0, 11000.0)['tur'])
        lim, unit = tartur.standard_accuracy(MODEL, 'LUX', 10000.0)
        self.assertAlmostEqual(lim, 290.0, 9)
        self.assertEqual(unit, 'lux')

    def test_standards_specs_view_shows_the_sheet(self):
        row = next(x for x in sm.standards(self.db) if x['model'] == MODEL)
        rows = sm.rows_of(row['id'], path=self.db)
        chips = view.kind_chips(rows)
        self.assertEqual([c[0] for c in chips], ['', 'LUX', 'FC', 'LAMBERT', 'UVIRR'])
        self.assertEqual([c[3] for c in chips][1:], ['Illuminance (lux)', 'Illuminance (foot-candle)', 'Luminance (lambert)', 'UV irradiance (365 nm)'])
        by = {r['kind']: r for r in rows}
        # display only: no SI prefix is put on the light units; the micro sign / superscript appear only in the view text
        self.assertEqual(view.span_text(by['LUX']), '0 lux to 35000 lux')
        self.assertEqual(view.span_text(by['FC']), '0 FC to 3000 FC')
        self.assertEqual(view.span_text(by['LAMBERT']), '0 La to 100000 La')
        self.assertEqual(view.span_text(by['UVIRR']), '0 \u00b5W/cm\u00b2 to 3000 \u00b5W/cm\u00b2')
        self.assertEqual(view.spec_cell(by['LUX'], '1 yr')[0], '\u00b12.9 %')
        self.assertEqual(view.spec_cell(by['UVIRR'], '1 yr'), ('\u00b15 %', '[1 yr] Accuracy: +/-(5.0 % I.V.)'))      # the view drops the trailing zero, the printed text keeps it
        self.assertEqual(len(view.group_rows(rows)), 4)


if __name__ == '__main__':
    unittest.main()
