"""5520A standard sheet (specs/standards/fluke_5520a_standard.json, written by specs/build_5520a_standard.py from the 5520A Service Manual pp. 1-7 .. 1-23).

Spot checks of representative values, worked by hand from the printed ppm / percent + floor terms, and a few uncertainties / TAR / TUR through the same code path
the 5522A and 5560A use (specmanager lookup, uncertainty_budget.build, tartur.compute).

Run:  python -m unittest tests.test_standard_5520a
"""
import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'specs'))

import specmanager as sm
import tartur
import uncertainty
import uncertainty_budget as ub

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'fluke_5520a_standard.json')
UV, MV, UA = 1e-6, 1e-3, 1e-6


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard('5520A', cls.db)
        cls.a = sm.standard('5522A', cls.db)
        cls.sc = uncertainty.load()
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)

    def lim(self, kind, value, **kw):
        h = self.s.lookup(kind, value, **kw)
        return None if h is None else h.limit

    # ---- registration / header
    def test_registered_and_found_by_name(self):
        self.assertIsNotNone(self.s)
        self.assertEqual(self.s.model, '5520A')
        self.assertEqual(sm.standard('Fluke 5520A calibrator', self.db).model, '5520A')
        self.assertEqual(sm.standard('Fluke 5522A', self.db).model, '5522A')        # the 5520A does not capture the 5522A's name
        self.assertIn('5520A', [x['model'] for x in sm.standards(self.db)])

    def test_confidence_and_divisor(self):
        self.assertEqual(self.s.info['confidence_pct'], 99.0)            # printed p. 1-7: "Specification Confidence Interval 99 %"
        d, why = self.s.divisor()
        self.assertAlmostEqual(d, 2.576)
        self.assertIn('99', why)
        self.assertEqual(self.s.period, '1 yr')

    def test_no_sheet_errors(self):
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])

    def test_json_is_what_the_builder_writes(self):
        import build_5520a_standard as b
        fresh = b.build()
        for k in ('standard', 'notes', 'limits', 'functions', 'problems'):
            if k == 'standard':
                self.assertEqual({x: y for x, y in fresh[k].items() if x != 'built'}, {x: y for x, y in self.data[k].items() if x != 'built'})
            else:
                self.assertEqual(fresh[k], self.data[k], k)

    def test_both_periods_stored_except_frequency(self):
        for f in self.data['functions']:
            for r in f['ranges']:
                per = [s['period'] for s in r['specs']]
                self.assertEqual(per, ['1 yr'] if f['name'].startswith('Frequency') else ['90 day', '1 yr'], (f['name'], r['label']))

    # ---- DC voltage (p. 1-8): ppm of output + uV
    def test_dc_voltage(self):
        self.assertAlmostEqual(self.lim('DCV', 0.1), 20e-6 * 0.1 + 1 * UV, 12)           # 329.9999 mV range, 1 yr
        self.assertAlmostEqual(self.lim('DCV', 10.0), 12e-6 * 10 + 20 * UV, 12)         # 32.99999 V range
        self.assertAlmostEqual(self.lim('DCV', 10.0, period='90 day'), 10e-6 * 10 + 20 * UV, 12)
        self.assertAlmostEqual(self.lim('DCV', 200.0), 18e-6 * 200 + 150 * UV, 12)
        self.assertAlmostEqual(self.lim('DCV', 500.0), 18e-6 * 500 + 1500 * UV, 12)
        self.assertIsNone(self.lim('DCV', 1010.0))              # no printed row above 1000 V (flagged on the sheet)

    def test_aux_rows_are_not_used_unless_asked(self):
        self.assertAlmostEqual(self.lim('DCV', 5.0), 12e-6 * 5 + 20 * UV, 12)           # NORMAL 32.99999 V range, not the AUX 3.3 to 7 V row
        self.assertAlmostEqual(self.lim('DCV', 5.0, variant='auxiliary'), 400e-6 * 5 + 350 * UV, 12)
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=1e3, variant='auxiliary'), 0.2 / 100 * 1.0 + 1400 * UV, 12)   # AUX 1 kHz to 5 kHz (border takes the larger): 0.2 % + 1400 uV

    # ---- DC current (p. 1-9)
    def test_dc_current(self):
        self.assertAlmostEqual(self.lim('DCI', 100e-6), 150e-6 * 100e-6 + 0.02 * UA, 15)        # 329.999 uA range (printed 'mA', see sheet note 9)
        self.assertAlmostEqual(self.lim('DCI', 0.01), 100e-6 * 0.01 + 0.25 * UA, 12)
        self.assertAlmostEqual(self.lim('DCI', 20.0), 1000e-6 * 20 + 750 * UA, 12)

    # ---- resistance (p. 1-11): ppm + floor (12 hour zero), 7 day floor as a variant
    def test_resistance(self):
        self.assertAlmostEqual(self.lim('OHM', 100.0), 28e-6 * 100 + 0.0014, 12)
        self.assertAlmostEqual(self.lim('OHM', 100.0, period='90 day'), 22e-6 * 100 + 0.0014, 12)
        self.assertAlmostEqual(self.lim('OHM', 100.0, variant='7 day'), 28e-6 * 100 + 0.015, 12)
        self.assertAlmostEqual(self.lim('OHM', 10e6), 130e-6 * 10e6 + 50, 9)
        self.assertAlmostEqual(self.lim('OHM', 100e6), 500e-6 * 100e6 + 3000, 6)
        self.assertAlmostEqual(self.lim('OHM2', 1e3), 28e-6 * 1e3 + 0.002, 12)          # 330 ohm to 1.099999 kohm: floor 0.002

    # ---- AC voltage (p. 1-12): ppm + uV, bands by frequency, 1020 V range only to 10 kHz, nothing above 500 kHz
    def test_ac_voltage(self):
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=1e3), 150e-6 * 1 + 60 * UV, 12)
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=1e3, period='90 day'), 140e-6 * 1 + 60 * UV, 12)
        self.assertAlmostEqual(self.lim('ACV', 100.0, frequency=30e3), 300e-6 * 100 + 6000 * UV, 12)
        self.assertAlmostEqual(self.lim('ACV', 750.0, frequency=5e3), 300e-6 * 750 + 10000 * UV, 12)
        self.assertIsNone(self.lim('ACV', 750.0, frequency=20e3))        # 330 V to 1020 V only to 10 kHz
        self.assertIsNone(self.lim('ACV', 100.0, frequency=200e3))      # 33 V to 329.999 V stops at 100 kHz
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=500e3), 2400e-6 * 1 + 600 * UV, 12)
        self.assertIsNone(self.lim('ACV', 1.0, frequency=600e3))        # maximum specified frequency 500 kHz
        self.assertAlmostEqual(self.lim('ACV', 0.01, frequency=1e3), 150e-6 * 0.01 + 6 * UV, 12)

    # ---- AC current (pp. 1-14, 1-15): % of output + uA
    def test_ac_current(self):
        self.assertAlmostEqual(self.lim('ACI', 1.0, frequency=400), 0.05 / 100 * 1 + 100 * UA, 12)      # LCOMP off, 0.33 to 1.09999 A, 45 Hz to 1 kHz
        self.assertAlmostEqual(self.lim('ACI', 10.0, frequency=60), 0.06 / 100 * 10 + 2000 * UA, 12)
        self.assertAlmostEqual(self.lim('ACI', 1.0, frequency=400, variant='lcomp on'), 0.3 / 100 * 1 + 1000 * UA, 12)
        self.assertIsNone(self.lim('ACI', 0.01, frequency=40e3))        # 30 kHz maximum
        self.assertIsNone(self.lim('ACI', 1.0, frequency=20e3))         # 0.33 A to 2.99999 A stops at 10 kHz
        # 10 A at 40 Hz: LCOMP off starts at 45 Hz, so only the LCOMP-on row (10 Hz to 100 Hz, 0.12 % + 2000 uA) holds it
        self.assertAlmostEqual(self.lim('ACI', 10.0, frequency=40), 0.12 / 100 * 10 + 2000 * UA, 12)

    # ---- capacitance (p. 1-16)
    def test_capacitance(self):
        self.assertAlmostEqual(self.lim('CAP', 1e-6), 0.25 / 100 * 1e-6 + 1e-9, 15)
        self.assertAlmostEqual(self.lim('CAP', 100e-9), 0.25 / 100 * 100e-9 + 0.1e-9, 15)
        self.assertAlmostEqual(self.lim('CAP', 100e-9, period='90 day'), 0.19 / 100 * 100e-9 + 0.1e-9, 15)

    # ---- frequency (p. 1-23): 2.5 ppm + 5 uHz, 1 year only
    def test_frequency(self):
        self.assertAlmostEqual(self.lim('FREQ', 1000.0), 2.5e-6 * 1000 + 5e-6, 12)
        self.assertIsNone(self.s.lookup('FREQ', 1000.0, period='90 day'))
        self.assertIsNone(self.lim('FREQ', 3e6))

    # ---- thermocouple (p. 1-17) and RTD (p. 1-18)
    def test_temperature(self):
        for t, tc, one, ninety in ((100, 'K', 0.16, 0.12), (400, 'K', 0.26, 0.19), (-200, 'K', 0.33, 0.25), (1372, 'K', 0.40, 0.30), (700, 'B', 0.44, 0.42), (-30, 'J', 0.16, 0.12),
                                   (2000, 'C', 0.84, 0.63)):
            h = self.s.lookup_temperature(t, tc=tc)
            self.assertAlmostEqual(h.limit, one, 9, (tc, t))
            self.assertAlmostEqual(self.s.lookup_temperature(t, tc=tc, period='90 day').limit, ninety, 9, (tc, t))
        self.assertIsNone(self.s.lookup_temperature(1400, tc='K'))      # never extrapolates
        self.assertEqual(self.s.resolution(self.s.lookup_temperature(100))[0], 0.01)
        rtd = [r for r in self.s.rows if r['function'] == 'Temperature [RTD, Pt 385, 200 Ohm]' and r['amp_lo'] == 0.0]
        self.assertEqual(len(rtd), 1)
        self.assertEqual([x['abs'] for x in rtd[0]['specs']], [0.04, 0.04])
        self.assertEqual(rtd[0]['resolution'], 0.003)
        self.assertFalse([r for r in self.s.rows if r['function'] == 'Temperature [RTD, Pt 385, 100 Ohm]'])      # not in the 5520A table

    # ---- the same code path as the 5522A: budget, TAR, TUR
    def test_budget_uses_99_percent_divisor_and_manual_resolution(self):
        b = ub.build('DCV', 0.1, 'V', standard=self.s, scope=self.sc)
        u_std = 3e-6 / 2.576
        u_res = 1e-7 / math.sqrt(12)                      # manual resolution 0.1 uV on the 329.9999 mV range
        self.assertAlmostEqual(b.components[0].u, u_std, 15)
        self.assertAlmostEqual(b.components[1].u, u_res, 15)
        self.assertAlmostEqual(b.emu, 2 * math.sqrt(u_std ** 2 + u_res ** 2), 15)
        self.assertGreaterEqual(b.reported, b.emu)
        self.assertGreaterEqual(b.reported, b.cmc)
        self.assertIn('manual', b.components[1].source)

    def test_same_divisor_gives_the_5522a_budget(self):
        """The two sheets carry the same 1 yr numbers at 10 V DC and, since 2026-10-22, the same stored level (99 %, divisor 2.576: the 5522A manual p. 1-8 prints
        99 % too), so the budgets agree as stored.  (Before, the 5522A sheet had no level, divisor 2, and the 5520A budget was smaller.)"""
        b99 = ub.build('DCV', 10.0, 'V', standard=self.s, scope=self.sc)
        b52 = ub.build('DCV', 10.0, 'V', standard=self.a, scope=self.sc)
        self.assertAlmostEqual(b99.emu, b52.emu, 12)
        self.assertEqual(b99.reported, b52.reported)
        sm.set_standard_field(self.s.id, 'divisor', 2.0, who='test', reason='divisor 2 for the test', path=self.db)
        try:
            b2 = ub.build('DCV', 10.0, 'V', standard=sm.standard('5520A', self.db), scope=self.sc)
            self.assertGreater(b2.emu, b52.emu)                              # a divisor of 2 gives the larger budget
        finally:
            sm.set_standard_field(self.s.id, 'divisor', None, path=self.db)

    def test_tar_tur_through_tartur(self):
        p = dict(kind='DCV', nominal=10.0, unit='V', range=10.0)
        r = tartur.compute(p, 10 - 350e-6, 10 + 350e-6, self.s, self.sc)
        self.assertAlmostEqual(r['accuracy'], 140e-6, 12)
        self.assertAlmostEqual(r['tar'], 350 / 140, 6)                       # 2.5 : 1, no divisor
        b = ub.build('DCV', 10.0, 'V', standard=self.s, scope=self.sc, range_value=10.0)
        self.assertEqual(r['uncertainty'], b.reported)
        self.assertAlmostEqual(r['tur'], 350e-6 / b.reported, 9)
        pi = dict(kind='ACI', nominal=1.0, unit='A', range=1.0, frequency=400.0)
        ri = tartur.compute(pi, 1 - 0.01, 1 + 0.01, self.s, self.sc)
        self.assertAlmostEqual(ri['accuracy'], 0.0006, 12)
        self.assertAlmostEqual(ri['tar'], 0.01 / 0.0006, 6)

    def test_temperature_budget(self):
        b = ub.build('TEMP', 100.0, 'degC', standard=self.s, scope=self.sc)
        u_std = 0.16 / 2.576
        u_res = 0.01 / math.sqrt(12)
        self.assertAlmostEqual(b.emu, 2 * math.sqrt(u_std ** 2 + u_res ** 2), 12)
        self.assertEqual(b.hit.row['function'], 'Temperature [Thermocouple, Type K Output]')


if __name__ == '__main__':
    unittest.main()
