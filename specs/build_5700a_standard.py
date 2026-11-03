"""Builds specs/standards/fluke_5700a_standard.json from the Fluke 5700A Calibrator Service Manual, Chapter 1 (Specifications).

    python specs/build_5700a_standard.py            # writes specs/standards/fluke_5700a_standard.json (idempotent: same bytes every run)

SOURCE: 'fluke--5700a--service--ID10104.pdf' = 5700A Calibrator Service Manual, PN 791996, February 1990 Rev. 9, 3/96 (632 PDF pages).  This is the
ORIGINAL 5700A (the manual does not mention a "Series II"; the 5700A/5720A Series II have their own, tighter specifications and are NOT covered by this sheet).
Printed page 1-N is PDF page N + 22 (specifications: printed 1-5 .. 1-15 = PDF 27 .. 37).  Rows carry the PDF page in 'page'; notes and 'limits' quote the printed page.

Every number below was transcribed by eye from RENDERED PAGE IMAGES (PyMuPDF, 130 dpi page, the AC voltage table again at 260 dpi), not from the extracted text
(the text layer loses the micro / ohm / plus-minus signs and scrambles the AC voltage table).  The four absolute-uncertainty columns the manual prints are all
transcribed as printed (24 Hours, 90 Days, 180 Days, 1 Year) and stored as the periods '24 hr', '90 day', '180 day' and '1 yr' (the default period of a standard stays '1 yr').
check_order() asserts that no column gets smaller from 24 hours to 1 year, which catches most transcription errors; the printed exceptions are listed in KNOWN_ANOMALIES.
Values are SI base units; ppm / percent of output become 'rel', the floor becomes 'abs'.  The specification text is parsed by specmanager.parse_spec, the same code
path as the 5520A / 5522A / 5560A sheets.  Where the printed table disagrees with itself the printed value is stored and flagged in 'problems'; nothing is corrected.

Stored:   DC voltage (1-5), AC voltage (1-6), DC current (1-11), AC current (1-12), resistance (1-9), wideband AC voltage Option -03 (1-14), the 5725A amplifier rows
          printed inside the AC voltage, DC current and AC current tables (functions with '5725A Amplifier' in the name), frequency (1-8, 1-13).
NOT stored (listed in 'notes' / 'problems' / 'limits'): the Relative Uncertainty columns (they apply only after range-constant calibration and do not include the external
          standards), the secondary performance tables (stability, temperature coefficient, noise, linearity, distortion, load regulation, compliance, burden), the
          resistance current-derating table (p. 1-10), the wideband flatness / harmonic tables (p. 1-14), phase specifications.
"""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402
sys.path.insert(0, str(HERE))
import build_5520a_standard as b5  # noqa: E402     (generic helpers only: make_row, fn)

OUT = HERE / 'standards' / 'fluke_5700a_standard.json'
PDF_OFFSET = 22                      # printed 1-N -> PDF page N + 22
BUILT = '2026-11-03T00:00:00'        # fixed on purpose: the builder must write the same bytes on every run
MU = 'µ'
PERIODS = ('24 hr', '90 day', '180 day', '1 yr')     # the four printed columns, in the printed order


def pdf(printed_n):
    return printed_n + PDF_OFFSET


# ------------------------------------------------------------------------------------------------------------ reading the printed cells
PREFIX = {'n': D('1e-9'), 'µ': D('1e-6'), 'm': D('1e-3'), '': D(1)}
_CELL = re.compile(r'^(?P<rel>\d*\.?\d+)\s*(?P<pct>%)?\s*\+\s*(?P<fl>\d*\.?\d+)\s*(?P<fu>[nµm]?[VA])?$')


def cell(text, default_unit):
    """'500 + 1.7 mV' / '.15% + 110' / '6.5 + .75' -> (rel, 'ppm' | '%', floor, floor unit text).  The unit of a floor is the table header's unless the cell prints one."""
    m = _CELL.match(text.strip().replace('μ', 'µ'))        # Greek mu -> micro sign
    if not m:
        raise ValueError(f'cannot read printed cell {text!r}')
    return D(m['rel']), ('%' if m['pct'] else 'ppm'), D(m['fl']), (m['fu'] or default_unit)


def to_ppm_and_floor(c):
    rel, rel_unit, fl, fu = c
    return (rel * (D(10000) if rel_unit == '%' else 1)), fl * PREFIX[fu[:-1]]


def num(d):
    return format(d.normalize(), 'f') if d == d.to_integral() else format(d, 'f')


KNOWN_ANOMALIES = set()      # (where) strings of printed cells that break the 24 hr <= 90 day <= 180 day <= 1 yr order; each is flagged in problems


def check_order(where, texts, default_unit):
    """Every column is at least the previous one (rel and floor), else the transcription (or the manual) is wrong."""
    cells = [cell(t, default_unit) for t in texts if t]
    vals = [to_ppm_and_floor(c) for c in cells]
    for a, b in zip(vals, vals[1:]):
        if b[0] < a[0] or b[1] < a[1]:
            if where not in KNOWN_ANOMALIES:
                raise AssertionError(f'{where}: columns not in order: {texts}')


def spec_texts(where, texts, default_unit):
    """The four printed cells (24 hr, 90 day, 180 day, 1 yr; None = not usable) -> the sheet's specification texts."""
    check_order(where, texts, default_unit)
    out = []
    for period, t in zip(PERIODS, texts):
        if t is None:
            continue
        rel, rel_unit, fl, fu = cell(t, default_unit)
        out.append(b5.spec_text(period, float(rel), rel_unit, float(fl), fu))
    return out


def _fmt_hz(f):
    if f >= 1e6:
        return f'{f / 1e6:g} MHz'
    if f >= 1e3:
        return f'{f / 1e3:g} kHz'
    return f'{f:g} Hz'


# ------------------------------------------------------------------------------------------------------------ DC voltage (printed p. 1-5)
# (range label, effective band, printed text, resolution V, [24 hr, 90 day, 180 day, 1 yr] in ppm of output + uV)
DCV = [
    ('220 mV', '0 mV to 220 mV', '', 10e-9, ['6.5 + .75', '7 + .75', '8 + .75', '9 + .8']),
    ('2.2 V', '0.22 V to 2.2 V', '', 100e-9, ['3.5 + 1.2', '6 + 1.2', '7 + 1.2', '8 + 1.2']),
    ('11 V', '2.2 V to 11 V', '', 1e-6, ['3.5 + 3', '5 + 4', '7 + 4', '8 + 4']),
    ('22 V', '11 V to 22 V', '', 1e-6, ['3.5 + 6', '5 + 8', '7 + 8', '8 + 8']),
    ('220 V', '22 V to 220 V', '', 10e-6, ['5 + 100', '6 + 100', '8 + 100', '9 + 100']),
    ('1100 V', '220 V to 1100 V', 'minimum output 100 V on the 1100 V range', 100e-6, ['7 + 600', '8 + 600', '10 + 600', '11 + 600']),
]


def dc_voltage():
    rows = [b5.make_row('Voltage, DC', lab, [band], spec_texts(f'DCV {lab}', texts, MU + 'V'), pdf(5), res, printed)
            for lab, band, printed, res, texts in DCV]
    return [b5.fn('Voltage, DC', 'output', rows, pdf(5))]


# ------------------------------------------------------------------------------------------------------------ AC voltage (printed p. 1-6)
ACV_BANDS = [(10, 20), (20, 40), (40, 20e3), (20e3, 50e3), (50e3, 100e3), (100e3, 300e3), (300e3, 500e3), (500e3, 1e6)]
# (range label, effective band, resolution V, default floor unit, [per frequency band: 4 printed cells])
ACV = [
    ('2.2 mV', '0.22 mV to 2.2 mV', 1e-9, MU + 'V', [
        ['500 + 5', '550 + 5', '600 + 5', '600 + 5'], ['200 + 5', '220 + 5', '230 + 5', '240 + 5'], ['100 + 5', '110 + 5', '120 + 5', '120 + 5'],
        ['340 + 5', '370 + 5', '390 + 5', '410 + 5'], ['800 + 8', '900 + 8', '950 + 8', '950 + 8'], ['.11% + 15', '.12% + 15', '.13% + 15', '.13% + 15'],
        ['.15% + 30', '.17% + 30', '.17% + 30', '.18% + 30'], ['.4% + 40', '.44% + 4', '.47% + 40', '.48% + 40']]),
    ('22 mV', '2.2 mV to 22 mV', 10e-9, MU + 'V', [
        ['500 + 6', '550 + 6', '600 + 6', '600 + 6'], ['200 + 6', '220 + 6', '230 + 6', '240 + 6'], ['100 + 6', '110 + 6', '120 + 6', '120 + 6'],
        ['340 + 6', '370 + 6', '390 + 6', '410 + 6'], ['800 + 8', '900 + 8', '950 + 8', '950 + 8'], ['.11% + 15', '.12% + 15', '.13% + 15', '.13% + 15'],
        ['.15% + 30', '.17% + 30', '.17% + 30', '.18% + 30'], ['.4% + 40', '.44% + 4', '.47% + 40', '.48% + 40']]),
    ('220 mV', '22 mV to 220 mV', 100e-9, MU + 'V', [
        ['500 + 16', '550 + 16', '600 + 16', '600 + 16'], ['200 + 10', '220 + 10', '230 + 10', '240 + 10'], ['95 + 10', '100 + 10', '110 + 10', '110 + 10'],
        ['300 + 10', '330 + 10', '350 + 10', '360 + 10'], ['750 + 30', '800 + 30', '850 + 30', '900 + 30'], ['940 + 30', '.1% + 30', '.11% + 30', '.11% + 30'],
        ['.15% + 40', '.17% + 40', '.17% + 40', '.18% + 40'], ['.30% + 100', '.33% + 100', '.35% + 100', '.36% + 100']]),
    ('2.2 V', '0.22 V to 2.2 V', 1e-6, MU + 'V', [
        ['500 + 100', '550 + 100', '600 + 100', '600 + 100'], ['150 + 30', '170 + 30', '170 + 30', '180 + 30'], ['70 + 7', '75 + 7', '80 + 7', '85 + 7'],
        ['120 + 20', '130 + 20', '140 + 20', '140 + 20'], ['230 + 80', '250 + 80', '270 + 80', '280 + 80'], ['400 + 150', '440 + 150', '470 + 150', '480 + 150'],
        ['.10% + 400', '.11% + 400', '.12% + 400', '.12% + 400'], ['.20% + 1 mV', '.22% + 1 mV', '.23% + 1 mV', '.24% + 1 mV']]),
    ('22 V', '2.2 V to 22 V', 10e-6, MU + 'V', [
        ['500 + 1 mV', '550 + 1 mV', '600 + 1 mV', '600 + 1 mV'], ['150 + 300', '170 + 300', '170 + 300', '180 + 300'], ['70 + 70', '75 + 70', '80 + 70', '85 + 70'],
        ['120 + 200', '130 + 200', '140 + 200', '140 + 200'], ['230 + 400', '250 + 400', '270 + 400', '280 + 400'],
        ['500 + 1.7 mV', '550 + 1.7 mV', '550 + 1.7 mV', '600 + 1.7 mV'], ['.12% + 5 mV', '.13% + 5 mV', '.13% + 5 mV', '.14% + 5 mV'],
        ['.26% + 9 mV', '.28% + 9 mV', '.29% + 9 mV', '.30% + 9 mV']]),
    ('220 V', '22 V to 220 V', 100e-6, 'mV', [
        ['500 + 10', '550 + 10', '600 + 10', '600 + 10'], ['150 + 3', '170 + 3', '170 + 3', '180 + 3'], ['75 + 1', '80 + 1', '85 + 1', '90 + 1'],
        ['200 + 4', '220 + 4', '240 + 4', '250 + 4'], ['500 + 10', '550 + 10', '600 + 10', '600 + 10'], ['.15% + 110', '.15% + 110', '.16% + 110', '.16% + 110'],
        ['.50% + 110', '.52% + 110', '.53% + 110', '.54% + 110'], ['1.20% + 220', '1.25% + 220', '1.25% + 220', '1.30% + 220']]),
]
# 1100 V range of the 5700A itself: 50 Hz - 1 kHz only (resolution 11 mV)
ACV_1100 = ('1100 V', '220 V to 1100 V', 11e-3, 'mV', [(50, 1e3, ['75 + 4', '80 + 4', '85 + 4', '90 + 4'])])
# 5725A amplifier rows (printed under "5725A Amplifier:", resolution 1 mV): (range label, band, [(f_lo, f_hi, cells)])
ACV_5725A = [
    ('1100 V', '110 V to 1100 V', 'mV', [(40, 1e3, ['75 + 4', '80 + 4', '85 + 4', '90 + 4']), (1e3, 20e3, ['105 + 6', '125 + 6', '135 + 6', '165 + 6']),
                                         (20e3, 30e3, ['230 + 11', '360 + 11', '440 + 11', '600 + 11'])]),
    ('750 V', '75 V to 750 V', 'mV', [(30e3, 50e3, ['230 + 11', '360 + 11', '440 + 11', '600 + 11']), (50e3, 100e3, ['600 + 45', '.13% + 45', '.16% + 45', '.23% + 45'])]),
]
KNOWN_ANOMALIES |= {f'ACV 2.2 mV @ 500 kHz to 1 MHz', f'ACV 22 mV @ 500 kHz to 1 MHz'}


def _ac_row(fname, kind_tag, lab, band, f_lo, f_hi, texts, default_unit, res, page, printed=''):
    where = f'{kind_tag} {lab} @ {_fmt_hz(f_lo)} to {_fmt_hz(f_hi)}'
    return b5.make_row(fname, f'{lab} @ {_fmt_hz(f_lo)} to {_fmt_hz(f_hi)}', [band, f'{_fmt_hz(f_lo)} to {_fmt_hz(f_hi)}'],
                       spec_texts(where, texts, default_unit), page, res, printed)


def ac_voltage():
    fname = 'Voltage, AC [Sinewave]'
    rows = []
    for lab, band, res, du, per_band in ACV:
        for (f_lo, f_hi), texts in zip(ACV_BANDS, per_band):
            printed = ''
            if lab == '220 V' and f_hi > 100e3:
                printed = 'frequency band printed as such in the 220 V block (see problems)'
            rows.append(_ac_row(fname, 'ACV', lab, band, f_lo, f_hi, texts, du, res, pdf(6), printed))
    lab, band, res, du, bands = ACV_1100
    for f_lo, f_hi, texts in bands:
        rows.append(_ac_row(fname, 'ACV', lab, band, f_lo, f_hi, texts, du, res, pdf(6), 'minimum output 10 % of range; stored from the top of the 220 V range'))
    f5 = 'Voltage, AC [Sinewave, 5725A Amplifier]'
    rows5 = []
    for lab, band, du, bands in ACV_5725A:
        for f_lo, f_hi, texts in bands:
            rows5.append(_ac_row(f5, 'ACV 5725A', lab, band, f_lo, f_hi, texts, du, 1e-3, pdf(6), 'minimum output 10 % of range (p. 1-8)'))
    return [b5.fn(fname, 'output', rows, pdf(6)), b5.fn(f5, 'output', rows5, pdf(6))]


# ------------------------------------------------------------------------------------------------------------ wideband AC voltage, Option -03 (printed p. 1-14)
# (range label, band, resolution V, [24 hr, 90 day, 180 day, 1 yr] in % of output + uV).  Specification applies 30 Hz - 500 kHz at the end of the cable / 50 ohm termination.
WIDEBAND = [
    ('1.1 mV', '0.3 mV to 1.1 mV', 10e-9, ['.4 + .4', '.5 + .4', '.6 + .4', '.8 + 2']),
    ('3 mV', '1.1 mV to 3 mV', 10e-9, ['.4 + 1', '.45 + 1', '.5 + 1', '.7 + 3']),
    ('11 mV', '3 mV to 11 mV', 100e-9, ['.2 + 4', '.35 + 4', '.5 + 4', '.7 + 8']),
    ('33 mV', '11 mV to 33 mV', 100e-9, ['.2 + 10', '.3 + 10', '.45 + 10', '.6 + 16']),
    ('110 mV', '33 mV to 110 mV', 1e-6, ['.2 + 40', '.3 + 40', '.45 + 40', '.6 + 40']),
    ('330 mV', '110 mV to 330 mV', 1e-6, ['0.2 + 100', '.25 + 100', '.35 + 100', '.5 + 100']),
    ('1.1 V', '0.33 V to 1.1 V', 10e-6, ['.2 + 400', '.25 + 400', '.35 + 400', '.5 + 400']),
    ('3.5 V', '1.1 V to 3.5 V', 10e-6, [None, '.2 + 500', '.3 + 500', '.4 + 500']),       # 24 hr is printed "15 + 500" (see problems): not stored
]


def wideband():
    fname = 'Voltage, AC [Wideband, Option 5700A-03]'
    rows = []
    for lab, band, res, texts in WIDEBAND:
        specs = []
        for period, t in zip(PERIODS, texts):
            if t is None:
                continue
            rel, _, fl, fu = cell(t, MU + 'V')
            specs.append(b5.spec_text(period, float(rel), '%', float(fl), fu))       # the wideband table is in % of output + uV
        check_order(f'WB {lab}', texts, MU + 'V')
        rows.append(b5.make_row(fname, f'{lab} @ 30 Hz to 500 kHz', [band, '30 Hz to 500 kHz'], specs, pdf(14), res))
    return [b5.fn(fname, 'output', rows, pdf(14))]


# ------------------------------------------------------------------------------------------------------------ DC current (printed p. 1-11)
# (range label, band, resolution A, default floor unit, cells)
DCI = [
    ('220 µA', '0 µA to 220 µA', 0.1e-9, 'nA', ['45 + 10', '50 + 10', '55 + 10', '60 + 10']),
    ('2.2 mA', '0.22 mA to 2.2 mA', 1e-9, 'nA', ['45 + 10', '50 + 10', '55 + 10', '60 + 10']),
    ('22 mA', '2.2 mA to 22 mA', 10e-9, 'nA', ['45 + 100', '50 + 100', '55 + 100', '60 + 100']),
    ('220 mA', '22 mA to 220 mA', 0.1e-6, MU + 'A', ['55 + 1', '60 + 1', '65 + 1', '70 + 1']),
    ('2.2 A', '0.22 A to 2.2 A', 1e-6, MU + 'A', ['75 + 30', '80 + 30', '90 + 30', '95 + 30']),
]
DCI_5725A = ('11 A', '2.2 A to 11 A', 10e-6, MU + 'A', ['330 + 470', '340 + 480', '350 + 480', '360 + 480'])


def dc_current():
    fname = 'Current, DC'
    rows = [b5.make_row(fname, lab, [band], spec_texts(f'DCI {lab}', texts, du), pdf(11), res) for lab, band, res, du, texts in DCI]
    f5 = 'Current, DC [5725A Amplifier]'
    lab, band, res, du, texts = DCI_5725A
    rows5 = [b5.make_row(f5, lab, [band], spec_texts(f'DCI 5725A {lab}', texts, du), pdf(11), res)]
    return [b5.fn(fname, 'output', rows, pdf(11)), b5.fn(f5, 'output', rows5, pdf(11))]


# ------------------------------------------------------------------------------------------------------------ AC current (printed p. 1-12)
ACI_BANDS = [(10, 20), (20, 40), (40, 1e3), (1e3, 5e3), (5e3, 10e3)]
ACI_2A = [(20, 1e3), (1e3, 5e3), (5e3, 10e3)]
ACI_11A = [(40, 1e3), (1e3, 5e3), (5e3, 10e3)]
# (range label, band, resolution A, default floor unit, bands, cells per band)
ACI = [
    ('220 µA', '9 µA to 220 µA', 1e-9, 'nA', ACI_BANDS, [
        ['650 + 30', '700 + 30', '750 + 30', '800 + 30'], ['350 + 25', '380 + 25', '410 + 25', '420 + 25'], ['120 + 20', '140 + 20', '150 + 20', '160 + 20'],
        ['500 + 50', '600 + 50', '650 + 50', '700 + 50'], ['.15% + 100', '.16% + 100', '.17% + 100', '.18% + 100']]),
    ('2.2 mA', '0.22 mA to 2.2 mA', 10e-9, 'nA', ACI_BANDS, [
        ['650 + 50', '700 + 50', '750 + 50', '800 + 50'], ['350 + 40', '380 + 40', '410 + 40', '420 + 40'], ['120 + 40', '140 + 40', '150 + 40', '160 + 40'],
        ['500 + 500', '600 + 500', '650 + 500', '700 + 500'], ['.15% + 1 µA', '.16% + 1 µA', '.17% + 1 µA', '.18% + 1 µA']]),
    ('22 mA', '2.2 mA to 22 mA', 100e-9, 'nA', ACI_BANDS, [
        ['650 + 500', '700 + 500', '750 + 500', '800 + 500'], ['350 + 400', '380 + 400', '410 + 400', '420 + 400'], ['120 + 400', '140 + 400', '150 + 400', '160 + 400'],
        ['500 + 5 µA', '600 + 5 µA', '650 + 5 µA', '700 + 5 µA'], ['.15% + 10 µA', '.16% + 10 µA', '.17% + 10 µA', '.18% + 10 µA']]),
    ('220 mA', '22 mA to 220 mA', 1e-6, MU + 'A', ACI_BANDS, [
        ['650 + 5', '700 + 5', '750 + 5', '800 + 5'], ['350 + 4', '380 + 4', '410 + 4', '420 + 4'], ['120 + 4', '150 + 4', '170 + 4', '180 + 4'],
        ['500 + 50', '600 + 50', '650 + 50', '700 + 50'], ['.15% + 100', '.16% + 100', '.17% + 100', '.18% + 100']]),
    ('2.2 A', '0.22 A to 2.2 A', 10e-6, MU + 'A', ACI_2A, [
        ['600 + 40', '650 + 40', '700 + 40', '750 + 40'], ['700 + 100', '750 + 100', '800 + 100', '850 + 100'], ['.80% + 200', '.90% + 200', '.95% + 200', '1.0% + 200']]),
]
ACI_5725A = ('11 A', '1 A to 11 A', 100e-6, MU + 'A', ACI_11A, [
    ['370 + 170', '400 + 170', '440 + 170', '460 + 170'], ['800 + 380', '850 + 380', '900 + 380', '950 + 380'], ['.3% + 750', '.33% + 750', '.35% + 750', '.36% + 750']])


def ac_current():
    fname = 'Current, AC [Sinewave]'
    rows = []
    for lab, band, res, du, bands, per_band in ACI:
        for (f_lo, f_hi), texts in zip(bands, per_band):
            rows.append(_ac_row(fname, 'ACI', lab, band, f_lo, f_hi, texts, du, res, pdf(12)))
    f5 = 'Current, AC [Sinewave, 5725A Amplifier]'
    lab, band, res, du, bands, per_band = ACI_5725A
    rows5 = [_ac_row(f5, 'ACI 5725A', lab, band, f_lo, f_hi, texts, du, res, pdf(12)) for (f_lo, f_hi), texts in zip(bands, per_band)]
    return [b5.fn(fname, 'output', rows, pdf(12)), b5.fn(f5, 'output', rows5, pdf(12))]


# ------------------------------------------------------------------------------------------------------------ resistance (printed p. 1-9)
# fixed nominal values only (1 x 10^n and 1.9 x 10^n, short to 100 Mohm): (label, nominal text, ppm [24 hr, 90 day, 180 day, 1 yr]); the short is a floor of 50 uohm in every column
RES = [
    ('1 ohm', '1 ohm', [85, 95, 100, 110]), ('1.9 ohm', '1.9 ohm', [85, 95, 100, 110]), ('10 ohm', '10 ohm', [26, 28, 30, 33]), ('19 ohm', '19 ohm', [24, 26, 28, 31]),
    ('100 ohm', '100 ohm', [15, 17, 18, 20]), ('190 ohm', '190 ohm', [15, 17, 18, 20]), ('1 kohm', '1 kohm', [11, 12, 13, 15]), ('1.9 kohm', '1.9 kohm', [11, 12, 13, 15]),
    ('10 kohm', '10 kohm', [9, 11, 12, 14]), ('19 kohm', '19 kohm', [9, 11, 12, 14]), ('100 kohm', '100 kohm', [11, 13, 14, 16]), ('190 kohm', '190 kohm', [11, 13, 14, 16]),
    ('1 Mohm', '1 Mohm', [16, 18, 20, 23]), ('1.9 Mohm', '1.9 Mohm', [17, 19, 21, 24]), ('10 Mohm', '10 Mohm', [33, 37, 40, 46]), ('19 Mohm', '19 Mohm', [43, 47, 50, 55]),
    ('100 Mohm', '100 Mohm', [110, 120, 125, 130]),
]


def resistance():
    fname = 'Resistance'
    rows = [b5.make_row(fname, '0 ohm (short)', ['0 ohm to 0 ohm'],
                        [f'[{p}] Accuracy: +/-(50 {MU}ohm)' for p in PERIODS], pdf(9), None, 'nominal value 0 (short): 50 µΩ in every column')]
    for lab, nominal, ppm in RES:
        assert ppm == sorted(ppm), lab
        specs = [f'[{p}] Accuracy: +/-({v:g} ppm I.V.)' for p, v in zip(PERIODS, ppm)]
        r = b5.make_row(fname, lab, [f'{nominal} to {nominal}'], specs, pdf(9))
        r['resolution'], r['res_src'] = None, ''         # a nominal value is not a range: analyse_range would read '1.9 kohm' as a range with a last digit
        rows.append(r)
    return [b5.fn(fname, 'output', rows, pdf(9))]


# ------------------------------------------------------------------------------------------------------------ frequency (printed p. 1-8, p. 1-13)
FREQ = [('10 Hz to 11.999 Hz', 0.001), ('12 Hz to 119.99 Hz', 0.01), ('120 Hz to 1199.9 Hz', 0.1), ('1.2 kHz to 11.999 kHz', 1.0), ('12 kHz to 119.99 kHz', 10.0),
        ('120 kHz to 1.1999 MHz', 100.0)]


def frequency():
    rows = [b5.make_row('Frequency [Normal Output]', band, [band], ['[1 yr] Accuracy: +/-(0.01 % I.V.)'], pdf(8), res) for band, res in FREQ]
    return [b5.fn('Frequency [Normal Output]', 'output', rows, pdf(8))]


# ------------------------------------------------------------------------------------------------------------ notes, limits, problems
NOTES = {
    '1': 'SOURCE: Fluke 5700A Calibrator Service Manual PN 791996, February 1990 Rev. 9, 3/96 (supplied PDF fluke--5700a--service--ID10104.pdf, 632 pages), Chapter 1 Specifications, '
         'Table 1-1, printed pp. 1-3 to 1-15 = PDF pp. 25-37 (printed 1-N = PDF N + 22). Rows carry the PDF page. This is the original 5700A; the 5700A / 5720A Series II have their own '
         '(tighter) specifications and are not covered by this sheet. Every value was read from rendered page images, not from extracted text.',
    '2': 'CONFIDENCE LEVEL: the manual prints none (no coverage factor or confidence interval anywhere in Chapter 1). The sheet carries no level, so the coverage divisor is 2 (k = 2 assumed, '
         'the laboratory convention for a sheet that states none). Set the divisor in Standards Specs if the manufacturer\'s level is confirmed from another document.',
    '3': 'CONDITIONS (printed pp. 1-3, 1-15): valid after a 30 minute warm-up, or twice the time the 5700A has been off; "5700A Absolute Uncertainty ... includes stability, temperature coefficient, linearity, '
         'line and load regulation, and the traceability to external standards. You do not need to add anything to absolute uncertainty". The absolute uncertainty columns are +/-5 degC from the '
         'calibration temperature (calibration 15 to 35 degC, operating 0 to 50 degC). The temperature coefficient (secondary table) is an adder only outside +/-5 degC from calibration temperature '
         '(resistance note 2, p. 1-9: or calibrated outside 19 to 24 degC). DC and AC current: for field strengths above 1 V/m but below 3 V/m add 1 % of range (pp. 1-11, 1-12): NOT included in the rows.',
    '4': 'PERIODS: the four absolute uncertainty columns are stored as the periods "24 hr", "90 day", "180 day" and "1 yr" (free-text period labels, the repository convention; the default period of the '
         'standard stays "1 yr"). The Relative Uncertainty columns (24 hours and 90 days, +/-1 degC) apply only after range-constant calibration and exclude the external standards: NOT stored.',
    '5': 'RANGE BANDS: the manual prints one specification per range, with a minimum output (DC: 0 V for every range except 100 V for the 1100 V range, p. 1-5; AC voltage and AC current: 10 % of range, '
         'p. 1-8, p. 1-13, 9 uA for the 220 uA AC current range). The sheet stores non-overlapping bands (the smallest range that holds the value, the rule the other sheets use): '
         'e.g. 2.2 V range = 0.22 V to 2.2 V, 11 V range = 2.2 V to 11 V, 22 V range = 11 V to 22 V, 1100 V range = 220 V to 1100 V. This is an interpretation, NOT verified on the instrument. '
         'The printed minimum is kept in the row\'s "printed" field where it differs.',
    '6': 'RESISTANCE (p. 1-9): the 5700A sources only fixed nominal values (1 x 10^n and 1.9 x 10^n ohm from the short to 100 Mohm). The table is the "Absolute Uncertainty of Characterized Value": the '
         'uncertainty of the value the 5700A displays, not of the nominal. Each nominal is a row whose value band is that single value (lo = hi), so a lookup finds a row only at exactly '
         'a nominal; the short (0 ohm) is a floor of 50 uohm in every column. Note 1 (p. 1-9): "Specifications apply to displayed value. 4-wire connections, except 100 mΩ" (read as printed). '
         'The characterized value may differ from nominal by up to 500 ppm (1 ohm) to 150 ppm (100 ohm to 190 kohm) (secondary table): the displayed value must be used. NOT stored: the current '
         'derating factors (p. 1-10, errors outside the allowed load current range, equations 1 and 2) and the two-wire compensation adder (4 / 15 / 60 / 120 mohm).',
    '7': 'AC VOLTAGE 220 V RANGE (p. 1-6): the 220 V block prints the same eight frequency bands as the lower ranges (10 Hz to 1 MHz) with the last three in % + mV. The volt-hertz capability graph (p. 1-8) '
         'and the 5700A frequency limits for 220 V do not reach 1 MHz. The rows are stored as printed; a lookup only finds them if asked for a point the instrument cannot make.',
    '8': '5725A AMPLIFIER and WIDEBAND OPTION -03: the rows printed under "5725A Amplifier:" (AC voltage 1100 V and 750 V, DC current 11 A, AC current 11 A) are stored in their own functions '
         '("... [5725A Amplifier]"), and the Option 5700A-03 wideband module (p. 1-14, 30 Hz to 500 kHz, % of output + uV, specifications apply at the end of the cable and 50 ohm termination) in '
         '"Voltage, AC [Wideband, Option 5700A-03]". specmanager.DEFAULT_VARIANT excludes "5725a" and "wideband" from a plain lookup, so the base 5700A figures are used unless variant= asks for them. '
         'Amplifier AC voltage bands are 10 % to 100 % of the range (minimum output, p. 1-8), interpretation.',
    '9': 'FREQUENCY: the manual prints one figure, "Uncertainty: +/-0.01 %" (p. 1-8 AC voltage, p. 1-13 AC current, p. 1-14 wideband), with no period. Stored under "1 yr" only (the same choice as the 5520A '
         'sheet); no 24 hr / 90 day / 180 day value was invented. Ranges 10.000-11.999 Hz ... 120.0k-1.1999 MHz, resolution 11 999 counts (so 0.001 Hz up to 100 Hz per range digit); wideband resolution '
         '11 999 counts to 1.1999 MHz, 119 counts to 30 MHz.',
    '10': 'NOT STORED: relative uncertainty columns; secondary performance tables (stability, temperature coefficient, noise, linearity, load regulation, distortion, compliance limits, burden voltage '
          'adder, maximum load / peak current); resistance current derating and two-wire adders; wideband flatness (flatness to a 1 kHz reference: 10 Hz to 30 MHz, +/- 0.1 % to 1.5 % + uV) and '
          'harmonic distortion; phase lock and phase reference specifications; settling times.',
}

LIMITS = [
    dict(function='DC voltage', limit='0 to +/-1100 V; minimum output 0 V on every range except 100 V on the 1100 V range. Maximum load 50 mA (2.2 V to 220 V ranges), 20 mA (1100 V); 50 ohm output impedance on the 220 mV range. Remote sensing available 0 to +/-1100 V on the 2.2 V to 1100 V ranges.', page='1-5'),
    dict(function='AC voltage', limit='10 Hz to 1.2 MHz (5700A, mV ranges to 1 MHz in the table); 1100 V range 50 Hz to 1 kHz on the 5700A alone; 5725A amplifier 1100 V from 40 Hz to 30 kHz and 750 V from 30 kHz to 100 kHz; volt-hertz limit 2.2 x 10^7 V-Hz; minimum output 10 % of range; maximum load 50 mA (2.2 V to 220 V, 0 to 40 degC), 20 mA (40 to 50 degC), 6 mA (1100 V); external sense below 100 kHz (5700A), below 30 kHz (5725A).', page='1-8'),
    dict(function='Wideband AC voltage (Option 5700A-03)', limit='300 uV (-57 dBm) to 3.5 V (+24 dBm), 10 Hz to 30 MHz; absolute uncertainty specified 30 Hz to 500 kHz; dBm reference 50 ohm; frequency uncertainty +/-0.01 %.', page='1-14'),
    dict(function='DC current', limit='0 to 2.2 A from the 5700A terminals (11 A with the 5725A); minimum output 0 on every range; 5700A compliance 2 V for outputs from 1 A to 2.2 A; maximum from the 5700A terminals 2.2 A.', page='1-11'),
    dict(function='AC current', limit='10 Hz to 10 kHz (2.2 A range from 20 Hz; 5725A 11 A range from 40 Hz); maximum 2.2 A from the 5700A (11 A with the 5725A, minimum 1 A); minimum output 9 uA on the 220 uA range, 10 % on the other ranges; power factor 0.9 to 1 (5700A), 0.1 to 1 (5725A); inductive load 400 uH (20 uH above 1 A).', page='1-13'),
    dict(function='Resistance', limit='1 x 10^n and 1.9 x 10^n ohm from the short to 100 Mohm (fixed values, no continuously variable output); load current ranges 8-500 mA (short) down to 50-200 nA (100 Mohm); two-wire compensation for values below 100 kohm, limited to 11 mA and 2 V burden.', page='1-9'),
    dict(function='General', limit='Warm-up twice the time since last warmed up, to a maximum of 30 minutes; operating 0 to 50 degC, calibration 15 to 35 degC, storage -40 to 75 degC; guard isolation 20 V; interfaces IEEE-488, RS-232, 5725A, 5205A / 5215A, 5220A, phase lock in (BNC), phase reference out (BNC); line 47 to 63 Hz, +/-10 % of the selected nominal 100 / 110 / 115 / 120 / 200 / 220 / 230 / 240 V, maximum 300 VA (5700A), 750 VA (5725A).', page='1-15'),
]


def problems_for(data):
    probs = [p for p in sm.validate_data(data)
             if not (p['level'] == 'warn' and p['where'].startswith('Resistance / ') and ('gap between' in p['what']))]      # fixed nominals: gaps between them are by design (note 6)

    def w(where, what, level='warn'):
        probs.append(dict(level=level, where=where, what=what))
    w('standard', 'Typed from the 5700A Service Manual Rev. 9 (3/96) specification tables (printed pp. 1-5 to 1-15); no approval signature. The manual prints NO confidence level: the sheet has none (divisor 2, k = 2 assumed). '
                  'The original 5700A only; the 5700A Series II specifications are different.')
    w('Voltage, AC [Sinewave] / 2.2 mV and 22 mV @ 500 kHz to 1 MHz', 'The 90 day absolute uncertainty is printed ".44% + 4" (p. 1-6); the 24 hour, 180 day and 1 year cells of the same row print "+ 40" and the 24 hour limit is already ".4% + 40". '
        'Stored as printed (4 uV); almost certainly a missing zero.')
    w('Voltage, AC [Sinewave] / 220 V', 'The 220 V block prints the same eight frequency bands as the lower ranges, up to 500 kHz to 1 MHz (p. 1-6); the volt-hertz limit does not allow it. Stored as printed (note 7).')
    w('Voltage, AC [Sinewave] / 220 V @ 100 kHz to 300 kHz', 'The 90 day absolute uncertainty is ".15% + 110" like the 24 hour column; the relative column prints ".15% + 100" (not stored). Stored as printed.')
    w('Voltage, DC / ranges', 'The manual prints "Minimum output: 0 V for all ranges, except 100 V for 1100 V range" (p. 1-5); the sheet stores non-overlapping bands (note 5). Interpretation, not verified on the instrument.')
    w('Voltage, AC [Sinewave] / 1100 V', 'The 5700A 1100 V range prints 50 Hz to 1 kHz only; stored from 220 V (the top of the 220 V range) although its printed minimum output is 10 % of range (110 V).')
    w('Voltage, AC [Wideband, Option 5700A-03] / 3.5 V', 'The 24 hour column prints "15 + 500" (p. 1-14), larger than the 90 day cell ".2 + 500": almost certainly ".15 + 500". The 24 hr period of this row is NOT stored.')
    w('Resistance', 'Fixed nominal values only (note 6): a lookup finds a row only at exactly a nominal. The two-wire compensation adder and the current derating factors (p. 1-10) are NOT included.')
    w('Resistance / nominal 100 Mohm', 'Note 1 of the resistance table is printed "4-wire connections, except 100 mΩ"; it may mean the 100 Mohm nominal (the one value with no 4-wire hook-up). Read as printed, not interpreted; check against the Operator Manual.')
    w('Frequency', 'The manual prints one frequency uncertainty (+/-0.01 %) with no period; stored under "1 yr" (note 9).')
    w('standard', 'Not stored: relative uncertainty columns, secondary performance tables, resistance derating factors, wideband flatness and harmonics, phase specifications (note 10).')
    return probs


def build():
    functions = []
    functions += dc_voltage()
    functions += ac_voltage()
    functions += wideband()
    functions += dc_current()
    functions += ac_current()
    functions += resistance()
    functions += frequency()
    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='5700A', description='Multifunction Calibrator (original 5700A, with Option 5700A-03 and 5725A Amplifier rows)',
        confidence_text='[Not Specified] - not printed in the manual', confidence_pct=None,
        reference='5700A Calibrator Service Manual PN 791996, Feb 1990 Rev. 9 3/96, Chapter 1 Specifications, printed pp. 1-3 to 1-15 (PDF pp. 25-37)', revision='Rev. 9, 3/96',
        author='typed from the page images by specs/build_5700a_standard.py', approved_by='', approve_date='', source_pdf='fluke--5700a--service--ID10104.pdf',
        sheet_generated='', built=BUILT),
        notes=NOTES, limits=LIMITS, functions=functions)
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"5700A: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {OUT}")
    for p in data['problems']:
        print(p['level'].upper(), '|', p['where'], '|', p['what'][:150])


if __name__ == '__main__':
    main()
