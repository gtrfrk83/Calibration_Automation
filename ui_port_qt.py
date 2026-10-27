"""QtUiPort: the Qt (PySide6) implementation of ui_port.UiPort.  The Qt twin of ui_port_tk.TkUiPort; the contract is ui_port.py.

Install it before any window exists:   ui_port.set_ui(ui_port_qt.QtUiPort())      (ui_port.select_toolkit() does this for CALSUITE_UI=qt)

What differs from the Tk port, and what is deliberately the same (observable behaviour, as the engines see it):

* Same: every method, its arguments and return value (True / False / None / '' conventions of ui_port.py); every prompt text and button name is the engine's own; the
  prompt sequence of every engine is identical (tests/test_ui_port_qt.py drives the recorded Tk sequences, tests/golden_ui/*.json, through this port).
* `parent` is the host's window (the QMainWindow run_app made); None -> the active window.  It is never part of a recorded prompt.
* Esc / the close button of a dialog answers the SAFE way: No / Cancel / False / None, exactly like the Tk dialogs (askyesno -> False, askokcancel -> False,
  askyesnocancel -> None, askstring / askfloat -> None, confirm_steps -> False).  A plain message (info / warning / error) closes with Esc or Enter.
* `call_from_worker(win, fn, *args)`: Tk ran fn on the UI thread via win.after and returned its result; if fn RAISED, Tk printed the traceback on the UI thread and the
  worker got None.  QtUiPort reproduces that: the worker gets None, the exception is reported on the UI thread by qtui.app's exception hook (a dialog with the traceback,
  never silent) and the worker is not held up by that dialog.  (qtui.app.call_on_ui_thread itself re-raises in the worker; use it directly in new Qt code.)
  Called ON the UI thread (Tk would deadlock) fn is simply called.  If the application is closing the worker gets RuntimeError('the application is closing').
* `post(win, fn, *args)`: thread safe; fn runs on the UI thread later (always queued, also when called from the UI thread).  A failing fn is shown by the exception hook.
* `after(win, ms, fn, *args)` returns a handle (QTimer); `cancel_after(win, handle)` is the Qt twin of win.after_cancel.
* `var()` returns a qtui.vars.QtVar (get / set / trace_add('write', cb) like Tk); bind widgets with qtui.vars.bind.
* `view(name)` picks `<name>_qt` (agilent34410a_view -> agilent34410a_view_qt) and raises ImportError naming the missing Qt twin if that view has not been ported yet.
* `enable_hidpi()` calls qtui.app.configure_hidpi (Qt 6 is DPI aware by itself; this only keeps 125 / 150 % scales unrounded).  `flush` repaints (pending events without user input); `update` processes every pending event (Tk win.update()).
* `report_details` shows the Qt review window when a Qt screen module `qtui.screens.report_review` exists and covers the engine (its `ask(parent, procedure)` -> dict | None |
  UNAVAILABLE), otherwise the plain 'Report details' popup (the Qt copy of report_dialog.ask_details_plain).
* `surprise_handler(win)` is surprise.tk_handler's poller with a Qt schedule; the Stop / Continue window is `surprise_view_qt.dialog` (a Qt view module, reached through view()).
* The handheld windows (ask_reading / ask_range / ask_ir_problem: handheld_dmm_view_qt; ask_readings / progress_window: run_queue_ui_qt) are at the end of this file.
* A secret (ask_text show='*') is masked in the entry and never logged by this module.

This module imports PySide6 and qtui only; no Tk.
"""
from __future__ import annotations

import importlib
import re
import sys

from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLineEdit

import ui_theme_core as core
from qtui import app as qapp
from qtui import prompts
from qtui.theme import M
from qtui.vars import QtVar
from qtui.widgets import ModalDialog

ICON_KIND = {'error': 'error', 'info': 'info', 'question': 'question', 'warning': 'warning'}


def _kw(**kw):
    return {k: v for k, v in kw.items() if v is not None}


# Tk key sequences ('<Control-s>', '<F5>', '<Escape>', '<Alt-Key-1>') -> Qt
_KEYS = {'escape': 'Esc', 'return': 'Return', 'enter': 'Enter', 'kp_enter': 'Enter', 'space': 'Space', 'tab': 'Tab', 'backspace': 'Backspace', 'delete': 'Del',
         'insert': 'Ins', 'home': 'Home', 'end': 'End', 'prior': 'PgUp', 'next': 'PgDown', 'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right'}
_MODS = {'control': 'Ctrl', 'ctrl': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift', 'meta': 'Meta'}


def qt_key_sequence(sequence: str) -> str:
    """'<Control-Shift-S>' -> 'Ctrl+Shift+S'.  Raises ValueError for a sequence that is not a keyboard shortcut."""
    m = re.fullmatch(r'<(.+)>', sequence.strip())
    if not m:
        raise ValueError(f'not a Tk key sequence: {sequence!r}')
    parts, mods, key = m.group(1).split('-'), [], None
    for i, part in enumerate(parts):
        low = part.lower()
        if low in _MODS and i < len(parts) - 1:
            mods.append(_MODS[low])
        elif low in ('key', 'keypress') and i < len(parts) - 1:
            continue
        else:
            key = '-'.join(parts[i:])
            break
    if key is None:
        raise ValueError(f'no key in {sequence!r}')
    low = key.lower()
    if low in _KEYS:
        key = _KEYS[low]
    elif re.fullmatch(r'f\d{1,2}', low):
        key = key.upper()
    elif len(key) == 1:
        if key.isalpha():
            if key.isupper() and 'Shift' not in mods:         # Tk: '<Control-S>' means Ctrl+Shift+S
                mods.append('Shift')
            key = key.upper()
    else:
        raise ValueError(f'unknown key {key!r} in {sequence!r}')
    return '+'.join(mods + [key])


class _CloseFilter(QObject):
    """Tk's protocol('WM_DELETE_WINDOW', fn): the window's close button calls fn instead of closing; fn decides (and calls port.close(win))."""

    def __init__(self, win, fn):
        super().__init__(win)
        self.fn = fn
        win.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Close and not obj.property('_calsuite_closing'):
            ev.ignore()
            self.fn()
            return True
        return False


class QtUiPort:
    """See ui_port.py for the contract and the module doc for the Qt-specific notes."""

    # ---- messages and questions ---------------------------------------------------------------------------------------------------------
    def message(self, kind, title, text, *, parent=None):
        prompts.message(parent, kind, title, text)

    def ask_yes_no(self, title, text, *, icon=None, default=None, parent=None):
        d = 'no' if default == 'no' else 'yes'
        return prompts.question(parent, ICON_KIND.get(icon, 'question'), title, text, (('Yes', 'yes'), ('No', 'no')), default=d, cancel='no') == 'yes'

    def ask_ok_cancel(self, title, text, *, icon=None, parent=None):
        return prompts.question(parent, ICON_KIND.get(icon, 'question'), title, text, (('OK', 'ok'), ('Cancel', 'cancel')), default='ok', cancel='cancel') == 'ok'

    def ask_retry_cancel(self, title, text, *, icon=None, parent=None):
        return prompts.question(parent, ICON_KIND.get(icon, 'warning'), title, text, (('Retry', 'retry'), ('Cancel', 'cancel')), default='retry', cancel='cancel') == 'retry'

    def ask_yes_no_cancel(self, title, text, *, icon=None, parent=None):
        key = prompts.question(parent, ICON_KIND.get(icon, 'question'), title, text, (('Yes', 'yes'), ('No', 'no'), ('Cancel', 'cancel')), default='yes', cancel='cancel')
        return {'yes': True, 'no': False}.get(key)

    def ask_text(self, title, prompt, *, initial=None, show=None, parent=None):
        return prompts.ask_text(parent, title, prompt, initial, show)

    def ask_number(self, title, prompt, *, initial=None, minvalue=None, maxvalue=None, integer=False, parent=None):
        return prompts.ask_number(parent, title, prompt, initial, minvalue, maxvalue, integer)

    def choose_file(self, *, parent=None, **opts):
        return prompts.open_file(parent, **_kw(**opts))

    def save_file(self, *, parent=None, **opts):
        return prompts.save_file(parent, **_kw(**opts))

    def choose_dir(self, *, parent=None, **opts):
        return prompts.choose_dir(parent, **_kw(**opts))

    def operator_prompt(self, title, heading, steps, *, parent=None, **opts):
        return prompts.operator_prompt(parent, title, heading, steps, **opts)

    def report_details(self, procedure='', *, parent=None):
        try:
            review = importlib.import_module('qtui.screens.report_review')
        except ImportError:
            review = None
        if review is not None and hasattr(review, 'ask'):
            out = review.ask(prompts.resolve_parent(parent), procedure)
            if out is not getattr(review, 'UNAVAILABLE', object()):
                return out
        return _report_details_plain(parent, procedure)

    # ---- threads and time ---------------------------------------------------------------------------------------------------------------
    def post(self, win, fn, *args):
        qapp.post(fn, *args)

    def after(self, win, ms, fn, *args):
        owner = win if isinstance(win, QObject) else QApplication.instance()
        timer = QTimer(owner)
        timer.setSingleShot(True)

        def fire():
            timer.deleteLater()
            fn(*args)
        timer.timeout.connect(fire)
        timer.start(max(0, int(ms)))
        return timer

    def cancel_after(self, win, handle):
        try:
            handle.stop()
            handle.deleteLater()
        except RuntimeError:
            pass

    def call_from_worker(self, win, fn, *args):
        def run():
            try:
                return fn(*args)
            except BaseException:                    # noqa: BLE001 - Tk: reported on the UI thread, the worker gets None
                exc = sys.exc_info()
                qapp.post(qapp._excepthook, *exc)
                return None
        return qapp.call_on_ui_thread(run)

    # ---- window and variables -----------------------------------------------------------------------------------------------------------
    def run_app(self, factory):
        qapp.run_app(factory)

    def set_title(self, win, text):
        win.setWindowTitle(text)

    def on_close(self, win, fn):
        _CloseFilter(win, fn)

    def bind_key(self, win, sequence, fn):
        sc = QShortcut(QKeySequence(qt_key_sequence(sequence)), win)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(lambda: fn())

    def close(self, win):
        win.setProperty('_calsuite_closing', True)
        win.close()
        if win.isVisible():                          # called from inside the window's own close event (the on_close handler): Qt ignores a nested close(), so close once that event is over
            QTimer.singleShot(0, win.close)

    def flush(self, win):
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)          # repaint what changed; no clicks / keys are handled here (Tk update_idletasks)

    def var(self, value='', kind='str'):
        return QtVar(value, kind)

    def surprise_handler(self, win):
        import surprise
        return surprise.tk_handler(win, schedule=lambda ms, fn: self.after(win, ms, fn))

    def view(self, name):
        try:
            return importlib.import_module(f'{name}_qt')
        except ModuleNotFoundError as exc:
            if exc.name == f'{name}_qt':
                raise ImportError(f'the Qt window code {name}_qt.py has not been written yet (Qt twin of {name}_tk.py)') from exc
            raise

    # ---- APPENDED BY WP-A (adjustment launchers) ------------------------------------------------------------------------------------------
    def ask_value(self, title, prompt, default, *, parent=None):
        return prompts.ask_value(parent, title, prompt, default)

    def update(self, win):
        QApplication.processEvents()

    def enable_hidpi(self):
        qapp.configure_hidpi()



# ----------------------------------------------------------------------------------------------------------------------------------------------------
# report details: the plain popup (the Qt copy of report_dialog.ask_details_plain)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def _report_details_plain(parent, procedure: str = ''):
    import report_pdf
    store = core.Settings('report_details')
    dlg = ModalDialog(prompts.resolve_parent(parent), prompts._title('Report details'), width=560)
    dlg.title_label.setText('Report details')
    dlg.sub_label.setText('Printed on the report. Everything is optional; entries are remembered for next time.')
    dlg.sub_label.show()
    edits = {k: QLineEdit() for k in ('technician', 'temperature', 'humidity')}      # not shown and not remembered: the cover cert carries them; the keys stay empty in the details
    dlg.body.addWidget(prompts.plain_label('Standards used', 'section', wrap=False))
    saved = store.get('standards', []) or []
    sg = QGridLayout()
    sg.setHorizontalSpacing(M.sm)
    for c, hd in enumerate(('Standard (model)', 'Serial number', 'Calibration due')):
        sg.addWidget(prompts.plain_label(hd, 'hint', wrap=False), 0, c)
    std_rows = []
    for r in range(1, 4):
        prior = saved[r - 1] if r - 1 < len(saved) else {}
        trio = [QLineEdit(str(prior.get(k, '') or '')) for k in ('description', 'serial', 'due')]
        std_rows.append(trio)
        for c, e in enumerate(trio):
            sg.addWidget(e, r, c)
    sg.setColumnStretch(0, 3)
    sg.setColumnStretch(1, 2)
    sg.setColumnStretch(2, 2)
    dlg.body.addLayout(sg)
    remembered = report_pdf.remembered_show_tar_tur()
    tar = QCheckBox('Show TAR on the data file')
    tar.setChecked(bool(remembered.tar))
    tur = QCheckBox('Show TUR on the data file')
    tur.setChecked(bool(remembered.tur))
    left = QCheckBox('As left data as numerical')
    left.setChecked(report_pdf.remembered_left_numeric())
    dlg.body.addWidget(tar)
    dlg.body.addWidget(tur)
    dlg.body.addWidget(left)
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Create report', role='primary', result='ok', default=True)
    if dlg.run() != 'ok':
        return None
    details = {k: e.text().strip() for k, e in edits.items()}
    details['standards'] = [dict(zip(('description', 'serial', 'due'), (x.text().strip() for x in trio))) for trio in std_rows]
    details['procedure'] = procedure
    details['show_tar'], details['show_tur'] = bool(tar.isChecked()), bool(tur.isChecked())
    details['show_tar_tur'] = report_pdf.TarTur(details['show_tar'], details['show_tur'])
    report_pdf.remember_show_tar_tur(details['show_tar_tur'])
    details['left_numeric'] = bool(left.isChecked())
    report_pdf.remember_left_numeric(details['left_numeric'])
    store.set('standards', details['standards'])
    store.save()
    return details




# ----------------------------------------------------------------------------------------------------------------------------------------------------
# HANDHELD WINDOWS (ui_port.py 'Handheld reading windows', work package WP-H; Qt side QT-H).  Like the Tk port, the windows are the toolkit's view code: handheld_dmm_view_qt
# (reading, IR problem, dial) and run_queue_ui_qt (the run-queue reading window and its progress window).  `parent` is resolved to a widget like every prompt's.
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def _ask_reading(self, p, total, out_text, out_note, accept, mode, question=None, unit='', annunciator=False, validate=None, phase='',
                 limit_s=None, on_expire=None, device='METER', source='CALIBRATOR OUTPUT', demo_fill=None, *, parent=None):
    return self.view('handheld_dmm_view').ask_reading(prompts.resolve_parent(parent), p, total, out_text, out_note, accept, mode, question, unit, annunciator, validate,
                                                      phase, limit_s, on_expire, device, source, demo_fill)


def _ask_readings(self, p, total, out_text, out_note, accept, meters, unit='', judge=None, limit_s=None, on_expire=None, device='METER',
                  source='CALIBRATOR OUTPUT', demo_fill=None, tol_text='', phase='', heading='', *, parent=None):
    return importlib.import_module('run_queue_ui_qt').ask_readings(prompts.resolve_parent(parent), p, total, out_text, out_note, accept, meters, unit, judge, limit_s,
                                                                   on_expire, device, source, demo_fill, tol_text, phase, heading)


def _ask_range(self, p, total, dial, standby_text, *, parent=None):
    return self.view('handheld_dmm_view').ask_range(prompts.resolve_parent(parent), p, total, dial, standby_text)


def _ask_ir_problem(self, p, total, problems, shown, *, parent=None):
    return self.view('handheld_dmm_view').ask_ir_problem(prompts.resolve_parent(parent), p, total, problems, shown)


def _progress_window(self, win, title='Queue progress', on_show=None, on_export=None):
    return importlib.import_module('run_queue_ui_qt').QueueProgress(win, **_kw(title=title if title != 'Queue progress' else None, on_show=on_show, on_export=on_export))


QtUiPort.ask_reading = _ask_reading
QtUiPort.ask_readings = _ask_readings
QtUiPort.ask_range = _ask_range
QtUiPort.ask_ir_problem = _ask_ir_problem
QtUiPort.progress_window = _progress_window
