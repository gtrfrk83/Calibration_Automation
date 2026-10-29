"""Fluke 5560A standards accuracy sheet (specs/standards/fluke_5560a_standard.json, written by specs/build_5560a_standard_from_manual.py) from
Fluke 5560A Product Specifications, Dec 2022 Rev. 8, 6/26 (PDF page = printed page + 2).  The table below is a SECOND, hand-typed transcription of key
cells (read again from the rendered page images), independent of the builder's tables.  Run:  python -m unittest tests.test_standard_5560a"""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal as D

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_5560a_standard_from_manual as b  # noqa: E402
import specmanager as sm  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'fluke_5560a_standard.json')
MODEL = '5560A'

# (function, range label) -> (PDF page, {period: (relative term as printed, floor in base units)}); relative term in ppm for volts / ohms / current,
# in % for capacitance / inductance.  95 % column (divisor 2).
KEY = {
    ('Voltage, DC', '12V'): (4, {'1 yr': ('6.2 ppm', 10e-6), '90 day': ('5 ppm', 10e-6)}),
    ('Voltage, DC', '120mV'): (4, {'1 yr': ('9.3 ppm', 0.8e-6), '90 day': ('7.8 ppm', 0.8e-6)}),
    ('Resistance [4-wire]', '1.2 kOhm'): (14, {'1 yr': ('19 ppm', 2e-3), '90 day': ('17 ppm', 2e-3)}),
    ('Resistance [4-wire]', '1200 MOhm'): (14, {'1 yr': ('0.31 %', 100e3), '90 day': ('0.3 %', 100e3)}),
    ('Resistance [2-Wire]', '12 Ohm'): (14, {'1 yr': ('19 ppm', 2.25e-3)}),
    ('Resistance [2-Wire]', '1.2 kOhm'): (14, {'1 yr': ('19 ppm', 7e-3)}),
    ('Resistance [2-Wire]', '1200 MOhm'): (14, {'1 yr': ('0.31 %', 102e3)}),
    ('Capacitance', '1.2nF'): (15, {'1 yr': ('0.09 %', 4e-12), '90 day': ('0.09 %', 4e-12)}),
    ('Capacitance', '12nF'): (15, {'1 yr': ('0.09 %', 5e-12), '90 day': ('0.09 %', 5e-12)}),
    ('Capacitance', '120nF'): (15, {'1 yr': ('0.1 %', 30e-12), '90 day': ('0.09 %', 30e-12)}),
    ('Capacitance', '12 µF'): (15, {'1 yr': ('0.1 %', 3e-9), '90 day': ('0.09 %', 3e-9)}),
    ('Capacitance', '120 µF'): (15, {'1 yr': ('0.12 %', 25e-9), '90 day': ('0.1 %', 25e-9)}),
    ('Inductance', '1.2mH'): (16, {'1 yr': ('0.09 %', 1e-6), '90 day': ('0.09 %', 1e-6)}),
}


def rel_of(text):
    num, unit = text.split()
    return float(D(num) / (D(1000000) if unit == 'ppm' else D(100)))


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(MODEL, cls.db)
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.raw = fh.read()
        cls.data = json.loads(cls.raw)
        cls.rng = {(f['name'], r['label']): r for f in cls.data['functions'] for r in f['ranges']}

    def test_sheet_is_registered_and_clean(self):
        self.assertIsNotNone(self.s)
        self.assertEqual(len(self.s.rows), 286)                  # 256 + the square-wave amplitude (25) and DC offset (5) rows of build_square_wave_rows.py
        self.assertEqual(len(self.data['functions']), 39)
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        by = {}
        for r in self.s.rows:
            by[r['kind']] = by.get(r['kind'], 0) + 1
        self.assertEqual(by, {'TEMP': 124, 'ACV': 75, 'ACI': 36, 'OHM': 18, 'CAP': 9, 'DCI': 8, 'IND': 7, 'DCV': 5, 'FREQ': 4})

    def test_builder_reproduces_the_shipped_sheet_byte_for_byte(self):
        fresh = json.dumps(b.build(), indent=1, ensure_ascii=False) + '\n'
        self.assertEqual(fresh, self.raw)

    def test_header_is_the_document_and_nobody_approved_it(self):
        st = self.data['standard']
        self.assertEqual(st['reference'], 'Product Specifications Dec 2022 Rev. 8, 6/26')
        self.assertEqual(st['confidence_pct'], 95.0)
        for k in ('author', 'approved_by', 'approve_date'):
            self.assertEqual(st[k], '')                                   # no invented author or approval
        self.assertEqual(self.s.divisor()[0], 2.0)
        self.assertTrue(all(r.get('page') for r in self.rng.values()))     # a page on every row

    def test_periods_are_1_yr_first_and_90_day_only(self):
        self.assertEqual(b.PERIODS, ('1 yr', '90 day'))
        self.assertEqual(self.s.period, '1 yr')
        for r in self.s.rows:
            if r['function'] == 'Frequency':
                continue
            if 'Duty' in r['function']:
                continue
            self.assertEqual([x['period'] for x in r['specs']], ['1 yr', '90 day'], r['label'])
        text = json.dumps(self.data['functions'])
        self.assertNotIn('2 yr', text)
        self.assertNotIn('"2 y"', text)

    def test_second_transcription_of_key_cells(self):
        for (fn, label), (page, periods) in KEY.items():
            rng = self.rng[(fn, label)]
            self.assertEqual(rng['page'], page, (fn, label))
            for period, (rel, floor) in periods.items():
                sp = next(s for s in rng['specs'] if s['period'] == period)
                with self.subTest(fn=fn, label=label, period=period):
                    self.assertEqual(sp['rel'], rel_of(rel))
                    self.assertAlmostEqual(sp['abs'], floor, delta=floor * 1e-9)

    def test_capacitance_floors_were_a_thousand_times_too_small_before(self):
        # old sheet: 4e-15, 5e-15, 3e-14, 2.5e-11 F (git 794aeff); the document prints 4 pF, 5 pF, 30 pF, 25 nF (p.15)
        floors = [self.rng[('Capacitance', lab)]['specs'][0]['abs'] for lab in ('1.2nF', '12nF', '120nF', '120 µF')]
        for got, want in zip(floors, (4e-12, 5e-12, 3e-11, 2.5e-8)):
            self.assertAlmostEqual(got, want, delta=want * 1e-9)

    def test_lookups_at_the_points_the_procedures_use(self):
        self.assertAlmostEqual(self.s.lookup('DCV', 10.0).limit, 72e-6, 12)                                   # 6.2 ppm + 10 uV
        self.assertAlmostEqual(self.s.lookup('CAP', 5e-9).limit, 5e-9 * 9e-4 + 5e-12, 15)                     # 12 nF range
        self.assertAlmostEqual(self.s.lookup('CAP', 9e-5).limit, 9e-5 * 1.2e-3 + 25e-9, 12)                   # 120 uF range
        self.assertAlmostEqual(self.s.lookup('OHM', 1000.0).limit, 1000 * 19e-6 + 2e-3, 9)
        self.assertAlmostEqual(self.s.lookup('ACV', 1.0, frequency=10.0).limit, 1.0 * 680e-6 + 70e-6, 9)      # 1.2 V, 5-10 Hz: 70 uV (old sheet 75 uV)
        self.assertAlmostEqual(self.s.lookup('DCI', 0.010).limit, 7.8e-5 * 0.010 + 8e-8, 12)
        self.assertEqual(self.s.lookup('ACI', 20.0, frequency=60.0).row['label'][:5], '30.2A')

    def test_90_day_is_used_only_when_asked_for(self):
        for kind, v, kw in (('DCV', 10.0, {}), ('ACV', 1.0, {'frequency': 1000.0}), ('OHM', 1000.0, {}), ('CAP', 1e-5, {}), ('ACI', 12.0, {'frequency': 40.0})):
            default = self.s.lookup(kind, v, **kw)
            yr = self.s.lookup(kind, v, period='1 yr', **kw)
            d90 = self.s.lookup(kind, v, period='90 day', **kw)
            self.assertEqual(default.period, '1 yr')
            self.assertEqual(default.limit, yr.limit)
            self.assertLess(d90.limit, yr.limit + 1e-18)
        self.assertAlmostEqual(self.s.lookup('DCV', 10.0, period='90 day').limit, 60e-6, 12)
        self.assertIsNone(self.s.lookup('DCV', 10.0, period='2 yr'))
        # a budget and a TAR (no period argument anywhere) use the 1 yr figure
        bud = ub.build('DCV', 10.0, 'V', standard=self.s)
        self.assertEqual(bud.hit.period, '1 yr')
        self.assertAlmostEqual(bud.hit.limit, 72e-6, 12)

    def test_type_k_and_duty_rows(self):
        h = self.s.lookup_temperature(100.0)
        self.assertEqual(h.period, '1 yr')
        self.assertAlmostEqual(h.limit, 0.09, 6)
        duty = [r for r in self.s.rows if 'Duty' in r['function']]
        self.assertEqual([(r['amp_lo'], r['amp_hi'], r['specs'][0]['abs']) for r in duty], [(50.0, 50.0, 0.03), (10.0, 49.0, 0.06), (51.0, 90.0, 0.06)])
        self.assertEqual({r['direction'] for r in duty}, {'output'})


if __name__ == '__main__':
    unittest.main()
