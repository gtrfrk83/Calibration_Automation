"""Writes specs/fluke_8808a_adjustment.json (Fluke 8808A, guided ADJUSTMENT over the RS-232 calibration dialog of the Calibration Manual).

Source: Fluke 8808A Digital Multimeter Calibration Manual (October 2008, 56 pages), read from RENDERED PAGE IMAGES (pdftoppm, 110 dpi pages, then
170 dpi crops of Table 3-9 and of the 'Calibration Points' lists read a SECOND time), never from extracted text (the micro and ohm signs corrupt).
Printed pages used:
    3-3   Table 3-1 required equipment (Fluke 5700A + 5725A, Fluke 271 or equivalent for frequency, Fluke 5520A for the resistance adjustment; low thermal 4-wire short)
    3-11  'Adjustment (Calibration)': equipment (= Table 3-1), the three ways (front panel, RS-232 manual, RS-232 automatic = a Fluke MET/CAL program),
          front-panel adjustment (CAL seal, Cal Enable button, the six function keys, RANGE starts a point, the recommended value)
    3-12 .. 3-15  Table 3-9 Adjustment Steps, 124 steps (the BUILT table)
    3-16  front panel: exit / CAL ERROR, notes (4WIRE, ZERO point with the leads removed, mA / 10 A terminals by range, 1.9 V for frequency);
          'RS-232 Calibration (Manual)': *TER, VDC VAC ADC AAC OHMS FREQ, CALREF, the Enter key, 'WAIT...', EXIT
    3-17  W4 note, 'Disconnect Test Leads!' / 'Connect to mA socket!' / 'Connect to 10A socket' notes, 'RS-232 Calibration (Automatic)', 'Calibration Points' (adc, aac)
    3-18  'Calibration Points' (vdc, vac, ohm, hz)
    1-9   Warm Up: one half hour to full uncertainty specifications

What is NOT in the manual (so nothing here invents it): a calibration password or code, a save / lock command, a calibration date or due date, the units and number
format of the recommended-value reply, the reply to the Enter key, how long a point takes, what the meter does with a function that was left incomplete (only 'CAL ERROR').

DISCREPANCIES found while cross-reading Table 3-9 against the 'Calibration Points' lists (each read twice; both values are kept as flags on the step, and the program
asks the METER which value it wants - the meter sends 'a new recommended calibration value' before every point, p. 3-15 / 3-16):
    * VAC, first gain point of each range: Table 3-9 prints 10 mV / 0.1 V / 1 V / 10 V / 37.5 V (steps 23, 27, 31, 35, 39); the list prints 0.05 / 0.5 / 5.0 / 50.0 / 100.0 V.
    * AAC, first gain point of the 2 A and 10 A ranges: Table 3-9 prints 0.1 A and 0.5 A (steps 92, 96); the list prints 0.01 A and 1.0 A.
    All other gain points agree (VDC, ADC, the other AAC and VAC points, ohms, frequency).  The list also carries a 0.0 first value for every range, where Table 3-9 has ONE
    zero step per function (VDC, VAC, AAC, ADC) and, for ohms, a zero on the 200 ohm range only (the other ranges start at 1, 10, 100, 1000, 10000, 1e5 ohm in both).

Run:  python specs/build_8808a_adjustment.py
"""
import json
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
OUT = HERE / 'fluke_8808a_adjustment.json'
DOC = 'Fluke 8808A Digital Multimeter Calibration Manual (October 2008)'
UNITS = {'mV': ('V', D('0.001')), 'V': ('V', D(1)), 'Hz': ('Hz', D(1)), 'kHz': ('Hz', D(1000)), 'Ω': ('ohm', D(1)), 'kΩ': ('ohm', D(1000)), 'MΩ': ('ohm', D(1000000)),
         'µA': ('A', D('0.000001')), 'mA': ('A', D('0.001')), 'A': ('A', D(1))}

def page_of(n):
    """The printed page of a step: 3-12 holds steps 1-30, 3-13 steps 31-62, 3-14 steps 63-95, 3-15 steps 96-124."""
    return 'p. 3-12' if n <= 30 else 'p. 3-13' if n <= 62 else 'p. 3-14' if n <= 95 else 'p. 3-15'


def num(text):
    """'-199.9 mV' -> (Decimal value in base units, base unit). The unit is the last token."""
    value, unit = text.rsplit(' ', 1)
    base, scale = UNITS[unit]
    return D(value) * scale, base


def fmt(d: D) -> str:
    s = format(d.normalize(), 'f')
    return s if s not in ('-0', '') else '0'


# ---------------------------------------------------------------------------------------------------------------------------------- Table 3-9
# Per function: (range_no, [Point column as printed]) groups in the printed order; the zero step(s) are given separately.  Range numbers are those of the
# 'Calibration Points' lists (p. 3-17 / 3-18) = Table 4-11A of the Users Manual (checked against drivers/fluke_8808a.RANGES below).
VDC = [(1, ['-199.9 mV', '-100 mV', '100 mV', '199.9 mV']), (2, ['-1.999 V', '-1 V', '1 V', '1.999 V']), (3, ['-19.99 V', '-10 V', '10 V', '19.99 V']),
       (4, ['-199.9 V', '-100 V', '100 V', '199.9 V']), (5, ['-1000 V', '-500 V', '500 V', '1000 V'])]
VAC = [(1, ['10 mV', '100 mV', '150 mV', '199.9 mV']), (2, ['0.1 V', '1 V', '1.5 V', '1.999 V']), (3, ['1 V', '10 V', '15 V', '19.99 V']),
       (4, ['10 V', '100 V', '150 V', '199.9 V']), (5, ['37.5 V', '200 V', '500 V', '750 V'])]
FREQ = [(1, ['500 Hz', '1 kHz', '1.5 kHz']), (2, ['5 kHz', '10 kHz', '15 kHz']), (3, ['50 kHz', '100 kHz', '150 kHz']), (4, ['250 kHz', '500 kHz', '750 kHz'])]
OHMS = [(1, ['50 Ω', '100 Ω', '150 Ω']), (2, ['1 Ω', '0.5 kΩ', '1 kΩ', '1.5 kΩ']), (3, ['10 Ω', '5 kΩ', '10 kΩ', '15 kΩ']), (4, ['100 Ω', '50 kΩ', '100 kΩ', '150 kΩ']),
        (5, ['1 kΩ', '0.5 MΩ', '1 MΩ', '1.5 MΩ']), (6, ['10 kΩ', '5 MΩ', '10 MΩ', '15 MΩ']), (7, ['100 kΩ', '20 MΩ', '50 MΩ', '100 MΩ'])]
AAC = [(1, ['1 mA', '5 mA', '10 mA', '19.99 mA']), (2, ['10 mA', '50 mA', '100 mA', '199.9 mA']), (3, ['0.1 A', '0.5 A', '1 A', '1.999 A']), (4, ['0.5 A', '2 A', '5 A', '10 A'])]
ADC = [(1, ['-199.9 µA', '-100 µA', '100 µA', '199.9 µA']), (2, ['-1999 µA', '-1000 µA', '1000 µA', '1999 µA']), (3, ['-19.99 mA', '-10 mA', '10 mA', '19.99 mA']),
       (4, ['-199.9 mA', '-100 mA', '100 mA', '199.9 mA']), (5, ['-1.999 A', '-1 A', '1 A', '1.999 A']), (6, ['-10 A', '-5 A', '5 A', '10 A'])]

# 'Calibration Points' (p. 3-17 / 3-18), the four GAIN values of each range, base units (the leading 0.0 of every range is the zero point, see the docstring).
LIST = {
    'ADC': {1: ['-0.0001999', '-0.0001', '0.0001', '0.0001999'], 2: ['-0.001999', '-0.001', '0.001', '0.001999'], 3: ['-0.01999', '-0.01', '0.01', '0.01999'],
            4: ['-0.1999', '-0.1', '0.1', '0.1999'], 5: ['-1.999', '-1.0', '1.0', '1.999'], 6: ['-10.0', '-5.0', '5.0', '10.0']},
    'AAC': {1: ['0.001', '0.005', '0.01', '0.01999'], 2: ['0.01', '0.05', '0.1', '0.1999'], 3: ['0.01', '0.5', '1.0', '1.999'], 4: ['1.0', '2.0', '5.0', '10.0']},
    'VDC': {1: ['-0.1999', '-0.1', '0.1', '0.1999'], 2: ['-1.999', '-1.0', '1.0', '1.999'], 3: ['-19.990', '-10.0', '10.0', '19.990'], 4: ['-199.90', '-100.0', '100.0', '199.9'],
            5: ['-1000.0', '-500.0', '500.0', '1000.0']},
    'VAC': {1: ['0.05', '0.10', '0.15', '0.1999'], 2: ['0.5', '1.0', '1.5', '1.999'], 3: ['5.0', '10.0', '15.0', '19.99'], 4: ['50.0', '100.0', '150.0', '199.9'], 5: ['100.0', '200.0', '500.0', '750.0']},
    'OHMS': {1: ['0.5E+2', '1.0E+2', '1.5E+2'], 2: ['1.0', '0.5E+3', '1.0E+3', '1.5E+3'], 3: ['10.0', '0.5E+4', '1.0E+4', '1.5E+4'], 4: ['100.0', '0.5E+5', '1.0E+5', '1.5E+5'],
             5: ['1000.0', '0.5E+6', '1.0E+6', '1.5E+6'], 6: ['10000.0', '0.5E+7', '1.0E+7', '1.5E+7'], 7: ['1.0E+5', '0.2E+8', '0.5E+8', '1.0E+8']},
    'FREQ': {1: ['500', '1000', '1500'], 2: ['5000', '10000', '15000'], 3: ['50000', '100000', '150000'], 4: ['250000', '500000', '750000']},
}
CONFLICT_IDS = {23, 27, 31, 35, 39, 92, 96}          # the steps whose Table 3-9 value differs from the list (read twice)
CHARACTERIZE = {('ADC', 1), ('ADC', 2), ('ADC', 4), ('ADC', 5)}      # "need characterize 5520A with 8508A" is printed beside these ranges (p. 3-15)
RANGE_KIND = {'VDC': 'DCV', 'VAC': 'ACV', 'ADC': 'DCI', 'AAC': 'ACI', 'OHMS': 'OHM4', 'FREQ': 'FREQ'}
FUNCTIONS = [
    ('VDC', 'Volts DC', 'Volts DC: zero point with the 4-wire short, gains with the 5700A / 5725A (Table 3-9, steps 1 to 21)'),
    ('VAC', 'Volts AC', 'Volts AC: zero with the calibrator in standby or disconnected, gains at 1 kHz with the 5700A / 5725A (steps 22 to 42)'),
    ('FREQ', 'Frequency', 'Frequency: 1.9 V at 500 Hz to 750 kHz, "adjust using 5520A" (steps 43 to 54)'),
    ('OHMS', 'Resistance (4-wire, then 2-wire)', 'Ohms: "adjust using 5520A": 4-wire steps 55 to 66, 2-wire steps 67 to 82'),
    ('AAC', 'Current AC', 'Current AC: zero with the inputs open, gains at 500 Hz with the 5700A / 5725A (steps 83 to 99)'),
    ('ADC', 'Current DC', 'Current DC: zero with the inputs open, gains with the 5700A / 5725A; the 5520A must be characterized with an 8508A on four ranges (steps 100 to 124)'),
]
TITLES = {'VDC': 'DC volts', 'VAC': 'AC volts', 'FREQ': 'Frequency', 'OHMS': 'Resistance', 'AAC': 'AC current', 'ADC': 'DC current'}


def group_of(func, range_no, zero, wire):
    if func == 'VDC':
        return 'ZERO_SHORT' if zero else 'VOLT'
    if func in ('VAC', 'FREQ'):
        return 'VOLT'
    if func == 'OHMS':
        return 'ZERO_SHORT' if zero else ('OHM4' if wire == 4 else 'OHM2')
    if zero:
        return 'ZERO_OPEN'
    if func == 'ADC':
        return 'IMA' if range_no <= 4 else 'I2A' if range_no == 5 else 'I10A'
    return 'IMA' if range_no <= 2 else 'I2A' if range_no == 3 else 'I10A'


def build():
    from drivers.fluke_8808a import RANGES
    steps = []

    def add(func, range_no, text, zero=False, printed_input=None, list_value=None, wire=None, desc=''):
        n = len(steps) + 1
        if zero:
            value, unit = D(0), {'VDC': 'V', 'VAC': 'V', 'AAC': 'A', 'ADC': 'A', 'OHMS': 'ohm'}[func]
        else:
            value, unit = num(text)
        if func == 'FREQ':
            src = {'kind': 'ACV', 'value': '1.9', 'unit': 'V', 'frequency': fmt(value)}      # 1.9 V at the test frequency (p. 3-13, p. 3-16 note)
        elif zero:
            src = None                                                                         # short / open / calibrator in standby: no calibrator output (the zero ohm point uses the 4-wire short, owner's policy)
        else:
            src = {'kind': {'VDC': 'DCV', 'VAC': 'ACV', 'ADC': 'DCI', 'AAC': 'ACI', 'OHMS': 'OHM'}[func], 'value': fmt(value), 'unit': unit,
                   'frequency': '1000' if func == 'VAC' else '500' if func == 'AAC' else None}
        table = RANGES['DCV' if func == 'VDC' else 'ACV' if func == 'VAC' else 'DCI' if func == 'ADC' else 'ACI' if func == 'AAC' else 'FREQ' if func == 'FREQ' else 'OHM4']
        s = dict(id=f'S{n:03d}', n=n, function=func, command=func, range_no=range_no, range=(table[range_no - 1] if range_no else None),
                 title=f'{TITLES[func]} {text}' + (' (zero)' if zero else ''), point={'value': fmt(value), 'unit': 'Hz' if func == 'FREQ' else unit, 'text': text}, source=src,
                 group=group_of(func, range_no or 0, zero, wire), zero=zero, wire=wire, page=f'{page_of(n)} (Table 3-9, step {n})', printed_input=printed_input or text, description=desc,
                 list_value=list_value, conflict=(n in CONFLICT_IDS), characterize=((func, range_no) in CHARACTERIZE and not zero))
        steps.append(s)
        return s

    # VDC
    add('VDC', None, '0 mV/0V', zero=True, printed_input='0 mV', desc='Zero point of VDC, all ranges')
    for rno, pts in VDC:
        for i, t in enumerate(pts):
            add('VDC', rno, t, list_value=LIST['VDC'][rno][i], desc=f'Gain of VDC, {fmt(D(str(RANGES["DCV"][rno - 1])))} V range')
    # VAC
    add('VAC', None, '0 mV/0 V', zero=True, printed_input='0 mV', desc='Zero point of VAC, all ranges')
    for rno, pts in VAC:
        for i, t in enumerate(pts):
            add('VAC', rno, t, printed_input=f'{t}@1 kHz', list_value=LIST['VAC'][rno][i], desc=f'Gain of VAC, {fmt(D(str(RANGES["ACV"][rno - 1])))} V range')
    # FREQ
    for rno, pts in FREQ:
        for i, t in enumerate(pts):
            add('FREQ', rno, t, printed_input='1.9 V@' + t, list_value=LIST['FREQ'][rno][i], desc='Frequency')
    # OHMS
    add('OHMS', 1, '0 Ω', zero=True, wire=4, printed_input='0 Ω, 4Wire', desc='Zero point of OHMS, 200 Ω range; made with the low thermal 4-wire short on INPUT and SENSE (owner policy), no calibrator output')
    for rno, pts in OHMS:
        wire = 4 if rno <= 3 else 2
        for i, t in enumerate(pts):
            lv = LIST['OHMS'][rno][i]
            add('OHMS', rno, t, printed_input=f'{t}, {wire}Wire', list_value=lv, wire=wire, desc=f'Gain of OHMS, {RANGES["OHM2"][rno - 1]:g} Ω range')
    # AAC
    add('AAC', None, '0 mA/0 A', zero=True, printed_input='Open, no connection', desc='Zero point of AAC, all ranges')
    for rno, pts in AAC:
        for i, t in enumerate(pts):
            add('AAC', rno, t, printed_input=f'{t}@500 Hz', list_value=LIST['AAC'][rno][i], desc=f'Gain of AAC, {RANGES["ACI"][rno - 1]:g} A range')
    # ADC
    add('ADC', None, '0 µA/0 mA/0 A', zero=True, printed_input='Open, no connection', desc='Zero point of ADC, all ranges')
    for rno, pts in ADC:
        for i, t in enumerate(pts):
            add('ADC', rno, t, list_value=LIST['ADC'][rno][i], desc=f'Gain of ADC, {RANGES["DCI"][rno - 1]:g} A range')
    return steps


def check(steps):
    from drivers.fluke_8808a import RANGES
    assert len(steps) == 124, len(steps)
    counts = {f: sum(1 for s in steps if s['function'] == f) for f, _t, _d in FUNCTIONS}
    assert counts == {'VDC': 21, 'VAC': 21, 'FREQ': 12, 'OHMS': 28, 'AAC': 17, 'ADC': 25}, counts
    assert [s['n'] for s in steps] == list(range(1, 125))
    # the printed sections: steps 1-21 VDC, 22-42 VAC, 43-54 FREQ, 55-82 OHMS, 83-99 AAC, 100-124 ADC
    bounds = {'VDC': (1, 21), 'VAC': (22, 42), 'FREQ': (43, 54), 'OHMS': (55, 82), 'AAC': (83, 99), 'ADC': (100, 124)}
    for s in steps:
        lo, hi = bounds[s['function']]
        assert lo <= s['n'] <= hi, s['id']
    # every gain point equals the 'Calibration Points' list except the known discrepancies (each is flagged on the step)
    diffs = set()
    for s in steps:
        if s['zero'] or s['list_value'] is None:
            continue
        if D(s['point']['value']) != D(s['list_value']):
            diffs.add(s['n'])
    assert diffs == CONFLICT_IDS, sorted(diffs ^ CONFLICT_IDS)
    # every sourced point is inside the range it is adjusted on (+ 0.5 % overrange allowed; the 10 A / 1000 V / 750 V full scale points sit at 100 %)
    for s in steps:
        if s['zero'] or s['function'] == 'FREQ' or s['range'] is None:
            continue
        assert abs(D(s['point']['value'])) <= D(str(s['range'])) * D('1.0001') + D('0.0000001'), (s['id'], s['point'], s['range'])
    # the printed point text must reproduce the value (a typing slip shows here)
    for s in steps:
        if not s['zero']:
            v, _u = num(s['point']['text'])
            assert v == D(s['point']['value']), s['id']
    assert sum(1 for s in steps if s['conflict']) == 7
    assert RANGES['FREQ'] == (2e3, 20e3, 200e3, 1000e3)


GENERAL = [
    'This procedure changes the calibration constants of the Fluke 8808A. The manual: "Meter adjustments, or calibration, should be performed at the desired interval, or whenever a verification test indicates a Meter function is out of tolerance" (p. 3-11). Run the performance verification (As Found) first and again afterwards (As Left).',
    'Warm-up: one half hour to full uncertainty specifications (General Specifications, p. 1-9). The equipment is that of Table 3-1 (p. 3-3): Fluke 5700A with 5725A amplifier (volts, current), Fluke 271 or equivalent for frequency, Fluke 5520A for the resistance adjustment, the low thermal 4-wire short (Fluke PN 2653346) for the DC volts and the zero ohm points.',
    'Method used here: the dialog of "RS-232 Calibration (Manual)" (p. 3-16): for each function the function name, an optional CALREF, the Enter key to confirm the value, the Enter key to start the point. The calibration mode is entered by the operator at the front panel with the calibration button (owner policy); *TER, which the manual shows as the RS-232 entry, is an optional, UNVERIFIED path that is off by default. The manual describes no save, lock, password or date command.',
    'Once a function is selected, ALL of its calibration points must be calibrated before the calibration process is left; otherwise a CAL ERROR shows in the display (p. 3-16). Each function is therefore run as a whole.',
    'Current: use the mA input terminal for the low ranges (ADC ranges 1 to 4, AAC ranges 1 and 2) and the 10 A input terminal for the high ranges (ADC ranges 5 and 6, AAC ranges 3 and 4); for a ZERO point of a current function all test leads are removed (p. 3-16).',
    'Frequency: set the calibrator to 1.9 volts for the frequency calibration input (p. 3-16).',
    'When the meter returns "W4" after the recommended value, 4-wire compensation is enabled on the input (p. 3-17). When it returns "Disconnect Test Leads!" all test leads are removed; "Connect to mA socket!" / "Connect to 10A socket" name the terminal to use (p. 3-17).',
    'Send EXIT to leave the calibration mode at any time; a function that has not been completely calibrated then shows CAL ERROR (p. 3-16).',
]

EQUIPMENT = {
    'table': 'Table 3-1 (p. 3-3)',
    'rows': [['Volts dc', 'Calibrator', 'Fluke 5700A', 'Figure 3-1'], ['Volts dc', '4-wire short', 'Fluke low thermal 4-wire short or equivalent (Fluke PN 2653346)', ''],
             ['Volts ac', 'Calibrator + amplifier', 'Fluke 5700A + Fluke 5725A', 'Figure 3-1'], ['Resistance', 'Calibrator', 'Fluke 5700A', 'Figures 3-2 and 3-3'],
             ['Amps dc', 'Calibrator + amplifier', 'Fluke 5700A + Fluke 5725A', 'Figures 3-4 and 3-5'], ['Amps dc', '4-wire short', 'Fluke low thermal 4-wire short or equivalent (Fluke PN 2653346)', ''],
             ['Amps ac', 'Calibrator + amplifier', 'Fluke 5700A + Fluke 5725A', 'Figures 3-4 and 3-5'],
             ['Frequency', 'Function generator', 'Fluke 271 or equivalent', 'Requires frequency specification better than 0.0025 %'],
             ['Resistance adjust', 'Calibrator', 'Fluke 5520A', 'Requires resistance accuracy better than 0.0045 %']],
    'requirements': {'frequency_spec_pct': '0.0025', 'resistance_accuracy_pct': '0.0045'},
    'note': 'Table 3-9 names the Fluke 5700A / 5725A for volts and current, the Fluke 5520A for frequency and resistance, and says the 5520A must be characterized with an 8508A on four DC current ranges (200 uA, 2000 uA, 200 mA, 2 A); this lab characterizes with a Keysight / Agilent 3458A.',
}


def main():
    steps = build()
    check(steps)
    functions = []
    for order, (fid, title, section) in enumerate(FUNCTIONS, start=1):
        ids = [s['id'] for s in steps if s['function'] == fid]
        functions.append(dict(id=fid, command=fid, order=order, title=title, section=section, steps=ids, count=len(ids)))
    spec = dict(schema=1, kind='bench-dmm-adjustment-dialog', instrument='Fluke 8808A', source=DOC, method='RS-232 Calibration (Manual): *TER and the function / CALREF / Enter dialog (pp. 3-16, 3-17)',
                general=GENERAL, equipment=EQUIPMENT,
                times={'warmup_min': 30, 'point_timeout_s': 180, 'quiet_s': 1.5, 'settle_s': {'DCV': 8, 'ACV': 15, 'DCI': 8, 'ACI': 15, 'OHM': 8, 'OHM_HIGH': 15, 'FREQ': 8}},
                times_note='Only warmup_min is a manual figure (p. 1-9). point_timeout_s, quiet_s and the settle times are ENGINEERING CHOICES of this program (UNVERIFIED: the manual gives no duration for a point and no reply timing).',
                functions=functions, steps=steps,
                discrepancies=[dict(steps=[s['id'] for s in steps if s['conflict']], text='Table 3-9 and the Calibration Points lists (pp. 3-17, 3-18) print different first gain points for the AC volts ranges (steps 23, 27, 31, 35, 39) and the 2 A / 10 A AC current ranges (steps 92, 96); the meter\'s own recommended value decides.')])
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {OUT.name}: {len(steps)} steps, ' + ', '.join(f'{f["id"]} {f["count"]}' for f in functions) + f'; {sum(1 for s in steps if s["conflict"])} flagged discrepancies')


if __name__ == '__main__':
    main()
