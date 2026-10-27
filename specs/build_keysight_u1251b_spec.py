"""Builds specs/keysight_u1251b_u1252b_pv.json for the shared handheld engine (handheld_dmm.py) from the Keysight U1251B and U1252B Handheld Digital Multimeter
User's and Service Guide (724 PDF pages; printed page = PDF page; the English edition is PDF pp. 1-~300).

    python3 specs/build_keysight_u1251b_spec.py

Source (read from RENDERED PAGE IMAGES, pdftoppm at 130, 220 and 300 dpi, every number twice, never from extracted text; tests/test_keysight_u1251b_points.py holds the second transcription):
  Table 6-2 "Verification Test", printed pp. 155-160 (columns Step / Test Function / Range / 5520A Output / "Error from nominal 1 year" for U1251B and U1252B), notes [a]-[p] printed pp. 160-161;
  Basic Operating Test (backlight, display, current terminal; the charge terminal alert test is NOT included, owner decision 2026-10-27), printed pp. 149-151; Test Considerations, printed p. 152; Recommended Test Equipment (Table 6-1), printed p. 148;
  Table 1-1 (rotary switch), printed p. 30, Figure 1-9 and Table 1-10 (terminals), printed p. 47; Table 6-4 "Adjustment table" (printed pp. 170-174), used ONLY for the display format of each range.
The chapter has ONE set of limits (1 year, "Error from nominal"): there is no 90 day / 2 year column, so nothing had to be chosen.  The table prints the ERROR from nominal (plus / minus), not low / high
limits: low = nominal - error and high = nominal + error, in Decimal, and the builder aborts when the pair is not symmetric about the nominal.

ONE FAMILY SPEC, TWO MODELS (as the 110 / 170 / 323 / 33x families): every step lists the models it applies to.  The two models have DIFFERENT limits in most rows, so such a row is two steps
(one per model, same printed row); a row with the same error on both is one step for both; 'N/A' cells remove the row from that model.
  U1251B and U1252B point counts: see the builder output (also in tests/test_keysight_u1251b_points.py).   Registered: Procedures/Keysight_U1251B_Verification.py and Keysight_U1252B_Verification.py.
The meter has NO documented remote command set (only the IR-USB data-logging software): readings are typed by the operator (as the clamp meters).

WHAT THE TABLE DOES NOT SAY AND IS ADDED HERE (shown to the technician):
  * 5520A -> 5522A / 5560A: Table 6-1 and the column header name a Fluke 5520A; the program drives a 5522A or a 5560A (or the calibrator is set by hand).  A calibrator refuses an output it cannot make
    (calibrator_fit: the 5522A, 5520A and 5560A specification sheets cover every sourced point except the square-wave duty point, which no sheet covers).
  * Display resolution is NOT printed in the verification table.  Each typed reading is padded to the decimals of Table 6-4 (adjustment table) for the same range (5 V 4, 50 V 3, 500 V 2, 1000 V 1 ...),
    never fewer than the decimals needed to print the limit exactly; this is an INFERENCE (UNVERIFIED).
  * Table 6-2 step 1 'Turn the rotary switch to the ~V position', step 4 prints '(for model U1252B)' twice (the second is the U1251B: Table 1-1 / Table 1-10 print the DC V position for the U1251B and the
    DC+AC position for the U1252B): stored with a visible note; no limit is affected.
  * The 5 A and 10 A rows after the 'Caution: connect the calibrator to the A and COM terminals' band have NO step number.  They are placed after the AC mA rows (their print position), kind DC amps (no
    frequency is printed, unlike step 19's '5 A, 1 kHz').  Printed [k] / [j]: see the notes.  UNVERIFIED reading of the table: flagged in the report.
  * Step 15 prints [j] on the U1251B 500 uA cell and [i] on its neighbours: [j] concerns the 10 A range, [i] is the Null / thermal note: treated as a misprint for [i] (visible note; no limit affected).
  * Hand-set points (kind NONE, a 'by hand' set-up window): the frequency-counter point 12 (Keysight 33250A) and the square-wave OUTPUT points 20 (the meter is the source; Keysight 53131A and
    34410A measure: Table 6-1 says 34401A for 'Square Wave' while the table body says 34410A: flagged).  They carry NO uncertainty: the standard is not a calibrator the suite holds a specification for.
  * Amplitude (step 20, last row) prints only the error (+- 0.2 V), no nominal: 2.8 V is taken from the manufacturer's data sheet (not in this manual): UNVERIFIED, flagged.
  * Functional checks (Basic Operating Test, printed pp. 149-151) have no limits: yes / no points that run first (table F), owner rule of 2026-10-27 (as the 33x family).
  * Calibration ADJUSTMENT (Table 6-4, printed pp. 164-175) is NOT built.

CROSS-CHECK against the manufacturer's published accuracy: the manual has NO accuracy specification (chapter 7 refers to the data sheet).  A second-hand text extraction of the data sheet was available
(UNVERIFIED: cells missing, models mixed): where it gives a formula the printed error was recomputed ((% of reading) x nominal + counts x display step) and every such row agrees with the printed limit
EXCEPT the ones named in CHECKS below (verdict 'differs').  The AC volts / AC current rows could not be cross-checked (the data sheet cells were not legible in the extraction); their printed errors decode
to clean (% + counts) formulas.  NOTHING IS CHANGED: a printed limit is stored as printed.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keysight_u1251b_u1252b_pv.json'
DOCUMENT = 'Keysight U1251B and U1252B Handheld Digital Multimeter - User\'s and Service Guide'
MODELS = ('U1251B', 'U1252B')
BOTH = list(MODELS)
TABLE = '2'                                    # Table 6-2 (the engine's table key; 'F' = the functional checks, run first)
EXPECTED_COUNTS = {'U1251B': 0, 'U1252B': 0}   # filled in below once the rows are final (checked by build_spec and by the test's independent count)

PREFIX = {'p': D('1e-12'), 'n': D('1e-9'), 'µ': D('1e-6'), 'μ': D('1e-6'), 'm': D('1e-3'), '': D(1), 'k': D('1e3'), 'M': D('1e6'), 'G': D('1e9')}
BASES = {'V': 'V', 'A': 'A', 'Ω': 'ohm', 'Hz': 'Hz', 'F': 'F', 'S': 'S', '°C': 'C', '%': '%'}
_Q = re.compile(r'^\s*([+\-]?\s*\d+(?:\.\d+)?)\s*(p|n|µ|μ|m|k|M|G)?(V|A|Ω|Hz|F|S|°C|%)\s*$')


def q(text):
    """'4.5 kHz' -> (Decimal 4500, 'Hz'): a printed quantity in base units (case matters: mΩ is milli, MΩ is mega)."""
    m = _Q.match(text.replace('−', '-').replace('±', '').strip())
    if not m:
        raise SystemExit(f'cannot read the quantity {text!r}')
    return D(m.group(1).replace(' ', '')) * PREFIX[m.group(2) or ''], BASES[m.group(3)]


def display_unit(symbol):
    """'kΩ' -> (factor Decimal, base) for a display unit."""
    m = re.match(r'^(p|n|µ|m|k|M)?(V|A|Ω|Hz|F|S|°C|%)$', symbol)
    return PREFIX[m.group(1) or ''], BASES[m.group(2)]


def fmt(d: D, decimals: int) -> str:
    return format(d.quantize(D(1).scaleb(-decimals)), 'f') if decimals > 0 else format(d.quantize(D(1)), 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def needed_decimals(d: D) -> int:
    t = d.normalize().as_tuple()
    return max(0, -t.exponent)


# Display decimals of each range, from Table 6-4 (adjustment table, printed pp. 170-174: 'Cal Item' formats such as 3.0000 V, 03.000 V, 030.00 V, 0030.0 V); INFERENCE, UNVERIFIED for the verification
BASE_DEC = {('V', '5 V'): 4, ('V', '50 V'): 3, ('V', '500 V'): 2, ('V', '1000 V'): 1,
            ('mV', '50 mV'): 3, ('mV', '500 mV'): 2, ('mV', '1000 mV'): 1,
            ('Ω', '500 Ω'): 2, ('kΩ', '5 kΩ'): 4, ('kΩ', '50 kΩ'): 3, ('kΩ', '500 kΩ'): 2, ('MΩ', '5 MΩ'): 4, ('MΩ', '50 MΩ'): 3,
            ('µA', '500 µA'): 2, ('µA', '5000 µA'): 1, ('mA', '50 mA'): 3, ('mA', '440 mA'): 2, ('A', '5 A'): 4, ('A', '10 A'): 3,
            ('V', 'Diode'): 4, ('°C', '-200 °C until 1372 °C'): 1}

# the footnotes of Table 6-2, printed pp. 160-161, as printed
NOTE_TEXT = {
    'a': 'Note [a]: The additional error to be added as frequency > 20 kHz and signal input < 10% of range: 300 counts of LSD per kHz.',
    'b': 'Note [b]: The accuracy could be 0.05% + 10, always use relative function to zero thermal effect (short test leads) before measuring the signal.',
    'c': 'Note [c]: The accuracy of 500 Ω and 5 kΩ is specified after the Null function.',
    'd': 'Note [d]: For range of 50 MΩ / 500 MΩ, the RH is specified for < 60%.',
    'e': 'Note [e]: The accuracy is specified for < 50 nS and after Null function as open test lead.',
    'f': 'Note [f]: All frequency counters are susceptible to error when measuring low voltage, low-frequency signals. Shielding inputs from external noise pickup is critical for minimizing measurement errors.',
    'g': 'Note [g]: Use the Null mode to zero residual.',
    'h': 'Note [h]: Set both calibrator and multimeter to internal reference. Connect the K-type thermocouple extension (miniature thermocouple connector on both ends) between the calibrator\'s TC output and the multimeter via a TC-to-banana adapter. '
         'Allow at least 1 hour for the multimeter to stabilize before measurements are taken. The error limit does not include the error contributed by the thermocouple extension; to eliminate it, compensation of the calibrator output through a reference thermometer is recommended.',
    'i': 'Note [i]: Always use relative function to zero the thermal effect with open test lead before measuring the signal. If you do not use Relation function, add 20 digits for accuracy purposes.',
    'j': 'Note [j]: 10 A continuous, and additional 0.5% to specified accuracy when measuring a signal greater than 10 A~20 A for 30 seconds maximum. After measured current for > 10 A, cool down the meter for twice the measuring time you applied before low current measurement. With a 2-wire connection and compensation enabled at calibrator.',
    'k': 'Note [k]: Specification apply with settling time fulfilled.',
    'l': 'Note [l]: The current can be measuring from 2.5 A to 10 A continuous, and the additional of 0.5% to specified accuracy as measure the signal greater than 10 A~20 A for 30 seconds maximum. After measured current for > 10 A, cool down the meter for 2 times of measuring time you applied before low current measurement.',
    'm': 'Note [m]: For signal frequency greater than 1 kHz, additional 0.1% per kHz to be added to accuracy.',
    'n': 'Note [n]: Ensure that the ambient temperature is stable within ± 1 °C. Make sure that the multimeter is placed in a controlled environment for at least 1 hour. Keep the multimeter away from any ventilation exit. Do not touch the thermocouple test lead after connecting it to the calibrator. Allow the connection to stabilize for at least another 15 minutes before performing the measurement.',
    'o': 'Note [o]: With a 2-wire connection and compensation enabled at calibrator. (Owner decision 2026-10-27: no 2-wire compensation is commanded by the suite, options.two_wire_comp = false; set it at the calibrator by hand if the lab wants it.)',
    'p': 'Note [p]: Frequency counter performance test point is only applicable to U1252B.',
}

# rotary switch / button text ('short  (detail)'); the Shift (yellow) button and the dial symbols are as printed in Table 6-2, Table 1-1 (printed p. 30) and Table 1-10 (printed p. 47)
SW = {
    'ACV': 'V~  (AC volts: turn the rotary switch to the ~V position)',
    'FREQ': 'Hz  (frequency: in the ~V position press the Hz button to go to frequency mode)',
    'COUNTER': 'Hz  (frequency counter, U1252B: turn the rotary switch to the Hz/diode position and press Shift for the frequency counter mode)',
    'DUTY': '% duty  (duty cycle: in the ~V position press the Hz button to go to Duty Cycle mode)',
    'DCV': 'V⎓  (DC volts: turn the rotary switch to the ⎓V position on the U1251B, to the ≃V position on the U1252B)',
    'ACV2': 'V~  (AC volts, U1252B: in the ≃V position press the Shift button to go to the ~V mode)',
    'DCMV': 'mV⎓  (DC millivolts: turn the rotary switch to the ≃mV position)',
    'ACMV': 'mV~  (AC millivolts: in the ≃mV position press the Shift button to go to the ~mV mode)',
    'OHM': 'Ω  (turn the rotary switch to the Ω position)',
    'NS': 'nS  (conductance: in the Ω position press the Shift button to go to the ns mode)',
    'DIODE': 'Diode  (turn the rotary switch to the diode position: Hz/diode on the U1252B, diode on the U1251B)',
    'CAP': 'Capacitance  (turn the rotary switch to the temperature / capacitance position, capacitance function)',
    'TEMP': 'Temperature °C  (in the temperature / capacitance position press the Shift button to go to the temperature mode; °C)',
    'UADC': 'µA⎓  (DC microamps: turn the rotary switch to the µA position)',
    'UAAC': 'µA~  (AC microamps: in the µA position press the Shift button to go to the ~µA mode)',
    'MADC': 'mA⎓  (DC milliamps: turn the rotary switch to the mA·A position, mA input)',
    'MAAC': 'mA~  (AC milliamps: in the mA·A position press the Shift button to go to the ~mA mode)',
    'ADC': 'A⎓  (DC amps: the mA·A position with the lead in the A input; if Shift is lit from the AC mA step, press Shift to return to DC: not stated in the manual, UNVERIFIED)',
    'AAC': 'A~  (AC amps: in the mA·A position press the Shift button to go to the ~A mode)',
}

NOTE_RES = ('Display decimals (typed-reading padding) are those of Table 6-4 for this range (UNVERIFIED for the verification table), at least the decimals of the limits. Limits are the printed 1-year error from the nominal: '
            'low = nominal - error, high = nominal + error.')
NOTE_CAL = 'Table 6-2 names a Fluke 5520A; the program drives the 5522A or 5560A (or the calibrator is set by hand).'
NOTE_STEP4 = ('Printed misprint: the table says "to ≃V position (for model U1252B), to ⎓V position (for model U1252B)"; Table 1-1 / Table 1-10 put the ⎓V position on the U1251B and the ≃V position on the U1252B, '
              'so the second "(for model U1252B)" is read as U1251B. No limit is affected.')
NOTE_STEP15J = ('Printed misprint: the U1251B 500 µA cell is marked [j] (10 A continuous); its neighbours are marked [i] (Null / thermal effect): read as [i]. No limit is affected.')
NOTE_NOSTEP = ('The 5 A and 10 A rows below the printed Caution band have no step number: read as DC amps (CONFIRMED DC by the owner 2026-10-27; the table prints no frequency for them, step 19 prints "5 A, 1 kHz" for AC) and placed in their printed position, '
               'after the AC mA rows (UNVERIFIED reading of the table).')

# ROWS: (key, section, switch, range, kind, calibrator output as printed, nominal as printed (None = the output value), U1251B error as printed (None = N/A), U1252B error, display unit, extras)
# kind: ACV DCV ACI DCI OHM CAP TEMP, 'FREQ' (an ACV source, frequency reading), 'DUTY' (square-wave source), 'COND' (resistance source, conductance reading),
#       'HANDSET' (a hand-set point, no calibrator output; extras['setup'])
ROWS = [
    # ---- step 1: AC volts (printed p. 155)
    ('1', 'AC volts', 'ACV', '5 V', 'ACV', '5 V, 1 kHz', None, '32.5 mV', '22.5 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '5 V', 'ACV', '4.5 V, 10 kHz', None, '169.5 mV', '71.5 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '5 V', 'ACV', '4.5 V, 20 kHz', None, None, '169.5 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '5 V', 'ACV', '4.5 V, 30 kHz', None, '169.5 mV', None, 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '5 V', 'ACV', '4.5 V, 100 kHz', None, None, '169.5 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '50 V', 'ACV', '50 V, 1 kHz', None, '325 mV', '225 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '50 V', 'ACV', '45 V, 10 kHz', None, '1.695 V', '715 mV', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '50 V', 'ACV', '45 V, 20 kHz', None, None, '1.695 V', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '50 V', 'ACV', '45 V, 30 kHz', None, '1.695 V', None, 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '50 V', 'ACV', '45 V, 100 kHz', None, None, '1.695 V', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '500 V', 'ACV', '500 V, 1 kHz', None, '3.25 V', '2.25 V', 'V', {'fn': 'a'}),
    ('1', 'AC volts', 'ACV', '1000 V', 'ACV', '1000 V, 1 kHz', None, '10 V', '8.0 V', 'V', {'fn': 'a'}),
    # ---- step 2: frequency; step 3: duty cycle
    ('2', 'Frequency', 'FREQ', '9.9999 kHz', 'FREQ', '0.48 V, 1 kHz', '1 kHz', '500 mHz', '500 mHz', 'kHz',
     {'extra': 'Table 6-1 (printed p. 148) lists a Keysight 33250A for Frequency, Table 6-2 a 5520A output (0.48 V, 1 kHz): Table 6-2 is followed.'}),
    ('3', 'Duty cycle', 'DUTY', '0.01% – 99.99%', 'DUTY', '5.0 Vpp, 50 Hz, 50 %', '50 %', '0.315 %', '0.315 %', '%', {}),
    # ---- step 4: DC volts
    ('4', 'DC volts', 'DCV', '5 V', 'DCV', '5 V', None, '2 mV', '1.75 mV', 'V', {'fn': '', 'extra': NOTE_STEP4}),
    ('4', 'DC volts', 'DCV', '50 V', 'DCV', '50 V', None, '20 mV', '17.5 mV', 'V', {'extra': NOTE_STEP4}),
    ('4', 'DC volts', 'DCV', '500 V', 'DCV', '500 V', None, '200 mV', '200 mV', 'V', {'extra': NOTE_STEP4}),
    ('4', 'DC volts', 'DCV', '1000 V', 'DCV', '1000 V', None, '800 mV', '800 mV', 'V', {'extra': NOTE_STEP4}),
    # ---- step 5: AC volts, Shift mode (U1252B only)
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '5 V', 'ACV', '5 V, 1 kHz', None, None, '22.5 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '5 V', 'ACV', '5 V, 10 kHz', None, None, '79.0 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '5 V', 'ACV', '4.5 V, 20 kHz', None, None, '169.5 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '5 V', 'ACV', '4.5 V, 100 kHz', None, None, '169.5 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '50 V', 'ACV', '50 V, 1 kHz', None, None, '225 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '50 V', 'ACV', '50 V, 10 kHz', None, None, '790 mV', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '50 V', 'ACV', '45 V, 20 kHz', None, None, '1.695 V', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '50 V', 'ACV', '45 V, 100 kHz', None, None, '1.695 V', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '500 V', 'ACV', '500 V, 1 kHz', None, None, '2.25 V', 'V', {'fn': 'a'}),
    ('5', 'AC volts (U1252B, Shift mode)', 'ACV2', '1000 V', 'ACV', '1000 V, 1 kHz', None, None, '8.0 V', 'V', {'fn': 'a'}),
    # ---- step 6: DC mV (printed p. 156)
    ('6', 'DC mV', 'DCMV', '50 mV', 'DCV', '50 mV', None, '75 µV', '75 µV', 'mV', {'fn': 'b', 'prompt': NOTE_TEXT['b']}),
    ('6', 'DC mV', 'DCMV', '500 mV', 'DCV', '500 mV', None, '0.2 mV', '0.175 mV', 'mV', {}),
    ('6', 'DC mV', 'DCMV', '500 mV', 'DCV', '-500 mV', None, '0.2 mV', '0.175 mV', 'mV', {}),
    ('6', 'DC mV', 'DCMV', '1000 mV', 'DCV', '1000 mV', None, '0.8 mV', '0.75 mV', 'mV', {}),
    ('6', 'DC mV', 'DCMV', '1000 mV', 'DCV', '-1000 mV', None, '0.8 mV', '0.75 mV', 'mV', {}),
    # ---- step 7: AC mV (printed p. 157)
    ('7', 'AC mV', 'ACMV', '50 mV', 'ACV', '50 mV, 1 kHz', None, '0.34 mV', '0.24 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '50 mV', 'ACV', '50 mV, 10 kHz', None, '0.86 mV', '0.415 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '50 mV', 'ACV', '45 mV, 20 kHz', None, None, '1.695 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '50 mV', 'ACV', '50 mV, 30 kHz', None, '0.86 mV', None, 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '50 mV', 'ACV', '45 mV, 100 kHz', None, None, '1.695 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '500 mV, 45 Hz', None, '3.25 mV', '2.25 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '500 mV, 1 kHz', None, '3.25 mV', '2.25 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '500 mV, 10 kHz', None, '8.6 mV', '4.15 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '450 mV, 20 kHz', None, None, '16.95 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '500 mV, 30 kHz', None, '8.6 mV', None, 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '500 mV', 'ACV', '450 mV, 100 kHz', None, None, '16.95 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '1000 mV', 'ACV', '1000 mV, 1 kHz', None, '8.5 mV', '6.5 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '1000 mV', 'ACV', '1000 mV, 10 kHz', None, '47 mV', '11.5 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '1000 mV', 'ACV', '1000 mV, 20 kHz', None, None, '47.0 mV', 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '1000 mV', 'ACV', '1000 mV, 30 kHz', None, '47 mV', None, 'mV', {'fn': 'a'}),
    ('7', 'AC mV', 'ACMV', '1000 mV', 'ACV', '1000 mV, 100 kHz', None, None, '47.0 mV', 'mV', {'fn': 'a'}),
    # ---- step 8: ohms (printed pp. 157-158); 2-wire compensation is applied by the engine below 110 kOhm (the table's note [o] covers 500 Ohm, 5 kOhm, 50 kOhm)
    ('8', 'Ohms', 'OHM', '500 Ω', 'OHM', '500 Ω', None, '500 mΩ', '350 mΩ', 'Ω', {'fn': 'co', 'prompt': NOTE_TEXT['c']}),
    ('8', 'Ohms', 'OHM', '5 kΩ', 'OHM', '5 kΩ', None, '4.5 Ω', '3 Ω', 'kΩ', {'fn': 'co'}),
    ('8', 'Ohms', 'OHM', '50 kΩ', 'OHM', '50 kΩ', None, '45 Ω', '30 Ω', 'kΩ', {'fn': 'o'}),
    ('8', 'Ohms', 'OHM', '500 kΩ', 'OHM', '500 kΩ', None, '450 Ω', '300 Ω', 'kΩ', {}),
    ('8', 'Ohms', 'OHM', '5 MΩ', 'OHM', '5 MΩ', None, '10.5 kΩ', '8 kΩ', 'MΩ', {}),
    ('8', 'Ohms', 'OHM', '50 MΩ', 'OHM', '50 MΩ', None, '0.510 MΩ', '0.505 MΩ', 'MΩ', {'fn': 'd', 'settle': 10}),
    ('8', 'Ohms', 'OHM', '500 MΩ', 'OHM', '450 MΩ', None, None, '36.1 MΩ', 'MΩ', {'fn': 'd', 'settle': 10, 'extra': 'The table prints 450 MΩ (not the 500 MΩ range value) as the output.'}),
    # ---- step 9: conductance; step 10: diode (printed p. 158)
    ('9', 'Conductance', 'NS', '500 nS', 'COND', '50 nS', None, '0.7 nS', '0.6 nS', 'nS', {'fn': 'e', 'prompt': NOTE_TEXT['e'], 'settle': 10}),
    ('10', 'Diode', 'DIODE', 'Diode', 'DCV', '1 V', None, '1 mV', '1 mV', 'V', {}),
    # ---- step 11: frequency counter (U1252B only), sourced by the CALIBRATOR (owner answer 2026-10-27: not the 33250A); step 12 stays hand-set (33250A)
    ('11', 'Frequency counter', 'COUNTER', '999.99 kHz', 'FREQ', '0.6 V, 100 kHz', '100 kHz', None, '52 Hz', 'kHz',
     {'fn': 'fp', 'extra': 'Owner decision 2026-10-27: this point is sourced by the calibrator (5522A / 5560A, 600 mV rms at 100 kHz) instead of the Keysight 33250A named in Table 6-2; the limits are the printed ones. '
                           'The calibrator-frequency uncertainty rule applies.',
      'prompt': 'Meter (U1252B): turn the rotary switch to the Hz/diode position and press Shift for the frequency counter mode (999.99 kHz range). Shield the input from noise (note f). '
                'Connection: Ω V mV jack and COM, as for the other voltage points.'}),
    ('12', 'Frequency counter', 'COUNTER', '99.999 MHz', 'HANDSET', '1500 mVrms, 10 MHz (33250A)', '10 MHz', None, '5.2 kHz', 'MHz',
     {'fn': 'p', 'setup': 'Set the Keysight 33250A by hand: sine, 1500 mVrms, 10 MHz, to the meter (Ω V mV jack and COM; the connection and load are not stated in the table: UNVERIFIED) and press Output on. '
                           'Meter (U1252B): in the frequency counter mode press the Range button to go to frequency counter mode divide by 100 (99.999 MHz range). '
                           'Switch the 33250A output off after the reading.'}),
    # ---- step 13: capacitance (printed pp. 158-159)
    ('13', 'Capacitance', 'CAP', '10.000 nF', 'CAP', '10.000 nF', None, '0.108 nF', '0.108 nF', 'nF', {'fn': 'g', 'prompt': NOTE_TEXT['g'], 'settle': 10}),
    ('13', 'Capacitance', 'CAP', '100.00 nF', 'CAP', '100.00 nF', None, '1.05 nF', '1.05 nF', 'nF', {'settle': 10}),
    ('13', 'Capacitance', 'CAP', '1000.0 nF', 'CAP', '1000.0 nF', None, '10.5 nF', '10.5 nF', 'nF', {'settle': 10}),
    ('13', 'Capacitance', 'CAP', '10.000 µF', 'CAP', '10.000 µF', None, '0.105 µF', '0.105 µF', 'µF', {'settle': 10}),
    ('13', 'Capacitance', 'CAP', '100.00 µF', 'CAP', '100.00 µF', None, '1.05 µF', '1.05 µF', 'µF', {'settle': 15}),
    ('13', 'Capacitance', 'CAP', '1000.0 µF', 'CAP', '1000.0 µF', None, '10.5 µF', '10.5 µF', 'µF', {'settle': 15}),
    ('13', 'Capacitance', 'CAP', '10.00 mF', 'CAP', '10.00 mF', None, '0.105 mF', '0.105 mF', 'mF', {'settle': 20}),
    ('13', 'Capacitance', 'CAP', '100.00 mF', 'CAP', '10.00 mF', None, '0.4 mF', '0.4 mF', 'mF', {'settle': 20}),
    # ---- step 14: temperature (printed p. 159); both models
    ('14', 'Temperature', 'TEMP', '-200 °C until 1372 °C', 'TEMP', '0 °C', None, '3 °C', '3 °C', '°C', {'fn': 'hn', 'settle': 900}),
    ('14', 'Temperature', 'TEMP', '-200 °C until 1372 °C', 'TEMP', '100 °C', None, '3.3 °C', '3.3 °C', '°C', {'fn': 'hn', 'settle': 120}),
    # ---- steps 15 and 16: µA (printed p. 159)
    ('15', 'DC µA', 'UADC', '500 µA', 'DCI', '500 µA', None, '0.55 µA', '0.3 µA', 'µA', {'fn': 'i', 'prompt': NOTE_TEXT['i'], 'extra': NOTE_STEP15J}),
    ('15', 'DC µA', 'UADC', '5000 µA', 'DCI', '5000 µA', None, '5.5 µA', '3 µA', 'µA', {'fn': 'i'}),
    ('16', 'AC µA', 'UAAC', '500 µA', 'ACI', '500 µA, 1 kHz', None, '4.2 µA', '3.7 µA', 'µA', {'fn': 'a'}),
    ('16', 'AC µA', 'UAAC', '5000 µA', 'ACI', '5000 µA, 1 kHz', None, '42 µA', '37.0 µA', 'µA', {'fn': 'a'}),
    # ---- step 17: DC mA; step 18: AC mA (printed p. 160)
    ('17', 'DC mA', 'MADC', '50 mA', 'DCI', '50 mA', None, '0.105 mA', '80 µA', 'mA', {'fn': 'i', 'prompt': NOTE_TEXT['i']}),
    ('17', 'DC mA', 'MADC', '440 mA', 'DCI', '400 mA', None, '0.85 mA', '0.65 mA', 'mA', {'fn': 'i'}),
    ('18', 'AC mA', 'MAAC', '50 mA', 'ACI', '50 mA, 20 kHz', None, '0.42 mA', '0.37 mA', 'mA', {'fn': 'a'}),
    ('18', 'AC mA', 'MAAC', '440 mA', 'ACI', '400 mA, 45 Hz', None, '3.4 mA', '3.0 mA', 'mA', {'fn': 'a'}),
    ('18', 'AC mA', 'MAAC', '440 mA', 'ACI', '400 mA, 1 kHz', None, '3.4 mA', '3.0 mA', 'mA', {'fn': 'a'}),
    # ---- the two unnumbered rows under the Caution band: DC amps
    ('17*', 'DC amps', 'ADC', '5 A', 'DCI', '5 A', None, '16 mA', '16 mA', 'A', {'fn': 'k', 'extra': NOTE_NOSTEP, 'settle': 5}),
    ('17*', 'DC amps', 'ADC', '10 A', 'DCI', '10 A', None, '40 mA', '35 mA', 'A', {'fn': 'jk', 'extra': NOTE_NOSTEP, 'settle': 5}),
    # ---- step 19: AC amps (printed p. 160)
    ('19', 'AC amps', 'AAC', '5 A', 'ACI', '5 A, 1 kHz', None, '42 mA', '37 mA', 'A', {'settle': 5}),
    ('19', 'AC amps', 'AAC', '10 A', 'ACI', '10 A, 1 kHz', None, '100 mA', '90 mA', 'A', {'fn': 'l', 'settle': 5}),
    # ---- step 20: square-wave OUTPUT of the U1252B, measured with a Keysight 53131A (frequency / duty) and a 34410A (amplitude); printed p. 160
    ('20', 'Square wave output', 'OUT', '120 Hz @ 50%', 'HANDSET', '120 Hz @ 50% (53131A)', '120 Hz', None, '26 mHz', 'Hz',
     {'setup': 'U1252B: turn the rotary switch to the OUT ms (square wave output) position and set the output to 120 Hz at 50 % duty (the Range column). Connect the meter OUT jack and COM to the Keysight 53131A '
               'frequency counter (Table 6-2 header "Use 53131A"; the connection is not drawn: UNVERIFIED). Type the 53131A frequency reading.'}),
    ('20', 'Square wave output', 'OUT', '4800 Hz @ 50%', 'HANDSET', '4800 Hz @ 50% (53131A)', '4800 Hz', None, '260 mHz', 'Hz',
     {'setup': 'U1252B: in the OUT ms position set the output to 4800 Hz at 50 % duty. Keep the meter OUT jack and COM on the Keysight 53131A. Type the 53131A frequency reading.'}),
    ('20', 'Square wave output', 'OUT', '100 Hz @ 50%', 'HANDSET', '100 Hz @ 50% (53131A)', '50 %', None, '0.398 %', '%',
     {'fn': 'm', 'setup': 'U1252B: in the OUT ms position set the output to 100 Hz at 50 % duty (Duty Cycle). Keep the meter OUT jack and COM on the Keysight 53131A, measuring duty cycle (positive duty). Type the 53131A duty-cycle reading.'}),
    ('20', 'Square wave output', 'OUT', '100 Hz @ 25%', 'HANDSET', '100 Hz @ 25% (53131A)', '25 %', None, '0.398 %', '%',
     {'fn': 'm', 'setup': 'U1252B: set the OUT ms output to 100 Hz at 25 % duty. Type the 53131A duty-cycle reading.'}),
    ('20', 'Square wave output', 'OUT', '100 Hz @ 75%', 'HANDSET', '100 Hz @ 75% (53131A)', '75 %', None, '0.398 %', '%',
     {'fn': 'm', 'setup': 'U1252B: set the OUT ms output to 100 Hz at 75 % duty. Type the 53131A duty-cycle reading.'}),
    ('20', 'Square wave output', 'OUT', '4800 Hz @ 99.609%', 'HANDSET', '4800 Hz @ 99.609% (34410A)', '2.8 V', None, '0.2 V', 'V',
     {'nominal_unverified': True,
      'setup': 'U1252B: set the OUT ms output to 4800 Hz at 99.609 % duty (Amplitude). Connect the meter OUT jack and COM to the Keysight 34410A (Table 6-2 header "Use 34410A"; Table 6-1 names a 34401A; '
               'the connection and the 34410A function are not stated: DC volts is assumed, UNVERIFIED). Type the amplitude reading in volts.'}),
]

# Functional checks (Basic Operating Test, printed pp. 149-151): no limits, no uncertainty, yes / no.  (title, setup, question, models, page)
FUNC = [
    ('Backlit test', 'Backlit test (printed p. 149): press the Bat button to test the backlight. It will momentarily toggle the backlight ON and OFF.',
     'The backlight toggled ON and OFF.', BOTH, 'p. 149'),
    ('Display test', 'Testing the display (printed p. 149): press the Hold button and turn on the meter to view all segments of the display. Compare the display with the manual\'s Figure 6-1 '
                     '(the text says Table 6-1, which is the equipment table: misprint).', 'All display segments are shown, as in Figure 6-1.', BOTH, 'p. 149'),
    ('Current terminal test', 'Current terminal test (printed p. 150): the beep function must not be disabled in setup. Insert a test lead into the A terminal with the rotary switch NOT set to the mA·A function. '
                              'The meter sounds an alert beep and the primary display flashes "A-Err" until the lead is removed from the A terminal (Figure 6-2).',
     'The meter beeped and the primary display flashed "A-Err" until the lead was removed.', BOTH, 'p. 150'),
]

# CHECKS: published accuracy, recomputed from the DATA SHEET formulas as read from an UNVERIFIED second-hand extraction: ('section', range, output) -> {model: (percent, counts)}; the display step is that of the range
CHECKS = {
    ('DC mV', '50 mV', '50 mV'): {'U1251B': ('0.05', 50), 'U1252B': ('0.05', 50)},
    ('DC mV', '500 mV', '500 mV'): {'U1251B': ('0.03', 5), 'U1252B': ('0.025', 5)},
    ('DC mV', '500 mV', '-500 mV'): {'U1251B': ('0.03', 5), 'U1252B': ('0.025', 5)},
    ('DC mV', '1000 mV', '1000 mV'): {'U1251B': ('0.03', 5), 'U1252B': ('0.025', 5)},
    ('DC mV', '1000 mV', '-1000 mV'): {'U1251B': ('0.03', 5), 'U1252B': ('0.025', 5)},
    ('Ohms', '500 Ω', '500 Ω'): {'U1251B': ('0.08', 10), 'U1252B': ('0.05', 10)},
    ('Ohms', '5 kΩ', '5 kΩ'): {'U1251B': ('0.08', 5), 'U1252B': ('0.05', 5)},
    ('Ohms', '5 MΩ', '5 MΩ'): {'U1251B': ('0.2', 5), 'U1252B': ('0.15', 5)},
    ('Ohms', '50 MΩ', '50 MΩ'): {'U1251B': ('1', 10), 'U1252B': ('1', 5)},
    ('Ohms', '500 MΩ', '450 MΩ'): {'U1252B': ('8', 10)},
    ('Conductance', '500 nS', '50 nS'): {'U1251B': ('1', 20), 'U1252B': ('1', 10)},
    ('DC µA', '500 µA', '500 µA'): {'U1251B': ('0.1', 5), 'U1252B': ('0.05', 5)},
    ('DC µA', '5000 µA', '5000 µA'): {'U1251B': ('0.1', 5), 'U1252B': ('0.05', 5)},
    ('DC mA', '50 mA', '50 mA'): {'U1251B': ('0.2', 5), 'U1252B': ('0.15', 5)},
    ('DC mA', '440 mA', '400 mA'): {'U1251B': ('0.2', 5), 'U1252B': ('0.15', 5)},
    ('DC amps', '5 A', '5 A'): {'U1251B': ('0.3', 10), 'U1252B': ('0.3', 10)},
    ('DC amps', '10 A', '10 A'): {'U1252B': ('0.3', 5)},
    ('Capacitance', '10.000 nF', '10.000 nF'): {'U1251B': ('1', 8), 'U1252B': ('1', 8)},
    ('Capacitance', '100.00 nF', '100.00 nF'): {'U1251B': ('1', 5), 'U1252B': ('1', 5)},
    ('Temperature', '-200 °C until 1372 °C', '0 °C'): {'U1251B': ('0.3', 30), 'U1252B': ('0.3', 30)},
    ('Temperature', '-200 °C until 1372 °C', '100 °C'): {'U1251B': ('0.3', 30), 'U1252B': ('0.3', 30)},
}
# display step used by the check (one count), in the DISPLAY unit of the row; temperature: 0.1 degC
CHECK_RES = {('DC mV', '50 mV'): '0.001', ('DC mV', '500 mV'): '0.01', ('DC mV', '1000 mV'): '0.1', ('Ohms', '500 Ω'): '0.01', ('Ohms', '5 kΩ'): '0.0001', ('Ohms', '5 MΩ'): '0.0001',
             ('Ohms', '50 MΩ'): '0.001', ('Ohms', '500 MΩ'): '0.01', ('Conductance', '500 nS'): '0.01', ('DC µA', '500 µA'): '0.01', ('DC µA', '5000 µA'): '0.1', ('DC mA', '50 mA'): '0.001',
             ('DC mA', '440 mA'): '0.01', ('DC amps', '5 A'): '0.0001', ('DC amps', '10 A'): '0.001', ('Capacitance', '10.000 nF'): '0.001', ('Capacitance', '100.00 nF'): '0.01',
             ('Temperature', '-200 °C until 1372 °C'): '0.1'}
# rows whose printed limit differs from the recomputed data sheet figure (key (section, range, output, model) -> verdict); anything else that differs aborts the build
EXPECTED_DIFFERENT = {}
CHECK_NOTE = ('CHECK (UNVERIFIED second-hand data sheet): the printed error equals the data sheet accuracy {pct} % of reading + {counts} counts ({half} {unit}).')


def split_output(text):
    """'4.5 V, 10 kHz' -> (value Decimal base, base unit, frequency Hz or None) from a printed calibrator output (also '5.0 Vpp, 50 Hz, 50 %')."""
    parts = [t.strip() for t in text.split(',')]
    value, base = q(parts[0].replace('Vpp', 'V').replace('Vrms', 'V'))
    freq = q(parts[1])[0] if len(parts) > 1 and 'Hz' in parts[1] else None
    return value, base, freq


def decode_error(text):
    return q(text)


def build_rows():
    """The spec steps (one per printed row and model group), the problems found and the cross-check records."""
    steps, problems, flagged = [], [], []
    n = 0
    for key, section, sw, rng, kind, out, nom_text, e51, e52, du, ex in ROWS:
        groups = []                                       # [(models, error text)]
        if e51 is not None and e51 == e52:
            groups.append((BOTH, e51))
        else:
            if e51 is not None:
                groups.append((['U1251B'], e51))
            if e52 is not None:
                groups.append((['U1252B'], e52))
        for models, err in groups:
            n += 1
            factor, base = display_unit(du)
            out_value, out_base, out_freq = split_output(out) if kind != 'HANDSET' else (None, None, None)
            if kind == 'HANDSET':
                nominal, nbase = q(nom_text)
            elif nom_text is not None:
                nominal, nbase = q(nom_text)
            else:
                nominal, nbase = out_value, out_base
            if nbase != base:
                problems.append(f'row {key} {out}: nominal base {nbase} differs from the display unit base {base}')
            error, ebase = q(err)
            if ebase != base:
                problems.append(f'row {key} {out}: error base {ebase} differs from the display unit base {base}')
            low_b, high_b = nominal - error, nominal + error
            dec = max(needed_decimals(low_b / factor), needed_decimals(high_b / factor), needed_decimals(nominal / factor))
            if kind in ('FREQ',):
                dec = max(dec, 4)                          # the range text '9.9999 kHz'
            if kind == 'DUTY':
                dec = max(dec, 3)
            m = re.match(r'^\s*\d+\.(\d+)\s*(?:nF|µF|mF|kHz|MHz)\s*$', rng)
            if m:
                dec = max(dec, len(m.group(1)))
            dec = max(dec, BASE_DEC.get((du, rng), 0))
            low, high = fmt(low_b / factor, dec), fmt(high_b / factor, dec)
            if (D(low) + D(high)) / 2 != nominal / factor:
                problems.append(f'row {key} {out}: limits {low} .. {high} not symmetric about {nominal / factor}')
            ref = 'T6-2 unnumbered A rows' if key == '17*' else f'T6-2 #{key}'
            step = dict(table=TABLE, step=n, id=f'{TABLE}-{n}', section=section, switch=SW[sw] if sw in SW else sw, range=rng, models=list(models), test='numeric',
                        display_unit=du, factor=clean(factor), base_unit=base, low=low, high=high, nominal=clean(nominal), ref=ref)
            notes = [f'Table 6-2 (printed pp. 155-160): "Error from nominal 1 year" ±{err} for the {" and ".join(models)}.']
            if kind == 'HANDSET':
                step['kind'] = 'NONE'
                step['setup'] = ex['setup']
                step['group'] = 'NONE'
                step['no_uncertainty'] = True
                step['report_desc'] = f'{section}, {out}'
                notes.append('Set by hand: the standard is not a calibrator the suite drives. NO UNCERTAINTY is printed for this point (the 33250A / 53131A / 34410A specifications are not held by the suite): listed in the report.')
                step['switch'] = f'{section}  (set by hand: see the set-up window)'
                if ex.get('nominal_unverified'):
                    notes.append('The table prints only the error (±0.2 V) and no nominal: 2.8 V is from the manufacturer\'s data sheet (not this manual): UNVERIFIED. The limits 2.6 V to 3.0 V follow from it.')
            else:
                kd = {'FREQ': 'ACV', 'COND': 'OHM'}.get(kind, kind)
                step['kind'] = kd
                if kind == 'DUTY':
                    step['kind'] = 'DUTY'
                    step['applied'] = dict(value=5.0, frequency=50.0, duty=50.0, offset=0.0)
                    notes.append('Calibrator output (5520A column): 5.0 Vpp square wave at 50 Hz, 50 % duty. Both calibrators are put back to a sine wave after the point. No uncertainty: the suite holds no specification for a square-wave output (listed).')
                elif kind == 'COND':
                    step['applied'] = dict(value=clean(D(1) / out_value * 1), frequency=None)
                    step['report_desc'] = f'{rng} range (20 MΩ applied = 50 nS)'
                    step['unc_unit'] = 'ohm'
                    notes.append('50 nS is sourced as 20 MΩ (1 / 50 nS), the calibrator resistance output. The Uncertainty column carries the calibrator\'s uncertainty at 20 MΩ in ohms; TAR / TUR are blank (siemens vs ohms).')
                elif kind == 'FREQ':
                    step['applied'] = dict(value=clean(out_value), frequency=clean(out_freq))
                    step['unc_kind'] = 'FREQ'
                    step['report_desc'] = f'{rng} range, {out}'
                    step['no_freq_suffix'] = True
                else:
                    step['applied'] = dict(value=clean(out_value), frequency=clean(out_freq) if out_freq is not None else None)
                    if kd in ('DCV', 'DCI'):
                        step['applied']['frequency'] = None
                step['group'] = {'ACV': 'VOHM', 'DCV': 'VOHM', 'OHM': 'VOHM', 'CAP': 'VOHM', 'DUTY': 'VOHM', 'TEMP': 'TEMP', 'DCI': 'UAMP', 'ACI': 'UAMP'}[step['kind']]
                if step['kind'] in ('DCI', 'ACI') and base == 'A' and abs(out_value) >= 1:
                    step['group'] = 'AMP10'
            for letter in ex.get('fn', ''):
                notes.append(NOTE_TEXT[letter])
            if ex.get('extra'):
                notes.append(ex['extra'])
            if ex.get('prompt'):
                step['prompt'] = 'Before the first reading of this function: ' + ex['prompt']
            if kind != 'HANDSET':
                step['settle'] = 0                       # owner decision 2026-10-27: no program wait (including temperature); the technician enters the reading once it is stable
                notes.append('No settle wait is programmed (owner decision 2026-10-27): enter the reading once it is stable' + (f'; the manual-based wait of {ex["settle"]} s was dropped.' if ex.get('settle') else '.'))
            if kind == 'TEMP':
                step['base_unit'] = 'C'
            if section == 'Ohms' and out_value is not None and out_value >= 110000:
                notes.append('Above 110 kΩ the calibrator does not allow 2-wire compensation: it stays off and the log says so.')
            notes.append(NOTE_RES)
            notes.append(NOTE_CAL)
            step['tol_text'] = f'Table 6-2: {low} to {high} {du} (±{err} from the nominal, 1 year)'
            step['note'] = ' '.join(notes)
            # cross-check
            c = CHECKS.get((section, rng, out))
            if c:
                for model in models:
                    if model not in c:
                        continue
                    pct, counts = c[model]
                    res = D(CHECK_RES[(section, rng)])
                    # the data sheet's counts are counts of the display step in the display unit; the nominal in the display unit
                    half = D(pct) / 100 * abs(nominal / factor) + counts * res
                    printed = error / factor
                    if half != printed:
                        verdict = 'differs'
                        flagged.append((step['id'], model, section, rng, out, str(printed.normalize()), str(half.normalize()), verdict))
                        step['note'] += f' CHECK - DISCREPANCY (printed limit NOT changed): the data sheet formula ({pct} % + {counts} counts, UNVERIFIED extraction) gives ±{half.normalize():f} {du}, the table prints ±{printed.normalize():f} {du}.'
                        step.setdefault('check', {})[model] = dict(verdict=verdict, printed=format(printed.normalize(), 'f'), data_sheet=format(half.normalize(), 'f'))
                    else:
                        step.setdefault('check', {})[model] = dict(verdict='same', printed=format(printed.normalize(), 'f'), data_sheet=format(half.normalize(), 'f'))
            steps.append(step)
    return steps, problems, flagged


def build_functional():
    out = []
    for k, (title, setup, question, models, page) in enumerate(FUNC, 1):
        out.append(dict(table='F', step=k, id=f'F-{k}', section='Functional checks', switch=title, range='', models=list(models), kind='VISUAL', test='visual', title=title, setup=setup,
                        question=question, setup_key='NONE', ref=f'{page} functional check',
                        note=f'Basic Operating Test ({page}); no calibrator output, no limits, no uncertainty (yes / no). Owner rule 2026-10-27: included.'))
    return out


TEMP_SETUP = ('Meter: the temperature / capacitance position, Shift for the temperature mode, °C, internal reference (note [h]). K-type thermocouple extension (miniature connector on both ends) from the calibrator TC output '
              'to the meter through a TC-to-banana adapter (Ω V mV and COM jacks). The calibrator also on its internal reference. The meter must have been in a controlled environment for at least 1 hour (ambient stable '
              'within ±1 °C, away from any ventilation exit), do not touch the thermocouple lead after connecting it, and allow the connection to stabilise for at least another 15 minutes (note [n]).')
GROUPS = {
    'TEMP': dict(title='Connect the thermocouple', summary=TEMP_SETUP,
                 steps=[['Standby', 'The calibrator is in STANDBY while you connect.'],
                        ['Meter', 'Turn the rotary switch to the temperature / capacitance position and press Shift for the temperature mode (°C). Set the multimeter and the calibrator to internal reference (note [h]).'],
                        ['Connect', 'K-type thermocouple extension (miniature thermocouple connector on both ends) from the calibrator TC output to the multimeter via a TC-to-banana adapter (Ω V mV and COM jacks).'],
                        ['Settle', 'Meter in a controlled environment for at least 1 hour, ambient stable within ±1 °C, away from ventilation; do not touch the thermocouple lead; allow another 15 minutes after connecting (note [n]).']],
                 caution='The error limit does not include the thermocouple extension (note [h]).', diagram='diagrams/hook_u1251b_TEMP.png'),
}

SOURCE_NOTE = (
    'Table 6-2 "Verification Test" of the Keysight U1251B and U1252B User\'s and Service Guide (printed pp. 155-160, notes [a]-[p] pp. 160-161): the column "Error from nominal 1 year" is the only limit set '
    '(no 90 day / 2 year columns). Limits are the plus / minus error around the nominal in Decimal; two models with different errors are two steps of the same row. '
    'The table names a Fluke 5520A (Table 6-1, p. 148); the program drives a Fluke 5522A or 5560A, or you set the calibrator by hand. The frequency counter point 12 (Keysight 33250A) and the '
    'square wave output points (step 20; Keysight 53131A and 34410A) are set by hand and carry no uncertainty. The meter has no documented remote command set: you type the display reading. '
    'The table has no display resolutions: typed readings are padded to the decimals of Table 6-4 for the range. The printed table\'s misprints and unreadable cells are flagged in the point notes. '
    'The calibration adjustment (printed pp. 164-175) is not part of this procedure.')
REPORT_NOTE = ('Limits are those of the manufacturer\'s Table 6-2 "Error from nominal 1 year" (Keysight U1251B and U1252B User\'s and Service Guide, printed pp. 155-160), unchanged. '
               'The frequency counter and square wave output points are set and measured with other instruments by hand and carry no uncertainty.')


def build_spec():
    steps, problems, flagged = build_rows()
    steps += build_functional()
    counts = {m: sum(1 for s in steps if m in s['models']) for m in MODELS}
    table_counts = {m: sum(1 for s in steps if m in s['models'] and s['table'] == TABLE) for m in MODELS}
    if table_counts != EXPECTED_TABLE:
        problems.append(f'Table 6-2 points per model {table_counts} differ from {EXPECTED_TABLE}')
    if problems:
        raise SystemExit('Problems:\n  ' + '\n  '.join(problems))
    unexpected = [f for f in flagged if (f[2], f[3], f[4], f[1]) not in EXPECTED_DIFFERENT and (f[2], f[3], f[4], f[1]) not in EXPECTED_FLAGS]
    if unexpected:
        raise SystemExit('Cross-check differences not expected (re-read the table): ' + '; '.join(map(str, unexpected)))
    spec = dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='u1251b', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, two_wire_comp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='149-151 (Basic Operating Test), 152 (Test Considerations), 154-161 (Performance Verification Tests, Table 6-2 pp. 155-160, notes pp. 160-161); equipment Table 6-1 p. 148; Table 1-1 p. 30; Table 1-10 p. 47',
                    cite='Keysight U1251B and U1252B User\'s and Service Guide, Table 6-2 Verification Test, printed pp. 155-160 (Error from nominal, 1 year)',
                    limits='Manufacturer limits, Table 6-2 "Error from nominal 1 year", as printed',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={'U1251B': dict(name='Keysight U1251B', brand='Keysight', model_note='Keysight U1251B handheld digital multimeter (4.5 digit, 50 000 counts): Table 6-2 plus the functional checks'),
                'U1252B': dict(name='Keysight U1252B', brand='Keysight', model_note='Keysight U1252B handheld digital multimeter (frequency counter, square wave output, AC+DC): Table 6-2 plus the functional checks')},
        groups=GROUPS, steps=steps)
    for m in MODELS:
        spec['models'][m]['model_note'] += f' ({counts[m]} points).'
    return spec, flagged


EXPECTED_TABLE = {'U1251B': 60, 'U1252B': 84}    # counted by hand from the rendered Table 6-2 (N/A cells removed): 60 + 3 functional checks = 63; 84 + 3 = 87
EXPECTED_FLAGS = {}


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
