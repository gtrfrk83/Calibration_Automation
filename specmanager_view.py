"""Display model of the Standards Specs tab (no Tk, no database): what text each card, stat block, chip and table cell shows.

Everything here is DISPLAY ONLY.  The stored rows, the printed sheet text and the numbers the uncertainty budgets use are never touched: a
formatted specification such as +/-(800 ppm + 6.00 uV) is built from the printed text of the sheet ('raw') with decimal arithmetic (no float), and
whenever the printed text is not one of the usual shapes the cell falls back to the printed text itself, so nothing is ever guessed.  The printed
text stays available as the tooltip of the cell.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

import specmanager as sm

PLUS_MINUS = '±'
LE = '≤'
MICRO = 'µ'
OMEGA = 'Ω'
DIVIDE = '÷'
DOT = '·'

KIND_ORDER = ['DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'COND', 'FREQ', 'TEMP', 'POWDC', 'POWAC', 'PHASE', 'LUX', 'FC', 'LAMBERT', 'UVIRR']
KIND_NAMES = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM': 'Resistance', 'CAP': 'Capacitance',
              'IND': 'Inductance', 'COND': 'Conductance', 'FREQ': 'Frequency', 'TEMP': 'Temperature', 'POWDC': 'DC power', 'POWAC': 'AC power',
              'PHASE': 'Phase', 'RPM': 'Rotation speed', 'RISE': 'Rise time', 'ABER': 'Aberrations', 'FLAT': 'Flatness', 'TIME': 'Time',
              'LUX': 'Illuminance (lux)', 'FC': 'Illuminance (foot-candle)', 'LAMBERT': 'Luminance (lambert)', 'UVIRR': 'UV irradiance (365 nm)',
              'OTHER': 'Other'}
KIND_CHIP = {'POWDC': 'Power DC', 'POWAC': 'Power AC', 'LUX': 'Lux', 'LAMBERT': 'Lambert', 'UVIRR': 'UV 365 nm', 'OTHER': 'Other'}

_NUM = r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'
_SCALABLE = ('V', 'A', 'F', 'Hz', 'W', 'H', 'S', 's', 'ohm', 'Vpp', 'App')
_STEPS = (9, 6, 3, 0, -3, -6, -9, -12)
_PREFIX_SYMBOL = {9: 'G', 6: 'M', 3: 'k', 0: '', -3: 'm', -6: MICRO, -9: 'n', -12: 'p'}
_SYMBOL = {'ohm': OMEGA, 'Ohm': OMEGA, 'degC': '°C', 'degF': '°F', 'deg': '°', 'sec': 's', 'uW/cm2': 'µW/cm²'}   # uW/cm2 (light sheet) is stored ASCII, shown as printed on the scope


# ------------------------------------------------------------------------------------------------------------ decimal helpers
def to_decimal(value):
    """Decimal of a number or of its printed text; None when it is neither.  A float goes through repr() (its shortest text), never through binary."""
    if value is None or value == '':
        return None
    try:
        return Decimal(value if isinstance(value, (Decimal, str)) else repr(value))
    except (InvalidOperation, ValueError):
        return None


def plain(d):
    """Decimal as plain digits without an exponent or trailing zeros: 8E+2 -> '800', 0.00093 -> '0.00093'."""
    if d == 0:
        return '0'
    return format(d.normalize(), 'f')


def _prefix_exponent(d):
    e = d.adjusted()
    return next((s for s in _STEPS if e >= s), _STEPS[-1])


def si_text(value, unit='', sig=3, exact=False):
    """Value with an SI prefix: 6e-06 V -> '6.00 uV' (with the micro sign), 0.3299999 V -> '330 mV'.

    At least `sig` significant digits.  exact=True never rounds (329.9999 mV stays 329.9999 mV: used for the terms of a specification); otherwise the
    value is rounded half up to `sig` digits (used for spans / frequencies / resolutions).  Units that take no prefix (degC, dB, ppm ...) are printed as is."""
    d = to_decimal(value)
    if d is None:
        return ''
    sym = _SYMBOL.get(unit, unit)
    if unit not in _SCALABLE:
        return f'{plain(d)} {sym}'.strip() if exact else f'{_round_sig(d, sig)} {sym}'.strip()
    if d == 0:
        return f'0 {sym}'.strip()
    with localcontext() as ctx:
        ctx.prec = 60
        p = _prefix_exponent(abs(d))
        for _ in range(1):
            mant = d.scaleb(-p)
            text = _digits(mant, sig, exact)
            if not exact and abs(Decimal(text)) >= 1000 and p < _STEPS[0]:      # 999.96 uV rounds to 1000 uV: say 1.00 mV
                p += 3
                text = _digits(Decimal(text).scaleb(-3), sig, False)
            break
    return f'{text} {_PREFIX_SYMBOL[p]}{sym}'.strip()


def _digits(mant, sig, exact):
    need = max(0, -mant.normalize().as_tuple().exponent) if exact else 0
    dec = max(need, sig - 1 - mant.adjusted(), 0)
    q = Decimal(1).scaleb(-dec)
    return format(mant.quantize(q, rounding=ROUND_HALF_UP), 'f')


def _round_sig(d, sig):
    if d == 0:
        return '0'
    with localcontext() as ctx:
        ctx.prec = 60
        return _digits(d, sig, False)


def split_unit(text):
    """'mV' -> (Decimal factor to the base unit, base symbol, annotation) e.g. (0.001, 'V', ''); an unknown unit gives (None, text, '')."""
    text = (text or '').strip()
    annot = ''
    m = sm._ANNOT.search(text)
    if m:
        annot, text = f' ({m.group(1)})', text[:m.start()].strip()
    if text in sm.SPECIAL:
        return Decimal(1), sm.SPECIAL[text], annot
    for base in sm.BASE:
        if text.endswith(base):
            pre = text[:-len(base)]
            if pre == '' or pre in sm.PREFIX:
                sym = {'Ohm': 'ohm', 'sec': 's'}.get(base, base)
                return Decimal(repr(sm.PREFIX.get(pre, 1.0))), sym, annot
    return None, text, annot


# ------------------------------------------------------------------------------------------------------------ one specification
_HEAD = re.compile(r'^\[(?P<period>[^\]]*)\]\s*Accuracy:\s*(?P<body>.*)$', re.S)
_REL = re.compile(rf'^({_NUM})\s*(ppm|%)\s*I\.V\.$')
_FS = re.compile(rf'^({_NUM})\s*%\s*F\.S\.\{{"Full Scale" = ({_NUM})\s*(\S+)\}}$')
_RNG = re.compile(rf'^({_NUM})\s*(ppm|%)\s*of range\{{"Range" = ({_NUM})\s*(\S+)\}}$')       # DMM 'ppm / % of range' (3458A)
_ABS = re.compile(rf'^({_NUM})\s*(\S.*)$')


def _term(term):
    m = _REL.match(term)
    if m:
        return f'{plain(Decimal(m.group(1)))} {m.group(2)}'
    m = _FS.match(term)
    if m:
        factor, sym, _a = split_unit(m.group(3))
        fs = Decimal(m.group(2)) * factor if factor is not None else None
        if fs is None:
            return None
        return f'{plain(Decimal(m.group(1)))} % FS ({si_text(fs, sym, exact=True)})'
    m = _RNG.match(term)
    if m:
        factor, sym, _a = split_unit(m.group(4))
        rng = Decimal(m.group(3)) * factor if factor is not None else None
        if rng is None:
            return None
        return f'{plain(Decimal(m.group(1)))} {m.group(2)} of range ({si_text(rng, sym, exact=True)})'
    m = _ABS.match(term)
    if m:
        num = Decimal(m.group(1))
        factor, sym, annot = split_unit(m.group(2))
        if factor is None:
            return f'{plain(num)} {sym}'
        return si_text(num * factor, sym, exact=True) + annot
    return None


def format_spec(spec):
    """Display text of one printed accuracy line: '[1 yr] Accuracy: +/-(800 ppm I.V. + 0.006 mV)' -> '+/-(800 ppm + 6.00 uV)' (with the real signs).

    Anything that is not the usual shape (dB terms, 'x N', a note in the line ...) is shown as the printed text with the signs replaced, so the cell
    never states more than the sheet does."""
    raw = (spec.get('raw') or spec.get('text') or '').strip()
    if not raw:
        return ''
    m = _HEAD.match(raw)
    body = (m.group('body') if m else raw).strip()
    shown = body.replace('+/-', PLUS_MINUS).replace('<=', LE)
    if not m or spec.get('error'):
        return shown
    le = body.startswith('<=')
    inner = body[2:] if le else body[3:] if body.startswith('+/-') else None
    if inner is None:
        return shown
    inner = inner.strip()
    if not (inner.startswith('(') and inner.endswith(')')):
        return shown
    inner = inner[1:-1]
    try:
        terms = [_term(t) for t in sm._split_terms(inner)]
    except (InvalidOperation, ValueError, ArithmeticError):
        return shown
    if not terms or any(t is None for t in terms):
        return shown
    sign = f'{LE} ' if le else PLUS_MINUS
    return sign + (terms[0] if len(terms) == 1 else '(' + ' + '.join(terms) + ')')


def spec_for(row, period):
    return next((s for s in row.get('specs') or [] if s.get('period') == period), None)


def spec_cell(row, period):
    """(display text, printed text) of the row's specification for one period; ('', '') when the sheet has none."""
    s = spec_for(row, period)
    if not s:
        return '', ''
    return format_spec(s), (s.get('raw') or s.get('text') or '')


def period_columns(rows, default='1 yr', limit=3):
    """(periods shown as columns, the other periods on the sheet).  Most-printed first; the standard's default period goes first when the sheet prints
    it on at least half as many rows as the most-printed one (the 8902A prints 'spec' on 65 rows and '1 yr' on 3: 'spec' comes first)."""
    count = {}
    for r in rows:
        for s in r.get('specs') or []:
            if s.get('period') and (s.get('raw') or s.get('text')):
                count[s['period']] = count.get(s['period'], 0) + 1
    top = max(count.values(), default=0)
    first = default if count.get(default, 0) * 2 >= top and default in count else None
    order = sorted(count, key=lambda p: (p != first, -count[p], p))
    return order[:limit], order[limit:]


def period_heading(period):
    """'1 yr' -> '1 YR SPEC', '90 day' -> '90 DAY SPEC', 'spec' -> 'SPEC', 'typical' -> 'TYPICAL' (a period that starts with a number is a calibration interval)."""
    return f'{period.upper()} SPEC' if period[:1].isdigit() else period.upper()


# ------------------------------------------------------------------------------------------------------------ one row
def split_label(label):
    """'1.2A @ 3 - 45 Hz' -> ('1.2A', '3 - 45 Hz'); a label without ' @ ' -> (label, '')."""
    a, sep, b = (label or '').partition(' @ ')
    return (a.strip(), b.strip()) if sep else ((label or '').strip(), '')


def span_text(row):
    if row.get('amp_lo') is None:
        return ''
    u = row.get('unit') or ''
    return f"{si_text(row['amp_lo'], u)} to {si_text(row['amp_hi'], u)}"


def freq_text(row):
    if row.get('freq_lo') is None:
        return split_label(row.get('label'))[1]
    return f"{si_text(row['freq_lo'], 'Hz')} to {si_text(row['freq_hi'], 'Hz')}"


def resolution_text(row):
    return si_text(row['resolution'], row.get('unit') or '') if row.get('resolution') else ''


def matches(row, kind='', term=''):
    """The filter of the old table, unchanged: function type, and the text in function + label + variant (case-insensitive)."""
    if kind and row['kind'] != kind:
        return False
    term = (term or '').strip().lower()
    return not term or term in (row['function'] + ' ' + row['label'] + ' ' + row['variant']).lower()


def kind_chips(rows):
    """[(kind code or '', chip text, count, full name)] for the function / type chips: 'All' first, then the kinds present."""
    count = {}
    for r in rows:
        count[r['kind']] = count.get(r['kind'], 0) + 1
    order = [k for k in KIND_ORDER if k in count] + sorted(k for k in count if k not in KIND_ORDER and k != 'OTHER') + (['OTHER'] if 'OTHER' in count else [])
    return [('', 'All', len(rows), 'Every function')] + [(k, KIND_CHIP.get(k, k), count[k], KIND_NAMES.get(k, k)) for k in order]


def group_rows(rows):
    """[(key, title, [rows])] in sheet order: one group per (function, direction).  The title says when the standard measures (input)."""
    out, index = [], {}
    for r in rows:
        key = (r['function'], r.get('direction') or '')
        if key not in index:
            index[key] = len(out)
            title = r['function'] + ('  (measures)' if key[1] == 'input' else '')
            out.append((key, title, []))
        out[index[key]][2].append(r)
    return out


# ------------------------------------------------------------------------------------------------------------ standards rail and header
def description_of(std):
    """The description without a trailing '(5520A)' that repeats the model."""
    d = (std.get('description') or '').strip()
    model = std.get('model') or ''
    suffix = f'({model})'
    return d[:-len(suffix)].rstrip() if model and d.endswith(suffix) else d


def confidence_summary(text, pct):
    """(value for the stat block, note, stated?) from the confidence text and number of a standard."""
    text = (text or '').strip()
    if pct:
        m = re.search(r'\((.*)\)\s*$', text)
        note = m.group(1).split(':')[0].strip() if m else ('stated on the sheet' if text else '')
        return f'{pct:g} %', note, True
    return 'Not stated', 'k = 2 assumed', False


def divisor_text(div):
    d = to_decimal(div)
    return plain(d) if d is not None else ''


def card_chip(std, div):
    """(text, kind) of the confidence / divisor chip of a rail card: blue when the sheet states a level (or the person set a divisor), grey when k = 2 is assumed."""
    d = divisor_text(div)
    pct = std.get('confidence_pct')
    manual = bool(std.get('divisor'))
    if pct:
        return f'{pct:g} % {DOT} {DIVIDE} {d}' + (' (set)' if manual else ''), 'info'
    if manual:
        return f'{DIVIDE} {d} (set)', 'info'
    return f'k = 2 assumed {DOT} {DIVIDE} {d}', 'neutral'


def issues_kind(problems):
    """Colour of the sheet issues pill: good when none, bad when any is an error, warn otherwise."""
    if not problems:
        return 'good'
    return 'bad' if any((p.get('level') or '').lower() in ('error', 'bad') for p in problems) else 'warn'


def issues_text(n):
    return f"{n} sheet issue{'' if n == 1 else 's'}"


def approved_text(std):
    who, when = (std.get('approved_by') or '').strip(), (std.get('approve_date') or '').strip()
    if not who and not when:
        return 'Not approved on the sheet'
    return f'{who} {DOT} {when}' if who and when else who or when


def period_note(shown, others):
    if not shown:
        return 'no accuracy lines'
    note = ' and '.join(shown) if len(shown) < 3 else ', '.join(shown[:-1]) + ' and ' + shown[-1]
    return f'columns: {note}' + (f"; also {', '.join(others)}" if others else '')


def ranges_note(rows):
    functions = {(r['function'], r.get('direction')) for r in rows}
    return f"in {len(functions)} function{'' if len(functions) == 1 else 's'}" if rows else 'none on the sheet'


def shown_count_text(shown, total):
    return f"Showing {shown} of {total} range{'' if total == 1 else 's'}"


def empty_message(total, kind, term):
    """What the table says when it has no rows: (message, can clear filters?)."""
    if not total:
        return 'This standard has no ranges. Import its specification (Import spec JSON...) to fill the table.', False
    parts = []
    if kind:
        parts.append(f'the {KIND_NAMES.get(kind, kind)} filter')
    if (term or '').strip():
        parts.append(f"the text '{term.strip()}'")
    return 'No range matches ' + ' and '.join(parts) + '.', True


def rail_width(panel_width):
    """Width of the standards rail for a panel of this width: 300 normally, narrower below ~1180, None (collapsed to a selector) below ~940."""
    if panel_width >= 1180:
        return 300
    if panel_width >= 1000:
        return 248
    if panel_width >= 940:
        return 224
    return None


def shown_periods(columns, table_width):
    """How many period columns fit: all of them in a wide table, two in a narrow one."""
    return columns[:3] if table_width >= 840 else columns[:2]


def ellipsize(text, width, measure):
    """Cut `text` with an ellipsis so measure(text) <= width."""
    if measure(text) <= width:
        return text
    cut = text
    while cut and measure(cut + '…') > width:
        cut = cut[:-1]
    return cut.rstrip() + '…'
