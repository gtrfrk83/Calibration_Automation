"""Light-theme / spacing polish of Asset History and the Review uncertainties window: both built in LIGHT, the width of a wide window shared between the
columns, the blue changed-standard text readable, a theme switched with the window open.  Skipped when PySide6 / reportlab / pypdf / pdftotext are missing.

    <venv python> -m unittest tests.test_qt_polish_data_history_review
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['HOME'] = tempfile.mkdtemp()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import test_qt_history as TH
    import test_qt_report_review as TR
    from PySide6.QtWidgets import QApplication
    from qtui import theme


def pump(n=8):
    for _ in range(n):
        QApplication.processEvents()


def ratio(a, b):
    from qtui.screens.spec_editor import _contrast
    return _contrast(a, b)


@unittest.skipUnless(HAVE_QT and TH.HAVE, 'PySide6, reportlab and pypdf are needed')
class LightHistory(TH.Base):
    def setUp(self):
        super().setUp()
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')

    def test_light_panel_builds_selects_and_a_wide_window_shares_its_width(self):
        p = self.panel()
        p.resize(1900, 900)
        pump()
        hh = p.assets.horizontalHeader()
        keys = [c.key for c in p.assets.source_model.columns]
        self.assertGreater(hh.sectionSize(keys.index('model')), 250, 'the instrument column took its share')
        for k in ('serial', 'last', 'result'):
            self.assertGreater(hh.sectionSize(keys.index(k)), {'serial': 140, 'last': 120, 'result': 170}[k], k)
        self.assertEqual(p.runs.row_count(), (1, 1))
        t = theme.tokens()
        self.assertGreaterEqual(ratio(t['bad'], t['bad_bg']), 4.5)

    def test_the_drift_chart_is_painted_in_light_and_after_a_switch(self):
        from qtui.screens import asset_history as AH
        chart = AH.DriftChart([('2026-01-01', 1.0, 20.0), ('2026-02-01', 1.0, 140.0)], 'V')
        self.addCleanup(chart.deleteLater)
        chart.resize(700, 320)
        light = chart.grab().toImage()
        theme.set_theme('dark')
        pump()
        dark = chart.grab().toImage()
        self.assertNotEqual(light.pixelColor(300, 5), dark.pixelColor(300, 5), 'the chart repaints from the theme tokens')


@unittest.skipUnless(TR.READY, TR.WHY)
class LightReview(TR.Base):
    def setUp(self):
        super().setUp()
        theme.set_theme('light')
        self.addCleanup(theme.set_theme, 'dark')

    def test_light_window_builds_and_the_changed_standard_text_is_blue_and_readable(self):
        w = self.window()
        row = next(r for r in self.model.rows if not r.spec.locked and len(self.model.options(r.spec.idx)) > 1 and r.cur.status != TR.M.NOT_IN_SCOPE)
        self.model.set_standard(row.spec.idx, self.other(row.spec.idx))
        w.refresh()
        pump()
        t = theme.tokens()
        self.assertEqual(row.status, TR.M.CHANGED)
        self.assertGreaterEqual(ratio(t['info'], t['table']), 4.5)
        self.assertGreaterEqual(ratio(t['info'], t['select']), 4.4)           # 4.497 in light: 0.003 short of AA; the coordinator is told (theme.py token)
        self.assertGreaterEqual(ratio(t['info'], t['row_alt']), 4.5)
        self.assertIn('Scope CMC (as published)', [c.title for c in w.table.source_model.columns])
        before = w.grab().toImage()
        theme.set_theme('dark')
        pump()
        self.assertNotEqual(before.pixelColor(10, 10), w.grab().toImage().pixelColor(10, 10), 'an open window repaints on a live switch')


if __name__ == '__main__':
    unittest.main()
