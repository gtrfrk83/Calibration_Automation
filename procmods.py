"""Procedure modifications: the override store, resolver and view-model (Tk-free).  Shipped specs and driver defaults are never edited.

Override kinds
    command  a driver command template (validated by cmdreg; target 'DriverClass:key')
    param    a tunable (settle, delay, NPLC ...); name, or 'name@<pointkey>' for one point.  NPLC/filter/settle-type tunables carry
             affects_conditions (the report says the test conditions differ from the manufacturer's)
    point    skip a test point (target = point key)
    text     setup / note / prompt text ('setup:<pointkey>', 'note:<pointkey>', 'prompt:<name>', 'hookup:<name>'); safety text is locked
    limit    the numeric tolerance of a point (target = point key).  DEVELOPER MODE ONLY: creating, editing, enabling and importing a
             limit override needs an unlocked devmode.DevSession; applying a saved one does not.  Every limit row carries an HMAC
             (device key in devmode.json) checked at apply time; a failing row is TAMPERED and not applied.  Pass/fail logic is untouched.
Scopes: 'run' (memory / checkpoint snapshot only, never written to the override table), 'asset', 'model'.  Precedence run > asset > model > factory.
Every override has a non-empty reason.  Rows are append-only: an edit appends a new version (supersedes = previous uid); only
`enabled` toggles (SQLite triggers enforce this).  Storage: lab_registry.sqlite3 (labregistry.DB by default, injectable); the
Manager's calibration_procedures.sqlite3 is never opened here.

ALL mutations need developer mode: every create / edit / enable / disable / reset / run-scope entry / import apply / export takes an
unlocked devmode.DevSession and is refused (OverrideError) without one - enforced here, not only in the UI.  Reading, resolve(),
apply_points(), snapshots, summaries, the view-model and 'run factory' (resolve(factory_only=True)) never need it.

Public API (stable)
    Store(path=None, devmode=None, now=None)
        .add(kind, target, value, scope, reason, *, model='', asset_id='', author=None, cmd=None, driver_name=None, point=None,
             factory=None, factory_hash='', label='', fw_match=None, expires_at=None, tested=None, session=<DevSession, required>) -> entry dict
        .edit(uid, *, value, reason, <same options>) -> new entry   .set_enabled(uid, enabled, who=None, session=...) .reset(uid, who, session)
        .get(uid) .history(uid) .entries(model=None, asset_id=None, kind=None, heads_only=True) .log(uid=None)
        OverrideError(.problems) is raised for anything refused.
    make_run_entry(kind, target, value, reason, *, author=None, cmd=None, point=None, session=None, ...) -> entry (scope 'run', in memory)
    resolve(model, asset, run_overrides=None, idn=None, *, store=None, now=None, factory_only=False) -> OverrideSet (immutable)
    OverrideSet: .hash .active() .entries() .commands_for(driver) .param(name, default, point_key=None) .point_override(key)
                 .limit_override(key) .text(key, default='') .with_idn(idn) .tampered() .has_limits .bool(oset)
    point_keys(points) / point_key(p) / point_hash(p);  apply_points(points, oset) -> patched COPIES;  check_points(points, oset)
    assert_limits_unchanged(orig, patched, limit_ok=())  (raises LimitsChangedError)
    build_snapshot(oset, prior=None) / restore_snapshot(snap, ...) / verify_snapshot(snap) / compare_with_current(snap, oset)
    record_run_snapshot(run_id, snapshot_or_oset, demo=False, store=None) / get_run_snapshot(run_id, store=None)
    export_entries(store, path=None, *, model, asset_id, session) / import_preview(store, data, ...) / apply_import(store, preview, ...)
    rows(driver_registries, oset, filter='all', search='') / setting_rows / point_rows / changes(oset)
    modifications_summary(oset) -> [] when unmodified, else dicts (text, reason, author, date, unverified, affects_conditions,
                 applies_to, kind, limit, manufacturer_tolerance, tolerance_used, tolerances_modified); tolerances_modified(oset)
    register_param(name, ...) to let an engine declare its own tunables.
"""
from __future__ import annotations

import copy
import getpass
import hashlib
import json
import math
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import cmdreg
import devmode as _devmode

KINDS = ('command', 'param', 'point', 'text', 'limit')
SCOPES = ('run', 'asset', 'model')
STORED_SCOPES = ('asset', 'model')
RANK = {'run': 3, 'asset': 2, 'model': 1}
FORMAT = 'calov'
SCHEMA_VERSION = 1

SCHEMA = '''
CREATE TABLE IF NOT EXISTS override (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('command','param','point','text','limit')),
    target TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('model','asset')),
    model TEXT NOT NULL DEFAULT '',
    asset_id TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
    value_json TEXT NOT NULL,
    factory_hash TEXT NOT NULL DEFAULT '',
    fw_match TEXT,
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    supersedes TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    tested_json TEXT,
    mac TEXT
);
CREATE INDEX IF NOT EXISTS override_lookup ON override(model, asset_id, kind, target);
CREATE TABLE IF NOT EXISTS override_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    action TEXT NOT NULL,
    at TEXT NOT NULL,
    who TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS run_overrides (
    run_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS override_append_only BEFORE UPDATE ON override
WHEN NEW.id IS NOT OLD.id OR NEW.uid IS NOT OLD.uid OR NEW.kind IS NOT OLD.kind OR NEW.target IS NOT OLD.target
  OR NEW.scope IS NOT OLD.scope OR NEW.model IS NOT OLD.model OR NEW.asset_id IS NOT OLD.asset_id
  OR NEW.value_json IS NOT OLD.value_json OR NEW.factory_hash IS NOT OLD.factory_hash OR NEW.fw_match IS NOT OLD.fw_match
  OR NEW.reason IS NOT OLD.reason OR NEW.author IS NOT OLD.author OR NEW.created_at IS NOT OLD.created_at
  OR NEW.version IS NOT OLD.version OR NEW.supersedes IS NOT OLD.supersedes OR NEW.expires_at IS NOT OLD.expires_at
  OR NEW.tested_json IS NOT OLD.tested_json OR NEW.mac IS NOT OLD.mac
BEGIN SELECT RAISE(ABORT, 'override rows are append-only (only enabled may change)'); END;
CREATE TRIGGER IF NOT EXISTS override_no_delete BEFORE DELETE ON override
BEGIN SELECT RAISE(ABORT, 'override rows are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS override_log_no_update BEFORE UPDATE ON override_log
BEGIN SELECT RAISE(ABORT, 'override_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS override_log_no_delete BEFORE DELETE ON override_log
BEGIN SELECT RAISE(ABORT, 'override_log is append-only'); END;
'''


class OverrideError(ValueError):
    def __init__(self, problems):
        self.problems = [str(p) for p in ([problems] if isinstance(problems, str) else problems)]
        super().__init__('; '.join(self.problems))


class LimitsChangedError(AssertionError):
    """A point's limit fields differ from the factory ones without a valid limit override."""


# ------------------------------------------------------------------------------------------------------------ helpers
def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, default=repr)


def sha(obj) -> str:
    return hashlib.sha256((obj if isinstance(obj, str) else canon(obj)).encode('utf-8')).hexdigest()


def fh(value) -> str:
    """Short hash of a factory value (template, default, text) for stale detection.  Numbers compare by value."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return sha(value)[:16]
    if isinstance(value, (int, float)):
        return sha(format(float(value), '.12g'))[:16]
    return sha(value)[:16]


def default_author() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return 'unknown'


def _iso(dt) -> str:
    return dt.isoformat(timespec='seconds')


def _parse_dt(text):
    """ISO date or date-time -> (datetime, date_only) or (None, False)."""
    try:
        t = str(text).strip()
        return datetime.fromisoformat(t), len(t) <= 10
    except (ValueError, TypeError):
        return None, False


def _expired(entry, now) -> bool:
    exp = entry.get('expires_at')
    if not exp or now is None:
        return False
    dt, date_only = _parse_dt(exp)
    if dt is None:
        return False
    if date_only:
        dt += timedelta(days=1)
    return now >= dt


def _num(x):
    try:
        v = float(str(x).replace(',', '')) if isinstance(x, str) else float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------------ params
PARAMS: dict = {}


def register_param(name, ptype='float', lo=None, hi=None, choices=None, affects_conditions=False, per_point=False,
                   point_field=None, label='', unit=''):
    """Declare a tunable.  per_point tunables may be overridden for one point and are written to p[point_field or name]."""
    field = point_field or name
    if per_point and field in LIMIT_FIELDS:
        raise ValueError(f'{field} is a limit field and cannot be a per-point tunable')
    PARAMS[name] = dict(type=ptype, lo=lo, hi=hi, choices=tuple(choices) if choices else None,
                        affects_conditions=bool(affects_conditions), per_point=bool(per_point), field=field, label=label or name, unit=unit)


def _check_param_value(name, value):
    spec = PARAMS.get(name)
    if spec is None:
        return [f'unknown setting {name!r}']
    if spec['type'] == 'enum':
        return [] if value in (spec['choices'] or ()) else [f'{name}: must be one of {list(spec["choices"] or ())}']
    v = _num(value) if not isinstance(value, bool) else None
    if v is None:
        return [f'{name}: expected a number']
    if spec['type'] == 'int' and v != int(v):
        return [f'{name}: expected a whole number']
    if spec['lo'] is not None and v < spec['lo'] or spec['hi'] is not None and v > spec['hi']:
        return [f'{name}: must be between {spec["lo"]} and {spec["hi"]}']
    return []


# ------------------------------------------------------------------------------------------------------------ point keys
LIMIT_FIELDS = ('limits', 'error', 'low', 'high', 'tol_text', 'tolerance', 'tol', 'limit', 'lo', 'hi', 'min', 'max', 'nominal', 'unit',
                'kind', 'range', 'amplitude', 'frequency', 'filter_hz', 'applied', 'period', 'passfail', 'test', 'factor', 'base_unit',
                'display_unit', 'source', 'terminal', 'input', 'section', 'id', 'stim', 'ch', 'accuracy', 'switch', 'table', 'step',
                'desc', 'description')
LIMIT_PATCH_FIELDS = ('error', 'low', 'high')                      # the only limit fields a valid limit override may change
LIMIT_MARKERS = ('limit_modified', 'limit_factory')
_KEY_FIELDS = ('section', 'kind', 'nominal', 'range', 'frequency', 'filter_hz', 'terminal', 'input', 'amplitude', 'switch', 'ch', 'stim',
               'table', 'step', 'desc')
_HASH_FIELDS = _KEY_FIELDS + ('limits', 'low', 'high', 'tol_text', 'unit', 'setup', 'applied', 'terminal', 'source', 'amplitude')
_MUTABLE_BASE = {'skip', 'setup', 'tech_note', 'ov'} | set(LIMIT_MARKERS)


def _kv(v):
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, (int, float)):
        return format(float(v), '.9g')
    if isinstance(v, dict):
        return ','.join(f'{k}={_kv(x)}' for k, x in sorted(v.items()))
    return str(v)


def point_key(p: dict) -> str:
    """Stable key from spec content (section id, kind, nominal, range, frequency, filter_hz ...), never the list position."""
    parts = []
    for f in _KEY_FIELDS:
        if f in p and p[f] is not None:
            parts.append(f'{f[0:4]}={_kv(p[f])}')
    if isinstance(p.get('applied'), dict):
        parts.append('app=' + _kv(p['applied']))
    return '|'.join(parts) or 'point'


def point_keys(points) -> list:
    seen, out = {}, []
    for p in points:
        k = point_key(p)
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f'{k}#{seen[k]}')
    return out


def point_hash(p: dict) -> str:
    return sha({f: p[f] for f in _HASH_FIELDS if f in p})[:16]


def limit_factory(p: dict) -> dict:
    """The limit values of a point as they are before any override ({'error':..} or {'low':..,'high':..})."""
    if 'error' in p and p.get('error') is not None:
        return {'mode': 'error', 'error': p['error']}
    return {'mode': 'band', 'low': p.get('low'), 'high': p.get('high')}


def _same_num(a, b):
    if a is None or b is None:
        return a is b
    x, y = _num(a), _num(b)
    return a == b if x is None or y is None else x == y


def _factory_matches(p, fac):
    if not isinstance(fac, dict):
        return False
    if fac.get('mode') == 'error':
        return 'error' in p and _same_num(p['error'], fac.get('error'))
    return all(_same_num(p.get(k), fac.get(k)) for k in ('low', 'high'))


def check_limit_value(p, value) -> list:
    """Problems with a proposed limit value for point p (mode matches the point, finite, low < high, nominal inside)."""
    probs = []
    fac = limit_factory(p)
    mode = value.get('mode')
    if mode != fac['mode']:
        return [f'this point has {"a +/- error" if fac["mode"] == "error" else "low/high limits"}; use mode {fac["mode"]!r}']
    if mode == 'error':
        e = _num(value.get('error'))
        if e is None or e <= 0:
            probs.append('the +/- error must be a positive number')
        return probs
    lo, hi = value.get('low'), value.get('high')
    for name, new in (('low', lo), ('high', hi)):
        if fac[name] is None:
            if new is not None:
                probs.append(f'this point has no {name} limit; one cannot be added')
        elif _num(new) is None:
            probs.append(f'{name} must be a finite number')
    if not probs and fac['low'] is not None and fac['high'] is not None:
        if not _num(lo) < _num(hi):
            probs.append('low must be below high')
        nom = _num(p.get('nominal'))
        fac_ = _num(p.get('factor'))
        if nom is not None and fac_:
            nom = nom / fac_                                     # handheld steps: nominal in base units, limits in display units
        if nom is not None and not _num(lo) <= nom <= _num(hi):
            probs.append('the nominal value must lie between low and high')
    return probs


def _apply_limit(p, value):
    fac = limit_factory(p)
    p['limit_factory'] = copy.deepcopy(fac)
    p['limit_modified'] = True
    if value['mode'] == 'error':
        p['error'] = float(_num(value['error']))
        return
    for k in ('low', 'high'):
        new = value.get(k)
        if new is None or p.get(k) is None:
            continue
        p[k] = str(new) if isinstance(p[k], str) else float(_num(new))


def _tolerance_text(fac, value, unit=''):
    u = f' {unit}'.rstrip() if unit else ''
    if (fac or {}).get('mode') == 'error':
        return f'+/-{fac.get("error"):g}{u}', f'+/-{_num(value.get("error")):g}{u}'
    f = lambda d: f'{d.get("low")} to {d.get("high")}{u}'
    return f(fac or {}), f(value or {})


# ------------------------------------------------------------------------------------------------------------ entries
TEXT_KINDS = ('setup', 'note', 'prompt', 'hookup')
LOCKED_TEXT = re.compile(r'^(safety|hv|warn|confirm)', re.I)
MAX_TEXT = 2000


def command_target(driver_name, key):
    return f'{driver_name}:{key}'


def _check_text(key, text):
    probs = []
    kind, _, name = str(key).partition(':')
    if kind not in TEXT_KINDS or not name:
        probs.append(f'text key must look like setup:<point>, note:<point>, prompt:<name> or hookup:<name> (got {key!r})')
    elif kind in ('prompt', 'hookup') and LOCKED_TEXT.match(name):
        probs.append('safety and high-voltage prompts are locked')
    if not isinstance(text, str) or not text.strip():
        probs.append('the text is empty')
    else:
        if len(text) > MAX_TEXT:
            probs.append(f'longer than {MAX_TEXT} characters')
        if any(ord(c) < 32 and c not in '\n' for c in text):
            probs.append('control characters are not allowed')
    return probs


def _mac_payload(e) -> bytes:
    keys = ('uid', 'kind', 'target', 'scope', 'model', 'asset_id', 'value', 'factory_hash', 'fw_match', 'reason', 'author',
            'created_at', 'version', 'supersedes', 'expires_at')
    return canon({k: e.get(k) for k in keys}).encode('utf-8')


def _need_dev(session, dm):
    if not isinstance(session, _devmode.DevSession) or not session.touch():
        raise OverrideError('developer mode must be unlocked to change, import or export procedure modifications')
    if dm is not None and Path(session.devmode.path) != Path(dm.path):
        raise OverrideError('this developer-mode session belongs to a different settings file')


def build_entry(kind, target, value, scope, reason, *, model='', asset_id='', author=None, cmd=None, driver_name=None, point=None,
                factory=None, factory_hash='', label='', fw_match=None, expires_at=None, tested=None, session=None, devmode=None,
                now=None, uid=None, version=1, supersedes=None, enabled=1, allow_run=False):
    """Validate and normalise a new override.  Returns the entry dict; raises OverrideError listing every problem."""
    probs = []
    _need_dev(session, devmode)                          # every mutation needs an unlocked developer-mode session
    if kind not in KINDS:
        raise OverrideError(f'unknown kind {kind!r}')
    if scope not in SCOPES or (scope == 'run' and not allow_run):
        raise OverrideError("scope must be 'asset' or 'model' ('run' entries are made with make_run_entry and never stored)")
    if not isinstance(reason, str) or not reason.strip():
        probs.append('a reason is required')
    if scope == 'model' and not model:
        probs.append('model scope needs a model')
    if scope == 'asset' and not asset_id:
        probs.append('asset scope needs an asset id')
    if fw_match:
        try:
            re.compile(fw_match)
        except re.error:
            probs.append('firmware condition is not a valid pattern')
    if expires_at and _parse_dt(expires_at)[0] is None:
        probs.append('expires_at must be an ISO date')
    value = dict(value or {})
    v = {}
    if kind == 'command':
        tpl = value.get('template')
        if cmd is None:
            probs.append('the factory command is needed to check an edited command')
        else:
            probs += [str(p) for p in cmdreg.validate(tpl, cmd, driver_name)]
            if tpl == cmd.template:
                probs.append('identical to the factory command; nothing to override')
            if cmd.secret:
                probs.append('commands with secret values are not editable')
            factory = cmd.template
            label = label or cmd.name
        v = {'template': tpl}
    elif kind == 'param':
        name = str(target).partition('@')[0]
        v = {'value': value.get('value')}
        probs += _check_param_value(name, v['value'])
        spec = PARAMS.get(name)
        if spec:
            if '@' in str(target) and not spec['per_point']:
                probs.append(f'{name} cannot be set for a single point')
            v['affects_conditions'] = bool(spec['affects_conditions'] or value.get('affects_conditions'))
            label = label or spec['label']
    elif kind == 'point':
        v = {'skip': True}
        if point is not None:
            factory_hash = point_hash(point)
    elif kind == 'text':
        v = {'text': value.get('text')}
        probs += _check_text(target, v['text'])
    elif kind == 'limit':
        if point is None:
            probs.append('the point is needed to check a tolerance change')
        else:
            v = {k: value.get(k) for k in ('mode', 'error', 'low', 'high') if k in value}
            probs += check_limit_value(point, v)
            factory_hash = point_hash(point)
            v['factory'] = limit_factory(point)
            v['unit'] = point.get('unit', '')
            if not probs and canon({k: v.get(k) for k in ('error', 'low', 'high')}) == canon(
                    {k: v['factory'].get(k) for k in ('error', 'low', 'high')}) and all(
                    _same_num(v.get(k), v['factory'].get(k)) for k in ('error', 'low', 'high')):
                probs.append('identical to the manufacturer tolerance; nothing to override')
    if probs:
        raise OverrideError(probs)
    if factory is not None and kind in ('command', 'param', 'text') and not factory_hash:
        factory_hash = fh(factory)
    if kind in ('command', 'param', 'text') and factory is not None:
        v['factory'] = factory
    if label:
        v['label'] = label
    if kind == 'point' and label:
        v['label'] = label
    if value.get('_import'):
        v['_import'] = value['_import']
    now = now or datetime.now()
    entry = {
        'uid': uid or secrets.token_hex(4), 'kind': kind, 'target': str(target), 'scope': scope,
        'model': model or '', 'asset_id': asset_id or '', 'value': v, 'factory_hash': factory_hash or '',
        'fw_match': fw_match or None, 'reason': reason.strip(), 'author': author or default_author(),
        'created_at': _iso(now), 'version': version, 'supersedes': supersedes, 'enabled': int(enabled),
        'expires_at': expires_at or None, 'tested': tested, 'mac': None,
    }
    if kind == 'limit':
        dm = devmode or session.devmode
        entry['mac'] = dm.mac(_mac_payload(entry))
    return entry


def make_run_entry(kind, target, value, reason, *, author=None, cmd=None, driver_name=None, point=None, factory=None, label='',
                   fw_match=None, tested=None, session=None, devmode=None, now=None):
    """An override for this run only: validated like a stored one, held in memory / the checkpoint snapshot, never written to the DB.
    Pass the result in resolve(..., run_overrides=[...])."""
    return build_entry(kind, target, value, 'run', reason, author=author, cmd=cmd, driver_name=driver_name, point=point, factory=factory,
                       label=label, fw_match=fw_match, tested=tested, session=session, devmode=devmode, now=now, allow_run=True)


# ------------------------------------------------------------------------------------------------------------ store
_COLS = ('id', 'uid', 'kind', 'target', 'scope', 'model', 'asset_id', 'value_json', 'factory_hash', 'fw_match', 'reason', 'author',
         'created_at', 'version', 'supersedes', 'enabled', 'expires_at', 'tested_json', 'mac')


def _row_entry(row):
    d = dict(zip(_COLS, row))
    d['value'] = json.loads(d.pop('value_json'))
    t = d.pop('tested_json')
    d['tested'] = json.loads(t) if t else None
    return d


class Store:
    """The override tables in lab_registry.sqlite3 (path injectable).  Reads degrade to empty on a damaged file; writes raise OverrideError."""

    def __init__(self, path=None, devmode=None, now=None):
        self._path = Path(path) if path else None
        self._devmode = devmode
        self._now = now or datetime.now

    @property
    def path(self) -> Path:
        if self._path:
            return self._path
        import labregistry
        return Path(labregistry.DB)

    @property
    def devmode(self):
        if self._devmode is None:
            self._devmode = _devmode.DevMode()
        return self._devmode

    def now(self):
        return self._now()

    def lock_reason(self, model='', proc_key='') -> str:
        """'' when saved procedure changes for this model may be written, else the sentence saying the procedure is verified on hardware and
        locked (verified.py).  The registry is this store's own file; the seeded list only applies to the real registry (no explicit path)."""
        try:
            import verified
        except ImportError:
            return ''
        return verified.Registry(self._path, seed=self._path is None).lock_reason(proc_key=proc_key, model=model)

    def _refuse_if_locked(self, model, proc_key=''):
        why = self.lock_reason(model, proc_key)
        if why:
            raise OverrideError(why)

    @contextmanager
    def _db(self):
        con = sqlite3.connect(str(self.path), timeout=5)
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    # -------------------------------------------------------------------------------------------- reads
    def get(self, uid):
        try:
            with self._db() as con:
                row = con.execute(f'SELECT {",".join(_COLS)} FROM override WHERE uid=?', (uid,)).fetchone()
            return _row_entry(row) if row else None
        except sqlite3.Error:
            return None

    def entries(self, model=None, asset_id=None, kind=None, heads_only=True, enabled=None):
        sql, args = f'SELECT {",".join(_COLS)} FROM override WHERE 1=1', []
        if model is not None:
            sql += ' AND model=? COLLATE NOCASE'
            args.append(model)
        if asset_id is not None:
            sql += ' AND asset_id=?'
            args.append(asset_id)
        if kind:
            sql += ' AND kind=?'
            args.append(kind)
        if enabled is not None:
            sql += ' AND enabled=?'
            args.append(int(enabled))
        if heads_only:
            sql += ' AND uid NOT IN (SELECT supersedes FROM override WHERE supersedes IS NOT NULL)'
        try:
            with self._db() as con:
                return [_row_entry(r) for r in con.execute(sql + ' ORDER BY id', args).fetchall()]
        except sqlite3.Error:
            return []

    def candidates(self, model, asset):
        """Enabled head rows that apply to this model / asset (scope filtering only)."""
        out = []
        for e in self.entries(heads_only=True, enabled=True):
            if e['scope'] == 'model' and (e['model'] or '').casefold() == (model or '').casefold() and model:
                out.append(e)
            elif e['scope'] == 'asset' and asset and e['asset_id'].casefold() == str(asset).casefold():
                out.append(e)
        return out

    def history(self, uid):
        """All versions of the chain containing uid, oldest first."""
        allrows = {e['uid']: e for e in self.entries(heads_only=False)}
        if uid not in allrows:
            return []
        cur = allrows[uid]
        while cur.get('supersedes') in allrows:
            cur = allrows[cur['supersedes']]
        chain = [cur]
        nxt = {e['supersedes']: e for e in allrows.values() if e['supersedes']}
        while chain[-1]['uid'] in nxt:
            chain.append(nxt[chain[-1]['uid']])
        return chain

    def log(self, uid=None):
        try:
            with self._db() as con:
                q, a = 'SELECT uid,action,at,who,detail FROM override_log', ()
                if uid:
                    q, a = q + ' WHERE uid=?', (uid,)
                return [dict(zip(('uid', 'action', 'at', 'who', 'detail'), r)) for r in con.execute(q + ' ORDER BY id', a)]
        except sqlite3.Error:
            return []

    # -------------------------------------------------------------------------------------------- writes
    def _insert(self, e, action, who):
        self._refuse_if_locked(e.get('model') or '')       # the one place every create / edit / import is written: verified procedures are locked
        try:
            with self._db() as con:
                con.execute(
                    f'INSERT INTO override({",".join(c for c in _COLS if c not in ("id",) and c not in ("value_json", "tested_json"))},'
                    f'value_json,tested_json) VALUES({",".join("?" * (len(_COLS) - 1))})',
                    [e[c] for c in _COLS if c not in ('id', 'value_json', 'tested_json')] + [canon(e['value']),
                                                                                              canon(e['tested']) if e['tested'] else None])
                con.execute('INSERT INTO override_log(uid,action,at,who,detail) VALUES(?,?,?,?,?)',
                            (e['uid'], action, _iso(self.now()), who or e['author'], canon({'kind': e['kind'], 'target': e['target'],
                                                                                           'scope': e['scope'], 'reason': e['reason']})))
        except sqlite3.Error as ex:
            raise OverrideError(f'could not save the change ({ex})')
        return self.get(e['uid'])

    def _head_for(self, kind, target, scope, model, asset_id):
        for e in self.entries(heads_only=True):
            if (e['kind'], e['target'], e['scope']) == (kind, target, scope) and e['model'].casefold() == (model or '').casefold() \
                    and e['asset_id'].casefold() == (asset_id or '').casefold():
                return e
        return None

    def add(self, kind, target, value, scope, reason, *, model='', asset_id='', author=None, session=None, **opts):
        _need_dev(session, self.devmode)
        if scope in STORED_SCOPES and self._head_for(kind, str(target), scope, model, asset_id):
            raise OverrideError('this item is already overridden in that scope; edit the existing override instead')
        e = build_entry(kind, target, value, scope, reason, model=model, asset_id=asset_id, author=author, session=session,
                        devmode=self.devmode, now=self.now(), **opts)
        return self._insert(e, 'create', author)

    def edit(self, uid, *, value, reason, author=None, session=None, **opts):
        _need_dev(session, self.devmode)
        prev = self.get(uid)
        if prev is None:
            raise OverrideError('no such override')
        if any(x['supersedes'] == uid for x in self.entries(heads_only=False)):
            raise OverrideError('that version has been superseded; edit the newest one')
        for k in ('fw_match', 'expires_at', 'tested'):
            opts.setdefault(k, None if k == 'tested' else prev.get(k))
        opts.setdefault('label', prev['value'].get('label', ''))
        if prev['kind'] == 'command' or prev['kind'] == 'param' or prev['kind'] == 'text':
            opts.setdefault('factory', prev['value'].get('factory'))
        e = build_entry(prev['kind'], prev['target'], value, prev['scope'], reason, model=prev['model'], asset_id=prev['asset_id'],
                        author=author, session=session, devmode=self.devmode, now=self.now(),
                        version=prev['version'] + 1, supersedes=uid, enabled=prev['enabled'], **opts)
        if not opts.get('factory_hash') and not e['factory_hash']:
            e['factory_hash'] = prev['factory_hash']
            if e['kind'] == 'limit':
                e['mac'] = self.devmode.mac(_mac_payload(e))
        return self._insert(e, 'edit', author)

    def reset(self, uid, who=None, session=None):
        """Reset to factory = disable the override (the row stays for the audit trail)."""
        return self.set_enabled(uid, False, who, session)

    def set_enabled(self, uid, enabled, who=None, session=None):
        _need_dev(session, self.devmode)
        e = self.get(uid)
        if e is None:
            raise OverrideError('no such override')
        self._refuse_if_locked(e.get('model') or '')
        try:
            with self._db() as con:
                con.execute('UPDATE override SET enabled=? WHERE uid=?', (int(bool(enabled)), uid))
                con.execute('INSERT INTO override_log(uid,action,at,who,detail) VALUES(?,?,?,?,?)',
                            (uid, 'enable' if enabled else 'disable', _iso(self.now()), who or default_author(), ''))
        except sqlite3.Error as ex:
            raise OverrideError(f'could not save the change ({ex})')
        return self.get(uid)


# ------------------------------------------------------------------------------------------------------------ override set
class OverrideSet:
    """Immutable view of the overrides in effect for one model / asset / run.  Build with resolve()."""
    __slots__ = ('_cands', 'model', 'asset', 'idn', '_hash', '_status', '_devmode', '_verify', '_now', '_frozen')

    def __init__(self, candidates, model, asset, idn=None, devmode=None, now=None, verify=True):
        object.__setattr__(self, '_frozen', False)
        cands = tuple(canon(c) for c in candidates)
        object.__setattr__(self, '_cands', cands)
        for k, v in (('model', model), ('asset', asset), ('idn', idn), ('_devmode', devmode), ('_now', now), ('_verify', verify)):
            object.__setattr__(self, k, v)
        status = _evaluate([json.loads(c) for c in cands], idn, now, devmode, verify)
        object.__setattr__(self, '_status', tuple(status))
        act = sorted([e['uid'], e['kind'], e['target'], canon(e['value']), e['scope']] for e, s in zip(map(json.loads, cands), status) if s == 'active')
        object.__setattr__(self, '_hash', sha(act) if act else '')
        object.__setattr__(self, '_frozen', True)

    def __setattr__(self, k, v):
        raise AttributeError('OverrideSet is immutable')

    def _all(self):
        return [dict(json.loads(c), status=s) for c, s in zip(self._cands, self._status)]

    @property
    def hash(self) -> str:
        return self._hash

    def __bool__(self):
        return any(s == 'active' for s in self._status)

    def entries(self, status=None) -> list:
        """Every candidate with a 'status': active, shadowed, expired, pending_fw, no_fw, tampered."""
        return [e for e in self._all() if status is None or e['status'] == status]

    def active(self, kind=None) -> list:
        return [e for e in self._all() if e['status'] == 'active' and (kind is None or e['kind'] == kind)]

    def tampered(self) -> list:
        return self.entries('tampered')

    @property
    def has_limits(self) -> bool:
        return bool(self.active('limit'))

    def with_idn(self, idn):
        """The same set re-evaluated once the instrument's *IDN? is known (fw_match conditions)."""
        return OverrideSet([json.loads(c) for c in self._cands], self.model, self.asset, idn, self._devmode, self._now, self._verify)

    def _find(self, kind, target):
        for e in self.active(kind):
            if e['target'] == target:
                return e
        return None

    def commands_for(self, driver, registry=None) -> dict:
        """{key: template} to pass to inst.use_commands().  `driver` is a class / instance (validated against its merged COMMANDS)
        or a class name (applied unchecked; send-time validation still runs)."""
        return self._command_eval(driver, registry)[0]

    def rejected_commands(self, driver, registry=None) -> list:
        """[(uid, [problems])] for command overrides that were not applied (invalid or stale)."""
        return self._command_eval(driver, registry)[1]

    def _command_eval(self, driver, registry=None):
        if isinstance(driver, str):
            names, reg, dname = [driver], registry, driver
        else:
            cls = driver if isinstance(driver, type) else type(driver)
            names, reg, dname = [c.__name__ for c in cls.__mro__], registry or cmdreg.merge_commands(cls), cls.__name__
        out, rejected, rank = {}, [], {}
        for e in self.active('command'):
            name, _, key = e['target'].partition(':')
            if name not in names:
                continue
            tpl = e['value'].get('template')
            if reg is not None:
                cmd = reg.get(key)
                probs = [str(p) for p in cmdreg.validate(tpl, cmd, dname)] if cmd else ['unknown command']
                if cmd and not probs and e['factory_hash'] and e['factory_hash'] != fh(cmd.template):
                    probs = ['stale: the factory command changed since this override was made']
                if probs:
                    rejected.append((e['uid'], probs))
                    continue
            r = names.index(name)
            if key not in rank or r < rank[key]:
                rank[key], out[key] = r, tpl
        if reg is not None:
            bad = cmdreg.validate_bundle(out, reg)
            if bad:
                rejected.append(('bundle', [str(b) for b in bad]))
                out = {}
        return out, rejected

    def param(self, name, default=None, point_key=None):
        for target in ([f'{name}@{point_key}'] if point_key else []) + [name]:
            e = self._find('param', target)
            if e:
                if e['factory_hash'] and '@' not in target and e['factory_hash'] != fh(default) and default is not None:
                    return default                       # factory default changed: stale, not applied
                return e['value'].get('value')
        return default

    def point_override(self, key):
        return self._find('point', key)

    def limit_override(self, key):
        return self._find('limit', key)

    def text(self, key, default=''):
        e = self._find('text', key)
        if e and not (e['factory_hash'] and e['factory_hash'] != fh(default)):
            return e['value'].get('text', default)
        return default


def _evaluate(cands, idn, now, devmode, verify):
    status = []
    for e in cands:
        s = 'active'
        if e['kind'] == 'limit' and verify:
            try:
                ok = devmode.verify_mac(_mac_payload(e), e.get('mac')) if devmode else False
            except Exception:
                ok = False
            if not ok:
                s = 'tampered'
        if s == 'active' and _expired(e, now):
            s = 'expired'
        if s == 'active' and e.get('fw_match'):
            if idn is None:
                s = 'pending_fw'
            else:
                try:
                    s = 'active' if re.search(e['fw_match'], str(idn), re.I) else 'no_fw'
                except re.error:
                    s = 'no_fw'
        status.append(s)
    best = {}
    for i, (e, s) in enumerate(zip(cands, status)):
        if s != 'active':
            continue
        k = (e['kind'], e['target'])
        score = (RANK.get(e['scope'], 0), e.get('created_at', ''), e.get('version', 1))
        if k not in best or score > best[k][0]:
            best[k] = (score, i)
    for i, (e, s) in enumerate(zip(cands, status)):
        if s == 'active' and best[(e['kind'], e['target'])][1] != i:
            status[i] = 'shadowed'
    return status


def resolve(model, asset, run_overrides=None, idn=None, *, store=None, now=None, factory_only=False, devmode=None) -> OverrideSet:
    """Overrides in effect for this model / asset (+ in-memory run entries).  Never raises: an unreadable DB gives an empty set.
    factory_only=True ("Run factory") returns an empty set."""
    store = store or Store()
    now = now or store.now()
    if factory_only:
        return OverrideSet([], model, asset, idn, None, now)
    cands = store.candidates(model, asset)
    for r in (run_overrides or []):
        r = copy.deepcopy(r)
        r['scope'] = 'run'
        r.setdefault('uid', 'run-' + secrets.token_hex(3))
        cands.append(r)
    dm = devmode or (store.devmode if any(c['kind'] == 'limit' for c in cands) else None)
    return OverrideSet(cands, model, asset, idn, dm, now)


# ------------------------------------------------------------------------------------------------------------ apply
def _bytes(v):
    return canon(v).encode('utf-8')


def assert_limits_unchanged(orig, patched, limit_ok=()):
    """Every point: all limit fields (and every field outside the mutable set) byte-identical, except error/low/high of the indices
    in `limit_ok` (points with a valid limit override).  Raises LimitsChangedError."""
    if len(orig) != len(patched):
        raise LimitsChangedError('point count changed')
    per_point = {s['field'] for s in PARAMS.values() if s['per_point']}
    for i, (a, b) in enumerate(zip(orig, patched)):
        mutable = _MUTABLE_BASE | per_point | (set(LIMIT_PATCH_FIELDS) if i in limit_ok else set())
        for k in set(a) | set(b):
            if k in mutable:
                continue
            if _bytes(a.get(k, '\0missing')) != _bytes(b.get(k, '\0missing')):
                raise LimitsChangedError(f'point {i}: field {k!r} changed')
        for k in LIMIT_FIELDS:
            if k in LIMIT_PATCH_FIELDS and i in limit_ok:
                continue
            if _bytes(a.get(k, '\0missing')) != _bytes(b.get(k, '\0missing')):
                raise LimitsChangedError(f'point {i}: limit field {k!r} changed')


def check_points(points, oset) -> dict:
    """{'stale': [(uid, key)], 'orphan': [(uid, key)]} for point / limit / per-point entries that no longer fit the spec."""
    keys = point_keys(points)
    byk = dict(zip(keys, points))
    stale, orphan = [], []
    for e in oset.active():
        t = e['target']
        if e['kind'] in ('point', 'limit'):
            p = byk.get(t)
            if p is None:
                orphan.append((e['uid'], t))
            elif e['factory_hash'] and e['factory_hash'] != point_hash(p):
                stale.append((e['uid'], t))
            elif e['kind'] == 'limit' and not _factory_matches(p, e['value'].get('factory')):
                stale.append((e['uid'], t))
        elif e['kind'] == 'param' and '@' in t:
            p = byk.get(t.partition('@')[2])
            if p is None:
                orphan.append((e['uid'], t))
        elif e['kind'] == 'text' and t.partition(':')[0] in ('setup', 'note'):
            p = byk.get(t.partition(':')[2])
            if p is None:
                orphan.append((e['uid'], t))
            elif t.startswith('setup:') and e['factory_hash'] and e['factory_hash'] != fh(p.get('setup')):
                stale.append((e['uid'], t))
    return {'stale': stale, 'orphan': orphan}


def apply_points(points, oset) -> list:
    """Patched COPIES of the points: skip flag, setup/note text, per-point settings and - only through valid enabled, HMAC-verified
    limit overrides - error/low/high.  Stale or orphaned entries are not applied.  Unmodified points come back as plain copies.
    Call after the period has been applied (p['error'] set).  Limit fields of every other kind are guarded byte-identical."""
    keys = point_keys(points)
    check = check_points(points, oset)
    bad = {u for u, _k in check['stale'] + check['orphan']}
    act = [e for e in oset.active() if e['uid'] not in bad]
    by = {}
    for e in act:
        by.setdefault(e['kind'], {})[e['target']] = e
    out, limit_ok = [], set()
    for i, (p, k) in enumerate(zip(points, keys)):
        q = copy.deepcopy(p)
        used = []
        e = by.get('point', {}).get(k)
        if e:
            q['skip'] = True
            used.append(e['uid'])
        e = by.get('limit', {}).get(k)
        if e:
            _apply_limit(q, e['value'])
            limit_ok.add(i)
            used.append(e['uid'])
        for t, e in by.get('param', {}).items():
            name, _, pk = t.partition('@')
            if pk == k and name in PARAMS and PARAMS[name]['per_point']:
                q[PARAMS[name]['field']] = e['value']['value']
                used.append(e['uid'])
        e = by.get('text', {}).get('setup:' + k)
        if e:
            q['setup'] = e['value']['text']
            used.append(e['uid'])
        e = by.get('text', {}).get('note:' + k)
        if e:
            q['tech_note'] = e['value']['text']
            used.append(e['uid'])
        if used:
            q['ov'] = used
        out.append(q)
    assert_limits_unchanged(points, out, limit_ok)
    return out


# ------------------------------------------------------------------------------------------------------------ snapshots
def _clean(e):
    d = copy.deepcopy(e)
    d.pop('status', None)
    d.pop('id', None)
    return d


def build_snapshot(oset, prior=None, now=None) -> dict:
    """{'revs': [{'rev', 'at', 'entries'}], 'hash'} - appends a revision to `prior` only when the effective set changed."""
    revs = copy.deepcopy((prior or {}).get('revs') or [])
    if not revs or revs[-1].get('hash') != oset.hash:
        revs.append({'rev': len(revs) + 1, 'at': _iso(now or datetime.now()), 'entries': [_clean(e) for e in oset.active()],
                     'hash': oset.hash})
    return {'revs': revs, 'hash': oset.hash}


def verify_snapshot(snap) -> bool:
    """True when the stored hash matches the entries of the last revision."""
    try:
        rev = snap['revs'][-1]
        act = sorted([e['uid'], e['kind'], e['target'], canon(e['value']), e['scope']] for e in rev['entries'])
        h = sha(act) if act else ''
        return h == snap['hash'] == rev.get('hash', h)
    except (KeyError, IndexError, TypeError):
        return False


def restore_snapshot(snap, rev=None, *, idn=None, devmode=None, verify=True, model=None, asset=None) -> OverrideSet:
    """The OverrideSet saved in a checkpoint / report (default: last revision).  Expiry is not re-evaluated.  verify=False skips the
    limit-row HMAC check (re-printing a report on another PC)."""
    revs = (snap or {}).get('revs') or []
    r = next((x for x in revs if x['rev'] == rev), None) if rev else (revs[-1] if revs else None)
    ents = copy.deepcopy(r['entries']) if r else []
    dm = devmode or (_devmode.DevMode() if verify and any(e['kind'] == 'limit' for e in ents) else None)
    return OverrideSet(ents, model, asset, idn, dm, None, verify)


def compare_with_current(snap, current) -> dict:
    """{'same', 'added', 'removed', 'changed'} between the saved snapshot and the current OverrideSet (lists of (kind, target))."""
    saved = {(e['kind'], e['target']): e for e in (snap['revs'][-1]['entries'] if snap and snap.get('revs') else [])}
    now = {(e['kind'], e['target']): e for e in current.active()}
    added = sorted(set(now) - set(saved))
    removed = sorted(set(saved) - set(now))
    changed = sorted(k for k in set(saved) & set(now) if canon(saved[k]['value']) != canon(now[k]['value']))
    return {'same': not (added or removed or changed), 'added': added, 'removed': removed, 'changed': changed}


def record_run_snapshot(run_id, snapshot, demo=False, store=None) -> bool:
    """Record the snapshot of an issued report in run_overrides.  Demo mode records nothing; an unmodified run (no entries) records
    nothing.  The snapshot may include 'run' scope entries: it is the evidence of what the issued report used."""
    if demo or snapshot is None:
        return False
    if isinstance(snapshot, OverrideSet):
        snapshot = build_snapshot(snapshot)
    if not snapshot.get('revs') or not snapshot['revs'][-1]['entries']:
        return False
    store = store or Store()
    text = canon(snapshot)
    try:
        with store._db() as con:
            con.execute('INSERT OR REPLACE INTO run_overrides(run_id,snapshot_json,sha256) VALUES(?,?,?)', (str(run_id), text, sha(text)))
        return True
    except sqlite3.Error:
        return False


def get_run_snapshot(run_id, store=None):
    store = store or Store()
    try:
        with store._db() as con:
            row = con.execute('SELECT snapshot_json,sha256 FROM run_overrides WHERE run_id=?', (str(run_id),)).fetchone()
        return json.loads(row[0]) if row and sha(row[0]) == row[1] else None
    except (sqlite3.Error, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------------ export / import
_EXPORT_FIELDS = ('uid', 'kind', 'target', 'scope', 'model', 'asset_id', 'value', 'factory_hash', 'fw_match', 'reason', 'author',
                  'created_at', 'version', 'expires_at', 'tested')


def export_entries(store, path=None, *, model=None, asset_id=None, session=None, who=None):
    """Write the enabled override heads to a *.calov.json payload.  'run' scope is never included.  Limit entries are included only
    with an unlocked developer-mode session (and only if their HMAC verifies).  Returns (payload, notes)."""
    _need_dev(session, store.devmode)
    notes, ents = [], []
    dev_ok = True
    for e in store.entries(model=model, asset_id=asset_id, heads_only=True, enabled=True):
        if e['scope'] not in STORED_SCOPES:
            continue
        if e['kind'] == 'limit':
            if not dev_ok:
                notes.append(f'tolerance change for {e["target"]} not exported (developer mode is locked)')
                continue
            if not store.devmode.verify_mac(_mac_payload(e), e.get('mac')):
                notes.append(f'tolerance change for {e["target"]} not exported (TAMPERED)')
                continue
        ents.append({k: copy.deepcopy(e.get(k)) for k in _EXPORT_FIELDS})
    payload = {'format': FORMAT, 'schema': SCHEMA_VERSION, 'created_at': _iso(store.now()), 'exported_by': who or default_author(),
               'entries': ents, 'sha256': sha(ents)}
    if path:
        Path(path).write_text(json.dumps(payload, indent=1, sort_keys=True), encoding='utf-8')
    return payload, notes


def _load_payload(data):
    if isinstance(data, dict):
        return data
    text = data
    if isinstance(data, Path) or (isinstance(data, str) and '\n' not in data and not data.lstrip().startswith('{')):
        text = Path(data).read_text(encoding='utf-8')
    return json.loads(text)


def _validate_import_entry(e, registries, session, dm):
    """Problems for one imported entry (structural; points are not available so limit values are checked for shape only)."""
    probs = []
    try:
        if e.get('kind') not in KINDS:
            return [f'unknown kind {e.get("kind")!r}']
        if e.get('scope') not in STORED_SCOPES:
            return [f'scope {e.get("scope")!r} cannot be imported']
        if not str(e.get('reason') or '').strip():
            probs.append('no reason')
        k, v = e['kind'], e.get('value') or {}
        if k == 'command':
            name, _, key = e['target'].partition(':')
            cmd = ((registries or {}).get(name) or {}).get(key)
            if cmd is None:
                probs.append('this command is not known here; cannot be checked')
            else:
                probs += [str(p) for p in cmdreg.validate(v.get('template'), cmd, name)]
                if e.get('factory_hash') and e['factory_hash'] != fh(cmd.template):
                    probs.append('the factory command differs from the one this override was made against')
        elif k == 'param':
            probs += _check_param_value(e['target'].partition('@')[0], v.get('value'))
        elif k == 'text':
            probs += _check_text(e['target'], v.get('text'))
        elif k == 'limit':
            if v.get('mode') == 'error':
                n = _num(v.get('error'))
                if n is None or n <= 0:
                    probs.append('bad tolerance value')
            elif v.get('mode') == 'band':
                if not any(_num(v.get(x)) is not None for x in ('low', 'high')):
                    probs.append('bad tolerance value')
            else:
                probs.append('bad tolerance mode')
    except Exception as ex:
        probs.append(f'could not check ({type(ex).__name__})')
    return probs


def import_preview(store, data, *, registries=None, session=None) -> dict:
    """Parse and check a *.calov.json (path, text or dict).  Applies NOTHING.  Returns
    {'ok', 'problems', 'items': [{'index', 'entry', 'accept', 'conflict', 'existing_uid', 'problems', 'needs_devmode'}]}.
    conflict: None | 'identical' | 'different'.  accept defaults True only for clean, non-conflicting, applicable entries."""
    res = {'ok': False, 'problems': [], 'items': []}
    try:
        payload = _load_payload(data)
    except (OSError, ValueError, TypeError):
        res['problems'].append('not a readable override file')
        return res
    if not isinstance(payload, dict) or payload.get('format') != FORMAT:
        res['problems'].append('not a calov file')
        return res
    if payload.get('schema') != SCHEMA_VERSION:
        res['problems'].append(f'unsupported schema version {payload.get("schema")!r}')
        return res
    ents = payload.get('entries')
    if not isinstance(ents, list) or payload.get('sha256') != sha(ents):
        res['problems'].append('the file was modified after export (checksum mismatch)')
        return res
    heads = store.entries(heads_only=True)
    for i, e in enumerate(ents):
        probs = _validate_import_entry(e, registries, session, store.devmode)
        needs = e.get('kind') == 'limit'
        conflict, existing = None, None
        if isinstance(e, dict):
            for h in heads:
                if (h['kind'], h['target'], h['scope']) == (e.get('kind'), e.get('target'), e.get('scope')) \
                        and h['model'].casefold() == str(e.get('model') or '').casefold() and h['asset_id'].casefold() == str(e.get('asset_id') or '').casefold():
                    existing = h['uid']
                    same = canon({k: v for k, v in h['value'].items() if k != '_import'}) == canon({k: v for k, v in (e.get('value') or {}).items() if k != '_import'})
                    conflict = 'identical' if same else 'different'
        res['items'].append({'index': i, 'entry': e, 'accept': not probs and conflict is None, 'conflict': conflict,
                             'existing_uid': existing, 'problems': probs, 'needs_devmode': needs})
    res['ok'] = True
    return res


def apply_import(store, preview, *, who=None, session=None, accept=None) -> list:
    """Apply the accepted entries of a preview (accept: iterable of indices overriding the preview's flags).  Entries keep their
    author and gain imported_by; tested info is dropped (they are UNVERIFIED here).  Returns the created entries."""
    _need_dev(session, store.devmode)
    chosen = {it['index'] for it in preview['items'] if it['accept']} if accept is None else set(accept)
    created = []
    for it in preview['items']:
        if it['index'] not in chosen:
            continue
        if it['problems']:
            raise OverrideError(f'entry {it["index"]} has problems: ' + '; '.join(it['problems']))
        e = it['entry']
        who = who or default_author()
        value = copy.deepcopy(e['value'])
        value['_import'] = {'by': who, 'at': _iso(store.now()), 'from_uid': e.get('uid'),
                            'tested_elsewhere': e.get('tested') or None}
        uid = e.get('uid') if store.get(e.get('uid') or '') is None else None
        head = store._head_for(e['kind'], e['target'], e['scope'], e.get('model', ''), e.get('asset_id', ''))
        row = {'uid': uid or secrets.token_hex(4), 'kind': e['kind'], 'target': e['target'], 'scope': e['scope'],
               'model': e.get('model') or '', 'asset_id': e.get('asset_id') or '', 'value': value,
               'factory_hash': e.get('factory_hash') or '', 'fw_match': e.get('fw_match'), 'reason': e['reason'].strip(),
               'author': e.get('author') or '', 'created_at': e.get('created_at') or _iso(store.now()),
               'version': (head['version'] + 1) if head else 1, 'supersedes': head['uid'] if head else None, 'enabled': 1,
               'expires_at': e.get('expires_at'), 'tested': None, 'mac': None}
        if e['kind'] == 'limit':
            row['mac'] = store.devmode.mac(_mac_payload(row))
        created.append(store._insert(row, 'import', who))
    return created


def imported_by(entry):
    return (entry.get('value') or {}).get('_import', {}).get('by')


# ------------------------------------------------------------------------------------------------------------ view-model
def _scope_text(e, oset=None):
    if e['scope'] == 'run':
        return 'this run only'
    if e['scope'] == 'asset':
        return f'asset {e["asset_id"]}'
    return f'all {e["model"]}'


def _unverified(e):
    return e['kind'] == 'command' and not e.get('tested')


def _stale_uids(oset, points=None, driver_registries=None, defaults=None):
    stale = set()
    if points is not None:
        c = check_points(points, oset)
        stale |= {u for u, _ in c['stale'] + c['orphan']}
    for e in oset.active('command'):
        name, _, key = e['target'].partition(':')
        cmd = ((driver_registries or {}).get(name) or {}).get(key)
        if cmd and e['factory_hash'] and e['factory_hash'] != fh(cmd.template):
            stale.add(e['uid'])
    for e in oset.active('param'):
        if defaults and e['target'] in defaults and e['factory_hash'] and e['factory_hash'] != fh(defaults[e['target']]):
            stale.add(e['uid'])
    return stale


def rows(driver_registries, oset, filter='all', search='', stale=None) -> list:
    """Plain dicts for the Commands list.  driver_registries = {driver_name: {key: Cmd}}.  state in
    factory | modified | unverified | locked | stale; `modified` / `unverified` are also given as booleans."""
    stale = stale if stale is not None else _stale_uids(oset, None, driver_registries)
    out = []
    needle = (search or '').casefold()
    for dname, reg in (driver_registries or {}).items():
        for key, cmd in reg.items():
            target = command_target(dname, key)
            ov = next((e for e in oset.entries() if e['kind'] == 'command' and e['target'] == target and e['status'] == 'active'), None)
            ok, why = cmdreg.is_overridable(cmd)
            is_stale = bool(ov and ov['uid'] in stale)
            applied = bool(ov and not is_stale and ok)
            current = ov['value']['template'] if applied else cmd.template
            unv = ok and ((not cmd.verified) or (applied and _unverified(ov)))
            state = 'locked' if not ok else 'stale' if is_stale else 'modified' if applied else 'unverified' if unv else 'factory'
            row = {'key': key, 'target': target, 'driver': dname, 'name': cmd.name or key, 'description': cmd.description,
                   'factory': cmd.template, 'current': current, 'state': state, 'modified': applied, 'unverified': bool(unv),
                   'locked': not ok, 'lock_reason': why, 'risk': cmd.risk, 'kind': cmd.kind, 'ref': cmd.ref,
                   'uid': ov['uid'] if ov else None, 'reason': ov['reason'] if ov else '', 'readback': cmd.readback,
                   'placeholders': sorted(cmd.placeholders)}
            if needle and needle not in ' '.join((key, row['name'], cmd.description, cmd.template, current)).casefold():
                continue
            if filter == 'modified' and state not in ('modified', 'stale'):
                continue
            if filter == 'unverified' and not unv:
                continue
            if filter == 'locked' and not row['locked']:
                continue
            out.append(row)
    return out


def setting_rows(oset, defaults=None, filter='all', search='') -> list:
    """Rows for registered tunables: {name: factory default} -> dicts (key, name, factory, current, state, affects_conditions)."""
    out = []
    for name, spec in PARAMS.items():
        d = (defaults or {}).get(name)
        e = next((x for x in oset.active('param') if x['target'] == name), None)
        stale = bool(e and d is not None and e['factory_hash'] and e['factory_hash'] != fh(d))
        cur = e['value']['value'] if e and not stale else d
        state = 'stale' if stale else 'modified' if e else 'factory'
        row = {'key': name, 'name': spec['label'], 'factory': d, 'current': cur, 'state': state, 'modified': state == 'modified',
               'affects_conditions': spec['affects_conditions'], 'unit': spec['unit'], 'uid': e['uid'] if e else None,
               'locked': False, 'lock_reason': ''}
        if search and search.casefold() not in f'{name} {spec["label"]}'.casefold():
            continue
        if filter == 'modified' and state == 'factory':
            continue
        if filter in ('unverified', 'locked'):
            continue
        out.append(row)
    return out


def point_rows(points, oset, filter='all', search='') -> list:
    """Rows for the Points tab: key, description, state (skip / limit / text changes), stale flags."""
    keys = point_keys(points)
    chk = check_points(points, oset)
    stale = {u for u, _ in chk['stale']}
    act = oset.active()
    out = []
    for p, k in zip(points, keys):
        mine = [e for e in act if e['target'] == k or e['target'].endswith('@' + k) or e['target'].endswith(':' + k)]
        kinds = sorted({e['kind'] for e in mine})
        st = 'stale' if any(e['uid'] in stale for e in mine) else 'modified' if mine else 'factory'
        row = {'key': k, 'name': p.get('description') or p.get('desc') or k, 'state': st, 'modified': bool(mine), 'kinds': kinds,
               'skip': 'point' in kinds, 'limit': 'limit' in kinds, 'unverified': False, 'locked': False, 'lock_reason': ''}
        if search and search.casefold() not in f'{k} {row["name"]}'.casefold():
            continue
        if filter == 'modified' and st == 'factory':
            continue
        if filter in ('unverified', 'locked'):
            continue
        out.append(row)
    return out


def changes(oset, points=None, driver_registries=None, defaults=None) -> list:
    """The Changes tab / diff: one dict per override candidate with factory vs current text and its status (stale is added when the
    spec / registries / defaults are supplied)."""
    stale = _stale_uids(oset, points, driver_registries, defaults)
    out = []
    for e in oset.entries():
        v, f = e['value'], None
        if e['kind'] == 'command':
            f, cur = v.get('factory'), v.get('template')
        elif e['kind'] == 'param':
            f, cur = v.get('factory'), v.get('value')
        elif e['kind'] == 'point':
            f, cur = 'measured', 'skipped'
        elif e['kind'] == 'text':
            f, cur = v.get('factory'), v.get('text')
        else:
            f, cur = _tolerance_text(v.get('factory'), v, v.get('unit', ''))
        out.append({'uid': e['uid'], 'kind': e['kind'], 'target': e['target'], 'label': v.get('label') or e['target'], 'factory': f,
                    'current': cur, 'scope': e['scope'], 'applies_to': _scope_text(e), 'reason': e['reason'], 'author': e['author'],
                    'at': e['created_at'], 'status': 'stale' if e['uid'] in stale and e['status'] == 'active' else e['status'],
                    'unverified': _unverified(e), 'affects_conditions': bool(v.get('affects_conditions')),
                    'imported_by': imported_by(e)})
    return out


def modifications_summary(oset) -> list:
    """Lines for the report's "Procedure modifications" block ([] when nothing is in effect).  Each dict: text, reason, author, date,
    unverified, affects_conditions, applies_to, kind, uid, limit (bool), manufacturer_tolerance, tolerance_used and
    tolerances_modified (True on limit lines: tells the report to print the header line)."""
    out = []
    for e in oset.active():
        v, k = e['value'], e['kind']
        label = v.get('label') or e['target']
        man = used = ''
        if k == 'command':
            text = f'Command "{label}": {v.get("factory")} -> {v.get("template")}'
        elif k == 'param':
            text = f'Setting "{label}"{"" if "@" not in e["target"] else " (point " + e["target"].partition("@")[2] + ")"}: {v.get("factory")} -> {v.get("value")}'
        elif k == 'point':
            text = f'Point {label} skipped'
        elif k == 'text':
            text = f'Text "{label}" changed'
        else:
            man, used = _tolerance_text(v.get('factory'), v, v.get('unit', ''))
            text = f'Tolerance for {label}: manufacturer {man}, used {used}'
        fac = used_v = ''
        if k == 'command':
            fac, used_v = v.get('factory'), v.get('template')
        elif k == 'param':
            fac, used_v = v.get('factory'), v.get('value')
        elif k == 'limit':
            fac, used_v = man, used
        out.append({'item': label, 'factory': '' if fac is None else str(fac), 'used': '' if used_v is None else str(used_v),
                    'version': e.get('version'),
                    'text': text, 'reason': e['reason'], 'author': e['author'], 'date': e['created_at'][:10],
                    'unverified': _unverified(e), 'affects_conditions': bool(v.get('affects_conditions')),
                    'applies_to': _scope_text(e), 'kind': k, 'uid': e['uid'], 'limit': k == 'limit',
                    'manufacturer_tolerance': man, 'tolerance_used': used, 'tolerances_modified': k == 'limit',
                    'imported_by': imported_by(e)})
    return out


def modifications_for_report(run_id, store=None) -> list:
    """Plain function for the engines: the "Procedure modifications" lines of an issued run, read back from run_overrides in
    lab_registry.sqlite3 (see record_run_snapshot).  [] when the run had no overrides, was a demo run, or the stored row fails its
    checksum.  Never raises.  Pass the result as write_calibration_pdf(..., modifications=...)."""
    try:
        snap = get_run_snapshot(run_id, store=store)
        if not snap:
            return []
        return modifications_summary(restore_snapshot(snap, verify=False))
    except Exception:
        return []


def tolerances_modified(oset) -> bool:
    """True when any limit override is in effect (the report prints the 'tolerances modified' header line)."""
    return oset.has_limits
