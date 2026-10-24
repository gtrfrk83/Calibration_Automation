"""Standards spec editor: the document model (Tk-free, no database).

A standards sheet is a JSON file in specs/standards/ (`schema`, `standard` header block, `notes`, optional `limits`, `functions` -> `ranges` -> `specs` /
`params`, `problems`).  `SpecDoc` loads one, keeps the file as read (`original`) and a working copy (`current`), applies typed cell edits to the copy,
lists every difference as a `Change` (old -> new), validates the copy (errors block saving, warnings do not) and serialises it back in the file's own layout.
Nothing here writes a file: spec_edit_io.py does that, after the edit has been documented.

Rules (project): values stay in SI base units in the file; the editor only DISPLAYS scaled text (specmanager_view.si_text, exact, never rounded) and parses
typed text with Decimal (no float arithmetic); a number is stored as the float that prints back to the typed digits (a value with more than 15
significant digits is refused).  Instrument commands, limits logic and engines are not touched by anything in here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import specmanager as sm
import specmanager_view as view

HERE = Path(__file__).resolve().parent
STANDARDS_DIR = HERE / 'specs' / 'standards'

MICRO = view.MICRO
_ABSENT = object()


class EditError(ValueError):
    """A typed value that cannot be stored; the message is shown to the person."""


class SpecFileError(ValueError):
    """The file is not a standards sheet at all (not JSON, or the main blocks are missing)."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------------------------------------------------ typed text <-> Decimal
_PREFIX = {'p': Decimal('1e-12'), 'n': Decimal('1e-9'), 'u': Decimal('1e-6'), MICRO: Decimal('1e-6'), 'μ': Decimal('1e-6'), 'm': Decimal('1e-3'),
           'k': Decimal('1e3'), 'M': Decimal('1e6'), 'G': Decimal('1e9')}
_PREFIXABLE = ('V', 'A', 'F', 'Hz', 'W', 'H', 'S', 's', 'ohm', 'Vpp', 'App')
_NUMBER = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$', re.S)
MAX_DIGITS = 15


def _unit_text(s: str) -> str:
    return (s or '').replace('µ', 'u').replace('μ', 'u').replace('Ω', 'ohm').replace('Ω', 'ohm').replace('Ohm', 'ohm').replace('°C', 'degC').replace('°F', 'degF').replace('°', 'deg').replace('²', '2')


def may_be_negative(unit) -> bool:
    """Logarithmic and temperature units carry negative terms on real sheets (noise floors in dBc, degC bands)."""
    u = unit or ''
    return u.startswith('dB') or u in ('degC', 'degF', 'deg', 'rad', 'ratio')


def split_number(text):
    """'20 mA' -> (Decimal('20'), 'mA'); raises EditError for text that does not start with a plain number."""
    m = _NUMBER.match(text or '')
    if not m:
        raise EditError(f'"{(text or "").strip()}" is not a number')
    try:
        d = Decimal(m.group(1))
    except InvalidOperation:
        raise EditError(f'"{m.group(1)}" is not a number')
    if not d.is_finite():
        raise EditError('the number must be finite')
    return d, m.group(2)


def parse_quantity(text, unit=''):
    """Typed text -> Decimal in the SI base `unit`.  '0.1 mA' with unit 'A' -> 0.0001; a bare number is already in the base unit; a unit that is not
    the field's unit (or a prefix of it) is refused instead of guessed."""
    d, suffix = split_number(text)
    if not suffix:
        return d
    s, u = _unit_text(suffix), _unit_text(unit)
    if not u:
        raise EditError(f'this row has no unit; type a plain number (not "{suffix}") or set the unit first')
    if s == u:
        return d
    if u in _PREFIXABLE and s.endswith(u) and s[:-len(u)] in _PREFIX:
        return d * _PREFIX[s[:-len(u)]]
    raise EditError(f'"{suffix}" is not {u} (expected {u} with an optional SI prefix)')


def suffix_of(text) -> str:
    return split_number(text)[1]


def parse_ratio(text):
    """Typed text -> Decimal fraction: '0.8 %' -> 0.008, '90 ppm' -> 0.00009, '90 uA/A' -> 0.00009, '0.0009' -> 0.0009."""
    d, suffix = split_number(text)
    s = _unit_text(suffix).replace(' ', '')
    if s == '':
        return d
    if s == '%':
        return d / 100
    if s == 'ppm':
        return d * Decimal('1e-6')
    if s == 'ppb':
        return d * Decimal('1e-9')
    m = re.fullmatch(r'([pnuμµmkM]?)([A-Za-z]+)/([A-Za-z]+)', s)
    if m and m.group(2) == m.group(3):
        return d * (_PREFIX[m.group(1)] if m.group(1) else 1)
    raise EditError(f'"{suffix}" is not a ratio (use %, ppm, a unit ratio such as uA/A, or a plain fraction)')


def to_float(d: Decimal, what='value'):
    """The float that holds `d`.  Refused when it would not print back to the same digits."""
    if len(d.normalize().as_tuple().digits) > MAX_DIGITS:
        raise EditError(f'{what}: more than {MAX_DIGITS} significant digits; the file stores about that many')
    f = float(d)
    if not math.isfinite(f):
        raise EditError(f'{what}: out of range')
    return f


def dec(value):
    """Decimal of a stored number (through its shortest text, never binary), None for None / non-numbers."""
    return view.to_decimal(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fmt_ratio(value) -> str:
    """0.008 -> '0.8 %', 9e-05 -> '90 ppm', 5e-10 -> '0.0000000005' (exact; used for display and as the text typed back by the cell editor)."""
    d = dec(value)
    if d is None:
        return ''
    if d == 0:
        return '0'
    if abs(d) >= Decimal('0.001'):
        return f'{view.plain(d * 100)} %'
    if abs(d) >= Decimal('1e-6'):
        return f'{view.plain(d * Decimal("1e6"))} ppm'
    return view.plain(d)


def fmt_quantity(value, unit='') -> str:
    d = dec(value)
    if d is None or not d.is_finite():
        return '' if d is None else str(value)         # a damaged (NaN / inf) number is shown as it is, never scaled
    return view.si_text(d, unit or '', exact=True)


# ------------------------------------------------------------------------------------------------------------ the document
RATIO_KEYS = ('rel', 'fs_rel')
SPEC_QUANTITY = ('fs_value', 'abs')
NODE_LISTS = ('functions', 'ranges', 'specs', 'params', 'limits', 'problems')
INFO_FIELDS = ('manufacturer', 'model', 'description', 'confidence_text', 'confidence_pct', 'reference', 'revision', 'author', 'approved_by',
               'approve_date', 'source_pdf', 'sheet_generated', 'built')
READ_ONLY_INFO = ('model',)
RANGE_FIELDS = {'label': 'str', 'page': 'int?', 'kind': 'str', 'variant': 'str', 'unit': 'str', 'amp_lo': 'qty?', 'amp_hi': 'qty?', 'freq_lo': 'hz?',
                'freq_hi': 'hz?', 'range_max': 'qty?', 'resolution': 'qty?', 'res_src': 'str', 'printed': 'str', 'allowed_frequency': 'str',
                'qualifiers': 'json', 'raw_other': 'json'}
SPEC_FIELDS = {'period': 'str', 'rel': 'ratio', 'fs_rel': 'ratio', 'fs_value': 'sqty', 'abs': 'sqty', 'unit': 'str', 'le': 'bool', 'raw': 'str'}
PARAM_FIELDS = {'tag': 'str', 'lo': 'pqty?', 'hi': 'pqty?', 'unit': 'str', 'text': 'str', 'annot': 'str', 'notes': 'ints'}
FUNCTION_FIELDS = {'name': 'str', 'direction': 'dir', 'page': 'int?'}
LIMIT_FIELDS = {'function': 'str', 'limit': 'str', 'page': 'str'}
PROBLEM_FIELDS = {'level': 'level', 'where': 'str', 'what': 'str'}
DIRECTIONS = ('output', 'input')
LEVELS = ('error', 'warn')
OPTIONAL_RANGE_KEYS = ('printed', 'allowed_frequency')
TOP_KEYS = ('schema', 'standard', 'notes', 'limits', 'functions', 'problems')


@dataclass
class Style:
    indent: object = 1
    ascii: bool = False
    newline: bool = True
    exact: bool = True            # the file is byte-for-byte what json.dumps with this style writes


def detect_style(raw: bytes, data) -> Style:
    text = raw.decode('utf-8')
    for indent in (1, 2, 4, None):
        for asc in (False, True):
            for nl in (True, False):
                if (json.dumps(data, indent=indent, ensure_ascii=asc) + ('\n' if nl else '')) == text:
                    return Style(indent, asc, nl, True)
    return Style(1, False, True, False)


def dumps(data, style: Style) -> bytes:
    return (json.dumps(data, indent=style.indent, ensure_ascii=style.ascii) + ('\n' if style.newline else '')).encode('utf-8')


def iter_nodes(data):
    """(list name, parent, node) for every node the editor tracks by identity."""
    if not isinstance(data, dict):
        return
    for fn in data.get('functions') or []:
        if isinstance(fn, dict):
            yield 'functions', data, fn
            for r in fn.get('ranges') or []:
                if isinstance(r, dict):
                    yield 'ranges', fn, r
                    for s in r.get('specs') or []:
                        if isinstance(s, dict):
                            yield 'specs', r, s
                    for p in r.get('params') or []:
                        if isinstance(p, dict):
                            yield 'params', r, p
    for name in ('limits', 'problems'):
        for x in data.get(name) or []:
            if isinstance(x, dict):
                yield name, data, x


@dataclass
class Change:
    op: str                     # 'set' | 'add' | 'remove'
    area: str                   # rows | notes | info | limits | issues | file
    node: str                   # function | range | spec | param | note | info | limit | problem | file
    uid: object                 # node uid (note number for a note, field name for info)
    key: str                    # field changed ('' for a whole node added / removed)
    where: str                  # human location: 'Current, DC / (2 to 20) A / 1 yr'
    label: str                  # human field name
    old: object = None
    new: object = None
    old_text: str = ''
    new_text: str = ''
    path: str = ''
    absent: str = ''            # 'old' | 'new': the key did not exist before / after
    after: object = None        # remove: uid of the sibling it followed in the original list
    range_uid: object = None
    unit: str = ''

    def as_json(self) -> dict:
        d = dict(op=self.op, area=self.area, where=self.where, field=self.label, path=self.path, old=self.old, new=self.new,
                 old_text=self.old_text, new_text=self.new_text)
        if self.absent:
            d['absent'] = self.absent
        return d


KEY_LABEL = {'rel': 'Reading (rel)', 'fs_rel': 'Full-scale (rel)', 'fs_value': 'Full-scale value', 'abs': 'Floor (abs)', 'resolution': 'Resolution',
             'res_src': 'Resolution source', 'amp_lo': 'Span low', 'amp_hi': 'Span high', 'freq_lo': 'Frequency low', 'freq_hi': 'Frequency high',
             'range_max': 'Range maximum', 'label': 'Range label', 'page': 'Page', 'notes': 'Note references', 'name': 'Function name', 'kind': 'Kind',
             'variant': 'Variant', 'unit': 'Unit', 'period': 'Period', 'raw': 'Printed text', 'le': 'Upper bound only (<=)', 'direction': 'Direction'}


class SpecDoc:
    """One standards sheet file, its working copy, and everything derived from them."""

    def __init__(self, path, raw: bytes, data: dict):
        self.path = Path(path)
        self.raw = raw
        self.sha = sha256_bytes(raw)
        self.style = detect_style(raw, data)
        self.original = data
        self.current = copy.deepcopy(data)
        self._counter = 0
        self._uid_cur, self._uid_org, self._by_cur, self._by_org = {}, {}, {}, {}
        for (_, _, o), (_, _, c) in zip(iter_nodes(self.original), iter_nodes(self.current)):
            u = self._new_uid()
            self._uid_org[id(o)], self._uid_cur[id(c)] = u, u
            self._by_org[u], self._by_cur[u] = o, c
        self._diff_cache = None
        self._vd_before = None

    # ---- loading / saving the bytes
    @classmethod
    def load(cls, path):
        path = Path(path)
        raw = path.read_bytes()
        return cls.from_bytes(path, raw)

    @classmethod
    def from_bytes(cls, path, raw: bytes):
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            raise SpecFileError(f'{Path(path).name} is not valid JSON: {e}')
        if not isinstance(data, dict) or not isinstance(data.get('standard'), dict) or not isinstance(data.get('functions'), list):
            raise SpecFileError(f'{Path(path).name} is not a standards sheet (it needs a "standard" block and a "functions" list)')
        return cls(path, raw, data)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def model(self) -> str:
        return str(self.original.get('standard', {}).get('model', ''))

    def to_bytes(self) -> bytes:
        return dumps(self.current, self.style)

    def rebase(self, raw: bytes):
        """After a successful save: the saved file becomes the new 'original' (the pending list is empty again)."""
        data = json.loads(raw.decode('utf-8'))
        self.__init__(self.path, raw, data)

    def discard_all(self):
        self.current = copy.deepcopy(self.original)
        self._uid_cur, self._by_cur = {}, {}
        for (_, _, o), (_, _, c) in zip(iter_nodes(self.original), iter_nodes(self.current)):
            u = self._uid_org[id(o)]
            self._uid_cur[id(c)] = u
            self._by_cur[u] = c
        self._touch()

    def _new_uid(self) -> int:
        self._counter += 1
        return self._counter

    def _touch(self):
        self._diff_cache = None

    @property
    def dirty(self) -> bool:
        return self.to_bytes() != self.raw

    def uid(self, node) -> int:
        return self._uid_cur[id(node)]

    def node(self, uid):
        return self._by_cur.get(uid)

    def has_uid(self, uid) -> bool:
        return uid in self._by_cur

    def original_node(self, uid):
        return self._by_org.get(uid)

    def _register(self, node, uid=None):
        u = uid if uid is not None else self._new_uid()
        self._uid_cur[id(node)] = u
        self._by_cur[u] = node
        return u

    def _register_tree(self, node, kind):
        u = self._register(node)
        if kind == 'range':
            for s in node.get('specs') or []:
                self._register(s)
            for p in node.get('params') or []:
                self._register(p)
        return u

    # ---- rows (one table line per range x specification)
    def functions(self):
        return [f for f in self.current.get('functions') or [] if isinstance(f, dict)]

    def ranges(self):
        """[(function, range)] in file order."""
        return [(f, r) for f in self.functions() for r in f.get('ranges') or [] if isinstance(r, dict)]

    def function_of(self, rng):
        return next((f for f in self.functions() if any(r is rng for r in f.get('ranges') or [])), None)

    def lines(self):
        """The Rows table: [Line] (iid, function, range, spec or None, first line of its range)."""
        out = []
        for f, r in self.ranges():
            specs = [s for s in r.get('specs') or [] if isinstance(s, dict)] or [None]
            for i, s in enumerate(specs):
                out.append(Line(iid=f'L{self.uid(r)}_{self.uid(s) if s is not None else 0}', fn=f, rng=r, spec=s, first=(i == 0)))
        return out

    def line(self, iid):
        return next((ln for ln in self.lines() if ln.iid == iid), None)

    def ordinal(self, rng) -> int:
        """1-based position of a range among all ranges of the sheet (the 'Row n' of messages)."""
        return self.ordinals().get(id(rng), 0)

    def ordinals(self) -> dict:
        return {id(r): i for i, (_, r) in enumerate(self.ranges(), 1)}

    def touched_ranges(self) -> set:
        """uids of the rows with a pending change (warnings about old data are only raised for these)."""
        out = set()
        for c in self.diff():
            if c.area == 'rows':
                out.add(c.range_uid if c.range_uid is not None else c.uid)
        return out

    def sheet_issues_before(self):
        if self._vd_before is None:
            try:
                self._vd_before = {(i['level'], i['where'], i['what']) for i in sm.validate_data(self.original)}
            except Exception:
                self._vd_before = set()
        return self._vd_before

    def range_notes(self, rng):
        return sorted({n for p in rng.get('params') or [] if isinstance(p, dict) for n in p.get('notes') or [] if isinstance(n, int)})

    def cell_text(self, ln, col) -> str:
        r, s, f = ln.rng, ln.spec, ln.fn
        if col == 'function':
            return str(f.get('name', '')) if ln.first else ''
        if col == 'period':
            return str(s.get('period', '')) if s else ''
        if col in ('rel', 'fs_rel'):
            return fmt_ratio(s.get(col)) if s else ''
        if col in ('fs_value', 'abs'):
            return fmt_quantity(s.get(col), (s.get('unit') or r.get('unit') or '')) if s else ''
        if not ln.first:
            return ''
        u = r.get('unit') or ''
        if col == 'label':
            return str(r.get('label', ''))
        if col == 'span':
            if r.get('amp_lo') is None and r.get('amp_hi') is None:
                return ''
            return f"{fmt_quantity(r.get('amp_lo'), u)} to {fmt_quantity(r.get('amp_hi'), u)}"
        if col == 'freq':
            if r.get('freq_lo') is None and r.get('freq_hi') is None:
                return ''
            return f"{fmt_quantity(r.get('freq_lo'), 'Hz')} to {fmt_quantity(r.get('freq_hi'), 'Hz')}"
        if col == 'res':
            return fmt_quantity(r.get('resolution'), u)
        if col == 'notes':
            return ', '.join(str(n) for n in self.range_notes(r))
        if col == 'page':
            return '' if r.get('page') is None else str(r.get('page'))
        raise KeyError(col)

    # ---- editing: every method changes only `current`, returns the keys it set (empty = nothing changed) and raises EditError
    def _set(self, node, key, value) -> bool:
        if key in node and node[key] == value and type(node[key]) is type(value):
            return False
        node[key] = value
        self._touch()
        return True

    def edit_cell(self, iid, col, text):
        ln = self.line(iid)
        if ln is None:
            raise EditError('that row no longer exists')
        r, s, f = ln.rng, ln.spec, ln.fn
        text = (text or '').strip()
        if col not in ('function', 'period', 'rel', 'fs_rel', 'fs_value', 'abs') and not ln.first:
            raise EditError('this column belongs to the whole row: edit it on the first line of the row')
        if col == 'function':
            if not text:
                raise EditError('the function name cannot be empty')
            return ['name'] if self._set(f, 'name', text) else []
        if col == 'label':
            if not text:
                raise EditError('the range label cannot be empty')
            return ['label'] if self._set(r, 'label', text) else []
        if col in ('span', 'freq'):
            lo_key, hi_key, unit = ('amp_lo', 'amp_hi', r.get('unit') or '') if col == 'span' else ('freq_lo', 'freq_hi', 'Hz')
            lo, hi = parse_span(text, unit)
            changed = []
            for key, v in ((lo_key, lo), (hi_key, hi)):
                if self._set(r, key, None if v is None else to_float(v, key)):
                    changed.append(key)
            return changed
        if col == 'page':
            if text == '':
                return ['page'] if self._set(r, 'page', None) else []
            if not re.fullmatch(r'\d+', text):
                raise EditError('the page is a whole number (or blank)')
            return ['page'] if self._set(r, 'page', int(text)) else []
        if col == 'res':
            u = r.get('unit') or ''
            if text == '':
                a = self._set(r, 'resolution', None)
                b = self._set(r, 'res_src', '')
                return [k for k, ch in (('resolution', a), ('res_src', b)) if ch]
            d = parse_quantity(text, u)
            if d <= 0:
                raise EditError('the resolution must be greater than zero (or blank)')
            a = self._set(r, 'resolution', to_float(d, 'resolution'))
            b = self._set(r, 'res_src', 'edited') if a else False
            return [k for k, ch in (('resolution', a), ('res_src', b)) if ch]
        if col == 'notes':
            return self._edit_notes(r, text)
        if s is None:
            raise EditError('this row has no specification line; add a period line first')
        if col == 'period':
            if not text:
                raise EditError('the period cannot be empty')
            return ['period'] if self._set(s, 'period', text) else []
        if col in RATIO_KEYS:
            d = parse_ratio(text)
            if d < 0:
                raise EditError('a relative term cannot be negative')
            return [col] if self._set(s, col, to_float(d, col)) else []
        if col in SPEC_QUANTITY:
            d = parse_quantity(text, s.get('unit') or r.get('unit') or '')
            if d < 0 and not may_be_negative(s.get('unit') or r.get('unit')):
                raise EditError('a floor / full-scale value cannot be negative in this unit')
            return [col] if self._set(s, col, to_float(d, col)) else []
        raise EditError(f'unknown column {col}')

    def _edit_notes(self, rng, text):
        refs = parse_ints(text)
        params = [p for p in rng.get('params') or [] if isinstance(p, dict)]
        if not params:
            if not refs:
                return []
            raise EditError('this row has no value-range block (params) to hold note references; add them in Row details')
        sets = {tuple(p.get('notes') or []) for p in params}
        if len(sets) > 1:
            raise EditError('the value ranges of this row carry different note references; edit them one by one in Row details')
        return ['notes'] if any([self._set(p, 'notes', list(refs)) for p in params]) else []

    def edit_field(self, node, key, text):
        """Generic typed edit of one field of a range / spec / param / function / limit / problem node (Row details dialog)."""
        kind = self.kind_of(node)
        table = {'range': RANGE_FIELDS, 'spec': SPEC_FIELDS, 'param': PARAM_FIELDS, 'function': FUNCTION_FIELDS, 'limit': LIMIT_FIELDS, 'problem': PROBLEM_FIELDS}[kind]
        if key not in table:
            raise EditError(f'{key} cannot be edited here')
        typ = table[key]
        text = (text or '').strip() if isinstance(text, str) else text
        rng_unit = None
        if kind == 'range':
            rng_unit = node.get('unit') or ''
        elif kind == 'spec':
            owner = next((r for _, r in self.ranges() if any(x is node for x in r.get('specs') or [])), {})
            rng_unit = node.get('unit') or owner.get('unit') or ''
        elif kind == 'param':
            rng_unit = node.get('unit') or ''
        if typ == 'str':
            if key in ('label', 'name', 'period') and not text:
                raise EditError(f'{KEY_LABEL.get(key, key)} cannot be empty')
            new = text
            if key in OPTIONAL_RANGE_KEYS and text == '' and key not in node:
                return []
        elif typ == 'int?':
            if text == '':
                new = None
            elif re.fullmatch(r'\d+', text):
                new = int(text)
            else:
                raise EditError('a whole number (or blank)')
        elif typ in ('qty?', 'hz?', 'pqty?'):
            if text == '':
                new = None
            else:
                d = parse_quantity(text, 'Hz' if typ == 'hz?' else rng_unit)
                new = to_float(d, key)
        elif typ == 'sqty':
            d = parse_quantity(text, rng_unit)
            if d < 0 and not may_be_negative(rng_unit):
                raise EditError('cannot be negative in this unit')
            new = to_float(d, key)
        elif typ == 'ratio':
            d = parse_ratio(text)
            if d < 0:
                raise EditError('cannot be negative')
            new = to_float(d, key)
        elif typ == 'bool':
            low = str(text).lower()
            if low in ('true', 'yes', '1', 'on'):
                new = True
            elif low in ('false', 'no', '0', 'off', ''):
                new = False
            else:
                raise EditError('true or false')
        elif typ == 'ints':
            new = parse_ints(text)
        elif typ == 'dir':
            if text not in DIRECTIONS:
                raise EditError('output or input')
            new = text
        elif typ == 'level':
            if text not in LEVELS:
                raise EditError('error or warn')
            new = text
        elif typ == 'json':
            try:
                new = json.loads(text) if text else []
            except ValueError as e:
                raise EditError(f'not valid JSON: {e}')
            if not isinstance(new, list):
                raise EditError('a list ([ ... ]) is expected')
        else:
            raise EditError(f'unsupported field type {typ}')
        if key == 'resolution' and new is not None and new <= 0:
            raise EditError('the resolution must be greater than zero (or blank)')
        changed = [key] if self._set(node, key, new) else []
        if key == 'resolution' and changed:
            if self._set(node, 'res_src', 'edited' if new is not None else ''):
                changed.append('res_src')
        return changed

    def kind_of(self, node) -> str:
        u = self._uid_cur.get(id(node))
        for name, _, n in iter_nodes(self.current):
            if n is node:
                return {'functions': 'function', 'ranges': 'range', 'specs': 'spec', 'params': 'param', 'limits': 'limit', 'problems': 'problem'}[name]
        raise EditError(f'unknown node {u}')

    # info (standard block)
    def edit_info(self, key, text):
        std = self.current.setdefault('standard', {})
        if key in READ_ONLY_INFO:
            raise EditError(f'{key} identifies the sheet in the database and cannot be changed here (a different model is a different sheet)')
        text = (text or '').strip()
        if key == 'confidence_pct':
            if text == '':
                new = None
            else:
                d, suffix = split_number(text)
                if suffix not in ('', '%'):
                    raise EditError('type the confidence as a number of percent, e.g. 95')
                if not Decimal(0) < d < Decimal(100):
                    raise EditError('the confidence level must be between 0 and 100 percent (or blank = not specified)')
                new = to_float(d, key)
        else:
            new = text
        return [key] if self._set(std, key, new) else []

    # notes
    def edit_note(self, number, text):
        notes = self.current.setdefault('notes', {})
        number = str(number)
        if number not in notes:
            raise EditError(f'note {number} does not exist')
        text = (text or '').strip()
        if not text:
            raise EditError('a note cannot be empty (delete it instead)')
        return [number] if self._set(notes, number, text) else []

    def add_note(self, text=''):
        notes = self.current.setdefault('notes', {})
        nums = [int(k) for k in notes if str(k).isdigit()]
        number = str(max(nums, default=0) + 1)
        notes[number] = (text or '').strip() or '(new note: type the text)'
        self._touch()
        return number

    def delete_note(self, number):
        notes = self.current.get('notes') or {}
        if str(number) not in notes:
            raise EditError(f'note {number} does not exist')
        del notes[str(number)]
        self._touch()

    # list areas (limits, problems)
    def list_nodes(self, area):
        return [x for x in self.current.get('limits' if area == 'limits' else 'problems') or [] if isinstance(x, dict)]

    def add_list_item(self, area):
        name = 'limits' if area == 'limits' else 'problems'
        if not isinstance(self.current.get(name), list):
            self.current[name] = []
        item = {'function': '', 'limit': '', 'page': ''} if area == 'limits' else {'level': 'warn', 'where': '', 'what': ''}
        self.current[name].append(item)
        self._register(item)
        self._touch()
        return item

    def delete_list_item(self, area, node):
        name = 'limits' if area == 'limits' else 'problems'
        lst = self.current.get(name) or []
        for i, x in enumerate(lst):
            if x is node:
                del lst[i]
                if not lst and name not in self.original:
                    del self.current[name]
                self._touch()
                return
        raise EditError('that entry no longer exists')

    # rows added / removed
    def add_range_after(self, rng):
        """A copy of `rng` right after it in its function (to be edited).  Returns the new range."""
        f = self.function_of(rng)
        if f is None:
            raise EditError('that row no longer exists')
        new = copy.deepcopy(rng)
        lst = f['ranges']
        idx = next(i for i, x in enumerate(lst) if x is rng)
        lst.insert(idx + 1, new)
        self._register_tree(new, 'range')
        self._touch()
        return new

    def delete_range(self, rng):
        f = self.function_of(rng)
        if f is None:
            raise EditError('that row no longer exists')
        f['ranges'] = [x for x in f['ranges'] if x is not rng]
        self._touch()

    def add_spec_line(self, rng):
        """A copy of the last period line of the range with an EMPTY period (an error until a period is typed)."""
        specs = rng.setdefault('specs', [])
        new = copy.deepcopy(specs[-1]) if specs else {'period': '', 'rel': 0.0, 'fs_rel': 0.0, 'fs_value': 0.0, 'abs': 0.0, 'unit': rng.get('unit') or '', 'le': False, 'raw': ''}
        new['period'] = ''
        specs.append(new)
        self._register(new)
        self._touch()
        return new

    def delete_spec_line(self, rng, spec):
        specs = rng.get('specs') or []
        if len(specs) <= 1:
            raise EditError('a row needs at least one specification line; delete the row instead')
        rng['specs'] = [s for s in specs if s is not spec]
        self._touch()

    # ---- the differences
    def diff(self):
        if self._diff_cache is None:
            self._diff_cache = _compute_diff(self.original, self.current, _UidMatcher(self))
        return self._diff_cache

    def changes_of(self, area=None):
        return [c for c in self.diff() if area in (None, c.area)]

    def change_count(self) -> int:
        return len(self.diff())

    def changed_cells(self):
        """{(line iid, column)} of cells whose value differs from the file (the amber cells)."""
        out = set()
        lines = self.lines()
        by_range = {}
        for ln in lines:
            by_range.setdefault(self.uid(ln.rng), []).append(ln)
        col_of_range = {'label': 'label', 'amp_lo': 'span', 'amp_hi': 'span', 'freq_lo': 'freq', 'freq_hi': 'freq', 'resolution': 'res', 'res_src': 'res', 'page': 'page'}
        for c in self.diff():
            if c.area != 'rows':
                continue
            if c.node == 'range' and c.key in col_of_range:
                for ln in by_range.get(c.uid, [])[:1]:
                    out.add((ln.iid, col_of_range[c.key]))
            elif c.node == 'param' and c.key == 'notes':
                for ln in by_range.get(c.range_uid, [])[:1]:
                    out.add((ln.iid, 'notes'))
            elif c.node == 'spec' and c.key in ('period', 'rel', 'fs_rel', 'fs_value', 'abs'):
                for ln in by_range.get(c.range_uid, []):
                    if ln.spec is not None and self.uid(ln.spec) == c.uid:
                        out.add((ln.iid, c.key))
            elif c.node == 'function' and c.key == 'name':
                for r_uid, lns in by_range.items():
                    if self.uid(lns[0].fn) == c.uid:
                        out.add((lns[0].iid, 'function'))
        return out

    def new_range_uids(self):
        return {c.uid for c in self.diff() if c.area == 'rows' and c.node == 'range' and c.op == 'add'}

    def revert(self, change: Change):
        """Undo one pending change (the node / key goes back to what the file has)."""
        if change.op == 'set':
            node = self._node_for(change)
            if node is None:
                return
            if change.absent == 'old':
                node.pop(change.key, None)
            else:
                node[change.key] = copy.deepcopy(change.old)
            self._touch()
        elif change.op == 'add':
            if change.node == 'range':
                n = self.node(change.uid)
                if n is not None:
                    self.delete_range(n)
            elif change.node == 'note':
                self.current['notes'].pop(str(change.uid), None)
                self._touch()
            elif change.node == 'spec':
                n = self.node(change.uid)
                owner = self.node(change.range_uid)
                if n is not None and owner is not None:
                    owner['specs'] = [s for s in owner['specs'] if s is not n]
                    self._touch()
            elif change.node in ('limit', 'problem'):
                n = self.node(change.uid)
                if n is not None:
                    self.delete_list_item('limits' if change.node == 'limit' else 'issues', n)
            elif change.node == 'info' or change.absent == 'old':
                node = self._node_for(change)
                if node is not None:
                    node.pop(change.key, None)
                    self._touch()
        elif change.op == 'remove':
            self._reinsert(change)

    def revert_all(self):
        self.discard_all()

    def _node_for(self, change):
        if change.area == 'info' or change.node == 'info':
            return self.current.setdefault('standard', {})
        if change.node == 'note':
            return self.current.get('notes')
        if change.node == 'file':
            return self.current
        return self.node(change.uid)

    def _reinsert(self, change):
        if change.node == 'note':
            self.current.setdefault('notes', {})[str(change.uid)] = copy.deepcopy(change.old)
            self._touch()
            return
        node = copy.deepcopy(change.old)
        if change.node == 'range':
            owner_uid = change.extra_parent
            fn = self.node(owner_uid)
            if fn is None:
                raise EditError('the function of that row is gone; discard all changes instead')
            lst = fn['ranges']
            at = 0
            for i, x in enumerate(lst):
                if self.uid(x) == change.after:
                    at = i + 1
            lst.insert(at, node)
            self._register(node, change.uid)
            orig = self.original_node(change.uid) or {}
            for key in ('specs', 'params'):
                olds = orig.get(key) or []
                for i, child in enumerate(node.get(key) or []):
                    # the children get their ORIGINAL ids back, so the comparison sees the same nodes again (not a remove + an add)
                    same = i < len(olds) and self._uid_org.get(id(olds[i]))
                    self._register(child, same if same else None)
            self._touch()
        elif change.node == 'spec':
            owner = self.node(change.range_uid)
            if owner is None:
                raise EditError('the row of that line is gone')
            owner.setdefault('specs', []).append(node)
            self._register(node, change.uid)
            self._touch()
        elif change.node in ('limit', 'problem'):
            name = 'limits' if change.node == 'limit' else 'problems'
            if not isinstance(self.current.get(name), list):
                self.current[name] = []
            self.current[name].append(node)
            self._register(node, change.uid)
            self._touch()
        else:
            raise EditError('this removal cannot be undone one by one; discard all changes instead')

    def summary(self) -> str:
        cs = self.diff()
        if not cs:
            return 'no changes'
        cells = sum(1 for c in cs if c.op == 'set')
        adds = sum(1 for c in cs if c.op == 'add')
        rems = sum(1 for c in cs if c.op == 'remove')
        parts = []
        if cells:
            parts.append(f'{cells} field{"s" if cells != 1 else ""} changed')
        if adds:
            parts.append(f'{adds} added')
        if rems:
            parts.append(f'{rems} removed')
        return ', '.join(parts)


@dataclass
class Line:
    iid: str
    fn: dict
    rng: dict
    spec: object
    first: bool


def parse_ints(text) -> list:
    text = (text or '').strip()
    if not text:
        return []
    parts = [p for p in re.split(r'[\s,;]+', text) if p]
    out = []
    for p in parts:
        if not re.fullmatch(r'\d+', p):
            raise EditError(f'"{p}" is not a note number (type numbers separated by commas)')
        out.append(int(p))
    return sorted(set(out))


def parse_span(text, unit):
    """'2 to 20 A' -> (2, 20); '10 Hz to 1 kHz' -> (10, 1000); '' -> (None, None).  A bare left number takes the unit of the right one ('2 to 20 mA')."""
    text = (text or '').strip()
    if text in ('', '-', '—', 'none'):
        return None, None
    parts = re.split(r'\s+to\s+', text, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise EditError('type a span as "low to high", e.g. 2 to 20 A (or leave it blank)')
    left, right = parts
    d_left, s_left = split_number(left)
    d_right, s_right = split_number(right)
    if not s_left and s_right:
        left = f'{left} {s_right}'
    lo, hi = parse_quantity(left, unit), parse_quantity(right, unit)
    if lo > hi:
        raise EditError('the low end is above the high end')
    return lo, hi


# ------------------------------------------------------------------------------------------------------------ the diff engine
class _UidMatcher:
    """Pairs nodes of the file and the working copy by identity (a cell edit never makes a row 'removed and added')."""

    def __init__(self, doc):
        self.doc = doc

    def pair(self, listname, olist, clist):
        d = self.doc
        o_by = {d._uid_org[id(x)]: x for x in olist if isinstance(x, dict) and id(x) in d._uid_org}
        c_by = {d._uid_cur[id(x)]: x for x in clist if isinstance(x, dict) and id(x) in d._uid_cur}
        pairs = [(o_by[u], c) for u, c in c_by.items() if u in o_by]
        removed = [(u, o) for u, o in o_by.items() if u not in c_by]
        added = [(u, c) for u, c in c_by.items() if u not in o_by]
        return pairs, removed, added

    def uid_of(self, node, side):
        d = self.doc
        return (d._uid_org if side == 'o' else d._uid_cur).get(id(node))


def _natural_key(listname, x):
    if listname == 'functions':
        return (x.get('name'), x.get('direction'))
    if listname == 'ranges':
        return (x.get('label'), x.get('variant'), x.get('kind'), x.get('amp_lo'), x.get('amp_hi'), x.get('freq_lo'), x.get('freq_hi'))
    if listname == 'specs':
        return (x.get('period'),)
    if listname == 'limits':
        return (x.get('function'), x.get('page'))
    if listname == 'problems':
        return (x.get('level'), x.get('where'), x.get('what'))
    return None


class _KeyMatcher:
    """Pairs nodes of two files by their printed identity (used to compare a file with another version of itself)."""

    def __init__(self):
        self._ids = {}
        self._n = 0

    def _uid(self, node):
        k = id(node)
        if k not in self._ids:
            self._n += 1
            self._ids[k] = self._n
        return self._ids[k]

    def pair(self, listname, olist, clist):
        def keyed(lst):
            seen, out = {}, []
            for x in lst:
                if not isinstance(x, dict):
                    continue
                k = _natural_key(listname, x)
                if k is None:
                    k = ('#', len(out))
                n = seen.get(k, 0)
                seen[k] = n + 1
                out.append(((k, n), x))
            return out
        ok, ck = dict(keyed(olist)), dict(keyed(clist))
        pairs = [(ok[k], ck[k]) for k in ck if k in ok]
        removed = [(self._uid(ok[k]), ok[k]) for k in ok if k not in ck]
        added = [(self._uid(ck[k]), ck[k]) for k in ck if k not in ok]
        return pairs, removed, added

    def uid_of(self, node, side):
        return self._uid(node)


def compare_data(old: dict, new: dict) -> list:
    """Changes between two versions of a sheet (loaded files), matched by printed identity.  Used by the history view."""
    return _compute_diff(old, new, _KeyMatcher())


def _short(v, limit=160):
    if isinstance(v, str):
        return v if len(v) <= limit else v[:limit - 1] + '…'
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit - 1] + '…'


def _value_text(key, value, unit=''):
    if value is _ABSENT or value is None:
        return '(blank)' if value is None else '(absent)'
    if key in RATIO_KEYS:
        return fmt_ratio(value) or str(value)
    if key in ('amp_lo', 'amp_hi', 'range_max', 'resolution', 'lo', 'hi', 'fs_value', 'abs'):
        return fmt_quantity(value, unit) or _short(value)
    if key in ('freq_lo', 'freq_hi'):
        return fmt_quantity(value, 'Hz') or _short(value)
    if isinstance(value, str):
        return _short(value) if value != '' else '(blank)'
    return _short(value)


def _compute_diff(orig: dict, cur: dict, matcher) -> list:
    out = []

    def emit(**kw):
        out.append(Change(**kw))

    def scalars(o, c, skip, mk):
        """Field changes of one dict pair; mk(key, old, new, absent) -> dict of Change fields."""
        for k in list(c.keys()) + [k for k in o.keys() if k not in c]:
            if k in skip:
                continue
            ov, cv = o.get(k, _ABSENT), c.get(k, _ABSENT)
            if ov is _ABSENT and cv is _ABSENT:
                continue
            if ov is not _ABSENT and cv is not _ABSENT and ov == cv and type(ov) is type(cv):
                continue
            emit(**mk(k, None if ov is _ABSENT else ov, None if cv is _ABSENT else cv, 'old' if ov is _ABSENT else ('new' if cv is _ABSENT else ''), ov, cv))

    # ---- header block and the file's other top-level keys
    def info_mk(k, ov, cv, absent, o_raw, c_raw):
        return dict(op='set', area='info', node='info', uid=k, key=k, where='Standard info', label=k.replace('_', ' '), old=ov, new=cv, absent=absent,
                    old_text=_value_text(k, o_raw), new_text=_value_text(k, c_raw), path=f'standard.{k}')
    scalars(orig.get('standard') or {}, cur.get('standard') or {}, (), info_mk)

    def top_mk(k, ov, cv, absent, o_raw, c_raw):
        return dict(op='set', area='file', node='file', uid=k, key=k, where='File', label=k, old=ov, new=cv, absent=absent,
                    old_text=_value_text(k, o_raw), new_text=_value_text(k, c_raw), path=k)
    scalars({k: v for k, v in orig.items() if k not in TOP_KEYS or k == 'schema'}, {k: v for k, v in cur.items() if k not in TOP_KEYS or k == 'schema'}, (), top_mk)
    # ---- notes
    on, cn = orig.get('notes') or {}, cur.get('notes') or {}

    def numkey(k):
        return (0, int(k), k) if str(k).isdigit() else (1, 0, str(k))
    for k in sorted(set(on) | set(cn), key=numkey):
        if k in on and k in cn:
            if on[k] != cn[k]:
                emit(op='set', area='notes', node='note', uid=k, key=k, where=f'Note {k}', label='Text', old=on[k], new=cn[k], old_text=_short(on[k]), new_text=_short(cn[k]), path=f'notes.{k}')
        elif k in cn:
            emit(op='add', area='notes', node='note', uid=k, key='', where=f'Note {k}', label='Note added', new=cn[k], new_text=_short(cn[k]), path=f'notes.{k}')
        else:
            emit(op='remove', area='notes', node='note', uid=k, key='', where=f'Note {k}', label='Note removed', old=on[k], old_text=_short(on[k]), path=f'notes.{k}')

    # ---- limits / problems
    for name, area, node, label in (('limits', 'limits', 'limit', 'Limit line'), ('problems', 'issues', 'problem', 'Sheet issue')):
        pairs, removed, added = matcher.pair(name, [x for x in orig.get(name) or []], [x for x in cur.get(name) or []])
        for i, (o, c) in enumerate(pairs):
            u = matcher.uid_of(c, 'c')
            where = f"{label}: {_short(c.get('function') or c.get('where') or '', 60)}"

            def mk(k, ov, cv, absent, o_raw, c_raw, u=u, where=where):
                return dict(op='set', area=area, node=node, uid=u, key=k, where=where, label=k, old=ov, new=cv, absent=absent,
                            old_text=_value_text(k, o_raw), new_text=_value_text(k, c_raw), path=f'{name}[{u}].{k}')
            scalars(o, c, (), mk)
        for u, o in removed:
            emit(op='remove', area=area, node=node, uid=u, key='', where=f"{label}: {_short(o.get('function') or o.get('where') or '', 60)}", label=f'{label} removed',
                 old=copy.deepcopy(o), old_text=_short(o), path=f'{name}[{u}]')
        for u, c in added:
            emit(op='add', area=area, node=node, uid=u, key='', where=f"{label}: {_short(c.get('function') or c.get('where') or '', 60)}", label=f'{label} added',
                 new=copy.deepcopy(c), new_text=_short(c), path=f'{name}[{u}]')

    # ---- functions -> ranges -> specs / params
    f_pairs, f_removed, f_added = matcher.pair('functions', orig.get('functions') or [], cur.get('functions') or [])
    for fo, fc in f_pairs:
        fu = matcher.uid_of(fc, 'c')
        fname = str(fc.get('name', ''))

        def fmk(k, ov, cv, absent, o_raw, c_raw, fu=fu, fname=fname):
            return dict(op='set', area='rows', node='function', uid=fu, key=k, where=f'Function "{fname}"', label=KEY_LABEL.get(k, k), old=ov, new=cv, absent=absent,
                        old_text=_value_text(k, o_raw), new_text=_value_text(k, c_raw), path=f'functions[{fu}].{k}')
        scalars(fo, fc, ('ranges',), fmk)
        r_pairs, r_removed, r_added = matcher.pair('ranges', fo.get('ranges') or [], fc.get('ranges') or [])
        for ro, rc in r_pairs:
            ru = matcher.uid_of(rc, 'c')
            unit = rc.get('unit') or ''
            where = f"{fname} / {rc.get('label', '')}"

            def rmk(k, ov, cv, absent, o_raw, c_raw, ru=ru, where=where, unit=unit):
                return dict(op='set', area='rows', node='range', uid=ru, key=k, where=where, label=KEY_LABEL.get(k, k), old=ov, new=cv, absent=absent,
                            old_text=_value_text(k, o_raw, unit), new_text=_value_text(k, c_raw, unit), path=f'ranges[{ru}].{k}', range_uid=ru, unit=unit)
            scalars(ro, rc, ('specs', 'params'), rmk)
            s_pairs, s_removed, s_added = matcher.pair('specs', ro.get('specs') or [], rc.get('specs') or [])
            for so, sc in s_pairs:
                su = matcher.uid_of(sc, 'c')
                swhere = f"{where} / {sc.get('period', '')}"
                sunit = sc.get('unit') or unit

                def smk(k, ov, cv, absent, o_raw, c_raw, su=su, swhere=swhere, ru=ru, sunit=sunit):
                    return dict(op='set', area='rows', node='spec', uid=su, key=k, where=swhere, label=KEY_LABEL.get(k, k), old=ov, new=cv, absent=absent,
                                old_text=_value_text(k, o_raw, sunit), new_text=_value_text(k, c_raw, sunit), path=f'specs[{su}].{k}', range_uid=ru, unit=sunit)
                scalars(so, sc, (), smk)
            for su, so in s_removed:
                emit(op='remove', area='rows', node='spec', uid=su, key='', where=f"{where} / {so.get('period', '')}", label='Period line removed', old=copy.deepcopy(so),
                     old_text=_short(so.get('raw') or so.get('period')), path=f'specs[{su}]', range_uid=ru)
            for su, sc in s_added:
                emit(op='add', area='rows', node='spec', uid=su, key='', where=f"{where} / {sc.get('period', '')}", label='Period line added', new=copy.deepcopy(sc),
                     new_text=_short(sc.get('raw') or sc.get('period') or '(period to type)'), path=f'specs[{su}]', range_uid=ru)
            p_pairs, p_removed, p_added = matcher.pair('params', ro.get('params') or [], rc.get('params') or [])
            for i, (po, pc) in enumerate(p_pairs):
                pu = matcher.uid_of(pc, 'c')

                def pmk(k, ov, cv, absent, o_raw, c_raw, pu=pu, ru=ru, where=where, i=i, unit=unit):
                    return dict(op='set', area='rows', node='param', uid=pu, key=k, where=f'{where} / value range {i + 1}', label=KEY_LABEL.get(k, k), old=ov, new=cv, absent=absent,
                                old_text=_value_text(k, o_raw, unit), new_text=_value_text(k, c_raw, unit), path=f'params[{pu}].{k}', range_uid=ru)
                scalars(po, pc, (), pmk)
            for pu, po in p_removed:
                emit(op='remove', area='rows', node='param', uid=pu, key='', where=where, label='Value range removed', old=copy.deepcopy(po), old_text=_short(po), path=f'params[{pu}]', range_uid=ru)
            for pu, pc in p_added:
                emit(op='add', area='rows', node='param', uid=pu, key='', where=where, label='Value range added', new=copy.deepcopy(pc), new_text=_short(pc), path=f'params[{pu}]', range_uid=ru)
        orig_ranges = [x for x in fo.get('ranges') or [] if isinstance(x, dict)]
        for ru, ro in r_removed:
            idx = next((i for i, x in enumerate(orig_ranges) if x is ro), 0)
            prev = next((matcher.uid_of(orig_ranges[j], 'o') for j in range(idx - 1, -1, -1)
                         if any(matcher.uid_of(orig_ranges[j], 'o') == matcher.uid_of(pr, 'o') for pr, _ in r_pairs)), None) if idx else None
            ch = Change(op='remove', area='rows', node='range', uid=ru, key='', where=f"{fname} / {ro.get('label', '')}", label='Row deleted', old=copy.deepcopy(ro),
                        old_text=_range_summary(ro), path=f'ranges[{ru}]', after=prev, range_uid=ru)
            ch.extra_parent = fu
            out.append(ch)
        for ru, rc in r_added:
            emit(op='add', area='rows', node='range', uid=ru, key='', where=f"{fname} / {rc.get('label', '')}", label='Row added', new=copy.deepcopy(rc),
                 new_text=_range_summary(rc), path=f'ranges[{ru}]', range_uid=ru)
    for fu, fo in f_removed:
        emit(op='remove', area='rows', node='function', uid=fu, key='', where=f'Function "{fo.get("name", "")}"', label='Function removed', old=copy.deepcopy(fo), old_text=f'{len(fo.get("ranges") or [])} rows',
             path=f'functions[{fu}]')
    for fu, fc in f_added:
        emit(op='add', area='rows', node='function', uid=fu, key='', where=f'Function "{fc.get("name", "")}"', label='Function added', new=copy.deepcopy(fc), new_text=f'{len(fc.get("ranges") or [])} rows',
             path=f'functions[{fu}]')
    return out


def _range_summary(r) -> str:
    u = r.get('unit') or ''
    bits = [str(r.get('label', ''))]
    if r.get('amp_lo') is not None:
        bits.append(f"{fmt_quantity(r.get('amp_lo'), u)} to {fmt_quantity(r.get('amp_hi'), u)}")
    specs = r.get('specs') or []
    if specs:
        s = specs[0]
        bits.append(f"{s.get('period', '')}: {fmt_ratio(s.get('rel')) or '0'} + {fmt_quantity(s.get('abs'), s.get('unit') or u) or '0'}")
    return '; '.join(b for b in bits if b)


# Change gets one attribute outside the dataclass fields (the function a deleted row came from); declared here so dataclass equality is unaffected.
Change.extra_parent = None


# ------------------------------------------------------------------------------------------------------------ validation
@dataclass
class Issue:
    level: str                  # 'error' | 'warn' | 'info'
    code: str
    area: str                   # rows | notes | info | limits | issues | file
    target: object              # range uid (rows), note number (notes), field name (info), node uid (limits / issues), None
    message: str
    where: str = ''
    row: int = 0                # 1-based row number for rows
    existing: bool = False      # an error that the file already had before this edit (shown red, does not block saving)


class Report:
    def __init__(self):
        self.issues: list = []
        self.checks: list = []          # [(level 'ok'|'warn'|'error'|'info', text)] shown under 'Checks before save'

    @property
    def errors(self):
        return [i for i in self.issues if i.level == 'error']

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == 'warn']

    @property
    def new_errors(self):
        """The errors this edit INTRODUCES; only these block saving."""
        return [i for i in self.issues if i.level == 'error' and not i.existing]

    @property
    def existing_errors(self):
        """Errors the file already has without the pending edit: still red, listed as 'existing', never block a save."""
        return [i for i in self.issues if i.level == 'error' and i.existing]

    @property
    def can_save(self) -> bool:
        return not self.new_errors

    def for_target(self, area, target):
        return [i for i in self.issues if i.area == area and i.target == target]

    def row_issues(self, range_uid):
        return self.for_target('rows', range_uid)

    def worst(self, area, target):
        found = self.for_target(area, target)
        if any(i.level == 'error' for i in found):
            return 'error'
        if any(i.level == 'warn' for i in found):
            return 'warn'
        return ''

    def text_for(self, area, target) -> str:
        return '\n'.join(('✕ ' if i.level == 'error' else '⚠ ') + i.message + (' (existing, not from this edit)' if i.existing else '')
                         for i in self.for_target(area, target) if i.level in ('error', 'warn'))


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unit_known(unit) -> bool:
    if not unit:
        return True
    f, sym, _ = view.split_unit(unit)
    return f is not None or unit in sm.SPECIAL.values() or unit in KNOWN_FREE_UNITS


KNOWN_FREE_UNITS = {'dB', 'dBm', 'dBc', 'dBc/Hz', 'ratio', 'PF', 'lux', 'FC', 'La', 'rpm', 'uW/cm2', '%DC', 'deg', 'rad', 'degC', 'degF', 'ohm'}


_ROW_PREFIX = re.compile(r'^Row \d+: ')


def _issue_key(i):
    return (i.area, i.target, i.code, _ROW_PREFIX.sub('', i.message))


def validate(doc: SpecDoc, builder_dir=None) -> Report:
    """The checks of `_validate_core`, with every error that the file ALREADY had (same row / field, same kind, same text) marked `existing`: those stay red
    but only the errors the pending edit introduces block saving.  An edit that fixes an error, or leaves it alone, is not blocked by it."""
    rep = _validate_core(doc, builder_dir)
    if not rep.errors:
        return rep
    try:
        key = doc.raw
        if getattr(doc, '_baseline_for', None) is not key:
            base = _validate_core(SpecDoc.from_bytes(doc.path, doc.raw), builder_dir)
            doc._baseline_keys, doc._baseline_for = {_issue_key(i) for i in base.issues if i.level == 'error'}, key
        known = doc._baseline_keys
    except Exception:
        return rep                                   # no baseline: every error counts as new (the safe side)
    for i in rep.issues:
        if i.level == 'error' and _issue_key(i) in known:
            i.existing = True
    n_old, n_new = len(rep.existing_errors), len(rep.new_errors)
    if n_old:
        rep.checks.append(('warn', f'{n_old} error{"s" if n_old != 1 else ""} already in the file (not from this edit; shown red, they do not block this save)'))
    if n_new:
        rep.checks.append(('error', f'{n_new} error{"s" if n_new != 1 else ""} introduced by this edit (block saving)'))
    return rep


def _validate_core(doc: SpecDoc, builder_dir=None) -> Report:
    """Schema, numbers, units, confidence, note references; sheet checks of the edited rows; what the edit touches.  Errors block saving, warnings do not."""
    rep = Report()
    cur = doc.current
    add = rep.issues.append

    # ---- schema of the blocks
    schema_ok = True
    if not isinstance(cur.get('standard'), dict):
        add(Issue('error', 'schema', 'file', None, 'The "standard" block is missing or not an object.'))
        schema_ok = False
    if not isinstance(cur.get('notes', {}), dict):
        add(Issue('error', 'schema', 'file', None, 'The "notes" block is not an object.'))
        schema_ok = False
    if not isinstance(cur.get('functions'), list):
        add(Issue('error', 'schema', 'file', None, 'The "functions" list is missing.'))
        schema_ok = False
        _finish(doc, rep, 0)
        return rep
    if cur.get('schema') != 1:
        add(Issue('error', 'schema', 'file', None, f'"schema" is {cur.get("schema")!r}; this editor knows schema 1.'))
        schema_ok = False
    for name in ('limits', 'problems'):
        if cur.get(name) is not None and not isinstance(cur.get(name), list):
            add(Issue('error', 'schema', 'file', None, f'"{name}" is not a list.'))
            schema_ok = False
    if doc.original.get('standard', {}).get('model') != cur.get('standard', {}).get('model'):
        add(Issue('error', 'model', 'info', 'model', 'The model identifies the sheet in the database and cannot change.'))

    notes = cur.get('notes') if isinstance(cur.get('notes'), dict) else {}
    note_keys = set(str(k) for k in notes)
    nrows = 0
    new_uids = doc.new_range_uids()
    touched = doc.touched_ranges()
    ords = doc.ordinals()
    seen_note_missing = False
    number_problem = False

    for fi, fn in enumerate(cur.get('functions') or [], 1):
        fwhere = f'function {fi}'
        if not isinstance(fn, dict):
            add(Issue('error', 'schema', 'file', None, f'{fwhere} is not an object.'))
            schema_ok = False
            continue
        fname = fn.get('name')
        if not isinstance(fname, str) or not fname.strip():
            add(Issue('error', 'schema', 'rows', doc.uid(fn) if id(fn) in doc._uid_cur else None, f'{fwhere}: the function name is empty.', where=fwhere))
            schema_ok = False
        if fn.get('direction') not in DIRECTIONS:
            add(Issue('error', 'schema', 'rows', None, f'Function "{fname}": direction must be output or input.', where=fwhere))
            schema_ok = False
        if not isinstance(fn.get('ranges'), list):
            add(Issue('error', 'schema', 'rows', None, f'Function "{fname}": "ranges" is not a list.', where=fwhere))
            schema_ok = False
            continue
        if not fn['ranges']:
            add(Issue('warn', 'empty-function', 'rows', None, f'Function "{fname}" has no rows left (it is ignored by the application).', where=fwhere))
        for r in fn['ranges']:
            if not isinstance(r, dict):
                add(Issue('error', 'schema', 'file', None, f'A row of "{fname}" is not an object.'))
                schema_ok = False
                continue
            nrows += 1
            ru = doc.uid(r)
            row = ords.get(id(r), 0)
            where = f'{fname} / {r.get("label", "")}'

            def err(code, msg, ru=ru, row=row, where=where):
                add(Issue('error', code, 'rows', ru, f'Row {row}: {msg}', where=where, row=row))

            def warn(code, msg, ru=ru, row=row, where=where):
                add(Issue('warn', code, 'rows', ru, f'Row {row}: {msg}', where=where, row=row))
            if not isinstance(r.get('label'), str) or not r.get('label', '').strip():
                err('label', 'the range label is empty.')
            if not isinstance(r.get('kind'), str) or not r.get('kind'):
                err('kind', 'the kind is empty (DCV, ACV, DCI, ...).')
            for key in ('amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'range_max', 'resolution'):
                v = r.get(key)
                if v is not None and not _is_number(v):
                    err('number', f'{KEY_LABEL.get(key, key)} is not a number ({v!r}).')
                    number_problem = True
            if _is_number(r.get('amp_lo')) and _is_number(r.get('amp_hi')) and r['amp_lo'] > r['amp_hi']:
                err('span', 'the span low end is above the high end.')
            if _is_number(r.get('freq_lo')) and _is_number(r.get('freq_hi')) and r['freq_lo'] > r['freq_hi']:
                err('span', 'the frequency low end is above the high end.')
            if (r.get('amp_lo') is None) != (r.get('amp_hi') is None):
                err('span', 'the span needs both a low and a high end (or neither).')
            if (r.get('freq_lo') is None) != (r.get('freq_hi') is None):
                err('span', 'the frequency band needs both a low and a high end (or neither).')
            if _is_number(r.get('resolution')) and r['resolution'] <= 0:
                err('number', 'the resolution must be greater than zero.')
            if r.get('page') is not None and not (isinstance(r.get('page'), int) and not isinstance(r.get('page'), bool)):
                err('page', 'the page is not a whole number.')
            if not isinstance(r.get('unit', ''), str):
                err('unit', 'the unit is not text.')
            elif r.get('unit') and not _unit_known(r['unit']) and ru in touched:
                warn('unit', f'the unit "{r["unit"]}" is not one the application scales (it is shown as typed).')
            elif (r.get('amp_lo') is not None or r.get('resolution') is not None) and not r.get('unit') and ru in touched:
                warn('unit', 'the row has values but no unit.')
            if not isinstance(r.get('qualifiers', []), list):
                err('schema', 'qualifiers is not a list.')
            specs = r.get('specs')
            if not isinstance(specs, list) or not specs:
                err('specs', 'there is no accuracy specification line.')
                specs = []
            seen_periods = set()
            for s in specs:
                if not isinstance(s, dict):
                    err('specs', 'a specification line is not an object.')
                    continue
                su = doc.uid(s) if id(s) in doc._uid_cur else None
                period = s.get('period')
                if not isinstance(period, str) or not period.strip():
                    err('period', 'a specification line has no period (1 yr, 90 day ...).')
                elif period in seen_periods:
                    err('period', f'the period "{period}" appears twice.')
                else:
                    seen_periods.add(period)
                for key in ('rel', 'fs_rel', 'fs_value', 'abs'):
                    v = s.get(key)
                    if not _is_number(v):
                        err('number', f'{KEY_LABEL.get(key, key)} of "{period}" is not a number ({v!r}).')
                        number_problem = True
                    elif v < 0 and not (key in SPEC_QUANTITY and may_be_negative(s.get('unit') or r.get('unit'))):
                        err('number', f'{KEY_LABEL.get(key, key)} of "{period}" is negative.')
                    elif len(Decimal(repr(v)).normalize().as_tuple().digits) > 17:
                        warn('number', f'{KEY_LABEL.get(key, key)} of "{period}" has more than 17 significant digits.')
                if not isinstance(s.get('le', False), bool):
                    err('schema', f'"le" of "{period}" is not true / false.')
                if not isinstance(s.get('unit', ''), str):
                    err('unit', f'the unit of "{period}" is not text.')
                if _is_number(s.get('rel')) and s['rel'] >= 1 and ru in touched:
                    warn('big', f'Reading term of "{period}" is {fmt_ratio(s["rel"])}: 100 % or more.')
            # printed text no longer matching the numbers that were edited
            for c in (c for c in doc.diff() if c.area == 'rows' and c.node == 'spec' and c.range_uid == ru and c.op == 'set' and c.key in ('rel', 'fs_rel', 'fs_value', 'abs', 'le')):
                owner_spec = doc.node(c.uid)
                changed_raw = any(x.node == 'spec' and x.uid == c.uid and x.key == 'raw' for x in doc.diff())
                if owner_spec is not None and not changed_raw:
                    warn('raw', f'the {KEY_LABEL.get(c.key, c.key)} of "{owner_spec.get("period", "")}" was edited but the printed text ("{_short(owner_spec.get("raw", ""), 60)}") was not; '
                                'edit it in Row details if the print should match.')
                    break
            # note references
            for p in r.get('params') or []:
                if not isinstance(p, dict):
                    err('schema', 'a value-range block (params) is not an object.')
                    continue
                refs = p.get('notes', [])
                if not isinstance(refs, list) or any(not isinstance(n, int) or isinstance(n, bool) for n in refs):
                    err('notes', 'note references must be whole numbers.')
                    continue
                for n in refs:
                    if str(n) not in note_keys:
                        err('note-missing', f'note {n} does not exist.')
                        seen_note_missing = True
                for key in ('lo', 'hi'):
                    if p.get(key) is not None and not _is_number(p.get(key)):
                        err('number', f'a value-range {key} is not a number.')
            if ru in new_uids and any(_same_row(r, x) for _, x in doc.ranges() if x is not r and doc.uid(x) not in new_uids):
                warn('new-same', 'this new row has the same values as an existing row; edit it before saving.')

    # ---- header block
    std = cur.get('standard') if isinstance(cur.get('standard'), dict) else {}
    pct = std.get('confidence_pct')
    if pct is not None:
        if not _is_number(pct) or not 0 < pct < 100:
            add(Issue('error', 'confidence', 'info', 'confidence_pct', 'Confidence level must be a number between 0 and 100 percent (or blank = not specified).'))
    for key in ('manufacturer', 'model', 'description'):
        if not isinstance(std.get(key), str) or not std.get(key, '').strip():
            add(Issue('error' if key == 'model' else 'warn', 'info-empty', 'info', key, f'{key} is empty.'))
    for key in INFO_FIELDS:
        if key in std and not (std[key] is None or isinstance(std[key], str) or key == 'confidence_pct'):
            add(Issue('error', 'info-type', 'info', key, f'{key} must be text.'))
    # notes
    for k, v in notes.items():
        if not str(k).isdigit():
            add(Issue('warn', 'note-key', 'notes', str(k), f'Note "{k}" is not numbered; row references are numbers.'))
        if not isinstance(v, str) or not v.strip():
            add(Issue('error', 'note-empty', 'notes', str(k), f'Note {k} is empty.'))
    # limits / problems
    for x in cur.get('limits') or []:
        if isinstance(x, dict):
            for key in ('function', 'limit'):
                if not isinstance(x.get(key), str) or not x.get(key, '').strip():
                    add(Issue('error', 'limit-empty', 'limits', doc.uid(x), f'A limit line has an empty {key}.'))
        else:
            add(Issue('error', 'schema', 'limits', None, 'A limit line is not an object.'))
    for x in cur.get('problems') or []:
        if isinstance(x, dict):
            if x.get('level') not in LEVELS:
                add(Issue('error', 'problem-level', 'issues', doc.uid(x), 'A sheet issue needs level "error" or "warn".'))
            if not isinstance(x.get('what'), str) or not x.get('what', '').strip():
                add(Issue('error', 'problem-empty', 'issues', doc.uid(x), 'A sheet issue has no text.'))
        else:
            add(Issue('error', 'schema', 'issues', None, 'A sheet issue is not an object.'))
    # notes no row refers to
    used = {n for _, r in doc.ranges() for p in (r.get('params') or []) if isinstance(p, dict) for n in (p.get('notes') or []) if isinstance(n, int)}
    for k in notes:
        if str(k).isdigit() and int(k) not in used and any(c.area == 'rows' or (c.area == 'notes' and c.uid == k) for c in doc.diff()) and doc.original.get('notes', {}).get(k) is not None:
            was_used = any(isinstance(p, dict) and int(k) in (p.get('notes') or []) for _, r in _all_ranges(doc.original) for p in (r.get('params') or []))
            if was_used:
                add(Issue('warn', 'note-unused', 'notes', str(k), f'Note {k} is no longer referenced by any row.'))

    # sheet checks that the edit made worse
    if schema_ok:
        try:
            before = doc.sheet_issues_before()
            for i in (sm.validate_data(doc.current) if any(c.area == 'rows' for c in doc.diff()) else []):
                if (i['level'], i['where'], i['what']) not in before:
                    target, row = _row_for_where(doc, i['where'])
                    add(Issue('warn', 'sheet-check', 'rows' if target else 'file', target, f'Sheet check ({i["level"]}): {i["what"]}', where=i['where'], row=row))
        except Exception as exc:                      # a malformed sheet must not crash the editor; the schema errors above say what is wrong
            add(Issue('warn', 'sheet-check', 'file', None, f'The sheet check could not run on the edited sheet ({type(exc).__name__}).'))

    if not doc.style.exact:
        add(Issue('warn', 'layout', 'file', None, 'The file is not laid out the way the builder scripts write it; saving will reformat the whole file (the documented diff lists only the real changes).'))
    _finish(doc, rep, nrows, schema_ok=schema_ok, number_problem=number_problem, note_missing=seen_note_missing)
    return rep


def _all_ranges(data):
    for f in data.get('functions') or []:
        for r in (f.get('ranges') or []) if isinstance(f, dict) else []:
            if isinstance(r, dict):
                yield f, r


def _same_row(a, b) -> bool:
    keys = ('label', 'kind', 'unit', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'resolution', 'range_max', 'specs')
    return all(a.get(k) == b.get(k) for k in keys)


def _row_for_where(doc, where):
    """validate_data names a row 'function / label (p.N)': find it among the current ranges."""
    for f, r in doc.ranges():
        if where == f"{f.get('name')} / {r.get('label')} (p.{r.get('page', '?')})":
            return doc.uid(r), doc.ordinal(r)
    return None, 0


def _finish(doc, rep, nrows, schema_ok=True, number_problem=False, note_missing=False):
    errs = rep.errors
    schema_errs = [i for i in errs if i.code in ('schema', 'label', 'kind', 'specs', 'period', 'page', 'model', 'info-type', 'limit-empty', 'problem-level', 'problem-empty', 'note-empty')]
    rep.checks.append(('error' if schema_errs else 'ok', f'Schema valid, {nrows} rows' if not schema_errs else f'Schema: {len(schema_errs)} problem{"s" if len(schema_errs) != 1 else ""}'))
    num_errs = [i for i in errs if i.code in ('number', 'span')]
    rep.checks.append(('error' if num_errs else 'ok', 'Numbers and units parse (Decimal)' if not num_errs else f'Numbers / spans: {len(num_errs)} problem{"s" if len(num_errs) != 1 else ""}'))
    conf = doc.current.get('standard', {}).get('confidence_pct') if isinstance(doc.current.get('standard'), dict) else None
    conf_err = [i for i in errs if i.code == 'confidence']
    if conf_err:
        rep.checks.append(('error', conf_err[0].message))
    elif conf is None:
        rep.checks.append(('warn', 'Confidence level not specified: divisor 2.0 (k = 2 assumed)'))
    else:
        d = divisor_for(conf)
        rep.checks.append(('ok', f'Confidence {conf:g} % gives divisor {d[0]:g}' + ('' if d[1] else ' (nearest standard level; set the divisor in Standards Specs if another is wanted)')))
    ref_errs = [i for i in errs if i.code in ('note-missing', 'notes')]
    rep.checks.append(('error' if ref_errs else 'ok', 'All note references resolve' if not ref_errs else f'{len(ref_errs)} note reference{"s" if len(ref_errs) != 1 else ""} to notes that do not exist'))
    cs = doc.diff()
    touches_rows = any(c.area == 'rows' for c in cs) or any(c.node == 'info' and c.key == 'confidence_pct' for c in cs)
    if touches_rows:
        rep.issues.append(Issue('warn', 'budget', 'file', None, 'This edit feeds uncertainty budgets: reports generated after it use the new numbers (issued reports are not recomputed).'))
    if cs:
        rep.issues.append(Issue('info', 'verified', 'file', None, 'Procedures that use this standard: only the owner marks a procedure verified; see the verified-status line below.'))


def divisor_for(pct):
    """(divisor, exact table match) the way specmanager.StandardSpec.divisor turns a confidence level into a divisor."""
    table = {68.27: 1.0, 90.0: 1.645, 95.0: 2.0, 95.45: 2.0, 99.0: 2.576, 99.73: 3.0}
    near = min(table, key=lambda x: abs(x - pct))
    return table[near], abs(near - pct) < 0.01


# ------------------------------------------------------------------------------------------------------------ what else the edit touches
def procedures_listing(spec_file, directory=None):
    """Procedures whose sidecar names this file anywhere in its fingerprint / specs lists (their 'verified' status would change when it changes)."""
    base = Path(directory) if directory else HERE / 'Procedures'
    out = []
    for f in sorted(base.glob('*.procedure.json')):
        try:
            text = f.read_text(encoding='utf-8')
            data = json.loads(text)
        except (OSError, ValueError):
            continue
        fp = json.dumps(data.get('fingerprint') or {}) + json.dumps(data.get('specs') or [])
        if spec_file in fp:
            out.append(data.get('id') or f.stem)
    return out


def builders_for(spec_file, directory=None):
    """The builder scripts in specs/ that write this file (by name).  Every one of them overwrites the file without asking; (script, how found)."""
    base = Path(directory) if directory else HERE / 'specs'
    found = []
    for f in sorted(base.glob('build_*.py')):
        try:
            text = f.read_text(encoding='utf-8')
        except OSError:
            continue
        stem = spec_file[:-len('_standard.json')] if spec_file.endswith('_standard.json') else spec_file
        if spec_file in text or f"'{stem}'" in text:
            found.append((f.name, 'names the file'))
    if not found and spec_file.startswith('fluke_') and (base / 'build_standard_spec.py').exists():
        found.append(('build_standard_spec.py', 'writes fluke_<model>_standard.json from a SpecTrack PDF'))
    return found


def list_sheets(directory=None):
    """[(path, model, description)] of the sheets in specs/standards/ (the files specmanager.seed loads)."""
    base = Path(directory) if directory else STANDARDS_DIR
    out = []
    for f in sorted(base.glob('*_standard.json')):
        try:
            std = json.loads(f.read_text(encoding='utf-8')).get('standard') or {}
        except (OSError, ValueError):
            std = {}
        out.append((f, str(std.get('model', '')), str(std.get('description', ''))))
    return out


def sheet_for_model(model, directory=None):
    for f, m, _ in list_sheets(directory):
        if m.strip().lower() == str(model).strip().lower():
            return f
    return None
