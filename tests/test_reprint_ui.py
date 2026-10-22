"""Thin Tk wiring of 'Regenerate PDF' on the Asset History tab (labregistry_ui.HistoryPanel), under the tkinter stub.

No tkinter is installed where these tests run: the REAL window was never opened or looked at.  What is checked: the widgets/bindings the panel asks
for, and that the handlers pass the right questions to report_snapshot.regenerate and show its messages; the logic itself is in test_reprint_snapshot.

File name sorts after test_beta on purpose (the stub changes test_beta if installed earlier).  Run:  python -m unittest tests.test_reprint_ui
"""
import inspect
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402  (installs the tkinter stub)
import test_reprint_snapshot as S  # noqa: E402  (issue() / HEADER helpers only)
import labregistry  # noqa: E402
import labregistry_ui as lui  # noqa: E402
import report_snapshot as rs  # noqa: E402


class FakeTree:
    def __init__(self, selection=(), row_at=''):
        self._sel, self.row_at, self.binds, self.master = list(selection), row_at, {}, mock.MagicMock()

    def selection(self):
        return tuple(self._sel)

    def selection_set(self, row):
        self._sel = [row]

    def identify_row(self, y):
        return self.row_at

    def bind(self, seq, fn, add=None):
        self.binds[seq] = fn

    def __getattr__(self, name):
        return mock.MagicMock()


class Boxes:
    """Records messagebox / filedialog calls and answers them."""

    def __init__(self, save=None, yes=True, ok=True):
        self.calls, self.save, self.yes, self.ok = [], save, yes, ok

    def install(self, test):
        for name, fn in (('showinfo', lambda *a, **k: self.calls.append(('info', a, k))),
                         ('askyesno', lambda *a, **k: self.calls.append(('askyesno', a, k)) or self.yes),
                         ('askokcancel', lambda *a, **k: self.calls.append(('askokcancel', a, k)) or self.ok)):
            p = mock.patch.object(lui.messagebox, name, fn, create=True)
            p.start()
            test.addCleanup(p.stop)
        p = mock.patch.object(lui.filedialog, 'asksaveasfilename', lambda **k: self.calls.append(('save', (), k)) or self.save, create=True)
        p.start()
        test.addCleanup(p.stop)

    def kinds(self):
        return [c[0] for c in self.calls]

    def info_text(self):
        return ' '.join(str(c[1][1]) for c in self.calls if c[0] == 'info')


def panel(selection=()):
    p = object.__new__(lui.HistoryPanel)
    p.runs = FakeTree(selection)
    p.regen_note = R.Var()
    p.menu = mock.MagicMock()
    p.winfo_toplevel = lambda: 'TOP'
    return p


class Construction(unittest.TestCase):
    def test_the_panel_binds_double_click_and_context_menu_and_has_the_button(self):
        trees = []

        def make_table(parent, *a, **k):
            t = FakeTree()
            trees.append(t)
            return t
        menu = mock.MagicMock()
        with mock.patch.object(lui.ui, 'make_table', make_table), mock.patch.object(lui.tk, 'Menu', lambda *a, **k: menu), \
                mock.patch.object(lui.reg, 'assets_overview', lambda term='': []), mock.patch.object(lui.ttk, 'Button') as button:
            p = lui.HistoryPanel(None)
        runs = trees[1]
        self.assertEqual(sorted(runs.binds), sorted(['<Button-2>', '<Button-3>', '<Double-1>', '<<TreeviewSelect>>']))
        self.assertEqual(runs.binds['<Double-1>'].__func__, lui.HistoryPanel._runs_double)
        self.assertNotIn('<Double-1>', trees[0].binds)
        self.assertIn('<Double-1>', trees[2].binds, 'double-click on a point still opens the drift chart')
        labels = [c.kwargs.get('text') for c in button.call_args_list]
        self.assertIn('Regenerate PDF...', labels)
        self.assertIn('Open report PDF', labels)
        self.assertEqual([c.kwargs['label'] for c in menu.add_command.call_args_list], ['Regenerate PDF...', 'Open report PDF'])
        self.assertTrue(p is not None)


class Handlers(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        S.issue(self.dir / 'orig.pdf')
        self.rid = labregistry.runs_for('A-7')[0]['id']
        self.boxes = Boxes()
        self.boxes.install(self)

    def edit(self, sql):
        con = sqlite3.connect(str(self.db))
        con.execute(sql)
        con.commit()
        con.close()

    def test_regenerate_asks_where_to_save_and_reports_the_new_file(self):
        out = self.dir / 'again.pdf'
        self.boxes.save = str(out)
        p = panel([str(self.rid)])
        p.regenerate_pdf()
        save = next(c for c in self.boxes.calls if c[0] == 'save')[2]
        self.assertEqual(save['initialfile'], 'A-7-01-02-2026.pdf')
        self.assertEqual(save['initialdir'], str(self.dir))
        self.assertFalse(save['confirmoverwrite'], 'the panel asks about overwriting itself')
        self.assertTrue(out.read_bytes().startswith(b'%PDF'))
        self.assertIn('Regenerated from the saved record', self.boxes.info_text())

    def test_nothing_selected(self):
        panel().regenerate_pdf()
        self.assertEqual(self.boxes.kinds(), ['info'])
        self.assertIn('Select a report', self.boxes.info_text())

    def test_cancelled_save_dialog_is_silent(self):
        self.boxes.save = ''
        panel([str(self.rid)]).regenerate_pdf()
        self.assertEqual(self.boxes.kinds(), ['save'])

    def test_existing_file_asks_and_declining_keeps_it(self):
        there = self.dir / 'there.pdf'
        there.write_bytes(b'precious')
        self.boxes.save, self.boxes.yes = str(there), False
        panel([str(self.rid)]).regenerate_pdf()
        ask = next(c for c in self.boxes.calls if c[0] == 'askyesno')
        self.assertEqual(ask[2]['default'], 'no')
        self.assertEqual(there.read_bytes(), b'precious')
        self.boxes.save, self.boxes.yes = str(there), True
        panel([str(self.rid)]).regenerate_pdf()
        self.assertTrue(there.read_bytes().startswith(b'%PDF'))

    def test_replacing_the_original_file_says_so(self):
        self.boxes.save, self.boxes.yes = str(self.dir / 'orig.pdf'), False
        panel([str(self.rid)]).regenerate_pdf()
        self.assertIn('original report was saved to', next(c for c in self.boxes.calls if c[0] == 'askyesno')[1][1])

    def test_missing_snapshot_and_incomplete_history_show_the_plain_message(self):
        self.edit('DELETE FROM report_snapshots')
        self.edit('DELETE FROM points WHERE rowid=(SELECT MAX(rowid) FROM points)')
        self.boxes.save = str(self.dir / 'x.pdf')
        panel([str(self.rid)]).regenerate_pdf()
        self.assertIn('no saved report record', self.boxes.info_text())
        self.assertIn('Only 2 of the 3 points', self.boxes.info_text())
        self.assertNotIn('save', self.boxes.kinds())
        self.assertFalse((self.dir / 'x.pdf').exists())

    def test_old_event_is_rebuilt_only_after_a_confirmation_that_says_what_is_missing(self):
        self.edit('DELETE FROM report_snapshots')
        self.boxes.save = str(self.dir / 'rebuilt.pdf')
        panel([str(self.rid)]).regenerate_pdf()
        ask = next(c for c in self.boxes.calls if c[0] == 'askokcancel')
        self.assertIn('NOT be identical', ask[1][1])
        self.assertTrue((self.dir / 'rebuilt.pdf').exists())
        self.assertIn('Rebuilt from history rows', self.boxes.info_text())
        (self.dir / 'rebuilt2.pdf').unlink(missing_ok=True)
        self.boxes.ok, self.boxes.save = False, str(self.dir / 'rebuilt2.pdf')
        panel([str(self.rid)]).regenerate_pdf()
        self.assertFalse((self.dir / 'rebuilt2.pdf').exists())

    def test_hash_mismatch_is_refused_with_a_message(self):
        self.edit("UPDATE report_snapshots SET payload_json=replace(payload_json,'T. Tech','X')")
        self.boxes.save = str(self.dir / 'x.pdf')
        panel([str(self.rid)]).regenerate_pdf()
        self.assertIn('checksum', self.boxes.info_text())
        self.assertFalse((self.dir / 'x.pdf').exists())

    def test_double_click_regenerates_directly(self):
        p = panel([str(self.rid)])
        p.runs.row_at = str(self.rid)
        p.regenerate_pdf, p.open_report = mock.MagicMock(), mock.MagicMock()
        event = mock.MagicMock(y=5)
        with mock.patch.object(lui, 'choose_action', side_effect=AssertionError):      # no question
            p._runs_double(event)
        self.assertEqual((p.regenerate_pdf.call_count, p.open_report.call_count), (1, 0))
        p.regenerate_pdf.reset_mock()
        p.runs.row_at = ''                                                     # double-click on empty space: nothing
        p._runs_double(event)
        self.assertEqual(p.regenerate_pdf.call_count, 0)

    def test_context_menu_selects_the_row_and_pops_up(self):
        p = panel()
        p.runs.row_at = str(self.rid)
        p._runs_menu(mock.MagicMock(y=3, x_root=10, y_root=20))
        self.assertEqual(p.runs.selection(), (str(self.rid),))
        p.menu.tk_popup.assert_called_once_with(10, 20)
        p.menu.reset_mock()
        p.runs.row_at = ''
        p._runs_menu(mock.MagicMock(y=3, x_root=10, y_root=20))
        p.menu.tk_popup.assert_not_called()

    def test_hint_line_tells_whether_the_event_can_be_regenerated(self):
        p = panel()
        p._show_regen_hint(self.rid)
        self.assertIn('Saved report record found', p.regen_note.get())
        self.edit('DELETE FROM report_snapshots')
        p._show_regen_hint(self.rid)
        self.assertIn('can be rebuilt from history rows, not identical', p.regen_note.get())
        p._show_regen_hint(None)
        self.assertEqual(p.regen_note.get(), '')
        with mock.patch.object(lui.snap, 'availability', side_effect=RuntimeError('x')):
            p._show_regen_hint(self.rid)
        self.assertEqual(p.regen_note.get(), '', 'a failure never reaches the user as an error window')

    def test_source_has_the_wiring(self):
        src = inspect.getsource(lui.HistoryPanel.__init__)
        self.assertIn("self.runs.bind('<Double-1>', self._runs_double)", src)
        self.assertIn('Regenerate PDF...', src)


if __name__ == '__main__':
    unittest.main()
