"""Fluke 374 / 375 / 376 / 376-II clamp meter performance verification (Procedures/Fluke_37x_Verification.py -> iflex_option.main(MODEL, spec=...), a subclass of the shared handheld
engine that adds the 'iFlex probe supplied' window option; specs/fluke_376_pv.json built by specs/build_fluke_376_spec.py from the Calibration Manual, Table 1, printed pp. 3-4, and the
374 FC / 375 FC / 376 FC Users Manual, printed pp. 20-26, for the accuracy).  The 376 is the model of the detailed tests; the 374, 375 and 376-II have their own classes below.

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
    1: ('10 V AC @ 50 Hz', 'XXX', '9.4', '10.7'), 2: ('500 V AC @ 50 Hz', 'XXX', '492.0', '508.0'), 3: ('900 V AC @ 50 Hz', '--X', '882', '919'),
    4: ('500 V AC @ 500 Hz', 'XXX', '492.0', '508.0'),
    5: ('-500 V DC', 'XXX', '-505.5', '-494.5'), 6: ('10 V DC', 'XXX', '9.4', '10.6'), 7: ('500 V DC', 'XXX', '494.5', '505.5'), 8: ('900 V DC', '--X', '886', '914'),
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
FUNCTION_PROMPTS = ['V~  (AC volts)', 'V⎓  (DC volts)',
                    'mV⎓  (DC millivolts: dial on V⎓ / mV, then press the yellow button to select mV; Users Manual p. 12)',
                    'Ω  (ohms: the Ω position, shared with continuity and capacitance; the display must show Ω)',
                    'Capacitance ⊣⊢  (dial on the Ω position, then press the yellow button ONCE to select capacitance (display shows µF); Users Manual p. 14, single press owner-confirmed)',
                    'A~  (AC amps: detachable jaw closed around the 50-turn coil)',
                    'A⎓  (DC amps: detachable jaw closed around the 50-turn coil; the yellow button is ZERO, Users Manual p. 11)',
                    'iFlex A~  (dial on iFlex A~; the iFlex probe plugged in, or the simulation leads)']
# rows whose printed limit is not the full or half accuracy printed in the Users Manual (specs/build_fluke_376_spec.py): flagged per model, never changed
_LOOSE = {'376': 'looser', '376-II': 'looser'}
FLAGGED = {1: {'374': 'rounded', '375': 'rounded', **_LOOSE}, 2: _LOOSE, 3: _LOOSE, 4: _LOOSE,
           28: {m: 'tighter' for m in MODELS}, 29: {m: 'tighter' for m in ('376', '376-II')}, 36: {m: 'tighter' for m in MODELS}, 37: {m: 'tighter' for m in MODELS}}
IFLEX_SIM = (30, 31, 32, 33, 34)
IFLEX_POINTS = IFLEX_SIM + (35, 36, 37, 38)
# the Users Manual (R3 ENG) accuracy as read from the page images: (percent of reading, digits, printed page) by model
UM_ACCURACY = {'ACV': {'374': ('1.5', 5, 24), '375': ('1.5', 5, 24), '376': ('1', 5, 24)}, 'DCV': ('1', 5, 24), 'MV': ('1', 5, 24), 'OHM': ('1', 5, 26), 'CAP': ('1', 4, 26),
               'ACA50': ('2', 5, 20), 'ACA440': ('2.5', 5, 20), 'DCA': ('2', 5, 23), 'IFLEX': ('3', 5, 21)}
COIL_POINTS = tuple(range(23, 30)) + (35, 36, 37, 38)
# cable-change prompts: the group changes at these points (VOHM, then the coil terminals alternate, then the iFlex leads, then the iFlex loop on the coil)
CABLE_POINTS = [1, 23, 24, 27, 28, 30, 35, 36]
FUNCTION_POINTS = [1, 5, 9, 13, 20, 23, 27, 30]


def setUpModule():
    """tkinter is stubbed here, not at import time (see tests/test_87v_points.py)."""
    global h, H, Flow, SPECS, Spy, SPEC, PTS, BUILDER, X
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import iflex_option as _x
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy, X = _h, _H, _o.Flow, _o.SPECS, _o.Spy, _x
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

    def test_accuracy_table_is_the_users_manual(self):
        """The builder's accuracy table (ACC) is the 374 FC / 375 FC / 376 FC Users Manual (pp. 20-26), per model; the 376-II (not in that manual) uses the 376 FC figures."""
        for key, want in UM_ACCURACY.items():
            for m in MODELS:
                w = want[{'376-II': '376'}.get(m, m)] if key == 'ACV' else want
                self.assertEqual(BUILDER.ACC[m][key], w[:2], (key, m))
            self.assertEqual(BUILDER.ACC_PAGE[key], f'p. {(want["376"] if key == "ACV" else want)[2]}', key)
        self.assertNotIn('fluke.com', (ROOT / 'specs' / 'build_fluke_376_spec.py').read_text(encoding='utf-8'))
        self.assertNotIn('fluke.com', json.dumps(SPEC))

    def test_limits_against_the_users_manual_accuracy(self):
        """Every printed limit against the Users Manual accuracy, per model; the builder classifies each row.  Flagged rows are stored AS PRINTED."""
        steps, problems, flagged = BUILDER.build_steps()
        self.assertEqual(problems, [])
        self.assertEqual({int(f[0].split('-')[1]): {m: v for m, v in f[8].items() if v in ('tighter', 'rounded', 'looser')} for f in flagged}, FLAGGED)
        self.assertEqual({n: sorted(p['check']['models']) for n, p in PTS.items() if 'check' in p}, {n: sorted(d) for n, d in FLAGGED.items()})
        self.assertEqual({n: {m: c['verdict'] for m, c in p['check']['models'].items()} for n, p in PTS.items() if 'check' in p}, FLAGGED)
        side = lambda n, m: PTS[n]['check']['models'][m]['printed_vs_spec']
        self.assertEqual(side(1, '374'), [dict(side='high', printed='0.7', half_spec='0.325', full_spec='0.65')])        # 1.5 %: 10 V high 10.7 vs 10.65 (rounded)
        self.assertEqual(side(1, '376'), [dict(side='high', printed='0.7', half_spec='0.3', full_spec='0.6')])          # 1 %: +-0.6 V; 10.7 is looser
        self.assertEqual(side(2, '376'), [dict(side=s_, printed='8', half_spec='2.75', full_spec='5.5') for s_ in ('low', 'high')])       # 500 V: printed +-8.0 (1.5 %) vs +-5.5 (1 %)
        self.assertEqual(side(3, '376-II'), [dict(side='low', printed='18', half_spec='7', full_spec='14'), dict(side='high', printed='19', half_spec='7', full_spec='14')])
        self.assertEqual(side(4, '376'), side(2, '376'))
        self.assertEqual([(c['printed'], c['half_spec']) for c in side(28, '374')], [('5', '5.25')] * 2)               # dc amps 10 A: +-5.0 vs +-10.5 (half 5.25)
        self.assertEqual([(c['printed'], c['half_spec']) for c in side(37, '375')], [('13', '13.75')] * 2)             # iFlex with coil 18 A
        for n in FLAGGED:                                            # printed limits kept: nothing was corrected
            self.assertEqual((PTS[n]['low'], PTS[n]['high']), TABLE_1[n][2:], n)
            self.assertIn('CHECK (printed limit not changed', PTS[n]['note'])
            self.assertIn('Users Manual', PTS[n]['note'])
        self.assertFalse([n for n, p in PTS.items() if 'printed_limits' in p])
        # every row/model not flagged is the full accuracy or half of it, to within half a display step; every flagged one is as flagged (independent arithmetic)
        for n, p in PTS.items():
            key, res = BUILDER.ROWS[n - 1][10], D(BUILDER.ROWS[n - 1][11])
            for m in p['models']:
                pct, digits = (UM_ACCURACY[key][{'376-II': '376'}.get(m, m)] if key == 'ACV' else UM_ACCURACY[key])[:2]
                full = D(pct) / 100 * abs(D(NOMINAL[n])) + digits * res
                got = (D(NOMINAL[n]) - D(p['low']), D(p['high']) - D(NOMINAL[n]))
                if m in FLAGGED.get(n, {}):
                    kinds = {'looser': any(g > full + res / 2 for g in got), 'rounded': any(full < g <= full + res / 2 for g in got),
                             'tighter': not all(abs(g - full) <= res / 2 or abs(g - full / 2) <= res / 2 for g in got)}
                    self.assertTrue(kinds[FLAGGED[n][m]], (n, m, got, full))
                else:
                    for g in got:
                        self.assertTrue(abs(g - full) <= res / 2 or abs(g - full / 2) <= res / 2, (n, m, g, full))

    def test_builder_flags_a_limit_looser_than_the_accuracy(self):
        info, verdict = BUILDER.check_row('10', '9.0', '11.0', BUILDER.ACC['376']['ACV'], '0.1')       # +-1.0 V: wider than +-0.6 V
        self.assertEqual(verdict, 'looser')
        self.assertTrue(info)
        self.assertEqual(BUILDER.check_row('500', '492.0', '508.0', BUILDER.ACC['374']['ACV'], '0.1'), ([], 'full'))
        self.assertEqual(BUILDER.check_row('500', '492.0', '508.0', BUILDER.ACC['376']['ACV'], '0.1')[1], 'looser')      # the same printed limit is looser for a 1 % meter

    def test_the_builder_aborts_on_an_unexpected_verdict(self):
        saved = dict(BUILDER.EXPECTED_FLAGS)
        try:
            BUILDER.EXPECTED_FLAGS.pop(2)
            self.assertTrue(BUILDER.build_steps()[1])
        finally:
            BUILDER.EXPECTED_FLAGS.clear()
            BUILDER.EXPECTED_FLAGS.update(saved)

    def test_whole_volts_on_the_1000_v_range(self):
        """900 V rows (1000 V range, 1 V resolution): limits stored and shown as whole volts, the printed text (one decimal) kept."""
        for n, low, high, printed in ((3, '882', '919', ('882.0', '919.0')), (8, '886', '914', ('886.0', '914.0'))):
            p = PTS[n]
            self.assertEqual((p['low'], p['high'], p['range']), (low, high, '1000 V'))
            self.assertEqual((p['printed_text']['low'], p['printed_text']['high']), printed)
            self.assertEqual(h.pad_reading(p, '900'), '900')
            self.assertEqual(D(p['low']), D(printed[0]))
            self.assertEqual(D(p['high']), D(printed[1]))
        self.assertEqual({PTS[n]['printed_text']['low'] for n in (3, 8)}, {'882.0', '886.0'})

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_the_coil_points(self):
        """Table 1 p. 4: the calibrator drives a 50-turn coil and the limits are meter readings (50 x the calibrator current)."""
        for n, p in PTS.items():
            if n in COIL_POINTS:
                self.assertIn(p['kind'], ('ACI', 'DCI'))
                self.assertEqual(D(str(p['applied']['value'])) * 50, D(str(p['nominal'])), n)
                self.assertNotIn('no_uncertainty', p, n)             # every current point carries an uncertainty, the 5500A/COIL's (AC below 20.5 A: none printed, see test_coil_uncertainty)
                self.assertIn('A2LA-5500A-COIL', p['note'], n)
                self.assertEqual((p['unc_standard'], p['unc_nominal']), ('A2LA-5500A-COIL', p['nominal']), n)
                self.assertIn('50 turns', p['report_desc'])
                self.assertIn('50-turn coil', h.describe(p))
                self.assertNotIn('unc_unit', p)
                self.assertEqual(p['range'], '2500 A' if p['section'] == 'iFlex with coil' else '', n)       # the jaw range is per model (600.0 / 999.9 A, Users Manual p. 20)
        self.assertEqual({n: p['applied']['value'] for n, p in PTS.items() if n in COIL_POINTS},
                         {23: 0.2, 24: 10.0, 25: 18.0, 26: 6.0, 27: 0.2, 28: 10.0, 29: 18.0, 35: 0.2, 36: 10.0, 37: 18.0, 38: 6.0})

    def test_current_uncertainty_is_looked_up_at_the_applied_current_below_the_coil_cmc_rows(self):
        """Every ACI / DCI point is looked up at the calibrator current (18 A at most), below the 20.5 A at which the lab CMC table's coil lines (coil-standard-2) start,
        so those rows never touch this procedure; the meter reading (up to 900 A) is never the lookup value."""
        amps = [p['applied']['value'] for p in PTS.values() if p['kind'] in ('ACI', 'DCI')]
        self.assertEqual(len(amps), 11)
        self.assertLess(max(amps), 20.5)
        self.assertEqual(max(amps), 18.0)

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
        self.assertEqual([d['id'] for d in o['include_toggles']], ['iflex'])
        self.assertIs(o['include_toggles'][0]['default'], True)         # a meter that has an iFlex gets every test
        self.assertEqual(o['include_toggles'][0]['off_text'], 'not tested (no iFlex supplied); the iFlex simulation points are still tested')
        self.assertEqual([p['n'] for p in PTS.values() if p.get('include') == 'iflex'], [35, 36, 37, 38])
        self.assertFalse([p for p in PTS.values() if p.get('include') and p['section'] not in ('iFlex simulated', 'iFlex with coil')])

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
        self.assertIn('UNVERIFIED', ' '.join(' '.join(s) for s in SPEC['groups']['COIL_AUX']['steps']))      # how the jaw sits on the coil: still unverified
        sim = ' '.join(' '.join(s) for s in SPEC['groups']['IFLEX_SIM']['steps'])
        self.assertIn('owner-confirmed', sim)                       # the far-left 2 mm jack is the iFlex input: no longer UNVERIFIED
        self.assertNotIn('UNVERIFIED', sim)
        notes = ' '.join(p['note'] for p in PTS.values() if p['applied']['frequency'] == 440 or p['applied']['value'] == 18)
        self.assertIn('owner-confirmed', notes)                     # 6 A at 440 Hz and 18 A: the coil and calibrator can do them
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

    def test_sidecars_are_automated_verifications_one_per_model(self):
        import procscan
        want = {'374': ('Fluke_374_Verification', 36), '375': ('Fluke_375_Verification', 37), '376': ('Fluke_376_Verification', 35), '376-II': ('Fluke_376II_Verification', 38)}
        found = {x.id: x for x in procscan.procs(ROOT) if x.id.startswith('Fluke_37')}
        self.assertEqual(sorted(found), sorted(v[0] for v in want.values()))
        for model, (pid, order) in want.items():
            p = found[pid]
            self.assertEqual(p.effective_kind, 'verification', pid)          # Manager rows classify under Automated Calibrations
            self.assertNotIn('Manual', p.name)
            self.assertEqual((p.model, p.category, p.name), (model, 'Clamp Meter', f'Fluke {model} Clamp Meter Performance Verification'), pid)
            self.assertIn('Fluke 374 / 375 / 376 / 376-II Clamp Meter Performance Verification', p.description, pid)       # the family title
            self.assertEqual((p.hookup_meter, p.diagram_prefixes), ('fluke376', ('hook_fluke376',)), pid)
            self.assertIn('hookups.py#fluke376', p.fingerprint_code)         # only this meter's slice of hookups.py: no other procedure is touched
            self.assertIn('iflex_option.py', p.fingerprint_code)
            self.assertEqual(p.fingerprint_spec, (f'specs/fluke_376_pv.json#{model}',), pid)
            self.assertEqual(p.specs, ('specs/fluke_376_pv.json',))
            self.assertEqual(p.order, order)
            for rel in p.own_files:
                self.assertTrue((ROOT / rel).is_file(), rel)
            self.assertTrue((ROOT / p.launcher).is_file())

    def test_the_launchers_name_the_engine(self):
        for model, pid in (('374', 'Fluke_374_Verification'), ('375', 'Fluke_375_Verification'), ('376', 'Fluke_376_Verification'), ('376-II', 'Fluke_376II_Verification')):
            text = (ROOT / 'Procedures' / f'{pid}.py').read_text(encoding='utf-8')
            self.assertIn('iflex_option.main(MODEL, spec=SPEC)', text, pid)
            self.assertIn("SPEC = 'fluke_376_pv.json'", text, pid)
            self.assertIn(f"MODEL = '{model}'", text, pid)
        self.assertIs(h.App.QUEUE_SUPPORTED, True)               # the shared engine is untouched: the run queue is on for the other handhelds
        self.assertIs(X.App.QUEUE_SUPPORTED, True)               # the run queue is on; the iFlex setting is per queue meter (tests/test_fluke_376_queue.py)
        self.assertTrue(issubclass(X.App, h.App))


class Padding(unittest.TestCase):
    def test_typed_readings_are_padded_to_the_resolution(self):
        for n, typed, want in ((1, '10', '10.0'), (3, '900', '900'), (8, '900', '900'), (9, '-250', '-250.0'), (16, '3000', '3000'), (18, '30', '30.00'), (19, '54', '54.00'),
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
        self.assertEqual(h.judge_numeric(PTS[3], '919')[0], 'PASS')
        self.assertEqual(h.judge_numeric(PTS[3], '920')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[3], '881')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS[3], '882')[0], 'PASS')
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

    def make(self, model='5522A', demo=False, meter=None):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {model}', 'sim', transport=Spy(bench, model))
            io.auto_ramp = False
        app = X.App(self.hn.root, meter or MODEL, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
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
        self.assertIn('Jaw, 18 A x 50 turns', flat)
        self.assertIn('iFlex, 18 A x 50 turns', flat)
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

    def test_coil_point_uncertainty_is_the_5500a_coil_sheet_at_the_effective_current(self):
        """Owner decision 2026-10-26: the 50-turn coil points use the A2LA 5500A/COIL sheet at the effective (meter) current, never the calibrator's at the coil current."""
        import report_pdf
        app, io = self.run_perfect('5522A')
        rows = app.certificate_rows()
        for p, r in zip(app.points, rows):
            if p['n'] in COIL_POINTS:
                if p['n'] in (23, 35):                                       # AC 10 A: below the coil's 20.5 A AC lines -> the calibrator's uncertainty at the sourced current (owner, 2026-10-26)
                    q = dict(kind=p['kind'], nominal=p['applied']['value'], frequency=p['applied'].get('frequency'), unit='A', range=None)
                    self.assertEqual(r['Uncertainty'], report_pdf.point_uncertainty(q, standard=app.calibrator_model()), p['n'])
                else:
                    q = dict(kind=p['kind'], nominal=p['nominal'], frequency=p['applied'].get('frequency'), unit='A', range=None, extra=app.unc_extra(p))
                    self.assertTrue(app.unc_extra(p), p['n'])                 # the clamp / coil interaction is part of every covered coil point
                    self.assertEqual(r['Uncertainty'], report_pdf.point_uncertainty(q, standard='A2LA-5500A-COIL'), p['n'])
                self.assertIn('A2LA-5500A-COIL', p['note'])
        by_n = {p['n']: r for p, r in zip(app.points, rows)}
        self.assertEqual(by_n[23]['Uncertainty'], '150 µA')                # below the coil range: the calibrator at 0.2 A
        self.assertEqual(by_n[24]['Uncertainty'], '5.0 A')                 # 500 A AC 50 Hz: the coil's 0.8 % (4.0 A) RSS the clamp / coil interaction (3.0 A)
        self.assertEqual(by_n[27]['Uncertainty'], '560 mA')                # 10 A DC: the coil's 1.0 mA RSS the interaction (0.55 A)
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


OFF_COUNTS = {'374': 24, '375': 30, '376': 34, '376-II': 34}
ON_COUNTS = {'374': 28, '375': 34, '376': 38, '376-II': 38}


def _off_points(model):
    pts = [p for p in h.points_for(SPEC, model) if p.get('include') != 'iflex']
    for n, p in enumerate(pts, 1):
        p['n'] = n
    return pts


def _flow(model, off=False, calibrator=True, once=True):
    f = Flow(model, calibrator=calibrator)
    f.spec['options']['hv_once_per_group'] = once
    if off:
        f.app.points = _off_points(model)
    f.run()
    return f


def _prompt_counts(f):
    return dict(cable=sum(1 for e in f.events if e[0] == 'setup'), function=len(f.functions()), hv=sum(1 for e in f.events if e[0] == 'hv'), reading=sum(1 for e in f.events if e[0] == 'point'))


class IFlexPrompts(unittest.TestCase):
    """Prompt counts with the iFlex option ON and OFF, per model (the same prompt flow the engine runs, dialogs recorded)."""
    def test_counts_per_model_on_and_off(self):
        want = {('374', False): (8, 7, 1, 28), ('374', True): (6, 7, 1, 24), ('375', False): (8, 8, 1, 34), ('375', True): (6, 8, 1, 30),
                ('376', False): (8, 8, 1, 38), ('376', True): (6, 8, 1, 34), ('376-II', False): (8, 8, 1, 38), ('376-II', True): (6, 8, 1, 34)}
        for (model, off), counts in want.items():
            got = _prompt_counts(_flow(model, off))
            self.assertEqual((got['cable'], got['function'], got['hv'], got['reading']), counts, (model, off))
        totals = {k: sum(v) for k, v in want.items()}
        self.assertEqual((totals[('376', False)], totals[('376', True)]), (55, 49))
        self.assertEqual({m: (totals[(m, False)], totals[(m, True)]) for m in MODELS}, {'374': (44, 38), '375': (51, 45), '376': (55, 49), '376-II': (55, 49)})

    def test_off_never_asks_for_an_iflex_prompt(self):
        for model in MODELS:
            f = _flow(model, True)
            self.assertEqual([e[1] for e in f.events if e[0] == 'point'], list(range(1, OFF_COUNTS[model] + 1)), model)       # renumbered, no gap
            self.assertEqual(len([sw for _n, sw in f.functions() if 'iFlex' in sw]), 1, model)      # only the simulation function prompt stays
            self.assertFalse([e for e in f.events if e[0] == 'setup' and e[1] > OFF_COUNTS[model]], model)
            self.assertTrue(all(p.get('include') != 'iflex' for p in f.app.points), model)

    def test_off_376_cable_and_function_points(self):
        f = _flow('376', True)
        self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], [1, 23, 24, 27, 28, 30])      # VOHM, the coil AUX / 20 A moves, the iFlex simulation leads; no iFlex loop
        self.assertEqual([int(n) for n, _sw in f.functions()], [1, 5, 9, 13, 20, 23, 27, 30])
        self.assertEqual([sw for _n, sw in f.functions()], FUNCTION_PROMPTS[:8])

    def test_per_point_rule_counts(self):
        """With the per-point high-voltage rule of the other handhelds the 376 asks 6 times either way (no iFlex point is high voltage): 60 ON, 47 OFF."""
        on, off = _prompt_counts(_flow('376', False, once=False)), _prompt_counts(_flow('376', True, once=False))
        self.assertEqual((sum(on.values()), sum(off.values())), (60, 54))


class IFlexOption(unittest.TestCase):
    """The window option on the real App (iflex_option.App) and the simulated bench."""
    def setUp(self):
        self.hn = H.Harness().start()
        EndToEnd.make = EndToEnd.make

    def tearDown(self):
        self.hn.stop()

    def make(self, meter=MODEL, cal='5522A', demo=False):
        return EndToEnd.make(self, cal, demo=demo, meter=meter)

    def ask(self, kind='askyesno'):
        return [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'Skip the iFlex tests']

    def pdf(self, app):
        return EndToEnd.pdf(self, app)

    def test_default_is_on_and_nothing_is_skipped(self):
        for model in MODELS:
            app, _ = self.make(meter=model)
            self.assertTrue(app.include_is_on('iflex'))
            self.assertEqual(len(app.points), ON_COUNTS[model], model)
            self.assertEqual(app._include_vars['iflex'].get(), True)
            self.assertIn('ON', app.include_text())
            self.assertEqual(sum(1 for p in app.points if p.get('include') == 'iflex'), 4, model)      # all four models have the 4 iFlex-with-coil points; the 5 simulation points are never tagged

    def test_off_asks_first_says_what_happens_and_changes_the_list(self):
        app, _ = self.make()
        self.assertTrue(app.set_include('iflex', False))
        q = self.ask()
        self.assertEqual(len(q), 1)
        self.assertIn('4 iFlex point(s) will not be run', q[0][3])
        self.assertIn('not tested (no iFlex supplied)', q[0][3])
        self.assertEqual(len(app.points), 34)
        self.assertEqual([p['n'] for p in app.points], list(range(1, 35)))
        self.assertEqual(set(app.by_id), {p['id'] for p in app.points})
        self.assertIn('OFF', app.include_text())
        self.assertIn('iFlex simulated', [p['section'] for p in app.points])              # the simulation points stay
        self.assertFalse([p for p in app.points if 'iFlex, ' in p.get('desc', '')])
        self.assertTrue(app.set_include('iflex', True, ask=False))
        self.assertEqual(len(app.points), 38)
        self.assertEqual([p['id'] for p in app.points], [f'1-{n}' for n in range(1, 39)])        # back in manual order, ids unchanged
        self.assertFalse(app.set_include('iflex', True))                                           # no change, no entry in the log
        self.assertEqual([e['value'] for e in app._include_log], [False, True])

    def test_declining_keeps_it_on(self):
        app, _ = self.make()
        self.hn.box_answer['askyesno'] = False
        var = app._include_vars['iflex']
        var.set(False)                                              # the operator clicks the box ...
        app._on_include_click('iflex')                              # ... the question is answered No
        self.assertTrue(app.include_is_on('iflex'))
        self.assertEqual(var.get(), True)
        self.assertEqual(len(app.points), 38)
        self.assertEqual(app._include_log, [])

    def test_a_click_applies_the_box(self):
        app, _ = self.make()
        app._include_vars['iflex'].set(False)
        app._on_include_click('iflex')
        self.assertFalse(app.include_is_on('iflex'))
        self.assertEqual(app._include_vars['iflex'].get(), False)
        self.assertEqual(len(app.points), 34)

    def test_it_cannot_change_during_a_run(self):
        app, _ = self.make()
        app.busy = True
        self.assertFalse(app.set_include('iflex', False))
        self.assertTrue(app.include_is_on('iflex'))
        self.assertEqual(len(app.points), 38)
        self.assertEqual(self.ask(), [])
        app._include_vars['iflex'].set(False)
        app._on_include_click('iflex')
        self.assertEqual(app._include_vars['iflex'].get(), True)           # the box shows the setting in force
        app.busy = False

    def test_full_run_off_for_every_model(self):
        for model in MODELS:
            app, io = self.make(meter=model)
            self.assertTrue(app.set_include('iflex', False))
            self.hn.default_reading = H.typed_nominal
            self.assertTrue(self.hn.run_all(), model)
            self.assertEqual(len(app.found), OFF_COUNTS[model], model)
            self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, model)
            self.assertFalse([k for k in app.found if int(k.split('-')[1]) >= 35], model)           # no iFlex-with-coil point was run (the simulation points 1-30..1-34 are)
            texts = [t for _i, t in H.wire(io)]
            outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
            self.assertEqual(outs, [OUT_COMMANDS[int(p['id'].split('-')[1])] for p in app.points], model)         # not a single iFlex-with-coil output
            self.assertEqual(texts[-1], 'STBY', model)
            titles = [d[1] for d in self.hn.dialogs if d[0] == 'confirm']
            self.assertEqual(titles.count('Change the cables'), 6, model)
            self.assertEqual(titles.count('Change the function'), {'374': 7}.get(model, 8), model)
            self.assertEqual(len([d for d in self.hn.dialogs if d[0] == 'reading']), OFF_COUNTS[model], model)
            self.assertFalse([d for d in self.hn.dialogs if d[0] == 'confirm' and ('iFlex' in ' '.join(d[3]) or 'iFlex' in str(d[2])) and 'imulat' not in str(d[2])], model)      # only the iFlex SIMULATION prompts remain
            self.assertEqual(len([d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']), 1, model)
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_full_run_on_for_every_model(self):
        for model in MODELS:
            app, io = self.make(meter=model)
            self.hn.default_reading = H.typed_nominal
            self.assertTrue(self.hn.run_all(), model)
            self.assertEqual(len(app.found), ON_COUNTS[model], model)
            titles = [d[1] for d in self.hn.dialogs if d[0] == 'confirm']
            self.assertEqual(titles.count('Change the cables'), 8, model)
            self.assertEqual(titles.count('Change the function'), 7 if model == '374' else 8, model)
            self.assertEqual(self.ask(), [], model)                              # ON: nothing was asked
            self.hn.stop()
            self.hn = H.Harness().start()

    def test_turning_it_off_after_readings_keeps_them(self):
        app, io = self.make()
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 38)
        for n in range(36, 39):                                     # only the first iFlex-with-coil point (1-35) keeps a reading
            del app.found[f'1-{n}']
        self.assertTrue(app.set_include('iflex', False))
        self.assertIn('1 reading(s) already recorded stay', self.ask()[0][3])
        self.assertEqual(len(app.points), 35)                       # 34 + the recorded 1-35
        self.assertEqual(app.points[-1]['id'], '1-35')
        self.assertEqual(len(app.found), 35)                        # nothing was discarded
        self.assertEqual(app.found['1-35']['result'], 'PASS')
        self.assertIn('1 recorded earlier kept', app.include_text())
        self.assertEqual(app._include_log[-1]['recorded'], 35)
        rows = app.certificate_rows()
        self.assertEqual(len(rows), 35)                             # the recorded iFlex reading stays in the report
        header = dict(app.report_header(app.spec['source']))
        self.assertIn('1 reading(s) recorded before it was turned off are included', header['iFlex tests'])

    def test_checkpoint_round_trip_of_the_setting(self):
        app, io = self.make()
        self.assertTrue(app.set_include('iflex', False))
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        app.save()
        path = app._checkpoint_path()
        data = json.loads(path.read_text())
        self.assertEqual(data['include'], {'iflex': False})
        self.assertEqual([(e['id'], e['value']) for e in data['include_log']], [('iflex', False)])
        self.assertEqual(len(data['results']), 34)
        self.assertEqual(data['model'], '376')
        # a new window: default ON; loading the progress file restores OFF and the 29-point list
        app2, _ = self.make()
        self.assertTrue(app2.include_is_on('iflex'))
        self.assertEqual(len(app2.points), 38)
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertFalse(app2.include_is_on('iflex'))
        self.assertEqual(len(app2.points), 34)
        self.assertEqual(app2._include_vars['iflex'].get(), False)
        self.assertEqual(len(app2.found), 34)
        self.assertEqual(app2._include_log, app._include_log)
        # ... and a progress file saved ON puts it back ON, and one saved before the option existed (no 'include' key) is ON
        data['include'] = {'iflex': True}
        path.write_text(json.dumps(data))
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertTrue(app2.include_is_on('iflex'))
        self.assertEqual(len(app2.points), 38)
        app2.set_include('iflex', False, ask=False)                 # (saves the progress of this window over the file, so the old-format file is written after it)
        data.pop('include')
        data.pop('include_log')
        path.write_text(json.dumps(data))
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertTrue(app2.include_is_on('iflex'))                # the default, never a silent skip
        self.assertEqual(app2._include_log, [])

    def test_a_checkpoint_off_with_a_recorded_iflex_point_loads_it(self):
        app, io = self.make()
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        app.found.pop('1-35')
        app._include['iflex'] = False
        app.save()
        app2, _ = self.make()
        with mock.patch.object(h.filedialog, 'askopenfilename', lambda **k: str(app._checkpoint_path())):
            app2.load()
        self.assertFalse(app2.include_is_on('iflex'))
        self.assertEqual(len(app2.points), 34 + 3)                  # the 3 recorded iFlex-with-coil readings are kept, the missing 1-35 is not asked for
        self.assertNotIn('1-35', app2.by_id)

    def test_pdf_with_the_iflex_tests_on(self):
        app, io = self.make()
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        out, seen, text = self.pdf(app)
        flat = ' '.join(text.split())
        self.assertIn('iFlex tests: Tested (iFlex supplied)', flat)
        self.assertNotIn('Not tested', flat)
        self.assertIn('iFlex, 18 A x 50 turns', flat)
        self.assertIn('2500 A, 75 mV applied', flat)
        self.assertEqual(len(app.certificate_rows()), 38)
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))
        self.assertIn('Calibration Data', text)

    def test_pdf_with_the_iflex_tests_off(self):
        app, io = self.make()
        self.assertTrue(app.set_include('iflex', False))
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        out, seen, text = self.pdf(app)
        import ui_theme as ui
        self.assertEqual(seen['initialfile'], ui.report_filename('A-376'))          # named asset#-date, as always
        flat = ' '.join(text.split())
        self.assertIn('iFlex tests: Not tested (no iFlex supplied)', flat)
        self.assertNotIn('iFlex, 18 A', flat)                                        # the points that were not run have no row
        self.assertIn('mV applied', flat)                                          # the simulation points are still in the report
        self.assertIn('Jaw, 18 A x 50 turns', flat)
        self.assertEqual(len(app.certificate_rows()), 34)
        self.assertNotIn('Cover', text)
        self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))             # a real run is never marked demo
        self.assertIn('RESULT: PASS', text.upper())
        self.assertNotIn('PENDING', text.upper())                                    # not shown as failed or pending
        self.assertIn('not tested (no iFlex supplied); the iFlex simulation points are still tested', app.source_note())          # the report note repeats the setting

    def test_demo_off_stays_demo(self):
        app, _ = self.make(demo=True)
        self.assertTrue(app.set_include('iflex', False))
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 34)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        out, seen, text = self.pdf(app)
        self.assertIn('DEMO', text.upper())
        self.assertIn('Not tested (no iFlex supplied)', ' '.join(text.split()))

    def test_a_spec_without_the_option_runs_like_the_engine(self):
        spec = h.load_spec(SPEC_NAME)
        spec['options'].pop('include_toggles')
        app = X.App(self.hn.root, MODEL, spec=spec)
        self.assertEqual(len(app.points), 38)
        self.assertFalse(hasattr(app, 'include_bar'))
        self.assertEqual(app.save_fields().keys(), h.App.save_fields(app).keys())
        self.assertEqual(app.report_header(spec['source']), h.App.report_header(app, spec['source']))

    def test_run_queue_is_offered_and_a_single_meter_is_not_a_queue(self):
        app, _ = self.make()
        self.assertTrue(app.queue_supported())
        self.assertFalse(app.queue_wants_run())                  # no meters listed: the procedure runs as a single-meter run


if __name__ == '__main__':
    unittest.main()
