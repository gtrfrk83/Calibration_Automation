"""Bench DMM frequency points print the Frequency - Measure CMC alone (branch uncertainty-engines).  Run:  python -m unittest tests.test_bench_freq_cmc

The 34410A / 34411A, Truevolt (34460A .. 34470A), 34970A / 34972A (DACQ) and 8808A procedures have FREQ points: an AC volts output of `amplitude` at the
test frequency (`nominal`, Hz) read by the DMM counter.  They used to print the calibrator's own frequency accuracy (a 5522A budget, e.g. 5.8 Hz at 50 kHz)
combined with the CMC.  Owner: every frequency is tied to the GPS-referenced lab standard, so the uncertainty is the A2LA 'Frequency - Measure' CMC
(7.1e-12 of the frequency, k = 2 already) ALONE: no calibrator accuracy term, no combining.  Done in report_pdf.point_uncertainty and tartur (no engine
file changes, so no verification fingerprint moves).  Hand-worked: 7.1e-12 x f, rounded UP to 2 s.f."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import procspec  # noqa: E402
import report_pdf  # noqa: E402
import tartur  # noqa: E402
import uncertainty  # noqa: E402

SPECS = ['keysight_34410a_pv.json', 'keysight_34460a_pv.json', 'keysight_34461a_pv.json', 'keysight_34465a_pv.json', 'keysight_34470a_pv.json',
         'keysight_34970a_pv.json', 'keysight_34972a_pv.json', 'fluke_8808a_pv.json']
STANDARDS = (None, '5522A', '5720A', '5730A', '5560A', '3458A')


def freq_points(name):
    spec = json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))
    out = [p for p in procspec.flatten(spec) if p['kind'] == 'FREQ']
    for p in out:
        p.setdefault('low', p['nominal'] - p.get('error', 1.0))
        p.setdefault('high', p['nominal'] + p.get('error', 1.0))
    return out


class BenchFrequency(unittest.TestCase):
    def test_every_engine_family_has_frequency_points(self):
        for name in SPECS:
            self.assertTrue(freq_points(name), name)

    def test_cmc_alone_whatever_the_calibrator(self):
        for name in SPECS:
            for p in freq_points(name):
                want = uncertainty.format_value(7.1e-12 * p['nominal'], 'Hz')
                for std in STANDARDS:
                    self.assertEqual(report_pdf.point_uncertainty(p, standard=std), want, (name, p['nominal'], std))

    def test_hand_values(self):
        p = dict(kind='FREQ', nominal=50000.0, unit='Hz', frequency=None, range=None)
        self.assertEqual(report_pdf.point_uncertainty(p, standard='5522A'), '360 nHz')          # 3.55e-7 Hz (was 5.8 Hz with the 5522A budget)
        p = dict(kind='FREQ', nominal=10.0, unit='Hz', frequency=None, range=None)
        self.assertEqual(report_pdf.point_uncertainty(p, standard='5522A'), '71 pHz')            # 7.1e-11 Hz

    def test_the_report_row_carries_it(self):
        p = freq_points('keysight_34410a_pv.json')[0]
        row = report_pdf.point_row(p, p['nominal'], False, standard='5522A')
        self.assertEqual(row['Uncertainty'], uncertainty.format_value(7.1e-12 * p['nominal'], 'Hz'))

    def test_tur_against_the_cmc_and_tar_blank(self):
        for name in SPECS:
            for p in freq_points(name):
                f = tartur.row_fields(p, p['low'], p['high'], standard='5522A')
                self.assertEqual(f['TAR'], '', (name, p['nominal']))            # no calibrator frequency accuracy is used
                self.assertNotEqual(f['TUR'], '', (name, p['nominal']))
                d = tartur.compute(p, p['low'], p['high'], standard='5522A')
                self.assertAlmostEqual(d['uncertainty'], uncertainty.round_up(7.1e-12 * p['nominal']), 18)

    def test_other_kinds_are_untouched(self):
        p = dict(kind='ACV', nominal=1.0, unit='V', frequency=1000.0, range=None)
        self.assertTrue(report_pdf.point_uncertainty(p, standard='5522A').endswith('V'))
        self.assertNotEqual(report_pdf.point_uncertainty(p, standard='5522A'), report_pdf.point_uncertainty(p))


if __name__ == '__main__':
    unittest.main()
