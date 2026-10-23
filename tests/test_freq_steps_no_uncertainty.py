"""Handheld frequency steps print no uncertainty (branch uncertainty-engines, part B).  Run:  python -m unittest tests.test_freq_steps_no_uncertainty

The 77 IV, 110-series and 87V steps that source AC volts and READ a frequency used to print the calibrator's voltage uncertainty with a Hz unit
('2.9 mHz').  They now carry `no_uncertainty` (spec only): blank Uncertainty, TAR and TUR, like the 170 series."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import handheld_dmm as H  # noqa: E402
import tartur  # noqa: E402

FIXED = {'fluke_77iv_pv.json': ['2-17'], 'fluke_110_series_pv.json': ['3-17'], 'fluke_87v_pv.json': ['1-11', '1-12', '1-13', '1-14']}
KNOWN_UNFIXED = {('fluke_287_289_pv.json', '4-24')}          # same quirk, not in the request: listed so nobody finds it by accident


def steps(name):
    return json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))['steps']


class Fixed(unittest.TestCase):
    def test_the_frequency_steps_are_blank(self):
        for name, ids in FIXED.items():
            found = [s for s in steps(name) if s.get('base_unit') == 'Hz' and s['kind'] == 'ACV' and s.get('applied')]
            self.assertEqual([s['id'] for s in found], ids, name)
            for s in found:
                self.assertIs(s.get('no_uncertainty'), True, (name, s['id']))
                self.assertFalse(H.App.has_uncertainty(s), (name, s['id']))

    def test_the_report_row_and_ratios_are_blank(self):
        class App:
            has_uncertainty = staticmethod(H.App.has_uncertainty)

            def calibrator_model(self):
                return '5522A'

        s = next(x for x in steps('fluke_77iv_pv.json') if x['id'] == '2-17')
        row = H.App.certificate_row(App(), s, dict(result='PASS', reading=50000.0, entered='50.00'))
        self.assertEqual(row['Uncertainty'], '')
        control = next(x for x in steps('fluke_77iv_pv.json') if x['id'] == '2-9')            # AC 5 V 45 Hz: unchanged, still has one
        self.assertNotEqual(H.App.certificate_row(App(), control, dict(result='PASS', reading=5.0, entered='5.000'))['Uncertainty'], '')

    def test_no_other_step_lost_its_uncertainty(self):
        """Every step that still carries an uncertainty reads in the unit of its kind (the quirk), except the one documented exception."""
        bad = set()
        for name in sorted(p.name for p in (ROOT / 'specs').glob('*_pv.json')):
            if 'steps' not in json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8')):
                continue                                    # not a handheld step spec
            for s in steps(name):
                if 'base_unit' not in s or not H.App.has_uncertainty(s) or s.get('unc_unit'):
                    continue                                # unc_unit: the Fluke 376 iFlex steps word their uncertainty in volts on purpose
                natural = tartur.NATURAL_UNITS.get('OHM2' if s['kind'] == 'OHM' else s['kind'])
                if natural is not None and s['base_unit'] not in natural:
                    bad.add((name, s['id']))
        self.assertEqual(bad, KNOWN_UNFIXED)

    def test_builders_agree_with_the_json(self):
        spec = importlib.util.spec_from_file_location('build_77_spec', ROOT / 'specs' / 'build_77_spec.py')
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        self.assertEqual(json.loads(json.dumps(b.build_spec())), json.loads((ROOT / 'specs' / 'fluke_77iv_pv.json').read_text(encoding='utf-8')))
        src = (ROOT / 'specs' / 'build_87v_spec.py').read_text(encoding='utf-8')
        self.assertEqual(src.count('no_uncertainty=True)'), 4)          # rows 11-12, 13, 14 plus the conductance row that already had it (that call ends in '))')


if __name__ == '__main__':
    unittest.main()
