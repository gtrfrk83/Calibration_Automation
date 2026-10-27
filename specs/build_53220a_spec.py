"""Writes specs/keysight_53220a_pv.json (Keysight 53210A / 53220A / 53230A universal frequency counter / timer, performance verification).

Source: Keysight 53210A/53220A/53230A 350 MHz Universal Frequency Counter/Timer, Assembly Level Service Guide, chapter 1 "Performance Tests"
(PDF page = printed page for this file):
    Operational verification            pp. 29-36   (Self-Test p. 31; frequency checks p. 33; termination checks p. 35)
    Table 1-1 equipment                 p. 28
    Test 1  Absolute time base          pp. 38-43   (Q)
    Test 2  Frequency accuracy ch 1, 2  pp. 44-50   (Q)
    Test 3  Single period               pp. 50-55   53220A / 53230A
    Test 4  Pulse width                 pp. 56-61   (Q) 53220A / 53230A
    Test 5  Time interval               pp. 61-65   (Q) 53220A / 53230A
    Test 6a Option 106 microwave        pp. 66-71   (Q)
    Test 6b Option 115 microwave        pp. 72-77   (Q)
    Test 7  Pulse burst frequency       pp. 77-89   53230A, Option 150 (+ 106 or 115)   7a / 7c are (Q)
    Performance Test Record             pp. 90-99   (the limits below are the ones printed there; each was also compared with the test text)
Every limit, nominal and frequency was read from the RENDERED PAGE IMAGES (pdftoppm), twice.  Text extraction was used only to find the pages.  The Programmer's
Reference (518 pp.) covers the 53220A and 53230A ONLY, so every 53210A SCPI command (including the microwave channel being Channel 2) is UNVERIFIED.

LIMITS: the record pages print "Minimum / Maximum" for the mean and a maximum for the standard deviation.  The builder stores them exactly as printed (Decimal, base
units Hz / s).  Per model a point has limits{model: {low, high, printed}} (mean) or limits{model: {max, printed}} (Std Dev: the statistic must be at or below it;
0 .. max is the band).  Test 1 has limits for each time-base option and each period (counter in operation 1 year or less / more than 1 year: footnotes [a] / [b]).

CROSS-CHECK (this script ABORTS if a printed limit disagrees with the pattern below; a documented exception is kept as printed and flagged, never changed):
  The mean half-width of Tests 2 and 6 is 1e-9 x f (53220A / 53230A) and 1e-8 x f (53210A) at every frequency; the Std Dev maximum is 7e-9 x f (53220A),
  1.4e-9 x f (53230A) and 1.4e-8 x f (53210A).  This is the published frequency accuracy for a 10 ms gate: systematic uncertainty 10 ps / gate (53220A, 53230A,
  resolution-enhanced) or 100 ps / gate (53210A) and a random uncertainty 1.4 x TSS / (RE x gate) with TSS 100 ps (53210A, 53220A) or 20 ps (53230A) and RE 1 (53210A) or 2
  (53220A, 53230A).  Single period (Test 3): half-width = Taccuracy 200 ps (53220A) / 100 ps (53230A), Std Dev = 1.4 x TSS (140 ps / 28 ps).  Pulse width (Test 4): half-width
  2 x Taccuracy, Std Dev 1.4 x TSS.  Burst (Test 7): systematic 200 ps (6 GHz narrow) / 400 ps (15 GHz narrow) / burst width; wide: 100 ps (6 GHz) / 200 ps (15 GHz) per burst
  width with RE 1; random 100 ps (narrow) / 40 ps (6 GHz wide) / 75 ps (15 GHz wide) per burst width.  Test 1: +/-1 ppm (standard time base) and +/-50 ppb (Option 010) = the 1-year
  aging; halved (0.5 ppm, 25 ppb) = the 2-year aging figures.
  THE FORMULAS WERE NOT SUPPLIED: they come from the 53200A series data sheet 5990-6283EN as extracted from a third-party mirror (xdevs.com) with the fractions flattened by the
  extraction.  They are listed as UNVERIFIED in the spec ('datasheet_check') and in the final report; the data sheet was not read from page images.

PRINTED DISCREPANCIES kept as printed and flagged (see 'flags'):
  * Test 7c record page (p. 99) prints a minimum of 1.348 865 000 GHz; the test text (p. 88) says 1.35 GHz +/- 1.35 MHz, which is 1.348 650 000 GHz (the maximum, 1.351 350 000,
    agrees with the text).  The stricter record-page value is APPLIED (never loosened without the owner), the text value is shown in the flag.
  * Test 6a 5.88 GHz, 53220A Std Dev: printed 41.100 Hz; 7e-9 x 5.88 GHz = 41.16 Hz (the other printed Std Dev values are truncated the same way: 82.32 -> 82.3, 8.232 -> 8.23).
  * Test 5 step 4 says "Record the Median"; steps 2 and the record say the Mean: the Mean is used.
  * Test 6b header says -23 dBm at 300 MHz; the 3.1 GHz step says -27 dBm; the 15 GHz step says -4 dBm (all three used as printed).
  * Test 1 limits are HALVED for a counter in operation more than 1 year (footnote only): both sets are built; the operator chooses.

Run:  python specs/build_53220a_spec.py
"""
import json
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keysight_53220a_pv.json'
DOC = 'Keysight 53210A/53220A/53230A Assembly Level Service Guide'
MODELS = ('53210A', '53220A', '53230A')
SCALE = {'GHz': D('1e9'), 'MHz': D('1e6'), 'kHz': D('1e3'), 'Hz': D(1), 'mHz': D('1e-3'),
         'uSec': D('1e-6'), 'nSec': D('1e-9'), 'nSecs': D('1e-9')}


def val(text):
    """'114.999 999 885 MHz' / '2 450.000 000 mHz' -> Decimal in base units (Hz or s)."""
    number, unit = text.rsplit(' ', 1)
    return D(number.replace(' ', '')) * SCALE[unit]


def num(d):
    """JSON number: the Decimal as a float (its shortest repr is the printed value in base units)."""
    return float(d)


def band(lo, hi):
    return {'low': num(val(lo)), 'high': num(val(hi)), 'printed': f'{lo} .. {hi}'}


def smax(text):
    return {'max': num(val(text)), 'printed': f'< {text}'}


# ---- Test 1 (record p. 91; test p. 38-43): time-base option x period ----------------------------------------------------------------------------------
T1 = {'std': {'1y': band('9.999 990 000 MHz', '10.000 010 000 MHz'), 'gt1y': band('9.999 995 000 MHz', '10.000 005 000 MHz')},
      '010': {'1y': band('9.999 999 500 MHz', '10.000 000 500 MHz'), 'gt1y': band('9.999 999 750 MHz', '10.000 000 250 MHz')}}

# ---- Test 2 (record pp. 91-93): per model, per frequency ----------------------------------------------------------------------------------------------
T2 = {  # frequency (Hz): {model: (mean low, mean high, std dev max)}
    10e6: {'53210A': ('9.999 999 900 MHz', '10.000 000 100 MHz', '140.000 mHz'),
           '53220A': ('9.999 999 990 MHz', '10.000 000 010 MHz', '70.000 000 mHz'),
           '53230A': ('9.999 999 990 MHz', '10.000 000 010 MHz', '14.000 000 mHz')},
    115e6: {'53210A': ('114.999 998 850 MHz', '115.000 001 150 MHz', '1 610.000 mHz'),
            '53220A': ('114.999 999 885 MHz', '115.000 000 115 MHz', '805.000 000 mHz'),
            '53230A': ('114.999 999 885 MHz', '115.000 000 115 MHz', '161.000 000 mHz')},
    350e6: {'53210A': ('349.999 996 500 MHz', '350.000 003 500 MHz', '4 900.000 mHz'),
            '53220A': ('349.999 999 650 MHz', '350.000 000 350 MHz', '2 450.000 000 mHz'),
            '53230A': ('349.999 999 650 MHz', '350.000 000 350 MHz', '490.000 000 mHz')},
}
# ---- Test 3 single period (record p. 94), 53220A / 53230A -------------------------------------------------------------------------------------------
T3 = {  # frequency: {model: (low, high, std dev max)}
    1e6: {'53220A': ('0.999 800 000 uSec', '1.000 200 000 uSec', '0.140 000 000 nSec'),
          '53230A': ('0.999 900 000 uSec', '1.000 100 000 uSec', '0.028 000 000 nSec')},
    250e6: {'53220A': ('0.003 800 000 uSec', '0.004 200 000 uSec', '0.140 000 000 nSec'),
            '53230A': ('0.003 900 000 uSec', '0.004 100 000 uSec', '0.028 000 000 nSec')},
}
# ---- Test 4 pulse width (record p. 95) and Test 5 time interval (record p. 96) ---------------------------------------------------------------------------
T4 = {'53220A': ('4.600 000 000 nSec', '5.400 000 000 nSec', '0.140 000 000 nSec'), '53230A': ('4.800 000 000 nSec', '5.200 000 000 nSec', '0.028 000 000 nSec')}
T5 = {'53220A': ('49.400 000 000 nSecs', '50.400 000 000 nSec', '0.140 000 000 nSec'), '53230A': ('49.650 000 000 nSecs', '50.150 000 000 nSec', '0.028 000 000 nSec')}
# ---- Test 6 microwave channel (record pp. 96-98): 6a Option 106, 6b Option 115 ----------------------------------------------------------------------------
T6A = {100e6: {'53210A': ('99.999 999 000 MHz', '100.000 001 000 MHz', '1 400.000 000 mHz'),
               '53220A': ('99.999 999 900 MHz', '100.000 000 100 MHz', '700.000 000 mHz'),
               '53230A': ('99.999 999 900 MHz', '100.000 000 100 MHz', '140.000 000 mHz')},
       5.88e9: {'53210A': ('5.879 999 941 200 GHz', '5.880 000 058 800 GHz', '82.300 000 000 Hz'),
                '53220A': ('5.879 999 994 120 GHz', '5.880 000 005 880 GHz', '41.100 000 000 Hz'),
                '53230A': ('5.879 999 994 120 GHz', '5.880 000 005 880 GHz', '8.230 000 000 Hz')}}
T6B = {300e6: {'53210A': ('299.999 997 MHz', '300.000 003 MHz', '4.2 Hz'),
               '53220A': ('299.999 999 7 MHz', '300.000 000 3 MHz', '2.1 Hz'),
               '53230A': ('299.999 999 7 MHz', '300.000 000 3 MHz', '0.42 Hz')},
       3.1e9: {'53210A': ('3.099 999 969 GHz', '3.100 000 031 GHz', '43.4 Hz'),
               '53220A': ('3.099 999 996 9 GHz', '3.100 000 003 1 GHz', '21.7 Hz'),
               '53230A': ('3.099 999 996 9 GHz', '3.100 000 003 1 GHz', '4.34 Hz')},
       15e9: {'53210A': ('14.999 999 850 GHz', '15.000 000 150 GHz', '210 Hz'),
              '53220A': ('14.999 999 985 GHz', '15.000 000 015 GHz', '105 Hz'),
              '53230A': ('14.999 999 985 GHz', '15.000 000 015 GHz', '21 Hz')}}
# ---- Test 7 pulse burst (record pp. 98-99), 53230A only ---------------------------------------------------------------------------------------------------
T7 = [  # (id, carrier Hz, level dBm, burst width s, narrow, dB level, option, mean low, mean high, std dev max, text limit)
    ('7a', 6e9, 0.0, 200e-9, True, -12, '106', '5.994 000 000 GHz', '6.006 000 000 GHz', '3.000 MHz', '6 GHz +/- 6 MHz'),
    ('7b', 6e9, 0.0, 13e-6, False, -6, '106', '5.999 954 000 GHz', '6.000 046 000 GHz', '18.500 kHz', '6 GHz +/- 46 kHz'),
    ('7c', 1.35e9, -6.0, 400e-9, True, -6, '115', '1.348 865 000 GHz', '1.351 350 000 GHz', '338 kHz', '1.35 GHz +/- 1.35 MHz'),
    ('7d', 1.35e9, -6.0, 13e-6, False, -6, '115', '1.349 979 200 GHz', '1.350 020 800 GHz', '7.79 kHz', '1.35 GHz +/- 20.8 kHz'),
]

DOC_PAGES = {'1': '38-43 (record p. 91)', '2a': '44-49 (record p. 92)', '2b': '44-49 (record p. 93)', '3': '50-55 (record p. 94)', '4a': '56-60 (record p. 95)',
             '4b': '56-60 (record p. 95)', '5': '61-65 (record p. 96)', '6a': '66-71 (record pp. 96-97)', '6b': '72-77 (record pp. 97-98)',
             '7a': '78-83 (record p. 98)', '7b': '78-83 (record p. 99)', '7c': '84-89 (record p. 99)', '7d': '84-89 (record p. 99)', 'OV2': '31'}


def fmt_si(value, unit):
    """Description text for a stimulus value."""
    for scale, prefix in ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1.0, '')):
        if abs(value) >= scale:
            return f'{value / scale:g} {prefix}{unit}'
    return f'{value:g} {unit}'


def fmt_time(t):
    for scale, prefix in ((1.0, ''), (1e-3, 'm'), (1e-6, 'u'), (1e-9, 'n')):
        if abs(t) >= scale * 0.999:
            return f'{t / scale:g} {prefix}s'
    return f'{t:g} s'


def stat_pair(base, mean_limits, sdev_limits, **common):
    """The Mean point and the Std Dev point of one measurement (the Std Dev point follows its Mean point and reuses the same 100 readings)."""
    mean = dict(common, ref=base + '.mean', stat='mean', limits=mean_limits)
    sdev = dict(common, ref=base + '.sdev', stat='sdev', limits=sdev_limits, parent=base + '.mean')
    return [mean, sdev]


def build():
    sections = []
    # ---------------------------------------------------------------- operational verification
    sections.append(dict(id='ov', title='Operational verification: self-test', page='29-36 (Self-Test p. 31)', setup=(
        'Power on and let the counter finish its power-on test.  The program sends *TST? (Programmer\'s Reference p. 201: 0 = all tests passed, 1 = at least one failed; '
        'it takes more than 5 seconds and the counter then does a Factory Reset).  The frequency checks (p. 33) and the termination checks (p. 35) print no numeric limit '
        '("approximately 10 MHz", "approximately 50 ohm" / "1 Mohm") and need a DMM for the terminations: they are NOT built as pass / fail points.'),
        points=[dict(ref='OV2', test='OV2', func='TST', kind='TST', channel=None, unit='', nominal=0.0, stat='pass', quick=True, requires=[], timebase=None,
                     stimulus=dict(group='NONE'), page=DOC_PAGES['OV2'],
                     limits={m: {'low': 0.0, 'high': 0.0, 'printed': '0 (pass)'} for m in MODELS})]))

    # ---------------------------------------------------------------- Test 1
    t1 = dict(ref='1.10MHz.mean', test='1', func='FREQ', kind='FREQ', channel=1, unit='Hz', nominal=10e6, stat='mean', quick=True, requires=[], timebase='INT',
              gate_s=None, stimulus=dict(group='LH', frequency=10e6, level_dbm=7.0), page=DOC_PAGES['1'],
              limits={m: T1 for m in MODELS}, limits_by='timebase_option',
              flags=['Limits for a counter in operation MORE than 1 year are half of the 1-year limits (footnotes [a] and [b], record p. 91; test text p. 43): both are built, the operator picks the period.',
                     'The limits assume the primary frequency standard (better than 1e-10) replaced the factory calibration uncertainty and a calibration at 23 +/- 5 C (p. 43).'])
    sections.append(dict(id='t1', title='Test 1: Absolute time base', page='38-43', setup=(
        'Source: 10 MHz, +7 dBm into Channel 1 (50 ohm), locked to the 10 MHz primary frequency standard (FS725 Rubidium, better than 1e-10).  The counter uses its INTERNAL '
        'time base.  Preset; trigger Manual; 100 readings per trigger; noise rejection Off; Ch1 DC coupling, 50 ohm, 5 V range, auto level Off, level 0.000 V, bandwidth '
        'limit Off, probe 1:1; statistics On.  Mean must be 10 MHz +/- 10 Hz (standard time base) or +/- 0.5 Hz (Option 010); half of that for a counter in operation more than 1 year.'),
        points=[t1]))

    # ---------------------------------------------------------------- Test 2
    pts = []
    for test, ch in (('2a', 1), ('2b', 2)):
        for f, row in T2.items():
            mods = {m: row[m] for m in row if not (test == '2b' and m == '53210A')}
            label = fmt_si(f, 'Hz').replace(' ', '')
            pts += stat_pair(f'{test}.{label}', {m: band(r[0], r[1]) for m, r in mods.items()}, {m: smax(r[2]) for m, r in mods.items()}, test=test, func='FREQ', kind='FREQ',
                             channel=ch, unit='Hz', nominal=f, quick=True, requires=[], timebase='EXT', gate_s=0.01, stimulus=dict(group='LH', frequency=f, level_dbm=7.0),
                             page=DOC_PAGES[test])
    sections.append(dict(id='t2', title='Test 2: Frequency accuracy, channels 1 and 2', page='44-50', setup=(
        'Source: 10, 115 and 350 MHz at +7 dBm into Channel 1, then Channel 2 (the 53210A has no Channel 2).  The counter uses an EXTERNAL 10 MHz reference on Ext Ref In '
        '(the FS725 house standard).  Preset; Auto measurement mode; noise rejection Off; trigger Manual; 100 readings; gate Timed 10 ms, Gate Out On, polarity Normal; '
        'channel DC, 50 ohm, 5 V range, bandwidth limit Off, auto level Off, level 0.000 V; statistics On.  Mean and Std Dev are judged against the record-page limits.'),
        points=pts))

    # ---------------------------------------------------------------- Test 3
    pts = []
    for ch in (1, 2):
        for f, row in T3.items():
            label = fmt_si(f, 'Hz').replace(' ', '')
            pts += stat_pair(f'3.ch{ch}.{label}', {m: band(r[0], r[1]) for m, r in row.items()}, {m: smax(r[2]) for m, r in row.items()}, test='3', func='SPER', kind='PERIOD',
                             channel=ch, unit='s', nominal=1.0 / f, quick=False, requires=[], timebase='EXT', gate_s=None,
                             stimulus=dict(group='LH', frequency=f, level_dbm=7.0), page=DOC_PAGES['3'])
    sections.append(dict(id='t3', title='Test 3: Single period', page='50-55', setup=(
        'Source: 1 MHz and 250 MHz at +7 dBm into Channel 1, then Channel 2.  External 10 MHz reference.  Time Interval, Single Period; auto level Off, level 0 V; noise '
        'rejection Off; channel DC, 50 ohm, 5 V range, bandwidth limit Off; trigger Manual, 100 readings, delay 0.  53220A and 53230A only.'), points=pts))

    # ---------------------------------------------------------------- Test 4
    pts = []
    for test, ch in (('4a', 1), ('4b', 2)):
        pts += stat_pair(f'{test}.ch{ch}.5ns', {m: band(r[0], r[1]) for m, r in T4.items()}, {m: smax(r[2]) for m, r in T4.items()}, test=test, func='PWID', kind='PWID', channel=ch,
                         unit='s', nominal=5e-9, quick=True, requires=[], timebase='EXT', gate_s=None,
                         stimulus=dict(group='PULSE', width_s=5e-9, period_s=66.6e-9, vpp=1.0), page=DOC_PAGES[test])
    sections.append(dict(id='t4', title='Test 4: Pulse width', page='56-61', setup=(
        'Source: pulse generator (Keysight 81134A or equivalent) 1 Vpp, period 66.6 ns, pulse width 5 ns, into Channel 1 then Channel 2 (50 ohm).  External 10 MHz reference.  Pulse Width, '
        'width positive, auto level Off, level 0.00 V, noise rejection Off; channel DC, 50 ohm, 5 V range, bandwidth limit Off; trigger Manual, 100 readings.  53220A and 53230A only.  '
        'The 96270A has no pulse output: another standard is needed.'), points=pts))

    # ---------------------------------------------------------------- Test 5
    pts = stat_pair('5.ch1-ch2.49.9ns', {m: band(r[0], r[1]) for m, r in T5.items()}, {m: smax(r[2]) for m, r in T5.items()}, test='5', func='TINT', kind='TINT', channel=12, unit='s',
                    nominal=49.9e-9, quick=True, requires=[], timebase='EXT', gate_s=None,
                    stimulus=dict(group='PULSE', width_s=5e-9, period_s=66.6e-9, delay_s=49.9e-9, vpp=1.0), page=DOC_PAGES['5'],
                    flags=['Printed: step 4 says "Record the Median", step 2 and the record page say Mean.  The Mean is judged.'])
    sections.append(dict(id='t5', title='Test 5: Time interval', page='61-65', setup=(
        'Source: pulse generator, both channels 1 Vpp, period 66.6 ns, pulse width 5 ns, Channel 2 delayed 49.9 ns; the two 3.5 mm cables must be exactly the same length.  External 10 MHz '
        'reference.  Time Interval 1-2; start and stop slope Positive, auto level Off, level 0 V, noise rejection Off; trigger Manual, 100 readings, delay 0.  53220A and 53230A only.'),
        points=pts))

    # ---------------------------------------------------------------- Test 6a / 6b
    pts = []
    for f, row in T6A.items():
        label = fmt_si(f, 'Hz').replace(' ', '')
        pts += stat_pair(f'6a.{label}', {m: band(r[0], r[1]) for m, r in row.items()}, {m: smax(r[2]) for m, r in row.items()}, test='6a', func='FREQ', kind='FREQ', channel=3, unit='Hz',
                         nominal=f, quick=True, requires=['106'], timebase='EXT', gate_s=0.01,
                         stimulus=dict(group='LH' if f <= 4e9 else 'MW', frequency=f, level_dbm=-27.0), page=DOC_PAGES['6a'])
    sections.append(dict(id='t6a', title='Test 6a: Frequency accuracy, Option 106 microwave channel', page='66-71', setup=(
        'Needs Option 106 (6 GHz).  The microwave input is Channel 3 on the 53220A / 53230A and Channel 2 on the 53210A.  Source: 100 MHz and 5.88 GHz at -27 dBm; the input power MUST be '
        '-27 +/- 0.5 dBm AT THE COUNTER INPUT (use a cable of known loss, or a power meter).  External 10 MHz reference.  Gate Timed 10 ms, Gate Out On; trigger Manual, 100 readings.'), points=pts))
    pts = []
    levels = {300e6: -23.0, 3.1e9: -27.0, 15e9: -4.0}
    for f, row in T6B.items():
        label = fmt_si(f, 'Hz').replace(' ', '')
        pts += stat_pair(f'6b.{label}', {m: band(r[0], r[1]) for m, r in row.items()}, {m: smax(r[2]) for m, r in row.items()}, test='6b', func='FREQ', kind='FREQ', channel=3, unit='Hz',
                         nominal=f, quick=True, requires=['115'], timebase='EXT', gate_s=0.01,
                         stimulus=dict(group='LH' if f <= 4e9 else 'MW', frequency=f, level_dbm=levels[f]), page=DOC_PAGES['6b'],
                         flags=(['Printed: the Test 6b setup header says -23 dBm at 300 MHz and the 3.1 GHz step says -27 dBm (15 GHz: -4 dBm); each is used as printed.'] if f == 300e6 else []))
    sections.append(dict(id='t6b', title='Test 6b: Frequency accuracy, Option 115 microwave channel', page='72-77', setup=(
        'Needs Option 115 (15 GHz).  Channel 3 (53210A: Channel 2).  Source: 300 MHz at -23 dBm, 3.1 GHz at -27 dBm, 15 GHz at -4 dBm, at the counter input (+/- 0.5 dBm).  '
        'External 10 MHz reference.  Gate Timed 10 ms, Gate Out On; trigger Manual, 100 readings.'), points=pts))

    # ---------------------------------------------------------------- Test 7
    pts = []
    for tid, f, lvl, width, narrow, dbl, opt, lo, hi, sd, text in T7:
        flags = []
        if tid == '7c':
            flags.append('Record page (p. 99) prints 1.348 865 000 GHz as the minimum; the test text (p. 88) and the maximum give 1.35 GHz +/- 1.35 MHz = 1.348 650 000 GHz.  The stricter printed '
                         'record-page value is applied; nothing was changed.  Owner to decide.')
        pts += stat_pair(f'{tid}.{fmt_si(f, "Hz").replace(" ", "")}.{fmt_time(width).replace(" ", "")}', {'53230A': band(lo, hi)}, {'53230A': smax(sd)}, test=tid, func='BURST', kind='FREQ',
                         channel=3, unit='Hz', nominal=f, quick=tid in ('7a', '7c'), requires=[opt, '150'], timebase='EXT', gate_s=None, narrow=narrow, burst_db=dbl,
                         stimulus=dict(group='BURST', frequency=f, level_dbm=lvl, burst_width_s=width, pri_s=1e-3), text_limit=text, page=DOC_PAGES[tid], flags=flags)
    sections.append(dict(id='t7', title='Test 7: Pulse burst frequency', page='77-89', setup=(
        '53230A only, Option 150 with Option 106 (7a, 7b) or Option 115 (7c, 7d).  Source: pulse-modulated microwave generator (Keysight E8257D-520-UNW), auto-level control Off, PRI 1 ms, '
        'burst widths 200 ns / 13 us (6 GHz, 0 dBm) and 400 ns / 13 us (1.35 GHz, -6 dBm).  Freq/Period, Pulse/Burst, Burst Freq; dB level -12 (7a) or -6; Narrow On for the 200 ns and 400 ns '
        'bursts, Off for 13 us; Gate Auto On; trigger Manual, 100 readings.  The 96270A has no pulse modulation: another standard is needed.  For Quick verification only 7a and 7c are run.'),
        points=pts))

    spec = dict(
        schema=1, kind='counter-pv', family='Keysight 53210A / 53220A / 53230A universal frequency counter / timer', default_period='1y',
        periods={'1y': 'Counter in operation 1 year or less', 'gt1y': 'Counter in operation more than 1 year (Test 1 limits halved)'},
        source=dict(document=DOC, pages='Chapter 1 Performance Tests, pp. 28-99 (the record pp. 90-99)', programmers_reference='Keysight 53220A/53230A Programmer\'s Reference (518 pp.)',
                    note='Keysight 53210A/53220A/53230A Assembly Level Service Guide, chapter 1 (Performance Tests); Programmer\'s Reference for the commands.  Limits are the printed record-page limits.'),
        models={
            '53210A': dict(title='Keysight 53210A', idn='53210A', channels=[1], micro_channel=2, time_tests=False, burst=False, gate_resolution_s=1e-5,
                           scpi='UNVERIFIED: the supplied Programmer\'s Reference covers the 53220A and 53230A only; the 53210A\'s microwave input is Channel 2 (Service Guide p. 67)'),
            '53220A': dict(title='Keysight 53220A', idn='53220A', channels=[1, 2], micro_channel=3, time_tests=True, burst=False, gate_resolution_s=1e-5, scpi='Programmer\'s Reference'),
            '53230A': dict(title='Keysight 53230A', idn='53230A', channels=[1, 2], micro_channel=3, time_tests=True, burst=True, gate_resolution_s=1e-6, scpi='Programmer\'s Reference'),
        },
        options={
            '010': 'High-stability OCXO time base (detected: *OPT? field 1 = 010).  Changes the Test 1 limits.',
            '106': '6 GHz microwave channel (detected: *OPT? field 2 = 106).  Tests 6a, 7a, 7b.',
            '115': '15 GHz microwave channel (detected: *OPT? field 2 = 115).  Tests 6b, 7c, 7d.',
            '150': 'Pulse microwave measurement (53230A only; detected: *OPT? field 3 = 150).  Test 7.',
            '201': 'Rear-panel inputs (not reported by *OPT?: declared by the operator; changes the hook-up text only).',
        },
        measure=dict(readings=100, gate_s=0.01, coupling='DC', impedance=50.0, input_range=5.0, level_v=0.0, probe=1, noise_rejection='OFF', low_pass_filter='OFF', measurement_mode='AUTO',
                     trigger='BUS', gate_output='ON', gate_polarity='NORM'),
        equipment=[
            dict(name='Microwave signal generator', need='100 MHz to 15 GHz, +/-10 ppb at 6 and 15 GHz, pulse width accuracy +/-10 %', example='Keysight E8257D-520-UNW', page='28'),
            dict(name='Pulse generator', need='5 ns pulse width +/- 40 ps', example='Keysight 81134A', page='28'),
            dict(name='RF signal generator', need='10 MHz +/- 2.000E-12', example='SRS CG635', page='28'),
            dict(name='Primary frequency standard (10 MHz house standard)', need='absolute accuracy better than 1x10-10', example='SRS FS725 Rubidium', page='28'),
            dict(name='DC power supply', need='adjustable to 5.000 V (listed, no test in the chapter uses it)', example='Keysight 6234A', page='28'),
            dict(name='DMM', need='microvolt accuracy (termination checks only)', example='Keysight 34410A', page='28'),
        ],
        general=[
            'Ambient 18 to 28 C (ideally 23 +/- 1 C), relative humidity below 80 % (p. 28).',
            'Warm-up 45 minutes (2.5 hours after delivery; 72 hours if stored for months) (p. 28).',
            '50 ohm RG-58 cables; AutoDigits off to verify the accuracy places (p. 28).',
        ],
        datasheet_check=dict(
            status='UNVERIFIED: the 53200A series data sheet (5990-6283EN) was not supplied; the formulas were taken from a third-party mirror (xdevs.com) as extracted text with flattened fractions, not from page images',
            rules=dict(mean_half_width_relative={'53210A': '1e-8', '53220A': '1e-9', '53230A': '1e-9'}, sdev_max_relative={'53210A': '1.4e-8', '53220A': '7e-9', '53230A': '1.4e-9'},
                       single_period_half_width_s={'53220A': '2e-10', '53230A': '1e-10'}, sdev_time_s={'53220A': '1.4e-10', '53230A': '2.8e-11'}),
            exceptions=['6a 5.88 GHz 53220A Std Dev printed 41.1 Hz (7e-9 x 5.88e9 = 41.16 Hz): printed values are truncated, not rounded',
                        '7c record-page minimum 1.348 865 000 GHz against 1.348 650 000 GHz from the test text and the formula (systematic 400 ps / 400 ns = 1e-3 -> 1.35 MHz)']),
        sections=sections)
    check(spec)
    return spec


def check(spec):
    """Abort on a printed limit that disagrees with the published pattern (documented exceptions are listed in datasheet_check.exceptions)."""
    rel_mean = {'53210A': D('1e-8'), '53220A': D('1e-9'), '53230A': D('1e-9')}
    rel_sd = {'53210A': D('1.4e-8'), '53220A': D('7e-9'), '53230A': D('1.4e-9')}
    for s in spec['sections']:
        for p in s['points']:
            test, f = p['test'], D(repr(p['nominal']))
            for m, lim in p['limits'].items():
                if test in ('2a', '2b', '6a', '6b') and p['stat'] == 'mean':
                    width = (D(repr(lim['high'])) - D(repr(lim['low']))) / 2
                    want = rel_mean[m] * f
                    if abs(width - want) > want * D('1e-9'):
                        raise SystemExit(f'{p["ref"]} {m}: mean half-width {width} != {want}')
                if test in ('2a', '2b', '6a', '6b') and p['stat'] == 'sdev':
                    want = rel_sd[m] * f
                    got = D(repr(lim['max']))
                    exact = abs(got - want) <= want * D('1e-9')
                    truncated = got <= want and want - got < want * D('0.01')          # printed values are truncated: 41.16 -> 41.1
                    if not (exact or truncated):
                        raise SystemExit(f'{p["ref"]} {m}: std dev max {got} != {want}')
                    if not exact:
                        p.setdefault('flags', []).append(f'{m}: printed Std Dev maximum {lim["printed"]} is the formula value {want:g} truncated, not rounded (no limit changed)')
            if test == '7c' and p['stat'] == 'mean':
                lim = p['limits']['53230A']
                if D(repr(lim['low'])) == D('1.35e9') - D('1.35e6'):
                    raise SystemExit('7c: the record-page misprint is gone: remove the flag')
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[argv.index('--out') + 1]) if '--out' in argv else OUT          # --out: write somewhere else (the test compares it with the stored file)
    spec = build()
    out.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {out} ({n} points in {len(spec["sections"])} sections)')


if __name__ == '__main__':
    main()
