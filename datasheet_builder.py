"""Datasheet Builder core (stage A): the UI-free data model, specification expressions, test point calculator, validation and storage
for datasheets that a user builds from scratch for ANY make / model.  No tkinter, no instrument I/O.

Three modules, one public API (everything below is importable from `datasheet_builder`; the last two are loaded lazily):

    datasheet_builder.py           model, expressions, calculator, validation, storage / versioning   (this file)
    datasheet_builder_specs.py     export to the runnable spec JSON (schema extension 'dsb'), spec validation, spec -> datasheet
    datasheet_builder_match.py     'automate': which imported standard sources / measures each point, TAR / TUR, driver table

Design notes: design/datasheet_builder.md (in the session scratchpad; the same text is the reference for the UI and runtime stages).

----------------------------------------------------------------------------------------------------------------------------------------
DATA MODEL  (all numbers are Decimal in SI base units: V A ohm F Hz s degC dB; JSON stores them as strings; scaling is display-only)

    ds = Datasheet(make='Keysight', model='34461A', title='34461A Performance Verification')
    ds.periods                      [Period('90d', '90 days'), Period('1y', '1 year')]      default_period = '1y'
    fn = ds.add_function('DCV')     Function(kind=...)        kinds: DMM  DCV ACV DCI ACI OHM2 OHM4 CAP FREQ PERIOD TEMP DIODE CONT
                                                                     SCOPE SCOPE_GAIN SCOPE_OFFSET SCOPE_BW SCOPE_TIMEBASE SCOPE_TRIGGER
                                                                     GENERATOR GEN_AMPL GEN_FREQ GEN_OFFSET GEN_FLAT      (KINDS has unit, name, legacy name)
    fn.direction                    'measure' = the UUT measures a stimulus the standard sources (DMM, scope);
                                    'source'  = the UUT outputs and a standard measures (generators)
    fn.ranges  [Range]              id, full_scale, resolution, label, display_unit (display only), max_input, unipolar
    fn.spec    [SpecEntry]          per-range and / or per-frequency-band accuracy: Expr per period (+ optional asymmetric minus Expr,
                                    one-sided mode low_only / high_only with a 'bound'), plus the text as printed
    fn.rules   [PointRule]          the calculator's rule set;   fn.points [Point]  the generated and hand-made test points
    Point                           id (stable), range_id, nominal, frequency, amplitude, settings{}, overrides{period: {low, high}}, enabled, edited

EXPRESSIONS  (exact Decimal arithmetic; context prec 50; the one irrational form, dB, is evaluated to 50 digits)

    parse_expr('0.05 % of reading + 0.01 % of range + 2 counts + 10 uV', unit='V')    -> Expr      (never guesses: ExprError(code))
    Expr.evaluate(Ctx(reading=5, full_scale=10, resolution=0.0001, frequency=None))   -> Tol(minus, plus)
    terms:  pct_reading ('%iV', % of input value)  pct_range (% of full scale)  counts (n x resolution)  abs (SI value)
            ppm_reading  ppm_range  db (ratio on the reading; basis 'amplitude' 20 log, or 'power' 10 log);   ops: sum, max, min
    expr.to_dict() / Expr.from_dict(d) / expr.text(unit)       the serial form and the human form; SpecEntry.printed keeps the manual's text

LIMITS
    fn.limit_for(point, period, ds)  -> Limit(nominal, low, high, minus, plus, source 'spec'|'override', ambiguous, ...);  Limit.accept_text(unit)
    Low / high are EXACT (nominal -/+ tolerance, normalised, no rounding), as the existing build_*.py scripts do (build_mm325.py); the opt-in
    ds.options['limit_rounding'] = 'outward' rounds low DOWN and high UP to the range resolution (never tightens a limit).
    Where two spec entries of equal specificity meet at a border the TIGHTER tolerance is used and Limit.ambiguous is True (validate warns).

CALCULATOR
    fn.add_rule(PointRule('pct', 'percent_of_range', {'percents': ['10','50','100'], 'bipolar': True}, frequencies={...}, amplitude='1 V'))
    regenerate(fn)  -> RegenReport(added, kept, removed, skipped)        rules -> points; user-edited points and manual points are never lost
    add_point / edit_point / remove_point / set_override / clear_override       hand editing;  Point.id never changes after creation
    rule types: percent_of_range  zero_and_full  fixed  linear  log  decade_125  frequency_sweep      frequency modes: list linear log bands none

VALIDATION   validate(ds) -> [DsProblem]   (cmdreg.Problem: str message + .code, plus .level 'error' | 'warn' and .where).  Pure: it never changes
             the datasheet and never guesses; errors(problems) / warnings(problems) filter.

STORAGE      (appdata data folder: user_specs/ ; registry tables user_datasheets + user_datasheet_versions in lab_registry.sqlite3 only)
    save(ds, who='', note='') -> SaveResult(uid, version, status, spec_path, problems)     every save is a NEW version; nothing is overwritten
    load(uid, version=None) -> Datasheet | None     list_datasheets() versions(uid) duplicate(uid, ...) delete(uid) restore(uid)  [delete is soft]
    export_json(uid, path, version=None) / import_json(path) -> ImportResult              procedure_entries() -> the 'user-built' rows for the Manager
    No function raises on a missing or damaged database / file: callers get None / [] / a result carrying problems.

AUTOMATION   datasheet_builder_match.match(ds, ...) -> MatchResult  (per-point assignment, uncovered list with reasons, TAR / TUR, overrides)
             datasheet_builder_match.driver_table() -> what each standard's driver can source / measure today
SPEC OUTPUT  datasheet_builder_specs.export_spec(ds, period=None, plan=None) -> ExportResult(spec, problems)   (kind 'manual-reading' + 'dsb')
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Optional

import appdata
import cmdreg

D = Decimal
SCHEMA = 'dsb-1'
PREC = 50
TAG = 'user-built'
HERE = Path(__file__).resolve().parent

# ============================================================================================================== problems / errors


class DsError(ValueError):
    """Raised by constructors / parsers for input that cannot be used.  .code says which rule."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ExprError(DsError):
    pass


class DsProblem(cmdreg.Problem):
    """A validation finding: str message, .code, .level ('error' | 'warn'), .where (path such as 'dcv/r10/dcv.r10.+5')."""
    level = 'error'
    where = ''

    def __new__(cls, code, message, level='error', where=''):
        obj = super().__new__(cls, code, message)
        obj.level, obj.where = level, where
        return obj


def errors(problems):
    return [p for p in problems if getattr(p, 'level', 'error') == 'error']


def warnings(problems):
    return [p for p in problems if getattr(p, 'level', 'error') == 'warn']


# ============================================================================================================== kinds / units
KINDS = {   # unit = SI base unit of the nominal / limits; legacy = the name the existing engines / specs use for the same test
    'DCV': dict(unit='V', name='DC volts', family='dmm', direction='measure', ac=False, switch='V⎓  (DC volts)'),
    'ACV': dict(unit='V', name='AC volts', family='dmm', direction='measure', ac=True, switch='V~  (AC volts)'),
    'DCI': dict(unit='A', name='DC current', family='dmm', direction='measure', ac=False, switch='A⎓  (DC current)'),
    'ACI': dict(unit='A', name='AC current', family='dmm', direction='measure', ac=True, switch='A~  (AC current)'),
    'OHM2': dict(unit='ohm', name='2-wire ohms', family='dmm', direction='measure', ac=False, switch='Ω  (2-wire resistance)'),
    'OHM4': dict(unit='ohm', name='4-wire ohms', family='dmm', direction='measure', ac=False, switch='Ω 4W  (4-wire resistance)'),
    'CAP': dict(unit='F', name='Capacitance', family='dmm', direction='measure', ac=False, switch='Capacitance'),
    'FREQ': dict(unit='Hz', name='Frequency', family='dmm', direction='measure', ac=False, value='frequency', amplitude=True, switch='Hz  (frequency)'),
    'PERIOD': dict(unit='s', name='Period', family='dmm', direction='measure', ac=False, value='period', amplitude=True, switch='Period'),
    'TEMP': dict(unit='degC', name='Temperature (simulated)', family='dmm', direction='measure', ac=False, switch='Temperature'),
    'DIODE': dict(unit='V', name='Diode test', family='dmm', direction='measure', ac=False, switch='Diode test'),
    'CONT': dict(unit='ohm', name='Continuity', family='dmm', direction='measure', ac=False, passfail=True, switch='Continuity'),
    # kinds the Cal Processor (.MDD) import needs (mdd_convert.py); they are also usable in the Datasheet Builder.  None of them has an automatic
    # source or measurement: they are run by typing the reading (the matcher finds no standard for them and the point is done by hand).
    'TEMPF': dict(unit='degF', name='Temperature (°F)', family='dmm', direction='measure', ac=False, switch='Temperature'),
    'COND': dict(unit='S', name='Conductance', family='dmm', direction='measure', ac=False, switch='nS  (conductance)'),
    'PCT': dict(unit='%', name='Percent reading (duty cycle ...)', family='dmm', direction='measure', ac=False, switch='%  (duty cycle)'),
    'CHECK': dict(unit='', name='Functional check (pass / fail)', family='dmm', direction='measure', ac=False, passfail=True, switch='Functional check'),
    'SCOPE_GAIN': dict(unit='V', name='Scope DC gain', family='scope', direction='measure', ac=False, legacy='GAIN', switch='Vertical (DC gain)'),
    'SCOPE_OFFSET': dict(unit='V', name='Scope DC offset', family='scope', direction='measure', ac=False, legacy='OFFSET', switch='Vertical (offset)'),
    'SCOPE_BW': dict(unit='dB', name='Scope bandwidth', family='scope', direction='measure', ac=True, amplitude=True, legacy='BW', switch='Bandwidth'),
    'SCOPE_TIMEBASE': dict(unit='s', name='Scope time base', family='scope', direction='measure', ac=False, value='period', amplitude=False,
                           legacy='TIMEBASE', switch='Horizontal (time base)'),
    'SCOPE_TRIGGER': dict(unit='', name='Scope trigger', family='scope', direction='measure', ac=True, amplitude=True, passfail=True, legacy='TRIG',
                          switch='Trigger'),
    'GEN_AMPL': dict(unit='V', name='Generator amplitude', family='generator', direction='source', ac=True, legacy='ACAMP / AFGAMP',
                     switch='Generator amplitude'),
    'GEN_FREQ': dict(unit='Hz', name='Generator frequency', family='generator', direction='source', ac=False, value='frequency', amplitude=True,
                     legacy='TIMEBASE / AFGFREQ', switch='Generator frequency'),
    'GEN_OFFSET': dict(unit='V', name='Generator DC offset', family='generator', direction='source', ac=False, legacy='AFGOFF',
                       switch='Generator offset'),
    'GEN_FLAT': dict(unit='dB', name='Generator flatness', family='generator', direction='source', ac=True, amplitude=True, legacy='FLAT / LFFLAT',
                     switch='Generator flatness'),
}
DIRECTIONS = ('measure', 'source')
PERIOD_PRESETS = [('24h', '24 hours'), ('90d', '90 days'), ('1y', '1 year'), ('2y', '2 years')]
_PREFIXES = {'p': -12, 'n': -9, 'µ': -6, 'μ': -6, 'u': -6, 'm': -3, '': 0, 'k': 3, 'M': 6, 'G': 9}
_PREFIX_ORDER = [('p', -12), ('n', -9), ('µ', -6), ('m', -3), ('', 0), ('k', 3), ('M', 6), ('G', 9)]
_NO_PREFIX = ('degC', 'degF', 'dB', '%', 'ratio', '')
_SYMBOL = {'ohm': 'Ω', 'degC': '°C', 'degF': '°F'}
_UNIT_ALIASES = [('S', 'S'), ('ohms', 'ohm'), ('ohm', 'ohm'), ('Ω', 'ohm'), ('Ω', 'ohm'), ('degC', 'degC'), ('°C', 'degC'), ('Hz', 'Hz'), ('hz', 'Hz'),
                 ('dB', 'dB'), ('db', 'dB'), ('sec', 's'), ('V', 'V'), ('A', 'A'), ('F', 'F'), ('s', 's'), ('C', 'degC'), ('degF', 'degF'), ('°F', 'degF'), ('%', '%')]


def kind_info(kind):
    try:
        return KINDS[kind]
    except KeyError:
        raise DsError('bad_kind', f'unknown function kind {kind!r}') from None


def unit_symbol(unit):
    return _SYMBOL.get(unit, unit)


def dec(x, what='value'):
    """Decimal from str / int / float (float via its shortest repr) / Decimal.  Rejects NaN, Infinity and anything unparsable (DsError 'number')."""
    try:
        if isinstance(x, Decimal):
            d = x
        elif isinstance(x, bool):
            raise InvalidOperation
        elif isinstance(x, float):
            d = Decimal(repr(x))
        elif isinstance(x, int):
            d = Decimal(x)
        else:
            d = Decimal(str(x).strip().replace(',', '').replace('−', '-'))
    except (InvalidOperation, ValueError, TypeError):
        raise DsError('number', f'{what}: {x!r} is not a number') from None
    if not d.is_finite():
        raise DsError('number', f'{what}: {x!r} is not a finite number')
    return d


def fmt(d):
    """Plain decimal text without exponent or trailing zeros ('0.0010' -> '0.001', 1E+3 -> '1000', -0 -> '0')."""
    if d is None:
        return ''
    d = dec(d)
    if d == 0:
        return '0'
    return format(d.normalize(), 'f')


def parse_quantity(text, unit=None):
    """'10 mV', '5 kΩ', '1.5uF', '250' -> Decimal in SI base units.  A bare number is taken in the base unit; a prefix with no unit symbol
    ('5 k') takes the expected `unit`.  When `unit` is given a different unit symbol is an error (DsError 'unit').  Never guesses a prefix."""
    if not isinstance(text, str):
        return dec(text)
    s = text.strip().replace('−', '-')
    m = re.match(r'^([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|[+-]?\.\d+)\s*(.*)$', s)
    if not m:
        raise DsError('number', f'{text!r} is not a quantity')
    value, rest = dec(m.group(1)), m.group(2).strip()
    if not rest:
        return value
    for alias, base in _UNIT_ALIASES:
        if rest.endswith(alias):
            prefix = rest[:-len(alias)].strip()
            if prefix in _PREFIXES and (prefix == '' or base not in _NO_PREFIX):
                if unit not in (None, '') and base != unit:
                    raise DsError('unit', f'{text!r} is in {base}, expected {unit}')
                with localcontext() as c:
                    c.prec = PREC
                    return value * D(10) ** _PREFIXES[prefix]
    if rest in _PREFIXES and unit not in (None, '') and unit not in _NO_PREFIX:
        with localcontext() as c:
            c.prec = PREC
            return value * D(10) ** _PREFIXES[rest]
    raise DsError('unit', f'{text!r}: cannot read the unit {rest!r}')


def best_prefix(value, unit):
    """(prefix symbol, exponent) so the displayed number is 1..999 (display only).  Units without prefixes keep ('', 0)."""
    if unit in _NO_PREFIX:
        return '', 0
    v = abs(dec(value))
    if v == 0:
        return '', 0
    pick = ('', 0)
    for sym, exp in _PREFIX_ORDER:
        if v >= D(10) ** exp:
            pick = (sym, exp)
    return pick


def format_si(value, unit, prefix=None, decimals=None):
    """Display text '5.000 V', '100 µA', '20 kΩ' (exact digits unless `decimals` is given).  `prefix` forces a prefix symbol."""
    v = dec(value)
    if prefix is None:
        prefix, exp = best_prefix(v, unit)
    else:
        exp = dict(_PREFIX_ORDER)[prefix]
    with localcontext() as c:
        c.prec = PREC
        shown = v / D(10) ** exp
    text = f'{shown:.{decimals}f}' if decimals is not None else fmt(shown)
    return f'{text} {prefix}{unit_symbol(unit)}'.rstrip()


def prefix_factor(prefix):
    return D(10) ** dict(_PREFIX_ORDER)[prefix]


def _q(d, places):
    return d.quantize(D(1).scaleb(-places))


# ============================================================================================================== expressions
@dataclass
class Ctx:
    """What an expression is evaluated against (SI): the reading (nominal), the range full scale, the display resolution, the frequency."""
    reading: Decimal
    full_scale: Optional[Decimal] = None
    resolution: Optional[Decimal] = None
    frequency: Optional[Decimal] = None


@dataclass(frozen=True)
class Tol:
    """A tolerance: how far below (minus) and above (plus) the nominal a reading may be.  Both >= 0."""
    minus: Decimal
    plus: Decimal

    @property
    def symmetric(self):
        return self.minus == self.plus

    def __add__(self, other):
        return Tol(self.minus + other.minus, self.plus + other.plus)


TERM_KINDS = ('pct_reading', 'pct_range', 'counts', 'abs', 'ppm_reading', 'ppm_range', 'db')


@dataclass
class Term:
    kind: str
    value: Decimal
    basis: str = 'amplitude'          # db only: 'amplitude' (20 log) or 'power' (10 log)

    def __post_init__(self):
        if self.kind not in TERM_KINDS:
            raise ExprError('bad_term', f'unknown term kind {self.kind!r}')
        self.value = dec(self.value, 'term value')
        if self.value < 0:
            raise ExprError('bad_value', 'a tolerance term cannot be negative (the sign is the +/- of the whole expression)')
        if self.kind == 'db' and self.basis not in ('amplitude', 'power'):
            raise ExprError('bad_term', "dB basis must be 'amplitude' or 'power'")

    def evaluate(self, ctx):
        with localcontext() as c:
            c.prec = PREC
            v, k = self.value, self.kind
            if k in ('pct_reading', 'ppm_reading', 'db') and ctx.reading is None:
                raise ExprError('missing_context', f'{k} needs the reading')
            if k == 'pct_reading':
                x = abs(ctx.reading) * v / 100
            elif k == 'ppm_reading':
                x = abs(ctx.reading) * v / 1000000
            elif k in ('pct_range', 'ppm_range'):
                if ctx.full_scale is None:
                    raise ExprError('missing_context', f'{k} needs the range full scale')
                x = abs(ctx.full_scale) * v / (100 if k == 'pct_range' else 1000000)
            elif k == 'counts':
                if ctx.resolution is None:
                    raise ExprError('missing_context', 'counts need the range resolution (value of one count)')
                x = v * ctx.resolution
            elif k == 'abs':
                x = v
            else:   # db
                div = D(20) if self.basis == 'amplitude' else D(10)
                up, down = D(10) ** (v / div), D(10) ** (-v / div)
                r = abs(ctx.reading)
                return Tol(r * (1 - down), r * (up - 1))
            return Tol(x, x)

    def text(self, unit=''):
        k, v = self.kind, fmt(self.value)
        if k == 'pct_reading':
            return f'{v} % of reading'
        if k == 'pct_range':
            return f'{v} % of range'
        if k == 'ppm_reading':
            return f'{v} ppm of reading'
        if k == 'ppm_range':
            return f'{v} ppm of range'
        if k == 'counts':
            return f'{v} count' + ('' if self.value == 1 else 's')
        if k == 'db':
            return f'{v} dB' + ('' if self.basis == 'amplitude' else ' (power)')
        return format_si(self.value, unit) if unit else v

    def to_dict(self):
        d = {'t': self.kind, 'v': fmt(self.value)}
        if self.kind == 'db' and self.basis != 'amplitude':
            d['basis'] = self.basis
        return d


@dataclass
class Expr:
    """sum / max / min of terms (and of nested Exprs).  `printed` keeps the manufacturer's wording for a human to compare."""
    op: str = 'sum'
    items: list = field(default_factory=list)
    printed: str = ''

    def __post_init__(self):
        if self.op not in ('sum', 'max', 'min'):
            raise ExprError('bad_op', f'unknown operation {self.op!r}')

    def evaluate(self, ctx):
        if not self.items:
            raise ExprError('empty', 'the expression has no terms')
        parts = [i.evaluate(ctx) for i in self.items]
        if self.op == 'sum':
            out = parts[0]
            for p in parts[1:]:
                out = out + p
            return out
        pick = max if self.op == 'max' else min
        return Tol(pick(p.minus for p in parts), pick(p.plus for p in parts))

    def body(self, unit=''):
        inner = [i.body(unit) if isinstance(i, Expr) else i.text(unit) for i in self.items]
        if self.op == 'sum':
            return ' + '.join(inner) if len(inner) == 1 or isinstance(self.items[0], Expr) else '(' + ' + '.join(inner) + ')'
        return f'{self.op}(' + ', '.join(inner) + ')'

    def text(self, unit=''):
        """Human form: '\u00b1(0.05 % of reading + 2 counts)', '\u00b1max(0.01 % of range, 50 \u00b5V)'."""
        return '\u00b1' + self.body(unit)

    def terms(self):
        for i in self.items:
            if isinstance(i, Expr):
                yield from i.terms()
            else:
                yield i

    def to_dict(self):
        d = {'op': self.op, 'items': [i.to_dict() for i in self.items]}
        if self.printed:
            d['printed'] = self.printed
        return d

    @classmethod
    def from_dict(cls, d, _depth=0):
        if _depth > 8 or not isinstance(d, dict):
            raise ExprError('bad_expr', 'expression is nested too deeply or is not an object')
        items = []
        for i in d.get('items', []):
            if not isinstance(i, dict):
                raise ExprError('bad_expr', 'expression item is not an object')
            items.append(cls.from_dict(i, _depth + 1) if 'op' in i else Term(i.get('t'), i.get('v'), i.get('basis', 'amplitude')))
        return cls(d.get('op', 'sum'), items, d.get('printed', ''))


def sum_of(*terms, printed=''):
    return Expr('sum', list(terms), printed)


_BASIS_REF = r'(?:of\s+)?(?:reading|rdg|input(?:\s+value)?|i\.?v\.?|iv|value)'
_BASIS_RNG = r'(?:of\s+)?(?:range|rng|full[\s-]*scale|f\.?s\.?|fs)'
_NUMRE = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


def _split_top(text, seps):
    out, depth, cur = [], 0, ''
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if depth == 0 and ch in seps:
            out.append(cur)
            cur = ''
            continue
        cur += ch
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def _split_plus(text):
    """Split on '+' that separates terms (not the sign of an exponent such as 1e+3 and not inside parentheses)."""
    out, depth, cur, i = [], 0, '', 0
    while i < len(text):
        ch = text[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == '+' and depth == 0 and not (cur and cur[-1] in 'eE' and cur[:-1].strip()[-1:].isdigit() and i + 1 < len(text) and text[i + 1].isdigit()):
            out.append(cur)
            cur = ''
        else:
            cur += ch
        i += 1
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def parse_expr(text, unit='', default_basis=None):
    """Parse the usual ways a specification is printed.  Examples (unit='V'):
         '0.05 % of reading + 0.01 % of range'      '±(0.5 % rdg + 3 digits)'     '0.0035 % iV + 2 counts'     '20 ppm + 0.5 mV'
         '10 uV'      '0.1 dB'      'max(0.01 %, 50 uV)' (basis from default_basis)      'min(...)'
       Bases: reading / rdg / input value / iV / i.v. ; range / full scale / FS.  Counts: count(s) digit(s) lsd cts.  A % or ppm with no basis
       needs default_basis ('reading' or 'range'), otherwise ExprError('ambiguous_basis').  A bare number needs a unit (ExprError
       'ambiguous_unit').  Nothing is guessed.  The input text is kept in Expr.printed."""
    if not isinstance(text, str) or not text.strip():
        raise ExprError('empty', 'the specification text is empty')
    raw = text.strip()
    expr = _parse(raw, unit, default_basis)
    expr.printed = raw
    return expr


def _parse(s, unit, default_basis):
    s = s.strip()
    s = re.sub(r'^(?:±|\+/-|\+-)\s*', '', s).strip()
    m = re.match(r'^(max|min)\s*\((.*)\)$', s, re.I | re.S)
    if m:
        return Expr(m.group(1).lower(), [_parse(p, unit, default_basis) for p in _split_top(m.group(2), ',;')])
    while s.startswith('(') and s.endswith(')') and len(_split_top(s[1:-1], '\x00')) == 1 and _balanced(s[1:-1]):
        s = s[1:-1].strip()
    parts = _split_plus(s)
    if len(parts) > 1:
        items = []
        for p in parts:
            sub = _parse(p, unit, default_basis)
            items.extend(sub.items if sub.op == 'sum' and not sub.printed else [sub])
        return Expr('sum', items)
    return Expr('sum', [_parse_term(parts[0] if parts else s, unit, default_basis)])


def _balanced(s):
    depth = 0
    for ch in s:
        depth += (ch == '(') - (ch == ')')
        if depth < 0:
            return False
    return depth == 0


def _parse_term(t, unit, default_basis):
    t = t.strip().replace('µ', 'u').replace('μ', 'u')
    m = re.match(rf'^({_NUMRE})\s*(%|ppm)\s*(?:{_BASIS_REF}|(?P<rng>{_BASIS_RNG}))?\s*$', t, re.I)
    if m:
        value, pct = m.group(1), m.group(2) == '%'
        has_basis = bool(re.search(r'[a-z]', t[m.end(2):], re.I))
        if re.match(rf'^{_NUMRE}\s*(?:%|ppm)\s*{_BASIS_RNG}\s*$', t, re.I) and has_basis:
            basis = 'range'
        elif has_basis:
            basis = 'reading'
        elif default_basis in ('reading', 'range'):
            basis = default_basis
        else:
            raise ExprError('ambiguous_basis', f'{t!r}: say of reading or of range (or give default_basis)')
        return Term(('pct_' if pct else 'ppm_') + basis, value)
    m = re.match(rf'^({_NUMRE})\s*(?:counts?|digits?|lsd|cts?|d)$', t, re.I)
    if m:
        return Term('counts', m.group(1))
    m = re.match(rf'^({_NUMRE})\s*dB(\s*\(?power\)?)?$', t, re.I)
    if m:
        if unit == 'dB':                       # the function's own unit is dB (flatness, bandwidth): a fixed +/- dB, not a ratio on the reading
            return Term('abs', m.group(1))
        return Term('db', m.group(1), 'power' if m.group(2) else 'amplitude')
    m = re.match(rf'^({_NUMRE})\s*(.*)$', t)
    if m:
        if not m.group(2).strip():
            raise ExprError('ambiguous_unit', f'{t!r}: a fixed term needs a unit (e.g. 0.5 mV)')
        try:
            return Term('abs', parse_quantity(t, unit or None))
        except DsError as e:
            raise ExprError(e.code, str(e)) from None
    raise ExprError('syntax', f'cannot read the specification term {t!r}')


# ============================================================================================================== model
@dataclass
class Period:
    id: str
    label: str = ''

    def to_dict(self):
        return {'id': self.id, 'label': self.label or self.id}


@dataclass
class Range:
    id: str
    full_scale: Decimal
    resolution: Optional[Decimal] = None     # value of one count in this range (SI)
    label: str = ''                          # as printed on the instrument ('20.0000 V'); '' = built from the full scale
    display_unit: str = ''                   # display only: prefix symbol ('m', 'k', 'µ', '') or '' = automatic
    max_input: Optional[Decimal] = None      # highest |input| the range accepts (over-range); None = full_scale
    unipolar: bool = False                   # True: negative values do not belong to this range
    settings: dict = field(default_factory=dict)

    def __post_init__(self):
        self.full_scale = dec(self.full_scale, 'full scale')
        self.resolution = None if self.resolution in (None, '') else dec(self.resolution, 'resolution')
        self.max_input = None if self.max_input in (None, '') else dec(self.max_input, 'max input')

    @property
    def top(self):
        return self.max_input if self.max_input is not None else self.full_scale

    def holds(self, value):
        v = dec(value)
        return (v >= 0 or not self.unipolar) and abs(v) <= self.top

    def to_dict(self):
        d = {'id': self.id, 'full_scale': fmt(self.full_scale), 'resolution': fmt(self.resolution) if self.resolution is not None else None,
             'label': self.label, 'display_unit': self.display_unit, 'max_input': fmt(self.max_input) if self.max_input is not None else None,
             'unipolar': self.unipolar}
        if self.settings:
            d['settings'] = dict(self.settings)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d['id'], d['full_scale'], d.get('resolution'), d.get('label', ''), d.get('display_unit', ''), d.get('max_input'),
                   bool(d.get('unipolar')), dict(d.get('settings') or {}))


MODES = ('both', 'low_only', 'high_only')


@dataclass
class SpecEntry:
    """One row of the specification table.  range_id None = every range; f_lo / f_hi None = no frequency restriction (inclusive bounds).
    exprs: {period id: Expr} (the plus side, or both sides); exprs_minus: optional different minus side; printed: {period id: text as printed}.
    mode low_only / high_only: a one-sided limit (e.g. bandwidth >= -3 dB); `bound` is the opposite bound a typed reading must stay within
    (needed because the handheld engine judges low <= reading <= high)."""
    exprs: dict = field(default_factory=dict)
    range_id: Optional[str] = None
    f_lo: Optional[Decimal] = None
    f_hi: Optional[Decimal] = None
    exprs_minus: dict = field(default_factory=dict)
    printed: dict = field(default_factory=dict)
    mode: str = 'both'
    bound: Optional[Decimal] = None
    note: str = ''

    def __post_init__(self):
        self.f_lo = None if self.f_lo in (None, '') else dec(self.f_lo, 'band start')
        self.f_hi = None if self.f_hi in (None, '') else dec(self.f_hi, 'band end')
        self.bound = None if self.bound in (None, '') else dec(self.bound, 'bound')
        if self.mode not in MODES:
            raise DsError('bad_mode', f'mode must be one of {MODES}')

    @property
    def score(self):
        return (2 if self.range_id is not None else 0) + (1 if (self.f_lo is not None or self.f_hi is not None) else 0)

    def matches(self, range_id, frequency):
        if self.range_id is not None and self.range_id != range_id:
            return False
        if self.f_lo is None and self.f_hi is None:
            return True
        if frequency is None:
            return False
        f = dec(frequency)
        return (self.f_lo is None or f >= self.f_lo) and (self.f_hi is None or f <= self.f_hi)

    def to_dict(self):
        return {'range_id': self.range_id, 'f_lo': fmt(self.f_lo) if self.f_lo is not None else None,
                'f_hi': fmt(self.f_hi) if self.f_hi is not None else None,
                'exprs': {k: v.to_dict() for k, v in self.exprs.items()}, 'exprs_minus': {k: v.to_dict() for k, v in self.exprs_minus.items()},
                'printed': dict(self.printed), 'mode': self.mode, 'bound': fmt(self.bound) if self.bound is not None else None, 'note': self.note}

    @classmethod
    def from_dict(cls, d):
        return cls({k: Expr.from_dict(v) for k, v in (d.get('exprs') or {}).items()}, d.get('range_id'), d.get('f_lo'), d.get('f_hi'),
                   {k: Expr.from_dict(v) for k, v in (d.get('exprs_minus') or {}).items()}, dict(d.get('printed') or {}), d.get('mode', 'both'),
                   d.get('bound'), d.get('note', ''))


@dataclass
class Point:
    id: str
    range_id: str
    nominal: Decimal
    frequency: Optional[Decimal] = None
    amplitude: Optional[Decimal] = None      # the stimulus level where it is not the nominal (FREQ, PERIOD, GEN_FREQ, SCOPE_BW ...), SI (V rms; scope Vpp)
    label: str = ''
    origin: str = 'user'                     # 'rule:<rule id>' or 'user'
    edited: bool = False
    enabled: bool = True
    settings: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)    # {period id: {'low': str|None, 'high': str|None}}  (SI strings)
    note: str = ''
    spec: Optional['SpecEntry'] = None       # this point's OWN specification (the datasheet grid's row tolerance); None = the function's spec table applies

    def __post_init__(self):
        self.nominal = dec(self.nominal, 'nominal')
        self.frequency = None if self.frequency in (None, '') else dec(self.frequency, 'frequency')
        self.amplitude = None if self.amplitude in (None, '') else dec(self.amplitude, 'amplitude')

    def to_dict(self):
        d = {'id': self.id, 'range_id': self.range_id, 'nominal': fmt(self.nominal),
             'frequency': fmt(self.frequency) if self.frequency is not None else None,
             'amplitude': fmt(self.amplitude) if self.amplitude is not None else None, 'label': self.label, 'origin': self.origin,
             'edited': self.edited, 'enabled': self.enabled, 'settings': dict(self.settings), 'overrides': copy.deepcopy(self.overrides), 'note': self.note}
        if self.spec is not None:                 # written only when set, so every file made before the datasheet grid is unchanged
            d['spec'] = self.spec.to_dict()
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d['id'], d['range_id'], d['nominal'], d.get('frequency'), d.get('amplitude'), d.get('label', ''), d.get('origin', 'user'),
                   bool(d.get('edited')), bool(d.get('enabled', True)), dict(d.get('settings') or {}), copy.deepcopy(d.get('overrides') or {}),
                   d.get('note', ''), SpecEntry.from_dict(d['spec']) if d.get('spec') else None)


RULE_TYPES = ('percent_of_range', 'zero_and_full', 'fixed', 'linear', 'log', 'decade_125', 'frequency_sweep')
FREQ_MODES = ('none', 'list', 'linear', 'log', 'bands')


@dataclass
class PointRule:
    """A calculator rule.  params by type:
         percent_of_range  {'percents': ['10','50','100'], 'bipolar': False, 'zero': False}             % of each range's full scale
         zero_and_full     {'bipolar': True}                                                             0, +FS (and -FS)
         fixed             {'values': ['1 mV', '5 V']}                                                   typed points (quantities)
         linear            {'start','stop','count'}  or  {'start','stop','step'}
         log               {'start','stop','count'}  or  {'start','stop','per_decade'}, 'sig': 3        significant digits kept
         decade_125        {'start','stop'}                                                              1-2-5 sequence
         frequency_sweep   {'nominal': '0'}                                                              one nominal, many frequencies (BW, flatness)
       frequencies: {'mode': 'list', 'values': [...]} | {'mode':'linear'|'log', 'start','stop','count'|'per_decade'} | {'mode':'bands','at':'edges'|'mid'|'both'}
       range_ids: restrict to these ranges (None = all, absolute values go to the smallest range that holds them).
       amplitude: the stimulus level stored on each point (FREQ, PERIOD, SCOPE_BW ...).  settings: copied to each point."""
    id: str
    type: str
    params: dict = field(default_factory=dict)
    frequencies: Optional[dict] = None
    range_ids: Optional[list] = None
    amplitude: Optional[str] = None
    settings: dict = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self):
        if self.type not in RULE_TYPES:
            raise DsError('rule_type', f'unknown rule type {self.type!r}')

    def to_dict(self):
        return {'id': self.id, 'type': self.type, 'params': copy.deepcopy(self.params), 'frequencies': copy.deepcopy(self.frequencies),
                'range_ids': list(self.range_ids) if self.range_ids is not None else None, 'amplitude': self.amplitude,
                'settings': dict(self.settings), 'enabled': self.enabled}

    @classmethod
    def from_dict(cls, d):
        return cls(d['id'], d['type'], copy.deepcopy(d.get('params') or {}), copy.deepcopy(d.get('frequencies')), d.get('range_ids'),
                   d.get('amplitude'), dict(d.get('settings') or {}), bool(d.get('enabled', True)))


@dataclass
class Limit:
    """The accept band of one point for one period (SI).  low / high None = open on that side (one-sided limit)."""
    nominal: Decimal
    low: Optional[Decimal]
    high: Optional[Decimal]
    minus: Optional[Decimal] = None
    plus: Optional[Decimal] = None
    source: str = 'spec'                 # 'spec' | 'override'
    ambiguous: bool = False              # two equally specific entries matched; the tighter one was used
    one_sided: bool = False
    bound_used: bool = False

    @property
    def symmetric(self):
        return self.minus is not None and self.minus == self.plus

    @property
    def tolerance(self):
        """Half the width of the accept band (what TAR / TUR use), or None for one-sided / missing limits."""
        if self.low is None or self.high is None or self.high <= self.low:
            return None
        return (self.high - self.low) / 2

    def accept_text(self, unit='', prefix=None):
        """'Accept if 4.9965 V <= reading <= 5.0035 V' (display-only scaling with one shared prefix; exact digits)."""
        sides = [x for x in (self.low, self.high) if x is not None]
        if prefix is None and sides:
            prefix = best_prefix(max(abs(x) for x in sides), unit)[0]

        def f(x):
            return format_si(x, unit, prefix=prefix)
        if self.low is not None and self.high is not None:
            return f'Accept if {f(self.low)} <= reading <= {f(self.high)}'
        if self.low is not None:
            return f'Accept if reading >= {f(self.low)}'
        if self.high is not None:
            return f'Accept if reading <= {f(self.high)}'
        return 'No limit'


@dataclass
class Function:
    id: str
    kind: str
    name: str = ''
    direction: str = 'measure'
    ranges: list = field(default_factory=list)
    spec: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    points: list = field(default_factory=list)
    display_unit: str = ''               # display prefix for this function ('' = automatic per range); display only
    switch: str = ''                     # text for the operator: what to select on the UUT
    settings: dict = field(default_factory=dict)    # function-wide: tc_type, waveform, load, terminal, ...
    settle: Optional[float] = None
    optional: bool = False
    notes: str = ''

    def __post_init__(self):
        info = kind_info(self.kind)
        self.name = self.name or info['name']
        if self.direction not in DIRECTIONS:
            raise DsError('bad_direction', f'direction must be one of {DIRECTIONS}')

    @property
    def info(self):
        return KINDS[self.kind]

    @property
    def unit(self):
        return self.info['unit']

    def range(self, range_id):
        return next((r for r in self.ranges if r.id == range_id), None)

    def point(self, point_id):
        return next((p for p in self.points if p.id == point_id), None)

    def add_range(self, full_scale, resolution=None, **kw):
        fs = dec(full_scale, 'full scale')
        rid = kw.pop('id', None) or 'r' + fmt(fs)
        if self.range(rid):
            raise DsError('dup_range', f'range {rid!r} already exists')
        rng = Range(rid, fs, resolution, **kw)
        self.ranges.append(rng)
        self.ranges.sort(key=lambda r: r.full_scale)
        return rng

    def add_spec(self, expr_by_period, range_id=None, f_lo=None, f_hi=None, **kw):
        """expr_by_period: {period: Expr | text} or a single Expr / text for every period of the datasheet (resolved at validate time via
        Datasheet.set_spec).  Returns the SpecEntry."""
        entry = SpecEntry({k: (v if isinstance(v, Expr) else parse_expr(v, self.unit)) for k, v in expr_by_period.items()}, range_id, f_lo, f_hi, **kw)
        self.spec.append(entry)
        return entry

    def add_rule(self, rule):
        if any(r.id == rule.id for r in self.rules):
            raise DsError('dup_rule', f'rule {rule.id!r} already exists')
        self.rules.append(rule)
        return rule

    def range_for(self, value):
        """The smallest range that holds |value| (None when none does)."""
        for r in sorted(self.ranges, key=lambda r: r.top):
            if r.holds(value):
                return r
        return None

    # ---- specification lookup and limits
    def spec_for(self, range_id, frequency=None):
        """(entries that match, the most specific ones).  Specificity: a range-specific entry beats a general one, a frequency band beats none."""
        hits = [e for e in self.spec if e.matches(range_id, frequency)]
        if not hits:
            return [], []
        top = max(e.score for e in hits)
        return hits, [e for e in hits if e.score == top]

    def governing(self, point):
        """The specification entries that decide `point`: its own (Point.spec, the grid's row tolerance) when it has one, else the most specific
        entries of the function's table ([] when none applies)."""
        if point.spec is not None:
            return [point.spec]
        return self.spec_for(point.range_id, point.frequency)[1]

    def limit_for(self, point, period, ds=None):
        """Limit of `point` for `period` (id).  A point override wins, then the point's own specification, then the function's table.  Raises
        DsError('no_spec' ...) when nothing applies (validate lists those first)."""
        rng = self.range(point.range_id)
        ov = point.overrides.get(period)
        rounding = (ds.options.get('limit_rounding', 'exact') if ds else 'exact')
        if ov and (ov.get('low') not in (None, '') or ov.get('high') not in (None, '')):
            low = dec(ov['low']) if ov.get('low') not in (None, '') else None
            high = dec(ov['high']) if ov.get('high') not in (None, '') else None
            return Limit(point.nominal, low, high, None if low is None else point.nominal - low, None if high is None else high - point.nominal,
                         'override', one_sided=low is None or high is None)
        ctx = Ctx(point.nominal, rng.full_scale if rng else None, rng.resolution if rng else None, point.frequency)
        tops = self.governing(point)
        if not tops:
            raise DsError('no_spec', f'{self.id}: no specification covers range {point.range_id!r} at frequency {fmt(point.frequency) if point.frequency is not None else "-"}')
        best = None
        for e in tops:
            if period not in e.exprs:
                raise DsError('spec_missing_period', f'{self.id}: a specification entry has no expression for period {period!r}')
            plus = e.exprs[period].evaluate(ctx)
            minus = e.exprs_minus[period].evaluate(ctx) if period in e.exprs_minus else plus
            tol = Tol(minus.minus, plus.plus)
            if best is None or (tol.minus + tol.plus) < (best[1].minus + best[1].plus):
                best = (e, tol)
        entry, tol = best
        low = point.nominal - tol.minus
        high = point.nominal + tol.plus
        bound_used = False
        if entry.mode == 'low_only':
            high = entry.bound
            bound_used = entry.bound is not None
        elif entry.mode == 'high_only':
            low = entry.bound
            bound_used = entry.bound is not None
        lim = Limit(point.nominal, low, high, tol.minus, tol.plus, 'spec', ambiguous=len(tops) > 1, one_sided=entry.mode != 'both',
                    bound_used=bound_used)
        if rounding == 'outward' and rng and rng.resolution:
            step = rng.resolution
            with localcontext() as c:
                c.prec = PREC
                if lim.low is not None:
                    lim.low = (lim.low / step).to_integral_value(ROUND_FLOOR) * step
                if lim.high is not None:
                    lim.high = (lim.high / step).to_integral_value(ROUND_CEILING) * step
        return lim

    def tol_text(self, point, period, ds=None):
        """Human check text such as '±(0.05 % of reading + 0.01 % of range) = ±3.5 mV' for the point's governing entry."""
        tops = self.governing(point)
        if not tops or period not in tops[0].exprs:
            return ''
        lim = self.limit_for(point, period, ds)
        e = tops[0]
        base = e.exprs[period].text(self.unit)
        if lim.symmetric:
            return f'{base} = ±{format_si(lim.plus, self.unit)}'
        return f'{base} = -{format_si(lim.minus, self.unit)} / +{format_si(lim.plus, self.unit)}'

    def to_dict(self):
        return {'id': self.id, 'kind': self.kind, 'name': self.name, 'direction': self.direction, 'display_unit': self.display_unit,
                'switch': self.switch, 'settings': dict(self.settings), 'settle': self.settle, 'optional': self.optional, 'notes': self.notes,
                'ranges': [r.to_dict() for r in self.ranges], 'spec': [e.to_dict() for e in self.spec],
                'rules': [r.to_dict() for r in self.rules], 'points': [p.to_dict() for p in self.points]}

    @classmethod
    def from_dict(cls, d):
        fn = cls(d['id'], d['kind'], d.get('name', ''), d.get('direction', KINDS.get(d['kind'], {}).get('direction', 'measure')),
                 display_unit=d.get('display_unit', ''), switch=d.get('switch', ''), settings=dict(d.get('settings') or {}),
                 settle=d.get('settle'), optional=bool(d.get('optional')), notes=d.get('notes', ''))
        fn.ranges = [Range.from_dict(r) for r in d.get('ranges', [])]
        fn.spec = [SpecEntry.from_dict(e) for e in d.get('spec', [])]
        fn.rules = [PointRule.from_dict(r) for r in d.get('rules', [])]
        fn.points = [Point.from_dict(p) for p in d.get('points', [])]
        return fn


@dataclass
class Datasheet:
    make: str = ''
    model: str = ''
    title: str = ''
    version: int = 0                         # the saved version (set by save(); 0 = never saved)
    notes: str = ''
    functions: list = field(default_factory=list)
    periods: list = field(default_factory=lambda: [Period('1y', '1 year')])
    default_period: str = '1y'
    revision: str = ''                       # free text label of the datasheet itself ('Rev B', 'manual 2024-05')
    options: dict = field(default_factory=dict)      # limit_rounding, hv_threshold_v, auto_ramp, function_prompt, ...
    assignments: dict = field(default_factory=dict)  # {point id: standard model}: the person's overrides of the automatic choice
    source: dict = field(default_factory=dict)       # document / pages / note (shown in the spec 'source')
    uid: str = ''
    created: str = ''

    def function(self, function_id):
        return next((f for f in self.functions if f.id == function_id), None)

    def add_function(self, kind, name='', direction=None, id=None, **kw):
        info = kind_info(kind)
        if id is None:
            base, n = kind.lower(), 1
            id = base
            while self.function(id):
                n += 1
                id = f'{base}{n}'
        if self.function(id):
            raise DsError('dup_function', f'function {id!r} already exists')
        fn = Function(id, kind, name, direction or info['direction'], **kw)
        self.functions.append(fn)
        return fn

    def set_periods(self, periods, default=None):
        self.periods = [p if isinstance(p, Period) else Period(*p) if isinstance(p, tuple) else Period(p, dict(PERIOD_PRESETS).get(p, p)) for p in periods]
        self.default_period = default or self.periods[0].id

    def period_ids(self):
        return [p.id for p in self.periods]

    def all_points(self):
        for fn in self.functions:
            for p in fn.points:
                yield fn, p

    def set_spec(self, fn, expr_text, range_id=None, f_lo=None, f_hi=None, default_basis=None, **kw):
        """Add a specification entry that applies the same text to every period of this datasheet (typical for one-period sheets);
        pass a dict {period: text} for per-period wording.  Returns the SpecEntry."""
        texts = expr_text if isinstance(expr_text, dict) else {p: expr_text for p in self.period_ids()}
        exprs = {k: (v if isinstance(v, Expr) else parse_expr(v, fn.unit, default_basis)) for k, v in texts.items()}
        entry = SpecEntry(exprs, range_id, f_lo, f_hi, printed={k: (v if isinstance(v, str) else '') for k, v in texts.items()}, **kw)
        fn.spec.append(entry)
        return entry

    def to_dict(self):
        return {'schema': SCHEMA, 'uid': self.uid, 'make': self.make, 'model': self.model, 'title': self.title, 'version': self.version,
                'revision': self.revision, 'notes': self.notes, 'created': self.created, 'source': dict(self.source),
                'periods': [p.to_dict() for p in self.periods], 'default_period': self.default_period, 'options': copy.deepcopy(self.options),
                'assignments': dict(self.assignments), 'functions': [f.to_dict() for f in self.functions]}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or d.get('schema') != SCHEMA:
            raise DsError('schema', f'not a datasheet ({SCHEMA}) file')
        try:
            ds = cls(d.get('make', ''), d.get('model', ''), d.get('title', ''), int(d.get('version') or 0), d.get('notes', ''), [],
                     [Period(p['id'], p.get('label', '')) for p in d.get('periods', [])], d.get('default_period', ''), d.get('revision', ''),
                     copy.deepcopy(d.get('options') or {}), dict(d.get('assignments') or {}), dict(d.get('source') or {}), d.get('uid', ''),
                     d.get('created', ''))
            ds.functions = [Function.from_dict(f) for f in d.get('functions', [])]
        except DsError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise DsError('format', f'the datasheet file is damaged ({type(e).__name__}: {e})') from None
        return ds

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=True, sort_keys=False)

    @classmethod
    def from_json(cls, text):
        try:
            return cls.from_dict(json.loads(text))
        except json.JSONDecodeError as e:
            raise DsError('format', f'not valid JSON ({e})') from None

    def copy(self):
        return Datasheet.from_dict(copy.deepcopy(self.to_dict()))


# ============================================================================================================== calculator
def point_id(function_id, range_id, nominal, frequency=None, amplitude=None, uses_amplitude=False):
    """Deterministic id from the quantities, e.g. 'dcv.r10.+5', 'acv.r10.+5@1000', 'freq.r1.+10~0.1'.  Characters: letters digits . + - @ ~ _"""
    n = dec(nominal)
    s = f'{function_id}.{range_id}.{"+" if n >= 0 else ""}{fmt(n)}'
    if frequency is not None:
        s += '@' + fmt(frequency)
    if uses_amplitude and amplitude is not None:
        s += '~' + fmt(amplitude)
    return s


def _uses_amp(fn):
    return bool(fn.info.get('amplitude'))


def _sig(d, digits):
    if d == 0:
        return d
    with localcontext() as c:
        c.prec = PREC
        exp = d.adjusted() - digits + 1
        return d.quantize(D(1).scaleb(exp)) if exp <= 0 else d.quantize(D(1))


def _steps_linear(start, stop, count=None, step=None):
    start, stop = dec(start, 'start'), dec(stop, 'stop')
    if stop < start:
        raise DsError('rule_params', 'stop is below start')
    with localcontext() as c:
        c.prec = PREC
        if step is not None:
            st = dec(step, 'step')
            if st <= 0:
                raise DsError('rule_params', 'step must be positive')
            out, v = [], start
            while v <= stop:
                out.append(v)
                v += st
                if len(out) > 10000:
                    raise DsError('rule_params', 'more than 10000 points')
            return out
        n = int(count or 0)
        if n < 2:
            raise DsError('rule_params', 'linear needs count >= 2 (or a step)')
        return [start + (stop - start) * i / (n - 1) for i in range(n)]


def _steps_log(start, stop, count=None, per_decade=None, sig=3):
    start, stop = dec(start, 'start'), dec(stop, 'stop')
    if start <= 0 or stop <= start:
        raise DsError('rule_params', 'log needs 0 < start < stop')
    with localcontext() as c:
        c.prec = PREC
        if per_decade:
            pd = int(per_decade)
            n = int(math.ceil(float((stop / start).log10()) * pd - 1e-9)) + 1
        else:
            n = int(count or 0)
        if n < 2 or n > 10000:
            raise DsError('rule_params', 'log needs count >= 2 (or per_decade)')
        l0, l1 = start.log10(), stop.log10()
        out = []
        for i in range(n):
            if per_decade:
                v = D(10) ** (l0 + D(i) / int(per_decade))
            else:
                v = D(10) ** (l0 + (l1 - l0) * i / (n - 1))
            v = _sig(v, int(sig))
            out.append(min(v, stop))
        if per_decade:
            if out[-1] < stop:
                out.append(stop)
        else:
            out[-1] = stop
        out[0] = start
    return out


def _steps_125(start, stop):
    start, stop = dec(start, 'start'), dec(stop, 'stop')
    if start <= 0 or stop < start:
        raise DsError('rule_params', 'decade_125 needs 0 < start <= stop')
    out = []
    for d in range(start.adjusted() - 1, stop.adjusted() + 2):
        for m in (1, 2, 5):
            v = D(m).scaleb(d)
            if start <= v <= stop:
                out.append(v)
    return out


def _freq_values(fn, rule, rng):
    spec = rule.frequencies
    if not spec or spec.get('mode', 'none') == 'none':
        return [None]
    mode = spec['mode']
    if mode not in FREQ_MODES:
        raise DsError('rule_frequency', f'unknown frequency mode {mode!r}')
    if mode == 'list':
        vals = [parse_quantity(v, 'Hz') for v in spec.get('values', [])]
    elif mode == 'linear':
        vals = _steps_linear(parse_quantity(spec['start'], 'Hz'), parse_quantity(spec['stop'], 'Hz'), spec.get('count'), spec.get('step'))
    elif mode == 'log':
        vals = _steps_log(parse_quantity(spec['start'], 'Hz'), parse_quantity(spec['stop'], 'Hz'), spec.get('count'), spec.get('per_decade'),
                          spec.get('sig', 3))
    else:   # bands: edges / geometric mid of the specification bands that apply to this range
        at = spec.get('at', 'edges')
        if at not in ('edges', 'mid', 'both'):
            raise DsError('rule_frequency', "bands 'at' must be edges, mid or both")
        vals = []
        for e in fn.spec:
            if e.range_id not in (None, rng.id if rng else None) or e.f_lo is None or e.f_hi is None:
                continue
            if at in ('edges', 'both'):
                vals += [v for v in (e.f_lo, e.f_hi) if v > 0]
            if at in ('mid', 'both') and e.f_lo > 0:
                with localcontext() as c:
                    c.prec = PREC
                    vals.append(_sig((e.f_lo * e.f_hi).sqrt(), 3))
    vals = sorted(set(vals))
    if not vals:
        raise DsError('rule_frequency', 'the frequency rule produced no frequencies')
    return vals


def _percent_values(params, rng):
    out = []
    pcts = [dec(p, 'percent') for p in params.get('percents', [])]
    if params.get('zero'):
        out.append(D(0))
    with localcontext() as c:
        c.prec = PREC
        for p in pcts:
            v = rng.full_scale * p / 100
            out.append(v)
            if params.get('bipolar') and not rng.unipolar and v != 0:
                out.append(-v)
    return out


def _abs_values(rule):
    p, t = rule.params, rule.type
    if t == 'fixed':
        return [parse_quantity(v, None) for v in p.get('values', [])]
    if t == 'linear':
        return _steps_linear(parse_quantity(p['start']), parse_quantity(p['stop']), p.get('count'), p.get('step'))
    if t == 'log':
        return _steps_log(parse_quantity(p['start']), parse_quantity(p['stop']), p.get('count'), p.get('per_decade'), p.get('sig', 3))
    if t == 'decade_125':
        return _steps_125(parse_quantity(p['start']), parse_quantity(p['stop']))
    raise DsError('rule_type', f'{t} is not an absolute-value rule')


@dataclass
class RegenReport:
    added: list = field(default_factory=list)       # point ids
    kept: list = field(default_factory=list)       # generated points that already existed (and were not edited)
    removed: list = field(default_factory=list)     # rule points no longer produced by any rule (and not edited)
    skipped: list = field(default_factory=list)     # [(value text, reason)] values no range could hold
    orphaned: list = field(default_factory=list)    # edited rule points no rule produces any more (kept as manual points)


def generate_points(fn, rule):
    """Points one rule produces for function `fn` ([Point], unsorted, may hold duplicates) and [(text, reason)] skipped values."""
    if not fn.ranges:
        raise DsError('no_ranges', f'{fn.id}: define the ranges before generating points')
    ranges = [r for r in fn.ranges if rule.range_ids is None or r.id in rule.range_ids]
    if rule.range_ids is not None:
        unknown = [i for i in rule.range_ids if not fn.range(i)]
        if unknown:
            raise DsError('rule_ranges', f'rule {rule.id}: unknown range(s) {unknown}')
    amp = parse_quantity(rule.amplitude) if rule.amplitude not in (None, '') else None
    info = fn.info
    if info.get('ac') and not (rule.frequencies and rule.frequencies.get('mode', 'none') != 'none'):
        raise DsError('rule_frequency', f'rule {rule.id}: {fn.kind} points need a frequency rule')
    pairs, skipped = [], []     # (value, range)
    if rule.type == 'frequency_sweep':
        nominal = parse_quantity(rule.params.get('nominal', '0'))
        for rng in ranges[:1]:
            pairs.append((nominal, rng))
    elif rule.type in ('percent_of_range', 'zero_and_full'):
        for rng in ranges:
            if rule.type == 'zero_and_full':
                vals = [D(0), rng.full_scale] + ([-rng.full_scale] if rule.params.get('bipolar', True) and not rng.unipolar else [])
            else:
                vals = _percent_values(rule.params, rng)
            pairs += [(v, rng) for v in vals]
    else:
        pool = sorted(ranges, key=lambda r: r.top)
        for v in _abs_values(rule):
            rng = next((r for r in pool if r.holds(v)), None)
            if rng is None:
                skipped.append((fmt(v), 'outside_ranges'))
            else:
                pairs.append((v, rng))
    out = []
    for v, rng in pairs:
        for f in _freq_values(fn, rule, rng):
            out.append(Point(point_id(fn.id, rng.id, v, f, amp, _uses_amp(fn)), rng.id, v, f, amp, origin='rule:' + rule.id, settings=dict(rule.settings)))
    return out, skipped


def sort_points(fn):
    """Order: range (ascending), nominal (ascending), frequency (ascending)."""
    order = {r.id: i for i, r in enumerate(sorted(fn.ranges, key=lambda r: r.full_scale))}
    fn.points.sort(key=lambda p: (order.get(p.range_id, 1 << 30), p.nominal, p.frequency if p.frequency is not None else D(-1), p.id))


def regenerate(fn):
    """Apply the function's enabled rules.  New rule points are added; a rule point no rule produces any more is removed unless the person edited
    it (then it is kept as a manual point); manual and edited points are never touched.  Duplicates are merged on the point id.  Returns RegenReport."""
    rep = RegenReport()
    produced = {}
    for rule in fn.rules:
        if not rule.enabled:
            continue
        pts, skipped = generate_points(fn, rule)
        rep.skipped += skipped
        for p in pts:
            produced.setdefault(p.id, p)
    existing = {p.id: p for p in fn.points}
    for pid, p in produced.items():
        if pid in existing:
            if not existing[pid].edited and existing[pid].origin.startswith('rule:'):
                rep.kept.append(pid)
        else:
            fn.points.append(p)
            rep.added.append(pid)
    for p in list(fn.points):
        if p.origin.startswith('rule:') and p.id not in produced:
            if p.edited:
                p.origin = 'user'
                rep.orphaned.append(p.id)
            else:
                fn.points.remove(p)
                rep.removed.append(p.id)
    sort_points(fn)
    return rep


def add_point(fn, nominal, range_id=None, frequency=None, amplitude=None, **kw):
    """A hand-made point.  The range defaults to the smallest that holds the value (DsError 'no_range' when none does - nothing is guessed)."""
    n = parse_quantity(nominal, fn.unit or None) if isinstance(nominal, str) else dec(nominal)
    rng = fn.range(range_id) if range_id else fn.range_for(n)
    if rng is None:
        raise DsError('no_range', f'no range holds {fmt(n)} {fn.unit}' if not range_id else f'unknown range {range_id!r}')
    f = parse_quantity(frequency, 'Hz') if isinstance(frequency, str) else frequency
    a = parse_quantity(amplitude) if isinstance(amplitude, str) else amplitude
    pid = point_id(fn.id, rng.id, n, None if f is None else dec(f), None if a is None else dec(a), _uses_amp(fn))
    if fn.point(pid):
        raise DsError('dup_point', f'point {pid} already exists')
    p = Point(pid, rng.id, n, f, a, origin='user', edited=True, **kw)
    fn.points.append(p)
    sort_points(fn)
    return p


def edit_point(fn, pid, **changes):
    """Change fields of a point (nominal, frequency, amplitude, label, enabled, settings, note, range_id).  The id never changes."""
    p = fn.point(pid)
    if p is None:
        raise DsError('no_point', f'no point {pid!r}')
    for k, v in changes.items():
        if k not in ('nominal', 'frequency', 'amplitude', 'label', 'enabled', 'settings', 'note', 'range_id'):
            raise DsError('bad_field', f'point field {k!r} cannot be edited')
        if k == 'nominal':
            v = dec(v) if not isinstance(v, str) else parse_quantity(v, fn.unit or None)
        elif k in ('frequency', 'amplitude'):
            v = None if v in (None, '') else (parse_quantity(v) if isinstance(v, str) else dec(v))
        setattr(p, k, v)
    p.edited = True
    sort_points(fn)
    return p


def remove_point(fn, pid):
    p = fn.point(pid)
    if p is None:
        raise DsError('no_point', f'no point {pid!r}')
    fn.points.remove(p)


def set_override(fn, pid, period, low=None, high=None):
    """Type the limits of one point for one period (SI numbers or quantities).  Either side may stay None (open)."""
    p = fn.point(pid)
    if p is None:
        raise DsError('no_point', f'no point {pid!r}')
    lo = None if low in (None, '') else dec(parse_quantity(low, fn.unit or None) if isinstance(low, str) else low)
    hi = None if high in (None, '') else dec(parse_quantity(high, fn.unit or None) if isinstance(high, str) else high)
    p.overrides[period] = {'low': None if lo is None else fmt(lo), 'high': None if hi is None else fmt(hi)}
    p.edited = True


def clear_override(fn, pid, period=None):
    p = fn.point(pid)
    if p is None:
        raise DsError('no_point', f'no point {pid!r}')
    if period is None:
        p.overrides.clear()
    else:
        p.overrides.pop(period, None)


def point_limits(ds, fn, point, period=None):
    """dict(low, high, nominal, minus, plus, accept, tol_text, source, ambiguous) for the editor / preview, SI values as Decimal; error text in 'error'."""
    period = period or ds.default_period
    try:
        lim = fn.limit_for(point, period, ds)
    except DsError as e:
        return {'error': str(e), 'code': e.code}
    return dict(low=lim.low, high=lim.high, nominal=lim.nominal, minus=lim.minus, plus=lim.plus, accept=lim.accept_text(fn.unit),
                tol_text=fn.tol_text(point, period, ds), source=lim.source, ambiguous=lim.ambiguous, one_sided=lim.one_sided)


# ============================================================================================================== validation
_ID = re.compile(r'^[A-Za-z0-9_]+$')
_PID = re.compile(r'^[A-Za-z0-9_.+\-@~]+$')


def validate(ds):
    """Problems in a datasheet.  Pure and read-only: nothing is corrected, nothing is guessed."""
    out = []

    def add(code, msg, level='error', where=''):
        out.append(DsProblem(code, msg, level, where))

    if not ds.make.strip():
        add('no_make', 'The make is empty.', where='datasheet')
    if not ds.model.strip():
        add('no_model', 'The model is empty.', where='datasheet')
    if not ds.title.strip():
        add('no_title', 'The title is empty.', 'warn', 'datasheet')
    pids = ds.period_ids()
    if not pids:
        add('no_periods', 'Define at least one time period.', where='datasheet')
    if len(set(pids)) != len(pids):
        add('dup_period', 'Two time periods have the same id.', where='datasheet')
    for p in ds.periods:
        if not _ID.match(p.id or ''):
            add('bad_period', f'Period id {p.id!r} may only contain letters, digits and _.', where='datasheet')
    if pids and ds.default_period not in pids:
        add('default_period', f'The default period {ds.default_period!r} is not one of {pids}.', where='datasheet')
    if ds.options.get('limit_rounding', 'exact') not in ('exact', 'outward'):
        add('limit_rounding', "options.limit_rounding must be 'exact' or 'outward'.", where='datasheet')
    if not ds.functions:
        add('no_functions', 'The datasheet has no functions.', where='datasheet')
    seen_f = set()
    all_ids = {}
    for fn in ds.functions:
        _validate_function(ds, fn, add, seen_f, all_ids)
    if ds.functions and not any(p.enabled for fn in ds.functions for p in fn.points):
        # empty sections are only warnings (the run skips them), but a sheet with no test row at all has nothing to run
        add('no_test_rows', 'The datasheet has no test rows yet.', where='datasheet')
    for pid, model in ds.assignments.items():
        if pid not in all_ids:
            add('assignment_unknown_point', f'The standard assignment for {pid!r} names a point that does not exist.', 'warn', 'datasheet')
    return out


def _validate_function(ds, fn, add, seen_f, all_ids):
    w = fn.id
    if fn.id in seen_f or not _ID.match(fn.id or ''):
        add('dup_function' if fn.id in seen_f else 'bad_id', f'Function id {fn.id!r} is duplicated or has characters other than letters, digits and _.', where=w)
    seen_f.add(fn.id)
    info = KINDS.get(fn.kind)
    if info is None:
        add('bad_kind', f'Unknown function kind {fn.kind!r}.', where=w)
        return
    if fn.direction not in DIRECTIONS:
        add('bad_direction', f'Direction {fn.direction!r} is not measure or source.', where=w)
    elif info['family'] == 'generator' and fn.direction != 'source':
        add('bad_direction', f'{fn.kind} is a generator function: its direction must be source (the standard measures).', where=w)
    elif info['family'] == 'scope' and fn.direction != 'measure':
        add('bad_direction', f'{fn.kind} is a scope function: its direction must be measure (the scope measures a sourced signal).', where=w)
    if fn.display_unit and fn.display_unit not in dict(_PREFIX_ORDER) and fn.display_unit not in ('', ):
        add('unit_mismatch', f'Display prefix {fn.display_unit!r} is not an SI prefix.', where=w)
    if fn.display_unit and info['unit'] in _NO_PREFIX and fn.display_unit not in ('',):
        add('unit_mismatch', f'{info["unit"] or "this function"} is shown without an SI prefix.', where=w)
    if not fn.ranges:
        # a section with no rows yet (a template, or a section still to be filled) is only a warning: the run skips it
        add('no_ranges', f'{fn.name}: no ranges defined.', 'warn' if not fn.points else 'error', w)
    seen_r = set()
    prev = None
    for rng in fn.ranges:
        rw = f'{w}/{rng.id}'
        if rng.id in seen_r:
            add('dup_range', f'Range id {rng.id!r} is used twice.', where=rw)
        seen_r.add(rng.id)
        if not _PID.match(rng.id or ''):
            add('bad_id', f'Range id {rng.id!r} has characters that are not allowed.', where=rw)
        if rng.full_scale <= 0:
            add('range_value', 'The full scale must be above zero.', where=rw)
        if prev is not None and rng.full_scale <= prev:
            add('range_order', f'Ranges must ascend: {fmt(rng.full_scale)} follows {fmt(prev)}.', where=rw)
        prev = rng.full_scale
        if rng.resolution is not None and (rng.resolution <= 0 or rng.resolution > rng.full_scale):
            add('range_resolution', 'The resolution must be above zero and not larger than the full scale.', where=rw)
        if rng.max_input is not None and rng.max_input < rng.full_scale:
            add('range_value', 'The maximum input is below the full scale.', where=rw)
        if rng.display_unit and (rng.display_unit not in dict(_PREFIX_ORDER) or info['unit'] in _NO_PREFIX):
            add('unit_mismatch', f'Range display prefix {rng.display_unit!r} does not fit {info["unit"] or "this function"}.', where=rw)
    # specification table
    periods = ds.period_ids()
    if not info.get('passfail') and not fn.spec:
        # a function with no table is fine when every enabled point carries its own specification or typed limits (the datasheet grid)
        bare = [p for p in fn.points if p.enabled and p.spec is None and not all(any(v not in (None, '') for v in (p.overrides.get(per) or {}).values()) for per in periods)]
        if bare or not fn.points:
            add('no_spec', f'{fn.name}: no specification entered, so no limits can be calculated.', 'warn' if not fn.points else 'error', w)
    for i, e in enumerate(fn.spec):
        ew = f'{w}/spec{i + 1}'
        if e.range_id is not None and fn.range(e.range_id) is None:
            add('spec_range_unknown', f'Specification entry {i + 1} names range {e.range_id!r}, which does not exist.', where=ew)
        if e.f_lo is not None and e.f_hi is not None and e.f_lo > e.f_hi:
            add('spec_band_inverted', f'Specification entry {i + 1}: the frequency band starts above where it ends.', where=ew)
        if (e.f_lo is not None or e.f_hi is not None) and not info.get('ac') and info['family'] != 'generator' and not info.get('value'):
            add('freq_not_allowed', f'Specification entry {i + 1} has a frequency band but {fn.kind} has no frequency.', 'warn', ew)
        for p in periods:
            if p not in e.exprs:
                add('spec_missing_period', f'Specification entry {i + 1} has no expression for period {p!r}.', where=ew)
        for p in list(e.exprs) + list(e.exprs_minus):
            if p not in periods:
                add('spec_period_unknown', f'Specification entry {i + 1} has an expression for period {p!r}, which the datasheet does not define.', 'warn', ew)
        for p, ex in list(e.exprs.items()) + list(e.exprs_minus.items()):
            for t in ex.terms() if isinstance(ex, Expr) else []:
                if t.kind == 'counts' and not any(r.resolution for r in fn.ranges if e.range_id in (None, r.id)):
                    add('expr_context', f'Specification entry {i + 1} uses counts but no range has a resolution.', where=ew)
                if t.kind in ('pct_range', 'ppm_range') and not fn.ranges:
                    add('expr_context', f'Specification entry {i + 1} uses a percentage of range but there are no ranges.', where=ew)
                if t.kind == 'abs' and info['unit'] == '':
                    add('unit_mismatch', f'Specification entry {i + 1}: a fixed term has no unit in a pass / fail function.', where=ew)
        if e.mode != 'both' and e.bound is None:
            add('one_sided_needs_bound', f'Specification entry {i + 1} is one-sided; the runnable spec also needs the opposite bound for the typed reading.', 'warn', ew)
    seen_p, seen_q = set(), {}
    if not fn.points:
        add('no_points', f'{fn.name}: no test points yet.', 'warn', w)
    for p in fn.points:
        pw = f'{w}/{p.range_id}/{p.id}'
        if p.id in seen_p or p.id in all_ids:
            add('dup_point_id', f'Point id {p.id!r} is used twice.', where=pw)
        seen_p.add(p.id)
        all_ids[p.id] = fn.id
        if not _PID.match(p.id or ''):
            add('bad_id', f'Point id {p.id!r} has characters that are not allowed.', where=pw)
        rng = fn.range(p.range_id)
        if rng is None:
            add('point_range_unknown', f'Point {p.id} names range {p.range_id!r}, which does not exist.', where=pw)
        elif not rng.holds(p.nominal) and not info.get('value') and info['unit'] not in ('dB', ''):
            add('point_outside_range', f'Point {p.id}: {fmt(p.nominal)} {info["unit"]} is outside range {rng.id} (limit {fmt(rng.top)}).', where=pw)
        elif rng is not None and info.get('value') and not (0 < abs(p.nominal) <= rng.top):
            add('point_outside_range', f'Point {p.id}: {fmt(p.nominal)} is outside range {rng.id} (limit {fmt(rng.top)}).', where=pw)
        manual = bool(ds.options.get('manual_entry')) and info['family'] == 'dmm'      # a manual calibration: nothing is sourced, so a missing frequency / amplitude is only a warning
        if info.get('ac') and (p.frequency is None or p.frequency <= 0):
            add('no_frequency', f'Point {p.id}: {fn.kind} needs a frequency above zero.', 'warn' if manual else 'error', pw)
        if not info.get('ac') and p.frequency is not None and not info.get('value') and info['family'] != 'generator':
            add('freq_not_allowed', f'Point {p.id}: {fn.kind} has no frequency, but one is set.', 'warn', pw)
        if info.get('amplitude') and (p.amplitude is None or p.amplitude <= 0) and fn.kind not in ('SCOPE_TIMEBASE', 'GEN_FREQ'):
            add('no_amplitude', f'Point {p.id}: {fn.kind} needs the stimulus amplitude.', 'warn' if manual else 'error', pw)
        if info.get('value') in ('frequency', 'period') and p.nominal <= 0:
            add('point_outside_range', f'Point {p.id}: a {info["value"]} must be above zero.', where=pw)
        key = (p.range_id, fmt(p.nominal), fmt(p.frequency) if p.frequency is not None else None, fmt(p.amplitude) if p.amplitude is not None else None,
               json.dumps(p.settings, sort_keys=True))
        if key in seen_q and seen_q[key] != p.id:
            add('dup_point', f'Points {seen_q[key]} and {p.id} are the same test.', 'warn', pw)
        seen_q[key] = p.id
        if info.get('passfail') or not p.enabled:
            continue
        for per in periods:
            _validate_limit(ds, fn, p, per, add, pw)
        for per in p.overrides:
            if per not in periods:
                add('override_period', f'Point {p.id}: a typed limit exists for period {per!r}, which the datasheet does not define.', 'warn', pw)
    for rule in fn.rules:
        try:
            if rule.enabled and fn.ranges:
                generate_points(fn, rule)
        except DsError as e:
            add('rule_' + e.code if not e.code.startswith('rule') else e.code, f'Rule {rule.id}: {e}', where=f'{w}/rule/{rule.id}')


def _validate_limit(ds, fn, p, per, add, pw):
    try:
        lim = fn.limit_for(p, per, ds)
    except DsError as e:
        add('expr_eval' if e.code in ('missing_context', 'empty', 'bad_expr') else e.code if e.code in ('no_spec', 'spec_missing_period') else 'expr_eval',
            f'Point {p.id} [{per}]: {e}', where=pw)
        return
    if lim.low is not None and lim.high is not None and lim.low > lim.high:
        add('limit_inverted', f'Point {p.id} [{per}]: the low limit {fmt(lim.low)} is above the high limit {fmt(lim.high)}.', where=pw)
    for side in (lim.low, lim.high):
        if side is not None and side != side.to_integral_value() and side.adjusted() < -30:
            add('limit_value', f'Point {p.id} [{per}]: a limit is not a usable number.', where=pw)
    if lim.source == 'override':
        ov = p.overrides.get(per, {})
        if ov.get('low') not in (None, '') and ov.get('high') not in (None, '') and dec(ov['low']) > dec(ov['high']):
            add('override_inverted', f'Point {p.id} [{per}]: the typed low limit is above the typed high limit.', where=pw)
    if lim.low is not None and lim.high is not None and not (lim.low <= p.nominal <= lim.high) and not lim.one_sided:
        add('nominal_outside_limit', f'Point {p.id} [{per}]: the nominal is outside its own limits.', 'warn', pw)
    if lim.ambiguous:
        add('spec_border', f'Point {p.id} [{per}]: two specification entries apply equally (a range or band border); the tighter one is used.', 'warn', pw)
    if lim.one_sided and not lim.bound_used and lim.source == 'spec':
        add('one_sided_needs_bound', f'Point {p.id} [{per}]: one-sided limit without the opposite bound.', 'warn', pw)
    if lim.low is not None and lim.high is not None and lim.high == lim.low and lim.source == 'spec':
        add('limit_zero_width', f'Point {p.id} [{per}]: the limits have zero width.', 'warn', pw)


# ============================================================================================================== storage
def user_specs_dir():
    """<data folder>/user_specs (created on first use; falls back to a folder beside the program when the data folder is not writable)."""
    root = appdata.data_dir() / 'user_specs'
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = HERE / 'user_specs'
        root.mkdir(parents=True, exist_ok=True)
    return root


def slug(text, fallback='x'):
    s = re.sub(r'[^A-Za-z0-9]+', '-', (text or '').strip()).strip('-')
    return s[:40] or fallback


def make_uid(ds):
    """<make>_<model>_<slug of the title>  (file name stem of user_specs/<uid>.json)."""
    return f'{slug(ds.make, "make")}_{slug(ds.model, "model")}_{slug(ds.title, "datasheet")}'


DB = appdata.db_path('lab_registry.sqlite3')
REG_SCHEMA = '''
CREATE TABLE IF NOT EXISTS user_datasheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE COLLATE NOCASE,
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    tag TEXT NOT NULL DEFAULT 'user-built',
    current_version INTEGER NOT NULL DEFAULT 0,
    runnable_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    points INTEGER NOT NULL DEFAULT 0,
    spec_file TEXT NOT NULL DEFAULT '',
    deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS user_datasheet_versions (
    datasheet_id INTEGER NOT NULL REFERENCES user_datasheets(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    saved_at TEXT NOT NULL,
    who TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    file TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    points INTEGER NOT NULL DEFAULT 0,
    problems_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (datasheet_id, version)
);
'''


@contextmanager
def _db(path=None):
    con = sqlite3.connect(str(path or DB), timeout=5)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript(REG_SCHEMA)
        if 'kind' not in {r[1] for r in con.execute('PRAGMA table_info(user_datasheets)')}:      # a registry made before the Manual Calibrations tab
            con.execute("ALTER TABLE user_datasheets ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
        yield con
        con.commit()
    finally:
        con.close()


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class SaveResult:
    ok: bool
    uid: str = ''
    version: int = 0
    status: str = ''                 # 'ready' (a runnable spec was written) | 'draft' (saved as a version only; problems say why)
    spec_path: str = ''
    version_file: str = ''
    problems: list = field(default_factory=list)
    kind: str = ''                   # 'manual' | 'verification' (which Manager tab lists it); '' when no runnable spec was written


def _paths(uid, root=None):
    root = Path(root) if root else user_specs_dir()
    return root, root / f'{uid}.json', root / 'versions' / uid


def lock_reason(uid, db=None):
    """'' when the user-built procedure `uid` may be edited or deleted, else the sentence saying it is verified on hardware and locked (verified.py).
    `db` is the registry file (None = the real one, where the seeded list applies)."""
    if not uid:
        return ''
    try:
        import verified
    except ImportError:
        return ''
    return verified.Registry(db, seed=db is None).lock_reason(proc_key=verified.DS_PREFIX + str(uid))


KIND_AUTOMATED, KIND_MANUAL = 'verification', 'manual'      # the Manager's procscan.KIND_* values ('verification' = the Automated Calibrations tab)


def classify_kind(ds):
    """Which Manager tab lists this datasheet once it is saved: 'manual' when no automation applies, else 'verification' (Automated Calibrations).
    Manual = the owner flagged it (ds.options['manual_entry']) or the standards matcher finds NO point that a standard could source / measure
    (datasheet_builder_match: every point is 'manual' or uncovered).  Read only; any problem (no standards sheet, matcher error) means 'verification',
    the behaviour before the Manual Calibrations tab existed."""
    if ds.options.get('manual_entry'):
        return KIND_MANUAL
    if not any(p.enabled for _fn, p in ds.all_points()):
        return KIND_AUTOMATED
    try:
        import datasheet_builder_match as dm
        res = dm.match_datasheet(ds)
        if res.assignments and not any(a.can_automate for a in res.assignments.values()):
            return KIND_MANUAL
    except Exception:
        pass
    return KIND_AUTOMATED


def save(ds, who='', note='', root=None, db=None):
    """Save `ds` as a NEW version.  The datasheet is written to user_specs/versions/<uid>/vNNNN.datasheet.json (never overwritten).  If it validates
    (no errors) and exports, the runnable spec is also written to versions/<uid>/vNNNN.spec.json and user_specs/<uid>.json is replaced atomically
    (the previous runnable file already exists as its own version file).  Otherwise status is 'draft' and the earlier runnable spec stays.
    ds.uid / ds.version / ds.created are set.  The registry row is updated; a damaged registry never stops the files being written."""
    import datasheet_builder_specs as dsp
    why = lock_reason(ds.uid, db)
    if why:                                                  # verified on hardware and locked: no new version, nothing written
        return SaveResult(False, ds.uid, ds.version, 'locked', problems=[DsProblem('locked', why)])
    problems = validate(ds)
    rule_check = None
    if not errors(problems):                                  # the build-time rules 1-5 (datasheet_builder_rules): an error there keeps the sheet a draft
        try:
            import datasheet_builder_rules as _rules
            extra, rule_check = _rules.blocking_problems(ds)
            problems = problems + extra
        except Exception:
            rule_check = None
    try:
        if not ds.uid:
            ds.uid = make_uid(ds)
            with _db(db) as con:                         # a different datasheet already uses this name: never take it over silently
                taken = con.execute('SELECT 1 FROM user_datasheets WHERE uid=?', (ds.uid,)).fetchone()
            if taken or _paths(ds.uid, root)[1].exists():
                n = 2
                while True:
                    cand = f'{ds.uid}-{n}'
                    with _db(db) as con:
                        busy = con.execute('SELECT 1 FROM user_datasheets WHERE uid=?', (cand,)).fetchone()
                    if not busy and not _paths(cand, root)[1].exists():
                        ds.uid = cand
                        break
                    n += 1
    except sqlite3.Error:
        pass
    if not ds.uid:
        ds.uid = make_uid(ds)
    root_, runnable, vdir = _paths(ds.uid, root)
    last = 0
    try:
        existing = [int(m.group(1)) for f in vdir.glob('v*.datasheet.json') if (m := re.match(r'v(\d+)\.datasheet\.json$', f.name))] if vdir.is_dir() else []
        last = max(existing, default=0)
        with _db(db) as con:
            row = con.execute('SELECT current_version FROM user_datasheets WHERE uid=?', (ds.uid,)).fetchone()
            last = max(last, row[0] if row else 0)
    except sqlite3.Error:
        pass
    version = last + 1
    ds.version = version
    ds.created = ds.created or _now()
    result = SaveResult(False, ds.uid, version, 'draft', problems=list(problems))
    exported = None
    if not errors(problems):
        exported = dsp.export_spec(ds, uid=ds.uid)
        result.problems += [p for p in exported.problems if p not in result.problems]
        if exported.spec is None:
            exported = None
        elif rule_check is not None:                          # what the Manager's list says about the sheet without running the check again
            exported.spec['dsb']['engine']['check'] = rule_check.save_summary()
    status = 'ready' if exported else 'draft'
    kind = classify_kind(ds) if exported else ''
    result.kind = kind
    try:
        vdir.mkdir(parents=True, exist_ok=True)
        vfile = vdir / f'v{version:04d}.datasheet.json'
        if vfile.exists():
            raise OSError(f'{vfile} already exists')
        text = ds.to_json()
        _atomic_write(vfile, text)
        result.version_file = str(vfile)
        if exported:
            spec_text = json.dumps(exported.spec, indent=1, ensure_ascii=True)
            _atomic_write(vdir / f'v{version:04d}.spec.json', spec_text)
            _atomic_write(runnable, spec_text)
            result.spec_path = str(runnable)
    except OSError as e:
        result.problems.append(DsProblem('write', f'Could not write the datasheet files: {e}'))
        return result
    result.status, result.ok = status, True
    try:
        with _db(db) as con:
            row = con.execute('SELECT id,created_at,runnable_version,spec_file,deleted FROM user_datasheets WHERE uid=?', (ds.uid,)).fetchone()
            npts = sum(len(f.points) for f in ds.functions)
            if row is None:
                did = con.execute('INSERT INTO user_datasheets(uid,make,model,title,tag,current_version,runnable_version,status,points,spec_file,created_at,updated_at,kind)'
                                  ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (ds.uid, ds.make, ds.model, ds.title, TAG, version, version if exported else 0, status, npts,
                                   str(runnable) if exported else '', ds.created, _now(), kind)).lastrowid
            else:
                did = row[0]
                con.execute('UPDATE user_datasheets SET make=?,model=?,title=?,current_version=?,runnable_version=?,status=?,points=?,spec_file=?,updated_at=? WHERE id=?',
                            (ds.make, ds.model, ds.title, version, version if exported else row[2], status, npts,
                             str(runnable) if exported else row[3], _now(), did))
                if exported:                                       # the kind follows the runnable version (a draft keeps the earlier one)
                    con.execute('UPDATE user_datasheets SET kind=? WHERE id=?', (kind, did))
            con.execute('INSERT INTO user_datasheet_versions(datasheet_id,version,saved_at,who,note,file,sha256,status,points,problems_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (did, version, _now(), who, note, str(vfile), hashlib.sha256(text.encode('utf-8')).hexdigest(), status, npts,
                         json.dumps([{'code': p.code, 'level': getattr(p, 'level', 'error'), 'message': str(p), 'where': getattr(p, 'where', '')} for p in result.problems])))
    except sqlite3.Error:
        result.problems.append(DsProblem('registry', 'The registry could not be updated; the files were saved.', 'warn'))
    return result


def _read_version_file(uid, version, root=None):
    _, _, vdir = _paths(uid, root)
    f = vdir / f'v{int(version):04d}.datasheet.json'
    try:
        return Datasheet.from_json(f.read_text(encoding='utf-8'))
    except (OSError, DsError, ValueError):
        return None


def load(uid, version=None, root=None, db=None):
    """The datasheet `uid` (latest version, or the given one), or None when it is missing or damaged."""
    try:
        if version is None:
            v = None
            try:
                with _db(db) as con:
                    row = con.execute('SELECT current_version FROM user_datasheets WHERE uid=?', (uid,)).fetchone()
                    v = row[0] if row else None
            except sqlite3.Error:
                pass
            if v is None:
                vs = [x['version'] for x in versions(uid, root=root, db=db)]
                v = max(vs) if vs else None
            if v is None:
                return None
            version = v
        return _read_version_file(uid, version, root)
    except Exception:
        return None


def versions(uid, root=None, db=None):
    """[{version, saved_at, who, note, status, points, file, sha256}] newest first.  Falls back to the files when the registry is unreadable."""
    out = []
    try:
        with _db(db) as con:
            rows = con.execute('SELECT v.version,v.saved_at,v.who,v.note,v.status,v.points,v.file,v.sha256 FROM user_datasheet_versions v '
                               'JOIN user_datasheets d ON d.id=v.datasheet_id WHERE d.uid=? ORDER BY v.version DESC', (uid,)).fetchall()
        out = [dict(zip(('version', 'saved_at', 'who', 'note', 'status', 'points', 'file', 'sha256'), r)) for r in rows]
    except sqlite3.Error:
        out = []
    if not out:
        _, _, vdir = _paths(uid, root)
        try:
            for f in sorted(vdir.glob('v*.datasheet.json'), reverse=True):
                m = re.match(r'v(\d+)\.datasheet\.json$', f.name)
                if m:
                    out.append(dict(version=int(m.group(1)), saved_at='', who='', note='', status='', points=0, file=str(f), sha256=''))
        except OSError:
            pass
    return out


def list_datasheets(include_deleted=False, root=None, db=None):
    """[{uid, make, model, title, tag, version, runnable_version, status, points, spec_file, deleted, updated_at}], newest first.  Registry first;
    when it is unreadable the datasheet files themselves are listed."""
    keys = ('uid', 'make', 'model', 'title', 'tag', 'version', 'runnable_version', 'status', 'points', 'spec_file', 'deleted', 'updated_at', 'kind')
    try:
        with _db(db) as con:
            q = 'SELECT uid,make,model,title,tag,current_version,runnable_version,status,points,spec_file,deleted,updated_at,kind FROM user_datasheets'
            if not include_deleted:
                q += ' WHERE deleted=0'
            rows = con.execute(q + ' ORDER BY updated_at DESC, id DESC').fetchall()
        return [dict(zip(keys, r)) for r in rows]
    except sqlite3.Error:
        pass
    out = []                      # damaged registry: scan the files
    try:
        base = Path(root) if root else user_specs_dir()
        for d in sorted((base / 'versions').iterdir()) if (base / 'versions').is_dir() else []:
            vs = sorted(d.glob('v*.datasheet.json'))
            if not vs:
                continue
            ds = Datasheet.from_json(vs[-1].read_text(encoding='utf-8'))
            sp, run_v = base / f'{d.name}.json', 0
            if sp.is_file():                                   # the runnable file says which version it was made from
                try:
                    run_v = int(json.loads(sp.read_text(encoding='utf-8'))['dsb']['version'])
                except (OSError, ValueError, KeyError, TypeError):
                    run_v = 0
            out.append(dict(uid=d.name, make=ds.make, model=ds.model, title=ds.title, tag=TAG, version=ds.version, runnable_version=run_v,
                            status='ready' if run_v else 'draft', points=sum(len(f.points) for f in ds.functions),
                            spec_file=str(sp) if run_v else '', deleted=0, updated_at='', kind=''))
    except (OSError, DsError, ValueError):
        pass
    return out


def duplicate(uid, title=None, model=None, make=None, who='', root=None, db=None):
    """Copy the latest version of `uid` as a NEW datasheet (new uid, version 1).  Returns SaveResult, or None when the source cannot be loaded."""
    src = load(uid, root=root, db=db)
    if src is None:
        return None
    new = src.copy()
    new.uid, new.version, new.created = '', 0, ''
    new.title = title or (src.title + ' (copy)')
    if model:
        new.model = model
    if make:
        new.make = make
    return save(new, who=who, note=f'duplicated from {uid} v{src.version}', root=root, db=db)


def delete(uid, who='', root=None, db=None):
    """SOFT delete: the registry row is marked deleted and the runnable spec file is moved to user_specs/_deleted/ (so it leaves the Procedures list).
    Every version file stays.  Returns True when something was marked.  A procedure that is verified on hardware and locked is not deleted."""
    if lock_reason(uid, db):
        return False
    try:
        with _db(db) as con:
            row = con.execute('SELECT id,spec_file FROM user_datasheets WHERE uid=? AND deleted=0', (uid,)).fetchone()
            if not row:
                return False
            con.execute('UPDATE user_datasheets SET deleted=1,deleted_at=?,updated_at=? WHERE id=?', (_now(), _now(), row[0]))
        base, runnable, _ = _paths(uid, root)
        if runnable.exists():
            (base / '_deleted').mkdir(exist_ok=True)
            shutil.move(str(runnable), str(base / '_deleted' / runnable.name))
        return True
    except (sqlite3.Error, OSError):
        return False


def restore(uid, root=None, db=None):
    try:
        with _db(db) as con:
            row = con.execute('SELECT id FROM user_datasheets WHERE uid=? AND deleted=1', (uid,)).fetchone()
            if not row:
                return False
            con.execute("UPDATE user_datasheets SET deleted=0,deleted_at='',updated_at=? WHERE id=?", (_now(), row[0]))
        base, runnable, _ = _paths(uid, root)
        parked = base / '_deleted' / runnable.name
        if parked.exists() and not runnable.exists():
            shutil.move(str(parked), str(runnable))
        return True
    except (sqlite3.Error, OSError):
        return False


def export_json(uid, path, version=None, root=None, db=None):
    """Write the datasheet (or one of its versions) to `path` as a standalone JSON file.  Returns True on success."""
    ds = load(uid, version, root=root, db=db)
    if ds is None:
        return False
    try:
        _atomic_write(path, ds.to_json())
        return True
    except OSError:
        return False


@dataclass
class ImportResult:
    ok: bool
    uid: str = ''
    version: int = 0
    problems: list = field(default_factory=list)


def import_json(path, who='', root=None, db=None):
    """Import a datasheet JSON (a datasheet file, or a runnable spec that carries one).  It always becomes a NEW datasheet: if its name is taken the
    uid gets a suffix, an existing datasheet is never overwritten.  Damaged or foreign files return ok=False with a problem; nothing is stored."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return ImportResult(False, problems=[DsProblem('import_read', f'Cannot read {path}: {e}')])
    if isinstance(data, dict) and isinstance(data.get('dsb'), dict) and isinstance(data['dsb'].get('datasheet'), dict):
        data = data['dsb']['datasheet']
    try:
        ds = Datasheet.from_dict(data)
    except DsError as e:
        return ImportResult(False, problems=[DsProblem('import_' + e.code, str(e))])
    ds.uid, ds.version, ds.created = '', 0, ''
    res = save(ds, who=who, note=f'imported from {Path(path).name}', root=root, db=db)
    return ImportResult(res.ok, res.uid, res.version, res.problems)


def procedure_entries(root=None, db=None):
    """The 'user-built' rows for the Manager's Procedures list: [{uid, name, manufacturer, model, category, tag, spec_path, version, status, kind}] for every
    non-deleted datasheet that has a runnable spec file on disk.  kind = 'manual' (Manual Calibrations tab) or 'verification' (Automated Calibrations)."""
    out = []
    for r in list_datasheets(root=root, db=db):
        sp = r['spec_file']
        if r['runnable_version'] and sp and Path(sp).is_file():
            out.append(dict(uid=r['uid'], name=f"{r['make']} {r['model']} - {r['title']}".strip(' -'), manufacturer=r['make'], model=r['model'],
                            category='User-built', tag=TAG, spec_path=sp, version=r['runnable_version'], status=r['status'],
                            kind=r.get('kind') or KIND_AUTOMATED))
    return out


def __getattr__(name):     # lazy re-export of the spec / matcher APIs (avoids a circular import)
    if name in ('export_spec', 'ExportResult', 'validate_spec', 'datasheet_from_spec', 'engine_kind'):
        import datasheet_builder_specs as m
        return getattr(m, {'validate_spec': 'validate_spec_ext'}.get(name, name))
    if name in ('match', 'match_datasheet', 'MatchResult', 'driver_table', 'automation_status', 'Assignment'):
        import datasheet_builder_match as m
        return getattr(m, {'match': 'match_datasheet'}.get(name, name))
    raise AttributeError(name)
