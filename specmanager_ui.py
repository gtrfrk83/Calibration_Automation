"""Specification Manager tab: the standards (calibrators) whose published specifications feed the uncertainty budgets, and the EMU check."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import specmanager as sm
import ui_theme as ui
import uncertainty
import uncertainty_budget as ub

KINDS = ['', 'DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'COND', 'FREQ', 'TEMP', 'POWDC', 'POWAC', 'PHASE']
UNITS = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'OHM2': 'ohm', 'OHM4': 'ohm', 'CAP': 'F', 'FREQ': 'Hz'}


def _si(value, unit):
    return uncertainty.format_value(value, unit, sig=3) if value is not None else ''


class SpecManagerPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        sm.seed()
        self.sel = None
        self.kind = tk.StringVar()
        self.term = tk.StringVar()
        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Label(top, text='Standards whose published accuracy specifications are used to compute reported uncertainties', style='Muted.TLabel').pack(side='left')
        ttk.Button(top, text='Import spec JSON...', style='Quiet.TButton', command=self.import_json).pack(side='right')
        ttk.Button(top, text='Export JSON...', style='Quiet.TButton', command=self.export_json).pack(side='right', padx=6)
        self.stds = ui.make_table(self, ('model', 'desc', 'conf', 'div', 'period', 'rows', 'assets', 'issues', 'approved'),
                                  ('Model', 'Description', 'Confidence on sheet', 'Divisor', 'Period', 'Ranges', 'Assets', 'Sheet issues', 'Approved'),
                                  (90, 140, 140, 150, 70, 70, 160, 90, 190), height=4, anchors={'model': 'w', 'desc': 'w', 'assets': 'w', 'approved': 'w'}, pack=False)
        self.stds.master.pack(fill='x', pady=(8, 6))
        self.stds.bind('<<TreeviewSelect>>', lambda _e: self.pick())
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        ttk.Button(bar, text='Set divisor...', command=self.set_divisor).pack(side='left')
        ttk.Button(bar, text='Set assets...', command=self.set_assets).pack(side='left', padx=6)
        ttk.Button(bar, text='Sheet issues...', command=self.show_issues).pack(side='left')
        ttk.Button(bar, text='Check an EMU...', style='Accent.TButton', command=self.check_emu).pack(side='right')
        f = ttk.Frame(self)
        f.pack(fill='x', pady=(10, 3))
        ttk.Label(f, text='Ranges').pack(side='left')
        ttk.Combobox(f, textvariable=self.kind, values=KINDS, width=8, state='readonly').pack(side='left', padx=6)
        ttk.Entry(f, textvariable=self.term, width=28).pack(side='left')
        ttk.Label(f, text='  filter by function type / text   (double-click a row to set its calibrator resolution)', style='Small.TLabel').pack(side='left')
        self.kind.trace_add('write', lambda *_: self.show_rows())
        self.term.trace_add('write', lambda *_: self.show_rows())
        self.rows = ui.make_table(self, ('function', 'range', 'amp', 'freq', 'res', 'one', 'ninety'),
                                  ('Function', 'Range', 'Value span', 'Frequency', 'Resolution', '1 yr spec', '90 day spec'),
                                  (300, 200, 200, 150, 110, 190, 190), height=12,
                                  anchors={'function': 'w', 'range': 'w', 'amp': 'w', 'freq': 'w', 'res': 'e', 'one': 'w', 'ninety': 'w'})
        self.rows.bind('<Double-1>', lambda _e: self.edit_resolution())
        self.refresh()

    # ----------------------------------------------------------------------------------------------------
    def refresh(self):
        self.stds.delete(*self.stds.get_children())
        for s in sm.standards():
            div, why = sm.standard(s['id']).divisor()
            assets = ', '.join(a for a, _ in sm.assets_of(s['id']))
            data = sm.export_data(s['id'])
            issues = len(data.get('problems') or [])
            self.stds.insert('', 'end', iid=str(s['id']), values=(s['model'], s['description'], s['confidence_text'] or 'not specified', f'{div:g}',
                                                              s['period'], s['rows'], assets, issues, f"{s['approved_by']} {s['approve_date']}"))
        kids = self.stds.get_children()
        if kids and not (self.sel and str(self.sel) in kids):
            self.stds.selection_set(kids[0])
        self.pick()

    def pick(self):
        s = self.stds.selection()
        self.sel = int(s[0]) if s else None
        self.show_rows()

    def show_rows(self):
        self.rows.delete(*self.rows.get_children())
        if self.sel is None:
            return
        term = self.term.get().strip().lower()
        for r in sm.rows_of(self.sel, kind=self.kind.get() or None):
            if term and term not in (r['function'] + ' ' + r['label'] + ' ' + r['variant']).lower():
                continue
            u = r['unit']
            amp = f"{_si(r['amp_lo'], u)} to {_si(r['amp_hi'], u)}" if r['amp_lo'] is not None else ''
            frq = f"{_si(r['freq_lo'], 'Hz')} to {_si(r['freq_hi'], 'Hz')}" if r['freq_lo'] is not None else ''
            txt = {s['period']: s.get('text') or s.get('raw') or '' for s in r['specs']}
            self.rows.insert('', 'end', iid=str(r['id']), values=(r['function'], r['label'], amp, frq, _si(r['resolution'], u) if r['resolution'] else '',
                                                              txt.get('1 yr', ''), txt.get('90 day', '')))

    # ----------------------------------------------------------------------------------------------------
    def _who(self):
        import getpass
        try:
            return getpass.getuser()
        except Exception:
            return ''

    def set_divisor(self):
        if self.sel is None:
            return
        cur = sm.standard(self.sel).divisor()[0]
        txt = simpledialog.askstring('Coverage divisor', 'Divisor that turns the published accuracy into a standard uncertainty (k = 1).\n'
                                     'Common: 2 (95 % treated as k = 2), 1.96, 2.576 (99 %), 1.732 (rectangular).\nBlank = use the sheet\'s confidence level.',
                                     initialvalue=f'{cur:g}', parent=self)
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and not 1.0 <= val <= 4.0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Divisor', 'Enter a number between 1 and 4.', parent=self)
            return
        reason = simpledialog.askstring('Reason', 'Reason for the change (kept in the change log):', parent=self) or ''
        sm.set_standard_field(self.sel, 'divisor', val, who=self._who(), reason=reason)
        self.refresh()

    def set_assets(self):
        if self.sel is None:
            return
        cur = '; '.join(f'{a}:{s}' for a, s in sm.assets_of(self.sel))
        txt = simpledialog.askstring('Assets', 'Instrument IDs of the units of this model used as standards.\nFormat  ID:serial; ID:serial', initialvalue=cur, parent=self)
        if txt is None:
            return
        pairs = []
        for part in txt.split(';'):
            if part.strip():
                a, _, s = part.partition(':')
                pairs.append((a.strip(), s.strip()))
        sm.set_assets(self.sel, pairs)
        self.refresh()

    def edit_resolution(self):
        sel = self.rows.selection()
        if not sel:
            return
        rid = int(sel[0])
        row = next((r for r in sm.rows_of(self.sel) if r['id'] == rid), None)
        if not row:
            return
        txt = simpledialog.askstring('Calibrator resolution', f"Resolution of the calibrator on '{row['label']}' in {row['unit'] or 'SI base units'} "
                                     '(the last digit it can set).\nBlank = not recorded.', initialvalue=f"{row['resolution']:g}" if row['resolution'] else '', parent=self)
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and val <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Resolution', 'Enter a positive number in SI base units (V, A, ohm, F, Hz).', parent=self)
            return
        sm.update_row(rid, {'resolution': val}, who=self._who(), reason='resolution entered in the manager')
        self.show_rows()

    def show_issues(self):
        if self.sel is None:
            return
        probs = sm.export_data(self.sel).get('problems') or []
        win = tk.Toplevel(self)
        win.title('Sheet issues found when the specification was read')
        txt = tk.Text(win, width=130, height=28, wrap='word')
        txt.pack(fill='both', expand=True)
        txt.insert('end', '\n'.join(f"[{p['level']}] {p['where']}: {p['what']}" for p in probs) or 'None found.')
        txt.configure(state='disabled')

    def import_json(self):
        f = filedialog.askopenfilename(parent=self, filetypes=[('Spec JSON', '*.json')])
        if not f:
            return
        try:
            data = json.load(open(f, encoding='utf-8'))
            if not sm.import_data(data, who=self._who()):
                raise ValueError('not a specification file')
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror('Import', f'Could not import: {e}', parent=self)
            return
        self.refresh()

    def export_json(self):
        if self.sel is None:
            return
        f = filedialog.asksaveasfilename(parent=self, defaultextension='.json')
        if f:
            json.dump(sm.export_data(self.sel), open(f, 'w', encoding='utf-8'), indent=1)

    # ----------------------------------------------------------------------------------------------------
    def check_emu(self):
        if self.sel is None:
            return
        CheckDialog(self, sm.standard(self.sel))


class CheckDialog(tk.Toplevel):
    """Enter an applied point and the EMU that was reported; shows the budget and whether the report is below the scope CMC or the budget."""
    def __init__(self, parent, standard):
        super().__init__(parent)
        self.title(f'Check a reported EMU - {standard.model}')
        self.std = standard
        self.v = {k: tk.StringVar(value=d) for k, d in (('kind', 'DCV'), ('nominal', ''), ('freq', ''), ('reported', ''), ('res', ''), ('typea', ''))}
        g = ttk.Frame(self, padding=12)
        g.pack(fill='both', expand=True)
        for i, (lab, key, hint) in enumerate((('Function', 'kind', ''), ('Nominal (SI: V, A, ohm, F, Hz)', 'nominal', 'e.g. 0.1'), ('Frequency (Hz)', 'freq', 'AC only'),
                                              ('Reported EMU (SI units, k = 2)', 'reported', 'e.g. 3e-6'), ('Calibrator resolution (SI)', 'res', 'blank = from the sheet'),
                                              ('Type A std. uncertainty (SI, k = 1)', 'typea', 'repeatability, blank = none'))):
            ttk.Label(g, text=lab).grid(row=i, column=0, sticky='w', pady=2)
            if key == 'kind':
                ttk.Combobox(g, textvariable=self.v[key], values=[k for k in KINDS if k][:7] + ['FREQ'], width=10, state='readonly').grid(row=i, column=1, sticky='w')
            else:
                ttk.Entry(g, textvariable=self.v[key], width=16).grid(row=i, column=1, sticky='w')
            ttk.Label(g, text=hint, style='Small.TLabel').grid(row=i, column=2, sticky='w', padx=6)
        ttk.Button(g, text='Check', style='Accent.TButton', command=self.run).grid(row=7, column=0, pady=8, sticky='w')
        self.out = tk.Text(g, width=96, height=14, wrap='word')
        self.out.grid(row=8, column=0, columnspan=3)

    def _num(self, key, required=False):
        t = self.v[key].get().strip()
        if not t:
            if required:
                raise ValueError(key)
            return None
        return float(t)

    def run(self):
        try:
            nominal, reported = self._num('nominal', True), self._num('reported', True)
            freq, res, ta = self._num('freq'), self._num('res'), self._num('typea')
        except ValueError:
            messagebox.showerror('Check', 'Enter numbers (nominal and reported are required).', parent=self)
            return
        kind = self.v['kind'].get()
        b = ub.build(kind, nominal, UNITS.get(kind, ''), standard=self.std, frequency=freq, resolution=res, type_a=[('Type A', ta, 1.0)] if ta else [])
        status, text = ub.audit(reported, b)
        lines = [f'{status}: {text}', '']
        for c in b.components:
            lines.append(f'  {c.name:28s} u = {c.u:.4g}   ({c.source})')
        if b.emu is not None:
            lines.append(f'  Expanded (k = {b.k:g}): {b.emu:.4g}')
        lines.append(f'  Scope CMC: {b.cmc:.4g}' if b.cmc is not None else '  Scope CMC: not covered')
        if b.reported is not None:
            lines.append(f'  Smallest value that may be reported: {b.reported:.4g}')
        lines += [f'  Note: {n}' for n in b.notes]
        self.out.delete('1.0', 'end')
        self.out.insert('end', '\n'.join(lines))
