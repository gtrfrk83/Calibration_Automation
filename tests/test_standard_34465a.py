"""Keysight 34465A standards accuracy sheet (specs/standards/keysight_34465a_standard.json, written by specs/build_34465a_standard.py) from the Keysight data sheet
5991-1983EN, 'Specifications 34465A' pp. 15-17.  KEY below is a SECOND, hand-typed transcription of key cells (read again from the rendered page images), independent
of the builder's tables.  Run:  python -m unittest tests.test_standard_34465a"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_34465a_standard as b  # noqa: E402
from truevolt_common import TruevoltChecks  # noqa: E402

R = 'Resistance [4-wire or 2W with math null]'
KEY = {
    ('Voltage, DC', '100 mV range'): {'90 day': ('0.0040', '0.0035'), '2 yr': ('0.0065', '0.0035')},
    ('Voltage, DC', '1 V range'): {'1 yr': ('0.0035', '0.0004')},
    ('Voltage, DC', '10 V range'): {'90 day': ('0.0020', '0.0004'), '1 yr': ('0.0030', '0.0004'), '2 yr': ('0.0045', '0.0004')},
    ('Voltage, DC', '1000 V range'): {'90 day': ('0.0035', '0.0006'), '1 yr': ('0.0040', '0.0006'), '2 yr': ('0.0055', '0.0006')},
    (R, '100 ohm range'): {'1 yr': ('0.0060', '0.0040')},
    (R, '1 Mohm range'): {'1 yr': ('0.0070', '0.0005')},
    (R, '100 Mohm range'): {'90 day': ('0.2000', '0.0010')},
    (R, '1 Gohm range'): {'1 yr': ('3.0000', '0.0010'), '2 yr': ('4.0000', '0.0010')},
    ('Current, DC', '1 uA range (typical)'): {'1 yr': ('0.0500', '0.0050')},
    ('Current, DC', '100 uA range (typical)'): {'1 yr': ('0.0500', '0.0010')},
    ('Current, DC', '1 A range'): {'90 day': ('0.0700', '0.0100'), '1 yr': ('0.0800', '0.0100'), '2 yr': ('0.1000', '0.0100')},
    ('Current, DC', '10 A range'): {'1 yr': ('0.1200', '0.0100'), '2 yr': ('0.1500', '0.0100')},
    ('Voltage, AC', '1 V range @ 5 Hz to 10 Hz'): {'1 yr': ('0.10', '0.02'), '2 yr': ('0.11', '0.02')},
    ('Voltage, AC', '10 V range @ 100 kHz to 300 kHz'): {'1 yr': ('1.00', '0.10')},
    ('Voltage, AC', '100 mV range @ 3 Hz to 5 Hz'): {'1 yr': ('0.50', '0.02')},
    ('Current, AC', '100 uA range @ 3 Hz to 5 kHz'): {'90 day': ('0.09', '0.04'), '1 yr': ('0.10', '0.04')},
    ('Current, AC', '1 A range @ 5 kHz to 10 kHz (typical)'): {'1 yr': ('0.10', '0.04')},
    ('Current, AC', '3 A range @ 3 Hz to 5 kHz'): {'1 yr': ('0.23', '0.04')},
    ('Capacitance', '1 nF range'): {'1 yr': ('0.50', '0.50')},
    ('Capacitance', '100 uF range'): {'1 yr': ('0.40', '0.10')},
    ('Frequency', '100 Hz to 1 kHz'): {'90 day': ('0.006', '0'), '1 yr': ('0.007', '0'), '2 yr': ('0.010', '0')},
    ('Frequency', '1 kHz to 300 kHz'): {'1 yr': ('0.007', '0'), '2 yr': ('0.009', '0')},
    ('Frequency [Square wave]', 'Square wave 10 Hz to 300 kHz'): {'90 day': ('0.004', '0'), '1 yr': ('0.006', '0'), '2 yr': ('0.008', '0')},
}


class Sheet(TruevoltChecks, unittest.TestCase):
    MODEL = '34465A'
    JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'keysight_34465a_standard.json')
    BUILDER = b
    KEY = KEY
    ROWS = 83
    KINDS = {'DCV': 5, 'OHM': 14, 'DCI': 9, 'ACV': 30, 'ACI': 14, 'CAP': 6, 'FREQ': 5}
    PAGES = {15, 16}
    DCV10_1YR = 10 * 3.0e-5 + 10 * 4e-6          # 0.0030 % of 10 V + 0.0004 % of the 10 V range = 340 uV
    DCV10_90D = 10 * 2.0e-5 + 10 * 4e-6          # 240 uV
    DCV10_2YR = 10 * 4.5e-5 + 10 * 4e-6          # 490 uV
    LOOKUPS = [
        ('DCV', 0.1, {}, 0.1 * 5e-5 + 0.1 * 3.5e-5, 12),
        ('OHM', 1000.0, {}, 1000 * 4e-5 + 1000 * 5e-6, 9),                                 # 1 kohm range 0.0040 % + 0.0005 %: 0.045 ohm
        ('OHM', 1e9, {}, 1e9 * 3e-2 + 1e9 * 1e-5, 0),                                      # 1 Gohm: 3.0000 % + 0.0010 %
        ('DCI', 0.2, {}, 0.2 * 8e-4 + 1.0 * 1e-4, 12),                                     # 1 A range 0.0800 % + 0.0100 %
        ('DCI', 1e-6, {}, 1e-6 * 5e-4 + 1e-6 * 5e-5, 15),                                  # lands on the 1 uA range (typical)
        ('ACV', 1.0, {'frequency': 1000.0}, 1.0 * 5e-4 + 1.0 * 2e-4, 12),                  # 10 Hz - 20 kHz: 0.05 % + 0.02 %
        ('ACV', 5.0, {'frequency': 150e3}, 5 * 0.01 + 10 * 0.001, 9),                      # 100 - 300 kHz, 10 V range: 1.00 % + 0.10 % of 10 V
        ('ACI', 1.0, {'frequency': 100.0}, 1.0 * 1e-3 + 1.0 * 4e-4, 12),
        ('CAP', 1e-7, {}, 1e-7 * 4e-3 + 1e-7 * 1e-3, 15),
        ('FREQ', 1000.0, {}, 1000 * 7e-5, 9),                                              # band edge: both bands print 0.007 %
        ('FREQ', 50.0, {}, 50 * 3e-4, 12),
    ]

    def test_extra_ranges_of_the_34465a(self):
        self.assertEqual(len([1 for (f, _) in self.rng if f == 'Current, DC']), 9)                        # 1 uA ... 10 A
        self.assertEqual(sum('typical' in l for (f, l) in self.rng if f == 'Current, DC'), 3)           # 1, 10, 100 uA
        self.assertEqual(self.hit('OHM', 5e8).row['label'], '1 Gohm range')
        self.assertIsNone(self.hit('OHM', 1.5e9))
        self.assertIsNone(self.hit('OHM', 5e8, variant='2-wire'))                                         # 100 Mohm / 1 Gohm are 2-wire only: no no-math-null rows
        self.assertEqual(self.hit('DCI', 8.0).row['label'], '10 A range')
        self.assertTrue(self.hit('ACI', 1.0, frequency=7e3).row['label'].endswith('(typical)'))
        self.assertEqual(sum('typical' in l for (f, l) in self.rng if f == 'Current, AC'), 7)
        self.assertIn('ACAL', self.data['notes']['4'])
        # the AC current 24 h / 90 day cells of the 100 uA - 1 A group are not the 1 year cells
        sp = {s['period']: s['rel'] for s in self.rng[('Current, AC', '1 A range @ 3 Hz to 5 kHz')]['specs']}
        self.assertLess(sp['90 day'], sp['1 yr'])


if __name__ == '__main__':
    unittest.main()
