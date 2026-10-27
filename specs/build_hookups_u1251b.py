"""Hook-up diagrams of the Keysight U1251B / U1252B procedure:   python3 specs/build_hookups_u1251b.py      (needs Pillow; the procedures do not)

Writes diagrams/hook_u1251b_<CAL>_<GROUP>.png (CAL 5560A / 5522A; GROUP VOHM, UAMP, AMP10) and diagrams/hook_u1251b_TEMP.png.
Owner request 2026-10-27: drawn from the owner's photo of the U1252B front panel (crop saved as diagrams/keysight_u1252b_terminals.png) for the jack positions,
and from hookups.py (CAL_TERMS, METERS 'u1251b') for the calibrator terminals and the leads: red = high, black = COM.
Jacks left to right on the photo: A (10 A MAX FUSED) | µA mA (440 mA FUSED) | COM | Ω V mV (1000 V MAX).
UNVERIFIED: the U1251B is drawn from the same picture (same jack layout assumed; no U1251B photo was supplied).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PHOTO = ROOT / 'diagrams' / 'keysight_u1252b_terminals.png'
OUT = ROOT / 'diagrams'
S = 4
JACK = {'A': (39, 88), 'MA': (94, 88), 'COM': (144, 88), 'V': (199, 88)}                       # centres in the 228 x 120 crop
NAME = {'A': 'A (10 A MAX, fused)', 'MA': 'µA mA (440 mA, fused)', 'COM': 'COM', 'V': 'Ω V mV (1000 V MAX)'}
RED, BLACK, GREY = (200, 20, 25), (25, 25, 25), (110, 110, 110)
FONT = '/usr/share/fonts/truetype/dejavu/'
CAL = {   # hookups.CAL_TERMS
    '5560A': {'VOHM': ('OUTPUT V/Ω HI', 'OUTPUT V/Ω LO'), 'UAMP': ('VI AUX', 'OUTPUT V/Ω LO'), 'AMP10': ('30A', 'OUTPUT V/Ω LO')},
    '5522A': {'VOHM': ('NORMAL HI', 'NORMAL LO'), 'UAMP': ('AUX HI', 'AUX LO'), 'AMP10': ('20 A', 'AUX LO')},
}
GROUP = {
    'VOHM': ('V', 'volts, ohms, capacitance, diode, frequency', 'Ω V mV jack (red) and COM (black). 5560A: the lit green terminals.'),
    'UAMP': ('MA', 'µA and mA current', 'µA mA jack (red) and COM (black). Fuse 440 mA. 5560A: the lit blue terminals.'),
    'AMP10': ('A', '5 A and 10 A current', 'A jack (red) and COM (black). Fuse 11 A; connect before applying 5 A / 10 A (meter caution band). 5560A: the lit blue terminals.'),
}


def font(size, bold=False):
    return ImageFont.truetype(FONT + ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'), size)


def draw(path, title, sub, leads, note):
    """leads: [(jack, colour, line1, line2)]"""
    photo = Image.open(PHOTO).convert('RGB')
    pw, ph = photo.width * S, photo.height * S
    photo = photo.resize((pw, ph), Image.LANCZOS)
    top, bottom, side = 250, 110, 40
    W, H = pw + 2 * side, ph + top + bottom
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    im.paste(photo, (side, top))
    pos = {k: (side + x * S, top + y * S) for k, (x, y) in JACK.items()}
    d.text((side, 10), title, font=font(20, True), fill=(0, 0, 0))
    d.text((side, 40), sub, font=font(14), fill=(60, 60, 60))
    used = {j for j, *_ in leads}
    for k, (cx, cy) in pos.items():
        if k not in used:
            d.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], outline=(150, 150, 150), width=3)
    placed = []
    for jack, colour, l1, l2 in leads:
        cx, cy = pos[jack]
        d.line([(cx, cy - 6), (cx, top - 70)], fill=colour, width=10)
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=colour, outline=(255, 255, 255), width=3)
        w = max(d.textlength(l1, font=font(14, True)), d.textlength(l2, font=font(11))) + 16
        x0 = min(max(side - 30, cx - w / 2), W - w - 4)
        row = 0
        while any(x0 < px + pw_ + 6 and px < x0 + w + 6 and pr == row for px, pw_, pr in placed):
            row += 1
        placed.append((x0, w, row))
        y0 = top - 140 - row * 58
        d.line([(cx, top - 70), (cx, y0 + 46)], fill=colour, width=10)
        d.rectangle([x0, y0, x0 + w, y0 + 46], fill=(245, 245, 245), outline=colour, width=3)
        d.text((x0 + 8, y0 + 4), l1, font=font(14, True), fill=colour if colour != GREY else (0, 0, 0))
        d.text((x0 + 8, y0 + 26), l2, font=font(11), fill=(40, 40, 40))
    for k, (cx, cy) in pos.items():
        d.text((cx, top + ph + 6), NAME[k], font=font(11), fill=(60, 60, 60), anchor='ma')
    d.text((side, H - 52), note, font=font(13), fill=(0, 0, 0))
    d.text((side, H - 30), 'Drawn from the owner photo of the U1252B (jack positions); the U1251B is assumed to have the same layout (UNVERIFIED). Leads red = high, black = COM.',
           font=font(11), fill=(90, 90, 90))
    im.save(path)
    return path


def main():
    for cal, groups in CAL.items():
        for g, (hi, lo) in groups.items():
            jack, what, note = GROUP[g]
            if cal != '5560A':
                note = note.split(' 5560A:')[0]
            draw(OUT / f'hook_u1251b_{cal}_{g}.png', f'Keysight U1251B / U1252B - {what}', f'Fluke {cal} to the meter',
                 [(jack, RED, 'CAL HI', f'{cal} {hi}'), ('COM', BLACK, 'CAL LO', f'{cal} {lo}')], note)
            print('wrote', f'hook_u1251b_{cal}_{g}.png')
    draw(OUT / 'hook_u1251b_TEMP.png', 'Keysight U1251B / U1252B - temperature (Type K thermocouple)', 'Calibrator TC output to the meter',
         [('V', GREY, 'TC + (calibrator TC output)', 'K-type extension, TC-to-banana adapter'), ('COM', GREY, 'TC − (calibrator TC output)', 'observe the polarity')],
         'Type K extension, TC-to-banana adapter, Ω V mV and COM jacks; meter in the temperature mode (Shift).')
    print('wrote hook_u1251b_TEMP.png')


if __name__ == '__main__':
    main()
