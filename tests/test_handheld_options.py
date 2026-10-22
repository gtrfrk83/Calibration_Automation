"""Rules (NOTES.md standing rules): handheld procedures go straight to high voltage except where a manual prescribes a ramp
(options.auto_ramp), and every function change prompts for the rotary switch (options.function_prompt)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tk_stub
_tk_stub.install()
import handheld_dmm as h  # noqa: E402
from drivers.simulated import SimFlukeTransport, make_bench  # noqa: E402

SPECS = {'113': 'fluke_110_series_pv.json', '117': 'fluke_110_series_pv.json', '87V': 'fluke_87v_pv.json', '287': 'fluke_287_289_pv.json',
         '289': 'fluke_287_289_pv.json', 'MM325': 'klein_mm325_pv.json'}
NEW_STYLE = ('87V', '287', '289', 'MM325')          # specs whose options set auto_ramp false (the 110-series keeps explicit ramp lists)


class Spy(SimFlukeTransport):
    """The simulated calibrator, remembering every command written to it."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sent = []

    def write(self, text):
        self.sent.append(text.strip())
        super().write(text)


def make_io(spec):
    bench, _ft, _s = make_bench()
    t = Spy(bench, '5522A')
    io = h.IO('Fluke 5522A', 'sim', transport=t)
    io.auto_ramp = spec.get('options', {}).get('auto_ramp', True)
    io._wait = lambda *a, **k: None
    return io, t


def outs(t, since):
    return [c for c in t.sent[since:] if c.upper().startswith('OUT ') and not c.endswith('?')]


class DirectHighVoltage(unittest.TestCase):
    def test_options(self):
        for model in NEW_STYLE:
            o = h.load_spec(SPECS[model]).get('options', {})
            self.assertIs(o.get('auto_ramp'), False, model)
            self.assertIs(o.get('function_prompt'), True, model)
        o110 = h.load_spec(SPECS['113'])['options']
        self.assertTrue(o110.get('auto_ramp', True))            # 3-40 (AUTO-V LoZ) must still ramp
        self.assertIs(o110.get('function_prompt'), True)

    def test_every_point_above_100v_is_one_out_command_unless_ramp_list(self):
        for model in NEW_STYLE:
            spec = h.load_spec(SPECS[model])
            io, t = make_io(spec)
            seen = 0
            for p in h.points_for(spec, model):
                a = p.get('applied')
                if not a or p['kind'] not in ('DCV', 'ACV') or abs(a['value']) <= 100:
                    continue
                n0 = len(t.sent)
                io.apply(p)
                got = outs(t, n0)
                want = len(p['ramp']) if p.get('ramp') else 1
                self.assertEqual(len(got), want, f'{model} {p["id"]}: {got}')
                seen += 1
            self.assertGreater(seen, 0, model)

    def test_289_footnote_7_ramp_kept(self):
        spec = h.load_spec(SPECS['289'])
        ramps = [p for p in h.points_for(spec, '289') if p.get('ramp')]
        self.assertEqual([p['ramp'] for p in ramps], [[60.0, 120.0]])
        io, t = make_io(spec)
        io.apply(ramps[0])
        self.assertEqual(len(outs(t, 0)), 2)

    def test_110_series_unchanged(self):
        """Explicit single-step ramp lists on the 600 V points; the 50 V ramp stays only on AUTO-V LoZ (3-40)."""
        spec = h.load_spec(SPECS['113'])
        io, t = make_io(spec)
        for p in h.points_for(spec, '117'):
            a = p.get('applied')
            if not a or p['kind'] not in ('DCV', 'ACV') or abs(a['value']) <= 100:
                continue
            n0 = len(t.sent)
            io.apply(p)
            got = outs(t, n0)
            if p['id'] == '3-40':
                self.assertEqual(len(got), 10, got)
                self.assertEqual(got[0].split(',')[0], 'OUT 50V')
            else:
                self.assertEqual(len(p['ramp']), 1, p['id'])
                self.assertEqual(len(got), 1, (p['id'], got))


class Flow:
    """Runs App._next over a model's points with the dialogs replaced by recorders (manual calibrator, typed readings)."""
    def __init__(self, model, cancel_at=None, calibrator=False):
        self.spec = h.load_spec(SPECS[model])
        self.events, self.cancel_at, self.n_prompts = [], cancel_at, 0
        app = object.__new__(h.App)
        app.spec, app.model = self.spec, model
        app.points = h.points_for(self.spec, model)
        app.demo, app.stop, app._busy = False, False, False
        app.io = None
        app.last_high_current = None
        app._stage = {'id': None, 'done': set()}
        app.cal_mode = SimpleNamespace(get=lambda: 'Fluke 5522A' if calibrator else 'Manual calibrator')
        if calibrator:                                      # a calibrator that accepts everything (the worker thread runs inline)
            app.io = SimpleNamespace(standby=lambda: None, apply=lambda p, cancel=None: None)
            app._poll = lambda points, i, p, key, state: app._ask(points, i, p, key)
        app.read_mode = SimpleNamespace(get=lambda: h.READ_TYPED)
        app.ir = self.spec['options'].get('ir')
        app.tree = SimpleNamespace(exists=lambda i: False)
        app.status = SimpleNamespace(set=lambda s: None)
        app.root = SimpleNamespace(after=lambda ms, fn: fn())
        app.save = lambda: None
        app._prompt_setup = lambda p: self.events.append(('setup', p['n'])) or True
        app._ask = lambda points, i, p, key: (self.events.append(('point', p['n'])), app._next(points, i + 1, key))
        self.app = app

    def run(self):
        orig_confirm, orig_range, orig_ask = h.ui.confirm_steps, h.ask_range, h.messagebox.askyesno
        flow = self

        def confirm(root, title, sub, steps, **k):
            if title == 'Change the function':
                flow.n_prompts += 1
                flow.events.append(('function', k['facts'][0][1].split()[0], steps[0][1].replace('Turn the meter to: ', '')))
                return flow.cancel_at != flow.n_prompts
            flow.events.append(('other-prompt', title))
            return True
        h.ui.confirm_steps = confirm
        h.ask_range = lambda root, p, total, dial, text: self.events.append(('range', p['n'])) or 'ok'
        h.messagebox.askyesno = lambda *a, **k: self.events.append(('hv', a[1])) or True
        try:
            self.app._last_switch = None
            self.app._next(self.app.points, 0, None)
        finally:
            h.ui.confirm_steps, h.ask_range, h.messagebox.askyesno = orig_confirm, orig_range, orig_ask
        return self.events

    def functions(self):
        return [(e[1], e[2]) for e in self.events if e[0] == 'function']


class FunctionPrompt(unittest.TestCase):
    def test_sequences(self):
        for model, want in EXPECTED.items():
            f = Flow(model)
            f.run()
            self.assertEqual([sw for _n, sw in f.functions()], want, model)

    def test_prompt_precedes_the_point_and_follows_the_setup_prompt(self):
        for model in ('87V', '287', '289'):
            ev = Flow(model).run()
            for i, e in enumerate(ev):
                if e[0] == 'function':
                    nxt = [x for x in ev[i + 1:] if x[0] in ('point', 'function')][0]       # (only the REL / meter-setup / HV confirmations may sit in between) IR read / typed reading happens in the point
                    self.assertEqual(nxt, ('point', int(e[1])), (model, e))
                    if i and ev[i - 1][0] == 'setup':
                        self.assertEqual(ev[i - 1][1], int(e[1]), (model, e))

    def test_no_prompt_for_functional_checks_or_hand_set_points(self):
        for model in ('87V', '287', '289', '113'):
            f = Flow(model)
            none_pts = {p['n'] for p in f.app.points if p['group'] == 'NONE'}
            f.run()
            self.assertFalse(none_pts & {int(n) for n, _ in f.functions()}, model)
            self.assertTrue(none_pts, model)

    def test_no_double_prompt_on_same_function(self):
        for model in ('87V', '287', '289', 'MM325', '113'):
            seq = [sw for _n, sw in (lambda f: (f.run(), f.functions())[1])(Flow(model))]
            self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])), model)

    def test_mm325_dial_prompt_replaces_function_prompt(self):
        ev = Flow('MM325').run()
        self.assertFalse([e for e in ev if e[0] == 'function'])
        self.assertEqual(len([e for e in ev if e[0] == 'range']), 18)

    def test_cancel_pauses_then_resume_prompts_again(self):
        f = Flow('87V', cancel_at=2)
        ev = f.run()
        self.assertEqual(f.n_prompts, 2)
        self.assertFalse(f.app.busy)
        self.assertEqual(ev[-1][0], 'function')                 # stopped there: no point was recorded after it
        resumed = Flow('87V')
        resumed.app.points = [p for p in resumed.app.points if p['n'] >= int(ev[-1][1])]
        resumed.run()
        self.assertEqual(resumed.functions()[0][1], ev[-1][2])  # a fresh run asks for the same function again

    def test_high_voltage_prompt_mentions_a_ramp_only_when_one_happens(self):
        texts = {}
        for model in ('87V', '289', '113', '117'):
            f = Flow(model, calibrator=True)
            f.run()
            texts[model] = {}
            pts = {p['n']: p for p in f.app.points}
            hv_points = [p for p in f.app.points if f.app._high_voltage(p)]
            hv_texts = [e[1] for e in f.events if e[0] == 'hv']
            self.assertEqual(len(hv_texts), len(hv_points), model)
            texts[model] = dict(zip([p['id'] for p in hv_points], hv_texts))
        self.assertFalse([i for i, t in texts['87V'].items() if 'ramp' in t])
        self.assertFalse([i for i, t in texts['289'].items() if 'ramp' in t])
        self.assertFalse([i for i, t in texts['117'].items() if 'ramp' in t and i != '3-40'])      # explicit one-step lists: no ramp
        self.assertIn('ramped', texts['117']['3-40'])

    def test_off_when_not_enabled(self):
        f = Flow('87V')
        f.app.spec = dict(f.spec, options={k: v for k, v in f.spec['options'].items() if k != 'function_prompt'})
        f.run()
        self.assertFalse(f.functions())


EXPECTED = {       # the rotary-switch prompts, in order (group NONE points carry their own prompt; MM325 gets its dial prompt at every point)
    '113': ['Ω  (Ohms)  [113: CHEK / Ω position]', 'V CHEK  Continuity', 'V CHEK  Diode test', 'V CHEK  Volts'],
    '117': ['Ω  (Ohms)', 'Continuity', 'V~  (AC volts)', 'V~ Hz  (AC volts + frequency)', 'V⎓  (DC volts)', 'mV~  (AC millivolts)',
            'mV⎓  (DC millivolts)', 'Diode', 'LoZ capacitance', 'A⎓  (DC amps)', 'A~  (AC amps)', 'AUTO-V LoZ', 'VoltAlert  (Hi)', 'VoltAlert  (Lo)'],
    '87V': ['mV  (AC millivolts)', 'V~  (AC volts)', 'Hz  (frequency, AC volts input)', 'Hz  (duty cycle, DC volts input)', 'V⎓  (DC volts)', 'mV  (DC millivolts)', 'Ω  (resistance)',
            'Diode test', 'A~  (AC amps)', 'A⎓  (DC amps)', 'mA / µA', 'V~  (AC volts)', 'V⎓  (DC volts)', 'Temperature'],
    '287': ['mV ⎓ / temperature position, temperature (°C)', 'mV ⎓ / temperature position (DC millivolts)', 'Ω position (ohms)',
            'mV ~ position (AC millivolts)', 'V ~ position (AC volts)', 'V ⎓ position (DC volts)',
            'Ω position, capacitance (press the yellow button)', 'diode / continuity position', 'µA position (current)',
            'mA / A position, mA', 'mA / A position, A'],
    'MM325': [],
}
EXPECTED['289'] = EXPECTED['287'][:8] + ['Ω position, LoΩ (289)'] + EXPECTED['287'][8:] + ['LoZ position (289)']

if __name__ == '__main__':
    unittest.main()
