"""Builds specs/klein_mm325_pv.json and the diagrams in diagrams/ for the Klein Tools MM325 procedure.

    python3 specs/build_mm325.py          (needs Pillow; the finished procedure itself does not)

Source: Klein Tools MM325 Digital Multimeter Instruction Manual - specifications p. 3, operation pp. 5-10.
One test point per range at 90 % of the range; every AC point at 60 Hz (the manual specifies AC at 50-60 Hz).
Limits = +/-(percent of reading + digits x resolution), the manual's accuracy statement, evaluated exactly with Decimal.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_SPEC = HERE / 'klein_mm325_pv.json'
DIAG = ROOT / 'diagrams'
POINT_FRACTION = D('0.9')
AC_HZ = 60

# ------------------------------------------------------------------------------------------------ the dial (manual p. 5)
# 20 positions, 18 degrees apart, clockwise from OFF at the top.
DIAL = [
    ('OFF', 'OFF', 'off'), ('ACV_600', '600', 'acv'), ('ACV_200', '200', 'acv'), ('DIODE', 'diode', 'diode'), ('CONT', 'cont', 'diode'),
    ('OHM_2k', '2k', 'ohm'), ('OHM_20k', '20k', 'ohm'), ('OHM_200k', '200k', 'ohm'), ('OHM_2M', '2M', 'ohm'),
    ('A_10', '10', 'amp'), ('A_200m', '200m', 'amp'), ('A_20m', '20m', 'amp'), ('A_200u', '200µ', 'amp'),
    ('BATT_1.5V', '1.5V', 'batt'), ('BATT_9V', '9V', 'batt'),
    ('DCV_200m', '200m', 'dcv'), ('DCV_2', '2', 'dcv'), ('DCV_20', '20', 'dcv'), ('DCV_200', '200', 'dcv'), ('DCV_600', '600', 'dcv'),
]
GROUP_CAPTION = {'dcv': 'V⎓', 'acv': 'V~', 'ohm': 'Ω', 'amp': 'A⎓', 'batt': 'BATT', 'diode': ''}
GROUP_COLOR = {'dcv': '#8ec5ff', 'acv': '#ff9fb2', 'ohm': '#8de0a5', 'amp': '#ffc27a', 'batt': '#f2e27a', 'diode': '#c9a8ff', 'off': '#ffffff'}
GROUP_FUNCTION = {'dcv': 'V⎓ (DC volts)', 'acv': 'V~ (AC volts)', 'ohm': 'Ω (resistance)', 'amp': 'A⎓ (DC current)', 'batt': 'BATT (battery test)'}
DIAL_SIZE = 400
DIAL_CENTER = (200, 200)
LABEL_RADIUS = 158


def dial_xy(index, radius=LABEL_RADIUS):
    theta = math.radians(index * 18)
    return DIAL_CENTER[0] + radius * math.sin(theta), DIAL_CENTER[1] - radius * math.cos(theta)


# ------------------------------------------------------------------------------------------------ the test points
def fmt(d: D) -> str:
    return format(d.normalize(), 'f')


R = [
    ('DC volts', 'V⎓  (DC volts)', 'DCV_200m', '200.0 mV', 'DCV', 'mV', '0.001', 'V', '200', '0.1', '0.5', 3, 'VOHM'),
    ('DC volts', 'V⎓  (DC volts)', 'DCV_2', '2000 mV', 'DCV', 'mV', '0.001', 'V', '2000', '1', '0.5', 3, 'VOHM'),
    ('DC volts', 'V⎓  (DC volts)', 'DCV_20', '20.00 V', 'DCV', 'V', '1.0', 'V', '20', '0.01', '0.5', 3, 'VOHM'),
    ('DC volts', 'V⎓  (DC volts)', 'DCV_200', '200.0 V', 'DCV', 'V', '1.0', 'V', '200', '0.1', '0.8', 3, 'VOHM'),
    ('DC volts', 'V⎓  (DC volts)', 'DCV_600', '600 V', 'DCV', 'V', '1.0', 'V', '600', '1', '0.8', 3, 'VOHM'),
    ('AC volts', 'V~  (AC volts, 50 to 60 Hz)', 'ACV_200', '200.0 V', 'ACV', 'V', '1.0', 'V', '200', '0.1', '1.0', 3, 'VOHM'),
    ('AC volts', 'V~  (AC volts, 50 to 60 Hz)', 'ACV_600', '600 V', 'ACV', 'V', '1.0', 'V', '600', '1', '1.2', 5, 'VOHM'),
    ('Battery test', 'BATT  (battery test)', 'BATT_9V', '9 V', 'DCV', 'V', '1.0', 'V', '9', '0.01', '1.0', 2, 'VOHM'),
    ('Battery test', 'BATT  (battery test)', 'BATT_1.5V', '1.5 V', 'DCV', 'V', '1.0', 'V', '1.5', '0.001', '1.0', 2, 'VOHM'),
    ('Resistance', 'Ω  (resistance)', 'CONT', '200.0 Ω', 'OHM', 'Ω', '1.0', 'ohm', '200', '0.1', '0.8', 3, 'VOHM'),
    ('Resistance', 'Ω  (resistance)', 'OHM_2k', '2000 Ω', 'OHM', 'Ω', '1.0', 'ohm', '2000', '1', '0.8', 3, 'VOHM'),
    ('Resistance', 'Ω  (resistance)', 'OHM_20k', '20.00 kΩ', 'OHM', 'kΩ', '1000.0', 'ohm', '20', '0.01', '0.8', 3, 'VOHM'),
    ('Resistance', 'Ω  (resistance)', 'OHM_200k', '200.0 kΩ', 'OHM', 'kΩ', '1000.0', 'ohm', '200', '0.1', '0.8', 3, 'VOHM'),
    ('Resistance', 'Ω  (resistance)', 'OHM_2M', '2000 kΩ', 'OHM', 'kΩ', '1000.0', 'ohm', '2000', '1', '1.0', 3, 'VOHM'),
    ('DC current', 'A⎓  (DC current)', 'A_200u', '200.0 µA', 'DCI', 'µA', '0.000001', 'A', '200', '0.1', '1.0', 5, 'UAMP'),
    ('DC current', 'A⎓  (DC current)', 'A_20m', '20.00 mA', 'DCI', 'mA', '0.001', 'A', '20', '0.01', '1.0', 5, 'UAMP'),
    ('DC current', 'A⎓  (DC current)', 'A_200m', '200.0 mA', 'DCI', 'mA', '0.001', 'A', '200', '0.1', '1.0', 5, 'UAMP'),
    ('DC current', 'A⎓  (DC current)', 'A_10', '10.00 A', 'DCI', 'A', '1.0', 'A', '10', '0.01', '2.0', 5, 'AMP10'),
]
SETTLE = {'DCV_200m': 3, 'DCV_2': 3, 'DCV_20': 3, 'DCV_200': 3, 'DCV_600': 3, 'ACV_200': 5, 'ACV_600': 5, 'BATT_9V': 3, 'BATT_1.5V': 3, 'CONT': 4, 'OHM_2k': 4, 'OHM_20k': 4, 'OHM_200k': 5, 'OHM_2M': 6, 'A_200u': 4, 'A_20m': 4, 'A_200m': 4, 'A_10': 2}
NOTES = {'ACV_200': 'The AC specification applies from 50 to 60 Hz (manual p. 3); every AC point is run at 60 Hz.', 'BATT_9V': 'The meter loads the source with about 450 Ω (about 18 mA at 8.1 V, manual p. 3). The calibrator must be able to source this current.', 'BATT_1.5V': 'The meter loads the source with about 100 Ω (about 13.5 mA at 1.35 V, manual p. 3).', 'CONT': 'The manual lists a 200.0 Ω range (p. 3) but the dial (p. 5) has no 200 Ω label. Use the continuity position, which reads resistance (p. 10). If your meter has a separate 200 Ω position, use that. If the display does not show about 180.0, skip the point and tell your supervisor.', 'OHM_2k': 'Two-wire connection: the lead resistance adds to the reading.', 'A_10': 'Meter limit: above 6 A, measure for no more than 30 s, then rest the meter for 10 minutes (manual p. 9). The output switches off after 30 s.'}


def build_steps():
    steps = []
    label_of = {key: label for key, label, _g in DIAL}
    for n, (section, switch, dial, rng, kind, unit, factor, base, fs, res, pct, digits, group) in enumerate(R, 1):
        full, resolution = D(fs), D(res)
        applied = (full * POINT_FRACTION).quantize(resolution) if (full * POINT_FRACTION) != (full * POINT_FRACTION).quantize(resolution) else full * POINT_FRACTION
        tolerance = D(pct) / 100 * applied + digits * resolution
        low, high = applied - tolerance, applied + tolerance
        applied_base = float(applied * D(factor))
        step = dict(
            table='1', step=n, section=section, switch=switch, range=rng, models=['MM325'], kind=kind, display_unit=unit, factor=float(D(factor)), base_unit=base,
            low=fmt(low), high=fmt(high), test='numeric',
            applied=dict(value=applied_base, frequency=AC_HZ if kind == 'ACV' else None), nominal=applied_base,
            group=group, settle=SETTLE[dial], dial=dial, ref='p. 3',
            accuracy=f'±({pct} % of reading + {digits} digits)',
            tol_text=f'±({pct} % × {fmt(applied)} {unit} + {digits} × {fmt(resolution)} {unit}) = ±{fmt(tolerance)} {unit}',
            id=f'1-{n}')
        group_key = next(g for k, l, g in DIAL if k == dial)
        word = 'continuity position' if dial == 'CONT' else f'position labelled "{label_of[dial]}"'
        step['dial_text'] = f'{GROUP_FUNCTION.get(group_key, "")}  -  {word}'.strip(' -')
        if dial == 'CONT':
            step['dial_text'] = 'Ω / continuity position (•))) - the 200 Ω range'
        if dial in NOTES:
            step['note'] = NOTES[dial]
        if dial == 'A_10':
            step['max_on_s'] = 30
            step['recovery_s'] = 600
        steps.append(step)
    return steps


def build_spec():
    positions = {}
    for i, (key, label, group) in enumerate(DIAL):
        x, y = dial_xy(i)
        positions[key] = dict(label=label, x=round(x, 1), y=round(y, 1), angle=i * 18, group=group)
    return dict(
        schema=3, kind='handheld-manual',
        source=dict(document='Klein Tools MM325 Digital Multimeter Instruction Manual',
                    pages='3 (specifications), 5-10 (operation)',
                    cite='Klein Tools MM325 Instruction Manual, pp. 3 and 5-10',
                    limits='Manufacturer accuracy, +/-(% of reading + digits), one point per range at 90 % of range',
                    note='One test point per range at 90 % of the range; every AC point at 60 Hz. Limits are the manual\'s accuracy statement '
                         '(+/-(% of reading + digits), 18 to 28 C) evaluated at the applied value. Diode test and continuity have no stated tolerance and are not included. '
                         'Calibrator: Fluke 5560A (or 5522A).'),
        options=dict(range_prompt=True, point_percent=90, ac_frequency_hz=AC_HZ, hv_threshold_v=60, hookup_meter='mm325', auto_ramp=False, function_prompt=True),
        models={'MM325': dict(name='Klein Tools MM325', brand='Klein', model_note='manual-ranging digital multimeter, 600 V CAT III')},
        dial=dict(image='diagrams/mm325_dial.png', size=[DIAL_SIZE, DIAL_SIZE], center=list(DIAL_CENTER), knob_radius=84, positions=positions),
        steps=build_steps())


# ------------------------------------------------------------------------------------------------ drawing (Pillow)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from draw_kit import Pen, bezier   # noqa: E402


def draw_diode(pen, x, y, color):
    pen.polygon([(x - 9, y - 7), (x - 9, y + 7), (x + 4, y)], fill=color)
    pen.line([(x + 6, y - 8), (x + 6, y + 8)], color, 2.2)


def dc_symbol(pen, x, y, color):
    """The DC sign (solid bar over a dashed bar), drawn by hand because the standard fonts lack it."""
    pen.line([(x - 6, y - 3), (x + 6, y - 3)], color, 1.8)
    for a, b in ((-6, -3), (-1, 2), (4, 6)):
        pen.line([(x + a, y + 2.5), (x + b, y + 2.5)], color, 1.8)


def caption(pen, x, y, text, color, size=14):
    if text.endswith('\u2393'):
        pen.text(x - 7, y, text[:-1], size, color)
        dc_symbol(pen, x + 9, y - 2, color)
    else:
        pen.text(x, y, text, size, color)


def draw_dial_base(path):
    w = DIAL_SIZE
    pen = Pen(w, w, (0, 0, 0, 0))
    pen.rect(2, 2, w - 3, w - 3, r=28, fill='#2f3339', outline='#55606e', width=2)
    for i, (key, label, group) in enumerate(DIAL):
        x, y = dial_xy(i)
        color = GROUP_COLOR[group]
        if key == 'DIODE':
            draw_diode(pen, x, y, color)
        elif key == 'CONT':
            pen.text(x, y, '\u2022))', 18, color)
        else:
            pen.text(x, y, label, 16, color)
        x0, y0 = dial_xy(i, 98)
        x1, y1 = dial_xy(i, 108)
        pen.line([(x0, y0), (x1, y1)], '#6c7683', 1.8)
    spans = {}
    for i, (key, label, group) in enumerate(DIAL):
        spans.setdefault(group, []).append(i)
    for group, idx in spans.items():
        text = GROUP_CAPTION.get(group, '')
        if text:
            x, y = dial_xy(sum(idx) / len(idx), 128)
            caption(pen, x, y, text, GROUP_COLOR[group])
    pen.save(path)


def main():
    spec = build_spec()
    OUT_SPEC.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
    draw_dial_base(DIAG / 'mm325_dial.png')
    print('wrote', OUT_SPEC, len(spec['steps']), 'points')


if __name__ == '__main__':
    main()
