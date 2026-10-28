"""TDS / TBS time-base point (marker edge position in divisions): its uncertainty is the calibrator's Scope Out time-mark specification (5522A sheet, 2.5 ppm of the
edge time for 2 ns - 0.02 s), expressed in divisions of the measurement time base, no longer 'N/A' / 'Not in scope'."""
import json
import unittest
from pathlib import Path

import tbs2000b_verification as B
import tds2000c_verification as T

SPECS = Path(__file__).resolve().parent.parent / 'specs'


def point(name):
    return next(p for p in json.loads((SPECS / name).read_text(encoding='utf-8'))['points'] if p['kind'] == 'TIMEBASE')


class MarkerUncertainty(unittest.TestCase):
    def test_tds2000c(self):
        p = point('tektronix_tds2000c_pv.json')               # 10 ms marker, edge at 10 ms, 250 ns/div: 2.5 ppm x 10 ms = 25 ns = 0.1 div; budget (k = 2) 20 ns = 0.08 div
        self.assertEqual(T.uncertainty_text(p, {}), '0.08 div')
        self.assertEqual(T.tar_tur_fields(p, {'raw': {}}), {'TAR': '20.0:1', 'TUR': '25.0:1'})

    def test_tbs2000b(self):
        p = point('tektronix_tbs2000b_pv.json')               # 1 ms marker, 10 ns/div
        self.assertEqual(B.uncertainty_text(p, {}), '0.2 div')
        self.assertEqual(B.tar_tur_fields(p, {'raw': {}})['TAR'], '10.0:1')

    def test_tbs1000_family_points(self):
        for f in ('tektronix_tbs1000_pv.json', 'tektronix_tbs1000c_pv.json'):
            self.assertRegex(T.uncertainty_text(point(f), {}), r'^\d(\.\d+)? div$', f)

    def test_other_points_unchanged(self):
        pts = json.loads((SPECS / 'tektronix_tds2000c_pv.json').read_text(encoding='utf-8'))['points']
        for p in pts:
            if p['kind'] != 'TIMEBASE' and (p['stim'] == 'none' or p.get('passfail')):
                self.assertEqual(T.uncertainty_text(p, {}), 'N/A')


class FamilyReview(unittest.TestCase):
    """TBS1000 / TBS1000C apps subclass the TDS2000C App in their own module: the review window must still find the engine (it fell back to the plain popup)."""

    def test_engine_module_of_a_family_app(self):
        import report_review_adapters as A
        import tbs1000_verification as F

        class Probe(F.TBS1000App):
            pass
        for cls in (F.TBS1000App, F.TBS1000CApp, Probe):
            obj = object.__new__(cls)
            self.assertIs(A._mod(obj), T, cls.__name__)


if __name__ == '__main__':
    unittest.main()
