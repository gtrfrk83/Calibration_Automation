"""Fluke 753 / 754 Documenting Process Calibrator performance verification (Procedures/Fluke_753_Verification.py, Fluke_754_Verification.py -> fluke_753_754.main(MODEL, spec='fluke_753_754_pv.json');
specs/fluke_753_754_pv.json built by specs/build_fluke_753_754_spec.py from the Calibration Manual, Performance Verification Tests, printed pp. 9-32).

Part 1: the spec against an INDEPENDENT second transcription of every table (read from the rendered page images, twice), the printed misprint of the 30 V row, the two directions
(UUT input = measured, UUT output = sourced) and their labels, the thermocouple type of every temperature point, the hook-up groups and diagrams, sidecars, launchers.
Part 2: the uncertainty rule by DIRECTION: every UUT output point resolves to the measuring standard's INPUT-direction sheet row, every UUT input point to the calibrator's OUTPUT-direction row;
the per-point measuring-standard choice (default 3458A; 34461A / 34465A only when their sheet is installed).
Part 3: the real engine (fluke_753_754.App on handheld_dmm.App) on the simulated bench with the 5522A and 5560A: wire commands, no calibrator output at a UUT output point, standby after every
point, a typed reading judged exactly, the PDF report, demo.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_fluke_753_754_points"""
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
h = H = F = SPECS = Spy = SPEC = BUILDER = None
SPEC_NAME = 'fluke_753_754_pv.json'
MODELS = ('753', '754')
COUNTS = {'753': 90, '754': 91}

# The printed tables, as read a second time from the page images: table -> [(input / output as printed, min 1-year, max 1-year, min 2-year, max 2-year)] in table order.
PRINTED = {
    '3': [('0 mV', '-0.005', '0.005', '-0.005', '0.005'), ('0.1 V', '99.975', '100.025', '99.965', '100.035'), ('-0.1 V', '-100.025', '-99.975', '-100.035', '-99.965'),
          ('0 (3 V)', '-0.00005', '0.00005', '-0.00005', '0.00005'), ('1.0', '0.99975', '1.00025', '0.99965', '1.00035'), ('2.0', '1.99955', '2.00045', '1.99935', '2.00065'),
          ('3', '2.99935', '3.00065', '2.99905', '3.00095'), ('-3', '-3.00065', '-2.99935', '-3.00095', '-2.99905'),
          ('0 (30 V)', '-0.0005', '0.0005', '-0.0005', '0.0005'), ('30', '29.9935', '29.9870', '29.9905', '30.0095'), ('-30', '-30.0065', '-29.9935', '-30.0095', '-29.9905'),
          ('0 (300 V)', '-0.05', '0.05', '-0.05', '0.05'), ('295', '294.80', '295.20', '294.74', '295.26'), ('-295', '-295.20', '-294.80', '-295.26', '-294.74')],
    '4': [('0.26 500', '0.257', '0.263', '0.253', '0.267'), ('3 500', '2.983', '3.017', '2.966', '3.034'), ('0.26 40', '0.257', '0.263', '0.253', '0.267'), ('3 40', '2.983', '3.017', '2.966', '3.034'),
          ('2.6 500', '2.567', '2.633', '2.53', '2.67'), ('30 500', '29.830', '30.170', '29.66', '30.34'), ('2.6 40', '2.567', '2.633', '2.53', '2.67'), ('30 40', '29.830', '30.170', '29.66', '30.34'),
          ('27 500', '26.665', '27.335', '26.5', '27.5'), ('295 500', '293.325', '296.675', '291.9', '298.2'), ('27 40', '26.665', '27.335', '26.5', '27.5'), ('295 50', '293.325', '296.675', '291.9', '298.2')],
    '5': [('4 mA', '3.995', '4.005', '3.992', '4.008'), ('20 mA', '19.993', '20.007', '19.990', '20.010'), ('30 mA', '29.992', '30.008', '29.989', '30.012'), ('-30 mA', '-30.008', '-29.992', '-30.012', '-29.989'),
          ('0 mA', '-0.02', '0.02', '-0.03', '0.03'), ('100 mA', '99.97', '100.03', '99.96', '100.04'), ('-100 mA', '-100.03', '-99.97', '-100.04', '-99.96')],
    '6': [('0 (10 ohm)', '-0.050', '0.050', '-0.070', '0.070'), ('10 ohm', '9.945', '10.055', '9.923', '10.077'), ('0 (100 ohm)', '-0.05', '0.05', '-0.07', '0.07'), ('100 ohm', '99.90', '100.10', '99.86', '100.14'),
          ('0 (1000 ohm)', '-0.5', '0.5', '-0.7', '0.7'), ('1 kohm', '999.0', '1001.0', '998.6', '1001.4'), ('0 (10 kohm)', '-0.010', '0.010', '-0.015', '0.015'), ('10 kohm', '9.980', '10.020', '9.970', '10.030')],
    '7': [('10 Hz 300 mV', '9.95', '10.05', '9.95', '10.05'), ('150 Hz 300 mV', '149.5', '150.5', '149.5', '150.5'), ('1.2 kHz 1.0 V', '1.195', '1.205', '1.195', '1.205'),
          ('12 kHz 1.0 V', '11.95', '12.05', '11.95', '12.05'), ('49 kHz 2.0 V', '48.95', '49.05', '48.95', '49.05')],
    '8': [('10 mV', '9.9940', '10.0060', '9.9935', '10.0065'), ('0.1 V', '99.9850', '100.0150', '99.9800', '100.0200'), ('0.15 V', '0.14994', '0.15007', '0.14993', '0.15007'),
          ('1 V', '0.99985', '1.00015', '0.99980', '1.00020'), ('1.5 V', '1.49935', '1.50065', '1.49928', '1.50073'), ('10 V', '9.99850', '10.00150', '9.99800', '10.00200')],
    '9': [('2 mA', '1.99680', '2.00320', '1.99660', '2.00340'), ('4 mA', '3.99660', '4.00340', '3.99620', '4.00380'), ('12 mA', '11.99580', '12.00420', '11.99460', '12.00540'),
          ('21 mA', '20.99490', '21.00510', '20.99280', '21.00720')],
    '10': [('4', '3.99220', '4.00780', '3.99140', '4.00860'), ('21', '20.98880', '21.01120', '20.98460', '21.01540')],
    '11': [('0.1 ohm', '0.0900', '0.1100', '0.0850', '0.1150'), ('1 ohm', '0.9899', '1.0101', '0.9849', '1.0152'), ('10 ohm', '9.9890', '10.0110', '9.9835', '10.0165'),
           ('20 ohm', '19.978', '20.022', '19.967', '20.033'), ('100 ohm', '99.970', '100.030', '99.955', '100.045'), ('200 ohm', '199.76', '200.24', '199.64', '200.36'),
           ('1000 ohm', '999.60', '1000.40', '999.40', '1000.60'), ('2 kohm', '1.9966', '2.0034', '1.9944', '2.0056'), ('10 kohm', '9.9950', '10.0050', '9.9920', '10.0080')],
    '12': [('5 Hz Sine', '4.99', '5.01', '4.99', '5.01'), ('1 kHz Sine', '999.9', '1000.1', '999.9', '1000.1'), ('10 kHz Sine', '9.998', '10.002', '9.998', '10.002'),
           ('49 kHz Sine', '48.995', '49.005', '48.995', '49.005'), ('5 Hz Square', '4.99', '5.01', '4.99', '5.01'), ('1 kHz Square', '999.9', '1000.1', '999.9', '1000.1'),
           ('50 Hz Square (7.5 Vpp)', '49.9', '50.1', '49.9', '50.1')],
    '13': [('-5.550 mV (-180 C)', '-180.9', '-179.1', '-181.2', '-178.8'), ('0.000 mV (0 C)', '-0.5', '0.5', '-0.6', '0.6'), ('52.410 mV (1300 C)', '1299.1', '1300.9', '1298.8', '1301.2')],
    '14': [('-180 C', '-5.5616', '-5.539', '-5.5653', '-5.5353'), ('0 C', '-0.0197', '0.0197', '-0.0237', '0.0237'), ('1300 C', '52.3928', '52.4277', '52.3893', '52.4312')],
    '15': [('-180 (27.096)', '-180.07', '-179.93', '-180.14', '-179.86'), ('100 (138.505)', '99.93', '100.07', '99.86', '100.14'), ('780 (369.712)', '779.79', '780.21', '779.59', '780.41')],
    '16': [('-180 (27.096)', '-180.47', '-179.53', '-180.54', '-179.46'), ('100 (138.505)', '99.53', '100.47', '99.46', '100.54'), ('780 (369.712)', '779.39', '780.61', '779.19', '780.81')],
    '17': [('-180 C 27.096', '27.075', '27.118', '27.054', '27.139'), ('100 C 138.505', '138.487', '138.524', '138.468', '138.543'), ('780 C 369.712', '369.6707', '369.7532', '369.630', '369.795')],
    'LP': [('23.4 V to 28.6 V', '23.4', '28.6', '23.4', '28.6')],
}
SECTION_OF = {'3': 'DC Volts Measure', '4': 'AC Volts Measure', '5': 'DC Current Measure', '6': 'Resistance Measure', '7': 'Frequency Measure', '8': 'DC Volts Source', '9': 'DC Current Source',
              '10': 'Simulate Transmitter', '11': 'Resistance Source', '12': 'Frequency Source', '13': 'Thermocouple Measure Type K', '14': 'Thermocouple Source Type K',
              '15': 'RTD Measure Pt100 four-wire', '16': 'RTD Measure Pt100 three-wire', '17': 'RTD Source Pt100', 'LP': 'Loop Power'}
MEASURE_TABLES = {'3', '4', '5', '6', '7', '13', '15', '16'}


def setUpModule():
    global h, H, F, SPECS, Spy, SPEC, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import fluke_753_754 as _f
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, F, SPECS, Spy = _h, _H, _f, _o.SPECS, _o.Spy
    for m in MODELS:
        SPECS[m] = SPEC_NAME
    SPEC = h.load_spec(SPEC_NAME)
    s = importlib.util.spec_from_file_location('build_fluke_753_754_spec', ROOT / 'specs' / 'build_fluke_753_754_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    for m in MODELS:
        SPECS.pop(m, None)


def pts(model):
    return h.points_for(SPEC, model)


def by_table(t):
    return [s for s in SPEC['steps'] if s['table'] == t]


class Spec(unittest.TestCase):
    def test_counts_per_model_and_hart_is_754_only(self):
        self.assertEqual({m: len(pts(m)) for m in MODELS}, COUNTS)
        hart = [s for s in SPEC['steps'] if s['table'] == 'H']
        self.assertEqual([s['models'] for s in hart], [['754']])
        self.assertEqual(hart[0]['test'], 'visual')
        self.assertEqual(sum(len(v) for v in PRINTED.values()) + 1, 91)

    def test_every_row_matches_the_second_reading_of_the_tables(self):
        for table, rows in PRINTED.items():
            steps = by_table(table)
            self.assertEqual(len(steps), len(rows), table)
            for s, (label, lo1, hi1, lo2, hi2) in zip(steps, rows):
                if (table, label) == ('3', '30'):
                    self.assertEqual((D(s['low']), D(s['high'])), (D('29.9935'), D('30.0065')), 'misprint corrected')
                else:
                    self.assertEqual((D(s['low']), D(s['high'])), (D(lo1), D(hi1)), (table, label))
                self.assertEqual((D(s['limits_2y']['low']), D(s['limits_2y']['high'])), (D(lo2), D(hi2)), (table, label, '2-year'))

    def test_the_30_v_misprint_is_corrected_visibly(self):
        s = [x for x in by_table('3') if x['range'] == '30.0000 V' and x['nominal'] == 30][0]
        self.assertEqual((s['low'], s['high']), ('29.9935', '30.0065'))
        self.assertEqual(s['printed_text']['high'], '29.9870')
        self.assertIn('PRINTED MISPRINT', s['note'])
        self.assertEqual(s['check']['verdict'], 'misprint')
        self.assertIn('29.9870', SPEC['source']['report_note'])

    def test_every_limit_agrees_with_the_published_accuracy_statement(self):
        """The builder recomputes each limit from the accuracy statement (printed pp. 5-8): no row but the misprint disagrees."""
        bad = [(s['id'], s['check']['arithmetic']) for s in SPEC['steps'] if (s.get('check') or {}).get('arithmetic')]
        self.assertEqual(bad, [])

    def test_nominal_is_inside_the_limits(self):
        for s in SPEC['steps']:
            if s['test'] == 'numeric':
                self.assertLessEqual(D(s['low']) * D(str(s['factor'])), D(str(s['nominal'])) + D('1e-12'), s['id'])
                self.assertGreaterEqual(D(s['high']) * D(str(s['factor'])), D(str(s['nominal'])) - D('1e-12'), s['id'])

    # ---- the two directions, and their labels ----------------------------------------------------------------------------------------------
    def test_direction_and_labels(self):
        for s in SPEC['steps']:
            if s['table'] == 'H':
                self.assertEqual(s['direction'], 'none')
                continue
            source = s['table'] not in MEASURE_TABLES
            self.assertEqual(s['direction'], 'source' if source else 'measure', s['id'])
            self.assertTrue(s['section'].startswith(SECTION_OF[s['table']]), s['id'])
            self.assertIn('(UUT output)' if source else '(UUT input)', s['section'], s['id'])
            if source:
                self.assertTrue(s['report_desc'].startswith('Output: '), s['id'])
                self.assertIn('UUT sources', s['dsb_out'])
                self.assertIn('MANUAL ENTRY', s['note'].upper())
            else:
                self.assertNotIn('Output', s['section'])

    def test_source_points_have_no_calibrator_output_and_the_measure_points_do(self):
        for s in SPEC['steps']:
            if s['table'] == 'H':
                continue
            if s['direction'] == 'source':
                if s['table'] == '10':
                    self.assertEqual(s['applied'], {'value': 8.0, 'frequency': None})         # the 5522A loop supply: not a measured value
                    self.assertTrue(s['loop_supply'])
                else:
                    self.assertIsNone(s['applied'], s['id'])
                self.assertEqual(s['unc_direction'], 'input')
                self.assertEqual(s['uut']['sheet_direction'], 'input')
                self.assertIn(s['uut']['kind'], ('DCV', 'DCI', 'OHM', 'FREQ'))
            else:
                self.assertIsNotNone(s['applied'], s['id'])
                self.assertEqual(s['unc_direction'], 'output')

    def test_simulate_transmitter_loop_supply_is_not_a_calibrator_output_for_the_run(self):
        """Table 10's 8 V supply: the step is a UUT output point (manual entry); the engine must not set the calibrator from it."""
        for s in by_table('10'):
            self.assertEqual(s['direction'], 'source')
        # handled in the engine test below (no OUT 0.008A / OUT 8V in the wire log for these points)

    # ---- thermocouple / RTD types ----------------------------------------------------------------------------------------------------------
    def test_every_temperature_point_is_type_k_and_every_rtd_is_pt100_385(self):
        temps = [s for s in SPEC['steps'] if s['table'] in ('13', '14')]
        self.assertEqual(len(temps), 6)
        for s in temps:
            self.assertEqual(s['tc'], 'K', s['id'])
            self.assertIn('Type K', s['section'])
            self.assertIn('Type K', s['note'])
        self.assertEqual([s['nominal'] for s in by_table('13')], [-180.0, 0.0, 1300.0])
        for s in SPEC['steps']:
            if s['table'] in ('15', '16', '17'):
                self.assertEqual(s['rtd'], 'Pt385-100')
                self.assertIn('Pt100', s['section'])
        other = {'E', 'N', 'J', 'T', 'B', 'R', 'S', 'C', 'L', 'U'}
        for s in SPEC['steps']:
            if s.get('tc'):
                self.assertNotIn(s['tc'], other)
        self.assertEqual([s['rtd_celsius'] for s in by_table('15')], [-180.0, 100.0, 780.0])
        self.assertEqual([s['applied']['value'] for s in by_table('15')], [27.096, 138.505, 369.712])

    def test_tc_measure_deviation_from_the_manual_method_is_stated(self):
        for s in by_table('13'):
            self.assertIn('DEVIATION', s['note'])
            self.assertIn('mv_equivalent', s)
        self.assertEqual([s['mv_equivalent'] for s in by_table('13')], ['-5.550', '0.000', '52.410'])

    # ---- groups, diagrams, sidecars --------------------------------------------------------------------------------------------------------
    def test_groups_and_diagrams(self):
        used = {s['group'] for s in SPEC['steps']}
        self.assertEqual(used, set(SPEC['groups']))
        for name, g in SPEC['groups'].items():
            self.assertEqual(g['diagram'], f'diagrams/hook_fluke753_{name}.png')
            self.assertTrue((ROOT / g['diagram']).is_file(), g['diagram'])
        for name in ('fluke_753_754_front.png', 'fluke_753_754_terminals.png'):
            self.assertTrue((ROOT / 'diagrams' / name).is_file(), name)
        text = (ROOT / 'diagrams' / 'README_fluke753.txt').read_text(encoding='utf-8')
        for g in SPEC['groups']:
            self.assertIn(g, text)
        import hookups
        self.assertEqual(hookups.METERS['fluke753']['panels'], ('fluke_753_754_terminals.png', 'fluke_753_754_front.png'))

    def test_group_of_each_table(self):
        want = {'3': 'MEAS_V', '4': 'MEAS_V', '5': 'MEAS_MA', '6': 'MEAS_OHM', '7': 'MEAS_V', '8': 'SRC_V', '9': 'SRC_MA', '10': 'SRC_SIM', '11': 'SRC_OHM', '12': 'SRC_FREQ',
                '13': 'MEAS_TC', '14': 'SRC_TC', '15': 'MEAS_RTD4', '16': 'MEAS_RTD3', '17': 'SRC_OHM', 'LP': 'LOOP', 'H': 'HART'}
        for s in SPEC['steps']:
            self.assertEqual(s['group'], want[s['table']], s['id'])

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec())))

    def test_builder_aborts_on_a_wrong_point_count(self):
        rows = list(BUILDER.T9)
        try:
            BUILDER.T9[:] = rows[:3]
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
        finally:
            BUILDER.T9[:] = rows

    def test_sidecars_launchers(self):
        for m in MODELS:
            d = json.loads((ROOT / 'Procedures' / f'Fluke_{m}_Verification.procedure.json').read_text(encoding='utf-8'))
            self.assertEqual((d['id'], d['model'], d['engine'], d['specs']), (f'Fluke_{m}_Verification', m, ['handheld_dmm.py', 'fluke_753_754.py'], ['specs/fluke_753_754_pv.json']))
            self.assertIn(f'{COUNTS[m]} points', d['description'])
            self.assertIn('specs/fluke_753_754_pv.json#' + m, d['fingerprint']['spec'])
            src = (ROOT / 'Procedures' / f'Fluke_{m}_Verification.py').read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", src)
            self.assertIn("SPEC = 'fluke_753_754_pv.json'", src)
            self.assertIn('fluke_753_754.main(MODEL, spec=SPEC)', src)


class UncertaintyByDirection(unittest.TestCase):
    """Owner rule 2026-10-26: the lookup keys off the direction.  A UUT OUTPUT point is measured by the multimeter standard (its INPUT-direction sheet);
    a UUT INPUT point is sourced by the calibrator (its OUTPUT-direction sheet)."""

    def setUp(self):
        self.hn = H.Harness().start()
        self.app = F.App(self.hn.root, '754', demo=False, spec=h.load_spec(SPEC_NAME), io_factory=None)
        self.app.asset.set('A-1')
        self.app.cal_mode.set(h.CAL_CHOICES[1])           # the 5522A, the manual's calibrator

    def tearDown(self):
        self.hn.stop()

    def test_every_sourced_point_resolves_to_an_input_direction_sheet(self):
        n = 0
        for p in self.app.points:
            if p.get('direction') != 'source':
                continue
            self.assertEqual(F.unc_direction(p), 'input')
            b, model, direction = self.app._budget(p)
            self.assertEqual((model, direction), ('3458A', 'input'), p['id'])
            self.assertIsNotNone(b, p['id'])
            self.assertIsNotNone(b.hit, f'{p["id"]}: no sheet row')
            self.assertEqual(b.hit.row['direction'], 'input', p['id'])
            self.assertIsNotNone(b.reported, p['id'])
            n += 1
        self.assertEqual(n, 35)                           # 6 + 4 + 2 + 9 + 7 + 3 + 3 + 1

    def test_every_measured_point_resolves_to_an_output_direction_sheet(self):
        import uncertainty_budget as ub
        n = 0
        for p in self.app.points:
            if p.get('direction') != 'measure':
                continue
            self.assertEqual(F.unc_direction(p), 'output')
            a = p['applied']
            if F.is_rtd(p):
                b = F.rtd_budget(p, '5522A')
            elif p['kind'] == 'TEMP':
                b = ub.build('TEMP', a['value'], 'degC', standard='5522A')
            else:
                kind = 'OHM2' if p['kind'] == 'OHM' else p['kind']
                unit = 'ohm' if p['kind'] == 'OHM' else ('V' if p['kind'] in ('DCV', 'ACV') else 'A')
                b = ub.build(kind, a['value'], unit, standard='5522A', frequency=a.get('frequency'))
            self.assertIsNotNone(b.hit, f'{p["id"]}: no sheet row')
            self.assertEqual(b.hit.row['direction'], 'output', p['id'])
            n += 1
        self.assertEqual(n, 55)                           # 14 + 12 + 7 + 8 + 5 + 3 + 3 + 3

    def test_the_two_directions_use_different_rows(self):
        """The same quantity read both ways must not give the same sheet row (DC volts: 3458A input row vs 5522A output row)."""
        import uncertainty_budget as ub
        meas = ub.build('DCV', 10.0, 'V', standard='5522A', direction='output', basis='generate')
        src = ub.build('DCV', 10.0, 'V', standard='3458A', direction='input', basis='measure')
        self.assertEqual((meas.hit.row['direction'], src.hit.row['direction']), ('output', 'input'))
        self.assertNotEqual(meas.hit.row['function'] + str(meas.hit.limit), src.hit.row['function'] + str(src.hit.limit))

    def test_has_uncertainty_covers_every_numeric_point(self):
        for p in self.app.points:
            self.assertEqual(self.app.has_uncertainty(p), p['test'] == 'numeric', p['id'])

    def test_no_point_that_should_carry_an_uncertainty_is_blank(self):
        for p in self.app.points:
            if self.app.has_uncertainty(p):
                self.assertTrue(self.app.uncertainty_text(p) or not (F.is_source(p) or F.is_rtd(p)), p['id'])

    def test_rtd_uncertainty_is_in_degc_from_the_calibrators_rtd_sheet(self):
        for p in by_table('15') + by_table('16'):
            q = self.app.points[[x['id'] for x in self.app.points].index(p['id'])]
            text = self.app.uncertainty_text(q)
            self.assertTrue(text.endswith('°C'), (p['id'], text))
            b = F.rtd_budget(q, '5522A')
            self.assertEqual(b.hit.row['unit'], 'degC')
            self.assertIn('Pt 385', b.hit.row['variant'] + b.hit.row['function'])

    def test_the_choice_list_tolerates_a_missing_sheet(self):
        p = [x for x in self.app.points if x['id'] == '8-1'][0]
        installed = self.app.unc_models()
        self.assertEqual(installed[0], '3458A')
        self.assertTrue(set(installed) <= set(F.UNC_STANDARDS))
        self.assertEqual(self.app.unc_options(p)[0], '3458A')
        with mock.patch.object(F, 'have_standard', lambda m: m == '3458A'):
            self.assertEqual(self.app.unc_models(), ['3458A'])
            self.app.unc_choice['8-1'] = '34465A'                    # a saved pick whose sheet is not installed: the default is used
            self.assertEqual(self.app.unc_standard_of(p), '3458A')
            self.assertTrue(self.app.uncertainty_text(p))

    def test_per_point_choice_menu_choice_saved_and_named_in_the_report(self):
        p = [x for x in self.app.points if x['id'] == '8-3'][0]
        self.assertEqual(self.app.unc_standard_of(p), F.DEFAULT_UNC_STANDARD)
        orig = F.source_budget
        with mock.patch.object(F, 'have_standard', lambda m: True), mock.patch.object(F, 'source_budget', lambda q, m: orig(q, '3458A')):       # the 34461A / 34465A sheets stand in as the 3458A's
            self.app._unc_cache.clear()
            menu = self.app.tree_menu_extras('8-3')
            labels = [m[0] for m in menu]
            self.assertEqual(labels[0], 'Uncertainty standard: 3458A (default)  (selected)')
            self.assertEqual(len(labels), 3)
            self.assertIn('Uncertainty standard: 34461A', labels)
            [m for m in menu if '34465A' in m[0]][0][1]()             # the owner picks the 34465A for this point
            self.assertEqual(self.app.unc_standard_of(p), '34465A')
            self.assertEqual(self.app.save_fields()['unc_choice'], {'8-3': '34465A'})
            self.app.found['8-3'] = dict(result='PASS', reading=0.15, entered='0.15000', source='typed', synthetic=False)
            self.assertIn('34465A (1 point(s))', self.app.source_note())
            data = dict(self.app.save_fields())
            self.app.unc_choice = {}
            self.app.load_results(data)
            self.assertEqual(self.app.unc_choice, {'8-3': '34465A'})
            [m for m in self.app.tree_menu_extras('8-3') if m[0].startswith('Uncertainty standard: 3458A')][0][1]()
            self.assertEqual(self.app.unc_choice, {})                 # picking the default clears the choice

    def test_measure_points_have_no_choice_menu(self):
        self.assertEqual(self.app.tree_menu_extras('3-1'), [])
        self.assertEqual(self.app.tree_menu_extras('H-1'), [])

    def test_tar_tur_fields_for_a_source_point_and_an_rtd_point(self):
        p = [x for x in self.app.points if x['id'] == '8-3'][0]
        f = self.app.certificate_fields(p)
        self.assertTrue(f['TUR'] and f['TAR'], f)
        r = [x for x in self.app.points if x['id'] == '15-1'][0]
        f = self.app.certificate_fields(r)
        self.assertTrue(f['TUR'], f)


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
        app = F.App(self.hn.root, meter, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
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

    def test_perfect_unit_passes_every_model_with_either_calibrator(self):
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                self.assertEqual(len(app.found), COUNTS[meter], (meter, cal))
                self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, (meter, cal))
                self.assertTrue(all(not r['synthetic'] for r in app.found.values()))
                self.hn.stop(); self.hn = H.Harness().start()

    def test_reading_windows_say_which_instrument_is_read(self):
        app, io = self.run_perfect('753')
        devs = {d[1]: d[3] for d in self.hn.dialogs if d[0] == 'reading'}
        for p in app.points:
            self.assertEqual(devs[p['id']], 'EXTERNAL MEASURING INSTRUMENT' if p['direction'] == 'source' else 'UUT DISPLAY', p['id'])

    def test_wire_log_no_calibrator_output_for_uut_output_points(self):
        app, io = self.run_perfect('754')
        texts = [t for _i, t in H.wire(io)]
        outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
        measure = [p for p in pts('754') if p['direction'] == 'measure']
        self.assertEqual(len(outs), len(measure) + 2)        # one OUT per calibrator-sourced point, the two 8 V loop supplies of Table 10, and none for the other 33 UUT output points
        self.assertEqual(outs.count('OUT 8V,0Hz'), 2)
        for want in ('OUT 0.1V,0Hz', 'OUT -295V,0Hz', 'OUT 295V,500Hz', 'OUT 0.004A,0Hz', 'OUT 10OHM', 'OUT 0.3V,10Hz', 'OUT 2V,49000Hz', 'OUT -180CEL', 'OUT 1300CEL', 'OUT 27.096OHM', 'OUT 369.712OHM'):
            self.assertTrue(any(o.startswith(want[:-3] if want.endswith('CEL') else want) for o in outs), want)
        self.assertEqual(sum(1 for o in outs if o.endswith('CEL')), 3)
        self.assertEqual(sum(1 for t in texts if t == 'TC_TYPE K'), 3)           # Type K, exactly
        self.assertFalse(any('TC_TYPE' in t and t != 'TC_TYPE K' and t != 'TC_TYPE?' for t in texts))
        self.assertLess(texts.index('*RST'), texts.index(outs[0]))
        self.assertEqual(texts[-1], 'STBY')
        idx = [i for i, t in enumerate(texts) if t in outs]
        for a, b in zip(idx, idx[1:]):
            self.assertIn('STBY', texts[a + 1:b])
        applied = [p for p in pts('754') if p['applied']]
        self.assertEqual(len(applied), len(outs))
        for o, p in zip(outs, applied):
            if p['kind'] in ('DCV', 'DCI'):
                self.assertTrue(o.endswith(',0Hz'), o)                       # DC outputs carry an explicit 0 Hz

    def test_the_5560a_tc_order_is_kept(self):
        app, io = self.run_perfect('753', '5560A')
        texts = [t for _i, t in H.wire(io)]
        i = texts.index('TSENS_TYPE TC')
        seq = [t for t in texts[i:i + 14] if not t.startswith('*OPC') and t != 'ERR?']
        self.assertEqual(seq[:5], ['TSENS_TYPE TC', 'OUT -180CEL', 'TC_TYPE K', 'TC_TYPE?', 'OUT -180CEL'])      # NOTES.md: TSENS, OUT, TC_TYPE, read-back, OUT

    def test_cable_change_prompts_follow_the_groups(self):
        app, io = self.run_perfect('754')
        cables = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
        order = []
        for p in pts('754'):
            if not order or order[-1] != p['group']:
                order.append(p['group'])
        self.assertEqual(len(cables), len(order))

    def test_uut_output_points_are_labelled_output_in_the_window_and_the_report(self):
        app, io = self.run_perfect('753')
        rows = dict(zip([p['id'] for p in app.certificate_rows_and_points()[1]], app.certificate_rows()))
        for p in app.points:
            row = rows[p['id']]
            if p['direction'] == 'source':
                self.assertIn('(UUT output)', row['Section'], p['id'])
                self.assertTrue(row['Description'].startswith('Output: '), (p['id'], row['Description']))
            else:
                self.assertIn('(UUT input)', row['Section'], p['id'])
            self.assertTrue(row['Uncertainty'], (p['id'], row))
        self.assertEqual(sum(1 for r in rows.values() if not r['Uncertainty']), 0)

    def test_out_of_tolerance_fails_and_exact_limit_passes(self):
        app, io = self.make('754')
        pt = [p for p in pts('754') if p['id'] == '11-5'][0]          # UUT output 100 ohm: 99.970 .. 100.030
        self.hn.default_reading = lambda p: ('100.030' if p['id'] != '11-5' and p['id'] == pt['id'] else (H.typed_nominal(p) if p['id'] != pt['id'] else '100.031'))
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['11-5']['result'], 'FAIL')
        self.hn.stop(); self.hn = H.Harness().start()
        app, io = self.make('754')
        self.hn.default_reading = lambda p: ('100.030' if p['id'] == '11-5' else H.typed_nominal(p))
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['11-5']['result'], 'PASS')

    def test_the_corrected_30_v_row_passes_at_30_0065_and_fails_above(self):
        app, io = self.make('753')
        self.hn.default_reading = lambda p: ('30.0065' if p['id'] == '3-10' else H.typed_nominal(p))
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['3-10']['result'], 'PASS')
        self.hn.stop(); self.hn = H.Harness().start()
        app, io = self.make('753')
        self.hn.default_reading = lambda p: ('30.0066' if p['id'] == '3-10' else H.typed_nominal(p))
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['3-10']['result'], 'FAIL')

    def test_hart_question_is_pass_fail_with_no_uncertainty(self):
        app, io = self.run_perfect('754')
        r = app.found['H-1']
        self.assertEqual(r['result'], 'PASS')
        row = [x for p, x in zip(app.certificate_rows_and_points()[1], app.certificate_rows()) if p['id'] == 'H-1'][0]
        self.assertEqual(row['Uncertainty'], '')
        self.assertNotIn('H-1', {p['id'] for p in pts('753')})

    def test_report_pdf_is_calibration_data_with_the_notes(self):
        app, io = self.run_perfect('754')
        out = tempfile.mkdtemp() + '/x.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        text = subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout
        self.assertIn('Calibration Data', text)
        self.assertIn('30.0065', text)
        self.assertIn('(UUT output)', text)
        note = app.source_note()
        self.assertIn('misprint', note.lower())
        self.assertIn('3458A (35 point(s))', note)

    def test_demo_is_marked_and_never_real(self):
        for meter in MODELS:
            app, _ = self.make(meter, demo=True)
            self.assertTrue(self.hn.run_all(), meter)
            self.assertTrue(app.any_synthetic())
            self.assertEqual(len(app.found), COUNTS[meter])
            self.hn.stop(); self.hn = H.Harness().start()


if __name__ == '__main__':
    unittest.main()
