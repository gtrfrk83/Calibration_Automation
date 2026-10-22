"""The two small dialogs of the Procedures list's 'Verified on hardware' buttons (the rules are in verified.py; this is only Tk wiring).

    verified_ui.ask_mark(parent, entry, status)    -> {'who', 'on_date', 'note', 'hardware'} or None (cancelled)
    verified_ui.ask_unlock(parent, entry, status)  -> {'who', 'reason'} or None

A wrong entry is explained inside the dialog (red line) and the dialog stays open.  The person's name is remembered for next time.
These windows have not been viewed on a screen; tests only build them under the tkinter stub.
"""
import tkinter as tk
from tkinter import ttk

import ui_theme as ui
import verified


def _remembered():
    return ui.Settings('verified')


def _frame(parent, title, heading, lead):
    win = ui.dialog(parent, title)
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(22, 18, 22, 16))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=heading, style='Bold.TLabel', wraplength=ui.px(460), justify='left').pack(anchor='w')
    ttk.Label(outer, text=lead, style='Muted.TLabel', wraplength=ui.px(460), justify='left').pack(anchor='w', pady=(2, 10))
    return win, outer


def _finish(win, outer, parent, submit, ok_text, error_var):
    ttk.Label(outer, textvariable=error_var, foreground=ui.C['bad'], wraplength=ui.px(460), justify='left').pack(anchor='w', pady=(8, 0))
    bar = ttk.Frame(outer)
    bar.pack(fill='x', pady=(12, 0))
    ttk.Button(bar, text=ok_text, style='Accent.TButton', command=lambda: submit(True)).pack(side='right')
    ttk.Button(bar, text='Cancel', command=lambda: submit(False)).pack(side='right', padx=(0, 8))
    win.bind('<Return>', lambda _e: submit(True))
    ui.center_on(win, parent)
    parent.wait_window(win)


def ask_mark(parent, entry, status, today=None):
    store = _remembered()
    again = status.kind != 'none'
    win, outer = _frame(parent, 'Mark verified on hardware',
                        f'{"Verify again" if again else "Mark verified on hardware"}: {entry.name or entry.proc_key}',
                        'Only after this procedure has run correctly on the actual instruments. It is then LOCKED: it cannot be edited '
                        '(procedure changes, the in-run editor, developer-mode edits, the Datasheet Builder) until someone unlocks it with a '
                        'reason. Running it is not affected. A fingerprint of its files and settings is saved so a later change shows up here.')
    vars_ = {'who': tk.StringVar(value=store.get('who', '') or verified.default_who()),
             'on_date': tk.StringVar(value=(today or verified.date.today()).isoformat()),
             'instrument': tk.StringVar(), 'calibrator': tk.StringVar(), 'note': tk.StringVar()}
    grid = ttk.Frame(outer)
    grid.pack(fill='x')
    rows = (('who', 'Verified by *', 28, ''), ('on_date', 'Date', 14, 'year-month-day (today if left as is)'),
            ('instrument', 'Instrument / serial', 36, 'optional, the unit it was run on'), ('calibrator', 'Calibrator / standard', 36, 'optional'),
            ('note', 'Note', 48, 'optional'))
    for r, (key, label, width, hint) in enumerate(rows):
        ttk.Label(grid, text=label).grid(row=r, column=0, sticky='w', pady=3)
        ttk.Entry(grid, textvariable=vars_[key], width=width).grid(row=r, column=1, padx=(10, 8), pady=3, sticky='w')
        ttk.Label(grid, text=hint, style='Muted.TLabel').grid(row=r, column=2, sticky='w')
    error, result = tk.StringVar(), {'v': None}

    def submit(ok):
        if ok:
            clean, problems = verified.check_verify_form(vars_['who'].get(), vars_['on_date'].get(), vars_['note'].get(),
                                                         verified.compose_hardware(vars_['instrument'].get(), vars_['calibrator'].get()), today)
            if problems:
                error.set(' '.join(problems))
                return
            store.set('who', clean['who'])
            store.save()
            result['v'] = clean
        win.destroy()
    _finish(win, outer, parent, submit, 'Mark verified and lock', error)
    return result['v']


def ask_unlock(parent, entry, status):
    store = _remembered()
    win, outer = _frame(parent, 'Unlock for editing', f'Unlock for editing: {entry.name or entry.proc_key}',
                        'Anyone can unlock, but it is recorded: who, when and why. While it is unlocked it can be edited and its '
                        'verification no longer protects it. Afterwards, press "Lock again" if nothing changed, or verify it on the hardware '
                        'again. Changes saved before it was locked stay as they are.')
    who, reason = tk.StringVar(value=store.get('who', '') or verified.default_who()), tk.StringVar()
    grid = ttk.Frame(outer)
    grid.pack(fill='x')
    for r, (label, var, width) in enumerate((('Your name *', who, 28), ('Reason *', reason, 56))):
        ttk.Label(grid, text=label).grid(row=r, column=0, sticky='w', pady=3)
        ttk.Entry(grid, textvariable=var, width=width).grid(row=r, column=1, padx=(10, 0), pady=3, sticky='w')
    error, result = tk.StringVar(), {'v': None}

    def submit(ok):
        if ok:
            clean, problems = verified.check_unlock_form(who.get(), reason.get())
            if problems:
                error.set(' '.join(problems))
                return
            store.set('who', clean['who'])
            store.save()
            result['v'] = clean
        win.destroy()
    _finish(win, outer, parent, submit, 'Unlock', error)
    return result['v']
