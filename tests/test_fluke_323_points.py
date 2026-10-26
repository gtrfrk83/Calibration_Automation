"""Fluke 323 / 324 / 325 clamp meter performance verification (Procedures/Fluke_32x_Verification.py -> handheld_dmm.main(MODEL, spec='fluke_323_pv.json');
specs/fluke_323_pv.json built by specs/build_fluke_323_spec.py from the Calibration Manual, Table 4, printed pp. 13-14).

Part 1: the spec against an INDEPENDENT second transcription of Table 4 (read from the rendered page images, twice), the X / N/A model columns, the printed misprint of the 30K ohm row,
the 50-turn coil assignment of every current row AND of the three frequency rows (calibrator current x 50 = meter reading), the hook-up groups (below 3 A the low-current output, 3 A and
above the 20 A / 30 A output), hook-ups, sidecars, launchers.
Part 2: the real engine (handheld_dmm.App) on the simulated bench with the 5522A and 5560A, one run per model: wire commands, explicit 0 Hz on DC, standby after each point, a typed
reading judged exactly, the PDF report.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_fluke_323_points"""
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
h = H = Flow = SPECS = Spy = SPEC = BUILDER = None
SPEC_NAME = 'fluke_323_pv.json'
MODELS = ('323', '324', '325')
COUNTS = {'323': 16, '324': 24, '325': 30}

# Table 4 as read a second time: (calibrator output as printed, models as X / N/A for 323 324 325, low, high) in table order
TABLE_4 = [
    ('-5 °C', 'NXX', '-5.8', '-4.2'), ('0 °C', 'NXX', '-0.8', '0.8'), ('100 °C', 'NXX', '98.2', '101.8'), ('400 °C', 'NXX', '395.2', '404.8'),
    ('10 V @ 50 Hz', 'XXX', '9.3', '10.7'), ('500 V @ 50 Hz', 'NXX', '492.0', '508.0'), ('500 V @ 500 Hz', 'NXX', '492.0', '508.0'),
    ('600 V @ 50 Hz', 'XNN', '590.5', '609.5'), ('600 V @ 400 Hz', 'XNN', '590.5', '609.5'),
    ('-600 V', 'XNN', '-606.5', '-593.5'), ('-500 V', 'NXX', '-505.5', '-494.5'), ('10 V', 'XXX', '9.4', '10.6'), ('500 V', 'NXX', '494.5', '505.5'), ('600 V', 'XNN', '593.5', '606.5'),
    ('0 Ω', 'XNN', '0.0', '0.5'), ('10 Ω', 'XXX', '9.4', '10.6'), ('300 Ω', 'NXX', '296.5', '303.5'), ('350 Ω', 'XNN', '346.0', '354.0'), ('1000 Ω', 'NXX', '985', '1015'),
    ('3000 Ω', 'NXX', '2965', '3035'), ('3500 Ω', 'XNN', '3460', '3540'), ('10K Ω', 'NXX', '9.85', '10.15'), ('30K Ω', 'NXX', '29.65', '30.35'),
    ('10 µF', 'NXX', '9.5', '10.5'), ('500 µF', 'NXX', '491', '509'), ('900 µF', 'NXX', '887', '913'),
    ('0.2 A, 5 Hz', 'NNX', '4.7', '5.3'), ('0.2 A, 50 Hz', 'NNX', '49.6', '50.4'), ('0.2 A, 500 Hz', 'NNX', '497.5', '501.5'),
    ('0.12 A @ 50 Hz', 'XNN', '5.4', '6.6'), ('0.48 A @ 150 Hz', 'XNN', '22.9', '25.1'), ('4.2 A @ 50 Hz', 'XNN', '205.3', '214.7'), ('7.8 A @ 50 Hz', 'XNN', '381.7', '398.3'),
    ('7.8 A @ 150 Hz', 'XNN', '379.7', '400.3'), ('7.8 A @ 400 Hz', 'XNN', '379.7', '400.3'),
    ('0.004 A @ 50 Hz', 'NXN', '0.15', '0.25'), ('0.2 A @ 50 Hz', 'NXN', '9.80', '10.20'), ('0.6 A @ 50 Hz', 'NXN', '29.50', '30.50'), ('2 A @ 50 Hz', 'NXN', '97.5', '102.5'),
    ('6 A @ 50 Hz', 'NXN', '293.5', '306.5'),
    ('0.2 A @ 50 Hz', 'NNX', '9.75', '10.25'), ('0.6 A @ 50 Hz', 'NNX', '29.35', '30.65'), ('2 A @ 50 Hz', 'NNX', '98.0', '102.0'), ('6 A @ 50 Hz', 'NNX', '295.0', '305.0'),
    ('0.2 A', 'NNX', '9.75', '10.25'), ('0.6 A', 'NNX', '29.35', '30.65'), ('2 A', 'NNX', '97.5', '102.5'), ('6 A', 'NNX', '293.5', '306.5'),
]
COIL_ROWS = range(27, 48)               # step index 28..48 (0-based 27..47): frequency, AC amps, DC amps
LOW_OUTPUT = {'0.2', '0.6', '2', '0.004', '0.12', '0.48', '6'}


def setUpModule():
    global h, H, Flow, SPECS, Spy, SPEC, BUILDER, X
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import iflex_option as _x
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy, X = _h, _H, _o.Flow, _o.SPECS, _o.Spy, _x
    for m in MODELS:
        SPECS[m] = SPEC_NAME
    SPEC = h.load_spec(SPEC_NAME)
    s = importlib.util.spec_from_file_location('build_fluke_323_spec', ROOT / 'specs' / 'build_fluke_323_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    for m in MODELS:
        SPECS.pop(m, None)


def pts(model):
    return h.points_for(SPEC, model)


class Spec(unittest.TestCase):
    def test_48_rows_and_counts_per_model(self):
        self.assertEqual(len(SPEC['steps']), 48)
        self.assertEqual({m: len(pts(m)) for m in MODELS}, COUNTS)

    def test_every_row_matches_table_4(self):
        for step, (out, x, low, high) in zip(SPEC['steps'], TABLE_4):
            self.assertEqual((step['low'], step['high']), (low, high), out)
            self.assertEqual(''.join('X' if m in step['models'] else 'N' for m in MODELS), x, out)

    def test_the_30k_misprint_is_corrected_visibly(self):
        s = [s for s in SPEC['steps'] if s['display_unit'] == 'kΩ' and s['nominal'] == 30000][0]
        self.assertEqual((s['low'], s['high']), ('29.65', '30.35'))
        self.assertIn('PRINTED MISPRINT', s['note'])
        self.assertIn('34.65', s['printed_text']['low'])
        self.assertEqual(s['check']['verdict'], 'misprint')

    def test_amps_rows_are_50_turns_of_the_calibrator_current(self):
        for s in SPEC['steps']:
            if s['section'] in ('AC amps', 'DC amps'):
                self.assertEqual(D(str(s['nominal'])), D(str(s['applied']['value'])) * 50, s['id'])
                lo, hi = D(s['low']), D(s['high'])
                self.assertEqual((lo + hi) / 2, D(str(s['nominal'])), s['id'])
                self.assertEqual(s['unc_standard'], 'A2LA-5500A-COIL')
                self.assertEqual(s['unc_nominal'], s['nominal'])

    def test_frequency_rows_are_assigned_to_the_coil(self):
        f = [s for s in SPEC['steps'] if s['section'] == 'Frequency']
        self.assertEqual([s['models'] for s in f], [['325']] * 3)
        self.assertEqual([(s['applied']['value'], s['applied']['frequency'], s['nominal']) for s in f], [(0.2, 5.0, 5.0), (0.2, 50.0, 50.0), (0.2, 500.0, 500.0)])
        for s in f:
            self.assertEqual(s['group'], 'COIL_AUX')
            self.assertEqual(s['display_unit'], 'Hz')
            self.assertIn('ASSIGNED TO THE 50-TURN COIL', s['note'])
            self.assertEqual(s['unc_kind'], 'FREQ')

    def test_groups_by_calibrator_output(self):
        for s in SPEC['steps']:
            if s['section'] in ('AC amps', 'DC amps', 'Frequency'):
                want = 'COIL_AUX' if s['applied']['value'] < 3 else 'COIL_20A'
                self.assertEqual(s['group'], want, s['id'])
            elif s['section'] == 'Temperature':
                self.assertEqual(s['group'], 'TEMP')
            else:
                self.assertEqual(s['group'], 'VOHM', s['id'])
        high = sorted({(s['applied']['value'], s['applied']['frequency'] or 0.0) for s in SPEC['steps'] if s.get('group') == 'COIL_20A'})
        self.assertEqual(high, [(4.2, 50.0), (6.0, 0.0), (6.0, 50.0), (7.8, 50.0), (7.8, 150.0), (7.8, 400.0)])

    def test_the_323_has_no_coil_other_than_ac_amps(self):
        self.assertEqual({p['section'] for p in pts('323') if p['group'].startswith('COIL')}, {'AC amps'})
        self.assertEqual(sum(1 for p in pts('323') if p['group'].startswith('COIL')), 6)
        self.assertEqual(sum(1 for p in pts('324') if p['group'].startswith('COIL')), 5)
        self.assertEqual(sum(1 for p in pts('325') if p['group'].startswith('COIL')), 11)      # 3 frequency + 4 AC + 4 DC

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_builder_aborts_on_a_wrong_coil_ratio(self):
        rows = list(BUILDER.ROWS)
        try:
            BUILDER.ROWS = [r if r[3] != '4.2' else (*r[:6], '200', '195', '205', *r[9:]) for r in rows]
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
        finally:
            BUILDER.ROWS = rows

    def test_hookups_and_diagrams_readme(self):
        import hookups
        for cal in ('5560A', '5522A'):
            plan = hookups.plan('fluke323', cal, 'VOHM', manual=False)
            self.assertTrue(plan and plan['steps'] and plan['caution'])
        self.assertEqual(SPEC['options']['hookup_meter'], 'fluke323')
        text = (ROOT / 'diagrams' / 'README_fluke323.txt').read_text(encoding='utf-8')
        for name in ('hook_fluke323_COIL_AUX.png', 'hook_fluke323_COIL_20A.png', 'hook_fluke323_TEMP.png', 'hook_fluke323_<calibrator>_VOHM.png'):
            self.assertIn(name, text)
        for g in SPEC['groups'].values():
            self.assertTrue(g['diagram'].startswith('diagrams/hook_fluke323_'))

    def test_sidecars_launchers(self):
        for m in MODELS:
            d = json.loads((ROOT / 'Procedures' / f'Fluke_{m}_Verification.procedure.json').read_text(encoding='utf-8'))
            self.assertEqual((d['id'], d['model'], d['engine'], d['specs'], d['hookup']['meter']), (f'Fluke_{m}_Verification', m, ['handheld_dmm.py', 'iflex_option.py'], ['specs/fluke_323_pv.json'], 'fluke323'))
            self.assertIn(f'{COUNTS[m]} points', d['description'])
            src = (ROOT / 'Procedures' / f'Fluke_{m}_Verification.py').read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", src)
            self.assertIn("SPEC = 'fluke_323_pv.json'", src)
            self.assertIn('iflex_option.main(MODEL, spec=SPEC)', src)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()

    def make(self, meter, cal='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {cal}', 'sim', transport=Spy(bench, cal))
            io.auto_ramp = False
        app = X.App(self.hn.root, meter, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
        app.asset.set(f'A-{meter}'); app.serial.set('S-1')
        app.cal_mode.set(h.CAL_CHOICES[1] if cal == '5522A' else h.CAL_CHOICES[0])
        if io:
            app.io = io
        self.hn.app = app
        return app, io

    def run_perfect(self, meter, cal='5522A'):
        app, io = self.make(meter, cal)
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        return app, io

    def test_perfect_meter_passes_every_model_with_either_calibrator(self):
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                self.assertEqual(len(app.found), COUNTS[meter], (meter, cal))
                self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, (meter, cal))
                self.assertTrue(all(not r['synthetic'] and r['source'] == 'typed' for r in app.found.values()))
                self.hn.stop(); self.hn = H.Harness().start()

    def test_wire_log_325_coil_outputs_standby_and_dc_zero_hz(self):
        app, io = self.run_perfect('325')
        texts = [t for _i, t in H.wire(io)]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(len(outs), 30)
        for want in ('OUT 0.2A,5Hz', 'OUT 0.2A,50Hz', 'OUT 0.2A,500Hz', 'OUT 6A,50Hz', 'OUT 0.2A,0Hz', 'OUT 6A,0Hz', 'OUT -5CEL', 'OUT 400CEL', 'OUT 900UF'):
            self.assertTrue(any(o.startswith(want[:-1] if want.endswith('CEL') else want) for o in outs), want)
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))
        self.assertEqual(texts[-1], 'STBY')
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b])
        for o, p in zip(outs, pts('325')):
            if p['kind'] in ('DCV', 'DCI'):
                self.assertTrue(o.endswith(',0Hz'), o)

    def test_wire_log_323_ac_amps(self):
        app, io = self.run_perfect('323')
        outs = [t for _i, t in H.wire(io) if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual([o for o in outs if o.endswith('Hz') and 'A,' in o], ['OUT 0.12A,50Hz', 'OUT 0.48A,150Hz', 'OUT 4.2A,50Hz', 'OUT 7.8A,50Hz', 'OUT 7.8A,150Hz', 'OUT 7.8A,400Hz'])

    def test_cable_change_prompts_for_the_coil_groups(self):
        app, io = self.run_perfect('323')
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
        self.assertEqual(len(cables), 3)                       # leads (volts, ohms), then the 50-turn coil on the low-current output, then on the 20 A output

    def test_coil_point_uncertainty_is_the_coil_rule(self):
        import report_pdf
        app, io = self.run_perfect('324')
        rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
        by_id = {p['id']: p for p in app.points}
        for pid, p in by_id.items():
            if p['section'] == 'AC amps':
                self.assertIn('A2LA-5500A-COIL', p['note'])
                nom, std = X.App.unc_source(p)
                q = dict(kind=p['kind'], nominal=nom, frequency=p['applied']['frequency'], unit='A', range=None, extra=X.App.unc_extra(p))
                if X.App.unc_scale(p) != 1.0:
                    q['scale'] = X.App.unc_scale(p)
                self.assertEqual(rows[pid]['Uncertainty'], report_pdf.point_uncertainty(q, standard=std or app.calibrator_model()), pid)

    def test_out_of_tolerance_fails_and_exact_limit_passes(self):
        app, io = self.make('324')
        point = pts('324')[-1]                          # 6 A x 50 = 300 A, limits 293.5 .. 306.5
        self.hn.default_reading = lambda p: ('306.5' if p['n'] != point['n'] else '306.6')
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found[point['id']]['result'], 'FAIL')

    def test_report_has_the_misprint_note_and_coil_uncertainty(self):
        app, io = self.run_perfect('325')
        out = tempfile.mkdtemp() + '/x.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        self.assertIn('Calibration Data', text)
        self.assertIn('29.65', text)
        self.assertIn('misprint', app.source_note().lower())               # the footer note is kept with the issued report (the PDF itself does not print it)

    def test_demo_is_marked_and_never_real(self):
        for meter in MODELS:
            app, _ = self.make(meter, demo=True)
            self.assertTrue(self.hn.run_all(), meter)
            self.assertTrue(app.any_synthetic())
            self.assertEqual(len(app.found), COUNTS[meter])
            self.hn.stop(); self.hn = H.Harness().start()


if __name__ == '__main__':
    unittest.main()
