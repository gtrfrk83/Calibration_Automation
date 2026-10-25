"""Builds specs/tektronix_mdo3_pv.json from the 3 Series MDO (MDO32 / MDO34) Specifications and Performance Verification manual
(077-1499-10, May 2026): test record pp. 48-89, procedures pp. 90-130, specifications pp. 10-46.  PDF page = printed page in this manual.

Every number below was typed from the RENDERED PAGE IMAGES (pdftoppm -r 110), each read twice; the extracted text was used only to find the
pages.  Limits are built with Decimal arithmetic from the printed strings and written as floats.  The specification cross-checks at the end
(CHECKS) recompute the printed limits from the published accuracy statements; a disagreement is listed in DISCREPANCIES (and in the spec's
'discrepancies' list), never silently changed.  The two clear misprints that ARE corrected carry a visible 'note' on the point.

Point fields (base units) are the MDO4000C engine's (specs/build_mdo_spec.py): section, kind, desc, ch, nominal, low, high (None = one-sided),
unit, models (None = all ten model keys), req (option tokens that must all hold: SA3 noSA3 AFG DVM TPA noTPA), stim, plus per-kind
parameters.  New optional parameters the shared engine reads only when present (absent on every MDO4000C point, so that procedure is unchanged):
    per_div      BAL / REFFREQ: the reading is reported in divisions (mean / V/div; edge deviation / s/div), as the test record prints it
    detection    DANL: the RF average-trace detection method (manual pp. 110, 119: Average)
    method       NOISE: 'rms_mean' = sqrt(RMS^2 - Mean^2) from two measurement slots (manual p. 104)
    hscale       OFFSET: time base for the DC setup (manual p. 101: 20 ms/div)
    vpp, coarse_hscale, fine_hscale   REFFREQ: time-mark amplitude and the two time bases (manual p. 103)
    ref_level    SPUR: reference level (manual p. 113: -15 dBm)
    counter      DVMFREQ: 'trigger' = the trigger frequency counter (manual p. 130), vscale / hscale of that setup
Model keys: '<channels>-<bandwidth MHz>' = MDO32-100 ... MDO34-1000 (p. 10 model overview; bandwidth is the 3-BW-xxx option).
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'specs' / 'tektronix_mdo3_pv.json'

BANDWIDTHS = [100, 200, 350, 500, 1000]                                    # MHz, p. 10
MODELS = [f'{n}-{bw}' for bw in BANDWIDTHS for n in (32, 34)]
FOUR_CH = [m for m in MODELS if m.startswith('34')]
BW_OF = {m: int(m.split('-')[1]) for m in MODELS}
WITH_250 = [m for m in MODELS if BW_OF[m] >= 350]                         # p. 15: 250 MHz filter only on 350 MHz / 500 MHz / 1 GHz instruments
MODEL_INFO = {m: dict(title=f'MDO{m.split("-")[0]} {("1 GHz" if BW_OF[m] == 1000 else str(BW_OF[m]) + " MHz")}',
                      channels=int(m[1]), bandwidth_hz=BW_OF[m] * 1e6,
                      bw_limits=['TWEnty', 'TWOFifty'] if m in WITH_250 else ['TWEnty'],
                      counter_max_hz=100e6 if BW_OF[m] == 100 else 150e6, option=f'3-BW-{BW_OF[m]}')
              for m in MODELS}

PAGES = {'selftest': 90, 'imp': 91, 'bal': 92, 'bw': 94, 'gain': 97, 'off': 101, 'srate': 103, 'noise': 104, 'dt': 105,
         'danl': 110, 'spur': 113, 'level': 114, 'tpa': 117, 'tpadanl': 119, 'trig': 122, 'afgf': 123, 'afga': 125, 'afgo': 126,
         'dvmdc': 127, 'dvmac': 129, 'dvmf': 130}
RECORD_PAGES = {'selftest': 48, 'imp': 49, 'bal': 50, 'bw': 56, 'gain': 57, 'off': 60, 'srate': 63, 'noise': 64, 'dt': 67,
                'danl': 80, 'spur': 80, 'level': 81, 'tpa': 82, 'tpadanl': 82, 'trig': 82, 'afgf': 83, 'afga': 83, 'afgo': 83,
                'dvmdc': 84, 'dvmac': 86, 'dvmf': 88}
TITLES = {'selftest': 'Self test and signal path compensation', 'imp': 'Input impedance', 'bal': 'DC balance', 'bw': 'Analog bandwidth',
          'gain': 'DC gain accuracy', 'off': 'DC offset accuracy', 'srate': 'Sample rate and delay time accuracy',
          'noise': 'Random noise (sample mode)', 'dt': 'Delta-time measurement accuracy', 'danl': 'Displayed average noise level (DANL)',
          'spur': 'Residual spurious response', 'level': 'Level measurement uncertainty', 'tpa': 'TPA-N-PRE functional check',
          'tpadanl': 'DANL with TPA-N-PRE attached', 'trig': 'Auxiliary (trigger) output', 'afgf': 'AFG frequency accuracy',
          'afga': 'AFG amplitude accuracy', 'afgo': 'AFG DC offset accuracy', 'dvmdc': 'DVM voltage accuracy (DC)',
          'dvmac': 'DVM voltage accuracy (AC)', 'dvmf': 'DVM frequency accuracy'}
ORDER = list(TITLES)
UNIT = {'p': D('1e-12'), 'n': D('1e-9'), 'u': D('1e-6'), 'µ': D('1e-6'), 'm': D('1e-3'), '': D(1), 'k': D('1e3'), 'M': D('1e6'), 'G': D('1e9')}

points = []
DISCREPANCIES = []


def q(text):
    """'707.3 mV' / '-1.016 V' / '233 ps' / '9.9987 kHz' -> Decimal in base units (the printed string, no float on the way)."""
    t = text.replace('–', '-').replace('−', '-').strip()
    num, unit = t.split(' ', 1) if ' ' in t else (t, '')
    unit = unit.strip()
    for base in ('Hz', 'V', 's', 'Ω', 'dBm/Hz', 'dBm', 'dB', '%', 'div'):
        if unit.endswith(base):
            prefix = unit[: -len(base)]
            if base in ('dBm/Hz', 'dBm', 'dB', '%', 'div'):
                return D(num)
            return D(num) * UNIT[prefix]
    return D(num)


def fl(x):
    return None if x is None else float(x)


def add(sec, kind, desc, nominal, low, high, unit, ch=None, models=None, req=None, stim='cal', **kw):
    p = dict(section=sec, kind=kind, desc=desc, ch=ch, nominal=fl(nominal), low=fl(low), high=fl(high), unit=unit, stim=stim)
    if models and sorted(models) != sorted(MODELS):
        p['models'] = sorted(models, key=MODELS.index)
    if req:
        p['req'] = req
    for k, v in kw.items():
        p[k] = fl(v) if isinstance(v, D) else v
    points.append(p)


def vtxt(v):
    v = D(v)
    return f'{v * 1000:f}'.rstrip('0').rstrip('.') + ' mV' if abs(v) < 1 else f'{v:f}'.rstrip('0').rstrip('.') + ' V'


def chans(ch):
    """Channels 3 and 4 exist on the MDO34 only (p. 12)."""
    return FOUR_CH if ch in (3, 4) else MODELS


CH = (1, 2, 3, 4)

# ---- self test (test record p. 48 'Self Test'; procedure p. 90 runs the system diagnostics, then the signal path compensation) ----------
add('selftest', 'SELFTEST', 'System diagnostics (all tests pass)', 1, 1, 1, '', stim='none', passfail=True)
add('selftest', 'SPC', 'Signal path compensation (status Pass)', 1, 1, 1, '', stim='none', passfail=True,
    note='The test record (p. 48) has a Self Test row only; the procedure (p. 90) requires a passing SPC before the other tests.')

# ---- input impedance (p. 49; procedure p. 91) ------------------------------------------------------------------------------------------
for ch in CH:
    for vs in ('10 mV', '100 mV'):
        add('imp', 'IMP', f'CH{ch} 1 MΩ, {vs}/div', D('1e6'), q('990 kΩ'), q('1.01 MΩ'), 'ohm', ch=ch, term='1M', vscale=q(vs), models=chans(ch))
    for vs in ('10 mV', '100 mV'):
        add('imp', 'IMP', f'CH{ch} 50 Ω, {vs}/div', D(50), q('49.5 Ω'), q('50.5 Ω'), 'ohm', ch=ch, term='50', vscale=q(vs), models=chans(ch))

# ---- DC balance (pp. 50-55, every channel table identical; procedure p. 92). Limits are printed in divisions --------------------------
BAL = {'50': [('1 mV', '0.500'), ('2 mV', '0.250'), ('10 mV', '0.200'), ('100 mV', '0.200'), ('1 V', '0.200')],
       '1M': [('1 mV', '0.300'), ('2 mV', '0.200'), ('10 mV', '0.200'), ('100 mV', '0.200'), ('1 V', '0.200')]}
BWN = {'TWEnty': '20 MHz BW', 'TWOFifty': '250 MHz BW', 'FULl': 'Full BW'}
for ch in CH:
    for bw in ('TWEnty', 'TWOFifty', 'FULl'):
        for term, tl in (('50', '50 Ω'), ('1M', '1 MΩ')):
            for vs, lim in BAL[term]:
                models = [m for m in chans(ch) if bw != 'TWOFifty' or m in WITH_250]
                add('bal', 'BAL', f'CH{ch} {tl}, {BWN[bw]}, {vs}/div', D(0), -D(lim), D(lim), 'div', ch=ch, term=term, bw=bw, vscale=q(vs),
                    stim='none', per_div=True, models=models)

# ---- analog bandwidth 50 Ω (record p. 56; worksheet pp. 95-96; specification p. 15) --------------------------------------------------------
BWF = {1000: {'10 mV': '1 GHz', '5 mV': '500 MHz', '2 mV': '350 MHz', '1 mV': '150 MHz'},
       500: {'10 mV': '500 MHz', '5 mV': '500 MHz', '2 mV': '350 MHz', '1 mV': '150 MHz'},
       350: {'10 mV': '350 MHz', '5 mV': '350 MHz', '2 mV': '350 MHz', '1 mV': '150 MHz'},
       200: {'10 mV': '200 MHz', '5 mV': '200 MHz', '2 mV': '200 MHz', '1 mV': '150 MHz'},
       100: {'10 mV': '100 MHz', '5 mV': '100 MHz', '2 mV': '100 MHz', '1 mV': '100 MHz'}}
BW_NOTES = {(500, '10 mV'): 'The worksheet (p. 95) lists no 10 mV/div row for 500 MHz instruments; the specification (p. 15: 5 mV/div - 1 V/div, DC - 500 MHz) is used.',
            (350, '10 mV'): 'The worksheet (p. 95) lists no 10 mV/div row for 350 MHz instruments; the specification (p. 15: 5 mV/div - 1 V/div, DC - 350 MHz) is used.',
            (200, '10 mV'): 'The worksheet (pp. 95-96) lists no 10 mV/div row for 200 MHz instruments; the specification (p. 15: 2 mV/div - 1 V/div, DC - 200 MHz) is used.',
            (200, '5 mV'): 'The worksheet (pp. 95-96) lists no 5 mV/div row for 200 MHz instruments; the specification (p. 15: 2 mV/div - 1 V/div, DC - 200 MHz) is used.',
            (200, '1 mV'): 'The worksheet (p. 96) prints two 1 mV/div rows for 200 MHz instruments (150 MHz and 100 MHz); the specification (p. 15: 1 mV/div - 1.99 mV/div, DC - 150 MHz) is used.',
            (100, '10 mV'): 'The worksheet (p. 96) lists only 1 mV/div for 100 MHz instruments; the specification (p. 15: 1 mV/div - 1 V/div, DC - 100 MHz) is used.',
            (100, '5 mV'): 'The worksheet (p. 96) lists only 1 mV/div for 100 MHz instruments; the specification (p. 15: 1 mV/div - 1 V/div, DC - 100 MHz) is used.',
            (100, '2 mV'): 'The worksheet (p. 96) lists only 1 mV/div for 100 MHz instruments; the specification (p. 15: 1 mV/div - 1 V/div, DC - 100 MHz) is used.'}
for bw in BANDWIDTHS:
    for ch in CH:
        for vs in ('10 mV', '5 mV', '2 mV', '1 mV'):
            fr = q(BWF[bw][vs])
            models = [m for m in chans(ch) if BW_OF[m] == bw]
            extra = {'note': BW_NOTES[(bw, vs)]} if (bw, vs) in BW_NOTES else {}
            add('bw', 'BW', f'CH{ch} 50 Ω, {vs}/div, {BWF[bw][vs]}', D(1), D('0.707'), None, 'ratio', ch=ch, term='50', vscale=q(vs), hscale=q('4 ns'),
                freq=fr, vin_pp=8 * q(vs), ref_hz=q('10 MHz'), models=models, **extra)

# ---- DC gain (record pp. 57-59: 1 MΩ, 20 MHz BW, 0 V offset; worksheet pp. 98-100 gives Vdiff expected / Vnegative / Vpositive) ------------
GAIN = [('1 mV', '7 mV', '2.5'), ('2 mV', '14 mV', '2.0'), ('4.98 mV', '34.86 mV', '3.0'), ('5 mV', '35 mV', '1.5'), ('10 mV', '70 mV', '1.5'),
        ('20 mV', '140 mV', '1.5'), ('49.8 mV', '348.6 mV', '3.0'), ('50 mV', '350 mV', '1.5'), ('100 mV', '700 mV', '1.5'), ('200 mV', '1400 mV', '1.5'),
        ('500 mV', '3500 mV', '1.5'), ('1 V', '7000 mV', '1.5')]
for ch in CH:
    for vs, vd, lim in GAIN:
        vdiff = q(vd)
        extra = {'note': 'The test record prints this vertical scale as "49.8 mV" (no /div).'} if vs == '49.8 mV' else {}
        add('gain', 'GAIN', f'CH{ch} 1 MΩ, 20 MHz BW, {vs}/div', D(0), -D(lim), D(lim), '%', ch=ch, term='1M', bw='TWEnty', vscale=q(vs),
            vdiff=vdiff, vneg=-vdiff / 2, vpos=vdiff / 2, models=chans(ch), **extra)

# ---- DC offset (record pp. 60-63, 1 MΩ, 20 MHz BW; procedure p. 101: 20 ms/div, position 0) -------------------------------------------------
OFF = [('1 mV', '700 mV', '692.7 mV', '707.3 mV'), ('2 mV', '700 mV', '692.6 mV', '707.4 mV'), ('10 mV', '1 V', '988 mV', '1012 mV'),
       ('100 mV', '10.0 V', '9.88 V', '10.12 V'), ('1 V', '100 V', '98.80 V', '101.2 V'), ('1.01 V', '100 V', '98.80 V', '101.2 V')]
for ch in CH:
    for vs, off, lo, hi in OFF:
        for sign in (1, -1):
            o = sign * q(off)
            lo_v, hi_v = (q(lo), q(hi)) if sign > 0 else (-q(hi), -q(lo))
            extra = {'note': 'The procedure (p. 101) sets 900 mV for the first row; the test record (p. 60) prints 700 mV, which is applied.'} if vs in ('1 mV', '2 mV') else {}
            add('off', 'OFFSET', f'CH{ch} 1 MΩ, 20 MHz BW, {vs}/div, offset {vtxt(o)}', o, lo_v, hi_v, 'V', ch=ch, term='1M', bw='TWEnty', vscale=q(vs),
                offset=o, hscale=q('20 ms'), models=chans(ch), **extra)

# ---- sample rate and delay time (record p. 63: -2 to +2 division; procedure p. 103: 80 ms time mark, 1 Vpp, 50 Ω, 500 mV/div,
#      20 ms/div, delay 80 ms, then 400 ns/div; one division = 5 ppm) -------------------------------------------------------------------------
add('srate', 'REFFREQ', 'Time-base error (80 ms mark, 400 ns/div)', D(0), D(-2), D(2), 'div', ch=1, stim='gen', period=q('80 ms'), vpp=q('1 V'),
    coarse_hscale=q('20 ms'), fine_hscale=q('400 ns'), per_div=True)

# ---- random noise (record pp. 64-66; procedure p. 104: 50 Ω, 100 mV/div, 10 ms/div, RMS noise = sqrt(RMS^2 - Mean^2)) ----------------------
NOISE = {1000: [('FULl', '3.1 mV'), ('TWOFifty', '3.4 mV'), ('TWEnty', '3.4 mV')], 500: [('FULl', '3.1 mV'), ('TWOFifty', '3.3 mV'), ('TWEnty', '3.25 mV')],
         350: [('FULl', '3.3 mV'), ('TWOFifty', '3.3 mV'), ('TWEnty', '3.25 mV')], 200: [('FULl', '3.25 mV'), ('TWEnty', '3.25 mV')],
         100: [('FULl', '2.85 mV'), ('TWEnty', '3.25 mV')]}
for bw in BANDWIDTHS:
    for ch in CH:
        for filt, lim in NOISE[bw]:
            extra = {}
            if bw == 1000 and ch == 4 and filt == 'FULl':
                lim = '3.4 mV'      # printed so on p. 64 (CH1-CH3 print 3.1 mV; the guaranteed specification p. 19 is 3.1 mV) - see DISCREPANCIES
                extra['note'] = 'The test record (p. 64) prints 3.4 mV for CH4 Full BW on 1 GHz instruments (3.1 mV for CH1-CH3; specification p. 19: 3.1 mV). The printed 3.4 mV is applied.'
            models = [m for m in chans(ch) if BW_OF[m] == bw]
            add('noise', 'NOISE', f'CH{ch} 50 Ω, {BWN[filt]}, 100 mV/div', D(0), None, q(lim), 'V', ch=ch, term='50', bw=filt, vscale=q('100 mV'),
                hscale=q('10 ms'), stim='none', method='rms_mean', models=models, **extra)

# ---- delta time (record pp. 67-77; procedure pp. 105-106: Burst Width standard deviation, 50 Ω, one channel at a time) -----------------------
DT_LT1G = [('4 ns', '240 MHz', [('100 mV', '800 mV', '233 ps'), ('500 mV', '4 V', '233 ps'), ('1 V', '4 V', '237 ps')]),
           ('40 ns', '24 MHz', [('5 mV', '40 mV', '435 ps'), ('100 mV', '800 mV', '359 ps'), ('500 mV', '4 V', '356 ps'), ('1 V', '4 V', '583 ps')]),
           ('400 ns', '2.4 MHz', [('5 mV', '40 mV', '3.69 ns'), ('100 mV', '800 mV', '2.75 ns'), ('500 mV', '4 V', '2.71 ns'), ('1 V', '4 V', '5.36 ns')]),
           ('4 µs', '240 kHz', [('5 mV', '40 mV', '36.8 ns'), ('100 mV', '800 mV', '27.4 ns'), ('500 mV', '4 V', '27.0 ns'), ('1 V', '4 V', '53.5 ns')]),
           ('40 µs', '24 kHz', [('5 mV', '40 mV', '368 ns'), ('100 mV', '800 mV', '274 ns'), ('500 mV', '4 V', '270 ns'), ('1 V', '4 V', '535 ns')]),
           ('400 µs', '2.4 kHz', [('5 mV', '40 mV', '3.68 µs'), ('100 mV', '800 mV', '2.74 µs'), ('500 mV', '4 V', '2.70 µs'), ('1 V', '4 V', '5.35 µs')])]
DT_1G = [('4 ns', '240 MHz', [('100 mV', '800 mV', '119 ps'), ('500 mV', '4 V', '119 ps'), ('1 V', '4 V', '128 ps')]),
         ('40 ns', '24 MHz', [('5 mV', '40 mV', '386 ps'), ('100 mV', '800 mV', '298 ps'), ('500 mV', '4 V', '294 ps'), ('1 V', '4 V', '584 ps')]),
         ('400 ns', '2.4 MHz', [('5 mV', '40 mV', '3.69 ns'), ('100 mV', '800 mV', '2.75 ns'), ('500 mV', '4 V', '2.71 ns'), ('1 V', '4 V', '5.36 ns')]),
         ('4 µs', '240 kHz', [('5 mV', '40 mV', '36.8 ns'), ('100 mV', '800 mV', '27.4 ns'), ('500 mV', '4 V', '27.0 ns'), ('1 V', '4 V', '53.5 ns')]),
         ('40 µs', '24 kHz', [('5 mV', '40 mV', '368 ns'), ('100 mV', '800 mV', '274 ns'), ('500 mV', '4 V', '270 ns'), ('1 V', '4 V', '535 ns')]),
         ('400 µs', '2.4 kHz', [('5 mV', '40 mV', '3.68 µs'), ('100 mV', '800 mV', '2.74 µs'), ('500 mV', '4 V', '2.70 µs'), ('1 V', '4 V', '5.35 µs')])]
for table, group in ((DT_LT1G, [m for m in MODELS if BW_OF[m] < 1000]), (DT_1G, [m for m in MODELS if BW_OF[m] == 1000])):
    for ch in CH:
        for hs, fr, rows in table:
            models = [m for m in group if m in chans(ch) and not (hs == '4 ns' and BW_OF[m] in (100, 200))]   # '(does not apply to 100 and 200 MHz models)'
            for vs, vpp, hi in rows:
                add('dt', 'DELTA', f'CH{ch} {hs}/div, {fr}, {vs}/div ({vpp} p-p)', D(0), None, q(hi), 's', ch=ch, vscale=q(vs), vpp=q(vpp), hscale=q(hs),
                    freq=q(fr), models=models)

# ---- DANL (record p. 80; procedure pp. 110-112: average trace, average detection, reference level -15 dBm) ---------------------------------
def fname(x):
    return f'{x / D("1e9"):g} GHz' if x >= D('1e9') else f'{x / D("1e6"):g} MHz' if x >= D('1e6') else f'{x / D("1e3"):g} kHz'


DANL = [('9 kHz', '50 kHz', '-109', None), ('50 kHz', '5 MHz', '-126', None), ('5 MHz', '1 GHz', '-136', 'noSA3'), ('5 MHz', '2 GHz', '-136', 'SA3'),
        ('2 GHz', '3 GHz', '-126', 'SA3')]
for lo_f, hi_f, lim, opt in DANL:
    a, b = q(lo_f), q(hi_f)
    add('danl', 'DANL', f'{fname(a)} to {fname(b)}' + (' (3-SA3 installed)' if opt == 'SA3' else ' (3-SA3 not installed)' if opt else ''),
        D(0), None, D(lim), 'dBm/Hz', req=[x for x in (opt, 'noTPA') if x], stim='none', f_start=a, f_stop=b, ref_level=D(-15), detection='AVErage')

# ---- residual spurious response (record p. 80 PASS / FAIL; procedure p. 113: no spur above -78 dBm, reference level -15 dBm, RBW 100 kHz
#      above 5 MHz; specification p. 41: < -78 dBm, at 2.5 GHz < -62 dBm, at 1.25 GHz < -76 dBm) --------------------------------------------------
SPURS = [('9 kHz to 50 kHz', '9 kHz', '50 kHz', None, [], '-78', None, 'span'),
         ('50 kHz to 5 MHz', '50 kHz', '5 MHz', None, [], '-78', None, 'span'),
         ('5 MHz to 1 GHz (3-SA3 not installed)', '5 MHz', '1 GHz', '100 kHz', [], '-78', 'noSA3', 'span'),
         ('5 MHz to 2 GHz, not 1.25 GHz (3-SA3 installed)', '5 MHz', '2 GHz', '100 kHz', ['1.25 GHz'], '-78', 'SA3', 'span'),
         ('1.25 GHz spur (3-SA3 installed)', '1.25 GHz', '1.25 GHz', '100 kHz', None, '-76', 'SA3', 'at'),
         ('2 GHz to 3 GHz, not 2.5 GHz (3-SA3 installed)', '2 GHz', '3 GHz', '100 kHz', ['2.5 GHz'], '-78', 'SA3', 'span'),
         ('2.5 GHz spur (3-SA3 installed)', '2.5 GHz', '2.5 GHz', '100 kHz', None, '-62', 'SA3', 'at')]
SPUR_NOTE = 'The test record (p. 80) records PASS or FAIL; the limit is the procedure threshold (p. 113: no spur above -78 dBm), as the specification (p. 41).'
for name, f0, f1, rbw, excl, lim, opt, mode in SPURS:
    note = SPUR_NOTE if mode == 'span' else (f'The test record (p. 80) records PASS or FAIL and the procedure (p. 113) only notes this spur level; '
                                             f'the limit is the specification (p. 41: at {f0} < {lim} dBm).')
    add('spur', 'SPUR', name, D(0), None, D(lim), 'dBm', req=[opt] if opt else None, stim='none', f_start=q(f0), f_stop=q(f1),
        rbw=q(rbw) if rbw else None, exclude=[float(q(e)) for e in (excl or [])], at_freq=float(q(f0)) if mode == 'at' else None, ref_level=D(-15), note=note)

# ---- level measurement uncertainty (record p. 81; procedure pp. 114-116: power meter / splitter reference, reference level = generator level) ----
BANDS = [('50 kHz', '50 kHz', '50 kHz', '100 kHz', '100 kHz', '1', None),
         ('100 kHz - 900 kHz', '100 kHz', '900 kHz', '100 kHz', '100 kHz', '1', None),
         ('1 MHz - 9 MHz', '1 MHz', '9 MHz', '1 MHz', '2 MHz', '1', None),
         ('10 MHz - 90 MHz', '10 MHz', '90 MHz', '10 MHz', '20 MHz', '1', None),
         ('100 MHz - 1 GHz (3-SA3 not installed)', '100 MHz', '1 GHz', '100 MHz', '50 MHz', '1', 'noSA3'),
         ('100 MHz - 1.5 GHz (3-SA3 installed)', '100 MHz', '1.5 GHz', '100 MHz', '50 MHz', '1', 'SA3'),
         ('1.6 GHz - 2.5 GHz (3-SA3 installed)', '1.6 GHz', '2.5 GHz', '100 MHz', '50 MHz', '1.3', 'SA3'),
         ('2.6 GHz - 3 GHz (3-SA3 installed)', '2.6 GHz', '3 GHz', '100 MHz', '50 MHz', '1.5', 'SA3')]
LEVEL_NOTES = {'100 MHz - 1 GHz (3-SA3 not installed)': 'Test record row "100 MHz - 1.5 GHz"; without 3-SA3 the procedure (p. 115 step s) steps 100 MHz to 1 GHz.',
               '1.6 GHz - 2.5 GHz (3-SA3 installed)': 'Test record row "1.5 GHz - 2.5 GHz": the 100 MHz steps of p. 116 from 1.6 GHz; 1.5 GHz is judged in the +/-1 dB row (specification p. 42: 50 kHz - 1.5 GHz < +/-1 dB).',
               '2.6 GHz - 3 GHz (3-SA3 installed)': 'Test record row "2.5 GHz - 3 GHz": the 100 MHz steps of p. 116 from 2.6 GHz; 2.5 GHz is judged in the +/-1.3 dB row (specification p. 42: 1.5 GHz - 2.5 GHz < +/-1.3 dB).'}
for level in (10, 0, -15):
    for name, f0, f1, step, span, lim, opt in BANDS:
        extra = {'note': LEVEL_NOTES[name]} if name in LEVEL_NOTES else {}
        add('level', 'ABSAMP', f'{level:+d} dBm, {name}', D(level), -D(lim), D(lim), 'dB', req=[opt] if opt else None, stim='rf', level_dbm=D(level),
            f_start=q(f0), f_step=q(step), f_stop=q(f1), span=q(span), **extra)

# ---- TPA-N-PRE functional check (record p. 82: <= 1.5 dB; procedure pp. 117-118) ----------------------------------------------------------
for freq in ('1.7 GHz', '2.9 GHz'):
    for level, rl in (('-20', '-15'), ('-35', '-30')):
        add('tpa', 'TPAFUNC', f'{freq}, {level} dBm in, reference level {rl} dBm', D(0), D('-1.5'), D('1.5'), 'dB', req=['SA3', 'TPA'], stim='rf',
            freq=q(freq), level_dbm=D(level), ref_level=D(rl), span=q('50 MHz'),
            note='The test record (p. 82) says "All models"; 1.7 GHz and 2.9 GHz are above the standard 1 GHz analyzer range (p. 11), so the point needs 3-SA3.')

# ---- DANL with the TPA-N-PRE (record p. 82; procedure pp. 119-121: reference level -30 dBm) ---------------------------------------------------
TDANL = [('9 kHz', '50 kHz', '-117', None), ('50 kHz', '5 MHz', '-138', None), ('5 MHz', '1 GHz', '-148', 'noSA3'), ('5 MHz', '2 GHz', '-148', 'SA3'),
         ('2 GHz', '3 GHz', '-138', 'SA3')]
for lo_f, hi_f, lim, opt in TDANL:
    a, b = q(lo_f), q(hi_f)
    extra = {'note': 'The test record (p. 82) prints "50 kHz - 1 GHz (3-SA3 not installed)"; the procedure (p. 120 step 4) checks 5 MHz to 1 GHz, which is used.'} if opt == 'noSA3' else {}
    add('tpadanl', 'DANL', f'{fname(a)} to {fname(b)} (TPA-N-PRE)' + (' (3-SA3 installed)' if opt == 'SA3' else ' (3-SA3 not installed)' if opt else ''),
        D(0), None, D(lim), 'dBm/Hz', req=[x for x in (opt, 'TPA') if x], stim='none', f_start=a, f_stop=b, ref_level=D(-30), tpa=True,
        detection='AVErage', **extra)

# ---- auxiliary (trigger) output (record p. 82; procedure p. 122: CH1 1 V/div, 4 us/div, High and Low measurements) ----------------------------
add('trig', 'TRIGOUT', 'Aux out HIGH, 1 MΩ', q('2.25 V'), q('2.25 V'), None, 'V', ch=1, term='1M', state='HIGH', stim='none')
add('trig', 'TRIGOUT', 'Aux out LOW, 1 MΩ', q('0.7 V'), None, q('0.7 V'), 'V', ch=1, term='1M', state='LOW', stim='none')
add('trig', 'TRIGOUT', 'Aux out HIGH, 50 Ω', q('0.9 V'), q('0.9 V'), None, 'V', ch=1, term='50', state='HIGH', stim='none')
add('trig', 'TRIGOUT', 'Aux out LOW, 50 Ω', q('0.25 V'), None, q('0.25 V'), 'V', ch=1, term='50', state='LOW', stim='none')

# ---- AFG (record p. 83; procedures pp. 123-126) -----------------------------------------------------------------------------------------------
for wave, f, lo, hi, label in (('SINE', '10 kHz', '9.9987 kHz', '10.0013 kHz', 'Sine wave 10 kHz'), ('SINE', '50 MHz', '49.9975 MHz', '50.0025 MHz', 'Sine wave 50 MHz'),
                               ('SQUare', '25 kHz', '24.99875 kHz', '25.00125 kHz', 'Square wave 25 kHz'), ('SQUare', '25 MHz', '24.99875 MHz', '25.00125 MHz', 'Square wave 25 MHz')):
    add('afgf', 'AFGFREQ', f'{label}, 2.5 V p-p, 50 Ω', q(f), q(lo), q(hi), 'Hz', req=['AFG'], stim='none', wave=wave, vpp=q('2.5 V'))
add('afga', 'AFGAMP', 'Square 20 mV p-p at 1 kHz, 0 V offset, 50 Ω (rms)', q('10 mV'), q('9.35 mV'), q('10.65 mV'), 'V', req=['AFG'], stim='none',
    vpp=q('20 mV'), offset=D(0), freq=q('1 kHz'))
add('afga', 'AFGAMP', 'Square 1 V p-p at 1 kHz, 0.2 V offset, 50 Ω (rms)', q('500 mV'), q('490.5 mV'), q('509.5 mV'), 'V', req=['AFG'], stim='none',
    vpp=q('1 V'), offset=q('0.2 V'), freq=q('1 kHz'))
for lvl, lo, hi in (('20 mV', '18.7 mV', '21.3 mV'), ('1 V', '984 mV', '1.016 V'), ('-1 V', '-1.016 V', '-984 mV')):
    add('afgo', 'AFGOFF', f'DC {lvl} into 50 Ω', q(lvl), q(lo), q(hi), 'V', req=['AFG'], stim='none', level=q(lvl))

# ---- DVM DC (record pp. 84-85, every channel identical; procedure pp. 127-128) -----------------------------------------------------------------
DVMDC = [('1', '-5', '-5', '-5.117', '-4.883'), ('0.5', '-2', '-2', '-2.052', '-1.948'), ('0.5', '-1', '-0.5', '-1.0345', '-0.9655'),
         ('0.2', '-0.5', '-0.5', '-0.5175', '-0.4825'), ('0.01', '0.002', '0', '0.00042', '0.00442'), ('0.2', '0.5', '0.5', '0.4825', '0.5175'),
         ('0.5', '1', '0.5', '0.9655', '1.0345'), ('0.5', '2', '2', '1.948', '2.052'), ('1', '5', '5', '4.883', '5.117')]
for ch in CH:
    for vs, vin, off, lo, hi in DVMDC:
        extra = {}
        lo_d = D(lo)
        if vin == '0.002':
            lo_d = -D(lo)            # CORRECTED misprint: see the note and DISCREPANCIES
            extra['note'] = ('The test record (pp. 84-85) prints a low limit of 0.00042 V for the 2 mV input; the specification (p. 46) gives '
                             '+/-(2 mV + 4.2 % x 10 mV ...) = +/-2.42 mV around 2 mV, i.e. -0.00042 V. The sign was lost in print; -0.00042 V is applied.')
        add('dvmdc', 'DVMDC', f'CH{ch} {vtxt(vs)}/div, input {vtxt(vin)}, offset {vtxt(off)}', D(vin), lo_d, D(hi), 'V', ch=ch, req=['DVM'],
            vscale=D(vs), offset=D(off), models=chans(ch), **extra)

# ---- DVM AC (record pp. 86-87; procedure p. 129: 5560A square wave, 50 Ω) ---------------------------------------------------------------------
DVMAC = [('5 mV', '20 mV', '9.800 mV', '10.200 mV'), ('10 mV', '50 mV', '24.5 mV', '25.500 mV'), ('100 mV', '0.5 V', '245.000 mV', '255.000 mV'),
         ('200 mV', '1 V', '490.000 mV', '510.000 mV'), ('1 V', '5 V', '2.450 V', '2.550 V')]
for ch in CH:
    for vs, vpp, lo, hi in DVMAC:
        extra = {'note': 'The test record (pp. 86-87) prints "2.450 mV" and "2.550 mV" for the 5 V p-p row; a 5 V p-p square wave is 2.5 V rms and the '
                         'specification (p. 46: +/-2 %) gives 2.450 V to 2.550 V, which is applied.'} if vpp == '5 V' else {}
        add('dvmac', 'DVMAC', f'CH{ch} {vs}/div, {vtxt(q(vpp))} p-p square at 1 kHz (rms)', q(vpp) / 2, q(lo), q(hi), 'V', ch=ch, req=['DVM'], vscale=q(vs),
            vpp=q(vpp), freq=q('1 kHz'), models=chans(ch), **extra)

# ---- DVM frequency (record pp. 88-89; procedure p. 130: trigger frequency counter, 200 mV/div, 20 ms/div, 1 V p-p) ------------------------------
DVMF = [('9.0000 Hz', '8.9998 Hz', '9.0002 Hz'), ('99.000 Hz', '98.998 Hz', '99.002 Hz'), ('999.00 Hz', '998.98 Hz', '999.02 Hz'),
        ('99.000 kHz', '98.998 kHz', '99.002 kHz'), ('999.00 kHz', '998.98 kHz', '999.02 kHz'), ('150 MHz', '149.99 MHz', '150.01 MHz')]
for ch in CH:
    for nom, lo, hi in DVMF:
        f = q(nom)
        models = [m for m in chans(ch) if f <= D(str(MODEL_INFO[m]['counter_max_hz']))]
        extra = {'note': 'Verifies the counter maximum input frequency. The specification (p. 46) gives 100 MHz for 100 MHz models, so this point is not run on them.'} if f > D('1e8') else {}
        add('dvmf', 'DVMFREQ', f'CH{ch} {nom}', f, q(lo), q(hi), 'Hz', ch=ch, req=['DVM'], freq=f, stim='cal', counter='trigger', vscale=q('200 mV'),
            hscale=q('20 ms'), vpp=q('1 V'), models=models, **extra)


# =====================================================================================================================================
# cross-checks against the published specification (Decimal); anything that does not agree is LISTED, not changed
# =====================================================================================================================================
def check(name, printed_lo, printed_hi, spec_lo, spec_hi, tol=D('1e-12')):
    if abs(D(str(printed_lo)) - spec_lo) > tol or abs(D(str(printed_hi)) - spec_hi) > tol:
        DISCREPANCIES.append(f'{name}: printed {printed_lo} .. {printed_hi}, specification gives {spec_lo} .. {spec_hi}')


# DVM DC (p. 46): +/-(2 mV + ((4 x V/div / |Vin|) + 1) % of |Vin| + 0.5 % of |offset|)
for vs, vin, off, lo, hi in DVMDC:
    v, s, o = D(vin), D(vs), D(off)
    tol = D('0.002') + (4 * s / abs(v) + 1) / 100 * abs(v) + D('0.005') * abs(o)
    check(f'DVM DC {vin} V at {vs} V/div, offset {off} V (pp. 84-85)', lo, hi, v - tol, v + tol)
# DVM AC (p. 46): +/-2 % at 1 kHz
for vs, vpp, lo, hi in DVMAC:
    n = q(vpp) / 2
    check(f'DVM AC {vpp} p-p (p. 86)', q(lo), q(hi), n * D('0.98'), n * D('1.02'))
# DVM frequency (p. 46): +/-(10 uHz/Hz + 1 count), 5 digits
for nom, lo, hi in DVMF:
    f = q(nom)
    count = D(1).scaleb(f.adjusted() - 4)                     # 1 count of a 5-digit readout (p. 46 'Frequency: 5 digits')
    tol = f * D('10e-6') + count
    check(f'DVM frequency {nom} (p. 88)', q(lo), q(hi), f - tol, f + tol, tol=tol * D('0.2'))    # printed limits are rounded to the display digits
# AFG (p. 44): frequency 130 ppm <= 10 kHz, 50 ppm above; amplitude +/-(1.5 % Vpp + 1.5 % |offset| + 1 mV) in Vpp -> rms of a square = Vpp / 2
for f, lo, hi in (('10 kHz', '9.9987 kHz', '10.0013 kHz'), ('50 MHz', '49.9975 MHz', '50.0025 MHz'), ('25 kHz', '24.99875 kHz', '25.00125 kHz'), ('25 MHz', '24.99875 MHz', '25.00125 MHz')):
    fr = q(f)
    ppm = D('130e-6') if fr <= D('1e4') else D('50e-6')
    check(f'AFG frequency {f} (p. 83)', q(lo), q(hi), fr * (1 - ppm), fr * (1 + ppm))
for vpp, off, lo, hi in (('20 mV', '0', '9.35 mV', '10.65 mV'), ('1 V', '0.2', '490.5 mV', '509.5 mV')):
    tol = (q(vpp) * D('0.015') + D(off) * D('0.015') + D('0.001')) / 2
    check(f'AFG amplitude {vpp} p-p (p. 83)', q(lo), q(hi), q(vpp) / 2 - tol, q(vpp) / 2 + tol)
for lvl, lo, hi in (('20 mV', '18.7 mV', '21.3 mV'), ('1 V', '984 mV', '1.016 V'), ('-1 V', '-1.016 V', '-984 mV')):
    tol = abs(q(lvl)) * D('0.015') + D('0.001')
    check(f'AFG DC offset {lvl} (p. 83)', q(lo), q(hi), q(lvl) - tol, q(lvl) + tol)
# DC offset (p. 14): +/-(0.01 x |offset - position| + DC balance), position 0; DC balance (p. 13) 0.2 div, 0.3 div at 1 mV/div (1 MΩ)
for vs, off, lo, hi in OFF:
    bal = (D('0.3') if vs == '1 mV' else D('0.2')) * q(vs)
    tol = D('0.01') * q(off) + bal
    check(f'DC offset {off} at {vs}/div (p. 60)', q(lo), q(hi), q(off) - tol, q(off) + tol)
# DC gain (p. 13): 2.5 % at 1 mV/div, 2.0 % at 2 mV/div, 1.5 % from 5 mV/div, 3.0 % variable gain (4.98 / 49.8 mV/div)
for vs, _vd, lim in GAIN:
    spec = {'1 mV': '2.5', '2 mV': '2.0', '4.98 mV': '3.0', '49.8 mV': '3.0'}.get(vs, '1.5')
    check(f'DC gain {vs}/div (p. 57)', -D(lim), D(lim), -D(spec), D(spec))
# DC balance (p. 13)
for term, rows in BAL.items():
    for vs, lim in rows:
        spec = {('50', '1 mV'): '0.5', ('50', '2 mV'): '0.25', ('1M', '1 mV'): '0.3'}.get((term, vs), '0.2')
        check(f'DC balance {term} {vs}/div (p. 50)', -D(lim), D(lim), -D(spec), D(spec))
# random noise, 100 mV/div, 50 Ω, Full BW (p. 19 guaranteed) / 250 MHz and 20 MHz BW (p. 20)
SPEC_NOISE = {1000: {'FULl': '3.1', 'TWOFifty': '3.4', 'TWEnty': '3.4'}, 500: {'FULl': '3.1', 'TWOFifty': '3.3', 'TWEnty': '3.25'},
              350: {'FULl': '3.3', 'TWOFifty': '3.3', 'TWEnty': '3.25'}, 200: {'FULl': '3.25', 'TWEnty': '3.25'}, 100: {'FULl': '2.85', 'TWEnty': '3.25'}}
for bw, rows in NOISE.items():
    for filt, lim in rows:
        check(f'Random noise {bw} MHz instruments, {BWN[filt]} (p. 64)', 0, q(lim), 0, D(SPEC_NOISE[bw][filt]) / 1000)
DISCREPANCIES.append('Random noise, 1 GHz instruments, CH4 Full BW (p. 64): printed 3.4 mV (CH1-CH3 3.1 mV); specification p. 19: 3.1 mV. Printed value applied.')
# level measurement uncertainty (p. 42): 50 kHz - 1.5 GHz < +/-1 dB, 1.5 - 2.5 GHz < +/-1.3 dB, 2.5 - 3 GHz < +/-1.5 dB: the printed rows agree.
# DANL (p. 41): 9 - 50 kHz -109, 50 kHz - 5 MHz -126, 5 MHz - 2 GHz -136, 2 - 3 GHz -126 dBm/Hz: the printed rows agree.
# Sample rate (p. 27: +/-10 ppm over >= 1 ms): 2 div x 400 ns / 80 ms = 10 ppm: agrees (p. 103: one division = 5 ppm).
# Not cross-checked (no published figure in this manual): delta-time limits (p. 27 gives the formula only), aux output levels (p. 36 gives none),
# TPA-N-PRE functional and DANL limits (no TPA specification in this manual), input impedance (p. 12: 1 MΩ +/-1 %, 50 Ω +/-1 % - agrees).
MISPRINTS = [
    'DVM DC, 2 mV input (pp. 84-85): printed low limit 0.00042 V; specification p. 46 gives -0.00042 V. CORRECTED to -0.00042 V (visible note on the point).',
    'DVM AC, 5 V p-p at 1 V/div (pp. 86-87): printed 2.450 mV / 2.550 mV; 2.5 V rms +/-2 % = 2.450 V / 2.550 V. CORRECTED to volts (visible note).',
    'DC balance procedure (p. 92 step 8) names a 150 MHz bandwidth limit; the test record and the specification (p. 15) use 250 MHz. 250 MHz used.',
    'DC offset procedure (p. 101) sets 900 mV at 1 mV/div; the test record prints 700 mV. 700 mV used.',
    'DC offset 1.01 V/div, +/-100 V (p. 60): specification p. 14 gives +/-1.202 V (0.2 div x 1.01 V/div); printed +/-1.2 V (98.80 / 101.2 V) applied.',
    'DC gain (p. 97-98): the procedure measures at 50 Ω first and repeats at 1 MΩ; the test record lists 1 MΩ only (no 50 Ω rows or limits). 1 MΩ only built.',
    'Bandwidth worksheet (pp. 95-96): no 10 mV/div row for 500 / 350 / 200 / 100 MHz instruments and two 1 mV/div rows (150 MHz, 100 MHz) for 200 MHz; '
    'the specification (p. 15) frequencies are used (see the notes on the points).',
    'TPA DANL (p. 82): "50 kHz - 1 GHz (3-SA3 not installed)"; procedure p. 120 checks 5 MHz - 1 GHz. 5 MHz used.',
    'Residual spurs (p. 80): the "5 MHz to 2 GHz (not 1.25 GHz)" row has no 3-SA3 qualifier; the procedure (p. 113) checks 5 MHz - 1 GHz without '
    '3-SA3 and 5 MHz - 2 GHz with it. Built as the procedure.',
    'DVM frequency 150 MHz (p. 88): printed +/-10 kHz; specification p. 46 (+/-(10 uHz/Hz + 1 count)) gives +/-11.5 kHz. Printed (tighter) limit applied. '
    'Specification p. 46: counter maximum 100 MHz for 100 MHz models - the 150 MHz point is not run on them.',
]
DISCREPANCIES.extend(MISPRINTS)

# ---- write ---------------------------------------------------------------------------------------------------------------------------------
for i, p in enumerate(points, 1):
    p['id'] = i
spec = dict(schema=2, manufacturer='Tektronix', model='MDO3', models=MODELS, model_info=MODEL_INFO,
            title='3 Series MDO (MDO32 / MDO34) Performance Verification',
            options=dict(sa=['None', 'SA3'], tokens=['SA3', 'noSA3', 'AFG', 'DVM', 'TPA', 'noTPA'],
                         note='The 1 GHz spectrum analyzer is standard on every model (p. 11); 3-SA3 extends it to 3 GHz. 3-AFG, 3-DVM, TPA-N-PRE as on the label.'),
            source=dict(document='3 Series MDO Specifications and Performance Verification (077-1499-10)', pages='47-130 (test record pp. 48-89, procedures pp. 90-130)',
                        note='Limits are the printed test-record limits, typed from the rendered page images. Tables that repeat per channel were read per channel.'),
            sections=[dict(id=s, title=TITLES[s], page=PAGES[s], record_page=RECORD_PAGES[s]) for s in ORDER],
            discrepancies=DISCREPANCIES, points=points)

if __name__ == '__main__':
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(len(points), dict(Counter(p['section'] for p in points)))
    for d in DISCREPANCIES:
        print('  !', d)
