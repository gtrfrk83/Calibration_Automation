"""5700A standard sheet (specs/standards/fluke_5700a_standard.json, written by specs/build_5700a_standard.py from the 5700A Service Manual PN 791996
Rev. 9 3/96, Chapter 1, printed pp. 1-5 .. 1-14).

Spot checks of representative values worked by hand from the printed ppm / percent + floor terms, the lookup rules (non-overlapping bands, the 5725A amplifier and
wideband rows only on request, fixed resistance nominals), and a budget / TAR through the same code path the 5520A and 5522A use.

Run:  python -m unittest tests.test_standard_5700a
"""
import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import specmanager as sm
import tartur
import uncertainty
import uncertainty_budget as ub

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'fluke_5700a_standard.json')
UV, MV, NA, UA = 1e-6, 1e-3, 1e-9, 1e-6


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard('5700A', cls.db)
        cls.sc = uncertainty.load()
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)

    def lim(self, kind, value, **kw):
        h = self.s.lookup(kind, value, **kw)
        return None if h is None else h.limit

    # ---- registration / header
    def test_registered_and_found_by_name(self):
        self.assertIsNotNone(self.s)
        self.assertEqual(self.s.model, '5700A')
        self.assertEqual(sm.standard('Fluke 5700A calibrator', self.db).model, '5700A')
        self.assertIn('5700A', [x['model'] for x in sm.standards(self.db)])

    def test_no_confidence_level_is_printed(self):
        self.assertIsNone(self.s.info['confidence_pct'])                 # Chapter 1 prints no confidence level
        d, why = self.s.divisor()
        self.assertEqual(d, 2.0)
        self.assertIn('not specified', why)
        self.assertEqual(self.s.period, '1 yr')

    def test_no_sheet_errors(self):
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])

    def test_json_is_what_the_builder_writes(self):
        import build_5700a_standard as b
        self.assertEqual(b.build(), self.data)

    def test_periods_stored(self):
        for f in self.data['functions']:
            for r in f['ranges']:
                per = [s['period'] for s in r['specs']]
                where = (f['name'], r['label'])
                if f['name'].startswith('Frequency'):
                    self.assertEqual(per, ['1 yr'], where)
                elif f['name'].startswith('Voltage, AC [Wideband') and r['label'].startswith('3.5 V'):
                    self.assertEqual(per, ['90 day', '180 day', '1 yr'], where)      # the 24 hour cell is a printed misprint, not stored
                else:
                    self.assertEqual(per, ['24 hr', '90 day', '180 day', '1 yr'], where)

    def test_columns_never_shrink_from_24_hours_to_1_year_except_the_printed_misprint(self):
        odd = []
        for f in self.data['functions']:
            for r in f['ranges']:
                sp = [s for s in r['specs'] if s['period'] != '1 yr' or len(r['specs']) > 1]
                for a, b in zip(sp, sp[1:]):
                    if b['rel'] < a['rel'] - 1e-15 or b['abs'] < a['abs'] - 1e-15:
                        odd.append((f['name'], r['label']))
        self.assertEqual(sorted(odd), [('Voltage, AC [Sinewave]', '2.2 mV @ 500 kHz to 1 MHz'), ('Voltage, AC [Sinewave]', '22 mV @ 500 kHz to 1 MHz')])

    # ---- DC voltage (p. 1-5): ppm of output + uV
    def test_dc_voltage(self):
        self.assertAlmostEqual(self.lim('DCV', 0.1), 9e-6 * 0.1 + 0.8 * UV, 15)          # 220 mV range, 1 yr
        self.assertAlmostEqual(self.lim('DCV', 10.0), 8e-6 * 10 + 4 * UV, 12)            # 11 V range
        self.assertAlmostEqual(self.lim('DCV', 10.0, period='90 day'), 5e-6 * 10 + 4 * UV, 12)
        self.assertAlmostEqual(self.lim('DCV', 10.0, period='180 day'), 7e-6 * 10 + 4 * UV, 12)
        self.assertAlmostEqual(self.lim('DCV', 10.0, period='24 hr'), 3.5e-6 * 10 + 3 * UV, 12)
        self.assertAlmostEqual(self.lim('DCV', 100.0), 9e-6 * 100 + 100 * UV, 12)        # 220 V range
        self.assertAlmostEqual(self.lim('DCV', 1000.0), 11e-6 * 1000 + 600 * UV, 12)     # 1100 V range
        self.assertAlmostEqual(self.lim('DCV', -10.0), self.lim('DCV', 10.0), 15)       # negative points use the magnitude
        self.assertIsNone(self.lim('DCV', 1101.0))

    def test_dc_voltage_resolution_from_the_manual(self):
        self.assertEqual(self.s.resolution(self.s.lookup('DCV', 10.0)), (1e-6, "resolution column printed in the manufacturer's manual"))
        self.assertAlmostEqual(self.s.resolution(self.s.lookup('DCV', 0.1))[0], 10e-9, 18)

    # ---- AC voltage (p. 1-6)
    def test_ac_voltage(self):
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=1e3), 85e-6 * 1 + 7 * UV, 12)           # 2.2 V range, 40 Hz - 20 kHz
        self.assertAlmostEqual(self.lim('ACV', 100.0, frequency=1e3), 90e-6 * 100 + 1 * MV, 12)        # 220 V range, ppm + mV
        self.assertAlmostEqual(self.lim('ACV', 1000.0, frequency=500.0), 90e-6 * 1000 + 4 * MV, 12)    # 1100 V range, 50 Hz - 1 kHz
        self.assertAlmostEqual(self.lim('ACV', 3.0, frequency=1e6), 0.30 / 100 * 3 + 9 * MV, 12)       # 22 V range 500 kHz - 1 MHz, % + mV
        self.assertAlmostEqual(self.lim('ACV', 0.001, frequency=1e3), 120e-6 * 0.001 + 5 * UV, 15)     # 2.2 mV range
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=1e3, period='90 day'), 75e-6 + 7 * UV, 12)

    def test_ac_voltage_border_takes_the_larger_limit(self):
        self.assertAlmostEqual(self.lim('ACV', 1.0, frequency=20e3), 140e-6 * 1 + 20 * UV, 12)         # 20 kHz is in both 40-20k (85 + 7) and 20k-50k (140 + 20)

    def test_ac_voltage_needs_a_frequency(self):
        self.assertIsNone(self.lim('ACV', 1.0))                          # an AC row without a frequency band is never matched

    def test_5700a_alone_has_no_ac_above_220_v_outside_50_hz_to_1_khz(self):
        self.assertIsNone(self.lim('ACV', 1000.0, frequency=5e3))        # only the 5725A amplifier makes it

    # ---- 5725A amplifier and wideband option: only on request
    def test_5725a_rows_are_not_used_unless_asked(self):
        self.assertIsNone(self.lim('DCI', 5.0))                          # 11 A is the 5725A
        self.assertAlmostEqual(self.lim('DCI', 5.0, variant='5725A'), 360e-6 * 5 + 480 * UA, 12)
        self.assertAlmostEqual(self.lim('ACV', 1000.0, frequency=5e3, variant='5725A'), 165e-6 * 1000 + 6 * MV, 12)
        self.assertAlmostEqual(self.lim('ACV', 500.0, frequency=60e3, variant='5725A'), 0.23 / 100 * 500 + 45 * MV, 12)    # 750 V block, 50-100 kHz
        self.assertIsNone(self.lim('ACI', 5.0, frequency=1e3))
        self.assertAlmostEqual(self.lim('ACI', 5.0, frequency=1e3, variant='5725A'), 950e-6 * 5 + 380 * UA, 12)

    def test_wideband_rows_are_not_used_unless_asked(self):
        plain = self.s.lookup('ACV', 1.0, frequency=100e3)
        self.assertEqual(plain.row['function'], 'Voltage, AC [Sinewave]')
        wide = self.s.lookup('ACV', 1.0, frequency=100e3, variant='wideband')
        self.assertEqual(wide.row['function'], 'Voltage, AC [Wideband, Option 5700A-03]')
        self.assertAlmostEqual(wide.limit, 0.5 / 100 * 1.0 + 400 * UV, 12)                              # 1.1 V range, 1 yr: 0.5 % + 400 uV
        self.assertIsNone(self.lim('ACV', 1.0, frequency=1e6, variant='wideband'))                     # absolute uncertainty is specified 30 Hz - 500 kHz only

    # ---- DC current (p. 1-11): ppm + nA / uA
    def test_dc_current(self):
        self.assertAlmostEqual(self.lim('DCI', 1e-3), 60e-6 * 1e-3 + 10 * NA, 15)       # 2.2 mA range
        self.assertAlmostEqual(self.lim('DCI', 0.1), 70e-6 * 0.1 + 1 * UA, 12)          # 220 mA range
        self.assertAlmostEqual(self.lim('DCI', 1.0), 95e-6 * 1.0 + 30 * UA, 12)         # 2.2 A range
        self.assertIsNone(self.lim('DCI', 2.5))                                          # above the 5700A's own 2.2 A

    # ---- AC current (p. 1-12)
    def test_ac_current(self):
        self.assertAlmostEqual(self.lim('ACI', 1.0, frequency=500.0), 750e-6 * 1.0 + 40 * UA, 12)      # 2.2 A range, 20 Hz - 1 kHz
        self.assertAlmostEqual(self.lim('ACI', 1.0, frequency=1e3), 850e-6 * 1.0 + 100 * UA, 12)       # 1 kHz is the border with 1k-5k: the larger limit
        self.assertAlmostEqual(self.lim('ACI', 0.01, frequency=10e3), 0.18 / 100 * 0.01 + 10 * UA, 12)  # 22 mA range 5-10 kHz, % + uA
        self.assertAlmostEqual(self.lim('ACI', 0.001, frequency=60.0), 160e-6 * 0.001 + 40 * NA, 15)   # 2.2 mA range
        self.assertIsNone(self.lim('ACI', 1.0, frequency=15.0))                                          # the 2.2 A range starts at 20 Hz

    # ---- resistance (p. 1-9): fixed nominals, ppm of the characterized value
    def test_resistance(self):
        self.assertAlmostEqual(self.lim('OHM4', 10e3), 14e-6 * 10e3, 12)
        self.assertAlmostEqual(self.lim('OHM4', 10e3, period='90 day'), 11e-6 * 10e3, 12)
        self.assertAlmostEqual(self.lim('OHM2', 1.9e3), 15e-6 * 1.9e3, 12)
        self.assertAlmostEqual(self.lim('OHM4', 100e6), 130e-6 * 100e6, 6)
        self.assertAlmostEqual(self.lim('OHM4', 1.0), 110e-6 * 1.0, 12)
        self.assertAlmostEqual(self.lim('OHM4', 0.0), 50e-6, 12)                         # the short: 50 uohm floor
        self.assertIsNone(self.lim('OHM4', 5e3))                                         # not a nominal the 5700A can source
        self.assertIsNone(self.lim('OHM4', 10e3 * 1.0001))
        self.assertIsNone(self.s.resolution(self.s.lookup('OHM4', 1.9e3))[0])            # a nominal has no resolution (analyse_range would invent one from '1.9')

    def test_every_resistance_nominal_is_a_single_value(self):
        f = next(x for x in self.data['functions'] if x['name'] == 'Resistance')
        self.assertEqual(len(f['ranges']), 18)                                           # short + 17 nominals
        for r in f['ranges']:
            self.assertEqual(r['amp_lo'], r['amp_hi'], r['label'])

    # ---- frequency (p. 1-8): +/-0.01 %
    def test_frequency(self):
        self.assertAlmostEqual(self.lim('FREQ', 1000.0), 0.1, 12)
        self.assertAlmostEqual(self.lim('FREQ', 1e6), 100.0, 9)

    # ---- the uncertainty budget and TAR use the sheet like any other standard
    def test_budget_uses_divisor_2_and_manual_resolution(self):
        b = ub.build('DCV', 10.0, 'V', standard=self.s, scope=self.sc)
        self.assertIsNotNone(b)
        u_std = 84e-6 / 2.0
        u_res = 1e-6 / math.sqrt(12)
        self.assertAlmostEqual(b.emu, 2 * math.sqrt(u_std ** 2 + u_res ** 2), 12)
        self.assertEqual(b.hit.row['function'], 'Voltage, DC')

    def test_tar_through_tartur(self):
        p = dict(kind='DCV', nominal=10.0, unit='V', range=10.0)
        r = tartur.compute(p, 10 - 350e-6, 10 + 350e-6, self.s, self.sc)
        self.assertAlmostEqual(r['accuracy'], 84e-6, 12)
        self.assertAlmostEqual(r['tar'], 350 / 84, 6)                       # TAR has no divisor


if __name__ == '__main__':
    unittest.main()
