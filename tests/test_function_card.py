"""The 'Change the function' window (layout C: point strip + stepper): what it is built from, for several functions and families.
Presentation only; the prompt sequence, wording of the original steps and return values are covered by test_handheld_options and the golden transcripts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub
_tk_stub.install()
import handheld_dmm as h  # noqa: E402
from test_handheld_options import SPECS as _SPECS, Flow  # noqa: E402

SPECS = dict(_SPECS, **{'179': 'fluke_170_series_pv.json'})

STANDBY = 'The calibrator output is OFF (standby) while you turn the rotary switch.'


def first(model, section):
    spec = h.load_spec(SPECS[model])
    pts = h.points_for(spec, model)
    p = next(q for q in pts if q['section'] == section)
    return p, len(pts)


class Card(unittest.TestCase):
    def test_functions(self):
        for model, section, short, detail in (('117', 'AC volts', 'V~', 'AC volts'), ('117', 'Ohms', 'Ω', 'Ohms'), ('117', 'DC amps', 'A⎓', 'DC amps'),
                                              ('179', 'Temperature', 'Temperature', '179 only; press the YELLOW button'),
                                              ('117', 'Capacitance', 'Capacitance', '')):
            p, total = first(model, section)
            c = h.function_change_card(p, total, STANDBY)
            self.assertEqual((c['n'], c['total']), (p['n'], total))
            self.assertEqual(c['test'], h.describe(p))
            self.assertEqual(c['meter_line'], f'Meter: {short}' + (f'  range {p["range"]}' if p['range'] else ''))
            (l1, d1, s1), (l2, d2, s2), (l3, d3, s3) = c['steps']
            self.assertEqual(d1, STANDBY)                           # the standby sentence is unchanged
            self.assertEqual(l2, f'Turn the rotary switch to {short}')
            self.assertEqual(d2, detail)
            self.assertEqual(l3, f'Press Done when the meter shows {short}')

    def test_standby_tick_only_when_known(self):
        p, total = first('117', 'AC volts')
        self.assertEqual(h.function_change_card(p, total, STANDBY)['steps'][0][2], 'todo')
        self.assertEqual(h.function_change_card(p, total, STANDBY, standby_known=True)['steps'][0][2], 'done')

    def test_other_families_keep_full_switch_text(self):
        for model, section in (('87V', 'Resistance'), ('287', 'Capacitance'), ('77IV', 'Continuity'), ('MM325', 'DC current')):
            p, total = first(model, section)
            c = h.function_change_card(p, total, STANDBY)
            short, detail = h.split_switch(p['switch'])
            self.assertIn(short, c['steps'][1][0])
            self.assertEqual(c['steps'][1][1], detail)
            self.assertTrue(all(t for t, _d, _s in c['steps']))

    def test_prompt_passes_layout_and_card_and_keeps_old_arguments(self):
        seen = []
        real = h.ui.confirm_steps

        def confirm(root, title, sub, steps, **k):
            if title == 'Change the function':
                seen.append((steps, k))
            return True
        h.ui.confirm_steps = confirm
        try:
            f = Flow('117')
            f.app._last_switch = None
            f.app._next(f.app.points, 0, None)
        finally:
            h.ui.confirm_steps = real
        self.assertTrue(seen)
        steps, k = seen[0]
        self.assertEqual(k['layout'], 'function_change')
        self.assertEqual(steps[0][0], 'Rotary switch')                                 # the original list is still passed, unchanged
        self.assertTrue(steps[0][1].startswith('Turn the meter to: '))
        self.assertIn('Keep the calibrator in STANDBY', steps[1][1])                    # Flow uses the manual calibrator
        self.assertEqual(k['card']['steps'][0][2], 'todo')
        self.assertEqual(k['facts'][0][0], 'Next point')


if __name__ == '__main__':
    unittest.main()
