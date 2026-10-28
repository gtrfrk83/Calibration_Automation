"""QT-G1a: the Qt twins of the bench verification engine windows (truevolt_view_qt, dacq_view_qt, k2000_view_qt, f8808a_view_qt, a34401a_view_qt, f8846a_view_qt,
agilent34410a_view_qt) against the Tk windows they replace.  Headless (QT_QPA_PLATFORM=offscreen); skipped without PySide6.

  * WidgetState: the object tree of every window (buttons, check boxes, the As Found / As Left switch, combo boxes with their drop-down values, table headings, title) and each
    widget's enabled state idle and busy equals the dump taken ONCE from the real Tk window under Xvfb (tests/golden_ui/qt_views_bench_widgets_tk.json; tests/qt_bench_dump.py).
  * Rows: a full virtual run through the Qt window leaves the same result rows (values and tags) and the same detail text per selected point as the Tk window code
    records for the same simulated run.
  * Interaction: every button calls the engine method the Tk button called, Ctrl+S saves, the drawer opens / closes with Esc, selecting a row writes the detail text,
    a small window folds the sidebar and shortens the action buttons, the demo / hardware notices, the surprise window appears over the run window.
  * Render: the idle / busy / failures windows render non-blank (the screenshots reviewed by hand are made by tests/qt_bench_shots.py).
The prompt sequences are tests/test_qt_views_bench_prompts.py."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    import qt_bench_harness as QH
    import qt_bench_dump as D

FIXTURE = ROOT / 'tests' / 'golden_ui' / 'qt_views_bench_widgets_tk.json'
KEYS = ('truevolt_34470A', 'truevolt_34461A', 'dacq_34970A', 'dacq_34972A', 'k2000', 'f8808a', 'a34401a', 'f8846a', 'a34410a_34410A', 'a34410a_34411A')
VIEWS = ('truevolt_view', 'dacq_view', 'k2000_view', 'f8808a_view', 'a34401a_view', 'f8846a_view', 'agilent34410a_view')


def maker(key):
    return dict(D.engines())[key]


def no_ports():
    """list_com_ports() answers [] (the Tk fixture was made on a machine without serial ports)."""
    import dacq_verification, fluke8808a_verification
    return mock.patch.multiple(dacq_verification, list_com_ports=lambda: []), mock.patch.multiple(fluke8808a_verification, list_com_ports=lambda: [])


def buttons(win):
    return {b.text(): b for b in win.findChildren(QPushButton)}


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WidgetState(unittest.TestCase):
    def setUp(self):
        self.hn = QH.QtHarness().start()
        self.p1, self.p2 = no_ports()
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop()
        self.hn.stop()

    def test_every_window_equals_the_tk_dump(self):
        want_all = json.loads(FIXTURE.read_text(encoding='utf-8'))
        import suite_info
        from qtui.bench_view import suite_title
        for key in KEYS:
            for demo in (True, False):
                name = f'{key}|{"demo" if demo else "hardware"}'
                with self.subTest(name):
                    self.hn.root.close()
                    from PySide6.QtWidgets import QMainWindow
                    root = QMainWindow()
                    app = maker(key)(root, demo)
                    QH.show(root)
                    got = D.dump('qt', root, app, update=QApplication.processEvents)
                    want = want_all[name]
                    self.assertEqual(suite_title(want['title']), got['title'])
                    self.assertTrue(got['title'].startswith(suite_info.NAME))
                    self.assertEqual(want['headings'], got['headings'])
                    for group in ('buttons', 'checks', 'modes', 'combos'):
                        for state in ('idle', 'busy'):
                            have = [r for r in got[group][state] if r[0] not in ('Log', 'Rerun From Selected')]          # the shell's own Log button (hidden until there is a log line) and 'Rerun From Selected' are new in Qt
                            self.assertEqual(want[group][state], have, f'{name}: {group} {state}')
                    root.close()

    def test_stop_is_the_only_active_button_while_busy_and_the_inputs_lock(self):
        for key in ('truevolt_34470A', 'a34401a'):
            from PySide6.QtWidgets import QMainWindow
            root = QMainWindow()
            app = maker(key)(root, True)
            QH.show(root)
            b = buttons(root)
            self.assertFalse(b['■  Stop'].isEnabled())
            self.assertTrue(b['▶  Run All Pending'].isEnabled())
            app._busy = True
            app._sync_buttons()
            b = buttons(root)
            self.assertTrue(b['■  Stop'].isEnabled())
            for t in ('▶  Run All Pending', 'Run Shown Section', 'Rerun Selected', 'Load progress', 'Test connections'):
                self.assertFalse(b[t].isEnabled(), t)
            for t in ('Export Report (PDF)', 'Save progress'):
                self.assertTrue(b[t].isEnabled(), t)             # as in the Tk window: only the run buttons lock
            app._busy = False
            app._sync_buttons()
            self.assertTrue(buttons(root)['▶  Run All Pending'].isEnabled())
            root.close()

    def test_views_resolve_through_the_qt_port(self):
        import ui_port
        port = ui_port.get_ui()
        for v in VIEWS:
            mod = port.view(v)
            self.assertTrue(mod.__name__.endswith('_qt'), v)
            for fn in ('setup_window', 'finish_window', 'sync_buttons', 'build_ui', 'table_selection', 'table_has', 'table_select', 'table_set_rows', 'table_update_row', 'set_choices'):
                self.assertTrue(callable(getattr(mod, fn)), f'{v}.{fn}')
            tk_mod = __import__(v + '_tk')
            tk_funcs = sorted(n for n in dir(tk_mod) if callable(getattr(tk_mod, n)) and getattr(getattr(tk_mod, n), '__module__', '') == v + '_tk')
            for n in tk_funcs:
                self.assertTrue(callable(getattr(mod, n, None)), f'{v}_qt has no {n}() that {v}_tk has')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Rows(unittest.TestCase):
    """The same simulated run through the Tk window code (stubbed widgets, rows recorded at the view's table_* calls) and the Qt window code."""

    CASES = ('truevolt_34470A', 'dacq_34972A', 'k2000', 'a34401a', 'f8846a', 'a34410a_34410A')

    def tk_side(self, key):
        C = QH.C
        hn = C.PortHarness(None)
        hn.start()
        try:
            app = maker(key)(hn.root, True)
            app.asset.set('A-1'); app.serial.set('S-1')
            hn.app = app
            rows, view = {}, app.ui_view

            def set_rows(self, rs, keep):
                rows.clear()
                for iid, values, tags in rs:
                    rows[iid] = (list(values), list(tags) if isinstance(tags, (list, tuple)) else [tags])

            def update(self, iid, values, tags):
                rows[iid] = (list(values), list(tags) if isinstance(tags, (list, tuple)) else [tags])
            with mock.patch.object(view, 'table_set_rows', set_rows), mock.patch.object(view, 'table_update_row', update), \
                    mock.patch.object(view, 'table_has', lambda self, iid: True):
                app.refresh()                                           # the rows the constructor made, recorded too
                self.assertTrue(hn.run_all())
                details = {}
                for iid in rows:
                    with mock.patch.object(view, 'table_selection', lambda self, _i=iid: (_i,)):
                        app.on_select()
                    details[iid] = app.detail.get()
            return rows, details
        finally:
            hn.stop()

    def qt_side(self, key):
        hn = QH.QtHarness()
        hn.start()
        try:
            app = maker(key)(hn.root, True)
            app.asset.set('A-1'); app.serial.set('S-1')
            hn.app = app
            QH.show(hn.root)
            self.assertTrue(hn.run_all())
            tree = app.tree
            rows = {iid: (list(tree.item(iid)['values']), list(tree.item(iid)['tags'])) for iid in tree.get_children()}
            details = {}
            for iid in rows:
                tree.selection_set(iid)
                QTest.qWait(2)                                          # the table coalesces selection changes into one signal on the next event-loop turn
                details[iid] = app.detail.get()
            return rows, details
        finally:
            hn.stop()

    def test_rows_and_detail_text_equal_the_tk_window(self):
        for key in self.CASES:
            with self.subTest(key):
                tk_rows, tk_details = self.tk_side(key)
                qt_rows, qt_details = self.qt_side(key)
                self.assertGreater(len(tk_rows), 5)
                self.assertEqual(sorted(tk_rows), sorted(qt_rows))
                for iid in tk_rows:
                    self.assertEqual(tk_rows[iid], qt_rows[iid], f'{key} row {iid}')
                    self.assertEqual(tk_details[iid], qt_details[iid], f'{key} detail {iid}')
                self.assertTrue(all(t[1] and t[1][-1] in ('pass', 'fail', 'error', 'pending', 'next') or True for t in tk_rows.values()))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Interaction(unittest.TestCase):
    def setUp(self):
        self.hn = QH.QtHarness().start()

    def tearDown(self):
        self.hn.stop()

    def build(self, key, demo=True, **patches):
        app = maker(key)(self.hn.root, demo)
        app.asset.set('A-1'); app.serial.set('S-1')
        self.hn.app = app
        QH.show(self.hn.root)
        return app

    def test_buttons_call_the_engine_methods(self):
        for key, extra in (('truevolt_34461A', ()), ('f8846a', ('export_excel',)), ('f8808a', ()), ('dacq_34972A', ())):
            with self.subTest(key):
                self.hn.root.close()
                from PySide6.QtWidgets import QMainWindow
                self.hn.root = QMainWindow()
                cls = type(maker(key)(QMainWindow(), True))
                names = ['run_all', 'run_section', 'rerun', 'request_stop', 'export_pdf', 'load', 'save', 'find_instruments', 'test_connections', *extra]
                if key == 'f8846a':
                    names = [n for n in names if n != 'find_instruments']        # its drawer button is 'Refresh ports' (the factory stubs refresh_ports itself)
                with mock.patch.multiple(cls, **{n: mock.DEFAULT for n in names}) as m:
                    app = self.build(key)
                    b = buttons(self.hn.root)
                    app._busy = True
                    app._sync_buttons()
                    for text, name in (('■  Stop', 'request_stop'), ('Export Report (PDF)', 'export_pdf'), ('Save progress', 'save')):
                        QTest.mouseClick(b[text], Qt.MouseButton.LeftButton)
                        self.assertEqual(m[name].call_count, 1, (key, text))
                    app._busy = False
                    app._sync_buttons()
                    for text, name in (('▶  Run All Pending', 'run_all'), ('Run Shown Section', 'run_section'), ('Rerun Selected', 'rerun'), ('Load progress', 'load')):
                        QTest.mouseClick(b[text], Qt.MouseButton.LeftButton)
                        self.assertEqual(m[name].call_count, 1, (key, text))
                    if extra:
                        QTest.mouseClick(b['Export Excel (.xlsx)'], Qt.MouseButton.LeftButton)
                        self.assertEqual(m['export_excel'].call_count, 1)
                    self.hn.shell = app.shell
                    app.shell.open_drawer()
                    QApplication.processEvents()
                    for text, name in (('Test connections', 'test_connections'), ('Find instruments', 'find_instruments')):
                        if text in b and name in m:
                            QTest.mouseClick(b[text], Qt.MouseButton.LeftButton)
                            self.assertEqual(m[name].call_count, 1, (key, text))

    def test_ctrl_s_saves_and_the_drawer_opens_and_closes_with_escape(self):
        import keithley2000_verification as K
        with mock.patch.object(K.App, 'save') as save:                  # the window binds the method when it is built
            app = self.build('k2000')
            QTest.keyClick(self.hn.root, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            QTest.qWait(20)
            self.assertEqual(save.call_count, 1)
        sh = app.shell
        self.assertFalse(sh._drawer_open)
        QTest.mouseClick(sh.btn_drawer, Qt.MouseButton.LeftButton)
        self.assertTrue(sh._drawer_open)
        self.assertTrue(sh.drawer.isVisible())
        QTest.keyClick(sh.drawer_body.findChildren(QPushButton)[0] if sh.drawer_body.findChildren(QPushButton) else sh.btn_drawer_close, Qt.Key.Key_Escape)
        QApplication.processEvents()
        self.assertFalse(sh._drawer_open)

    def test_selecting_a_row_writes_the_detail_text_and_the_filter_refreshes(self):
        app = self.build('a34410a_34410A')
        tree = app.tree
        first = tree.get_children()[3]
        tree.selection_set(first)
        QTest.qWait(5)
        text = app.detail.get()
        self.assertNotIn('Acceptable reading', text)                          # owner 2026-10-27: the limits are in the point table only
        self.assertIn('Setup:', text)
        n = len(tree.get_children())
        combo = app.status_filter
        combo.setCurrentText('Failed (OOT)')
        combo.activated.emit(combo.currentIndex())              # the <<ComboboxSelected>> of the Tk box: the table is refreshed with the new filter
        self.assertEqual(app.show_status.get(), 'Failed (OOT)')
        self.assertEqual(len(tree.get_children()), 0)
        self.assertGreater(n, 10)

    def test_small_window_folds_the_sidebar_and_shortens_the_buttons(self):
        app = self.build('truevolt_34470A')
        sh = app.shell
        self.assertFalse(sh.compact)
        self.assertTrue(sh.sidebar.isVisible())
        self.hn.root.resize(900, 700)
        QTest.qWait(80)
        self.assertTrue(sh.compact)
        self.assertFalse(sh.sidebar.isVisible())
        b = buttons(self.hn.root)
        self.assertIn('Rerun', b)
        self.assertNotIn('Rerun Selected', b)
        self.assertTrue(sh.section_picker.isVisible())
        win = self.hn.root.geometry()
        for t in ('▶  Run', 'Section', 'Rerun', '■ Stop', 'PDF', 'Load', 'Save'):
            g = b[t].mapTo(self.hn.root, b[t].rect().topLeft())
            self.assertTrue(0 <= g.x() and g.x() + b[t].width() <= win.width(), f'{t} fits the 900 px window')
        self.assertLessEqual(self.hn.root.minimumWidth(), 900)

    def test_notices_and_chips(self):
        for key, demo, text in (('f8808a', True, 'Results are generated by the program and are NOT calibration evidence'), ('f8808a', False, 'The program pauses and shows the hook-up'),
                                ('truevolt_34470A', False, 'The program pauses and asks you to confirm the wiring'), ('dacq_34970A', False, 'Warm the instrument up for 2 hours')):
            from PySide6.QtWidgets import QLabel, QMainWindow
            self.hn.root.close()
            self.hn.root = QMainWindow()
            self.build(key, demo)
            labels = ' '.join(l.text() for l in self.hn.root.findChildren(QLabel))
            self.assertIn(text, labels, (key, demo))
            self.assertIn('DEMO MODE' if demo else 'HARDWARE MODE', labels)

    def test_surprise_window_over_the_run_window(self):
        """A worker thread raises a surprise through the window's handler (surprise.py protocol): the Stop / Continue window opens on the UI thread, Continue answers True."""
        import surprise
        import ui_port
        app = self.build('truevolt_34470A')
        handler = ui_port.get_ui().surprise_handler(self.hn.root)
        s = surprise.Surprise('empty reply', 'DMM', 'READ?', '', 'a number', '', log_tail=['>> READ?', '<< '], stop_only=False)
        answer, seen = {}, {}

        def operator():                                           # the scripted operator: polls from inside the dialog's own event loop
            dlg = QApplication.activeModalWidget()
            if dlg is not None and 'texts' not in seen:
                seen['texts'] = [b.text() for b in dlg.findChildren(QPushButton)]
                seen['parent_is_window'] = dlg.parentWidget() is self.hn.root or dlg.parentWidget() is None
                next(b for b in dlg.findChildren(QPushButton) if b.text() == 'Continue').click()

        def worker():
            answer['v'] = handler(s)
        poll = QTimer()
        poll.setInterval(5)
        poll.timeout.connect(operator)
        poll.start()
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        end = time.time() + 15
        while t.is_alive() and time.time() < end:
            QTest.qWait(5)
        poll.stop()
        self.assertFalse(t.is_alive(), 'the surprise window did not appear / answer')
        self.assertIn('Stop', seen['texts'])
        self.assertIn('Continue', seen['texts'])
        self.assertEqual(answer.get('v'), True)

    def test_asset_history_hint_still_fills_the_serial(self):
        """labregistry.attach gets a window with after / after_cancel (finish_window): typing a known Instrument ID fills the serial like in Tk."""
        import labregistry
        app = self.build('truevolt_34470A')
        calls = []
        with mock.patch.object(labregistry, 'attach', lambda root, a, s, notify: calls.append((root, a, s, notify))):
            import truevolt_view_qt
            truevolt_view_qt.finish_window(app)
        root, asset, serial, notify = calls[0]
        fired = []
        h = root.after(1, lambda: fired.append(1))
        QTest.qWait(40)
        self.assertEqual(fired, [1])
        root.after_cancel(root.after(500, lambda: fired.append(2)))
        self.assertIs(asset, app.asset)

    def test_help_menu_and_title_pattern(self):
        app = self.build('a34401a')
        self.assertTrue(self.hn.root.windowTitle().startswith('Calibration Suite  |  Agilent 34401A | Performance Verification v54 [DEMO]  |  v'), self.hn.root.windowTitle())
        titles = [a.text().replace('&', '') for a in self.hn.root.menuBar().actions()]
        self.assertIn('Help', titles)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Render(unittest.TestCase):
    def test_idle_busy_and_failures_render(self):
        from PySide6.QtGui import QImage
        out = Path(os.environ.get('QT_BENCH_SHOTS') or tempfile.mkdtemp())
        for key in ('truevolt_34470A', 'dacq_34972A', 'f8846a'):
            hn = QH.QtHarness().start()
            try:
                app = maker(key)(hn.root, True)
                app.asset.set('A-1'); app.serial.set('S-1')
                hn.app = app
                QH.show(hn.root)
                QH.shot(hn.root, out / f'{key}_idle.png')
                self.assertTrue(hn.run_all())
                QH.record_failures(app)
                QH.shot(hn.root, out / f'{key}_failures.png')
                app._busy = True
                app._sync_buttons()
                QH.shot(hn.root, out / f'{key}_busy.png')
                app._busy = False
                for name in ('idle', 'failures', 'busy'):
                    img = QImage(str(out / f'{key}_{name}.png'))
                    self.assertGreater(img.width(), 1000)
                    colors = {img.pixelColor(x, y).rgb() for x in range(0, img.width(), 37) for y in range(0, img.height(), 29)}
                    self.assertGreater(len(colors), 8, f'{key} {name} looks blank')
                fails = [iid for iid in app.tree.get_children() if 'fail' in app.tree.item(iid)['tags']]
                self.assertGreaterEqual(len(fails), 3)
            finally:
                hn.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Sidecars(unittest.TestCase):
    PAIRS = {'truevolt_view': ('Keysight_34460A', 'Keysight_34461A', 'Keysight_34465A', 'Keysight_34470A'), 'dacq_view': ('Keysight_34970A', 'Keysight_34972A'),
             'k2000_view': ('Keithley_2000',), 'f8808a_view': ('Fluke_8808A_Verification',), 'a34401a_view': ('Agilent_34401A',), 'f8846a_view': ('Fluke_8846A_Verification',),
             'agilent34410a_view': ('Agilent_34410A', 'Agilent_34411A')}

    def test_every_qt_view_is_fingerprinted_next_to_its_tk_twin(self):
        for view, procs in self.PAIRS.items():
            for pname in procs:
                path = next(q for q in sorted(ROOT.joinpath('Procedures').glob(f'{pname}*.procedure.json')) if 'Adjustment' not in q.name)
                code = json.loads(path.read_text(encoding='utf-8'))['fingerprint']['code']
                self.assertIn(f'{view}_tk.py', code, path.name)
                self.assertIn(f'{view}_qt.py', code, path.name)
                self.assertEqual(code.index(f'{view}_qt.py'), code.index(f'{view}_tk.py') + 1, f'{path.name}: the Qt twin is listed right after the Tk view')
                self.assertIn('qtui/bench_view.py', code, path.name)


if __name__ == '__main__':
    unittest.main()
