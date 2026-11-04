"""More hook-up diagrams, drawn in the same style as specs/build_hookups.py:

    python3 specs/build_hookups_ext.py             (needs Pillow; the procedures themselves do not)

  * Fluke 287 / 289, four-wire ohms (group OHM4):     hook_fluke28x_<5560A|5522A>_OHM4.png
  * bench DMMs, Fluke 5560A to the meter's front jacks: hook_<model>_5560A_<KEY>.png   models 34401A 34460A 34461A 34465A 8846A
        KEY: VOLT  RES2  RES4  SHORT  OPEN  I_<jack>  (I_I, I_3A, I_10A, I_400MA)
  * Keithley DMM6500, calibrator 5560A or 5522A (a 5520A uses the 5522A picture): hook_dmm6500_<5560A|5522A>_<GROUP>.png  (GROUPs: diagrams/README_dmm6500.txt)

    python3 specs/build_hookups_ext.py             (every set)
    python3 specs/build_hookups_ext.py dmm6500     (only the named set(s): fluke28x, bench, dmm6500; the other diagrams stay byte for byte as they are)

The jack layouts of the bench meters are read from the front-panel photos the owner supplied (diagrams/README_panels.txt); nothing here
changes a prompt's text, limits or commands - the pictures are only what the prompts show.   (The 28x's other groups are drawn by build_hookups.py.)
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import build_hookups as B                                   # noqa: E402
from build_hookups import P, K, W, H, RED, BLACK, AMBER, OUT, JACK_Y, METER_DRAW, draw_5560a, draw_5522a, draw_meter, draw_jack, draw_labels, draw_cable  # noqa: E402
import draw_kit                                             # noqa: E402
from draw_kit import Pen, min_distance                      # noqa: E402


def _windows_fonts():
    """draw_kit looks for the Linux DejaVu fonts only; on a machine without them (Windows) fall back to Verdana / Consolas, which have the same proportions.
    Where DejaVu exists nothing changes."""
    from PIL import ImageFont
    if Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf').exists():
        return None
    base, cache = 'C:/Windows/Fonts/', {}

    def get(size, bold=True, mono=False):
        name = ('consolab.ttf' if bold else 'consola.ttf') if mono else ('verdanab.ttf' if bold else 'verdana.ttf')
        key = (round(size * 4), name)
        if key not in cache:
            cache[key] = ImageFont.truetype(base + name, max(1, int(round(size * draw_kit.S))))
        return cache[key]
    return get


if _windows_fonts() is not None:
    draw_kit._fonts = _windows_fonts


def path_len(r):
    return sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(r, r[1:]))


def route_all(cables, candidates, clearance):
    """cables: list of dicts. candidates(cable) -> list of routes. clearance(a, b) -> minimum distance wanted between cables a and b.
    Tries every order (greedy, shortest non-touching route first); returns routes in the cables' order (touching allowed only if nothing else exists)."""
    for need_clear in (True, False):
        best = None
        for order in itertools.permutations(range(len(cables))):
            chosen, total, ok = {}, 0, True
            for i in order:
                pick = None
                for r in sorted(candidates(cables[i]), key=path_len):
                    if need_clear and any(min_distance(r, chosen[j]) < clearance(cables[i], cables[j]) for j in chosen):
                        continue
                    pick = r
                    break
                if pick is None:
                    ok = False
                    break
                chosen[i] = pick
                total += path_len(pick)
            if ok and (best is None or total < best[0]):
                best = (total, chosen)
        if best:
            return [best[1][i] for i in range(len(cables))]
    raise RuntimeError('no cable routes found')


# ------------------------------------------------------------------------------------------------ 287 / 289, four-wire ohms
def ohm4_candidates(c):
    ex, ey = c['exit'][-1]
    out = []
    for mode in ('above', 'under'):
        for vx in (392, 410, 428, 446):
            if vx >= ex:
                continue
            for ty in ((408, 424, 440, 456) if mode == 'above' else (610, 624, 638)):
                end = (JACK_Y - 46) if mode == 'above' else (JACK_Y + 46)
                out.append([c['start'], *c['exit'], (vx, ey), (vx, ty), (c['x'], ty), (c['x'], end)])
    return out


def hook_ohm4(meter, cal):
    pen = Pen(W, H, '#ffffff')
    if cal == '5560A':
        names = ('OUT_HI', 'OUT_LO', 'SEN_HI', 'SEN_LO')
        jacks = draw_5560a(pen, {n: 'green' for n in names}, False)
        jacks['SEN_HI'] = (jacks['SEN_HI'][0], [P(69, 64), P(-9, 64)])           # sense leads leave between the OUTPUT sockets
        jacks['SEN_LO'] = (jacks['SEN_LO'][0], [P(69, 102), P(-9, 102)])
        force_hi, force_lo, sense_hi, sense_lo = names
        caption = 'Fluke 5560A front panel'
    else:
        names = ('NORMAL_HI', 'NORMAL_LO', 'AUX_HI', 'AUX_LO')
        jacks = draw_5522a(pen, {n: True for n in names})
        force_hi, force_lo, sense_hi, sense_lo = names
        caption = 'Fluke 5522A front panel (output terminals)'
    pen.text(B.PX + 76 * K, B.PY + (276 if cal == '5560A' else 196) * K + 18, caption, 11, '#5a6475', bold=False)
    mj = draw_meter(pen, meter)
    vx, cx = mj['vohm'], mj['com']
    cables = [dict(name=force_hi, color=RED, w=7, x=vx - 5, jack='vohm'), dict(name=force_lo, color=BLACK, w=7, x=cx - 5, jack='com'),
              dict(name=sense_hi, color=RED, w=5, x=vx + 5, jack='vohm'), dict(name=sense_lo, color=BLACK, w=5, x=cx + 5, jack='com')]
    for c in cables:
        c['start'], c['exit'] = jacks[c['name']]
    routes = route_all(cables, ohm4_candidates, lambda a, b: 9 if a['jack'] == b['jack'] else 15)
    for key, label, x in METER_DRAW[meter]['jacks']:
        draw_jack(pen, x, key in ('vohm', 'com'))
    for c, r in sorted(zip(cables, routes), key=lambda t: t[0]['w']):                # thin sense leads first, force leads on top
        draw_cable(pen, r, c['color'], c['w'])
    for c, r in zip(cables, routes):
        end = r[-1]
        under = r[-2][1] > B.JACK_Y
        y0, y1 = (B.JACK_Y + 14, B.JACK_Y + 46) if under else (B.JACK_Y - 46, B.JACK_Y - 14)
        pen.rect(c['x'] - 8, y0, c['x'] + 8, y1, r=4, fill=c['color'], outline='#ffffff', width=1.6)
    for c in cables:
        pen.circle(c['start'][0], c['start'][1], 6.4 * K, fill=c['color'], outline='#ffffff', width=1.8)
    draw_labels(pen, meter, {vx, cx})
    pen.text(400, 650, 'thick leads: output HI / LO   -   thin leads: sense (AUX / SENSE) HI / LO', 9.5, '#5a6475', bold=False)
    pen.save(OUT / f'hook_{meter}_{cal}_OHM4.png')


# ------------------------------------------------------------------------------------------------ bench DMMs
COL_FAR, COL_NEAR = 120, 270                # jack columns: the far one is reached down the corridor between the columns
ROW_HI, ROW_LO, ROW_I = 250, 360, 480
CORRIDOR = (188, 206, 224)
BENCH = {
    # name: (brand, model line, far-column heading, near-column heading, {jack: (column x, row y, label)}, switch note, current jacks)
    '34401A': dict(brand='KEYSIGHT', line='34401A  6½ digit DMM', far='Ω 4W Sense', near='Input  V Ω',
                   jacks={'SE_HI': (COL_FAR, ROW_HI, 'HI'), 'SE_LO': (COL_FAR, ROW_LO, 'LO'), 'IN_HI': (COL_NEAR, ROW_HI, 'HI'),
                          'IN_LO': (COL_NEAR, ROW_LO, 'LO'), 'I_I': (COL_NEAR, ROW_I, 'I  (3 A)')}, switch=True),
    '34460A': dict(brand='KEYSIGHT', line='34460A  6½ digit DMM', far='Sense  Ω 4W', near='Input  V Ω',
                   jacks={'SE_HI': (COL_FAR, ROW_HI, 'HI'), 'SE_LO': (COL_FAR, ROW_LO, 'LO'), 'IN_HI': (COL_NEAR, ROW_HI, 'HI'),
                          'IN_LO': (COL_NEAR, ROW_LO, 'LO'), 'I_3A': (COL_NEAR, ROW_I, 'I  (3 A)')}, switch=False),
    '34461A': dict(brand='KEYSIGHT', line='34461A  6½ digit DMM', far='Sense  Ω 4W', near='Input  V Ω',
                   jacks={'SE_HI': (COL_FAR, ROW_HI, 'HI'), 'SE_LO': (COL_FAR, ROW_LO, 'LO'), 'IN_HI': (COL_NEAR, ROW_HI, 'HI'),
                          'IN_LO': (COL_NEAR, ROW_LO, 'LO'), 'I_10A': (COL_FAR, ROW_I, '10 A'), 'I_3A': (COL_NEAR, ROW_I, '3 A')}, switch=True),
    '8846A': dict(brand='FLUKE', line='8846A  6½ digit DMM', far='INPUT  V Ω', near='SENSE  4W Ω',
                  jacks={'IN_HI': (COL_FAR, ROW_HI, 'HI'), 'IN_LO': (COL_FAR, ROW_LO, 'LO'), 'SE_HI': (COL_NEAR, ROW_HI, 'HI'),
                         'SE_LO': (COL_NEAR, ROW_LO, 'LO'), 'I_400MA': (COL_FAR, ROW_I, '400 mA'), 'I_10A': (COL_NEAR, ROW_I, '10 A')}, switch=True),
}
BENCH['34465A'] = dict(BENCH['34461A'], line='34465A  6½ digit DMM')
BENCH_BODY = {'KEYSIGHT': ('#3a3d44', '#1f2126', '#ffffff', '#e8761d'), 'FLUKE': ('#f3c40f', '#2b2e33', '#ffffff', '#f3c40f')}


def draw_bench(pen, model, used, shorted=()):
    cfg = BENCH[model]
    outer, face, ink, accent = BENCH_BODY[cfg['brand']]
    pen.rect(24, 20, 372, 612, r=30, fill=outer, outline='#15171b', width=4)
    pen.rect(40, 36, 356, 596, r=20, fill=face)
    pen.text(198, 62, cfg['brand'], 14, accent)
    pen.text(198, 84, cfg['line'], 11, ink, bold=False)
    pen.rect(62, 104, 334, 156, r=6, fill='#c9d3bf', outline='#16181b', width=2)
    pen.text(198, 130, '8.8.8.8.8.8', 26, '#8e9a84', mono=True)
    pen.text(COL_FAR, 176, cfg['far'], 11, ink)
    pen.text(COL_NEAR, 176, cfg['near'], 11, ink)
    pos = {}
    for key, (x, y, label) in cfg['jacks'].items():
        pos[key] = (x, y)
        red = key.endswith('HI') or key.startswith('I_')
        if key in used:
            pen.circle(x, y, 25, outline=AMBER, width=4)
        pen.circle(x, y, 18, fill='#0d0e10', outline='#c0392b' if red else '#8b919b', width=3.2)
        pen.circle(x, y, 7, fill='#3a3f47')
        w = pen.text_size(label, 10.5)[0] + 14
        pen.rect(x - w / 2, y + 24, x + w / 2, y + 44, r=7, fill='#2f333a')
        pen.text(x, y + 34, label, 10.5, ink if key in used else '#9aa0aa')
    if cfg['switch']:
        pen.text(198, 572, 'FRONT / REAR switch: FRONT', 10, '#9aa0aa', bold=False)
    return pos


def bench_candidates(c, pos):
    ex, ey = c['exit'][-1]
    jx, jy = pos[c['jack']]
    out = []
    for vx in (392, 410, 428, 446):
        if vx >= ex:
            continue
        if jx == COL_NEAR:
            out.append([c['start'], *c['exit'], (vx, ey), (vx, jy), (jx + 46, jy)])
        else:
            for ty in (192, 206, 220):
                for cx in CORRIDOR:
                    out.append([c['start'], *c['exit'], (vx, ey), (vx, ty), (cx, ty), (cx, jy), (jx + 46, jy)])
    return out


def bench_cal(pen, names, color, sense=False):
    jacks = draw_5560a(pen, {n: color for n in names}, False)
    if 'SEN_HI' in names:
        jacks['SEN_HI'] = (jacks['SEN_HI'][0], [P(69, 64), P(-9, 64)])
        jacks['SEN_LO'] = (jacks['SEN_LO'][0], [P(69, 102), P(-9, 102)])
    pen.text(B.PX + 76 * K, B.PY + 276 * K + 18, 'Fluke 5560A front panel', 11, '#5a6475', bold=False)
    return jacks


def hook_bench(model, key):
    pen = Pen(W, H, '#ffffff')
    cfg = BENCH[model]
    current = key.startswith('I_')
    if key in ('SHORT', 'OPEN'):
        cal_names, leads = (), []
    elif key in ('VOLT', 'RES2'):
        cal_names, leads = ('OUT_HI', 'OUT_LO'), [('OUT_HI', 'IN_HI', RED, 7), ('OUT_LO', 'IN_LO', BLACK, 7)]
    elif key == 'RES4':
        cal_names = ('OUT_HI', 'OUT_LO', 'SEN_HI', 'SEN_LO')
        leads = [('OUT_HI', 'IN_HI', RED, 7), ('OUT_LO', 'IN_LO', BLACK, 7), ('SEN_HI', 'SE_HI', RED, 5), ('SEN_LO', 'SE_LO', BLACK, 5)]
    else:
        hot = 'THIRTY' if key == 'I_10A' else 'VI_AUX'
        cal_names, leads = (hot, 'OUT_LO'), [(hot, key, RED, 7), ('OUT_LO', 'IN_LO', BLACK, 7)]
    used = {j for _, j, _, _ in leads}
    if key == 'SHORT':
        used = {'IN_HI', 'IN_LO', 'SE_HI', 'SE_LO'} & set(cfg['jacks'])
    pos = draw_bench(pen, model, used)
    if cal_names:
        jacks = bench_cal(pen, cal_names, 'blue' if current else 'green')
    else:
        jacks = draw_5560a(pen, {}, False)
        pen.text(B.PX + 76 * K, B.PY + 276 * K + 18, 'Fluke 5560A: left in STANDBY', 11, '#5a6475', bold=False)
    cables = [dict(name=a, jack=b, color=c, w=w) for a, b, c, w in leads]
    for c in cables:
        c['start'], c['exit'] = jacks[c['name']]
    if cables:
        routes = route_all(cables, lambda c: bench_candidates(c, pos), lambda a, b: 14)
        for c, r in sorted(zip(cables, routes), key=lambda t: t[0]['w']):
            draw_cable(pen, r, c['color'], c['w'])
        if current:                                          # keep the terminal name readable on top of the cable
            label = '30A' if key == 'I_10A' else 'VI AUX'
            tx, ty = P(70, 143) if label == '30A' else P(22, 143)
            w = pen.text_size(label, 4.6 * K)[0] + 8
            pen.rect(tx - w / 2, ty - 8, tx + w / 2, ty + 8, r=5, fill='#dcdcd6')
            pen.text(tx, ty, label, 4.6 * K, '#3a3a3a')
        for c, r in zip(cables, routes):
            jx, jy = pos[c['jack']]
            pen.rect(jx + 14, jy - 8, jx + 46, jy + 8, r=4, fill=c['color'], outline='#ffffff', width=1.6)
            pen.circle(c['start'][0], c['start'][1], 6.4 * K, fill=c['color'], outline='#ffffff', width=1.8)
        if key == 'RES4':
            pen.text(198, 640, 'thick leads: HI / LO   -   thin leads: SENSE HI / LO', 9.5, '#5a6475', bold=False)
    if key == 'SHORT':
        for hi, lo in (('IN_HI', 'IN_LO'), ('SE_HI', 'SE_LO')):
            if hi in pos:
                (x, y0), (_, y1) = pos[hi], pos[lo]
                pen.rect(x - 9, y0 - 6, x + 9, y1 + 6, r=9, fill='#b87333', outline='#ffffff', width=2)
        pen.rect(70, 500, 326, 548, r=8, fill='#2f333a', outline=AMBER, width=2)
        pen.text(198, 517, 'Low-thermal copper short', 11, '#ffffff')
        pen.text(198, 536, 'across INPUT HI / LO and SENSE HI / LO', 9.5, '#c9ced6', bold=False)
    if key == 'OPEN':
        pen.rect(70, 500, 326, 548, r=8, fill='#2f333a', outline=AMBER, width=2)
        pen.text(198, 517, 'Current input left OPEN', 11, '#ffffff')
        pen.text(198, 536, 'nothing connected to any jack', 9.5, '#c9ced6', bold=False)
    pen.save(OUT / f'hook_{model}_5560A_{key}.png')


def bench_keys(model):
    cfg = BENCH[model]
    return ['VOLT', 'RES2', 'RES4', 'SHORT', 'OPEN'] + [k for k in cfg['jacks'] if k.startswith('I_')]


# ------------------------------------------------------------------------------------------------ Keithley DMM6500 (5560A or 5522A)
# Jack layout from the owner's front-panel photo (diagrams/dmm6500_panel.png): top row SENSE HI / INPUT HI, second row SENSE LO / INPUT LO, the AMPS 3A
# BNC-style jack below INPUT LO, TERMINALS FRONT / REAR button.  The 10 A jack is on the REAR panel, which is not in the photo (drawn as an inset, UNVERIFIED).
D65_ROW_REAR = 488
D65_POS = {'SE_HI': (COL_FAR, ROW_HI), 'SE_LO': (COL_FAR, ROW_LO), 'IN_HI': (COL_NEAR, ROW_HI), 'IN_LO': (COL_NEAR, ROW_LO), 'I_3A': (COL_NEAR, ROW_I),
           'R_IN_LO': (COL_FAR, D65_ROW_REAR), 'R_10A': (COL_NEAR, D65_ROW_REAR)}
D65_FRONT = ('SE_HI', 'SE_LO', 'IN_HI', 'IN_LO', 'I_3A')
CAL_TERM = {   # role -> calibrator terminal name used by draw_5560a / draw_5522a (the same terminals hookups.py names for the handheld meters)
    '5560A': dict(hi='OUT_HI', lo='OUT_LO', sen_hi='SEN_HI', sen_lo='SEN_LO', cur_hi='VI_AUX', cur_lo='OUT_LO', amp='THIRTY'),
    '5522A': dict(hi='NORMAL_HI', lo='NORMAL_LO', sen_hi='AUX_HI', sen_lo='AUX_LO', cur_hi='AUX_HI', cur_lo='AUX_LO', amp='TWENTY'),
}
UNV = True      # note flag: not shown in the owner's photo or in a manual figure we have seen
UNV_SENSE = ('UNVERIFIED: the 5560A sense terminals for the sense leads (SENSE HI / LO drawn); confirm on the real calibrator.', UNV, ('5560A',))
# GROUP -> (lead set, notes: (text, unverified))
D65_GROUPS = {
    'DCV': ('V', [('Shielded cable, shield to the calibrator LO; low-thermal connections for the 100 mV and 1 V ranges (CM Fig. 1; digitize voltage points: Fig. 4).', 0)]),
    'ACV': ('V', [('Shielded low-capacitance cable (below 1000 pF), shield to the calibrator LO (CM Fig. 2).', 0)]),
    'ACV750': ('V', [('Low-capacitance cable, below 150 pF for 750 V (CM Fig. 3).', 0),
                     ('UNVERIFIED: the 5725A amplifier the manual puts behind the calibrator for 740 V at 50 kHz and 100 kHz is not drawn.', UNV)]),
    'FREQ': ('V', [('AC voltage from the calibrator at the test frequency (the manual uses a 3390 generator, CM Fig. 5).', 0)]),
    'TC': ('V', [('Low-thermal DC voltage source for the type J table values: the calibrator voltage output, not its TC connector (CM Fig. 6).', 0)]),
    'RTD4': ('R4', [('4-wire PT100 simulation (CM Fig. 7): thick leads = force to INPUT HI / LO, thin leads = sense to SENSE HI / LO; calibrator external sense ON.', 0), UNV_SENSE]),
    'RTD3': ('R3', [('3-wire PT100 simulation (CM Fig. 8): thick leads to INPUT HI / LO, thin lead to SENSE LO; SENSE HI is not used.', 0),
                    ('UNVERIFIED: which calibrator terminal feeds SENSE LO (the calibrator sense LO is drawn); check Figure 8.', UNV)]),
    'SHORT4': ('SHORT', [('Keithley 8610 / 8620 4-wire short across INPUT HI / LO and SENSE HI / LO; no calibrator output (CM Fig. 17).', 0),
                          ('UNVERIFIED: the short is drawn as copper bars; its orientation is as Figure 17 shows (not drawn).', UNV)]),
    'OHM4': ('R4', [('4-wire, shielded Teflon cable (CM Fig. 9): thick leads = force to INPUT HI / LO, thin = sense to SENSE HI / LO; external sense ON.', 0),
                    ('Note: the 3458A reference meter (GPIB) is in the 4-wire loop for the 1 ohm and 10 ohm points: UNVERIFIED wiring, not drawn.', UNV), UNV_SENSE]),
    'OHM2': ('R2', [('2-wire: INPUT HI / LO only, no sense leads, calibrator external sense OFF; shielded Teflon cable (CM Fig. 10).', 0)]),
    'DCI_LOW': ('I', [('Calibrator current to AMPS 3A and INPUT LO, 10 uA to 10 mA (CM Fig. 11).', 0),
                      ('Note: the 3458A (current function) is in series with the DMM6500; UNVERIFIED which lead it sits in, not drawn.', UNV)]),
    'DCI': ('I', [('Calibrator current to AMPS 3A and INPUT LO, 100 mA to 3 A (CM Fig. 12). Check the calibrator range and fuses first.', 0)]),
    'DIGI': ('I', [('Digitize current: the same hook-up as DCI (CM Fig. 13).', 0)]),
    'ACI': ('I', [('AC current: calibrator to AMPS 3A and INPUT LO (CM Fig. 14).', 0)]),
    'REAR10A': ('I10', [('TERMINALS on REAR: calibrator current output to the rear 10A AMPS jack and INPUT LO, heavy short cables (CM Figs. 18 to 20).', 0),
                        ('UNVERIFIED: the rear panel is not in the photo (jack positions are schematic); the 5725A amplifier of the manual is not drawn.', UNV)]),
    'CAP': ('V', [('Calibrator capacitance output to INPUT HI / LO, short shielded cable; first point: the cable alone, calibrator in standby.', 0),
                  ('UNVERIFIED: the 5560A capacitance output terminals (drawn on OUTPUT V/ohm HI / LO).', UNV, ('5560A',))]),
}
D65_LEADS = {      # lead set -> (calibrator role, DMM6500 jack, colour, width)
    'V': [('hi', 'IN_HI', RED, 7), ('lo', 'IN_LO', BLACK, 7)],
    'R2': [('hi', 'IN_HI', RED, 7), ('lo', 'IN_LO', BLACK, 7)],
    'R4': [('hi', 'IN_HI', RED, 7), ('lo', 'IN_LO', BLACK, 7), ('sen_hi', 'SE_HI', RED, 5), ('sen_lo', 'SE_LO', BLACK, 5)],
    'R3': [('hi', 'IN_HI', RED, 7), ('lo', 'IN_LO', BLACK, 7), ('sen_lo', 'SE_LO', BLACK, 5)],
    'I': [('cur_hi', 'I_3A', RED, 7), ('cur_lo', 'IN_LO', BLACK, 7)],
    'I10': [('amp', 'R_10A', RED, 7), ('cur_lo', 'R_IN_LO', BLACK, 7)],
    'SHORT': [],
}


def draw_dmm6500(pen, used, rear=False, shorted=False):
    """The DMM6500 front panel, jacks where the owner's photo has them. used: jack keys to ring in amber. rear: TERMINALS on REAR, the front jacks are dimmed and the
    rear-panel inset is drawn (UNVERIFIED layout)."""
    ink, red = '#2b2e33', '#d71920'
    pen.rect(24, 20, 372, 612, r=26, fill='#9ca0a6', outline='#15171b', width=4)
    pen.rect(40, 36, 356, 596, r=16, fill='#dcdee1')
    pen.rect(52, 48, 138, 72, r=3, fill=red)
    pen.text(95, 60, 'KEITHLEY', 12, '#ffffff')
    pen.text(262, 60, 'DMM6500', 14, ink)
    pen.text(262, 80, '6½ digit multimeter', 10, ink, bold=False)
    pen.rect(62, 104, 334, 156, r=6, fill='#0b0d0e', outline='#16181b', width=2)
    pen.text(198, 130, '+0.000000', 24, '#3bd16f', mono=True)
    pen.text(COL_FAR, 176, 'SENSE  Ω 4 WIRE', 10.5, ink)
    pen.text(COL_NEAR, 176, 'INPUT', 11, ink)
    labels = []
    for key in D65_FRONT:
        x, y = D65_POS[key]
        on = key in used and not rear
        if on:
            pen.circle(x, y, 25, outline=AMBER, width=4)
        if key == 'I_3A':                                          # the AMPS jack is a larger BNC-style socket
            pen.circle(x, y, 21, fill='#b9bcc1', outline='#6b7078', width=2.5)
            pen.circle(x, y, 14, fill='#e9eaec', outline='#8b919b', width=2)
            pen.circle(x, y, 6, fill='#7d6a4a', outline='#4a3f2c', width=1.5)
            label = 'AMPS 3A'
        else:
            hi = key.endswith('HI')
            pen.circle(x, y, 18, fill='#0d0e10', outline=('#c0392b' if hi else '#8b919b') if not rear else '#6b7078', width=3.2)
            pen.circle(x, y, 7, fill='#3a3f47')
            label = 'HI' if hi else 'LO'
        labels.append((x, y, label, on))
    if shorted:
        for hi, lo in (('IN_HI', 'IN_LO'), ('SE_HI', 'SE_LO')):
            (x, y0), (_, y1) = D65_POS[hi], D65_POS[lo]
            pen.rect(x - 9, y0 - 6, x + 9, y1 + 6, r=9, fill='#b87333', outline='#ffffff', width=2)
    for x, y, label, on in labels:
        w = pen.text_size(label, 10.5)[0] + 14
        pen.rect(x - w / 2, y + 26, x + w / 2, y + 46, r=7, fill='#2f333a')
        pen.text(x, y + 36, label, 10.5, '#ffffff' if on else '#9aa0aa')
    if rear:
        pen.rect(46, 408, 350, 546, r=10, fill='#f7f1e3', outline='#b45309', width=2.4)      # the header sits right of the cable corridor (x 188 to 224)
        pen.text(292, 421, 'REAR PANEL', 10, '#7a3a00')
        pen.text(292, 435, 'not in the photo:', 8.5, '#b45309', bold=False)
        pen.text(292, 447, 'layout UNVERIFIED', 8.5, '#b45309', bold=False)
        for key, label in (('R_IN_LO', 'INPUT LO'), ('R_10A', 'AMPS 10 A')):
            x, y = D65_POS[key]
            pen.circle(x, y, 25, outline=AMBER, width=4)
            big = key == 'R_10A'
            pen.circle(x, y, 21 if big else 18, fill='#b9bcc1' if big else '#0d0e10', outline='#6b7078' if big else '#8b919b', width=3)
            pen.circle(x, y, 7, fill='#3a3f47')
            w = pen.text_size(label, 10)[0] + 14
            pen.rect(x - w / 2, y + 26, x + w / 2, y + 46, r=7, fill='#2f333a')
            pen.text(x, y + 36, label, 10, '#ffffff')
    for label, yy, lit in (('FRONT', 554, not rear), ('REAR', 574, rear)):          # TERMINALS FRONT / REAR indicator (the switch cannot be set remotely)
        pen.text(104, yy, label, 9.5, ink, bold=False)
        pen.circle(136, yy, 5, fill='#d6e640' if lit else '#6b7078', outline='#444', width=1)
    pen.circle(198, 564, 14, fill='#8b919b', outline='#3d424b', width=2)
    pen.text(262, 564, 'TERMINALS', 9.5, ink)


def wrap_text(pen, text, size, maxw):
    lines, cur = [], ''
    for word in text.split():
        trial = (cur + ' ' + word).strip()
        if cur and pen.text_size(trial, size, bold=False)[0] > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur else lines


def draw_notes(pen, notes, y0=624, size=9, maxw=752):
    """Hook-up notes under the pictures; UNVERIFIED lines in amber-brown."""
    rows = [(line, unverified) for text, unverified in notes for line in wrap_text(pen, text, size, maxw)]
    y0 = min(y0, H - 6 - 13 * (len(rows) - 1))
    for i, (line, unverified) in enumerate(rows):
        pen.text(W / 2, y0 + 13 * i, line, size, '#b45309' if unverified else '#5a6475', bold=False)
    return len(rows)


def cal_panel(pen, cal, names, color, stand_by=False):
    """The calibrator drawing for the bench path: the 5560A from the front-panel photo (bench_cal) or the 5522A schematic.  A 5520A uses the 5522A picture."""
    if cal == '5560A':
        if stand_by:
            jacks = draw_5560a(pen, {}, False)
            pen.text(B.PX + 76 * K, B.PY + 276 * K + 18, 'Fluke 5560A: not used', 11, '#5a6475', bold=False)
            return jacks
        jacks = bench_cal(pen, names, color)
        if 'SEN_LO' in names and 'SEN_HI' not in names:          # 3-wire: the lone sense lead leaves between the OUTPUT sockets too, not through OUTPUT LO
            jacks['SEN_LO'] = (jacks['SEN_LO'][0], [P(69, 102), P(-9, 102)])
        return jacks
    jacks = draw_5522a(pen, {n: True for n in names})
    pen.text(B.PX + 76 * K, B.PY + 196 * K + 18, 'Fluke 5522A: not used' if stand_by else 'Fluke 5522A front panel (output terminals)', 11, '#5a6475', bold=False)
    if not stand_by:
        pen.text(B.PX + 76 * K, B.PY + 196 * K + 34, '(a 5520A uses this picture)', 9.5, '#5a6475', bold=False)
    return jacks


def hook_dmm6500(cal, group):
    kind, notes = D65_GROUPS[group]
    pen = Pen(W, H, '#ffffff')
    names = CAL_TERM[cal]
    leads = [(names[role], jack, c, w) for role, jack, c, w in D65_LEADS[kind]]
    rear = kind == 'I10'
    current = kind in ('I', 'I10')
    used = {j for _, j, _, _ in leads}
    if kind == 'SHORT':
        used = {'IN_HI', 'IN_LO', 'SE_HI', 'SE_LO'}
    draw_dmm6500(pen, used, rear=rear, shorted=kind == 'SHORT')
    jacks = cal_panel(pen, cal, tuple(dict.fromkeys(n for n, _, _, _ in leads)), 'blue' if current else 'green', stand_by=not leads)
    cables = [dict(name=a, jack=b, color=c, w=w) for a, b, c, w in leads]
    for c in cables:
        c['start'], c['exit'] = jacks[c['name']]
    if cables:
        routes = route_all(cables, lambda c: bench_candidates(c, D65_POS), lambda a, b: 14)
        for c, r in sorted(zip(cables, routes), key=lambda t: t[0]['w']):
            draw_cable(pen, r, c['color'], c['w'])
        if cal == '5560A' and current:                           # keep the terminal names readable on top of the cable
            for label, (ux, uy) in (('VI AUX', (22, 143)), ('30A', (70, 143))):
                tx, ty = P(ux, uy)
                w = pen.text_size(label, 4.6 * K)[0] + 8
                pen.rect(tx - w / 2, ty - 8, tx + w / 2, ty + 8, r=5, fill='#dcdcd6')
                pen.text(tx, ty, label, 4.6 * K, '#3a3a3a')
        if cal == '5522A':
            for label, (ux, uy) in (('20A', (86, 131)), ('GUARD', (34, 131))):
                tx, ty = P(ux, uy)
                w = pen.text_size(label, 4.6 * K)[0] + 8
                pen.rect(tx - w / 2, ty - 8, tx + w / 2, ty + 8, r=5, fill='#dcdcd6')
                pen.text(tx, ty, label, 4.4 * K, '#2f6fd0' if label == 'GUARD' else '#3a3a3a')
        for c, r in zip(cables, routes):
            jx, jy = D65_POS[c['jack']]
            pen.rect(jx + 14, jy - 8, jx + 46, jy + 8, r=4, fill=c['color'], outline='#ffffff', width=1.6)
            pen.circle(c['start'][0], c['start'][1], 6.4 * K, fill=c['color'], outline='#ffffff', width=1.8)
    notes = [n[:2] for n in notes if len(n) < 3 or cal in n[2]]
    if draw_notes(pen, notes) > 3:
        raise RuntimeError(f'{group}: more than three note lines')
    pen.save(OUT / f'hook_dmm6500_{cal}_{group}.png')


def main(only=()):
    made = 0
    if not only or 'fluke28x' in only:
        for cal in ('5560A', '5522A'):
            hook_ohm4('fluke28x', cal)
            made += 1
    if not only or 'bench' in only:
        for model in BENCH:
            for key in bench_keys(model):
                hook_bench(model, key)
                made += 1
    if not only or 'dmm6500' in only:
        for cal in ('5560A', '5522A'):
            for group in D65_GROUPS:
                hook_dmm6500(cal, group)
                made += 1
    print('wrote', made, 'diagrams to', OUT)


if __name__ == '__main__':
    main(tuple(sys.argv[1:]))
