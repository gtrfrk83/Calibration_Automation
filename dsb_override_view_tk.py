"""Manual override entry window of the user-built datasheet runtime (dsb_override.ask_typed): the Tk widgets.  Reached through
`ui_port.ui.view('dsb_override_view')`; the Qt twin is dsb_override_view_qt.py.  The typed text is parsed and judged by dsb_override.parse_typed (no toolkit); the short
'Use this reading?' confirmation is asked through the UI port, over this window.  Nothing here decides anything about a calibration."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import handheld_dmm as hh
import ui_theme as ui
from ui_port import ui as port


def ask_typed(parent, p, total, parse, reason='', cancel_text='Cancel', demo=False, stored=''):
    """Modal entry window.  `parse(p, text)` -> Typed (ValueError: the reason, shown in the window).  Returns Typed, or None when cancelled / stopped.
    The short confirmation is asked after the typed value is valid."""
    result = {'v': None}
    win = ui.dialog(parent, f'Point {p["n"]} of {total} - enter the reading')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(ui.px(22), ui.px(16), ui.px(22), ui.px(14)))
    outer.pack(fill='both', expand=True)
    wrap = ui.px(520)
    unit = p.get('display_unit') or ''
    ttk.Label(outer, text=f'Point {p["n"]} of {total}  -  {p["section"]}', style='Small.TLabel').pack(anchor='w')
    ttk.Label(outer, text=hh.describe(p), style='Section.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(2, 8))
    if reason:
        ttk.Label(outer, text='The automatic reading failed: ' + reason, style='Bold.TLabel', wraplength=wrap, justify='left',
                  foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(0, 8))
    elif stored:
        ttk.Label(outer, text=f'Stored reading: {stored}. Typing a value replaces it.', style='Small.TLabel', wraplength=wrap, justify='left').pack(anchor='w', pady=(0, 8))
    if demo:
        ttk.Label(outer, text='DEMO: the value you type is recorded as demo data. Nothing here is calibration evidence.', style='Small.TLabel',
                  wraplength=wrap, justify='left', foreground=ui.C.get('warn', '#B26A00')).pack(anchor='w', pady=(0, 8))
    ttk.Label(outer, text='TYPE THE READING', style='MetricCap.TLabel').pack(anchor='w')
    row = ttk.Frame(outer)
    row.pack(fill='x', pady=(4, 0))
    text = tk.StringVar()
    entry = ttk.Entry(row, textvariable=text, width=16)
    entry.pack(side='left')
    ttk.Label(row, text=unit, style='Bold.TLabel').pack(side='left', padx=(10, 0))
    ttk.Label(outer, text=f'Acceptable reading: {p["low"]} to {p["high"]} {unit}', style='Small.TLabel').pack(anchor='w', pady=(6, 0))
    error = tk.StringVar()
    ttk.Label(outer, textvariable=error, wraplength=wrap, justify='left', foreground=ui.C.get('bad', '#B3261E')).pack(anchor='w', pady=(6, 0))

    def done(use):
        if not use:
            win.destroy()
            return
        try:
            typed = parse(p, text.get())
        except ValueError as exc:
            error.set(str(exc))
            return
        error.set('')
        if not port.ask_yes_no('Use this reading?', f'Use {typed.shown} as the reading for point {p["n"]}?', parent=win):
            entry.focus_set()
            return
        result['v'] = typed
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


