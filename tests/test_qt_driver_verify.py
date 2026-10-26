"""File > Driver verification...: the window, driven against the simulated bench (no hardware)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.modules.setdefault('tkinter', None)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import driver_verify as V  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    from qtui import app
    from qtui.screens import driver_verify_window as W
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'lab_registry.sqlite3'
        self.logs = Path(self.tmp.name) / 'logs'
        self.w = W.DriverVerifyWindow(None, db=self.db, log_folder=self.logs)
        self.w.show()
        self.addCleanup(self.w.close)
        names = [c[0] for c in self.w.catalog]
        self.w.driver_box.setCurrentIndex(next(i for i, n in enumerate(names) if n.startswith('Fluke 5560A')))
        self.w.sim_cb.setChecked(True)

    def connect(self):
        self.w.connect_driver()
        self.assertIsNotNone(self.w.driver, self.w.state.text())

    def test_connect_lists_every_command_and_ticks_only_the_queries(self):
        self.connect()
        self.assertEqual(len(self.w.rows), len(self.w.plan))
        self.assertTrue(all(r.pick == (r.step.mode == 'query' and r.step.sendable) for r in self.w.rows))
        self.assertIn('SIMULATED', self.w.state.text())

    def test_running_the_ticked_queries_fills_results_without_any_confirmation(self):
        self.connect()
        with mock.patch.object(self.w, '_confirm_list', side_effect=AssertionError('no confirmation expected for queries')):
            self.w.run_ticked()
            self.w.wait()
        done = [r for r in self.w.rows if r.result is not None]
        self.assertEqual(len(done), sum(1 for r in self.w.rows if r.pick))
        self.assertIn('SIMULATED - NOT EVIDENCE', self.w.findings.toPlainText())

    def test_set_commands_need_the_confirmation_and_cancel_sends_nothing(self):
        self.connect()
        self.w.tick('set')
        with mock.patch.object(self.w, '_confirm_list', return_value=False) as ask:
            self.w.run_ticked()
        self.assertTrue(ask.called)
        self.assertEqual([r for r in self.w.rows if r.result is not None], [])
        self.assertFalse(any(t.rstrip().endswith('OPER') for t in self.w.driver.log.lines()))

    def test_confirmed_sets_run_and_outputs_return_to_standby(self):
        self.connect()
        self.w.tick('set')
        with mock.patch.object(self.w, '_confirm_list', return_value=True):
            self.w.run_ticked()
            self.w.wait()
        by = {r.step.key: r for r in self.w.rows}
        self.assertIsNotNone(by['oper.on'].result)
        self.assertIn('standby', by['oper.on'].result.note)
        self.assertFalse(self.w.driver.is_operating())

    def test_a_simulated_run_cannot_be_saved_and_csv_is_marked(self):
        self.connect()
        self.w.run_ticked()
        self.w.wait()
        self.w.save_record()
        self.assertIn('cannot be saved', self.w.state.text())
        self.assertFalse(self.db.exists())
        out = Path(self.tmp.name) / 'x.csv'
        with mock.patch.object(self.w, '_csv_path', return_value=str(out)):
            self.w.export_csv()
        self.assertIn('SIMULATED - NOT EVIDENCE', out.read_text(encoding='utf-8-sig'))

    def test_a_check_can_be_settled_by_the_tester(self):
        self.connect()
        self.w.tick('set')
        with mock.patch.object(self.w, '_confirm_list', return_value=True):
            self.w.run_ticked()
            self.w.wait()
        row = next(r for r in self.w.rows if r.result is not None and r.result.status == 'check')
        self.w.table.select_rows([row]) if hasattr(self.w.table, 'select_rows') else None
        with mock.patch.object(self.w.table, 'selected_rows', return_value=[row]):
            self.w.settle(True)
        self.assertEqual(row.result.status, 'pass')
        self.assertTrue(row.result.confirmed_by_tester)

    def real_window(self):
        """A window whose transport is the simulator but which is NOT marked simulated (stands in for real hardware)."""
        from drivers.simulated import make_bench
        w = W.DriverVerifyWindow(None, db=self.db, log_folder=self.logs, transport_factory=lambda cls, addr, baud, sim: make_bench()[1])
        self.addCleanup(w.close)
        names = [c[0] for c in w.catalog]
        w.driver_box.setCurrentIndex(next(i for i, n in enumerate(names) if n.startswith('Fluke 5560A')))
        w.address_e.setText('ASRL9::INSTR')
        w.connect_driver()
        self.assertIsNotNone(w.driver, w.state.text())
        return w

    def test_a_simulated_run_leaves_no_log_files(self):
        self.connect()
        self.w.run_ticked()
        self.w.wait()
        self.assertFalse(self.logs.exists())

    def test_a_real_run_writes_a_transcript_and_csv_even_if_never_saved(self):
        w = self.real_window()
        w.run_ticked()
        w.wait()
        self.assertIsNotNone(w.run_files)
        txt, csv_ = w.run_files
        text = txt.read_text(encoding='utf-8')
        self.assertIn('passed', text)
        self.assertIn('--- command log ---', text)
        self.assertIn('*IDN?', text)
        self.assertTrue(csv_.exists())
        self.assertNotIn('SIMULATED', csv_.read_text(encoding='utf-8-sig'))

    def test_closing_saves_an_unsaved_real_run_and_the_status_tab_shows_it(self):
        w = self.real_window()
        w.run_ticked()
        w.wait()
        self.assertTrue(w.unsaved)
        self.assertEqual(V.load_runs('Fluke5560A', db=self.db), [])
        w.close()
        self.assertEqual(len(V.load_runs('Fluke5560A', db=self.db)), 1)
        w2 = W.DriverVerifyWindow(None, db=self.db, log_folder=self.logs)
        self.addCleanup(w2.close)
        w2.refresh_status()
        row = next(r for r in w2.status_rows if r['cls'] == 'Fluke5560A')
        self.assertGreater(row['passed'], 5)
        self.assertEqual(row['state'], 'partly tested')
        self.assertTrue(row['last_tested'])
        other = next(r for r in w2.status_rows if r['cls'] == 'TektronixMDO3')
        self.assertEqual((other['state'], other['passed']), ('not tested', 0))

    def test_the_last_on_bench_column_and_status_export(self):
        w = self.real_window()
        w.run_ticked()
        w.wait()
        w.save_record()
        row = next(r for r in w.rows if r.step.key == 'oper.query')
        self.assertTrue(w._bench_text(row).startswith('pass'))
        out = Path(self.tmp.name) / 'status.csv'
        with mock.patch.object(w, '_status_path', return_value=str(out)):
            w.export_status()
        text = out.read_text(encoding='utf-8-sig')
        self.assertIn('Fluke 5560A', text)
        self.assertIn('partly tested', text)

    def test_connecting_without_an_address_says_so(self):
        self.w.sim_cb.setChecked(False)
        self.w.connect_driver()
        self.assertIsNone(self.w.driver)
        self.assertIn('address', self.w.state.text())


if HAVE_QT:
    from tests.test_qt_manager import QtCase as _ManagerCase

    class FileMenu(_ManagerCase):
        def test_the_manager_file_menu_opens_the_tool(self):
            texts = [a.text() for a in self.win.file_menu.actions()]
            name = next(t for t in texts if 'Driver verification' in t)
            self.assertLess(texts.index(name), texts.index('E&xit'))
            w = self.win.driver_verification()
            self.addCleanup(w.close)
            self.assertTrue(w.isVisible())


if __name__ == '__main__':
    unittest.main()
