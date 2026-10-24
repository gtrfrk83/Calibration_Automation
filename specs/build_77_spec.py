"""Builds specs/fluke_77iv_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke Model 77 Series IV Calibration Information.

    python3 specs/build_77_spec.py

Source: Fluke Model 77 Series IV Digital Multimeter, Calibration Information (20 pages, Rev. 11/2006)
  Table 2 "Performance Tests", printed pp. 12-13 (35 steps; the 5500A output, lower limit and upper limit of every step);
  Table 1 "Calibrator Specifications", p. 11; the specification tables, pp. 4-6 (ranges, resolution, accuracy).
Every nominal, frequency and limit below was read from the RENDERED PAGE IMAGES of those pages (pdftoppm, 130 and 260 dpi), twice, never from
extracted text (the units mu and Omega do not survive text extraction). What the table does not say (calibrator output kind, wiring group, which
dial position and yellow-button state to select) is added here and shown to the technician as a note.

One correction to the printed table, flagged in the spec, the on-screen source note and the report header:
  step 8 (AC volts, 50 mV at 45 Hz) prints "0.47 V ac" to "0.53 V ac".  A 50 mV input on the 6.000 V range (the lowest AC range, p. 5) reads about
  0.050 V, so no meter could pass 0.47 to 0.53 V: the decimal point is evidently a typo.  The limits used are 0.047 to 0.053 V ac, which is
  exactly the manual's own method for every other row (2.0 % of reading + 2 counts of 0.001 V = 0.003 V; see check_against_specification below).
  The printed text is kept in the step ('printed_limits') and the decision is listed for the lab owner.
The 77 IV is autoranging: Table 2 names no range, so each step's 'range' is the range the reading falls in (specification table, p. 5).
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_77iv_pv.json'
MODEL = '77IV'
TABLE = '2'

# display unit -> (factor to base unit, base unit)
UNITS = {'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'MΩ': ('1000000', 'ohm'), 'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'kHz': ('1000', 'Hz'),
         'nF': ('0.000000001', 'F'), 'mA': ('0.001', 'A'), 'A': ('1', 'A')}

# dial position / function text shown by the "Change the function" prompt; the engine asks again whenever this text changes between two points
SW = {
    'ohm': 'Ω  (dial: Ω / capacitance position)',
    'cont': 'Continuity  •)))  (dial: continuity / diode position)',
    'acv': 'V~  (dial: Hz V~ position)',
    'hz': 'Hz  (dial: Hz V~ position; press the YELLOW button)',
    'dcv': 'V⎓  (dial: V⎓ position)',
    'mv': 'mV⎓  (dial: mV⎓ position)',
    'cap': 'Capacitance  ⊣⊢  (dial: Ω / capacitance position; press the YELLOW button)',
    'acma': 'mA~  (dial: mA position, AC)',
    'aca': 'A~  (dial: A position, AC)',
    'dcma': 'mA⎓  (dial: mA position; press the YELLOW button)',
    'dca': 'A⎓  (dial: A position; press the YELLOW button)',
}

NOTE_LEADS = 'Table 2 note: avoid coupled noise on AC current by leaving the VΩ input unconnected (or shorting it to COM).'
NOTE_YELLOW = 'Table 2 footnote 1: press the YELLOW button to access this function.'
NOTE_OHMS = 'The limits do not include test lead resistance (Table 2 note 2).'
NOTE_ACDC_AC = 'Table 2 gives no yellow-button step for AC (only DC milliamps / DC amps carry footnote 1): the display should show AC (~).'

# (step, section, switch, range, kind, applied value (base units), applied frequency (Hz), display unit, low, high, accuracy (pct, counts, resolution), extras)
# low / high are the strings printed in Table 2 (as read from the page image) except where 'corrected' is given.
ROWS = [
    (1, 'Ohms', 'ohm', '600.0 Ω', 'OHM', 500, None, 'Ω', '497.3', '502.7', ('0.5', 2, '0.1'), dict(note=NOTE_OHMS)),
    (2, 'Ohms', 'ohm', '60.00 kΩ', 'OHM', 50000, None, 'kΩ', '49.74', '50.26', ('0.5', 1, '0.01'), dict(note=NOTE_OHMS)),
    (3, 'Ohms', 'ohm', '6.000 MΩ', 'OHM', 5000000, None, 'MΩ', '4.974', '5.026', ('0.5', 1, '0.001'), dict(note=NOTE_OHMS)),
    (4, 'Ohms', 'ohm', '50.00 MΩ', 'OHM', 10000000, None, 'MΩ', '9.79', '10.21', ('2.0', 1, '0.01'), dict(note=NOTE_OHMS)),
    (5, 'Ohms', 'ohm', '50.00 MΩ', 'OHM', 40000000, None, 'MΩ', '39.19', '40.81', ('2.0', 1, '0.01'), dict(note=NOTE_OHMS)),
    (6, 'Continuity', 'cont', '600 Ω', 'BEEP', 25, None, 'Ω', None, None, None, dict(expect='on')),
    (7, 'Continuity', 'cont', '600 Ω', 'BEEP', 250, None, 'Ω', None, None, None, dict(expect='off')),
    (8, 'AC volts', 'acv', '6.000 V', 'ACV', 0.05, 45, 'V', '0.47', '0.53', ('2.0', 2, '0.001'),
     dict(corrected=('0.047', '0.053'), report_desc='6.000 V range (limits corrected)',
          note='LIMIT CORRECTED: Table 2 prints 0.47 to 0.53 V ac for this 50 mV input, which no meter could meet (it reads about 0.050 V on the 6.000 V range). '
               'The limits used are 0.047 to 0.053 V (2.0 % of reading + 2 counts of 0.001 V, the manual\'s own method; p. 5). Confirm with your supervisor.')),
    (9, 'AC volts', 'acv', '6.000 V', 'ACV', 5, 45, 'V', '4.898', '5.102', ('2.0', 2, '0.001'), {}),
    (10, 'AC volts', 'acv', '6.000 V', 'ACV', 5, 1000, 'V', '4.898', '5.102', ('2.0', 2, '0.001'), {}),
    (11, 'AC volts', 'acv', '60.00 V', 'ACV', 50, 45, 'V', '48.98', '51.02', ('2.0', 2, '0.01'), {}),
    (12, 'AC volts', 'acv', '60.00 V', 'ACV', 50, 1000, 'V', '48.98', '51.02', ('2.0', 2, '0.01'), {}),
    (13, 'AC volts', 'acv', '600.0 V', 'ACV', 500, 45, 'V', '489.8', '510.2', ('2.0', 2, '0.1'), {}),
    (14, 'AC volts', 'acv', '600.0 V', 'ACV', 500, 1000, 'V', '489.8', '510.2', ('2.0', 2, '0.1'), {}),
    (15, 'AC volts', 'acv', '1000 V', 'ACV', 1000, 45, 'V', '978', '1022', ('2.0', 2, '1'), {}),
    (16, 'AC volts', 'acv', '1000 V', 'ACV', 1000, 1000, 'V', '978', '1022', ('2.0', 2, '1'), {}),
    (17, 'AC volts frequency', 'hz', '99.99 kHz', 'ACV', 5, 50000, 'kHz', '49.94', '50.06', ('0.1', 1, '0.01'),
     dict(nominal=50000.0, note='The meter displays FREQUENCY on this step (the calibrator applies 5 V at 50 kHz). ' + NOTE_YELLOW,
          report_desc='99.99 kHz range (5 V applied)', unc_kind='FREQ')),
    (18, 'DC volts', 'dcv', '6.000 V', 'DCV', 5, None, 'V', '4.984', '5.016', ('0.3', 1, '0.001'), {}),
    (19, 'DC volts', 'dcv', '600.0 V', 'DCV', 300, None, 'V', '299.0', '301.0', ('0.3', 1, '0.1'), {}),
    (20, 'DC volts', 'dcv', '1000 V', 'DCV', 1000, None, 'V', '996', '1004', ('0.3', 1, '1'), {}),
    (21, 'DC volts', 'dcv', '1000 V', 'DCV', -1000, None, 'V', '-1004', '-996', ('0.3', 1, '1'), {}),
    (22, 'DC millivolts', 'mv', '600.0 mV', 'DCV', 0.03, None, 'mV', '29.8', '30.2', ('0.3', 1, '0.1'), {}),
    (23, 'DC millivolts', 'mv', '600.0 mV', 'DCV', -0.3, None, 'mV', '-301.0', '-299.0', ('0.3', 1, '0.1'), {}),
    (24, 'DC millivolts', 'mv', '600.0 mV', 'DCV', 0.6, None, 'mV', '598.1', '601.9', ('0.3', 1, '0.1'), {}),
    (25, 'Capacitance', 'cap', '1000 nF', 'CAP', 9e-07, None, 'nF', '887', '913', ('1.2', 2, '1'),
     dict(settle=10, note='Apply 900 nF. ' + NOTE_YELLOW)),
    (26, 'AC milliamps', 'acma', '60.00 mA', 'ACI', 0.0005, 45, 'mA', '0.47', '0.53', ('2.5', 2, '0.01'), dict(note=NOTE_ACDC_AC + ' ' + NOTE_LEADS)),
    (27, 'AC milliamps', 'acma', '60.00 mA', 'ACI', 0.05, 1000, 'mA', '48.73', '51.27', ('2.5', 2, '0.01'), dict(note=NOTE_ACDC_AC + ' ' + NOTE_LEADS)),
    (28, 'AC milliamps', 'acma', '400.0 mA', 'ACI', 0.4, 1000, 'mA', '389.8', '410.2', ('2.5', 2, '0.1'), dict(note=NOTE_ACDC_AC + ' ' + NOTE_LEADS)),
    (29, 'AC amps', 'aca', '6.000 A', 'ACI', 4, 45, 'A', '3.898', '4.102', ('2.5', 2, '0.001'), dict(settle=5, note=NOTE_LEADS)),
    (30, 'AC amps', 'aca', '10.00 A', 'ACI', 9, 1000, 'A', '8.75', '9.25', ('2.5', 2, '0.01'), dict(settle=5, note=NOTE_LEADS)),
    (31, 'DC milliamps', 'dcma', '60.00 mA', 'DCI', 0.003, None, 'mA', '2.93', '3.07', ('1.5', 2, '0.01'), dict(note=NOTE_YELLOW + ' The table lists 3 mA at 0 Hz (DC).')),
    (32, 'DC milliamps', 'dcma', '60.00 mA', 'DCI', 0.05, None, 'mA', '49.23', '50.77', ('1.5', 2, '0.01'), dict(note=NOTE_YELLOW)),
    (33, 'DC milliamps', 'dcma', '400.0 mA', 'DCI', -0.4, None, 'mA', '-406.2', '-393.8', ('1.5', 2, '0.1'), dict(note=NOTE_YELLOW)),
    (34, 'DC amps', 'dca', '6.000 A', 'DCI', 4, None, 'A', '3.938', '4.062', ('1.5', 2, '0.001'), dict(settle=5, note=NOTE_YELLOW)),
    (35, 'DC amps', 'dca', '10.00 A', 'DCI', -9, None, 'A', '-9.16', '-8.84', ('1.5', 2, '0.01'), dict(settle=5, note=NOTE_YELLOW)),
]
GROUP = {'OHM': 'VOHM', 'BEEP': 'VOHM', 'ACV': 'VOHM', 'DCV': 'VOHM', 'CAP': 'VOHM'}      # currents: UAMP up to 400 mA, AMP10 for the A input


def group_for(kind, value, unit):
    if kind in ('ACI', 'DCI'):
        return 'AMP10' if unit == 'A' else 'UAMP'
    return GROUP[kind]


def fmt(d: D) -> str:
    return format(d.normalize(), 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def check_against_specification(step_no, display_unit, applied, low, high, accuracy):
    """The manual's own method (pp. 5, 12-13): limit = +/-(% of reading + counts x resolution), printed rounded to the display resolution.
    Returns a list of problems (empty when both printed limits are within half a display step of the computed ones).
    Used by the builder and by tests/test_77_points.py."""
    pct, counts, res = D(accuracy[0]), accuracy[1], D(accuracy[2])
    reading = D(str(applied)) / D(UNITS[display_unit][0])        # the applied value in the display unit
    expect = pct / 100 * abs(reading) + counts * res
    problems = []
    for name, printed in (('low', reading - D(low)), ('high', D(high) - reading)):
        if abs(printed - expect) > res / 2:
            problems.append(f'step {step_no}: the {name} limit is {printed} {display_unit} from the nominal, the specification gives {expect}')
    return problems


def build_steps():
    steps, problems = [], []
    for n, section, sw, rng, kind, value, freq, unit, low, high, accuracy, extra in ROWS:
        factor, base = UNITS[unit]
        engine_kind = 'OHM' if kind == 'BEEP' else kind
        step = dict(table=TABLE, step=n, section=section, switch=SW[sw], range=rng, models=[MODEL], kind=engine_kind)
        if kind == 'BEEP':
            step.update(test='beeper', expect=extra['expect'], applied=dict(value=value, frequency=None), nominal=value, base_unit=base,
                        display_unit=unit, factor=float(D(factor)),
                        question='The beeper is ON (sounding).' if extra['expect'] == 'on' else 'The beeper is OFF (silent).')
        else:
            used_low, used_high = extra.get('corrected', (low, high))
            problems += check_against_specification(n, unit, extra.get('nominal', value), used_low, used_high, accuracy)
            if 'corrected' in extra:                      # the printed limits must be the ones that DISAGREE with the specification (that is why they are corrected)
                assert check_against_specification(n, unit, extra.get('nominal', value), low, high, accuracy), f'step {n}: the printed limits agree with the specification, nothing to correct'
            step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=used_low, high=used_high, test='numeric',
                        applied=dict(value=clean(value), frequency=float(freq) if freq else None), nominal=extra.get('nominal', clean(value)))
            pct, counts, res = accuracy
            word = 'count' if counts == 1 else 'counts'
            step['accuracy'] = f'±({pct} % of reading + {counts} {word})'
            step['tol_text'] = (f'Table 2: {used_low} to {used_high} {unit}   (specification p. 5: ±({pct} % of reading + {counts} {word} of {res} {unit}))')
            if 'corrected' in extra:
                step['printed_limits'] = dict(low=low, high=high, unit=unit, note='as printed in Table 2 (p. 12); a typo: see note')
        step['group'] = group_for(kind, value, unit)
        if 'settle' in extra:
            step['settle'] = extra['settle']
        if 'note' in extra:
            step['note'] = extra['note']
        if 'report_desc' in extra:
            step['report_desc'] = extra['report_desc']
        if extra.get('unc_kind'):                     # the reading is a frequency: its uncertainty is the Frequency - Measure CMC alone (see NOTES.md)
            step['unc_kind'] = extra['unc_kind']
        step['ref'] = f'T{TABLE} #{n}'
        step['id'] = f'{TABLE}-{n}'
        steps.append(step)
    return steps, problems


def build_spec():
    steps, problems = build_steps()
    if problems:
        raise SystemExit('Table 2 limits disagree with the specification table (p. 5):\n  ' + '\n  '.join(problems))
    return dict(
        schema=2, kind='manual-reading',
        options=dict(hookup_meter='fluke77', hv_threshold_v=30, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document='Fluke Model 77 Series IV Digital Multimeter - Calibration Information',
                    pages='11-13 (printed): Table 1 p. 11, Table 2 Performance Tests pp. 12-13; specifications pp. 4-6',
                    cite='Fluke Model 77 Series IV Calibration Information, Table 2, pp. 12-13 (step 8 limits corrected from the printed 0.47 / 0.53 V ac to 0.047 / 0.053 V ac)',
                    limits='Manufacturer limits, Table 2 (1 year); step 8 corrected, see Source',
                    report_note=('Limits are those of the manufacturer\'s Table 2 (Fluke 77 Series IV Calibration Information, pp. 12-13) with one correction: step 8 (AC volts, 50 mV at 45 Hz) '
                                 'is printed as 0.47 to 0.53 V ac, which cannot apply to a 50 mV input; 0.047 to 0.053 V ac (2 % of reading + 2 counts of 0.001 V, manual p. 5) was used.'),
                    note='Table 2 Performance Tests, 35 steps: 33 numeric readings and 2 continuity (beeper) checks; limits as printed except step 8: the printed 0.47 to 0.53 V ac '
                         'at 50 mV cannot be right and 0.047 to 0.053 V ac (2 % + 2 counts, p. 5) is used. The meter is autoranging: each range shown is the one the reading falls '
                         'in (p. 5). The manual names a Fluke 5500A; the procedure drives a Fluke 5522A or 5560A (or you set the calibrator by hand). '
                         'High-voltage points go straight to the test value (the manual prescribes no ramp).'),
        models={MODEL: dict(name='Fluke 77 Series IV', brand='Fluke', model_note='Fluke Model 77 Series IV autoranging digital multimeter (6000 counts)')},
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
    kinds = {}
    for s in spec['steps']:
        kinds[s['section']] = kinds.get(s['section'], 0) + 1
    print('wrote', OUT, len(spec['steps']), 'points', kinds)


if __name__ == '__main__':
    main()
