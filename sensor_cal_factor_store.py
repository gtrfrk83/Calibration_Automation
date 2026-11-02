"""Saved cal-factor tables of power sensors (by sensor model and serial), in lab_registry.sqlite3: NEW tables only; calibration_procedures.sqlite3 is not touched.

    store = SensorTableStore(demo=False)
    store.save('11722A', 'MY12345', 98.5, [(1.0, 99.0), (2000.0, 96.0)], 'Technician')
    store.load('11722A', 'MY12345')  ->  {'reference': 98.5, 'pairs': [(1.0, 99.0), ...], 'saved_at': '...', 'saved_by': '...'}

A DEMO store is in memory only: nothing it saves reaches the database.  One table per (sensor model, sensor serial); saving again replaces it.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sensor_cal_factor_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_model TEXT NOT NULL COLLATE NOCASE,
    sensor_serial TEXT NOT NULL COLLATE NOCASE,
    reference_pct REAL NOT NULL,
    saved_by TEXT NOT NULL DEFAULT '',
    saved_at TEXT NOT NULL,
    UNIQUE(sensor_model, sensor_serial)
);
CREATE TABLE IF NOT EXISTS sensor_cal_factor_pairs (
    table_id INTEGER NOT NULL REFERENCES sensor_cal_factor_tables(id) ON DELETE CASCADE,
    mhz REAL NOT NULL,
    pct REAL NOT NULL,
    PRIMARY KEY (table_id, mhz)
);
'''


class SensorTableStore:
    def __init__(self, demo=False, path=None):
        self.demo = bool(demo)
        if self.demo:
            self.path = ':memory:'
        else:
            import appdata
            self.path = str(path or appdata.db_path('lab_registry.sqlite3'))
        self.con = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript(SCHEMA)
        self.con.commit()

    def save(self, model, serial, reference, pairs, saved_by=''):
        model, serial = str(model).strip(), str(serial).strip()
        if not model or not serial:
            raise ValueError('Enter the sensor model and serial number first.')
        now = datetime.now().isoformat(timespec='seconds')
        with self.con:
            self.con.execute('DELETE FROM sensor_cal_factor_tables WHERE sensor_model=? AND sensor_serial=?', (model, serial))
            tid = self.con.execute('INSERT INTO sensor_cal_factor_tables(sensor_model,sensor_serial,reference_pct,saved_by,saved_at) VALUES(?,?,?,?,?)',
                                   (model, serial, float(reference), saved_by, now)).lastrowid
            self.con.executemany('INSERT INTO sensor_cal_factor_pairs(table_id,mhz,pct) VALUES(?,?,?)', [(tid, float(f), float(c)) for f, c in pairs])
        return tid

    def load(self, model, serial):
        row = self.con.execute('SELECT id,reference_pct,saved_by,saved_at FROM sensor_cal_factor_tables WHERE sensor_model=? AND sensor_serial=?',
                               (str(model).strip(), str(serial).strip())).fetchone()
        if row is None:
            return None
        pairs = self.con.execute('SELECT mhz,pct FROM sensor_cal_factor_pairs WHERE table_id=? ORDER BY mhz', (row[0],)).fetchall()
        return {'reference': row[1], 'pairs': [(f, c) for f, c in pairs], 'saved_by': row[2], 'saved_at': row[3]}

    def list(self):
        return self.con.execute('SELECT sensor_model,sensor_serial,saved_at FROM sensor_cal_factor_tables ORDER BY sensor_model,sensor_serial').fetchall()

    def close(self):
        try:
            self.con.close()
        except sqlite3.Error:
            pass
