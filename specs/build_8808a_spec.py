"""Builds specs/fluke_8808a_pv.json: the Fluke 8808A performance verification (bench 5-1/2 digit DMM, RS-232 only).

    python3 specs/build_8808a_spec.py

Source: Fluke 8808A Calibration Manual (56 pp.), chapter 3 "Performance Verification and Calibration":
  Table 3-1 required equipment (printed p. 3-3), Tables 3-2 to 3-8 (printed pp. 3-4 to 3-11: DC volts, AC volts, 4-wire ohms, 2-wire ohms,
  DC current, AC current, frequency; 105 points), and the specification tables, printed pp. 1-10 to 1-14 (the accuracy of every function).
Every nominal, range, frequency and limit below was read from the RENDERED PAGE IMAGES of those pages (pdftoppm, 130 and 150 dpi), twice, never from
extracted text (the units mu and Omega do not survive text extraction). Nothing was typed from a text extraction.

What the manual prints: for each point a 90-day and a 1-year limit pair (High, Low). The manual says to use the 90-day limits for an acceptance test
after a calibration and recommends a one-year interval, so the procedure offers both periods (default 1 year). The limits are the manual's printed
numbers ("printed limits": the specification formula, rounded to the printed number of decimals), so a printed limit pair can be a little asymmetric about
the nominal. The ohms rows print "STD +/- tolerance", where STD is the calibrator's own reading of the resistance it applies; the procedure uses the
calibrator's setpoint as STD (the engine cannot read a 5700A-class value back), so those limits are nominal +/- tolerance (std_relative = true).

Every printed limit is checked here against the manual's own accuracy formula (+/-(% of reading + % of range), printed pp. 1-10 to 1-14) with Decimal math,
and the build FAILS when a limit disagrees with the formula by more than the rounding of its last printed digit and the disagreement is not listed
below. Listed disagreements are of three kinds (each is kept in the point as 'flags', the printed text is kept in 'printed_limits'):
  typo          a clear misprint (missing minus sign, a dropped decimal point, a wrong digit): the limit of the manual's own formula is used
  looser        the printed limit is LOOSER than the manual's own formula: the formula's limit is used (the specification is never relaxed)
  tighter       the printed limit is TIGHTER than the formula (the frequency rows): the printed limit is kept
  structure     a misprint in the nominal, range, frequency or unit columns, corrected by the table's own limits (see each note)
Every one is listed for the lab owner in the final summary of this work and in NOTES.md.

Run order: all shorted-input zero points first (one fixture), then the open current-input zero points, then the sourced points grouped by the cabling
they need (voltage, 4-wire ohms, 2-wire ohms, then the mA terminal, the 2 A range on the 10 A terminal, the 10 A range), as the 34970A spec does.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_8808a_pv.json'
MODEL = '8808A'
PERIODS = ('90d', '1y')

# display unit -> (factor to base unit, base unit)
UNITS = {'V': (D(1), 'V'), 'mV': (D('0.001'), 'V'), 'uA': (D('0.000001'), 'A'), 'mA': (D('0.001'), 'A'), 'A': (D(1), 'A'),
         'ohm': (D(1), 'ohm'), 'kohm': (D(1000), 'ohm'), 'Mohm': (D(1000000), 'ohm'), 'Hz': (D(1), 'Hz'), 'kHz': (D(1000), 'Hz')}
TOKEN = re.compile(r'^(STD)?\s*([+-]?)\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)$')

# ----------------------------------------------------------------------------------------------------------------------------------
# The manual's accuracy formulas (specification tables, printed pp. 1-10 to 1-14): (% of reading, % of range) for 90 days and 1 year.
# ----------------------------------------------------------------------------------------------------------------------------------
DCV = {D('0.2'): ((D('0.01'), D('0.003')), (D('0.015'), D('0.004'))), D(2): ((D('0.01'), D('0.002')), (D('0.015'), D('0.003'))),
       D(20): ((D('0.01'), D('0.003')), (D('0.015'), D('0.004'))), D(200): ((D('0.01'), D('0.002')), (D('0.015'), D('0.003'))),
       D(1000): ((D('0.01'), D('0.002')), (D('0.015'), D('0.003')))}
ACV_BANDS = [          # (upper edge of the band, inclusive, Hz), 90 days, 1 year. 20-45 Hz is the first band (45 Hz belongs to the next one)
    (D(45), True, ((D('0.8'), D('0.05')), (D('0.9'), D('0.05')))), ]
# AC volts: bands by frequency, the same on every range. A frequency belongs to the band whose upper edge it does not exceed (45 Hz belongs to 45 Hz - 20 kHz,
# 20 kHz to 45 Hz - 20 kHz, 50 kHz to 20 - 50 kHz), except that 20 Hz belongs to the first band.
ACV_TABLE = [(D(45), ((D('0.8'), D('0.05')), (D('0.9'), D('0.05'))), 'lt'),       # 20 Hz to below 45 Hz
             (D(20000), ((D('0.15'), D('0.05')), (D('0.2'), D('0.05'))), 'le'),    # 45 Hz to 20 kHz
             (D(50000), ((D('0.3'), D('0.05')), (D('0.35'), D('0.05'))), 'le'),    # above 20 kHz to 50 kHz
             (D(100000), ((D('0.8'), D('0.05')), (D('0.9'), D('0.05'))), 'le')]    # above 50 kHz to 100 kHz
OHM = {D(200): ((D('0.02'), D('0.004')), (D('0.03'), D('0.004'))), D(2000): ((D('0.015'), D('0.002')), (D('0.02'), D('0.003'))),
       D(20000): ((D('0.015'), D('0.002')), (D('0.02'), D('0.003'))), D(200000): ((D('0.015'), D('0.002')), (D('0.02'), D('0.003'))),
       D(2000000): ((D('0.03'), D('0.003')), (D('0.04'), D('0.004'))), D(20000000): ((D('0.2'), D('0.003')), (D('0.25'), D('0.003'))),
       D(100000000): ((D('1.5'), D('0.004')), (D('1.75'), D('0.004')))}
DCI = {D('0.0002'): ((D('0.02'), D('0.005')), (D('0.03'), D('0.005'))), D('0.002'): ((D('0.015'), D('0.005')), (D('0.02'), D('0.005'))),
       D('0.02'): ((D('0.03'), D('0.02')), (D('0.04'), D('0.02'))), D('0.2'): ((D('0.02'), D('0.005')), (D('0.03'), D('0.008'))),
       D(2): ((D('0.05'), D('0.02')), (D('0.08'), D('0.02'))), D(10): ((D('0.18'), D('0.01')), (D('0.2'), D('0.01')))}
# AC current: (low band 20-45 Hz, high band 45 Hz - 2 kHz) per range
ACI = {D('0.02'): (((D(1), D('0.05')), (D('1.25'), D('0.06'))), ((D('0.25'), D('0.05')), (D('0.3'), D('0.06')))),
       D('0.2'): (((D('0.8'), D('0.05')), (D(1), D('0.06'))), ((D('0.25'), D('0.05')), (D('0.3'), D('0.06')))),
       D(2): (((D(1), D('0.05')), (D('1.25'), D('0.06'))), ((D('0.25'), D('0.05')), (D('0.3'), D('0.06')))),
       D(10): (((D(1), D('0.1')), (D('1.25'), D('0.12'))), ((D('0.35'), D('0.1')), (D('0.5'), D('0.12'))))}
FREQ = {D(2000): ((D('0.01'), D('0.002')), (D('0.01'), D('0.003'))), D(20000): ((D('0.01'), D('0.002')), (D('0.01'), D('0.003'))),
        D(200000): ((D('0.01'), D('0.002')), (D('0.01'), D('0.003'))), D(1000000): ((D('0.01'), D('0.004')), (D('0.01'), D('0.006')))}


def formula(kind, rng, freq, period):
    """(% of reading, % of range) the manual's specification gives for this point and period ('90d' / '1y')."""
    i = PERIODS.index(period)
    if kind == 'DCV':
        return DCV[rng][i]
    if kind == 'ACV':
        for edge, pcts, mode in ACV_TABLE:
            if freq < edge or (mode == 'le' and freq == edge):
                return pcts[i]
        raise KeyError(f'AC volts: no band for {freq} Hz')
    if kind in ('OHM2', 'OHM4'):
        return OHM[rng][i]
    if kind == 'DCI':
        return DCI[rng][i]
    if kind == 'ACI':
        low, high = ACI[rng]
        return (low if freq < 45 else high)[i]
    if kind == 'FREQ':
        return FREQ[rng][i]
    raise KeyError(kind)


def tolerance(kind, nominal, rng, freq, period):
    """The manual's tolerance (base units) for the point: % of reading + % of range."""
    p_read, p_range = formula(kind, rng, freq, period)
    return p_read / 100 * abs(nominal) + p_range / 100 * rng


# ----------------------------------------------------------------------------------------------------------------------------------
# The tables, as printed. Each row: (nominal text, range text, frequency text or None, [90d High, 90d Low, 1y High, 1y Low]).
# Nominal / range / frequency are "<number> <unit>" strings; limits are "<number> <unit>" or, for ohms, "STD+<number> <unit>" / "STD-<number> <unit>".
# ----------------------------------------------------------------------------------------------------------------------------------
T32 = [   # Table 3-2, printed p. 3-4, direct voltage verification steps (17)
    ('0 V', '200 mV', None, ['0.006 mV', '-0.006 mV', '0.008 mV', '-0.008 mV']),
    ('190 mV', '200 mV', None, ['190.025 mV', '189.975 mV', '190.037 mV', '189.964 mV']),
    ('-190 mV', '200 mV', None, ['-189.975 mV', '-190.025 mV', '-189.964 mV', '-190.037 mV']),
    ('0 V', '2 V', None, ['0.00004 V', '-0.00004 V', '0.00006 V', '-0.00006 V']),
    ('0.5 V', '2 V', None, ['0.50009 V', '0.49991 V', '0.50014 V', '0.49986 V']),
    ('-0.5 V', '2 V', None, ['-0.49991 V', '-0.50009 V', '-0.49986 V', '-0.50014 V']),
    ('1.9 V', '2 V', None, ['1.90023 V', '1.89977 V', '1.90034 V', '1.89966 V']),
    ('-1.9 V', '2 V', None, ['-1.89977 V', '-1.90023 V', '-1.89966 V', '-1.90034 V']),
    ('0 V', '20 V', None, ['0.0006 V', '-0.0006 V', '0.0008 V', '-0.0008 V']),
    ('19 V', '20 V', None, ['19.0025 V', '18.9975 V', '19.0037 V', '18.9963 V']),
    ('-19 V', '20 V', None, ['-18.9975 V', '-19.0025 V', '-18.9963 V', '19.0037 V']),
    ('0 V', '200 V', None, ['0.004 V', '-0.004 V', '0.006 V', '-0.006 V']),
    ('190 V', '200 V', None, ['190.023 V', '189.977 V', '190.034 V', '189.966 V']),
    ('-190 V', '200 V', None, ['-189.977 V', '-190.023 V', '-189.966 V', '-190.034 V']),
    ('0 V', '1000 V', None, ['0.02 V', '-0.02 V', '0.03 V', '-0.03 V']),
    ('1000 V', '1000 V', None, ['1000.12 V', '999.88 V', '1000.18 V', '999.82 V']),
    ('-1000 V', '1000 V', None, ['-999.88 V', '-1000.12 V', '-999.82 V', '-1000.18 V']),
]
T33 = [   # Table 3-3, printed p. 3-5, alternating voltage verification steps (28)
    ('10 mV', '200 mV', '50 Hz', ['10.120 mV', '9.890 mV', '10.120 mV', '9.880 mV']),
    ('190 mV', '200 mV', '20 Hz', ['191.620 mV', '188.380 mV', '191.810 mV', '188.190 mV']),
    ('190 mV', '200 mV', '45 Hz', ['190.385 mV', '189.615 mV', '190.480 mV', '189.520 mV']),
    ('190 mV', '200 mV', '20 kHz', ['190.385 mV', '189.615 mV', '190.480 mV', '189.520 mV']),
    ('190 mV', '200 mV', '50 kHz', ['190.670 mV', '189.330 mV', '190.765 mV', '189.235 mV']),
    ('190 mV', '200 mV', '100 kHz', ['191.620 mV', '188.380 mV', '191.810 mV', '188.190 mV']),
    ('0.1 V', '2 V', '50 Hz', ['0.10115 V', '0.09885 V', '0.10120 V', '0.09880 V']),
    ('1.9 V', '2 V', '20 Hz', ['1.91620 V', '1.88380 V', '1.91810 V', '1.88190 V']),
    ('1.9 V', '2 V', '45 Hz', ['1.90385 V', '1.89615 V', '1.90480 V', '1.89520 V']),
    ('1.9 V', '2 V', '20 kHz', ['1.903985 V', '1.89615 V', '1.90480 V', '1.89520 V']),
    ('1.9 V', '2 V', '50 kHz', ['1.90670 V', '1.89330 V', '1.90765 V', '1.89235 V']),
    ('1.9 V', '2 V', '100 kHz', ['1.91620 V', '1.88380 V', '1.91810 V', '1.88190 V']),
    ('1 V', '20 V', '50 Hz', ['1.0115 V', '0.9885 V', '1.0120 V', '0.9880 V']),
    ('19 V', '20 V', '20 Hz', ['19.1620 V', '18.8380 V', '19.1810 V', '18.8190 V']),
    ('19 V', '20 V', '45 Hz', ['19.0385 V', '18.9615 V', '19.0480 V', '18.9520 V']),
    ('19 V', '20 V', '20 kHz', ['19.0385 V', '18.9615 V', '19.0480 V', '18.9520 V']),
    ('19 V', '20 V', '50 kHz', ['19.0670 V', '18.9330 V', '19.0765 V', '18.9235 V']),
    ('19 V', '20 V', '100 kHz', ['19.1620 V', '18.8380 V', '19.1810 V', '18.8190 V']),
    ('10 V', '200 V', '50 Hz', ['10.115 V', '9.885 V', '10.120 V', '9.880 V']),
    ('190 V', '200 V', '45 Hz', ['190.385 V', '189.615 V', '190.480 V', '189.520 V']),
    ('190 V', '200 V', '20 kHz', ['190.39 V', '189.62 V', '190.480 V', '189.520 V']),
    ('190 V', '200 V', '50 kHz', ['190.670 V', '189.330 V', '190.765 V', '189.235 V']),
    ('190 V', '200 V', '100 kHz', ['191.620 V', '188.380 V', '191.810 V', '188.190 V']),
    ('750 V', '30 V', '50 Hz', ['30.42 V', '29.58 V', '30.44 V', '29.57 V']),        # Ampl. and Range columns swapped in the manual (see STRUCT)
    ('750 V', '750 V', '45 Hz', ['751.50 V', '748.50 V', '751.88 V', '748.13 V']),
    ('750 V', '750 V', '20 kHz', ['751.50 V', '748.50 V', '751.88 V', '748.13 V']),
    ('750 V', '750 V', '50 kHz', ['752.63 V', '747.48 V', '753.00 V', '747.00 V']),
    ('750 V', '750 V', '100 kHz', ['756.38 V', '743.62 V', '757.13 V', '742.88 V']),
]
T34 = [   # Table 3-4, printed p. 3-6, 4-wire ohms verification steps (6); STD = the calibrator reading
    ('0 ohm', '200 ohm', None, ['0.008 ohm', '-0.008 ohm', '0.008 ohm', '-0.008 ohm']),
    ('190 ohm', '200 ohm', None, ['STD+0.046 ohm', 'STD-0.046 ohm', 'STD+0.065 ohm', 'STD-0.065 ohm']),
    ('0 kohm', '2 kohm', None, ['0.00004 kohm', '-0.00004 kohm', '0.00006 kohm', '-0.00006 kohm']),
    ('1.9 kohm', '2 kohm', None, ['STD+0.00033 kohm', 'STD-0.00033 kohm', 'STD+0.00044 kohm', 'STD-0.00044 kohm']),
    ('0 kohm', '20 kohm', None, ['0.0004 kohm', '-0.0004 kohm', '0.0006 kohm', '-0.0006 kohm']),
    ('19 kohm', '20 kohm', None, ['STD+0.0033 kohm', 'STD-0.0033 kohm', 'STD+0.0044 kohm', 'STD-0.0044 kohm']),
]
T35 = [   # Table 3-5, printed pp. 3-7 and 3-8, 2-wire ohms verification steps (14)
    ('0 ohm', '200 ohm', None, ['0.008 ohm', '-0.008 ohm', '0.008 ohm', '-0.008 ohm']),
    ('190 ohm', '200 ohm', None, ['STD+0.046 ohm', 'STD-0.046 ohm', 'STD+0.065 ohm', 'STD-0.065 ohm']),
    ('0 kohm', '2 kohm', None, ['0.00004 kohm', '-0.00004 kohm', '0.00006 kohm', '-0.00006 kohm']),
    ('1.9 kohm', '2 kohm', None, ['STD+0.00033 kohm', 'STD-0.00033 kohm', 'STD+0.0044 kohm', 'STD-0.0044 kohm']),
    ('0 kohm', '20 kohm', None, ['0.0004 kohm', '-0.0004 kohm', '0.0006 kohm', '-0.0006 kohm']),
    ('19 kohm', '20 kohm', None, ['STD+0.0033 kohm', 'STD-0.0033 kohm', 'STD+0.0044 kohm', 'STD-0.0044 kohm']),
    ('0 kohm', '200 kohm', None, ['0.004 kohm', '-0.004 kohm', '0.006 kohm', '-0.006 kohm']),
    ('190 kohm', '200 kohm', None, ['STD+0.033 kohm', 'STD-0.033 kohm', 'STD+0.044 kohm', 'STD-0.044 kohm']),
    ('0 Mohm', '2 Mohm', None, ['0.00006 Mohm', '-0.00006 Mohm', '0.00008 Mohm', '-0.00008 Mohm']),
    ('1.9 Mohm', '2 Mohm', None, ['STD+0.00063 Mohm', 'STD-0.00063 Mohm', 'STD+0.00084 Mohm', 'STD-0.00084 Mohm']),
    ('0 Mohm', '20 Mohm', None, ['0.0006 Mohm', '-0.0006 Mohm', '0.0006 Mohm', '-0.0006 Mohm']),
    ('19 Mohm', '20 Mohm', None, ['STD+0.0386 Mohm', 'STD-0.0386 Mohm', 'STD+0.0481 Mohm', 'STD-0.0481 Mohm']),
    ('0 Mohm', '100 Mohm', None, ['0.004 Mohm', '-0.004 Mohm', '0.004 Mohm', '-0.004 Mohm']),
    ('100 Mohm', '100 Mohm', None, ['STD+1.504 Mohm', 'STD-1.504 Mohm', 'STD+1.754 Mohm', 'STD-1.754 Mohm']),
]
T36 = [   # Table 3-6, printed pp. 3-9 and 3-10, direct current verification steps (18)
    ('0 uA', '200 uA', None, ['0.010 uA', '-0.010 uA', '0.010 uA', '-0.010 uA']),
    ('190 uA', '200 uA', None, ['190.048 uA', '189.952 uA', '190.067 uA', '189.933 uA']),
    ('-190 uA', '200 uA', None, ['-189.952 uA', '-190.048 uA', '-189.933 uA', '-190.067 uA']),
    ('0 uA', '2000 uA', None, ['0.10 uA', '-0.10 uA', '0.10 uA', '-0.10 uA']),
    ('1900 uA', '2000 uA', None, ['1900.39 uA', '1899.62 uA', '1900.48 uA', '1899.52 uA']),
    ('-1900 uA', '2000 uA', None, ['-1899.62 uA', '-1900.39 uA', '-1899.52 uA', '-1900.48 uA']),
    ('0 mA', '20 mA', None, ['0.0040 mA', '-0.0040 mA', '0.0040 mA', '-0.0040 mA']),
    ('19 mA', '20 mA', None, ['19.0097 mA', '18.9903 mA', '19.0116 mA', '18.9884 mA']),
    ('-19 mA', '20 mA', None, ['-18.9903 mA', '-19.0097 mA', '-18.9884 mA', '-190.0116 mA']),
    ('0 mA', '200 mA', None, ['0.010 mA', '-0.010 mA', '0.020 mA', '-0.020 mA']),
    ('190 mA', '200 mA', None, ['190.048 mA', '189.952 mA', '190.073 mA', '189.927 mA']),
    ('-190 mA', '200 mA', None, ['-189.952 mA', '190.048 mA', '-189.927 mA', '-190.073 mA']),
    ('0 A', '2 A', None, ['0.00040 A', '-0.00040 A', '0.00040 A', '-0.00040 A']),
    ('1.9 A', '2 A', None, ['1.90135 A', '1.89865 A', '1.90192 A', '1.89808 A']),
    ('-1.9 A', '2 A', None, ['-1.89865 A', '-1.90135 A', '-1.89808 A', '-1.90192 A']),
    ('0 A', '10 A', None, ['0.0010 A', '-0.0010 A', '0.0010 A', '-0.0010 A']),
    ('10 A', '10 A', None, ['10.0190 A', '9.9810 A', '10.0210 A', '9.9790 A']),
    ('-10 A', '10 A', None, ['-9.9810 A', '-10.0190 A', '-9.9790 A', '-10.0210 A']),
]
T37 = [   # Table 3-7, printed p. 3-10, alternating current verification steps (16)
    ('1 mA', '20 mA', '45 Hz', ['1.0125 mA', '0.9875 mA', '1.0150 mA', '0.9850 mA']),
    ('19 mA', '20 mA', '20 Hz', ['19.2000 mA', '18.8000 mA', '19.2495 mA', '18.7505 mA']),
    ('19 mA', '20 mA', '45 Hz', ['19.058 mA', '18.943 mA', '19.0690 mA', '18.9310 mA']),
    ('19 mA', '20 mA', '2 kHz', ['19.0575 mA', '18.9425 mA', '19.0690 mA', '18.9310 mA']),
    ('10 mA', '200 mA', '45 Hz', ['10.125 mA', '9.875 mA', '10.150 mA', '9.850 mA']),
    ('190 mA', '200 mA', '20 Hz', ['191.620 mA', '188.380 mA', '192.020 mA', '187.980 mA']),
    ('190 mA', '200 mA', '45 Hz', ['190.575 mA', '189.425 mA', '190.690 mA', '189.310 mA']),
    ('190 mA', '200 mA', '2 kHz', ['190.575 mA', '189.425 mA', '190.690 mA', '189.310 mA']),
    ('0.1 A', '2 A', '45 Hz', ['0.10125 A', '0.09875 A', '0.10150 A', '0.09850 A']),
    ('1.9 A', '2 A', '20 Hz', ['1.92000 A', '1.88000 A', '1.92495 A', '1.87505 A']),
    ('1.9 A', '2 A', '45 Hz', ['1.90575 A', '1.89425 A', '1.90690 A', '1.89310 A']),
    ('1.9 A', '2 A', '2 kHz', ['1.90575 A', '1.89425 A', '1.90690 A', '1.89310 A']),
    ('0.5 A', '10 A', '45 Hz', ['0.5118 A', '0.4883 A', '0.5145 A', '04855 A']),
    ('10 A', '10 A', '40 Hz', ['10.1100 A', '9.8900 A', '10.1370 A', '9.8630 A']),
    ('10 A', '10 A', '45 A', ['10.0450 A', '9.9550 A', '10.0620 A', '9.9380 A']),          # printed "45 A": a misprint of 45 Hz (see STRUCT)
    ('10 A', '10 A', '1 kHz', ['10.0450 A', '9.9550 A', '10.0620 A', '9.9380 A']),
]
T38 = [   # Table 3-8, printed p. 3-11, frequency verification steps (6); every row applies 0.1 V; the manual prints the limits of the last four rows in "Hz"
    ('0.1 V', '2000 Hz', '20 Hz', ['20.04 Hz', '19.96 Hz', '20.06 Hz', '19.94 Hz']),
    ('0.1 V', '2000 Hz', '50 Hz', ['50.01 Hz', '50.00 Hz', '50.01 Hz', '50.00 Hz']),
    ('0.1 V', '2000 Hz', '1900 Hz', ['1900.19 Hz', '1899.81 Hz', '1900.19 Hz', '1899.81 Hz']),
    ('0.1 V', '20 kHz', '19 kHz', ['19.0023 kHz', '18.9977 kHz', '19.0025 kHz', '18.9975 kHz']),
    ('0.1 V', '200 kHz', '195 kHz', ['195.024 kHz', '194.977 kHz', '195.026 kHz', '194.975 kHz']),
    ('0.1 V', '1000 kHz', '1000 kHz', ['1000.14 kHz', '999.86 kHz', '1000.16 kHz', '999.84 kHz']),
]

# ----------------------------------------------------------------------------------------------------------------------------------
# Disagreements with the manual's own formula that are accepted (row = 1-based row number of the table).
#   CORR  (table, row): [(period, field, used text, kind, why)]      kind 'typo' or 'looser': the used limit replaces the printed one
#   KEEP  (table, row): why                                          printed limits kept although they differ from the formula (tighter)
#   STRUCT (table, row): dict(nominal=, range=, frequency=, unit=, why=)   misprinted columns
# ----------------------------------------------------------------------------------------------------------------------------------
CORR = {
    ('3-2', 11): [('1y', 'low', '-19.0037 V', 'typo', 'the minus sign is missing: the 1-year low limit of -19 V prints 19.0037 V; the formula and the 1-year high limit (-18.9963 V) give -19.0037 V')],
    ('3-3', 1): [('90d', 'high', '10.115 mV', 'looser', 'the 90-day pair prints 10.120 / 9.890 mV; the formula (0.15 % of 10 mV + 0.05 % of 200 mV = 0.115 mV) gives 10.115 / 9.885 mV'),
                 ('90d', 'low', '9.885 mV', 'looser', 'see the 90-day high limit of this row')],
    ('3-3', 10): [('90d', 'high', '1.90385 V', 'typo', 'prints "1.903985 V": one digit too many; the formula and every other 45 Hz - 20 kHz row (190.385 mV, 19.0385 V ...) give 1.90385 V')],
    ('3-3', 27): [('90d', 'low', '747.38 V', 'typo', 'prints 747.48 V; the formula (0.3 % of 750 V + 0.05 % of 750 V = 2.625 V) gives 747.375 V (747.38 V) and the high limit prints 752.63 V')],
    ('3-5', 4): [('1y', 'high', 'STD+0.00044 kohm', 'typo', 'prints "STD+0.0044 kohm": a digit dropped; 0.02 % of 1.9 kohm + 0.003 % of 2 kohm = 0.00044 kohm, the 4-wire table (3-4) prints 0.00044 kohm for the same point'),
                ('1y', 'low', 'STD-0.00044 kohm', 'typo', 'prints "STD-0.0044 kohm": see the 1-year high limit of this row')],
    ('3-6', 9): [('1y', 'low', '-19.0116 mA', 'typo', 'prints "-190.0116 mA": an extra digit; the formula and the 1-year high limit (-18.9884 mA) give -19.0116 mA')],
    ('3-6', 10): [('1y', 'high', '0.016 mA', 'looser', 'the 1-year zero limit of the 200 mA range prints 0.020 mA; the specification (0.008 % of the 200 mA range, the same term that gives the printed 190.073 mA limit) is 0.016 mA'),
                  ('1y', 'low', '-0.016 mA', 'looser', 'see the 1-year high limit of this row')],
    ('3-6', 12): [('90d', 'low', '-190.048 mA', 'typo', 'the minus sign is missing: prints 190.048 mA; the formula and the high limit (-189.952 mA) give -190.048 mA')],
    ('3-7', 13): [('1y', 'low', '0.4855 A', 'typo', 'prints "04855 A": the decimal point is missing; the formula gives 0.4855 A (0.5 A - 0.0145 A)')],
}
KEEP = {
    ('3-8', 2): 'the printed 50.00 / 50.01 Hz is TIGHTER than the specification formula (0.01 % of 50 Hz + 0.002 % of the 2000 Hz range = 0.045 Hz); the printed limits are kept',
    ('3-8', 3): 'the printed 1899.81 / 1900.19 Hz is TIGHTER than the specification formula (0.01 % of 1900 Hz + 0.002 % of the 2000 Hz range = 0.23 Hz); the printed limits are kept',
}
STRUCT = {
    ('3-3', 24): dict(nominal='30 V', range='750 V', why='the Ampl. and Range columns are swapped (prints Ampl. 750 V, Range 30 V): the limits (30.42 / 29.58 V = 0.15 % of 30 V + 0.05 % of 750 V) are those of 30 V on the 750 V range'),
    ('3-7', 15): dict(frequency='45 Hz', why='the frequency prints "45 A": a misprint of 45 Hz (the same limits as the 1 kHz row, i.e. the 45 Hz - 2 kHz band)'),
    ('3-8', 4): dict(unit='kHz', why='the limits print "Hz" but are kHz (19.0023 against a 19 kHz input)'),
    ('3-8', 5): dict(unit='kHz', why='the limits print "Hz" but are kHz (195.024 against a 195 kHz input)'),
    ('3-8', 6): dict(unit='kHz', why='the limits print "Hz" but are kHz (1000.14 against a 1000 kHz input)'),
}
# points the calibrators cannot make (name -> reason, per calibrator): the procedure asks for another standard instead.
# A calibrator that is not listed for a point CAN make it and drives it.  5522A: Operators Manual (R0) Detailed Specifications.
# 5560A: Product Specifications (Rev. 8, 6/26), read from the rendered page images (PDF pp. 4-5 = printed pp. 3-4, ACV; PDF p. 9 = printed p. 8, ACI).
_5522A_HV = '5522A: 330 V to 1020 V is specified 45 Hz to 10 kHz only (5522A Operators Manual, Detailed Specifications, AC voltage, printed p. 1-12). The manual uses a 5725A amplifier.'
_5560A_HV = ('5560A: the 1020 V range (above 330 V, so 750 V) is specified 3 Hz to 10 kHz only; the 330 V range stops at 100 kHz (5560A Product Specifications, ACV Specifications, '
             'printed p. 4). The manual uses a 5725A amplifier.')
CAL_LIMITS = {
    ('3-3', 26): {'5522A': _5522A_HV, '5560A': _5560A_HV},
    ('3-3', 27): {'5522A': _5522A_HV, '5560A': _5560A_HV},
    ('3-3', 28): {'5522A': _5522A_HV, '5560A': _5560A_HV},
    # 10 A ac at 40 Hz: the 5560A CAN make it (12 A range, 3 Hz to 45 Hz, 5560A Product Specifications, ACI Specifications, printed p. 8), so only the 5522A is listed
    ('3-7', 14): {'5522A': '5522A: 3 A to 10.9999 A ac is specified 45 Hz to 5 kHz only (5522A Operators Manual, Detailed Specifications, AC current, printed p. 1-14); this point is at 40 Hz.'},
    ('3-8', 6): {'5522A': '5522A: the ac voltage output stops at 500 kHz (5522A Operators Manual, Detailed Specifications, AC voltage, printed p. 1-12); this point is at 1000 kHz. The manual uses a Fluke 271 function generator.',
                 '5560A': '5560A: the ac voltage output stops at 500 kHz (5560A Product Specifications, ACV Specifications, printed pp. 3-4); this point is at 1000 kHz. The manual uses a Fluke 271 function generator.'},
}


# ----------------------------------------------------------------------------------------------------------------------------------
def parse(text):
    """'-190.025 mV' / 'STD+0.046 ohm' -> (is_std, signed Decimal in display unit, decimals printed, unit)."""
    m = TOKEN.match(text.strip())
    if not m:
        raise ValueError(f'cannot read {text!r}')
    std, sign, number, unit = m.groups()
    if unit not in UNITS:
        raise ValueError(f'unknown unit in {text!r}')
    value = D(number)
    if sign == '-':
        value = -value
    return bool(std), value, len(number.split('.')[1]) if '.' in number else 0, unit


def base(text):
    """Base-unit Decimal of a '<number> <unit>' text (no STD)."""
    _std, value, _dec, unit = parse(text)
    return value * UNITS[unit][0]


def clean(value) -> float:
    return float(f'{float(value):.12g}')


def limit_pair(row_limits, nominal_base, std_relative, columns):
    """From the four printed strings: {period: (low_text, high_text)}; checks nothing."""
    out = {}
    for i, period in enumerate(PERIODS):
        out[period] = dict(high=row_limits[columns[i * 2]], low=row_limits[columns[i * 2 + 1]])
    return out


def to_base_limit(text, nominal):
    """Absolute limit (base units) from a printed text: STD +/- tol is relative to the nominal, otherwise absolute."""
    std, value, _dec, unit = parse(text)
    factor = UNITS[unit][0]
    return (nominal + value * factor) if std else value * factor


def half_unit(text):
    _std, _value, dec, unit = parse(text)
    return D(1).scaleb(-dec) / 2 * UNITS[unit][0]


def check_row(kind, nominal, rng, freq, limits, tol_for):
    """Problems (list of text) of one row's limits: (low, high) text per period against the formula; limits = {period: dict(low, high)}."""
    problems = []
    for period in PERIODS:
        tol = tol_for(period)
        for name, sign in (('high', 1), ('low', -1)):
            text = limits[period][name]
            used = to_base_limit(text, nominal)
            expected = nominal + sign * tol
            if abs(used - expected) > half_unit(text):
                problems.append((period, name, text, expected))
    return problems


def build_points():
    points, problems, unused_flags = [], [], set()
    seen_corr = set()
    tables = [('3-2', 'DCV', T32, '3-4'), ('3-3', 'ACV', T33, '3-5'), ('3-4', 'OHM4', T34, '3-6'), ('3-5', 'OHM2', T35, '3-7 / 3-8'),
              ('3-6', 'DCI', T36, '3-9 / 3-10'), ('3-7', 'ACI', T37, '3-10'), ('3-8', 'FREQ', T38, '3-11')]
    for table, kind, rows, page in tables:
        for number, (nom_text, rng_text, freq_text, printed) in enumerate(rows, start=1):
            key = (table, number)
            struct = STRUCT.get(key, {})
            nom_text, rng_text = struct.get('nominal', nom_text), struct.get('range', rng_text)
            freq_text = struct.get('frequency', freq_text)
            nominal, rng = base(nom_text), base(rng_text)
            freq = base(freq_text) if freq_text else None
            if kind == 'FREQ':                                  # the point's nominal is the applied frequency; the source level is 0.1 V
                amplitude, nominal, freq = nominal, freq, None
            else:
                amplitude = None
            is_zero = nominal == 0 and kind != 'FREQ'
            std_relative = any(parse(t)[0] for t in printed)
            printed_limits = {PERIODS[i // 2]: {} for i in range(4)}
            for i, text in enumerate(printed):
                printed_limits[PERIODS[i // 2]]['high' if i % 2 == 0 else 'low'] = text
            if 'unit' in struct:                                # printed "Hz" where kHz is meant: the unit column is corrected
                printed_limits = {p: {n: re.sub(r'(?<!k)Hz$', struct['unit'], t) for n, t in d.items()} for p, d in printed_limits.items()}
            used = {p: dict(d) for p, d in printed_limits.items()}
            flags = []
            for period, field, text, ckind, why in CORR.get(key, []):
                seen_corr.add((key, period, field))
                used[period][field] = text
                flags.append(dict(code=ckind, period=period, field=field, printed=printed_limits[period][field], used=text, why=why))
            if key in STRUCT:
                flags.append(dict(code='structure', why=struct['why']))
            if key in KEEP:
                flags.append(dict(code='tighter', why=KEEP[key]))
            rng_for = rng
            check_freq = freq if kind in ('ACV', 'ACI') else None
            tol_for = lambda period, k=kind, n=nominal, r=rng_for, f=check_freq: tolerance(k, n, r, f, period)    # noqa: E731
            if kind == 'FREQ':
                tol_for = lambda period, n=nominal, r=rng: tolerance('FREQ', n, r, None, period)                  # noqa: E731
            # 1. the limits USED must agree with the formula (except the kept, tighter ones)
            found = check_row(kind, nominal, rng, freq, used, tol_for)
            if key not in KEEP:
                for period, name, text, expected in found:
                    problems.append(f'Table {table} row {number}: the {period} {name} limit {text!r} is {to_base_limit(text, nominal)} but the specification gives {expected}')
            else:
                if not found:
                    problems.append(f'Table {table} row {number}: listed as tighter than the specification but it agrees with it')
            # 2. every correction must correct a printed limit that really disagrees with the formula
            printed_bad = {(p, n) for p, n, _t, _e in check_row(kind, nominal, rng, freq, printed_limits, tol_for)}
            for period, field, _text, _ckind, _why in CORR.get(key, []):
                if (period, field) not in printed_bad:
                    problems.append(f'Table {table} row {number}: the printed {period} {field} limit agrees with the specification, nothing to correct')
            point = dict(ref=f'T{table} #{number}', table=table, row=number, page=page, kind=kind, nominal=clean(nominal), range=clean(rng),
                         unit=UNITS[parse(nom_text.replace('ohm', 'ohm') if kind != 'FREQ' else '0.1 V')[3]][1] if kind != 'FREQ' else 'Hz',
                         frequency=clean(freq) if freq is not None else None)
            if kind == 'FREQ':
                point['amplitude'] = clean(amplitude)
            point['limits'] = {}
            for period in PERIODS:
                low = to_base_limit(used[period]['low'], nominal)
                high = to_base_limit(used[period]['high'], nominal)
                if low > high:
                    problems.append(f'Table {table} row {number}: {period} low {low} above high {high}')
                point['limits'][period] = dict(low=clean(low), high=clean(high))
            point['accuracy'] = {p: [str(x) for x in formula(kind, rng, freq if kind in ('ACV', 'ACI') else None, p)] for p in PERIODS}
            point['std_relative'] = std_relative
            if any(f['code'] != 'structure' for f in flags) or flags:
                point['printed_limits'] = printed_limits
                point['flags'] = flags
            if key in CAL_LIMITS:
                point['cal_limits'] = dict(CAL_LIMITS[key])
            points.append(point)
            point['_zero'] = is_zero
    for key in CORR:
        for period, field, *_rest in CORR[key]:
            if (key, period, field) not in seen_corr:
                problems.append(f'correction {key} {period} {field} was not applied')
    return points, problems


# ----------------------------------------------------------------------------------------------------------------------------------
SECTIONS = [
    ('ZERO_SHORT', 'Zero offset, shorted input', 'ZERO_SHORT', '3-4 to 3-8',
     'Fit the low-thermal 4-wire short across INPUT HI / LO and SENSE HI / LO (Table 3-1, Fluke PN 2653346). The calibrator is in STANDBY and is not used as a zero source.'),
    ('ZERO_OPEN', 'Zero offset, open current input', 'ZERO_OPEN', '3-9 / 3-10',
     'Leave the current input (mA terminal, 10 A terminal) OPEN with nothing connected. The calibrator is in STANDBY.'),
    ('DCV', 'DC volts', 'VOLT', '3-4', 'Calibrator voltage output to INPUT HI / LO (Figure 3-1).'),
    ('ACV', 'AC volts', 'VOLT', '3-5', 'Calibrator voltage output to INPUT HI / LO (Figure 3-1).'),
    ('FREQ', 'Frequency', 'VOLT', '3-11', 'Calibrator ac voltage output (0.1 V) to INPUT HI / LO.'),
    ('OHM4', '4-wire ohms', 'OHM4', '3-6', 'Calibrator output to INPUT HI / LO and calibrator SENSE to the meter SENSE 4W HI / LO (Figure 3-2). Calibrator external sense ON.'),
    ('OHM2', '2-wire ohms', 'OHM2', '3-7 / 3-8', 'Calibrator output to INPUT HI / LO, sense to INPUT HI / LO (Figure 3-3). Calibrator external sense ON and 2-wire compensation ON.'),
    ('DCI', 'DC current', None, '3-9 / 3-10', 'See each point: Figure 3-4 (mA terminal, 10 A terminal for the 2 A range) and Figure 3-5 (10 A terminal).'),
    ('ACI', 'AC current', None, '3-10', 'See each point: Figure 3-4 (mA terminal, 10 A terminal for the 2 A range) and Figure 3-5 (10 A terminal).'),
]


def classify(p):
    """(section id, group, terminal, source, input) for a point."""
    kind, zero = p['kind'], p.pop('_zero')
    cur_group = (lambda: 'IMA' if p['range'] <= 0.2 else 'I2A' if p['range'] == 2 else 'I10A')
    terminal = 'MA' if kind in ('DCI', 'ACI') and p['range'] <= 0.2 else '10A' if kind in ('DCI', 'ACI') else 'INPUT'
    if zero:
        if kind == 'DCI':
            return 'ZERO_OPEN', 'ZERO_OPEN', terminal, 'none', 'open'
        return 'ZERO_SHORT', 'ZERO_SHORT', 'INPUT', 'none', 'short'
    if kind in ('DCI', 'ACI'):
        return kind, cur_group(), terminal, 'calibrator', None
    return {'DCV': 'DCV', 'ACV': 'ACV', 'FREQ': 'FREQ', 'OHM4': 'OHM4', 'OHM2': 'OHM2'}[kind], {'DCV': 'VOLT', 'ACV': 'VOLT', 'FREQ': 'VOLT', 'OHM4': 'OHM4', 'OHM2': 'OHM2'}[kind], 'INPUT', 'calibrator', None


def build_spec():
    points, problems = build_points()
    if problems:
        raise SystemExit('Tables 3-2 to 3-8 disagree with the specification (printed pp. 1-10 to 1-14):\n  ' + '\n  '.join(problems))
    by_section = {s[0]: [] for s in SECTIONS}
    for p in points:
        section, group, terminal, source, inp = classify(p)
        p.update(section=section, group=group, terminal=terminal, source=source, input=inp)
        by_section[section].append(p)
    order = ('ZERO_SHORT', 'ZERO_OPEN', 'DCV', 'ACV', 'FREQ', 'OHM4', 'OHM2', 'DCI', 'ACI')
    for sid, plist in by_section.items():                   # the zero sections list DC volts, then 4-wire ohms, then 2-wire ohms (table order)
        plist.sort(key=lambda p: (order.index(p['kind'] if p['kind'] in order else 'DCV'), p['table'], p['row'])) if sid in ('ZERO_SHORT',) else None
    sections = []
    for sid, title, group, page, setup in SECTIONS:
        sections.append(dict(id=sid, title=title, group=group, page=page, setup=setup, points=by_section[sid]))
    for sec in sections:
        for p in sec['points']:
            p.pop('section', None)
    total = sum(len(s['points']) for s in sections)
    return dict(
        schema=1, kind='bench-dmm-band', model=MODEL, periods=list(PERIODS), default_period='1y', interface='rs232',
        options=dict(hv_threshold_v=100, report_title='Calibration Data', warm_up_minutes=30),
        source=dict(
            document='Fluke 8808A Digital Multimeter, Calibration Manual (56 pp.), chapter 3 "Performance Verification and Calibration"',
            pages='printed pp. 3-3 (Table 3-1, required equipment), 3-4 to 3-11 (Tables 3-2 to 3-8 and Figures 3-1 to 3-5); accuracy specifications pp. 1-10 to 1-14',
            cite='Fluke 8808A Calibration Manual, Tables 3-2 to 3-8, pp. 3-4 to 3-11 (limits as printed except the corrections listed in the point flags)',
            limits='Manufacturer limits, 90 days and 1 year, as printed (rounded) in Tables 3-2 to 3-8; typographical errors corrected from the specification formula, see the point flags',
            report_note=('Limits are those of the manufacturer\'s Tables 3-2 to 3-8 (Fluke 8808A Calibration Manual, pp. 3-4 to 3-11), 90-day or 1-year as chosen, as printed '
                         '(the manual rounds each limit to the printed number of digits). Printed typographical errors were corrected from the manual\'s own accuracy '
                         'specification (pp. 1-10 to 1-14); each correction is recorded with the point. Resistance limits are the calibrator setting +/- the printed tolerance.'),
            note=(f'Tables 3-2 to 3-8, {total} points: DC volts 17, AC volts 28, 4-wire ohms 6, 2-wire ohms 14, DC current 18, AC current 16, frequency 6 (the zero-offset points of each '
                  'table are run first, with the input shorted or, for current, open). Limits are the printed 90-day or 1-year limits; several typographical errors in the printed tables '
                  'were corrected from the specification formula (see the point details). The manual names a Fluke 5700A with a 5725A amplifier and a Fluke 271 function generator; this '
                  'procedure drives a Fluke 5522A or 5560A. Points the selected calibrator cannot make (5522A: 750 V ac above 10 kHz, 10 A ac at 40 Hz, 1000 kHz; 5560A: 750 V ac above 10 kHz, 1000 kHz) are measured with a standard '
                  'you connect. The meter must be warmed up for half an hour; the specification is valid in the 5-1/2 digit (slow) rate only.')),
        models={MODEL: dict(name='Fluke 8808A', brand='Fluke', model_note='Fluke 8808A 5-1/2 digit bench multimeter, RS-232 only (no IEEE-488, no USB)')},
        sections=sections)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=True), encoding='utf-8')
    counts = {s['id']: len(s['points']) for s in spec['sections']}
    flagged = [p['ref'] for s in spec['sections'] for p in s['points'] if p.get('flags')]
    print('wrote', OUT, sum(counts.values()), 'points', counts)
    print('points with flags:', ', '.join(flagged))


if __name__ == '__main__':
    main()
