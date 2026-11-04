"""Standards used for a run: the list the owner chose up front (CANDIDATES), what the run shows actually touched each point (OBSERVED), and the rule that joins them.
Toolkit-free (no Tk / Qt), additive: with an empty list nothing in the review or the report changes.

    StandardsUsed   the list: StandardUse(model, asset, role) entries, 'bench profiles' stored in lab_registry.sqlite3 (tables bench_profiles / bench_profile_items;
                    calibration_procedures.sqlite3 is never touched).  It is stored with the report: details['uncertainty_review']['standards_used'].
    capture         install() wraps drivers.transport.CommandLog.add and manual_override.ManualOverrideMixin.mo_begin at run time (those files are fingerprinted by 71 / 3
                    verified procedures and are NOT edited): a log gets `point` (the point that is current) and `touched` ({point: [instrument label, ...]}, the instruments
                    that were WRITTEN to while it was current).  Nothing is added to the wire.
    assignment      assign(...) -> Assignment: candidates = the list that the sheets cover at the point; observed use wins; the tie-break is returned as text;
                    a second observed standard (role measure / monitor / amplifier / coil) is combined by report_review_model.evaluate as extra RSS components.

OBSERVED = the instrument's label is in the command log for that point.  ASSUMED = no capture exists for the point (typed readings, engines without the hook,
a log that did not see any listed standard): the first listed standard that covers the point is used and the row says 'assumed'.  A second standard is never assumed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

OBSERVED, ASSUMED = 'observed', 'assumed'
FORMAT_VERSION = 1
ROLES = ('source', 'measure', 'monitor', 'amplifier', 'coil')
PRIMARY_ROLES = ('source', 'measure')               # what can be the first standard of a point
SECOND_ROLES = ('measure', 'monitor', 'amplifier', 'coil')
DIRECTION = {'source': 'output', 'amplifier': 'output', 'coil': 'output', 'measure': 'input', 'monitor': 'input'}
# models that have a sheet in specs/standards and whose direction fits the role (checked against the sheets, see tests/test_standards_used.py)
CANDIDATE_MODELS = {'5560A': 'source', '5522A': 'source', '5520A': 'source', '5700A': 'source', '33250A': 'source', '96270A': 'source',
                    '5790B': 'measure', '3458A': 'measure', '34461A': 'measure', '34465A': 'measure', '8902A': 'measure', '8563E': 'measure',
                    'A2LA-5500A-COIL': 'coil'}
LABELS = {'5700A': 'Fluke 5700A', '33250A': 'Keysight 33250A', '96270A': 'Fluke 96270A', '5790B': 'Fluke 5790B', '3458A': 'Keysight 3458A',
          '34461A': 'Keysight 34461A', '34465A': 'Keysight 34465A', '8902A': 'HP 8902A', '8563E': 'HP 8563E'}
_MODEL_RE = re.compile('|'.join(sorted((re.escape(m) for m in CANDIDATE_MODELS if not m.startswith('A2LA')), key=len, reverse=True)), re.I)


@dataclass
class StandardUse:
    model: str
    asset: str = ''
    role: str = 'source'

    def __post_init__(self):
        self.model = str(self.model or '').strip().upper().replace('FLUKE', '').replace('KEYSIGHT', '').replace('AGILENT', '').strip() if self.model not in CANDIDATE_MODELS else self.model
        self.asset = str(self.asset or '').strip()
        self.role = self.role if self.role in ROLES else CANDIDATE_MODELS.get(self.model, 'source')

    @property
    def direction(self) -> str:
        return DIRECTION[self.role]

    def as_dict(self) -> dict:
        return dict(model=self.model, asset=self.asset, role=self.role)


class StandardsUsed:
    """The ordered list of standards the owner picked (add by model number, optional asset number).  The order is the tie-break order."""

    def __init__(self, items=(), profile=''):
        self.items: list[StandardUse] = []
        self.profile = profile
        for it in items:
            self.add(**it) if isinstance(it, dict) else self.add(it.model, it.asset, it.role)

    def add(self, model, asset='', role=None):
        s = StandardUse(model, asset, role or CANDIDATE_MODELS.get(str(model).strip().upper(), 'source'))
        if not s.model:
            raise ValueError('a standard needs a model number')
        if any(x.model == s.model and x.asset == s.asset and x.role == s.role for x in self.items):
            return s
        self.items.append(s)
        return s

    def remove(self, model, asset=''):
        self.items = [x for x in self.items if not (x.model == model and x.asset == asset)]

    def __bool__(self):
        return bool(self.items)

    def __iter__(self):
        return iter(self.items)

    def models(self) -> list:
        out = []
        for x in self.items:
            if x.model not in out:
                out.append(x.model)
        return out

    def find(self, model, role=None):
        return [x for x in self.items if x.model == model and (role is None or x.role == role)]

    def record(self) -> dict:
        return dict(version=FORMAT_VERSION, profile=self.profile, list=[x.as_dict() for x in self.items])

    @classmethod
    def from_record(cls, rec):
        rec = rec or {}
        return cls(rec.get('list') or [], rec.get('profile', ''))


# ---------------------------------------------------------------------------------------------------------------------------- bench profiles (lab_registry.sqlite3)
DDL = '''
CREATE TABLE IF NOT EXISTS bench_profiles (
    name TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT '',
    saved TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bench_profile_items (
    profile TEXT NOT NULL REFERENCES bench_profiles(name) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    model TEXT NOT NULL,
    asset TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'source',
    PRIMARY KEY (profile, position)
);
'''


def _db():
    import labregistry
    return labregistry._db()


def save_profile(name, standards, note='') -> bool:
    """Store the list as bench profile `name` (replaces a profile of that name).  False when it cannot be stored (never raises)."""
    name = str(name or '').strip()
    if not name:
        return False
    try:
        from datetime import datetime
        with _db() as con:
            con.executescript(DDL)
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('DELETE FROM bench_profiles WHERE name=?', (name,))
            con.execute('INSERT INTO bench_profiles(name,note,saved) VALUES(?,?,?)', (name, note, datetime.now().isoformat(timespec='seconds')))
            for i, s in enumerate(standards):
                con.execute('INSERT INTO bench_profile_items(profile,position,model,asset,role) VALUES(?,?,?,?,?)', (name, i, s.model, s.asset, s.role))
        return True
    except Exception:
        return False


def load_profile(name):
    """The StandardsUsed saved as `name`, or None."""
    try:
        with _db() as con:
            con.executescript(DDL)
            if con.execute('SELECT 1 FROM bench_profiles WHERE name=?', (name,)).fetchone() is None:
                return None
            rows = con.execute('SELECT model,asset,role FROM bench_profile_items WHERE profile=? ORDER BY position', (name,)).fetchall()
        return StandardsUsed([dict(model=m, asset=a, role=r) for m, a, r in rows], profile=name)
    except Exception:
        return None


def profile_names() -> list:
    try:
        with _db() as con:
            con.executescript(DDL)
            return [r[0] for r in con.execute('SELECT name FROM bench_profiles ORDER BY name')]
    except Exception:
        return []


def delete_profile(name) -> bool:
    try:
        with _db() as con:
            con.executescript(DDL)
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('DELETE FROM bench_profiles WHERE name=?', (name,))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------------------------------------------------------- the list for the next review
_session = StandardsUsed()


def session_list() -> StandardsUsed:
    """The list chosen for this session (empty = the feature is off and every review is exactly what it always was)."""
    return _session


def set_session_list(standards) -> StandardsUsed:
    global _session
    _session = standards if isinstance(standards, StandardsUsed) else StandardsUsed(standards or ())
    return _session


# ---------------------------------------------------------------------------------------------------------------------------- capture (read side)
def model_of_label(label):
    """'5560A' / 'Fluke5790B' / 'Keysight 3458A' -> the model key the sheets use, or None (the unit under test, a meter, anything unknown)."""
    m = _MODEL_RE.search(str(label or ''))
    return m.group(0).upper() if m else None


_installed = False


def install() -> bool:
    """Switch the capture on for this process: wraps drivers.transport.CommandLog.add (to note which instrument label is written to while a point is current) and
    manual_override.ManualOverrideMixin.mo_begin (to say which point is current).  The originals run FIRST and unchanged, so the wire, the log text and the evidence
    log are exactly what they were; the wrapper only records.  Done by wrapping at run time - NOT by editing drivers/transport.py or manual_override.py - because
    those files are in the fingerprint of 71 / 3 verified procedures and editing them would flip every one of them to 'Changed since verification'.
    Idempotent; never raises; called at start-up (qtui.app.create_app) and by the review flow.  A log made before install() has no capture (`observed_for` -> None)."""
    global _installed
    if _installed:
        return True
    try:
        import manual_override
        from drivers import transport
        orig_add, orig_begin = transport.CommandLog.add, manual_override.ManualOverrideMixin.mo_begin

        def add(self, direction, text, instrument=''):
            orig_add(self, direction, text, instrument)
            try:
                d = self.__dict__
                touched = d.setdefault('touched', {})
                pt = d.get('point')
                if pt is not None and direction == '>>' and instrument:
                    seen = touched.setdefault(pt, [])
                    if instrument not in seen:
                        seen.append(instrument)
            except Exception:
                pass

        def mo_begin(self, p):
            orig_begin(self, p)
            mark_point(self, p)

        transport.CommandLog.add = add
        manual_override.ManualOverrideMixin.mo_begin = mo_begin
        _installed = True
    except Exception:
        return False
    return True


def mark_point(app, p):
    """The run loop (mo_begin) calls this when point p starts: later commands to any instrument are attributed to it.  Never raises."""
    try:
        log = getattr(getattr(app, 'io', None), 'log', None) or getattr(app, 'log', None)
        if log is not None and hasattr(log, 'entries'):
            log.__dict__.setdefault('touched', {})
            log.__dict__['point'] = str(p.get('id', p.get('ref', '')))
    except Exception:
        pass


def logs_of(app) -> list:
    out = []
    for o in (getattr(getattr(app, 'io', None), 'log', None), getattr(app, 'log', None)):
        if o is not None and 'touched' in getattr(o, '__dict__', {}) and o not in out:
            out.append(o)
    return out


def observed_for(app) -> dict | None:
    """{point id (str): [model key, ...]} for the standards written to while each point was current, in the order first seen.  None = this engine has no capture
    (so every row is 'assumed')."""
    logs = logs_of(app)
    if not logs:
        return None
    out = {}
    for log in logs:
        for pt, labels in log.touched.items():
            for lab in labels:
                m = model_of_label(lab)
                if m and m not in out.setdefault(pt, []):
                    out[pt].append(m)
    return out


# ---------------------------------------------------------------------------------------------------------------------------- the rule
@dataclass
class Assignment:
    primary: StandardUse | None = None
    second: StandardUse | None = None
    basis: str = ASSUMED                           # OBSERVED | ASSUMED
    candidates: list = field(default_factory=list)  # listed standards whose sheet covers the point
    tie_break: str = ''
    why: str = ''
    gap: bool = False                              # no listed standard covers the point
    demo: bool = False                             # the run was simulated: nothing here is evidence
    unlisted: bool = False                         # the engine's standard is not in the list

    def uses(self) -> list:
        return [dict(s.as_dict(), basis=self.basis if s is self.primary else OBSERVED) for s in (self.primary, self.second) if s is not None]

    def as_dict(self) -> dict:
        return dict(standards=self.uses(), basis=self.basis, candidates=[c.as_dict() for c in self.candidates], tie_break=self.tie_break, why=(('SIMULATED RUN - not evidence. ' if self.demo else '') + self.why), gap=self.gap, unlisted=self.unlisted, demo=self.demo)


def assign(listed, observed, covers, exclude=(), engine_default=None) -> Assignment:
    """listed   StandardsUsed (the candidates, in tie-break order)
    observed    [model key] seen on the wire for this point, or None when the engine / point has no capture
    covers      callable(StandardUse) -> text of the spec row that covers the point (truthy) or ''   (spec-row coverage: kind, amplitude, frequency band, direction)
    exclude     model keys never counted as observed (the unit under test's own model)
    engine_default  the standard the engine itself used for the point: with no capture it stays the assumed one when it is listed and covers the point
    Returns the Assignment: observed use wins; with none the first listed standard that covers the point is ASSUMED."""
    a = Assignment()
    cov = [(s, covers(s)) for s in listed]
    a.candidates = [s for s, t in cov if t]
    text = {id(s): t for s, t in cov}
    if not a.candidates:
        a.gap, a.why = True, 'no listed standard has a specification row for this point'
        return a
    seen = [m for m in (observed or []) if m not in exclude]
    prim_pool = [s for s in a.candidates if s.role in PRIMARY_ROLES]
    sec_pool = [s for s in a.candidates if s.role in SECOND_ROLES]
    hit = next(((m, s) for m in seen for s in prim_pool if s.model == m), None)
    if hit is not None:
        a.primary, a.basis = hit[1], OBSERVED
        same = [s for s in prim_pool if s.model == hit[0]]
        if len(same) > 1:
            a.tie_break = f'{hit[0]} is listed {len(same)} times for this role: the first listed (asset {same[0].asset or "none"}) is used'
        others = [s for s in prim_pool if s.model != hit[0]]
        if others:
            a.tie_break = (a.tie_break + '; ' if a.tie_break else '') + 'also covering and listed, but not used on the wire: ' + ', '.join(sorted({s.model for s in others}))
        sec = next(((m, s) for m in seen for s in sec_pool if s.model == m and s is not a.primary and s.model != hit[0]), None)
        if sec is not None:
            a.second = sec[1]
        a.why = f'{hit[0]} was written to while this point ran (observed); spec row: {text[id(hit[1])]}'
    else:
        pool = prim_pool or a.candidates
        own = next((s for s in pool if engine_default and s.model == engine_default), None)
        a.primary = own or pool[0]
        a.basis = ASSUMED
        if own is not None:
            if len({s.model for s in pool}) > 1:
                a.tie_break = f"listed and covering: {', '.join(sorted({s.model for s in pool}))} - the engine's own standard ({own.model}) is kept"
        elif len(pool) > 1:
            a.tie_break = 'listed and covering: ' + ', '.join(s.model for s in pool) + ' - the first listed is used'
        if own is None and engine_default:
            a.tie_break = (a.tie_break + '; ' if a.tie_break else '') + f'the engine used {engine_default}, which is not in the list or does not cover the point'
        a.why = ('no capture for this point' if observed is None else 'no listed standard was seen on the wire for this point') + f' (assumed); spec row: {text[id(a.primary)]}'
    return a
