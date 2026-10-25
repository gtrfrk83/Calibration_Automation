"""The Stop / Continue window of surprise.py for Tk (moved unchanged from surprise._dialog; surprise.py imports no toolkit).  Reached through
ui_port.get_ui().view('surprise_view')."""
from __future__ import annotations

from surprise import KINDS


def dialog(root, title, s):
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    result = {'go': False}
    body = ttk.Frame(win, padding=12)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text=KINDS.get(s.kind, s.kind), font=('TkDefaultFont', 11, 'bold')).pack(anchor='w')
    ttk.Label(body, text='\n'.join(s.lines()), justify='left').pack(anchor='w', pady=(6, 6))
    if getattr(s, 'stop_only', False):
        ttk.Label(body, text='Continue is not offered here: the run cannot safely go on from this point.').pack(anchor='w', pady=(0, 6))
    ttk.Label(body, text=f'Last {len(s.log_tail)} log lines:').pack(anchor='w')
    box = tk.Text(body, width=100, height=12, wrap='none')
    box.insert('1.0', '\n'.join(s.log_tail))
    box.configure(state='disabled')
    box.pack(fill='both', expand=True)
    row = ttk.Frame(body)
    row.pack(anchor='e', pady=(8, 0))

    def pick(go):
        result['go'] = go
        win.destroy()

    stop = ttk.Button(row, text='Stop', command=lambda: pick(False))
    cont = None if getattr(s, 'stop_only', False) else ttk.Button(row, text='Continue', command=lambda: pick(True))
    stop.pack(side='left', padx=4)
    if cont is not None:
        cont.pack(side='left', padx=4)
    win.protocol('WM_DELETE_WINDOW', lambda: pick(False))      # closing the window is Stop
    win._surprise = dict(stop=stop, cont=cont, text=box)
    stop.focus_set()
    try:
        win.grab_set()
    except tk.TclError:
        pass
    root.wait_window(win)
    return result['go']
