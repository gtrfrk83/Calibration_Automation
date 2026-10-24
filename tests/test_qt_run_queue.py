"""Qt twin of the run queue windows (run_queue_ui -> qtui.screens.run_queue, re-exported by run_queue_ui_qt; run_queue_view_qt): the scenarios of
tests/real_tk_checks.py::checks_run_queue (set-up window, the one-window reading entry for several meters, progress window) with the same outputs, driven with
real clicks and typing on the offscreen platform.  Skipped when PySide6 is not importable.

    <venv python> -m unittest tests.test_qt_run_queue
"""
import os
import sys
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

import run_queue as RQ  # noqa: E402  (toolkit-free)

if HAVE_QT:
    import threading
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget
    from qtui import app as qapp
    from qtui.screens import common
    from qtui.screens import run_queue as RU
    QAPP = qapp.create_app()

HH = None


def setUpModule():
    global HH
    if HAVE_QT:
        if 'tkinter' not in sys.modules:
            sys.modules['tkinter'] = None
        import _tk_stub
        _tk_stub.install()
        import handheld_dmm
        HH = handheld_dmm


def texts_of(widget):
    return ' '.join(l.text() for l in widget.findChildren(QLabel))


def buttons_of(widget):
    return {b.text(): b for b in widget.findChildren(QPushButton)}


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QAPP
        cls.spec = HH.load_spec('fluke_110_series_pv.json')
        cls.pts = HH.points_for(cls.spec, '117')
        cls.p = next(x for x in cls.pts if x['kind'] == 'DCV' and x['nominal'] == 5.0)

    def drive(self, open_it, act, ms=250):
        """Open a modal window with `open_it` and run `act(window)` inside its event loop; whatever the act leaves open is closed after 4 s (never hang)."""
        seen = {}

        def go():
            win = QApplication.activeModalWidget()
            seen['win'] = win
            try:
                act(win, seen)
            except BaseException as e:          # report it from the test, not from a dialog
                import traceback
                seen['exc'] = traceback.format_exc()
                if win is not None:
                    win.reject()

        def never_hang():
            w = QApplication.activeModalWidget()
            if w is not None:
                w.reject()
        timers = []
        for delay, fn in ((ms, go), (4000, never_hang)):
            t = QTimer()
            t.setSingleShot(True)
            t.timeout.connect(fn)
            t.start(delay)
            timers.append(t)
        try:
            seen['result'] = open_it()
        finally:
            for t in timers:                     # a stale safety timer must not close the next test's window
                t.stop()
        if 'exc' in seen:
            self.fail(seen['exc'])
        return seen


# ===================================================================================================================== set-up window
class SetupWindow(Base):
    meters = [('4412', '21090134', 'M. Reyes'), ('4413', '21090187', 'M. Reyes'), ('4415', '21090240', 'M. Reyes')]

    def summarize(self, meters, mode):
        q = RQ.RunQueue()
        for a, sn, t in meters:
            q.add(a, sn, t)
        info = RQ.summary(self.pts, q, self.spec['options'], mode=mode)
        if mode == RQ.POINT_BY_POINT:
            return dict(title=f'Saves {info["saved"]} calibrator settings', body=f'{info["points"]} points x {len(meters)} meters = {info["alone"]} settings one at a time; '
                        f'point by point needs {info["settings"]}.', ok=True, kind='good')
        return dict(title='One meter at a time', body=f'{info["alone"]} calibrator settings.', ok=True, kind='warn')

    def dialog(self, meters=None, mode=RQ.POINT_BY_POINT, **kw):
        d = RU.QueueSetupDialog(None, 'Run queue - Fluke 117', meters if meters is not None else self.meters, mode, self.summarize, status_of=lambda a: 'Ready',
                                default_tech='M. Reyes', **kw)
        d.show()
        self.qapp.processEvents()
        self.addCleanup(d.close)
        return d

    def assets(self, d):
        return [r['asset'] for r in d.table.rows()]

    def test_buttons_rows_and_title(self):
        d = self.dialog()
        b = buttons_of(d)
        self.assertTrue({'+ Add meter', 'Edit', 'Remove', 'Move up', 'Move down', 'Start queue', 'Cancel', 'Save (do not start)'} <= set(b), sorted(b))
        self.assertEqual(self.assets(d), ['4412', '4413', '4415'])
        self.assertEqual(d.windowTitle(), 'Run queue - Fluke 117  (3 meters)')
        self.assertEqual([r['status'] for r in d.table.rows()], ['Ready'] * 3)
        self.assertIn('Saves', d.sum_head.text())
        self.assertTrue(d.cards[RQ.POINT_BY_POINT].radio.isChecked())
        self.assertFalse(d.cards[RQ.ONE_AT_A_TIME].radio.isChecked())

    def test_move_remove_choose_and_start_returns_the_edited_queue_and_mode(self):
        def act(win, seen):
            win.table.select_rows([win._rows[0]])
            win.buttons['Move down'].click()
            seen['moved'] = [r['asset'] for r in win.table.rows()]
            win.table.select_rows([win._rows[2]])
            win.buttons['Remove'].click()
            seen['removed'] = len(win.table.rows())
            win.cards[RQ.ONE_AT_A_TIME].radio.click()
            seen['mode_card'] = win.cards[RQ.ONE_AT_A_TIME].radio.isChecked()
            seen['head'] = win.sum_head.text()
            win.start.click()
        r = self.drive(lambda: RU.ask_queue_setup(None, 'Run queue - Fluke 117', self.meters, RQ.POINT_BY_POINT, self.summarize, status_of=lambda a: 'Ready',
                                                  default_tech='M. Reyes'), act)
        self.assertEqual(r['moved'], ['4413', '4412', '4415'])
        self.assertEqual(r['removed'], 2)
        self.assertTrue(r['mode_card'])
        self.assertEqual(r['head'], 'One meter at a time')
        res = r['result']
        self.assertTrue(res and res['action'] == 'start' and [m[0] for m in res['meters']] == ['4413', '4412'] and res['mode'] == RQ.ONE_AT_A_TIME, res)

    def test_cancel_returns_nothing(self):
        r = self.drive(lambda: RU.ask_queue_setup(None, 'Run queue - Fluke 117', self.meters, RQ.POINT_BY_POINT, self.summarize),
                       lambda w, s: buttons_of(w)['Cancel'].click())
        self.assertIsNone(r['result'])

    def test_escape_and_closing_return_nothing(self):
        r = self.drive(lambda: RU.ask_queue_setup(None, 'Run queue - Fluke 117', self.meters, RQ.POINT_BY_POINT, self.summarize),
                       lambda w, s: QTest.keyClick(w, Qt.Key.Key_Escape))
        self.assertIsNone(r['result'])

    def test_save_returns_save_with_the_meters(self):
        r = self.drive(lambda: RU.ask_queue_setup(None, 'Run queue - Fluke 117', self.meters[:2], RQ.ONE_AT_A_TIME, self.summarize),
                       lambda w, s: w.save.click())
        self.assertEqual(r['result'], dict(action='save', meters=self.meters[:2], mode=RQ.ONE_AT_A_TIME))

    def test_enter_does_nothing_in_the_setup_window(self):
        d = self.dialog()
        d.table.setFocus()
        QTest.keyClick(d, Qt.Key.Key_Return)
        self.assertTrue(d.isVisible())
        self.assertIsNone(d.answer)

    def test_one_meter_says_run_this_meter_and_none_disables_start_and_save(self):
        d = self.dialog(meters=self.meters[:1])
        self.assertEqual(d.start.text(), 'Run this meter')
        self.assertEqual(d.windowTitle(), 'Run queue - Fluke 117  (1 meter)')
        d.table.select_rows([d._rows[0]])
        d.buttons['Remove'].click()
        self.assertFalse(d.start.isEnabled())
        self.assertFalse(d.save.isEnabled())
        self.assertEqual(d.start.text(), 'Run this meter')

    def test_the_engine_can_block_the_start(self):
        d = RU.QueueSetupDialog(None, 'Run queue', self.meters, RQ.POINT_BY_POINT,
                                lambda m, mode: dict(title='Not possible', body='b', warnings=['w1', 'w2'], ok=False, kind='bad'))
        d.show()
        self.addCleanup(d.close)
        self.assertFalse(d.start.isEnabled())
        self.assertTrue(d.save.isEnabled())
        self.assertEqual(d.sum_body.text(), 'b\nw1\nw2')

    def test_add_edit_validation_and_limits(self):
        d = self.dialog(meters=self.meters[:2])
        answers = [('4412', '', ''), ('4499', 'S1', 'Pat'), None]
        with mock.patch.object(RU, 'ask_meter', side_effect=lambda *a, **k: answers.pop(0)) as ask:
            d.buttons['+ Add meter'].click()                              # duplicate
            self.assertEqual(d.note.text(), 'Asset 4412 is already in the queue.')
            self.assertEqual(self.assets(d), ['4412', '4413'])
            d.buttons['+ Add meter'].click()
            self.assertEqual(self.assets(d), ['4412', '4413', '4499'])
            self.assertEqual(d.note.text(), '')
            d.buttons['+ Add meter'].click()                              # cancelled
            self.assertEqual(len(self.assets(d)), 3)
        self.assertEqual(ask.call_args_list[0][0][1], 'Add meter')
        self.assertNotIn('4412', [c[0] for c in ask.call_args_list[0][1]['candidates']] or [])
        d2 = self.dialog(meters=[(f'A{i}', '', '') for i in range(RQ.MAX_METERS)])
        with mock.patch.object(RU, 'ask_meter', return_value=('ZZ', '', '')):
            d2.buttons['+ Add meter'].click()
        self.assertEqual(d2.note.text(), f'A queue holds at most {RQ.MAX_METERS} meters.')
        d.table.select_rows([d._rows[1]])
        with mock.patch.object(RU, 'ask_meter', return_value=('4412', '', '')):
            d.buttons['Edit'].click()
        self.assertEqual(d.note.text(), 'Asset 4412 is already in the queue.')
        with mock.patch.object(RU, 'ask_meter', return_value=('4413', 'SN9', 'Lee')):
            d.buttons['Edit'].click()
        self.assertEqual(d.state['meters'][1], ('4413', 'SN9', 'Lee'))
        self.assertEqual(d.selected(), 1)                                 # the edited row stays selected

    def test_double_click_or_enter_on_a_row_edits_it(self):
        d = self.dialog()
        d.table.select_rows([d._rows[0]])
        with mock.patch.object(RU, 'ask_meter', return_value=('4412', 'NEW', 'M. Reyes')) as ask:
            d.table.rowActivated.emit(d._rows[0])
        self.assertEqual(ask.call_args[0][1], 'Edit meter')
        self.assertEqual(d.state['meters'][0][1], 'NEW')

    def test_ir_only_forces_one_meter_at_a_time_with_the_reason(self):
        d = self.dialog(ir_only=True)
        self.assertEqual(d.state['mode'], RQ.ONE_AT_A_TIME)
        self.assertTrue(d.cards[RQ.ONE_AT_A_TIME].radio.isChecked())
        d.cards[RQ.POINT_BY_POINT].radio.click()
        self.assertEqual(d.state['mode'], RQ.ONE_AT_A_TIME)
        self.assertEqual(d.note.text(), RQ.IR_REASON[0].upper() + RQ.IR_REASON[1:] + '.')
        self.assertFalse(d.cards[RQ.POINT_BY_POINT].radio.isChecked())

    def test_clicking_the_card_text_chooses_the_mode(self):
        d = self.dialog()
        QTest.mouseClick(d.cards[RQ.ONE_AT_A_TIME], Qt.MouseButton.LeftButton)
        self.assertEqual(d.state['mode'], RQ.ONE_AT_A_TIME)

    def test_meter_dialog_validates_fills_the_serial_and_returns_the_triple(self):
        r = self.drive(lambda: RU.ask_meter(None, 'Add meter', candidates=[('4412', 'SN-1'), ('4413', 'SN-2')], default_tech='M. Reyes'),
                       lambda w, s: (w.button('ok').click(), s.__setitem__('msg', w.msg.text()), w.asset.setCurrentText('4413'), w.asset.activated.emit(1),
                                     s.__setitem__('serial', w.serial.text()), w.button('ok').click()))
        self.assertEqual(r['msg'], 'Enter the asset number.')
        self.assertEqual(r['serial'], 'SN-2')
        self.assertEqual(r['result'], ('4413', 'SN-2', 'M. Reyes'))

    def test_meter_dialog_cancel_returns_none_and_edit_prefills(self):
        r = self.drive(lambda: RU.ask_meter(None, 'Edit meter', '4412', 'S', 'T', candidates=[('4412', 'S')]),
                       lambda w, s: (s.__setitem__('v', (w.asset.currentText(), w.serial.text(), w.tech.text())), w.button('cancel').click()))
        self.assertEqual(r['v'], ('4412', 'S', 'T'))
        self.assertIsNone(r['result'])

    def test_called_from_a_worker_thread_it_runs_on_the_ui_thread(self):
        out = {}

        def worker():
            out['r'] = RU.ask_queue_setup(None, 'Run queue', self.meters, RQ.POINT_BY_POINT, self.summarize)
        QTimer.singleShot(400, lambda: (out.__setitem__('on_ui', qapp.is_ui_thread()), buttons_of(QApplication.activeModalWidget())['Start queue'].click()))
        t = threading.Thread(target=worker)
        t.start()
        end = time.monotonic() + 5
        while t.is_alive() and time.monotonic() < end:
            self.qapp.processEvents()
            time.sleep(0.01)
        t.join(1)
        self.assertEqual(out['r']['action'], 'start')


# ===================================================================================================================== reading window
class ReadingWindow(Base):
    asset_rows = [('4412', '4412', ''), ('4413', '4413', ''), ('4415', '4415', '')]

    def judge(self, key, text):
        padded = HH.pad_reading(self.p, text)
        state, _ = HH.judge_numeric(self.p, padded)
        return state, padded, '+0.001 V from nominal' if state == 'PASS' else ''

    def dialog(self, **kw):
        d = RU.ReadingsDialog(None, self.p, len(self.pts), HH.output_text(self.p), 'Output is ON - allow the reading to settle, then read the meter.',
                              '4.9950 to 5.0050 V', self.asset_rows, unit='V', judge=self.judge, heading=HH.describe(self.p), **kw)
        d.show()
        self.qapp.processEvents()
        self.addCleanup(d.close)
        return d

    def read(self, **kw):
        return lambda: RU.ask_readings(None, self.p, len(self.pts), HH.output_text(self.p), 'Output is ON - allow the reading to settle, then read the meter.',
                                       '4.9950 to 5.0050 V', self.asset_rows, unit='V', judge=self.judge, heading=HH.describe(self.p), **kw)

    def type_into(self, d, i, text):
        e = d.rows[i].entry
        e.setFocus()
        QTest.keyClicks(e, text)

    def test_one_box_per_meter_with_the_asset_numbers(self):
        d = self.dialog()
        self.assertEqual(len(d.rows), 3)
        self.assertEqual(d.windowTitle(), f'Point {self.p["n"]} of {len(self.pts)}')
        t = texts_of(d)
        for a in ('4412', '4413', '4415'):
            self.assertIn(f'Asset {a}', t)
        self.assertIn('Meter 1', t)
        self.assertIn('ACCEPT IF', t)
        self.assertIn('4.9950 to 5.0050 V', t)
        self.assertIn('on every meter', t)
        self.assertIn('WHAT DOES EACH METER SHOW?', t)
        self.assertIn('CALIBRATOR OUTPUT', t)
        self.assertIn(f'{len(self.asset_rows)} meters', t)
        self.assertTrue(d.rows[0].entry.hasFocus())
        self.assertEqual([r.state.text() for r in d.rows], ['waiting'] * 3)

    def test_live_pass_padding_and_fail(self):
        d = self.dialog()
        self.type_into(d, 0, '5.001')
        self.type_into(d, 1, '5.0')
        self.assertEqual(d.rows[0].state.text(), '✓ PASS')
        self.assertEqual(d.rows[1].state.text(), '✓ PASS')
        self.assertIn('padded to 5.000', d.rows[1].note.text())
        self.assertNotIn('padded', d.rows[0].note.text())
        self.assertIn('+0.001 V from nominal', d.rows[0].note.text())
        self.type_into(d, 2, '9')
        self.assertEqual(d.rows[2].state.text(), '✗ FAIL')
        self.type_into(d, 2, 'x')                                          # '9x': not a reading
        self.assertEqual(d.rows[2].state.text(), 'not a reading')
        self.assertTrue(d.rows[2].note.text())

    def test_enter_moves_to_the_next_box_and_in_the_last_box_records(self):
        def act(win, seen):
            for i, t in enumerate(('5.001', '5.0', '9')):
                self.type_into(win, i, t)
            QTest.keyClick(win.rows[0].entry, Qt.Key.Key_Return)
            seen['focus'] = win.rows[1].entry.hasFocus()
            QTest.keyClick(win.rows[2].entry, Qt.Key.Key_Return)            # Enter in the last box records
        r = self.drive(self.read(), act)
        self.assertTrue(r['focus'], 'Enter moves to the next box')
        got = r['result']
        self.assertEqual(got['action'], 'record')
        self.assertEqual(got['texts'], {'4412': '5.001', '4413': '5.0', '4415': '9'})
        self.assertEqual(got['no_reading'], [])

    def test_empty_boxes_refuse_to_record_and_stop_run_stops(self):
        def act(win, seen):
            buttons_of(win)['Record all  (Enter)'].click()
            seen['still_open'] = win.isVisible()
            seen['error'] = win.error.text()
            seen['focus'] = win.rows[0].entry.hasFocus()
            buttons_of(win)['Stop run'].click()
        r = self.drive(self.read(), act)
        self.assertTrue(r['still_open'])
        self.assertEqual(r['error'], 'Enter the reading of Asset 4412, or tick "No reading" for it.')
        self.assertTrue(r['focus'])
        self.assertEqual(r['result']['action'], 'stop')
        self.assertEqual(r['result']['texts'], {})

    def test_a_bad_reading_names_the_meter_and_refuses(self):
        def act(win, seen):
            self.type_into(win, 0, '5.0')
            self.type_into(win, 1, 'abc')
            self.type_into(win, 2, '5.0')
            win.record_button.click()
            seen['error'] = win.error.text()
            seen['open'] = win.isVisible()
            win.stop_button.click()
        r = self.drive(self.read(), act)
        self.assertTrue(r['open'])
        self.assertTrue(r['error'].startswith('Asset 4413: '), r['error'])

    def test_skip_point(self):
        r = self.drive(self.read(), lambda w, s: buttons_of(w)['Skip point'].click())
        self.assertEqual(r['result']['action'], 'skip')

    def test_closing_the_window_or_escape_is_stop_run(self):
        r = self.drive(self.read(), lambda w, s: QTest.keyClick(w, Qt.Key.Key_Escape))
        self.assertEqual(r['result']['action'], 'stop')
        r = self.drive(self.read(), lambda w, s: w.close())
        self.assertEqual(r['result']['action'], 'stop')

    def test_demo_fill_button_fills_every_box(self):
        def act(win, seen):
            b = buttons_of(win)
            seen['names'] = sorted(b)
            seen['demo_note'] = 'Nothing here is calibration evidence.' in texts_of(win)
            next(v for k, v in b.items() if 'simulated' in k).click()
            seen['filled'] = [r.entry.text() for r in win.rows]
            seen['focus'] = win.rows[0].entry.hasFocus()
            b['Record all  (Enter)'].click()
        r = self.drive(self.read(demo_fill=lambda i: f'5.00{i}'), act)
        self.assertTrue(any('simulated' in k for k in r['names']))
        self.assertTrue(r['demo_note'])
        self.assertEqual(r['filled'], ['5.000', '5.001', '5.002'])
        self.assertTrue(r['focus'])
        self.assertEqual(r['result']['action'], 'record')
        self.assertEqual(len(r['result']['texts']), 3)

    def test_no_demo_button_without_demo_fill(self):
        d = self.dialog()
        self.assertFalse(any('simulated' in k for k in buttons_of(d)))

    def test_a_meter_marked_no_reading_records_nothing(self):
        def act(win, seen):
            self.type_into(win, 0, '5.0')
            self.type_into(win, 2, '5.0')
            win.rows[1].skip.click()
            seen['state'] = (win.rows[1].state.text(), win.rows[1].entry.isEnabled(), win.rows[1].note.text())
            win.record_button.click()
        r = self.drive(self.read(), act)
        self.assertEqual(r['state'], ('no reading', False, 'nothing is recorded for this meter at this point'))
        self.assertEqual(r['result']['texts'], {'4412': '5.0', '4413': None, '4415': '5.0'})
        self.assertEqual(r['result']['no_reading'], ['4413'])

    def test_enter_skips_a_no_reading_meter(self):
        d = self.dialog()
        d.rows[1].skip.click()
        self.type_into(d, 0, '5.0')
        QTest.keyClick(d.rows[0].entry, Qt.Key.Key_Return)
        self.assertTrue(d.rows[2].entry.hasFocus())

    def test_every_meter_no_reading_means_use_skip_point(self):
        d = self.dialog()
        for r in d.rows:
            r.skip.click()
        got, msg, bad = d.collect()
        self.assertIsNone(got)
        self.assertEqual(msg, 'Every meter is marked "No reading": use Skip point instead.')
        self.assertIsNone(bad)

    def test_the_time_limit_counts_down_and_switches_the_output_off_once(self):
        expired = []
        t = [100.0]
        with mock.patch.object(RU, '_now', lambda: t[0]):
            d = self.dialog(limit_s=30, on_expire=lambda: expired.append(1))
            self.assertIn('Take the readings within 30 s - the output switches off automatically.', d.counter.text())
            t[0] += 12
            d._tick()
            self.assertIn('within 18 s', d.counter.text())
            t[0] += 60
            d._tick()
            d._tick()
        self.assertEqual(d.counter.text(), 'Time limit reached - the output has been switched off. Enter the readings you saw.')
        self.assertEqual(expired, [1])

    def test_without_an_expire_hook_the_text_asks_for_standby(self):
        t = [5.0]
        with mock.patch.object(RU, '_now', lambda: t[0]):
            d = self.dialog(limit_s=10)
            self.assertIn('then put the calibrator in STANDBY.', d.counter.text())
            t[0] += 11
            d._tick()
        self.assertEqual(d.counter.text(), 'Time limit reached - put the calibrator in STANDBY now, then enter the readings.')

    def test_phase_source_and_device_labels(self):
        d = RU.ReadingsDialog(None, self.p, 40, '5 V', 'Wait', 'x', self.asset_rows, unit='V', judge=self.judge, device='CLAMP', source='GENERATOR', phase='As Left',
                              tol_text='0.1 %', heading='h')
        d.show()
        self.addCleanup(d.close)
        t = texts_of(d)
        self.assertIn('As Left', t)
        self.assertIn('WHAT DOES EACH CLAMP SHOW?', t)
        self.assertIn('GENERATOR', t)
        self.assertIn('limit: 0.1 %', t)

    def test_focus_follows_the_box_and_is_keyboard_operable(self):
        d = self.dialog()
        d.rows[1].entry.setFocus()
        self.qapp.processEvents()
        self.assertIn('2px', d.rows[1].styleSheet())
        self.assertIn('1px', d.rows[0].styleSheet())

    def test_handheld_dmm_ask_readings_contract(self):
        import inspect
        sig = list(inspect.signature(RU.ask_readings).parameters)
        self.assertEqual(sig, ['parent', 'p', 'total', 'out_text', 'out_note', 'accept', 'meters', 'unit', 'judge', 'limit_s', 'on_expire', 'device', 'source',
                               'demo_fill', 'tol_text', 'phase', 'heading'])
        import run_queue_ui_qt
        self.assertIs(run_queue_ui_qt.ask_readings, RU.ask_readings)


# ===================================================================================================================== progress window
class ProgressWindow(Base):
    rows = [dict(asset='4412', serial='', status='Running', recorded=7, failed=0, first_fail=None, total=40),
            dict(asset='4413', serial='', status='Running', recorded=6, failed=0, first_fail=None, total=40),
            dict(asset='4415', serial='', status='Running', recorded=6, failed=1, first_fail=3, total=40)]

    def test_progress_running_then_finished_with_export_and_show(self):
        prog = RU.QueueProgress(None)
        self.addCleanup(prog.close)
        prog.update('Point 7 of 40  -  all 3 meters', 7 / 40, self.rows)
        self.qapp.processEvents()
        self.assertTrue(prog.alive())
        self.assertEqual(prog.head.text(), 'Point 7 of 40  -  all 3 meters')
        self.assertEqual(prog.bar.value(), 18)
        t = texts_of(prog.win)
        self.assertIn('Asset 4412', t)
        self.assertIn('7 recorded   0 fail', t)
        self.assertIn('6 recorded   1 FAIL at point 3', t)
        self.assertIn(RU.QueueProgress.FOOT, t)
        self.assertEqual(buttons_of(prog.win), {}, 'no buttons while the queue runs')
        calls = []
        prog.on_export, prog.on_show = (lambda: calls.append('export')), (lambda a: calls.append(a))
        prog.update('Queue complete', 1.0, self.rows, finished=True)
        b = buttons_of(prog.win)
        self.assertTrue({'Export all reports (PDF)...', 'Close'} <= set(b), sorted(b))
        self.assertEqual(sum(1 for k in b if k == 'Show'), 1)
        self.assertEqual(len(prog.show_buttons), 3)
        b['Export all reports (PDF)...'].click()
        prog.show_buttons['4413'].click()
        self.assertEqual(calls, ['export', '4413'])
        self.assertTrue(prog.alive())
        b['Close'].click()
        self.assertFalse(prog.alive())
        prog.update('x', 0, self.rows)                                     # updating a closed window is harmless

    def test_finished_note_and_export_button_only_when_an_exporter_is_given(self):
        prog = RU.QueueProgress(None, on_show=None, on_export=None)
        self.addCleanup(prog.close)
        prog.update('Queue stopped', 0.5, self.rows, finished=True, note='The run was paused.')
        self.assertIn('The run was paused.', texts_of(prog.win))
        self.assertEqual(sorted(buttons_of(prog.win)), ['Close'])
        prog.update('again', 0.5, self.rows)                                # a later running update drops the buttons again
        self.assertEqual(buttons_of(prog.win), {})

    def test_the_window_title_and_failing_meter_status_text(self):
        prog = RU.QueueProgress(None, 'Queue progress')
        self.addCleanup(prog.close)
        rows = [dict(self.rows[0], status='Done')]
        prog.update('h', 0.1, rows)
        self.assertEqual(prog.win.windowTitle(), 'Queue progress')
        self.assertIn('7 recorded   0 fail   -   Done', texts_of(prog.win))

    def test_update_from_a_worker_thread_lands_on_the_ui_thread(self):
        prog = RU.QueueProgress(None)
        self.addCleanup(prog.close)
        t = threading.Thread(target=lambda: prog.update('from a worker', 0.25, self.rows))
        t.start()
        t.join()
        end = time.monotonic() + 3
        while prog.head.text() != 'from a worker' and time.monotonic() < end:
            self.qapp.processEvents()
        self.assertEqual(prog.head.text(), 'from a worker')
        self.assertEqual(prog.bar.value(), 25)


# ===================================================================================================================== the seams
class Seams(Base):
    def test_view_functions_resolve_at_call_time(self):
        import run_queue_view_qt as V
        import run_queue_ui_qt
        with mock.patch.object(run_queue_ui_qt, 'ask_queue_setup', lambda *a, **k: dict(action='save', meters=[('A', '', ''), ('B', '', '')], mode=RQ.POINT_BY_POINT)):
            self.assertEqual(V.ask_queue_setup(None, 't', [], RQ.POINT_BY_POINT, None)['action'], 'save')
        prog = V.queue_progress(None, on_show=None)
        self.addCleanup(prog.close)
        self.assertIsInstance(prog, RU.QueueProgress)

    def test_the_drawer_block_adds_button_and_status_line_and_returns_the_next_row(self):
        import run_queue_view_qt as V

        class Win:
            opened = 0

            def open_queue_setup(self):
                self.opened += 1
        host, win = QWidget(), Win()
        grid = QGridLayout(host)
        nxt = V.build_queue_drawer(win, grid, 14)
        self.assertEqual(nxt, 17)
        self.assertEqual(win.btn_queue.text(), 'Run queue...')
        self.assertEqual(win.queue_label.text(), 'No queue: one meter, as usual.')
        win.queue_label.set('Queue of 3')
        self.assertEqual(win.queue_label.text(), 'Queue of 3')
        win.btn_queue.click()
        self.assertEqual(win.opened, 1)
        self.assertEqual(grid.rowCount(), 17)
        self.assertIn('Several meters', texts_of(host))
        host2 = QWidget()
        QGridLayout(host2)
        self.assertEqual(V.build_queue_drawer(Win(), host2, 0), 3)


if __name__ == '__main__':
    unittest.main()
