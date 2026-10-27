"""Keysight 34461A standards accuracy sheet (specs/standards/keysight_34461a_standard.json, written by specs/build_34461a_standard.py) from the Keysight data sheet
5991-1983EN, 'Specifications 34461A' pp. 13-14.  KEY below is a SECOND, hand-typed transcription of key cells (read again from the rendered page images), independent
of the builder's tables.  Run:  python -m unittest tests.test_standard_34461a"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_34461a_standard as b  # noqa: E402
from truevolt_common import TruevoltChecks  # noqa: E402

R = 'Resistance [4-wire or 2W with math null]'
# (function name, range label) -> {period: (% of reading, % of range) as printed}
KEY = {
    ('Voltage, DC', '100 mV range'): {'90 day': ('0.0040', '0.0035'), '1 yr': ('0.0050', '0.0035'), '2 yr': ('0.0065', '0.0035')},
    ('Voltage, DC', '10 V range'): {'90 day': ('0.0020', '0.0005'), '1 yr': ('0.0035', '0.0005'), '2 yr': ('0.0050', '0.0005')},
    ('Voltage, DC', '1000 V range'): {'1 yr': ('0.0045', '0.0010'), '2 yr': ('0.0060', '0.0010')},
    (R, '100 ohm range'): {'1 yr': ('0.0100', '0.0040')},
    (R, '10 Mohm range'): {'1 yr': ('0.0400', '0.0010'), '2 yr': ('0.0600', '0.0010')},
    (R, '100 Mohm range'): {'90 day': ('0.8000', '0.0100'), '2 yr': ('0.8000', '0.0100')},
    ('Current, DC', '100 uA range'): {'1 yr': ('0.0500', '0.0250')},
    ('Current, DC', '3 A range'): {'1 yr': ('0.2000', '0.0200'), '2 yr': ('0.2300', '0.0200')},
    ('Current, DC', '10 A range'): {'90 day': ('0.1200', '0.0100'), '2 yr': ('0.1500', '0.0100')},
    ('Voltage, AC', '1 V range @ 10 Hz to 20 kHz'): {'90 day': ('0.05', '0.03'), '1 yr': ('0.06', '0.03'), '2 yr': ('0.07', '0.03')},
    ('Voltage, AC', '10 V range @ 100 kHz to 300 kHz'): {'1 yr': ('4.00', '0.50')},
    ('Voltage, AC', '750 V range @ 3 Hz to 5 Hz'): {'1 yr': ('1.00', '0.03')},
    ('Voltage, AC', '100 mV range @ 20 kHz to 50 kHz'): {'90 day': ('0.11', '0.05'), '2 yr': ('0.13', '0.05')},
    ('Current, AC', '1 A range @ 3 Hz to 5 kHz'): {'1 yr': ('0.10', '0.04')},
    ('Current, AC', '3 A range @ 3 Hz to 5 kHz'): {'1 yr': ('0.23', '0.04')},
    ('Current, AC', '10 A range @ 3 Hz to 5 kHz'): {'1 yr': ('0.15', '0.04')},
    ('Capacitance', '1 nF range'): {'1 yr': ('0.50', '0.50')},
    ('Capacitance', '10 uF range'): {'1 yr': ('0.40', '0.10')},
    ('Frequency', '100 Hz to 1 kHz'): {'90 day': ('0.008', '0'), '1 yr': ('0.010', '0')},
    ('Frequency', '1 kHz to 300 kHz'): {'90 day': ('0.006', '0'), '2 yr': ('0.010', '0')},
}


class Sheet(TruevoltChecks, unittest.TestCase):
    MODEL = '34461A'
    JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'keysight_34461a_standard.json')
    BUILDER = b
    KEY = KEY
    ROWS = 80
    KINDS = {'DCV': 5, 'OHM': 13, 'DCI': 7, 'ACV': 30, 'ACI': 14, 'CAP': 6, 'FREQ': 5}
    PAGES = {13, 14}
    DCV10_1YR = 10 * 3.5e-5 + 10 * 5e-6          # 0.0035 % of 10 V + 0.0005 % of the 10 V range = 400 uV
    DCV10_90D = 10 * 2.0e-5 + 10 * 5e-6          # 250 uV
    DCV10_2YR = 10 * 5.0e-5 + 10 * 5e-6          # 550 uV
    LOOKUPS = [
        ('DCV', 0.1, {}, 0.1 * 5e-5 + 0.1 * 3.5e-5, 12),                                   # 100 mV range: 0.0050 % + 0.0035 % of 0.1 V = 8.5 uV
        ('OHM', 1000.0, {}, 1000 * 1e-4 + 1000 * 1e-5, 9),                                 # 1 kohm range 0.0100 % + 0.0010 %: 0.11 ohm
        ('DCI', 0.2, {}, 0.2 * 1e-3 + 1.0 * 1e-4, 12),                                     # 1 A range 0.1000 % + 0.0100 % of 1 A
        ('ACV', 1.0, {'frequency': 1000.0}, 1.0 * 6e-4 + 1.0 * 3e-4, 12),                  # 10 Hz - 20 kHz: 0.06 % + 0.03 %
        ('ACV', 5.0, {'frequency': 150e3}, 5 * 0.04 + 10 * 0.005, 9),                      # 100 - 300 kHz on the 10 V range: 4.00 % + 0.50 % of 10 V
        ('ACI', 1.0, {'frequency': 100.0}, 1.0 * 1e-3 + 1.0 * 4e-4, 12),
        ('CAP', 1e-7, {}, 1e-7 * 4e-3 + 1e-7 * 1e-3, 15),                                  # 100 nF range 0.40 % + 0.10 %
        ('FREQ', 1000.0, {}, 1000 * 1e-4, 9),                                              # band edge: both bands print 0.010 %
        ('FREQ', 50.0, {}, 50 * 3e-4, 12),
    ]

    def test_extra_ranges_and_limits_of_the_34461a(self):
        self.assertIsNone(self.hit('DCV', 1100.0))                         # beyond 1000 V (no 20 % over range on this range)
        self.assertIsNone(self.hit('ACV', 1.0, frequency=400e3))           # above 300 kHz
        self.assertIsNone(self.hit('ACI', 1.0, frequency=20e3))            # above 10 kHz
        self.assertEqual(self.hit('DCV', 1.15).row['label'], '1 V range')  # 20 % over range: 1.15 V is still the 1 V range
        self.assertEqual(self.hit('DCI', 8.0).row['label'], '10 A range')
        self.assertTrue(self.hit('ACI', 1.0, frequency=7e3).row['label'].endswith('(typical)'))
        self.assertEqual(sum('typical' in r['label'] for (f, _), r in self.rng.items() if f == 'Current, AC'), 7)
        self.assertEqual(len([1 for (f, _) in self.rng if f == 'Current, DC']), 7)           # no uA ranges below 100 uA on the 34461A


if __name__ == '__main__':
    unittest.main()
