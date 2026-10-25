"""Application bootstrap for the Qt UI: one QApplication, the theme, HiDPI, the icon hook, `run_app(factory)` (the semantics of ui_port.run_app), an exception
hook that always shows a dialog, and the UI-thread helpers (`post`, `call_on_ui_thread`) a worker thread uses to touch the UI.

    app.create_app()                         # idempotent; call before any widget
    app.run_app(lambda win: build(win))      # win = the main QMainWindow; returns the exit code

Thread helpers (the Qt side of ui_port.post / call_from_worker):
    app.post(fn, *args)                      thread-safe, fire and forget: fn runs later on the UI thread (also when called from the UI thread)
    app.call_on_ui_thread(fn, *args, timeout=None)
        from a worker: run fn on the UI thread, BLOCK until it ran, return its result; an exception in fn is re-raised in the worker (the Tk port gives
        the worker None and reports on the UI thread; the Qt contract is stricter and simpler: the caller always learns).  On the UI thread itself fn is
        just called (no deadlock).  `timeout` seconds -> TimeoutError in the worker (fn is dropped if it had not started; if it already started it finishes
        unobserved).  If the application quits while a worker waits, the wait ends with RuntimeError('the application is closing').
"""
from __future__ import annotations

import os
import re
import sys
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from . import theme

_app: QApplication | None = None
_invoker: '_Invoker | None' = None
_closing = threading.Event()
_icon_hook: Callable[[], QIcon | str | None] | None = None
_log_hook: Callable[[str, str], Any] | None = None
APP_NAME = 'Calibration Suite'


class _Invoker(QObject):
    """Lives on the UI thread.  A signal emitted from any thread is delivered here as a queued call, i.e. runs on the UI thread."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, fn):
        try:
            fn()
        except BaseException:                      # a failing posted call must not kill the event loop: report it like any other uncaught error
            _excepthook(*sys.exc_info())


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# start-up
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def configure_hidpi() -> None:
    """Before the QApplication exists.  Qt 6 is per-monitor DPI aware on Windows by itself; this only makes the scale factors pass through unrounded
    (125 % / 150 % screens stay crisp instead of snapping to 100 / 200 %).  QT_SCALE_FACTOR_ROUNDING_POLICY from the environment wins."""
    if QCoreApplication.instance() is not None:
        return
    if 'QT_SCALE_FACTOR_ROUNDING_POLICY' not in os.environ:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def set_icon_hook(fn: Callable[[], QIcon | str | None] | None) -> None:
    """fn() returns the application icon (QIcon or a file path); called when the app is created, and applied to the app (so every window gets it)."""
    global _icon_hook
    _icon_hook = fn
    if _app is not None:
        _apply_icon()


def set_log_hook(fn: Callable[[str, str], Any] | None) -> None:
    """fn(traceback_text, where) is called for every uncaught exception (the host plugs diagnostics.write_log in).  Its result (e.g. a path) is shown."""
    global _log_hook
    _log_hook = fn


def _apply_icon() -> None:
    if _icon_hook is None or _app is None:
        return
    try:
        ic = _icon_hook()
        if isinstance(ic, str):
            ic = QIcon(ic)
        if ic is not None and not ic.isNull():
            _app.setWindowIcon(ic)
    except Exception:
        pass


def create_app(argv: list[str] | None = None, *, name: str = APP_NAME) -> QApplication:
    """The one QApplication (created once; later calls return it).  Theme applied (dark only for now, see qtui.theme), UI font set, exception hook installed."""
    global _app, _invoker
    inst = QApplication.instance()
    if inst is not None and _app is None:
        _app = inst                                # created by someone else (tests): adopt it
    if _app is None:
        configure_hidpi()
        _app = QApplication(list(argv if argv is not None else sys.argv))
    if _invoker is None:
        _invoker = _Invoker()
        _invoker.moveToThread(_app.thread())
        _app.aboutToQuit.connect(_closing.set)
    _app.setApplicationName(name)
    _app.setStyle('Fusion')                        # the style sheet is written against Fusion: the same look on every platform
    _app.setFont(theme.ui_font())
    theme.manager().apply_initial(_app)
    _apply_icon()
    install_excepthook()
    return _app


def instance() -> QApplication:
    if _app is None:
        raise RuntimeError('qtui.app.create_app() has not been called')
    return _app


def run_app(factory: Callable[[QMainWindow], Any], *, title: str | None = None, size: tuple[int, int] | None = None, show: bool = True) -> int:
    """Same semantic as ui_port.run_app: create the application and its main window, call factory(win) to build the app, run the event loop until the
    window closes, return the exit code.  `win` is a QMainWindow whose central widget the factory sets."""
    app = create_app()
    _closing.clear()
    win = QMainWindow()
    win.setObjectName('main')
    if title:
        win.setWindowTitle(title)
    if size:
        win.resize(*size)
    try:
        factory(win)
    except BaseException:
        _excepthook(*sys.exc_info())
        return 1
    if win.property('_calsuite_closing'):          # the factory closed the window (a launcher whose file question was cancelled): no event loop
        return 0
    if show:
        win.show()
    try:
        return app.exec()
    finally:
        _closing.clear()                           # the app object lives on (tests and hosts may run another loop)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# threads
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def is_ui_thread() -> bool:
    return _app is not None and QThread.currentThread() is _app.thread()


def post(fn: Callable, *args, **kw) -> None:
    """Thread-safe fire and forget: run fn(*args, **kw) on the UI thread soon.  Never blocks, never raises into the caller; an exception in fn goes to
    the exception hook (a dialog)."""
    if _invoker is None:
        raise RuntimeError('qtui.app.create_app() has not been called')
    _invoker.call.emit(lambda: fn(*args, **kw))


def call_on_ui_thread(fn: Callable, *args, timeout: float | None = None, **kw):
    """See the module doc: blocks the calling worker until fn ran on the UI thread; returns its result or re-raises its exception."""
    if _invoker is None:
        raise RuntimeError('qtui.app.create_app() has not been called')
    if is_ui_thread():
        return fn(*args, **kw)
    if _closing.is_set():
        raise RuntimeError('the application is closing')
    box: dict = {}
    done = threading.Event()
    lock = threading.Lock()

    def run():
        with lock:
            if box.get('abandoned'):
                return
            box['started'] = True
        try:
            box['value'] = fn(*args, **kw)
        except BaseException as exc:               # noqa: BLE001 - handed to the worker
            box['error'] = exc
        finally:
            done.set()

    _invoker.call.emit(run)
    waited = 0.0
    while not done.wait(0.1):                       # poll so a closing application releases the worker
        waited += 0.1
        if _closing.is_set():
            with lock:
                if not box.get('started'):
                    box['abandoned'] = True
                    raise RuntimeError('the application is closing')
        if timeout is not None and waited >= timeout:
            with lock:
                if not box.get('started'):
                    box['abandoned'] = True
                    raise TimeoutError(f'the UI thread did not run the call within {timeout:g} s')
            done.wait()                             # already running: let it finish, the result is still valid
            break
    if 'error' in box:
        raise box['error']
    return box.get('value')


def after(ms: int, fn: Callable, *args) -> QTimer:
    """UI thread only: run fn after ms (the Qt side of ui_port.after)."""
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(lambda: (fn(*args), t.deleteLater()))
    t.start(ms)
    return t


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# uncaught exceptions: never silent
# ----------------------------------------------------------------------------------------------------------------------------------------------------
_SECRET = re.compile(r'(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key)\b(\s*[=:]\s*)(\S+)')
_showing = False
_pending = 0
_original_hook = sys.excepthook


def scrub(text: str) -> str:
    """Blank anything that looks like a password or token (the standing rule: never write passwords to logs or screens)."""
    return _SECRET.sub(lambda m: f'{m.group(1)}{m.group(2)}<hidden>', text)


def install_excepthook() -> None:
    sys.excepthook = _excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _thread_excepthook


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    _excepthook(args.exc_type, args.exc_value, args.exc_traceback, where=f'thread {args.thread.name if args.thread else "?"}')


def _excepthook(etype, value, tb, where: str = '') -> None:
    text = scrub(''.join(traceback.format_exception(etype, value, tb)))
    try:
        sys.__stderr__.write(text)
    except Exception:
        pass
    if QApplication.instance() is None:
        return
    if not is_ui_thread():
        post(show_error, text, where)
        return
    show_error(text, where)


def show_error(text: str, where: str = '') -> None:
    """The error dialog (ModalDialog): a plain-language heading, the log location, 'Copy details'.  If one is already open the new error is counted in it
    instead of stacking dialogs."""
    global _showing, _pending
    if _showing:
        _pending += 1
        return
    from .widgets import MessageDialog
    _showing = True
    try:
        logged = ''
        if _log_hook is not None:
            try:
                res = _log_hook(text, where)
                logged = f'\n\nA diagnostic log was saved: {res}' if res else ''
            except Exception:
                pass
        parent = QApplication.activeWindow()
        dlg = MessageDialog(parent, 'error', 'Something went wrong',
                            'The program hit an unexpected error. Your saved data is not affected; if a measurement was running, check the instruments are in standby. '
                            'Please send the details below to support.' + logged,
                            buttons=(('Close', 'close', 'primary'), ('Copy details', 'copy', None)), cancel_key='close', detail=text)
        copy = dlg.button('copy')
        copy.clicked.disconnect()
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(text), copy.setText('Copied')))
        dlg.run()
        if _pending:
            n, _pending = _pending, 0
            _showing = False
            show_error(f'{n} more error(s) occurred while this dialog was open; see the console / log.', where)
    finally:
        _showing = False


def make_main_window(title: str = '', size: tuple[int, int] = (1360, 820)) -> QMainWindow:
    """A themed main window with a 'root' central widget for the style sheet (screens usually use run_app's window instead)."""
    win = QMainWindow()
    win.setWindowTitle(title)
    win.resize(*size)
    root = QWidget()
    root.setObjectName('root')
    win.setCentralWidget(root)
    return win
