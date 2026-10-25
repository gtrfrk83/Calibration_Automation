import unittest

import uncertainty as U


class ScopeTextTests(unittest.TestCase):
    def test_ac_current_is_printed_in_percent(self):
        self.assertEqual(U.load().dmm_text('ACI', 100e-6, None, 5000), '0.39 % + 80 nA')

    def test_dc_volts_stays_per_unit(self):
        self.assertIn('µV/V', U.load().dmm_text('DCV', 1, None, None))


if __name__ == '__main__':
    unittest.main()
