"""Fluke 333 / 334 / 335 / 336 / 337 clamp meter performance verification (Procedures/Fluke_33X_Verification.py -> iflex_option.main(MODEL, spec='fluke_33x_pv.json');
specs/fluke_33x_pv.json built by specs/build_fluke_33x_spec.py from the 33X ClampMeters Calibration Information, Table 2, printed pp. 8-9).

Part 1: the spec against an INDEPENDENT second transcription of both halves of Table 2 (read from the rendered page images at 260 dpi, after the first reading at 130 / 200 dpi), the five model columns
(the manual has no X / N/A columns: the table a row is printed in plus the printed model tags), the 50-turn coil assignment (the printed output = the current in the jaw = 50 x the calibrator
current), the inrush / frequency / 0 A rows, the beeper and 'does not change' rows, the hook-up groups, the cross-check against the printed Specifications (four ohms rows looser, one frequency
row rounded: nothing changed), hook-ups, sidecars, launchers.
Part 2: the real engine (iflex_option.App on handheld_dmm) on the simulated bench with the 5522A and 5560A, one run per model: wire commands (explicit 0 Hz on DC, LCOMP on AC coil points only,
standby after each point), a typed reading judged exactly, the coil uncertainty, the exact list of points without an uncertainty, the PDF report, demo marking.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_fluke_33x_points"""
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
SPEC_NAME = 'fluke_33x_pv.json'
MODELS = ('333', '334', '335', '336', '337')
COUNTS = {'333': 12, '334': 16, '335': 16, '336': 23, '337': 30}          # Table 2 rows 11 / 13 / 13 / 20 / 27 + functional checks 1 / 3 / 3 / 3 / 3
TABLE_COUNTS = {'333': 11, '334': 13, '335': 13, '336': 20, '337': 27}
# the functional checks of printed pp. 5-6 as read a second time: (title keyword, models as X / N for 333..337) in the manual's order
FUNC = [('Display', 'NXXXX'), ('Backlight', 'NXXXX'), ('Keypad', 'XXXXX')]

# Table 2 as read a second time: (the '5520A Output' column as printed, models as X / N for 333 334 335 336 337, low, high, what the meter shows) in table order.
# low / high None: the table prints no numeric limits ('Beeper On', 'Reading does not change').
TABLE_2A = [      # printed p. 8: Performance Tests 333, 334, 335
    ('20 V 50 Hz', 'XXXNN', '19.3', '20.7', '20'), ('600 V 50 Hz', 'XXXNN', '593.5', '606.5', '600'),
    ('20 V', 'XXXNN', '19.3', '20.7', '20'), ('-20 V', 'XXXNN', '-20.7', '-19.3', '-20'), ('600 V', 'XXXNN', '593.5', '606.5', '600'), ('-600 V', 'XXXNN', '-606.5', '-593.5', '-600'),
    ('25 Ω', 'XXXNN', None, None, '25'),
    ('600 Ω', 'XXXNN', '590.5', '609.5', '600'), ('6 KΩ (334, 335)', 'NXXNN', '5905', '6095', '6000'),
    ('20 A 50 Hz', 'XXXNN', '19.1', '20.9', '20'), ('200 A 50 Hz', 'XXXNN', '195.5', '204.5', '200'), ('400 A 50 Hz (333)', 'XNNNN', '391.5', '408.5', '400'),
    ('600 A 50 Hz (334, 335)', 'NXXNN', '587.5', '612.5', '600'),
    ('**5 A 60 Hz', 'NXXNN', '4.4', '5.6', '5'),
]
TABLE_2B = [      # printed p. 9: Performance Tests 336, 337 (cont.)
    ('20 V 50 Hz', 'NNNXX', '19.3', '20.7', '20'), ('600 V 50 Hz', 'NNNXX', '593.5', '606.5', '600'), ('600 V 400 Hz', 'NNNXX', '563.5', '636.5', '600'),
    ('Min/Max (337) 600 V 400 Hz', 'NNNNX', '563.5', '636.5', '600'), ('Min/Max (337) 20 V 400 Hz', 'NNNNX', None, None, '20'),
    ('20 V', 'NNNXX', '19.3', '20.7', '20'), ('-20 V', 'NNNXX', '-20.7', '-19.3', '-20'), ('600 V', 'NNNXX', '593.5', '606.5', '600'), ('-600 V', 'NNNXX', '-606.5', '-593.5', '-600'),
    ('25 Ω', 'NNNXX', None, None, '25'),
    ('600 Ω', 'NNNXX', '590.5', '609.5', '600'), ('6 KΩ', 'NNNXX', '5905', '6095', '6000'),
    ('20 A 50 Hz', 'NNNXX', '19.1', '20.9', '20'), ('200 A 50 Hz', 'NNNXX', '195.5', '204.5', '200'), ('200 A 400 Hz', 'NNNXX', '187.5', '212.5', '200'),
    ('600 A 50 Hz', 'NNNXX', '587.5', '612.5', '600'), ('900 A 50 Hz (337 only)', 'NNNNX', '881.5', '918.5', '900'),
    ('**5 A 60 Hz', 'NNNXX', '4.4', '5.6', '5'),
    ('0.0 A after button push', 'NNNXX', '-0.5', '0.5', '0'), ('20.0 A', 'NNNXX', '19.1', '20.9', '20'), ('-20.0 A', 'NNNXX', '-20.9', '-19.1', '-20'),
    ('600.0 A', 'NNNXX', '587.5', '612.5', '600'), ('-600.0 A', 'NNNXX', '-612.5', '-587.5', '-600'), ('900.0 A (337)', 'NNNNX', '881.5', '918.5', '900'), ('-900.0 A (337)', 'NNNNX', '-918.5', '-881.5', '-900'),
    ('5 A 10 Hz', 'NNNNX', '9.4', '10.6', '10'), ('10 A 300 Hz', 'NNNNX', '298.0', '302.0', '300'),
]
TABLE = TABLE_2A + TABLE_2B
# what the calibrator is programmed to, from the printed output column: (value in base units, frequency or None) - amps are the printed current / 50
APPLIED = [(20, 50), (600, 50), (20, None), (-20, None), (600, None), (-600, None), (25, None), (600, None), (6000, None),
           (0.4, 50), (4, 50), (8, 50), (12, 50), (0.1, 60),
           (20, 50), (600, 50), (600, 400), (600, 400), (20, 400), (20, None), (-20, None), (600, None), (-600, None), (25, None), (600, None), (6000, None),
           (0.4, 50), (4, 50), (4, 400), (12, 50), (18, 50), (0.1, 60),
           (0, None), (0.4, None), (-0.4, None), (12, None), (-12, None), (18, None), (-18, None), (0.1, 10), (0.2, 300)]
SECTIONS = (['AC volts'] * 2 + ['DC volts'] * 4 + ['Continuity', 'Ohms', 'Ohms'] + ['AC amps'] * 4 + ['Inrush']
            + ['AC volts'] * 3 + ['Min/Max'] * 2 + ['DC volts'] * 4 + ['Continuity', 'Ohms', 'Ohms'] + ['AC amps'] * 5 + ['Inrush'] + ['DC amps'] * 7 + ['Frequency'] * 2)


def group_of(applied, section):
    """The hook-up group the second transcription implies: leads, or the coil on the low / high current terminals (3 A is the 5522A AUX limit)."""
    if section in ('AC volts', 'DC volts', 'Min/Max', 'Continuity', 'Ohms'):
        return 'VOHM'
    return 'COIL_AUX' if abs(applied[0]) < 3 else 'COIL_20A'


GROUPS = [group_of(a, s) for a, s in zip(APPLIED, SECTIONS)]


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
    s = importlib.util.spec_from_file_location('build_fluke_33x_spec', ROOT / 'specs' / 'build_fluke_33x_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    for m in MODELS:
        SPECS.pop(m, None)


def pts(model):
    return h.points_for(SPEC, model)


class Spec(unittest.TestCase):
    def test_41_rows_in_two_tables_and_counts_per_model(self):
        self.assertEqual(len(TABLE), 41)
        self.assertEqual(len(SPEC['steps']), 44)                                  # 41 Table 2 rows + 3 functional checks
        tb = SPEC['steps'][:41]
        self.assertEqual([s['step'] for s in tb], list(range(1, 42)))
        self.assertEqual([s['table'] for s in tb].count('2A'), 14)
        self.assertEqual([s['table'] for s in tb].count('2B'), 27)
        self.assertEqual([s['ref'] for s in tb], [f'T2A #{i}' for i in range(1, 15)] + [f'T2B #{i}' for i in range(1, 28)])
        self.assertEqual(len({s['id'] for s in SPEC['steps']}), 44)
        self.assertEqual({m: len(pts(m)) for m in MODELS}, COUNTS)
        self.assertEqual({m: sum(1 for s in tb if m in s['models']) for m in MODELS}, TABLE_COUNTS)
        self.assertEqual({m: sum(1 for r in TABLE if r[1][MODELS.index(m)] == 'X') for m in MODELS}, TABLE_COUNTS)      # the second transcription gives the same counts

    def test_functional_checks_are_yes_no_points_that_run_first(self):
        """Owner decision 2026-10-27: display (334-337), backlight (334-337) and keypad (all) checks, printed pp. 5-6, as visual points: no output, no limits, no uncertainty; table F runs first in manual order."""
        f = SPEC['steps'][41:]
        self.assertEqual([s['id'] for s in f], ['F-1', 'F-2', 'F-3'])
        for s, (kw, flags) in zip(f, FUNC):
            self.assertIn(kw, s['title'])
            self.assertEqual(''.join('X' if m in s['models'] else 'N' for m in MODELS), flags)
            self.assertEqual((s['test'], s['kind'], s['table']), ('visual', 'VISUAL', 'F'))
            self.assertNotIn('applied', s)
            self.assertNotIn('low', s)
        for m in MODELS:
            ids = [p['id'] for p in pts(m)]
            n_f = sum(1 for p in pts(m) if p['table'] == 'F')
            self.assertEqual(ids[:n_f], [i for i in ('F-1', 'F-2', 'F-3') if m in SPEC['steps'][41 + int(i[-1]) - 1]['models']], m)
            self.assertTrue(all(p['group'] == 'NONE' for p in pts(m) if p['table'] == 'F'))
        self.assertEqual(sum(1 for p in pts('333') if p['table'] == 'F'), 1)          # the 333 has no display test and no backlight

    def test_every_row_matches_the_second_transcription(self):
        for step, (out, flags, low, high, nom) in zip(SPEC['steps'][:41], TABLE):
            self.assertEqual(''.join('X' if m in step['models'] else 'N' for m in MODELS), flags, out)
            self.assertEqual(D(str(step['nominal'] / step['factor'])).normalize(), D(nom).normalize(), out)
            if low is None:
                self.assertNotIn('low', step, out)
                self.assertIn(step['test'], ('beeper', 'visual'), out)
            else:
                self.assertEqual((step['low'], step['high']), (low, high), out)
                self.assertEqual(step['test'], 'numeric', out)

    def test_sections_and_calibrator_outputs(self):
        self.assertEqual([s['section'] for s in SPEC['steps'][:41]], SECTIONS)
        for step, (value, freq), (out, *_r) in zip(SPEC['steps'][:41], APPLIED, TABLE):
            self.assertEqual((step['applied']['value'], step['applied']['frequency']), (value, float(freq) if freq else None), out)

    def test_amps_inrush_rows_are_50_turns_of_the_calibrator_current(self):
        coil = [s for s in SPEC['steps'] if s['section'] in ('AC amps', 'Inrush', 'DC amps')]
        self.assertEqual(len(coil), 9 + 2 + 7)
        for s in coil:
            self.assertEqual(D(str(s['nominal'])), D(str(s['applied']['value'])) * 50, s['id'])
            lo, hi = D(s['low']), D(s['high'])
            self.assertEqual((lo + hi) / 2, D(str(s['nominal'])), s['id'])
            self.assertEqual(s['unc_standard'], 'A2LA-5500A-COIL', s['id'])           # the repository rule (tests/test_coil_uncertainty.py): every 50-turn coil step names the coil sheet
            self.assertEqual(s['unc_nominal'], s['nominal'])
            self.assertIn('INFERENCE', s['note'], s['id'])
        self.assertEqual([s['nominal'] for s in SPEC['steps'] if s['section'] == 'DC amps'], [0, 20, -20, 600, -600, 900, -900])
        self.assertTrue(all(s['applied']['frequency'] is None for s in SPEC['steps'] if s['section'] == 'DC amps'))

    def test_inrush_rows_carry_the_footnotes(self):
        r = [s for s in SPEC['steps'] if s['section'] == 'Inrush']
        self.assertEqual([(s['id'], s['models']) for s in r], [('2A-14', ['334', '335']), ('2B-32', ['336', '337'])])
        for s in r:
            self.assertEqual((s['applied']['value'], s['applied']['frequency'], s['nominal']), (0.1, 60.0, 5.0))
            self.assertIn('INRUSH button must be pressed after current is applied', s['note'])
            self.assertIn('bar (- - - -)', s['note'])
            self.assertIn('INRUSH', s['switch'])
        self.assertNotIn('333', [m for s in r for m in s['models']])               # the 333 has no inrush (Specifications: NA)

    def test_frequency_rows_through_the_coil(self):
        f = [s for s in SPEC['steps'][:41] if s['display_unit'] == 'Hz']
        self.assertEqual([(s['id'], s['models'], s['applied']['value'], s['applied']['frequency'], s['nominal'], s['unc_kind'], s['group']) for s in f],
                         [('2B-40', ['337'], 0.1, 10.0, 10, 'FREQ', 'COIL_AUX'), ('2B-41', ['337'], 0.2, 300.0, 300, 'FREQ', 'COIL_AUX')])
        for s in f:
            self.assertNotIn('unc_standard', s)
            self.assertIn('INFERENCE', s['note'])
            self.assertIn('trigger level', s['note'])
        self.assertIn('exactly the trigger level', f[1]['note'])

    def test_zero_amp_point_has_no_uncertainty_by_design(self):
        z = SPEC['steps'][32]
        self.assertEqual((z['id'], z['section'], z['kind'], z['applied']['value'], z['group'], z['models']), ('2B-33', 'DC amps', 'DCI', 0, 'COIL_AUX', ['336', '337']))
        self.assertTrue(z['no_uncertainty'])                                       # prints none (owner precedent of the 381's 0 A point); unc_standard stays only for the repository coil rule
        self.assertEqual((z['unc_standard'], z['unc_nominal']), ('A2LA-5500A-COIL', 0))
        self.assertIn('NO UNCERTAINTY', z['note'])
        self.assertIn('ZERO', z['note'])
        self.assertIn('ZERO', z['switch'])

    def test_continuity_and_does_not_change_rows_are_not_numeric(self):
        c = [s for s in SPEC['steps'] if s['section'] == 'Continuity']
        self.assertEqual([(s['id'], s['test'], s['expect'], s['applied']['value'], s['kind'], s['models']) for s in c],
                         [('2A-7', 'beeper', 'on', 25, 'OHM', ['333', '334', '335']), ('2B-24', 'beeper', 'on', 25, 'OHM', ['336', '337'])])
        v = SPEC['steps'][18]
        self.assertEqual((v['id'], v['test'], v['section'], v['models'], v['applied']['value'], v['applied']['frequency']), ('2B-19', 'visual', 'Min/Max', ['337'], 20, 400.0))
        self.assertIn('does NOT change', v['question'])
        mm = SPEC['steps'][17]
        self.assertEqual((mm['id'], mm['test'], mm['applied']['frequency']), ('2B-18', 'numeric', 400.0))
        self.assertEqual(mm['switch'], v['switch'])                                  # one dial prompt for the pair; the MIN/MAX instruction is in the text
        self.assertIn('MIN/MAX', mm['switch'])

    def test_groups(self):
        self.assertEqual([s.get('group') for s in SPEC['steps'][:41]], GROUPS)
        self.assertEqual(set(GROUPS), set(SPEC['groups']) | {'VOHM'})
        high = sorted({(s['applied']['value'], s['applied']['frequency'] or 0.0) for s in SPEC['steps'][:41] if s['group'] == 'COIL_20A'})
        self.assertEqual(high, [(-18.0, 0.0), (-12.0, 0.0), (4.0, 50.0), (4.0, 400.0), (8.0, 50.0), (12.0, 0.0), (12.0, 50.0), (18.0, 0.0), (18.0, 50.0)])

    def test_published_accuracy_cross_check_flags_but_changes_nothing(self):
        flagged = {s['id']: s['check']['verdict'] for s in SPEC['steps'] if s.get('check')}
        self.assertEqual(flagged, {'2A-8': 'looser', '2A-9': 'looser', '2B-25': 'looser', '2B-26': 'looser', '2B-40': 'rounded'})
        for s in SPEC['steps']:
            if s.get('check'):
                self.assertIn('CHECK', s['note'])
                if s['check']['verdict'] == 'looser':
                    self.assertIn('DISCREPANCY', s['note'])
                    self.assertIn('1.5 % + 5 counts', s['note'])
        o = [s for s in SPEC['steps'] if s['id'] == '2A-8'][0]          # 600 ohm: printed +-9.5, published +-6.5 (1 % + 5 x 0.1)
        self.assertEqual((o['low'], o['high']), ('590.5', '609.5'))
        self.assertEqual([i['full_spec'] for i in o['check']['printed_vs_spec']], ['6.5', '6.5'])
        k = [s for s in SPEC['steps'] if s['id'] == '2B-26'][0]
        self.assertEqual([i['full_spec'] for i in k['check']['printed_vs_spec']], ['65', '65'])
        f = [s for s in SPEC['steps'] if s['id'] == '2B-40'][0]
        self.assertEqual([i['full_spec'] for i in f['check']['printed_vs_spec']], ['0.55', '0.55'])

    def test_every_other_limit_is_the_full_published_accuracy(self):
        """Independent re-computation of the printed Specifications (p. 3), not through the builder's own helper."""
        rule = {'ACV': (D('0.01'), 5, D('0.1')), 'DCV': (D('0.01'), 5, D('0.1')), 'ACA': (D('0.02'), 5, D('0.1')), 'DCA': (D('0.02'), 5, D('0.1')), 'INR': (D('0.02'), 5, D('0.1'))}
        for s in SPEC['steps']:
            if s['test'] != 'numeric' or s.get('check') or s['section'] in ('Frequency', 'Ohms'):
                continue
            key = {'AC volts': 'ACV', 'Min/Max': 'ACV', 'DC volts': 'DCV', 'AC amps': 'ACA', 'DC amps': 'DCA', 'Inrush': 'INR'}[s['section']]
            pct, counts, res = rule[key]
            if s['applied'].get('frequency') == 400:
                pct = D('0.06')                                                  # 6 % + 5 counts at 400 Hz (the 400 Hz rows only)
            nom = D(str(s['nominal']))
            half = pct * abs(nom) + counts * res
            self.assertEqual((nom - D(s['low']), D(s['high']) - nom), (half, half), s['id'])

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_builder_aborts_on_a_wrong_coil_ratio_or_limit(self):
        rows = list(BUILDER.ROWS)
        try:
            BUILDER.ROWS = [r if not (r[1] == 'AC amps' and r[6] == '12' and r[0] == '2A') else (*r[:6], '10', *r[7:]) for r in rows]          # 10 A x 50 is not 600 A
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
            BUILDER.ROWS = [r if not (r[1] == 'DC volts' and r[9] == '600' and r[0] == '2A') else (*r[:10], '593.0', '606.0', *r[12:]) for r in rows]      # neither the published accuracy nor a flagged rounding
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
            BUILDER.ROWS = rows[:-1]
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
        finally:
            BUILDER.ROWS = rows

    def test_hookups_and_diagrams_readme(self):
        import hookups
        for cal in ('5560A', '5522A'):
            plan = hookups.plan('fluke33x', cal, 'VOHM', manual=False)
            self.assertTrue(plan and plan['steps'] and plan['caution'])
            self.assertIn('600 V', plan['caution'])
        self.assertEqual(SPEC['options']['hookup_meter'], 'fluke33x')
        text = (ROOT / 'diagrams' / 'README_fluke33x.txt').read_text(encoding='utf-8')
        for name in ('hook_fluke33x_COIL_AUX.png', 'hook_fluke33x_COIL_20A.png', 'hook_fluke33x_5560A_VOHM.png', 'hook_fluke33x_5522A_VOHM.png'):
            self.assertIn(name, text)
        for g in SPEC['groups'].values():
            self.assertTrue(g['diagram'].startswith('diagrams/hook_fluke33x_'))
        self.assertEqual(sorted(g['diagram'] for g in SPEC['groups'].values()), ['diagrams/hook_fluke33x_COIL_20A.png', 'diagrams/hook_fluke33x_COIL_AUX.png'])
        self.assertEqual(list((ROOT / 'diagrams').glob('hook_fluke33x_*.png')), [], 'diagrams are owner-supplied; none is invented here')

    def test_sidecars_and_launchers(self):
        for n, m in enumerate(MODELS):
            d = json.loads((ROOT / 'Procedures' / f'Fluke_{m}_Verification.procedure.json').read_text(encoding='utf-8'))
            self.assertEqual((d['id'], d['model'], d['engine'], d['specs'], d['hookup']['meter'], d['category']),
                             (f'Fluke_{m}_Verification', m, ['handheld_dmm.py', 'iflex_option.py'], ['specs/fluke_33x_pv.json'], 'fluke33x', 'Clamp Meter'))
            self.assertEqual(d['name'], f'Fluke {m} Clamp Meter Performance Verification')
            self.assertIn(f'{COUNTS[m]} points', d['description'])
            self.assertNotIn('kind', d)                                         # verification: lists under Automated Calibrations
            self.assertIn('specs/fluke_33x_pv.json#' + m, d['fingerprint']['spec'])
            self.assertIn('hookups.py#fluke33x', d['fingerprint']['code'])
            src = (ROOT / 'Procedures' / f'Fluke_{m}_Verification.py').read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", src)
            self.assertIn("SPEC = 'fluke_33x_pv.json'", src)
            self.assertIn('iflex_option.main(MODEL, spec=SPEC)', src)
        self.assertEqual(len({json.loads((ROOT / 'Procedures' / f'Fluke_{m}_Verification.procedure.json').read_text(encoding='utf-8'))['order'] for m in MODELS}), 5)


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

    def fresh(self):
        self.hn.stop(); self.hn = H.Harness().start()

    def test_perfect_meter_passes_every_model_with_either_calibrator(self):
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                self.assertEqual(len(app.found), COUNTS[meter], (meter, cal))
                self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, (meter, cal))
                self.assertTrue(all(not r['synthetic'] for r in app.found.values()))
                self.assertTrue(all(r['source'] == 'typed' for k, r in app.found.items() if r.get('reading') is not None))          # every numeric reading was typed (yes / no points carry none)
                self.fresh()

    def test_wire_log_outputs_standby_dc_zero_hz_and_reset_first(self):
        for meter in MODELS:
            app, io = self.run_perfect(meter)
            texts = [t for _i, t in H.wire(io)]
            outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
            self.assertEqual(len(outs), TABLE_COUNTS[meter], meter)
            self.assertLess(texts.index('*RST'), texts.index(outs[0]))
            self.assertEqual(texts[-1], 'STBY')
            idx = [i for i, t in enumerate(texts) if t in outs]
            for a, b in zip(idx, idx[1:]):
                self.assertIn('STBY', texts[a + 1:b], meter)
            for o, p in zip(outs, [p for p in pts(meter) if p['table'] != 'F']):
                if p['kind'] in ('DCV', 'DCI'):
                    self.assertTrue(o.endswith(',0Hz'), o)
            self.fresh()

    def test_wire_log_337_every_output_as_derived_from_the_printed_table(self):
        app, io = self.run_perfect('337')
        outs = [t for _i, t in H.wire(io) if t.startswith('OUT ') and not t.endswith('?')]
        want = ['OUT 20V,50Hz', 'OUT 600V,50Hz', 'OUT 600V,400Hz', 'OUT 600V,400Hz', 'OUT 20V,400Hz', 'OUT 20V,0Hz', 'OUT -20V,0Hz', 'OUT 600V,0Hz', 'OUT -600V,0Hz', 'OUT 25',
                'OUT 600', 'OUT 6000', 'OUT 0.4A,50Hz', 'OUT 4A,50Hz', 'OUT 4A,400Hz', 'OUT 12A,50Hz', 'OUT 18A,50Hz', 'OUT 0.1A,60Hz', 'OUT 0A,0Hz', 'OUT 0.4A,0Hz', 'OUT -0.4A,0Hz',
                'OUT 12A,0Hz', 'OUT -12A,0Hz', 'OUT 18A,0Hz', 'OUT -18A,0Hz', 'OUT 0.1A,10Hz', 'OUT 0.2A,300Hz']
        self.assertEqual(len(outs), len(want))
        for o, w in zip(outs, want):
            self.assertTrue(o.startswith(w), (o, w))

    def test_ac_coil_points_get_lcomp_on_and_off_and_nothing_else_does(self):
        """Owner request 2026-10-26 (and the manual's own step 4, printed p. 7): LCOMP ON for AC current through the coil, OFF afterwards; every AC coil point here is inside what the 5522A allows."""
        expected = {'333': 3, '334': 4, '335': 4, '336': 5, '337': 8}        # AC amps + inrush (+ the two frequency rows on the 337)
        for meter in MODELS:
            app, io = self.run_perfect(meter)
            texts = [t for _i, t in H.wire(io)]
            ons = [i for i, t in enumerate(texts) if t == 'LCOMP ON']
            self.assertEqual(len(ons), expected[meter], meter)
            for i in ons:
                self.assertTrue(texts[i - 1].startswith('OUT '))
                self.assertEqual(texts[i + 1], 'LCOMP?')
                self.assertIn('OPER', texts[i + 1:i + 8])
                self.assertFalse(texts[i - 1].endswith(',0Hz') or texts[i - 1].split(',')[0].endswith('V'), texts[i - 1])
            self.assertEqual(sum(1 for t in texts if t == 'LCOMP OFF'), len(ons))
            self.assertEqual(texts[-1], 'STBY')
            self.fresh()

    def test_5560a_gets_no_lcomp_command(self):
        app, io = self.run_perfect('337', '5560A')
        self.assertFalse(any(t.startswith('LCOMP') for _i, t in H.wire(io)))

    def test_cable_change_prompts_follow_the_group_changes(self):
        for meter in MODELS:
            app, io = self.run_perfect(meter)
            groups = [p['group'] for p in app.points if p['group'] != 'NONE']          # the yes / no functional checks (group NONE) need no cable change
            cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
            self.assertEqual(len(cables), 1 + sum(1 for a, b in zip(groups, groups[1:]) if a != b), meter)
            self.fresh()

    def test_dial_prompt_for_each_function_change(self):
        app, io = self.run_perfect('337')
        fn = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the function']
        self.assertGreaterEqual(len(fn), 8)                                      # V~, V~ MIN/MAX, V=, Ohm, Continuity, ..., A~, INRUSH, A=, Hz

    def test_coil_point_uncertainty_is_the_coil_rule(self):
        import report_pdf
        app, io = self.run_perfect('337')
        rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
        covered = {}
        self.assertEqual(rows['2B-33']['Uncertainty'], '')                  # the 0 A point names the coil sheet (repository rule) but prints no uncertainty (no_uncertainty)
        for p in app.points:
            if p.get('unc_standard') and not p.get('no_uncertainty'):
                nom, std = X.App.unc_source(p)
                covered[p['id']] = std
                q = dict(kind=p['kind'], nominal=nom, frequency=p['applied']['frequency'], unit=p['base_unit'], range=None, extra=X.App.unc_extra(p))
                if X.App.unc_scale(p) != 1.0:
                    q['scale'] = X.App.unc_scale(p)
                self.assertEqual(rows[p['id']]['Uncertainty'], report_pdf.point_uncertainty(q, standard=std or app.calibrator_model()), p['id'])
        self.assertIsNone(covered['2B-27'])                              # 20 A ac: below the coil's 20.5 A: the calibrator, scaled by the 50 turns
        self.assertIsNone(covered['2B-32'])                              # 5 A inrush
        self.assertEqual(covered['2B-28'], 'A2LA-5500A-COIL')            # 200 A ac
        self.assertEqual(covered['2B-31'], 'A2LA-5500A-COIL')            # 900 A ac
        self.assertEqual(covered['2B-34'], 'A2LA-5500A-COIL')            # +20 A dc
        self.assertEqual(covered['2B-39'], 'A2LA-5500A-COIL')            # -900 A dc

    def test_points_without_an_uncertainty_are_exactly_the_known_list(self):
        """Owner instruction: a point that should carry an uncertainty and has none is reported, never invented.  Without one: the 0 A dc point (336, 337; no_uncertainty, as the 381's 0 A point,
        owner decision 2026-10-26) and the 337's Min/Max 'reading does not change' yes / no check (no numeric reading).  The two continuity beeper points DO carry one (the calibrator's 25 ohm)."""
        f3, f13 = [('F-3', 'VISUAL')], [('F-1', 'VISUAL'), ('F-2', 'VISUAL'), ('F-3', 'VISUAL')]          # functional checks: yes / no, no uncertainty (owner 2026-10-27)
        want = {'333': f3, '334': f13, '335': f13, '336': f13 + [('2B-33', 'DCI')], '337': f13 + [('2B-19', 'ACV'), ('2B-33', 'DCI')]}
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                missing = [(p['id'], p['kind']) for p, r in zip(app.points, app.certificate_rows()) if not str(r.get('Uncertainty') or '').strip()]
                self.assertEqual(missing, want[meter], (meter, cal))
                self.fresh()

    def test_frequency_rows_use_the_calibrators_own_frequency_specification(self):
        want = {'5522A': ('5.8 mHz', '58 mHz'), '5560A': ('25 µHz', '750 µHz')}
        for cal, texts in want.items():
            app, io = self.run_perfect('337', cal)
            rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
            self.assertEqual((rows['2B-40']['Uncertainty'], rows['2B-41']['Uncertainty']), texts, cal)
            self.fresh()

    def test_out_of_tolerance_fails_and_exact_limit_passes(self):
        app, io = self.make('337')
        point = [p for p in pts('337') if p['id'] == '2B-30'][0]          # 12 A x 50 = 600 A, limits 587.5 .. 612.5
        self.hn.default_reading = lambda p: p['high'] if p['n'] != point['n'] else '612.6'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found[point['id']]['result'], 'FAIL')
        self.assertEqual({r['result'] for k, r in app.found.items() if k != point['id']}, {'PASS'})

    def test_sign_matters_on_dc_amps(self):
        app, io = self.make('336')
        self.hn.default_reading = lambda p: ('900' if p['id'] == '2B-37' else H.typed_nominal(p))     # the -600 A point typed without the sign
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['2B-37']['result'], 'FAIL')

    def test_beeper_and_does_not_change_judgements(self):
        """A 'No' to the beeper question or to 'the reading does not change' fails the point (the answer is typed by the operator; no limits are printed for these two rows)."""
        app, io = self.make('337')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings = {'2B-24': False, '2B-19': False}
        self.assertTrue(self.hn.run_all())
        self.assertEqual((app.found['2B-24']['result'], app.found['2B-19']['result']), ('FAIL', 'FAIL'))
        self.assertEqual(app.found['2B-24']['entered'], 'Beeper not on')
        self.assertEqual(app.found['2B-19']['entered'], 'Fail')
        self.assertEqual({r['result'] for k, r in app.found.items() if k not in ('2B-24', '2B-19')}, {'PASS'})
        self.fresh()
        app, io = self.run_perfect('337')
        self.assertEqual((app.found['2B-24']['entered'], app.found['2B-19']['entered']), ('Beeper on', 'Pass'))

    def test_report_is_calibration_data_with_the_source_note(self):
        app, io = self.run_perfect('337')
        out = tempfile.mkdtemp() + '/x.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        self.assertIn('Calibration Data', text)
        self.assertIn('918.5', text)
        self.assertIn('Table 2', app.source_note())
        self.assertIn('looser', app.source_note())
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRATION', ''))

    def test_demo_is_marked_and_never_real(self):
        for meter in MODELS:
            app, _ = self.make(meter, demo=True)
            self.assertTrue(self.hn.run_all(), meter)
            self.assertTrue(app.any_synthetic())
            self.assertEqual(len(app.found), COUNTS[meter])
            self.fresh()


if __name__ == '__main__':
    unittest.main()
