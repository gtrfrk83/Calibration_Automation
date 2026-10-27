"""Review window shown when the technician presses Export Report (PDF): every test point with its assigned uncertainty, the standard that applied it
(changeable per row or for the selected rows), budget, scope minimum, reported value, TUR and a status badge.  Replaces the old details-only popup; the
report details (technician, conditions, standards used, TAR / TUR) stay in a compact strip.

How it is reached (no engine is edited, so no procedure's verified fingerprint changes):  report_dialog.ask_details(parent, procedure) calls ask().  ask()
finds the engine App by object scan - the object whose `.root` is `parent` and which has `certificate_rows_and_points()` - builds the Tk-free model
(report_review_model.py) from the rows and points the engine would print, shows the window, and returns the same details dict as before plus
details['uncertainty_review'].  report_pdf.write_calibration_pdf applies the changes; report_snapshot stores them (details are part of the snapshot), so
Asset History 'Regenerate PDF' prints them again.  When the App cannot be found, or the engine is not covered yet (phase 2: fgen, MDO4000C, TDS2000C,
WaveSurfer), ask() returns UNAVAILABLE and report_dialog shows the old popup.  Never raises into the engine.

Rules: no reason is asked for a standard change; Reported is never below the scope minimum (report_pdf.point_uncertainty / uncertainty_budget); the
window also opens in a demo run (marked); nothing here changes a limit, a pass / fail result or an instrument command.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import report_review_model as M
import ui_theme as ui

from report_review_flow import (COVERED, SHORT, UNAVAILABLE, asset_of, build_models, find_app, finish, hint_kinds, is_demo)       # noqa: F401  (moved to the toolkit-free module; names kept here)


def ask(parent, procedure='', app=None):
    """The review window for the engine behind `parent`.  Returns the details dict, None when cancelled, or UNAVAILABLE (use the old popup)."""
    built = build_models(parent, procedure, app)
    if built is UNAVAILABLE:
        return UNAVAILABLE
    models, demo = built
    details = None
    for n, model in enumerate(models, 1):
        win = ReviewWindow(parent, model, procedure, demo=demo, details=details, position=(n, len(models)))
        details = win.run()
        if details is None:
            return None
    return finish(models, details)


class ReviewWindow:
    last = None                      # the most recent window (the real-Tk checks drive it)
    COLS = ('step', 'point', 'tol', 'std', 'budget', 'scope', 'reported', 'tur', 'status')
    HEADS = ('Step', 'Test point', 'Tolerance', 'Standard used', 'Budget', 'Scope minimum', 'Reported (k=2)', 'TUR', 'Status')
    WIDTHS = (46, 220, 82, 108, 74, 96, 96, 58, 140)

    def __init__(self, parent, model, procedure='', demo=False, details=None, position=(1, 1)):
        self.parent, self.model, self.procedure, self.demo = parent, model, procedure, demo
        ReviewWindow.last = self
        self.store = ui.Settings('report_details')
        self.filter = tk.StringVar(value='All')
        self.result = None
        self.editor = None
        self.win = ui.dialog(parent, 'Review uncertainties before generating the PDF')
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self._build(details or {}, position)
        ui.fit_window(self.win, 1360, 860, min_w=860, min_h=520)
        self.refresh()

    # ------------------------------------------------------------------------------------------------------------------ layout
    def _build(self, prior, position):
        win, m = self.win, self.model
        win.configure(background=ui.C['bg'])
        bottom = ttk.Frame(win, padding=(ui.px(18), ui.px(10)))
        bottom.pack(side='bottom', fill='x')
        self.btn_ok = ttk.Button(bottom, text='Generate PDF' if position[0] == position[1] else f'Next meter ({position[0]}/{position[1]})',
                                 style='Accent.TButton', command=self.generate)
        self.btn_ok.pack(side='right')
        ttk.Button(bottom, text='Cancel', command=self.cancel).pack(side='right', padx=(0, 8))
        self.btn_reset = ttk.Button(bottom, text='Reset changes', command=self.reset)
        self.btn_reset.pack(side='right', padx=(0, 8))
        tk.Frame(win, height=1, background=ui.C['border']).pack(side='bottom', fill='x')

        asset = m.asset or 'not entered'
        banner = ui.Banner(win, 'Review uncertainties before generating the PDF', '')
        banner.pack(fill='x')
        self.banner = banner
        self.pills = {}
        for key, kind in (('As budgeted', 'good'), ('Raised to scope', 'warn'), ('Not in scope', 'bad'), ('Standard changed', 'info'), (M.MANUAL, 'warn')):
            self.pills[key] = banner.add_pill('', kind)
        self.subtitle_base = f'{self.procedure or "Calibration"} · Asset {asset}' + (f' · meter {position[0]} of {position[1]}' if position[1] > 1 else '')
        if self.demo:
            ui.Notice(win, 'DEMO DATA - NOT CALIBRATION EVIDENCE. This is a demo run: the PDF is stamped DEMO and nothing is recorded in Asset History.',
                      'warn').pack(fill='x', padx=ui.px(18), pady=(8, 0))

        # ---- compact details strip
        strip = ttk.Frame(win, padding=(ui.px(18), ui.px(8), ui.px(18), 0))
        strip.pack(fill='x')
        self.vars = {k: tk.StringVar(value=prior.get(k, self.store.get(k, ''))) for k in ('technician', 'temperature', 'humidity')}
        for c, (key, text, width) in enumerate((('technician', 'Technician', 16), ('temperature', 'Temperature', 9), ('humidity', 'Humidity', 9))):
            ttk.Label(strip, text=text, style='Muted.TLabel').grid(row=0, column=2 * c, sticky='w', padx=(0, 4))
            ttk.Entry(strip, textvariable=self.vars[key], width=width).grid(row=0, column=2 * c + 1, sticky='w', padx=(0, 14))
        ttk.Label(strip, text='Default standard', style='Muted.TLabel').grid(row=1, column=0, columnspan=2, sticky='w', padx=(0, 4), pady=(6, 0))
        self.default_var = tk.StringVar(value=M.label(m.default_std))
        self.default_box = ttk.Combobox(strip, textvariable=self.default_var, state='readonly', width=13, values=[])
        self.default_box.grid(row=1, column=2, columnspan=2, sticky='w', padx=(0, 14), pady=(6, 0))
        self.default_box.bind('<<ComboboxSelected>>', self.on_default)
        import report_pdf
        remembered = report_pdf.remembered_show_tar_tur()
        self.tar_var = tk.BooleanVar(value=bool(prior.get('show_tar', remembered.tar)))
        self.tur_var = tk.BooleanVar(value=bool(prior.get('show_tur', remembered.tur)))
        ttk.Checkbutton(strip, text='TAR on the PDF', variable=self.tar_var).grid(row=1, column=4, columnspan=2, sticky='w', padx=(0, 8), pady=(6, 0))
        ttk.Checkbutton(strip, text='TUR on the PDF', variable=self.tur_var).grid(row=1, column=6, columnspan=2, sticky='w', padx=(0, 8), pady=(6, 0))
        self.left_var = tk.BooleanVar(value=bool(prior.get('left_numeric', report_pdf.remembered_left_numeric())))
        ttk.Checkbutton(strip, text='As left data as numerical', variable=self.left_var).grid(row=1, column=8, columnspan=2, sticky='w', padx=(0, 8), pady=(6, 0))
        ttk.Button(strip, text='Standards used…', command=self.edit_standards).grid(row=0, column=6, columnspan=3, sticky='e')
        strip.columnconfigure(8, weight=1)
        self.standards = prior.get('standards') or self.store.get('standards', []) or []

        # ---- filter / bulk bar
        bar = ttk.Frame(win, padding=(ui.px(18), ui.px(8), ui.px(18), ui.px(6)))
        bar.pack(fill='x')
        ttk.Label(bar, text='Show').pack(side='left', padx=(0, 6))
        self.filter_buttons = {}
        for name in M.FILTERS:
            b = ttk.Radiobutton(bar, text=name, value=name, variable=self.filter, command=self.refresh)
            b.pack(side='left', padx=(0, 10))
            self.filter_buttons[name] = b
        self.bulk_var = tk.StringVar()
        ttk.Button(bar, text='Apply', command=self.apply_bulk).pack(side='right')
        self.bulk_box = ttk.Combobox(bar, textvariable=self.bulk_var, state='readonly', width=13, values=[])
        self.bulk_box.pack(side='right', padx=(6, 8))
        ttk.Label(bar, text='Set standard for selected rows').pack(side='right')

        # ---- the grid
        holder = ttk.Frame(win, padding=(ui.px(18), 0))
        holder.pack(fill='both', expand=True)
        self.tree = ui.make_table(holder, self.COLS, self.HEADS, self.WIDTHS, selectmode='extended',
                                  anchors=dict(step='w', point='w', tol='e', std='w', budget='e', scope='e', reported='e', tur='e', status='w'),
                                  stretch=dict(step=False, point=True, tol=False, std=False, budget=False, scope=False, reported=False, tur=False, status=False),
                                  height=14, hscroll=False)
        C = ui.C
        self.tree.tag_configure('ok', background=C['row_even'], foreground=C['text'])
        self.tree.tag_configure('raised', background=C['row_even'], foreground=C['warn'])
        self.tree.tag_configure('bad', background=C['bad_bg'], foreground=C['bad'])
        self.tree.tag_configure('changed', background=C['info_bg'], foreground=C['info'])
        self.tree.tag_configure('locked', background=C['row_even'], foreground=C['muted'])
        self.tree.tag_configure('manual', background=C['warn_bg'], foreground=C['bad'])
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        self.tree.bind('<Button-1>', self.on_click, add='+')
        self.tree.bind('<Configure>', lambda _e: self.close_editor(), add='+')

        # ---- notes
        foot = ttk.Frame(win, padding=(ui.px(18), ui.px(8)))
        foot.pack(side='bottom', fill='x')
        self.note = ttk.Label(foot, style='Muted.TLabel', justify='left', wraplength=ui.px(900),
                              text='Reported = larger of Budget and Scope minimum, rounded up to 2 significant figures (k = 2), never below the lab\u2019s A2LA scope minimum. '
                                   'Limits and pass / fail are never touched.')
        self.note.pack(side='left', fill='x', expand=True)
        self.hint = tk.StringVar()
        self.hint_label = ttk.Label(win, textvariable=self.hint, style='Muted.TLabel', foreground=ui.C['bad'], padding=(ui.px(18), 0), wraplength=ui.px(1100), justify='left')
        self.hint_label.pack(side='bottom', fill='x')
        foot.bind('<Configure>', lambda e: self.note.configure(wraplength=max(ui.px(240), e.width - ui.px(40))), add='+')
        holder.pack_forget()
        holder.pack(fill='both', expand=True)                      # packed last: the notes and buttons below keep their room, the grid takes the rest

    # ------------------------------------------------------------------------------------------------------------------ content
    def row_values(self, r):
        s, e = r.spec, r.cur
        if s.locked and s.q.get('kind') == 'FREQ':
            std = M.LOCKED_FREQUENCY
        elif s.locked:
            std = s.std_label or '—'
        else:
            std = M.label(r.standard) + '  ▾'
        unit = e.unit
        budget = M.fmt(e.budget, unit) or '—'
        scope = M.fmt(e.cmc, unit) or ('not in scope' if e.status != M.NO_UNC else '—')
        rep = r.reported_text or '—'
        if r.can_type() and r.typed is None:
            rep += '  [type]'                                            # a point the scope does not cover: click to type an uncertainty
        tur = r.tur_text or '—'
        return (s.step, f'{s.nominal_text}  ·  {s.description}', M.tolerance_text(s) or '—', std, budget, scope, rep, tur, r.status)

    def tag_for(self, r):
        if r.spec.locked and r.cur.status in (M.NO_UNC, M.AS_BUDGETED):
            return 'locked'
        st = r.status
        return {M.MANUAL: 'manual', M.NOT_IN_SCOPE: 'bad', M.CHANGED: 'changed', M.RAISED: 'raised', M.NO_UNC: 'locked'}.get(st, 'ok')

    def refresh(self):
        self.close_editor()
        m = self.model
        keep = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for r in m.visible(self.filter.get()):
            self.tree.insert('', 'end', iid=str(r.spec.idx), values=self.row_values(r), tags=(self.tag_for(r),))
        for iid in keep:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        c = m.counts()
        with_unc = c['all'] - c.get(M.NO_UNC, 0)
        self.banner.subtitle.set(f'{self.subtitle_base} · {with_unc} of {c["all"]} points carry an uncertainty')
        for key, pill in self.pills.items():
            pill.configure(text=f'{c.get(key, 0)} {SHORT.get(key, key.lower())}')
        for name, text in (('All', f'All {c["all"]}'), ('Needs attention', f'Needs attention {c["attention"]}'), ('Changed by me', f'Changed by me {c["changed"]}')):
            self.filter_buttons[name].configure(text=text)
        n_bad = c.get(M.NOT_IN_SCOPE, 0)
        self.default_hint = (f'{n_bad} point(s) not in the lab scope (red): printed as before. Click the Reported cell [type] to enter an uncertainty.' if n_bad else '')
        if not self.editor:
            self.hint.set(self.default_hint)
        opts = sorted({k for r in m.rows if not r.spec.locked for k in m.options(r.spec.idx)}, key=lambda k: M.SOURCE_STANDARDS.index(k) if k in M.SOURCE_STANDARDS else 9)
        self.default_box.configure(values=[M.label(k) for k in opts], state='readonly' if opts else 'disabled')
        self.default_var.set(M.label(m.default_std))
        self.btn_reset.configure(state='normal' if (c['changed'] or m.default_std != m.engine_default) else 'disabled')
        self.on_select()

    def on_select(self, _e=None):
        idx = [int(i) for i in self.tree.selection()]
        common = self.model.common_options(idx) if idx else []
        self.bulk_box.configure(values=[M.label(k) for k in common], state='readonly' if common else 'disabled')
        if self.bulk_var.get() and M.key_of(self.bulk_var.get()) not in common:
            self.bulk_var.set('')

    # ------------------------------------------------------------------------------------------------------------------ editing
    def close_editor(self):
        if self.editor is not None:
            try:
                self.editor.destroy()
            except tk.TclError:
                pass
            self.editor = None

    def on_click(self, event):
        self.close_editor()
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid or col not in ('#4', '#7'):
            return
        idx = int(iid)
        row = self.model.rows[idx]
        if col == '#4' and not row.spec.locked:
            self.win.after_idle(lambda: self.open_editor(iid, idx))
        elif col == '#7' and row.can_type():
            self.win.after_idle(lambda: self.open_typed(iid, idx))

    def open_editor(self, iid, idx):
        bb = self.tree.bbox(iid, '#4')
        if not bb:
            return
        opts = self.model.options(idx)
        box = ttk.Combobox(self.tree, state='readonly', values=[M.label(k) for k in opts])
        box.set(M.label(self.model.rows[idx].standard))
        box.place(x=bb[0], y=bb[1], width=bb[2], height=bb[3])
        box.bind('<<ComboboxSelected>>', lambda _e: self.choose(idx, box.get()))
        box.bind('<Escape>', lambda _e: self.close_editor())
        self.editor = box
        box.focus_set()

    def open_typed(self, iid, idx):
        """Editable Reported cell of a row the lab scope does not cover: value + unit (a bare number is in the unit named in the hint).  Enter keeps it, empty
        clears it, Esc leaves the cell as it was."""
        bb = self.tree.bbox(iid, '#7')
        if not bb:
            return
        row = self.model.rows[idx]
        var = tk.StringVar(value=(row.typed or {}).get('text', ''))
        box = ttk.Entry(self.tree, textvariable=var)
        box.place(x=max(bb[0] - 40, 0), y=bb[1], width=bb[2] + 40, height=bb[3])
        self.editor = box
        unit = row.entry_hint()
        self.hint.set(f'Type the uncertainty (k = 2) for step {row.spec.step}, for example 3.5 {unit}; a bare number is in {unit}. '
                      'Enter keeps it, empty clears it, Esc cancels.')

        def commit(_e=None):
            ok, msg = self.model.set_typed(idx, var.get())
            if ok:
                self.hint.set('')
                self.refresh()
            else:
                self.hint.set(msg)
                box.focus_set()
        box.bind('<Return>', commit)
        box.bind('<KP_Enter>', commit)
        box.bind('<Escape>', lambda _e: (self.close_editor(), self.hint.set(self.default_hint)))
        box.focus_set()
        box.select_range(0, 'end')

    def choose(self, idx, text):
        self.close_editor()
        self.model.set_standard(idx, text)
        self.refresh()

    def apply_bulk(self):
        idx = [int(i) for i in self.tree.selection()]
        if idx and self.bulk_var.get():
            self.model.set_standard_many(idx, self.bulk_var.get())
            self.refresh()

    def on_default(self, _e=None):
        self.model.set_default(self.default_var.get())
        self.refresh()

    def reset(self):
        self.model.reset()
        self.refresh()

    def edit_standards(self):
        dlg = ui.dialog(self.win, 'Standards used')
        dlg.resizable(False, False)
        body = ttk.Frame(dlg, padding=(18, 14))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Standards used (kept with the report record; optional)', style='Bold.TLabel').pack(anchor='w', pady=(0, 6))
        grid = ttk.Frame(body)
        grid.pack(fill='x')
        for c, h in enumerate(('Standard (model)', 'Serial number', 'Calibration due')):
            ttk.Label(grid, text=h, style='Muted.TLabel').grid(row=0, column=c, sticky='w', padx=(0, 8))
        rows = []
        for r in range(1, 4):
            prior = self.standards[r - 1] if r - 1 < len(self.standards) else {}
            trio = [tk.StringVar(value=prior.get(k, '')) for k in ('description', 'serial', 'due')]
            rows.append(trio)
            for c, (v, w) in enumerate(zip(trio, (28, 16, 14))):
                ttk.Entry(grid, textvariable=v, width=w).grid(row=r, column=c, padx=(0, 8), pady=2, sticky='w')

        def ok():
            self.standards = [dict(zip(('description', 'serial', 'due'), (x.get().strip() for x in trio))) for trio in rows]
            dlg.destroy()
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=(10, 0))
        ttk.Button(bar, text='OK', style='Accent.TButton', command=ok).pack(side='right')
        ttk.Button(bar, text='Cancel', command=dlg.destroy).pack(side='right', padx=(0, 8))
        self.win.wait_window(dlg)

    # ------------------------------------------------------------------------------------------------------------------ finish
    def details(self) -> dict:
        import report_pdf
        d = {k: v.get().strip() for k, v in self.vars.items()}
        d['standards'] = [dict(s) for s in self.standards]
        d['procedure'] = self.procedure
        d['show_tar'], d['show_tur'] = bool(self.tar_var.get()), bool(self.tur_var.get())
        d['show_tar_tur'] = report_pdf.TarTur(d['show_tar'], d['show_tur'])
        d['left_numeric'] = bool(self.left_var.get())
        return d

    def generate(self):
        import report_pdf
        d = self.details()
        report_pdf.remember_show_tar_tur(d['show_tar_tur'])
        report_pdf.remember_left_numeric(d['left_numeric'])
        for k in ('technician', 'temperature', 'humidity'):
            self.store.set(k, d[k])
        self.store.set('standards', d['standards'])
        self.store.save()
        self.result = d
        self.win.destroy()

    def cancel(self):
        self.result = None
        self.win.destroy()

    def run(self):
        self.parent.wait_window(self.win)
        return self.result
