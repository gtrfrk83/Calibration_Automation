"""The manual-reading entry window for Qt (port of the removed Tk view manual_override_view_tk.py; same public function `ask_reading_window`).  The window only collects the typed
text; `submit(win, typed, clear_error)` (manual_override.ask_manual_reading.done) validates it and asks the short confirmation through the UiPort, so the Use /
Cancel logic of the prompt stays in the engine-side module.  Reached through ui_port.get_ui().view('manual_override_view').

Same texts, same order, same buttons as the Tk window: 'Point N of T  -  section', the description, the failure notice (with the STANDBY line) or the stored-reading
line, the DEMO line, 'WHAT DOES THE METER SHOW?', the entry with its unit, 'Acceptable reading: lo to hi unit', the error line, and Cancel (red when the automatic
reading failed) / 'Use this reading  (Enter)'.  Enter uses the reading; closing the window is Cancel (so is Esc)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit

from qtui.widgets import Banner, label, ModalDialog


def build(parent, p, total, vals, unit, reason, cancel_text, demo, stored, submit):
    """The dialog (not yet shown).  `.entry`, `.error`, `.ok`, `.cancel` are reachable for tests; `.value` is what `submit` returned as 'use' (None until then)."""
    dlg = ModalDialog(parent, f'Point {p["id"]} of {total} - enter the reading', width=560)
    dlg.title_label.hide()
    dlg.value = None
    dlg.add_text(f'Point {p["id"]} of {total}  -  {p.get("section_title", "")}', 'hint')
    dlg.add_text(p['description'], 'section')
    if reason:
        dlg.failure = Banner('The automatic reading failed: ' + reason, 'error')
        dlg.failure.text_label.setTextFormat(Qt.TextFormat.PlainText)
        dlg.body.addWidget(dlg.failure)
        dlg.add_text('The calibrator is in STANDBY. Read the meter display and type it here to carry on, or stop the run.', 'hint')
    elif stored:
        dlg.add_text(f'Stored reading: {stored}. Typing a value replaces it.', 'hint')
    if demo:
        dlg.demo_note = Banner('DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.', 'warn')
        dlg.demo_note.text_label.setTextFormat(Qt.TextFormat.PlainText)
        dlg.body.addWidget(dlg.demo_note)
    dlg.body.addWidget(label('WHAT DOES THE METER SHOW?', 'kvkey'))
    row = QHBoxLayout()
    dlg.entry = QLineEdit()
    dlg.entry.setMaximumWidth(220)
    dlg.entry.setAccessibleName('Reading')
    row.addWidget(dlg.entry)
    row.addWidget(label(unit, 'section'))
    row.addStretch(1)
    dlg.body.addLayout(row)
    dlg.add_text(f'Acceptable reading: {vals[0]} to {vals[1]} {unit}', 'hint')
    dlg.error = Banner('', 'error')                                     # the message of an invalid entry; hidden until there is one
    dlg.error.text_label.setTextFormat(Qt.TextFormat.PlainText)
    dlg.error.hide()
    dlg.body.addWidget(dlg.error)

    def clear_error():
        dlg.error.hide()
        dlg.error.set_text('')

    def use():
        what, got = submit(dlg, dlg.entry.text(), clear_error)
        if what == 'error':
            dlg.error.set_text(got)
            dlg.error.show()
            return False                                                # stays open
        if what == 'again':
            dlg.entry.setFocus()
            return False
        dlg.value = got
        return True
    dlg.cancel = dlg.add_button(cancel_text, role='danger' if reason else None, result='cancel', cancel=True)
    dlg.ok = dlg.add_button('Use this reading  (Enter)', role='primary', result='use', default=True, callback=use)
    dlg.initial_focus = dlg.entry
    return dlg


def ask_reading_window(parent, p, total, vals, unit, reason, cancel_text, demo, stored, submit):
    """Modal entry window.  Returns what `submit` returned as 'use' (the Entered), or None when cancelled / stopped."""
    dlg = build(parent, p, total, vals, unit, reason, cancel_text, demo, stored, submit)
    dlg.run()
    return dlg.value if dlg.result_key == 'use' else None
