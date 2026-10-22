"""Pure helpers for the per-point editor (Tk-free, no I/O, no instrument access).  procmods.py imports this module; it imports nothing of the suite.

What lives here
  * Decimal-safe number parsing for the developer-mode fields (tolerance, nominal): text is parsed to `Decimal` and compared as `Decimal`,
    never through binary floats, so 0.1 + 0.2 style surprises cannot make a limit check pass or fail wrongly.  Values are stored as the
    decimal TEXT the technician typed (normalised) and converted to float only when a point is patched (the engines work in floats).
  * Units: the base unit of a point.  Display scaling (mV, kHz ...) is display only, so SI-prefixed units are refused; a unit can only be
    replaced by another unit of the same dimension (V -> VDC, ohm -> OHM ...), because the unit never changes what is sourced or measured.
  * Point field paths: which fields of an engine point a point-definition override may patch (a fixed allow-list, also re-checked when applied).
  * Command targets of the per-point command overrides ('Driver:key@<pointkey>' and the extra lines 'Driver:+before1@<pointkey>').
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# ------------------------------------------------------------------------------------------------------------ decimals
_DEC = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')


def parse_decimal(text):
    """`Decimal` for text typed by a person; None when it is not a plain finite number ('', 'abc', 'nan', 'inf', '1,5', '5 V' ...)."""
    if isinstance(text, Decimal):
        return text if text.is_finite() else None
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, (int, float)):
        try:
            d = Decimal(str(text))
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    t = str(text).strip()
    if not _DEC.match(t):
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def dec_text(d) -> str:
    """Plain (non-exponent) text of a Decimal, trailing zeros of a fraction removed: Decimal('5.000') -> '5', Decimal('1E+3') -> '1000'."""
    d = parse_decimal(d)
    if d is None:
        return ''
    s = format(d, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return '0' if s in ('', '-0', '+0', '-') else s


def same_decimal(a, b) -> bool:
    x, y = parse_decimal(a), parse_decimal(b)
    if x is None or y is None:
        return a is b or (x is None and y is None and a == b)
    return x == y


def to_float(value):
    d = parse_decimal(value)
    return None if d is None else float(d)


# ------------------------------------------------------------------------------------------------------------ units
UNIT_GROUPS = {
    'volt': ('V', 'VAC', 'VDC', 'Vpp', 'Vrms'),
    'amp': ('A', 'AAC', 'ADC', 'Arms'),
    'ohm': ('ohm', 'OHM'),
    'frequency': ('Hz',),
    'time': ('s',),
    'capacitance': ('F',),
    'temperature': ('CEL', 'degC'),
    'power': ('W',),
    'ratio': ('%', 'PCT', 'ratio', 'dB', 'dBc', 'dBm', 'dBm/Hz', 'dBc/Hz', 'div', 'ppm'),
    'none': ('',),
}
VALID_UNITS = tuple(u for g in UNIT_GROUPS.values() for u in g)


def unit_group(unit):
    for name, members in UNIT_GROUPS.items():
        if unit in members:
            return name
    return None


def check_unit(old, new) -> list:
    """Problems with replacing the unit `old` by `new` ([] = fine).  Base units only (display scaling is display only); same dimension."""
    if not isinstance(new, str):
        return ['the unit must be text']
    if new not in VALID_UNITS:
        hint = ''
        if re.match(r'^[munkMGTpµμ](V|A|Hz|s|F|W|ohm)$', new):
            hint = ' Enter the base unit; the program scales it (mV, kHz ...) for display.'
        return [f'"{new}" is not a known unit (known: {", ".join(u for u in VALID_UNITS if u)}).{hint}']
    g_old = unit_group(old)
    if g_old is not None and unit_group(new) != g_old:
        return [f'the unit can only be replaced by one of the same kind ({", ".join(UNIT_GROUPS[g_old]) or "none"}); '
                f'it does not change what is sourced or measured']
    return []


# ------------------------------------------------------------------------------------------------------------ point fields
# Paths a point-definition override may patch.  'applied.value' is the value a handheld procedure sources (follows the nominal).
FIELD_PATHS = ('nominal', 'applied.value', 'unit', 'description', 'desc', 'dsb_desc')
CREATABLE = ('dsb_desc',)           # may be added to a point that does not have it (the handheld engine words a description from it when present)
DEF_KEYS = ('nominal', 'new_unit', 'description')           # the keys of a limit override's value that carry a point-definition change
DEF_FIELDS = {'nominal': 'nominal', 'new_unit': 'unit', 'description': 'description'}    # value key -> name in the 'fields' map
MAX_DESCRIPTION = 200


def get_path(p, path):
    cur = p
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def has_path(p, path) -> bool:
    cur = p
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def set_path(q, path, value):
    cur = q
    parts = path.split('.')
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value


def check_description(text) -> list:
    if not isinstance(text, str) or not text.strip():
        return ['the description is empty']
    if len(text) > MAX_DESCRIPTION:
        return [f'the description is longer than {MAX_DESCRIPTION} characters']
    if any(ord(c) < 32 for c in text):
        return ['control characters are not allowed in the description']
    return []


# ------------------------------------------------------------------------------------------------------------ command targets
PHASES = ('before', 'after')
MAX_EXTRA = 3                                       # extra command lines per point, driver and phase
_EXTRA_KEY = re.compile(r'^\+(before|after)([1-9]\d*)$')


def point_command_target(driver, key, point_key) -> str:
    return f'{driver}:{key}@{point_key}'


def extra_command_target(driver, phase, n, point_key) -> str:
    return f'{driver}:+{phase}{n}@{point_key}'


def parse_command_target(target):
    """dict(driver, key, point, extra) for a command override target.  point is None for an ordinary (driver-wide) command override;
    extra is (phase, n) for an extra command line, else None.  Never raises."""
    head, sep, point = str(target).partition('@')
    driver, _, key = head.partition(':')
    extra = None
    m = _EXTRA_KEY.match(key)
    if m:
        extra = (m.group(1), int(m.group(2)))
    return {'driver': driver, 'key': key, 'point': point if sep else None, 'extra': extra}
