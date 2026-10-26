"""Clamp meters on the 50-turn coil (Fluke 374 / 375 / 376 / 376-II) take their uncertainty from the A2LA 5500A/COIL sheet at the effective current.
Rule (NOTES.md): every procedure with 50-turn-coil points carries unc_standard / unc_nominal on those steps - this test fails for a new one that forgets."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import report_review_model as R  # noqa: E402
import report_pdf  # noqa: E402

COIL = 'A2LA-5500A-COIL'


def steps_with_coil():
    for f in sorted((ROOT / 'specs').glob('*_pv.json')):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for s in d.get('steps', []) if isinstance(d, dict) else []:
            text = json.dumps(s)
            if 'COIL' in str(s.get('group', '')) and ('50-turn' in text or '50 turns' in text or 'x 50' in text):
                yield f.name, s


class Rule(unittest.TestCase):
    def test_every_50_turn_coil_step_names_the_coil_sheet_and_the_effective_current(self):
        found = list(steps_with_coil())
        self.assertTrue(found, 'no 50-turn coil steps found')
        for name, s in found:
            self.assertEqual(s.get('unc_standard'), COIL, f'{name} step {s.get("id")}: a 50-turn-coil point must use {COIL}')
            self.assertEqual(float(s['unc_nominal']), float(s['nominal']), f'{name} step {s.get("id")}: use the EFFECTIVE current (the nominal)')

    def test_the_20_turn_365_is_not_a_50_turn_coil_and_keeps_its_calibrator_uncertainty(self):
        d = json.loads((ROOT / 'specs' / 'fluke_365_pv.json').read_text(encoding='utf-8'))
        self.assertFalse([s for s in d['steps'] if 'unc_standard' in s])


class Numbers(unittest.TestCase):
    def ev(self, kind, nominal, freq, low, high):
        q = dict(kind=kind, nominal=nominal, frequency=freq, unit='A', range=None)
        return R.evaluate(R.PointSpec(0, 'x', '', '', '', q, q, low, high, 'A', COIL, expects=True), COIL)

    def test_ac_500_a_uses_the_coil_line_not_the_larger_amplifier_line(self):
        e = self.ev('ACI', 500.0, 50.0, 489.5, 510.5)
        self.assertEqual(e.reported, 4.0)                                  # 0.8 % of 500 A; the 0.7 % + 0.84 A amplifier line (4.34 A) is other equipment
        self.assertEqual(e.status, R.AS_BUDGETED)

    def test_ac_440_hz_band(self):
        self.assertAlmostEqual(self.ev('ACI', 300.0, 440.0, 291.0, 309.0).budget, 2.97)       # 0.99 %

    def test_dc_10_a_uses_the_coil_dc_row(self):
        self.assertAlmostEqual(self.ev('DCI', 10.0, None, 9.0, 11.0).reported, 0.001)        # 90 uA/A + 0.1 mA

    def test_ac_10_a_is_below_the_coils_20_5_a_ac_range_and_is_not_in_scope(self):
        e = self.ev('ACI', 10.0, 50.0, 9.3, 10.7)
        self.assertEqual((e.unc_text, e.status), ('', R.NOT_IN_SCOPE))
        self.assertEqual(report_pdf.point_uncertainty(dict(kind='ACI', nominal=10.0, frequency=50.0, unit='A', range=None), standard=COIL), '')


class Review(unittest.TestCase):
    def spec(self, kind, nominal, freq, low, high):
        q = dict(kind=kind, nominal=nominal, frequency=freq, unit='A', range=None)
        s = R.PointSpec(0, 'c', '', '', '', q, q, low, high, 'A', COIL, printed={'Uncertainty': 'x'}, expects=True)
        s.options = [COIL]
        return s

    def test_a_coil_row_is_not_moved_by_the_run_default(self):
        m = R.ReviewModel([self.spec('ACI', 500.0, 50.0, 489.5, 510.5)], default_standard='5560A')
        self.assertEqual(m.table()[0]['standard'], COIL)
        m.set_default('5522A')
        self.assertEqual(m.table()[0]['standard'], COIL)
        self.assertEqual(m.rows[0].cur.reported, 4.0)
        self.assertFalse(m.set_standard(0, '5560A'))                       # the coil is not a calibrator choice

    def test_an_uncovered_coil_row_is_open_for_a_typed_value(self):
        m = R.ReviewModel([self.spec('ACI', 10.0, 50.0, 9.3, 10.7)], default_standard='5560A')
        self.assertEqual(m.table()[0]['status'], R.NOT_IN_SCOPE)
        self.assertTrue(m.set_typed(0, '80 mA', source='owner', reason='below the coil lines')[0])


if __name__ == '__main__':
    unittest.main()
