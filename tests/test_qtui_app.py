"""qtui.app: UI-thread helpers (post, call_on_ui_thread: success / exception / timeout), the exception dialog, create_app idempotence.
Skipped when PySide6 is not importable.  Headless."""
import os
import sys
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtWidgets import QApplication
    from qtui import app


def pump_until(cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    return cond()


class Worker(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.result, self.error, self.finished = fn, None, None, False

    def run(self):
        try:
            self.result = self.fn()
        except BaseException as exc:                  # noqa: BLE001
            self.error = exc
        self.finished = True


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def test_create_app_is_idempotent_and_dark(self):
        self.assertIs(app.create_app(), self.app)
        self.assertIs(QApplication.instance(), self.app)
        from qtui import theme
        self.assertEqual(theme.name(), 'dark')

    def test_call_on_ui_thread_returns_the_result_and_runs_on_the_ui_thread(self):
        where = []

        def on_ui(a, b=0):
            where.append(app.is_ui_thread())
            return a + b
        w = Worker(lambda: app.call_on_ui_thread(on_ui, 2, b=3))
        w.start()
        self.assertTrue(pump_until(lambda: w.finished))
        self.assertEqual((w.result, w.error), (5, None))
        self.assertEqual(where, [True])

    def test_call_on_ui_thread_blocks_the_worker_until_it_ran(self):
        order = []

        def work():
            order.append('before')
            app.call_on_ui_thread(lambda: (time.sleep(0.15), order.append('ui')))
            order.append('after')
        w = Worker(work)
        w.start()
        self.assertTrue(pump_until(lambda: w.finished))
        self.assertEqual(order, ['before', 'ui', 'after'])

    def test_exception_propagates_to_the_worker(self):
        def boom():
            raise ValueError('nope')
        w = Worker(lambda: app.call_on_ui_thread(boom))
        w.start()
        self.assertTrue(pump_until(lambda: w.finished))
        self.assertIsInstance(w.error, ValueError)
        self.assertEqual(str(w.error), 'nope')

    def test_timeout_when_the_ui_thread_is_busy_and_the_call_is_dropped(self):
        ran = []
        w = Worker(lambda: app.call_on_ui_thread(lambda: ran.append(1), timeout=0.3))
        w.start()
        w.join(3)                                      # this (UI) thread does not pump events meanwhile
        self.assertTrue(w.finished)
        self.assertIsInstance(w.error, TimeoutError)
        pump_until(lambda: False, 0.2)                 # now the queued call is delivered: it must have been dropped
        self.assertEqual(ran, [])

    def test_ui_thread_calls_directly_without_deadlock(self):
        self.assertEqual(app.call_on_ui_thread(lambda: 42), 42)

    def test_post_runs_later_on_the_ui_thread_in_order(self):
        seen = []
        w = Worker(lambda: [app.post(seen.append, i) for i in range(5)])
        w.start()
        w.join(2)
        self.assertEqual(seen, [])                     # nothing ran on the worker
        self.assertTrue(pump_until(lambda: len(seen) == 5))
        self.assertEqual(seen, [0, 1, 2, 3, 4])
        app.post(seen.append, 'ui')                    # from the UI thread it is still deferred
        self.assertEqual(seen[-1], 4)
        self.assertTrue(pump_until(lambda: seen[-1] == 'ui'))

    def test_scrub_hides_passwords(self):
        out = app.scrub('connect password=hunter2 token: abc123 user=bob')
        self.assertNotIn('hunter2', out)
        self.assertNotIn('abc123', out)
        self.assertIn('user=bob', out)

    def test_uncaught_exception_shows_a_dialog_and_never_silent(self):
        from qtui import widgets
        shown = []
        orig = widgets.ModalDialog.run

        def fake_run(self):
            shown.append((self.windowTitle(), self.detail_edit.toPlainText() if getattr(self, 'detail_edit', None) else ''))
            return 'close'
        widgets.ModalDialog.run = fake_run
        err = sys.__stderr__
        devnull = open(os.devnull, 'w')
        sys.__stderr__ = devnull
        try:
            try:
                raise RuntimeError('kaboom password=secret1')
            except RuntimeError:
                app._excepthook(*sys.exc_info())
            self.assertEqual(len(shown), 1)
            self.assertIn('kaboom', shown[0][1])
            self.assertNotIn('secret1', shown[0][1])
            # raised inside a posted call: reported, the event loop keeps running
            app.post(lambda: 1 / 0)
            pump_until(lambda: len(shown) == 2)
            self.assertEqual(len(shown), 2)
            self.assertIn('ZeroDivisionError', shown[1][1])
            # from a thread: the hook posts the dialog to the UI thread
            w = Worker(lambda: app._thread_excepthook(type('A', (), dict(exc_type=KeyError, exc_value=KeyError('k'), exc_traceback=None, thread=threading.current_thread()))))
            w.start()
            w.join(2)
            pump_until(lambda: len(shown) == 3)
            self.assertEqual(len(shown), 3)
        finally:
            widgets.ModalDialog.run = orig
            sys.__stderr__ = err
            devnull.close()

    def test_run_app_builds_and_returns_exit_code(self):
        built = []
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.app.quit)
        code = app.run_app(lambda win: built.append(win), title='t', size=(300, 200))
        self.assertEqual(code, 0)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].windowTitle(), 't')


if __name__ == '__main__':
    unittest.main()
