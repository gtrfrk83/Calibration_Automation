"""qtui.table.DataTable: sorting, filtering, selection, editing hooks, clipboard, row tone, uniform rows, and a speed sanity check.
Skipped when PySide6 is not importable.  Headless."""
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QHeaderView
    from qtui import app
    from qtui.table import BADGE_ROLE, Column, DataTable, PROGRESS_ROLE, ROW_ROLE


def rows(n=8):
    names = ['b-12', 'a-3', 'B-1', 'c-20', 'a-10', 'd', 'e', 'f']
    return [dict(id=i, name=names[i % len(names)], val=(i * 7) % 5 + 0.5 * i, status=['Ready', 'Failed', 'Needs review'][i % 3], pick=False, std='A', done=i / 10)
            for i in range(n)]


def columns():
    return [Column('id', '#', 40, align='right'), Column('name', 'Name', 120, natural=True), Column('val', 'Value', 80, align='right', fmt=lambda v: f'{v:.2f}'),
            Column('status', 'Status', 100, kind='badge', badge_map={'Ready': 'good', 'Failed': 'bad', 'Needs review': 'warn'}),
            Column('pick', '', 30, kind='checkbox', editable=True), Column('std', 'Std', 80, kind='combo', editable=True, choices=['A', 'B']),
            Column('done', 'Done', 80, kind='progress')]


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def make(self, n=8, **kw):
        t = DataTable(columns(), rows(n), row_key=lambda r: r['id'], **kw)
        t.resize(900, 400)
        t.show()
        self.app.processEvents()
        return t

    def names(self, t):
        return [r['name'] for r in t.visible_rows()]

    def test_sort_text_number_descending_and_natural(self):
        t = self.make()
        t.sort_by('name')
        self.assertEqual(self.names(t), ['a-3', 'a-10', 'B-1', 'b-12', 'c-20', 'd', 'e', 'f'])          # natural, case-insensitive: a-3 before a-10
        t.sort_by('name', True)
        self.assertEqual(self.names(t)[0], 'f')
        t.sort_by('val')
        vals = [r['val'] for r in t.visible_rows()]
        self.assertEqual(vals, sorted(vals))
        t.sort_by('val', True)
        vals = [r['val'] for r in t.visible_rows()]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_header_click_toggles_direction(self):
        t = self.make()
        i = t.column_index('val')
        t._header_clicked(i)
        self.assertEqual(t.sort_state(), ('val', False))
        t._header_clicked(i)
        self.assertEqual(t.sort_state(), ('val', True))

    def test_empty_values_sort_last_both_ways(self):
        rs = rows(4)
        rs[1]['val'] = None
        t = DataTable(columns(), rs)
        t.sort_by('val')
        self.assertIsNone(t.visible_rows()[-1]['val'])
        t.sort_by('val', True)
        self.assertIsNone(t.visible_rows()[-1]['val'])

    def test_filter_words_and_predicate(self):
        t = self.make()
        t.set_filter_text('a')
        self.assertTrue(all('a' in ' '.join(str(v) for v in (r['name'], r['status'], r['std'])).lower() for r in t.visible_rows()))
        t.set_filter_text('failed')
        self.assertEqual({r['status'] for r in t.visible_rows()}, {'Failed'})
        t.set_filter_text('failed a-')
        self.assertTrue(all(r['status'] == 'Failed' and r['name'].lower().startswith('a-') for r in t.visible_rows()))
        t.set_filter_text('')
        self.assertEqual(len(t.visible_rows()), 8)
        t.set_predicate(lambda r: r['id'] % 2 == 0)
        self.assertEqual([r['id'] for r in t.visible_rows()], [0, 2, 4, 6])
        t.set_filter_text('ready')
        self.assertEqual([r['id'] for r in t.visible_rows()], [0, 6])
        counts = []
        t.countsChanged.connect(lambda v, n: counts.append((v, n)))
        t.set_predicate(None)
        t.set_filter_text('')
        self.assertEqual(counts[-1], (8, 8))

    def test_selection_multi_and_survives_sort_and_filter(self):
        t = self.make()
        got = []
        t.selectionChangedRows.connect(got.append)
        t.select_rows([t.rows()[1], t.rows()[4]])
        self.app.processEvents()
        self.assertEqual([r['id'] for r in t.selected_rows()], [1, 4])
        self.assertEqual(sorted(r['id'] for r in got[-1]), [1, 4])
        t.sort_by('name', True)
        self.assertEqual(sorted(r['id'] for r in t.selected_rows()), [1, 4])
        t.set_filter_text('zzz')
        self.assertEqual(t.selected_rows(), [])
        t.set_filter_text('')
        t.clearSelection()
        t.selectAll()
        self.assertEqual(len(t.selected_rows()), 8)
        self.assertEqual(t.selected_count(), 8)

    def test_set_rows_keeps_selection_by_key(self):
        t = self.make()
        t.select_rows([t.rows()[2]])
        t.set_rows(rows(8))                                  # new objects, same ids
        self.assertEqual([r['id'] for r in t.selected_rows()], [2])

    def test_single_select_mode(self):
        t = DataTable(columns(), rows(), multi=False)
        t.select_rows(t.rows()[:3])
        self.assertLessEqual(len(t.selected_rows()), 1)

    def test_copy_selection_tsv(self):
        t = self.make()
        t.sort_by('id')
        t.select_rows([t.rows()[0], t.rows()[2]])
        text = t.copy_selection(header=True)
        lines = text.split('\n')
        self.assertEqual(lines[0].split('\t')[:3], ['#', 'Name', 'Value'])
        self.assertEqual(len(lines), 3)
        self.assertEqual(QGuiApplication.clipboard().text(), text)
        self.assertEqual(lines[1].split('\t')[1], t.rows()[0]['name'])
        self.assertEqual(lines[1].split('\t')[2], f"{t.rows()[0]['val']:.2f}")       # the formatter's text, as shown

    def test_cell_data_roles(self):
        t = self.make()
        m = t.proxy
        ix = lambda r, key: m.index(r, t.column_index(key))        # noqa: E731
        self.assertEqual(ix(0, 'status').data(BADGE_ROLE), 'good')
        self.assertEqual(ix(1, 'status').data(BADGE_ROLE), 'bad')
        self.assertAlmostEqual(ix(3, 'done').data(PROGRESS_ROLE), 0.3)
        self.assertIs(ix(2, 'id').data(ROW_ROLE).row, t.rows()[2])
        self.assertIs(t.row_of(ix(2, 'id')), t.rows()[2])
        self.assertEqual(ix(0, 'val').data(Qt.ItemDataRole.TextAlignmentRole) & Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignRight)

    def test_row_tone_colours(self):
        t = self.make(row_tone=lambda r: {'Failed': 'fail', 'Needs review': 'warn', 'Ready': 'pass'}[r['status']])
        bg = [t.proxy.index(i, 1).data(Qt.ItemDataRole.BackgroundRole) for i in range(3)]
        self.assertTrue(all(b is not None for b in bg))
        self.assertEqual(len({b.name() for b in bg}), 3)                       # pass / fail / warn differ
        self.assertIsNone(t.proxy.index(0, 1).data(Qt.ItemDataRole.ForegroundRole))          # pass keeps normal text
        self.assertIsNotNone(t.proxy.index(1, 1).data(Qt.ItemDataRole.ForegroundRole))       # fail is red text as well as tint

    def test_edit_hook_reject_accept_and_signal(self):
        t = self.make()
        got = []
        t.cellEdited.connect(lambda *a: got.append(a))
        t.set_edit_hook(lambda row, key, old, new: new != 'B')
        ix = t.proxy.index(0, t.column_index('std'))
        self.assertFalse(t.proxy.setData(ix, 'B'))
        self.assertEqual(t.rows()[0]['std'], 'A')
        self.assertTrue(t.proxy.setData(ix, 'C'))
        self.assertEqual(t.rows()[0]['std'], 'C')
        self.assertEqual(got[-1][1:], ('std', 'A', 'C'))
        self.assertFalse(t.proxy.setData(t.proxy.index(0, t.column_index('name')), 'x'))      # not editable

    def test_checkbox_toggle_applies_to_all_selected_rows(self):
        t = self.make()
        t.select_rows(t.rows()[:3])
        t.toggle_check(t.proxy.index(1, t.column_index('pick')), True)
        self.assertEqual([r['pick'] for r in t.rows()[:4]], [True, True, True, False])

    def test_uniform_row_heights(self):
        t = self.make()
        vh = t.verticalHeader()
        self.assertEqual(vh.sectionResizeMode(0), QHeaderView.ResizeMode.Fixed)
        self.assertEqual({t.rowHeight(i) for i in range(8)}, {vh.defaultSectionSize()})

    def test_frozen_first_column(self):
        t = DataTable(columns(), rows(), frozen=True)
        t.resize(300, 300)
        t.show()
        self.app.processEvents()
        fv = t._frozen_view
        self.assertEqual(fv.width(), t.columnWidth(0))
        self.assertTrue(all(fv.isColumnHidden(c) for c in range(1, 7)))
        t.setColumnWidth(0, 90)
        self.assertEqual(fv.columnWidth(0), 90)
        self.assertIs(fv.selectionModel(), t.selectionModel())

    def test_50k_rows_are_fast_enough(self):
        n = 50000
        rs = [dict(id=i, name=f'Proc {(i * 7919) % n:06d}', val=(i * 37 % 1000) / 7, status='Ready', pick=False, std='A', done=0.5) for i in range(n)]
        t = DataTable(columns(), row_key=lambda r: r['id'])
        t.resize(900, 500)
        t.show()
        t0 = time.perf_counter()
        t.set_rows(rs)
        self.app.processEvents()
        t_load = time.perf_counter() - t0
        t0 = time.perf_counter()
        t.sort_by('name')
        self.app.processEvents()
        t_sort = time.perf_counter() - t0
        t0 = time.perf_counter()
        t.set_filter_text('0042')
        self.app.processEvents()
        t_filter = time.perf_counter() - t0
        self.assertEqual(len(t.visible_rows()), sum('0042' in r['name'] or '0042' in str(r['id']) or '0042' in f"{r['val']:.2f}" for r in rs))        # any searchable column
        # generous bounds (a slow CI box): the point is that none of these is seconds
        self.assertLess(t_load, 2.0)
        self.assertLess(t_sort, 3.0)
        self.assertLess(t_filter, 3.0)


if __name__ == '__main__':
    unittest.main()
