"""Qt twin of procmods_ui.py: the 'Modify procedure' window (thin: all behaviour lives in procmods_ui_model.py, which is unit-tested without a toolkit),
the developer-mode passphrase dialog, and the shell hooks (the 'Modify procedure' action with its MODIFIED / DEVELOPER MODE chips, the in-run 'Edit point'
action).  Same public names, same behaviour as the Tk module:

    import qtui.screens.procmods_editor as procmods_editor
    win = procmods_editor.open_modify_window(parent, ctx)              # ctx = procmods_ui_model.Context(...)
    ctl = procmods_editor.attach_to_shell(shell, lambda: ctx)          # adds the 'Modify procedure' action + the MODIFIED / DEVELOPER MODE chips
    hook = procmods_editor.attach_live(app, shell)                     # 'Edit point' in a running procedure window (opens procmods_point_editor)

The window is READ-ONLY (everything visible, nothing editable) until developer mode is unlocked with the passphrase, and while a run is in progress.  It
never prints or stores the passphrase (the entries are wiped as soon as they are used).  `shell` is whatever the engine's window gives: it needs
`add_action(text, command, short=...)`, `set_modified(n)`, `set_devmode(on)` and optionally `set_verified(text)` and `root` (a QWidget, the parent of the windows).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

import procmods as pm
import procmods_ui_model as M
from qtui import theme
from qtui.screens import common
from qtui.table import Column, DataTable
from qtui.widgets import Badge, SearchField, SegmentedFilter, label

POLL_MS = 1000
FILTERS = (('all', 'All'), ('modified', 'Modified'), ('unverified', 'Unverified'), ('locked', 'Locked'))
DEFAULT_SIZE = (1000, 660)

_shared_lock = None


def shared_lock(devmode=None) -> M.DevLock:
    """One DevLock per process, so every Modify window (and the Manager) shares the same unlocked session."""
    global _shared_lock
    if _shared_lock is None or (devmode is not None and _shared_lock.devmode is not devmode):
        _shared_lock = M.DevLock(devmode)
    return _shared_lock


# ------------------------------------------------------------------------------------------------------------ passphrase dialog
class UnlockDialog(common.ModalDialog):
    """Modal.  First use: choose + confirm a passphrase.  Otherwise: enter it.  Shows the lock-out delay.  `self.ok` tells the result."""

    def __init__(self, parent, lock: M.DevLock):
        first = lock.state == 'unset'
        super().__init__(common.qparent(parent), 'Developer mode: set passphrase' if first else 'Developer mode: unlock', width=440)
        self.lock = lock
        self.ok = False
        intro = ('Developer mode protects procedure changes. Choose a passphrase (at least 8 characters). It is stored only as a hash on '
                 'this computer; if you forget it, delete ~/.calibration_suite/devmode.json to start again.') if first else \
            'Enter the developer-mode passphrase to change this procedure. Without it the window is read-only.'
        self.add_text(intro)
        self.body.addWidget(label('Passphrase', 'section'))
        self.e1 = QLineEdit()
        self.e1.setEchoMode(QLineEdit.EchoMode.Password)
        self.e1.setAccessibleName('Passphrase')
        self.body.addWidget(self.e1)
        self.e2 = None
        if first:
            self.body.addWidget(label('Repeat passphrase', 'section'))
            self.e2 = QLineEdit()
            self.e2.setEchoMode(QLineEdit.EchoMode.Password)
            self.e2.setAccessibleName('Repeat passphrase')
            self.body.addWidget(self.e2)
        self.msg = common.ToneLabel('bad')
        self.body.addWidget(self.msg)
        self.add_button('Cancel', cancel=True)
        self.go = self.add_button('Set passphrase' if first else 'Unlock', role='primary', default=True, result='go', callback=self.submit)
        self.initial_focus = self.e1
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._tick()

    @property
    def pw(self):
        return common.TextVar(self.e1)

    @property
    def pw2(self):
        return common.TextVar(self.e2) if self.e2 is not None else common.TextVar(QLineEdit())

    def _tick(self):
        """Counts the lock-out down on screen."""
        text = self.lock.lockout_text()
        if text:
            self.msg.setText(text)
        self.go.setEnabled(not text)
        if text:
            self._timer.start()
        else:
            self._timer.stop()

    def submit(self):
        """Returns False (the dialog stays) unless the passphrase was accepted."""
        if self.lock.state == 'unset':
            res = self.lock.first_use(self.e1.text(), self.e2.text() if self.e2 is not None else '')
        else:
            res = self.lock.unlock(self.e1.text())
        self.e1.clear()                                        # never keep it around
        if self.e2 is not None:
            self.e2.clear()
        if res.ok:
            self.ok = True
            return True
        self.msg.setText(res.message)
        self._tick()
        return False


def ask_unlock(parent, lock: M.DevLock) -> bool:
    if lock.unlocked:
        return True
    dlg = UnlockDialog(parent, lock)
    dlg.run()
    return dlg.ok


# ------------------------------------------------------------------------------------------------------------ list + editor tabs
class Field:
    """A caption over a read-only value (the Tk `_field`)."""

    def __init__(self, layout, caption):
        self.caption = label(caption, 'hint')
        self.value = label('', wrap=True)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addSpacing(6)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set(self, text):
        self.value.setText(str(text))

    def text(self) -> str:
        return self.value.text()


class _Tab(QWidget):
    """A searchable list on the left, an editor pane on the right.  Subclasses fill `rows()` and `build_editor()`."""
    kind = ''
    UNIFORM = 1                                   # how the two panes share the width (list : editor)

    def __init__(self, parent, win):
        super().__init__(parent)
        self.win = win
        self.model = win.model
        self.selected = None
        self._rows = {}
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 0)
        self.table = self.make_table()
        self.table.selectionChangedRows.connect(self._on_rows)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.table)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor = QWidget()
        self.editor.setObjectName('tabEditor')
        self.edit_layout = QVBoxLayout(self.editor)
        self.edit_layout.setContentsMargins(14, 0, 4, 0)
        self.edit_layout.setSpacing(2)
        scroll.setWidget(self.editor)
        self.split.addWidget(scroll)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([360, 640])
        lay.addWidget(self.split)
        self.build_editor()
        self.edit_layout.addStretch(1)

    # -- to override
    def columns(self):
        return [Column('flags', '', width=70, getter=self.flag_text), Column('name', 'Item', width=300, stretch=True, getter=self.name_text, tone=self.name_tone)]

    def rows(self, flt, search):
        return []

    def build_editor(self):
        pass

    def show(self, row):
        pass

    # -- shared
    def make_table(self):
        return DataTable(self.columns(), [], row_tone=self.row_tone, row_key=self.row_key, multi=False, tone_style='text', empty_text='Nothing to show')

    @staticmethod
    def row_key(r):
        return r.get('target') or r['key']

    @staticmethod
    def row_tone(r):
        return 'warn' if r.get('modified') or r.get('draft') else None

    @staticmethod
    def name_tone(r):
        return 'muted' if r.get('locked') and not (r.get('modified') or r.get('draft')) else None

    def reload(self):
        keep = self.selected
        self._rows = {}
        rows = []
        for r in self.rows(self.win.filter_key(), self.win.search_text()):
            self._rows[self.row_key(r)] = r
            rows.append(r)
        self.table.set_rows(rows, keep_selection=False)
        if keep and keep in self._rows:
            self.table.select_rows([self._rows[keep]])
            self.selected = keep
            self.show(self._rows[keep])
        else:
            self.selected = None
            self.show(None)

    def select(self, key):
        """Select the row `key` (what a click does); the editor pane follows at once."""
        row = self._rows.get(key)
        self.table.select_rows([row] if row is not None else [])
        self._on_rows([row] if row is not None else [])

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

    def _on_rows(self, rows):
        key = self.row_key(rows[0]) if rows else None
        if key == self.selected and rows:
            return
        self.on_select(key)

    def on_select(self, key=None):
        self.selected = key
        self.show(self._rows.get(self.selected))

    def set_enabled(self, widgets, enabled):
        common.set_enabled(widgets, enabled)

    def heading(self, text):
        lab = label(text, 'section', wrap=True)
        self.edit_layout.addWidget(lab)
        return lab

    def field(self, caption):
        return Field(self.edit_layout, caption)

    def caption(self, text):
        self.edit_layout.addSpacing(8)
        lab = label(text, 'hint')
        self.edit_layout.addWidget(lab)
        return lab

    def note(self, text):
        self.edit_layout.addSpacing(6)
        lab = common.hint(text)
        self.edit_layout.addWidget(lab)
        return lab

    def reason_row(self):
        self.edit_layout.addSpacing(10)
        self.edit_layout.addWidget(label('Reason for the change (required)', 'section'))
        self.reason = QLineEdit()
        self.reason.setAccessibleName('Reason for the change')
        self.edit_layout.addWidget(self.reason)
        self.reason.textEdited.connect(lambda _t: self.model.set_reason(self.kind, self.selected, self.reason.text()) if self.selected else None)
        return self.reason

    def buttons_row(self, extra=()):
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        self.btn_undo = QPushButton('Undo')
        self.btn_undo.clicked.connect(self.undo)
        self.btn_reset = QPushButton('Reset to factory')
        self.btn_reset.clicked.connect(self.reset)
        for b in (*extra, self.btn_undo, self.btn_reset):
            row.addWidget(b)
        row.addStretch(1)
        self.edit_layout.addLayout(row)
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


class CommandsTab(_Tab):
    kind = 'command'

    def columns(self):
        return [Column('flags', '', width=70, getter=self.flag_text), Column('name', 'Command', width=190, getter=lambda r: r['name'], tone=self.name_tone),
                Column('key', 'Template', width=190, stretch=True, mono=True, getter=lambda r: r['current'])]

    def rows(self, flt, search):
        return self.model.commands(flt, search)

    def name_text(self, r):
        return r['name']

    def build_editor(self):
        self.title = self.heading('Select a command')
        self.meta = self.field('Kind / risk / source')
        self.factory = self.field('Factory')
        self.caption('Current (editable)')
        self.entry = QLineEdit()
        self.entry.setProperty('mono', True)
        self.entry.setAccessibleName('Current command')
        self.edit_layout.addWidget(self.entry)
        self.entry.textEdited.connect(lambda _t: self.typed())
        self.placeholders = self.field('Placeholders')
        self.paired = self.field('Paired check')
        self.edit_layout.addSpacing(8)
        self.status = common.ToneLabel('text')
        self.edit_layout.addWidget(self.status)
        self.lockmsg = common.ToneLabel('warn')
        self.edit_layout.addWidget(self.lockmsg)
        self.reason_entry = self.reason_row()
        self.btn_test = QPushButton('Test this command')
        self.btn_test.clicked.connect(self.test)
        self.buttons_row(extra=(self.btn_test,))
        self.edit_layout.addSpacing(8)
        self.test_out = common.ToneLabel('text')
        self.edit_layout.addWidget(self.test_out)
        self.edit_layout.addSpacing(8)
        self.edit_layout.addWidget(common.hint(M.TEST_NOTE))

    def show(self, row):
        d = self.model.command_detail(row['target']) if row else {'found': False}
        if not d['found']:
            self.title.setText('Select a command')
            for f in (self.meta, self.factory, self.placeholders, self.paired):
                f.set('')
            for lab in (self.status, self.lockmsg, self.test_out):
                lab.setText('')
            self.entry.setText('')
            self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset, self.btn_test], False)
            return
        badges = ('   ' + ' '.join(self.flag_text({'badges': d['badges']}).split())) if d['badges'] else ''
        self.title.setText(d['name'] + badges)
        self.meta.set(f'{d["kind"]} / {d["risk"]} / {"verified" if d["verified"] else "UNVERIFIED in the manual"}' + (f' / {d["ref"]}' if d['ref'] else ''))
        self.factory.set(d['factory'])
        self.entry.setText(d['current'])
        self.placeholders.set(', '.join(f'{{{n}}}{" (required)" if p["required"] else ""}' for n, p in d['placeholders'].items()) or 'none')
        self.paired.set((d['paired'] + ' (read back)') if d['paired'] else 'none')
        self.lockmsg.setText(d['lock_reason'] if not d['editable'] else '')
        self.reason.setText(d['reason'])
        self.status.setText(d['status'])
        self.test_out.setText(self._test_text(d['test_result']))
        self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], d['editable'])
        self.set_enabled([self.btn_test], d['can_test'])
        self.btn_test.setText('Test this command' if d['can_test'] else 'Test unavailable')
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
            self.model.stage_command(self.selected, self.entry.text())
        except pm.OverrideError as ex:
            self.status.setText(str(ex))
            return
        self.status.setText(self.model.command_status(self.selected, self.entry.text()))
        self.win.update_buttons()

    def test(self):
        if not self.selected:
            return
        self.btn_test.setEnabled(False)                     # one press, one test; nothing is retried automatically
        res = self.model.test_command(self.selected, self.entry.text())
        self.test_out.setText(self._test_text(res))
        self.status.setText(self.model.command_status(self.selected, self.entry.text()))
        QTimer.singleShot(300, self._reshow)

    def _reshow(self):
        if common.alive(self):
            self.show(self._rows.get(self.selected))


class SettingsTab(_Tab):
    kind = 'param'

    def columns(self):
        return [Column('flags', '', width=70, getter=self.flag_text), Column('name', 'Setting', width=220, getter=self.name_text, tone=self.name_tone),
                Column('cur', 'Value', width=120, stretch=True, getter=lambda r: f'{r["current"]} {r["unit"]}'.strip())]

    def rows(self, flt, search):
        return self.model.settings(flt, search)

    def build_editor(self):
        self.title = self.heading('Select a setting')
        self.factory = self.field('Factory')
        self.edit_layout.addSpacing(6)
        self.cond = common.ToneLabel('warn')
        self.edit_layout.addWidget(self.cond)
        self.caption('Value (editable)')
        self.entry = QLineEdit()
        self.entry.setAccessibleName('Value')
        self.edit_layout.addWidget(self.entry)
        self.entry.textEdited.connect(lambda _t: self.typed())
        self.reason_entry = self.reason_row()
        self.buttons_row()

    def show(self, row):
        if not row:
            self.title.setText('Select a setting')
            self.factory.set('')
            self.entry.setText('')
            self.cond.setText('')
            self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], False)
            return
        self.title.setText(row['name'] + ('   [M]' if row['modified'] else ''))
        self.factory.set(f'{row["factory"]} {row["unit"]}'.strip())
        self.entry.setText(str(row['current']))
        self.cond.setText('Changes the test conditions: the report states they differ from the manufacturer\'s procedure.' if row['affects_conditions'] else '')
        self.reason.setText(self.model.reasons.get(('param', row['key']), ''))
        self.set_enabled([self.entry, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable)

    def typed(self):
        if not self.selected:
            return
        raw = self.entry.text().strip()
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

    def columns(self):
        return [Column('flags', '', width=70, getter=self.flag_text), Column('name', 'Test point', width=300, stretch=True, getter=self.name_text, tone=self.name_tone),
                Column('state', 'State', width=90, getter=lambda r: 'skipped' if r['skip'] else r['state'])]

    def rows(self, flt, search):
        return self.model.points(flt, search)

    def build_editor(self):
        self.title = self.heading('Select a test point')
        self.note('A skipped point is not measured and is listed in the report with your reason. Limits and pass/fail are not '
                  'changed here (see Tolerances).')
        self.edit_layout.addSpacing(10)
        self.chk = QCheckBox('Skip this point')
        self.chk.clicked.connect(self.toggled)
        self.edit_layout.addWidget(self.chk)
        self.reason_entry = self.reason_row()
        self.buttons_row()

    def show(self, row):
        if not row:
            self.title.setText('Select a test point')
            self.set_enabled([self.chk, self.reason_entry, self.btn_undo, self.btn_reset], False)
            return
        self.title.setText(row['name'])
        self.chk.setChecked(bool(row['skip']) or ('point', row['key']) in self.model.drafts)
        self.reason.setText(self.model.reasons.get(('point', row['key']), ''))
        self.set_enabled([self.chk, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable)

    def toggled(self, *_):
        if self.selected:
            try:
                self.problems(self.model.stage_skip(self.selected, self.chk.isChecked()))
            except pm.OverrideError as ex:
                self.win.set_message(str(ex))
            self.win.update_buttons()


class TextTab(_Tab):
    kind = 'text'

    def rows(self, flt, search):
        return self.model.texts(flt, search)

    def build_editor(self):
        self.title = self.heading('Select a text item')
        self.factory = self.field('Factory')
        self.caption('Current (editable)')
        self.box = QPlainTextEdit()
        self.box.setAccessibleName('Current text')
        self.box.setMinimumHeight(120)
        self.edit_layout.addWidget(self.box)
        self.box.textChanged.connect(self._box_changed)
        self.lockmsg = common.ToneLabel('warn')
        self.edit_layout.addWidget(self.lockmsg)
        self.reason_entry = self.reason_row()
        self.buttons_row()

    def show(self, row):
        self._loading = True
        try:
            self.box.setPlainText('')
            if not row:
                self.title.setText('Select a text item')
                self.factory.set('')
                self.lockmsg.setText('')
                self.set_enabled([self.box, self.reason_entry, self.btn_undo, self.btn_reset], False)
                return
            self.title.setText(row['name'] + ('   [M]' if row['modified'] else ''))
            self.factory.set(row['factory'])
            d = self.model.drafts.get(('text', row['key']))
            self.box.setPlainText(d.value['text'] if d else row['current'])
            self.lockmsg.setText(row['lock_reason'])
            self.reason.setText(self.model.reasons.get(('text', row['key']), ''))
            self.set_enabled([self.box, self.reason_entry, self.btn_undo, self.btn_reset], self.model.editable and not row['locked'])
        finally:
            self._loading = False

    def _box_changed(self):
        if not self._loading:
            self.typed()

    def typed(self):
        if self.selected:
            try:
                self.problems(self.model.stage_text(self.selected, self.box.toPlainText().rstrip('\n')))
            except pm.OverrideError as ex:
                self.win.set_message(str(ex))
            self.win.update_buttons()


class TolerancesTab(_Tab):
    kind = 'limit'

    def columns(self):
        return [Column('flags', '', width=60, getter=self.flag_text), Column('name', 'Test point', width=240, stretch=True, getter=self.name_text, tone=self.name_tone),
                Column('factory', 'Manufacturer', width=120, getter=lambda r: r['factory']),
                Column('cur', 'Used', width=120, getter=lambda r: r['current'] + (' TAMPERED' if r.get('tampered') else ''))]

    def rows(self, flt, search):
        return self.model.tolerances(flt, search)

    def build_editor(self):
        self.title = self.heading('Select a test point')
        self.factory = self.field('Manufacturer tolerance (read-only)')
        self.note('Pass/fail is judged against the tolerance used, and the report says the tolerance was modified. Uncertainty '
                  'is not changed.')
        self.edit_layout.addSpacing(8)
        self.lab_a = label('', 'hint')
        self.edit_layout.addWidget(self.lab_a)
        self.ent_a = QLineEdit()
        self.edit_layout.addWidget(self.ent_a)
        self.edit_layout.addSpacing(8)
        self.lab_b = label('', 'hint')
        self.edit_layout.addWidget(self.lab_b)
        self.ent_b = QLineEdit()
        self.edit_layout.addWidget(self.ent_b)
        for w in (self.ent_a, self.ent_b):
            w.textEdited.connect(lambda _t: self.typed())
        self.reason_entry = self.reason_row()
        self.buttons_row()

    def show(self, row):
        widgets = [self.ent_a, self.ent_b, self.reason_entry, self.btn_undo, self.btn_reset]
        if not row:
            self.title.setText('Select a test point')
            self.factory.set('')
            self.set_enabled(widgets, False)
            return
        p = next(p for p, k in zip(self.model.ctx.points, pm.point_keys(self.model.ctx.points)) if k == row['key'])
        fac = pm.limit_factory(p)
        cur = self.model.oset.limit_override(row['key'])
        cv = (cur or {}).get('value', {})
        self.title.setText(row['name'] + ('   [M]' if row['modified'] else '') + ('   TAMPERED: not applied' if row.get('tampered') else ''))
        self.factory.set(row['factory'])
        if fac['mode'] == 'error':
            self.lab_a.setText(f'+/- error ({row["unit"]})')
            self.ent_a.setText(str(cv.get('error', fac['error'])))
            self.lab_b.setText('')
            self.ent_b.setText('')
            self.set_enabled([self.ent_b], False)
            enable = [self.ent_a]
        else:
            self.lab_a.setText(f'Low limit ({row["unit"]})')
            self.lab_b.setText(f'High limit ({row["unit"]})')
            self.ent_a.setText(str(cv.get('low', fac['low'])))
            self.ent_b.setText(str(cv.get('high', fac['high'])))
            enable = [self.ent_a, self.ent_b]
        self.reason.setText(self.model.reasons.get(('limit', row['key']), ''))
        self.set_enabled(widgets, False)
        if self.model.editable:
            self.set_enabled(enable + [self.reason_entry, self.btn_undo, self.btn_reset], True)

    def typed(self):
        if not self.selected:
            return
        row = self._rows[self.selected]
        try:
            if row['mode'] == 'error':
                probs = self.model.stage_limit(self.selected, error=self.ent_a.text().strip())
            else:
                probs = self.model.stage_limit(self.selected, low=self.ent_a.text().strip(), high=self.ent_b.text().strip())
            self.problems(probs)
        except pm.OverrideError as ex:
            self.win.set_message(str(ex))
        self.win.update_buttons()


class ChangesTab(_Tab):
    kind = ''

    def __init__(self, parent, win):
        QWidget.__init__(self, parent)
        self.win = win
        self.model = win.model
        self.selected = None
        self._rows = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 0)
        self.table = DataTable(self.columns(), [], row_tone=lambda r: 'warn' if r['status'] == 'active' else None, row_key=lambda r: r['uid'], multi=False,
                               tone_style='text', empty_text='No changes')
        self.table.selectionChangedRows.connect(self._on_rows)
        lay.addWidget(self.table, 1)
        self.detail = label('', wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.detail)
        row = QHBoxLayout()
        self.btn_reset = QPushButton('Reset selected')
        self.btn_reset.clicked.connect(self.reset_selected)
        self.btn_all = QPushButton('Reset all to factory...')
        self.btn_all.clicked.connect(win.reset_all)
        row.addWidget(self.btn_reset)
        row.addWidget(self.btn_all)
        row.addStretch(1)
        lay.addLayout(row)

    def columns(self):
        return [Column('flags', '', width=60, getter=self.flag_text), Column('name', 'Item', width=170, getter=lambda r: r['label']),
                Column('from', 'Factory', width=150, getter=lambda r: r['factory']), Column('to', 'Current', width=150, getter=lambda r: r['current']),
                Column('scope', 'Applies to', width=110, getter=lambda r: r['applies_to']),
                Column('status', 'Status', width=80, stretch=True, getter=lambda r: 'TAMPERED' if r['tampered'] else r['status'])]

    def reload(self):
        keep = self.selected
        self._rows = {}
        needle = self.win.search_text().casefold()
        rows = []
        for r in self.model.changes():
            if needle and needle not in f'{r["label"]} {r["factory"]} {r["current"]} {r["reason"]}'.casefold():
                continue
            self._rows[r['uid']] = r
            rows.append(r)
        self.table.set_rows(rows, keep_selection=False)
        if keep in self._rows:
            self.table.select_rows([self._rows[keep]])
        else:
            self.selected = None
            self.detail.setText('')
        self.set_enabled([self.btn_reset, self.btn_all], self.model.editable)

    def on_select(self, key=None):
        self.selected = key
        r = self._rows.get(self.selected)
        if not r:
            self.detail.setText('')
            return
        self.detail.setText(f'{r["label"]}: {r["factory"]}  ->  {r["current"]}\nReason: {r["reason"]}   By: {r["author"]}   {r["at"]}'
                            + (f'   Imported by {r["imported_by"]}' if r.get('imported_by') else '')
                            + ('\nUNVERIFIED: not tested on the instrument.' if r['unverified'] else ''))

    @staticmethod
    def row_key(r):
        return r['uid']

    def reset_selected(self):
        r = self._rows.get(self.selected)
        if r:
            self.model.stage_reset(r['kind'], r['target'])
            self.win.refresh()
            self.win.set_message('Reset staged. Give a reason, then press Apply.')


TAB_CLASSES = {'Commands': CommandsTab, 'Settings': SettingsTab, 'Points': PointsTab, 'Text': TextTab, 'Tolerances': TolerancesTab,
               'Changes': ChangesTab}


# ------------------------------------------------------------------------------------------------------------ the window
class ModifyWindow(QWidget):
    def __init__(self, parent, model: M.ProcModsModel, on_change=None):
        super().__init__(common.qparent(parent), Qt.WindowType.Window)
        self.setObjectName('root')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.model = model
        self.lock = model.lock
        self.on_change = on_change
        self._closing = False
        ctx = model.ctx
        self.setWindowTitle(('Edit procedure' if model.live_mode else 'Modify procedure') + f': {ctx.title}'
                            + (f' - asset {ctx.asset_id}' if ctx.asset_id else '') + (' [DEMO]' if ctx.demo else ''))
        common.clamp_size(self, *DEFAULT_SIZE, 760, 480)
        self.tabs = {}
        self._tips = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        self.banner = label('', wrap=True)
        head.addWidget(self.banner, 1)
        self.chip_mod = Badge('', 'warn')
        self.chip_dev = Badge('DEVELOPER MODE', 'warn')
        self.btn_lock = QPushButton('Unlock...')
        self.btn_lock.clicked.connect(self.toggle_lock)
        head.addWidget(self.chip_mod)
        head.addWidget(self.chip_dev)
        head.addWidget(self.btn_lock)
        root.addLayout(head)
        self.info = common.hint('')                              # live mode: which point the saved changes start at (not an error: not red)
        root.addWidget(self.info)

        bar = QHBoxLayout()
        bar.addWidget(label('Scope for new edits:'))
        self.scope_buttons = {}
        for value in pm.SCOPES:
            text = M.SCOPE_LABELS[value] + (f' ({ctx.asset_id})' if value == 'asset' and ctx.asset_id else f' ({ctx.model})' if value == 'model' and ctx.model else '')
            rb = QRadioButton(text)
            rb.setChecked(value == model.scope)
            rb.clicked.connect(lambda _c=False, v=value: self.scope_changed(v))
            self.scope_buttons[value] = rb
            bar.addWidget(rb)
        bar.addStretch(1)
        root.addLayout(bar)
        bar2 = QHBoxLayout()
        self.search = SearchField('Search', delay_ms=0)
        self.search.setMinimumWidth(260)
        self.search.queryChanged.connect(lambda _t: self.refresh())
        self.filter = SegmentedFilter(FILTERS)
        self.filter.currentChanged.connect(lambda _k: self.refresh())
        bar2.addWidget(self.search)
        bar2.addWidget(self.filter)
        bar2.addStretch(1)
        root.addLayout(bar2)

        self.nb = QTabWidget()
        root.addWidget(self.nb, 1)
        for name in model.visible_tabs():
            tab = TAB_CLASSES[name](self.nb, self)
            self.tabs[name] = tab
            self.nb.addTab(tab, name)

        self.message = common.ToneLabel('bad')
        root.addWidget(self.message)
        foot = QHBoxLayout()
        self.btn_reset_all = QPushButton('Reset all to factory...')
        self.btn_reset_all.clicked.connect(self.reset_all)
        self.btn_import = QPushButton('Import...')
        self.btn_import.clicked.connect(self.do_import)
        self.btn_export = QPushButton('Export...')
        self.btn_export.clicked.connect(self.do_export)
        self.btn_cancel = QPushButton('Cancel changes')
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_apply = QPushButton('Apply')
        self.btn_apply.setProperty('role', 'primary')
        self.btn_apply.clicked.connect(self.apply)
        self.btn_close = QPushButton('Close')
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_reset_all, self.btn_import, self.btn_export):
            foot.addWidget(b)
        foot.addStretch(1)
        for b in (self.btn_cancel, self.btn_apply, self.btn_close):
            foot.addWidget(b)
        root.addLayout(foot)

        self.lock.on_change(lambda _s: self._safe(self.refresh))
        self.refresh()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    # -- helpers
    def filter_key(self) -> str:
        return self.filter.current()

    def search_text(self) -> str:
        return self.search.text().strip()

    def _safe(self, fn):
        if common.alive(self) and not self._closing:
            fn()

    def tip(self, widget, text):
        self._tips[id(widget)] = text
        common.set_tooltip(widget, text)

    def set_message(self, text):
        self.message.setText(text)

    def scope_changed(self, value=None):
        if value is None:
            value = next((v for v, b in self.scope_buttons.items() if b.isChecked()), self.model.scope)
        try:
            self.model.set_scope(value)
            self.message.setText('')
        except ValueError as ex:
            self.scope_buttons[self.model.scope].setChecked(True)
            self.message.setText(str(ex))

    def _poll(self):
        if not common.alive(self):
            return
        before = self.lock.state
        self.lock.poll()
        if before != self.lock.state or self.lock.state in ('unlocked', 'lockout'):
            self.update_header()
        elif self.model.live_mode:
            self.update_info()                                 # the run moves on: keep 'starts at point N' current

    # -- refresh
    def update_header(self):
        m = self.model
        unlocked = self.lock.unlocked
        self.btn_lock.setText('Lock now' if unlocked else 'Unlock...')
        self.update_info()
        self.chip_dev.setVisible(unlocked)
        n = m.modified_count()
        self.chip_mod.set(M.chip_text(n), 'warn')
        self.chip_mod.setVisible(bool(n))
        if m.editable:
            mins = int(self.lock.remaining_s // 60)
            self.banner.setText(f'Developer mode unlocked; locks after 15 minutes idle ({mins} min left). Changes are staged until you press Apply.')
        else:
            extra = ('  ' + self.lock.lockout_text()) if self.lock.state == 'lockout' else ''
            self.banner.setText(m.read_only_reason + extra + '  Saved changes still apply when you run; "Run factory" is offered at the start of a run.')
        self.update_buttons()

    def update_info(self):
        """Live mode: say which point a saved change applies from, whether anything saved is still waiting, and what demo mode does."""
        m = self.model
        if not m.live_mode:
            self.info.setText('')
            self.info.setVisible(False)
            return
        lines = [m.applies_from_text()]
        waiting = m.ctx.live.pending()
        if waiting:
            lines.append('Saved, not in effect yet: ' + '; '.join(waiting))
        if m.ctx.demo:
            lines.append('DEMO: edits made here apply to this demo run only and are marked demo. Nothing is saved for later runs.')
        self.info.setText('\n'.join(lines))
        self.info.setVisible(True)

    def update_buttons(self):
        m = self.model
        ed = m.editable
        for b, on in ((self.btn_apply, ed and m.dirty), (self.btn_cancel, m.dirty), (self.btn_reset_all, ed),
                      (self.btn_import, ed), (self.btn_export, ed)):
            b.setEnabled(bool(on))
        counts = m.tab_counts()
        for name, tab in self.tabs.items():
            n = counts.get(name, 0)
            self.nb.setTabText(self.nb.indexOf(tab), f'{name} ({n})' if n and name in ('Changes', 'Tolerances') else name)

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
            self.message.setText('A reason is required for every change: ' + ', '.join(miss))
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
            if not common.ask_yes_no(self, 'Confirm wider change', f'{len(need)} change(s) will apply to {where} and stay in effect for later '
                                     f'runs:\n{lines}\n\nContinue?'):
                return
            confirmed = True
        redo = []
        if m.limit_blocked():
            self.message.setText(m.limit_blocked())
            return
        need = m.limit_redo_needed()
        if need:
            names = ', '.join(lab for _k, lab in need)
            if not common.ask_yes_no(self, 'Tolerance change needs a redo', f'The tolerance of {names} concerns a point that already has a reading '
                                     'or is in progress. A tolerance can only be changed for a point that is measured again against it, '
                                     'and the reading taken now will be replaced by the new one.\n\nSave the change and redo the point?'):
                self.message.setText('Not applied: the tolerance of a point that already has a reading changes only together with a redo.')
                return
            redo = [k for k, _lab in need]
        try:
            res = m.apply(confirmed=confirmed, redo=redo)
        except pm.OverrideError as ex:
            self.message.setText(str(ex))
            return
        self.message.setText('; '.join(f'{k}: {msg}' for k, msg in res.errors))
        if m.live_mode and res.done:
            offer = m.redo_offer()
            if offer and offer['key'] not in redo and common.ask_yes_no(
                    self, 'Measure this point again?', f'Saved. Point {offer["id"]} ({offer["desc"]}) is in progress and keeps the settings it started '
                    f'with; the change starts at the next point.\n\nMeasure point {offer["id"]} again with the new settings after it finishes? '
                    'The reading from the old settings will be replaced by the new one. Nothing is retried automatically.'):
                m.ctx.live.request_redo([offer['key']])
        self.refresh()

    def cancel(self):
        self.model.cancel()
        self.message.setText('')
        self.refresh()

    def reset_all(self):
        if not self.model.editable:
            return
        if not common.ask_yes_no(self, 'Reset all to factory', 'Stage the removal of every modification in effect? You still give a reason '
                                 'and press Apply. Saved rows are kept in the audit trail.'):
            return
        n = self.model.stage_reset_all()
        if n:
            reason = common.ask_text(self, 'Reason', 'Reason for resetting to factory (required):')
            if not (reason or '').strip():
                self.model.cancel()
                self.message.setText('Cancelled: a reason is required.')
                self.refresh()
                return
            for it in self.model.pending():
                self.model.set_reason(it['kind'], it['target'], reason.strip())
        self.message.setText(f'{n} reset(s) staged. Press Apply to save them.' if n else 'Nothing to reset.')
        self.refresh()

    def do_export(self):
        path = common.ask_save_path(self, 'Export', '.calov.json', 'Override set (*.calov.json *.json)')
        if not path:
            return
        try:
            notes = self.model.export(path)
            self.message.setText('Exported.' + ('  ' + '; '.join(notes) if notes else ''))
        except (pm.OverrideError, OSError) as ex:
            self.message.setText(str(ex))

    def do_import(self):
        path = common.ask_open_path(self, 'Import', 'Override set (*.calov.json *.json)')
        if not path:
            return
        prev = self.model.import_preview(path)
        if not prev['ok']:
            self.message.setText('; '.join(prev['problems']))
            return
        lines = self.model.preview_lines(prev)
        accept = [l['index'] for l in lines if l['accept']]
        text = '\n'.join(f'  {"+" if l["accept"] else "-"} {l["kind"]} {l["target"]} ({l["state"]})' + (f': {l["problems"][0]}' if l['problems'] else '')
                         for l in lines) or '  (empty)'
        if not accept or not common.ask_yes_no(self, 'Import override set', f'These entries will be imported (+) or skipped (-). Imported commands '
                                               f'are UNVERIFIED here.\n{text}\n\nImport the {len(accept)} marked +?'):
            return
        try:
            created = self.model.import_apply(prev, accept)
            self.message.setText(f'Imported {len(created)} entr{"y" if len(created) == 1 else "ies"}.')
        except pm.OverrideError as ex:
            self.message.setText(str(ex))
        self.refresh()

    def closeEvent(self, ev):
        """Closing (the Close button, the window's close button, Esc-less) asks before discarding staged changes, exactly like the Tk window."""
        if self.model.dirty and not common.ask_yes_no(self, 'Unsaved changes', 'Discard the staged changes?'):
            ev.ignore()
            return
        self._closing = True
        self._poll_timer.stop()
        self.model.cancel()
        super().closeEvent(ev)


def open_modify_window(parent, ctx: M.Context, lock: M.DevLock | None = None, on_change=None):
    """Open the window.  It starts read-only; the technician (or developer) presses Unlock to edit."""
    lock = lock or shared_lock()
    model = M.ProcModsModel(ctx, lock)
    win = ModifyWindow(parent, model, on_change=on_change)
    win.show()
    return win


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
        except RuntimeError:                                     # the shell's widgets are gone
            pass

    def count(self):
        ctx = self.ctx_factory()
        return M.ProcModsModel(ctx, self.lock).modified_count()

    def refresh(self):
        self.shell.set_modified(self.count())
        self.shell.set_devmode(self.lock.unlocked)

    def open(self):
        if common.alive(self.window):
            self.window.raise_()
            self.window.activateWindow()
            return
        self.window = open_modify_window(getattr(self.shell, 'root', None), self.ctx_factory(), self.lock, on_change=lambda _m: self.refresh())


def attach_to_shell(shell, ctx_factory, lock: M.DevLock | None = None) -> ShellHook:
    """Give an engine the 'Modify procedure' action and the MODIFIED (n) / DEVELOPER MODE chips.  ctx_factory() returns a fresh
    procmods_ui_model.Context (so it always reflects the current asset, connection and run state)."""
    return ShellHook(shell, ctx_factory, lock or shared_lock())


# ------------------------------------------------------------------------------------------------------------ inside a procedure window
class LiveHook:
    """The 'Edit point' action of a running procedure window (procmods_live): it opens the same small point window as right-click > Edit,
    for the point selected in the list (procmods_point_editor).  It stays usable during a run: saved edits start at the next point.  The older
    whole-procedure window (open_modify_window) is kept as a module but nothing in a running procedure opens it any more.  `app` is an engine App
    (procmods_engine.ProcModsMixin).

    A procedure that is verified on hardware and locked (verified.py) keeps the control, but disabled, with a green 'VERIFIED ON HARDWARE -
    LOCKED' chip and the reason as its tooltip.  Running is not affected."""

    LABEL = 'Edit point'
    CHIP = 'VERIFIED ON HARDWARE - LOCKED'

    def __init__(self, app, shell, lock):
        self.app, self.shell, self.lock = app, shell, lock
        self.window = None
        self.locked_reason = ''
        self.button = shell.add_action(self.LABEL, self.open, short='Edit')
        lock.on_change(lambda _s: self._safe_refresh())
        self.refresh()

    def _safe_refresh(self):
        try:
            self.refresh()
        except RuntimeError:
            pass

    def count(self) -> int:
        st = self.app.pm_state
        return len(st.oset.active()) if st is not None and st.oset else 0

    def verified_reason(self) -> str:
        """Why the procedure cannot be edited because it is verified and locked ('' = it can).  Looked at afresh every time."""
        st = self.app.pm_state
        return st.lock_reason() if st is not None else ''

    def refresh(self):
        """Header chips: MODIFIED (n) = what the running procedure uses, DEVELOPER MODE while unlocked, VERIFIED ... while locked by verification."""
        self.shell.set_modified(self.count())
        self.shell.set_devmode(self.lock.unlocked)
        self.sync_verified()

    def sync_verified(self):
        self.locked_reason = why = self.verified_reason()
        setter = getattr(self.shell, 'set_verified', None)
        if setter is not None:
            setter(self.CHIP if why else '')
        try:
            common.set_button_state(self.button, not why)
            common.set_tooltip(self.button, why)
        except (AttributeError, RuntimeError):
            pass

    def open(self):
        why = self.verified_reason()
        parent = getattr(self.shell, 'root', None)
        if why:
            self.sync_verified()
            common.show_info(parent, 'Procedure is locked', why)
            return None
        from qtui.screens import procmods_point_editor
        pid = procmods_point_editor.selected_point(self.app)
        if pid is None:
            common.show_info(parent, 'Edit point', 'Select a test point in the list first (or right-click a point and choose Edit).')
            return None
        self.window = procmods_point_editor.open_point_window(self.app, pid, lock=self.lock, parent=parent)
        return self.window


def attach_live(app, shell, lock: M.DevLock | None = None) -> LiveHook:
    """Add 'Edit point' to an engine's window (ProcModsMixin.pm_live_attach calls this once the shell is built)."""
    return LiveHook(app, shell, lock or shared_lock())


# ------------------------------------------------------------------------------------------------------------ Manager window
def open_manager_changes(parent, model_name, store=None, lock=None, registries=None, proc_key=''):
    """The Manager's 'Procedure changes...' window: the saved model-wide / asset overrides for a model (Changes tab only: the
    command and point lists need a running engine).  Read-only until unlocked; it cannot edit a running procedure."""
    ctx = M.Context(title=model_name, model=model_name, store=store, registries=registries or {}, proc_key=proc_key or '')
    return open_modify_window(parent, ctx, lock or shared_lock())
