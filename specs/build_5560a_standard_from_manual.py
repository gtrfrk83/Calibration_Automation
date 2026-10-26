"""Builds specs/standards/fluke_5560a_standard.json from the Fluke 5560A Product Specifications (December 2022, Rev. 8, 6/26, English).

    python specs/build_5560a_standard_from_manual.py            # writes specs/standards/fluke_5560a_standard.json (idempotent: same bytes every run)

Every number below was transcribed by eye from RENDERED PAGE IMAGES (pdftoppm -r 110, then a second reading of each table from a 160 dpi render) of
'5560_Specs.pdf' (31 pages), never from extracted text (micro and ohm signs get corrupted).  Page numbers: the cover is PDF page 1, so printed page n is
PDF page n + 2.  Rows carry the PDF page in 'page' (the Standards Specs / spec editor 'p.N'); notes, problems and the diff report quote the printed page.
Values are SI base units; ppm (the document's 'uV/V') and per cent of output become 'rel', the floors become 'abs'.  Nothing is guessed: whatever the
document leaves open, or the schema cannot hold, is written to 'problems'.

What is stored (owner decisions, 2026-10-25):
  * the 95 % confidence column (k = 2, divisor 2), as the previous sheet and NOTES.md 'Confidence level rule' have it; the 99 % column is not stored.
  * the 90 day and 1 yr columns ('90 day', '1 yr', the labels of the 3458A / 5520A / 5522A sheets).  The document's 2 y columns are NOT loaded.  Each row lists
    '1 yr' first and '90 day' second (the 5520A / 5522A / 3458A sheets list '90 day' first; three existing tests read specs[0] of a 5560A row as the 1 yr figure).
    The default period of a standard stays '1 yr' (specmanager standards.period / StandardSpec.lookup(period=None)): a 90 day figure is used only when
    a caller passes period='90 day'.
  * the floor column that is valid with an ohms zero within 24 h (resistance) - the 14 d zero floors are not stored.
Tables loaded (printed pages):
  p.2   DCV                              p.12  Resistance (4-wire; the 2-wire rows are DERIVED, see problems)
  p.3-4 ACV                              p.13  Capacitance
  p.6   DCI                              p.14  Inductance
  p.7-8 ACI                              p.15-17 TC Specifications: Types B C D E G J K L N R S T U BP XK (source rows; J and K input rows kept from the old sheet)
  p.10  Frequency (only a 2-YEAR absolute uncertainty is printed, see problems)   p.18-20 RTD Specifications (Cu 10 / 50 / 100, Ni 120, Pt 100 (385 / 3916 / 3926), Pt 200, Pt 500, Pt 1000)
  p.24  Duty cycle uncertainty (square wave)
Printed but NOT loaded (listed in 'problems' and in specs/fluke_5560a_spec_check.md): the 2 y columns; the 99 % columns; every 'Operating Characteristics'
table (stability, noise, distortion, resolution, compliance, load limits); ACI compliance adders; resistance floor scaling for currents outside the specified
range and the 14 d zero floors; capacitance / inductance COMP adders and the inductance frequency adder; Phase; AC / DC power; harmonics; ACV extended
bandwidth; ACV and ACI square wave accuracy; ACV DC offset; Aux voltage (DC, AC sine, AC square); TC voltage source / measure in linear modes; the 5560A with
52120A current specifications and their operating characteristics; frequency / dual output limit tables.
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

OUT = HERE / 'standards' / 'fluke_5560a_standard.json'
PDF_OFFSET = 2          # printed page n  ->  PDF page n + 2 (the cover is PDF page 1)
BUILT = '2026-10-25T00:00:00'        # fixed on purpose: the builder must write the same bytes on every run
PERIODS = ('1 yr', '90 day')         # stored order; the first is the default period of the standard

PREFIX = {'p': D('1e-12'), 'n': D('1e-9'), 'u': D('1e-6'), 'm': D('1e-3'), '': D(1), 'k': D('1e3'), 'M': D('1e6')}


def P(printed):
    return printed + PDF_OFFSET


# ------------------------------------------------------------------------------------------------------------ number helpers
def qty(text):
    """'0.8uV' / '3.5mV' / '2.5kOhm' / '4pF' -> (Decimal value in SI base unit, base unit)."""
    for base in ('Ohm', 'degC', 'V', 'A', 'F', 'H'):
        if text.endswith(base):
            num, pre = text[:-len(base)], ''
            while num and not (num[-1].isdigit() or num[-1] == '.'):
                pre, num = num[-1] + pre, num[:-1]
            return D(num) * PREFIX[pre], base
    raise ValueError(text)


def spec(period, rel, floor=None, rel_unit='ppm', abs_unit_text=None):
    """One parsed specification.  `rel` printed as ppm of output (rel_unit 'ppm', the document's uV/V) or per cent of output ('%'); `floor` like '0.8uV'.
    Built through specmanager.parse_spec (so the fields are exactly what the other sheets hold), then the numbers are replaced by the exact decimal
    value (no float artefacts such as 0.00010999999999999999) after checking that they agree."""
    body = f'{rel} {rel_unit} I.V.' if rel is not None else ''
    value = D(0)
    base = ''
    if floor:
        value, base = qty(floor)
        m = re.match(r'^(\d+(?:\.\d+)?)(\D.*)$', floor)
        nice = f'{m.group(1)} {m.group(2)}'
        body = (body + ' + ' if body else '') + nice
    raw = f'[{period}] Accuracy: +/-({body})'
    s = sm.parse_spec(raw)
    assert 'error' not in s, raw
    exact_rel = float(D(str(rel)) * (D('1e-6') if rel_unit == 'ppm' else D('1e-2'))) if rel is not None else 0.0
    exact_abs = float(value)
    assert abs(s['rel'] - exact_rel) <= 1e-12 * max(1.0, abs(exact_rel)) and abs(s['abs'] - exact_abs) <= 1e-9 * max(abs(exact_abs), 1e-30), raw
    s['rel'], s['abs'] = exact_rel, exact_abs
    s['unit'] = s['unit'] or (base if base else '')
    return s


def specs_for(cols, floor=None, rel_unit='ppm'):
    """cols = (90 d, 1 y) of the 95 % column -> [1 yr spec, 90 day spec]."""
    d90, d1y = cols
    return [spec('1 yr', d1y, floor, rel_unit), spec('90 day', d90, floor, rel_unit)]


def si_text(v, unit):
    v = float(v)
    if v == 0:
        return f'0 {unit}'
    for div, pre in ((1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p')):
        if abs(v) >= div * (1 - 1e-9):
            return f'{v / div:.10g} {pre}{unit}'
    return f'{v:g} {unit}'


def prm(lo, hi, unit, text, notes=()):
    return dict(tag='', lo=float(lo), hi=float(hi), unit=unit, text=text, annot='', notes=list(notes))


def entry(fname, label, page, amp, unit, freq=None, specs=(), notes=(), qualifiers=()):
    params = [prm(amp[0], amp[1], unit, f'{si_text(amp[0], unit)} to {si_text(amp[1], unit)}', notes)]
    if freq:
        params.append(prm(freq[0], freq[1], 'Hz', f'{si_text(freq[0], "Hz")} to {si_text(freq[1], "Hz")}'))
    for q in qualifiers:
        params.append(dict(tag=q[0], lo=float(q[1]), hi=float(q[2]), unit=q[3], text=f'[{q[0]}] {q[1]} {q[3]} to {q[2]} {q[3]}', annot='', notes=[]))
    r = dict(label=label, page=page, params=params, specs=list(specs), raw_other=[])
    r.update(sm.analyse_range(fname, label, params))
    return r


def band_label(rng, lo, hi):
    """'12mV @ 3 - 5 Hz', '12mV @ 10 Hz - 20 kHz', '1.2V @ 40.01 - 20 kHz'... (the old sheet's wording, made regular)"""
    def split(f):
        return (f / 1e3, 'kHz') if f >= 1e3 and f % 1e3 == 0 else (f, 'Hz')
    (a, ua), (b, ub) = split(lo), split(hi)
    if ua == ub:
        return f'{rng} @ {a:g} - {b:g} {ua}'
    return f'{rng} @ {a:g} {ua} - {b:g} {ub}'


# ------------------------------------------------------------------------------------------------------------ notes (ids are file-wide)
NOTES = {
    1: 'Confidence level (printed p.1): the document prints 99 % (k = 2.58) and, in some cases, 95 % (k = 2) columns at 90 d, 1 y and 2 y; Fluke guarantees performance to the 99 % level. '
       'This sheet stores the 95 % column, divisor 2 (NOTES.md "Confidence level rule"), for the 90 day and 1 yr periods only; the 99 % and 2 y columns are not loaded.',
    2: 'Conditions (printed pp.1-2): valid after a 30 minute warm-up or twice the time the product was off; calibration temperature tcal 15 degC to 35 degC; '
       'temperature coefficient outside tcal +/-5 degC is 10 % of the stated specification per degC.  The specifications include stability, temperature, humidity, linearity, line and load regulation and the reference standard uncertainty.',
    3: 'Range limits (printed p.2): for all functions the maximum value of each range is the range nominal (e.g. 12.000 000 V on the 12 V dc range).  Value bands on this sheet run from the previous range top to the range nominal (ac) or +/- the nominal (dc).',
    4: 'DCV (printed p.2): External Sense is applicable for the 1.2 V and 12 V ranges; it is also available on the 120 V range but performance is unspecified.',
    5: 'DCV 120 mV floor (printed p.2, footnote [2]): in the DCP function, or after extended periods of operation in DCI, ACI or ACP, the 120 mV range floor may increase up to 4 uV; it recovers to the specified 0.8 uV within 10 minutes after leaving the DCP, DCI, ACI or ACP function.',
    6: 'ACV (printed p.3): External Sense is applicable for the 1.2 V, 12 V and 120 V ranges below 100 kHz.',
    7: 'ACV operating characteristics (printed p.5): range lock is unavailable for ACV; minimum output for the 12 mV range is 1 mV; maximum load capacitance is 500 pF, subject to the maximum burden current limits.',
    8: 'ACV 120 V range, 100 kHz to 300 kHz (printed p.4, footnote [1]): 70 V max.',
    9: 'DCI (printed p.7): range lock is available in all ranges; maximum inductive load 400 uH for all ranges; 8 kohm maximum resistive load for specified performance.  ACI (printed p.9): range lock is unavailable; maximum inductive load 400 uH at frequencies below 1 kHz.',
    10: 'ACI 120 uA range, 45 Hz to 1 kHz (printed p.8, footnote [1]): the floor is 100 nA (not 10 nA) when the output frequency is within 2 Hz of the line frequency.  Minimum ACI output for the 120 uA range is 10 uA.',
    11: 'ACI 12 A range, 3 Hz to 45 Hz and 45 Hz to 1 kHz (printed p.8, footnote [2]): the floor is 2 mA for the ACP function with an output voltage above 120 V.',
    12: 'ACI accuracy applies for compliance voltages up to 1 V rms; for higher compliance voltages "accuracy specification adders apply" (printed pp.9-10 table: compliance adder in uA/V or the maximum resistive load, compliance limits, distortion / noise).  NOT stored (the schema has no field).  Example, 12 A range 3 Hz to 45 Hz: 3600 uA/V.',
    13: 'Resistance (printed pp.11-12): continuously variable 0 ohm to 1200 Mohm.  The specifications apply for four-wire compensation only.  The floor column stored is the 24 h zero (+/-1 degC) floor; the 14 d zero (+/-5 degC) floors (10 mohm, 15 mohm, 20 mohm, 200 mohm, 1 ohm, 10 ohm, 150 ohm, 2.5 kohm, 100 kohm) are NOT stored.',
    14: 'Resistance, 2-wire (printed p.11): for COMP OFF or two-wire COMP, 5 uV divided by the stimulus current in amps is added to the floor (example: 1 kohm at 1 mA: 0.002 ohm + 0.005 ohm = 0.007 ohm).  The 2-wire floors on this sheet are COMPUTED by the builder, floor + 5 uV / (lowest specified stimulus current of the range, printed p.12); the document prints no separate 2-wire table.',
    15: 'Resistance operating characteristics (printed p.12): specified stimulus current ranges (12 ohm 4 mA - 30 mA, 120 ohm 1 mA - 13 mA, 1.2 kohm 1 mA - 10 mA, 12 kohm 100 uA - 1.3 mA, 120 kohm 10 uA - 130 uA, 1.2 Mohm 1 uA - 13 uA, 12 Mohm 100 nA - 1.3 uA, 120 Mohm 25 nA - 1 uA, 1200 Mohm 2.5 nA - 100 nA); '
        'below them the floor becomes 2.5 x floor x Imin / Iactual; above them (up to the maximum current) the specification becomes spec x (Iactual / Ispec max)^0.5 + floor.  Not stored.  Max burden voltage 13 V.',
    16: 'Capacitance (printed p.13): output continuously variable 0 pF to 120 mF, SPECIFIED range 200 pF to 120 mF.  The specifications apply for COMP OFF; for four-wire or two-wire COMP add 15 pF for all ranges plus 0.03 % of output (1.2 uF range), 0.05 % (120 uF), 0.04 % (1.2 mF), 0.07 % (12 mF), 0.21 % (120 mF) - not stored.  Applies to dc charge / discharge meters and ac RCL meters (frequency limits per range on printed p.13, not stored).',
    17: 'Capacitance floors (printed p.13, footnotes): [1] 1.2 nF range: 2 pF for relative humidity within 15 % of the humidity at adjust; [2] 1.2 nF and 12 nF: after storage or operation at high humidity a drying-out period of at least 2 weeks can be required; [3] 120 uF and 12 mF: after storage outside the operating temperature range a relaxation period of at least 2 weeks near tcal may be required.',
    18: 'Inductance (printed p.14): output 13 uH to 120 H.  The specifications apply for four-wire COMP and at the specified frequency of each range (120 uH and 1.2 mH 1 kHz, 12 mH 110 Hz, 120 mH 100 Hz, 1.2 H 10 Hz, 12 H 3 Hz, 120 H 2 Hz); four-wire COMP is required for 120 uH and 1.2 mH.  '
        'COMP OFF / two-wire COMP adders (500 uH on 12 mH, 400 uH on 120 mH, 0.4 mH + 0.04 % on 1.2 H, 0.3 mH + 0.04 % on 12 H, 0.3 mH + 0.06 % on 120 H) and the frequency-adder table (other frequencies) are NOT stored.',
    19: 'Thermocouple (printed p.15): source specifications tcal +/-5 degC; they do NOT include thermocouple error; sourcing currents above 3 A may require a cooling-off time of up to 4x the sourcing time (max 20 min) for less than 0.01 degC additional error; resolution 0.01 degC; temperature standard ITS-90 or IPTS-68 selectable.  '
        'The document prints the 90 d / 1 y / 2 y columns once per thermocouple type; it prints no separate measure (input) table: the J and K input rows are kept from the previous sheet with the same figures (unverified direction).',
    20: 'Thermocouple temperature standard per type (printed pp.15-17): B, J, K, N, R, S, T: ITS-90 per NIST M.175 / IEC 60584-1:2013, IPTS-68 per IEC 584-1 (1977); C: W5Re/W26Re, ITS-90 per ASTM E230/E230M-17, IEC 60584-1:2013, ASTM E988-96, IPTS-68 per ASTM E988-84; D: W3Re/W25Re, ITS-90 per ASTM E1751-15, ASTM E988-96; '
        'E and G: the document prints "W/W26Re; ITS-90 per ASTM E1751-15; IPTS-68 per Hoskins Mfg. Co. (1974)" against BOTH (for Type E this looks like a copy of the Type G text: E is not a tungsten-rhenium type; stored as printed, owner to confirm if it matters); L, U: IPTS-68 per DIN 43710-1985; BP: ITS-90 per IEC 60584-1:2013, GOST R 8.585-2001; XK: ITS-90 per GOST R 8.585-2001.',
    21: 'RTD (printed p.18): temperature standard ITS-90 or IPTS-68 selectable; the specifications do NOT include sensor accuracy; they apply within 24 hours and +/-1 degC of the ohms zero adjustment and with COMP OFF at the output terminals or with two-wire and four-wire compensation; see Resistance Operating Characteristics for the stimulus current limits; resolution 0.001 degC; tcal +/-5 degC.',
    22: 'RTD standards (printed p.20, notes): [1] ITS-90 per Resistance Thermometry - MINCO Application Aid No. 18 (Cu 10, Ni 120, Pt 100 (3926)); [2] ITS-90 per GOST 6651-2009 (Cu 50, Cu 100); [3] ITS-90 per IEC 60751:2008, ASTM E1137-08; IPTS-68 per IEC 751:1983, DIN 43760 (Pt 100 (385), Pt 200, Pt 500, Pt 1000); [4] IPTS-68 per JIS C1604:1981 (Pt 100 (3916)).',
    23: 'Frequency (printed p.10): the only accuracy printed is "2 Year Absolute Uncertainty +/-2.5 uHz/Hz" (jitter 100 ns p-p).  With REF CLK set to external the frequency uncertainty is the uncertainty of the external 10 MHz clock (square or pulse, positive peak 3 V to 5 V, within +/-20 uHz/Hz of 10 MHz).  No 90 day or 1 yr figure is printed.  '
        'Frequency resolution (not stored): 0.01 Hz (0.01 Hz - 119.99 Hz), 0.1 Hz (120.0 Hz - 1199.9 Hz), 1 Hz (1.200 - 11.999 kHz), 10 Hz (12.00 - 119.99 kHz), 100 Hz (120.0 - 1199.9 kHz), 1 kHz (1.200 - 2.000 MHz).',
    24: 'Duty cycle (printed p.24, ACV Square Wave Characteristics; frequency 0.01 Hz to 100 kHz, duty range 1 % to 99 %): uncertainty +/-(0.02 % of period + 100 ns) at 50 % duty, +/-(0.05 % of period + 100 ns) for duty cycles from 10 % to 90 %; none is printed for 1 % to 10 % and 90 % to 99 %.  '
        'Stored in duty-cycle per cent (%DC) at the 1000 Hz of the previous sheet: 0.02 % + 100 ns x 1 kHz (0.01 %DC) = 0.03 %DC; 0.05 % + 0.01 %DC = 0.06 %DC.  The 100 ns term depends on frequency, which the schema cannot hold, so the figures are valid at 1 kHz only.',
}

# ------------------------------------------------------------------------------------------------------------ data (95 % column: "90 d", "1 y")
DCV = [   # (label, range top V, (90d, 1y) ppm, floor, notes)    printed p.2
    ('120mV', '0.12', (7.8, 9.3), '0.8uV', [4, 5]),
    ('1.2V', '1.2', (5.1, 6.4), '1uV', [4]),
    ('12V', '12', (5.0, 6.2), '10uV', [4]),
    ('120V', '120', (7.2, 8.5), '100uV', [4]),
    ('1020V', '1020', (7.2, 8.5), '1000uV', []),
]
# External Sense (note 4) applies to 1.2 V and 12 V; the 120 mV floor footnote (note 5) to 120 mV only.  Fix the per-row notes explicitly:
DCV_NOTES = {'120mV': [5], '1.2V': [4], '12V': [4], '120V': [], '1020V': []}

ACV_RANGES = [('12mV', 0.0, 0.012), ('120mV', 0.012, 0.12), ('1.2V', 0.12, 1.2), ('12V', 1.2, 12.0), ('120V', 12.0, 120.0), ('330V', 120.0, 330.0), ('1020V', 330.0, 1020.0)]
ACV_PAGE = {'12mV': 3, '120mV': 3, '1.2V': 4, '12V': 4, '120V': 4, '330V': 4, '1020V': 4}
# range -> [(f lo, f hi, (90 d, 1 y) ppm, floor, note ids)]       printed pp.3-4
ACV = {
    '12mV': [(3, 5, (1600, 1900), '7uV'), (5, 10, (540, 680), '7uV'), (10, 20e3, (93, 120), '6uV'), (20e3, 50e3, (230, 290), '6uV'),
             (50e3, 100e3, (930, 1200), '15uV'), (100e3, 300e3, (5000, 6200), '30uV'), (300e3, 500e3, (5000, 6200), '30uV')],
    '120mV': [(3, 5, (1600, 1900), '7uV'), (5, 10, (540, 680), '7uV'), (10, 20e3, (89, 110), '6uV'), (20e3, 50e3, (220, 270), '8uV'),
              (50e3, 100e3, (500, 620), '20uV'), (100e3, 300e3, (1200, 1600), '30uV'), (300e3, 500e3, (1200, 1600), '30uV')],
    '1.2V': [(3, 5, (1600, 1900), '75uV'), (5, 10, (540, 680), '70uV'), (10, 40, (89, 110), '60uV'), (40.01, 20e3, (89, 110), '8uV'),
             (20e3, 50e3, (190, 230), '14uV'), (50e3, 100e3, (430, 540), '40uV'), (100e3, 300e3, (1200, 1500), '80uV'), (300e3, 500e3, (1200, 1500), '80uV')],
    '12V': [(3, 5, (1600, 1900), '750uV'), (5, 10, (540, 680), '750uV'), (10, 40, (89, 110), '350uV'), (40.01, 20e3, (89, 110), '50uV'),
            (20e3, 50e3, (190, 230), '50uV'), (50e3, 100e3, (430, 540), '125uV'), (100e3, 300e3, (1200, 1600), '600uV'), (300e3, 500e3, (1200, 1600), '600uV')],
    '120V': [(3, 5, (1600, 1900), '7.5mV'), (5, 10, (540, 680), '7.5mV'), (10, 40, (89, 110), '3.5mV'), (40.01, 20e3, (89, 110), '500uV'),
             (20e3, 50e3, (190, 230), '500uV'), (50e3, 100e3, (430, 540), '1.25mV'), (100e3, 300e3, (1200, 1600), '20mV')],
    '330V': [(3, 5, (1600, 1900), '75mV'), (5, 10, (540, 680), '75mV'), (10, 20e3, (89, 110), '8mV'), (20e3, 50e3, (190, 230), '8mV'),
             (50e3, 100e3, (930, 1200), '12.5mV')],
    '1020V': [(3, 5, (1600, 1900), '75mV'), (5, 10, (540, 680), '75mV'), (10, 10e3, (89, 110), '80mV')],
}
ACV_NOTES = {('120V', 100e3): [8]}      # footnote [1] on the 100 kHz - 300 kHz row of the 120 V range

DCI = [   # (label, range top A, (90 d, 1 y) ppm, floor)       printed p.6
    ('120µA', '0.00012', (78, 97), '6nA'), ('1.2mA', '0.0012', (62, 78), '15nA'), ('12mA', '0.012', (62, 78), '80nA'), ('120mA', '0.12', (62, 78), '800nA'),
    ('1.2A', '1.2', (100, 120), '10uA'), ('3.1A', '3.1', (190, 230), '150uA'), ('12A', '12', (190, 230), '250uA'), ('30.2A', '30.2', (620, 780), '500uA'),
]

ACI_RANGES = [('120µA', 0.0, 0.00012), ('1.2mA', 0.00012, 0.0012), ('12mA', 0.0012, 0.012), ('120mA', 0.012, 0.12), ('1.2A', 0.12, 1.2),
              ('3.1A', 1.2, 3.1), ('12A', 3.1, 12.0), ('30.2A', 12.0, 30.2)]
ACI_PAGE = {'120µA': 7, '1.2mA': 7, '12mA': 7, '120mA': 8, '1.2A': 8, '3.1A': 8, '12A': 8, '30.2A': 8}
ACI = {   # printed pp.7-8:  (f lo, f hi, (90 d, 1 y) ppm, floor)
    '120µA': [(3, 45, (160, 190), '10nA'), (45, 1e3, (160, 190), '10nA'), (1e3, 5e3, (160, 190), '10nA'), (5e3, 10e3, (930, 1200), '40nA'), (10e3, 30e3, (3100, 3900), '1uA')],
    '1.2mA': [(3, 45, (160, 190), '100nA'), (45, 1e3, (160, 190), '100nA'), (1e3, 5e3, (160, 190), '100nA'), (5e3, 10e3, (930, 1200), '100nA'), (10e3, 30e3, (3100, 3900), '5uA')],
    '12mA': [(3, 45, (160, 190), '1uA'), (45, 1e3, (160, 190), '1uA'), (1e3, 5e3, (160, 190), '1uA'), (5e3, 10e3, (930, 1200), '1uA'), (10e3, 30e3, (3100, 3900), '10uA')],
    '120mA': [(3, 45, (160, 190), '10uA'), (45, 1e3, (93, 120), '5uA'), (1e3, 5e3, (160, 190), '8uA'), (5e3, 10e3, (930, 1200), '10uA'), (10e3, 30e3, (3100, 3900), '100uA')],
    '1.2A': [(3, 45, (160, 190), '100uA'), (45, 1e3, (160, 190), '50uA'), (1e3, 5e3, (160, 190), '80uA'), (5e3, 10e3, (1600, 1900), '300uA'), (10e3, 30e3, (3100, 3900), '300uA')],
    '3.1A': [(3, 45, (230, 290), '500uA'), (45, 1e3, (190, 230), '300uA'), (1e3, 5e3, (230, 290), '300uA'), (5e3, 10e3, (1600, 1900), '500uA')],
    '12A': [(3, 45, (230, 290), '1mA'), (45, 1e3, (190, 230), '500uA'), (1e3, 5e3, (230, 290), '800uA'), (5e3, 10e3, (1600, 1900), '1mA')],
    '30.2A': [(3, 45, (620, 780), '10mA'), (45, 1e3, (430, 540), '8mA'), (1e3, 5e3, (3100, 3900), '8mA')],
}
ACI_NOTES = {('120µA', 45): [10], ('12A', 3): [11], ('12A', 45): [11]}

# resistance (printed p.12): (label, range top ohm, (90 d, 1 y) ppm, 24 h zero floor, lowest specified stimulus current)
OHM = [
    ('12 Ohm', '12', (17, 19), '1mOhm', '4mA'), ('120 Ohm', '120', (17, 19), '1mOhm', '1mA'), ('1.2 kOhm', '1200', (17, 19), '2mOhm', '1mA'),
    ('12 kOhm', '12000', (17, 19), '20mOhm', '100uA'), ('120 kOhm', '120000', (17, 19), '200mOhm', '10uA'), ('1.2 MOhm', '1200000', (17, 19), '2Ohm', '1uA'),
    ('12 MOhm', '12000000', (22, 27), '30Ohm', '100nA'), ('120 MOhm', '120000000', (300, 330), '2.5kOhm', '25nA'), ('1200 MOhm', '1200000000', (3000, 3100), '100kOhm', '2.5nA'),
]

CAP = [   # printed p.13: (label, range top F, (90 d, 1 y) per cent of output, floor)
    ('1.2nF', '1.2e-9', ('0.09', '0.09'), '4pF', [17]), ('12nF', '1.2e-8', ('0.09', '0.09'), '5pF', [17]), ('120nF', '1.2e-7', ('0.09', '0.10'), '30pF', []),
    ('1.2 µF', '1.2e-6', ('0.09', '0.10'), '300pF', []), ('12 µF', '1.2e-5', ('0.09', '0.10'), '3nF', []), ('120 µF', '1.2e-4', ('0.10', '0.12'), '25nF', [17]),
    ('1.2 mF', '1.2e-3', ('0.17', '0.19'), '250nF', []), ('12 mF', '1.2e-2', ('0.17', '0.19'), '3uF', [17]), ('120 mF', '1.2e-1', ('0.35', '0.39'), '30uF', []),
]
IND = [   # printed p.14: (label, range top H, (90 d, 1 y) per cent of output, floor)
    ('120µH', '1.2e-4', ('0.14', '0.16'), '200nH'), ('1.2mH', '1.2e-3', ('0.09', '0.09'), '1uH'), ('12mH', '1.2e-2', ('0.09', '0.09'), '10uH'),
    ('120mH', '1.2e-1', ('0.09', '0.09'), '100uH'), ('1.2H', '1.2', ('0.10', '0.12'), '1mH'), ('12H', '12', ('0.14', '0.16'), '10mH'), ('120H', '120', ('0.17', '0.19'), '100mH'),
]

# thermocouples (printed pp.15-17): type -> (printed page, [(lo degC, hi degC, 90 d, 1 y)])  95 % column, degC
TC = {
    'B': (15, [(600, 800, '0.27', '0.34'), (800, 1000, '0.21', '0.26'), (1000, 1550, '0.19', '0.23'), (1550, 1820, '0.20', '0.26')]),
    'C': (15, [(0, 150, '0.16', '0.19'), (150, 650, '0.13', '0.16'), (650, 1000, '0.16', '0.20'), (1000, 1800, '0.28', '0.35'), (1800, 2315, '0.49', '0.61')]),
    'D': (15, [(0, 150, '0.16', '0.19'), (150, 650, '0.13', '0.16'), (650, 1000, '0.16', '0.20'), (1000, 1800, '0.27', '0.34'), (1800, 2315, '0.48', '0.61')]),
    'E': (15, [(-250, -150, '0.25', '0.31'), (-150, -25, '0.08', '0.11'), (-25, 350, '0.07', '0.09'), (350, 650, '0.10', '0.12'), (650, 1000, '0.12', '0.16')]),
    'G': (15, [(0, 150, '0.31', '0.39'), (150, 650, '0.2', '0.26'), (650, 1000, '0.16', '0.20'), (1000, 1800, '0.26', '0.33'), (1800, 2315, '0.48', '0.60')]),
    'J': (16, [(-210, -100, '0.15', '0.19'), (-100, -30, '0.08', '0.10'), (-30, 150, '0.07', '0.09'), (150, 760, '0.09', '0.11'), (760, 1200, '0.12', '0.16')]),
    'K': (16, [(-200, -100, '0.17', '0.22'), (-100, -25, '0.08', '0.10'), (-25, 120, '0.07', '0.09'), (120, 1000, '0.13', '0.16'), (1000, 1372, '0.22', '0.27')]),
    'L': (16, [(-200, -100, '0.19', '0.24'), (-100, 800, '0.12', '0.16'), (800, 900, '0.07', '0.09')]),
    'N': (16, [(-200, -100, '0.20', '0.26'), (-100, -25, '0.09', '0.12'), (-25, 120, '0.08', '0.10'), (120, 410, '0.07', '0.09'), (410, 1300, '0.12', '0.16')]),
    'R': (16, [(0, 250, '0.32', '0.40'), (250, 400, '0.18', '0.23'), (400, 1000, '0.17', '0.21'), (1000, 1767, '0.21', '0.26')]),
    'S': (16, [(0, 250, '0.26', '0.33'), (250, 1000, '0.19', '0.24'), (1000, 1400, '0.20', '0.25'), (1400, 1767, '0.26', '0.32')]),
    'T': (17, [(-250, -150, '0.37', '0.47'), (-150, 0, '0.13', '0.16'), (0, 120, '0.08', '0.10'), (120, 400, '0.07', '0.09')]),
    'U': (17, [(-200, 0, '0.25', '0.31'), (0, 600, '0.07', '0.09')]),
    'BP': (17, [(0, 1000, '0.25', '0.31'), (1000, 2000, '0.37', '0.47'), (2000, 2500, '0.50', '0.62')]),
    'XK': (17, [(-200, 300, '0.12', '0.16'), (300, 800, '0.19', '0.23')]),
}
TC_ORDER = ['K', 'J', 'B', 'BP', 'C', 'D', 'E', 'G', 'L', 'N', 'R', 'S', 'T', 'U', 'XK']
# J and K input rows are kept from the previous sheet (no separate measure table is printed); they use the same figures
TC_INPUT = ['K', 'J']

# RTD (printed pp.18-20): name -> (printed page, note id, [(lo degC, hi degC, 90 d, 1 y)])  95 % column
RTD = {
    'Cu 10 (427)': (18, 22, [(-80, 260, '0.21', '0.23')]),
    'Cu 50 (428)': (18, 22, [(-180, 200, '0.28', '0.31')]),
    'Cu 100 (428)': (18, 22, [(-180, 40, '0.28', '0.31'), (40, 200, '0.46', '0.50')]),
    'Ni 120 (672)': (18, 22, [(-80, 0, '0.05', '0.06'), (0, 100, '0.05', '0.06'), (100, 260, '0.1', '0.11')]),
    'Pt 100 (385)': (18, 22, [(-200, -80, '0.04', '0.04'), (-80, 0, '0.04', '0.04'), (0, 100, '0.05', '0.05'), (100, 300, '0.06', '0.07'), (300, 400, '0.07', '0.08'),
                              (400, 630, '0.09', '0.09'), (630, 800, '0.15', '0.18')]),
    'Pt 100 (3916)': (19, 22, [(-200, -190, '0.18', '0.19'), (-190, -80, '0.03', '0.03'), (-80, 0, '0.04', '0.04'), (0, 100, '0.04', '0.05'), (100, 260, '0.05', '0.05'),
                               (260, 300, '0.05', '0.06'), (300, 400, '0.06', '0.07'), (400, 600, '0.07', '0.08'), (600, 630, '0.16', '0.18')]),
    'Pt 100 (3926)': (19, 22, [(-200, -80, '0.04', '0.04'), (-80, 0, '0.04', '0.04'), (0, 100, '0.05', '0.05'), (100, 300, '0.06', '0.07'), (300, 400, '0.07', '0.08'),
                               (400, 630, '0.09', '0.09')]),
    'Pt 200 (385)': (19, 22, [(-200, -80, '0.03', '0.03'), (-80, 0, '0.03', '0.03'), (0, 100, '0.03', '0.03'), (100, 260, '0.04', '0.04'), (260, 300, '0.09', '0.09'),
                              (300, 400, '0.09', '0.10'), (400, 600, '0.10', '0.11'), (600, 630, '0.11', '0.12')]),
    'Pt 500 (385)': (19, 22, [(-200, -80, '0.03', '0.03'), (-80, 0, '0.04', '0.04'), (0, 100, '0.04', '0.04'), (100, 260, '0.04', '0.05'), (260, 300, '0.05', '0.06'),
                              (300, 400, '0.05', '0.06'), (400, 600, '0.06', '0.07'), (600, 630, '0.08', '0.09')]),
    'Pt 1000 (385)': (20, 22, [(-200, -80, '0.02', '0.02'), (-80, 0, '0.02', '0.02'), (0, 100, '0.03', '0.03'), (100, 260, '0.04', '0.04'), (260, 300, '0.04', '0.05'),
                               (300, 400, '0.05', '0.05'), (400, 600, '0.05', '0.05'), (600, 630, '0.16', '0.18')]),
}


# ------------------------------------------------------------------------------------------------------------ builders
def temp_specs(d90, d1y):
    return [spec('1 yr', None, f'{d1y}degC'), spec('90 day', None, f'{d90}degC')]


def build():
    functions, problems = [], []

    # ---- Voltage, DC
    f = dict(name='Voltage, DC', direction='output', page=P(2), ranges=[])
    for label, top, cols, floor, _ in DCV:
        t = float(D(top))
        f['ranges'].append(entry(f['name'], label, P(2), (-t, t), 'V', None, specs_for(cols, floor), [3] + DCV_NOTES[label]))
    functions.append(f)

    # ---- Voltage, AC
    f = dict(name='Voltage, AC', direction='output', page=P(3), ranges=[])
    for name, alo, ahi in ACV_RANGES:
        for flo, fhi, cols, floor in ACV[name]:
            notes = [3] + ([7] if name == '12mV' else []) + ([6] if name in ('1.2V', '12V', '120V') and fhi <= 100e3 else []) + ACV_NOTES.get((name, flo), [])
            f['ranges'].append(entry(f['name'], band_label(name, flo, fhi), P(ACV_PAGE[name]), (alo, ahi), 'V', (flo, fhi), specs_for(cols, floor), notes))
    functions.append(f)

    # ---- Current, DC
    f = dict(name='Current, DC', direction='output', page=P(6), ranges=[])
    for label, top, cols, floor in DCI:
        t = float(D(top))
        f['ranges'].append(entry(f['name'], label, P(6), (-t, t), 'A', None, specs_for(cols, floor), [9]))
    functions.append(f)

    # ---- Current, AC
    f = dict(name='Current, AC', direction='output', page=P(7), ranges=[])
    for name, alo, ahi in ACI_RANGES:
        for flo, fhi, cols, floor in ACI[name]:
            notes = [9, 12] + ACI_NOTES.get((name, flo), [])
            f['ranges'].append(entry(f['name'], band_label(name, flo, fhi), P(ACI_PAGE[name]), (alo, ahi), 'A', (flo, fhi), specs_for(cols, floor), notes))
    functions.append(f)

    # ---- Frequency (only a 2 year absolute uncertainty is printed: kept as the '1 yr' figure of the previous sheet, see problems)
    f = dict(name='Frequency', direction='output', page=P(10), ranges=[])
    r = entry(f['name'], '0.01Hz - 2MHz', P(10), (0.01, 2e6), 'Hz', None, [spec('1 yr', 2.5)], [23])
    r['range_max'] = None
    f['ranges'].append(r)
    functions.append(f)

    # ---- Resistance 4-wire and 2-wire
    f4 = dict(name='Resistance [4-wire]', direction='output', page=P(12), ranges=[])
    f2 = dict(name='Resistance [2-Wire]', direction='output', page=P(12), ranges=[])
    prev = D(0)
    for label, top, cols, floor, imin in OHM:
        t = D(top)
        amp = (float(prev), float(t))
        f4['ranges'].append(entry(f4['name'], label, P(12), amp, 'ohm', None, specs_for(cols, floor), [13, 15]))
        fl, _ = qty(floor)
        extra = D('5e-6') / qty(imin)[0]
        floor2 = fl + extra
        floor2_text = f'{floor2.normalize():f}Ohm'
        f2['ranges'].append(entry(f2['name'], label, P(12), amp, 'ohm', None, specs_for(cols, floor2_text), [13, 14, 15]))
        prev = t
    functions += [f4, f2]

    # ---- Capacitance
    f = dict(name='Capacitance', direction='output', page=P(13), ranges=[])
    prev = D(0)
    for label, top, cols, floor, notes in CAP:
        t = D(top)
        f['ranges'].append(entry(f['name'], label, P(13), (float(prev), float(t)), 'F', None, specs_for(cols, floor, rel_unit='%'), [16] + notes))
        prev = t
    functions.append(f)

    # ---- Inductance
    f = dict(name='Inductance', direction='output', page=P(14), ranges=[])
    prev = D(0)
    for label, top, cols, floor in IND:
        t = D(top)
        f['ranges'].append(entry(f['name'], label, P(14), (float(prev), float(t)), 'H', None, specs_for(cols, floor, rel_unit='%'), [18]))
        prev = t
    functions.append(f)

    # ---- Thermocouples: source rows for every printed type, then the J / K input rows of the previous sheet
    def tc_function(tc, direction):
        page, rows = TC[tc]
        fn = dict(name=f'Temperature [Type {tc}]', direction=direction, page=P(page), ranges=[])
        for lo, hi, d90, d1y in rows:
            fn['ranges'].append(entry(fn['name'], f'{lo} to {hi}', P(page), (lo, hi), 'degC', None, temp_specs(d90, d1y), [19, 20]))
        return fn
    for tc in TC_ORDER:
        functions.append(tc_function(tc, 'output'))
        if tc in TC_INPUT:
            functions.append(tc_function(tc, 'input'))

    # ---- RTD
    for name, (page, note, rows) in RTD.items():
        fn = dict(name=f'Temperature [RTD {name}]', direction='output', page=P(page), ranges=[])
        for lo, hi, d90, d1y in rows:
            fn['ranges'].append(entry(fn['name'], f'{lo} to {hi}', P(page), (lo, hi), 'degC', None, temp_specs(d90, d1y), [21, note]))
        functions.append(fn)

    # ---- Duty cycle (square wave output), 1000 Hz as on the previous sheet
    fd = dict(name='Frequency [Duty Cycle]', direction='output', page=P(24), ranges=[])
    for label, lo, hi, val in (('50 %', 50, 50, '0.03'), ('10 to 49 %', 10, 49, '0.06'), ('51 to 90 %', 51, 90, '0.06')):
        s = sm.parse_spec(f'[1 yr] Accuracy: +/-({val} %DC)')
        assert 'error' not in s
        r = entry(fd['name'], f'1000Hz {label}', P(24), (lo, hi), '%DC', None, [s], [24], qualifiers=[('Hz', 1000, 1000, 'Hz')])
        fd['ranges'].append(r)
    functions.append(fd)

    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='5560A', description='Calibrator',
        confidence_text='95 % confidence level (k = 2) column; the document also prints a 99 % (k = 2.58) column, not stored',
        confidence_pct=95.0,
        reference='Product Specifications Dec 2022 Rev. 8, 6/26', revision='Rev. 8, 6/26',
        author='', approved_by='', approve_date='', source_pdf='5560_Specs.pdf', sheet_generated='', built=BUILT),
        notes={str(k): v for k, v in NOTES.items()}, functions=functions)

    def w(where, what, level='warn'):
        problems.append(dict(level=level, where=where, what=what))
    w('standard', 'Source: Fluke 5560A Product Specifications, December 2022, Rev. 8, 6/26 (English), 31 pages. Row "page" fields are PDF page numbers (printed page n = PDF page n + 2).')
    w('standard', 'Approval: no author or approval is recorded. The previous sheet (a SpecTrack export) carried author and approval "Tyler, Mike A, 2/10/2026"; that approval was for the SpecTrack sheet, not for this rebuild from the document, so the fields are blank until the owner approves it.')
    w('standard', 'Periods: only 90 day and 1 yr (95 % column, divisor 2). The document\'s 2 y columns and its 99 % columns are not loaded (owner decision). The default period of the standard stays 1 yr; a 90 day figure is used only when a caller asks for period="90 day".')
    w('Frequency', 'The document prints ONLY a "2 Year Absolute Uncertainty" (+/-2.5 uHz/Hz, printed p.10); no 90 day or 1 yr figure exists. The previous sheet\'s value (2.5 ppm) is kept under "1 yr" so frequency lookups still work (a 2 year figure also bounds the 1 year one); no 90 day row is invented. Owner to confirm.')
    w('Frequency', 'The previous sheet\'s amplitude qualifier [V 0 to 100] is dropped: the document gives no amplitude dependence for the frequency uncertainty. Resolution bands (printed p.10) are not stored.')
    w('Frequency [Duty Cycle]', 'The document prints no period for the duty cycle uncertainty and gives it for 10 % to 90 % only (0.02 % of period + 100 ns at 50 %; 0.05 % of period + 100 ns otherwise, printed p.24). The previous sheet\'s three rows (1-49 %, 50 %, 51-99 %, rel 0.05 %, direction input) are replaced by rows for 50 %, 10-49 % and 51-90 % in %DC at 1000 Hz (direction output: the 5560A sources the square wave); 1-10 % and 90-99 % have no figure. The 100 ns term depends on frequency (0.01 %DC at 1 kHz only).')
    w('Resistance [2-Wire]', 'The 2-wire floors are COMPUTED by the builder (24 h floor + 5 uV / lowest specified stimulus current, printed pp.11-12); the document prints no 2-wire table. The previous sheet differs at 12 ohm (0.002 vs 0.00225) and 1200 Mohm (300 kohm vs 102 kohm); the other seven agree with the formula.')
    w('Resistance', 'Floors stored are the 24 h zero (+/-1 degC) column; the 14 d zero (+/-5 degC) floors are not stored. Floor scaling for stimulus currents below / above the specified range (printed p.12) and the RF-field increase of 150 % / 160 % (printed p.11) are not stored.')
    w('Resistance, Capacitance, Inductance', 'Four-wire compensation is assumed for the stored resistance, inductance (and COMP OFF for capacitance) figures; the COMP adders printed with those tables are not stored.')
    w('Voltage, AC', 'The ACV 12 mV range minimum output (1 mV, note 7), the 100 kHz - 300 kHz 70 V limit of the 120 V range (note 8) and External Sense (note 6) are stored as notes only (notes 6 - 8).')
    w('Voltage, AC / Current, AC', 'Bands printed against 40.01 Hz (1.2 V, 12 V, 120 V ranges) are stored from 40.01 Hz up, as printed; 40 Hz belongs to the 10 Hz - 40 Hz row. Neighbouring bands share their border value; the larger limit is used on a border (specmanager rule).')
    w('Temperature', 'The J and K "input" rows are kept from the previous sheet: the document prints one TC table (source), not a measure table. Values equal the printed J / K figures. Direction "input" is unverified.')
    w('Temperature', 'Thermocouple and RTD specifications exclude thermocouple / sensor error and are valid for tcal +/-5 degC (printed pp.15, 18). Types B C D E G L N R S T U BP XK and all RTD tables are NEW on this sheet (not in the previous one).')
    w('standard', 'NOT LOADED (the document prints them; owner to decide whether to add): resolution tables (DCV p.3, ACV p.5, DCI p.7, ACI p.9, resistance p.12, capacitance p.13, inductance p.14, TC 0.01 degC / RTD 0.001 degC) - the sheet row field "resolution" stays blank, so no resolution term enters the budgets (as before); '
                'operating characteristics (stability, noise, distortion, compliance, output impedance, load limits); ACI compliance adders; ACV extended bandwidth (0.01 Hz - 3 Hz 5 %, printed p.23); ACV / ACI square wave accuracy (pp.24-25); ACV DC offset (p.26); Aux voltage DC / AC sine / AC square (pp.26-28); '
                'phase (p.11); AC / DC power and dual output limits (pp.21-22); harmonics (p.23); TC voltage source / measure in linear modes (p.17); 5560A with 52120A current specifications (pp.28-29); the 2 y and 99 % columns of every table.')
    problems.extend(sm.validate_data(data))
    data['problems'] = problems
    return data


def main():
    data = build()
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    print(f"{len(data['functions'])} functions, {n} rows, {len(data['problems'])} problems -> {out}")


if __name__ == '__main__':
    main()
