"""More hook-up diagrams, drawn in the same style as specs/build_hookups.py:

    python3 specs/build_hookups_ext.py             (needs Pillow; the procedures themselves do not)

  * Fluke 287 / 289, four-wire ohms (group OHM4):     hook_fluke28x_<5560A|5522A>_OHM4.png
  * bench DMMs, Fluke 5560A to the meter's front jacks: hook_<model>_5560A_<KEY>.png   models 34401A 34460A 34461A 34465A 8846A
        KEY: VOLT  RES2  RES4  SHORT  OPEN  I_<jack>  (I_I, I_3A, I_10A, I_400MA)

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
from draw_kit import Pen, min_distance                      # noqa: E402


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


def main():
    made = 0
    for cal in ('5560A', '5522A'):
        hook_ohm4('fluke28x', cal)
        made += 1
    for model in BENCH:
        for key in bench_keys(model):
            hook_bench(model, key)
            made += 1
    print('wrote', made, 'diagrams to', OUT)


if __name__ == '__main__':
    main()
