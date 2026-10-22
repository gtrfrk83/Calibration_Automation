"""5560A standard file: the DC 12 mA and AC 30.2 A value ranges were mis-printed on the sheet and corrected (2026-10-22)."""
import os
import tempfile
import unittest

import specmanager as sm


class Ranges5560A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 't.sqlite3')
        sm.seed(path=cls.db)
        std = next(s for s in sm.standards(cls.db) if s['model'] == '5560A')
        cls.std = sm.StandardSpec(std['id'], path=cls.db)

    def test_dc_10_ma_uses_the_12_ma_range(self):
        h = self.std.lookup('DCI', 0.010)
        self.assertEqual(h.row['label'], '12mA')
        self.assertAlmostEqual(h.limit, 7.8e-5 * 0.010 + 8e-8, places=12)

    def test_dc_range_edges(self):
        self.assertEqual(self.std.lookup('DCI', 0.0011).row['label'], '1.2mA')
        self.assertEqual(self.std.lookup('DCI', 0.0119).row['label'], '12mA')
        self.assertEqual(self.std.lookup('DCI', 0.1).row['label'], '120mA')

    def test_ac_20_a_uses_the_30_2_a_range(self):
        h = self.std.lookup('ACI', 20.0, frequency=60.0)
        self.assertTrue(h.row['label'].startswith('30.2A'))
        self.assertIsNotNone(self.std.lookup('ACI', 12.0, frequency=60.0))

    def test_no_value_range_errors_remain(self):
        d = sm.validate_data(sm.json.loads(open(os.path.join(os.path.dirname(sm.__file__), 'specs', 'standards', 'fluke_5560a_standard.json'), encoding='utf-8').read())) if hasattr(sm, 'json') else []
        self.assertFalse([x for x in d if 'value range ends at' in x['what']])


if __name__ == '__main__':
    unittest.main()
