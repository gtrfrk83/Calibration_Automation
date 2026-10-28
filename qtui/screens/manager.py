"""The Qt Calibration Procedure Manager (port of Calibration_Procedure_Manager.Manager): menu bar, header, the main tabs (Procedures with its three views,
Asset History, Standards Specs, Datasheet Builder), the table of procedures, the Selected-procedure card, the status bar with 'Find instruments...'.

    from qtui.screens.manager import ManagerWindow
    win = ManagerWindow()                  # the registry / launch rules come from manager_model.ManagerCore; the three hosted panels from qtui.screens.PANELS
    win.show()

Behaviour, handlers, menu items, accelerators and status texts are the Tk Manager's; the database, list, card and launch rules are manager_model.py (shared with
the Tk Manager).  Run / Try in demo mode start the procedure exactly as the Tk Manager does (subprocess.Popen of `python <script> [--demo [--fast-demo]]` in the
script's folder; the child inherits CALSUITE_UI, which picks its toolkit, see ui_port.select_toolkit).  `launcher(args, cwd=...)` can be replaced (tests).
No Tk import."""
from __future__ import annotations

import inspect
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

import dsb_manager
import manager_model as mm
import packages
import procedure_menu
import procscan
import suite_info
import verified
from qtui import app, layouts, theme
from qtui.screens import PANELS, find_instruments, help_menu, load_panel
from qtui.screens import manager_dialogs as dialogs
from qtui.table import Column, DataTable
from qtui.theme import M
from qtui.widgets import (Badge, Banner, EmptyState, GhostButton, PrimaryButton, SearchField, SecondaryButton, StatusLine, label, make_tab_bar, rule)

TITLE = 'Calibration Procedure Manager'
SUBTITLE = 'Run, document and maintain your calibration procedures'
MAIN_TABS = (('procedures', 'Procedures'), ('asset_history', 'Asset History'), ('standards_specs', 'Standards Specs'), ('datasheet_builder', 'Datasheet Builder'), ('uncertainty_calc', 'Uncertainty\nCalculator'), ('procedure_generator', 'Procedure\nGenerator'))
PANEL_TITLES = {'asset_history': 'Asset History', 'standards_specs': 'Standards Specs', 'datasheet_builder': 'Datasheet Builder', 'uncertainty_calc': 'Uncertainty Calculator', 'procedure_generator': 'Procedure Generator'}


class StatusProxy:
    """The Manager's status text: `.set(text)` / `.get()` like the Tk StringVar the panels were given, and callable (`status(text)`)."""

    def __init__(self, line: StatusLine, text=''):
        self._line, self._text = line, ''
        self.set(text)

    def set(self, text):
        self._text = str(text)
        self._line.set(self._text)

    def get(self):
        return self._text

    __call__ = set


def _default_launcher(args, cwd=None):
    return subprocess.Popen(args, cwd=cwd)


class VerificationPopup(QFrame):
    """The full verification record under the info button: selectable text, closes on Esc or a click elsewhere."""

    def __init__(self, text, anchor: QWidget):
        super().__init__(anchor.window(), Qt.WindowType.Popup)
        self.setProperty('surface', 'popover')
        v = QVBoxLayout(self)
        v.setContentsMargins(M.md, M.sm, M.md, M.sm)
        self.box = QPlainTextEdit(text)
        self.box.setReadOnly(True)
        self.box.setFrameShape(QFrame.Shape.NoFrame)
        self.box.setStyleSheet('background: transparent;')
        self.box.setFixedWidth(420)
        lines = sum(len(x) // 52 + 1 for x in text.split('\n'))
        self.box.setFixedHeight(min(16, max(3, lines)) * (self.box.fontMetrics().lineSpacing()) + 24)
        v.addWidget(self.box)
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        scr = (anchor.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = min(pos.x(), scr.right() - self.width() - 8)
        y = pos.y()
        if y + self.height() > scr.bottom() - 8:
            y = max(scr.top(), anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4)
        self.move(max(scr.left(), x), y)


class _ShareWidth(QObject):
    """Keeps the procedure list readable in a wide window: the width beyond `base` is shared between the columns by `weights` (the last column, which
    stretches, keeps the rest), so the list does not become one huge Procedure column with the others pushed to the far right."""
    MIN = (215, 108, 74, 118, 64)                              # what each column shrinks to in a narrow window, so the last column stays on screen

    def __init__(self, table, base_widths, weights):
        super().__init__(table)
        self.table, self.base, self.weights = table, base_widths, weights
        table.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        try:
            hh = self.table.horizontalHeader()
            vw = self.table.viewport().width()
            extra = max(0, vw - sum(self.base) - 220)
            squeeze = 0.0
            if vw - 96 < sum(self.base):                           # narrow: shrink toward MIN so the 'Verified on hardware' column keeps ~96 px
                squeeze = min(1.0, (sum(self.base) - (vw - 96)) / max(1, sum(self.base) - sum(self.MIN)))
            for i, (w, k) in enumerate(zip(self.base, self.weights)):
                hh.resizeSection(i, int(w + extra * k - (w - self.MIN[i]) * squeeze))
        except RuntimeError:
            pass                                                   # the table went away


class ManagerWindow(QMainWindow):
    view_kind = procscan.KIND_VERIFICATION

    def __init__(self, core: mm.ManagerCore | None = None, launcher=None, panels: dict | None = None, parent=None):
        super().__init__(parent)
        self.core = core or mm.ManagerCore()
        self.launcher = launcher or _default_launcher
        self.panel_registry = dict(PANELS if panels is None else panels)
        self.demo = False
        self.setWindowTitle(TITLE)
        self.setAcceptDrops(True)
        self.resize(1260, 800)
        self.setMinimumSize(900, 580)
        self._ver_pop = None
        self._row_menu = None
        self._readiness_window = None
        self.find_window = None
        self.panels = {}
        self._panel_notes = {}

        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(M.page_margin, M.lg, M.page_margin, M.sm)
        page.setSpacing(M.md)

        # ---- header
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = label(TITLE, 'title')
        col.addWidget(self.title_label)
        col.addWidget(label(SUBTITLE, 'sub'))
        head.addLayout(col)
        head.addStretch(1)
        self.db_chip = label('Database: ' + self.core.db.name, 'chip')
        head.addWidget(self.db_chip, 0, Qt.AlignmentFlag.AlignTop)
        page.addLayout(head)

        # ---- status bar first: build_* use self.status
        self.statusbar = QStatusBar()
        self.statusbar.setSizeGripEnabled(False)
        self.setStatusBar(self.statusbar)
        self.status_line = StatusLine()
        self.status = StatusProxy(self.status_line, mm.START_STATUS)
        self.statusbar.addWidget(self.status_line, 1)
        self.btn_find = SecondaryButton('Find instruments...', on_click=self.find_instruments)       # a tool for every tab
        self.statusbar.addPermanentWidget(self.btn_find)
        self.version_label = label(mm.VERSION, 'hint')
        self.version_label.setContentsMargins(0, 0, M.md, 0)
        self.statusbar.addPermanentWidget(self.version_label)

        # ---- main tabs
        self.tabs = make_tab_bar([t for _k, t in MAIN_TABS])
        self.tabs.setAccessibleName('Main tabs')
        self.tabs.setProperty('tall', any('\n' in t for _k, t in MAIN_TABS))          # room for the two-line 'Uncertainty / Calculator' label
        self.stack = QStackedWidget()
        page.addWidget(self.tabs)
        page.addWidget(self.stack, 1)
        self.library_page = QWidget()
        self.stack.addWidget(self.library_page)
        self.page_of = {'procedures': self.library_page}
        for key in ('asset_history', 'standards_specs', 'datasheet_builder', 'uncertainty_calc', 'procedure_generator'):
            holder = QWidget()
            QVBoxLayout(holder).setContentsMargins(0, M.sm, 0, 0)
            self.stack.addWidget(holder)
            self.page_of[key] = holder
        self.build_menus()
        self.build_library_tab()
        for key in ('asset_history', 'standards_specs', 'datasheet_builder', 'uncertainty_calc', 'procedure_generator'):
            self.build_panel(key)
        help_menu.dress(self)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.refresh()
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.focus_search)
        self.table.setFocus()
        self._first_tab = QTimer(self)
        self._first_tab.setSingleShot(True)
        self._first_tab.timeout.connect(lambda: self._tab_changed(0))
        layouts.restore('manager', self)
        self._first_tab.start(0)                # the Tk notebook reports its first tab once it is shown: the status line then reads the tab's own text

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, 'card_column'):
            self.card_column.setFixedWidth(max(356, min(396, int(self.width() * 0.26) + 16)))        # the card is a little wider on a wide window; the table keeps the rest

    def closeEvent(self, ev):
        layouts.save('manager', self)
        self._first_tab.stop()
        if self.find_window is not None and hasattr(self.find_window, 'close'):
            self.find_window.close()
        if getattr(self, 'driver_verify_window', None) is not None:
            self.driver_verify_window.close()
        super().closeEvent(ev)

    def apply_settings(self):
        """File > Settings: the demo buttons are shown unless the person switched them off."""
        import app_settings
        show = app_settings.get(app_settings.SHOW_DEMO)
        self.btn_demo.setVisible(show)
        self.fast_demo_box.setVisible(show)

    # ------------------------------------------------------------------ menus
    def build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu('&File')
        self.act_driver_verify = QAction('&Driver verification...', self)
        self.act_driver_verify.triggered.connect(lambda _c=False: self.driver_verification())
        file_menu.addAction(self.act_driver_verify)
        file_menu.addSeparator()
        self.act_exit = QAction('E&xit', self)
        self.act_exit.setShortcut(QKeySequence('Ctrl+Q'))
        self.act_exit.triggered.connect(self.close)
        file_menu.addAction(self.act_exit)
        self.file_menu = file_menu
        # the Library menu sits immediately left of Help (Help is added by help_menu.dress afterwards); Alt+L
        menu = self.library_menu = bar.addMenu('&Library')
        self.library_actions = {}

        def add(key, text, fn):
            a = QAction(text, self)
            a.triggered.connect(lambda _c=False: fn())
            menu.addAction(a)
            self.library_actions[key] = a
            return a
        add('mdd', 'Import Mudcats datasheet (.mdd)...', self.import_mdd_procedure)
        add('package', 'Import procedure package...', self.import_package)
        add('export', procedure_menu.EXPORT_LABEL, self.export_package)
        add('register', 'Register procedure...', self.add)
        menu.addSeparator()
        self.library_info = QAction('Library folder: ', self)                  # info line (text refreshed when the menu opens)
        self.library_info.setEnabled(False)
        menu.addAction(self.library_info)
        self.library_actions['info'] = self.library_info
        add('folder', 'Library folder...', self.choose_library_folder)
        menu.addSeparator()
        add('remove', 'Remove from library', self.remove)
        menu.aboutToShow.connect(self.refresh_library_menu)
        self.refresh_library_menu()

    def refresh_library_menu(self):
        """Enabled states when the menu opens: Remove from library needs a selected procedure; the info line shows the current library folder."""
        self.library_info.setText('Library folder: ' + self.core.library_folder_text())
        self.library_actions['remove'].setEnabled(hasattr(self, 'table') and self.selected_iid() is not None)
        rec = self._selected_row() if hasattr(self, 'table') else None
        self.library_actions['export'].setEnabled(bool(rec) and self.core.exportable(rec))

    # ------------------------------------------------------------------ panels hosted from other modules
    def build_panel(self, key):
        holder = self.page_of[key]
        lay = holder.layout()
        title = PANEL_TITLES[key]
        try:
            cls = load_panel_from(self.panel_registry, key)
        except ModuleNotFoundError as exc:
            if exc.name and not self.panel_registry[key].partition(':')[0].startswith(exc.name):
                note = EmptyState(f'{title} could not be loaded', f'Missing module: {exc.name}', icon_name='warn')           # a real import error inside the panel
            else:
                note = EmptyState(f'{title} is not built yet', 'The Qt version of this tab has not been added to this build; the Tk Manager still has it.')
        except KeyError:
            note = EmptyState(f'{title} is not registered', 'qtui.screens.PANELS has no entry for this tab.', icon_name='warn')
        except (ImportError, AttributeError) as exc:
            note = EmptyState(f'{title} could not be loaded', str(exc), icon_name='warn')
        else:
            kwargs = {}
            params = inspect.signature(cls.__init__).parameters
            if 'on_saved' in params and key in ('datasheet_builder', 'procedure_generator'):         # a saved / built / approved procedure changes the Procedures list
                kwargs['on_saved'] = self._dsb_saved
            if 'status' in params:
                kwargs['status'] = self.status
            try:
                panel = cls(holder, **kwargs)
            except Exception as exc:                                     # one broken tab never takes the Manager down
                note = EmptyState(f'{title} could not be built', f'{type(exc).__name__}: {exc}', icon_name='warn')
            else:
                self.panels[key] = panel
                lay.addWidget(panel, 1)
                return panel
        self._panel_notes[key] = note
        lay.addWidget(note, 1)
        return None

    @property
    def history_panel(self):
        return self.panels.get('asset_history')

    @property
    def specs_panel(self):
        return self.panels.get('standards_specs')

    @property
    def dsb_panel(self):
        return self.panels.get('datasheet_builder')

    def _dsb_saved(self):
        """A datasheet was saved, deleted, restored or imported: the Procedures list is refreshed (the runnable spec has changed)."""
        self.refresh()

    def _tab_changed(self, index):
        key = MAIN_TABS[index][0]
        self.stack.setCurrentWidget(self.page_of[key])
        if key == 'procedures':
            self.refresh_details()
        else:
            panel = self.panels.get(key)
            if panel is not None and hasattr(panel, 'refresh'):
                panel.refresh()
        self.status.set(mm.TAB_STATUS[key])

    def set_demo_history(self, on):
        """Help > Show demonstration asset history: the Asset History tab reads the fictional demo file (read only, banner on top) instead of the real
        history.  Never remembered: every start shows the real history.  Returns the state afterwards; the Help item always agrees with it."""
        panel = self.history_panel
        if panel is None or not hasattr(panel, 'set_demo'):
            state = False
        else:
            state = panel.set_demo(bool(on))
        act = getattr(self, 'help_actions', {}).get('demo_history')
        if act is not None and act.isChecked() != state:
            act.blockSignals(True)
            act.setChecked(state)
            act.blockSignals(False)
        if state:
            self.select_tab('asset_history')
            self.status.set('Showing DEMONSTRATION asset history: fictional assets, not real calibration records. Turn it off in the Help menu.')
        else:
            self.status.set(mm.TAB_STATUS['asset_history'] if self.tabs.currentIndex() == 1 else mm.START_STATUS)
        return state

    def select_tab(self, key):
        self.tabs.setCurrentIndex([k for k, _t in MAIN_TABS].index(key))

    def focus_search(self):
        self.select_tab('procedures')
        self.search.setFocus()

    # ------------------------------------------------------------------ Procedures tab
    def build_library_tab(self):
        outer = QVBoxLayout(self.library_page)
        outer.setContentsMargins(0, M.sm, 0, 0)
        outer.setSpacing(M.md)
        self.view_bar = make_tab_bar([t for _k, t in mm.VIEW_TABS], sub=True)
        self.view_bar.setAccessibleName('Procedure views')
        self.view_bar.currentChanged.connect(self._view_changed)
        outer.addWidget(self.view_bar)
        self.view_notes = {procscan.KIND_ADJUSTMENT: Banner(mm.ADJUSTMENT_NOTE, 'warn'), procscan.KIND_MANUAL: Banner(mm.MANUAL_NOTE, 'info')}
        for note in self.view_notes.values():
            note.hide()
            outer.addWidget(note)
        self.adjust_note = self.view_notes[procscan.KIND_ADJUSTMENT]

        bar = QHBoxLayout()
        bar.setSpacing(M.sm)
        bar.addWidget(label('Find'))
        self.search = SearchField('Search procedures', delay_ms=0)
        self.search.setFixedWidth(260)
        self.search.queryChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search)
        self.category_box = QComboBox()
        self.category_box.setFixedWidth(220)
        self.category_box.addItem(mm.ALL_CATEGORIES)
        self.category_box.activated.connect(lambda _i: self.refresh())
        bar.addWidget(self.category_box)
        self.btn_clear = SecondaryButton('Clear', on_click=self.clear_filters)
        bar.addWidget(self.btn_clear)
        bar.addStretch(1)
        outer.addLayout(bar)

        split = QHBoxLayout()
        split.setSpacing(M.lg)
        cols = [Column('name', 'Procedure', 235, getter=lambda r: r.name, tone=lambda r: 'bad' if not r.found else 'warn' if r.n_mod else None),
                Column('manufacturer', 'Manufacturer', 112, getter=lambda r: r.manufacturer),
                Column('model', 'Model', 90, getter=lambda r: r.model),
                Column('category', 'Category', 150, getter=lambda r: r.category),
                Column('ready', 'Status', 80, getter=lambda r: r.status, tone=lambda r: 'bad' if not r.found else 'warn' if r.n_mod else 'good'),
                Column('verified', 'Verified on hardware', 185, stretch=True, getter=lambda r: r.verified,
                       tone=lambda r: 'good' if 'verified' in r.tags else 'warn' if r.vkind in ('changed', 'unlocked') else 'muted')]
        self.table = DataTable(cols, [], row_key=lambda r: r.iid, multi=False, empty_text=mm.EMPTY_LIBRARY)
        self.table.setMinimumWidth(480)
        self._share = _ShareWidth(self.table, (285, 112, 90, 150, 80), (0.30, 0.12, 0.08, 0.15, 0.08))   # a wide window shares its extra width between the columns
        self.table.selectionChangedRows.connect(lambda _r: self.refresh_details())
        self.table.rowActivated.connect(lambda _r: self.run_selected())
        # the right-click menu of a row replaces the table's own copy menu (Menu key / Shift+F10 reach the same slot)
        self.table.customContextMenuRequested.disconnect()
        self.table.customContextMenuRequested.connect(self._row_menu_pointer)
        split.addWidget(self.table, 1)
        split.addWidget(self.build_card())
        outer.addLayout(split, 1)

    def build_card(self):
        column = self.card_column = QWidget()
        column.setFixedWidth(376)
        cv = QVBoxLayout(column)
        cv.setContentsMargins(4, 0, 12, 14)                  # room around the card for its soft shadow (Appearance > Depth)
        cv.setSpacing(M.sm)
        cv.addWidget(label('Selected procedure', 'section'))
        card = self.card = QFrame()
        card.setProperty('surface', 'card')
        card.setObjectName('procedure_card')
        v = QVBoxLayout(card)
        v.setContentsMargins(M.lg, M.lg, M.lg, M.md)
        v.setSpacing(M.sm)
        # the title, description and file info scroll when the window is too short; Run / demo and the verification buttons are pinned below them
        scroll = self.card_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }')
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(M.sm)
        self.d_name = label('', 'h2', wrap=True)
        self.d_sub = label('', 'sub', wrap=True)
        self.d_pill = Badge('', 'neutral')
        self.d_mod = Badge('', 'warn')
        self.d_desc = label('', wrap=True)
        self.d_path = label('', 'hint', wrap=True)
        for w in (self.d_name, self.d_sub):
            bv.addWidget(w)
        chips = QHBoxLayout()
        chips.addWidget(self.d_pill)
        chips.addWidget(self.d_mod)
        chips.addStretch(1)
        bv.addLayout(chips)
        bv.addWidget(self.d_desc)
        bv.addWidget(self.d_path)
        bv.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        pinned = QVBoxLayout()
        pinned.setSpacing(M.sm)
        pinned.addWidget(rule())
        ver_row = QHBoxLayout()
        self.d_ver = Badge('', 'neutral', small=True)                              # 'VERIFIED ON HARDWARE <date> - LOCKED' / 'CHANGED SINCE' / 'UNLOCKED' / 'NOT VERIFIED'
        self.d_ver_text = ''                                           # the full text (verified.Status.detail_lines): shown by the info button, not on the card
        self.btn_ver_info = QPushButton('i')
        self.btn_ver_info.setProperty('role', 'info')
        self.btn_ver_info.setAccessibleName('Show the full verification record')
        self.btn_ver_info.setToolTip('Show the full verification record')
        self.btn_ver_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ver_info.setAutoDefault(False)
        self.btn_ver_info.clicked.connect(lambda _c=False: self.show_verified_details())
        ver_row.addWidget(self.d_ver)
        ver_row.addWidget(self.btn_ver_info)
        ver_row.addStretch(1)
        pinned.addLayout(ver_row)
        run_row = QHBoxLayout()
        run_row.setSpacing(M.sm)
        self.btn_run = PrimaryButton('▶ Run', on_click=self.run_selected)
        self.btn_demo = SecondaryButton('Try in demo mode', on_click=lambda: self.run_selected(demo=True))
        self.btn_run.setToolTip(mm.RUN_TIP)
        self.btn_demo.setToolTip(mm.DEMO_EXPLANATION)
        run_row.addWidget(self.btn_run, 2)
        run_row.addWidget(self.btn_demo, 3)
        pinned.addLayout(run_row)
        self.fast_demo_box = QCheckBox('Fast demo (no windows)')                # demo without windows or commands (the old quick demo)
        pinned.addWidget(self.fast_demo_box)
        self.apply_settings()
        pinned.addWidget(label(mm.RUN_HINT, 'hint', wrap=True))
        ver_btns = QHBoxLayout()
        ver_btns.setSpacing(M.sm)
        self.btn_verify = SecondaryButton('Mark verified...', on_click=self.mark_verified)
        self.btn_lock = SecondaryButton('Unlock...', on_click=self.toggle_lock)
        self.btn_verify.full_text = self.btn_lock.full_text = ''
        ver_btns.addWidget(self.btn_verify, 1)
        ver_btns.addWidget(self.btn_lock, 1)
        pinned.addLayout(ver_btns)
        gen_btns = QHBoxLayout()                                    # only for a procedure from the Procedure Generator (shown by refresh_details)
        gen_btns.setSpacing(M.sm)
        self.btn_approve = PrimaryButton('Approve (owner)...', on_click=self.approve_generated)
        self.btn_draft_again = SecondaryButton('Mark as draft again...', on_click=self.draft_again_generated)
        for b in (self.btn_approve, self.btn_draft_again):
            b.hide()
            gen_btns.addWidget(b, 1)
        pinned.addLayout(gen_btns)
        v.addLayout(pinned)
        cv.addWidget(card, 1)
        return column

    @property
    def fast_demo(self):
        return self.fast_demo_box.isChecked()

    @property
    def category(self):
        return self.category_box.currentText() or mm.ALL_CATEGORIES

    def clear_filters(self):
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.category_box.setCurrentIndex(0)
        self.refresh()

    def _view_changed(self, index):
        kind = mm.VIEW_TABS[index][0]
        if kind == self.view_kind:
            return
        self.view_kind = kind
        self.category_box.setCurrentIndex(0)                    # the category list belongs to the view
        for k, note in self.view_notes.items():
            note.setVisible(k == kind)
        self.refresh()

    def select_view(self, kind):
        self.view_bar.setCurrentIndex([k for k, _t in mm.VIEW_TABS].index(kind))

    # ------------------------------------------------------------------ the list and the card
    def selected_iid(self):
        rows = self.table.selected_rows()
        return rows[0].iid if rows else None

    def _selected_row(self):
        return self.core.row_record(self.selected_iid())

    def refresh(self):
        keep = self.selected_iid()
        state = self.core.list_state(self.view_kind, self.search.text(), self.category)
        cats = [mm.ALL_CATEGORIES] + state.categories
        self.category_box.blockSignals(True)
        self.category_box.clear()
        self.category_box.addItems(cats)
        self.category_box.setCurrentIndex(cats.index(state.category))
        self.category_box.blockSignals(False)
        self.table.empty_text = state.empty_text
        self.table.set_rows(state.rows, keep_selection=False)
        self.table.viewport().update()
        row = next((r for r in state.rows if r.iid == keep), None) or (state.rows[0] if state.rows else None)
        if row is not None:
            self.table.select_rows([row])
            self.table.scroll_to_row(row)
        self.refresh_details()
        self.status.set(state.status)

    def refresh_details(self):
        rec = self._selected_row()
        c = self.core.card(rec)
        self.d_name.setText(c.name)
        self.d_sub.setText(c.sub)
        self.d_desc.setText(c.desc)
        self.d_path.setText(c.path)
        self.d_pill.set(c.ready_text, c.ready_tone)
        self.d_pill.setVisible(bool(c.ready_text))
        self.btn_run.setEnabled(c.run_enabled)
        self.btn_demo.setEnabled(c.run_enabled)
        self.d_mod.set(c.mod_text, 'warn')
        self.d_mod.setVisible(bool(c.mod_text))                    # 'MODIFIED (n)': saved model-wide procedure changes exist
        self.d_ver.set(c.ver_pill, c.ver_tone)
        self.d_ver.setVisible(bool(c.ver_pill))
        self.d_ver_text = c.ver_text
        self.btn_ver_info.setEnabled(c.info_enabled)
        for button, text, full, enabled in ((self.btn_verify, c.verify_text, c.verify_full, c.verify_enabled), (self.btn_lock, c.lock_text, c.lock_full, c.lock_enabled)):
            button.full_text = full                                  # the full wording (tooltip, row menu); the card button shows the short one
            if text:
                button.setText(text)
            button.setToolTip(full)
            button.setEnabled(enabled)
        if not rec:
            self.btn_verify.setEnabled(False)
            self.btn_lock.setEnabled(False)
        gen = self.generated_state()
        self.btn_approve.setVisible(bool(gen and gen[1].draft))              # never offered for a procedure that was not generated
        self.btn_draft_again.setVisible(bool(gen and not gen[1].draft))
        return c

    # ------------------------------------------------------------------ owner approval of a generated procedure (Procedure Generator)
    def generated_state(self):
        """(uid, generated_draft.State) of the selected procedure when it was made by the Procedure Generator, else None."""
        iid = self.selected_iid()
        if iid is None or not dsb_manager.is_user_iid(iid):
            return None
        import generated_draft
        uid = str(iid)[len(dsb_manager.IID_PREFIX):]
        st = generated_draft.state(uid)
        return (uid, st) if st.generated else None

    def _generated_done(self, st, text):
        self.refresh()
        self.status.set(text)

    def approve_generated(self):
        gen = self.generated_state()
        if gen is None or not gen[1].draft:
            return None
        from qtui.screens import procedure_generator as pgen
        rec = self._selected_row()
        new = pgen.run_approve(self, gen[0], str(rec[1]) if rec else '')
        if new is not None:
            self._generated_done(new, f'Approved by {new.approved_by}. Later runs and reports no longer carry the draft marking.')
        return new

    def draft_again_generated(self):
        gen = self.generated_state()
        if gen is None or gen[1].draft:
            return None
        from qtui.screens import procedure_generator as pgen
        rec = self._selected_row()
        new = pgen.run_draft_again(self, gen[0], str(rec[1]) if rec else '')
        if new is not None:
            self._generated_done(new, 'Marked as a draft again: later runs ask for confirmation and every report page carries the banner.')
        return new

    # ------------------------------------------------------------------ right-click menu of a procedure row
    def _row_menu_pointer(self, pos):
        """Right click (pos in the table viewport) or the Menu key / Shift+F10 (the keyboard: the menu opens on the selected row)."""
        index = self.table.indexAt(pos)
        if index.isValid():
            self.table.select_rows([self.table.row_of(index)])
            self.refresh_details()                              # the card and the buttons follow the row right away (the menu reads their state)
            anchor = pos
        else:
            if self.selected_iid() is None:
                return None
            cur = self.table.currentIndex()
            rect = self.table.visualRect(cur) if cur.isValid() else None
            anchor = QPoint(24, (rect.bottom() if rect else 24))
            self.refresh_details()
        return self.post_row_menu(self.table.viewport().mapToGlobal(anchor))

    def row_menu_items(self):
        rec = self._selected_row()
        if not rec:
            return None
        return self.core.row_menu_items(rec, self.refresh_details())

    def build_row_menu(self):
        entries = self.row_menu_items()
        if entries is None:
            return None
        actions = {procedure_menu.RUN: self.run_selected, procedure_menu.DEMO: lambda: self.run_selected(demo=True), procedure_menu.READINESS: self.readiness_check,
                   procedure_menu.VERIFY: self.mark_verified, procedure_menu.LOCK: self.toggle_lock, procedure_menu.REMOVE: self.remove, procedure_menu.EXPORT: self.export_package,
                   procedure_menu.RESTORE: self.restore_previous, procedure_menu.COPY_NAME: self.copy_procedure_name,
                   procedure_menu.COPY_PATH: self.copy_procedure_path, procedure_menu.SHOW: self.show_procedure_location}
        menu = QMenu(self.table)
        for e in entries:
            if e is None:
                menu.addSeparator()
            else:
                act = menu.addAction(e.label)
                act.setEnabled(bool(e.enabled))
                act.setData(e.key)
                act.triggered.connect(lambda _c=False, fn=actions[e.key]: fn())
        gen = self.generated_state()
        if gen is not None:                                          # only a procedure from the Procedure Generator
            menu.addSeparator()
            act = menu.addAction('Approve (owner)...' if gen[1].draft else 'Mark as draft again...')
            act.setData('approve' if gen[1].draft else 'draft_again')
            act.triggered.connect(lambda _c=False: self.approve_generated() if gen[1].draft else self.draft_again_generated())
        menu.addSeparator()
        act = menu.addAction('Open manual...')
        act.setData('open_manual')
        act.triggered.connect(lambda _c=False: self.open_manual())
        return menu

    def open_manual(self):
        """The selected procedure's instrument manual (PDF), in the suite's own viewer.  Manuals are found by model number in manuals.folders()."""
        rec = self._selected_row()
        if not rec:
            return None
        from qtui import manual_viewer
        return manual_viewer.open_for_model(self, str(rec[1]))

    def post_row_menu(self, global_pos):
        menu = self.build_row_menu()
        if menu is None:
            return None
        self._row_menu = menu
        menu.popup(global_pos)
        return menu

    def _copy(self, text, what):
        QGuiApplication.clipboard().setText(text)
        self.status.set(f'Copied the {what} to the clipboard.')

    def copy_procedure_name(self):
        rec = self._selected_row()
        if rec:
            self._copy(str(rec[1]), 'procedure name')

    def copy_procedure_path(self):
        rec = self._selected_row()
        if rec and rec[5]:
            self._copy(str(self.core.script_file(rec[5])), 'file path')

    def show_procedure_location(self):
        rec = self._selected_row()
        if not rec or not rec[5]:
            return
        path = self.core.script_file(rec[5])
        if not path.is_file():
            dialogs.message(self, 'error', 'Procedure not found', f'Cannot locate the procedure script:\n{path}')
            return
        try:
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', str(path)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path.parent)])
        except OSError as exc:
            dialogs.message(self, 'error', 'Could not open the folder', str(exc))

    def readiness_check(self):
        """Readiness check of the selected procedure on the simulated bench (tools/readiness_check.py in a subprocess; no instrument I/O)."""
        rec = self._selected_row()
        cmd = self.core.readiness_command(rec)
        if not rec or cmd is None:
            dialogs.message(self, 'info', 'Readiness check', 'tools/readiness_check.py was not found next to the Manager.')
            return
        self.status.set(f'Readiness check of {rec[1]} ...')
        out = []

        def work():
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(self.core.base))
                out.append((r.stdout or '') + (r.stderr or ''))
            except (OSError, subprocess.SubprocessError) as exc:
                out.append(f'The readiness check could not run: {exc}')
        th = self._readiness_thread = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                QTimer.singleShot(200, poll)
                return
            self._readiness_window = dialogs.show_text_window(self, f'Readiness check - {rec[1]}', out[0])
            self.status.set('Readiness check finished.')
        QTimer.singleShot(200, poll)

    # ------------------------------------------------------------------ Verified on hardware (verified.py)
    def show_verified_details(self):
        """The full verification text (who, when, notes, what changed) in a small window under the info button: selectable, closes on Esc or a click elsewhere."""
        text = self.d_ver_text.strip()
        if not text:
            return None
        old = self._ver_pop
        if old is not None and old.isVisible():
            old.close()
            self._ver_pop = None
            return None
        self._ver_pop = VerificationPopup(text, self.btn_ver_info)
        self._ver_pop.show()
        return self._ver_pop

    def mark_verified(self):
        rec = self._selected_row()
        if not rec:
            return None
        entry, status = self.core.ver_status(rec)
        form = dialogs.ask_mark(self, entry, status)
        if not form:
            return None
        try:
            record, message = self.core.mark_verified(rec, form)
        except verified.VerifyError as ex:
            dialogs.message(self, 'error', 'Not recorded', str(ex))
            return None
        self.refresh()
        self.status.set(message)
        return record

    def toggle_lock(self):
        """'Unlock for editing...' (a typed reason is required) or, once unlocked and unchanged, 'Lock again'."""
        import ui_theme_core
        rec = self._selected_row()
        if not rec:
            return None
        entry, status = self.core.ver_status(rec)
        try:
            if status.kind == 'unlocked':
                who = dialogs.ask_text(self, 'Lock again', 'Nothing has changed since it was verified. Your name (recorded):',
                                       ui_theme_core.Settings('verified').get('who', '') or verified.default_who())
                if not who:
                    return None
                record, message = self.core.relock(rec, who)
            elif status.kind in ('verified', 'changed'):
                form = dialogs.ask_unlock(self, entry, status)
                if not form:
                    return None
                record, message = self.core.unlock(rec, form)
            else:
                return None
        except verified.VerifyError as ex:
            dialogs.message(self, 'error', 'Not changed', str(ex))
            return None
        self.refresh()
        self.status.set(message)
        return record

    # ------------------------------------------------------------------ run / demo
    def _launch(self, name, script, demo, asset=None, extra=None):
        plan = self.core.launch_args(script, demo, self.fast_demo, asset, extra)
        if plan is None:
            dialogs.message(self, 'error', 'Procedure not found',
                            f'Cannot locate the procedure script:\n{self.core.script_file(script)}\n\nRegister its new location if it was moved.')
            return False
        args, cwd = plan
        try:
            self.launcher(args, cwd=cwd)
        except OSError as exc:
            dialogs.message(self, 'error', 'Launch failed', str(exc))
            return False
        return True

    def run_selected(self, demo=None):
        iid = self.selected_iid()
        if iid is not None and dsb_manager.is_user_iid(iid):       # a user-built datasheet: the generic launcher with its spec file
            u = self.core.user.get(iid)
            demo = self.demo if demo is None else demo
            if u and self._launch(u['name'], u['script'], demo, extra=['--spec', u['spec_path']]):
                self.status.set(f'Launched {u["name"]}' + (' in demo mode.' if demo else '.'))
            return
        selected = self.core.db_record(iid)
        if iid is None:
            dialogs.message(self, 'info', 'Select a procedure', 'Select a procedure from the list first.')
            return
        if not selected:
            return
        name, script = selected
        demo = self.demo if demo is None else demo
        if self._launch(name, script, demo):
            self.status.set(f'Launched {name}' + (' in demo mode.' if demo else '.'))

    def driver_verification(self):
        from qtui.screens import driver_verify_window
        self.driver_verify_window = driver_verify_window.open_driver_verify(self)
        return self.driver_verify_window

    def find_instruments(self):
        self.find_window = find_instruments.open_find_instruments(self)
        return self.find_window

    # ------------------------------------------------------------------ Library menu actions
    def add(self):
        script = dialogs.pick_open_file(self, 'Select a standalone Python calibration procedure', 'Python scripts (*.py)')
        if not script:
            return
        name = dialogs.ask_register(self, script, self.core.display_path(script),
                                    lambda n, mfr, model, cat, desc: self.core.register(script, n, mfr, model, cat, desc))
        if name:
            self.refresh()
            self.status.set(f'Registered "{name}".')

    def remove(self):
        iid = self.selected_iid()
        if iid is not None and dsb_manager.is_user_iid(iid):
            u = self.core.user.get(str(iid)) or {}
            if not dialogs.ask_yes_no(self, 'Remove procedure', f'Remove "{u.get("name", "this procedure")}" from the list?\n\nIts files are kept and it can be restored in the Datasheet Builder.'):
                return
            ok, text = self.core.remove_user(iid)
            if ok:
                self.refresh()
                self.status.set(text)
            else:
                dialogs.message(self, 'info', 'Not removed', text)
            return
        rec = self._selected_row()
        if rec:
            entry, status = self.core.ver_status(rec)
            if status.locked:                                      # verified on hardware and locked: it stays in the list until it is unlocked
                dialogs.message(self, 'info', 'Verified and locked', verified.lock_text(status.record))
                return
        selected = self.core.db_record(iid)
        if iid is None:
            dialogs.message(self, 'info', 'Select a procedure', 'Select a procedure from the list first.')
            return
        if not selected:
            return
        name, _ = selected
        if not dialogs.ask_yes_no(self, 'Remove from library', f'Remove "{name}" from the procedure library?\n\nThe Python script will not be deleted.'):
            return
        self.core.remove(iid)
        self.refresh()
        self.status.set(f'Removed "{name}" from the library (script file kept).')

    def set_library_folder(self, folder):
        try:
            packages.set_library_dir(folder)
        except OSError as exc:
            dialogs.message(self, 'error', 'Library folder', f'The setting could not be saved ({exc}).')
        self.refresh_library_menu()

    def choose_library_folder(self):
        chosen = dialogs.choose_library_folder(self)
        if chosen is not None:
            self.refresh_library_menu()

    def import_package(self):
        """Pick a package, show what it is and what it would do, and install it only after the person confirms."""
        path = dialogs.choose_package(self)
        if not path:
            return
        reg, library = self.core.verified(), packages.get_library_dir()
        preview = packages.inspect(path, self.core.base, reg, library)
        if not dialogs.ask_install(self, preview):
            self.status.set('Package not imported.')
            return
        try:
            result = packages.install(path, self.core.base, reg, expected_sha256=preview.zip_sha256, library_dir=library)
        except packages.PackageError as exc:
            dialogs.message(self, 'error', 'Import failed', str(exc))
            return
        self.refresh()                                       # the scan finds a new procedure; a verified one that changed shows its state
        self.status.set(f'Imported {result.name} version {result.version} ({len(result.written)} file(s) written).')
        dialogs.show_result(self, result, preview)

    def export_package(self):
        """Write the selected procedure as a package zip (the same file tools/make_package.py makes) into a folder the person picks."""
        rec = self._selected_row()
        if not rec:
            dialogs.message(self, 'info', 'Select a procedure', 'Select a procedure from the list first.')
            return
        if not self.core.exportable(rec):
            dialogs.message(self, 'info', 'Not exportable here', 'Only an installed procedure can be exported here. A user-built datasheet is exported from the Datasheet Builder.')
            return
        folder = packages.get_library_dir()
        out = dialogs.pick_folder(self, f'Choose the folder for the package of "{rec[1]}"', folder if folder and Path(folder).is_dir() else '')
        if not out:
            return
        entry, status = self.core.ver_status(rec)
        mark = bool(status.locked) and dialogs.ask_yes_no(self, 'Verified mark', 'Include your verified-on-hardware mark in the package?\n\nThe receiving suite honours it only when its files match.')
        try:
            path, digest = self.core.export_package(rec, out, with_mark=mark)
        except packages.PackageError as exc:
            dialogs.message(self, 'error', 'Not exported', str(exc))
            return
        self.status.set(f'Exported {Path(path).name} to {out} (sha256 {digest[:12]}...).')
        dialogs.message(self, 'info', 'Package written', f'{path}\n\nsha256 {digest}\n\nIt holds this procedure\'s own files; shared engines are listed as required and are not in it.')

    def restore_previous(self):
        rec = self.core.managed_record(self.selected_iid())
        path = self.core.managed_path(rec)
        if not path or not path.is_file():
            dialogs.message(self, 'error', 'Not managed', 'Select a managed procedure.')
            return
        backups = self.core.available_backups(rec)
        if not backups:
            dialogs.message(self, 'info', 'No backups', 'No previous versions are available.')
            return

        def restore(source, win):
            try:
                raw = self.core.validated_update(source)
            except Exception as exc:
                dialogs.message(win, 'error', 'Invalid backup', str(exc))
                return False
            if not dialogs.ask_yes_no(win, 'Confirm restore', f'Restore {source.name}?\nThe current procedure will also be backed up.'):
                return False
            try:
                self.core.backup(rec, path)
                self.core.atomic_replace(raw, path)
            except Exception as exc:
                dialogs.message(win, 'error', 'Restore failed', str(exc))
                return False
            return True
        if dialogs.ask_restore(self, rec, backups, restore):
            self.refresh()
            self.status.set(f'Restored {rec[1]} from the chosen version')
            dialogs.message(self, 'info', 'Restored', 'Previous procedure restored. Reopen any running procedure windows.')

    # ------------------------------------------------------------------ Mudcats .MDD import
    def import_mdd_procedure(self, path=None):
        """Import a Mudcats .MDD as a MANUAL calibration (the preview first; nothing is created until it is approved)."""
        path = path or dialogs.pick_open_file(self, 'Choose Cal Processor datasheet', 'Cal Processor datasheet (*.mdd *.MDD);;All files (*)')
        if not path:
            return None
        return dialogs.open_mdd_preview(self, path, on_created=self._mdd_procedure_created, status=self.status.set)

    @staticmethod
    def dropped_mdd_paths(mime):
        """The .mdd files in a drag (local files only; anything else is ignored)."""
        if mime is None or not mime.hasUrls():
            return []
        paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return [p for p in paths if p.lower().endswith('.mdd') and Path(p).is_file()]

    def dragEnterEvent(self, event):
        if self.dropped_mdd_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.dropped_mdd_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # one review window per file, same preview-first flow as the button; nothing is created until each is approved
        for path in paths:
            self.import_mdd_procedure(path)

    def _mdd_procedure_created(self, res):
        """The new manual procedure is in the registry: show it (Manual Calibrations tab, selected)."""
        self.select_view(procscan.KIND_MANUAL)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.category_box.setCurrentIndex(0)
        self.refresh()
        iid = dsb_manager.IID_PREFIX + res.uid
        row = next((r for r in self.table.rows() if r.iid == iid), None)
        if row is not None:
            self.table.select_rows([row])
            self.table.scroll_to_row(row)


def load_panel_from(registry, key):
    """qtui.screens.load_panel for an explicit registry (the Manager's own copy of PANELS, which tests may replace)."""
    import importlib
    module, _, cls = registry[key].partition(':')
    return getattr(importlib.import_module(module), cls)
