"""Qt twin of procmods_point_ui.py: the window of the per-point editor (thin: every decision lives in procmods_point_model.py, which is tested without a
toolkit).

    from qtui.screens import procmods_point_editor
    procmods_point_editor.attach_tree_menu(app, tree)        # right-click a test point -> Edit        (ProcModsMixin.pm_bind_tree calls this)
    procmods_point_editor.open_point_window(app, pid)        # the small window for one point
    procmods_point_editor.selected_point(app)                # the point selected in any of the app's lists (None when nothing is)

`tree` is a qtui.table.DataTable (preferred; the id handed to `resolver(iid)` is the row's `row_key`, which is the point id in every engine's point list) or any
other QAbstractItemView (QTreeWidget / QTableWidget: the item's Qt.UserRole data, else its row number as text).  The options of the window are the Tk ones:
commands in send order, 'Use for this point' / 'Restore default', 'Add a command line' (before / after, read-back, expected reply), the developer-mode point
definition fields with their 'Restore default' buttons, scope (this run / this instrument / all of this model), 'Measure this point again', the audit-trail
acknowledgement, Apply / Cancel changes / Close.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QMenu, QPushButton, QRadioButton,
                               QScrollArea, QSplitter, QTreeWidget, QVBoxLayout, QWidget)

import procmods as pm
import procmods_point_model as PM
import procmods_ui_model as M
from qtui.screens import common
from qtui.screens import procmods_editor as UI
from qtui.screens._share import ShareWidth
from qtui.table import Column, DataTable
from qtui.theme import M as SP
from qtui.widgets import Badge, label

POLL_MS = 1000
DEFAULT_SIZE = (980, 960)                      # device-independent px; clamped to the screen
MIN_SIZE = (720, 560)
_open = {}                                    # (id(app), str(pid)) -> window, so a second Edit on the same point raises the first


# ------------------------------------------------------------------------------------------------------------ the right-click menu
def _iid_of_index(tree, index):
    """The id the engine's resolver understands for the row at `index` of `tree`."""
    if not index.isValid():
        return None
    if isinstance(tree, DataTable):
        row = tree.row_of(index)
        return None if row is None else tree.row_key(row)
    if isinstance(tree, QTreeWidget):
        item = tree.itemFromIndex(index)
        data = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return data if data is not None else str(index.row())
    data = index.sibling(index.row(), 0).data(Qt.ItemDataRole.UserRole)
    return data if data is not None else str(index.row())


def _selected_iid(tree):
    if isinstance(tree, DataTable):
        keys = tree.selected_keys()
        return keys[0] if keys else None
    sm = tree.selectionModel()
    rows = sm.selectedRows() if sm is not None else []
    return _iid_of_index(tree, rows[0]) if rows else None


def _select_iid(tree, iid):
    if isinstance(tree, DataTable):
        for r in tree.visible_rows():
            if tree.row_key(r) == iid:
                tree.select_rows([r])
                return


class TreeMenu:
    """What attach_tree_menu returns: `menu_for(pid)` builds the QMenu (Edit [+ the reason it is disabled] + the engine's own entries); the right-click
    handler pops it up.  Kept as an object so a test can read the entries without a modal loop."""

    def __init__(self, app, tree, resolver, lock):
        self.app, self.tree, self.resolve, self.lock = app, tree, resolver, lock
        self.menu = None
        self.pid = None
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        if isinstance(tree, DataTable):                       # the table's own copy menu is folded into this one
            try:
                tree.customContextMenuRequested.disconnect(tree._context_menu)
            except (RuntimeError, TypeError):
                pass
        tree.customContextMenuRequested.connect(self.popup)

    def menu_for(self, pid):
        app = self.app
        menu = QMenu(self.tree)
        enabled, why = PM.menu_state(app, pid)
        act = menu.addAction('Edit')
        act.setEnabled(bool(enabled))
        act.triggered.connect(lambda _c=False, pid=pid: open_point_window(app, pid, lock=self.lock))
        if not enabled:
            menu.addAction(why[:90] + ('...' if len(why) > 90 else '')).setEnabled(False)
        extras = getattr(app, 'tree_menu_extras', None)         # an engine's own entries (manual_override: 'Enter reading manually'); none for every other procedure
        if extras is not None:
            try:
                for text, command, ok, reason in extras(pid):
                    menu.addSeparator()
                    a = menu.addAction(text)
                    a.setEnabled(bool(ok))
                    a.triggered.connect(lambda _c=False, c=command: c())
                    if not ok and reason:
                        menu.addAction(reason[:90] + ('...' if len(reason) > 90 else '')).setEnabled(False)
            except Exception:
                pass
        run = PM.run_from_entry(app)                            # 'Run from here' = the Rerun From Selected button, for every procedure that has one
        if run is not None:
            menu.addSeparator()
            a = menu.addAction(run[0])
            a.setEnabled(bool(run[2]))
            a.triggered.connect(lambda _c=False, c=run[1]: c())
            if not run[2] and run[3]:
                menu.addAction(run[3]).setEnabled(False)
        if isinstance(self.tree, DataTable) and self.tree.selected_count():
            menu.addSeparator()
            menu.addAction('Copy').triggered.connect(lambda _c=False: self.tree.copy_selection())
        return menu

    def popup(self, pos: QPoint):
        iid = _iid_of_index(self.tree, self.tree.indexAt(pos))
        if iid is None:
            return None
        _select_iid(self.tree, iid)
        pid = self.resolve(iid)
        self.pid = pid
        self.menu = self.menu_for(pid)
        self.exec_menu(self.menu, self.tree.viewport().mapToGlobal(pos))
        return self.menu

    @staticmethod
    def exec_menu(menu, global_pos):
        """The modal pop-up (one place, so a test can answer it without a modal loop)."""
        menu.exec(global_pos)


def attach_tree_menu(app, tree, resolver=None, lock=None):
    """Right-click a row of `tree` -> 'Edit'.  `resolver(iid)` gives the point id (default: the row's id, which is the point id in every engine's point
    list).  The item is disabled, with the reason shown under it, on a verified / locked procedure and while the point is being measured.  Returns the TreeMenu."""
    res = resolver or (lambda iid: iid)
    tm = TreeMenu(app, tree, res, lock)
    app.__dict__.setdefault('_pm_tree_menus', []).append((tree, res))
    return tm


def selected_point(app):
    """The id of the point selected in any of the app's point lists (None if nothing is)."""
    for tree, res in app.__dict__.get('_pm_tree_menus', []):
        try:
            iid = _selected_iid(tree)
        except RuntimeError:                                      # the list's widget is gone
            continue
        if iid is not None:
            return res(iid)
    return None


def open_point_window(app, pid, lock=None, parent=None):
    """Open (or raise) the window for point `pid`.  Says why, instead of opening, when the point cannot be edited at all."""
    lock = lock or UI.shared_lock()
    root = parent or getattr(app, 'root', None)
    ok, why = PM.menu_state(app, pid)
    if not ok:
        common.show_info(root, 'Edit point', why)
        return None
    key = (id(app), str(pid))
    win = _open.get(key)
    if win is not None and common.alive(win):
        win.raise_()
        win.activateWindow()
        return win
    model = PM.PointEditModel(app, pid, lock)
    win = PointWindow(root, app, model)
    _open[key] = win
    win.show()
    return win


# ------------------------------------------------------------------------------------------------------------ the window
class PointWindow(QWidget):
    COLUMNS = (('seq', '#', 44), ('inst', 'Instrument', 100), ('cmd', 'Command for this point', 290), ('rb', 'Read-back', 120),
               ('risk', 'Risk', 90), ('status', 'Status', 120), ('chg', 'Changed', 80))

    def __init__(self, parent, app, model: PM.PointEditModel):
        super().__init__(common.qparent(parent), Qt.WindowType.Window)
        self.setObjectName('root')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.app, self.model, self.lock = app, model, model.lock
        self.setWindowTitle(model.title + (' [DEMO]' if model.demo else ''))
        self._selected = None
        self._busy = False
        self._closing = False
        self.fvars, self.fmsg, self.fentries, self.frestore = {}, {}, {}, {}

        root = QVBoxLayout(self)
        root.setContentsMargins(SP.lg, SP.md, SP.lg, SP.sm)
        root.setSpacing(SP.sm)

        # ---- header
        head = QHBoxLayout()
        self.banner_lbl = label('', wrap=True)
        head.addWidget(self.banner_lbl, 1)
        if model.demo:
            self.chip_demo = Badge('DEMO', 'warn')
            head.addWidget(self.chip_demo)
        self.chip_dev = Badge('DEVELOPER MODE', 'warn')
        head.addWidget(self.chip_dev)
        self.btn_dev = QPushButton('Turn on developer mode...')
        self.btn_dev.clicked.connect(self.toggle_dev)
        head.addWidget(self.btn_dev)
        root.addLayout(head)
        self.info_lbl = common.hint('')
        root.addWidget(self.info_lbl)

        # ---- the command table (bounded: it scrolls, a point can have a few hundred commands) over the scrolling details
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 2, 0, 2)
        tl.setSpacing(2)
        tl.addWidget(label('Instrument commands for this point, in the order they are sent', 'section'))
        self.plan_lbl = common.hint('')
        tl.addWidget(self.plan_lbl)
        cols = [Column('seq', '#', width=44, getter=lambda r: r.seq, tone=self._tone),
                Column('inst', 'Instrument', width=100, getter=lambda r: r.label, tone=self._tone),
                Column('cmd', 'Command for this point', width=290, stretch=True, mono=True, tone=self._tone,
                       getter=lambda r: r.shown_wire + ('   (not saved)' if r.staged or r.pending else '')),
                Column('rb', 'Read-back', width=120, mono=True, getter=lambda r: r.readback_wire, tone=self._tone),
                Column('risk', 'Risk', width=130, getter=lambda r: r.risk_text, tone=self._tone),
                Column('status', 'Status', width=120, getter=lambda r: r.status_text, tone=self._tone),
                Column('chg', 'Changed', width=80, getter=lambda r: 'changed' if r.changed else '', tone=self._tone)]
        self.tree = DataTable(cols, [], row_tone=lambda r: 'warn' if r.changed else None, row_key=lambda r: str(r.seq), multi=False, tone_style='text',
                              empty_text='No commands')
        self.tree.setMinimumHeight(150)
        self._share = ShareWidth(self.tree, (44, 100, 290, 120, 130, 120, 80), (0.2, 0.6, 1.8, 0.9, 0.8, 0.7, 0.4))     # a wide window is shared, not left to the Command column
        self.tree.selectionChangedRows.connect(lambda _rows: self.on_select())
        tl.addWidget(self.tree, 1)
        split.addWidget(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        det = QWidget()
        self.details = det
        dl = QVBoxLayout(det)
        dl.setContentsMargins(0, 4, 6, 4)
        dl.setSpacing(SP.sm)

        ed = QGroupBox('Selected command')
        el = QVBoxLayout(ed)
        self.cmd_info_lbl = common.hint('')
        el.addWidget(self.cmd_info_lbl)
        er = QHBoxLayout()
        er.addWidget(label('Command (template):'))
        self.cmd_entry = QLineEdit()
        self.cmd_entry.setProperty('mono', True)
        self.cmd_entry.setAccessibleName('Command (template)')
        er.addWidget(self.cmd_entry, 1)
        self.btn_use = QPushButton('Use for this point')
        self.btn_use.clicked.connect(self.use_command)
        self.btn_restore = QPushButton('Restore default')
        self.btn_restore.clicked.connect(self.restore_command)
        er.addWidget(self.btn_use)
        er.addWidget(self.btn_restore)
        el.addLayout(er)
        self.cmd_preview_lbl = label('', wrap=True)
        self.cmd_preview_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        el.addWidget(self.cmd_preview_lbl)
        self.cmd_test_lbl = common.hint('')
        el.addWidget(self.cmd_test_lbl)
        dl.addWidget(ed)

        ex = QGroupBox('Add a command line for this point')
        xl = QVBoxLayout(ex)
        r1 = QHBoxLayout()
        self.x_inst_box = QComboBox()
        self.x_inst_box.setMinimumWidth(190)
        self.x_inst_box.setAccessibleName('Instrument')
        self.x_phase_box = QComboBox()
        self.x_phase_box.addItems(['before', 'after'])
        self.x_phase_box.setAccessibleName('Before or after')
        r1.addWidget(self.x_inst_box)
        r1.addWidget(self.x_phase_box)
        r1.addWidget(label('the point\'s own commands:'))
        self.x_cmd_entry = QLineEdit()
        self.x_cmd_entry.setProperty('mono', True)
        self.x_cmd_entry.setAccessibleName('Command line')
        r1.addWidget(self.x_cmd_entry, 1)
        xl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(label('Read back with (a setting needs this):'))
        self.x_rb_entry = QLineEdit()
        self.x_rb_entry.setProperty('mono', True)
        self.x_rb_entry.setMaximumWidth(190)
        self.x_rb_entry.setAccessibleName('Read back with')
        r2.addWidget(self.x_rb_entry)
        r2.addWidget(label('Expected reply:'))
        self.x_exp_entry = QLineEdit()
        self.x_exp_entry.setProperty('mono', True)
        self.x_exp_entry.setMaximumWidth(130)
        self.x_exp_entry.setAccessibleName('Expected reply')
        r2.addWidget(self.x_exp_entry)
        self.btn_add = QPushButton('Add line')
        self.btn_add.clicked.connect(self.add_extra)
        self.btn_rm = QPushButton('Remove selected line')
        self.btn_rm.clicked.connect(self.remove_extra)
        r2.addWidget(self.btn_add)
        r2.addWidget(self.btn_rm)
        r2.addStretch(1)
        xl.addLayout(r2)
        dl.addWidget(ex)

        self.dev = QGroupBox('Point definition (developer mode)')
        dvl = QVBoxLayout(self.dev)
        self.dev_note = common.hint('')
        dvl.addWidget(self.dev_note)
        self.dev_grid_host = QWidget()
        self.dev_grid = QGridLayout(self.dev_grid_host)
        self.dev_grid.setContentsMargins(0, 0, 0, 0)
        self.dev_grid.setColumnStretch(3, 1)
        dvl.addWidget(self.dev_grid_host)
        dl.addWidget(self.dev)
        dl.addStretch(1)
        scroll.setWidget(det)
        split.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 350])
        root.addWidget(split, 1)
        self._build_fields()

        # ---- footer (always visible)
        self.warn = common.ToneLabel('warn')
        root.addWidget(self.warn)
        self.summary = label('', wrap=True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.summary)
        rr = QHBoxLayout()
        rr.addWidget(label('Reason for the change (required):'))
        self.reason_entry = QLineEdit()
        self.reason_entry.setAccessibleName('Reason for the change')
        rr.addWidget(self.reason_entry, 1)
        self.reason_entry.textChanged.connect(lambda _t: self._reason_typed())
        root.addLayout(rr)
        sc = QHBoxLayout()
        sc.addWidget(label('Applies to:'))
        self.scope_buttons = {}
        for value, text, available, why in model.scope_choices():
            b = QRadioButton(text)
            b.setChecked(value == model.scope)
            b.setEnabled(bool(available))
            if why:
                b.setToolTip(why)
            b.clicked.connect(lambda _c=False, v=value: self.scope_changed(v))
            sc.addWidget(b)
            self.scope_buttons[value] = b
        sc.addStretch(1)
        root.addLayout(sc)
        self.chk_redo = QCheckBox('Measure this point again after the change')
        self.chk_redo.clicked.connect(self._redo_toggled)
        root.addWidget(self.chk_redo)
        self.chk_ack = QCheckBox('I understand this changes pass/fail for this point and is recorded in the audit trail.')
        self.chk_ack.clicked.connect(self._ack_toggled)
        root.addWidget(self.chk_ack)
        self.message = common.ToneLabel('bad')
        root.addWidget(self.message)
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_cancel = QPushButton('Cancel changes')
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_apply = QPushButton('Apply')
        self.btn_apply.setProperty('role', 'primary')
        self.btn_apply.clicked.connect(self.apply)
        self.btn_close = QPushButton('Close')
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_cancel, self.btn_apply, self.btn_close):
            foot.addWidget(b)
        root.addLayout(foot)

        common.clamp_size(self, *DEFAULT_SIZE, *MIN_SIZE)
        self.lock.on_change(lambda _s: self._safe(self.refresh))
        self.refresh()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_MS)
        self._poll_timer.timeout.connect(lambda: self._safe(self._tick))
        self._poll_timer.start()

    # ---- helpers -------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _tone(r):
        return 'muted' if (not r.editable and not r.changed) else None

    def _safe(self, fn):
        if common.alive(self) and not self._closing:
            fn()

    def _tick(self):
        self.update_header()
        self.update_buttons()

    def _clear_fields(self):
        while self.dev_grid.count():
            it = self.dev_grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _build_fields(self):
        self._clear_fields()
        self.fvars, self.fmsg, self.fentries, self.frestore = {}, {}, {}, {}
        for r, name in enumerate(n for n in PM.FIELD_ORDER if n in self.model.fields):
            f = self.model.fields[name]
            self.dev_grid.addWidget(label(f.label), r, 0)
            e = QLineEdit(f.text)
            e.setAccessibleName(f.label)
            e.setMinimumWidth(320 if name == 'description' else 140)
            e.setMaximumWidth(420 if name == 'description' else 160)
            self.dev_grid.addWidget(e, r, 1)
            self.fentries[name] = e
            self.fvars[name] = e
            e.textEdited.connect(lambda _t, n=name: self.field_typed(n))
            e.editingFinished.connect(lambda n=name: self.field_typed(n))
            b = QPushButton('Restore default')
            b.clicked.connect(lambda _c=False, n=name: self.restore_field(n))
            self.dev_grid.addWidget(b, r, 2)
            self.frestore[name] = b
            msg = common.hint('')
            self.dev_grid.addWidget(msg, r, 3)
            self.fmsg[name] = msg

    def field_text(self, name) -> str:
        return self.fvars[name].text()

    def set_field_text(self, name, text) -> None:
        self.fvars[name].setText(text)

    # ---- refresh -------------------------------------------------------------------------------------------------------------
    def refresh(self):
        m = self.model
        self.update_header()
        self.update_scope_buttons()
        self.plan_lbl.setText(m.plan_note)
        sel = self._selected
        rows = list(m.rows)
        self.tree.set_rows(rows, keep_selection=False)
        if sel is not None:
            keep = next((r for r in rows if r.seq == sel), None)
            if keep is not None:
                self.tree.select_rows([keep])
        drivers = m.extra_drivers()
        items = [f'{lab} ({d})' for d, lab in drivers]
        current = self.x_inst_box.currentText()
        self.x_inst_box.blockSignals(True)
        self.x_inst_box.clear()
        self.x_inst_box.addItems(items)
        if current in items:
            self.x_inst_box.setCurrentText(current)
        self.x_inst_box.blockSignals(False)
        for name, f in m.fields.items():
            e = self.fvars.get(name)
            if e is not None and f.staged is None and e.text() != f.text:
                e.setText(f.text)
        self.on_select()
        self.update_fields()
        self.update_footer()
        self.update_buttons()

    def update_scope_buttons(self):
        for value, _label, available, why in self.model.scope_choices():
            b = self.scope_buttons.get(value)
            if b is not None:
                b.setEnabled(bool(available))
        b = self.scope_buttons.get(self.model.scope)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def update_header(self):
        m = self.model
        st = self.lock.state
        self.chip_dev.set('DEVELOPER MODE ON' if st == 'unlocked' else 'DEVELOPER MODE OFF', 'warn' if st == 'unlocked' else 'neutral')
        self.btn_dev.setText('Turn off developer mode' if st == 'unlocked' else 'Turn on developer mode...')
        self.banner_lbl.setText(m.banner)
        why = m.blocked_reason
        if why:
            self.info_lbl.setText(why + '  (read-only)')
        elif st != 'unlocked':
            self.info_lbl.setText('You can type or change commands for this run only without a passphrase. Turn on developer mode to change the point\'s '
                                  'limits, nominal, unit and description, or to save a change for this instrument or for all of this model. '
                                  'The passphrase is the one used for all procedure changes.')
        else:
            self.info_lbl.setText(m.effective_from_text() or m.pm.applies_from_text())

    def update_fields(self):
        m = self.model
        dev_ok = m.editable
        for name, f in m.fields.items():
            e = self.fentries.get(name)
            if e is None:
                continue
            e.setEnabled(bool(f.editable and dev_ok))
            self.frestore[name].setEnabled(bool(f.editable and dev_ok and f.changed))
            parts = []
            if f.problems:
                parts.append('; '.join(f.problems))
            else:
                if f.reason and not f.editable and f.reason != m.read_only_reason:        # the same sentence is in the note above the fields
                    parts.append(f.reason)
                if f.changed:
                    parts.append(f'default: {f.factory}')
                if f.display and f.display != f.text:
                    parts.append(f'= {f.display}')
                if f.note:
                    parts.append(f.note)
            self.fmsg[name].setText('   '.join(parts))
        self.dev.setTitle('Point definition (developer mode)' + ('' if dev_ok else ' - read-only'))
        if dev_ok:
            self.dev_note.setText('Change the point\'s limits, nominal, unit and description here; each change needs a reason below and is recorded.')
        elif m.blocked_reason:
            self.dev_note.setText('Read-only: ' + m.blocked_reason)
        else:
            self.dev_note.setText('Read-only: turn on developer mode (button at the top) to change the limits, nominal, unit or description of this point.')

    def update_footer(self):
        m = self.model
        lines = [f'{what}: {old} -> {new}' if (old or new) else what for what, old, new in m.staged_summary()]
        self.summary.setText('To be saved:\n  ' + '\n  '.join(lines) if lines else '')
        self.warn.setText('\n'.join(m.warnings()))
        need_redo = m.redo_required
        if need_redo:
            self.chk_redo.setChecked(True)
        self.chk_redo.setEnabled(not (need_redo or not m.has_reading))
        self.chk_ack.setChecked(bool(m.acknowledged))
        self.chk_ack.setEnabled(bool(m.needs_acknowledgement))

    def update_buttons(self):
        m = self.model
        self.btn_apply.setEnabled(bool(m.pm.drafts and not m.blockers()))
        self.btn_cancel.setEnabled(bool(m.pm.drafts))
        ok = m.commands_editable                                    # typed commands for this run need no developer mode
        self.btn_add.setEnabled(bool(ok))
        r = m.row(self._selected) if self._selected is not None else None
        self.btn_rm.setEnabled(bool(r is not None and r.extra is not None and (ok or r.pending)))
        self.btn_use.setEnabled(bool(r is not None and r.editable))
        self.btn_restore.setEnabled(bool(r is not None and (r.pending or r.source == 'this point' or r.staged)))
        self.cmd_entry.setEnabled(bool(r is not None and r.editable))

    # ---- selection -----------------------------------------------------------------------------------------------------------
    def select_seq(self, seq):
        """Select the command row `seq` (what a click does)."""
        row = next((r for r in self.model.rows if r.seq == seq), None)
        if row is not None:
            self.tree.select_rows([row])
        self.on_select()

    def on_select(self):
        sel = self.tree.selected_rows()
        self._selected = int(sel[0].seq) if sel else self._selected
        r = self.model.row(self._selected) if self._selected is not None else None
        if r is None:
            self.cmd_info_lbl.setText('Select a command above to see its details.')
            self.cmd_entry.setText('')
            self.cmd_preview_lbl.setText('')
            self.cmd_test_lbl.setText('')
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
        self.cmd_info_lbl.setText('  |  '.join(bits))
        self.cmd_entry.setText(r.staged if r.staged is not None else (r.template or r.wire))
        self.cmd_preview_lbl.setText(f'This point sends: {r.shown_wire}' + ('   (typed commands are UNVERIFIED)' if r.source != 'factory' or r.staged else ''))
        self.cmd_test_lbl.setText('Test command: ' + self.model.test_info(r.seq)[1])
        if r.seq in self.model.command_problems:
            self.message.setText('; '.join(self.model.command_problems[r.seq]))
        self.update_buttons()

    # ---- actions ---------------------------------------------------------------------------------------------------------------
    def toggle_dev(self):
        if self.lock.unlocked:
            self.lock.lock()
        else:
            UI.ask_unlock(self, self.lock)
        self.model.load(plan=False)
        self.refresh()

    def scope_changed(self, value=None):
        if value is None:
            value = next((v for v, b in self.scope_buttons.items() if b.isChecked()), self.model.scope)
        try:
            self.model.set_scope(value)
            self.message.setText('')
        except ValueError as ex:
            self.scope_buttons[self.model.scope].setChecked(True)
            self.message.setText(str(ex))
        self.update_footer()

    def _reason_typed(self):
        self.model.set_reason(self.reason_entry.text())
        self.update_buttons()

    def _ack_toggled(self, *_):
        self.model.acknowledge(self.chk_ack.isChecked())
        self.update_buttons()

    def _redo_toggled(self, *_):
        self.model.set_redo(self.chk_redo.isChecked())

    def use_command(self):
        if self._selected is None:
            return
        probs = self.model.stage_command(self._selected, self.cmd_entry.text())
        self.message.setText('; '.join(probs))
        self.refresh()

    def restore_command(self):
        if self._selected is None:
            return
        probs = self.model.restore_command(self._selected)
        self.message.setText('; '.join(probs))
        self.refresh()

    def add_extra(self):
        label_ = self.x_inst_box.currentText()
        driver = label_[label_.rfind('(') + 1:-1] if '(' in label_ else label_
        probs = self.model.add_extra(driver, self.x_phase_box.currentText(), self.x_cmd_entry.text(), self.x_rb_entry.text(), self.x_exp_entry.text())
        self.message.setText('; '.join(probs))
        if not probs:
            self.x_cmd_entry.setText('')
            self.x_rb_entry.setText('')
            self.x_exp_entry.setText('')
        self.refresh()

    def remove_extra(self):
        if self._selected is None:
            return
        probs = self.model.remove_extra(self._selected)
        self.message.setText('; '.join(probs))
        self.refresh()

    def field_typed(self, name):
        probs = self.model.stage_field(name, self.fvars[name].text())
        self.message.setText('')
        self.update_fields()
        self.update_footer()
        self.update_buttons()
        return probs

    def restore_field(self, name):
        self.model.restore_field(name)
        self.fvars[name].setText(self.model.fields[name].text)
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
            if not common.ask_yes_no(self, 'Confirm wider change', f'This change will apply to {where} and stay in effect for later runs.\n\nContinue?'):
                return
            confirmed = True
        if m.redo_will_happen:
            if not common.ask_yes_no(self, 'Measure the point again', 'This point already has a reading. It will be measured again with the new settings and the '
                                     'old reading replaced by the new one. Nothing is retried automatically.\n\nSave the change and redo the point?'):
                return
        self._busy = True
        try:
            res = m.apply(confirmed=confirmed)
        except pm.OverrideError as ex:
            self.message.setText(str(ex))
            return
        finally:
            self._busy = False
        self.message.setText('; '.join(f'{k}: {msg}' for k, msg in res.errors))
        self.reason_entry.setText('')
        self._build_fields()
        self.refresh()

    def cancel(self):
        self.model.cancel()
        self.reason_entry.setText('')
        self.message.setText('')
        self._build_fields()
        self.refresh()

    def closeEvent(self, ev):
        if self.model.pm.drafts and not common.ask_yes_no(self, 'Discard changes?', 'There are changes that have not been applied. Close and discard them?'):
            ev.ignore()
            return
        self._closing = True
        self._poll_timer.stop()
        _open.pop((id(self.app), str(self.model.pid)), None)
        super().closeEvent(ev)
