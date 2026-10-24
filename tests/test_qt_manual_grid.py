"""Qt twin of manual_grid (qtui.screens.manual_grid): the scenario of tests/real_tk_checks.py (manual run window, typed readings in the point grid) on a fake
run app with the real DataTable.  Skipped when PySide6 is not importable.

    <venv python> -m unittest tests.test_qt_manual_grid
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from qtui import app as qapp
    from qtui.screens.manual_grid import GridEntry
    from qtui.table import Column, DataTable
    QAPP = qapp.create_app()


class Var:
    def __init__(self):
        self.v = ''

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class FakeApp:
    """The parts of dsb_runtime.DsbApp the grid uses: points, results, type_reading (pad to 4 decimals, judge against low..high), status, mode."""
    mode_label = 'As Found'
    is_left = False
    busy = False
    virtual = False

    def __init__(self, n=6):
        self.points = [dict(id=f'p{i}', n=i, test='numeric', low=f'{i * 1.0 - 0.001 * i:.4f}', high=f'{i * 1.0 + 0.001 * i:.4f}', display_unit='V') for i in range(1, n + 1)]
        self.by_id = {p['id']: p for p in self.points}
        self.results, self.left = {}, {}
        self.status = Var()

    def type_reading(self, p, text):
        t = text.strip()
        try:
            v = float(t)
        except ValueError:
            raise ValueError('That is not a number.')
        if v != v or v in (float('inf'), float('-inf')):
            raise ValueError('That is not a number.')
        entered = f'{v:.4f}' if t.replace('-', '').replace('.', '').isdigit() and len(t.split('.')[-1]) < 4 else t
        store = self.left if self.is_left else self.results
        store[p['id']] = dict(entered=entered, result='PASS' if float(p['low']) <= v <= float(p['high']) else 'FAIL', source='typed')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ManualGrid(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        cols = [Column('n', 'Point', width=60, getter=lambda r: str(r['n'])),
                Column('found', 'As Found', width=120, getter=lambda r: (self.app.results.get(r['id']) or {}).get('entered', '')),
                Column('left', 'As Left', width=120, getter=lambda r: (self.app.left.get(r['id']) or {}).get('entered', ''))]
        self.view = DataTable(cols, self.app.points, row_key=lambda r: r['id'])
        self.view.resize(520, 300)
        self.view.show()
        QAPP.processEvents()
        self.ge = GridEntry(self.app, self.view)
        self.addCleanup(self.view.close)

    def select(self, iid):
        self.view.select_rows([next(r for r in self.app.points if r['id'] == iid)])
        QAPP.processEvents()

    def test_enter_opens_typed_value_is_padded_judged_and_next_point_opens(self):
        self.select('p2')
        self.view.setFocus()
        QTest.keyClick(self.view, Qt.Key.Key_Return)
        self.assertTrue(self.ge.is_open() and self.ge.iid == 'p2')
        QTest.keyClicks(self.ge.entry, '2')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Return)
        rec = self.app.results['p2']
        self.assertEqual((rec['entered'], rec['result'], rec['source']), ('2.0000', 'PASS', 'typed'))
        self.assertTrue(self.ge.is_open() and self.ge.iid == 'p3', 'Enter saved and opened the NEXT point')
        st = self.app.status.get()
        self.assertIn('accept 2.9970 to 3.0030 V', st)
        self.assertIn('Point 2 saved: 2.0000 V PASS', st)

    def test_nan_is_refused_and_the_box_stays(self):
        self.ge.open('p3')
        QTest.keyClicks(self.ge.entry, 'nan')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Return)
        self.assertTrue(self.ge.is_open() and self.ge.iid == 'p3' and 'p3' not in self.app.results)
        self.assertIn('number', self.app.status.get().lower())
        self.assertEqual(self.ge.entry.property('invalid'), True)

    def test_out_of_limit_is_stored_as_fail_and_esc_closes(self):
        self.ge.open('p3')
        self.ge.var.set('3.05')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Return)
        self.assertEqual(self.app.results['p3']['result'], 'FAIL')
        self.assertTrue(self.ge.is_open())
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Escape)
        self.assertFalse(self.ge.is_open())
        self.assertEqual(self.app.status.get(), 'Reading box closed; nothing was saved for that point.')

    def test_typing_on_a_selected_point_opens_the_box_with_that_character(self):
        self.select('p4')
        self.view.setFocus()
        QTest.keyClick(self.view, Qt.Key.Key_5)
        self.assertTrue(self.ge.is_open())
        self.assertEqual(self.ge.var.get(), '5')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Escape)

    def test_up_down_and_tab_move_and_save(self):
        self.ge.open('p3')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Up)
        self.assertEqual(self.ge.iid, 'p2')
        self.ge.var.set('2')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Tab)
        self.assertEqual((self.ge.iid, self.app.results['p2']['entered']), ('p3', '2.0000'))
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Down)                # an empty box just moves on
        self.assertEqual(self.ge.iid, 'p4')
        self.assertNotIn('p3', self.app.results)

    def test_first_and_last_point_messages(self):
        self.ge.open('p1')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Up)
        self.assertEqual(self.app.status.get(), 'That is the first point.')
        self.assertFalse(self.ge.is_open())
        self.ge.open('p6')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_Return)
        self.assertEqual(self.app.status.get(), 'That was the last point.')

    def test_as_left_goes_to_its_own_column_and_keeps_as_found(self):
        self.ge.open('p1')
        self.ge.var.set('1')
        self.ge.commit()
        self.ge.close()
        self.app.is_left, self.app.mode_label = True, 'As Left'
        self.assertTrue(self.ge.open('p1'))
        self.ge.var.set('1.0001')
        self.ge.commit()
        self.assertEqual((self.app.left['p1']['entered'], self.app.left['p1']['result']), ('1.0001', 'PASS'))
        self.assertEqual(self.app.results['p1']['entered'], '1.0000')
        self.assertIn('(As Left)', self.app.status.get())

    def test_no_typing_while_a_run_is_in_progress(self):
        self.app.busy = True
        self.assertFalse(self.ge.open('p1'))
        self.assertIn('A run is in progress', self.app.status.get())

    def test_grid_allows_blocks_a_point_with_the_reason(self):
        self.app.grid_allows = lambda p: (p['id'] != 'p2', 'This point is read by the instrument.')
        self.assertFalse(self.ge.open('p2'))
        self.assertEqual(self.app.status.get(), 'This point is read by the instrument.')
        self.assertTrue(self.ge.open('p3'))

    def test_demo_f9_fills_a_simulated_reading_only_in_demo(self):
        self.ge.open('p2')
        QTest.keyClick(self.ge.entry, Qt.Key.Key_F9)
        self.assertEqual(self.ge.var.get(), '')
        self.ge.close()
        self.app.virtual = True
        self.app.virtual_failures = lambda: False
        self.ge.open('p2')
        self.assertIn('DEMO: F9 fills a simulated reading.', self.app.status.get())
        QTest.keyClick(self.ge.entry, Qt.Key.Key_F9)
        self.assertNotEqual(self.ge.var.get(), '')
        float(self.ge.var.get())

    def test_scrolling_or_resizing_closes_the_box(self):
        self.ge.open('p2')
        self.view.resize(600, 320)
        QAPP.processEvents()
        self.assertFalse(self.ge.is_open())


if __name__ == '__main__':
    unittest.main()
