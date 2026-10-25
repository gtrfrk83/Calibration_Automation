"""Scope 'AC Voltage - Measure, AC Flatness - Relative to 1 kHz' (1888.03 pp. 22-28) and the 33220A RF flatness points measured on the 5790B
WIDEBAND input: rows of spot frequencies are bands, a gap takes the larger neighbour, the smallest range holding the level applies (owner 2026-10-25)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub
_tk_stub.install()
import fgen_verification as fg  # noqa: E402
import uncertainty  # noqa: E402


class ScopeLines(unittest.TestCase):
    def setUp(self):
        self.sc = uncertainty.load()

    def test_values_read_from_the_page_images(self):
        f = self.sc.ac_flatness
        self.assertAlmostEqual(f(0.335, 100e3), 0.00052)        # 0.7 V lines, 50 Hz .. 500 kHz row: 0.052 %
        self.assertAlmostEqual(f(0.335, 2e6), 0.00066)          # 700 kHz .. 2 MHz row
        self.assertAlmostEqual(f(1.0, 20e6), 0.0017)            # 2.2 V / 1 V and 2.2 V / 2 V, 20 MHz: 0.17 %
        self.assertAlmostEqual(f(0.002, 25e6), 0.0091)          # 2.2 mV / 1 mV, 23 .. 30 MHz row: 0.91 %
        self.assertAlmostEqual(f(0.005, 105), 0.00069)          # 7 mV / 3.2 mV, 105 Hz alone: 0.069 %

    def test_spot_rows_are_bands_and_gaps_take_the_larger_neighbour(self):
        f = self.sc.ac_flatness
        self.assertAlmostEqual(f(0.335, 5e6), 0.0011)           # inside '3, 4, 6, 8, 9, 10 MHz'
        self.assertAlmostEqual(f(0.335, 2.5e6), 0.0011)         # between 2 MHz (0.066 %) and 3 MHz (0.11 %): the larger
        self.assertAlmostEqual(f(1.0, 17.5e6), 0.0017)          # between 17 MHz (0.16 %) and 20 MHz (0.17 %)

    def test_outside_the_lines_is_not_in_scope(self):
        f = self.sc.ac_flatness
        self.assertIsNone(f(0.335, 60e6))
        self.assertIsNone(f(0.335, 5))
        self.assertIsNone(f(8.0, 1e6))


class GeneratorFlatness(unittest.TestCase):
    def points(self):
        fg.configure('33220A')                                  # the 33220A spec offers the WIDEBAND method
        return [p for p in fg.POINTS if p['kind'] == 'FLAT']

    def test_wideband_points_report_the_larger_of_scope_and_5790b_in_db(self):
        for p in self.points():
            fb = fg.flat_budget(p)
            self.assertIsNotNone(fb, p['desc'])
            value, src, cmc, emu = fb
            self.assertAlmostEqual(value, max(cmc, emu or 0))
            self.assertEqual(src, 'budget' if (emu or 0) > cmc else 'scope')
            level = fg.flat_level_v(p)
            self.assertAlmostEqual(cmc, 20 * math.log10(1 + uncertainty.load().ac_flatness(level, p['frequency'])))
            text, _src = fg.point_uncertainty(p, 'WBND')
            self.assertTrue(text.endswith(' dB'), text)

    def test_power_meter_method_stays_blank(self):
        for p in self.points():
            self.assertEqual(fg.point_uncertainty(p, 'POWER'), ('', ''))


if __name__ == '__main__':
    unittest.main()
