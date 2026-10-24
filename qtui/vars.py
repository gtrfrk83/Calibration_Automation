"""QtVar: a Tk-variable look-alike (get / set / trace_add / trace_remove) for the Qt build, and `bind()` to tie one to a widget.

The engines and the *_view files talk to `ui_port.var(value, kind)` objects (`asset`, `serial`, `period`, `status_var` ...).  Under Qt the object is a QtVar: a plain
Python value holder that calls its 'write' traces (callback(name, index, mode), like Tk) on every set().  Traces run on the thread that called set(); widgets
bound with `bind()` are only touched on the UI thread (set() from a worker is forwarded with qtui.app.post).

    v = QtVar('abc')                       # kind 'str' | 'bool' | 'int' | 'float'
    bind(line_edit, v)                     # QLineEdit / QComboBox (editable or not) / QCheckBox / QRadioButton(value=) / QLabel (one way) / QPlainTextEdit
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QRadioButton, QWidget

_CAST = {'str': str, 'bool': bool, 'int': int, 'float': float}


def _cast(kind: str, v: Any):
    if kind == 'bool':
        if isinstance(v, str):
            return v.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(v)
    if kind == 'int':
        return int(float(v)) if not isinstance(v, int) else v
    if kind == 'float':
        return float(v)
    return '' if v is None else str(v)


class QtVar:
    """get / set / trace_add('write', cb) / trace_remove like a Tk variable.  Reading is thread-safe; set() calls the traces synchronously."""

    def __init__(self, value: Any = '', kind: str = 'str'):
        if kind not in _CAST:
            raise ValueError(f'unknown variable kind {kind!r}')
        self.kind = kind
        self._lock = threading.RLock()
        self._v = _cast(kind, value)
        self._cbs: dict[str, Callable] = {}
        self._n = 0

    def get(self):
        with self._lock:
            return self._v

    def set(self, v) -> None:
        v = _cast(self.kind, v)
        with self._lock:
            self._v = v
            cbs = list(self._cbs.values())
        for cb in cbs:
            cb('', '', 'write')

    def trace_add(self, mode, callback) -> str:
        """Only 'write' is meaningful (like the ScriptedVar); returns the id for trace_remove."""
        with self._lock:
            self._n += 1
            tid = f'qtvar{self._n}'
            self._cbs[tid] = callback
        return tid

    def trace_remove(self, mode, tid) -> None:
        with self._lock:
            self._cbs.pop(tid, None)

    def __repr__(self):
        return f'QtVar({self._v!r}, {self.kind!r})'


def bind(widget: QWidget, var: QtVar, *, value: Any = None) -> QWidget:
    """Two-way binding of a widget to a QtVar (the Tk `textvariable=` / `variable=`).  A QRadioButton needs `value` (the var is set to it when the button is
    chosen, and the button is checked when var == value).  Returns the widget."""
    from . import app

    def on_ui(fn):
        return lambda *_: fn() if (app.is_ui_thread() or app._invoker is None) else app.post(fn)

    if isinstance(widget, QLabel):
        def push():
            widget.setText(str(var.get()))
        push()
        var.trace_add('write', on_ui(push))
    elif isinstance(widget, QLineEdit):
        def push():
            if widget.text() != str(var.get()):
                widget.setText(str(var.get()))
        push()
        var.trace_add('write', on_ui(push))
        widget.textChanged.connect(lambda t: var.get() != t and var.set(t))
    elif isinstance(widget, QPlainTextEdit):
        def push():
            if widget.toPlainText() != str(var.get()):
                widget.setPlainText(str(var.get()))
        push()
        var.trace_add('write', on_ui(push))
        widget.textChanged.connect(lambda: var.get() != widget.toPlainText() and var.set(widget.toPlainText()))
    elif isinstance(widget, QComboBox):
        def push():
            t = str(var.get())
            if widget.currentText() == t:
                return
            i = widget.findText(t)
            if i >= 0:
                widget.setCurrentIndex(i)
            elif widget.isEditable():
                widget.setEditText(t)
                if widget.lineEdit() is not None:
                    widget.lineEdit().setCursorPosition(0)           # show the start of a long address, not its tail
        push()
        var.trace_add('write', on_ui(push))
        if widget.isEditable():
            widget.editTextChanged.connect(lambda t: var.get() != t and var.set(t))
        widget.currentTextChanged.connect(lambda t: var.get() != t and var.set(t))
    elif isinstance(widget, QRadioButton):
        widget.setAutoExclusive(False)                       # the variable decides which radio button of the set is on (they need not share a parent)

        def push():
            widget.setChecked(var.get() == value)
        push()
        var.trace_add('write', on_ui(push))

        def toggled(on):
            if on and var.get() != value:
                var.set(value)
            elif not on and var.get() == value:              # clicking the chosen button again must not switch it off
                widget.setChecked(True)
        widget.toggled.connect(toggled)
    elif isinstance(widget, (QCheckBox, QAbstractButton)) and widget.isCheckable():
        def push():
            widget.setChecked(bool(var.get()))
        push()
        var.trace_add('write', on_ui(push))
        widget.toggled.connect(lambda on: bool(var.get()) != on and var.set(on))
    else:
        raise TypeError(f'cannot bind a {type(widget).__name__} to a variable')
    return widget
