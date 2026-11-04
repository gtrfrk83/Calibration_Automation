"""Builds specs/keithley_485_pv.json for the shared handheld engine (handheld_dmm.py, through Procedures/Keithley_485_Verification.py) from the
Keithley Model 485 Autoranging Picoammeter Instruction Manual (document 485-901-01 Rev. F, 57 PDF pages).

    python3 specs/build_keithley_485_spec.py

Source (printed page numbers):
  Section 3.5 Verification Procedure, p. 3-1 (steps 1-10); Table 3-1 Recommended Test Equipment and Figure 3-1 Shielded Test Fixture, p. 3-2;
  Table 3-2 Range Accuracy, p. 3-2 (7 ranges); 2.7.2 Zero Check, p. 2-4; SPECIFICATIONS (front of the manual: range, resolution, 1-year accuracy).
Every current, limit and resolution below was read from the RENDERED PAGE IMAGES (pdftoppm), twice, never from extracted text.

Method (Table 3-2): a DC voltage V is applied through a measured resistor R in a shielded fixture, so the 485 reads I = V / R.  The calibrator setting is
    V = I (required current) x R (measured value of the resistor)
so the current is exactly the required current and the printed 'Allowable Readings' are judged unchanged.  R comes from the lab's resistance box
(RESISTORS below, one decade per range).  When the box is recalibrated: edit BOX, RESISTORS and RESISTOR_U here and run this script again.

Negative current (step 10, 'reverse the + and - test leads at the DC calibrator and repeat all checks'): the calibrator sources -V instead (the same current
reversal with the leads left in place); each range is checked + then - so the resistor is changed once per range.

Cross-check against the published accuracy (SPECIFICATIONS, 1 year, 18-28 degC, +/-(% rdg + counts)): every printed limit is checked in Decimal: never looser
than the specification and within one display step of it.  The 2 uA row computes +/-0.00295 uA and is printed +/-0.0029 (rounded inward to the 0.0001 uA
display step); nothing is changed.  The builder aborts on any other disagreement.
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keithley_485_pv.json'
MODEL = '485'
TABLE = '3-2'
DOCUMENT = 'Keithley Model 485 Autoranging Picoammeter - Instruction Manual (485-901-01 Rev. F)'

# ---------------------------------------------------------------------------------------------------------------- the lab's resistance box (EDIT HERE)
# switch position (10^n) -> measured value in ohms, exactly as the box's calibration lists it.  Only 10^4 .. 10^10 are used by Table 3-2.
RESISTORS = {
    2: '100.0213',
    3: '999.802',
    4: '10001.29',
    5: '99974.57',
    6: '999634.5',
    7: '10014901',
    8: '99956900',
    9: '1010135000',
    10: '9932420000',
    11: '99707000000',
}
# switch position -> expanded uncertainty (k = 2, ~95 %) of the measured value from the box's calibration report: (relative part in ppm (uOhm/Ohm), absolute
# part in ohms).  A position missing here prints no Uncertainty / TAR / TUR on its points (the calibrator alone would understate it).
BOX = dict(name='Agilent 16340A RC Box', serial='1937J00597', asset='ATS-4225', certificate='Keysight WO-01470653', calibrated='2026-07-24')
RESISTOR_U = {
    2: ('66', '0.0001'),            # 100 ohm thru 10 kOhm: 0.0066 % + 0.1 mOhm
    3: ('66', '0.0001'),
    4: ('66', '0.0001'),
    5: ('1.2', '0'),                # 100 kOhm: 1.2 uOhm/Ohm
    6: ('1.66', '0'),               # 1 MOhm
    7: ('5.35', '0'),               # 10 MOhm
    8: ('60', '0'),                 # 100 MOhm
    9: ('193', '0'),                # 1 GOhm
    10: ('240', '0'),               # 10 GOhm
    11: ('206', '0'),               # 100 GOhm
}
RESISTOR_U_PPM = {pos: (D(rel) + D(ab) / D(RESISTORS[pos]) * D(10) ** 6) for pos, (rel, ab) in RESISTOR_U.items()}

VOLT_STEP = D('0.00001')          # calibrator setting rounded to 10 uV (finer than the 5520A / 5522A 33 V range step; < 1 ppm of 19 V)

# display unit -> (factor to base unit, base unit)
UNITS = {'nA': ('1E-9', 'A'), 'µA': ('1E-6', 'A'), 'mA': ('1E-3', 'A')}

# (range, display unit, required current (display unit), resistor position, printed low, printed high, accuracy % rdg, counts, resolution (display unit), settle s)
# Table 3-2, p. 3-2; accuracy and resolution from SPECIFICATIONS.
ROWS = [
    ('2 nA', 'nA', '1.9000', 10, '1.8920', '1.9080', '0.4', 4, '0.0001', 10),
    ('20 nA', 'nA', '19.000', 9, '18.923', '19.077', '0.4', 1, '0.001', 10),
    ('200 nA', 'nA', '190.00', 8, '189.61', '190.39', '0.2', 1, '0.01', 5),
    ('2 µA', 'µA', '1.9000', 7, '1.8971', '1.9029', '0.15', 1, '0.0001', 5),
    ('20 µA', 'µA', '19.000', 6, '18.980', '19.020', '0.1', 1, '0.001', 5),
    ('200 µA', 'µA', '190.00', 5, '189.80', '190.20', '0.1', 1, '0.01', 5),
    ('2 mA', 'mA', '1.9000', 4, '1.8980', '1.9020', '0.1', 1, '0.0001', 5),
]

SI = {0: '', 3: 'k', 6: 'M', 9: 'G'}


def fmt(d: D) -> str:
    return format(d.normalize(), 'f') if d != d.to_integral() else str(int(d))


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def ohms_text(r: D) -> str:
    e = max(k for k in SI if r >= D(10) ** k)
    return f'{fmt(r / D(10) ** e)} {SI[e]}Ω'


def position_text(n: int) -> str:
    return f'10^{n}'


def check_limits(rng, reading, low, high, pct, counts, res):
    """The printed limits against +/-(% rdg + counts x resolution): never looser, and within one display step."""
    half = D(pct) / 100 * reading + counts * D(res)
    lo, hi = D(low), D(high)
    if lo < reading - half or hi > reading + half:
        raise SystemExit(f'{rng}: printed {low} .. {high} is LOOSER than the specification +/-{half}')
    if lo >= reading - half + D(res) or hi <= reading + half - D(res):
        raise SystemExit(f'{rng}: printed {low} .. {high} is more than one display step inside the specification +/-{half}')
    return half


def group_for(rng, pos, r: D):
    key = f'R{pos}'
    return key, dict(
        title=f'Set up for the {rng} range: resistance box at {position_text(pos)}',
        summary=f'Calibrator NORMAL HI / LO -> resistance box at {position_text(pos)} ({ohms_text(r)}) in the shielded fixture -> low-noise coax -> 485 INPUT. 485 on the {rng} range.',
        steps=[
            ['Standby', 'The calibrator is put in STANDBY before you change the resistor (in manual-calibrator mode, put it in STANDBY yourself).'],
            ['Resistor', f'Set the {BOX["name"]} (asset {BOX["asset"]}) to the {position_text(pos)} position (measured value {ohms_text(r)}). It must be in a shielded (metal) enclosure, '
                         'as the test fixture of Figure 3-1 (p. 3-2). The calibrator setting is calculated from this measured value.'],
            ['Calibrator', 'Calibrator output HI -> resistor input (+), output LO -> the fixture LO (-), which is the BNC shield; the fixture case to the calibrator ground '
                           '(Figure 3-1: three banana jacks +, - and ground). (Which calibrator ground terminal: UNVERIFIED.)'],
            ['485 input', 'Fixture BNC output -> 485 INPUT with a low-noise coaxial cable such as the Keithley 4801 (step 8, p. 3-1). Keep the cable still during the reading.'],
            ['485 range', f'Release ZERO CHECK, REL and LOG off, then press the {rng} range button (manual range, not AUTO).'],
        ],
        caution='The calibrator applies about 19 V DC to the fixture. Do not exceed 30 V rms between the 485 input low and chassis ground (p. 2-3).')


def build_steps():
    steps, groups, n = [], {}, 0
    steps.append(dict(
        table='F', step=1, section='Zero check', switch='ZERO CHECK, 2nA range', range='', models=[MODEL], kind='VISUAL', test='visual',
        title='Zero check (2nA range, ZERO CHECK locked in)',
        setup=('Warm up the 485 for one hour (3.4, p. 3-1). INPUT open: no cable on the 485 INPUT. Select the 2nA range, REL and LOG off, '
               'press ZERO CHECK in to the locked position, adjust the front-panel ZERO trimpot for .0000 +/- 1 count, then release ZERO CHECK '
               '(steps 4 and 5, p. 3-1; 2.7.2, p. 2-4). The calibrator has no output.'),
        question='The 485 reads .0000 +/- 1 count on the 2nA range with ZERO CHECK in (after the ZERO adjustment).',
        setup_key='NONE', id='F-1'))
    for rng, unit, cur, pos, low, high, pct, counts, res, settle in ROWS:
        factor, base = UNITS[unit]
        r = D(RESISTORS[pos])
        reading = D(cur)
        half = check_limits(rng, reading, low, high, pct, counts, res)
        current = reading * D(factor)                                   # amperes
        volts = (current * r).quantize(VOLT_STEP, rounding=ROUND_HALF_UP)
        key, grp = group_for(rng, pos, r)
        groups[key] = grp
        word = 'count' if counts == 1 else 'counts'
        acc = f'±({pct} % rdg + {counts} {word})'
        for sign in (1, -1):
            n += 1
            s = D(sign)
            lo, hi = (low, high) if sign > 0 else ('-' + high, '-' + low)
            step = dict(table=TABLE, step=n, section='DC current', switch=f'{rng} range', range=rng, models=[MODEL], kind='DCV',
                        display_unit=unit, factor=float(D(factor)), base_unit=base, test='numeric', low=lo, high=hi, accuracy=acc,
                        tol_text=(f'Table 3-2 (p. 3-2): {lo} to {hi} {unit}   (specification {acc}, 1 year, 18-28 °C: ±{fmt(half)} {unit}; '
                                  f'resolution {res} {unit})'),
                        applied=dict(value=clean(s * volts), frequency=None),
                        nominal=clean(s * current),
                        dsb_out=f'{s * volts:.5f} V DC',          # the full 10 uV setting (the engine's own wording rounds to 6 figures)
                        resistor=dict(position=position_text(pos), ohms=clean(r), u_ppm=clean(RESISTOR_U_PPM[pos]) if pos in RESISTOR_U_PPM else None),
                        unc_kind='CURRENT_VIA_R',
                        report_desc=f'{rng} range, {"+" if sign > 0 else "-"}{cur} {unit}',
                        settle=settle, group=key,
                        note=(f'{"Positive" if sign > 0 else "Negative"} current. Calibrator {fmt(s * volts)} V DC through the {position_text(pos)} resistor '
                              f'({ohms_text(r)}): V = I x R = {cur} {unit} x {ohms_text(r)} (Table 3-2).'
                              + ('' if sign > 0 else ' Step 10 reverses the leads at the calibrator; the program sources the negative voltage instead.')),
                        ref=f'T3-2 {rng} {"+" if sign > 0 else "-"}', id=f'{TABLE}-{n}')
            steps.append(step)
    return steps, groups


def build_spec():
    steps, groups = build_steps()
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=False, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='Verification procedure p. 3-1; Table 3-1, Figure 3-1 and Table 3-2 p. 3-2; Zero Check p. 2-4; Specifications (front of the manual)',
                    cite='Keithley 485 Instruction Manual, Table 3-2 Range Accuracy, p. 3-2',
                    limits='Printed in Table 3-2 (Allowable Readings, 18-28 °C); checked against the published 1-year accuracy',
                    report_note=('Keithley 485 performance verification, Section 3.5 and Table 3-2 of the Instruction Manual: each range is driven by a DC calibrator '
                                 'through a measured resistor (calibrator setting V = I x R), positive and negative current. Limits are the Allowable Readings of Table 3-2.'),
                    note=('Table 3-2: 7 ranges, positive and negative current (14 points) plus the zero check. The DC calibrator (Fluke 5560A, 5522A or 5520A) sources '
                          'V = I x R through the lab\'s resistance box (measured values in specs/build_keithley_485_spec.py); the technician selects the range and types the reading.')),
        models={MODEL: dict(name='Keithley 485', brand='Keithley', model_note='Keithley Model 485 Autoranging Picoammeter (4 1/2 digit, 2 nA to 2 mA)')},
        groups=groups,
        resistance_box=dict(BOX, ohms={position_text(k): clean(D(v)) for k, v in RESISTORS.items()},
                            u_ppm_k2={position_text(k): clean(v) for k, v in RESISTOR_U_PPM.items()}),
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print('wrote', OUT, len(spec['steps']), 'points')
    for s in spec['steps']:
        if s['test'] == 'numeric':
            print(f"  {s['id']:7} {s['range']:7} {s['applied']['value']:>12} V  {s['low']:>8} .. {s['high']:<8} {s['display_unit']}")


if __name__ == '__main__':
    main()
