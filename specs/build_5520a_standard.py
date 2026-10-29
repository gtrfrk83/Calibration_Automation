"""Builds specs/standards/fluke_5520a_standard.json from the Fluke 5520A Service Manual, Chapter 1 (Specifications).

    python specs/build_5520a_standard.py            # writes specs/standards/fluke_5520a_standard.json

SOURCE: '5520A_Manual.pdf' (5520A Service Manual with the SC300 / SC600 chapters, 254 PDF pages).  Printed page 1-N is PDF page N + 16
(general specifications 1-7 = PDF p. 23).  Rows carry the PDF page in 'page'; notes and the 'limits' list quote the printed page.

Every number below was typed from RENDERED PAGE IMAGES (pdftoppm, 130 dpi page, then a 200 dpi crop read a second time), NOT from extracted text:
  1-7   General Specifications (PDF 23): warm-up, tcal, temperature coefficient, absolute-uncertainty definition, "Specification Confidence Interval 99 %"
  1-8   DC voltage (PDF 24)          1-9   DC current (PDF 25)           1-11  Resistance (PDF 27)
  1-12  AC voltage, NORMAL (PDF 28)  1-13  AC voltage, AUX (PDF 29)       1-14  AC current LCOMP off (PDF 30)
  1-15  AC current LCOMP on + resolution / compliance (PDF 31)            1-16  Capacitance (PDF 32)
  1-17  Thermocouple (PDF 33)        1-18  RTD (PDF 34)                   1-20  Power and dual-output limits (PDF 36)
  1-23  Frequency (PDF 39)           1-25  AC voltage extended bandwidth (PDF 41)
Both columns the manual prints, 90 days and 1 year, are stored (period '90 day' and '1 yr'); frequency prints one column (1 year) and is stored as such.
Values are SI base units; ppm / percent of output become 'rel', the floor becomes 'abs'.  Specifications are parsed by specmanager.parse_spec from
text of the same form the other standard sheets use, so the code path is the same as for the 5522A and 5560A.

Where the printed table disagrees with itself or with what the instrument does, the printed value is stored and the point is flagged in NOTES / problems; nothing is
silently corrected.  NOT stored: stability (24 h), noise / distortion columns, max burden, compliance adders, TC linear modes, power, phase, harmonics, non-sine and
extended-bandwidth AC (summarised in 'limits' only), SC300 / SC600 scope-option specifications.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402
sys.path.insert(0, str(HERE))
import build_square_wave_rows as sq  # noqa: E402

PDF_OFFSET = 16
MU = 'µ'
DEG = '°C'
PERIODS = ('90 day', '1 yr')


# ---------------------------------------------------------------------------------------------------------- helpers
def spec_text(period, rel=None, rel_unit='ppm', floor=None, floor_unit=''):
    """'[90 day] Accuracy: +/-(15 ppm I.V. + 1 uV)' (the sheet text form parsed by specmanager)."""
    terms = []
    if rel is not None:
        terms.append(f'{rel:g} {rel_unit} I.V.')
    if floor is not None:
        terms.append(f'{floor:g} {floor_unit}')
    return f'[{period}] Accuracy: +/-(' + ' + '.join(terms) + ')'


def make_row(fname, label, param_texts, specs, page, resolution=None, printed=''):
    """One range row.  param_texts: ['0 mV to 329.9999 mV', ('1 Hz to 10 Hz')]; specs: list of spec texts."""
    params = []
    for t in param_texts:
        p = sm.parse_param(t)
        if p is None:
            raise ValueError(f'cannot parse value range {t!r}')
        params.append(p)
    parsed = []
    for t in specs:
        s = sm.parse_spec(t)
        if s.get('error'):
            raise ValueError(f'cannot parse specification {t!r}: {s["error"]}')
        parsed.append(s)
    rng = dict(label=label, page=page, params=params, specs=parsed, raw_other=[])
    rng.update(sm.analyse_range(fname, label, params))
    if resolution is not None:
        rng['resolution'] = resolution
        rng['res_src'] = 'manual'
    if printed:
        rng['printed'] = printed
    return rng


def fn(name, direction, ranges, page):
    return dict(name=name, direction=direction, page=page, ranges=ranges)


def pdf(printed_n):
    return printed_n + PDF_OFFSET


def both(r90, f90, r1, f1, unit_rel, floor_unit):
    return [spec_text('90 day', r90, unit_rel, f90, floor_unit), spec_text('1 yr', r1, unit_rel, f1, floor_unit)]


# ---------------------------------------------------------------------------------------------------------- DC voltage (p. 1-8)
# (label, effective band, printed range text, (ppm, uV) 90 d, (ppm, uV) 1 yr, resolution V)
DCV = [
    ('329.9999 mV', '0 mV to 329.9999 mV', '0 to 329.9999 mV', (15, 1), (20, 1), 0.1e-6),
    ('3.299999 V', '0.33 V to 3.299999 V', '0 to 3.299999 V', (9, 2), (11, 2), 1e-6),
    ('32.99999 V', '3.3 V to 32.99999 V', '0 to 32.99999 V', (10, 20), (12, 20), 10e-6),
    ('329.9999 V', '33 V to 329.9999 V', '30 V to 329.9999 V', (15, 150), (18, 150), 100e-6),
    ('1000.000 V', '330 V to 1000.000 V', '100 V to 1000.000 V', (15, 1500), (18, 1500), 1000e-6),
]
DCV_AUX = [   # Auxiliary output (dual output mode only)
    ('329.999 mV', '0 mV to 329.999 mV', '0 to 329.999 mV', (300, 350), (400, 350), 1e-6),
    ('3.29999 V', '0.33 V to 3.29999 V', '0.33 V to 3.29999 V', (300, 350), (400, 350), 10e-6),
    ('7 V', '3.3 V to 7 V', '3.3 V to 7 V', (300, 350), (400, 350), 100e-6),
]


def dc_voltage():
    rows = []
    for lab, band, printed, a, b, res in DCV:
        rows.append(make_row('Voltage, DC', lab, [band], both(a[0], a[1], b[0], b[1], 'ppm', MU + 'V'), pdf(24), res, printed))
    aux = []
    for lab, band, printed, a, b, res in DCV_AUX:
        aux.append(make_row('Voltage, DC [Auxiliary Output (Dual Output Mode)]', lab, [band], both(a[0], a[1], b[0], b[1], 'ppm', MU + 'V'), pdf(24), res, printed))
    return [fn('Voltage, DC', 'output', rows, pdf(24)),
            fn('Voltage, DC [Auxiliary Output (Dual Output Mode)]', 'output', aux, pdf(24))]


# ---------------------------------------------------------------------------------------------------------- DC current (p. 1-9)
# (label, effective band, printed range, (ppm, uA) 90 d, (ppm, uA) 1 yr, resolution A)   resolution: the printed column says 'nA, mA ...' = see note 9
DCI = [
    ('329.999 ' + MU + 'A', '0 ' + MU + 'A to 329.999 ' + MU + 'A', '0 to 329.999 mA [sic, microamps]', (120, 0.02), (150, 0.02), 1e-9),
    ('3.29999 mA', '0.33 mA to 3.29999 mA', '0 to 3.29999 mA', (80, 0.05), (100, 0.05), 1e-8),
    ('32.9999 mA', '3.3 mA to 32.9999 mA', '0 to 32.9999 mA', (80, 0.25), (100, 0.25), 1e-7),
    ('329.999 mA', '33 mA to 329.999 mA', '0 to 329.999 mA', (80, 2.5), (100, 2.5), 1e-6),
    ('1.09999 A', '0.33 A to 1.09999 A', '0 to 1.09999 A', (160, 40), (200, 40), 1e-5),
    ('2.99999 A', '1.1 A to 2.99999 A', '1.1 to 2.99999 A', (300, 40), (380, 40), 1e-5),
    ('10.9999 A', '3 A to 10.9999 A', '0 to 10.9999 A (20 A Range)', (380, 500), (500, 500), 1e-4),
    ('20.5 A', '11 A to 20.5 A', '11 to 20.5 A [1][2]', (800, 750), (1000, 750), 1e-4),
]


def dc_current():
    rows = [make_row('Current, DC', lab, [band], both(a[0], a[1], b[0], b[1], 'ppm', MU + 'A'), pdf(25), res, printed) for lab, band, printed, a, b, res in DCI]
    return [fn('Current, DC', 'output', rows, pdf(25))]


# ---------------------------------------------------------------------------------------------------------- Resistance (p. 1-11)
# (label, band, ppm 90 d, ppm 1 yr, floor 12 h +/-1 C (ohm), floor 7 d +/-5 C (ohm), resolution ohm)
OHM = [
    ('10.9999 ohm', '0 ohm to 10.9999 ohm', 35, 40, 0.001, 0.01, 0.0001),
    ('32.9999 ohm', '11 ohm to 32.9999 ohm', 25, 30, 0.0015, 0.015, 0.0001),
    ('109.9999 ohm', '33 ohm to 109.9999 ohm', 22, 28, 0.0014, 0.015, 0.0001),
    ('329.9999 ohm', '110 ohm to 329.9999 ohm', 22, 28, 0.002, 0.02, 0.0001),
    ('1.099999 kohm', '330 ohm to 1.099999 kohm', 22, 28, 0.002, 0.02, 0.001),
    ('3.299999 kohm', '1.1 kohm to 3.299999 kohm', 22, 28, 0.02, 0.2, 0.001),
    ('10.99999 kohm', '3.3 kohm to 10.99999 kohm', 22, 28, 0.02, 0.1, 0.01),
    ('32.99999 kohm', '11 kohm to 32.99999 kohm', 22, 28, 0.2, 1, 0.01),
    ('109.9999 kohm', '33 kohm to 109.9999 kohm', 22, 28, 0.2, 1, 0.1),
    ('329.9999 kohm', '110 kohm to 329.9999 kohm', 25, 32, 2, 10, 0.1),
    ('1.099999 Mohm', '330 kohm to 1.099999 Mohm', 25, 32, 2, 10, 1),
    ('3.299999 Mohm', '1.1 Mohm to 3.299999 Mohm', 40, 60, 30, 150, 1),
    ('10.99999 Mohm', '3.3 Mohm to 10.99999 Mohm', 110, 130, 50, 250, 10),
    ('32.99999 Mohm', '11 Mohm to 32.99999 Mohm', 200, 250, 2500, 2500, 10),
    ('109.9999 Mohm', '33 Mohm to 109.9999 Mohm', 400, 500, 3000, 3000, 100),
    ('329.9999 Mohm', '110 Mohm to 329.9999 Mohm', 2500, 3000, 100000, 100000, 1000),
    ('1100 Mohm', '330 Mohm to 1100 Mohm', 12000, 15000, 500000, 500000, 10000),
]


def resistance():
    twelve, seven = [], []
    for lab, band, p90, p1, f12, f7, res in OHM:
        twelve.append(make_row('Resistance', lab, [band], both(p90, f12, p1, f12, 'ppm', 'ohm'), pdf(27), res))
        seven.append(make_row('Resistance [7 Day Zero Cal Floor]', lab, [band], both(p90, f7, p1, f7, 'ppm', 'ohm'), pdf(27), res))
    return [fn('Resistance', 'output', twelve, pdf(27)),
            fn('Resistance [7 Day Zero Cal Floor]', 'output', seven, pdf(27))]


# ---------------------------------------------------------------------------------------------------------- AC voltage (pp. 1-12, 1-13)
# NORMAL: per range (label, band, resolution V, bands [(f_lo, f_hi, (ppm, uV) 90 d, (ppm, uV) 1 yr)])
HZ = lambda f: (f'{f:g} Hz' if f < 1e3 else f'{f / 1e3:g} kHz')       # noqa: E731
ACV = [
    ('32.999 mV', '1 mV to 32.999 mV', 1e-6, [(10, 45, (600, 6), (800, 6)), (45, 10e3, (120, 6), (150, 6)), (10e3, 20e3, (160, 6), (200, 6)),
                                              (20e3, 50e3, (800, 6), (1000, 6)), (50e3, 100e3, (3000, 12), (3500, 12)), (100e3, 500e3, (6000, 50), (8000, 50))]),
    ('329.999 mV', '33 mV to 329.999 mV', 1e-6, [(10, 45, (250, 8), (300, 8)), (45, 10e3, (140, 8), (145, 8)), (10e3, 20e3, (150, 8), (160, 8)),
                                                  (20e3, 50e3, (300, 8), (350, 8)), (50e3, 100e3, (600, 32), (800, 32)), (100e3, 500e3, (1600, 70), (2000, 70))]),
    ('3.29999 V', '0.33 V to 3.29999 V', 10e-6, [(10, 45, (250, 50), (300, 50)), (45, 10e3, (140, 60), (150, 60)), (10e3, 20e3, (160, 60), (190, 60)),
                                                  (20e3, 50e3, (250, 50), (300, 50)), (50e3, 100e3, (550, 125), (700, 125)), (100e3, 500e3, (2000, 600), (2400, 600))]),
    ('32.9999 V', '3.3 V to 32.9999 V', 100e-6, [(10, 45, (250, 650), (300, 650)), (45, 10e3, (125, 600), (150, 600)), (10e3, 20e3, (220, 600), (240, 600)),
                                                  (20e3, 50e3, (300, 600), (350, 600)), (50e3, 100e3, (750, 1600), (900, 1600))]),
    ('329.999 V', '33 V to 329.999 V', 1e-3, [(45, 1e3, (150, 2000), (190, 2000)), (1e3, 10e3, (160, 6000), (200, 6000)), (10e3, 20e3, (220, 6000), (250, 6000)),
                                              (20e3, 50e3, (240, 6000), (300, 6000)), (50e3, 100e3, (1600, 50000), (2000, 50000))]),
    ('1020 V', '330 V to 1020 V', 10e-3, [(45, 1e3, (250, 10000), (300, 10000)), (1e3, 5e3, (200, 10000), (250, 10000)), (5e3, 10e3, (250, 10000), (300, 10000))]),
]
# AUX (dual output only), % of output + uV.  (label, band, resolution V, bands [(f_lo, f_hi, (%, uV) 90 d, (%, uV) 1 yr)])
ACV_AUX = [
    ('329.999 mV', '10 mV to 329.999 mV', 1e-6, [(10, 20, (0.15, 370), (0.2, 370)), (20, 45, (0.08, 370), (0.1, 370)), (45, 1e3, (0.08, 370), (0.1, 370)),
                                                  (1e3, 5e3, (0.15, 450), (0.2, 450)), (5e3, 10e3, (0.3, 450), (0.4, 450)), (10e3, 30e3, (4.0, 900), (5.0, 900))]),
    ('3.29999 V', '0.33 V to 3.29999 V', 10e-6, [(10, 20, (0.15, 450), (0.2, 450)), (20, 45, (0.08, 450), (0.1, 450)), (45, 1e3, (0.07, 450), (0.09, 450)),
                                                  (1e3, 5e3, (0.15, 1400), (0.2, 1400)), (5e3, 10e3, (0.3, 1400), (0.4, 1400)), (10e3, 30e3, (4.0, 2800), (5.0, 2800))]),
    ('5 V', '3.3 V to 5 V', 100e-6, [(10, 20, (0.15, 450), (0.2, 450)), (20, 45, (0.08, 450), (0.1, 450)), (45, 1e3, (0.07, 450), (0.09, 450)),
                                      (1e3, 5e3, (0.15, 1400), (0.2, 1400)), (5e3, 10e3, (0.3, 1400), (0.4, 1400))]),
]


def _ac_rows(fname, table, rel_unit, page):
    rows = []
    for lab, band, res, bands in table:
        for f_lo, f_hi, a, b in bands:
            rows.append(make_row(fname, f'{lab} @ {HZ(f_lo)} to {HZ(f_hi)}', [band, f'{HZ(f_lo)} to {HZ(f_hi)}'],
                                 both(a[0], a[1], b[0], b[1], rel_unit, MU + 'V'), page, res))
    return rows


def ac_voltage():
    return [fn('Voltage, AC [Sinewave]', 'output', _ac_rows('Voltage, AC [Sinewave]', ACV, 'ppm', pdf(28)), pdf(28)),
            fn('Voltage, AC [Sinewave Auxiliary Output (Dual Output Mode)]', 'output',
               _ac_rows('Voltage, AC [Sinewave Auxiliary Output (Dual Output Mode)]', ACV_AUX, '%', pdf(29)), pdf(29))]


# ---------------------------------------------------------------------------------------------------------- AC current (pp. 1-14, 1-15)
# % of output + uA.  (label, band, resolution A, bands [(f_lo, f_hi, (%, uA) 90 d, (%, uA) 1 yr)])
ACI_OFF = [
    ('329.99 ' + MU + 'A', '29 ' + MU + 'A to 329.99 ' + MU + 'A', 0.01e-6,
     [(10, 20, (0.16, 0.1), (0.2, 0.1)), (20, 45, (0.12, 0.1), (0.15, 0.1)), (45, 1e3, (0.1, 0.1), (0.125, 0.1)), (1e3, 5e3, (0.25, 0.15), (0.3, 0.15)),
      (5e3, 10e3, (0.6, 0.2), (0.8, 0.2)), (10e3, 30e3, (1.2, 0.4), (1.6, 0.4))]),
    ('3.2999 mA', '0.33 mA to 3.2999 mA', 0.01e-6,
     [(10, 20, (0.16, 0.15), (0.2, 0.15)), (20, 45, (0.1, 0.15), (0.125, 0.15)), (45, 1e3, (0.08, 0.15), (0.1, 0.15)), (1e3, 5e3, (0.16, 0.2), (0.2, 0.2)),
      (5e3, 10e3, (0.4, 0.3), (0.5, 0.3)), (10e3, 30e3, (0.8, 0.6), (1.0, 0.6))]),
    ('32.999 mA', '3.3 mA to 32.999 mA', 0.1e-6,
     [(10, 20, (0.15, 2), (0.18, 2)), (20, 45, (0.075, 2), (0.09, 2)), (45, 1e3, (0.035, 2), (0.04, 2)), (1e3, 5e3, (0.065, 2), (0.08, 2)),
      (5e3, 10e3, (0.16, 3), (0.2, 3)), (10e3, 30e3, (0.32, 4), (0.4, 4))]),
    ('329.99 mA', '33 mA to 329.99 mA', 1e-6,
     [(10, 20, (0.15, 20), (0.18, 20)), (20, 45, (0.075, 20), (0.09, 20)), (45, 1e3, (0.035, 20), (0.04, 20)), (1e3, 5e3, (0.08, 50), (0.10, 50)),
      (5e3, 10e3, (0.16, 100), (0.2, 100)), (10e3, 30e3, (0.32, 200), (0.4, 200))]),
    ('1.09999 A', '0.33 A to 1.09999 A', 10e-6,
     [(10, 45, (0.15, 100), (0.18, 100)), (45, 1e3, (0.036, 100), (0.05, 100)), (1e3, 5e3, (0.5, 1000), (0.6, 1000)), (5e3, 10e3, (2.0, 5000), (2.5, 5000))]),
    ('2.99999 A', '1.1 A to 2.99999 A', 10e-6,
     [(10, 45, (0.15, 100), (0.18, 100)), (45, 1e3, (0.05, 100), (0.06, 100)), (1e3, 5e3, (0.5, 1000), (0.6, 1000)), (5e3, 10e3, (2.0, 5000), (2.5, 5000))]),
    ('10.9999 A', '3 A to 10.9999 A', 100e-6,
     [(45, 100, (0.05, 2000), (0.06, 2000)), (100, 1e3, (0.08, 2000), (0.10, 2000)), (1e3, 5e3, (2.5, 2000), (3.0, 2000))]),
    ('20.5 A', '11 A to 20.5 A', 100e-6,
     [(45, 100, (0.1, 5000), (0.12, 5000)), (100, 1e3, (0.13, 5000), (0.15, 5000)), (1e3, 5e3, (2.5, 5000), (3.0, 5000))]),
]
ACI_ON = [
    ('329.99 ' + MU + 'A', '29 ' + MU + 'A to 329.99 ' + MU + 'A', 0.01e-6, [(10, 100, (0.2, 0.2), (0.25, 0.2)), (100, 1e3, (0.5, 0.5), (0.6, 0.5))]),
    ('3.2999 mA', '0.33 mA to 3.2999 mA', 0.01e-6, [(10, 100, (0.2, 0.3), (0.25, 0.3)), (100, 1e3, (0.5, 0.8), (0.6, 0.8))]),
    ('32.999 mA', '3.3 mA to 32.999 mA', 0.1e-6, [(10, 100, (0.07, 4), (0.08, 4)), (100, 1e3, (0.18, 10), (0.2, 10))]),
    ('329.99 mA', '33 mA to 329.99 mA', 1e-6, [(10, 100, (0.07, 40), (0.08, 40)), (100, 1e3, (0.18, 100), (0.2, 100))]),
    ('2.99999 A', '0.33 A to 2.99999 A', 10e-6, [(10, 100, (0.1, 200), (0.12, 200)), (100, 440, (0.25, 1000), (0.3, 1000))]),
    ('20.5 A', '3 A to 20.5 A', 100e-6, [(10, 100, (0.1, 2000), (0.12, 2000)), (100, 1e3, (0.8, 5000), (1.0, 5000))]),
]


def ac_current():
    off = _ac_rows_i('Current, AC [Sinewave, LCOMP off]', ACI_OFF, pdf(30))
    on = _ac_rows_i('Current, AC [Sinewave, LCOMP on]', ACI_ON, pdf(31))
    return [fn('Current, AC [Sinewave, LCOMP off]', 'output', off, pdf(30)), fn('Current, AC [Sinewave, LCOMP on]', 'output', on, pdf(31))]


def _ac_rows_i(fname, table, page):
    rows = []
    for lab, band, res, bands in table:
        for f_lo, f_hi, a, b in bands:
            rows.append(make_row(fname, f'{lab} @ {HZ(f_lo)} to {HZ(f_hi)}', [band, f'{HZ(f_lo)} to {HZ(f_hi)}'],
                                 both(a[0], a[1], b[0], b[1], '%', MU + 'A'), page, res))
    return rows


# ---------------------------------------------------------------------------------------------------------- Capacitance (p. 1-16)
# (label, band, % 90 d, floor 90 d, % 1 yr, floor 1 yr, floor unit, resolution F, allowed frequency text)
CAP = [
    ('0.3999 nF', '0.19 nF to 0.3999 nF', 0.38, 0.01, 0.5, 0.01, 'nF', 0.1e-12, '10 Hz to 10 kHz'),
    ('1.0999 nF', '0.4 nF to 1.0999 nF', 0.38, 0.01, 0.5, 0.01, 'nF', 0.1e-12, '10 Hz to 10 kHz'),
    ('3.2999 nF', '1.1 nF to 3.2999 nF', 0.38, 0.01, 0.5, 0.01, 'nF', 0.1e-12, '10 Hz to 3 kHz'),
    ('10.9999 nF', '3.3 nF to 10.9999 nF', 0.19, 0.01, 0.25, 0.01, 'nF', 0.1e-12, '10 Hz to 1 kHz'),
    ('32.9999 nF', '11 nF to 32.9999 nF', 0.19, 0.1, 0.25, 0.1, 'nF', 0.1e-12, '10 Hz to 1 kHz'),
    ('109.999 nF', '33 nF to 109.999 nF', 0.19, 0.1, 0.25, 0.1, 'nF', 1e-12, '10 Hz to 1 kHz'),
    ('329.999 nF', '110 nF to 329.999 nF', 0.19, 0.3, 0.25, 0.3, 'nF', 1e-12, '10 Hz to 1 kHz'),
    ('1.09999 ' + MU + 'F', '0.33 ' + MU + 'F to 1.09999 ' + MU + 'F', 0.19, 1, 0.25, 1, 'nF', 10e-12, '10 Hz to 600 Hz'),
    ('3.29999 ' + MU + 'F', '1.1 ' + MU + 'F to 3.29999 ' + MU + 'F', 0.19, 3, 0.25, 3, 'nF', 10e-12, '10 Hz to 300 Hz'),
    ('10.9999 ' + MU + 'F', '3.3 ' + MU + 'F to 10.9999 ' + MU + 'F', 0.19, 10, 0.25, 10, 'nF', 100e-12, '10 Hz to 150 Hz'),
    ('32.9999 ' + MU + 'F', '11 ' + MU + 'F to 32.9999 ' + MU + 'F', 0.30, 30, 0.40, 30, 'nF', 100e-12, '10 Hz to 120 Hz'),
    ('109.999 ' + MU + 'F', '33 ' + MU + 'F to 109.999 ' + MU + 'F', 0.34, 100, 0.45, 100, 'nF', 1e-9, '10 Hz to 80 Hz'),
    ('329.999 ' + MU + 'F', '110 ' + MU + 'F to 329.999 ' + MU + 'F', 0.34, 300, 0.45, 300, 'nF', 1e-9, '0 to 50 Hz'),
    ('1.09999 mF', '0.33 mF to 1.09999 mF', 0.34, 1, 0.45, 1, MU + 'F', 10e-9, '0 to 20 Hz'),
    ('3.2999 mF', '1.1 mF to 3.2999 mF', 0.34, 3, 0.45, 3, MU + 'F', 10e-9, '0 to 6 Hz'),
    ('10.9999 mF', '3.3 mF to 10.9999 mF', 0.34, 10, 0.45, 10, MU + 'F', 100e-9, '0 to 2 Hz'),
    ('32.9999 mF', '11 mF to 32.9999 mF', 0.7, 30, 0.75, 30, MU + 'F', 100e-9, '0 to 0.6 Hz'),
    ('110 mF', '33 mF to 110 mF', 1.0, 100, 1.1, 100, MU + 'F', 10e-6, '0 to 0.2 Hz'),
]


def capacitance():
    rows = []
    for lab, band, p90, f90, p1, f1, fu, res, allowed in CAP:
        specs = [spec_text('90 day', p90, '%', f90, fu), spec_text('1 yr', p1, '%', f1, fu)]
        r = make_row('Capacitance', lab, [band], specs, pdf(32), res)
        r['allowed_frequency'] = allowed          # printed 'Min and Max to Meet Specification' column (informational)
        rows.append(r)
    return [fn('Capacitance', 'output', rows, pdf(32))]


# ---------------------------------------------------------------------------------------------------------- Thermocouple (p. 1-17) and RTD (p. 1-18)
TC = {   # type -> [(lo, hi, 90 d, 1 yr)] degC, 'Source/Measure' (one column serves both directions)
    'B': [(600, 800, 0.42, 0.44), (800, 1000, 0.34, 0.34), (1000, 1550, 0.30, 0.30), (1550, 1820, 0.26, 0.33)],
    'C': [(0, 150, 0.23, 0.30), (150, 650, 0.19, 0.26), (650, 1000, 0.23, 0.31), (1000, 1800, 0.38, 0.50), (1800, 2316, 0.63, 0.84)],
    'E': [(-250, -100, 0.38, 0.50), (-100, -25, 0.12, 0.16), (-25, 350, 0.10, 0.14), (350, 650, 0.12, 0.16), (650, 1000, 0.16, 0.21)],
    'J': [(-210, -100, 0.20, 0.27), (-100, -30, 0.12, 0.16), (-30, 150, 0.10, 0.14), (150, 760, 0.13, 0.17), (760, 1200, 0.18, 0.23)],
    'K': [(-200, -100, 0.25, 0.33), (-100, -25, 0.14, 0.18), (-25, 120, 0.12, 0.16), (120, 1000, 0.19, 0.26), (1000, 1372, 0.30, 0.40)],
    'L': [(-200, -100, 0.37, 0.37), (-100, 800, 0.26, 0.26), (800, 900, 0.17, 0.17)],
    'N': [(-200, -100, 0.30, 0.40), (-100, -25, 0.17, 0.22), (-25, 120, 0.15, 0.19), (120, 410, 0.14, 0.18), (410, 1300, 0.21, 0.27)],
    'R': [(0, 250, 0.48, 0.57), (250, 400, 0.28, 0.35), (400, 1000, 0.26, 0.33), (1000, 1767, 0.30, 0.40)],
    'S': [(0, 250, 0.47, 0.47), (250, 1000, 0.30, 0.36), (1000, 1400, 0.28, 0.37), (1400, 1767, 0.34, 0.46)],
    'T': [(-250, -150, 0.48, 0.63), (-150, 0, 0.18, 0.24), (0, 120, 0.12, 0.16), (120, 400, 0.10, 0.14)],
    'U': [(-200, 0, 0.56, 0.56), (0, 600, 0.27, 0.27)],
}
RTD = [   # (function text, [(lo, hi, 90 d, 1 yr)])
    ('RTD, Pt 395, 100 Ohm', [(-200, -80, 0.04, 0.05), (-80, 0, 0.05, 0.05), (0, 100, 0.07, 0.07), (100, 300, 0.08, 0.09), (300, 400, 0.09, 0.10), (400, 630, 0.10, 0.12), (630, 800, 0.21, 0.23)]),
    ('RTD, Pt 3926, 100 Ohm', [(-200, -80, 0.04, 0.05), (-80, 0, 0.05, 0.05), (0, 100, 0.07, 0.07), (100, 300, 0.08, 0.09), (300, 400, 0.09, 0.10), (400, 630, 0.10, 0.12)]),
    ('RTD, Pt 3916, 100 Ohm', [(-200, -190, 0.25, 0.25), (-190, -80, 0.04, 0.04), (-80, 0, 0.05, 0.05), (0, 100, 0.06, 0.06), (100, 260, 0.06, 0.07), (260, 300, 0.07, 0.08),
                               (300, 400, 0.08, 0.09), (400, 600, 0.08, 0.10), (600, 630, 0.21, 0.23)]),
    ('RTD, Pt 385, 200 Ohm', [(-200, -80, 0.03, 0.04), (-80, 0, 0.03, 0.04), (0, 100, 0.04, 0.04), (100, 260, 0.04, 0.05), (260, 300, 0.11, 0.12), (300, 400, 0.12, 0.13),
                              (400, 600, 0.12, 0.14), (600, 630, 0.14, 0.16)]),
    ('RTD, Pt 385, 500 Ohm', [(-200, -80, 0.03, 0.04), (-80, 0, 0.04, 0.05), (0, 100, 0.05, 0.05), (100, 260, 0.06, 0.06), (260, 300, 0.07, 0.08), (300, 400, 0.07, 0.08),
                              (400, 600, 0.08, 0.09), (600, 630, 0.09, 0.11)]),
    ('RTD, Pt 385, 1000 Ohm', [(-200, -80, 0.03, 0.03), (-80, 0, 0.03, 0.03), (0, 100, 0.03, 0.04), (100, 260, 0.04, 0.05), (260, 300, 0.05, 0.06), (300, 400, 0.05, 0.07),
                               (400, 600, 0.06, 0.07), (600, 630, 0.22, 0.23)]),
    ('RTD, PtNi 385, 120 Ohm (Ni120)', [(-80, 0, 0.06, 0.08), (0, 100, 0.07, 0.08), (100, 260, 0.13, 0.14)]),
    ('RTD, Cu 427, 10 Ohm', [(-100, 260, 0.3, 0.3)]),
]
TC_RES, RTD_RES = 0.01, 0.003


def _t(v):
    return f'{v:g} {DEG}'


def temperature():
    out = []
    for tc, bands in TC.items():
        for direction in ('output', 'input'):
            rows = [make_row(f'Temperature [Thermocouple, Type {tc} {direction.title()}]', f'{lo:g} to {hi:g} {DEG}', [f'{_t(lo)} to {_t(hi)}'],
                             [spec_text('90 day', None, floor=a, floor_unit=DEG), spec_text('1 yr', None, floor=b, floor_unit=DEG)], pdf(33), TC_RES)
                    for lo, hi, a, b in bands]
            out.append(fn(f'Temperature [Thermocouple, Type {tc} {direction.title()}]', direction, rows, pdf(33)))
    for name, bands in RTD:
        fname = f'Temperature [{name}]'
        rows = [make_row(fname, f'{lo:g} to {hi:g} {DEG}', [f'{_t(lo)} to {_t(hi)}'],
                         [spec_text('90 day', None, floor=a, floor_unit=DEG), spec_text('1 yr', None, floor=b, floor_unit=DEG)], pdf(34), RTD_RES)
                for lo, hi, a, b in bands]
        out.append(fn(fname, 'output', rows, pdf(34)))
    return out


# ---------------------------------------------------------------------------------------------------------- Frequency (p. 1-23)
FREQ = [('0.01 Hz to 119.99 Hz', 0.01), ('120 Hz to 1199.9 Hz', 0.1), ('1.2 kHz to 11.999 kHz', 1.0), ('12 kHz to 119.99 kHz', 10.0), ('120 kHz to 1199.9 kHz', 100.0),
        ('1.2 MHz to 2 MHz', 1000.0)]


def frequency():
    rows = [make_row('Frequency [Normal Output]', band, [band], [spec_text('1 yr', 2.5, 'ppm', 5, MU + 'Hz')], pdf(39), res) for band, res in FREQ]
    return [fn('Frequency [Normal Output]', 'output', rows, pdf(39))]


# ---------------------------------------------------------------------------------------------------------- notes, limits, problems
NOTES = {
    '1': 'SOURCE: Fluke 5520A Service Manual (supplied PDF 5520A_Manual.pdf), Chapter 1 Specifications, printed pp. 1-6 to 1-25 = PDF pp. 22-41 (printed 1-N = PDF N + 16). Rows carry the PDF page. '
         'Every value was read from rendered page images (130 dpi page, then a 200 dpi crop read a second time), not from extracted text.',
    '2': 'CONFIDENCE LEVEL: "Specification Confidence Interval 99 %" (General Specifications, printed p. 1-7, PDF p. 23). The sheet stores confidence_pct 99, so the coverage divisor is 2.576 '
         '(specmanager.divisor). Harmonised 2026-10-22 (the lab reports at 95 %, k = 2): the 5522A sheet is now also stored at 99 % (its Operators Manual p. 1-8 prints 99 %), the 5560A sheet is stored at its printed 95 % column (divisor 2). '
         'See NOTES.md, "Confidence level rule". To budget the 5520A with divisor 2 instead, set it in Standards Specs (logged).',
    '3': 'CONDITIONS (printed pp. 1-6, 1-7): valid after a 30 minute warm-up (or twice the time off); tcal = ambient temperature at calibration, tcal 15 to 35 degC; the tables hold for tcal +/-5 degC; outside it add 0.1 x '
         '(90 day or 1 year specification) per degC; zero cal every 7 days or when the ambient changes by more than 5 degC; the tightest ohms specification needs an ohms zero cal every 12 hours within +/-1 degC. '
         'The absolute uncertainty includes stability, temperature coefficient, linearity, line and load regulation and the traceability of the standards used for calibration: nothing is to be added for the temperature range indicated. '
         'EMC (p. 1-7): in fields of 1 to 3 V/m resistance outputs have a floor adder of 0.508 ohm (the unit glyph after 0.508 was not legible on the page image; read as ohm); not specified above 3 V/m; TC simulate / measure not specified above 0.4 V/m (pp. 1-8, 1-17).',
    '4': 'PERIODS: 90 day and 1 yr are both stored for every function the manual prints two columns for. Frequency (p. 1-23) prints ONE column, "1-Year Absolute Uncertainty": stored under 1 yr only (there is no 90 day value; none was invented). '
         'The 24 hour stability column (DC voltage, p. 1-8), noise and distortion columns, max burden and the compliance adders are not stored.',
    '5': 'RESOLUTION: taken from the manual\'s own resolution columns (res_src "manual"): DC voltage 0.1 uV .. 1000 uV (p. 1-8), DC current (p. 1-9), resistance 0.0001 .. 10000 ohm (p. 1-11), AC voltage 1 uV .. 10 mV (pp. 1-12, 1-13), '
         'AC current resolution table (p. 1-15, applies to LCOMP off and on), capacitance 0.1 pF .. 10 uF (p. 1-16), thermocouple 0.01 degC (p. 1-17 note [2]), RTD 0.003 degC (p. 1-18 note [1]), frequency 0.01 Hz .. 1 kHz (p. 1-23).',
    '6': 'RESISTANCE FLOOR: the table prints two floors, "12 hrs +/-1 degC" and "7 days +/-5 degC" since the ohms zero cal. Function "Resistance" holds the 12 hour floor (the tightest, the same choice the 5522A sheet makes: 0.001 ohm on the 0 to 11 ohm range). '
         'Function "Resistance [7 Day Zero Cal Floor]" holds the same ppm with the 7 day floor; it is excluded from a plain lookup and used only with variant="7 day". Footnote [2] (p. 1-11): the floors apply to 4-WIRE compensation only; for 2-WIRE and '
         '2-WIRE COMP add 5 uV per amp of stimulus current to the floor (example 0.002 + 5 uV / 1 mA = 0.007 ohm): NOT included here (the stimulus current is not known to the budget), so a 2-wire budget is understated by that term. '
         'Footnote [3]: for currents below the allowable range the floor grows by Imin / Iactual: NOT applied.',
    '7': 'RANGE EDGES: the manual prints DC voltage and DC current ranges as "0 to X". They are stored as non-overlapping bands (the smallest range that holds the value, the rule specmanager.lookup uses for the other sheets): '
         'the printed text is kept in each row\'s "printed" field. DC voltage prints "30 V to 329.9999 V" and "100 V to 1000.000 V"; these overlap the 33 V and 330 V ranges and are stored as 33 V to 329.9999 V and 330 V to 1000 V '
         '(interpretation, NOT verified on the instrument; storing the printed 30 V / 100 V edges instead makes a lookup take the larger of the two overlapping rows). DC voltage 1000 to 1020 V is not covered by a printed row '
         '(the limits table p. 1-20 gives 0 to +/-1020 V; the AC table prints 330 V to 1020 V): a DC point above 1000 V finds no row.',
    '8': 'AUXILIARY output (dual output mode): DC voltage (p. 1-8) and AC voltage sine (p. 1-13) are stored in their own functions ("Auxiliary Output (Dual Output Mode)"), which a plain DCV / ACV lookup excludes. '
         'AUX AC is printed in % of output + uV (the NORMAL table is ppm of output + uV).',
    '9': 'PRINTED ANOMALIES (stored as read, flagged in problems): (a) DC current p. 1-9 first row is printed "0 to 329.999 mA" with resolution "1 nA"; the noise table below it says 329.999 uA, so it is stored as microamps; '
         'the resolution column of that table is printed in mA for rows 2 to 8 ("0.01 mA" ... "100 mA") but the digits of the ranges make them uA (3.29999 mA range: 0.01 uA), stored as uA-based values (10 nA ... 100 uA). '
         '(b) AC current LCOMP off, 3 A to 10.9999 A (p. 1-14) prints the second band "100 kHz to 1 kHz": stored as 100 Hz to 1 kHz (the next band is 1 kHz to 5 kHz, and the 11 A row prints 100 Hz to 1 kHz). '
         '(c) AC current LCOMP on, 3 A to 20.5 A footnote [3] (p. 1-15): "floor 1000 uA within 30 seconds, 5000 uA for operating times > 30 seconds" while the table prints 5000 uA (footnote [2] gives 4000 / 2000 for the lower band): '
         'the table value is stored; the footnote wording looks transposed. (d) Capacitance p. 1-16 prints "0.33 uF to 1.09999mF" for the 0.33 mF range: stored as 0.33 mF to 1.09999 mF. '
         '(e) The Pt 385 100 ohm RTD is NOT in the 5520A RTD table (p. 1-18: Pt 395, Pt 3926, Pt 3916 at 100 ohm; Pt 385 at 200, 500, 1000 ohm; PtNi 385 120 ohm; Cu 427 10 ohm), unlike the 5522A sheet. '
         '(f) The general specifications table (p. 1-7) says "5500A Calibrator" for weight / power / dimensions (a manual-wide wording quirk); the 5520A is the instrument of every table.',
    '10': 'TEMPERATURE: thermocouple types B C E J K L N R S T U, 90 day and 1 yr, in degC; the manual prints one "Source/Measure" column, stored for both directions (functions "... Output" = the calibrator sources, "... Input" = it measures). '
          'Resolution 0.01 degC; standard ITS-90 or IPTS-68 selectable; note [3]: does not include thermocouple error. The manual prints no reference-junction condition beyond tcal +/-5 degC (p. 1-17). '
          'Type K values are identical to the 5522A sheet. RTD (p. 1-18): COMP OFF (NORMAL terminals) and 2-wire / 4-wire compensation, resolution 0.003 degC; Cu 427 is based on MINCO Application Aid No. 18.',
    '11': 'NOT STORED: DC power and AC power (pp. 1-18, 1-19 summaries in % of watts output), power / dual-output limits (summarised in "limits"), phase (p. 1-21), harmonics (p. 1-25), AC voltage and current non-sine and extended '
          'bandwidth (pp. 1-25 .. 1-30, summarised in "limits"), AC voltage DC offset, TC linear 10 uV/degC and 1 mV/degC modes (p. 1-8: 50 ppm + 3 uV 1 yr), and the SC300 / SC600 scope-option specifications (chapters 6 and 7). '
          'The 5522A sheet carries the scope-option rows; this one does not, so scope bandwidth / time base points cannot be costed on it.',
}

# Output limits that decide whether the calibrator can make a point at all (printed page of the manual).  Stored as data (not used by the lookup, which already returns no row outside a band).
LIMITS = [
    dict(function='AC voltage, NORMAL', limit='330 V to 1020 V: 45 Hz to 10 kHz only (45 Hz-1 kHz, 1-5 kHz, 5-10 kHz); 33 V to 329.999 V: 45 Hz to 100 kHz; 3.3 V to 32.9999 V: 10 Hz to 100 kHz; below 3.3 V: 10 Hz to 500 kHz. Maximum specified frequency 500 kHz.', page='1-12'),
    dict(function='AC voltage, extended bandwidth', limit='Typical / wide specification only (5 % of output + 0.5 % of range): 0.01 Hz to 9.99 Hz on all NORMAL ranges to 33 V; 0.3 V to 3.3 V from 500.1 kHz to 1 MHz (-10 dB at 1 MHz, typical) and 1.001 MHz to 2 MHz (-31 dB at 2 MHz, typical); AUX 0.01 Hz to 9.99 Hz.', page='1-25'),
    dict(function='AC voltage, AUX (dual output)', limit='10 mV to 5 V, 10 Hz to 30 kHz; the 3.3 V to 5 V range only to 10 kHz; the maximum frequency of the dual output is 30 kHz.', page='1-13'),
    dict(function='AC current, LCOMP off', limit='29 uA to 329.99 mA: 10 Hz to 30 kHz; 0.33 A to 2.99999 A: 10 Hz to 10 kHz; 3 A to 20.5 A: 45 Hz to 5 kHz (nothing below 45 Hz).', page='1-14'),
    dict(function='AC current, LCOMP on', limit='29 uA to 329.99 mA: 10 Hz to 1 kHz; 0.33 A to 2.99999 A: 10 Hz to 440 Hz; 3 A to 20.5 A: 10 Hz to 1 kHz. Compliance limits 7 / 7 / 5 / 5 / 4 / 3 V rms by range (p. 1-15).', page='1-14, 1-15'),
    dict(function='Currents above 11 A', limit='DC and AC: continuous below 11 A; above 11 A the time allowed is 60 - T - I minutes in any 60 minutes (T = ambient degC, I = amps), Figure 1-4 (p. 1-10); floor is larger within 30 s of selecting operate (DC 1500 uA then 750 uA; AC LCOMP on 4000 / 2000 uA).', page='1-9, 1-10, 1-15'),
    dict(function='DC outputs', limit='Voltage 0 to +/-1020 V; current 0 to +/-20.5 A; AUX voltage 0 to +/-7 V; AC AUX 10 mV to 5 V.', page='1-20'),
    dict(function='Dual output / power', limit='45 Hz to 65 Hz: 33 mV to 1000 V with 3.3 mA to 20.5 A; 65 Hz to 500 Hz: 330 mV to 1000 V (33 mA to 2.99999 A) or 3.3 V to 1000 V (33 mA to 20.5 A); 500 Hz to 1 kHz: 330 mV to 1000 V, 33 mA to 20.5 A; '
                                    '1 kHz to 5 kHz: 3.3 V to 1000 V (limited to 500 V in dual voltage mode), 33 mA to 2.99999 A; 5 kHz to 10 kHz: 3.3 V to 1000 V (250 V in dual voltage mode), 33 mA to 329.99 mA. Phase 0 to +/-179.99 deg, resolution 0.01 deg.', page='1-20'),
    dict(function='Capacitance', limit='0.19 nF to 110 mF continuously variable; maximum peak voltage 3 V; maximum peak current 150 mA, rms 30 mA below 1.1 uF and 100 mA from 1.1 uF; lead resistance 10 ohm maximum in 2-wire COMP; allowed frequency / charge-discharge rate by range (10 Hz to 10 kHz on the smallest ranges down to 0 to 0.2 Hz on 110 mF).', page='1-16'),
    dict(function='Resistance', limit='Continuously variable 0 ohm to 1.1 Gohm; allowable current by range from 1 mA to 125 mA (0 to 33 ohm) down to 1 nA to 13 nA (330 Mohm to 1100 Mohm).', page='1-11'),
    dict(function='Thermocouple', limit='B 600 to 1820, C 0 to 2316, E -250 to 1000, J -210 to 1200, K -200 to 1372, L -200 to 900, N -200 to 1300, R 0 to 1767, S 0 to 1767, T -250 to 400, U -200 to 600 degC; ITS-90 or IPTS-68.', page='1-17'),
    dict(function='RTD', limit='Pt 395 / 3926 100 ohm -200 to 800 / 630 degC; Pt 3916 -200 to 630; Pt 385 200 / 500 / 1000 ohm -200 to 630; PtNi 385 120 ohm -80 to 260; Cu 427 10 ohm -100 to 260 degC.', page='1-18'),
    dict(function='Frequency', limit='0.01 Hz to 2.000 MHz; jitter 100 ns; 2.5 ppm +/-5 uHz (internal reference, 1 year); with REF CLK external: the uncertainty of the external 10 MHz clock +/-5 uHz (1 V to 5 V p-p).', page='1-23'),
]


def problems_for(data):
    probs = list(sm.validate_data(data))

    def w(where, what, level='warn'):
        probs.append(dict(level=level, where=where, what=what))
    w('standard', 'Typed from the 5520A Service Manual specification tables (printed pp. 1-7 to 1-23); no approval signature. Confidence level 99 % is printed (p. 1-7) and stored; divisor 2.576. '
                  'The 5522A sheet states none (divisor 2) and the 5560A sheet is 95 % (divisor 2): the three calibrators are not on one confidence basis (NOTES.md).')
    w('Voltage, DC / 329.9999 V, 1000.000 V', 'The manual prints "30 V to 329.9999 V" and "100 V to 1000.000 V". Stored as 33 V to 329.9999 V and 330 V to 1000 V (the instrument ranges); see note 7. Interpretation, not verified.')
    w('Voltage, DC / 1000.000 V', 'No printed DC voltage row above 1000 V although the output limit is 1020 V (p. 1-20).')
    w('Current, DC / 329.999 uA', 'Printed "0 to 329.999 mA" (p. 1-9) but the noise table and the 1 nA resolution make it 329.999 uA; stored as microamps.')
    w('Current, DC / resolution column', 'The printed resolution column carries the unit "mA" on every row below the first (0.01 mA ... 100 mA); the digits of the range make them uA. Stored as 10 nA ... 100 uA.')
    w('Current, AC [LCOMP off] / 10.9999 A', 'Second band printed "100 kHz to 1 kHz" (p. 1-14); stored as 100 Hz to 1 kHz.')
    w('Current, AC [LCOMP on] / 20.5 A', 'Footnote [3] (p. 1-15) words the floor within / after 30 seconds the other way round to the table; the table value (5000 uA) is stored.')
    w('Capacitance / 1.09999 mF', 'Printed "0.33 uF to 1.09999mF" (p. 1-16); stored as 0.33 mF to 1.09999 mF.')
    w('Temperature [RTD]', 'No Pt 385 100 ohm row in the 5520A table (p. 1-18); the 5522A sheet has one. A lookup for that RTD finds nothing.')
    w('Resistance', 'Floors are the 4-wire values (footnote [2], p. 1-11). 2-wire / 2-wire COMP add 5 uV per amp of stimulus current: not included.')
    w('Frequency', 'The manual prints a 1 year column only; there is no 90 day specification for frequency.')
    w('standard', 'Not stored: stability, noise, burden, compliance adders, power, phase, harmonics, non-sine AC other than the square wave (written by build_square_wave_rows.py), extended bandwidth AC, TC linear modes, SC300 / SC600 (note 11).')
    return probs


def build():
    functions = []
    functions += dc_voltage()
    functions += dc_current()
    functions += resistance()
    functions += ac_voltage()
    functions += ac_current()
    functions += capacitance()
    functions += temperature()
    functions += frequency()
    functions += sq.functions_5520a()           # square-wave amplitude, DC offset, duty cycle (specs/build_square_wave_rows.py)
    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='5520A', description='Multi-Product Calibrator (5520A)',
        confidence_text='99%', confidence_pct=99.0,
        reference='5520A Service Manual, Chapter 1 Specifications, printed pp. 1-6 to 1-25 (PDF pp. 22-41)', revision='', author='typed from the page images by specs/build_5520a_standard.py',
        approved_by='', approve_date='', source_pdf='5520A_Manual.pdf', sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=dict(NOTES, square_wave=sq.NOTE_5520A), limits=LIMITS, functions=functions)
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'fluke_5520a_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"5520A: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {out}")
    for p in data['problems']:
        if p['level'] == 'error':
            print('ERROR', p['where'], '-', p['what'])


if __name__ == '__main__':
    main()
