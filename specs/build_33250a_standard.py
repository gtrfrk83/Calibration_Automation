"""Builds specs/standards/agilent_33250a_standard.json: the Agilent 33250A 80 MHz function / arbitrary waveform generator as a STANDARD (a stimulus source).

    python specs/build_33250a_standard.py            # writes specs/standards/agilent_33250a_standard.json (idempotent: same bytes every run)

SOURCE: 'Agilent 33250A 80 MHz Waveform Generator User's Guide', publication number 33250-90002, Edition 2, March 2003 (337 PDF pages), Chapter 8
'Specifications': printed pp. 319-323 = PDF pp. 321-324 (PDF page = printed page + 1; Output Characteristics and Frequency / Signal Characteristics are on printed
pp. 320-321, 'General Specifications' on printed p. 323).  Every number below was transcribed by eye from RENDERED PAGE IMAGES (pdftoppm 130 dpi, then a second
reading of every block from a 260 dpi crop), never from extracted text (micro and ohm signs get corrupted).  The two readings agree.

WHAT IS STORED (all direction 'output', period '1 yr' = the manual's stated warranted period: 'Accuracy (1 year)', 'Calibration Interval 1 year'):
  * Frequency: +/-(2 ppm of setting), 18 degC to 28 degC, 1 uHz to 80 MHz.  The 3 ppm (0 degC to 55 degC) figure is in note 4 only (a second row would win every plain lookup).
  * Voltage, AC [Sinewave into 50 Ohm, Vpp] (unit Vpp, the manual's own unit): the printed 1 kHz accuracy +/-(1 % of setting + 1 mVpp), and per frequency band the same
    accuracy PLUS the printed flatness (a DERIVED worst-case sum, flagged): 2 % (below 10 MHz), 3 % (10 - 50 MHz), 6 % (50 - 80 MHz), each + 1 mVpp.
  * Flatness [Sinewave relative to 1 kHz]: as printed, +/-1 % (0.1 dB), +/-2 % (0.2 dB), +/-5 % (0.4 dB).
  * Voltage, DC [Offset ...]: +/-(1 % of setting + 2 mV + 0.5 % of amplitude); two functions (DC Volts waveform with amplitude 0; offset under a waveform with
    the amplitude term bounded at the 10 Vpp maximum, flagged).
  * Rise Time (square wave) < 8 ns; Time: square wave asymmetry and jitter (rms), pulse jitter (rms), arb jitter (rms), as printed (percent / ppm of the PERIOD, assumed).
  * Sinewave spectral purity (kind OTHER, '<=' limits in dBc): harmonic distortion, total harmonic distortion, spurious (non-harmonic).
NOT STORED (in 'limits' / notes / 'problems'): ranges and resolutions that carry no accuracy (period, pulse width, edge time, duty cycle, phase offset, amplitude and
frequency ranges), phase noise (typical only), configuration and download times, trigger / burst / sweep / modulation / reference-clock characteristics, general data.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

OUT = HERE / 'standards' / 'agilent_33250a_standard.json'
BUILT = '2026-10-27T00:00:00'        # fixed on purpose: the builder must write the same bytes on every run
PERIOD = '1 yr'
PDF = {'sig': 321, 'out': 322, 'gen': 324}      # printed pp. 320 / 321 / 323 -> PDF pages (printed + 1)

PREFIX = {'p': D('1e-12'), 'n': D('1e-9'), 'u': D('1e-6'), 'm': D('1e-3'), '': D(1), 'k': D('1e3'), 'M': D('1e6')}


def si_text(v, unit):
    v = float(v)
    if v == 0:
        return f'0 {unit}'
    for div, pre in ((1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p')):
        if abs(v) >= div * (1 - 1e-9):
            return f'{v / div:.10g} {pre}{unit}'
    return f'{v:g} {unit}'


def prm(lo, hi, unit, notes=()):
    return dict(tag='', lo=float(lo), hi=float(hi), unit=unit, text=f'{si_text(lo, unit)} to {si_text(hi, unit)}', annot='', notes=list(notes))


def spec(body, rel=None, absval=None, le=False, unit=None):
    """One parsed '1 yr' specification: `body` is the sheet text ('1 % I.V. + 1 mVpp'); the numbers are replaced by the exact Decimal values (`rel` as a
    fraction, `absval` in SI) after checking that specmanager.parse_spec read the same."""
    raw = f'[{PERIOD}] Accuracy: ' + (f'<=({body})' if le else f'+/-({body})')
    s = sm.parse_spec(raw)
    assert 'error' not in s, raw
    if rel is not None:
        assert abs(s['rel'] - float(rel)) <= 1e-12, raw
        s['rel'] = float(rel)
    if absval is not None:
        assert abs(s['abs'] - float(absval)) <= 1e-9 * abs(float(absval)), raw
        s['abs'] = float(absval)
    if unit:
        s['unit'] = unit
    s['raw'] = raw
    return s


def hand_spec(body, absval, unit, rel=0.0):
    """A '<=' limit the sheet text parser cannot read as such (dBc, an rms term with a slope): numbers stored, raw text as printed."""
    return dict(period=PERIOD, rel=float(rel), fs_rel=0.0, fs_value=0.0, abs=float(absval), unit=unit, le=True, raw=f'[{PERIOD}] Accuracy: <=({body})')


def entry(fname, label, page, params, specs, notes=()):
    r = dict(label=label, page=page, params=params, specs=list(specs), raw_other=[])
    r.update(sm.analyse_range(fname, label, params))
    r['printed'] = label
    return r


# ------------------------------------------------------------------------------------------------------------ notes (file-wide ids)
NOTES = {
    1: 'SOURCE: Agilent 33250A 80 MHz Waveform Generator User\'s Guide, publication number 33250-90002, Edition 2, March 2003, Chapter 8 "Specifications", printed pp. 319-323 '
       '(PDF pp. 321-324; row "page" = PDF page = printed page + 1). Read from rendered page images, each block twice; the readings agree. Built by specs/build_33250a_standard.py.',
    2: 'PERIOD AND CONFIDENCE: the manual states the frequency accuracy for "1 year" and a Calibration Interval of 1 year; every figure on this sheet is stored under "1 yr" (default period). '
       'The manual states NO confidence level and no k: "not specified", stored with no level (divisor 2, laboratory convention, as the 8563E / 3458A / T-10A sheets). The manual also says '
       'nothing on whether the figures are warranted limits or typical values except where it writes "typical" (phase noise, impedance), which is NOT stored.',
    3: 'CONDITIONS: output characteristics are into 50 ohm (the open-circuit amplitude range is 20 mVpp to 20 Vpp, printed footnote 2); amplitude and offset accuracy at 1 kHz, above 10 mVpp, '
       'Autorange ON (printed p. 321). Warm-up time 1 hour (general specifications, printed p. 323). Printed footnote 1 of Output Characteristics: add 1/10th of the output amplitude AND offset '
       'specification per degC for operation outside 18 degC to 28 degC (1-year specification); NOT applied to any stored row (a lab at 18 - 28 degC needs nothing).',
    4: 'FREQUENCY (printed p. 320): "Accuracy (1 year): 2 ppm, 18 degC to 28 degC; 3 ppm, 0 degC to 55 degC". Stored: 2 ppm of the setting (+/-(2 ppm I.V.)), range 1 uHz to 80 MHz (sine and square). '
       'The 3 ppm figure for 0 - 55 degC is NOT stored as a row (a plain lookup takes the larger limit of every matching row and would always return 3 ppm). Waveform limits: sine and square 1 uHz - 80 MHz, '
       'ramp 1 uHz - 1 MHz, pulse 500 uHz - 50 MHz, arb 1 uHz - 25 MHz (printed p. 320); the 80 MHz row is the maximum. Resolution 1 uHz, pulse 5 digits (not stored). '
       'The manual prints NO separate ageing or stability figure for the 10 MHz time base: the 2 ppm one-year accuracy is the only time-base specification.',
    5: 'AMPLITUDE (printed p. 321): range 10 mVpp to 10 Vpp into 50 ohm. Accuracy (at 1 kHz, >10 mVpp, Autorange On): +/-(1 % of setting + 1 mVpp). Stored in the manual\'s own unit (Vpp), no conversion to Vrms. '
       '"Setting" is the amplitude setting in Vpp (units Vpp, Vrms, dBm, High / Low level are all selectable; the spec is printed in Vpp). Resolution 0.1 mV or 4 digits (not stored).',
    6: 'FLATNESS (printed p. 321): sinewave relative to 1 kHz, Autorange On: below 10 MHz +/-1 % (0.1 dB), 10 MHz to 50 MHz +/-2 % (0.2 dB), 50 MHz to 80 MHz +/-5 % (0.4 dB). Printed footnote 3: dB rounded to 1 digit; '
       'the instrument adheres to the "%" specification (so the % figures are stored). The lower edge of "<10 MHz" is not printed: 1 uHz (the lowest sine frequency) is used.',
    7: 'DERIVED ROWS (not printed as such): the "Voltage, AC [Sinewave into 50 Ohm, Vpp]" rows for frequency bands are the 1 kHz accuracy (1 % + 1 mVpp) PLUS the printed flatness of the band (arithmetic worst-case sum: 2 %, 3 %, 6 % + 1 mVpp); '
       'the manual does not say how the two combine. The 1 kHz row is the printed accuracy alone; the bands next to it start / stop 1 uHz away (999.999999 Hz, 1000.000001 Hz, the frequency resolution) so that exactly 1 kHz '
       'finds only the printed row. A frequency exactly on 10 MHz or 50 MHz takes the worse (higher) row (NOTES.md "Frequency band edges").',
    8: 'OFFSET (printed p. 321): range +/-5 V peak (ac + dc) into 50 ohm. Accuracy: 1 % of setting + 2 mV + 0.5 % of amplitude. The amplitude term depends on the waveform amplitude, which the schema cannot hold per point: '
       'function "[Offset, DC Volts waveform, 50 Ohm]" assumes amplitude 0 (+/-(1 % I.V. + 2 mV)); function "[Offset under a waveform, 50 Ohm]" bounds the term at the 10 Vpp maximum (0.5 % x 10 Vpp = 50 mV, stored as 0.5 % F.S., '
       'Full Scale = 10 Vpp). "Amplitude" is taken as the Vpp setting (UNVERIFIED). The plain DCV lookup returns the larger (waveform) row; ask for variant "DC Volts" for the amplitude-0 case.',
    9: 'SQUARE WAVE (printed p. 320): rise / fall time < 8 ns (printed footnote 4: edge time is decreased at higher frequency), overshoot < 5 %, asymmetry 1 % of period + 1 ns, jitter (rms) below 2 MHz 0.01 % + 525 ps and '
       '2 MHz and above 0.1 % + 75 ps; duty cycle 20.0 % to 80.0 % (to 25 MHz), 40.0 % to 60.0 % (25 - 50 MHz), 50.0 % fixed (50 - 80 MHz). "%" is taken as per cent of the PERIOD (the manual says "1% of period" for asymmetry and '
       'nothing for the jitter terms: ASSUMED the same). Rise time is stored as a "<=" limit (the manual prints "<").',
    10: 'JITTER IS rms: the figures are a standard deviation (one sigma), not a bound; they are stored as +/-(...) terms so the lookup returns the printed magnitude, but a budget that divides a sheet value by the coverage divisor '
        '(2) would halve a quantity that is already a standard deviation. Nothing selects the TIME rows of this sheet today.',
    11: 'PULSE (printed p. 320): period 20.00 ns to 2000.0 s, pulse width 8.0 ns to 1999.9 s, variable edge time 5.00 ns to 1.00 ms, overshoot < 5 %, jitter (rms) 100 ppm + 50 ps. The manual prints NO accuracy for pulse '
        'width, period or edge time (only ranges and resolution digits): none is stored. ARB (printed p. 320): minimum edge time < 10 ns, linearity < 0.1 % of peak output, settling time < 50 ns to 0.5 % of final value, '
        'jitter (rms) 30 ppm + 2.5 ns. RAMP: linearity < 0.1 % of peak output, symmetry 0.0 % to 100.0 %.',
    12: 'SPECTRAL PURITY (printed p. 320), sine, kind OTHER (limits in dBc, "<=" rows): harmonic distortion < 3 Vpp / > 3 Vpp: DC - 1 MHz -60 / -55 dBc, 1 - 5 MHz -57 / -45 dBc, 5 - 80 MHz -37 / -30 dBc (footnote 2: low amplitudes '
        'limited by a -70 dBm floor); total harmonic distortion DC to 20 kHz < 0.2 % + 0.1 mVrms; spurious (non-harmonic) DC - 1 MHz -60 dBc, 1 - 20 MHz -50 dBc, 20 - 80 MHz -50 dBc + 6 dBc/octave (footnote 3: limited by a -75 dBm floor). '
        'The 6 dBc/octave slope is only in the row text; the stored number is -50 dBc. "3 Vpp" itself sits in both columns of the printed table (< 3 / > 3): stored as 0 - 3 Vpp and 3 - 10 Vpp.',
    13: 'TYPICAL ONLY, NOT STORED: phase noise (30 kHz band) < -65 dBc at 10 MHz and < -47 dBc at 80 MHz (printed "typical"); waveform output impedance 50 ohm typical. Other printed items not stored: arbitrary waveform length / '
        'sample rate / memory, configuration and arb download times, trigger input / output, burst, sweep, modulation, phase offset (range -360 deg to +360 deg, resolution 0.001 deg; no accuracy printed), clock reference '
        '(external lock 10 MHz +/- 35 kHz; internal reference output 10 MHz, 632 mVpp), sync output, general specifications.',
}

LIMITS = [
    dict(function='Frequency', limit='Accuracy (1 year) +/-2 ppm 18 - 28 degC, +/-3 ppm 0 - 55 degC; range sine / square 1 uHz - 80 MHz, ramp 1 MHz, pulse 500 uHz - 50 MHz, arb 25 MHz; resolution 1 uHz (pulse 5 digits).', page='321'),
    dict(function='Voltage, AC / Flatness', limit='Into 50 ohm: 10 mVpp to 10 Vpp; accuracy at 1 kHz, >10 mVpp, Autorange On +/-(1 % + 1 mVpp); flatness rel. to 1 kHz <10 MHz +/-1 %, 10 - 50 MHz +/-2 %, 50 - 80 MHz +/-5 %.', page='322'),
    dict(function='Voltage, DC [Offset]', limit='+/-5 Vpk ac + dc into 50 ohm; accuracy 1 % of setting + 2 mV + 0.5 % of amplitude.', page='322'),
    dict(function='Pulse', limit='Period 20.00 ns to 2000.0 s; width 8.0 ns to 1999.9 s; variable edge time 5.00 ns to 1.00 ms; overshoot < 5 %; jitter (rms) 100 ppm + 50 ps. No accuracy printed for period / width / edge.', page='321'),
    dict(function='Square wave', limit='Rise / fall < 8 ns; overshoot < 5 %; asymmetry 1 % of period + 1 ns; duty cycle 20 - 80 % (<= 25 MHz), 40 - 60 % (25 - 50 MHz), 50 % fixed (50 - 80 MHz).', page='321'),
]


def build():
    functions, problems = [], []

    # ---- Frequency (the 10 MHz time base)
    fn = 'Frequency'
    f = dict(name=fn, direction='output', page=PDF['sig'], ranges=[
        entry(fn, '1 µHz to 80 MHz (18 °C to 28 °C)', PDF['sig'], [prm(1e-6, 8e7, 'Hz', [4])], [spec('2 ppm I.V.', rel=D('2e-6'))])])
    functions.append(f)

    # ---- Voltage, AC sine into 50 ohm, unit Vpp: the printed 1 kHz accuracy and the derived frequency bands
    fn = 'Voltage, AC [Sinewave into 50 Ohm, Vpp]'
    f = dict(name=fn, direction='output', page=PDF['out'], ranges=[])
    amp = (0.01, 10.0)
    fixed = D('0.001')
    acv = [   # (label, f lo, f hi, per cent of setting, notes)
        ('1 kHz (printed accuracy)', 1000.0, 1000.0, D('1'), [3, 5]),
        ('1 µHz to 999.999999 Hz (accuracy + flatness)', 1e-6, 999.999999, D('2'), [3, 5, 6, 7]),
        ('1000.000001 Hz to 10 MHz (accuracy + flatness)', 1000.000001, 1e7, D('2'), [3, 5, 6, 7]),
        ('10 MHz to 50 MHz (accuracy + flatness)', 1e7, 5e7, D('3'), [3, 5, 6, 7]),
        ('50 MHz to 80 MHz (accuracy + flatness)', 5e7, 8e7, D('6'), [3, 5, 6, 7]),
    ]
    for label, flo, fhi, pct, notes in acv:
        ps = [prm(amp[0], amp[1], 'Vpp', notes), prm(flo, fhi, 'Hz')]
        f['ranges'].append(entry(fn, f'10 mVpp to 10 Vpp @ {label}', PDF['out'], ps, [spec(f'{pct} % I.V. + 1 mVpp', rel=pct / 100, absval=fixed, unit='Vpp')]))
    functions.append(f)

    # ---- Flatness relative to 1 kHz (as printed)
    fn = 'Flatness [Sinewave relative to 1 kHz, 50 Ohm]'
    f = dict(name=fn, direction='output', page=PDF['out'], ranges=[])
    for label, flo, fhi, pct, db in (('below 10 MHz', 1e-6, 1e7, D('1'), '0.1 dB'), ('10 MHz to 50 MHz', 1e7, 5e7, D('2'), '0.2 dB'), ('50 MHz to 80 MHz', 5e7, 8e7, D('5'), '0.4 dB')):
        ps = [prm(amp[0], amp[1], 'Vpp', [6]), prm(flo, fhi, 'Hz')]
        s = spec(f'{pct} % I.V.', rel=pct / 100, unit='Vpp')
        f['ranges'].append(entry(fn, f'10 mVpp to 10 Vpp, {label} ({db})', PDF['out'], ps, [s]))
    functions.append(f)

    # ---- Offset (DC volts)
    fn = 'Voltage, DC [Offset, DC Volts waveform, 50 Ohm]'
    f = dict(name=fn, direction='output', page=PDF['out'], ranges=[
        entry(fn, '-5 V to 5 V (amplitude 0)', PDF['out'], [prm(-5, 5, 'V', [8])], [spec('1 % I.V. + 2 mV', rel=D('0.01'), absval=D('0.002'), unit='V')])])
    functions.append(f)
    fn = 'Voltage, DC [Offset under a waveform, 50 Ohm]'
    s = sm.parse_spec(f'[{PERIOD}] Accuracy: +/-(1 % I.V. + 2 mV + 0.5 % F.S.{{"Full Scale" = 10 Vpp}})')
    assert 'error' not in s
    s.update(rel=0.01, abs=0.002, fs_rel=0.005, fs_value=10.0, unit='V')
    f = dict(name=fn, direction='output', page=PDF['out'], ranges=[entry(fn, '-5 V to 5 V (amplitude up to 10 Vpp)', PDF['out'], [prm(-5, 5, 'V', [8])], [s])])
    functions.append(f)

    # ---- Rise time
    fn = 'Rise Time [Square wave into 50 Ohm]'
    f = dict(name=fn, direction='output', page=PDF['sig'], ranges=[
        entry(fn, 'Rise / fall time, square wave', PDF['sig'], [prm(0, 0, 's', [9])], [spec('8 ns', absval=D('8e-9'), le=True, unit='s')])])
    functions.append(f)

    # ---- Time: asymmetry and jitter, value = the period (square 12.5 ns to 1e6 s, ...)
    def time_fn(fn, label, lo, hi, body, rel, absval, notes):
        s = spec(body, rel=rel, absval=absval, unit='s')
        return dict(name=fn, direction='output', page=PDF['sig'], ranges=[entry(fn, label, PDF['sig'], [prm(lo, hi, 's', notes)], [s])])
    functions.append(time_fn('Time [Square wave Asymmetry]', 'Period 12.5 ns to 1,000,000 s', 12.5e-9, 1e6, '1 % I.V. + 1 ns', D('0.01'), D('1e-9'), [9]))
    functions.append(time_fn('Time [Square wave Jitter (rms), below 2 MHz]', 'Period 500 ns to 1,000,000 s (below 2 MHz)', 5e-7, 1e6, '0.01 % I.V. + 525 ps', D('1e-4'), D('5.25e-10'), [9, 10]))
    functions.append(time_fn('Time [Square wave Jitter (rms), 2 MHz and above]', 'Period 12.5 ns to 500 ns (2 MHz and above)', 12.5e-9, 5e-7, '0.1 % I.V. + 75 ps', D('1e-3'), D('7.5e-11'), [9, 10]))
    functions.append(time_fn('Time [Pulse Jitter (rms)]', 'Period 20 ns to 2000 s', 20e-9, 2000.0, '100 ppm I.V. + 50 ps', D('1e-4'), D('5e-11'), [10, 11]))
    functions.append(time_fn('Time [Arb Jitter (rms)]', 'Period 40 ns to 1,000,000 s', 40e-9, 1e6, '30 ppm I.V. + 2.5 ns', D('3e-5'), D('2.5e-9'), [10, 11]))

    # ---- Sinewave spectral purity (kind OTHER, limits in dBc)
    fn = 'Sinewave Spectral Purity [Harmonic Distortion]'
    f = dict(name=fn, direction='output', page=PDF['sig'], ranges=[])
    harm = ((0.0, 1e6, 'DC to 1 MHz', -60, -55), (1e6, 5e6, '1 MHz to 5 MHz', -57, -45), (5e6, 8e7, '5 MHz to 80 MHz', -37, -30))
    for flo, fhi, label, lo_amp, hi_amp in harm:
        for (alo, ahi), val, tag in (((0.0, 3.0), lo_amp, '< 3 Vpp'), ((3.0, 10.0), hi_amp, '> 3 Vpp')):
            ps = [prm(alo, ahi, 'Vpp', [12]), prm(flo, fhi, 'Hz')]
            f['ranges'].append(entry(fn, f'{tag}, {label}', PDF['sig'], ps, [hand_spec(f'{val} dBc', val, 'dBc')]))
    functions.append(f)
    fn = 'Sinewave Spectral Purity [Total Harmonic Distortion]'
    f = dict(name=fn, direction='output', page=PDF['sig'], ranges=[
        entry(fn, 'DC to 20 kHz (0.1 mV is rms)', PDF['sig'], [prm(0.0, 2e4, 'Hz', [12])], [hand_spec('0.2 % I.V. + 0.1 mV', 1e-4, 'V', rel=0.002)])])
    functions.append(f)
    fn = 'Sinewave Spectral Purity [Spurious (non-harmonic)]'
    f = dict(name=fn, direction='output', page=PDF['sig'], ranges=[])
    for flo, fhi, label, val, extra in ((0.0, 1e6, 'DC to 1 MHz', -60, ''), (1e6, 2e7, '1 MHz to 20 MHz', -50, ''), (2e7, 8e7, '20 MHz to 80 MHz', -50, ' + 6 dBc/octave')):
        f['ranges'].append(entry(fn, label, PDF['sig'], [prm(flo, fhi, 'Hz', [12])], [hand_spec(f'{val} dBc{extra}', val, 'dBc')]))
    functions.append(f)

    data = dict(schema=1, standard=dict(
        manufacturer='Agilent', model='33250A', description='80 MHz function / arbitrary waveform generator (stimulus source: frequency, amplitude, offset, pulse timing)',
        confidence_text='not specified in the manual (divisor 2, laboratory convention)', confidence_pct=None,
        reference="Agilent 33250A 80 MHz Waveform Generator User's Guide, 33250-90002, Edition 2, March 2003, Chapter 8 Specifications, printed pp. 319-323 (PDF pp. 321-324)",
        revision='Edition 2, March 2003', author='built from the manual page images by specs/build_33250a_standard.py', approved_by='', approve_date='',
        source_pdf='Agilent 33250A User Manual.pdf', sheet_generated='', built=BUILT),
        notes={str(k): v for k, v in NOTES.items()}, limits=LIMITS, functions=functions)

    def w(where, what, level='warn'):
        problems.append(dict(level=level, where=where, what=what))
    w('standard', "Source: Agilent 33250A User's Guide, 33250-90002 Edition 2 (March 2003), Chapter 8, printed pp. 319-323. Row 'page' fields are PDF page numbers (printed page + 1). Read from rendered images, each block twice.")
    w('standard', 'Period "1 yr" (the manual states the accuracy for 1 year and a 1 year calibration interval). No confidence level / k is printed: stored with no level, divisor 2 (laboratory convention). ASSUMED.')
    w('Frequency', 'The manual prints no separate ageing / stability figure for the 10 MHz time base; only "Accuracy (1 year) 2 ppm, 18 - 28 degC; 3 ppm, 0 - 55 degC". The 3 ppm figure is in the notes only; the lab temperature range is assumed to be 18 - 28 degC.')
    w('Voltage, AC [Sinewave into 50 Ohm, Vpp]', 'DERIVED: the frequency-band rows add the printed flatness to the printed 1 kHz accuracy (arithmetic sum, 2 % / 3 % / 6 % + 1 mVpp); the manual does not print the combination. The 1 kHz row is the printed figure.')
    w('Voltage, AC [Sinewave into 50 Ohm, Vpp]', 'Unit Vpp as printed: the rows are EXCLUDED from a plain AC volts lookup (specmanager.DEFAULT_VARIANT excludes "vpp", a value in V rms would match the wrong band); ask for variant "Vpp". ">10 mVpp" is printed for the accuracy; the 10 mVpp lower edge is stored.')
    w('Voltage, AC [Sinewave into 50 Ohm, Vpp]', 'Band edges 999.999999 Hz and 1000.000001 Hz (1 uHz either side of 1 kHz) keep exactly 1 kHz on the printed row; the lower edge of "<10 MHz" is not printed (1 uHz assumed).')
    w('Voltage, DC [Offset under a waveform, 50 Ohm]', 'The "0.5 % of amplitude" term depends on the waveform amplitude, which the sheet cannot hold per point: bounded at the 10 Vpp maximum (50 mV). UNVERIFIED that "amplitude" means the Vpp setting. A plain DCV lookup returns this larger row.')
    w('Voltage, DC [Offset, DC Volts waveform, 50 Ohm]', 'ASSUMED: the DC Volts waveform has amplitude 0, so the amplitude term is 0. The manual does not say so.')
    w('Time', 'Jitter (rms) rows are one-sigma standard deviations stored as +/-(...) magnitudes; "%" of the period is ASSUMED for the jitter terms (the manual says "of period" only for asymmetry). A budget dividing by the divisor would halve an already-standard figure.')
    w('Time', 'The manual prints NO accuracy for pulse width, period, edge time or duty cycle (ranges and resolution digits only): none stored (see "limits"). Owner to say whether a pulse-width accuracy is wanted from the service guide.')
    w('Rise Time [Square wave into 50 Ohm]', 'Printed "< 8 ns" (footnote 4: decreased at higher frequency), stored as "<=" 8 ns, value range 0 (the 5522A rise-time convention).')
    w('Sinewave Spectral Purity', 'Kind OTHER, "<=" limits in dBc (the 8563E convention); the 20 - 80 MHz spurious slope "+ 6 dBc/octave" is in the text only; THD stored as 0.2 % + 0.1 mV (rms). Phase noise is "typical" in the manual and is NOT stored.')
    w('standard', 'NOT STORED (printed, no accuracy or typical only): resolution (frequency 1 uHz, pulse 5 digits; amplitude 0.1 mV or 4 digits), phase offset, amplitude / frequency / period / pulse width / edge time ranges, phase noise (typical), impedance (50 ohm typical), '
                  'trigger, burst, sweep, modulation, reference clock, sync, configuration and download times, general specifications (see notes 11 and 13).')
    problems.extend(sm.validate_data(data))
    data['problems'] = problems
    return data


def main():
    data = build()
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    print(f"33250A: {len(data['functions'])} functions, {n} ranges, {len(data['problems'])} problems -> {out}")
    for p in data['problems']:
        if p['level'] == 'error' or 'validate' in p.get('where', ''):
            print(p['level'].upper(), p['where'], '-', p['what'])


if __name__ == '__main__':
    main()
