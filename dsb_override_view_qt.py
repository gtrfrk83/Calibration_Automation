"""Manual override entry window of the user-built datasheet runtime (dsb_override.ask_typed): the Qt dialog.  The port of the removed Tk view dsb_override_view_tk.py with the same function,
reached through `ui_port.ui.view('dsb_override_view')`.  The typed text is parsed and judged by dsb_override.parse_typed (no toolkit); the short 'Use this reading?'
confirmation is asked through the UI port, over this window.  Nothing here decides anything about a calibration."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit

import handheld_dmm as hh
from qtui import prompts, theme
from qtui.screens import common
from qtui.widgets import ModalDialog
from ui_port import ui as port

WIDTH = 560


class TypedDialog(ModalDialog):
    """`value` = the Typed the operator entered and confirmed, or None (cancelled / closed).  Enter = 'Use this reading'; the reason a typed text is refused shows in the
    window, which stays open; the confirmation question 'Use this reading?' (port.ask_yes_no, over this window) must be answered Yes."""

    def __init__(self, parent, p, total, parse, reason='', cancel_text='Cancel', demo=False, stored=''):
        super().__init__(common.qparent(parent), f'Point {p["n"]} of {total} - enter the reading', width=WIDTH + 2 * theme.M.xl)
        self.title_label.hide()
        self.p, self.parse, self.value = p, parse, None
        unit = p.get('display_unit') or ''
        self.body.addWidget(prompts.plain_label(f'Point {p["n"]} of {total}  -  {p["section"]}', 'hint'))
        self.heading_label = prompts.plain_label(hh.describe(p), 'h2')
        self.body.addWidget(self.heading_label)
        self.reason_label = self.stored_label = self.demo_label = None
        if reason:
            self.reason_label = common.ToneLabel('bad', 'The automatic reading failed: ' + reason)
            self.reason_label.setTextFormat(Qt.TextFormat.PlainText)
            self.body.addWidget(self.reason_label)
        elif stored:
            self.stored_label = prompts.plain_label(f'Stored reading: {stored}. Typing a value replaces it.', 'hint')
            self.body.addWidget(self.stored_label)
        if demo:
            self.demo_label = common.ToneLabel('warn', 'DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.')
            self.demo_label.setTextFormat(Qt.TextFormat.PlainText)
            self.body.addWidget(self.demo_label)
        self.body.addWidget(prompts.plain_label('TYPE THE READING', 'hint'))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.entry = QLineEdit()
        self.entry.setAccessibleName('Reading')
        self.entry.setFixedWidth(180)
        self.entry.textChanged.connect(lambda _t: self.error.setText(''))
        row.addWidget(self.entry)
        self.unit_label = prompts.plain_label(unit, 'section', wrap=False)
        row.addWidget(self.unit_label)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(prompts.plain_label(f'Acceptable reading: {p["low"]} to {p["high"]} {unit}', 'hint'))
        self.error = common.ToneLabel('bad')
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.error)
        self._button_row.takeAt(0)                                               # Cancel at the left edge, the primary button at the right (as in Tk)
        self.cancel_button = self.add_button(cancel_text, role='danger' if reason else None, result='cancel', cancel=True)
        self._button_row.addStretch(1)
        self.use_button = self.add_button('Use this reading  (Enter)', role='primary', result='use', default=True, callback=self._use)
        self.initial_focus = self.entry
        prompts.fit_dialog(self, WIDTH + 2 * theme.M.xl)

    def _use(self):
        try:
            typed = self.parse(self.p, self.entry.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        self.error.setText('')
        if not port.ask_yes_no('Use this reading?', f'Use {typed.shown} as the reading for point {self.p["n"]}?', parent=self):
            self.entry.setFocus()
            return False
        self.value = typed
        return True


def ask_typed(parent, p, total, parse, reason='', cancel_text='Cancel', demo=False, stored=''):
    """Modal entry window.  `parse(p, text)` -> Typed (ValueError: the reason, shown in the window).  Returns Typed, or None when cancelled / stopped."""
    def run():
        dlg = TypedDialog(parent, p, total, parse, reason, cancel_text, demo, stored)
        dlg.run()
        return dlg.value
    return common.on_ui(run)
