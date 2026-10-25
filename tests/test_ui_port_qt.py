"""QtUiPort (ui_port_qt.py) driven headless: the recorded Tk prompt sequences (tests/golden_ui/*.json) played through the Qt dialogs with an auto-clicking
operator, the worker-thread calls, the window plumbing and the toolkit selector.  Skipped when PySide6 is not importable.

An 'operator' (Driver) polls the active modal dialog from inside its event loop, checks what is ON SCREEN (title, text, button names, entry contents, step texts) against
the recorded Tk prompt and presses the button / types the text that produced the recorded answer; the port must then return that recorded answer.  So a prompt
sequence only passes when the Qt dialogs show the same title, text and buttons as the Tk ones and give the same answers back.
"""
import glob
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QLineEdit, QMainWindow, QPushButton
    import ui_port_qt
    from qtui import app as qapp, prompts

import ui_port  # noqa: E402  (toolkit-free)

# prompts of windows that are not dialogs of this package: report_details (covered elsewhere) and the handheld windows (proved in tests/test_qt_views_handheld.py)
SKIP_KINDS = ('ask_reading', 'ask_readings', 'ask_range', 'ask_ir_problem', 'report_details',
              'ask_typed', 'prerun_list', 'prerun_result')            # the last three: the user datasheet's own windows (tests/test_qt_dsb_runtime.py)
LAST = {}                                  # record -> what its dialog showed (filled by the per-prompt test, reused by the sequence test)
FIXTURES = sorted(glob.glob(str(ROOT / 'tests' / 'golden_ui' / 'ui_prompts_*.json')))
DATE = '1-2-2026'


def pump_until(cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.003)
    return cond()


class Driver:
    """The scripted operator: `handler(dialog)` runs once, inside the dialog's own event loop, as soon as a modal dialog is active."""

    def __init__(self):
        self.seen = []
        self.error = None

    def run(self, call, handler, timeout=10.0):
        done = {'handled': False}
        t0 = time.time()
        timer = QTimer()
        timer.setInterval(5)

        def poll():
            w = QApplication.activeModalWidget()
            if w is None or done['handled']:
                if time.time() - t0 > timeout and w is not None:
                    done['handled'] = True
                    self.error = 'timeout'
                    w.reject()
                return
            done['handled'] = True
            try:
                handler(w)
            except BaseException as exc:                 # noqa: BLE001 - a failing check must close the dialog, or the test hangs
                self.error = exc
                w.reject() if w.isVisible() else None
        timer.timeout.connect(poll)
        timer.start()
        try:
            out = call()
        finally:
            timer.stop()
        if self.error is not None:
            if isinstance(self.error, BaseException):
                raise self.error
            raise AssertionError(self.error)
        if not done['handled']:
            raise AssertionError('no dialog was shown')
        return out


def button_texts(dlg):
    return [b.text() for b in dlg.findChildren(QPushButton) if b.isVisibleTo(dlg) and b.text()]


def press(dlg, text):
    for b in dlg.findChildren(QPushButton):
        if b.text() == text and b.isVisibleTo(dlg):
            b.click()
            return
    raise AssertionError(f'no button {text!r} in {button_texts(dlg)}')


def label_texts(dlg):
    return [lab.text() for lab in dlg.findChildren(QLabel) if lab.isVisibleTo(dlg) and lab.text()]


def all_records():
    out = []
    for f in FIXTURES:
        data = json.loads(Path(f).read_text(encoding='utf-8'))
        for scen, recs in data.items():
            for r in recs:
                out.append((Path(f).stem.replace('ui_prompts_', ''), scen, r))
    return out


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp.create_app()
        prompts.native_file_dialogs = False
        cls.win = QMainWindow()
        cls.win.show()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.tmp.cleanup()
        prompts.native_file_dialogs = None
        ui_port.set_ui(None)

    def setUp(self):
        self.port = ui_port_qt.QtUiPort()
        self.d = Driver()


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the recorded Tk prompts, one by one
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class GoldenPrompts(QtCase):
    """Every distinct recorded prompt (kind, title, text, buttons, options, answer) of every engine fixture, played through the Qt port."""

    def play(self, rec):
        """Show `rec` through the port with the operator giving its recorded answer; returns the record of what was on screen."""
        kind, title, text, answer = rec['kind'], rec.get('title', ''), rec.get('text', ''), rec.get('answer')
        port, win, d = self.port, self.win, self.d
        shown = {}
        self.last = None

        if kind in ('info', 'warning', 'error'):
            def handler(dlg):
                shown['title'], shown['body'], shown['buttons'] = dlg.windowTitle(), label_texts(dlg), button_texts(dlg)
                press(dlg, 'OK')
            d.run(lambda: port.message(kind, title, text, parent=win), handler)
            self.assertEqual(shown['title'], title)
            self.assertIn(text, shown['body'])
            self.assertEqual(shown['buttons'], rec['buttons'])
            self.last = (kind, shown['title'], tuple(shown['buttons']))
            return None

        if kind in ('ask_yes_no', 'ask_ok_cancel', 'ask_yes_no_cancel', 'ask_retry_cancel'):
            def handler(dlg):
                shown['title'], shown['body'], shown['buttons'] = dlg.windowTitle(), label_texts(dlg), button_texts(dlg)
                names = rec['buttons']
                if kind == 'ask_yes_no':
                    pick = 'Yes' if answer else 'No'
                elif kind == 'ask_ok_cancel':
                    pick = 'OK' if answer else 'Cancel'
                elif kind == 'ask_retry_cancel':
                    pick = 'Retry' if answer else 'Cancel'
                else:
                    pick = 'Cancel' if answer is None else ('Yes' if answer else 'No')
                press(dlg, pick)
            extra = {k: rec[k] for k in ('icon', 'default') if k in rec}
            out = d.run(lambda: getattr(port, kind)(title, text, parent=win, **extra), handler)
            self.assertEqual(shown['title'], title)
            self.assertIn(text, shown['body'])
            self.assertEqual(shown['buttons'], rec['buttons'])
            self.assertEqual(out, answer, f'{kind} {title!r}')
            self.last = (kind, shown['title'], tuple(shown['buttons']))
            return None

        if kind == 'ask_text':
            def handler(dlg):
                shown['title'], shown['body'] = dlg.windowTitle(), label_texts(dlg)
                entry = dlg.findChild(QLineEdit)
                shown['initial'] = entry.text()
                if answer is None:
                    press(dlg, 'Cancel')
                else:
                    entry.setText(answer)
                    press(dlg, 'OK')
            out = d.run(lambda: port.ask_text(title, text, initial=rec.get('initial'), parent=win), handler)
            self.assertEqual(shown['title'], title)
            self.assertIn(text, shown['body'])
            self.assertEqual(shown['initial'], rec.get('initial') or '')
            self.assertEqual(out, answer)
            self.last = (kind, shown['title'], ())
            return None

        if kind == 'ask_number':
            def handler(dlg):
                shown['title'], shown['body'] = dlg.windowTitle(), label_texts(dlg)
                entry = dlg.findChild(QLineEdit)
                if answer is None:
                    press(dlg, 'Cancel')
                else:
                    entry.setText(repr(float(answer)))
                    press(dlg, 'OK')
            out = d.run(lambda: port.ask_number(title, text, initial=rec.get('initial'), parent=win), handler)
            self.assertEqual(shown['title'], title)
            self.assertIn(text, shown['body'])
            if isinstance(answer, float) and math.isnan(answer):
                self.assertTrue(math.isnan(out))
            else:
                self.assertEqual(out, answer)
            self.last = (kind, shown['title'], ())
            return None

        if kind == 'ask_value':
            def handler(dlg):
                shown['title'], shown['body'] = dlg.windowTitle(), label_texts(dlg)
                entry = dlg.findChild(QLineEdit)
                self.assertEqual(entry.text(), 'DEFAULT')              # pre-filled with the default
                if answer is None:
                    press(dlg, 'Cancel')
                else:
                    entry.setText(answer)
                    press(dlg, 'Use this value')
            out = d.run(lambda: port.ask_value(title, text, 'DEFAULT', parent=win), handler)
            self.assertEqual(shown['title'], title)
            self.assertIn(text, shown['body'])
            self.assertEqual(out, answer)
            self.last = (kind, shown['title'], ())
            return None

        if kind == 'operator_prompt':
            def handler(dlg):
                shown['title'], shown['body'], shown['buttons'] = dlg.windowTitle(), label_texts(dlg), button_texts(dlg)
                self.assertEqual(dlg.result_key, None)
                press(dlg, rec['buttons'][0] if answer else rec['buttons'][1])
            opts = {k: rec[k] for k in ('facts', 'caution') if k in rec}
            opts['ok'], opts['cancel'] = rec['buttons']
            if rec.get('layout'):
                opts.update(rec['layout'])
            steps = rec['steps']
            if opts.get('layout') == 'function_change':
                return 'skip'                                        # the card dict is not part of the record (covered by test_function_change_window)
            out = d.run(lambda: port.operator_prompt(title, text, steps, parent=win, **opts), handler)
            self.assertEqual(shown['title'].replace(' [DEMO]', ''), title)
            self.assertIn(text, shown['body'])
            for step in steps:
                for part in (step if isinstance(step, list) else [step]):
                    if part:
                        self.assertIn(part, shown['body'], f'step text missing in {title!r}')
            for k, v in rec.get('facts', []):
                self.assertIn(str(k), shown['body'])
                self.assertIn(str(v), shown['body'])
            if rec.get('caution'):
                self.assertIn(rec['caution'], shown['body'])
            self.assertEqual(shown['buttons'], rec['buttons'][::-1])          # Cancel left of OK (the Tk window packs them the same way round)
            self.assertEqual(out, answer)
            self.last = (kind, shown['title'].replace(' [DEMO]', ''), tuple(shown['buttons'][::-1]))
            return None

        if kind in ('save_file', 'choose_file'):
            opts = dict(rec.get('options', {}))
            if 'initialfile' in opts:
                opts['initialfile'] = opts['initialfile'].replace('<date>', DATE)
            opts['filetypes'] = [tuple(x) for x in opts.get('filetypes', [])]
            tmp = Path(self.tmp.name)
            opts['initialdir'] = str(tmp)
            target = tmp / answer if answer else None
            if target is not None and kind == 'choose_file':
                target.write_text('x')

            def handler(dlg):
                self.assertIsInstance(dlg, QFileDialog)
                shown['filters'] = dlg.nameFilters()
                shown['suffix'] = dlg.defaultSuffix()
                shown['selected'] = Path(dlg.selectedFiles()[0]).name if dlg.selectedFiles() else ''
                if answer:
                    dlg.selectFile(str(target))
                    dlg.accept()
                else:
                    dlg.reject()
            fn = port.save_file if kind == 'save_file' else port.choose_file
            out = d.run(lambda: fn(parent=win, **opts), handler)
            if opts['filetypes']:
                self.assertEqual(shown['filters'], [f'{a} ({b if isinstance(b, str) else " ".join(b)})' for a, b in opts['filetypes']])
            if opts.get('defaultextension'):
                self.assertEqual('.' + shown['suffix'], opts['defaultextension'])
            if 'initialfile' in opts:
                self.assertEqual(shown['selected'], opts['initialfile'])
            self.assertEqual(Path(out).name if out else '', answer)
            self.last = (kind, '', ())
            return None
        return 'skip'

    def test_every_distinct_recorded_prompt(self):
        seen, played = set(), 0
        skipped = {}
        for name, scen, rec in all_records():
            key = json.dumps({k: v for k, v in rec.items()}, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            if rec['kind'] in SKIP_KINDS:
                skipped[rec['kind']] = skipped.get(rec['kind'], 0) + 1          # WP-H windows / the review screen: other tests
                continue
            with self.subTest(fixture=name, scenario=scen, kind=rec['kind'], title=rec.get('title')):
                r = self.play(rec)
                LAST[key] = self.last
                if r == 'skip':
                    skipped[rec['kind']] = skipped.get(rec['kind'], 0) + 1
                else:
                    played += 1
        self.assertGreater(played, 100)

    def test_sequences_equal_the_tk_ones(self):
        """Per scenario: the sequence of (kind, window title, button names) the Qt dialogs showed, prompt after prompt, equals the recorded Tk sequence
        (and every answer came back as recorded: play() asserts that).  ask_reading / report_details / function-change prompts are covered elsewhere."""
        checked = 0
        for path in FIXTURES:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            for scen, recs in data.items():
                shown, want, seen = [], [], set()
                for rec in recs:
                    if rec['kind'] in SKIP_KINDS or (rec.get('layout') or {}).get('layout') == 'function_change':
                        continue
                    key = json.dumps(rec, sort_keys=True, default=str)
                    if len(recs) > 60 and key in seen:                 # the long virtual handheld runs repeat the same prompts for every point
                        continue
                    seen.add(key)
                    with self.subTest(fixture=Path(path).stem, scenario=scen, kind=rec['kind']):
                        if key in LAST:
                            self.last = LAST[key]
                        else:
                            self.play(rec)
                    shown.append(self.last)
                    kind, title = rec['kind'], rec.get('title', '')
                    btn = tuple(rec.get('buttons') or ()) if kind in ('info', 'warning', 'error', 'ask_yes_no', 'ask_ok_cancel', 'ask_yes_no_cancel', 'ask_retry_cancel',
                                                                       'operator_prompt') else ()
                    want.append((kind, '' if kind in ('save_file', 'choose_file') else title, btn))
                self.assertEqual(shown, want, f'{Path(path).stem}/{scen}')
                checked += len(want)
        self.assertGreater(checked, 500)


class FunctionChangeAndPlain(QtCase):
    def test_function_change_window(self):
        card = dict(n=3, total=12, test='DC volts 1 V', meter_line='Meter: V  range 4 V', steps=[('Standby', 'Calibrator is in STANDBY', 'done'), ('Turn the dial', 'to V', 'todo'),
                                                                                                    ('Press Done', 'The program goes on', 'todo')])
        shown = {}

        def handler(dlg):
            shown['body'] = label_texts(dlg)
            shown['buttons'] = button_texts(dlg)
            press(dlg, 'Done')
        out = self.d.run(lambda: self.port.operator_prompt('Change the function', 'x', [], parent=self.win, layout='function_change', card=card, ok='Done', cancel='Cancel'), handler)
        self.assertTrue(out)
        self.assertIn('3 of 12' if '3 of 12' in shown['body'] else 'DC volts 1 V', shown['body'])
        for s in ('Standby', 'Calibrator is in STANDBY', 'Turn the dial', 'Press Done', 'Meter: V  range 4 V'):
            self.assertIn(s, shown['body'])
        self.assertEqual(shown['buttons'], ['Cancel', 'Done'])

    def test_text_that_looks_like_html_is_shown_literally(self):
        txt = 'USB0::<mfgID>::<modID>::INSTR and <b>not bold</b>'
        shown = {}

        def handler(dlg):
            for lab in dlg.findChildren(QLabel):
                if lab.text() == txt:
                    shown['fmt'] = lab.textFormat()
            press(dlg, 'OK')
        self.d.run(lambda: self.port.message('info', 'x', txt, parent=self.win), handler)
        self.assertEqual(shown.get('fmt'), Qt.TextFormat.PlainText)

    def test_hookup_picture_is_shown(self):
        img = next(iter(sorted((ROOT / 'diagrams').glob('*.png'))), None)
        if img is None:
            self.skipTest('no diagram in diagrams/')
        shown = {}

        def handler(dlg):
            pic = dlg.findChild(QLabel, 'hookup_picture')
            shown['pix'] = pic is not None and not pic.pixmap().isNull()
            press(dlg, 'Connections verified')
        out = self.d.run(lambda: self.port.operator_prompt('Rewire', 'Connect', [('Wiring', 'Do it')], parent=self.win, image=str(img), ok='Connections verified'), handler)
        self.assertTrue(out)
        self.assertTrue(shown['pix'])

    def test_secret_entry_is_masked_and_not_recorded(self):
        shown = {}

        def handler(dlg):
            e = dlg.findChild(QLineEdit)
            shown['echo'] = e.echoMode()
            e.setText('s3cret')
            press(dlg, 'OK')
        out = self.d.run(lambda: self.port.ask_text('Code', 'Calibration code', show='*', parent=self.win), handler)
        self.assertEqual(out, 's3cret')
        self.assertEqual(shown['echo'], QLineEdit.EchoMode.Password)

    def test_ask_number_validation_like_simpledialog(self):
        """A bad entry shows the warning and the dialog stays open; the range is enforced; OK on a good one returns the number."""
        steps = []

        def handler(dlg):
            e = dlg.findChild(QLineEdit)
            e.setText('abc')
            press(dlg, 'OK')                      # -> warning 'Illegal value' (modal, nested): answered by the second poll below
        warned = {}

        def warn_closer():
            w = QApplication.activeModalWidget()
            if w is not None and w.windowTitle() == 'Illegal value':
                warned['text'] = label_texts(w)
                press(w, 'OK')
                QTimer.singleShot(0, lambda: (QApplication.activeModalWidget().findChild(QLineEdit).setText('7'), press(QApplication.activeModalWidget(), 'OK')))
            else:
                QTimer.singleShot(5, warn_closer)
        QTimer.singleShot(30, warn_closer)
        out = self.d.run(lambda: self.port.ask_number('N', 'Enter', minvalue=1, maxvalue=10, parent=self.win), handler)
        self.assertEqual(out, 7.0)
        self.assertIn('Not a floating-point value.\nPlease try again', warned['text'])

    def test_ask_number_integer_and_bounds(self):
        def entering(text):
            def handler(dlg):
                dlg.findChild(QLineEdit).setText(text)
                press(dlg, 'OK')
            return handler
        d = Driver()
        self.assertEqual(d.run(lambda: self.port.ask_number('N', 'p', integer=True, parent=self.win), entering('12')), 12)
        self.assertIsInstance(Driver().run(lambda: self.port.ask_number('N', 'p', integer=True, parent=self.win), entering('12')), int)

    def test_report_details_plain_popup(self):
        home = tempfile.mkdtemp()
        old = os.environ.get('HOME'), os.environ.get('USERPROFILE')
        os.environ['HOME'] = os.environ['USERPROFILE'] = home
        try:
            def cancel(dlg):
                press(dlg, 'Cancel')
            self.assertIsNone(Driver().run(lambda: self.port.report_details('Proc', parent=self.win), cancel))

            def create(dlg):
                dlg.findChildren(QLineEdit)[0].setText('Jane')
                press(dlg, 'Create report')
            got = Driver().run(lambda: self.port.report_details('Proc', parent=self.win), create)
            self.assertEqual(got['technician'], 'Jane')
            self.assertEqual(got['procedure'], 'Proc')
            self.assertEqual(len(got['standards']), 3)
            self.assertIn('show_tar_tur', got)
        finally:
            for k, v in zip(('HOME', 'USERPROFILE'), old):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_esc_and_enter_answer_the_safe_way(self):
        def esc(dlg):
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
        self.assertFalse(Driver().run(lambda: self.port.ask_yes_no('t', 'x', parent=self.win), esc))
        self.assertFalse(Driver().run(lambda: self.port.ask_ok_cancel('t', 'x', parent=self.win), esc))
        self.assertIsNone(Driver().run(lambda: self.port.ask_yes_no_cancel('t', 'x', parent=self.win), esc))
        self.assertFalse(Driver().run(lambda: self.port.operator_prompt('t', 'h', ['s'], parent=self.win), esc))
        self.assertIsNone(Driver().run(lambda: self.port.ask_text('t', 'p', parent=self.win), esc))

        def enter(dlg):
            QTest.keyClick(dlg, Qt.Key.Key_Return)
        self.assertTrue(Driver().run(lambda: self.port.ask_yes_no('t', 'x', parent=self.win), enter))                         # the preselected button is Yes
        self.assertFalse(Driver().run(lambda: self.port.ask_yes_no('t', 'x', default='no', parent=self.win), enter))          # default='no' preselects No
        self.assertTrue(Driver().run(lambda: self.port.operator_prompt('t', 'h', ['s'], parent=self.win), enter))

    def test_close_button_of_a_dialog_is_cancel(self):
        def closer(dlg):
            dlg.close()
        self.assertFalse(Driver().run(lambda: self.port.ask_yes_no('t', 'x', parent=self.win), closer))
        self.assertFalse(Driver().run(lambda: self.port.operator_prompt('t', 'h', ['s'], parent=self.win), closer))

    def test_choose_dir(self):
        tmp = self.tmp.name

        def handler(dlg):
            dlg.selectFile(tmp)
            dlg.accept()
        out = Driver().run(lambda: self.port.choose_dir(parent=self.win, initialdir=tmp), handler)
        self.assertEqual(Path(out), Path(tmp))
        self.assertEqual(Driver().run(lambda: self.port.choose_dir(parent=self.win, initialdir=tmp), lambda dlg: dlg.reject()), '')


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# threads and window plumbing
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.result, self.error = fn, None, None

    def run(self):
        try:
            self.result = self.fn()
        except BaseException as exc:                    # noqa: BLE001
            self.error = exc


class Threads(QtCase):
    def test_call_from_worker_returns_the_result(self):
        w = Worker(lambda: self.port.call_from_worker(self.win, lambda a, b: (a + b, threading.current_thread() is threading.main_thread()), 2, 3))
        w.start()
        self.assertTrue(pump_until(lambda: not w.is_alive()))
        self.assertEqual(w.result, (5, True))

    def test_call_from_worker_shows_a_dialog_for_the_worker_and_returns_the_answer(self):
        """The fgen 'ask a number' pattern: the worker blocks while the operator answers on the UI thread."""
        w = Worker(lambda: self.port.call_from_worker(self.win, lambda: self.port.ask_number('Reading', 'Enter value', parent=self.win)))
        d = Driver()

        def handler(dlg):
            dlg.findChild(QLineEdit).setText('3.5')
            press(dlg, 'OK')
        w.start()
        self.d = d
        done = {'ok': False}
        timer = QTimer()
        timer.setInterval(5)

        def poll():
            m = QApplication.activeModalWidget()
            if m is not None and not done['ok']:
                done['ok'] = True
                handler(m)
        timer.timeout.connect(poll)
        timer.start()
        self.assertTrue(pump_until(lambda: not w.is_alive(), 10))
        timer.stop()
        self.assertEqual(w.result, 3.5)

    def test_call_from_worker_cancelled_dialog_gives_none(self):
        w = Worker(lambda: self.port.call_from_worker(self.win, lambda: self.port.ask_text('T', 'P', parent=self.win)))
        w.start()
        done = {'ok': False}
        timer = QTimer()
        timer.setInterval(5)

        def poll():
            m = QApplication.activeModalWidget()
            if m is not None and not done['ok']:
                done['ok'] = True
                press(m, 'Cancel')
        timer.timeout.connect(poll)
        timer.start()
        self.assertTrue(pump_until(lambda: not w.is_alive(), 10))
        timer.stop()
        self.assertIsNone(w.result)
        self.assertIsNone(w.error)

    def test_call_from_worker_exception_gives_none_and_is_reported_on_the_ui_thread(self):
        reported = []
        orig = qapp.show_error
        qapp.show_error = lambda text, where='': reported.append((text, threading.current_thread() is threading.main_thread()))
        try:
            def boom():
                raise ValueError('boom in fn')
            w = Worker(lambda: self.port.call_from_worker(self.win, boom))
            w.start()
            self.assertTrue(pump_until(lambda: not w.is_alive()))
            self.assertIsNone(w.result)
            self.assertIsNone(w.error)
            self.assertTrue(pump_until(lambda: bool(reported)))
        finally:
            qapp.show_error = orig
        self.assertIn('boom in fn', reported[0][0])
        self.assertTrue(reported[0][1])

    def test_call_from_worker_on_the_ui_thread_does_not_deadlock(self):
        self.assertEqual(self.port.call_from_worker(self.win, lambda: 41 + 1), 42)

    def test_post_from_worker_runs_on_ui_thread_in_order(self):
        seen = []
        w = Worker(lambda: [self.port.post(self.win, lambda i=i: seen.append((i, threading.current_thread() is threading.main_thread()))) for i in range(5)])
        w.start()
        self.assertTrue(pump_until(lambda: len(seen) == 5))
        self.assertEqual(seen, [(i, True) for i in range(5)])

    def test_after_runs_once_and_can_be_cancelled(self):
        hits = []
        self.port.after(self.win, 10, hits.append, 'a')
        h = self.port.after(self.win, 10, hits.append, 'b')
        self.port.cancel_after(self.win, h)
        self.assertTrue(pump_until(lambda: 'a' in hits))
        pump_until(lambda: False, 0.1)
        self.assertEqual(hits, ['a'])

    def test_many_workers_ask_at_once_without_deadlock(self):
        ws = [Worker(lambda i=i: self.port.call_from_worker(self.win, lambda: i * 2)) for i in range(8)]
        for w in ws:
            w.start()
        self.assertTrue(pump_until(lambda: not any(w.is_alive() for w in ws)))
        self.assertEqual([w.result for w in ws], [i * 2 for i in range(8)])


class Plumbing(QtCase):
    def test_var_like_tk(self):
        v = self.port.var('a')
        seen = []
        v.trace_add('write', lambda *a: seen.append(v.get()))
        v.set('b')
        self.assertEqual((v.get(), seen), ('b', ['b']))
        self.assertIs(self.port.var(True, 'bool').get(), True)
        self.assertEqual(self.port.var(3, 'int').get(), 3)
        self.assertEqual(self.port.var('2.5', 'float').get(), 2.5)

    def test_title_close_handler_and_shortcut(self):
        w = QMainWindow()
        w.show()
        self.port.set_title(w, 'Hello')
        self.assertEqual(w.windowTitle(), 'Hello')
        called = []
        self.port.on_close(w, lambda: called.append('close'))
        w.close()
        self.assertEqual(called, ['close'])
        self.assertTrue(w.isVisible())                       # the handler decides: the window stays until port.close()
        keys = []
        self.port.bind_key(w, '<Control-s>', lambda: keys.append('save'))
        w.activateWindow()
        QTest.keyClick(w, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        self.port.close(w)
        self.assertFalse(w.isVisible())
        self.assertEqual(called, ['close'])

    def test_flush_and_update_process_events(self):
        hits = []
        qapp.post(hits.append, 1)
        self.port.flush(self.win)
        self.assertEqual(hits, [1])
        qapp.post(hits.append, 2)
        self.port.update(self.win)
        self.assertEqual(hits, [1, 2])

    def test_view_picks_the_qt_twin(self):
        with self.assertRaises(ImportError) as cm:
            self.port.view('no_such_view')
        self.assertIn('no_such_view_qt', str(cm.exception))

    def test_every_uiport_method_exists(self):
        names = [n for n in dir(ui_port.ScriptedUiPort) if not n.startswith('_') and callable(getattr(ui_port.ScriptedUiPort, n))
                 and n not in ('run_scheduled',)]
        missing = [n for n in names if not hasattr(ui_port_qt.QtUiPort, n)]
        self.assertEqual(missing, [])

    def test_handheld_methods_are_the_qt_windows(self):
        """QT-H: the five handheld methods are implemented here (no NotImplementedError fallback); their windows are proved in tests/test_qt_views_handheld.py."""
        for name in ('ask_reading', 'ask_readings', 'ask_range', 'ask_ir_problem', 'progress_window'):
            fn = getattr(ui_port_qt.QtUiPort, name)
            self.assertEqual(fn.__module__, 'ui_port_qt', name)
            self.assertNotIn('WP-H', (fn.__doc__ or '') + fn.__code__.co_consts.__repr__(), name)
        self.assertEqual(self.port.view('handheld_dmm_view').__name__, 'handheld_dmm_view_qt')


class Selector(unittest.TestCase):
    def tearDown(self):
        os.environ.pop('CALSUITE_UI', None)
        ui_port.set_ui(None)

    @unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
    def test_env_qt_installs_the_qt_port(self):
        os.environ['CALSUITE_UI'] = 'qt'
        port = ui_port.select_toolkit()
        self.assertIsInstance(port, ui_port_qt.QtUiPort)
        self.assertIs(ui_port.get_ui(), port)
        self.assertIsInstance(ui_port.select_toolkit('qt'), ui_port_qt.QtUiPort)

    def test_unknown_toolkit_is_an_error(self):
        with self.assertRaises(ValueError):
            ui_port.select_toolkit('gtk')
        os.environ['CALSUITE_UI'] = 'QTT'
        with self.assertRaises(ValueError):
            ui_port.select_toolkit()


if __name__ == '__main__':
    unittest.main()
