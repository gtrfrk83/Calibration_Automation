"""Cal Processor (Mudcats) .MDD datasheet -> a Datasheet Builder sheet that runs as a MANUAL calibration.  No tkinter, no instrument I/O.

    import mdd_importer_v49, mdd_convert
    parsed = mdd_importer_v49.parse_mdd(path)           # the existing read-only parser: header + test point records, nothing executed
    conv = mdd_convert.convert(parsed)                  # Conversion: .sheet (datasheet_builder.Datasheet), .issues, .rows (one per MDD point), counts
    existing = mdd_convert.find_existing(conv, parsed)  # same file imported before / same name already a procedure (the person is asked)
    res = mdd_convert.register(conv, parsed, who='...') # archive the .MDD, save the sheet (a new version when asked), record the import

SAFETY: only the 'Data Sheet Header' and 'Test Points' records that parse_mdd returns are read.  The MDD's command, script and specification sections are never
looked at, parsed or run; the text taken from a record is cleaned of control characters and cut to a sane length; the number of points is capped.  The size limit,
the "Cal Processor only" check and the table checks stay in parse_mdd (unchanged).

WHAT IS CONVERTED (per test point; the MDD fields are the ones mdd_importer_v49 stores: Text_Function, Text_Nominal, Text_Tolerance, Text_SpecStatement,
Tol_Low, Tol_High, TP_ID, DS_PageNo, Text_AsFound / Text_AsLeft / Text_OutOfTol):
    section        Text_Function (first '~' segment) -> a section (Function) of the sheet; consecutive points with the same text and kind share one
    nominal, unit  Text_Nominal 'value unit~condition...' -> nominal in SI; the unit decides the kind (V A ohm F Hz s degC degF % S); AC / DC from words in the
                   function text or a frequency condition ('@ 60 Hz'); an 'a to b unit' cell (a numeric range printed as the nominal) is a range
    frequency      '@ 60 Hz' / '@ 1 kHz' in the conditions; for a frequency reading the '@ 600 mV' level is the amplitude
    limits         Tol_Low / Tol_High exactly as printed, in the tolerance unit of Text_Tolerance, stored as exact typed limits of the point (no spec expression is invented)
    resolution     the most decimals printed in the limits / nominal -> point setting 'decimals': a typed reading is padded to it (handheld_dmm.pad_reading)
    ranges         NOT in the MDD.  One range per section and printed unit prefix is made from the largest value (so units are shown as printed: mV stays mV);
                   it is marked 'unspecified' and its size is never printed or used
    period         CalInterval ('365 Days') -> the sheet's one time period
    spec text      Text_SpecStatement -> the point's note (shown in the point details); not used for limits
    pass / fail    a point with no numeric limits becomes a functional check (answer Yes / No)
NOT converted: As Found / As Left / Out of Tol values the MDD may already hold (a template is imported, never somebody's readings - a warning says if there were
any), the MDD's page layout and header-row records, commands, scripts, specification tables.  A point whose unit, nominal or limits cannot be read is NOT
converted and is listed in Conversion.issues with the reason; guesses (AC or DC assumed from the wording, a range's midpoint taken as the nominal, a unit
shown without its p-p / rms note) are listed as 'uncertain'.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import datasheet_builder as db

D = Decimal
MAX_POINTS = 5000                 # a sheet of more points than this is refused (a normal datasheet has tens to a few hundred)
MAX_TEXT = 400                    # characters kept from any one field
SOURCE_TAG = 'mdd'

_CTRL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
_NUM = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)'
_PREFIX_EXP = {'': 0, 'p': -12, 'n': -9, 'µ': -6, 'μ': -6, 'u': -6, 'm': -3, 'k': 3, 'K': 3, 'M': 6, 'G': 9}
_PREFIX_SYMBOL = {'': '', 'p': 'p', 'n': 'n', 'µ': 'µ', 'μ': 'µ', 'u': 'µ', 'm': 'm', 'k': 'k', 'K': 'k', 'M': 'M', 'G': 'G'}
_UNIT = re.compile(r'^(?P<prefix>[pnµμumkKMG]?)(?P<base>Vpp|Vrms|V|A|[Oo]hms?|Ω|F|Hz|s|S|°C|°F|%)$')
# printed base -> (SI base unit of the datasheet model, whether an SI prefix is allowed, note when the printed unit says more than the base unit)
_BASE = {'V': ('V', True, ''), 'Vpp': ('V', True, 'peak-to-peak'), 'Vrms': ('V', True, 'rms'), 'A': ('A', True, ''),
         'ohm': ('ohm', True, ''), 'F': ('F', True, ''), 'Hz': ('Hz', True, ''), 's': ('s', True, ''), 'S': ('S', True, ''),
         '°C': ('degC', False, ''), '°F': ('degF', False, ''), '%': ('%', False, '')}


# ============================================================================================================== results
@dataclass
class Issue:
    level: str                  # 'error' (the point is NOT converted) | 'warn' (converted, but uncertain: check it) | 'info'
    code: str
    message: str
    point: int = 0              # 1-based number of the MDD test point (0 = the whole file)
    tp_id: str = ''

    def to_dict(self):
        return dict(level=self.level, code=self.code, message=self.message, point=self.point, tp_id=self.tp_id)


@dataclass
class Conversion:
    sheet: object = None                                    # datasheet_builder.Datasheet
    issues: list = field(default_factory=list)
    rows: list = field(default_factory=list)                # one dict per MDD point: no, tp_id, section, kind, nominal, unit, low, high, frequency, status, message
    source: dict = field(default_factory=dict)              # file name, sha256, header fields
    total: int = 0

    @property
    def converted(self):
        return sum(1 for r in self.rows if r['status'] != 'skipped')

    @property
    def skipped(self):
        return sum(1 for r in self.rows if r['status'] == 'skipped')

    @property
    def uncertain(self):
        return sum(1 for r in self.rows if r['status'] == 'uncertain')

    @property
    def sections(self):
        return sum(1 for fn in self.sheet.functions if fn.points) if self.sheet is not None else 0

    def of_point(self, n):
        return [i for i in self.issues if i.point == n]

    def summary(self):
        return (f'{self.sections} section(s), {self.converted} of {self.total} test point(s) converted, {self.skipped} could not be converted, '
                f'{self.uncertain} uncertain (check them).')


# ============================================================================================================== text helpers
def clean(text, limit=MAX_TEXT):
    """A record field as one safe line: control characters out, white space collapsed, cut to `limit`."""
    t = _CTRL.sub(' ', str(text or ''))
    return re.sub(r'\s+', ' ', t).strip()[:limit]


def cell_parts(text):
    """('first', ['later', ...]) of an MDD cell: '~' separates the lines of a cell."""
    parts = [clean(x) for x in str(text or '').split('~')]
    parts = [x for x in parts if x]
    return (parts[0], parts[1:]) if parts else ('', [])


def decimals_of(text):
    """Number of decimals printed in a number text ('329.10' -> 2); 0 when it has none or is not a number."""
    m = re.match(rf'^\s*({_NUM})\s*$', str(text or ''))
    if not m or 'e' in text.lower():
        return 0
    return len(m.group(1).partition('.')[2])


def parse_unit(text):
    """(prefix symbol, SI base unit, prefix exponent, note) of a printed unit ('kOhm' -> ('k', 'ohm', 3, '')), or None when it is not a unit this import knows."""
    t = clean(text).replace(' ', '').replace('deg', '°').replace('Deg', '°')
    if t in ('Ohm', 'Ohms', 'ohm', 'ohms'):
        t = 'ohm'
    m = _UNIT.match(t)
    if not m:
        return None
    prefix, base = m.group('prefix'), m.group('base')
    if base in ('Ohm', 'Ohms', 'ohm', 'ohms', 'Ω'):
        base = 'ohm'
    if base == 'Vpp' and prefix == 'K':
        return None
    si, allowed, note = _BASE[base]
    if prefix and not allowed:
        return None
    return _PREFIX_SYMBOL[prefix], si, _PREFIX_EXP[prefix], note


def to_si(value, exp):
    return D(value).scaleb(exp)


def parse_number(text):
    try:
        v = D(str(text).strip().replace(' ', ''))
    except (InvalidOperation, ValueError):
        return None
    return v if v.is_finite() else None


def split_value_unit(text):
    """'330.0 mV' -> (Decimal('330.0'), 'mV', '330.0'); 'a to b unit' -> ((a, b), unit); None when it is neither."""
    t = clean(text)
    m = re.match(rf'^({_NUM})\s+to\s+({_NUM})\s*(\S*)$', t)
    if m:
        return (D(m.group(1)), D(m.group(2))), m.group(3), (m.group(1), m.group(2))
    m = re.match(rf'^({_NUM})\s*(\S*)$', t)
    if m:
        return D(m.group(1)), m.group(2), m.group(1)
    return None


def conditions(parts):
    """({'frequency': Decimal Hz, 'level': Decimal V, ...}, [text of the other lines]) from the lines after the first '~' of a nominal cell."""
    found, rest = {}, []
    for line in parts:
        used = False
        for m in re.finditer(rf'@\s*({_NUM})\s*([A-Za-zµμΩ°%]+)', line):
            u = parse_unit(m.group(2))
            if u is None:
                continue
            value = to_si(D(m.group(1)), u[2])
            if u[1] == 'Hz' and 'frequency' not in found:
                found['frequency'] = value
                used = True
            elif u[1] == 'V' and 'level' not in found:
                found['level'] = value
                used = True
        if not used:
            rest.append(line)
    return found, rest


_FFFD = '\ufffd'


def repair_units(text, context=''):
    """The MDD received here holds U+FFFD where the file had a micro or degree sign (the byte was lost before the file reached us).  Only the unit positions
    are repaired, from the context: '�A', '�V', '�s', '�S', '�Hz', '�Ohm' = micro; '�F' = degree F when the function text is about temperature, else microfarad.
    Returns (text, repaired?).  Anything else keeps its U+FFFD (the unit is then unknown and the point becomes a check)."""
    if _FFFD not in text:
        return text, False
    ctx = context.lower()
    deg = 'temp' in ctx or 'thermo' in ctx or 'type k' in ctx

    def one(m):
        return ('\u00b0' if deg else '\u00b5') + m.group(1) if m.group(1) == 'F' else '\u00b5' + m.group(1)
    new = re.sub(_FFFD + r'(F|Hz|Ohm|[AVsS])(?![A-Za-z])', one, text)
    return new, new != text


def spec_text(text):
    """A specification statement for the note: the lost plus-minus sign (U+FFFD before a number, bracket or space) is shown as +/-."""
    return re.sub(_FFFD + r'(?=\s*[\d(.])', '\u00b1', text)


_BARE_RANGE = re.compile(r'^[\d.,]+\s*[A-Za-z\u00b5\u03bc\u03a9\u00b0%\ufffd]*\s*Range$', re.I)


def section_name(func_first, prev):
    """The section of a point from its function text.  '|' (and a bare range label such as '60V Range') continue the section above; 'AC Volts Accuracy: 600mV Range'
    is the section 'AC Volts Accuracy' (the range text goes to the point's label)."""
    t = func_first.strip()
    if not t or t == '|' or _BARE_RANGE.match(t):
        return prev or ''
    m = re.match(r'^(.*?):\s*[^:]*\bRange\b[^:]*(?::.*)?$', t)
    name = clean(m.group(1)) if m and m.group(1).strip() else t
    if prev and name != prev and len(name) > 4 and prev.lower().startswith(name.lower()):
        return prev                                            # 'AC Curren' (a typo in the file) is the section 'AC Current'
    return name


def range_text(*texts):
    for t in texts:
        m = re.search(r'([\d.]+\s*[A-Za-z\u00b5\u03bc\u03a9\u00b0%\ufffd]*\s*Range)\b', t or '')
        if m:
            return clean(m.group(1), 40)
    return ''


def period_from(interval):
    """(period id, label) from CalInterval ('365 Days' -> ('365d', '365 Days')); an unreadable text gives ('mdd', text)."""
    t = clean(interval)
    m = re.match(r'^(\d+)\s*(day|days|d|month|months|mo|year|years|yr|y)?\b', t, re.I)
    if m:
        n, unit = int(m.group(1)), (m.group(2) or 'd').lower()
        sym = 'd' if unit.startswith('d') else 'm' if unit.startswith('mo') else 'y'
        if not m.group(2):
            t = f'{n} Days'                         # Cal Processor prints the interval as a bare number of days ('365')
        return f'{n}{sym}', t
    return 'mdd', t or 'as printed in the MDD'


def slug_id(text, fallback='sec'):
    s = re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower()
    return (s[:30] or fallback)


# ============================================================================================================== kind of a point
def infer_kind(base, func_text, cond_lines, has_frequency, unit_note):
    """(kind, note or '') for a point whose tolerance / reading unit has SI base `base`.  The note is set when the kind was GUESSED (the point is marked uncertain)."""
    text = (func_text + ' ' + ' '.join(cond_lines)).lower()
    ac = bool(re.search(r'\bac\b|\bvac\b|\baac\b|\bv~|\ba~|\brms\b|a\.c\.', text)) or unit_note == 'rms'
    dc = bool(re.search(r'\bdc\b|\bvdc\b|\badc\b|d\.c\.', text))
    if base in ('V', 'A'):
        v = base == 'V'
        if v and 'diode' in text:
            return 'DIODE', ''
        if ac and not dc:
            return ('ACV' if v else 'ACI'), ''
        if dc and not ac:
            return ('DCV' if v else 'DCI'), ''
        if has_frequency or unit_note == 'peak-to-peak':
            return ('ACV' if v else 'ACI'), 'assumed AC: the wording does not say AC or DC, but a frequency / peak-to-peak unit is printed'
        why = 'both AC and DC are named' if (ac and dc) else 'neither AC nor DC is named'
        return ('DCV' if v else 'DCI'), f'assumed DC ({why})'
    if base == 'ohm':
        if re.search(r'4[ -]?wire|four[ -]?wire|\b4w\b|4-w', text):
            return 'OHM4', ''
        return 'OHM2', ''
    simple = {'F': 'CAP', 'Hz': 'FREQ', 's': 'PERIOD', 'degC': 'TEMP', 'degF': 'TEMPF', '%': 'PCT', 'S': 'COND'}
    return simple.get(base), ''


# ============================================================================================================== convert
class _Group:
    """Points of one section while the sheet is built."""

    def __init__(self, name, kind):
        self.name, self.kind, self.items = name, kind, []


def convert(parsed, make=None, model=None, title=None, manual_entry=True) -> Conversion:
    """The Datasheet Builder sheet for a parse_mdd() result.  Never raises for a bad point (it is listed and left out); raises ValueError when the file has too many
    points or nothing at all could be converted."""
    h = parsed.get('header') or {}
    points = parsed.get('points') or []
    if len(points) > MAX_POINTS:
        raise ValueError(f'This datasheet has {len(points)} test points; more than {MAX_POINTS} is refused.')
    conv = Conversion(total=len(points))
    conv.source = dict(sha256=parsed.get('sha256', ''), source_path=str(parsed.get('source_path', '')), filename=Path(str(parsed.get('source_path', ''))).name,
                       header={k: clean(h.get(k, '')) for k in ('Manufacturer', 'Model', 'Description', 'Procedure_Name', 'CalInterval', 'App_Version')})
    hd = conv.source['header']
    make = clean(make if make is not None else hd['Manufacturer'], 80)
    model = clean(model if model is not None else hd['Model'], 80)
    interval = hd['CalInterval']
    title = clean(title if title is not None else f"{hd['Description'] or hd['Procedure_Name'] or 'Cal Processor datasheet'}" + (f' ({period_from(interval)[1]})' if interval else ''), 120)
    pid, plabel = period_from(interval)
    # ---- 1. every MDD point -> a candidate (or an error row) -------------------------------------------------------------------------------------------
    groups, last, prev_section = [], None, ''
    readings_seen = 0
    for n, raw in enumerate(points, 1):
        tp = clean(raw.get('TP_ID', ''), 40)
        row = dict(no=n, tp_id=tp, section='', kind='', nominal=clean(raw.get('Text_Nominal', '')).replace('~', ' | '), unit='', low='', high='',
                   frequency='', status='ok', message='')
        conv.rows.append(row)
        if clean(raw.get('Text_AsFound', '')) or clean(raw.get('Text_AsLeft', '')) not in ('', 'Same') or clean(raw.get('Text_OutOfTol', '')):
            readings_seen += 1
        try:
            cand = _candidate(raw, n, tp, conv, prev_section)
        except _Skip as sk:
            row.update(status='skipped', message=sk.message)
            conv.issues.append(Issue('error', sk.code, sk.message, n, tp))
            last = None
            continue
        row.update(section=cand['section'], kind=cand['kind'], unit=cand['unit_text'], low=cand['low_text'], high=cand['high_text'],
                   frequency=db.format_si(cand['frequency'], 'Hz') if cand['frequency'] is not None else '')
        for level, code, msg in cand['notes']:
            conv.issues.append(Issue(level, code, msg, n, tp))
            if level == 'warn':
                row.update(status='uncertain', message=(row['message'] + '; ' if row['message'] else '') + msg)
        cand['n'], cand['tp'] = n, tp
        if cand.get('shown'):
            row['nominal'] = cand['shown']
        prev_section = cand['section']
        key = (cand['section'], cand['kind'])
        if last is None or last.name != key[0] or last.kind != key[1]:
            last = _Group(*key)
            groups.append(last)
        last.items.append(cand)
    if readings_seen:
        conv.issues.append(Issue('warn', 'readings_present', f'{readings_seen} test point(s) already hold As Found / As Left / Out of Tol text in the MDD. '
                                 'Only the template is imported; those values are NOT copied (a calibration is recorded by running the procedure).'))
    if not groups:
        raise ValueError('No test point of this datasheet could be converted: ' + (conv.issues[0].message if conv.issues else 'no test points.'))
    # ---- 2. the sheet ---------------------------------------------------------------------------------------------------------------------------------
    if not make:
        make = 'Unknown make'
        conv.issues.append(Issue('warn', 'no_make', 'The MDD names no manufacturer: "Unknown make" is used (change it in the preview).'))
    if not model:
        model = 'Unknown model'
        conv.issues.append(Issue('warn', 'no_model', 'The MDD names no model: "Unknown model" is used (change it in the preview).'))
    ds = db.Datasheet(make, model, title, revision=hd['Procedure_Name'])
    ds.set_periods([db.Period(pid, plabel)], pid)
    ds.source = dict(document=f'Cal Processor datasheet {conv.source["filename"] or ""}'.strip() + (f' ({hd["Procedure_Name"]})' if hd['Procedure_Name'] else ''),
                     pages=f'MDD points 1-{len(points)}',
                     note=f'Imported from a Mudcats / Cal Processor .MDD datasheet (sha256 {conv.source["sha256"][:16]}). Nominals and limits are as printed in the MDD; '
                          'ranges are not in the MDD. Check the limits against the source before use.')
    ds.options.update(manual_entry=bool(manual_entry), function_prompt=False, mdd_sha256=conv.source['sha256'])
    ids = set()
    for g in groups:
        fid = slug_id(g.name) + '_' + g.kind.lower()
        base, k = fid, 1
        while fid in ids:
            k += 1
            fid = f'{base}_{k}'
        ids.add(fid)
        fn = ds.add_function(g.kind, g.name, id=fid, settings={'source': SOURCE_TAG})
        _fill_function(ds, fn, g, pid)
    # ---- 3. the sheet must validate: a point that makes it invalid is taken out and listed ----------------------------------------------------------
    for _ in range(len(points) + 2):
        errs = db.errors(db.validate(ds))
        if not errs:
            break
        bad = {}
        known = {p.id for _f, p in ds.all_points()}
        for e in errs:
            last_seg = (getattr(e, 'where', '') or '').rsplit('/', 1)[-1]
            if last_seg in known:
                bad.setdefault(last_seg, str(e))
        if not bad:
            raise ValueError('The converted sheet is not valid: ' + str(errs[0]))
        for fn in ds.functions:
            for p in list(fn.points):
                if p.id in bad:
                    n = int(p.id.rsplit('.p', 1)[1])
                    fn.points.remove(p)
                    conv.rows[n - 1].update(status='skipped', message=bad[p.id])
                    conv.issues.append(Issue('error', 'invalid_point', 'Left out: ' + bad[p.id], n, p.origin.partition(':')[2]))
    ds.functions = [fn for fn in ds.functions if fn.points]
    if not ds.functions:
        raise ValueError('No test point of this datasheet could be converted.')
    for prob in db.warnings(db.validate(ds)):
        m = re.search(r'\.p(\d+)$', getattr(prob, 'where', '') or '')
        n = int(m.group(1)) if m else 0
        if prob.code in ('dup_point',):
            conv.issues.append(Issue('info', prob.code, str(prob), n, ''))
        elif prob.code not in ('no_title', 'nominal_outside_limit'):
            conv.issues.append(Issue('warn', prob.code, str(prob), n, ''))
            if n and conv.rows[n - 1]['status'] == 'ok':
                conv.rows[n - 1].update(status='uncertain', message=str(prob))
    for fn in ds.functions:
        for p in fn.points:
            ds.assignments[p.id] = 'MANUAL'
    conv.sheet = ds
    return conv


class _Skip(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _candidate(raw, n, tp, conv, prev_section=''):
    out = _candidate0(raw, n, tp, conv, prev_section)
    out['shown'] = out.pop('_shown', '')
    return out


def _candidate0(raw, n, tp, conv, prev_section=''):
    """The converted fields of one MDD point, or raises _Skip(code, reason)."""
    func_first, func_rest = cell_parts(raw.get('Text_Function', ''))
    section = section_name(func_first, prev_section)
    context = ' '.join([section, func_first] + func_rest)
    repaired = False
    fixed = []
    for cell in ('Text_Nominal', 'Text_Tolerance'):
        t, r = repair_units(str(raw.get(cell, '')), context)
        repaired = repaired or r
        fixed.append(t)
    nom_first, nom_rest = cell_parts(fixed[0])
    tol_first, tol_rest = cell_parts(fixed[1])
    func_first_fixed, _r = repair_units(func_first, context)
    spec = spec_text(clean(raw.get('Text_SpecStatement', '')).replace('~', ' '))
    spec, r2 = repair_units(spec, context)
    low_raw, high_raw = clean(raw.get('Tol_Low', ''), 60), clean(raw.get('Tol_High', ''), 60)
    notes = []
    if repaired:
        notes.append(('warn', 'unit_char_repaired', 'The file has a lost micro / degree character in the unit; it was restored from the function text (check the unit).'))
    cond, other = conditions(nom_rest + func_rest + [func_first])
    passfail = tol_first.lower().startswith('pass/fail')
    nominal = split_value_unit(nom_first)
    shown = ' | '.join([nom_first] + list(nom_rest))
    label = nom_first + (' @ ' + ' @ '.join(x.lstrip('@ ').strip() for x in nom_rest if x.strip().startswith('@')) if any(x.strip().startswith('@') for x in nom_rest) else '')
    rng_txt = range_text(func_first, *func_rest)
    if rng_txt:
        label += f' ({rng_txt})'
    page = clean(raw.get('DS_PageNo', ''), 20)
    note_bits = [f'MDD point {n}' + (f' (TP {tp}' + (f', page {page}' if page else '') + ')' if tp else '')]
    if spec:
        note_bits.append('Spec: ' + spec)
    if other:
        note_bits.append(' / '.join(other))
    note = '. '.join(note_bits)
    has_limits = bool(low_raw or high_raw) and not passfail
    base = None
    # ---- numeric limits -----------------------------------------------------------------------------------------------------------------------------------
    low = high = None
    unit_t = None
    if has_limits:
        low, high = parse_number(low_raw), parse_number(high_raw)
        if low is None or high is None:
            raise _Skip('limits_unreadable', f'The limits "{low_raw}" / "{high_raw}" are not numbers.')
        if low > high:
            raise _Skip('limits_inverted', f'The low limit {low_raw} is above the high limit {high_raw}.')
        tol_unit = re.sub(r'\[.*?\]', '', tol_first).split()[-1] if re.sub(r'\[.*?\]', '', tol_first).split() else ''
        unit_t = parse_unit(tol_unit)
        if unit_t is None and tol_unit:                                   # unrecognised unit: a pass / fail check, the printed limits kept in the note
            note += f'. Limits as printed (unit "{tol_unit}" not recognised): {low_raw} to {high_raw}'
            notes.append(('warn', 'limit_unit_unknown', f'The unit "{tol_unit}" of the limits is not recognised: converted as a pass / fail check; the printed limits '
                                                         f'{low_raw} to {high_raw} are kept in the point note.'))
            return dict(_shown=shown, section=section or 'Functional checks', kind='CHECK', unit_text='pass / fail', low_text=low_raw, high_text=high_raw, frequency=None,
                        nominal=D(0), label=label or func_first, note=note, decimals=0, lo=None, hi=None, prefix='', notes=notes, amplitude=None)
        if unit_t is None:
            unit_t = parse_unit(nominal[1]) if nominal and nominal[1] else None
            if unit_t is None:
                raise _Skip('unit_unknown', 'No unit is printed for the limits or the nominal.')
            notes.append(('warn', 'unit_from_nominal', 'The limits have no unit text; the unit of the nominal is used.'))
    elif passfail and nominal and isinstance(nominal[0], tuple):          # 'Pass/Fail' with the numeric range printed as the nominal ("0.21 to 31 nF")
        low, high = nominal[0]
        low_raw, high_raw = nominal[2]
        unit_t = parse_unit(nominal[1])
        if unit_t is None:
            raise _Skip('unit_unknown', f'The unit "{nominal[1]}" of the range is not one this import knows.')
        notes.append(('info', 'range_limits', 'Printed as Pass/Fail with a numeric range: the range is used as the limits.'))
    if unit_t is None:                                                    # a functional check: no numeric limits at all
        if not (func_first or nom_first):
            raise _Skip('empty_point', 'The point has no function text and no nominal.')
        notes.append(('warn' if not passfail else 'info', 'functional_check',
                      'No numeric limits are printed: converted as a pass / fail functional check (the technician answers Yes / No).'))
        fields = dict(_shown=shown, section=section or 'Functional checks', kind='CHECK', unit_text='pass / fail', low_text='', high_text='', frequency=None, nominal=D(0),
                      label=label or func_first, note=note, decimals=0, lo=None, hi=None, prefix='', notes=notes, amplitude=None)
        return fields
    prefix, base, exp, unote = unit_t
    # ---- nominal --------------------------------------------------------------------------------------------------------------------------------------------------
    nom_unit = parse_unit(nominal[1]) if nominal and nominal[1] else None
    if nominal is None:
        mid = (low + high) / 2
        value_si = to_si(mid, exp)
        notes.append(('warn', 'nominal_missing', f'The nominal "{nom_first}" is not a number: the middle of the limits is used.'))
    elif isinstance(nominal[0], tuple):
        a, b = nominal[0]
        value_si = to_si((a + b) / 2, nom_unit[2] if nom_unit else exp)
        notes.append(('warn', 'nominal_midpoint', 'The nominal is printed as a range; its middle is used as the nominal (the limits are the range).'))
    else:
        if nom_unit is None and nominal[1]:
            notes.append(('warn', 'nominal_unit', f'The nominal unit "{nominal[1]}" is not known; the unit of the limits ({prefix}{base}) is used.'))
            nom_unit = unit_t
        elif nom_unit is None:
            nom_unit = unit_t
            notes.append(('warn', 'nominal_unit', f'The nominal has no unit; the unit of the limits ({prefix}{base}) is used.'))
        elif nom_unit[1] != base:
            raise _Skip('unit_mismatch', f'The nominal is in {nominal[1]} but the limits are in {prefix}{base}: not the same quantity.')
        value_si = to_si(nominal[0], nom_unit[2])
    lo_si, hi_si = to_si(low, exp), to_si(high, exp)
    kctx = ' '.join([section, func_first] + func_rest)
    inherited = False
    if not re.search(r'\b(ac|dc|vac|vdc|aac|adc)\b', kctx.lower()) and prev_section:
        kctx += ' ' + prev_section                                 # 'Min/Max: Min' follows 'DC Voltage: Min/Max: Max'
        inherited = bool(re.search(r'\b(ac|dc|vac|vdc|aac|adc)\b', prev_section.lower()))
    kind, guess = infer_kind(base, kctx, nom_rest, 'frequency' in cond, unote or (nom_unit[3] if nom_unit else ''))
    if kind is None:
        raise _Skip('unit_unknown', f'No test type is known for the unit {base}.')
    if inherited and not guess:
        notes.append(('warn', 'kind_inherited', 'AC / DC is not named for this point; it is taken from the section above (check it).'))
    if guess:
        notes.append(('warn', 'kind_guessed', guess[0].upper() + guess[1:] + '.'))
    if unote and unote != 'rms':
        notes.append(('info', 'unit_note', f'The printed unit is {prefix}{base} ({unote}); it is shown as {prefix}{db.unit_symbol(base)}.'))
    if not (lo_si <= value_si <= hi_si) and not (isinstance(nominal and nominal[0], tuple)):
        notes.append(('warn', 'nominal_outside_limits', 'The nominal is outside its own limits as printed (limits kept as printed).'))
    decimals = max(decimals_of(low_raw), decimals_of(high_raw), decimals_of(nominal[2]) if nominal and not isinstance(nominal[0], tuple) else 0)
    if base in ('V', 'A') and kind in ('ACV', 'ACI') and 'frequency' not in cond:
        notes.append(('warn', 'no_frequency', 'AC point without a frequency in the nominal text (none is invented).'))
    amplitude = cond.get('level') if kind in ('FREQ', 'PERIOD') else None
    if kind in ('FREQ', 'PERIOD') and amplitude is None:
        notes.append(('warn', 'no_amplitude', 'Frequency / period reading without an input level in the nominal text (none is invented).'))
    return dict(_shown=shown, section=section or db.KINDS[kind]['name'], kind=kind, unit_text=f'{prefix}{db.unit_symbol(base)}', low_text=low_raw, high_text=high_raw,
                frequency=cond.get('frequency') if kind in ('ACV', 'ACI', 'FREQ', 'PERIOD', 'DIODE', 'DCV', 'DCI') or 'frequency' in cond else None,
                nominal=value_si, label=label, note=note, decimals=decimals, lo=lo_si, hi=hi_si, prefix=prefix, notes=notes, amplitude=amplitude,
                base=base)


def _fill_function(ds, fn, group, period):
    """Ranges (one per printed prefix, unspecified), then the points with their exact limits."""
    items = group.items
    if fn.kind == 'CHECK':
        rng = fn.add_range(1, id='r1', settings={'unspecified': True})
        by_prefix = {'': rng}
    else:
        by_prefix = {}
        for pre in dict.fromkeys(it['prefix'] for it in items):
            vals = [abs(v) for it in items if it['prefix'] == pre for v in (it['nominal'], it['lo'], it['hi']) if v is not None]
            fs = max(vals) if vals else D(0)
            if fs <= 0:
                fs = D(10) ** _PREFIX_EXP.get(pre, 0)
            used = {r.full_scale for r in fn.ranges}
            while fs in used:
                fs = fs * (D(1) + D(10) ** -9)                 # equal sizes (1 V and 1000 mV): distinct, ascending; the size is never shown
            rid = f'r{len(fn.ranges) + 1}'
            by_prefix[pre] = fn.add_range(fs, id=rid, display_unit=pre if db.KINDS[fn.kind]['unit'] not in db._NO_PREFIX else '',
                                          settings={'unspecified': True, 'display_prefix': pre})
    for it in items:
        p = db.Point(f'{fn.id}.p{it["n"]:04d}', by_prefix[it['prefix']].id, it['nominal'], it['frequency'], it['amplitude'],
                     label=it['label'], origin=f'{SOURCE_TAG}:{it["tp"]}', note=it['note'])
        fn.points.append(p)
        if it['decimals']:
            p.settings['decimals'] = it['decimals']
        if it['lo'] is not None:
            p.overrides[period] = {'low': db.fmt(it['lo']), 'high': db.fmt(it['hi'])}


# ============================================================================================================== registration
IMPORT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS mdd_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    uid TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    archive TEXT NOT NULL DEFAULT '',
    points_total INTEGER NOT NULL DEFAULT 0,
    points_converted INTEGER NOT NULL DEFAULT 0,
    who TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT ''
);
'''



def archive_dir():
    import appdata
    return appdata.data_dir() / 'mdd_archive'


def _con(path=None):
    con = sqlite3.connect(str(path or db.DB), timeout=5)
    con.executescript(IMPORT_SCHEMA)
    return con


@dataclass
class Existing:
    uid: str
    title: str
    versions: int
    reason: str                 # 'same_file' (this exact .MDD was imported as it) | 'same_name' (a procedure of that name exists)
    kind: str = ''


def find_existing(conv, registry=None, root=None):
    """Procedures this import would collide with: the same .MDD (sha256) imported before, or a registered datasheet with the uid the sheet would get.
    Read only.  The person is asked before anything is created (new copy / new version of one of these / cancel)."""
    out, seen = [], set()
    try:
        con = _con(registry)
        try:
            for uid, version in con.execute('SELECT uid, version FROM mdd_imports WHERE sha256=? ORDER BY id', (conv.source.get('sha256', ''),)):
                row = con.execute('SELECT title, current_version, kind FROM user_datasheets WHERE uid=? AND deleted=0', (uid,)).fetchone() \
                    if _has_table(con, 'user_datasheets') else None
                if row and uid not in seen:
                    seen.add(uid)
                    out.append(Existing(uid, row[0], row[1], 'same_file', row[2] or ''))
        finally:
            con.close()
    except sqlite3.Error:
        pass
    uid = db.make_uid(conv.sheet)
    try:
        for r in db.list_datasheets(root=root, db=registry):
            if r['uid'].lower() == uid.lower() and r['uid'] not in seen:
                seen.add(r['uid'])
                out.append(Existing(r['uid'], r.get('title', ''), r.get('current_version', 0), 'same_name', r.get('kind', '')))
    except Exception:
        pass
    return out


def _has_table(con, name):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


@dataclass
class RegisterResult:
    ok: bool
    uid: str = ''
    version: int = 0
    status: str = ''
    kind: str = ''
    archive: str = ''
    problems: list = field(default_factory=list)
    message: str = ''


def register(conv, parsed, who='', replace_uid=None, registry=None, root=None, archive_to=None):
    """Archive the original .MDD (immutable, named by sha256) and save the sheet as a registered manual procedure.
    replace_uid=None   a NEW procedure (a name already in use gets a '-2' suffix: nothing is overwritten)
    replace_uid='uid'  a NEW VERSION of that procedure (earlier versions are kept, as the Datasheet Builder's save does)
    Returns RegisterResult; nothing is registered when the sheet is not runnable (status 'draft' is reported as not ok)."""
    import mdd_importer_v49
    if conv.sheet is None:
        return RegisterResult(False, message='Nothing was converted.')
    ds = conv.sheet.copy()
    ds.uid = replace_uid or ''
    ds.options['manual_entry'] = True
    try:                                   # a manual calibration sources nothing: its missing uncertainty is waived for the whole sheet, in the open (Sheet check rule 5)
        import datasheet_builder_rules as _rules
        _rules.set_waiver(ds, [_rules.WHOLE_SHEET], 'manual_calibration', 'manual calibration: imported from .MDD, no automation', who=f'import ({who})' if who else 'import')
    except Exception:
        pass
    ds.assignments = {p.id: 'MANUAL' for _f, p in ds.all_points()}
    try:
        arch = mdd_importer_v49.archive_mdd(parsed, archive_to or archive_dir())
    except (OSError, ValueError) as e:
        return RegisterResult(False, message=f'The original .MDD could not be archived: {e}')
    res = db.save(ds, who=who, note=f'Imported from {conv.source.get("filename") or "a .MDD datasheet"} (sha256 {conv.source.get("sha256", "")[:12]})',
                  root=root, db=registry)
    out = RegisterResult(bool(res.ok and res.status == 'ready'), res.uid, res.version, res.status, res.kind, str(arch), list(res.problems))
    if not out.ok:
        out.message = 'The sheet was saved only as a draft: ' + '; '.join(str(p) for p in res.problems[:3]) if res.ok else 'Not saved: ' + '; '.join(str(p) for p in res.problems[:3])
        return out
    try:
        con = _con(registry)
        try:
            con.execute('INSERT INTO mdd_imports(sha256,filename,uid,version,archive,points_total,points_converted,who,imported_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        (conv.source.get('sha256', ''), conv.source.get('filename', ''), res.uid, res.version, str(arch), conv.total, conv.converted,
                         who, datetime.now().isoformat(timespec='seconds')))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        out.problems.append(db.DsProblem('registry', 'The import record could not be written; the procedure was saved.', 'warn'))
    return out
