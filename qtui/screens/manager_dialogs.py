"""The small windows of the Qt Manager: message / question / text boxes, 'Mark verified' and 'Unlock' (verified_ui.py twin), the procedure package windows
(packages_ui.py twin), the Register procedure form, 'Restore previous version', the Mudcats .MDD import preview (mdd_import_ui.py twin) and the readiness-check
output window.  Rules and wording are the Tk ones; every function keeps the Tk signature (`ask_mark(parent, entry, status)` ...) so a test can drive it.

File pickers go through the three `pick_*` functions so a test replaces them instead of opening a native dialog.  No Tk import."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QRadioButton, QScrollArea,
                               QVBoxLayout, QWidget)

import ui_theme_core as core
import verified
from qtui import theme
from qtui.table import Column, DataTable
from qtui.theme import M
from qtui.widgets import Badge, Banner, MessageDialog, ModalDialog, label


# ---------------------------------------------------------------------------------------------------------------------------------------------
# message boxes (the tkinter messagebox / simpledialog replacements of the Manager)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def message(parent, kind, title, text, detail=''):
    """One OK button.  kind 'info' | 'warning' | 'error'."""
    MessageDialog(parent, kind, title, text, detail=detail).run()


def ask_yes_no(parent, title, text):
    return MessageDialog(parent, 'question', title, text, buttons=(('Yes', 'yes', 'primary'), ('No', 'no', None)), cancel_key='no').run() == 'yes'


def ask_text(parent, title, prompt, initial=''):
    """simpledialog.askstring: the text typed, or None when cancelled."""
    dlg = ModalDialog(parent, title)
    dlg.title_label.hide()
    dlg.add_text(prompt)
    edit = QLineEdit(initial or '')
    dlg.body.addWidget(edit)
    dlg.initial_focus = edit
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('OK', role='primary', result='ok', default=True)
    dlg.edit = edit
    return edit.text() if dlg.run() == 'ok' else None


def pick_open_file(parent, title, filters, directory=''):
    """filters = 'Python scripts (*.py)' style (Qt syntax).  '' = cancelled."""
    return QFileDialog.getOpenFileName(parent, title, directory, filters)[0] or ''


def pick_folder(parent, title, directory=''):
    return QFileDialog.getExistingDirectory(parent, title, directory) or ''


def _field_row(grid: QFormLayout, text, edit, hint=''):
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(M.md)
    row.addWidget(edit, 1)
    if hint:
        row.addWidget(label(hint, 'hint'))
    grid.addRow(label(text), box)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# verified_ui.py
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _remembered():
    return core.Settings('verified')


def _verified_dialog(parent, title, heading, lead, ok_text):
    dlg = ModalDialog(parent, title, width=620)
    dlg.title_label.setText(heading)
    dlg.sub_label.setText(lead)
    dlg.sub_label.setVisible(True)
    return dlg


def _finish(dlg, grid, ok_text, error, submit):
    dlg.body.addLayout(grid)
    error.setProperty('role', 'hint')
    error.setStyleSheet(f"color: {theme.tokens()['bad']};")          # one dynamic colour, taken from the token
    error.setWordWrap(True)
    dlg.body.addWidget(error)
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button(ok_text, role='primary', result='ok', default=True, callback=submit)


def ask_mark(parent, entry, status, today=None):
    """'Mark verified on hardware' form -> {'who', 'on_date', 'note', 'hardware'} or None."""
    store = _remembered()
    again = status.kind != 'none'
    dlg = _verified_dialog(parent, 'Mark verified on hardware', f'{"Verify again" if again else "Mark verified on hardware"}: {entry.name or entry.proc_key}',
                           'Only after this procedure has run correctly on the actual instruments. It is then LOCKED: it cannot be edited '
                           '(procedure changes, the in-run editor, developer-mode edits, the Datasheet Builder) until someone unlocks it with a '
                           'reason. Running it is not affected. A fingerprint of its files and settings is saved so a later change shows up here.', 'Mark verified and lock')
    edits = {'who': QLineEdit(store.get('who', '') or verified.default_who()), 'on_date': QLineEdit((today or verified.date.today()).isoformat()),
             'instrument': QLineEdit(), 'calibrator': QLineEdit(), 'note': QLineEdit()}
    grid = QFormLayout()
    grid.setHorizontalSpacing(M.md)
    for key, text, hint in (('who', 'Verified by *', ''), ('on_date', 'Date', 'year-month-day (today if left as is)'),
                            ('instrument', 'Instrument / serial', 'optional, the unit it was run on'), ('calibrator', 'Calibrator / standard', 'optional'),
                            ('note', 'Note', 'optional')):
        _field_row(grid, text, edits[key], hint)
    error, result = QLabel(''), {'v': None}

    def submit():
        clean, problems = verified.check_verify_form(edits['who'].text(), edits['on_date'].text(), edits['note'].text(),
                                                     verified.compose_hardware(edits['instrument'].text(), edits['calibrator'].text()), today)
        if problems:
            error.setText(' '.join(problems))          # a wrong entry is explained inside the dialog; it stays open
            return False
        store.set('who', clean['who'])
        store.save()
        result['v'] = clean
        return True
    _finish(dlg, grid, 'Mark verified and lock', error, submit)
    dlg.edits, dlg.error = edits, error
    _last['dialog'] = dlg
    dlg.run()
    return result['v']


def ask_unlock(parent, entry, status):
    """'Unlock for editing' form -> {'who', 'reason'} or None."""
    store = _remembered()
    dlg = _verified_dialog(parent, 'Unlock for editing', f'Unlock for editing: {entry.name or entry.proc_key}',
                           'Anyone can unlock, but it is recorded: who, when and why. While it is unlocked it can be edited and its '
                           'verification no longer protects it. Afterwards, press "Lock again" if nothing changed, or verify it on the hardware '
                           'again. Changes saved before it was locked stay as they are.', 'Unlock')
    edits = {'who': QLineEdit(store.get('who', '') or verified.default_who()), 'reason': QLineEdit()}
    grid = QFormLayout()
    grid.setHorizontalSpacing(M.md)
    _field_row(grid, 'Your name *', edits['who'])
    _field_row(grid, 'Reason *', edits['reason'])
    error, result = QLabel(''), {'v': None}

    def submit():
        clean, problems = verified.check_unlock_form(edits['who'].text(), edits['reason'].text())
        if problems:
            error.setText(' '.join(problems))
            return False
        store.set('who', clean['who'])
        store.save()
        result['v'] = clean
        return True
    _finish(dlg, grid, 'Unlock', error, submit)
    dlg.edits, dlg.error = edits, error
    _last['dialog'] = dlg
    dlg.run()
    return result['v']


_last: dict = {}            # the most recent form dialog (tests reach its fields from a timer while it is open)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# packages_ui.py
# ---------------------------------------------------------------------------------------------------------------------------------------------
STATE_TEXT = {'new': 'New', 'replace': 'REPLACES installed file', 'same': 'Identical'}


def choose_package(parent):
    import packages
    folder = packages.get_library_dir()
    directory = folder if folder and Path(folder).is_dir() else ''
    return pick_open_file(parent, 'Choose a procedure package', 'Procedure packages (zip) (*.zip);;All files (*)', directory)


def choose_library_folder(parent):
    """The folder that was set, or None (cancelled)."""
    import packages
    current = packages.get_library_dir()
    chosen = pick_folder(parent, "Choose the lab's procedure library folder (a shared drive, for example)", current if current and Path(current).is_dir() else '')
    if not chosen:
        return None
    packages.set_library_dir(chosen)
    return chosen


def _origin_text(pv):
    where = {True: "inside the lab's library folder", False: "NOT inside the lab's library folder", None: 'no library folder is set'}[pv.in_library]
    return f'{pv.origin}\n({where})\nsha256 {pv.zip_sha256}'


def _verified_text(pv):
    parts = []
    if pv.installed_version:
        parts.append(f'Installed now: version {pv.installed_version}. Verified on hardware: {pv.status_text}.')
    else:
        parts.append('Not installed yet.')
    if pv.will_unlock:
        parts.append('INSTALLING WILL UNLOCK IT: it is verified and locked now, and this package replaces its files.')
    if pv.mark is not None:
        parts.append('The package carries a verified mark: ' + pv.mark_detail)
    return '\n'.join(parts)


def ask_install(parent, pv):
    """The package preview; True = the person confirmed the install."""
    import packages
    dlg = ModalDialog(parent, 'Import procedure package', width=820)
    dlg.set_title('Import procedure package' if pv.ok else 'This package cannot be imported')
    dlg.sub_label.setText(pv.zip_name)
    dlg.sub_label.setVisible(True)
    dlg.setMinimumHeight(760)
    dlg.resize(860, 780)
    info = QWidget()
    iv = QVBoxLayout(info)
    iv.setContentsMargins(0, 0, 0, 0)
    iv.setSpacing(M.sm)
    iv.addWidget(Banner(packages.CODE_WARNING, 'warn', title='Packages contain program code'))
    if pv.in_library is not True:
        iv.addWidget(Banner("This file is not inside the lab's library folder." if pv.in_library is False else
                                  'No library folder is set (Library menu > "Library folder..."), so nothing shows that this file comes from the lab\'s own library.',
                                  'error' if pv.in_library is False else 'info'))
    if pv.errors:
        iv.addWidget(Banner('\n'.join('- ' + e for e in pv.errors[:12]) + ('\n- ... and more' if len(pv.errors) > 12 else ''), 'error',
                                  title='Refused: nothing will be installed'))
    for w in pv.warnings:
        if w.startswith('This file is NOT') or w.startswith('No library folder'):
            continue
        iv.addWidget(Banner(w, 'warn', title='Verified on hardware' if 'VERIFIED ON HARDWARE' in w else ''))
    dlg.rows = []
    if pv.proc_id:
        grid = QFormLayout()
        grid.setHorizontalSpacing(M.lg)
        grid.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        def row(name, value, bold=False):
            lab = label(value, 'kvvalue' if bold else None, wrap=True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addRow(label(name, 'kvkey'), lab)
            dlg.rows.append((name, value))
        row('Procedure', pv.name, True)
        row('Version', pv.version + (f'   (installed: {pv.installed_version})' if pv.installed_version else '   (new procedure)'))
        row('Made by (claimed)', pv.author or 'not stated')
        row('Origin', _origin_text(pv))
        if pv.ok:
            row('Verified status', _verified_text(pv))
            if pv.affected:
                row('Also affected', '; '.join(f'{n}: will show "Changed since verification"' for n, _c in pv.affected))
            if pv.requires:
                row('Needs (already installed)', ', '.join(pv.requires))
        iv.addLayout(grid)
    iv.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet('QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }')
    scroll.setWidget(info)
    scroll.setMinimumHeight(340)
    dlg.body.addWidget(scroll, 1)
    dlg.info_scroll = scroll
    dlg.table = None
    if pv.files:
        dlg.body.addWidget(label(f'Files ({len(pv.files)}): replaced files are copied to Backups/packages first', 'section'))
        table = DataTable([Column('path', 'File', 430, stretch=True), Column('size', 'Size', 80, align='right', fmt=lambda v: f'{v:,}'),
                           Column('what', 'What happens', 220, getter=lambda f: STATE_TEXT[f.state], tone=lambda f: 'warn' if f.state == 'replace' else None)],
                          list(pv.files), multi=False)
        table.setMinimumHeight(4 * M.row_h + M.header_h)
        dlg.body.addWidget(table, 1)
        dlg.table = table
    confirm = QCheckBox('I know where this package came from and I want to install it.')
    if pv.ok:
        dlg.body.addWidget(confirm)
    dlg.confirm = confirm
    dlg.add_button('Cancel' if pv.ok else 'Close', cancel=True)
    dlg.install = None
    if pv.ok:
        dlg.install = dlg.add_button('Install package', role='primary', result='install', default=True)
        dlg.install.setEnabled(False)
        confirm.toggled.connect(dlg.install.setEnabled)               # the Install button stays disabled until the confirmation box is ticked
    _last['dialog'] = dlg
    return dlg.run() == 'install' and pv.ok


def show_result(parent, res, pv):
    lines = [f'Installed {res.name} version {res.version}: {len(res.written)} file(s) written.']
    if res.backups:
        lines.append(f'{len(res.backups)} replaced file(s) were backed up first (Backups/packages/...).')
    if res.unlocked:
        lines.append('The procedure was verified and locked; it is now UNLOCKED and needs hardware re-verification.')
    if res.mark_applied:
        lines.append("The package's verified mark matched the installed files, so the procedure is marked verified and locked.")
    elif pv.mark is not None and pv.mark_state != 'valid':
        lines.append("The package's verified mark was not accepted: " + pv.mark_detail)
    lines += res.notes
    message(parent, 'info', 'Package installed', '\n\n'.join(lines))


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Register procedure / Restore previous version (Manager.add / Manager.restore_previous)
# ---------------------------------------------------------------------------------------------------------------------------------------------
REGISTER_FIELDS = ('Procedure name *', 'Manufacturer', 'Model', 'Category', 'Description')


def ask_register(parent, script_path, shown_path, save):
    """The 'Register Calibration Procedure' form.  `save(name, manufacturer, model, category, description)` is called on 'Save procedure'; it raises
    sqlite3.IntegrityError when the script is registered already.  Returns True when saved."""
    import sqlite3
    dlg = ModalDialog(parent, 'Register Calibration Procedure', width=620)
    dlg.set_title('Register a procedure')
    dlg.sub_label.setText(f'Script: {shown_path}')
    dlg.sub_label.setVisible(True)
    edits = {}
    grid = QFormLayout()
    grid.setHorizontalSpacing(M.md)
    for text, default in zip(REGISTER_FIELDS, (Path(script_path).stem.replace('_', ' '), '', '', '', '')):
        edit = QLineEdit(default)
        edits[text.rstrip(' *')] = edit
        grid.addRow(label(text), edit)
    dlg.body.addLayout(grid)
    result = {'name': None}

    def do_save():
        name = edits['Procedure name'].text().strip()
        if not name:
            message(dlg, 'error', 'Missing name', 'Enter a procedure name.')
            return False
        try:
            save(name, edits['Manufacturer'].text().strip(), edits['Model'].text().strip(), edits['Category'].text().strip(), edits['Description'].text().strip())
        except sqlite3.IntegrityError:
            message(dlg, 'error', 'Already registered', 'This script is already in the library.')
            return False
        result['name'] = name
        return True
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Save procedure', role='primary', result='save', default=True, callback=do_save)
    dlg.edits = edits
    _last['dialog'] = dlg
    dlg.run()
    return result['name']


def ask_restore(parent, rec, backups, restore):
    """The 'Restore procedure version' list.  `restore(source_path, window)` does the validation and the replace; returns True when it restored."""
    from PySide6.QtWidgets import QListWidget
    dlg = ModalDialog(parent, 'Restore procedure version', width=640)
    dlg.set_title(f'Restore {rec[1]}')
    dlg.sub_label.setText('Pick the version to bring back. The current version is backed up first.')
    dlg.sub_label.setVisible(True)
    lb = QListWidget()
    lb.setMinimumHeight(220)
    for b in backups:
        lb.addItem(b.name)
    lb.setCurrentRow(0)
    dlg.body.addWidget(lb)
    dlg.list = lb

    def go():
        row = lb.currentRow()
        if row < 0:
            return False
        return restore(backups[row], dlg) is not False
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Restore selected', role='primary', result='restore', default=True, callback=go)
    _last['dialog'] = dlg
    return dlg.run() == 'restore'


# ---------------------------------------------------------------------------------------------------------------------------------------------
# the readiness-check output
# ---------------------------------------------------------------------------------------------------------------------------------------------
def show_text_window(parent, title, text):
    """A non-modal read-only monospace window (the readiness check output)."""
    from PySide6.QtWidgets import QDialog
    win = QDialog(parent)
    win.setWindowTitle(title)
    win.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
    v = QVBoxLayout(win)
    v.setContentsMargins(M.md, M.md, M.md, M.md)
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    box.setPlainText(text)
    box.setProperty('mono', True)
    box.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {M.font_mono}px;")
    v.addWidget(box)
    win.resize(980, 640)
    win.text_box = box
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    win.show()
    return win


# ---------------------------------------------------------------------------------------------------------------------------------------------
# mdd_import_ui.py
# ---------------------------------------------------------------------------------------------------------------------------------------------
def open_mdd_preview(parent, path, on_created=None, status=None, registry=None, spec_root=None, archive_to=None):
    """Parse `path` and open the import preview.  Returns the Preview (None when the file cannot be read; the reason is shown).  `status` is a callable
    taking the status text (or None)."""
    import mdd_convert as mc
    from mdd_importer_v49 import parse_mdd
    try:
        parsed = parse_mdd(path)
        conv = mc.convert(parsed)
    except (OSError, ValueError) as exc:
        message(parent, 'error', 'Cannot import datasheet', str(exc))
        return None
    pv = MddPreview(parent, parsed, conv, on_created, status, registry, spec_root, archive_to)
    pv.dialog.show()
    return pv


def _who():
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return ''


class MddPreview:
    """The import preview: nothing is created until 'Create manual procedure' is pressed (mdd_import_ui.Preview)."""
    STATUS_TEXT = {'ok': 'Converted', 'uncertain': 'CHECK', 'skipped': 'NOT converted'}
    INTRO = ('The datasheet is imported as a MANUAL calibration: the technician types each reading straight into the test point grid. Nominals and limits are '
             'exactly as printed in the MDD; ranges are not in an MDD, so none is shown. The original .MDD is kept as an archive copy; its embedded commands '
             'and scripts are never run.')

    def __init__(self, parent, parsed, conv, on_created, status, registry=None, spec_root=None, archive_to=None):
        self.parent, self.parsed, self.conv = parent, parsed, conv
        self.on_created, self.status = on_created, status
        self.registry, self.spec_root, self.archive_to = registry, spec_root, archive_to
        self.who = _who
        h = conv.source['header']
        dlg = self.dialog = ModalDialog(parent, 'Import Mudcats datasheet as a manual calibration - review before creating', width=1000, modal=False)
        dlg.setMinimumHeight(760)
        dlg.title_label.hide()
        self.heading = label('', 'h2')
        head = QHBoxLayout()
        head.addWidget(self.heading, 1)
        self.pills = QHBoxLayout()
        head.addLayout(self.pills)
        dlg.body.addLayout(head)
        dlg.body.addWidget(label(f"Source: {conv.source['filename'] or '-'}   |   Procedure: {h['Procedure_Name'] or '-'}   |   Interval: {h['CalInterval'] or '-'}", 'sub'))
        dlg.body.addWidget(Banner(self.INTRO, 'info'))
        names = QHBoxLayout()
        self.make, self.model, self.title = QLineEdit(conv.sheet.make), QLineEdit(conv.sheet.model), QLineEdit(conv.sheet.title)
        for text, edit, stretch in (('Make', self.make, 2), ('Model', self.model, 2), ('Title', self.title, 4)):
            names.addWidget(label(text))
            names.addWidget(edit, stretch)
            edit.returnPressed.connect(self.rebuild)
        from qtui.widgets import GhostButton
        names.addWidget(GhostButton('Update preview', on_click=self.rebuild))
        dlg.body.addLayout(names)
        self.existing = QVBoxLayout()
        dlg.body.addLayout(self.existing)
        self.group = QButtonGroup(dlg)
        self.grid = DataTable([Column('no', 'No.', 50, align='right'), Column('section', 'Section', 170), Column('nominal', 'Nominal (as printed)', 230),
                               Column('unit', 'Unit', 70), Column('low', 'Low', 80), Column('high', 'High', 80),
                               Column('result', 'Result', 110, getter=lambda r: self.STATUS_TEXT[r['status']]),
                               Column('message', 'Why / note', 420, stretch=True)], [], row_tone=lambda r: {'skipped': 'fail', 'uncertain': 'warn'}.get(r['status']),
                              row_key=lambda r: r['no'], multi=False)
        self.grid.setMinimumHeight(380)
        dlg.body.addWidget(self.grid, 1)
        dlg.add_button('Cancel', cancel=True)
        self.create_btn = dlg.add_button('Create manual procedure', role='primary', result='create', default=True, callback=self.create, close=False)
        self.fill()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def fill(self):
        import mdd_convert as mc
        c = self.conv
        self.heading.setText(f'{self.make.text().strip()}  {self.model.text().strip()}  -  {self.title.text().strip()}')
        self._clear(self.pills)
        self.pill_texts = [f'{c.sections} section(s)', f'{c.converted} of {c.total} points converted']
        self.pills.addWidget(Badge(self.pill_texts[0], 'info'))
        self.pills.addWidget(Badge(self.pill_texts[1], 'good' if not c.skipped else 'info'))
        if c.uncertain:
            self.pill_texts.append(f'{c.uncertain} to check')
            self.pills.addWidget(Badge(self.pill_texts[-1], 'warn'))
        if c.skipped:
            self.pill_texts.append(f'{c.skipped} NOT converted')
            self.pills.addWidget(Badge(self.pill_texts[-1], 'bad'))
        self.grid.set_rows(list(c.rows), keep_selection=False)
        self._clear(self.existing)
        for b in list(self.group.buttons()):
            self.group.removeButton(b)
        found = mc.find_existing(c, self.registry, self.spec_root)
        self.found = found
        self.choice = 'new'
        self.radio_new = self.radio_version = None
        if found:
            e = found[0]
            why = ('This exact .MDD file was imported before as' if e.reason == 'same_file' else 'A procedure with this name already exists:')
            self.existing.addWidget(Banner(f'{why} "{e.title}" ({e.uid}, {e.versions} saved version(s)). Nothing is overwritten: choose what to do.', 'warn'))
            self.radio_new = QRadioButton('Create a separate new procedure (default)')
            self.radio_version = QRadioButton(f'Save as a NEW VERSION of "{e.title}" (earlier versions are kept)')
            self.radio_new.setChecked(True)
            for b in (self.radio_new, self.radio_version):
                self.group.addButton(b)
                self.existing.addWidget(b)
        gen = [i for i in c.issues if i.point == 0]
        if gen:
            self.existing.addWidget(Banner('  '.join(i.message for i in gen), 'warn'))
        self.create_btn.setEnabled(True)

    def rebuild(self):
        import mdd_convert as mc
        try:
            self.conv = mc.convert(self.parsed, make=self.make.text(), model=self.model.text(), title=self.title.text())
        except ValueError as exc:
            message(self.dialog, 'error', 'Cannot convert', str(exc))
            return
        self.fill()

    def create(self):
        import mdd_convert as mc
        choice = 'version' if (self.radio_version is not None and self.radio_version.isChecked()) else 'new'
        if (self.make.text().strip(), self.model.text().strip(), self.title.text().strip()) != (self.conv.sheet.make, self.conv.sheet.model, self.conv.sheet.title):
            self.rebuild()
            if self.found and choice == 'version' and self.radio_version is not None:
                self.radio_version.setChecked(True)
        replace = self.found[0].uid if (self.found and self.radio_version is not None and self.radio_version.isChecked()) else None
        res = mc.register(self.conv, self.parsed, self.who(), replace_uid=replace, registry=self.registry, root=self.spec_root, archive_to=self.archive_to)
        if not res.ok:
            message(self.dialog, 'error', 'Import failed', res.message or 'The procedure could not be created.')
            return False
        self.dialog.result_key = 'create'
        self.dialog.accept()
        msg = (f'Created the manual calibration "{self.conv.sheet.title}" (version {res.version}): {self.conv.converted} of {self.conv.total} test points. '
               f'{self.conv.skipped} not converted, {self.conv.uncertain} to check. It is listed under Manual Calibrations.')
        if self.status is not None:
            self.status(msg)
        if self.on_created:
            self.on_created(res)
        message(self.parent, 'info', 'Datasheet import', msg)
        return False
