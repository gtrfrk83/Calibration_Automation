"""The run queue's windows for Tk.  The window code itself is run_queue_ui.py (a Tk-only module: set-up window, progress window, the one-window reading
entry that handheld_dmm imports); this module is the thin seam `ui_port.get_ui().view('run_queue_view')` the toolkit-free engine (run_queue_engine.py) uses, plus
the 'Several meters' block of the Connections drawer (moved unchanged from QueueMixin.build_queue_drawer).  Everything resolves run_queue_ui at call time, so a test
that patches run_queue_ui.ask_queue_setup still takes effect."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui


def ask_queue_setup(*args, **kwargs):
    import run_queue_ui
    return run_queue_ui.ask_queue_setup(*args, **kwargs)


def queue_progress(*args, **kwargs):
    import run_queue_ui
    return run_queue_ui.QueueProgress(*args, **kwargs)


def build_queue_drawer(self, d, row):
    """The 'Run queue' area of the Connections drawer (rows row .. row+2).  Returns the next free row."""
    ttk.Separator(d).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    ttk.Label(d, text='Several meters', style='Bold.TLabel').grid(row=row + 1, column=0, sticky='w')
    self.btn_queue = ttk.Button(d, text='Run queue...', command=self.open_queue_setup)
    self.btn_queue.grid(row=row + 1, column=1, sticky='w', padx=(10, 0))
    self.queue_label = tk.StringVar(value='No queue: one meter, as usual.')
    ttk.Label(d, textvariable=self.queue_label, style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=row + 2, column=0, columnspan=2, sticky='w', pady=(4, 0))
    return row + 3
