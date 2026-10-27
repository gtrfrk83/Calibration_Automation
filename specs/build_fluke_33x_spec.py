"""Builds specs/fluke_33x_pv.json for the shared handheld engine (handheld_dmm.py / iflex_option.py) from the Fluke 33X ClampMeters Calibration Information
(PN 1618765, June 2001, Rev. 2, 12/03; 16 pages; printed page = PDF page).

    python3 specs/build_fluke_33x_spec.py

Source (read from RENDERED PAGE IMAGES, pdftoppm at 130, 200 and 260 dpi, each number twice, never from extracted text; tests/test_fluke_33x_points.py holds the second transcription):
  Table 2 "Performance Tests 333, 334, 335", printed p. 8: 14 rows;
  Table 2 "Performance Tests 336, 337 (cont.)", printed p. 9: 27 rows;
  "Performance Test Procedure" and Figure 4 "33x Amps/Hz Verification Setup" (printed p. 7), Table 1 "Required Equipment" (printed p. 5), "Preparing for the Performance Test" (printed p. 6),
  Figure 2 (the dial and buttons, 337 shown, printed p. 5), Safety Information (printed p. 2), Specifications (printed p. 3, used for the cross-check below).
The manual has NO X / N/A model columns: the models of a row come from the table it is printed in (p. 8: 333 334 335; p. 9: 336 337) and the model tags printed in the rows
('(333)', '(334, 335)', '(337 only)', '(337)'), plus the Specifications on p. 3 (inrush is NA on the 333; the 6 kOhm row is tagged '(334, 335)' on p. 8 because the 333 has a 600 ohm range only).
The meter has NO remote interface: the operator types the display reading, as for the 323 / 365 / 376 / 381.

ONE FAMILY SPEC, FIVE MODELS (as the 110 / 170 / 374-376 / 323 families): every step lists its models.
  333: 12 points   334: 16   335: 16   336: 23   337: 30   (Table 2: 11 / 13 / 13 / 20 / 27, plus the functional checks 1 / 3 / 3 / 3 / 3).   Registered: Procedures/Fluke_333_Verification.py ... Fluke_337_Verification.py.

THE 50-TURN COIL (Table 1: 'Fluke 5500A/Coil'; Figure 4; procedure step 4 'make sure LCOMP on the 5520A is ON'):
  * The column '5520A Output' of the amps rows lists the CURRENT THE CLAMP SEES (20 A, 200 A, 600 A, 900 A ...): 600 A and 900 A are not outputs any calibrator can make, and the limits are centred
    on those values.  The calibrator therefore drives value / 50 through the 50-turn coil (0.4 A, 4 A, 8 A, 12 A, 18 A): this is an INFERENCE (UNVERIFIED), the same ratio as every other clamp-meter procedure
    (calibrator current x 50 = meter reading).  The builder checks that every limit pair is centred on the effective current and aborts otherwise.
  * INRUSH rows: 5 A at 60 Hz in the jaw = 0.1 A through the coil; the note quotes the manual's footnotes (press INRUSH AFTER the current is applied; the display bars, then shows the reading with the inrush light on).
  * Frequency rows (337): '5 A 10 Hz' and '10 A 300 Hz' are the current in the jaw (Figure 4 is captioned 'Amps/Hz Verification Setup' and the Specifications give the Hz trigger level in amps: 10-100 Hz 5 A or more,
    100-400 Hz more than 10 A): 0.1 A at 10 Hz and 0.2 A at 300 Hz through the coil, the meter on its Hz position showing the FREQUENCY.  The 300 Hz row sits exactly on the printed trigger level ('> 10 A'): UNVERIFIED.
  * 0.0 A DC 'after button push': the calibrator outputs 0 A DC through the coil (jaw closed round the coil) and the operator presses the ZERO button (Figure 2) before the reading; how the ZERO button acts is UNVERIFIED.
    No uncertainty is printed for this point (owner decision of 2026-10-26 for the 381's 0 A dc point, applied here by the same reasoning: a zero point; step carries no_uncertainty): reported to the owner.
  * Hook-up groups: calibrator output below 3 A on the low-current terminals (COIL_AUX), 3 A and above on the 20 A / 30 A ones (COIL_20A): the split of the 323 / 376 / 381 specs.
  * Uncertainty (owner decision 2026-10-26): coil points carry the 5500A/COIL scope lines at the EFFECTIVE current where they cover it (AC 20.5 A and above, DC 2 A and above), else the calibrator's at the sourced
    current x 50 (coil_rule.py); the frequency rows the calibrator's own output-frequency specification (owner decision 2026-10-26).

Two points are not numeric limits: 'Continuity 25 ohm: Beeper On' (test 'beeper', as the 170 series) and Min/Max '20 V 400 Hz: Reading does not change' (test 'visual' with a calibrator output: a yes / no question).
The functional checks of the section (display test, backlight test, keypad test; printed pp. 5-6) have no limits: built as yes / no 'visual' points of table 'F' (owner decision 2026-10-27; display and backlight 334-337, keypad all five).  The calibration ADJUSTMENT (printed pp. 10-12) is not built.

CROSS-CHECK against the PUBLISHED specifications of the same manual (printed p. 3; resolutions are not printed, they are the display step of the printed limits: 0.1 V, 0.1 A, 0.1 ohm / 1 ohm, 0.1 Hz):
  AC volts 1 % + 5 counts (50/60 Hz; 336 / 337 20-100 Hz), 6 % + 5 counts (100-400 Hz); DC volts 1 % + 5; ohms 1 % + 5; AC amps 2 % + 5 (50/60 Hz; 336 / 337 10-100 Hz), 6 % + 5 (10-400 Hz as printed);
  DC amps 2 % + 5 (336 / 337); inrush 2 % + 5 (334-337); frequency 0.5 % + 5 counts (337).
  Every printed limit equals the full published accuracy to within half a display step EXCEPT:
    * the four OHMS rows (600 ohm 590.5 .. 609.5; 6 kohm 5905 .. 6095; on both tables): the printed limits are +-9.5 ohm / +-95 ohm, which is 1.5 % + 5 counts, NOT the 1 % + 5 counts the Specifications print
      (+-6.5 / +-65): the printed limits are LOOSER than the published accuracy by 3 ohm / 30 ohm.  Stored AS PRINTED, flagged in the point note, `step.check` and the builder output (verdict 'looser').
    * frequency 10 Hz (9.4 .. 10.6): the accuracy is +-0.55 Hz (9.45 .. 10.55), the printed limits are the two values rounded outward (verdict 'rounded').
  NOTHING is changed.  A mismatch of any other kind aborts the build.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_33x_pv.json'
DOCUMENT = 'Fluke 33X ClampMeters - Calibration Information (PN 1618765, June 2001, Rev. 2, 12/03)'
MODELS = ('333', '334', '335', '336', '337')
EXPECTED_COUNTS = {'333': 12, '334': 16, '335': 16, '336': 23, '337': 30}          # Table 2 rows (11 / 13 / 13 / 20 / 27) + the functional checks (1 / 3 / 3 / 3 / 3)
TABLE_COUNTS = {'333': 11, '334': 13, '335': 13, '336': 20, '337': 27}
EXPECTED_TABLE_COUNTS = {'2A': 14, '2B': 27}
TURNS = 50
PAGE = {'2A': '8', '2B': '9'}
TABLE_NAME = {'2A': 'Table 2 (333, 334, 335)', '2B': 'Table 2 (336, 337)'}

UNITS = {'V': ('1', 'V'), 'Ω': ('1', 'ohm'), 'A': ('1', 'A'), 'Hz': ('1', 'Hz')}

M_A = ('333', '334', '335')
M_B = ('336', '337')
M333, M334_5, M337 = ('333',), ('334', '335'), ('337',)

# Dial (Figure 2, printed p. 5, 337 shown, read from the rendered page): OFF, V~, V (dc), Ohm with the continuity symbol (one position), A~, A (dc), Hz; buttons ZERO, INRUSH, MIN/MAX and a backlight button.
# How continuity is selected within the ohm position, and whether the Hz position is a dial position on every model, are not stated: UNVERIFIED.
SW = {
    'acv': 'V~  (AC volts)',
    'acv_mm': 'V~  (AC volts, MIN/MAX mode: press the MIN/MAX button; Min/Max rows, printed p. 9)',
    'dcv': 'V⎓  (DC volts)',
    'ohm': 'Ω  (ohms: the Ω position, shared with continuity; the display must show Ω, not continuity)',
    'cont': 'Continuity  •)))  (the Ω position with the continuity function; how it is selected is not described in the Calibration Information: UNVERIFIED)',
    'aca': 'A~  (AC amps: jaw closed around the 50-turn coil)',
    'inrush': 'A~ INRUSH  (AC amps: jaw closed around the 50-turn coil; press the INRUSH button AFTER the current is applied)',
    'dca': 'A⎓  (DC amps: jaw closed around the 50-turn coil; press ZERO with 0 A before the first DC amps point)',
    'hz': 'Hz  (frequency: dial on Hz; jaw closed around the 50-turn coil)',
}

# published accuracy (percent of reading, counts), Specifications printed p. 3
ACC = {'ACV': ('1', 5), 'ACV400': ('6', 5), 'DCV': ('1', 5), 'OHM': ('1', 5), 'ACA50': ('2', 5), 'ACA400': ('6', 5), 'INRUSH': ('2', 5), 'DCA': ('2', 5), 'HZ': ('0.5', 5)}
UM = 'Specifications (printed p. 3)'

NOTE_RANGE = ('Table 2 names no range and no resolution. Range and resolution shown are those of the Specifications (printed p. 3: 600.0 V, 600.0 ohm / 6000 ohm, amps 0.1 A) and the decimals of the printed limits; '
              'the meter autoranges (the Specifications print "0 - 600.00 V" for AC volts, taken as 600.0 V: UNVERIFIED).')
NOTE_OHMS = 'Table 2 does not say whether the limits include test lead resistance (UNVERIFIED); use short leads.'
NOTE_COIL = ('The calibrator drives the {turns}-turn coil and the meter reads {turns} x the calibrator current: {applied} A in, {nominal} A on the meter. The "5520A Output" column of Table 2 (printed p. {page}) lists the {nominal} A '
             'the jaw sees (the limits are meter readings, centred on it); the calibrator output {applied} A = {nominal} / {turns} is an INFERENCE (UNVERIFIED), as for every clamp meter on the 5500A/COIL. '
             'Uncertainty (owner decision): the 5500A/COIL\'s own scope uncertainty (A2LA-5500A-COIL) at the effective current the jaw sees ({nominal} A), not the calibrator\'s at {applied} A; '
             'where the coil\'s lines do not cover the point (AC below 20.5 A) the calibrator\'s uncertainty at the sourced current x 50 is used. TAR / TUR compare it with the meter-reading tolerance printed in Table 2.')
NOTE_INRUSH = ('Table 2 footnotes: "The INRUSH button must be pressed after current is applied to the 50-turn coil" and "Display should bar (- - - -), then show reading with inrush light on (334, 335)". '
               'The program applies the output, then asks for the reading: press INRUSH once the current is on. The footnote names 334 and 335 for the barring display; the same row is printed for the 336 / 337 and the '
               'Specifications give the inrush integration time as 100 ms (NA on the 333, which has no INRUSH button and no inrush row). 5 A in the jaw = 0.1 A at 60 Hz through the coil.')
NOTE_FREQ = ('Frequency (337): "{eff} A {freq} Hz" in Table 2: the current the jaw sees, {applied} A at {freq} Hz through the {turns}-turn coil (Figure 4 is the "Amps/Hz Verification Setup"); the meter shows the FREQUENCY, '
             '{nominal} Hz. The Specifications give the Hz trigger level as 10-100 Hz: 5 A or more, 100-400 Hz: more than 10 A{trig}. The coil assignment and the x 50 are an INFERENCE (UNVERIFIED). '
             'Uncertainty (owner decision, 2026-10-26, all handheld meters): the frequency is the calibrator\'s own OUTPUT frequency, so the uncertainty is the calibrator\'s published frequency specification '
             '(5522A / 5520A sheet or 5560A sheet, uncertainty_budget FREQ), not the lab Frequency - Measure CMC alone.')
NOTE_TRIG300 = ('; the 300 Hz point is 10 A, exactly the trigger level printed as "> 10 A", so a marginal trigger may need the point repeated (UNVERIFIED)')
NOTE_ZERO = ('Table 2: "0.0 A after button push". The calibrator outputs 0 A dc (programmed and operated as for every point) through the coil with the jaw closed round it; press the ZERO button (Figure 2) and read: '
             'limits -0.5 A to 0.5 A. How the ZERO button works on the meter (and whether the later DC amps points need it) is not described in the Calibration Information: UNVERIFIED. '
             'NO UNCERTAINTY is printed for this point (owner decision of 2026-10-26 for the 381\'s 0 A dc point, applied here: a zero point, the calibrator floor is not a meaningful uncertainty for the meter zero; '
             'the step carries no_uncertainty): the owner is asked to confirm.')
NOTE_POLARITY = ('DC polarity: the manual does not describe the coil polarity for the DC amps points. A positive calibrator current must read positive on the meter and a negative one negative (the typed sign is judged): '
                 'if the sign is reversed, swap the two coil leads at the calibrator (UNVERIFIED).')
NOTE_DUTY = ('Coil duty (5500A/COIL data): 11 A rms continuous, 20 A rms for 2 minutes (above 11 A: 2 minutes ON, 8 minutes OFF); {applied} A is above 11 A: keep the output ON only as long as the reading needs and let the coil rest '
             '8 minutes before the next high-current point (UNVERIFIED for this coil).')
NOTE_400 = ('400 Hz through the coil: the 5500A/COIL data sheet gives DC and 45-440 Hz; 4 A at 400 Hz is inside it. LCOMP is set where the calibrator allows it (below 1 kHz from 0.33 A, 5522A Operators Manual p. 6-23).')
NOTE_MM = ('Min/Max rows (337, printed p. 9): with the meter on V~ press MIN/MAX; the calibrator applies 600 V at 400 Hz and the reading is judged against the printed limits (the same figures as the plain 600 V 400 Hz row). '
           'Which of MAX / MIN the display shows after the button press is not stated (UNVERIFIED): read the value that is displayed. Press MIN/MAX again afterwards (not stated either).')
NOTE_NOCHANGE = ('Min/Max (337), "Reading does not change": the meter stays in MIN/MAX mode from the 600 V 400 Hz point; the calibrator now outputs 20 V at 400 Hz and the displayed reading must stay as it was '
                 '(the Table prints no limits: a yes / no judgement; MIN/MAX holds the extreme, so a high reading must not follow the output down to 20 V). The yes / no question is the operator\'s; '
                 'NO UNCERTAINTY applies (no numeric reading, nothing to compare).')
NOTE_BEEP = 'Table 2: "25 ohm: Beeper On" (Specifications: continuity beeper at 30 ohm or less). The calibrator outputs 25 ohm; the beeper must sound.'
NOTE_HIV = 'The 600 V point sits at the top of the 600.0 V range (the meter must not be used above 600 V or 400 Hz fundamental, Safety Information, printed p. 2). HIGH VOLTAGE confirmation is asked once per hook-up group.'
NOTE_6K = '6 kohm is on the 600 - 6000 ohm range (Specifications, printed p. 3); the printed limits (5905 .. 6095) are whole ohms, so 1 ohm resolution is used (UNVERIFIED).'
NOTE_OTHER_MODELS = {
    '2A': 'Table 2 (333, 334, 335), printed p. 8.',
    '2B': 'Table 2 (336, 337), printed p. 9 ("Table 2. Performance Tests 336, 337 (cont.)").',
}

# (table, section, switch key, range, kind, test, applied (calibrator output, base units; amps: meter reading / 50), frequency, display unit, nominal (what the meter shows, display unit),
#  printed low, printed high, accuracy key, resolution, models, extras)
ROWS = [
    # ---- Table 2 (333, 334, 335), printed p. 8
    ('2A', 'AC volts', 'acv', '600.0 V', 'ACV', 'numeric', '20', 50, 'V', '20', '19.3', '20.7', 'ACV', '0.1', M_A, {}),
    ('2A', 'AC volts', 'acv', '600.0 V', 'ACV', 'numeric', '600', 50, 'V', '600', '593.5', '606.5', 'ACV', '0.1', M_A, {'hiv': True}),
    ('2A', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '20', None, 'V', '20', '19.3', '20.7', 'DCV', '0.1', M_A, {}),
    ('2A', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '-20', None, 'V', '-20', '-20.7', '-19.3', 'DCV', '0.1', M_A, {}),
    ('2A', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '600', None, 'V', '600', '593.5', '606.5', 'DCV', '0.1', M_A, {'hiv': True}),
    ('2A', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '-600', None, 'V', '-600', '-606.5', '-593.5', 'DCV', '0.1', M_A, {'hiv': True}),
    ('2A', 'Continuity', 'cont', '', 'OHM', 'beeper', '25', None, 'Ω', '25', None, None, None, None, M_A, {}),
    ('2A', 'Ohms', 'ohm', '600.0 Ω', 'OHM', 'numeric', '600', None, 'Ω', '600', '590.5', '609.5', 'OHM', '0.1', M_A, {}),
    ('2A', 'Ohms', 'ohm', '6000 Ω', 'OHM', 'numeric', '6000', None, 'Ω', '6000', '5905', '6095', 'OHM', '1', M334_5, {'k6': True}),
    ('2A', 'AC amps', 'aca', '', 'ACI', 'numeric', '0.4', 50, 'A', '20', '19.1', '20.9', 'ACA50', '0.1', M_A, {'coil': True}),
    ('2A', 'AC amps', 'aca', '', 'ACI', 'numeric', '4', 50, 'A', '200', '195.5', '204.5', 'ACA50', '0.1', M_A, {'coil': True}),
    ('2A', 'AC amps', 'aca', '', 'ACI', 'numeric', '8', 50, 'A', '400', '391.5', '408.5', 'ACA50', '0.1', M333, {'coil': True}),
    ('2A', 'AC amps', 'aca', '', 'ACI', 'numeric', '12', 50, 'A', '600', '587.5', '612.5', 'ACA50', '0.1', M334_5, {'coil': True}),
    ('2A', 'Inrush', 'inrush', '', 'ACI', 'numeric', '0.1', 60, 'A', '5', '4.4', '5.6', 'INRUSH', '0.1', M334_5, {'coil': True, 'inrush': True}),
    # ---- Table 2 (336, 337), printed p. 9
    ('2B', 'AC volts', 'acv', '600.0 V', 'ACV', 'numeric', '20', 50, 'V', '20', '19.3', '20.7', 'ACV', '0.1', M_B, {}),
    ('2B', 'AC volts', 'acv', '600.0 V', 'ACV', 'numeric', '600', 50, 'V', '600', '593.5', '606.5', 'ACV', '0.1', M_B, {'hiv': True}),
    ('2B', 'AC volts', 'acv', '600.0 V', 'ACV', 'numeric', '600', 400, 'V', '600', '563.5', '636.5', 'ACV400', '0.1', M_B, {'hiv': True}),
    ('2B', 'Min/Max', 'acv_mm', '600.0 V', 'ACV', 'numeric', '600', 400, 'V', '600', '563.5', '636.5', 'ACV400', '0.1', M337, {'hiv': True, 'minmax': True}),
    ('2B', 'Min/Max', 'acv_mm', '600.0 V', 'ACV', 'visual', '20', 400, 'V', '20', None, None, None, None, M337, {'nochange': True}),
    ('2B', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '20', None, 'V', '20', '19.3', '20.7', 'DCV', '0.1', M_B, {}),
    ('2B', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '-20', None, 'V', '-20', '-20.7', '-19.3', 'DCV', '0.1', M_B, {}),
    ('2B', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '600', None, 'V', '600', '593.5', '606.5', 'DCV', '0.1', M_B, {'hiv': True}),
    ('2B', 'DC volts', 'dcv', '600.0 V', 'DCV', 'numeric', '-600', None, 'V', '-600', '-606.5', '-593.5', 'DCV', '0.1', M_B, {'hiv': True}),
    ('2B', 'Continuity', 'cont', '', 'OHM', 'beeper', '25', None, 'Ω', '25', None, None, None, None, M_B, {}),
    ('2B', 'Ohms', 'ohm', '600.0 Ω', 'OHM', 'numeric', '600', None, 'Ω', '600', '590.5', '609.5', 'OHM', '0.1', M_B, {}),
    ('2B', 'Ohms', 'ohm', '6000 Ω', 'OHM', 'numeric', '6000', None, 'Ω', '6000', '5905', '6095', 'OHM', '1', M_B, {'k6': True}),
    ('2B', 'AC amps', 'aca', '', 'ACI', 'numeric', '0.4', 50, 'A', '20', '19.1', '20.9', 'ACA50', '0.1', M_B, {'coil': True}),
    ('2B', 'AC amps', 'aca', '', 'ACI', 'numeric', '4', 50, 'A', '200', '195.5', '204.5', 'ACA50', '0.1', M_B, {'coil': True}),
    ('2B', 'AC amps', 'aca', '', 'ACI', 'numeric', '4', 400, 'A', '200', '187.5', '212.5', 'ACA400', '0.1', M_B, {'coil': True}),
    ('2B', 'AC amps', 'aca', '', 'ACI', 'numeric', '12', 50, 'A', '600', '587.5', '612.5', 'ACA50', '0.1', M_B, {'coil': True}),
    ('2B', 'AC amps', 'aca', '', 'ACI', 'numeric', '18', 50, 'A', '900', '881.5', '918.5', 'ACA50', '0.1', M337, {'coil': True}),
    ('2B', 'Inrush', 'inrush', '', 'ACI', 'numeric', '0.1', 60, 'A', '5', '4.4', '5.6', 'INRUSH', '0.1', M_B, {'coil': True, 'inrush': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '0', None, 'A', '0', '-0.5', '0.5', 'DCA', '0.1', M_B, {'coil': True, 'zero': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '0.4', None, 'A', '20', '19.1', '20.9', 'DCA', '0.1', M_B, {'coil': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '-0.4', None, 'A', '-20', '-20.9', '-19.1', 'DCA', '0.1', M_B, {'coil': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '12', None, 'A', '600', '587.5', '612.5', 'DCA', '0.1', M_B, {'coil': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '-12', None, 'A', '-600', '-612.5', '-587.5', 'DCA', '0.1', M_B, {'coil': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '18', None, 'A', '900', '881.5', '918.5', 'DCA', '0.1', M337, {'coil': True}),
    ('2B', 'DC amps', 'dca', '', 'DCI', 'numeric', '-18', None, 'A', '-900', '-918.5', '-881.5', 'DCA', '0.1', M337, {'coil': True}),
    ('2B', 'Frequency', 'hz', '', 'ACI', 'numeric', '0.1', 10, 'Hz', '10', '9.4', '10.6', 'HZ', '0.1', M337, {'coil': True, 'freq_row': True, 'eff': '5'}),
    ('2B', 'Frequency', 'hz', '', 'ACI', 'numeric', '0.2', 300, 'Hz', '300', '298.0', '302.0', 'HZ', '0.1', M337, {'coil': True, 'freq_row': True, 'eff': '10', 'trig300': True}),
]
EXPECTED_COUNT = 41

# Functional checks, printed pp. 5-6 (no calibrator output, no limits, no uncertainty; yes / no, table 'F' runs first as in the 110 / 287 families), in the manual's order:
# (title, switch, setup, question, models, printed page)
FUNC = [
    ('Display test', 'Display test',
     'Testing the Display (printed p. 5, Figure 2): turn the Meter on while holding down the INRUSH button, then check all segments for clarity and contrast. The 333 is not equipped with this feature.',
     'All display segments are clear and have good contrast.', ('334', '335', '336', '337'), 'p. 5'),
    ('Backlight test', 'Backlight test',
     'Backlight Test (printed p. 6, Figure 3): press the backlight button. The backlight will come on and the unit will beep. Press the button a second time to turn the backlight off.',
     'The backlight came on with a beep and went off at the second press.', ('334', '335', '336', '337'), 'p. 6'),
    ('Keypad test', 'Keypad test',
     'Keypad Test (printed p. 6): turn the Meter on and push each button separately. Each button push will cause the Meter to beep.',
     'Every button push made the Meter beep.', MODELS, 'p. 6'),
]
# rows the check classifies as other than 'full' / 'half' (global step number in table order): anything else that is not full aborts (re-read the table)
EXPECTED_FLAGS = {8: 'looser', 9: 'looser', 25: 'looser', 26: 'looser', 40: 'rounded'}


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def spec_halfwidth(nominal, acc, res):
    pct, digits = D(acc[0]), acc[1]
    return pct / 100 * abs(D(nominal)) + digits * D(res)


def check_row(nominal, low, high, acc, res):
    """(info, verdict) as the 376 / 381 builders: 'full', 'half', 'tighter', 'rounded' or 'looser' against the published accuracy; nothing is changed."""
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


def group_for(extra, applied, test):
    if test == 'beeper' or not extra.get('coil'):
        return 'VOHM'
    return 'COIL_AUX' if abs(D(applied)) < 3 else 'COIL_20A'


def check_rows():
    problems = []
    for n, (table, section, sw, rng, kind, test, applied, freq, unit, nominal, low, high, acc_key, res, models, extra) in enumerate(ROWS, 1):
        if test == 'numeric':
            nom, lo, hi = D(nominal), D(low), D(high)
            if not lo <= nom <= hi:
                problems.append(f'row {n}: nominal {nominal} not between {low} and {high}')
            if abs((nom - lo) - (hi - nom)) > D('0.0000001'):
                problems.append(f'row {n}: limits not symmetric about {nominal}: {low} .. {high}')
            if extra.get('coil') and not extra.get('freq_row') and D(applied) * TURNS != nom:
                problems.append(f'row {n}: {applied} A x {TURNS} turns is not {nominal} A')
            if extra.get('freq_row'):
                if D(nominal) != D(freq):
                    problems.append(f'row {n}: frequency nominal {nominal} Hz differs from {freq} Hz')
                if D(applied) * TURNS != D(extra['eff']):
                    problems.append(f'row {n}: {applied} A x {TURNS} turns is not the printed {extra["eff"]} A')
    if len(ROWS) != EXPECTED_COUNT:
        problems.append(f'{len(ROWS)} rows, Table 2 has {EXPECTED_COUNT}')
    tc = {t: sum(1 for r in ROWS if r[0] == t) for t in EXPECTED_TABLE_COUNTS}
    if tc != EXPECTED_TABLE_COUNTS:
        problems.append(f'rows per table {tc} differ from {EXPECTED_TABLE_COUNTS}')
    counts = {m: sum(1 for r in ROWS if m in r[14]) for m in MODELS}
    if counts != TABLE_COUNTS:
        problems.append(f'Table 2 points per model {counts} differ from {TABLE_COUNTS}')
    return problems


def build_steps():
    steps, problems, flagged = [], [], []
    for n, (table, section, sw, rng, kind, test, applied, freq, unit, nominal, low, high, acc_key, res, models, extra) in enumerate(ROWS, 1):
        factor, base = UNITS[unit]
        tn = sum(1 for r in ROWS[:n] if r[0] == table)             # row number within its printed table (the 'ref')
        page = PAGE[table]
        a_txt = f'{D(applied).normalize():f}'
        n_txt = f'{D(nominal).normalize():f}'
        step = dict(table=table, step=n, section=section, switch=SW[sw], range=rng, models=list(models), kind=kind, test=test)
        if test == 'beeper':
            step.update(expect='on', question='The beeper is ON (sounding).', applied=dict(value=clean(applied), frequency=None), nominal=clean(D(nominal) * D(factor)),
                        base_unit=base, display_unit=unit, factor=float(D(factor)))
            step['note'] = ' '.join([NOTE_BEEP, NOTE_OHMS])
            step['group'] = 'VOHM'
            step['ref'] = f'T{table} #{tn}'
            step['id'] = f'{table}-{n}'
            steps.append(step)
            continue
        if test == 'visual':
            step.update(title='Min/Max: reading does not change (20 V, 400 Hz)', question='MIN/MAX is on and the displayed reading does NOT change when the output drops to 20 V.',
                        applied=dict(value=clean(applied), frequency=float(freq)), nominal=clean(D(nominal) * D(factor)), base_unit=base, display_unit=unit, factor=float(D(factor)))
            step['note'] = NOTE_NOCHANGE
            step['report_desc'] = 'Min/Max, 20 V 400 Hz: reading does not change'
            step['group'] = 'VOHM'
            step['settle'] = 3
            step['ref'] = f'T{table} #{tn}'
            step['id'] = f'{table}-{n}'
            steps.append(step)
            continue
        info, verdict = check_row(nominal, low, high, ACC[acc_key], res)
        expected = EXPECTED_FLAGS.get(n)
        if (verdict if verdict in ('tighter', 'rounded', 'looser') else None) != expected:
            problems.append(f'step {n}: classified {verdict!r}, the builder expects {expected!r} (re-read the table)')
        step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=low, high=high,
                    applied=dict(value=clean(applied), frequency=float(freq) if freq else None), nominal=clean(D(nominal) * D(factor)))
        acc = ACC[acc_key]
        full = spec_halfwidth(nominal, acc, res)
        step['accuracy'] = f'±({acc[0]} % of reading + {acc[1]} counts)'
        step['tol_text'] = (f'{TABLE_NAME[table]}: {low} to {high} {unit}   ({UM}: ±({acc[0]} % of reading + {acc[1]} counts of {res} {unit}) = ±{fmt(full.normalize())} {unit})')
        notes = [NOTE_OTHER_MODELS[table], NOTE_RANGE]
        if extra.get('freq_row'):
            notes.append(NOTE_FREQ.format(eff=extra['eff'], freq=freq, applied=a_txt, turns=TURNS, nominal=n_txt, trig=NOTE_TRIG300 if extra.get('trig300') else ''))
            step['unc_kind'] = 'FREQ'
            step['no_freq_suffix'] = True
            step['report_desc'] = f'{a_txt} A x {TURNS} turns, {freq} Hz'
            step['dsb_desc'] = f'Frequency, jaw on the {TURNS}-turn coil: calibrator {a_txt} A @ {freq} Hz, meter reads {n_txt} Hz'
            step['settle'] = 5
        elif extra.get('coil'):
            notes.append(NOTE_COIL.format(turns=TURNS, applied=a_txt, nominal=n_txt, page=page))
            if extra.get('inrush'):
                notes.append(NOTE_INRUSH)
            step['report_desc'] = f'{"Inrush, " if extra.get("inrush") else "Jaw, "}{a_txt} A x {TURNS} turns'
            step['dsb_desc'] = f'{section}, jaw on the {TURNS}-turn coil: meter reads {n_txt} A' + (f' @ {freq} Hz' if freq else '')
            step['settle'] = 5
            step['unc_standard'] = 'A2LA-5500A-COIL'          # every 50-turn-coil point names the coil sheet at the effective current (tests/test_coil_uncertainty.py)
            step['unc_nominal'] = step['nominal']
            if extra.get('zero'):
                step['no_uncertainty'] = True                  # ... but the 0 A point prints none (no_uncertainty wins in has_uncertainty; the coil sheet has no 0 A line anyway)
                step['report_desc'] = '0 A dc after ZERO'
                step['dsb_desc'] = 'DC amps, 0 A: jaw closed on the coil, ZERO pressed'
                notes.append(NOTE_ZERO)
            if freq == 400:
                notes.append(NOTE_400)
            if abs(D(applied)) > 11:
                notes.append(NOTE_DUTY.format(applied=a_txt))
            if kind == 'DCI':
                notes.append(NOTE_POLARITY)
        if extra.get('minmax'):
            notes.append(NOTE_MM)
            step['report_desc'] = 'MIN/MAX mode, 600 V 400 Hz'
        if kind == 'OHM':
            notes.append(NOTE_OHMS)
        if extra.get('hiv'):
            notes.append(NOTE_HIV)
        if extra.get('k6'):
            notes.append(NOTE_6K)
        if verdict in ('rounded', 'looser'):
            what = '; '.join(f'{i["side"]} limit ±{i["printed"]} from the nominal vs the published ±{i["full_spec"]}' for i in info)
            step['check'] = dict(verdict=verdict, printed_vs_spec=info, full_spec=fmt(full.normalize()))
            if verdict == 'looser':
                notes.append(f'CHECK - DISCREPANCY (printed limit NOT changed; {UM}): the printed limits are LOOSER than the published accuracy of {acc[0]} % + {acc[1]} counts ({what}); '
                             'they are the figures of 1.5 % + 5 counts. Used as printed.')
            else:
                notes.append(f'CHECK (printed limit not changed; {UM}): the printed limit is the specification value rounded outward to the display step ({what}).')
            flagged.append((f'{table}-{n}', verdict, section, applied, freq, nominal, low, high))
        step['group'] = group_for(extra, applied, test)
        step['note'] = ' '.join(notes)
        step['ref'] = f'T{table} #{tn}'
        step['id'] = f'{table}-{n}'          # the step number runs on across the two tables (the engine orders points by it); 'ref' is the printed row
        steps.append(step)
    for k, (title, switch, setup, question, models, page) in enumerate(FUNC, 1):
        steps.append(dict(table='F', step=k, section='Functional checks', switch=switch, range='', models=list(models), kind='VISUAL', test='visual', title=title, setup=setup,
                          question=question, setup_key='NONE', id=f'F-{k}', ref=f'{page} functional check',
                          note=f'Functional check of the Performance Tests section ({page}); no calibrator output, no limits, no uncertainty (yes / no). Owner decision 2026-10-27: included.'))
    counts = {m: sum(1 for s in steps if m in s['models']) for m in MODELS}
    if counts != EXPECTED_COUNTS:
        problems.append(f'points per model {counts} differ from {EXPECTED_COUNTS}')
    return steps, problems, flagged


def common():
    return [
        ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
        ('Test leads', 'REMOVE the test leads from the VΩ and COM jacks while current is measured with the jaw (general practice; the Calibration Information does not say).'),
        ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
    ]


LCOMP_TEXT = ('Fluke 5522A / 5520A: the program turns inductive-load compensation (LCOMP) ON for every AC point through the coil (read back with LCOMP?) and OFF afterwards (the Calibration Information, printed p. 7 step 4, '
              'asks for LCOMP ON on the 5520A for the amp function; 5522A Operators Manual p. 6-23; on the 5520A the command is UNVERIFIED). Where the calibrator does not allow it (440 Hz and above below 0.33 A; '
              '1 kHz and above from 0.33 A) it is not set and the log says so. 5560A: no LCOMP command for its own output - set it yourself if needed.')
GROUPS = {
    'COIL_AUX': dict(
        title='Change the cables: 50-turn coil on the calibrator low-current output',
        summary='Calibrator low-current output (5522A / 5520A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=common() + [
            ('Coil', 'The wired coil is 50 turns (Table 1, printed p. 5: Fluke 5500A/Coil; Figure 4, printed p. 7). Connect its two ends to the calibrator low-current output: Fluke 5522A / 5520A AUX HI and AUX LO; '
                     'Fluke 5560A VI AUX (HI) and OUTPUT LO. Use plugs rated for the current.'),
            ('Jaw', 'Close the jaw around the coil (Figure 4 shows the conductor through the jaw), fully closed, the coil centred in the opening, the coil leads kept away from the meter body. '
                    'The meter then reads 50 x the calibrator current (0.4 A reads 20 A; 0.1 A reads 5 A).'),
            ('LCOMP', LCOMP_TEXT),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads (the manual: "make sure the calibrator is in standby mode (STBY)", printed p. 6).',
        diagram='diagrams/hook_fluke33x_COIL_AUX.png'),
    'COIL_20A': dict(
        title='Change the cables: 50-turn coil on the calibrator high-current output',
        summary='Calibrator high-current output (5522A / 5520A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=common() + [
            ('Coil', 'Move the two ends of the 50-turn coil to the calibrator high-current terminals: Fluke 5522A / 5520A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 18 A.'),
            ('Jaw', 'The jaw stays closed around the coil (centred, fully closed, leads away from the meter body). The meter reads 50 x the calibrator current: 4 A reads 200 A, 8 A reads 400 A, 12 A reads 600 A, 18 A reads 900 A.'),
            ('LCOMP', 'Fluke 5522A / 5520A: AC points through the coil - the program turns LCOMP ON for each (and OFF afterwards), as for the low-current points.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 18 A flows in the coil. Duty (5500A/COIL data): 11 A rms continuous, 20 A rms for 2 minutes then 8 minutes OFF; not confirmed for this coil (UNVERIFIED). '
                'Keep the calibrator in STANDBY whenever you touch the coil or leads.',
        diagram='diagrams/hook_fluke33x_COIL_20A.png'),
}

SOURCE_NOTE = (
    'Table 2 of the 33X Calibration Information (PN 1618765, Rev. 2, 12/03): "Performance Tests 333, 334, 335" (14 rows, printed p. 8) and "Performance Tests 336, 337 (cont.)" (27 rows, printed p. 9) = 41 rows '
    '(AC volts 5, Min/Max 2, DC volts 8, continuity 2, ohms 4, AC amps 9, inrush 2, DC amps 7, frequency 2). The tables have no step numbers and no X / N/A columns: steps are numbered in table order and the number runs on '
    'across the two tables (2A-1 .. 2A-14, then 2B-15 .. 2B-41; the ref T2A #n / T2B #n is the printed row); the models of a row are the table it is printed in (p. 8: 333 334 335; p. 9: 336 337) and the tags printed '
    'in the rows (333 / 334, 335 / 337 only / 337), so the Table 2 points per model are 333: 11, 334: 13, 335: 13, 336: 20, 337: 27 (12 / 16 / 16 / 23 / 30 with the functional checks). '
    'Table 1 (printed p. 5) names a Fluke 5520A (the program drives a Fluke 5522A, 5520A or 5560A, or you set the calibrator by hand), any Fluke DMM and the Fluke 5500A/Coil (50 turns). '
    'The "5520A Output" column of the amps rows lists the current the jaw sees; the calibrator drives that / 50 through the coil (the meter reads 50 x the calibrator current; an inference, as for every clamp meter), '
    'the inrush rows (5 A at 60 Hz) and the frequency rows (5 A at 10 Hz, 10 A at 300 Hz) likewise. The meter has no remote interface: you type the display reading. The manual prints one set of limits; they are used as printed. '
    'The four ohms limits (590.5 .. 609.5 and 5905 .. 6095) are looser than the printed Specifications (1 % + 5 counts; the limits are 1.5 % + 5 counts) and the 10 Hz frequency limits are the specification rounded outward: '
    'both flagged, nothing changed. High-voltage points go straight to the test value (the manual prescribes no ramp). The display, backlight and keypad checks (printed pp. 5-6) are yes / no points that run first (table F: 334-337 three, 333 the keypad only); the calibration ADJUSTMENT '
    '(printed pp. 10-12) is not part of this procedure.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s Table 2 (Fluke 33X ClampMeters Calibration Information, printed pp. 8-9), unchanged. The current, inrush and frequency points are driven through a 50-turn coil '
    '(calibrator current x 50 = the reading shown); the Uncertainty of a coil point is that of the 5500A/COIL scope lines at the effective current where they cover it, otherwise the calibrator\'s at the sourced current x 50; '
    'the frequency points carry the calibrator\'s frequency specification. The four ohms limits are looser than the published accuracy of the Specifications (1 % + 5 counts) and are reported as printed.')


def build_spec():
    problems = check_rows()
    steps, more, flagged = build_steps()
    problems += more
    if problems:
        raise SystemExit('Problems:\n  ' + '\n  '.join(problems))
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='fluke33x', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='8-9 (printed = PDF page): Table 2 pp. 8-9; procedure and Figure 4 p. 7; equipment Table 1 p. 5; Figure 2 p. 5; Specifications p. 3',
                    cite='Fluke 33X ClampMeters Calibration Information, Table 2 Performance Tests, printed pp. 8-9; limits unchanged, rows flagged against the Specifications (printed p. 3)',
                    limits='Manufacturer limits, Table 2, as printed (one set, no interval columns)',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={'333': dict(name='Fluke 333', brand='Fluke', model_note='Fluke 333 clamp meter (400 A, average responding): Table 2 p. 8, 11 points + keypad check = 12 (AC volts, DC volts, continuity, 600 ohm, AC amps through the 50-turn coil)'),
                '334': dict(name='Fluke 334', brand='Fluke', model_note='Fluke 334 true-rms clamp meter (600 A, inrush): Table 2 p. 8, 13 points + 3 functional checks = 16 (adds the 6 kohm and inrush rows)'),
                '335': dict(name='Fluke 335', brand='Fluke', model_note='Fluke 335 true-rms clamp meter (600 A, inrush): Table 2 p. 8, 13 points + 3 functional checks = 16 (same rows as the 334)'),
                '336': dict(name='Fluke 336', brand='Fluke', model_note='Fluke 336 true-rms clamp meter (600 A AC / DC, inrush): Table 2 p. 9, 20 points + 3 functional checks = 23 (adds 400 Hz rows and DC amps)'),
                '337': dict(name='Fluke 337', brand='Fluke', model_note='Fluke 337 true-rms clamp meter (999.9 A AC / DC, inrush, frequency): Table 2 p. 9, 27 points + 3 functional checks = 30 (adds Min/Max, 900 A and frequency rows)')},
        groups=GROUPS,
        steps=steps), flagged


def main():
    spec, flagged = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT.name, len(spec['steps']), 'steps;', count)
    print('points per model:', {m: sum(1 for s in spec['steps'] if m in s['models']) for m in MODELS})
    for f in flagged:
        print('  FLAG', f)


if __name__ == '__main__':
    main()
