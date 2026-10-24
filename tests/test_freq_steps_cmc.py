"""Handheld frequency steps print the Frequency - Measure CMC alone (branch uncertainty-engines, part B).  Run:  python -m unittest tests.test_freq_steps_cmc

The 77 IV, 110-series, 87V and 287 / 289 steps that source AC volts and READ a frequency used to print the calibrator's VOLTAGE uncertainty with a Hz
unit ('2.9 mHz').  Owner: all frequency interfaces are tied to the GPS-referenced lab standard, so the lab's 'Frequency - Measure' CMC (7.1e-12 of
the frequency) is the uncertainty of those steps, on its own: never combined with a voltage / amplitude uncertainty, never the other way round.
The steps carry `unc_kind: 'FREQ'` (spec) and handheld_dmm.certificate_row / certificate_fields read it."""
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
import uncertainty  # noqa: E402

FIXED = {'fluke_77iv_pv.json': ['2-17'], 'fluke_110_series_pv.json': ['3-17'], 'fluke_87v_pv.json': ['1-11', '1-12', '1-13', '1-14'], 'fluke_287_289_pv.json': ['4-24'],
         'fluke_170_series_pv.json': ['2-16', '2-17', '2-18', '2-19', '2-25', '2-26', '3-16', '3-17', '3-18', '3-19', '3-25']}
LEFT_BLANK = set()                                 # no Hz-reading step with a source is left without the marker
CMC_REL = 7.1e-12                                  # Frequency - Measure, 10 Hz to 26.5 GHz (specs/a2la_1888_03_cmc.json)
EXPECTED = {('fluke_77iv_pv.json', '2-17'): ('360 nHz', 50000.0), ('fluke_110_series_pv.json', '3-17'): ('360 nHz', 50000.0),
            ('fluke_87v_pv.json', '1-11'): ('710 nHz', 99950.0), ('fluke_87v_pv.json', '1-12'): ('1.5 µHz', 199500.0),
            ('fluke_87v_pv.json', '1-13'): ('710 nHz', 99950.0), ('fluke_87v_pv.json', '1-14'): ('710 nHz', 99950.0),
            ('fluke_287_289_pv.json', '4-24'): ('320 pHz', 45.0)}
for _sid, _text, _f in (('2-16', '320 pHz', 45.0), ('2-17', '6.4 nHz', 900.0), ('2-18', '64 nHz', 9000.0), ('2-19', '360 nHz', 50000.0), ('2-25', '320 pHz', 45.0),
                        ('2-26', '360 nHz', 50000.0), ('3-16', '320 pHz', 45.0), ('3-17', '6.4 nHz', 900.0), ('3-18', '64 nHz', 9000.0), ('3-19', '360 nHz', 50000.0),
                        ('3-25', '320 pHz', 45.0)):
    EXPECTED[('fluke_170_series_pv.json', _sid)] = (_text, _f)       # 45 Hz 3.195e-10, 900 Hz 6.39e-9, 9 kHz 6.39e-8, 50 kHz 3.55e-7: rounded up to 2 s.f.      # 7.1e-12 x f, rounded UP to 2 s.f.: 3.55e-7 -> 3.6e-7, 7.096e-7 -> 7.1e-7, 1.416e-6 -> 1.5e-6, 3.195e-10 -> 3.2e-10


def steps(name):
    d = json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))
    return d.get('steps', [])


def step(name, sid):
    return next(s for s in steps(name) if s['id'] == sid)


class App:
    has_uncertainty = staticmethod(H.App.has_uncertainty)
    certificate_row = H.App.certificate_row
    certificate_fields = H.App.certificate_fields

    def __init__(self, model='5522A'):
        self.model = model

    def calibrator_model(self):
        return self.model


def row(s, model='5522A'):
    return App(model).certificate_row(s, dict(result='PASS', reading=s['nominal'], entered='x'))


class FrequencyRows(unittest.TestCase):
    def test_the_frequency_steps_carry_the_marker(self):
        for name, ids in FIXED.items():
            found = [s['id'] for s in steps(name) if s.get('base_unit') == 'Hz' and s['kind'] == 'ACV' and s.get('applied') and s.get('unc_kind') == 'FREQ']
            self.assertEqual(found, ids, name)
            for sid in ids:
                self.assertNotIn('no_uncertainty', step(name, sid))
                self.assertTrue(H.App.has_uncertainty(step(name, sid)))

    def test_printed_value_is_the_frequency_measure_cmc_alone(self):
        """Hand-worked: 7.1e-12 x f, rounded up to 2 s.f. and shown with its SI prefix (Hz)."""
        for (name, sid), (text, freq) in EXPECTED.items():
            s = step(name, sid)
            self.assertEqual(s['applied']['frequency'], freq)
            self.assertEqual(row(s)['Uncertainty'], text, (name, sid))
            self.assertEqual(text, uncertainty.format_value(CMC_REL * freq, 'Hz'))

    def test_tur_is_against_the_frequency_cmc_and_tar_is_blank(self):
        for (name, sid) in EXPECTED:
            f = App().certificate_fields(step(name, sid))
            self.assertEqual(f['TAR'], '', (name, sid))                           # no calibrator frequency accuracy is used: not well defined, left blank
            self.assertEqual(f['TUR'], '>1000:1', (name, sid))                    # tolerance of several mHz to Hz over a sub-microhertz CMC

    def test_nothing_else_changed(self):
        """Every Hz-reading step with a source carries the marker (the sourceless 4-25 / 1-15 rows have no source and no uncertainty)."""
        left = set()
        import glob
        for path in sorted(glob.glob(str(ROOT / 'specs' / '*_pv.json'))):
            name = Path(path).name
            for s in steps(name):
                if s.get('base_unit') == 'Hz' and s.get('applied') and s.get('unc_kind') != 'FREQ':
                    left.add(name)
                    self.assertTrue(s.get('no_uncertainty'), (name, s['id']))
        self.assertEqual(left, LEFT_BLANK)

    def test_builders_agree_with_the_json(self):
        spec = importlib.util.spec_from_file_location('build_77_spec', ROOT / 'specs' / 'build_77_spec.py')
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        self.assertEqual(json.loads(json.dumps(b.build_spec())), json.loads((ROOT / 'specs' / 'fluke_77iv_pv.json').read_text(encoding='utf-8')))
        src = (ROOT / 'specs' / 'build_87v_spec.py').read_text(encoding='utf-8')
        self.assertEqual(src.count("unc_kind='FREQ')"), 3)
        self.assertIn("'no_uncertainty', 'unc_kind'", src)


if __name__ == '__main__':
    unittest.main()
