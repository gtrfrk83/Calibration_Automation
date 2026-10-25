"""Datasheet Builder inspector: the frequency unit picker, the footer Calc, the side radios."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from qtui.screens.dsb_inspector import FreqBox
from qtui.screens import dsb_common as C

_app = QApplication.instance() or QApplication([])


class FreqBoxTests(unittest.TestCase):
    def test_round_trip(self):
        b = FreqBox()
        bind = C.Bind(b)
        bind.set('1 MHz')
        self.assertEqual((b.edit.text(), b.unit.currentText()), ('1', 'MHz'))
        self.assertEqual(bind.get(), '1 MHz')
        b.unit.setCurrentText('kHz')
        b.edit.setText('20')
        self.assertEqual(bind.get(), '20 kHz')
        b.edit.setText('5 GHz')                 # a unit typed by hand wins
        self.assertEqual(bind.get(), '5 GHz')
        bind.set('')
        self.assertEqual(bind.get(), '')


if __name__ == '__main__':
    unittest.main()
