"""Light-theme / spacing polish of the Standards Specs tab and the standards spec editor (qtui/screens/standards_specs.py, spec_editor.py).

Builds the screens in LIGHT, checks the contrast pairs the polish pass fixed, that a wide editor grid shares its width (no empty stretch area), that the
toolbar wraps instead of cutting a button, and that a theme switched while the windows are open repaints their HTML and tones.  Skipped without PySide6.

    <venv python> -m unittest tests.test_qt_polish_data_specs
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
    import time
    import test_qt_specs as TS
    from PySide6.QtWidgets import QApplication
    from qtui import theme
    from qtui.screens import spec_editor as sed


def pump(n=6):
    for _ in range(n):
        QApplication.processEvents()
    time.sleep(0.02)
    for _ in range(3):
        QApplication.processEvents()


def ratio(a, b):
    from qtui.screens.spec_editor import _contrast
    return _contrast(a, b)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LightEditor(TS.Base):
    def setUp(self):
        super().setUp()
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')

    def test_editor_builds_in_light_and_a_changed_cell_is_readable(self):
        ed = self.editor()
        self.assertEqual(theme.name(), 'light')
        first = ed.doc.lines()[0].iid
        ed.grid_rows.commit_text(first, 'res', '0.01 A')
        pump()
        bg, fg = sed.amber()
        self.assertGreaterEqual(ratio(fg, bg), 4.5)
        for name in ('light', 'dark'):
            theme.set_theme(name)
            bg, fg = sed.amber()
            self.assertGreaterEqual(ratio(fg, bg), 4.5, name)

    def test_wide_grid_shares_the_width_and_the_last_column_does_not_hold_the_rest(self):
        ed = self.editor(size=(1900, 900))
        pump()
        t = ed.grid_rows.table
        hh = t.horizontalHeader()
        base = {c[0]: c[2] for c in sed.COLS}
        keys = [c.key for c in t.source_model.columns]
        wide = [k for k in ('function', 'label') if hh.sectionSize(keys.index(k)) > base[k]]
        self.assertEqual(wide, ['function', 'label'], 'the extra width went to the text columns')
        last = keys.index('span')
        self.assertLess(hh.sectionSize(last), base['span'] * 3, 'the last column is not one huge stretch area')

    def test_toolbar_wraps_in_a_narrow_window_and_keeps_every_button_whole(self):
        ed = self.editor(size=(1000, 700))
        pump()
        for b in ed.btn.values():
            self.assertGreaterEqual(b.width(), b.sizeHint().width(), b.text())

    def test_live_switch_repaints_the_pending_panel_and_the_tones(self):
        theme.set_theme('dark')
        ed = self.editor()
        ed.grid_rows.commit_text(ed.doc.lines()[0].iid, 'res', '0.01 A')
        pump()
        self.assertIn(theme.build_tokens('dark')['text'].lower(), ed.pending.document().defaultStyleSheet().lower())
        theme.set_theme('light')
        pump()
        self.assertIn(theme.build_tokens('light')['text'].lower(), ed.pending.document().defaultStyleSheet().lower())
        self.assertIn('Pending changes', ed.pending.toPlainText())
        self.assertEqual(ed.path_label.palette().color(ed.path_label.foregroundRole()).name().lower(), theme.build_tokens('light')['muted'].lower())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LightStandardsTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qtui import app
        cls.app = app.create_app()

    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        import specmanager as sm
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        from qtui.screens import standards_specs as ss
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        sd = tmp / 'standards'
        sd.mkdir()
        for f in TS.SHEETS:
            shutil.copy(f, sd / f.name)
        sm.seed(sd, tmp / 'lab_registry.sqlite3')
        p = mock.patch.object(sm, 'DB', tmp / 'lab_registry.sqlite3')
        p.start()
        self.addCleanup(p.stop)
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')
        self.host = QWidget()
        lay = QVBoxLayout(self.host)
        self.p = ss.StandardsSpecsPanel(self.host)
        lay.addWidget(self.p)
        self.host.resize(1500, 900)
        self.host.show()
        self.addCleanup(self.host.close)
        pump()

    def test_light_panel_builds_and_the_range_column_is_wide_enough_for_a_group_title(self):
        self.assertGreaterEqual(self.p.rows.columnWidth(0), 120)
        self.assertEqual(theme.name(), 'light')
        t = theme.tokens()
        for pair in (('text', 'card'), ('muted', 'card'), ('good', 'good_bg'), ('warn', 'warn_bg'), ('bad', 'bad_bg'), ('info', 'info_bg'), ('neutral', 'neutral_bg')):
            self.assertGreaterEqual(ratio(t[pair[0]], t[pair[1]]), 4.5, pair)

    def test_live_switch_keeps_the_table_readable(self):
        theme.set_theme('dark')
        pump()
        theme.set_theme('light')
        pump()
        self.assertGreater(self.p.rows.topLevelItemCount(), 0)


if __name__ == '__main__':
    unittest.main()
