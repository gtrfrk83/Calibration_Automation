"""The calibrator-model note under the picker for Qt (twin of calibrator_fit_view_tk.py; same `attach_note` signature).  Reached through
ui_port.get_ui().view('calibrator_fit_view')."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLayout

from qtui.widgets import label


def attach_note(parent, offer, ui=None, widgets=(), row=None, columnspan=2, wrap=340):
    """A muted label saying whether the model is offered and why not, added under the picker inside `parent` (a QLayout, or a widget: its layout) or placed at
    `row` of a grid (`parent` a QGridLayout, or a widget with one); the full explanation is the tooltip of the label and of `widgets` (the picker itself).
    `ui` is the Tk theme module the Tk view needs for px(); the Qt twin takes it for the same call signature and ignores it (`wrap` is in device-independent
    pixels).  Returns the label."""
    lab = label(offer.text, 'sub', wrap=True)
    lab.setMaximumWidth(wrap)
    lay = parent if isinstance(parent, QLayout) else parent.layout()
    if row is None:
        lab.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(lab)
    else:
        lab.setContentsMargins(0, 0, 0, 6)
        if not isinstance(lay, QGridLayout):
            raise TypeError('attach_note(row=...) needs a grid layout')
        lay.addWidget(lab, row, 0, 1, columnspan)
    return lab                                  # no hover box: the line says what matters
