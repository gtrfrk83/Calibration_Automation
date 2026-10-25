"""Soft shadows: where they go, where they do not, and the switch."""
import os
import sys
import unittest
from unittest import mock

sys.modules.setdefault('tkinter', None)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton, QTableWidget, QVBoxLayout, QWidget
from qtui import app, depth

app.create_app()


def card(*kids):
    f = QFrame()
    f.setProperty('surface', 'card')
    lay = QVBoxLayout(f)
    for k in kids:
        lay.addWidget(k)
    return f


class DepthTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'CALSUITE_DEPTH': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def show(self, w):
        w.show()
        QApplication.processEvents()
        self.addCleanup(w.close)
        return w

    def test_buttons_and_cards_get_shadows_flat_ones_do_not(self):
        b, ghost, tog = QPushButton('Run'), QPushButton('Details'), QPushButton('x')
        ghost.setProperty('role', 'ghost')
        tog.setCheckable(True)
        inner = card(QPushButton('in'))
        outer = card(b, inner)
        root = self.show(QWidget())
        QVBoxLayout(root).addWidget(outer)
        root.layout().addWidget(ghost)
        root.layout().addWidget(tog)
        QApplication.processEvents()
        has = lambda w: w.graphicsEffect() is not None
        self.assertTrue(has(b) and has(outer))
        self.assertFalse(has(ghost) or has(tog))
        self.assertFalse(has(inner))                                   # no card inside a card

    def test_a_card_holding_a_table_stays_flat(self):
        t = QTableWidget(3, 2)
        c = card(t)
        root = self.show(QWidget())
        QVBoxLayout(root).addWidget(c)
        QApplication.processEvents()
        self.assertIsNone(c.graphicsEffect())

    def test_switch_removes_and_restores_everywhere_and_remembers(self):
        b = QPushButton('Run')
        c = card(b)
        root = self.show(QWidget())
        QVBoxLayout(root).addWidget(c)
        QApplication.processEvents()
        self.assertIsNotNone(b.graphicsEffect())
        with mock.patch('ui_theme_core.Settings') as S:
            depth.set_enabled(False, save=True)
            S.return_value.set.assert_called_with('depth', 'flat')
        self.assertIsNone(b.graphicsEffect())
        self.assertIsNone(c.graphicsEffect())
        depth.set_enabled(True)
        self.assertIsNotNone(b.graphicsEffect())
        self.assertIsNotNone(c.graphicsEffect())

    def test_off_by_environment_adds_nothing(self):
        with mock.patch.dict(os.environ, {'CALSUITE_DEPTH': '0'}):
            b = QPushButton('Run')
            self.show(b)
            self.assertIsNone(b.graphicsEffect())


if __name__ == '__main__':
    unittest.main()
