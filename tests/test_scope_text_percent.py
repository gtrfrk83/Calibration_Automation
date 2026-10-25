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


if __name__ == '__main__':
    unittest.main()
