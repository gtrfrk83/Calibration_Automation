"""Datasheet Builder: how a temperature point is SOURCED (a thermocouple type, or an RTD type).  No tkinter.

The choice is stored in the point's settings as `settings['sensor']` = a canonical KEY: a thermocouple letter 'B' 'C' 'D' 'E' 'J' 'K' 'L' 'N' 'R' 'S' 'T' 'U', or an RTD key
'Pt385-100' 'Pt385-200' 'Pt385-500' 'Pt385-1000' 'Pt3926-100' 'Pt3916-100' 'Pt395-100' 'Cu427-10' 'PtNi385-120' (the keys of the lab scope's TEMP lines in
specs/a2la_1888_03_cmc.json -> uncertainty.sensor_types()).  Old sheets only carry settings['tc_type'] = 'K' (a letter): that is read as the choice.  A point with neither is
'not chosen yet' (sensor_of() returns '').

ONE place for the list: sensor_types().  It takes the scope's own list (uncertainty.sensor_types(): ordered (key, label) pairs) when that function exists and falls back to
the list below with the same keys and labels, so merging the branch that adds the RTD lines to the scope needs no change here.

What each key means for the standards matcher: variant_for(key) is the text of the standard's own function name ('Type K' -> 'Temperature [Thermocouple, Type K Output]';
'Pt385-100' -> 'Temperature [RTD, Pt 385, 100 Ohm]').  automation_kind() says whether the suite's run engine can source it (see its docstring).
"""
from __future__ import annotations

import re

THERMOCOUPLES = tuple('BCDEJKLNRSTU')
_RTD_FALLBACK = (('Pt385-100', 'RTD Pt 385, 100 ohm'), ('Pt385-200', 'RTD Pt 385, 200 ohm'), ('Pt385-500', 'RTD Pt 385, 500 ohm'), ('Pt385-1000', 'RTD Pt 385, 1000 ohm'),
                 ('Pt3926-100', 'RTD Pt 3926, 100 ohm'), ('Pt3916-100', 'RTD Pt 3916, 100 ohm'), ('Pt395-100', 'RTD Pt 395, 100 ohm'),
                 ('Cu427-10', 'RTD Cu 427, 10 ohm'), ('PtNi385-120', 'RTD PtNi 385, 120 ohm (Ni120)'))
_RTD_KEY = re.compile(r'^(Pt|Cu|PtNi)(\d+)-(\d+)$')
NOT_CHOSEN = 'Choose how the temperature is sourced (thermocouple type or RTD)'


def sensor_types():
    """[(key, label)] in display order: thermocouples B..U, then the RTDs."""
    try:
        import uncertainty
        f = getattr(uncertainty, 'sensor_types', None)
        got = f() if f else None
        if got:
            return [(k, l) for k, l in (got.items() if isinstance(got, dict) else got)]
    except Exception:
        pass
    return [(t, f'Thermocouple Type {t}') for t in THERMOCOUPLES] + list(_RTD_FALLBACK)


def label(key):
    return dict(sensor_types()).get(key, key or '')


def key_of_label(text):
    text = (text or '').strip()
    for k, lab in sensor_types():
        if text in (lab, k):
            return k
    return ''


def is_rtd(key):
    return bool(key) and key not in THERMOCOUPLES


def short(key):
    """'Type K' / 'RTD Pt 385, 100 ohm': the words shown in a grid cell."""
    return f'Type {key}' if key in THERMOCOUPLES else label(key)


def sensor_of(fn, p):
    """The choice for a temperature point: its own settings['sensor'], else the function's, else the old settings['tc_type'] letter, else '' (not chosen yet)."""
    if fn is None or fn.kind != 'TEMP':
        return ''
    for src in (p.settings if p is not None else {}, fn.settings):
        k = str(src.get('sensor') or '').strip()
        if k and k in dict(sensor_types()):
            return k
    for src in (p.settings if p is not None else {}, fn.settings):
        t = str(src.get('tc_type') or '').strip().upper()
        if t in THERMOCOUPLES:
            return t
    return ''


def variant_for(key):
    """The text the standards matcher looks for in a standard's function name: 'Type K', 'Pt 385, 100 Ohm'.  '' for no choice."""
    if key in THERMOCOUPLES:
        return f'Type {key}'
    m = _RTD_KEY.match(key or '')
    return f'{m.group(1)} {m.group(2)}, {m.group(3)} Ohm' if m else ''


def automation_kind(settings, kind='TEMP'):
    """The driver-table key for what the run engine would have to do: 'TEMP' for thermocouple Type K (the stock engine sources Type K only; it calls
    set_output_temperature(c) without a type), 'TEMP_OTHER' for every other thermocouple type and for the RTDs (the suite has no call for them: set by hand).
    A point with no sensor keeps the old meaning (Type K)."""
    if kind != 'TEMP':
        return kind
    key = str((settings or {}).get('sensor') or '').strip() or str((settings or {}).get('tc_type') or '').strip().upper() or 'K'
    return 'TEMP' if key == 'K' else 'TEMP_OTHER'
