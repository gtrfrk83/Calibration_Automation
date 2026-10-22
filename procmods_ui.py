"""Tk widgets for 'Modify procedure' (thin: all behaviour lives in procmods_ui_model.py, which is unit-tested without tkinter).

    import procmods_ui
    win = procmods_ui.open_modify_window(parent, ctx)              # ctx = procmods_ui_model.Context(...)
    ctl = procmods_ui.attach_to_shell(shell, lambda: ctx)          # adds the 'Modify procedure' action + the MODIFIED / DEVELOPER MODE chips

The window is READ-ONLY (everything visible, nothing editable) until developer mode is unlocked with the passphrase, and while a run is
in progress.  It never prints or stores the passphrase.  NOTE: these widgets were written without a display; they have been imported and
constructed under tests/_tk_stub.py only, never looked at on screen.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import procmods as pm
import procmods_ui_model as M
import ui_theme as ui

POLL_MS = 1000
FILTERS = (('all', 'All'), ('modified', 'Modified'), ('unverified', 'Unverified'), ('locked', 'Locked'))

_shared_lock = None


def shared_lock(devmode=None) -> M.DevLock:
    """One DevLock per process, so every Modify window (and the Manager) shares the same unlocked session."""
    global _shared_lock
    if _shared_lock is None or (devmode is not None and _shared_lock.devmode is not devmode):
        _shared_lock = M.DevLock(devmode)
    return _shared_lock


# ------------------------------------------------------------------------------------------------------------ passphrase dialog
class UnlockDialog(tk.Toplevel):
    """Modal.  First use: choose + confirm a passphrase.  Otherwise: enter it.  Shows the lock-out delay.  `self.ok` tells the result."""

    def __init__(self, parent, lock: M.DevLock):
        super().__init__(parent)
        self.lock = lock
        self.ok = False
        first = lock.state == 'unset'
        self.title('Developer mode: set passphrase' if first else 'Developer mode: unlock')
        self.transient(parent)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=16)
        body.pack(fill='both', expand=True)
        intro = ('Developer mode protects procedure changes. Choose a passphrase (at least 8 characters). It is stored only as a hash on '
                 'this computer; if you forget it, delete ~/.calibration_suite/devmode.json to start again.') if first else \
            'Enter the developer-mode passphrase to change this procedure. Without it the window is read-only.'
        ttk.Label(body, text=intro, wraplength=ui.px(380), justify='left').pack(anchor='w', pady=(0, 10))
        self.pw = tk.StringVar()
        self.pw2 = tk.StringVar()
        ttk.Label(body, text='Passphrase').pack(anchor='w')
        self.e1 = ttk.Entry(body, textvariable=self.pw, show='*', width=34)
        self.e1.pack(anchor='w', pady=(0, 6))
        self.e2 = None
        if first:
            ttk.Label(body, text='Repeat passphrase').pack(anchor='w')
            self.e2 = ttk.Entry(body, textvariable=self.pw2, show='*', width=34)
            self.e2.pack(anchor='w', pady=(0, 6))
        self.msg = tk.StringVar()
        ttk.Label(body, textvariable=self.msg, wraplength=ui.px(380), foreground=ui.C['bad']).pack(anchor='w', pady=(4, 8))
        row = ttk.Frame(body)
        row.pack(fill='x')
        ttk.Button(row, text='Cancel', command=self.destroy).pack(side='right')
        self.go = ttk.Button(row, text='Set passphrase' if first else 'Unlock', style='Accent.TButton', command=self.submit)
        self.go.pack(side='right', padx=8)
        self.bind('<Return>', lambda _e: self.submit())
        self.bind('<Escape>', lambda _e: self.destroy())
        self._tick()
        self.e1.focus_set()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _tick(self):
        """Counts the lock-out down on screen."""
        text = self.lock.lockout_text()
        if text:
            self.msg.set(text)
        self.go.configure(state='disabled' if text else 'normal')
        if text:
            self.after(500, self._tick)

    def submit(self):
        if self.lock.state == 'unset':
            res = self.lock.first_use(self.pw.get(), self.pw2.get())
        else:
            res = self.lock.unlock(self.pw.get())
        self.pw.set('')                                        # never keep it around
        self.pw2.set('')
        if res.ok:
            self.ok = True
            self.destroy()
        else:
            self.msg.set(res.message)
            self._tick()


def ask_unlock(parent, lock: M.DevLock) -> bool:
    if lock.unlocked:
        return True
    dlg = UnlockDialog(parent, lock)
    parent.wait_window(dlg)
    return dlg.ok


# ------------------------------------------------------------------------------------------------------------ list + editor tabs
class _Tab(ttk.Frame):
    """A searchable list on the left, an editor pane on the right.  Subclasses fill `rows()` and `build_editor()`."""
    kind = ''
    columns = ('flags', 'name')
    heads = ('', 'Item')
    widths = (70, 300)

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.model = win.model
        self.selected = None
        self._rows = {}
        panes = ttk.Frame(self)
        panes.pack(fill='both', expand=True)
        panes.columnconfigure(0, weight=1, uniform='p')
        panes.columnconfigure(1, weight=2, uniform='p')
        panes.rowconfigure(0, weight=1)
        self.tree = ui.make_table(panes, self.columns, self.heads, self.widths, anchors={'name': 'w'}, height=14, pack=False,
                                  stretch={'flags': False})
        self.tree.master.grid(row=0, column=0, sticky='nsew')
        self.tree.tag_configure('modified', foreground=ui.C['warn'])
        self.tree.tag_configure('locked', foreground=ui.C['faint'])
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.on_select())
        self.editor = ttk.Frame(panes, padding=(14, 4, 4, 4))
        self.editor.grid(row=0, column=1, sticky='nsew')
        self.build_editor()

    # -- to override
    def rows(self, flt, search):
        return []

    def build_editor(self):
        pass

    def show(self, row):
        pass

    # -- shared
    def reload(self):
        keep = self.selected
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for r in self.rows(self.win.filter.get(), self.win.search.get().strip()):
            iid = r.get('target') or r['key']
            tags = ('modified',) if r.get('modified') or r.get('draft') else ('locked',) if r.get('locked') else ()
            self.tree.insert('', 'end', iid=iid, values=(self.flag_text(r), self.name_text(r)), tags=tags)
            self._rows[iid] = r
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        else:
            self.selected = None
            self.show(None)

    @staticmethod
    def flag_text(r):
        sym = {'M': '[M]', '!': '[!]', 'S': '[stale]', 'lock': '🔒'}
        flags = list(r.get('badges') or [])
        if r.get('draft'):
            flags.insert(0, 'M')
        return ' '.join(sym[f] for f in flags)

    @staticmethod
    def name_text(r):
        return r.get('name') or r['key']

    def on_select(self):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None
        self.show(self._rows.get(self.selected))

    def set_enabled(self, widgets, enabled):
        for w in widgets:
            try:
                w.configure(state='normal' if enabled else 'disabled')
            except tk.TclError:
                pass

    def reason_row(self, parent):
        ttk.Label(parent, text='Reason for the change (required)').pack(anchor='w', pady=(10, 0))
        self.reason = tk.StringVar()
        e = ttk.Entry(parent, textvariable=self.reason)
        e.pack(fill='x')
        e.bind('<KeyRelease>', lambda _e: self.model.set_reason(self.kind, self.selected, self.reason.get()) if self.selected else None)
        return e

    def buttons_row(self, parent, extra=()):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(10, 0))
        self.btn_undo = ttk.Button(row, text='Undo', command=self.undo)
        self.btn_reset = ttk.Button(row, text='Reset to factory', command=self.reset)
        for b in (*extra, self.btn_undo, self.btn_reset):
            b.pack(side='left', padx=(0, 8))
        return row

    def undo(self):
        if self.selected:
            self.model.undo(self.kind, self.selected)
            self.win.refresh()

    def reset(self):
        if self.selected:
            self.model.stage_reset(self.kind, self.selected)
            self.win.refresh()

    def problems(self, probs):
        self.win.set_message('; '.join(probs) if probs else '')


def _heading(parent, text):
    ttk.Label(parent, text=text, style='Section.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w')


def _field(parent, label):
    ttk.Label(parent, text=label, style='Small.TLabel').pack(anchor='w', pady=(8, 0))
    var = tk.StringVar()
    ttk.Label(parent, textvariable=var, wraplength=ui.px(420), justify='left').pack(anchor='w')
    return var


class CommandsTab(_Tab):
    kind = 'command'
    columns = ('flags', 'name', 'key')
    heads = ('', 'Command', 'Template')
    widths = (70, 190, 190)

    def rows(self, flt, search):
        return self.model.commands(flt, search)

    def name_text(self, r):
        return r['name']

    def reload(self):
        super().reload()
        for iid, r in self._rows.items():
            self.tree.set(iid, 'key', r['current'])

    def build_editor(self):
        e = self.editor
        self.title = tk.StringVar(value='Select a command')
        ttk.Label(e, textvariable=self.title, style='Section.TLabel').pack(anchor='w')
        self.meta = _field(e, 'Kind / risk / source')
        self.factory = _field(e, 'Factory')
        ttk.Label(e, text='Current (editable)', style='Small.TLabel').pack(anchor='w', pady=(8, 0))
        self.text = tk.StringVar()
        self.entry = ttk.Entry(e, textvariable=self.text)
        self.entry.pack(fill='x')
        self.entry.bind('<KeyRelease>', lambda _e: self.typed())
        self.placeholders = _field(e, 'Placeholders')
        self.paired = _field(e, 'Paired check')
        self.status = tk.StringVar()
        ttk.Label(e, textvariable=self.status, wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(8, 0))
        self.lockmsg = tk.StringVar()
        ttk.Label(e, textvariable=self.lockmsg, foreground=ui.C['warn'], wraplength=ui.px(420), justify='left').pack(anchor='w')
        self.reason_entry = self.reason_row(e)
        self.btn_test = ttk.Button(e, text='Test this command', command=self.test)
        self.buttons_row(e, extra=(self.btn_test,))
        self.test_out = tk.StringVar()
        ttk.Label(e, textvariable=self.test_out, wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(8, 0))
        ttk.Label(e, text=M.TEST_NOTE, style='Small.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(8, 0))

    def show(self, row):
        d = self.model.command_detail(row['target']) if row else {'found': False}
        if not d['found']:
            self.title.set('Select a command')
            for v in (self.meta, self.factory, self.text, self.placeholders, self.paired, self.status, self.lockmsg, self.test_out):
                v.set('')
            self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset, self.btn_test], False)
            return
        badges = ('   ' + ' '.join(self.flag_text({'badges': d['badges']}).split())) if d['badges'] else ''
        self.title.set(d['name'] + badges)
        self.meta.set(f'{d["kind"]} / {d["risk"]} / {"verified" if d["verified"] else "UNVERIFIED in the manual"}' + (f' / {d["ref"]}' if d['ref'] else ''))
        self.factory.set(d['factory'])
        self.text.set(d['current'])
        self.placeholders.set(', '.join(f'{{{n}}}{" (required)" if p["required"] else ""}' for n, p in d['placeholders'].items()) or 'none')
        self.paired.set((d['paired'] + ' (read back)') if d['paired'] else 'none')
        self.lockmsg.set(d['lock_reason'] if not d['editable'] else '')
        self.reason.set(d['reason'])
        self.status.set(d['status'])
        self.test_out.set(self._test_text(d['test_result']))
        self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], d['editable'])
        self.set_enabled([self.btn_test], d['can_test'])
        self.btn_test.configure(text='Test this command' if d['can_test'] else 'Test unavailable')
        self.win.tip(self.btn_test, d['test_reason'])

    @staticmethod
    def _test_text(res):
        if not res:
            return ''
        if res.get('message'):
            return res['message']
        return f'Sent: {res.get("sent", "")}\nReply: {res.get("reply", "")}\nError queue: {res.get("errors", "")}'

    def typed(self):
        if not self.selected:
            return
        try:
            chk = self.model.stage_command(self.selected, self.text.get())
        except pm.OverrideError as ex:
            self.status.set(str(ex))
            return
        self.status.set(self.model.command_status(self.selected, self.text.get()))
        self.win.update_buttons()

    def test(self):
        if not self.selected:
            return
        self.btn_test.configure(state='disabled')           # one press, one test; nothing is retried automatically
        res = self.model.test_command(self.selected, self.text.get())
        self.test_out.set(self._test_text(res))
        self.status.set(self.model.command_status(self.selected, self.text.get()))
        self.after(300, lambda: self.show(self._rows.get(self.selected)))


class SettingsTab(_Tab):
    kind = 'param'
    columns = ('flags', 'name', 'cur')
    heads = ('', 'Setting', 'Value')
    widths = (70, 220, 120)

    def rows(self, flt, search):
        return self.model.settings(flt, search)

    def reload(self):
        super().reload()
        for iid, r in self._rows.items():
            self.tree.set(iid, 'cur', f'{r["current"]} {r["unit"]}'.strip())

    def build_editor(self):
        e = self.editor
        self.title = tk.StringVar(value='Select a setting')
        ttk.Label(e, textvariable=self.title, style='Section.TLabel').pack(anchor='w')
        self.factory = _field(e, 'Factory')
        self.cond = tk.StringVar()
        ttk.Label(e, textvariable=self.cond, foreground=ui.C['warn'], wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(6, 0))
        ttk.Label(e, text='Value (editable)', style='Small.TLabel').pack(anchor='w', pady=(8, 0))
        self.value = tk.StringVar()
        self.entry = ttk.Entry(e, textvariable=self.value)
        self.entry.pack(fill='x')
        self.entry.bind('<KeyRelease>', lambda _e: self.typed())
        self.reason_entry = self.reason_row(e)
        self.buttons_row(e)

    def show(self, row):
        if not row:
            self.title.set('Select a setting')
            self.factory.set('')
            self.value.set('')
            self.cond.set('')
            self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], False)
            return
        self.title.set(row['name'] + ('   [M]' if row['modified'] else ''))
        self.factory.set(f'{row["factory"]} {row["unit"]}'.strip())
        self.value.set(str(row['current']))
        self.cond.set('Changes the test conditions: the report states they differ from the manufacturer\'s procedure.' if row['affects_conditions'] else '')
        self.reason.set(self.model.reasons.get(('param', row['key']), ''))
        self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable)

    def typed(self):
        if not self.selected:
            return
        raw = self.value.get().strip()
        try:
            val = float(raw) if raw.replace('.', '', 1).replace('-', '', 1).replace('e', '', 1).isdigit() else raw
            if isinstance(val, float) and val == int(val) and '.' not in raw:
                val = int(val)
            self.problems(self.model.stage_param(self.selected, val))
        except pm.OverrideError as ex:
            self.win.set_message(str(ex))
        self.win.update_buttons()


class PointsTab(_Tab):
    kind = 'point'
    columns = ('flags', 'name', 'state')
    heads = ('', 'Test point', 'State')
    widths = (70, 300, 90)

    def rows(self, flt, search):
        return self.model.points(flt, search)

    def reload(self):
        super().reload()
        for iid, r in self._rows.items():
            self.tree.set(iid, 'state', 'skipped' if r['skip'] else r['state'])

    def build_editor(self):
        e = self.editor
        self.title = tk.StringVar(value='Select a test point')
        ttk.Label(e, textvariable=self.title, style='Section.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w')
        ttk.Label(e, text='A skipped point is not measured and is listed in the report with your reason. Limits and pass/fail are not '
                          'changed here (see Tolerances).', style='Small.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(6, 0))
        self.skip = tk.BooleanVar(value=False)
        self.chk = ttk.Checkbutton(e, text='Skip this point', variable=self.skip, command=self.toggled)
        self.chk.pack(anchor='w', pady=(10, 0))
        self.reason_entry = self.reason_row(e)
        self.buttons_row(e)

    def show(self, row):
        if not row:
            self.title.set('Select a test point')
            self.set_enabled([self.chk, self.reason_entry, self.btn_undo, self.btn_reset], False)
            return
        self.title.set(row['name'])
        self.skip.set(bool(row['skip']) or ('point', row['key']) in self.model.drafts)
        self.reason.set(self.model.reasons.get(('point', row['key']), ''))
        self.set_enabled([self.chk, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable)

    def toggled(self):
        if self.selected:
            try:
                self.problems(self.model.stage_skip(self.selected, self.skip.get()))
            except pm.OverrideError as ex:
                self.win.set_message(str(ex))
            self.win.update_buttons()


class TextTab(_Tab):
    kind = 'text'

    def rows(self, flt, search):
        return self.model.texts(flt, search)

    def build_editor(self):
        e = self.editor
        self.title = tk.StringVar(value='Select a text item')
        ttk.Label(e, textvariable=self.title, style='Section.TLabel').pack(anchor='w')
        self.factory = _field(e, 'Factory')
        ttk.Label(e, text='Current (editable)', style='Small.TLabel').pack(anchor='w', pady=(8, 0))
        self.box = tk.Text(e, height=6, wrap='word')
        self.box.pack(fill='x')
        self.box.bind('<KeyRelease>', lambda _e: self.typed())
        self.lockmsg = tk.StringVar()
        ttk.Label(e, textvariable=self.lockmsg, foreground=ui.C['warn']).pack(anchor='w')
        self.reason_entry = self.reason_row(e)
        self.buttons_row(e)

    def show(self, row):
        self.box.configure(state='normal')
        self.box.delete('1.0', 'end')
        if not row:
            self.title.set('Select a text item')
            self.factory.set('')
            self.lockmsg.set('')
            self.set_enabled([self.box, self.reason_entry, self.btn_undo, self.btn_reset], False)
            return
        self.title.set(row['name'] + ('   [M]' if row['modified'] else ''))
        self.factory.set(row['factory'])
        d = self.model.drafts.get(('text', row['key']))
        self.box.insert('1.0', d.value['text'] if d else row['current'])
        self.lockmsg.set(row['lock_reason'])
        self.reason.set(self.model.reasons.get(('text', row['key']), ''))
        self.set_enabled([self.box, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable and not row['locked'])

    def typed(self):
        if self.selected:
            try:
                self.problems(self.model.stage_text(self.selected, self.box.get('1.0', 'end').rstrip('\n')))
            except pm.OverrideError as ex:
                self.win.set_message(str(ex))
            self.win.update_buttons()


class TolerancesTab(_Tab):
    kind = 'limit'
    columns = ('flags', 'name', 'factory', 'cur')
    heads = ('', 'Test point', 'Manufacturer', 'Used')
    widths = (60, 240, 120, 120)

    def rows(self, flt, search):
        return self.model.tolerances(flt, search)

    def reload(self):
        super().reload()
        for iid, r in self._rows.items():
            self.tree.set(iid, 'factory', r['factory'])
            self.tree.set(iid, 'cur', r['current'] + (' TAMPERED' if r.get('tampered') else ''))

    def build_editor(self):
        e = self.editor
        self.title = tk.StringVar(value='Select a test point')
        ttk.Label(e, textvariable=self.title, style='Section.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w')
        self.factory = _field(e, 'Manufacturer tolerance (read-only)')
        ttk.Label(e, text='Pass/fail is judged against the tolerance used, and the report says the tolerance was modified. Uncertainty '
                          'is not changed.', style='Small.TLabel', wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(6, 0))
        self.v_a, self.v_b = tk.StringVar(), tk.StringVar()
        self.lab_a = ttk.Label(e, text='', style='Small.TLabel')
        self.lab_a.pack(anchor='w', pady=(8, 0))
        self.ent_a = ttk.Entry(e, textvariable=self.v_a)
        self.ent_a.pack(fill='x')
        self.lab_b = ttk.Label(e, text='', style='Small.TLabel')
        self.lab_b.pack(anchor='w', pady=(8, 0))
        self.ent_b = ttk.Entry(e, textvariable=self.v_b)
        self.ent_b.pack(fill='x')
        for w in (self.ent_a, self.ent_b):
            w.bind('<KeyRelease>', lambda _e: self.typed())
        self.reason_entry = self.reason_row(e)
        self.buttons_row(e)

    def show(self, row):
        widgets = [self.ent_a, self.ent_b, self.reason_entry, self.btn_undo, self.btn_reset]
        if not row:
            self.title.set('Select a test point')
            self.factory.set('')
            self.set_enabled(widgets, False)
            return
        p = next(p for p, k in zip(self.model.ctx.points, pm.point_keys(self.model.ctx.points)) if k == row['key'])
        fac = pm.limit_factory(p)
        cur = self.model.oset.limit_override(row['key'])
        cv = (cur or {}).get('value', {})
        self.title.set(row['name'] + ('   [M]' if row['modified'] else '') + ('   TAMPERED: not applied' if row.get('tampered') else ''))
        self.factory.set(row['factory'])
        if fac['mode'] == 'error':
            self.lab_a.configure(text=f'+/- error ({row["unit"]})')
            self.v_a.set(str(cv.get('error', fac['error'])))
            self.lab_b.configure(text='')
            self.v_b.set('')
            self.set_enabled([self.ent_b], False)
            enable = [self.ent_a]
        else:
            self.lab_a.configure(text=f'Low limit ({row["unit"]})')
            self.lab_b.configure(text=f'High limit ({row["unit"]})')
            self.v_a.set(str(cv.get('low', fac['low'])))
            self.v_b.set(str(cv.get('high', fac['high'])))
            enable = [self.ent_a, self.ent_b]
        self.reason.set(self.model.reasons.get(('limit', row['key']), ''))
        self.set_enabled(widgets, False)
        if self.model.editable:
            self.set_enabled(enable + [self.reason_entry, self.btn_undo, self.btn_reset], True)

    def typed(self):
        if not self.selected:
            return
        row = self._rows[self.selected]
        try:
            if row['mode'] == 'error':
                probs = self.model.stage_limit(self.selected, error=self.v_a.get().strip())
            else:
                probs = self.model.stage_limit(self.selected, low=self.v_a.get().strip(), high=self.v_b.get().strip())
            self.problems(probs)
        except pm.OverrideError as ex:
            self.win.set_message(str(ex))
        self.win.update_buttons()


class ChangesTab(_Tab):
    kind = ''
    columns = ('flags', 'name', 'from', 'to', 'scope', 'status')
    heads = ('', 'Item', 'Factory', 'Current', 'Applies to', 'Status')
    widths = (60, 170, 150, 150, 110, 80)

    def __init__(self, parent, win):
        ttk.Frame.__init__(self, parent)
        self.win = win
        self.model = win.model
        self.selected = None
        self._rows = {}
        self.tree = ui.make_table(self, self.columns, self.heads, self.widths, anchors={'name': 'w', 'from': 'w', 'to': 'w', 'scope': 'w'},
                                  height=12, pack=True, stretch={'flags': False})
        self.tree.tag_configure('modified', foreground=ui.C['warn'])
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.on_select())
        self.detail = tk.StringVar()
        ttk.Label(self, textvariable=self.detail, wraplength=ui.px(760), justify='left').pack(anchor='w', pady=(8, 0))
        row = ttk.Frame(self)
        row.pack(fill='x', pady=(6, 0))
        self.btn_reset = ttk.Button(row, text='Reset selected', command=self.reset_selected)
        self.btn_all = ttk.Button(row, text='Reset all to factory...', command=win.reset_all)
        self.btn_reset.pack(side='left', padx=(0, 8))
        self.btn_all.pack(side='left')

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        needle = self.win.search.get().strip().casefold()
        for r in self.model.changes():
            if needle and needle not in f'{r["label"]} {r["factory"]} {r["current"]} {r["reason"]}'.casefold():
                continue
            self.tree.insert('', 'end', iid=r['uid'], tags=('modified',) if r['status'] == 'active' else (),
                             values=(self.flag_text(r), r['label'], r['factory'], r['current'], r['applies_to'],
                                     'TAMPERED' if r['tampered'] else r['status']))
            self._rows[r['uid']] = r
        self.set_enabled([self.btn_reset, self.btn_all], self.model.editable)

    def on_select(self):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None
        r = self._rows.get(self.selected)
        if not r:
            self.detail.set('')
            return
        self.detail.set(f'{r["label"]}: {r["factory"]}  ->  {r["current"]}\nReason: {r["reason"]}   By: {r["author"]}   {r["at"]}'
                        + (f'   Imported by {r["imported_by"]}' if r.get('imported_by') else '')
                        + ('\nUNVERIFIED: not tested on the instrument.' if r['unverified'] else ''))

    def reset_selected(self):
        r = self._rows.get(self.selected)
        if r:
            self.model.stage_reset(r['kind'], r['target'])
            self.win.refresh()
            self.win.set_message('Reset staged. Give a reason, then press Apply.')


TAB_CLASSES = {'Commands': CommandsTab, 'Settings': SettingsTab, 'Points': PointsTab, 'Text': TextTab, 'Tolerances': TolerancesTab,
               'Changes': ChangesTab}


# ------------------------------------------------------------------------------------------------------------ the window
class ModifyWindow(tk.Toplevel):
    def __init__(self, parent, model: M.ProcModsModel, on_change=None):
        super().__init__(parent)
        self.model = model
        self.lock = model.lock
        self.on_change = on_change
        ctx = model.ctx
        self.title(('Edit procedure' if model.live_mode else 'Modify procedure') + f': {ctx.title}'
                   + (f' - asset {ctx.asset_id}' if ctx.asset_id else '') + (' [DEMO]' if ctx.demo else ''))
        self.geometry(f'{ui.px(1000)}x{ui.px(660)}')
        self.filter = tk.StringVar(value='all')
        self.search = tk.StringVar()
        self.scope = tk.StringVar(value=model.scope)
        self.message = tk.StringVar()
        self.tabs = {}
        self._tips = {}

        head = ttk.Frame(self, padding=(14, 10, 14, 4))
        head.pack(fill='x')
        self.chip_dev = ui.Pill(head, 'DEVELOPER MODE', 'warn')
        self.chip_mod = ui.Pill(head, '', 'warn')
        self.btn_lock = ttk.Button(head, text='Unlock...', command=self.toggle_lock)
        self.btn_lock.pack(side='right')
        self.chip_dev.pack(side='right', padx=8)
        self.chip_mod.pack(side='right', padx=8)
        self.banner = tk.StringVar()
        ttk.Label(head, textvariable=self.banner, wraplength=ui.px(560), justify='left').pack(side='left')
        self.info = tk.StringVar()                              # live mode: which point the saved changes start at (not an error: not red)
        ttk.Label(self, textvariable=self.info, wraplength=ui.px(940), justify='left', padding=(14, 0, 14, 4)).pack(fill='x')

        bar = ttk.Frame(self, padding=(14, 2, 14, 4))
        bar.pack(fill='x')
        ttk.Label(bar, text='Scope for new edits:').pack(side='left')
        for value in pm.SCOPES:
            label = M.SCOPE_LABELS[value] + (f' ({ctx.asset_id})' if value == 'asset' and ctx.asset_id else f' ({ctx.model})' if value == 'model' and ctx.model else '')
            ttk.Radiobutton(bar, text=label, value=value, variable=self.scope, command=self.scope_changed).pack(side='left', padx=(10, 0))
        bar2 = ttk.Frame(self, padding=(14, 2, 14, 6))
        bar2.pack(fill='x')
        e = ttk.Entry(bar2, textvariable=self.search, width=30)
        e.pack(side='left')
        e.bind('<KeyRelease>', lambda _e: self.refresh())
        for value, label in FILTERS:
            ttk.Radiobutton(bar2, text=label, value=value, variable=self.filter, command=self.refresh).pack(side='left', padx=(10, 0))

        foot = ttk.Frame(self, padding=(14, 8))
        foot.pack(side='bottom', fill='x')
        ttk.Label(self, textvariable=self.message, foreground=ui.C['bad'], wraplength=ui.px(940), justify='left',
                  padding=(14, 0)).pack(side='bottom', fill='x')
        self.btn_reset_all = ttk.Button(foot, text='Reset all to factory...', command=self.reset_all)
        self.btn_import = ttk.Button(foot, text='Import...', command=self.do_import)
        self.btn_export = ttk.Button(foot, text='Export...', command=self.do_export)
        for b in (self.btn_reset_all, self.btn_import, self.btn_export):
            b.pack(side='left', padx=(0, 8))
        self.btn_close = ttk.Button(foot, text='Close', command=self.close)
        self.btn_apply = ttk.Button(foot, text='Apply', style='Accent.TButton', command=self.apply)
        self.btn_cancel = ttk.Button(foot, text='Cancel changes', command=self.cancel)
        self.btn_close.pack(side='right')
        self.btn_apply.pack(side='right', padx=8)
        self.btn_cancel.pack(side='right')

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=14, pady=(0, 4))
        for name in model.visible_tabs():
            tab = TAB_CLASSES[name](self.nb, self)
            self.tabs[name] = tab
            self.nb.add(tab, text=name)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.lock.on_change(lambda _s: self._safe(self.refresh))
        self.refresh()
        self.after(POLL_MS, self._poll)

    # -- helpers
    def _safe(self, fn):
        try:
            if self.winfo_exists():
                fn()
        except tk.TclError:
            pass

    def tip(self, widget, text):
        self._tips[str(widget)] = text

    def set_message(self, text):
        self.message.set(text)

    def scope_changed(self):
        try:
            self.model.set_scope(self.scope.get())
            self.message.set('')
        except ValueError as ex:
            self.scope.set(self.model.scope)
            self.message.set(str(ex))

    def _poll(self):
        if not self.winfo_exists():
            return
        before = self.lock.state
        self.lock.poll()
        if before != self.lock.state or self.lock.state in ('unlocked', 'lockout'):
            self.update_header()
        elif self.model.live_mode:
            self.update_info()                                 # the run moves on: keep 'starts at point N' current
        self.after(POLL_MS, self._poll)

    # -- refresh
    def update_header(self):
        m = self.model
        unlocked = self.lock.unlocked
        self.btn_lock.configure(text='Lock now' if unlocked else 'Unlock...')
        self.update_info()
        (self.chip_dev.pack(side='right', padx=8) if unlocked else self.chip_dev.pack_forget())
        n = m.modified_count()
        self.chip_mod.set(M.chip_text(n), 'warn')
        (self.chip_mod.pack(side='right', padx=8) if n else self.chip_mod.pack_forget())
        if m.editable:
            mins = int(self.lock.remaining_s // 60)
            self.banner.set(f'Developer mode unlocked; locks after 15 minutes idle ({mins} min left). Changes are staged until you press Apply.')
        else:
            extra = ('  ' + self.lock.lockout_text()) if self.lock.state == 'lockout' else ''
            self.banner.set(m.read_only_reason + extra + '  Saved changes still apply when you run; "Run factory" is offered at the start of a run.')
        self.update_buttons()

    def update_info(self):
        """Live mode: say which point a saved change applies from, whether anything saved is still waiting, and what demo mode does."""
        m = self.model
        if not m.live_mode:
            self.info.set('')
            return
        lines = [m.applies_from_text()]
        waiting = m.ctx.live.pending()
        if waiting:
            lines.append('Saved, not in effect yet: ' + '; '.join(waiting))
        if m.ctx.demo:
            lines.append('DEMO: edits made here apply to this demo run only and are marked demo. Nothing is saved for later runs.')
        self.info.set('\n'.join(lines))

    def update_buttons(self):
        m = self.model
        ed = m.editable
        for b, on in ((self.btn_apply, ed and m.dirty), (self.btn_cancel, m.dirty), (self.btn_reset_all, ed),
                      (self.btn_import, ed), (self.btn_export, ed)):
            b.configure(state='normal' if on else 'disabled')
        counts = m.tab_counts()
        for name, tab in self.tabs.items():
            n = counts.get(name, 0)
            self.nb.tab(tab, text=f'{name} ({n})' if n and name in ('Changes', 'Tolerances') else name)

    def refresh(self):
        self.model.refresh()
        for tab in self.tabs.values():
            tab.reload()
        self.update_header()
        if self.on_change:
            self.on_change(self.model)

    # -- actions
    def toggle_lock(self):
        if self.lock.unlocked:
            self.lock.lock()
        else:
            ask_unlock(self, self.lock)
        self.refresh()

    def _reasons_ok(self):
        miss = self.model.missing_reasons()
        if miss:
            self.message.set('A reason is required for every change: ' + ', '.join(miss))
        return not miss

    def apply(self):
        m = self.model
        if not self._reasons_ok():
            return
        confirmed = False
        need = m.scope_confirmation_needed()
        if need:
            where = M.SCOPE_LABELS[m.scope].lower()
            lines = '\n'.join(f'  - {p["label"]}: {p["reason"]}' for p in need)
            if not messagebox.askyesno('Confirm wider change', f'{len(need)} change(s) will apply to {where} and stay in effect for later '
                                       f'runs:\n{lines}\n\nContinue?', parent=self):
                return
            confirmed = True
        redo = []
        if m.limit_blocked():
            self.message.set(m.limit_blocked())
            return
        need = m.limit_redo_needed()
        if need:
            names = ', '.join(lab for _k, lab in need)
            if not messagebox.askyesno('Tolerance change needs a redo', f'The tolerance of {names} concerns a point that already has a reading '
                                       'or is in progress. A tolerance can only be changed for a point that is measured again against it, '
                                       'and the reading taken now will be replaced by the new one.\n\nSave the change and redo the point?', parent=self):
                self.message.set('Not applied: the tolerance of a point that already has a reading changes only together with a redo.')
                return
            redo = [k for k, _lab in need]
        try:
            res = m.apply(confirmed=confirmed, redo=redo)
        except pm.OverrideError as ex:
            self.message.set(str(ex))
            return
        self.message.set('; '.join(f'{k}: {msg}' for k, msg in res.errors))
        if m.live_mode and res.done:
            offer = m.redo_offer()
            if offer and offer['key'] not in redo and messagebox.askyesno(
                    'Measure this point again?', f'Saved. Point {offer["id"]} ({offer["desc"]}) is in progress and keeps the settings it started '
                    f'with; the change starts at the next point.\n\nMeasure point {offer["id"]} again with the new settings after it finishes? '
                    'The reading from the old settings will be replaced by the new one. Nothing is retried automatically.', parent=self):
                m.ctx.live.request_redo([offer['key']])
        self.refresh()

    def cancel(self):
        self.model.cancel()
        self.message.set('')
        self.refresh()

    def reset_all(self):
        if not self.model.editable:
            return
        if not messagebox.askyesno('Reset all to factory', 'Stage the removal of every modification in effect? You still give a reason '
                                   'and press Apply. Saved rows are kept in the audit trail.', parent=self):
            return
        n = self.model.stage_reset_all()
        if n:
            reason = simpledialog.askstring('Reason', 'Reason for resetting to factory (required):', parent=self)
            if not (reason or '').strip():
                self.model.cancel()
                self.message.set('Cancelled: a reason is required.')
                self.refresh()
                return
            for it in self.model.pending():
                self.model.set_reason(it['kind'], it['target'], reason.strip())
        self.message.set(f'{n} reset(s) staged. Press Apply to save them.' if n else 'Nothing to reset.')
        self.refresh()

    def do_export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.calov.json', filetypes=[('Override set', '*.calov.json *.json')])
        if not path:
            return
        try:
            notes = self.model.export(path)
            self.message.set('Exported.' + ('  ' + '; '.join(notes) if notes else ''))
        except (pm.OverrideError, OSError) as ex:
            self.message.set(str(ex))

    def do_import(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Override set', '*.calov.json *.json')])
        if not path:
            return
        prev = self.model.import_preview(path)
        if not prev['ok']:
            self.message.set('; '.join(prev['problems']))
            return
        lines = self.model.preview_lines(prev)
        accept = [l['index'] for l in lines if l['accept']]
        text = '\n'.join(f'  {"+" if l["accept"] else "-"} {l["kind"]} {l["target"]} ({l["state"]})' + (f': {l["problems"][0]}' if l['problems'] else '')
                         for l in lines) or '  (empty)'
        if not accept or not messagebox.askyesno('Import override set', f'These entries will be imported (+) or skipped (-). Imported commands '
                                                 f'are UNVERIFIED here.\n{text}\n\nImport the {len(accept)} marked +?', parent=self):
            return
        try:
            created = self.model.import_apply(prev, accept)
            self.message.set(f'Imported {len(created)} entr{"y" if len(created) == 1 else "ies"}.')
        except pm.OverrideError as ex:
            self.message.set(str(ex))
        self.refresh()

    def close(self):
        if self.model.dirty and not messagebox.askyesno('Unsaved changes', 'Discard the staged changes?', parent=self):
            return
        self.model.cancel()
        self.destroy()


def open_modify_window(parent, ctx: M.Context, lock: M.DevLock | None = None, on_change=None):
    """Open the window.  It starts read-only; the technician (or developer) presses Unlock to edit."""
    lock = lock or shared_lock()
    model = M.ProcModsModel(ctx, lock)
    return ModifyWindow(parent, model, on_change=on_change)


# ------------------------------------------------------------------------------------------------------------ shell hookup
class ShellHook:
    """What attach_to_shell returns: call refresh() after the overrides change (e.g. after the engine re-resolves them)."""

    def __init__(self, shell, ctx_factory, lock):
        self.shell, self.ctx_factory, self.lock = shell, ctx_factory, lock
        self.window = None
        self.button = shell.add_action('Modify procedure', self.open, short='Modify')
        lock.on_change(lambda _s: self._safe_refresh())
        self.refresh()

    def _safe_refresh(self):
        try:
            self.refresh()
        except tk.TclError:
            pass

    def count(self):
        ctx = self.ctx_factory()
        return M.ProcModsModel(ctx, self.lock).modified_count()

    def refresh(self):
        self.shell.set_modified(self.count())
        self.shell.set_devmode(self.lock.unlocked)

    def open(self):
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.lift()
                    return
            except tk.TclError:
                pass
        self.window = open_modify_window(self.shell.root, self.ctx_factory(), self.lock, on_change=lambda _m: self.refresh())


def attach_to_shell(shell, ctx_factory, lock: M.DevLock | None = None) -> ShellHook:
    """Give an engine the 'Modify procedure' action and the MODIFIED (n) / DEVELOPER MODE chips.  ctx_factory() returns a fresh
    procmods_ui_model.Context (so it always reflects the current asset, connection and run state)."""
    return ShellHook(shell, ctx_factory, lock or shared_lock())


# ------------------------------------------------------------------------------------------------------------ inside a procedure window
class LiveHook:
    """The 'Edit procedure' action of a running procedure window (procmods_live).  Unlike the Manager's window, it stays usable during a run:
    saved edits start at the next point.  `app` is an engine App (procmods_engine.ProcModsMixin)."""

    LABEL = 'Edit procedure'

    def __init__(self, app, shell, lock):
        self.app, self.shell, self.lock = app, shell, lock
        self.window = None
        self.button = shell.add_action(self.LABEL, self.open, short='Edit')
        lock.on_change(lambda _s: self._safe_refresh())
        self.refresh()

    def _safe_refresh(self):
        try:
            self.refresh()
        except tk.TclError:
            pass

    def count(self) -> int:
        st = self.app.pm_state
        return len(st.oset.active()) if st is not None and st.oset else 0

    def refresh(self):
        """Header chips: MODIFIED (n) = what the running procedure uses, DEVELOPER MODE while unlocked."""
        self.shell.set_modified(self.count())
        self.shell.set_devmode(self.lock.unlocked)

    def open(self):
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.lift()
                    return self.window
            except tk.TclError:
                pass
        ctx = self.app.pm_live_context()
        self.window = open_modify_window(self.shell.root, ctx, self.lock, on_change=lambda _m: self.refresh())
        return self.window


def attach_live(app, shell, lock: M.DevLock | None = None) -> LiveHook:
    """Add 'Edit procedure' to an engine's window (ProcModsMixin.pm_live_attach calls this once the shell is built)."""
    return LiveHook(app, shell, lock or shared_lock())


# ------------------------------------------------------------------------------------------------------------ Manager window
def open_manager_changes(parent, model_name, store=None, lock=None, registries=None):
    """The Manager's 'Procedure changes...' window: the saved model-wide / asset overrides for a model (Changes tab only: the
    command and point lists need a running engine).  Read-only until unlocked; it cannot edit a running procedure."""
    ctx = M.Context(title=model_name, model=model_name, store=store, registries=registries or {})
    return open_modify_window(parent, ctx, lock or shared_lock())
