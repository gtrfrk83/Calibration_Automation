"""Handheld frequency steps: the OLD rule (Frequency - Measure CMC alone, reachable with handheld_dmm.FREQ_UNCERTAINTY_FROM_CALIBRATOR = False) and the
CURRENT default (owner decision 2026-10-26: the calibrator's own output-frequency specification) (branch uncertainty-engines, part B).  Run:  python -m unittest tests.test_freq_steps_cmc

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

FIXED = {'fluke_77iv_pv.json': ['2-17'], 'fluke_110_series_pv.json': ['3-17'], 'fluke_80_series_v_pv.json': ['3-11', '3-12', '3-13', '3-14', '3-15'], 'fluke_287_289_pv.json': ['4-24'],
         'fluke_170_series_pv.json': ['2-16', '2-17', '2-18', '2-19', '2-25', '2-26', '3-16', '3-17', '3-18', '3-19', '3-25']}
LEFT_BLANK = set()                                 # no Hz-reading step with a source is left without the marker
CMC_REL = 7.1e-12                                  # Frequency - Measure, 10 Hz to 26.5 GHz (specs/a2la_1888_03_cmc.json)
EXPECTED = {('fluke_77iv_pv.json', '2-17'): ('360 nHz', 50000.0), ('fluke_110_series_pv.json', '3-17'): ('360 nHz', 50000.0),
            ('fluke_80_series_v_pv.json', '3-11'): ('710 nHz', 99950.0), ('fluke_80_series_v_pv.json', '3-12'): ('1.5 µHz', 199500.0),
            ('fluke_80_series_v_pv.json', '3-13'): ('710 nHz', 99950.0), ('fluke_80_series_v_pv.json', '3-14'): ('710 nHz', 99950.0),
            ('fluke_287_289_pv.json', '4-24'): ('320 pHz', 45.0)}
for _sid, _text, _f in (('2-16', '320 pHz', 45.0), ('2-17', '6.4 nHz', 900.0), ('2-18', '64 nHz', 9000.0), ('2-19', '360 nHz', 50000.0), ('2-25', '320 pHz', 45.0),
                        ('2-26', '360 nHz', 50000.0), ('3-16', '320 pHz', 45.0), ('3-17', '6.4 nHz', 900.0), ('3-18', '64 nHz', 9000.0), ('3-19', '360 nHz', 50000.0),
                        ('3-25', '320 pHz', 45.0)):
    EXPECTED[('fluke_170_series_pv.json', _sid)] = (_text, _f)       # 45 Hz 3.195e-10, 900 Hz 6.39e-9, 9 kHz 6.39e-8, 50 kHz 3.55e-7: rounded up to 2 s.f.      # 7.1e-12 x f, rounded UP to 2 s.f.: 3.55e-7 -> 3.6e-7, 7.096e-7 -> 7.1e-7, 1.416e-6 -> 1.5e-6, 3.195e-10 -> 3.2e-10


NEW = {('fluke_77iv_pv.json', '2-17'): ('5.8 Hz', '130 mHz'), ('fluke_110_series_pv.json', '3-17'): ('5.8 Hz', '130 mHz'),
       ('fluke_80_series_v_pv.json', '3-11'): ('5.8 Hz', '250 mHz'), ('fluke_80_series_v_pv.json', '3-12'): ('58 Hz', '500 mHz'),
       ('fluke_80_series_v_pv.json', '3-13'): ('5.8 Hz', '250 mHz'), ('fluke_80_series_v_pv.json', '3-14'): ('5.8 Hz', '250 mHz'),
       ('fluke_287_289_pv.json', '4-24'): ('5.8 mHz', '120 µHz')}
for _sid, _a, _b in (('2-16', '5.8 mHz', '120 µHz'), ('2-17', '58 mHz', '2.3 mHz'), ('2-18', '580 mHz', '23 mHz'), ('2-19', '5.8 Hz', '130 mHz'), ('2-25', '5.8 mHz', '120 µHz'),
                     ('2-26', '5.8 Hz', '130 mHz'), ('3-16', '5.8 mHz', '120 µHz'), ('3-17', '58 mHz', '2.3 mHz'), ('3-18', '580 mHz', '23 mHz'), ('3-19', '5.8 Hz', '130 mHz'),
                     ('3-25', '5.8 mHz', '120 µHz')):
    NEW[('fluke_170_series_pv.json', _sid)] = (_a, _b)          # (5522A / 5520A, 5560A)


class OldRule:
    """Run a test with the switch off (the lab Frequency - Measure CMC alone)."""
    def setUp(self):
        self._sw = H.FREQ_UNCERTAINTY_FROM_CALIBRATOR
        H.FREQ_UNCERTAINTY_FROM_CALIBRATOR = False

    def tearDown(self):
        H.FREQ_UNCERTAINTY_FROM_CALIBRATOR = self._sw


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


class FrequencyRows(OldRule, unittest.TestCase):
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

    def test_the_old_rule_is_reached_by_the_one_switch(self):
        self.assertFalse(H.FREQ_UNCERTAINTY_FROM_CALIBRATOR)
        self.assertEqual(row(step('fluke_323_pv.json', '4-28'))['Uncertainty'], '360 pHz')
        self.assertEqual(row(step('fluke_323_pv.json', '4-27'))['Uncertainty'], '')      # 5 Hz: below the CMC's 10 Hz start, no uncertainty

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
        spec = importlib.util.spec_from_file_location('build_80v_spec', ROOT / 'specs' / 'build_80v_spec.py')
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        self.assertEqual(json.loads(json.dumps(b.build_spec(), ensure_ascii=False)), json.loads((ROOT / 'specs' / 'fluke_80_series_v_pv.json').read_text(encoding='utf-8')))


class CalibratorFrequencyRule(unittest.TestCase):
    """Owner decision 2026-10-26 (default): every handheld FREQ point takes the calibrator's own output-frequency specification."""
    def test_default_is_on(self):
        self.assertTrue(H.FREQ_UNCERTAINTY_FROM_CALIBRATOR)

    def test_printed_values_and_ratios(self):
        for (name, sid), (t5522, t5560) in NEW.items():
            s = step(name, sid)
            for model, text in (('5522A', t5522), ('5520A', t5522), ('5560A', t5560)):
                self.assertEqual(row(s, model)['Uncertainty'], text, (name, sid, model))
                f = App(model).certificate_fields(s)
                self.assertTrue(f['TUR'] and f['TAR'], (name, sid, model, f))

    def test_323_family_including_the_5_hz_point(self):
        want = {'4-27': ('5.8 mHz', '13 µHz'), '4-28': ('5.8 mHz', '130 µHz'), '4-29': ('58 mHz', '1.3 mHz')}      # 5 / 50 / 500 Hz
        for sid, (a, b) in want.items():
            s = step('fluke_323_pv.json', sid)
            self.assertEqual(row(s, '5522A')['Uncertainty'], a, sid)
            self.assertEqual(row(s, '5560A')['Uncertainty'], b, sid)

    def test_no_calibrator_falls_back_to_the_cmc(self):
        self.assertEqual(row(step('fluke_323_pv.json', '4-28'), None)['Uncertainty'], '360 pHz')

    def test_nothing_but_the_uncertainty_cells_changed(self):
        s = step('fluke_323_pv.json', '4-28')
        on = row(s)
        H.FREQ_UNCERTAINTY_FROM_CALIBRATOR = False
        try:
            off = row(s)
        finally:
            H.FREQ_UNCERTAINTY_FROM_CALIBRATOR = True
        self.assertEqual({k: v for k, v in on.items() if k != 'Uncertainty'}, {k: v for k, v in off.items() if k != 'Uncertainty'})

    def test_bench_default_of_report_pdf_is_unchanged(self):
        import report_pdf
        q = dict(kind='FREQ', nominal=50.0, frequency=None, unit='Hz', range=None)
        self.assertEqual(report_pdf.point_uncertainty(q, standard='5522A'), report_pdf.point_uncertainty(q))


if __name__ == '__main__':
    unittest.main()
