"""User-built datasheet runtime (dsb_runtime.DsbApp): the Tk widgets of its window.  DsbApp is the handheld engine's App (window code in handheld_dmm_view_tk.py) with the
Datasheet Builder's run-time rules; what it adds to the window lives here, reached through `ui_port.ui.view('dsb_runtime_view')`:

    build_section_bar(self)        rule 12: the section-mode box next to the Show boxes (self.section_caption / section_mode_var / section_mode_box)
    build_standards(self, ...)     the 'Standards used by this datasheet' rows of the Connections drawer (the engine decides which; self.std_addr holds the variables)
    build_manual_drawer(self)      the 'Manual calibration' text of the drawer of a manual calibration, and the stock notice that does not apply removed
    retitle_manual(self)           'Performance Verification' -> 'Manual Calibration' in the window title and the banner
    attach_grid_entry(self)        typed readings straight into the test point grid (manual_grid.GridEntry)

Each takes the engine's DsbApp as `self`.  The Qt twin is dsb_runtime_view_qt.py; nothing here decides anything about a calibration.
"""
from __future__ import annotations

from tkinter import ttk

import ui_theme as ui
from ui_port import ui as port


def build_section_bar(self, labels):
    """The control of rule 12: in the bar above the test points, next to the Show boxes; acts on the section chosen in the sidebar."""
    try:
        bar = self.shell.section_picker.master
    except Exception:
        return False
    box = ttk.Frame(bar)
    box.pack(side='left', padx=(24, 0))
    self.section_caption = port.var('Section mode: choose a section on the left')
    ttk.Label(box, textvariable=self.section_caption, style='Muted.TLabel').pack(side='left', padx=(0, 6))
    self.section_mode_var = port.var('')
    self.section_mode_box = ttk.Combobox(box, textvariable=self.section_mode_var, values=list(labels), state='disabled', width=15)
    self.section_mode_box.pack(side='left')
    self.section_mode_box.bind('<<ComboboxSelected>>', lambda _e: self._on_mode_chosen())
    try:
        self.tree.tag_configure('skipped', foreground=ui.C['muted'])
    except Exception:
        pass
    return True


def build_standards(self, rows, counter, periods, help_text):
    """rows = [(model, label)]: one address entry each (self.std_addr[model] is its variable); `counter`: the counter timebase box; `periods`: the period box (>1 period)."""
    d = self.shell.drawer_body
    row = 20
    ttk.Separator(d).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    ttk.Label(d, text='Standards used by this datasheet', style='Bold.TLabel').grid(row=row + 1, column=0, columnspan=2, sticky='w')
    row += 2
    for model, label in rows:
        ttk.Label(d, text=label).grid(row=row, column=0, sticky='w', pady=4)
        ttk.Entry(d, textvariable=self.std_addr[model], width=34).grid(row=row, column=1, sticky='ew', padx=(10, 0), pady=4)
        row += 1
    if counter:
        ttk.Label(d, text='Counter timebase').grid(row=row, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.counter_ref, values=['EXT', 'INT'], state='readonly', width=9).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1
    if periods:
        ttk.Label(d, text='Specification period').grid(row=row, column=0, sticky='w', pady=4)
        box = ttk.Combobox(d, textvariable=self.period_var, values=list(periods), state='readonly', width=9)
        box.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        box.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
        row += 1
    ttk.Label(d, text=help_text, style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=row, column=0, columnspan=2, sticky='w', pady=(6, 0))


def build_manual_drawer(self, stock_start, heading, text):
    holder = self.shell.notice_holder
    for child in list(holder.winfo_children()):                 # the stock text ('the calibrator is programmed and enabled ...') does not apply
        label = getattr(child, 'label', None)
        try:
            if label is not None and str(label.cget('text')).startswith(stock_start):
                child.destroy()
        except Exception:
            pass
    d = self.shell.drawer_body
    ttk.Separator(d).grid(row=20, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    ttk.Label(d, text=heading, style='Bold.TLabel').grid(row=21, column=0, columnspan=2, sticky='w')
    ttk.Label(d, text=text, style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=22, column=0, columnspan=2, sticky='w', pady=(6, 0))


def retitle_manual(self, old, new, subtitle):
    """The stock banner says 'Performance Verification' and 'the calibrator output is set for you': neither is true of a manual calibration."""
    try:
        title = str(self.root.title())
        if ' ' + old in title:
            self.root.title(title.replace(' ' + old, ' ' + new))
    except Exception:
        pass

    def walk(w):
        for c in w.winfo_children():
            yield c
            yield from walk(c)
    try:
        for w in walk(self.root):
            text = str(w.cget('text')) if 'text' in w.keys() else ''
            if text.endswith('  -  ' + old):
                w.configure(text=text.replace(old, new))
        self.shell.subtitle.set(subtitle)
    except Exception:
        pass


def attach_grid_entry(self):
    import manual_grid
    self.grid_entry = manual_grid.GridEntry(self, self.tree)
