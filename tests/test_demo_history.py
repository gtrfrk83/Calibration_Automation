"""Fictional demonstration Asset History (demo_history.py, Help > Show demonstration asset history, the banner on the Asset History tab).

Project rule under test: demo mode must never produce real-looking evidence.  So: the fake history lives in its OWN file (lab_registry_demo.sqlite3), the
real registry is never touched by generating or viewing it, nothing from it reaches next-due, find-existing, auto-fill, imports or the diagnostic log,
nothing can be written to it from the suite, and no PDF can be made from a demonstration event (the Regenerate PDF action is disabled with a plain reason
and every code path under it refuses as well).

File name sorts after test_beta on purpose (the tkinter stub).  Qt parts are skipped when PySide6 is missing.  Run:  python -m unittest tests.test_demo_history
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
_DATA = tempfile.mkdtemp(prefix='demo_history_data_')
_OLD_DATA = os.environ.get('CALSUITE_DATA')
os.environ['CALSUITE_DATA'] = _DATA                      # this process's data folder is a throw-away one

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

import _qt_test_support as support  # noqa: E402
support.force_tk_stub()
import reprint_harness as R  # noqa: E402  (installs the tkinter stub)
import appdata  # noqa: E402
import demo_history as dh  # noqa: E402
import diagnostics  # noqa: E402
import labregistry  # noqa: E402
import report_snapshot as rs  # noqa: E402

TODAY = date(2026, 10, 25)


def tearDownModule():
    if _OLD_DATA is None:
        os.environ.pop('CALSUITE_DATA', None)
    else:
        os.environ['CALSUITE_DATA'] = _OLD_DATA


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path):
    con = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
    try:
        return {t: con.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in ('runs', 'points', 'demo_marker', 'demo_assets')}
    finally:
        con.close()


REAL_HEADER = [('Instrument', 'Real DMM'), ('Instrument ID', 'A-7'), ('Serial', 'SN7')]
REAL_ROWS = [{'Section': 'DCV', 'Description': '10 V', 'Nominal': '10.000', 'Tolerance -': '9.990', 'Tolerance +': '10.010', 'UOM': 'V', 'As Found': '10.002', 'OOT': ''}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.real = self.dir / 'lab_registry.sqlite3'
        self.demo = self.dir / dh.DEMO_DB_NAME
        patches = [mock.patch.object(labregistry, 'DB', self.real), mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.dir)})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def real_event(self):
        return labregistry.record_run(REAL_HEADER, REAL_ROWS, {'technician': 'A. Real', 'procedure': 'real proc'}, report_file=str(self.dir / 'real.pdf'),
                                      when=datetime(2026, 3, 3, 10, 0))


class Generated(Base):
    def setUp(self):
        super().setUp()
        dh.generate(self.demo, today=TODAY)

    def test_twelve_fictional_assets_with_two_to_five_events_in_three_years(self):
        over = labregistry.assets_overview('', db=self.demo)
        self.assertEqual(len(over), 12)
        for r in over:
            self.assertTrue(r['asset_id'].startswith('DEMO-'), r)
            self.assertTrue(r['serial'].startswith('DEMO-SN-'), r)
            runs = labregistry.runs_for(r['asset_id'], db=self.demo)
            self.assertTrue(2 <= len(runs) <= 5, (r['asset_id'], len(runs)))
            for run in runs:
                self.assertEqual(run['technician'], 'Demo Technician')
                self.assertTrue(run['report_file'].startswith(r['asset_id']) and run['report_file'].endswith('-DEMO.pdf'))
                d = datetime.fromisoformat(run['run_at']).date()
                self.assertLess(d, TODAY)
                self.assertLessEqual((TODAY - d).days, 3 * 366)
                pts = labregistry.points_for(run['id'], db=self.demo)
                self.assertEqual(len(pts), run['total'])
                self.assertEqual(sum(p['result'] == 'FAIL' for p in pts), run['failed'])
                for p in pts:
                    self.assertTrue(p['low'] and p['high'] and p['found'] and p['nominal'])
                    self.assertLessEqual(float(p['low']), float(p['nominal']))
                    self.assertGreaterEqual(float(p['high']), float(p['nominal']))
                    if p['result'] == 'PASS':
                        self.assertTrue(float(p['low']) <= float(p['found']) <= float(p['high']), p)
                    else:
                        self.assertFalse(float(p['low']) <= float(p['found']) <= float(p['high']), p)

    def test_instrument_types_failures_drift_overdue_and_due_soon(self):
        models = {r['model'] for r in labregistry.assets_overview('', db=self.demo)}
        self.assertTrue({'Fluke 87V', 'Fluke 8846A', 'Keysight 34401A', 'Keysight 33220A', 'Tektronix TDS2000C', 'Tektronix MDO4000C'} <= models)
        over = labregistry.assets_overview('', db=self.demo)
        self.assertGreaterEqual(sum(1 for r in over if r['failed']), 2, 'one or two latest reports with an out-of-tolerance point')
        fails = [p for r in over for run in labregistry.runs_for(r['asset_id'], db=self.demo) for p in labregistry.points_for(run['id'], db=self.demo) if p['result'] == 'FAIL']
        self.assertTrue(2 <= len(fails) <= 4, len(fails))
        due = {r['asset_id']: labregistry.next_due(r['asset_id'], db=self.demo)[0] for r in over}
        overdue = [a for a, d in due.items() if d < TODAY]
        soon = [a for a, d in due.items() if 0 <= (d - TODAY).days <= 30]
        self.assertEqual(overdue, ['DEMO-0003'])
        self.assertEqual(soon, ['DEMO-0002'])
        # a slow drift is visible in the drift view: the 10 V DC point of DEMO-0002 climbs report after report
        pct = [v for _d, _f, v in labregistry.drift('DEMO-0002', 'DC Voltage', '10 V DC', db=self.demo)]
        self.assertEqual(len(pct), 3)
        self.assertTrue(pct[0] < pct[1] < pct[2] < 100, pct)

    def test_deterministic_and_same_tables_as_the_real_registry(self):
        other = self.dir / 'again' / dh.DEMO_DB_NAME
        dh.generate(other, today=TODAY)
        self.assertEqual(dump(self.demo), dump(other))
        con = sqlite3.connect(f'file:{self.demo.as_posix()}?mode=ro', uri=True)
        ref = sqlite3.connect(':memory:')
        ref.executescript(labregistry.SCHEMA)
        for table in ('runs', 'points'):
            self.assertEqual(con.execute(f'PRAGMA table_info({table})').fetchall(), ref.execute(f'PRAGMA table_info({table})').fetchall())
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('report_snapshots', names, 'no snapshot, so nothing can be reprinted')
        self.assertEqual(con.execute("SELECT COUNT(*) FROM runs WHERE standards_json<>'[]'").fetchone()[0], 0, 'no calibrator serials are invented')
        con.close()
        ref.close()
        self.assertEqual(dh.verify(self.demo), (True, ''))

    def test_dates_follow_today_so_overdue_stays_true(self):
        later = self.dir / 'later' / dh.DEMO_DB_NAME
        dh.generate(later, today=date(2027, 6, 1))
        self.assertEqual(dh.anchor_of(later), '2027-06-01')
        newest = max(r['last'] for r in labregistry.assets_overview('', db=later))
        self.assertLess(newest[:10], '2027-06-01')
        with mock.patch.object(dh, 'demo_path', lambda: self.demo):
            self.assertEqual(dh.ensure(today=TODAY), self.demo)
            stamp = digest(self.demo)
            self.assertEqual(dh.ensure(today=TODAY), self.demo)
            self.assertEqual(digest(self.demo), stamp, 'an up-to-date file is not rewritten')
            dh.ensure(today=date(2027, 6, 1))
            self.assertEqual(dh.anchor_of(self.demo), '2027-06-01')

    def test_generate_only_writes_the_demo_file(self):
        with self.assertRaises(ValueError):
            dh.generate(self.dir / 'lab_registry.sqlite3', today=TODAY)
        with self.assertRaises(ValueError):
            dh.generate(self.dir / 'other.sqlite3', today=TODAY)
        self.assertFalse(self.real.exists())

    def test_a_damaged_or_foreign_file_is_not_shown(self):
        self.demo.write_bytes(b'not a database')
        self.assertFalse(dh.verify(self.demo)[0])
        self.assertEqual(dh.generate(self.demo, today=TODAY), self.demo)          # a file that fails its checks is simply rebuilt
        con = sqlite3.connect(str(self.demo))
        con.execute("UPDATE runs SET asset_id='A-7' WHERE id=1")
        con.commit()
        con.close()
        ok, why = dh.verify(self.demo)
        self.assertFalse(ok)
        self.assertIn('not a demonstration event', why)


class RealRegistryIsUntouched(Base):
    def test_generating_and_reading_the_demo_never_changes_the_real_registry(self):
        self.real_event()
        before = digest(self.real)
        dh.generate(self.demo, today=TODAY)
        for r in labregistry.assets_overview('', db=self.demo):
            labregistry.runs_for(r['asset_id'], db=self.demo)
            labregistry.next_due(r['asset_id'], db=self.demo)
        self.assertEqual(digest(self.real), before)

    def test_demo_events_do_not_appear_anywhere_in_the_real_history(self):
        self.real_event()
        dh.generate(self.demo, today=TODAY)
        self.assertEqual([r['asset_id'] for r in labregistry.assets_overview('')], ['A-7'])
        self.assertEqual(labregistry.assets_overview('DEMO'), [])
        self.assertEqual(labregistry.runs_for('DEMO-0001'), [])
        self.assertEqual(labregistry.next_due('DEMO-0003'), (None, None))                   # next-due lists
        self.assertEqual(labregistry.asset_summary('DEMO-0003'), '')                         # the procedures' Instrument ID hint
        self.assertIsNone(labregistry.instrument_record('DEMO-0001'))                        # find-existing / serial auto-fill
        self.assertEqual(labregistry.drift('DEMO-0002', 'DC Voltage', '10 V DC'), [])
        con = sqlite3.connect(str(self.real))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM runs WHERE asset_id LIKE 'DEMO%'").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '%demo%'").fetchone()[0], 0)
        con.close()

    def test_run_queue_suggestions_come_from_the_real_history_only(self):
        import run_queue_engine
        dh.generate(self.demo, today=TODAY)
        fake = mock.MagicMock()
        fake.info = {'name': 'Fluke 87V'}
        fake.model = '87V'
        self.assertEqual(run_queue_engine.QueueMixin.queue_candidates(fake), [])
        labregistry.record_run([('Instrument', 'Fluke 87V'), ('Instrument ID', 'A-7'), ('Serial', 'SN7')], REAL_ROWS, {}, when=datetime(2026, 3, 3, 10, 0))
        self.assertEqual(run_queue_engine.QueueMixin.queue_candidates(fake), [('A-7', 'SN7')])

    def test_not_imported_not_logged(self):
        dh.generate(self.demo, today=TODAY)
        self.assertNotIn(dh.DEMO_DB_NAME, appdata.DB_NAMES)
        src = self.dir / 'src'
        src.mkdir()
        (src / 'lab_registry.sqlite3').write_bytes(b'x')
        (src / dh.DEMO_DB_NAME).write_bytes(self.demo.read_bytes())
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.dir / 'dest')}):
            self.assertEqual(appdata.import_from(src), ['lab_registry.sqlite3'])
        log = diagnostics.write_log('x', 'test').read_text(encoding='utf-8')
        self.assertNotIn('DEMO-', log)
        self.assertNotIn('demonstration', log.lower())


class NothingCanBeWritten(Base):
    def setUp(self):
        super().setUp()
        dh.generate(self.demo, today=TODAY)
        self.stamp = digest(self.demo)

    def test_the_demo_file_opens_read_only(self):
        with labregistry._db(self.demo) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO demo_marker VALUES('x','y')")
        self.assertEqual(digest(self.demo), self.stamp)

    def test_a_run_can_not_record_into_the_demo_file_even_if_it_were_the_registry(self):
        with mock.patch.object(labregistry, 'DB', self.demo):
            self.assertIsNone(labregistry.record_run(REAL_HEADER, REAL_ROWS, {'technician': 'x'}, report_file=str(self.dir / 'r.pdf')))
        self.assertEqual(digest(self.demo), self.stamp)

    def test_snapshots_are_never_saved_into_or_read_from_the_demo_file(self):
        self.assertFalse(rs.record_issued(1, header=REAL_HEADER, rows=REAL_ROWS, details={}, issued_at='2026-01-01 10:00', db_path=self.demo))
        self.assertEqual(rs.load(1, self.demo).status, rs.DAMAGED)
        self.assertEqual(digest(self.demo), self.stamp)

    def test_the_real_registry_is_not_created_by_viewing_demo_data(self):
        for r in labregistry.assets_overview('', db=self.demo):
            labregistry.runs_for(r['asset_id'], db=self.demo)
        self.assertFalse(self.real.exists())


class NoPdfFromADemoEvent(Base):
    def setUp(self):
        super().setUp()
        dh.generate(self.demo, today=TODAY)
        self.rid = labregistry.runs_for('DEMO-0001', db=self.demo)[0]['id']
        self.stamp = digest(self.demo)

    def test_plan_regenerate_and_rebuild_all_refuse(self):
        self.assertEqual(rs.plan(self.rid, self.demo).kind, rs.NONE)
        self.assertEqual(rs.availability(self.rid, self.demo)[0], rs.NONE)
        asked = []
        out = self.dir / 'x.pdf'
        res = rs.regenerate(self.rid, choose_path=lambda *a: asked.append(a) or out, confirm_overwrite=lambda *a: True,
                            confirm_rebuilt=lambda m: asked.append(m) or True, db_path=self.demo)
        self.assertFalse(res.ok)
        self.assertIn('never turned into a PDF', res.message)
        self.assertEqual(asked, [], 'nothing was even asked')
        self.assertFalse(out.exists())
        self.assertEqual(rs.rebuild_from_history(self.rid, self.demo)[0], None)
        self.assertEqual(sorted(p.name for p in self.dir.glob('*.pdf')), [])
        with self.assertRaises(Exception):
            rs.write_report({'demo': True, 'details': {}, 'rows': [], 'header': [], 'title': 'x', 'issued_at': ''}, out, rs.REBUILT)
        self.assertEqual(digest(self.demo), self.stamp)

    def test_a_real_event_in_the_real_registry_still_has_its_plan(self):
        self.real_event = labregistry.record_run(REAL_HEADER, REAL_ROWS, {'technician': 'A. Real', 'procedure': 'p'}, when=datetime(2026, 3, 3, 10, 0))
        self.assertEqual(rs.plan(self.real_event).kind, rs.REBUILT, 'the real registry keeps its behaviour')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Screen(Base):
    @classmethod
    def setUpClass(cls):
        from qtui import app
        cls.app = app.create_app()

    def pump(self, n=4):
        for _ in range(n):
            self.app.processEvents()

    def window(self, **kw):
        import manager_model as mm
        import verified as V
        from qtui.screens.manager import ManagerWindow
        t = self.dir / 'mgr'
        t.mkdir(exist_ok=True)
        core = mm.ManagerCore(db=t / 'procedures.sqlite3', registry=V.Registry(t / 'verified.sqlite3', seed=False))
        win = ManagerWindow(core, launcher=lambda *a, **k: None)
        win.resize(1300, 820)
        win.show()
        self.addCleanup(lambda: (win.close(), win.deleteLater(), self.pump()))
        self.pump()
        self.dialogs = []
        from qtui.screens import asset_history as AH
        for name in ('_info', '_error'):
            p = mock.patch.object(AH, name, lambda parent, title, text, _n=name: self.dialogs.append((_n, title, text)))
            p.start()
            self.addCleanup(p.stop)
        win.select_tab('asset_history')
        self.pump()
        return win

    def test_off_at_start_banner_hidden_real_history_shown(self):
        self.real_event()
        win = self.window()
        act = win.help_actions['demo_history']
        self.assertEqual(act.text(), 'Show demonstration asset history')
        self.assertTrue(act.isCheckable())
        self.assertFalse(act.isChecked())
        p = win.history_panel
        self.assertTrue(p.banner.isHidden())
        self.assertEqual([r['asset_id'] for r in p.assets.rows()], ['A-7'])
        self.assertFalse(self.demo.exists(), 'the demo file is only made when asked for')

    def test_switch_on_shows_banner_demo_rows_only_and_off_restores_the_real_history(self):
        self.real_event()
        win = self.window()
        real_stamp = digest(self.real)                                  # after the window is built (other panels create their own tables at start-up)
        act = win.help_actions['demo_history']
        act.setChecked(True)
        self.pump()
        p = win.history_panel
        self.assertTrue(p.demo)
        self.assertFalse(p.banner.isHidden())
        self.assertIn('DEMONSTRATION DATA: fictional assets, not real calibration records', p.banner.text_label.text())
        self.assertEqual(p.banner._kind, 'warn')
        ids = [r['asset_id'] for r in p.assets.rows()]
        self.assertEqual(len(ids), 12)
        self.assertTrue(all(i.startswith('DEMO-') for i in ids))
        self.assertEqual(win.tabs.currentIndex(), 1)
        for row in p.assets.rows():                                     # every row on every table belongs to a demo asset
            p.assets.select_rows([row])
            self.pump()
            self.assertTrue(p.runs.rows())
            for run in p.runs.rows():
                self.assertTrue(run['asset_id'].startswith('DEMO-'))
                self.assertEqual(run['tech'], 'Demo Technician')
        self.assertIn('fictional', p.note.text())
        # the check stays on when the person moves between tabs
        win.select_tab('procedures')
        win.select_tab('asset_history')
        self.pump()
        self.assertTrue(act.isChecked())
        self.assertFalse(p.banner.isHidden())
        # off: the real history is back, the banner is gone
        act.setChecked(False)
        self.pump()
        self.assertFalse(p.demo)
        self.assertTrue(p.banner.isHidden())
        self.assertEqual([r['asset_id'] for r in p.assets.rows()], ['A-7'])
        self.assertEqual(digest(self.real), real_stamp, 'the real registry is byte-for-byte what it was')

    def test_not_remembered_a_new_window_starts_on_the_real_history(self):
        win = self.window()
        win.help_actions['demo_history'].setChecked(True)
        self.pump()
        win.close()
        win2 = self.window()
        self.assertFalse(win2.help_actions['demo_history'].isChecked())
        self.assertTrue(win2.history_panel.banner.isHidden())
        self.assertFalse(win2.history_panel.demo)
        for path in self.dir.rglob('*'):                                # no settings file mentions it
            if path.is_file() and path.suffix in ('.json', '.ini', '.txt'):
                self.assertNotIn('demonstration', path.read_text(errors='ignore').lower(), path)

    def test_regenerate_is_disabled_and_every_route_says_why(self):
        win = self.window()
        win.help_actions['demo_history'].setChecked(True)
        self.pump()
        p = win.history_panel
        p.assets.select_rows([p.assets.rows()[0]])
        self.pump()
        self.assertFalse(p.btn_regen.isEnabled())
        self.assertFalse(p.btn_open.isEnabled())
        self.assertFalse(p.act_regen.isEnabled())
        self.assertIn('never made into a PDF', p.regen_note.text())
        from qtui.screens import asset_history as AH
        with mock.patch.object(AH, '_save_file', side_effect=AssertionError('no save dialog for a demonstration event')), \
                mock.patch.object(rs, 'write_report', side_effect=AssertionError('no PDF')):
            p.regenerate_pdf()
            p._runs_double(p.runs.rows()[0])
            p.open_report()
        self.assertEqual([d[0] for d in self.dialogs], ['_info', '_info', '_info'])
        self.assertIn('never turned into a PDF', self.dialogs[0][2])
        self.assertEqual(sorted(p.name for p in self.dir.rglob('*.pdf')), [])
        win.help_actions['demo_history'].setChecked(False)
        self.pump()
        self.assertTrue(p.btn_regen.isEnabled() and p.btn_open.isEnabled(), 'real history gets its buttons back')

    def test_drift_view_reads_the_demo_file_and_says_so(self):
        win = self.window()
        win.help_actions['demo_history'].setChecked(True)
        self.pump()
        p = win.history_panel
        p.assets.select_rows([r for r in p.assets.rows() if r['asset_id'] == 'DEMO-0002'])
        self.pump()
        p.points.select_rows([r for r in p.points.rows() if r['description'] == '10 V DC'])
        seen = {}
        from qtui.screens import asset_history as AH

        def fake_run(dlg):
            seen['title'] = dlg.windowTitle()
            seen['sub'] = dlg.sub_label.text()
            seen['points'] = len(dlg.chart.points)
            return 'x'
        with mock.patch.object(AH.ModalDialog, 'run', fake_run):
            p.show_drift()
        self.assertIn('DEMONSTRATION DATA', seen['title'])
        self.assertIn('DEMONSTRATION DATA', seen['sub'])
        self.assertEqual(seen['points'], 3)

    def test_a_demo_file_that_fails_its_checks_leaves_the_real_history_showing(self):
        self.real_event()
        win = self.window()
        with mock.patch.object(dh, 'ensure', lambda *a, **k: None):
            win.help_actions['demo_history'].setChecked(True)
            self.pump()
        p = win.history_panel
        self.assertFalse(p.demo)
        self.assertFalse(win.help_actions['demo_history'].isChecked(), 'the Help item agrees with what is shown')
        self.assertTrue(p.banner.isHidden())
        self.assertEqual([r['asset_id'] for r in p.assets.rows()], ['A-7'])
        self.assertEqual(self.dialogs[0][0], '_error')

    def test_other_windows_do_not_get_the_item(self):
        from PySide6.QtWidgets import QMainWindow
        from qtui.screens import help_menu
        w = QMainWindow()
        self.addCleanup(w.deleteLater)
        help_menu.add_help_menu(w)
        self.assertNotIn('demo_history', w.help_actions)


if __name__ == '__main__':
    unittest.main()
