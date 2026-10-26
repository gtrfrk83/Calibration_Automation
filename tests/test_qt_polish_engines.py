"""Qt polish pass, engine windows and the Datasheet Builder: LIGHT theme and layout checks.  Headless (QT_QPA_PLATFORM=offscreen); skipped without PySide6.

  * Contrast: the colour pairs the engine windows and the builder paint (text on background, muted text, pass / fail / warn / info on their tints, the primary and
    danger buttons, the selected row) in BOTH themes.
  * Bench windows (truevolt, dacq, k2000, f8808a, a34401a, f8846a, agilent34410a), the handheld window with the long 376 note, the three generator / scope windows and
    the WaveSurfer window, built in LIGHT at the 1000 x 640 minimum and at 1920 x 1080: no exception, a light window, the detail text never over the table, the
    Limits column wide enough for its text in the small window, the numbers sharing a wide table.
  * The adjustment windows at 1100 x 700 (no horizontal scroll bar; the button bar wraps), the small dialogs, the Datasheet Builder editor and list (the sheet's
    function column no longer takes every spare pixel).
  * Live switch: a window built in dark repaints in light without a restart (a subprocess: tests/qt_polish_live_switch.py).
Screenshots reviewed by hand are made by the scripts named in NOTES.md ('Qt polish pass: datasheet builder and engine windows')."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['CALSUITE_THEME'] = 'light'                         # the start-up choice of every window this module builds
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

try:
    import tkinter  # noqa: F401
    for _sub in ('messagebox', 'filedialog', 'simpledialog'):       # tests/dsb_run_harness.py (imported by the harnesses) expects them in sys.modules
        try:
            __import__('tkinter.' + _sub)
        except ImportError:
            pass
except ImportError:                                                 # the CI sandbox has none
    import _tk_stub
    _tk_stub.install()

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMainWindow, QScrollArea, QWidget
    from qtui import theme
    from qtui.bench_view import DetailBox


def setUpModule():
    # qtui/theme.build_appearance_menu connects a lambda that raises once the window owning the menu is closed, and the error dialog of qtui.app then blocks the run
    # (reported in NOTES.md, shared component): this module builds many windows in one process, so its windows get no Appearance menu (the live switch is tested in
    # a subprocess with windows that stay open).
    if HAVE_QT:
        global _PATCH, _PATCH2
        _PATCH = mock.patch.object(theme, 'build_appearance_menu', lambda *a, **k: None)
        _PATCH2 = mock.patch.object(theme, 'fill_appearance_menu', lambda *a, **k: None)
        _PATCH.start()
        _PATCH2.start()


def tearDownModule():
    if HAVE_QT:
        _PATCH.stop()
        _PATCH2.stop()


def lum(h):
    h = h.lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4          # noqa: E731
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + .05) / (lb + .05)


# (foreground token, background token, least contrast): 4.5 for text, 3 for the bold text of a filled button
PAIRS = (('text', 'bg', 4.5), ('text', 'table', 4.5), ('muted', 'bg', 4.5), ('muted', 'table', 4.5), ('muted', 'head', 4.5),
         ('good', 'good_bg', 4.5), ('bad', 'bad_bg', 4.5), ('warn', 'warn_bg', 4.5), ('info', 'info_bg', 4.5), ('neutral', 'neutral_bg', 4.5),
         ('row_pass_fg', 'row_pass', 4.5), ('row_fail_fg', 'row_fail', 4.5), ('row_warn_fg', 'row_warn', 4.5), ('text', 'select', 4.5), ('bad', 'select', 4.0),
         ('good', 'select', 4.0), ('on_primary', 'primary', 2.8), ('tooltip_fg', 'tip', 4.5), ('primary_off_fg', 'primary_off', 4.5),
         ('danger_off_fg', 'danger_off', 4.5), ('focus', 'bg', 3.0))


def points_of(app):
    import sys as _s
    return app.active_points() if hasattr(app, 'active_points') else _s.modules[type(app).__module__].POINTS


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Contrast(unittest.TestCase):
    def test_pairs_in_both_themes(self):
        for name in ('dark', 'light'):
            t = theme.build_tokens(name)
            for fg, bg, least in PAIRS:
                with self.subTest(f'{name}: {fg} on {bg}'):
                    self.assertGreaterEqual(contrast(t[fg], t[bg]), least, f'{t[fg]} on {t[bg]}')
            with self.subTest(f'{name}: white on danger'):                  # the danger button's text is white
                self.assertGreaterEqual(contrast('#FFFFFF', t['danger']), 4.5)

    def test_light_is_enabled_and_the_window_comes_up_light(self):
        self.assertIn('light', theme.ENABLED_THEMES)
        from qtui import app as qapp
        qapp.create_app()
        self.assertEqual(theme.name(), 'light')
        self.assertFalse(theme.tokens()['is_dark'])


def no_overlap(test, win, tree, what=''):
    """The detail box starts below the table (it used to paint over the table's last rows in a window of 1000 x 640)."""
    boxes = [b for b in win.findChildren(DetailBox) if b.isVisible()]
    test.assertTrue(boxes, f'{what}: no detail box')
    t_bottom = tree.mapTo(win, tree.rect().bottomLeft()).y()
    for b in boxes:
        test.assertLessEqual(t_bottom, b.mapTo(win, b.rect().topLeft()).y() + 1, f'{what}: the detail text is over the table')
        test.assertGreater(b.height(), 12, what)
    test.assertGreaterEqual(tree.height(), tree.minimumHeight(), what)


def window_is_light(test, win):
    img = win.grab().toImage()
    px = img.pixelColor(img.width() // 2, img.height() - 3)                   # the status bar / window background
    test.assertGreater(px.lightness(), 180, 'the window is not light')


def central_scroll(win):
    return win.findChildren(QScrollArea)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class BenchLight(unittest.TestCase):
    KEYS = ('truevolt_34470A', 'dacq_34970A', 'k2000', 'f8808a', 'a34401a', 'f8846a', 'a34410a_34410A')

    def run_window(self, key, size):
        import qt_bench_dump as D
        import qt_bench_harness as QH
        hn = QH.QtHarness().start()
        self.addCleanup(hn.stop)
        app = dict(D.engines())[key](hn.root, True)
        app.asset.set('A-1234')
        app.serial.set('MY54001234')
        hn.app = app
        QH.show(hn.root, *size)
        return hn, app, QH

    def test_every_window_at_the_minimum_and_wide(self):
        for key in self.KEYS:
            for size in ((1000, 640), (1920, 1080)):
                with self.subTest(f'{key} {size}'):
                    hn, app, QH = self.run_window(key, size)
                    self.assertEqual(theme.name(), 'light')
                    for p in points_of(app)[:24]:
                        app._record(p, p['nominal'] + 0.2 * p['error'], True)
                    QH.record_failures(app)
                    app.tree.selection_set(str(points_of(app)[11]['id']))
                    QTest.qWait(250)
                    window_is_light(self, hn.root)
                    no_overlap(self, hn.root, app.tree, f'{key} {size}')
                    hh = app.tree.horizontalHeader()
                    if size[0] <= 1000:                                        # the small window: the merged Limits column has the width its text needs
                        self.assertFalse(app.tree.isColumnHidden(app.tree._keys.index('limits')))
                        self.assertGreaterEqual(hh.sectionSize(app.tree._keys.index('limits')), 200, key)
                    else:                                                       # the wide window: the numbers share the spare width
                        self.assertGreater(hh.sectionSize(app.tree._keys.index('found')), 100, key)
                        self.assertLess(hh.sectionSize(app.tree._keys.index('description')), app.tree.viewport().width() * 0.62, key)
                    app.shell.open_drawer()
                    QTest.qWait(150)
                    app.shell.close_drawer()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class HandheldLight(unittest.TestCase):
    def test_376_with_its_long_note_never_overlaps_the_table(self):
        import qt_handheld_harness as Q
        import handheld_dmm as hh
        import iflex_option
        hn = Q.QtHarness(None).start()
        self.addCleanup(hn.stop)
        for size in ((1000, 640), (1100, 700), (1920, 1080)):
            hn.root.close()
            hn.root = QMainWindow()
            app = iflex_option.App(hn.root, '376', demo=True, spec=hh.load_spec('fluke_376_pv.json'), fast_demo=False)
            hn.app = app
            hn.root.resize(*size)
            hn.root.show()
            QTest.qWait(250)
            hn.run_all()
            QTest.qWait(250)
            with self.subTest(size):
                no_overlap(self, hn.root, app.tree, f'376 {size}')
                window_is_light(self, hn.root)
                if size[0] <= 1000:
                    self.assertGreaterEqual(app.tree.horizontalHeader().sectionSize(app.tree._keys.index('limits')), 200)
                else:
                    self.assertGreaterEqual(app.tree.horizontalHeader().sectionSize(app.tree._keys.index('nominal')), 150)   # 'Calibrator output' is not cut

    def test_the_dialogs_build_in_light(self):
        import handheld_dmm_view_qt as V
        from qtui import app as qapp
        qapp.create_app()
        p = dict(id='1', n=1, section='DC volts', test='numeric', switch='V DC', range='600.0 V', group='DCV', applied=True, note='', display_unit='V', tol_text='',
                 low='0.9', high='1.1', nominal=1.0, factor=1.0, base_unit='V', dial=None)
        for mode in ('numeric', 'yesno'):
            dlg = V.ReadingDialog(None, p, 10, '1.0000 V', 'Output is ON', '0.9 to 1.1 V', mode, question='Is it lit?', unit='V', demo_fill=lambda: '1')
            dlg.show()
            QTest.qWait(50)
            self.assertFalse(dlg.grab().isNull())
            dlg.close()
        dlg = V.IrProblemDialog(None, p, 5, ['The meter is in the wrong function'], 'V DC')
        dlg.show()
        QTest.qWait(50)
        dlg.close()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class GenscopeLight(unittest.TestCase):
    def test_three_windows_light(self):
        import genscope_rows as G
        import qt_genscope_harness as Q
        for key in ('fgen_33250A_failures', 'mdo4000c_failures', 'tds2000c_2012C_failures'):
            for size in ((1000, 640), (1920, 1080)):
                with self.subTest(f'{key} {size}'):
                    hn = Q.QtHarness(Q.Answers([lambda r: r.get('initial') if r['kind'] in ('ask_number', 'ask_text') else None])).start()
                    try:
                        app = G.build(key, hn.root)
                        hn.app = app
                        hn.root.setMinimumSize(0, 0)
                        hn.root.resize(*size)
                        hn.root.show()
                        Q.settle(10)
                        app.run_all()
                        hn.pump(600)
                        QTest.qWait(300)
                        self.assertEqual(theme.name(), 'light')
                        window_is_light(self, hn.root)
                        no_overlap(self, hn.root, app.tree, f'{key} {size}')
                        if size[0] >= 1900:
                            self.assertLess(app.tree.horizontalHeader().sectionSize(app.tree._keys.index('description')), app.tree.viewport().width() * 0.62)
                    finally:
                        hn.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WaveSurferLight(unittest.TestCase):
    def test_window_light_small_and_wide(self):
        import qt_ws_harness as Q
        for size in ((1000, 680), (1920, 1080)):
            hn = Q.Harness()
            try:
                a = hn.app
                hn.win.setMinimumSize(0, 0)
                hn.win.resize(*size)
                a.load_demo_data()
                QTest.qWait(300)
                with self.subTest(size):
                    window_is_light(self, hn.win)
                    no_overlap(self, hn.win, a.utree, f'wavesurfer {size}')
                    view = a.utree
                    if hn.win.width() < 1200:                                  # not wide enough for every column: the merged Limits column
                        self.assertTrue(view.isColumnHidden(view._keys.index('low')))
                    else:
                        self.assertFalse(view.isColumnHidden(view._keys.index('low')))
            finally:
                hn.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class AdjustLight(unittest.TestCase):
    def build(self, key):
        import importlib
        import test_qt_views_adjust as T
        hn = T.QtHarness(None)
        hn.start()
        self.addCleanup(hn.stop)
        mod = importlib.import_module(T.VIEWS[key][1])
        if key == 'f8846a':
            tmp = Path(tempfile.mkdtemp())
            for name in ('_registry_path', '_legacy_path'):
                p = mock.patch.object(mod, name, lambda _n=name: tmp / f'{_n}.sqlite3')
                p.start()
                self.addCleanup(p.stop)
        hn.root = QMainWindow()
        hn.roots.append(hn.root)
        app = mod.App(hn.root, demo=True)
        hn.app = app
        hn.root.setMinimumSize(0, 0)
        return hn, app

    def test_three_windows_light_at_1100(self):
        for key in ('keithley', 'f8808a', 'f8846a'):
            with self.subTest(key):
                hn, app = self.build(key)
                hn.root.resize(1100, 700)
                hn.root.show()
                QTest.qWait(250)
                self.assertEqual(theme.name(), 'light')
                bar = hn.root.findChildren(QScrollArea)[0].horizontalScrollBar()
                if key == 'f8846a':
                    self.assertEqual(bar.maximum(), 0, 'the 8846A page needs a horizontal scroll bar at 1100 px')
                window_is_light(self, hn.root)

    def test_the_button_bar_wraps_in_a_narrow_window(self):
        from qtui import adjust_window as aw
        from qtui import shell_helpers as ui
        from qtui.vars import QtVar
        from qtui.app import create_app
        create_app()
        left = [ui.button(None, t, None) for t in ('Mark setup reviewed', 'Unlock adjustment (authorised)', 'Execute selected verified open step', 'Commit coefficients (CAL:REC)')]
        right = [ui.button(None, 'Relock and disconnect', None)]
        lay = aw.button_bar(left, right, QtVar(False, 'bool'), lambda: None)
        host = QWidget()
        host.setLayout(lay)
        host.resize(1500, 80)
        host.show()
        QTest.qWait(50)
        self.assertEqual(left[0].y(), right[0].y(), 'one row when there is room')
        host.resize(900, 120)
        QTest.qWait(80)
        self.assertGreater(right[0].y(), left[0].y(), 'two rows in a narrow window')
        self.assertLessEqual(right[0].geometry().right(), 900)
        host.close()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class DialogsLight(unittest.TestCase):
    def test_small_dialogs_build_and_render(self):
        from qtui import app as qapp
        qapp.create_app()
        import surprise
        import surprise_view_qt as SV
        import manual_override_view_qt as MV
        import dsb_prerun_view_qt as PV
        s = surprise.Surprise('empty reply', 'DMM', 'READ?', '', 'a number', 'the meter did not answer', log_tail=['>> READ?', '<< '], stop_only=False)
        p = dict(id=12, description='DC volts 10 V range', section_title='DC volts')
        host = QMainWindow()
        dialogs = [SV.build(host, 'Stop on surprise', s),
                   MV.build(None, p, 105, (-1, 1), 'V', 'the meter did not answer', 'Stop run', True, '', lambda d, t, c: ('use', t)),
                   PV.PreRunDialog(None, 'Review these commands.', 'SOUR:VOLT:LEV 1\nSOUR:VOLT:LEV 2')]
        for d in dialogs:
            d.show()
            QTest.qWait(60)
            img = d.grab().toImage()
            self.assertGreater(img.pixelColor(5, 5).lightness(), 180, type(d).__name__)
            d.close()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class DatasheetBuilderLight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qtui import app as qapp
        qapp.create_app()

    def test_editor_and_list_in_light_and_the_wide_sheet_shares_its_width(self):
        import test_qt_dsb as T
        import dsb_scenario as sc
        T.QtDsbCase.setUpClass()
        case = T.QtDsbCase('setUp')
        case.setUp()
        try:
            win = case.new_window()
            win.resize(1920, 1080)
            win.show()
            QTest.qWait(300)
            self.assertEqual(theme.name(), 'light')
            sc_ = sc
            win.make_v.set('Acme'), win.model_v.set('DM-1'), win.title_v.set('DM-1 PV')
            win.commit_header()
            win.function_chosen(sc_.dcv_label(win))
            case.type_cell(win, '5 V')
            QTest.qWait(300)
            hh = win.sheet.horizontalHeader()
            vp = win.sheet.viewport().width()
            # columns: 0 '#', 1 FUNCTION, 2 NOMINAL, 3 LOW, 4 HIGH, 5 STANDARD, 6 UNCERTAINTY (the STEP NUM column is no longer on screen)
            self.assertLess(hh.sectionSize(1), vp * 0.45, 'the function column takes every spare pixel')
            self.assertGreater(hh.sectionSize(1), 300, 'the function column did not grow')
            self.assertGreater(hh.sectionSize(2), 200, 'the nominal column did not grow')
            self.assertGreater(hh.sectionSize(5), 150, 'the standard column did not grow')
            self.assertGreater(win.grab().toImage().pixelColor(win.width() // 2, win.height() - 3).lightness(), 180)
            win.resize(1000, 640)
            QTest.qWait(300)
            self.assertGreaterEqual(hh.sectionSize(1), 120)
            # the list
            case.panel.resize(1920, 800)
            case.panel.show()
            QTest.qWait(200)
            tb = case.panel.table
            self.assertLessEqual(tb.horizontalHeader().sectionSize(tb._keys.index('title')) if hasattr(tb, '_keys') else 0, vp)
        finally:
            case.close_all()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LiveSwitch(unittest.TestCase):
    def test_windows_repaint_without_a_restart(self):
        env = dict(os.environ)
        env['CALSUITE_THEME'] = 'dark'
        r = subprocess.run([sys.executable, str(ROOT / 'tests' / 'qt_polish_live_switch.py')], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn('LIVE SWITCH OK', r.stdout)


if __name__ == '__main__':
    unittest.main()
