"""Shared checks of the Keysight 34461A / 34465A standards sheets (tests/test_standard_34461a.py, tests/test_standard_34465a.py).
A plain mixin (this module has no tests of its own): the model files set MODEL, JSON_PATH, BUILDER (module), KEY (second hand transcription), COUNTS, PAGES,
LOOKUPS and DEFAULT_ONE_YEAR; the checks below run for each model."""
import json
import math
import os
import sys
import tempfile
from decimal import Decimal as D

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import specmanager as sm  # noqa: E402
import tartur  # noqa: E402
import uncertainty_budget as ub  # noqa: E402


class TruevoltChecks:
    MODEL = ''
    JSON_PATH = ''
    BUILDER = None
    KEY = {}
    ROWS = 0
    KINDS = {}
    PAGES = set()
    LOOKUPS = []          # (kind, value, kwargs, expected 1 yr limit, places)
    DCV10_1YR = 0.0       # +/- limit at 10 V, 1 yr, as worked out by hand
    DCV10_90D = 0.0
    DCV10_2YR = 0.0

    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(cls.MODEL, cls.db)
        with open(cls.JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)
        cls.rng = {(f['name'], r['label']): r for f in cls.data['functions'] for r in f['ranges']}

    def hit(self, kind, v, **kw):
        kw.setdefault('direction', 'input')
        return self.s.lookup(kind, v, **kw)

    def test_sheet_is_registered_and_clean(self):
        self.assertIsNotNone(self.s)
        self.assertIn(self.MODEL, [x['model'] for x in sm.standards(self.db)])
        self.assertEqual(sm.standard('Keysight ' + self.MODEL, self.db).model, self.MODEL)
        self.assertEqual(len(self.s.rows), self.ROWS)
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertEqual({r['direction'] for r in self.s.rows}, {'input'})
        by = {}
        for r in self.s.rows:
            by[r['kind']] = by.get(r['kind'], 0) + 1
        self.assertEqual(by, self.KINDS)

    def test_builder_reproduces_the_shipped_sheet(self):
        self.assertTrue(self.BUILDER.VERIFIED_AGAINST_IMAGE)
        fresh = self.BUILDER.build()
        for d in (fresh, self.data):
            d['standard'].pop('built', None)
        self.assertEqual(fresh, self.data)

    def test_second_transcription_of_key_cells(self):
        for (fn, label), periods in self.KEY.items():
            rng = self.rng[(fn, label)]
            for period, (rd, rg) in periods.items():
                sp = next(s for s in rng['specs'] if s['period'] == period)
                with self.subTest(fn=fn, label=label, period=period):
                    self.assertEqual(sp['rel'], float(D(rd) / 100))
                    self.assertEqual(sp['fs_rel'], float(D(rg) / 100))

    def test_periods_are_90_day_1_yr_2_yr_and_the_default_is_1_yr(self):
        self.assertEqual(self.BUILDER.eng.PERIODS, ['90 day', '1 yr', '2 yr'])
        for r in self.s.rows:
            self.assertEqual([x['period'] for x in r['specs']], ['90 day', '1 yr', '2 yr'], r['label'])
        self.assertNotIn('24 hour', json.dumps(self.data['functions']))
        self.assertEqual(self.s.period, '1 yr')
        self.assertIn('DEFAULT PERIOD', self.data['notes']['5'])
        self.assertIn('1 yr', self.data['notes']['5'])

    def test_default_lookup_returns_the_1_yr_figure(self):
        """Owner: the uncertainty assignment uses the 1 year column, so the plain (default period) lookup must be the 1 yr figure for every kind."""
        for kind, v, kw, expect, places in self.LOOKUPS:
            with self.subTest(kind=kind, value=v):
                h = self.hit(kind, v, **kw)
                self.assertIsNotNone(h)
                self.assertEqual(h.period, '1 yr')
                self.assertAlmostEqual(h.limit, expect, places)
                self.assertEqual(h.limit, self.hit(kind, v, period='1 yr', **kw).limit)
        d10 = self.hit('DCV', 10.0)
        self.assertAlmostEqual(d10.limit, self.DCV10_1YR, 12)
        self.assertAlmostEqual(self.hit('DCV', 10.0, period='90 day').limit, self.DCV10_90D, 12)
        self.assertAlmostEqual(self.hit('DCV', 10.0, period='2 yr').limit, self.DCV10_2YR, 12)
        self.assertLess(self.DCV10_90D, self.DCV10_1YR)
        self.assertLess(self.DCV10_1YR, self.DCV10_2YR)
        # the callers of the uncertainty assignment
        lim, unit = tartur.standard_accuracy(self.MODEL, 'DCV', 10.0, direction='input')
        self.assertAlmostEqual(lim, self.DCV10_1YR, 12)
        self.assertEqual(unit, 'V')
        bud = ub.build('DCV', 10.0, 'V', standard=self.s, scope=None, direction='input')
        self.assertEqual(bud.hit.period, '1 yr')
        self.assertAlmostEqual(bud.hit.limit, self.DCV10_1YR, 12)
        self.assertIsNone(ub.build('DCV', 10.0, 'V', standard=self.s, scope=None).hit)       # default direction is 'output': the DMM measures

    def test_percent_of_range_uses_the_range_name_exact_decimal(self):
        sp = next(s for s in self.rng[('Voltage, DC', '10 V range')]['specs'] if s['period'] == '1 yr')
        self.assertEqual(sp['fs_value'], 10.0)
        self.assertTrue(sp['raw'].startswith('[1 yr] Accuracy: +/-('))
        self.assertIn('% I.V. +', sp['raw'])
        self.assertIn('% of range{"Range" = 10 V})', sp['raw'])
        p = sm.parse_spec(sp['raw'])
        self.assertTrue(math.isclose(p['rel'], sp['rel'], rel_tol=1e-12) and math.isclose(p['fs_rel'], sp['fs_rel'], rel_tol=1e-12))
        self.assertEqual(p['fs_value'], 10.0)
        # 5 V on the 10 V range: the range term is against the range name
        self.assertAlmostEqual(self.hit('DCV', 5.0).limit, 5 * sp['rel'] + 10 * sp['fs_rel'], 12)

    def test_confidence_is_k2_so_95_percent_divisor_2(self):
        self.assertEqual(self.s.info['confidence_pct'], 95.0)
        d, why = self.s.divisor()
        self.assertEqual(d, 2.0)
        self.assertIn('95', why)
        self.assertIn('k = 2', self.data['standard']['confidence_text'])
        self.assertIn('ISO/IEC 17025', self.data['standard']['confidence_text'])
        self.assertFalse(any('Confidence level is not specified' in p['what'] for p in self.data['problems']))
        self.assertTrue(any('k = 2' in p['what'] for p in self.data['problems']))        # the 95 % is an inference: flagged

    def test_resistance_two_wire_without_null_adds_0_2_ohm(self):
        four = self.hit('OHM', 1000.0)
        self.assertIn('4-wire', four.row['function'])
        self.assertNotIn('no math null', four.row['function'])
        two = self.hit('OHM', 1000.0, variant='2-wire')
        self.assertIn('no math null', two.row['function'])
        self.assertAlmostEqual(two.limit - four.limit, 0.2, 9)
        sp = next(s for s in self.rng[('Resistance [2-wire, no math null]', '1 kohm range')]['specs'] if s['period'] == '1 yr')
        self.assertEqual((sp['abs'], sp['unit']), (0.2, 'ohm'))

    def test_pages_are_recorded(self):
        self.assertEqual({r['page'] for r in self.rng.values()}, self.PAGES)

    def test_square_wave_is_a_separate_function(self):
        sq = self.hit('FREQ', 50e3, variant='square')
        self.assertEqual(sq.row['function'], 'Frequency [Square wave]')
        self.assertIsNone(self.hit('FREQ', 5.0, variant='square'))       # below 10 Hz

    def test_no_driver_or_automation_claim_in_the_notes(self):
        self.assertNotIn('driver', json.dumps(self.data['notes']).lower().replace('data sheet', ''))
