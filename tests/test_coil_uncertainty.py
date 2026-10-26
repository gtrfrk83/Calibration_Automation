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
            if s.get('unc_kind') == 'FREQ':
                continue               # the 325 Frequency rows: the lab's Frequency - Measure CMC alone (existing mechanism), not the coil sheet
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

    def test_ac_10_a_is_below_the_coils_20_5_a_ac_range_so_the_calibrator_is_used(self):
        import iflex_option
        d = json.loads((ROOT / 'specs' / 'fluke_376_pv.json').read_text(encoding='utf-8'))
        by = {s['id']: s for s in d['steps']}
        s = dict(by['1-23'], test='numeric')
        self.assertEqual(iflex_option.App.unc_source(s), (0.2, None))                       # the sourced current and the calibrator in use
        self.assertEqual(iflex_option.App.unc_source(dict(by['1-35'], test='numeric')), (0.2, None))
        self.assertEqual(iflex_option.App.unc_source(by['1-24']), (500.0, COIL))            # covered: the coil sheet at the effective current
        self.assertEqual(iflex_option.App.unc_source(by['1-27']), (10.0, COIL))             # DC 10 A: the coil's DC row (2 to 20 A)
        # the coil's own sheet alone prints nothing for AC 10 A (nothing is extrapolated)
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



class Interaction(unittest.TestCase):
    def test_the_interaction_term_and_the_pure_rule(self):
        import coil_rule
        self.assertAlmostEqual(coil_rule.interaction_limit(500.0), 3.0)                  # 0.50 % of 500 A + 0.5 A
        (name, u, sens), = coil_rule.extra_components(500.0)
        self.assertAlmostEqual(u, 1.5)                                                   # limit / 2
        self.assertEqual(coil_rule.sourced_current(500.0), 10.0)
        self.assertEqual(coil_rule.uncertainty_source('ACI', 500.0, 10.0, 50.0)[1], COIL)
        self.assertEqual(coil_rule.uncertainty_source('ACI', 10.0, 0.2, 50.0), (0.2, None, ()))      # below the coil's range: the calibrator at the sourced current, no interaction
        self.assertEqual(coil_rule.uncertainty_source('DCI', 10.0, 0.2)[1], COIL)

    def test_it_is_rss_with_the_coil_line(self):
        import uncertainty_budget as ub
        import coil_rule
        b = ub.build('ACI', 500.0, 'A', standard=COIL, frequency=50.0, extra=coil_rule.extra_components(500.0))
        self.assertAlmostEqual(b.emu, (4.0 ** 2 + 3.0 ** 2) ** 0.5, 6)                  # 5.0 A, k = 2
        self.assertEqual(b.reported, 5.0)


if __name__ == '__main__':
    unittest.main()


class Scale(unittest.TestCase):
    """Owner 2026-10-26: below the coil's range the calibrator's uncertainty at the sourced current is multiplied by the 50 turns."""
    def test_scale_factor(self):
        import coil_rule
        self.assertEqual(coil_rule.uncertainty_scale('ACI', 10.0, 50.0), 50.0)           # AC 10 A: below 20.5 A
        self.assertEqual(coil_rule.uncertainty_scale('ACI', 500.0, 50.0), 1.0)           # covered by the coil sheet
        self.assertEqual(coil_rule.uncertainty_scale('DCI', 10.0), 1.0)
        import iflex_option
        d = json.loads((ROOT / 'specs' / 'fluke_376_pv.json').read_text(encoding='utf-8'))
        by = {s['id']: dict(s, test='numeric') for s in d['steps']}
        self.assertEqual(iflex_option.App.unc_scale(by['1-23']), 50.0)
        self.assertEqual(iflex_option.App.unc_scale(by['1-24']), 1.0)
        self.assertEqual(iflex_option.App.unc_scale(by['1-10']), 1.0)                    # not a coil point

    def test_budget_and_ratios_are_referred_to_the_current_the_clamp_reads(self):
        import uncertainty_budget as ub, tartur
        one = ub.build('ACI', 0.2, 'A', standard='5522A', frequency=50.0)
        fifty = ub.build('ACI', 0.2, 'A', standard='5522A', frequency=50.0, scale=50.0)
        self.assertAlmostEqual(fifty.emu, one.emu * 50, places=12)
        self.assertAlmostEqual(fifty.cmc, one.cmc * 50, places=12)
        q1 = dict(kind='ACI', nominal=0.2, frequency=50.0, unit='A', range=None)
        q50 = dict(q1, scale=50.0)
        r1 = tartur.row_fields(q1, 9.3, 10.7, standard='5522A')
        r50 = tartur.row_fields(q50, 9.3, 10.7, standard='5522A')
        self.assertNotEqual(r1['TUR'], r50['TUR'])
        self.assertLess(float(r50['TUR'].split(':')[0].lstrip('>')), 100)                # about 20:1 instead of >1000:1

