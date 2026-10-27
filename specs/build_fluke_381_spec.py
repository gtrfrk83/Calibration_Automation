"""Builds specs/fluke_381_pv.json for the shared handheld engine (handheld_dmm.py / iflex_option.py) from the Fluke 381 Remote Display True-rms Clamp Meter
Calibration Manual (Rev. 1, 06/2012, 28 PDF pages; printed page = PDF page - 8).

    python3 specs/build_fluke_381_spec.py

Source:
  Table 3 "Performance Tests", printed pp. 11-12 (PDF 19-20): AC volts 7, DC volts 6, ohms 10, AC amps (50-turn coil) 6, DC amps (50-turn coil) 10, frequency (50-turn coil) 1 = 40 rows;
  Table 4 "iFlex Performance Tests", printed p. 14 (PDF 22): iFlex AC amps 6 (4 through the 50-turn coil, 2 simulated with a voltage), iFlex frequency 1 = 7 rows;
  Table 2 "Required Equipment" (printed p. 8): calibrator with 4.5 digit resolution (Fluke 552xA), wired coil 50 turns (5500A/COIL), 2 mm to 4 mm slim reach probe TP2 (PN 650892), test lead 6358 (PN 1903307);
  Figures 3 to 7 (printed pp. 8-10, 13, 14), the iFlex paragraph (printed p. 13), Table 3 footnote [1] (0 A dc), Table 4 footnotes [1] / [2], Figure 1 (the meter, printed p. 5);
  Specifications (printed pp. 5-7), used for the cross-check below.
Every nominal, frequency and limit was read from RENDERED PAGE IMAGES (pdftoppm at 150, 200 and 220 dpi), twice, never from extracted text; tests/test_fluke_381_points.py holds the second transcription.
The meter has NO remote interface (the 2.4 GHz link only feeds its own remote display): the operator types the display reading, as for the 323 / 376.

ONE MODEL (381): 47 points, 42 without the 5 iFlex-with-coil points (the iFlex window option of iflex_option.py, as the 376; the 2 iFlex simulation points always run).

Calibrator (the manual says 'Fluke 552xA'; the suite drives a 5522A, 5520A or 5560A, or you set it by hand):
  * AC / DC volts, ohms: NORMAL HI / LO (5522A / 5520A) or OUTPUT V/Ω HI / LO (5560A) on test leads in VΩ and COM (Figure 5), group VOHM;
  * AC / DC amps, frequency and iFlex-with-coil: the calibrator CURRENT output through the 50-turn coil (5500A/COIL): below 3 A on the low-current terminals (5522A AUX HI / AUX LO, 5560A VI AUX / OUTPUT LO),
    3 A and above on the high-current ones (5522A 20 A, 5560A 30A) (groups COIL_AUX / COIL_20A, IFLEX_COIL_AUX / IFLEX_COIL_20A);
  * 0 A dc (Table 3 footnote [1]): NOT the coil - a single wire from AUX HI to AUX LO with the meter clamped around it (group WIRE_0A);
  * iFlex simulation (Table 4 footnote [2], Figure 7): the calibrator VAC output (75 mV at 50 Hz, 750 mV at 500 Hz; the simulated Rogowski voltage is proportional to frequency) into the iFlex input (group IFLEX_SIM).

Limits interval: the Calibration Manual prints ONE set of limits per point (no 90-day / 1-year columns); they are used as printed.

Cross-check against the PUBLISHED specifications in the same manual (printed pp. 5-7, Electrical Specifications), as the 376 builder does for its Users Manual:
  AC volts 600 V / 1000 V, 0.1 V / 1 V, 1.5 % + 5 digits (20-500 Hz); DC volts 600.0 V / 1000 V, 0.1 V / 1 V, 1 % + 5; resistance 600 / 6 k / 60 kΩ, 0.1 / 1 / 10 Ω, 1 % + 5;
  AC current via jaw 999.9 A, 0.1 A, 2 % + 5 (10-100 Hz), 5 % + 5 (100-500 Hz); DC current 999.9 A, 0.1 A, 2 % + 5; AC current via iFlex 999.9 A / 2500 A, 0.1 A / 1 A, 3 % + 5 (45-500 Hz);
  frequency via jaw and via iFlex 5.0-500.0 Hz, 0.1 Hz, 0.5 % + 5 digits.
  Every printed limit is the full published accuracy to within half a display step, except the 'rounded' rows (EXPECTED_FLAGS: the specification value rounded up on one side: AC 10 V 9.4 / 10.7 against
  9.35 / 10.65; frequency 49.3 / 50.8 against 49.25 / 50.75; iFlex 995 A 964.6 / 1025.4 against 964.65 / 1025.35).  NOTHING is changed: limits are stored as printed, flagged in the point note.
  A mismatch of any other kind aborts the build (re-read the table).
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_381_pv.json'
DOCUMENT = 'Fluke 381 Remote Display True-rms Clamp Meter - Calibration Manual (Rev. 1, 06/2012)'
MODEL = '381'
TURNS = 50
INCLUDE_IFLEX = dict(id='iflex', label='iFlex probe supplied: run the iFlex tests', default=True, count_text='iFlex-with-coil point',
                     off_text='not tested (no iFlex supplied); the iFlex simulation points are still tested', on_text='tested (iFlex supplied)')

UNITS = {'V': ('1', 'V'), 'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'A': ('1', 'A'), 'Hz': ('1', 'Hz')}

# Rotary switch (Figure 1, printed p. 5, read from the rendered page): OFF, V~, V⎓, Ω with the continuity symbol, A~ (Hz in yellow), A⎓, iFlex A~ (Hz in yellow); a yellow ZERO button.
SW = {
    'acv': 'V~  (AC volts)',
    'dcv': 'V⎓  (DC volts)',
    'ohm': 'Ω  (ohms: the Ω position, shared with continuity; the display must show Ω)',
    'aca': 'A~  (AC amps: jaw closed around the 50-turn coil)',
    'dca': 'A⎓  (DC amps: jaw closed around the 50-turn coil, or around the single wire for the 0 A point)',
    'hz': 'Hz  (frequency: dial on A~, Hz selected; jaw closed around the 50-turn coil; how Hz is selected is not described in the Calibration Manual: UNVERIFIED)',
    'iflex': 'iFlex A~  (dial on iFlex A~; the iFlex probe plugged in, or the simulation leads)',
    'iflexhz': 'iFlex Hz  (frequency: dial on iFlex A~, Hz selected; the iFlex loop around the 50-turn coil; how Hz is selected is not described in the Calibration Manual: UNVERIFIED)',
}

# published accuracy (percent of reading, digits), manual printed pp. 5-7 (page in ACC_PAGE)
ACC = {'ACV': ('1.5', 5), 'DCV': ('1', 5), 'OHM': ('1', 5), 'ACA50': ('2', 5), 'ACA440': ('5', 5), 'DCA': ('2', 5), 'IFLEX': ('3', 5), 'HZ': ('0.5', 5)}
ACC_PAGE = {'ACV': 'p. 6', 'DCV': 'p. 6', 'OHM': 'p. 7', 'ACA50': 'p. 5', 'ACA440': 'p. 5', 'DCA': 'p. 6', 'IFLEX': 'p. 5', 'HZ': 'pp. 6-7'}
UM = 'Calibration Manual Specifications'

NOTE_RANGE = ('Tables 3 / 4 name no range: the range shown is the one the published resolutions put this reading in (Specifications, printed pp. 5-7; the meter autoranges).')
NOTE_OHMS = 'Table 3 does not say whether the limits include test lead resistance (UNVERIFIED); use short leads.'
NOTE_COIL = ('The calibrator drives the {turns}-turn coil and the meter reads {turns} x the calibrator current: {applied} A in, {nominal} A on the meter. The limits are the meter readings (Table {table}, printed p. {page}). '
             'Uncertainty (owner decision): the 5500A/COIL\'s own scope uncertainty (A2LA-5500A-COIL) at the effective current the jaw sees ({nominal} A), not the calibrator\'s at {applied} A; '
             'where the coil\'s lines do not cover the point (AC below 20.5 A) the calibrator\'s uncertainty at the sourced current x 50 is used. TAR / TUR compare it with the meter-reading tolerance printed in Table {table}.')
NOTE_IFLEX_SIM = ('iFlex simulation (Table 4 footnote [2], Figure 7, printed p. 14): calibrator VAC output HI to the iFlex 2 mm jack (far left; the small far-left jack is the iFlex input, owner-confirmed), LO to the black COM jack; the calibrator drives {applied} mV AC at {freq} Hz and the meter '
                  'reads {nominal} A (the simulated coil voltage is proportional to frequency: 30 uV per A at 50 Hz, 300 uV per A at 500 Hz). Uncertainty (the 376 convention): the regular calibrator AC VOLTS uncertainty at the output as printed; '
                  'TAR / TUR stay blank (the tolerance is in amps, the uncertainty in volts).')
NOTE_IFLEX_COIL = ('Table 4 footnote [1]: the iFlex loop from the 381 is placed around the {turns}-turn coil and the calibrator AAC output drives the coil ({applied} A in, {nominal} {unit} on the meter; Figure 6, printed p. 13). '
                   'Uncertainty: A2LA-5500A-COIL at the effective current where it covers the point (AC 20.5 A and above), else the calibrator at the sourced current x 50.')
NOTE_IFLEX_RANGE = 'iFlex range 999.9 A / 2500 A: 0.1 A resolution up to 999.9 A, 1 A above (Specifications, printed p. 5).'
NOTE_ZERO = ('The 381 has a yellow ZERO button (Figure 1); the Calibration Manual does not describe its use. Whether the DC amps function must be zeroed (jaw clear of any conductor, before the calibrator drives current) '
             'before the DC amps points is UNVERIFIED: zero it first if the meter requires it.')
NOTE_POLARITY = ('DC polarity: Figure 4 (printed p. 9) is captioned "Polarity is Reversed" and shows the calibrator RED lead in the coil\'s BLACK terminal and the BLACK lead in the coil\'s RED terminal (the display shows +600.8 A DC for +12 A). '
                 'Use that connection: a positive calibrator current must read positive and a negative one negative (the typed sign is judged). The orientation of the coil in the jaw is not described: UNVERIFIED.')
NOTE_WIRE = ('Table 3 footnote [1]: the 0 A dc test is performed with a SINGLE WIRE connected from the calibrator AUX HI to AUX LO (no coil) and the 381 clamped around the wire (Figure 3, printed p. 8). '
             'The calibrator outputs 0 A dc; the point checks the meter zero. UNVERIFIED: whether the output must be in OPERATE with 0 A (the program programs 0 A dc and operates it, as for every point). '
             'NO UNCERTAINTY is printed for this point (owner decision, 2026-10-26: a zero point, the calibrator floor is not a meaningful uncertainty for the meter zero; the step carries no_uncertainty).')
NOTE_FREQ = ('The calibrator drives {applied} A at 50 Hz through the {turns}-turn coil ({nominal} A in the {tool}) and the meter shows the FREQUENCY. The test current is exactly the trigger level in the Specifications '
             '({trig}); a marginal trigger may need the point repeated (UNVERIFIED). Uncertainty (owner decision, 2026-10-26, all handheld meters): the frequency is the calibrator\'s own OUTPUT frequency, so the uncertainty is the calibrator\'s published frequency specification '
             '(5522A / 5520A sheet or 5560A sheet, uncertainty_budget FREQ), not the lab Frequency - Measure CMC alone.')
NOTE_HIV = ('The 600 V point sits at the top of the 600.0 V range (full scale 600.0 V): which range the meter uses for 600 V (0.1 V or 1 V resolution) is UNVERIFIED; the limits are shown as printed (one decimal).')
NOTE_6K = ('6000 ohm is the full scale of the 6 kΩ range: whether the meter stays on that range (1 Ω resolution, as the printed limits imply) or changes to 60 kΩ (10 Ω) is UNVERIFIED.')
NOTE_DUTY = ('Coil duty (5500A/COIL technical data): 11 A rms continuous, 20 A rms for 2 minutes (above 11 A: 2 minutes ON, 8 minutes OFF); {applied} A is above 11 A: keep the output ON only as long as the reading needs and let the coil rest 8 minutes '
             'before the next high-current point (UNVERIFIED for this coil).')
NOTE_500 = ('500 Hz: the 5500A/COIL data sheet gives its frequency of operation as DC and 45-440 Hz; 500 Hz is outside it (the table asks for it; the coil\'s response at 500 Hz is UNVERIFIED). '
            'LCOMP is not set at 500 Hz (the 5522A allows it below 440 Hz under 0.33 A).')
NOTE_440 = '440 Hz: LCOMP is not set (the 5522A allows it below 440 Hz under 0.33 A; 5522A Operators Manual p. 6-23) and the point is flagged in the log.'

# (table, section, switch, range, kind, applied (calibrator output, base units), frequency, display unit, nominal (display unit), printed low, printed high, accuracy key, resolution, extras)
ROWS = [
    ('3', 'AC volts', 'acv', '600.0 V', 'ACV', '20', 20, 'V', '20', '19.2', '20.8', 'ACV', '0.1', {}),
    ('3', 'AC volts', 'acv', '600.0 V', 'ACV', '10', 50, 'V', '10', '9.4', '10.7', 'ACV', '0.1', {}),
    ('3', 'AC volts', 'acv', '600.0 V', 'ACV', '600', 50, 'V', '600', '590.5', '609.5', 'ACV', '0.1', {'hiv': True}),
    ('3', 'AC volts', 'acv', '1000 V', 'ACV', '1000', 50, 'V', '1000', '980', '1020', 'ACV', '1', {}),
    ('3', 'AC volts', 'acv', '600.0 V', 'ACV', '10', 500, 'V', '10', '9.4', '10.7', 'ACV', '0.1', {}),
    ('3', 'AC volts', 'acv', '600.0 V', 'ACV', '600', 500, 'V', '600', '590.5', '609.5', 'ACV', '0.1', {'hiv': True}),
    ('3', 'AC volts', 'acv', '1000 V', 'ACV', '1000', 500, 'V', '1000', '980', '1020', 'ACV', '1', {}),
    ('3', 'DC volts', 'dcv', '1000 V', 'DCV', '-1000', None, 'V', '-1000', '-1015', '-985', 'DCV', '1', {}),
    ('3', 'DC volts', 'dcv', '600.0 V', 'DCV', '-600', None, 'V', '-600', '-606.5', '-593.5', 'DCV', '0.1', {'hiv': True}),
    ('3', 'DC volts', 'dcv', '600.0 V', 'DCV', '-10', None, 'V', '-10', '-10.6', '-9.4', 'DCV', '0.1', {}),
    ('3', 'DC volts', 'dcv', '600.0 V', 'DCV', '10', None, 'V', '10', '9.4', '10.6', 'DCV', '0.1', {}),
    ('3', 'DC volts', 'dcv', '600.0 V', 'DCV', '600', None, 'V', '600', '593.5', '606.5', 'DCV', '0.1', {'hiv': True}),
    ('3', 'DC volts', 'dcv', '1000 V', 'DCV', '1000', None, 'V', '1000', '985', '1015', 'DCV', '1', {}),
    ('3', 'Ohms', 'ohm', '600.0 Ω', 'OHM', '0', None, 'Ω', '0', '-0.5', '0.5', 'OHM', '0.1', {}),
    ('3', 'Ohms', 'ohm', '600.0 Ω', 'OHM', '10', None, 'Ω', '10', '9.4', '10.6', 'OHM', '0.1', {}),
    ('3', 'Ohms', 'ohm', '600.0 Ω', 'OHM', '100', None, 'Ω', '100', '98.5', '101.5', 'OHM', '0.1', {}),
    ('3', 'Ohms', 'ohm', '600.0 Ω', 'OHM', '590', None, 'Ω', '590', '583.6', '596.4', 'OHM', '0.1', {}),
    ('3', 'Ohms', 'ohm', '6000 Ω', 'OHM', '1000', None, 'Ω', '1000', '985', '1015', 'OHM', '1', {}),
    ('3', 'Ohms', 'ohm', '6000 Ω', 'OHM', '3000', None, 'Ω', '3000', '2965', '3035', 'OHM', '1', {}),
    ('3', 'Ohms', 'ohm', '6000 Ω', 'OHM', '6000', None, 'Ω', '6000', '5935', '6065', 'OHM', '1', {'k6': True}),
    ('3', 'Ohms', 'ohm', '60.00 kΩ', 'OHM', '10000', None, 'kΩ', '10', '9.85', '10.15', 'OHM', '0.01', {}),
    ('3', 'Ohms', 'ohm', '60.00 kΩ', 'OHM', '30000', None, 'kΩ', '30', '29.65', '30.35', 'OHM', '0.01', {}),
    ('3', 'Ohms', 'ohm', '60.00 kΩ', 'OHM', '60000', None, 'kΩ', '60', '59.35', '60.65', 'OHM', '0.01', {}),
    ('3', 'AC amps', 'aca', '', 'ACI', '0.2', 50, 'A', '10', '9.3', '10.7', 'ACA50', '0.1', {'coil': True}),
    ('3', 'AC amps', 'aca', '', 'ACI', '2', 50, 'A', '100', '97.5', '102.5', 'ACA50', '0.1', {'coil': True}),
    ('3', 'AC amps', 'aca', '', 'ACI', '12', 50, 'A', '600', '587.5', '612.5', 'ACA50', '0.1', {'coil': True}),
    ('3', 'AC amps', 'aca', '', 'ACI', '18', 50, 'A', '900', '881.5', '918.5', 'ACA50', '0.1', {'coil': True}),
    ('3', 'AC amps', 'aca', '', 'ACI', '19.5', 50, 'A', '975', '955.0', '995.0', 'ACA50', '0.1', {'coil': True}),
    ('3', 'AC amps', 'aca', '', 'ACI', '0.2', 440, 'A', '10', '9.0', '11.0', 'ACA440', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '-19.5', None, 'A', '-975', '-995.0', '-955.0', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '-12', None, 'A', '-600', '-612.5', '-587.5', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '-2', None, 'A', '-100', '-102.5', '-97.5', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '-0.2', None, 'A', '-10', '-10.7', '-9.3', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '0', None, 'A', '0', '-0.5', '0.5', 'DCA', '0.1', {'wire': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '0.2', None, 'A', '10', '9.3', '10.7', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '2', None, 'A', '100', '97.5', '102.5', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '12', None, 'A', '600', '587.5', '612.5', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '18', None, 'A', '900', '881.5', '918.5', 'DCA', '0.1', {'coil': True}),
    ('3', 'DC amps', 'dca', '', 'DCI', '19.5', None, 'A', '975', '955.0', '995.0', 'DCA', '0.1', {'coil': True}),
    ('3', 'Frequency', 'hz', '', 'ACI', '0.1', 50, 'Hz', '50', '49.3', '50.8', 'HZ', '0.1', {'coil': True, 'freq_row': True, 'trig': 'jaw 10 to 100 Hz: 5 A or more'}),
    ('4', 'iFlex AC amps', 'iflex', '999.9 A', 'ACI', '0.2', 50, 'A', '10', '9.2', '10.8', 'IFLEX', '0.1', {'coil': True, 'iflex': True}),
    ('4', 'iFlex AC amps', 'iflex', '999.9 A', 'ACI', '12', 50, 'A', '600', '581.5', '618.5', 'IFLEX', '0.1', {'coil': True, 'iflex': True}),
    ('4', 'iFlex AC amps', 'iflex', '999.9 A', 'ACI', '19.9', 50, 'A', '995', '964.6', '1025.4', 'IFLEX', '0.1', {'coil': True, 'iflex': True}),
    ('4', 'iFlex AC amps', 'iflex', '2500 A', 'ACV', '0.075', 50, 'A', '2500', '2420', '2580', 'IFLEX', '1', {'sim': True}),
    ('4', 'iFlex AC amps', 'iflex', '999.9 A', 'ACI', '0.2', 500, 'A', '10', '9.2', '10.8', 'IFLEX', '0.1', {'coil': True, 'iflex': True}),
    ('4', 'iFlex AC amps', 'iflex', '2500 A', 'ACV', '0.75', 500, 'A', '2500', '2420', '2580', 'IFLEX', '1', {'sim': True}),
    ('4', 'iFlex frequency', 'iflexhz', '', 'ACI', '0.4', 50, 'Hz', '50', '49.3', '50.8', 'HZ', '0.1', {'coil': True, 'iflex': True, 'freq_row': True, 'trig': 'iFlex 20 to 100 Hz: 20 A or more'}),
]
EXPECTED_COUNT = 47
EXPECTED_TABLE_COUNTS = {'3': 40, '4': 7}
# rows the check classifies as 'rounded' (global step number in table order); every other row must be 'full' (or 'half'): anything else aborts
EXPECTED_FLAGS = {2: 'rounded', 5: 'rounded', 40: 'rounded', 43: 'rounded', 47: 'rounded'}


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def decimals(text: str) -> int:
    return max(0, -D(text).as_tuple().exponent)


def spec_halfwidth(nominal, acc, res):
    pct, digits = D(acc[0]), acc[1]
    return pct / 100 * abs(D(nominal)) + digits * D(res)


def check_row(nominal, low, high, acc, res):
    """(info, verdict) as the 376 builder: 'full', 'half', 'tighter', 'rounded' or 'looser' against the published accuracy; nothing is changed."""
    full = spec_halfwidth(nominal, acc, res)
    half = full / 2
    nominal, low, high, res = D(nominal), D(low), D(high), D(res)
    step = res / 2
    info, kinds = [], set()
    for name, got in (('low', nominal - low), ('high', high - nominal)):
        if got > full + step:
            kinds.add('looser')
        elif abs(got - full) <= step:
            kinds.add('rounded' if got > full else 'full')
        elif abs(got - half) <= step:
            kinds.add('half')
        else:
            kinds.add('tighter')
        if got > full or (abs(got - full) > step and abs(got - half) > step):
            info.append(dict(side=name, printed=fmt(got.normalize()), full_spec=fmt(full.normalize())))
    for v in ('looser', 'tighter', 'rounded', 'half', 'full'):
        if v in kinds:
            return info, v
    return info, 'full'


def group_for(extra, applied):
    if extra.get('sim'):
        return 'IFLEX_SIM'
    if extra.get('wire'):
        return 'WIRE_0A'
    if extra.get('coil'):
        low_current = abs(D(applied)) < 3
        if extra.get('iflex'):
            return 'IFLEX_COIL_AUX' if low_current else 'IFLEX_COIL_20A'
        return 'COIL_AUX' if low_current else 'COIL_20A'
    return 'VOHM'


def check_rows():
    problems = []
    for n, (table, section, sw, rng, kind, applied, freq, unit, nominal, low, high, acc_key, res, extra) in enumerate(ROWS, 1):
        nom, lo, hi = D(nominal), D(low), D(high)
        if not lo <= nom <= hi:
            problems.append(f'row {n}: nominal {nominal} not between {low} and {high}')
        if abs((nom - lo) - (hi - nom)) > D('0.0000001') and not extra.get('freq_row') and n not in EXPECTED_FLAGS:
            problems.append(f'row {n}: limits not symmetric about {nominal}: {low} .. {high}')
        if extra.get('coil') and not extra.get('freq_row') and D(applied) * TURNS != nom:
            problems.append(f'row {n}: {applied} A x {TURNS} turns is not {nominal} A')
        if extra.get('freq_row') and D(nominal) != D(freq):
            problems.append(f'row {n}: frequency nominal {nominal} Hz differs from {freq} Hz')
        if extra.get('sim') and D(applied) * 1000 * D(50) / D(freq) != D('75'):
            problems.append(f'row {n}: simulation voltage is not proportional to frequency (75 mV at 50 Hz)')
    if len(ROWS) != EXPECTED_COUNT:
        problems.append(f'{len(ROWS)} rows, Tables 3 and 4 have {EXPECTED_COUNT}')
    counts = {t: sum(1 for r in ROWS if r[0] == t) for t in EXPECTED_TABLE_COUNTS}
    if counts != EXPECTED_TABLE_COUNTS:
        problems.append(f'rows per table {counts} differ from {EXPECTED_TABLE_COUNTS}')
    return problems


def build_steps():
    steps, problems, flagged = [], [], []
    for n, (table, section, sw, rng, kind, applied, freq, unit, nominal, low, high, acc_key, res, extra) in enumerate(ROWS, 1):
        factor, base = UNITS[unit]
        info, verdict = check_row(nominal, low, high, ACC[acc_key], res)
        expected = EXPECTED_FLAGS.get(n)
        if (verdict if verdict in ('tighter', 'rounded', 'looser') else None) != expected:
            problems.append(f'step {n}: classified {verdict!r}, the builder expects {expected!r} (re-read the table)')
        tn = sum(1 for r in ROWS[:n] if r[0] == table)             # row number within its printed table (the 'ref')
        page = '11-12' if table == '3' else '14'
        step = dict(table=table, step=n, section=section, switch=SW[sw], range=rng, models=[MODEL], kind=kind)
        if extra.get('iflex'):
            step['include'] = 'iflex'
        step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=low, high=high, test='numeric',
                    applied=dict(value=clean(applied), frequency=float(freq) if freq else None), nominal=clean(D(nominal) * D(factor)))
        acc = ACC[acc_key]
        full = spec_halfwidth(nominal, acc, res)
        step['accuracy'] = f'±({acc[0]} % of reading + {acc[1]} digits)'
        step['tol_text'] = (f'Table {table}: {low} to {high} {unit}   ({UM} {ACC_PAGE[acc_key]}: ±({acc[0]} % of reading + {acc[1]} digits of {res} {unit}) = ±{fmt(full.normalize())} {unit})')
        notes = [NOTE_RANGE]
        a_txt = f'{D(applied).normalize():f}'
        n_txt = f'{D(nominal).normalize():f}'
        if extra.get('sim'):
            mv = D(applied) * 1000
            notes.append(NOTE_IFLEX_SIM.format(applied=f'{mv.normalize():f}', freq=freq, nominal=n_txt))
            notes.append(NOTE_IFLEX_RANGE)
            step['unc_unit'] = 'V'
            step['report_desc'] = f'{rng}, {mv.normalize():f} mV applied'
            step['dsb_desc'] = f'iFlex simulated, {rng} range: {mv.normalize():f} mV AC @ {freq} Hz, meter reads {n_txt} A'
            step['settle'] = 5
        elif extra.get('wire'):
            notes.append(NOTE_WIRE)
            step['report_desc'] = '0 A dc, single wire'
            step['no_uncertainty'] = True
            step['dsb_desc'] = 'DC amps, 0 A: single wire AUX HI to AUX LO, meter clamped around the wire'
            step['settle'] = 5
        elif extra.get('coil'):
            tool = 'iFlex loop' if extra.get('iflex') else 'jaw'
            if extra.get('freq_row'):
                notes.append(NOTE_FREQ.format(applied=a_txt, turns=TURNS, nominal=D(applied) * TURNS, tool=tool, trig=extra['trig']))
                step['unc_kind'] = 'FREQ'
                step['no_freq_suffix'] = True
                step['report_desc'] = f'{a_txt} A x {TURNS} turns, {freq} Hz'
                step['dsb_desc'] = f'Frequency, {tool} on the {TURNS}-turn coil: calibrator {a_txt} A @ {freq} Hz, meter reads {n_txt} Hz'
            else:
                notes.append((NOTE_IFLEX_COIL.format(turns=TURNS, applied=a_txt, nominal=n_txt, unit=unit) if extra.get('iflex')
                              else NOTE_COIL.format(turns=TURNS, applied=a_txt, nominal=n_txt, table=table, page=page)))
                if extra.get('iflex'):
                    notes.append(NOTE_IFLEX_RANGE)
                lead = 'iFlex' if extra.get('iflex') else 'Jaw'
                step['report_desc'] = f'{lead}, {a_txt} A x {TURNS} turns'
                head = f'iFlex loop on the {TURNS}-turn coil' if extra.get('iflex') else f'{section}, jaw on the {TURNS}-turn coil'
                step['dsb_desc'] = f'{head}: meter reads {n_txt} A' + (f' @ {freq} Hz' if freq else '')
                step['unc_standard'] = 'A2LA-5500A-COIL'
                step['unc_nominal'] = step['nominal']
            step['settle'] = 5
            if freq == 440:
                notes.append(NOTE_440)
            if freq == 500 and kind == 'ACI' and not extra.get('freq_row'):
                notes.append(NOTE_500)
            if abs(D(applied)) > 11:
                notes.append(NOTE_DUTY.format(applied=a_txt))
            if kind == 'DCI':
                notes.append(NOTE_POLARITY)
            if sw == 'dca' and applied == '-19.5':
                notes.append(NOTE_ZERO)
        if kind == 'OHM':
            notes.append(NOTE_OHMS)
        if extra.get('hiv'):
            notes.append(NOTE_HIV)
        if extra.get('k6'):
            notes.append(NOTE_6K)
        if verdict == 'rounded':
            what = '; '.join(f'{i["side"]} limit ±{i["printed"]} from the nominal vs the published ±{i["full_spec"]}' for i in info)
            step['check'] = dict(verdict='rounded', printed_vs_spec=info, full_spec=fmt(full.normalize()))
            notes.append(f'CHECK (printed limit not changed; {UM} {ACC_PAGE[acc_key]}): the printed limit is the specification value rounded to the display step ({what}).')
            flagged.append((f'{table}-{n}', verdict, section, applied, freq, nominal, low, high))
        step['group'] = group_for(extra, applied)
        step['note'] = ' '.join(notes)
        step['ref'] = f'T{table} #{tn}'
        step['id'] = f'{table}-{n}'          # the step number runs on across the two tables (the engine orders points by it); 'ref' is the printed row
        steps.append(step)
    return steps, problems, flagged


def common(tool):
    return [
        ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
        ('Test leads', f'REMOVE the test leads from the VΩ and COM jacks while current is measured with the {tool} ("Do not measure current while the test leads are in the input jacks", Safety Information, printed p. 2).'),
        ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
    ]


LCOMP_TEXT = ('Fluke 5522A / 5520A: the program turns inductive-load compensation (LCOMP) ON for every AC point through the coil (read back with LCOMP?) and OFF afterwards (5522A Operators Manual p. 6-23; on the 5520A '
              'the command is UNVERIFIED). Where the calibrator does not allow it (440 Hz and above below 0.33 A; 1 kHz and above from 0.33 A) it is not set and the log says so. 5560A: no LCOMP command for its own output - set it yourself if needed.')
POLARITY_TEXT = ('Polarity (Figure 4, printed p. 9, "Polarity is Reversed"): calibrator RED lead to the coil\'s BLACK terminal, calibrator BLACK lead to the coil\'s RED terminal, as drawn. '
                 'For DC points a positive calibrator current must read positive on the meter.')
GROUPS = {
    'COIL_AUX': dict(
        title='Change the cables: 50-turn coil on the calibrator low-current output',
        summary='Calibrator low-current output (5522A / 5520A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=common('jaw') + [
            ('Coil', 'The wired coil is 50 turns (Table 2, printed p. 8: 5500A/COIL). Connect its two ends to the calibrator low-current output: Fluke 5522A / 5520A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO (Figure 4). Use plugs rated for the current.'),
            ('Polarity', POLARITY_TEXT),
            ('Jaw', 'Close the jaw around the coil, fully closed, the coil centred in the opening, the coil leads kept away from the meter body. The meter then reads 50 x the calibrator current (0.2 A reads 10 A).'),
            ('LCOMP', LCOMP_TEXT),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads. Do not measure ac/dc current in circuits above 600 V or 200 A with the jaw (Safety Information, p. 3).',
        diagram='diagrams/hook_fluke381_COIL_AUX.png'),
    'COIL_20A': dict(
        title='Change the cables: 50-turn coil on the calibrator high-current output',
        summary='Calibrator high-current output (5522A / 5520A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=common('jaw') + [
            ('Coil', 'Move the two ends of the 50-turn coil to the calibrator high-current terminals: Fluke 5522A / 5520A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 19.5 A.'),
            ('Polarity', POLARITY_TEXT),
            ('Jaw', 'The jaw stays closed around the coil (centred, fully closed, leads away from the meter body). The meter reads 50 x the calibrator current: 12 A reads 600 A, 18 A reads 900 A, 19.5 A reads 975 A.'),
            ('LCOMP', 'Fluke 5522A / 5520A: AC points through the coil - the program turns LCOMP ON for each (and OFF afterwards), as for the low-current points.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 19.9 A flows in the coil. Duty (5500A/COIL data): 11 A rms continuous, 20 A rms for 2 minutes then 8 minutes OFF; not confirmed for this coil (UNVERIFIED). Keep the calibrator in STANDBY whenever you touch the coil or leads.',
        diagram='diagrams/hook_fluke381_COIL_20A.png'),
    'WIRE_0A': dict(
        title='Change the cables: single wire for the 0 A dc point (no coil)',
        summary='Calibrator AUX HI -> a single wire -> AUX LO (5522A / 5520A; 5560A VI AUX -> OUTPUT LO); the meter jaw closed around the wire.',
        steps=common('jaw') + [
            ('Wire', 'Table 3 footnote [1]: connect a SINGLE WIRE from the calibrator AUX HI to AUX LO (5560A: VI AUX to OUTPUT LO). Remove the 50-turn coil from the calibrator terminals for this point.'),
            ('Jaw', 'Clamp the meter jaw around the wire only (Figure 3, printed p. 8). The calibrator outputs 0 A dc: the meter should read 0.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='The calibrator output is 0 A, but the wire is a closed current loop on the calibrator terminals: keep the output in STANDBY while you connect the wire and keep clear of the terminals.',
        diagram='diagrams/hook_fluke381_WIRE_0A.png'),
    'IFLEX_SIM': dict(
        title='Change the cables: iFlex simulation (calibrator voltage output to the iFlex input)',
        summary='Calibrator NORMAL HI (5522A / 5520A) / OUTPUT V/Ω HI (5560A) -> iFlex 2 mm jack (far left); calibrator LO -> the black COM jack. Test lead with retractable sheath (6358, PN 1903307) and 2 mm to 4 mm Slim Reach probe (TP2, PN 650892).',
        steps=[
            ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
            ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
            ('Calibrator', 'Fluke 5522A / 5520A: NORMAL HI and NORMAL LO; Fluke 5560A: OUTPUT V/Ω HI and OUTPUT V/Ω LO (the voltage output, as for the volts points).'),
            ('iFlex input', 'Calibrator HI to the iFlex 2 mm jack on the far left of the meter, calibrator LO to the black COM jack (iFlex paragraph, printed p. 13; Figure 7, printed p. 14). Use the test probe for iFlex '
                            '(2 mm to 4 mm Slim Reach probe, TP2, PN 650892) and the test lead with retractable sheath (6358, PN 1903307). No iFlex loop is connected. The far-left small jack in Figure 1 (unlabelled in the manual) is the iFlex input (owner-confirmed).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='The output is only millivolts (75 and 750 mV). Keep the calibrator in STANDBY while you connect the leads.',
        diagram='diagrams/hook_fluke381_IFLEX_SIM.png'),
    'IFLEX_COIL_AUX': dict(
        title='Change the cables: iFlex loop on the 50-turn coil, calibrator low-current output',
        summary='Calibrator low-current output (5522A / 5520A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the iFlex loop around the coil, plugged into the meter. No test leads in the meter jacks.',
        steps=common('iFlex') + [
            ('Coil', 'Coil on the calibrator low-current output as for the jaw points: Fluke 5522A / 5520A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO.'),
            ('iFlex', 'Remove the jaw from the coil. Plug the iFlex probe into the meter and place its loop around the coil (Table 4 footnote [1], Figure 6, printed p. 13). The meter reads 50 x the calibrator current: 0.2 A reads 10 A. '
                      'The iFlex error is 0.5 % / 1.0 % / 2.0 % by the distance of the conductor from the optimum position (Figure 2, printed p. 6): centre the coil in the loop. How the loop sits on the 5500A/COIL is not described: UNVERIFIED.'),
            ('LCOMP', LCOMP_TEXT),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil, the loop or the leads. Do not apply the iFlex around or remove it from hazardous live conductors (Safety Information, p. 3).',
        diagram='diagrams/hook_fluke381_IFLEX_COIL_AUX.png'),
    'IFLEX_COIL_20A': dict(
        title='Change the cables: iFlex loop on the 50-turn coil, calibrator high-current output',
        summary='Calibrator high-current output (5522A / 5520A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the iFlex loop around the coil, plugged into the meter. No test leads in the meter jacks.',
        steps=common('iFlex') + [
            ('Coil', 'Move the two ends of the coil to the calibrator high-current terminals: Fluke 5522A / 5520A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 19.9 A.'),
            ('iFlex', 'The iFlex loop stays around the coil, the probe plugged into the meter. The meter reads 50 x the calibrator current: 12 A reads 600 A, 19.9 A reads 995 A.'),
            ('LCOMP', 'Fluke 5522A / 5520A: AC points through the coil - the program turns LCOMP ON for each (and OFF afterwards).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 19.9 A flows in the coil. Duty (5500A/COIL data): 11 A rms continuous, 20 A rms for 2 minutes then 8 minutes OFF; not confirmed for this coil (UNVERIFIED). Keep the calibrator in STANDBY whenever you touch the coil or leads.',
        diagram='diagrams/hook_fluke381_IFLEX_COIL_20A.png'),
}

SOURCE_NOTE = (
    'Table 3 (40 rows: AC volts 7, DC volts 6, ohms 10, AC amps 6, DC amps 10, frequency 1; printed pp. 11-12) and Table 4 (7 rows: iFlex AC amps 6, iFlex frequency 1; printed p. 14) of the 381 Calibration Manual. '
    'The tables have no step numbers: steps are numbered in table order and the number runs on across the two tables (3-1 .. 3-40, then 4-41 .. 4-47 for Table 4 rows 1 to 7; the ref T4 #n of a point is the printed row). Table 2 (printed p. 8) names a calibrator with 4.5 digit resolution (Fluke 552xA), the 5500A/COIL (50 turns), the TP2 probe and test lead 6358; '
    'the program drives a Fluke 5522A, 5520A or 5560A (or you set the calibrator by hand). The AC / DC amps, frequency and iFlex-with-coil rows are driven through the 50-turn coil (calibrator current x 50 = the reading; limits are meter readings), '
    'the 0 A dc point with a single wire AUX HI to AUX LO (footnote [1]), and the two iFlex simulation rows with the calibrator VAC output (footnote [2]). The meter has no remote interface: you type the display reading. '
    'The manual prints one set of limits (no interval columns); they are used as printed. Where a printed limit is not the full accuracy of the Specifications (printed pp. 5-7) the point says so (five rows are the specification value rounded to the display step). '
    'The iFlex-with-coil tests (5 points) can be switched off before the run when the meter has no iFlex (the window option; the 2 simulation points always run). '
    'High-voltage points go straight to the test value (the manual prescribes no ramp). The functional checks and the calibration ADJUSTMENT (Table 5, printed pp. 15-18) are not part of this procedure.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s Tables 3 and 4 (Fluke 381 Calibration Manual, printed pp. 11-12 and 14), unchanged. The current and frequency points are driven through a 50-turn coil (calibrator current x 50 = the reading shown), '
    'the 0 A dc point with a single wire, and the iFlex simulated points with a voltage on the iFlex input; the Uncertainty of a coil point is that of the 5500A/COIL scope lines at the effective current where they cover it, otherwise the calibrator\'s at the sourced current x 50.')


def build_spec():
    problems = check_rows()
    steps, more, flagged = build_steps()
    problems += more
    if problems:
        raise SystemExit('Problems:\n  ' + '\n  '.join(problems))
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='fluke381', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data', include_toggles=[INCLUDE_IFLEX]),
        source=dict(document=DOCUMENT,
                    pages='11-12 and 14 (printed): Table 3 pp. 11-12 (PDF pages 19-20), Table 4 p. 14 (PDF 22); equipment Table 2 p. 8; Figures 3-7 pp. 8-10, 13-14; Specifications pp. 5-7',
                    cite='Fluke 381 Calibration Manual, Table 3 Performance Tests and Table 4 iFlex Performance Tests, printed pp. 11-12 and 14; limits unchanged, rows flagged against the Specifications (printed pp. 5-7)',
                    limits='Manufacturer limits, Tables 3 and 4, as printed (one set, no interval columns)',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={MODEL: dict(name='Fluke 381', brand='Fluke', model_note='Fluke 381 remote display true-rms clamp meter (999.9 A jaw, 1000 V, 60 kohm, iFlex 2500 A): Tables 3 and 4, 47 points (42 without the iFlex-with-coil tests)')},
        groups=GROUPS,
        steps=steps), flagged


def main():
    spec, flagged = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT.name, len(spec['steps']), 'steps;', count)
    for f in flagged:
        print('  FLAG', f)


if __name__ == '__main__':
    main()
