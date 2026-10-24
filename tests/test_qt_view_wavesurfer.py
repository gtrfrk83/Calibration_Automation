"""The Qt window of the WaveSurfer WS4104HD procedure (wavesurfer_view_qt.py + wavesurfer_qt_common / _sections / _settings.py), package QT-G2b.  Skipped (except the static
tests) when PySide6 is not importable.

  * static: the Qt files are Tk-free and under 1,500 lines, the view has every public function of wavesurfer_view_tk.py, every text of the Tk view is in the Qt files,
    the procedure's sidecar fingerprint lists them;
  * the 8 scenarios / 233 prompts of tests/golden_ui/ui_prompts_wavesurfer.json, played through the REAL engine on the Qt view with a real Qt dialog for every prompt
    (tests/qt_ws_harness.py: the operator presses the buttons / types the answers; title, text and buttons are checked on screen);
  * the widget-state record of the Tk window (tests/qt_ref/wavesurfer_tk_state.json, real Tk 9 under Xvfb) equals the Qt window's, busy and idle;
  * the engine's DC voltage point methods (the golden engine_wavesurfer_dcv flow) run on the Qt App give the golden wire transcript;
  * window behaviour: tables, selection, filters, sections, the Test settings dialog, closing, the periodic ticks, the worker -> operator question queue.
Which sections the simulated bench covers: DC voltage only (drivers/simulated.make_bench).  RMS noise, impedance, offset, bandwidth, time base and trigger level run here
with the same fake workers the Tk fixture was recorded with (they put the real workers' events); their instrument code is covered by recorded fixtures only.
Run (separate process):  <venv python> -m unittest tests.test_qt_view_wavesurfer
"""
import ast
import json
import os
import re
import sys
import threading
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'tests' / 'qt_ref'))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

QT_FILES = ('wavesurfer_view_qt.py', 'wavesurfer_qt_common.py', 'wavesurfer_qt_sections.py', 'wavesurfer_qt_settings.py')
TK_VIEW = ROOT / 'wavesurfer_view_tk.py'
FIXTURE = ROOT / 'tests' / 'golden_ui' / 'ui_prompts_wavesurfer.json'
TK_STATE = ROOT / 'tests' / 'qt_ref' / 'wavesurfer_tk_state.json'


def toplevel_names(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    return {n for n in names if not n.startswith('_')}


def string_constants(path, skip_docstrings=True):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            docs.add(id(node.body[0].value))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and not (skip_docstrings and id(n) in docs)}


class StaticTests(unittest.TestCase):
    def test_qt_files_are_tk_free_and_short(self):
        for name in QT_FILES:
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertLess(len(text.splitlines()), 1500, name)
            for node in ast.walk(ast.parse(text)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for m in mods:
                    self.assertNotIn(m.split('.')[0], ('tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk'), f'{name} imports {m}')
                    self.assertFalse(m.endswith('_view_tk'), f'{name} imports {m}')

    def test_every_public_function_of_the_tk_view_exists(self):
        missing = toplevel_names(TK_VIEW) - toplevel_names(ROOT / 'wavesurfer_view_qt.py')
        self.assertEqual(sorted(missing), [])

    def test_every_text_of_the_tk_window_is_in_the_qt_window(self):
        """Every label / button / heading / note string of the Tk window code (strings of 4+ characters that read as words) is in the Qt files, untouched."""
        qt = set()
        for name in QT_FILES:
            qt |= string_constants(ROOT / name)
        tk_only = {s for s in string_constants(TK_VIEW)
                   if len(s) >= 4 and re.search(r'[A-Za-z]{3}', s) and ' ' in s.strip() or s in ('Retest', 'Serial', 'Model', 'Show', 'Baud', 'Channel', 'Range', 'Result', 'Units')}
        tech = ('TLabel', 'TButton', 'TFrame', 'wait_window', 'vertical', 'determinate', 'headings', 'browse')
        missing = sorted(s for s in tk_only if s not in qt and not any(t in s for t in tech) and '<' not in s and not s.startswith('WaveSurfer 4104HD |'))
        # the strings that are in the Qt files with a different split (Tk wrote long notes as one literal, the Qt files wrap them the same way) are compared whole
        joined = ' '.join(qt)
        really = [s for s in missing if s not in joined and s not in ('Instrument ID *', 'Serial')]       # those two are the shell's own (Shell.build_identity)
        self.assertEqual(really, [])

    def test_sidecar_lists_the_qt_files(self):
        side = json.loads((ROOT / 'Procedures' / 'WaveSurfer_WS4104HD.procedure.json').read_text(encoding='utf-8'))
        code = side['fingerprint']['code']
        self.assertIn('wavesurfer_view_tk.py', code)
        for name in QT_FILES:
            self.assertIn(name, code, name)
            self.assertLess(code.index('wavesurfer_view_tk.py'), code.index(name))
            self.assertTrue((ROOT / name).is_file())
        self.assertIn('wavesurfer_view_qt.py', side['own_files'])
        self.assertTrue(side['seed_verified'])

    def test_the_fixture_is_the_8_scenario_233_prompt_one(self):
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(len(data), 8)
        self.assertEqual(sum(len(v) for v in data.values()), 233)


if HAVE_QT:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QWidget
    import shiboken6

    from tests import qt_ws_harness as HN
    import ui_port
    from tests.test_ui_port_qt import Driver, button_texts, label_texts, press
    import ws_state


class QtAdapter:
    """ws_state's adapter for the Qt window."""

    def enabled(self, w):
        return w.isEnabled()

    def text(self, w):
        return w.text()

    def title(self, app):
        return app.root.windowTitle()

    def tabs(self, app):
        return [app.tabs.tabText(i) for i in range(app.tabs.count())]

    def columns(self, tree):
        return list(tree._keys)

    def heading(self, tree, key):
        return tree.heading(key)

    def rows(self, tree):
        return [(list(tree.item(i, 'values')), list(tree.item(i, 'tags'))) for i in tree.get_children()]

    def progress(self, bar):
        return float(bar.value()), float(bar.maximum())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtCase(unittest.TestCase):
    def setUp(self):
        self.h = None

    def tearDown(self):
        if self.h is not None:
            self.h.stop()

    def harness(self, **kw):
        self.h = HN.Harness(**kw)
        return self.h


# ====================================================================================================================================================
class PromptSequences(QtCase):
    """The 8 scenarios of the Tk build, prompt for prompt, through the real engine and real Qt dialogs."""
    want = json.loads(FIXTURE.read_text(encoding='utf-8')) if FIXTURE.exists() else {}

    def check(self, name):
        got = json.loads(json.dumps(HN.run_scenarios([name])[name]))
        self.assertEqual(len(got), len(self.want[name]), name)
        for i, (g, w) in enumerate(zip(got, self.want[name])):
            self.assertEqual(g, w, f'{name}: prompt {i}')

    def test_table_buttons(self):
        self.check('table_buttons')

    def test_demo_data_and_pm(self):
        self.check('demo_data_and_pm')

    def test_noise(self):
        self.check('noise')

    def test_dcv_on_the_simulated_bench(self):
        self.check('dcv')

    def test_sections_impedance_offset_bandwidth_timebase_trigger(self):
        self.check('sections')

    def test_bad_checkpoints(self):
        self.check('bad_checkpoints')

    def test_exports(self):
        self.check('exports')

    def test_close_window(self):
        self.check('close_window')

    def test_all_233(self):
        out = HN.run_scenarios()
        self.assertEqual(sorted(out), sorted(self.want))
        self.assertEqual(sum(len(v) for v in out.values()), 233)


# ====================================================================================================================================================
class Engine(QtCase):
    def test_engine_wavesurfer_dcv_flow_on_the_qt_app(self):
        """tests/golden/engine_wavesurfer_dcv.json (recorded on a window-less FakeApp): the same two DCV point methods called on the real App behind the Qt view give the
        same wire commands, command log, events and result (the 'call' text names the app, so it is compared without it)."""
        import drivers
        from tests import golden_capture as gc
        golden = json.loads((ROOT / 'tests' / 'golden' / 'engine_wavesurfer_dcv.json').read_text(encoding='utf-8'))['entries']
        h = self.harness(sim_bench=True)
        a, W = h.app, h.W
        from drivers.simulated import make_bench
        bench, ft, st = make_bench()
        transports = {'fluke': gc.RecordingTransport(ft), 'scope': gc.RecordingTransport(st)}

        def open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=10):
            fluke = drivers.Fluke5560A(transports['fluke'], log) if fluke_addr else None
            scope = drivers.WaveSurfer4104HD(transports['scope'], log) if scope_addr else None
            return fluke, scope
        a.open_bench = open_bench
        a.events.queue.clear()
        c = gc.Case('engine_wavesurfer_dcv')
        point = dict(channel=1, scale_v_div=0.5, nominal_v=1.0, lower_v=0.99, upper_v=1.01)
        log_holder = {}
        orig = drivers.CommandLog

        class HoldLog(orig):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                log_holder['log'] = self
        drivers.CommandLog = HoldLog
        try:
            with gc.pinned():
                for name, fn, args in (('WaveSurfer_WS4104HD.automatic_dcv_point', W.RMSNoiseApp.automatic_dcv_point, (a, point, 2.0, 'sim', 9600, 'sim')),
                                       ('WaveSurfer_WS4104HD.read_dcv_scope', W.RMSNoiseApp.read_dcv_scope, (a, point))):
                    log_holder.clear()
                    c.run(name, fn, *args, _log=None)
                    c.entries[-1]['log'] = [f'{i}|{d}|{t}' for _ts, i, d, t in log_holder['log'].entries]
                    c.entries[-1]['events'] = [list(map(_plain, a.events.get_nowait())) for _ in range(a.events.qsize())]
        finally:
            drivers.CommandLog = orig
        self.assertEqual(len(c.entries), len(golden))
        for got, want in zip(c.entries, golden):
            got = json.loads(json.dumps(got, default=str))
            for key in ('case', 'method', 'wire', 'log', 'events', 'result'):
                self.assertEqual(got[key], want[key], f'{want["case"]}: {key}')
            self.assertEqual(got['call'].split(', ', 1)[1], want['call'].split(', ', 1)[1])


def _plain(x):
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, float):
        return round(x, 9)
    return x if isinstance(x, (int, str, bool, type(None))) else repr(x)


# ====================================================================================================================================================
class WidgetStates(QtCase):
    def test_widget_state_equals_the_tk_window(self):
        """Buttons (enabled / text), the notebook's tab titles, every table (columns, headings, rows, tags), progress bars, status texts, chip, sections, title: idle,
        a function busy, the RMS-noise run going, demo data, each function chosen in the sidebar, the 'Failed' filter."""
        want = json.loads(TK_STATE.read_text(encoding='utf-8'))
        h = self.harness()
        got = json.loads(json.dumps(ws_state.collect(h.app, QtAdapter()), sort_keys=True, ensure_ascii=False))
        self.assertEqual([s['label'] for s in got], [s['label'] for s in want])
        for g, w in zip(got, want):
            for key in w:
                self.assertEqual(g[key], w[key], f'{w["label"]}: {key}')

    def test_busy_and_idle_buttons(self):
        h = self.harness()
        a = h.app
        a._unified_tick()
        self.assertTrue(a.btn_run.isEnabled() and not a.btn_stop.isEnabled())
        a.dc_running = True
        a._unified_tick()
        self.assertFalse(a.btn_run.isEnabled() or a.btn_section.isEnabled() or a.btn_rerun.isEnabled() or a.btn_clear.isEnabled())
        self.assertTrue(a.btn_stop.isEnabled())
        self.assertFalse(any(b.isEnabled() for b in a.mode_buttons))
        a.dc_running = False
        a._unified_tick()
        self.assertTrue(a.btn_run.isEnabled() and not a.btn_stop.isEnabled() and all(b.isEnabled() for b in a.mode_buttons))
        a.set_running(True)
        self.assertFalse(a.start_button.isEnabled() or a.connect_button.isEnabled() or a.channel_select.isEnabled())
        self.assertTrue(a.stop_button.isEnabled())
        a.set_running(False)
        self.assertTrue(a.start_button.isEnabled() and a.channel_select.isEnabled() and not a.stop_button.isEnabled())


# ====================================================================================================================================================
class WindowBehaviour(QtCase):
    def test_structure(self):
        h = self.harness()
        a = h.app
        self.assertTrue(a.win_visible if hasattr(a, 'win_visible') else h.win.isVisible())
        self.assertTrue(h.win.windowTitle().startswith('Calibration Suite'))
        self.assertIn('WaveSurfer 4104HD', h.win.windowTitle())
        self.assertEqual([a.tabs.tabText(i).strip() for i in range(a.tabs.count())],
                         ['RMS Noise', 'DC Voltage', 'Input Impedance', 'Offset / P1 Mean', 'Bandwidth / LEVSINE', 'Time Base', 'Trigger Level'])
        self.assertFalse(a.tabs.isVisible())                                   # the notebook is never shown (as in Tk)
        self.assertEqual({k: len(getattr(a, k).get_children()) for k in ('dc_tree', 'imp_tree')}, {'dc_tree': 80, 'imp_tree': 28})
        self.assertEqual(a.utree.rowCount() if hasattr(a.utree, 'rowCount') else len(a.utree.get_children()), 209)
        self.assertEqual([r[0] for r in a.shell.sections], ['RMS noise', 'DC voltage', 'Input impedance', 'Offset (P1 mean)', 'Bandwidth (LEVSINE)', 'Time base', 'Trigger level'])
        self.assertEqual([b.text() for b in (a.btn_run, a.btn_section, a.btn_rerun, a.btn_stop, a.btn_clear)],
                         ['▶  Run All Pending', 'Run Shown Section', 'Rerun Selected', '■  Stop', 'Clear function results'])
        self.assertEqual(a.conn_pill.text(), 'Scope: not connected')
        self.assertIn('Edit point', [b.text() for b in h.win.findChildren(QPushButton)])      # the procedure-modification action (pm_live_attach)
        self.assertEqual(a.show_function.get(), 'All functions')

    def test_section_pick_filters_the_table_and_selection_shows_the_detail(self):
        h = self.harness()
        a = h.app
        a.load_demo_data()
        a.refresh_unified(force=True)
        h.port.prompts.clear()
        a.shell.choose_section('DC voltage')
        self.assertEqual(a.show_function.get(), 'DC voltage')
        self.assertEqual(len(a.utree.get_children()), 80)
        first = a.utree.get_children()[0]
        a.utree.selection_set(first)
        QApplication.processEvents()                                     # the table reports a selection change from the event loop (Tk: a virtual event)
        self.assertIn('DC voltage', a.detail.get())
        self.assertIn('Accept:', a.detail.get())
        a.shell.choose_section('All sections')
        self.assertEqual(len(a.utree.get_children()), 209)
        a.show_status.set('Failed (OOT)')
        a.refresh_unified(force=True)
        self.assertEqual(len(a.utree.get_children()), 6)
        self.assertEqual(h.port.prompts, [])

    def test_as_left_progress_counts_the_failed_points_only(self):
        h = self.harness()
        a = h.app
        a.load_demo_data()
        a.refresh_unified(force=True)
        self.assertEqual(a.summary.text.get(), '209 of 209 tested')
        a._mode = __import__('datamode').LEFT                                       # As Left: progress is about the points that failed As Found
        fmap = {'a': {'result': 'FAIL'}, 'b': {'result': 'PASS'}, 'c': {'result': 'FAIL'}}
        lmap = {'a': {'done': True, 'result': 'PASS'}}
        h.V.show_unified(a, [], [{'kind': 'dcv', 'result': 'PASS'}], fmap, lmap, 3, 1, 2)
        self.assertEqual(a.summary.text.get(), '1 of 2 re-run done')
        self.assertEqual(a.summary.ok.text(), '1 now in limits')
        self.assertEqual(a.summary.rem.text(), '1 to re-run')

    def test_filter_combobox_refreshes(self):
        h = self.harness()
        a = h.app
        a.load_demo_data()
        a.refresh_unified(force=True)
        combo = next(c for c in h.win.findChildren(QWidget) if c.accessibleName() == 'Show')
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], list(__import__('datamode').STATUS_FILTERS))
        combo.setCurrentIndex(combo.findText('Failed (OOT)'))
        combo.activated.emit(combo.currentIndex())
        self.assertEqual(a.show_status.get(), 'Failed (OOT)')
        self.assertEqual(len(a.utree.get_children()), 6)

    def test_section_tables_keep_selection_and_scroll(self):
        h = self.harness()
        a = h.app
        a.load_demo_data()
        ids = a.dc_tree.get_children()
        a.dc_tree.selection_set(ids[10])
        a.refresh_dcv_table()
        self.assertEqual(a.dc_tree.selection(), (ids[10],))
        self.assertEqual(h.V.row_index(a.dc_tree, ids[10]), 10)
        h.V.select_and_show(a.dc_tree, ids[40])
        self.assertEqual(h.V.selection(a.dc_tree), (ids[40],))
        self.assertEqual(h.V.children(a.dc_tree), tuple(ids))

    def test_set_grid_replaces_and_updates_rows(self):
        h = self.harness()
        tree = h.app.tb_tree
        V = h.V
        ids = V.set_grid(tree, [(('a', '1', '', '', '', '', '', ''), ('pass',)), (('b', '2', '', '', '', '', '', ''), ('fail',))], active=0)
        self.assertEqual(len(ids), 2)
        tree.selection_set(ids[1])
        ids = V.set_grid(tree, [(('a', '9', '', '', '', '', '', ''), ('pass',)), (('b', '8', '', '', '', '', '', ''), ('pass',))])
        self.assertEqual(tree.selection(), (ids[1],))
        self.assertEqual(tree.item(ids[1], 'values')[1], '8')
        V.set_grid(tree, [])
        self.assertEqual(tree.get_children(), ())

    def test_progress_bars(self):
        h = self.harness()
        a, V = h.app, h.V
        V.set_maximum(a.progress, 12)
        V.set_value(a.progress, 5)
        self.assertEqual((a.progress.value(), a.progress.maximum()), (5, 12))
        V.set_value(a.progress, 99)                                   # never past the maximum
        self.assertEqual(a.progress.value(), 12)

    def test_tab_open_and_titles(self):
        h = self.harness()
        a, V = h.app, h.V
        self.assertTrue(V.tab_open(a, 'dc_window'))
        self.assertFalse(V.tab_open(a, 'no_such_tab'))
        a.dc_rows = []
        a.update_tab_titles()
        self.assertEqual(a.tabs.tabText(a.tabs.indexOf(a.dc_window)), '  DC Voltage  ')
        a.load_demo_data()
        a.update_tab_titles()
        self.assertIn('✔', a.tabs.tabText(a.tabs.indexOf(a.dc_window)))

    def test_hidden_buttons_exist_but_are_never_shown(self):
        h = self.harness()
        a = h.app
        self.assertEqual(a.dc_next_button.text(), 'Start / Next DCV Point')
        self.assertEqual(a.imp_next_button.text(), 'Measure Next Impedance Point')
        self.assertTrue(a.dc_next_button.isHidden() and a.imp_next_button.isHidden())
        h.V.set_state(a.dc_next_button, 'disabled')
        self.assertFalse(a.dc_next_button.isEnabled())

    def test_window_gone_stops_the_periodic_ticks_quietly(self):
        h = self.harness()
        a = h.app
        gone = h.V.window_gone()
        self.assertTrue(issubclass(gone, RuntimeError))
        win = h.win
        h.port.q.clear()
        shiboken6.delete(win)
        a._unified_tick()                                               # catches WindowGone, schedules nothing, raises nothing
        a.update_tab_titles()
        self.assertEqual(h.port.q, [])
        with self.assertRaises(gone):
            h.V.set_state(a.btn_run, 'disabled')
        from PySide6.QtWidgets import QMainWindow
        h.win = QMainWindow()                                           # the harness closes a window in stop()

    def test_a_real_runtime_error_is_not_swallowed(self):
        h = self.harness()
        a = h.app
        with self.assertRaises(RuntimeError) as cm:
            with unittest_patch(a, 'refresh_unified', RuntimeError('engine bug')):
                a._unified_tick()
        self.assertNotIsInstance(cm.exception, h.V.window_gone())

    def test_dialog_open(self):
        h = self.harness()
        a = h.app
        self.assertFalse(h.V.dialog_open(a))
        seen = {}

        def handler(dlg):
            seen['open'] = h.V.dialog_open(a)
            press(dlg, 'OK')
        from qtui import prompts
        Driver().run(lambda: prompts.message(h.win, 'info', 'x', 'y'), handler)
        self.assertTrue(seen['open'])
        self.assertFalse(h.V.dialog_open(a))

    def test_drawer_holds_the_connection_widgets(self):
        h = self.harness()
        a = h.app
        a.shell.open_drawer()
        QApplication.processEvents()
        texts = [w.text() for w in a.shell.drawer.findChildren(QLabel)] + [w.text() for w in a.shell.drawer.findChildren(QPushButton)]
        for t in ('Model', 'Teledyne LeCroy WaveSurfer 4104HD', 'Scope VISA address', 'Test scope', 'Fluke 5560A VISA', 'Fluke baud', 'Test Fluke', 'Test settings...'):
            self.assertIn(t, texts)
        edits = a.shell.drawer.findChildren(QLineEdit)
        self.assertEqual([e.text() for e in edits], [a.visa_address.get(), a.fluke_address.get(), a.fluke_baud.get()])
        edits[1].setText('ASRL3::INSTR')
        self.assertEqual(a.fluke_address.get(), 'ASRL3::INSTR')                 # two-way binding
        a.fluke_address.set('ASRL4::INSTR')
        self.assertEqual(edits[1].text(), 'ASRL4::INSTR')
        QTest.keyClick(a.shell.drawer, Qt.Key.Key_Escape)
        a.shell.close_drawer()

    def test_instrument_id_entry_syncs_the_asset_when_left(self):
        h = self.harness()
        a = h.app
        calls = []
        a.sync_asset = lambda: calls.append(a.instrument_id.get())
        a.shell.id_entry.setFocus()
        a.shell.id_entry.setText('WS-9')
        a.shell.id_entry.editingFinished.emit()
        self.assertIn('WS-9', calls)

    def test_closing_the_window_asks_the_engine(self):
        h = self.harness()
        a = h.app
        a.running = True
        h.rule(HN.title_is('Test running'))
        h.win.close()                                                   # the close button -> the engine's on_close (a question), answered No: the window stays
        QApplication.processEvents()
        self.assertTrue(h.win.isVisible())
        self.assertEqual([p['title'] for p in h.port.prompts], ['Test running'])
        h.clear_rules()
        a.running = False
        h.win.close()
        self.assertEqual(h.port.events[-1][0], 'close')                 # nothing running: the engine closes it

    def test_worker_question_queue_round_trip(self):
        """A worker thread asks the operator through the engine's event queue and blocks on the reply queue; the UI side answers it from process_events."""
        import queue
        h = self.harness()
        a = h.app
        reply = queue.Queue()
        got = []

        def worker():
            a.events.put(('ask', 'Trigger before the level?', 'Did the scope trigger?', reply))
            got.append(reply.get(timeout=10))
        t = threading.Thread(target=worker)
        t.start()
        t.join(0.05)
        h.rule(lambda r: False if r['kind'] == 'ask_yes_no_cancel' else None)
        for _ in range(200):
            a.process_events()
            if not t.is_alive():
                break
            QApplication.processEvents()
        t.join(5)
        self.assertEqual(got, [False])
        self.assertEqual([p['title'] for p in h.port.prompts], ['Trigger before the level?'])

    def test_real_timers_run_the_ticks(self):
        """With the real QtUiPort.after (not the queue of the scenarios) the 500 ms tick and the event pump run by themselves."""
        import WaveSurfer_WS4104HD as W
        from PySide6.QtWidgets import QMainWindow
        import ui_port_qt
        from qtui import app as qapp
        qapp.create_app()
        old = ui_port.set_ui(ui_port_qt.QtUiPort())
        win = QMainWindow()
        try:
            a = W.RMSNoiseApp(win)
            win.show()
            a.dc_running = True
            a.events.put(('status', 'Connected: sim'))
            QTest.qWait(1300)
            self.assertFalse(a.btn_run.isEnabled())                      # _unified_tick ran
            self.assertTrue(a.btn_stop.isEnabled())
            self.assertEqual(a.status.get(), 'Connected: sim')           # process_events ran
            a.dc_running = False
            QTest.qWait(700)
            self.assertTrue(a.btn_run.isEnabled())
        finally:
            win.close()
            win.deleteLater()
            ui_port.set_ui(old)
            QApplication.processEvents()


class _Patch:
    def __init__(self, obj, name, exc):
        self.obj, self.name, self.exc, self.old = obj, name, exc, None

    def __enter__(self):
        self.old = getattr(self.obj, self.name)

        def boom(*a, **k):
            raise self.exc
        setattr(self.obj, self.name, boom)

    def __exit__(self, *a):
        setattr(self.obj, self.name, self.old)
        return False


def unittest_patch(obj, name, exc):
    return _Patch(obj, name, exc)


# ====================================================================================================================================================
class SettingsDialog(QtCase):
    def labels_of_the_tk_dialog(self):
        src = TK_VIEW.read_text(encoding='utf-8')
        block = src[src.index('def show_settings_dialog'):src.index('def show_dcv')]
        rows = block[block.index('rows = ('):block.index('for r, (label, var, kind)')]
        return [ast.literal_eval("'" + t + "'") for t in re.findall(r"\('([^']*)',", rows)]

    def test_rows_and_notes_equal_the_tk_dialog(self):
        import wavesurfer_qt_settings as T
        h = self.harness()
        got = [label for label, _v, _k in T.rows(h.app)]
        self.assertEqual(got, self.labels_of_the_tk_dialog())
        dlg = T.build(h.app)
        texts = [lab.text() for lab in dlg.findChildren(QLabel)]
        self.assertEqual([t for t in texts if t in got], got)
        self.assertIn(T.NOTE_TOP, texts)
        self.assertIn(T.NOTE_BOTTOM, texts)
        self.assertEqual(dlg.windowTitle(), 'Test settings')
        self.assertEqual(button_texts(dlg), ['Close'])
        dlg.deleteLater()

    def test_edits_reach_the_engine_variables_and_close_closes(self):
        h = self.harness()
        a = h.app
        seen = {}

        def handler(dlg):
            f = dlg.fields
            seen['fields'] = list(f)
            for key, text in (('DC voltage: Settle after OPER (s)', '4.5'), ('Time base: Marker period (\u00b5s)', '20'), ('RMS noise: Minimum limits (dB), 9 values', '1,2,3')):
                f[key].selectAll()
                QTest.keyClicks(f[key], text)                              # typed, as the operator does
            f['DC voltage: Automatic Fluke output'].click()
            f['RMS noise: Channel'].setCurrentIndex(2)
            f['RMS noise: Channel'].activated.emit(2)
            press(dlg, 'Close')
        h.port.d.run(a.show_settings_dialog, handler)
        self.assertEqual((a.dc_settle.get(), a.tb_period_us.get(), a.limit_text.get(), a.dc_auto_fluke.get(), a.channel.get()), ('4.5', '20', '1,2,3', False, '3'))
        self.assertEqual(len(seen['fields']), 17)             # 23 rows, 6 of them section headings

    def test_escape_closes(self):
        h = self.harness()

        def handler(dlg):
            dlg.activateWindow()                                           # a key event goes to the active window
            QApplication.processEvents()
            self.assertIs(dlg.focusWidget(), dlg.fields['RMS noise: Channel'])         # the first field has the focus
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
        h.port.d.run(h.app.show_settings_dialog, handler)

    def test_fits_a_small_screen(self):
        import wavesurfer_qt_settings as T
        h = self.harness()
        dlg = T.build(h.app)
        dlg.show()
        QApplication.processEvents()
        scr = dlg.screen().availableGeometry()
        self.assertLessEqual(dlg.height(), scr.height())
        dlg.close()
        dlg.deleteLater()


# ====================================================================================================================================================
class Rendering(QtCase):
    def clipped(self, root):
        """Visible one-line labels / buttons whose text is wider than the widget."""
        bad = []
        for w in root.findChildren(QWidget):
            if not w.isVisible():
                continue
            if isinstance(w, (QPushButton, QLabel)) and w.text() and not (isinstance(w, QLabel) and w.wordWrap()):
                if w.parentWidget() is not None and w.parentWidget().objectName().startswith('qt_'):
                    continue
                need = w.fontMetrics().horizontalAdvance(w.text().split('\n')[0])
                if need > w.width() + 2 and not w.property('elide'):
                    bad.append((type(w).__name__, w.text()[:40], need, w.width()))
        return bad

    def test_renders_at_the_designed_sizes_without_clipped_text(self):
        h = self.harness()
        a = h.app
        a.load_demo_data()
        for size in ((1320, 860), (1000, 680), (900, 640)):
            h.win.resize(*size)
            for _ in range(5):
                QApplication.processEvents()
            pm = h.win.grab()
            self.assertFalse(pm.isNull())
            self.assertGreaterEqual(h.win.width(), 900)
            bad = [b for b in self.clipped(h.win) if b[0] == 'QPushButton']
            self.assertEqual(bad, [], f'clipped at {size}')

    def test_small_window_folds_the_sidebar_and_shortens_the_buttons(self):
        h = self.harness()
        a = h.app
        h.win.resize(960, 660)
        for _ in range(8):
            QApplication.processEvents()
        self.assertEqual(a.btn_run.text(), '▶  Run')
        self.assertEqual(a.btn_stop.text(), '■ Stop')
        h.win.resize(1320, 860)
        for _ in range(8):
            QApplication.processEvents()
        self.assertEqual(a.btn_run.text(), '▶  Run All Pending')

    def test_keyboard_reaches_the_main_controls(self):
        h = self.harness()
        a = h.app
        for w in (a.btn_run, a.btn_section, a.btn_rerun, a.shell.id_entry, a.shell.serial_entry, a.utree):
            self.assertTrue(w.focusPolicy() & Qt.FocusPolicy.TabFocus, w)


if __name__ == '__main__':
    unittest.main()
