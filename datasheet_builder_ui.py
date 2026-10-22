"""Tk widgets for the Datasheet Builder (thin: every decision lives in datasheet_builder_ui_model.py, which is unit-tested without tkinter).

    import datasheet_builder_ui as dsb_ui
    panel = dsb_ui.DatasheetBuilderPanel(parent_frame, on_saved=callback)       # the Manager's 'Datasheet Builder' tab
    panel.refresh()                                                             # when the tab is shown

The tab lists the user datasheets (New / Open / Duplicate / Delete + Restore / Export JSON / Import JSON / Version history).  Opening one shows
the grid editor window: a spreadsheet-like sheet (one row per test point) with an Edit Cell bar above it, the spec boxes (Select Spec Types, Calc / Recalc)
below it and a tool column at the right.  The older detail pages (Ranges, Specification table, Sections, Details, Standards and automation) open from the
More menu.  Messages (error / warning, with the row) show under the sheet and in the Warnings list.  Anyone can use it (there is no developer-mode lock).
Display-only SI scaling: the model formats values, the datasheet keeps SI.

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
        self.hint.configure(text=f'Type values with their unit, for example {M.show(M.db.D(10), fn.unit)} or {M.show(M.db.D("0.1"), fn.unit)}.' if fn else 'Add a section first (More > Sections and function settings).')

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


# ------------------------------------------------------------------------------------------------------------------------------ the sheet
class SheetCanvas(tk.Canvas):
    """The big spreadsheet-like grid: heading, row numbers, one row per test point, empty rows at the end.  Drawing and 'which cell is here'
    come from M.GridGeometry; what a row shows comes from the model.  Click a cell to select it; the window handles the keys."""

    def __init__(self, parent, model, on_click, on_key, on_edit):
        super().__init__(parent, background=ui.C['table'], highlightthickness=1, highlightbackground=ui.C['border_strong'], takefocus=1)
        self.model, self.on_click, self.on_key, self.on_edit = model, on_click, on_key, on_edit
        self.geo = M.GridGeometry(row_h=ui.px(30), head_h=ui.px(44), num_w=ui.px(48), widths=[ui.px(c['width']) for c in M.GRID_COLUMNS])
        self.top = 0
        self.scrollbar = None
        self._cw = ui.px(7)
        self.bind('<Button-1>', self._click)
        self.bind('<Double-Button-1>', lambda _e: self.on_edit())
        self.bind('<Key>', lambda e: self.on_key(e))
        self.bind('<Configure>', lambda _e: self.redraw())
        self.bind('<MouseWheel>', self._wheel)
        self.bind('<Button-4>', lambda _e: self.scroll_cmd('scroll', -3, 'units'))
        self.bind('<Button-5>', lambda _e: self.scroll_cmd('scroll', 3, 'units'))

    # ---- size and scrolling
    def _size(self):
        try:
            w, h = int(self.winfo_width()), int(self.winfo_height())
        except (TypeError, ValueError, tk.TclError):
            w = h = 0
        return (w if w > 80 else ui.px(1000)), (h if h > 80 else ui.px(480))

    def _wheel(self, e):
        try:
            self.scroll_cmd('scroll', -1 if e.delta > 0 else 1, 'units')
        except (TypeError, AttributeError):
            pass

    def scroll_cmd(self, *args):
        """The scrollbar's command: ('moveto', fraction) or ('scroll', n, 'units' | 'pages')."""
        w, h = self._size()
        n = len(self.model.rows())
        room = self.geo.max_top(n, h)
        if args and args[0] == 'moveto':
            self.top = int(float(args[1]) * (n * self.geo.row_h))
        elif len(args) >= 3 and args[0] == 'scroll':
            step = self.geo.row_h if args[2] == 'units' else max(self.geo.row_h, h - self.geo.head_h - self.geo.row_h)
            self.top += int(args[1]) * step
        self.top = max(0, min(room, self.top))
        self.redraw()

    def see(self, key=None):
        """Scroll so the selected row shows."""
        i = self.model.row_index(key)
        if i is None:
            return
        _w, h = self._size()
        self.top = self.geo.top_for(i, self.top, h)

    # ---- drawing
    def _fit(self, text, width):
        if not text:
            return ''
        n = max(1, int((width - ui.px(12)) // self._cw))
        return text if len(text) <= n else text[:max(1, n - 1)] + '…'

    def redraw(self):
        try:
            self.delete('all')
            w, h = self._size()
            geo, rows = self.geo, self.model.rows()
            geo.fit(w - ui.px(4))
            self.top = max(0, min(self.top, geo.max_top(len(rows), h)))
            c = ui.C
            sel_key, sel_col = self.model.sel_key, M.COL_KEYS.index(self.model.sel_col)
            first, last = geo.visible(self.top, h, len(rows))
            for r in range(first, last):
                row = rows[r]
                x0, y0, x1, y1 = geo.box(r, 0, self.top)
                is_sel = row['key'] == sel_key
                self.create_rectangle(0, y0, geo.num_w, y1, fill=c['select'] if is_sel else c['head'], outline=c['border_strong'])
                self.create_text(geo.num_w / 2, (y0 + y1) / 2, text=str(row['n']), fill=c['muted'], font=self._bold)
                if row['kind'] == 'header':
                    self.create_rectangle(geo.num_w, y0, geo.width, y1, fill=c['head_hi'], outline=c['border_strong'])
                    label = row['function'] + (f'   - {row["problem"]}' if row['problem'] and row['level'] == 'error' else '')
                    self.create_text(geo.num_w + ui.px(10), (y0 + y1) / 2, text=self._fit(label, geo.width - geo.num_w), anchor='w',
                                     fill=c['bad'] if row['problem'] and row['level'] == 'error' else c['text'], font=self._bold)
                    if is_sel:
                        self.create_rectangle(geo.num_w + 1, y0 + 1, geo.width - 1, y1 - 1, outline=c['primary'], width=2)
                    continue
                for ci, col in enumerate(M.GRID_COLUMNS):
                    cx0, cy0, cx1, cy1 = geo.box(r, ci, self.top)
                    selected_cell = is_sel and ci == sel_col
                    fill = c['primary'] if selected_cell else (c['bad_bg'] if col['key'] in row['bad'] and row['level'] == 'error' else
                                                                  c['warn_bg'] if col['key'] in row['bad'] else c['select'] if is_sel else c['table'])
                    self.create_rectangle(cx0, cy0, cx1, cy1, fill=fill, outline=c['border_strong'])
                    text = self._fit(row.get(col['key'], ''), cx1 - cx0)
                    if not text:
                        continue
                    color = c['on_primary'] if selected_cell else c['muted'] if (not row['enabled'] and row['kind'] == 'point') else c['text']
                    if col['align'] == 'center':
                        self.create_text((cx0 + cx1) / 2, (cy0 + cy1) / 2, text=text, fill=color, font=self._font)
                    else:
                        self.create_text(cx0 + ui.px(8), (cy0 + cy1) / 2, text=text, anchor='w', fill=color, font=self._font)
            # the heading is drawn last so scrolled rows slide under it
            self.create_rectangle(0, 0, geo.width, geo.head_h, fill=c['head'], outline=c['border_strong'])
            self.create_text(geo.num_w / 2, geo.head_h / 2, text='#', fill=c['muted'], font=self._bold)
            for ci, col in enumerate(M.GRID_COLUMNS):
                x0 = geo.col_x(ci)
                self.create_rectangle(x0, 0, x0 + geo.widths[ci], geo.head_h, fill=c['head'], outline=c['border_strong'])
                self.create_text(x0 + geo.widths[ci] / 2, geo.head_h / 2, text=self._fit(col['title'], geo.widths[ci]) if len(col['title']) < 14 else col['title'],
                                 fill=c['text'], font=self._bold, width=max(20, geo.widths[ci] - ui.px(8)), justify='center')
            if self.scrollbar is not None:
                total = max(1, len(rows) * geo.row_h)
                self.scrollbar.set(self.top / total, min(1.0, (self.top + h - geo.head_h) / total))
        except tk.TclError:                       # the window is closing
            pass

    @property
    def _font(self):
        return 'TkDefaultFont'

    @property
    def _bold(self):
        return 'CalBold'

    # ---- mouse
    def _click(self, event):
        self.focus_set()
        rows = self.model.rows()
        r = self.geo.row_at(event.y, len(rows), self.top)
        c = self.geo.col_at(event.x)
        if r is None or r < 0 or c is None:
            return
        self.on_click(r, 0 if c < 0 else c)


# ------------------------------------------------------------------------------------------------------------------------------ small dialogs
class ChoiceDialog(tk.Toplevel):
    """Pick one thing from a list (a function for a new section).  `value` is the chosen label, None when cancelled."""

    def __init__(self, parent, title, prompt, labels, initial=''):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.value = None
        self.var = tk.StringVar(value=initial or (labels[0] if labels else ''))
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=prompt, wraplength=ui.px(420), justify='left').pack(anchor='w')
        self.box = ttk.Combobox(body, textvariable=self.var, values=list(labels), state='readonly', width=46)
        self.box.pack(anchor='w', pady=(8, 10))
        bar, _ = row_buttons(body, ('OK', self.ok, 'Accent.TButton'), ('Cancel', self.destroy))
        bar.pack(anchor='e')
        self.bind('<Return>', lambda _e: self.ok())
        self.bind('<Escape>', lambda _e: self.destroy())

    def ok(self):
        self.value = self.var.get()
        self.destroy()


def ask_choice(parent, title, prompt, labels, initial=''):
    dlg = ChoiceDialog(parent, title, prompt, labels, initial)
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    parent.wait_window(dlg)
    return dlg.value


class PageDialog(tk.Toplevel):
    """One of the older detail pages (Ranges, Specification table, Sections, Details, Standards) in its own window over the sheet."""

    def __init__(self, owner, title, page_cls, width=1000, height=640):
        super().__init__(owner)
        self.owner = owner
        self.title(title)
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        self.page = page_cls(body, owner)
        self.page.pack(fill='both', expand=True)
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=(8, 0))
        ttk.Button(bar, text='Close', command=self.close).pack(side='right')
        self.bind('<Escape>', lambda _e: self.close())
        self.page.reload()
        ui.fit_window(self, width, height, min_w=720, min_h=420)

    def reload(self):
        self.page.reload()

    def close(self):
        self.page.commit()
        self.destroy()


class ProblemsWindow(tk.Toplevel):
    """Everything that needs attention, in plain words.  Double-click one to go to its row."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.title('Problems on this datasheet')
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        self.summary = tk.StringVar()
        ttk.Label(body, textvariable=self.summary, style='Bold.TLabel').pack(anchor='w', pady=(0, 6))
        self.table = ui.make_table(body, ('level', 'row', 'text'), ('', 'Row', 'What to do'), (90, 60, 760), anchors={'text': 'w'}, height=10, zebra=False,
                                   stretch={'level': False, 'row': False})
        self.table.bind('<Double-1>', lambda _e: self.go())
        bar, _ = row_buttons(body, ('Go to the row', self.go, 'Accent.TButton'), ('Close', self.destroy))
        bar.pack(anchor='e', pady=(8, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        self._rows = []
        self.reload()
        ui.fit_window(self, 980, 440, min_w=640, min_h=300)

    def reload(self):
        m = self.owner.model
        self._rows = m.problem_rows()
        self.summary.set(m.problem_summary())
        rows = [dict(r, id=i, level_text='FIX' if r['level'] == 'error' else 'warning', row_text=r['row'] or '') for i, r in enumerate(self._rows)]
        fill(self.table, rows, 'id', ('level_text', 'row_text', 'text'), tags=lambda r: ('fail',) if r['level'] == 'error' else ('error',))

    def go(self):
        s = selected(self.table)
        if not s or int(s[0]) >= len(self._rows):
            return None
        row = self._rows[int(s[0])]
        if row['key']:
            self.owner.goto_row(row['key'])
        return row


class PreviewWindow(tk.Toplevel):
    """The blank datasheet as it would print, with Save as PDF.  As Found and As Left are empty: it is a template, not a record."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        view = owner.model.print_view()
        self.view = view
        self.title('Print preview: ' + view['title'])
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=view['title'], style='Section.TLabel').pack(anchor='w')
        ttk.Label(body, text=view['subtitle'], style='Muted.TLabel').pack(anchor='w')
        ui.Notice(body, kind='warn', text=view['notice']).pack(fill='x', pady=(6, 8))
        keys = tuple(f'c{i}' for i in range(len(view['columns'])))
        self.table = ui.make_table(body, keys, view['columns'], (70, 220, 170, 110, 110, 60, 260), anchors={'c1': 'w', 'c2': 'w', 'c6': 'w'}, height=14, zebra=False)
        for i, row in enumerate(view['rows']):
            self.table.insert('', 'end', iid=str(i), values=row['cells'], tags=('pending',) if row['kind'] == 'header' else ())
        self.msg = tk.StringVar()
        ttk.Label(body, textvariable=self.msg, style='Muted.TLabel', wraplength=ui.px(800), justify='left').pack(anchor='w', pady=(6, 0))
        bar, _ = row_buttons(body, ('Save as PDF to print...', self.save_pdf, 'Accent.TButton'), ('Close', self.destroy))
        bar.pack(anchor='e', pady=(8, 0))
        self.bind('<Escape>', lambda _e: self.destroy())
        ui.fit_window(self, 1000, 560, min_w=700, min_h=360)

    def save_pdf(self):
        m = self.owner.model
        name = ('-'.join(x for x in (m.ds.make, m.ds.model, 'blank datasheet') if x) or 'blank datasheet').replace(' ', '_') + '.pdf'
        path = filedialog.asksaveasfilename(title='Save the blank datasheet as PDF', defaultextension='.pdf', initialfile=name, filetypes=[('PDF', '*.pdf')], parent=self)
        if not path:
            return None
        res = m.write_sheet_pdf(path)
        self.msg.set(res.message)
        return res


# ------------------------------------------------------------------------------------------------------------------------------ the boxes under the sheet
class SpecPanel(ttk.Frame):
    """Select Spec Types, the matching entry fields, the options row, Calc / Recalc and the Test Point Definitions list.  It only shows and collects
    values: M.GridModel.panel_state() fills it and M.GridModel.calc_row() uses what form() returns."""

    def __init__(self, parent, win):
        super().__init__(parent, padding=(8, 6))
        self.win = win
        self.sides = {'plus': M.GridModel.blank_side(), 'minus': M.GridModel.blank_side()}
        self.operand_now = 'plus'
        self.v = {k: tk.StringVar() for k in ('nominal', 'units', 'freq', 'level', 'expect', 'iv', 'fs', 'fs_scale', 'floor', 'db', 'calc', 'multi_high', 'multi_n',
                                              'decs', 'res', 'operand', 'multi_mode', 'func', 'definition')}
        self.b = {k: tk.BooleanVar(value=False) for k in ('iv_ppm', 'multi', 'asym', 'auto_res')}
        self.types = {k: tk.BooleanVar(value=False) for k in M.SPEC_ORDER}
        self.cells = {}
        self._defs = []
        self._choices = []
        self._state = {}

        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Label(top, text='This row tests:', style='Bold.TLabel').pack(side='left')
        self.func_box = ttk.Combobox(top, textvariable=self.v['func'], state='readonly', width=34)
        self.func_box.pack(side='left', padx=(6, 18))
        self.func_box.bind('<<ComboboxSelected>>', lambda _e: self.win.function_chosen(self.v['func'].get()))
        ttk.Label(top, text='Select Spec Types:', style='Bold.TLabel').pack(side='left')
        for key, label, hint in M.SPEC_TYPES:
            cb = ttk.Checkbutton(top, text=label, variable=self.types[key], command=self.types_changed)
            cb.pack(side='left', padx=(10, 0))
            tip(cb, hint)

        box = ttk.LabelFrame(self, text='Entry fields', padding=(8, 4))
        box.pack(fill='x', pady=(6, 0))
        self.box = box

        def cell(name, label, var, width, row, col, hint='', widget=None):
            f = ttk.Frame(box)
            ttk.Label(f, text=label, style='Small.TLabel').pack(anchor='w')
            e = widget(f) if widget else ttk.Entry(f, textvariable=var, width=width)
            e.pack(anchor='w')
            if hint:
                tip(e, hint)
            f.grid(row=row, column=col, sticky='w', padx=(0, 10), pady=2)
            self.cells[name] = f
            return e

        self.nominal_e = cell('nominal', 'Nominal Value', self.v['nominal'], 14, 0, 0, 'The value to test, for example 5. The unit comes from Units of Measure.')
        self.units_c = cell('units', 'Units of Measure', self.v['units'], 12, 0, 1, 'The unit the numbers in these boxes are in. Display only.',
                            widget=lambda f: ttk.Combobox(f, textvariable=self.v['units'], width=10))
        self.units_b = ttk.Button(box, text='...', width=3, command=self.pick_unit)
        self.units_b.grid(row=0, column=2, sticky='sw', pady=2)
        tip(self.units_b, 'Pick the unit from a list (mV, V, kV ...).')
        cell('iv', '% of I.V.', self.v['iv'], 10, 0, 3, 'How many percent of the value being tested, for example 0.05.')
        self.cells['iv_ppm'] = ttk.Checkbutton(box, text='ppm', variable=self.b['iv_ppm'])
        self.cells['iv_ppm'].grid(row=0, column=4, sticky='sw', pady=2)
        tip(self.cells['iv_ppm'], 'Tick when the number is parts per million of the value instead of percent.')
        cell('fs', '% of F.S.', self.v['fs'], 10, 0, 5, 'How many percent of the full scale, for example 0.01.')
        cell('fs_scale', 'F.S. (full scale)', self.v['fs_scale'], 12, 0, 6, 'The full scale of the range this row is on, for example 10 V. Leave it as it is to keep the range.')
        cell('floor', 'Floor (fixed value)', self.v['floor'], 12, 0, 7, 'A fixed amount added to the tolerance, in the Units of Measure, for example 20.')
        cell('db', '± dB', self.v['db'], 8, 0, 8, 'A tolerance in dB, for example 0.5.')
        cell('calc', 'Calculator: type the accuracy statement', self.v['calc'], 46, 1, 0, 'For example 0.05 % of reading + 2 counts. Same wording as the manual.')
        self.cells['calc'].grid(columnspan=4)
        cell('freq', 'Frequency', self.v['freq'], 12, 1, 4, 'For AC and frequency tests, with its unit, for example 1 kHz.')
        cell('level', 'Signal level', self.v['level'], 10, 1, 5, 'The level of the signal applied while a frequency, period or bandwidth is tested, for example 1 V.')
        cell('expect', 'Beeper should be', self.v['expect'], 8, 1, 6, widget=lambda f: ttk.Combobox(f, textvariable=self.v['expect'], values=['on', 'off'], state='readonly', width=6))
        self.multi_cb = ttk.Checkbutton(box, text='Multiple Test Points', variable=self.b['multi'], command=self.multi_changed)
        self.multi_cb.grid(row=2, column=0, sticky='w', pady=(4, 0))
        tip(self.multi_cb, 'Make several rows at once: Nominal Value is the lowest, High is the last. Choose below how the rows are spaced.')
        cell('multi_high', 'High', self.v['multi_high'], 12, 2, 1, 'The last value the rows should reach.')
        cell('multi_n', 'n', self.v['multi_n'], 8, 2, 3, 'How many points (Lo to High) or the size of the step (n %, n Units, n ppm).')
        self.asym_cb = ttk.Checkbutton(box, text='Asymmetrical Tol', variable=self.b['asym'], command=self.asym_changed)
        self.asym_cb.grid(row=3, column=0, sticky='w')
        tip(self.asym_cb, 'The tolerance below the nominal differs from the one above it. Use Operand to switch between entering the + side and the - side.')

        opt = ttk.Frame(self)
        opt.pack(fill='x', pady=(6, 0))
        modes = ttk.Frame(opt)
        modes.pack(side='left', padx=(0, 14))
        self.v['multi_mode'].set('span')
        for i, (key, label, hint) in enumerate(M.MULTI_MODES):
            rb = ttk.Radiobutton(modes, text=label, value=key, variable=self.v['multi_mode'])
            rb.grid(row=i % 2, column=i // 2, sticky='w', padx=(0, 10))
            tip(rb, hint)
        dec = ttk.Frame(opt)
        dec.pack(side='left', padx=(0, 14))
        ttk.Label(dec, text='Display Decs.').grid(row=0, column=0, sticky='w')
        de = ttk.Entry(dec, textvariable=self.v['decs'], width=4)
        de.grid(row=0, column=1, padx=4)
        tip(de, 'How many decimal places the instrument shows in these units, for example 4 for 5.0000. Auto Res turns it into the resolution.')
        ttk.Label(dec, text='Operand').grid(row=1, column=0, sticky='w')
        self.operand_box = ttk.Combobox(dec, textvariable=self.v['operand'], values=['±', '+', '-'], state='disabled', width=3)
        self.operand_box.grid(row=1, column=1, padx=4)
        self.operand_box.bind('<<ComboboxSelected>>', lambda _e: self.operand_changed())
        tip(self.operand_box, 'With Asymmetrical Tol ticked: which side (+ or -) the boxes above are for.')
        res = ttk.Frame(opt)
        res.pack(side='left', padx=(0, 14))
        ttk.Label(res, text='Meas Res').grid(row=0, column=0, sticky='w')
        self.res_e = ttk.Entry(res, textvariable=self.v['res'], width=12, state='disabled')
        self.res_e.grid(row=0, column=1, padx=4)
        tip(self.res_e, 'The smallest step the instrument display shows in this range, for example 10 µV. Rows on the same range share it.')
        self.auto_cb = ttk.Checkbutton(res, text='Auto Res', variable=self.b['auto_res'], command=self.auto_changed)
        self.auto_cb.grid(row=1, column=0, columnspan=2, sticky='w')
        tip(self.auto_cb, 'Work the resolution out from Display Decs (or from the decimals you typed in Nominal Value).')
        self.calc_b = ttk.Button(opt, text='Calc', style='Accent.TButton', command=self.win.calc)
        self.calc_b.pack(side='left', padx=(0, 6))
        tip(self.calc_b, 'Work out the calibration tolerance of this row from the boxes and put it in the sheet.')
        self.recalc_b = ttk.Button(opt, text='Recalc', command=self.win.recalc)
        self.recalc_b.pack(side='left', padx=(0, 6))
        tip(self.recalc_b, 'Re-run the test point rules and check every row of the sheet.')
        self.copy_b = ttk.Button(opt, text='Copy tolerance to rows below', command=self.win.copy_down)
        self.copy_b.pack(side='left', padx=(0, 14))
        tip(self.copy_b, 'Give the rows under this one, in the same section, the same tolerance as this row.')
        defs = ttk.Frame(opt)
        defs.pack(side='left', fill='x', expand=True)
        ttk.Label(defs, text='Test Point Definitions:').pack(anchor='w')
        self.def_box = ttk.Combobox(defs, textvariable=self.v['definition'], state='readonly', width=44)
        self.def_box.pack(anchor='w')
        self.def_box.bind('<<ComboboxSelected>>', lambda _e: self.win.definition_chosen(self.v['definition'].get()))
        tip(self.def_box, 'The rules of the test point calculator for this section. Pick one to change it.')
        self.note = tk.StringVar()
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', wraplength=ui.px(1000), justify='left').pack(anchor='w', pady=(4, 0))

    # ---- visibility
    def types_changed(self):
        self.show_fields()

    def multi_changed(self):
        self.show_fields()

    def auto_changed(self):
        self.res_e.configure(state='disabled' if self.b['auto_res'].get() else 'normal')

    def asym_changed(self):
        self.save_side()
        self.operand_box.configure(state='readonly' if self.b['asym'].get() else 'disabled')
        if not self.b['asym'].get():
            self.operand_now = 'plus'
            self.v['operand'].set('±')
            self.load_side()
        else:
            self.v['operand'].set('+')

    def operand_changed(self):
        self.save_side()
        self.operand_now = 'minus' if self.v['operand'].get() == '-' else 'plus'
        self.load_side()

    def save_side(self):
        s = self.sides[self.operand_now]
        s.update(iv=self.v['iv'].get(), iv_ppm=self.b['iv_ppm'].get(), fs=self.v['fs'].get(), floor=self.v['floor'].get(), db=self.v['db'].get(), calc=self.v['calc'].get())

    def load_side(self):
        s = self.sides[self.operand_now]
        self.v['iv'].set(s['iv']), self.b['iv_ppm'].set(bool(s['iv_ppm'])), self.v['fs'].set(s['fs']), self.v['floor'].set(s['floor']), self.v['db'].set(s['db'])
        self.v['calc'].set(s['calc'])

    def show_fields(self):
        st = self._state
        fields = st.get('fields', {})
        want = {'iv': self.types['iv'].get(), 'iv_ppm': self.types['iv'].get(), 'fs': self.types['fs'].get(), 'fs_scale': self.types['fs'].get(),
                'floor': self.types['floor'].get(), 'db': self.types['db'].get(), 'calc': self.types['calc'].get(), 'freq': fields.get('frequency', False),
                'level': fields.get('amplitude', False), 'expect': fields.get('expect', False), 'multi_high': self.b['multi'].get(), 'multi_n': self.b['multi'].get()}
        if st.get('passfail'):
            for k in ('iv', 'iv_ppm', 'fs', 'fs_scale', 'floor', 'db', 'calc'):
                want[k] = False
        for name, widget in self.cells.items():
            if name in want and not want[name]:
                widget.grid_remove()
            elif name in want:
                widget.grid()

    # ---- the unit picker
    def pick_unit(self):
        choices = self._state.get('unit_choices') or []
        if not choices:
            return None
        menu = tk.Menu(self, tearoff=0)
        for u in choices:
            menu.add_command(label=u, command=lambda u=u: self.v['units'].set(u))
        try:
            menu.tk_popup(self.units_b.winfo_rootx(), self.units_b.winfo_rooty() + self.units_b.winfo_height())
        except tk.TclError:
            pass
        return menu

    # ---- model <-> boxes
    def load(self, state):
        """Fill the boxes from M.GridModel.panel_state()."""
        self._state = state
        form = state['form']
        self.sides = {'plus': dict(form['plus']), 'minus': dict(form['minus'])}
        self.operand_now = 'plus'
        for k in ('nominal', 'units', 'freq', 'level', 'expect', 'fs_scale', 'multi_high', 'multi_n', 'decs', 'res', 'multi_mode'):
            self.v[k].set(form[k])
        for k in M.SPEC_ORDER:
            self.types[k].set(k in form['types'])
        self.b['multi'].set(bool(form['multi'])), self.b['asym'].set(bool(form['asym'])), self.b['auto_res'].set(bool(form['auto_res']))
        self.v['operand'].set('+' if form['asym'] else '±')
        self.operand_box.configure(state='readonly' if form['asym'] else 'disabled')
        self.load_side()
        self.units_c.configure(values=state['unit_choices'])
        self._choices = self.win.model.function_choices()
        self.func_box.configure(values=[c['label'] for c in self._choices])
        self.v['func'].set(state['function'])
        self.func_box.configure(state='readonly' if state['can_edit'] or state['kind'] == 'blank' else 'disabled')
        defs = self.win.model.definition_rows(state['fid']) if state['fid'] else []
        self._defs = defs
        self.def_box.configure(values=['New rule...'] + [d['label'] for d in defs])
        self.v['definition'].set('')
        self.auto_changed()
        self.show_fields()
        self.note.set(state['note'])
        usable = 'normal' if state['can_edit'] else 'disabled'
        for b in (self.calc_b, self.copy_b):
            b.configure(state=usable)

    def form(self):
        """The boxes as a form dict for M.GridModel.calc_row()."""
        self.save_side()
        asym = bool(self.b['asym'].get())
        return dict(types=[k for k in M.SPEC_ORDER if self.types[k].get()], plus=dict(self.sides['plus']), minus=dict(self.sides['minus']), asym=asym,
                    operand='-' if self.v['operand'].get() == '-' else '+', fs_scale=self.v['fs_scale'].get(), nominal=self.v['nominal'].get(), units=self.v['units'].get(),
                    freq=self.v['freq'].get(), level=self.v['level'].get(), expect=self.v['expect'].get() or 'on', multi=bool(self.b['multi'].get()),
                    multi_mode=self.v['multi_mode'].get() or 'span', multi_high=self.v['multi_high'].get(), multi_n=self.v['multi_n'].get(), decs=self.v['decs'].get(),
                    res=self.v['res'].get(), auto_res=bool(self.b['auto_res'].get()))

    def definition_id(self, label):
        return next((d['id'] for d in self._defs if d['label'] == label), None)


# ------------------------------------------------------------------------------------------------------------------------------ the window
class GridEditorWindow(tk.Toplevel):
    """One datasheet as a big grid: Edit Cell bar and toolbar on top, the sheet in the middle, the tool column at the right, the spec boxes below.
    Every decision is in M.GridModel; this class draws it and passes clicks and keys to it."""

    def __init__(self, parent, model, panel=None):
        super().__init__(parent)
        self.model, self.panel = model, panel
        self.dialogs = []
        self.configure(background=ui.C['bg'])
        self.banner = ui.Banner(self, 'Datasheet Builder', 'One row per test point. Click a cell, type, press Enter.')
        self.banner.pack(fill='x')
        self.dirty_pill = self.banner.add_pill('', 'warn')
        self.problem_pill = self.banner.add_pill('', 'good')
        self.status = tk.StringVar(value='')
        ui.StatusBar(self, self.status).pack(side='bottom', fill='x')
        self.note = tk.StringVar()
        self.note_label = ttk.Label(self, textvariable=self.note, wraplength=ui.px(1100), justify='left')
        self.note_label.pack(side='bottom', anchor='w', padx=14)
        self.issue = tk.StringVar()
        self.issue_label = ttk.Label(self, textvariable=self.issue, wraplength=ui.px(1100), justify='left')
        self.issue_label.pack(side='bottom', anchor='w', padx=14)
        self.panel_box = SpecPanel(self, self)
        self.panel_box.pack(side='bottom', fill='x', padx=6)

        main = ttk.Frame(self, padding=(10, 6))
        main.pack(fill='both', expand=True)
        self._build_header(main)
        self._build_editbar(main)
        mid = ttk.Frame(main)
        mid.pack(fill='both', expand=True, pady=(6, 0))
        self._build_tools(mid)
        sheet_holder = ttk.Frame(mid)
        sheet_holder.pack(side='left', fill='both', expand=True)
        self.sheet = SheetCanvas(sheet_holder, model, self.sheet_click, self.sheet_key, self.focus_bar)
        sb = ttk.Scrollbar(sheet_holder, orient='vertical', command=self.sheet.scroll_cmd)
        self.sheet.scrollbar = sb
        sb.pack(side='right', fill='y')
        self.sheet.pack(side='left', fill='both', expand=True)

        self.protocol('WM_DELETE_WINDOW', self.close)
        for seq, fn in (('<Control-z>', self.undo), ('<Control-y>', self.redo), ('<Control-s>', self.save), ('<Control-p>', self.preview)):
            self.bind(seq, lambda _e, fn=fn: (fn(), 'break')[1])
        ui.fit_window(self, 1340, 900, min_w=1000, min_h=700)
        self.sync()

    # ---- building
    def _build_header(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill='x')
        self.make_v, self.model_v, self.title_v = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.make_e = self.model_e = self.title_e = None
        for label, var, width, hint in (('Make', self.make_v, 16, 'The manufacturer, for example Keysight.'), ('Model', self.model_v, 14, 'For example 34461A.'),
                                        ('Title', self.title_v, 34, 'What the procedure list shows, for example 34461A Performance Verification.')):
            ttk.Label(bar, text=label, style='Bold.TLabel').pack(side='left', padx=(0, 4))
            e = ttk.Entry(bar, textvariable=var, width=width)
            e.pack(side='left', padx=(0, 12))
            setattr(self, {'Make': 'make_e', 'Model': 'model_e', 'Title': 'title_e'}[label], e)
            e.bind('<FocusOut>', lambda _e: self.commit_header())
            e.bind('<Return>', lambda _e: self.commit_header())
            tip(e, hint)
        self.period_v = tk.StringVar()
        self.period_label = ttk.Label(bar, text='Tolerances for')
        self.period_box = ttk.Combobox(bar, textvariable=self.period_v, state='readonly', width=14)
        self.period_box.bind('<<ComboboxSelected>>', lambda _e: self.period_chosen())
        right = ttk.Frame(bar)
        right.pack(side='right')
        self.undo_b = ttk.Button(right, text='Undo', command=self.undo)
        self.undo_b.pack(side='left', padx=(0, 4))
        self.redo_b = ttk.Button(right, text='Redo', command=self.redo)
        self.redo_b.pack(side='left', padx=(0, 10))
        ttk.Button(right, text='Standards...', command=self.open_standards).pack(side='left', padx=(0, 4))
        more = ttk.Menubutton(right, text='More')
        menu = tk.Menu(more, tearoff=0)
        for label, cmd in (('Test point calculator...', self.open_calculator), ('Ranges...', self.open_ranges), ('Specification table (advanced)...', self.open_spec),
                           ('Sections and function settings...', self.open_functions), ('Details and time periods...', self.open_details),
                           ('What can the suite drive today?', self.open_drivers), ('Version history...', self.open_versions)):
            menu.add_command(label=label, command=cmd)
        more.configure(menu=menu)
        self.more_menu = menu
        more.pack(side='left')

    def _build_editbar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=(8, 0))
        ttk.Label(bar, text='Edit Cell:', style='Bold.TLabel').pack(side='left', padx=(0, 6))
        self.bar_v = tk.StringVar()
        self.bar = ttk.Entry(bar, textvariable=self.bar_v)
        self.bar.pack(side='left', fill='x', expand=True)
        self.bar.bind('<Return>', lambda _e: self.commit_bar('down'))
        self.bar.bind('<KP_Enter>', lambda _e: self.commit_bar('down'))
        self.bar.bind('<Tab>', lambda _e: self.commit_bar('right') or 'break')
        self.bar.bind('<Escape>', lambda _e: self.cancel_bar())
        tip(self.bar, 'Type the new content of the selected cell and press Enter. Esc puts the old text back.')
        for text, cmd, hint in (('Print / Preview', self.preview, 'See the blank datasheet as it prints, and save it as a PDF.'),
                                ('Save', self.save, 'Save a new version (Ctrl+S).'),
                                ('Calculate', self.calc, 'Work out the tolerance of the selected row from the boxes below (same as Calc).')):
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side='left', padx=(6, 0))
            tip(b, hint)

    def _build_tools(self, parent):
        col = ttk.Frame(parent, padding=(8, 0, 0, 0))
        col.pack(side='right', fill='y')
        ttk.Label(col, text='Lock Status', style='Bold.TLabel').pack(anchor='w')
        self.lock_v = tk.StringVar(value=M.LOCK_MODES[0][1])
        lock = ttk.Combobox(col, textvariable=self.lock_v, values=[lab for _k, lab in M.LOCK_MODES], state='readonly', width=14)
        lock.pack(anchor='w', pady=(2, 10))
        lock.bind('<<ComboboxSelected>>', lambda _e: self.lock_chosen())
        tip(lock, 'Locked: nothing can be changed by accident. Edit Mode: you can change the sheet.')
        ttk.Label(col, text='Copy symbol to the Edit Cell', style='Bold.TLabel').pack(anchor='w')
        grid = ttk.Frame(col)
        grid.pack(anchor='w', pady=(2, 10))
        self.symbol_buttons = {}
        for i, name in enumerate(M.SYMBOLS + ('Units',)):
            b = ttk.Button(grid, text=name, width=3 if name != 'Units' else 6, style='Compact.TButton', command=lambda n=name: self.insert_symbol(n))
            b.grid(row=i // 3, column=i % 3, padx=1, pady=1)
            self.symbol_buttons[name] = b
        ttk.Label(col, text='Special Ops', style='Bold.TLabel').pack(anchor='w')
        self.header_b = ttk.Button(col, text='Ins. Header', command=self.insert_header)
        self.header_b.pack(anchor='w', fill='x', pady=(2, 2))
        tip(self.header_b, 'Add a new section heading (a new function to test) after the selected row.')
        self.break_b = ttk.Button(col, text='Page Break', state='disabled')
        self.break_b.pack(anchor='w', fill='x', pady=(0, 2))
        tip(self.break_b, 'Not available: the report decides where its pages end.')
        self.delete_b = ttk.Button(col, text='Delete row', style='Danger.TButton', command=self.delete_row)
        self.delete_b.pack(anchor='w', fill='x', pady=(0, 10))
        ttk.Label(col, text='Warnings', style='Bold.TLabel').pack(anchor='w')
        self.warn_v = tk.StringVar()
        ttk.Label(col, textvariable=self.warn_v, wraplength=ui.px(170), justify='left').pack(anchor='w')
        ttk.Button(col, text='Show list', command=self.show_problems).pack(anchor='w', fill='x', pady=(2, 10))
        ttk.Label(col, text='Row level remark', style='Bold.TLabel').pack(anchor='w')
        self.remark_v = tk.StringVar()
        re_ = ttk.Entry(col, textvariable=self.remark_v, width=22)
        re_.pack(anchor='w', pady=(2, 2))
        re_.bind('<Return>', lambda _e: self.remark_set())
        re_.bind('<FocusOut>', lambda _e: self.remark_set(quiet=True))
        tip(re_, 'A note the operator sees with this row. A * appears next to its step number.')
        self.run_v = tk.BooleanVar(value=True)
        rc = ttk.Checkbutton(col, text='Run this row', variable=self.run_v, command=self.run_set)
        rc.pack(anchor='w')
        tip(rc, 'Untick to keep the row on the sheet but leave it out of the procedure.')

    # ---- showing
    def sync(self):
        """Redraw the sheet and fill the Edit Cell bar and the boxes from the model."""
        m = self.model
        row = m.select()
        self.sheet.see()
        self.sheet.redraw()
        ok, why = m.cell_editable()
        self.bar_v.set(m.cell_text())
        self.bar.configure(state='normal' if ok else 'readonly')
        state = m.panel_state()
        self.panel_box.load(state)
        self.remark_v.set(state['form']['remark']), self.run_v.set(bool(state['form']['run']))
        self.set_issue(row, ok, why)

    def set_issue(self, row, ok=True, why=''):
        text = f'Row {row["n"]}: {row["problem"]}' if row['problem'] else ''
        self.issue.set(text or ('' if ok else why))
        try:
            self.issue_label.configure(foreground=ui.C['bad'] if row['level'] == 'error' else ui.C['warn'] if row['problem'] else ui.C['muted'])
        except (tk.TclError, KeyError):
            pass

    def refresh(self):
        m = self.model
        ds = m.ds
        for var, val, e in ((self.make_v, ds.make, self.make_e), (self.model_v, ds.model, self.model_e), (self.title_v, ds.title, self.title_e)):
            if var.get() != val and self.focus_get() is not e:
                var.set(val)
        self.title(('* ' if m.dirty else '') + m.title + ' - Datasheet Builder')
        self.dirty_pill.set('unsaved changes' if m.dirty else 'saved', 'warn' if m.dirty else 'good')
        c = m.problem_counts()
        self.problem_pill.set(f'{c["errors"]} to fix' if c['errors'] else f'{c["warnings"]} warning(s)' if c['warnings'] else 'no problems', 'bad' if c['errors'] else 'warn' if c['warnings'] else 'good')
        self.warn_v.set(m.problem_summary())
        self.undo_b.configure(state='normal' if m.can_undo else 'disabled')
        self.redo_b.configure(state='normal' if m.can_redo else 'disabled')
        if len(ds.periods) > 1:
            self.period_label.pack(side='left', padx=(0, 4))
            self.period_box.pack(side='left')
            self.period_box.configure(values=[p.label or p.id for p in ds.periods])
            self.period_v.set(next((p.label or p.id for p in ds.periods if p.id == m.period), ''))
        else:
            self.period_label.pack_forget()
            self.period_box.pack_forget()
        self.sync()
        for d in list(self.dialogs):
            try:
                d.reload()
            except tk.TclError:
                self.dialogs.remove(d)

    def changed(self, outcome=None):
        """After every action: the message (green / red), then redraw everything."""
        if outcome is not None:
            msg = outcome.message if outcome.ok else 'Not done: ' + outcome.message
            self.note.set(msg)
            self.status.set(outcome.message if outcome.ok else 'Cannot do that: ' + outcome.message)
            try:
                self.note_label.configure(foreground=ui.C['good'] if outcome.ok else ui.C['bad'])
            except (tk.TclError, KeyError):
                pass
        self.refresh()
        return outcome

    def commit_page(self):
        """Hook the detail pages use before they close (nothing is held back in this window)."""

    # ---- the sheet
    def sheet_click(self, r, c):
        self.commit_bar_if_changed()
        self.model.select_at(r, c)
        self.sync()

    def goto_row(self, key):
        self.model.select(key, 'nominal')
        self.sync()
        self.focus_force()

    def sheet_key(self, e):
        ks = e.keysym
        state = int(getattr(e, 'state', 0) or 0)
        ctrl = bool(state & 0x4)
        if ctrl:
            return None
        act = self.model.nav(ks, shift=bool(state & 0x1))
        if act == 'moved':
            self.sync()
            return 'break'
        if act == 'edit':
            self.focus_bar(select_all=True)
            return 'break'
        if ks in ('Delete', 'BackSpace'):
            self.changed(self.model.clear_cell())
            return 'break'
        ch = getattr(e, 'char', '')
        if ch and ch.isprintable() and not ch.isspace() or ch == ' ':
            ok, why = self.model.cell_editable()
            if not ok:
                self.set_issue(self.model.selected_row(), False, why)
                return 'break'
            self.bar_v.set(ch)
            self.focus_bar()
            return 'break'
        return None

    def focus_bar(self, select_all=False):
        ok, why = self.model.cell_editable()
        if not ok:
            self.set_issue(self.model.selected_row(), False, why)
            return
        self.bar.focus_set()
        try:
            if select_all:
                self.bar.selection_range(0, 'end')
            self.bar.icursor('end')
        except tk.TclError:
            pass

    def commit_bar_if_changed(self):
        if self.bar_v.get() != self.model.cell_text() and self.model.cell_editable()[0] and str(self.focus_get()) == str(self.bar):
            self.commit_bar('stay')

    def commit_bar(self, move='down'):
        """Enter (down) or Tab (right) in the Edit Cell bar."""
        ok, why = self.model.cell_editable()
        if not ok:
            self.set_issue(self.model.selected_row(), False, why)
            return None
        res = self.model.commit_cell(self.bar_v.get(), move=move)
        self.changed(res)
        self.sheet.focus_set()
        return res

    def cancel_bar(self):
        self.bar_v.set(self.model.cell_text())
        self.sheet.focus_set()

    # ---- header strip
    def commit_header(self):
        ds = self.model.ds
        new = dict(make=self.make_v.get().strip(), model=self.model_v.get().strip(), title=self.title_v.get().strip())
        if new == dict(make=ds.make, model=ds.model, title=ds.title):
            return None
        return self.changed(self.model.set_header(**new))

    def period_chosen(self):
        label = self.period_v.get()
        pid = next((p.id for p in self.model.ds.periods if (p.label or p.id) == label), '')
        if pid and self.model.set_period(pid):
            self.refresh()

    # ---- the buttons
    def calc(self):
        self.commit_header()
        form = self.panel_box.form()
        form.update(remark=self.remark_v.get(), run=bool(self.run_v.get()))
        return self.changed(self.model.calc_row(form=form))

    def recalc(self):
        return self.changed(self.model.recalc_all())

    def copy_down(self):
        n = self.model.would_overwrite()
        if n and not messagebox.askyesno('Copy tolerance', f'{n} row(s) below already have a tolerance of their own. Replace them with this row\'s tolerance? (Undo brings them back.)', parent=self):
            return None
        return self.changed(self.model.copy_tolerance())

    def function_chosen(self, label):
        row = self.model.selected_row()
        if row['kind'] == 'blank':
            return self.changed(self.model.set_target_function(label))
        if row['kind'] == 'point':
            res = self.model.move_point(row['key'], label)
            if res.ok and isinstance(res.detail, str):
                self.model.select(res.detail)
            return self.changed(res)
        return None

    def definition_chosen(self, label):
        rid = self.panel_box.definition_id(label)
        if label == 'New rule...' or rid is None:
            return self.open_calculator()
        return self.open_calculator(rid)

    def insert_symbol(self, name):
        sym = self.model.symbol_text(name)
        if not sym:
            return None
        target = self.focus_get()
        entry = target if isinstance(target, ttk.Entry) else self.bar
        try:
            entry.insert('insert', sym)
            if entry is self.bar:
                self.bar.focus_set()
            self.clipboard_clear()
            self.clipboard_append(sym)
        except tk.TclError:
            pass
        return sym

    def insert_header(self):
        labels = [c['label'] for c in self.model.function_choices() if c['label'].startswith('New section: ')]
        pick = ask_choice(self, 'Ins. Header', 'What does the new section test?', [x[len('New section: '):] for x in labels])
        if not pick:
            return None
        return self.changed(self.model.add_section(pick))

    def delete_row(self):
        row = self.model.selected_row()
        if row['kind'] == 'header':
            fn = self.model.ds.function(row['fid'])
            if not messagebox.askyesno('Delete section', f'Delete the section "{fn.name}" with its {len(fn.points)} row(s)? (Undo brings it back.)', parent=self):
                return None
        return self.changed(self.model.clear_row())

    def remark_set(self, quiet=False):
        row = self.model.selected_row()
        if row['kind'] != 'point':
            return None
        fn, p = self.model.point_of()
        if p is None or p.note == self.remark_v.get().strip():
            return None
        return self.changed(self.model.set_remark(row['key'], self.remark_v.get()))

    def run_set(self):
        row = self.model.selected_row()
        if row['kind'] != 'point':
            return None
        return self.changed(self.model.set_run(row['key'], bool(self.run_v.get())))

    def lock_chosen(self):
        res = self.model.set_locked(self.lock_v.get() == M.LOCK_MODES[1][1])
        return self.changed(res)

    def show_problems(self):
        win = ProblemsWindow(self)
        self.dialogs.append(win)
        return win

    def preview(self):
        return PreviewWindow(self)

    # ---- the other windows
    def _page(self, title, cls, **kw):
        dlg = PageDialog(self, title, cls, **kw)
        self.dialogs.append(dlg)
        return dlg

    def open_ranges(self):
        return self._page('Ranges', RangesPage)

    def open_spec(self):
        return self._page('Specification table (advanced)', SpecPage)

    def open_functions(self):
        return self._page('Sections and function settings', FunctionsPage, width=1000, height=620)

    def open_details(self):
        return self._page('Details and time periods', HeaderPage, width=980, height=560)

    def open_standards(self):
        self.commit_header()
        return self._page('Standards and automation', AutomationPage, width=1180, height=700)

    def open_drivers(self):
        return DriversWindow(self, self.model)

    def open_versions(self):
        if not self.model.ds.uid:
            return self.changed(M.Outcome(False, 'Nothing to show yet: save the datasheet once first.'))
        return VersionsWindow(self, self.model.storage, self.model.ds.uid, editor=self, panel=self.panel)

    def open_calculator(self, rule_id=None):
        fn = self.model.fn()
        if fn is None:
            return self.changed(M.Outcome(False, 'Click a row (or choose a function) first: the calculator makes rows for one section.'))
        if not fn.ranges:
            return self.changed(M.Outcome(False, 'This section has no ranges yet. Add a test row first (its range follows from its value), or open More > Ranges.'))
        dlg = RuleDialog(self, self.model, fn.id, rule_id)
        self.wait_window(dlg)
        if dlg.outcome is not None:
            return self.changed(dlg.outcome)
        return None

    # ---- undo / save / close
    def undo(self):
        return self.changed(self.model.undo())

    def redo(self):
        return self.changed(self.model.redo())

    def save(self, note=''):
        self.commit_header()
        res = self.model.save_sheet(note)
        if not res.ok and isinstance(res.detail, dict) and res.detail.get('needs_draft'):
            if messagebox.askyesno('Save as a draft?', res.message + '\n\nSave it as a draft now? A draft is kept as a version but is not a runnable procedure yet.', parent=self):
                res = self.model.save_sheet(note, as_draft=True)
            else:
                return self.changed(res)
        self.changed(res)
        if res.ok:
            self.saved()
        return res

    def saved(self):
        if self.panel is not None:
            self.panel.editor_saved(self)

    def close(self):
        self.commit_header()
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
        return GridEditorWindow(self, ed)

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
                         'version. This is separate from the Mudcats Datasheet Importer tab (Cal Processor .MDD templates).', 950).pack(anchor='w', pady=(0, 10))
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
            self.say(self.lst.last_error if self.lst.refused else f'Could not read datasheet {uid}: the file is missing or damaged.')
            return None
        return self.open_editor(ed)

    def open_editor(self, model):
        win = GridEditorWindow(self.winfo_toplevel(), model, panel=self)
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
            why = self.lst.storage.lock_reason(uid)
            if why:                                                   # verified on hardware and locked: say so before asking anything
                self.say(why)
                return None
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
