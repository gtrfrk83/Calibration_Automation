"""Specification manager: the published accuracy specifications of the laboratory's STANDARDS (calibrators), kept in lab_registry.sqlite3.

The uncertainty budget (uncertainty_budget.py) reads these specifications to work out the standard's contribution to a reported
expanded measurement uncertainty (EMU), and then checks the result against the A2LA scope of accreditation so that nothing is
reported below the laboratory's CMC.

    import specmanager as sm
    sm.seed()                                    # loads specs/standards/*.json the first time (idempotent)
    std = sm.standard('5522A')                   # by model, asset id or database id; None when unknown
    hit = std.lookup('DCV', 0.1)                 # -> Hit(row, spec, period): spec = absolute +/- error limit in SI base units
    hit = std.lookup('ACV', 1.0, frequency=1e3)

Rules (project):
  * calibration_procedures.sqlite3 is never touched; everything here lives in lab_registry.sqlite3 (new tables, existing ones unchanged).
  * No function raises on a damaged / missing database: callers get None / empty lists.
  * Values are SI base units (V, A, ohm, Hz, F, W, H, s, degC, degF).  Display scaling is done only by the UI.
  * Nothing is guessed: unparsed text stays in 'raw', and suspicious rows are listed by validate() instead of being corrected.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
import appdata  # noqa: E402
DB = appdata.db_path('lab_registry.sqlite3')
SPEC_DIR = HERE / 'specs' / 'standards'

# ------------------------------------------------------------------------------------------------------------ units
PREFIX = {'p': 1e-12, 'n': 1e-9, 'µ': 1e-6, 'μ': 1e-6, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'M': 1e6, 'G': 1e9}
SPECIAL = {'°C': 'degC', '°F': 'degF', '°': 'deg', 'rpm': 'rpm', 'PF': 'PF', '%DC': '%DC'}
BASE = ('Vpp', 'App', 'Ohm', 'ohm', 'Hz', 'sec', 'V', 'A', 'F', 'W', 'H', 'S', 's')
_ANNOT = re.compile(r'\s*\(([A-Z])\)\s*$')
_NUM = r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'


def to_base(value, unit_text):
    """(value in SI base unit, base unit symbol, annotation letter or ''): 329.9999 mV -> (0.3299999, 'V', ''); 5 °C (E) -> (5, 'degC', 'E')."""
    unit_text = (unit_text or '').strip()
    annot = ''
    m = _ANNOT.search(unit_text)
    if m:
        annot, unit_text = m.group(1), unit_text[:m.start()].strip()
    if unit_text in SPECIAL:
        return float(value), SPECIAL[unit_text], annot
    for b in BASE:
        if unit_text.endswith(b):
            pre = unit_text[:-len(b)]
            if pre == '' or pre in PREFIX:
                sym = {'Ohm': 'ohm', 'sec': 's', 'Vpp': 'Vpp', 'App': 'App'}.get(b, b)
                return float(value) * PREFIX.get(pre, 1.0), sym, annot
    return float(value), unit_text, annot


def decimals(text):
    m = re.match(r'[-+]?\d*\.?(\d*)', text.replace('E', 'e'))
    mant = text.lower().split('e')[0]
    return len(mant.split('.')[1]) if '.' in mant else 0


# ------------------------------------------------------------------------------------------------------------ parsing the sheet text
_PARAM = re.compile(
    rf'^(?:\[(?P<tag>[^\]]+)\]\s*)?(?P<lo>{_NUM})\s*(?P<ulo>[^\d\s{{][^\s{{]*(?:\s\([A-Z]\))?)?\s+to\s+(?P<hi>{_NUM})\s*'
    rf'(?P<uhi>[^\s{{][^\s{{]*(?:\s\([A-Z]\))?)?\s*(?:\{{Notes:\s*(?P<notes>[\d,\s]+)\}})?$')


def parse_param(text):
    """'0 mV to 329.9999 mV', '[Voltage] 0 V to 1000 V', '1 kHz to 10 kHz {Notes: 6}' -> dict, or None if it is not a value range."""
    m = _PARAM.match(text.strip())
    if not m:
        return None
    ulo, uhi = m.group('ulo') or m.group('uhi') or '', m.group('uhi') or m.group('ulo') or ''
    lo, unit, a1 = to_base(m.group('lo'), ulo)
    hi, unit2, a2 = to_base(m.group('hi'), uhi)
    if unit != unit2:
        return None
    return dict(tag=m.group('tag') or '', lo=lo, hi=hi, unit=unit, text=text.strip(), annot=a1 or a2,
                notes=[int(x) for x in re.findall(r'\d+', m.group('notes') or '')])


def _split_terms(inner):
    out, depth, cur = [], 0, ''
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        if depth == 0 and inner[i:i + 3] == ' + ':
            out.append(cur); cur = ''; i += 3; continue
        cur += ch; i += 1
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def parse_spec(text):
    """'[1 yr] Accuracy: +/-(20 ppm I.V. + 0.001 mV)' -> dict(period, rel, fs_rel, fs_value, abs, unit, ...).  Unparsed -> dict(error=...)."""
    raw = text.strip()
    pm = re.match(r'\[([^\]]+)\]\s*Accuracy:\s*(.*)$', raw)
    out = dict(period=pm.group(1) if pm else '', rel=0.0, fs_rel=0.0, fs_value=0.0, abs=0.0, unit='', le=False, raw=raw)
    if not pm:
        out['error'] = 'not an accuracy line'
        return out
    body = pm.group(2).strip()
    if body.startswith('<='):
        out['le'] = True
        body = body[2:]
    elif body.startswith('+/-'):
        body = body[3:]
    body = body.strip()
    if body.startswith('(') and body.endswith(')'):
        body = body[1:-1]
    try:
        for term in _split_terms(body):
            m = re.match(rf'^({_NUM})\s*(ppm|%)\s*I\.V\.$', term)
            if m:
                out['rel'] += float(m.group(1)) * (1e-6 if m.group(2) == 'ppm' else 1e-2)
                continue
            m = re.match(rf'^({_NUM})\s*%\s*F\.S\.\{{"Full Scale" = ({_NUM})\s*(\S+)\}}$', term)
            if m:
                v, u, _ = to_base(m.group(2), m.group(3))
                out['fs_rel'] += float(m.group(1)) * 1e-2
                out['fs_value'] = v
                out['unit'] = out['unit'] or u
                continue
            m = re.match(rf'^({_NUM})\s*(\S.*)$', term)
            if m:
                v, u, _ = to_base(m.group(1), m.group(2))
                out['abs'] += v
                out['unit'] = out['unit'] or u
                continue
            raise ValueError(term)
    except ValueError as exc:
        out['error'] = f'cannot read term {exc}'
    return out


def spec_value(spec, value):
    """Absolute +/- limit of one parsed specification at an indicated value (SI)."""
    return spec['rel'] * abs(value) + spec['fs_rel'] * spec['fs_value'] + spec['abs']


# ------------------------------------------------------------------------------------------------------------ classifying a function / range
FUNCTION_KINDS = [  # (regex on the function name, kind) - first match wins
    (r'^voltage, dc', 'DCV'), (r'^voltage, ac', 'ACV'), (r'^current, dc', 'DCI'), (r'^current, ac', 'ACI'),
    (r'^resistance', 'OHM'), (r'^capacitance', 'CAP'), (r'^inductance', 'IND'), (r'^conductance', 'COND'),
    (r'^frequency', 'FREQ'), (r'^temperature', 'TEMP'), (r'^power, dc', 'POWDC'), (r'^power, ac', 'POWAC'),
    (r'^phase', 'PHASE'), (r'^rpm', 'RPM'), (r'^rise time', 'RISE'), (r'^aberrations', 'ABER'), (r'^flatness', 'FLAT'), (r'^time', 'TIME'),
]


def classify(function_name):
    low = function_name.strip().lower()
    for pat, kind in FUNCTION_KINDS:
        if re.match(pat, low):
            variant = ''
            m = re.search(r'\[(.*)\]', function_name)
            if m:
                variant = m.group(1)
            elif kind == 'OHM' and function_name.strip().lower() != 'resistance':
                variant = function_name.strip()
            return kind, variant
    return 'OTHER', ''


def analyse_range(function_name, label, params):
    """Derived numeric fields for a range: kind, variant, amplitude / frequency bands, range maximum, resolution (least digit of the label)."""
    kind, variant = classify(function_name)
    amp = freq = None
    qualifiers = []
    for p in params:
        if p['tag']:
            qualifiers.append(p)
        elif p['unit'] == 'Hz' and kind not in ('FREQ',):
            freq = freq or p
        elif amp is None:
            amp = p
        else:                       # a second value range (power: the voltage and current that make the wattage)
            qualifiers.append(dict(p, tag=p['unit']))
    if amp is None and qualifiers and kind != 'FREQ':      # e.g. '[50 Ohm Impedance] 0 V to 6 V': the tag is only a label
        amp = qualifiers.pop(0)
    out = dict(kind=kind, variant=variant, amp_lo=amp['lo'] if amp else None, amp_hi=amp['hi'] if amp else None,
               unit=amp['unit'] if amp else '', freq_lo=freq['lo'] if freq else None, freq_hi=freq['hi'] if freq else None,
               qualifiers=[dict(tag=q['tag'], lo=q['lo'], hi=q['hi'], unit=q['unit']) for q in qualifiers],
               range_max=None, resolution=None, res_src='')
    m = re.match(rf'^\(?({_NUM})\s*([^\s,@()]+)', label.strip())
    if m and not re.match(r'^\s*to\b', label[m.end():]):
        v, u, _ = to_base(m.group(1), m.group(2))
        if u in ('V', 'A', 'ohm', 'F', 'H', 'W', 'Hz', 'S', 'Vpp', 'App', 's') and out['unit'] in ('', u):
            out['range_max'] = v
            d = decimals(m.group(1))
            if d and m.group(1).rstrip().endswith('9'):   # only a full-scale label (329.9999 mV) shows the digits; a range name (1.2V) does not
                pass
            else:
                d = 0
            if d:   # an integer label ("1000 V") says nothing about the calibrator's resolution
                out['resolution'] = (10.0 ** -d) * (v / float(m.group(1)))
                out['res_src'] = 'label'
    return out


# ------------------------------------------------------------------------------------------------------------ validation
def _fmt(v, unit=''):
    return f'{v:.6g} {unit}'.strip()


def validate_data(data):
    """Problems in an imported sheet (a list of dicts: level 'error' | 'warn', where, what).  Nothing is corrected; the person decides."""
    out = []
    conf = data['standard'].get('confidence_pct')
    if conf is None:
        out.append(dict(level='warn', where='standard', what='Confidence level is not specified on the sheet; set the coverage divisor in the manager before relying on this standard.'))
    seen = {}
    for f in data['functions']:
        bands = defaultdict_list()
        for r in f['ranges']:
            where = f"{f['name']} / {r['label']} (p.{r.get('page', '?')})"
            if r.get('amp_lo') is None and r.get('kind') not in ('OTHER',):
                out.append(dict(level='warn', where=where, what='no value range found for this entry'))
            if not r.get('specs'):
                out.append(dict(level='error', where=where, what='no accuracy specification'))
            for s in r.get('specs', []):
                if s.get('error'):
                    out.append(dict(level='error', where=where, what=f"cannot read specification: {s['raw']}"))
            # value range against the range maximum
            if r.get('range_max') is not None and r.get('amp_hi') is not None and abs(r['range_max']) > 0:
                rm, hi = abs(r['range_max']), abs(r['amp_hi'])
                if not math.isclose(rm, hi, rel_tol=0.02) and r['kind'] not in ('TEMP', 'FREQ'):
                    out.append(dict(level='error', where=where, what=f"value range ends at {_fmt(r['amp_hi'], r['unit'])} but the range is {_fmt(r['range_max'], r['unit'])}"))
            # the printed range band vs the parameter (compared in SI base units)
            m = re.match(rf'^\(?({_NUM})\s*([^\d\s][^\s,@()]*)?\s+to\s+({_NUM})\)?\s*([^\s,@()]+)?', r['label'].strip())
            if m and r.get('amp_lo') is not None and r['kind'] not in ('FREQ', 'ABER', 'TIME', 'RISE'):
                u1, u2 = (m.group(2) or m.group(4) or ''), (m.group(4) or m.group(2) or '')
                lo_l, _, _ = to_base(m.group(1), u1)
                hi_l, unit_l, _ = to_base(m.group(3), u2)
                if unit_l == r['unit'] or not unit_l:
                    if not math.isclose(lo_l, r['amp_lo'], rel_tol=1e-6, abs_tol=1e-12) or not math.isclose(hi_l, r['amp_hi'], rel_tol=1e-6, abs_tol=1e-12):
                        out.append(dict(level='warn', where=where, what=f"printed range '{r['label'].split(',')[0].split('@')[0].strip()}' differs from its value range "
                                                                          f"{_fmt(r['amp_lo'], r['unit'])} to {_fmt(r['amp_hi'], r['unit'])}"))
            # annotation letters (K) inside a J function
            m = re.search(r'Type ([A-Z])', f['name'])
            if m:
                for p in r.get('params', []):
                    if p.get('annot') and p['annot'] != m.group(1):
                        out.append(dict(level='error', where=where, what=f"value range is marked ({p['annot']}) in a Type {m.group(1)} function: {p['text']}"))
            # one-year vs 90-day
            by = {s['period']: s for s in r.get('specs', []) if not s.get('error')}
            a, b = by.get('90 day'), by.get('1 yr')
            if a and b:
                for part, name in (('rel', 'relative'), ('abs', 'fixed'), ('fs_rel', 'full-scale')):
                    if a[part] and b[part] < a[part] * 0.999:
                        out.append(dict(level='error', where=where, what=f"1 yr {name} term ({b[part]:.6g}) is smaller than the 90 day term ({a[part]:.6g})"))
                    elif a[part] and b[part] > a[part] * 4:
                        out.append(dict(level='warn', where=where, what=f"1 yr {name} term ({b[part]:.6g}) is {b[part] / a[part]:.0f} times the 90 day term ({a[part]:.6g}); check for a typing error"))
            if r['unit'] == 'PF' and r.get('amp_lo') is not None:
                lab = re.match(_NUM, r['label'].strip())
                if lab and not math.isclose(float(lab.group()), r['amp_lo'], rel_tol=1e-6):
                    out.append(dict(level='warn', where=where, what=f"power factor is printed {lab.group()} but the value range is {r['amp_lo']:g}"))
            if r.get('amp_lo') is not None and r.get('freq_lo') is None:
                bands[(r['variant'], r['unit'], r.get('freq_lo'), r.get('freq_hi'), tuple((q['tag'], q['lo'], q['hi']) for q in r.get('qualifiers', [])))].append(r)
            key = (f['name'], r['label'], json.dumps([p.get('text') for p in r.get('params', [])]))
            if key in seen and seen[key] != json.dumps(r.get('specs'), sort_keys=True):
                out.append(dict(level='warn', where=where, what='the same range with the same limits appears twice with different specifications'))
            seen[key] = json.dumps(r.get('specs'), sort_keys=True)
        # gaps / overlaps between neighbouring ranges of one function (no frequency band; bipolar ranges count as 0 .. max)
        for key, rs in bands.items():
            def span(r):
                lo, hi = r['amp_lo'], r['amp_hi']
                return (0.0, hi) if lo < 0 < hi and math.isclose(lo, -hi, rel_tol=1e-9) else (min(lo, hi), max(lo, hi))
            rs = sorted(rs, key=span)
            for a, b in zip(rs, rs[1:]):
                if a['unit'] in ('PF', 'deg', 'rpm', '%DC', 's') or a['kind'] in ('POWDC', 'POWAC', 'FLAT', 'ABER'):
                    continue
                (alo, ahi), (blo, bhi) = span(a), span(b)
                if (alo, ahi) == (blo, bhi):
                    continue
                tol = 1e-4 * max(abs(ahi), 1e-9)
                where_b = f"{f['name']} / {b['label']} (p.{b.get('page', '?')})"
                if blo > ahi + tol and not math.isclose(blo, ahi, rel_tol=0.02):
                    out.append(dict(level='warn', where=where_b, what=f"gap between {_fmt(ahi, a['unit'])} and {_fmt(blo, b['unit'])}"))
                elif blo < ahi - tol and not (blo == 0.0 and a['amp_lo'] < 0):     # symmetric +/- ranges are nested by design
                    out.append(dict(level='warn', where=where_b, what=f"overlaps the previous range ({_fmt(blo, b['unit'])} < {_fmt(ahi, a['unit'])})"))
    return out


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


# ------------------------------------------------------------------------------------------------------------ database
SCHEMA = '''
CREATE TABLE IF NOT EXISTS standards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    confidence_text TEXT NOT NULL DEFAULT '',
    confidence_pct REAL,
    divisor REAL,
    period TEXT NOT NULL DEFAULT '1 yr',
    reference TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approve_date TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT '',
    notes_json TEXT NOT NULL DEFAULT '{}',
    problems_json TEXT NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX IF NOT EXISTS standards_model ON standards(model);
CREATE TABLE IF NOT EXISTS standard_assets (
    standard_id INTEGER NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL COLLATE NOCASE,
    serial TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (standard_id, asset_id)
);
CREATE TABLE IF NOT EXISTS spec_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_id INTEGER NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL DEFAULT 0,
    function TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'output',
    kind TEXT NOT NULL DEFAULT 'OTHER',
    variant TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    amp_lo REAL, amp_hi REAL, freq_lo REAL, freq_hi REAL,
    range_max REAL, resolution REAL, res_src TEXT NOT NULL DEFAULT '',
    qualifiers_json TEXT NOT NULL DEFAULT '[]',
    specs_json TEXT NOT NULL DEFAULT '[]',
    note_refs TEXT NOT NULL DEFAULT '',
    page INTEGER,
    edited INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS spec_rows_lookup ON spec_rows(standard_id, kind);
CREATE TABLE IF NOT EXISTS spec_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    who TEXT NOT NULL DEFAULT '',
    standard_id INTEGER,
    row_id INTEGER,
    field TEXT NOT NULL DEFAULT '',
    old TEXT NOT NULL DEFAULT '',
    new TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
'''


@contextmanager
def _db(path=None):
    con = sqlite3.connect(str(path or DB), timeout=5)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _log(con, standard_id, row_id, field, old, new, who='', reason=''):
    con.execute('INSERT INTO spec_changes(at,who,standard_id,row_id,field,old,new,reason) VALUES(?,?,?,?,?,?,?,?)',
                (datetime.now().isoformat(timespec='seconds'), who, standard_id, row_id, field, str(old), str(new), reason))


def import_data(data, who='', replace=True, path=None):
    """Store a parsed sheet (specs/standards/*.json).  An earlier import of the same model is replaced (the change log keeps a record).
    Returns the standard id or None."""
    s = data['standard']
    model = (s.get('model') or '').strip()
    if not model:
        return None
    problems = data.get('problems') or validate_data(data)
    try:
        with _db(path) as con:
            old = con.execute('SELECT id,divisor,period FROM standards WHERE model=?', (model,)).fetchone()
            keep_div, keep_period = (old[1], old[2]) if old else (None, '1 yr')
            if old:
                if not replace:
                    return old[0]
                con.execute('DELETE FROM spec_rows WHERE standard_id=?', (old[0],))
                con.execute('DELETE FROM standards WHERE id=?', (old[0],))
            sid = con.execute(
                '''INSERT INTO standards(manufacturer,model,description,confidence_text,confidence_pct,divisor,period,reference,revision,author,
                   approved_by,approve_date,source_file,imported_at,notes_json,problems_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (s.get('manufacturer', ''), model, s.get('description', ''), s.get('confidence_text', ''), s.get('confidence_pct'), keep_div, keep_period,
                 s.get('reference', ''), s.get('revision', ''), s.get('author', ''), s.get('approved_by', ''), s.get('approve_date', ''),
                 s.get('source_pdf', ''), datetime.now().isoformat(timespec='seconds'), json.dumps(data.get('notes', {})), json.dumps(problems))).lastrowid
            n = 0
            for f in data['functions']:
                for r in f['ranges']:
                    n += 1
                    notes = sorted({x for p in r.get('params', []) for x in p.get('notes', [])})
                    con.execute(
                        '''INSERT INTO spec_rows(standard_id,ordinal,function,direction,kind,variant,label,unit,amp_lo,amp_hi,freq_lo,freq_hi,range_max,
                           resolution,res_src,qualifiers_json,specs_json,note_refs,page) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (sid, n, f['name'], f.get('direction') or 'output', r.get('kind', 'OTHER'), r.get('variant', ''), r['label'], r.get('unit', ''),
                         r.get('amp_lo'), r.get('amp_hi'), r.get('freq_lo'), r.get('freq_hi'), r.get('range_max'), r.get('resolution'), r.get('res_src', ''),
                         json.dumps(r.get('qualifiers', [])), json.dumps(r.get('specs', [])), ','.join(str(x) for x in notes), r.get('page')))
            _log(con, sid, None, 'import', '', f"{n} ranges from {s.get('source_pdf', '')}", who)
            return sid
    except sqlite3.Error:
        return None


def seed(directory=SPEC_DIR, path=None):
    """Load every specs/standards/*.json whose model is not in the database yet.  Returns the number loaded."""
    count = 0
    for f in sorted(Path(directory).glob('*_standard.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            model = data['standard']['model']
            with _db(path) as con:
                if con.execute('SELECT 1 FROM standards WHERE model=?', (model,)).fetchone():
                    continue
            if import_data(data, who='seed', path=path):
                count += 1
        except (OSError, ValueError, KeyError, sqlite3.Error):
            continue
    return count


def standards(path=None):
    try:
        with _db(path) as con:
            rows = con.execute('SELECT id,manufacturer,model,description,confidence_text,confidence_pct,divisor,period,approved_by,approve_date,'
                               'source_file,imported_at,reference,revision,author FROM standards ORDER BY model').fetchall()
            counts = dict(con.execute('SELECT standard_id,COUNT(*) FROM spec_rows GROUP BY standard_id').fetchall())
    except sqlite3.Error:
        return []
    keys = ('id', 'manufacturer', 'model', 'description', 'confidence_text', 'confidence_pct', 'divisor', 'period', 'approved_by', 'approve_date',
            'source_file', 'imported_at', 'reference', 'revision', 'author')
    return [dict(zip(keys, r), rows=counts.get(r[0], 0)) for r in rows]


def standard(key, path=None):
    """Standard by id, model ('5522A', 'Fluke 5522A'), or asset id; None if not found."""
    if key in (None, ''):
        return None
    try:
        with _db(path) as con:
            row = None
            if isinstance(key, int):
                row = con.execute('SELECT id FROM standards WHERE id=?', (key,)).fetchone()
            else:
                text = str(key).strip()
                row = con.execute('SELECT id FROM standards WHERE model=?', (text,)).fetchone()
                if not row:
                    row = con.execute('SELECT standard_id FROM standard_assets WHERE asset_id=?', (text,)).fetchone()
                if not row:
                    models = [m for (m,) in con.execute('SELECT model FROM standards')]
                    low = text.lower()
                    hit = [m for m in models if re.search(rf'(?<![a-z0-9]){re.escape(m.lower())}(?![a-z0-9])', low)]
                    if hit:
                        row = con.execute('SELECT id FROM standards WHERE model=?', (max(hit, key=len),)).fetchone()
            return StandardSpec(row[0], path) if row else None
    except sqlite3.Error:
        return None


def set_standard_field(standard_id, field, value, who='', reason='', path=None):
    """Edit the coverage divisor / default period / description / confidence of a standard (logged)."""
    if field not in ('divisor', 'period', 'description', 'confidence_pct', 'confidence_text', 'approved_by', 'approve_date'):
        raise ValueError(f'field {field} cannot be edited')
    with _db(path) as con:
        old = con.execute(f'SELECT {field} FROM standards WHERE id=?', (standard_id,)).fetchone()
        con.execute(f'UPDATE standards SET {field}=? WHERE id=?', (value, standard_id))
        _log(con, standard_id, None, field, old[0] if old else '', value, who, reason)


def set_assets(standard_id, assets, path=None):
    """assets: [(asset_id, serial)] - the physical units of this model that the lab uses as standards."""
    with _db(path) as con:
        con.execute('DELETE FROM standard_assets WHERE standard_id=?', (standard_id,))
        con.executemany('INSERT OR REPLACE INTO standard_assets VALUES(?,?,?)', [(standard_id, a.strip(), (s or '').strip()) for a, s in assets if a and a.strip()])


def assets_of(standard_id, path=None):
    try:
        with _db(path) as con:
            return con.execute('SELECT asset_id,serial FROM standard_assets WHERE standard_id=? ORDER BY asset_id', (standard_id,)).fetchall()
    except sqlite3.Error:
        return []


def log_for(standard_id, limit=200, path=None):
    try:
        with _db(path) as con:
            return con.execute('SELECT at,who,field,old,new,reason,row_id FROM spec_changes WHERE standard_id=? ORDER BY id DESC LIMIT ?', (standard_id, limit)).fetchall()
    except sqlite3.Error:
        return []


ROW_KEYS = ('id', 'ordinal', 'function', 'direction', 'kind', 'variant', 'label', 'unit', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'range_max',
            'resolution', 'res_src', 'qualifiers_json', 'specs_json', 'note_refs', 'page', 'edited')


def rows_of(standard_id, kind=None, path=None):
    try:
        with _db(path) as con:
            q = f'SELECT {",".join(ROW_KEYS)} FROM spec_rows WHERE standard_id=?' + (' AND kind=?' if kind else '') + ' ORDER BY ordinal'
            data = con.execute(q, (standard_id, kind) if kind else (standard_id,)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in data:
        d = dict(zip(ROW_KEYS, r))
        d['qualifiers'] = json.loads(d.pop('qualifiers_json') or '[]')
        d['specs'] = json.loads(d.pop('specs_json') or '[]')
        out.append(d)
    return out


def update_row(row_id, changes, who='', reason='', path=None):
    """Edit one row ('resolution', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'variant', 'specs').  Every change is logged with who/why."""
    allowed = {'resolution', 'amp_lo', 'amp_hi', 'freq_lo', 'freq_hi', 'variant', 'range_max', 'specs'}
    with _db(path) as con:
        cur = con.execute('SELECT standard_id,' + ','.join(c if c != 'specs' else 'specs_json' for c in allowed) + ' FROM spec_rows WHERE id=?', (row_id,)).fetchone()
        if not cur:
            return False
        sid = cur[0]
        old = dict(zip(allowed, cur[1:]))
        for field, value in changes.items():
            if field not in allowed:
                raise ValueError(f'field {field} cannot be edited')
            col = 'specs_json' if field == 'specs' else field
            store = json.dumps(value) if field == 'specs' else value
            if field == 'resolution':
                con.execute('UPDATE spec_rows SET resolution=?, res_src=? WHERE id=?', (value, 'edited' if value is not None else '', row_id))
            else:
                con.execute(f'UPDATE spec_rows SET {col}=? WHERE id=?', (store, row_id))
            con.execute('UPDATE spec_rows SET edited=1 WHERE id=?', (row_id,))
            _log(con, sid, row_id, field, old[field], store, who, reason)
        return True


def export_data(standard_id, path=None):
    """The standard as the JSON structure specs/standards/*.json uses (round-trips through import_data)."""
    with _db(path) as con:
        s = con.execute('SELECT manufacturer,model,description,confidence_text,confidence_pct,reference,revision,author,approved_by,approve_date,source_file,'
                        'notes_json FROM standards WHERE id=?', (standard_id,)).fetchone()
    if not s:
        return None
    head = dict(zip(('manufacturer', 'model', 'description', 'confidence_text', 'confidence_pct', 'reference', 'revision', 'author', 'approved_by',
                     'approve_date', 'source_pdf'), s[:11]))
    funcs = {}
    for r in rows_of(standard_id, path=path):
        f = funcs.setdefault((r['function'], r['direction']), dict(name=r['function'], direction=r['direction'], ranges=[]))
        params = []
        if r['amp_lo'] is not None:
            params.append(dict(tag='', lo=r['amp_lo'], hi=r['amp_hi'], unit=r['unit'], text='', annot='', notes=[]))
        if r['freq_lo'] is not None:
            params.append(dict(tag='', lo=r['freq_lo'], hi=r['freq_hi'], unit='Hz', text='', annot='', notes=[]))
        f['ranges'].append(dict(label=r['label'], page=r['page'], params=params, specs=r['specs'], kind=r['kind'], variant=r['variant'], amp_lo=r['amp_lo'],
                                amp_hi=r['amp_hi'], unit=r['unit'], freq_lo=r['freq_lo'], freq_hi=r['freq_hi'], qualifiers=r['qualifiers'],
                                range_max=r['range_max'], resolution=r['resolution'], res_src=r['res_src']))
    return dict(schema=1, standard=head, notes=json.loads(s[11] or '{}'), functions=list(funcs.values()))


# ------------------------------------------------------------------------------------------------------------ lookup
DEFAULT_VARIANT = {   # preferred / excluded words in the function's bracket text, per kind (the person can pass variant= to override)
    'ACV': dict(prefer=('sinewave',), exclude=('extended', 'triangle', 'squarewave', 'scope', 'truncated')),
    'ACI': dict(prefer=('lcomp off',), exclude=('non-sinewave', 'squarewave', 'trianglewave')),
    'OHM': dict(prefer=('4-wire',), exclude=()),
    'FREQ': dict(prefer=('field service',), exclude=('scope', 'duty')),
}


class Hit:
    """A matching specification row for one set-point."""

    def __init__(self, row, spec, value):
        self.row, self.spec, self.value = row, spec, value
        self.limit = spec_value(spec, value)         # absolute +/- error limit, SI
        self.period = spec['period']

    def __repr__(self):
        return f"Hit({self.row['function']} / {self.row['label']} [{self.period}] +/-{self.limit:.6g} {self.row['unit']})"


class StandardSpec:
    def __init__(self, standard_id, path=None):
        self.id, self.path = standard_id, path
        info = next((s for s in standards(path) if s['id'] == standard_id), {})
        self.info = info
        self.model = info.get('model', '')
        self.period = info.get('period') or '1 yr'
        self.rows = rows_of(standard_id, path=path)

    # coverage divisor that turns the printed accuracy into a standard uncertainty (k = 1)
    def divisor(self):
        """Coverage divisor.  An explicit value set by the person wins; 95 % -> 2.0 (the laboratory's convention); 99 % -> 2.576; not specified -> 2.0 (what the
        laboratory's uncertainty software does with a standard whose sheet gives no confidence level).  Returns (divisor, source text)."""
        d = self.info.get('divisor')
        if d:
            return float(d), 'set in the specification manager'
        c = self.info.get('confidence_pct')
        table = {68.27: 1.0, 90.0: 1.645, 95.0: 2.0, 95.45: 2.0, 99.0: 2.576, 99.73: 3.0}
        if c is not None:
            near = min(table, key=lambda x: abs(x - c))
            if abs(near - c) < 0.01:
                return table[near], f'{c:g} % confidence on the sheet'
        return 2.0, 'confidence level not specified on the sheet: k = 2 assumed'

    def _eligible(self, kind, variant, direction):
        rules = DEFAULT_VARIANT.get(kind, {})
        rows = [r for r in self.rows if r['kind'] == kind and (direction is None or r['direction'] == direction)]
        if variant:
            sel = [r for r in rows if variant.lower() in r['variant'].lower() or variant.lower() in r['function'].lower()]
            return sel
        rows = [r for r in rows if not any(x in (r['variant'] + ' ' + r['function']).lower() for x in rules.get('exclude', ()))]
        return rows

    def lookup(self, kind, value, frequency=None, variant='', direction='output', period=None, qualifier=None):
        """Specification of the standard at one output value.  The larger limit is used where a value sits on the border of two ranges
        (the same rule as the scope CMC).  Returns Hit or None when no row of this standard covers the point."""
        kind = {'OHM2': 'OHM', 'OHM4': 'OHM'}.get(kind, kind)
        v = abs(value)
        period = period or self.period
        rows = self._eligible(kind, variant, direction)
        pref = DEFAULT_VARIANT.get(kind, {}).get('prefer', ())
        hits = []
        for r in rows:
            if r['amp_lo'] is None:
                continue
            lo, hi = sorted((abs(r['amp_lo']), abs(r['amp_hi']))) if r['amp_lo'] * r['amp_hi'] >= 0 else (0.0, max(abs(r['amp_lo']), abs(r['amp_hi'])))
            if not (lo <= v <= hi):
                continue
            if r['freq_lo'] is not None:
                if frequency is None or not (r['freq_lo'] <= frequency <= r['freq_hi']):
                    continue
            elif frequency not in (None, 0) and kind in ('ACV', 'ACI'):
                continue
            if qualifier is not None:
                if not any(q['lo'] <= abs(qualifier[1]) <= q['hi'] and q['tag'].lower() == qualifier[0].lower() for q in r['qualifiers']):
                    continue
            spec = next((s for s in r['specs'] if s['period'] == period and not s.get('error')), None)
            if spec is None:
                continue
            hits.append(Hit(r, spec, value))
        if not hits:
            return None
        # symmetric (+/-) ranges are nested full-scale ranges: the instrument uses the smallest one that holds the value
        sym = [h for h in hits if h.row['amp_lo'] is not None and h.row['amp_lo'] < 0 < h.row['amp_hi']]
        if sym:
            tight = {}
            for h in sym:
                key = (h.row['function'], h.row['variant'])
                if key not in tight or h.row['amp_hi'] < tight[key]:
                    tight[key] = h.row['amp_hi']
            hits = [h for h in hits if h not in sym or h.row['amp_hi'] <= tight[(h.row['function'], h.row['variant'])]]
        if pref and not variant:
            preferred = [h for h in hits if any(p in (h.row['variant'] + ' ' + h.row['function']).lower() for p in pref)]
            hits = preferred or hits
        return max(hits, key=lambda h: h.limit)

    def resolution(self, hit):
        """(resolution in SI, source text) of the calibrator at this point, from the row's own value (edited) or the printed range digits."""
        r = hit.row
        if r.get('resolution'):
            return float(r['resolution']), ('edited in the manager' if r.get('res_src') == 'edited' else 'last digit of the printed range')
        return None, 'resolution of this range is not recorded'


def values_summary(standard_id, path=None):
    """Counts per kind, for the manager's overview."""
    out = {}
    for r in rows_of(standard_id, path=path):
        out[r['kind']] = out.get(r['kind'], 0) + 1
    return out
