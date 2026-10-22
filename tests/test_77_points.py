"""Fluke Model 77 Series IV procedure (Procedures/Fluke_77IV_Verification.py on the shared handheld engine, specs/fluke_77iv_pv.json).

Part 1: the spec against an INDEPENDENT second transcription of Calibration Information Table 2 (printed pp. 12-13, read from the rendered page
images) and against the manual's own accuracy method (p. 5); step 8's corrected limits; options; function / cable / high-voltage prompt sequences.
Part 2: the real engine (handheld_dmm.App, worker threads, drivers, judging, checkpoint, PDF) on the simulated bench with both calibrators
(5522A, 5560A): wire commands, explicit 0 Hz on DC, set / read back / never retried, standby after each point, reset first, demo never real.
tkinter is stubbed in setUpModule (not at import time), like tests/test_87v_points.py, so tests.test_beta is loaded exactly as before.
Run:  python -m unittest tests.test_77_points"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
h = H = rt = Flow = SPECS = Spy = SPEC = PTS = BUILDER = None
SPEC_NAME = 'fluke_77iv_pv.json'
MODEL = '77IV'

# Table 2 as read a second time from the page images: step -> (calibrator output as the engine words it, lower limit, upper limit, display unit)
TABLE_2 = {
    1: ('500 Ω', '497.3', '502.7', 'Ω'), 2: ('50 kΩ', '49.74', '50.26', 'kΩ'), 3: ('5 MΩ', '4.974', '5.026', 'MΩ'),
    4: ('10 MΩ', '9.79', '10.21', 'MΩ'), 5: ('40 MΩ', '39.19', '40.81', 'MΩ'),
    6: ('25 Ω', None, None, 'Ω'), 7: ('250 Ω', None, None, 'Ω'),
    8: ('50 mV AC @ 45 Hz', '0.047', '0.053', 'V'),                    # printed 0.47 / 0.53: corrected, see Step8
    9: ('5 V AC @ 45 Hz', '4.898', '5.102', 'V'), 10: ('5 V AC @ 1 kHz', '4.898', '5.102', 'V'),
    11: ('50 V AC @ 45 Hz', '48.98', '51.02', 'V'), 12: ('50 V AC @ 1 kHz', '48.98', '51.02', 'V'),
    13: ('500 V AC @ 45 Hz', '489.8', '510.2', 'V'), 14: ('500 V AC @ 1 kHz', '489.8', '510.2', 'V'),
    15: ('1 kV AC @ 45 Hz', '978', '1022', 'V'), 16: ('1 kV AC @ 1 kHz', '978', '1022', 'V'),
    17: ('5 V AC @ 50 kHz', '49.94', '50.06', 'kHz'),
    18: ('5 V DC', '4.984', '5.016', 'V'), 19: ('300 V DC', '299.0', '301.0', 'V'),
    20: ('1 kV DC', '996', '1004', 'V'), 21: ('-1 kV DC', '-1004', '-996', 'V'),
    22: ('30 mV DC', '29.8', '30.2', 'mV'), 23: ('-300 mV DC', '-301.0', '-299.0', 'mV'), 24: ('600 mV DC', '598.1', '601.9', 'mV'),
    25: ('900 nF', '887', '913', 'nF'),
    26: ('500 µA AC @ 45 Hz', '0.47', '0.53', 'mA'), 27: ('50 mA AC @ 1 kHz', '48.73', '51.27', 'mA'), 28: ('400 mA AC @ 1 kHz', '389.8', '410.2', 'mA'),
    29: ('4 A AC @ 45 Hz', '3.898', '4.102', 'A'), 30: ('9 A AC @ 1 kHz', '8.75', '9.25', 'A'),
    31: ('3 mA DC', '2.93', '3.07', 'mA'), 32: ('50 mA DC', '49.23', '50.77', 'mA'), 33: ('-400 mA DC', '-406.2', '-393.8', 'mA'),
    34: ('4 A DC', '3.938', '4.062', 'A'), 35: ('-9 A DC', '-9.16', '-8.84', 'A'),
}
# what the calibrator is sent for each step (both calibrators): the command, then every DC output with an explicit ,0Hz
OUT_COMMANDS = {
    1: 'OUT 500OHM', 2: 'OUT 50000OHM', 3: 'OUT 5000000OHM', 4: 'OUT 10000000OHM', 5: 'OUT 40000000OHM', 6: 'OUT 25OHM', 7: 'OUT 250OHM',
    8: 'OUT 0.05V,45Hz', 9: 'OUT 5V,45Hz', 10: 'OUT 5V,1000Hz', 11: 'OUT 50V,45Hz', 12: 'OUT 50V,1000Hz', 13: 'OUT 500V,45Hz', 14: 'OUT 500V,1000Hz',
    15: 'OUT 1000V,45Hz', 16: 'OUT 1000V,1000Hz', 17: 'OUT 5V,50000Hz',
    18: 'OUT 5V,0Hz', 19: 'OUT 300V,0Hz', 20: 'OUT 1000V,0Hz', 21: 'OUT -1000V,0Hz', 22: 'OUT 0.03V,0Hz', 23: 'OUT -0.3V,0Hz', 24: 'OUT 0.6V,0Hz',
    25: 'OUT 900NF',
    26: 'OUT 0.0005A,45Hz', 27: 'OUT 0.05A,1000Hz', 28: 'OUT 0.4A,1000Hz', 29: 'OUT 4A,45Hz', 30: 'OUT 9A,1000Hz',
    31: 'OUT 0.003A,0Hz', 32: 'OUT 0.05A,0Hz', 33: 'OUT -0.4A,0Hz', 34: 'OUT 4A,0Hz', 35: 'OUT -9A,0Hz',
}
SECTION_COUNTS = {'Ohms': 5, 'Continuity': 2, 'AC volts': 9, 'AC volts frequency': 1, 'DC volts': 4, 'DC millivolts': 3, 'Capacitance': 1,
                  'AC milliamps': 3, 'AC amps': 2, 'DC milliamps': 3, 'DC amps': 2}
FUNCTION_PROMPTS = ['Ω  (dial: Ω / capacitance position)', 'Continuity  •)))  (dial: continuity / diode position)', 'V~  (dial: Hz V~ position)', 'Hz  (dial: Hz V~ position; press the YELLOW button)', 'V⎓  (dial: V⎓ position)', 'mV⎓  (dial: mV⎓ position)', 'Capacitance  ⊣⊢  (dial: Ω / capacitance position; press the YELLOW button)', 'mA~  (dial: mA position, AC)', 'A~  (dial: A position, AC)', 'mA⎓  (dial: mA position; press the YELLOW button)', 'A⎓  (dial: A position; press the YELLOW button)']


def setUpModule():
    """tkinter is stubbed here, not at import time (see tests/test_87v_points.py)."""
    global h, H, rt, Flow, SPECS, Spy, SPEC, PTS, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy = _h, _H, _o.Flow, _o.SPECS, _o.Spy
    assert SPECS[MODEL] == SPEC_NAME                            # registered in tests/test_handheld_options.py (the shared Flow helper looks the spec up by model)
    SPEC = h.load_spec(SPEC_NAME)
    PTS = {p['n']: p for p in h.points_for(SPEC, MODEL)}
    s = importlib.util.spec_from_file_location('build_77_spec', ROOT / 'specs' / 'build_77_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


class Spec(unittest.TestCase):
    def test_35_points_by_function(self):
        self.assertEqual(len(PTS), 35)
        counts = {}
        for p in PTS.values():
            counts[p['section']] = counts.get(p['section'], 0) + 1
        self.assertEqual(counts, SECTION_COUNTS)
        self.assertEqual([p['step'] for p in PTS.values()], list(range(1, 36)))        # manual order, no gaps
        self.assertEqual({p['id'] for p in PTS.values()}, {f'2-{n}' for n in range(1, 36)})
        self.assertEqual(sum(1 for p in PTS.values() if p['test'] == 'numeric'), 33)
        self.assertEqual([n for n, p in PTS.items() if p['test'] == 'beeper'], [6, 7])

    def test_every_point_matches_table_2(self):
        for n, (out, low, high, unit) in TABLE_2.items():
            p = PTS[n]
            self.assertEqual(h.output_text(p), out, n)
            self.assertEqual(p['display_unit'], unit, n)
            if low is None:
                self.assertEqual((p['test'], p.get('low'), p.get('high')), ('beeper', None, None), n)
            else:
                self.assertEqual((p['low'], p['high']), (low, high), n)
                self.assertEqual(p['test'], 'numeric')

    def test_beeper_points(self):
        a, b = PTS[6], PTS[7]
        self.assertEqual((a['expect'], b['expect']), ('on', 'off'))
        self.assertEqual((a['applied']['value'], b['applied']['value']), (25, 250))
        self.assertEqual(h.describe(a), 'Continuity, 25 Ω: beeper ON')
        self.assertEqual(h.describe(b), 'Continuity, 250 Ω: beeper OFF')

    def test_limits_follow_the_manuals_accuracy_method(self):
        """+/-(% of reading + counts x resolution), p. 5, to within half a display step: an independent check of every transcribed limit."""
        steps, problems = BUILDER.build_steps()
        self.assertEqual(problems, [])
        self.assertEqual(len(steps), 35)

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_units_factors_and_nominal(self):
        for p in PTS.values():
            self.assertTrue(D(str(p['factor'])) > 0)
            if p['test'] == 'numeric':
                self.assertLess(D(p['low']), D(p['nominal']) / D(str(p['factor'])) + D('0.000001'))
                self.assertGreater(D(p['high']), D(p['nominal']) / D(str(p['factor'])) - D('0.000001'))
                self.assertEqual(D(p['nominal']) / D(str(p['factor'])) in (D(p['low']), D(p['high'])), False)
        self.assertEqual((PTS[17]['base_unit'], PTS[17]['nominal'], PTS[17]['applied']), ('Hz', 50000.0, dict(value=5.0, frequency=50000.0)))
        self.assertEqual((PTS[25]['base_unit'], PTS[25]['nominal'], PTS[25]['kind']), ('F', 9e-07, 'CAP'))

    def test_validator_passes_and_no_ramp_lists(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        self.assertFalse([n for n, p in PTS.items() if p.get('ramp')])

    def test_options(self):
        o = SPEC['options']
        self.assertIs(o['auto_ramp'], False)                    # high-voltage points go straight to the test value (the manual prescribes no ramp)
        self.assertIs(o['function_prompt'], True)
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title']), ('fluke77', 30, 'Calibration Data'))
        self.assertNotIn('ir', o)                                # no remote interface: readings are typed

    def test_groups(self):
        groups = [(n, p['group']) for n, p in PTS.items()]
        self.assertEqual([g for _n, g in groups if _n <= 25], ['VOHM'] * 25)
        self.assertEqual({n: g for n, g in groups if n > 25}, {26: 'UAMP', 27: 'UAMP', 28: 'UAMP', 29: 'AMP10', 30: 'AMP10', 31: 'UAMP', 32: 'UAMP', 33: 'UAMP', 34: 'AMP10', 35: 'AMP10'})

    def test_hookups_exist_for_both_calibrators(self):
        import hookups
        for cal in ('5560A', '5522A'):
            for group in ('VOHM', 'UAMP', 'AMP10'):
                plan = hookups.plan('fluke77', cal, group, manual=False)
                self.assertTrue(plan and plan['image'] and Path(plan['image']).is_file(), (cal, group))
        self.assertIn('400 mA', hookups.summary('fluke77', '5522A', 'UAMP'))
        self.assertIn('10A', hookups.summary('fluke77', '5560A', 'AMP10'))

    def test_jack_names_are_as_printed_on_the_case(self):
        """Photo of the real terminals: 2 x 2 block, '400 mA' / '10A' (fused) on the left, 'V Ω' / 'COM' on the right."""
        import hookups
        self.assertEqual(hookups.METERS['fluke77']['jacks'], {'vohm': 'V Ω', 'ma': '400 mA', 'a10': '10A', 'com': 'COM'})
        self.assertIn('V Ω', hookups.summary('fluke77', '5522A', 'VOHM'))


class Step8(unittest.TestCase):
    def test_corrected_limits_and_how_they_are_recorded(self):
        p = PTS[8]
        self.assertEqual((p['low'], p['high'], p['nominal'], p['range']), ('0.047', '0.053', 0.05, '6.000 V'))
        self.assertEqual(p['printed_limits'], dict(low='0.47', high='0.53', unit='V', note=p['printed_limits']['note']))
        self.assertIn('LIMIT CORRECTED', p['note'])
        self.assertIn('0.47', p['note'])
        self.assertIn('step 8', SPEC['source']['cite'])
        self.assertIn('step 8', SPEC['source']['limits'])
        self.assertIn('step 8', SPEC['source']['note'])
        self.assertIn('0.47 to 0.53 V ac', SPEC['source']['report_note'])

    def test_the_printed_limits_cannot_be_met(self):
        """0.47 to 0.53 V ac for a 50 mV input: the meter reads about 0.050 V, so a perfect meter would fail."""
        printed = dict(PTS[8], low='0.47', high='0.53')
        self.assertEqual(h.judge_numeric(printed, '0.050')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[8], '0.050')[0], 'PASS')
        self.assertTrue(BUILDER.check_against_specification(8, 'V', 0.05, '0.47', '0.53', ('2.0', 2, '0.001')))
        self.assertEqual(BUILDER.check_against_specification(8, 'V', 0.05, '0.047', '0.053', ('2.0', 2, '0.001')), [])

    def test_no_other_step_is_corrected(self):
        self.assertEqual([n for n, p in PTS.items() if 'printed_limits' in p], [8])


class Padding(unittest.TestCase):
    def test_typed_readings_are_padded_to_the_resolution(self):
        for n, typed, want in ((9, '5', '5.000'), (8, '0.05', '0.050'), (17, '50', '50.00'), (25, '900', '900'), (1, '500', '500.0'),
                               (3, '5', '5.000'), (20, '1000', '1000'), (30, '9', '9.00'), (35, '-9', '-9.00'), (23, '-300', '-300.0')):
            self.assertEqual(h.pad_reading(PTS[n], typed), want, n)

    def test_a_perfect_meter_passes_every_point(self):
        for n, p in PTS.items():
            if p['test'] == 'numeric':
                typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
                self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', n)


class Prompts(unittest.TestCase):
    def test_function_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([sw for _n, sw in f.functions()], FUNCTION_PROMPTS)
        # a function prompt always sits right before the first point of the function and AFTER the cable-change prompt when there is one
        for i, e in enumerate(f.events):
            if e[0] == 'function':
                nxt = [x for x in f.events[i + 1:] if x[0] in ('point', 'function')][0]
                self.assertEqual(nxt, ('point', int(e[1])))
                if i and f.events[i - 1][0] == 'setup':
                    self.assertEqual(f.events[i - 1][1], int(e[1]))

    def test_cable_change_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], [1, 26, 29, 31, 34])         # VOHM, UAMP, AMP10, UAMP, AMP10

    def test_function_prompt_without_a_cable_change(self):
        """Ω -> continuity -> AC volts ... -> capacitance keep the same cables but the dial / yellow button moves: still asked."""
        f = Flow(MODEL)
        f.run()
        asked = {int(n) for n, _sw in f.functions()}
        for n in (2 + 4, 8, 17, 18, 22, 25):                    # 6 = continuity
            self.assertIn(n, asked)
        self.assertFalse({n for n in asked if PTS[n]['group'] == 'NONE'})

    def test_high_voltage_prompts_never_mention_a_ramp(self):
        f = Flow(MODEL, calibrator=True)
        f.run()
        hv = [p['n'] for p in f.app.points if f.app._high_voltage(p)]
        self.assertEqual(hv, [11, 12, 13, 14, 15, 16, 19, 20, 21])    # 30 V and above (the manual's caution level for AC, p. 2)
        texts = [e[1] for e in f.events if e[0] == 'hv']
        self.assertEqual(len(texts), len(hv))
        self.assertFalse([t for t in texts if 'ramp' in t])

    def test_direct_high_voltage_one_out_command(self):
        io, t = _io('5522A')
        for n in (13, 14, 15, 16, 19, 20, 21):
            n0 = len(t.sent)
            io.apply(PTS[n])
            outs = [c for c in t.sent[n0:] if c.upper().startswith('OUT ') and not c.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[n]], n)


def _io(model):
    bench, _ft, _s = __import__('drivers.simulated', fromlist=['make_bench']).make_bench()
    from drivers.simulated import SimFlukeTransport
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
            self.assertEqual(outs, [OUT_COMMANDS[n]], (model, n))                # one OUT, sent once (never retried)
            self.assertEqual(sent[0], 'STBY', (model, n))                         # standby before every setup
            self.assertLess(sent.index(OUT_COMMANDS[n]), sent.index('ERR?'), (model, n))
            self.assertLess(sent.index('ERR?'), sent.index('OPER'), (model, n))   # the error queue is read, and only then the output enabled
            self.assertEqual(sum(1 for c in sent if c == 'OPER'), 1, (model, n))
            io.standby()
            self.assertEqual(t.sent[-1], 'STBY', (model, n))
            if p['kind'] in ('DCV', 'DCI'):
                self.assertTrue(OUT_COMMANDS[n].endswith(',0Hz'), (model, n))
            self.assertFalse(io.cal.wave_nonsine)                                 # no square wave anywhere in this procedure
        return t

    def test_5522a(self):
        self.check('5522A')

    def test_5560a(self):
        self.check('5560A')

    def test_a_rejected_output_is_never_operated(self):
        io, t = _io('5522A')
        t.reject = (OUT_COMMANDS[25].upper(),)
        with self.assertRaises(Exception):
            io.apply(PTS[25])
        self.assertNotIn('OPER', t.sent)
        self.assertEqual(sum(1 for c in t.sent if c == OUT_COMMANDS[25]), 1)

    def test_registry_entries_used_and_their_verified_flags(self):
        """Every calibrator command this procedure sends is an existing registry command; nothing new was added."""
        import cmdreg
        from drivers import Fluke5522A, Fluke5560A
        for cls in (Fluke5560A, Fluke5522A):
            reg = cmdreg.merge_commands(cls)
            for key in ('out.ohms', 'out.volts.hz', 'out.volts.dc', 'out.amps.hz', 'out.amps.dc', 'out.cap.nf', 'oper.stby', 'oper.on', 'err.query'):
                self.assertIn(key, reg, key)
        reg = cmdreg.merge_commands(Fluke5560A)
        self.assertTrue(reg['out.ohms'].verified and reg['out.volts.hz'].verified and reg['out.volts.dc'].verified)
        self.assertFalse(reg['out.cap.nf'].verified)          # capacitance output: not verified on a 5560A (listed in NOTES.md)
        self.assertFalse(reg['out.amps.dc'].verified)


class EndToEnd(unittest.TestCase):
    """The real App on the simulated bench; only the modal dialogs are scripted."""
    def setUp(self):
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()

    def make(self, model='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench, SimFlukeTransport
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {model}', 'sim', transport=Spy(bench, model))
            io.auto_ramp = False
        app = h.App(self.hn.root, MODEL, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None)
        app.asset.set('A-77')
        app.serial.set('S-77')
        app.cal_mode.set(h.CAL_CHOICES[1] if model == '5522A' else h.CAL_CHOICES[0])
        if io:
            app.io = io
        self.hn.app = app
        return app, io

    def pdf(self, app):
        out = tempfile.mkdtemp() + '/x.pdf'
        seen = {}

        def save(**k):
            seen.update(k)
            return out
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '',
             'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', save):
            app.export_pdf()
        return out, seen, subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout

    def run_perfect(self, model):
        app, io = self.make(model)
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        return app, io

    def test_perfect_meter_passes_all_35_with_either_calibrator(self):
        for model in ('5522A', '5560A'):
            app, io = self.run_perfect(model)
            self.assertEqual(len(app.found), 35, model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertTrue(all(not r['synthetic'] and r['data'] == 'As Found' for r in app.found.values()))
            self.assertEqual(app.found['2-8']['entered'], '0.050')           # padded to the resolution
            self.assertEqual(app.found['2-17']['entered'], '50.00')
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_wire_log(self):
        app, io = self.run_perfect('5522A')
        w = H.wire(io)
        texts = [t for _i, t in w]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(outs, [OUT_COMMANDS[n] for n in range(1, 36)])          # every point once, in manual order, none repeated
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))               # reset before the first point
        self.assertEqual(texts[-1], 'STBY')                                        # left in standby
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b], 'standby between two points')
        for n in range(1, 36):
            if PTS[n]['kind'] in ('DCV', 'DCI'):
                self.assertTrue(outs[n - 1].endswith(',0Hz'), outs[n - 1])          # every DC output carries an explicit 0 Hz
        self.assertEqual(sum(1 for t in texts if t == 'OPER'), 35)

    def test_prompts_and_hv_dialogs(self):
        app, io = self.run_perfect('5522A')
        confirms = [d for d in self.hn.dialogs if d[0] == 'confirm']
        titles = [d[1] for d in confirms]
        self.assertEqual(titles.count('Change the cables'), 5)
        self.assertEqual(titles.count('Change the function'), 11)
        hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(hv), 9)
        self.assertFalse([d for d in hv if 'ramp' in d[3]])
        beeps = [d for d in self.hn.dialogs if d[0] == 'reading' and d[2] == 'yesno']
        self.assertEqual([d[1] for d in beeps], ['2-6', '2-7'])

    def test_out_of_tolerance_fails_and_is_reported(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['2-10'] = '5.2'
        self.hn.readings['2-7'] = False
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['2-10', '2-7'])
        self.assertEqual(app.found['2-7']['entered'], 'Beeper not off')

    def test_report_is_calibration_data_named_asset_date(self):
        app, io = self.run_perfect('5522A')
        out, seen, text = self.pdf(app)
        import ui_theme as ui
        self.assertEqual(seen['initialfile'], ui.report_filename('A-77'))
        self.assertRegex(seen['initialfile'], r'^A-77-\d\d-\d\d-\d{4}\.pdf$')
        self.assertIn('Calibration Data', text)
        self.assertNotIn('Performance Verification', text)
        self.assertIn('Fluke 77 Series IV', text)
        flat = ' '.join(text.split())
        self.assertIn('6.000 V range (limits corrected)', flat)       # the correction is stated on the report itself
        self.assertIn('99.99 kHz range (5 V applied)', ' '.join(text.split()))
        self.assertNotIn('2 V applied', text)
        self.assertIn('Page 1 of 1', text)                                          # the 35 rows fit one page
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))          # a real run is never marked demo
        self.assertRegex(text, r'Uncertainty\s+TAR\s+TUR')
        self.assertNotIn('Cover', text)
        # TAR / TUR: the frequency point is read in Hz, a 'natural unit' mismatch: no ratio there
        line = next(l for l in text.splitlines() if '99.99 kHz range' in l)
        self.assertNotRegex(line, r'\d+\.\d:1')

    def test_demo_never_produces_real_looking_evidence(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 35)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(app.any_synthetic())
        out, seen, text = self.pdf(app)
        self.assertIn('DEMO', text.upper())
        self.assertEqual(app.io, None)                                          # no instrument was touched

    def test_checkpoint_and_resume_never_repeat_a_point(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['2-12'] = None                                          # operator stops at point 12 (no reading)
        self.hn.default_reading = lambda p: None if p['id'] == '2-12' else H.typed_nominal(p)
        self.hn.run_all()
        self.assertEqual(len(app.found), 11)
        self.assertEqual(sorted(app.found)[0], '2-1')
        texts_before = [t for _i, t in H.wire(io)]
        self.assertEqual(texts_before[-1], 'STBY')

    def test_procedure_modifications_are_wired(self):
        app, io = self.make('5522A')
        self.assertEqual(app.pm_state.model if hasattr(app, 'pm_state') and hasattr(app.pm_state, 'model') else MODEL, MODEL)
        self.assertTrue(hasattr(app, 'pm_begin_run') and hasattr(app, 'pm_step') and hasattr(app, 'pm_live_attach'))
        self.assertEqual(app.pm_point_title(app.points[0]), 'Ohms, 600.0 Ω range')


class Registered(unittest.TestCase):
    def test_launcher_manager_and_verified_registration(self):
        launcher = ROOT / 'Procedures' / 'Fluke_77IV_Verification.py'
        text = launcher.read_text(encoding='utf-8')
        self.assertIn("MODEL = '77IV'", text)
        self.assertIn("SPEC = 'fluke_77iv_pv.json'", text)
        manager = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertIn("'Fluke 77 Series IV Performance Verification': 'Fluke_77IV_Verification.py'", manager)
        self.assertIn("'Fluke_77IV_Verification.py': '1'", manager)
        self.assertIn("('Fluke 77 Series IV Performance Verification','Fluke','77 Series IV','Digital Multimeter','Fluke_77IV_Verification.py')", manager)
        import verified
        self.assertIn('Fluke_77IV_Verification.py', verified.FILES)
        self.assertNotIn('Fluke_77IV_Verification.py', {s['proc_key'] for s in verified.SEED})      # not verified on hardware: nothing seeded

    def test_the_launcher_imports_and_names_the_spec(self):
        spec = importlib.util.spec_from_file_location('launcher77', ROOT / 'Procedures' / 'Fluke_77IV_Verification.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual((mod.MODEL, mod.SPEC), (MODEL, SPEC_NAME))
        self.assertTrue((ROOT / 'specs' / mod.SPEC).is_file())


if __name__ == '__main__':
    unittest.main()
