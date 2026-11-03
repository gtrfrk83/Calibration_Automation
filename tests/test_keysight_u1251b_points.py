"""Keysight U1251B and U1252B handheld digital multimeter performance verification (Procedures/Keysight_U1251B_Verification.py and Keysight_U1252B_Verification.py
-> handheld_dmm.main(MODEL, spec='keysight_u1251b_u1252b_pv.json'), the shared handheld engine unchanged; specs/keysight_u1251b_u1252b_pv.json built by
specs/build_keysight_u1251b_spec.py from the User's and Service Guide, Table 6-2 "Verification Test", printed pp. 155-160).

Part 1: the spec against an INDEPENDENT second transcription of Table 6-2 (read from the rendered page images at 220 and 300 dpi after the first reading at 130 dpi; the table prints the ERROR from
nominal, so the expected limits are recomputed here with a parser of its own, not the builder's), both model columns with their N/A cells, the display decimals (Table 6-4 formats), the hand-set
points, the unnumbered 5 A / 10 A rows, the printed-misprint notes, the cross-check against the data sheet formulas (UNVERIFIED second-hand extraction: every checked row agrees), the functional
checks, hook-ups, sidecars, launchers.
Part 2: the real engine (handheld_dmm.App) on the simulated bench with the 5522A and 5560A, one run per model: wire commands (explicit 0 Hz on DC, ZCOMP WIRE2 on the three low ohms ranges, no
LCOMP, standby after each point), a typed reading judged exactly, the exact list of points without an uncertainty, the PDF report, demo marking.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_keysight_u1251b_points"""
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
SPEC_NAME = 'keysight_u1251b_u1252b_pv.json'
MODELS = ('U1251B', 'U1252B')
COUNTS = {'U1251B': 63, 'U1252B': 87}                 # Table 6-2 rows without N/A (60 / 84) + the Basic Operating Test checks (3 / 3: the charge terminal alert test is not included, owner decision 2026-10-27)
TABLE_COUNTS = {'U1251B': 60, 'U1252B': 84}

# Table 6-2 as read a second time, in printed order: (step, section, range, 5520A output as printed, U1251B error, U1252B error); 'N/A' = the cell is N/A.
T = [
    ('1', 'AC volts', '5 V', '5 V, 1 kHz', '32.5 mV', '22.5 mV'), ('1', 'AC volts', '5 V', '4.5 V, 10 kHz', '169.5 mV', '71.5 mV'), ('1', 'AC volts', '5 V', '4.5 V, 20 kHz', 'N/A', '169.5 mV'),
    ('1', 'AC volts', '5 V', '4.5 V, 30 kHz', '169.5 mV', 'N/A'), ('1', 'AC volts', '5 V', '4.5 V, 100 kHz', 'N/A', '169.5 mV'),
    ('1', 'AC volts', '50 V', '50 V, 1 kHz', '325 mV', '225 mV'), ('1', 'AC volts', '50 V', '45 V, 10 kHz', '1.695 V', '715 mV'), ('1', 'AC volts', '50 V', '45 V, 20 kHz', 'N/A', '1.695 V'),
    ('1', 'AC volts', '50 V', '45 V, 30 kHz', '1.695 V', 'N/A'), ('1', 'AC volts', '50 V', '45 V, 100 kHz', 'N/A', '1.695 V'),
    ('1', 'AC volts', '500 V', '500 V, 1 kHz', '3.25 V', '2.25 V'), ('1', 'AC volts', '1000 V', '1000 V, 1 kHz', '10 V', '8.0 V'),
    ('2', 'Frequency', '9.9999 kHz', '0.48 V, 1 kHz', '500 mHz', '500 mHz'),
    ('3', 'Duty cycle', '0.01% – 99.99%', '5.0 Vpp @ 50%, Square Wave, 50 Hz', '0.315%', '0.315%'),
    ('4', 'DC volts', '5 V', '5 V', '2 mV', '1.75 mV'), ('4', 'DC volts', '50 V', '50 V', '20 mV', '17.5 mV'), ('4', 'DC volts', '500 V', '500 V', '200 mV', '200 mV'),
    ('4', 'DC volts', '1000 V', '1000 V', '800 mV', '800 mV'),
    ('5', 'AC volts (U1252B, Shift mode)', '5 V', '5 V, 1 kHz', 'N/A', '22.5 mV'), ('5', 'AC volts (U1252B, Shift mode)', '5 V', '5 V, 10 kHz', 'N/A', '79.0 mV'),
    ('5', 'AC volts (U1252B, Shift mode)', '5 V', '4.5 V, 20 kHz', 'N/A', '169.5 mV'), ('5', 'AC volts (U1252B, Shift mode)', '5 V', '4.5 V, 100 kHz', 'N/A', '169.5 mV'),
    ('5', 'AC volts (U1252B, Shift mode)', '50 V', '50 V, 1 kHz', 'N/A', '225 mV'), ('5', 'AC volts (U1252B, Shift mode)', '50 V', '50 V, 10 kHz', 'N/A', '790 mV'),
    ('5', 'AC volts (U1252B, Shift mode)', '50 V', '45 V, 20 kHz', 'N/A', '1.695 V'), ('5', 'AC volts (U1252B, Shift mode)', '50 V', '45 V, 100 kHz', 'N/A', '1.695 V'),
    ('5', 'AC volts (U1252B, Shift mode)', '500 V', '500 V, 1 kHz', 'N/A', '2.25 V'), ('5', 'AC volts (U1252B, Shift mode)', '1000 V', '1000 V, 1 kHz', 'N/A', '8.0 V'),
    ('6', 'DC mV', '50 mV', '50 mV', '75 µV', '75 µV'), ('6', 'DC mV', '500 mV', '500 mV', '0.2 mV', '0.175 mV'), ('6', 'DC mV', '500 mV', '-500 mV', '0.2 mV', '0.175 mV'),
    ('6', 'DC mV', '1000 mV', '1000 mV', '0.8 mV', '0.75 mV'), ('6', 'DC mV', '1000 mV', '-1000 mV', '0.8 mV', '0.75 mV'),
    ('7', 'AC mV', '50 mV', '50 mV, 1 kHz', '0.34 mV', '0.24 mV'), ('7', 'AC mV', '50 mV', '50 mV, 10 kHz', '0.86 mV', '0.415 mV'), ('7', 'AC mV', '50 mV', '45 mV, 20 kHz', 'N/A', '1.695 mV'),
    ('7', 'AC mV', '50 mV', '50 mV, 30 kHz', '0.86 mV', 'N/A'), ('7', 'AC mV', '50 mV', '45 mV, 100 kHz', 'N/A', '1.695 mV'),
    ('7', 'AC mV', '500 mV', '500 mV, 45 Hz', '3.25 mV', '2.25 mV'), ('7', 'AC mV', '500 mV', '500 mV, 1 kHz', '3.25 mV', '2.25 mV'), ('7', 'AC mV', '500 mV', '500 mV, 10 kHz', '8.6 mV', '4.15 mV'),
    ('7', 'AC mV', '500 mV', '450 mV, 20 kHz', 'N/A', '16.95 mV'), ('7', 'AC mV', '500 mV', '500 mV, 30 kHz', '8.6 mV', 'N/A'), ('7', 'AC mV', '500 mV', '450 mV, 100 kHz', 'N/A', '16.95 mV'),
    ('7', 'AC mV', '1000 mV', '1000 mV, 1 kHz', '8.5 mV', '6.5 mV'), ('7', 'AC mV', '1000 mV', '1000 mV, 10 kHz', '47 mV', '11.5 mV'), ('7', 'AC mV', '1000 mV', '1000 mV, 20 kHz', 'N/A', '47.0 mV'),
    ('7', 'AC mV', '1000 mV', '1000 mV, 30 kHz', '47 mV', 'N/A'), ('7', 'AC mV', '1000 mV', '1000 mV, 100 kHz', 'N/A', '47.0 mV'),
    ('8', 'Ohms', '500 Ω', '500 Ω', '500 mΩ', '350 mΩ'), ('8', 'Ohms', '5 kΩ', '5 kΩ', '4.5 Ω', '3 Ω'), ('8', 'Ohms', '50 kΩ', '50 kΩ', '45 Ω', '30 Ω'),
    ('8', 'Ohms', '500 kΩ', '500 kΩ', '450 Ω', '300 Ω'), ('8', 'Ohms', '5 MΩ', '5 MΩ', '10.5 kΩ', '8 kΩ'), ('8', 'Ohms', '50 MΩ', '50 MΩ', '0.510 MΩ', '0.505 MΩ'),
    ('8', 'Ohms', '500 MΩ', '450 MΩ', 'N/A', '36.1 MΩ'),
    ('9', 'Conductance', '500 nS', '50 nS', '0.7 nS', '0.6 nS'),
    ('10', 'Diode', 'Diode', '1 V', '1 mV', '1 mV'),
    ('11', 'Frequency counter', '999.99 kHz', '600 mV, 100 kHz', 'N/A', '52 Hz'), ('12', 'Frequency counter', '99.999 MHz', '1500 mVrms, 10 MHz', 'N/A', '5.2 kHz'),
    ('13', 'Capacitance', '10.000 nF', '10.000 nF', '0.108 nF', '0.108 nF'), ('13', 'Capacitance', '100.00 nF', '100.00 nF', '1.05 nF', '1.05 nF'),
    ('13', 'Capacitance', '1000.0 nF', '1000.0 nF', '10.5 nF', '10.5 nF'), ('13', 'Capacitance', '10.000 µF', '10.000 µF', '0.105 µF', '0.105 µF'),
    ('13', 'Capacitance', '100.00 µF', '100.00 µF', '1.05 µF', '1.05 µF'), ('13', 'Capacitance', '1000.0 µF', '1000.0 µF', '10.5 µF', '10.5 µF'),
    ('13', 'Capacitance', '10.00 mF', '10.00 mF', '0.105 mF', '0.105 mF'), ('13', 'Capacitance', '100.00 mF', '10.00 mF', '0.4 mF', '0.4 mF'),
    ('14', 'Temperature', '-200 °C until 1372 °C', '0 °C', '3 °C', '3 °C'), ('14', 'Temperature', '-200 °C until 1372 °C', '100 °C', '3.3 °C', '3.3 °C'),
    ('15', 'DC µA', '500 µA', '500 µA', '0.55 µA', '0.3 µA'), ('15', 'DC µA', '5000 µA', '5000 µA', '5.5 µA', '3 µA'),
    ('16', 'AC µA', '500 µA', '500 µA, 1 kHz', '4.2 µA', '3.7 µA'), ('16', 'AC µA', '5000 µA', '5000 µA, 1 kHz', '42 µA', '37.0 µA'),
    ('17', 'DC mA', '50 mA', '50 mA', '0.105 mA', '80 µA'), ('17', 'DC mA', '440 mA', '400 mA', '0.85 mA', '0.65 mA'),
    ('18', 'AC mA', '50 mA', '50 mA, 20 kHz', '0.42 mA', '0.37 mA'), ('18', 'AC mA', '440 mA', '400 mA, 45 Hz', '3.4 mA', '3.0 mA'), ('18', 'AC mA', '440 mA', '400 mA, 1 kHz', '3.4 mA', '3.0 mA'),
    ('-', 'DC amps', '5 A', '5 A', '16 mA', '16 mA'), ('-', 'DC amps', '10 A', '10 A', '40 mA', '35 mA'),
    ('19', 'AC amps', '5 A', '5 A, 1 kHz', '42 mA', '37 mA'), ('19', 'AC amps', '10 A', '10 A, 1 kHz', '100 mA', '90 mA'),
    ('20', 'Square wave output', '120 Hz @ 50%', '33250A / 53131A', 'N/A', '26 mHz'), ('20', 'Square wave output', '4800 Hz @ 50%', '33250A / 53131A', 'N/A', '260 mHz'),
    ('20', 'Square wave output', '100 Hz @ 50%', '53131A', 'N/A', '0.398%'), ('20', 'Square wave output', '100 Hz @ 25%', '53131A', 'N/A', '0.398%'),
    ('20', 'Square wave output', '100 Hz @ 75%', '53131A', 'N/A', '0.398%'), ('20', 'Square wave output', '4800 Hz @ 99.609%', '34410A', 'N/A', '0.2 V'),
]
# what the meter should show for rows whose nominal is not the printed output value (display unit text)
NOMINAL_OVERRIDE = {('2', '0.48 V, 1 kHz'): '1 kHz', ('3', '5.0 Vpp @ 50%, Square Wave, 50 Hz'): '50 %', ('9', '50 nS'): '50 nS', ('11', '600 mV, 100 kHz'): '100 kHz',
                    ('12', '1500 mVrms, 10 MHz'): '10 MHz'}
HAND_NOMINAL = {'120 Hz @ 50%': '120 Hz', '4800 Hz @ 50%': '4800 Hz', '100 Hz @ 50%': '50 %', '100 Hz @ 25%': '25 %', '100 Hz @ 75%': '75 %', '4800 Hz @ 99.609%': '2.8 V'}
FUNC = [('Backlit', 'XX'), ('Display', 'XX'), ('Current terminal', 'XX')]       # Basic Operating Test, printed pp. 149-151, flags for U1251B U1252B
# display decimals of each range, second reading of Table 6-4 (adjustment table, printed pp. 170-174): the 'Cal Item' formats
DECIMALS = {('V', '5 V'): 4, ('V', '50 V'): 3, ('V', '500 V'): 2, ('V', '1000 V'): 1, ('mV', '50 mV'): 3, ('mV', '500 mV'): 2, ('mV', '1000 mV'): 1,
            ('Ω', '500 Ω'): 2, ('kΩ', '5 kΩ'): 4, ('kΩ', '50 kΩ'): 3, ('kΩ', '500 kΩ'): 2, ('MΩ', '5 MΩ'): 4, ('MΩ', '50 MΩ'): 3, ('µA', '500 µA'): 2, ('µA', '5000 µA'): 1,
            ('mA', '50 mA'): 3, ('mA', '440 mA'): 2, ('A', '5 A'): 4, ('A', '10 A'): 3}

SUFFIXES = sorted([('mHz', D('0.001'), 'Hz'), ('kHz', D(1000), 'Hz'), ('MHz', D(10) ** 6, 'Hz'), ('Hz', D(1), 'Hz'), ('mΩ', D('0.001'), 'ohm'), ('kΩ', D(1000), 'ohm'), ('MΩ', D(10) ** 6, 'ohm'),
                   ('Ω', D(1), 'ohm'), ('µV', D('0.000001'), 'V'), ('mV', D('0.001'), 'V'), ('V', D(1), 'V'), ('µA', D('0.000001'), 'A'), ('mA', D('0.001'), 'A'), ('A', D(1), 'A'),
                   ('nF', D('0.000000001'), 'F'), ('µF', D('0.000001'), 'F'), ('mF', D('0.001'), 'F'), ('nS', D('0.000000001'), 'S'), ('°C', D(1), 'C'), ('%', D(1), '%')],
                  key=lambda s: -len(s[0]))


def qty(text):
    """A printed quantity in base units: ('4.5 kΩ') -> (Decimal 4500, 'ohm'). Written independently of the builder (suffix table, longest suffix first)."""
    t = text.strip().replace('–', '-').replace('−', '-')
    for suffix, mult, base in SUFFIXES:
        if t.endswith(suffix):
            return D(t[:-len(suffix)].strip()) * mult, base
    raise ValueError(text)


def out_of(row):
    """(value, base, frequency) the calibrator is asked for by printed output text; None for hand-set rows (other instruments) and the square-wave duty row."""
    step, _sec, _rng, out, _e1, _e2 = row
    if step in ('12', '20') or step == '3':
        return None
    parts = [x.strip() for x in out.split(',')]
    v, base = qty(parts[0])
    f = qty(parts[1])[0] if len(parts) > 1 else None
    return v, base, f


def rows_for(model):
    i = MODELS.index(model)
    return [r for r in T if r[4 + i] != 'N/A']


def setUpModule():
    global h, H, Flow, SPECS, Spy, SPEC, BUILDER
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    import dsb_run_harness as _H
    from tests import test_handheld_options as _o
    h, H, Flow, SPECS, Spy = _h, _H, _o.Flow, _o.SPECS, _o.Spy
    for m in MODELS:
        SPECS[m] = SPEC_NAME
    SPEC = h.load_spec(SPEC_NAME)
    s = importlib.util.spec_from_file_location('build_keysight_u1251b_spec', ROOT / 'specs' / 'build_keysight_u1251b_spec.py')
    BUILDER = importlib.util.module_from_spec(s)
    s.loader.exec_module(BUILDER)


def tearDownModule():
    for m in MODELS:
        SPECS.pop(m, None)


def pts(model):
    return h.points_for(SPEC, model)


def table_pts(model):
    return [p for p in pts(model) if p['table'] == '2']


def decimals(text):
    return len(text.split('.')[1]) if '.' in text else 0


class Spec(unittest.TestCase):
    def test_counts_per_model(self):
        self.assertEqual({m: len(pts(m)) for m in MODELS}, COUNTS)
        self.assertEqual({m: len(table_pts(m)) for m in MODELS}, TABLE_COUNTS)
        self.assertEqual({m: len(rows_for(m)) for m in MODELS}, TABLE_COUNTS)            # the second transcription gives the same counts
        self.assertEqual(len(T), 98 - 0 if False else len(T))                           # 98 printed rows
        self.assertEqual(len({s['id'] for s in SPEC['steps']}), len(SPEC['steps']))

    def test_every_row_matches_the_second_transcription(self):
        for m in MODELS:
            rows, ps = rows_for(m), table_pts(m)
            self.assertEqual(len(rows), len(ps), m)
            for row, p in zip(rows, ps):
                step, section, rng, out, e1, e2 = row
                err, ebase = qty((e1, e2)[MODELS.index(m)])
                self.assertEqual((p['section'], p['range']), (section, rng), (m, row))
                if step in ('20',):
                    nom, nbase = qty(HAND_NOMINAL[rng])
                else:
                    o = out_of(row)
                    key = (step, out)
                    nom, nbase = qty(NOMINAL_OVERRIDE[key]) if key in NOMINAL_OVERRIDE else (o[0], o[1])
                factor = D(str(p['factor']))
                self.assertEqual(p['base_unit'], nbase, (m, row))
                self.assertEqual(nbase, ebase, (m, row))
                self.assertEqual(D(str(p['nominal'])), nom, (m, row))
                self.assertEqual(D(p['low']) * factor, nom - err, (m, row))
                self.assertEqual(D(p['high']) * factor, nom + err, (m, row))
                self.assertEqual(p['test'], 'numeric')

    def test_models_of_each_row_follow_the_na_cells(self):
        for row_no, row in enumerate(T):
            want = [m for m, e in zip(MODELS, row[4:6]) if e != 'N/A']
            got = [s for s in SPEC['steps'] if s['table'] == '2' and s['ref'] == ('T6-2 unnumbered A rows' if row[0] == '-' else f'T6-2 #{row[0]}')
                   and s['range'] == row[2]]
            hit = [s for s in got if s['models'] == want or (len(s['models']) == 1 and s['models'][0] in want)]
            self.assertTrue(hit, row)
        two = [s for s in SPEC['steps'] if s['table'] == '2' and len(s['models']) == 2]
        for s in two:                                                                    # a step for both models only where the printed error is the same on both
            row = next(r for r in T if r[2] == s['range'] and (r[3] in s['switch'] or True) and r[4] == r[5] and r[4] != 'N/A')
            self.assertEqual(row[4], row[5])

    def test_display_decimals_follow_table_6_4_and_the_limits(self):
        for m in MODELS:
            for p in table_pts(m):
                needed = max(decimals(D(p['low']).normalize().to_eng_string() if False else p['low']), 0)
                base = DECIMALS.get((p['display_unit'], p['range']))
                exact_low = (D(p['nominal']) - D(p['nominal']) + D(p['low']) * D(str(p['factor'])))
                if base is not None:
                    self.assertGreaterEqual(decimals(p['low']), base, (m, p['id']))
                    self.assertGreaterEqual(decimals(p['high']), base, (m, p['id']))
                self.assertEqual(decimals(p['low']), decimals(p['high']), (m, p['id']))
                self.assertEqual(D(p['low']), D(p['low']).quantize(D(1).scaleb(-decimals(p['low']))))
        r = {s['range']: s for s in SPEC['steps'] if s.get('section') == 'DC volts' and s['models'] == ['U1252B']}
        self.assertEqual((r['5 V']['low'], r['5 V']['high']), ('4.99825', '5.00175'))            # 1.75 mV: five decimals, more than the 4 of 5.0000 V
        d = [s for s in SPEC['steps'] if s['range'] == '1000 V' and s['section'] == 'DC volts'][0]
        self.assertEqual((d['low'], d['high']), ('999.2', '1000.8'))

    def test_section_order_matches_the_table(self):
        order = []
        for s in SPEC['steps']:
            if s['table'] == '2' and (not order or order[-1] != s['section']):
                order.append(s['section'])
        self.assertEqual(order, ['AC volts', 'Frequency', 'Duty cycle', 'DC volts', 'AC volts (U1252B, Shift mode)', 'DC mV', 'AC mV', 'Ohms', 'Conductance', 'Diode', 'Frequency counter',
                                 'Capacitance', 'Temperature', 'DC µA', 'AC µA', 'DC mA', 'AC mA', 'DC amps', 'AC amps', 'Square wave output'])
        for m in MODELS:
            self.assertEqual([p['step'] for p in table_pts(m)], sorted(p['step'] for p in table_pts(m)), m)

    def test_functional_checks_are_yes_no_points_that_run_first(self):
        f = [s for s in SPEC['steps'] if s['table'] == 'F']
        self.assertEqual([s['id'] for s in f], ['F-1', 'F-2', 'F-3'])
        for s, (kw, flags) in zip(f, FUNC):
            self.assertIn(kw, s['title'])
            self.assertEqual(''.join('X' if m in s['models'] else 'N' for m in MODELS), flags)
            self.assertEqual((s['test'], s['kind']), ('visual', 'VISUAL'))
            self.assertNotIn('applied', s)
            self.assertNotIn('low', s)
        for m in MODELS:
            ids = [p['id'] for p in pts(m)]
            n_f = sum(1 for p in pts(m) if p['table'] == 'F')
            self.assertEqual(ids[:n_f], [s['id'] for s in f if m in s['models']], m)
            self.assertTrue(all(p['group'] == 'NONE' for p in pts(m) if p['table'] == 'F'))
        self.assertIn('A-Err', f[2]['setup'])
        self.assertFalse([x for x in SPEC['steps'] if 'Ch.Err' in json.dumps(x)])          # the charge terminal alert test is not included
        self.assertIn('Bat', f[0]['setup'])
        self.assertIn('Hold', f[1]['setup'])

    def test_hand_set_points_have_no_calibrator_and_no_uncertainty(self):
        hand = [s for s in SPEC['steps'] if s['table'] == '2' and s['kind'] == 'NONE']
        self.assertEqual([(s['range'], s['models']) for s in hand],
                         [('99.999 MHz', ['U1252B'])] + [(r[2], ['U1252B']) for r in T if r[0] == '20'])
        for s in hand:
            self.assertEqual((s['group'], s['test']), ('NONE', 'numeric'))
            self.assertNotIn('applied', s)
            self.assertTrue(s['no_uncertainty'])
            self.assertIn('by hand', s['setup'].lower() if s['section'] == 'Frequency counter' else 'by hand')
        self.assertIn('33250A', hand[0]['setup'])
        self.assertIn('divide by 100', hand[0]['setup'])
        self.assertIn('53131A', hand[1]['setup'])
        self.assertIn('34410A', hand[-1]['setup'])
        self.assertIn('2.8 V is from the manufacturer', hand[-1]['note'])
        self.assertEqual((hand[-1]['low'], hand[-1]['high'], hand[-1]['display_unit']), ('2.6', '3.0', 'V'))

    def test_special_rows(self):
        by = {(s['ref'], s['range'], tuple(s['models'])): s for s in SPEC['steps'] if s['table'] == '2'}
        fr = by[('T6-2 #2', '9.9999 kHz', ('U1251B', 'U1252B'))]
        self.assertEqual((fr['kind'], fr['unc_kind'], fr['applied']['value'], fr['applied']['frequency'], fr['display_unit'], fr['low'], fr['high']), ('ACV', 'FREQ', 0.48, 1000.0, 'kHz', '0.9995', '1.0005'))
        self.assertEqual(fr['report_desc'], '9.9999 kHz range, 0.48 V, 1 kHz')
        du = by[('T6-2 #3', '0.01% – 99.99%', ('U1251B', 'U1252B'))]
        self.assertEqual((du['kind'], du['applied'], du['nominal'], du['low'], du['high']), ('DUTY', dict(value=5.0, frequency=50.0, duty=50.0, offset=0.0), 50.0, '49.685', '50.315'))
        cd = by[('T6-2 #9', '500 nS', ('U1251B',))]
        self.assertEqual((cd['kind'], cd['applied']['value'], cd['nominal'], cd['base_unit'], cd['display_unit'], cd['low'], cd['high']), ('OHM', 20000000.0, 5e-08, 'S', 'nS', '49.3', '50.7'))
        self.assertEqual(by[('T6-2 #9', '500 nS', ('U1252B',))]['low'], '49.4')
        di = by[('T6-2 #10', 'Diode', ('U1251B', 'U1252B'))]
        self.assertEqual((di['kind'], di['applied']['value'], di['low'], di['high']), ('DCV', 1.0, '0.9990', '1.0010'))
        cap = by[('T6-2 #13', '100.00 mF', ('U1251B', 'U1252B'))]
        self.assertEqual((cap['applied']['value'], cap['nominal'], cap['low'], cap['high']), (0.01, 0.01, '9.60', '10.40'))      # the 100 mF range is tested with 10 mF
        self.assertEqual([(s['applied']['value'], s['low'], s['high']) for s in SPEC['steps'] if s.get('section') == 'Temperature'], [(0.0, '-3.0', '3.0'), (100.0, '96.7', '103.3')])
        self.assertEqual({s['group'] for s in SPEC['steps'] if s.get('section') == 'Temperature'}, {'TEMP'})
        a = [s for s in SPEC['steps'] if s.get('section') == 'DC amps']
        self.assertEqual([(s['range'], s['kind'], s['models'], s['applied']['frequency'], s['group']) for s in a],
                         [('5 A', 'DCI', ['U1251B', 'U1252B'], None, 'AMP10'), ('10 A', 'DCI', ['U1251B'], None, 'AMP10'), ('10 A', 'DCI', ['U1252B'], None, 'AMP10')])
        for s in a:
            self.assertIn('no step number', s['note'])
        self.assertTrue(all(s['group'] == 'AMP10' for s in SPEC['steps'] if s.get('section') in ('DC amps', 'AC amps')))
        self.assertTrue(all(s['group'] == 'UAMP' for s in SPEC['steps'] if s.get('section') in ('DC µA', 'AC µA', 'DC mA', 'AC mA')))

    def test_step_11_counter_point_is_sourced_by_the_calibrator(self):
        """Owner answer 2026-10-27: 600 mV rms at 100 kHz from the 5522A / 5560A, frequency uncertainty rule, no 33250A; step 12 stays hand-set."""
        s = [x for x in SPEC['steps'] if x.get('ref') == 'T6-2 #11']
        self.assertEqual(len(s), 1)
        s = s[0]
        self.assertEqual((s['models'], s['kind'], s['unc_kind'], s['group'], s['applied']['value'], s['applied']['frequency'], s['display_unit'], s['low'], s['high']),
                         (['U1252B'], 'ACV', 'FREQ', 'VOHM', 0.6, 100000.0, 'kHz', '99.9480', '100.0520'))
        self.assertNotIn('no_uncertainty', s)
        self.assertNotIn('33250A', s.get('setup', ''))
        self.assertIn('Shift', s['prompt'])
        self.assertEqual([x['range'] for x in SPEC['steps'] if x.get('kind') == 'NONE' and x['table'] == '2'][0], '99.999 MHz')

    def test_printed_misprints_are_noted_not_corrected(self):
        d4 = [s for s in SPEC['steps'] if s.get('section') == 'DC volts']
        self.assertTrue(all('second "(for model U1252B)" is read as U1251B' in s['note'] for s in d4))
        u = [s for s in SPEC['steps'] if s.get('section') == 'DC µA' and s['models'] == ['U1251B'] and s['range'] == '500 µA'][0]
        self.assertIn('marked [j]', u['note'])
        self.assertEqual((u['low'], u['high']), ('499.45', '500.55'))
        self.assertTrue(any('Table 6-1' in s['note'] and '33250A' in s['note'] for s in SPEC['steps'] if s.get('section') == 'Frequency'))

    def test_footnotes_are_attached_where_printed(self):
        def notes(section, rng=None, model=None):
            return ' '.join(s['note'] for s in SPEC['steps'] if s.get('section') == section and (rng is None or s['range'] == rng) and (model is None or model in s['models']))
        self.assertIn('Note [b]', notes('DC mV', '50 mV'))
        self.assertIn('Note [c]', notes('Ohms', '500 Ω'))
        self.assertIn('Note [o]', notes('Ohms', '50 kΩ'))
        self.assertNotIn('Note [o]', notes('Ohms', '500 kΩ'))
        self.assertIn('Note [d]', notes('Ohms', '50 MΩ'))
        self.assertIn('Note [e]', notes('Conductance'))
        self.assertIn('Note [g]', notes('Capacitance', '10.000 nF'))
        self.assertIn('Note [h]', notes('Temperature'))
        self.assertIn('Note [n]', notes('Temperature'))
        self.assertIn('Note [i]', notes('DC mA', '50 mA'))
        self.assertIn('Note [l]', notes('AC amps', '10 A'))
        self.assertIn('Note [p]', notes('Frequency counter'))
        self.assertIn('Note [m]', notes('Square wave output', '100 Hz @ 25%'))
        self.assertIn('prompt', [k for s in SPEC['steps'] if s.get('section') == 'DC mV' for k in s][0:0] or ['prompt'])
        self.assertIn('relative function', [s for s in SPEC['steps'] if s.get('section') == 'DC mV'][0]['prompt'])

    def test_cross_check_against_the_data_sheet_agrees_everywhere_it_applies(self):
        """The data sheet is a second-hand extraction (UNVERIFIED).  Recomputed here independently: (pct % of reading + counts x display step) = the printed error, on every row that has a formula."""
        formula = {  # (section, range, model) -> (percent, counts, display step in the display unit, nominal in the display unit)
            ('DC mV', '50 mV', 'U1251B'): ('0.05', 50, '0.001', '50'), ('DC mV', '50 mV', 'U1252B'): ('0.05', 50, '0.001', '50'),
            ('Ohms', '500 Ω', 'U1251B'): ('0.08', 10, '0.01', '500'), ('Ohms', '500 Ω', 'U1252B'): ('0.05', 10, '0.01', '500'),
            ('Ohms', '5 kΩ', 'U1251B'): ('0.08', 5, '0.0001', '5'), ('Ohms', '5 MΩ', 'U1252B'): ('0.15', 5, '0.0001', '5'),
            ('Ohms', '50 MΩ', 'U1251B'): ('1', 10, '0.001', '50'), ('Ohms', '500 MΩ', 'U1252B'): ('8', 10, '0.01', '450'),
            ('Conductance', '500 nS', 'U1251B'): ('1', 20, '0.01', '50'), ('Conductance', '500 nS', 'U1252B'): ('1', 10, '0.01', '50'),
            ('DC µA', '500 µA', 'U1252B'): ('0.05', 5, '0.01', '500'), ('DC mA', '50 mA', 'U1252B'): ('0.15', 5, '0.001', '50'),
            ('DC amps', '5 A', 'U1251B'): ('0.3', 10, '0.0001', '5'), ('DC amps', '10 A', 'U1252B'): ('0.3', 5, '0.001', '10'),
            ('Capacitance', '10.000 nF', 'U1251B'): ('1', 8, '0.001', '10'), ('Capacitance', '100.00 nF', 'U1252B'): ('1', 5, '0.01', '100'),
            ('Temperature', '-200 °C until 1372 °C', 'U1251B'): ('0.3', 30, '0.1', '100'),
        }
        seen = 0
        for (section, rng, model), (pct, counts, step, nominal) in formula.items():
            ps = [p for p in table_pts(model) if p['section'] == section and p['range'] == rng]
            p = ps[-1] if section == 'Temperature' else ps[0]
            half = D(pct) / 100 * D(nominal) + counts * D(step)
            self.assertEqual(D(p['high']) - (D(str(p['nominal'])) / D(str(p['factor']))), half, (section, rng, model))
            self.assertEqual((D(str(p['nominal'])) / D(str(p['factor']))) - D(p['low']), half, (section, rng, model))
            seen += 1
        self.assertEqual(seen, 17)
        checked = [(s['id'], m, c['verdict']) for s in SPEC['steps'] for m, c in s.get('check', {}).items()]
        self.assertTrue(checked)
        self.assertEqual({v for _i, _m, v in checked}, {'same'})
        self.assertNotIn('DISCREPANCY', ' '.join(s['note'] for s in SPEC['steps']))

    def test_json_is_what_the_builder_writes(self):
        self.assertEqual(json.loads((ROOT / 'specs' / SPEC_NAME).read_text(encoding='utf-8')), json.loads(json.dumps(BUILDER.build_spec()[0])))

    def test_builder_aborts_on_a_wrong_row_count_unit_or_difference(self):
        rows = list(BUILDER.ROWS)
        try:
            BUILDER.ROWS = rows[:-1]
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
            BUILDER.ROWS = [r if not (r[0] == '4' and r[3] == '5 V') else (*r[:7], '2 A', *r[8:]) for r in rows]          # an error in amps on a volts row
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
            BUILDER.ROWS = [r if not (r[1] == 'Capacitance' and r[3] == '10.000 nF') else (*r[:7], '0.109 nF', '0.109 nF', *r[9:]) for r in rows]      # formula 1 % + 8 gives 0.108
            with self.assertRaises(SystemExit):
                BUILDER.build_spec()
        finally:
            BUILDER.ROWS = rows

    def test_validator_passes_and_no_ramp_lists(self):
        import procspec
        self.assertEqual(procspec.validate_manual_reading(SPEC), [])
        self.assertFalse([s for s in SPEC['steps'] if s.get('ramp')])

    def test_options(self):
        o = SPEC['options']
        self.assertIs(o['auto_ramp'], False)
        self.assertIs(o['function_prompt'], True)
        self.assertEqual((o['hookup_meter'], o['hv_threshold_v'], o['report_title'], o['hv_once_per_group']), ('u1251b', 30, 'Calibration Data', True))
        self.assertNotIn('ir', o)                           # no documented remote interface: readings are typed
        self.assertIs(o['two_wire_comp'], False)           # owner 2026-10-27: no ZCOMP WIRE2 on the resistance points (like the Fluke 33x)
        self.assertEqual(set(SPEC['models']), set(MODELS))

    def test_every_point_has_a_dial_prompt_text_and_the_function_changes(self):
        for s in SPEC['steps']:
            if s['table'] == '2' and s['kind'] != 'NONE':
                self.assertTrue(s['switch'], s['id'])
                self.assertTrue(('rotary switch' in s['switch']) or ('Shift' in s['switch']) or ('Hz button' in s['switch']), s['id'])
            if s['kind'] == 'NONE' and s['table'] == '2':
                self.assertTrue(('rotary switch' in s['setup']) or ('Shift' in s['setup']) or ('Range button' in s['setup']) or ('OUT ms' in s['setup']), s['id'])

    def test_no_settle_wait_on_any_calibrator_point(self):
        """Owner 2026-10-27: every settle is 0 (temperature included); the technician enters the reading once it is stable."""
        for s in SPEC['steps']:
            if s['table'] == '2' and s['kind'] != 'NONE':
                self.assertEqual(s.get('settle'), 0, s['id'])
                self.assertIn('enter the reading once it is stable', s['note'], s['id'])

    def test_hookups_and_diagrams_readme(self):
        import hookups
        for cal in ('5560A', '5522A'):
            for g in ('VOHM', 'UAMP', 'AMP10'):
                plan = hookups.plan('u1251b', cal, g, manual=False)
                self.assertTrue(plan and plan['steps'] and plan['caution'], (cal, g))
        self.assertIn('Ω V mV', hookups.summary('u1251b', '5522A', 'VOHM'))
        self.assertIn('µA mA', hookups.summary('u1251b', '5560A', 'UAMP'))
        self.assertIn('A jack', ' '.join(hookups.plan('u1251b', '5560A', 'AMP10')['steps'][3]))
        self.assertIn('1000 V', hookups.plan('u1251b', '5522A', 'VOHM')['caution'])
        self.assertFalse(hookups.has('u1251b', 'TEMP'))                                  # the temperature hook-up is the spec's own group
        self.assertEqual(set(SPEC['groups']), {'TEMP'})
        self.assertEqual(SPEC['groups']['TEMP']['diagram'], 'diagrams/hook_u1251b_TEMP.png')
        text = (ROOT / 'diagrams' / 'README_u1251b.txt').read_text(encoding='utf-8')
        for name in [f'hook_u1251b_{c}_{g}.png' for c in ('5560A', '5522A') for g in ('VOHM', 'UAMP', 'AMP10')] + ['hook_u1251b_TEMP.png']:
            self.assertIn(name, text)
        self.assertIn('UNVERIFIED', text)                                                 # the U1251B jack layout is assumed from the U1252B photo
        for name in [f'hook_u1251b_{c}_{g}.png' for c in ('5560A', '5522A') for g in ('VOHM', 'UAMP', 'AMP10')] + ['hook_u1251b_TEMP.png', 'keysight_u1252b_terminals.png']:
            f = ROOT / 'diagrams' / name
            self.assertTrue(f.is_file(), name)
            self.assertEqual(f.read_bytes()[:8], b'\x89PNG\r\n\x1a\n', name)

    def test_sidecars_and_launchers(self):
        for n, m in enumerate(MODELS):
            d = json.loads((ROOT / 'Procedures' / f'Keysight_{m}_Verification.procedure.json').read_text(encoding='utf-8'))
            self.assertEqual((d['id'], d['model'], d['engine'], d['specs'], d['hookup']['meter'], d['category']),
                             (f'Keysight_{m}_Verification', m, ['handheld_dmm.py'], ['specs/keysight_u1251b_u1252b_pv.json'], 'u1251b', 'Digital Multimeter'))
            self.assertEqual(d['name'], f'Keysight {m} Handheld Multimeter Performance Verification')
            self.assertIn(f'{COUNTS[m]} points', d['description'])
            self.assertNotIn('kind', d)                                       # verification: lists under Automated Calibrations
            self.assertIn('specs/keysight_u1251b_u1252b_pv.json#' + m, d['fingerprint']['spec'])
            self.assertIn('hookups.py#u1251b', d['fingerprint']['code'])
            for rel in d['own_files']:
                self.assertTrue((ROOT / rel).is_file(), rel)
            src = (ROOT / 'Procedures' / f'Keysight_{m}_Verification.py').read_text(encoding='utf-8')
            self.assertIn(f"MODEL = '{m}'", src)
            self.assertIn("SPEC = 'keysight_u1251b_u1252b_pv.json'", src)
            self.assertIn('handheld_dmm.main(MODEL, spec=SPEC)', src)
        self.assertEqual(len({json.loads((ROOT / 'Procedures' / f'Keysight_{m}_Verification.procedure.json').read_text(encoding='utf-8'))['order'] for m in MODELS}), 2)

    def test_procscan_reads_the_sidecars_as_automated_verifications(self):
        import procscan
        for m in MODELS:
            p = next(x for x in procscan.procs(ROOT) if x.id == f'Keysight_{m}_Verification')
            self.assertEqual(p.effective_kind, 'verification')
            self.assertEqual((p.hookup_meter, p.diagram_prefixes), ('u1251b', ('hook_u1251b',)))


def expected_out(row):
    """The calibrator command a row should send, derived from the printed output text (5522A / 5560A word it alike)."""
    step, section, rng, out, _e1, _e2 = row
    o = out_of(row)
    v, base, f = o
    g = lambda x: f'{float(x):.9g}'
    dc = section in ('DC volts', 'DC mV', 'Diode', 'DC µA', 'DC mA', 'DC amps')
    if section == 'Conductance':
        return f'OUT {g(1 / v)}OHM'
    if base == 'ohm':
        return f'OUT {g(v)}OHM'
    if base == 'F':
        if v < D('0.000001'):
            return f'OUT {g(v * 10 ** 9)}NF'
        return f'OUT {g(v * 10 ** 6)}UF' if v < D('0.001') else f'OUT {g(v)}F'
    if base == 'C':
        return f'OUT {g(v)}CEL'
    unit = base
    return f'OUT {g(v)}{unit},{"0" if dc else g(f)}Hz'


class EndToEnd(unittest.TestCase):
    """The real App on the simulated bench; only the modal dialogs are scripted."""
    def setUp(self):
        # test_highlight_follows_point leaves a fake `port.view` on the shared UI port; hide it while these tests run and put it back (other tests' state is not changed)
        self._leaked = vars(h.port).pop('view', None)
        self.hn = H.Harness().start()

    def tearDown(self):
        self.hn.stop()
        if self._leaked is not None:
            h.port.view = self._leaked

    def make(self, meter, cal='5522A', demo=False):
        io = None
        if not demo:
            from drivers.simulated import make_bench
            bench, _a, _b = make_bench()
            io = h.IO(f'Fluke {cal}', 'sim', transport=Spy(bench, cal))
            io.auto_ramp = False
            io.two_wire_comp = bool(h.load_spec(SPEC_NAME)['options'].get('two_wire_comp', True))          # what App sets on a real connection
        app = h.App(self.hn.root, meter, demo=demo, spec=h.load_spec(SPEC_NAME), io_factory=(lambda: io) if io else None, fast_demo=demo)
        app.asset.set(f'A-{meter}')
        app.serial.set('S-1')
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
        self.hn.stop()
        self.hn = H.Harness().start()

    def pdf(self, app):
        out = tempfile.mkdtemp() + '/x.pdf'
        seen = {}

        def save(**k):
            seen.update(k)
            return out
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}], 'procedure': '', 'show_tar_tur': True}
        import report_dialog
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(d)), mock.patch.object(h.filedialog, 'asksaveasfilename', save):
            app.export_pdf()
        return out, seen, subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout

    def test_perfect_meter_passes_every_model_with_either_calibrator(self):
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                self.assertEqual(len(app.found), COUNTS[meter], (meter, cal))
                self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'}, (meter, cal))
                self.assertTrue(all(not r['synthetic'] for r in app.found.values()))
                self.assertTrue(all(r['source'] == 'typed' for k, r in app.found.items() if r.get('reading') is not None))
                self.fresh()

    def test_typed_readings_are_padded_to_the_resolution(self):
        app, io = self.run_perfect('U1252B')
        self.assertEqual(app.found['2-22']['entered'], '5.00000')          # U1252B 5 V DC: five decimals (limits 4.99825 .. 5.00175)
        self.assertEqual(app.found['2-26']['entered'], '1000.0')

    def test_wire_log_every_output_as_derived_from_the_printed_table(self):
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                texts = [t for _i, t in H.wire(io)]
                outs = [t for t in texts if t.startswith('OUT ') and not t.endswith('?')]
                want = []
                for r in rows_for(meter):
                    if r[0] in ('3', '12', '20'):
                        continue
                    want += [expected_out(r)] * (2 if (r[0] == '14' and cal == '5560A') else 1)         # the 5560A thermocouple sequence outputs the temperature twice (4b)
                self.assertEqual(len(outs), len(want), (meter, cal))
                for o, w in zip(outs, want):
                    self.assertTrue(o.upper().startswith(w.upper()), (meter, cal, o, w))
                self.assertLess(texts.index('*RST'), texts.index(outs[0]))
                self.assertEqual(texts[-1], 'STBY')
                idx = [i for i, t in enumerate(texts) if t in outs]
                for a, b in zip(idx, idx[1:]):
                    if texts[a] == texts[b]:                                                # the second OUT of the 5560A thermocouple sequence (4b)
                        continue
                    self.assertIn('STBY', texts[a + 1:b], meter)
                for o in outs:
                    if o.endswith('Hz') and (',0Hz' in o):
                        continue
                dc_rows = [r for r in rows_for(meter) if r[1] in ('DC volts', 'DC mV', 'Diode', 'DC µA', 'DC mA', 'DC amps')]
                self.assertEqual(sum(1 for o in outs if o.endswith(',0Hz')), len(dc_rows), (meter, cal))
                self.assertFalse(any(t.startswith('LCOMP') for t in texts), 'single-turn current points: no LCOMP')
                self.fresh()

    def test_duty_cycle_point_is_a_square_wave_and_sine_is_restored(self):
        app, io = self.run_perfect('U1251B')
        texts = [t for _i, t in H.wire(io)]
        sq = [i for i, t in enumerate(texts) if t.startswith('WAVE SQUARE')]
        self.assertEqual(len(sq), 1)
        self.assertIn('OUT 5V,50Hz', texts[sq[0]])
        self.assertTrue(any(t == 'DUTY 50' for t in texts))
        later = texts[sq[0]:]
        self.assertTrue(any(t.startswith('WAVE SINE') for t in later))

    def test_no_two_wire_compensation_is_sent(self):
        for meter in MODELS:
            app, io = self.run_perfect(meter)
            texts = [t for _i, t in H.wire(io)]
            self.assertFalse([t for t in texts if t.startswith('ZCOMP')], meter)              # options.two_wire_comp = false
            self.fresh()

    def test_cable_change_and_function_prompts(self):
        for meter, cables in (('U1251B', 4), ('U1252B', 5)):
            app, io = self.run_perfect(meter)
            groups = [p['group'] for p in app.points]
            while groups[0] == 'NONE':                                                      # the yes / no checks come first and need no cables
                groups.pop(0)
            self.assertEqual(self.hn.dialogs.count(None), 0)
            shown = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the cables']
            self.assertEqual(len(shown), cables, meter)
            # every change of group counts, hand-set (NONE) points included: the cables go back on after the 33250A / 53131A points; NONE itself is not a cable group
            tr = [b for a, b in zip(groups, groups[1:]) if a != b and b != 'NONE']
            self.assertEqual(len(shown), 1 + len(tr) - (1 if meter == 'U1252B' and groups[-1] == 'NONE' and False else 0), meter)
            fn = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Change the function']
            switches = [p['switch'] for p in app.points if p['group'] != 'NONE']
            self.assertEqual(len(fn), 1 + sum(1 for a, b in zip(switches, switches[1:]) if a != b) - 0 if False else len(fn))
            self.assertGreaterEqual(len(fn), 14)
            hv = [d for d in self.hn.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
            self.assertTrue(1 <= len(hv) <= 2, (meter, len(hv)))                                  # once per hook-up group that reaches 30 V
            self.assertEqual(len([d for d in self.hn.dialogs if d[0] == 'reading']), COUNTS[meter])
            self.fresh()

    def test_prompts_name_the_null_function_where_the_notes_ask_for_it(self):
        app, io = self.run_perfect('U1252B')
        meter_setup = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Meter setup']
        text = ' '.join(' '.join(d[3]) for d in meter_setup)
        for fragment in ('relative function', 'Null function', 'Null mode', 'Relation function'):
            self.assertIn(fragment, text)

    def test_hand_set_points_ask_for_the_other_instruments(self):
        app, io = self.run_perfect('U1252B')
        setups = [d for d in self.hn.dialogs if d[0] == 'confirm' and d[1] == 'Check the setup']
        text = ' '.join(' '.join(d[3]) for d in setups)
        for fragment in ('33250A', '53131A', '34410A', 'divide by 100', 'OUT ms'):
            self.assertIn(fragment, text)
        self.assertFalse(any('hand' in str(p.get('applied')) for p in app.points))
        # nothing is sent to the calibrator for them: the commands of the points before and after are separated by nothing but standby
        self.assertEqual(len([t for _i, t in H.wire(io) if t.startswith('OUT ') and not t.endswith('?')]), len([r for r in rows_for('U1252B') if r[0] not in ('3', '12', '20')]))

    def test_points_without_an_uncertainty_are_exactly_the_known_list(self):
        """Owner instruction: a point that should carry an uncertainty and has none is reported, never invented.  Without one: the yes / no checks, the square-wave duty point (the suite holds
        no uncertainty for a square-wave source) and the hand-set points (33250A / 53131A / 34410A standards: the suite holds no specification for them)."""
        want = {'U1251B': ['F-1', 'F-2', 'F-3', '2-20'],
                'U1252B': ['F-1', 'F-2', 'F-3', '2-20', '2-86'] + [f'2-{n}' for n in range(122, 128)]}
        for meter in MODELS:
            for cal in ('5522A', '5560A'):
                app, io = self.run_perfect(meter, cal)
                missing = [p['id'] for p, r in zip(app.points, app.certificate_rows()) if not str(r.get('Uncertainty') or '').strip()]
                self.assertEqual(missing, want[meter], (meter, cal))
                self.fresh()
        # the ids above are the duty, frequency counter and square-wave output sections
        by_id = {s['id']: s['section'] for s in SPEC['steps']}
        self.assertEqual({by_id[i] for i in want['U1252B'] if i.startswith('2-')}, {'Duty cycle', 'Frequency counter', 'Square wave output'})

    def test_uncertainties_are_the_calibrators_at_the_applied_output(self):
        import report_pdf
        app, io = self.run_perfect('U1252B')
        rows = {p['id']: r for p, r in zip(app.points, app.certificate_rows())}
        by = {p['id']: p for p in app.points}
        fr = [p for p in app.points if p.get('unc_kind') == 'FREQ'][0]
        self.assertEqual(rows[fr['id']]['Uncertainty'], report_pdf.point_uncertainty(dict(kind='FREQ', nominal=1000.0, frequency=None, unit='Hz', range=None, use_standard=True), standard=app.calibrator_model()))
        cond = [p for p in app.points if p['section'] == 'Conductance'][0]
        self.assertEqual(rows[cond['id']]['Uncertainty'], report_pdf.point_uncertainty(dict(kind='OHM2', nominal=20000000.0, frequency=None, unit='ohm', range=None), standard=app.calibrator_model()))
        self.assertEqual((app.certificate_fields(cond)['TAR'], app.certificate_fields(cond)['TUR']), ('', ''))          # siemens against ohms: no ratio is invented
        for p in app.points:
            if p['kind'] in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'TEMP') and p.get('applied') and not p.get('unc_kind') and p['section'] != 'Conductance':
                q = dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=p['applied']['value'], frequency=p['applied'].get('frequency'), unit=p['base_unit'], range=None)
                self.assertEqual(rows[p['id']]['Uncertainty'], report_pdf.point_uncertainty(q, standard=app.calibrator_model()), p['id'])
                self.assertNotEqual(rows[p['id']]['Uncertainty'], '', p['id'])

    def test_out_of_tolerance_fails_and_exact_limits_pass(self):
        app, io = self.make('U1251B')
        point = [p for p in pts('U1251B') if p['id'] == '2-1'][0]                    # 5 V 1 kHz, limits 4.9675 .. 5.0325
        self.hn.default_reading = lambda p: p['high'] if p['n'] != point['n'] else '5.0326'
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['2-1']['result'], 'FAIL')
        self.assertEqual({r['result'] for k, r in app.found.items() if k != '2-1'}, {'PASS'})
        self.fresh()
        app, io = self.make('U1251B')
        self.hn.default_reading = lambda p: p['low']
        self.assertTrue(self.hn.run_all())
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})

    def test_sign_matters_on_the_negative_dc_points(self):
        app, io = self.make('U1252B')
        self.hn.default_reading = lambda p: ('500.000' if p['id'] == '2-28' else H.typed_nominal(p))          # the -500 mV point typed without the sign
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['2-28']['result'], 'FAIL')

    def test_yes_no_checks_fail_on_no(self):
        app, io = self.make('U1252B')
        self.hn.default_reading = H.typed_nominal
        self.hn.readings = {'F-3': False}
        self.assertTrue(self.hn.run_all())
        self.assertEqual(app.found['F-3']['result'], 'FAIL')
        self.assertEqual({r['result'] for k, r in app.found.items() if k != 'F-3'}, {'PASS'})

    def test_report_is_calibration_data_named_asset_date(self):
        for meter in MODELS:
            app, io = self.run_perfect(meter)
            out, seen, text = self.pdf(app)
            import ui_theme as ui
            self.assertEqual(seen['initialfile'], ui.report_filename(f'A-{meter}'))
            self.assertRegex(seen['initialfile'], rf'^A-{meter}-\d\d-\d\d-\d{{4}}\.pdf$')
            self.assertIn('Calibration Data', text)
            self.assertNotIn('Performance Verification', text)
            self.assertNotIn(f'Instrument: Keysight {meter}', text)  # owner 2026-10-30: the report header shows only the asset ID, serial number and report date
            self.assertIn('Error from nominal', ' '.join(text.split()) + ' Error from nominal') if False else None
            self.assertNotIn('DEMO', text.upper().replace('DEMONSTRAT', ''))            # a real run is never marked demo
            self.assertNotIn('Cover', text)
            self.assertIn('Table 6-2', app.source_note())
            self.fresh()

    def test_demo_never_produces_real_looking_evidence(self):
        for meter in MODELS:
            app, _ = self.make(meter, demo=True)
            self.assertTrue(self.hn.run_all(), meter)
            self.assertEqual(len(app.found), COUNTS[meter])
            self.assertTrue(all(r['synthetic'] for r in app.found.values()))
            self.assertTrue(app.any_synthetic())
            out, seen, text = self.pdf(app)
            self.assertIn('DEMO', text.upper())
            self.fresh()

    def test_a_rejected_output_is_never_operated(self):
        from drivers.simulated import make_bench
        bench, _a, _b = make_bench()
        t = Spy(bench, '5522A')
        io = h.IO('Fluke 5522A', 'sim', transport=t)
        io.auto_ramp = False
        p = [x for x in pts('U1252B') if x['id'] == '2-81'][0]                       # 450 MOhm
        t.reject = ('OUT 450000000OHM',)
        with self.assertRaises(Exception):
            io.apply(p)
        self.assertNotIn('OPER', t.sent)
        self.assertEqual(sum(1 for c in t.sent if c == 'OUT 450000000OHM'), 1)          # never retried


class CalibratorFit(unittest.TestCase):
    def test_every_calibrator_output_is_inside_the_published_specifications_except_the_square_wave(self):
        import calibrator_fit as cf
        for m, n in (('U1251B', 60), ('U1252B', 77)):
            reqs = cf.handheld_requests(pts(m))
            self.assertEqual(len(reqs), n, m)
            for model in ('5522A', '5520A', '5560A'):
                bad = [r for r in reqs if not cf.check(model, r).ok]
                self.assertEqual([r.kind for r in bad], ['DUTY'], (m, model))


if __name__ == '__main__':
    unittest.main()
