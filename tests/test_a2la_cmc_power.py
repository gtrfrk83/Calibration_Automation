"""The 'AC Power - Generate' line in the lab CMC table (specs/a2la_1888_03_cmc.json, added by specs/build_a2la_cmc_power.py): the builder only appends that entry,
is idempotent, and uncertainty.Scope returns the scope's CMC for AC power at (45 to 65) Hz.   Run:  python -m unittest tests.test_a2la_cmc_power"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_a2la_cmc_power as bp  # noqa: E402
import uncertainty  # noqa: E402

PATH = os.path.join(HERE, 'specs', 'a2la_1888_03_cmc.json')


def load():
    with open(PATH, encoding='utf-8') as fh:
        return json.load(fh)


class TestPowerLine(unittest.TestCase):
    def test_file_is_the_builder_output(self):
        data = load()
        with open(PATH, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), bp.dumps(bp.apply(copy.deepcopy(data))))

    def test_only_one_entry_is_added_and_others_are_kept(self):
        data = load()
        power = [e for e in data['entries'] if e['parameter'] == bp.PARAMETER]
        self.assertEqual(len(power), 1)
        self.assertEqual(power[0], bp.entry())
        before = copy.deepcopy(data)
        before['entries'] = [e for e in before['entries'] if e['parameter'] != bp.PARAMETER]
        self.assertEqual(bp.apply(copy.deepcopy(before)), data)

    def test_scope_cmc_at_60_hz(self):
        scope = uncertainty.Scope(load())
        for watts, cmc in ((200, 0.26), (400, 0.52), (600, 0.78), (800, 1.04), (1000, 1.30), (0.05, 0.05 * 0.0023), (50e3, 50.0)):
            self.assertAlmostEqual(scope.dmm('POWAC', watts, frequency=60.0), cmc, places=9)
        self.assertEqual(scope.dmm_text('POWAC', 600, frequency=60.0), '0.13 %')

    def test_band_edges_and_limits(self):
        scope = uncertainty.Scope(load())
        self.assertAlmostEqual(scope.dmm('POWAC', 0.1, frequency=60.0), 0.1 * 0.0023, places=12)    # overlap edge: the larger CMC
        self.assertAlmostEqual(scope.dmm('POWAC', 45, frequency=45.0), 45 * 0.0013, places=12)
        self.assertAlmostEqual(scope.dmm('POWAC', 45, frequency=65.0), 45 * 0.0013, places=12)
        for watts, freq in ((200, 400.0), (200, 44.9), (200, None), (0.005, 60.0), (130e3, 60.0)):
            self.assertIsNone(scope.dmm('POWAC', watts, frequency=freq))
        self.assertIsNone(scope.dmm('POWDC', 200))                                                  # no DC power line


if __name__ == '__main__':
    unittest.main()
