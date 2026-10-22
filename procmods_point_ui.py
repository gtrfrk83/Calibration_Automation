"""Tk window of the per-point editor (thin: every decision lives in procmods_point_model.py, which is tested without tkinter).

    procmods_point_ui.attach_tree_menu(app, tree)        # right-click a test point -> Edit        (ProcModsMixin.pm_bind_tree calls this)
    procmods_point_ui.open_point_window(app, pid)        # the small window for one point

NOTE: these widgets were written without a display.  They have been imported and constructed under tests/_tk_stub.py only; they have never
been looked at on a screen.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import procmods as pm
import procmods_point_model as PM
import procmods_ui as UI
import procmods_ui_model as M
import ui_theme as ui

POLL_MS = 1000
_open = {}                                    # (id(app), str(pid)) -> window, so a second Edit on the same point raises the first


# ------------------------------------------------------------------------------------------------------------ the right-click menu
def attach_tree_menu(app, tree, resolver=None, lock=None):
    """Right-click a row of `tree` -> 'Edit'.  `resolver(iid)` gives the point id (default: the row's iid, which is the point id in every
    engine's point list).  The item is disabled, with the reason shown under it, on a verified / locked procedure and while the point is
    being measured.  Returns the menu."""
    menu = tk.Menu(tree, tearoff=0)
    res = resolver or (lambda iid: iid)
    state = {'pid': None}

    def popup(event):
        try:
            iid = tree.identify_row(event.y)
            if not iid:
                return None
            tree.selection_set(iid)
            pid = res(iid)
            state['pid'] = pid
            enabled, why = PM.menu_state(app, pid)
            menu.delete(0, 'end')
            menu.add_command(label='Edit', command=lambda: open_point_window(app, pid, lock=lock), state='normal' if enabled else 'disabled')
            if not enabled:
                menu.add_command(label=why[:90] + ('...' if len(why) > 90 else ''), state='disabled')
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass
        return 'break'

    for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):
        tree.bind(seq, popup, add='+')
    app.__dict__.setdefault('_pm_tree_menus', []).append((tree, res))
    return menu


def selected_point(app):
    """The id of the point selected in any of the app's point lists (None if nothing is)."""
    for tree, res in app.__dict__.get('_pm_tree_menus', []):
        try:
            sel = tree.selection()
        except tk.TclError:
            continue
        if sel:
            return res(sel[0])
    return None


def open_point_window(app, pid, lock=None, parent=None):
    """Open (or raise) the window for point `pid`.  Says why, instead of opening, when the point cannot be edited at all."""
    lock = lock or UI.shared_lock()
    root = parent or getattr(app, 'root', None)
    ok, why = PM.menu_state(app, pid)
    if not ok:
        messagebox.showinfo('Edit point', why, parent=root)
        return None
    key = (id(app), str(pid))
    win = _open.get(key)
    if win is not None:
        try:
            if win.winfo_exists():
                win.lift()
                return win
        except tk.TclError:
            pass
    model = PM.PointEditModel(app, pid, lock)
    win = PointWindow(root, app, model)
    _open[key] = win
    return win


# ------------------------------------------------------------------------------------------------------------ the window
class PointWindow(tk.Toplevel):
    COLUMNS = (('seq', '#', 34), ('inst', 'Instrument', 84), ('cmd', 'Command for this point', 250), ('rb', 'Read-back', 110),
               ('risk', 'Risk', 90), ('status', 'Status', 108), ('chg', 'Changed', 70))

    def __init__(self, parent, app, model: PM.PointEditModel):
        super().__init__(parent)
        self.app, self.model, self.lock = app, model, model.lock
        self.title(model.title + (' [DEMO]' if model.demo else ''))
        self.geometry(f'{ui.px(860)}x{ui.px(760)}')
        self.message = tk.StringVar()
        self.scope = tk.StringVar(value=model.scope)
        self.reason = tk.StringVar()
        self.ack = tk.BooleanVar(value=False)
        self.redo = tk.BooleanVar(value=False)
        self.cmd_text = tk.StringVar()
        self.cmd_preview = tk.StringVar()
        self.cmd_info = tk.StringVar()
        self.cmd_test = tk.StringVar()
        self.fvars = {}
        self.fmsg = {}
        self._selected = None
        self._busy = False

        # ---- header
        head = ttk.Frame(self, padding=(14, 10, 14, 2))
        head.pack(fill='x')
        self.chip_dev = ui.Pill(head, 'DEVELOPER MODE', 'warn')
        self.btn_dev = ttk.Button(head, text='Turn on developer mode...', command=self.toggle_dev)
        self.btn_dev.pack(side='right')
        self.chip_dev.pack(side='right', padx=8)
        if model.demo:
            ui.Pill(head, 'DEMO', 'warn').pack(side='right', padx=8)
        self.banner = tk.StringVar()
        ttk.Label(head, textvariable=self.banner, wraplength=ui.px(560), justify='left').pack(side='left')
        self.info = tk.StringVar()
        ttk.Label(self, textvariable=self.info, wraplength=ui.px(820), justify='left', style='Muted.TLabel', padding=(14, 0, 14, 4)).pack(fill='x')

        # ---- footer first (so it is never pushed out)
        foot = ttk.Frame(self, padding=(14, 6))
        foot.pack(side='bottom', fill='x')
        ttk.Label(self, textvariable=self.message, foreground=ui.C['bad'], wraplength=ui.px(820), justify='left',
                  padding=(14, 0)).pack(side='bottom', fill='x')
        self.btn_all = ttk.Button(foot, text='All procedure changes...', command=self.open_all)
        self.btn_all.pack(side='left')
        self.btn_close = ttk.Button(foot, text='Close', command=self.close)
        self.btn_apply = ttk.Button(foot, text='Apply', style='Accent.TButton', command=self.apply)
        self.btn_cancel = ttk.Button(foot, text='Cancel changes', command=self.cancel)
        self.btn_close.pack(side='right')
        self.btn_apply.pack(side='right', padx=8)
        self.btn_cancel.pack(side='right')
        sv = ttk.Frame(self, padding=(14, 4))
        sv.pack(side='bottom', fill='x')
        self.warn = tk.StringVar()
        ttk.Label(sv, textvariable=self.warn, wraplength=ui.px(820), justify='left', foreground=ui.C['warn']).pack(fill='x')
        self.summary = tk.StringVar()
        ttk.Label(sv, textvariable=self.summary, wraplength=ui.px(820), justify='left').pack(fill='x', pady=(2, 0))
        rr = ttk.Frame(sv)
        rr.pack(fill='x', pady=(4, 0))
        ttk.Label(rr, text='Reason for the change (required):').pack(side='left')
        self.reason_entry = ttk.Entry(rr, textvariable=self.reason, width=60)
        self.reason_entry.pack(side='left', padx=8, fill='x', expand=True)
        self.reason.trace_add('write', lambda *_: self._reason_typed())
        sc = ttk.Frame(sv)
        sc.pack(fill='x', pady=(4, 0))
        ttk.Label(sc, text='Applies to:').pack(side='left')
        self.scope_buttons = {}
        for value, label, available, why in model.scope_choices():
            b = ttk.Radiobutton(sc, text=label, value=value, variable=self.scope, command=self.scope_changed)
            b.pack(side='left', padx=(10, 0))
            if not available:
                b.configure(state='disabled')
            self.scope_buttons[value] = b
        self.chk_redo = ttk.Checkbutton(sv, text='Measure this point again after the change', variable=self.redo, command=self._redo_toggled)
        self.chk_redo.pack(anchor='w', pady=(4, 0))
        self.chk_ack = ttk.Checkbutton(sv, text='I understand this changes pass/fail for this point and is recorded in the audit trail.',
                                       variable=self.ack, command=self._ack_toggled)
        self.chk_ack.pack(anchor='w')

        # ---- body (scrolls: a point can have a few hundred commands)
        body = ttk.Frame(self, padding=(14, 2, 14, 2))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Instrument commands for this point, in the order they are sent', style='Bold.TLabel').pack(anchor='w')
        self.plan_note = tk.StringVar()
        ttk.Label(body, textvariable=self.plan_note, wraplength=ui.px(820), justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        holder = ttk.Frame(body)
        holder.pack(fill='both', expand=True, pady=(2, 4))
        self.tree = ttk.Treeview(holder, columns=[c[0] for c in self.COLUMNS], show='headings', height=9, selectmode='browse')
        for key, label, width in self.COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=ui.px(width), anchor='w')
        self.tree.tag_configure('changed', foreground=ui.C['warn'])
        self.tree.tag_configure('readonly', foreground=ui.C['muted'])
        self.tree.pack(side='left', fill='both', expand=True)
        bar = ttk.Scrollbar(holder, orient='vertical', command=self.tree.yview)
        bar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.on_select())

        ed = ttk.LabelFrame(body, text='Selected command', padding=8)
        ed.pack(fill='x')
        ttk.Label(ed, textvariable=self.cmd_info, wraplength=ui.px(800), justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        er = ttk.Frame(ed)
        er.pack(fill='x', pady=(4, 0))
        ttk.Label(er, text='Command (template):').pack(side='left')
        self.cmd_entry = ttk.Entry(er, textvariable=self.cmd_text, width=60)
        self.cmd_entry.pack(side='left', padx=8, fill='x', expand=True)
        self.btn_use = ttk.Button(er, text='Use for this point', command=self.use_command)
        self.btn_use.pack(side='left')
        self.btn_restore = ttk.Button(er, text='Restore default', command=self.restore_command)
        self.btn_restore.pack(side='left', padx=(6, 0))
        ttk.Label(ed, textvariable=self.cmd_preview, wraplength=ui.px(800), justify='left').pack(anchor='w', fill='x', pady=(4, 0))
        ttk.Label(ed, textvariable=self.cmd_test, style='Small.TLabel').pack(anchor='w')

        ex = ttk.LabelFrame(body, text='Add a command line for this point', padding=8)
        ex.pack(fill='x', pady=(6, 0))
        r1 = ttk.Frame(ex)
        r1.pack(fill='x')
        self.x_inst = tk.StringVar()
        self.x_phase = tk.StringVar(value='before')
        self.x_cmd, self.x_rb, self.x_exp = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.x_inst_box = ttk.Combobox(r1, textvariable=self.x_inst, values=[], width=14, state='readonly')
        self.x_inst_box.pack(side='left')
        ttk.Combobox(r1, textvariable=self.x_phase, values=['before', 'after'], width=8, state='readonly').pack(side='left', padx=6)
        ttk.Label(r1, text='the point\'s own commands:').pack(side='left')
        self.x_cmd_entry = ttk.Entry(r1, textvariable=self.x_cmd, width=34)
        self.x_cmd_entry.pack(side='left', padx=6, fill='x', expand=True)
        r2 = ttk.Frame(ex)
        r2.pack(fill='x', pady=(4, 0))
        ttk.Label(r2, text='Read back with (a setting needs this):').pack(side='left')
        ttk.Entry(r2, textvariable=self.x_rb, width=22).pack(side='left', padx=6)
        ttk.Label(r2, text='Expected reply:').pack(side='left')
        ttk.Entry(r2, textvariable=self.x_exp, width=14).pack(side='left', padx=6)
        self.btn_add = ttk.Button(r2, text='Add line', command=self.add_extra)
        self.btn_add.pack(side='left', padx=6)
        self.btn_rm = ttk.Button(r2, text='Remove selected line', command=self.remove_extra)
        self.btn_rm.pack(side='left')

        self.dev = ttk.LabelFrame(body, text='Point definition (developer mode)', padding=8)
        self.dev.pack(fill='x', pady=(6, 0))
        self.dev_grid = ttk.Frame(self.dev)
        self.dev_grid.pack(fill='x')
        self._build_fields()

        self.protocol('WM_DELETE_WINDOW', self.close)
        self.lock.on_change(lambda _s: self._safe(self.refresh))
        self.refresh()
        self.after(POLL_MS, self._poll)

    # ---- helpers -------------------------------------------------------------------------------------------------------------
    def _safe(self, fn):
        try:
            if self.winfo_exists():
                fn()
        except tk.TclError:
            pass

    def _poll(self):
        def tick():
            self.update_header()
            self.update_buttons()
            self.after(POLL_MS, self._poll)
        self._safe(tick)

    def _build_fields(self):
        for w in list(self.dev_grid.winfo_children()):
            w.destroy()
        self.fvars, self.fmsg, self.fentries, self.frestore = {}, {}, {}, {}
        for r, name in enumerate(n for n in PM.FIELD_ORDER if n in self.model.fields):
            f = self.model.fields[name]
            ttk.Label(self.dev_grid, text=f.label).grid(row=r, column=0, sticky='w', padx=(0, 8), pady=2)
            var = tk.StringVar(value=f.text)
            self.fvars[name] = var
            e = ttk.Entry(self.dev_grid, textvariable=var, width=44 if name == 'description' else 18)
            e.grid(row=r, column=1, sticky='w', pady=2)
            self.fentries[name] = e
            e.bind('<KeyRelease>', lambda _e, n=name: self.field_typed(n))
            e.bind('<FocusOut>', lambda _e, n=name: self.field_typed(n))
            b = ttk.Button(self.dev_grid, text='Restore default', command=lambda n=name: self.restore_field(n))
            b.grid(row=r, column=2, padx=8)
            self.frestore[name] = b
            msg = tk.StringVar()
            self.fmsg[name] = msg
            ttk.Label(self.dev_grid, textvariable=msg, wraplength=ui.px(360), justify='left', style='Small.TLabel').grid(row=r, column=3, sticky='w')

    # ---- refresh -------------------------------------------------------------------------------------------------------------
    def refresh(self):
        m = self.model
        self.update_header()
        self.update_scope_buttons()
        self.plan_note.set(m.plan_note)
        sel = self._selected
        self.tree.delete(*self.tree.get_children())
        for r in m.rows:
            cmd = r.shown_wire + ('   (not saved)' if r.staged or r.pending else '')
            self.tree.insert('', 'end', iid=str(r.seq), values=(r.seq, r.label, cmd, r.readback_wire, r.risk_text, r.status_text,
                                                              'changed' if r.changed else ''),
                             tags=('changed',) if r.changed else (() if r.editable else ('readonly',)))
        if sel is not None and self.tree.exists(str(sel)):
            self.tree.selection_set(str(sel))
        self.x_inst_box.configure(values=[f'{lab} ({d})' for d, lab in m.extra_drivers()])
        if not self.x_inst.get() and m.extra_drivers():
            self.x_inst.set(f'{m.extra_drivers()[0][1]} ({m.extra_drivers()[0][0]})')
        for name, f in m.fields.items():
            var = self.fvars.get(name)
            if var is not None and f.staged is None and var.get() != f.text:
                var.set(f.text)
        self.on_select()
        self.update_fields()
        self.update_footer()
        self.update_buttons()

    def update_scope_buttons(self):
        for value, _label, available, why in self.model.scope_choices():
            b = self.scope_buttons.get(value)
            if b is not None:
                b.configure(state='normal' if available else 'disabled')
        if self.scope.get() != self.model.scope:
            self.scope.set(self.model.scope)

    def update_header(self):
        m = self.model
        st = self.lock.state
        self.chip_dev.set('DEVELOPER MODE ON' if st == 'unlocked' else 'DEVELOPER MODE OFF', 'warn' if st == 'unlocked' else 'neutral')
        self.btn_dev.configure(text='Turn off developer mode' if st == 'unlocked' else 'Turn on developer mode...')
        self.banner.set(m.banner)
        why = m.blocked_reason
        if why:
            self.info.set(why + '  (read-only)')
        elif st != 'unlocked':
            self.info.set('You can type or change commands for this run only without a passphrase. Turn on developer mode to change the point\'s '
                          'limits, nominal, unit and description, or to save a change for this instrument or for all of this model. '
                          'The passphrase is the one used for all procedure changes.')
        else:
            self.info.set(m.effective_from_text() or m.pm.applies_from_text())

    def update_fields(self):
        m = self.model
        dev_ok = m.editable
        for name, f in m.fields.items():
            e = self.fentries.get(name)
            if e is None:
                continue
            e.configure(state='normal' if (f.editable and dev_ok) else 'disabled')
            self.frestore[name].configure(state='normal' if (f.editable and dev_ok and f.changed) else 'disabled')
            parts = []
            if f.problems:
                parts.append('; '.join(f.problems))
            else:
                if f.reason and not f.editable:
                    parts.append(f.reason)
                if f.changed:
                    parts.append(f'default: {f.factory}')
                if f.display and f.display != f.text:
                    parts.append(f'= {f.display}')
                if f.note:
                    parts.append(f.note)
            self.fmsg[name].set('   '.join(parts))
        self.dev.configure(text='Point definition (developer mode)' + ('' if dev_ok else ' - read-only'))

    def update_footer(self):
        m = self.model
        lines = [f'{what}: {old} -> {new}' if (old or new) else what for what, old, new in m.staged_summary()]
        self.summary.set('To be saved:\n  ' + '\n  '.join(lines) if lines else '')
        self.warn.set('\n'.join(m.warnings()))
        need_redo = m.redo_required
        if need_redo:
            self.redo.set(True)
        self.chk_redo.configure(state='disabled' if (need_redo or not m.has_reading) else 'normal')
        self.ack.set(m.acknowledged)
        self.chk_ack.configure(state='normal' if m.needs_acknowledgement else 'disabled')

    def update_buttons(self):
        m = self.model
        self.btn_apply.configure(state='normal' if (m.pm.drafts and not m.blockers()) else 'disabled')
        self.btn_cancel.configure(state='normal' if m.pm.drafts else 'disabled')
        ok = m.commands_editable                                    # typed commands for this run need no developer mode
        for b in (self.btn_add,):
            b.configure(state='normal' if ok else 'disabled')
        r = m.row(self._selected) if self._selected is not None else None
        self.btn_rm.configure(state='normal' if (r is not None and r.extra is not None and (ok or r.pending)) else 'disabled')
        self.btn_use.configure(state='normal' if (r is not None and r.editable) else 'disabled')
        self.btn_restore.configure(state='normal' if (r is not None and (r.pending or r.source == 'this point' or r.staged)) else 'disabled')
        self.cmd_entry.configure(state='normal' if (r is not None and r.editable) else 'disabled')

    # ---- selection -----------------------------------------------------------------------------------------------------------
    def on_select(self):
        sel = self.tree.selection()
        self._selected = int(sel[0]) if sel else self._selected
        r = self.model.row(self._selected) if self._selected is not None else None
        if r is None:
            self.cmd_info.set('Select a command above to see its details.')
            self.cmd_text.set('')
            self.cmd_preview.set('')
            self.cmd_test.set('')
            return
        bits = [f'{r.label} - {r.name or "command not in the table"}', f'risk: {r.risk_text}', f'status: {r.status_text}']
        if r.source != 'factory':
            bits.append(f'changed: {r.source}')
        if r.factory_template and r.factory_template != r.template:
            bits.append(f'manufacturer default: {r.factory_template}')
        if r.readback_wire:
            bits.append(f'read back with {r.readback_wire}')
        if not r.editable and r.reason:
            bits.append(r.reason)
        self.cmd_info.set('  |  '.join(bits))
        self.cmd_text.set(r.staged if r.staged is not None else (r.template or r.wire))
        self.cmd_preview.set(f'This point sends: {r.shown_wire}' + ('   (typed commands are UNVERIFIED)' if r.source != 'factory' or r.staged else ''))
        self.cmd_test.set('Test command: ' + self.model.test_info(r.seq)[1])
        if r.seq in self.model.command_problems:
            self.message.set('; '.join(self.model.command_problems[r.seq]))
        self.update_buttons()

    # ---- actions ---------------------------------------------------------------------------------------------------------------
    def toggle_dev(self):
        if self.lock.unlocked:
            self.lock.lock()
        else:
            UI.ask_unlock(self, self.lock)
        self.model.load(plan=False)
        self.refresh()

    def scope_changed(self):
        try:
            self.model.set_scope(self.scope.get())
            self.message.set('')
        except ValueError as ex:
            self.scope.set(self.model.scope)
            self.message.set(str(ex))
        self.update_footer()

    def _reason_typed(self):
        self.model.set_reason(self.reason.get())
        self.update_buttons()

    def _ack_toggled(self):
        self.model.acknowledge(self.ack.get())
        self.update_buttons()

    def _redo_toggled(self):
        self.model.set_redo(self.redo.get())

    def use_command(self):
        if self._selected is None:
            return
        probs = self.model.stage_command(self._selected, self.cmd_text.get())
        self.message.set('; '.join(probs))
        self.refresh()

    def restore_command(self):
        if self._selected is None:
            return
        probs = self.model.restore_command(self._selected)
        self.message.set('; '.join(probs))
        self.refresh()

    def add_extra(self):
        label = self.x_inst.get()
        driver = label[label.rfind('(') + 1:-1] if '(' in label else label
        probs = self.model.add_extra(driver, self.x_phase.get(), self.x_cmd.get(), self.x_rb.get(), self.x_exp.get())
        self.message.set('; '.join(probs))
        if not probs:
            self.x_cmd.set('')
            self.x_rb.set('')
            self.x_exp.set('')
        self.refresh()

    def remove_extra(self):
        if self._selected is None:
            return
        probs = self.model.remove_extra(self._selected)
        self.message.set('; '.join(probs))
        self.refresh()

    def field_typed(self, name):
        probs = self.model.stage_field(name, self.fvars[name].get())
        self.message.set('')
        self.update_fields()
        self.update_footer()
        self.update_buttons()
        return probs

    def restore_field(self, name):
        self.model.restore_field(name)
        self.fvars[name].set(self.model.fields[name].text)
        self.update_fields()
        self.update_footer()
        self.update_buttons()

    def apply(self):
        m = self.model
        if self._busy:
            return
        confirmed = False
        if m.scope != 'run':
            where = M.SCOPE_LABELS[m.scope].lower()
            if not messagebox.askyesno('Confirm wider change', f'This change will apply to {where} and stay in effect for later runs.\n\nContinue?', parent=self):
                return
            confirmed = True
        if m.redo_will_happen:
            if not messagebox.askyesno('Measure the point again', 'This point already has a reading. It will be measured again with the new settings and the '
                                       'old reading replaced by the new one. Nothing is retried automatically.\n\nSave the change and redo the point?', parent=self):
                return
        self._busy = True
        try:
            res = m.apply(confirmed=confirmed)
        except pm.OverrideError as ex:
            self.message.set(str(ex))
            return
        finally:
            self._busy = False
        self.message.set('; '.join(f'{k}: {msg}' for k, msg in res.errors))
        self.reason.set('')
        self._build_fields()
        self.refresh()

    def cancel(self):
        self.model.cancel()
        self.reason.set('')
        self.message.set('')
        self._build_fields()
        self.refresh()

    def open_all(self):
        """The older all-procedure window (settle times, skipping points, notes, driver-wide commands)."""
        try:
            UI.open_modify_window(self, self.app.pm_live_context(), self.lock)
        except Exception as exc:
            self.message.set(f'Could not open it ({type(exc).__name__}).')

    def close(self):
        if self.model.pm.drafts and not messagebox.askyesno('Discard changes?', 'There are changes that have not been applied. Close and discard them?', parent=self):
            return
        _open.pop((id(self.app), str(self.model.pid)), None)
        self.destroy()
