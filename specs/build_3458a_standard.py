"""Builds specs/standards/keysight_3458a_standard.json: the accuracy specifications of the Keysight / Agilent 3458A 8.5-digit multimeter, as a standards sheet.

    python specs/build_3458a_standard.py            # writes specs/standards/keysight_3458a_standard.json

SOURCE: '3458A Multimeter - Reliably Accurate Measurement Every Time', Keysight data sheet 5965-4971E (published June 10, 2026), 44 pages, supplied as
'hp3458a_specs.pdf'.  The page numbers below are the data sheet's own printed numbers (they equal the PDF page numbers).  Tables used:
    p. 12  DC voltage accuracy (only 90 day and 1 year are stored; ppm of reading + ppm of range; Option 002 values in parentheses), footnotes 1-6
    p. 13  DC voltage transfer accuracy / linearity (10 min, Tref +/-0.5 degC)
    p. 16  Resistance accuracy (4-wire, OHMF; PRESET; NPLC 100; OCOMP ON), footnotes 1-4
    p. 17  Two-wire ohms: offset errors added to the four-wire accuracy (90 day 150 mOhm, 1 year 250 mOhm; the 24 hour and 2 year offsets are not stored)
    p. 20  DC current accuracy (ppm of reading + ppm of range), footnotes 1-6
    p. 24  AC voltage, synchronous sub-sampled mode (SETACV SYNC), ACBAND <= 2 MHz and > 2 MHz; one column '24-hour to 2 year' (% of reading + % of range)
    p. 27  AC voltage, analog mode (SETACV ANA); one column '24-hour to 2 year'
    p. 29  AC voltage, random sampled mode (SETACV RNDM); one column '24-hour to 2 year'
    p. 32  AC current (ACI); one column '24-hour to 2 year'
    p. 34  Frequency / period accuracy ('24 Hour - 2 Year (0 degC - 55 degC)')
Not stored (notes only): temperature coefficients, additional errors (noise, low-frequency, crest factor, source resistance, resolution multiplier, ACDCV / ACDCI),
settling, noise rejection, reading rates, digitizing, math, the AC transfer accuracy formula (0.002 % + resolution in %) and the traceability adders.

VERIFICATION STATUS: every number was read from RENDERED PAGE IMAGES (pdftoppm at 130 to 300 dpi, viewed as PNG), never from the extracted text, and each stored table
was read twice (the whole page, then a high-resolution crop of the table); the two readings agree.  The independent second transcription is in
tests/test_standard_3458a.py.  Read once only (information in the notes, not used by any lookup): the temperature coefficients of the AC functions, the ACDCV / ACDCI
additional-error tables and the frequency / period characteristics.  One printed cell is NOT readable in the data sheet itself: the 1 GOhm with-ACAL temperature coefficient (printed '1  2'); it is not stored.  Set VERIFIED_AGAINST_IMAGE = False if the data sheet is replaced until the new pages have been read the same way.

CONFIDENCE LEVEL: the data sheet states NONE.  Pages 8 to 35 were read for the words confidence / sigma / k = 2 / 99 % / 95 % / coverage / guaranteed / warranted and
nothing of the kind is printed; the text only says the accuracy is 'relative to the calibration standards' (p. 8).  The sheet is stored with confidence_pct
None ('[Not Specified]'), so the repository's rule for a sheet without a level applies (divisor 2 assumed, as for the 8563E, 8902A and 96270A sheets).  This is a
FLAG, not a finding: nothing in the data sheet supports 95 % or 99 %.  The owner decides the divisor (Standards Specs lets a divisor be set per standard).

How the repository form holds a DMM specification (no schema change):
  * 'ppm of reading' / '% of reading' -> spec['rel']  ('8 ppm I.V.' = 8e-06, built with Decimal so the stored float is the nearest to the printed figure).
  * 'ppm of range' / '% of range' -> spec['fs_rel'] x spec['fs_value']; fs_value is the NAME of the range (0.1 V for the 100 mV range, 10 V for the 10 V range), because the
    data sheet says (p. 8) 'Range means the name of the scale, e.g. 1 V, 10 V; range does not mean the full-scale reading, e.g. 1.2 V, 12 V'.  Printed text form
    '0.3 ppm of range{"Range" = 1 V}' (new, additive: specmanager.parse_spec and the Standards Specs view accept it; the old '% F.S.{"Full Scale" = ..}' form is unchanged).
  * a fixed term (two-wire ohms offset) -> spec['abs'] (ohm).
  * periods are free text: '90 day', '1 yr' (owner: no 24 hour, no 2 year) and '10 min' for the DC transfer accuracy.  The default period of a standard is '1 yr'.  The AC and
    frequency tables print ONE column '24-hour to 2 year', so the same specification is stored under both periods.
  * each range is a bipolar row (amp_lo = -full scale, amp_hi = +full scale), so specmanager picks the SMALLEST range that holds the value, as the instrument does
    (a 200 uA current is on the 1 mA range, whose full scale is 1.2 mA).  AC rows carry the frequency band (freq_lo, freq_hi); an unprinted (blank) band has no row.
  * direction 'input': the 3458A MEASURES (same as the 5790B, 8563E and 8902A sheets).  specmanager.lookup defaults to direction 'output', so callers pass
    direction='input' (tartur.standard_accuracy has the argument; the Datasheet Builder matcher uses the row direction itself).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

VERIFIED_AGAINST_IMAGE = True            # all stored tables read from rendered page images, twice (see the docstring); False re-adds the warnings
SOURCE_PDF = 'hp3458a_specs.pdf'
MODEL = '3458A'
PERIODS = ['90 day', '1 yr']       # owner: the lab uses 1 yr (default) and 90 day only; the 24 hour and 2 year columns are not stored
CONFIDENCE_TEXT = ('[Not Specified] - the Keysight 3458A data sheet (5965-4971E, pp. 8-35) prints no confidence level and no coverage factor; '
                   'it states only that the accuracy is relative to the calibration standards (p. 8)')

M, U, N, P, K = D('1e-3'), D('1e-6'), D('1e-9'), D('1e-12'), D('1e3')           # SI factors (Decimal)


def num(x):
    """Decimal -> shortest plain text ('0.12', '1050', '0.00005')."""
    x = D(x).normalize()
    t = format(x, 'f')
    return t


# ------------------------------------------------------------------------------------------------------------ the tables as printed
# DC voltage, p. 12.  range name (V) / full scale (V) / maximum resolution (V) / accuracy per period 'ppm of reading + ppm of range' (Option 002 reading in parentheses)
DCV_RANGES = [('100 mV', '0.1', '0.12', '1e-8'), ('1 V', '1', '1.2', '1e-8'), ('10 V', '10', '12', '1e-7'), ('100 V', '100', '120', '1e-6'), ('1000 V', '1000', '1050', '1e-5')]
DCV = {            # period -> per range 'reading (option 002 reading) + range'
    '90 day': ['5.0 (3.5) + 3', '4.6 (3.1) + 0.3', '4.1 (2.6) + 0.05', '6.0 (4.5) + 0.3', '6.0 (4.5) + 0.1'],
    '1 yr': ['9 (5) + 3', '8 (4) + 0.3', '8 (4) + 0.05', '10 (6) + 0.3', '10 (6) + 0.1'],
}
# DC voltage transfer accuracy / linearity, p. 13: 10 min, Tref +/-0.5 degC, ppm of reading + ppm of range
DCV_TRANSFER = ['0.5 + 0.5', '0.3 + 0.1', '0.05 + 0.05', '0.5 + 0.1', '1.5 + 0.05']

# Resistance, pp. 16-17.  range name (ohm) / full scale / maximum resolution; accuracy 'reading + range' ('%' = percent of reading, otherwise ppm)
OHM_RANGES = [('10 ohm', '10', '12', '1e-5'), ('100 ohm', '100', '120', '1e-5'), ('1 kohm', '1000', '1200', '1e-4'), ('10 kohm', '10000', '12000', '1e-3'),
              ('100 kohm', '100000', '120000', '1e-2'), ('1 Mohm', '1000000', '1200000', '1e-1'), ('10 Mohm', '10000000', '12000000', '1'),
              ('100 Mohm', '100000000', '120000000', '10'), ('1 Gohm', '1000000000', '1200000000', '100')]
OHM = {
    '90 day': ['15 + 5', '10 + 5', '8 + 0.5', '8 + 0.5', '8 + 0.5', '12 + 2', '50 + 10', '500 + 10', '0.5% + 10'],
    '1 yr': ['15 + 5', '12 + 5', '10 + 0.5', '10 + 0.5', '10 + 0.5', '15 + 2', '50 + 10', '500 + 10', '0.5% + 10'],
}
OHM2_OFFSET = {'90 day': '0.15', '1 yr': '0.25'}      # ohm: 150 mOhm / 250 mOhm (p. 17; the printed 24 hour and 2 year offsets are not stored)

# DC current, p. 20.  range name (A) / full scale / maximum resolution
DCI_RANGES = [('100 nA', '1e-7', '1.2e-7', '1e-12'), ('1 uA', '1e-6', '1.2e-6', '1e-12'), ('10 uA', '1e-5', '1.2e-5', '1e-12'), ('100 uA', '1e-4', '1.2e-4', '1e-11'),
              ('1 mA', '1e-3', '1.2e-3', '1e-10'), ('10 mA', '1e-2', '1.2e-2', '1e-9'), ('100 mA', '1e-1', '1.2e-1', '1e-8'), ('1 A', '1', '1.05', '1e-7')]
DCI = {
    '90 day': ['30 + 400', '15 + 40', '15 + 10', '15 + 8', '15 + 5', '15 + 5', '30 + 5', '100 + 10'],
    '1 yr': ['30 + 400', '20 + 40', '20 + 10', '20 + 8', '20 + 5', '20 + 5', '35 + 5', '110 + 10'],
}
DCI_TYPICAL = (0, 1, 2)         # 100 nA, 1 uA, 10 uA: footnote 6 'Typical accuracy'

# AC voltage: range names and full scales (V); maximum resolution (V) per mode.  Accuracy '% of reading + % of range', one column '24-hour to 2 year'.
ACV_RANGES = [('10 mV', '0.01', '0.012'), ('100 mV', '0.1', '0.12'), ('1 V', '1', '1.2'), ('10 V', '10', '12'), ('100 V', '100', '120'), ('1000 V', '1000', '700')]
ACV_GROUP = {'10 mV': '10 mV', '100 mV': '100 mV - 10 V', '1 V': '100 mV - 10 V', '10 V': '100 mV - 10 V', '100 V': '100 V', '1000 V': '1000 V'}
ACV_RES = {'SYNC': ['1e-8', '1e-8', '1e-7', '1e-6', '1e-5', '1e-4'], 'ANA': ['1e-8', '1e-7', '1e-6', '1e-5', '1e-4', '1e-3'], 'RNDM': ['1e-6', '1e-5', '1e-4', '1e-3', '1e-2', '1e-1']}
HZ = D(1)
KHZ, MHZ = D(1000), D(1000000)
# (title, mode, printed page, [bands in Hz (lo, hi)], {printed range group: [accuracy per band, '' = blank cell]})
ACV_TABLES = [
    ('SETACV SYNC, ACBAND <= 2 MHz', 'SYNC', 24, [(1, 40), (40, 1e3), (1e3, 20e3), (20e3, 50e3), (50e3, 100e3), (100e3, 300e3), (300e3, 1e6), (1e6, 2e6)], {
        '10 mV': ['0.03 + 0.03', '0.02 + 0.011', '0.03 + 0.011', '0.1 + 0.011', '0.5 + 0.011', '4.0 + 0.02', '', ''],
        '100 mV - 10 V': ['0.007 + 0.004', '0.007 + 0.002', '0.014 + 0.002', '0.03 + 0.002', '0.08 + 0.002', '0.3 + 0.01', '1 + 0.01', '1.5 + 0.01'],
        '100 V': ['0.02 + 0.004', '0.02 + 0.002', '0.02 + 0.002', '0.035 + 0.002', '0.12 + 0.002', '0.4 + 0.01', '1.5 + 0.01', ''],
        '1000 V': ['0.04 + 0.004', '0.04 + 0.002', '0.06 + 0.002', '0.12 + 0.002', '0.3 + 0.002', '', '', '']}),
    ('SETACV SYNC, ACBAND > 2 MHz', 'SYNC', 24, [(45, 100e3), (100e3, 1e6), (1e6, 4e6), (4e6, 8e6), (8e6, 10e6)], {
        '10 mV': ['0.09 + 0.06', '1.2 + 0.05', '7 + 0.07', '20 + 0.08', ''],
        '100 mV - 10 V': ['0.09 + 0.06', '2.0 + 0.05', '4 + 0.07', '4 + 0.08', '15 + 0.1'],
        '100 V': ['0.12 + 0.002', '', '', '', ''],
        '1000 V': ['0.3 + 0.01', '', '', '', '']}),
    ('SETACV ANA', 'ANA', 27, [(10, 20), (20, 40), (40, 100), (100, 20e3), (20e3, 50e3), (50e3, 100e3), (100e3, 250e3), (250e3, 500e3), (500e3, 1e6), (1e6, 2e6)], {
        '10 mV': ['0.4 + 0.32', '0.15 + 0.25', '0.06 + 0.25', '0.02 + 0.25', '0.15 + 0.25', '0.7 + 0.35', '4 + 0.7', '', '', ''],
        '100 mV - 10 V': ['0.4 + 0.02', '0.15 + 0.02', '0.06 + 0.01', '0.02 + 0.01', '0.15 + 0.04', '0.6 + 0.08', '2 + 0.5', '3 + 0.6', '5 + 2', '10 + 5'],
        '100 V': ['0.4 + 0.02', '0.15 + 0.02', '0.06 + 0.01', '0.03 + 0.01', '0.15 + 0.04', '0.6 + 0.08', '2 + 0.5', '3 + 0.6', '5 + 2', ''],
        '1000 V': ['0.42 + 0.03', '0.17 + 0.03', '0.08 + 0.02', '0.06 + 0.02', '0.15 + 0.04', '0.6 + 0.2', '', '', '', '']}),
    ('SETACV RNDM, ACBAND <= 2 MHz', 'RNDM', 29, [(20, 100e3), (100e3, 300e3), (300e3, 1e6), (1e6, 2e6)], {
        '10 mV': ['0.5 + 0.02', '4 + 0.02', '', ''],
        '100 mV - 10 V': ['0.08 + 0.002', '0.3 + 0.01', '1 + 0.01', '1.5 + 0.01'],
        '100 V': ['0.12 + 0.002', '0.4 + 0.01', '1.5 + 0.01', ''],
        '1000 V': ['0.3 + 0.01', '', '', '']}),
    ('SETACV RNDM, ACBAND > 2 MHz', 'RNDM', 29, [(20, 100e3), (100e3, 1e6), (1e6, 4e6), (4e6, 8e6), (8e6, 10e6)], {
        '10 mV': ['0.1 + 0.05', '1.2 + 0.05', '7 + 0.07', '20 + 0.08', ''],
        '100 mV - 10 V': ['0.1 + 0.05', '2 + 0.05', '4 + 0.07', '4 + 0.08', '15 + 0.1'],
        '100 V': ['0.12 + 0.002', '', '', '', ''],
        '1000 V': ['0.3 + 0.01', '', '', '', '']}),
]

# AC current, p. 32.  range name (A) / full scale / maximum resolution; bands 10-20, 20-45, 45-100 Hz, 100 Hz-5 kHz, 5-20, 20-50, 50-100 kHz (the last three typical, footnote 3)
ACI_RANGES = [('100 uA', '1e-4', '1.2e-4', '1e-10'), ('1 mA', '1e-3', '1.2e-3', '1e-9'), ('10 mA', '1e-2', '1.2e-2', '1e-8'), ('100 mA', '1e-1', '1.2e-1', '1e-7'), ('1 A', '1', '1.05', '1e-6')]
ACI_GROUP = {'100 uA': '100 uA', '1 mA': '1 mA - 100 mA', '10 mA': '1 mA - 100 mA', '100 mA': '1 mA - 100 mA', '1 A': '1 A'}
ACI_BANDS = [(10, 20), (20, 45), (45, 100), (100, 5e3), (5e3, 20e3), (20e3, 50e3), (50e3, 100e3)]
ACI_TYPICAL_BANDS = (4, 5, 6)
ACI = {'100 uA': ['0.4 + 0.03', '0.15 + 0.03', '0.06 + 0.03', '0.06 + 0.03', '', '', ''],
       '1 mA - 100 mA': ['0.4 + 0.02', '0.15 + 0.02', '0.06 + 0.02', '0.03 + 0.02', '0.06 + 0.02', '0.4 + 0.04', '0.55 + 0.15'],
       '1 A': ['0.4 + 0.02', '0.16 + 0.02', '0.08 + 0.02', '0.1 + 0.02', '0.3 + 0.02', '1 + 0.04', '']}

# Frequency / period, p. 34: '24 Hour - 2 Year (0 degC - 55 degC)', % of reading
FREQ = [('1 Hz to 40 Hz (period 1 s to 25 ms)', 1, 40, '0.05'), ('40 Hz to 100 MHz (period 25 ms to 100 ns)', 40, 1e8, '0.01')]


# ------------------------------------------------------------------------------------------------------------ helpers
def hz_text(v):
    v = D(repr(float(v)))
    for f, sym in ((D(10) ** 6, 'MHz'), (D(10) ** 3, 'kHz'), (D(1), 'Hz')):
        if v >= f:
            return f'{num(v / f)} {sym}'
    return f'{num(v)} Hz'


def si_range_text(x, base):
    """'0.0001' + 'A' -> '100 uA' (ASCII, for labels)."""
    x = D(x)
    for f, pre in ((D(1), ''), (M, 'm'), (U, 'u'), (N, 'n'), (P, 'p')):
        if x >= f or pre == 'p':
            return f'{num(x / f)} {pre}{base}'
    return f'{num(x)} {base}'


def split_terms(text, pct_reading=False):
    """'8 (4) + 0.3' -> ('8', '4' or None, '0.3');  '0.5% + 10' -> ('0.5%', None, '10')."""
    left, right = [t.strip() for t in text.split(' + ')]
    opt = None
    if '(' in left:
        left, opt = left.split('(')
        left, opt = left.strip(), opt.strip(' )')
    return left, opt, right


def make_spec(period, reading, range_term, range_text, range_si, range_pct=False, abs_term=None, abs_unit=''):
    """One specification dict: reading '8' (ppm) or '0.5%', range_term '0.3' (ppm, or percent when range_pct) against the range NAME range_text ('1 V', ASCII
    units) = range_si (Decimal, SI); Decimal arithmetic for every stored figure.  reading / range_term None = no such term."""
    terms, rel, fs_rel = [], D(0), D(0)
    if reading is not None:
        if reading.endswith('%'):
            terms.append(f'{reading[:-1]} % I.V.')
            rel = D(reading[:-1]) / 100
        else:
            terms.append(f'{reading} ppm I.V.')
            rel = D(reading) / 1000000
    fs_value = D(0)
    if range_term is not None:
        unit_txt = 'ppm' if not range_pct else '%'
        terms.append(f'{range_term} {unit_txt} of range{{"Range" = {range_text}}}')
        fs_rel = D(range_term) / (100 if range_pct else 1000000)
        fs_value = D(range_si)                                          # Decimal, SI
    ab = D(0)
    if abs_term is not None:
        terms.append(f'{abs_term} {abs_unit}')
        ab = D(abs_term)
    raw = f'[{period}] Accuracy: +/-(' + ' + '.join(terms) + ')'
    spec = dict(period=period, rel=float(rel), fs_rel=float(fs_rel), fs_value=float(fs_value), abs=float(ab), unit=abs_unit or '', le=False, raw=raw)
    chk = sm.parse_spec(raw)                                            # the repository's own parser must read the same numbers back
    if chk.get('error'):
        raise ValueError(f'{raw}: {chk["error"]}')
    for k in ('rel', 'fs_rel', 'fs_value', 'abs'):
        if not math.isclose(chk[k], spec[k], rel_tol=1e-12, abs_tol=1e-30):
            raise ValueError(f'{raw}: {k} {chk[k]!r} != {spec[k]!r}')
    return spec


def amp_param(fs, unit, text, notes=()):
    return dict(tag='', lo=-float(D(fs)), hi=float(D(fs)), unit=unit, text=text, annot='', notes=list(notes))


def freq_param(lo, hi):
    return dict(tag='', lo=float(D(repr(float(lo)))), hi=float(D(repr(float(hi)))), unit='Hz', text=f'{hz_text(lo)} to {hz_text(hi)}', annot='', notes=[])


def make_range(name, label, printed, kind_expected, params, specs, page, resolution=None, freq=None, unit='V'):
    kind, variant = sm.classify(name)
    if kind != kind_expected:
        raise ValueError(f'{name}: classify gives {kind}, expected {kind_expected}')
    amp = params[0]
    return dict(label=label, page=page, params=params, specs=specs, raw_other=[], printed=printed, kind=kind, variant=variant,
                amp_lo=amp['lo'], amp_hi=amp['hi'], unit=amp['unit'], freq_lo=freq[0] if freq else None, freq_hi=freq[1] if freq else None,
                qualifiers=[], range_max=None, resolution=float(D(resolution)) if resolution else None, res_src='manual' if resolution else '')


# ------------------------------------------------------------------------------------------------------------ notes
NOTES = {
    '1': 'SOURCE: Keysight 3458A Multimeter data sheet 5965-4971E (published June 10, 2026), supplied as hp3458a_specs.pdf; printed page numbers equal the PDF page numbers: '
         'DC volts p. 12 (transfer accuracy p. 13), resistance pp. 16-17, DC current p. 20, AC volts pp. 24 (SYNC), 27 (ANA), 29 (RNDM), AC current p. 32, frequency / period p. 34. '
         'Built by specs/build_3458a_standard.py.',
    '2': 'VERIFICATION: every stored number was read from RENDERED PAGE IMAGES (never the extracted text), each table twice (whole page, then a 300 dpi crop of the table); '
         'the two readings agree. Notes that only quote the temperature coefficients of the AC functions, the ACDCV / ACDCI additional errors and the frequency / period '
         'characteristics were read once (information; no lookup uses them). The 1 GOhm resistance temperature coefficient WITH ACAL (printed "1   2") could not be read '
         'in the data sheet itself and is NOT stored.',
    '3': 'CONFIDENCE LEVEL: NOT STATED. The data sheet (pp. 8-35) prints no confidence level, sigma, coverage factor k, or "99 %" / "95 %"; p. 8 says only that the accuracy is '
         'relative to the calibration standards. Stored as confidence_pct None ("[Not Specified]"), so the repository rule for such a sheet applies: coverage divisor 2.0 ASSUMED '
         '(the same treatment as the 8563E, 8902A and 96270A sheets). Set the divisor in Standards Specs if the lab decides otherwise (a Keysight spec limit is often treated as a '
         'rectangular limit, divisor sqrt(3), but this sheet does not say so).',
    '4': 'RELATIVE vs ABSOLUTE (p. 8): all accuracy specifications are RELATIVE to the calibration standards. The absolute accuracy adds the traceability error of the standards '
         'used for the last external calibration; the data sheet gives the factory figure and it is NOT added to any stored row: DC volts +2 ppm of reading (p. 12 footnote 5), '
         'resistance +3 ppm of reading, traceability of 10 kOhm (p. 16 footnote 3), DC current +5 ppm of reading, the sum of the 10 V and 10 kOhm values (p. 20 footnote 5), '
         'AC volts +2 ppm of reading, traceability of 10 V DC (pp. 24, 27), AC current +5 ppm of reading (p. 32 footnote 2). When the lab calibrates its own 3458A the '
         'traceability of THAT calibration replaces these factory figures. OPEN ITEM: the owner is unsure whether the factory adders should be added; they stay NOT stored until decided.',
    '5': 'RANGE (p. 8): "Range means the name of the scale, e.g., 1 V, 10 V, etc.; range does not mean the full-scale reading, e.g., 1.2 V, 12 V". The ppm / % of range term is '
         'therefore taken against the range NAME (0.1 V on the 100 mV range, 1 V, 10 V, 100 V, 1000 V; 1 uA on the 1 uA range ...), stored as fs_value; the row spans -full scale '
         'to +full scale (full scale as printed: 120 mV, 1.2 V, 12 V, 120 V, 1050 V; resistance 12 ohm ... 1.2 Gohm; DC current 120 nA ... 1.05 A; AC volts 12 mV ... 120 V and 700 V on the 1000 V range; AC current 120 uA ... 1.05 A).',
    '6': 'PERIODS (owner: the lab uses 1 year specifications): only "90 day" and "1 yr" are stored (the printed 24 hour and 2 year columns are NOT stored); the default period of the standard is "1 yr". '
         'Conditions: 90 day / 1 year = within 24 hours and +/-1 degC of the last ACAL, Tcal +/-5 degC, MATH NULL, fixed range (p. 12 footnote 5; p. 16 footnote 3; p. 20 footnote 5). '
         'Specifications are for PRESET; NPLC 100 (resistance: PRESET; NPLC 100; OCOMP ON; OHMF). AC volts, AC current and frequency print ONE column "24-hour to 2 year" '
         '(pp. 24, 27, 29, 32, 34): the same specification is stored under both periods.',
    '7': 'OPTION 002 (high stability, p. 12 footnote 5): the DC volts "ppm of reading" figures in parentheses are for Option 002 (only the DC volts table has parenthesised figures). '
         'PER THE OWNER the lab\'s 3458A HAS Option 002, so "Voltage, DC [Option 002 high stability]" is the DEFAULT of a plain DC volts lookup (specmanager.DEFAULT_VARIANT prefer "option 002"). '
         'The standard-stability figures (8 ppm / year) are stored as the alternate function "Voltage, DC [Standard stability]", selectable with variant="Standard stability". '
         'Ordering page: "8 ppm Stability" standard, "3458A-002 High stability (4 ppm/year) reference" option.',
    '8': 'DC VOLTS EXTRA TERMS, NOT STORED (p. 12): without MATH NULL add 0.15 ppm of range to 10 V, 0.7 ppm of range to 1 V and 7 ppm of range to 0.1 V; without MATH NULL and for a fixed range of '
         'less than 4 minutes add 0.25 ppm of range to 10 V, 1.7 ppm of range to 1 V and 17 ppm of range to 0.1 V. Footnote 6 (1000 V range): "Add 12 ppm X (Vin / 1000)2 additional errors for '
         'inputs > 100 vV" (printed so; read as 12 ppm x (Vin/1000)^2 of reading for inputs above 100 V: 12 ppm at 1000 V). Footnote 6 is NOT in any stored 1000 V row.',
    '9': 'DC VOLTS TRANSFER ACCURACY / LINEARITY (p. 13), stored under the period "10 min": 10 min, Tref +/-0.5 degC, ppm of reading + ppm of range: 100 mV 0.5 + 0.5, 1 V 0.3 + 0.1, 10 V 0.05 + 0.05, '
         '100 V 0.5 + 0.1, 1000 V 1.5 + 0.05. Conditions (p. 13): following a 4-hour warm-up, full scale to 10 % of full scale; 1000 V range measurements within 5 % of the initial value and after settling; '
         'Tref is the starting ambient temperature; fixed range (> 4 min) using accepted metrology practices. A plain lookup (period "1 yr") never returns these rows; pass period="10 min".',
    '10': 'TWO-WIRE OHMS (p. 17): "add the following offset errors to the four-wire ohms (OHMF) accuracy: 24 Hour: 50 mOhm. 90 Day: 150 mOhm. 1 Year: 250 mOhm. 2 Year: 500 mOhm". Stored as a fixed term '
          '(0.05 / 0.15 / 0.25 / 0.5 ohm) added to the four-wire row, function "Resistance [2-wire (OHM)]". A plain resistance lookup prefers the 4-wire function (repository rule); pass variant="2-wire". '
          '100 MOhm and 1 GOhm: the measurement is computed from 10 MOhm in parallel with the input (p. 16 footnote 4). OCOMP is stated ON for the accuracy table (p. 16 footnote 1); the data sheet lists the '
          'offset-compensated ohms for 10 Ohm to 100 kOhm only (p. 5), so the 1 MOhm to 1 GOhm rows cannot have OCOMP on (not explained in the data sheet).',
    '11': 'DC CURRENT TYPICAL (p. 20 footnote 6 "Typical accuracy"): the 100 nA, 1 uA and 10 uA rows are TYPICAL, not warranted; the labels say so. Factory traceability +5 ppm of reading is not in the rows (note 4). '
          'The range ends at 1.05 A (full scale): a current above 1.05 A (for example 2 A) has NO row and a lookup returns None; the maximum input is 1.5 A pk (p. 22).',
    '12': 'AC VOLTS: three techniques, one function each (p. 23): SETACV SYNC (synchronously sub-sampled, 1 Hz to 10 MHz, repetitive signal required), SETACV ANA (analog, 10 Hz to 2 MHz, power-up default), '
          'SETACV RNDM (random sampled, 20 Hz to 10 MHz). SYNC is split by ACBAND (<= 2 MHz and > 2 MHz, p. 24), RNDM likewise (p. 29); ANA has one table (p. 27). Accuracy is % of reading + % of range, '
          '24 hour to 2 year. Conditions: SYNC and RNDM full scale to 10 % (SYNC) of full scale, ANA full scale to 1/20 full scale, DC < 10 % of the AC sine wave input, crest factor 1.4, PRESET, within '
          '24 hours and +/-1 degC of the last ACAL, Lo to guard switch on, peak (AC + DC) input limited to 5 x full scale (SYNC); ANA: maximum DC 400 V. LFILTER ON recommended below 20 kHz (SYNC). '
          'A blank cell in the printed table means no specification: no row is stored (for example 10 mV at 300 kHz to 2 MHz, 1000 V above 100 kHz). The plain lookup returns the LARGEST limit of the modes '
          'that cover the point; pass variant="SYNC", "ANA" or "RNDM" (and "<= 2 MHz" / "> 2 MHz") for one mode. The RNDM table carries the footnote number 1 on its title, but its only footnote is the '
          'temperature-coefficient one: its own conditions are not printed (p. 29); the SYNC / ANA conditions are assumed to apply and that is UNVERIFIED.',
    '13': 'AC VOLTS TEMPERATURE COEFFICIENTS (% of reading + % of range per degC beyond +/-1 degC of the last ACAL but within +/-5 degC; information only): SYNC (p. 24) 10 mV 0.002 + 0.02, 100 mV - 1000 V 0.001 + 0.0001; '
          'ANA (p. 27) 10 mV 0.003 + 0.006 (specification applies full scale to 1/4 full scale), others 0.002 + 0.0; RNDM (p. 29) 10 mV 0.002 + 0.02, others 0.001 + 0.00001; '
          'for ACBAND > 2 MHz use the 10 mV figure for all ranges. High-frequency temperature coefficient (outside Tcal +/-5 degC, % of reading per degC, pp. 26, 31): 2-4 MHz 0.02 (10 mV - 1 V) / 0.08 (10 V - 1000 V); '
          '4-10 MHz 0.08. AC current (p. 32): 0.002 + 0 for every range.',
    '14': 'AC CURRENT (p. 32): ACI and ACDCI, 24 hour to 2 year, % of reading + % of range, full scale to 1/20 full scale, sine wave, crest factor 1.4, PRESET, within 24 hours and +/-1 degC of the last ACAL. '
          'The 5 kHz to 20 kHz, 20 kHz to 50 kHz and 50 kHz to 100 kHz columns are TYPICAL (footnote 3; labels say so). The 100 uA range is limited to 1 kHz (footnote 4): the 100 Hz - 5 kHz cell is stored with '
          'its upper band edge at 1 kHz and its printed band in the label. Factory traceability +5 ppm of reading is not in the rows (note 4). The 1 A range is full scale 1.05 A.',
    '15': 'ADDITIONAL ERRORS, NOT STORED: noise (RMS noise multipliers and the NPLC curves, pp. 13, 14, 17, 19, 21), temperature coefficients of the DC functions (note 16), AZERO OFF temperature coefficient '
          '(DC volts 5 uV/degC on 100 mV - 10 V and 500 uV/degC on 100 V - 1000 V, p. 15; resistance, ppm of range per degC, p. 19: 10 and 100 ohm 50, 1 and 10 kohm 5, 100 kohm to 10 Mohm 1, 100 Mohm 10, 1 Gohm 100), '
          'low-frequency error, crest factor error, source-resistance flatness errors, resolution multipliers, ACDCV / ACDCI additional errors, settling, common mode rejection, reading rates, digitizing, math. '
          'The AC transfer accuracy (p. 24: 100 mV - 100 V, "0.002 + resolution in %" % of reading, 45 Hz - 20 kHz, within 10 min and +/-0.5 degC, 4-hour warm-up) depends on the RES setting and is NOT stored.',
    '16': 'DC TEMPERATURE COEFFICIENTS (ppm of reading + ppm of range per degC; without ACAL: additional error from Tcal or last ACAL +/-1 degC; with ACAL: from Tcal +/-5 degC; information only, read twice): '
          'DC volts (p. 12) 100 mV 1.2 + 1 / 0.15 + 1; 1 V 1.2 + 0.1 / 0.15 + 0.1; 10 V 0.5 + 0.01 / 0.15 + 0.01; 100 V 2 + 0.4 / 0.15 + 0.1; 1000 V 2 + 0.04 / 0.15 + 0.01. '
          'Resistance (p. 16) 10 and 100 ohm 3 + 1 / 1 + 1; 1, 10, 100 kohm 3 + 0.1 / 1 + 0.1; 1 Mohm 3 + 1 / 1 + 1; 10 Mohm 20 + 20 / 5 + 2; 100 Mohm 100 + 20 / 25 + 2; 1 Gohm 1000 + 20 / (not readable). '
          'DC current (p. 20) 100 nA 10 + 200 / 2 + 50; 1 uA 2 + 20 / 2 + 5; 10 uA 10 + 4 / 2 + 1; 100 uA 10 + 3 / 2 + 1; 1 mA 10 + 2 / 2 + 1; 10 mA 10 + 2 / 2 + 1; 100 mA 25 + 2 / 2 + 1; 1 A 25 + 3 / 2 + 2. '
          'Not in any stored row: the sheet is at the temperature conditions of note 6.',
    '17': 'FREQUENCY / PERIOD (p. 34): "24 Hour - 2 Year (0 degC - 55 degC)": 1 Hz - 40 Hz (1 s - 25 ms) 0.05 % of reading; 40 Hz - 100 MHz (25 ms - 100 ns) 0.01 % of reading. The same page lists the input '
          'ranges (voltage 1 Hz - 10 MHz, 700 V rms - 1 mV rms; current 1 Hz - 100 kHz, 1 A rms - 10 uA rms), so the printed 100 MHz upper limit of the accuracy table is beyond the voltage / current input range '
          '(not explained in the data sheet; stored as printed). Time base 10 MHz +/-0.01 %, 0 to 55 degC (p. 35). The period rows are the same table (periods in parentheses) and are not stored separately.',
    '18': 'DIRECTION: "input" - the 3458A measures (the 5790B / 8563E / 8902A sheets do the same). specmanager.StandardSpec.lookup defaults to direction "output" and the budget (uncertainty_budget.build) does '
          'not pass one, so use lookup(..., direction="input") / tartur.standard_accuracy(..., direction="input"). The Datasheet Builder matcher uses the row direction itself.',
    '19': 'RESOLUTION: the "Maximum Resolution" column of each function table is stored as the row resolution (source "manual"): 8.5 digits at NPLC 100. A measurement at fewer power line cycles has a larger resolution '
          'and larger noise (pp. 13, 14, 17, 19, 21: not stored).',
}

LIMITS = [
    dict(function='Voltage, DC', limit='Accuracy per range, 90 day / 1 year, ppm of reading + ppm of range (PRESET; NPLC 100; MATH NULL; ACAL within 24 h, +/-1 degC; Tcal +/-5 degC).', page='12'),
    dict(function='Resistance', limit='Four-wire (OHMF) accuracy per range plus two-wire offset 50 / 150 / 250 / 500 mOhm; ppm of reading + ppm of range (0.5 %, 0.1 %, 1 % on the top ranges).', page='16-17'),
    dict(function='Current, DC', limit='100 nA to 1 A ranges; 100 nA, 1 uA and 10 uA typical.', page='20'),
    dict(function='Voltage, AC', limit='SYNC (<= 2 MHz and > 2 MHz), ANA, RNDM: % of reading + % of range per frequency band (one printed column, stored under 90 day and 1 yr).', page='24, 27, 29'),
    dict(function='Current, AC', limit='100 uA to 1 A: % of reading + % of range per frequency band; 5 kHz to 100 kHz typical.', page='32'),
    dict(function='Frequency', limit='0.05 % of reading (1 Hz - 40 Hz); 0.01 % of reading (40 Hz - 100 MHz).', page='34'),
]


# ------------------------------------------------------------------------------------------------------------ rows
def dc_rows():
    funcs = []
    # DC volts, standard stability (and Option 002 with the parenthesised readings)
    for title, option in (('Voltage, DC [Option 002 high stability]', True), ('Voltage, DC [Standard stability]', False)):
        f = dict(name=title, direction='input', page=12, ranges=[])
        for i, (rname_, rv, fs, res) in enumerate(DCV_RANGES):
            specs = []
            for per in PERIODS:
                cell = DCV[per][i]
                if cell is None:
                    continue
                reading, opt, rng = split_terms(cell)
                if option and opt is not None:
                    reading = opt
                specs.append(make_spec(per, reading, rng, rname_, D(rv)))
            fsd = D(fs)
            label = f'{rname_} range'
            f['ranges'].append(make_range(title, label, rname_, 'DCV', [amp_param(fs, 'V', f'-{si_range_text(fsd, "V")} to {si_range_text(fsd, "V")}', notes=[5, 6] + ([7] if option else []) + ([8] if i == 4 else []))],
                                          specs, 12, resolution=res))
        funcs.append(f)
    # transfer accuracy
    f = dict(name='Voltage, DC [Transfer, 10 min]', direction='input', page=13, ranges=[])
    for i, (rname_, rv, fs, res) in enumerate(DCV_RANGES):
        reading, _o, rng = split_terms(DCV_TRANSFER[i])
        fsd = D(fs)
        f['ranges'].append(make_range(f['name'], f'{rname_} range', rname_, 'DCV', [amp_param(fs, 'V', f'-{si_range_text(fsd, "V")} to {si_range_text(fsd, "V")}', notes=[9])],
                                      [make_spec('10 min', reading, rng, rname_, D(rv))], 13, resolution=res))
    funcs.append(f)
    # resistance, four-wire and two-wire
    for title, two in (('Resistance [4-wire (OHMF)]', False), ('Resistance [2-wire (OHM)]', True)):
        f = dict(name=title, direction='input', page=16, ranges=[])
        for i, (rname_, rv, fs, res) in enumerate(OHM_RANGES):
            specs = []
            for per in PERIODS:
                reading, _o, rng = split_terms(OHM[per][i])
                specs.append(make_spec(per, reading, rng, rname_, D(rv), abs_term=OHM2_OFFSET[per] if two else None, abs_unit='ohm' if two else ''))
            fsd = D(fs)
            f['ranges'].append(make_range(title, f'{rname_} range', rname_, 'OHM',
                                          [amp_param(fs, 'ohm', f'-{num(fsd)} ohm to {num(fsd)} ohm', notes=[6] + ([10] if (two or i >= 7) else []))], specs, 16, resolution=res))
        funcs.append(f)
    # DC current
    f = dict(name='Current, DC', direction='input', page=20, ranges=[])
    for i, (rname_, rv, fs, res) in enumerate(DCI_RANGES):
        specs = []
        for per in PERIODS:
            reading, _o, rng = split_terms(DCI[per][i])
            specs.append(make_spec(per, reading, rng, rname_, D(rv)))
        fsd = D(fs)
        typical = i in DCI_TYPICAL
        label = f'{rname_} range' + (' (typical)' if typical else '')
        f['ranges'].append(make_range(f['name'], label, rname_, 'DCI', [amp_param(fs, 'A', f'-{si_range_text(fsd, "A")} to {si_range_text(fsd, "A")}', notes=[6, 11] if typical else [6])],
                                      specs, 20, resolution=res))
    funcs.append(f)
    return funcs


def ac_rows():
    funcs = []
    for title, mode, page, bands, table in ACV_TABLES:
        name = f'Voltage, AC [{title}]'
        f = dict(name=name, direction='input', page=page, ranges=[])
        for ri, (rname_, rv, fs) in enumerate(ACV_RANGES):
            cells = table[ACV_GROUP[rname_]]
            fsd = D(fs)
            res = ACV_RES[mode][ri]
            for bi, (lo, hi) in enumerate(bands):
                cell = cells[bi]
                if not cell:
                    continue
                reading, _o, rng = split_terms(cell)
                specs = [make_spec_pct(per, reading, rng, rname_, D(rv)) for per in PERIODS]
                label = f'{rname_} range @ {hz_text(lo)} to {hz_text(hi)}'
                f['ranges'].append(make_range(name, label, rname_, 'ACV',
                                              [amp_param(fs, 'V', f'-{si_range_text(fsd, "V")} to {si_range_text(fsd, "V")}', notes=[12]), freq_param(lo, hi)],
                                              specs, page, resolution=res, freq=(float(D(repr(float(lo)))), float(D(repr(float(hi)))))))
        funcs.append(f)
    # AC current
    f = dict(name='Current, AC', direction='input', page=32, ranges=[])
    for ri, (rname_, rv, fs, res) in enumerate(ACI_RANGES):
        cells = ACI[ACI_GROUP[rname_]]
        fsd = D(fs)
        for bi, (lo, hi) in enumerate(ACI_BANDS):
            cell = cells[bi]
            if not cell:
                continue
            reading, _o, rng = split_terms(cell)
            specs = [make_spec_pct(per, reading, rng, rname_, D(rv)) for per in PERIODS]
            typical = bi in ACI_TYPICAL_BANDS
            hi_eff = 1e3 if (rname_ == '100 uA' and bi == 3) else hi
            label = f'{rname_} range @ {hz_text(lo)} to {hz_text(hi)}' + (' (1 kHz maximum on 100 uA)' if hi_eff != hi else '') + (' (typical)' if typical else '')
            f['ranges'].append(make_range(f['name'], label, rname_, 'ACI',
                                          [amp_param(fs, 'A', f'-{si_range_text(fsd, "A")} to {si_range_text(fsd, "A")}', notes=[14]), freq_param(lo, hi_eff)],
                                          specs, 32, resolution=res, freq=(float(D(repr(float(lo)))), float(D(repr(float(hi_eff)))))))
    funcs.append(f)
    # frequency
    f = dict(name='Frequency', direction='input', page=34, ranges=[])
    for text, lo, hi, pct in FREQ:
        specs = [make_spec(per, pct + '%', None, '', D(0)) for per in PERIODS]
        param = dict(tag='', lo=float(lo), hi=float(hi), unit='Hz', text=text, annot='', notes=[17])
        f['ranges'].append(make_range('Frequency', text, text.split(' (')[0], 'FREQ', [param], specs, 34))
    funcs.append(f)
    return funcs


def make_spec_pct(period, reading_pct, range_pct, range_name, range_value):
    """AC table cell: percent of reading + percent of range (Decimal)."""
    return make_spec(period, reading_pct + '%', range_pct, range_name, range_value, range_pct=True)


def problems_for(data):
    probs = list(sm.validate_data(data))
    if not VERIFIED_AGAINST_IMAGE:
        probs.append(dict(level='warn', where='standard', what='UNVERIFIED against the rendered pages: re-read the tables from page images and rebuild.'))
    probs.append(dict(level='warn', where='standard', what='CONFIDENCE LEVEL NOT STATED by the data sheet (5965-4971E): confidence_pct is empty and the coverage divisor 2 is an ASSUMPTION '
                                                          '(repository rule for a sheet without a level). Decide the divisor in Standards Specs.'))
    probs.append(dict(level='warn', where='standard', what='The accuracy is RELATIVE to the calibration standards (p. 8). The factory traceability adders (DC volts 2 ppm, resistance 3 ppm, DC current 5 ppm, '
                                                          'AC volts 2 ppm, AC current 5 ppm of reading) are not added to any row. OPEN ITEM: the owner has not decided whether they are wanted.'))
    probs.append(dict(level='warn', where='Voltage, DC / 1000 V range (p. 12 footnote 6)', what='Footnote 6, "Add 12 ppm X (Vin / 1000)2 additional errors for inputs > 100 vV", is not in the stored 1000 V rows '
                                                                                                'and is printed with typing errors; it is a note only.'))
    probs.append(dict(level='warn', where='Voltage, DC [Option 002 high stability]', what='Option 002 (high stability) is the DEFAULT of a plain DC volts lookup because the owner says the lab\'s 3458A has it; '
                                                                                         'the standard-stability rows are stored as the variant "Standard stability".'))
    probs.append(dict(level='warn', where='Current, DC / 100 nA, 1 uA, 10 uA', what='Typical accuracy (p. 20 footnote 6), not warranted.'))
    probs.append(dict(level='warn', where='Current, DC', what='The highest range is 1 A (full scale 1.05 A): there is no row for a current above 1.05 A (2 A).'))
    probs.append(dict(level='warn', where='Voltage, AC [SETACV RNDM, ...] (p. 29)', what='The random-sampled table prints no conditions of its own (its footnote 1 is the temperature-coefficient one); the SYNC / ANA conditions are assumed.'))
    probs.append(dict(level='warn', where='Current, AC (p. 32)', what='Bands 5 kHz to 100 kHz are typical (footnote 3); the 100 Hz - 5 kHz band of the 100 uA range is stored to 1 kHz (footnote 4).'))
    probs.append(dict(level='warn', where='Frequency (p. 34)', what='The accuracy table runs to 100 MHz, beyond the 10 MHz voltage input range printed on the same page; stored as printed.'))
    return probs


def build():
    functions = dc_rows() + ac_rows()
    data = dict(schema=1, standard=dict(
        manufacturer='Keysight Technologies (Agilent / Hewlett-Packard)', model=MODEL,
        description='8.5-digit digital multimeter (Keysight data sheet 5965-4971E)',
        confidence_text=CONFIDENCE_TEXT, confidence_pct=None,
        reference='Keysight 3458A Multimeter data sheet 5965-4971E, published June 10, 2026, pp. 8-35 (accuracy tables pp. 12, 13, 16, 17, 20, 24, 27, 29, 32, 34)',
        revision='5965-4971E (June 10, 2026)',
        author='written by specs/build_3458a_standard.py from the rendered page images of the data sheet' + ('' if VERIFIED_AGAINST_IMAGE else ' (UNVERIFIED against the rendered pages)'),
        approved_by='', approve_date='', source_pdf=SOURCE_PDF, sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, limits=LIMITS, functions=functions)
    data['problems'] = problems_for(data)
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'keysight_3458a_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    errs = [p for p in data['problems'] if p['level'] == 'error']
    print(f"{MODEL}: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} flagged ({len(errs)} errors) -> {out}")
    for f in data['functions']:
        print(f"  {f['name']}: {len(f['ranges'])} rows")
    for p in data['problems']:
        print(p['level'].upper(), p['where'], '-', p['what'][:160])


if __name__ == '__main__':
    main()
