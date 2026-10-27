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

from PIL import Image, ImageDraw, ImageFont

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
                [('tm', BLACK, CAL['I']), ('bm', BLACK, CAL['I0'])], [], 'Calibrator current output in series with the mA jack; the manual adds a Fluke 8508A in the loop (optional here).'),
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


def font(size, bold=False):
    return ImageFont.truetype(FONT + ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'), size)


def draw(group):
    title, figure, leads, jumpers, note = GROUPS[group]
    photo = Image.open(PHOTO).convert('RGB')
    pw, ph = photo.width * S, photo.height * S
    photo = photo.resize((pw, ph), Image.LANCZOS)
    top, bottom, side = 290, 230, 40
    W, H = pw + 2 * side, ph + top + bottom
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    im.paste(photo, (side, top))
    pos = {k: (side + x * S, top + y * S) for k, (x, y) in JACK.items()}
    d.text((side, 10), f'Fluke 753 / 754 - {title}', font=font(20, True), fill=(0, 0, 0))
    d.text((side, 40), figure, font=font(14), fill=(60, 60, 60))
    used = {j for j, _c, _t in leads} | {a for a, b in jumpers} | {b for a, b in jumpers}
    for k, (cx, cy) in pos.items():                                # the jacks not used: a grey cross-hatch ring so the used ones stand out
        if k not in used:
            d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], outline=(150, 150, 150), width=3)
    # leads: top jacks go up to boxes above, bottom jacks go down; several leads on one jack fan out
    groups = {}
    for lead in leads:
        groups.setdefault(lead[0], []).append(lead)
    boxes = []
    for jack, items in groups.items():
        cx, cy = pos[jack]
        up = jack[0] == 't' and jack != 'tc'
        for n, (j, colour, (l1, l2)) in enumerate(items):
            dx = (n - (len(items) - 1) / 2) * 26
            if jack == 'tc':
                end = (side + 10 + n * 10, top + ph + 20 + n * 40)
                start = (cx + (n - 0.5) * 16, cy)
                bx, by = side, top + ph + 70 + n * 70
            elif up:
                start, end = (cx + dx * 0.4, cy - 10), (cx + dx, top - 60 - n * 0)
                bx, by = cx + dx, top - 130
            else:
                start, end = (cx + dx * 0.4, cy + 10), (cx + dx, top + ph + 40)
                bx, by = cx + dx, top + ph + 60
            d.line([start, end], fill=colour, width=9)
            d.ellipse([start[0] - 11, start[1] - 11, start[0] + 11, start[1] + 11], fill=colour, outline=(255, 255, 255), width=2)
            boxes.append((bx, by, l1, l2, colour, up, jack))
    for a, b in jumpers:
        (ax, ay), (bx2, by2) = pos[a], pos[b]
        d.arc([min(ax, bx2), ay - 10, max(ax, bx2), ay + 70], 0, 180, fill=BLACK, width=7)
    # text boxes, spaced so they do not overlap
    placed = []
    for bx, by, l1, l2, colour, up, jack in sorted(boxes, key=lambda b: (b[5], b[0])):
        w = max(d.textlength(l1, font=font(14, True)), d.textlength(l2, font=font(11))) + 16
        x0 = bx - w / 2
        row = 0
        x0 = min(max(side - 30, x0), W - w - 4)
        while any(x0 < px + pw_ + 6 and px < x0 + w + 6 and pr == row and pu == up for px, pw_, pr, pu in placed):
            row += 1
        placed.append((x0, w, row, up))
        y0 = (top - 132 - row * 56) if up else (top + ph + 48 + row * 52)
        d.rectangle([x0, y0, x0 + w, y0 + 46], fill=(245, 245, 245), outline=colour, width=3)
        d.text((x0 + 8, y0 + 4), l1, font=font(14, True), fill=colour if colour != GREY else (0, 0, 0))
        d.text((x0 + 8, y0 + 26), l2, font=font(11), fill=(40, 40, 40))
    d.text((side, H - 52), note, font=font(13), fill=(0, 0, 0))
    d.text((side, H - 30), 'Drawn from the supplied photo (jack positions) and the Calibration Manual figure named above. Leads red = high, black = low / common.', font=font(11), fill=(90, 90, 90))
    path = OUT / f'hook_fluke753_{group}.png'
    im.save(path)
    return path


def main():
    for g in GROUPS:
        print('wrote', draw(g).name)


if __name__ == '__main__':
    main()
