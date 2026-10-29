"""Fluke 365 clamp meter performance verification (Procedures/Fluke_365_Verification.py -> handheld_dmm.main('365', spec=...), the shared handheld engine unchanged,
specs/fluke_365_pv.json built by specs/build_fluke_365_spec.py from the Calibration Manual, Table 2, printed pp. 7-8).

Part 1: the spec against an INDEPENDENT second transcription of Table 2 (read from the rendered page images at 170 and 260 dpi); the four rows whose printed limit is
not half of the published specification are flagged and NOT changed; the coil points (calibrator x 20 = meter); options; function / cable / high-voltage prompt sequences;
hook-ups; the sidecar (automated, i.e. kind verification) and its classification; one high-voltage question per hook-up group; current-point uncertainty (unscaled).
Part 2: the real engine (handheld_dmm.App, worker threads, drivers, judging, checkpoint, PDF) on the simulated bench with both calibrators
(5522A, 5560A): wire commands, explicit 0 Hz on DC, set / read back / never retried, standby after each point, reset first, demo never real.
tkinter is stubbed in setUpModule (not at import time), like tests/test_77_points.py, so tests.test_beta is loaded exactly as before.
Run:  python -m unittest tests.test_fluke_365_points"""
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
h = H = Flow = SPECS = Spy = SPEC = PTS = BUILDER = None
SPEC_NAME = 'fluke_365_pv.json'
MODEL = '365'

# Table 2 as read a second time from the page images: step -> (calibrator output as the engine words it, lower limit, upper limit)
TABLE_2 = {
    1: ('30 V AC @ 50 Hz', '29.5', '30.5'), 2: ('300 V AC @ 50 Hz', '297.5', '302.5'), 3: ('570 V AC @ 50 Hz', '565.5', '574.5'),
    4: ('30 V AC @ 400 Hz', '29.5', '30.5'), 5: ('300 V AC @ 400 Hz', '297.5', '302.5'), 6: ('570 V AC @ 400 Hz', '565.5', '574.5'),
    7: ('0 V DC', '-0.3', '0.3'), 8: ('30 V DC', '29.6', '30.4'), 9: ('300 V DC', '298.2', '301.8'), 10: ('570 V DC', '566.9', '573.1'),
    11: ('-30 V DC', '-30.4', '-29.6'), 12: ('-300 V DC', '-301.8', '-298.2'), 13: ('-570 V DC', '-573.1', '-566.9'),
    14: ('0 Ω', '0.0', '0.3'), 15: ('30 Ω', '29.6', '30.4'), 16: ('300 Ω', '298.2', '301.8'), 17: ('570 Ω', '566.9', '573.1'),
    18: ('900 Ω', '894', '907'), 19: ('3 kΩ', '2982', '3018'), 20: ('5.7 kΩ', '5669', '5731'),
    21: ('500 mA AC @ 50 Hz', '9.6', '10.4'), 22: ('5 A AC @ 50 Hz', '98.7', '101.3'), 23: ('9.5 A AC @ 50 Hz', '187.5', '192.5'),
    24: ('500 mA AC @ 400 Hz', '9.6', '10.4'), 25: ('5 A AC @ 400 Hz', '98.5', '101.5'), 26: ('9.5 A AC @ 400 Hz', '187.4', '192.6'),
    27: ('500 mA DC', '9.6', '10.4'), 28: ('5 A DC', '98.7', '101.3'), 29: ('9.5 A DC', '187.5', '192.5'),
    30: ('-500 mA DC', '-10.4', '-9.6'), 31: ('-5 A DC', '-101.3', '-98.7'), 32: ('-9.5 A DC', '-192.5', '-187.5'),
}
# what the calibrator is sent for each step (both calibrators): the command, then every DC output with an explicit ,0Hz
OUT_COMMANDS = {
    1: 'OUT 30V,50Hz', 2: 'OUT 300V,50Hz', 3: 'OUT 570V,50Hz', 4: 'OUT 30V,400Hz', 5: 'OUT 300V,400Hz', 6: 'OUT 570V,400Hz',
    7: 'OUT 0V,0Hz', 8: 'OUT 30V,0Hz', 9: 'OUT 300V,0Hz', 10: 'OUT 570V,0Hz', 11: 'OUT -30V,0Hz', 12: 'OUT -300V,0Hz', 13: 'OUT -570V,0Hz',
    14: 'OUT 0OHM', 15: 'OUT 30OHM', 16: 'OUT 300OHM', 17: 'OUT 570OHM', 18: 'OUT 900OHM', 19: 'OUT 3000OHM', 20: 'OUT 5700OHM',
    21: 'OUT 0.5A,50Hz', 22: 'OUT 5A,50Hz', 23: 'OUT 9.5A,50Hz', 24: 'OUT 0.5A,400Hz', 25: 'OUT 5A,400Hz', 26: 'OUT 9.5A,400Hz',
    27: 'OUT 0.5A,0Hz', 28: 'OUT 5A,0Hz', 29: 'OUT 9.5A,0Hz', 30: 'OUT -0.5A,0Hz', 31: 'OUT -5A,0Hz', 32: 'OUT -9.5A,0Hz',
}
SECTION_COUNTS = {'AC volts': 6, 'DC volts': 7, 'Ohms': 7, 'AC amps': 6, 'DC amps': 6}
FUNCTION_PROMPTS = ['V~  (AC volts)', 'V⎓  (DC volts)', 'Ω  (ohms; the position shared with continuity)',
                    'A~  (AC amps, detachable jaw on the 20-turn coil)', 'A⎓  (DC amps, detachable jaw on the 20-turn coil)']
# the printed limit that is not half of the published specification (specs/build_fluke_365_spec.py): flagged, never changed
FLAGGED = (18, 23, 29, 32)


def setUpModule():
    """tkinter is stubbed here, not at import time (see tests/test_87v_points.py)."""
    global h, H, Flow, SPECS, Spy, SPEC, PTS, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy = _h, _H, _o.Flow, _o.SPECS, _o.Spy
    SPECS[MODEL] = SPEC_NAME                                     # the shared Flow helper looks the spec up by model; removed again in tearDownModule
    SPEC = h.load_spec(SPEC_NAME)
    PTS = {p['n']: p for p in h.points_for(SPEC, MODEL)}
    s = importlib.util.spec_from_file_location('build_fluke_365_spec', ROOT / 'specs' / 'build_fluke_365_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    SPECS.pop(MODEL, None)


class Spec(unittest.TestCase):
    def test_32_points_by_function(self):
        self.assertEqual(len(PTS), 32)
        counts = {}
        for p in PTS.values():
            counts[p['section']] = counts.get(p['section'], 0) + 1
        self.assertEqual(counts, SECTION_COUNTS)
        self.assertEqual([p['step'] for p in PTS.values()], list(range(1, 33)))        # manual order, no gaps
        self.assertEqual({p['id'] for p in PTS.values()}, {f'2-{n}' for n in range(1, 33)})
        self.assertTrue(all(p['test'] == 'numeric' for p in PTS.values()))

    def test_every_point_matches_table_2(self):
        for n, (out, low, high) in TABLE_2.items():
            p = PTS[n]
            self.assertEqual(h.output_text(p), out, n)
            self.assertEqual((p['low'], p['high']), (low, high), n)
        self.assertEqual(set(TABLE_2), set(PTS))
        self.assertEqual({p['models'][0] for p in PTS.values()}, {'365'})

    def test_limits_against_the_published_specification(self):
        """Every printed limit is inside the full specification (printed p. 5: +/-(% of reading + 5 digits)); every one is half of it to within half a display
        step except the four flagged rows, which are stored AS PRINTED with the disagreement recorded."""
        steps, problems, flagged = BUILDER.build_steps()
        self.assertEqual(problems, [])                              # none looser than the specification
        self.assertEqual([f[0] for f in flagged], [f'2-{n}' for n in FLAGGED])
        self.assertEqual([n for n, p in PTS.items() if 'check' in p], list(FLAGGED))
        # the 900 ohm lower limit: 6 below the nominal, the pattern gives 7 (printed 894, pattern 893); the three 190 A rows: +/-2.5, the pattern gives 2.15
        self.assertEqual(PTS[18]['check']['printed_vs_spec'], [dict(side='low', printed='6', half_spec='7', full_spec='14')])
        for n in (23, 29, 32):
            self.assertEqual([(c['printed'], c['half_spec'], c['full_spec']) for c in PTS[n]['check']['printed_vs_spec']], [('2.5', '2.15', '4.3')] * 2)
            self.assertIn('CHECK (printed limit not changed)', PTS[n]['note'])
        for n in FLAGGED:                                            # printed limits kept: nothing was corrected
            self.assertEqual((PTS[n]['low'], PTS[n]['high']), TABLE_2[n][1:], n)
            self.assertNotIn('printed_limits', PTS[n])
        self.assertFalse([n for n, p in PTS.items() if 'printed_limits' in p])

    def test_builder_rejects_a_limit_looser_than_the_specification(self):
        problems, _info = BUILDER.check_row('x', '30', '28.9', '31.1', BUILDER.ACC['ACV'], '0.1')       # +/-1.1 V: wider than +/-0.95 V
        self.assertTrue(problems)
        self.assertEqual(BUILDER.check_row('x', '30', '29.5', '30.5', BUILDER.ACC['ACV'], '0.1'), ([], []))

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_the_coil_points(self):
        """Table 2 p. 8: the calibrator drives a 20-turn coil and the limits are meter readings (20 x the calibrator current)."""
        for n, p in PTS.items():
            if p['kind'] in ('ACI', 'DCI'):
                self.assertEqual(D(str(p['applied']['value'])) * 20, D(str(p['nominal'])), n)
                self.assertNotIn('no_uncertainty', p, n)             # every current point carries the calibrator's current uncertainty (unscaled)
                self.assertIn('NOT multiplied by 20', p['note'], n)
                self.assertEqual(p['report_desc'], f'200.0 A, {D(str(p["applied"]["value"])).normalize():f} A x 20 turns')
                self.assertIn('20-turn coil', h.describe(p))
                self.assertEqual(p['range'], '200.0 A')
            else:
                self.assertNotIn('no_uncertainty', p)
                self.assertEqual(D(str(p['applied']['value'])), D(str(p['nominal'])), n)

    def test_units_resolutions_and_ranges(self):
        for n, p in PTS.items():
            self.assertEqual(p['factor'], 1.0)
            self.assertEqual({'V': 'V', 'Ω': 'ohm', 'A': 'A'}[p['display_unit']], p['base_unit'])
        self.assertEqual({p['range'] for p in PTS.values() if p['section'] == 'Ohms'}, {'600.0 Ω', '6000 Ω'})
        self.assertEqual([p['range'] for n, p in PTS.items() if p['section'] == 'Ohms'], ['600.0 Ω'] * 4 + ['6000 Ω'] * 3)
        self.assertEqual(PTS[14]['low'], '0.0')                      # printed '0'; written at the display resolution, the same number (printed_text keeps the print)
        self.assertEqual(PTS[14]['printed_text']['low'], '0')

    def test_validator_passes_and_no_ramp_lists(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        self.assertFalse([n for n, p in PTS.items() if p.get('ramp')])

    def test_options(self):
        o = SPEC['options']
        self.assertIs(o['auto_ramp'], False)                    # high-voltage points go straight to the test value (the manual prescribes no ramp)
        self.assertIs(o['function_prompt'], True)
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title']), ('fluke365', 30, 'Calibration Data'))
        self.assertNotIn('ir', o)                                # no remote interface: readings are typed

    def test_groups(self):
        self.assertEqual({n: p['group'] for n, p in PTS.items() if n > 20},
                         {21: 'COIL_AUX', 22: 'COIL_20A', 23: 'COIL_20A', 24: 'COIL_AUX', 25: 'COIL_20A', 26: 'COIL_20A',
                          27: 'COIL_AUX', 28: 'COIL_20A', 29: 'COIL_20A', 30: 'COIL_AUX', 31: 'COIL_20A', 32: 'COIL_20A'})
        self.assertEqual({p['group'] for n, p in PTS.items() if n <= 20}, {'VOHM'})
        self.assertEqual(set(SPEC['groups']), {'COIL_AUX', 'COIL_20A'})

    def test_hookups_voltage_ohms_for_both_calibrators_and_coil_groups_from_the_spec(self):
        import hookups
        for cal in ('5560A', '5522A'):
            plan = hookups.plan('fluke365', cal, 'VOHM', manual=False)
            self.assertTrue(plan and plan['steps'] and plan['caution'], cal)        # the diagram PNG itself is supplied by the owner (diagrams/README_fluke365.txt)
            self.assertIn('VΩ', hookups.summary('fluke365', cal, 'VOHM'))
        self.assertFalse(hookups.has('fluke365', 'COIL_AUX') or hookups.has('fluke365', 'COIL_20A'))      # coil hook-ups are the spec's own groups
        for g in SPEC['groups'].values():
            text = ' '.join(' '.join(s) for s in g['steps'])
            self.assertIn('REMOVE the test leads', text)          # Safety Information p. 2: no current measurement with the leads in the jacks
            self.assertIn('ALL 20 turns', text)
            self.assertIn('UNVERIFIED', text)
            self.assertTrue(g['diagram'].startswith('diagrams/hook_fluke365_COIL_'))

    def test_readme_names_every_expected_diagram(self):
        text = (ROOT / 'diagrams' / 'README_fluke365.txt').read_text(encoding='utf-8')
        for name in ('hook_fluke365_5560A_VOHM.png', 'hook_fluke365_5522A_VOHM.png', 'hook_fluke365_COIL_AUX.png', 'hook_fluke365_COIL_20A.png'):
            self.assertIn(name, text)
        self.assertFalse(list((ROOT / 'diagrams').glob('hook_fluke365*')))       # diagrams are supplied by the owner: none is invented

    def test_sidecar_is_an_automated_verification(self):
        import procscan
        p = next(x for x in procscan.procs(ROOT) if x.id == 'Fluke_365_Verification')
        self.assertEqual(p.effective_kind, 'verification')
        self.assertNotIn('Manual', p.name)
        self.assertEqual((p.hookup_meter, p.diagram_prefixes), ('fluke365', ('hook_fluke365',)))
        self.assertIn('hookups.py#fluke365', p.fingerprint_code)         # only this meter's slice of hookups.py: no other procedure is touched
        self.assertEqual(p.specs, ('specs/fluke_365_pv.json',))
        for rel in p.own_files:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertTrue((ROOT / p.launcher).is_file())

    def test_the_launcher_names_the_engine(self):
        text = (ROOT / 'Procedures' / 'Fluke_365_Verification.py').read_text(encoding='utf-8')
        self.assertIn('handheld_dmm.main(MODEL, spec=SPEC)', text)
        self.assertIn("SPEC = 'fluke_365_pv.json'", text)
        self.assertFalse((ROOT / 'fluke365_verification.py').exists())         # no 365-only engine fork
        self.assertIs(h.App.QUEUE_SUPPORTED, True)               # the run queue is on, as for the other handhelds


class Padding(unittest.TestCase):
    def test_typed_readings_are_padded_to_the_resolution(self):
        for n, typed, want in ((1, '30', '30.0'), (3, '570', '570.0'), (7, '0', '0.0'), (11, '-30', '-30.0'), (14, '0', '0.0'), (19, '3000', '3000'),
                               (21, '10', '10.0'), (23, '190', '190.0'), (32, '-190', '-190.0')):
            self.assertEqual(h.pad_reading(PTS[n], typed), want, n)

    def test_a_perfect_meter_passes_every_point(self):
        for n, p in PTS.items():
            typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
            self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', n)

    def test_judging_is_exact_at_the_printed_limits(self):
        self.assertEqual(h.judge_numeric(PTS[1], '30.5')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[1], '30.6')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[14], '0.3')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[14], '0.4')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[18], '893')[0], 'FAIL')          # the printed lower limit is judged, not the specification pattern's 893
        self.assertEqual(h.judge_numeric(PTS[18], '894')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[23], '187.4')[0], 'FAIL')        # 190 A: printed 187.5 .. 192.5, unchanged
        self.assertEqual(h.judge_numeric(PTS[23], '192.5')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[32], '-192.5')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[32], '-192.6')[0], 'FAIL')


class Prompts(unittest.TestCase):
    def test_function_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([sw for _n, sw in f.functions()], FUNCTION_PROMPTS)
        self.assertEqual([int(n) for n, _sw in f.functions()], [1, 7, 14, 21, 27])
        for i, e in enumerate(f.events):
            if e[0] == 'function':
                nxt = [x for x in f.events[i + 1:] if x[0] in ('point', 'function')][0]
                self.assertEqual(nxt, ('point', int(e[1])))
                if i and f.events[i - 1][0] == 'setup':
                    self.assertEqual(f.events[i - 1][1], int(e[1]))          # the cable change comes first, then the dial

    def test_cable_change_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], [1, 21, 22, 24, 25, 27, 28, 30, 31])       # VOHM, then the coil moves between AUX and 20 A

    def test_no_double_function_prompt(self):
        f = Flow(MODEL)
        f.run()
        seq = [sw for _n, sw in f.functions()]
        self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])))

    def test_high_voltage_prompts_never_mention_a_ramp(self):
        f = Flow(MODEL, calibrator=True)
        f.run()
        hv = [p['n'] for p in f.app.points if f.app._high_voltage(p)]
        self.assertEqual(hv, [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13])     # 30 V and above: the manual's shock level is 30 V ac rms / 60 V dc (Safety Information p. 2)
        texts = [e[1] for e in f.events if e[0] == 'hv']
        self.assertEqual(len(texts), 1)
        self.assertFalse([t for t in texts if 'ramp' in t])

    def test_direct_high_voltage_one_out_command(self):
        io, t = _io('5522A')
        for n in (3, 6, 10, 13):
            n0 = len(t.sent)
            io.apply(PTS[n])
            outs = [c for c in t.sent[n0:] if c.upper().startswith('OUT ') and not c.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[n]], n)


def _io(model):
    bench, _ft, _s = __import__('drivers.simulated', fromlist=['make_bench']).make_bench()
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
        t.reject = (OUT_COMMANDS[23].upper(),)
        with self.assertRaises(Exception):
            io.apply(PTS[23])
        self.assertNotIn('OPER', t.sent)
        self.assertEqual(sum(1 for c in t.sent if c == OUT_COMMANDS[23]), 1)

    def test_every_output_is_inside_the_published_calibrator_specifications(self):
        """calibrator_fit: the 5522A, the 5520A and the 5560A sheets cover all 32 outputs (the coil is NOT part of that check: it is UNVERIFIED)."""
        import calibrator_fit as cf
        reqs = cf.handheld_requests(list(PTS.values()))
        self.assertEqual(len(reqs), 32)
        for model in ('5522A', '5520A', '5560A'):
            self.assertEqual([r for r in reqs if not cf.check(model, r).ok], [], model)

    def test_no_new_calibrator_command(self):
        """Every calibrator command this procedure sends is an existing registry command; nothing new was added."""
        import cmdreg
        from drivers import Fluke5522A, Fluke5560A
        for cls in (Fluke5560A, Fluke5522A):
            reg = cmdreg.merge_commands(cls)
            for key in ('out.ohms', 'out.volts.hz', 'out.volts.dc', 'out.amps.hz', 'out.amps.dc', 'oper.stby', 'oper.on', 'err.query'):
                self.assertIn(key, reg, key)
        reg = cmdreg.merge_commands(Fluke5560A)
        self.assertTrue(reg['out.ohms'].verified and reg['out.volts.hz'].verified and reg['out.volts.dc'].verified)
        self.assertFalse(reg['out.amps.dc'].verified)                              # current outputs on a 5560A: not verified (listed in NOTES.md)


class EndToEnd(unittest.TestCase):
    """The real App on the simulated bench; only the modal dialogs are scripted."""
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
        app.asset.set('A-365')
        app.serial.set('S-365')
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

    def test_perfect_meter_passes_all_32_with_either_calibrator(self):
        for model in ('5522A', '5560A'):
            app, io = self.run_perfect(model)
            self.assertEqual(len(app.found), 32, model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertTrue(all(not r['synthetic'] and r['data'] == 'As Found' and r['source'] == 'typed' for r in app.found.values()))
            self.assertEqual(app.found['2-1']['entered'], '30.0')           # padded to the resolution
            self.assertEqual(app.found['2-19']['entered'], '3000')
            self.assertEqual(app.found['2-32']['entered'], '-190.0')
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_wire_log(self):
        app, io = self.run_perfect('5522A')
        texts = [t for _i, t in H.wire(io)]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(outs, [OUT_COMMANDS[n] for n in range(1, 33)])          # every point once, in manual order, none repeated
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))               # reset before the first point
        self.assertEqual(texts[-1], 'STBY')                                        # left in standby
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b], 'standby between two points')
        for n in range(1, 33):
            if PTS[n]['kind'] in ('DCV', 'DCI'):
                self.assertTrue(outs[n - 1].endswith(',0Hz'), outs[n - 1])          # every DC output carries an explicit 0 Hz
        self.assertEqual(sum(1 for t in texts if t == 'OPER'), 32)

    def test_prompts_and_hv_dialogs(self):
        app, io = self.run_perfect('5522A')
        titles = [d[1] for d in self.hn.dialogs if d[0] == 'confirm']
        self.assertEqual(titles.count('Change the cables'), 9)
        self.assertEqual(titles.count('Change the function'), 5)
        hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(hv), 1)                                   # options.hv_once_per_group: ONE question for the VOHM hook-up group (was 12, one per point)
        self.assertFalse([d for d in hv if 'ramp' in d[3]])
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
        self.assertEqual(sum(1 for d in cables if 'REMOVE the test leads' in ' '.join(d[3])), 8)       # every coil hook-up says so (VOHM is the first)
        self.assertEqual(len([d for d in self.hn.dialogs if d[0] == 'reading']), 32)

    def test_out_of_tolerance_fails_and_is_reported(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['2-3'] = '575.0'
        self.hn.readings['2-23'] = '187.4'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['2-23', '2-3'])

    def test_report_is_calibration_data_named_asset_date(self):
        app, io = self.run_perfect('5522A')
        out, seen, text = self.pdf(app)
        import ui_theme as ui
        self.assertEqual(seen['initialfile'], ui.report_filename('A-365'))
        self.assertRegex(seen['initialfile'], r'^A-365-\d\d-\d\d-\d{4}\.pdf$')
        self.assertIn('Calibration Data', text)
        self.assertNotIn('Performance Verification', text)
        self.assertIn('Fluke 365', text)
        flat = ' '.join(text.split())
        self.assertIn('200.0 A, 9.5 A x 20 turns', flat)
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))          # a real run is never marked demo
        self.assertRegex(text, r'Uncertainty\s+TAR\s+TUR')
        self.assertNotIn('Cover', text)
        self.assertNotIn('Due', text.replace('Due Date', ''))                      # no standards-due tracking on the report body
        # every one of the 32 points carries an uncertainty, TAR and TUR (the coil points: the calibrator's current uncertainty, unscaled)
        rows = app.certificate_rows()
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(r['Uncertainty'] != '' for r in rows), [r['Description'] for r in rows if not r['Uncertainty']])
        fields = [app.certificate_fields(p) for p in app.points]
        self.assertTrue(all(f['TAR'] != '' and f['TUR'] != '' for f in fields), fields)

    def test_current_uncertainty_is_the_calibrators_at_the_output_current_unscaled(self):
        """Owner-chosen convention: Uncertainty = the regular calibrator current uncertainty at point / 20 (no x20, no coil); TAR / TUR use it as it is."""
        import report_pdf
        app, io = self.run_perfect('5522A')
        rows = app.certificate_rows()
        for p, r in zip(app.points, rows):
            if p['kind'] in ('ACI', 'DCI'):
                q = dict(kind=p['kind'], nominal=p['applied']['value'], frequency=p['applied'].get('frequency'), unit='A', range=None)
                self.assertEqual(r['Uncertainty'], report_pdf.point_uncertainty(q, standard=app.calibrator_model()), p['n'])
                self.assertIn('NOT multiplied by 20', p['note'])
        self.assertFalse(set(PTS) - {p['n'] for p in app.points})

    def test_other_specs_keep_the_per_point_high_voltage_question(self):
        for name in ('fluke_77iv_pv.json', 'fluke_170_series_pv.json', 'fluke_110_series_pv.json'):
            self.assertNotIn('hv_once_per_group', json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8')).get('options', {}), name)
        self.assertIs(SPEC['options']['hv_once_per_group'], True)

    def test_demo_never_produces_real_looking_evidence(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 32)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(app.any_synthetic())
        out, seen, text = self.pdf(app)
        self.assertIn('DEMO', text.upper())



if __name__ == '__main__':
    unittest.main()
