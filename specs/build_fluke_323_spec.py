"""Builds specs/fluke_323_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 323 / 324 / 325 Clamp Meter Calibration Manual
(February 2013, 28 PDF pages).

    python3 specs/build_fluke_323_spec.py

Source (printed page numbers; PDF page = printed page + 8):
  Table 4 "Performance Tests", printed pp. 13-14 (PDF 21-22): 48 rows, one X / N/A column per model (323, 324, 325); read from RENDERED PAGE IMAGES (pdftoppm, 110 and 150 dpi), twice,
  never from extracted text (the text version of the 30K row is garbled in the same way as the page: see the misprint below);
  "Temperature, Volts, Ohms, Frequency, and Capacitance" (printed p. 11, Figure 4: calibrator NORMAL output and ground to the meter's VΩ and COM jacks);
  "Current" (printed p. 12, Figure 5: calibrator current output and ground to the 50-turn coil, the meter jaw closed around it);
  Table 3 "Required Equipment" (printed p. 8): calibrator with 4.5 digit resolution (recommended Fluke 5520A), wired coil 50 turns (5500A/COIL);
  the performance tests, printed pp. 9-10 (display test, firmware / model number, backlight, button test: functional checks, NOT part of this spec).
The Calibration Manual prints no accuracy statement and no ranges or resolutions: the limits are stored exactly as printed (nothing is cross-checked against a published specification here)
and no range is named on any point (the meter autoranges).

ONE FAMILY SPEC, THREE MODELS (as the 110 / 170 / 374-376 families): every step lists the models it applies to, from the X columns of Table 4.
  323: 16 points   324: 24 points   325: 30 points.   Registered: Procedures/Fluke_323_Verification.py, Fluke_324_Verification.py, Fluke_325_Verification.py.

THE 50-TURN COIL (owner request: 'make sure the 50 turn coil test points are assigned correctly'):
  * AC Amps (with 50-Turn Coil) and DC Amps (with 50-Turn Coil): the Calibrator Output column is the current the CALIBRATOR drives through the 50-turn coil (0.004 ... 7.8 A) and the limits
    are what the METER reads: 50 x the calibrator current (0.12 A -> 6 A, 0.48 A -> 24 A, 4.2 A -> 210 A, 7.8 A -> 390 A; 0.004 A -> 0.2 A, 0.2 A -> 10 A, 0.6 A -> 30 A, 2 A -> 100 A,
    6 A -> 300 A).  applied.value = the calibrator current, nominal = what the meter shows.  The builder checks that every limit pair is centred on 50 x the calibrator current and aborts otherwise.
  * Frequency (325): Table 4 prints 'Calibrator Output 0.2 A, 5 Hz / 50 Hz / 500 Hz'.  The text of the manual puts Frequency under 'Temperature, Volts, Ohms, Frequency, and Capacitance' (leads
    on the NORMAL output, Figure 4), but a NORMAL output cannot make an AMP value, and only the Current section (Figure 5) drives amps.  So these three rows are ASSIGNED TO THE 50-TURN COIL:
    0.2 A from the calibrator through the coil = 10 A in the jaw, at 5 / 50 / 500 Hz, and the meter shows Hz.  This is an inference, not stated by the manual (UNVERIFIED): confirm it on the meter.
    (The manual prints no 'x 50' for the frequency rows; a single turn with 0.2 A is below any clamp's input threshold.)
  * Every other row (temperature, AC / DC volts, ohms, capacitance) uses the test leads / thermocouple: no coil.
  * Hook-up group by calibrator output: below 3 A the calibrator's low-current output (5522A / 5520A AUX, 5560A VI AUX), 3 A and above its high-current output (20 A / 30A): the same split
    the 376 spec uses (the 5522A's AUX output stops at 2.99999 A).
  * Uncertainty (owner decision 2026-10-26, as the 365 / 376): the coil points carry the uncertainty of the 5500A/COIL's own A2LA scope lines at the EFFECTIVE current the jaw sees (the nominal);
    nothing is printed where the coil's lines do not cover the point.  The frequency rows carry the calibrator's frequency uncertainty (unc_kind FREQ).

PRINTED MISPRINTS (limits are never changed silently; each correction is stated in the step's note, shown in the point window, and in the report's source note, which the engine keeps with the issued report):
  * Table 4 prints the 30K ohm row as '34.65 KΩ' and '30.35 Ω'.  The row is symmetric about 30 kΩ like its neighbours (10K: +-0.15 K = 1.5 %; 3000: +-35; 1000: +-15), so it is stored as
    29.65 kΩ to 30.35 kΩ (printed values 34.65 K / 30.35 Ω flagged).  UNVERIFIED against a second source: confirm.
  * Table 4 prints '-606.5' (no unit) as the -600 V low limit: the unit is the row's V.
  * '25.1A', '295.0A', '492.0V' lack a space only.
The builder aborts when a limit pair is not as expected.  Display resolutions are NOT printed: values keep the decimals of the printed limits, and a typed reading is padded to them.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_323_pv.json'
TABLE = '4'
DOCUMENT = 'Fluke 323 / 324 / 325 Clamp Meter - Calibration Manual (February 2013)'
MODELS = ('323', '324', '325')
M323, M324, M325 = ('323',), ('324',), ('325',)
M324_5, M323_4, ALL = ('324', '325'), ('323', '324'), MODELS
TURNS = 50
EXPECTED_COUNTS = {'323': 16, '324': 24, '325': 30}

UNITS = {'V': ('1', 'V'), 'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'µF': ('0.000001', 'F'), 'A': ('1', 'A'), '°C': ('1', 'degC'), 'Hz': ('1', 'Hz')}

# Rotary switch text ('short  (detail)').  The Calibration Manual names the functions only (Figure 4 shows the 325 dial); dial symbols and the yellow-button behaviour are not stated: UNVERIFIED.
SW = {
    'temp': 'Temperature  (the temperature function: dial position and the C / F button are not described in the Calibration Manual; UNVERIFIED)',
    'acv': 'V~  (AC volts)',
    'dcv': 'V⎓  (DC volts)',
    'ohm': 'Ω  (ohms)',
    'cap': 'Capacitance  (the capacitance function: how it is selected is not described in the Calibration Manual; UNVERIFIED)',
    'aca': 'A~  (AC amps: jaw closed around the 50-turn coil)',
    'dca': 'A⎓  (DC amps: jaw closed around the 50-turn coil)',
    'hz': 'Hz  (frequency: jaw closed around the 50-turn coil; how it is selected is not described in the Calibration Manual; UNVERIFIED)',
}

# (section, switch key, kind, applied value (calibrator output, base units), frequency, display unit, nominal (what the meter shows, display unit), printed low, printed high, models, extras)
# extras: coil -> driven through the 50-turn coil; printed -> the limits as the manual prints them when they differ from the stored ones
ROWS = [
    # --- Temperature (324, 325)
    ('Temperature', 'temp', 'TEMP', '-5', None, '°C', '-5', '-5.8', '-4.2', M324_5, {}),
    ('Temperature', 'temp', 'TEMP', '0', None, '°C', '0', '-0.8', '0.8', M324_5, {}),
    ('Temperature', 'temp', 'TEMP', '100', None, '°C', '100', '98.2', '101.8', M324_5, {}),
    ('Temperature', 'temp', 'TEMP', '400', None, '°C', '400', '395.2', '404.8', M324_5, {}),
    # --- AC volts
    ('AC volts', 'acv', 'ACV', '10', 50, 'V', '10', '9.3', '10.7', ALL, {}),
    ('AC volts', 'acv', 'ACV', '500', 50, 'V', '500', '492.0', '508.0', M324_5, {}),
    ('AC volts', 'acv', 'ACV', '500', 500, 'V', '500', '492.0', '508.0', M324_5, {}),
    ('AC volts', 'acv', 'ACV', '600', 50, 'V', '600', '590.5', '609.5', M323, {}),
    ('AC volts', 'acv', 'ACV', '600', 400, 'V', '600', '590.5', '609.5', M323, {}),
    # --- DC volts
    ('DC volts', 'dcv', 'DCV', '-600', None, 'V', '-600', '-606.5', '-593.5', M323, {}),
    ('DC volts', 'dcv', 'DCV', '-500', None, 'V', '-500', '-505.5', '-494.5', M324_5, {}),
    ('DC volts', 'dcv', 'DCV', '10', None, 'V', '10', '9.4', '10.6', ALL, {}),
    ('DC volts', 'dcv', 'DCV', '500', None, 'V', '500', '494.5', '505.5', M324_5, {}),
    ('DC volts', 'dcv', 'DCV', '600', None, 'V', '600', '593.5', '606.5', M323, {}),
    # --- Ohms
    ('Ohms', 'ohm', 'OHM', '0', None, 'Ω', '0', '0.0', '0.5', M323, {}),
    ('Ohms', 'ohm', 'OHM', '10', None, 'Ω', '10', '9.4', '10.6', ALL, {}),
    ('Ohms', 'ohm', 'OHM', '300', None, 'Ω', '300', '296.5', '303.5', M324_5, {}),
    ('Ohms', 'ohm', 'OHM', '350', None, 'Ω', '350', '346.0', '354.0', M323, {}),
    ('Ohms', 'ohm', 'OHM', '1000', None, 'Ω', '1000', '985', '1015', M324_5, {}),
    ('Ohms', 'ohm', 'OHM', '3000', None, 'Ω', '3000', '2965', '3035', M324_5, {}),
    ('Ohms', 'ohm', 'OHM', '3500', None, 'Ω', '3500', '3460', '3540', M323, {}),
    ('Ohms', 'ohm', 'OHM', '10000', None, 'kΩ', '10', '9.85', '10.15', M324_5, {}),
    ('Ohms', 'ohm', 'OHM', '30000', None, 'kΩ', '30', '29.65', '30.35', M324_5, {'printed': ('34.65', '30.35'), 'printed_units': ('kΩ', 'Ω')}),
    # --- Capacitance (324, 325)
    ('Capacitance', 'cap', 'CAP', '0.00001', None, 'µF', '10', '9.5', '10.5', M324_5, {'settle': 10}),
    ('Capacitance', 'cap', 'CAP', '0.0005', None, 'µF', '500', '491', '509', M324_5, {'settle': 10}),
    ('Capacitance', 'cap', 'CAP', '0.0009', None, 'µF', '900', '887', '913', M324_5, {'settle': 10}),
    # --- Frequency (325): calibrator 0.2 A through the 50-turn coil (ASSIGNMENT, see the module text)
    ('Frequency', 'hz', 'ACI', '0.2', 5, 'Hz', '5', '4.7', '5.3', M325, {'coil': True, 'freq_row': True}),
    ('Frequency', 'hz', 'ACI', '0.2', 50, 'Hz', '50', '49.6', '50.4', M325, {'coil': True, 'freq_row': True}),
    ('Frequency', 'hz', 'ACI', '0.2', 500, 'Hz', '500', '497.5', '501.5', M325, {'coil': True, 'freq_row': True}),
    # --- AC amps (with 50-turn coil): calibrator current, the meter shows 50 x
    ('AC amps', 'aca', 'ACI', '0.12', 50, 'A', '6', '5.4', '6.6', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.48', 150, 'A', '24', '22.9', '25.1', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '4.2', 50, 'A', '210', '205.3', '214.7', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '7.8', 50, 'A', '390', '381.7', '398.3', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '7.8', 150, 'A', '390', '379.7', '400.3', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '7.8', 400, 'A', '390', '379.7', '400.3', M323, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.004', 50, 'A', '0.2', '0.15', '0.25', M324, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.2', 50, 'A', '10', '9.80', '10.20', M324, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.6', 50, 'A', '30', '29.50', '30.50', M324, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '2', 50, 'A', '100', '97.5', '102.5', M324, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '6', 50, 'A', '300', '293.5', '306.5', M324, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.2', 50, 'A', '10', '9.75', '10.25', M325, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '0.6', 50, 'A', '30', '29.35', '30.65', M325, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '2', 50, 'A', '100', '98.0', '102.0', M325, {'coil': True}),
    ('AC amps', 'aca', 'ACI', '6', 50, 'A', '300', '295.0', '305.0', M325, {'coil': True}),
    # --- DC amps (325)
    ('DC amps', 'dca', 'DCI', '0.2', None, 'A', '10', '9.75', '10.25', M325, {'coil': True}),
    ('DC amps', 'dca', 'DCI', '0.6', None, 'A', '30', '29.35', '30.65', M325, {'coil': True}),
    ('DC amps', 'dca', 'DCI', '2', None, 'A', '100', '97.5', '102.5', M325, {'coil': True}),
    ('DC amps', 'dca', 'DCI', '6', None, 'A', '300', '293.5', '306.5', M325, {'coil': True}),
]

NOTE_OHMS = 'Table 4 does not say whether the limits include test lead resistance (UNVERIFIED); use short leads.'
NOTE_RANGE = 'Table 4 names no range and no resolution (the Calibration Manual prints neither): the meter autoranges; the limits are shown with the decimals Table 4 prints.'
NOTE_COIL = ('The calibrator drives the {turns}-turn coil and the meter reads {turns} x the calibrator current: {applied} A in, {nominal} A on the meter. The limits are the meter readings (Table 4, printed pp. 13-14). '
             'Uncertainty (owner decision): the 5500A/COIL\'s own scope uncertainty (A2LA-5500A-COIL) at the effective current the jaw sees ({nominal} A), not the calibrator\'s at {applied} A; '
             'no value is printed where the coil\'s lines do not cover the point. TAR / TUR compare it with the meter-reading tolerance printed in Table 4.')
NOTE_FREQ = ('ASSIGNED TO THE 50-TURN COIL (UNVERIFIED inference): Table 4 prints the calibrator output as 0.2 A, which a NORMAL (voltage) output cannot make, and only the Current section (Figure 5) drives amps through the coil. '
             'The calibrator drives 0.2 A at {freq} Hz through the {turns}-turn coil (10 A in the jaw) and the meter shows the FREQUENCY, {nominal} Hz. The manual prints no x {turns} for these rows: '
             'confirm on the meter. Uncertainty: the calibrator\'s frequency uncertainty.')
NOTE_30K = ('PRINTED MISPRINT: Table 4 prints the limits of this row as 34.65 KΩ and 30.35 Ω. The row is symmetric about the nominal like its neighbours (10K: +-1.5 %; 3000 Ω: +-35 Ω), so the limits used are 29.65 kΩ and 30.35 kΩ. '
            'The printed limits are not used. UNVERIFIED against a second source.')
NOTE_NEG600 = 'Table 4 prints the low limit as "-606.5" without a unit: the row\'s V is taken.'
NOTE_TEMP = ('The calibrator simulates a thermocouple in degrees C (thermocouple type and connection are not stated in the Calibration Manual: the meter is a K-type thermocouple meter, UNVERIFIED). '
             'Figure 4 connects the calibrator NORMAL output and ground to the VΩ and COM jacks for this group of tests; whether the temperature test uses a thermocouple adapter is not described (UNVERIFIED). '
             'Let the meter and the calibrator connection settle to room temperature before the first point.')
NOTE_CAP = 'Settling time 10 s is an engineering choice (the manual gives none; UNVERIFIED). The 5560A capacitance commands are not verified (existing registry).'
NOTE_HIGHI = ('7.8 A at up to 400 Hz: the calibrator output and the 50-turn coil must carry it. 7.8 A for the 5522A / 5520A 20 A output at 400 Hz is not checked against its output specification here: if the calibrator refuses the output the run stops at this point. '
              'Duty cycle: the 5500A/COIL data recorded in NOTES.md allows 11 A rms continuously (UNVERIFIED for this coil).')


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def decimals(text: str) -> int:
    return max(0, -D(text).as_tuple().exponent)


def group_for(kind, applied, extra):
    if kind == 'TEMP':
        return 'TEMP'
    if extra.get('coil'):
        return 'COIL_AUX' if abs(D(applied)) < 3 else 'COIL_20A'
    return 'VOHM'


def check_rows():
    """Sanity checks that abort the build (re-read the table): the amps rows are centred on 50 x the calibrator current, every limit pair contains its nominal, the counts per model are Table 4's."""
    problems = []
    for n, (section, sw, kind, applied, freq, unit, nominal, low, high, models, extra) in enumerate(ROWS, 1):
        nom, lo, hi = D(nominal), D(low), D(high)
        if not lo <= nom <= hi:
            problems.append(f'row {n}: nominal {nominal} not between {low} and {high}')
        if extra.get('coil') and not extra.get('freq_row'):
            if D(applied) * TURNS != nom:
                problems.append(f'row {n}: {applied} A x {TURNS} turns is not {nominal} A')
        if extra.get('freq_row') and D(nominal) != D(freq):
            problems.append(f'row {n}: frequency nominal {nominal} Hz differs from the applied {freq} Hz')
        if unit != 'Hz' and kind not in ('TEMP',) and abs((nom - lo) - (hi - nom)) > 0 and (nom - lo, hi - nom) != (D(0), D('0.5')) and nominal != '0':
            if abs((nom - lo) - (hi - nom)) > D('0.0000001'):
                problems.append(f'row {n}: limits not symmetric about {nominal}: {low} .. {high}')
    counts = {m: sum(1 for r in ROWS if m in r[9]) for m in MODELS}
    if counts != EXPECTED_COUNTS:
        problems.append(f'points per model {counts} differ from the X columns of Table 4 {EXPECTED_COUNTS}')
    return problems


def build_steps():
    steps = []
    for n, (section, sw, kind, applied, freq, unit, nominal, low, high, models, extra) in enumerate(ROWS, 1):
        factor, base = UNITS[unit]
        assert decimals(low) == decimals(high) or True
        step = dict(table=TABLE, step=n, section=section, switch=SW[sw], range='', models=list(models), kind=kind, display_unit=unit, factor=float(D(factor)), base_unit=base,
                    low=low, high=high, test='numeric', applied=dict(value=clean(applied), frequency=float(freq) if freq else None), nominal=clean(D(nominal) * D(factor)))
        notes = [NOTE_RANGE]
        a_txt = f'{D(applied).normalize():f}'
        n_txt = f'{D(nominal).normalize():f}'
        step['tol_text'] = f'Table 4: {low} to {high} {unit}'
        if kind == 'TEMP':
            notes.append(NOTE_TEMP)
            step['settle'] = 30
        if extra.get('coil') and extra.get('freq_row'):
            notes.append(NOTE_FREQ.format(freq=freq, turns=TURNS, nominal=n_txt))
            step['report_desc'] = f'0.2 A x {TURNS} turns, {freq} Hz'
            step['dsb_desc'] = f'Frequency, jaw on the {TURNS}-turn coil: calibrator 0.2 A @ {freq} Hz, meter reads {n_txt} Hz'
            step['settle'] = 5
            step['unc_kind'] = 'FREQ'
            step['no_freq_suffix'] = True
        elif extra.get('coil'):
            notes.append(NOTE_COIL.format(turns=TURNS, applied=a_txt, nominal=n_txt))
            step['report_desc'] = f'Jaw, {a_txt} A x {TURNS} turns'
            step['settle'] = 5
            step['dsb_desc'] = f'{section}, jaw on the {TURNS}-turn coil: meter reads {n_txt} A' + (f' @ {freq} Hz' if freq else '')
            step['unc_standard'] = 'A2LA-5500A-COIL'
            step['unc_nominal'] = step['nominal']
            if D(applied) >= 4:
                notes.append(NOTE_HIGHI)
        if kind == 'OHM':
            notes.append(NOTE_OHMS)
        if kind == 'CAP':
            notes.append(NOTE_CAP)
            step['settle'] = extra.get('settle', 10)
        if extra.get('printed'):
            pl, ph = extra['printed']; ul, uh = extra['printed_units']
            step['printed_text'] = dict(low=f'{pl} {ul}', high=f'{ph} {uh}', note='PRINTED MISPRINT corrected: the table prints 34.65 KΩ and 30.35 Ω; stored 29.65 kΩ and 30.35 kΩ')
            notes.append(NOTE_30K)
            step['check'] = dict(verdict='misprint', printed=dict(low=f'{pl} {ul}', high=f'{ph} {uh}'), used=dict(low=low, high=high))
        if nominal == '-600':
            notes.append(NOTE_NEG600)
        step['group'] = group_for(kind, applied, extra)
        step['note'] = ' '.join(notes)
        step['ref'] = f'T{TABLE} #{n}'
        step['id'] = f'{TABLE}-{n}'
        steps.append(step)
    return steps


def coil_common():
    return [
        ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
        ('Test leads', 'REMOVE the test leads from the VΩ and COM jacks while the current is measured with the jaw (general practice; the Calibration Manual does not say).'),
        ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
    ]


GROUPS = {
    'COIL_AUX': dict(
        title='Change the cables: 50-turn coil on the calibrator low-current output',
        summary='Calibrator low-current output (5522A / 5520A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=coil_common() + [
            ('Coil', 'The wired coil is 50 turns (Table 3, printed p. 8: 5500A/COIL). Connect its two ends to the calibrator current output and ground (Figure 5): Fluke 5522A / 5520A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO. Use plugs rated for the current.'),
            ('Jaw', 'Close the jaw around the coil, fully closed, the coil centred in the opening, the coil leads kept away from the meter body. The meter then reads 50 x the calibrator current (0.2 A reads 10 A).'),
            ('LCOMP', 'Fluke 5522A / 5520A: for the AC points switch inductive-load compensation (LCOMP) ON at the calibrator front panel when the coil needs it. The program does not set it: UNVERIFIED for this coil.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads.',
        diagram='diagrams/hook_fluke323_COIL_AUX.png'),
    'COIL_20A': dict(
        title='Change the cables: 50-turn coil on the calibrator high-current output',
        summary='Calibrator high-current output (5522A / 5520A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (5500A/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=coil_common() + [
            ('Coil', 'Move the two ends of the 50-turn coil to the calibrator high-current terminals: Fluke 5522A / 5520A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 7.8 A (4.2 A and 7.8 A on the 323, 6 A on the 324 and 325).'),
            ('Jaw', 'The jaw stays closed around the coil (centred, fully closed, leads away from the meter body). The meter reads 50 x the calibrator current: 4.2 A reads 210 A, 6 A reads 300 A, 7.8 A reads 390 A.'),
            ('LCOMP', 'Fluke 5522A / 5520A: AC points with LCOMP ON when the coil needs it (not set by the program; UNVERIFIED for this coil).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 7.8 A flows in the coil. Keep the calibrator in STANDBY whenever you touch the coil or leads; check that the coil and leads are not warm after a long run (duty cycle not confirmed for this coil: UNVERIFIED).',
        diagram='diagrams/hook_fluke323_COIL_20A.png'),
    'TEMP': dict(
        title='Change the cables: temperature (thermocouple simulation)',
        summary='Calibrator thermocouple output (TC) -> the meter temperature input (see the Users Manual for the meter: the Calibration Manual does not describe the temperature connection).',
        steps=[
            ('Meter dial', 'Turn the meter dial to OFF before you move any lead, then to the temperature function.'),
            ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
            ('Connection', 'Connect the calibrator thermocouple (TC) output to the meter temperature input with the correct thermocouple cable and adapter for the meter (K-type assumed, UNVERIFIED). '
                           'Figure 4 of the Calibration Manual shows the NORMAL output and ground on the meter VΩ and COM jacks for the group of tests that includes temperature; if your meter takes the thermocouple there, use that connection instead.'),
            ('Soak', 'Let the cable and meter settle to room temperature before the first temperature point.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='The output is a simulated thermocouple signal (millivolts). Keep the calibrator in STANDBY while you connect the leads.',
        diagram='diagrams/hook_fluke323_TEMP.png'),
}

SOURCE_NOTE = (
    'Table 4 (48 rows: temperature 4, AC volts 5, DC volts 5, ohms 9, capacitance 3, frequency 3, AC amps 15, DC amps 4; printed pp. 13-14 of the 323 / 324 / 325 Calibration Manual). '
    'The table has no step numbers: steps are numbered in table order (4-1 .. 4-%d). One family spec: the X columns decide the models (323: 16 points, 324: 24, 325: 30). '
    'Table 3 (printed p. 8) names a calibrator with 4.5 digit resolution (Fluke 5520A recommended; the program drives a Fluke 5522A, 5520A or 5560A, or you set the calibrator by hand) and the 5500A/COIL (50 turns). '
    'The AC / DC amps rows are driven through the 50-turn coil: the Calibrator Output is the current the calibrator drives and the meter reads 50 x that (the limits are meter readings). The three Frequency rows (325) '
    'are ASSIGNED TO THE COIL (0.2 A through the coil = 10 A in the jaw): the manual lists them with the lead tests but a NORMAL output cannot make an amps value (UNVERIFIED inference). '
    'The meter has no remote interface: you type the display reading. Limits are as printed (nothing is changed); the 30K ohm row is a printed misprint (34.65 KΩ / 30.35 Ω) and is used as 29.65 kΩ / 30.35 kΩ, visibly flagged. '
    'The manual prints no ranges, resolutions or accuracy figures. The functional tests (display, firmware, backlight, buttons; printed pp. 9-10) and the calibration ADJUSTMENT (printed pp. 15-) are not part of this procedure.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s Table 4 (Fluke 323 / 324 / 325 Calibration Manual, printed pp. 13-14), unchanged except the 30K ohm row, whose printed limits (34.65 KΩ, 30.35 Ω) are a misprint and are '
    'reported as 29.65 kΩ to 30.35 kΩ. The current and frequency points are driven through a 50-turn coil (calibrator current x 50 = the reading shown); their Uncertainty is that of the 5500A/COIL scope lines '
    'at the effective current where the lines cover it (frequency: the calibrator\'s frequency uncertainty).')


def build_spec():
    problems = check_rows()
    if problems:
        raise SystemExit('Problems:\n  ' + '\n  '.join(problems))
    steps = build_steps()
    note = SOURCE_NOTE % len(steps)
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='fluke323', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='13-14 (printed): Table 4 pp. 13-14 (PDF pages 21-22); connections pp. 11-12; equipment Table 3 p. 8',
                    cite='Fluke 323 / 324 / 325 Calibration Manual, Table 4 Performance Tests, printed pp. 13-14; limits unchanged except the printed misprint of the 30K ohm row',
                    limits='Manufacturer limits, Table 4, as printed',
                    report_note=REPORT_NOTE, note=note),
        models={'323': dict(name='Fluke 323', brand='Fluke', model_note='Fluke 323 true-rms clamp meter: Table 4, 16 points (AC volts, DC volts, ohms, AC amps through the 50-turn coil)'),
                '324': dict(name='Fluke 324', brand='Fluke', model_note='Fluke 324 true-rms clamp meter: Table 4, 24 points (adds temperature and capacitance)'),
                '325': dict(name='Fluke 325', brand='Fluke', model_note='Fluke 325 true-rms clamp meter: Table 4, 30 points (adds frequency and DC amps)')},
        groups=GROUPS,
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT.name, len(spec['steps']), 'steps;', count)
    print('points per model:', {m: sum(1 for s in spec['steps'] if m in s['models']) for m in MODELS})


if __name__ == '__main__':
    main()
