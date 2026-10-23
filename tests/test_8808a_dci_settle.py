"""Fluke 8808A: longer settle for DC current at 10 A and on the 200 uA / 2000 uA ranges (bench: readings were taken too early).
The two values are engineering estimates, not manual figures. Other points keep their settle times. Simulated only."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402,F401  (installs the tkinter stub)
import fluke8808a_verification as E  # noqa: E402


def settle(p, overrides=None):
    stub = SimpleNamespace(pm_param=lambda key, default: (overrides or {}).get(key, default))
    return E.IO.settle(stub, p)


class DciSettle(unittest.TestCase):
    def pt(self, kind, rng, source='cal'):
        return {'kind': kind, 'range': rng, 'source': source, 'settle_s': None}

    def test_10a_and_low_ranges_wait_longer(self):
        self.assertEqual(settle(self.pt('DCI', 10.0)), E.DCI_10A_SETTLE_S)
        self.assertEqual(settle(self.pt('DCI', 200e-6)), E.DCI_LOW_SETTLE_S)
        self.assertEqual(settle(self.pt('DCI', 2000e-6)), E.DCI_LOW_SETTLE_S)
        self.assertGreater(E.DCI_10A_SETTLE_S, 2.0)
        self.assertGreater(E.DCI_LOW_SETTLE_S, 2.0)

    def test_other_points_unchanged(self):
        self.assertEqual(settle(self.pt('DCI', 20e-3)), 2.0)
        self.assertEqual(settle(self.pt('DCI', 2.0)), 2.0)
        self.assertEqual(settle(self.pt('DCV', 20.0)), 2.0)
        self.assertEqual(settle(self.pt('ACV', 20.0)), 4.0)
        self.assertEqual(settle(self.pt('DCI', 10.0, source='none')), 2.0)       # zero-offset (open input) points

    def test_tunable_and_per_point_override(self):
        self.assertEqual(settle(self.pt('DCI', 10.0), {'f8808a.settle.dci_10a': 12.0}), 12.0)
        self.assertEqual(settle(self.pt('DCI', 200e-6), {'f8808a.settle.dci_low': 9.0}), 9.0)
        p = self.pt('DCI', 10.0); p['settle_s'] = 3.5
        self.assertEqual(settle(p), 3.5)


if __name__ == '__main__':
    unittest.main()
