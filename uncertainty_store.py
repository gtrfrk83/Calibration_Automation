"""Saved uncertainty calculations (the Uncertainty Calculator tab), kept in the lab registry file so they can be reviewed, edited and copied later.

    uncertainty_store.save(name, state, summary='', calc_id=None) -> id     (a new row, or the same row updated when calc_id is given)
    uncertainty_store.load(calc_id)  -> dict(id, name, state, summary, created_at, updated_at) or None
    uncertainty_store.listing(term='') -> [dict(id, name, summary, updated_at)], newest first
    uncertainty_store.duplicate(calc_id, new_name) -> new id or None
    uncertainty_store.delete(calc_id) -> bool

`state` is the calculator's own JSON-able dict (what was typed, not the result: the numbers are worked out again when it is opened).  The table is added to
lab_registry.sqlite3 with CREATE TABLE IF NOT EXISTS; calibration_procedures.sqlite3 is never touched.  Nothing here raises on a damaged or missing file: callers
get None / [] / False instead.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import labregistry

SCHEMA = '''
CREATE TABLE IF NOT EXISTS uncertainty_calcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL
);
'''


@contextmanager
def _db():
    con = sqlite3.connect(str(labregistry.DB), timeout=5)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def save(name, state, summary='', calc_id=None):
    name = (name or '').strip() or 'Untitled uncertainty'
    try:
        blob = json.dumps(state, sort_keys=True)
        with _db() as con:
            if calc_id is not None and con.execute('SELECT 1 FROM uncertainty_calcs WHERE id=?', (calc_id,)).fetchone():
                con.execute('UPDATE uncertainty_calcs SET name=?, updated_at=?, summary=?, state_json=? WHERE id=?', (name, _now(), summary, blob, calc_id))
                return calc_id
            cur = con.execute('INSERT INTO uncertainty_calcs(name, created_at, updated_at, summary, state_json) VALUES (?,?,?,?,?)', (name, _now(), _now(), summary, blob))
            return cur.lastrowid
    except (sqlite3.Error, TypeError, ValueError):
        return None


def load(calc_id):
    try:
        with _db() as con:
            row = con.execute('SELECT id, name, summary, created_at, updated_at, state_json FROM uncertainty_calcs WHERE id=?', (calc_id,)).fetchone()
        if not row:
            return None
        return dict(id=row[0], name=row[1], summary=row[2], created_at=row[3], updated_at=row[4], state=json.loads(row[5]))
    except (sqlite3.Error, ValueError):
        return None


def listing(term=''):
    try:
        with _db() as con:
            rows = con.execute('SELECT id, name, summary, updated_at FROM uncertainty_calcs ORDER BY updated_at DESC, id DESC').fetchall()
    except sqlite3.Error:
        return []
    out = [dict(id=r[0], name=r[1], summary=r[2], updated_at=r[3]) for r in rows]
    t = (term or '').strip().lower()
    return [r for r in out if t in r['name'].lower() or t in r['summary'].lower()] if t else out


def duplicate(calc_id, new_name):
    rec = load(calc_id)
    return save(new_name, rec['state'], rec['summary']) if rec else None


def delete(calc_id):
    try:
        with _db() as con:
            return con.execute('DELETE FROM uncertainty_calcs WHERE id=?', (calc_id,)).rowcount > 0
    except sqlite3.Error:
        return False
