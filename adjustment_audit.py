"""Audit record of an instrument ADJUSTMENT (calibration constants changed), in lab_registry.sqlite3.

The pattern of the Fluke 8846A guided adjustment (one run record + one event per action, shown in the window as the audit log) kept for the Keithley 2000, with the differences
the standing rules ask for:
  * the tables live in lab_registry.sqlite3 (new tables, nothing of calibration_procedures.sqlite3 is touched); no schema of an existing table is changed;
  * NOTHING that is a calibration code / password is ever written: a command text goes through `clean()`, which masks a :CODE argument, and the procedure never passes the code at all;
  * a DEMO session never reaches the database: it writes to an in-memory database that disappears with the window, every row says DEMO, and Asset History is not involved;
  * nothing is exported to a file: the record is the database and the window's audit log.

    store = AuditStore(demo=False)
    run_id = store.start_run('Keithley 2000', asset, serial, technician, uut_idn=..., firmware=..., scope='ALL')
    store.log('STEP', 'OK', 'D03 +10 V DC: :CAL:PROT:DC:STEP3 10', step_id='D03')
    store.set_status('SAVED_NOT_VERIFIED')
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS adjustment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    asset_id TEXT NOT NULL COLLATE NOCASE,
    serial TEXT NOT NULL DEFAULT '',
    technician TEXT NOT NULL DEFAULT '',
    uut_idn TEXT NOT NULL DEFAULT '',
    firmware TEXT NOT NULL DEFAULT '',
    calibrator TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    demo INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS adjustment_runs_asset ON adjustment_runs(asset_id, started_at);
CREATE TABLE IF NOT EXISTS adjustment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES adjustment_runs(id) ON DELETE CASCADE,
    event_time TEXT NOT NULL,
    step_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS adjustment_events_run ON adjustment_events(run_id);
'''

CODE_ARG = re.compile(r"(CODE\s*)(['\"]?)[^'\"\s;]*\2", re.I)


def clean(text) -> str:
    """Defence in depth: a text that carries a :CODE argument is masked. (The calibration code is never passed to this module in the first place.)"""
    return CODE_ARG.sub(lambda m: f"{m.group(1)}'********'", str(text))


def default_path() -> Path:
    import appdata
    return appdata.db_path('lab_registry.sqlite3')


class AuditStore:
    """One adjustment run at a time. demo=True: in-memory only (nothing persisted, nothing that could look like evidence)."""

    def __init__(self, demo=False, path=None):
        self.demo = bool(demo)
        self.path = ':memory:' if self.demo else str(path or default_path())
        self.con = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript(SCHEMA)
        cols = {r[1] for r in self.con.execute('PRAGMA table_info(adjustment_events)')}
        if 'source' not in cols:                                  # additive, lab_registry.sqlite3 only: where a value entered by the operator came from ('' for every older row)
            self.con.execute("ALTER TABLE adjustment_events ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        self.con.commit()
        self.run_id = None

    # ---- runs
    def start_run(self, instrument, asset, serial, technician, uut_idn='', firmware='', calibrator='', scope='') -> int:
        now = datetime.now().isoformat(timespec='seconds')
        cur = self.con.execute('INSERT INTO adjustment_runs(instrument,asset_id,serial,technician,uut_idn,firmware,calibrator,scope,demo,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               (instrument, asset, serial, technician, clean(uut_idn), firmware, clean(calibrator), scope, int(self.demo), now, now))
        self.con.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def set_status(self, status):
        if self.run_id is None:
            return
        self.con.execute('UPDATE adjustment_runs SET status=?, updated_at=? WHERE id=?', (status, datetime.now().isoformat(timespec='seconds'), self.run_id))
        self.con.commit()

    def status(self):
        if self.run_id is None:
            return None
        row = self.con.execute('SELECT status FROM adjustment_runs WHERE id=?', (self.run_id,)).fetchone()
        return row[0] if row else None

    # ---- events
    def log(self, action, outcome='', detail='', step_id='', source=''):
        """One audit line; returns (time, action, outcome, detail) as stored (what the window shows). Nothing happens without a run."""
        if self.run_id is None:
            return None
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        detail = clean(detail)
        self.con.execute('INSERT INTO adjustment_events(run_id,event_time,step_id,action,outcome,detail,source) VALUES(?,?,?,?,?,?,?)',
                         (self.run_id, now, step_id or '', action, outcome, detail, clean(source)))
        self.con.execute('UPDATE adjustment_runs SET updated_at=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'), self.run_id))
        self.con.commit()
        return (now, action, outcome, detail)

    def events(self, run_id=None):
        rid = run_id if run_id is not None else self.run_id
        return self.con.execute('SELECT event_time,step_id,action,outcome,detail FROM adjustment_events WHERE run_id=? ORDER BY id', (rid,)).fetchall()

    def sources(self, run_id=None):
        """(step_id, action, source) of every event that carries a source."""
        rid = run_id if run_id is not None else self.run_id
        return self.con.execute("SELECT step_id,action,source FROM adjustment_events WHERE run_id=? AND source<>'' ORDER BY id", (rid,)).fetchall()

    def close(self):
        try:
            self.con.close()
        except sqlite3.Error:
            pass
