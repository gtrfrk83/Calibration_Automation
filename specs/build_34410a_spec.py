"""Writes specs/keysight_34410a_pv.json (Keysight / Agilent 34410A 6 1/2-digit multimeter, performance verification).

Source: Keysight 34410A/11A/L4411A Service Guide, Chapter 3 "Calibration Procedures", "Verification Tests" (printed pp. 68-87; PDF pages 70-89):
    Zero Offset Verification        printed p. 69   (front terminals, then the same table on the rear terminals, p. 68)
    DC Volts gain                   printed p. 71
    DC Current gain                 printed p. 73
    Ohms gain (4-wire; 100 Mohm 2-wire)  printed p. 75
    Frequency gain                  printed p. 77
    AC Volts                        printed p. 79
    AC Current                      printed p. 81
    Optional AC Voltage             printed p. 83
    Optional AC Current             printed p. 85
    Optional Capacitance            printed p. 87   (1 year only)
Every limit and nominal was read from the RENDERED PAGE IMAGES (pdftoppm), twice, not from extracted text (the extracted text corrupts the
mu and Omega signs).  The tables print three intervals (24 hour, 90 day, 1 year).  The Service Guide says acceptance is compared with the 90 day
limits and the 24 hour limits are for within 24 hours of an adjustment (p. 66); the lab chose 1 year for the other bench DMMs, so 1 year is the default here.

CROSS-CHECK (this script aborts if any printed limit disagrees): every printed half-width is recomputed in Decimal from the published accuracy
specification, Keysight 34410A/11A/L4411A User's Guide chapter 5 "Specifications" (printed pp. 129, 132, 134, 136; PDF pp. 131, 134, 136, 138):
    DC volts / resistance / DC current / capacitance   +/-(% of reading + % of range)   per interval
    AC volts / AC current                              +/-(% of reading + % of range) by frequency band; AC volts add 30 uV below 1 kHz and, on the 750 V range,
                                                       0.7 mV per volt above 300 V; AC current on the 3 A range adds 0.05 % of reading + 0.02 % of range
    Frequency                                          +/-(% of reading); for inputs from 10 mV to 100 mV on the 100 mV range the % of reading is multiplied by 10
    Zero offset                                        the % of range part only
A printed limit that equals the formula result "without" a footnote adder where the footnote applies is kept as printed and flagged in the point
('flags' + 'printed_limits'): see DC volts 1000 V (footnote 5: +0.02 mV per volt above 500 V).

Run:  python specs/build_34410a_spec.py
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keysight_34410a_pv.json'
PERIODS = ('24h', '90d', '1y')
DOC = 'Keysight 34410A/11A/L4411A Service Guide'
UG = "Keysight 34410A/11A/L4411A User's Guide"
SCALE = {'uV': D('1e-6'), 'mV': D('1e-3'), 'V': D(1), 'uA': D('1e-6'), 'mA': D('1e-3'), 'A': D(1), 'mohm': D('1e-3'), 'ohm': D(1),
         'kohm': D(1000), 'Mohm': D(1000000), 'mHz': D('1e-3'), 'Hz': D(1), 'kHz': D(1000), 'uF': D('1e-6'), 'nF': D('1e-9')}
BASE = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM2': 'ohm', 'OHM4': 'ohm', 'FREQ': 'Hz', 'CAP': 'F'}


def pct(r, g, reading, rng):
    """+/-(% of reading + % of range) as an exact Decimal in base units."""
    return (D(str(reading)) * D(r) + D(str(rng)) * D(g)) / D(100)


def num(text, unit):
    return D(text) * SCALE[unit]


# ---- accuracy specification (User's Guide pp. 129, 132, 134, 136): per range, per interval (% of reading, % of range) -------------------------------------
DCV = {  # range V
    '0.1': {'24h': ('0.0030', '0.0030'), '90d': ('0.0040', '0.0035'), '1y': ('0.0050', '0.0035')},
    '1': {'24h': ('0.0020', '0.0006'), '90d': ('0.0030', '0.0007'), '1y': ('0.0035', '0.0007')},
    '10': {'24h': ('0.0015', '0.0004'), '90d': ('0.0020', '0.0005'), '1y': ('0.0030', '0.0005')},
    '100': {'24h': ('0.0020', '0.0006'), '90d': ('0.0035', '0.0006'), '1y': ('0.0040', '0.0006')},
    '1000': {'24h': ('0.0020', '0.0006'), '90d': ('0.0035', '0.0006'), '1y': ('0.0040', '0.0006')},
}
OHM = {  # range ohm
    '100': {'24h': ('0.0030', '0.0030'), '90d': ('0.008', '0.004'), '1y': ('0.010', '0.004')},
    '1000': {'24h': ('0.0020', '0.0005'), '90d': ('0.007', '0.001'), '1y': ('0.010', '0.001')},
    '10000': {'24h': ('0.0020', '0.0005'), '90d': ('0.007', '0.001'), '1y': ('0.010', '0.001')},
    '100000': {'24h': ('0.0020', '0.0005'), '90d': ('0.007', '0.001'), '1y': ('0.010', '0.001')},
    '1000000': {'24h': ('0.0020', '0.0010'), '90d': ('0.010', '0.001'), '1y': ('0.012', '0.001')},
    '10000000': {'24h': ('0.0100', '0.0010'), '90d': ('0.030', '0.001'), '1y': ('0.040', '0.001')},
    '100000000': {'24h': ('0.200', '0.001'), '90d': ('0.600', '0.001'), '1y': ('0.800', '0.001')},
}
DCI = {  # range A
    '0.0001': {'24h': ('0.010', '0.020'), '90d': ('0.040', '0.025'), '1y': ('0.050', '0.025')},
    '0.001': {'24h': ('0.007', '0.006'), '90d': ('0.030', '0.006'), '1y': ('0.050', '0.006')},
    '0.01': {'24h': ('0.007', '0.020'), '90d': ('0.030', '0.020'), '1y': ('0.050', '0.020')},
    '0.1': {'24h': ('0.010', '0.004'), '90d': ('0.030', '0.005'), '1y': ('0.050', '0.005')},
    '1': {'24h': ('0.050', '0.006'), '90d': ('0.080', '0.010'), '1y': ('0.100', '0.010')},
    '3': {'24h': ('0.100', '0.020'), '90d': ('0.120', '0.020'), '1y': ('0.150', '0.020')},
}
ACV_BANDS = [  # (low Hz, high Hz, {interval: (% reading, % range)}) ; a frequency on a border belongs to the lower band (10 Hz-20 kHz includes 20 kHz, 20-50 kHz includes 50 kHz)
    (3, 5, {'24h': ('0.50', '0.02'), '90d': ('0.50', '0.03'), '1y': ('0.50', '0.03')}),
    (5, 10, {'24h': ('0.10', '0.02'), '90d': ('0.10', '0.03'), '1y': ('0.10', '0.03')}),
    (10, 20000, {'24h': ('0.02', '0.02'), '90d': ('0.05', '0.03'), '1y': ('0.06', '0.03')}),
    (20000, 50000, {'24h': ('0.05', '0.04'), '90d': ('0.09', '0.05'), '1y': ('0.10', '0.05')}),
    (50000, 100000, {'24h': ('0.20', '0.08'), '90d': ('0.30', '0.08'), '1y': ('0.40', '0.08')}),
    (100000, 300000, {'24h': ('1.00', '0.50'), '90d': ('1.20', '0.50'), '1y': ('1.20', '0.50')}),
]
ACI_BANDS = [(3, 5000, ('0.10', '0.04')), (5000, 10000, ('0.20', '0.04'))]      # the same in every interval
FREQ_BANDS = [(3, 5, {'24h': '0.07', '90d': '0.07', '1y': '0.07'}), (5, 10, {'24h': '0.04', '90d': '0.04', '1y': '0.04'}),
              (10, 40, {'24h': '0.02', '90d': '0.02', '1y': '0.02'}), (40, 300000, {'24h': '0.005', '90d': '0.006', '1y': '0.007'})]
CAP = {'1e-9': ('0.50', '0.50'), '1e-8': ('0.40', '0.10'), '1e-7': ('0.40', '0.10'), '1e-6': ('0.40', '0.10'), '1e-5': ('0.40', '0.10')}   # one column: 24 hour / 90 day / 1 year


def band(table, f, upper=False):
    """The accuracy band of frequency f.  A frequency on a border belongs to the LOWER band (20 kHz to 10 Hz-20 kHz, 50 kHz to 20-50 kHz, 5 kHz to 3 Hz-5 kHz) unless
    upper=True: the printed 10 Hz AC volts rows use the 10 Hz-20 kHz band and the printed 40 Hz frequency row uses the 40 Hz-300 kHz band."""
    for lo, hi, v in table:
        if (lo <= f < hi) if upper else (lo < f <= hi):
            return v
    raise SystemExit(f'no accuracy band for {f} Hz')


def pt(kind, nominal, rng, printed, calc, input=None, unit_n=None, **extra):
    """One point.  nominal: (text, unit) in the table's units; rng: base-unit string; printed: {interval: (text, unit)};
    calc(interval) -> [(label, Decimal half-width in base units), ...]: the first entry is what the specification gives, any later one a documented
    alternative (an adder).  The printed half-width must equal one of them exactly or the script aborts."""
    limits, text, flags = {}, {}, []
    for per in PERIODS:
        if per not in printed:
            continue
        t, u = printed[per]
        half = D(t) * SCALE[u]
        cands = calc(per)
        match = [lab for lab, v in cands if v == half]
        if not match:
            raise SystemExit(f'{kind} {nominal} range {rng}: printed {per} limit {t} {u} = {half} disagrees with the specification '
                             f'{[(lab, str(v)) for lab, v in cands]}')
        if match[0] != cands[0][0]:
            flags.append(f'{per}: printed limit equals the specification {match[0]}')
        limits[per] = float(half)
        text[per] = f'{t} {u}'
    p = dict(kind=kind, range=float(D(rng)), limits=limits, quick=False, printed_limits=text)
    if nominal is not None:
        p['nominal'] = float(D(nominal[0]) * SCALE[nominal[1]])
    p.update(extra)
    if input:
        p['input'] = input
    if flags:
        p['flags'] = flags
    return p


def same(per_text, unit):
    return {per: (per_text[i], unit) for i, per in enumerate(PERIODS)}


def printed3(t24, t90, t1y, unit):
    return {'24h': (t24, unit), '90d': (t90, unit), '1y': (t1y, unit)}


def zero_points(terminal):
    """Zero Offset Verification, printed p. 69: the % of range part of the specification."""
    rows = []
    def z(kind, rng, unit, p24, p90, p1y, table, input, q=False, plc=100):
        calc = lambda per: [('% of range only', pct('0', table[rng][per][1], 0, rng))]
        p = pt(kind, (('0', 'V') if kind == 'DCV' else ('0', 'A') if kind == 'DCI' else ('0', 'ohm')), rng, printed3(p24, p90, p1y, unit), calc,
               input=input, source='none', terminal=terminal, plc=plc)
        p['quick'] = q
        rows.append(p)
    for rng, unit, a, b, c, q in (('0.0001', 'uA', '0.02', '0.025', '0.025', False), ('0.001', 'uA', '0.060', '0.060', '0.060', False),
                                  ('0.01', 'uA', '2', '2', '2', False), ('0.1', 'uA', '4', '5', '5', True), ('1', 'uA', '60', '100', '100', False),
                                  ('3', 'uA', '600', '600', '600', False)):
        z('DCI', rng, unit, a, b, c, DCI, 'open', q)
    for rng, unit, a, b, c, q in (('0.1', 'uV', '3', '3.5', '3.5', True), ('1', 'uV', '6', '7', '7', False), ('10', 'uV', '40', '50', '50', False),
                                  ('100', 'uV', '600', '600', '600', False), ('1000', 'mV', '6', '6', '6', False)):
        z('DCV', rng, unit, a, b, c, DCV, 'short', q)
    for rng, unit, a, b, c, q in (('100', 'mohm', '3', '4', '4', False), ('1000', 'mohm', '5', '10', '10', False), ('10000', 'mohm', '50', '100', '100', True),
                                  ('100000', 'mohm', '500', '1000', '1000', False), ('1000000', 'ohm', '10', '10', '10', False),
                                  ('10000000', 'ohm', '100', '100', '100', False), ('100000000', 'kohm', '1', '1', '1', False)):
        z('OHM4', rng, unit, a, b, c, OHM, 'short', q)
    return rows


def gain_dcv():
    rows = []
    for nominal, unit, rng, p24, p90, p1y, q in (('0.1', 'V', '0.1', '6', '7.5', '8.5', False), ('-0.1', 'V', '0.1', '6', '7.5', '8.5', False),
                                                 ('1', 'V', '1', '26', '37', '42', False), ('10', 'V', '10', '190', '250', '350', True),
                                                 ('-10', 'V', '10', '190', '250', '350', False), ('100', 'V', '100', '2.6', '4.1', '4.6', True),
                                                 ('1000', 'V', '1000', '26', '41', '56', False)):
        big = rng == '1000'
        us = 'mV' if nominal in ('100', '1000') else 'uV'
        shown = {'0.1': ('100', 'mV'), '-0.1': ('-100', 'mV'), '1': ('1', 'V'), '10': ('10', 'V'), '-10': ('-10', 'V'), '100': ('100', 'V'), '1000': ('1000', 'V')}[nominal]
        def calc(per, nominal=nominal, rng=rng, big=big):
            r, g = DCV[rng][per]
            base = pct(r, g, abs(D(nominal)), rng)
            out = [('without the footnote 5 adder', base)]
            if big:
                out.append(('with the footnote 5 adder (+0.02 mV per volt above 500 V = 10 mV)', base + D('0.00002') * (abs(D(nominal)) - 500)))
            return out
        p = pt('DCV', (nominal, 'V'), rng, {'24h': (p24, us), '90d': (p90, us), '1y': (p1y, us)}, calc, plc=100, terminal='FRONT')
        p['quick'] = q
        p['table_nominal'] = f'{shown[0]} {shown[1]}'
        rows.append(p)
    return rows


def gain_dci():
    rows = []
    for nominal, unit, rng, p24, p90, p1y, q, lim_unit in (('100', 'uA', '0.0001', '0.03', '0.065', '0.075', False, 'uA'), ('1', 'mA', '0.001', '0.13', '0.36', '0.56', False, 'uA'),
                                                           ('10', 'mA', '0.01', '2.7', '5', '7', True, 'uA'), ('100', 'mA', '0.1', '14', '35', '55', False, 'uA'),
                                                           ('1', 'A', '1', '560', '900', '1.1', True, None), ('2', 'A', '3', '2.6', '3', '3.6', False, 'mA')):
        if rng == '1':
            pr = {'24h': ('560', 'uA'), '90d': ('900', 'uA'), '1y': ('1.1', 'mA')}
        elif lim_unit == 'mA':
            pr = {'24h': (p24, 'mA'), '90d': (p90, 'mA'), '1y': (p1y, 'mA')}
        else:
            pr = {'24h': (p24, 'uA'), '90d': (p90, 'uA'), '1y': (p1y, 'uA')}
        calc = lambda per, nominal=nominal, unit=unit, rng=rng: [('specification', pct(*DCI[rng][per], num(nominal, unit), rng))]
        p = pt('DCI', (nominal, unit), rng, pr, calc, plc=100, terminal='FRONT')
        p['quick'] = q
        rows.append(p)
    return rows


def gain_ohm():
    rows = []
    for nominal, unit, rng, pr, q in (('100', 'ohm', '100', printed3('6', '12', '14', 'mohm'), False), ('1', 'kohm', '1000', printed3('25', '80', '110', 'mohm'), True),
                                      ('10', 'kohm', '10000', printed3('250', '800', '1.1', None), False), ('100', 'kohm', '100000', printed3('2.5', '8', '11', 'ohm'), False),
                                      ('1', 'Mohm', '1000000', printed3('30', '110', '130', 'ohm'), False), ('10', 'Mohm', '10000000', printed3('1.1', '3.1', '4.1', 'kohm'), True),
                                      ('100', 'Mohm', '100000000', printed3('201', '601', '801', 'kohm'), False)):
        if rng == '10000':
            pr = {'24h': ('250', 'mohm'), '90d': ('800', 'mohm'), '1y': ('1.1', 'ohm')}
        calc = lambda per, nominal=nominal, unit=unit, rng=rng: [('specification', pct(*OHM[rng][per], num(nominal, unit), rng))]
        kind = 'OHM2' if rng == '100000000' else 'OHM4'          # footnote [2]: verify only, no adjustment, 2-wire ohms
        p = pt(kind, (nominal, unit), rng, pr, calc, plc=100, terminal='FRONT')
        p['quick'] = q
        if kind == 'OHM2':
            p['note'] = 'Table footnote 2: verify only, no adjustment. 2-wire ohms.'
        rows.append(p)
    return rows


def gain_freq():
    rows = []
    for hz, unit, amp, rng, pr, q in (('40', 'Hz', '0.01', '0.1', printed3('20', '24', '28', 'mHz'), False), ('10', 'kHz', '7', '10', printed3('0.5', '0.6', '0.7', 'Hz'), True)):
        f = D(hz) * SCALE[unit]
        mult = D(10) if (D(rng) == D('0.1') and D(amp) < D('0.1')) else D(1)           # 10 mV to 100 mV input on the 100 mV range: multiply the % of reading by 10 (User's Guide p. 134 note 3)
        calc = lambda per, f=f, mult=mult: [('specification', f * D(band(FREQ_BANDS, int(f), upper=True)[per]) * mult / D(100))]
        p = pt('FREQ', (hz, unit), rng, pr, calc, terminal='FRONT')
        p['amplitude'] = float(D(amp))
        p['quick'] = q
        p['aperture_s'] = 1
        rows.append(p)
    return rows


def acv_calc(nominal, rng, f):
    def calc(per):
        r, g = band(ACV_BANDS, f, upper=(f == 10))[per]
        v = pct(r, g, nominal, rng)
        if f < 1000:
            v += D('0.00003')                                    # note [4]: add 30 uV below 1 kHz
        if D(rng) == 750 and D(str(nominal)) > 300:
            v += D('0.0007') * (D(str(nominal)) - 300)           # note [4]: 750 V range add 0.7 mV per volt over 300 V
        return [('specification', v)]
    return calc


def gain_acv():
    rows = []
    for nominal, nunit, f, rng, pr, q in (
            ('100', 'mV', 1000, '0.1', printed3('40', '80', '90', 'uV'), False), ('100', 'mV', 50000, '0.1', printed3('90', '140', '150', 'uV'), True),
            ('100', 'mV', 300000, '0.1', printed3('1.50', '1.70', '1.70', 'mV'), False),
            ('1', 'V', 1000, '1', printed3('400', '800', '900', 'uV'), False), ('1', 'V', 50000, '1', {'24h': ('900', 'uV'), '90d': ('1.4', 'mV'), '1y': ('1.5', 'mV')}, False),
            ('1', 'V', 300000, '1', printed3('15', '17', '17', 'mV'), False),
            ('10', 'V', 10, '10', printed3('4.03', '8.03', '9.03', 'mV'), False), ('10', 'V', 1000, '10', printed3('4', '8', '9', 'mV'), False),
            ('10', 'V', 50000, '10', printed3('9', '14', '15', 'mV'), True), ('10', 'V', 300000, '10', printed3('150', '170', '170', 'mV'), False),
            ('100', 'V', 1000, '100', printed3('40', '80', '90', 'mV'), True), ('100', 'V', 50000, '100', printed3('90', '140', '150', 'mV'), False),
            ('50', 'V', 300000, '100', {'24h': ('1', 'V'), '90d': ('1.1', 'V'), '1y': ('1.1', 'V')}, False),
            ('750', 'V', 1000, '750', printed3('615', '915', '990', 'mV'), False), ('210', 'V', 50000, '750', printed3('405', '564', '585', 'mV'), False),
            ('70', 'V', 300000, '750', {'24h': ('4.45', 'V'), '90d': ('4.59', 'V'), '1y': ('4.59', 'V')}, False)):
        nom = num(nunit == 'mV' and nominal or nominal, nunit)
        p = pt('ACV', (nominal, nunit), rng, pr, acv_calc(nom, rng, f), frequency=float(f), filter_hz=3, terminal='FRONT')
        p['quick'] = q
        rows.append(p)
    return rows


def aci_calc(nominal, rng, f):
    def calc(per):
        r, g = band([(lo, hi, v) for lo, hi, v in ACI_BANDS], f)
        v = pct(r, g, nominal, rng)
        if D(rng) == 3:
            v += pct('0.05', '0.02', nominal, rng)               # note [5]: 3 A range (all frequencies): add 0.05 % of reading + 0.02 % of range
        return [('specification', v)]
    return calc


def gain_aci():
    rows = []
    for nominal, unit, f, rng, pr, q in (
            ('100', 'uA', 1000, '0.0001', same(('0.14', '0.14', '0.14'), 'uA'), False), ('100', 'uA', 5000, '0.0001', same(('0.14', '0.14', '0.14'), 'uA'), True),
            ('1', 'mA', 1000, '0.001', same(('1.4', '1.4', '1.4'), 'uA'), False), ('1', 'mA', 5000, '0.001', same(('1.4', '1.4', '1.4'), 'uA'), False),
            ('10', 'mA', 1000, '0.01', same(('14', '14', '14'), 'uA'), False), ('10', 'mA', 5000, '0.01', same(('14', '14', '14'), 'uA'), False),
            ('100', 'mA', 1000, '0.1', same(('140', '140', '140'), 'uA'), False), ('100', 'mA', 5000, '0.1', same(('140', '140', '140'), 'uA'), False),
            ('1', 'A', 1000, '1', same(('1.4', '1.4', '1.4'), 'mA'), False), ('1', 'A', 5000, '1', same(('1.4', '1.4', '1.4'), 'mA'), False),
            ('2', 'A', 1000, '3', same(('4.8', '4.8', '4.8'), 'mA'), False), ('2', 'A', 5000, '3', same(('4.8', '4.8', '4.8'), 'mA'), False)):
        p = pt('ACI', (nominal, unit), rng, pr, aci_calc(num(nominal, unit), rng, f), frequency=float(f), filter_hz=3, terminal='FRONT')
        p['quick'] = q
        rows.append(p)
    return rows


def opt_acv():
    rows = []
    for nominal, nunit, f, rng, pr in (
            ('1', 'V', 10, '1', printed3('430', '830', '930', 'uV')), ('1', 'V', 1000, '1', printed3('400', '800', '900', 'uV')),
            ('1', 'V', 20000, '1', printed3('400', '800', '900', 'uV')), ('1', 'V', 50000, '1', {'24h': ('900', 'uV'), '90d': ('1.4', 'mV'), '1y': ('1.5', 'mV')}),
            ('1', 'V', 100000, '1', printed3('2.8', '3.8', '4.8', 'mV')), ('1', 'V', 300000, '1', printed3('15', '17', '17', 'mV')),
            ('10', 'V', 1000, '10', printed3('4', '8', '9', 'mV')), ('1', 'V', 1000, '10', printed3('2.2', '3.5', '3.6', 'mV')),
            ('0.1', 'V', 1000, '10', printed3('2.02', '3.05', '3.06', 'mV'))):
        nom = D(nominal)
        p = pt('ACV', (nominal, 'V'), rng, pr, acv_calc(nom, rng, f), frequency=float(f), filter_hz=3, terminal='FRONT')
        rows.append(p)
    return rows


def opt_aci():
    rows = []
    for nominal, unit, f, rng, pr in (
            ('1', 'mA', 10, '0.001', same(('1.4', '1.4', '1.4'), 'uA')), ('1', 'mA', 1000, '0.001', same(('1.4', '1.4', '1.4'), 'uA')),
            ('1', 'mA', 5000, '0.001', same(('1.4', '1.4', '1.4'), 'uA')), ('100', 'mA', 1000, '0.1', same(('140', '140', '140'), 'uA')),
            ('10', 'mA', 1000, '0.1', same(('50', '50', '50'), 'uA')), ('1', 'mA', 1000, '0.1', same(('41', '41', '41'), 'uA'))):
        p = pt('ACI', (nominal, unit), rng, pr, aci_calc(num(nominal, unit), rng, f), frequency=float(f), filter_hz=3, terminal='FRONT')
        rows.append(p)
    return rows


def opt_cap():
    rows = []
    for rng, pr in (('1e-6', {'1y': ('0.005', 'uF')}), ('1e-5', {'1y': ('0.014', 'uF')})):
        calc = lambda per, rng=rng: [('specification', pct(*CAP[rng], D('1e-6'), rng))]
        p = pt('CAP', ('1', 'uF'), rng, pr, calc, terminal='FRONT', source='manual')
        # the accuracy table has ONE column for 24 hour / 90 day / 1 year (User's Guide p. 136), the Service Guide prints the 1 year column only
        p['limits'] = {per: p['limits']['1y'] for per in PERIODS}
        p['printed_limits'] = {'1y': p['printed_limits']['1y']}
        p['note'] = ('Optional test (Service Guide p. 87), 1 year limit printed; the specification has one column for 24 hour / 90 day / 1 year, so the same limit is used for all three. '
                     'Specification is with Math Null (User\'s Guide p. 136); null the test-lead capacitance with the leads open before connecting the standard.')
        rows.append(p)
    return rows


def build():
    def sec(id, title, page, setup, points, source='calibrator', terminal='FRONT', optional=False, group=None):
        s = dict(id=id, title=title, page=page, source=source, terminal=terminal, setup=setup, points=points)
        if optional:
            s['optional'] = True
        if group:
            s['group'] = group
        return s
    zero_setup = ('Install the 34172B low-thermal 4-terminal short (or equivalent) across the %s terminals; leave the current input OPEN for the DC current ranges. '
                  'Select the %s terminals with the Front/Rear switch. 100 NPLC. The calibrator stays in STANDBY.')
    sections = [
        sec('zero_front', 'Zero offset - front terminals', '69 (and 68, steps 1-3)', zero_setup % ('FRONT', 'FRONT'), zero_points('FRONT'), source='none', terminal='FRONT'),
        sec('zero_rear', 'Zero offset - rear terminals', '69 (and 68, steps 4-5)', zero_setup % ('REAR', 'REAR'), zero_points('REAR'), source='none', terminal='REAR'),
        sec('dcv', 'DC volts gain', '71', 'Calibrator voltage output to the front INPUT HI / LO; 100 NPLC; each range in the order of the table.', gain_dcv()),
        sec('dci', 'DC current gain', '73', 'Calibrator current output to the front 3 A (I) terminal and INPUT LO; 100 NPLC. Check the 3 A fuse first.', gain_dci()),
        sec('ohm', 'Resistance gain', '75', '4-wire ohms: calibrator force to INPUT HI / LO and sense to SENSE HI / LO (external sense on); 100 NPLC. The 100 Mohm point is 2-wire ohms.', gain_ohm()),
        sec('freq', 'Frequency gain', '77', 'Frequency function, default range, minimum resolution (1 s aperture). Calibrator AC voltage (a generator is the manual\'s standard) to INPUT HI / LO.', gain_freq()),
        sec('acv', 'AC volts', '79', 'AC volts, 3 Hz (slow) filter. Calibrator voltage output to the front INPUT HI / LO; each range in the order of the table.', gain_acv()),
        sec('aci', 'AC current', '81', 'AC current, 3 Hz (slow) filter. Calibrator current output to the front 3 A (I) terminal and INPUT LO.', gain_aci()),
        sec('acv_opt', 'AC volts, optional tests', '83', 'Optional AC voltage tests (Service Guide p. 82), 3 Hz filter.', opt_acv(), optional=True),
        sec('aci_opt', 'AC current, optional tests', '85', 'Optional AC current tests (Service Guide p. 84), 3 Hz filter.', opt_aci(), optional=True),
        sec('cap', 'Capacitance, optional tests', '87', 'Optional capacitance tests (Service Guide p. 86): a 1 uF capacitance standard (IET SCA-1uF) connected by the technician, 2-wire.',
            opt_cap(), source='manual', optional=True),
    ]
    return dict(
        schema=1, manufacturer='Keysight', model='34410A', title='34410A Performance Verification', idn_match=['34410A'],
        source=dict(document=DOC, pages='68-87 (Verification Tests, PDF pages 70-89)',
                    note='Three intervals are printed (24 hour, 90 day, 1 year). The manual compares acceptance results with the 90 day limits and uses the 24 hour limits only within 24 hours of '
                         'an adjustment (p. 66); the default here is the 1 year limit (calibration interval). Without adjustment the manual asks for a guard band of no more than 80 % of '
                         'the specification (p. 66): not applied. 1000 V DC: the 1 year limit includes the footnote 5 adder, the 24 hour and 90 day limits do not (as printed).'),
        periods=list(PERIODS), default_period='1y', front_rear_switch=True,
        equipment=dict(zero='Keysight 34172B low-thermal short (4-terminal)', dc_ac_source='Fluke 5720A (manual); this procedure drives a Fluke 5522A, 5560A or 5520A',
                       frequency='Keysight 33220A (manual); the calibrator\'s own AC voltage output at the stated frequency is used', capacitance='IET SCA-1uF',
                       accuracy_requirement='<1/5 of the instrument 24 hour specification (p. 64)'),
        general=['Ambient 18 to 28 C (ideally 23 C +/- 2 C), relative humidity below 80 % (p. 67).',
                 'Allow a 90 minute warm-up with a copper short connected (p. 67).',
                 'Shielded twisted-pair PTFE cables, shields to earth ground at one place (p. 67).',
                 'Select 100 NPLC for DC volts, DC current and resistance; the 3 Hz (slow) AC filter for AC volts and AC current (pp. 69-82).',
                 'Without adjustment use a guard band of no more than 80 % of the specification (p. 66): not applied.'],
        measure=dict(nplc=100, ac_bandwidth=3, freq_aperture_s=1,
                     note='100 NPLC (DC volts, DC current, resistance, zero offset), AC bandwidth 3 Hz (AC volts, AC current), frequency CONF:FREQ DEF,MIN (1 s aperture): '
                          'the conditions the tables state (footnote [1] of each table, pp. 69-82).'),
        sections=sections)


def main():
    spec = build()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
    total = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {total} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
