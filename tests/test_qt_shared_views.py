"""Qt twins of the shared helper windows (surprise_view_qt, datamode_view_qt, manual_override_view_qt, run_queue_view_qt, procmods_view_qt, calibrator_fit_view_qt).

Headless (QT_QPA_PLATFORM=offscreen), skipped when PySide6 is not importable.  The surprise tests prove the worker-thread protocol of surprise.py on Qt: a worker
thread asks, the poller (a Qt single-shot timer on the UI thread) shows the dialog on the UI thread and answers; with no event loop the answer is Stop after the
5 s wait (shortened here).  The manual-override test replays, in the order of the scenario `overrides_datamode_note_reset_8808a` of tests/golden_ui/ui_prompts_shared.json,
the manual-override prompts of ManualOverrideMixin (a stand-in App) and compares the records the port saw with the fixture; the entry window is driven with QTest."""
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import tkinter  # noqa: F401
except ImportError:                                  # the CI sandbox has none: handheld_dmm (manual_override.parse_reading) imports it
    import _tk_stub
    _tk_stub.install()

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import importlib
    import unittest.mock
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget
    import ui_port
    import surprise
    import datamode
    import manual_override as MO
    from qtui import app as qapp
    from qtui.table import Column, DataTable
    from qtui.widgets import Banner, ModalDialog
    import surprise_view_qt, datamode_view_qt, manual_override_view_qt, run_queue_view_qt, procmods_view_qt, calibrator_fit_view_qt  # noqa: E401

    class QtViewPort(ui_port.ScriptedUiPort):
        """The scripted port with the Qt window modules: view('x_view') -> x_view_qt (what ui_port_qt will do)."""

        def view(self, name):
            return importlib.import_module(f'{name}_qt')


def pump_until(cond, timeout=8.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.003)
    return cond()


GOLDEN = json.loads((ROOT / 'tests' / 'golden_ui' / 'ui_prompts_shared.json').read_text(encoding='utf-8'))


def a_surprise(**kw):
    base = dict(kind='readback', instrument='Fluke 8808A', command='RANGE 2', reply='RANGE 3', expected='2', detail='read back with RANGE?',
                log_tail=[f'line {i}' for i in range(20)])
    base.update(kw)
    return surprise.Surprise(**base)


class Clicker:
    """Answers whatever modal dialog is open: `action(dialog)` once per dialog (the UI thread's QTimer, so it also works inside a nested exec)."""

    def __init__(self, action):
        self.action, self.seen, self.timer = action, [], QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(15)

    def tick(self):
        w = QApplication.activeModalWidget()
        if isinstance(w, ModalDialog) and id(w) not in {id(x) for x in self.seen}:
            self.seen.append(w)
            self.action(w)

    def stop(self):
        self.timer.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp.create_app()

    def setUp(self):
        self.port = QtViewPort()
        self.old = ui_port.set_ui(self.port)

    def tearDown(self):
        ui_port.set_ui(self.old)


# ====================================================================================================================================================
# surprise
# ====================================================================================================================================================
class SurpriseDialog(QtCase):
    def test_stop_and_continue_split(self):
        both = surprise_view_qt.build(None, 'Stop on surprise', a_surprise())
        self.assertEqual([b.text() for b in both._buttons.values()], ['Stop', 'Continue'])
        self.assertIsNotNone(both.parts['cont'])
        only = surprise_view_qt.build(None, 'Stop on surprise', a_surprise(stop_only=True))
        self.assertEqual([b.text() for b in only._buttons.values()], ['Stop'])
        self.assertIsNone(only.parts['cont'])
        texts = [w.text() for w in only.findChildren(type(only.title_label))]
        self.assertTrue(any(t == 'Continue is not offered here: the run cannot safely go on from this point.' for t in texts))
        self.assertFalse(any('Continue is not offered' in w.text() for w in both.findChildren(type(both.title_label))))

    def test_content_matches_the_tk_window(self):
        s = a_surprise(detail='note')
        d = surprise_view_qt.build(None, 'T', s)
        self.assertEqual(d.windowTitle(), 'T')
        self.assertEqual(d.title_label.text(), surprise.KINDS['readback'])
        texts = [w.text() for w in d.findChildren(type(d.title_label))]
        self.assertIn('\n'.join(s.lines()), texts)
        self.assertIn('Last 20 log lines:', texts)
        self.assertEqual(d.parts['text'].toPlainText(), '\n'.join(s.log_tail))
        self.assertTrue(d.parts['text'].isReadOnly())

    def test_stop_has_the_focus_and_closing_is_stop(self):
        d = surprise_view_qt.build(None, 'T', a_surprise())
        d.show()
        self.app.processEvents()
        self.assertIs(d.focusWidget(), d.parts['stop'])
        QTest.keyClick(d, Qt.Key.Key_Escape)
        self.assertEqual(d.result_key, 'stop')
        d2 = surprise_view_qt.build(None, 'T', a_surprise())
        d2.show()
        d2.close()                                       # the title-bar X
        self.assertFalse(d2.isVisible())
        self.assertNotEqual(d2.result_key, 'continue')

    def run_dialog(self, s, press):
        c = Clicker(lambda dlg: QTimer.singleShot(0, press(dlg)))
        try:
            return surprise_view_qt.dialog(None, 'T', s)
        finally:
            c.stop()

    def test_dialog_returns_true_only_for_continue(self):
        self.assertTrue(self.run_dialog(a_surprise(), lambda d: d.parts['cont'].click))
        self.assertFalse(self.run_dialog(a_surprise(), lambda d: d.parts['stop'].click))
        self.assertFalse(self.run_dialog(a_surprise(), lambda d: d.close))
        self.assertFalse(self.run_dialog(a_surprise(stop_only=True), lambda d: d.parts['stop'].click))

    def test_enter_on_the_focused_stop_button_is_stop(self):
        def press(d):
            return lambda: QTest.keyClick(d, Qt.Key.Key_Return)
        self.assertFalse(self.run_dialog(a_surprise(), press))


class SurpriseWorkerThread(QtCase):
    """The protocol of surprise._TkAsker, unchanged, on Qt timers."""

    def setUp(self):
        super().setUp()
        self.built_on = []
        real = surprise_view_qt.build

        def build(root, title, s):
            self.built_on.append(threading.current_thread())
            return real(root, title, s)
        self._b = unittest.mock.patch.object(surprise_view_qt, 'build', build)
        self._b.start()

    def tearDown(self):
        self._b.stop()
        super().tearDown()

    def ask_from_worker(self, handler, s, clicker=None):
        out = {}

        def work():
            out['go'] = handler(s)
        t = threading.Thread(target=work, daemon=True)
        t0 = time.time()
        t.start()
        ok = pump_until(lambda: not t.is_alive())
        out['elapsed'] = time.time() - t0
        self.assertTrue(ok, 'the worker never got its answer')
        return out

    def test_worker_asks_dialog_shows_on_the_ui_thread_continue(self):
        h = surprise_view_qt.make_handler(None)
        c = Clicker(lambda d: d.parts['cont'].click())
        try:
            out = self.ask_from_worker(h, a_surprise())
        finally:
            c.stop()
        self.assertIs(out['go'], True)
        self.assertEqual(self.built_on, [threading.main_thread()])

    def test_worker_stop_and_several_asks_in_a_row(self):
        h = surprise_view_qt.make_handler(None)
        answers = iter(['stop', 'continue', 'stop'])
        c = Clicker(lambda d: d.parts['stop' if next(answers) == 'stop' else 'cont'].click())
        try:
            got = [self.ask_from_worker(h, a_surprise())['go'] for _ in range(3)]
        finally:
            c.stop()
        self.assertEqual(got, [False, True, False])
        self.assertEqual(set(self.built_on), {threading.main_thread()})

    def test_stop_only_never_continues(self):
        h = surprise_view_qt.make_handler(None)
        c = Clicker(lambda d: self.assertIsNone(d.parts['cont']) or d.parts['stop'].click())
        try:
            out = self.ask_from_worker(h, a_surprise(stop_only=True))
        finally:
            c.stop()
        self.assertIs(out['go'], False)

    def test_guard_stops_with_surprise_stop_through_the_qt_handler(self):
        class Log:
            virtual = False
            entries = []

            def lines(self):
                return ['a', 'b']

            def add(self, *a):
                pass

        class Inst:
            label = 'X'
            log = Log()
        h = surprise_view_qt.make_handler(None)
        g = surprise.Guard(Inst(), h)
        res = {}

        def work():
            try:
                g.surprise('reply', 'MEAS?', '', 'float')
                res['r'] = 'continued'
            except surprise.SurpriseStop:
                res['r'] = 'stopped'
        c = Clicker(lambda d: d.parts['stop'].click())
        t = threading.Thread(target=work, daemon=True)
        t.start()
        try:
            self.assertTrue(pump_until(lambda: not t.is_alive()))
        finally:
            c.stop()
        self.assertEqual(res['r'], 'stopped')

    def test_no_poller_means_stop_after_the_wait(self):
        self.assertEqual(surprise._TkAsker.START_WAIT, 5.0)                    # the shipped value is unchanged
        h = surprise_view_qt.make_handler(None)
        with unittest.mock.patch.object(surprise._TkAsker, 'START_WAIT', 0.4):
            out = {}
            t = threading.Thread(target=lambda: out.update(go=h(a_surprise())), daemon=True)
            t0 = time.time()
            t.start()
            t.join(5)                                                          # the UI thread does NOT process events: no poller runs
            el = time.time() - t0
        self.assertIs(out.get('go'), False)
        self.assertGreaterEqual(el, 0.35)
        self.assertLess(el, 3)
        self.assertEqual(self.built_on, [])                                    # no dialog was built
        # the abandoned request is dropped: pumping events afterwards shows nothing
        QApplication.processEvents()
        time.sleep(0.15)
        QApplication.processEvents()
        self.assertEqual(self.built_on, [])

    def test_handler_made_on_a_thread_without_an_event_loop_stops(self):
        made = {}
        t = threading.Thread(target=lambda: made.update(h=surprise_view_qt.make_handler(None)), daemon=True)
        t.start()
        t.join(2)
        with unittest.mock.patch.object(surprise._TkAsker, 'START_WAIT', 0.4):
            out = self.ask_from_worker(made['h'], a_surprise())
        self.assertIs(out['go'], False)
        self.assertEqual(self.built_on, [])

    def test_ui_thread_asks_directly(self):
        h = surprise_view_qt.make_handler(None)
        c = Clicker(lambda d: d.parts['cont'].click())
        try:
            self.assertTrue(h(a_surprise()))
        finally:
            c.stop()


# ====================================================================================================================================================
# data mode
# ====================================================================================================================================================
class FakeApp(datamode.DataModeMixin):
    def __init__(self):
        self.status = datamode_view_qt.QtVar('')
        self.refreshed = 0
        self.busy = False

    def refresh(self):
        self.refreshed += 1


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class DataModeView(QtCase):
    def strip(self):
        host = QWidget()
        QHBoxLayout(host)
        holder = QWidget()
        QVBoxLayout(holder)
        a = FakeApp()
        a.build_mode_segment(host, notice_holder=holder)
        host.show()
        holder.show()
        self.app.processEvents()
        self.host, self.holder = host, holder
        return a

    def test_segment_switches_and_shows_the_notice(self):
        a = self.strip()
        found, left = a.mode_buttons
        self.assertEqual([b.text() for b in a.mode_buttons], ['As Found', 'As Left'])
        self.assertTrue(found.isChecked())
        self.assertEqual(a.mode_var.get(), 'found')
        self.assertIn('First measurements', a.mode_segment.parent().toolTip())
        QTest.mouseClick(left, Qt.MouseButton.LeftButton)
        self.assertEqual(a._mode, 'left')
        self.assertEqual(a.mode_var.get(), 'left')
        self.assertEqual(a.status.get(), 'Collecting As Left data. Run the points again after the adjustment.')
        self.assertEqual(a.refreshed, 1)
        self.assertIsNotNone(a.mode_notice)
        self.assertEqual(a.mode_notice.text_label.text(), 'Collecting AS LEFT: readings are saved beside the As Found values, which stay locked. Use after an adjustment only.')
        self.assertIn('Measure again after the adjustment', a.mode_segment.parent().toolTip())
        QTest.mouseClick(found, Qt.MouseButton.LeftButton)
        self.assertEqual(a._mode, 'found')
        self.assertIsNone(a.mode_notice)
        self.assertEqual(self.holder.layout().count(), 0)

    def test_busy_run_refuses_the_switch_and_puts_the_control_back(self):
        a = self.strip()
        a.busy = True
        QTest.mouseClick(a.mode_buttons[1], Qt.MouseButton.LeftButton)
        self.assertEqual(a._mode, 'found')
        self.assertEqual(a.mode_var.get(), 'found')
        self.assertTrue(a.mode_buttons[0].isChecked())
        self.assertFalse(a.mode_buttons[1].isChecked())

    def test_setting_the_variable_does_not_click(self):
        a = self.strip()
        calls = []
        a._mode_clicked = lambda: calls.append(1)
        a.mode_var.set('left')
        self.assertEqual(calls, [])
        self.assertTrue(a.mode_buttons[1].isChecked())

    def test_load_results_resets_to_as_found_and_the_toggle_follows(self):
        a = self.strip()
        a.set_data_mode('left')
        self.assertTrue(a.mode_buttons[1].isChecked())
        a.load_results({'results': {}, 'left_results': {}})
        self.assertTrue(a.mode_buttons[0].isChecked())
        self.assertIsNone(a.mode_notice)

    def test_the_bar_variant(self):
        host = QWidget()
        QVBoxLayout(host)
        a = FakeApp()
        bar = a.build_mode_bar(host)
        host.show()
        self.assertIs(bar.parent(), host)
        self.assertEqual([b.text() for b in a.mode_buttons], ['As Found', 'As Left'])
        QTest.mouseClick(a.mode_buttons[1], Qt.MouseButton.LeftButton)
        self.assertEqual(a._mode, 'left')
        self.assertEqual(a.mode_hint.get(), datamode.HINT_LEFT)
        self.assertIsNotNone(a.mode_notice)
        self.assertEqual(a.mode_notice.title_label.text(), 'Collecting As Left data')
        self.assertTrue(a.mode_notice.text_label.text().startswith('Readings taken now are saved as AS LEFT.'))
        a.set_data_mode('found')
        self.assertIsNone(a.mode_notice)
        self.assertTrue(a.mode_buttons[0].isChecked())

    def test_reading_column_heading_follows_the_mode(self):
        a = self.strip()
        a.tree = DataTable([Column('id', 'Point'), Column('entered', 'Reading')], [])
        a.set_data_mode('left')
        self.assertEqual(a.tree.source_model.headerData(1, Qt.Orientation.Horizontal), 'As Left reading')
        a.set_data_mode('found')
        self.assertEqual(a.tree.source_model.headerData(1, Qt.Orientation.Horizontal), 'Reading')
        a.tree = DataTable([Column('id', 'Point'), Column('found', 'x'), Column('reading', 'y')], [])
        a.set_data_mode('left')                                                # 'reading' wins over 'found' (the order of the Tk loop)
        self.assertEqual(a.tree.source_model.headerData(2, Qt.Orientation.Horizontal), 'As Left reading')
        self.assertEqual(a.tree.source_model.headerData(1, Qt.Orientation.Horizontal), 'x')


# ====================================================================================================================================================
# manual override
# ====================================================================================================================================================
POINT = dict(id=1, description='DC volts 1 V on the 2 V range', unit='V', nominal=1.0, low=0.9995, high=1.0005, section_title='DC voltage')


class OverrideApp(MO.ManualOverrideMixin):
    MANUAL_OVERRIDE = True

    def __init__(self, parent):
        self.root, self.demo, self.busy, self.io = parent, True, False, None
        self.status = datamode_view_qt.QtVar('')
        self.asset = datamode_view_qt.QtVar('')
        self.results, self.recorded = {}, []
        self.tree = type('T', (), {'selection': lambda s: ()})()

    def mo_point(self, iid):
        return POINT

    def mo_total(self):
        return 5

    def is_manual(self, p):
        return False

    def confirm_found_overwrite(self, points):
        return True

    def _record(self, p, reading, synthetic, manual=False, extra=None):
        self.recorded.append((p['id'], reading, synthetic, extra))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ManualOverrideView(QtCase):
    def type_and(self, text, button, then=None):
        def act(dlg):
            if text is not None:
                dlg.entry.setText(text)
            dlg.button(button).click()
            if then:
                then(dlg)
        return Clicker(act)

    def test_replays_the_scenario_prompts_in_order(self):
        host = QWidget()
        a = OverrideApp(host)
        golden = GOLDEN['overrides_datamode_note_reset_8808a']
        a.busy = True
        a.mo_button_clicked()                                                  # busy, no point being measured
        a._mo_current = dict(POINT)
        a.mo_enter_for(dict(POINT, id=POINT['id'] + 1000))                     # busy: only the point being measured
        a.busy = False
        a._mo_current = None
        a.mo_button_clicked()                                                  # nothing selected
        a.mo_replace(POINT)                                                    # no instrument ID
        self.assertEqual(self.port.prompts, golden[:4])

    def test_entry_window_use_asks_the_short_confirmation_and_records(self):
        host = QWidget()
        a = OverrideApp(host)
        a.asset.set('A-8808')
        c = self.type_and('1.0003', 'use')
        try:
            a.mo_replace(POINT)
        finally:
            c.stop()
        self.assertEqual(len(self.port.prompts), 1)
        rec = self.port.prompts[0]
        self.assertEqual((rec['kind'], rec['title'], rec['buttons'], rec['answer']), ('ask_yes_no', 'Use this reading?', ['Yes', 'No'], True))
        self.assertEqual(rec['text'], 'Use 1.0003 V as the reading for point 1?')
        self.assertEqual(len(a.recorded), 1)
        pid, reading, synthetic, extra = a.recorded[0]
        self.assertEqual((pid, synthetic), (1, True))
        self.assertAlmostEqual(reading, 1.0003)
        self.assertTrue(extra['overridden'])

    def test_invalid_entry_shows_its_message_and_stays_open_then_cancel(self):
        host = QWidget()
        a = OverrideApp(host)
        a.asset.set('A-8808')
        seen = []

        def act(dlg):
            if not seen:
                dlg.entry.setText('abc')
                dlg.ok.click()
                seen.append((dlg.isVisible(), not dlg.error.isHidden(), dlg.error.text_label.text()))
                dlg.entry.setText('')
                dlg.ok.click()
                seen.append((dlg.isVisible(), dlg.error.text_label.text()))
                dlg.cancel.click()
        c = Clicker(act)
        try:
            a.mo_replace(POINT)
        finally:
            c.stop()
        self.assertEqual(seen[0], (True, True, MO.NOT_A_NUMBER))
        self.assertEqual(seen[1], (True, MO.NOT_A_NUMBER))
        self.assertEqual(self.port.prompts, [])                                # no confirmation was asked for a wrong entry
        self.assertEqual(a.recorded, [])

    def test_declining_the_confirmation_keeps_the_window_open(self):
        host = QWidget()
        a = OverrideApp(host)
        a.asset.set('A-8808')
        self.port.answers.rules.append(lambda r: False if r['kind'] == 'ask_yes_no' else None)
        steps = []

        def act(dlg):
            if not steps:
                dlg.entry.setText('1.0001')
                dlg.ok.click()
                steps.append(dlg.isVisible())
                dlg.cancel.click()
        c = Clicker(act)
        try:
            a.mo_replace(POINT)
        finally:
            c.stop()
        self.assertEqual(steps, [True])
        self.assertEqual(a.recorded, [])

    def test_texts_for_a_failed_automatic_reading_and_demo(self):
        vals, unit, _ = MO.entry_scale(POINT)
        d = manual_override_view_qt.build(None, POINT, 5, vals, unit, 'timeout', 'Stop run', True, '', lambda *a: ('use', None))
        texts = [w.text() for w in d.findChildren(type(d.title_label))]
        banners = [b.text_label.text() for b in d.findChildren(Banner)]
        self.assertEqual(d.windowTitle(), 'Point 1 of 5 - enter the reading')
        self.assertIn('Point 1 of 5  -  DC voltage', texts)
        self.assertIn(POINT['description'], texts)
        self.assertIn('The automatic reading failed: timeout', banners)
        self.assertIn('The calibrator is in STANDBY. Read the meter display and type it here to carry on, or stop the run.', texts)
        self.assertIn('DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.', banners)
        self.assertIn('WHAT DOES THE METER SHOW?', texts)
        self.assertIn(f'Acceptable reading: {vals[0]} to {vals[1]} {unit}', texts)
        self.assertEqual(d.cancel.text(), 'Stop run')
        self.assertEqual(d.cancel.property('role'), 'danger')
        self.assertEqual(d.ok.text(), 'Use this reading  (Enter)')
        s = manual_override_view_qt.build(None, POINT, 5, vals, unit, '', 'Cancel', False, '1.00020 V', lambda *a: ('use', None))
        self.assertIn('Stored reading: 1.00020 V. Typing a value replaces it.', [w.text() for w in s.findChildren(type(s.title_label))])
        self.assertIsNone(s.cancel.property('role'))

    def test_enter_key_uses_the_reading_and_closing_cancels(self):
        host = QWidget()
        got = []
        c = Clicker(lambda d: (d.entry.setText('7'), QTest.keyClick(d.entry, Qt.Key.Key_Return)))
        try:
            r = manual_override_view_qt.ask_reading_window(host, POINT, 5, (0.9, 1.1), 'V', '', 'Cancel', False, '', lambda w, t, clr: ('use', t))
        finally:
            c.stop()
        self.assertEqual(r, '7')
        c = Clicker(lambda d: d.close())
        try:
            r = manual_override_view_qt.ask_reading_window(host, POINT, 5, (0.9, 1.1), 'V', '', 'Cancel', False, '', lambda w, t, clr: got.append(t) or ('use', t))
        finally:
            c.stop()
        self.assertIsNone(r)
        self.assertEqual(got, [])


# ====================================================================================================================================================
# run queue drawer, procmods menu, calibrator note
# ====================================================================================================================================================
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QueueDrawer(QtCase):
    def test_block_takes_three_rows_and_the_button_opens_the_setup(self):
        host = QWidget()
        grid = QGridLayout(host)

        class A:
            opened = 0

            def open_queue_setup(self):
                self.opened += 1
        a = A()
        nxt = run_queue_view_qt.build_queue_drawer(a, grid, 4)
        self.assertEqual(nxt, 7)
        self.assertEqual(a.btn_queue.text(), 'Run queue...')
        self.assertEqual(a.queue_label.get(), 'No queue: one meter, as usual.')
        host.show()
        QTest.mouseClick(a.btn_queue, Qt.MouseButton.LeftButton)
        self.assertEqual(a.opened, 1)
        a.queue_label.set('2 meters: 4412, 4413')
        self.assertEqual(a.queue_label_widget.text(), '2 meters: 4412, 4413')
        rows = sorted({grid.getItemPosition(i)[0] for i in range(grid.count())})
        self.assertEqual(rows, [4, 5, 6])

    def test_setup_and_progress_are_resolved_at_call_time(self):
        import types
        fake = types.ModuleType('run_queue_ui_qt')
        fake.ask_queue_setup = lambda *a, **k: ('setup', a, k)
        fake.QueueProgress = lambda *a, **k: ('progress', a, k)
        with unittest.mock.patch.dict(sys.modules, {'run_queue_ui_qt': fake}):
            self.assertEqual(run_queue_view_qt.ask_queue_setup(1, 2, x=3), ('setup', (1, 2), {'x': 3}))
            self.assertEqual(run_queue_view_qt.queue_progress('p', title='t'), ('progress', ('p',), {'title': 't'}))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ProcmodsMenu(QtCase):
    def make(self, enabled=True, why='', extras=None):
        class A:
            pm_state = object()
            opened = []

            def tree_menu_extras(self, pid):
                return extras or []
        a = A()
        rows = [dict(id=1), dict(id=2)]
        t = DataTable([Column('id', 'Point')], rows, row_key=lambda r: r['id'])
        patch = unittest.mock.patch.object(procmods_view_qt.PM, 'menu_state', lambda app, pid: (enabled, why))
        patch.start()
        self.addCleanup(patch.stop)
        return a, t

    def test_edit_enabled(self):
        a, t = self.make()
        tm = procmods_view_qt.attach_tree_menu(a, t)
        self.assertIs(t.context_provider.__self__, tm)
        ents = tm.entries(1)
        self.assertEqual([(e[0], e[2]) for e in ents], [('Edit', True)])
        self.assertEqual(a.__dict__['_pm_tree_menus'][0][0], t)

    def test_locked_shows_the_reason_cut_at_90(self):
        a, t = self.make(False, 'x' * 120)
        ents = procmods_view_qt.attach_tree_menu(a, t).entries(1)
        self.assertEqual([(e[0], e[2]) for e in ents], [('Edit', False), ('x' * 90 + '...', False)])

    def test_engine_extras_follow_after_a_separator(self):
        calls = []
        a, t = self.make(extras=[('Enter reading manually...', lambda: calls.append(1), True, ''), ('Other', None, False, 'not now')])
        tm = procmods_view_qt.attach_tree_menu(a, t, resolver=lambda k: k * 10)
        ents = tm.entries(5)
        self.assertEqual([e[0] for e in ents], ['Edit', '-', 'Enter reading manually...', '-', 'Other', 'not now'])
        menu = tm.build(5)
        self.assertEqual([x.text() for x in menu.actions() if not x.isSeparator()], ['Edit', 'Enter reading manually...', 'Other', 'not now'])
        menu.actions()[2].trigger()
        self.assertEqual(calls, [1])
        rows = tm.row_entries(t.rows()[1])                                     # resolver gets the row key (2 -> 20)
        self.assertEqual(rows[0][0], 'Edit')

    def test_edit_calls_the_point_window_of_the_qt_editor(self):
        import types
        seen = []
        fake = types.ModuleType('procmods_point_ui_qt')
        fake.open_point_window = lambda app, pid, lock=None, parent=None: seen.append((pid, lock)) or 'win'
        a, t = self.make()
        tm = procmods_view_qt.attach_tree_menu(a, t, lock='L')
        with unittest.mock.patch.dict(sys.modules, {'procmods_point_ui_qt': fake}):
            tm.entries(3)[0][1]()
        self.assertEqual(seen, [(3, 'L')])

    def test_datatable_context_menu_lists_edit_above_copy(self):
        a, t = self.make()
        procmods_view_qt.attach_tree_menu(a, t)
        shown = []
        from PySide6.QtWidgets import QMenu

        class RecordingMenu(QMenu):
            def exec(self, *a):
                shown.append([x.text() for x in self.actions() if not x.isSeparator()])
        with unittest.mock.patch('qtui.table.QMenu', RecordingMenu):
            t.resize(300, 200)
            t.show()
            self.app.processEvents()
            pos = t.visualRect(t.proxy.index(0, 0)).center()
            t._context_menu(pos)
        self.assertEqual(shown[0][0], 'Edit')
        self.assertIn('Copy', shown[0][1])
        self.assertEqual(t.selected_keys(), [1])                               # right-click selects the row first


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class CalibratorNote(QtCase):
    def test_pack_and_grid(self):
        offer = type('O', (), dict(text='Model offered.', tooltip='Because the lab calibrator is 5522A.'))()
        host = QWidget()
        col = QVBoxLayout(host)
        picker = QPushButton('pick')
        col.addWidget(picker)
        lab = calibrator_fit_view_qt.attach_note(host, offer, None, widgets=(picker,))
        self.assertEqual(lab.text(), 'Model offered.')
        self.assertEqual(lab.toolTip(), offer.tooltip)
        self.assertEqual(picker.toolTip(), offer.tooltip)
        self.assertEqual(col.count(), 2)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        lab2 = calibrator_fit_view_qt.attach_note(grid_host, offer, None, row=3, columnspan=2)
        self.assertEqual(grid.getItemPosition(grid.indexOf(lab2))[:2], (3, 0))
        with self.assertRaises(TypeError):
            calibrator_fit_view_qt.attach_note(host, offer, None, row=1)


class Rules(unittest.TestCase):
    def test_no_tk_in_the_qt_twins(self):
        import ast
        for name in ('surprise_view_qt', 'datamode_view_qt', 'manual_override_view_qt', 'run_queue_view_qt', 'procmods_view_qt', 'calibrator_fit_view_qt'):
            tree = ast.parse((ROOT / f'{name}.py').read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                for m in mods:
                    top = m.split('.')[0]
                    self.assertNotIn(top, ('tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk'), f'{name} imports {m}')
                    self.assertFalse(top.endswith('_view_tk'), f'{name} imports {m}')

    def test_every_twin_has_the_public_names_of_its_tk_view(self):
        import ast
        for stem in ('surprise_view', 'datamode_view', 'manual_override_view', 'run_queue_view', 'procmods_view', 'calibrator_fit_view'):
            def names(path):
                return {n.name for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith('_')}
            tk, qt = names(ROOT / f'{stem}_tk.py'), names(ROOT / f'{stem}_qt.py')
            self.assertLessEqual(tk, qt, f'{stem}_qt lacks {tk - qt}')


if __name__ == '__main__':
    unittest.main()
