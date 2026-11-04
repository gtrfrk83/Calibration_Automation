"""Keithley 485 procedure (Procedures/Keithley_485_Verification.py on the shared handheld engine, specs/keithley_485_pv.json).

Instruction Manual Table 3-2 (p. 3-2): a DC calibrator through a measured resistor, V = I x R, every range at + and - current, plus the zero check.
Part 1: the spec against an INDEPENDENT hand transcription of Table 3-2 and of the resistance box values, the published accuracy, the uncertainty rule.
Part 2: the real engine on the simulated bench with all three calibrators.  tkinter is stubbed in setUpModule (not at import time), like tests/test_fluke_101_points.py.
Run:  python -m unittest tests.test_keithley_485_points"""
import importlib.util
import json
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
h = H = Flow = Spy = SPEC = PTS = BUILDER = None
SPEC_NAME = 'keithley_485_pv.json'
MODEL = '485'

# range -> (required current, unit, resistance box position, measured ohms (box calibration), printed low, printed high)   Table 3-2, p. 3-2
TABLE = {
    '2 nA': ('1.9000', 'nA', '10^10', '9932420000', '1.8920', '1.9080'),
    '20 nA': ('19.000', 'nA', '10^9', '1010135000', '18.923', '19.077'),
    '200 nA': ('190.00', 'nA', '10^8', '99956900', '189.61', '190.39'),
    '2 µA': ('1.9000', 'µA', '10^7', '10014901', '1.8971', '1.9029'),
    '20 µA': ('19.000', 'µA', '10^6', '999634.5', '18.980', '19.020'),
    '200 µA': ('190.00', 'µA', '10^5', '99974.57', '189.80', '190.20'),
    '2 mA': ('1.9000', 'mA', '10^4', '10001.29', '1.8980', '1.9020'),
}
# the calibrator setting V = I x R, rounded to 10 uV (worked by hand)
VOLTS = {'2 nA': '18.87160', '20 nA': '19.19257', '200 nA': '18.99181', '2 µA': '19.02831', '20 µA': '18.99306', '200 µA': '18.99517', '2 mA': '19.00245'}
OUT_COMMANDS = {}
for _i, _r in enumerate(TABLE):
    OUT_COMMANDS[2 + 2 * _i] = f'OUT {float(VOLTS[_r]):.9g}V,0Hz'
    OUT_COMMANDS[3 + 2 * _i] = f'OUT {-float(VOLTS[_r]):.9g}V,0Hz'
SCALE = {'nA': D('1E-9'), 'µA': D('1E-6'), 'mA': D('1E-3')}
ACC = {'2 nA': ('0.4', 4, '0.0001'), '20 nA': ('0.4', 1, '0.001'), '200 nA': ('0.2', 1, '0.01'), '2 µA': ('0.15', 1, '0.0001'),
       '20 µA': ('0.1', 1, '0.001'), '200 µA': ('0.1', 1, '0.01'), '2 mA': ('0.1', 1, '0.0001')}      # SPECIFICATIONS, 1 year, 18-28 degC


def setUpModule():
    global h, H, Flow, Spy, SPEC, PTS, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, Spy = _h, _H, _o.Flow, _o.Spy
    SPEC = h.load_spec(SPEC_NAME)
    PTS = {p['n']: p for p in h.points_for(SPEC, MODEL)}
    s = importlib.util.spec_from_file_location('build_keithley_485_spec', ROOT / 'specs' / 'build_keithley_485_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def numeric():
    return [p for p in PTS.values() if p['test'] == 'numeric']


class Spec(unittest.TestCase):
    def test_zero_check_then_14_points(self):
        self.assertEqual(len(PTS), 15)
        z = PTS[1]
        self.assertEqual((z['id'], z['test'], z['group']), ('F-1', 'visual', 'NONE'))
        self.assertIn('ZERO CHECK', z['setup'])
        self.assertEqual([p['id'] for p in numeric()], [f'3-2-{n}' for n in range(1, 15)])

    def test_every_point_matches_table_3_2_and_the_box(self):
        for i, (rng, (cur, unit, pos, ohms, low, high)) in enumerate(TABLE.items()):
            pos_p, neg_p = PTS[2 + 2 * i], PTS[3 + 2 * i]
            for p, sign in ((pos_p, 1), (neg_p, -1)):
                self.assertEqual((p['range'], p['display_unit'], p['kind'], p['base_unit']), (rng, unit, 'DCV', 'A'), rng)
                self.assertEqual(p['resistor']['position'], pos)
                self.assertEqual(D(str(p['resistor']['ohms'])), D(ohms))
                self.assertEqual(D(str(p['applied']['value'])), sign * D(VOLTS[rng]), rng)
                self.assertEqual(D(str(p['nominal'])), sign * D(cur) * SCALE[unit], rng)
                self.assertEqual(p['group'], 'R' + pos.split('^')[1])
                self.assertEqual(p['unc_kind'], 'CURRENT_VIA_R')
                self.assertEqual(h.output_text(p), f'{sign * D(VOLTS[rng]):.5f} V DC')
            self.assertEqual((pos_p['low'], pos_p['high']), (low, high))
            self.assertEqual((neg_p['low'], neg_p['high']), ('-' + high, '-' + low))

    def test_calibrator_setting_gives_the_required_current_within_1_ppm(self):
        for p in numeric():
            i = D(str(p['applied']['value'])) / D(str(p['resistor']['ohms']))
            self.assertLess(abs(i / D(str(p['nominal'])) - 1), D('1E-6'), p['id'])

    def test_printed_limits_are_inside_the_published_accuracy(self):
        for rng, (cur, unit, _pos, _ohms, low, high) in TABLE.items():
            pct, counts, res = ACC[rng]
            half = D(pct) / 100 * D(cur) + counts * D(res)
            self.assertGreaterEqual(D(low), D(cur) - half, rng)
            self.assertLessEqual(D(high), D(cur) + half, rng)
            self.assertLess(D(low), D(cur) - half + D(res), rng)
            self.assertGreater(D(high), D(cur) + half - D(res), rng)

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_validator_and_options(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        o = SPEC['options']
        self.assertEqual((o['hv_threshold_v'], o['report_title'], o['auto_ramp'], o['function_prompt']), (30, 'Calibration Data', False, False))
        self.assertTrue(all(abs(p['applied']['value']) < 30 for p in numeric()))         # about 19 V: no high-voltage question

    def test_a_perfect_meter_passes_and_padding(self):
        for p in numeric():
            typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
            self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', p['id'])
        self.assertEqual(h.pad_reading(PTS[2], '1.9'), '1.9000')
        self.assertEqual(h.pad_reading(PTS[3], '-1.9'), '-1.9000')
        self.assertEqual(h.judge_numeric(PTS[2], '1.9081')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[3], '1.9000')[0], 'FAIL')                  # wrong sign on the negative point


class Uncertainty(unittest.TestCase):
    def test_box_uncertainties_are_the_certificate(self):
        # Keysight WO-01470653 (Agilent 16340A S/N 1937J00597, ATS-4225), k = 2: 10 kOhm 0.0066 % + 0.1 mOhm, 100 kOhm 1.2, 1 MOhm 1.66, 10 MOhm 5.35,
        # 100 MOhm 60, 1 GOhm 193, 10 GOhm 240 uOhm/Ohm
        want = {'10^4': D('66') + D('0.0001') / D('10001.29') * D(10) ** 6, '10^5': D('1.2'), '10^6': D('1.66'), '10^7': D('5.35'),
                '10^8': D('60'), '10^9': D('193'), '10^10': D('240')}
        self.assertEqual((SPEC['resistance_box']['asset'], SPEC['resistance_box']['serial']), ('ATS-4225', '1937J00597'))
        for p in numeric():
            self.assertAlmostEqual(p['resistor']['u_ppm'], float(want[p['resistor']['position']]), places=6)

    def test_every_point_prints_an_uncertainty_and_ratios_with_every_calibrator(self):
        import handheld_unc
        for cal in ('5520A', '5522A', '5560A'):
            for p in numeric():
                self.assertTrue(handheld_unc.text(p, cal), (cal, p['id']))
                r = handheld_unc.ratios(p, cal, float(D(p['low']) * D(str(p['factor']))), float(D(p['high']) * D(str(p['factor']))))
                self.assertTrue(r['TAR'] and r['TUR'], (cal, p['id']))

    def test_blank_when_a_resistor_has_no_uncertainty(self):
        import handheld_unc
        p = dict(numeric()[0], resistor=dict(numeric()[0]['resistor'], u_ppm=None))
        self.assertEqual(handheld_unc.text(p, '5560A'), '')

    def test_rule_combines_the_dc_volts_budget_and_the_resistor(self):
        import math
        import handheld_unc
        import uncertainty_budget
        for cal in ('5520A', '5522A', '5560A'):
            for p in numeric():
                q = dict(p, resistor=dict(p['resistor'], u_ppm=100.0))
                u, acc, unit = handheld_unc.evaluate(q, cal)
                v, i = abs(p['applied']['value']), abs(p['nominal'])
                b = uncertainty_budget.build('DCV', v, 'V', standard=cal)
                self.assertEqual(unit, 'A')
                self.assertAlmostEqual(u, i * math.sqrt((b.value / v) ** 2 + 1e-8), delta=i * 1e-9)
                self.assertGreater(u, i * 100e-6)
                self.assertTrue(handheld_unc.text(q, cal))
                r = handheld_unc.ratios(q, cal, float(D(p['low']) * D(str(p['factor']))), float(D(p['high']) * D(str(p['factor']))))
                self.assertTrue(r['TAR'] and r['TUR'], (cal, p['id']))


def _io(model):
    from drivers.simulated import make_bench
    bench, _ft, _s = make_bench()
    t = Spy(bench, model)
    io = h.IO(f'Fluke {model}', 'sim', transport=t)
    io.auto_ramp = False
    io._wait = lambda *a, **k: None
    return io, t


class Calibrators(unittest.TestCase):
    def check(self, model):
        io, t = _io(model)
        for p in numeric():
            n0 = len(t.sent)
            io.apply(p)
            sent = t.sent[n0:]
            outs = [c for c in sent if c.upper().startswith('OUT ') and not c.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[p['n']]], (model, p['n']))
            self.assertTrue(outs[0].endswith(',0Hz'))
            self.assertEqual(sent[0], 'STBY', (model, p['n']))
            self.assertLess(sent.index('ERR?'), sent.index('OPER'), (model, p['n']))
            io.standby()
            self.assertEqual(t.sent[-1], 'STBY', (model, p['n']))

    def test_5522a(self):
        self.check('5522A')

    def test_5560a(self):
        self.check('5560A')

    def test_5520a(self):
        self.check('5520A')

    def test_5520a_is_offered(self):
        import calibrator_fit
        offer = calibrator_fit.make_offer('5520A', calibrator_fit.handheld_requests(numeric()))
        self.assertTrue(offer.offered)


class Prompts(unittest.TestCase):
    def test_one_setup_prompt_per_range(self):
        f = Flow('77IV')                                                                   # only the shared scaffolding; the points are replaced below
        f.app.spec, f.app.model, f.app.points = SPEC, MODEL, h.points_for(SPEC, MODEL)
        f.app.ir = SPEC['options'].get('ir')
        f.run()
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], [1, 2, 4, 6, 8, 10, 12, 14])
        self.assertEqual(f.functions(), [])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()

    def make(self, model='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {model}', 'sim', transport=Spy(bench, model))
            io.auto_ramp = False
        app = h.App(self.hn.root, MODEL, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
        app.asset.set('A-485')
        app.serial.set('S-485')
        app.cal_mode.set(h.CAL_CHOICES[1] if model == '5522A' else h.CAL_CHOICES[0])
        if io:
            app.io = io
        self.hn.app = app
        return app, io

    def test_perfect_meter_passes_with_either_calibrator(self):
        for model in ('5522A', '5560A'):
            app, io = self.make(model)
            self.hn.default_reading = H.typed_nominal
            self.assertTrue(self.hn.run_all())
            self.assertEqual(len(app.found), 15, model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertEqual(app.found['3-2-1']['entered'], '1.9000')
            texts = [t for _i, t in H.wire(io)]
            outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[n] for n in range(2, 16)], model)
            self.assertLess(texts.index('*RST'), texts.index(outs[0]))
            self.assertEqual(texts[-1], 'STBY')
            self.assertFalse([d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE'])
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_out_of_tolerance_fails(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['3-2-4'] = '-19.08'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['3-2-4'])

    def test_demo_is_marked_and_touches_no_instrument(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 15)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertEqual(app.io, None)


class Registered(unittest.TestCase):
    def test_launcher_and_sidecar(self):
        spec = importlib.util.spec_from_file_location('launcher485', ROOT / 'Procedures' / 'Keithley_485_Verification.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual((mod.MODEL, mod.SPEC), (MODEL, SPEC_NAME))
        side = json.loads((ROOT / 'Procedures' / 'Keithley_485_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['launcher']), ('Keithley_485_Verification', '485', 'Procedures/Keithley_485_Verification.py'))
        self.assertIn('handheld_unc.py', side['fingerprint']['code'])
        self.assertFalse(side['seed_verified'])


if __name__ == '__main__':
    unittest.main()
