"""The Stop / Continue window of surprise.py for Qt (twin of surprise_view_tk.py; same public function `dialog(root, title, s)`).  Reached through
ui_port.get_ui().view('surprise_view').

What stays exactly as in the Tk build:
  * the window shows the kind of surprise (bold), the instrument / command / reply / expected lines, the 'Continue is not offered' note for a stop_only
    surprise, the last log lines (read-only, no wrapping), and the buttons Stop and Continue (Stop only when stop_only);
  * Stop has the focus, closing the window (the title-bar X, Esc) is Stop, only the Continue button answers True;
  * `dialog` blocks until the operator answered and returns True (Continue) / False (Stop).

The worker-thread protocol is NOT here, it is surprise._TkAsker (toolkit-free, unchanged): the worker queues a request and waits, a poller that runs ON the UI
thread (`schedule(ms, fn)`, below: a Qt single-shot timer) shows this dialog and answers; when nothing picks the request up within START_WAIT (5 s: no event
loop is running, or the handler was made on a thread that has none) the answer is Stop, so a run can never hang.  `make_handler(win)` builds that handler for Qt.
No Tk import."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit

from qtui import theme
from qtui.widgets import ModalDialog, label

from surprise import KINDS


def build(root, title, s):
    """The dialog widget (not yet shown).  `parts` (dict stop / cont / text) are the widgets a test or a caller can reach; `result_key` is 'stop' or 'continue'
    once it was answered."""
    stop_only = bool(getattr(s, 'stop_only', False))
    dlg = ModalDialog(root, title, width=760)
    dlg.title_label.setText(KINDS.get(s.kind, s.kind))               # the Tk window's bold first line (the window title is `title`)
    dlg.body.addWidget(_selectable(s.lines()))
    if stop_only:
        dlg.add_text('Continue is not offered here: the run cannot safely go on from this point.', 'hint')
    dlg.add_text(f'Last {len(s.log_tail)} log lines:', 'section')
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    box.setPlainText('\n'.join(s.log_tail))
    lines_h = 12 * (theme.M.font_mono + 5) + 16                          # 12 lines, as the Tk box (the QSS gives text boxes a min-height of its own, so it is set here)
    box.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {theme.M.font_mono}px; min-height: {lines_h}px;")
    box.setAccessibleName('Log lines')
    dlg.body.addWidget(box, 1)
    stop = dlg.add_button('Stop', role='danger', result='stop', default=True, cancel=True)     # closing the window / Esc is Stop
    cont = None if stop_only else dlg.add_button('Continue', result='continue')
    dlg.initial_focus = stop
    dlg.parts = dict(stop=stop, cont=cont, text=box)
    dlg.resize(max(dlg.sizeHint().width(), 760), dlg.sizeHint().height())
    return dlg


def _selectable(lines):
    lab = label('\n'.join(lines), 'mono', wrap=False)
    from PySide6.QtCore import Qt
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def dialog(root, title, s):
    """Blocks until the operator answered; True = Continue, False = Stop (also when the window is closed)."""
    dlg = build(root, title, s)
    dlg.run()
    return dlg.result_key == 'continue'


def schedule(ms, fn):
    """surprise._TkAsker's `schedule(ms, fn)` for Qt: run fn on the calling thread's event loop after ms.  Called on the UI thread (where the handler is made, and
    from the poller itself); on a thread without a running event loop the timer simply never fires, which is the 'no poller' case (the answer is Stop after 5 s)."""
    QTimer.singleShot(ms, fn)


def make_handler(win, title='Stop on surprise'):
    """The Guard handler for Qt: ONE dialog, True (Continue) / False (Stop).  Make it on the UI thread before the worker thread starts (surprise.tk_handler with the
    Qt scheduler; the protocol is the same as for Tk)."""
    import surprise
    return surprise.tk_handler(win, title, schedule=schedule)
