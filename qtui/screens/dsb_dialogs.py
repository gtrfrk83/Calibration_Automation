"""Datasheet Builder (Qt): the small windows and dialogs of the editor: Problems, Print preview, What the suite can drive, Version history, the rule
(test point calculator) dialog, the New datasheet question and the one-function chooser, and PageDialog (an older detail page in its own window).
Ports of the datasheet_builder_ui classes of the same names; all decisions are in datasheet_builder_ui_model.  No Tk import."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QWidget

import datasheet_builder_ui_model as M
from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.table import Column
from qtui.theme import M as SZ


def present(dlg: widgets.ModalDialog) -> widgets.ModalDialog:
    """Show a non-modal tool window at its intended size."""
    dlg.show()
    w, h = getattr(dlg, '_size_hint', (0, 0))
    if w:
        dlg.resize(w, h)
        dlg._center()
    return dlg


# ------------------------------------------------------------------------------------------------------------------------------ choice / new sheet
class ChoiceDialog(widgets.ModalDialog):
    """Pick one thing from a list.  `value` is the chosen label, None when cancelled."""

    def __init__(self, parent, title, prompt, labels, initial=''):
        super().__init__(parent, title)
        self.title_label.hide()
        self.value = None
        self.add_text(prompt)
        self.box = QComboBox()
        self.box.addItems(list(labels))
        i = self.box.findText(initial or (labels[0] if labels else ''))
        self.box.setCurrentIndex(max(0, i))
        self.body.addWidget(self.box)
        self.initial_focus = self.box
        self.add_button('Cancel', cancel=True)
        self.add_button('OK', role='primary', result='ok', default=True, callback=self.ok)

    def ok(self):
        self.value = self.box.currentText()


def ask_choice(parent, title, prompt, labels, initial=''):
    dlg = ChoiceDialog(parent, title, prompt, labels, initial)
    dlg.run()
    return dlg.value


class NewSheetDialog(widgets.ModalDialog):
    """The New datasheet question: start blank (the default) or with the handheld multimeter sections.  `cancelled` is True after Cancel / Esc / closing."""

    def __init__(self, parent):
        super().__init__(parent, 'New datasheet', width=480)
        self.title_label.hide()
        self.cancelled = True
        self.add_text('A new datasheet starts blank: you add the sections and rows you need.')
        self.check = QCheckBox('Start from a handheld template')
        C.tip(self.check, 'Adds an empty section for each handheld multimeter function: DC volts, AC volts, DC current, AC current, 2-wire ohms, continuity, capacitance, '
                          'frequency, temperature (simulated) and diode test. You still type the rows. Nothing is copied from a manufacturer procedure.')
        self.body.addWidget(self.check)
        self.add_text('DC / AC volts and current, ohms, continuity, capacitance, frequency, temperature and diode sections, empty.', 'hint')
        self.initial_focus = self.check
        self.add_button('Cancel', cancel=True)
        self.add_button('Create', role='primary', result='create', default=True, callback=lambda: setattr(self, 'cancelled', False))

    @property
    def handheld(self):
        return self.check


def ask_new_sheet(parent):
    """None when cancelled, else True (start from the handheld template) or False (blank)."""
    dlg = NewSheetDialog(parent)
    dlg.run()
    return None if dlg.cancelled else bool(dlg.check.isChecked())


# ------------------------------------------------------------------------------------------------------------------------------ problems / preview / drivers
class ProblemsWindow(widgets.ModalDialog):
    """Everything that needs attention, in plain words.  Double-click one to go to its row."""

    def __init__(self, owner):
        super().__init__(owner, 'Problems on this datasheet', width=640, modal=False)
        self.title_label.hide()
        self._size_hint = (980, 440)
        self.owner = owner
        self.summary = widgets.label('', 'section')
        self.body.addWidget(self.summary)
        self.table = C.table([Column('level_text', '', 90), Column('row_text', 'Row', 60), Column('text', 'What to do', 760, stretch=True)],
                             row_tone=lambda r: {'error': 'fail', 'warn': 'warn'}.get(r['level']))
        self.table.rowActivated.connect(lambda _r: self.go())
        self.body.addWidget(self.table, 1)
        self.add_button('Go to the row', role='primary', close=False, callback=self.go)
        self.add_button('Close', cancel=True)
        self._rows = []
        self.reload()

    def reload(self):
        m = self.owner.model
        self._rows = m.problem_rows()
        self.summary.setText(m.problem_summary())
        rows = [dict(r, id=i, level_text='FIX' if r['level'] == 'error' else 'warning', row_text=r['row'] or '') for i, r in enumerate(self._rows)]
        C.fill(self.table, rows)

    def go(self):
        s = C.selected_ids(self.table)
        if not s or int(s[0]) >= len(self._rows):
            return None
        row = self._rows[int(s[0])]
        if row['key']:
            self.owner.goto_row(row['key'])
        return row


class PreviewWindow(widgets.ModalDialog):
    """The blank datasheet as it would print, with Save as PDF.  As Found and As Left are empty: it is a template, not a record."""

    def __init__(self, owner):
        view = owner.model.print_view()
        super().__init__(owner, 'Print preview: ' + view['title'], width=700, modal=False)
        self.title_label.hide()
        self._size_hint = (1000, 560)
        self.owner, self.view = owner, view
        self.body.addWidget(widgets.label(view['title'], 'h2'))
        self.body.addWidget(widgets.label(view['subtitle'], 'sub'))
        self.body.addWidget(widgets.Banner(view['notice'], 'warn'))
        widths = (80, 230, 120, 90, 90, 100, 110, 110)
        cols = [Column(i, name, widths[i] if i < len(widths) else 100, stretch=(i == 1)) for i, name in enumerate(view['columns'])]
        rows = [tuple(r['cells']) for r in view['rows']]
        headers = {id(rw) for rw, r in zip(rows, view['rows']) if r['kind'] == 'header'}
        self.table = C.table(cols, row_tone=lambda r: 'info' if id(r) in headers else None)
        self.table.set_rows(rows, keep_selection=False)
        self.body.addWidget(self.table, 1)
        self.msg = widgets.label('', 'sub', wrap=True)
        self.body.addWidget(self.msg)
        self.add_button('Save as PDF to print...', role='primary', close=False, callback=self.save_pdf)
        self.add_button('Close', cancel=True)

    def save_pdf(self):
        m = self.owner.model
        name = ('-'.join(x for x in (m.ds.make, m.ds.model, 'blank datasheet') if x) or 'blank datasheet').replace(' ', '_') + '.pdf'
        path = C.ask_save_path(self, 'Save the blank datasheet as PDF', name, 'PDF (*.pdf)')
        if not path:
            return None
        res = m.write_sheet_pdf(path)
        self.msg.setText(res.message)
        return res


class DriversWindow(widgets.ModalDialog):
    """Read-only: each standard, its driver, and what the driver can do for the functions of this datasheet."""

    def __init__(self, parent, model):
        super().__init__(parent, 'What the suite can drive today', width=700, modal=False)
        self.title_label.hide()
        self._size_hint = (1000, 440)
        self.body.addWidget(widgets.label('A standard can be able to produce a point (it covers it) without the suite having a driver to run it by itself. '
                                          '"Commands not yet verified" means the driver exists but has not been confirmed on hardware.', 'sub', wrap=True))
        t = C.table([Column('model', 'Standard', 90), Column('role', 'Role', 80), Column('driver', 'Driver', 150), Column('imported_text', 'Spec imported', 100),
                     Column('functions_text', "This datasheet's functions", 520, stretch=True)], sortable=True)
        rows = []
        for r in model.driver_rows():
            rows.append(dict(r, id=r['model'], imported_text='yes' if r['imported'] else 'no',
                             functions_text='; '.join(f'{k}: {v["text"]}' for k, v in r['functions'].items()) or '(nothing for these functions)'))
        C.fill(t, rows)
        self.table = t
        self.body.addWidget(t, 1)
        self.add_button('Close', cancel=True)


# ------------------------------------------------------------------------------------------------------------------------------ the rule dialog
class RuleDialog(widgets.ModalDialog):
    """Rule picker: choose how the points are worked out.  `outcome` holds the result (None = cancelled)."""

    def __init__(self, parent, model, fid, rule_id=None):
        super().__init__(parent, 'Change rule' if rule_id else 'Add a rule for the test points', width=600)
        self.title_label.hide()
        self.model, self.fid, self.rule_id, self.outcome = model, fid, rule_id, None
        cat = model.rule_catalog(fid)
        self.cat = cat
        self.type_pairs = [(r['key'], r['label']) for r in cat['rules']]
        self.freq_pairs = [(k, lab) for k, lab in cat['freq']]
        self.body.addWidget(widgets.label('Kind of rule', 'section'))
        self.type_box = QComboBox()
        self.type_box.addItems([lab for _k, lab in self.type_pairs])
        self.type_box.activated.connect(lambda _i: self.layout())
        self.body.addWidget(self.type_box)
        self.help = widgets.label('', 'sub', wrap=True)
        self.body.addWidget(self.help)
        f = C.Form(columns=2)
        self.v = {}
        self.v['type'] = C.Bind(self.type_box)

        def entry(key, label, w, hint=''):
            self.v[key] = C.Bind(f.entry(label, w, hint))
        entry('percents', 'Percentages of full scale', 24, 'For example 10, 50, 100')
        self.bipolar = f.check('Also the negative side')
        self.zero = f.check('Also zero')
        entry('values', 'Points', 40, 'For example 1 mV, 5 V, 100 mV. Each goes on the smallest range that holds it.')
        entry('start', 'Start', 14, 'With its unit, for example 1 V')
        entry('stop', 'Stop', 14)
        entry('count', 'Number of points', 8)
        entry('step', 'or step', 12, 'For example 0.5 V')
        entry('per_decade', 'or points per decade', 8)
        entry('nominal', 'Level', 12, 'The one level the frequencies are applied at (0 for dB tests).')
        self.body.addWidget(f)
        fr, frl = C.group('Frequencies')
        ff = C.Form(columns=2)
        self.freq_box = ff.combo('Frequencies', [lab for _k, lab in self.freq_pairs], 40)
        self.v['freq_mode'] = C.Bind(self.freq_box)
        for key, label, w, hint in (('freq_values', 'List', 30, 'For example 100 Hz, 1 kHz, 20 kHz'), ('freq_start', 'Start', 12, ''), ('freq_stop', 'Stop', 12, ''),
                                    ('freq_count', 'Number of frequencies', 8, ''), ('freq_per_decade', 'or per decade (log)', 8, '')):
            self.v[key] = C.Bind(ff.entry(label, w, hint))
        at = ff.combo('Band points', ['edges', 'mid', 'both'], 10, 'edges = the band limits; mid = the middle of each band.')
        self.v['freq_at'] = C.Bind(at)
        frl.addWidget(ff)
        self.body.addWidget(fr)
        if cat['uses_amplitude']:
            af = C.Form(columns=1)
            self.v['amplitude'] = C.Bind(af.entry('Stimulus level (e.g. 1 V)', 12, 'The level of the signal applied while a frequency / period / bandwidth is tested.'))
            self.body.addWidget(af)
        else:
            self.v['amplitude'] = C.Bind(QLineEdit())
        rf, rfl = C.group('Only on these ranges (none ticked = all)')
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.range_vars = {}
        for rid, text in cat['ranges']:
            cb = QCheckBox(text)
            self.range_vars[rid] = C.Bind(cb)
            rl.addWidget(cb)
        rl.addStretch(1)
        rfl.addWidget(row)
        self.body.addWidget(rf)
        self.msg = widgets.label('', 'sub', wrap=True)
        self.msg.setProperty('role', 'hint')
        self.msg_tone = C.ToneLabel('', 'bad')
        self.body.addWidget(self.msg_tone)
        self.initial_focus = self.type_box
        self.add_button('Cancel', cancel=True)
        self.add_button('OK', role='primary', result='ok', default=True, callback=self.ok)
        self.load()
        self.layout()

    def load(self):
        form = self.model.rule_form(self.fid, self.rule_id) if self.rule_id else {}
        self.v['type'].set(C.label_of(self.type_pairs, form.get('type', 'percent_of_range')))
        for k in self.v:
            if k in form and k != 'type':
                self.v[k].set(form[k] if k not in ('freq_mode',) else C.label_of(self.freq_pairs, form[k]))
        if not form:
            self.v['freq_mode'].set(C.label_of(self.freq_pairs, 'list' if self.cat['needs_frequency'] else 'none'))
            self.v['percents'].set('10, 50, 100')
            self.v['nominal'].set('0')
        else:
            self.v['freq_mode'].set(C.label_of(self.freq_pairs, form.get('freq_mode', 'none')))
        self.bipolar.setChecked(bool(form.get('bipolar'))), self.zero.setChecked(bool(form.get('zero')))
        for rid in form.get('range_ids', []):
            if rid in self.range_vars:
                self.range_vars[rid].set(True)

    def layout(self):
        key = C.value_of(self.type_pairs, self.v['type'].get())
        self.help.setText(next((r['help'] for r in self.cat['rules'] if r['key'] == key), ''))

    def form(self):
        d = {k: v.get() for k, v in self.v.items()}
        d['type'] = C.value_of(self.type_pairs, d['type'])
        d['freq_mode'] = C.value_of(self.freq_pairs, d['freq_mode'])
        d['bipolar'], d['zero'] = self.bipolar.isChecked(), self.zero.isChecked()
        d['range_ids'] = [rid for rid, var in self.range_vars.items() if var.get()]
        return d

    def ok(self):
        form = self.form()
        res = self.model.update_rule(self.fid, self.rule_id, form) if self.rule_id else self.model.add_rule(self.fid, form)
        if not res.ok:
            self.msg_tone.setText(res.message)
            return False
        self.outcome = res
        return True


# ------------------------------------------------------------------------------------------------------------------------------ pages in a window
class PageDialog(widgets.ModalDialog):
    """One of the older detail pages (Ranges, Specification table, Sections, Details, Standards) in its own window over the sheet."""

    def __init__(self, owner, title, page_cls, width=1000, height=640):
        super().__init__(owner, title, width=720, modal=False)
        self.title_label.hide()
        self._size_hint = (width, height)
        self.owner = owner
        self.page = page_cls(self, owner)
        self.body.addWidget(self.page, 1)
        self.add_button('Close', cancel=True, callback=self.page.commit)
        self.page.reload()

    def reload(self):
        self.page.reload()

    def reject(self):
        self.page.commit()
        super().reject()


# ------------------------------------------------------------------------------------------------------------------------------ version history
class VersionsWindow(widgets.ModalDialog):
    """Version history of one datasheet: open an old version in an editor, load it into the open editor, or export it."""

    def __init__(self, parent, storage, uid, editor=None, panel=None):
        super().__init__(parent, f'Version history: {uid}', width=640, modal=False)
        self.title_label.hide()
        self._size_hint = (900, 440)
        self.lst = M.DatasheetList(storage)
        self.uid, self.editor, self.panel = uid, editor, panel
        self.body.addWidget(widgets.label('Every save is a new version and old versions are never changed. Opening an old version and saving it creates a newer version.', 'sub', wrap=True))
        self.table = C.table([Column('version', 'Version', 70, align='right'), Column('saved', 'Saved', 170), Column('who', 'By', 110), Column('status', 'Status', 150),
                              Column('points', 'Points', 70, align='right'), Column('note', 'Note', 300, stretch=True)], sortable=True, multi=True)
        self.body.addWidget(self.table, 1)
        self.msg = widgets.label('', 'sub', wrap=True)
        self.body.addWidget(self.msg)
        self.add_button('Open in a new window', role='primary', close=False, callback=self.open_new)
        if editor is not None:
            self.add_button('Load into the open editor', close=False, callback=self.load_here)
        cb = self.add_button('Compare', close=False, callback=self.compare)
        cb.setToolTip('Select two versions to see what changed between them, or one version to compare it with the one before it.')
        self.add_button('Export JSON...', close=False, callback=self.export)
        self.add_button('Close', cancel=True)
        self.reload()

    def reload(self):
        rows = self.lst.version_rows(self.uid)
        C.fill(self.table, [dict(r, id=r['version'], saved=r['saved_at'], status=r['status_text']) for r in rows])

    def _version(self):
        s = C.selected_ids(self.table)
        return int(s[0]) if s else None

    def compare(self):
        sel = sorted(int(v) for v in C.selected_ids(self.table))
        if not sel:
            self.msg.setText('Select a version first (two to compare them, or one to compare it with the version before).')
            return None
        if len(sel) == 1:
            older = [r['version'] for r in self.lst.version_rows(self.uid) if r['version'] < sel[0]]
            if not older:
                self.msg.setText('That is the first version: there is nothing before it to compare with.')
                return None
            sel = [max(older), sel[0]]
        res = self.lst.compare_versions(self.uid, sel[0], sel[-1])
        self.msg.setText(res.message)
        if res.ok:
            CompareWindow(self, self.uid, sel[0], sel[-1], res.detail).show()
        return res

    def open_new(self):
        v = self._version()
        if v is None:
            self.msg.setText('Select a version first.')
            return None
        ed = self.lst.open(self.uid, v)
        if ed is None:
            self.msg.setText(self.lst.last_error)
            return None
        if self.panel is not None:
            return self.panel.open_editor(ed)
        from qtui.screens.dsb_editor import GridEditorWindow
        win = GridEditorWindow(self, ed)
        win.show()
        return win

    def load_here(self):
        v = self._version()
        if v is None:
            self.msg.setText('Select a version first.')
            return None
        res = self.editor.model.load_version(v)
        self.editor.changed(res)
        self.msg.setText(res.message)
        return res

    def export(self):
        v = self._version()
        if v is None:
            self.msg.setText('Select a version first.')
            return None
        path = C.ask_save_path(self, 'Export version as JSON', f'{self.uid}-v{v}.json', 'JSON (*.json)')
        res = self.lst.export_json(self.uid, path, v)
        self.msg.setText(res.message)
        return res


class CompareWindow(widgets.ModalDialog):
    """What changed from one saved version to a newer one: header lines, then a row per added / removed / changed point."""

    def __init__(self, parent, uid, old, new, diff):
        super().__init__(parent, f'Compare versions {old} and {new}: {uid}', width=760, modal=False)
        self.title_label.hide()
        self._size_hint = (980, 520)
        self.diff = diff
        self.body.addWidget(widgets.label(f'Version {old} -> version {new}. ' + diff.summary(), 'sub', wrap=True))
        tone = {'added': 'good', 'removed': 'bad', 'changed': 'warn'}
        self.table = C.table([Column('kind', 'Change', 80), Column('section', 'Section', 150), Column('point', 'Test point', 190), Column('what', 'What', 110),
                              Column('before', 'Version %d' % old, 220, stretch=True), Column('after', 'Version %d' % new, 220, stretch=True)],
                             row_tone=lambda r: tone.get(r.get('kind')), empty='No differences.')
        C.fill(self.table, [dict(id=i, kind=c.kind, section=c.section, point=c.point, what=c.what or ('whole point' if c.point else 'whole section'),
                                 before=c.before, after=c.after) for i, c in enumerate(diff.rows)])
        self.body.addWidget(self.table, 1)
        self.add_button('Close', cancel=True, default=True)


class SaveBlockedDialog(widgets.ModalDialog):
    """Shown when Save finds problems: every error in one list (the sheet's own and the Sheet check's), a click on a line shows the row, and the three ways on:
    go to the selected row, save the sheet as a draft anyway, or keep editing.  run() returns 'go', 'draft' or 'edit'; `chosen_key` is the row to go to."""

    def __init__(self, parent, items):
        super().__init__(parent, 'Before this can be saved as a procedure', width=760)
        self.title_label.hide()
        self._size_hint = (900, 460)
        self.items = items
        self.chosen_key = ''
        self.body.addWidget(widgets.label(f'{len(items)} thing{"s" * (len(items) != 1)} to fix before this sheet can run as a procedure. Double-click a line to go to its row. '
                                          'A draft is kept as a version but is not a runnable procedure yet.', 'sub', wrap=True))
        self.table = C.table([Column('row', 'Row', 54, align='right'), Column('where', 'Section', 170), Column('text', 'What to fix', 560, stretch=True)], row_tone=lambda r: 'fail')
        C.fill(self.table, [dict(id=i, row=it.get('row') or '', where=it.get('where', ''), text=it['text']) for i, it in enumerate(items)])
        self.table.rowActivated.connect(lambda _r: self._go())
        self.body.addWidget(self.table, 1)
        self.add_button('Keep editing', cancel=True, result='edit')
        self.add_button('Save as a draft', result='draft')
        self.go_b = self.add_button('Go to the row', role='primary', result='go', default=True, callback=self._go_cb)

    def _selected(self):
        sel = C.selected_ids(self.table)
        return self.items[int(sel[0])] if sel else (self.items[0] if self.items else None)

    def _go_cb(self):
        it = self._selected()
        self.chosen_key = (it or {}).get('key', '')
        return None

    def _go(self):
        self._go_cb()
        self.result_key = 'go'
        self.accept()
