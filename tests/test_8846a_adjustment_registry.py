"""Fluke 8846A guided adjustment: its audit history lives in lab_registry.sqlite3; calibration_procedures.sqlite3 is never written (standing rule)."""
import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import _tk_stub  # noqa: E402
_tk_stub.install()


def load_launcher():
    spec = importlib.util.spec_from_file_location('adj8846a_under_test', ROOT / 'Procedures' / 'Fluke_8846A_Adjustment.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Var:
    def __init__(self, v): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v


class Table:
    def delete(self, *a): pass
    def get_children(self): return ()
    def insert(self, *a, **k): pass


def make_old(path):
    con = sqlite3.connect(path)
    con.executescript('''
    CREATE TABLE instruments(id INTEGER PRIMARY KEY, name TEXT);
    INSERT INTO instruments VALUES(1,'x');
    CREATE TABLE adjustment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, serial_number TEXT NOT NULL,
        technician TEXT NOT NULL, meter_idn TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE adjustment_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES adjustment_runs(id),
        event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, step_index INTEGER, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '');
    INSERT INTO adjustment_runs VALUES(1,'A1','S1','Tech','IDN1','ADJUSTED_NOT_VERIFIED','2026-01-01 10:00:00','2026-01-01 11:00:00');
    INSERT INTO adjustment_runs VALUES(2,'A2','S2','Tech','IDN2','IN_PROGRESS','2026-02-01 10:00:00','2026-02-01 10:05:00');
    INSERT INTO adjustment_events VALUES(1,1,'2026-01-01 10:00:01',NULL,'RUN_STARTED','d','OK');
    INSERT INTO adjustment_events VALUES(2,1,'2026-01-01 10:30:00',3,'STEP','d2','CONFIRMED');
    INSERT INTO adjustment_events VALUES(3,2,'2026-02-01 10:00:01',NULL,'RUN_STARTED','d','OK');
    ''')
    con.commit()
    con.close()


class Registry8846A(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.old = self.dir / 'calibration_procedures.sqlite3'
        self.reg = self.dir / 'lab_registry.sqlite3'
        make_old(self.old)
        self.mod = load_launcher()

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, db, table):
        con = sqlite3.connect(db)
        try:
            return con.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
        finally:
            con.close()

    def test_migration_copies_old_rows_exactly_once(self):
        old_runs = self.rows(self.old, 'adjustment_runs')
        old_events = self.rows(self.old, 'adjustment_events')
        for _ in range(3):                      # repeated opens never duplicate
            self.mod.connect_db(self.reg, self.old).close()
        self.assertEqual(self.rows(self.reg, self.mod.RUNS), old_runs)
        self.assertEqual(self.rows(self.reg, self.mod.EVENTS), old_events)
        self.assertEqual(self.rows(self.reg, self.mod.MIGRATION)[0][:3], ('calibration_procedures.sqlite3', 2, 3))

    def test_migration_never_touches_the_old_file(self):
        before = sha(self.old)
        self.mod.connect_db(self.reg, self.old).close()
        self.assertEqual(sha(self.old), before)

    def test_no_old_file_or_no_old_tables_is_fine(self):
        self.mod.connect_db(self.dir / 'a.sqlite3', self.dir / 'missing.sqlite3').close()
        other = self.dir / 'other.sqlite3'
        sqlite3.connect(other).close()
        self.mod.connect_db(self.dir / 'b.sqlite3', other).close()
        self.assertEqual(self.rows(self.dir / 'b.sqlite3', self.mod.RUNS), [])

    def test_simulated_run_writes_only_to_the_registry(self):
        before = sha(self.old)
        mod = self.mod
        app = mod.App.__new__(mod.App)
        app.demo, app.meter, app.run_id, app.committed = True, None, None, False
        app.asset, app.serial, app.tech = Var('A9'), Var('S9'), Var('Tech')
        app.status, app.log_table = Var(''), Table()
        app.reset_meter = lambda: True
        app._sync = lambda: None
        app.conn = mod.connect_db(self.reg, self.old)
        import ui_port_tk       # the launcher's dialogs go through the UI port now (Tk implementation shows them with tkinter.messagebox)
        with mock.patch.object(ui_port_tk.messagebox, 'askyesno', return_value=True), mock.patch.object(ui_port_tk.messagebox, 'showwarning'):
            app.start()
            app.log('STEP', 'simulated', 'DEMO', 3)
        app.conn.close()
        self.assertEqual(sha(self.old), before)
        runs = self.rows(self.reg, mod.RUNS)
        self.assertEqual([r[1] for r in runs], ['A1', 'A2', 'A9'])
        self.assertEqual(runs[-1][0], 3)
        self.assertEqual([r[4] for r in self.rows(self.reg, mod.EVENTS) if r[1] == 3], ['RUN_STARTED', 'STEP'])
        self.assertEqual(len(self.rows(self.old, 'adjustment_runs')), 2)       # old tables unchanged

    def test_launcher_has_no_write_path_to_the_old_file(self):
        src = (ROOT / 'Procedures' / 'Fluke_8846A_Adjustment.py').read_text(encoding='utf-8')
        self.assertNotIn("DB = BASE", src)
        self.assertNotIn('INTO adjustment_runs(', src)
        self.assertNotIn('INTO adjustment_events(', src)


if __name__ == '__main__':
    unittest.main()
