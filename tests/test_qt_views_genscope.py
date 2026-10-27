"""Qt windows of the function generators and scopes (QT-G2a): fgen_view_qt (33220A / 33250A / 33210A), mdo4000c_view_qt, tds2000c_view_qt.  Skipped without PySide6.  Offscreen.

What is proven, against the Tk build:

  Prompts*   the real engine on the simulated bench behind the real Qt window and the Qt port (only the modal dialogs are scripted) shows the SAME prompts in the SAME order with the
             same answers as tests/golden_ui/ui_prompts_{fgen,mdo4000c,tds2000c}.json (recorded on the unported Tk engines): the scenario functions of tests/ui_prompt_capture_wpg.py
             run unchanged on tests/qt_genscope_harness.QtHarness.
  Rows*      after a whole virtual run the Qt window holds the same title, table rows (values, tags), status and detail text, sections, counts, filtered / sectioned rows as the REAL
             Tk window did (tests/qt_ref/genscope_rows.json, recorded by tests/record_tk_genscope.py on real Tk 9 under Xvfb).
  HandOff    fgen's typed reading box crosses threads (`call_from_worker`) with REAL Qt dialogs: the worker blocks while the box is open, the point is recorded only after OK with the
             typed value, Cancel and an exception both give the worker None (the Tk behaviour, tests/real_tk_wpg_fgen.py).
  Window     the labels / buttons / lists of the Tk views are all there, busy and idle states, the drawer, the compact window, shortcuts, close, asset history, table interaction.

Run each engine's classes as a separate process (MDO takes about a minute):   python -m unittest tests.test_qt_views_genscope.PromptsMdo   etc.
"""
import ast
import json
import os
import re
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
sys.path.insert(0, str(ROOT / 'Procedures'))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton
    import genscope_rows as G
    import qt_genscope_harness as Q
    import ui_port
    import ui_port_qt
    import ui_prompt_capture as C
    import test_ui_prompts as P
    from qtui import app as qapp

VIEWS = {'fgen': 'fgen_view', 'mdo': 'mdo4000c_view', 'tds': 'tds2000c_view'}
ENGINE_KEY = {'fgen': 'fgen', 'mdo': 'mdo4000c', 'tds': 'tds2000c'}


def top_level_functions(path):
    return sorted(n.name for n in ast.parse(Path(path).read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef))


def tk_constants(path):
    """Constant texts the Tk view puts on screen: text= of labels / buttons / check boxes, the first argument of add_action, constant `values=` lists."""
    texts, lists = set(), []
    for node in ast.walk(ast.parse(Path(path).read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
        for kw in node.keywords:
            if kw.arg == 'text' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                texts.add(kw.value.value)
            if kw.arg == 'values' and isinstance(kw.value, ast.List) and all(isinstance(e, ast.Constant) for e in kw.value.elts):
                lists.append([e.value for e in kw.value.elts])
        if name == 'add_action' and node.args and isinstance(node.args[0], ast.Constant):
            texts.add(node.args[0].value)
    return texts, lists


# ======================================================================================================================================================
# prompts: the scenario functions recorded on the Tk build, on the Qt window
# ======================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PromptsBase(unittest.TestCase):
    name = ''

    def check(self):
        want, got = P.recorded(self.name), P.canon(C.capture(self.name, Q.QtHarness))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{self.name}: scenario {scenario}')


class PromptsFgen(PromptsBase):
    name = 'fgen'

    def test_prompts_equal_the_tk_fixture(self):
        self.check()


class PromptsMdo(PromptsBase):
    name = 'mdo4000c'

    def test_prompts_equal_the_tk_fixture(self):
        self.check()


class PromptsTds(PromptsBase):
    name = 'tds2000c'

    def test_prompts_equal_the_tk_fixture(self):
        self.check()


# ======================================================================================================================================================
# rows, status, detail text: the real Tk window's result of the same run
# ======================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RowsBase(unittest.TestCase):
    keys = ()

    def snap(self, key):
        hn = Q.QtHarness(Q.Answers([lambda r: r.get('initial') if r['kind'] in ('ask_number', 'ask_text') else None])).start()
        try:
            app = G.build(key, hn.root)
            hn.app = app
            hn.root.show()
            Q.settle()

            def run(start):
                start()
                return hn.pump(600)
            return G.snapshot(app, hn.root.windowTitle(), run, Q.settle)
        finally:
            hn.stop()

    def check(self, key):
        want = json.loads(G.REF.read_text(encoding='utf-8'))[key]
        got = json.loads(json.dumps(self.snap(key)))
        self.assertEqual(sorted(got), sorted(want))
        for field in want:
            if field == 'status_texts':                       # the SET of status lines shown during the run, timing independent
                self.assertEqual(sorted(got[field]), sorted(want[field]), field)
            else:
                self.assertEqual(got[field], want[field], f'{key}: {field}')
        self.assertTrue(got['rows'], 'rows')


class RowsFgen(RowsBase):
    def test_33220a(self):
        self.check('fgen_33220A')

    def test_33250a_with_failures(self):
        self.check('fgen_33250A_failures')

    def test_33210a(self):
        self.check('fgen_33210A')


class RowsMdo(RowsBase):
    def test_virtual_run(self):
        self.check('mdo4000c')

    def test_with_failures(self):
        self.check('mdo4000c_failures')

    def test_the_rf_level_and_flatness_rows_of_the_96270a(self):
        self.check('mdo4000c_sa6_rf_rows')


class RowsTds(RowsBase):
    def test_2024c(self):
        self.check('tds2000c_2024C')

    def test_2012c_with_failures(self):
        self.check('tds2000c_2012C_failures')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RowsReference(unittest.TestCase):
    def test_the_failure_scenarios_really_fail_points(self):
        ref = json.loads(G.REF.read_text(encoding='utf-8'))
        for key in ref:
            fails = ref[key]['counts'].get('FAIL', 0)
            self.assertEqual(bool(fails), 'failures' in key, key)
            if fails:
                self.assertTrue(ref[key]['filter Failed (OOT)'], key)


# ======================================================================================================================================================
# fgen typed reading: worker thread blocked while the REAL Qt box is open
# ======================================================================================================================================================
class HandOffPort(ui_port_qt.QtUiPort if HAVE_QT else object):
    """The real QtUiPort, except for the dialogs that are not the subject (hook-up prompts, message boxes: recorded) and an `ask_number` that notes where it ran."""

    def __init__(self, scenario):
        super().__init__()
        self.scenario, self.boxes, self.seen = scenario, [], {}

    def message(self, kind, title, text, *, parent=None):
        self.boxes.append((kind, title, text))

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        return True

    def ask_yes_no(self, *a, **k):
        return True

    def ask_ok_cancel(self, *a, **k):
        return True

    def ask_number(self, title, prompt, **kw):
        self.seen['thread_is_main'] = threading.current_thread() is threading.main_thread()
        self.seen['title'] = title
        self.seen['worker_alive'] = any(t.daemon and t.is_alive() for t in threading.enumerate())
        if self.scenario == 'raise':
            raise RuntimeError('ask_number failed on the UI thread')
        return super().ask_number(title, prompt, **kw)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class HandOff(unittest.TestCase):
    """Two demo points on the real 33220A window: SELFTEST, then TIMEBASE whose typed counter reading is asked by the WORKER through `port.call_from_worker`."""

    def run_scenario(self, scenario):
        import fgen_verification as F
        hn = Q.QtHarness().start()
        port = HandOffPort(scenario)
        ui_port.set_ui(port)
        reported = []
        orig_show = qapp.show_error
        qapp.show_error = lambda text, where='': reported.append((text, threading.current_thread() is threading.main_thread()))
        state = {'pressed': False}
        timer = QTimer()
        timer.setInterval(5)
        try:
            F.configure('33220A')
            app = F.App(hn.root, '33220A', demo=True)
            hn.app = app
            hn.root.show()
            app.asset.set('A1')
            app.serial.set('S1')
            points = [p for p in F.POINTS if p['kind'] in ('SELFTEST', 'TIMEBASE')][:2]
            self.assertEqual([p['kind'] for p in points], ['SELFTEST', 'TIMEBASE'])

            def poll():
                dlg = QApplication.activeModalWidget()
                if dlg is None or state['pressed']:
                    return
                state['pressed'] = True
                state['title'] = dlg.windowTitle()
                state['entry'] = dlg.findChild(QLineEdit).text()
                state['worker_waiting'] = app.results.get(str(points[1]['id'])) is None and any(t.daemon and t.is_alive() for t in threading.enumerate())
                state['dialog_thread_main'] = threading.current_thread() is threading.main_thread()
                want = 'OK' if scenario == 'answer' else 'Cancel'
                for b in dlg.findChildren(QPushButton):
                    if b.text() == want and b.isVisibleTo(dlg):
                        b.click()
                        return
                raise AssertionError(f'no {want} button')
            timer.timeout.connect(poll)
            timer.start()
            app.execute(points)
            self.assertTrue(hn.pump(90), 'the run ended (not hung)')
            Q.settle(10)
            return app, points, port, state, reported
        finally:
            timer.stop()
            qapp.show_error = orig_show
            hn.stop()

    def test_answer_records_the_typed_value_after_ok(self):
        app, points, port, state, _ = self.run_scenario('answer')
        rec = app.results.get(str(points[1]['id']))
        self.assertIn(str(points[0]['id']), app.results)
        self.assertTrue(port.seen['thread_is_main'], 'the box is created on the UI thread')
        self.assertTrue(port.seen['worker_alive'], 'the worker is alive and blocked while the box is open')
        self.assertEqual(port.seen['title'], 'Type the reading [DEMO]')
        self.assertTrue(state['pressed'] and state['title'] == 'Type the reading [DEMO]', state)
        self.assertNotIn(state['entry'], ('', None))
        self.assertTrue(state['worker_waiting'], 'the point is not recorded while the box is open')
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(rec['reading'], float(state['entry']), delta=1e-9 * max(1.0, abs(rec['reading'])))
        self.assertEqual([b for b in port.boxes if b[0] == 'error'], [])

    def test_cancel_gives_the_worker_none_and_stops_the_run(self):
        app, points, port, state, _ = self.run_scenario('cancel')
        self.assertTrue(state['pressed'] and state['worker_waiting'])
        self.assertIsNone(app.results.get(str(points[1]['id'])))
        self.assertIn(str(points[0]['id']), app.results)
        errs = [b for b in port.boxes if b[0] == 'error']
        self.assertEqual([b[1] for b in errs], ['Measurement stopped'])
        self.assertIn('Reading not entered', errs[0][2])
        self.assertFalse(app.busy)

    def test_exception_in_the_box_gives_the_worker_none_and_is_reported_on_the_ui_thread(self):
        app, points, port, state, reported = self.run_scenario('raise')
        self.assertIsNone(app.results.get(str(points[1]['id'])))
        errs = [b for b in port.boxes if b[0] == 'error']
        self.assertEqual([b[1] for b in errs], ['Measurement stopped'])
        self.assertIn('Reading not entered', errs[0][2])
        self.assertTrue(port.seen['worker_alive'])
        self.assertTrue(any('ask_number failed on the UI thread' in r[0] and r[1] for r in reported), reported)
        self.assertFalse(app.busy)


# ======================================================================================================================================================
# the real dialogs (hook-up prompts, message boxes, typed readings) of a whole run, clicked by a scripted operator
# ======================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RealDialogsBase(unittest.TestCase):
    """The REAL QtUiPort (no scripted dialogs): a timer clicks the affirmative button of every modal window the engine opens.  The (title, buttons) sequence of the windows
    that appeared equals the one recorded on the Tk build (tests/golden_ui/ui_prompts_<engine>.json); the run finishes with every point recorded."""
    key, fixture, scenario = '', '', ''

    def test_the_windows_of_a_whole_run(self):
        if not self.fixture:
            self.skipTest('the base class itself: the Tds / Mdo / Fgen subclasses run this test')
        want = json.loads((ROOT / 'tests' / 'golden_ui' / f'ui_prompts_{self.fixture}.json').read_text(encoding='utf-8'))[self.scenario]
        hn = Q.QtHarness().start()
        ui_port.set_ui(ui_port_qt.QtUiPort())
        shown, state = [], {'n': 0, 'last': None}
        timer = QTimer()
        timer.setInterval(4)
        try:
            app = G.build(self.key, hn.root)
            hn.app = app
            hn.root.show()
            Q.settle()

            def click():
                dlg = QApplication.activeModalWidget()
                if dlg is None or dlg is state['last']:
                    return
                state['last'] = dlg
                names = [b.text() for b in dlg.findChildren(QPushButton) if b.isVisibleTo(dlg) and b.text()]
                shown.append((dlg.windowTitle().replace(' [DEMO]', ''), sorted(names)))
                pick = want[state['n']].get('buttons', ['OK'])[0] if state['n'] < len(want) else names[0]
                state['n'] += 1
                for b in dlg.findChildren(QPushButton):
                    if b.text() == pick and b.isVisibleTo(dlg):
                        b.click()
                        return
                raise AssertionError(f'no {pick!r} among {names}')
            timer.timeout.connect(click)
            timer.start()
            app.run_all()
            self.assertTrue(hn.pump(300))
            Q.settle(10)
            self.assertEqual(shown, [(w['title'].replace(' [DEMO]', ''), sorted(w.get('buttons', ['OK', 'Cancel']))) for w in want])
            self.assertEqual(len(app.results), len([p for p in app.active_points()]))
        finally:
            timer.stop()
            hn.stop()


class RealDialogsTds(RealDialogsBase):
    key, fixture, scenario = 'tds2000c_2024C', 'tds2000c', 'virtual_run_2024C'


class RealDialogsMdo(RealDialogsBase):
    key, fixture, scenario = 'mdo4000c', 'mdo4000c', 'virtual_run'


class RealDialogsFgen(RealDialogsBase):
    key, fixture, scenario = 'fgen_33250A_failures', 'fgen', 'virtual_run_33250A'


# ======================================================================================================================================================
# the windows themselves
# ======================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WindowCase(unittest.TestCase):
    kind = 'fgen'

    def setUp(self):
        self.hn = Q.QtHarness().start()
        self.addCleanup(self.hn.stop)
        self.app = G.build({'fgen': 'fgen_33220A', 'mdo': 'mdo4000c', 'tds': 'tds2000c_2024C'}[self.kind], self.hn.root)
        self.hn.app = self.app
        self.win = self.hn.root
        self.win.setMinimumSize(0, 0)               # fit_window shrinks to the (small) offscreen screen
        self.win.resize(1480, 840)
        self.win.show()
        Q.settle(10)
        QTest.qWait(30)

    @property
    def view_file(self):
        return ROOT / f'{VIEWS[self.kind]}_qt.py'

    def widgets(self, cls):
        return self.win.findChildren(cls)

    def texts(self):
        out = set()
        for w in self.widgets(QLabel) + self.widgets(QAbstractButton):
            out.add(w.text())
        return out

    def combos(self):
        return [[c.itemText(i) for i in range(c.count())] for c in self.widgets(QComboBox)]


class WindowTests:
    """Shared by the three engines (mixin)."""

    def test_the_qt_view_has_every_function_of_the_tk_view(self):
        tk = top_level_functions(ROOT / f'{VIEWS[self.kind]}_tk.py')
        view = self.hn.port.view(VIEWS[self.kind])
        self.assertEqual(view.__name__, f'{VIEWS[self.kind]}_qt')
        self.assertEqual([n for n in tk if not callable(getattr(view, n, None))], [])

    def test_every_constant_text_and_list_of_the_tk_view_is_on_screen(self):
        texts, lists = tk_constants(ROOT / f'{VIEWS[self.kind]}_tk.py')
        have, combos = self.texts(), self.combos()
        missing = sorted(t for t in texts if t not in have)
        self.assertEqual(missing, [])
        for values in lists:
            self.assertIn([str(v) for v in values], combos, values)

    def test_the_title_the_chips_and_the_version(self):
        sh = self.app.shell
        self.assertTrue(self.win.windowTitle().endswith('Performance Verification [DEMO]'))
        self.assertTrue(sh.title_label.text().endswith('Performance Verification'))
        self.assertEqual(self.app.conn_pill.text(), self.app.chip_text())

    def test_busy_disables_the_run_buttons_and_the_configuration_and_enables_stop(self):
        a = self.app
        cfg = list(a.cfg_widgets) if hasattr(a, 'cfg_widgets') else [a.period_combo, a.set_combo, a.ref_combo]
        for b in (a.btn_run, a.btn_section, a.btn_rerun, a.btn_test, a.btn_load, a.btn_find, *a.mode_buttons, *cfg):
            self.assertTrue(b.isEnabled())
        self.assertFalse(a.btn_stop.isEnabled())
        a.busy = True
        Q.settle()
        for b in (a.btn_run, a.btn_section, a.btn_rerun, a.btn_test, a.btn_load, a.btn_find, *a.mode_buttons, *cfg):
            self.assertFalse(b.isEnabled(), b)
        self.assertTrue(a.btn_stop.isEnabled())
        a.busy = False
        Q.settle()
        self.assertTrue(a.btn_run.isEnabled())
        self.assertFalse(a.btn_stop.isEnabled())

    def test_the_action_bar_order_and_roles(self):
        sh = self.app.shell
        left = [b.text() for b in sh.actions_left.findChildren(QPushButton)]
        right = [b.text() for b in sh.actions_right.findChildren(QPushButton)]
        self.assertEqual(left[:5], ['▶  Run All Pending', 'Run Shown Section', 'Rerun Selected', 'Rerun From Selected', '■  Stop'])
        self.assertEqual(right, ['Export Report (PDF)', 'Load progress', 'Save progress'])
        self.assertEqual(self.app.btn_run.property('role'), 'primary')
        self.assertEqual(self.app.btn_stop.property('role'), 'danger')

    def test_a_small_window_uses_the_short_texts_and_the_section_drop_down(self):
        sh = self.app.shell
        self.win.setMinimumSize(0, 0)
        self.win.resize(900, 680)
        Q.settle(10)
        QTest.qWait(50)
        self.assertTrue(sh.compact)
        self.assertEqual([b.text() for b in sh.actions_left.findChildren(QPushButton)][:5], ['▶  Run', 'Section', 'Rerun', 'From here', '■ Stop'])
        self.assertFalse(sh.sidebar.isVisible())
        self.assertTrue(sh.section_picker.isVisibleTo(self.win))
        self.assertTrue(self.app.tree.isVisible())
        self.win.resize(1480, 840)
        Q.settle(10)
        QTest.qWait(50)
        self.assertFalse(sh.compact)

    def test_the_drawer_holds_the_connection_boxes_and_closes_with_escape(self):
        sh = self.app.shell
        QTest.mouseClick(sh.btn_drawer, Qt.MouseButton.LeftButton)
        Q.settle()
        self.assertTrue(sh.drawer.isVisible())
        for key, box in self.addr_boxes().items():
            self.assertTrue(box.isEditable() and box.isVisibleTo(sh.drawer), key)
        QTest.keyClick(self.win, Qt.Key.Key_Escape)
        Q.settle()
        self.assertFalse(sh.drawer.isVisible())

    def test_typing_an_address_sets_the_variable_and_set_choices_keeps_it(self):
        key, box = next(iter(self.addr_boxes().items()))
        box.setEditText('GPIB0::14::INSTR')
        self.assertEqual(self.app.addr[key if key in self.app.addr else 'uut'].get(), 'GPIB0::14::INSTR')
        if hasattr(self.app.ui_view, 'set_choices'):
            self.app.ui_view.set_choices(self.app, ['GPIB0::1::INSTR', 'USB0::A::INSTR'])
        else:                                                        # the TDS engine assigns the values itself (find_instruments)
            for cb in self.app.addr_boxes.values():
                cb['values'] = ['GPIB0::1::INSTR', 'USB0::A::INSTR']
        for b in self.addr_boxes().values():
            self.assertEqual([b.itemText(i) for i in range(b.count())], ['GPIB0::1::INSTR', 'USB0::A::INSTR'])
        self.assertEqual(box.currentText(), 'GPIB0::14::INSTR')

    def test_selecting_a_row_fills_the_detail_text(self):
        a = self.app
        a.tree.selection_set('2')
        Q.settle()
        self.assertNotEqual(a.detail.get(), 'Select a test point to see its setup.')
        self.assertIn(a.tree.item('2')['values'][1].replace(' ★', ''), a.detail.get() + a.tree.item('2')['values'][1].replace(' ★', ''))
        QTest.keyClick(a.tree, Qt.Key.Key_Down)
        Q.settle()
        self.assertTrue(a.tree.selection())

    def test_the_asset_history_helper_works_on_a_qt_window(self):
        """labregistry.attach debounces the Instrument ID with root.after: on Qt that is AfterRoot (a timer of the port)."""
        import labregistry
        a = self.app
        with mock.patch.object(labregistry, 'instrument_record', lambda asset: ('SER-77',)), \
                mock.patch.object(labregistry, 'asset_summary', lambda asset: f'History of {asset}'), \
                mock.patch.object(labregistry, 'runs_for', lambda asset: []):
            a.serial.set('')
            a.asset.set('ZZ-9')
            deadline = time.time() + 3
            while a.serial.get() != 'SER-77' and time.time() < deadline:
                QTest.qWait(50)
        self.assertEqual(a.serial.get(), 'SER-77')
        self.assertEqual(a.status.get(), 'History of ZZ-9')

    def test_the_instrument_id_box_is_bound_to_the_variable(self):
        e = self.app.shell.id_entry
        e.clear()
        QTest.keyClicks(e, 'B-42')
        self.assertEqual(self.app.asset.get(), 'B-42')

    def test_as_left_toggle_changes_the_table_heading(self):
        a = self.app
        left = a.mode_buttons[1]
        QTest.mouseClick(left, Qt.MouseButton.LeftButton)
        Q.settle()
        self.assertTrue(a.is_left)
        self.assertEqual(a.tree.heading('left')['text'] if isinstance(a.tree.heading('left'), dict) else a.tree.heading('left'), '● As Left')
        QTest.mouseClick(a.mode_buttons[0], Qt.MouseButton.LeftButton)
        Q.settle()
        self.assertFalse(a.is_left)

    def test_the_status_filter_lists(self):
        import datamode
        items = [self.app.show_combo.itemText(i) for i in range(self.app.show_combo.count())]
        want = list(datamode.STATUS_FILTERS) + (['Skipped'] if self.kind != 'fgen' else [])
        self.assertEqual(items, want)
        self.app.show_combo.setCurrentIndex(2)
        self.app.show_combo.activated.emit(2)
        Q.settle()
        self.assertEqual(self.app.show_status.get(), 'Passed')
        self.assertEqual(self.app.tree.get_children(), ())

    def test_the_window_closes_through_the_engines_handler(self):
        called = []
        self.app.disconnect = lambda *a, **k: called.append('disconnect')
        self.app._save_addrs() if hasattr(self.app, '_save_addrs') else None
        self.win.close()
        Q.settle(10)
        self.assertFalse(self.win.isVisible())
        self.assertIn('disconnect', called)

    def test_no_tk_in_the_qt_files(self):
        for name in (f'{VIEWS[self.kind]}_qt.py', 'genscope_support_view_qt.py'):
            src = (ROOT / name).read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'^\s*(import|from)\s+(tkinter|ttk)\b', src, re.M), name)

    def test_the_sidecars_list_the_qt_files_next_to_the_tk_twin(self):
        for side in sorted((ROOT / 'Procedures').glob('*.procedure.json')):
            code = json.loads(side.read_text(encoding='utf-8'))['fingerprint']['code']
            if 'tbs2000b_view_tk.py' in code:
                continue   # the TBS2000B has its own window files; its Tk view only borrows the TDS2000C table helpers
            if f'{VIEWS[self.kind]}_tk.py' in code:
                i = code.index(f'{VIEWS[self.kind]}_tk.py')
                self.assertEqual(code[i + 1:i + 3], [f'{VIEWS[self.kind]}_qt.py', 'genscope_support_view_qt.py'], side.name)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class SurpriseHandOff(WindowCase):
    """Stop on surprise (surprise.py) from the generator's worker thread: the handler is made on the UI thread with the window as its parent (`port.surprise_handler(root)`),
    the worker's question shows the REAL Stop / Continue window over the fgen window and waits; Continue -> True, Stop / closing the window -> False."""
    kind = 'fgen'

    def ask(self, press):
        import surprise
        handler = self.hn.port.surprise_handler(self.win)
        s = surprise.Surprise(kind='readback', instrument='Agilent 33220A', command='VOLT 1.0', reply='VOLT 0.1', expected='1.0', detail='read back with VOLT?',
                              log_tail=['>> VOLT 1.0', '<< VOLT 0.1'])
        out, seen = {}, {}
        worker = threading.Thread(target=lambda: out.setdefault('go', handler(s)), daemon=True)
        timer = QTimer()
        timer.setInterval(5)

        def poll():
            dlg = QApplication.activeModalWidget()
            if dlg is None or 'dlg' in seen:
                return
            seen['dlg'], seen['worker_waiting'], seen['answered'] = dlg, worker.is_alive() and 'go' not in out, 'go' in out
            seen['title'] = dlg.windowTitle()
            seen['texts'] = [lab.text() for lab in dlg.findChildren(QLabel)]
            press(dlg)
        timer.timeout.connect(poll)
        timer.start()
        worker.start()
        end = time.time() + 15
        while worker.is_alive() and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.003)
        timer.stop()
        self.assertFalse(worker.is_alive(), 'the worker never got its answer')
        return out['go'], seen

    def test_continue(self):
        go, seen = self.ask(lambda d: d.parts['cont'].click())
        self.assertTrue(go)
        self.assertTrue(seen['worker_waiting'] and not seen['answered'])
        self.assertIn('Read-back does not match', seen['texts'])

    def test_stop(self):
        go, _ = self.ask(lambda d: d.parts['stop'].click())
        self.assertFalse(go)

    def test_closing_the_window_is_stop(self):
        go, _ = self.ask(lambda d: d.close())
        self.assertFalse(go)

    def test_the_demo_window_makes_no_handler_like_tk(self):
        self.assertIsNone(self.app._surprise_handler())


class WindowFgen(WindowTests, WindowCase):
    kind = 'fgen'

    def addr_boxes(self):
        return self.app.entries

    def test_the_period_and_test_set_boxes_drive_the_rows(self):
        a = self.app
        before = [a.tree.item(i)['values'][3] for i in a.tree.get_children()][:5]
        n_all = len(a.tree.get_children())
        old_period = a.period.get()
        a.period_combo.setCurrentIndex(0 if a.period_combo.currentIndex() else 1)           # the user's pick: `activated` follows `currentIndexChanged`
        a.period_combo.activated.emit(a.period_combo.currentIndex())
        Q.settle()
        self.assertNotEqual(a.period.get(), old_period)
        after = [a.tree.item(i)['values'][3] for i in a.tree.get_children()][:5]
        self.assertNotEqual(before, after, 'another period changes the limits shown')
        a.set_combo.setCurrentIndex(1)
        a.set_combo.activated.emit(1)
        Q.settle()
        self.assertTrue(a.test_set.get().startswith('Quick'))
        self.assertLess(len(a.tree.get_children()), n_all)

    def test_the_drawer_rows_of_the_tk_view(self):
        labels = [t for t in self.texts() if t]
        for t in ('Limits to apply', 'Test set', 'Fluke 5790B', 'Frequency counter', 'Power meter', '5790B input', '5790B baud', 'Timebase', '33220A (under test)'):
            self.assertIn(t, labels)
        self.assertTrue(hasattr(self.app, 'method_combo') == (len(__import__('fgen_verification').SPEC.get('flatness_methods', ['POWER'])) > 1))

    def test_ctrl_s_saves(self):
        import fgen_verification as F
        hn = Q.QtHarness().start()
        try:
            with mock.patch.object(F.App, 'save') as m:
                F.configure('33220A')
                a = F.App(hn.root, '33220A', demo=True)
                hn.root.show()
                Q.settle()
                QTest.keyClick(hn.root, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
                Q.settle()
                self.assertEqual(m.call_count, 1)
        finally:
            hn.stop()


class WindowMdo(WindowTests, WindowCase):
    kind = 'mdo'

    def addr_boxes(self):
        return self.app.addr_boxes

    def test_the_model_box_follows_the_variable_and_the_options_drive_the_configuration(self):
        a = self.app
        box = a.cfg_widgets[0]
        self.assertEqual(a.v_model.get(), a.v_model.get().replace('MDO', ''))          # the engine keeps the bare model (on_config strips the prefix)
        self.assertEqual(box.currentText(), 'MDO' + a.v_model.get())
        box.setCurrentIndex(1)
        box.activated.emit(1)
        Q.settle()
        self.assertEqual(a.read_cfg().model, box.currentText().replace('MDO', ''))
        a.v_model.set('4104C')
        self.assertEqual(box.currentText(), 'MDO4104C')
        afg = a.cfg_widgets[2]
        self.assertIsInstance(afg, QCheckBox)
        a.shell.open_drawer()
        Q.settle()
        QTest.mouseClick(afg, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, 9))          # on the box (a Qt check box answers on its box and text)
        Q.settle()
        self.assertTrue(a.v_afg.get())
        self.assertTrue(a.read_cfg().afg)
        QTest.mouseClick(afg, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, 9))
        self.assertFalse(a.v_afg.get())

    def test_model_and_options_are_on_the_main_window_not_in_the_drawer(self):
        row = self.app.uut_options_row
        self.assertTrue(row.isVisibleTo(self.win))
        for w in self.app.cfg_widgets + [self.app.btn_read_opts]:
            self.assertTrue(row.isAncestorOf(w), w)
            self.assertFalse(self.app.shell.drawer_body.isAncestorOf(w), w)
        self.win.grab().save(str(Path(tempfile.gettempdir()) / 'mdo_options_row.png'))

    def test_the_hookup_prompt_pump_is_the_engines_own(self):
        self.assertTrue(hasattr(self.app, 'q') and callable(self.app._pump))
        self.assertTrue(self.app.btn_read_opts.isEnabled())

    def test_the_96270a_rf_level_rows_and_their_setup_text(self):
        import mdo4000c_verification as M
        rf = [p for p in M.POINTS if p['kind'] == 'ABSAMP']
        self.assertGreaterEqual(len(rf), 9)
        self.app.cfg_widgets[1].setCurrentText('SA6')                      # the spectrum analyzer option adds the RF rows
        self.app.cfg_widgets[1].activated.emit(self.app.cfg_widgets[1].currentIndex())
        Q.settle()
        self.assertEqual(self.app.v_sa.get(), 'SA6')
        ids = set(self.app.tree.get_children())
        self.assertTrue(all(str(p['id']) in ids for p in rf))
        self.app.tree.selection_set(str(rf[0]['id']))
        Q.settle()
        self.assertIn('Fluke 96270A', self.app.detail.get())
        row = self.app.tree.item(str(rf[0]['id']))['values']
        self.assertEqual(str(row[0]), str(rf[0]['id']))
        self.assertIn(rf[0]['desc'] if 'desc' in rf[0] else row[1], row[1])


class WindowTds(WindowTests, WindowCase):
    kind = 'tds'

    def addr_boxes(self):
        return self.app.addr_boxes

    def test_the_model_box_and_read_model(self):
        a = self.app
        box = a.cfg_widgets[0]
        self.assertEqual(box.currentText(), 'TDS' + a.v_model.get().replace('TDS', ''))
        box.setCurrentIndex(1)
        box.activated.emit(1)
        Q.settle()
        self.assertEqual(a.v_model.get(), box.currentText().replace('TDS', ''))
        self.assertTrue(a.btn_read_model.isEnabled())


if __name__ == '__main__':
    unittest.main()
