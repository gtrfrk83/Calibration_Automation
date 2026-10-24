"""Qt Asset History tab (qtui/screens/asset_history.py): the twin of labregistry_ui.HistoryPanel, checked against the same behaviours as
tests/test_reprint_ui.py (which only had the Tk wiring under a stub): the tables, the selection chain, the questions 'Regenerate PDF...' asks in order,
the messages, double-click / context menu, the hint line, Open report PDF, the drift chart; and the end-to-end part the Tk test could not do: regenerating
from the panel gives a PDF identical to the original.

Skipped when PySide6 (or reportlab / pypdf / pdftotext) is missing.  Run (venv with PySide6):  python -m unittest tests.test_qt_history
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import _qt_test_support as support  # noqa: E402
    support.force_tk_stub()
    import reprint_harness as R  # noqa: E402  (installs the tkinter stub)
    import test_reprint_snapshot as S  # noqa: E402  (issue() / HEADER helpers)
    import labregistry  # noqa: E402
    from PySide6.QtCore import QPoint, Qt  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402
    from qtui.screens import asset_history as AH  # noqa: E402
    HAVE = S.HAVE

    get_app = support.get_app
else:
    HAVE = False


def pump(n=4):
    for _ in range(n):
        QApplication.processEvents()


class Boxes:
    """Records every question / message / file dialog of the panel and answers them (the Tk test patched messagebox / filedialog the same way)."""

    def __init__(self, save=None, yes=True, ok=True):
        self.calls, self.save, self.yes, self.ok = [], save, yes, ok

    def install(self, test):
        patches = {'_info': lambda parent, title, text: self.calls.append(('info', (title, text), {})),
                   '_error': lambda parent, title, text: self.calls.append(('error', (title, text), {})),
                   '_ask_yes_no': lambda parent, title, text, default_no=True: self.calls.append(('askyesno', (title, text), {'default': 'no' if default_no else 'yes'})) or self.yes,
                   '_ask_ok_cancel': lambda parent, title, text: self.calls.append(('askokcancel', (title, text), {})) or self.ok,
                   '_save_file': lambda parent, title, initial_dir, initial_file, flt, default_ext='.pdf': self.calls.append(
                       ('save', (title,), {'initialdir': initial_dir, 'initialfile': initial_file, 'filter': flt})) or self.save}
        for name, fn in patches.items():
            p = mock.patch.object(AH, name, fn)
            p.start()
            test.addCleanup(p.stop)

    def kinds(self):
        return [c[0] for c in self.calls]

    def info_text(self):
        return ' '.join(str(c[1][1]) for c in self.calls if c[0] == 'info')


@unittest.skipUnless(HAVE_QT and HAVE, 'PySide6, reportlab and pypdf are needed')
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        S.issue(self.dir / 'orig.pdf')
        self.rid = labregistry.runs_for('A-7')[0]['id']
        self.boxes = Boxes()
        self.boxes.install(self)

    def panel(self, select=True):
        p = AH.AssetHistoryPanel(None)
        self.addCleanup(p.deleteLater)
        p.show()
        p.resize(1300, 800)
        pump()
        if select:
            self.select(p)
        return p

    def select(self, p, asset='A-7'):
        p.assets.select_rows([r for r in p.assets.rows() if r['asset_id'] == asset])
        pump()
        return p

    def edit(self, sql):
        con = sqlite3.connect(str(self.db))
        con.execute(sql)
        con.commit()
        con.close()


class Construction(Base):
    def test_the_three_tables_the_buttons_and_the_note(self):
        p = self.panel(select=False)
        self.assertEqual([c.title for c in p.assets.source_model.columns], ['Instrument ID', 'Instrument', 'Serial number', 'Reports', 'Last report', 'Last result', 'Next due'])
        self.assertEqual([c.title for c in p.runs.source_model.columns], ['Report date', 'Procedure', 'Technician', 'Points', 'Out of tol.', 'Report file'])
        self.assertEqual([c.title for c in p.points.source_model.columns],
                         ['Section', 'Test point', 'Nominal', 'Low limit', 'High limit', 'As found', 'Units', 'Result', '% of tol.'])
        self.assertEqual([b.text() for b in (p.btn_drift, p.btn_open, p.btn_regen)], ['Drift of selected point...', 'Open report PDF', 'Regenerate PDF...'])
        self.assertEqual([a.text() for a in p.menu.actions()], ['Regenerate PDF...', 'Open report PDF'])
        self.assertEqual(p.note.text(), '1 instrument(s) with reports on this computer.')
        self.assertEqual(p.assets.row_count(), (1, 1))
        row = p.assets.rows()[0]
        self.assertEqual((row['asset_id'], row['model'], row['serial'], row['runs'], row['result']), ('A-7', 'Test DMM', 'SN7', 1, 'OUT OF TOLERANCE'))
        self.assertRegex(row['last'], r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(p.runs.row_count(), (0, 0), 'nothing is selected until an instrument is chosen (as in Tk)')

    def test_empty_history_says_how_it_fills(self):
        self.edit('DELETE FROM runs')
        p = self.panel(select=False)
        self.assertEqual(p.note.text(), 'No reports recorded yet: history is added each time a PDF report is exported.')

    def test_selection_chain_runs_points_and_the_hint_line(self):
        p = self.panel()
        self.assertEqual(p._asset(), 'A-7')
        self.assertEqual(p.runs.row_count(), (1, 1))
        r = p.runs.rows()[0]
        self.assertRegex(r['date'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
        self.assertEqual((r['procedure'], r['tech'], r['points'], r['failed'], r['file']), ('bench test', 'T. Tech', 3, 1, 'orig.pdf'))
        self.assertEqual(p._selected_run_id(), self.rid, 'the newest report is selected by itself')
        self.assertEqual([x['description'] for x in p.points.rows()], ['10 V range', '100 V range', '1 kOhm'])
        fail = p.points.rows()[1]
        self.assertEqual((fail['result'], fail['pct']), ('FAIL', '+200%'))
        self.assertIn('Saved report record found', p.regen_note.text())

    def test_search_filters_the_instruments_and_refresh_keeps_the_selection(self):
        S.issue(self.dir / 'o2.pdf', header=[('Instrument', 'Other DMM'), ('Instrument ID', 'A-8'), ('Serial', 'SN8'), ('Source', 'x')])
        p = self.panel(select=False)
        self.assertEqual(p.assets.row_count(), (2, 2))
        self.select(p, 'A-8')
        p.term.setText('SN7')
        p.term.flush()
        pump()
        self.assertEqual([r['asset_id'] for r in p.assets.rows()], ['A-7'])
        self.assertEqual(p.runs.row_count(), (0, 0), 'the selected instrument is gone from the list: its reports go too')
        p.term.setText('')
        p.term.flush()
        pump()
        self.assertEqual(p.assets.row_count(), (2, 2))
        self.select(p, 'A-8')
        p.btn_refresh.click()
        pump()
        self.assertEqual(p._asset(), 'A-8')
        self.assertEqual(p.runs.row_count(), (1, 1))

    def test_hint_line_tells_whether_the_event_can_be_regenerated(self):
        p = self.panel()
        p._show_regen_hint(self.rid)
        self.assertIn('Saved report record found', p.regen_note.text())
        self.edit('DELETE FROM report_snapshots')
        p._show_regen_hint(self.rid)
        self.assertIn('can be rebuilt from history rows, not identical', p.regen_note.text())
        p._show_regen_hint(None)
        self.assertEqual(p.regen_note.text(), '')
        with mock.patch.object(AH.snap, 'availability', side_effect=RuntimeError('x')):
            p._show_regen_hint(self.rid)
        self.assertEqual(p.regen_note.text(), '', 'a failure never reaches the user as an error window')


class Regenerate(Base):
    def test_regenerate_asks_where_to_save_and_reports_the_new_file(self):
        out = self.dir / 'again.pdf'
        self.boxes.save = str(out)
        self.panel().regenerate_pdf()
        save = next(c for c in self.boxes.calls if c[0] == 'save')
        self.assertEqual(save[1], ('Save regenerated report',))
        self.assertEqual(save[2]['initialfile'], 'A-7-01-02-2026.pdf')
        self.assertEqual(save[2]['initialdir'], str(self.dir))
        self.assertEqual(save[2]['filter'], 'PDF report (*.pdf)')
        self.assertTrue(out.read_bytes().startswith(b'%PDF'))
        self.assertIn('Regenerated from the saved record', self.boxes.info_text())

    def test_regenerated_pdf_is_identical_to_the_original(self):
        out = self.dir / 'again.pdf'
        self.boxes.save = str(out)
        self.panel().regenerate_pdf()
        self.assertEqual(R.differences(self.dir / 'orig.pdf', out, None), [])
        self.assertEqual(R.pdf_text(self.dir / 'orig.pdf'), R.pdf_text(out))

    def test_nothing_selected(self):
        self.panel(select=False).regenerate_pdf()
        self.assertEqual(self.boxes.kinds(), ['info'])
        self.assertEqual(self.boxes.calls[0][1], ('Regenerate PDF', 'Select a report in the middle table first.'))

    def test_cancelled_save_dialog_is_silent(self):
        self.boxes.save = ''
        self.panel().regenerate_pdf()
        self.assertEqual(self.boxes.kinds(), ['save'])

    def test_existing_file_asks_and_declining_keeps_it(self):
        there = self.dir / 'there.pdf'
        there.write_bytes(b'precious')
        self.boxes.save, self.boxes.yes = str(there), False
        self.panel().regenerate_pdf()
        ask = next(c for c in self.boxes.calls if c[0] == 'askyesno')
        self.assertEqual(ask[2]['default'], 'no')
        self.assertEqual(ask[1][0], 'Replace file?')
        self.assertEqual(there.read_bytes(), b'precious')
        self.boxes.save, self.boxes.yes = str(there), True
        self.panel().regenerate_pdf()
        self.assertTrue(there.read_bytes().startswith(b'%PDF'))

    def test_replacing_the_original_file_says_so(self):
        self.boxes.save, self.boxes.yes = str(self.dir / 'orig.pdf'), False
        self.panel().regenerate_pdf()
        self.assertIn('original report was saved to', next(c for c in self.boxes.calls if c[0] == 'askyesno')[1][1])

    def test_missing_snapshot_and_incomplete_history_show_the_plain_message(self):
        self.edit('DELETE FROM report_snapshots')
        self.edit('DELETE FROM points WHERE rowid=(SELECT MAX(rowid) FROM points)')
        self.boxes.save = str(self.dir / 'x.pdf')
        self.panel().regenerate_pdf()
        self.assertIn('no saved report record', self.boxes.info_text())
        self.assertIn('Only 2 of the 3 points', self.boxes.info_text())
        self.assertNotIn('save', self.boxes.kinds())
        self.assertFalse((self.dir / 'x.pdf').exists())

    def test_old_event_is_rebuilt_only_after_a_confirmation_that_says_what_is_missing(self):
        self.edit('DELETE FROM report_snapshots')
        self.boxes.save = str(self.dir / 'rebuilt.pdf')
        self.panel().regenerate_pdf()
        ask = next(c for c in self.boxes.calls if c[0] == 'askokcancel')
        self.assertIn('NOT be identical', ask[1][1])
        self.assertTrue(ask[1][1].endswith('\n\nContinue?'))
        self.assertTrue((self.dir / 'rebuilt.pdf').exists())
        self.assertIn('Rebuilt from history rows', self.boxes.info_text())
        (self.dir / 'rebuilt2.pdf').unlink(missing_ok=True)
        self.boxes.ok, self.boxes.save = False, str(self.dir / 'rebuilt2.pdf')
        self.panel().regenerate_pdf()
        self.assertFalse((self.dir / 'rebuilt2.pdf').exists())

    def test_hash_mismatch_is_refused_with_a_message(self):
        self.edit("UPDATE report_snapshots SET payload_json=replace(payload_json,'T. Tech','X')")
        self.boxes.save = str(self.dir / 'x.pdf')
        self.panel().regenerate_pdf()
        self.assertIn('checksum', self.boxes.info_text())
        self.assertFalse((self.dir / 'x.pdf').exists())

    def test_double_click_regenerates_directly(self):
        p = self.panel()
        p.regenerate_pdf, p.open_report = mock.MagicMock(), mock.MagicMock()
        row = p.runs.rows()[0]
        with mock.patch.object(AH, 'choose_action', side_effect=AssertionError):      # no question
            p._runs_double(row)
        self.assertEqual((p.regenerate_pdf.call_count, p.open_report.call_count), (1, 0))
        p.regenerate_pdf.reset_mock()
        p._runs_double(None)                                                   # double-click on empty space: nothing
        self.assertEqual(p.regenerate_pdf.call_count, 0)

    def test_a_real_double_click_on_the_row_and_on_empty_space(self):
        p = self.panel()
        p.regenerate_pdf = mock.MagicMock()
        ix = p.runs.proxy.index(0, 1)
        support.dclick(p.runs.viewport(), p.runs.visualRect(ix).center())
        pump()
        self.assertEqual(p.regenerate_pdf.call_count, 1)
        support.dclick(p.runs.viewport(), QPoint(20, p.runs.viewport().height() - 6))
        pump()
        self.assertEqual(p.regenerate_pdf.call_count, 1, 'empty space does nothing')

    def test_context_menu_selects_the_row_and_pops_up(self):
        S.issue(self.dir / 'two.pdf')
        p = self.panel()
        self.assertEqual(p.runs.row_count()[0], 2)
        second = p.runs.proxy.index(1, 1)
        with mock.patch.object(p.menu, 'popup') as pop:
            p._runs_menu(p.runs.visualRect(second).center())
            pop.assert_called_once()
            self.assertEqual(p._selected_run_id(), p.runs.rows()[1]['id'])
            pop.reset_mock()
            p._runs_menu(QPoint(20, p.runs.viewport().height() - 6))          # empty space: no menu
            pop.assert_not_called()
        self.assertEqual([a.text() for a in p.menu.actions()], ['Regenerate PDF...', 'Open report PDF'])

    def test_the_buttons_call_the_handlers(self):
        p = self.panel()
        p.btn_regen.clicked.disconnect()
        p.btn_regen.clicked.connect(lambda *_a: self.boxes.calls.append(('regen', (), {})))
        p.btn_regen.click()
        self.assertEqual(self.boxes.kinds(), ['regen'])


class OpenAndDrift(Base):
    def test_open_report_missing_file_says_so(self):
        (self.dir / 'orig.pdf').unlink()
        p = self.panel()
        p.open_report()
        self.assertEqual(self.boxes.calls[-1][1], ('Report', 'The PDF is not at the place it was saved (it may have been moved or deleted).'))
        self.assertEqual(self.boxes.kinds(), ['info'])

    def test_open_report_hands_the_file_to_the_system_viewer(self):
        run = labregistry.runs_for('A-7')[0]
        self.assertTrue(os.path.exists(run['report_file']), run['report_file'])
        p = self.panel()
        with mock.patch.object(AH, '_open_file') as op:
            p.open_report()
        op.assert_called_once_with(run['report_file'])
        with mock.patch.object(AH, '_open_file', side_effect=OSError('no viewer')):
            p.open_report()
        self.assertEqual(self.boxes.calls[-1], ('error', ('Report', 'no viewer'), {}))

    def test_drift_needs_a_point_then_opens_the_chart_for_it(self):
        p = self.panel()
        p.show_drift()
        self.assertEqual(self.boxes.calls[-1][1], ('Drift', 'Select a test point in the lower table first.'))
        p.points.select_rows([p.points.rows()[1]])
        pump()
        with mock.patch.object(AH, 'open_drift_chart') as chart:
            p.show_drift()
        chart.assert_called_once()
        self.assertEqual(chart.call_args.args[1:], ('A-7', 'DC Volts', '100 V range', 'V'))
        # a double-click on a point opens the chart too
        with mock.patch.object(AH, 'open_drift_chart') as chart:
            support.dclick(p.points.viewport(), p.points.visualRect(p.points.proxy.index(0, 1)).center())
            pump()
        chart.assert_called_once()
        self.assertEqual(chart.call_args.args[1:], ('A-7', 'DC Volts', '10 V range', 'V'))

    def test_the_drift_chart_window_and_its_data(self):
        S.issue(self.dir / 'again.pdf')                                       # a second report of the same asset: two drift points
        seen = {}

        def look():
            dlg = QApplication.activeModalWidget()
            seen['title'] = dlg.title_label.text()
            seen['points'] = len(dlg.chart.points)
            seen['png'] = dlg.chart.grab().save(str(self.dir / 'drift.png'))
            dlg.button('close').click()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, look)
        AH.open_drift_chart(None, 'A-7', 'DC Volts', '100 V range', 'V')
        self.assertEqual(seen['title'], 'A-7  -  100 V range')
        self.assertEqual(seen['points'], 2)
        self.assertTrue(seen['png'])

    def test_choose_action_returns_the_choice(self):
        from PySide6.QtCore import QTimer
        for button, want in (('regenerate', 'regenerate'), ('open', 'open'), ('cancel', None)):
            QTimer.singleShot(40, lambda b=button: QApplication.activeModalWidget().button(b).click())
            self.assertEqual(AH.choose_action(None), want)
        QTimer.singleShot(40, lambda: QTest.keyClick(QApplication.activeModalWidget(), Qt.Key.Key_Escape))
        self.assertIsNone(AH.choose_action(None))


class Rules(unittest.TestCase):
    def test_the_screen_modules_import_no_tk(self):
        import ast
        for f in sorted((ROOT / 'qtui' / 'screens').glob('*.py')):
            for node in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for n in names:
                    top = n.split('.')[0]
                    self.assertNotIn(top, {'tkinter', 'ui_theme', 'ui_shell', 'ui_port_tk'}, f'{f.name} imports {n}')
                    self.assertFalse(top.endswith('_view_tk'), f'{f.name} imports {n}')


if __name__ == '__main__':
    unittest.main()
