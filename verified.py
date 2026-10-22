"""Verified on hardware: mark a procedure as verified on the real instruments and lock it against edits.  Tk-free; no instrument I/O.

    reg = verified.Registry()                                  # lab_registry.sqlite3 (injectable: Registry(path, base=...))
    entry = verified.make_entry(name, model, script, base)     # the procedure as the Procedures list knows it (user-built: user_uid=...)
    st = reg.status(entry)                                     # Status: .kind none | verified | changed | unlocked, .text, .detail_lines()
    reg.verify(entry, who, on_date, note, hardware)            # record the verification and LOCK
    reg.unlock(entry.proc_key, who, reason)                    # reason required; recorded (who / when / why)
    reg.relock(entry, who)                                     # only when nothing changed since the verification; otherwise verify again
    reg.lock_reason(proc_key='', model='')                     # '' = editable, else the plain sentence every editor shows

What is stored (NEW table proc_verify_events in lab_registry.sqlite3; no existing table is touched; calibration_procedures.sqlite3 is never
opened).  The table is append-only (triggers refuse UPDATE and DELETE): verify / unlock / relock / seed.  The state of a procedure is worked
out from its events, so who verified it, who unlocked it, when and why can always be read back.

What 'locked' means (enforced where the edit would be saved, not only in the buttons):
    * procmods.Store: add / edit / enable / disable / reset / import of a saved procedure change for the model is refused;
    * procmods_ui_model.ProcModsModel (the editor before a run and the in-run 'Edit procedure'): read-only with the sentence above;
    * datasheet_builder: saving a new version of, or deleting, a user-built procedure is refused (Duplicate still works).
Running a locked procedure is not affected, and changes that were saved before the lock stay as they are.

'Changed since verification': at verification time a fingerprint of the procedure's definition is stored: the program files it runs (its
launcher, engine and drivers), its test point / limit file(s) (user-built: the runnable spec) and the saved procedure changes (overrides) for its
model.  Text files are compared without regard to line endings, JSON without regard to layout.  The suite never blocks an update.  A verified
procedure whose fingerprint no longer matches is NOT locked: the first time it is looked at (the Procedures list, or an editor asking whether it is
locked) one auto-unlock event is recorded (who 'system', reason 'files changed since verification: <files>') and the list shows 'Changed since
verification - needs hardware re-verification' until someone presses 'Mark verified on hardware' again.  The fingerprint is only computed
when the list is drawn or a verification is recorded, never during a lock check.

Seed: SEED lists the procedures that are already verified.  It is code (shipped with every copy, so it cannot go missing) and is written into
the registry the first time the real registry is used; a registry that cannot be read treats the seeded procedures as locked.  A registry given
an explicit path (tests) is never seeded.  The baseline fingerprint of a seeded procedure is taken from the files installed when it is first seeded.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DS_PREFIX = 'ds:'
MIN_REASON = 8
SEED_VERSION = 1

SCHEMA = '''
CREATE TABLE IF NOT EXISTS proc_verify_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proc_key TEXT NOT NULL COLLATE NOCASE,
    action TEXT NOT NULL CHECK(action IN ('verify','unlock','relock','seed')),
    at TEXT NOT NULL,
    who TEXT NOT NULL CHECK(length(trim(who)) > 0),
    on_date TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '' CHECK(action <> 'unlock' OR length(trim(reason)) > 0),
    note TEXT NOT NULL DEFAULT '',
    hardware TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    definition_hash TEXT NOT NULL DEFAULT '',
    components_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS proc_verify_key ON proc_verify_events(proc_key, id);
CREATE TRIGGER IF NOT EXISTS proc_verify_no_update BEFORE UPDATE ON proc_verify_events
BEGIN SELECT RAISE(ABORT, 'verification events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS proc_verify_no_delete BEFORE DELETE ON proc_verify_events
BEGIN SELECT RAISE(ABORT, 'verification events are never deleted'); END;
'''

CHANGED_TEXT = 'Changed since verification - needs hardware re-verification'

# ------------------------------------------------------------------------------------------------------------ the seeded list
SEED_WHO = 'Mike (lab owner)'
SEED_DATE = '2026-10-22'
SEED_NOTE = ('Recorded on 2026-10-22 from the lab owner\'s statement that this procedure ran flawlessly on the actual hardware. '
             'The date of the hardware run, the instrument and the calibrator were not entered. The fingerprint was taken from the files '
             'installed when this was first recorded.')
SEED = (
    dict(proc_key='Tektronix_TDS2000C_Verification.py', name='Tektronix TDS2000C / TDS1000C-EDU Performance Verification',
         model='TDS2000C/TDS1000C-EDU'),
    dict(proc_key='WaveSurfer_WS4104HD.py', name='WaveSurfer WS4104HD Verification', model='WS4104HD'),
    dict(proc_key='Fluke_117_Verification.py', name='Fluke 117 Performance Verification', model='117'),
)

# ------------------------------------------------------------------------------------------------------------ what a procedure is made of
_COMMON = ['drivers/base.py', 'drivers/transport.py']


def _files(launcher, engine, drivers, specs=()):
    return {'code': [f'Procedures/{launcher}'] + list(engine) + _COMMON + [f'drivers/{d}.py' for d in drivers],
            'spec': [f'specs/{s}' for s in specs]}


_HH = ['handheld_dmm.py', 'hookups.py']
_TV = ['truevolt_verification.py', 'procspec.py']
_DQ = ['dacq_verification.py', 'procspec.py']
_FG = ['fgen_verification.py']
FILES = {
    'WaveSurfer_WS4104HD.py': _files('WaveSurfer_WS4104HD.py', [], ['lecroy_ws4104hd', 'fluke_5560a']),
    'Fluke_87V.py': _files('Fluke_87V.py', _HH, ['fluke_5560a'], ['fluke_87v_pv.json']),
    'Agilent_34401A.py': _files('Agilent_34401A.py', [], ['scpi_dmm', 'fluke_5560a']),
    'Fluke_8846A_Verification.py': _files('Fluke_8846A_Verification.py', [], ['scpi_dmm', 'fluke_5560a']),
    'Fluke_8846A_Adjustment.py': _files('Fluke_8846A_Adjustment.py', [], ['scpi_dmm']),
    'Keysight_34465A_Verification.py': _files('Keysight_34465A_Verification.py', _TV, ['keysight_truevolt', 'fluke_5560a'], ['keysight_34465a_pv.json']),
    'Keysight_34460A_Verification.py': _files('Keysight_34460A_Verification.py', _TV, ['keysight_truevolt', 'fluke_5560a'], ['keysight_34460a_pv.json']),
    'Keysight_34461A_Verification.py': _files('Keysight_34461A_Verification.py', _TV, ['keysight_truevolt', 'fluke_5560a'], ['keysight_34461a_pv.json']),
    'Keysight_34470A_Verification.py': _files('Keysight_34470A_Verification.py', _TV, ['keysight_truevolt', 'fluke_5560a'], ['keysight_34470a_pv.json']),
    'Keysight_34970A_Verification.py': _files('Keysight_34970A_Verification.py', _DQ, ['keysight_dacq', 'fluke_5560a'], ['keysight_34970a_pv.json']),
    'Keysight_34972A_Verification.py': _files('Keysight_34972A_Verification.py', _DQ, ['keysight_dacq', 'fluke_5560a'], ['keysight_34972a_pv.json']),
    'Tektronix_MDO4000C_Verification.py': _files('Tektronix_MDO4000C_Verification.py', ['mdo4000c_verification.py'],
                                                 ['tektronix_mdo4000c', 'fluke_5560a', 'reference_instruments'],
                                                 ['tektronix_mdo4000c_pv.json', 'mdo4000c_reference_cmc.json']),
    'Tektronix_TDS2000C_Verification.py': _files('Tektronix_TDS2000C_Verification.py', ['tds2000c_verification.py'],
                                                 ['tektronix_tds2000c', 'fluke_5522a_scope', 'fluke_5560a'], ['tektronix_tds2000c_pv.json']),
    'Fluke_110_Verification.py': _files('Fluke_110_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Fluke_113_Verification.py': _files('Fluke_113_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Fluke_114_Verification.py': _files('Fluke_114_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Fluke_115_Verification.py': _files('Fluke_115_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Fluke_116_Verification.py': _files('Fluke_116_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Fluke_117_Verification.py': _files('Fluke_117_Verification.py', _HH, ['fluke_5560a'], ['fluke_110_series_pv.json']),
    'Klein_MM325_Verification.py': _files('Klein_MM325_Verification.py', _HH, ['fluke_5560a'], ['klein_mm325_pv.json']),
    'Keysight_33210A_Verification.py': _files('Keysight_33210A_Verification.py', _FG,
                                              ['keysight_332xx', 'fluke_5790b', 'keysight_5313x', 'reference_instruments'], ['keysight_33210a_pv.json']),
    'Agilent_33220A_Verification.py': _files('Agilent_33220A_Verification.py', _FG,
                                             ['keysight_332xx', 'fluke_5790b', 'keysight_5313x', 'reference_instruments'], ['keysight_33220a_pv.json']),
    'Agilent_33250A_Verification.py': _files('Agilent_33250A_Verification.py', _FG,
                                             ['keysight_332xx', 'fluke_5790b', 'keysight_5313x', 'reference_instruments'], ['keysight_33250a_pv.json']),
    'Fluke_287_Verification.py': _files('Fluke_287_Verification.py', _HH, ['fluke_5560a', 'fluke_28x'], ['fluke_287_289_pv.json']),
    'Fluke_289_Verification.py': _files('Fluke_289_Verification.py', _HH, ['fluke_5560a', 'fluke_28x'], ['fluke_287_289_pv.json']),
    'Fluke_77IV_Verification.py': _files('Fluke_77IV_Verification.py', _HH, ['fluke_5560a'], ['fluke_77iv_pv.json']),
}
USER_CODE = ['Procedures/User_Datasheet.py', 'dsb_runtime.py']      # a user-built procedure: its runnable spec is the rest of its definition


# ------------------------------------------------------------------------------------------------------------ small helpers
class VerifyError(ValueError):
    """Refused, with a plain-language reason."""


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _sha(text) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode('utf-8')).hexdigest()


def _file_digest(path) -> str:
    """Fingerprint of one file: JSON by content (layout does not matter), anything else with line endings normalised; 'MISSING' when absent."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError:
        return 'MISSING'
    if p.suffix.lower() == '.json':
        try:
            return _sha(_canon(json.loads(raw.decode('utf-8-sig'))))
        except ValueError:
            pass
    return _sha(raw.replace(b'\r\n', b'\n'))


def _now_text(now) -> str:
    return now().isoformat(timespec='seconds')


def default_who() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ''


@dataclass(frozen=True)
class Entry:
    """A procedure as the Procedures list knows it."""
    proc_key: str
    name: str = ''
    model: str = ''
    script: str = ''          # absolute path of the launcher script ('' for a user-built procedure)
    spec_path: str = ''       # user-built: its runnable spec file

    @property
    def is_user_built(self) -> bool:
        return self.proc_key.startswith(DS_PREFIX)


def key_for(script, base=HERE, user_uid=None) -> str:
    """The stable key of a procedure: 'ds:<uid>' (user-built), its file name when it sits in Procedures/, else its resolved path."""
    if user_uid:
        return DS_PREFIX + str(user_uid)
    p = Path(script)
    if not p.is_absolute():
        p = Path(base) / p
    try:
        return p.resolve().relative_to((Path(base) / 'Procedures').resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def make_entry(name, model, script, base=HERE, user_uid=None, spec_path='') -> Entry:
    if user_uid:
        return Entry(DS_PREFIX + str(user_uid), name or '', model or '', '', str(spec_path or ''))
    p = Path(script)
    if not p.is_absolute():
        p = Path(base) / p
    return Entry(key_for(script, base), name or '', model or '', str(p.resolve()))


# ------------------------------------------------------------------------------------------------------------ forms
def check_verify_form(who, on_date='', note='', hardware='', today=None):
    """-> (clean dict, [problems]).  Date blank = today; it must be a real date and not in the future."""
    today = today or date.today()
    problems = []
    who = (who or '').strip()
    if not who:
        problems.append('Type the name of the person who verified it.')
    elif len(who) > 80:
        problems.append('The name is too long (80 characters at most).')
    text = (on_date or '').strip()
    if not text:
        d = today
    else:
        import labregistry
        d = labregistry.parse_date(text)
        if d is None:
            problems.append(f'The date "{text}" is not understood. Use year-month-day, for example {today.isoformat()}.')
        elif d > today:
            problems.append('The date is in the future.')
    note, hardware = (note or '').strip(), (hardware or '').strip()
    for label, value in (('note', note), ('instrument / calibrator', hardware)):
        if len(value) > 500:
            problems.append(f'The {label} is too long (500 characters at most).')
    return dict(who=who, on_date=d.isoformat() if d else '', note=note, hardware=hardware), problems


def compose_hardware(instrument='', calibrator='') -> str:
    """The 'run on' line from the two optional dialog fields."""
    parts = []
    if (instrument or '').strip():
        parts.append('Instrument: ' + instrument.strip())
    if (calibrator or '').strip():
        parts.append('Calibrator: ' + calibrator.strip())
    return '; '.join(parts)


def check_unlock_form(who, reason):
    who, reason = (who or '').strip(), (reason or '').strip()
    problems = []
    if not who:
        problems.append('Type your name.')
    if len(reason) < MIN_REASON:
        problems.append('Type the reason for unlocking (a few words: what has to change and why).')
    if len(reason) > 500:
        problems.append('The reason is too long (500 characters at most).')
    return dict(who=who, reason=reason), problems


# ------------------------------------------------------------------------------------------------------------ records
@dataclass
class Record:
    proc_key: str
    name: str = ''
    model: str = ''
    locked: bool = True
    verified_by: str = ''
    verified_on: str = ''
    note: str = ''
    hardware: str = ''
    hash: str = ''
    components: dict = field(default_factory=dict)
    source: str = 'user'                 # 'user' | 'seed'
    recorded_at: str = ''
    unlocked_by: str = ''
    unlocked_at: str = ''
    unlock_reason: str = ''
    unreadable: bool = False             # the registry could not be read: a seeded procedure is treated as locked


def lock_text(rec: Record) -> str:
    """The sentence every refused editor shows."""
    label = f'"{rec.name}"' if rec.name else (f'the procedure for {rec.model}' if rec.model else 'This procedure')
    who = f' ({rec.verified_on}' + (f', {rec.verified_by}' if rec.verified_by else '') + ')' if rec.verified_on or rec.verified_by else ''
    text = (f'{label} is verified on hardware{who} and locked, so it cannot be edited. To change it, select it in the Procedures list of the '
            'Calibration Procedure Manager and press "Unlock for editing" (a reason is required). Running it is not affected, and changes '
            'saved before it was locked stay as they are.')
    if rec.proc_key.startswith(DS_PREFIX):
        text += ' To work on a copy without unlocking, use Duplicate in the Datasheet Builder.'
    return text


@dataclass
class Status:
    kind: str = 'none'                   # 'none' | 'verified' | 'changed' | 'unlocked'
    record: Record | None = None
    changes: list = field(default_factory=list)       # what differs from the verified definition (['program file: handheld_dmm.py', ...])
    changed: bool = False                # the definition differs from the one that was verified (any kind)

    @property
    def locked(self) -> bool:
        return bool(self.record and self.record.locked)

    @property
    def text(self) -> str:
        """The 'Verified on hardware' cell of the Procedures list."""
        r = self.record
        if self.kind == 'none' or r is None:
            return 'Not verified'
        base = f'Verified {r.verified_on}'
        if self.kind == 'verified':
            return base + '  [locked]'
        if self.kind == 'changed':
            return CHANGED_TEXT
        return base + '  [UNLOCKED]' + ('  changed' if self.changed else '')

    @property
    def tone(self) -> str:
        return {'verified': 'good', 'changed': 'warn', 'unlocked': 'warn'}.get(self.kind, 'neutral')

    @property
    def pill(self) -> str:
        r = self.record
        if self.kind == 'none' or r is None:
            return 'NOT VERIFIED ON HARDWARE'
        return {'verified': f'VERIFIED ON HARDWARE {r.verified_on} - LOCKED',
                'changed': CHANGED_TEXT.upper(),
                'unlocked': f'VERIFIED {r.verified_on} - UNLOCKED FOR EDITING'}[self.kind]

    def detail_lines(self) -> list:
        r = self.record
        if self.kind == 'none' or r is None:
            return ['Not marked as verified on hardware. Press "Mark verified on hardware..." after it has run correctly on the real instruments; it is then locked against edits.']
        out = [f'Verified on hardware by {r.verified_by} on {r.verified_on}.']
        if r.hardware:
            out.append(f'Run on: {r.hardware}')
        if r.note:
            out.append(f'Note: {r.note}')
        if self.kind == 'verified':
            out.append('Locked: editing is refused. The files and settings are unchanged since it was verified.')
        elif self.kind == 'changed':
            out.append('NOT locked: it has changed since it was verified (' + '; '.join(self.changes or ['the definition differs']) + ').')
            if r.unlocked_by == 'system':
                out.append(f'Unlocked automatically on {r.unlocked_at[:10]}.')
            out.append('It needs hardware re-verification: run it on the hardware, then press "Mark verified on hardware...".')
        else:
            out.append(f'UNLOCKED by {r.unlocked_by} on {r.unlocked_at[:10]}: {r.unlock_reason}')
            out.append(('It has been changed since it was verified: ' + '; '.join(self.changes or ['the definition differs']) +
                        '. Mark it verified again to lock it.') if self.changed else
                       'Nothing has changed since it was verified, so it can be locked again with one click.')
        if r.source == 'seed':
            out.append('Recorded from the lab owner\'s statement (date, instrument and calibrator of the hardware run not entered).')
        return out


def ui_state(status: Status) -> dict:
    """What the two buttons of the Procedures list show: {'verify': (text, enabled), 'lock': (text, enabled)}."""
    k = status.kind
    if k == 'none':
        return {'verify': ('Mark verified on hardware...', True), 'lock': ('Unlock for editing...', False)}
    if k == 'verified':
        return {'verify': ('Mark verified on hardware...', False), 'lock': ('Unlock for editing...', True)}
    if k == 'changed':
        return {'verify': ('Mark verified on hardware...', True), 'lock': ('Lock again (nothing changed)', False)}
    return {'verify': ('Mark verified again...', True), 'lock': ('Lock again (nothing changed)', not status.changed)}


def describe_changes(old: dict, new: dict) -> list:
    """Friendly list of what differs between two component dicts."""
    names = {'code': 'program file', 'spec': 'test points / limits file', 'overrides': 'saved procedure change'}
    out = []
    for group in ('code', 'spec', 'overrides'):
        a, b = (old or {}).get(group) or {}, (new or {}).get(group) or {}
        for label in sorted(set(a) | set(b)):
            if a.get(label) != b.get(label):
                out.append(f'{names[group]}: {label}' + (' (new)' if label not in a else ' (removed)' if label not in b else ''))
    return out


# ------------------------------------------------------------------------------------------------------------ the registry
_SEEDED = set()          # registry files already seeded in this process


class Registry:
    def __init__(self, path=None, base=None, seed=None, now=None):
        """path None = the real lab registry (and the seeded list applies); an explicit path is never seeded unless seed=True."""
        self.seed = (path is None) if seed is None else bool(seed)
        if path is None:
            import labregistry
            path = labregistry.DB
        self.path = Path(path)
        self.base = Path(base) if base else HERE
        self._now = now or datetime.now

    # ---- storage
    @contextmanager
    def _db(self):
        con = sqlite3.connect(str(self.path), timeout=5)
        try:
            con.executescript(SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()

    @contextmanager
    def _read(self):
        """A read-only look that creates nothing: a registry file without the table (or without the file) reads as 'no events'."""
        if not self.path.is_file():
            raise FileNotFoundError(str(self.path))
        con = sqlite3.connect(str(self.path), timeout=5)             # no schema script here: nothing is created in a file that lacks the table
        try:
            yield con
        finally:
            con.close()

    _COLS = ('id', 'proc_key', 'action', 'at', 'who', 'on_date', 'reason', 'note', 'hardware', 'name', 'model', 'definition_hash', 'components_json')

    def _events(self, con, key=None) -> list:
        sql = f'SELECT {",".join(self._COLS)} FROM proc_verify_events'
        args = ()
        if key is not None:
            sql, args = sql + ' WHERE proc_key=?', (key,)
        return [dict(zip(self._COLS, r)) for r in con.execute(sql + ' ORDER BY id', args)]

    @staticmethod
    def _fold(events) -> dict:
        """{lower-case key: Record} worked out from the events, oldest first."""
        out = {}
        for e in events:
            k = e['proc_key'].casefold()
            if e['action'] in ('verify', 'seed'):
                try:
                    comps = json.loads(e['components_json'] or '{}')
                except ValueError:
                    comps = {}
                out[k] = Record(e['proc_key'], e['name'], e['model'], True, e['who'], e['on_date'], e['note'], e['hardware'],
                                e['definition_hash'], comps if isinstance(comps, dict) else {}, 'seed' if e['action'] == 'seed' else 'user', e['at'])
            elif k in out:
                r = out[k]
                if e['action'] == 'unlock':
                    r.locked, r.unlocked_by, r.unlocked_at, r.unlock_reason = False, e['who'], e['at'], e['reason']
                elif e['action'] == 'relock':
                    r.locked = True
        return out

    def _fallback(self) -> dict:
        """The registry cannot be read: the seeded procedures count as locked (fail safe)."""
        return {s['proc_key'].casefold(): Record(s['proc_key'], s['name'], s['model'], True, SEED_WHO, SEED_DATE, source='seed', unreadable=True)
                for s in SEED}

    def records(self) -> dict:
        """{lower-case proc_key: Record}.  Never raises."""
        try:
            self._ensure_seeded()
            with self._read() as con:
                return self._fold(self._events(con))
        except FileNotFoundError:
            return {}
        except sqlite3.OperationalError as ex:
            if 'no such table' in str(ex):
                return {}
            return self._fallback() if self.seed else {}
        except (sqlite3.Error, OSError):
            return self._fallback() if self.seed else {}

    def record(self, proc_key) -> Record | None:
        return self.records().get(str(proc_key or '').casefold())

    def history(self, proc_key) -> list:
        """[{at, action, who, on_date, reason, note, hardware}] oldest first."""
        try:
            with self._db() as con:
                return [{k: e[k] for k in ('at', 'action', 'who', 'on_date', 'reason', 'note', 'hardware')} for e in self._events(con, proc_key)]
        except sqlite3.Error:
            return []

    # ---- the lock
    def lock_reason(self, proc_key='', model='') -> str:
        """'' when editing is allowed, else the sentence to show.  With a proc_key only that procedure counts; with a model only (the saved
        procedure changes are kept per model) any locked library procedure of that model counts.  User-built procedures match by key only."""
        recs = self.records()

        def still_locked(r):
            if not r.locked:
                return False
            e = self._entry_of(r)
            if e is not None:
                r = self.sync(e) or r        # changed files: auto-unlock (once) instead of refusing
            return r.locked
        key = str(proc_key or '').casefold()
        if key:
            r = recs.get(key)
            return lock_text(r) if r and still_locked(r) else ''
        m = str(model or '').strip().casefold()
        if m:
            for r in recs.values():
                if r.locked and not r.proc_key.startswith(DS_PREFIX) and r.model.strip().casefold() == m and still_locked(r):
                    return lock_text(r)
        return ''

    # ---- what a procedure is made of
    def _override_component(self, con, model) -> dict:
        if not model:
            return {}
        try:
            rows = con.execute('SELECT kind,target,scope,asset_id,value_json FROM override WHERE enabled=1 AND model=? COLLATE NOCASE '
                               'AND uid NOT IN (SELECT supersedes FROM override WHERE supersedes IS NOT NULL)', (model,)).fetchall()
        except sqlite3.Error:
            return {}
        return {f'{k}:{t}@{s}' + (f':{a}' if a else ''): _sha(v or '') for k, t, s, a, v in rows}

    def definition(self, entry: Entry, con=None) -> dict:
        """{'code': {file: digest}, 'spec': {file: digest}, 'overrides': {item: digest}} for the files installed now."""
        base = self.base
        code, spec = {}, {}
        if entry.is_user_built:
            for rel in USER_CODE:
                code[rel] = _file_digest(base / rel)
            if entry.spec_path:
                spec['user spec'] = _file_digest(entry.spec_path)
        elif entry.proc_key in FILES:
            for rel in FILES[entry.proc_key]['code']:
                code[rel] = _file_digest(base / rel)
            for rel in FILES[entry.proc_key]['spec']:
                spec[rel] = _file_digest(base / rel)
        elif entry.script:
            code[Path(entry.script).name] = _file_digest(entry.script)
        if con is not None:
            ov = self._override_component(con, entry.model)
        else:
            try:
                with self._db() as c:
                    ov = self._override_component(c, entry.model)
            except sqlite3.Error:
                ov = {}
        return {'code': code, 'spec': spec, 'overrides': ov}

    @staticmethod
    def definition_hash(components) -> str:
        return _sha(_canon(components))

    # ---- status
    def _status(self, rec: Record | None, entry: Entry, con=None) -> Status:
        if rec is None:
            return Status('none')
        comps = self.definition(entry, con)
        changed = rec.unreadable is False and self.definition_hash(comps) != rec.hash
        changes = describe_changes(rec.components, comps) if changed else []
        if changed and not changes:
            changes = ['the definition differs']
        kind = 'changed' if changed else ('verified' if rec.locked else 'unlocked')
        return Status(kind, rec, changes, changed)

    def status(self, entry: Entry) -> Status:
        return self._status(self.sync(entry), entry)

    # ---- automatic unlock: a verified procedure whose files changed is no longer verified
    def sync(self, entry: Entry) -> Record | None:
        """The record of `entry`.  If it is locked but its fingerprint no longer matches the verified one, record ONE auto-unlock event (who 'system',
        the changed files as the reason) and return the unlocked record; it stays unlocked until someone marks it verified again."""
        rec = self.record(entry.proc_key)
        if rec is None or not rec.locked or rec.unreadable:
            return rec
        comps = self.definition(entry)
        if self.definition_hash(comps) == rec.hash:
            return rec
        changes = describe_changes(rec.components, comps) or ['the definition differs']
        try:
            with self._db() as con:
                con.execute('BEGIN IMMEDIATE')
                cur = self._fold(self._events(con)).get(rec.proc_key.casefold())
                if cur is not None and cur.locked and cur.hash == rec.hash:        # not already done by another window
                    self._insert(con, cur.proc_key, 'unlock', 'system', reason='files changed since verification: ' + '; '.join(changes),
                                 name=cur.name, model=cur.model)
        except sqlite3.Error:
            return rec                                                              # cannot write: stay locked (fail safe)
        return self.record(entry.proc_key)

    def _entry_of(self, rec: Record):
        if rec.proc_key.startswith(DS_PREFIX):
            return None                      # its spec file is only known to the Procedures list, which syncs it
        p = Path(rec.proc_key)
        script = str(p if p.is_absolute() else self.base / 'Procedures' / rec.proc_key)
        return Entry(rec.proc_key, rec.name, rec.model, script)

    def statuses(self, entries) -> dict:
        """{proc_key: Status} for the Procedures list: the registry is read once, and a definition is only worked out for verified procedures."""
        recs = self.records()
        out = {}
        try:
            with self._db() as con:
                for e in entries:
                    r = recs.get(e.proc_key.casefold())
                    if r is not None and r.locked:
                        r = self.sync(e)
                    out[e.proc_key] = self._status(r, e, con)
        except sqlite3.Error:
            for e in entries:
                out[e.proc_key] = self._status(recs.get(e.proc_key.casefold()), e)
        return out

    # ---- actions
    def _insert(self, con, key, action, who, **kw):
        con.execute('INSERT INTO proc_verify_events(proc_key,action,at,who,on_date,reason,note,hardware,name,model,definition_hash,components_json)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key, action, _now_text(self._now), who, kw.get('on_date', ''), kw.get('reason', ''), kw.get('note', ''), kw.get('hardware', ''),
                     kw.get('name', ''), kw.get('model', ''), kw.get('hash', ''), _canon(kw.get('components', {}))))

    def verify(self, entry: Entry, who, on_date='', note='', hardware='', today=None) -> Record:
        """Record 'verified on hardware' and lock.  Refused for a procedure that is already verified, locked and unchanged."""
        clean, problems = check_verify_form(who, on_date, note, hardware, today)
        if problems:
            raise VerifyError(' '.join(problems))
        try:
            with self._db() as con:
                con.execute('BEGIN IMMEDIATE')
                rec = self._fold(self._events(con)).get(entry.proc_key.casefold())
                comps = self.definition(entry, con)
                h = self.definition_hash(comps)
                if rec is not None and rec.locked and rec.hash == h:
                    raise VerifyError('It is already verified and locked, and nothing has changed since. To change it, unlock it first.')
                self._insert(con, entry.proc_key, 'verify', clean['who'], on_date=clean['on_date'], note=clean['note'], hardware=clean['hardware'],
                             name=entry.name, model=entry.model, hash=h, components=comps)
        except sqlite3.Error as ex:
            raise VerifyError(f'Could not save the verification ({ex}).')
        return self.record(entry.proc_key)

    def unlock(self, proc_key, who, reason) -> Record:
        clean, problems = check_unlock_form(who, reason)
        if problems:
            raise VerifyError(' '.join(problems))
        try:
            with self._db() as con:
                con.execute('BEGIN IMMEDIATE')
                rec = self._fold(self._events(con)).get(str(proc_key).casefold())
                if rec is None:
                    raise VerifyError('This procedure has not been marked as verified, so there is nothing to unlock.')
                if not rec.locked:
                    raise VerifyError('It is already unlocked.')
                self._insert(con, rec.proc_key, 'unlock', clean['who'], reason=clean['reason'], name=rec.name, model=rec.model)
        except sqlite3.Error as ex:
            raise VerifyError(f'Could not save the unlock ({ex}).')
        return self.record(proc_key)

    def relock(self, entry: Entry, who) -> Record:
        """Lock again without a new verification: only when nothing changed since it was verified."""
        who = (who or '').strip()
        if not who:
            raise VerifyError('Type your name.')
        try:
            with self._db() as con:
                con.execute('BEGIN IMMEDIATE')
                rec = self._fold(self._events(con)).get(entry.proc_key.casefold())
                if rec is None:
                    raise VerifyError('This procedure has not been marked as verified.')
                if rec.locked:
                    raise VerifyError('It is already locked.')
                if self.definition_hash(self.definition(entry, con)) != rec.hash:
                    raise VerifyError('Something has changed since it was verified, so it cannot simply be locked again. Mark it verified again on the hardware.')
                self._insert(con, rec.proc_key, 'relock', who, name=rec.name, model=rec.model)
        except sqlite3.Error as ex:
            raise VerifyError(f'Could not save the lock ({ex}).')
        return self.record(entry.proc_key)

    # ---- seeding
    def _ensure_seeded(self):
        key = str(self.path)
        if not self.seed or key in _SEEDED:
            return
        self.ensure_seeded()
        _SEEDED.add(key)

    def ensure_seeded(self) -> int:
        """Write a 'seed' event for every SEED procedure that has no event yet (once per registry).  Returns how many were written."""
        n = 0
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            have = {e['proc_key'].casefold() for e in self._events(con)}
            for s in SEED:
                if s['proc_key'].casefold() in have:
                    continue
                entry = Entry(s['proc_key'], s['name'], s['model'], str(self.base / 'Procedures' / s['proc_key']))
                comps = self.definition(entry, con)
                self._insert(con, s['proc_key'], 'seed', SEED_WHO, on_date=SEED_DATE, note=SEED_NOTE, name=s['name'], model=s['model'],
                             hash=self.definition_hash(comps), components=comps)
                n += 1
        return n


def default_registry() -> Registry:
    return Registry()
