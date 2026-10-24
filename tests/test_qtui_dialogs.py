"""qtui.widgets: ModalDialog Esc / Enter / focus order / centring, MessageDialog, ProgressDialog, SegmentedFilter, Badge, Banner, SearchField.
Skipped when PySide6 is not importable.  Headless."""
import os
import sys
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
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QMainWindow, QWidget
    from qtui import app, theme
    from qtui.widgets import Badge, Banner, MessageDialog, ModalDialog, ProgressDialog, SearchField, SegmentedFilter, StatusLine, set_prop


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def dlg(self, parent=None):
        d = ModalDialog(parent, 'Title', subtitle='sub')
        self.e1, self.e2 = QLineEdit(), QLineEdit()
        d.body.addWidget(self.e1)
        d.body.addWidget(self.e2)
        self.cancel = d.add_button('Cancel', cancel=True)
        self.ok = d.add_button('OK', role='primary', default=True)
        d.show()
        self.app.processEvents()
        return d

    def test_escape_cancels(self):
        d = self.dlg()
        QTest.keyClick(d, Qt.Key.Key_Escape)
        self.assertFalse(d.isVisible())
        self.assertEqual(d.result_key, 'cancel')
        self.assertEqual(d.result(), 0)

    def test_enter_presses_the_default_button_also_from_a_field(self):
        d = self.dlg()
        self.e1.setFocus()
        QTest.keyClick(self.e1, Qt.Key.Key_Return)
        self.assertFalse(d.isVisible())
        self.assertEqual(d.result_key, 'ok')
        self.assertEqual(d.result(), 1)

    def test_enter_on_a_focused_cancel_button_cancels(self):
        d = self.dlg()
        self.cancel.setFocus()
        QTest.keyClick(d, Qt.Key.Key_Enter)
        self.assertEqual(d.result_key, 'cancel')

    def test_callback_false_keeps_the_dialog_open(self):
        d = ModalDialog(None, 'T')
        d.add_button('Save', role='primary', default=True, callback=lambda: False)
        d.show()
        QTest.keyClick(d, Qt.Key.Key_Return)
        self.assertTrue(d.isVisible())
        d.close()

    def test_default_button_has_focus_when_there_are_no_fields_and_fields_come_first_otherwise(self):
        d = ModalDialog(None, 'T')
        d.add_button('Cancel', cancel=True)
        ok = d.add_button('OK', role='primary', default=True)
        d.show()
        self.app.processEvents()
        self.assertIs(d.focusWidget(), ok)
        d.close()
        d = self.dlg()
        self.assertIs(d.focusWidget(), self.e1)
        order = []
        w = self.e1
        for _ in range(4):                              # follow the tab chain from the first field
            order.append(w)
            w = w.nextInFocusChain()
            while not (w.focusPolicy() & Qt.FocusPolicy.TabFocus) or not w.isVisible():
                w = w.nextInFocusChain()
        self.assertEqual(order[:4], [self.e1, self.e2, self.cancel, self.ok])
        d.close()

    def test_centred_on_parent(self):
        win = QMainWindow()
        win.resize(900, 600)
        win.move(100, 100)
        win.show()
        d = self.dlg(win)
        c1, c2 = d.frameGeometry().center(), win.frameGeometry().center()
        self.assertLessEqual(abs(c1.x() - c2.x()), 3)
        self.assertLessEqual(abs(c1.y() - c2.y()), 3)
        d.close()
        win.close()

    def test_message_dialog_single_ok_closes_on_escape_and_enter(self):
        for key in (Qt.Key.Key_Escape, Qt.Key.Key_Return):
            m = MessageDialog(None, 'error', 'Stopped', 'text')
            m.show()
            QTest.keyClick(m, key)
            self.assertFalse(m.isVisible())
            self.assertEqual(m.result_key, 'ok')

    def test_danger_dialog_cancel_key(self):
        m = MessageDialog(None, 'warning', 'HV', 'text', buttons=(('Cancel', 'cancel', None), ('Enable output', 'yes', 'danger')), cancel_key='cancel')
        m.show()
        QTest.keyClick(m, Qt.Key.Key_Escape)
        self.assertEqual(m.result_key, 'cancel')
        m = MessageDialog(None, 'warning', 'HV', 'text', buttons=(('Cancel', 'cancel', None), ('Enable output', 'yes', 'danger')), cancel_key='cancel')
        m.show()
        QTest.keyClick(m, Qt.Key.Key_Return)
        self.assertEqual(m.result_key, 'yes')

    def test_progress_dialog_escape_cancels_the_work_not_the_window(self):
        p = ProgressDialog(None, 'Working', 'x', maximum=10)
        hits = []
        p.cancelled.connect(lambda: hits.append(1))
        p.show()
        p.set_progress(4, message='y', detail='z')
        self.assertEqual(p.bar.value(), 4)
        self.assertEqual(p.message_label.text(), 'y')
        QTest.keyClick(p, Qt.Key.Key_Escape)
        self.assertTrue(p.isVisible())
        self.assertTrue(p.was_cancelled)
        self.assertEqual(hits, [1])
        p.finish()
        self.assertFalse(p.isVisible())
        self.assertEqual(p.result_key, 'cancel')

    def test_progress_indeterminate(self):
        p = ProgressDialog(None, 'Working', cancelable=False)
        self.assertEqual((p.bar.minimum(), p.bar.maximum()), (0, 0))
        p.show()
        QTest.keyClick(p, Qt.Key.Key_Escape)
        self.assertTrue(p.isVisible())                  # nothing to cancel: Esc does not close a running job
        p.finish()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def test_badge_kinds(self):
        b = Badge('x', 'good')
        self.assertEqual(b.property('badge'), 'good')
        b.set_kind('bogus')
        self.assertEqual(b.property('badge'), 'neutral')

    def test_segmented_filter_signal_counts_and_arrow_keys(self):
        f = SegmentedFilter([('a', 'All', 5), ('b', 'Bad', 2), ('c', 'Mine')])
        got = []
        f.currentChanged.connect(got.append)
        f.show()
        f.set_count('b', 3)
        self.assertEqual(f._buttons['b'].text(), 'Bad  3')
        QTest.mouseClick(f._buttons['b'], Qt.MouseButton.LeftButton)
        self.assertEqual((f.current(), got), ('b', ['b']))
        f._buttons['b'].setFocus()
        QTest.keyClick(f._buttons['b'], Qt.Key.Key_Right)
        self.assertEqual(f.current(), 'c')
        QTest.keyClick(f._buttons['c'], Qt.Key.Key_Right)
        self.assertEqual(f.current(), 'a')                           # wraps
        self.assertEqual(sum(1 for b in f._buttons.values() if b.focusPolicy() == Qt.FocusPolicy.StrongFocus), 1)     # one Tab stop

    def test_search_field_debounce_clear_and_escape(self):
        s = SearchField('Find', delay_ms=10000)
        got = []
        s.queryChanged.connect(got.append)
        s.show()
        s.setText('abc')
        self.assertEqual(got, [])
        s.flush()
        self.assertEqual(got, ['abc'])
        QTest.keyClick(s, Qt.Key.Key_Escape)
        self.assertEqual(s.text(), '')

    def test_banner_and_status_line(self):
        b = Banner('t', 'warn', closable=True)
        b.show()
        b.close_button.click()
        self.assertFalse(b.isVisible())
        sl = StatusLine('Report saved')
        self.assertEqual(sl.kind(), 'good')
        sl.set('Measurement failed: timeout')
        self.assertEqual(sl.kind(), 'bad')
        self.assertIn(theme.tokens()['bad_dot'], sl.text())

    def test_set_prop_repolishes(self):
        w = QWidget()
        set_prop(w, 'role', 'x')
        self.assertEqual(w.property('role'), 'x')


if __name__ == '__main__':
    unittest.main()
