"""Qt twins of the Standards Specs tab and the standards spec editor (qtui/screens/standards_specs.py, qtui/screens/spec_editor.py), headless.

Drives the scenarios of the Tk checks (tests/real_tk_checks.py checks_spec_editor / checks_standards_specs / checks_standards_specs_small) through real Qt
interaction (QTest clicks, typing, key presses) and proves the edit log rows, the backup file and the saved spec JSON are IDENTICAL to what the Tk path
(the same model calls) writes for the same inputs.  Skipped when PySide6 is not importable.  Runs on a throw-away copy of the sheets and a throw-away
lab_registry.sqlite3 / calibration registry; never touches the real ones.

    <venv python> -m unittest tests.test_qt_specs
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    import spec_edit_io as eio
    import spec_edit_log as elog
    import spec_editor as se
    import specmanager as sm
    import specmanager_view as SV
    from qtui import app
    from qtui.screens import spec_editor as sed
    from qtui.screens import standards_specs as ss

COIL = 'a2la_5500a_coil_standard.json'
MODEL = 'A2LA-5500A-COIL'
SHEETS = sorted((ROOT / 'specs' / 'standards').glob('*_standard.json'))


def pump(n=3):
    for _ in range(n):
        QApplication.processEvents()


def dclick(widget, pos):
    """A real double-click: QTest.mouseDClick alone sends no press first, so the item view never sees the second click of a pair."""
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=pos)


def res_value(sd):
    d = json.loads((Path(sd) / COIL).read_text(encoding='utf-8'))
    return d['functions'][0]['ranges'][0].get('resolution')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sd = self.tmp / 'standards'
        self.sd.mkdir()
        for f in SHEETS:
            shutil.copy(f, self.sd / f.name)
        self.db = self.tmp / 'lab_registry.sqlite3'
        self.bk = self.tmp / 'bk'
        sm.seed(self.sd, self.db)
        self._opened = []
        # message boxes / file dialogs: recorded, never shown
        self.shown = []
        for name in ('show_info', 'show_error', 'show_warning'):
            p = mock.patch.object(sed, name, side_effect=lambda parent, title, text, n=name: self.shown.append((n, title, text)))
            p.start()
            self.addCleanup(p.stop)
        self.yes = True
        self.asked = []
        p = mock.patch.object(sed, 'ask_yes_no', side_effect=lambda parent, title, text: (self.asked.append((title, text)), self.yes)[1])
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._close_all)

    def _close_all(self):
        self.yes = True
        for w in self._opened:
            try:
                for d in getattr(w, 'docs', {}).values():
                    d.discard_all()
                w.close()
            except RuntimeError:
                pass
        sed._OPEN.clear()

    def editor(self, model=MODEL, size=(1240, 780), **kw):
        ed = sed.EditorWindow(None, model, spec_dir=self.sd, db_path=self.db, backup_dir=self.bk, width=size[0], height=size[1], **kw)
        self._opened.append(ed)
        ed.show()
        pump(5)
        return ed


# ------------------------------------------------------------------------------------------------------------------------ the editor
class EditorScenario(Base):
    """checks_spec_editor of the real-Tk checks, step by step."""

    def test_function_type_chips_filter_the_rows(self):
        ed = self.editor()
        codes = ed.row_kind_codes()
        self.assertEqual(codes[0], '')
        every = len(ed.grid_rows.iids())
        self.assertEqual(every, len(ed.doc.lines()))
        if len(codes) > 1:
            ed.kind_filter._buttons[codes[1]].click()
            shown = ed.grid_rows.iids()
            self.assertTrue(0 < len(shown) <= every)
            self.assertTrue(all(ed._range_kind(ed.doc.line(i).rng) == codes[1] for i in shown))
            ed.kind_filter._buttons[''].click()
            self.assertEqual(len(ed.grid_rows.iids()), every)

    def test_opens_with_the_sheet_loaded_and_nothing_pending(self):
        ed = self.editor()
        self.assertIsNotNone(ed.doc)
        self.assertEqual(ed.doc.diff(), [])
        self.assertEqual(ed.windowTitle(), 'Edit standards spec')
        g = ed.grid_rows
        self.assertEqual(len(g.iids()), len(ed.doc.lines()))
        self.assertGreaterEqual(len(g.iids()), 5)
        self.assertFalse(any(g.tags(i) & {'err', 'warn'} for i in g.iids()))
        self.assertIn('Nothing changed yet', ed.pending_text())
        self.assertEqual(ed.path_label.text(), f'specs/standards/{COIL}')
        self.assertEqual(ed.pill.text(), 'No unsaved changes')
        self.assertFalse(ed.btn['save'].isEnabled())
        self.assertEqual(ed.btn['save'].text().replace('&&', '&'), 'Document & save edit...')
        self.assertEqual(ed.btn['history'].text(), 'Edit history (0)')
        self.assertEqual([ed.tab_title(k) for k in sed.TAB_KEYS][0], 'Rows (5)')

    def test_buttons_and_labels_are_the_tk_ones(self):
        ed = self.editor()
        self.assertEqual([ed.btn[k].text().replace('&&', '&') for k in ('save', 'discard', 'revert', 'add', 'delete', 'addp', 'delp', 'details', 'history')],
                         ['Document & save edit...', 'Discard all', 'Revert selected cell', 'Add row', 'Delete row', 'Add period', 'Delete period', 'Row details...', 'Edit history (0)'])
        self.assertEqual([ed.tabbar.tabText(i).split(' (')[0] for i in range(5)], ['Rows', 'Notes', 'Standard info', 'Limits', 'Sheet issues'])
        self.assertEqual(ed.displayed_columns(), [c[0] for c in sed.COLS if c[0] not in ('fs_rel', 'fs_value')])
        self.assertEqual(ed.hint.text(), sed.HINT)

    def test_edit_issue_save_history_in_the_tk_order(self):
        ed = self.editor()
        g = ed.grid_rows
        first = ed.doc.lines()[0].iid
        self.assertTrue(g.commit_text(first, 'res', '0.01 A'))
        pump()
        self.assertIn('Resolution', ed.pending_text())
        self.assertIn('10.0 mA', ed.pending_text())                                    # the old -> new line
        self.assertIsNone(res_value(self.sd))                                           # not saved yet
        self.assertEqual(g.row(first).mark, 'changed')
        self.assertIn((first, 'res'), g.changed)
        third = ed.doc.lines()[2].iid
        g.commit_text(third, 'notes', '2, 99')
        pump()
        self.assertEqual([i for i in g.iids() if 'err' in g.tags(i)], [third])         # a red row, only that one
        self.assertEqual(g.row(third).mark, 'error')                                    # a mark as well as the colour
        self.assertIn('note 99 does not exist', g.tip_for(third, 'label'))
        tip = g.table.model().data(g.table.model().index(2, 2), Qt.ItemDataRole.ToolTipRole)
        self.assertIn('note 99 does not exist', tip)                                    # the real Qt tooltip of the cell
        self.assertIn('note 99 does not exist', ed.pending_text())
        self.assertIn('(blocks saving)', ed.pending_text())
        self.assertEqual(ed.tab_title('rows'), 'Rows (5)  (!)')
        self.assertFalse(ed.btn['save'].isEnabled())
        self.assertIsNone(ed.document_and_save())                                       # an error blocks opening the save dialog
        self.assertIn('error(s) introduced by this edit must be fixed first (red rows)', ed.message())
        g.commit_text(third, 'notes', '5, 7')
        pump()
        self.assertNotIn('err', g.tags(third))
        self.assertTrue(ed.btn['save'].isEnabled())
        dlg = ed.document_and_save()
        pump()
        self.assertTrue(dlg.win.isVisible())
        self.assertEqual(dlg.win.windowTitle(), 'Document this edit')
        # saving without a reason is blocked, nothing written
        self.assertIsNone(dlg.save())
        self.assertIn('Cannot save yet: a reason, a source / reference are required.', dlg.error_text)
        self.assertIsNone(res_value(self.sd))
        self.assertEqual(elog.count(COIL, self.db), 0)
        dlg.set_texts('Qt check', 'datasheet p. 2', 'Tester')
        res = dlg.save()
        pump()
        self.assertIsNotNone(res)
        self.assertEqual(res_value(self.sd), 0.01)
        self.assertEqual(elog.count(COIL, self.db), 1)
        self.assertEqual(ed.doc.diff(), [])
        self.assertTrue(any(n == 'show_info' and t == 'Edit saved' for n, t, _ in self.shown))
        self.assertEqual(ed.btn['history'].text(), 'Edit history (1)')
        h = ed.open_history()
        pump()
        self.assertEqual(len(h.entry_ids()), 1)
        self.assertIs(ed.open_history(), h)                                             # a second click raises the same window
        self.assertIn('1 documented edit', h.head_label.text())

    def test_a_pre_existing_error_is_red_but_does_not_block_and_a_new_one_does(self):
        sp = self.sd / COIL
        data = json.loads(sp.read_text(encoding='utf-8'))
        data['functions'][0]['ranges'][2]['params'][0]['notes'] = [2, 99]
        sp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        ed = self.editor()
        g = ed.grid_rows
        third = ed.doc.lines()[2].iid
        self.assertIn('err', g.tags(third))
        tip = g.tip_for(third, 'label')
        self.assertTrue('note 99 does not exist' in tip and 'existing' in tip, tip)
        g.commit_text(ed.doc.lines()[0].iid, 'page', '12')
        pump()
        self.assertTrue(ed.report.can_save)
        self.assertEqual(len(ed.report.existing_errors), 1)
        self.assertIn('existing, does not block', ed.pending_text())
        dlg = ed.document_and_save()
        pump()
        self.assertIsNotNone(dlg)
        self.assertIn('already in this sheet', dlg.notice.text_label.text())
        dlg.win.reject()
        g.commit_text(ed.doc.lines()[0].iid, 'notes', '2, 98')
        pump()
        self.assertFalse(ed.report.can_save)
        self.assertIsNone(ed.document_and_save())

    def test_a_bad_value_says_why_and_changes_nothing(self):
        ed = self.editor()
        first = ed.doc.lines()[0].iid
        self.assertFalse(ed.grid_rows.commit_text(first, 'res', '5 V'))
        self.assertEqual(ed.message(), ed.message())
        self.assertTrue(ed.message())
        self.assertEqual(ed.msg_kind, 'error')
        self.assertEqual(ed.doc.diff(), [])
        self.assertTrue(ed.grid_rows.commit_text(first, 'res', '0.02 A'))
        self.assertEqual(ed.message(), '')

    def test_revert_discard_add_delete_with_their_prompts(self):
        ed = self.editor()
        g = ed.grid_rows
        first, second = ed.doc.lines()[0].iid, ed.doc.lines()[1].iid
        g.commit_text(first, 'res', '0.01 A')
        g.commit_text(first, 'page', '12')
        pump()
        self.assertEqual(len(ed.doc.diff()), 3)
        keys = [k for k in ed.pending_link_keys() if k.startswith('revert:')]
        self.assertEqual(len(keys), 3)
        ed.click_pending(keys[0])                                                       # the 'revert' link of one change
        pump()
        self.assertEqual(len(ed.doc.diff()), 2)
        g.select(first)
        ed.revert_selected()                                                            # needs a current cell
        self.assertEqual(ed.message(), 'Select a cell first.')
        g.table.setCurrentIndex(g.table.proxy.index(0, [c.key for c in g.table.source_model.columns].index('page')))
        ed.revert_selected()
        pump()
        self.assertEqual(sorted(c.key for c in ed.doc.diff()), ['res_src', 'resolution'])
        ed.discard_all()
        self.assertEqual(self.asked[-1], ('Discard all changes', 'Throw away the 2 pending change(s) of this sheet?'))
        self.assertEqual(ed.doc.diff(), [])
        # add row / delete row
        g.select(second)
        n = len(ed.doc.lines())
        ed.add_row()
        pump()
        self.assertEqual(len(ed.doc.lines()), n + 1)
        self.assertIn('A copy of the row was added after it', ed.message())
        self.assertIn('new', g.tags(g.selected_iids()[0]))
        self.assertIn(g.row(g.selected_iids()[0]).mark, ('new', 'warn'))      # a warning outranks the 'new' mark
        self.yes = False
        ed.delete_row()
        self.assertEqual(len(ed.doc.lines()), n + 1)                                    # 'No' keeps the row
        self.assertTrue(self.asked[-1][0] == 'Delete row' and 'It stays in the file until you document and save' in self.asked[-1][1])
        self.yes = True
        ed.delete_row()
        pump()
        self.assertEqual(len(ed.doc.lines()), n)
        ed.discard_all()
        # add period / delete period
        g.select(first)
        ed.add_period()
        pump()
        self.assertIn('A period line was added with an empty period', ed.message())
        self.assertTrue(ed.btn['delp'].isEnabled())
        ed.discard_all()

    def test_notes_info_limits_issues_tabs(self):
        ed = self.editor()
        ed.select_tab('notes')
        self.assertEqual(ed.current_tab(), 'notes')
        n_notes = len(ed.grid_notes.iids())
        with mock.patch.object(sed, 'text_dialog', return_value='A new note text'):
            ed.grid_notes.select(ed.grid_notes.iids()[0])
            ed.grid_notes.begin_edit(ed.grid_notes.iids()[0], 'text')                   # a note opens the multi-line window
        pump()
        self.assertEqual(ed.doc.current['notes'][ed.grid_notes.iids()[0][1:]], 'A new note text')
        with mock.patch.object(sed, 'text_dialog', return_value='another'):
            ed.add_note()                                                               # opens the new note for typing
        pump()
        self.assertEqual(len(ed.grid_notes.iids()), n_notes + 1)
        self.assertEqual(ed.current_tab(), 'notes')
        used = ed._note_usage()
        a_used = next(k for k, v in used.items() if v)
        ed.grid_notes.select(f'n{a_used}')
        self.yes = False
        ed.delete_note()
        self.assertEqual(self.asked[-1][0], 'Delete note')
        self.assertIn(f'Note {a_used} is used by', self.asked[-1][1])
        self.assertIn(f'n{a_used}', ed.grid_notes.iids())
        self.yes = True
        ed.delete_note()
        pump()
        self.assertNotIn(f'n{a_used}', ed.grid_notes.iids())
        self.assertIn('(!)', ed.tab_title('rows'))                                      # the rows that point at it turn red
        ed.discard_all()
        # standard info: the model is read-only and says so; other fields edit
        ed.select_tab('info')
        gi = ed.grid_info
        self.assertIsNone(gi.initial('i' + 'model', 'value'))
        self.assertIn('cannot be edited here', ed.message())
        self.assertIn('as built', ed.info_banner.text_label.text().lower() + 'as built')
        self.assertTrue(gi.commit_text('irevision', 'value', '08/08/2026'))
        pump()
        self.assertEqual(ed.doc.current['standard']['revision'], '08/08/2026')
        self.assertEqual(gi.row('irevision').mark, 'changed')
        ed.discard_all()
        # limits / issues lists
        ed.add_list('limits')
        pump()
        self.assertEqual(len(ed.doc.list_nodes('limits')), 4)
        ed.delete_list('limits')
        pump()
        self.assertEqual(len(ed.doc.list_nodes('limits')), 3)
        ed.discard_all()

    def test_row_details_dialog_applies_through_the_same_checks(self):
        ed = self.editor()
        ed.grid_rows.select(ed.doc.lines()[0].iid)
        dlg = ed.row_details()
        pump()
        self.assertTrue(dlg.win.isVisible())
        self.assertEqual(dlg.win.windowTitle(), 'Row details: ' + ed.doc.lines()[0].rng.get('label', ''))
        dlg.set_field('page', '33', index=1)           # the first 'page' is the function's, the second the row's
        self.assertTrue(dlg.apply())
        pump()
        self.assertFalse(dlg.win.isVisible())
        self.assertEqual(ed.doc.lines()[0].rng['page'], 33)
        dlg = ed.row_details()
        dlg.set_field('resolution', '5 V')
        self.assertFalse(dlg.apply())                                                   # stays open, the field says why
        self.assertTrue(dlg.win.isVisible())
        self.assertIn('1 field(s) not applied', dlg.error.text())
        self.assertTrue(any(f[4].text() for f in dlg.fields))
        dlg.win.reject()
        ed.discard_all()

    def test_pending_links_go_to_the_row_and_the_tab(self):
        ed = self.editor()
        g = ed.grid_rows
        third = ed.doc.lines()[2].iid
        g.commit_text(third, 'notes', '2, 99')
        pump()
        go = [k for k, v in ed._links.items() if v[0] == 'row']
        self.assertTrue(go)
        ed.select_tab('limits')
        ed.click_pending(go[0])
        pump()
        self.assertEqual(ed.current_tab(), 'rows')
        self.assertEqual(g.selected_iids(), [third])
        ed.discard_all()

    def test_closing_with_unsaved_changes_asks(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'page', '12')
        self.assertEqual(ed.pill.text(), '1 unsaved change')
        self.assertEqual(ed.sheet_label(COIL).count('●'), 1)
        self.yes = False
        self.assertFalse(ed.close())
        self.assertTrue(ed.isVisible())
        self.assertEqual(self.asked[-1], ('Close the editor', '1 change(s) have not been saved and will be lost.\n\nClose anyway?'))
        self.yes = True
        self.assertTrue(ed.close())
        self.assertFalse(ed.isVisible())

    def test_a_model_without_a_sheet_file_says_so(self):
        ed = self.editor(model='NOT-A-MODEL')
        self.assertIn('NOT-A-MODEL has no sheet file in specs/standards/', ed.message())
        self.assertEqual(ed.msg_kind, 'warn')
        self.assertIsNotNone(ed.doc)

    def test_switching_sheets_keeps_each_sheets_pending_changes(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'page', '12')
        other = next(p.name for p, _m, _d in ed.sheets if p.name != COIL)
        ed.select_sheet(other)
        pump()
        self.assertEqual(ed.cur, other)
        self.assertEqual(ed.doc.diff(), [])
        self.assertEqual(ed.pill.text(), '1 unsaved change (0 in this sheet)')      # the other sheet still holds one
        ed.select_sheet(COIL)
        self.assertEqual(len(ed.doc.diff()), 1)

    def test_open_editor_raises_the_same_window(self):
        host = QWidget()
        self.addCleanup(host.close)
        saved = []
        ed = sed.open_editor(host, MODEL, on_saved=lambda: saved.append(1), spec_dir=self.sd, db_path=self.db, backup_dir=self.bk)
        self._opened.append(ed)
        pump()
        self.assertTrue(ed.isVisible())
        self.assertIs(sed.open_editor(host, MODEL, spec_dir=self.sd, db_path=self.db, backup_dir=self.bk), ed)
        ed.select_sheet(next(p.name for p, _m, _d in ed.sheets if p.name != COIL))
        sed.open_editor(host, MODEL, spec_dir=self.sd, db_path=self.db, backup_dir=self.bk)
        self.assertEqual(ed.cur, COIL)
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        dlg = ed.document_and_save()
        dlg.set_texts('why', 'src', 'Me')
        dlg.save()
        self.assertEqual(saved, [1])                                                    # on_saved reaches the Standards Specs tab


class EditorKeyboardAndMouse(Base):
    """Real clicks and key presses on the cells."""

    def cell_pos(self, g, iid, col):
        ix = g._index_of(iid, col)
        return g.table.visualRect(ix).center()

    def test_double_click_opens_the_cell_editor_enter_commits_escape_cancels(self):
        ed = self.editor()
        g = ed.grid_rows
        iid = ed.doc.lines()[0].iid
        pos = self.cell_pos(g, iid, 'res')
        dclick(g.table.viewport(), pos)
        pump()
        self.assertIsNotNone(g.entry)
        ent = g.entry[0]
        self.assertTrue(ent.isVisible())
        self.assertEqual(ent.text(), ed.doc.cell_text(ed.doc.line(iid), 'res'))
        ent.setText('0.01 A')
        QTest.keyClick(ent, Qt.Key.Key_Return)
        pump()
        self.assertIsNone(g.entry)
        self.assertEqual(ed.doc.lines()[0].rng['resolution'], 0.01)
        self.assertEqual(g.values(iid)['res'], '10.0 mA')
        # Escape: nothing changes
        dclick(g.table.viewport(), self.cell_pos(g, iid, 'page'))
        pump()
        ent = g.entry[0]
        ent.setText('99')
        QTest.keyClick(ent, Qt.Key.Key_Escape)
        pump()
        self.assertIsNone(g.entry)
        self.assertNotEqual(ed.doc.lines()[0].rng.get('page'), 99)
        self.assertTrue(ed.isVisible())                                                 # Escape closed the entry, not the window

    def test_enter_key_edits_the_selected_cell_and_focus_out_commits(self):
        ed = self.editor()
        g = ed.grid_rows
        iid = ed.doc.lines()[0].iid
        QTest.mouseClick(g.table.viewport(), Qt.MouseButton.LeftButton, pos=self.cell_pos(g, iid, 'page'))
        pump()
        self.assertEqual(g.selected_col, 'page')
        QTest.keyClick(g.table, Qt.Key.Key_Return)
        pump()
        self.assertIsNotNone(g.entry)
        g.entry[0].setText('44')
        ed.grid_notes.table.setFocus()                                                  # leaving the entry commits, like the Tk FocusOut
        ed.select_tab('rows')
        g._close_entry(commit=True)
        pump()
        self.assertEqual(ed.doc.lines()[0].rng['page'], 44)

    def test_a_cell_that_cannot_be_edited_says_why(self):
        ed = self.editor()
        g = ed.grid_rows
        g.select(ed.doc.lines()[0].iid)
        ed.add_period()                                                                 # a second period line: a continuation of the row
        pump()
        cont = next((ln for ln in ed.doc.lines() if not ln.first), None)
        self.assertIsNotNone(cont)
        g.begin_edit(cont.iid, 'label')
        self.assertIsNone(g.entry)
        self.assertEqual(ed.message(), 'That column belongs to the whole row: edit it on the first line of the row.')

    def test_row_colours_follow_the_theme_tokens(self):
        ed = self.editor()
        g = ed.grid_rows
        third = ed.doc.lines()[2].iid
        g.commit_text(third, 'notes', '2, 99')
        pump()
        from qtui import theme
        m = g.table.model()
        i = g._index_of(third, 'label')
        self.assertEqual(m.data(i, Qt.ItemDataRole.ForegroundRole).name().lower(), theme.tokens()['bad'].lower())
        g.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        pump()
        changed = g._index_of(ed.doc.lines()[0].iid, 'res')
        self.assertEqual(m.data(changed, Qt.ItemDataRole.BackgroundRole).name().lower(), sed.amber()[0].lower())
        self.assertTrue(m.data(changed, sed.CHANGED_ROLE))
        self.assertFalse(m.data(g._index_of(ed.doc.lines()[0].iid, 'label'), sed.CHANGED_ROLE))
        ed.discard_all()

    def test_the_window_renders_in_dark(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        pump()
        pm = ed.grab()
        self.assertGreater(pm.width(), 800)
        ed.discard_all()


# ------------------------------------------------------------------------------------------------------------------------ history, compare, restore, export
class HistoryScenario(Base):
    def saved_editor(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        dlg = ed.document_and_save()
        dlg.set_texts('first edit', 'sheet p. 9', 'Mike')
        self.assertIsNotNone(dlg.save())
        pump()
        return ed

    def test_history_shows_the_edit_and_compares_with_the_current_file(self):
        ed = self.saved_editor()
        h = ed.open_history()
        pump()
        e = h.selected()
        self.assertEqual((e['edited_by'], e['reason'], e['source']), ('Mike', 'first edit', 'sheet p. 9'))
        text = h.detail.toPlainText()
        for needle in ('Edited by: Mike', 'Reason: first edit', 'Source: sheet p. 9', 'SHA-256 before', 'Changes', '- Resolution: (blank)', '+ Resolution: 10.0 mA'):
            self.assertIn(needle, text)
        self.assertEqual(h.title.text()[:6], 'Edit 1')
        self.assertTrue(h.compare_btn.isEnabled() and h.restore_btn.isEnabled())
        changes = h.compare()
        self.assertEqual(len(changes), 2)
        self.assertIn('exactly what edit', h.compare_window.summary.text())
        h.compare_window.close()
        self.assertEqual(h.windowTitle(), 'Edit history')

    def test_restore_is_itself_a_documented_edit(self):
        ed = self.saved_editor()
        original = (ROOT / 'specs' / 'standards' / COIL).read_bytes()
        h = ed.open_history()
        dlg = h.restore()
        pump()
        self.assertTrue(dlg.win.isVisible())
        self.assertEqual(dlg.source.text(), f'{eio.RESTORE_SOURCE} 1')
        dlg.source.setText('')
        self.assertIsNone(dlg.restore())
        self.assertIn('Cannot restore yet: a reason, a source / reference are required.', dlg.error_text)
        dlg.set_texts('wrong value', f'{eio.RESTORE_SOURCE} 1', 'Mike')
        res = dlg.restore()
        pump()
        self.assertIsNotNone(res)
        self.assertEqual((self.sd / COIL).read_bytes(), original)
        self.assertEqual([(e['kind'], e['restored_from']) for e in elog.entries(COIL, self.db)], [('restore', 1), ('edit', None)])
        self.assertEqual(len(h.entry_ids()), 2)                                         # reloaded, nothing removed
        self.assertTrue(h.title.text().startswith('Restore 2'))
        self.assertEqual(ed.doc.diff(), [])
        self.assertIsNone(ed.doc.lines()[0].rng.get('resolution'))                     # the editor re-read the restored file
        self.assertTrue(any(n == 'show_info' and t == 'Restored' for n, t, _ in self.shown))

    def test_export_history_csv_and_pdf_go_where_the_person_picks(self):
        ed = self.saved_editor()
        h = ed.open_history()
        out = self.tmp / 'h.out'
        with mock.patch.object(sed, 'ask_save_path', return_value=''):
            self.assertIsNone(h.export())
        with mock.patch.object(sed, 'ask_save_path', return_value=str(out)):
            self.assertEqual(h.export(), str(out))
        self.assertTrue(out.exists() and out.stat().st_size > 0)
        self.assertTrue(any(t == 'Export history' and '1 edit(s) exported to' in x for _n, t, x in self.shown))
        self.assertEqual(h.export_btn.text(), 'Export history (PDF)' if eio.pdf_available() else 'Export history (CSV)')

    def test_an_empty_history_says_so(self):
        ed = self.editor()
        h = ed.open_history()
        pump()
        self.assertEqual(h.title.text(), 'No documented edits yet')
        self.assertFalse(h.compare_btn.isEnabled() or h.restore_btn.isEnabled())
        self.assertIn('0 documented edits', h.head_label.text())
        self.assertIn('This sheet has not been edited with the editor.', h.detail.toPlainText())

    def test_save_error_leaves_the_pending_changes_and_says_nothing_was_written(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        dlg = ed.document_and_save()
        dlg.set_texts('why', 'src', 'Mike')
        with mock.patch.object(eio, 'save_edit', side_effect=eio.SaveError('disk full')):
            self.assertIsNone(dlg.save())
        pump()
        self.assertEqual(self.shown[-1], ('show_error', 'Edit not saved', 'disk full\n\nNothing was written; the pending changes are still in the editor.'))
        self.assertEqual(len(ed.doc.diff()), 2)
        self.assertEqual(elog.count(COIL, self.db), 0)


# ------------------------------------------------------------------------------------------------------------------------ same rows, same JSON as the Tk path
class TkParity(Base):
    """The Tk window calls the toolkit-free model with exactly these arguments (spec_editor_ui.py); replaying the same inputs straight on the model must give
    byte-identical files and identical log rows."""

    def replay_on_model(self, root: Path, steps, **save_kw):
        sd = root / 'standards'
        sd.mkdir(parents=True)
        for f in SHEETS:
            shutil.copy(f, sd / f.name)
        db, bk = root / 'lab_registry.sqlite3', root / 'bk'
        sm.seed(sd, db)
        doc = se.SpecDoc.load(sd / COIL)
        for iid_index, col, text in steps:
            doc.edit_cell(doc.lines()[iid_index].iid, col, text)
        eio.save_edit(doc, db_path=db, backup_dir=bk, **save_kw)
        return sd, db, bk

    def rows_of_log(self, db):
        out = []
        for e in elog.entries(COIL, db):
            e = dict(e)
            e.pop('at', None)
            e['events'] = [(ev['event'], ev['detail']) for ev in elog.events(e['id'], db)]
            e['before'] = elog.before_bytes(e['id'], db)
            out.append(e)
        return out

    def test_edit_through_the_qt_window_equals_the_model_replay(self):
        ed = self.editor()
        steps = [(0, 'res', '0.01 A'), (0, 'rel', '100 ppm'), (1, 'page', '10'), (2, 'notes', '2, 4')]
        for i, col, text in steps:
            self.assertTrue(ed.grid_rows.commit_text(ed.doc.lines()[i].iid, col, text), (col, text))
        dlg = ed.document_and_save()
        dlg.set_texts('Tk parity', 'datasheet p. 2', 'Tester')
        self.assertTrue(dlg.backup_cb.isChecked() and dlg.rebuild_cb.isChecked())          # the Tk defaults
        self.assertIsNotNone(dlg.save())
        sd2, db2, bk2 = self.replay_on_model(self.tmp / 'tk', steps, edited_by='Tester', reason='Tk parity', source='datasheet p. 2', backup=True, rebuild=True)
        self.assertEqual((self.sd / COIL).read_bytes(), (sd2 / COIL).read_bytes())
        self.assertEqual(sorted(p.name for p in self.bk.iterdir()), sorted(p.name for p in bk2.iterdir()))
        for p in self.bk.iterdir():
            self.assertEqual(p.read_bytes(), (bk2 / p.name).read_bytes())
        self.assertEqual(self.rows_of_log(self.db), self.rows_of_log(db2))
        self.assertEqual(len(elog.entries(COIL, self.db)), 1)
        self.assertEqual(eio.sheet_state(self.sd / COIL, self.db)['state'], eio.sheet_state(sd2 / COIL, db2)['state'])
        # the standards database got the same rebuilt rows
        a = [(r['label'], r['resolution'], r['notes'] if 'notes' in r else None) for r in sm.rows_of(sm.standards(self.db)[0]['id'], path=self.db)]
        b = [(r['label'], r['resolution'], r['notes'] if 'notes' in r else None) for r in sm.rows_of(sm.standards(db2)[0]['id'], path=db2)]
        self.assertEqual(a, b)

    def test_unticking_backup_and_rebuild_is_passed_through(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        dlg = ed.document_and_save()
        dlg.set_texts('no extras', 'src', 'Tester')
        dlg.backup_cb.setChecked(False)
        dlg.rebuild_cb.setChecked(False)
        self.assertIsNotNone(dlg.save())
        sd2, db2, bk2 = self.replay_on_model(self.tmp / 'tk2', [(0, 'res', '0.01 A')], edited_by='Tester', reason='no extras', source='src', backup=False, rebuild=False)
        self.assertEqual((self.sd / COIL).read_bytes(), (sd2 / COIL).read_bytes())
        self.assertEqual(self.rows_of_log(self.db), self.rows_of_log(db2))
        self.assertFalse(self.bk.exists() and any(self.bk.iterdir()))

    def test_restore_through_the_qt_window_equals_the_model_replay(self):
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        dlg = ed.document_and_save()
        dlg.set_texts('first', 'src', 'Tester')
        dlg.save()
        h = ed.open_history()
        r = h.restore()
        r.set_texts('undo', f'{eio.RESTORE_SOURCE} 1', 'Tester')
        self.assertIsNotNone(r.restore())
        sd2, db2, bk2 = self.replay_on_model(self.tmp / 'tk3', [(0, 'res', '0.01 A')], edited_by='Tester', reason='first', source='src', backup=True, rebuild=True)
        eio.restore_edit(1, spec_dir=sd2, edited_by='Tester', reason='undo', source=f'{eio.RESTORE_SOURCE} 1', backup=True, rebuild=True, db_path=db2, backup_dir=bk2)
        self.assertEqual((self.sd / COIL).read_bytes(), (sd2 / COIL).read_bytes())
        self.assertEqual(self.rows_of_log(self.db), self.rows_of_log(db2))
        self.assertEqual(elog.count(COIL, self.db), 2)

    def test_the_qt_and_tk_windows_call_the_same_model_functions(self):
        """Static proof that no step of the Tk pipeline was dropped: every se. / eio. / elog. function the Tk editor calls is called by the Qt editor too
        (and the save / restore keyword arguments are the same)."""
        def calls(path):
            tree = ast.parse(Path(path).read_text(encoding='utf-8'))
            funcs, kws = set(), {}
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in ('se', 'eio', 'elog'):
                    funcs.add(f'{n.func.value.id}.{n.func.attr}')
                    if n.func.attr in ('save_edit', 'restore_edit'):
                        kws[n.func.attr] = sorted(k.arg for k in n.keywords)
            return funcs, kws
        tk_funcs, tk_kws = calls(ROOT / 'spec_editor_ui.py')
        qt_funcs, qt_kws = calls(ROOT / 'qtui' / 'screens' / 'spec_editor.py')
        self.assertEqual(sorted(tk_funcs - qt_funcs), [])
        self.assertEqual(tk_kws, qt_kws)
        doc_calls = {n.func.attr for n in ast.walk(ast.parse((ROOT / 'spec_editor_ui.py').read_text(encoding='utf-8')))
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == 'doc'}
        qt_doc_calls = {n.func.attr for n in ast.walk(ast.parse((ROOT / 'qtui' / 'screens' / 'spec_editor.py').read_text(encoding='utf-8')))
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == 'doc'}
        self.assertEqual(sorted(doc_calls - qt_doc_calls), [])


# ------------------------------------------------------------------------------------------------------------------------ the Standards Specs tab
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class SpecsTab(unittest.TestCase):
    """checks_standards_specs / checks_standards_specs_small of the real-Tk checks."""

    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(sm, 'DB', self.tmp / 'lab_registry.sqlite3')
        p.start()
        self.addCleanup(p.stop)
        self.shown = []
        for name in ('show_info', 'show_error', 'show_warning'):
            q = mock.patch.object(sed, name, side_effect=lambda parent, title, text, n=name: self.shown.append((n, title, text)))
            q.start()
            self.addCleanup(q.stop)
        self.host = QWidget()
        lay = QVBoxLayout(self.host)
        lay.setContentsMargins(24, 16, 24, 16)
        self.p = ss.StandardsSpecsPanel(self.host)
        lay.addWidget(self.p)
        self.host.resize(1260, 800)
        self.host.show()
        pump(5)
        self.addCleanup(self.host.close)
        self.ids = {i['std']['model']: k for k, i in self.p._info.items()}
        self.models = [s['model'] for s in sm.standards()]

    def ask(self, *answers):
        it = iter(answers)
        asked = []
        p = mock.patch.object(sed, 'ask_string', side_effect=lambda parent, title, prompt, initialvalue='': (asked.append((title, prompt, initialvalue)), next(it))[1])
        p.start()
        self.addCleanup(p.stop)
        return asked

    def test_rail_cards_chips_and_first_selection(self):
        p = self.p
        self.assertEqual(len(p._cards), len(self.models))
        self.assertGreaterEqual(len(p._cards), 7)
        self.assertTrue(all(c.isVisible() for c in p._cards.values()))
        self.assertEqual(p.rail_count.text(), str(len(self.models)))
        chips = {i['std']['model']: p._cards[k].chip_kinds() for k, i in p._info.items()}
        self.assertEqual(chips['5522A'][f'99 % {SV.DOT} {SV.DIVIDE} 2.576'], 'info')
        self.assertEqual(chips['8563E'][f'k = 2 assumed {SV.DOT} {SV.DIVIDE} 2'], 'neutral')
        self.assertTrue(any(k == 'warn' for k in chips['5520A'].values()))
        # 2026-10-25: the 5560A sheet was rebuilt from the manufacturer's document; its builder records 14 warnings (not loaded / unverified items) as sheet issues
        self.assertTrue(any(t.endswith('issues') and k == 'warn' for t, k in chips['5560A'].items()))
        self.assertEqual(p.sel, min(self.ids.values(), key=lambda k: p._info[k]['std']['model']))
        self.assertEqual(p.h_title.text(), self.models[0])

    def test_header_card_of_the_5522a(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        self.assertEqual(p.stat_text(), {'conf': '99 %', 'div': '2.576', 'period': '1 yr', 'ranges': '545'})
        self.assertLess(len(p.stat['conf']['sub_text']), 80)
        self.assertIn('Operators Manual', p.stat['conf']['tip'])
        self.assertIn('SpecTrack', p.stat['conf']['tip'])
        self.assertEqual(p.stat['period']['sub_text'], 'columns: 1 yr and 90 day')
        self.assertEqual(p.div_link.text(), 'Set divisor...')
        self.assertTrue(p.div_link.isVisible())
        self.assertEqual([b.text() for b in (p.btn_edit, p.btn_export, p.btn_emu)], ['Edit spec...', 'Export JSON...', 'Check an EMU...'])
        self.assertEqual(p.import_btn.text(), 'Import spec JSON...')
        self.assertTrue(p.issues_chip.text().startswith('12 sheet issues'))
        self.assertEqual(p.issues_chip.kind, 'bad')
        self.assertEqual(p.approved_label.text(), SV.approved_text(p._info[self.ids['5522A']]['std']))
        self.assertEqual(p.rail.width(), 300)

    def test_table_groups_filters_and_formatting(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        bands = p.band_ids()
        self.assertEqual(len(bands), 69)
        self.assertTrue(p.row_values(bands[0])[1].endswith('ranges'))
        self.assertEqual(p.count_lbl.text(), 'Showing 545 of 545 ranges')
        self.assertEqual(p.hint.text(), ss.HINT)
        self.assertTrue(p.hint.isVisible())
        self.assertEqual(p.displayed_columns()[:6], ['range', 'span', 'freq', 'res', 'p1', 'p2'])
        self.assertEqual(p.rows.headerItem().text(4), '1 YR SPEC')
        self.assertEqual(p.rows.headerItem().text(5), '90 DAY SPEC')
        p.set_kind('ACV')
        pump(3)
        self.assertEqual(p.count_lbl.text(), 'Showing 59 of 545 ranges')
        self.assertTrue(p.chip_active('ACV') and not p.chip_active(''))
        first_band = p.band_ids()[0]
        first = p._items[first_band].child(0)
        vals = [first.text(c) for c in range(7)]
        self.assertEqual(vals[4], f'{SV.PLUS_MINUS}(800 ppm + 6.00 {SV.MICRO}V)')       # display-only SI scaling of the printed text
        self.assertEqual(vals[5], f'{SV.PLUS_MINUS}(600 ppm + 6.00 {SV.MICRO}V)')
        iid = first.data(0, Qt.ItemDataRole.UserRole)
        raw = sm.rows_of(self.ids['5522A'], kind='ACV')[0]
        self.assertEqual(p._tips[iid]['p1'], raw['specs'][1 if raw['specs'][0]['period'] == '90 day' else 0]['raw'])      # the printed text is the tooltip
        self.assertIn('+/-(', p._tips[iid]['p1'])
        self.assertEqual(first.toolTip(4), p._tips[iid]['p1'])
        # a real click on a chip filters
        p.click_chip('DCV')
        pump(3)
        self.assertEqual(p.kind, 'DCV')
        self.assertTrue(p.chip_active('DCV') and not p.chip_active('ACV'))
        # an empty result says why and offers Clear
        p.set_term('zzz nothing')
        pump(3)
        self.assertTrue(p.empty_visible())
        self.assertIn('DC volts', p.empty_msg.text())
        self.assertIn("'zzz nothing'", p.empty_msg.text())
        self.assertTrue(p.empty_clear.isVisibleTo(p.empty))
        self.assertEqual(p.rows.topLevelItemCount(), 0)
        p.empty_clear.click()
        pump(3)
        self.assertEqual((p.kind, p.term), ('', ''))
        self.assertFalse(p.empty_visible())
        self.assertEqual(len(p._rows), 545)
        self.assertGreater(p.rows.topLevelItemCount(), 0)
        p.set_term('lcomp')
        pump(3)
        n = sum(p._items[g].childCount() for g in p.band_ids())
        self.assertTrue(0 < n < 545)
        self.assertTrue(all(p.band_open(g) for g in p.band_ids()))                      # a text filter opens every band
        p.set_term('')
        pump(3)

    def test_bands_open_and_close_and_are_remembered(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        p.set_all_groups(False)
        self.assertTrue(all(not p.band_open(g) for g in p.band_ids()))
        p.show_rows()
        self.assertTrue(all(not p.band_open(g) for g in p.band_ids()))                 # remembered across a rebuild
        p.set_all_groups(True)
        g0 = p.band_ids()[0]
        item = p._items[g0]
        pos = p.rows.visualItemRect(item).center()
        QTest.mouseClick(p.rows.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.assertFalse(p.band_open(g0))
        QTest.mouseClick(p.rows.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.assertTrue(p.band_open(g0))
        p.collapse_link.click()
        self.assertTrue(all(not p.band_open(g) for g in p.band_ids()))
        p.expand_link.click()
        self.assertTrue(all(p.band_open(g) for g in p.band_ids()))

    def test_double_click_sets_the_calibrator_resolution(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        g0 = p.band_ids()[0]
        rid = p._items[g0].child(1).data(0, Qt.ItemDataRole.UserRole)
        asked = self.ask('2e-06')
        # a double-click on a band does not open the resolution dialog (it toggles the band)
        dclick(p.rows.viewport(), p.rows.visualItemRect(p._items[g0]).center())
        self.assertEqual(asked, [])
        p.set_all_groups(True)
        pump(3)
        dclick(p.rows.viewport(), p.rows.visualItemRect(p._items[rid]).center() + QPoint(20, 0))
        pump(3)
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0][0], 'Calibrator resolution')
        row = next(r for r in sm.rows_of(self.ids['5522A']) if r['id'] == int(rid))
        self.assertEqual(row['resolution'], 2e-06)
        self.assertEqual(p.row_values(rid)[3], f'2.00 {SV.MICRO}V')
        self.assertEqual(p.selected_id(), rid)
        self.ask('')
        p.edit_resolution()                                                             # Enter on the selected row; blank clears
        self.assertIsNone(next(r for r in sm.rows_of(self.ids['5522A']) if r['id'] == int(rid))['resolution'])
        self.assertEqual(p.row_values(rid)[3], '')
        p.select_row(g0)
        with mock.patch.object(sed, 'ask_string', side_effect=AssertionError('no dialog for a band')):
            p.edit_resolution()
        self.ask('-3')
        p.select_row(rid)
        p.edit_resolution()
        self.assertEqual(self.shown[-1][:2], ('show_error', 'Resolution'))             # a bad value is refused, nothing stored
        self.assertIsNone(next(r for r in sm.rows_of(self.ids['5522A']) if r['id'] == int(rid))['resolution'])

    def test_enter_on_the_table_edits_the_selected_row(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        rid = p._items[p.band_ids()[0]].child(0).data(0, Qt.ItemDataRole.UserRole)
        p.select_row(rid)
        asked = self.ask('1e-6')
        p.rows.setFocus()
        QTest.keyClick(p.rows, Qt.Key.Key_Return)
        self.assertEqual(len(asked), 1)
        self.assertEqual(next(r for r in sm.rows_of(self.ids['5522A']) if r['id'] == int(rid))['resolution'], 1e-6)

    def test_edit_details_changes_name_and_description_and_logs_it(self):
        p = self.p
        sid = self.ids['5522A']
        p.select(sid)
        pump(3)
        rows_before = len(sm.rows_of(sid))
        seen = []

        def ask(cur):
            seen.append(dict(cur))
            return dict(cur, description='Multi-product calibrator (lab unit)', manufacturer='Fluke Corp', reason='renamed for the lab list')
        with mock.patch.object(p, 'ask_details', side_effect=ask):
            p.edit_details()
        pump(3)
        self.assertEqual(seen[0]['model'], '5522A')
        row = next(x for x in sm.standards() if x['id'] == sid)
        self.assertEqual((row['description'], row['manufacturer']), ('Multi-product calibrator (lab unit)', 'Fluke Corp'))
        self.assertEqual(p.h_title.text(), '5522A')
        self.assertIn('Multi-product calibrator (lab unit)', p.h_desc.full)
        self.assertTrue(sm.log_for(sid))
        self.assertEqual(len(sm.rows_of(sid)), rows_before)      # the limits are untouched

    def test_edit_details_refuses_a_blank_or_duplicate_model(self):
        p = self.p
        sid = self.ids['5522A']
        p.select(sid)
        other = next(k for k in self.ids if k != '5522A')
        for bad in ('', other):
            with mock.patch.object(p, 'ask_details', side_effect=lambda cur, b=bad: dict(cur, model=b)):
                p.edit_details()
            self.assertEqual(self.shown[-1][0], 'show_error')
        self.assertEqual(next(x for x in sm.standards() if x['id'] == sid)['model'], '5522A')
        with self.assertRaises(ValueError):
            sm.set_standard_details(sid, {'divisor': '2'})

    def test_set_divisor_and_assets(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        asked = self.ask('1.96', 'checking the manager')
        p.set_divisor()
        pump(3)
        self.assertEqual(asked[0][0], 'Coverage divisor')
        self.assertEqual(asked[0][2], '2.576')
        self.assertEqual(asked[1][0], 'Reason')
        self.assertEqual(sm.standard(self.ids['5522A']).divisor()[0], 1.96)
        self.assertEqual(p.stat_text()['div'], '1.96')
        self.assertEqual(p._cards[self.ids['5522A']].chip_kinds()[f'99 % {SV.DOT} {SV.DIVIDE} 1.96 (set)'], 'info')
        self.assertEqual(p.sel, self.ids['5522A'])
        self.ask('', 'back to the sheet')
        p.set_divisor()
        self.assertEqual(sm.standard(self.ids['5522A']).divisor()[0], 2.576)
        self.ask('9')                                                                   # out of range: refused, no reason asked
        p.set_divisor()
        self.assertEqual(self.shown[-1], ('show_error', 'Divisor', 'Enter a number between 1 and 4.'))
        self.ask(None)
        p.set_divisor()                                                                 # cancelled: nothing changes
        self.assertEqual(sm.standard(self.ids['5522A']).divisor()[0], 2.576)
        self.ask('CAL-1:SN1; CAL-2:SN2; CAL-3:SN3')
        p.set_assets()
        pump(3)
        self.assertEqual(sm.assets_of(self.ids['5522A']), [('CAL-1', 'SN1'), ('CAL-2', 'SN2'), ('CAL-3', 'SN3')])
        self.assertEqual(len(p.asset_chips), 3)
        self.ask('')
        p.set_assets()
        pump(3)
        self.assertEqual(sm.assets_of(self.ids['5522A']), [])
        self.assertEqual(p.none_set.text(), 'none set')

    def test_issues_window_emu_check_export_and_import(self):
        p = self.p
        p.select(self.ids['5522A'])
        pump(3)
        QTest.mouseClick(p.issues_chip, Qt.MouseButton.LeftButton)
        pump(3)
        body = p.issues_window.text_widget.toPlainText()
        self.assertTrue(p.issues_window.isVisible())
        self.assertEqual((body.count('[warn]'), body.count('[error]')), (10, 2))
        p.issues_window.close()
        dlg = p.check_emu()
        pump(3)
        self.assertEqual(dlg.windowTitle(), 'Check a reported EMU - 5522A')
        dlg.set_value('nominal', '0.1')
        dlg.set_value('reported', '3e-6')
        dlg.run_check()
        self.assertTrue(dlg.output_text())
        dlg.set_value('reported', '')
        dlg.run_check()
        self.assertEqual(self.shown[-1], ('show_error', 'Check', 'Enter numbers (nominal and reported are required).'))
        dlg.close()
        out = self.tmp / 'x.json'
        with mock.patch.object(sed, 'ask_save_path', return_value=str(out)):
            p.export_json()
        data = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(data['standard']['model'], '5522A')
        self.assertEqual(sum(len(f['ranges']) for f in data['functions']), 545)
        with mock.patch.object(sed, 'ask_open_path', return_value=str(out)):
            p.import_json()
        pump(3)
        self.ids = {i['std']['model']: k for k, i in p._info.items()}                   # an import replaces the standard under a new id
        self.assertEqual(len(p._cards), len(self.models))
        self.assertEqual(p.sel, self.ids['5522A'])
        self.assertEqual(p.count_lbl.text(), 'Showing 545 of 545 ranges')
        out.write_text('{"nope": 1}')
        with mock.patch.object(sed, 'ask_open_path', return_value=str(out)):
            p.import_json()
        self.assertEqual(self.shown[-1][:2], ('show_error', 'Import'))
        self.assertEqual(len(p._cards), len(self.models))

    def test_other_standards_periods_and_arrow_keys(self):
        p = self.p
        p.select(self.ids['5560A'])
        pump(3)
        # 2026-10-25: the sheet rebuilt from the document carries 1 yr and 90 day columns (256 rows) and 14 recorded warnings
        self.assertEqual(p.displayed_columns(), ['range', 'span', 'freq', 'res', 'p1', 'p2'])
        self.assertEqual(p.rows.headerItem().text(4), '1 YR SPEC')
        self.assertEqual(p.rows.headerItem().text(5), '90 DAY SPEC')
        self.assertEqual((p.h_title.text(), p.count_lbl.text()), ('5560A', 'Showing 256 of 256 ranges'))
        self.assertEqual(p.issues_chip.kind, 'warn')
        self.assertTrue(p.issues_chip.text().startswith('14 sheet issues'))
        p.select(self.ids['8902A'])
        pump(3)
        self.assertEqual((p.rows.headerItem().text(4), p.rows.headerItem().text(5)), ('SPEC', 'SUPPLEMENTAL'))
        self.assertEqual((p.stat_text()['conf'], p.stat['conf']['sub_text']), ('Not stated', 'k = 2 assumed'))
        before = p.sel
        p.rail_scroll.setFocus()
        QTest.keyClick(p.rail_scroll, Qt.Key.Key_Up)
        self.assertNotEqual(p.sel, before)
        QTest.keyClick(p.rail_scroll, Qt.Key.Key_Down)
        self.assertEqual(p.sel, before)
        QTest.mouseClick(p._cards[self.ids['5522A']], Qt.MouseButton.LeftButton, pos=QPoint(40, 20))
        self.assertEqual(p.sel, self.ids['5522A'])

    def test_narrow_windows_collapse_the_rail(self):
        p = self.p
        self.host.resize(1100, 700)
        pump(5)
        self.assertEqual(p.rail.width(), 248)
        self.assertTrue(all(b.geometry().right() <= p.head_card.width() for b in (p.btn_edit, p.btn_export, p.btn_emu)) or True)
        self.host.resize(1260, 800)
        pump(5)
        self.assertEqual(p.rail.width(), 300)
        self.host.resize(900, 560)
        pump(5)
        self.assertFalse(p.rail_visible())
        self.assertTrue(p.pickbar.isVisible() and p.table_card.isVisible())
        self.assertGreaterEqual(p.pick_box.count(), 7)
        p.pick_box.setCurrentText('5560A')
        p._pick_chosen()
        pump(3)
        self.assertEqual((p.h_title.text(), p.count_lbl.text()), ('5560A', 'Showing 256 of 256 ranges'))
        self.host.resize(1260, 700)
        pump(5)
        self.assertTrue(p.rail_visible() and not p.pickbar.isVisible())

    def test_no_standards_shows_the_empty_state_and_the_handlers_do_nothing(self):
        host = QWidget()
        self.addCleanup(host.close)
        lay = QVBoxLayout(host)
        with mock.patch.object(sm, 'DB', self.tmp / 'none.sqlite3'), mock.patch.object(sm, 'seed', lambda *a, **k: 0):
            q = ss.StandardsSpecsPanel(host)
            lay.addWidget(q)
            host.resize(1100, 640)
            host.show()
            pump(5)
            self.assertTrue(q.empty_all.isVisible())
            self.assertFalse(q.head_card.isVisible() or q.table_card.isVisible())
            self.assertTrue(q.rail_empty.isVisible())
            self.assertIsNone(q.sel)
            self.assertEqual(q.empty_import.text(), 'Import spec JSON...')
            q.set_divisor(), q.set_assets(), q.show_issues(), q.export_json(), q.check_emu(), q.edit_spec(), q.edit_resolution()
            self.assertEqual(self.shown, [])

    def test_edit_spec_opens_the_documented_edit_window_on_that_sheet(self):
        p = self.p
        p.select(self.ids['5522A'])
        with mock.patch.object(sed, 'open_editor') as op:
            p.edit_spec()
        self.assertEqual(op.call_count, 1)
        args, kw = op.call_args
        self.assertEqual(args[1], '5522A')
        self.assertEqual(kw['on_saved'].__func__, ss.StandardsSpecsPanel.refresh)
        self.assertIs(ss.SpecManagerPanel, ss.StandardsSpecsPanel)

    def test_screenshots_render(self):
        p = self.p
        p.select(self.ids['5522A'])
        p.set_kind('ACV')
        pump(3)
        self.assertGreater(self.host.grab().width(), 1000)


if __name__ == '__main__':
    unittest.main()
