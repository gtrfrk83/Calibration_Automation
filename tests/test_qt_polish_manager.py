"""Light theme + spacing polish of the Manager and its hosted dialogs: key token pairs reach their contrast in BOTH themes, the screens build in light, a live
theme switch repaints already-open windows (style sheets that name tokens, painted icons), and a narrow Manager keeps every list column on screen.
Skipped when PySide6 is not importable.   python -m unittest tests.test_qt_polish_manager"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
_DATA = tempfile.mkdtemp(prefix='qt_polish_mgr_')
os.environ.setdefault('CALSUITE_DATA', _DATA)

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtWidgets import QLabel, QWidget
    from qtui import app, theme, widgets as W

MIN = [('text', 'bg', 7), ('text', 'card', 7), ('muted', 'bg', 4.5), ('muted', 'card', 4.5), ('placeholder', 'field', 4.5), ('on_primary', 'primary', 4.5),
       ('on_primary', 'primary_hi', 4.5), ('primary', 'bg', 4.5), ('primary', 'card', 4.5), ('info', 'select', 4.5), ('info', 'info_bg', 4.5),
       ('good', 'good_bg', 4.5), ('bad', 'bad_bg', 4.5), ('warn', 'warn_bg', 4.5), ('faint', 'bg', 3), ('faint', 'card', 3), ('disabled_fg', 'disabled_bg', 3),
       ('primary_off_fg', 'primary_off', 4.5), ('tooltip_fg', 'tip', 4.5), ('text', 'select', 7)]


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Contrast(unittest.TestCase):
    def test_key_pairs_in_both_themes(self):
        for name in ('dark', 'light'):
            t = theme.build_tokens(name)
            for a, b, need in MIN:
                self.assertGreaterEqual(theme.contrast(t[a], t[b]), need, f'{name}: {a} on {b}')
        self.assertGreaterEqual(theme.contrast('#FFFFFF', theme.build_tokens('light')['danger']), 4.5)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LightScreens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def tearDown(self):
        theme.set_theme('dark')

    def pump(self):
        for _ in range(5):
            self.app.processEvents()

    def manager(self):
        import manager_model as mm
        import verified as V
        from qtui.screens.manager import ManagerWindow
        t = Path(tempfile.mkdtemp())
        core = mm.ManagerCore(db=t / 'p.sqlite3', registry=V.Registry(t / 'v.sqlite3', seed=False))
        w = ManagerWindow(core, launcher=lambda *a, **k: None, panels={})
        self.addCleanup(w.close)
        return w

    def test_manager_builds_in_light_and_every_column_fits_a_narrow_window(self):
        theme.set_theme('light')
        w = self.manager()
        w.resize(1100, 700)
        w.show()
        for _ in range(8):
            self.pump()
        hh = w.table.horizontalHeader()
        last = hh.count() - 1
        self.assertLessEqual(hh.sectionPosition(last) + 60, w.table.viewport().width(), 'the last column starts off screen')
        self.assertFalse(w.table.horizontalScrollBar().isVisible())

    def test_dialogs_build_in_light(self):
        import types
        from qtui.screens import manager_dialogs as D
        theme.set_theme('light')
        parent = QWidget()
        for make in (lambda: W.MessageDialog(parent, 'warning', 'Heads up', 'Text', detail='a\nb'),
                     lambda: W.ModalDialog(parent, 'Register'),
                     lambda: W.ProgressDialog(parent, 'Working', 'x', maximum=10)):
            d = make()
            d.show()
            self.pump()
            self.assertFalse(d.grab().isNull())
            d.close()

    def test_live_switch_repaints_open_widgets(self):
        theme.set_theme('dark')
        host = QWidget()
        lab = QLabel('x', host)
        W.follow_tokens(lab, lambda: f"color: {theme.tokens()['bad']};")
        icon = QLabel(host)
        W.follow_theme(icon, lambda: icon.setPixmap(theme.pixmap('info', theme.tokens()['info'], 16)))
        dark_css, dark_px = lab.styleSheet(), icon.pixmap().toImage().pixelColor(8, 8).name()
        theme.set_theme('light')
        self.pump()
        self.assertNotEqual(lab.styleSheet(), dark_css)
        self.assertIn(theme.tokens()['bad'], lab.styleSheet())
        self.assertNotEqual(icon.pixmap().cacheKey(), 0)
        W.follow_tokens(lab, lambda: 'color: red;')                       # a second call replaces the first builder
        theme.set_theme('dark')
        self.assertEqual(lab.styleSheet(), 'color: red;')
        host.deleteLater()
        theme.set_theme('light')                                          # a deleted widget's follower must not raise
        self.pump()

    def test_find_instruments_and_share_width(self):
        from qtui.screens import find_instruments as FI
        import instrument_scan as S
        theme.set_theme('light')
        t = Path(tempfile.mkdtemp())
        w = FI.FindInstrumentsWindow(None, memory=S.ResourceMemory(t / 'lab.sqlite3', workstation='WS-1'), serial_ports=lambda: [])
        w.resize(1900, 900)
        w.show()
        for _ in range(8):
            self.pump()
        self.assertGreater(w.table.columnWidth(0), 300)                    # extra width is shared, not one giant Instrument column
        w.close()


if __name__ == '__main__':
    unittest.main()
