"""Tk widgets for the Datasheet Builder (thin: every decision lives in datasheet_builder_ui_model.py, which is unit-tested without tkinter).

    import datasheet_builder_ui as dsb_ui
    panel = dsb_ui.DatasheetBuilderPanel(parent_frame, on_saved=callback)       # the Manager's 'Datasheet Builder' tab
    panel.refresh()                                                             # when the tab is shown

The tab lists the user datasheets (New / Open / Duplicate / Delete + Restore / Export JSON / Import JSON / Version history).  Opening one shows the
editor window, a guided flow: Header -> Functions -> Ranges -> Specification -> Test points -> Automation -> Review & Save.  Every step shows the
validation messages (error / warning, with the location) that belong to it; double-click a message to jump to the place.  Anyone can use it (there
is no developer-mode lock).  Display-only SI scaling: the model formats values, the datasheet keeps SI.

NOTE: these widgets were written without a display.  They have been imported and constructed under tests/_tk_stub.py only (every class constructs
and every handler runs); the windows have NEVER been looked at on a real screen, so layout, wrapping, sizes and colours are unchecked.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import datasheet_builder_ui_model as M
import ui_theme as ui

ALL_FUNCTIONS = '(all functions)'
MODE_LABELS = {'both': 'Both sides (nominal ± tolerance)', 'low_only': 'Low side only (reading must not be below)', 'high_only': 'High side only (reading must not be above)'}
BASIS_LABELS = (('', 'Ask me (a % must say of reading or of range)'), ('reading', 'A plain % means % of reading'), ('range', 'A plain % means % of range'))
FILTER_LABELS = (('all', 'All points'), ('uncovered', 'Not covered by any standard'), ('cannot', 'Cannot be automated'), ('unverified', 'Commands not yet verified'))


# ------------------------------------------------------------------------------------------------------------------------------ helpers
def selected(tree):
    """The selected row ids as a tuple (empty when nothing is selected)."""
    try:
        return tuple(tree.selection())
    except Exception:                      # tk.TclError when the widget is gone
        return ()


def fill(tree, rows, key='id', values=(), tags=None, zebra=True):
    """Replace the rows of a table.  rows: list of dicts; values: the keys shown; tags(row) -> extra tag tuple."""
    for item in tuple(tree.get_children()):
        tree.delete(item)
    for n, r in enumerate(rows):
        t = tuple(tags(r)) if tags else ()
        if zebra and not t:
            t = ('even' if n % 2 == 0 else 'odd',)
        tree.insert('', 'end', iid=str(r[key]), values=[r.get(k, '') for k in values], tags=t)


def label_of(pairs, value):
    return next((lab for v, lab in pairs if v == value), pairs[0][1] if pairs else '')


def value_of(pairs, label):
    return next((v for v, lab in pairs if lab == label), pairs[0][0] if pairs else '')


def tip(widget, text):
    try:
        ui.Tooltip(widget, text)
    except (tk.TclError, AttributeError):
        pass


def help_label(parent, text, width=900):
    lab = ttk.Label(parent, text=text, style='Muted.TLabel', wraplength=ui.px(width), justify='left')
    return lab


def row_buttons(parent, *specs):
    """A row of buttons: specs are (text, command) or (text, command, style).  Returns (frame, {text: button})."""
    bar = ttk.Frame(parent)
    out = {}
    for spec in specs:
        text, cmd = spec[0], spec[1]
        kw = {'style': spec[2]} if len(spec) > 2 else {}
        b = ttk.Button(bar, text=text, command=cmd, **kw)
        b.pack(side='left', padx=(0, 8))
        out[text] = b
    return bar, out


class Form(ttk.Frame):
    """Label + entry/combobox rows in a grid: form.entry('Full scale', var) ..."""

    def __init__(self, parent, columns=2):
        super().__init__(parent)
        self.row = 0
        self.col = 0
        self.columns = columns

    def _place(self, label, widget, help_text=''):
        c = self.col * 2
        ttk.Label(self, text=label).grid(row=self.row, column=c, sticky='w', padx=(0, 6), pady=3)
        widget.grid(row=self.row, column=c + 1, sticky='we', padx=(0, 14), pady=3)
        if help_text:
            tip(widget, help_text)
        self.col += 1
        if self.col >= self.columns:
            self.col, self.row = 0, self.row + 1
        return widget

    def entry(self, label, var, width=18, help_text=''):
        return self._place(label, ttk.Entry(self, textvariable=var, width=width), help_text)

    def combo(self, label, var, values, width=22, help_text=''):
        return self._place(label, ttk.Combobox(self, textvariable=var, values=list(values), state='readonly', width=width), help_text)

    def check(self, text, var, help_text=''):
        cb = ttk.Checkbutton(self, text=text, variable=var)
        cb.grid(row=self.row, column=self.col * 2, columnspan=2, sticky='w', pady=3)
        if help_text:
            tip(cb, help_text)
        self.col += 1
        if self.col >= self.columns:
            self.col, self.row = 0, self.row + 1
        return cb

    def newline(self):
        if self.col:
            self.col, self.row = 0, self.row + 1


# ------------------------------------------------------------------------------------------------------------------------------ step bar
class StepBar(ttk.Frame):
    """The numbered flow indicator.  Clicking a step goes there (greyed out when it needs something first)."""

    KIND = {'current': 'Info', 'done': 'Good', 'warn': 'Neutral', 'error': 'Neutral', 'todo': 'Neutral'}

    def __init__(self, parent, model, command):
        super().__init__(parent)
        self.model, self.command = model, command
        self.labels = []
        self.tips = [st['help'] for st in M.STEPS]
        for i, st in enumerate(M.STEPS):
            if i:
                ttk.Label(self, text='›', style='Muted.TLabel').pack(side='left', padx=4)
            lab = ttk.Label(self, text=f'{i + 1}  {st["title"]}', style='PillNeutral.TLabel', cursor='hand2')
            lab.pack(side='left')
            lab.bind('<Button-1>', lambda _e, k=i: self.command(k))
            ui.Tooltip(lab, lambda k=i: self.tips[k])
            self.labels.append(lab)
        self.update_states()

    def update_states(self):
        for lab, s in zip(self.labels, self.model.step_states()):
            mark = {'done': '✔  ', 'error': '✖  ', 'warn': '!  '}.get(s['state'], '')
            count = f'  ({s["errors"]})' if s['errors'] else ''
            lab.configure(text=f'{mark}{s["index"] + 1}  {s["title"]}{count}' if mark else f'{s["index"] + 1}  {s["title"]}{count}',
                          style=f'Pill{self.KIND[s["state"]]}.TLabel')
            self.tips[s['index']] = s['why_not'] or M.STEPS[s['index']]['help']


# ------------------------------------------------------------------------------------------------------------------------------ pages
class Page(ttk.Frame):
    """One step of the flow.  `reload()` re-reads the model; `commit()` pushes typed-but-not-applied text into it."""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.model = win.model

    def reload(self):
        pass

    def commit(self):
        pass

    def say(self, outcome):
        self.win.changed(outcome)
        return outcome

    def intro(self, step):
        help_label(self, M.STEPS[step]['help']).pack(anchor='w', pady=(0, 8), fill='x')


class FunctionBar(ttk.Frame):
    """'Function: [DC volts v]' picker shared by the pages that work on one function at a time."""

    def __init__(self, parent, win, with_all=False, command=None):
        super().__init__(parent)
        self.win, self.with_all, self.command = win, with_all, command
        self.var = tk.StringVar()
        ttk.Label(self, text='Function:', style='Bold.TLabel').pack(side='left', padx=(0, 6))
        self.box = ttk.Combobox(self, textvariable=self.var, state='readonly', width=34)
        self.box.pack(side='left')
        self.box.bind('<<ComboboxSelected>>', lambda _e: self.picked())
        self.ids = {}
        self.all = with_all                                   # '(all functions)' is chosen (the default where it exists)

    def reload(self):
        rows = self.win.model.function_rows()
        self.ids = {f'{r["name"]} ({r["id"]})' if sum(1 for x in rows if x['name'] == r['name']) > 1 else r['name']: r['id'] for r in rows}
        names = list(self.ids)
        if self.with_all:
            names = [ALL_FUNCTIONS] + names
        self.box.configure(values=names)
        cur = self.win.model.fid
        label = next((n for n, i in self.ids.items() if i == cur), '')
        self.var.set(ALL_FUNCTIONS if self.with_all and self.all else label or (names[0] if names else ''))

    def picked(self):
        self.all = self.with_all and self.var.get() == ALL_FUNCTIONS
        if not self.all:
            self.win.model.select_function(self.ids.get(self.var.get(), ''))
        if self.command:
            self.command()

    @property
    def fid(self):
        return '' if self.with_all and self.all else self.ids.get(self.var.get(), self.win.model.fid)


class HeaderPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_HEADER)
        self.make, self.mdl, self.title, self.revision, self.notes = (tk.StringVar() for _ in range(5))
        form = Form(self, columns=1)
        form.columnconfigure(1, weight=1)
        for label, var, tip_text in (('Make (manufacturer)', self.make, 'For example Keysight, Fluke, Tektronix.'),
                                     ('Model', self.mdl, 'For example 34461A.'),
                                     ('Title', self.title, 'What the procedure list shows, for example "34461A Performance Verification".'),
                                     ('Document / revision', self.revision, 'Optional: which manual or revision you copied the specification from.'),
                                     ('Notes', self.notes, 'Optional notes for yourself.')):
            e = form.entry(label, var, width=70, help_text=tip_text)
            e.bind('<FocusOut>', lambda _e: self.commit())
            e.bind('<Return>', lambda _e: self.commit())
        form.pack(fill='x', anchor='w')
        ttk.Label(self, text='Time periods the specification is valid for', style='Section.TLabel').pack(anchor='w', pady=(14, 2))
        help_label(self, 'One period is enough. Add more (for example 90 days and 1 year) when the manual prints a different accuracy for each; '
                         'you then type the specification once per period. The default period is the one the procedure uses.').pack(anchor='w', fill='x')
        holder = ttk.Frame(self)
        holder.pack(fill='x', pady=6)
        self.periods = ui.make_table(holder, ('id', 'label', 'default'), ('Id', 'Name', 'Default'), (100, 240, 90), anchors={'label': 'w', 'id': 'w'}, height=4, zebra=True,
                                     stretch={'id': False, 'default': False})
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        self.preset = tk.StringVar()
        self.custom_id, self.custom_label = tk.StringVar(), tk.StringVar()
        self.preset_box = ttk.Combobox(bar, textvariable=self.preset, state='readonly', width=14)
        self.preset_box.pack(side='left')
        ttk.Button(bar, text='Add this period', command=self.add_preset).pack(side='left', padx=(6, 18))
        ttk.Label(bar, text='or your own  id').pack(side='left')
        ttk.Entry(bar, textvariable=self.custom_id, width=8).pack(side='left', padx=4)
        ttk.Label(bar, text='name').pack(side='left')
        ttk.Entry(bar, textvariable=self.custom_label, width=16).pack(side='left', padx=4)
        ttk.Button(bar, text='Add', command=self.add_custom).pack(side='left', padx=(4, 18))
        ttk.Button(bar, text='Make default', command=self.make_default).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Remove period', command=self.remove).pack(side='left')
        self.outward = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text='Round the limits outward to the display resolution (never tighter than the exact limit)', variable=self.outward,
                        command=self.set_rounding).pack(anchor='w', pady=(12, 0))

    def commit(self):
        ds = self.model.ds
        new = dict(make=self.make.get(), model=self.mdl.get(), title=self.title.get(), revision=self.revision.get(), notes=self.notes.get())
        old = dict(make=ds.make, model=ds.model, title=ds.title, revision=ds.revision, notes=ds.notes)
        if {k: v.strip() for k, v in new.items()} == {k: v.strip() for k, v in old.items()}:
            return
        self.say(self.model.set_header(**new))

    def reload(self):
        ds = self.model.ds
        for var, val in ((self.make, ds.make), (self.mdl, ds.model), (self.title, ds.title), (self.revision, ds.revision), (self.notes, ds.notes)):
            if var.get() != val:
                var.set(val)
        fill(self.periods, [dict(r, default_text='yes' if r['default'] else '') for r in self.model.period_rows()], 'id', ('id', 'label', 'default_text'))
        self.preset_box.configure(values=[f"{p['id']}  ({p['label']})" for p in self.model.period_presets() if not p['used']])
        self.outward.set(ds.options.get('limit_rounding') == 'outward')

    def add_preset(self):
        self.commit()
        pid = self.preset.get().split()[0] if self.preset.get().strip() else ''
        if not pid:
            return self.say(M.Outcome(False, 'Choose a period from the list, or type your own.'))
        return self.say(self.model.add_period(pid))

    def add_custom(self):
        self.commit()
        res = self.say(self.model.add_period(self.custom_id.get(), self.custom_label.get()))
        if res.ok:
            self.custom_id.set(''), self.custom_label.set('')
        return res

    def _sel(self):
        s = selected(self.periods)
        return s[0] if s else ''

    def make_default(self):
        self.commit()
        return self.say(self.model.set_default_period(self._sel())) if self._sel() else self.say(M.Outcome(False, 'Select a period first.'))

    def remove(self):
        self.commit()
        pid = self._sel()
        if not pid:
            return self.say(M.Outcome(False, 'Select a period first.'))
        if not messagebox.askyesno('Remove period', f'Remove the period "{pid}" and the specification text typed for it?', parent=self.win):
            return None
        return self.say(self.model.remove_period(pid))

    def set_rounding(self):
        self.commit()
        self.say(self.model.set_limit_rounding(self.outward.get()))


class FunctionsPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_FUNCTIONS)
        panes = ttk.Frame(self)
        panes.pack(fill='both', expand=True)
        panes.columnconfigure(0, weight=3)
        panes.columnconfigure(1, weight=2)
        panes.rowconfigure(0, weight=1)
        left = ttk.Frame(panes)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        self.table = ui.make_table(left, ('name', 'kind', 'direction', 'ranges', 'points', 'problems'), ('Function', 'Kind', 'Direction', 'Ranges', 'Points', 'Errors'),
                                   (200, 130, 110, 70, 70, 70), anchors={'name': 'w', 'kind': 'w', 'direction': 'w'}, height=10, zebra=True,
                                   stretch={'ranges': False, 'points': False, 'problems': False})
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.picked())
        bar, _ = row_buttons(left, ('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1)), ('Remove function', self.remove, 'Danger.TButton'))
        bar.pack(fill='x', pady=(8, 0))
        right = ttk.LabelFrame(panes, text='Add a function', padding=12)
        right.grid(row=0, column=1, sticky='nsew')
        self.kind_var, self.name_var = tk.StringVar(), tk.StringVar()
        self.kinds = {}
        ttk.Label(right, text='What does it measure or output?').pack(anchor='w')
        self.kind_box = ttk.Combobox(right, textvariable=self.kind_var, state='readonly', width=44)
        self.kind_box.pack(anchor='w', pady=(2, 6))
        ttk.Label(right, text='Name (optional, shown on the procedure)').pack(anchor='w')
        ttk.Entry(right, textvariable=self.name_var, width=46).pack(anchor='w', pady=(2, 8))
        ttk.Button(right, text='Add function', style='Accent.TButton', command=self.add).pack(anchor='w')
        self.detail = ttk.LabelFrame(panes, text='Selected function', padding=12)
        self.detail.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        self.d_name, self.d_dir, self.d_switch = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.dform = Form(self.detail, columns=2)
        self.dform.entry('Name', self.d_name, 30)
        self.dir_box = self.dform.combo('Direction', self.d_dir, [], 60, 'Who measures and who supplies?')
        self.dform.entry('Tell the operator to select', self.d_switch, 40, 'Shown at the start of this function, for example "DC volts, auto range off".')
        self.dform.pack(fill='x')
        self.setting_vars = {}
        self.setting_box = ttk.Frame(self.detail)
        self.setting_box.pack(fill='x')
        ttk.Button(self.detail, text='Apply changes', command=self.apply).pack(anchor='w', pady=(6, 0))
        self._dirs = []

    def reload(self):
        m = self.model
        kinds = m.kind_choices()
        self.kinds = {f"{k['group_label']}: {k['label']}": k['kind'] for k in kinds}
        self.kind_box.configure(values=list(self.kinds))
        if not self.kind_var.get() and self.kinds:
            self.kind_var.set(next(iter(self.kinds)))
        rows = m.function_rows()
        fill(self.table, rows, 'id', ('name', 'kind', 'direction', 'ranges', 'points', 'problems'))
        if m.fid:
            try:
                self.table.selection_set(m.fid)
            except tk.TclError:
                pass
        self.reload_detail()

    def reload_detail(self):
        m = self.model
        fn = m.fn()
        if fn is None:
            self.d_name.set(''), self.d_switch.set('')
            return
        self.d_name.set(fn.name)
        self.d_switch.set(fn.switch)
        self._dirs = m.direction_choices(fn.id)
        self.dir_box.configure(values=[lab for _v, lab in self._dirs], state='readonly' if len(self._dirs) > 1 else 'disabled')
        self.d_dir.set(label_of(self._dirs, fn.direction))
        for w in tuple(self.setting_box.winfo_children()):
            w.destroy()
        self.setting_vars = {}
        f = Form(self.setting_box, columns=3)
        for fld in m.setting_fields(fn.id):
            var = tk.StringVar(value=fld['value'])
            self.setting_vars[fld['key']] = var
            f.combo(fld['label'], var, fld['choices'], 10)
        f.pack(fill='x')

    def picked(self):
        s = selected(self.table)
        if s:
            self.model.select_function(s[0])
            self.reload_detail()

    def add(self):
        res = self.say(self.model.add_function(self.kinds.get(self.kind_var.get(), ''), self.name_var.get()))
        if res.ok:
            self.name_var.set('')
        return res

    def apply(self):
        fid = self.model.fid
        if not fid:
            return self.say(M.Outcome(False, 'Select a function first.'))
        res = self.model.set_function(fid, name=self.d_name.get(), direction=value_of(self._dirs, self.d_dir.get()) if self._dirs else None, switch=self.d_switch.get())
        for key, var in self.setting_vars.items():
            res = self.model.set_function_setting(fid, key, var.get()) if res.ok else res
        return self.say(res)

    def remove(self):
        fn = self.model.fn()
        if fn is None:
            return self.say(M.Outcome(False, 'Select a function first.'))
        if not messagebox.askyesno('Remove function', f'Remove {fn.name} with its ranges, specification and {len(fn.points)} point(s)? (Undo brings it back.)', parent=self.win):
            return None
        return self.say(self.model.remove_function(fn.id))

    def move(self, delta):
        if self.model.fid:
            self.say(self.model.move_function(self.model.fid, delta))


class RangesPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_RANGES)
        self.fbar = FunctionBar(self, win, command=self.reload)
        self.fbar.pack(anchor='w', pady=(0, 8))
        self.table = ui.make_table(self, ('text', 'resolution', 'max', 'unit', 'points', 'spec'), ('Range (full scale)', 'Resolution', 'Max input', 'Shown in', 'Points', 'Spec lines'),
                                   (170, 130, 110, 90, 70, 80), anchors={'text': 'w', 'resolution': 'w', 'max': 'w'}, height=8, zebra=True, pack=False,
                                   stretch={'points': False, 'spec': False})
        self.table.master.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.picked())
        self.fs, self.res, self.label, self.unit, self.maxin, self.decimals, self.dec_prefix, self.bulk = (tk.StringVar() for _ in range(8))
        self.unipolar = tk.BooleanVar(value=False)
        box = ttk.LabelFrame(self, text='Add or change a range', padding=10)
        box.pack(fill='x', pady=(10, 0))
        form = Form(box, columns=3)
        form.entry('Full scale', self.fs, 14, 'The top of the range with its unit, for example 10 V or 100 mV.')
        form.entry('Resolution', self.res, 14, 'The smallest step the display shows in this range, for example 10 µV. A "count" in the specification means this.')
        form.combo('Show values in', self.unit, [lab for _v, lab in M.PREFIX_CHOICES], 14, 'Display only: the datasheet stores SI values.')
        form.entry('Label as printed (optional)', self.label, 14, 'For example 10.00000 V.')
        form.entry('Max input (optional)', self.maxin, 14, 'The highest input the range accepts when that is above the full scale (over-range).')
        form.check('Positive values only', self.unipolar)
        form.pack(fill='x')
        helper = ttk.Frame(box)
        helper.pack(fill='x', pady=(4, 0))
        ttk.Label(helper, text='Resolution helper: the display shows').pack(side='left')
        ttk.Entry(helper, textvariable=self.decimals, width=4).pack(side='left', padx=4)
        ttk.Label(helper, text='decimals when the range is shown in').pack(side='left')
        ttk.Combobox(helper, textvariable=self.dec_prefix, values=['', 'm', 'µ', 'k'], width=4, state='readonly').pack(side='left', padx=4)
        ttk.Button(helper, text='Use as resolution', command=self.use_decimals).pack(side='left', padx=6)
        bar, _ = row_buttons(box, ('Add range', self.add, 'Accent.TButton'), ('Change selected', self.change), ('Remove selected', self.remove, 'Danger.TButton'))
        bar.pack(fill='x', pady=(8, 0))
        bulk = ttk.Frame(box)
        bulk.pack(fill='x', pady=(8, 0))
        ttk.Label(bulk, text='Or add several full scales at once:').pack(side='left')
        ttk.Entry(bulk, textvariable=self.bulk, width=44).pack(side='left', padx=6)
        ttk.Button(bulk, text='Add them', command=self.add_many).pack(side='left')
        self.hint = ttk.Label(self, text='', style='Muted.TLabel', wraplength=ui.px(900), justify='left')
        self.hint.pack(anchor='w', pady=(6, 0))

    def reload(self):
        self.fbar.reload()
        rows = self.model.range_rows(self.fbar.fid)
        fill(self.table, rows, 'id', ('text', 'resolution', 'max_input', 'display_unit', 'points', 'spec'))
        fn = self.model.fn(self.fbar.fid)
        self.hint.configure(text=f'Type values with their unit, for example {M.show(M.db.D(10), fn.unit)} or {M.show(M.db.D("0.1"), fn.unit)}.' if fn else 'Add a function first (step 2).')

    def picked(self):
        s = selected(self.table)
        fn = self.model.fn(self.fbar.fid)
        if not s or fn is None:
            return
        r = fn.range(s[0])
        if r is None:
            return
        self.fs.set(M.show(r.full_scale, fn.unit))
        self.res.set(M.show(r.resolution, fn.unit) if r.resolution is not None else '')
        self.label.set(r.label)
        self.maxin.set(M.show(r.max_input, fn.unit) if r.max_input is not None else '')
        self.unit.set(label_of(M.PREFIX_CHOICES, r.display_unit if r.display_unit else ''))
        self.unipolar.set(r.unipolar)

    def _prefix(self):
        return value_of(M.PREFIX_CHOICES, self.unit.get())

    def use_decimals(self):
        try:
            v = self.model.resolution_from_decimals(self.dec_prefix.get(), int(self.decimals.get()))
        except (ValueError, M.db.DsError) as exc:
            return self.say(M.Outcome(False, M.plain_error(exc) if isinstance(exc, M.db.DsError) else 'Type a whole number of decimals.'))
        fn = self.model.fn(self.fbar.fid)
        self.res.set(M.show(v, fn.unit) if fn else str(v))
        return None

    def add(self):
        res = self.say(self.model.add_range(self.fbar.fid, self.fs.get(), self.res.get(), self.label.get(), self._prefix(), self.maxin.get(), self.unipolar.get()))
        if res.ok:
            self.fs.set(''), self.res.set(''), self.label.set(''), self.maxin.set('')
        return res

    def change(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a range in the table first.'))
        return self.say(self.model.edit_range(self.fbar.fid, s[0], self.fs.get(), self.res.get(), self.label.get(), self._prefix(), self.maxin.get(), self.unipolar.get()))

    def add_many(self):
        res = self.say(self.model.add_ranges(self.fbar.fid, self.bulk.get()))
        if res.ok:
            self.bulk.set('')
        return res

    def remove(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a range in the table first.'))
        use = self.model.range_usage(self.fbar.fid, s[0])
        cascade = False
        if use['points'] or use['spec']:
            if not messagebox.askyesno('Remove range', f'This range has {use["points"]} point(s) and {use["spec"]} specification line(s). Remove it together with them? (Undo brings them back.)', parent=self.win):
                return None
            cascade = True
        return self.say(self.model.remove_range(self.fbar.fid, s[0], cascade))


class SpecPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_SPEC)
        self.fbar = FunctionBar(self, win, command=self.reload)
        self.fbar.pack(anchor='w', pady=(0, 8))
        self.table = ui.make_table(self, ('scope', 'text', 'mode'), ('Applies to', 'Accuracy (default period)', 'Sides'), (230, 480, 150), anchors={'scope': 'w', 'text': 'w', 'mode': 'w'},
                                   height=6, zebra=True, pack=False, stretch={'mode': False})
        self.table.master.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.picked())
        self.warn = ttk.Label(self, text='', style='Muted.TLabel', wraplength=ui.px(900), justify='left')
        self.warn.pack(anchor='w', pady=(4, 0))
        box = ttk.LabelFrame(self, text='Specification line', padding=10)
        box.pack(fill='x', pady=(8, 0))
        self.range_var, self.flo, self.fhi, self.mode, self.bound, self.basis, self.minus = (tk.StringVar() for _ in range(7))
        self.period_vars = {}
        self.form = Form(box, columns=3)
        self.range_box = self.form.combo('Range', self.range_var, ['All ranges'], 20, 'Which range this line is for. "All ranges" applies to every range that has no line of its own.')
        self.flo_e = self.form.entry('From frequency', self.flo, 12, 'AC and frequency functions: where this band starts, for example 10 Hz. Leave empty for no band.')
        self.fhi_e = self.form.entry('To frequency', self.fhi, 12, 'Where the band ends, for example 1 kHz.')
        self.form.combo('Sides', self.mode, [MODE_LABELS[k] for k in db_modes()], 36, 'Use "low side only" for limits like a bandwidth that must not fall below -3 dB.')
        self.form.entry('Opposite bound (one-sided)', self.bound, 12, 'The other limit a typed reading must stay within, in the function unit.')
        self.form.combo('A plain % means', self.basis, [lab for _v, lab in BASIS_LABELS], 36)
        self.form.pack(fill='x')
        self.period_box = ttk.Frame(box)
        self.period_box.pack(fill='x', pady=(4, 0))
        hb = ttk.Frame(box)
        hb.pack(fill='x', pady=(6, 0))
        ttk.Label(hb, text='Insert:').pack(side='left', padx=(0, 6))
        self.helper_buttons = {}
        self.focus_key = ''
        self.hb = hb
        self.example_var = tk.StringVar(value='')
        self.example_box = ui.Notice(box, kind='info', textvariable=self.example_var, title='Worked example')
        self.example_box.pack(fill='x', pady=(8, 0))
        self.parts_var = tk.StringVar(value='')
        ttk.Label(box, textvariable=self.parts_var, style='Muted.TLabel', wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(2, 0))
        bar, _ = row_buttons(box, ('Add line', self.add, 'Accent.TButton'), ('Change selected line', self.change), ('Remove selected line', self.remove, 'Danger.TButton'),
                             ('Copy to other ranges...', self.copy))
        bar.pack(fill='x', pady=(8, 0))
        for v in (self.range_var, self.flo, self.fhi, self.basis, self.minus, self.mode, self.bound):
            v.trace_add('write', lambda *_: self.update_example())
        self._ranges = []

    def reload(self):
        self.fbar.reload()
        m = self.model
        fid = self.fbar.fid
        fn = m.fn(fid)
        rows = m.spec_rows(fid)
        dflt = m.ds.default_period
        for r in rows:
            r['text'] = r['texts'].get(dflt, '')
            r['mode_text'] = {'both': 'both', 'low_only': 'low only', 'high_only': 'high only'}[r['mode']]
        fill(self.table, [dict(r, id=r['index']) for r in rows], 'id', ('scope', 'text', 'mode_text'))
        if fn is None:
            return
        self._ranges = [('', 'All ranges')] + [(r.id, m.range_text(fn, r)) for r in fn.ranges]
        self.range_box.configure(values=[lab for _v, lab in self._ranges])
        if self.range_var.get() not in [lab for _v, lab in self._ranges]:
            self.range_var.set('All ranges')
        has_f = bool(fn.info.get('ac') or fn.info['family'] == 'generator' or fn.info.get('value'))
        for w in (self.flo_e, self.fhi_e):
            w.configure(state='normal' if has_f else 'disabled')
        for w in tuple(self.period_box.winfo_children()):
            w.destroy()
        old = {k: v.get() for k, v in self.period_vars.items()}
        self.period_vars = {}
        pf = Form(self.period_box, columns=1)
        pf.columnconfigure(1, weight=1)
        for p in m.ds.periods:
            var = tk.StringVar(value=old.get(p.id, ''))
            self.period_vars[p.id] = var
            e = pf.entry(f'Accuracy for {p.label or p.id}', var, 80, 'For example 0.05 % of reading + 0.01 % of range')
            e.bind('<FocusIn>', lambda _e, k=p.id: setattr(self, 'focus_key', k))
            var.trace_add('write', lambda *_: self.update_example())
        pf.pack(fill='x')
        mf = Form(self.period_box, columns=1)
        mf.entry('Different tolerance below the nominal (optional)', self.minus, 60, 'Only when the manual gives a different tolerance below the nominal than above it.')
        mf.pack(fill='x')
        for b in tuple(self.helper_buttons.values()):
            b.destroy()
        self.helper_buttons = {}
        for h in m.helpers(fid):
            b = ttk.Button(self.hb, text=h['label'], style='Compact.TButton', command=lambda k=h['key']: self.insert(k))
            b.pack(side='left', padx=(0, 4))
            tip(b, h['help'])
            self.helper_buttons[h['key']] = b
        self.update_example()
        warn = m.uncovered_ranges(fid)
        self.warn.configure(text=('No specification line applies yet to: ' + ', '.join(warn) + '. Add a line for these (or an "All ranges" line).') if warn else '')

    # ---- form <-> model
    def _range_id(self):
        return value_of(self._ranges, self.range_var.get()) if self._ranges else None

    def _mode(self):
        return next((k for k in db_modes() if MODE_LABELS[k] == self.mode.get()), 'both')

    def _texts(self):
        return {k: v.get() for k, v in self.period_vars.items()}

    def _basis(self):
        return value_of(BASIS_LABELS, self.basis.get()) or None

    def _key(self):
        return self.focus_key if self.focus_key in self.period_vars else (self.model.period if self.model.period in self.period_vars else next(iter(self.period_vars), ''))

    def insert(self, key):
        k = self._key()
        if not k:
            return
        var = self.period_vars[k]
        var.set(self.model.insert_helper(var.get(), key, self.fbar.fid))

    def update_example(self):
        k = self._key()
        if not k or not self.model.fn(self.fbar.fid):
            self.example_var.set('')
            self.parts_var.set('')
            return
        r = self.model.example(self.fbar.fid, self.period_vars[k].get(), self._range_id(), f_lo=self.flo.get(), f_hi=self.fhi.get(), default_basis=self._basis(), minus_text=self.minus.get())
        self.example_var.set(r['text'] or 'Type the accuracy statement above.')
        self.parts_var.set(('; '.join(r['parts'])) if r['ok'] and r['parts'] else '')
        try:
            self.example_box.configure(style='NoticeInfo.TFrame' if r['ok'] else 'NoticeWarn.TFrame')
        except tk.TclError:
            pass

    def picked(self):
        s = selected(self.table)
        rows = self.model.spec_rows(self.fbar.fid)
        if not s or int(s[0]) >= len(rows):
            return
        r = rows[int(s[0])]
        self.range_var.set(label_of(self._ranges, r['range_id'] or ''))
        self.flo.set(r['f_lo']), self.fhi.set(r['f_hi']), self.bound.set(r['bound'])
        self.mode.set(MODE_LABELS[r['mode']])
        for k, var in self.period_vars.items():
            var.set(r['texts'].get(k, ''))
        self.minus.set(next(iter(r['minus'].values()), ''))

    def _minus_texts(self):
        t = self.minus.get().strip()
        return {k: t for k in self.period_vars} if t else None

    def add(self):
        return self.say(self.model.add_spec_entry(self.fbar.fid, self._texts(), self._range_id(), self.flo.get(), self.fhi.get(), self._mode(), self.bound.get(),
                                                  self._minus_texts(), self._basis()))

    def change(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a line in the table first.'))
        return self.say(self.model.edit_spec_entry(self.fbar.fid, int(s[0]), self._texts(), self._range_id(), self.flo.get(), self.fhi.get(), self._mode(), self.bound.get(),
                                                   self._minus_texts(), self._basis()))

    def remove(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a line in the table first.'))
        return self.say(self.model.remove_spec_entry(self.fbar.fid, int(s[0])))

    def copy(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select the line to copy first.'))
        fn = self.model.fn(self.fbar.fid)
        text = simpledialog.askstring('Copy to other ranges', 'Copy to which ranges? Type the full scales, separated by commas (for example 1 V, 10 V), or "all".', parent=self.win)
        if not text or fn is None:
            return None
        if text.strip().lower() == 'all':
            ids = [r.id for r in fn.ranges]
        else:
            try:
                wanted = [M.db.parse_quantity(t, fn.unit or None) for t in M.split_list(text)]
            except M.db.DsError as exc:
                return self.say(M.Outcome(False, M.plain_error(exc)))
            ids = [r.id for r in fn.ranges if r.full_scale in wanted]
        return self.say(self.model.copy_spec_to_ranges(self.fbar.fid, int(s[0]), ids))


def db_modes():
    return M.db.MODES


class PointsPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_POINTS)
        top = ttk.Frame(self)
        top.pack(fill='x')
        self.fbar = FunctionBar(top, win, command=self.reload)
        self.fbar.pack(side='left')
        ttk.Label(top, text='   Show limits for:').pack(side='left')
        self.period_var = tk.StringVar()
        self.period_box = ttk.Combobox(top, textvariable=self.period_var, state='readonly', width=14)
        self.period_box.pack(side='left', padx=6)
        self.period_box.bind('<<ComboboxSelected>>', lambda _e: self.period_picked())
        self.only_problems = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='Only points with problems', variable=self.only_problems, command=self.reload).pack(side='left', padx=12)
        ttk.Label(self, text='How the points are worked out (rules)', style='Section.TLabel').pack(anchor='w', pady=(8, 2))
        self.rules = ui.make_table(self, ('label', 'text', 'points', 'on'), ('Rule', 'What it makes', 'Points', 'On'), (170, 560, 70, 50), anchors={'label': 'w', 'text': 'w'},
                                   height=3, zebra=True, pack=False, stretch={'points': False, 'on': False})
        self.rules.master.pack(fill='x')
        bar, _ = row_buttons(self, ('Add rule...', self.add_rule, 'Accent.TButton'), ('Change rule...', self.edit_rule), ('Switch rule on/off', self.toggle_rule),
                             ('Remove rule', self.remove_rule, 'Danger.TButton'), ('Recalculate points', self.recalculate))
        bar.pack(fill='x', pady=(6, 6))
        ttk.Label(self, text='Test points and their limits', style='Section.TLabel').pack(anchor='w', pady=(4, 2))
        cols = ('nominal', 'frequency', 'amplitude', 'range', 'low', 'high', 'source', 'origin', 'on')
        self.table = ui.make_table(self, cols, ('Nominal', 'Frequency', 'Level', 'Range', 'Low limit', 'High limit', 'Limits from', 'Made by', 'On'), (110, 90, 80, 90, 120, 120, 90, 80, 40),
                                   anchors={'nominal': 'e', 'low': 'e', 'high': 'e'}, height=10, pack=False, stretch={'on': False})
        self.table.master.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.picked())
        self.table.bind('<Double-1>', lambda _e: self.edit_point())
        self.detail = tk.StringVar(value='Select a point to see its accept text.')
        ttk.Label(self, textvariable=self.detail, style='Muted.TLabel', wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(4, 0))
        bar2, _ = row_buttons(self, ('Add point...', self.add_point), ('Edit point...', self.edit_point), ('Typed limits...', self.override), ('Switch point on/off', self.toggle_point),
                              ('Remove point', self.remove_point, 'Danger.TButton'))
        bar2.pack(fill='x', pady=(6, 0))
        self._rows = {}

    def reload(self):
        self.fbar.reload()
        m = self.model
        fid = self.fbar.fid
        ids = [p['id'] for p in m.period_rows()]
        self.period_box.configure(values=ids)
        self.period_var.set(m.period)
        fill(self.rules, [dict(r, on_text='yes' if r['enabled'] else 'no') for r in m.rule_rows(fid)], 'id', ('label', 'text', 'points', 'on_text'))
        rows = m.point_rows(fid, m.period, self.only_problems.get())
        self._rows = {r['id']: r for r in rows}
        for r in rows:
            r['on_text'] = 'yes' if r['enabled'] else 'no'
        fill(self.table, rows, 'id', ('nominal', 'frequency', 'amplitude', 'range', 'low', 'high', 'source', 'origin', 'on_text'),
             tags=lambda r: ('error',) if r['has_error'] else ('pending',) if not r['enabled'] else ())
        self.detail.set(f'{len(rows)} point(s).')

    def period_picked(self):
        if self.model.set_period(self.period_var.get()):
            self.reload()

    def _pid(self):
        s = selected(self.table)
        return s[0] if s else ''

    def picked(self):
        r = self._rows.get(self._pid())
        if r:
            self.detail.set(f'{r["accept"]}.   {r["tol_text"]}' + (f'   PROBLEM: {r["error"]}' if r['error'] else '') + ('   (two specification lines apply equally here; the tighter one is used)' if r['ambiguous'] else ''))

    def recalculate(self):
        return self.say(self.model.recalculate(self.fbar.fid))

    # ---- rules
    def _rule_id(self):
        s = selected(self.rules)
        return s[0] if s else ''

    def add_rule(self):
        if not self.fbar.fid:
            return self.say(M.Outcome(False, 'Add a function and its ranges first.'))
        dlg = RuleDialog(self.win, self.model, self.fbar.fid)
        self.win.wait_window(dlg)
        if dlg.outcome:
            self.say(dlg.outcome)
        return dlg.outcome

    def edit_rule(self):
        rid = self._rule_id()
        if not rid:
            return self.say(M.Outcome(False, 'Select a rule in the table first.'))
        dlg = RuleDialog(self.win, self.model, self.fbar.fid, rid)
        self.win.wait_window(dlg)
        if dlg.outcome:
            self.say(dlg.outcome)
        return dlg.outcome

    def toggle_rule(self):
        rid = self._rule_id()
        if not rid:
            return self.say(M.Outcome(False, 'Select a rule in the table first.'))
        fn = self.model.fn(self.fbar.fid)
        r = next((x for x in fn.rules if x.id == rid), None)
        return self.say(self.model.set_rule_enabled(self.fbar.fid, rid, not (r and r.enabled)))

    def remove_rule(self):
        rid = self._rule_id()
        if not rid:
            return self.say(M.Outcome(False, 'Select a rule in the table first.'))
        if not messagebox.askyesno('Remove rule', 'Remove this rule and the points only it produced? (Points you edited are kept; Undo brings the rest back.)', parent=self.win):
            return None
        return self.say(self.model.remove_rule(self.fbar.fid, rid))

    # ---- points
    def add_point(self):
        if not self.fbar.fid:
            return self.say(M.Outcome(False, 'Add a function and its ranges first.'))
        dlg = PointDialog(self.win, self.model, self.fbar.fid)
        self.win.wait_window(dlg)
        if dlg.outcome:
            self.say(dlg.outcome)
        return dlg.outcome

    def edit_point(self):
        pid = self._pid()
        if not pid:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        dlg = PointDialog(self.win, self.model, self.fbar.fid, pid)
        self.win.wait_window(dlg)
        if dlg.outcome:
            self.say(dlg.outcome)
        return dlg.outcome

    def override(self):
        pid = self._pid()
        if not pid:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        d = self.model.point_detail(self.fbar.fid, pid)
        fn = self.model.fn(self.fbar.fid)
        text = simpledialog.askstring('Typed limits', f'Low and high limit for {pid} ({self.model.period}), in SI units or with a unit, separated by a comma.\n'
                                      f'Example: 4.99 V, 5.01 V.   Leave empty to use the specification again.', initialvalue=f"{d.get('low', '')}, {d.get('high', '')}".strip(' ,'),
                                      parent=self.win)
        if text is None:
            return None
        parts = [t.strip() for t in text.split(',')] + ['', '']
        return self.say(self.model.set_point_override(self.fbar.fid, pid, parts[0], parts[1]) if fn else M.Outcome(False, 'No function.'))

    def toggle_point(self):
        pid = self._pid()
        if not pid:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        return self.say(self.model.set_point_enabled(self.fbar.fid, pid, not self._rows[pid]['enabled']))

    def remove_point(self):
        pid = self._pid()
        if not pid:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        return self.say(self.model.remove_point(self.fbar.fid, pid))


class RuleDialog(tk.Toplevel):
    """Rule picker: choose how the points are worked out; only the fields that apply are shown.  `outcome` holds the result (None = cancelled)."""

    def __init__(self, parent, model, fid, rule_id=None):
        super().__init__(parent)
        self.model, self.fid, self.rule_id, self.outcome = model, fid, rule_id, None
        self.title('Change rule' if rule_id else 'Add a rule for the test points')
        self.transient(parent)
        cat = model.rule_catalog(fid)
        self.cat = cat
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        self.v = {k: tk.StringVar() for k in ('type', 'percents', 'values', 'start', 'stop', 'count', 'step', 'per_decade', 'nominal', 'freq_mode', 'freq_values', 'freq_start',
                                              'freq_stop', 'freq_count', 'freq_per_decade', 'freq_at', 'amplitude')}
        self.bipolar, self.zero = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.range_vars = {}
        self.type_pairs = [(r['key'], r['label']) for r in cat['rules']]
        self.freq_pairs = [(k, lab) for k, lab in cat['freq']]
        ttk.Label(body, text='Kind of rule', style='Bold.TLabel').pack(anchor='w')
        self.type_box = ttk.Combobox(body, textvariable=self.v['type'], values=[lab for _k, lab in self.type_pairs], state='readonly', width=40)
        self.type_box.pack(anchor='w', pady=(2, 2))
        self.type_box.bind('<<ComboboxSelected>>', lambda _e: self.layout())
        self.help = ttk.Label(body, text='', style='Muted.TLabel', wraplength=ui.px(560), justify='left')
        self.help.pack(anchor='w', pady=(0, 8))
        self.fields = ttk.Frame(body)
        self.fields.pack(fill='x')
        self.sections = {}
        f = Form(self.fields, columns=2)
        f.entry('Percentages of full scale', self.v['percents'], 24, 'For example 10, 50, 100')
        f.check('Also the negative side', self.bipolar)
        f.check('Also zero', self.zero)
        f.entry('Points', self.v['values'], 40, 'For example 1 mV, 5 V, 100 mV. Each goes on the smallest range that holds it.')
        f.entry('Start', self.v['start'], 14, 'With its unit, for example 1 V')
        f.entry('Stop', self.v['stop'], 14)
        f.entry('Number of points', self.v['count'], 8)
        f.entry('or step', self.v['step'], 12, 'For example 0.5 V')
        f.entry('or points per decade', self.v['per_decade'], 8)
        f.entry('Level', self.v['nominal'], 12, 'The one level the frequencies are applied at (0 for dB tests).')
        f.pack(fill='x')
        fr = ttk.LabelFrame(body, text='Frequencies', padding=8)
        fr.pack(fill='x', pady=(8, 0))
        ff = Form(fr, columns=2)
        ff.combo('Frequencies', self.v['freq_mode'], [lab for _k, lab in self.freq_pairs], 40)
        ff.entry('List', self.v['freq_values'], 30, 'For example 100 Hz, 1 kHz, 20 kHz')
        ff.entry('Start', self.v['freq_start'], 12)
        ff.entry('Stop', self.v['freq_stop'], 12)
        ff.entry('Number of frequencies', self.v['freq_count'], 8)
        ff.entry('or per decade (log)', self.v['freq_per_decade'], 8)
        ff.combo('Band points', self.v['freq_at'], ['edges', 'mid', 'both'], 10, 'edges = the band limits; mid = the middle of each band.')
        ff.pack(fill='x')
        if cat['uses_amplitude']:
            af = Form(body, columns=1)
            af.entry('Stimulus level (e.g. 1 V)', self.v['amplitude'], 12, 'The level of the signal applied while a frequency / period / bandwidth is tested.')
            af.pack(fill='x', pady=(6, 0))
        rf = ttk.LabelFrame(body, text='Only on these ranges (none ticked = all)', padding=8)
        rf.pack(fill='x', pady=(8, 0))
        for rid, text in cat['ranges']:
            var = tk.BooleanVar(value=False)
            self.range_vars[rid] = var
            ttk.Checkbutton(rf, text=text, variable=var).pack(side='left', padx=4)
        self.msg = tk.StringVar()
        ttk.Label(body, textvariable=self.msg, foreground=ui.C['bad'], wraplength=ui.px(560), justify='left').pack(anchor='w', pady=(8, 0))
        bar, _ = row_buttons(body, ('OK', self.ok, 'Accent.TButton'), ('Cancel', self.destroy))
        bar.pack(anchor='e', pady=(10, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        self.load()
        self.layout()

    def load(self):
        form = self.model.rule_form(self.fid, self.rule_id) if self.rule_id else {}
        self.v['type'].set(label_of(self.type_pairs, form.get('type', 'percent_of_range')))
        for k in self.v:
            if k in form and k != 'type':
                self.v[k].set(form[k] if k not in ('freq_mode',) else label_of(self.freq_pairs, form[k]))
        if not form:
            self.v['freq_mode'].set(label_of(self.freq_pairs, 'list' if self.cat['needs_frequency'] else 'none'))
            self.v['percents'].set('10, 50, 100')
            self.v['nominal'].set('0')
        else:
            self.v['freq_mode'].set(label_of(self.freq_pairs, form.get('freq_mode', 'none')))
        self.bipolar.set(bool(form.get('bipolar'))), self.zero.set(bool(form.get('zero')))
        for rid in form.get('range_ids', []):
            if rid in self.range_vars:
                self.range_vars[rid].set(True)

    def layout(self):
        key = value_of(self.type_pairs, self.v['type'].get())
        self.help.configure(text=next((r['help'] for r in self.cat['rules'] if r['key'] == key), ''))

    def form(self):
        d = {k: v.get() for k, v in self.v.items()}
        d['type'] = value_of(self.type_pairs, d['type'])
        d['freq_mode'] = value_of(self.freq_pairs, d['freq_mode'])
        d['bipolar'], d['zero'] = self.bipolar.get(), self.zero.get()
        d['range_ids'] = [rid for rid, var in self.range_vars.items() if var.get()]
        return d

    def ok(self):
        form = self.form()
        res = self.model.update_rule(self.fid, self.rule_id, form) if self.rule_id else self.model.add_rule(self.fid, form)
        if not res.ok:
            self.msg.set(res.message)
            return
        self.outcome = res
        self.destroy()


class PointDialog(tk.Toplevel):
    """Add or edit one point by hand.  `outcome` holds the result (None = cancelled)."""

    def __init__(self, parent, model, fid, pid=None):
        super().__init__(parent)
        self.model, self.fid, self.pid, self.outcome = model, fid, pid, None
        self.title('Edit test point' if pid else 'Add a test point')
        self.transient(parent)
        fields = model.point_form_fields(fid)
        fn = model.fn(fid)
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        self.nominal, self.freq, self.amp, self.label, self.note, self.expect, self.range_var = (tk.StringVar() for _ in range(7))
        self.ranges = [('', 'Automatic (smallest range that holds it)')] + [(r.id, model.range_text(fn, r)) for r in fn.ranges] if fn else [('', 'Automatic')]
        f = Form(body, columns=1)
        f.entry(f'Nominal ({fields["unit"] or "value"})', self.nominal, 24, 'With a unit, for example 5 V or 100 mV.')
        if not pid:
            f.combo('Range', self.range_var, [lab for _v, lab in self.ranges], 34)
        if fields['frequency']:
            f.entry('Frequency', self.freq, 16, 'For example 1 kHz')
        if fields['amplitude']:
            f.entry('Stimulus level', self.amp, 16, 'For example 1 V')
        if fields['expect']:
            f.combo('Beeper should be', self.expect, ['on', 'off'], 8)
        f.entry('Label (optional)', self.label, 30)
        f.entry('Note for the operator (optional)', self.note, 40)
        f.pack(fill='x')
        self.msg = tk.StringVar()
        ttk.Label(body, textvariable=self.msg, foreground=ui.C['bad'], wraplength=ui.px(420), justify='left').pack(anchor='w', pady=(8, 0))
        bar, _ = row_buttons(body, ('OK', self.ok, 'Accent.TButton'), ('Cancel', self.destroy))
        bar.pack(anchor='e', pady=(10, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        if pid:
            d = model.point_detail(fid, pid)
            self.nominal.set(M.show(M.db.dec(d['nominal']), fn.unit))
            self.freq.set(M.show(M.db.dec(d['frequency']), 'Hz') if d['frequency'] else '')
            self.amp.set(M.show(M.db.dec(d['amplitude']), 'V') if d['amplitude'] else '')
            self.label.set(d['label']), self.note.set(d['note']), self.expect.set(d['expect'] or 'on')
        else:
            self.expect.set('on')

    def ok(self):
        if self.pid:
            res = self.model.edit_point(self.fid, self.pid, nominal=self.nominal.get(), frequency=self.freq.get(), amplitude=self.amp.get(), label=self.label.get(),
                                        note=self.note.get(), expect=self.expect.get() if self.model.point_form_fields(self.fid)['expect'] else None)
        else:
            res = self.model.add_point(self.fid, self.nominal.get(), value_of(self.ranges, self.range_var.get()) or None, self.freq.get(), self.amp.get(), self.label.get(), self.note.get(),
                                       self.expect.get() if self.model.point_form_fields(self.fid)['expect'] else None)
        if not res.ok:
            self.msg.set(res.message)
            return
        self.outcome = res
        self.destroy()


class AutomationPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_AUTOMATION)
        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Button(top, text='Check which standards can do this', style='Accent.TButton', command=self.run).pack(side='left')
        ttk.Button(top, text='What can the suite drive today?', command=self.drivers).pack(side='left', padx=8)
        self.fbar = FunctionBar(top, win, with_all=True, command=self.reload)
        self.fbar.pack(side='left', padx=12)
        self.filter = tk.StringVar(value=FILTER_LABELS[0][1])
        box = ttk.Combobox(top, textvariable=self.filter, values=[lab for _k, lab in FILTER_LABELS], state='readonly', width=30)
        box.pack(side='left')
        box.bind('<<ComboboxSelected>>', lambda _e: self.reload())
        self.summary = tk.StringVar(value='Press the button to look through the standards you imported.')
        self.summary_box = ui.Notice(self, kind='info', textvariable=self.summary, title='Result')
        self.summary_box.pack(fill='x', pady=(8, 6))
        cols = ('function', 'point', 'standard', 'mode', 'tar', 'tur', 'automation', 'message')
        self.table = ui.make_table(self, cols, ('Function', 'Point', 'Standard', 'Chosen', 'TAR', 'TUR', 'Can the suite run it?', 'Why / note'), (120, 150, 80, 80, 70, 70, 250, 340),
                                   anchors={'function': 'w', 'point': 'w', 'automation': 'w', 'message': 'w'}, height=9, pack=False, stretch={'mode': False, 'tar': False, 'tur': False})
        self.table.master.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.picked())
        pick = ttk.LabelFrame(self, text='Standard for the selected point', padding=8)
        pick.pack(fill='x', pady=(8, 0))
        self.cands = ui.make_table(pick, ('standard', 'covered', 'tur', 'tar', 'automation', 'why'), ('Standard', 'Covers it', 'TUR', 'TAR', 'Automation', 'Why not'), (80, 80, 70, 70, 250, 380),
                                   anchors={'automation': 'w', 'why': 'w'}, height=4, pack=False, stretch={'covered': False})
        self.cands.master.pack(fill='x')
        row = ttk.Frame(pick)
        row.pack(fill='x', pady=(6, 0))
        self.choice = tk.StringVar()
        self.choice_box = ttk.Combobox(row, textvariable=self.choice, state='readonly', width=50)
        self.choice_box.pack(side='left')
        ttk.Button(row, text='Use this standard for the point', command=self.apply_choice).pack(side='left', padx=8)
        ttk.Button(row, text='Clear all my choices', command=self.clear).pack(side='left')
        self._choices = []
        self._rows = {}

    def _filter(self):
        return value_of(FILTER_LABELS, self.filter.get())

    def reload(self):
        self.fbar.reload()
        m = self.model
        if m.match_result is None:
            fill(self.table, [], 'point_id', ())
            return
        stale = not m.match_fresh()
        rows = m.match_rows(self.fbar.fid or None, self._filter())
        self._rows = {r['point_id']: r for r in rows}
        fill(self.table, rows, 'point_id', ('function', 'point', 'standard', 'mode', 'tar', 'tur', 'automation', 'message'),
             tags=lambda r: {'bad': ('fail',), 'warn': ('error',)}.get(r['level'], ()))
        self.summary.set(m.match_summary_text() + (' (the datasheet changed since: check again)' if stale else ''))

    def run(self):
        res = self.model.run_match()
        self.say(res)
        if not res.ok:
            self.summary.set(res.message)
        self.reload()
        return res

    def picked(self):
        s = selected(self.table)
        if not s:
            return
        rows = self.model.candidate_rows(s[0])
        fill(self.cands, [dict(r, id=r['standard'], covered_text='yes' if r['covered'] else 'no', why=r['message']) for r in rows], 'id',
             ('standard', 'covered_text', 'tur', 'tar', 'automation', 'why'))
        self._choices = self.model.override_choices(s[0])
        self.choice_box.configure(values=[lab for _v, lab in self._choices])
        cur = self.model.ds.assignments.get(s[0], '')
        self.choice.set(label_of(self._choices, cur))

    def apply_choice(self):
        s = selected(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        res = self.say(self.model.set_assignment(s[0], value_of(self._choices, self.choice.get())))
        self.reload()
        return res

    def clear(self):
        if not self.model.ds.assignments:
            return self.say(M.Outcome(False, 'You have not chosen any standard by hand.'))
        res = self.say(self.model.clear_assignments())
        self.reload()
        return res

    def drivers(self):
        return DriversWindow(self.win, self.model)


class DriversWindow(tk.Toplevel):
    """Read-only: each standard, its driver, and what the driver can do for the functions of this datasheet."""

    def __init__(self, parent, model):
        super().__init__(parent)
        self.title('What the suite can drive today')
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        help_label(body, 'A standard can be able to produce a point (it covers it) without the suite having a driver to run it by itself. '
                         '"Commands not yet verified" means the driver exists but has not been confirmed on hardware.', 760).pack(anchor='w', pady=(0, 8))
        t = ui.make_table(body, ('model', 'role', 'driver', 'imported', 'functions'), ('Standard', 'Role', 'Driver', 'Spec imported', 'This datasheet\'s functions'), (90, 80, 150, 100, 520),
                          anchors={'model': 'w', 'role': 'w', 'driver': 'w', 'functions': 'w'}, height=10, zebra=True)
        rows = []
        for r in model.driver_rows():
            rows.append(dict(r, id=r['model'], imported_text='yes' if r['imported'] else 'no',
                             functions_text='; '.join(f'{k}: {v["text"]}' for k, v in r['functions'].items()) or '(nothing for these functions)'))
        fill(t, rows, 'id', ('model', 'role', 'driver', 'imported_text', 'functions_text'))
        ttk.Button(body, text='Close', command=self.destroy).pack(anchor='e', pady=(8, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        ui.fit_window(self, 1000, 440, min_w=700, min_h=300)


class ReviewPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_REVIEW)
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, justify='left', wraplength=ui.px(900)).pack(anchor='w')
        self.auto = tk.StringVar()
        ttk.Label(self, textvariable=self.auto, style='Muted.TLabel', justify='left', wraplength=ui.px(900)).pack(anchor='w', pady=(6, 0))
        ttk.Label(self, text='Everything that needs your attention', style='Section.TLabel').pack(anchor='w', pady=(10, 2))
        self.table = ui.make_table(self, ('level', 'step', 'where', 'message'), ('', 'Step', 'Where', 'What is wrong'), (70, 110, 260, 560), anchors={'where': 'w', 'message': 'w', 'step': 'w'},
                                   height=8, pack=False, stretch={'level': False, 'step': False})
        self.table.master.pack(fill='both', expand=True)
        self.table.bind('<Double-1>', lambda _e: self.go_to())
        self.can = tk.StringVar()
        self.note = tk.StringVar()
        ttk.Label(self, textvariable=self.can, style='Bold.TLabel', wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(8, 0))
        row = ttk.Frame(self)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='Note for this version (optional):').pack(side='left')
        ttk.Entry(row, textvariable=self.note, width=50).pack(side='left', padx=6)
        bar, self.buttons = row_buttons(self, ('Save new version', self.save, 'Accent.TButton'), ('Save as draft (not runnable)', self.save_draft), ('Version history...', self.history))
        bar.pack(fill='x', pady=(8, 0))
        self.result = tk.StringVar()
        ttk.Label(self, textvariable=self.result, wraplength=ui.px(900), justify='left').pack(anchor='w', pady=(6, 0))
        self._problems = []

    def reload(self):
        rv = self.model.review()
        self.summary.set('\n'.join(rv['lines']) + f"\n{rv['points']} test point(s) in total." + (f"\nBased on {rv['based_on']}." if rv['based_on'] else ''))
        self.auto.set(rv['automation'])
        self._problems = rv['problems']
        rows = [dict(p, id=i, level_text='ERROR' if p['level'] == 'error' else 'warning', step_text=M.STEPS[p['step']]['title'], where_text=p['location'] or p['where']) for i, p in enumerate(rv['problems'])]
        fill(self.table, rows, 'id', ('level_text', 'step_text', 'where_text', 'message'), tags=lambda r: ('fail',) if r['level'] == 'error' else ('error',))
        self.can.set(rv['save_text'])
        state = 'normal' if rv['can_save'] else 'disabled'
        self.buttons['Save new version'].configure(state=state)
        self.buttons['Save as draft (not runnable)'].configure(state='normal' if rv['can_save_draft'] and not rv['can_save'] else 'disabled')
        self.buttons['Version history...'].configure(state='normal' if self.model.ds.uid else 'disabled')

    def go_to(self):
        s = selected(self.table)
        if s and int(s[0]) < len(self._problems):
            self.win.goto_problem(self._problems[int(s[0])])

    def _save(self, draft):
        self.win.commit_page()
        res = self.model.save(self.note.get(), as_draft=draft)
        self.result.set(res.message)
        self.say(res)
        if res.ok:
            self.note.set('')
            self.win.saved()
        self.reload()
        return res

    def save(self):
        return self._save(False)

    def save_draft(self):
        return self._save(True)

    def history(self):
        return VersionsWindow(self.win, self.model.storage, self.model.ds.uid, editor=self.win)


# ------------------------------------------------------------------------------------------------------------------------------ editor window
class EditorWindow(tk.Toplevel):
    """The guided flow window for one datasheet."""

    def __init__(self, parent, model, panel=None):
        super().__init__(parent)
        self.model, self.panel = model, panel
        self.configure(background=ui.C['bg'])
        self.banner = ui.Banner(self, 'Datasheet Builder', 'Build a datasheet from the manufacturer\'s specification, step by step')
        self.banner.pack(fill='x')
        self.dirty_pill = self.banner.add_pill('', 'warn')
        self.steps = StepBar(self, model, self.go)
        self.steps.pack(fill='x', padx=14, pady=(10, 4))
        self.status = tk.StringVar(value='')
        ui.StatusBar(self, self.status).pack(side='bottom', fill='x')
        nav = ttk.Frame(self, padding=(14, 6))
        nav.pack(side='bottom', fill='x')
        self.back_b = ttk.Button(nav, text='‹ Back', command=self.back)
        self.back_b.pack(side='left')
        self.undo_b = ttk.Button(nav, text='Undo', command=self.undo)
        self.undo_b.pack(side='left', padx=(14, 4))
        self.redo_b = ttk.Button(nav, text='Redo', command=self.redo)
        self.redo_b.pack(side='left')
        self.next_b = ttk.Button(nav, text='Next ›', style='Accent.TButton', command=self.next)
        self.next_b.pack(side='right')
        self.problem_box = ttk.LabelFrame(self, text='Problems in this step', padding=(10, 4))
        self.problem_box.pack(side='bottom', fill='x', padx=14, pady=(0, 4))
        self.problems = ui.make_table(self.problem_box, ('level', 'where', 'message'), ('', 'Where', 'What is wrong'), (80, 260, 700), anchors={'where': 'w', 'message': 'w'}, height=3,
                                      stretch={'level': False})
        self.problems.bind('<Double-1>', lambda _e: self.open_problem())
        self.note = tk.StringVar()
        self.note_label = ttk.Label(self, textvariable=self.note, wraplength=ui.px(1000), justify='left')
        self.note_label.pack(side='bottom', anchor='w', padx=14)
        self.holder = ttk.Frame(self, padding=(14, 6))
        self.holder.pack(fill='both', expand=True)
        self.pages = [HeaderPage(self.holder, self), FunctionsPage(self.holder, self), RangesPage(self.holder, self), SpecPage(self.holder, self),
                      PointsPage(self.holder, self), AutomationPage(self.holder, self), ReviewPage(self.holder, self)]
        self._shown = None
        self._problem_rows = []
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-z>', lambda _e: self.undo())
        self.bind('<Control-y>', lambda _e: self.redo())
        ui.fit_window(self, 1240, 860, min_w=900, min_h=620)
        self.show()

    # ---- showing
    def commit_page(self):
        if self._shown is not None:
            self.pages[self._shown].commit()

    def show(self):
        step = self.model.step
        if self._shown is not None and self._shown != step:
            self.pages[self._shown].pack_forget()
        recalculated = None
        if step == M.S_POINTS and self._shown != step:
            recalculated = self.model.recalculate()             # rules -> points (edited and hand-made points are never touched)
        self.pages[step].pack(fill='both', expand=True)
        self._shown = step
        self.refresh()
        if recalculated is not None and recalculated.message != 'No point changed.':
            self.changed(recalculated)

    def refresh(self):
        if self._shown is None:
            return
        self.pages[self._shown].reload()
        self.steps.update_states()
        m = self.model
        self.title(('* ' if m.dirty else '') + m.title + ' - Datasheet Builder')
        self.dirty_pill.set('unsaved changes' if m.dirty else 'saved', 'warn' if m.dirty else 'good')
        self.back_b.configure(state='normal' if m.step > 0 else 'disabled')
        self.next_b.configure(state='normal' if m.step < len(M.STEPS) - 1 else 'disabled')
        self.undo_b.configure(text=f'Undo {m.undo_label}' if m.can_undo else 'Undo', state='normal' if m.can_undo else 'disabled')
        self.redo_b.configure(state='normal' if m.can_redo else 'disabled')
        probs = m.problems_for(step=m.step, function_id=m.fid if m.step in (M.S_RANGES, M.S_SPEC, M.S_POINTS) else None)
        self._problem_rows = probs
        rows = [dict(p, id=i, level_text='ERROR' if p['level'] == 'error' else 'warning', where_text=p['location'] or p['where']) for i, p in enumerate(probs)]
        fill(self.problems, rows, 'id', ('level_text', 'where_text', 'message'), tags=lambda r: ('fail',) if r['level'] == 'error' else ('error',))
        self.problem_box.configure(text=f'Problems in this step ({len(probs)})' if probs else 'No problems in this step')

    def changed(self, outcome=None):
        """Called by the pages after every action: status line, then redraw."""
        if outcome is not None:
            self.note.set(outcome.message if outcome.ok else 'Not done: ' + outcome.message)
            self.status.set(outcome.message if outcome.ok else 'Cannot do that: ' + outcome.message)
            try:
                self.note_label.configure(foreground=ui.C['good'] if outcome.ok else ui.C['bad'])
            except (tk.TclError, KeyError):
                pass
        self.refresh()

    # ---- navigation
    def go(self, step):
        self.commit_page()
        res = self.model.go(step)
        if not res.ok:
            self.changed(res)
            return res
        self.show()
        return res

    def next(self):
        return self.go(self.model.step + 1)

    def back(self):
        return self.go(self.model.step - 1)

    def goto_problem(self, problem):
        self.commit_page()
        self.model.goto_problem(problem)
        self.show()

    def open_problem(self):
        s = selected(self.problems)
        if s and int(s[0]) < len(self._problem_rows):
            self.goto_problem(self._problem_rows[int(s[0])])

    def undo(self):
        self.commit_page()
        self.changed(self.model.undo())

    def redo(self):
        self.changed(self.model.redo())

    def saved(self):
        if self.panel is not None:
            self.panel.editor_saved(self)

    def close(self):
        self.commit_page()
        if self.model.dirty and not messagebox.askyesno('Unsaved changes', 'This datasheet has changes that are not saved. Close without saving?', parent=self):
            return False
        if self.panel is not None:
            self.panel.editor_closed(self)
        self.destroy()
        return True


class VersionsWindow(tk.Toplevel):
    """Version history of one datasheet: open an old version in an editor, load it into the open editor, or export it."""

    def __init__(self, parent, storage, uid, editor=None, panel=None):
        super().__init__(parent)
        self.lst = M.DatasheetList(storage)
        self.uid, self.editor, self.panel = uid, editor, panel
        self.title(f'Version history: {uid}')
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        help_label(body, 'Every save is a new version and old versions are never changed. Opening an old version and saving it creates a newer version.', 760).pack(anchor='w', pady=(0, 6))
        self.table = ui.make_table(body, ('version', 'saved', 'who', 'status', 'points', 'note'), ('Version', 'Saved', 'By', 'Status', 'Points', 'Note'), (70, 170, 110, 150, 70, 300),
                                   anchors={'saved': 'w', 'who': 'w', 'status': 'w', 'note': 'w'}, height=10, zebra=True, stretch={'version': False, 'points': False})
        self.msg = tk.StringVar()
        ttk.Label(body, textvariable=self.msg, style='Muted.TLabel', wraplength=ui.px(700), justify='left').pack(anchor='w', pady=(6, 0))
        specs = [('Open in a new window', self.open_new, 'Accent.TButton')]
        if editor is not None:
            specs.append(('Load into the open editor', self.load_here))
        specs += [('Export JSON...', self.export), ('Close', self.destroy)]
        bar, _ = row_buttons(body, *specs)
        bar.pack(fill='x', pady=(8, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        self.reload()
        ui.fit_window(self, 900, 440, min_w=640, min_h=300)

    def reload(self):
        rows = self.lst.version_rows(self.uid)
        fill(self.table, [dict(r, id=r['version'], saved=r['saved_at'], status=r['status_text']) for r in rows], 'id', ('version', 'saved', 'who', 'status', 'points', 'note'))

    def _version(self):
        s = selected(self.table)
        return int(s[0]) if s else None

    def open_new(self):
        v = self._version()
        if v is None:
            self.msg.set('Select a version first.')
            return None
        ed = self.lst.open(self.uid, v)
        if ed is None:
            self.msg.set(self.lst.last_error)
            return None
        if self.panel is not None:
            return self.panel.open_editor(ed)
        return EditorWindow(self, ed)

    def load_here(self):
        v = self._version()
        if v is None:
            self.msg.set('Select a version first.')
            return None
        res = self.editor.model.load_version(v)
        self.editor.changed(res)
        self.msg.set(res.message)
        return res

    def export(self):
        v = self._version()
        if v is None:
            self.msg.set('Select a version first.')
            return None
        path = filedialog.asksaveasfilename(title='Export version as JSON', defaultextension='.json', initialfile=f'{self.uid}-v{v}.json', filetypes=[('JSON', '*.json')], parent=self)
        res = self.lst.export_json(self.uid, path, v)
        self.msg.set(res.message)
        return res


# ------------------------------------------------------------------------------------------------------------------------------ the tab
class DatasheetBuilderPanel(ttk.Frame):
    """The Manager's 'Datasheet Builder' tab: the list of user datasheets and the actions on them."""

    COLS = ('make', 'model', 'title', 'version', 'functions', 'points', 'automation', 'saved')

    def __init__(self, parent, storage=None, on_saved=None, status=None, matcher_factory=None):
        super().__init__(parent)
        self.lst = M.DatasheetList(storage, matcher_factory)
        self.on_saved, self.status, self.matcher_factory = on_saved, status, matcher_factory
        self.editors = {}
        help_label(self, 'Build a datasheet for any instrument from its manufacturer\'s specification: you describe the functions, ranges and accuracy, the builder works out the '
                         'test points and limits, finds which of your standards can supply them, and saves a procedure the suite can run. Everything you save is kept as a numbered '
                         'version. This is separate from the imported Cal Processor .MDD templates.', 950).pack(anchor='w', pady=(0, 10))
        bar = ttk.Frame(self)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Button(bar, text='New...', style='Accent.TButton', command=self.new).pack(side='left', padx=(0, 8))
        self.b_open = ttk.Button(bar, text='Open', command=self.open_selected)
        self.b_open.pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Duplicate', command=self.duplicate).pack(side='left', padx=(0, 8))
        self.b_delete = ttk.Button(bar, text='Delete', command=self.delete_or_restore)
        self.b_delete.pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Version history...', command=self.history).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Export JSON...', command=self.export).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Import JSON...', command=self.import_).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Refresh', command=self.refresh).pack(side='left')
        flt = ttk.Frame(self)
        flt.pack(fill='x', pady=(0, 6))
        ttk.Label(flt, text='Search').pack(side='left')
        self.search = tk.StringVar()
        ttk.Entry(flt, textvariable=self.search, width=34).pack(side='left', padx=6)
        self.search.trace_add('write', lambda *_: self.apply_search())
        self.show_deleted = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text='Show deleted', variable=self.show_deleted, command=self.toggle_deleted).pack(side='left', padx=12)
        self.table = ui.make_table(self, self.COLS, ('Make', 'Model', 'Title', 'Ver', 'Functions', 'Points', 'Automation', 'Last saved'), (110, 110, 220, 50, 220, 70, 280, 150),
                                   anchors={'make': 'w', 'model': 'w', 'title': 'w', 'functions': 'w', 'automation': 'w', 'saved': 'w'}, zebra=True,
                                   stretch={'version': False, 'points': False, 'saved': False})
        self.table.bind('<Double-1>', lambda _e: self.open_selected())
        self.table.bind('<<TreeviewSelect>>', lambda _e: self.selection_changed())
        self.empty = ttk.Label(self.table.master, text='', style='Muted.TLabel', justify='center')
        self.message = tk.StringVar(value='')
        ttk.Label(self, textvariable=self.message, wraplength=ui.px(950), justify='left').pack(anchor='w', pady=(6, 0))
        self._rows = {}
        self.apply_search()                                    # empty until the tab is first shown: the Manager calls refresh() then

    # ---- list
    def say(self, text):
        self.message.set(text)
        if self.status is not None:
            try:
                self.status.set(text)
            except (tk.TclError, AttributeError):
                pass

    def refresh(self):
        self.lst.refresh()
        self.apply_search()

    def apply_search(self):
        self.lst.search = self.search.get()
        rows = self.lst.rows()
        self._rows = {r['uid']: r for r in rows}
        fill(self.table, rows, 'uid', self.COLS, tags=lambda r: ('pending',) if r['deleted'] else ('error',) if r['status'] == 'draft' else ())
        self.empty.configure(text=self.lst.empty_text())
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.45, anchor='center')
            self.empty.lift()
        self.selection_changed()
        return rows

    def toggle_deleted(self):
        self.lst.show_deleted = self.show_deleted.get()
        self.refresh()

    def _uid(self):
        s = selected(self.table)
        return s[0] if s else ''

    def selection_changed(self):
        row = self._rows.get(self._uid())
        self.b_delete.configure(text='Restore' if row and row['deleted'] else 'Delete')
        self.b_open.configure(state='disabled' if row and row['deleted'] else 'normal')

    def _need(self):
        uid = self._uid()
        if not uid:
            self.say('Select a datasheet in the list first.')
        return uid

    # ---- actions
    def new(self):
        return self.open_editor(self.lst.new())

    def open_selected(self):
        uid = self._need()
        if not uid:
            return None
        if self._rows.get(uid, {}).get('deleted'):
            self.say('This datasheet is deleted. Restore it first.')
            return None
        win = self.editors.get(uid)
        if win is not None:
            try:
                win.lift()
                win.focus_force()
                return win
            except tk.TclError:
                self.editors.pop(uid, None)
        ed = self.lst.open(uid)
        if ed is None:
            self.say(f'Could not read datasheet {uid}: the file is missing or damaged.')
            return None
        return self.open_editor(ed)

    def open_editor(self, model):
        win = EditorWindow(self.winfo_toplevel(), model, panel=self)
        win._key = model.ds.uid or f'new-{id(win)}'
        self.editors[win._key] = win
        return win

    def editor_saved(self, win):
        uid = win.model.ds.uid
        old = getattr(win, '_key', None)
        if old != uid and old in self.editors:
            self.editors.pop(old, None)
        self.editors[uid] = win
        win._key = uid
        self.refresh()
        self.say(win.model.last_save and f'Saved version {win.model.last_save.version} of {uid}.' or 'Saved.')
        if self.on_saved is not None:
            try:
                self.on_saved()
            except Exception as exc:                       # the Manager's own refresh must never break a save that has already succeeded
                self.say(f'Saved, but the procedure list could not be refreshed: {exc}')

    def editor_closed(self, win):
        key = getattr(win, '_key', None)
        if self.editors.get(key) is win:
            self.editors.pop(key, None)

    def duplicate(self):
        uid = self._need()
        if not uid:
            return None
        row = self._rows[uid]
        title = simpledialog.askstring('Duplicate datasheet', 'Title of the copy:', initialvalue=f'{row["title"]} (copy)', parent=self.winfo_toplevel())
        if not title:
            return None
        res = self.lst.duplicate(uid, title)
        self.say(res.message)
        self.apply_search()
        return res

    def delete_or_restore(self):
        uid = self._need()
        if not uid:
            return None
        row = self._rows[uid]
        if row['deleted']:
            res = self.lst.restore(uid)
        else:
            if not messagebox.askyesno('Delete datasheet', f'Delete "{row["title"]}"? It leaves the Procedures list. Every version is kept and you can restore it '
                                       f'(tick "Show deleted").', parent=self.winfo_toplevel()):
                return None
            res = self.lst.delete(uid)
        self.say(res.message)
        self.apply_search()
        if self.on_saved is not None and res.ok:
            try:
                self.on_saved()
            except Exception:
                pass
        return res

    def history(self):
        uid = self._need()
        if not uid:
            return None
        return VersionsWindow(self.winfo_toplevel(), self.lst.storage, uid, panel=self)

    def export(self):
        uid = self._need()
        if not uid:
            return None
        path = filedialog.asksaveasfilename(title='Export datasheet as JSON', defaultextension='.json', initialfile=f'{uid}.json', filetypes=[('JSON', '*.json')],
                                            parent=self.winfo_toplevel())
        res = self.lst.export_json(uid, path)
        self.say(res.message)
        return res

    def import_(self):
        path = filedialog.askopenfilename(title='Import a datasheet JSON (or a runnable spec made by the builder)', filetypes=[('JSON', '*.json'), ('All files', '*.*')],
                                          parent=self.winfo_toplevel())
        if not path:
            return None
        res = self.lst.import_json(path)
        self.say(res.message)
        self.apply_search()
        if res.ok and self.on_saved is not None:
            try:
                self.on_saved()
            except Exception:
                pass
        return res
