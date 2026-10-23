"""Fluke 376 clamp meter performance verification (Procedures/Fluke_376_Verification.py -> handheld_dmm.main('376', spec=...), the shared handheld engine,
specs/fluke_376_pv.json built by specs/build_fluke_376_spec.py from the Fluke 374 / 375 / 376 / 376-II Calibration Manual, Table 1, printed pp. 3-4).

Part 1: the spec against an INDEPENDENT second transcription of Table 1 (read from the rendered page images at 130, 200 and 260 dpi), the X / - model columns of the family spec (374, 375,
376, 376-II), the rows whose printed limit is neither the full nor half of the published accuracy (flagged, NOT changed), the coil and iFlex points (calibrator output x 50 = meter reading,
iFlex simulation voltages), options, function / cable / high-voltage prompt sequences (and the high-voltage count with options.hv_once_per_group off and on), hook-ups, the sidecar
(automated, i.e. kind verification), uncertainty and TAR / TUR on every sourced point.
Part 2: the real engine (handheld_dmm.App, worker threads, drivers, judging, checkpoint, PDF) on the simulated bench with both calibrators (5522A, 5560A): wire commands, explicit 0 Hz
on DC, set / read back / never retried, standby after each point, reset first, demo never real.
tkinter is stubbed in setUpModule (not at import time), like tests/test_77_points.py, so tests.test_beta is loaded exactly as before.
Run:  python -m unittest tests.test_fluke_376_points"""
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
SPEC_NAME = 'fluke_376_pv.json'
MODEL = '376'
MODELS = ('374', '375', '376', '376-II')

# Table 1 as read a second time from the page images: step -> (calibrator output as the engine words it, X / - for 374 375 376/376-II, lower limit, upper limit)
TABLE_1 = {
    1: ('10 V AC @ 50 Hz', 'XXX', '9.4', '10.7'), 2: ('500 V AC @ 50 Hz', 'XXX', '492.0', '508.0'), 3: ('900 V AC @ 50 Hz', '--X', '882.0', '919.0'),
    4: ('500 V AC @ 500 Hz', 'XXX', '492.0', '508.0'),
    5: ('-500 V DC', 'XXX', '-505.5', '-494.5'), 6: ('10 V DC', 'XXX', '9.4', '10.6'), 7: ('500 V DC', 'XXX', '494.5', '505.5'), 8: ('900 V DC', '--X', '886.0', '914.0'),
    9: ('-250 mV DC', '-XX', '-253.0', '-247.0'), 10: ('50 mV DC', '-XX', '49.0', '51.0'), 11: ('250 mV DC', '-XX', '247.0', '253.0'), 12: ('450 mV DC', '-XX', '445.0', '455.0'),
    13: ('60 Ω', 'XXX', '58.9', '61.1'), 14: ('300 Ω', 'XXX', '296.5', '303.5'), 15: ('540 Ω', 'XXX', '534.1', '545.9'), 16: ('3 kΩ', 'XXX', '2965', '3035'),
    17: ('5.4 kΩ', 'XXX', '5341', '5459'), 18: ('30 kΩ', '-XX', '29.65', '30.35'), 19: ('54 kΩ', '-XX', '53.41', '54.59'),
    20: ('10 µF', 'XXX', '9.5', '10.5'), 21: ('500 µF', 'XXX', '491', '509'), 22: ('900 µF', 'XXX', '887', '913'),
    23: ('200 mA AC @ 50 Hz', 'XXX', '9.3', '10.7'), 24: ('10 A AC @ 50 Hz', 'XXX', '489.5', '510.5'), 25: ('18 A AC @ 50 Hz', '--X', '881.5', '918.5'),
    26: ('6 A AC @ 440 Hz', 'XXX', '292.0', '308.0'),
    27: ('200 mA DC', 'XXX', '9.7', '10.3'), 28: ('10 A DC', 'XXX', '495.0', '505.0'), 29: ('18 A DC', '--X', '891.0', '909.0'),
    30: ('3 mV AC @ 50 Hz', 'XXX', '98.2', '101.8'), 31: ('30 mV AC @ 50 Hz', 'XXX', '982', '1018'), 32: ('60 mV AC @ 50 Hz', 'XXX', '1967', '2033'),
    33: ('75 mV AC @ 50 Hz', 'XXX', '2460', '2540'), 34: ('750 mV AC @ 500 Hz', 'XXX', '2460', '2540'),
    35: ('200 mA AC @ 50 Hz', 'XXX', '9.6', '10.4'), 36: ('10 A AC @ 50 Hz', 'XXX', '493.0', '507.0'), 37: ('18 A AC @ 50 Hz', 'XXX', '887.0', '913.0'),
    38: ('6 A AC @ 440 Hz', 'XXX', '295.2', '304.8'),
}
# the meter reading each row should show (display unit as printed) and its unit
NOMINAL = {1: '10', 2: '500', 3: '900', 4: '500', 5: '-500', 6: '10', 7: '500', 8: '900', 9: '-250', 10: '50', 11: '250', 12: '450', 13: '60', 14: '300', 15: '540', 16: '3000',
           17: '5400', 18: '30', 19: '54', 20: '10', 21: '500', 22: '900', 23: '10', 24: '500', 25: '900', 26: '300', 27: '10', 28: '500', 29: '900',
           30: '100', 31: '1000', 32: '2000', 33: '2500', 34: '2500', 35: '10', 36: '500', 37: '900', 38: '300'}
UNIT = {**{n: 'V' for n in range(1, 9)}, **{n: 'mV' for n in range(9, 13)}, **{n: 'Ω' for n in range(13, 18)}, 18: 'kΩ', 19: 'kΩ', **{n: 'µF' for n in (20, 21, 22)},
        **{n: 'A' for n in range(23, 39)}}
# what the calibrator is sent for each step (both calibrators): the command, then every DC output with an explicit ,0Hz
OUT_COMMANDS = {
    1: 'OUT 10V,50Hz', 2: 'OUT 500V,50Hz', 3: 'OUT 900V,50Hz', 4: 'OUT 500V,500Hz',
    5: 'OUT -500V,0Hz', 6: 'OUT 10V,0Hz', 7: 'OUT 500V,0Hz', 8: 'OUT 900V,0Hz', 9: 'OUT -0.25V,0Hz', 10: 'OUT 0.05V,0Hz', 11: 'OUT 0.25V,0Hz', 12: 'OUT 0.45V,0Hz',
    13: 'OUT 60OHM', 14: 'OUT 300OHM', 15: 'OUT 540OHM', 16: 'OUT 3000OHM', 17: 'OUT 5400OHM', 18: 'OUT 30000OHM', 19: 'OUT 54000OHM',
    20: 'OUT 10UF', 21: 'OUT 500UF', 22: 'OUT 900UF',
    23: 'OUT 0.2A,50Hz', 24: 'OUT 10A,50Hz', 25: 'OUT 18A,50Hz', 26: 'OUT 6A,440Hz', 27: 'OUT 0.2A,0Hz', 28: 'OUT 10A,0Hz', 29: 'OUT 18A,0Hz',
    30: 'OUT 0.003V,50Hz', 31: 'OUT 0.03V,50Hz', 32: 'OUT 0.06V,50Hz', 33: 'OUT 0.075V,50Hz', 34: 'OUT 0.75V,500Hz',
    35: 'OUT 0.2A,50Hz', 36: 'OUT 10A,50Hz', 37: 'OUT 18A,50Hz', 38: 'OUT 6A,440Hz',
}
SECTION_COUNTS = {'AC volts': 4, 'DC volts': 8, 'Ohms': 7, 'Capacitance': 3, 'AC amps': 4, 'DC amps': 3, 'iFlex simulated': 5, 'iFlex with coil': 4}
FUNCTION_PROMPTS = ['V~  (AC volts)', 'V⎓  (DC volts)', 'mV⎓  (DC millivolts: the V⎓ position, mV is its yellow alternate function; how it is selected is UNVERIFIED)',
                    'Ω  (ohms: the Ω position, shared with continuity and capacitance)',
                    'Capacitance ⊣⊢  (the Ω position, ⊣⊢ is its yellow alternate function; how it is selected is UNVERIFIED)',
                    'A~  (AC amps: detachable jaw closed around the 50-turn coil)', 'A⎓  (DC amps: detachable jaw closed around the 50-turn coil)',
                    'iFlex A~  (iFlex AC current; the iFlex probe plugged in, or the simulation leads)']
# rows whose printed limit is neither the full nor half of the published accuracy (specs/build_fluke_376_spec.py): flagged, never changed
FLAGGED = {1: 'rounded', 3: 'rounded', 28: 'tighter', 29: 'tighter', 36: 'tighter', 37: 'tighter'}
IFLEX_SIM = (30, 31, 32, 33, 34)
COIL_POINTS = tuple(range(23, 30)) + (35, 36, 37, 38)
# cable-change prompts: the group changes at these points (VOHM, then the coil terminals alternate, then the iFlex leads, then the iFlex loop on the coil)
CABLE_POINTS = [1, 23, 24, 27, 28, 30, 35, 36]
FUNCTION_POINTS = [1, 5, 9, 13, 20, 23, 27, 30]


def setUpModule():
    """tkinter is stubbed here, not at import time (see tests/test_87v_points.py)."""
    global h, H, Flow, SPECS, Spy, SPEC, PTS, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy = _h, _H, _o.Flow, _o.SPECS, _o.Spy
    for m in MODELS:
        SPECS[m] = SPEC_NAME                                     # the shared Flow helper looks the spec up by model; removed again in tearDownModule
    SPEC = h.load_spec(SPEC_NAME)
    PTS = {p['n']: p for p in h.points_for(SPEC, MODEL)}
    s = importlib.util.spec_from_file_location('build_fluke_376_spec', ROOT / 'specs' / 'build_fluke_376_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    for m in MODELS:
        SPECS.pop(m, None)


class Spec(unittest.TestCase):
    def test_38_points_by_function(self):
        self.assertEqual(len(PTS), 38)
        counts = {}
        for p in PTS.values():
            counts[p['section']] = counts.get(p['section'], 0) + 1
        self.assertEqual(counts, SECTION_COUNTS)
        self.assertEqual([p['step'] for p in PTS.values()], list(range(1, 39)))        # manual order, no gaps
        self.assertEqual({p['id'] for p in PTS.values()}, {f'1-{n}' for n in range(1, 39)})
        self.assertTrue(all(p['test'] == 'numeric' for p in PTS.values()))

    def test_every_point_matches_table_1(self):
        for n, (out, cols, low, high) in TABLE_1.items():
            p = PTS[n]
            self.assertEqual(h.output_text(p), out, n)
            self.assertEqual((p['low'], p['high']), (low, high), n)
            self.assertEqual(p['display_unit'], UNIT[n], n)
            self.assertEqual(D(str(p['nominal'])) / D(str(p['factor'])), D(NOMINAL[n]), n)
        self.assertEqual(set(TABLE_1), set(PTS))

    def test_family_flags_follow_the_x_columns(self):
        """One family spec, per-model flags: the X / - columns of Table 1 (374, 375, 376/376-II) decide each step's models."""
        self.assertEqual(set(SPEC['models']), set(MODELS))
        for n, (_out, cols, _l, _h) in TABLE_1.items():
            step = next(s for s in SPEC['steps'] if s['step'] == n)
            want = [m for m, c in zip(('374', '375', '376'), cols) if c == 'X'] + (['376-II'] if cols[2] == 'X' else [])
            self.assertEqual(step['models'], want, n)
        counts = {m: len(h.points_for(SPEC, m)) for m in MODELS}
        self.assertEqual(counts, {'374': 28, '375': 34, '376': 38, '376-II': 38})
        self.assertEqual([p['id'] for p in h.points_for(SPEC, '376')], [p['id'] for p in h.points_for(SPEC, '376-II')])
        # the 374 has no mV, no 30K / 54K, no 900 V, no 18 A (rows 3, 8, 9-12, 18, 19, 25, 29); the 375 only lacks 900 V and the 18 A jaw rows (3, 8, 25, 29)
        missing = lambda m: sorted(set(range(1, 39)) - {int(p['id'].split('-')[1]) for p in h.points_for(SPEC, m)})
        self.assertEqual(missing('374'), [3, 8, 9, 10, 11, 12, 18, 19, 25, 29])
        self.assertEqual(missing('375'), [3, 8, 25, 29])
        self.assertEqual(missing('376'), [])
        for m in ('374', '375'):                                  # 18 A with the iFlex loop is X for every model (row 37)
            self.assertIn('1-37', {p['id'] for p in h.points_for(SPEC, m)})
        self.assertEqual([n for n, p in enumerate(h.points_for(SPEC, '374'), 1)], [p['n'] for p in h.points_for(SPEC, '374')])     # renumbered 1..28 per model

    def test_limits_against_the_published_accuracy(self):
        """Every printed limit is inside the published accuracy (UNVERIFIED source: the fluke.com page of the 376); the builder classifies each row.  Flagged rows are stored AS PRINTED."""
        steps, problems, flagged = BUILDER.build_steps()
        self.assertEqual(problems, [])                              # none looser than the accuracy by more than half a display step
        self.assertEqual({int(f[0].split('-')[1]): f[1] for f in flagged}, FLAGGED)
        self.assertEqual({n: p['check']['verdict'] for n, p in PTS.items() if 'check' in p}, FLAGGED)
        self.assertEqual(PTS[1]['check']['printed_vs_spec'], [dict(side='high', printed='0.7', half_spec='0.325', full_spec='0.65')])        # 10 V high 10.7 vs 10.65
        self.assertEqual(PTS[3]['check']['printed_vs_spec'], [dict(side='high', printed='19', half_spec='9.25', full_spec='18.5')])         # 900 V ac high 919 vs 918.5
        self.assertEqual([(c['printed'], c['half_spec']) for c in PTS[28]['check']['printed_vs_spec']], [('5', '5.25')] * 2)               # dc amps 10 A: +-5.0 vs +-10.5 (half 5.25)
        self.assertEqual([(c['printed'], c['half_spec']) for c in PTS[37]['check']['printed_vs_spec']], [('13', '13.75')] * 2)             # iFlex with coil 18 A
        for n in FLAGGED:                                            # printed limits kept: nothing was corrected
            self.assertEqual((PTS[n]['low'], PTS[n]['high']), TABLE_1[n][2:], n)
            self.assertIn('CHECK (printed limit not changed)', PTS[n]['note'])
            self.assertNotIn('printed_limits', PTS[n])
        self.assertFalse([n for n, p in PTS.items() if 'printed_limits' in p])
        # every row not flagged is the full accuracy or half of it, to within half a display step
        for n, p in PTS.items():
            if n in FLAGGED:
                continue
            full = BUILDER.spec_halfwidth(NOMINAL[n], BUILDER.ACC[BUILDER.ROWS[n - 1][10]], BUILDER.ROWS[n - 1][11])
            res = D(BUILDER.ROWS[n - 1][11])
            for got in (D(NOMINAL[n]) - D(p['low']), D(p['high']) - D(NOMINAL[n])):
                self.assertTrue(abs(got - full) <= res / 2 or abs(got - full / 2) <= res / 2, (n, got, full))

    def test_builder_rejects_a_limit_looser_than_the_accuracy(self):
        problems, _info, _v = BUILDER.check_row('x', '10', '9.0', '11.0', BUILDER.ACC['ACV'], '0.1')       # +-1.0 V: wider than +-0.65 V
        self.assertTrue(problems)
        self.assertEqual(BUILDER.check_row('x', '500', '492.0', '508.0', BUILDER.ACC['ACV'], '0.1')[0], [])
        self.assertEqual(BUILDER.check_row('x', '500', '492.0', '508.0', BUILDER.ACC['ACV'], '0.1')[2], 'full')

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_the_coil_points(self):
        """Table 1 p. 4: the calibrator drives a 50-turn coil and the limits are meter readings (50 x the calibrator current)."""
        for n, p in PTS.items():
            if n in COIL_POINTS:
                self.assertIn(p['kind'], ('ACI', 'DCI'))
                self.assertEqual(D(str(p['applied']['value'])) * 50, D(str(p['nominal'])), n)
                self.assertNotIn('no_uncertainty', p, n)             # every current point carries the calibrator's current uncertainty (unscaled)
                self.assertIn('NOT multiplied by 50', p['note'], n)
                self.assertIn('50 turns', p['report_desc'])
                self.assertIn('50-turn coil', h.describe(p))
                self.assertNotIn('unc_unit', p)
                self.assertEqual(p['range'], '999.9 A')
        self.assertEqual({n: p['applied']['value'] for n, p in PTS.items() if n in COIL_POINTS},
                         {23: 0.2, 24: 10.0, 25: 18.0, 26: 6.0, 27: 0.2, 28: 10.0, 29: 18.0, 35: 0.2, 36: 10.0, 37: 18.0, 38: 6.0})

    def test_the_iflex_simulation_points(self):
        """Printed p. 3: the calibrator drives mV into the iFlex input and the meter reads amps (30 uV per A at 50 Hz, 300 uV per A at 500 Hz)."""
        for n in IFLEX_SIM:
            p = PTS[n]
            self.assertEqual((p['kind'], p['base_unit'], p['unc_unit'], p['group']), ('ACV', 'A', 'V', 'IFLEX_SIM'), n)
            per_amp = D(str(p['applied']['value'])) / D(str(p['nominal']))
            self.assertEqual(per_amp, D('0.00003') if p['applied']['frequency'] == 50 else D('0.0003'), n)
            self.assertNotIn('no_uncertainty', p)
            self.assertIn('TAR / TUR stay blank', p['note'])
        self.assertEqual([PTS[n]['applied']['value'] for n in IFLEX_SIM], [0.003, 0.03, 0.06, 0.075, 0.75])
        self.assertTrue(all('unc_unit' not in p for n, p in PTS.items() if n not in IFLEX_SIM))

    def test_units_resolutions_and_ranges(self):
        for n, p in PTS.items():
            self.assertEqual({'V': 'V', 'mV': 'V', 'Ω': 'ohm', 'kΩ': 'ohm', 'µF': 'F', 'A': 'A'}[p['display_unit']], p['base_unit'])
            self.assertEqual(p['factor'], {'V': 1.0, 'mV': 0.001, 'Ω': 1.0, 'kΩ': 1000.0, 'µF': 1e-06, 'A': 1.0}[p['display_unit']])
        self.assertEqual({p['range'] for p in PTS.values() if p['section'] == 'Ohms'}, {'600.0 Ω', '6000 Ω', '60.00 kΩ'})
        self.assertEqual([p['range'] for n, p in PTS.items() if p['section'] == 'Ohms'], ['600.0 Ω'] * 3 + ['6000 Ω'] * 2 + ['60.00 kΩ'] * 2)
        self.assertEqual([p['range'] for n, p in PTS.items() if p['section'] == 'Capacitance'], ['100.0 µF', '1000 µF', '1000 µF'])
        self.assertEqual({PTS[n]['range'] for n in (3, 8)}, {'1000 V'})

    def test_validator_passes_and_no_ramp_lists(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        self.assertFalse([n for n, p in PTS.items() if p.get('ramp')])

    def test_options(self):
        o = SPEC['options']
        self.assertIs(o['auto_ramp'], False)                    # high-voltage points go straight to the test value (the manual prescribes no ramp)
        self.assertIs(o['function_prompt'], True)
        self.assertIs(o['hv_once_per_group'], True)
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title']), ('fluke376', 30, 'Calibration Data'))
        self.assertNotIn('ir', o)                                # no remote interface: readings are typed

    def test_groups(self):
        self.assertEqual({n: p['group'] for n, p in PTS.items() if n > 22},
                         {23: 'COIL_AUX', 24: 'COIL_20A', 25: 'COIL_20A', 26: 'COIL_20A', 27: 'COIL_AUX', 28: 'COIL_20A', 29: 'COIL_20A',
                          30: 'IFLEX_SIM', 31: 'IFLEX_SIM', 32: 'IFLEX_SIM', 33: 'IFLEX_SIM', 34: 'IFLEX_SIM',
                          35: 'IFLEX_COIL_AUX', 36: 'IFLEX_COIL_20A', 37: 'IFLEX_COIL_20A', 38: 'IFLEX_COIL_20A'})
        self.assertEqual({p['group'] for n, p in PTS.items() if n <= 22}, {'VOHM'})
        self.assertEqual(set(SPEC['groups']), {'COIL_AUX', 'COIL_20A', 'IFLEX_SIM', 'IFLEX_COIL_AUX', 'IFLEX_COIL_20A'})

    def test_hookups_voltage_ohms_for_both_calibrators_and_other_groups_from_the_spec(self):
        import hookups
        for cal in ('5560A', '5522A'):
            plan = hookups.plan('fluke376', cal, 'VOHM', manual=False)
            self.assertTrue(plan and plan['steps'] and plan['caution'], cal)        # the diagram PNG itself is supplied by the owner (diagrams/README_fluke376.txt)
            self.assertIn('VΩ', hookups.summary('fluke376', cal, 'VOHM'))
        for g in SPEC['groups']:
            self.assertFalse(hookups.has('fluke376', g), g)            # the other hook-ups are the spec's own groups
        for name, g in SPEC['groups'].items():
            text = ' '.join(' '.join(s) for s in g['steps'])
            self.assertTrue(g['diagram'].startswith('diagrams/hook_fluke376_'), name)
            if 'COIL' in name:
                self.assertIn('REMOVE the test leads', text)
                self.assertIn('50-turn', g['title'])
        self.assertIn('2 mm jack', ' '.join(' '.join(s) for s in SPEC['groups']['IFLEX_SIM']['steps']))
        self.assertIn('Slim Reach', ' '.join(' '.join(s) for s in SPEC['groups']['IFLEX_SIM']['steps']))
        self.assertIn('UNVERIFIED', ' '.join(' '.join(s) for s in SPEC['groups']['COIL_AUX']['steps']))
        for other in ('fluke365', 'fluke170', 'fluke110', 'fluke87v', 'fluke77', 'mm325'):   # the other meters' tables are untouched by the new entries
            self.assertIn(other, hookups.METERS)
            self.assertNotEqual(hookups.METERS[other]['name'], hookups.METERS['fluke376']['name'])

    def test_readme_names_every_expected_diagram(self):
        text = (ROOT / 'diagrams' / 'README_fluke376.txt').read_text(encoding='utf-8')
        names = ['hook_fluke376_5560A_VOHM.png', 'hook_fluke376_5522A_VOHM.png'] + [Path(g['diagram']).name for g in SPEC['groups'].values()]
        self.assertEqual(len(names), 7)
        for name in names:
            self.assertIn(name, text)
        self.assertFalse(list((ROOT / 'diagrams').glob('hook_fluke376*')))       # diagrams are supplied by the owner: none is invented

    def test_sidecar_is_an_automated_verification(self):
        import procscan
        p = next(x for x in procscan.procs(ROOT) if x.id == 'Fluke_376_Verification')
        self.assertEqual(p.effective_kind, 'verification')
        self.assertNotIn('Manual', p.name)
        self.assertEqual((p.model, p.category, p.name), ('376', 'Clamp Meter', 'Fluke 376 Clamp Meter Performance Verification'))
        self.assertEqual((p.hookup_meter, p.diagram_prefixes), ('fluke376', ('hook_fluke376',)))
        self.assertIn('hookups.py#fluke376', p.fingerprint_code)         # only this meter's slice of hookups.py: no other procedure is touched
        self.assertEqual(p.specs, ('specs/fluke_376_pv.json',))
        for rel in p.own_files:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertTrue((ROOT / p.launcher).is_file())
        # only the 376 is registered: the 374, 375 and 376-II are in the spec but have no launcher
        self.assertEqual([x.id for x in procscan.procs(ROOT) if x.id.startswith('Fluke_37')], ['Fluke_376_Verification'])

    def test_the_launcher_names_the_engine(self):
        text = (ROOT / 'Procedures' / 'Fluke_376_Verification.py').read_text(encoding='utf-8')
        self.assertIn('handheld_dmm.main(MODEL, spec=SPEC)', text)
        self.assertIn("SPEC = 'fluke_376_pv.json'", text)
        self.assertIn("MODEL = '376'", text)
        self.assertIs(h.App.QUEUE_SUPPORTED, True)               # the run queue is on, as for the other handhelds


class Padding(unittest.TestCase):
    def test_typed_readings_are_padded_to_the_resolution(self):
        for n, typed, want in ((1, '10', '10.0'), (3, '900', '900.0'), (9, '-250', '-250.0'), (16, '3000', '3000'), (18, '30', '30.00'), (19, '54', '54.00'),
                               (20, '10', '10.0'), (21, '500', '500'), (23, '10', '10.0'), (30, '100', '100.0'), (31, '1000', '1000'), (34, '2500', '2500')):
            self.assertEqual(h.pad_reading(PTS[n], typed), want, n)

    def test_a_perfect_meter_passes_every_point(self):
        for n, p in PTS.items():
            typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
            self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', n)

    def test_judging_is_exact_at_the_printed_limits(self):
        self.assertEqual(h.judge_numeric(PTS[1], '10.7')[0], 'PASS')          # the printed (rounded) limit is judged, not 10.65
        self.assertEqual(h.judge_numeric(PTS[1], '10.8')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[1], '9.4')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[1], '9.3')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[3], '919.0')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[3], '920.0')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[9], '-253.0')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[9], '-253.1')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[18], '30.35')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[18], '30.36')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[28], '495.0')[0], 'PASS')        # dc amps 10 A: printed +-5.0 (tighter than the accuracy), judged as printed
        self.assertEqual(h.judge_numeric(PTS[28], '494.9')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[34], '2540')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[34], '2541')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[21], '491')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[21], '490')[0], 'FAIL')
        self.assertAlmostEqual(h.judge_numeric(PTS[18], '30.00')[1], 30000.0)  # kΩ typed, base units ohm
        self.assertAlmostEqual(h.judge_numeric(PTS[10], '50.0')[1], 0.05)      # mV typed, base units V
        self.assertAlmostEqual(h.judge_numeric(PTS[22], '900')[1], 0.0009)     # µF typed, base units F


class Prompts(unittest.TestCase):
    def test_function_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([sw for _n, sw in f.functions()], FUNCTION_PROMPTS)
        self.assertEqual([int(n) for n, _sw in f.functions()], FUNCTION_POINTS)
        for i, e in enumerate(f.events):
            if e[0] == 'function':
                nxt = [x for x in f.events[i + 1:] if x[0] in ('point', 'function')][0]
                self.assertEqual(nxt, ('point', int(e[1])))
                if i and f.events[i - 1][0] == 'setup':
                    self.assertEqual(f.events[i - 1][1], int(e[1]))          # the cable change comes first, then the dial

    def test_cable_change_prompts(self):
        f = Flow(MODEL)
        f.run()
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], CABLE_POINTS)       # VOHM, the coil moves between AUX and 20 A, the iFlex leads, the iFlex loop on the coil

    def test_no_double_function_prompt(self):
        f = Flow(MODEL)
        f.run()
        seq = [sw for _n, sw in f.functions()]
        self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])))
        self.assertEqual(len(seq), 8)

    def test_high_voltage_prompts_never_mention_a_ramp_and_come_once_per_group(self):
        f = Flow(MODEL, calibrator=True)
        f.run()
        hv = [p['n'] for p in f.app.points if f.app._high_voltage(p)]
        self.assertEqual(hv, [2, 3, 4, 5, 7, 8])     # 30 V and above: 500 V and 900 V; the mV, iFlex simulation (<= 750 mV) and coil points are not high voltage
        texts = [e[1] for e in f.events if e[0] == 'hv']
        self.assertEqual(len(texts), 1)
        self.assertFalse([t for t in texts if 'ramp' in t])

    def test_prompt_counts_per_full_run_before_and_after_hv_once_per_group(self):
        """Per full 376 run: cable 8 + function 8 + high voltage + reading 38.  hv_once_per_group on (this spec): 1 high-voltage question; off (the per-point rule of the
        other handhelds): 6, one per point of 30 V and above.  Total 55 against 60."""
        def counts(once):
            f = Flow(MODEL, calibrator=True)
            f.spec['options']['hv_once_per_group'] = once
            f.run()
            return (sum(1 for e in f.events if e[0] == 'setup'), len(f.functions()), sum(1 for e in f.events if e[0] == 'hv'), sum(1 for e in f.events if e[0] == 'point'))
        self.assertEqual(counts(True), (8, 8, 1, 38))
        self.assertEqual(counts(False), (8, 8, 6, 38))
        self.assertEqual(sum(counts(True)), 55)
        self.assertEqual(sum(counts(False)), 60)

    def test_other_models_prompt_sequences(self):
        for model, funcs, cables, points in (('374', 7, 8, 28), ('375', 8, 8, 34), ('376-II', 8, 8, 38)):
            f = Flow(model)
            f.run()
            self.assertEqual(len([e for e in f.events if e[0] == 'point']), points, model)
            self.assertEqual(len(f.functions()), funcs, model)               # the 374 has no mV position change: 7 function prompts, the 375 and the 376-II 8
            self.assertEqual(len([e for e in f.events if e[0] == 'setup']), cables, model)

    def test_direct_high_voltage_one_out_command(self):
        io, t = _io('5522A')
        for n in (3, 8):
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
        t.reject = (OUT_COMMANDS[25].upper(),)
        with self.assertRaises(Exception):
            io.apply(PTS[25])
        self.assertNotIn('OPER', t.sent)
        self.assertEqual(sum(1 for c in t.sent if c == OUT_COMMANDS[25]), 1)

    def test_every_output_is_inside_the_published_calibrator_specifications(self):
        """calibrator_fit: the 5522A, the 5520A and the 5560A sheets cover all 38 outputs (the coil, its compliance and the iFlex input are NOT part of that check: UNVERIFIED)."""
        import calibrator_fit as cf
        reqs = cf.handheld_requests(list(PTS.values()))
        self.assertEqual(len(reqs), 38)
        for model in ('5522A', '5520A', '5560A'):
            self.assertEqual([r.key for r in reqs if not cf.check(model, r).ok], [], model)

    def test_no_new_calibrator_command(self):
        """Every calibrator command this procedure sends is an existing registry command; nothing new was added."""
        import cmdreg
        from drivers import Fluke5522A, Fluke5560A
        for cls in (Fluke5560A, Fluke5522A):
            reg = cmdreg.merge_commands(cls)
            for key in ('out.ohms', 'out.volts.hz', 'out.volts.dc', 'out.amps.hz', 'out.amps.dc', 'out.cap.uf', 'oper.stby', 'oper.on', 'err.query'):
                self.assertIn(key, reg, key)
        reg = cmdreg.merge_commands(Fluke5560A)
        self.assertTrue(reg['out.ohms'].verified and reg['out.volts.hz'].verified and reg['out.volts.dc'].verified)
        self.assertFalse(reg['out.amps.dc'].verified)                              # current outputs on a 5560A: not verified (listed in NOTES.md)
        self.assertFalse(reg['out.cap.uf'].verified)                               # capacitance on a 5560A: not verified


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
        app.asset.set('A-376')
        app.serial.set('S-376')
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

    def test_perfect_meter_passes_all_38_with_either_calibrator(self):
        for model in ('5522A', '5560A'):
            app, io = self.run_perfect(model)
            self.assertEqual(len(app.found), 38, model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertTrue(all(not r['synthetic'] and r['data'] == 'As Found' and r['source'] == 'typed' for r in app.found.values()))
            self.assertEqual(app.found['1-1']['entered'], '10.0')           # padded to the resolution
            self.assertEqual(app.found['1-16']['entered'], '3000')
            self.assertEqual(app.found['1-18']['entered'], '30.00')
            self.assertEqual(app.found['1-9']['entered'], '-250.0')
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_wire_log(self):
        app, io = self.run_perfect('5522A')
        texts = [t for _i, t in H.wire(io)]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(outs, [OUT_COMMANDS[n] for n in range(1, 39)])          # every point once, in manual order, none repeated
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))               # reset before the first point
        self.assertEqual(texts[-1], 'STBY')                                        # left in standby
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b], 'standby between two points')
        for n in range(1, 39):
            if PTS[n]['kind'] in ('DCV', 'DCI'):
                self.assertTrue(outs[n - 1].endswith(',0Hz'), outs[n - 1])          # every DC output carries an explicit 0 Hz
        self.assertEqual(sum(1 for t in texts if t == 'OPER'), 38)

    def test_prompts_and_hv_dialogs(self):
        app, io = self.run_perfect('5522A')
        titles = [d[1] for d in self.hn.dialogs if d[0] == 'confirm']
        self.assertEqual(titles.count('Change the cables'), 8)
        self.assertEqual(titles.count('Change the function'), 8)
        hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(hv), 1)                                   # options.hv_once_per_group: ONE question for the VOHM hook-up group (6 points of 30 V and above)
        self.assertFalse([d for d in hv if 'ramp' in d[3]])
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
        self.assertEqual(sum(1 for d in cables if 'REMOVE the test leads' in ' '.join(d[3])), 6)       # the four coil hook-ups (AUX, 20 A, twice) and the two iFlex loop hook-ups
        self.assertEqual(len([d for d in self.hn.dialogs if d[0] == 'reading']), 38)

    def test_out_of_tolerance_fails_and_is_reported(self):
        app, io = self.make('5522A')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['1-3'] = '920.0'
        self.hn.readings['1-25'] = '881.4'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['1-25', '1-3'])

    def test_report_is_calibration_data_named_asset_date(self):
        app, io = self.run_perfect('5522A')
        out, seen, text = self.pdf(app)
        import ui_theme as ui
        self.assertEqual(seen['initialfile'], ui.report_filename('A-376'))
        self.assertRegex(seen['initialfile'], r'^A-376-\d\d-\d\d-\d{4}\.pdf$')
        self.assertIn('Calibration Data', text)
        self.assertNotIn('Performance Verification', text)
        self.assertIn('Fluke 376', text)
        flat = ' '.join(text.split())
        self.assertIn('999.9 A, 18 A x 50 turns', flat)
        self.assertIn('2500 A, 75 mV applied', flat)
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))          # a real run is never marked demo
        self.assertRegex(text, r'Uncertainty\s+TAR\s+TUR')
        self.assertNotIn('Cover', text)
        self.assertNotIn('Due', text.replace('Due Date', ''))                      # no standards-due tracking on the report body
        # every one of the 38 points carries an uncertainty; TAR and TUR on all but the five iFlex simulation points (a tolerance in amps is never divided by volts)
        rows = app.certificate_rows()
        self.assertEqual(len(rows), 38)
        self.assertTrue(all(r['Uncertainty'] != '' for r in rows), [r['Description'] for r in rows if not r['Uncertainty']])
        fields = [app.certificate_fields(p) for p in app.points]
        for p, f in zip(app.points, fields):
            if p['n'] in IFLEX_SIM:
                self.assertEqual((f['TAR'], f['TUR']), ('', ''), p['n'])
            else:
                self.assertTrue(f['TAR'] != '' and f['TUR'] != '', (p['n'], f))

    def test_current_uncertainty_is_the_calibrators_at_the_output_current_unscaled(self):
        """Owner-chosen convention: Uncertainty = the regular calibrator current uncertainty at point / 50 (no x50, no coil); TAR / TUR use it as it is."""
        import report_pdf
        app, io = self.run_perfect('5522A')
        rows = app.certificate_rows()
        for p, r in zip(app.points, rows):
            if p['n'] in COIL_POINTS:
                q = dict(kind=p['kind'], nominal=p['applied']['value'], frequency=p['applied'].get('frequency'), unit='A', range=None)
                self.assertEqual(r['Uncertainty'], report_pdf.point_uncertainty(q, standard=app.calibrator_model()), p['n'])
                self.assertIn('NOT multiplied by 50', p['note'])
        self.assertFalse(set(PTS) - {p['n'] for p in app.points})

    def test_iflex_simulation_uncertainty_is_the_calibrators_ac_volts_in_volts(self):
        """The simulation rows are sourced as AC volts and read in amps: the Uncertainty is the calibrator's AC VOLTS uncertainty, worded in volts (not amps)."""
        import report_pdf
        for model in ('5522A', '5560A'):
            app, io = self.run_perfect(model)
            rows = app.certificate_rows()
            for p, r in zip(app.points, rows):
                if p['n'] in IFLEX_SIM:
                    q = dict(kind='ACV', nominal=p['applied']['value'], frequency=p['applied']['frequency'], unit='V', range=None)
                    want = report_pdf.point_uncertainty(q, standard=app.calibrator_model())
                    self.assertTrue(want.endswith('V'), want)
                    self.assertEqual(r['Uncertainty'], want, (model, p['n']))
                    self.assertNotRegex(r['Uncertainty'], r'A$')
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_the_unc_unit_key_changes_nothing_for_other_specs(self):
        for name in ('fluke_77iv_pv.json', 'fluke_87v_pv.json', 'fluke_170_series_pv.json', 'fluke_110_series_pv.json', 'fluke_365_pv.json', 'fluke_287_289_pv.json', 'klein_mm325_pv.json'):
            spec = json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))
            self.assertFalse([s['id'] for s in spec['steps'] if 'unc_unit' in s], name)

    def test_other_specs_keep_the_per_point_high_voltage_question(self):
        for name in ('fluke_77iv_pv.json', 'fluke_87v_pv.json', 'fluke_170_series_pv.json', 'fluke_110_series_pv.json'):
            self.assertNotIn('hv_once_per_group', json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8')).get('options', {}), name)
        self.assertIs(SPEC['options']['hv_once_per_group'], True)

    def test_demo_never_produces_real_looking_evidence(self):
        app, _ = self.make(demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 38)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(app.any_synthetic())
        out, seen, text = self.pdf(app)
        self.assertIn('DEMO', text.upper())


if __name__ == '__main__':
    unittest.main()
