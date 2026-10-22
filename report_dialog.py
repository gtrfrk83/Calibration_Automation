"""Small dialog collecting the report's optional details (technician, environment, standards used).
Remembers the last entries per user so the technician normally just presses Save."""
import tkinter as tk
from tkinter import ttk

import report_pdf
import ui_theme as ui


def ask_details(parent, procedure=''):
    """Returns a dict for report_pdf.write_calibration_pdf(details=...), or None if cancelled."""
    store = ui.Settings('report_details')
    win = ui.dialog(parent, 'Report details')
    win.resizable(False, False)
    outer = ttk.Frame(win, padding=(22, 18, 22, 16)); outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='Report details', style='Bold.TLabel').pack(anchor='w')
    ttk.Label(outer, text='Printed on the report. Everything is optional; entries are remembered for next time.', style='Muted.TLabel').pack(anchor='w', pady=(2, 10))
    vars_ = {k: tk.StringVar(value=store.get(k, '')) for k in ('technician', 'temperature', 'humidity')}
    grid = ttk.Frame(outer); grid.pack(fill='x')
    for r, (key, label, hint) in enumerate((('technician', 'Technician', ''), ('temperature', 'Temperature', 'e.g. 23.1 °C'), ('humidity', 'Humidity', 'e.g. 45 %RH'))):
        ttk.Label(grid, text=label).grid(row=r, column=0, sticky='w', pady=3)
        ttk.Entry(grid, textvariable=vars_[key], width=26).grid(row=r, column=1, padx=(10, 8), pady=3)
        ttk.Label(grid, text=hint, style='Muted.TLabel').grid(row=r, column=2, sticky='w')
    ttk.Label(outer, text='Standards used', style='Bold.TLabel').pack(anchor='w', pady=(12, 2))
    saved = store.get('standards', []) or []
    std_rows = []
    sg = ttk.Frame(outer); sg.pack(fill='x')
    for c, h in enumerate(('Standard (model)', 'Serial number', 'Calibration due')):
        ttk.Label(sg, text=h, style='Muted.TLabel').grid(row=0, column=c, sticky='w', padx=(0, 8))
    for r in range(1, 4):
        prior = saved[r - 1] if r - 1 < len(saved) else {}
        trio = [tk.StringVar(value=prior.get(k, '')) for k in ('description', 'serial', 'due')]
        std_rows.append(trio)
        for c, (v, w) in enumerate(zip(trio, (28, 16, 14))):
            ttk.Entry(sg, textvariable=v, width=w).grid(row=r, column=c, padx=(0, 8), pady=2, sticky='w')
    remembered = report_pdf.remembered_show_tar_tur()                        # first run: both off
    tar_var, tur_var = tk.BooleanVar(value=remembered.tar), tk.BooleanVar(value=remembered.tur)
    ttk.Checkbutton(outer, text='Show TAR on the data file', variable=tar_var).pack(anchor='w', pady=(12, 0))
    ttk.Checkbutton(outer, text='Show TUR on the data file', variable=tur_var).pack(anchor='w')
    result = {'ok': None}

    def done(ok):
        if ok:
            details = {k: v.get().strip() for k, v in vars_.items()}
            details['standards'] = [dict(zip(('description', 'serial', 'due'), (x.get().strip() for x in trio))) for trio in std_rows]
            details['procedure'] = procedure
            details['show_tar'], details['show_tur'] = bool(tar_var.get()), bool(tur_var.get())
            details['show_tar_tur'] = report_pdf.TarTur(details['show_tar'], details['show_tur'])      # truthy if either is on
            report_pdf.remember_show_tar_tur(details['show_tar_tur'])
            for k in ('technician', 'temperature', 'humidity'):
                store.set(k, details[k])
            store.set('standards', details['standards']); store.save()
            result['ok'] = details
        win.destroy()

    bar = ttk.Frame(outer); bar.pack(fill='x', pady=(14, 0))
    ttk.Button(bar, text='Create report', style='Accent.TButton', command=lambda: done(True)).pack(side='right')
    ttk.Button(bar, text='Cancel', command=lambda: done(False)).pack(side='right', padx=(0, 8))
    win.bind('<Return>', lambda _e: done(True))
    win.update_idletasks()
    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        y = parent.winfo_rooty() + max(20, (parent.winfo_height() - win.winfo_height()) // 3)
        win.geometry(f'+{max(x, 0)}+{max(y, 0)}')
    except tk.TclError:
        pass
    parent.wait_window(win)
    return result['ok']
