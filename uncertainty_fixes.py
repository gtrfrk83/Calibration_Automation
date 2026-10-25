"""Remembered fixes for points the lab scope does not cover (the review window's 'Why?' panel), kept in the lab registry file.

    uncertainty_fixes.save_fix(procedure, section, description, unit, text, source, reason, who, like=False) -> id
    uncertainty_fixes.last_fix(procedure, section, description, unit)   -> dict or None   (the newest fix for exactly that point)
    uncertainty_fixes.like_rule(procedure, section, unit)               -> dict or None   ('use it for all points like this')
    uncertainty_fixes.flag(procedure, asset, section, description, note, who) -> id     (the 'Flag for quality' list)
    uncertainty_fixes.flags(open_only=True)                             -> [dict]

A fix is text the review window can type into a not-in-scope row (for example '0.012 dB'); it never touches a point the scope covers, a limit or a result.
Tables are added to lab_registry.sqlite3 with CREATE TABLE IF NOT EXISTS; calibration_procedures.sqlite3 is never touched.  Nothing here raises on a damaged
or missing file: callers get None / [] instead.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import labregistry

SCHEMA = '''
CREATE TABLE IF NOT EXISTS uncertainty_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    like INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    who TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS uncertainty_fixes_key ON uncertainty_fixes(procedure, section, unit);
CREATE TABLE IF NOT EXISTS uncertainty_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure TEXT NOT NULL DEFAULT '',
    asset TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    who TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
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


def _row(cols, r):
    return dict(zip(cols, r)) if r else None


COLS = ('id', 'procedure', 'section', 'description', 'unit', 'like', 'text', 'source', 'reason', 'who', 'at')


def save_fix(procedure, section, description, unit, text, source='', reason='', who='', like=False):
    try:
        with _db() as con:
            cur = con.execute('INSERT INTO uncertainty_fixes(procedure, section, description, unit, like, text, source, reason, who, at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                              (procedure or '', section or '', description or '', unit or '', 1 if like else 0, text, source or '', reason or '', who or '', _now()))
            return cur.lastrowid
    except sqlite3.Error:
        return None


def last_fix(procedure, section, description, unit):
    try:
        with _db() as con:
            r = con.execute(f'SELECT {", ".join(COLS)} FROM uncertainty_fixes WHERE procedure=? AND section=? AND description=? AND unit=? ORDER BY id DESC LIMIT 1',
                            (procedure or '', section or '', description or '', unit or '')).fetchone()
        return _row(COLS, r)
    except sqlite3.Error:
        return None


def like_rule(procedure, section, unit):
    try:
        with _db() as con:
            r = con.execute(f'SELECT {", ".join(COLS)} FROM uncertainty_fixes WHERE like=1 AND procedure=? AND section=? AND unit=? ORDER BY id DESC LIMIT 1',
                            (procedure or '', section or '', unit or '')).fetchone()
        return _row(COLS, r)
    except sqlite3.Error:
        return None


FLAG_COLS = ('id', 'procedure', 'asset', 'section', 'description', 'note', 'who', 'at', 'status')


def flag(procedure, asset, section, description, note='', who=''):
    try:
        with _db() as con:
            cur = con.execute('INSERT INTO uncertainty_flags(procedure, asset, section, description, note, who, at) VALUES (?,?,?,?,?,?,?)',
                              (procedure or '', asset or '', section or '', description or '', note or '', who or '', _now()))
            return cur.lastrowid
    except sqlite3.Error:
        return None


def flags(open_only=True):
    try:
        with _db() as con:
            rows = con.execute(f'SELECT {", ".join(FLAG_COLS)} FROM uncertainty_flags' + (" WHERE status='open'" if open_only else '') + ' ORDER BY id DESC').fetchall()
        return [_row(FLAG_COLS, r) for r in rows]
    except sqlite3.Error:
        return []


def who_am_i() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return ''
