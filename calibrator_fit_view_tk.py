"""The calibrator-model note under the picker for Tk (moved unchanged from calibrator_fit.attach_note; calibrator_fit.py imports no toolkit)."""
from __future__ import annotations

from tkinter import ttk


def attach_note(parent, offer, ui, widgets=(), row=None, columnspan=2, wrap=340):
    """A muted label saying whether the model is offered and why not, packed under the picker inside `parent` (or gridded at `row` of a grid); the full
    explanation is the tooltip of the label and of `widgets` (the picker itself).  Returns the label."""
    lab = ttk.Label(parent, text=offer.text, style='Muted.TLabel', wraplength=ui.px(wrap), justify='left')
    if row is None:
        lab.pack(fill='x', pady=(4, 0))
    else:
        lab.grid(row=row, column=0, columnspan=columnspan, sticky='w', pady=(0, 6))
    for w in (lab, *widgets):
        ui.Tooltip(w, offer.tooltip)
    return lab
