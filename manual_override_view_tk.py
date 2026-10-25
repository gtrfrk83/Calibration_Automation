"""The manual-reading entry window for Tk (moved from manual_override.ask_manual_reading; manual_override.py imports no toolkit).  The window only
collects the typed text; `submit(win, typed, clear_error)` (manual_override.ask_manual_reading.done) validates it and asks the short confirmation, so the Use / Cancel logic of the prompt stays in the
engine-side module.  Reached through ui_port.get_ui().view('manual_override_view')."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui


def ask_reading_window(parent, p, total, vals, unit, reason, cancel_text, demo, stored, submit):
    """Modal entry window.  Returns what `submit` returned as 'use' (the Entered), or None when cancelled / stopped."""
    result = {'v': None}
    win = ui.dialog(parent, f'Point {p["id"]} of {total} - enter the reading')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    wrap = ui.px(520)
    ttk.Label(outer, text=f'Point {p["id"]} of {total}  -  {p.get("section_title", "")}', style='Small.TLabel').pack(anchor='w')
    ttk.Label(outer, text=p['description'], style='Section.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(2, 8))
    if reason:
        ttk.Label(outer, text='The automatic reading failed: ' + reason, style='Bold.TLabel', wraplength=wrap, justify='left',
                  foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(0, 8))
        ttk.Label(outer, text='The calibrator is in STANDBY. Read the meter display and type it here to carry on, or stop the run.',
                  style='Small.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(0, 8))
    elif stored:
        ttk.Label(outer, text=f'Stored reading: {stored}. Typing a value replaces it.', style='Small.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(0, 8))
    if demo:
        ttk.Label(outer, text='DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.', style='Small.TLabel',
                  wraplength=wrap, justify='left', foreground=ui.C.get('warn', '#B26A00')).pack(anchor='w', pady=(0, 8))
    ttk.Label(outer, text='WHAT DOES THE METER SHOW?', style='MetricCap.TLabel').pack(anchor='w')
    row = ttk.Frame(outer)
    row.pack(fill='x', pady=(4, 0))
    text = tk.StringVar()
    entry = ttk.Entry(row, textvariable=text, width=16)
    entry.pack(side='left')
    ttk.Label(row, text=unit, style='Bold.TLabel').pack(side='left', padx=(10, 0))
    ttk.Label(outer, text=f'Acceptable reading: {vals[0]} to {vals[1]} {unit}', style='Small.TLabel').pack(anchor='w', pady=(6, 0))
    error = tk.StringVar()
    ttk.Label(outer, textvariable=error, wraplength=wrap, justify='left', foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(6, 0))

    def done(use):
        if not use:
            win.destroy()
            return
        what, got = submit(win, text.get(), lambda: error.set(''))
        if what == 'error':
            error.set(got)
            return
        if what == 'again':
            entry.focus_set()
            return
        result['v'] = got
        win.destroy()
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(14, 0))
    ok = ttk.Button(bar, text='Use this reading  (Enter)', style='Accent.TButton', command=lambda: done(True))
    ok.pack(side='right')
    ttk.Button(bar, text=cancel_text, style='Danger.TButton' if reason else 'TButton', command=lambda: done(False)).pack(side='left')
    win.bind('<Return>', lambda _e: done(True))
    win.protocol('WM_DELETE_WINDOW', lambda: done(False))
    ui.center_on(win, parent.winfo_toplevel())
    entry.focus_set()
    win.wait_window()
    return result['v']


