"""Edit log of the Standards Spec editor (Tk-free).

Every documented edit of a standards sheet (specs/standards/*.json) is one row of `spec_edits` in lab_registry.sqlite3: who, when, why, from which
source, the SHA-256 of the file before and after, the changed fields (a JSON diff) and the file as it was before (gzip), so that the edit can be
undone later by another documented edit.  `spec_edit_events` holds what happened after the row was written (the sheet rebuild in the database).

Rules (project):
  * Both tables are NEW and created additively (CREATE TABLE IF NOT EXISTS).  calibration_procedures.sqlite3 is never touched and no existing
    table of lab_registry.sqlite3 is changed.
  * Append-only: triggers refuse every UPDATE and DELETE.  A mistake is corrected by a later entry (a restore is an entry), never by rewriting one.
  * No function raises on a missing / damaged file when it only READS: callers get empty results.  `append` raises (the caller then undoes the
    file write: an edit without a log row must not stay).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = '''
CREATE TABLE IF NOT EXISTS spec_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    spec_file TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'edit',
    edited_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL,
    backup_file TEXT NOT NULL DEFAULT '',
    sha_before TEXT NOT NULL,
    sha_after TEXT NOT NULL,
    diff_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    restored_from INTEGER,
    rebuild_requested INTEGER NOT NULL DEFAULT 0,
    before_gz BLOB
);
CREATE INDEX IF NOT EXISTS spec_edits_file ON spec_edits(spec_file, id);
CREATE TRIGGER IF NOT EXISTS spec_edits_no_update BEFORE UPDATE ON spec_edits
BEGIN SELECT RAISE(ABORT, 'spec_edits is append-only'); END;
CREATE TRIGGER IF NOT EXISTS spec_edits_no_delete BEFORE DELETE ON spec_edits
BEGIN SELECT RAISE(ABORT, 'spec_edits is append-only'); END;
CREATE TABLE IF NOT EXISTS spec_edit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edit_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS spec_edit_events_edit ON spec_edit_events(edit_id, id);
CREATE TRIGGER IF NOT EXISTS spec_edit_events_no_update BEFORE UPDATE ON spec_edit_events
BEGIN SELECT RAISE(ABORT, 'spec_edit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS spec_edit_events_no_delete BEFORE DELETE ON spec_edit_events
BEGIN SELECT RAISE(ABORT, 'spec_edit_events is append-only'); END;
'''

COLUMNS = ('id', 'at', 'spec_file', 'model', 'kind', 'edited_by', 'reason', 'source', 'backup_file', 'sha_before', 'sha_after', 'diff_json',
           'summary', 'restored_from', 'rebuild_requested')


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def default_path():
    import labregistry
    return labregistry.DB


@contextmanager
def _db(path=None):
    con = sqlite3.connect(str(path or default_path()), timeout=5)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


@contextmanager
def _read(path=None):
    """A read-only look that creates nothing: a registry without the tables (or without the file) reads as 'no edits'."""
    p = Path(path or default_path())
    if not p.is_file():
        raise FileNotFoundError(str(p))
    con = sqlite3.connect(str(p), timeout=5)
    try:
        yield con
    finally:
        con.close()


def _now(now=None) -> str:
    return (now or datetime.now)().isoformat(timespec='seconds')


def _entry(row) -> dict:
    d = dict(zip(COLUMNS, row))
    try:
        d['diff'] = json.loads(d.pop('diff_json') or '[]')
    except ValueError:
        d['diff'] = []
    return d


# ------------------------------------------------------------------------------------------------------------ writing
def append(spec_file, model, kind, edited_by, reason, source, sha_before, sha_after, diff, summary, before_bytes,
           backup_file='', restored_from=None, rebuild_requested=False, path=None, now=None) -> int:
    """Add one documented edit.  Returns its id.  Raises ValueError for a missing who / reason / source or an unknown kind, sqlite3.Error on a database problem."""
    if kind not in ('edit', 'restore'):
        raise ValueError(f'unknown kind {kind!r}')
    for name, value in (('edited by', edited_by), ('reason', reason), ('source', source)):
        if not str(value or '').strip():
            raise ValueError(f'{name} is required')
    with _db(path) as con:
        cur = con.execute(
            'INSERT INTO spec_edits(at,spec_file,model,kind,edited_by,reason,source,backup_file,sha_before,sha_after,diff_json,summary,restored_from,'
            'rebuild_requested,before_gz) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (_now(now), spec_file, model or '', kind, edited_by.strip(), reason.strip(), source.strip(), backup_file or '', sha_before, sha_after,
             json.dumps(diff, ensure_ascii=False), summary or '', restored_from, 1 if rebuild_requested else 0, gzip.compress(before_bytes or b'', 6)))
        return cur.lastrowid


def add_event(edit_id, event, detail='', path=None, now=None) -> int:
    with _db(path) as con:
        return con.execute('INSERT INTO spec_edit_events(edit_id,at,event,detail) VALUES(?,?,?,?)', (edit_id, _now(now), event, detail or '')).lastrowid


# ------------------------------------------------------------------------------------------------------------ reading
def entries(spec_file, path=None) -> list:
    """The documented edits of one sheet file, newest first (dicts with 'diff' decoded; the before-file is not loaded)."""
    try:
        with _read(path) as con:
            rows = con.execute(f'SELECT {",".join(COLUMNS)} FROM spec_edits WHERE spec_file=? ORDER BY id DESC', (spec_file,)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [_entry(r) for r in rows]


def entry(edit_id, path=None):
    try:
        with _read(path) as con:
            row = con.execute(f'SELECT {",".join(COLUMNS)} FROM spec_edits WHERE id=?', (edit_id,)).fetchone()
    except (OSError, sqlite3.Error):
        return None
    return _entry(row) if row else None


def before_bytes(edit_id, path=None):
    """The file as it was before the edit (checked against sha_before), or None when it is not stored / does not match."""
    try:
        with _read(path) as con:
            row = con.execute('SELECT before_gz, sha_before FROM spec_edits WHERE id=?', (edit_id,)).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if not row or row[0] is None:
        return None
    try:
        raw = gzip.decompress(row[0])
    except (OSError, EOFError):
        return None
    return raw if sha256_bytes(raw) == row[1] else None


def events(edit_id, path=None) -> list:
    try:
        with _read(path) as con:
            rows = con.execute('SELECT at,event,detail FROM spec_edit_events WHERE edit_id=? ORDER BY id', (edit_id,)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [dict(at=a, event=e, detail=d) for a, e, d in rows]


def count(spec_file, path=None) -> int:
    try:
        with _read(path) as con:
            return con.execute('SELECT COUNT(*) FROM spec_edits WHERE spec_file=?', (spec_file,)).fetchone()[0]
    except (OSError, sqlite3.Error):
        return 0


def last_editor(path=None) -> str:
    """The name used for the most recent documented edit of ANY sheet ('' when none): the default of the 'Edited by' box."""
    try:
        with _read(path) as con:
            row = con.execute('SELECT edited_by FROM spec_edits ORDER BY id DESC LIMIT 1').fetchone()
    except (OSError, sqlite3.Error):
        return ''
    return row[0] if row else ''


def hand_edit_state(spec_file, current_sha, path=None) -> dict:
    """Where a sheet file stands against its log (no file access):

        state 'as built'            no documented edit
        state 'edited by hand'      the file is exactly what the last documented edit wrote, and that differs from the file before the first edit
        state 'back to as built'    the file equals the file before the first documented edit
        state 'changed outside'     the file is neither: it was replaced after the last documented edit (a builder script was run again, or it was edited some other way)
    """
    es = entries(spec_file, path)
    if not es:
        return dict(state='as built', edits=0, last=None, built_sha='')
    first, last = es[-1], es[0]
    built_sha = first['sha_before']
    if current_sha == last['sha_after']:
        state = 'back to as built' if current_sha == built_sha else 'edited by hand'
    elif current_sha == built_sha:
        state = 'back to as built'
    else:
        state = 'changed outside'
    return dict(state=state, edits=len(es), last=last, built_sha=built_sha)
