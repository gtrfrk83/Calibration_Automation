"""Fluke 101 procedure (Procedures/Fluke_101_Verification.py on the shared handheld engine, specs/fluke_101_pv.json).

The Users Manual has no calibration table: one point per range at 90 % of the range (AC volts and AC millivolts at 60 and 400 Hz), limits = the published
1-year accuracy (pp. 20 and 22) rounded inward to the display step.  Part 1: the spec against an INDEPENDENT hand transcription of those limits (computed
from the specification table read a second time from the page images), options, prompts.  Part 2: the real engine on the simulated bench with both calibrators.
tkinter is stubbed in setUpModule (not at import time), like tests/test_77_points.py.
Run:  python -m unittest tests.test_fluke_101_points"""
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
SPEC_NAME = 'fluke_101_pv.json'
MODEL = '101'

# step -> (calibrator output as the engine words it, lower limit, upper limit, display unit, range)
EXPECTED = {
    1: ('5.4 V AC @ 60 Hz', '5.343', '5.457', 'V', '6.000 V'), 2: ('5.4 V AC @ 400 Hz', '5.343', '5.457', 'V', '6.000 V'),
    3: ('54 V AC @ 60 Hz', '53.43', '54.57', 'V', '60.00 V'), 4: ('54 V AC @ 400 Hz', '53.43', '54.57', 'V', '60.00 V'),
    5: ('540 V AC @ 60 Hz', '534.3', '545.7', 'V', '600.0 V'), 6: ('540 V AC @ 400 Hz', '534.3', '545.7', 'V', '600.0 V'),
    7: ('5.4 V DC', '5.370', '5.430', 'V', '6.000 V'), 8: ('54 V DC', '53.70', '54.30', 'V', '60.00 V'), 9: ('540 V DC', '537.0', '543.0', 'V', '600.0 V'),
    10: ('540 mV AC @ 60 Hz', '523.5', '556.5', 'mV', '600.0 mV'), 11: ('540 mV AC @ 400 Hz', '523.5', '556.5', 'mV', '600.0 mV'),
    12: ('360 Ω', '357.9', '362.1', 'Ω', '400.0 Ω'), 13: ('3.6 kΩ', '3.580', '3.620', 'kΩ', '4.000 kΩ'), 14: ('36 kΩ', '35.80', '36.20', 'kΩ', '40.00 kΩ'),
    15: ('360 kΩ', '358.0', '362.0', 'kΩ', '400.0 kΩ'), 16: ('3.6 MΩ', '3.580', '3.620', 'MΩ', '4.000 MΩ'), 17: ('36 MΩ', '35.43', '36.57', 'MΩ', '40.00 MΩ'),
    18: ('1.8 V DC', '1.620', '1.980', 'V', '2.000 V'),
    19: ('45 nF', '44.05', '45.95', 'nF', '50.00 nF'), 20: ('450 nF', '440.5', '459.5', 'nF', '500.0 nF'), 21: ('4.5 µF', '4.270', '4.730', 'µF', '5.000 µF'),
    22: ('45 µF', '42.70', '47.30', 'µF', '50.00 µF'), 23: ('450 µF', '427.0', '473.0', 'µF', '500.0 µF'), 24: ('900 µF', '850', '950', 'µF', '1000 µF'),
    25: ('5 V AC @ 45 Hz', '44.93', '45.07', 'Hz', '50.00 Hz'), 26: ('5 V AC @ 450 Hz', '449.3', '450.7', 'Hz', '500.0 Hz'),
    27: ('5 V AC @ 4.5 kHz', '4.493', '4.507', 'kHz', '5.000 kHz'), 28: ('5 V AC @ 45 kHz', '44.93', '45.07', 'kHz', '50.00 kHz'),
    29: ('5 V AC @ 90 kHz', '89.7', '90.3', 'kHz', '100.0 kHz'),
}
SECTION_COUNTS = {'AC volts': 6, 'DC volts': 3, 'AC millivolts': 2, 'Ohms': 6, 'Diode test': 1, 'Capacitance': 6, 'Frequency': 5}
OUT_COMMANDS = {
    1: 'OUT 5.4V,60Hz', 2: 'OUT 5.4V,400Hz', 3: 'OUT 54V,60Hz', 4: 'OUT 54V,400Hz', 5: 'OUT 540V,60Hz', 6: 'OUT 540V,400Hz',
    7: 'OUT 5.4V,0Hz', 8: 'OUT 54V,0Hz', 9: 'OUT 540V,0Hz', 10: 'OUT 0.54V,60Hz', 11: 'OUT 0.54V,400Hz',
    12: 'OUT 360OHM', 13: 'OUT 3600OHM', 14: 'OUT 36000OHM', 15: 'OUT 360000OHM', 16: 'OUT 3600000OHM', 17: 'OUT 36000000OHM',
    18: 'OUT 1.8V,0Hz',
    19: 'OUT 45NF', 20: 'OUT 450NF', 21: 'OUT 4.5UF', 22: 'OUT 45UF', 23: 'OUT 450UF', 24: 'OUT 900UF',
    25: 'OUT 5V,45Hz', 26: 'OUT 5V,450Hz', 27: 'OUT 5V,4500Hz', 28: 'OUT 5V,45000Hz', 29: 'OUT 5V,90000Hz',
}
FUNCTION_PROMPTS = ['V~  (AC volts)', 'V⎓  (DC volts)', 'mV~  (AC millivolts)', 'Ω  (ohms)', 'Diode  ▶|  (dial: Ω position; push the YELLOW button twice)',
                    'Capacitance  ⊣⊢  (dial: capacitance position)', 'Hz  (dial: Hz position)']


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
    s = importlib.util.spec_from_file_location('build_fluke_101_spec', ROOT / 'specs' / 'build_fluke_101_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


class Spec(unittest.TestCase):
    def test_29_points_by_function(self):
        self.assertEqual(len(PTS), 29)
        counts = {}
        for p in PTS.values():
            counts[p['section']] = counts.get(p['section'], 0) + 1
        self.assertEqual(counts, SECTION_COUNTS)
        self.assertEqual({p['id'] for p in PTS.values()}, {f'1-{n}' for n in range(1, 30)})

    def test_every_point_matches_the_hand_transcription(self):
        for n, (out, low, high, unit, rng) in EXPECTED.items():
            p = PTS[n]
            self.assertEqual(h.output_text(p), out, n)
            self.assertEqual((p['low'], p['high'], p['display_unit'], p['range']), (low, high, unit, rng), n)
            self.assertEqual(p['test'], 'numeric')
            self.assertEqual(p['group'], 'VOHM')

    def test_one_point_at_90_percent_of_each_range_and_both_frequencies_for_ac_volts(self):
        for n, p in PTS.items():
            full = D(p['range'].split()[0])
            shown = D(str(p['nominal'])) / D(str(p['factor']))
            self.assertEqual(shown, full * D('0.9'), n)                       # the diode point is 1.8 V of the 2.000 V range
        for section in ('AC volts', 'AC millivolts'):
            self.assertEqual({p['applied']['frequency'] for p in PTS.values() if p['section'] == section}, {60.0, 400.0})
        ranges = [(p['section'], p['range']) for p in PTS.values() if p['section'] not in ('AC volts', 'AC millivolts')]
        self.assertEqual(len(ranges), len(set(ranges)))                      # exactly one point per range
        self.assertEqual(len([1 for p in PTS.values() if p['section'] == 'AC volts' and p['applied']['frequency'] == 60.0]), 3)

    def test_limits_are_the_published_accuracy_rounded_inward(self):
        """Independent recomputation: +/-(% x reading + counts x resolution); the limit is never looser than that and within one display step of it."""
        acc = {'AC volts': ('1.0', 3), 'DC volts': ('0.5', 3), 'AC millivolts': ('3.0', 3), 'Diode test': ('10', 0), 'Frequency': ('0.1', 3)}
        for n, p in PTS.items():
            sec = p['section']
            if sec in acc:
                pct, counts = acc[sec]
            elif sec == 'Ohms':
                pct, counts = {'400.0 Ω': ('0.5', 3), '40.00 MΩ': ('1.5', 3)}.get(p['range'], ('0.5', 2))
            else:
                pct, counts = ('2', 5) if 'nF' in p['range'] else ('5', 5)
            res = D(10) ** -(len(p['low'].split('.')[1]) if '.' in p['low'] else 0)
            reading = D(str(p['nominal'])) / D(str(p['factor']))
            half = D(pct) / 100 * reading + counts * res
            self.assertGreaterEqual(D(p['low']), reading - half, n)
            self.assertLessEqual(D(p['high']), reading + half, n)
            self.assertLess(D(p['low']), reading - half + res, n)
            self.assertGreater(D(p['high']), reading + half - res, n)

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_no_current_points_the_meter_has_no_current_function(self):
        self.assertFalse([p for p in PTS.values() if p['kind'] in ('ACI', 'DCI')])
        self.assertFalse([p for p in PTS.values() if p['group'] in ('UAMP', 'AMP10')])

    def test_frequency_rows_are_frequency_readings(self):
        for n in range(25, 30):
            p = PTS[n]
            self.assertEqual((p['kind'], p['unc_kind'], p['base_unit'], p['no_freq_suffix']), ('ACV', 'FREQ', 'Hz', True))
            self.assertEqual(p['applied']['value'], 5.0)

    def test_validator_options_and_no_remote_interface(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        o = SPEC['options']
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title'], o['auto_ramp'], o['function_prompt']), ('fluke101', 30, 'Calibration Data', False, True))
        self.assertNotIn('ir', o)
        self.assertFalse([n for n, p in PTS.items() if p.get('ramp')])

    def test_hookup_is_two_jacks(self):
        import hookups
        self.assertEqual(hookups.METERS['fluke101']['jacks'], {'vohm': 'VΩ', 'com': 'COM'})
        self.assertEqual(hookups.AVAILABLE['fluke101'], ('VOHM',))
        self.assertIn('VΩ', hookups.summary('fluke101', '5522A', 'VOHM'))

    def test_a_perfect_meter_passes_and_padding(self):
        for n, p in PTS.items():
            typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
            self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', n)
        for n, typed, want in ((1, '5.4', '5.400'), (9, '540', '540.0'), (24, '900', '900'), (25, '45', '45.00'), (10, '540', '540.0')):
            self.assertEqual(h.pad_reading(PTS[n], typed), want, n)
        self.assertEqual(h.judge_numeric(PTS[7], '5.44')[0], 'FAIL')


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
        for n, p in PTS.items():
            n0 = len(t.sent)
            io.apply(p)
            sent = t.sent[n0:]
            outs = [c for c in sent if c.upper().startswith('OUT ') and not c.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[n]], (model, n))
            self.assertEqual(sent[0], 'STBY', (model, n))
            self.assertLess(sent.index('ERR?'), sent.index('OPER'), (model, n))
            self.assertEqual(sum(1 for c in sent if c == 'OPER'), 1, (model, n))
            io.standby()
            self.assertEqual(t.sent[-1], 'STBY', (model, n))
            if p['kind'] == 'DCV':
                self.assertTrue(OUT_COMMANDS[n].endswith(',0Hz'), (model, n))                  # explicit 0 Hz on every DC output (diode point included)

    def test_5522a(self):
        self.check('5522A')

    def test_5560a(self):
        self.check('5560A')

    def test_5520a(self):
        self.check('5520A')

    def test_5520a_is_offered_and_every_point_has_an_uncertainty_with_all_three_calibrators(self):
        import calibrator_fit
        import report_pdf
        offer = calibrator_fit.make_offer('5520A', calibrator_fit.handheld_requests(list(PTS.values())))
        self.assertTrue(offer.offered)                                                       # all 29 points are inside the 5520A's published specification
        self.assertEqual(len(offer.fit.ok), 29)
        for cal in ('5520A', '5522A', '5560A'):
            for n, p in PTS.items():
                a = p['applied']
                q = (dict(kind='FREQ', nominal=a['frequency'], frequency=None, unit='Hz', range=None, use_standard=h.freq_from_calibrator()) if p.get('unc_kind') == 'FREQ'
                     else dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=a['value'], frequency=a.get('frequency'), unit=p['base_unit'], range=None))
                self.assertTrue(report_pdf.point_uncertainty(q, standard=cal), (cal, n))


class Prompts(unittest.TestCase):
    def test_function_and_cable_prompts(self):
        f = Flow('77IV')                                                                   # only the shared scaffolding; the points are replaced below
        f.app.spec, f.app.model, f.app.points = SPEC, MODEL, h.points_for(SPEC, MODEL)
        f.app.ir = SPEC['options'].get('ir')
        f.run()
        self.assertEqual([sw for _n, sw in f.functions()], FUNCTION_PROMPTS)
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], [1])                  # one hook-up for the whole run (VOHM)


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
        app.asset.set('A-101')
        app.serial.set('S-101')
        app.cal_mode.set(h.CAL_CHOICES[1] if model == '5522A' else h.CAL_CHOICES[0])
        if io:
            app.io = io
        self.hn.app = app
        return app, io

    def test_perfect_meter_passes_all_29_with_either_calibrator(self):
        for model in ('5522A', '5560A'):
            app, io = self.make(model)
            self.hn.default_reading = H.typed_nominal
            self.assertTrue(self.hn.run_all())
            self.assertEqual(len(app.found), 29, model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertEqual(app.found['1-7']['entered'], '5.400')
            self.assertEqual(app.found['1-25']['entered'], '45.00')
            texts = [t for _i, t in H.wire(io)]
            outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[n] for n in range(1, 30)], model)
            self.assertLess(texts.index('*RST'), texts.index(outs[0]))
            self.assertEqual(texts[-1], 'STBY')
            hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
            self.assertEqual(len(hv), 1, model)                                              # once per hook-up group (owner decision)
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_out_of_tolerance_fails(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['1-2'] = '5.5'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['1-2'])

    def test_demo_is_marked_and_touches_no_instrument(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 29)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertEqual(app.io, None)


class Registered(unittest.TestCase):
    def test_launcher_and_sidecar(self):
        spec = importlib.util.spec_from_file_location('launcher101', ROOT / 'Procedures' / 'Fluke_101_Verification.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual((mod.MODEL, mod.SPEC), (MODEL, SPEC_NAME))
        side = json.loads((ROOT / 'Procedures' / 'Fluke_101_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['launcher']), ('Fluke_101_Verification', '101', 'Procedures/Fluke_101_Verification.py'))
        self.assertIn('hookups.py#fluke101', side['fingerprint']['code'])
        self.assertFalse(side['seed_verified'])


if __name__ == '__main__':
    unittest.main()
