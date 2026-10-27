"""Hook-up diagrams of the Fluke 753 / 754 procedure:   python3 specs/build_hookups_753.py      (needs Pillow; the procedures do not)

Writes diagrams/hook_fluke753_<GROUP>.png (one per group of specs/fluke_753_754_pv.json).  They are drawn ONLY from
  * the owner's terminal photo diagrams/fluke_753_754_terminals.png (the jack positions), and
  * the Calibration Manual's own figures (which jack each lead uses): Figures 1-13 and 15, printed pp. 11-31 (PDF pp. 19-40).
Nothing else is invented.  The lead colours are the figures' (red = high side, black = low / common); the instrument at the other end is named by its terminal, no picture of it is drawn.
The calibrator terminals are those of hookups.CAL_TERMS (5522A / 5560A; the 5520A uses the 5522A's).

WHERE THE JACKS COME FROM  (both agree, see the final report):
    photo  : top row  VΩ RTD (SOURCE side, left) | mA / mA Ω RTD (middle) | V (MEASURE side, right);  bottom row: three commons (30 V MAX, 50 V MAX, CAT II 300 V MAX); TC mini-jack lower left.
    PDF    : the same labels, drawn in every figure; the leads of each figure give the assignment below.
    UNVERIFIED  Figure 3 / 11 / 12 (the black leads) and Figure 7 (the lead colours at the middle jacks) are small and cross the jack shields: read from the 300 dpi page images; confirm on the bench.
"""
from __future__ import annotations

from pathlib import Path

import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PHOTO = ROOT / 'diagrams' / 'fluke_753_754_terminals.png'
OUT = ROOT / 'diagrams'
S = 3                                            # photo scale
JACK = {'tl': (118, 50), 'tm': (180, 50), 'tr': (240, 50), 'bl': (118, 94), 'bm': (180, 94), 'br': (240, 94), 'tc': (60, 93)}   # centres in the photo (293 x 136 px)
NAME = {'tl': 'V Ω RTD (SOURCE)', 'tm': 'mA / mA Ω RTD', 'tr': 'V (MEASURE)', 'bl': 'COM (SOURCE, 30 V MAX)', 'bm': 'COM (50 V MAX)', 'br': 'COM (MEASURE, CAT II 300 V)', 'tc': 'TC + / −'}
RED, BLACK, BLUE, GREY = (200, 20, 25), (25, 25, 25), (20, 90, 200), (110, 110, 110)
FONT = '/usr/share/fonts/truetype/dejavu/'

# the calibrator terminals (hookups.CAL_TERMS), as the two-line text of a box
CAL = {
    'V': ('CAL HI', '5522A NORMAL HI  |  5560A OUTPUT V/Ω HI'), 'V0': ('CAL LO', '5522A NORMAL LO  |  5560A OUTPUT V/Ω LO'),
    'I': ('CAL HI', '5522A AUX HI  |  5560A VI AUX'), 'I0': ('CAL LO', '5522A AUX LO  |  5560A OUTPUT LO'),
    'S': ('CAL SENSE HI', '5522A AUX SENSE HI  |  5560A SENSE HI'), 'S0': ('CAL SENSE LO', '5522A AUX SENSE LO  |  5560A SENSE LO'),
    'TC': ('CAL TC', '5522A / 5560A TC output (Type K wire, polarity as marked)'),
}


def meter(text):
    return ('EXTERNAL DMM', text)


# group -> (title, figure, leads [(jack, colour, (line1, line2))], jumpers [(jackA, jackB)], note)
GROUPS = {
    'MEAS_V': ('UUT measures dc / ac volts and frequency', 'Figures 1 and 4, printed pp. 11 and 16',
               [('tr', RED, CAL['V']), ('br', BLACK, CAL['V0'])], [], 'Calibrator output to the MEASURE side V jack and its common.'),
    'MEAS_MA': ('UUT measures dc mA', 'Figure 2, printed p. 13',
                [('tm', BLACK, ('3458A in series', 'UUT mA jack <- 3458A LO;  3458A I <- CAL HI (5522A AUX HI | 5560A VI AUX)')), ('bm', BLACK, CAL['I0'])], [], 'Calibrator current through the 3458A (in place of the manual 8508A) into the mA jack. 3458A terminals UNVERIFIED.'),
    'MEAS_OHM': ('UUT measures resistance', 'Figure 3, printed p. 15',
                 [('tm', RED, CAL['V']), ('tm', RED, CAL['S']), ('bm', BLACK, CAL['V0']), ('bm', BLACK, CAL['S0'])], [], 'Four-wire at the calibrator, two-wire at the UUT: both HI leads on the mA Ω RTD jack, both LO leads on the common below it; calibrator 2-wire compensation ON.'),
    'MEAS_TC': ('UUT measures a Type K thermocouple', 'Figure 10, printed p. 24 (the manual uses dc mV through a lag bath)',
                [('tc', GREY, CAL['TC'])], [], 'Type K thermocouple wire from the calibrator TC output to the UUT TC mini-jack (+ / − as marked).'),
    'MEAS_RTD4': ('UUT measures a four-wire RTD (Pt100, 385)', 'Figure 11, printed p. 27',
                  [('tm', RED, CAL['V']), ('tr', RED, CAL['S']), ('bm', BLACK, CAL['V0']), ('br', BLACK, CAL['S0'])], [], 'Four-wire connection; calibrator four-wire compensation ON. Which black lead goes to which common: UNVERIFIED.'),
    'MEAS_RTD3': ('UUT measures a three-wire RTD (Pt100, 385)', 'Figure 12, printed p. 28',
                  [('tm', RED, CAL['V']), ('tr', BLACK, ('3-WIRE LEAD 2', 'the lead drawn black on the V jack in Figure 12: UNVERIFIED')), ('br', BLACK, CAL['V0'])], [('bm', 'br')], 'Three-wire connection with a jumper between the two commons; compensation OFF. Lead positions: UNVERIFIED.'),
    'SRC_V': ('UUT sources dc volts', 'Figure 5, printed p. 17',
              [('tl', RED, meter('INPUT HI (dc volts)')), ('bl', BLACK, meter('INPUT LO'))], [], 'The SOURCE side V Ω RTD jack and its common to the external DMM.'),
    'SRC_MA': ('UUT sources dc mA', 'Figure 6, printed p. 18',
               [('tm', RED, meter('mA / A input (dc current)')), ('bm', BLACK, meter('LO / current return'))], [], 'The middle mA jack and the common below it to the external DMM current input.'),
    'SRC_SIM': ('UUT simulates a transmitter', 'Figure 7, printed p. 19',
                [('tm', BLACK, ('LOOP / DMM', 'external DMM (dc current) in series with the calibrator 8 V dc')), ('bm', BLACK, ('LOOP / DMM', 'loop return (calibrator)'))], [], 'The calibrator supplies about 8 V dc; polarity as the figure. The figure draws both leads dark: the polarity is UNVERIFIED.'),
    'SRC_OHM': ('UUT sources resistance / RTD', 'Figure 8, printed p. 20',
                [('tl', RED, meter('INPUT HI')), ('tl', RED, meter('SENSE HI')), ('bl', BLACK, meter('INPUT LO')), ('bl', BLACK, meter('SENSE LO'))], [], 'Four-wire at the DMM, two-wire at the UUT: two leads on each SOURCE jack; DMM in four-wire ohms.'),
    'SRC_FREQ': ('UUT sources frequency', 'Figure 9, printed p. 22',
                 [('tl', RED, ('BNC adapter', 'counter (Tektronix FCA3000) and Fluke 123 channel A')), ('bl', BLACK, ('BNC adapter', 'shield / low'))], [], 'The SOURCE jacks through a BNC adapter to the counter; the Fluke 123 shows the waveform.'),
    'SRC_TC': ('UUT sources a Type K thermocouple', 'Figure 10, printed p. 24 (DMM in place of the 5522A)',
               [('tc', GREY, ('LAG BATH', 'Type K to copper junctions, then the external DMM mV input'))], [], 'Type K wire from the UUT TC mini-jack to the lag bath, copper to the DMM.'),
    'LOOP': ('Loop power', 'Figure 13, printed p. 30',
             [('tm', RED, meter('INPUT HI (dc volts)')), ('bm', BLACK, meter('INPUT LO'))], [], 'The mA jack and the common below it to the external DMM (dc volts).'),
    'HART': ('HART mode (754 only)', 'Figure 15, printed p. 32',
             [('tm', RED, ('HART transmitter', '+ / loop supply')), ('bm', BLACK, ('HART transmitter', '− / return'))], [], 'The mA jack and common to the HART transmitter (Rosemount 1151 / 3051 or any HART device).'),
}


HERE_ = HERE
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from draw_kit import Pen, smooth, min_distance        # noqa: E402
import itertools                                       # noqa: E402
import build_hookups as bh                             # noqa: E402  (the 5560A / 5522A panel drawers of the handheld pictures)
import hookups                                         # noqa: E402

W, H = 780, 730
YEL, FACE, EDGE = '#f3c40f', '#2b2e33', '#8a6d00'
CABLE = {RED: '#d11a2a', BLACK: '#1b1b1b', GREY: '#e3b800'}
AMBER = '#ffb300'
# jacks drawn like the owner's photo: top row V Ohm RTD | mA, mA Ohm RTD | V (red surrounds), bottom row the three commons, TC mini-jack lower left
DRAW = {'tl': (125, 448), 'tm': (195, 448), 'tr': (265, 448), 'bl': (125, 512), 'bm': (195, 512), 'br': (265, 512), 'tc': (72, 512)}
LABEL = {'tl': 'V Ω RTD', 'tm': 'mA / mA Ω RTD', 'tr': 'V', 'bl': 'COM 30 V', 'bm': 'COM 50 V', 'br': 'COM CAT II 300 V'}
TOP_LANES, BOTTOM_LANES = (336, 386), (620, 580)     # a lead from further left takes the lane further out, so no two cables cross
DEV_X = 470


def wrap(pen, text, size, width):
    lines = []
    for part in text.split('|'):
        cur = ''
        for word in part.strip().split():
            if cur and pen.text_size(cur + ' ' + word, size, False)[0] > width:
                lines.append(cur)
                cur = word
            else:
                cur = (cur + ' ' + word).strip()
        if cur:
            lines.append(cur)
    return lines


def draw_753(pen, used, jumpers):
    pen.rect(40, 62, 330, 566, r=34, fill=YEL, outline=EDGE, width=5)
    pen.rect(54, 76, 316, 552, r=24, fill=FACE)
    pen.text(185, 96, 'FLUKE', 13, YEL)
    pen.text(185, 114, '753 / 754  Documenting Process Calibrator', 8.5, '#ffffff', bold=False)
    pen.rect(72, 128, 298, 252, r=6, fill='#c9d3bf', outline='#16181b', width=2)
    pen.text(185, 190, '753 / 754', 22, '#8e9a84')
    for i in range(4):                                                  # soft keys
        pen.rect(78 + i * 55, 260, 124 + i * 55, 276, r=4, fill='#4a4f57')
    for r in range(3):                                                  # key block
        for c in range(6):
            pen.rect(76 + c * 37, 292 + r * 22, 106 + c * 37, 308 + r * 22, r=4, fill='#3a3f47' if (r + c) % 3 else '#555b66')
    pen.rect(58, 418, 312, 548, r=14, fill='#d99a0b', outline='#6b4f00', width=2)          # the terminal panel (the owner's photo: orange-yellow plate)
    for key, (x, y) in DRAW.items():
        if key == 'tc':
            pen.rect(x - 22, y - 9, x + 22, y + 9, r=6, fill='#0d0e10', outline='#8b919b' if key in used else '#5c626c', width=2.4)
            pen.rect(x - 12, y - 3, x + 12, y + 3, r=2, fill='#333840')
            if key in used:
                pen.rect(x - 28, y - 15, x + 28, y + 15, r=9, outline=AMBER, width=3.2)
            continue
        ring = '#b3121c' if key[0] == 't' else '#1b1b1b'
        if key in used:
            pen.circle(x, y, 25, outline=AMBER, width=3.6)
        pen.circle(x, y, 17, fill=ring, outline='#ffffff', width=1.6)
        pen.circle(x, y, 11, fill='#0d0e10', outline='#8b919b' if key in used else '#5c626c', width=2.4)
        pen.circle(x, y, 4, fill='#333840')


def draw_labels(pen, used):
    for key, text in LABEL.items():
        x, y = DRAW[key]
        y = y + 26 if key[0] == 't' else y - 26
        size = 7.6 if len(text) > 8 else 8.4
        pen.text(x, y, text, size, '#1b1b1b' if key in used else '#4a3300', bold=key in used)
    pen.text(160, 430, 'SOURCE', 8, '#4a3300')
    pen.text(230, 430, 'MEASURE', 8, '#4a3300')
    x, y = DRAW['tc']
    pen.text(x, y - 22, 'TC', 8.4, '#1b1b1b' if 'tc' in used else '#4a3300')


def cable(pen, pts, color, width=7):
    pts = smooth(pts, 4)
    pen.line(pts, '#ffffff', width + 4)
    pen.line(pts, color, width)


def draw(group):
    title, figure, leads, jumpers, note = GROUPS[group]
    pen = Pen(W, H, '#ffffff')
    pen.text(24, 20, f'Fluke 753 / 754 - {title}', 15, '#000000', anchor='lm')
    pen.text(24, 40, figure, 10, '#3c3c3c', bold=False, anchor='lm')
    used = {j for j, _c, _t in leads} | {a for a, b in jumpers} | {b for a, b in jumpers}
    draw_753(pen, used, jumpers)
    # one plug per lead; leads on the same jack sit side by side
    per = {}
    for lead in leads:
        per.setdefault(lead[0], []).append(lead)
    plugs = []
    for jack, items in per.items():
        for n, lead in enumerate(items):
            x = DRAW[jack][0] + (n - (len(items) - 1) / 2) * 20
            plugs.append((x, jack, lead))
    plugs.sort(key=lambda t: t[0])
    top = [p for p in plugs if p[1][0] == 't' and p[1] != 'tc']
    bottom = [p for p in plugs if p[1][0] == 'b' or p[1] == 'tc']
    placed = []
    for lanes, group_, down in ((TOP_LANES, top, False), (BOTTOM_LANES, bottom, True)):
        ys = list(lanes[:len(group_)])
        ys = sorted(ys) if not down else sorted(ys, reverse=True)
        for (x, jack, lead), lane in zip(group_, ys):
            placed.append((x, jack, lead, lane, down))
    dev_lo = min(l for *_a, l, _d in placed) - 52
    dev_hi = max(l for *_a, l, _d in placed) + 34
    kind = DEVICE.get(group, ('OTHER END', '#3d4f66'))
    pen.rect(DEV_X, dev_lo, W - 14, dev_hi, r=14, fill=kind[1], outline='#16181b', width=3)
    pen.text(DEV_X + 18, dev_lo + 20, kind[0], 12.5, '#ffffff', anchor='lm')
    titles = {l[2][0] for l in leads}
    for x, jack, (j, colour, (l1, l2)), lane, down in placed:
        jy = DRAW[jack][1]
        c = CABLE[colour]
        y_end = jy + (34 if down else -34)
        if jack == 'tc':
            y_end = jy + 34
        cable(pen, [(DEV_X + 24, lane), (x, lane), (x, y_end)], c)
        y0, y1 = (jy + 10, jy + 34) if (down or jack == 'tc') else (jy - 34, jy - 10)
        pen.rect(x - 7, y0, x + 7, y1, r=4, fill=c, outline='#ffffff', width=1.5)
        pen.circle(DEV_X + 24, lane, 10, fill='#0d0e10', outline='#8b919b', width=2.2)
        pen.circle(DEV_X + 24, lane, 6.4, fill=c, outline='#ffffff', width=1.6)
        if l1 != kind[0]:
            pen.text(DEV_X + 44, lane - 9, l1, 10.5, '#ffffff', anchor='lm')
        else:
            pen.text(DEV_X + 44, lane - 9, {'EXTERNAL DMM': 'DMM input'}.get(l1, l1), 10.5, '#ffffff', anchor='lm')
        for i, line in enumerate(wrap(pen, l2, 8.6, W - 14 - (DEV_X + 44) - 8)[:3]):
            pen.text(DEV_X + 44, lane + 5 + i * 11, line, 8.6, '#dfe6ee', bold=False, anchor='lm')
    for a, b in jumpers:                                                # a jumper plug between two jacks, drawn under them
        (ax, ay), (bx, by) = DRAW[a], DRAW[b]
        bx -= 10 * len(per.get(b, ())) if per.get(b) else 0
        cable(pen, [(ax, ay + 12), (ax, ay + 26), (bx, ay + 26), (bx, ay + 12)], BLACK, 6)
    draw_labels(pen, used)
    for n, line in enumerate(wrap(pen, note, 9.5, W - 48)[:3]):
        pen.text(24, H - 58 + n * 14, line, 9.5, '#000000', bold=False, anchor='lm')
    pen.text(24, H - 14, 'Jacks drawn from the supplied photo; leads from the Calibration Manual figure named above (red = high, black = low / common).', 8, '#5a6475', bold=False, anchor='lm')
    path = OUT / f'hook_fluke753_{group}.png'
    pen.save(path)
    return path



# ------------------------------------------------------------------------------------------------ per-calibrator pictures
# diagrams/hook_fluke753_<5560A|5522A>_<GROUP>.png for the groups a calibrator drives; the engine picks the file of the chosen calibrator
CAL_GROUPS = ('MEAS_V', 'MEAS_MA', 'MEAS_OHM', 'MEAS_TC', 'MEAS_RTD4', 'MEAS_RTD3')
KEY_OF = {id(v): k for k, v in CAL.items()}
JACKNAME = {'5560A': {'V': 'OUT_HI', 'V0': 'OUT_LO', 'I': 'VI_AUX', 'I0': 'OUT_LO', 'S': 'SEN_HI', 'S0': 'SEN_LO', 'TC': 'TC'},
            '5522A': {'V': 'NORMAL_HI', 'V0': 'NORMAL_LO', 'I': 'AUX_HI', 'I0': 'AUX_LO', 'S': 'AUX_HI', 'S0': 'AUX_LO', 'TC': 'TC'}}
VXS = (440, 418, 396, 374, 352)


def route_all(cables):
    """cables: [(start, exit_pts, meter_x, y_end, down)] -> routes that do not touch (searched over the vertical lanes and the horizontal lane order)."""
    n = len(cables)
    tops = [i for i, c in enumerate(cables) if not c[4]]
    bots = [i for i, c in enumerate(cables) if c[4]]
    best = None
    for vxs in itertools.permutations(VXS, n):
        for tl in itertools.permutations(TOP_LANES[:max(len(tops), 1)] if len(tops) <= 2 else TOP_LANES, len(tops)):
            for bl in itertools.permutations(BOTTOM_LANES if len(bots) else (), len(bots)):
                lane = {}
                for i, y in zip(tops, tl):
                    lane[i] = y
                for i, y in zip(bots, bl):
                    lane[i] = y
                routes = []
                for i, (start, exit_pts, mx, y_end, down) in enumerate(cables):
                    ey = exit_pts[-1][1]
                    pts = [start, *exit_pts, (vxs[i], ey), (vxs[i], lane[i]), (mx, lane[i]), (mx, y_end)]
                    routes.append(pts)
                bad = sum(min_distance(a, b) < 13 for a, b in itertools.combinations(routes, 2))
                length = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for r in routes for p, q in zip(r, r[1:]))
                key = (bad, length)
                if best is None or key < best[0]:
                    best = (key, routes)
        if best and best[0][0] == 0 and n > 3:
            break
    return best[1]


def draw_cal(group, cal):
    title, figure, leads, jumpers, note = GROUPS[group]
    bh.PY = 62                                                          # panel below the title line
    pen = Pen(W, H, '#ffffff')
    pen.text(24, 20, f'Fluke 753 / 754 - {title}', 15, '#000000', anchor='lm')
    pen.text(24, 40, figure + f'   |   calibrator: Fluke {cal}', 10, '#3c3c3c', bold=False, anchor='lm')
    used = {j for j, _c, _t in leads} | {a for a, b in jumpers} | {b for a, b in jumpers}
    draw_753(pen, used, jumpers)
    names = JACKNAME[cal]
    lit, wanted = {}, []
    for jack, colour, text in leads:
        key = KEY_OF.get(id(text))
        if key:
            lit[names[key]] = 'blue' if key in ('I', 'I0') and cal == '5560A' else 'green'
    if cal == '5560A':
        jacks = bh.draw_5560a(pen, lit, False)
    else:
        jacks = bh.draw_5522a(pen, {k: True for k in lit})
    pen.text(bh.PX + 76 * bh.K, bh.PY + (276 if cal == '5560A' else 196) * bh.K + 18, f'Fluke {cal} front panel' + ('' if cal == '5560A' else ' (output terminals)'), 10.5, '#5a6475', bold=False)
    per = {}
    for lead in leads:
        per.setdefault(lead[0], []).append(lead)
    plugs = []
    for jack, items in per.items():
        for n, lead in enumerate(items):
            plugs.append((DRAW[jack][0] + (n - (len(items) - 1) / 2) * 20, jack, lead))
    plugs.sort(key=lambda t: t[0])
    cables, tags, extra = [], [], []
    manual = None
    for x, jack, (j, colour, text) in plugs:
        down = jack[0] == 'b' or jack == 'tc'
        jy = DRAW[jack][1]
        y_end = jy + 34 if down else jy - 34
        key = KEY_OF.get(id(text))
        if key is None:
            if group == 'MEAS_MA' and j == 'tm':
                manual = (x, jack, colour, y_end)
            else:
                tags.append((x, jack, colour, y_end, down, text))
            continue
        start, exit_pts = jacks[names[key]]
        cables.append((start, exit_pts, x, y_end, down, colour, key))
    routes = route_all([c[:5] for c in cables]) if cables else []
    drawn = []
    for r, c in zip(routes, cables):
        drawn.append((r, c))
    # the 3458A in series (dc mA): box in the middle, its LO to the UUT mA jack, its I to the calibrator current output
    if manual:
        bx0, by0, bx1, by1 = 346, 430, 432, 482
        pen.rect(bx0, by0, bx1, by1, r=8, fill='#2f5a4a', outline='#16181b', width=2.5)
        pen.text((bx0 + bx1) / 2, by0 + 14, '3458A', 11, '#ffffff')
        pen.text((bx0 + bx1) / 2, by0 + 28, 'in series', 8.6, '#dfe6ee', bold=False)
        pen.text(bx0 + 18, by0 + 42, 'LO', 8.4, '#dfe6ee')
        pen.text(bx1 - 20, by0 + 42, 'I', 8.4, '#dfe6ee')
        x, jack, colour, y_end = manual
        a = [(x, y_end), (x, TOP_LANES[1]), (bx0 + 18, TOP_LANES[1]), (bx0 + 18, by0)]
        cable(pen, a, CABLE[colour])
        kI = 'I'
        start, exit_pts = jacks[names[kI]]
        lit_note = None
        b = [start, *exit_pts, (453, 456), (bx1 + 4, 456)]
        extra.append((b, RED, (x, jack, colour, y_end), a))
    for r, (c) in drawn:
        pass
    # draw: black cables first, red on top
    order = sorted(range(len(drawn)), key=lambda i: drawn[i][1][5] != BLACK)
    for i in order:
        r, c = drawn[i]
        if manual and c[6] == 'I0':                                      # the return goes around the 3458A: down its left side
            ey = c[1][-1][1]
            r = [c[0], *c[1], (446, ey), (446, BOTTOM_LANES[1]), (c[2], BOTTOM_LANES[1]), (c[2], c[3])]
        cable(pen, r, CABLE[c[5]])
    for b, col, *_ in extra:
        cable(pen, b, CABLE[col])
        pen.rect(bx1 - 2, 450, bx1 + 8, 462, r=3, fill=CABLE[col], outline='#ffffff', width=1.3)
    for (r, c) in drawn:                                                  # plugs on the UUT jacks and the calibrator ends
        x, y_end, down, colour = c[2], c[3], c[4], c[5]
        jy = y_end - 34 if down else y_end + 34
        y0, y1 = (jy + 10, jy + 34) if down else (jy - 34, jy - 10)
        pen.rect(x - 7, y0, x + 7, y1, r=4, fill=CABLE[colour], outline='#ffffff', width=1.5)
        pen.circle(c[0][0], c[0][1], 6.4 * bh.K, fill=CABLE[colour], outline='#ffffff', width=1.8)
    if manual:
        x, jack, colour, y_end = manual
        jy = DRAW[jack][1]
        pen.rect(x - 7, jy - 34, x + 7, jy - 10, r=4, fill=CABLE[colour], outline='#ffffff', width=1.5)
        c0 = jacks[names['I']][0]
        pen.circle(c0[0], c0[1], 6.4 * bh.K, fill=RED_, outline='#ffffff', width=1.8)
    for x, jack, colour, y_end, down, text in tags:                       # a lead the figure does not tie to a calibrator terminal (UNVERIFIED)
        ys = TOP_LANES[1] if not down else BOTTOM_LANES[1]
        cable(pen, [(x, y_end), (x, ys), (x + 36, ys)], CABLE[colour])
        pen.rect(x + 32, ys - 18, x + 90, ys + 18, r=6, fill='#fff3c4', outline='#b58900', width=2)
        pen.text(x + 61, ys - 6, 'LEAD 2', 8, '#5a4300')
        pen.text(x + 61, ys + 8, 'UNVERIFIED', 7, '#b00020')
        jy = DRAW[jack][1]
        y0, y1 = (jy + 10, jy + 34) if down else (jy - 34, jy - 10)
        pen.rect(x - 7, y0, x + 7, y1, r=4, fill=CABLE[colour], outline='#ffffff', width=1.5)
    for a, b in jumpers:
        (ax, ay), (bx, by) = DRAW[a], DRAW[b]
        bx -= 10 * len(per.get(b, ())) if per.get(b) else 0
        cable(pen, [(ax, ay + 12), (ax, ay + 26), (bx, ay + 26), (bx, ay + 12)], BLACK, 6)
    draw_labels(pen, used)
    for n, line in enumerate(wrap(pen, note, 9.5, W - 48)[:3]):
        pen.text(24, H - 58 + n * 14, line, 9.5, '#000000', bold=False, anchor='lm')
    pen.text(24, H - 14, 'Jacks drawn from the supplied photo; leads from the Calibration Manual figure named above (red = high, black = low / common).', 8, '#5a6475', bold=False, anchor='lm')
    path = OUT / f'hook_fluke753_{cal}_{group}.png'
    pen.save(path)
    return path


RED_ = '#d11a2a'

DEVICE = {'MEAS_V': ('CALIBRATOR', '#3d4f66'), 'MEAS_MA': ('CALIBRATOR + 3458A', '#3d4f66'), 'MEAS_OHM': ('CALIBRATOR', '#3d4f66'),
          'MEAS_TC': ('CALIBRATOR', '#3d4f66'), 'MEAS_RTD4': ('CALIBRATOR', '#3d4f66'), 'MEAS_RTD3': ('CALIBRATOR', '#3d4f66'),
          'SRC_V': ('EXTERNAL DMM', '#2f5a4a'), 'SRC_MA': ('EXTERNAL DMM', '#2f5a4a'), 'SRC_SIM': ('CALIBRATOR + DMM', '#3d4f66'),
          'SRC_OHM': ('EXTERNAL DMM', '#2f5a4a'), 'SRC_FREQ': ('COUNTER / SCOPEMETER', '#5a4a2f'), 'SRC_TC': ('LAG BATH + DMM', '#5a4a2f'),
          'LOOP': ('EXTERNAL DMM', '#2f5a4a'), 'HART': ('HART TRANSMITTER', '#5a4a2f')}


# pictures the owner supplied (kept as files; never redrawn): SRC_SIM = Figure 7 (simulate transmitter), supplied 2026-10-27
SUPPLIED = ('SRC_SIM',)


def main():
    for g in GROUPS:
        if g in SUPPLIED:
            continue
        print('wrote', draw(g).name)
    for cal in ('5560A', '5522A'):
        for g in CAL_GROUPS:
            print('wrote', draw_cal(g, cal).name)


if __name__ == '__main__':
    main()
