"""iFlex window option (iflex_option.App): the Tk widgets of the 'iFlex probe supplied' check boxes.

Moved out of iflex_option.py unchanged: the include bar above the results table, the per-meter rows of the Connections drawer and the label refresh.  Every function takes the
engine's App as `self` and keeps its widgets and variables as attributes of it (`_include_vars`, `_include_labels`, `_inc_rows`, ...).  The engine reaches this module through
`ui_port.ui.view('iflex_option_view')` (iflex_option_view_tk under Tk; a Qt port provides iflex_option_view_qt with the same functions).  Nothing here decides anything about a calibration.
"""
import tkinter as tk
from tkinter import ttk

import ui_theme as ui


def build_include_bar(self):
    defs = self.include_defs()
    self._include_vars, self._include_labels = {}, {}
    bar = ttk.Frame(self.shell.content)
    slaves = self.shell.content.pack_slaves()
    bar.pack(side='top', fill='x', pady=(0, 6), **({'before': slaves[0]} if slaves else {}))
    self.include_bar = bar
    for d in defs:
        var = tk.BooleanVar(self.root, value=self._include.get(d['id'], True))
        self._include_vars[d['id']] = var
        ttk.Checkbutton(bar, text=d['label'], variable=var, command=lambda k=d['id']: self._on_include_click(k)).pack(side='left')
        label = ttk.Label(bar, text=self.include_text(d['id'], short=True), style='Muted.TLabel')
        label.pack(side='left', padx=(12, 0))
        self._include_labels[d['id']] = label


def build_include_rows(self, d, nxt):
    """The row holder of the Connections drawer, then its per-meter rows (the engine then builds the rows and returns nxt + 1)."""
    self._inc_rows = ttk.Frame(d)
    self._inc_rows.grid(row=nxt, column=0, columnspan=2, sticky='ew', pady=(6, 0))
    self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, None


def rebuild_include_rows(self):
    """Update the per-meter boxes in place when the meters are unchanged, else rebuild them."""
    box = getattr(self, '_inc_rows', None)
    if box is None:
        return
    meters, defs = list(self.queue.meters), self.include_defs()
    sig = tuple(m.asset for m in meters)
    if defs and meters and sig == getattr(self, '_inc_rows_sig', None):          # same meters: update the boxes in place (the box being clicked stays)
        for m in meters:
            inc = self._ensure_meter(m)
            self._inc_row_vars[m.asset].set(bool(inc.get(defs[0]['id'], True)))
            self._inc_row_notes[m.asset].configure(text=self._meter_include_note(m, defs[0]))
        return
    for w in list(box.winfo_children()):
        w.destroy()
    self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, sig
    if not meters or not defs:
        return
    d = defs[0]
    ttk.Label(box, text=f'{self._inc_label(None)} probe, per meter', style='Bold.TLabel').grid(row=0, column=0, sticky='w')
    box.columnconfigure(0, weight=1)
    for r, m in enumerate(meters):
        inc = self._ensure_meter(m)
        var = tk.BooleanVar(self.root, value=bool(inc.get(d['id'], True)))
        self._inc_row_vars[m.asset] = var
        ttk.Checkbutton(box, text=f'{m.asset}: {self._inc_label(None)} supplied', variable=var,
                        command=lambda m=m, v=var: self._on_meter_include_click(m, v)).grid(row=1 + 2 * r, column=0, sticky='w', pady=(4, 0))
        note = ttk.Label(box, text=self._meter_include_note(m, d), style='Muted.TLabel', wraplength=ui.px(320), justify='left')
        note.grid(row=2 + 2 * r, column=0, sticky='w', padx=(24, 0))
        self._inc_row_notes[m.asset] = note


def set_include_label(self, key, text):
    self._include_labels[key].configure(text=text)
