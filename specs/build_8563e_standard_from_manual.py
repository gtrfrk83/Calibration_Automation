"""Builds specs/standards/agilent_8563e_standard.json from the Agilent 8560 E-Series / EC-Series Calibration Guide, Chapter 5
("8563E/EC Specifications and Characteristics").

    python specs/build_8563e_standard_from_manual.py            # writes specs/standards/agilent_8563e_standard.json

Source: '8563 Specifications.pdf' (PDF title "8560E/EC Series Spectrum Analyzer Calibration Guide", Volumes I and II, 1082 pages).
The guide has one specification chapter per model: Ch.2 8560E/EC (PDF 63-100), Ch.3 8561E/EC (101-136), Ch.4 8562E/EC (137-176),
Ch.5 8563E/EC (177-216), Ch.6 8564E/EC (217-256), Ch.7 8565E/EC (257-296).  ONLY Chapter 5 is read here, so every value in the file is
8563E/EC-specific.  Printed page number = PDF page number in this file ("page" fields, notes and problems all use the same number).

Every number below was transcribed by eye from RENDERED PAGE IMAGES (pdftoppm -r 110, PDF pp.178-212) and not from extracted text.
Nothing is guessed: ambiguities and everything the schema cannot hold are written to 'problems'.

Storage conventions
  * direction 'input' (the analyzer measures) except the CAL OUTPUT amplitude and 1ST LO OUTPUT amplitude, which are 'output' (kind OTHER, so they are never
    returned for a DCV / ACV / FREQ lookup).
  * Units as printed: dB, dBm, dBc, dBc/Hz are stored as printed (NOT converted to linear); Hz, s are SI base units.  spec 'abs' holds the printed number
    (dB for dB limits, dBm / dBc / dBc/Hz for level limits); spec 'unit' says which.  'rel' is a fraction (5 % -> 0.05; 1E-7 -> 1e-7).
  * Two-sided limits '<+/-x' are stored as +/-x (le false); one-sided limits '<x' are stored with le true (raw '<=(x)'): the limit is the printed number.
    Strictly-less-than is not distinguished from less-than-or-equal.
  * period: every warranted specification is '2 yr' (the printed two-year calibration cycle, pp.178, 198).  Characteristic ('typical') values printed next to
    a specification (frequency response, p.193) are a second spec on the same row with period 'typical'.  The cumulative-scale-fidelity 'characteristic'
    (p.196) has period 'characteristic'.  Frequency-reference aging uses '1 day (after 7 day warmup)' / '1 yr' / 'temperature'.
  * Option / serial-number-prefix variants (Option 103, 006, 007, H13; serial prefix 3246A, 3310A, 3645A) are separate rows, named in the function name or label:
    the person must choose the rows that match the unit.  Serial prefix / option are NOT stored as numeric qualifiers.
  * Values derived by arithmetic from a printed formula with the harmonic mixing number N (N from p.180: Band 0 = 1, Band 1 = 1, Band 2 = 2, Band 3 = 4)
    are marked 'derived' in the label and note 3.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

PAGE_OFFSET = 0    # printed page == PDF page in this guide

# ---------------------------------------------------------------------------------------------------------- notes (ids are file-wide)
NOTES = {
    1: 'Conditions (p.178): five-minute warmup in ambient conditions, autocoupled controls, preselector peaked at the signal of interest, digital trace display, IF ADJ ON, '
       'REF LVL CAL adjusted, 1ST LO OUTPUT and 2ND IF OUTPUT terminated in 50 ohms, two-year calibration cycle, environmental requirements met. After a 30-minute warmup at 20 to 30 degC '
       'the preselector does not have to be peaked at each signal (factory preselector-peak values are sufficient). Amplitude temperature drift is a nominal 1 dB per 10 degC (p.178).',
    2: 'Chapter 5 of the guide is the 8563E/EC chapter (PDF pp.177-216). Option / serial-number-prefix variants are rows of their own; choose those that match the unit (Option 006, 007, 103, H13; serial prefix <3246A, 3246A to <3645A, >=3645A, <3310A / >=3310A).',
    3: 'DERIVED value: the printed formula contains the harmonic mixing number N (p.180: Band 0 = 1, Band 1 = 1, Band 2 = 2, Band 3 = 4); the number stored is the formula evaluated for that band. The manual does not print this number.',
    4: 'All specifications are 2 yr (two-year calibration cycle, p.178 and p.198). The manual states no confidence level and no coverage factor.',
    5: 'Typical value, printed beside the specification (p.193): "Typical (20 degC to 30 degC)". Not warranted. Stored as a second spec with period "typical".',
    6: 'Noise sidebands (p.183) are specified for carrier frequencies <=1 GHz. For f > 1 GHz and f <= 2.9 GHz the footnotes add: 5.2 dB x (f/1 GHz - 1) (100 Hz, 1 kHz), 2.5 dB x (f/1 GHz - 1) (10 kHz, 100 kHz serial prefix <3436A), '
       '3.0 dB x (f/1 GHz - 1) (30 kHz), 2.0 dB (100 kHz serial prefix >=3436A) (markers on the page: double-dagger, section sign, hash, double asterisk). NOT stored (frequency-dependent adder). For > 2.9 GHz refer to the characteristics section (not a specification).',
    7: 'Noise sidebands (p.183): footnote double-dagger-dagger: 10 kHz and 30 kHz offsets apply for RES BW <= 1 kHz or span <= 745 kHz; footnote double-dagger-double-dagger: the 100 kHz offset applies for RES BW >= 3 kHz or span > 745 kHz.',
    8: 'Displayed average noise level (p.190): with no signal at input, 1 Hz video bandwidth and 0 dB input attenuation, tracking generator off. Columns: 10 Hz RES BW (Option 103) and 1 Hz RES BW (Non-Option 103).',
    9: 'Reference level uncertainty / frequency response (p.193): with 10 dB input attenuation. Relative = referenced to the midpoint between the highest and lowest peak excursions; absolute = referenced to the 300 MHz CAL OUTPUT.',
    10: 'Printed band label "13.2 kHz to 22.0 GHz" on the Relative frequency response table (p.193) is read as 13.2 GHz to 22.0 GHz (typo in the manual: the adjacent bands are 6.46 to 13.2 GHz and 22.0 to 26.5 GHz).',
    11: 'Mixer level = input level - input attenuation (footnote on pp.189, 191).',
    12: 'Delayed sweep accuracy footnote (p.187): in E-Series instruments without Option 007 the delay time is subject to up to +/-0.5 us of jitter from synchronization to the internal 1 MHz timebase; in E-Series with Option 007 and in EC-Series using sweep times <30 ms, up to +/-83 ns of jitter (12 MHz timebase). Not added to the stored limits.',
    13: 'Gate delay (p.188): the gate delay time experiences up to +/-0.5 us of jitter from synchronization to the internal 1 MHz timebase; time from GATE TRIGGER INPUT to positive edge of GATE OUTPUT. Gate length: time from positive edge to negative edge of GATE OUTPUT.',
    14: 'Scale fidelity (p.196): not the same for RES BW <=100 Hz as for RES BW >=300 Hz; signals not at the reference level see an additional amplitude difference when switching between the two sets. 0 to -70 dB range for RES BW <=100 Hz when SPAN = 0 Hz.',
    15: 'Printed as "+/-2.5 dB characteristic" (p.196): a characteristic, not a specification.',
    16: 'Spurious responses (p.191): mixer level = input level - input attenuation; N = harmonic mixing number. TOI: two signals at the input mixer spaced by >=1 kHz.',
    17: 'Gain compression footnote markers (p.189): the first band is marked with a double-dagger and the other two with a dagger; only the double-dagger footnote ("Mixer level = input level - input attenuation") is printed.',
    18: 'Frequency reference accuracy (p.182): the aging / temperature-stability / settability figures are fractional (dimensionless). They are stored as rel (fraction of frequency) on the 10 MHz reference frequency (value 10 MHz); multiply rel by any other frequency (CAL OUTPUT 300 MHz, 10 MHz REF output, readout frequency) to get the error in Hz. "frequency reference accuracy" in the readout formulas = (aging x period since adjustment) + initial achievable accuracy + temperature stability.',
    19: 'Option 006 extends the low-frequency tuning limit from 9 kHz (non-Option 006) to 30 Hz.',
    20: 'Residual FM (p.183): zero span, 10 Hz RES BW, peak-to-peak in 20 ms. See "Resolution Bandwidth Usability" in Frequency Characteristics (not a specification).',
    21: 'Residual responses (p.191): ">200 kHz with no signal at input, 0 dB input attenuation, N [symbol missing] 1": the relation symbol between N and 1 is absent in the printed PDF page (text and image); the condition is stored as printed.',
}

SPEC_PERIOD = '2 yr'


# ---------------------------------------------------------------------------------------------------------- builders
def S(raw_period, text, rel=0.0, abs_=0.0, unit='', le=False, fs_rel=0.0, fs_value=0.0):
    """One spec dict in the same keys as specmanager.parse_spec.  'text' is the printed limit (kept in 'raw')."""
    body = f'<=({text})' if le else f'+/-({text})'
    return dict(period=raw_period, rel=float(rel), fs_rel=float(fs_rel), fs_value=float(fs_value), abs=float(abs_), unit=unit, le=bool(le),
                raw=f'[{raw_period}] Accuracy: {body}')


def prm(lo, hi, unit, text, tag='', notes=()):
    return dict(tag=tag, lo=float(lo), hi=float(hi), unit=unit, text=text, annot='', notes=list(notes))


def fmt_hz(f):
    for div, u in ((1e9, 'GHz'), (1e6, 'MHz'), (1e3, 'kHz'), (1, 'Hz')):
        if f >= div:
            return f'{f / div:g} {u}'
    return f'{f:g} Hz'


def freq(lo, hi, notes=()):
    t = fmt_hz(lo) if lo == hi else f'{fmt_hz(lo)} to {fmt_hz(hi)}'
    return prm(lo, hi, 'Hz', t, notes=notes)


def row(fname, label, page, params, specs):
    r = dict(label=label, page=page + PAGE_OFFSET, params=params, specs=specs, raw_other=[])
    r.update(sm.analyse_range(fname, label, params))
    return r


def func(name, page, direction='input'):
    return dict(name=name, direction=direction, page=page + PAGE_OFFSET, ranges=[])


def add(f, label, page, params, specs):
    f['ranges'].append(row(f['name'], label, page, params, specs))


# internal mixing bands (p.180): name, low (Hz), high (Hz), N
BANDS = [('Band 0', 30.0, 2.9e9, 1), ('Band 1', 2.75e9, 6.46e9, 1), ('Band 2', 5.86e9, 13.2e9, 2), ('Band 3', 12.4e9, 26.5e9, 4)]


def build():
    functions, problems = [], []

    def w(where, what):
        problems.append(dict(level='warn', where=where, what=what))

    # ---------------------------------------------------------------- frequency reference accuracy (p.182)
    f = func('Reference Oscillator, Frequency Reference Accuracy', 182)
    ref = freq(10e6, 10e6, notes=[18])
    for opt, aging, aging_txt, temp, temp_txt in (
            ('Non-Option 103', 1e-7, '1E-7/year', 1e-8, '1E-8, -10 degC to +55 degC, referenced to 25 degC'),
            ('Option 103', 2e-6, '2E-6/year', 1e-6, '1E-6, -10 degC to +55 degC, referenced to 25 degC')):
        if opt == 'Non-Option 103':
            add(f, f'{opt} aging per day (after 7 day warmup) @ 10 MHz', 182, [ref],
                [S('1 day (after 7 day warmup)', '0.5E-9/day', rel=0.5e-9, unit='Hz')])
        add(f, f'{opt} aging per year @ 10 MHz', 182, [ref], [S('1 yr', aging_txt, rel=aging, unit='Hz')])
        if opt == 'Option 103':
            add(f, f'{opt} settability @ 10 MHz', 182, [ref], [S(SPEC_PERIOD, '1E-6', rel=1e-6, unit='Hz')])
        add(f, f'{opt} temperature stability @ 10 MHz', 182, [ref], [S('temperature', temp_txt, rel=temp, unit='Hz')])
    functions.append(f)

    # ---------------------------------------------------------------- residual FM (p.183), derived per band
    f = func('Residual FM [Peak-to-Peak in 20 ms, zero span, 10 Hz RES BW]', 183)
    for opt, per_n in (('Non-Option 103', 1.0), ('Option 103', 10.0)):
        for name, lo, hi, n in BANDS:
            add(f, f'{opt}, {name} (N={n}, derived) @ {fmt_hz(lo)} to {fmt_hz(hi)}', 183, [freq(lo, hi, notes=[3, 19, 20])],
                [S(SPEC_PERIOD, f'{per_n:g} Hz x N, N = {n}', abs_=per_n * n, unit='Hz', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- noise sidebands (p.183), carrier <= 1 GHz
    f = func('Noise Sidebands [Carrier <= 1 GHz]', 183)
    carrier = freq(0, 1e9, notes=[6])
    # (offset Hz, serial text, non-103, 103)
    NS = [(100, 'serial prefix <3436A', -80, -70), (100, 'serial prefix >=3436A', -88, -70), (1e3, '', -97, -90), (10e3, '', -113, -113),
          (30e3, '', -113, -113), (100e3, 'serial prefix <3436A', -113, -113), (100e3, 'serial prefix >=3436A', -117, -117)]
    for off, ser, v0, v1 in NS:
        for opt, v in (('Non-Option 103', v0), ('Option 103', v1)):
            tag = prm(off, off, 'Hz', f'{fmt_hz(off)} offset', tag='Offset', notes=[7] if off in (10e3, 30e3, 100e3) else [])
            lab = f'{opt}, offset {fmt_hz(off)}' + (f', {ser}' if ser else '') + ' @ carrier <= 1 GHz'
            add(f, lab, 183, [tag, carrier], [S(SPEC_PERIOD, f'{v} dBc/Hz', abs_=v, unit='dBc/Hz', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- span accuracy (p.184), per mixing band, derived thresholds
    f = func('Span Accuracy [Internal Mixing]', 184)
    for name, lo, hi, n in BANDS:
        th = 2e6 * n
        add(f, f'{name} (N={n}, derived), SPAN <= {fmt_hz(th)} @ {fmt_hz(lo)} to {fmt_hz(hi)}', 184,
            [prm(0, th, 'Hz', f'span 0 Hz to {fmt_hz(th)}', tag='Span', notes=[3]), freq(lo, hi)], [S(SPEC_PERIOD, '1 % of span', rel=0.01, unit='Hz')])
        add(f, f'{name} (N={n}, derived), SPAN > {fmt_hz(th)} @ {fmt_hz(lo)} to {fmt_hz(hi)}', 184,
            [prm(th, 13.2e9, 'Hz', f'span > {fmt_hz(th)} to 13.2 GHz', tag='Span', notes=[3]), freq(lo, hi)], [S(SPEC_PERIOD, '5 % of span', rel=0.05, unit='Hz')])
    functions.append(f)

    # ---------------------------------------------------------------- resolution bandwidth (p.185)
    f = func('Resolution Bandwidth, Accuracy', 185)
    add(f, 'RES BW 1 Hz to 300 kHz (RBW setting)', 185, [prm(1, 300e3, 'Hz', '1 Hz to 300 kHz RES BW')], [S(SPEC_PERIOD, '10 % of RES BW', rel=0.10, unit='Hz')])
    add(f, 'RES BW 1 MHz (RBW setting)', 185, [prm(1e6, 1e6, 'Hz', '1 MHz RES BW')], [S(SPEC_PERIOD, '25 % of RES BW', rel=0.25, unit='Hz')])
    functions.append(f)
    f = func('Resolution Bandwidth, Selectivity [60 dB/3 dB bandwidth ratio]', 185)
    add(f, 'RES BW >= 300 Hz (ratio less than)', 185, [prm(300, 2e6, 'Hz', 'RES BW >= 300 Hz (to 2 MHz)')], [S(SPEC_PERIOD, '15:1', abs_=15, unit='ratio', le=True)])
    add(f, 'RES BW <= 100 Hz (ratio less than)', 185, [prm(1, 100, 'Hz', 'RES BW 1 Hz to 100 Hz')], [S(SPEC_PERIOD, '5:1', abs_=5, unit='ratio', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- sweep time accuracy (p.186)
    for var, rows_ in (('Non-Option 007 (E-Series)', [(30e-3, 6000.0, 0.01, '1 %'), (50e-6, 30e-3, 0.10, '10 %')]),
                       ('Option 007 (E-Series) and all EC-Series', [(30e-3, 6000.0, 0.01, '1 %'), (50e-6, 30e-3, 0.001, '0.1 %')])):
        f = func(f'Time, Sweep Time Accuracy [Span = 0 Hz, {var}]', 186)
        for lo, hi, rel, txt in rows_:
            nm = 'sweep time 30 ms to 6,000 s' if lo == 30e-3 else 'sweep time < 30 ms (50 us lower end from the sweep time range, p.186)'
            add(f, f'Sweep time {nm}', 186, [prm(lo, hi, 's', f'{lo:g} s to {hi:g} s')], [S(SPEC_PERIOD, f'{txt} of sweep time', rel=rel, unit='s')])
        functions.append(f)

    # ---------------------------------------------------------------- delayed sweep (p.187)
    delay = prm(2e-6, 65.535e-3, 's', '+2 us to +65.535 ms', notes=[12])
    f = func('Time, Delayed Sweep Accuracy [Serial prefix 3310A and above]', 187)
    add(f, 'Delay +2 us to +65.535 ms', 187, [delay], [S(SPEC_PERIOD, '1 us', abs_=1e-6, unit='s')])
    functions.append(f)
    f = func('Time, Delayed Sweep Accuracy [Serial prefix <3310A]', 187)
    for t_lo, t_hi, pct in ((20, 30, 0.0005), (-10, 55, 0.0012)):
        add(f, f'Delay +2 us to +65.535 ms, {t_lo} to {t_hi} degC', 187,
            [delay, prm(t_lo, t_hi, 'degC', f'{t_lo} degC to {t_hi} degC', tag='Temperature')],
            [S(SPEC_PERIOD, f'1 us + {pct * 100:g} % x DELAY SWEEP setting', rel=pct, abs_=1e-6, unit='s')])
    functions.append(f)

    # ---------------------------------------------------------------- gate delay / gate length (p.188)
    gd = prm(3e-6, 65.535e-3, 's', '3 us to 65.535 ms', notes=[13])
    f = func('Time, Gate Delay Accuracy [Serial prefix 3310A and above]', 188)
    add(f, 'Gate delay 3 us to 65.535 ms', 188, [gd], [S(SPEC_PERIOD, '1 us', abs_=1e-6, unit='s', le=True)])
    functions.append(f)
    f = func('Time, Gate Delay Accuracy [Serial prefix <3310A]', 188)
    for t_lo, t_hi, pct in ((20, 30, 0.0005), (-10, 55, 0.0012)):
        add(f, f'Gate delay 3 us to 65.535 ms, {t_lo} to {t_hi} degC', 188,
            [gd, prm(t_lo, t_hi, 'degC', f'{t_lo} degC to {t_hi} degC', tag='Temperature')],
            [S(SPEC_PERIOD, f'1 us + {pct * 100:g} % x GATE DELAY setting', rel=pct, abs_=1e-6, unit='s')])
    functions.append(f)
    gl = prm(1e-6, 65.535e-3, 's', '1 us to 65.535 ms', notes=[13])
    f = func('Time, Gate Length Accuracy [Serial prefix 3310A and above]', 188)
    add(f, 'Gate length 1 us to 65.535 ms', 188, [gl], [S(SPEC_PERIOD, '1 us', abs_=1e-6, unit='s', le=True)])
    functions.append(f)
    f = func('Time, Gate Length Accuracy [Serial prefix <3310A]', 188)
    for t_lo, t_hi, pct in ((20, 30, 0.0005), (-10, 55, 0.0012)):
        add(f, f'Gate length 1 us to 65.535 ms, {t_lo} to {t_hi} degC', 188,
            [gl, prm(t_lo, t_hi, 'degC', f'{t_lo} degC to {t_hi} degC', tag='Temperature')],
            [S(SPEC_PERIOD, f'0.2 us + {pct * 100:g} % x GATE LENGTH setting', rel=pct, abs_=0.2e-6, unit='s')])
    functions.append(f)

    # ---------------------------------------------------------------- gain compression (p.189)
    f = func('Gain Compression', 189)
    for lo, hi, mix, mark in ((10e6, 2.9e9, -5, ''), (2.9e9, 6.46e9, 0, ''), (6.46e9, 26.5e9, -3, '')):
        add(f, f'Mixer level <= {mix} dBm @ {fmt_hz(lo)} to {fmt_hz(hi)}', 189,
            [prm(mix, mix, 'dBm', f'<= {mix} dBm at input mixer', tag='Mixer level (max)', notes=[11, 17]), freq(lo, hi)],
            [S(SPEC_PERIOD, '1.0 dB', abs_=1.0, unit='dB', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- displayed average noise level (p.190)
    f = func('Displayed Average Noise Level [No signal, 0 dB input attenuation, 1 Hz video bandwidth]', 190)
    # (label, flo, fhi, 10 Hz RBW Option 103, 1 Hz RBW Non-Option 103)
    DANL = [('30 Hz (Option 006)', 30, 30, -80, -90), ('1 kHz (Option 006)', 1e3, 1e3, -95, -105), ('10 kHz', 10e3, 10e3, -110, -120),
            ('100 kHz', 100e3, 100e3, -110, -120), ('1 MHz to 10 MHz', 1e6, 10e6, -130, -140),
            ('10 MHz to 2.9 GHz, serial prefix <3246A', 10e6, 2.9e9, -135, -145),
            ('10 MHz to 2.9 GHz, serial prefix 3246A to <3645A', 10e6, 2.9e9, -134, -144),
            ('10 MHz to 2.9 GHz, serial prefix >=3645A', 10e6, 2.9e9, -139, -149),
            ('10 MHz to 2.9 GHz, Option H13', 10e6, 2.9e9, -139, -149),
            ('2.9 GHz to 6.46 GHz', 2.9e9, 6.46e9, -138, -148), ('6.46 GHz to 13.2 GHz', 6.46e9, 13.2e9, -135, -145),
            ('13.2 GHz to 22.0 GHz', 13.2e9, 22.0e9, -130, -140), ('22.0 GHz to 26.5 GHz', 22.0e9, 26.5e9, -129, -139)]
    for lab, lo, hi, v103, v0 in DANL:
        for opt, rbw, v in (('Non-Option 103', 1, v0), ('Option 103', 10, v103)):
            add(f, f'{opt}, {rbw} Hz RES BW, {lab}', 190, [prm(rbw, rbw, 'Hz', f'{rbw} Hz RES BW', tag='RES BW', notes=[8]), freq(lo, hi, notes=[19] if 'Option 006' in lab else [])],
                [S(SPEC_PERIOD, f'{v} dBm', abs_=v, unit='dBm', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- spurious responses (p.191)
    f = func('Spurious Responses [Second Harmonic Distortion]', 191)
    for lab, lo, hi, mix, v in (('serial prefix <3645A', 1e6, 1.45e9, -40, -72), ('serial prefix >=3645A', 20e6, 1.45e9, -40, -79), ('Option H13', 20e6, 1.45e9, -40, -79),
                                ('1.45 GHz to 2.0 GHz', 1.45e9, 2.0e9, -10, -85), ('2.0 GHz to 13.25 GHz', 2.0e9, 13.25e9, -10, -100)):
        add(f, f'Applied signal {fmt_hz(lo)} to {fmt_hz(hi)} ({lab}), mixer level {mix} dBm', 191,
            [prm(mix, mix, 'dBm', f'{mix} dBm mixer level', tag='Mixer level', notes=[11]), freq(lo, hi)], [S(SPEC_PERIOD, f'{v} dBc', abs_=v, unit='dBc', le=True)])
    functions.append(f)
    f = func('Spurious Responses [Third Order Intermodulation Distortion]', 191)
    for lab, lo, hi, v in (('serial prefix <3645A', 1e6, 2.9e9, -78), ('serial prefix >=3645A', 20e6, 2.9e9, -82), ('Option H13', 20e6, 2.9e9, -82),
                           ('2.9 GHz to 6.46 GHz', 2.9e9, 6.46e9, -90), ('6.46 GHz to 26.5 GHz', 6.46e9, 26.5e9, -75)):
        add(f, f'Frequency range {fmt_hz(lo)} to {fmt_hz(hi)} ({lab}), two signals at -30 dBm each', 191,
            [prm(-30, -30, 'dBm', '-30 dBm each at input mixer', tag='Mixer level (each)', notes=[11, 16]), freq(lo, hi)], [S(SPEC_PERIOD, f'{v} dBc', abs_=v, unit='dBc', le=True)])
    functions.append(f)
    f = func('Spurious Responses [Image, Multiple and Out-of-Band]', 191)
    add(f, 'Frequency range 10 MHz to 26.5 GHz, mixer level -10 dBm', 191,
        [prm(-10, -10, 'dBm', '-10 dBm mixer level', tag='Mixer level', notes=[11]), freq(10e6, 26.5e9)], [S(SPEC_PERIOD, '-80 dBc', abs_=-80, unit='dBc', le=True)])
    functions.append(f)
    f = func('Residual Responses [No signal at input, 0 dB input attenuation]', 191)
    add(f, 'Residual responses >200 kHz (N relation symbol missing in print)', 191,
        [prm(0, 0, 'dB', '0 dB input attenuation', tag='Input attenuation', notes=[21]), freq(200e3, 26.5e9, notes=[21])], [S(SPEC_PERIOD, '-90 dBm', abs_=-90, unit='dBm', le=True)])
    functions.append(f)

    # ---------------------------------------------------------------- reference level uncertainty: frequency response (p.193)
    att10 = prm(10, 10, 'dB', '10 dB input attenuation', tag='Input attenuation', notes=[9])
    f = func('Flatness [Frequency Response, Relative, 10 dB input attenuation]', 193)
    REL = [('30 Hz to 2.9 GHz (Option 006)', 30, 2.9e9, 1.25, 0.8), ('9 kHz to 2.9 GHz (Non-Option 006)', 9e3, 2.9e9, 1.25, 0.8),
           ('100 MHz to 2.0 GHz (serial prefix >=3645A)', 100e6, 2.0e9, 1.0, 0.8), ('2.9 GHz to 6.46 GHz', 2.9e9, 6.46e9, 1.5, 1.0),
           ('6.46 GHz to 13.2 GHz', 6.46e9, 13.2e9, 2.2, 1.5), ('13.2 GHz to 22.0 GHz (printed "13.2 kHz")', 13.2e9, 22.0e9, 2.5, 1.5),
           ('22.0 GHz to 26.5 GHz', 22.0e9, 26.5e9, 3.3, 2.2)]
    for lab, lo, hi, s2, ty in REL:
        add(f, f'Relative, {lab}', 193, [att10, freq(lo, hi, notes=[10] if 'kHz")' in lab else [])],
            [S(SPEC_PERIOD, f'{s2} dB', abs_=s2, unit='dB'), S('typical', f'{ty} dB', abs_=ty, unit='dB')])
    functions.append(f)
    f = func('Flatness [Frequency Response, Absolute, referenced to 300 MHz CAL OUTPUT, 10 dB input attenuation]', 193)
    ABS = [('30 Hz to 2.9 GHz (Option 006)', 30, 2.9e9, 1.80, 1.0), ('9 kHz to 2.9 GHz (Non-Option 006)', 9e3, 2.9e9, 1.80, 1.0),
           ('2.9 GHz to 6.46 GHz', 2.9e9, 6.46e9, 2.4, 1.5), ('6.46 GHz to 13.2 GHz', 6.46e9, 13.2e9, 2.9, 2.0),
           ('13.2 GHz to 26.5 GHz', 13.2e9, 26.5e9, 4.0, 2.5), ('30 Hz to 26.5 GHz (Option 006)', 30, 26.5e9, 4.0, 2.5),
           ('9 kHz to 26.5 GHz (Non-Option 006)', 9e3, 26.5e9, 4.0, 2.5)]
    for lab, lo, hi, s2, ty in ABS:
        add(f, f'Absolute, {lab}', 193, [att10, freq(lo, hi)], [S(SPEC_PERIOD, f'{s2} dB', abs_=s2, unit='dB'), S('typical', f'{ty} dB', abs_=ty, unit='dB')])
    functions.append(f)

    # ---------------------------------------------------------------- other amplitude uncertainties (pp.193-195)
    f = func('Amplitude Uncertainty [Band Switching, additional to Relative Frequency Response]', 193)
    add(f, 'Between any two bands', 193, [freq(9e3, 26.5e9)], [S(SPEC_PERIOD, '1.0 dB', abs_=1.0, unit='dB')])
    functions.append(f)
    f = func('Amplitude Uncertainty [Calibrator, -10 dBm 300 MHz]', 193)
    add(f, 'Calibrator uncertainty at -10 dBm, 300 MHz', 193, [prm(-10, -10, 'dBm', '-10 dBm', tag='Level'), freq(300e6, 300e6)], [S(SPEC_PERIOD, '0.3 dB', abs_=0.3, unit='dB')])
    functions.append(f)
    f = func('Amplitude Uncertainty [Input Attenuator Switching, 20 to 70 dB settings referenced to 10 dB]', 194)
    for lab, lo in (('9 kHz to 2.9 GHz', 9e3), ('30 Hz to 2.9 GHz (Option 006)', 30)):
        add(f, f'Per 10 dB step, {lab}', 194, [prm(10, 10, 'dB', '10 dB step', tag='Step'), freq(lo, 2.9e9)], [S(SPEC_PERIOD, '0.6 dB per 10 dB step', abs_=0.6, unit='dB/10 dB step')])
        add(f, f'Maximum, {lab}', 194, [prm(20, 70, 'dB', '20 to 70 dB settings', tag='Attenuator setting'), freq(lo, 2.9e9)], [S(SPEC_PERIOD, '1.8 dB maximum', abs_=1.8, unit='dB')])
    functions.append(f)
    f = func('Amplitude Uncertainty [IF Gain]', 194)
    add(f, 'Reference levels 0 dBm to -80 dBm, 10 dB input attenuation', 194, [prm(-80, 0, 'dBm', '0 dBm to -80 dBm reference level')], [S(SPEC_PERIOD, '1.0 dB', abs_=1.0, unit='dB')])
    functions.append(f)
    f = func('Amplitude Uncertainty [Resolution Bandwidth Switching, referenced to 300 kHz RES BW]', 194)
    add(f, 'Referenced to 300 kHz resolution bandwidth at the reference level', 194, [prm(1, 2e6, 'Hz', 'RES BW 1 Hz to 2 MHz (range per p.185)', notes=[14])], [S(SPEC_PERIOD, '0.5 dB', abs_=0.5, unit='dB')])
    functions.append(f)
    f = func('Amplitude Uncertainty [Pulse Digitization, pulse response mode, PRF > 720/sweep time]', 195)
    add(f, 'LOG, RES BW <= 1 MHz (peak-to-peak)', 195, [prm(1, 1e6, 'Hz', 'RES BW <= 1 MHz')], [S(SPEC_PERIOD, '1.25 dB peak-to-peak', abs_=1.25, unit='dB p-p', le=True)])
    add(f, 'LOG, RES BW = 2 MHz (peak-to-peak)', 195, [prm(2e6, 2e6, 'Hz', 'RES BW = 2 MHz')], [S(SPEC_PERIOD, '3 dB peak-to-peak', abs_=3, unit='dB p-p', le=True)])
    add(f, 'LINEAR, RES BW <= 1 MHz (peak-to-peak, of reference level)', 195, [prm(1, 1e6, 'Hz', 'RES BW <= 1 MHz')], [S(SPEC_PERIOD, '4 % of reference level peak-to-peak', rel=0.04, unit='x reference level p-p', le=True)])
    add(f, 'LINEAR, RES BW = 2 MHz (peak-to-peak, of reference level)', 195, [prm(2e6, 2e6, 'Hz', 'RES BW = 2 MHz')], [S(SPEC_PERIOD, '12 % of reference level peak-to-peak', rel=0.12, unit='x reference level p-p', le=True)])
    functions.append(f)
    f = func('Amplitude Uncertainty [IF Alignment, additional, 300 Hz RES BW only]', 195)
    add(f, '300 Hz RES BW only', 195, [prm(300, 300, 'Hz', '300 Hz RES BW')], [S(SPEC_PERIOD, '0.5 dB', abs_=0.5, unit='dB')])
    functions.append(f)

    # ---------------------------------------------------------------- scale fidelity (p.196)
    f = func('Scale Fidelity [LOG, Incremental, 0 to -90 dB range]', 196)
    add(f, 'RES BW >= 300 Hz (per dB)', 196, [prm(300, 2e6, 'Hz', 'RES BW >= 300 Hz', notes=[14])], [S(SPEC_PERIOD, '0.1 dB/dB', abs_=0.1, unit='dB/dB')])
    add(f, 'RES BW <= 100 Hz (per 2 dB)', 196, [prm(1, 100, 'Hz', 'RES BW <= 100 Hz', notes=[14])], [S(SPEC_PERIOD, '0.2 dB/2 dB', abs_=0.2, unit='dB/2 dB')])
    functions.append(f)
    f = func('Scale Fidelity [LOG, Cumulative, maximum]', 196)
    add(f, '0 to -90 dB range, RES BW >= 300 Hz, maximum', 196, [prm(300, 2e6, 'Hz', 'RES BW >= 300 Hz', notes=[14])], [S(SPEC_PERIOD, '0.85 dB maximum (0.1 dB/dB from the reference level)', abs_=0.85, unit='dB')])
    add(f, '0 to -90 dB range (-70 dB for span 0 Hz), RES BW <= 100 Hz, maximum', 196, [prm(1, 100, 'Hz', 'RES BW <= 100 Hz', notes=[14])], [S(SPEC_PERIOD, '0.85 dB maximum (0.2 dB/2 dB from the reference level)', abs_=0.85, unit='dB')])
    add(f, '0 to -100 dB range, RES BW >= 300 Hz', 196, [prm(300, 2e6, 'Hz', 'RES BW >= 300 Hz', notes=[14, 15])], [S('characteristic', '2.5 dB (characteristic)', abs_=2.5, unit='dB')])
    add(f, '0 to -100 dB range, RES BW <= 100 Hz, maximum', 196, [prm(1, 100, 'Hz', 'RES BW <= 100 Hz', notes=[14])], [S(SPEC_PERIOD, '1.5 dB maximum', abs_=1.5, unit='dB')])
    functions.append(f)
    f = func('Scale Fidelity [LINEAR]', 196)
    add(f, 'LINEAR scale (of reference level)', 196, [prm(1, 2e6, 'Hz', 'any RES BW (not restricted on the page)', notes=[14])], [S(SPEC_PERIOD, '3 % of reference level', rel=0.03, unit='x reference level')])
    functions.append(f)

    # ---------------------------------------------------------------- outputs and IF input (p.197)
    f = func('IF INPUT [Full-screen deflection level, external mixing, 0 dBm reference level, 30 dB conversion loss]', 197)
    add(f, 'Input level -30 dBm +/-1.5 dB', 197, [prm(-31.5, -28.5, 'dBm', '-30 dBm +/-1.5 dB')], [S(SPEC_PERIOD, '1.5 dB', abs_=1.5, unit='dB')])
    functions.append(f)
    f = func('Calibrator Output [CAL OUTPUT, 300 MHz]', 197, direction='output')
    add(f, 'CAL OUTPUT amplitude -10 dBm', 197, [prm(-10, -10, 'dBm', '-10 dBm'), freq(300e6, 300e6)], [S(SPEC_PERIOD, '0.3 dB', abs_=0.3, unit='dB')])
    functions.append(f)
    f = func('Local Oscillator Output [1ST LO OUTPUT]', 197, direction='output')
    add(f, '1ST LO OUTPUT amplitude +16.5 dBm', 197, [prm(16.5, 16.5, 'dBm', '+16.5 dBm')], [S(SPEC_PERIOD, '2.0 dB', abs_=2.0, unit='dB')])
    functions.append(f)
    # ---------------------------------------------------------------- explicit problems
    w('standard', 'Direction is "input" for the measuring specifications (the analyzer measures). specmanager.StandardSpec.lookup() defaults to direction="output": pass direction="input" (or None). '
                  'The CAL OUTPUT amplitude and 1ST LO OUTPUT amplitude rows are direction "output" with kind OTHER.')
    w('standard', 'No confidence level or coverage factor is printed for the specifications (p.178). confidence_pct is left empty; the specification manager will assume k = 2 unless a divisor is set. '
                  'The guide calls them "warranted performance" under the stated conditions.')
    w('standard', 'Period: every warranted row is stored with period "2 yr" (the printed two-year calibration cycle). specmanager.StandardSpec.lookup() defaults to the standard\'s '
                  'period (default "1 yr"), so a lookup needs period="2 yr" (or set the standard\'s period to 2 yr in the manager) to find these specs. Typical values use period "typical".')
    w('standard', 'Model coverage: the guide (title "8560E/EC Series Spectrum Analyzer Calibration Guide", 1082 pages, Volumes I and II) has one specification chapter per model: 8560E/EC (Ch.2, PDF 63-100), '
                  '8561E/EC (Ch.3, 101-136), 8562E/EC (Ch.4, 137-176), 8563E/EC (Ch.5, 177-216), 8564E/EC (Ch.6, 217-256), 8565E/EC (Ch.7, 257-296). ONLY Ch.5 (pp.177-216) was read; every value in this file is 8563E/EC-specific. '
                  'The performance tests (Vol. II, Ch.10, p.513 on) and test-record limits were not read.')
    w('standard', 'Model name: stored as "8563E" (manufacturer "Agilent"). The chapter covers the 8563E and the 8563EC (the EC series differs by Option 007 timing and other items called out per row); the guide gives no separate 8563EC column. Check which rows (Option 006/007/103/H13, serial prefix) apply to the asset.')
    w('standard', 'Page numbers: printed page = PDF page in this guide, so "page" fields and notes use the one number.')
    w('Frequency Readout Accuracy (p.181)', 'NOT STORED (depends on span, RES BW, N and a sum of terms the schema cannot hold): <+/-(frequency readout x frequency reference accuracy + 5 % of frequency span + 15 % of resolution bandwidth + 10 Hz) for SPAN > 2 MHz x N; '
                                          '<+/-(frequency readout x frequency reference accuracy + 1 % of frequency span + 15 % of resolution bandwidth + 10 Hz) for SPAN <= 2 MHz x N (START, CENTER, STOP or MARKER frequency). N = harmonic mixing mode.')
    w('Frequency Count Marker (p.181)', 'NOT STORED (needs N, reference accuracy and LSD): marker accuracy (S/N >= 25 dB) <+/-(marker frequency x frequency reference accuracy + 2 Hz x N + 1 LSD); '
                                       'delta count accuracy <+/-(delta frequency x frequency reference accuracy + 4 Hz x N + 2 LSD). Resolution selectable 1 Hz to 1 MHz. Marker frequency resolution SPAN/600 (min 1 Hz) and marker time resolution sweep time/600 (p.188) are resolutions, not stored.')
    w('Noise Sidebands > 1 GHz (p.183)', 'Frequency-dependent adders for carriers above 1 GHz and up to 2.9 GHz are not stored (see note 6); only the <=1 GHz limits are rows.')
    w('Spurious Responses, all input-related (p.191)', 'NOT STORED: 10 MHz to 26.5 GHz, mixer level -40 dBm, < (-75 + 20 log N) dBc, N = harmonic mixing number. Depends on N; evaluating it would need a rounded (irrational) number the manual does not print.')
    w('Resolution Bandwidth, Accuracy (p.185)', '2 MHz RES BW accuracy is printed "<+50 %, -25 %" (asymmetric): the schema holds one +/- limit, so it is NOT stored.')
    w('Resolution Bandwidth / Video Bandwidth / Span / Sweep ranges, mixing bands (pp.180, 184, 185, 186, 187)', 'Range-only entries (frequency range, internal and external mixing bands, harmonic mixing numbers, span range 0 Hz and 100 Hz to 13.2 GHz, external mixing minimum span 100 Hz x N, RES BW 1 Hz to 1 MHz (Option 103: 10 Hz to 1 MHz) and 2 MHz, video BW 1 Hz to 3 MHz, '
                                                                                                                           'sweep time ranges, trigger modes, delayed-sweep and gate ranges/resolution) carry no accuracy and are NOT stored. Delayed-sweep range and gate range are used as value ranges of their accuracy rows.')
    w('Bandwidth shape (p.185)', 'Qualitative (approximately Gaussian / synchronously tuned 4-pole / digital) and not stored.')
    w('Maximum Safe Input Power / DC (p.189)', 'Ratings, not accuracies, NOT stored: average continuous power +30 dBm (1 W) with input attenuation >=10 dB; peak pulse power +50 dBm (100 W) for pulse widths <=10 us and <1 % duty cycle with input attenuation >=30 dB; DC voltage <+/-0.2 V.')
    w('Display range, reference level range, marker amplitude resolution (pp.192, 196)', 'Not stored (ranges and resolutions): LOG 10 / 5 / 2 / 1 dB/DIV and LINEAR 10 % per division scales; reference level range -120 dBm to +30 dBm (LOG, 0.1 dB steps) and 2.2 uV to 7.07 V (LINEAR, 1 % steps); marker amplitude resolution (1/6, 1/12, 1/30, 1/60 dB; reference level/600).')
    w('Inputs and Outputs / General Specifications (pp.197-201)', 'Connector, GPIB, plotter/printer, environmental, EMC, power and dimension tables are not calibration data and are NOT stored. Of p.197: IF INPUT level, CAL OUTPUT amplitude and 1ST LO OUTPUT amplitude ARE stored.')
    w('Characteristics (pp.202-212)', '"These are not specifications" (p.202): typical / nominal / approximate values (e.g. initial achievable accuracy, warmup, impulse bandwidth, noise-sideband plots, band-to-band amplitude accuracy, dynamic range) are NOT stored. Regulatory pages 213-216 not read.')
    w('Scale Fidelity, Cumulative LOG (p.196)', 'Printed "0.1 dB/dB from the reference level to a maximum of +/-0.85 dB": the slope and the cap are both on the page; only the cap (0.85 dB, 1.5 dB) is stored as a number with the slope in the spec text. The 0 to -100 dB range with RES BW >= 300 Hz is "+/-2.5 dB characteristic" (stored with period "characteristic"); '
                                               'whether the RES BW <= 100 Hz "maximum of +/-1.5 dB" is also a characteristic is not stated (stored as a specification, 2 yr). Linear / incremental limits in dB per dB are stored with unit "dB/dB" or "dB/2 dB", not as ordinary +/- limits.')
    w('Scale Fidelity / Pulse Digitization / LINEAR (pp.195, 196)', 'Limits given as a percentage of the reference level are stored as rel with unit "x reference level" (value = the reference level, which the program must supply). Pulse digitization limits are peak-to-peak and one-sided ("<").')
    w('Amplitude Uncertainty [Input Attenuator Switching] (p.194)', 'Printed "<+/-0.6 dB/10 dB step, +/-1.8 dB max.": stored as two rows (per step, maximum). The two-number rule cannot be a single spec.')
    w('Amplitude Uncertainty [Resolution Bandwidth Switching] (p.194)', 'The value range of the RES BW is not printed on the row; stored as 1 Hz to 2 MHz (the RES BW range on p.185). Referenced to 300 kHz RES BW at the reference level.')
    w('Gate Delay / Gate Length Accuracy (p.188)', 'The page has Edge Mode and Level Mode columns; the accuracy figures sit under the Edge Mode column for "serial prefix 3310A and above" and are centred across both columns for the <3310A formulas. Mode applicability is not stated unambiguously; stored without a mode qualifier. Level-mode range (<=0.5 us) not stored.')
    w('Gain Compression (p.189)', 'Footnote markers are double-dagger on the first band and dagger on the other two, but only the double-dagger footnote is printed (note 17). Level conditions are "mixer level at or below" the printed dBm; stored as a (max) qualifier.')
    w('Residual Responses (p.191)', 'The relation symbol between "N" and "1" is missing in the PDF page (condition ">200 kHz with no signal at input, 0 dB input attenuation, N [?] 1"); stored as printed with the upper frequency 26.5 GHz (the instrument\'s range), which is not on the page.')
    w('Flatness [Frequency Response, Relative] 13.2 GHz to 22.0 GHz (p.193)', 'Printed "13.2 kHz to 22.0 GHz"; read as 13.2 GHz (note 10). Confirm against the manufacturer if the row is used.')
    w('Flatness [Frequency Response] (p.193)', 'Value range for the flatness rows is the input attenuation (10 dB, printed condition); the amplitude level of the measurement is not specified. Relative flatness is a peak-to-peak-about-midpoint figure; "typical" is a second spec (period "typical"), not a guarantee.')
    w('Residual FM / Span Accuracy rows (pp.183, 184)', 'Per-band rows are DERIVED from the printed formulas with N from p.180 (note 3). Band 0 lower limit stored as 30 Hz (Option 006); non-Option 006 units start at 9 kHz. Bands overlap as printed (Band 1/Band 2 and Band 2/Band 3 ranges overlap on p.180). Span accuracy value range for the upper rows ends at 13.2 GHz (internal-mixing span limit, p.184).')
    w('Reference Oscillator, Frequency Reference Accuracy (p.182)', 'Stored as fractional rel on a 10 MHz reference (note 18); the printed "Settability <+/-1E-6" for Option 103 is stored with period "2 yr" (no period printed). The "after 7 day warmup" daily aging and the yearly aging are separate rows with their own period labels; Non-Option 103 settability is not printed.')
    w('Calibrator Output / 10 MHz REF OUT frequency (p.197)', 'NOT STORED: CAL OUTPUT frequency "300 MHz +/-(300 MHz x frequency reference accuracy)" and 10 MHz REF output frequency "10 MHz +/-(10 MHz x frequency reference accuracy)" have no numeric limit (depends on aging x time since adjustment, initial accuracy and temperature stability, note 18). 10 MHz REF IN/OUT connector information is not stored.')
    w('Sweep Time Accuracy (p.186)', 'Lower end of the "<30 ms" value range (50 us) is taken from the sweep time range table on the same page (analog display 50 us to <30 ms; Option 007 digital 50 us to 6,000 s).')
    problems.extend(sm.validate_data(_data(functions)))
    return functions, problems


def _data(functions):
    return dict(schema=1, standard=dict(
        manufacturer='Agilent', model='8563E', description='Spectrum Analyzer, 9 kHz (30 Hz Opt 006) to 26.5 GHz (8563E / 8563EC)',
        confidence_text='[Not Specified]', confidence_pct=None,
        reference='Agilent 8560 E-Series and EC-Series Spectrum Analyzers Calibration Guide (Volumes I & II), Chapter 5 "8563E/EC Specifications and Characteristics", PDF/printed pp.177-216; '
                  'specifications read from pp.178-197 (PDF page = printed page)',
        revision='8560E/EC Calibration Guide (PDF created 2010-05-20)', author='built from the manual page images by specs/build_8563e_standard_from_manual.py', approved_by='', approve_date='',
        source_pdf='8563 Specifications.pdf', sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes={str(k): v for k, v in NOTES.items()}, functions=functions)


def main():
    functions, problems = build()
    data = _data(functions)
    data['problems'] = problems
    out = HERE / 'standards' / 'agilent_8563e_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in functions)
    print(f'{len(functions)} functions, {n} rows, {len(problems)} problems -> {out}')


if __name__ == '__main__':
    main()
