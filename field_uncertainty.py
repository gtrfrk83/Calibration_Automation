"""Field-assigned uncertainties: what a technician does at a customer site when a test point has no uncertainty.  Toolkit-free (the panel is
qtui/screens/field_uncertainty_panel.py).

    missing = field_uncertainty.annotate(model, app=app, demo=False)   # on a report_review_model.ReviewModel: which rows should carry an uncertainty and have none
    info = field_uncertainty.point_info(model, idx)                     # the point, as the panel shows it
    ranked = field_uncertainty.suggestions(model, idx)                 # [Suggestion], best first, each built from the existing machinery
    chk = field_uncertainty.check_manual(info, '12.5', 'u', ...)       # validate a typed value (Decimal, never float)
    aid = field_uncertainty.add(info, value, source='manual', reason='...', who='...', demo=False)   # lab_registry.sqlite3 (or this session only, in demo)
    rows, details, notes = field_uncertainty.apply_to_rows(rows, details, header, demo=False, reprint=False)    # the report layer (report_pdf calls it)

What it is and what it is not
  * An assignment fills a point that PRINTS NO UNCERTAINTY (or, when the technician explicitly chose 'replace' and gave a reason, replaces a computed one).  It never
    changes a limit, a pass / fail result, a reading, an instrument command or a prompt, and it never overrides a computed uncertainty on its own.
  * A point that should carry an uncertainty is decided by uncertainty_expect.should_have: the same function the readiness check's `uncertainty` finding uses.
  * The value is kept as an exact Decimal in SI base units (display-only SI scaling: 12.5 uV is stored as 0.0000125 V).  Nothing is rounded up or down.
  * New data lives ONLY in lab_registry.sqlite3 (table field_uncertainty, CREATE TABLE IF NOT EXISTS, as uncertainty_fixes does).  calibration_procedures.sqlite3
    is never opened here.  A write is made once, read back and compared; it is never retried (a mismatch is an error and nothing is kept).  Reads may fail quietly.
  * A printed report marks every assigned value ('12.5 uV (assigned in the field, note 1)') and carries a footnote with who / why / when / basis, so an assignment can
    never pass as a computed budget.  A reprint of a saved report uses the notes saved with it and never looks the database up again.
  * Demo mode never persists: assignments go to this process's memory only, are never read from or written to the registry, and the demo marking of every page
    is the report writer's own and is not touched here.
  * No password is ever stored, logged or exported: text that looks like one is refused; nothing here writes to a log.
"""
from __future__ import annotations

import csv
import io
import math
import re
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

MARK = 'assigned in the field'
MARK_RE = re.compile(r'\(assigned in the field, note (\d+)\)')
SESSION_PREFIX = 'suggested:'
MIN_REASON = 5
MAX_VALUE = Decimal('1e12')
MIN_VALUE = Decimal('1e-15')
NO_PASSWORDS = 'Do not type a password or other secret here. Describe the reason in words.'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS field_uncertainty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure_id TEXT NOT NULL,
    point_id TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    nominal_text TEXT NOT NULL DEFAULT '',
    step TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL,
    display TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    who TEXT NOT NULL,
    at TEXT NOT NULL,
    app_version TEXT NOT NULL DEFAULT '',
    first_asset TEXT NOT NULL DEFAULT '',
    first_run INTEGER,
    replaces INTEGER NOT NULL DEFAULT 0,
    replaced_text TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'point',
    group_id TEXT NOT NULL DEFAULT '',
    below_cmc_confirmed INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    withdrawn_at TEXT NOT NULL DEFAULT '',
    withdrawn_by TEXT NOT NULL DEFAULT '',
    withdrawn_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS field_uncertainty_point ON field_uncertainty(procedure_id, point_id, active);
'''
COLS = ('id', 'procedure_id', 'point_id', 'section', 'description', 'nominal_text', 'step', 'kind', 'unit', 'value', 'display', 'source', 'reason', 'who', 'at',
        'app_version', 'first_asset', 'first_run', 'replaces', 'replaced_text', 'scope', 'group_id', 'below_cmc_confirmed', 'active', 'withdrawn_at',
        'withdrawn_by', 'withdrawn_reason')
_INSERT_COLS = tuple(c for c in COLS if c not in ('id', 'first_run', 'active', 'withdrawn_at', 'withdrawn_by', 'withdrawn_reason'))     # first_run is set when the report is written


class Refused(Exception):
    """The assignment is not allowed (a plain sentence for the technician in str(); `code` is for the tests and the panel)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class StorageError(Exception):
    """The registry could not keep the assignment (nothing was kept; the write is not retried)."""


# ------------------------------------------------------------------------------------------------------------------------------ units, Decimal text
PREFIXABLE = ('V', 'A', 'ohm', 'Hz', 'F', 's')
TEMP_UNITS = ('C', 'degC', '°C')
_NAMES = {'V': ('v',), 'A': ('a',), 'ohm': ('ohm', 'ohms'), 'Hz': ('hz',), 'F': ('f',), 's': ('s', 'sec')}
_TEMP_NAMES = ('c', 'degc', '°c')
PREFIXES = {'p': Decimal('1e-12'), 'n': Decimal('1e-9'), 'u': Decimal('1e-6'), 'm': Decimal('1e-3'), '': Decimal(1), 'k': Decimal('1e3'), 'M': Decimal('1e6'),
            'G': Decimal('1e9')}
DEG_C = '\u00b0C'
_SYMBOL = {-12: 'p', -9: 'n', -6: 'µ', -3: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G'}
_NUM = re.compile(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$')


def canon_unit(unit) -> str:
    u = str(unit or '').strip()
    if u in ('ohm', 'Ohm', 'ohms', 'Ω', 'OHM'):
        return 'ohm'
    if u in TEMP_UNITS:
        return 'degC'
    return u


def prefix_choices(unit) -> list:
    """[(symbol_text, factor Decimal)] the unit drop-down offers for a point's natural unit, smallest first: [('nV', 1e-9), ('µV', 1e-6), ...]."""
    u = canon_unit(unit)
    if u in PREFIXABLE:
        base = 'Ohm' if u == 'ohm' else u
        return [(f'{_SYMBOL[e]}{base}', Decimal(10) ** e) for e in (-12, -9, -6, -3, 0, 3, 6, 9)]
    return [('°C' if u == 'degC' else u, Decimal(1))]


def parse_value(text, unit, default_factor=Decimal(1)):
    """(Decimal value in the unit's SI base, '') or (None, message).  `text` is a number with an optional unit ('12.5', '12.5 uV', '1.2e-3 V', '2 kOhm'); a bare number
    is in the unit the panel's drop-down shows (`default_factor`, e.g. 1e-6 for uV).  Decimal arithmetic only.  The unit must be the point's own, with an SI prefix."""
    u = canon_unit(unit)
    t = str(text or '').replace('µ', 'u').replace('μ', 'u').replace('Ω', 'ohm').replace(',', '.')
    m = _NUM.match(t)
    if not m:
        return None, 'Enter a number, for example 12.5.'
    num, tail = m.group(1), m.group(2).strip()
    factor = default_factor
    if tail:
        factor = None
        if u in PREFIXABLE:
            for pre, mult in PREFIXES.items():
                if tail.startswith(pre) and tail[len(pre):].lower() in _NAMES[u]:
                    factor = mult
                    break
            if factor is None:
                return None, f'The unit must be {"ohm" if u == "ohm" else u} with an SI prefix such as m or u (you typed "{tail}").'
        elif u == 'degC':
            if tail.lower() not in _TEMP_NAMES:
                return None, 'The unit must be °C.'
            factor = Decimal(1)
        else:
            if tail.lower() != u.lower():
                return None, f'The unit must be {u or "the unit of the point"} (you typed "{tail}").'
            factor = Decimal(1)
    try:
        value = Decimal(num) * factor
    except (InvalidOperation, ValueError):
        return None, 'Not a number.'
    if not value.is_finite():
        return None, 'Not a number.'
    if value <= 0:
        return None, 'The uncertainty must be greater than zero.'
    if value > MAX_VALUE or value < MIN_VALUE:
        return None, 'That value is not plausible; check the unit prefix.'
    return value, ''


def format_decimal(value, unit) -> str:
    """The printed text of an exact Decimal in SI base units, display-only scaling: Decimal('0.0000125'), 'V' -> '12.5 µV'; ohm prints 'Ohm' (kOhm, MOhm) as the reports do.
    Digits are exactly the Decimal's; nothing is rounded.  Units that are never prefixed (dB, %, °C ...) print as the number and the unit."""
    v = Decimal(value).normalize()
    u = canon_unit(unit)
    if u in PREFIXABLE and v != 0:
        e3 = max(-12, min(9, (v.adjusted() // 3) * 3))
        base = 'Ohm' if u == 'ohm' else u
        mant = format(v.scaleb(-e3).normalize(), 'f')
        return f'{mant} {_SYMBOL[e3]}{base}'
    if u in PREFIXABLE:
        return '0 Ohm' if u == 'ohm' else f'0 {u}'
    return f'{format(v, "f")} {"°C" if u == "degC" else u}'.strip()


def dec(x) -> Decimal:
    """A Decimal from a float the existing machinery produced, via its shortest repr (no binary noise)."""
    return x if isinstance(x, Decimal) else Decimal(repr(float(x)))


def plain(value) -> str:
    return format(Decimal(value), 'f')


# ------------------------------------------------------------------------------------------------------------------------------ people, secrets
_SECRET = re.compile(r'pass\s*word|passwd|\bpwd\b|pass\s*code|\bpin\s*[:=]|secret|credential', re.I)


def contains_secret(*texts) -> bool:
    return any(_SECRET.search(str(t or '')) for t in texts)


def check_people(reason, who, need_reason=True):
    """List of messages (empty = fine) for the reason and the technician's name."""
    out = []
    reason, who = str(reason or '').strip(), str(who or '').strip()
    if len(who) < 2:
        out.append('Enter your name.')
    if need_reason and (len(re.sub(r'[\W_]+', '', reason)) < MIN_REASON):
        out.append('Give a reason (a few words).')
    if contains_secret(reason, who):
        out.append(NO_PASSWORDS)
    return out


# ------------------------------------------------------------------------------------------------------------------------------ identity of a point
def _norm(text) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def point_id(section, description, nominal_text) -> str:
    """The key of a point inside a procedure: the three strings the report row prints (Section, Description, Nominal), whitespace-normalised.  Every engine's report row has
    them, so the same key is found when the point is reached in a run, in the review window and in the PDF."""
    return ' | '.join((_norm(section), _norm(description), _norm(nominal_text)))


def procedure_id_for(app) -> str:
    """A stable name for the procedure behind an engine App (module and model, or the user datasheet's key), the same wherever the App is seen.  '' when nothing is known."""
    try:
        st = getattr(app, 'pm_state', None)
        key = str(getattr(st, 'proc_key', '') or '')
        if key:
            return key
        mod = type(app).__module__
        model = ''
        if st is not None:
            model = str(getattr(st, 'model', '') or '')
        if not model:
            info = getattr(app, 'info', None)
            if isinstance(info, dict):
                model = str(info.get('name') or '')
        if not model:
            model = str(getattr(sys.modules.get(mod), 'MODEL', '') or '')
        return f'{mod}:{model}' if model else mod
    except Exception:
        return ''


def report_procedure_id(details) -> str:
    """The identity the report layer uses: the engine-derived id the details dict carries (details['field_procedure']), else the report's procedure title."""
    d = details or {}
    return _norm(d.get('field_procedure') or d.get('procedure') or '')


# ------------------------------------------------------------------------------------------------------------------------------ the registry table
def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _version() -> str:
    try:
        import suite_info
        return suite_info.full_version()
    except Exception:
        return ''


@contextmanager
def _db():
    """The registry for WRITING (schema created if missing, as uncertainty_fixes does).  Never the demonstration registry."""
    import labregistry
    if Path(str(labregistry.DB)).name.lower() == labregistry.DEMO_DB_NAME:
        raise labregistry.DemoRegistryError('the demonstration registry is read only')
    con = sqlite3.connect(str(labregistry.DB), timeout=5)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


@contextmanager
def _read():
    """The registry for READING: nothing is created.  Yields None when the file or the table does not exist yet (so a report written before any assignment never
    touches the registry)."""
    import labregistry
    path = Path(str(labregistry.DB))
    if not path.is_file() or path.name.lower() == labregistry.DEMO_DB_NAME:
        yield None
        return
    con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=5)
    try:
        has = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_uncertainty'").fetchone()
        yield con if has else None
    finally:
        con.close()


_SESSION: list = []             # demo mode: this process's memory only


def clear_session():
    del _SESSION[:]


def _row(r) -> dict:
    return dict(zip(COLS, r))


def _fetch(demo, where='', args=()):
    if demo:
        out = [dict(r) for r in _SESSION]
        return [r for r in out if _match_mem(r, where, args)]
    try:
        with _read() as con:
            if con is None:
                return []
            return [_row(r) for r in con.execute(f'SELECT {", ".join(COLS)} FROM field_uncertainty {where} ORDER BY id', args).fetchall()]
    except sqlite3.Error:
        return []


def _match_mem(r, where, args):
    if not where:
        return True
    if where == 'WHERE procedure_id=? AND active=1':
        return r['procedure_id'] == args[0] and r['active'] == 1
    if where == 'WHERE active=1':
        return r['active'] == 1
    if where == 'WHERE id=?':
        return r['id'] == args[0]
    return True


def lookup_all(procedure, demo=False) -> dict:
    """{point_id: newest active assignment dict} for one procedure.  Never raises; {} when there is nothing."""
    procedure = _norm(procedure)
    if not procedure:
        return {}
    out = {}
    for r in _fetch(demo, 'WHERE procedure_id=? AND active=1', (procedure,)):
        out[r['point_id']] = r                   # ordered by id: the newest wins
    return out


def lookup(procedure, section, description, nominal_text, demo=False):
    return lookup_all(procedure, demo).get(point_id(section, description, nominal_text))


def all_assignments(include_withdrawn=True, demo=False) -> list:
    """Every assignment, newest first (the lab owner's review list)."""
    rows = _fetch(demo, '' if include_withdrawn else 'WHERE active=1')
    if not include_withdrawn:
        rows = [r for r in rows if r['active'] == 1]
    return sorted(rows, key=lambda r: r['id'], reverse=True)


def status_of(r) -> str:
    return 'active' if r.get('active') else 'withdrawn'


# ------------------------------------------------------------------------------------------------------------------------------ the point, as the panel shows it
@dataclass
class PointInfo:
    procedure: str
    key: str
    idx: int
    step: str
    section: str
    description: str
    nominal_text: str
    kind: str
    unit: str                     # the point's natural unit ('V', 'A', 'ohm', 'Hz', 'F', 's', 'degC', 'dB' ...)
    nominal: float | None
    frequency: float | None
    range: float | None
    low: float | None
    high: float | None
    tolerance_unit: str
    standard: str                 # the calibrator / standard the engine uses for the point ('' = none)
    has_computed: bool
    computed_text: str
    locked: str
    asset: str = ''
    floor: Decimal | None = None
    floor_text: str = ''


def _unit_of(spec) -> str:
    import report_review_model as M
    q = spec.q or {}
    u = M._unit_of(q) if q else spec.unit
    return canon_unit(u or spec.unit)


def point_info(model, idx, procedure=None) -> PointInfo:
    row = model.rows[idx]
    spec = row.spec
    q = spec.q or {}
    printed = str(spec.printed.get('Uncertainty') or '').strip()
    computed = '' if printed in ('', 'N/A') else printed
    info = PointInfo(procedure=_norm(procedure or getattr(model, 'field_procedure', '') or model.procedure or model.title), key=point_id(spec.section, spec.description, spec.nominal_text),
                     idx=idx, step=str(spec.step), section=spec.section, description=spec.description, nominal_text=spec.nominal_text, kind=str(q.get('kind', '')),
                     unit=_unit_of(spec), nominal=q.get('nominal'), frequency=q.get('frequency'), range=q.get('range'), low=spec.low, high=spec.high,
                     tolerance_unit=spec.unit, standard=str(spec.default_std or ''), has_computed=bool(computed), computed_text=computed, locked=str(spec.locked or ''),
                     asset=str(getattr(model, 'asset', '') or ''))
    floor, text = cmc_floor(info, q)
    info.floor, info.floor_text = floor, text
    return info


# ------------------------------------------------------------------------------------------------------------------------------ the lab scope: floor and nearest line
def _decades_outside(x, lo, hi):
    try:
        x, lo, hi = abs(float(x)), float(lo), float(hi)
    except (TypeError, ValueError):
        return math.inf
    if lo <= x <= hi:
        return 0.0
    if x < lo:
        return math.log10(lo / x) if x > 0 and lo > 0 else math.inf
    return math.log10(x / hi) if hi > 0 else math.inf


def nearest_cmc(scope, kind, nominal, frequency=None, source=None, decades=1.0):
    """(value SI, text) of the lab CMC line NEAREST to a point the scope does not cover, applied at the point's own value, or None.  Only a line within `decades` decades
    (in level and, for AC, in frequency) counts.  It is an extrapolation and the caller must say so; nothing here is used unless the technician picks it."""
    try:
        import uncertainty as U
        kind = 'OHM' if kind in ('OHM2', 'OHM4') else kind
        entry = scope.entries.get(('generate', kind)) or scope.entries.get(('measure', kind))
        if entry is None or nominal is None or kind == 'TEMP':
            return None
        value = abs(float(nominal))
        best = None
        if kind in ('ACV', 'ACI'):
            if frequency is None:
                return None
            for block in entry['ranges']:
                for r in block['rows']:
                    da, df = _decades_outside(value, block['lo'], block['hi']), _decades_outside(frequency, r['f_lo'], r['f_hi'])
                    if best is None or da + df < best[0]:
                        best = (da + df, da, df, U._u(r, value, 0.0), r)
            if best is None or best[1] > decades or best[2] > decades:
                return None
            r = best[4]
            return dec(best[3]), f'lab CMC line {_fmt_range(r["f_lo"], r["f_hi"], "Hz")} (nearest to {format_decimal(dec(frequency), "Hz")}), applied at this level'
        src = U._src(source)
        for b in entry['bands']:
            if src and b.get('src') not in (None, src):
                continue
            d = _decades_outside(value, b['lo'], b['hi'])
            if best is None or d < best[0]:
                best = (d, d, 0.0, U._u(b, value), b)
        if best is None or best[1] > decades:
            return None
        return dec(best[3]), 'lab CMC band nearest to this level, applied at this level'
    except Exception:
        return None


def _fmt_range(lo, hi, unit):
    return f'{format_decimal(dec(lo), unit)} to {format_decimal(dec(hi), unit)}'


def cmc_floor(info, q):
    """(Decimal floor, text) the lab CMC gives the point: its own line when the scope covers it, else the nearest line (extrapolated); (None, '') when there is none."""
    try:
        import report_pdf
        sc = report_pdf.scope()
        if sc is None or info.nominal is None or not info.kind or q.get('source') == 'none':
            return None, ''
        std = q.get('standard') or info.standard or None
        direct = sc.dmm(info.kind, info.nominal, q.get('range'), info.frequency, source=std)
        if direct is not None:
            return dec(direct * float(q.get('scale') or 1.0)), 'lab CMC for this point'
        near = nearest_cmc(sc, info.kind, info.nominal, info.frequency, std)
        if near is not None:
            return near[0], near[1]
    except Exception:
        pass
    return None, ''


# ------------------------------------------------------------------------------------------------------------------------------ detection
@dataclass
class Missing:
    idx: int
    key: str
    reason: str                   # 'none' (nothing printed) | 'na' (N/A for lack of a specification)
    covered: bool | None          # does the lab scope cover the point (None = cannot tell)


def _raw_points(app, n):
    fn = getattr(app, 'certificate_rows_and_points', None) if app is not None else None
    if not callable(fn):
        return None
    try:
        _rows, pts = fn()
        return list(pts) if len(pts) == n else None
    except Exception:
        return None


def detect(model, app=None) -> dict:
    """{idx: Missing} for the rows that SHOULD carry an uncertainty (uncertainty_expect.should_have, the readiness check's rule; the oscilloscope / generator adapters'
    own `expects`) and whose engine printed none, or N/A for lack of a specification.  A row the technician typed in the review window is not missing."""
    import uncertainty_expect as X
    out = {}
    raw = _raw_points(app, len(model.rows))
    for i, row in enumerate(model.rows):
        spec = row.spec
        printed = str(spec.printed.get('Uncertainty') or '').strip()
        if printed not in ('', 'N/A') or row.typed is not None:
            continue
        q = spec.q or {}
        if raw is not None:
            p = raw[i]
            should = X.should_have(app, p)
            covered = X.covered(app, p)
        else:
            should = bool(spec.expects) or (bool(q) and q.get('source') != 'none' and X.should_have(app, q))
            covered = X.covered(app, q) if q.get('kind') and q.get('nominal') is not None else None
        if should:
            out[i] = Missing(i, point_id(spec.section, spec.description, spec.nominal_text), 'na' if printed == 'N/A' else 'none', covered)
    return out


def preview_text(a) -> str:
    return f'{a["display"]} ({MARK})'


def annotate(model, app=None, demo=False) -> dict:
    """Mark `model` for the field panel: model.field_missing {idx: Missing}, model.field_procedure, model.field_demo; and attach the stored assignment (if any) to each row as
    row.assigned (the review window then shows what will print).  Never raises; with nothing stored and nothing missing the model is unchanged."""
    try:
        model.field_procedure = procedure_id_for(app) if app is not None else _norm(model.procedure or model.title)
        model.field_demo = bool(demo)
        model.field_missing = detect(model, app)
        stored = lookup_all(model.field_procedure, demo)
        for i, row in enumerate(model.rows):
            a = stored.get(point_id(row.spec.section, row.spec.description, row.spec.nominal_text))
            row.assigned = None
            row.field_gap = i in model.field_missing
            if a is None:
                continue
            printed = str(row.spec.printed.get('Uncertainty') or '').strip()
            if printed in ('', 'N/A') or a['replaces']:
                row.assigned = a
        return model.field_missing
    except Exception:
        model.field_missing = {}
        return {}


# ------------------------------------------------------------------------------------------------------------------------------ suggestions
@dataclass
class Suggestion:
    rank: int
    value: Decimal
    unit: str
    display: str
    basis: str                    # '5560A 1 yr spec, budget k=2'
    machinery: str                # which existing module produced it
    detail: str = ''
    caution: str = ''             # non-empty = an extrapolation / a floor was applied: the panel shows a warning
    standard: str = ''

    @property
    def source(self) -> str:
        return SESSION_PREFIX + self.basis

    @property
    def line(self) -> str:
        return f'{self.display} from {self.basis}'

    @property
    def label(self) -> str:
        return f'Use {self.display}'


def _period(std_key) -> str:
    try:
        import specmanager as sm
        s = sm.standard(std_key)
        return (s.period if s is not None else '') or '1 yr'
    except Exception:
        return '1 yr'


def _candidates(model, idx) -> list:
    import report_review_model as M
    spec = model.rows[idx].spec
    out = []
    for k in [spec.default_std] + list(model.options(idx)) + list(M.SOURCE_STANDARDS):
        if k and k not in out:
            out.append(k)
    try:
        import specmanager as sm
        for s in sm.standards():
            m = s['model']
            if m not in out and not str(m).startswith('A2LA'):
                out.append(m)
    except Exception:
        pass
    return out


def suggestions(model, idx, procedure=None) -> list:
    """Ranked suggestions for one point, each built from the existing machinery (report_review_model.evaluate -> uncertainty_budget / specmanager, the lab scope, and
    uncertainty_fixes).  Best first:
      1  the standard the engine uses, when its published specification covers the point (budget k = 2, floored at the lab CMC)
      2  any other standard whose specification covers the point
      3  what a person used for exactly this point before (uncertainty_fixes: 'same as last time' / the saved rule)
      4  the nearest lab CMC line, applied at this level (EXTRAPOLATED; flagged)
      5  the nearest row of a standard's specification, applied at this level (EXTRAPOLATED; flagged)
    Never raises; [] when nothing applies."""
    out = []
    try:
        import report_review_model as M
        row = model.rows[idx]
        spec = row.spec
        info = point_info(model, idx, procedure)
        q = spec.q or {}
        unit = info.unit
        for n, key in enumerate(_candidates(model, idx)):
            try:
                ev = M.evaluate(spec, key)
            except Exception:
                continue
            if ev.budget is None or ev.reported is None or ev.reported <= 0:
                continue
            val, caution, detail = dec(ev.reported), '', 'u = published specification / coverage divisor, plus calibrator resolution / sqrt(12), RSS, k = 2; rounded up to 2 figures.'
            if info.floor is not None and val < info.floor:
                val = _ceil2(info.floor)
                caution, detail = 'Raised to the lab CMC floor (see below).', detail + ' Raised to the lab CMC line.'
            basis = f'{key} {_period(key)} spec, budget k=2'
            out.append(Suggestion(1 if key == spec.default_std else 2, val, unit, format_decimal(val, unit), basis, 'specmanager / uncertainty_budget (report_review_model.evaluate)',
                                  detail, caution, key))
        out.sort(key=lambda s: (s.rank, s.standard))
        try:
            import uncertainty_fixes as F
            proc = model.procedure or model.title
            last = F.last_fix(proc, spec.section, spec.description, row.cur.unit) or F.like_rule(proc, spec.section, row.cur.unit)
            if last:
                v, err = parse_value(last['text'], unit)
                if v is not None and not any(s.value == v for s in out):
                    out.append(Suggestion(3, v, unit, format_decimal(v, unit), f'same as last time ({last["at"]}' + (f', {last["who"]}' if last['who'] else '') + ')',
                                          'uncertainty_fixes', last.get('source', '') or ''))
        except Exception:
            pass
        import report_pdf
        sc = report_pdf.scope()
        if sc is not None and info.nominal is not None and info.kind and q.get('source') != 'none':
            near = nearest_cmc(sc, info.kind, info.nominal, info.frequency, info.standard or None)
            if near is not None and not any(s.rank in (1, 2) for s in out):
                out.append(Suggestion(4, near[0], unit, format_decimal(near[0], unit), f'nearest lab CMC line, k=2 ({near[1]})', 'uncertainty.Scope (lab CMC table)',
                                      'The scope has no line for this point; this is the closest line, applied at this level.',
                                      'Extrapolated: the point is outside the lab scope. Check it before you accept.'))
        if not any(s.rank in (1, 2) for s in out):
            ns = _nearest_spec_suggestion(spec, info, q, unit)
            if ns is not None:
                out.append(ns)
    except Exception:
        return out
    out.sort(key=lambda s: (s.rank, s.standard))
    kept = []
    for s in out:                                  # the same number from two extrapolations is one suggestion (the better-ranked basis is kept)
        if s.rank >= 4 and any(k.value == s.value for k in kept):
            continue
        kept.append(s)
    return kept


def standard_choices(model, idx) -> list:
    """Model keys of every standard the registry holds (the sheets of Standards Specs), for 'build one from another standard'; the engine's own and the calibrators first."""
    return _candidates(model, idx)


def budget_for_standard(model, idx, key, procedure=None):
    """The suggestion a CHOSEN standard gives for this point, or None when its sheet has no row that covers it.  The standard may be the source (direction 'output': the
    same call the engines make, report_review_model.evaluate) or a measuring standard (direction 'input': the standard's reading of the point, uncertainty_budget.build).
    Budget k = 2, floored at the lab CMC line when the point has one, rounded up to 2 figures."""
    import report_review_model as M
    spec = model.rows[idx].spec
    info = point_info(model, idx, procedure)
    basis, how, direction = f'{key} {_period(key)} spec, budget k=2', 'specmanager / uncertainty_budget (standard chosen by you)', 'output'
    try:
        ev = M.evaluate(spec, key)
        val = dec(ev.reported) if (ev.budget is not None and ev.reported is not None and ev.reported > 0) else None
    except Exception:
        val = None
    if val is None:
        try:
            import report_pdf
            import uncertainty_budget as ub
            q = spec.q or {}
            if info.kind and info.nominal is not None and q.get('source') != 'none' and spec.calc is None:
                b = ub.build(info.kind, info.nominal, 'ohm' if info.kind.startswith('OHM') else q.get('unit', info.unit), standard=key, frequency=info.frequency,
                             scope=report_pdf.scope(), range_value=q.get('range'), direction='input')
                if b.emu is not None and b.reported:
                    val, direction = dec(b.reported), 'input'
                    basis = f'{key} {_period(key)} spec (as measuring standard), budget k=2'
        except Exception:
            val = None
    if val is None:
        return None
    caution, detail = '', 'u = published specification / coverage divisor, plus resolution / sqrt(12), RSS, k = 2; rounded up to 2 figures.'
    if info.floor is not None and val < info.floor:
        val, caution, detail = _ceil2(info.floor), 'Raised to the lab CMC floor (see above).', detail + ' Raised to the lab CMC line.'
    return Suggestion(2, val, info.unit, format_decimal(val, info.unit), basis, how, detail, caution, key)


def _ceil2(x) -> Decimal:
    import uncertainty
    return dec(uncertainty.round_up(float(x)))


def _nearest_spec_suggestion(spec, info, q, unit, decades=1.0):
    """The nearest row of the engine's standard (or of a calibrator that sources the point) when no sheet row covers the point: its specification applied at this value
    (specmanager.Hit), as a budget k = 2.  Extrapolated: flagged."""
    try:
        import specmanager as sm
        import uncertainty_budget as ub
        kind = {'OHM2': 'OHM', 'OHM4': 'OHM'}.get(info.kind, info.kind)
        if not kind or info.nominal is None or kind in ('TEMP', 'FREQ'):
            return None
        for key in [spec.default_std] + ['5560A', '5522A', '5520A']:
            if not key:
                continue
            std = sm.standard(key)
            if std is None:
                continue
            best = None
            for r in std._eligible(kind, '', 'output'):
                if r['amp_lo'] is None:
                    continue
                lo, hi = sorted((abs(r['amp_lo']), abs(r['amp_hi']))) if r['amp_lo'] * r['amp_hi'] >= 0 else (0.0, max(abs(r['amp_lo']), abs(r['amp_hi'])))
                da = _decades_outside(info.nominal, lo, hi)
                if r['freq_lo'] is not None:
                    df = _decades_outside(info.frequency, r['freq_lo'], r['freq_hi']) if info.frequency else math.inf
                else:
                    df = 0.0
                sp = next((s for s in r['specs'] if s['period'] == std.period and not s.get('error')), None)
                if sp is None or da > decades or df > decades:
                    continue
                if best is None or da + df < best[0]:
                    best = (da + df, r, sp)
            if best is None:
                continue
            hit = sm.Hit(best[1], best[2], info.nominal)
            b = ub.Budget(info.kind, info.nominal, unit, std, info.frequency)
            div, why = std.divisor()
            b.add(f'{std.model} Calibrator', hit.limit / div, 1.0, why)
            res, _src = std.resolution(hit)
            if res:
                b.add('Resolution', res / math.sqrt(12), 1.0, '')
            val = dec(ub.ceil_sig(b.emu))
            if info.floor is not None and val < info.floor:
                val = _ceil2(info.floor)
            return Suggestion(5, val, unit, format_decimal(val, unit), f'nearest {std.model} {std.period} spec row, budget k=2', 'specmanager / uncertainty_budget',
                              'No row of the sheet covers this point; the nearest row (' + str(best[1].get('function', '')) + ') was applied at this level.',
                              'Extrapolated: no specification row covers this point. Check it before you accept.', key)
    except Exception:
        return None
    return None


# ------------------------------------------------------------------------------------------------------------------------------ validation
@dataclass
class Check:
    ok: bool = False
    value: Decimal | None = None
    display: str = ''
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    below_cmc: bool = False


def check_value(info, value, suggested=None) -> Check:
    """Sanity checks on an exact Decimal for a point: finite and positive, not absurd for the nominal, and the CMC floor (a value below the lab CMC needs a confirmation).
    Warnings never block; `below_cmc` blocks until the technician confirms."""
    c = Check(value=value)
    if value is None or value <= 0 or not value.is_finite():
        c.errors.append('The uncertainty must be greater than zero.')
        return c
    if value > MAX_VALUE or value < MIN_VALUE:
        c.errors.append('That value is not plausible; check the unit prefix.')
        return c
    u = canon_unit(info.unit)
    if u in PREFIXABLE and info.nominal not in (None, 0):
        if value > Decimal(repr(abs(float(info.nominal)))) * 1:
            c.errors.append('The uncertainty is larger than the nominal value of the point; check the unit prefix.')
    c.display = format_decimal(value, info.unit)
    if info.floor is not None and value < info.floor:
        c.below_cmc = True
        c.warnings.append(f'Below the lab CMC ({format_decimal(info.floor, info.unit)}; {info.floor_text}). An accredited value may not be smaller; confirm only if you know why.')
    try:
        tol = (Decimal(repr(float(info.high))) - Decimal(repr(float(info.low)))) / 2 if (info.low is not None and info.high is not None) else None
        if tol and canon_unit(info.tolerance_unit) == u and value > tol:
            c.warnings.append('Larger than the unit under test tolerance: the TUR is below 1:1.')
    except (InvalidOperation, ValueError, TypeError):
        pass
    if suggested:
        ratio = (value / suggested) if suggested > 0 else None
        if ratio is not None and (ratio > 100 or ratio < Decimal('0.01')):
            c.warnings.append(f'Differs from the suggested {format_decimal(suggested, info.unit)} by a factor of more than 100: check the unit prefix.')
    c.ok = not c.errors
    return c


def check_manual(info, text, default_factor=Decimal(1), suggested=None) -> Check:
    """parse_value + check_value for what the technician typed."""
    value, err = parse_value(text, info.unit, default_factor)
    if value is None:
        c = Check()
        c.errors.append(err)
        return c
    return check_value(info, value, suggested)


# ------------------------------------------------------------------------------------------------------------------------------ store
def _read_back(con, aid, expected) -> bool:
    got = con.execute(f'SELECT {", ".join(_INSERT_COLS)} FROM field_uncertainty WHERE id=?', (aid,)).fetchone()
    return got is not None and tuple(got) == tuple(expected)


def _values(info, value, display, source, reason, who, replace, scope, group_id, confirmed, asset, replaced_text, at=None):
    row = dict(procedure_id=info.procedure, point_id=info.key, section=info.section, description=info.description, nominal_text=info.nominal_text, step=info.step,
               kind=info.kind, unit=info.unit, value=plain(value), display=display, source=source, reason=str(reason).strip(), who=str(who).strip(),
               at=at or _now(), app_version=_version(), first_asset=str(asset or ''), replaces=1 if replace else 0, replaced_text=replaced_text if replace else '',
               scope=scope, group_id=group_id, below_cmc_confirmed=1 if confirmed else 0)
    return row


def _vet(info, value, source, reason, who, replace, confirm_below_cmc):
    if not info.procedure or not info.key:
        raise Refused('point', 'The point or the procedure is not identified, so the value cannot be kept.')
    msgs = check_people(reason, who, need_reason=(source == 'manual' or replace))
    if msgs:
        raise Refused('people', ' '.join(msgs))
    if not (source == 'manual' or str(source).startswith(SESSION_PREFIX)):
        raise Refused('source', 'The source must be manual or a suggestion.')
    chk = check_value(info, value)
    if not chk.ok:
        raise Refused('value', ' '.join(chk.errors))
    if info.has_computed and not replace:
        raise Refused('has_computed', 'This point already has a computed uncertainty. Choose "replace" and give a reason to put your value in its place.')
    if chk.below_cmc and not confirm_below_cmc:
        raise Refused('below_cmc', chk.warnings[0])
    if replace and len(re.sub(r'[\W_]+', '', str(reason or ''))) < MIN_REASON:
        raise Refused('people', 'Give a reason for replacing the computed value.')
    return chk


def add(info, value, *, source, reason, who, demo=False, replace=False, confirm_below_cmc=False, scope='point', group_id='', asset=None) -> int:
    """Keep one assignment.  Raises Refused (nothing kept) or StorageError.  Demo: this process's memory only, the registry is not opened.  The write is made once, read
    back and compared; it is never retried."""
    return add_many([(info, value, source)], reason=reason, who=who, demo=demo, replace=replace, confirm_below_cmc=confirm_below_cmc, scope=scope, group_id=group_id,
                    asset=asset)[0]


def add_many(items, *, reason, who, demo=False, replace=False, confirm_below_cmc=False, scope='kind', group_id='', asset=None) -> list:
    """Keep several assignments together (all or none).  items = [(PointInfo, Decimal value, source)].  Same rules as add()."""
    if not items:
        return []
    group_id = group_id or (_now().replace(':', '').replace('-', '') + f'-{len(items)}' if len(items) > 1 else '')
    rows = []
    for info, value, source in items:
        _vet(info, value, source, reason, who, replace, confirm_below_cmc)
        rows.append(_values(info, value, format_decimal(value, info.unit), source, reason, who, replace, scope if len(items) > 1 else 'point', group_id,
                            confirm_below_cmc and bool(info.floor is not None and value < info.floor), asset if asset is not None else info.asset,
                            info.computed_text))
    if demo:
        ids = []
        for r in rows:
            r = dict(r, id=(max([x['id'] for x in _SESSION] or [0]) + 1), first_run=None, active=1, withdrawn_at='', withdrawn_by='', withdrawn_reason='')
            _SESSION.append(r)
            ids.append(r['id'])
        return ids
    ids = []
    try:
        with _db() as con:
            for r in rows:
                expected = tuple(r[c] for c in _INSERT_COLS)
                cur = con.execute(f'INSERT INTO field_uncertainty({", ".join(_INSERT_COLS)}) VALUES ({", ".join("?" * len(_INSERT_COLS))})', expected)
                aid = cur.lastrowid
                if not _read_back(con, aid, expected):
                    raise StorageError('The registry did not keep the assignment exactly as written; nothing was saved.')
                ids.append(aid)
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f'The assignment could not be saved ({type(e).__name__}); nothing was saved.') from e
    return ids


def withdraw(aid, who, reason, demo=False) -> bool:
    """Take an assignment out of use (the record stays, marked withdrawn).  Needs a name and a reason.  True when it was active."""
    msgs = check_people(reason, who)
    if msgs:
        raise Refused('people', ' '.join(msgs))
    if demo:
        for r in _SESSION:
            if r['id'] == aid and r['active']:
                r.update(active=0, withdrawn_at=_now(), withdrawn_by=str(who).strip(), withdrawn_reason=str(reason).strip())
                return True
        return False
    try:
        with _db() as con:
            cur = con.execute('UPDATE field_uncertainty SET active=0, withdrawn_at=?, withdrawn_by=?, withdrawn_reason=? WHERE id=? AND active=1',
                              (_now(), str(who).strip(), str(reason).strip(), aid))
            return cur.rowcount > 0
    except sqlite3.Error as e:
        raise StorageError(f'Could not withdraw the assignment ({type(e).__name__}).') from e


def mark_used(ids, asset, run_id) -> int:
    """Set the asset and the run an assignment was FIRST printed on (only while still empty).  Never raises."""
    n = 0
    try:
        with _db() as con:
            for aid in ids:
                cur = con.execute("UPDATE field_uncertainty SET first_asset=CASE WHEN first_asset='' THEN ? ELSE first_asset END, "
                                  "first_run=CASE WHEN first_run IS NULL THEN ? ELSE first_run END WHERE id=?", (str(asset or ''), run_id, aid))
                n += cur.rowcount
    except Exception:
        return n
    return n


# ------------------------------------------------------------------------------------------------------------------------------ 'all points of this kind'
def kind_group(model, idx, method, value=None, suggestion=None) -> dict:
    """The OTHER points an assignment may safely be spread over, as the panel offers it.  Only points that print NO uncertainty (never a computed one, never a point that already
    has an assignment or a typed value), in this procedure, of the same kind and unit.
      method 'suggested'  each point gets ITS OWN value from the same standard and basis as `suggestion`; a point that basis cannot describe is left alone (counted in 'skipped').
      method 'manual'     the typed `value` is spread only over points with the SAME conditions (kind, unit, nominal, frequency and range): one number is not the uncertainty
                          of a different level.  Points of the same kind under other conditions are counted in 'skipped' and left alone.
    Returns {'items': [(PointInfo, Decimal, source)], 'skipped': n}.  The first point itself is not in it."""
    import report_review_model as M
    out = {'items': [], 'skipped': 0}
    me = model.rows[idx]
    mq = me.spec.q or {}
    seen = {point_id(me.spec.section, me.spec.description, me.spec.nominal_text)}
    for j in sorted(getattr(model, 'field_missing', {}) or {}):
        r = model.rows[j]
        if j == idx or r.assigned is not None or r.typed is not None:
            continue
        key = point_id(r.spec.section, r.spec.description, r.spec.nominal_text)
        if key in seen:                       # printed identically to a point already covered: one stored value serves both lines
            continue
        seen.add(key)
        q = r.spec.q or {}
        if q.get('kind') != mq.get('kind') or _unit_of(r.spec) != _unit_of(me.spec):
            continue
        info = point_info(model, j)
        if method == 'manual':
            if value is None or any(q.get(k) != mq.get(k) for k in ('nominal', 'frequency', 'range')):
                out['skipped'] += 1
                continue
            out['items'].append((info, value, 'manual'))
        else:
            if suggestion is None or not suggestion.standard:
                out['skipped'] += 1
                continue
            try:
                ev = M.evaluate(r.spec, suggestion.standard)
            except Exception:
                ev = None
            if ev is None or ev.budget is None or ev.reported is None or ev.reported <= 0:
                out['skipped'] += 1
                continue
            v = dec(ev.reported)
            if info.floor is not None and v < info.floor:
                v = _ceil2(info.floor)
            out['items'].append((info, v, suggestion.source))
    return out


# ------------------------------------------------------------------------------------------------------------------------------ the report layer
def _split_unit(uom):
    """(factor Decimal, base unit) of a report UOM cell ('mV' -> 1e-3, 'V'; 'kOhm' -> 1e3, 'ohm'; '%' -> 1, '%'), or None."""
    t = str(uom or '').strip().replace('µ', 'u').replace('μ', 'u').replace('Ω', 'ohm')
    for base in ('V', 'A', 'ohm', 'Hz', 'F', 's'):
        for pre, mult in PREFIXES.items():
            if t.startswith(pre) and t[len(pre):].lower() in _NAMES[base]:
                return mult, base
    if t.lower() in _TEMP_NAMES:
        return Decimal(1), 'degC'
    return (Decimal(1), t) if t else None


def _num(text):
    try:
        v = Decimal(str(text).replace(',', '').strip())
        return v if v.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def row_tur(row, value, unit):
    """TUR text for an assigned row from the limits the report row itself prints (Tolerance -/+ and UOM), or ''.  The tolerance must be in the unit of the assigned
    value (a % or dB tolerance is never divided by an uncertainty in volts)."""
    try:
        import tartur
        lo, hi = _num(row.get('Tolerance -')), _num(row.get('Tolerance +'))
        su = _split_unit(row.get('UOM'))
        if lo is None or hi is None or su is None or canon_unit(su[1]) != canon_unit(unit) or hi <= lo or value <= 0:
            return ''
        tol = (hi - lo) / 2 * su[0]
        return tartur.format_ratio(float(tol / value))
    except Exception:
        return ''


def marked(display, n) -> str:
    return f'{display} ({MARK}, note {n})'


def apply_to_rows(rows, details, header=None, demo=False, reprint=False):
    """The override layer.  Returns (rows, details, notes).

    * details already carries 'field_assignments' (a report written with them, now being printed again): they are authoritative, the rows already carry the marks,
      and nothing is looked up.
    * reprint without them: nothing is applied, ever (an old report must not pick up an assignment made after it was issued).
    * otherwise the assignments stored for this procedure are applied to rows whose Uncertainty cell is empty (or, for an explicit 'replace', any), the TUR cell is filled
      where the report has the column, and details gets 'field_assignments' (notes).
    With nothing to apply the SAME rows and details objects come back untouched.  Never raises."""
    try:
        if isinstance(details, dict) and 'field_assignments' in details:
            return rows, details, list(details['field_assignments'] or [])
        if reprint:
            return rows, details, []
        proc = report_procedure_id(details)
        stored = lookup_all(proc, demo) if proc else {}
        if not stored:
            return rows, details, []
        out, notes, used = [], [], {}
        for r in rows:
            a = stored.get(point_id(r.get('Section'), r.get('Description'), r.get('Nominal')))
            cell = str(r.get('Uncertainty') or '').strip()
            if a is None or (cell not in ('', 'N/A') and not a['replaces']):
                out.append(r)
                continue
            if a['id'] not in used:
                used[a['id']] = len(used) + 1
                notes.append(dict(note=used[a['id']], id=a['id'], section=a['section'], description=a['description'], nominal=a['nominal_text'], value=a['display'],
                                  source=a['source'], reason=a['reason'], who=a['who'], at=a['at'], replaces=bool(a['replaces']),
                                  replaced=(cell if a['replaces'] else ''), version=a['app_version']))
            new = dict(r)
            new['Uncertainty'] = marked(a['display'], used[a['id']])
            if 'TUR' in new and not str(new.get('TUR') or '').strip():
                v = _num(a['value'])
                new['TUR'] = row_tur(r, v, a['unit']) if v else ''
            out.append(new)
        if not notes:
            return rows, details, []
        d = dict(details or {})
        d['field_assignments'] = notes
        return out, d, notes
    except Exception:
        return rows, details, []


def footnote_lines(notes) -> list:
    """The footnote text for a report: [(kind, text)], kind 'head' | 'intro' | 'note'.  Empty for no notes."""
    if not notes:
        return []
    out = [('head', 'Uncertainties assigned in the field'),
           ('intro', 'The uncertainty of each point below was assigned by the technician at the point of use. It is NOT the result of the laboratory uncertainty budget or '
                     'the A2LA scope of accreditation, and it is not covered by them. Who assigned it, why and from what basis is recorded here and in the laboratory records.')]
    for n in notes:
        basis = 'entered by hand' if n.get('source') == 'manual' else str(n.get('source', '')).replace(SESSION_PREFIX, 'suggestion: ', 1)
        what = f'{n.get("description", "")}, {n.get("nominal", "")}'.strip(', ')
        text = (f'Note {n["note"]}. {what}: {n["value"]} ({basis}). Assigned by {n.get("who", "")} on {str(n.get("at", ""))[:16].replace("T", " ")}. Reason: {n.get("reason", "")}')
        if n.get('replaces'):
            text += f' This replaces the computed value {n.get("replaced") or "(none)"}.'
        out.append(('note', text))
    return out


# ------------------------------------------------------------------------------------------------------------------------------ the owner's list
CSV_COLUMNS = ('id', 'status', 'procedure', 'section', 'point', 'nominal', 'kind', 'value_SI', 'unit', 'printed', 'source', 'reason', 'assigned_by', 'assigned_at',
               'app_version', 'first_asset', 'first_run', 'replaces_computed', 'replaced_text', 'scope', 'group', 'below_cmc_confirmed', 'withdrawn_at', 'withdrawn_by',
               'withdrawn_reason')


def _csv_safe(x) -> str:
    s = '' if x is None else str(x)
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


def csv_rows(rows) -> list:
    out = []
    for r in rows:
        out.append([r['id'], status_of(r), r['procedure_id'], r['section'], r['description'], r['nominal_text'], r['kind'], r['value'], r['unit'], r['display'], r['source'],
                    r['reason'], r['who'], r['at'], r['app_version'], r['first_asset'], '' if r['first_run'] is None else r['first_run'], 'yes' if r['replaces'] else '',
                    r['replaced_text'], r['scope'], r['group_id'], 'yes' if r['below_cmc_confirmed'] else '', r['withdrawn_at'], r['withdrawn_by'], r['withdrawn_reason']])
    return [[_csv_safe(c) for c in line] for line in out]


def export_csv(path, rows=None, demo=False) -> int:
    """Write the review list as CSV (UTF-8 with BOM, so a spreadsheet shows the micro sign).  Returns the number of rows.  Nothing secret is in the table, so nothing is
    left out; text cells that start with = + - @ are prefixed with an apostrophe so a spreadsheet never runs them as a formula."""
    rows = all_assignments(True, demo) if rows is None else rows
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(CSV_COLUMNS)
    w.writerows(csv_rows(rows))
    Path(path).write_text(buf.getvalue(), encoding='utf-8-sig', newline='')
    return len(rows)
