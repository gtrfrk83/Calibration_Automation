"""Keysight 3458A standards accuracy sheet (specs/standards/keysight_3458a_standard.json, written by specs/build_3458a_standard.py) from the
Keysight data sheet 5965-4971E (pp. 8-35).  The table below is a SECOND, hand-typed transcription of key cells (read again from the rendered page
images), independent of the builder's tables.  Run:  python -m unittest tests.test_standard_3458a"""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal as D

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_3458a_standard as b  # noqa: E402
import specmanager as sm  # noqa: E402
import specmanager_view as view  # noqa: E402
import tartur  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'keysight_3458a_standard.json')
MODEL = '3458A'

# (function name, range label) -> {period: (ppm_or_pct of reading as printed, unit '' ppm / '%', range term as printed)}
STD = 'Voltage, DC [Standard stability]'
OPT = 'Voltage, DC [Option 002 high stability]'
KEY = {
    (STD, '10 V range'): {'90 day': ('4.1', '0.05'), '1 yr': ('8', '0.05')},
    (STD, '100 mV range'): {'1 yr': ('9', '3')},
    (OPT, '10 V range'): {'90 day': ('2.6', '0.05'), '1 yr': ('4', '0.05')},
    (OPT, '100 mV range'): {'90 day': ('3.5', '3'), '1 yr': ('5', '3')},
    (OPT, '1000 V range'): {'1 yr': ('6', '0.1')},
    ('Resistance [4-wire (OHMF)]', '10 kohm range'): {'90 day': ('8', '0.5'), '1 yr': ('10', '0.5')},
    ('Current, DC', '1 mA range'): {'90 day': ('15', '5'), '1 yr': ('20', '5')},
    ('Current, DC', '100 mA range'): {'1 yr': ('35', '5')},
    ('Current, DC', '1 A range'): {'1 yr': ('110', '10')},
}
OHM2_OFFSET = {'90 day': '0.15', '1 yr': '0.25'}


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(MODEL, cls.db)
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)
        cls.rng = {(f['name'], r['label']): r for f in cls.data['functions'] for r in f['ranges']}

    def hit(self, kind, v, **kw):
        kw.setdefault('direction', 'input')
        return self.s.lookup(kind, v, **kw)

    def test_sheet_is_registered_and_clean(self):
        self.assertIsNotNone(self.s)
        self.assertIn(MODEL, [x['model'] for x in sm.standards(self.db)])
        self.assertEqual(sm.standard('Keysight 3458A', self.db).model, MODEL)
        self.assertEqual(len(self.s.rows), 228)
        self.assertEqual(len(self.data['functions']), 13)
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertEqual({r['direction'] for r in self.s.rows}, {'input'})
        by = {}
        for r in self.s.rows:
            by[r['kind']] = by.get(r['kind'], 0) + 1
        self.assertEqual(by, {'DCV': 15, 'OHM': 18, 'DCI': 8, 'ACV': 154, 'ACI': 31, 'FREQ': 2})

    def test_builder_reproduces_the_shipped_sheet(self):
        self.assertTrue(b.VERIFIED_AGAINST_IMAGE)
        fresh = b.build()
        for d in (fresh, self.data):
            d['standard'].pop('built', None)
        self.assertEqual(fresh, self.data)

    def test_second_transcription_of_key_cells(self):
        for (fn, label), periods in KEY.items():
            rng = self.rng[(fn, label)]
            for period, (rd, rg) in periods.items():
                sp = next(s for s in rng['specs'] if s['period'] == period)
                with self.subTest(fn=fn, label=label, period=period):
                    pct = '%' in sp['raw'].split('I.V.')[0]
                    self.assertEqual(sp['rel'], float(D(rd) / (D(100) if pct else D(1000000))))
                    self.assertEqual(sp['fs_rel'], float(D(rg) / D(1000000)))

    def test_ppm_of_range_is_exact_decimal_and_uses_the_range_name(self):
        sp = next(s for s in self.rng[(STD, '10 V range')]['specs'] if s['period'] == '1 yr')
        self.assertEqual((sp['rel'], sp['fs_rel'], sp['fs_value'], sp['abs']), (8e-06, 5e-08, 10.0, 0.0))
        self.assertEqual(sp['raw'], '[1 yr] Accuracy: +/-(8 ppm I.V. + 0.05 ppm of range{"Range" = 10 V})')
        p = sm.parse_spec(sp['raw'])
        self.assertEqual((p['rel'], p['fs_rel'], p['fs_value']), (8e-06, 5e-08, 10.0))
        h = self.hit('DCV', 10.0, variant='standard stability')
        self.assertAlmostEqual(h.limit, 80.5e-6, 12)                      # 8 ppm of 10 V + 0.05 ppm of the 10 V range
        # range is the range NAME, not full scale: 5 V reading on the 10 V range
        self.assertAlmostEqual(self.hit('DCV', 5.0, variant='standard stability').limit, 5 * 8e-6 + 10 * 0.05e-6, 12)
        self.assertAlmostEqual(self.hit('DCV', 1.0, variant='standard stability').limit, 8e-6 + 0.3e-6, 12)   # 1 V sits on the 1 V range

    def test_option_002_is_the_default_of_a_plain_lookup_standard_stability_is_the_alternate(self):
        # owner: the lab's 3458A has Option 002 (high stability)
        h = self.hit('DCV', 10.0)
        self.assertEqual(h.row['function'], OPT)
        self.assertAlmostEqual(h.limit, 10 * 4e-6 + 10 * 0.05e-6, 12)                 # 4 ppm + 0.05 ppm of range = 40.5 uV at 10 V, 1 yr
        self.assertAlmostEqual(self.hit('DCV', 10.0, variant='option 002').limit, 40.5e-6, 12)
        alt = self.hit('DCV', 10.0, variant='standard stability')
        self.assertEqual(alt.row['function'], STD)
        self.assertAlmostEqual(alt.limit, 80.5e-6, 12)
        self.assertEqual([f['name'] for f in self.data['functions']][:2], [OPT, STD])
        self.assertIn('Option 002', self.data['notes']['7'])
        self.assertIn('OWNER', self.data['notes']['7'])
        # only the DC volts table has Option 002 figures: resistance / current have a single set
        self.assertEqual(sorted({r['function'] for r in self.s.rows if 'option' in (r['variant'] + r['function']).lower()}), [OPT])

    def test_periods_are_90_day_and_1_yr_only(self):
        self.assertEqual(b.PERIODS, ['90 day', '1 yr'])
        self.assertEqual(self.s.period, '1 yr')
        self.assertAlmostEqual(self.hit('DCV', 10.0, period='90 day').limit, 10 * 2.6e-6 + 0.5e-6, 12)
        self.assertAlmostEqual(self.hit('DCV', 10.0, variant='standard stability', period='90 day').limit, 41.5e-6, 12)
        for per in ('24 hour', '2 yr'):
            self.assertIsNone(self.hit('DCV', 10.0, period=per))
        # the transfer table has its own period
        h = self.hit('DCV', 10.0, variant='transfer', period='10 min')
        self.assertAlmostEqual(h.limit, 10 * 0.05e-6 + 10 * 0.05e-6, 12)
        # AC and frequency print a single column: stored under both periods
        for r in self.s.rows:
            if r['kind'] in ('ACV', 'ACI', 'FREQ'):
                self.assertEqual([x['period'] for x in r['specs']], ['90 day', '1 yr'])
        used = {sp['period'] for r in self.s.rows for sp in r['specs']}
        self.assertEqual(used, {'90 day', '1 yr', '10 min'})
        text = json.dumps(self.data['functions'])
        self.assertNotIn('24 hour', text)
        self.assertNotIn('2 yr', text)

    def test_no_flag_about_an_unreadable_cell_and_1000_v_has_1_yr(self):
        self.assertEqual([s['period'] for s in self.rng[(OPT, '1000 V range')]['specs']], ['90 day', '1 yr'])
        self.assertAlmostEqual(self.hit('DCV', 1000.0).limit, 1000 * 6e-6 + 1000 * 0.1e-6, 9)
        self.assertFalse(any('2 year' in p['what'] or '2 yr' in p['what'] for p in self.data['problems']))
        self.assertTrue(any('OPEN ITEM' in p['what'] for p in self.data['problems']))         # factory adders: owner undecided

    def test_resistance_two_wire_offsets_and_four_wire(self):
        self.assertAlmostEqual(self.hit('OHM', 10e3).limit, 10e3 * 10e-6 + 10e3 * 0.5e-6, 9)         # 0.105 ohm
        for period, off in OHM2_OFFSET.items():
            for lab in ('10 ohm range', '1 Gohm range'):
                sp = next(s for s in self.rng[('Resistance [2-wire (OHM)]', lab)]['specs'] if s['period'] == period)
                self.assertEqual(sp['abs'], float(D(off)))
        self.assertAlmostEqual(self.hit('OHM', 10e3, variant='2-wire').limit, 0.105 + 0.25, 9)
        self.assertAlmostEqual(self.hit('OHM', 100e6).limit, 100e6 * 500e-6 + 100e6 * 10e-6, 3)

    def test_dc_current_ranges_for_the_8808a_characterisation(self):
        self.assertAlmostEqual(self.hit('DCI', 200e-6).limit, 200e-6 * 20e-6 + 1e-3 * 5e-6, 15)       # lands on the 1 mA range
        self.assertAlmostEqual(self.hit('DCI', 2e-3).limit, 2e-3 * 20e-6 + 10e-3 * 5e-6, 15)         # 10 mA range
        self.assertAlmostEqual(self.hit('DCI', 0.2).limit, 0.2 * 110e-6 + 1.0 * 10e-6, 12)           # 1 A range
        self.assertIsNone(self.hit('DCI', 2.0))                                                       # 2 A is beyond the 3458A (1.05 A)
        self.assertEqual(sum('typical' in r['label'] for r in self.rng_by_fn('Current, DC')), 3)

    def rng_by_fn(self, fn):
        return [r for (f, _), r in self.rng.items() if f == fn]

    def test_ac_modes_and_default_variant(self):
        h = self.hit('ACV', 1.0, frequency=1000.0)
        self.assertEqual(h.row['variant'], 'SETACV SYNC, ACBAND <= 2 MHz')                           # DEFAULT_VARIANT prefers the sine SYNC mode
        self.assertAlmostEqual(h.limit, 1.6e-4, 9)
        self.assertEqual(self.hit('ACV', 1.0, frequency=3e6).row['variant'], 'SETACV SYNC, ACBAND > 2 MHz')
        self.assertAlmostEqual(self.hit('ACV', 1.0, frequency=3e6).limit, 0.0407, 6)                  # 4 % of reading + 0.07 % of 1 V range
        self.assertAlmostEqual(self.hit('ACI', 0.5, frequency=1000.0).limit, 7e-4, 9)

    def test_frequency_is_percent_of_reading(self):
        self.assertAlmostEqual(self.hit('FREQ', 20.0).limit, 20 * 0.0005, 12)
        self.assertAlmostEqual(self.hit('FREQ', 1000.0).limit, 1000 * 0.0001, 12)

    def test_confidence_not_printed_so_k2_assumed(self):
        self.assertIsNone(self.s.info['confidence_pct'])
        d, why = self.s.divisor()
        self.assertEqual(d, 2.0)
        self.assertIn('not specified', why)
        self.assertIn('Not Specified', self.data['standard']['confidence_text'])

    def test_pages_are_recorded(self):
        pages = {r['page'] for r in self.rng.values()}
        self.assertEqual(pages, {12, 13, 16, 20, 24, 27, 29, 32, 34})

    def test_view_shows_range_term_and_scales_for_display_only(self):
        rows = sm.rows_of(next(x for x in sm.standards(self.db) if x['model'] == MODEL)['id'], path=self.db)
        dcv = next(r for r in rows if r['kind'] == 'DCV' and r['function'] == OPT and r['amp_hi'] == 12.0)
        text = view.spec_cell(dcv, '1 yr')[0]
        self.assertIn('of range', text)
        self.assertIn('4 ppm', text)
        self.assertEqual(dcv['specs'][1]['fs_value'], 10.0)                       # stored in base units
        self.assertGreater(len(view.group_rows(rows)), 0)

    def test_budget_and_tartur_see_the_sheet_as_input(self):
        lim, unit = tartur.standard_accuracy(MODEL, 'DCV', 10.0, direction='input')
        self.assertAlmostEqual(lim, 40.5e-6, 12)
        self.assertEqual(unit, 'V')
        bud = ub.build('DCV', 10.0, 'V', standard=self.s, scope=None, direction='input') if 'direction' in ub.build.__code__.co_varnames else None
        if bud is not None:
            self.assertAlmostEqual(bud.hit.limit, 40.5e-6, 12)
            self.assertAlmostEqual(bud.emu, 40.5e-6, 12)                         # k = 2 assumed gives back the expanded limit
        else:
            self.assertIsNone(ub.build('DCV', 10.0, 'V', standard=self.s, scope=None).hit)   # default direction is 'output': documented in NOTES.md

    def test_parse_spec_of_range_term_variants(self):
        p = sm.parse_spec('[1 yr] Accuracy: +/-(0.09 % I.V. + 0.06 % of range{"Range" = 10 mV})')
        self.assertEqual((p['rel'], p['fs_rel'], p['fs_value']), (0.0009, 0.0006, 0.01))
        p = sm.parse_spec('[1 yr] Accuracy: +/-(10 ppm I.V. + 0.5 ppm of range{"Range" = 10 kohm} + 0.25 ohm)')
        self.assertEqual((p['fs_value'], p['abs']), (10000.0, 0.25))


if __name__ == '__main__':
    unittest.main()
