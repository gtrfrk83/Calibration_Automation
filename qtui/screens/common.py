"""Small helpers the QT-E screens share (procedure editor, point editor, run queue, readiness window, manual grid): the Qt counterparts of the
tkinter messagebox / simpledialog / filedialog calls the Tk twins make, a colour-from-token label, and a few widget conveniences.

Every message goes through ONE function per kind (`ask_yes_no`, `show_info`, `ask_text`, ...) that a screen calls as `common.ask_yes_no(...)`, so a test
(or a scripted operator) patches that name and the screen takes the answer without a modal loop.  Colours come from `theme.tokens()` and follow a theme
switch.  No Tk import, no engine import.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QWidget

from qtui import theme
from qtui.widgets import MessageDialog, ModalDialog, label


def qparent(obj) -> QWidget | None:
    """`obj` if it is a Qt widget (the shell / root an engine hands over), else None (a headless caller, a Tk object, None)."""
    return obj if isinstance(obj, QWidget) else None


def alive(widget) -> bool:
    """False for None and for a widget whose C++ object is gone (the Qt counterpart of winfo_exists)."""
    if widget is None:
        return False
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


# ---- message boxes ---------------------------------------------------------------------------------------------------------------------------------
def ask_yes_no(parent, title: str, text: str, *, yes: str = 'Yes', no: str = 'No', kind: str = 'question') -> bool:
    """tkinter messagebox.askyesno: Yes is the default button, Esc / closing the window answers No."""
    dlg = MessageDialog(qparent(parent), kind, title, text, buttons=((no, 'no', None), (yes, 'yes', 'primary')), cancel_key='no')
    return dlg.run() == 'yes'


def show_info(parent, title: str, text: str) -> None:
    MessageDialog(qparent(parent), 'info', title, text).run()


def show_warning(parent, title: str, text: str) -> None:
    MessageDialog(qparent(parent), 'warning', title, text).run()


def show_error(parent, title: str, text: str) -> None:
    MessageDialog(qparent(parent), 'error', title, text).run()


def ask_text(parent, title: str, prompt: str, initial: str = '') -> str | None:
    """tkinter simpledialog.askstring: the text, or None when cancelled."""
    dlg = ModalDialog(qparent(parent), title)
    dlg.title_label.hide()
    dlg.add_text(prompt)
    edit = QLineEdit(initial)
    dlg.body.addWidget(edit)
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('OK', role='primary', default=True, result='ok')
    dlg.initial_focus = edit
    return edit.text() if dlg.run() == 'ok' else None


def ask_save_path(parent, title: str = '', default_suffix: str = '', filters: str = '') -> str:
    path, _flt = QFileDialog.getSaveFileName(qparent(parent), title, '', filters)
    if path and default_suffix and '.' not in path.replace('\\', '/').rsplit('/', 1)[-1]:
        path += default_suffix
    return path or ''


def ask_open_path(parent, title: str = '', filters: str = '') -> str:
    path, _flt = QFileDialog.getOpenFileName(qparent(parent), title, '', filters)
    return path or ''


# ---- widgets ---------------------------------------------------------------------------------------------------------------------------------------
class ToneLabel(QLabel):
    """A wrapped label whose text colour is a theme token ('bad', 'warn', 'good', 'muted' ...) and follows a theme switch."""

    def __init__(self, tone: str = 'bad', text: str = '', *, wrap: bool = True, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._tone = tone
        self.setWordWrap(wrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        theme.manager().changed.connect(self._retone)
        self._retone()

    def _retone(self, *_):
        try:
            self.setStyleSheet(f'color: {theme.tokens()[self._tone]};')
        except RuntimeError:
            pass

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._retone()

    def set(self, text: str) -> None:
        self.setText(text)


class TextVar:
    """Just enough of a tk.StringVar around a QLineEdit / QLabel for the code that reads and writes a value (`get` / `set`)."""

    def __init__(self, widget):
        self.w = widget

    def get(self) -> str:
        return self.w.text()

    def set(self, value) -> None:
        self.w.setText('' if value is None else str(value))


def hint(text: str = '', *, wrap: bool = True) -> QLabel:
    """A muted small paragraph (the Tk 'Small.TLabel' / 'Muted.TLabel')."""
    lab = label(text, 'hint', wrap=wrap)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def set_enabled(widgets, enabled: bool) -> None:
    for w in widgets:
        try:
            w.setEnabled(bool(enabled))
        except (RuntimeError, AttributeError):
            pass


def set_button_state(button, enabled: bool) -> None:
    """A shell's 'action' button: a Qt widget / action (setEnabled) or anything with the Tk-style configure(state=...)."""
    if button is None:
        return
    if hasattr(button, 'setEnabled'):
        button.setEnabled(bool(enabled))
    elif hasattr(button, 'configure'):
        button.configure(state='normal' if enabled else 'disabled')


def set_tooltip(widget, text: str) -> None:
    if widget is not None and hasattr(widget, 'setToolTip'):
        widget.setToolTip(text or '')


def clamp_size(win: QWidget, width: int, height: int, min_w: int = 0, min_h: int = 0) -> None:
    """Default window size clamped to the screen it opens on, with a minimum size (the Tk `_size_window`)."""
    scr = (win.screen() or None)
    avail = scr.availableGeometry() if scr is not None else None
    w, h = width, height
    if avail is not None:
        w, h = min(w, avail.width() - 40), min(h, avail.height() - 90)
    win.resize(max(w, 200), max(h, 200))
    win.setMinimumSize(min(min_w, w), min(min_h, h))


def on_ui(fn: Callable, *args, **kw):
    """Run fn on the UI thread and return its result (an engine may call a window function from its worker: the Tk build did it through call_from_worker)."""
    from qtui import app
    if app.is_ui_thread():
        return fn(*args, **kw)
    return app.call_on_ui_thread(fn, *args, **kw)


def post_ui(fn: Callable, *args, **kw) -> None:
    """Fire and forget: fn runs on the UI thread (immediately when already there)."""
    from qtui import app
    if app.is_ui_thread():
        fn(*args, **kw)
    else:
        app.post(fn, *args, **kw)


def tone_css(selector: str, **props) -> str:
    """A one-selector style sheet whose values name theme tokens in braces: tone_css('QFrame#row', border='1px solid {border}', background='{card}')."""
    t = theme.tokens()
    body = ' '.join(f'{k.replace("_", "-")}: {v.format(**t)};' for k, v in props.items())
    return f'{selector} {{ {body} }}'
