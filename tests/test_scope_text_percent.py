import unittest

import uncertainty as U


class ScopeTextTests(unittest.TestCase):
    def test_ac_current_is_printed_in_percent(self):
        self.assertEqual(U.load().dmm_text('ACI', 20e-6, None, 8000), '0.39 % + 80 nA')

    def test_dc_volts_stays_per_unit(self):
        self.assertIn('µV/V', U.load().dmm_text('DCV', 1, None, None))

    def test_band_edge_belongs_to_the_lower_row(self):
        s = U.load()
        # (10 to 120) uA: 3 Hz to 5 kHz | (>5 to 10) kHz | (>10 to 30) kHz: 5 kHz is in the first row, not the worse one beside it
        self.assertLess(s.dmm('ACI', 10e-6, None, 5000), 0.0039 * 10e-6 + 80e-9)
        self.assertAlmostEqual(s.dmm('ACI', 10e-6, None, 5001), 0.0039 * 10e-6 + 80e-9, places=12)
        self.assertLess(s.dmm('ACI', 5, None, 5000), 0.05)


class ThermocoupleLines(unittest.TestCase):
    """Printed p. 13 of the scope (A2LA 1888.03 rev. 07/07/2026), degC."""
    EXPECT = {'B': [(700, .34), (900, .26), (1200, .23), (1700, .26)], 'C': [(100, .19), (400, .16), (800, .20), (1500, .35), (2000, .61)],
              'D': [(100, .19), (400, .16), (800, .20), (1500, .34), (2000, .61)], 'E': [(-250, .31), (-100, .12), (0, .10), (500, .13), (800, .16)], 'J': [(-150, .19), (-50, .11), (0, .10), (500, .12), (1000, .16)],
              'K': [(-150, .22), (-50, .11), (0, .10), (500, .16), (1200, .27)], 'L': [(-150, .24), (0, .16), (850, .10)],
              'N': [(-150, .26), (-50, .13), (0, .10), (300, .10), (1000, .16)], 'R': [(100, .40), (300, .23), (700, .21), (1500, .26)],
              'S': [(100, .33), (500, .24), (1200, .25), (1500, .32)], 'T': [(-200, .47), (-50, .16), (60, .11), (300, .10)], 'U': [(-100, .31), (300, .10)]}

    def test_every_band(self):
        s = U.load()
        for tc, rows in self.EXPECT.items():
            for t, v in rows:
                self.assertEqual(s.dmm('TEMP', t, tc=tc), v, (tc, t))

    def test_edges(self):
        s = U.load()
        self.assertEqual(s.dmm('TEMP', -25, tc='K'), 0.11)       # '(>-100 to -25)' keeps its upper edge
        self.assertEqual(s.dmm('TEMP', -25, tc='N'), 0.13)       # Type N prints no '>': closed bands, the larger CMC on the edge
        self.assertIsNone(s.dmm('TEMP', 1400, tc='K'))
        self.assertEqual(s.dmm_text('TEMP', 0, tc='K'), '0.10 °C')


class CapacitanceLines(unittest.TestCase):
    """Printed p. 11 of the scope: two groups of 'Capacitance - Generate' lines (5522A: 0.5 % + 0.01 nF ...; 5560A: 0.19 % + 3.6 pF ...)."""

    def test_each_calibrator_has_its_own_line(self):
        s = U.load()
        self.assertEqual(s.dmm_text('CAP', 5e-9, source='5522A'), '0.25 % + 0.3 nF')
        self.assertEqual(s.dmm_text('CAP', 5e-9, source='5560A'), '0.17 % + 11 pF')
        self.assertAlmostEqual(s.dmm('CAP', 5e-9, source='5560A'), 0.0017 * 5e-9 + 11e-12, places=15)
        self.assertAlmostEqual(s.dmm('CAP', 5e-9, source='5522A'), 0.0025 * 5e-9 + 0.3e-9, places=15)

    def test_unknown_calibrator_takes_the_larger(self):
        s = U.load()
        self.assertEqual(s.dmm('CAP', 5e-9), s.dmm('CAP', 5e-9, source='5522A'))
        self.assertEqual(s.dmm('CAP', 50e-6, source='5560A'), 0.0025 * 50e-6 + 49e-9)
        self.assertEqual(s.dmm('CAP', 50e-6, source='5522A'), 0.0045 * 50e-6 + 300e-9)


if __name__ == '__main__':
    unittest.main()
