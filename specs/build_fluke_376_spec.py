"""Builds specs/fluke_376_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 374 / 375 / 376 / 376-II Clamp Meters Calibration Manual
(December 2010, Rev. 2, 11/25; 14 PDF pages).

    python3 specs/build_fluke_376_spec.py

Source (printed page numbers; PDF page = printed page + 4):
  Table 1 "Performance Tests", printed pp. 3-4 (PDF 7-8): 38 rows, one X / - column per model (374, 375, 376/376-II);
  the paragraph above the table (printed p. 3): the iFlex simulated tests (calibrator HI to the iFlex 2 mm jack, far left; calibrator LO to the black COM jack);
  Table 2 "Required Equipment" (printed p. 4): calibrator 4.5 digit (Fluke 55XXA), wired coil 50 turns (55XXA/COIL), test probe for iFlex (2 mm to 4 mm Slim Reach, PN 6508922),
  test lead with retractable sheath (6358, PN 1903307); Figure 1 (printed p. 2): the meter, dial and the VOhm / COM jacks.
Every nominal, frequency and limit below was read from the RENDERED PAGE IMAGES (pdftoppm at 130, 200 and 260 dpi), twice, never from extracted text
(the extracted text moves the -500 V row into the AC volts block and prints '18 A @ 5 0Hz'); tests/test_fluke_376_points.py holds the second transcription.

ONE FAMILY SPEC, FOUR MODELS (as the 110 / 170 series): every step lists the models it applies to, from the X columns of Table 1:
  374: 28 points   375: 34 points (no 900 V, no 18 A)   376: 38 points   376-II: 38 points (Table 1 prints one column '376/376-II').
  The 374 has no mV, no 30K / 54K ohm, no 900 V and no 18 A rows; the 375 adds mV and 30K / 54K ohms; the 376 and 376-II add the 900 V and 18 A rows.
  Only the 376 is registered as a procedure (Procedures/Fluke_376_Verification.py).

What Table 1 means for the current rows:
  'AC / DC Amps (with 50-turn Coil)': the Calibrator Output (0.2 / 10 / 18 / 6 A) is the current the CALIBRATOR drives through the 50-turn coil; the limits are what the
      METER reads (50 x: 0.2 A -> 10 A, 10 A -> 500 A, 18 A -> 900 A, 6 A -> 300 A).  applied.value = the calibrator current, nominal = what the meter shows.
  'iFlex Current Probe (with Simulation)': the calibrator drives a VOLTAGE (3 / 30 / 60 / 75 mV at 50 Hz, 750 mV at 500 Hz) into the iFlex input and the meter reads amps
      (100 / 1000 / 2000 / 2500 / 2500 A; the simulated Rogowski coil voltage is proportional to frequency: 30 uV per A at 50 Hz, 300 uV per A at 500 Hz).
  'iFlex Current Probe (with 50-turn Coil)': the iFlex loop around the same 50-turn coil, the calibrator drives the coil current.

Uncertainty (owner decision): every sourced point carries the regular calibrator uncertainty at the actual calibrator OUTPUT (the coil current as it is, NOT multiplied by 50;
the iFlex simulation voltage as printed), through the existing mechanism.  The iFlex simulation rows are sourced as AC volts and read in amps: their Uncertainty is the calibrator's
AC VOLTS uncertainty (step.unc_unit 'V' tells the engine the unit of the source); TAR / TUR stay blank there (a tolerance in amps is never divided by an uncertainty in volts).

Cross-check against the published accuracy statement.  The Calibration Manual says 'Complete specifications are in the printed Users Manual' and prints none, so the accuracy table
below (ACC, RES) was taken from the fluke.com product page of the Fluke 376 (read 2026-10-23 through a text-summarising fetch, NOT from the Users Manual and NOT from a page image):
  AC volts 1.5 % + 5 digits (20-500 Hz); DC volts and mV 1 % + 5 digits; ohms 1 % + 5 digits; capacitance 1 % + 4 digits; AC amps (jaw) 2 % + 5 digits (10-100 Hz) and 2.5 % + 5 digits
  (100-500 Hz); DC amps 2 % + 5 digits; iFlex 3 % + 5 digits (5-500 Hz).  Resolutions (376): volts 0.1 V up to 600.0 V and 1 V up to 1000 V; mV 0.1 mV (500.0 mV); ohms 0.1 / 1 / 10 ohm
  (600 / 6000 / 60 k); capacitance 0.1 uF up to 100 uF and 1 uF up to 1000 uF; jaw amps 0.1 A (999.9 A); iFlex 0.1 A up to 999.9 A and 1 A up to 2500 A.
  UNVERIFIED: confirm every figure against the 374 / 375 / 376 Users Manual specifications.
The builder compares every printed limit with it (Decimal) and tells each row apart:
  'full'   the printed limit equals the full published specification to within half a display step (every volts, mV, ohms, capacitance and AC amps row);
  'half'   it equals half of it (the iFlex simulation rows, the DC amps 0.2 A row and two of the iFlex-with-coil rows: a 2:1 margin, as the Fluke 365 manual);
  'tighter' it is inside the full specification but is neither (DC amps 10 A and 18 A, +-5.0 / 9.0 A against +-10.5 / 18.5 A (half 5.25 / 9.25); iFlex with coil 10 A and 18 A,
            +-7.0 / 13.0 A against half = 7.75 / 13.75 A): stored as printed, flagged;
  'rounded' the printed limit is the specification value ROUNDED to the display step, so one side is looser than the specification by up to half a step (AC 10 V high 10.7 vs 10.65; AC 900 V
            882 / 919 vs 881.5 / 918.5, both rounded up): stored as printed, flagged;
  The builder aborts if a printed limit is LOOSER than the full specification by more than half a display step.  NOTHING is changed: limits are stored as printed.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_376_pv.json'
TABLE = '1'
DOCUMENT = 'Fluke 374 / 375 / 376 / 376-II Clamp Meters - Calibration Manual (December 2010, Rev. 2, 11/25)'
MODELS = ('374', '375', '376', '376-II')
ALL, NO374, ONLY376 = MODELS, ('375', '376', '376-II'), ('376', '376-II')
TURNS = 50

# display unit -> (factor to base unit, base unit); Table 1 prints 'KΩ' (capital K): shown as kΩ
UNITS = {'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'µF': ('0.000001', 'F'), 'A': ('1', 'A')}

# Rotary switch text ('short  (detail)': the engine prompts again whenever this text changes between two points).  Figure 1 (printed p. 2) shows the dial positions
# OFF, V~ (Hz yellow), V⎓ (mV yellow), Ω with the continuity symbol (capacitance symbol yellow), A~ (Hz yellow), A⎓ and iFlex A~ (Hz yellow); the alternate functions in
# yellow are the ones the Calibration Manual does not say how to select: UNVERIFIED (the yellow button is not named; the only yellow button drawn is ZERO).
SW = {
    'acv': 'V~  (AC volts)',
    'dcv': 'V⎓  (DC volts)',
    'mv': 'mV⎓  (DC millivolts: the V⎓ position, mV is its yellow alternate function; how it is selected is UNVERIFIED)',
    'ohm': 'Ω  (ohms: the Ω position, shared with continuity and capacitance)',
    'cap': 'Capacitance ⊣⊢  (the Ω position, ⊣⊢ is its yellow alternate function; how it is selected is UNVERIFIED)',
    'aca': 'A~  (AC amps: detachable jaw closed around the 50-turn coil)',
    'dca': 'A⎓  (DC amps: detachable jaw closed around the 50-turn coil)',
    'iflex': 'iFlex A~  (iFlex AC current; the iFlex probe plugged in, or the simulation leads)',
}

# published accuracy: (percent of reading, digits)  [UNVERIFIED: fluke.com product page, see the module docstring]
ACC = {'ACV': ('1.5', 5), 'DCV': ('1', 5), 'MV': ('1', 5), 'OHM': ('1', 5), 'CAP': ('1', 4), 'ACA50': ('2', 5), 'ACA440': ('2.5', 5), 'DCA': ('2', 5), 'IFLEX': ('3', 5)}

NOTE_OHMS = 'Table 1 does not say whether the limits include test lead resistance (UNVERIFIED); use short leads.'
NOTE_RANGE = 'Table 1 names no range: the range shown is the one the published resolutions put this reading in (UNVERIFIED).'
NOTE_COIL = ('The calibrator drives the {turns}-turn coil and the meter reads {turns} x the calibrator current: {applied} A in, {nominal} A on the meter. The limits are the meter readings (Table 1, printed p. 4). '
             'Uncertainty (owner-chosen convention): the regular calibrator current uncertainty at the calibrator output current ({applied} A), as it is, NOT multiplied by {turns} and without the coil; '
             'TAR / TUR compare that unscaled value with the meter-reading tolerance printed in Table 1.')
NOTE_IFLEX_SIM = ('iFlex simulation (printed p. 3): calibrator Output HI to the iFlex 2 mm jack (far left), Output LO to the black COM jack; the calibrator drives {applied} {unit} AC at {freq} Hz and the meter '
                  'reads {nominal} A. Uncertainty (owner-chosen convention): the regular calibrator AC VOLTS uncertainty at the output as printed; TAR / TUR stay blank (the tolerance is in amps, the uncertainty in volts).')
NOTE_IFLEX_COIL = ('The iFlex loop is placed around the {turns}-turn coil and the calibrator drives the coil: {applied} A in, {nominal} A on the meter (Table 1, printed p. 4). Uncertainty (owner-chosen convention): '
                   'the regular calibrator current uncertainty at {applied} A, NOT multiplied by {turns}; TAR / TUR compare it with the meter-reading tolerance.')
NOTE_440 = ('UNVERIFIED: the 5500A/COIL data recorded in NOTES.md (coil standard sheet) limits 65-440 Hz coil drive to 2.2 A (5500A) / 3 A (5520A) of calibrator output; Table 1 asks for 6 A at 440 Hz. '
            'Whether the 5522A / 5560A and the lab\'s coil can do it is not known: the calibrator refuses an output it cannot make and the run stops there.')
NOTE_18A = ('UNVERIFIED: the 5500A/COIL data recorded in NOTES.md allows 11 A rms continuously and up to 20 A rms for 2 minutes (above 11 A: 2 minutes ON, 8 minutes OFF). 18 A is above 11 A: '
            'keep the output ON only as long as the reading needs and let the coil rest 8 minutes before the next high-current point.')
NOTE_ZERO = ('Not in the Calibration Manual (UNVERIFIED): the meter has a ZERO button (Figure 1); with the jaw closed and nothing in it, a DC amps reading that is not zero may need it. Do not zero with the coil in the jaw.')
NOTE_900 = ('Printed with one decimal (882.0 style) although the 1000 V range is published with 1 V resolution (UNVERIFIED): a typed reading is padded to the printed one decimal.')

# (section, switch key, range, kind, applied (calibrator output, base units), frequency, display unit, nominal (what the meter shows, display unit), printed low, printed high,
#  accuracy key, resolution of the range the reading falls in (display unit), models, extras)
ROWS = [
    ('AC volts', 'acv', '600.0 V', 'ACV', '10', 50, 'V', '10', '9.4', '10.7', 'ACV', '0.1', ALL, {}),
    ('AC volts', 'acv', '600.0 V', 'ACV', '500', 50, 'V', '500', '492.0', '508.0', 'ACV', '0.1', ALL, {}),
    ('AC volts', 'acv', '1000 V', 'ACV', '900', 50, 'V', '900', '882.0', '919.0', 'ACV', '1', ONLY376, {'note900': True}),
    ('AC volts', 'acv', '600.0 V', 'ACV', '500', 500, 'V', '500', '492.0', '508.0', 'ACV', '0.1', ALL, {}),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '-500', None, 'V', '-500', '-505.5', '-494.5', 'DCV', '0.1', ALL, {}),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '10', None, 'V', '10', '9.4', '10.6', 'DCV', '0.1', ALL, {}),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '500', None, 'V', '500', '494.5', '505.5', 'DCV', '0.1', ALL, {}),
    ('DC volts', 'dcv', '1000 V', 'DCV', '900', None, 'V', '900', '886.0', '914.0', 'DCV', '1', ONLY376, {'note900': True}),
    ('DC volts', 'mv', '500.0 mV', 'DCV', '-0.25', None, 'mV', '-250', '-253.0', '-247.0', 'MV', '0.1', NO374, {}),
    ('DC volts', 'mv', '500.0 mV', 'DCV', '0.05', None, 'mV', '50', '49.0', '51.0', 'MV', '0.1', NO374, {}),
    ('DC volts', 'mv', '500.0 mV', 'DCV', '0.25', None, 'mV', '250', '247.0', '253.0', 'MV', '0.1', NO374, {}),
    ('DC volts', 'mv', '500.0 mV', 'DCV', '0.45', None, 'mV', '450', '445.0', '455.0', 'MV', '0.1', NO374, {}),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '60', None, 'Ω', '60', '58.9', '61.1', 'OHM', '0.1', ALL, {}),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '300', None, 'Ω', '300', '296.5', '303.5', 'OHM', '0.1', ALL, {}),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '540', None, 'Ω', '540', '534.1', '545.9', 'OHM', '0.1', ALL, {}),
    ('Ohms', 'ohm', '6000 Ω', 'OHM', '3000', None, 'Ω', '3000', '2965', '3035', 'OHM', '1', ALL, {}),
    ('Ohms', 'ohm', '6000 Ω', 'OHM', '5400', None, 'Ω', '5400', '5341', '5459', 'OHM', '1', ALL, {}),
    ('Ohms', 'ohm', '60.00 kΩ', 'OHM', '30000', None, 'kΩ', '30', '29.65', '30.35', 'OHM', '0.01', NO374, {}),
    ('Ohms', 'ohm', '60.00 kΩ', 'OHM', '54000', None, 'kΩ', '54', '53.41', '54.59', 'OHM', '0.01', NO374, {}),
    ('Capacitance', 'cap', '100.0 µF', 'CAP', '0.00001', None, 'µF', '10', '9.5', '10.5', 'CAP', '0.1', ALL, {'settle': 10}),
    ('Capacitance', 'cap', '1000 µF', 'CAP', '0.0005', None, 'µF', '500', '491', '509', 'CAP', '1', ALL, {'settle': 10}),
    ('Capacitance', 'cap', '1000 µF', 'CAP', '0.0009', None, 'µF', '900', '887', '913', 'CAP', '1', ALL, {'settle': 10}),
    ('AC amps', 'aca', '999.9 A', 'ACI', '0.2', 50, 'A', '10', '9.3', '10.7', 'ACA50', '0.1', ALL, {'coil': True}),
    ('AC amps', 'aca', '999.9 A', 'ACI', '10', 50, 'A', '500', '489.5', '510.5', 'ACA50', '0.1', ALL, {'coil': True}),
    ('AC amps', 'aca', '999.9 A', 'ACI', '18', 50, 'A', '900', '881.5', '918.5', 'ACA50', '0.1', ONLY376, {'coil': True}),
    ('AC amps', 'aca', '999.9 A', 'ACI', '6', 440, 'A', '300', '292.0', '308.0', 'ACA440', '0.1', ALL, {'coil': True}),
    ('DC amps', 'dca', '999.9 A', 'DCI', '0.2', None, 'A', '10', '9.7', '10.3', 'DCA', '0.1', ALL, {'coil': True}),
    ('DC amps', 'dca', '999.9 A', 'DCI', '10', None, 'A', '500', '495.0', '505.0', 'DCA', '0.1', ALL, {'coil': True}),
    ('DC amps', 'dca', '999.9 A', 'DCI', '18', None, 'A', '900', '891.0', '909.0', 'DCA', '0.1', ONLY376, {'coil': True}),
    ('iFlex simulated', 'iflex', '2500 A', 'ACV', '0.003', 50, 'A', '100', '98.2', '101.8', 'IFLEX', '0.1', ALL, {'sim': True}),
    ('iFlex simulated', 'iflex', '2500 A', 'ACV', '0.03', 50, 'A', '1000', '982', '1018', 'IFLEX', '1', ALL, {'sim': True}),
    ('iFlex simulated', 'iflex', '2500 A', 'ACV', '0.06', 50, 'A', '2000', '1967', '2033', 'IFLEX', '1', ALL, {'sim': True}),
    ('iFlex simulated', 'iflex', '2500 A', 'ACV', '0.075', 50, 'A', '2500', '2460', '2540', 'IFLEX', '1', ALL, {'sim': True}),
    ('iFlex simulated', 'iflex', '2500 A', 'ACV', '0.75', 500, 'A', '2500', '2460', '2540', 'IFLEX', '1', ALL, {'sim': True}),
    ('iFlex with coil', 'iflex', '999.9 A', 'ACI', '0.2', 50, 'A', '10', '9.6', '10.4', 'IFLEX', '0.1', ALL, {'coil': True, 'iflex': True}),
    ('iFlex with coil', 'iflex', '999.9 A', 'ACI', '10', 50, 'A', '500', '493.0', '507.0', 'IFLEX', '0.1', ALL, {'coil': True, 'iflex': True}),
    ('iFlex with coil', 'iflex', '999.9 A', 'ACI', '18', 50, 'A', '900', '887.0', '913.0', 'IFLEX', '0.1', ALL, {'coil': True, 'iflex': True}),
    ('iFlex with coil', 'iflex', '999.9 A', 'ACI', '6', 440, 'A', '300', '295.2', '304.8', 'IFLEX', '0.1', ALL, {'coil': True, 'iflex': True}),
]
EXPECTED_COUNTS = {'374': 28, '375': 34, '376': 38, '376-II': 38}
# rows the check classifies as other than 'full' / 'half' (printed step number within Table 1 order): flagged in the note, nothing changed
EXPECTED_FLAGS = {1: 'rounded', 3: 'rounded', 28: 'tighter', 29: 'tighter', 36: 'tighter', 37: 'tighter'}


def group_for(kind, applied, row_extra):
    """Hook-up group: volts / mV / ohms / capacitance on the test leads (hookups.py 'fluke376'); the coil rows on the calibrator low-current (0.2 A) or high-current output;
    the iFlex rows on the iFlex simulation leads or with the iFlex loop on the coil."""
    if row_extra.get('sim'):
        return 'IFLEX_SIM'
    if row_extra.get('coil'):
        low_current = abs(D(applied)) < 3
        if row_extra.get('iflex'):
            return 'IFLEX_COIL_AUX' if low_current else 'IFLEX_COIL_20A'
        return 'COIL_AUX' if low_current else 'COIL_20A'
    return 'VOHM'


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def decimals(text: str) -> int:
    return max(0, -D(text).as_tuple().exponent)


def spec_halfwidth(nominal, acc, res):
    """Published specification at the reading `nominal`: +/-(% of reading + digits x resolution), in the display unit (Decimal)."""
    pct, digits = D(acc[0]), acc[1]
    return pct / 100 * abs(D(nominal)) + digits * D(res)


def check_row(step_no, nominal, low, high, acc, res):
    """Compare the printed limits with the published accuracy.  Returns (problems, info, verdict): problems are printed limits LOOSER than the full specification by more than half a
    display step (the builder aborts); info lists the sides that are neither the full nor the half specification (flagged, never changed); verdict is 'full', 'half', 'tighter' or 'rounded'."""
    full = spec_halfwidth(nominal, acc, res)
    half = full / 2
    nominal, low, high, res = D(nominal), D(low), D(high), D(res)
    step = res / 2
    problems, info, kinds = [], [], set()
    for name, got in (('low', nominal - low), ('high', high - nominal)):
        if got > full + step:
            problems.append(f'step {step_no}: the printed {name} limit is {got} from the nominal, LOOSER than the published specification {full}')
        elif abs(got - full) <= step:
            kinds.add('rounded' if got > full else 'full')
        elif abs(got - half) <= step:
            kinds.add('half')
        else:
            kinds.add('tighter')
        if got > full or (abs(got - full) > step and abs(got - half) > step):
            info.append(dict(side=name, printed=fmt(got.normalize()), half_spec=fmt(half.normalize()), full_spec=fmt(full.normalize())))
    for v in ('tighter', 'rounded', 'half', 'full'):
        if v in kinds:
            return problems, info, v
    return problems, info, 'full'


def build_steps():
    steps, problems, flagged = [], [], []
    for n, (section, sw, rng, kind, applied, freq, unit, nominal, low, high, acc_key, res, models, extra) in enumerate(ROWS, 1):
        factor, base = UNITS[unit]
        acc = ACC[acc_key]
        p, info, verdict = check_row(f'{TABLE}-{n}', nominal, low, high, acc, res)
        problems += p
        if EXPECTED_FLAGS.get(n, verdict) != verdict and (n in EXPECTED_FLAGS or verdict in ('tighter', 'rounded')):
            problems.append(f'step {TABLE}-{n}: classified {verdict!r}, the builder expects {EXPECTED_FLAGS.get(n, "full or half")!r} (re-read the table)')
        assert decimals(low) >= decimals(res) or D(low) == D(low).quantize(D(res)), (n, low)
        low_f = fmt(D(low).quantize(D(res))) if decimals(low) < decimals(res) else low
        high_f = fmt(D(high).quantize(D(res))) if decimals(high) < decimals(res) else high
        assert D(low_f) == D(low) and D(high_f) == D(high), f'{TABLE}-{n}: reformatting changed a limit'
        step = dict(table=TABLE, step=n, section=section, switch=SW[sw], range=rng, models=list(models), kind=kind)
        step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=low_f, high=high_f, test='numeric',
                    applied=dict(value=clean(applied), frequency=float(freq) if freq else None), nominal=clean(D(nominal) * D(factor)))
        if (low_f, high_f) != (low, high):
            step['printed_text'] = dict(low=low, high=high, note='printed with fewer decimals than the display resolution; same value')
        pct, digits = acc
        what = 'digits of ' + res + ' ' + unit
        step['accuracy'] = f'±({pct} % of reading + {digits} digits)'
        full = spec_halfwidth(nominal, acc, res)
        step['tol_text'] = (f'Table 1: {low_f} to {high_f} {unit}   (published specification, UNVERIFIED: ±({pct} % of reading + {digits} {what}) = ±{fmt(full.normalize())} {unit}'
                            + ('; the table keeps half of it' if verdict == 'half' else '') + ')')
        notes = [NOTE_RANGE]
        a_txt = f'{D(applied).normalize():f}'
        n_txt = f'{D(nominal).normalize():f}'
        if extra.get('sim'):
            mv = D(applied) * 1000
            notes.append(NOTE_IFLEX_SIM.format(applied=f'{mv.normalize():f}', unit='mV', freq=freq, nominal=n_txt))
            step['unc_unit'] = 'V'                                       # the engine words the Uncertainty in the unit of the SOURCE (volts), not of the reading (amps)
            step['report_desc'] = f'{rng}, {mv.normalize():f} mV applied'
            step['dsb_desc'] = f'iFlex simulated, {rng} range: {mv.normalize():f} mV AC @ {freq} Hz, meter reads {n_txt} A'
        elif extra.get('coil'):
            tmpl = NOTE_IFLEX_COIL if extra.get('iflex') else NOTE_COIL
            notes.append(tmpl.format(turns=TURNS, applied=a_txt, nominal=n_txt))
            lead = 'iFlex' if extra.get('iflex') else rng[:-2] + ' A'
            step['report_desc'] = f'{lead}, {a_txt} A x {TURNS} turns'          # short: the report's Description cell wraps beyond ~30 characters
            step['settle'] = 5
            head = f'iFlex loop on the {TURNS}-turn coil' if extra.get('iflex') else f'{section}, jaw on the {TURNS}-turn coil'
            step['dsb_desc'] = f'{head}, {rng} range: meter reads {n_txt} A' + (f' @ {freq} Hz' if freq else '')
            if freq == 440:
                notes.append(NOTE_440)
            if D(applied) == 18:
                notes.append(NOTE_18A)
            if sw == 'dca' and applied == '0.2':
                notes.append(NOTE_ZERO)
        if kind == 'OHM':
            notes.append(NOTE_OHMS)
        if extra.get('note900'):
            notes.append(NOTE_900)
        if kind == 'CAP':
            notes.append('Settling time 10 s is an engineering choice (the manual gives none; UNVERIFIED). The 5560A capacitance commands are not verified (existing registry).')
        if info or verdict in ('tighter', 'rounded'):
            if verdict == 'rounded':
                sides = '; '.join(f'{i["side"]} limit {i["printed"]} from the nominal vs the full specification {i["full_spec"]}' for i in info)
            else:
                sides = '; '.join(f'{i["side"]} limit ±{i["printed"]} vs half of the specification ±{i["half_spec"]}' for i in info)
            if verdict == 'rounded':
                what_ = 'the printed limit is the specification value rounded to the display step (one side is looser than the specification by up to half a step)'
            else:
                what_ = 'the printed limit is inside the full specification but is neither the full specification nor half of it'
            step['check'] = dict(verdict=verdict, printed_vs_spec=info, full_spec=fmt(full.normalize()))
            notes.append(f'CHECK (printed limit not changed): {what_}: {sides} (full published specification ±{fmt(full.normalize())} {unit}, UNVERIFIED source).')
            flagged.append((f'{TABLE}-{n}', verdict, section, applied, freq, nominal, low, high, info))
        step['group'] = group_for(kind, applied, extra)
        if 'settle' in extra:
            step['settle'] = extra['settle']
        step['note'] = ' '.join(notes)
        step['ref'] = f'T{TABLE} #{n}'
        step['id'] = f'{TABLE}-{n}'
        steps.append(step)
    counts = {m: sum(1 for s in steps if m in s['models']) for m in MODELS}
    if counts != EXPECTED_COUNTS:
        problems.append(f'points per model {counts} differ from the X columns of Table 1 {EXPECTED_COUNTS}')
    return steps, problems, flagged


COIL_COMMON = [
    ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
    ('Test leads', 'REMOVE the test leads from the VΩ and COM jacks while the current is measured with the jaw or the iFlex (general practice; the Calibration Manual does not say).'),
    ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
]
GROUPS = {
    'COIL_AUX': dict(
        title='Change the cables: 50-turn coil on the calibrator low-current output',
        summary='Calibrator low-current output (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=COIL_COMMON + [
            ('Coil', 'The wired coil is 50 turns (Table 2, printed p. 4: 55XXA/COIL). Connect its two ends to the calibrator: Fluke 5522A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO. Use plugs rated for the current.'),
            ('Jaw', 'Close the detachable jaw around the coil, jaw fully closed, the coil centred in the opening, the coil leads kept away from the meter body. The meter then reads 50 x the calibrator current: '
                    '0.2 A reads 10 A. (How the jaw sits on the 55XXA/COIL is not described in the manual: UNVERIFIED.)'),
            ('LCOMP', 'Fluke 5522A: for the AC points switch inductive-load compensation (LCOMP) ON at the calibrator front panel when the coil needs it. The program does not set it: UNVERIFIED for this coil.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads. The jaw is marked 1000 A, CAT III 1000 V (Figure 1).',
        diagram='diagrams/hook_fluke376_COIL_AUX.png'),
    'COIL_20A': dict(
        title='Change the cables: 50-turn coil on the calibrator high-current output',
        summary='Calibrator high-current output (5522A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the meter jaw closed around the coil. No test leads in the meter jacks.',
        steps=COIL_COMMON + [
            ('Coil', 'Move the two ends of the 50-turn coil to the calibrator high-current terminals: Fluke 5522A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 18 A.'),
            ('Jaw', 'The detachable jaw stays closed around the coil (centred, jaw fully closed, leads away from the meter body). The meter reads 50 x the calibrator current: 10 A reads 500 A, 18 A reads 900 A, 6 A reads 300 A.'),
            ('LCOMP', 'Fluke 5522A: AC points with LCOMP ON when the coil needs it (not set by the program; UNVERIFIED for this coil).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 18 A flows in the coil. The 5500A/COIL data recorded in NOTES.md allows 11 A continuously and 20 A for 2 minutes (then 8 minutes rest): UNVERIFIED for this coil. '
                'Keep the calibrator in STANDBY whenever you touch the coil or leads; check that the coil and leads are not warm after a long run.',
        diagram='diagrams/hook_fluke376_COIL_20A.png'),
    'IFLEX_SIM': dict(
        title='Change the cables: iFlex simulation (calibrator voltage output to the iFlex input)',
        summary='Calibrator NORMAL HI (5522A) / OUTPUT V/Ω HI (5560A) -> iFlex 2 mm jack (far left); calibrator LO -> the black COM jack. Test lead with retractable sheath (6358, PN 1903307) and 2 mm to 4 mm Slim Reach probe (PN 6508922).',
        steps=[
            ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
            ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
            ('Calibrator', 'Fluke 5522A: NORMAL HI and NORMAL LO; Fluke 5560A: OUTPUT V/Ω HI and OUTPUT V/Ω LO (the voltage output, as for the volts points).'),
            ('iFlex input', 'Calibrator HI to the iFlex 2 mm jack on the far left of the meter, calibrator LO to the black COM jack (Performance Tests, printed p. 3). Use the test probe for iFlex (2 mm to 4 mm Slim Reach probe, PN 6508922) '
                            'and the test lead with retractable sheath (6358, PN 1903307) from the equipment list. No iFlex loop is connected. Which jack is the "far left" one is UNVERIFIED (Figure 1 shows the jacks too small to name).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='The output is only millivolts (3 to 750 mV). Keep the calibrator in STANDBY while you connect the leads.',
        diagram='diagrams/hook_fluke376_IFLEX_SIM.png'),
    'IFLEX_COIL_AUX': dict(
        title='Change the cables: iFlex loop on the 50-turn coil, calibrator low-current output',
        summary='Calibrator low-current output (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the iFlex loop around the coil, plugged into the meter. No test leads in the meter jacks.',
        steps=COIL_COMMON + [
            ('Coil', 'Coil on the calibrator low-current output as for the jaw points: Fluke 5522A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO.'),
            ('iFlex', 'Remove the jaw from the coil. Plug the iFlex probe into the meter and place its loop around the coil (Table 1, printed p. 4: iFlex Current Probe with 50-turn coil). The meter reads 50 x the calibrator current: 0.2 A reads 10 A. '
                      'How the loop sits on the 55XXA/COIL (position, closed latch, away from the leads) is not described in the manual: UNVERIFIED.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil, the loop or the leads.',
        diagram='diagrams/hook_fluke376_IFLEX_COIL_AUX.png'),
    'IFLEX_COIL_20A': dict(
        title='Change the cables: iFlex loop on the 50-turn coil, calibrator high-current output',
        summary='Calibrator high-current output (5522A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the iFlex loop around the coil, plugged into the meter. No test leads in the meter jacks.',
        steps=COIL_COMMON + [
            ('Coil', 'Move the two ends of the coil to the calibrator high-current terminals: Fluke 5522A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and leads must carry up to 18 A.'),
            ('iFlex', 'The iFlex loop stays around the coil, the probe plugged into the meter. The meter reads 50 x the calibrator current: 10 A reads 500 A, 18 A reads 900 A, 6 A reads 300 A.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 18 A flows in the coil. The 5500A/COIL data recorded in NOTES.md allows 11 A continuously and 20 A for 2 minutes (then 8 minutes rest): UNVERIFIED for this coil. '
                'Keep the calibrator in STANDBY whenever you touch the coil or leads.',
        diagram='diagrams/hook_fluke376_IFLEX_COIL_20A.png'),
}

SOURCE_NOTE = (
    'Table 1 (38 rows: AC volts 4, DC volts 8 (4 of them millivolts), ohms 7, capacitance 3, AC amps 4, DC amps 3, iFlex simulated 5, iFlex with coil 4; printed pp. 3-4 of the 374 / 375 / 376 / 376-II '
    'Calibration Manual). The table has no step numbers: steps are numbered in table order (1-1 .. 1-38). One family spec: the X columns decide the models (374: 28 points, 375: 34, 376 and 376-II: 38). '
    'Table 2 (printed p. 4) names a calibrator with 4.5 digit resolution (Fluke 55XXA recommended), the 55XXA/COIL (50 turns), the test probe for iFlex and a test lead; the procedure drives a Fluke 5522A or 5560A '
    '(or you set the calibrator by hand). The current rows are driven through the 50-turn coil: the calibrator output is 0.2 / 10 / 18 / 6 A and the meter reads 50 x that (limits are meter readings). '
    'The iFlex rows are simulated with a voltage (3 to 750 mV) or driven through the coil with the iFlex loop. The meter has no remote interface: you type the display reading. '
    'Limits are as printed (nothing is corrected). Where a printed limit is not the full or half published accuracy (UNVERIFIED source, the fluke.com product page) the point says so. '
    'High-voltage points go straight to the test value (the manual prescribes no ramp). The calibration ADJUSTMENT (Table 3, printed pp. 5-8) is not part of this procedure.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s Table 1 (Fluke 374 / 375 / 376 / 376-II Calibration Manual, printed pp. 3-4), unchanged. The jaw and iFlex current points are driven through a 50-turn coil '
    '(calibrator current x 50 = the reading shown); the iFlex simulated points apply a voltage to the iFlex input. Their Uncertainty is the calibrator\'s uncertainty at the actual output (current: point / 50, '
    'unscaled and without the coil; simulation: AC volts as applied), an owner-chosen convention; TAR / TUR compare it with the meter-reading tolerance for the coil points and are blank for the iFlex simulated points.')


def build_spec():
    steps, problems, flagged = build_steps()
    if problems:
        raise SystemExit('Problems:\n  ' + '\n  '.join(problems))
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='fluke376', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='3-4 (printed): Table 1 pp. 3-4 (PDF pages 7-8); equipment Table 2 p. 4; Figure 1 p. 2',
                    cite='Fluke 374 / 375 / 376 / 376-II Calibration Manual, Table 1 Performance Tests, printed pp. 3-4; limits unchanged, rows flagged against the published accuracy (UNVERIFIED source, see Source)',
                    limits='Manufacturer limits, Table 1, as printed',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={'374': dict(name='Fluke 374', brand='Fluke', model_note='Fluke 374 true-rms clamp meter (600 A jaw, 600 V): Table 1, 28 points'),
                '375': dict(name='Fluke 375', brand='Fluke', model_note='Fluke 375 true-rms clamp meter (600 A jaw, 600 V, mV): Table 1, 34 points'),
                '376': dict(name='Fluke 376', brand='Fluke', model_note='Fluke 376 true-rms clamp meter (999.9 A jaw, 1000 V, iFlex 2500 A): Table 1, 38 points'),
                '376-II': dict(name='Fluke 376-II', brand='Fluke', model_note='Fluke 376-II true-rms clamp meter: Table 1 prints one column for the 376 and the 376-II, 38 points (not registered as a procedure)')},
        groups=GROUPS,
        steps=steps), flagged


def main():
    spec, flagged = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT, len(spec['steps']), 'steps;', count)
    print('points per model:', {m: sum(1 for s in spec['steps'] if m in s['models']) for m in MODELS})
    for f in flagged:
        print('  FLAG', f[0], f[1], f[2], f'applied {f[3]}', f'{f[4]} Hz' if f[4] else 'dc', f'nominal {f[5]}', f'printed {f[6]} .. {f[7]}', f[8])


if __name__ == '__main__':
    main()
