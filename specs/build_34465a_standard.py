"""Builds specs/standards/keysight_34465a_standard.json: the accuracy specifications of the Keysight 34465A 6 1/2 digit Truevolt multimeter, as a standards sheet.

    python specs/build_34465a_standard.py

SOURCE: Keysight data sheet 5991-1983EN 'Digital Multimeters 34460A, 34461A, 34465A (6 1/2 digit), 34470A (7 1/2 digit)', published in USA June 10, 2026,
'Specifications 34465A' printed pp. 15-17 (PDF pages 15 to 17).  Shared engine and the period / confidence conventions: build_truevolt_standard.py.
Differences from the 34461A that are modelled as printed: DC voltage and resistance are ACAL capable (TACAL +/- 2 degC columns); resistance has 100 Mohm and 1 Gohm
ranges (2-wire only); DC current has 1 uA, 10 uA and 100 uA ranges (typical) and a 1 A range of its own figure; AC current 100 uA to 1 A share one table; AC voltage
and frequency figures differ.  Notes only: 24 hour column, temperature coefficients (with and without ACAL), burden voltages, gate-time errors, continuity, diode test,
DC:DC ratio, temperature (probe + 0.05 / 0.1 degC, thermocouples K J T E N probe + reference junction + 0.3 degC, R + 0.5 degC: need the probe's accuracy).
Every number was read from RENDERED PAGE IMAGES twice (150 dpi whole page, 250 dpi crops); the two readings agree.  tests/test_standard_34465a.py holds a second,
hand-typed transcription of key cells.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_truevolt_standard as eng  # noqa: E402

VERIFIED_AGAINST_IMAGE = True
MODEL = '34465A'

# ---- DC voltage, p. 15: range name / range name (V) / full scale (V) / (90 day, 1 yr, 2 yr) '% of reading + % of range' / typical
DCV = [('100 mV', '0.1', '0.12', ('0.0040 + 0.0035', '0.0050 + 0.0035', '0.0065 + 0.0035'), False),
       ('1 V', '1', '1.2', ('0.0025 + 0.0004', '0.0035 + 0.0004', '0.0050 + 0.0004'), False),
       ('10 V', '10', '12', ('0.0020 + 0.0004', '0.0030 + 0.0004', '0.0045 + 0.0004'), False),
       ('100 V', '100', '120', ('0.0035 + 0.0006', '0.0040 + 0.0006', '0.0055 + 0.0006'), False),
       ('1000 V', '1000', '1000', ('0.0035 + 0.0006', '0.0040 + 0.0006', '0.0055 + 0.0006'), False)]
# ---- resistance, p. 15
OHM = [('100 ohm', '100', '120', ('0.0050 + 0.0040', '0.0060 + 0.0040', '0.0070 + 0.0040'), False),
       ('1 kohm', '1000', '1200', ('0.0030 + 0.0005', '0.0040 + 0.0005', '0.0050 + 0.0005'), False),
       ('10 kohm', '10000', '12000', ('0.0030 + 0.0005', '0.0040 + 0.0005', '0.0050 + 0.0005'), False),
       ('100 kohm', '100000', '120000', ('0.0030 + 0.0005', '0.0040 + 0.0005', '0.0050 + 0.0005'), False),
       ('1 Mohm', '1000000', '1200000', ('0.0060 + 0.0005', '0.0070 + 0.0005', '0.0080 + 0.0005'), False),
       ('10 Mohm', '10000000', '12000000', ('0.0200 + 0.0010', '0.0250 + 0.0010', '0.0300 + 0.0010'), False),
       ('100 Mohm', '100000000', '120000000', ('0.2000 + 0.0010', '0.3000 + 0.0010', '0.4000 + 0.0010'), False),
       ('1 Gohm', '1000000000', '1200000000', ('2.0000 + 0.0010', '3.0000 + 0.0010', '4.0000 + 0.0010'), False)]
# ---- DC current, p. 15 (1 uA, 10 uA, 100 uA are "(typ)")
DCI = [('1 uA', '1e-6', '1.2e-6', ('0.0300 + 0.0050', '0.0500 + 0.0050', '0.0600 + 0.0050'), True),
       ('10 uA', '1e-5', '1.2e-5', ('0.0300 + 0.0020', '0.0500 + 0.0020', '0.0600 + 0.0020'), True),
       ('100 uA', '1e-4', '1.2e-4', ('0.0300 + 0.0010', '0.0500 + 0.0010', '0.0600 + 0.0010'), True),
       ('1 mA', '1e-3', '1.2e-3', ('0.0300 + 0.0050', '0.0500 + 0.0050', '0.0600 + 0.0050'), False),
       ('10 mA', '1e-2', '1.2e-2', ('0.0300 + 0.0200', '0.0500 + 0.0200', '0.0600 + 0.0200'), False),
       ('100 mA', '1e-1', '1.2e-1', ('0.0300 + 0.0050', '0.0500 + 0.0050', '0.0600 + 0.0050'), False),
       ('1 A', '1', '1.2', ('0.0700 + 0.0100', '0.0800 + 0.0100', '0.1000 + 0.0100'), False),
       ('3 A', '3', '3', ('0.2000 + 0.0200', '0.2000 + 0.0200', '0.2300 + 0.0200'), False),
       ('10 A', '10', '10', ('0.1200 + 0.0100', '0.1200 + 0.0100', '0.1500 + 0.0100'), False)]
# ---- capacitance, p. 16 (the same figure in all three columns)
CAP = [('1 nF', '1e-9', '1.2e-9', ('0.50 + 0.50',) * 3, False)] + [
    (n, v, fs, ('0.40 + 0.10',) * 3, False) for n, v, fs in
    (('10 nF', '1e-8', '1.2e-8'), ('100 nF', '1e-7', '1.2e-7'), ('1 uF', '1e-6', '1.2e-6'), ('10 uF', '1e-5', '1.2e-5'), ('100 uF', '1e-4', '1.2e-4'))]
# ---- AC voltage, p. 16: ranges 100 mV, 1 V, 10 V, 100 V, 750 V (one table)
ACV_RANGES = [('100 mV', '0.1', '0.12'), ('1 V', '1', '1.2'), ('10 V', '10', '12'), ('100 V', '100', '120'), ('750 V', '750', '750')]
ACV_BANDS = [(3, 5, '', ('0.50 + 0.02',) * 3, False),
             (5, 10, '', ('0.10 + 0.02', '0.10 + 0.02', '0.11 + 0.02'), False),
             (10, 20e3, '', ('0.04 + 0.02', '0.05 + 0.02', '0.06 + 0.02'), False),
             (20e3, 50e3, '', ('0.06 + 0.03', '0.07 + 0.03', '0.08 + 0.03'), False),
             (50e3, 100e3, '', ('0.15 + 0.05',) * 3, False),
             (100e3, 300e3, '', ('1.00 + 0.10',) * 3, False)]
# ---- AC current, p. 16: 100 uA - 1 A (one table), 3 A, 10 A.  3 Hz to 5 kHz; 5 kHz to 10 kHz typical.  cells (90 day, 1 yr, 2 yr) per band
ACI_GROUPS = [([('100 uA', '1e-4', '1.2e-4'), ('1 mA', '1e-3', '1.2e-3'), ('10 mA', '1e-2', '1.2e-2'), ('100 mA', '1e-1', '1.2e-1'), ('1 A', '1', '1.2')],
               ('0.09 + 0.04', '0.10 + 0.04', '0.10 + 0.04'), ('0.10 + 0.04',) * 3),
              ([('3 A', '3', '3')], ('0.23 + 0.04',) * 3, ('0.23 + 0.04',) * 3),
              ([('10 A', '10', '10')], ('0.15 + 0.04',) * 3, ('0.15 + 0.04',) * 3)]
# ---- frequency, p. 16, % of reading (90 day, 1 yr, 2 yr); 100 mV - 750 V ranges
FREQ = [(3, 10, '3 Hz to 10 Hz', ('0.070', '0.070', '0.070')),
        (10, 100, '10 Hz to 100 Hz', ('0.030', '0.030', '0.030')),
        (100, 1e3, '100 Hz to 1 kHz', ('0.006', '0.007', '0.010')),
        (1e3, 300e3, '1 kHz to 300 kHz', ('0.005', '0.007', '0.009'))]
FREQ_SQ = [(10, 300e3, 'Square wave 10 Hz to 300 kHz', ('0.004', '0.006', '0.008'))]


def functions():
    f = []
    f.append(eng.dc_function('Voltage, DC', 'DCV', 'V', 15, DCV, lambda r, t: [6, 9] + ([10] if r == '1000 V' else []), 'V'))
    f.append(eng.ohm_variant('Resistance [4-wire (or 2-wire with math null)]', 15, OHM, lambda r, t: [6, 11] + ([12] if r in ('100 Mohm', '1 Gohm') else [])))
    f.append(eng.ohm_variant('Resistance [2-wire, no math null]', 15, OHM, lambda r, t: [6, 11], extra_abs='0.2', skip=('100 Mohm', '1 Gohm')))
    f.append(eng.dc_function('Current, DC', 'DCI', 'A', 15, DCI, lambda r, t: [6, 13] + ([14] if t else []) + ([15] if r == '10 A' else []), 'A'))
    f.append(eng.ac_function('Voltage, AC', 'ACV', 'V', 16, ACV_RANGES, ACV_BANDS, [6, 16], 'V'))
    cur = dict(name='Current, AC', direction='input', page=16, ranges=[])
    for rngs, c1, c2 in ACI_GROUPS:
        bands = [(3, 5e3, '', c1, False), (5e3, 10e3, 'typical', c2, True)]
        cur['ranges'].extend(eng.ac_function('Current, AC', 'ACI', 'A', 16, rngs, bands, [6, 17] + ([15] if rngs[0][0] == '10 A' else []), 'A')['ranges'])
    f.append(cur)
    f.append(eng.dc_function('Capacitance', 'CAP', 'F', 16, CAP, lambda r, t: [6, 18], 'F'))
    f.append(eng.freq_function('Frequency', 16, FREQ, [19]))
    f.append(eng.freq_function('Frequency [Square wave]', 16, FREQ_SQ, [19, 20]))
    return f


NOTES = eng.common_notes(
    MODEL, 'pp. 15-17 (DC voltage, resistance, DC current, continuity, diode, DC:DC ratio, temperature: p. 15; true RMS AC voltage, true RMS AC current, capacitance, frequency, burden voltages: p. 16; footnotes: p. 17)',
    ': DC voltage and resistance (the first table of p. 15) are printed at TACAL +/- 2 degC (24 hour: +/- 1 degC), TACAL being the temperature of the last ACAL (footnote 1: ACAL run within the last 2 days); the DC current, AC and other functions are at TCAL +/- 5 degC. '
    'Footnote 1: specifications are for a 90-minute warm-up, integration setting of 10 or 100 NPLC, auto-zero on, AC slow filter.',
    'for the 34465A that is +/-(0.0030 % of reading + 0.0004 % of the 10 V range) on the 10 V range.')
NOTES.update({
    '9': 'DC VOLTS (p. 15): 100 mV to 1000 V. Temperature coefficient (information, not stored): footnote 6 (non ACAL): add per degC outside the last TACAL +/- 2 degC: 100 mV 0.0005 + 0.0005, 1 V - 1000 V 0.0005 + 0.0001; footnote 7 (with ACAL): add per degC outside TACAL +/- 2 degC: '
         '100 mV 0.0002 + 0.0005, 1 V - 1000 V 0.0002 + 0.0001 (% of reading + % of range). The 1000 V range has no 20 % over range.',
    '10': 'DC VOLTS 1000 V (footnote 9): for each additional volt over +/-500 V add 0.02 mV of error. NOT in the stored 1000 V row.',
    '11': 'RESISTANCE (p. 15, footnote 8): the specifications are for the 4-WIRE ohms function, or the 2-wire ohms function using math null for offset. WITHOUT math null add 0.2 ohm in the 2-wire ohms function: stored as the separate function '
          '"Resistance [2-wire, no math null]" with a fixed 0.2 ohm term (a plain lookup prefers the 4-wire function; pass variant="2-wire"). Footnote 8 also: the 100 Mohm and 1 Gohm ranges are 2-wire ohms function only, and "see the manual for low power ohms '
          'specification and measurement currents" (the low-power ohms figures are NOT in the data sheet and NOT stored). Temperature coefficients (not stored, non ACAL / with ACAL): 100 ohm 0.0006 + 0.0005 / 0.0002 + 0.0005, 1 k - 100 k 0.0006 + 0.0001 / 0.0002 + 0.0001, '
          '1 Mohm 0.0010 + 0.0002 / 0.0002 + 0.0002, 10 Mohm 0.0030 + 0.0004 / 0.0030 + 0.0004, 100 Mohm 0.1000 + 0.0001 / 0.0100 + 0.0001, 1 Gohm 1.0000 + 0.0001 / 0.1000 + 0.0001.',
    '12': 'RESISTANCE 100 Mohm and 1 Gohm (footnote 8): 2-wire function only; the no-math-null variant has NO row for them (the 0.2 ohm adder is not applicable to a range that exists only as 2-wire; the data sheet does not say): UNVERIFIED.',
    '13': 'DC CURRENT (p. 15): ranges 1 uA to 10 A; burden voltage at full scale (p. 16, information): 1 uA < 0.0011 V, 10 uA < 0.011 V, 100 uA < 0.11 V, 1 mA < 0.11 V, 10 mA < 0.027 V, 100 mA < 0.27 V, 1 A < 0.7 V / 0.05 V, 3 A < 2.0 V / 0.15 V '
          '(the second value is obtained on the 10 A input, footnote 21), 10 A < 0.5 V. Temperature coefficients (not stored): 1 uA 0.0020 + 0.0010, 10 uA 0.0015 + 0.0006, 100 uA 0.0015 + 0.0004, 1 mA 0.0015 + 0.0005, 10 mA 0.0020 + 0.0020, 100 mA 0.0020 + 0.0005, '
          '1 A 0.0050 + 0.0010, 3 A 0.0050 + 0.0020, 10 A 0.0050 + 0.0010. The printed 1 mA 24 hour cell reads "0.0070+ 0.0030" (spacing misprint, not stored).',
    '14': 'DC CURRENT TYPICAL: the 1 uA, 10 uA and 100 uA rows are printed "(typ)" - typical, not warranted; the labels say so.',
    '15': 'CURRENT 10 A range (footnote 4): only available on a separate front panel connector. Add 2 mA base per amp for inputs greater than 5 Arms. NOT in the stored 10 A rows (DC and AC). The 3 A and 10 A ranges have no 20 % over range (footnote 2).',
    '16': 'TRUE RMS AC VOLTAGE (p. 16): 100 mV, 1 V, 10 V, 100 V and 750 V ranges share one table; footnote 14: sine wave input > 0.3 % of range and > 1 mVrms; 750 V range limited to 8 x 10^7 V.Hz; for each additional volt over 300 Vrms add 1 mVrms of error '
          '(NOT stored); footnote 15: slow filter (3 Hz, 20 Hz, 200 Hz) low-frequency performance. Temperature coefficients (not stored, add per degC outside TCAL +/- 5 degC, footnote 5): 3-5 Hz 0.010 + 0.003, 5-10 Hz 0.008 + 0.003, 10 Hz-20 kHz 0.007 + 0.003, '
          '20-50 kHz 0.010 + 0.005, 50-100 kHz 0.060 + 0.008, 100-300 kHz 0.200 + 0.020. A band edge belongs to both bands; the larger limit is used there (repository rule). The 750 V range has no 20 % over range.',
    '17': 'TRUE RMS AC CURRENT (p. 16, footnotes 16, 17): sine wave input > 1 % of range and > 10 uArms; specifications are for sine wave input unless stated otherwise. The 5 kHz to 10 kHz band is TYPICAL on every range (labels say so). 100 uA, 1 mA, 10 mA, 100 mA and 1 A share one table; '
          '3 A and 10 A have their own. Temperature coefficients (not stored): 0.015 + 0.006 (3 Hz-5 kHz), 0.030 + 0.006 (5-10 kHz). The 24 hour and 90 day cells of the 100 uA - 1 A group differ (0.07 / 0.09) from the 1 year / 2 year cells (0.10): stored as printed.',
    '18': 'CAPACITANCE (p. 16): 1 nF to 100 uF, % of reading + % of range, the same figure in the 90 day, 1 year and 2 year columns (temperature coefficients 0.05 + 0.05 for 1 nF, 0.05 + 0.01 for the rest; not stored). Footnote 20: for using Math Null zeroing; high dissipation factor '
          'capacitors may show different results than a single frequency measurement; film capacitors usually have lower dissipation factors. The printed superscript on the Capacitance heading is 21 (footnote 21 is about burden voltage): the data sheet\'s footnote numbering is shifted here; '
          'footnote 20 is read as the capacitance one (UNVERIFIED). Rows are stored as bipolar value ranges like every sheet.',
    '19': 'FREQUENCY (p. 16): % of reading, 100 mV, 1 V, 10 V, 100 V and 750 V ranges; footnote 19 (printed superscript 18, 20): input > 100 mV; for 10 mV to 100 mV inputs multiply the % of reading error by 10; amplitude 10 % - 120 % of range except 14 % - 100 % for 750 ACV; 1 second gate time (7 digits). '
          'Stored by frequency band only. Temperature coefficient: 0.0002 (% of reading per degC) for every band (not stored). The footnote numbering of this section is shifted in the data sheet (see note 18): UNVERIFIED which footnote belongs to which heading.',
    '20': 'FREQUENCY square wave (footnote 18): square wave input specified for 10 Hz to 300 kHz for a 1 second aperture; for shorter apertures the minimum frequency requires > 2 cycles. Stored as the separate function "Frequency [Square wave]" (variant="square"). '
          'Additional frequency errors (% of reading, NOT stored; by aperture 1 s (0.1 ppm) / 0.1 s (1 ppm) / 0.01 s (10 ppm) / 0.001 s (100 ppm)): 3-40 Hz 0 / 0.100 / 0.160 / 0.160; 40-100 Hz 0 / 0.030 / 0.160 / 0.160; 100 Hz-1 kHz 0 / 0.020 / 0.200 / 0.200; 1 kHz-300 kHz 0 / 0.004 / 0.030 / 0.240; square wave 0 / 0 / 0 / 0.003.',
    '21': 'NOT STORED: 24 hour column; continuity (1 kohm) and diode test (5 V) rows; DC:DC ratio (typical: normalized input accuracy + normalized reference accuracy); digitizing (typical SFDR / SNDR / bandwidth, p. 17); '
          'temperature (p. 15, footnote 12 "limited by the selected probe"): PT100 "Probe accuracy + 0.05 degC", thermistor "Probe accuracy + 0.1 degC", K, J, T, E, N thermocouples "Probe accuracy + reference junction accuracy + 0.3 degC", '
          'R thermocouple (250 to 1760 degC) "+ 0.5 degC". They need the probe\'s own (and the reference junction\'s, typically +/- 1.0 degC with the U1180A, footnote 13) accuracy, so no number can be stored for the DMM alone. '
          'The footnote superscripts 13 / 14 / 23 on the PT100, R thermocouple and thermistor lines do not match the footnote texts well; not used.',
})
LIMITS = [
    dict(function='Voltage, DC', limit='100 mV to 1000 V: % of reading + % of range (90 day / 1 yr / 2 yr; TACAL +/- 2 degC).', page='15'),
    dict(function='Resistance', limit='100 ohm to 1 Gohm; 4-wire (or 2-wire with math null); 100 Mohm and 1 Gohm 2-wire only; 2-wire without math null adds 0.2 ohm.', page='15'),
    dict(function='Current, DC', limit='1 uA to 10 A; 1 uA, 10 uA, 100 uA typical.', page='15'),
    dict(function='Voltage, AC', limit='True RMS, 100 mV to 750 V, 3 Hz to 300 kHz, six bands.', page='16'),
    dict(function='Current, AC', limit='True RMS, 100 uA to 10 A, 3 Hz to 5 kHz; 5 kHz to 10 kHz typical.', page='16'),
    dict(function='Capacitance', limit='1 nF to 100 uF.', page='16'),
    dict(function='Frequency', limit='% of reading, 3 Hz to 300 kHz (sine) and 10 Hz to 300 kHz (square wave), 1 s aperture.', page='16'),
]
PROBLEMS = [
    dict(level='warn', where='standard', what='CONFIDENCE LEVEL: the data sheet prints k = 2 ("compliant to ISO/IEC 17025 for k = 2"), not a percentage; 95 % (divisor 2) is the repository inference from k = 2.'),
    dict(level='warn', where='standard', what='The "% of range" term is taken against the range NAME (0.1 V on the 100 mV range ...); the data sheet does not define "range". UNVERIFIED.'),
    dict(level='warn', where='standard', what='No resolution is recorded on any row: the budget has no resolution term for this standard.'),
    dict(level='warn', where='Voltage, DC / Resistance', what='DC voltage and resistance figures assume ACAL run within the last 2 days (footnote 1) and TACAL +/- 2 degC; the lab must run ACAL (or the temperature coefficient applies).'),
    dict(level='warn', where='Resistance [2-wire, no math null]', what='No rows for the 100 Mohm and 1 Gohm ranges (2-wire only); the low-power ohms specification is not in the data sheet ("see the manual").'),
    dict(level='warn', where='Voltage, DC / 1000 V', what='Footnote 9: add 0.02 mV per additional volt above +/-500 V; not in the stored row.'),
    dict(level='warn', where='Current, DC / 1 uA, 10 uA, 100 uA', what='Typical, not warranted ("(typ)").'),
    dict(level='warn', where='Current, DC / Current, AC / 10 A', what='Footnote 4: add 2 mA base per amp for inputs greater than 5 Arms; not in the stored 10 A rows.'),
    dict(level='warn', where='Current, AC (5 kHz to 10 kHz)', what='Typical, not warranted ("(typ)").'),
    dict(level='warn', where='Capacitance / Frequency footnotes', what='The footnote superscripts of the capacitance and frequency headings (21; 18, 20) do not match the footnote texts (20; 18, 19): the data sheet numbering is shifted; the reading in notes 18-19 is UNVERIFIED.'),
    dict(level='warn', where='Temperature', what='PT100 / thermistor / thermocouple accuracy is "probe accuracy (+ reference junction) + 0.05 ... 0.5 degC": not stored (needs the probe accuracy). Continuity, diode test and DC:DC ratio are not stored either.'),
    dict(level='warn', where='Frequency', what='Stored by frequency band only; the amplitude conditions and the additional frequency errors by aperture are notes only.'),
]
CFG = dict(model=MODEL, description='6 1/2 digit Truevolt digital multimeter, ACAL capable (Keysight data sheet 5991-1983EN)', json='keysight_34465a_standard.json', builder='build_34465a_standard.py',
           reference='Keysight Digital Multimeters 34460A/34461A/34465A/34470A data sheet 5991-1983EN, published June 10, 2026, "Specifications 34465A" printed pp. 15-17',
           functions=functions, notes=NOTES, limits=LIMITS, problems=PROBLEMS, verified=VERIFIED_AGAINST_IMAGE)


def build():
    return eng.build(CFG)


if __name__ == '__main__':
    eng.main(CFG)
