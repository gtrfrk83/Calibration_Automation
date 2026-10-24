"""The pre-run list of unverified commands (dsb_prerun.show_list): the Tk window.  Reached through `ui_port.ui.view('dsb_prerun_view')`; the Qt twin is
dsb_prerun_view_qt.py.  dsb_prerun works out what is listed (intro text, the lines shown); this only shows it and returns the operator's choice.
Nothing here decides anything about a calibration."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui


def show_list(root, intro, body_text):
    """The modal list: scrolling text, 'Accept and run' (not the default) and 'Cancel'.  Returns True when accepted."""
    result = {'ok': False}
    win = ui.dialog(root, 'Unverified commands: accept before a real run')
    body = ttk.Frame(win, padding=16)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Commands to accept', style='Header.TLabel').pack(anchor='w')
    ttk.Label(body, text=intro, style='Muted.TLabel', wraplength=ui.px(560), justify='left').pack(anchor='w', pady=(4, 8))
    box = ttk.Frame(body)
    box.pack(fill='both', expand=True)
    text = tk.Text(box, width=78, height=14, wrap='word', background=ui.C['card'], foreground=ui.C['text'],
                   relief='flat', highlightthickness=1, highlightbackground=ui.C['border_strong'], padx=8, pady=6)
    sb = ttk.Scrollbar(box, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    text.pack(side='left', fill='both', expand=True)
    text.insert('1.0', body_text)
    text.configure(state='disabled')
    bar = ttk.Frame(body)
    bar.pack(fill='x', pady=(10, 0))

    def done(ok):
        result['ok'] = ok
        win.destroy()
    cancel = ttk.Button(bar, text='Cancel (nothing is opened)', command=lambda: done(False))
    cancel.pack(side='right')
    ttk.Button(bar, text='Accept and run', command=lambda: done(True)).pack(side='right', padx=(0, 8))
    win.protocol('WM_DELETE_WINDOW', lambda: done(False))
    cancel.focus_set()
    ui.center_on(win, root)
    root.wait_window(win)
    return result['ok']


