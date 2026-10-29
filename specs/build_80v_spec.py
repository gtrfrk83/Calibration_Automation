"""Builds specs/fluke_80_series_v_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 80 Series V Calibration Manual.

    python3 specs/build_80v_spec.py

Source: Fluke 80 Series V Digital Multimeter Calibration Manual (September 2004, Rev. 4, 11/25), 22 pages:
  Table 1 "Required Equipment" printed p. 6 (Fluke 5560A, Fluke 80AK, K-type thermocouple), "Testing the Display" p. 7, "Testing the Pushbuttons" p. 9,
  Table 3 "Accuracy Tests" printed pp. 9-11 (steps 1-53; 33B; no step 48), footnotes 1-7 p. 11.
Every nominal, frequency and limit below was read from the RENDERED PAGE IMAGES of those pages (pypdfium2, 2.2x), twice, never from extracted text
(the units mu and Omega and the function symbols do not survive text extraction).

One family spec, three models.  Table 3 prints two Display Reading columns: '83 and 88' and '87'.
  * A row whose two columns differ becomes two steps (ids '3-<step>.87' for the 87V, '3-<step>.83' for the 83V and 88V); otherwise the id is '3-<step>'.
  * 'N/A' in the 83 and 88 column (steps 2, 4, 6, 8 AC volts at high frequency, 45 and 46 low pass filter) = 87V only.
  * Step 47 Peak Min/Max: '87 and 88 only'; footnote 7 'The Fluke-83 V does not have a Peak Min/Max function' -> 87V and 88V.
  * Steps 49 / 50 temperature: '87 and 88 only' -> 87V and 88V.
Not built: 'Testing the Inductive Pickup (88 Only)' (printed pp. 11-14: function generator burst into a 10 ohm loop, oscilloscope reading of the pickup output).
It needs an oscilloscope and a function generator, not the calibrator, and is left for the owner to decide (see the report).

The published accuracy specifications (80 Series V Users Manual) are NOT in the calibration manual and were not supplied, so the limits are not checked
against them here: the build checks only that every numeric limit pair brackets its nominal reading and (where the row is a plain accuracy test) is
symmetric about it, to within the display resolution.  The low pass filter rows are not symmetric (step 45 printed 372 to 408 V at 400 V; step 46 is a roll-off check, footnote 4, whose range does not
contain the 400 V applied) and the open-input rows have no nominal: those are stored as printed and not checked.
Format only (same number): '04.7 to 05.3' and '09.2 to 09.8' (capacitance, the meter shows the leading zero) are written 4.7 / 5.3 and 9.2 / 9.8;
the printed text is kept in 'printed_text'.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_80_series_v_pv.json'
DOCUMENT = 'Fluke 80 Series V Digital Multimeter - Calibration Manual (September 2004, Rev. 4, 11/25)'
MODELS = ('83V', '87V', '88V')
COL_83 = ('83V', '88V')                    # the '83 and 88' Display Reading column
COL_87 = ('87V',)

# display unit -> (factor to base unit, base unit)
UNITS = {'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'MΩ': ('1000000', 'ohm'), 'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'Hz': ('1', 'Hz'), 'kHz': ('1000', 'Hz'),
         'nF': ('0.000000001', 'F'), 'µF': ('0.000001', 'F'), 'µA': ('0.000001', 'A'), 'mA': ('0.001', 'A'), 'A': ('1', 'A'), '°C': ('1', 'degC'),
         'nS': ('0.000000001', 'S'), '%': ('1', '%')}

# rotary switch / function text shown by the "Change the function" prompt.  The names are Table 3's own 'Test Function' column; the manual has no
# figure of the dial and does not say which positions need the yellow (shift) button, so the button sequence is NOT verified (see NOTE_DIAL).
SW = {
    'acv': 'V~  (AC volts)',
    'hzac': 'V~ Hz  (AC volts frequency)',
    'hzdc': 'V⎓ Hz  (DC volts frequency)',
    'duty': 'V⎓ Hz  (DC volts duty cycle)',
    'dcv': 'V⎓  (DC volts)',
    'mv': 'mV⎓  (DC millivolts)',
    'ohm': 'Ω  (Ohms)',
    'ns': 'nS  (Conductance)',
    'diode': 'Diode  ▶|',
    'aca': 'A~  (AC amps)',
    'dca': 'A⎓  (DC amps)',
    'acma': 'mA~  (AC milliamps)',
    'dcma': 'mA⎓  (DC milliamps)',
    'acua': 'µA~  (AC microamps)',
    'dcua': 'µA⎓  (DC microamps)',
    'cap': 'Capacitance  ⊣⊢',
    'lpf': 'V~  (AC volts, low pass filter)',
    'peak': 'V⎓  (DC volts, Peak Min/Max)',
    'temp': 'mV⎓  (Temperature)',
}
NOTE_DIAL = ('Function names are the manual\'s own (Table 3, "Test Function"); the manual has no dial figure and names no button sequence, '
             'so confirm the position (and any yellow-button press) on the real meter.')
NOTE_OHMS_COMP = 'Table 3 footnote 1: use 2-wire compensation at the calibrator (the program sets it), or short the test leads and use REL to offset the lead resistance.'
NOTE_CAP_REL = ('Table 3 footnote 5: use REL to compensate for the internal meter and lead capacitance. The test leads must be disconnected from the calibrator '
                'before using REL.')
NOTE_10A = ('Table 3 footnote 6: 10 A continuous up to 35 °C; < 20 minutes on, 5 minutes off at 35 °C to 55 °C. 20 A for 30 seconds maximum; > 10 A unspecified.')
NOTE_LPF = ('Select the low pass filter on the AC volts function (the K / LPF indicator, Table 2 item 11, shows it is on).')
NOTE_LPF_800 = ('Table 3 footnote 4: the meter accuracy is not specified at this input frequency with the low pass filter selected. The reading shows the '
                'filter is active and follows the expected roll-off curve; it is judged against the printed range 226 to 340 V.')
NOTE_TEMP = ('Table 3 footnote 3: to ensure an accurate measurement, the meter and the thermocouple adapter must be at the same temperature. After connecting the '
             'thermocouple adapter (Fluke 80AK, K-type thermocouple with a mini-plug on both ends, Table 1) allow the reading to stabilise before recording it. '
             'The calibrator sources degrees C: set the meter to °C.')
NOTE_HZ = 'The meter displays FREQUENCY on this step (the calibrator applies {v} at {f}).'
NOTE_AC_CURRENT = 'The meter shows LEAd if the leads are in the A or mA µA jack and the rotary switch does not match the jack in use (Table 2, error messages).'

# Table 3 rows: (manual step, section, switch, range, kind, applied value (base units), applied frequency (Hz) or None, display unit, display resolution,
#                limits '83 and 88' (low, high) or None for N/A, limits '87' (low, high), extras)
# kind: ACV DCV ACI DCI OHM CAP TEMP DUTY SQUARE NONE.  'hzread' extras: the meter displays FREQUENCY, the nominal is the applied frequency.
ROWS = [
    ('1', 'AC volts', 'acv', '600 mV', 'ACV', 0.33, 60, 'mV', '0.1', ('327.9', '332.1'), ('327.3', '332.7'), {}),
    ('2', 'AC volts', 'acv', '600 mV', 'ACV', 0.6, 13000, 'mV', '0.1', None, ('586.0', '614.0'), {}),
    ('3', 'AC volts', 'acv', '6 V', 'ACV', 3.3, 60, 'V', '0.001', ('3.281', '3.319'), ('3.275', '3.325'), {}),
    ('4', 'AC volts', 'acv', '6 V', 'ACV', 3.3, 20000, 'V', '0.001', None, ('3.214', '3.386'), {}),
    ('5', 'AC volts', 'acv', '60 V', 'ACV', 33, 60, 'V', '0.01', ('32.81', '33.19'), ('32.75', '33.25'), {}),
    ('6', 'AC volts', 'acv', '60 V', 'ACV', 33, 20000, 'V', '0.01', None, ('32.14', '33.86'), {}),
    ('7', 'AC volts', 'acv', '600 V', 'ACV', 330, 60, 'V', '0.1', ('328.1', '331.9'), ('327.5', '332.5'), {}),
    ('8', 'AC volts', 'acv', '600 V', 'ACV', 330, 2500, 'V', '0.1', None, ('323.0', '337.0'), {}),
    ('9', 'AC volts', 'acv', '1000 V', 'ACV', 500, 60, 'V', '1', ('495', '505'), ('494', '506'), {}),
    ('10', 'AC volts', 'acv', '1000 V', 'ACV', 1000, 1000, 'V', '1', ('986', '1014'), ('986', '1014'), {}),
    ('11', 'AC volts frequency', 'hzac', '600 mV', 'ACV', 0.15, 99950, 'kHz', '0.01', ('99.93', '99.97'), ('99.93', '99.97'), dict(hzread=True)),
    ('12', 'AC volts frequency', 'hzac', '600 mV', 'ACV', 0.15, 199500, 'kHz', '0.01', ('199.48', '199.52'), ('199.48', '199.52'), dict(hzread=True)),
    ('13', 'AC volts frequency sensitivity', 'hzac', '6 V', 'ACV', 0.7, 99950, 'kHz', '0.01', ('99.93', '99.97'), ('99.93', '99.97'), dict(hzread=True)),
    ('14', 'AC volts frequency sensitivity', 'hzac', '60 V', 'ACV', 7, 99950, 'kHz', '0.01', ('99.93', '99.97'), ('99.93', '99.97'), dict(hzread=True)),
    # step 15 '3.4 V, 1 kHz Sq. Wave': a square-wave level, read as peak-to-peak like step 16's '5 V ... DC offset 2.5 V' (5522A square amplitude is p-p, Operators Manual p. 4-42);
    # no DC offset is printed, so none is set (UNVERIFIED, see the report)
    ('15', 'DC volts frequency trigger level', 'hzdc', '6 V', 'ACV', 3.4, 1000, 'Hz', '0.1', ('999.8', '1000.2'), ('999.8', '1000.2'),
     dict(hzread=True, square=dict(waveform='square', duty=50.0, offset=0.0))),
    ('16', 'DC volts duty cycle', 'duty', '6 V', 'DUTY', 5.0, 1000, '%', '0.1', ('49.7', '50.3'), ('49.7', '50.3'), dict(square=dict(duty=50.0, offset=2.5), nominal=50.0)),
    ('17', 'DC volts', 'dcv', '6 V', 'DCV', 3.3, None, 'V', '0.001', ('3.296', '3.304'), ('3.297', '3.303'), {}),
    ('18', 'DC volts', 'dcv', '60 V', 'DCV', 33, None, 'V', '0.01', ('32.96', '33.04'), ('32.97', '33.03'), {}),
    ('19', 'DC volts', 'dcv', '600 V', 'DCV', 330, None, 'V', '0.1', ('329.6', '330.4'), ('329.7', '330.3'), {}),
    ('20', 'DC volts', 'dcv', '1000 V', 'DCV', 1000, None, 'V', '1', ('998', '1002'), ('998', '1002'), {}),
    ('21', 'DC millivolts', 'mv', '600 mV', 'DCV', 0.033, None, 'mV', '0.1', ('32.8', '33.2'), ('32.9', '33.1'), {}),
    ('22', 'DC millivolts', 'mv', '600 mV', 'DCV', 0.33, None, 'mV', '0.1', ('328.9', '331.1'), ('329.6', '330.4'), {}),
    ('23', 'Ohms', 'ohm', '600 Ω', 'OHM', 330, None, 'Ω', '0.1', ('328.5', '331.5'), ('329.1', '330.9'), dict(comp=True)),
    ('24', 'Ohms', 'ohm', '6 kΩ', 'OHM', 3300, None, 'kΩ', '0.001', ('3.286', '3.314'), ('3.292', '3.308'), dict(comp=True)),
    ('25', 'Ohms', 'ohm', '60 kΩ', 'OHM', 33000, None, 'kΩ', '0.01', ('32.86', '33.14'), ('32.92', '33.08'), {}),
    ('26', 'Ohms', 'ohm', '600 kΩ', 'OHM', 330000, None, 'kΩ', '0.1', ('327.6', '332.4'), ('327.9', '332.1'), {}),
    ('27', 'Ohms', 'ohm', '6 MΩ', 'OHM', 3300000, None, 'MΩ', '0.001', ('3.276', '3.324'), ('3.279', '3.321'), {}),
    ('28', 'Ohms', 'ohm', '50 MΩ', 'OHM', 30000000, None, 'MΩ', '0.01', ('29.67', '30.33'), ('29.67', '30.33'), {}),
    ('29', 'Conductance', 'ns', '60 nS', 'NONE', None, None, 'nS', '0.01', ('-0.30', '0.30'), ('-0.30', '0.30'),
     dict(setup='Open input: disconnect the test leads from the calibrator and leave the meter inputs OPEN. Select conductance (nS). The calibrator stays in STANDBY.')),
    ('30', 'Conductance', 'ns', '60 nS', 'OHM', 100000000, None, 'nS', '0.01', ('9.60', '10.40'), ('9.60', '10.40'),
     dict(nominal_base=1e-08, no_uncertainty=True, note='10 nS is a 100 MΩ resistance: the calibrator is set to 100 MΩ (Table 3 step 30).')),
    ('31', 'Diode', 'diode', '6 V', 'DCV', 3.0, None, 'V', '0.001', ('2.939', '3.061'), ('2.939', '3.061'),
     dict(note='Apply 3.0 V dc to the VΩ input in diode test; the table lists the displayed voltage.')),
    ('32', 'AC amps', 'aca', '6 A', 'ACI', 3.0, 60, 'A', '0.001', ('2.962', '3.038'), ('2.968', '3.032'), dict(settle=5)),
    ('33', 'DC amps', 'dca', '6 A', 'DCI', 3.0, None, 'A', '0.001', ('2.984', '3.016'), ('2.990', '3.010'), dict(settle=5)),
    ('33B', 'DC amps', 'dca', '10 A', 'DCI', 10.0, None, 'A', '0.01', ('9.94', '10.06'), ('9.96', '10.04'), dict(settle=5, note=NOTE_10A)),
    ('34', 'AC milliamps', 'acma', '60 mA', 'ACI', 0.033, 60, 'mA', '0.01', ('32.58', '33.42'), ('32.65', '33.35'), {}),
    ('35', 'AC milliamps', 'acma', '400 mA', 'ACI', 0.33, 60, 'mA', '0.1', ('325.8', '334.2'), ('326.5', '333.5'), {}),
    ('36', 'DC milliamps', 'dcma', '60 mA', 'DCI', 0.033, None, 'mA', '0.01', ('32.83', '33.17'), ('32.89', '33.11'), {}),
    ('37', 'DC milliamps', 'dcma', '400 mA', 'DCI', 0.33, None, 'mA', '0.1', ('328.5', '331.5'), ('329.1', '330.9'), {}),
    ('38', 'AC microamps', 'acua', '600 µA', 'ACI', 0.00033, 60, 'µA', '0.1', ('325.8', '334.2'), ('326.5', '333.5'), {}),
    ('39', 'AC microamps', 'acua', '6000 µA', 'ACI', 0.0033, 60, 'µA', '1', ('3258', '3342'), ('3265', '3335'), {}),
    ('40', 'DC microamps', 'dcua', '600 µA', 'DCI', 0.00033, None, 'µA', '0.1', ('328.3', '331.7'), ('328.9', '331.1'), {}),
    ('41', 'DC microamps', 'dcua', '6000 µA', 'DCI', 0.0033, None, 'µA', '1', ('3285', '3315'), ('3291', '3309'), {}),
    ('42', 'Capacitance', 'cap', '10 nF', 'NONE', None, None, 'nF', '0.01', ('0.21', '0.31'), ('0.21', '0.31'),
     dict(setup='Table 3 footnote 2: remove the test leads from the meter (open input). Select capacitance, 10 nF range. The calibrator stays in STANDBY.')),
    ('43', 'Capacitance', 'cap', '100 nF', 'CAP', 5e-09, None, 'nF', '0.1', ('4.7', '5.3'), ('4.7', '5.3'),
     dict(settle=10, rel=True, printed_text=dict(low='04.7', high='05.3', note='printed with the leading zero the meter displays; same value'))),
    ('44', 'Capacitance', 'cap', '100 µF', 'CAP', 9.5e-06, None, 'µF', '0.1', ('9.2', '9.8'), ('9.2', '9.8'),
     dict(settle=15, printed_text=dict(low='09.2', high='09.8', note='printed with the leading zero the meter displays; same value'))),
    ('45', 'Low pass filter', 'lpf', '1000 V', 'ACV', 400, 400, 'V', '1', None, ('372', '408'), dict(note=NOTE_LPF, asym=True)),
    ('46', 'Low pass filter', 'lpf', '1000 V', 'ACV', 400, 800, 'V', '1', None, ('226', '340'), dict(note=NOTE_LPF + ' ' + NOTE_LPF_800, asym=True, nocheck=True)),
    # step 47 Peak Min/Max: 6 V p-p square wave, 2 kHz, 1 V DC offset -> the signal swings +4 V / -2 V; '83 and 88' column = 88V only (footnote 7)
    ('47 MAX', 'Peak Min / Max', 'peak', '6 V dc', 'SQUARE', 6.0, 2000, 'V', '0.001', ('3.895', '4.105'), ('3.897', '4.103'),
     dict(square=dict(duty=50.0, offset=1.0), nominal=4.0, peak='MAX', models83=('88V',))),
    ('47 MIN', 'Peak Min / Max', 'peak', '6 V dc', 'SQUARE', 6.0, 2000, 'V', '0.001', ('-2.103', '-1.897'), ('-2.102', '-1.898'),
     dict(square=dict(duty=50.0, offset=1.0), nominal=-2.0, peak='MIN', models83=('88V',))),
    ('49', 'Temperature', 'temp', 'Type K', 'TEMP', 0.0, None, '°C', '0.1', ('-1.0', '1.0'), ('-1.0', '1.0'), dict(models83=('88V',))),
    ('50', 'Temperature', 'temp', 'Type K', 'TEMP', 100.0, None, '°C', '0.1', ('98.0', '102.0'), ('98.0', '102.0'), dict(models83=('88V',))),
]

# functional checks (all models): the display and pushbutton tests (pp. 7, 9) run first, the backlight steps 51-53 of Table 3 run at the end
FUNCTIONAL = [
    ('F', 1, 'Display test', 'Turn the meter on to V~ while holding down the AutoHOLD button to view all segments of the display. Compare the display with '
                             'Figure 3 and Table 2 of the calibration manual (printed pp. 7-8).',
     'All display segments come on and match Figure 3 (no missing or extra segments).', 'p. 7'),
    ('F', 2, 'Pushbutton test', 'Turn the rotary knob to V~ (the first position, "Testing the Pushbuttons" step 1), then press each button.',
     'The meter beeps for each button press. Then press and hold MIN MAX a second time to exit MIN MAX mode.', 'p. 9'),
]
BACKLIGHT = [
    ('51', 'Press the backlight button.', 'The backlight comes on.'),
    ('52', 'Press the backlight button again.', 'The backlight intensifies.'),
    ('53', 'Press the backlight button again.', 'The backlight goes off.'),
]

GROUP = {'ACV': 'VOHM', 'DCV': 'VOHM', 'OHM': 'VOHM', 'CAP': 'VOHM', 'DUTY': 'VOHM', 'SQUARE': 'VOHM', 'NONE': 'NONE', 'TEMP': 'TEMP'}


def group_for(kind, unit):
    if kind in ('ACI', 'DCI'):
        return 'AMP10' if unit == 'A' else 'UAMP'
    return GROUP[kind]


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def check_limits(sid, nominal, low, high, res, asym):
    """The limits bracket the nominal and (unless asym) sit symmetric about it, to within half a display step: returns problems."""
    n, lo, hi, r = D(str(nominal)), D(low), D(high), D(res)
    problems = []
    if not lo < hi:
        problems.append(f'{sid}: low {low} is not below high {high}')
    if not lo <= n <= hi:
        problems.append(f'{sid}: the nominal {n} is outside {low} .. {high}')
    if not asym and abs((n - lo) - (hi - n)) > r / 2:
        problems.append(f'{sid}: {low} .. {high} is not symmetric about {n}')
    for t in (low, high):
        if max(0, -D(t).as_tuple().exponent) != max(0, -r.as_tuple().exponent):
            problems.append(f'{sid}: limit {t} is not written at the display resolution {res}')
    return problems


def numeric_step(row, models, limits, column):
    manual, section, sw, rng, kind, value, freq, unit, res, _l83, _l87, extra = row
    low, high = limits
    factor, base = UNITS[unit]
    step = dict(table='3', section=section, switch=SW[sw], range=rng, models=list(models), kind=kind, display_unit=unit, factor=float(D(factor)),
                base_unit=base, low=low, high=high, test='numeric')
    notes = []
    if kind == 'NONE':
        step['nominal'] = 0.0
        step['setup_key'] = 'NONE'
        step['setup'] = extra['setup']
        step['no_uncertainty'] = True
    else:
        applied = dict(value=clean(value), frequency=float(freq) if freq else None)
        if 'square' in extra:
            applied.update(extra['square'])
        step['applied'] = applied
        if extra.get('hzread'):
            step['nominal'] = clean(freq)
        elif 'nominal' in extra:
            step['nominal'] = clean(extra['nominal'])
        elif 'nominal_base' in extra:
            step['nominal'] = clean(extra['nominal_base'])
        else:
            step['nominal'] = clean(value)
    if extra.get('hzread'):
        step['no_freq_suffix'] = True
        step['unc_kind'] = 'FREQ'
        if 'square' in extra:
            v_text = f'a {clean(value):g} V p-p square wave'
            step['report_desc'] = f'{rng} range ({clean(value):g} V p-p square wave applied)'
        else:
            v_text = f'{clean(value) * 1000:g} mV' if value < 1 else f'{clean(value):g} V'
            step['report_desc'] = f'{rng} range ({v_text} applied)'
        f_text = f'{clean(freq) / 1000:g} kHz' if freq >= 1000 else f'{clean(freq):g} Hz'
        notes.append(NOTE_HZ.format(v=v_text, f=f_text))
    if kind == 'DUTY':
        notes.append('The meter displays DUTY CYCLE (%) on this step. The calibrator applies a 5 V p-p square wave, 1 kHz, 2.5 V DC offset, 50 % duty '
                     '(Table 3 step 16, p. 9).')
    if extra.get('peak') == 'MAX':
        step['prompt'] = ('With the meter on V DC (6 V range), select Peak Min Max (the PEAK indicator shows the 250 µs Peak Min Max mode, Table 2 item 9), '
                          'then read MAX.')
        notes.append('Peak Min/Max, read the MAX value. Calibrator: 6 V p-p square wave, 2 kHz, 1 V DC offset, so the signal swings +4 V / -2 V '
                     '(Table 3 step 47, p. 11).')
    if extra.get('peak') == 'MIN':
        step['prompt'] = 'Peak Min Max is on: step the meter to MIN (the display shows MIN) and read it.'
        notes.append('Peak Min/Max, read the MIN value (same 6 V p-p, 2 kHz, 1 V offset square wave; Table 3 step 47, p. 11). After you record this reading, '
                     'exit Min Max by pressing and holding the MIN MAX button.')
    if extra.get('comp'):
        notes.append(NOTE_OHMS_COMP)
    if extra.get('rel'):
        step['rel_zero'] = dict(value=None, text='Disconnect the test leads from the calibrator, then press REL on the meter to null the internal meter and lead '
                                                 'capacitance (Table 3 footnote 5). Reconnect the leads to the calibrator before continuing.')
        notes.append(NOTE_CAP_REL)
    if sw in ('aca', 'dca', 'acma', 'dcma', 'acua', 'dcua'):
        notes.append(NOTE_AC_CURRENT)
    if kind == 'TEMP':
        notes.append(NOTE_TEMP)
        step['settle'] = 30
    if extra.get('note'):
        notes.insert(0, extra['note'])
    if 'printed_text' in extra:
        step['printed_text'] = extra['printed_text']
    for key in ('settle', 'no_uncertainty'):
        if key in extra:
            step[key] = extra[key]
    step['group'] = group_for(kind, unit)
    if notes:
        step['note'] = ' '.join(notes)
    label = {'both': 'both columns', '87 only': '87 column; N/A for the 83 and 88'}.get(column, f'{column} column')
    step['tol_text'] = f'Table 3 step {manual} ({label}): {low} to {high} {unit}'
    step['ref'] = f'T3 #{manual}' + ('' if column == 'both' else f' ({column.replace(" only", "")})')
    return step


def build_steps():
    steps, problems = [], []
    for table, n, title, setup, question, page in FUNCTIONAL:
        steps.append(dict(table=table, step=n, section='Functional checks', switch=title, range='', models=list(MODELS), kind='VISUAL', test='visual', title=title,
                          setup=setup, question=question, setup_key='NONE', ref=page, id=f'F-{n}'))
    seq = 0
    for row in ROWS:
        manual, section, sw, rng, kind, value, freq, unit, res, l83, l87, extra = row
        seq += 1
        nominal_reading = (D(str(freq)) if extra.get('hzread') else D(str(extra.get('nominal', value if value is not None else 0)))) / D(UNITS[unit][0]) \
            if kind != 'OHM' or 'nominal_base' not in extra else D('10')
        if kind == 'NONE':
            nominal_reading = None
        models83 = extra.get('models83', COL_83)
        variants = []
        if l83 is None:
            variants.append((COL_87, l87, '87 only'))
        elif l83 == l87:
            variants.append((tuple(m for m in MODELS if m in COL_87 + models83), l87, 'both'))
        else:
            variants.append((COL_87, l87, '87'))
            variants.append((models83, l83, '83 and 88' if len(models83) == 2 else '88'))
        base_id = '3-' + manual.replace(' ', '')
        for models, limits, column in variants:
            sid = base_id if column in ('both', '87 only') else base_id + ('.87' if column == '87' else '.83')
            if nominal_reading is not None and not extra.get('nocheck'):
                problems += check_limits(sid, nominal_reading, limits[0], limits[1], res, extra.get('asym', False))
            step = numeric_step(row, models, limits, column)
            step['step'] = seq
            step['id'] = sid
            steps.append(step)
    for manual, setup, question in BACKLIGHT:
        seq += 1
        steps.append(dict(table='3', step=seq, section='Backlight', switch='Backlight', range='', models=list(MODELS), kind='VISUAL', test='visual',
                          title=f'Backlight (step {manual})', setup=setup, question=question, setup_key='NONE', ref=f'T3 #{manual}', id=f'3-{manual}'))
    ids = [s['id'] for s in steps]
    assert len(ids) == len(set(ids)), 'duplicate step ids'
    first_temp = next(s for s in steps if s['kind'] == 'TEMP')
    first_temp['prompt'] = ('Connect the K-type thermocouple (mini-plug on both ends) through the Fluke 80AK adapter. The meter and the adapter must be at the same '
                            'temperature: let the reading stabilise before recording it (Table 3 footnote 3). Set the meter to °C.')
    return steps, problems


SOURCE_NOTE = (
    'Table 3 "Accuracy Tests" (printed pp. 9-11) of the Fluke 80 Series V Calibration Manual, two Display Reading columns ("83 and 88", "87"); plus the display test (p. 7), '
    'the pushbutton test (p. 9) and the backlight steps 51-53. 87V: all rows. 83V: the "83 and 88" column without steps 2, 4, 6, 8, 45, 46 (N/A), 47 (no Peak Min/Max, '
    'footnote 7) and 49-50 (temperature, 87 and 88 only). 88V: the "83 and 88" column with steps 47 and 49-50. Not built: the 88V inductive pickup test (pp. 11-14, '
    'oscilloscope and function generator). Limits as printed (no corrections). The manual names a Fluke 5560A; the procedure drives a Fluke 5560A or 5522A (or you set the '
    'calibrator by hand). High-voltage points go straight to the test value (the manual prescribes no ramp). The meters have no remote interface: you type the display reading.')
REPORT_NOTE = ('Limits are the manufacturer\'s, as printed in the Fluke 80 Series V Calibration Manual, Table 3 "Accuracy Tests" (printed pp. 9-11), '
               '"83 and 88" or "87" column as applies to the model.')


def build_spec():
    steps, problems = build_steps()
    if problems:
        raise SystemExit('Table 3 limit check failed:\n  ' + '\n  '.join(problems))
    count = {m: sum(1 for s in steps if m in s['models']) for m in MODELS}
    return dict(
        schema=2, kind='manual-reading',
        options=dict(hookup_meter='fluke87v', hv_threshold_v=30, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='6-11 (printed): Table 1 p. 6, display test p. 7, pushbutton test p. 9, Table 3 pp. 9-11',
                    cite='Fluke 80 Series V Calibration Manual, Table 3 "Accuracy Tests", printed pp. 9-11',
                    limits='Manufacturer limits, Table 3 (1 year), as printed',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE + ' ' + NOTE_DIAL),
        models={'83V': dict(name='Fluke 83V', brand='Fluke', model_note=f'Fluke 83 Series V digital multimeter: Table 3 "83 and 88" column, {count["83V"]} points'),
                '87V': dict(name='Fluke 87V', brand='Fluke', model_note=f'Fluke 87 Series V true-rms digital multimeter: Table 3 "87" column, {count["87V"]} points'),
                '88V': dict(name='Fluke 88V', brand='Fluke', model_note=f'Fluke 88 Series V automotive multimeter: Table 3 "83 and 88" column, {count["88V"]} points '
                                                                          '(inductive pickup test not included)')},
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
    count = {m: sum(1 for s in spec['steps'] if m in s['models']) for m in MODELS}
    print('wrote', OUT, len(spec['steps']), 'steps; points per model', count)


if __name__ == '__main__':
    main()
