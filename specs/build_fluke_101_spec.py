"""Builds specs/fluke_101_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 101 Digital Multimeter Users Manual.

    python3 specs/build_fluke_101_spec.py

Source: Fluke 101 Digital Multimeter Users Manual (Rev. 2, 12/22; 26 PDF pages)
  Accuracy Specifications, printed pp. 20-22 (PDF pp. 24 and 26: range, resolution, accuracy of every function; PDF p. 25 is the overload / input impedance table);
  Rotary Switch, Figure 2 and Table 2, printed pp. 6-7; Measurements, printed pp. 8-14 (terminals, continuity, diode test, capacitance settle time).
Every range, resolution and accuracy figure below was read from the RENDERED PAGE IMAGES (130 dpi), twice, never from extracted text.

THE MANUAL HAS NO CALIBRATION PROCEDURE AND NO PERFORMANCE-VERIFICATION TABLE (it is a Users Manual).  The test points are the owner's choice (2026-10-28):
  one point per range at 90 % of the range; AC volts and AC millivolts at 60 Hz and 400 Hz (inside the specified 40 Hz to 500 Hz); the frequency ranges at 90 % of
  each range.  The LIMITS are the published 1-year accuracy specification applied to the applied value: +/-(% of reading + counts x resolution), computed here in Decimal.
  The limits are the FULL specification (no 2:1 test margin as in a manufacturer's performance table).  A limit that does not fall on a display step is rounded INWARD
  to the display resolution (low up, high down), so a reading is never accepted that the specification rejects.
What the manual does NOT have, and is therefore not built (listed in the final report):
  * AC and DC current: the Fluke 101 has no current function and no current jack (only VΩ and COM, p. 3).
  * Duty cycle ('1 % typical' at 50 / 60 Hz and 10 % to 90 % duty, p. 22), continuity (beeper below 70 ohm, p. 10): no per-range point was asked for.
"""
from __future__ import annotations

import json
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_101_pv.json'
MODEL = '101'
TABLE = '1'
POINT = D('0.9')                          # every point is 90 % of its range

# display unit -> (factor to base unit, base unit)
UNITS = {'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'MΩ': ('1000000', 'ohm'), 'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'Hz': ('1', 'Hz'), 'kHz': ('1000', 'Hz'),
         'nF': ('0.000000001', 'F'), 'µF': ('0.000001', 'F')}

# dial position text shown by the 'turn the meter to' prompt (Figure 2, p. 6: OFF, V~, V⎓, mV~, Ω (with the diode and continuity symbols), capacitance, Hz; the YELLOW button is item 7)
SW = {
    'acv': 'V~  (AC volts)',
    'dcv': 'V⎓  (DC volts)',
    'acmv': 'mV~  (AC millivolts)',
    'ohm': 'Ω  (ohms)',
    'diode': 'Diode  ▶|  (dial: Ω position; push the YELLOW button twice)',
    'cap': 'Capacitance  ⊣⊢  (dial: capacitance position)',
    'hz': 'Hz  (dial: Hz position)',
}

NOTE_YELLOW_DIODE = 'Turn the dial to Ω, then push the YELLOW button twice to activate the diode test mode (Test Diodes, p. 12). The meter shows the voltage across the diode test input; the calibrator applies 1.8 V DC.'
NOTE_CAP = ('Let the reading stabilize (up to 18 seconds, p. 12). The specification does not include test lead capacitance or the capacitance floor (up to 1.5 nF on the 50 nF range, p. 22 note 1): '
            'null the leads as you would on the bench if the lab practice does so (UNVERIFIED: the manual describes no REL step).')
NOTE_HZ = 'The meter displays FREQUENCY on this step: the calibrator applies {v} at {f}. Specified from 10 Hz to 100 kHz (p. 22).'
NOTE_FLOOR = 'Specified from 1 % to 100 % of range (p. 20, p. 22 note 2); this point is at 90 %.'

# published specification: key -> (percent of reading, counts)
ACC = {'ACV': ('1.0', 3), 'DCV': ('0.5', 3), 'ACMV': ('3.0', 3), 'DIODE': ('10', 0),
       'OHM400': ('0.5', 3), 'OHM_K': ('0.5', 2), 'OHM40M': ('1.5', 3),
       'CAP_N': ('2', 5), 'CAP_U': ('5', 5), 'HZ': ('0.1', 3)}

# rows follow the dial (Figure 2): V~, V⎓, mV~, Ω, diode (Ω position), capacitance, Hz
# (section, switch key, range text, full scale (display unit), kind, frequency (Hz or None), display unit, resolution (display unit), accuracy key, extras)
# the applied value is 90 % of the full scale of the range
ROWS = []
for rng, fs, res in (('6.000 V', '6', '0.001'), ('60.00 V', '60', '0.01'), ('600.0 V', '600', '0.1')):
    for f in (60, 400):
        ROWS.append(('AC volts', 'acv', rng, fs, 'ACV', f, 'V', res, 'ACV', {}))
for rng, fs, res in (('6.000 V', '6', '0.001'), ('60.00 V', '60', '0.01'), ('600.0 V', '600', '0.1')):
    ROWS.append(('DC volts', 'dcv', rng, fs, 'DCV', None, 'V', res, 'DCV', {}))
for f in (60, 400):
    ROWS.append(('AC millivolts', 'acmv', '600.0 mV', '600', 'ACV', f, 'mV', '0.1', 'ACMV', {}))
for rng, fs, unit, res, key in (('400.0 Ω', '400', 'Ω', '0.1', 'OHM400'), ('4.000 kΩ', '4', 'kΩ', '0.001', 'OHM_K'), ('40.00 kΩ', '40', 'kΩ', '0.01', 'OHM_K'),
                                ('400.0 kΩ', '400', 'kΩ', '0.1', 'OHM_K'), ('4.000 MΩ', '4', 'MΩ', '0.001', 'OHM_K'), ('40.00 MΩ', '40', 'MΩ', '0.01', 'OHM40M')):
    ROWS.append(('Ohms', 'ohm', rng, fs, 'OHM', None, unit, res, key, {}))
ROWS.append(('Diode test', 'diode', '2.000 V', '2', 'DCV', None, 'V', '0.001', 'DIODE', dict(note=NOTE_YELLOW_DIODE)))
for rng, fs, unit, res, key in (('50.00 nF', '50', 'nF', '0.01', 'CAP_N'), ('500.0 nF', '500', 'nF', '0.1', 'CAP_N'), ('5.000 µF', '5', 'µF', '0.001', 'CAP_U'),
                                ('50.00 µF', '50', 'µF', '0.01', 'CAP_U'), ('500.0 µF', '500', 'µF', '0.1', 'CAP_U'), ('1000 µF', '1000', 'µF', '1', 'CAP_U')):
    ROWS.append(('Capacitance', 'cap', rng, fs, 'CAP', None, unit, res, key, dict(settle=20, note=NOTE_CAP)))
for rng, fs, unit, res in (('50.00 Hz', '50', 'Hz', '0.01'), ('500.0 Hz', '500', 'Hz', '0.1'), ('5.000 kHz', '5', 'kHz', '0.001'),
                           ('50.00 kHz', '50', 'kHz', '0.01'), ('100.0 kHz', '100', 'kHz', '0.1')):
    ROWS.append(('Frequency', 'hz', rng, fs, 'ACV', None, unit, res, 'HZ', dict(hzread=True)))
# the frequency rows apply 5 V (a sine) at 90 % of the range frequency
HZ_LEVEL_V = D('5')


def fmt(d: D) -> str:
    return format(d.normalize(), 'f') if d != d.to_integral() else str(int(d))


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def quantize(x: D, res: D, rounding) -> D:
    return (x / res).to_integral_value(rounding=rounding) * res


def limits(reading: D, acc, res: D):
    """+/-(% of reading + counts x resolution), rounded INWARD to the display resolution (low up, high down)."""
    pct, counts = D(acc[0]), acc[1]
    half = pct / 100 * abs(reading) + counts * res
    return quantize(reading - half, res, ROUND_CEILING), quantize(reading + half, res, ROUND_FLOOR), half


def build_steps():
    steps, n = [], 0
    for section, sw, rng, fs, kind, freq, unit, res, key, extra in ROWS:
        n += 1
        factor, base = UNITS[unit]
        full = D(fs)
        reading = full * POINT                                        # 90 % of range, in the display unit
        resd = D(res)
        # the range text and the full scale must agree
        assert rng.startswith(fs), (rng, fs)
        step = dict(table=TABLE, step=n, section=section, switch=SW[sw], range=rng, models=[MODEL], kind=kind, display_unit=unit, factor=float(D(factor)), base_unit=base, test='numeric')
        lo, hi, half = limits(reading, ACC[key], resd)
        dec = max(0, -resd.as_tuple().exponent)                       # limits carry the display resolution's decimals (the engine pads typed readings to them)
        step['low'], step['high'] = f'{lo:.{dec}f}', f'{hi:.{dec}f}'
        pct, counts = ACC[key]
        word = 'count' if counts == 1 else 'counts'
        acc_text = f'±({pct} % of reading + {counts} {word})' if counts else f'±({pct} % of reading)'
        step['accuracy'] = acc_text
        step['tol_text'] = (f'Specification p. {22 if sw in ("ohm", "cap", "hz") else 20}: {step["low"]} to {step["high"]} {unit} at 90 % of range   '
                            f'({acc_text}, resolution {res} {unit}; limits rounded inward to the display step)')
        notes = []
        if extra.get('hzread'):
            f_hz = reading * D(factor)
            v_text = f'{fmt(HZ_LEVEL_V)} V'
            f_text = f'{fmt(reading)} {unit}'
            step['applied'] = dict(value=clean(HZ_LEVEL_V), frequency=float(f_hz))
            step['nominal'] = float(f_hz)
            step['no_freq_suffix'] = True
            step['unc_kind'] = 'FREQ'
            step['report_desc'] = f'{rng} range ({v_text} applied)'
            notes.append(NOTE_HZ.format(v=v_text, f=f_text) + ' The input level and waveform for the frequency counter are not given in the manual (UNVERIFIED).')
        else:
            applied = reading * D(factor)
            if sw == 'diode':
                applied = D('1.8')                                    # 90 % of the 2.000 V range
            step['applied'] = dict(value=clean(applied), frequency=float(freq) if freq else None)
            step['nominal'] = clean(applied)
            if freq:
                notes.append(NOTE_FLOOR + ' AC specified 40 Hz to 500 Hz.')
        if 'note' in extra:
            notes.insert(0, extra['note'])
        if 'settle' in extra:
            step['settle'] = extra['settle']
        step['group'] = 'VOHM'
        if notes:
            step['note'] = ' '.join(notes)
        step['ref'] = f'Spec #{n}'
        step['id'] = f'{TABLE}-{n}'
        steps.append(step)
    return steps


def build_spec():
    steps = build_steps()
    return dict(
        schema=2, kind='manual-reading',
        options=dict(hookup_meter='fluke101', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document='Fluke 101 Digital Multimeter - Users Manual (Rev. 2, 12/22)',
                    pages='Accuracy Specifications printed pp. 20-22; Rotary Switch pp. 6-7; Measurements pp. 8-14',
                    cite='Fluke 101 Users Manual, Accuracy Specifications, pp. 20 and 22 (limits computed from the published 1-year accuracy; the manual has no performance-verification table)',
                    limits='Computed from the manufacturer\'s published 1-year accuracy specification at 90 % of each range (no 2:1 test margin)',
                    report_note=('The Fluke 101 Users Manual has no calibration procedure. Test points: one per range at 90 % of the range (AC volts and AC millivolts at 60 Hz and 400 Hz). '
                                 'Limits are the manufacturer\'s published 1-year accuracy specification (Users Manual pp. 20 and 22), +/-(% of reading + counts), rounded inward to the display step.'),
                    note='The Fluke 101 Users Manual has no performance-verification table. The 90 % test points were chosen by the lab owner; the limits are the published 1-year accuracy '
                         'specification applied to each point (p. 20, p. 22). The meter has no current function. The Fluke 5522A or 5560A drives every point (or you set the calibrator by hand). '
                         'High-voltage points go straight to the test value.'),
        models={MODEL: dict(name='Fluke 101', brand='Fluke', model_note='Fluke 101 Digital Multimeter (6000 counts, CAT III 600 V)')},
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT, len(spec['steps']), 'points', count)


if __name__ == '__main__':
    main()
