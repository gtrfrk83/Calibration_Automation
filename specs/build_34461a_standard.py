"""Builds specs/standards/keysight_34461a_standard.json: the accuracy specifications of the Keysight 34461A 6 1/2 digit Truevolt multimeter, as a standards sheet.

    python specs/build_34461a_standard.py

SOURCE: Keysight data sheet 5991-1983EN 'Digital Multimeters 34460A, 34461A, 34465A (6 1/2 digit), 34470A (7 1/2 digit)', published in USA June 10, 2026,
'Specifications 34461A' printed pp. 13 and 14 (PDF pages 13 and 14).  Shared engine and the period / confidence conventions: build_truevolt_standard.py.
Stored: DC voltage, resistance (4-wire / 2-wire with math null, and 2-wire without math null), DC current, true RMS AC voltage, true RMS AC current, capacitance,
frequency (sine and square wave); periods 90 day / 1 yr / 2 yr (default 1 yr).  Notes only: 24 hour column, temperature coefficients, burden voltages, gate-time
errors, continuity, diode test, DC ratio, temperature (probe accuracy + 0.05 degC / + 0.1 degC: needs the probe's own accuracy).
Every number was read from RENDERED PAGE IMAGES twice (150 dpi whole page, 250 dpi crops); the two readings agree.  tests/test_standard_34461a.py holds a second,
hand-typed transcription of key cells.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_truevolt_standard as eng  # noqa: E402
from build_truevolt_standard import D  # noqa: E402

VERIFIED_AGAINST_IMAGE = True
MODEL = '34461A'

# ---- DC voltage, p. 13: range name / range name (V) / full scale (V) / (90 day, 1 yr, 2 yr) '% of reading + % of range' / typical
DCV = [('100 mV', '0.1', '0.12', ('0.0040 + 0.0035', '0.0050 + 0.0035', '0.0065 + 0.0035'), False),
       ('1 V', '1', '1.2', ('0.0030 + 0.0007', '0.0040 + 0.0007', '0.0055 + 0.0007'), False),
       ('10 V', '10', '12', ('0.0020 + 0.0005', '0.0035 + 0.0005', '0.0050 + 0.0005'), False),
       ('100 V', '100', '120', ('0.0035 + 0.0006', '0.0045 + 0.0006', '0.0060 + 0.0006'), False),
       ('1000 V', '1000', '1000', ('0.0035 + 0.0010', '0.0045 + 0.0010', '0.0060 + 0.0010'), False)]
# ---- resistance, p. 13 (test current in the label of the note only)
OHM = [('100 ohm', '100', '120', ('0.0080 + 0.0040', '0.0100 + 0.0040', '0.0120 + 0.0040'), False),
       ('1 kohm', '1000', '1200', ('0.0080 + 0.0010', '0.0100 + 0.0010', '0.0120 + 0.0010'), False),
       ('10 kohm', '10000', '12000', ('0.0080 + 0.0010', '0.0100 + 0.0010', '0.0120 + 0.0010'), False),
       ('100 kohm', '100000', '120000', ('0.0080 + 0.0010', '0.0100 + 0.0010', '0.0120 + 0.0010'), False),
       ('1 Mohm', '1000000', '1200000', ('0.0080 + 0.0010', '0.0100 + 0.0010', '0.0120 + 0.0010'), False),
       ('10 Mohm', '10000000', '12000000', ('0.0200 + 0.0010', '0.0400 + 0.0010', '0.0600 + 0.0010'), False),
       ('100 Mohm', '100000000', '120000000', ('0.8000 + 0.0100', '0.8000 + 0.0100', '0.8000 + 0.0100'), False)]
# ---- DC current, p. 13
DCI = [('100 uA', '1e-4', '1.2e-4', ('0.0400 + 0.0250', '0.0500 + 0.0250', '0.0600 + 0.0250'), False),
       ('1 mA', '1e-3', '1.2e-3', ('0.0300 + 0.0060', '0.0500 + 0.0060', '0.0600 + 0.0060'), False),
       ('10 mA', '1e-2', '1.2e-2', ('0.0300 + 0.0200', '0.0500 + 0.0200', '0.0600 + 0.0200'), False),
       ('100 mA', '1e-1', '1.2e-1', ('0.0300 + 0.0050', '0.0500 + 0.0050', '0.0600 + 0.0050'), False),
       ('1 A', '1', '1.2', ('0.0800 + 0.0100', '0.1000 + 0.0100', '0.1200 + 0.0100'), False),
       ('3 A', '3', '3', ('0.2000 + 0.0200', '0.2000 + 0.0200', '0.2300 + 0.0200'), False),
       ('10 A', '10', '10', ('0.1200 + 0.0100', '0.1200 + 0.0100', '0.1500 + 0.0100'), False)]
# ---- capacitance, p. 13 (the same figure in all three columns)
CAP = [('1 nF', '1e-9', '1.2e-9', ('0.50 + 0.50',) * 3, False)] + [
    (n, v, fs, ('0.40 + 0.10',) * 3, False) for n, v, fs in
    (('10 nF', '1e-8', '1.2e-8'), ('100 nF', '1e-7', '1.2e-7'), ('1 uF', '1e-6', '1.2e-6'), ('10 uF', '1e-5', '1.2e-5'), ('100 uF', '1e-4', '1.2e-4'))]
# ---- AC voltage, p. 13: ranges 100 mV, 1 V, 10 V, 100 V, 750 V (one table for all); bands (lo, hi, suffix, cells, typical)
ACV_RANGES = [('100 mV', '0.1', '0.12'), ('1 V', '1', '1.2'), ('10 V', '10', '12'), ('100 V', '100', '120'), ('750 V', '750', '750')]
ACV_BANDS = [(3, 5, '', ('1.00 + 0.03',) * 3, False),
             (5, 10, '', ('0.35 + 0.03',) * 3, False),
             (10, 20e3, '', ('0.05 + 0.03', '0.06 + 0.03', '0.07 + 0.03'), False),
             (20e3, 50e3, '', ('0.11 + 0.05', '0.12 + 0.05', '0.13 + 0.05'), False),
             (50e3, 100e3, '', ('0.60 + 0.08',) * 3, False),
             (100e3, 300e3, '', ('4.00 + 0.50',) * 3, False)]
# ---- AC current, pp. 13-14: 100 uA - 100 mA (one table), 1 A, 3 A, 10 A; the 5 kHz - 10 kHz band is typical
def aci_bands(cell):
    return [(3, 5e3, '', (cell,) * 3, False), (5e3, 10e3, 'typical', (cell,) * 3, True)]


ACI_GROUPS = [([('100 uA', '1e-4', '1.2e-4'), ('1 mA', '1e-3', '1.2e-3'), ('10 mA', '1e-2', '1.2e-2'), ('100 mA', '1e-1', '1.2e-1')], '0.10 + 0.04'),
              ([('1 A', '1', '1.2')], '0.10 + 0.04'),
              ([('3 A', '3', '3')], '0.23 + 0.04'),
              ([('10 A', '10', '10')], '0.15 + 0.04')]
# ---- frequency, p. 14, % of reading (90 day, 1 yr, 2 yr); 100 mV - 750 V ranges, 1 second gate time
FREQ = [(3, 10, '3 Hz to 10 Hz', ('0.100', '0.100', '0.100')),
        (10, 100, '10 Hz to 100 Hz', ('0.030', '0.030', '0.030')),
        (100, 1e3, '100 Hz to 1 kHz', ('0.008', '0.010', '0.010')),
        (1e3, 300e3, '1 kHz to 300 kHz', ('0.006', '0.010', '0.010'))]
FREQ_SQ = [(10, 300e3, 'Square wave 10 Hz to 300 kHz', ('0.006', '0.010', '0.010'))]


def functions():
    f = []
    f.append(eng.dc_function('Voltage, DC', 'DCV', 'V', 13, DCV, lambda r, t: [6, 9] + ([10] if r == '1000 V' else []), 'V'))
    f.append(eng.ohm_variant('Resistance [4-wire (or 2-wire with math null)]', 13, OHM, lambda r, t: [6, 11] + ([12] if r == '100 Mohm' else [])))
    f.append(eng.ohm_variant('Resistance [2-wire, no math null]', 13, OHM, lambda r, t: [6, 11], extra_abs='0.2', skip=('100 Mohm',)))
    f.append(eng.dc_function('Current, DC', 'DCI', 'A', 13, DCI, lambda r, t: [6, 13] + ([14] if r == '10 A' else []), 'A'))
    f.append(eng.ac_function('Voltage, AC', 'ACV', 'V', 13, ACV_RANGES, ACV_BANDS, [6, 15], 'V'))
    cur = dict(name='Current, AC', direction='input', page=13, ranges=[])
    for rngs, cell in ACI_GROUPS:
        part = eng.ac_function('Current, AC', 'ACI', 'A', 13 if cell == '0.10 + 0.04' and rngs[0][0] == '100 uA' else 14, rngs, aci_bands(cell), [6, 16], 'A')
        cur['ranges'].extend(part['ranges'])
    f.append(cur)
    f.append(eng.dc_function('Capacitance', 'CAP', 'F', 13, CAP, lambda r, t: [6, 17], 'F'))
    f.append(eng.freq_function('Frequency', 14, FREQ, [18]))
    f.append(eng.freq_function('Frequency [Square wave]', 14, FREQ_SQ, [18, 19]))
    return f


NOTES = eng.common_notes(
    MODEL, 'pp. 13-14 (DC voltage, true RMS AC voltage, resistance, DC current, capacitance, true RMS AC current: p. 13; AC current 1 A / 3 A / 10 A ranges, frequency and the footnotes: p. 14)',
    ': TCAL is the temperature of the last calibration (no ACAL on the 34461A). Footnote 1: DC specifications are for a 90-minute warm-up, aperture of 10 or 100 NPLC and auto zero on; AC specifications are for 90-minute warm-up, slow AC filter and sine wave.',
    'for the 34461A that is 0.0050 % of reading + 0.0035 % of the 0.1 V range on the 100 mV range, +/-(0.0035 % of reading + 0.0005 % of 10 V) on the 10 V range.')
NOTES.update({
    '9': 'DC VOLTS (p. 13): 100 mV to 1000 V; footnote 1 conditions; 1000 V range full scale is the range name (no 20 % over range, footnote 2). Temperature coefficient (information, not stored; add per degC outside TCAL +/- 5 degC, footnote 4): '
         '100 mV 0.0005 + 0.0005, 1 V to 1000 V 0.0005 + 0.0001 (% of reading + % of range).',
    '10': 'DC VOLTS 1000 V range: no additional voltage error is printed for the 34461A (the 34465A prints one for inputs above +/-500 V); none stored.',
    '11': 'RESISTANCE (p. 13, footnote 7): the specifications are for the 4-WIRE ohms function, or the 2-wire ohms function using math null for offset. WITHOUT math null add 0.2 ohm in the 2-wire ohms function: '
          'stored as the separate function "Resistance [2-wire, no math null]" with a fixed 0.2 ohm term (a plain resistance lookup prefers the 4-wire function; pass variant="2-wire"). Test currents (information): '
          '100 ohm and 1 kohm 1 mA, 10 kohm 100 uA, 100 kohm 10 uA, 1 Mohm 5 uA, 10 Mohm 500 nA, 100 Mohm 500 nA || 10 Mohm. Temperature coefficients (not stored): 100 ohm 0.0006 + 0.0005, 1 k - 100 k 0.0006 + 0.0001, '
          '1 Mohm 0.0010 + 0.0002, 10 Mohm 0.0030 + 0.0004, 100 Mohm 0.1500 + 0.0002.',
    '12': 'RESISTANCE 100 Mohm range (p. 13): test current 500 nA in parallel with 10 Mohm (a 2-wire measurement); the no-math-null variant has NO 100 Mohm row (the footnote 0.2 ohm adder is meaningless against 0.8 % and the data sheet does not say whether it applies): UNVERIFIED.',
    '13': 'DC CURRENT (p. 13): ranges 100 uA to 10 A; burden voltage (information): 100 uA < 0.011 V, 1 mA < 0.11 V, 10 mA < 0.05 V, 100 mA < 0.5 V, 1 A < 0.7 V, 3 A < 2.0 V, 10 A < 0.5 V. Temperature coefficients (not stored): '
          '100 uA 0.0020 + 0.0030, 1 mA 0.0020 + 0.0005, 10 mA 0.0020 + 0.0020, 100 mA 0.0020 + 0.0005, 1 A 0.0050 + 0.0010, 3 A 0.0050 + 0.0020, 10 A 0.0050 + 0.0010. The 3 A and 10 A ranges have no 20 % over range.',
    '14': 'DC / AC CURRENT 10 A range (footnote 8): only available on a separate front-panel connector. Add 2 mA base per amp for inputs greater than 5 Arms. The adder is NOT in the stored row.',
    '15': 'TRUE RMS AC VOLTAGE (p. 13): 100 mV, 1 V, 10 V, 100 V and 750 V ranges share one table; footnote 5: sine wave input > 0.3 % of range and > 1 mVrms, 750 V range limited to 8 x 10^7 V.Hz; footnote 6: slow filter (3 Hz) '
          'low-frequency performance, frequencies greater than the filter settings (3 Hz, 20 Hz, 200 Hz) are specified with no additional errors. The 750 V range has no 20 % over range. Temperature coefficients (not stored): '
          '3-5 Hz 0.100 + 0.003, 5-10 Hz 0.035 + 0.003, 10 Hz-20 kHz 0.005 + 0.003, 20-50 kHz 0.011 + 0.005, 50-100 kHz 0.060 + 0.008, 100-300 kHz 0.200 + 0.020. A band edge belongs to both bands; the larger limit is used there (repository rule).',
    '16': 'TRUE RMS AC CURRENT (pp. 13-14): footnote 9: sine wave input > 1 % of range and > 10 uArms. The 5 kHz to 10 kHz band is TYPICAL ("(typ)") on every range (labels say so). Ranges 100 uA, 1 mA, 10 mA, 100 mA share one table; '
          '1 A, 3 A and 10 A have their own. Temperature coefficients (not stored): 0.015 + 0.006 (3 Hz-5 kHz), 0.030 + 0.006 (5-10 kHz, typ). Burden voltages: 100 uA < 0.011 V, 1 mA < 0.11 V, 10 mA < 0.05 V, 100 mA < 0.5 V, 1 A < 0.7 V, 3 A < 2.0 V, 10 A < 0.5 V.',
    '17': 'CAPACITANCE (p. 13, footnote 15 -> printed as footnote 15): 1 nF to 100 uF, % of reading + % of range, the same figure in the 90 day, 1 year and 2 year columns (the printed temperature coefficients are 0.05 + 0.05 for 1 nF and 0.05 + 0.01 for the rest, not stored). '
          'Rows are stored as bipolar value ranges like every sheet (a capacitance cannot be negative).',
    '18': 'FREQUENCY (p. 14): % of reading, 100 mV, 1 V, 10 V, 100 V and 750 V ranges (footnote 14: amplitude 10 % to 120 % of range and less than 750 ACV), 1 second gate time, 7 digits (footnote 12); footnote 13: applies to sine and square inputs >= 100 mV; '
          'for 10 mV to < 100 mV inputs multiply the % of reading error by 10. Stored by frequency band only (no amplitude row). Temperature coefficients (not stored, % of reading per degC): 0.100, 0.035, 0.015, 0.015, 0.015.',
    '19': 'FREQUENCY square wave (footnote 15): square wave input specified for 10 Hz to 300 kHz; stored as the separate function "Frequency [Square wave]" because its band overlaps the sine bands (variant="square"). '
          'Additional gate time errors (% of reading, NOT stored): 0.1 s: 0.200 (3-40 Hz), 0.060 (40-100 Hz), 0.020 (100 Hz-1 kHz), 0.004 (1-300 kHz), square wave 0; 0.01 s: 0.200, 0.200, 0.200, 0.030, square wave 0; 1 s: 0.',
    '20': 'NOT STORED: 24 hour column; continuity (1 kohm) and diode test (5 V) rows (printed 0.0100 + 0.0300 at 1 year; not measuring-standard functions); DC ratio (typical: normalized input accuracy + normalized reference accuracy); '
          'temperature: PT100 (DIN/IEC 751) "Probe accuracy + 0.05 degC", thermistor "Probe accuracy + 0.1 degC" (footnote 11: limited by the selected probe; needs the probe\'s own accuracy, so no number can be stored for the DMM alone).',
})
LIMITS = [
    dict(function='Voltage, DC', limit='100 mV to 1000 V: % of reading + % of range (90 day / 1 yr / 2 yr).', page='13'),
    dict(function='Resistance', limit='100 ohm to 100 Mohm; 4-wire (or 2-wire with math null); 2-wire without math null adds 0.2 ohm.', page='13'),
    dict(function='Current, DC', limit='100 uA to 10 A.', page='13'),
    dict(function='Voltage, AC', limit='True RMS, 100 mV to 750 V, 3 Hz to 300 kHz, six bands.', page='13'),
    dict(function='Current, AC', limit='True RMS, 100 uA to 10 A, 3 Hz to 5 kHz; 5 kHz to 10 kHz typical.', page='13-14'),
    dict(function='Capacitance', limit='1 nF to 100 uF.', page='13'),
    dict(function='Frequency', limit='% of reading, 3 Hz to 300 kHz (sine) and 10 Hz to 300 kHz (square wave), 1 s gate time.', page='14'),
]
PROBLEMS = [
    dict(level='warn', where='standard', what='CONFIDENCE LEVEL: the data sheet prints k = 2 ("compliant to ISO/IEC 17025 for k = 2"), not a percentage; 95 % (divisor 2) is the repository inference from k = 2.'),
    dict(level='warn', where='standard', what='The "% of range" term is taken against the range NAME (0.1 V on the 100 mV range ...); the data sheet does not define "range". UNVERIFIED.'),
    dict(level='warn', where='standard', what='No resolution is recorded on any row: the budget has no resolution term for this standard.'),
    dict(level='warn', where='Resistance [2-wire, no math null] / 100 Mohm', what='No row for the 100 Mohm range: the data sheet does not say whether the 0.2 ohm adder applies there.'),
    dict(level='warn', where='Current, DC / Current, AC / 10 A', what='Footnote 8: add 2 mA base per amp for inputs greater than 5 Arms; not in the stored 10 A rows.'),
    dict(level='warn', where='Current, AC (5 kHz to 10 kHz)', what='Typical, not warranted ("(typ)").'),
    dict(level='warn', where='Temperature', what='PT100 / thermistor accuracy is "probe accuracy + 0.05 / 0.1 degC": not stored (needs the probe accuracy). Continuity, diode test and DC ratio are not stored either.'),
    dict(level='warn', where='Frequency', what='Stored by frequency band only; the amplitude conditions (footnotes 13, 14) and the gate-time errors are notes only.'),
]
CFG = dict(model=MODEL, description='6 1/2 digit Truevolt digital multimeter (Keysight data sheet 5991-1983EN)', json='keysight_34461a_standard.json', builder='build_34461a_standard.py',
           reference='Keysight Digital Multimeters 34460A/34461A/34465A/34470A data sheet 5991-1983EN, published June 10, 2026, "Specifications 34461A" printed pp. 13-14',
           functions=functions, notes=NOTES, limits=LIMITS, problems=PROBLEMS, verified=VERIFIED_AGAINST_IMAGE)


def build():
    return eng.build(CFG)


if __name__ == '__main__':
    eng.main(CFG)
