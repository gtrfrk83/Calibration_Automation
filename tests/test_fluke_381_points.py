"""Fluke 381 remote display clamp meter performance verification (Procedures/Fluke_381_Verification.py -> iflex_option.main('381', spec='fluke_381_pv.json');
specs/fluke_381_pv.json built by specs/build_fluke_381_spec.py from the Calibration Manual, Table 3 (printed pp. 11-12) and Table 4 (printed p. 14)).

Part 1: the spec against an INDEPENDENT second transcription of both tables (read from the rendered page images at a different resolution), the 50-turn coil assignment (calibrator current x 50 =
meter reading, sign kept for DC), the single-wire 0 A point, the iFlex simulation voltages, the hook-up groups, the iFlex option, hook-ups, sidecar, launcher.
Part 2: the real engine on the simulated bench with the 5522A and 5560A: wire commands (explicit 0 Hz on DC, negative DC current, LCOMP on AC coil points only, standby after each point), a typed
reading judged exactly, the coil uncertainty, the report, demo marking, and a check that every point has an uncertainty.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_fluke_381_points"""
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
h = H = Flow = SPECS = Spy = SPEC = BUILDER = X = None
SPEC_NAME = 'fluke_381_pv.json'
MODEL = '381'

# Tables 3 and 4 as read a second time: (calibrator output as printed, low, high) in table order
TABLE = [
    ('20 V @ 20 Hz', '19.2', '20.8'), ('10 V @ 50 Hz', '9.4', '10.7'), ('600 V @ 50 Hz', '590.5', '609.5'), ('1000 V @ 50 Hz', '980', '1020'),
    ('10 V @ 500 Hz', '9.4', '10.7'), ('600 V @ 500 Hz', '590.5', '609.5'), ('1000 V @ 500 Hz', '980', '1020'),
    ('-1000 V', '-1015', '-985'), ('-600 V', '-606.5', '-593.5'), ('-10 V', '-10.6', '-9.4'), ('10 V', '9.4', '10.6'), ('600 V', '593.5', '606.5'), ('1000 V', '985', '1015'),
    ('0 Ω', '-0.5', '0.5'), ('10 Ω', '9.4', '10.6'), ('100 Ω', '98.5', '101.5'), ('590 Ω', '583.6', '596.4'), ('1000 Ω', '985', '1015'), ('3000 Ω', '2965', '3035'),
    ('6000 Ω', '5935', '6065'), ('10 kΩ', '9.85', '10.15'), ('30 kΩ', '29.65', '30.35'), ('60 kΩ', '59.35', '60.65'),
    ('0.2 A @ 50 Hz', '9.3', '10.7'), ('2 A @ 50 Hz', '97.5', '102.5'), ('12 A @ 50 Hz', '587.5', '612.5'), ('18 A @ 50 Hz', '881.5', '918.5'), ('19.5 A @ 50 Hz', '955.0', '995.0'),
    ('0.2 A @ 440 Hz', '9.0', '11.0'),
    ('-19.5 A', '-995.0', '-955.0'), ('-12 A', '-612.5', '-587.5'), ('-2 A', '-102.5', '-97.5'), ('-0.2 A', '-10.7', '-9.3'), ('0 A', '-0.5', '0.5'),
    ('0.2 A', '9.3', '10.7'), ('2 A', '97.5', '102.5'), ('12 A', '587.5', '612.5'), ('18 A', '881.5', '918.5'), ('19.5 A', '955.0', '995.0'),
    ('0.1 A @ 50 Hz', '49.3', '50.8'),
    ('0.2 A @ 50 Hz', '9.2', '10.8'), ('12 A @ 50 Hz', '581.5', '618.5'), ('19.9 A @ 50 Hz', '964.6', '1025.4'), ('75 mV @ 50 Hz', '2420', '2580'),
    ('0.2 A @ 500 Hz', '9.2', '10.8'), ('750 mV @ 500 Hz', '2420', '2580'), ('0.4 A @ 50 Hz', '49.3', '50.8'),
]
NOMINALS = ['20', '10', '600', '1000', '10', '600', '1000', '-1000', '-600', '-10', '10', '600', '1000', '0', '10', '100', '590', '1000', '3000', '6000', '10', '30', '60',
            '10', '100', '600', '900', '975', '10', '-975', '-600', '-100', '-10', '0', '10', '100', '600', '900', '975', '50', '10', '600', '995', '2500', '10', '2500', '50']
GROUPS = (['VOHM'] * 23 + ['COIL_AUX', 'COIL_AUX', 'COIL_20A', 'COIL_20A', 'COIL_20A', 'COIL_AUX']
          + ['COIL_20A', 'COIL_20A', 'COIL_AUX', 'COIL_AUX', 'WIRE_0A', 'COIL_AUX', 'COIL_AUX', 'COIL_20A', 'COIL_20A', 'COIL_20A'] + ['COIL_AUX']
          + ['IFLEX_COIL_AUX', 'IFLEX_COIL_20A', 'IFLEX_COIL_20A', 'IFLEX_SIM', 'IFLEX_COIL_AUX', 'IFLEX_SIM', 'IFLEX_COIL_AUX'])


def setUpModule():
    global h, H, Flow, SPECS, Spy, SPEC, BUILDER, X
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import iflex_option as _x
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy, X = _h, _H, _o.Flow, _o.SPECS, _o.Spy, _x
    SPECS[MODEL] = SPEC_NAME
    SPEC = h.load_spec(SPEC_NAME)
    s = importlib.util.spec_from_file_location('build_fluke_381_spec', ROOT / 'specs' / 'build_fluke_381_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    SPECS.pop(MODEL, None)


def pts():
    return h.points_for(SPEC, MODEL)


class Spec(unittest.TestCase):
    def test_47_rows_in_two_tables(self):
        self.assertEqual([s['step'] for s in SPEC['steps']], list(range(1, 48)))          # one running number: the engine orders points by it
        self.assertEqual([s['ref'] for s in SPEC['steps'][40:]], [f'T4 #{i}' for i in range(1, 8)])
        self.assertEqual(len(SPEC['steps']), 47)
        self.assertEqual([s['table'] for s in SPEC['steps']].count('3'), 40)
        self.assertEqual([s['table'] for s in SPEC['steps']].count('4'), 7)
        self.assertEqual(len({s['id'] for s in SPEC['steps']}), 47)
        self.assertEqual(len(pts()), 47)
        self.assertEqual(len([p for p in pts() if not p.get('include')]), 42)

    def test_every_row_matches_the_second_transcription(self):
        for step, (out, low, high), nom in zip(SPEC['steps'], TABLE, NOMINALS):
            self.assertEqual((step['low'], step['high']), (low, high), out)
            self.assertEqual(D(str(step['nominal'] / step['factor'])).normalize(), D(nom).normalize(), out)
            self.assertEqual(step['models'], ['381'])

    def test_calibrator_outputs_as_printed(self):
        want = [(20, 20), (10, 50), (600, 50), (1000, 50), (10, 500), (600, 500), (1000, 500)]
        self.assertEqual([(s['applied']['value'], s['applied']['frequency']) for s in SPEC['steps'][:7]], want)
        self.assertEqual([s['applied']['value'] for s in SPEC['steps'][7:13]], [-1000, -600, -10, 10, 600, 1000])
        self.assertEqual([s['applied']['value'] for s in SPEC['steps'][13:23]], [0, 10, 100, 590, 1000, 3000, 6000, 10000, 30000, 60000])
        ac = [(s['applied']['value'], s['applied']['frequency']) for s in SPEC['steps'][23:29]]
        self.assertEqual(ac, [(0.2, 50), (2, 50), (12, 50), (18, 50), (19.5, 50), (0.2, 440)])
        self.assertEqual([s['applied']['value'] for s in SPEC['steps'][29:39]], [-19.5, -12, -2, -0.2, 0, 0.2, 2, 12, 18, 19.5])
        self.assertTrue(all(s['applied']['frequency'] is None for s in SPEC['steps'][29:39]))
        self.assertEqual((SPEC['steps'][39]['applied']['value'], SPEC['steps'][39]['applied']['frequency']), (0.1, 50))
        ifx = [(s['applied']['value'], s['applied']['frequency'], s['kind']) for s in SPEC['steps'][40:]]
        self.assertEqual(ifx, [(0.2, 50, 'ACI'), (12, 50, 'ACI'), (19.9, 50, 'ACI'), (0.075, 50, 'ACV'), (0.2, 500, 'ACI'), (0.75, 500, 'ACV'), (0.4, 50, 'ACI')])

    def test_amps_rows_are_50_turns_of_the_calibrator_current(self):
        for s in SPEC['steps']:
            if s['kind'] in ('ACI', 'DCI') and s['display_unit'] == 'A' and s['group'] != 'WIRE_0A':
                self.assertEqual(D(str(s['nominal'])), D(str(s['applied']['value'])) * 50, s['id'])
                self.assertEqual(s['unc_standard'], 'A2LA-5500A-COIL')
                self.assertEqual(s['unc_nominal'], s['nominal'])
        self.assertEqual([s['nominal'] for s in SPEC['steps'] if s['kind'] == 'DCI' and s['applied']['value'] < 0], [-975, -600, -100, -10])

    def test_frequency_rows_through_the_coil(self):
        f = [s for s in SPEC['steps'] if s['display_unit'] == 'Hz']
        self.assertEqual([(s['id'], s['applied']['value'], s['nominal'], s['unc_kind'], s['group']) for s in f],
                         [('3-40', 0.1, 50, 'FREQ', 'COIL_AUX'), ('4-47', 0.4, 50, 'FREQ', 'IFLEX_COIL_AUX')])
        self.assertIn('trigger level', f[0]['note'])
        self.assertNotIn('unc_standard', f[0])

    def test_iflex_simulation_is_75_mv_at_50_hz_and_750_mv_at_500_hz(self):
        sim = [s for s in SPEC['steps'] if s['group'] == 'IFLEX_SIM']
        self.assertEqual([(s['applied']['value'], s['applied']['frequency'], s['nominal'], s['unc_unit']) for s in sim], [(0.075, 50, 2500, 'V'), (0.75, 500, 2500, 'V')])
        self.assertTrue(all('include' not in s for s in sim))                      # the simulation always runs
        self.assertEqual(sum(1 for s in SPEC['steps'] if s.get('include') == 'iflex'), 5)

    def test_zero_amp_point_is_a_single_wire_not_the_coil(self):
        z = SPEC['steps'][33]
        self.assertEqual((z['group'], z['applied']['value'], z['kind']), ('WIRE_0A', 0, 'DCI'))
        self.assertNotIn('unc_standard', z)
        self.assertIn('SINGLE WIRE', z['note'])
        self.assertIn('footnote [1]', z['note'])

    def test_groups(self):
        self.assertEqual([s['group'] for s in SPEC['steps']], GROUPS)
        self.assertEqual(set(GROUPS), set(SPEC['groups']) | {'VOHM'})

    def test_published_accuracy_cross_check(self):
        rounded = sorted(s['id'] for s in SPEC['steps'] if s.get('check'))
        self.assertEqual(rounded, ['3-2', '3-40', '3-5', '4-43', '4-47'])
        self.assertTrue(all(s['check']['verdict'] == 'rounded' for s in SPEC['steps'] if s.get('check')))
        for s in SPEC['steps']:
            if s.get('check'):
                self.assertIn('CHECK', s['note'])

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_builder_aborts_on_a_wrong_coil_ratio_or_limit(self):
        rows = list(BUILDER.ROWS)
        try:
            BUILDER.ROWS = [r if not (r[1] == 'AC amps' and r[5] == '12') else (*r[:8], '700', *r[9:]) for r in rows]
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
            BUILDER.ROWS = [r if not (r[1] == 'DC volts' and r[8] == '600') else (*r[:9], '593.0', '606.0', *r[11:]) for r in rows]      # neither the published accuracy nor a flagged rounding
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
        finally:
            BUILDER.ROWS = rows

    def test_hookups_and_diagrams_readme(self):
        import hookups
        for cal in ('5560A', '5522A'):
            plan = hookups.plan('fluke381', cal, 'VOHM', manual=False)
            self.assertTrue(plan and plan['steps'] and plan['caution'])
        self.assertEqual(SPEC['options']['hookup_meter'], 'fluke381')
        text = (ROOT / 'diagrams' / 'README_fluke381.txt').read_text(encoding='utf-8')
        for name in ('hook_fluke381_COIL_AUX.png', 'hook_fluke381_COIL_20A.png', 'hook_fluke381_WIRE_0A.png', 'hook_fluke381_IFLEX_SIM.png', 'hook_fluke381_IFLEX_COIL_AUX.png',
                     'hook_fluke381_IFLEX_COIL_20A.png', 'hook_fluke381_5560A_VOHM.png'):
            self.assertIn(name, text)
        for g in SPEC['groups'].values():
            self.assertTrue(g['diagram'].startswith('diagrams/hook_fluke381_'))
        self.assertEqual(list((ROOT / 'diagrams').glob('hook_fluke381_*.png')), [], 'diagrams are owner-supplied; none is invented here')

    def test_sidecar_and_launcher(self):
        d = json.loads((ROOT / 'Procedures' / 'Fluke_381_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((d['id'], d['model'], d['engine'], d['specs'], d['hookup']['meter'], d['category']),
                         ('Fluke_381_Verification', '381', ['handheld_dmm.py', 'iflex_option.py'], ['specs/fluke_381_pv.json'], 'fluke381', 'Clamp Meter'))
        self.assertIn('47 points', d['description'])
        src = (ROOT / 'Procedures' / 'Fluke_381_Verification.py').read_text(encoding='utf-8')
        self.assertIn("MODEL = '381'", src)
        self.assertIn("SPEC = 'fluke_381_pv.json'", src)
        self.assertIn('iflex_option.main(MODEL, spec=SPEC)', src)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()

    def make(self, cal='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {cal}', 'sim', transport=Spy(bench, cal))
            io.auto_ramp = False
        app = X.App(self.hn.root, MODEL, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
        app.asset.set('A-381'); app.serial.set('S-1')
        app.cal_mode.set(h.CAL_CHOICES[1] if cal == '5522A' else h.CAL_CHOICES[0])
        if io:
            app.io = io
        self.hn.app = app
        return app, io

    def run_perfect(self, cal='5522A'):
        app, io = self.make(cal)
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        return app, io

    def test_perfect_meter_passes_with_either_calibrator(self):
        for cal in ('5522A', '5560A'):
            app, io = self.run_perfect(cal)
            self.assertEqual(len(app.found), 47, cal)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, cal)
            self.assertTrue(all(not r['synthetic'] and r['source'] == 'typed' for r in app.found.values()))
            self.hn.stop(); self.hn = H.Harness().start()

    def test_wire_log_dc_zero_hz_negative_and_zero_amps(self):
        app, io = self.run_perfect()
        texts = [t for _i, t in H.wire(io)]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(len(outs), 47, outs)
        for want in ('OUT 20V,20Hz', 'OUT 1000V,500Hz', 'OUT -1000V,0Hz', 'OUT 0A,0Hz', 'OUT -19.5A,0Hz', 'OUT -0.2A,0Hz', 'OUT 19.9A,50Hz', 'OUT 0.2A,440Hz', 'OUT 0.1A,50Hz', 'OUT 0.4A,50Hz'):
            self.assertIn(want, outs)
        for o, p in zip(outs, pts()):
            if p['kind'] in ('DCV', 'DCI'):
                self.assertTrue(o.endswith(',0Hz'), o)
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))
        self.assertEqual(texts[-1], 'STBY')
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b])

    def test_lcomp_only_on_allowed_ac_coil_points_and_off_after(self):
        app, io = self.run_perfect()
        texts = [t for _i, t in H.wire(io)]
        ons = [i for i, t in enumerate(texts) if t == 'LCOMP ON']
        # AC coil points: jaw 0.2 / 2 / 12 / 18 / 19.5 A at 50 Hz, iFlex 0.2 / 12 / 19.9 A at 50 Hz, frequency 0.1 A and 0.4 A at 50 Hz; 440 Hz and 500 Hz are outside what the 5522A allows
        self.assertEqual(len(ons), 5 + 3 + 2)
        for i in ons:
            self.assertTrue(texts[i - 1].startswith('OUT '))
            self.assertEqual(texts[i + 1], 'LCOMP?')
            self.assertIn('OPER', texts[i + 1:i + 8])
        self.assertEqual(sum(1 for t in texts if t == 'LCOMP OFF'), len(ons))
        for i in ons:
            self.assertNotIn(texts[i - 1], ('OUT 0.2A,440Hz', 'OUT 0.2A,500Hz'))
            self.assertFalse(texts[i - 1].endswith(',0Hz'))
        self.assertEqual(texts[-1], 'STBY')

    def test_5560a_gets_no_lcomp_command(self):
        app, io = self.run_perfect('5560A')
        self.assertFalse(any(t.startswith('LCOMP') for _i, t in H.wire(io)))

    def test_cable_change_prompts_follow_the_group_changes(self):
        app, io = self.run_perfect()
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
        self.assertEqual(len(cables), 1 + sum(1 for a, b in zip(GROUPS, GROUPS[1:]) if a != b))

    def test_coil_point_uncertainty_is_the_coil_rule(self):
        import report_pdf
        app, io = self.run_perfect()
        rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
        for p in app.points:
            if p.get('unc_standard'):
                nom, std = X.App.unc_source(p)
                q = dict(kind=p['kind'], nominal=nom, frequency=p['applied']['frequency'], unit=p['base_unit'], range=None, extra=X.App.unc_extra(p))
                if X.App.unc_scale(p) != 1.0:
                    q['scale'] = X.App.unc_scale(p)
                self.assertEqual(rows[p['id']]['Uncertainty'], report_pdf.point_uncertainty(q, standard=std or app.calibrator_model()), p['id'])
        covered = {p['id']: X.App.unc_source(p)[1] for p in app.points if p.get('unc_standard')}
        self.assertEqual(covered['3-25'], 'A2LA-5500A-COIL')            # 100 A (2 A x 50)
        self.assertIsNone(covered['3-24'])                              # 10 A AC: below the coil's 20.5 A: the calibrator
        self.assertEqual(covered['3-30'], 'A2LA-5500A-COIL')            # -975 A dc
        self.assertEqual(covered['3-35'], 'A2LA-5500A-COIL')            # +10 A dc

    def test_points_without_an_uncertainty_are_exactly_the_known_list(self):
        """Owner instruction: a point that should carry an uncertainty and has none is reported, never invented.  The only point without one is the 0 A dc point, by owner decision
        (no_uncertainty, 2026-10-26)."""
        for cal in ('5522A', '5560A'):
            app, io = self.run_perfect(cal)
            missing = [(p['id'], p['kind']) for p, r in zip(app.points, app.certificate_rows()) if not str(r.get('Uncertainty') or '').strip()]
            self.assertEqual(missing, [('3-34', 'DCI')], cal)
            z = [p for p in app.points if p['id'] == '3-34'][0]
            self.assertTrue(z['no_uncertainty'])
            self.assertIn('NO UNCERTAINTY', z['note'])
            self.hn.stop(); self.hn = H.Harness().start()

    def test_frequency_rows_use_the_calibrators_own_frequency_specification(self):
        """Owner decision 2026-10-26 (all handheld engines): 3-40 and 4-47 are the calibrator's OUTPUT frequency, so its published frequency specification is the uncertainty."""
        want = {'5522A': '5.8 mHz', '5560A': '130 µHz'}
        for cal, text in want.items():
            app, io = self.run_perfect(cal)
            rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
            for pid in ('3-40', '4-47'):
                self.assertEqual(rows[pid]['Uncertainty'], text, (cal, pid))
            fields = [app.certificate_fields(p) for p in app.points if p['id'] in ('3-40', '4-47')]
            self.assertTrue(all(f.get('TUR') for f in fields), fields)
            self.hn.stop(); self.hn = H.Harness().start()

    def test_the_frequency_rule_is_one_switch_and_bench_engines_are_unchanged(self):
        """The calibrator-frequency rule is the handheld default behind h.FREQ_UNCERTAINTY_FROM_CALIBRATOR; off gives the old CMC-alone figures; report_pdf's default is the old rule."""
        import report_pdf
        q = dict(kind='FREQ', nominal=50.0, frequency=None, unit='Hz', range=None)
        base = report_pdf.point_uncertainty(q, standard='5522A')
        self.assertEqual(base, report_pdf.point_uncertainty(q))                       # report_pdf default (bench engines): CMC alone, whatever the calibrator
        self.assertNotEqual(base, report_pdf.point_uncertainty(dict(q, use_standard=True), standard='5522A'))
        self.assertTrue(h.FREQ_UNCERTAINTY_FROM_CALIBRATOR)
        h.FREQ_UNCERTAINTY_FROM_CALIBRATOR = False
        try:
            app, io = self.run_perfect('5522A')
            rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
            self.assertEqual({rows[i]['Uncertainty'] for i in ('3-40', '4-47')}, {base})
        finally:
            h.FREQ_UNCERTAINTY_FROM_CALIBRATOR = True

    def test_out_of_tolerance_fails_and_exact_limit_passes(self):
        app, io = self.make()
        point = [p for p in pts() if p['id'] == '3-26'][0]          # 12 A x 50 = 600 A, limits 587.5 .. 612.5
        self.hn.default_reading = lambda p: (p['high'] if p['n'] != point['n'] else '612.6')      # every other point exactly on its high limit
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found[point['id']]['result'], 'FAIL')
        self.assertEqual({r['result'] for k, r in app.found.items() if k != point['id']}, {'PASS'})

    def test_sign_matters_on_dc_amps(self):
        app, io = self.make()
        self.hn.default_reading = lambda p: ('975' if p['id'] == '3-30' else H.typed_nominal(p))     # the -975 A point typed without the sign
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['3-30']['result'], 'FAIL')

    def test_report_is_calibration_data_with_the_source_note(self):
        app, io = self.run_perfect()
        out = tempfile.mkdtemp() + '/x.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        self.assertIn('Calibration Data', text)
        self.assertIn('Tables 3 and 4', app.source_note())

    def test_iflex_option_default_on_and_simulation_points_always_run(self):
        """Owner 2026-10-26: the procedure has the iFlex window option of the 376 (default ON); turning it OFF removes the 5 iFlex-through-coil points and NEVER the 2 simulation points."""
        app, io = self.make()
        self.assertEqual(SPEC['options']['include_toggles'][0]['id'], 'iflex')
        self.assertTrue(SPEC['options']['include_toggles'][0]['default'])
        self.assertTrue(app.include_is_on('iflex'))                                  # default ON
        self.assertEqual(len(app.points), 47)
        self.assertTrue(app.set_include('iflex', False, ask=False))
        self.assertFalse(app.include_is_on('iflex'))
        self.assertEqual(len(app.points), 42)
        ids = {p['id'] for p in app.points}
        self.assertTrue({'4-44', '4-46'} <= ids)                                    # the 75 mV / 50 Hz and 750 mV / 500 Hz simulation points stay
        self.assertEqual({p['id'] for p in SPEC['steps'] if p.get('include') == 'iflex'} & ids, set())
        self.assertEqual(sorted({p['id'] for p in SPEC['steps'] if p.get('include') == 'iflex'}), ['4-41', '4-42', '4-43', '4-45', '4-47'])
        self.assertEqual([p['applied']['value'] for p in app.points if p['group'] == 'IFLEX_SIM'], [0.075, 0.75])
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        outs = [t for _i, t in H.wire(io) if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(len(outs), 42)
        self.assertTrue(any(o.startswith('OUT 0.075V,50Hz') for o in outs), outs)
        self.assertTrue(any(o.startswith('OUT 0.75V,500Hz') for o in outs), outs)
        self.assertFalse(any(o in ('OUT 19.9A,50Hz', 'OUT 0.4A,50Hz') for o in outs))

    def test_the_far_left_jack_is_owner_confirmed(self):
        g = SPEC['groups']['IFLEX_SIM']
        text = ' '.join(t for _a, t in g['steps'])
        self.assertIn('owner-confirmed', text)
        self.assertNotIn('UNVERIFIED', text)
        self.assertIn('owner-confirmed', [s for s in SPEC['steps'] if s['group'] == 'IFLEX_SIM'][0]['note'])

    def test_demo_is_marked_and_never_real(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertTrue(app.any_synthetic())
        self.assertEqual(len(app.found), 47)


if __name__ == '__main__':
    unittest.main()
