"""The Datasheet Builder tab (Qt): the list of user datasheets and the actions on them.  Qt twin of datasheet_builder_ui.DatasheetBuilderPanel.

    panel = DatasheetBuilderPanel(parent_widget, on_saved=callback, status=fn)     # the Manager's 'Datasheet Builder' tab (storage / matcher_factory are for tests)
    panel.refresh()                                                                # when the tab is shown

New / Open / Duplicate / Delete + Restore / Version history / Export JSON / Import JSON / Refresh.  Opening one shows the grid editor window
(qtui.screens.dsb_editor.GridEditorWindow); the older detail pages, the Sheet check, the problems list, the preview and the version history live in
dsb_pages / dsb_check / dsb_dialogs.  Display-only SI scaling: the model formats values, the datasheet keeps SI.  Every decision is in
datasheet_builder_ui_model; this module draws it.  No Tk import.

`status` may be an object with set(text) (the Tk StringVar), setText(text), showMessage(text) or a plain callable."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import datasheet_builder_ui_model as M
from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.screens.dsb_check import CommandsWindow, SheetCheckWindow, ask_waiver                       # noqa: F401  (re-exported)
from qtui.screens.dsb_dialogs import (ChoiceDialog, DriversWindow, NewSheetDialog, PageDialog, PreviewWindow, ProblemsWindow, RuleDialog, VersionsWindow,   # noqa: F401
                                      ask_choice, ask_new_sheet)
from qtui.screens.dsb_editor import GridEditorWindow
from qtui.screens.dsb_inspector import Inspector, SpecPanel                                           # noqa: F401
from qtui.screens.dsb_pages import AutomationPage, FunctionsPage, HeaderPage, RangesPage, SpecPage    # noqa: F401
from qtui.table import Column
from qtui.theme import M as SZ

HELP = ('Build a datasheet for any instrument from its manufacturer\'s specification: you describe the functions, ranges and accuracy, the builder works out the '
        'test points and limits, finds which of your standards can supply them, and saves a procedure the suite can run. Everything you save is kept as a numbered '
        'version. (Cal Processor .MDD files are imported with the Procedures tab button.)')


class DatasheetBuilderPanel(QWidget):
    """The Manager's 'Datasheet Builder' tab: the list of user datasheets and the actions on them."""

    COLS = ('make', 'model', 'title', 'version', 'functions', 'points', 'automation', 'saved')

    def __init__(self, parent=None, storage=None, on_saved=None, status=None, matcher_factory=None):
        super().__init__(parent)
        self.lst = M.DatasheetList(storage, matcher_factory)
        self.on_saved, self.status, self.matcher_factory = on_saved, status, matcher_factory
        self.editors = {}
        self._rows = {}
        self.message = C.Var('', on_change=self._show_message)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SZ.sm)
        lay.addWidget(widgets.label(HELP, 'sub', wrap=True))
        bar = QHBoxLayout()
        bar.setSpacing(SZ.sm)
        self.b_new = C.button('New...', self.new, 'primary')
        self.b_open = C.button('Open', self.open_selected)
        self.b_duplicate = C.button('Duplicate', self.duplicate)
        self.b_delete = C.button('Delete', self.delete_or_restore)
        self.b_history = C.button('Version history...', self.history)
        self.b_export = C.button('Export JSON...', self.export)
        self.b_import = C.button('Import JSON...', self.import_)
        self.b_refresh = C.button('Refresh', self.refresh)
        for b in (self.b_new, self.b_open, self.b_duplicate, self.b_delete, self.b_history, self.b_export, self.b_import, self.b_refresh):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        flt = QHBoxLayout()
        flt.setSpacing(SZ.sm)
        flt.addWidget(QLabel('Search'))
        self.search = widgets.SearchField('Search datasheets')
        self.search.setMinimumWidth(260)
        self.search.queryChanged.connect(lambda _t: self.apply_search())
        flt.addWidget(self.search)
        self.show_deleted = QCheckBox('Show deleted')
        self.show_deleted.clicked.connect(lambda _c=False: self.toggle_deleted())
        flt.addWidget(self.show_deleted)
        flt.addStretch(1)
        lay.addLayout(flt)
        self.table = DataTableFor(self)
        lay.addWidget(self.table, 1)
        self.message_l = widgets.label('', wrap=True)
        lay.addWidget(self.message_l)
        self.apply_search()                                    # empty until the tab is first shown: the Manager calls refresh() then

    # ---- list
    def _show_message(self, text):
        self.message_l.setText(text)

    def say(self, text):
        self.message.set(text)
        st = self.status
        if st is None:
            return
        try:
            if hasattr(st, 'set'):
                st.set(text)
            elif hasattr(st, 'setText'):
                st.setText(text)
            elif hasattr(st, 'showMessage'):
                st.showMessage(text)
            elif callable(st):
                st(text)
        except RuntimeError:
            pass

    def refresh(self):
        self.lst.refresh()
        self.apply_search()

    def apply_search(self):
        self.lst.search = self.search.text()
        rows = self.lst.rows()
        self._rows = {r['uid']: r for r in rows}
        self.table.empty_text = self.lst.empty_text() or 'No datasheets'
        self.table.set_rows(rows, keep_selection=True)
        self.selection_changed()
        return rows

    def toggle_deleted(self):
        self.lst.show_deleted = self.show_deleted.isChecked()
        self.refresh()

    def _uid(self):
        s = C.selected_ids(self.table, 'uid')
        return s[0] if s else ''

    def selection_changed(self):
        row = self._rows.get(self._uid())
        self.b_delete.setText('Restore' if row and row['deleted'] else 'Delete')
        self.b_open.setEnabled(not (row and row['deleted']))

    def _need(self):
        uid = self._uid()
        if not uid:
            self.say('Select a datasheet in the list first.')
        return uid

    # ---- actions
    def new(self):
        handheld = ask_new_sheet(self.window())
        if handheld is None:
            return None
        return self.open_editor(self.lst.new(handheld=handheld))

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
                win.raise_()
                win.activateWindow()
                return win
            except RuntimeError:
                self.editors.pop(uid, None)
        ed = self.lst.open(uid)
        if ed is None:
            self.say(self.lst.last_error if self.lst.refused else f'Could not read datasheet {uid}: the file is missing or damaged.')
            return None
        return self.open_editor(ed)

    def open_editor(self, model):
        win = GridEditorWindow(self.window(), model, panel=self)
        win._key = model.ds.uid or f'new-{id(win)}'
        self.editors[win._key] = win
        win.show()
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
        title = C.ask_string(self.window(), 'Duplicate datasheet', 'Title of the copy:', f'{row["title"]} (copy)')
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
            if not C.ask_yes_no(self.window(), 'Delete datasheet', f'Delete "{row["title"]}"? It leaves the Procedures list. Every version is kept and you can restore it '
                                                                  f'(tick "Show deleted").'):
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
        win = VersionsWindow(self.window(), self.lst.storage, uid, panel=self)
        win.show()
        return win

    def export(self):
        uid = self._need()
        if not uid:
            return None
        path = C.ask_save_path(self.window(), 'Export datasheet as JSON', f'{uid}.json', 'JSON (*.json)')
        res = self.lst.export_json(uid, path)
        self.say(res.message)
        return res

    def import_(self):
        path = C.ask_open_path(self.window(), 'Import a datasheet JSON (or a runnable spec made by the builder)', 'JSON (*.json);;All files (*.*)')
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


def DataTableFor(panel: DatasheetBuilderPanel):
    """The list of datasheets: sortable, filterable-by-search-box rows keyed by uid; a deleted one is greyed, a draft amber."""
    cols = [Column('make', 'Make', 110), Column('model', 'Model', 110), Column('title', 'Title', 220, stretch=True), Column('version', 'Ver', 50, align='right'),
            Column('functions', 'Functions', 220), Column('points', 'Points', 70, align='right'), Column('automation', 'Automation', 280), Column('saved', 'Last saved', 175)]
    t = C.table(cols, row_tone=lambda r: 'warn' if (r['status'] == 'draft' and not r['deleted']) else None, key='uid', sortable=True, empty='No datasheets')
    for c in t.source_model.columns:
        if c.key in ('make', 'model', 'title', 'functions', 'automation', 'saved'):
            c.tone = lambda r: 'muted' if r.get('deleted') else None
    t.selectionChangedRows.connect(lambda _r: panel.selection_changed())
    t.rowActivated.connect(lambda _r: panel.open_selected())
    return t
