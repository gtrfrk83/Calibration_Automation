"""Builds specs/fluke_170_series_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 175 / 177 / 179 Calibration Information.

    python3 specs/build_170_spec.py

Source: Fluke 175, 177, 179 True-rms Multimeters, Calibration Information (22 pages, PN 1600476, Rev. 7, 3/23)
  Table 1 "Calibrator Specifications" p. 8 (a Fluke 5500A or equivalent), "Performance Tests" procedure p. 9,
  Table 2 "Performance Tests 175" pp. 10-11 (52 rows), Table 3 "Performance Tests 177/179" pp. 12-13 (51 rows + 3 temperature rows, 179 only).
Every nominal, frequency and limit below was read from the RENDERED PAGE IMAGES of those pages (pdftoppm, 220 dpi), twice, never from extracted
text (the units mu and Omega do not survive text extraction; the extracted text of this PDF also scrambles two of the rows listed below).
The manual's tables carry no step numbers: the steps here are numbered in table order (Table 2: 2-1 .. 2-52; Table 3: 3-1 .. 3-54).

One family spec, three models: the 175 is Table 2, the 177 and the 179 are Table 3 (the 179 adds the three temperature rows).

THREE printed values are corrected, each flagged in the spec (step.printed_limits), on the on-screen note, on the report and in NOTES.md.
The correction is made only where the table itself, the 175 table next to it and the +/-(% of reading + counts) accuracy method of the published
specification all agree that the printed text is a misprint:
  2-30 (175, ohms, 500 ohm):    upper limit printed '504.7 kOhm'; a 500 ohm input is judged 495.3 .. 504.7 ohm (the 177/179 table prints '504.7 Ohm').
  3-4  (177/179, AC volts, 5 V 45 Hz): upper limit printed '5.103 V ac'; the lower limit (4.947) and the 175 table say 5.053 V ac (1.0 % + 3 counts of 0.001 V).
  3-25 (177/179, DC volts frequency): printed '3 V 45 kHz  45.06 Hz  44.94 Hz': the input must be 3 V at 45 Hz (a 45 kHz input cannot read 45 Hz; the 175 table
        prints '3 V 45 Hz') and the lower / upper columns are swapped; judged 44.94 .. 45.06 Hz.
  (The 177/179 table has ONE DC-volts-frequency row; the 175 table has two, 3 V 45 Hz and 30 V 50 kHz.  No second row is invented for the 177/179.)
Format only (same number): a limit printed with fewer decimals than the display resolution is written at the display resolution (50.1 -> 50.10 V,
899 / 901 -> 899.0 / 901.0 Hz, 8.99 / 9.01 -> 8.990 / 9.010 kHz) so that a typed reading is padded to what the meter displays; the printed text is kept in 'printed_text'.

The published accuracy (the 170 Series Technical Data) is NOT in the calibration manual.  The accuracy table below (ACC) was taken from the
Fluke 170 Series Technical Data as summarised from the web (a secondary source; the PDF was not fetched here) and is used ONLY to check every printed
limit (build time and tests/test_170_points.py): +/-(% of reading + counts x resolution), to within half a display step.  Ranges and resolutions come
from the same data sheet and from the decimals of the printed limits; the manual itself names no range.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_170_series_pv.json'
DOCUMENT = 'Fluke 175, 177, 179 True-rms Multimeters - Calibration Information'

# display unit -> (factor to base unit, base unit)
UNITS = {'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'MΩ': ('1000000', 'ohm'), 'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'Hz': ('1', 'Hz'), 'kHz': ('1000', 'Hz'),
         'nF': ('0.000000001', 'F'), 'µF': ('0.000001', 'F'), 'mA': ('0.001', 'A'), 'A': ('1', 'A'), '°C': ('1', 'degC')}

# rotary switch / function text shown by the "Change the function" prompt (the engine asks again whenever this text changes between two points).
# The names are the manual's own 'Test (Switch Position)' column; the manual has NO figure of the dial, so the position names, their order and the
# yellow-button sequence are NOT verified against the real meter (see NOTE_DIAL).
SW = {
    'acv': 'V~  (AC volts)',
    'hzac': 'V~ Hz  (AC volts frequency; press the YELLOW button)',
    'dcv': 'V⎓  (DC volts)',
    'hzdc': 'V⎓ Hz  (DC volts frequency; press the YELLOW button)',
    'mv': 'mV⎓  (DC millivolts)',
    'ohm': 'Ω  (Ohms)',
    'cap': 'Capacitance  ⊣⊢  (press the YELLOW button)',
    'cont': 'Continuity  •)))',
    'diode': 'Diode  ▶|  (press the YELLOW button)',
    'acma': 'mA~  (AC milliamps)',
    'aca': 'A~  (AC amps)',
    'dcma': 'mA⎓  (DC milliamps; press the YELLOW button)',
    'dca': 'A⎓  (DC amps; press the YELLOW button)',
    'temp': 'Temperature  (179 only; press the YELLOW button)',
}
NOTE_DIAL = 'Dial position names are the manual\'s own (Tables 2 / 3, "Test (Switch Position)"); the manual has no dial figure, so confirm the position and button sequence on the real meter.'
NOTE_YELLOW = 'Table footnote 1: press the YELLOW button to access this function.'
NOTE_OHMS = 'The limits do not include test lead resistance (table note 2).'
NOTE_AC_CURRENT = ('Avoid coupled noise on AC current by either shorting the VΩ input to COM or leaving the VΩ input unconnected (manual p. 9). '
                   'The meter shows LEAd when the switch moves to or from the mA / A position (p. 2): check the leads are in the right jacks.')
NOTE_TEMP = ('Table 3 notes 1, 3, 4: press the YELLOW button to access temperature; be sure to use the correct cable (K-type thermocouple, mini-plug on both ends, '
             'through the Fluke 80AK adapter, Table 1); the meter and the thermocouple adapter must be at the same temperature (allow 20 minutes). '
             'The calibrator sources degrees C: set the meter to °C.')

# accuracy as published, +/-(percent of reading + counts): (pct, counts); resolution (display unit) is per row
ACC = {
    'AC_LOW': ('1.0', 3),          # AC volts 45 Hz - 500 Hz (all three models)
    'AC_HIGH': ('2.0', 3),         # AC volts 500 Hz - 1 kHz
    'ACI': ('1.5', 3),             # AC current (all)
    'DCI': ('1.0', 3),             # DC current (all)
    'OHM_LOW': ('0.9', 2), 'OHM': ('0.9', 1), 'OHM_50M': ('1.5', 3),
    'CAP': ('1.2', 2), 'DIODE': ('1.0', 2), 'HZ': ('0.1', 1), 'TEMP': ('1.0', 'abs'),       # temperature: 1 % + 1.0 degC
    'DCV_175': ('0.15', 2), 'DCV_177': ('0.09', 2), 'DCV_177_1000': ('0.1', 2),
}


def dcv_acc(model, value):
    if model == '175':
        return ACC['DCV_175']
    return ACC['DCV_177_1000'] if abs(value) >= 1000 else ACC['DCV_177']


# Row: (section, switch, range, kind, applied value (base units), applied frequency (Hz) or None, display unit, printed low, printed high,
#       accuracy key, display resolution (display unit), extras).   kind: ACV DCV ACI DCI OHM BEEP CAP TEMP.
# 'hzread' extras: the meter displays FREQUENCY, nominal = applied frequency.
def table_175():
    r = []
    a = r.append
    a(('AC volts', 'acv', '600.0 mV', 'ACV', 0.3, 45, 'mV', '296.7', '303.3', 'AC_LOW', '0.1', {}))
    a(('AC volts', 'acv', '600.0 mV', 'ACV', 0.5, 500, 'mV', '494.7', '505.3', 'AC_LOW', '0.1', {}))
    a(('AC volts', 'acv', '600.0 mV', 'ACV', 0.5, 1000, 'mV', '489.7', '510.3', 'AC_HIGH', '0.1', {}))
    a(('AC volts', 'acv', '6.000 V', 'ACV', 5, 45, 'V', '4.947', '5.053', 'AC_LOW', '0.001', {}))
    a(('AC volts', 'acv', '6.000 V', 'ACV', 5, 500, 'V', '4.947', '5.053', 'AC_LOW', '0.001', {}))
    a(('AC volts', 'acv', '6.000 V', 'ACV', 5, 1000, 'V', '4.897', '5.103', 'AC_HIGH', '0.001', {}))
    a(('AC volts', 'acv', '60.00 V', 'ACV', 50, 45, 'V', '49.47', '50.53', 'AC_LOW', '0.01', {}))
    a(('AC volts', 'acv', '60.00 V', 'ACV', 50, 500, 'V', '49.47', '50.53', 'AC_LOW', '0.01', {}))
    a(('AC volts', 'acv', '60.00 V', 'ACV', 50, 1000, 'V', '48.97', '51.03', 'AC_HIGH', '0.01', {}))
    a(('AC volts', 'acv', '600.0 V', 'ACV', 300, 45, 'V', '296.7', '303.3', 'AC_LOW', '0.1', {}))
    a(('AC volts', 'acv', '600.0 V', 'ACV', 500, 500, 'V', '494.7', '505.3', 'AC_LOW', '0.1', {}))
    a(('AC volts', 'acv', '600.0 V', 'ACV', 500, 1000, 'V', '489.7', '510.3', 'AC_HIGH', '0.1', {}))
    a(('AC volts', 'acv', '1000 V', 'ACV', 1000, 45, 'V', '987', '1013', 'AC_LOW', '1', {}))
    a(('AC volts', 'acv', '1000 V', 'ACV', 1000, 500, 'V', '987', '1013', 'AC_LOW', '1', {}))
    a(('AC volts', 'acv', '1000 V', 'ACV', 1000, 1000, 'V', '977', '1023', 'AC_HIGH', '1', {}))
    a(('AC volts frequency', 'hzac', '99.99 Hz', 'ACV', 1, 45, 'Hz', '44.94', '45.06', 'HZ', '0.01', dict(hzread=True)))
    a(('AC volts frequency', 'hzac', '999.9 Hz', 'ACV', 1, 900, 'Hz', '899', '901', 'HZ', '0.1', dict(hzread=True)))
    a(('AC volts frequency', 'hzac', '9.999 kHz', 'ACV', 1, 9000, 'kHz', '8.99', '9.01', 'HZ', '0.001', dict(hzread=True)))
    a(('AC volts frequency', 'hzac', '99.99 kHz', 'ACV', 5, 50000, 'kHz', '49.94', '50.06', 'HZ', '0.01', dict(hzread=True)))
    a(('DC volts', 'dcv', '6.000 V', 'DCV', 5, None, 'V', '4.990', '5.010', 'DCV', '0.001', {}))
    a(('DC volts', 'dcv', '60.00 V', 'DCV', 50, None, 'V', '49.90', '50.1', 'DCV', '0.01', {}))
    a(('DC volts', 'dcv', '600.0 V', 'DCV', 300, None, 'V', '299.3', '300.7', 'DCV', '0.1', {}))
    a(('DC volts', 'dcv', '1000 V', 'DCV', 1000, None, 'V', '996', '1004', 'DCV', '1', {}))
    a(('DC volts', 'dcv', '1000 V', 'DCV', -1000, None, 'V', '-1004', '-996', 'DCV', '1', {}))
    a(('DC volts frequency', 'hzdc', '99.99 Hz', 'ACV', 3, 45, 'Hz', '44.94', '45.06', 'HZ', '0.01', dict(hzread=True)))
    a(('DC volts frequency', 'hzdc', '99.99 kHz', 'ACV', 30, 50000, 'kHz', '49.94', '50.06', 'HZ', '0.01', dict(hzread=True)))
    a(('DC millivolts', 'mv', '600.0 mV', 'DCV', 0.03, None, 'mV', '29.8', '30.2', 'DCV', '0.1', {}))
    a(('DC millivolts', 'mv', '600.0 mV', 'DCV', -0.3, None, 'mV', '-300.7', '-299.3', 'DCV', '0.1', {}))
    a(('DC millivolts', 'mv', '600.0 mV', 'DCV', 0.6, None, 'mV', '598.9', '601.1', 'DCV', '0.1', {}))
    a(('Ohms', 'ohm', '600.0 Ω', 'OHM', 500, None, 'Ω', '495.3', '504.7', 'OHM_LOW', '0.1',
       dict(printed_limits=dict(low='495.3', high='504.7', unit='Ω (the upper limit is printed with the unit kΩ)', note='as printed in Table 2 (p. 11)'), note_fix='LIMIT UNIT CORRECTED: Table 2 prints the upper limit as 504.7 kΩ; the lower limit (495.3 Ω), the 177/179 table and the '
                                                                 'accuracy (0.9 % + 2 counts of 0.1 Ω = 4.7 Ω) all say 504.7 Ω.')))
    a(('Ohms', 'ohm', '6.000 kΩ', 'OHM', 5000, None, 'kΩ', '4.954', '5.046', 'OHM', '0.001', {}))
    a(('Ohms', 'ohm', '60.00 kΩ', 'OHM', 50000, None, 'kΩ', '49.54', '50.46', 'OHM', '0.01', {}))
    a(('Ohms', 'ohm', '600.0 kΩ', 'OHM', 500000, None, 'kΩ', '495.4', '504.6', 'OHM', '0.1', {}))
    a(('Ohms', 'ohm', '6.000 MΩ', 'OHM', 5000000, None, 'MΩ', '4.954', '5.046', 'OHM', '0.001', {}))
    a(('Ohms', 'ohm', '50.00 MΩ', 'OHM', 19000000, None, 'MΩ', '18.68', '19.32', 'OHM_50M', '0.01', {}))
    a(('Capacitance', 'cap', '1000 nF', 'CAP', 9e-07, None, 'nF', '887', '913', 'CAP', '1', dict(settle=10)))
    a(('Capacitance', 'cap', '10.00 µF', 'CAP', 9e-06, None, 'µF', '8.87', '9.13', 'CAP', '0.01', dict(settle=10)))
    a(('Capacitance', 'cap', '100.0 µF', 'CAP', 9e-05, None, 'µF', '88.7', '91.3', 'CAP', '0.1', dict(settle=10)))
    a(('Capacitance', 'cap', '9999 µF', 'CAP', 9e-04, None, 'µF', '887', '913', 'CAP', '1', dict(settle=10)))
    a(('Continuity', 'cont', '600 Ω', 'BEEP', 25, None, 'Ω', None, None, None, None, dict(expect='on')))
    a(('Continuity', 'cont', '600 Ω', 'BEEP', 250, None, 'Ω', None, None, None, None, dict(expect='off')))
    a(('Diode', 'diode', '2.400 V', 'DCV', 2.0, None, 'V', '1.978', '2.022', 'DIODE', '0.001', dict(diode=True)))
    a(('AC milliamps', 'acma', '60.00 mA', 'ACI', 0.003, 45, 'mA', '2.92', '3.08', 'ACI', '0.01', dict(leads=True)))
    a(('AC milliamps', 'acma', '60.00 mA', 'ACI', 0.05, 1000, 'mA', '49.22', '50.78', 'ACI', '0.01', dict(leads=True)))
    a(('AC milliamps', 'acma', '400.0 mA', 'ACI', 0.4, 1000, 'mA', '393.7', '406.3', 'ACI', '0.1', dict(leads=True)))
    a(('AC amps', 'aca', '6.000 A', 'ACI', 4, 45, 'A', '3.937', '4.063', 'ACI', '0.001', dict(leads=True, settle=5)))
    a(('AC amps', 'aca', '10.00 A', 'ACI', 9, 1000, 'A', '8.83', '9.17', 'ACI', '0.01', dict(leads=True, settle=5)))
    a(('DC milliamps', 'dcma', '60.00 mA', 'DCI', 0.003, None, 'mA', '2.94', '3.06', 'DCI', '0.01', {}))
    a(('DC milliamps', 'dcma', '60.00 mA', 'DCI', 0.05, None, 'mA', '49.47', '50.53', 'DCI', '0.01', {}))
    a(('DC milliamps', 'dcma', '400.0 mA', 'DCI', -0.4, None, 'mA', '-404.3', '-395.7', 'DCI', '0.1', {}))
    a(('DC amps', 'dca', '6.000 A', 'DCI', 4, None, 'A', '3.957', '4.043', 'DCI', '0.001', dict(settle=5)))
    a(('DC amps', 'dca', '10.00 A', 'DCI', -9, None, 'A', '-9.12', '-8.88', 'DCI', '0.01', dict(settle=5)))
    return r


def table_177():
    """Table 3 (177 / 179): the same rows as Table 2 except DC volts, DC volts frequency (one row) and DC millivolts; the 179 adds temperature."""
    rows = table_175()
    out = []
    for row in rows:
        section = row[0]
        if section == 'Ohms' and row[7] == '495.3':
            row = row[:11] + ({},)                                                  # Table 3 prints 504.7 Ω: nothing to correct
        if section == 'DC volts frequency':
            continue
        out.append(row)
    tab = {('AC volts', 5, 45): ('4.947', '5.103', '5.053'),
           ('DC volts', 5): ('4.993', '5.007'), ('DC volts', 50): ('49.93', '50.07'), ('DC volts', 300): ('299.5', '300.5'),
           ('DC volts', 1000): ('997', '1003'), ('DC volts', -1000): ('-1003', '-997'),
           ('DC millivolts', 0.03): ('29.8', '30.2'), ('DC millivolts', -0.3): ('-300.5', '-299.5'), ('DC millivolts', 0.6): ('599.3', '600.7')}
    fixed = []
    for row in out:
        section, sw, rng, kind, value, freq, unit, low, high, acc, res, extra = row
        extra = dict(extra)
        if (section, value, freq) in tab and section == 'AC volts':
            low, printed_high, high = tab[(section, value, freq)]
            extra['printed_limits'] = dict(low=low, high=printed_high, unit='V', note='as printed in Table 3 (p. 12)')
            extra['check_printed'] = True
            extra['note_fix'] = ('LIMIT CORRECTED: Table 3 prints the upper limit of 5 V at 45 Hz as 5.103 V ac, which is not symmetric about 5 V; the lower limit (4.947 V), the 175 table and the '
                                 'accuracy (1.0 % + 3 counts of 0.001 V = 0.053 V) give 5.053 V ac.')
        elif section == 'DC volts' and (section, value) in tab:
            low, high = tab[(section, value)]
            if value == 50:
                extra.pop('printed_text', None)
        elif section == 'DC millivolts' and (section, value) in tab:
            low, high = tab[(section, value)]
        fixed.append((section, sw, rng, kind, value, freq, unit, low, high, acc, res, extra))
    # the single DC volts frequency row of Table 3, inserted after DC volts (before DC millivolts) as printed
    idx = max(i for i, r in enumerate(fixed) if r[0] == 'DC volts') + 1
    fixed.insert(idx, ('DC volts frequency', 'hzdc', '99.99 Hz', 'ACV', 3, 45, 'Hz', '44.94', '45.06', 'HZ', '0.01',
                       dict(hzread=True, printed_limits=dict(low='45.06', high='44.94', unit='Hz', applied='3 V 45 kHz', note='as printed in Table 3 (p. 12): lower and upper columns swapped, input given as 45 kHz'),
                            note_fix='PRINTED ROW CORRECTED: Table 3 prints "3 V 45 kHz" with the limits 45.06 Hz (lower column) and 44.94 Hz (upper column). A 45 kHz input cannot read 45 Hz '
                                     'and the columns are swapped: the 175 table prints 3 V 45 Hz, 44.94 / 45.06 Hz. The input is 3 V at 45 Hz, judged 44.94 .. 45.06 Hz.')))
    return fixed


TEMP_ROWS = [
    ('Temperature', 'temp', 'Type K', 'TEMP', 0, None, '°C', '-1.0', '1.0', 'TEMP', '0.1', {}),
    ('Temperature', 'temp', 'Type K', 'TEMP', -40, None, '°C', '-41.4', '-38.6', 'TEMP', '0.1', {}),
    ('Temperature', 'temp', 'Type K', 'TEMP', 400, None, '°C', '395.0', '405.0', 'TEMP', '0.1', {}),
]

GROUP = {'OHM': 'VOHM', 'BEEP': 'VOHM', 'ACV': 'VOHM', 'DCV': 'VOHM', 'CAP': 'VOHM', 'TEMP': 'TEMP'}      # currents: UAMP up to 400 mA, AMP10 for the A input


def group_for(kind, unit):
    if kind in ('ACI', 'DCI'):
        return 'AMP10' if unit == 'A' else 'UAMP'
    return GROUP[kind]


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def decimals(text: str) -> int:
    return max(0, -D(text).as_tuple().exponent)


def accuracy_for(model, key, value):
    if key == 'DCV':
        return dcv_acc(model, value)
    return ACC[key]


def check_against_specification(step_no, display_unit, reading_value, low, high, accuracy, res):
    """+/-(% of reading + counts x resolution), printed rounded to the display resolution: returns problems (empty when both limits are within half a display step).
    reading_value: the nominal reading in the display unit (a Decimal / number)."""
    pct, counts = D(accuracy[0]), accuracy[1]
    res = D(res)
    reading = D(str(reading_value))
    expect = pct / 100 * abs(reading) + (D('1.0') if counts == 'abs' else counts * res)
    problems = []
    for name, got in (('low', reading - D(low)), ('high', D(high) - reading)):
        if abs(got - expect) > res / 2:
            problems.append(f'step {step_no}: the {name} limit is {got} {display_unit} from the nominal, the specification gives {expect}')
    return problems


def build_steps():
    steps, problems = [], []
    plans = (('2', ['175'], table_175(), 'Table 2 (Performance Tests 175), pp. 10-11'),
             ('3', ['177', '179'], table_177(), 'Table 3 (Performance Tests 177/179), pp. 12-13'),
             ('3', ['179'], TEMP_ROWS, 'Table 3 (Performance Tests 177/179, temperature, 179 only), p. 13'))
    counter = {'2': 0, '3': 0}
    for table, models, rows, where in plans:
        for section, sw, rng, kind, value, freq, unit, low, high, acc, res, extra in rows:
            counter[table] += 1
            n = counter[table]
            factor, base = UNITS[unit]
            model = models[0]
            reading_val = D(str(freq if extra.get('hzread') else value)) / D(factor) if kind != 'BEEP' else None
            step = dict(table=table, step=n, section=section, switch=SW[sw], range=rng, models=models, kind='OHM' if kind == 'BEEP' else kind)
            notes = []
            if kind == 'BEEP':
                step.update(test='beeper', expect=extra['expect'], applied=dict(value=value, frequency=None), nominal=value, base_unit=base,
                            display_unit=unit, factor=float(D(factor)),
                            question='The beeper is ON (sounding).' if extra['expect'] == 'on' else 'The beeper is OFF (silent).')
            else:
                accuracy = accuracy_for(model, acc, value)
                low_used, high_used = low, high
                # limits are written at the display resolution (same number): the printed text is kept when it differs
                low_f, high_f = format(D(low_used).quantize(D(res)), 'f'), format(D(high_used).quantize(D(res)), 'f')
                assert D(low_f) == D(low_used) and D(high_f) == D(high_used), f'{table}-{n}: reformatting changed a limit'
                if (low_f, high_f) != (low_used, high_used):
                    step['printed_text'] = dict(low=low_used, high=high_used, note='printed with fewer decimals than the display resolution; same value')
                low_used, high_used = low_f, high_f
                for m in models:
                    problems += check_against_specification(f'{table}-{n} ({m})', unit, reading_val, low_used, high_used, accuracy_for(m, acc, value), res)
                if extra.get('printed_limits'):
                    step['printed_limits'] = extra['printed_limits']
                if extra.get('check_printed'):               # the printed limits must be the ones that DISAGREE with the specification (that is why they are corrected)
                    pl = extra['printed_limits']
                    assert check_against_specification(f'{table}-{n}', unit, reading_val, pl['low'], pl['high'], accuracy, res), \
                        f'{table}-{n}: the printed limits agree with the specification, nothing to correct'
                a_value = clean(value)
                step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=low_used, high=high_used, test='numeric',
                            applied=dict(value=a_value, frequency=float(freq) if freq else None), nominal=clean(freq) if extra.get('hzread') else a_value)
                pct, counts = accuracy
                if counts == 'abs':
                    step['accuracy'] = f'±({pct} % of reading + 1.0 °C)'
                    word = '1.0 °C'
                else:
                    word = f'{counts} count' + ('' if counts == 1 else 's')
                    step['accuracy'] = f'±({pct} % of reading + {word})'
                    word = f'{word} of {res} {unit}'
                step['tol_text'] = f'{where.split(" (")[0]}: {low_used} to {high_used} {unit}   (published specification: ±({pct} % of reading + {word}))'
                if extra.get('hzread'):
                    step['no_uncertainty'] = True            # the reading is a frequency: the calibrator's voltage uncertainty does not apply (see NOTES.md)
                    step['report_desc'] = f'{rng} range ({clean(value):g} V applied)'
                    notes.append(f'The meter displays FREQUENCY on this step (the calibrator applies {clean(value):g} V at {clean(freq):g} Hz). ' + NOTE_YELLOW)
            if sw in ('cap', 'diode', 'dcma', 'dca'):
                notes.append(NOTE_YELLOW)
            if sw == 'ohm':
                notes.append(NOTE_OHMS)
            if sw == 'cap':
                notes.append(f'Apply {clean(value) / float(D(factor)):g} {unit} (the 5500A "Apply" capacitance).')
            if sw == 'diode':
                notes.append('Apply 2.0 V (DC) to the VΩ input in diode test; the table lists the displayed voltage.')
            if sw == 'hzdc':
                notes.append('"DC Volts Frequency": the calibrator applies an AC voltage (Table 3 "3 V" / "30 V" at the stated frequency) with the meter in DC volts, frequency.')
            if sw in ('acma', 'aca'):
                notes.append('Table gives no yellow-button step for AC current: the display should show AC (~).')
            if extra.get('leads'):
                notes.append(NOTE_AC_CURRENT)
            if sw == 'temp':
                notes.append(NOTE_TEMP)
                step['settle'] = 30
            if extra.get('note_fix'):
                notes.insert(0, extra['note_fix'])
            if 'printed_limits' in step:                     # the report prints the row's Description (footer notes are not printed): say there that a limit was corrected
                base = step.get('report_desc') or f'{rng.replace("Ω", "Ohm")} range'          # the report prints Ohm, never the Omega glyph
                step['report_desc'] = base[:-1] + ', limits corrected)' if base.endswith(')') else base + ' (limits corrected)'
            step['group'] = group_for(kind, unit)
            if 'settle' in extra:
                step['settle'] = extra['settle']
            if notes:
                step['note'] = ' '.join(notes)
            step['ref'] = f'T{table} #{n}'
            step['id'] = f'{table}-{n}'
            steps.append(step)
    # the first temperature point of the 179 asks for the 20-minute soak before the reading (once)
    first_temp = next(s for s in steps if s['kind'] == 'TEMP')
    first_temp['prompt'] = ('Table 3 note 4: to ensure accuracy, the meter and the thermocouple adapter must be at the same temperature. Allow 20 minutes before performing '
                            'the temperature points. Use the correct cable (K-type thermocouple, mini-plug on both ends, with the Fluke 80AK adapter). Press the YELLOW button '
                            'for temperature and set the meter to °C.')
    return steps, problems


SOURCE_NOTE = (
    'Table 2 (175: 52 rows) and Table 3 (177 / 179: 51 rows, plus 3 temperature rows for the 179 only): 175 / 177 / 179 Calibration Information pp. 10-13. The tables have no step '
    'numbers: steps are numbered in table order. THREE printed values are corrected (each flagged on the point and on the report): 175 ohms 500 ohm upper limit printed 504.7 kOhm '
    '(judged 504.7 ohm); 177/179 AC volts 5 V 45 Hz upper limit printed 5.103 V (judged 5.053 V, 1.0 % + 3 counts); 177/179 DC volts frequency printed "3 V 45 kHz, 45.06 / 44.94 Hz" '
    '(judged 3 V at 45 Hz, 44.94 to 45.06 Hz). Ranges are not named in the manual: each shown range is the one the reading falls in (from the published 170 Series resolutions). '
    'The manual names a Fluke 5500A; the procedure drives a Fluke 5522A or 5560A (or you set the calibrator by hand). High-voltage points go straight to the test value '
    '(the manual prescribes no ramp). The meters have no remote interface: you type the display reading.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s tables (Fluke 175 / 177 / 179 Calibration Information, Table 2 pp. 10-11 for the 175, Table 3 pp. 12-13 for the 177 / 179) with three '
    'corrections to misprints: 175 ohms 500 ohm upper limit (printed 504.7 kOhm, used 504.7 ohm); 177 / 179 AC volts 5 V 45 Hz upper limit (printed 5.103 V, used 5.053 V, 1.0 % + 3 counts); '
    '177 / 179 DC volts frequency (printed 3 V 45 kHz with the limits 45.06 and 44.94 Hz; used 3 V at 45 Hz, 44.94 to 45.06 Hz).')


def build_spec():
    steps, problems = build_steps()
    if problems:
        raise SystemExit('The tables disagree with the published accuracy:\n  ' + '\n  '.join(problems))
    return dict(
        schema=2, kind='manual-reading',
        options=dict(hookup_meter='fluke170', hv_threshold_v=30, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='8-13 (printed): Table 1 p. 8, procedure p. 9, Table 2 pp. 10-11, Table 3 pp. 12-13',
                    cite='Fluke 175, 177, 179 Calibration Information, Table 2 (175) pp. 10-11 and Table 3 (177 / 179) pp. 12-13; three printed values corrected (see Source)',
                    limits='Manufacturer limits, Tables 2 and 3; three corrections, see Source',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={'175': dict(name='Fluke 175', brand='Fluke', model_note='Fluke 175 true-rms digital multimeter (6000 counts): Table 2, 52 points'),
                '177': dict(name='Fluke 177', brand='Fluke', model_note='Fluke 177 true-rms digital multimeter (6000 counts): Table 3, 51 points'),
                '179': dict(name='Fluke 179', brand='Fluke', model_note='Fluke 179 true-rms digital multimeter (6000 counts): Table 3 plus temperature, 54 points')},
        steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
    count = {}
    for s in spec['steps']:
        for m in s['models']:
            count[m] = count.get(m, 0) + 1
    print('wrote', OUT, len(spec['steps']), 'steps; points per model', count)


if __name__ == '__main__':
    main()
