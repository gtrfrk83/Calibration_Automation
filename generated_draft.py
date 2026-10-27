"""DRAFT marking and owner approval of GENERATED procedures (Procedure Generator).  No Qt, no instrument I/O.

A procedure made by the Procedure Generator is a DRAFT until the owner approves it.  A draft CAN be run on the bench, but:
    * starting a run asks for a confirmation that says it is not approved (dsb_runtime.DsbApp.execute),
    * the run window carries a red banner (DsbApp._draft_banner),
    * every page of the PDF report carries the banner (report_pdf: details['draft_note']).
Approving removes the marking from LATER runs; reports already issued keep what they were printed with.

What is stored (lab_registry.sqlite3 only; calibration_procedures.sqlite3 is never opened):
    generated_procedures   one row per generated procedure (uid, project, current version, who built it, the unverified list)
    generated_approvals    APPEND-ONLY events (triggers refuse UPDATE and DELETE): 'approve' / 'draft_again' with who, when, the version and a note.
The state is worked out from the events: approved only when the LAST event is an 'approve' of the CURRENT version.  A rebuild (new version) is a draft again,
without anyone having to remember to un-approve it.  A procedure that is not in generated_procedures is not generated: state() says so and nothing changes for it.
"""
from __future__ import annotations

import getpass
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DRAFT_TEXT = 'DRAFT: not approved by the owner'
RUN_START_TITLE = 'Draft procedure'
RUN_START_TEXT = ('This procedure was generated from a manual and has NOT been approved by the owner.\n\n'
                  'It may contain misread limits or wrong settings. Every report you export from this run will carry the banner "' + DRAFT_TEXT + '" on every page.\n\n'
                  'Run it anyway?')
MIN_WHO = 2

SCHEMA = '''
CREATE TABLE IF NOT EXISTS generated_procedures (
    uid TEXT PRIMARY KEY COLLATE NOCASE,
    project_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    built_by TEXT NOT NULL DEFAULT '',
    built_at TEXT NOT NULL DEFAULT '',
    points INTEGER NOT NULL DEFAULT 0,
    unverified_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS generated_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL COLLATE NOCASE,
    action TEXT NOT NULL CHECK(action IN ('approve','draft_again','built')),
    version INTEGER NOT NULL DEFAULT 0,
    who TEXT NOT NULL CHECK(length(trim(who)) > 0),
    at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS generated_approvals_uid ON generated_approvals(uid, id);
CREATE TRIGGER IF NOT EXISTS generated_approvals_no_update BEFORE UPDATE ON generated_approvals
BEGIN SELECT RAISE(ABORT, 'approval events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS generated_approvals_no_delete BEFORE DELETE ON generated_approvals
BEGIN SELECT RAISE(ABORT, 'approval events are never deleted'); END;
'''


def default_db() -> Path:
    import appdata
    return appdata.db_path('lab_registry.sqlite3')


@contextmanager
def _con(db=None, create=True):
    if create:
        try:
            Path(db or default_db()).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    con = sqlite3.connect(str(db or default_db()), timeout=5)
    try:
        if create:
            con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def default_who() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ''


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


@dataclass
class State:
    generated: bool = False
    draft: bool = False
    version: int = 0
    project_id: str = ''
    approved_by: str = ''
    approved_at: str = ''
    approved_version: int = 0
    built_by: str = ''
    unverified: list = field(default_factory=list)
    history: list = field(default_factory=list)       # [(action, version, who, at, note)]

    @property
    def banner(self) -> str:
        return DRAFT_TEXT if self.draft else ''

    @property
    def text(self) -> str:
        if not self.generated:
            return ''
        if self.draft:
            return DRAFT_TEXT
        return f'Generated procedure, approved by {self.approved_by} on {self.approved_at[:10]}'


def state(uid, db=None) -> State:
    """The draft / approval state of a procedure.  Read only; never creates tables and never raises (a missing or damaged registry means 'not a generated procedure',
    which is what every existing procedure is)."""
    if not uid:
        return State()
    path = Path(db or default_db())
    if not path.is_file():
        return State()
    try:
        with _con(path, create=False) as con:
            row = con.execute('SELECT project_id,version,built_by,unverified_json FROM generated_procedures WHERE uid=?', (str(uid),)).fetchone()
            if row is None:
                return State()
            events = con.execute('SELECT action,version,who,at,note FROM generated_approvals WHERE uid=? ORDER BY id', (str(uid),)).fetchall()
    except sqlite3.Error:
        return State()
    st = State(generated=True, project_id=row[0], version=int(row[1]), built_by=row[2], history=[tuple(e) for e in events])
    try:
        st.unverified = list(json.loads(row[3]))
    except ValueError:
        st.unverified = []
    st.draft = True
    for action, version, who, at, _note in events:
        if action == 'approve' and int(version) == st.version:
            st.draft, st.approved_by, st.approved_at, st.approved_version = False, who, at, int(version)
        elif action in ('draft_again',):
            st.draft, st.approved_by, st.approved_at, st.approved_version = True, '', '', 0
    return st


def register(uid, project_id, version, mode, title, who, points, unverified, sources, db=None) -> None:
    """Record (or update) a generated procedure.  A new version is a draft again: the 'built' event makes that visible in the history."""
    with _con(db) as con:
        con.execute('INSERT INTO generated_procedures(uid,project_id,version,mode,title,built_by,built_at,points,unverified_json,sources_json) VALUES(?,?,?,?,?,?,?,?,?,?) '
                    'ON CONFLICT(uid) DO UPDATE SET project_id=excluded.project_id, version=excluded.version, mode=excluded.mode, title=excluded.title, built_by=excluded.built_by, '
                    'built_at=excluded.built_at, points=excluded.points, unverified_json=excluded.unverified_json, sources_json=excluded.sources_json',
                    (str(uid), project_id, int(version), mode, title, who or 'unknown', _now(), int(points), json.dumps(list(unverified)), json.dumps(dict(sources), sort_keys=True)))
        con.execute('INSERT INTO generated_approvals(uid,action,version,who,at,note) VALUES(?,?,?,?,?,?)',
                    (str(uid), 'built', int(version), who or 'unknown', _now(), f'built from project {project_id}'))


class ApprovalError(ValueError):
    pass


def approve(uid, who, note='', db=None) -> State:
    """The owner approves the CURRENT version of a generated procedure.  `who` is required (typed by the person; the suite has no sign-in, so this is a record,
    not an authentication).  Logged with the time.  Refused for a procedure that is not generated, or one that is already approved."""
    who = (who or '').strip()
    if len(who) < MIN_WHO:
        raise ApprovalError('Type the name of the person approving.')
    st = state(uid, db)
    if not st.generated:
        raise ApprovalError('This is not a generated procedure.')
    if not st.draft:
        raise ApprovalError('This procedure is already approved.')
    with _con(db) as con:
        con.execute('INSERT INTO generated_approvals(uid,action,version,who,at,note) VALUES(?,?,?,?,?,?)', (str(uid), 'approve', st.version, who, _now(), (note or '').strip()))
    return state(uid, db)


def mark_draft_again(uid, who, note='', db=None) -> State:
    """The owner puts the draft marking back (a problem was found after approval).  Logged; later runs and reports carry the banner again."""
    who = (who or '').strip()
    if len(who) < MIN_WHO:
        raise ApprovalError('Type the name of the person.')
    st = state(uid, db)
    if not st.generated:
        raise ApprovalError('This is not a generated procedure.')
    if st.draft:
        raise ApprovalError('This procedure is already marked as a draft.')
    with _con(db) as con:
        con.execute('INSERT INTO generated_approvals(uid,action,version,who,at,note) VALUES(?,?,?,?,?,?)', (str(uid), 'draft_again', st.version, who, _now(), (note or '').strip()))
    return state(uid, db)


def draft_uids(db=None) -> set:
    """The uids of every generated procedure that is currently a draft (the Manager's list marks them)."""
    path = Path(db or default_db())
    if not path.is_file():
        return set()
    try:
        with _con(path, create=False) as con:
            uids = [r[0] for r in con.execute('SELECT uid FROM generated_procedures')]
    except sqlite3.Error:
        return set()
    return {u for u in uids if state(u, path).draft}
