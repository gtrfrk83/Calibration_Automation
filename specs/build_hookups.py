"""Draws the hook-up diagrams in diagrams/ (hook_<meter>_<calibrator>_<group>.png).

    python3 specs/build_hookups.py                 (needs Pillow; the procedures themselves do not)
    python3 specs/build_hookups.py fluke77         (only the named meter(s); the other diagrams are left byte for byte as they are)

Meters: Klein MM325, Fluke 110 series, Fluke 87V, Fluke 77 Series IV.   Calibrators: Fluke 5560A and Fluke 5522A.
The terminals each calibrator uses come from hookups.py, so the pictures and the prompts' text agree.

5560A: drawn from a photograph of the real front panel (OUTPUT V/ohm HI / LO, VI AUX, SENSE HI / LO, 30A, GUARD, ground, TC, SCOPE, TRIG).
       Terminals in use are shown lit, green for voltage and blue for current, as the instrument lights them.
5522A: a labelled schematic of its output terminals (the real panel layout is not drawn); in use = amber ring.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import hookups                                   # noqa: E402
from draw_kit import Pen, bezier, min_distance, smooth   # noqa: E402

OUT = HERE.parent / 'diagrams'
W, H = 780, 656
K = 1.9                       # scale of the calibrator panel (it is 152 x 276 units)
PX, PY = 470, 14              # where the calibrator panel starts
JACK_Y = 520                  # the meter's jack row
RED, BLACK, YELLOW = '#d11a2a', '#1b1b1b', '#e3b800'
GLOW = {'green': '#2fe27a', 'blue': '#3a9bff'}
AMBER = '#ffb300'


def P(x, y):
    """Calibrator panel units -> picture pixels."""
    return (PX + x * K, PY + y * K)


# ------------------------------------------------------------------------------------------------ calibrators
def socket(pen, cx, cy, color, arc=None, side='left', lit=None, ring=None, rs=1.0):
    r = 15.5 * K * rs
    if lit:
        pen.glow(cx, cy, r + 2.2 * K, GLOW[lit])
    if ring:
        pen.circle(cx, cy, r + 4.5 * K, outline=ring, width=3)
    if arc:
        a0, a1 = (125, 235) if side == 'left' else (-55, 55)
        pen.arc(cx, cy, r + 3.4 * K, a0, a1, arc, width=3.4 * K)
    pen.circle(cx, cy, r, fill='#f3f3f0', outline='#b7b7b1', width=1.2)
    pen.circle(cx, cy, r * 0.68, fill='#e3e3de', outline='#cbcbc5', width=1)
    pen.circle(cx, cy, 6.8 * K * rs, fill=color, outline='#4a4a4a', width=1)
    pen.circle(cx, cy, 2.7 * K * rs, fill='#0c0c0c')


def draw_5560a(pen, lit, with_plugs):
    """Faithful render of the 5560A front panel (from the supplied photograph). lit: {jack name: 'green'|'blue'}.
    Returns {jack name: (centre, [exit points toward the left edge])}."""
    x0, y0 = P(0, 0)
    pen.rect(x0, y0, x0 + 152 * K, y0 + 276 * K, r=7 * K, fill='#dcdcd6', outline='#8c8c86', width=2.5)
    ink, soft = '#3a3a3a', '#8a8a84'
    pen.text(*P(28, 10), 'OUTPUT', 5.4 * K, ink)
    pen.text(*P(28, 19), 'V/Ω', 5.4 * K, ink)
    pen.text(*P(76, 10), 'SENSE', 5.4 * K, ink)
    pen.text(*P(76, 19), 'V/Ω', 5.4 * K, ink)
    tx, ty = P(48, 17)
    pen.polygon([(tx, ty - 7 * K), (tx - 7 * K, ty + 6 * K), (tx + 7 * K, ty + 6 * K)], fill=AMBER, outline='#6b4a00')
    pen.text(tx, ty + 2 * K, '!', 5 * K, '#4a3000')
    ox, oy = P(122, 11)
    pen.rect(ox - 20 * K, oy - 6 * K, ox + 20 * K, oy + 6 * K, r=3 * K, fill='#b9f5c9', outline='#38c15a', width=1.5)
    pen.text(ox, oy, 'OPERATE', 5.2 * K, '#1c8f43')
    pen.text(*P(122, 26), 'STANDBY', 5.2 * K, ink)
    hx, hy = P(122, 46)
    pen.polygon([(hx, hy - 8 * K), (hx - 8 * K, hy + 7 * K), (hx + 8 * K, hy + 7 * K)], fill='#f2f2ee', outline='#222')
    pen.text(hx, hy + 2.5 * K, '⚡', 5 * K, '#222')
    pen.text(*P(47, 44), 'HI', 4.4 * K, soft)
    pen.text(*P(47, 83), 'LO', 4.4 * K, ink)
    pen.text(*P(47, 124), 'HI', 4.4 * K, soft)
    pen.text(*P(120, 61), 'GUARD', 4.6 * K, '#2f6fd0')
    jacks = {}
    spec = {'OUT_HI': (20, 46, '#b3262e', '#8d1b25', 'left'), 'OUT_LO': (19, 83, '#161616', '#1f3a2a', 'left'),
            'VI_AUX': (20, 121, '#b3262e', '#8d1b25', 'left'), 'SEN_HI': (69, 46, '#b3262e', '#d56a78', 'right'),
            'SEN_LO': (69, 83, '#161616', '#1b1b1b', 'right'), 'THIRTY': (69, 121, '#b3262e', '#c24a58', 'right'),
            'GUARD': (120, 84, '#2d6fd0', '#2d6fd0', 'right'), 'GND': (120, 121, '#24352c', '#2f9e63', 'right')}
    for name, (ux, uy, color, arc, side) in spec.items():
        cx, cy = P(ux, uy)
        socket(pen, cx, cy, color, arc, side, lit.get(name))
        exit_pts = [P(-9, uy)]
        if name == 'THIRTY':
            exit_pts = [P(69, 150), P(-9, 150)]
        jacks[name] = ((cx, cy), exit_pts)
    pen.text(*P(22, 143), 'VI AUX', 4.4 * K, ink)
    pen.text(*P(70, 143), '30A', 4.6 * K, ink)
    ex, ey = P(120, 141)                                    # earth symbol
    pen.line([(ex, ey - 4 * K), (ex, ey)], ink, 1.2, caps=False)
    for i, half in enumerate((5, 3.4, 1.8)):
        pen.line([(ex - half * K, ey + i * 2 * K), (ex + half * K, ey + i * 2 * K)], ink, 1.4, caps=False)
    # thermocouple connector
    a, b = P(18, 157), P(54, 246)
    pen.rect(a[0], a[1], b[0], b[1], r=3 * K, fill='#8d9094', outline='#6f7276', width=1.5)
    lab = P(36, 164)
    pen.rect(lab[0] - 11 * K, lab[1] - 5 * K, lab[0] + 11 * K, lab[1] + 5 * K, r=1.5 * K, fill='#f4f4f1')
    pen.text(lab[0], lab[1], 'TC', 5.4 * K, ink)
    for ux in (26, 47):
        pen.circle(*P(ux, 203), 5.2 * K, fill='#1d1d1d', outline='#555', width=1)
    pen.text(*P(26, 190), '−', 5 * K, '#333')
    pen.text(*P(47, 190), '+', 5 * K, '#333')
    for ux in (21, 41):
        c0, c1 = P(ux, 222), P(ux + 13, 244)
        pen.rect(c0[0], c0[1], c1[0], c1[1], r=1.5 * K, fill='#202020', outline='#444', width=1)
    if 'TC' in lit:
        c = P(36, 232)
        pen.glow(c[0], c[1], 21 * K, GLOW['green'])
    jacks['TC'] = (P(36, 233), [P(36, 256), P(-9, 256)])
    # SCOPE (N) and TRIG (BNC) connectors
    pen.text(*P(66, 169), 'SCOPE', 4.8 * K, ink)
    cx, cy = P(103, 169)
    pen.circle(cx, cy, 15 * K, fill='#c9c9c9', outline='#8e8e8e', width=1.5)
    pen.circle(cx, cy, 11 * K, fill='#dedede', outline='#9a9a9a', width=1)
    pen.circle(cx, cy, 7 * K, fill='#7a4a2a', outline='#4a2a14', width=1)
    pen.circle(cx, cy, 2.6 * K, fill='#c98a54')
    pen.text(*P(70, 227), 'TRIG', 4.8 * K, ink)
    cx, cy = P(103, 229)
    pen.circle(cx, cy, 12 * K, fill='#c9c9c9', outline='#8e8e8e', width=1.5)
    pen.circle(cx, cy, 8 * K, fill='#e6e6e6', outline='#9a9a9a', width=1)
    pen.circle(cx, cy, 3.2 * K, fill='#f7f7f7', outline='#9a9a9a', width=1)
    pen.text(*P(76, 262), 'FLUKE 5560A', 5 * K, soft)
    return jacks


def draw_5522a(pen, lit):
    """The 5522A output-terminal block, laid out as on the real front panel (from a photograph): NORMAL column (HI, LO, GUARD),
    AUX column (HI, LO, 20A), SCOPE OUT and TRIG connectors, TC connector below. lit: {jack name: True} -> amber ring."""
    x0, y0 = P(0, 0)
    pen.rect(x0, y0, x0 + 152 * K, y0 + 196 * K, r=7 * K, fill='#dcdcd6', outline='#8c8c86', width=2.5)
    ink = '#3a3a3a'
    pen.text(*P(34, 6), 'NORMAL', 5.4 * K, ink)
    pen.text(*P(34, 12.5), 'V, \u03a9, \u2193, RTD', 3.6 * K, ink, bold=False)
    pen.text(*P(86, 6), 'AUX', 5.4 * K, ink)
    pen.text(*P(86, 12.5), 'A, \u03a9-SENSE, AUX V', 3.4 * K, ink, bold=False)
    pen.text(*P(128, 12), 'SCOPE', 4.8 * K, ink)
    pen.text(*P(128, 20), 'OUT', 4.8 * K, ink)
    tx, ty = P(9, 10)
    pen.polygon([(tx, ty - 6 * K), (tx - 6 * K, ty + 5 * K), (tx + 6 * K, ty + 5 * K)], fill='#f2f2ee', outline='#222')
    pen.text(*P(60, 38), 'HI', 4.4 * K, '#b3262e')
    pen.text(*P(60, 76), 'LO', 4.4 * K, ink)
    pen.text(*P(34, 131), 'GUARD', 4.4 * K, '#2f6fd0')
    pen.text(*P(86, 131), '20A', 4.6 * K, ink)
    spec = {'NORMAL_HI': (34, 38, '#b3262e', '#b3262e', 'left', [P(86, 38)][:0] + [P(-9, 38)]),
            'NORMAL_LO': (34, 76, '#161616', '#1f1f1f', 'left', [P(-9, 76)]),
            'GUARD': (34, 114, '#2d6fd0', '#2d6fd0', 'left', [P(-9, 114)]),
            'AUX_HI': (86, 38, '#b3262e', '#b3262e', 'right', [P(86, 20), P(-9, 20)]),
            'AUX_LO': (86, 76, '#161616', '#1f1f1f', 'right', [P(86, 57), P(-9, 57)]),
            'TWENTY': (86, 114, '#b3262e', '#b3262e', 'right', [P(86, 95), P(-9, 95)])}
    jacks = {}
    for name, (ux, uy, color, arc, side, exits) in spec.items():
        cx, cy = P(ux, uy)
        socket(pen, cx, cy, color, arc, side, None, AMBER if lit.get(name) else None, rs=0.82)
        jacks[name] = ((cx, cy), exits)
    for cy_u, r_u in ((50, 14), (104, 11)):                    # SCOPE OUT (BNC) and TRIG (BNC)
        cx, cy = P(128, cy_u)
        pen.circle(cx, cy, r_u * K, fill='#c9c9c9', outline='#8e8e8e', width=1.5)
        pen.circle(cx, cy, (r_u - 3.5) * K, fill='#e6e6e6', outline='#9a9a9a', width=1)
        pen.circle(cx, cy, 3.2 * K, fill='#f7f7f7', outline='#9a9a9a', width=1)
    pen.text(*P(128, 83), 'TRIG', 4.6 * K, ink)
    a, b = P(50, 160), P(106, 178)
    pen.rect(a[0], a[1], b[0], b[1], r=2 * K, fill='#f4f4f1', outline='#555', width=1.5)
    pen.text(*P(61, 169), '\u2212 \u25a4', 4.2 * K, ink)
    pen.text(*P(94, 169), '\u25a4 +', 4.2 * K, ink)
    pen.text(*P(78, 188), 'TC', 4.8 * K, ink)
    if lit.get('TC'):
        pen.circle(*P(78, 169), 30 * K, outline=AMBER, width=3)
    jacks['TC'] = (P(78, 169), [P(78, 190), P(-9, 190)])
    pen.text(*P(120, 190), 'FLUKE 5522A', 4.2 * K, '#8a8a84')
    return jacks


# ------------------------------------------------------------------------------------------------ meters
METER_DRAW = {
    'mm325': dict(brand='KLEIN TOOLS', model='MM325', body='#4a4f57', edge='#e8761d', face='#363a41', ink='#ffffff', accent='#f1b24a',
                  jacks=[('a10', '10A', 110), ('com', 'COM', 185), ('vohm', 'VΩ µA mA', 260)], alias={'ma': 'vohm'}),
    'fluke110': dict(brand='FLUKE', model='110 series', body='#f3c40f', edge='#8a6d00', face='#2b2e33', ink='#ffffff', accent='#f3c40f',
                     jacks=[('a10', 'A', 110), ('com', 'COM', 185), ('vohm', 'VΩ', 260)], alias={'ma': 'vohm'}),
    'fluke87v': dict(brand='FLUKE', model='87V', body='#f3c40f', edge='#8a6d00', face='#2b2e33', ink='#ffffff', accent='#f3c40f',
                     jacks=[('a10', '10A', 96), ('ma', 'mA µA', 152), ('com', 'COM', 208), ('vohm', 'VΩ', 264)], alias={}),
    # the jack order is drawn like the 87V's; the 77 IV manual names the jacks (pp. 7, 12) but does not show their order on the case
    'fluke77': dict(brand='FLUKE', model='77 Series IV', body='#f3c40f', edge='#8a6d00', face='#2b2e33', ink='#ffffff', accent='#f3c40f',
                    jacks=[('a10', '10A', 96), ('ma', '400 mA', 152), ('com', 'COM', 208), ('vohm', 'VΩ', 264)], alias={}),
}


def draw_meter(pen, kind):
    m = METER_DRAW[kind]
    pen.rect(60, 20, 310, 612, r=36, fill=m['body'], outline=m['edge'], width=5)
    pen.rect(76, 36, 294, 596, r=26, fill=m['face'])
    pen.text(185, 62, m['brand'], 14, m['accent'])
    pen.text(185, 82, m['model'], 11, m['ink'], bold=False)
    pen.rect(98, 102, 272, 170, r=6, fill='#c9d3bf', outline='#16181b', width=2)
    pen.text(185, 136, '8.8.8.8', 34, '#8e9a84', mono=True)
    for i in range(4):
        pen.rect(100 + i * 44, 186, 134 + i * 44, 204, r=5, fill=m['accent'] if kind != 'mm325' else '#6b717b')
    pen.circle(185, 320, 90, fill='#1d2025', outline='#6e7684', width=3)
    pen.circle(185, 320, 62, fill='#101215', outline='#3d424b', width=2)
    pen.polygon([(185, 262), (176, 286), (194, 286)], fill='#ffffff')
    jacks = {}
    for key, label, x in m['jacks']:
        jacks[key] = x
    for alias, target in m['alias'].items():
        jacks[alias] = jacks[target]
    return jacks


def draw_jack(pen, x, used):
    if used:
        pen.circle(x, JACK_Y, 25, outline=AMBER, width=4)
    pen.circle(x, JACK_Y, 16, fill='#0d0e10', outline='#8b919b' if used else '#5c626c', width=3)
    pen.circle(x, JACK_Y, 6, fill='#333840')


def draw_labels(pen, kind, used_x, above=False):
    for key, label, x in METER_DRAW[kind]['jacks']:
        size = 10 if len(label) > 5 else 12
        w = pen.text_size(label, size)[0] + 12
        y = JACK_Y - 36 if above else 584
        pen.rect(x - w / 2, y - 11, x + w / 2, y + 11, r=8, fill=METER_DRAW[kind]['face'])
        pen.text(x, y, label, size, '#ffffff' if x in used_x else '#8d939d')


def plug(pen, x, color, above):
    y0, y1 = (JACK_Y - 46, JACK_Y - 14) if above else (JACK_Y + 14, JACK_Y + 46)
    pen.rect(x - 8, y0, x + 8, y1, r=4, fill=color, outline='#ffffff', width=1.6)


# ------------------------------------------------------------------------------------------------ cable routing
def candidates(start, exit_pts, end_x, mode):
    """Square-cornered cable routes from a panel terminal to a meter jack: out of the panel's left edge, down a vertical lane,
    then in to the jack from above ('above') or from below ('under')."""
    ex, ey = exit_pts[-1]
    lanes = (392, 410, 428, 446) if ex > 450 else (ex - 60, ex - 40, ex - 20)
    out = []
    for vx in lanes:
        if vx >= ex:
            continue
        if mode == 'above':
            for ty in (412, 438, 464):
                out.append([start, *exit_pts, (vx, ey), (vx, ty), (end_x, ty), (end_x, JACK_Y - 46)])
        else:
            for ty in (630, 644):
                out.append([start, *exit_pts, (vx, ey), (vx, ty), (end_x, ty), (end_x, JACK_Y + 46)])
    return out


def choose_routes(cable_a, cable_b):
    """cable = (start, exit_pts, end_x). Best pair of non-touching routes: both from above if possible."""
    best = None
    for ma, mb in itertools.product(('above', 'under'), repeat=2):
        for ra in candidates(*cable_a, ma):
            for rb in candidates(*cable_b, mb):
                if min_distance(ra, rb) < 15:
                    continue
                score = (ma == 'under') + (mb == 'under')
                length = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for r in (ra, rb) for p, q in zip(r, r[1:]))
                key = (score, length)
                if best is None or key < best[0]:
                    best = (key, ra, rb, ma, mb)
    if best is None:
        raise RuntimeError('no non-touching cable routes found')
    return best[1:]


def draw_cable(pen, pts, color, width=7):
    pts = smooth(pts, 4)
    pen.line(pts, '#ffffff', width + 4)
    pen.line(pts, color, width)


# ------------------------------------------------------------------------------------------------ one diagram
def hook(meter, cal, group):
    pen = Pen(W, H, '#ffffff')
    hi_t, lo_t, color = hookups.CAL_TERMS[cal][group]
    if cal == '5560A':
        names = {'VOHM': ('OUT_HI', 'OUT_LO'), 'UAMP': ('VI_AUX', 'OUT_LO'), 'AMP10': ('THIRTY', 'OUT_LO'),
                 'VOLTALERT': ('OUT_HI', 'OUT_LO'), 'TEMP': ('TC', 'TC')}[group]
        lit = {n: color for n in names if group != 'TEMP'}
        if group == 'TEMP':
            lit = {'TC': 'green'}
        jacks = draw_5560a(pen, lit, group == 'VOLTALERT')
    else:
        names = {'VOHM': ('NORMAL_HI', 'NORMAL_LO'), 'UAMP': ('AUX_HI', 'AUX_LO'), 'AMP10': ('TWENTY', 'AUX_LO'),
                 'VOLTALERT': ('NORMAL_HI', 'NORMAL_LO'), 'TEMP': ('TC', 'TC')}[group]
        jacks = draw_5522a(pen, {n: True for n in names})
    mjacks = draw_meter(pen, meter)
    caption = {'5560A': 'Fluke 5560A front panel', '5522A': 'Fluke 5522A front panel (output terminals)'}[cal]
    pen.text(PX + 76 * K, PY + (276 if cal == '5560A' else 196) * K + 18, caption, 11, '#5a6475', bold=False)

    if group == 'TEMP':
        a_x = mjacks['vohm'] + 30
        box_l, box_r = mjacks['com'] - 32, mjacks['vohm'] + 32
        for x, c in ((mjacks['vohm'], RED), (mjacks['com'], BLACK)):
            pen.rect(x - 6, JACK_Y + 12, x + 6, JACK_Y + 44, r=3, fill=c, outline='#ffffff', width=1.4)
        pen.rect(box_l, JACK_Y + 40, box_r, JACK_Y + 92, r=8, fill='#d9dde3', outline='#6b7280', width=2)
        pen.text((box_l + box_r) / 2, JACK_Y + 60, 'Fluke 80AK', 10.5, '#1f2a44')
        pen.text((box_l + box_r) / 2, JACK_Y + 77, 'adapter', 10, '#1f2a44', bold=False)
        start, exit_pts = jacks['TC']
        pts = [start, *exit_pts[:1], (exit_pts[0][0], JACK_Y + 66), (box_r, JACK_Y + 66)]
        draw_cable(pen, pts, YELLOW, 6)
        pen.rect(box_r - 4, JACK_Y + 60, box_r + 10, JACK_Y + 72, r=3, fill='#222', outline='#ffffff', width=1.2)
        for x in (mjacks['vohm'], mjacks['com']):
            draw_jack(pen, x, True)
        used = {mjacks['vohm'], mjacks['com']}
        draw_labels(pen, meter, used, above=True)
        pen.save(OUT / f'hook_{meter}_{cal}_{group}.png')
        return

    if group == 'VOLTALERT':
        (hx, hy), _ = jacks[names[0]]
        (lx, ly), _ = jacks[names[1]]
        pen.rect(hx - 9, hy - 10, hx + 9, ly + 10, r=7, fill='#2a2a2a', outline='#ffffff', width=2)
        pen.circle(hx, hy, 5, fill=RED)
        pen.circle(lx, ly, 5, fill='#555555')
        pen.rect(130, 24, 240, 42, r=7, fill=AMBER)
        pen.text(185, 33, 'VoltAlert tip', 9.5, '#3a2a00')
        a, b = (240, 33), (hx - 14, hy)
        pen.dashed(a, (440, 33), AMBER, 3)
        pen.dashed((440, 33), (440, hy), AMBER, 3)
        pen.dashed((440, hy), b, AMBER, 3)
        pen.polygon([(b[0] + 2, b[1]), (b[0] - 10, b[1] - 6), (b[0] - 10, b[1] + 6)], fill=AMBER)
        pen.text(335, 16, 'hold the meter tip against the plug', 10, '#7a5a00')
        for key, label, x in METER_DRAW[meter]['jacks']:
            draw_jack(pen, x, False)
        draw_labels(pen, meter, set())
        pen.save(OUT / f'hook_{meter}_{cal}_{group}.png')
        return

    red_key = {'VOHM': 'vohm', 'UAMP': 'ma', 'AMP10': 'a10'}[group]
    red_x, black_x = mjacks[red_key], mjacks['com']
    red_start, red_exit = jacks[names[0]]
    black_start, black_exit = jacks[names[1]]
    r_route, b_route, r_mode, b_mode = choose_routes((red_start, red_exit, red_x), (black_start, black_exit, black_x))
    used = {red_x, black_x}
    for key, label, x in METER_DRAW[meter]['jacks']:
        draw_jack(pen, x, x in used)
    draw_cable(pen, b_route, BLACK)
    draw_cable(pen, r_route, RED)
    plug(pen, red_x, RED, r_mode == 'above')
    plug(pen, black_x, BLACK, b_mode == 'above')
    for (cx, cy), c in ((red_start, RED), (black_start, BLACK)):
        pen.circle(cx, cy, 6.4 * K, fill=c, outline='#ffffff', width=1.8)
    draw_labels(pen, meter, used)
    if cal == '5522A':
        for label, (ux, uy) in (('20A', (86, 131)), ('GUARD', (34, 131))):
            tx, ty = P(ux, uy)
            w = pen.text_size(label, 4.6 * K)[0] + 8
            pen.rect(tx - w / 2, ty - 8, tx + w / 2, ty + 8, r=5, fill='#dcdcd6')
            pen.text(tx, ty, label, 4.4 * K, '#2f6fd0' if label == 'GUARD' else '#3a3a3a')
    if cal == '5560A':                                       # keep the terminal names readable on top of the cables
        for label, (ux, uy) in (('VI AUX', (22, 143)), ('30A', (70, 143))):
            if label in (hi_t,) or group in ('UAMP', 'AMP10'):
                tx, ty = P(ux, uy)
                w = pen.text_size(label, 4.6 * K)[0] + 8
                pen.rect(tx - w / 2, ty - 8, tx + w / 2, ty + 8, r=5, fill='#dcdcd6')
                pen.text(tx, ty, label, 4.6 * K, '#3a3a3a')
    pen.save(OUT / f'hook_{meter}_{cal}_{group}.png')


def main(only=()):
    made = 0
    for meter, groups in hookups.AVAILABLE.items():
        if only and meter not in only:
            continue
        for cal in hookups.CAL_TERMS:
            for group in groups:
                hook(meter, cal, group)
                made += 1
    print('wrote', made, 'diagrams to', OUT)


if __name__ == '__main__':
    main(tuple(sys.argv[1:]))
