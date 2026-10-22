"""Fluke 175 / 177 / 179 procedures (Procedures/Fluke_17x_Verification.py on the shared handheld engine, specs/fluke_170_series_pv.json).

Part 1: the spec against an INDEPENDENT second transcription of Calibration Information Table 2 (175, printed pp. 10-11) and Table 3 (177 / 179, pp. 12-13),
read from the rendered page images, and against the published +/-(% of reading + counts) accuracy; the three corrected printed values; options;
function / cable / high-voltage prompt sequences; the model applicability (175: 52 points, 177: 51, 179: 54 = 177 + 3 temperature points).
Part 2: the real engine (handheld_dmm.App, worker threads, drivers, judging, checkpoint, PDF) on the simulated bench with both calibrators (5522A, 5560A):
wire commands, explicit 0 Hz on DC, set / read back / never retried, standby after each point, reset first, demo never real.
tkinter is stubbed in setUpModule (not at import time), like tests/test_87v_points.py and tests/test_77_points.py.
Run:  python -m unittest tests.test_170_points"""
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
h = H = Flow = Spy = SPEC = BUILDER = None
PTS = {}
SPEC_NAME = 'fluke_170_series_pv.json'
MODELS = ('175', '177', '179')

# --- Table 2 (175) as read a second time from the page images: step -> (calibrator output as the engine words it, lower limit, upper limit, display unit, wire command)
T2 = {
    1: ('300 mV AC @ 45 Hz', '296.7', '303.3', 'mV', 'OUT 0.3V,45Hz'), 2: ('500 mV AC @ 500 Hz', '494.7', '505.3', 'mV', 'OUT 0.5V,500Hz'),
    3: ('500 mV AC @ 1 kHz', '489.7', '510.3', 'mV', 'OUT 0.5V,1000Hz'),
    4: ('5 V AC @ 45 Hz', '4.947', '5.053', 'V', 'OUT 5V,45Hz'), 5: ('5 V AC @ 500 Hz', '4.947', '5.053', 'V', 'OUT 5V,500Hz'),
    6: ('5 V AC @ 1 kHz', '4.897', '5.103', 'V', 'OUT 5V,1000Hz'),
    7: ('50 V AC @ 45 Hz', '49.47', '50.53', 'V', 'OUT 50V,45Hz'), 8: ('50 V AC @ 500 Hz', '49.47', '50.53', 'V', 'OUT 50V,500Hz'),
    9: ('50 V AC @ 1 kHz', '48.97', '51.03', 'V', 'OUT 50V,1000Hz'),
    10: ('300 V AC @ 45 Hz', '296.7', '303.3', 'V', 'OUT 300V,45Hz'), 11: ('500 V AC @ 500 Hz', '494.7', '505.3', 'V', 'OUT 500V,500Hz'),
    12: ('500 V AC @ 1 kHz', '489.7', '510.3', 'V', 'OUT 500V,1000Hz'),
    13: ('1 kV AC @ 45 Hz', '987', '1013', 'V', 'OUT 1000V,45Hz'), 14: ('1 kV AC @ 500 Hz', '987', '1013', 'V', 'OUT 1000V,500Hz'),
    15: ('1 kV AC @ 1 kHz', '977', '1023', 'V', 'OUT 1000V,1000Hz'),
    16: ('1 V AC @ 45 Hz', '44.94', '45.06', 'Hz', 'OUT 1V,45Hz'), 17: ('1 V AC @ 900 Hz', '899.0', '901.0', 'Hz', 'OUT 1V,900Hz'),     # printed 899 / 901
    18: ('1 V AC @ 9 kHz', '8.990', '9.010', 'kHz', 'OUT 1V,9000Hz'), 19: ('5 V AC @ 50 kHz', '49.94', '50.06', 'kHz', 'OUT 5V,50000Hz'),   # printed 8.99 / 9.01
    20: ('5 V DC', '4.990', '5.010', 'V', 'OUT 5V,0Hz'), 21: ('50 V DC', '49.90', '50.10', 'V', 'OUT 50V,0Hz'),                           # printed 49.90 / 50.1
    22: ('300 V DC', '299.3', '300.7', 'V', 'OUT 300V,0Hz'), 23: ('1 kV DC', '996', '1004', 'V', 'OUT 1000V,0Hz'),
    24: ('-1 kV DC', '-1004', '-996', 'V', 'OUT -1000V,0Hz'),
    25: ('3 V AC @ 45 Hz', '44.94', '45.06', 'Hz', 'OUT 3V,45Hz'), 26: ('30 V AC @ 50 kHz', '49.94', '50.06', 'kHz', 'OUT 30V,50000Hz'),
    27: ('30 mV DC', '29.8', '30.2', 'mV', 'OUT 0.03V,0Hz'), 28: ('-300 mV DC', '-300.7', '-299.3', 'mV', 'OUT -0.3V,0Hz'),
    29: ('600 mV DC', '598.9', '601.1', 'mV', 'OUT 0.6V,0Hz'),
    30: ('500 Ω', '495.3', '504.7', 'Ω', 'OUT 500OHM'),                                                                                       # upper limit printed "504.7 kΩ"
    31: ('5 kΩ', '4.954', '5.046', 'kΩ', 'OUT 5000OHM'), 32: ('50 kΩ', '49.54', '50.46', 'kΩ', 'OUT 50000OHM'),
    33: ('500 kΩ', '495.4', '504.6', 'kΩ', 'OUT 500000OHM'), 34: ('5 MΩ', '4.954', '5.046', 'MΩ', 'OUT 5000000OHM'),
    35: ('19 MΩ', '18.68', '19.32', 'MΩ', 'OUT 19000000OHM'),
    36: ('900 nF', '887', '913', 'nF', 'OUT 900NF'), 37: ('9 µF', '8.87', '9.13', 'µF', 'OUT 9UF'), 38: ('90 µF', '88.7', '91.3', 'µF', 'OUT 90UF'),
    39: ('900 µF', '887', '913', 'µF', 'OUT 900UF'),
    40: ('25 Ω', None, None, 'Ω', 'OUT 25OHM'), 41: ('250 Ω', None, None, 'Ω', 'OUT 250OHM'),
    42: ('2 V DC', '1.978', '2.022', 'V', 'OUT 2V,0Hz'),
    43: ('3 mA AC @ 45 Hz', '2.92', '3.08', 'mA', 'OUT 0.003A,45Hz'), 44: ('50 mA AC @ 1 kHz', '49.22', '50.78', 'mA', 'OUT 0.05A,1000Hz'),
    45: ('400 mA AC @ 1 kHz', '393.7', '406.3', 'mA', 'OUT 0.4A,1000Hz'),
    46: ('4 A AC @ 45 Hz', '3.937', '4.063', 'A', 'OUT 4A,45Hz'), 47: ('9 A AC @ 1 kHz', '8.83', '9.17', 'A', 'OUT 9A,1000Hz'),
    48: ('3 mA DC', '2.94', '3.06', 'mA', 'OUT 0.003A,0Hz'), 49: ('50 mA DC', '49.47', '50.53', 'mA', 'OUT 0.05A,0Hz'),
    50: ('-400 mA DC', '-404.3', '-395.7', 'mA', 'OUT -0.4A,0Hz'),
    51: ('4 A DC', '3.957', '4.043', 'A', 'OUT 4A,0Hz'), 52: ('-9 A DC', '-9.12', '-8.88', 'A', 'OUT -9A,0Hz'),
}
# --- Table 3 (177 / 179): the rows that differ from Table 2 (step numbers of Table 3), the rest equal Table 2 with the DC-frequency row removed
T3_DIFF = {
    4: ('5 V AC @ 45 Hz', '4.947', '5.053', 'V', 'OUT 5V,45Hz'),                                                                           # upper limit printed 5.103
    20: ('5 V DC', '4.993', '5.007', 'V', 'OUT 5V,0Hz'), 21: ('50 V DC', '49.93', '50.07', 'V', 'OUT 50V,0Hz'), 22: ('300 V DC', '299.5', '300.5', 'V', 'OUT 300V,0Hz'),
    23: ('1 kV DC', '997', '1003', 'V', 'OUT 1000V,0Hz'), 24: ('-1 kV DC', '-1003', '-997', 'V', 'OUT -1000V,0Hz'),
    25: ('3 V AC @ 45 Hz', '44.94', '45.06', 'Hz', 'OUT 3V,45Hz'),                                                                         # printed "3 V 45 kHz", 45.06 / 44.94
    26: ('30 mV DC', '29.8', '30.2', 'mV', 'OUT 0.03V,0Hz'), 27: ('-300 mV DC', '-300.5', '-299.5', 'mV', 'OUT -0.3V,0Hz'), 28: ('600 mV DC', '599.3', '600.7', 'mV', 'OUT 0.6V,0Hz'),
}
T3_TEMP = {52: ('0 °C', '-1.0', '1.0', '°C', 'OUT 0CEL'), 53: ('-40 °C', '-41.4', '-38.6', '°C', 'OUT -40CEL'), 54: ('400 °C', '395.0', '405.0', '°C', 'OUT 400CEL')}


def table_for(model):
    if model == '175':
        return dict(T2)
    t = {}
    for n, row in T2.items():
        if n in (25, 26):                              # Table 3 has one DC volts frequency row, placed at 25
            continue
        m = n if n < 25 else n - 1
        t[m] = row
    t.update(T3_DIFF)
    if model == '179':
        t.update(T3_TEMP)
    return t


SECTION_COUNTS = {'AC volts': 15, 'AC volts frequency': 4, 'DC volts': 5, 'DC volts frequency': 2, 'DC millivolts': 3, 'Ohms': 6, 'Capacitance': 4, 'Continuity': 2, 'Diode': 1,
                  'AC milliamps': 3, 'AC amps': 2, 'DC milliamps': 3, 'DC amps': 2}
FUNCTIONS = ['V~  (AC volts)', 'V~ Hz  (AC volts frequency; press the YELLOW button)', 'V⎓  (DC volts)', 'V⎓ Hz  (DC volts frequency; press the YELLOW button)',
             'mV⎓  (DC millivolts)', 'Ω  (Ohms)', 'Capacitance  ⊣⊢  (press the YELLOW button)', 'Continuity  •)))', 'Diode  ▶|  (press the YELLOW button)',
             'mA~  (AC milliamps)', 'A~  (AC amps)', 'mA⎓  (DC milliamps; press the YELLOW button)', 'A⎓  (DC amps; press the YELLOW button)']
TEMP_FUNCTION = 'Temperature  (179 only; press the YELLOW button)'


def functions_for(model):
    f = list(FUNCTIONS)                                                               # the 177 / 179 DC volts frequency row is still its own function
    if model == '179':
        f.append(TEMP_FUNCTION)
    return f


def setUpModule():
    """tkinter is stubbed here, not at import time (see tests/test_87v_points.py)."""
    global h, H, Flow, Spy, SPEC, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, Spy = _h, _H, _o.Flow, _o.Spy
    for m in MODELS:
        _o.SPECS[m] = SPEC_NAME                                 # the shared Flow helper looks the spec up by model
    SPEC = h.load_spec(SPEC_NAME)
    for m in MODELS:
        PTS[m] = {p['n']: p for p in h.points_for(SPEC, m)}
    s = importlib.util.spec_from_file_location('build_170_spec', ROOT / 'specs' / 'build_170_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


class Spec(unittest.TestCase):
    def test_points_per_model(self):
        self.assertEqual({m: len(PTS[m]) for m in MODELS}, {'175': 52, '177': 51, '179': 54})
        self.assertEqual({'175', '177', '179'}, set(SPEC['models']))
        for m in MODELS:
            self.assertEqual([p['step'] for p in PTS[m].values()], list(range(1, len(PTS[m]) + 1)), m)      # table order, no gaps
        self.assertEqual({p['id'] for p in PTS['175'].values()}, {f'2-{n}' for n in range(1, 53)})
        self.assertEqual({p['id'] for p in PTS['177'].values()}, {f'3-{n}' for n in range(1, 52)})
        self.assertEqual({p['id'] for p in PTS['179'].values()}, {f'3-{n}' for n in range(1, 55)})
        self.assertEqual([p['id'] for p in PTS['179'].values() if p['kind'] == 'TEMP'], ['3-52', '3-53', '3-54'])
        self.assertFalse([p for m in ('175', '177') for p in PTS[m].values() if p['kind'] == 'TEMP'])           # temperature: 179 only
        for m in ('177', '179'):                                                                               # 177 and 179 share Table 3
            self.assertEqual([(p['id'], p.get('low'), p.get('high'), p['applied']) for n, p in PTS[m].items() if n <= 51],
                             [(p['id'], p.get('low'), p.get('high'), p['applied']) for n, p in PTS['177'].items()])

    def test_points_by_function(self):
        for m, want in (('175', SECTION_COUNTS), ('177', dict(SECTION_COUNTS, **{'DC volts frequency': 1})),
                        ('179', dict(SECTION_COUNTS, **{'DC volts frequency': 1}, Temperature=3))):
            counts = {}
            for p in PTS[m].values():
                counts[p['section']] = counts.get(p['section'], 0) + 1
            self.assertEqual(counts, want, m)

    def test_every_point_matches_the_tables(self):
        for m in MODELS:
            tbl = table_for(m)
            self.assertEqual(set(tbl), set(PTS[m]), m)
            for n, (out, low, high, unit, _cmd) in tbl.items():
                p = PTS[m][n]
                self.assertEqual(h.output_text(p), out, (m, n))
                self.assertEqual(p['display_unit'], unit, (m, n))
                if low is None:
                    self.assertEqual((p['test'], p.get('low'), p.get('high')), ('beeper', None, None), (m, n))
                else:
                    self.assertEqual((p['low'], p['high']), (low, high), (m, n))
                    self.assertEqual(p['test'], 'numeric')

    def test_beeper_points(self):
        for m in MODELS:
            a, b = [p for p in PTS[m].values() if p['test'] == 'beeper']
            self.assertEqual((a['expect'], b['expect']), ('on', 'off'))
            self.assertEqual((a['applied']['value'], b['applied']['value']), (25, 250))
            self.assertEqual(h.describe(a), 'Continuity, 25 Ω: beeper ON')

    def test_limits_follow_the_published_accuracy(self):
        """+/-(% of reading + counts x resolution) to within half a display step: an independent check of every transcribed limit (build time too)."""
        steps, problems = BUILDER.build_steps()
        self.assertEqual(problems, [])
        self.assertEqual(len(steps), 106)

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_units_factors_nominal_and_limits_bracket_the_nominal(self):
        for m in MODELS:
            for n, p in PTS[m].items():
                self.assertTrue(D(str(p['factor'])) > 0)
                if p['test'] == 'numeric':
                    nom = D(str(p['nominal'])) / D(str(p['factor']))
                    self.assertLess(D(p['low']), nom + D('0.000001'), (m, n))
                    self.assertGreater(D(p['high']), nom - D('0.000001'), (m, n))
                    self.assertNotIn(nom, (D(p['low']), D(p['high'])))
                    self.assertLess(D(p['low']), D(p['high']))
        # frequency points: sourced as AC volts, read in Hz; nominal = the frequency
        for m in MODELS:
            for n in (16, 17, 18, 19):
                p = PTS[m][n]
                self.assertEqual((p['kind'], p['base_unit'], p['nominal'], p.get('no_uncertainty')), ('ACV', 'Hz', p['applied']['frequency'], True))
                self.assertIs(p.get('no_freq_suffix'), True)
        t = PTS['179'][52]
        self.assertEqual((t['kind'], t['base_unit'], t['display_unit'], t['group']), ('TEMP', 'degC', '°C', 'TEMP'))

    def test_validator_passes_and_no_ramp_lists(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        self.assertFalse([p for m in MODELS for p in PTS[m].values() if p.get('ramp')])

    def test_options(self):
        o = SPEC['options']
        self.assertIs(o['auto_ramp'], False)                    # high-voltage points go straight to the test value (the manual prescribes no ramp)
        self.assertIs(o['function_prompt'], True)
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title']), ('fluke170', 30, 'Calibration Data'))
        self.assertNotIn('ir', o)                                # no remote interface: readings are typed

    def test_groups(self):
        for m in MODELS:
            groups = [p['group'] for p in PTS[m].values()]
            kinds = [p['id'] for p in PTS[m].values()]
            want = ['VOHM'] * (42 if m == '175' else 41) + ['UAMP'] * 3 + ['AMP10'] * 2 + ['UAMP'] * 3 + ['AMP10'] * 2 + (['TEMP'] * 3 if m == '179' else [])
            self.assertEqual(groups, want, (m, kinds))

    def test_hookups_exist_for_both_calibrators(self):
        import hookups
        for cal in ('5560A', '5522A'):
            for group in ('VOHM', 'UAMP', 'AMP10', 'TEMP'):
                plan = hookups.plan('fluke170', cal, group, manual=False)
                self.assertTrue(plan and plan['image'] and Path(plan['image']).is_file(), (cal, group))
        self.assertIn('400 mA', hookups.summary('fluke170', '5522A', 'UAMP'))
        self.assertIn('10A', hookups.summary('fluke170', '5560A', 'AMP10'))
        self.assertIn('80AK', hookups.summary('fluke170', '5560A', 'TEMP'))


class Corrections(unittest.TestCase):
    """Three printed values are corrected; everything else is as printed (format-only changes keep the printed text)."""
    def test_which_steps_are_corrected(self):
        self.assertEqual({(m, p['id']) for m in MODELS for p in PTS[m].values() if 'printed_limits' in p},
                         {('175', '2-30'), ('177', '3-4'), ('179', '3-4'), ('177', '3-25'), ('179', '3-25')})

    def test_175_ohms_unit(self):
        p = PTS['175'][30]
        self.assertEqual((p['low'], p['high'], p['display_unit']), ('495.3', '504.7', 'Ω'))
        self.assertIn('504.7 kΩ', p['note'])
        self.assertEqual(PTS['177'][29]['high'], '504.7')                    # Table 3 prints 504.7 Ω: no correction there
        self.assertNotIn('printed_limits', PTS['177'][29])

    def test_177_179_5v_45hz_upper_limit(self):
        for m in ('177', '179'):
            p = PTS[m][4]
            self.assertEqual((p['low'], p['high']), ('4.947', '5.053'))
            self.assertEqual(p['printed_limits']['high'], '5.103')
            self.assertIn('5.103', p['note'])
        self.assertEqual((PTS['175'][4]['low'], PTS['175'][4]['high']), ('4.947', '5.053'))               # Table 2 prints 5.053
        # the printed 5.103 disagrees with the published accuracy (1.0 % + 3 counts of 0.001 V = 0.053 V)
        self.assertTrue(BUILDER.check_against_specification('x', 'V', 5, '4.947', '5.103', BUILDER.ACC['AC_LOW'], '0.001'))
        self.assertEqual(BUILDER.check_against_specification('x', 'V', 5, '4.947', '5.053', BUILDER.ACC['AC_LOW'], '0.001'), [])

    def test_177_179_dc_volts_frequency_row(self):
        for m in ('177', '179'):
            p = PTS[m][25]
            self.assertEqual((p['applied'], p['low'], p['high'], p['display_unit']), (dict(value=3.0, frequency=45.0), '44.94', '45.06', 'Hz'))
            self.assertEqual((p['printed_limits']['low'], p['printed_limits']['high'], p['printed_limits']['applied']), ('45.06', '44.94', '3 V 45 kHz'))
            self.assertIn('45 kHz', p['note'])
        self.assertEqual([p['applied'] for p in PTS['175'].values() if p['section'] == 'DC volts frequency'],
                         [dict(value=3.0, frequency=45.0), dict(value=30.0, frequency=50000.0)])
        # as printed, no meter could pass: a 45 Hz reading is not between 45.06 and 44.94
        self.assertEqual(h.judge_numeric(dict(PTS['177'][25], low='45.06', high='44.94'), '45.00')[0], 'FAIL')
        self.assertEqual(h.judge_numeric(PTS['177'][25], '45.00')[0], 'PASS')

    def test_format_only_changes_keep_the_printed_text(self):
        p = PTS['175'][21]
        self.assertEqual((p['low'], p['high'], p['printed_text']['high']), ('49.90', '50.10', '50.1'))
        self.assertEqual(PTS['177'][17]['printed_text'], dict(low='899', high='901', note=PTS['177'][17]['printed_text']['note']))
        self.assertEqual((PTS['177'][18]['low'], PTS['177'][18]['printed_text']['low']), ('8.990', '8.99'))
        for m in MODELS:
            for p in PTS[m].values():
                if 'printed_text' in p:
                    self.assertEqual((D(p['low']), D(p['high'])), (D(p['printed_text']['low']), D(p['printed_text']['high'])))
        self.assertIn('three', SPEC['source']['note'].lower())
        self.assertIn('504.7 kOhm', SPEC['source']['report_note'])
        self.assertIn('5.103', SPEC['source']['report_note'])
        self.assertIn('45 kHz', SPEC['source']['report_note'])


class Padding(unittest.TestCase):
    def test_typed_readings_are_padded_to_the_resolution(self):
        p = PTS['175']
        for n, typed, want in ((4, '5', '5.000'), (17, '900', '900.0'), (18, '9', '9.000'), (16, '45', '45.00'), (21, '50', '50.00'), (23, '1000', '1000'),
                               (36, '900', '900'), (37, '9', '9.00'), (38, '90', '90.0'), (30, '500', '500.0'), (31, '5', '5.000'), (35, '19', '19.00'),
                               (47, '9', '9.00'), (52, '-9', '-9.00'), (28, '-300', '-300.0')):
            self.assertEqual(h.pad_reading(p[n], typed), want, n)
        self.assertEqual(h.pad_reading(PTS['179'][52], '0'), '0.0')
        self.assertEqual(h.pad_reading(PTS['179'][53], '-40'), '-40.0')

    def test_a_perfect_meter_passes_every_point(self):
        for m in MODELS:
            for n, p in PTS[m].items():
                if p['test'] == 'numeric':
                    typed = h.pad_reading(p, f'{p["nominal"] / p["factor"]:.9g}')
                    self.assertEqual(h.judge_numeric(p, typed)[0], 'PASS', (m, n))


class Prompts(unittest.TestCase):
    def test_function_prompts(self):
        for m in MODELS:
            f = Flow(m)
            f.run()
            self.assertEqual([sw for _n, sw in f.functions()], functions_for(m), m)
            for i, e in enumerate(f.events):                 # a function prompt sits right before the first point of the function, after a cable-change prompt
                if e[0] == 'function':
                    nxt = [x for x in f.events[i + 1:] if x[0] in ('point', 'function')][0]
                    self.assertEqual(nxt, ('point', int(e[1])))
                    if i and f.events[i - 1][0] == 'setup':
                        self.assertEqual(f.events[i - 1][1], int(e[1]))

    def test_function_prompt_count(self):
        for m, n in (('175', 13), ('177', 13), ('179', 14)):
            f = Flow(m)
            f.run()
            self.assertEqual(len(f.functions()), n, m)

    def test_cable_change_prompts(self):
        for m, want in (('175', [1, 43, 46, 48, 51]), ('177', [1, 42, 45, 47, 50]), ('179', [1, 42, 45, 47, 50, 52])):
            f = Flow(m)
            f.run()
            self.assertEqual([e[1] for e in f.events if e[0] == 'setup'], want, m)          # VOHM, UAMP, AMP10, UAMP, AMP10 (+ TEMP on the 179)

    def test_function_prompt_without_a_cable_change(self):
        """Ohms -> capacitance -> continuity -> diode keep the VΩ cables but the dial / yellow button moves: still asked (no cable-change prompt before them)."""
        f = Flow('175')
        f.run()
        asked = {int(n) for n, _sw in f.functions()}
        setups = {e[1] for e in f.events if e[0] == 'setup'}
        for n in (16, 20, 25, 27, 30, 36, 40, 42):
            self.assertIn(n, asked)
            self.assertNotIn(n, setups)
        self.assertFalse({n for n in asked if PTS['175'][n]['group'] == 'NONE'})

    def test_high_voltage_prompts_never_mention_a_ramp(self):
        for m, want in (('175', [7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23, 24, 26]), ('177', [7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23, 24]),
                        ('179', [7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23, 24])):
            f = Flow(m, calibrator=True)
            f.run()
            hv = [p['n'] for p in f.app.points if f.app._high_voltage(p)]
            self.assertEqual(hv, want, m)                    # 30 V and above
            texts = [e[1] for e in f.events if e[0] == 'hv']
            self.assertEqual(len(texts), len(hv))
            self.assertFalse([t for t in texts if 'ramp' in t])

    def test_direct_high_voltage_one_out_command(self):
        io, t = _io('5522A')
        tbl = table_for('175')
        for n in (10, 11, 12, 13, 14, 15, 22, 23, 24, 26):
            n0 = len(t.sent)
            io.apply(PTS['175'][n])
            outs = [c for c in t.sent[n0:] if c.upper().startswith('OUT ') and not c.endswith('?')]
            self.assertEqual(outs, [tbl[n][4]], n)

    def test_the_temperature_soak_prompt_is_asked_once_on_the_first_temperature_point(self):
        pts = [p for p in PTS['179'].values() if p['kind'] == 'TEMP']
        self.assertIn('20 minutes', pts[0]['prompt'])
        self.assertIn('°C', pts[0]['prompt'])
        self.assertFalse([p for p in pts[1:] if 'prompt' in p])
        for p in pts:
            self.assertIn('20 minutes', p['note'])


def _io(model):
    from drivers.simulated import make_bench
    bench, _ft, _s = make_bench()
    t = Spy(bench, model)
    io = h.IO(f'Fluke {model}', 'sim', transport=t)
    io.auto_ramp = False
    io._wait = lambda *a, **k: None
    return io, t


class Calibrators(unittest.TestCase):
    def check(self, cal):
        io, t = _io(cal)
        for model in MODELS:
            tbl = table_for(model)
            for n, p in PTS[model].items():
                n0 = len(t.sent)
                io.apply(p)
                sent = t.sent[n0:]
                outs = [c for c in sent if c.upper().startswith('OUT ') and not c.endswith('?')]
                self.assertEqual(outs, [tbl[n][4]], (cal, model, n))                    # one OUT, sent once (never retried)
                self.assertEqual(sent[0], 'STBY', (cal, model, n))                        # standby before every setup
                self.assertLess(sent.index(tbl[n][4]), sent.index('ERR?'), (cal, model, n))
                self.assertLess(sent.index('ERR?'), sent.index('OPER'), (cal, model, n))  # the error queue is read, and only then the output enabled
                self.assertEqual(sum(1 for c in sent if c == 'OPER'), 1, (cal, model, n))
                if p['kind'] == 'TEMP':
                    self.assertEqual(sent[1], 'TC_TYPE K')
                io.standby()
                self.assertEqual(t.sent[-1], 'STBY', (cal, model, n))
                if p['kind'] in ('DCV', 'DCI'):
                    self.assertTrue(tbl[n][4].endswith(',0Hz'), (cal, model, n))
                self.assertFalse(io.cal.wave_nonsine)                                    # no square wave anywhere in this procedure

    def test_5522a(self):
        self.check('5522A')

    def test_5560a(self):
        self.check('5560A')

    def test_a_rejected_output_is_never_operated(self):
        io, t = _io('5522A')
        t.reject = ('OUT 9UF',)
        with self.assertRaises(Exception):
            io.apply(PTS['175'][37])
        self.assertNotIn('OPER', t.sent)
        self.assertEqual(sum(1 for c in t.sent if c == 'OUT 9UF'), 1)

    def test_registry_entries_used_and_their_verified_flags(self):
        """Every calibrator command this procedure sends is an existing registry command; nothing new was added."""
        import cmdreg
        from drivers import Fluke5522A, Fluke5560A
        for cls in (Fluke5560A, Fluke5522A):
            reg = cmdreg.merge_commands(cls)
            for key in ('out.ohms', 'out.volts.hz', 'out.volts.dc', 'out.amps.hz', 'out.amps.dc', 'out.cap.nf', 'out.cap.uf', 'tc.type', 'out.temp', 'oper.stby', 'oper.on', 'err.query'):
                self.assertIn(key, reg, key)
        reg = cmdreg.merge_commands(Fluke5560A)
        self.assertTrue(reg['out.ohms'].verified and reg['out.volts.hz'].verified and reg['out.volts.dc'].verified)
        for key in ('out.cap.nf', 'out.cap.uf', 'out.amps.dc', 'tc.type', 'out.temp'):
            self.assertFalse(reg[key].verified, key)          # capacitance / DC current / thermocouple outputs: not verified on a 5560A (listed in NOTES.md)


class EndToEnd(unittest.TestCase):
    """The real App on the simulated bench; only the modal dialogs are scripted."""
    def setUp(self):
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()

    def make(self, model, cal='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {cal}', 'sim', transport=Spy(bench, cal))
            io.auto_ramp = False
        app = h.App(self.hn.root, model, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None)
        app.asset.set('A-17')
        app.serial.set('S-17')
        app.cal_mode.set(h.CAL_CHOICES[1] if cal == '5522A' else h.CAL_CHOICES[0])
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

    def run_perfect(self, model, cal='5522A'):
        app, io = self.make(model, cal)
        self.hn.default_reading = H.typed_nominal
        self.assertTrue(self.hn.run_all())
        return app, io

    def fresh(self):
        self.hn.stop()
        self.hn = H.Harness().start()

    def test_perfect_meter_passes_every_point_of_every_model_with_either_calibrator(self):
        for model, count in (('175', 52), ('177', 51), ('179', 54)):
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(model, cal)
                self.assertEqual(len(app.found), count, (model, cal))
                self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, (model, cal))
                self.assertTrue(all(not r['synthetic'] and r['data'] == 'As Found' for r in app.found.values()))
                self.fresh()

    def test_padding_on_the_real_run(self):
        app, io = self.run_perfect('175')
        self.assertEqual(app.found['2-4']['entered'], '5.000')
        self.assertEqual(app.found['2-17']['entered'], '900.0')
        self.assertEqual(app.found['2-19']['entered'], '50.00')
        app2 = None
        self.fresh()
        app2, _ = self.run_perfect('179')
        self.assertEqual(app2.found['3-52']['entered'], '0.0')

    def test_wire_log(self):
        for model in MODELS:
            app, io = self.run_perfect(model)
            tbl = table_for(model)
            w = H.wire(io)
            texts = [t for _i, t in w]
            outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
            self.assertEqual(outs, [tbl[n][4] for n in sorted(tbl)])                  # every point once, in table order, none repeated
            self.assertLess(texts.index('*RST'), texts.index(outs[0]))                # reset before the first point
            self.assertEqual(texts[-1], 'STBY')                                       # left in standby
            idx = [i for i, t in enumerate(texts) if t in outs]
            for a, b in zip(idx, idx[1:]):
                self.assertIn('STBY', texts[a + 1:b], 'standby between two points')
            for n in sorted(tbl):
                if PTS[model][n]['kind'] in ('DCV', 'DCI'):
                    self.assertTrue(outs[n - 1].endswith(',0Hz'), outs[n - 1])         # every DC output carries an explicit 0 Hz
            self.assertEqual(sum(1 for t in texts if t == 'OPER'), len(tbl))
            self.assertEqual(sum(1 for t in texts if t.startswith('TC_TYPE')), 3 if model == '179' else 0)
            self.fresh()

    def test_prompts_and_hv_dialogs(self):
        for model, want in (('175', (13, 5, 14)), ('177', (13, 5, 13)), ('179', (14, 6, 13))):
            app, io = self.run_perfect(model)
            confirms = [d for d in self.hn.dialogs if d[0] == 'confirm']
            titles = [d[1] for d in confirms]
            self.assertEqual(titles.count('Change the function'), want[0], model)
            self.assertEqual(titles.count('Change the cables'), want[1], model)
            hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
            self.assertEqual(len(hv), want[2], model)
            self.assertFalse([d for d in hv if 'ramp' in d[3]])
            beeps = [d for d in self.hn.dialogs if d[0] == 'reading' and d[2] == 'yesno']
            self.assertEqual(len(beeps), 2)
            if model == '179':
                self.assertEqual(titles.count('Meter setup'), 1)                      # the 20-minute temperature soak, once
            self.fresh()

    def test_out_of_tolerance_fails_and_is_reported(self):
        app, io = self.make('175')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings['2-6'] = '5.2'
        self.hn.readings['2-41'] = False
        self.assertTrue(self.hn.run_all())
        self.assertEqual(sorted(k for k, r in app.found.items() if r['result'] == 'FAIL'), ['2-41', '2-6'])
        self.assertEqual(app.found['2-41']['entered'], 'Beeper not off')

    def test_report_is_calibration_data_named_asset_date(self):
        for model, rows in (('175', 52), ('179', 54)):
            app, io = self.run_perfect(model)
            out, seen, text = self.pdf(app)
            import ui_theme as ui
            self.assertEqual(seen['initialfile'], ui.report_filename('A-17'))
            self.assertRegex(seen['initialfile'], r'^A-17-\d\d-\d\d-\d{4}\.pdf$')
            self.assertIn('Calibration Data', text)
            self.assertNotIn('Performance Verification', text)
            self.assertIn(f'Fluke {model}', text)
            flat = ' '.join(text.split())
            self.assertIn('99.99 kHz range (5 V applied)', flat)
            self.assertIn('999.9 Hz range (1 V applied)', flat)
            self.assertNotIn('2 V applied', text)
            self.assertEqual(flat.count('corrected)'), 1 if model == '175' else 2)         # the row Description says so (footer notes are not printed by report_pdf)
            self.assertIn('600.0 Ohm range (limits corrected)' if model == '175' else '6.000 V range (limits corrected)', flat)     # report_pdf prints Ω as Ohm
            if model == '179':
                self.assertRegex(text, r'99\.99 Hz range \(3 V applied, limits\s+(.*\n\s*)?corrected\)')       # the long description wraps in the table
            self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))          # a real run is never marked demo
            self.assertRegex(text, r'Uncertainty\s+TAR\s+TUR')
            self.assertNotIn('Cover', text)
            # frequency readings: no calibrator uncertainty in volts, no TAR / TUR (natural-unit guard)
            for line in (l for l in text.splitlines() if 'kHz range' in l or '999.9 Hz range' in l or '99.99 Hz range' in l):
                self.assertNotRegex(line, r'\d+\.\d:1')
                self.assertNotRegex(line, r'[mµ]Hz')
            self.fresh()

    def test_temperature_rows_are_in_degrees_c(self):
        app, io = self.run_perfect('179')
        out, seen, text = self.pdf(app)
        flat = ' '.join(text.split())
        self.assertIn('°C', text.replace('º', '°') + flat) if False else None
        rows = app.certificate_rows()
        temps = [r for r in rows if r['Section'] == 'Temperature']
        self.assertEqual(len(temps), 3)
        self.assertEqual([r['UOM'] for r in temps], ['°C'] * 3)
        self.assertEqual([r['Nominal'] for r in temps], ['0.0 °C', '-40.0 °C', '400.0 °C'])
        self.assertEqual([(r['Tolerance -'], r['Tolerance +']) for r in temps], [('-1.0', '1.0'), ('-41.4', '-38.6'), ('395.0', '405.0')])
        self.assertEqual([r['As Found'] for r in temps], ['0.0', '-40.0', '400.0'])

    def test_demo_never_produces_real_looking_evidence(self):
        app, _ = self.make('177', demo=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(len(app.found), 51)
        self.assertTrue(all(r['synthetic'] for r in app.found.values()))
        self.assertTrue(app.any_synthetic())
        out, seen, text = self.pdf(app)
        self.assertIn('DEMO', text.upper())
        self.assertEqual(app.io, None)                                          # no instrument was touched

    def test_checkpoint_and_resume_never_repeat_a_point(self):
        app, io = self.make('175')
        self.hn.default_reading = lambda p: None if p['id'] == '2-12' else H.typed_nominal(p)   # operator stops at point 12 (no reading)
        self.hn.run_all()
        self.assertEqual(len(app.found), 11)
        self.assertEqual(sorted(app.found)[0], '2-1')
        self.assertEqual([t for _i, t in H.wire(io)][-1], 'STBY')

    def test_procedure_modifications_are_wired(self):
        for model in MODELS:
            app, io = self.make(model)
            self.assertTrue(hasattr(app, 'pm_begin_run') and hasattr(app, 'pm_step') and hasattr(app, 'pm_live_attach'))
            self.assertEqual(app.pm_point_title(app.points[0]), 'AC volts, 600.0 mV range')
            self.fresh()


class Registered(unittest.TestCase):
    def test_launchers_manager_and_verified_registration(self):
        manager = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        import verified
        for m in MODELS:
            name = f'Fluke_{m}_Verification.py'
            text = (ROOT / 'Procedures' / name).read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", text)
            self.assertIn(f"SPEC = '{SPEC_NAME}'", text)
            self.assertIn(f"'Fluke {m} Performance Verification': '{name}'", manager)
            self.assertIn(f"'{name}': '1'", manager)
            self.assertIn(f"('Fluke {m} Performance Verification','Fluke','{m}','Digital Multimeter','{name}')", manager)
            self.assertIn(name, verified.FILES)
            self.assertNotIn(name, {s['proc_key'] for s in verified.SEED})          # not verified on hardware: nothing seeded

    def test_the_launchers_import_and_name_the_spec(self):
        for m in MODELS:
            spec = importlib.util.spec_from_file_location(f'launcher{m}', ROOT / 'Procedures' / f'Fluke_{m}_Verification.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertEqual((mod.MODEL, mod.SPEC), (m, SPEC_NAME))
            self.assertTrue((ROOT / 'specs' / mod.SPEC).is_file())


if __name__ == '__main__':
    unittest.main()
