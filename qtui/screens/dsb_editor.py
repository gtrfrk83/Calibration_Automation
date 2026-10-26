"""Datasheet Builder (Qt): the grid editor window, the Qt twin of datasheet_builder_ui.GridEditorWindow.

One datasheet as a big grid.  Top: title strip with the saved / warnings / check pills; the sheet bar (Make, Model, Title, Tolerances for [only when the sheet has
several time periods: there is NO period picker, the limits shown are the default period's], Lock Status, Undo / Redo, Standards, More, Preview / Print, Try in
demo, Run, Save); below it the Edit Cell bar, the sheet at the left and the row Inspector at the right; under the sheet the row count, Show list, Sheet check and
Recalc all.  Every decision is in datasheet_builder_ui_model.GridModel; this class draws it and passes clicks and keys to it.  The Low / High limit cells are
read-only (filled only from the tolerance calculator).  No Tk import."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget)

import datasheet_builder_ui_model as M
from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.screens.dsb_check import CheckWindowMixin
from qtui.screens.dsb_dialogs import DriversWindow, PageDialog, PreviewWindow, ProblemsWindow, RuleDialog, SaveBlockedDialog, VersionsWindow, present
from qtui.screens.dsb_grid import SheetGrid
from qtui import layouts
from qtui.screens.dsb_inspector import Inspector, Section
from qtui.screens.dsb_pages import AutomationPage, FunctionsPage, HeaderPage, RangesPage, SpecPage
from qtui.theme import M as SZ

INSPECTOR_W, INSPECTOR_NARROW_W, RAIL_W = 336, 290, 34
NARROW_BELOW = 1250                      # window width (px) under which the inspector is the narrower one


TEMPLATE_PROMPT = 'Add template...'


class _UndoKeys(QObject):
    """Ctrl+Z / Ctrl+Y undo the SHEET even while a text box has the focus (as in the Tk build): the text box must not keep them for itself."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.ShortcutOverride and ev.modifiers() & Qt.KeyboardModifier.ControlModifier and ev.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
            return True                                           # not accepted: the window shortcut fires
        return False


class GridEditorWindow(CheckWindowMixin, QWidget):
    launcher = None
    _accepted_unverified = ''

    def __init__(self, parent, model, panel=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName('root')
        self.model, self.panel = model, panel
        self.dialogs: list = []
        self._outcome = ''
        self._keep = False
        self._bar_wrapped = None
        self._insp_open = True
        self._insp_manual = False                            # True once Mike hides / shows the inspector by hand: then the window width no longer decides
        self._insp_narrow = None
        self._state_note = ''
        self.note = C.Var('')                                # the last action's message ('Not done: ...' for a refusal)
        self.issue = C.Var('')                               # the selected row's problem, or why its cell cannot be typed in
        self.status = C.Var('', on_change=lambda t: self.status_line.set(t))      # the one line at the bottom: the message, else the problem, else a hint
        self.setWindowTitle('Datasheet Builder')

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_title())
        main = QWidget()
        self.grid = QGridLayout(main)
        self.grid.setContentsMargins(12, 6, 12, 6)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(0, 1)
        self.grid.setRowStretch(2, 1)
        root.addWidget(main, 1)
        self.status_line = widgets.StatusLine('')
        self.status_line.setContentsMargins(12, 4, 12, 4)
        root.addWidget(self.status_line)

        self._build_header()
        self._build_editbar()
        self.sheet = SheetGrid(model, self.sheet_click, self.sheet_key, self.focus_bar)
        self.sheet.on_context = self.sheet_context
        self.grid.addWidget(self.sheet, 2, 0)
        self._build_footer()
        self.panel_box = Inspector(self)
        self.remark_v, self.run_v = self.panel_box.remark_v, self.panel_box.run_v
        self.inspector_frame = self.panel_box
        self.rail = QFrame()
        self.rail.setProperty('surface', 'card')
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(3, 6, 3, 6)
        self.rail_b = C.button('<', self.toggle_inspector, tooltip='Show the row panel (Ctrl+I).')
        self.rail_b.setProperty('role', 'icon')
        self.rail_b.setAccessibleName('Show the row panel')
        rl.addWidget(self.rail_b)
        rl.addStretch(1)
        self.grid.addWidget(self.panel_box, 1, 1, 3, 1)
        self.grid.addWidget(self.rail, 1, 1, 3, 1)
        self._set_inspector_width()

        for seq, fn in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+S', self.save), ('Ctrl+P', self.preview), ('Ctrl+I', self.toggle_inspector)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda fn=fn: fn())
        self._undo_keys = _UndoKeys(self)
        for e in self.findChildren(QLineEdit):
            e.installEventFilter(self._undo_keys)
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self.resize(min(1340, scr.width() - 40), min(900, scr.height() - 60))
        self.setMinimumSize(min(980, scr.width() - 40), min(620, scr.height() - 60))
        self._restore_layout()
        self.sync()
        self.refresh()                                       # header pills, title, Undo / Redo state before the first edit

    # ---- building
    def _build_title(self):
        strip = QFrame()
        strip.setProperty('surface', 'strip')
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(22, 8, 22, 8)
        lay.addWidget(widgets.label('Datasheet Builder', 'h2'))
        lay.addWidget(widgets.label('One row per test point. Click a cell, type, press Enter.', 'sub'))
        lay.addStretch(1)
        self.dirty_pill = widgets.Badge('', 'warn')
        self.problem_pill = widgets.Badge('', 'good')
        C.Clickable(self.problem_pill, self.show_problems)
        C.tip(self.problem_pill, lambda: 'Click to open the warnings list.\n' + self.model.problem_summary())
        lay.addWidget(self.dirty_pill)
        lay.addWidget(self.problem_pill)
        self.build_check_pill(lay)                           # the Sheet check pill (shown once the check has been run for this version of the sheet)
        return strip

    def _field(self, label):
        f = QWidget()
        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        f.label = widgets.label(label, 'hint')
        lay.addWidget(f.label)
        f.lay = lay
        return f

    def _build_header(self):
        bar = QWidget()
        self.sheet_bar = bar
        bl = QGridLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setColumnStretch(0, 1)
        self.grid.addWidget(bar, 0, 0, 1, 2)
        left, right = QWidget(), QWidget()
        self.bar_left, self.bar_right = left, right
        ll, rl = QHBoxLayout(left), QHBoxLayout(right)
        for lay in (ll, rl):
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
        self.hdr = {}
        for key, label, width, hint in (('make', 'Make', 110, 'The manufacturer, for example Keysight.'), ('model', 'Model', 90, 'For example 34461A.'),
                                        ('title', 'Title', 200, 'What the procedure list shows, for example 34461A Performance Verification.')):
            f = self._field(label)
            e = QLineEdit()
            e.setMinimumWidth(width)
            e.editingFinished.connect(self.commit_header)
            C.tip(e, hint)
            f.lay.addWidget(e)
            ll.addWidget(f, 1 if key == 'title' else 0)
            self.hdr[key] = e
        self.make_e, self.model_e, self.title_e = self.hdr['make'], self.hdr['model'], self.hdr['title']
        self.make_v, self.model_v, self.title_v = (C.Bind(self.hdr[k]) for k in ('make', 'model', 'title'))
        self.period_cell = self._field('Tolerances for')
        self.period_label = self.period_cell.label
        self.period_box = QLabel('')                          # a plain label, not a picker: the limits shown are the default period's (1 year)
        self.period_cell.lay.addWidget(self.period_box)
        self.period_cell.setVisible(False)
        ll.addWidget(self.period_cell)
        # right group: Lock Status, Undo / Redo, Standards, More, Preview / Print, Try in demo, Run, Save
        lockf = self._field('Lock Status')
        self.lock_box = QComboBox()
        self.lock_box.addItems([lab for _k, lab in M.LOCK_MODES])
        self.lock_box.activated.connect(lambda _i: self.lock_chosen())
        C.tip(self.lock_box, 'Locked: nothing can be changed by accident. Edit Mode: you can change the sheet.')
        lockf.lay.addWidget(self.lock_box)
        self.lock_v = C.Bind(self.lock_box)
        rl.addWidget(lockf)
        self.undo_b = C.button('Undo', self.undo, compact=True, tooltip='Undo the last change (Ctrl+Z).')
        self.redo_b = C.button('Redo', self.redo, compact=True, tooltip='Redo (Ctrl+Y).')
        self.standards_b = C.button('Standards...', self.open_standards, compact=True)
        self.more_b = C.button('More', None, compact=True)
        menu = QMenu(self.more_b)
        for label, cmd in (('Add handheld functions...', self.add_handheld), ('Test point calculator...', self.open_calculator), ('Ranges...', self.open_ranges),
                           ('Specification table (advanced)...', self.open_spec), ('Sections and function settings...', self.open_functions),
                           ('Details and time periods...', self.open_details), ('What can the suite drive today?', self.open_drivers), ('Version history...', self.open_versions)):
            menu.addAction(label, lambda cmd=cmd: cmd())
        self.more_b.setMenu(menu)
        self.more_menu = menu
        self.preview_b = C.button('Preview / Print', self.preview, compact=True, tooltip='See the blank datasheet as it prints, and save it as a PDF (Ctrl+P).')
        self.demo_b = C.button('Try in demo', lambda: self.run_sheet(True), compact=True)
        self.run_b = C.button('Run', lambda: self.run_sheet(False), compact=True)
        C.tip(self.run_b, lambda: 'Save, then run this datasheet on the real instruments (the same as Run in the Procedures list).\n' + self.model.automation_line())
        C.tip(self.demo_b, lambda: 'Save, then try this datasheet with virtual instruments (demo: nothing real is driven, the report is marked DEMO).\n' + self.model.automation_line())
        self.save_b = C.button('Save', self.save, 'primary', tooltip='Save a new version (Ctrl+S).')
        for w in (self.undo_b, self.redo_b, self.standards_b, self.more_b, self.preview_b, self.demo_b, self.run_b, self.save_b):
            rl.addWidget(w, 0, Qt.AlignmentFlag.AlignBottom)
        lockf.layout().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self._bar_layout(10 ** 4)

    def _bar_layout(self, width):
        need = self.bar_left.sizeHint().width() + self.bar_right.sizeHint().width() + 30
        wrap = need > width
        if wrap == self._bar_wrapped:
            return
        self._bar_wrapped = wrap
        bl = self.sheet_bar.layout()
        bl.removeWidget(self.bar_left)
        bl.removeWidget(self.bar_right)
        bl.addWidget(self.bar_left, 0, 0)
        if wrap:
            bl.addWidget(self.bar_right, 1, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
        else:
            bl.addWidget(self.bar_right, 0, 1, Qt.AlignmentFlag.AlignRight)

    def _build_editbar(self):
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(widgets.label('Edit Cell', 'section'))
        self.bar = QLineEdit()
        self.bar.setAccessibleName('Edit Cell')
        self.bar_v = C.Bind(self.bar)
        C.tip(self.bar, 'Type the new content of the selected cell and press Enter. Esc puts the old text back.')
        self.bar.returnPressed.connect(lambda: self.commit_bar('down'))
        self._bar_typed = False
        self.bar.textEdited.connect(lambda _t: setattr(self, '_bar_typed', True))     # text the operator typed (not text the window filled in)
        self.bar.installEventFilter(_BarKeys(self))
        lay.addWidget(self.bar, 1)
        self.symbol_buttons = {}                      # the ± ° µ ¹ ² ³ · Units buttons were removed (not needed); insert_symbol() stays for the code that uses it
        self.grid.addWidget(bar, 1, 0)

    def _build_footer(self):
        foot = QWidget()
        lay = QHBoxLayout(foot)
        lay.setContentsMargins(0, 2, 0, 0)
        self.count_l = widgets.label('', 'sub')
        lay.addWidget(self.count_l)
        lay.addSpacing(8)
        self.show_list_b = C.button('Show list', self.show_problems, compact=True, tooltip='Open the warnings list: every problem on the sheet, with the row it is on.')
        lay.addWidget(self.show_list_b)
        self.build_check_button(lay)
        self.recalc_b = C.button('Recalc all', self.recalc, compact=True, tooltip='Re-run the test point rules and check every row of the sheet.')
        lay.addWidget(self.recalc_b)
        lay.addSpacing(8)
        self.delete_b = C.button('Delete line', self.delete_line, compact=True, tooltip='Delete the selected line (a heading deletes its whole section). Undo brings it back. Also Delete on the nominal cell, or right-click the line.')
        lay.addWidget(self.delete_b)
        lay.addSpacing(8)
        self.template_box = QComboBox()                # templates: a starting set of empty sections, added on demand (New no longer asks)
        self.template_box.setToolTip('Add a template to this datasheet: empty sections to fill in. Sections the sheet already has stay as they are. Undo takes them out again.')
        self.template_box.setMinimumWidth(190)
        self.template_box.addItem(TEMPLATE_PROMPT)
        for name, _tip in self.model.TEMPLATES:
            self.template_box.addItem(name)
        self.template_box.activated.connect(self.template_chosen)
        lay.addWidget(self.template_box)
        lay.addStretch(1)
        self.grid.addWidget(foot, 3, 0)

    @property
    def count_v(self):
        return self.count_l

    # ---- the inspector: hide / show, width
    def toggle_inspector(self):
        """Hide > / the rail button / Ctrl+I: a choice made by hand.  It sticks for the session (the window width no longer opens or closes it)."""
        self._insp_manual = True
        self._insp_open = not self._insp_open
        self._set_inspector_width()
        if not self._insp_open:
            self.rail_b.setFocus()
        else:
            self.sheet.setFocus()
        return 'break'

    def _auto_inspector(self, width):
        """Open or close the inspector for the window width (unless it was set by hand).  Returns True when it changed.  Focus is left alone."""
        want = M.inspector_should_be_open(width, M.INSPECTOR_COLLAPSE_BELOW, self._insp_manual, self._insp_open)
        if want == self._insp_open:
            return False
        self._insp_open = want
        self._set_inspector_width()
        return True

    def _set_inspector_width(self):
        if self._insp_open:
            narrow = 1 < self.width() < NARROW_BELOW
            self._insp_narrow = narrow
            self.panel_box.setFixedWidth(INSPECTOR_NARROW_W if narrow else INSPECTOR_W)
            self.rail.setVisible(False)
            self.panel_box.setVisible(True)
        else:
            self.panel_box.setVisible(False)
            self.rail.setFixedWidth(RAIL_W)
            self.rail.setVisible(True)

    def _window_size(self, width):
        if self._auto_inspector(width):
            return
        if self._insp_open:
            narrow = width < NARROW_BELOW
            if narrow != self._insp_narrow:
                self._set_inspector_width()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._window_size(ev.size().width())
        self._bar_layout(ev.size().width() - 24)

    # ---- showing
    def sync(self):
        """Redraw the sheet and fill the Edit Cell bar and the inspector from the model."""
        m = self.model
        if not self._keep:
            self._outcome = ''
        row = m.select()
        self.sheet.reload()
        ok, why = m.cell_editable()
        self.bar.setText(m.cell_text())
        self._bar_typed = False
        self.bar.setReadOnly(not ok)
        self.delete_b.setEnabled(not getattr(m, 'locked', False))
        state = m.panel_state()
        self._state_note = state['note']
        if not getattr(self, '_keep_typed', False):
            self.panel_box.load(state)
        self.panel_box.set_header(row, sum(1 for r in m.rows() if r['kind'] != 'blank'))
        self.remark_v.set(state['form']['remark']), self.run_v.set(bool(state['form']['run']))
        self.set_issue(row, ok, why)

    def set_issue(self, row, ok=True, why='', fresh=False):
        text = f'Row {row["n"]}: {row["problem"]}' if row['problem'] else ''
        self.issue.set(text or ('' if ok else why))
        if fresh:
            self._outcome = ''
        self._show_status(row)

    def _show_status(self, row=None):
        """The one line under the window: the last message if there is one, else the problem of the selected row, else a hint about the row."""
        row = row or self.model.selected_row()
        if self._outcome:
            self.status.set(self._outcome)
        elif row['problem']:
            self.status.set(f'{"Error" if row["level"] == "error" else "Warning"}, row {row["n"]}: {row["problem"]}')
        elif self.issue.get():
            self.status.set(self.issue.get())
        else:
            self.status.set(self._state_note)

    def refresh(self):
        m = self.model
        ds = m.ds
        for val, e in ((ds.make, self.make_e), (ds.model, self.model_e), (ds.title, self.title_e)):
            if e.text() != val and not e.hasFocus():
                e.setText(val)
        self.setWindowTitle(('* ' if m.dirty else '') + m.title + ' - Datasheet Builder')
        self.dirty_pill.set('unsaved changes' if m.dirty else 'saved', 'warn' if m.dirty else 'good')
        c = m.problem_counts()
        self.problem_pill.set(f'{c["errors"]} to fix' if c['errors'] else f'{c["warnings"]} warning(s)' if c['warnings'] else 'no problems',
                              'bad' if c['errors'] else 'warn' if c['warnings'] else 'good')
        self.refresh_check()
        self._schedule_standards()
        self.count_l.setText(f'{sum(1 for r in m.rows() if r["kind"] != "blank")} rows')
        self.undo_b.setEnabled(bool(m.can_undo))
        self.redo_b.setEnabled(bool(m.can_redo))
        # The period picker is gone: the limits shown are always those of the default period (1 year); only a sheet with several periods names the one on show.
        if len(ds.periods) > 1:
            self.period_cell.setVisible(True)
            self.period_box.setText(next((p.label or p.id for p in ds.periods if p.id == m.period), ''))
        else:
            self.period_cell.setVisible(False)
        self.sync()
        for d in list(self.dialogs):
            try:
                if not d.isVisible():
                    self.dialogs.remove(d)
                    continue
                d.reload()
            except RuntimeError:
                self.dialogs.remove(d)

    def changed(self, outcome=None):
        """After every action: the message (green / red), then redraw everything."""
        if outcome is not None:
            msg = outcome.message if outcome.ok else 'Not done: ' + outcome.message
            self.note.set(msg)
            self._outcome = outcome.message if outcome.ok else 'Cannot do that: ' + outcome.message
        self._keep = outcome is not None
        try:
            self.refresh()
        finally:
            self._keep = False
        return outcome

    def commit_page(self):
        """Hook the detail pages use before they close (nothing is held back in this window)."""

    # ---- the sheet
    def sheet_click(self, r, c):
        self.commit_bar_if_changed()
        self.model.select_at(r, c)
        self.sync()
        if M.COL_KEYS[c] == 'standard':
            self.open_standard_menu()

    # ---- the STANDARD column: a drop-down of the standards that cover the point (and 'Automatic'); the UNCERTAINTY cell follows
    STANDARD_DELAY_MS = 350
    auto_standards = True                  # False: the cells are worked out only when asked for (tests)

    def update_standard_columns(self):
        """Work out the STANDARD / UNCERTAINTY cells once the edits have settled (the matcher is not cheap on a big sheet): blank until then."""
        try:
            if not self.model.standard_columns_ready() and self.model.refresh_standard_columns():
                self.sheet.reload()
        except RuntimeError:
            pass                                                   # the window went away

    def _schedule_standards(self):
        if not self.auto_standards or self.model.standard_columns_ready():
            return
        t = getattr(self, '_std_timer', None)
        if t is None:
            t = self._std_timer = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self.update_standard_columns)
        t.start(self.STANDARD_DELAY_MS)                            # every edit restarts the wait

    def standard_menu(self):
        """The drop-down for the selected STANDARD cell (a QMenu, not yet shown), or None when the row has no choice to make."""
        m = self.model
        self.update_standard_columns()
        row = m.selected_row()
        choices = m.standard_choices(row['key']) if row else []
        if not choices:
            return None
        menu = QMenu(self.sheet)
        menu.setToolTipsVisible(True)
        sub = None
        for ch in choices:
            if ch['scope'] == 'section' and row['kind'] == 'point':
                if sub is None:
                    menu.addSeparator()
                    sub = menu.addMenu('Set for the whole section')
                target = sub
            else:
                target = menu
            act = target.addAction(ch['label'])
            act.setCheckable(True)
            act.setChecked(bool(ch['checked']))
            act.setEnabled(bool(ch['enabled']) and not getattr(m, 'locked', False))
            act.triggered.connect(lambda _c=False, k=row['key'], v=ch['value'], sc=ch['scope']: self.standard_chosen(k, v, sc))
        return menu

    def open_standard_menu(self):
        row = self.model.selected_row()
        if not row or row['kind'] not in ('point', 'header'):
            return None
        menu = self.standard_menu()
        if menu is None:
            self._outcome = ''
            self.status.set('No standard to choose for this row (it carries no uncertainty, or no standards are loaded).')
            return None
        rect = self.sheet.cell_rect(self.model.row_index(), M.COL_KEYS.index('standard'))
        self._popup(menu, self.sheet.viewport().mapToGlobal(rect.bottomLeft()))
        return menu

    def _popup(self, menu, pos):
        menu.exec(pos)

    def standard_chosen(self, key, value, scope='point'):
        """A choice in the drop-down: ds.assignments (ONE undo step), the same as 'Use this standard for the point' on the Automation page."""
        self.commit_bar_if_changed()
        out = self.changed(self.model.choose_standard(key, value, scope))
        self.update_standard_columns()                             # the uncertainty cell follows at once
        return out

    def sensor_section(self, sensor):
        """'Whole section' / the right-click menu: every row of the temperature section gets the same sensor (ONE undo step)."""
        self.commit_bar_if_changed()
        return self.changed(self.model.set_sensor(None, sensor, 'section'))

    def delete_line(self):
        """Delete the selected line (the Delete line button and the right-click menu)."""
        self.commit_bar_if_changed()
        row = self.model.selected_row()
        if row and row.get('kind') == 'header':
            n = sum(1 for r in self.model.rows() if r.get('fid') == row.get('fid') and r.get('kind') == 'point')
            if n and not C.ask_yes_no(self, 'Delete section', f'Delete the whole section "{row.get("function", "")}" with its {n} row(s)? (Undo brings it back.)'):
                return None
        return self.changed(self.model.clear_row())

    def sheet_context(self, r, c, gpos):
        self.sheet_click(r, c)
        menu = QMenu(self.sheet)
        row = self.model.selected_row()
        label = 'Delete section' if row and row.get('kind') == 'header' else 'Delete line'
        act = menu.addAction(label)
        act.setEnabled(bool(row) and row.get('kind') != 'blank' and not getattr(self.model, 'locked', False))
        act.triggered.connect(self.delete_line)
        if row and row.get('fid') and row.get('kind') in ('header', 'point') and self.model.ds.function(row['fid']).kind == 'TEMP' and not getattr(self.model, 'locked', False):
            sub = menu.addMenu('Sourced as (whole section)')
            for key, lab in self.model.sensor_choices():
                sub.addAction(lab).triggered.connect(lambda _c=False, k=key: self.sensor_section(k))
        self._popup(menu, gpos)

    def goto_row(self, key):
        self.model.select(key, 'nominal')
        self.sync()
        self.raise_()
        self.activateWindow()

    def sheet_key(self, keysym, char='', shift=False, ctrl=False):
        if ctrl:
            return None
        act = self.model.nav(keysym, shift=shift)
        if act == 'moved':
            self.sync()
            return 'break'
        if act == 'edit':
            self.focus_bar(select_all=True)
            return 'break'
        if keysym in ('Delete', 'BackSpace'):
            self.changed(self.model.clear_cell())
            return 'break'
        if char and char.isprintable() and not char.isspace() or char == ' ':
            ok, why = self.model.cell_editable()
            if not ok:
                self.set_issue(self.model.selected_row(), False, why, fresh=True)
                return 'break'
            self.bar.setText(char)
            self.focus_bar()
            return 'break'
        return None

    def focus_bar(self, select_all=False):
        if self.model.sel_col == 'standard':                        # Enter / F2 / double-click on a STANDARD cell opens its drop-down instead of the Edit Cell bar
            return self.open_standard_menu()
        ok, why = self.model.cell_editable()
        if not ok:
            self.set_issue(self.model.selected_row(), False, why, fresh=True)
            return
        self.bar.setFocus()
        if select_all:
            self.bar.selectAll()
        else:
            self.bar.setCursorPosition(len(self.bar.text()))

    def commit_bar_if_changed(self):
        if self.bar.text() != self.model.cell_text() and self.model.cell_editable()[0] and (self._bar_typed or self.bar.hasFocus()):
            self.commit_bar('stay')

    def commit_bar(self, move='down'):
        """Enter (down) or Tab (right) in the Edit Cell bar."""
        ok, why = self.model.cell_editable()
        if not ok:
            self.set_issue(self.model.selected_row(), False, why, fresh=True)
            return None
        res = self.model.commit_cell(self.bar.text(), move=move)
        self.changed(res)
        self.sheet.setFocus()
        return res

    def cancel_bar(self):
        self.bar.setText(self.model.cell_text())
        self.sheet.setFocus()

    # ---- header strip
    def commit_header(self):
        ds = self.model.ds
        new = dict(make=self.make_e.text().strip(), model=self.model_e.text().strip(), title=self.title_e.text().strip())
        if new == dict(make=ds.make, model=ds.model, title=ds.title):
            return None
        return self.changed(self.model.set_header(**new))

    # ---- the buttons
    def calc(self):
        self.commit_header()
        form = self.panel_box.form()
        form.update(remark=self.remark_v.get(), run=bool(self.run_v.get()))
        out = self.model.calc_row(form=form)
        self._keep_typed = not out.ok            # a refused Calc leaves what was typed in the boxes, so it can be corrected
        try:
            return self.changed(out)
        finally:
            self._keep_typed = False

    def recalc(self):
        return self.changed(self.model.recalc_all())

    def clear_typed_limits(self):
        return self.changed(self.model.clear_typed_limits())

    def copy_down(self):
        if self.model.selected_row()['kind'] == 'blank':             # a new row: take the tolerance of the row above into the boxes (the sheet is not touched)
            return self.changed(self.model.use_tolerance_above())
        n = self.model.would_overwrite()
        if n and not C.ask_yes_no(self, 'Copy tolerance', f'{n} row(s) below already have a tolerance of their own. Replace them with this row\'s tolerance? (Undo brings them back.)'):
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
        target = QApplication.focusWidget()
        entry = target if isinstance(target, QLineEdit) and not target.isReadOnly() and target.window() is self else self.bar
        entry.insert(sym)
        if entry is self.bar:
            self.bar.setFocus()
        QGuiApplication.clipboard().setText(sym)
        return sym

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
        return present(win)

    def preview(self):
        return present(PreviewWindow(self))

    def template_chosen(self, index=None):
        """The Templates drop-down: add the chosen template's empty sections (no question: Undo takes them out again), then go back to the prompt."""
        i = self.template_box.currentIndex() if index is None else index
        name = self.template_box.itemText(i) if i > 0 else ''
        self.template_box.setCurrentIndex(0)
        if not name:
            return None
        res = self.model.add_template(name)
        return self.changed(res)

    def add_handheld(self):
        """More > Add handheld functions...: the handheld multimeter sections this sheet does not have yet."""
        missing = [t['name'] for t in self.model.handheld_template() if not t['present']]
        if not missing:
            return self.changed(M.Outcome(False, 'The sheet already has a section for every handheld function.'))
        if not C.ask_yes_no(self, 'Add handheld functions', 'Add an empty section for each of these?\n\n' + ', '.join(missing)
                            + '\n\nSections you already have stay as they are. Undo takes them out again.'):
            return None
        return self.changed(self.model.add_handheld_functions())

    def run_sheet(self, demo=False):
        """Run / Try in demo: save the sheet (asking first when it has unsaved changes), then start it in its own process like the Procedures list does.
        A sheet with problems is never run: the warnings list opens instead."""
        self.commit_header()
        m = self.model
        if m.problem_counts()['errors']:
            self.show_problems()
            return self.changed(M.Outcome(False, 'This sheet has problems to fix before it can run. The warnings list shows them.'))
        blocked = self.check_blocks_run()                      # the build rules (Sheet check): an error there stops the run, demo or real
        if blocked:
            return self.changed(M.Outcome(False, blocked))
        self._accepted_unverified = ''
        if not demo and not self.confirm_real_run():
            return self.changed(M.Outcome(False, 'Not started: the run on real instruments was not confirmed.'))
        if m.dirty or not m.ds.uid:
            if not C.ask_yes_no(self, 'Save before running', 'The suite runs the SAVED datasheet. Save this one now and ' + ('try it in demo?' if demo else 'run it?')):
                return None
            res = self.save()
            if not res.ok:
                return res
        entry = next((e for e in m.storage.entries() if e['uid'] == m.ds.uid), None)
        if entry is None:
            return self.changed(M.Outcome(False, 'This datasheet is not a runnable saved procedure yet. Save it first and fix what the warnings list shows.'))
        line = m.automation_line()
        if self._accepted_unverified and not demo:               # the operator accepted the list of unverified commands in the question: the run does not ask again
            entry = dict(entry, accepted_unverified=self._accepted_unverified)
        try:
            import dsb_manager
            (self.launcher or dsb_manager.launch_process)(entry, demo=demo)
        except OSError as exc:
            return self.changed(M.Outcome(False, f'The procedure could not be started ({exc}).'))
        return self.changed(M.Outcome(True, f'Launched {entry["name"]}' + (' in demo mode (virtual instruments).' if demo else '.') + ' ' + line))

    # ---- the other windows
    def _page(self, title, cls, **kw):
        dlg = PageDialog(self, title, cls, **kw)
        self.dialogs.append(dlg)
        return present(dlg)

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
        return present(DriversWindow(self, self.model))

    def open_versions(self):
        if not self.model.ds.uid:
            return self.changed(M.Outcome(False, 'Nothing to show yet: save the datasheet once first.'))
        return present(VersionsWindow(self, self.model.storage, self.model.ds.uid, editor=self, panel=self.panel))

    def open_calculator(self, rule_id=None):
        fn = self.model.fn()
        if fn is None:
            return self.changed(M.Outcome(False, 'Click a row (or choose a function) first: the calculator makes rows for one section.'))
        if not fn.ranges:
            return self.changed(M.Outcome(False, 'This section has no ranges yet. Add a test row first (its range follows from its value), or open More > Ranges.'))
        dlg = RuleDialog(self, self.model, fn.id, rule_id)
        dlg.run()
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
            items = self.model.save_blockers()
            choice = self.ask_save_blocked(items) if items else ('draft' if C.ask_yes_no(self, 'Save as a draft?', res.message + '\n\nSave it as a draft now?') else 'edit')
            if choice == 'draft':
                res = self.model.save_sheet(note, as_draft=True)
            else:
                if choice == 'go':
                    if self._blocked_key:
                        self.goto_row(self._blocked_key)
                    else:                                      # a problem of the header (make, model, title): the boxes at the top
                        self.make_e.setFocus()
                return self.changed(res)
        self.changed(res)
        if res.ok:
            self.saved()
        return res

    _blocked_key = ''

    def ask_save_blocked(self, items):
        """The list of what to fix before Save can make a runnable procedure: 'go' (a row was chosen), 'draft' or 'edit'.  A seam the tests replace."""
        dlg = SaveBlockedDialog(self, items)
        choice = dlg.run() or 'edit'
        self._blocked_key = dlg.chosen_key
        return choice

    def saved(self):
        if self.panel is not None:
            self.panel.editor_saved(self)

    # ---- remembered layout (window size / position, row panel open or hidden, which panel sections are open)
    def _layout_state(self):
        return {'inspector_open': bool(self._insp_open), 'sections': {s.title: bool(s.open) for s in self.panel_box.findChildren(Section)}}

    def _restore_layout(self):
        extra = layouts.restore('datasheet_builder', self)
        if 'inspector_open' in extra:
            self._insp_open, self._insp_manual = bool(extra['inspector_open']), True
            self._set_inspector_width()
        opened = extra.get('sections') or {}
        for sec in self.panel_box.findChildren(Section):
            if sec.title in opened and sec.open != bool(opened[sec.title]):
                sec.set_open(opened[sec.title])

    def closeEvent(self, ev):
        self.commit_header()
        if self.model.dirty and not C.ask_yes_no(self, 'Unsaved changes', 'This datasheet has changes that are not saved. Close without saving?'):
            ev.ignore()
            return
        for d in list(self.dialogs):
            try:
                d.close()
            except RuntimeError:
                pass
        layouts.save('datasheet_builder', self, extra=self._layout_state())
        if self.panel is not None:
            self.panel.editor_closed(self)
        ev.accept()


class _BarKeys(QObject):
    """Tab in the Edit Cell bar commits and goes right; Esc puts the old text back."""

    def __init__(self, win):
        super().__init__(win.bar)
        self.win = win

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Tab,):
                self.win.commit_bar('right')
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.win.cancel_bar()
                return True
        return False
