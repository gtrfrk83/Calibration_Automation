"""Datasheet Builder, rule 2 at run time: the PRE-RUN LIST.  A real run of a user-built datasheet may use only commands that have a manual page reference and a
verified flag; every other command it would send is listed here and the operator must accept the list before any real instrument is opened.

    dsb_prerun.accepted(root, spec, accepted_fingerprint='', ask=None)   -> True to go on, False to stop (nothing was opened)
    dsb_prerun.pre_run(spec)                                              -> dict(lines, count, points, fingerprint, dry, error)

The list is worked out by the same dry run the Builder's Sheet check uses (datasheet_builder_rules: the real driver code on the simulated bench), from the
datasheet the runnable spec carries.  `accepted_fingerprint` is the fingerprint of the list the Builder already showed and the operator accepted ('Run on real
instruments' question): the same list is not asked twice.  When the list cannot be worked out the operator is asked that, plainly (fail closed).  Demo runs
never come here (no real instrument is opened).  Nothing in the engine, the drivers, a limit or a safety prompt is changed by this module.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ui_theme as ui

MAX_SHOWN = 60


def pre_run(spec):
    """The unverified commands of the datasheet in `spec` (a runnable user-built spec).  Never raises: {'error': text} when it cannot be worked out."""
    try:
        import datasheet_builder_rules as rules
        import datasheet_builder_specs as dsp
        if (spec.get('options') or {}).get('manual_entry'):
            return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error='')
        ds = dsp.datasheet_from_spec(spec)
        if ds is None:
            return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error='the spec carries no datasheet to check')
        chk = rules.check(ds, (spec.get('dsb') or {}).get('period'))
        return dict(lines=chk.pre_run_lines(), count=len(chk.unverified), points=len(chk.unverified_points()), fingerprint=chk.fingerprint(), dry=chk.dry.available, error='')
    except Exception as exc:
        return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error=f'{type(exc).__name__}: {exc}')


def intro(info):
    if info.get('intro'):
        return info['intro']
    n, pts = info['count'], info['points']
    return (f'This run would send {n} command{"s" * (n != 1)} that {"are" if n != 1 else "is"} not verified on hardware or not tied to a manual page '
            f'({pts} point{"s" * (pts != 1)} use them). Real instruments run only after you accept the list.')


def show_list(root, info):
    """The modal list: scrolling text, 'Accept and run' (not the default) and 'Cancel'.  Returns True when accepted."""
    result = {'ok': False}
    win = ui.dialog(root, 'Unverified commands: accept before a real run')
    body = ttk.Frame(win, padding=16)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='Commands to accept', style='Header.TLabel').pack(anchor='w')
    ttk.Label(body, text=intro(info), style='Muted.TLabel', wraplength=ui.px(560), justify='left').pack(anchor='w', pady=(4, 8))
    box = ttk.Frame(body)
    box.pack(fill='both', expand=True)
    text = tk.Text(box, width=78, height=14, wrap='word', background=ui.C['card'], foreground=ui.C['text'],
                   relief='flat', highlightthickness=1, highlightbackground=ui.C['border_strong'], padx=8, pady=6)
    sb = ttk.Scrollbar(box, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    text.pack(side='left', fill='both', expand=True)
    shown = info['lines'][:MAX_SHOWN]
    text.insert('1.0', '\n'.join(f'  {l}' for l in shown) + (f'\n  ... and {len(info["lines"]) - MAX_SHOWN} more' if len(info['lines']) > MAX_SHOWN else ''))
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


def accepted(root, spec, accepted_fingerprint='', ask=None):
    """True when the run may go on.  `ask(info)` replaces the dialog (tests)."""
    info = pre_run(spec)
    if info['error']:
        info = dict(info, lines=[], count=0, points=0, intro=f'The list of unverified commands could not be worked out ({info["error"]}). '
                    'Real instruments run only after you accept that the commands are unchecked.')
        return bool((ask or (lambda i: show_list(root, i)))(info))
    if not info['count']:
        return True
    if accepted_fingerprint and accepted_fingerprint == info['fingerprint']:
        return True
    return bool((ask or (lambda i: show_list(root, i)))(info))
