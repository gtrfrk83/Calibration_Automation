"""Subprocess of tests/test_qt_polish_engines.py (not a test module): windows built in DARK are switched to LIGHT with theme.set_theme and must repaint at once.

Opens one bench window, one handheld window and the Datasheet Builder editor, grabs each, switches the theme and checks that the table / sheet / window background
pixels follow the new tokens and the window is light.  Prints 'LIVE SWITCH OK'.  (Windows stay open until the end: the Help > Appearance menu of a closed window must
not receive the signal.)"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['CALSUITE_THEME'] = 'dark'
ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / 'tests', ROOT / 'Procedures'):
    sys.path.insert(0, str(p))

try:                                                  # a real tkinter needs its dialog modules imported first; without one the stub stands in
    import tkinter  # noqa: F401
    for _sub in ('messagebox', 'filedialog', 'simpledialog'):
        __import__('tkinter.' + _sub)
except ImportError:
    import _tk_stub
    _tk_stub.install()
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMainWindow  # noqa: E402

import qt_bench_dump as D  # noqa: E402
import qt_bench_harness as QH  # noqa: E402
from qtui import theme  # noqa: E402


def near(a, b, tol=6):
    a, b = QColor(a), QColor(b)
    return abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol and abs(a.blue() - b.blue()) <= tol


def main():
    hn = QH.QtHarness().start()
    app = dict(D.engines())['truevolt_34470A'](hn.root, True)
    hn.app = app
    QH.show(hn.root, 1200, 760)
    for p in QH.points_of(app)[:12]:
        app._record(p, p['nominal'] + 0.2 * p['error'], True)
    QH.record_failures(app)
    QTest.qWait(300)
    assert theme.name() == 'dark', theme.name()
    before = hn.root.grab().toImage()
    assert before.pixelColor(before.width() // 2, before.height() - 3).lightness() < 90, 'not dark at first'
    # a second window, the Datasheet Builder editor, open at the same time
    import test_qt_dsb as T
    case = T.QtDsbCase('setUp')
    T.QtDsbCase.setUpClass()
    case.setUp()
    win = case.new_window()
    win.resize(1200, 760)
    QTest.qWait(300)
    sheet_before = win.sheet.viewport().grab().toImage()
    theme.set_theme('light')
    QTest.qWait(400)
    after = hn.root.grab().toImage()
    px = after.pixelColor(after.width() // 2, after.height() - 3)
    assert px.lightness() > 180, f'the bench window did not repaint light: {px.name()}'
    t = theme.tokens()
    tree_px = app.tree.viewport().grab().toImage().pixelColor(app.tree.viewport().width() - 400, 4)
    assert near(tree_px, t['table']) or near(tree_px, t['select']) or near(tree_px, t['row_fail']) or tree_px.lightness() > 200, f'table did not repaint: {tree_px.name()}'
    sheet_after = win.sheet.viewport().grab().toImage()
    assert sheet_after.pixelColor(sheet_after.width() - 5, sheet_after.height() - 5).lightness() > 180, 'the sheet did not repaint light'
    assert sheet_before.pixelColor(sheet_before.width() - 5, sheet_before.height() - 5).lightness() < 100, 'the sheet was not dark before'
    theme.set_theme('dark')
    QTest.qWait(300)
    back = hn.root.grab().toImage()
    assert back.pixelColor(back.width() // 2, back.height() - 3).lightness() < 90, 'the window did not go back to dark'
    print('LIVE SWITCH OK')
    case.close_all()
    hn.stop()


if __name__ == '__main__':
    main()
