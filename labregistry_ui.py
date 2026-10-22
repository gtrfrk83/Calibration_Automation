"""Screens for labregistry: the asset history browser and the drift chart (HistoryPanel is a plain ttk frame the Manager puts in a tab)."""
from __future__ import annotations

import os
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

import labregistry as reg
import report_snapshot as snap
import ui_theme as ui

def _tags(tree):
    tree.tag_configure('expired', background=ui.C['bad_bg'], foreground=ui.C['bad'])
    tree.tag_configure('fail', foreground=ui.C['bad'])


# ================================================================================================ asset history
class HistoryPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.term = tk.StringVar()
        bar = ttk.Frame(self)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='Find').pack(side='left')
        ttk.Entry(bar, textvariable=self.term, width=34).pack(side='left', padx=(8, 6))
        ttk.Label(bar, text='Instrument ID, model or serial number', style='Small.TLabel').pack(side='left', padx=(2, 8))
        ttk.Button(bar, text='Refresh', style='Quiet.TButton', command=self.refresh).pack(side='left')
        self.term.trace_add('write', lambda *_: self.refresh())
        self.note = tk.StringVar()
        ttk.Label(bar, textvariable=self.note, style='Muted.TLabel').pack(side='right')

        cols = ('asset', 'model', 'serial', 'runs', 'last', 'result', 'due')
        self.assets = ui.make_table(self, cols, ('Instrument ID', 'Instrument', 'Serial number', 'Reports', 'Last report', 'Last result', 'Next due'),
                                    (150, 250, 140, 70, 120, 130, 120), height=6, anchors={'asset': 'w', 'model': 'w', 'serial': 'w'}, pack=False)
        self.assets.master.pack(fill='x')
        _tags(self.assets)
        self.assets.bind('<<TreeviewSelect>>', lambda _e: self.show_runs())
        ttk.Label(self, text='Reports for the selected instrument (newest first)', style='Bold.TLabel').pack(anchor='w', pady=(10, 3))
        rcols = ('date', 'procedure', 'tech', 'points', 'failed', 'file')
        self.runs = ui.make_table(self, rcols, ('Report date', 'Procedure', 'Technician', 'Points', 'Out of tol.', 'Report file'),
                                  (150, 330, 130, 70, 90, 330), height=4, anchors={'procedure': 'w', 'tech': 'w', 'file': 'w'}, pack=False)
        self.runs.master.pack(fill='x')
        _tags(self.runs)
        self.runs.bind('<<TreeviewSelect>>', lambda _e: self.show_points())
        self.runs.bind('<Double-1>', self._runs_double)                                   # regenerate the PDF
        for button in ('<Button-3>', '<Button-2>'):                                         # context menu (right click; middle button on macOS)
            self.runs.bind(button, self._runs_menu)
        head = ttk.Frame(self)
        head.pack(fill='x', pady=(10, 3))
        ttk.Label(head, text='Points in the selected report', style='Bold.TLabel').pack(side='left')
        ttk.Label(head, text='  % of tolerance = how much of the allowed error the as-found reading used (0 on nominal, 100 at a limit)', style='Muted.TLabel').pack(side='left')
        pcols = ('section', 'desc', 'nominal', 'low', 'high', 'found', 'unit', 'result', 'pct')
        self.points = ui.make_table(self, pcols, ('Section', 'Test point', 'Nominal', 'Low limit', 'High limit', 'As found', 'Units', 'Result', '% of tol.'),
                                    (130, 300, 120, 90, 90, 100, 60, 70, 80), height=8,
                                    anchors={'section': 'w', 'desc': 'w', 'nominal': 'e', 'low': 'e', 'high': 'e', 'found': 'e', 'unit': 'w', 'pct': 'e'})
        _tags(self.points)
        self.points.bind('<Double-1>', lambda _e: self.show_drift())
        buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=(10, 0))
        self.btn_drift = ttk.Button(buttons, text='Drift of selected point...', style='Accent.TButton', command=self.show_drift)
        self.btn_drift.pack(side='left')
        self.btn_open = ttk.Button(buttons, text='Open report PDF', command=self.open_report)
        self.btn_open.pack(side='left', padx=8)
        self.btn_regen = ttk.Button(buttons, text='Regenerate PDF...', command=self.regenerate_pdf)
        self.btn_regen.pack(side='left')
        self.regen_note = tk.StringVar()
        ttk.Label(buttons, textvariable=self.regen_note, style='Muted.TLabel').pack(side='left', padx=10)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label='Regenerate PDF...', command=self.regenerate_pdf)
        self.menu.add_command(label='Open report PDF', command=self.open_report)
        self.refresh()

    def refresh(self):
        keep = self.assets.selection()
        self.assets.delete(*self.assets.get_children())
        rows = reg.assets_overview(self.term.get().strip())
        for r in rows:
            due, _ = reg.next_due(r['asset_id'])
            overdue = bool(due and due < date.today())
            result = 'OUT OF TOLERANCE' if r['failed'] else 'PASS'
            tag = 'fail' if r['failed'] else ''
            if overdue:
                tag = 'expired'
            self.assets.insert('', 'end', iid=r['asset_id'], values=(r['asset_id'], r['model'], r['serial'], r['runs'], r['last'][:10], result,
                                                                    (due.isoformat() + ('  OVERDUE' if overdue else '')) if due else ''), tags=(tag,) if tag else ())
        self.note.set(f'{len(rows)} instrument(s) with reports on this computer.' if rows else 'No reports recorded yet: history is added each time a PDF report is exported.')
        for k in keep:
            if self.assets.exists(k):
                self.assets.selection_set(k)
        self.show_runs()

    def _asset(self):
        sel = self.assets.selection()
        return sel[0] if sel else None

    def show_runs(self):
        keep = self.runs.selection()
        self.runs.delete(*self.runs.get_children())
        asset = self._asset()
        for r in (reg.runs_for(asset) if asset else []):
            self.runs.insert('', 'end', iid=str(r['id']), values=(r['run_at'].replace('T', ' ')[:16], r['procedure'], r['technician'], r['total'], r['failed'] or '',
                                                                  os.path.basename(r['report_file'])), tags=('fail',) if r['failed'] else ())
        kids = self.runs.get_children()
        pick = next((k for k in keep if self.runs.exists(k)), kids[0] if kids else None)
        if pick:
            self.runs.selection_set(pick)
        self.show_points()

    def show_points(self):
        self.points.delete(*self.points.get_children())
        sel = self.runs.selection()
        for n, p in enumerate(reg.points_for(int(sel[0])) if sel else []):
            pct = '' if p['dev_pct'] is None else f"{p['dev_pct']:+.0f}%"
            self.points.insert('', 'end', iid=str(n), values=(p['section'], p['description'], p['nominal'], p['low'], p['high'], p['found'], p['unit'],
                                                              p['result'], pct), tags=('fail',) if p['result'] == 'FAIL' else ())
        self._points = reg.points_for(int(sel[0])) if sel else []
        self._show_regen_hint(int(sel[0]) if sel else None)

    # ------------------------------------------------------------------------------------------ regenerate the PDF of an event
    def _show_regen_hint(self, run_id):
        """One line saying whether the selected event can be printed again (report_snapshot.availability); never raises."""
        try:
            self.regen_note.set(snap.availability(run_id)[1] if run_id is not None else '')
        except Exception:
            self.regen_note.set('')

    def _selected_run_id(self):
        sel = self.runs.selection()
        return int(sel[0]) if sel else None

    def regenerate_pdf(self):
        """Print the selected event's report again (report_snapshot.regenerate): ask where to save, never overwrite without asking."""
        parent = self.winfo_toplevel()
        run_id = self._selected_run_id()
        if run_id is None:
            messagebox.showinfo('Regenerate PDF', 'Select a report in the middle table first.', parent=parent)
            return

        def choose(default_name, original):
            options = dict(parent=parent, title='Save regenerated report', defaultextension='.pdf', initialfile=default_name,
                           filetypes=[('PDF report', '*.pdf')], confirmoverwrite=False)       # the overwrite question is asked by overwrite() below
            if original and os.path.isdir(os.path.dirname(original)):
                options['initialdir'] = os.path.dirname(original)
            return filedialog.asksaveasfilename(**options)

        def overwrite(path, is_original):
            what = 'This is the file the original report was saved to.\n\n' if is_original else ''
            return messagebox.askyesno('Replace file?', f'{what}{os.path.basename(path)} already exists. Replace it?', icon='warning', default='no', parent=parent)

        result = snap.regenerate(run_id, choose_path=choose, confirm_overwrite=overwrite,
                                 confirm_rebuilt=lambda text: messagebox.askokcancel('Rebuild from history rows', text + '\n\nContinue?', parent=parent))
        if result.message:                                  # a cancel has no message
            messagebox.showinfo('Regenerate PDF', result.message, parent=parent)

    def _runs_double(self, event=None):
        """Double-click on a report: regenerate the PDF."""
        if event is not None and not self.runs.identify_row(event.y):
            return
        self.regenerate_pdf()                                 # double-click goes straight to regenerate (Open stays on the button / menu)

    def _runs_menu(self, event):
        row = self.runs.identify_row(event.y)
        if row:
            self.runs.selection_set(row)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    def open_report(self):
        sel = self.runs.selection()
        run = next((r for r in reg.runs_for(self._asset() or '') if sel and str(r['id']) == sel[0]), None)
        if not run or not run['report_file'] or not os.path.exists(run['report_file']):
            messagebox.showinfo('Report', 'The PDF is not at the place it was saved (it may have been moved or deleted).', parent=self.winfo_toplevel())
            return
        try:
            os.startfile(run['report_file'])                      # Windows
        except AttributeError:
            import subprocess
            import sys
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', run['report_file']])
        except OSError as exc:
            messagebox.showerror('Report', str(exc), parent=self.winfo_toplevel())

    def show_drift(self):
        asset, sel = self._asset(), self.points.selection()
        if not asset or not sel:
            messagebox.showinfo('Drift', 'Select a test point in the lower table first.', parent=self.winfo_toplevel())
            return
        p = self._points[int(sel[0])]
        open_drift_chart(self.winfo_toplevel(), asset, p['section'], p['description'], p['unit'])


def choose_action(parent):
    """Small three-button question: 'regenerate' / 'open' / None."""
    win = ui.dialog(parent, 'Report')
    outer = ttk.Frame(win, padding=(18, 14, 18, 14))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='What would you like to do with this report?', style='Bold.TLabel').pack(anchor='w')
    ttk.Label(outer, text='Regenerate prints it again from the record saved when it was issued (it asks where to save).', style='Muted.TLabel').pack(anchor='w', pady=(2, 10))
    picked = {'v': None}

    def done(value):
        picked['v'] = value
        win.destroy()
    bar = ttk.Frame(outer)
    bar.pack(fill='x')
    ttk.Button(bar, text='Regenerate PDF...', style='Accent.TButton', command=lambda: done('regenerate')).pack(side='left')
    ttk.Button(bar, text='Open saved PDF', command=lambda: done('open')).pack(side='left', padx=8)
    ttk.Button(bar, text='Cancel', command=lambda: done(None)).pack(side='right')
    win.bind('<Escape>', lambda _e: done(None))
    parent.wait_window(win)
    return picked['v']


def open_drift_chart(parent, asset, section, description, unit=''):
    data = reg.drift(asset, section, description)
    win = ui.dialog(parent, 'Drift')
    outer = ttk.Frame(win, padding=(18, 14, 18, 14))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=f'{asset}  -  {description}', style='Section.TLabel').pack(anchor='w')
    ttk.Label(outer, text=f'{section}   |   as-found error as a % of the tolerance, one point per report.  0 = on nominal; +100 / -100 = at a limit.',
              style='Muted.TLabel').pack(anchor='w', pady=(2, 8))
    W, H, L, R, T, B = ui.px(760), ui.px(300), ui.px(56), ui.px(70), ui.px(22), ui.px(44)
    cv = tk.Canvas(outer, width=W, height=H, background=ui.C['card'], highlightthickness=1, highlightbackground=ui.C['border'])
    cv.pack()
    pts = [(d, f, v) for d, f, v in data if v is not None]
    if len(pts) < 1:
        cv.create_text(W / 2, H / 2, text='No numeric history for this point yet.', fill=ui.C['muted'])
    else:
        top = max(120.0, max(abs(v) for _, _, v in pts) * 1.15)
        y = lambda v: T + (top - v) / (2 * top) * (H - T - B)
        n = len(pts)
        x = lambda i: L + (W - L - R) * (0.5 if n == 1 else i / (n - 1))
        cv.create_rectangle(L, y(100), W - R, y(-100), fill=ui.C['good_bg'], outline='')
        for v in (-100, -50, 0, 50, 100):
            cv.create_line(L, y(v), W - R, y(v), fill=ui.C['bad'] if abs(v) == 100 else ui.C['border'], dash=() if v == 0 else (3, 3))
            cv.create_text(L - 6, y(v), text=f'{v:+d}%' if v else '0', anchor='e', fill=ui.C['muted'])
        if n > 1:
            cv.create_line(*[c for i, (_d, _f, v) in enumerate(pts) for c in (x(i), y(v))], fill=ui.C['primary'], width=2)
        for i, (d, f, v) in enumerate(pts):
            bad = abs(v) > 100
            cv.create_oval(x(i) - 4, y(v) - 4, x(i) + 4, y(v) + 4, fill=ui.C['bad_dot'] if bad else ui.C['primary'], outline='white')
            cv.create_text(x(i), H - B + 14, text=d[:10], fill=ui.C['muted'])
            cv.create_text(x(i), y(v) - 12, text=f'{f} {unit}'.strip(), fill=ui.C['text'])
    ttk.Button(outer, text='Close', style='Accent.TButton', command=win.destroy).pack(anchor='e', pady=(10, 0))
    parent.wait_window(win)
