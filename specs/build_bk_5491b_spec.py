"""Builds specs/bk_5491b_pv.json: the B&K Precision 5491B performance verification (bench 5-1/2 digit DMM, RS-232 / USB).

    python3 specs/build_bk_5491b_spec.py

Sources
  * The lab's own datasheet, `B_K_Precision_5491B_Digital_Multimeter__365_Days_.MDD` (Cal Processor, procedure ATS-1042, 365-day interval, 55 points): every point,
    nominal, frequency and limit below was transcribed from it (the rows of MDD_POINTS are the MDD text, unchanged). These are the DEFAULT limits ("Lab datasheet").
  * The 2831E / 5491B User Manual (v1.10.2024), Chapter 7, the 5491B specification tables printed pp. 67 to 72, read from RENDERED PAGE IMAGES (pdftoppm, viewed twice),
    never from extracted text. They are the cross-check and the second, selectable limit set ("Manufacturer specification").

How the limits are built. The MDD prints "+/-(a % I.V. + b % F.S. + floor)" for each point; the limit is that half-width, truncated (rounded toward zero) to the display
resolution of the nominal, around the nominal. The build REPRODUCES every one of the 55 printed limits that way (so the rule is known, not guessed) and FAILS if one differs.
The manufacturer set is the same calculation with the manual's own percentages (and the full scale of the range the point is really on). The two sets agree everywhere except
the points listed in DISCREPANCIES, which are kept in the point as 'flags' and listed for the lab owner in the final summary and in NOTES.md.
Frequency columns of the manual's AC tables: a test frequency that is the upper edge of a column belongs to that column (20 Hz and 50 Hz -> 20-50 Hz; 2 kHz -> 50 Hz-2 kHz;
20 kHz -> 50 Hz-20 kHz or 2-20 kHz; 50 kHz -> 20-50 kHz), which is what the MDD does at every one of its points.
"""
from __future__ import annotations

import json
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'bk_5491b_pv.json'
MODEL = '5491B'
PERIODS = ('mdd', 'mfr')

UNITS = {'mV': (D('0.001'), 'V'), 'V': (D(1), 'V'), 'uA': (D('0.000001'), 'A'), 'mA': (D('0.001'), 'A'), 'A': (D(1), 'A'), 'Ohm': (D(1), 'ohm'), 'kOhm': (D(1000), 'ohm'),
         'MOhm': (D(1000000), 'ohm'), 'Hz': (D(1), 'Hz'), 'kHz': (D(1000), 'Hz')}

# (function, nominal, frequency (or the amplitude for frequency points), low, high, % of reading, % of full scale, full scale, floor)  -- the MDD text, unchanged.
# A function of '|' repeats the one above (the MDD leaves it blank). Source: the MDD, point order as in the file.
MDD_POINTS = [
    ('Volts DC', '490.00 mV', None, '489.82', '490.18', '0.02', '0.016', '500 mV', '0.01 mV'),
    ('|', '4.9000 V', None, '4.8950', '4.9050', '0.02', '0.08', '5 V', '0.0001 V'),
    ('|', '49.000 V', None, '48.950', '49.050', '0.02', '0.08', '50 V', '0.001 V'),
    ('|', '490.00 V', None, '489.50', '490.50', '0.02', '0.08', '500 V', '0.01 V'),
    ('|', '900.0 V', None, '899.0', '901.0', '0.02', '0.08', '1000 V', '0.1 V'),
    ('Volts AC', '490.00 mV', '20 Hz', '484.70', '495.30', '1', '0.08', '500 mV', None),
    ('|', '490.00 mV', '50 Hz', '484.70', '495.30', '1', '0.08', '500 mV', None),
    ('|', '490.00 mV', '20 kHz', '486.80', '493.20', '0.5', '0.15', '500 mV', None),
    ('|', '490.00 mV', '50 kHz', '482.15', '497.85', '1.5', '0.1', '500 mV', None),
    ('|', '490.00 mV', '100 kHz', '473.80', '506.20', '3', '0.3', '500 mV', None),
    ('|', '4.9000 V', '20 Hz', '4.8470', '4.9530', '1', '0.08', '5 V', None),
    ('|', '4.9000 V', '50 Hz', '4.8470', '4.9530', '1', '0.08', '5 V', None),
    ('|', '4.9000 V', '20 kHz', '4.8819', '4.9181', '0.35', '0.02', '5 V', None),
    ('|', '4.9000 V', '50 kHz', '4.8490', '4.9510', '1', '0.04', '5 V', None),
    ('|', '4.9000 V', '100 kHz', '4.7480', '5.0520', '3', '0.1', '5 V', None),
    ('|', '49.000 V', '50 Hz', '48.470', '49.530', '1', '0.08', '50 V', None),
    ('|', '49.000 V', '20 kHz', '48.819', '49.181', '0.35', '0.02', '50 V', None),
    ('|', '49.000 V', '50 kHz', '48.490', '49.510', '1', '0.04', '50 V', None),
    ('|', '49.000 V', '100 kHz', '47.480', '50.520', '3', '0.1', '50 V', None),
    ('|', '490.00 V', '50 Hz', '487.40', '492.60', '0.5', '0.03', '500 V', None),
    ('|', '700.0 V', '50 Hz', '696.3', '703.7', '0.5', '0.03', '500 V', '0.1 V'),
    ('Resistance', '490.00 Ohm', None, '489.46', '490.54', '0.1', '0.01', '500 Ohm', None),
    ('|', '4.9000 kOhm', None, '4.8947', '4.9053', '0.1', '0.008', '5 kOhm', None),
    ('|', '49.000 kOhm', None, '48.947', '49.053', '0.1', '0.008', '50 kOhm', None),
    ('|', '490.00 kOhm', None, '489.47', '490.53', '0.1', '0.008', '500 kOhm', None),
    ('|', '4.9000 MOhm', None, '4.8923', '4.9077', '0.15', '0.008', '5 MOhm', None),
    ('|', '49.000 MOhm', None, '48.848', '49.152', '0.3', '0.01', '50 MOhm', None),
    ('Continuity', '490.00 Ohm', None, '489.31', '490.69', '0.1', '0.04', '500 Ohm', None),
    ('Frequency', '9.0000 Hz', '500 mV', '8.9935', '9.0065', '0.05', '0.02', '10 Hz', None),
    ('|', '90.000 Hz', '500 mV', '89.971', '90.029', '0.01', '0.02', '100 Hz', None),
    ('|', '90.000 kHz', '500 mV', '89.983', '90.017', '0.01', '0.008', '100 kHz', None),
    ('|', '900.00 kHz', '500 mV', '899.83', '900.17', '0.01', '0.008', '1000 kHz', None),
    ('DC Amps', '4.9000 mA', None, '4.8970', '4.9030', '0.05', '0.01', '5 mA', '0.0001 mA'),
    ('|', '49.000 mA', None, '48.971', '49.029', '0.05', '0.008', '50 mA', '0.001 mA'),
    ('|', '490.00 mA', None, '489.71', '490.29', '0.05', '0.008', '500 mA', '0.01 mA'),
    ('|', '4.9000 A', None, '4.8872', '4.9128', '0.25', '0.01', '5 A', '0.0001 A'),
    ('|', '10.000 A', None, '9.972', '10.028', '0.25', '0.01', '20 A', '0.001 A'),
    ('|', '19.000 A', None, '18.950', '19.050', '0.25', '0.01', '20 A', '0.001 A'),
    ('AC Amps', '4.9000 mA', '20 Hz', '4.8185', '4.9815', '1.5', '0.16', '5 mA', None),
    ('|', '4.9000 mA', '50 Hz', '4.8185', '4.9815', '1.5', '0.16', '5 mA', None),
    ('|', '4.9000 mA', '2 kHz', '4.8715', '4.9285', '0.5', '0.08', '5 mA', None),
    ('|', '4.9000 mA', '20 kHz', '4.7695', '5.0305', '2.5', '0.16', '5 mA', None),
    ('|', '49.000 mA', '20 Hz', '48.185', '49.815', '1.5', '0.16', '50 mA', None),
    ('|', '49.000 mA', '50 Hz', '48.185', '49.815', '1.5', '0.16', '50 mA', None),
    ('|', '49.000 mA', '2 kHz', '48.715', '49.285', '0.5', '0.08', '50 mA', None),
    ('|', '49.000 mA', '20 kHz', '47.960', '50.040', '2', '0.12', '50 mA', None),
    ('|', '490.00 mA', '20 Hz', '481.85', '498.15', '1.5', '0.16', '500 mA', None),
    ('|', '490.00 mA', '2 kHz', '487.15', '492.85', '0.5', '0.08', '500 mA', None),
    ('|', '490.00 mA', '20 kHz', '479.60', '500.40', '2', '0.12', '500 mA', None),
    ('|', '4.9000 A', '50 Hz', '4.7940', '5.0060', '2', '0.16', '5 A', None),
    ('|', '4.9000 A', '2 kHz', '4.8705', '4.9295', '0.5', '0.1', '5 A', None),
    ('|', '10.000 A', '50 Hz', '9.768', '10.232', '2', '0.16', '20 A', None),
    ('|', '10.000 A', '2 kHz', '9.930', '10.070', '0.5', '0.1', '20 A', None),
    ('|', '19.000 A', '50 Hz', '18.588', '19.412', '2', '0.16', '20 A', None),
    ('|', '19.000 A', '2 kHz', '18.885', '19.115', '0.5', '0.1', '20 A', None),
]

# ----------------------------------------------------------------------------------------------------------------------------------
# The manual's 5491B accuracy tables (printed pp. 67 to 72): (% of reading, % of range), 1 year, 23 C +/- 5 C. Read from the rendered page images.
# ----------------------------------------------------------------------------------------------------------------------------------
Q = lambda a, b: (D(a), D(b))                                                       # noqa: E731
MAN_DCV = {D('0.5'): Q('0.02', '0.016'), D(5): Q('0.02', '0.008'), D(50): Q('0.02', '0.008'), D(500): Q('0.02', '0.008'), D(1000): Q('0.02', '0.008')}   # p. 68
MAN_ACV = {   # p. 69: bands lf 20-50 Hz, mid 50 Hz-20 kHz, hi 20-50 kHz, vhi 50-100 kHz ('------' = None)
    D('0.5'): dict(lf=Q('1.0', '0.08'), mid=Q('0.5', '0.06'), hi=Q('1.5', '0.1'), vhi=Q('3.0', '0.3')),
    D(5): dict(lf=Q('1.0', '0.08'), mid=Q('0.35', '0.02'), hi=Q('1', '0.04'), vhi=Q('3.0', '0.1')),
    D(50): dict(lf=Q('1.0', '0.08'), mid=Q('0.35', '0.02'), hi=Q('1', '0.04'), vhi=Q('3.0', '0.1')),
    D(500): dict(lf=None, mid=Q('0.5', '0.03'), hi=Q('1', '0.04'), vhi=Q('3.0', '0.1')),
    D(750): dict(lf=None, mid=Q('0.5', '0.03'), hi=Q('2.3', '0.15'), vhi=Q('3.3', '0.8'))}
MAN_OHM = {D(500): Q('0.10', '0.01'), D(5000): Q('0.10', '0.008'), D(50000): Q('0.10', '0.008'), D(500000): Q('0.10', '0.008'),
           D(5000000): Q('0.15', '0.008'), D(50000000): Q('0.3', '0.01')}            # p. 71
MAN_CONT = Q('0.1', '0.04')                                                          # p. 71 (500 ohm range)
MAN_FREQ = {D(10): Q('0.05', '0.02'), D(100): Q('0.01', '0.02'), D(100000): Q('0.01', '0.008'), D(1000000): Q('0.01', '0.008')}     # p. 71 (frequency)
MAN_DCI = {D('0.005'): Q('0.05', '0.01'), D('0.05'): Q('0.05', '0.008'), D('0.5'): Q('0.05', '0.008'), D(5): Q('0.25', '0.01'), D(20): Q('0.25', '0.01')}     # p. 70
MAN_ACI = {   # p. 70: bands lf 20-50 Hz, mid 50 Hz-2 kHz, hi 2-20 kHz
    D('0.005'): dict(lf=Q('1.5', '0.16'), mid=Q('0.5', '0.08'), hi=Q('2.5', '0.16')),
    D('0.05'): dict(lf=Q('1.5', '0.16'), mid=Q('0.5', '0.08'), hi=Q('2', '0.12')),
    D('0.5'): dict(lf=Q('1.5', '0.16'), mid=Q('0.5', '0.08'), hi=Q('2', '0.12')),
    D(5): dict(lf=Q('2.0', '0.16'), mid=Q('0.5', '0.1'), hi=None),
    D(20): dict(lf=Q('2.0', '0.16'), mid=Q('0.5', '0.1'), hi=None)}

# Where the lab datasheet (MDD) and the manual disagree: point number (1-based, MDD order) -> (code, text). The build FAILS on any other disagreement and on any listed one that
# is not real.
DISCREPANCIES = {
    2: ('pct_range', 'MDD: 0.08 % of range (5 V); the manual (p. 68) prints 0.008 %'),
    3: ('pct_range', 'MDD: 0.08 % of range (50 V); the manual (p. 68) prints 0.008 %'),
    4: ('pct_range', 'MDD: 0.08 % of range (500 V); the manual (p. 68) prints 0.008 %'),
    5: ('pct_range', 'MDD: 0.08 % of range (1000 V); the manual (p. 68) prints 0.008 %'),
    8: ('pct_range', 'MDD: 0.15 % of range (500 mV, 50 Hz - 20 kHz); the manual (p. 69) prints 0.06 %'),
    21: ('range', 'MDD: the 500 V range (full scale 500 V); 700 V is on the 750 V range, whose full scale is 750 V (p. 69)'),
}
FUNCTIONS = {'Volts DC': 'DCV', 'Volts AC': 'ACV', 'Resistance': 'OHM2', 'Continuity': 'OHM2', 'Frequency': 'FREQ', 'DC Amps': 'DCI', 'AC Amps': 'ACI'}
PAGES = {'DCV': 'p. 68', 'ACV': 'p. 69', 'OHM2': 'p. 71', 'CONT': 'p. 71', 'FREQ': 'p. 71', 'DCI': 'p. 70', 'ACI': 'p. 70'}


def parse_value(text):
    """'490.00 mV' -> (Decimal base value, base unit, display resolution in base units, display unit)."""
    number, unit = text.split()
    factor, base = UNITS[unit]
    decimals = len(number.split('.')[1]) if '.' in number else 0
    return D(number) * factor, base, D(1).scaleb(-decimals) * factor, unit


def trunc(x, res):
    return (x / res).to_integral_value(rounding=ROUND_DOWN) * res


def half_width(nominal, pr, pf, fs, floor, res):
    return trunc(abs(nominal) * pr / 100 + fs * pf / 100 + floor, res)


def ac_band(kind, hz):
    edges = (('lf', D(50)), ('mid', D(20000) if kind == 'ACV' else D(2000)), ('hi', D(50000) if kind == 'ACV' else D(20000)), ('vhi', D(100000)))
    for name, edge in edges:
        if hz <= edge:
            return name
    raise SystemExit(f'{kind} at {hz} Hz is above the last band')


def manual_pct(kind, function, fs, hz):
    """(% of reading, % of range) the manual prints for a point; AC frequency bands as the module docstring says."""
    if function == 'CONT':
        return MAN_CONT
    table = {'DCV': MAN_DCV, 'OHM2': MAN_OHM, 'FREQ': MAN_FREQ, 'DCI': MAN_DCI}.get(kind)
    if table is not None:
        return table[fs]
    bands = (MAN_ACV if kind == 'ACV' else MAN_ACI)[fs]
    names = ['lf', 'mid', 'hi', 'vhi']
    i = names.index(ac_band(kind, hz))
    while i < len(names) and bands.get(names[i]) is None:         # a column printed '------' (500 V and 750 V below 50 Hz): the next column applies
        i += 1
    if i >= len(names) or bands.get(names[i]) is None:
        raise SystemExit(f'{kind} {fs} at {hz} Hz has no printed column')
    return bands[names[i]]


def clean(x):
    return float(f'{x:.12g}')


def build_points():
    points, problems, last = [], [], None
    real_range = lambda kind, fn, nominal, fs: fs                                  # noqa: E731
    for n, (fn_text, nom_text, f_text, low_t, high_t, pr_t, pf_t, fs_text, floor_t) in enumerate(MDD_POINTS, start=1):
        last = last if fn_text == '|' else fn_text
        function = last
        kind = FUNCTIONS[function]
        nominal, base, res, nunit = parse_value(nom_text)
        factor = UNITS[nunit][0]
        low, high = D(low_t) * factor, D(high_t) * factor
        fs_mdd = parse_value(fs_text)[0]
        pr, pf = D(pr_t), D(pf_t)
        floor = parse_value(floor_t)[0] if floor_t else D(0)
        freq = amp = None
        if kind == 'FREQ':
            amp = parse_value(f_text)[0]
        elif f_text:
            freq = parse_value(f_text)[0]
        # 1. the MDD's own formula reproduces its printed limits (this is what proves the rule)
        h = half_width(nominal, pr, pf, fs_mdd, floor, res)
        if (nominal - h, nominal + h) != (low, high):
            problems.append(f'point {n} ({nom_text}{" @ " + f_text if f_text else ""}): the MDD limits {low_t} to {high_t} are not nominal +/- {h / factor} (its own formula)')
        # 2. the manual's tables
        fs_real = fs_mdd
        if n == 21:
            fs_real = D(750)                                                           # 700 V is on the 750 V range
        mpr, mpf = manual_pct(kind, 'CONT' if function == 'Continuity' else function, fs_real, freq if kind in ('ACV', 'ACI') else None)
        differs = (mpr, mpf, fs_real) != (pr, pf, fs_mdd)
        if differs != (n in DISCREPANCIES):
            problems.append(f'point {n}: MDD ({pr} % + {pf} % of {fs_mdd}) vs manual ({mpr} % + {mpf} % of {fs_real}): '
                            + ('an unlisted disagreement' if differs else 'listed as a disagreement but they agree'))
        mh = half_width(nominal, mpr, mpf, fs_real, floor, res)
        point = dict(ref=f'MDD #{n}', row=n, page=PAGES['CONT' if function == 'Continuity' else kind], kind=kind, nominal=clean(nominal), range=clean(fs_real), unit=base,
                     frequency=clean(freq) if freq is not None else None)
        if function == 'Continuity':
            point['function'] = 'CONT'
        if amp is not None:
            point['amplitude'] = clean(amp)
        point['limits'] = {'mdd': dict(low=clean(low), high=clean(high)), 'mfr': dict(low=clean(nominal - mh), high=clean(nominal + mh))}
        point['accuracy'] = {'mdd': [str(pr), str(pf)], 'mfr': [str(mpr), str(mpf)]}
        point['floor'] = clean(floor)
        if n in DISCREPANCIES:
            code, text = DISCREPANCIES[n]
            point['flags'] = [dict(code=code, why=text, mdd=[str(pr), str(pf), str(fs_mdd)], manual=[str(mpr), str(mpf), str(fs_real)])]
        point['std_relative'] = False
        point['source'] = 'calibrator'
        points.append(point)
    return points, problems


SECTIONS = [          # id, title, wiring group, manual page, setup text, selector
    ('DCV', 'DC volts', 'VOLT', 'p. 68', 'Calibrator voltage output to the meter V / ohm and COM terminals.', lambda p: p['kind'] == 'DCV'),
    ('ACV', 'AC volts', 'VOLT', 'p. 69', 'Calibrator voltage output to the meter V / ohm and COM terminals.', lambda p: p['kind'] == 'ACV'),
    ('FREQ', 'Frequency', 'VOLT', 'p. 71', 'Calibrator AC voltage output (0.5 V rms) to the meter V / ohm and COM terminals.', lambda p: p['kind'] == 'FREQ'),
    ('OHM2', 'Resistance', 'OHM2', 'p. 71', 'Calibrator resistance output to the meter V / ohm and COM terminals (2-wire).', lambda p: p['kind'] == 'OHM2' and not p.get('function')),
    ('CONT', 'Continuity', 'OHM2', 'p. 71', 'Calibrator resistance output to the meter V / ohm and COM terminals (2-wire).', lambda p: p.get('function') == 'CONT'),
    ('DCI_MA', 'DC current, 500 mA terminal', 'IMA', 'p. 70', 'Calibrator current output to the meter 500 mA terminal and COM.', lambda p: p['kind'] == 'DCI' and p['range'] <= 0.5),
    ('ACI_MA', 'AC current, 500 mA terminal', 'IMA', 'p. 70', 'Calibrator current output to the meter 500 mA terminal and COM.', lambda p: p['kind'] == 'ACI' and p['range'] <= 0.5),
    ('DCI_A', 'DC current, 20 A terminal', 'I20A', 'p. 70', 'Calibrator current output (20 A) to the meter 20 A terminal and COM.', lambda p: p['kind'] == 'DCI' and p['range'] > 0.5),
    ('ACI_A', 'AC current, 20 A terminal', 'I20A', 'p. 70', 'Calibrator current output (20 A) to the meter 20 A terminal and COM.', lambda p: p['kind'] == 'ACI' and p['range'] > 0.5),
]


def build_spec():
    points, problems = build_points()
    if problems:
        raise SystemExit('The lab datasheet (MDD) and the 5491B manual disagree beyond the listed points:\n  ' + '\n  '.join(problems))
    sections, used = [], 0
    for sid, title, group, page, setup, select in SECTIONS:
        plist = [p for p in points if select(p)]
        for p in plist:
            p.update(group=group, terminal={'VOLT': 'INPUT', 'OHM2': 'INPUT', 'IMA': '500MA', 'I20A': '20A'}[group], input=None)
        used += len(plist)
        sections.append(dict(id=sid, title=title, group=group, page=page, setup=setup, points=plist))
    if used != len(points):
        raise SystemExit(f'{len(points) - used} point(s) are in no section')
    counts = ', '.join(f'{s["title"]} {len(s["points"])}' for s in sections)
    return dict(
        schema=1, kind='bench-dmm-band', model=MODEL, periods=list(PERIODS), default_period='mdd', interface='rs232',
        options=dict(hv_threshold_v=100, report_title='Calibration Data', warm_up_minutes=30),
        source=dict(
            document='B&K Precision 5491B 5-1/2 digit multimeter: the lab datasheet B_K_Precision_5491B_Digital_Multimeter__365_Days_.MDD (ATS-1042), cross-checked against the 2831E / 5491B User Manual',
            pages='User Manual v1.10.2024, Chapter 7 (5491B specifications), printed pp. 67 to 72; remote commands Chapters 5 and 6, pp. 41 to 64',
            cite='Lab datasheet ATS-1042 (365-day interval); manufacturer specification: B&K 5491B User Manual, Chapter 7, pp. 67 to 72',
            limits='Lab datasheet limits as the MDD prints them (default), or the manufacturer specification of the manual (the two differ only at the points listed in the point flags)',
            report_note=('Limits are those of the lab datasheet ATS-1042 (365-day interval) unless the report header says the manufacturer specification was applied '
                         '(B&K 5491B User Manual, Chapter 7, pp. 67 to 72). Each limit is nominal +/- (% of reading + % of range + resolution floor), as the datasheet prints it.'),
            note=(f'{len(points)} points: {counts}. Limits: the lab datasheet (default) or the manufacturer specification; they differ at {len(DISCREPANCIES)} points (see the point details). '
                  'The meter must be warmed up for half an hour; the specification is valid in the slow rate only (NPLC 10), which the program selects.')),
        models={MODEL: dict(name='B&K Precision 5491B', brand='B&K Precision', model_note='B&K Precision 5491B 5-1/2 digit bench multimeter, RS-232 and USB (virtual COM)')},
        sections=sections)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=True), encoding='utf-8')
    counts = {s['id']: len(s['points']) for s in spec['sections']}
    print('wrote', OUT, sum(counts.values()), 'points', counts)
    print('points with flags:', ', '.join(p['ref'] for s in spec['sections'] for p in s['points'] if p.get('flags')))


if __name__ == '__main__':
    main()
