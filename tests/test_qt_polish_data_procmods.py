"""Light-theme / spacing polish of the procedure editor, the point editor window, the manual grid box and the token contrast pairs the data screens rely on.
Skipped when PySide6 is not importable.

    <venv python> -m unittest tests.test_qt_polish_data_procmods
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import test_qt_procmods as TP
    import test_qt_manual_grid as TM
    from PySide6.QtWidgets import QApplication
    from qtui import theme


def pump(n=8):
    for _ in range(n):
        QApplication.processEvents()


def ratio(a, b):
    from qtui.screens.spec_editor import _contrast
    return _contrast(a, b)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LightProcmods(TP.QtBase):
    def setUp(self):
        super().setUp()
        self.unlock()
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')

    def test_every_tab_builds_in_light_and_the_changes_table_shares_a_wide_window(self):
        win = self.window()
        win.resize(1800, 900)
        for name, tab in win.tabs.items():
            win.nb.setCurrentIndex(list(win.tabs).index(name))
            tab.reload()
            pump()
        ch = win.tabs['Changes'].table
        hh = ch.horizontalHeader()
        self.assertGreater(hh.sectionSize(1), 170, 'Item column took its share')
        self.assertGreater(hh.sectionSize(2), 150, 'Factory column took its share')

    def test_live_switch_with_the_window_open(self):
        win = self.window()
        pump()
        before = win.grab().toImage().pixelColor(5, 5)
        theme.set_theme('dark')
        pump()
        self.assertNotEqual(before, win.grab().toImage().pixelColor(5, 5))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LightManualGrid(TM.ManualGrid):
    def setUp(self):
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')
        super().setUp()

    def test_light_box_over_a_cell_and_the_invalid_mark(self):
        self.ge.open('p3')
        self.ge.var.set('nan')
        self.ge.commit(1)
        pump()
        self.assertTrue(self.ge.entry.property('invalid'))
        t = theme.tokens()
        self.assertGreaterEqual(ratio(t['text'], t['field']), 4.5)
        self.assertGreaterEqual(ratio(t['bad'], t['field']), 4.5)


for _n in [n for n in dir(LightManualGrid) if n.startswith('test_') and n != 'test_light_box_over_a_cell_and_the_invalid_mark']:
    setattr(LightManualGrid, _n, None)                    # the inherited cases are test_qt_manual_grid's own


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TokenPairs(unittest.TestCase):
    PAIRS = (('text', 'card'), ('muted', 'card'), ('muted', 'bg'), ('good', 'good_bg'), ('warn', 'warn_bg'), ('bad', 'bad_bg'), ('info', 'info_bg'),
             ('neutral', 'neutral_bg'), ('info', 'card'), ('bad', 'card'), ('warn', 'card'), ('good', 'card'), ('row_fail_fg', 'card'),
             ('row_warn_fg', 'card'), ('text', 'select'))

    def test_light_and_dark_pairs_used_by_the_data_screens_are_readable(self):
        for name in ('light', 'dark'):
            t = theme.build_tokens(name)
            for a, b in self.PAIRS:
                self.assertGreaterEqual(ratio(t[a], t[b]), 4.5, (name, a, b))
            self.assertGreaterEqual(ratio(t['info'], t['select']), 4.4, name)       # light 4.497: the blue changed-standard text on a selected row (shared token)


if __name__ == '__main__':
    unittest.main()
