"""The pre-run list of unverified commands (dsb_prerun.show_list): the Qt dialog.  The twin of dsb_prerun_view_tk.py with the same function, reached through
`ui_port.ui.view('dsb_prerun_view')`.  dsb_prerun works out what is listed; this only shows it and returns the operator's choice.  'Accept and run' is not the default
button: Cancel has the focus and Enter.  Nothing here decides anything about a calibration."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

from qtui import prompts, theme
from qtui.screens import common
from qtui.widgets import ModalDialog

TITLE = 'Unverified commands: accept before a real run'
WIDTH = 640


class PreRunDialog(ModalDialog):
    """`go` is True only after 'Accept and run'; Cancel, Esc and the window button leave it False (nothing is opened)."""

    def __init__(self, parent, intro, body_text):
        super().__init__(common.qparent(parent), TITLE, width=WIDTH + 2 * theme.M.xl)
        self.title_label.hide()
        self.go = False
        self.body.addWidget(prompts.plain_label('Commands to accept', 'h2'))
        self.intro_label = prompts.plain_label(intro, 'sub')
        self.body.addWidget(self.intro_label)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName('Commands to accept')
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont(theme.mono_family())
        font.setPixelSize(theme.M.font_base)
        self.text.setFont(font)
        self.text.setMinimumHeight(260)
        self.text.setPlainText(body_text)
        self.body.addWidget(self.text, 1)
        self.accept_button = self.add_button('Accept and run', role='primary', result='accept', callback=self._accept)
        self.cancel_button = self.add_button('Cancel (nothing is opened)', result='cancel', cancel=True, default=True)
        self.initial_focus = self.cancel_button
        prompts.fit_dialog(self, WIDTH + 2 * theme.M.xl)

    def _accept(self):
        self.go = True


def show_list(root, intro, body_text):
    """The modal list: scrolling text, 'Accept and run' (not the default) and 'Cancel'.  Returns True when accepted."""
    def run():
        dlg = PreRunDialog(root, intro, body_text)
        dlg.run()
        return dlg.go
    return common.on_ui(run)
