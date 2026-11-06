"""Keysight Truevolt (34460A / 61A / 65A / 70A) report: the Uncertainty / TAR / TUR of a point use the standard that applied it (2026-11-06).
Before, every row used the 5560A, so the two capacitance points (the technician's own capacitance standard) printed the 5560A capacitance figure.
Run:  python -m unittest tests.test_truevolt_report_standard"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import procspec  # noqa: E402
import report_pdf  # noqa: E402
import truevolt_verification as tv  # noqa: E402

MODELS = ('34460a', '34461a', '34465a', '34470a')


def points(model):
    return procspec.flatten(json.loads((ROOT / 'specs' / f'keysight_{model}_pv.json').read_text(encoding='utf-8')))


class StandardPerPoint(unittest.TestCase):
    def test_only_calibrator_points_use_the_5560a(self):
        for m in MODELS:
            for p in points(m):
                want = '5560A' if p['source'] == 'calibrator' else None
                self.assertEqual(tv.App.standard_for(p), want, (m, p['id']))

    def test_manual_capacitance_points_print_the_scope_cmc(self):
        for m in MODELS:
            caps = [p for p in points(m) if p['kind'] == 'CAP']
            self.assertEqual(len(caps), 2, m)
            for p in caps:
                self.assertEqual(p['source'], 'manual')
                self.assertEqual(report_pdf.point_uncertainty(p, tv.App.standard_for(p)), report_pdf.point_uncertainty(p, None))
                self.assertNotEqual(report_pdf.point_uncertainty(p, tv.App.standard_for(p)), report_pdf.point_uncertainty(p, '5560A'))

    def test_calibrator_points_are_unchanged(self):
        for m in MODELS:
            for p in points(m):
                if p['source'] == 'calibrator':
                    self.assertEqual(report_pdf.point_uncertainty(p, tv.App.standard_for(p)), report_pdf.point_uncertainty(p, '5560A'), (m, p['id']))


if __name__ == '__main__':
    unittest.main()
