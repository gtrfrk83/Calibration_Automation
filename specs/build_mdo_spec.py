"""Builds specs/tektronix_mdo4000c_pv.json from the MDO4000C Series Specifications and Performance Verification manual
(077-1178-01 Rev B, test record pp. 35-83, procedures pp. 85-143). Delta-time tables are parsed from the manual text (every
channel table as printed); the other tables are typed from the test record and cross-checked against it.

Point fields (base units): section, kind, desc, ch, nominal, low, high (None = one-sided), unit, models (None = all),
req (list of option tokens that must all hold: SA SA6 noSA AFG DVM DIG TPA noTPA), stim, plus per-kind parameters.
"""
import json, re, sys

sys.path.insert(0, '/home/claude/scratch/mdo')
MODELS = ['4024C', '4034C', '4054C', '4104C']
MM = 1e-3
PAGES = {'selftest': 85, 'imp': 86, 'bal': 88, 'gain': 90, 'off': 94, 'bw': 96, 'noise': 99, 'ref': 101, 'dt': 103, 'dig': 105,
         'phase': 109, 'danl': 112, 'abs': 118, 'imd': 122, 'spur': 126, 'xt': 128, 'trig': 130, 'tpa': 131, 'tpadanl': 134,
         'afgf': 139, 'afga': 140, 'afgo': 140, 'dvmdc': 141, 'dvmac': 142, 'dvmf': 143}
TITLES = {'selftest': 'Self test and signal path compensation', 'imp': 'Input impedance', 'bal': 'DC balance', 'gain': 'DC gain accuracy',
          'off': 'DC offset accuracy', 'bw': 'Analog bandwidth', 'noise': 'Random noise (sample mode)', 'ref': 'Reference frequency error',
          'dt': 'Delta-time measurement accuracy', 'dig': 'Digital threshold accuracy', 'phase': 'Phase noise at 1 GHz',
          'danl': 'Displayed average noise level (DANL)', 'abs': 'Absolute amplitude accuracy', 'imd': 'Third-order intermodulation',
          'spur': 'Residual spurious response', 'xt': 'Crosstalk to RF channel', 'trig': 'Trigger output', 'tpa': 'TPA-N-PRE functional check',
          'tpadanl': 'DANL with TPA-N-PRE attached', 'afgf': 'AFG frequency accuracy', 'afga': 'AFG amplitude accuracy',
          'afgo': 'AFG DC offset accuracy', 'dvmdc': 'DVM voltage accuracy (DC)', 'dvmac': 'DVM voltage accuracy (AC)', 'dvmf': 'DVM frequency accuracy'}
ORDER = list(TITLES)
points = []


def add(sec, kind, desc, nominal, low, high, unit, ch=None, models=None, req=None, stim='cal', **kw):
    p = dict(section=sec, kind=kind, desc=desc, ch=ch, nominal=nominal, low=low, high=high, unit=unit, stim=stim)
    if models: p['models'] = models
    if req: p['req'] = req
    p.update(kw)
    points.append(p)


def f4(x):
    return float(f'{x:.9g}')


def vtxt(v):
    a = abs(v)
    return f'{v * 1e3:g} mV' if a < 1 else f'{v:g} V'


CH = [1, 2, 3, 4]

# ---- self test ------------------------------------------------------------------------------------------------------------
add('selftest', 'SELFTEST', 'System diagnostics (all tests pass)', 1, 1, 1, '', stim='none', passfail=True)
add('selftest', 'SPC', 'Signal path compensation (status Pass)', 1, 1, 1, '', stim='none', passfail=True)

# ---- input impedance --------------------------------------------------------------------------------------------------------
for ch in CH:
    for vs in (0.01, 0.1, 1.0):
        add('imp', 'IMP', f'CH{ch} 1 MΩ, {vtxt(vs)}/div', 1e6, 990e3, 1.01e6, 'ohm', ch=ch, term='1M', vscale=vs, stim='cal')
    add('imp', 'IMP', f'CH{ch} 250 kΩ, 100 mV/div', 250e3, 245e3, 255e3, 'ohm', ch=ch, term='250k', vscale=0.1, stim='cal')
    for vs in (0.01, 0.1):
        add('imp', 'IMP', f'CH{ch} 50 Ω, {vtxt(vs)}/div', 50.0, 49.5, 50.5, 'ohm', ch=ch, term='50', vscale=vs, stim='cal')
add('imp', 'IMP', 'AUX IN 250 kΩ', 250e3, 245e3, 255e3, 'ohm', ch='AUX', term='250k', vscale=None, req=['noSA'], stim='cal')

# ---- DC balance ------------------------------------------------------------------------------------------------------------
BAL50 = [(1, .2), (2, .2), (5, .5), (10, 1), (20, 2), (49.8, 4.98), (50, 5), (100, 10), (200, 20), (500, 50), (1000, 100)]
BAL1M = [(1, .225), (2, .4), (5, 1), (10, 2), (20, 4), (100, 20), (500, 100), (1000, 200), (10000, 2000)]
for ch in CH:
    for term, tl, rows in (('50', '50 Ω', BAL50), ('1M', '1 MΩ', BAL1M)):
        for vs, lim in rows:
            add('bal', 'BAL', f'CH{ch} {tl}, 20 MHz BW, {vs:g} mV/div', 0.0, -lim * MM, lim * MM, 'V', ch=ch, term=term, bw='TWEnty', vscale=vs * MM, stim='none')
        for bw, bl, models in (('TWOFifty', '250 MHz BW', ['4034C', '4054C', '4104C']), ('FULl', 'Full BW', None)):
            lim = 2 if term == '50' else 4
            add('bal', 'BAL', f'CH{ch} {tl}, {bl}, 20 mV/div', 0.0, -lim * MM, lim * MM, 'V', ch=ch, term=term, bw=bw, vscale=0.02, stim='none', models=models)

# ---- DC gain ---------------------------------------------------------------------------------------------------------------
G50 = [(1, 9, 2.0), (2, 18, 1.5), (5, 45, 1.5), (10, 90, 1.5), (20, 180, 1.5), (49.8, 448.2, 3.0), (50, 450, 1.5), (100, 900, 1.5), (200, 1800, 1.5), (500, 4900, 1.5), (1000, 9000, 1.5)]
G1M = [(1, 9, 2.0), (2, 18, 1.5), (5, 45, 1.5), (10, 90, 1.5), (20, 180, 1.5), (50, 450, 1.5), (63.5, 571.5, 3.0), (100, 900, 1.5), (200, 1800, 1.5), (500, 4900, 1.5), (1000, 9000, 1.5), (5000, 45000, 1.5)]
for ch in CH:
    for term, tl, rows in (('50', '50 Ω', G50), ('1M', '1 MΩ', G1M)):
        def gp(vs, vd, lim, bw, bl, models=None):
            add('gain', 'GAIN', f'CH{ch} {tl}, {bl}, {vs:g} mV/div', 0.0, -lim, lim, '%', ch=ch, term=term, bw=bw, vscale=vs * MM,
                vdiff=f4(vd * MM), vneg=f4(-vd * MM / 2), vpos=f4(vd * MM / 2), models=models)
        for vs, vd, lim in rows:
            gp(vs, vd, lim, 'TWEnty', '20 MHz BW')
        gp(20, 180, 1.5, 'TWOFifty', '250 MHz BW', ['4034C', '4054C', '4104C'])
        gp(20, 180, 1.5, 'FULl', 'Full BW')

# ---- DC offset -------------------------------------------------------------------------------------------------------------
OFF50 = [(0.001, 0.9, 895.3e-3, 904.7e-3), (0.1, 5.0, 4.965, 5.035)]
OFF1M = [(0.001, 0.9, 895.3e-3, 904.7e-3), (0.1, 9.0, 8.935, 9.065), (0.5, 9.0, 8.855, 9.145), (1.01, 99.5, 98.80, 100.2), (3.0, 99.5, 98.40, 100.6), (5.0, 99.5, 98.00, 101.0)]
for ch in CH:
    for term, tl, rows in (('50', '50 Ω', OFF50), ('1M', '1 MΩ', OFF1M)):
        for vs, off, lo, hi in rows:
            for sign in (1, -1):
                add('off', 'OFFSET', f'CH{ch} {tl}, 20 MHz BW, {vtxt(vs)}/div, offset {vtxt(sign * off)}', sign * off,
                    lo if sign > 0 else -hi, hi if sign > 0 else -lo, 'V', ch=ch, term=term, bw='TWEnty', vscale=vs, offset=sign * off)

# ---- analog bandwidth ------------------------------------------------------------------------------------------------------
SCALES = [(0.001, 4e-9), (0.002, 2e-9), (0.005, 1e-9), (0.01, 1e-9), (0.05, 1e-9), (0.1, 1e-9), (1.0, 1e-9)]


def bw_freq(model, term, vs):
    if term == '50':
        top = {'4104C': 500e6, '4054C': 500e6, '4034C': 350e6, '4024C': 200e6}[model]     # 4104C: 500 MHz (not 1 GHz) at 5 mV/div, footnote p.99
        if vs < 0.002: return 175e6
        if vs < 0.005: return 200e6 if model == '4024C' else 350e6
        if model == '4104C' and vs >= 0.01: return 1e9
        return top
    top = {'4104C': 500e6, '4054C': 380e6, '4034C': 350e6, '4024C': 200e6}[model]
    if vs < 0.002: return 175e6
    if vs < 0.005: return 200e6 if model == '4024C' else 350e6
    return top


for model in MODELS:
    for term, tl in (('50', '50 Ω'), ('1M', '1 MΩ')):
        for ch in CH:
            for vs, hs in SCALES:
                fr = bw_freq(model, term, vs)
                vin = 3.0 if vs >= 0.5 else 8 * vs
                add('bw', 'BW', f'CH{ch} {tl}, {vtxt(vs)}/div, {fr / 1e6:g} MHz', 1.0, 0.707, None, 'ratio', ch=ch, term=term, vscale=vs, hscale=hs,
                    freq=fr, vin_pp=f4(vin), ref_hz=50e3, models=[model], req=(['SA'] if (term == '1M' and model != '4104C') else None))

# ---- random noise ----------------------------------------------------------------------------------------------------------
NOISE = {  # (group, sa) -> {(term, bw): limit mV}
    ('4104C', None): {('1M', 'FULl'): 8.30, ('1M', 'TWOFifty'): 5.10, ('1M', 'TWEnty'): 5.10, ('50', 'FULl'): 6.08, ('50', 'TWOFifty'): 4.05, ('50', 'TWEnty'): 4.05},
    ('other', False): {('1M', 'FULl'): 8.13, ('1M', 'TWOFifty'): 6.10, ('1M', 'TWEnty'): 4.10, ('50', 'FULl'): 8.13, ('50', 'TWOFifty'): 6.10, ('50', 'TWEnty'): 4.10},
    ('other', True): {('1M', 'FULl'): 8.30, ('1M', 'TWOFifty'): 6.10, ('1M', 'TWEnty'): 4.10, ('50', 'FULl'): 8.13, ('50', 'TWOFifty'): 6.10, ('50', 'TWEnty'): 4.10},
}
BWN = {'FULl': 'Full BW', 'TWOFifty': '250 MHz BW', 'TWEnty': '20 MHz BW'}
for key, rows in NOISE.items():
    for ch in CH:
        for (term, bw), lim in rows.items():
            if key[0] == '4104C':
                models, req = ['4104C'], None
            else:
                models, req = ['4024C', '4034C', '4054C'], ['SA' if key[1] else 'noSA']
            if bw == 'TWOFifty': models = [m for m in models if m != '4024C']
            if not models: continue
            add('noise', 'NOISE', f'CH{ch} {"1 MΩ" if term == "1M" else "50 Ω"}, {BWN[bw]}, 100 mV/div', 0.0, None, lim * MM, 'V', ch=ch, term=term, bw=bw,
                vscale=0.1, stim='none', models=models, req=req)

# ---- reference frequency ---------------------------------------------------------------------------------------------------
add('ref', 'REFFREQ', 'Time-base error (400 ms mark, 200 ns/div)', 0.0, -640e-9, 640e-9, 's', ch=1, req=['SA'], stim='gen', period=0.4)
add('ref', 'REFFREQ', 'Time-base error (400 ms mark, 200 ns/div)', 0.0, -2e-6, 2e-6, 's', ch=1, req=['noSA'], stim='gen', period=0.4)

# ---- delta time (parsed from the manual text, every channel table as printed) -----------------------------------------------
dt = json.load(open('/home/claude/scratch/mdo/dt_all.json'))
for rec in dt:
    models = ['4104C'] if rec['model'] == 'MDO4104C' else ['4024C', '4034C', '4054C']
    ch = rec['ch']
    for blk in rec['blocks']:
        for vs, vpp, hi in blk['rows']:
            add('dt', 'DELTA', f'CH{ch} {blk["hscale"] * 1e9 if blk["hscale"] < 1e-6 else blk["hscale"] * 1e6:g} {"ns" if blk["hscale"] < 1e-6 else "µs"}/div, '
                f'{blk["freq"] / 1e6:g} MHz, {vtxt(vs)}/div ({vtxt(vpp)} p-p)' if blk['freq'] >= 1e6 else
                f'CH{ch} {blk["hscale"] * 1e6 if blk["hscale"] < 1e-3 else blk["hscale"] * 1e3:g} {"µs" if blk["hscale"] < 1e-3 else "ms"}/div, '
                f'{blk["freq"] / 1e3:g} kHz, {vtxt(vs)}/div ({vtxt(vpp)} p-p)',
                0.0, None, hi, 's', ch=ch, vscale=vs, vpp=vpp, hscale=blk['hscale'], freq=blk['freq'], models=models,
                req=['SA' if rec['sa'] else 'noSA'], stim='cal')

# ---- digital thresholds -----------------------------------------------------------------------------------------------------
for d in range(16):
    for thr, lo, hi in ((0.0, -0.1, 0.1), (4.0, 3.78, 4.22)):
        add('dig', 'DIGITAL', f'D{d} threshold {thr:g} V', thr, lo, hi, 'V', ch=f'D{d}', threshold=thr, req=['DIG'])

# ---- RF ---------------------------------------------------------------------------------------------------------------------
for off, lim, span, rbw in ((10e3, -108, 50e3, 250), (100e3, -110, 500e3, 1e3), (1e6, -120, 5e6, 50e3)):
    add('phase', 'PHASE', f'1 GHz carrier, {off / 1e3:g} kHz offset', 0.0, None, lim, 'dBc/Hz', req=['SA'], stim='rf', offset_hz=off, span=span, rbw=rbw)
DANL = [(9e3, 50e3, -116, False, -119), (50e3, 5e6, -130, False, -140), (5e6, 400e6, -146, False, -156), (400e6, 3e9, -147, False, -157),
        (3e9, 4e9, -148, True, -158), (4e9, 6e9, -140, True, -150)]
for lo_f, hi_f, lim, sa6, tlim in DANL:
    name = lambda x: f'{x / 1e9:g} GHz' if x >= 1e9 else f'{x / 1e6:g} MHz' if x >= 1e6 else f'{x / 1e3:g} kHz'
    add('danl', 'DANL', f'{name(lo_f)} to {name(hi_f)}', 0.0, None, lim, 'dBm/Hz', req=['SA6' if sa6 else 'SA', 'noTPA'], stim='none', f_start=lo_f, f_stop=hi_f, ref_level=-25.0)
    add('tpadanl', 'DANL', f'{name(lo_f)} to {name(hi_f)} (TPA-N-PRE)', 0.0, None, tlim, 'dBm/Hz', req=['SA6' if sa6 else 'SA', 'TPA'], stim='none', f_start=lo_f, f_stop=hi_f, ref_level=-40.0, tpa=True)

AA_BANDS = [('50 kHz - 950 kHz', 50e3, 100e3, 950e3, 100e3, 'SA'), ('1 MHz - 9 MHz', 1e6, 1e6, 9e6, 2e6, 'SA'), ('10 MHz - 90 MHz', 10e6, 10e6, 90e6, 20e6, 'SA'),
            ('100 MHz - 3 GHz', 100e6, 100e6, 2.9e9, 50e6, 'SA'), ('>3 GHz - 6 GHz', 3.1e9, 100e6, 5.9e9, 50e6, 'SA6')]
for level in (10, 0, -15):
    for name, f0, step, f1, span, req in AA_BANDS:
        add('abs', 'ABSAMP', f'{level:+d} dBm, {name}', float(level), -1.0, 1.0, 'dB', req=[req], stim='rf', level_dbm=float(level), f_start=f0, f_step=step, f_stop=f1, span=span)

add('imd', 'IMD', 'Centre 2.745 GHz, intermod spur 1 (20 MHz below f1)', 0.0, None, -62, 'dBc', req=['SA'], stim='rf2', f1=2.735e9, f2=2.755e9, center=2.745e9, which='low')
add('imd', 'IMD', 'Centre 2.745 GHz, intermod spur 2 (20 MHz above f2)', 0.0, None, -62, 'dBc', req=['SA'], stim='rf2', f1=2.735e9, f2=2.755e9, center=2.745e9, which='high')
add('imd', 'IMD', 'Centre 4.5 GHz, intermod spur 1 (20 MHz below f1)', 0.0, None, -62, 'dBc', req=['SA6'], stim='rf2', f1=4.49e9, f2=4.51e9, center=4.5e9, which='low')
add('imd', 'IMD', 'Centre 4.5 GHz, intermod spur 2 (20 MHz above f2)', 0.0, None, -62, 'dBc', req=['SA6'], stim='rf2', f1=4.49e9, f2=4.51e9, center=4.5e9, which='high')

SPURS = [('9 kHz - 50 kHz', 9e3, 50e3, 300.0, [], -85, 'SA', 'span'), ('50 kHz - 3 GHz (excluding 2.5 GHz)', 50e3, 3e9, 50e3, [2.5e9], -85, 'SA', 'span'),
         ('2.5 GHz spur', 2.5e9, 2.5e9, 50e3, None, -73, 'SA', 'at'), ('2.75 GHz - 4.5 GHz (excluding 3.75 GHz)', 2.75e9, 4.5e9, 50e3, [3.75e9], -85, 'SA6', 'span'),
         ('3.5 GHz - 5.99 GHz (excluding 4 GHz, 5 GHz)', 3.5e9, 6.0e9, 50e3, [4e9, 5e9], -85, 'SA6', 'span'), ('3.75 GHz spur', 3.75e9, 3.75e9, 50e3, None, -78, 'SA6', 'at'),
         ('4 GHz spur', 4e9, 4e9, 50e3, None, -78, 'SA6', 'at'), ('5 GHz spur', 5e9, 5e9, 50e3, None, -78, 'SA6', 'at')]
for name, f0, f1, rbw, excl, lim, req, mode in SPURS:
    add('spur', 'SPUR', name, 0.0, None, lim, 'dBm', req=[req], stim='none', f_start=f0, f_stop=f1, rbw=rbw, exclude=excl or [], at_freq=(f0 if mode == 'at' else None))

XF = [105e6 + 100e6 * i for i in range(20)]
for ch in CH:
    for f in XF:
        add('xt', 'XTALK', f'CH{ch} at {f / 1e6:g} MHz', 0.0, None, -68 if f < 1.1e9 else -48, 'dBm', ch=ch, req=['SA'], stim='rf', freq=f, vpp=0.633)

add('trig', 'TRIGOUT', 'Trigger out HIGH, 1 MΩ', 2.5, 2.5, None, 'V', ch=1, term='1M', state='HIGH', stim='none')
add('trig', 'TRIGOUT', 'Trigger out LOW, 1 MΩ', 0.7, None, 0.7, 'V', ch=1, term='1M', state='LOW', stim='none')
add('trig', 'TRIGOUT', 'Trigger out HIGH, 50 Ω', 1.0, 1.0, None, 'V', ch=1, term='50', state='HIGH', stim='none')
add('trig', 'TRIGOUT', 'Trigger out LOW, 50 Ω', 0.25, None, 0.25, 'V', ch=1, term='50', state='LOW', stim='none')

for freq, ref, name, req in ((1.7e9, 'SA', '1.7 GHz', 'SA'), (5.5e9, 'SA6', '5.5 GHz', 'SA6')):
    for level, rl in ((-30.0, -25.0), (-45.0, -40.0)):
        add('tpa', 'TPAFUNC', f'{name}, {level:g} dBm in, reference level {rl:g} dBm', 0.0, -2.0, 2.0, 'dB', req=[req, 'TPA'], stim='rf', freq=freq, level_dbm=level, ref_level=rl, span=50e6)

# ---- AFG -------------------------------------------------------------------------------------------------------------------
for wave, f, lo, hi in (('SINE', 10e3, 9.9987e3, 10.0013e3), ('SINE', 50e6, 49.9975e6, 50.0025e6), ('SQUare', 25e3, 24.99875e3, 25.00125e3), ('SQUare', 25e6, 24.99875e6, 25.00125e6)):
    add('afgf', 'AFGFREQ', f'{wave.title()} wave {f / 1e3:g} kHz, 2.5 V p-p, 50 Ω' if f < 1e6 else f'{wave.title()} wave {f / 1e6:g} MHz, 2.5 V p-p, 50 Ω',
        f, lo, hi, 'Hz', req=['AFG'], stim='none', wave=wave, vpp=2.5)
add('afga', 'AFGAMP', 'Square 20 mV p-p at 1 kHz, 0 V offset, 50 Ω (rms)', 10e-3, 9.35e-3, 10.65e-3, 'V', req=['AFG'], stim='none', vpp=0.02, offset=0.0, freq=1e3)
add('afga', 'AFGAMP', 'Square 1 V p-p at 1 kHz, 0.2 V offset, 50 Ω (rms)', 0.5, 490.5e-3, 509.5e-3, 'V', req=['AFG'], stim='none', vpp=1.0, offset=0.2, freq=1e3)
add('afgo', 'AFGOFF', 'DC 20 mV into 50 Ω', 20e-3, 18.7e-3, 21.3e-3, 'V', req=['AFG'], stim='none', level=0.02)
add('afgo', 'AFGOFF', 'DC 1 V into 50 Ω', 1.0, 0.984, 1.016, 'V', req=['AFG'], stim='none', level=1.0)

# ---- DVM ---------------------------------------------------------------------------------------------------------------------
DVMDC = [(1, -5, -5, -5.125, -4.875), (.5, -2, -2, -2.06, -1.94), (.5, -1, -.5, -1.06, -.94), (.2, -.5, -.5, -.5225, -.4775), (.01, .002, 0, .00097, .00303),
         (.2, .5, .5, .4775, .5225), (.5, 1, .5, .94, 1.06), (.5, 2, 2, 1.94, 2.06), (1, 5, 5, 4.875, 5.125)]
for ch in CH:
    for vs, vin, off, lo, hi in DVMDC:
        add('dvmdc', 'DVMDC', f'CH{ch} {vtxt(vs)}/div, input {vtxt(vin)}, offset {vtxt(off)}', vin, lo, hi, 'V', ch=ch, req=['DVM'], vscale=vs, offset=off)
DVMAC = [(.005, .02, 9.8e-3, 10.2e-3), (.01, .05, 24.5e-3, 25.5e-3), (.1, .5, 245e-3, 255e-3), (.2, 1.0, 490e-3, 510e-3), (1.0, 5.0, 2.45, 2.55)]
for ch in CH:
    for vs, vpp, lo, hi in DVMAC:
        add('dvmac', 'DVMAC', f'CH{ch} {vtxt(vs)}/div, {vtxt(vpp)} p-p square at 1 kHz (rms)', vpp / 2, lo, hi, 'V', ch=ch, req=['DVM'], vscale=vs, vpp=vpp, freq=1e3)
DVMF = [(10.0, 9.9989, 10.001), (100.0, 99.989, 100.01), (1e3, 999.89, 1000.1), (100e3, 99.989e3, 100.01e3), (1e6, 999.89e3, 1.0001e6), (150e6, 149.98e6, 150.02e6)]
for ch in CH:
    for f, lo, hi in DVMF:
        note = 'The manual prints 180 MHz for this row but gives limits of 149.98-150.02 MHz; the limits are applied at 150 MHz.' if f == 150e6 else None
        add('dvmf', 'DVMFREQ', f'CH{ch} {f / 1e6:g} MHz' if f >= 1e6 else f'CH{ch} {f / 1e3:g} kHz' if f >= 1e3 else f'CH{ch} {f:g} Hz', f, lo, hi, 'Hz', ch=ch,
            req=['DVM'], freq=f, stim='cal', **({'note': note} if note else {}))

# ---- write -------------------------------------------------------------------------------------------------------------------
for i, p in enumerate(points, 1):
    p['id'] = i
spec = dict(schema=2, manufacturer='Tektronix', model='MDO4000C', models=MODELS,
            title='MDO4000C Series Performance Verification',
            source=dict(document='MDO4000C Series Specifications and Performance Verification (077-1178-01 Rev B)', pages='33-143 (test record pp. 35-83)',
                        note='All limits are the printed test-record limits. Tables that repeat per channel were taken per channel as printed.'),
            sections=[dict(id=s, title=TITLES[s], page=PAGES[s]) for s in ORDER], points=points)
json.dump(spec, open('/home/claude/calsuite/specs/tektronix_mdo4000c_pv.json', 'w'), indent=1, ensure_ascii=False)
from collections import Counter
print(len(points), Counter(p['section'] for p in points))
