"""Datasheet Builder (Qt): the detail pages that open from the editor's More menu (Details and time periods, Sections and function settings, Ranges,
Specification table, Standards and automation).  Ports of the datasheet_builder_ui pages: each shows the model and passes what is typed back to it
(`reload()` re-reads the model, `commit()` pushes typed-but-not-applied text in).  No Tk import."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

import datasheet_builder_ui_model as M
from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.screens.dsb_dialogs import DriversWindow
from qtui.table import Column
from qtui.theme import M as SZ

ALL_FUNCTIONS = '(all functions)'
MODE_LABELS = {'both': 'Both sides (nominal ± tolerance)', 'low_only': 'Low side only (reading must not be below)', 'high_only': 'High side only (reading must not be above)'}
BASIS_LABELS = (('', 'Ask me (a % must say of reading or of range)'), ('reading', 'A plain % means % of reading'), ('range', 'A plain % means % of range'))
FILTER_LABELS = (('all', 'All points'), ('uncovered', 'Not covered by any standard'), ('cannot', 'Cannot be automated'), ('unverified', 'Commands not yet verified'))


def db_modes():
    return M.db.MODES


class FocusEdit(QLineEdit):
    focused = Signal()

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.focused.emit()


class Page(QWidget):
    """One step of the flow.  `reload()` re-reads the model; `commit()` pushes typed-but-not-applied text into it."""

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.model = win.model
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(SZ.sm)

    def reload(self):
        pass

    def commit(self):
        pass

    def say(self, outcome):
        self.win.changed(outcome)
        return outcome

    def intro(self, step):
        self.root.addWidget(C.hint(M.STEPS[step]['help']))

    def box(self, title):
        card, lay = C.group(title)
        self.root.addWidget(card)
        return lay


class FunctionBar(QWidget):
    """'Function: [DC volts v]' picker shared by the pages that work on one function at a time."""

    def __init__(self, win, with_all=False, command=None, parent=None):
        super().__init__(parent)
        self.win, self.with_all, self.command = win, with_all, command
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widgets.label('Function:', 'section'))
        self.box = QComboBox()
        self.box.setMinimumWidth(260)
        self.box.activated.connect(lambda _i: self.picked())
        lay.addWidget(self.box)
        lay.addStretch(1)
        self.ids = {}
        self.all = with_all                                   # '(all functions)' is chosen (the default where it exists)

    def reload(self):
        rows = self.win.model.function_rows()
        self.ids = {f'{r["name"]} ({r["id"]})' if sum(1 for x in rows if x['name'] == r['name']) > 1 else r['name']: r['id'] for r in rows}
        names = list(self.ids)
        if self.with_all:
            names = [ALL_FUNCTIONS] + names
        C.set_items(self.box, names)
        cur = self.win.model.fid
        label = next((n for n, i in self.ids.items() if i == cur), '')
        C.Bind(self.box).set(ALL_FUNCTIONS if self.with_all and self.all else label or (names[0] if names else ''))

    def picked(self):
        self.all = self.with_all and self.box.currentText() == ALL_FUNCTIONS
        if not self.all:
            self.win.model.select_function(self.ids.get(self.box.currentText(), ''))
        if self.command:
            self.command()

    @property
    def fid(self):
        return '' if self.with_all and self.all else self.ids.get(self.box.currentText(), self.win.model.fid)


class HeaderPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_HEADER)
        form = C.Form(columns=1)
        self.fields = {}
        for key, label, tip_text in (('make', 'Make (manufacturer)', 'For example Keysight, Fluke, Tektronix.'), ('model', 'Model', 'For example 34461A.'),
                                     ('title', 'Title', 'What the procedure list shows, for example "34461A Performance Verification".'),
                                     ('revision', 'Document / revision', 'Optional: which manual or revision you copied the specification from.'),
                                     ('notes', 'Notes', 'Optional notes for yourself.')):
            e = form.entry(label, 70, tip_text)
            e.editingFinished.connect(self.commit)
            self.fields[key] = C.Bind(e)
        self.make, self.mdl, self.title, self.revision, self.notes = (self.fields[k] for k in ('make', 'model', 'title', 'revision', 'notes'))
        self.root.addWidget(form)
        self.root.addWidget(widgets.label('Time periods the specification is valid for', 'section'))
        self.root.addWidget(C.hint('One period is enough. Add more (for example 90 days and 1 year) when the manual prints a different accuracy for each; '
                                   'you then type the specification once per period. The default period is the one the procedure uses.'))
        self.periods = C.table([Column('id', 'Id', 100), Column('label', 'Name', 240, stretch=True), Column('default_text', 'Default', 90)])
        self.periods.setMaximumHeight(170)
        self.root.addWidget(self.periods)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(190)
        self.preset = C.Bind(self.preset_box)
        bl.addWidget(self.preset_box)
        bl.addWidget(C.button('Add this period', self.add_preset))
        bl.addSpacing(12)
        bl.addWidget(QLabel('or your own  id'))
        self.custom_id_e, self.custom_label_e = QLineEdit(), QLineEdit()
        self.custom_id_e.setMaximumWidth(90)
        self.custom_label_e.setMaximumWidth(170)
        self.custom_id, self.custom_label = C.Bind(self.custom_id_e), C.Bind(self.custom_label_e)
        bl.addWidget(self.custom_id_e)
        bl.addWidget(QLabel('name'))
        bl.addWidget(self.custom_label_e)
        bl.addWidget(C.button('Add', self.add_custom))
        bl.addSpacing(12)
        bl.addWidget(C.button('Make default', self.make_default))
        bl.addWidget(C.button('Remove period', self.remove))
        bl.addStretch(1)
        self.root.addWidget(bar)
        self.outward_cb = QCheckBox('Round the limits outward to the display resolution (never tighter than the exact limit)')
        self.outward_cb.clicked.connect(lambda _c=False: self.set_rounding())
        self.manual_cb = QCheckBox('Manual calibration: no automation, the technician types every reading into the test point grid (listed under Manual Calibrations)')
        self.manual_cb.clicked.connect(lambda _c=False: self.set_manual())
        self.outward, self.manual = C.Bind(self.outward_cb), C.Bind(self.manual_cb)
        self.root.addSpacing(8)
        self.root.addWidget(self.outward_cb)
        self.root.addWidget(self.manual_cb)
        self.root.addStretch(1)

    def commit(self):
        ds = self.model.ds
        new = {k: v.get() for k, v in self.fields.items()}
        old = dict(make=ds.make, model=ds.model, title=ds.title, revision=ds.revision, notes=ds.notes)
        if {k: v.strip() for k, v in new.items()} == {k: v.strip() for k, v in old.items()}:
            return
        self.say(self.model.set_header(**new))

    def reload(self):
        ds = self.model.ds
        for var, val in ((self.make, ds.make), (self.mdl, ds.model), (self.title, ds.title), (self.revision, ds.revision), (self.notes, ds.notes)):
            if var.get() != val:
                var.set(val)
        C.fill(self.periods, [dict(r, default_text='yes' if r['default'] else '') for r in self.model.period_rows()])
        C.set_items(self.preset_box, [f"{p['id']}  ({p['label']})" for p in self.model.period_presets() if not p['used']])
        self.outward.set(ds.options.get('limit_rounding') == 'outward')
        self.manual.set(bool(ds.options.get('manual_entry')))

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
        s = C.selected_ids(self.periods)
        return s[0] if s else ''

    def make_default(self):
        self.commit()
        return self.say(self.model.set_default_period(self._sel())) if self._sel() else self.say(M.Outcome(False, 'Select a period first.'))

    def remove(self):
        self.commit()
        pid = self._sel()
        if not pid:
            return self.say(M.Outcome(False, 'Select a period first.'))
        if not C.ask_yes_no(self.win, 'Remove period', f'Remove the period "{pid}" and the specification text typed for it?'):
            return None
        return self.say(self.model.remove_period(pid))

    def set_rounding(self):
        self.commit()
        self.say(self.model.set_limit_rounding(self.outward.get()))

    def set_manual(self):
        self.say(self.model.set_manual_entry(self.manual.get()))


class FunctionsPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_FUNCTIONS)
        panes = QHBoxLayout()
        left = QVBoxLayout()
        self.table = C.table([Column('name', 'Function', 200, stretch=True), Column('kind', 'Kind', 130), Column('direction', 'Direction', 110),
                              Column('ranges', 'Ranges', 70, align='right'), Column('points', 'Points', 70, align='right'), Column('problems', 'Errors', 70, align='right')])
        self.table.selectionChangedRows.connect(lambda _r: self.picked())
        left.addWidget(self.table, 1)
        bar, _ = C.button_row(('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1)), ('Remove function', self.remove, 'danger'))
        left.addWidget(bar)
        panes.addLayout(left, 3)
        right, rl = C.group('Add a function')
        rl.addWidget(QLabel('What does it measure or output?'))
        self.kind_box = QComboBox()
        self.kinds = {}
        rl.addWidget(self.kind_box)
        rl.addWidget(QLabel('Name (optional, shown on the procedure)'))
        self.name_e = QLineEdit()
        self.name_var = C.Bind(self.name_e)
        rl.addWidget(self.name_e)
        rl.addWidget(C.button('Add function', self.add, 'primary'), 0, Qt.AlignmentFlag.AlignLeft)
        panes.addWidget(right, 2)
        self.root.addLayout(panes, 1)
        self.detail, dl = C.group('Selected function')
        self.dform = C.Form(columns=2)
        self.d_name = C.Bind(self.dform.entry('Name', 30))
        self.dir_box = self.dform.combo('Direction', [], 60, 'Who measures and who supplies?')
        self.d_dir = C.Bind(self.dir_box)
        self.d_switch = C.Bind(self.dform.entry('Tell the operator to select', 40, 'Shown at the start of this function, for example "DC volts, auto range off".'))
        dl.addWidget(self.dform)
        self.setting_holder = QWidget()
        self.setting_lay = QVBoxLayout(self.setting_holder)
        self.setting_lay.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.setting_holder)
        dl.addWidget(C.button('Apply changes', self.apply), 0, Qt.AlignmentFlag.AlignLeft)
        self.root.addWidget(self.detail)
        self.setting_vars = {}
        self._dirs = []

    def reload(self):
        m = self.model
        kinds = m.kind_choices()
        self.kinds = {f"{k['group_label']}: {k['label']}": k['kind'] for k in kinds}
        keep = self.kind_box.currentText()
        C.set_items(self.kind_box, list(self.kinds))
        C.Bind(self.kind_box).set(keep if keep in self.kinds else next(iter(self.kinds), ''))
        C.fill(self.table, m.function_rows())
        if m.fid:
            C.select_id(self.table, m.fid)
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
        C.set_items(self.dir_box, [lab for _v, lab in self._dirs])
        self.dir_box.setEnabled(len(self._dirs) > 1)
        self.d_dir.set(C.label_of(self._dirs, fn.direction))
        while self.setting_lay.count():
            it = self.setting_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.setting_vars = {}
        f = C.Form(columns=3)
        for fld in m.setting_fields(fn.id):
            box = f.combo(fld['label'], fld['choices'], 10)
            var = C.Bind(box)
            var.set(fld['value'])
            self.setting_vars[fld['key']] = var
        self.setting_lay.addWidget(f)

    def picked(self):
        s = C.selected_ids(self.table)
        if s:
            self.model.select_function(s[0])
            self.reload_detail()

    def add(self):
        res = self.say(self.model.add_function(self.kinds.get(self.kind_box.currentText(), ''), self.name_var.get()))
        if res.ok:
            self.name_var.set('')
        return res

    def apply(self):
        fid = self.model.fid
        if not fid:
            return self.say(M.Outcome(False, 'Select a function first.'))
        res = self.model.set_function(fid, name=self.d_name.get(), direction=C.value_of(self._dirs, self.d_dir.get()) if self._dirs else None, switch=self.d_switch.get())
        for key, var in self.setting_vars.items():
            res = self.model.set_function_setting(fid, key, var.get()) if res.ok else res
        return self.say(res)

    def remove(self):
        fn = self.model.fn()
        if fn is None:
            return self.say(M.Outcome(False, 'Select a function first.'))
        if not C.ask_yes_no(self.win, 'Remove function', f'Remove {fn.name} with its ranges, specification and {len(fn.points)} point(s)? (Undo brings it back.)'):
            return None
        return self.say(self.model.remove_function(fn.id))

    def move(self, delta):
        if self.model.fid:
            self.say(self.model.move_function(self.model.fid, delta))


class RangesPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_RANGES)
        self.fbar = FunctionBar(win, command=self.reload)
        self.root.addWidget(self.fbar)
        self.table = C.table([Column('text', 'Range (full scale)', 170), Column('resolution', 'Resolution', 130), Column('max_input', 'Max input', 110), Column('display_unit', 'Shown in', 90),
                              Column('points', 'Points', 70, align='right'), Column('spec', 'Spec lines', 80, align='right', stretch=True)])
        self.table.selectionChangedRows.connect(lambda _r: self.picked())
        self.root.addWidget(self.table, 1)
        box = self.box('Add or change a range')
        form = C.Form(columns=3)
        self.fs = C.Bind(form.entry('Full scale', 14, 'The top of the range with its unit, for example 10 V or 100 mV.'))
        self.res = C.Bind(form.entry('Resolution', 14, 'The smallest step the display shows in this range, for example 10 µV. A "count" in the specification means this.'))
        self.unit = C.Bind(form.combo('Show values in', [lab for _v, lab in M.PREFIX_CHOICES], 14, 'Display only: the datasheet stores SI values.'))
        self.label = C.Bind(form.entry('Label as printed (optional)', 14, 'For example 10.00000 V.'))
        self.maxin = C.Bind(form.entry('Max input (optional)', 14, 'The highest input the range accepts when that is above the full scale (over-range).'))
        self.unipolar_cb = form.check('Positive values only')
        self.unipolar = C.Bind(self.unipolar_cb)
        box.addWidget(form)
        helper = QWidget()
        hl = QHBoxLayout(helper)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QLabel('Resolution helper: the display shows'))
        self.decimals_e = QLineEdit()
        self.decimals_e.setMaximumWidth(60)
        self.decimals = C.Bind(self.decimals_e)
        hl.addWidget(self.decimals_e)
        hl.addWidget(QLabel('decimals when the range is shown in'))
        self.dec_prefix_box = QComboBox()
        self.dec_prefix_box.addItems(['', 'm', 'µ', 'k'])
        self.dec_prefix = C.Bind(self.dec_prefix_box)
        hl.addWidget(self.dec_prefix_box)
        hl.addWidget(C.button('Use as resolution', self.use_decimals))
        hl.addStretch(1)
        box.addWidget(helper)
        bar, _ = C.button_row(('Add range', self.add, 'primary'), ('Change selected', self.change), ('Remove selected', self.remove, 'danger'))
        box.addWidget(bar)
        bulk = QWidget()
        bl = QHBoxLayout(bulk)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel('Or add several full scales at once:'))
        be = QLineEdit()
        be.setMinimumWidth(300)
        self.bulk = C.Bind(be)
        bl.addWidget(be)
        bl.addWidget(C.button('Add them', self.add_many))
        bl.addStretch(1)
        box.addWidget(bulk)
        self.hint = C.small('')
        self.root.addWidget(self.hint)

    def reload(self):
        self.fbar.reload()
        rows = self.model.range_rows(self.fbar.fid)
        C.fill(self.table, rows)
        fn = self.model.fn(self.fbar.fid)
        self.hint.setText(f'Type values with their unit, for example {M.show(M.db.D(10), fn.unit)} or {M.show(M.db.D("0.1"), fn.unit)}.' if fn
                          else 'Add a section first (More > Sections and function settings).')

    def picked(self):
        s = C.selected_ids(self.table)
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
        self.unit.set(C.label_of(M.PREFIX_CHOICES, r.display_unit if r.display_unit else ''))
        self.unipolar.set(r.unipolar)

    def _prefix(self):
        return C.value_of(M.PREFIX_CHOICES, self.unit.get())

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
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a range in the table first.'))
        return self.say(self.model.edit_range(self.fbar.fid, s[0], self.fs.get(), self.res.get(), self.label.get(), self._prefix(), self.maxin.get(), self.unipolar.get()))

    def add_many(self):
        res = self.say(self.model.add_ranges(self.fbar.fid, self.bulk.get()))
        if res.ok:
            self.bulk.set('')
        return res

    def remove(self):
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a range in the table first.'))
        use = self.model.range_usage(self.fbar.fid, s[0])
        cascade = False
        if use['points'] or use['spec']:
            if not C.ask_yes_no(self.win, 'Remove range', f'This range has {use["points"]} point(s) and {use["spec"]} specification line(s). Remove it together with them? (Undo brings them back.)'):
                return None
            cascade = True
        return self.say(self.model.remove_range(self.fbar.fid, s[0], cascade))


class SpecPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_SPEC)
        self.fbar = FunctionBar(win, command=self.reload)
        self.root.addWidget(self.fbar)
        self.table = C.table([Column('scope', 'Applies to', 230), Column('text', 'Accuracy (default period)', 480, stretch=True), Column('mode_text', 'Sides', 150)])
        self.table.selectionChangedRows.connect(lambda _r: self.picked())
        self.root.addWidget(self.table, 1)
        self.warn = C.ToneLabel('', 'info')
        self.root.addWidget(self.warn)
        box = self.box('Specification line')
        self.form = C.Form(columns=3)
        self.range_box = self.form.combo('Range', ['All ranges'], 20, 'Which range this line is for. "All ranges" applies to every range that has no line of its own.')
        self.range_var = C.Bind(self.range_box)
        self.flo_e = self.form.entry('From frequency', 12, 'AC and frequency functions: where this band starts, for example 10 Hz. Leave empty for no band.')
        self.fhi_e = self.form.entry('To frequency', 12, 'Where the band ends, for example 1 kHz.')
        self.flo, self.fhi = C.Bind(self.flo_e), C.Bind(self.fhi_e)
        self.mode = C.Bind(self.form.combo('Sides', [MODE_LABELS[k] for k in db_modes()], 36, 'Use "low side only" for limits like a bandwidth that must not fall below -3 dB.'))
        self.bound = C.Bind(self.form.entry('Opposite bound (one-sided)', 12, 'The other limit a typed reading must stay within, in the function unit.'))
        self.basis = C.Bind(self.form.combo('A plain % means', [lab for _v, lab in BASIS_LABELS], 36))
        box.addWidget(self.form)
        self.period_holder = QWidget()
        self.period_lay = QVBoxLayout(self.period_holder)
        self.period_lay.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.period_holder)
        hb = QWidget()
        self.hb = QHBoxLayout(hb)
        self.hb.setContentsMargins(0, 0, 0, 0)
        self.hb.addWidget(QLabel('Insert:'))
        self.hb.addStretch(1)
        box.addWidget(hb)
        self.helper_buttons = {}
        self.focus_key = ''
        self.example_box = widgets.Banner('', 'info', title='Worked example')
        box.addWidget(self.example_box)
        self.parts_l = C.small('')
        box.addWidget(self.parts_l)
        bar, _ = C.button_row(('Add line', self.add, 'primary'), ('Change selected line', self.change), ('Remove selected line', self.remove, 'danger'), ('Copy to other ranges...', self.copy))
        box.addWidget(bar)
        self.period_vars = {}
        self.minus = None
        for e in (self.flo_e, self.fhi_e):
            e.textChanged.connect(lambda *_: self.update_example())
        self.bound.w.textChanged.connect(lambda *_: self.update_example())
        for b in (self.range_box, self.mode.w, self.basis.w):
            b.currentTextChanged.connect(lambda *_: self.update_example())
        self._ranges = []
        self._extra_bound = {}

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
        C.fill(self.table, [dict(r, id=r['index']) for r in rows])
        if fn is None:
            return
        self._ranges = [('', 'All ranges')] + [(r.id, m.range_text(fn, r)) for r in fn.ranges]
        cur = self.range_var.get()
        C.set_items(self.range_box, [lab for _v, lab in self._ranges])
        self.range_var.set(cur if cur in [lab for _v, lab in self._ranges] else 'All ranges')
        has_f = bool(fn.info.get('ac') or fn.info['family'] == 'generator' or fn.info.get('value'))
        for w in (self.flo_e, self.fhi_e):
            w.setEnabled(has_f)
        old = {k: v.get() for k, v in self.period_vars.items()}
        old_minus = self.minus.get() if self.minus is not None else ''
        while self.period_lay.count():
            it = self.period_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.period_vars = {}
        pf = C.Form(columns=1)
        for p in m.ds.periods:
            e = FocusEdit()
            pf.place(f'Accuracy for {p.label or p.id}', e, 'For example 0.05 % of reading + 0.01 % of range')
            e.setMinimumWidth(480)
            var = C.Bind(e)
            var.set(old.get(p.id, ''))
            self.period_vars[p.id] = var
            e.focused.connect(lambda k=p.id: setattr(self, 'focus_key', k))
            e.textChanged.connect(lambda *_: self.update_example())
        self.period_lay.addWidget(pf)
        mf = C.Form(columns=1)
        me = QLineEdit()
        mf.place('Different tolerance below the nominal (optional)', me, 'Only when the manual gives a different tolerance below the nominal than above it.')
        self.minus = C.Bind(me)
        self.minus.set(old_minus)
        me.textChanged.connect(lambda *_: self.update_example())
        self.period_lay.addWidget(mf)
        for b in tuple(self.helper_buttons.values()):
            b.deleteLater()
        self.helper_buttons = {}
        for h in m.helpers(fid):
            b = C.button(h['label'], (lambda k=h['key']: self.insert(k)), compact=True, tooltip=h['help'])
            self.hb.insertWidget(self.hb.count() - 1, b)
            self.helper_buttons[h['key']] = b
        self.update_example()
        warn = m.uncovered_ranges(fid)
        self.warn.setText(('No specification line applies yet to: ' + ', '.join(warn) + '. Add a line for these (or an "All ranges" line).') if warn else '')

    # ---- form <-> model
    def _range_id(self):
        return C.value_of(self._ranges, self.range_var.get()) if self._ranges else None

    def _mode(self):
        return next((k for k in db_modes() if MODE_LABELS[k] == self.mode.get()), 'both')

    def _texts(self):
        return {k: v.get() for k, v in self.period_vars.items()}

    def _basis(self):
        return C.value_of(BASIS_LABELS, self.basis.get()) or None

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
        if not k or not self.model.fn(self.fbar.fid) or self.minus is None:
            self.example_box.set_text('')
            self.parts_l.setText('')
            return
        r = self.model.example(self.fbar.fid, self.period_vars[k].get(), self._range_id(), f_lo=self.flo.get(), f_hi=self.fhi.get(), default_basis=self._basis(),
                               minus_text=self.minus.get())
        self.example_box.set_text(r['text'] or 'Type the accuracy statement above.')
        self.parts_l.setText(('; '.join(r['parts'])) if r['ok'] and r['parts'] else '')
        self.example_box.set_kind('info' if r['ok'] else 'warn')

    def picked(self):
        s = C.selected_ids(self.table)
        rows = self.model.spec_rows(self.fbar.fid)
        if not s or int(s[0]) >= len(rows):
            return
        r = rows[int(s[0])]
        self.range_var.set(C.label_of(self._ranges, r['range_id'] or ''))
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
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a line in the table first.'))
        return self.say(self.model.edit_spec_entry(self.fbar.fid, int(s[0]), self._texts(), self._range_id(), self.flo.get(), self.fhi.get(), self._mode(), self.bound.get(),
                                                   self._minus_texts(), self._basis()))

    def remove(self):
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a line in the table first.'))
        return self.say(self.model.remove_spec_entry(self.fbar.fid, int(s[0])))

    def copy(self):
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select the line to copy first.'))
        fn = self.model.fn(self.fbar.fid)
        text = C.ask_string(self.win, 'Copy to other ranges', 'Copy to which ranges? Type the full scales, separated by commas (for example 1 V, 10 V), or "all".')
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


class AutomationPage(Page):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.intro(M.S_AUTOMATION)
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(C.button('Check which standards can do this', self.run, 'primary'))
        tl.addWidget(C.button('What can the suite drive today?', self.drivers))
        self.fbar = FunctionBar(win, with_all=True, command=self.reload)
        tl.addWidget(self.fbar)
        self.filter_box = QComboBox()
        self.filter_box.addItems([lab for _k, lab in FILTER_LABELS])
        self.filter_box.activated.connect(lambda _i: self.reload())
        self.filter = C.Bind(self.filter_box)
        tl.addWidget(self.filter_box)
        tl.addStretch(1)
        self.root.addWidget(top)
        self.summary_box = widgets.Banner('Press the button to look through the standards you imported.', 'info', title='Result')
        self.root.addWidget(self.summary_box)
        self.table = C.table([Column('function', 'Function', 120), Column('point', 'Point', 150), Column('standard', 'Standard', 80), Column('mode', 'Chosen', 80),
                              Column('tar', 'TAR', 70, align='right'), Column('tur', 'TUR', 70, align='right'), Column('automation', 'Can the suite run it?', 250),
                              Column('message', 'Why / note', 340, stretch=True)], row_tone=lambda r: {'bad': 'fail', 'warn': 'warn'}.get(r['level']), key='point_id')
        self.table.selectionChangedRows.connect(lambda _r: self.picked())
        self.root.addWidget(self.table, 1)
        pick, pl = C.group('Standard for the selected point')
        self.cands = C.table([Column('standard', 'Standard', 80), Column('covered_text', 'Covers it', 80), Column('tur', 'TUR', 70, align='right'), Column('tar', 'TAR', 70, align='right'),
                              Column('automation', 'Automation', 250), Column('why', 'Why not', 380, stretch=True)])
        self.cands.setMaximumHeight(150)
        pl.addWidget(self.cands)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.choice_box = QComboBox()
        self.choice_box.setMinimumWidth(360)
        self.choice = C.Bind(self.choice_box)
        rl.addWidget(self.choice_box)
        rl.addWidget(C.button('Use this standard for the point', self.apply_choice))
        rl.addWidget(C.button('Clear all my choices', self.clear))
        rl.addStretch(1)
        pl.addWidget(row)
        self.root.addWidget(pick)
        self._choices = []
        self._rows = {}

    @property
    def summary(self):
        return self.summary_box

    def _filter(self):
        return C.value_of(FILTER_LABELS, self.filter.get())

    def reload(self):
        self.fbar.reload()
        m = self.model
        if m.match_result is None:
            C.fill(self.table, [])
            return
        stale = not m.match_fresh()
        rows = m.match_rows(self.fbar.fid or None, self._filter())
        self._rows = {r['point_id']: r for r in rows}
        C.fill(self.table, [dict(r, id=r['point_id']) for r in rows])
        self.summary_box.set_text(m.match_summary_text() + (' (the datasheet changed since: check again)' if stale else ''))

    def run(self):
        res = self.model.run_match()
        self.say(res)
        if not res.ok:
            self.summary_box.set_text(res.message)
        self.reload()
        return res

    def picked(self):
        s = C.selected_ids(self.table)
        if not s:
            return
        rows = self.model.candidate_rows(s[0])
        C.fill(self.cands, [dict(r, id=r['standard'], covered_text='yes' if r['covered'] else 'no', why=r['message']) for r in rows])
        self._choices = self.model.override_choices(s[0])
        C.set_items(self.choice_box, [lab for _v, lab in self._choices])
        cur = self.model.ds.assignments.get(s[0], '')
        self.choice.set(C.label_of(self._choices, cur))

    def apply_choice(self):
        s = C.selected_ids(self.table)
        if not s:
            return self.say(M.Outcome(False, 'Select a point in the table first.'))
        res = self.say(self.model.set_assignment(s[0], C.value_of(self._choices, self.choice.get())))
        self.reload()
        return res

    def clear(self):
        if not self.model.ds.assignments:
            return self.say(M.Outcome(False, 'You have not chosen any standard by hand.'))
        res = self.say(self.model.clear_assignments())
        self.reload()
        return res

    def drivers(self):
        w = DriversWindow(self.win, self.model)
        w.show()
        return w
