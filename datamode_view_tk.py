"""The As Found / As Left toggle, its notice and the table heading for Tk (moved unchanged from datamode.DataModeMixin; datamode.py imports no toolkit).
Functions whose first parameter is the App (`self`), reached through ui_port.get_ui().view('datamode_view')."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui
from datamode import FOUND, LEFT, LABEL, HINT_FOUND


def build_mode_bar(self, parent, **pack):
    """The 'Collecting data' toggle (As Found | As Left).  Returns the frame; it is packed with **pack (default: fill x)."""
    self.mode_var = tk.StringVar(value=self._mode)
    bar = ttk.Frame(parent)
    options = {'fill': 'x', 'pady': (8, 0)}
    options.update(pack)
    bar.pack(**options)
    row = ttk.Frame(bar)
    row.pack(fill='x')
    ttk.Label(row, text='Collecting data:', style='Bold.TLabel').pack(side='left', padx=(0, 10))
    self.mode_buttons = []
    for mode in (FOUND, LEFT):
        b = ttk.Radiobutton(row, text=LABEL[mode], value=mode, variable=self.mode_var, command=self._mode_clicked)
        b.pack(side='left', padx=(0, 14))
        self.mode_buttons.append(b)
    self.mode_hint = tk.StringVar(value=HINT_FOUND)
    hint = ttk.Label(row, textvariable=self.mode_hint, style='Small.TLabel', wraplength=ui.px(560), justify='left')
    hint.pack(side='left', fill='x', expand=True)
    def fit_hint(_e=None):                              # wrap to the room left of the toggle (its x position does not depend on its own width)
        room = row.winfo_width() - (hint.winfo_rootx() - row.winfo_rootx()) - ui.px(12)
        room = max(ui.px(160), room)
        if int(float(str(hint.cget('wraplength')))) != room:
            hint.configure(wraplength=room)
    row.bind('<Configure>', lambda e: row.after_idle(fit_hint), add='+')
    self.mode_notice_holder = ttk.Frame(bar)
    self.mode_notice_holder.pack(fill='x')
    self.mode_notice = None
    return bar


def build_mode_segment(self, parent, notice_holder=None):
    """The redesigned toggle: a compact  Collecting [ As Found | As Left ]  switch for the shell's top strip.  It keeps the same
    attributes as build_mode_bar (mode_var, mode_buttons, mode_hint, mode_notice_holder), so everything else works unchanged;
    the hint becomes a tooltip and the As Left warning becomes a one-line amber notice under the strip."""
    self.mode_var = tk.StringVar(value=self._mode)
    box = ttk.Frame(parent)
    box.pack(side='left', padx=(0, 14))
    ttk.Label(box, text='Collecting').pack(side='left', padx=(0, 8))
    self.mode_buttons = []
    for mode, style in ((FOUND, 'Seg.Toolbutton'), (LEFT, 'SegLeft.Toolbutton')):
        b = ttk.Radiobutton(box, text=LABEL[mode], value=mode, variable=self.mode_var, command=self._mode_clicked, style=style)
        b.pack(side='left')
        self.mode_buttons.append(b)
    self.mode_hint = tk.StringVar(value=HINT_FOUND)
    ui.Tooltip(box, lambda: self.mode_hint.get())
    self.mode_notice_holder = notice_holder if notice_holder is not None else ttk.Frame(parent)
    self.mode_notice = None
    self.mode_notice_short = True
    return box


def show_mode_notice(self):
    holder = getattr(self, 'mode_notice_holder', None)
    if holder is None:
        return
    if self.mode_notice is not None:
        self.mode_notice.destroy()
        self.mode_notice = None
    if self._mode == LEFT:
        short = getattr(self, 'mode_notice_short', False)
        self.mode_notice = ui.Notice(holder, ('Collecting AS LEFT: readings are saved beside the As Found values, which stay locked. Use after an adjustment only.' if short else
                                              'Readings taken now are saved as AS LEFT. Use this only after the instrument was adjusted. '
                                              'Switch back to As Found to review the original readings.'), 'warn', title=None if short else 'Collecting As Left data')
        self.mode_notice.pack(fill='x', pady=(6, 0))


def relabel_reading_column(self):
    tree = getattr(self, 'tree', None)
    if tree is None:
        return
    try:
        for col in ('reading', 'found', 'entered'):
            if col in tree['columns']:
                tree.heading(col, text=('As Left reading' if self._mode == LEFT else 'Reading'))
                break
    except tk.TclError:
        pass
