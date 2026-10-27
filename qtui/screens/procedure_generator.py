"""The 'Procedure Generator' tab of the Manager (Qt): build a procedure from an uploaded manual, with a person checking every number.

    ProcedureGeneratorPanel(parent, status=None, on_saved=None, store=None)

Left: the list of projects.  Right: the guided project (name and instruments; the MODE cards; the requirements checklist with drop / browse upload slots and the list
of uploads; the tables and review step; the Build button, which says exactly what is missing; the DRAFT / approval strip of a built procedure).  The table-review
workspace (page images, candidate rows) is qtui/screens/procedure_generator_review.py.

All rules live in procedure_generator.py (requirements, Build gate, validation), procedure_generator_ai.py (page images, API call), procedure_generator_build.py
(rows -> procedure) and generated_draft.py (DRAFT marking, approval).  This file shows them.  Dialogs go through the module functions below (a test replaces them)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import generated_draft as gd
import procedure_generator as pg
import procedure_generator_ai as ai
import procedure_generator_build as bd

from .. import theme
from ..theme import M
from ..widgets import Badge, Banner, Card, DangerButton, GhostButton, MessageDialog, ModalDialog, PrimaryButton, SecondaryButton, SectionHeader, follow_tokens, label, rule
from .procedure_generator_review import ReviewPage

STANDARD_BEST, STANDARD_NONE = '', '__none__'
ROLE_LABEL = {pg.ROLE_SPEC: 'Spec sheet / manual', pg.ROLE_PROG: 'Programming manual', pg.ROLE_PHOTO: 'Hook-up photo'}


# ---------------------------------------------------------------------------------------------------------------------------------- dialogs (a test replaces these)
def _info(parent, title, text, detail=''):
    MessageDialog(parent, 'info', title, text, detail=detail).run()


def _warn(parent, title, text, detail=''):
    MessageDialog(parent, 'warning', title, text, detail=detail).run()


def _error(parent, title, text):
    MessageDialog(parent, 'error', title, text).run()


def _ask(parent, title, text, yes='Yes', no='Cancel') -> bool:
    return MessageDialog(parent, 'question', title, text, buttons=((no, 'no', None), (yes, 'yes', 'primary')), cancel_key='no').run() == 'yes'


def _choose_files(parent, title, exts) -> list:
    pattern = ' '.join('*' + e for e in exts)
    paths, _f = QFileDialog.getOpenFileNames(parent, title, '', f'Files ({pattern})')
    return list(paths)


def _ask_approval(parent, name, who, unverified, sources=None) -> tuple | None:
    """(who, note) or None."""
    dlg = ModalDialog(parent, 'Approve this procedure', subtitle=f'"{name}" is a draft generated from a manual.', width=M.dialog_w + 80)
    dlg.add_text('Approving removes the DRAFT marking from later runs and reports. Only approve it after the limits and settings have been checked against the manual '
                 '(and, for an automated one, run on the bench). Who approved and when is recorded and cannot be changed.')
    if sources:
        dlg.body.addWidget(label('Built from (file and SHA-256):', 'section'))
        src = QPlainTextEdit('\n'.join(f'{n}   {h}' for n, h in sorted(sources.items())))
        src.setReadOnly(True)
        src.setMaximumHeight(M.row_h * 3)
        dlg.body.addWidget(src)
    if unverified:
        box = QPlainTextEdit('\n'.join(unverified))
        box.setReadOnly(True)
        box.setMinimumHeight(M.row_h * 4)
        dlg.body.addWidget(label(f'Still unverified ({len(unverified)}):', 'section'))
        dlg.body.addWidget(box)
    name_edit, note_edit = QLineEdit(who), QLineEdit()
    note_edit.setPlaceholderText('Note (optional)')
    dlg.body.addWidget(label('Your name *', 'section'))
    dlg.body.addWidget(name_edit)
    dlg.body.addWidget(note_edit)
    err = label('', 'hint')
    dlg.body.addWidget(err)
    out = {}

    def ok():
        if len(name_edit.text().strip()) < gd.MIN_WHO:
            err.setText('Type the name of the person approving.')
            return False
        out['v'] = (name_edit.text().strip(), note_edit.text().strip())
        return True
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('Approve', role='primary', result='approve', default=True, callback=ok)
    dlg.run()
    return out.get('v')


def run_approve(parent, uid, name, registry=None):
    """The owner's approval of a generated procedure: the SAME dialog from the Procedure Generator tab and from the Manager list.  Returns the new gd.State, or None."""
    st = gd.state(uid, registry)
    if not st.generated:
        _error(parent, 'Approve', 'This is not a generated procedure.')
        return None
    got = _ask_approval(parent, name or st.title or uid, gd.default_who(), st.unverified, st.sources)
    if not got:
        return None
    try:
        return gd.approve(uid, got[0], got[1], db=registry)
    except gd.ApprovalError as exc:
        _error(parent, 'Approve', str(exc))
        return None


def run_draft_again(parent, uid, name, registry=None):
    st = gd.state(uid, registry)
    if not st.generated:
        _error(parent, 'Mark as draft', 'This is not a generated procedure.')
        return None
    if not _ask(parent, 'Mark as draft again', f'Put the DRAFT marking back on "{name or st.title or uid}"? Later runs will ask for confirmation and every report page will carry the banner. This is recorded.',
                yes='Mark as draft', no='Cancel'):
        return None
    try:
        return gd.mark_draft_again(uid, gd.default_who() or 'owner', 'marked as draft again by the owner', db=registry)
    except gd.ApprovalError as exc:
        _error(parent, 'Mark as draft', str(exc))
        return None


class SettingsDialog(ModalDialog):
    """API key and model name.  The key is typed into a password field, is never shown again and is stored per user with restricted permissions."""

    def __init__(self, parent=None):
        super().__init__(parent, 'Procedure Generator settings', subtitle='The Claude API reads the page images of a manual into candidate rows.', width=M.dialog_w + 100)
        self.status = label('', 'hint', wrap=True)
        self.body.addWidget(self.status)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText('Paste an API key here to save it (it is not shown again)')
        self.body.addWidget(label('API key', 'section'))
        self.body.addWidget(self.key_edit)
        self.model_edit = QLineEdit(ai.load_settings()['model'])
        self.body.addWidget(label('Model name', 'section'))
        self.body.addWidget(self.model_edit)
        self.body.addWidget(label(f'Page images are drawn with: {ai.renderer_name() or "nothing installed (install pypdfium2 and pillow)"}.  '
                                  'Only page images are sent to the API; the key is never written to a log or to a project file.', 'hint', wrap=True))
        self.remove_btn = self.add_button('Remove saved key', result='remove', close=False, callback=self.remove_key)
        self.add_button('Close', cancel=True)
        self.add_button('Save', role='primary', result='save', default=True, callback=self.save)
        self.refresh_status()

    def refresh_status(self):
        src = ai.key_source()
        self.status.setText({'env': 'A key is set in the ANTHROPIC_API_KEY environment variable (it is used first).',
                             'file': 'A key is saved for your user account.', '': 'No API key is set. Without one you can still type the rows by hand.'}[src])
        self.remove_btn.setEnabled(src == 'file')

    def save(self):
        try:
            if self.key_edit.text().strip():
                warning = ai.save_key(self.key_edit.text())
                self.key_edit.clear()
                if warning:
                    _warn(self, 'API key saved', warning)
            if self.model_edit.text().strip():
                ai.save_settings(model=self.model_edit.text())
        except (ValueError, OSError) as exc:
            _error(self, 'Settings', ai.scrub(str(exc)))
            return False
        return True

    def remove_key(self):
        ai.remove_key()
        self.refresh_status()
        return False


def _clear(layout):
    """Remove every widget of a layout now (hidden and unparented first: a widget that is only deleteLater()'d is still painted until the event loop runs)."""
    while layout.count():
        w = layout.takeAt(0).widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


# ---------------------------------------------------------------------------------------------------------------------------------- widgets
class DropSlot(QFrame):
    """A dashed drop target that is also a Browse button.  filesDropped(list of path text) comes from a drop or from the chooser."""
    filesDropped = Signal(list)

    def __init__(self, title: str, hint: str, exts: tuple, parent=None):
        super().__init__(parent)
        self.exts = exts
        self.setAcceptDrops(True)
        self.setObjectName('dropslot')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(M.md, M.sm, M.md, M.sm)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = label(title, 'section')
        self.hint_label = label(hint, 'hint', wrap=True)
        col.addWidget(self.title_label)
        col.addWidget(self.hint_label)
        lay.addLayout(col, 1)
        self.state = Badge('Needed', 'warn', small=True)
        lay.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)
        self.browse = SecondaryButton('Browse...', on_click=self._browse)
        lay.addWidget(self.browse, 0, Qt.AlignmentFlag.AlignVCenter)
        self._hot = False
        follow_tokens(self, self._qss)

    def _qss(self) -> str:
        t = theme.tokens()
        edge = t['primary'] if self._hot else t['border_strong']
        return f'QFrame#dropslot {{ border: 2px dashed {edge}; border-radius: {M.radius_lg}px; background: {t["select"] if self._hot else "transparent"}; }}'

    def set_met(self, met: bool, optional=False):
        self.state.set('Done' if met else ('Optional' if optional else 'Needed'), 'good' if met else ('neutral' if optional else 'warn'))

    def _browse(self):
        paths = _choose_files(self, self.title_label.text(), self.exts)
        if paths:
            self.filesDropped.emit(paths)

    def _paths(self, ev):
        return [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self._hot = True
            follow_tokens(self, self._qss)

    def dragLeaveEvent(self, ev):
        self._hot = False
        follow_tokens(self, self._qss)

    def dropEvent(self, ev):
        self._hot = False
        follow_tokens(self, self._qss)
        paths = self._paths(ev)
        if paths:
            ev.acceptProposedAction()
            self.filesDropped.emit(paths)


class ModeCard(QFrame):
    """One of the three mode choices.  Click anywhere (or Space / Enter when focused) to choose it."""
    clicked = Signal(str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        info = pg.MODE_INFO[mode]
        self.setObjectName('modecard')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(info['title'])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(M.lg, M.md, M.lg, M.md)
        lay.setSpacing(M.xs + 2)
        self.title_label = label(info['title'], 'h2', wrap=True)
        lay.addWidget(self.title_label)
        lay.addWidget(label(info['tag'], 'sub', wrap=True))
        lay.addWidget(label(info['summary'], wrap=True))
        lay.addWidget(label('Needs', 'section'))
        for n in info['needs']:
            lay.addWidget(label('- ' + n, wrap=True))
        lay.addStretch(1)
        self.selected = False
        follow_tokens(self, self._qss)

    def _qss(self) -> str:
        t = theme.tokens()
        if self.selected:
            return f'QFrame#modecard {{ background: {t["select"]}; border: 2px solid {t["primary"]}; border-radius: {M.radius_lg}px; }}'
        return f'QFrame#modecard {{ background: {t["card"]}; border: 1px solid {t["border"]}; border-radius: {M.radius_lg}px; }} QFrame#modecard:hover {{ border-color: {t["primary"]}; }}'

    def set_selected(self, on: bool):
        self.selected = on
        follow_tokens(self, self._qss)

    def mousePressEvent(self, ev):
        self.setFocus()
        self.clicked.emit(self.mode)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit(self.mode)
        else:
            super().keyPressEvent(ev)


# ---------------------------------------------------------------------------------------------------------------------------------- the panel
class ProcedureGeneratorPanel(QWidget):
    def __init__(self, parent=None, status=None, on_saved=None, store: pg.Store | None = None, client_factory=None):
        super().__init__(parent)
        self.status = status
        self.on_saved = on_saved
        self.store = store or pg.Store()
        self.client_factory = client_factory
        self.p: pg.Project | None = None
        self._loading = False
        self.review: ReviewPage | None = None
        self.instrument_rows: list = []
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(M.lg)
        # ---- left: the projects
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(M.sm)
        left.setMinimumWidth(M.font_base * 17)
        left.setMaximumWidth(M.font_base * 24)
        ll.addWidget(label('Projects', 'h2'))
        self.new_btn = PrimaryButton('New project', on_click=self.new_project)
        ll.addWidget(self.new_btn)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._list_changed)
        ll.addWidget(self.list, 1)
        self.delete_btn = SecondaryButton('Delete project', on_click=self.delete_project)
        self.settings_btn = SecondaryButton('Settings (API key)...', on_click=self.open_settings)
        ll.addWidget(self.delete_btn)
        ll.addWidget(self.settings_btn)
        root.addWidget(left)
        root.addWidget(rule(vertical=True))
        # ---- right
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch(1)
        el.addWidget(label('Build a procedure from a manual', 'title'), 0, Qt.AlignmentFlag.AlignHCenter)
        el.addWidget(label('Upload the manufacturer\'s manual, choose the pages of the performance verification tables, check what Claude reads from them against the page, '
                           'and the program builds a procedure you can run. Create a project to start.', 'sub', wrap=True))
        el.addWidget(self.new_hint_button(), 0, Qt.AlignmentFlag.AlignHCenter)
        el.addStretch(2)
        self.stack.addWidget(self.empty)
        self.project_page = QWidget()
        self._build_project_page()
        self.stack.addWidget(self.project_page)
        self.reload_list()
        self.show_empty()

    def new_hint_button(self):
        b = PrimaryButton('New project', on_click=self.new_project)
        return b

    # ------------------------------------------------------------------ building the project page
    def _build_project_page(self):
        outer = QVBoxLayout(self.project_page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(M.md)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, M.md, 0)
        lay.setSpacing(M.lg)
        self.header = SectionHeader('', 'Create a procedure from a manual. A person checks every number before it is built.')
        self.status_badge = Badge('', 'neutral')
        self.header.add_trailing(self.status_badge)
        lay.addWidget(self.header)
        # 1. project
        c1 = Card('1. The project')
        form = QHBoxLayout()
        self.name_edit, self.make_edit, self.model_edit = QLineEdit(), QLineEdit(), QLineEdit()
        for edit, ph in ((self.name_edit, 'Project / procedure name'), (self.make_edit, 'Manufacturer'), (self.model_edit, 'Instrument model(s)')):
            edit.setPlaceholderText(ph)
            edit.editingFinished.connect(self._save_fields)
            form.addWidget(edit, 1)
        c1.add(label('Name, manufacturer and the model(s) the procedure is for', 'hint'))
        c1.body.addLayout(form)
        lay.addWidget(c1)
        # 2. mode
        c2 = Card('2. How much is automated?')
        row = QHBoxLayout()
        row.setSpacing(M.md)
        self.mode_cards = {}
        for m in pg.MODES:
            card = ModeCard(m)
            card.clicked.connect(self.set_mode)
            self.mode_cards[m] = card
            row.addWidget(card, 1)
        c2.body.addLayout(row)
        lay.addWidget(c2)
        # 3. requirements and uploads
        self.c3 = Card('3. What this mode needs')
        self.req_box = QVBoxLayout()
        self.req_box.setSpacing(M.xs)
        self.c3.body.addLayout(self.req_box)
        self.c3.add_rule()
        self.spec_slot = DropSlot('Spec sheet or manual (PDF)', 'Drop the manufacturer\'s manual or spec sheet here, or browse. At least one is required.', pg.SPEC_EXT)
        self.spec_slot.filesDropped.connect(lambda paths: self.add_files(pg.ROLE_SPEC, paths))
        self.c3.add(self.spec_slot)
        self.instr_card_box = QVBoxLayout()
        self.instr_card_box.setSpacing(M.sm)
        self.c3.body.addLayout(self.instr_card_box)
        self.photo_slot = DropSlot('Hook-up photo (PNG or JPG)', 'A photo of the hook-up. Required for two-way automation; optional otherwise. It is stored with the project '
                                   'and offered as the reference image; no diagram is drawn for you.', pg.PHOTO_EXT)
        self.photo_slot.filesDropped.connect(lambda paths: self.add_files(pg.ROLE_PHOTO, paths))
        self.c3.add(self.photo_slot)
        self.c3.add(label('Uploaded files (copied into the project, never changed)', 'section'))
        self.files_table = QTableWidget(0, 6)
        self.files_table.setHorizontalHeaderLabels(['File', 'Used for', 'Pages', 'Size', 'SHA-256', ''])
        self.files_table.verticalHeader().hide()
        self.files_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.horizontalHeader().setStretchLastSection(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.c3.add(self.files_table)
        lay.addWidget(self.c3)
        # 4. tables
        self.c4 = Card('4. Tables and review')
        self.tables_text = label('', wrap=True)
        self.c4.add(self.tables_text)
        brow = QHBoxLayout()
        self.review_btn = PrimaryButton('Choose pages and review the rows...', on_click=self.open_review)
        brow.addWidget(self.review_btn)
        brow.addStretch(1)
        self.c4.body.addLayout(brow)
        lay.addWidget(self.c4)
        # 5. the built procedure
        self.c5 = Card('5. The built procedure')
        self.built_text = label('', wrap=True)
        self.c5.add(self.built_text)
        srow = QHBoxLayout()
        self.standard_label = label('Standard for the uncertainty of typed readings', 'kvkey')
        self.standard_box = QComboBox()
        self.standard_box.currentIndexChanged.connect(self._standard_changed)
        srow.addWidget(self.standard_label)
        srow.addWidget(self.standard_box, 1)
        self.c5.body.addLayout(srow)
        arow = QHBoxLayout()
        self.approve_btn = PrimaryButton('Approve (owner)...', on_click=self.approve)
        self.draft_btn = SecondaryButton('Mark as draft again...', on_click=self.mark_draft_again)
        arow.addWidget(self.approve_btn)
        arow.addWidget(self.draft_btn)
        arow.addStretch(1)
        self.c5.body.addLayout(arow)
        lay.addWidget(self.c5)
        lay.addStretch(1)
        outer.addWidget(self.scroll, 1)
        # ---- the Build bar
        bar = QFrame()
        bar.setProperty('surface', 'barbottom')
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(M.lg, M.sm, M.lg, M.sm)
        self.build_label = label('', wrap=True)
        bl.addWidget(self.build_label, 1)
        self.build_btn = PrimaryButton('Build procedure', on_click=self.build)
        bl.addWidget(self.build_btn)
        outer.addWidget(bar)
        self.notice = Banner('', 'info')
        self.notice.hide()
        outer.addWidget(self.notice)

    # ------------------------------------------------------------------ helpers
    def say(self, text):
        if self.status is not None:
            try:
                self.status.set(text) if hasattr(self.status, 'set') else self.status(text)
            except Exception:
                pass

    def notify(self, text, kind='info'):
        self.notice.set_kind({'bad': 'error'}.get(kind, kind))
        self.notice.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.set_text(text)
        self.notice.setVisible(bool(text))
        self.say(text)

    def save(self):
        if self.p is not None:
            self.store.save(self.p)

    def refresh(self):
        """Called when the tab is shown."""
        keep = self.p.id if self.p else ''
        self.reload_list(keep)

    # ------------------------------------------------------------------ the project list
    def reload_list(self, select=''):
        self._loading = True
        self.list.clear()
        for pid, name, mode, _upd in self.store.list():
            st = self._build_state(pid)
            it = QListWidgetItem(f'{name or "(unnamed project)"}\n{pg.MODE_INFO[mode]["title"] if mode in pg.MODE_INFO else "no mode chosen"}{st}')
            it.setData(Qt.ItemDataRole.UserRole, pid)
            self.list.addItem(it)
            if pid == select:
                self.list.setCurrentItem(it)
        self._loading = False
        self.delete_btn.setEnabled(self.list.count() > 0)

    def _build_state(self, pid) -> str:
        p = self.store.load(pid)
        if p and p.build.get('uid'):
            st = gd.state(p.build['uid'], self.store.registry)
            return '  |  built, ' + ('DRAFT' if st.draft else 'approved') if st.generated else '  |  built'
        return ''

    def _list_changed(self, cur, _prev):
        if self._loading:
            return
        if cur is None:
            self.show_empty()
        else:
            self.select_project(cur.data(Qt.ItemDataRole.UserRole))

    def show_empty(self):
        self.p = None
        self.stack.setCurrentWidget(self.empty)

    def new_project(self):
        p = self.store.create('', gd.default_who())
        self.reload_list(p.id)
        self.select_project(p.id)
        self.name_edit.setFocus()
        return p

    def delete_project(self):
        if self.p is None:
            return
        if not _ask(self, 'Delete project', f'Delete the project "{self.p.name or "(unnamed)"}"? Its files stay on disk; a procedure already built from it stays in the library.', yes='Delete', no='Cancel'):
            return
        self.store.delete(self.p.id)
        self.p = None
        self.reload_list()
        self.show_empty()

    def select_project(self, pid):
        p = self.store.load(pid)
        if p is None:
            self.show_empty()
            return
        self.p = p
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == pid and self.list.currentRow() != i:
                self._loading = True
                self.list.setCurrentRow(i)
                self._loading = False
        self.stack.setCurrentWidget(self.project_page)
        self.refresh_project()

    def open_settings(self):
        SettingsDialog(self).run()
        self.refresh_project()

    # ------------------------------------------------------------------ the project page
    def _save_fields(self):
        if self.p is None or self._loading:
            return
        self.p.name, self.p.make, self.p.model = self.name_edit.text().strip(), self.make_edit.text().strip(), self.model_edit.text().strip()
        self.save()
        self.reload_list(self.p.id)
        self.refresh_requirements()

    def set_mode(self, mode):
        if self.p is None or mode not in pg.MODES:
            return
        self.p.mode = mode
        self.save()
        self.reload_list(self.p.id)
        self.refresh_project()

    def refresh_project(self):
        p = self.p
        if p is None:
            return
        self._loading = True
        self.header.title_label.setText(p.name or 'New project')
        for edit, v in ((self.name_edit, p.name), (self.make_edit, p.make), (self.model_edit, p.model)):
            if edit.text() != v:
                edit.setText(v)
        for m, card in self.mode_cards.items():
            card.set_selected(p.mode == m)
        self._loading = False
        self.refresh_instruments()
        self.refresh_requirements()
        self.refresh_files()
        self.refresh_tables()
        self.refresh_built()

    def refresh_requirements(self):
        p = self.p
        _clear(self.req_box)
        self.requirement_rows = []
        for r in pg.requirements(p):
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            badge = Badge('Done' if r.met else 'Needed', 'good' if r.met else 'warn', small=True)
            hl.addWidget(badge)
            hl.addWidget(label(r.label), 1)
            self.req_box.addWidget(row)
            self.requirement_rows.append((r, badge))
        has_mode = p.mode in pg.MODES
        self.spec_slot.setVisible(has_mode)
        self.photo_slot.setVisible(has_mode)
        self.spec_slot.set_met(bool(p.files_of(pg.ROLE_SPEC)))
        self.photo_slot.set_met(bool(p.files_of(pg.ROLE_PHOTO)), optional=p.mode != pg.TWOWAY)
        g = pg.gate(p)
        self.build_btn.setEnabled(g.can_click)
        self.build_label.setText(g.text)
        self.build_btn.setText('Build procedure' if g.stage != 'coming' else 'Build (two-way is coming)')
        self.build_btn.setToolTip(g.text)
        self.c4.setVisible(has_mode and p.mode != pg.TWOWAY)
        self.refresh_tables()

    def refresh_instruments(self):
        p = self.p
        _clear(self.instr_card_box)
        self.instrument_rows = []
        if p.mode != pg.TWOWAY:
            return
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(label('Instruments used in the procedure (the unit under test and every standard)', 'section'), 1)
        add = SecondaryButton('Add instrument', on_click=self.add_instrument)
        hl.addWidget(add)
        self.add_instrument_btn = add
        self.instr_card_box.addWidget(head)
        for ins in p.instruments:
            box = QFrame()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            line = QHBoxLayout()
            name = QLineEdit(ins.name)
            name.setPlaceholderText('Make and model, e.g. Fluke 5522A')
            name.editingFinished.connect(lambda i=ins, e=name: self._rename_instrument(i.id, e.text()))
            role = QComboBox()
            role.addItems(['Unit under test', 'Standard'])
            role.setCurrentIndex(0 if ins.role == 'uut' else 1)
            role.currentIndexChanged.connect(lambda idx, i=ins: self._instrument_role(i.id, 'uut' if idx == 0 else 'standard'))
            rm = SecondaryButton('Remove', on_click=lambda _c=False, i=ins: self.remove_instrument(i.id))
            line.addWidget(name, 1)
            line.addWidget(role)
            line.addWidget(rm)
            bl.addLayout(line)
            slot = DropSlot(f'Programming manual (PDF) for {ins.name or "this instrument"}', 'The manufacturer\'s remote / SCPI programming manual for this instrument.', pg.SPEC_EXT)
            slot.filesDropped.connect(lambda paths, i=ins: self.add_files(pg.ROLE_PROG, paths, i.id))
            slot.set_met(any(f.instrument == ins.id for f in p.files_of(pg.ROLE_PROG)))
            bl.addWidget(slot)
            self.instr_card_box.addWidget(box)
            self.instrument_rows.append((ins, name, slot))

    def refresh_files(self):
        p = self.p
        t = self.files_table
        t.setRowCount(len(p.files))
        for i, f in enumerate(p.files):
            used = ROLE_LABEL[f.role] + (f' ({p.instrument(f.instrument).name})' if f.instrument and p.instrument(f.instrument) else '')
            cells = [f.original, used, str(f.pages or '?') if f.role != pg.ROLE_PHOTO else 'image', pg.human_size(f.size), f.sha256[:16] + '...']
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setToolTip(f.sha256 if c == 4 else f'{f.original}\nSHA-256 {f.sha256}')
                t.setItem(i, c, it)
            rm = SecondaryButton('Remove', on_click=lambda _c=False, fid=f.id: self.remove_file(fid))
            t.setCellWidget(i, 5, rm)
        t.resizeColumnsToContents()
        t.setColumnWidth(5, SecondaryButton('Remove').sizeHint().width() + M.md)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.setFixedHeight(M.header_h + max(1, len(p.files)) * M.row_h + 6)
        t.setVisible(bool(p.files))

    def refresh_tables(self):
        p = self.p
        if p is None:
            return
        if p.mode == pg.TWOWAY:
            return
        sel = '; '.join(f'{p.file(fid).original} pages {a}-{b}' for fid, (a, b) in p.pages.items() if p.file(fid)) or 'no pages chosen yet'
        counts = {s: sum(1 for r in p.rows if r.status == s) for s in pg.STATUSES}
        un = pg.unchecked_pages(p)
        self.tables_text.setText(f'Table pages: {sel}.  Rows: {len(p.rows)} ({counts[pg.STATUS_ACCEPTED] + counts[pg.STATUS_EDITED]} accepted or edited, {counts[pg.STATUS_REJECTED]} rejected, '
                                 f'{counts[pg.STATUS_CANDIDATE]} undecided).  Pages still to confirm against the image: {len(un)}.')
        self.review_btn.setEnabled(bool(p.files_of(pg.ROLE_SPEC)))

    def refresh_built(self):
        p = self.p
        built = bool(p.build.get('uid'))
        self.c5.setVisible(built)
        if not built:
            self.status_badge.set('Not built', 'neutral')
            return
        st = gd.state(p.build['uid'], self.store.registry)
        if st.generated:
            self.status_badge.set(gd.DRAFT_TEXT if st.draft else f'Approved by {st.approved_by}', 'bad' if st.draft else 'good')
        self.built_text.setText(f'Built as "{p.build.get("title", p.name)}" version {p.build.get("version")} on {p.build.get("at", "")[:10]} '
                                f'({p.build.get("points", 0)} points; listed in the Manager under '
                                f'{"Manual Calibrations" if p.build.get("kind") == "manual" else "Automated Calibrations"}).  {st.text}')
        self.approve_btn.setEnabled(st.generated and st.draft)
        self.draft_btn.setEnabled(st.generated and not st.draft)
        manual = p.mode == pg.MANUAL
        self.standard_label.setVisible(manual)
        self.standard_box.setVisible(manual)
        if manual:
            self._loading = True
            self.standard_box.clear()
            self.standard_box.addItem('Best fit for this sheet (default)', STANDARD_BEST)
            self.standard_box.addItem('None: waive the uncertainty', STANDARD_NONE)
            try:
                import specmanager
                for r in specmanager.standards():
                    self.standard_box.addItem(r['model'], r['model'])
            except Exception:
                pass
            self.standard_box.setCurrentIndex(max(0, self.standard_box.findData(p.standard)))
            self._loading = False

    def _standard_changed(self, *_):
        if self._loading or self.p is None:
            return
        self.p.standard = self.standard_box.currentData() or ''
        self.save()

    # ------------------------------------------------------------------ uploads
    def add_files(self, role, paths, instrument=''):
        if self.p is None:
            return []
        added, problems = [], []
        for path in paths:
            try:
                added.append(self.store.add_file(self.p, path, role, instrument))
            except pg.UploadError as exc:
                problems.append(str(exc))
        self.refresh_project()
        if problems:
            self.notify('Not added: ' + '; '.join(problems), 'warn')
        elif added:
            self.notify(f'Added {len(added)} file(s): ' + ', '.join(f.original for f in added) + '.')
        return added

    def remove_file(self, fid):
        if self.p is None:
            return False
        f = self.p.file(fid)
        if f is None:
            return False
        if not _ask(self, 'Remove file', f'Remove {f.original} from the project? Your original file is not touched.', yes='Remove', no='Cancel'):
            return False
        try:
            self.store.remove_file(self.p, fid)
        except pg.UploadError as exc:
            self.notify(str(exc), 'warn')
            return False
        self.refresh_project()
        return True

    def add_instrument(self, name='', role=None):
        if self.p is None:
            return None
        ins = pg.Instrument(f'i{len(self.p.instruments) + 1}x{len(self.p.files) + 1}', name, role or ('uut' if not self.p.instruments else 'standard'))
        while any(i.id == ins.id for i in self.p.instruments):
            ins.id += 'x'
        self.p.instruments.append(ins)
        self.save()
        self.refresh_project()
        return ins

    def _rename_instrument(self, iid, text):
        ins = self.p.instrument(iid) if self.p else None
        if ins is not None and ins.name != text.strip():
            ins.name = text.strip()
            self.save()
            self.refresh_requirements()

    def _instrument_role(self, iid, role):
        ins = self.p.instrument(iid) if self.p else None
        if ins is not None:
            ins.role = role
            self.save()

    def remove_instrument(self, iid):
        if self.p is None or self.p.instrument(iid) is None:
            return
        for f in [f for f in self.p.files if f.instrument == iid]:
            try:
                self.store.remove_file(self.p, f.id)
            except pg.UploadError:
                pass
        self.p.instruments = [i for i in self.p.instruments if i.id != iid]
        self.save()
        self.refresh_project()

    # ------------------------------------------------------------------ review
    def open_review(self):
        if self.p is None or not self.p.files_of(pg.ROLE_SPEC):
            return
        if self.review is None:
            self.review = ReviewPage(self.store, self.p, client_factory=self.client_factory)
            self.review.backRequested.connect(self.close_review)
            self.review.changed.connect(self._review_changed)
            self.stack.addWidget(self.review)
        else:
            self.review.set_project(self.p)
        self.stack.setCurrentWidget(self.review)
        self.review.refresh()

    def close_review(self):
        self.stack.setCurrentWidget(self.project_page)
        self.refresh_project()

    def _review_changed(self):
        self.refresh_tables()
        self.refresh_requirements()

    # ------------------------------------------------------------------ build and approval
    def build(self):
        p = self.p
        if p is None:
            return None
        g = pg.gate(p)
        if g.stage == 'coming':
            self.save()
            _info(self, 'Two-way generation is coming', pg.TWOWAY_COMING)
            self.notify(pg.TWOWAY_COMING)
            return bd.BuildResult(coming=True, message=pg.TWOWAY_COMING, mode=p.mode)
        if not g.can_click:
            self.notify(g.text, 'warn')
            return None
        std = None if p.standard == STANDARD_BEST else ('' if p.standard == STANDARD_NONE else p.standard)
        res = bd.build(p, self.store, gd.default_who() or 'unknown', standard=std, registry=self.store.registry)
        self.refresh_project()
        self.reload_list(p.id)
        if not res.ok:
            _warn(self, 'The procedure was not built', res.message, detail='\n'.join(res.problems))
            return res
        lines = list(res.unverified) + [f'NO UNCERTAINTY: {x}' for x in res.uncertainty_missing]
        _info(self, 'Procedure built (DRAFT)', res.message + ('\n\nNOT VERIFIED (kept with the procedure):' if lines else ''), detail='\n'.join(lines))
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        self.notify(res.message)
        return res

    def approve(self):
        p = self.p
        if p is None or not p.build.get('uid'):
            return None
        new = run_approve(self, p.build['uid'], p.name, self.store.registry)
        if new is None:
            return None
        self.refresh_project()
        self.reload_list(p.id)
        if self.on_saved:
            self.on_saved()
        self.notify(f'Approved by {new.approved_by}. Later runs and reports no longer carry the draft marking.')
        return new

    def mark_draft_again(self):
        p = self.p
        if p is None or not p.build.get('uid'):
            return None
        new = run_draft_again(self, p.build['uid'], p.name, self.store.registry)
        if new is None:
            return None
        self.refresh_project()
        self.reload_list(p.id)
        if self.on_saved:
            self.on_saved()
        return new
