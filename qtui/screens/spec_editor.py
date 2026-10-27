"""Standards spec editor (Qt twin of spec_editor_ui.py).  The data work is in the toolkit-free models spec_editor.py, spec_edit_io.py and spec_edit_log.py,
which are REUSED here unchanged; this module is only the windows:

    open_editor(parent, model)    from the Standards Specs tab ('Edit spec...')

Editor: sheet list on the left, tabs Rows / Notes / Standard info / Limits / Sheet issues in the middle, 'Pending changes' and the checks before save on the
right.  A double-click (or Enter) edits a cell; changed cells are amber; a row, note or field with a validation ERROR is shown in red text (with a red mark
and a tooltip with the reason), a WARNING in amber.  Nothing is written until 'Document & save edit...' (reason, source, name required).
Edit history: a second window with the documented edits of the sheet, compare with the current file, restore (itself a documented edit), export.

Same behaviour, prompts, order of steps and texts as the Tk editor; only the look changed (design boards Main / Dialog / History + the qtui look).
Message boxes and file dialogs go through the module functions ask_yes_no / show_info / show_error / show_warning / ask_save_path so a test can drive them.
"""
from __future__ import annotations

import html
import json
import weakref
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

import spec_edit_io as eio
import spec_edit_log as elog
import spec_editor as se
import specmanager_view as view
import ui_theme_core as core
from qtui import theme
from qtui.screens._share import ShareWidth
from qtui.table import CellDelegate, Column, DataTable, TableModel
from qtui.theme import M
from qtui.widgets import Badge, Banner, MessageDialog, ModalDialog, PrimaryButton, SecondaryButton, SegmentedFilter, label, make_tab_bar, rule

COLS = [  # id, heading, width, anchor
    ('function', 'FUNCTION', 150, 'w'), ('label', 'RANGE', 96, 'w'), ('freq', 'FREQUENCY', 104, 'w'), ('period', 'PERIOD', 74, 'w'),
    ('rel', 'READING', 82, 'e'), ('fs_rel', 'FS (REL)', 80, 'e'), ('fs_value', 'FS VALUE', 88, 'e'), ('abs', 'FLOOR', 84, 'e'),
    ('res', 'RESOLUTION', 116, 'e'), ('notes', 'NOTES', 62, 'w'), ('page', 'PAGE', 52, 'e'), ('span', 'SPAN (VALUE RANGE)', 150, 'w')]
RANGE_LEVEL = ('label', 'span', 'freq', 'res', 'notes', 'page')
HINT = 'Double-click a cell to edit. Changed cells turn amber and are listed on the right. Nothing is written to the sheet until you document and save.'
SAVE_TEXT = 'Document & save edit...'
_MONO_COLS = ('rel', 'fs_rel', 'fs_value', 'abs', 'res', 'page', 'period')
CHANGED_ROLE = Qt.ItemDataRole.UserRole + 20
TAB_KEYS = ('rows', 'notes', 'info', 'limits', 'issues')


def _amp(text: str) -> str:
    """Button text with a literal '&' (Qt reads a single '&' as a mnemonic)."""
    return text.replace('&', '&&')


# ------------------------------------------------------------------------------------------------------------------------ prompts (patchable in tests)
def ask_yes_no(parent, title: str, text: str) -> bool:
    return MessageDialog(parent, 'question', title, text, buttons=(('Yes', 'yes', 'primary'), ('No', 'no', None)), cancel_key='no').run() == 'yes'


def show_info(parent, title: str, text: str) -> None:
    MessageDialog(parent, 'info', title, text).run()


def show_warning(parent, title: str, text: str) -> None:
    MessageDialog(parent, 'warning', title, text).run()


def show_error(parent, title: str, text: str) -> None:
    MessageDialog(parent, 'error', title, text).run()


def ask_save_path(parent, title: str, initial: str, filter_: str) -> str:
    return QFileDialog.getSaveFileName(parent, title, initial, filter_)[0]


def ask_open_path(parent, title: str, filter_: str) -> str:
    return QFileDialog.getOpenFileName(parent, title, '', filter_)[0]


def ask_string(parent, title: str, prompt: str, initialvalue: str = '') -> str | None:
    """A one-line question (the Qt counterpart of simpledialog.askstring); None when cancelled."""
    dlg = ModalDialog(parent, title, width=480)
    dlg.setWindowTitle(_title(title))
    dlg.add_text(prompt)
    edit = QLineEdit(initialvalue)
    dlg.body.addWidget(edit)
    dlg.initial_focus = edit
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('OK', role='primary', default=True)
    edit.selectAll()
    return edit.text() if dlg.run() == 'ok' else None


_TONED: 'weakref.WeakKeyDictionary' = weakref.WeakKeyDictionary()
_BROWSERS: 'weakref.WeakSet' = weakref.WeakSet()


def _tone(widget: QWidget, kind: str) -> None:
    """Text colour of a label from the theme tokens: 'bad' | 'warn' | 'good' | 'info' | 'muted' | 'text'."""
    t = theme.tokens()
    pal = widget.palette()
    pal.setColor(widget.foregroundRole(), QColor(t.get(kind, t['text'])))
    widget.setPalette(pal)
    _TONED[widget] = kind                                  # re-applied when the theme is switched live (see _retheme_all)


def _title(text: str) -> str:
    return text + core.DEMO_SUFFIX


# ------------------------------------------------------------------------------------------------------------------------ marks (drawn, no symbol font)
_MARKS: dict = {}


def mark_pixmap(kind: str, size: int = 14) -> QPixmap:
    """error cross / warning triangle / ok check / new plus / changed dot / info, in the theme colours."""
    key = (kind, size, theme.name())
    pm = _MARKS.get(key)
    if pm is not None:
        return pm
    t = theme.tokens()
    if kind in ('error', 'warn', 'info'):
        pm = theme.pixmap(kind, t[{'error': 'bad', 'warn': 'warn', 'info': 'muted'}[kind]], size)
    elif kind == 'ok':
        pm = theme.pixmap('good', t['good'], size)
    elif kind == 'changed':
        pm = theme.pixmap('dot', t['warn'], size)
    else:                                                                    # 'new': a plus
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(t['good']), max(1.6, size / 8.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        a, b, m = size * 0.24, size * 0.76, size * 0.5
        p.drawLine(QPointF(a, m), QPointF(b, m))
        p.drawLine(QPointF(m, a), QPointF(m, b))
        p.end()
    _MARKS[key] = pm
    return pm


def amber() -> tuple[str, str]:
    """(background, text) of a changed cell: stronger than the palette's warn_bg so it shows."""
    t = theme.tokens()
    bg = theme.blend(t['table'], t['warn_dot'], 0.30)
    return bg, (t['warn'] if _contrast(t['warn'], bg) >= 4.5 else t['text'])          # light: the amber text on the amber tint is under 4.5:1, the normal text colour is not


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = QColor(h)
        f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4          # noqa: E731
        return 0.2126 * f(c.redF()) + 0.7152 * f(c.greenF()) + 0.0722 * f(c.blueF())
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------------------------------------------------------------------ the table with inline editing
class GridRow:
    """One line of a grid: its id, the text of each column, the tags ('err' / 'warn' / 'cont' / 'new'), the mark and the group shading."""
    __slots__ = ('iid', 'values', 'tags', 'mark', 'shade')

    def __init__(self, iid, values, tags=(), mark='', shade=False):
        self.iid, self.values, self.tags, self.mark, self.shade = iid, values, set(tags), mark, shade


class _GridModel(TableModel):
    """TableModel plus what the editor paints per cell: the mark, the amber of a changed cell, red / amber row text, the issue tooltip."""

    def __init__(self, columns, grid, parent=None):
        super().__init__(columns, [], parent)
        self.grid = grid

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self.columns[index.column()].key
        g = self.grid
        if role == Qt.ItemDataRole.DecorationRole:
            return mark_pixmap(row.mark) if key == '_mark' and row.mark else None
        if role == Qt.ItemDataRole.BackgroundRole:
            if 'new' in row.tags or (row.iid, key) in g.changed:
                return QColor(amber()[0])
            return QColor(theme.tokens()['row_alt']) if row.shade else None
        if role == Qt.ItemDataRole.ForegroundRole:
            t = theme.tokens()
            if (row.iid, key) in g.changed or 'new' in row.tags:
                return QColor(t['bad'] if 'err' in row.tags else amber()[1])
            if 'err' in row.tags:
                return QColor(t['bad'])
            if 'warn' in row.tags:
                return QColor(t['warn'])
            if 'cont' in row.tags:
                return QColor(t['muted'])
            return None
        if role == CHANGED_ROLE:
            return (row.iid, key) in g.changed or 'new' in row.tags
        if role == Qt.ItemDataRole.ToolTipRole:
            return (g.tip_for(row.iid, key) if g.tip_for and key != '_mark' else '') or (g.tip_for(row.iid, 'function') if g.tip_for and key == '_mark' else '') or None
        return super().data(index, role)


class _GridDelegate(CellDelegate):
    """The qtui cell painter, plus a thin amber outline round a changed cell (it stays visible when the row is selected)."""

    def paint(self, painter, opt, index):
        super().paint(painter, opt, index)
        if index.data(CHANGED_ROLE) and index.data(Qt.ItemDataRole.DisplayRole):
            painter.save()
            painter.setPen(QPen(QColor(theme.tokens()['warn_dot']), 1))
            painter.drawRect(opt.rect.adjusted(0, 0, -1, -1))
            painter.restore()


class _CellEntry(QLineEdit):
    """The in-cell editor: Enter commits, Escape cancels, leaving it commits (like the Tk entry)."""

    def __init__(self, grid, parent):
        super().__init__(parent)
        self.grid = grid

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.grid._close_entry(commit=True)
            ev.accept()
        elif ev.key() == Qt.Key.Key_Escape:
            self.grid._close_entry(commit=False)
            ev.accept()
        else:
            super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self.grid.entry is not None and self.grid.entry[0] is self:
            self.grid._close_entry(commit=True)


class SpecTable(DataTable):
    def __init__(self, grid: 'Grid', columns):
        super().__init__(columns, [], row_key=lambda r: r.iid, multi=False, alternating=False, empty_text='Nothing here', parent=grid)
        old = self.source_model
        model = _GridModel(columns, grid, self)
        model.cellEdited.connect(self.cellEdited)
        self.source_model = model
        self.proxy.setSourceModel(model)
        old.deleteLater()
        self.grid = grid
        self.setItemDelegate(_GridDelegate(self))
        hh = self.horizontalHeader()
        hh.setSectionsClickable(False)
        hh.setSortIndicatorShown(False)
        hh.setStretchLastSection(True)
        self.setIconSize(QSize(14, 14))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.doubleClicked.connect(self._double)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: grid._reposition_entry())
        self.verticalScrollBar().valueChanged.connect(lambda _v: grid._reposition_entry())

    def _double(self, index):
        row = self.row_of(index)
        key = self.source_model.columns[self.proxy.mapToSource(index).column()].key
        if row is not None and key != '_mark':
            self.grid.begin_edit(row.iid, key)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2) and self.grid.entry is None:
            self.grid._enter()
            ev.accept()
            return
        super().keyPressEvent(ev)


class Grid(QWidget):
    """A table with (a) in-cell editing on double-click / Enter, (b) amber cells where changed, (c) red / amber rows with a tooltip for validation issues."""

    def __init__(self, parent, editor, columns, show_flag=True, hscroll=True):
        super().__init__(parent)
        self.ed = editor
        self.cols = columns
        self.rows: list[GridRow] = []
        self.changed: set = set()
        self.entry = None                # (QLineEdit, iid, column key, old text)
        self.on_edit = None              # (iid, column id, text) -> None; raises se.EditError
        self.initial = None              # (iid, column id) -> text for the editor, or None when the cell is not editable
        self.long_text = None            # (iid, column id) -> True to edit in the multi-line window
        self.tip_for = None              # (iid, column id) -> tooltip text
        cols = [Column('_mark', '', width=28, align='center', searchable=False, getter=lambda r: '')]
        for cid, head, width, anchor in columns:
            cols.append(Column(cid, head, width=width, align='left' if anchor == 'w' else 'right', mono=cid in _MONO_COLS, getter=lambda r, k=cid: r.values.get(k, '')))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = SpecTable(self, cols)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if hscroll else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.table)
        self._share = ShareWidth(self.table, [28] + [c[2] for c in columns], [0] + [c[2] * (2 if c[0] in ('function', 'label', 'text', 'value', 'what', 'limit', 'where') else 1) for c in columns])
        self.table.selectionChangedRows.connect(lambda _rows: self.ed._selection_changed(self))

    # ---- rows
    def set_rows(self, rows: list[GridRow]) -> None:
        self._close_entry(commit=False)
        keep = self.selected_iids()
        y0 = self.table.verticalScrollBar().value()
        self.rows = list(rows)
        self._by = {r.iid: r for r in rows}
        self.table.set_rows(self.rows, keep_selection=False)
        want = [self._by[i] for i in keep if i in self._by]
        if want:
            self.table.select_rows(want)
        self.table.verticalScrollBar().setValue(y0)

    def iids(self) -> list:
        return [r.iid for r in self.rows]

    def exists(self, iid) -> bool:
        return iid in getattr(self, '_by', {})

    def row(self, iid) -> GridRow | None:
        return getattr(self, '_by', {}).get(iid)

    def tags(self, iid) -> set:
        r = self.row(iid)
        return set(r.tags) if r else set()

    def values(self, iid) -> dict:
        r = self.row(iid)
        return dict(r.values) if r else {}

    def selected_iids(self) -> list:
        return [r.iid for r in self.table.selected_rows()]

    def select(self, iid, emit: bool = True) -> None:
        r = self.row(iid)
        if r is None:
            return
        self.table.select_rows([r])
        self.table.scroll_to_row(r)
        if emit:
            self.ed._selection_changed(self)

    def select_first(self) -> None:
        if self.rows:
            self.select(self.rows[0].iid)

    @property
    def selected_col(self):
        ix = self.table.currentIndex()
        if not ix.isValid():
            return None
        key = self.table.source_model.columns[self.table.proxy.mapToSource(ix).column()].key
        return None if key == '_mark' else key

    # ---- amber marks
    def set_changed(self, cells, text_of=None) -> None:
        self.changed = set(cells)
        self.table.viewport().update()

    # ---- editing
    def _enter(self):
        sel = self.selected_iids()
        col = self.selected_col
        if sel and col:
            self.begin_edit(sel[0], col)

    def _index_of(self, iid, col):
        pos = next((i for i, r in enumerate(self.rows) if r.iid == iid), None)
        if pos is None:
            return None
        names = [c.key for c in self.table.source_model.columns]
        ix = self.table.proxy.index(pos, names.index(col))
        return ix if ix.isValid() else None

    def begin_edit(self, iid, col):
        self._close_entry(commit=False)
        text = self.initial(iid, col) if self.initial else None
        if text is None:
            return
        if self.long_text and self.long_text(iid, col):
            new = text_dialog(self.ed, f'Edit {col}', text)
            if new is not None:
                self._apply(iid, col, new)
            return
        ix = self._index_of(iid, col)
        if ix is None:
            return
        self.table.scrollTo(ix)
        ent = _CellEntry(self, self.table.viewport())
        ent.setText(text)
        self.entry = (ent, iid, col, text)
        self._reposition_entry()
        ent.show()
        ent.setFocus()
        ent.selectAll()

    def _reposition_entry(self):
        if not self.entry:
            return
        ent, iid, col, _old = self.entry
        ix = self._index_of(iid, col)
        if ix is None:
            return
        r = self.table.visualRect(ix)
        ent.setGeometry(r.left(), r.top(), max(r.width(), 120), r.height())

    def _close_entry(self, commit):
        if not self.entry:
            return
        ent, iid, col, old = self.entry
        self.entry = None
        value = ent.text()
        ent.hide()
        ent.deleteLater()
        self.table.setFocus()
        if commit and value != old:
            self._apply(iid, col, value)

    def commit_text(self, iid, col, text):
        """Type `text` into a cell the way the person would (used by tests and by the entry)."""
        return self._apply(iid, col, text)

    def _apply(self, iid, col, text):
        try:
            self.on_edit(iid, col, text)
        except se.EditError as e:
            self.ed.say(str(e), 'error')
            return False
        self.ed.say('', '')
        return True


def text_dialog(parent, title, initial, readonly=False, width=90, height=14):
    """Multi-line text in a modal window; returns the new text or None when cancelled."""
    dlg = ModalDialog(parent, title, width=640)
    dlg.setWindowTitle(_title(title))
    dlg.title_label.hide()
    txt = QTextEdit()
    txt.setAcceptRichText(False)
    txt.setPlainText(initial)
    txt.setReadOnly(readonly)
    txt.setMinimumHeight(220)
    dlg.body.addWidget(txt)
    dlg.initial_focus = txt
    if readonly:
        dlg.add_button('Close', cancel=True)
        dlg.run()
        return None
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('OK', role='primary', default=True)
    return txt.toPlainText() if dlg.run() == 'ok' else None


# ------------------------------------------------------------------------------------------------------------------------ small helpers
def _wrapped(text: str = '', role: str | None = None) -> QLabel:
    lab = label(text, role, wrap=True)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return lab


def _banner(text: str, kind: str) -> Banner:
    b = Banner('', kind)
    b.text_label.setTextFormat(Qt.TextFormat.PlainText)
    b.text_label.setText(text)
    return b


class _Browser(QTextBrowser):
    """A text box whose HTML uses the theme colours: it remembers its HTML and re-applies style sheet, marks and text when the theme is switched live."""
    def __init__(self):
        super().__init__()
        self._src = None
        self.apply_theme(False)
        _BROWSERS.add(self)

    def setHtml(self, text):
        self._src = text
        super().setHtml(text)

    def apply_theme(self, redo=True):
        t = theme.tokens()
        self.document().setDefaultStyleSheet(
            f"body {{ color: {t['text']}; }} a {{ color: {t['primary']}; text-decoration: none; font-weight: 600; }} "
            f".mono {{ font-family: '{theme.mono_family()}'; }} .muted {{ color: {t['muted']}; }} .del {{ color: {t['bad']}; }} .add {{ color: {t['good']}; }} "
            f".err {{ color: {t['bad']}; }} .warnl {{ color: {t['warn']}; }} .ok {{ color: {t['good']}; }} .warn {{ color: {t['warn']}; }} h3 {{ margin-top: 12px; margin-bottom: 2px; }}")
        if redo:
            _add_marks(self)
            if self._src is not None:
                y = self.verticalScrollBar().value()
                super().setHtml(self._src)
                self.verticalScrollBar().setValue(y)


def _retheme_all(_name=None) -> None:
    for w, kind in list(_TONED.items()):
        try:
            _tone(w, kind)
        except RuntimeError:
            pass
    for b in list(_BROWSERS):
        try:
            b.apply_theme()
        except RuntimeError:
            pass


def _browser() -> QTextBrowser:
    b = _Browser()
    b.setOpenLinks(False)
    b.setOpenExternalLinks(False)
    b.setFrameShape(QFrame.Shape.NoFrame)
    return b


def _add_marks(browser: QTextBrowser) -> None:
    for k in ('error', 'warn', 'ok', 'info', 'new', 'changed'):
        browser.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(f'mark:{k}'), mark_pixmap(k))


def _mark_img(kind: str) -> str:
    return f'<img src="mark:{kind}" width="14" height="14"> '


def _diff_html(changes, limit=200) -> str:
    """The old / new lines of a list of changes (Change objects or the dicts the log stores) as HTML for a read-only text box."""
    esc = html.escape
    out = []
    for c in changes[:limit]:
        where = c.where if hasattr(c, 'where') else c.get('where', '')
        lab = c.label if hasattr(c, 'label') else c.get('field', '')
        op = c.op if hasattr(c, 'op') else c.get('op')
        old = c.old_text if hasattr(c, 'old_text') else c.get('old_text', '')
        new = c.new_text if hasattr(c, 'new_text') else c.get('new_text', '')
        out.append(f'<div class="muted mono">{esc(where)}</div>')
        if op == 'set':
            out.append(f'<div class="del mono">- {esc(lab)}: {esc(old or "(blank)")}</div>')
            out.append(f'<div class="add mono">+ {esc(lab)}: {esc(new or "(blank)")}</div>')
        elif op == 'add':
            out.append(f'<div class="add mono">+ {esc(lab)}: {esc(new)}</div>')
        else:
            out.append(f'<div class="del mono">- {esc(lab)}: {esc(old)}</div>')
    if len(changes) > limit:
        out.append(f'<div class="muted mono">... and {len(changes) - limit} more changes (all are saved and listed in the history)</div>')
    if not changes:
        out.append('<div class="muted mono">(no changes)</div>')
    return ''.join(out)


def _diff_box(changes, limit=200) -> QTextBrowser:
    b = _browser()
    b.setHtml('<body>' + _diff_html(changes, limit) + '</body>')
    b.setMinimumHeight(120)
    b.setProperty('surface', 'field')
    b.setFrameShape(QFrame.Shape.StyledPanel)
    return b


theme.manager().changed.connect(_retheme_all)


# ------------------------------------------------------------------------------------------------------------------------ the editor window
class EditorWindow(QWidget):
    def __init__(self, parent=None, model=None, on_saved=None, spec_dir=None, db_path=None, backup_dir=None, width=1240, height=780):
        super().__init__(None, Qt.WindowType.Window)
        self.win = self
        self.parent_widget, self.on_saved, self.spec_dir, self.db_path, self.backup_dir = parent, on_saved, spec_dir, db_path, backup_dir
        self.setWindowTitle(_title('Edit standards spec'))
        self.docs, self.errors_of_load = {}, {}
        self.sheets = se.list_sheets(spec_dir)
        self.cur = None            # file name
        self.report = None
        self.history_window = None
        self.detail_text = ''
        self._links = {}
        self._build()
        theme.manager().changed.connect(self._on_theme)
        self.resize(width, height)
        self.setMinimumSize(QSize(1000, 620))
        target = None
        if model:
            f = se.sheet_for_model(model, spec_dir)
            target = f.name if f else None
        if target is None and self.sheets:
            target = self.sheets[0][0].name
        if target:
            self.select_sheet(target)
        if model and not se.sheet_for_model(model, spec_dir):
            self.say(f'{model} has no sheet file in specs/standards/ (it was imported from elsewhere); pick a sheet on the left.', 'warn')

    def _on_theme(self, _name=None):
        if self.doc is not None:
            self.refresh()

    # ---- layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setProperty('surface', 'bar')
        hl = QHBoxLayout(head)
        hl.setContentsMargins(M.lg, M.md, M.lg, M.md)
        hl.setSpacing(M.md)
        hl.addWidget(label('Edit standards spec', 'h2'))
        self.path_label = label('', 'mono')
        _tone(self.path_label, 'muted')
        hl.addWidget(self.path_label, 1)
        self.pill = Badge('', 'neutral')
        hl.addWidget(self.pill)
        root.addWidget(head)
        bar = QFrame()
        from qtui.screens.standards_specs import FlowLayout          # wraps the buttons onto a second line in a narrow window instead of cutting their text
        bl = FlowLayout(bar, M.sm, M.sm)
        bl.setContentsMargins(M.lg, M.sm, M.lg, M.sm)
        self.btn = {}
        for key, text, cmd, primary in (
                ('save', SAVE_TEXT, self.document_and_save, True), ('discard', 'Discard all', self.discard_all, False),
                ('revert', 'Revert selected cell', self.revert_selected, False), ('add', 'Add row', self.add_row, False), ('delete', 'Delete row', self.delete_row, False),
                ('addp', 'Add period', self.add_period, False), ('delp', 'Delete period', self.delete_period, False), ('details', 'Row details...', self.row_details, False)):
            b = PrimaryButton(_amp(text)) if primary else SecondaryButton(_amp(text))
            b.clicked.connect(lambda _c=False, f=cmd: f())
            bl.addWidget(b)
            self.btn[key] = b
        self.btn['history'] = SecondaryButton('Edit history')
        self.btn['history'].clicked.connect(lambda _c=False: self.open_history())
        bl.addWidget(self.btn['history'])
        root.addWidget(bar)
        root.addWidget(rule())
        body = QWidget()
        bd = QHBoxLayout(body)
        bd.setContentsMargins(M.lg, M.md, M.lg, M.sm)
        bd.setSpacing(M.md)
        # left: sheets
        left = QFrame()
        left.setProperty('surface', 'card')
        left.setFixedWidth(180)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, M.md, 0, M.sm)
        ll.setSpacing(M.xs)
        cap = label('STANDARDS SHEETS', 'hint')
        cap.setContentsMargins(M.md, 0, M.md, 0)
        ll.addWidget(cap)
        self.sheet_list = QListWidget()
        self.sheet_list.setFrameShape(QFrame.Shape.NoFrame)
        self.sheet_list.setProperty('plain', True)
        self.sheet_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sheet_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        for path, model, desc in self.sheets:
            it = QListWidgetItem(model or path.name)
            it.setData(Qt.ItemDataRole.UserRole, path.name)
            self.sheet_list.addItem(it)
        self.sheet_list.currentItemChanged.connect(lambda *_: self._sheet_picked())
        ll.addWidget(self.sheet_list, 1)
        legend = _wrapped('● = unsaved edits\n(edited) = edited by hand since built', 'hint')
        legend.setContentsMargins(M.md, 0, M.md, 0)
        ll.addWidget(legend)
        bd.addWidget(left)
        # centre: tabs
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(M.xs)
        self.tabbar = make_tab_bar(['Rows', 'Notes', 'Standard info', 'Limits', 'Sheet issues'])
        ml.addWidget(self.tabbar)
        self.stack = QStackedWidget()
        self.tab_pages = {k: QWidget() for k in TAB_KEYS}
        for k in TAB_KEYS:
            self.stack.addWidget(self.tab_pages[k])
        self.tabbar.currentChanged.connect(self.stack.setCurrentIndex)
        ml.addWidget(self.stack, 1)
        self._build_rows_tab()
        self._build_notes_tab()
        self._build_info_tab()
        self._build_list_tab('limits', (('function', 'FUNCTION', 260, 'w'), ('limit', 'LIMIT TEXT', 520, 'w'), ('page', 'PAGE', 70, 'w')))
        self._build_list_tab('issues', (('level', 'LEVEL', 70, 'w'), ('where', 'WHERE', 300, 'w'), ('what', 'WHAT', 560, 'w')))
        msgrow = QHBoxLayout()
        msgrow.setSpacing(M.sm)
        self.msg_icon = QLabel()
        self.msg_icon.setFixedSize(16, 16)
        self.msg = _wrapped('')
        msgrow.addWidget(self.msg_icon, 0, Qt.AlignmentFlag.AlignTop)
        msgrow.addWidget(self.msg, 1)
        ml.addLayout(msgrow)
        bd.addWidget(mid, 1)
        # right: pending
        right = QFrame()
        right.setProperty('surface', 'card')
        right.setFixedWidth(310)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.pending = _browser()
        _add_marks(self.pending)
        self.pending.anchorClicked.connect(self._pending_link)
        self.pending.document().setDocumentMargin(14)
        self.pending.setStyleSheet('QTextBrowser { background: transparent; }')
        rl.addWidget(self.pending)
        bd.addWidget(right)
        root.addWidget(body, 1)
        self.status = label('', 'hint')
        self.status.setContentsMargins(M.lg, M.xs, M.lg, M.xs)
        sb = QFrame()
        sb.setProperty('surface', 'barbottom')
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(M.lg, M.xs + 1, M.lg, M.xs + 1)
        self.status.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.status, 1)
        root.addWidget(sb)

    def _page_layout(self, key):
        lay = QVBoxLayout(self.tab_pages[key])
        lay.setContentsMargins(0, M.sm, 0, 0)
        lay.setSpacing(M.xs)
        return lay

    def _build_rows_tab(self):
        lay = self._page_layout('rows')
        self.row_kind = ''                                   # the function-type chip: '' = All
        self._kind_specs = None
        self.kind_filter = None
        self.kind_scroll = QScrollArea()                      # one row of chips under the tabs; scrolls sideways when there are more than fit
        self.kind_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.kind_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.kind_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.kind_scroll.setWidgetResizable(False)
        lay.addWidget(self.kind_scroll)
        self.grid_rows = Grid(self, self, COLS)
        lay.addWidget(self.grid_rows, 1)
        g = self.grid_rows
        g.initial = self._rows_initial
        g.on_edit = lambda iid, col, text: self._edit_row_cell(iid, col, text)
        g.tip_for = self._rows_tip
        self.row_issue = _wrapped('', 'hint')
        lay.addWidget(self.row_issue)
        self.hint = _wrapped(HINT, 'hint')
        lay.addWidget(self.hint)

    def _build_notes_tab(self):
        lay = self._page_layout('notes')
        self.grid_notes = Grid(self, self, (('no', 'NO.', 60, 'w'), ('text', 'NOTE', 640, 'w'), ('used', 'USED BY', 100, 'w')))
        lay.addWidget(self.grid_notes, 1)
        g = self.grid_notes
        g.initial = lambda iid, col: self.doc.current['notes'][iid[1:]] if col == 'text' and iid[1:] in self.doc.current.get('notes', {}) else None
        g.long_text = lambda iid, col: True
        g.on_edit = lambda iid, col, text: (self.doc.edit_note(iid[1:], text), self.refresh())
        g.tip_for = lambda iid, col: self.report.text_for('notes', iid[1:]) if self.report else ''
        row = QHBoxLayout()
        b1, b2 = SecondaryButton('Add note'), SecondaryButton('Delete note')
        b1.clicked.connect(lambda _c=False: self.add_note())
        b2.clicked.connect(lambda _c=False: self.delete_note())
        row.addWidget(b1)
        row.addWidget(b2)
        self.notes_hint = _wrapped('Double-click a note to edit its text. A row that points at a deleted note turns red.', 'hint')
        row.addWidget(self.notes_hint, 1)
        lay.addLayout(row)

    def _build_info_tab(self):
        lay = self._page_layout('info')
        self.info_notice = QVBoxLayout()
        lay.addLayout(self.info_notice)
        self.grid_info = Grid(self, self, (('field', 'FIELD', 190, 'w'), ('value', 'VALUE', 700, 'w')), hscroll=False)
        lay.addWidget(self.grid_info, 1)
        g = self.grid_info
        g.initial = self._info_initial
        g.long_text = lambda iid, col: len(str(self.doc.current['standard'].get(iid[1:], '') or '')) > 70
        g.on_edit = lambda iid, col, text: (self.doc.edit_info(iid[1:], text), self.refresh())
        g.tip_for = lambda iid, col: self.report.text_for('info', iid[1:]) if self.report else ''
        self.info_derived = _wrapped('', 'hint')
        lay.addWidget(self.info_derived)

    def _build_list_tab(self, area, columns):
        lay = self._page_layout(area)
        g = Grid(self, self, columns)
        lay.addWidget(g, 1)
        setattr(self, 'grid_' + area, g)
        g.initial = lambda iid, col, a=area: self._list_initial(a, iid, col)
        g.long_text = lambda iid, col, a=area: col in ('limit', 'what')
        g.on_edit = lambda iid, col, text, a=area: self._list_edit(a, iid, col, text)
        g.tip_for = lambda iid, col, a=area: self.report.text_for(a, int(iid[1:])) if self.report else ''
        row = QHBoxLayout()
        b1, b2 = SecondaryButton('Add entry'), SecondaryButton('Delete entry')
        b1.clicked.connect(lambda _c=False, a=area: self.add_list(a))
        b2.clicked.connect(lambda _c=False, a=area: self.delete_list(a))
        row.addWidget(b1)
        row.addWidget(b2)
        hint = ('The limits written on the sheet (page, text); information for the reader of the sheet.' if area == 'limits' else
                'Problems found when the sheet was read (level, where, what). They are not recomputed by an edit; see the checks on the right for new ones.')
        row.addWidget(_wrapped(hint, 'hint'), 1)
        lay.addLayout(row)

    # ---- tabs
    def select_tab(self, key: str) -> None:
        self.tabbar.setCurrentIndex(TAB_KEYS.index(key))

    def current_tab(self) -> str:
        return TAB_KEYS[self.tabbar.currentIndex()]

    # ---- state helpers
    @property
    def doc(self):
        return self.docs.get(self.cur)

    def say(self, text, kind=''):
        self.msg.setText(text)
        _tone(self.msg, 'bad' if kind == 'error' else ('warn' if kind == 'warn' else 'muted'))
        mark = 'error' if kind == 'error' else ('warn' if kind == 'warn' else '')
        self.msg_icon.setPixmap(mark_pixmap(mark) if mark and text else QPixmap())
        self.msg_kind = kind

    def message(self) -> str:
        return self.msg.text()

    def select_sheet(self, name):
        if name not in [p.name for p, _, _ in self.sheets]:
            return
        for i in range(self.sheet_list.count()):
            if self.sheet_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.sheet_list.setCurrentRow(i)
                break
        self._sheet_picked()

    def _sheet_picked(self):
        it = self.sheet_list.currentItem()
        sel = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not sel or sel == self.cur:
            return
        self.cur = sel
        if self.cur not in self.docs:
            path = next(p for p, _, _ in self.sheets if p.name == self.cur)
            try:
                self.docs[self.cur] = se.SpecDoc.load(path)
                self.errors_of_load.pop(self.cur, None)
            except (se.SpecFileError, OSError) as e:
                self.errors_of_load[self.cur] = str(e)
        self.refresh()

    def _all_grids(self):
        return (self.grid_rows, self.grid_notes, self.grid_info, self.grid_limits, self.grid_issues)

    # ---- refreshing everything from the document
    def refresh(self):
        doc = self.doc
        for g in self._all_grids():
            g._close_entry(commit=False)
        if doc is None:
            self.report = None
            self.path_label.setText(self.errors_of_load.get(self.cur, ''))
            for b in self.btn.values():
                b.setEnabled(False)
            self._fill_pending()
            return
        self.report = se.validate(doc)
        self.path_label.setText(f'specs/standards/{doc.name}')
        self._fill_rows()
        self._fill_notes()
        self._fill_info()
        self._fill_list('limits', self.grid_limits, 'limit')
        self._fill_list('issues', self.grid_issues, 'problem')
        self._fill_pending()
        self._tab_titles()
        self._buttons()
        self._status_line()
        self._sheet_marks()
        self._selection_changed(self.grid_rows)

    def _unsaved(self):
        return sum(d.change_count() for d in self.docs.values())

    def _buttons(self):
        doc = self.doc
        n = doc.change_count()
        ok = self.report.can_save and n > 0
        self.btn['save'].setEnabled(ok)
        self.btn['discard'].setEnabled(bool(n))
        self.btn['history'].setText(f'Edit history ({elog.count(doc.name, self.db_path)})')
        total = self._unsaved()
        if total:
            self.pill.set(f'{total} unsaved change{"s" if total != 1 else ""}' + ('' if n == total else f' ({n} in this sheet)'), 'warn')
        else:
            self.pill.set('No unsaved changes', 'neutral')
        self.btn['save'].setText(_amp(SAVE_TEXT))

    def _sheet_marks(self):
        t = theme.tokens()
        for i, (path, model, _) in enumerate(self.sheets):
            d = self.docs.get(path.name)
            dirty = bool(d and d.change_count())
            st = eio.sheet_state(path, self.db_path)
            hand = st['state'] in ('edited by hand', 'changed outside')
            it = self.sheet_list.item(i)
            it.setText((model or path.name) + ('  ●' if dirty else '') + ('  (edited)' if hand else ''))
            it.setForeground(QColor(t['warn'] if dirty else (t['info'] if hand else t['text'])))

    def sheet_label(self, name: str) -> str:
        for i, (path, _m, _d) in enumerate(self.sheets):
            if path.name == name:
                return self.sheet_list.item(i).text()
        return ''

    def tab_title(self, key: str) -> str:
        return self.tabbar.tabText(TAB_KEYS.index(key))

    def _tab_titles(self):
        doc, rep = self.doc, self.report

        def mark(area, base):
            worst = ''
            for i in rep.issues:
                if i.area == area:
                    if i.level == 'error':
                        worst = 'error'
                        break
                    if i.level == 'warn':
                        worst = 'warn'
            return base + ('  (!)' if worst == 'error' else ('  (?)' if worst == 'warn' else ''))
        for key, text in (('rows', mark('rows', f'Rows ({len(doc.ranges())})')), ('notes', mark('notes', f'Notes ({len(doc.current.get("notes") or {})})')),
                          ('info', mark('info', 'Standard info')), ('limits', mark('limits', f'Limits ({len(doc.list_nodes("limits"))})')),
                          ('issues', mark('issues', f'Sheet issues ({len(doc.list_nodes("issues"))})'))):
            self.tabbar.setTabText(TAB_KEYS.index(key), text)

    def _status_line(self):
        doc = self.doc
        std = doc.current.get('standard', {})
        pct = std.get('confidence_pct')
        div = f'{se.divisor_for(pct)[0]:g}' if isinstance(pct, (int, float)) else '2 (assumed)'
        st = eio.sheet_state(doc, self.db_path)
        last = st['last']
        built = ', '.join(n for n, _ in st.get('builders') or [])
        parts = [f'Confidence {pct:g} %' if isinstance(pct, (int, float)) else 'Confidence not specified', f'divisor {div}', f'revision {std.get("revision", "") or "-"}',
                 f'last saved edit: {last["at"][:10]}' if last else 'no documented edit yet']
        if built:
            parts.append(f'built by specs/{built}')
        self.status.setText('  ·  '.join(parts) + ('   [edited by hand since built]' if st['state'] == 'edited by hand' else ''))

    # ---- rows tab
    def _display_cols(self):
        doc = self.doc
        has_fs = any((s.get('fs_rel') or s.get('fs_value')) for _, r in doc.ranges() for s in r.get('specs') or [] if isinstance(s, dict))
        return [c[0] for c in COLS if has_fs or c[0] not in ('fs_rel', 'fs_value')]

    def displayed_columns(self) -> list:
        t = self.grid_rows.table
        return [c.key for i, c in enumerate(t.source_model.columns) if c.key != '_mark' and not t.isColumnHidden(i)]

    def _range_kind(self, rng) -> str:
        return str(rng.get('kind') or 'OTHER')

    def _build_kind_chips(self):
        """All / DCV / ACV ... chips with the number of rows of each, the same chips as the Standards Specs view; rebuilt only when the counts change."""
        specs = view.kind_chips([{'kind': self._range_kind(r)} for _f, r in self.doc.ranges()])
        if self.row_kind not in {c[0] for c in specs}:
            self.row_kind = ''
        key = (tuple((c[0], c[1], c[2]) for c in specs), self.row_kind)
        if key == self._kind_specs:
            return
        self._kind_specs = key
        flt = SegmentedFilter([(code, text, n) for code, text, n, _full in specs])
        for code, _text, _n, full in specs:
            flt._buttons[code].setToolTip(full)
        flt.set_current(self.row_kind)
        flt.currentChanged.connect(self.set_row_kind)
        self.kind_filter = flt
        self.kind_scroll.setWidget(flt)
        flt.adjustSize()
        self.kind_scroll.setFixedHeight(flt.sizeHint().height() + (self.kind_scroll.horizontalScrollBar().sizeHint().height() if flt.sizeHint().width() > self.kind_scroll.width() > 0 else 2))

    def set_row_kind(self, code: str) -> None:
        """Show only the rows of one function type ('' = all)."""
        if code != self.row_kind:
            self.row_kind = code
            if self.doc is not None:
                self._fill_rows()

    def row_kind_codes(self) -> list:
        return list(self.kind_filter._buttons) if self.kind_filter else []

    def _fill_rows(self):
        g, doc, rep = self.grid_rows, self.doc, self.report
        self._build_kind_chips()
        shown = self._display_cols()
        for i, c in enumerate(g.table.source_model.columns):
            g.table.setColumnHidden(i, c.key not in shown and c.key != '_mark')
        changed = doc.changed_cells()
        new_uids = doc.new_range_uids()
        changed_iids = {i for i, _ in changed}
        shade = 0
        last_r = None
        rows = []
        for ln in doc.lines():
            if self.row_kind and self._range_kind(ln.rng) != self.row_kind:
                continue
            ru = doc.uid(ln.rng)
            if ru != last_r:
                shade += 1
                last_r = ru
            worst = rep.worst('rows', ru)
            tags = set()
            if ru in new_uids:
                tags.add('new')
            if worst == 'error':
                tags.add('err')
            elif worst == 'warn':
                tags.add('warn')
            elif not ln.first:
                tags.add('cont')
            mark = 'error' if worst == 'error' else ('warn' if worst == 'warn' else ('new' if ru in new_uids else ('changed' if ln.iid in changed_iids else '')))
            rows.append(GridRow(ln.iid, {c[0]: doc.cell_text(ln, c[0]) for c in COLS}, tags, mark, bool(shade % 2)))
        g.set_rows(rows)
        g.set_changed(changed)
        if not g.selected_iids() and rows:
            g.select(rows[0].iid, emit=False)

    def _rows_initial(self, iid, col):
        doc = self.doc
        ln = doc.line(iid)
        if ln is None or col not in [c[0] for c in COLS]:
            return None
        if col in RANGE_LEVEL and not ln.first:
            self.say('That column belongs to the whole row: edit it on the first line of the row.', 'warn')
            return None
        if col in ('period', 'rel', 'fs_rel', 'fs_value', 'abs') and ln.spec is None:
            self.say('This row has no specification line; use "Add period line".', 'warn')
            return None
        return doc.cell_text(ln, col)

    def _edit_row_cell(self, iid, col, text):
        keys = self.doc.edit_cell(iid, col, text)
        self.refresh()
        if self.grid_rows.exists(iid):
            self.grid_rows.select(iid)
        return keys

    def _rows_tip(self, iid, col):
        doc, rep = self.doc, self.report
        ln = doc.line(iid) if doc else None
        if ln is None or rep is None:
            return ''
        issue = rep.text_for('rows', doc.uid(ln.rng))
        return issue or (doc.cell_text(ln, col) if col in [c[0] for c in COLS] and len(doc.cell_text(ln, col)) > 9 else '')

    def _selected_line(self):
        sel = self.grid_rows.selected_iids()
        return self.doc.line(sel[0]) if sel and self.doc else None

    def _selection_changed(self, grid):
        if grid is not self.grid_rows or not self.doc:
            return
        ln = self._selected_line()
        has = ln is not None
        for k in ('delete', 'addp', 'details', 'add'):
            self.btn[k].setEnabled(has)
        self.btn['delp'].setEnabled(bool(has and ln.spec is not None and len(ln.rng.get('specs') or []) > 1))
        self.btn['revert'].setEnabled(has)
        text, bad = '', False
        if has and self.report:
            text = self.report.text_for('rows', self.doc.uid(ln.rng))
            bad = any(i.level == 'error' for i in self.report.row_issues(self.doc.uid(ln.rng)))
        self.row_issue.setText(text)
        _tone(self.row_issue, 'bad' if bad else 'warn')
        self.detail_text = text

    # ---- notes tab
    def _note_usage(self):
        use = {}
        for _, r in self.doc.ranges():
            for n in self.doc.range_notes(r):
                use[str(n)] = use.get(str(n), 0) + 1
        return use

    def _fill_notes(self):
        g, doc, rep = self.grid_notes, self.doc, self.report
        use = self._note_usage()
        changed = {(f'n{c.uid}', 'text') for c in doc.changes_of('notes') if c.op == 'set'}
        added = {f'n{c.uid}' for c in doc.changes_of('notes') if c.op == 'add'}
        rows = []
        for k in sorted(doc.current.get('notes') or {}, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, 0)):
            worst = rep.worst('notes', str(k))
            tags = {'err'} if worst == 'error' else ({'warn'} if worst == 'warn' else set())
            mark = 'error' if worst == 'error' else ('warn' if worst == 'warn' else ('new' if f'n{k}' in added else ('changed' if (f'n{k}', 'text') in changed else '')))
            text = str(doc.current['notes'][k]).replace('\n', ' ')
            rows.append(GridRow(f'n{k}', {'no': str(k), 'text': text, 'used': f'{use.get(str(k), 0)} rows'}, tags, mark))
        g.set_rows(rows)
        g.set_changed(changed | {(i, 'text') for i in added})

    def add_note(self):
        if not self.doc:
            return
        k = self.doc.add_note('')
        self.refresh()
        self.select_tab('notes')
        self.grid_notes.select(f'n{k}')
        self.grid_notes.begin_edit(f'n{k}', 'text')

    def delete_note(self):
        sel = self.grid_notes.selected_iids()
        if not sel or not self.doc:
            return
        n = self._note_usage().get(sel[0][1:], 0)
        if n and not ask_yes_no(self, 'Delete note', f'Note {sel[0][1:]} is used by {n} row(s); they will show a missing-note error until fixed.\n\nDelete it?'):
            return
        self.doc.delete_note(sel[0][1:])
        self.refresh()

    # ---- standard info tab
    def _info_keys(self):
        std = self.doc.current.get('standard') or {}
        return list(se.INFO_FIELDS) + [k for k in std if k not in se.INFO_FIELDS]

    def _fill_info(self):
        g, doc, rep = self.grid_info, self.doc, self.report
        std = doc.current.get('standard') or {}
        changed = {(f'i{c.uid}', 'value') for c in doc.changes_of('info') if c.node == 'info'}
        rows = []
        for k in self._info_keys():
            v = std.get(k)
            worst = rep.worst('info', k)
            tags = {'err'} if worst == 'error' else ({'warn'} if worst == 'warn' else set())
            mark = 'error' if worst == 'error' else ('warn' if worst == 'warn' else ('changed' if (f'i{k}', 'value') in changed else ''))
            shown = '' if v is None else str(v)
            if k in se.READ_ONLY_INFO:
                shown += '   (read-only: it identifies the sheet)'
            rows.append(GridRow(f'i{k}', {'field': k, 'value': shown.replace('\n', ' ')}, tags, mark))
        g.set_rows(rows)
        g.set_changed(changed)
        st = eio.sheet_state(doc, self.db_path)
        while self.info_notice.count():
            w = self.info_notice.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        kind = 'warn' if st['state'] in ('edited by hand', 'changed outside') else 'info'
        self.info_banner = _banner(eio.state_text(st), kind)
        self.info_notice.addWidget(self.info_banner)
        pct = std.get('confidence_pct')
        div = se.divisor_for(pct) if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
        lines = [f'Coverage divisor from the confidence level: {div[0]:g}' + ('' if div[1] else ' (nearest standard level)') if div else
                 'No confidence level: the divisor is 2 (k = 2 assumed); an explicit divisor set in Standards Specs wins over the sheet.']
        lines.append('Procedures whose fingerprint lists this file: ' + (', '.join(se.procedures_listing(doc.name)) or 'none'))
        lines.append(f'Current file SHA-256: {doc.sha}')
        self.info_derived.setText('\n'.join(lines))

    def _info_initial(self, iid, col):
        k = iid[1:]
        if col != 'value':
            return None
        if k in se.READ_ONLY_INFO:
            self.say('The model identifies the sheet in the database and cannot be edited here.', 'warn')
            return None
        v = self.doc.current['standard'].get(k)
        return '' if v is None else str(v)

    # ---- limits / issues tabs
    def _list_nodes(self, area):
        return self.doc.list_nodes('limits' if area == 'limits' else 'issues')

    def _fill_list(self, area, g, node):
        doc, rep = self.doc, self.report
        cols = [c[0] for c in g.cols]
        changes = doc.changes_of(area)
        changed = {(f'x{c.uid}', c.key) for c in changes if c.op == 'set'}
        added = {f'x{c.uid}' for c in changes if c.op == 'add'}
        rows = []
        for x in self._list_nodes(area):
            u = doc.uid(x)
            worst = rep.worst(area, u)
            tags = {'err'} if worst == 'error' else ({'warn'} if worst == 'warn' else set())
            if f'x{u}' in added:
                tags.add('new')
            mark = 'error' if worst == 'error' else ('new' if f'x{u}' in added else ('changed' if any(i == f'x{u}' for i, _ in changed) else ''))
            rows.append(GridRow(f'x{u}', {c: str(x.get(c, '')).replace('\n', ' ') for c in cols}, tags, mark))
        g.set_rows(rows)
        g.set_changed(changed | {(i, cols[0]) for i in added})

    def _list_node(self, iid):
        u = int(iid[1:])
        return next((x for x in self.doc.list_nodes('limits') + self.doc.list_nodes('issues') if self.doc.uid(x) == u), None)

    def _list_initial(self, area, iid, col):
        x = self._list_node(iid)
        return None if x is None else str(x.get(col, ''))

    def _list_edit(self, area, iid, col, text):
        x = self._list_node(iid)
        if x is None:
            raise se.EditError('that entry no longer exists')
        self.doc.edit_field(x, col, text)
        self.refresh()

    def add_list(self, area):
        if not self.doc:
            return
        x = self.doc.add_list_item(area)
        self.refresh()
        g = self.grid_limits if area == 'limits' else self.grid_issues
        g.select(f'x{self.doc.uid(x)}')

    def delete_list(self, area):
        g = self.grid_limits if area == 'limits' else self.grid_issues
        sel = g.selected_iids()
        if not sel:
            return
        x = self._list_node(sel[0])
        if x is not None:
            self.doc.delete_list_item(area, x)
            self.refresh()

    # ---- pending panel
    def _fill_pending(self):
        doc, rep = self.doc, self.report
        esc = html.escape
        p = self.pending
        _add_marks(p)
        self._links = {}
        if doc is None:
            p.setHtml('<body><p class="err">' + esc(self.errors_of_load.get(self.cur, 'Pick a sheet on the left.')) + '</p></body>')
            return
        out = []
        changes = doc.diff()
        out.append(f'<h3>Pending changes ({len(changes)})</h3>')
        if not changes:
            out.append('<p class="muted">Nothing changed yet. Double-click a cell to edit it.</p>')
        for n, c in enumerate(changes[:300]):
            self._links[f'revert:{n}'] = ('revert', c)
            out.append(f'<p style="margin-top:6px; margin-bottom:2px"><span class="muted">{esc(c.where)}</span><br><span class="muted">{esc(c.label)}</span><br>')
            if c.op == 'set':
                out.append(f'<s class="del">{esc(c.old_text or "(blank)")}</s> <span class="muted">&nbsp;&#8594;&nbsp;</span> <span class="add mono">{esc(c.new_text or "(blank)")}</span>')
            elif c.op == 'add':
                out.append(f'<span class="add mono">+ {esc(c.new_text or "added")}</span>')
            else:
                out.append(f'<s class="del">- {esc(c.old_text or "removed")}</s>')
            out.append(f'&nbsp;&nbsp;&nbsp;<a href="revert:{n}">revert</a></p>')
        if len(changes) > 300:
            out.append(f'<p class="muted">... and {len(changes) - 300} more (all are saved and listed in the history)</p>')
        out.append('<h3>Checks before save</h3>')
        css = {'ok': 'ok', 'warn': 'warnl', 'error': 'err', 'info': 'muted'}
        for level, text in rep.checks:
            out.append(f'<p style="margin-top:2px; margin-bottom:2px" class="{css[level]}">{_mark_img(level)}{esc(text)}</p>')
        shown = 0
        for i in rep.issues:
            if i.level not in ('error', 'warn') or i.code in ('budget',):
                continue
            shown += 1
            if shown > 40:
                break
            img = 'error' if i.level == 'error' else 'warn'
            msg = (i.message.rstrip('.') + (' (existing, does not block)' if i.existing else ' (blocks saving)')) if i.level == 'error' else i.message
            if i.area == 'rows' and i.target is not None:
                self._links[f'go:{shown}'] = ('row', i.target)
                body = f'<a href="go:{shown}" class="{"err" if i.level == "error" else "warnl"}">{esc(msg)}</a>'
            elif i.area in ('notes', 'info', 'limits', 'issues'):
                self._links[f'go:{shown}'] = ('tab', i.area)
                body = f'<a href="go:{shown}" class="{"err" if i.level == "error" else "warnl"}">{esc(msg)}</a>'
            else:
                body = esc(msg)
            out.append(f'<p style="margin-top:2px; margin-bottom:2px" class="{"err" if i.level == "error" else "warnl"}">{_mark_img(img)}{body}</p>')
        for i in rep.issues:
            if i.code == 'budget':
                out.append(f'<p style="margin-top:2px; margin-bottom:2px" class="warnl">{_mark_img("warn")}{esc(i.message)}</p>')
        listed = se.procedures_listing(doc.name)
        if doc.change_count():
            if listed:
                out.append('<p style="margin-top:2px; margin-bottom:2px" class="warnl">' + _mark_img('warn') + esc(
                    'Procedures that list this file in their fingerprint will show "Changed since verification": ' + ', '.join(listed) + '. Only you mark them verified again.') + '</p>')
            else:
                out.append('<p style="margin-top:2px; margin-bottom:2px" class="muted">' + _mark_img('info') + esc(
                    'Verified status: no procedure fingerprint lists this file, so no procedure flips to "Changed since verification" from saving it. '
                    'Only you mark a procedure verified.') + '</p>')
            for level, text in eio.database_notes(doc, self.db_path):
                out.append(f'<p style="margin-top:2px; margin-bottom:2px" class="{"warnl" if level == "warn" else "muted"}">{_mark_img("warn" if level == "warn" else "info")}{esc(text)}</p>')
        out.append('<p class="muted" style="margin-top:10px">A reason, your name and the source are required before the edit can be saved.</p>')
        p.setHtml('<body>' + ''.join(out) + '</body>')

    def pending_text(self):
        return self.pending.toPlainText()

    def _pending_link(self, url):
        kind = self._links.get(url.toString())
        if not kind:
            return
        what, arg = kind
        if what == 'revert':
            self._revert(arg)
        elif what == 'row':
            self.goto_row(arg)
        elif what == 'tab':
            self.select_tab(arg)

    def pending_link_keys(self) -> list:
        return list(self._links)

    def click_pending(self, key: str) -> None:
        """Follow a link of the pending panel the way a click does (revert:N, go:N)."""
        self._pending_link(QUrl(key))

    def goto_row(self, range_uid):
        self.select_tab('rows')
        for ln in self.doc.lines():
            if self.doc.uid(ln.rng) == range_uid:
                self.grid_rows.select(ln.iid)
                return

    # ---- actions
    def _revert(self, change):
        try:
            self.doc.revert(change)
        except se.EditError as e:
            self.say(str(e), 'error')
        self.refresh()

    def revert_selected(self):
        ln = self._selected_line()
        g = self.grid_rows
        col = g.selected_col
        if ln is None or not col:
            self.say('Select a cell first.', 'warn')
            return
        n = 0
        cols_keys = {'label': ('label',), 'span': ('amp_lo', 'amp_hi'), 'freq': ('freq_lo', 'freq_hi'), 'res': ('resolution', 'res_src'), 'page': ('page',),
                     'period': ('period',), 'rel': ('rel',), 'fs_rel': ('fs_rel',), 'fs_value': ('fs_value',), 'abs': ('abs',), 'function': ('name',), 'notes': ('notes',)}
        keys = cols_keys.get(col, ())
        ru = self.doc.uid(ln.rng)
        for c in list(self.doc.diff()):
            if c.area != 'rows' or c.op != 'set' or c.key not in keys:
                continue
            if c.node in ('range',) and c.uid == ru or c.node == 'param' and c.range_uid == ru or c.node == 'function' and c.uid == self.doc.uid(ln.fn) or (
                    c.node == 'spec' and ln.spec is not None and c.uid == self.doc.uid(ln.spec)):
                self.doc.revert(c)
                n += 1
        if not n:
            self.say('That cell has not been changed.', 'warn')
        self.refresh()

    def discard_all(self):
        if not self.doc or not self.doc.change_count():
            return
        if not ask_yes_no(self, 'Discard all changes', f'Throw away the {self.doc.change_count()} pending change(s) of this sheet?'):
            return
        self.doc.discard_all()
        self.refresh()

    def add_row(self):
        ln = self._selected_line()
        if ln is None:
            return
        new = self.doc.add_range_after(ln.rng)
        self.refresh()
        self.goto_row(self.doc.uid(new))
        self.say('A copy of the row was added after it: change its values (the red / amber marks say what is still the same).', 'warn')

    def delete_row(self):
        ln = self._selected_line()
        if ln is None:
            return
        lab = ln.rng.get('label', '')
        if not ask_yes_no(self, 'Delete row', f'Delete the row "{lab}" of "{ln.fn.get("name", "")}"?\n\nIt stays in the file until you document and save; '
                                              'the deletion is listed on the right and can be reverted.'):
            return
        self.doc.delete_range(ln.rng)
        self.refresh()

    def add_period(self):
        ln = self._selected_line()
        if ln is None:
            return
        self.doc.add_spec_line(ln.rng)
        self.refresh()
        self.say('A period line was added with an empty period: type it in the PERIOD cell.', 'warn')

    def delete_period(self):
        ln = self._selected_line()
        if ln is None or ln.spec is None:
            return
        try:
            self.doc.delete_spec_line(ln.rng, ln.spec)
        except se.EditError as e:
            self.say(str(e), 'error')
            return
        self.refresh()

    def row_details(self):
        ln = self._selected_line()
        if ln is None:
            return None
        return DetailsDialog(self, ln)

    def document_and_save(self):
        if not self.doc or not self.doc.change_count():
            return None
        if not self.report.can_save:
            self.say(f'{len(self.report.new_errors)} error(s) introduced by this edit must be fixed first (red rows).', 'error')
            return None
        return SaveDialog(self)

    def saved(self, result):
        self.refresh()
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass

    def open_history(self):
        if not self.doc:
            return None
        if self.history_window is not None and self.history_window.alive():
            self.history_window.win.raise_()
            self.history_window.win.activateWindow()
            return self.history_window
        self.history_window = HistoryWindow(self, self.doc.name, self.doc.model, db_path=self.db_path, spec_dir=self.spec_dir, backup_dir=self.backup_dir, editor=self)
        return self.history_window

    # ---- closing: unsaved edits are asked about (the Tk window did this on its close box)
    def closeEvent(self, ev):
        n = self._unsaved()
        if n and not ask_yes_no(self, 'Close the editor', f'{n} change(s) have not been saved and will be lost.\n\nClose anyway?'):
            ev.ignore()
            return
        for g in self._all_grids():
            g._close_entry(commit=False)
        if self.history_window is not None and self.history_window.alive():
            self.history_window.win.close()
        for k, v in list(_OPEN.items()):
            if v is self:
                del _OPEN[k]
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(ev)

    def alive(self) -> bool:
        try:
            return self.isVisible()
        except RuntimeError:
            return False


# ------------------------------------------------------------------------------------------------------------------------ row details
class DetailsDialog:
    """Every field of one row (range, its period lines, its value-range blocks, its function) as typed text; applied through the same checks as a cell."""

    def __init__(self, editor: EditorWindow, line):
        self.ed, self.doc = editor, editor.doc
        self.line = line
        title = f'Row details: {line.rng.get("label", "")}'
        self.dlg = self.win = ModalDialog(editor, title, width=760, modal=True)
        self.win.setWindowTitle(_title(title))
        self.win.title_label.hide()
        self.win.setMinimumHeight(560)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.form = QGridLayout(holder)
        self.form.setContentsMargins(0, 0, M.md, 0)
        self.form.setColumnStretch(1, 1)
        self.form.setHorizontalSpacing(M.md)
        self.form.setVerticalSpacing(M.xs + 2)
        scroll.setWidget(holder)
        self.win.body.addWidget(scroll, 1)
        self.fields = []        # (node, key, QLineEdit, original text, error label)
        self.row = 0
        self._section('Function (shared by every row of it)')
        self._node_fields(line.fn, se.FUNCTION_FIELDS)
        self._section('Row')
        self._node_fields(line.rng, se.RANGE_FIELDS, optional=se.OPTIONAL_RANGE_KEYS)
        for i, p in enumerate([x for x in line.rng.get('params') or [] if isinstance(x, dict)], 1):
            self._section(f'Value range {i} (the raw parse of the printed range; its note references are what the application uses)')
            self._node_fields(p, se.PARAM_FIELDS)
        for s in [x for x in line.rng.get('specs') or [] if isinstance(x, dict)]:
            self._section(f'Period line "{s.get("period", "")}"')
            self._node_fields(s, se.SPEC_FIELDS)
        self.error = label('', None, wrap=True)
        _tone(self.error, 'bad')
        self.win.body.addWidget(self.error)
        self.win.add_button('Close', cancel=True)
        self.win.add_button('Apply', role='primary', default=True, close=False, callback=self.apply)
        self.win.show()

    def _section(self, text):
        lab = label(text, 'section', wrap=True)
        lab.setContentsMargins(0, M.md if self.row else 0, 0, 0)
        self.form.addWidget(lab, self.row, 0, 1, 3)
        self.row += 1

    def _text(self, node, key, typ, unit):
        v = node.get(key)
        if v is None:
            return ''
        if typ in ('ratio',):
            return se.fmt_ratio(v)
        if typ in ('qty?', 'sqty', 'pqty?'):
            return se.fmt_quantity(v, unit)
        if typ == 'hz?':
            return se.fmt_quantity(v, 'Hz')
        if typ == 'json':
            return json.dumps(v, ensure_ascii=False)
        if typ == 'ints':
            return ', '.join(str(x) for x in v)
        if typ == 'bool':
            return 'true' if v else 'false'
        return str(v)

    def _node_fields(self, node, table, optional=()):
        unit = node.get('unit') or ''
        if table is se.SPEC_FIELDS:
            unit = node.get('unit') or self.line.rng.get('unit') or ''
        for key, typ in table.items():
            if key not in node and key not in optional and key not in ('page',):
                continue
            lab = label(se.KEY_LABEL.get(key, key), 'hint')
            ent = QLineEdit(self._text(node, key, typ, unit))
            err = label('', None)
            _tone(err, 'bad')
            self.form.addWidget(lab, self.row, 0)
            self.form.addWidget(ent, self.row, 1)
            self.form.addWidget(err, self.row, 2)
            self.fields.append((node, key, ent, ent.text(), err))
            self.row += 1

    def set_field(self, key, text, index=0):
        """Type `text` into the n-th field called `key` (used by tests)."""
        hits = [f for f in self.fields if f[1] == key]
        hits[index][2].setText(text)

    def apply(self):
        bad = 0
        for node, key, ent, orig, err in self.fields:
            err.setText('')
            if ent.text() == orig:
                continue
            try:
                self.doc.edit_field(node, key, ent.text())
            except se.EditError as e:
                err.setText(str(e))
                bad += 1
        self.error.setText(f'{bad} field(s) not applied (see the red text).' if bad else '')
        self.ed.refresh()
        if not bad:
            self.win.accept()
        return not bad

    def close(self):
        self.win.close()


# ------------------------------------------------------------------------------------------------------------------------ document & save
def _field_label(text: str) -> QLabel:
    return label(text, 'section')


def _multiline(rows: int = 3) -> QTextEdit:
    e = QTextEdit()
    e.setAcceptRichText(False)
    e.setTabChangesFocus(True)
    e.setFixedHeight(rows * 20 + 16)
    return e


class SaveDialog:
    """'Document this edit': reason, source and name are required; a diff preview; backup and rebuild options."""

    def __init__(self, editor: EditorWindow):
        self.ed, self.doc = editor, editor.doc
        self.win = self.dlg = ModalDialog(editor, 'Document this edit', subtitle=f'{self.doc.model or self.doc.name}  ·  {self.doc.summary()}. '
                                          'This is saved with the log and printed in the edit history.', width=720, modal=True)
        w = self.win
        w.setWindowTitle(_title('Document this edit'))
        self.preview = _diff_box(self.doc.diff())
        w.body.addWidget(self.preview)
        w.body.addWidget(_field_label('Reason for the change *'))
        self.reason = _multiline(3)
        w.body.addWidget(self.reason)
        row = QHBoxLayout()
        row.setSpacing(M.md)
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        c1.setSpacing(M.xs)
        c2.setSpacing(M.xs)
        c1.addWidget(_field_label('Source / reference *'))
        c2.addWidget(_field_label('Edited by *'))
        self.source = QLineEdit()
        self.who = QLineEdit(elog.last_editor(editor.db_path) or self._login())
        self.who.setMinimumWidth(190)
        c1.addWidget(self.source)
        c2.addWidget(self.who)
        row.addLayout(c1, 1)
        row.addLayout(c2)
        w.body.addLayout(row)
        backup_name = eio.next_backup(self.doc.name, editor.backup_dir).name
        self.backup_cb = QCheckBox(f'Save a backup of the previous spec file ({backup_name})')
        self.backup_cb.setChecked(True)
        self.rebuild_cb = QCheckBox('Rebuild the standards sheet from the edited spec (keeps assets, divisor and Standards Specs edits)')
        self.rebuild_cb.setChecked(True)
        w.body.addWidget(self.backup_cb)
        w.body.addWidget(self.rebuild_cb)
        notes = []
        listed = se.procedures_listing(self.doc.name)
        if listed:
            notes.append('Procedures that list this file in their fingerprint will show "Changed since verification": ' + ', '.join(listed) + '. Only you mark them verified again.')
        else:
            notes.append('Procedures that use this standard: no procedure fingerprint lists this file, so none flips to "Changed since verification" from this save. '
                         'Only you mark a procedure verified.')
        old = editor.report.existing_errors
        if old:
            notes.append(f'{len(old)} error{"s" if len(old) != 1 else ""} already in this sheet (not from this edit) stay red and are saved as they are: '
                         + '; '.join(i.message.rstrip('.') for i in old[:3]) + ('; ...' if len(old) > 3 else '') + '.')
        builders = se.builders_for(self.doc.name)
        if builders:
            notes.append('Running ' + ', '.join(n for n, _ in builders) + ' again will overwrite this edit (the builder rewrites the whole file). The history marks the sheet as edited by hand.')
        for level, text in eio.database_notes(self.doc, editor.db_path):
            notes.append(text)
        self.notice = _banner(' '.join(notes), 'warn')
        w.body.addWidget(self.notice)
        self.error_label = _wrapped('')
        _tone(self.error_label, 'bad')
        w.body.addWidget(self.error_label)
        w.add_button('Cancel', cancel=True)
        self.save_btn = w.add_button('Save edit', role='primary', default=True, close=False, callback=self.save)
        w.initial_focus = self.reason
        self.result = None
        w.show()

    @property
    def error_text(self) -> str:
        return self.error_label.text()

    def set_texts(self, reason: str, source: str, who: str | None = None) -> None:
        self.reason.setPlainText(reason)
        self.source.setText(source)
        if who is not None:
            self.who.setText(who)

    @staticmethod
    def _login():
        import verified
        return verified.default_who()

    def save(self):
        reason = self.reason.toPlainText().strip()
        source, who = self.source.text().strip(), self.who.text().strip()
        missing = [n for n, v in (('a reason', reason), ('a source / reference', source), ('your name', who)) if not v]
        if missing:
            self.error_label.setText('Cannot save yet: ' + ', '.join(missing) + (' is required.' if len(missing) == 1 else ' are required.'))
            (self.reason if not reason else (self.source if not source else self.who)).setFocus()
            return None
        self.error_label.setText('')
        self.save_btn.setEnabled(False)
        try:
            res = eio.save_edit(self.doc, edited_by=who, reason=reason, source=source, backup=self.backup_cb.isChecked(), rebuild=self.rebuild_cb.isChecked(),
                                db_path=self.ed.db_path, backup_dir=self.ed.backup_dir)
        except eio.SaveError as e:
            self.win.accept()
            show_error(self.ed, 'Edit not saved', str(e) + ('' if e.file_changed else '\n\nNothing was written; the pending changes are still in the editor.'))
            self.ed.refresh()
            return None
        self.result = res
        self.win.accept()
        show_info(self.ed, 'Edit saved', '\n\n'.join(res.messages))
        self.ed.saved(res)
        return res


# ------------------------------------------------------------------------------------------------------------------------ history
class HistoryWindow(QWidget):
    def __init__(self, parent, spec_file, model, db_path=None, spec_dir=None, backup_dir=None, editor=None):
        super().__init__(None, Qt.WindowType.Window)
        self.win = self
        self.spec_file, self.model, self.db_path, self.spec_dir, self.backup_dir, self.editor = spec_file, model, db_path, spec_dir, backup_dir, editor
        self.setWindowTitle(_title('Edit history'))
        self.compare_window = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QFrame()
        head.setProperty('surface', 'bar')
        hl = QHBoxLayout(head)
        hl.setContentsMargins(M.lg, M.md, M.lg, M.md)
        hl.setSpacing(M.md)
        hl.addWidget(label('Edit history', 'h2'))
        self.head_label = label('', 'sub')
        hl.addWidget(self.head_label, 1)
        self.export_btn = SecondaryButton('Export history (PDF)' if eio.pdf_available() else 'Export history (CSV)')
        self.export_btn.clicked.connect(lambda _c=False: self.export())
        back = SecondaryButton('Back to editor')
        back.clicked.connect(lambda _c=False: self.close())
        hl.addWidget(self.export_btn)
        hl.addWidget(back)
        root.addWidget(head)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        cols = [Column('edit', 'EDIT', width=84), Column('when', 'WHEN', width=160), Column('who', 'BY', width=100),
                Column('reason', 'REASON', width=200, stretch=True)]
        self.table = DataTable(cols, [], multi=False, row_key=lambda r: r['iid'], alternating=False, empty_text='No documented edits yet')
        self.table.setFixedWidth(580)
        self.table.horizontalHeader().setSectionsClickable(False)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.selectionChangedRows.connect(lambda _r: self.show_entry())
        body.addWidget(self.table)
        right = QVBoxLayout()
        right.setContentsMargins(M.lg, M.md, M.lg, M.md)
        right.setSpacing(M.sm)
        self.title = label('', 'h2')
        right.addWidget(self.title)
        self.detail = _browser()
        self.detail.setFrameShape(QFrame.Shape.NoFrame)
        right.addWidget(self.detail, 1)
        bar = QHBoxLayout()
        self.compare_btn = SecondaryButton('Compare with current file')
        self.restore_btn = SecondaryButton('Restore the file as it was before this edit...')
        self.compare_btn.clicked.connect(lambda _c=False: self.compare())
        self.restore_btn.clicked.connect(lambda _c=False: self.restore())
        bar.addWidget(self.compare_btn)
        bar.addWidget(self.restore_btn)
        bar.addStretch(1)
        right.addLayout(bar)
        self.note = _wrapped('Restoring is itself a documented edit: it asks for a reason and adds a new entry. Entries are never removed or rewritten. '
                             'Running a builder script again overwrites hand edits; the state line above says whether that has happened.', 'hint')
        right.addWidget(self.note)
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        self.resize(1180, 680)
        self.setMinimumSize(QSize(900, 480))
        self.entries = []
        self.reload()
        self.show()

    def alive(self):
        try:
            return self.isVisible()
        except RuntimeError:
            return False

    @property
    def path(self):
        return Path(self.spec_dir or se.STANDARDS_DIR) / self.spec_file

    def state(self):
        return eio.sheet_state(self.path, self.db_path)

    def entry_ids(self) -> list:
        return [r['iid'] for r in self.table.rows()]

    def reload(self):
        self.entries = elog.entries(self.spec_file, self.db_path)
        rows = []
        for e in self.entries:
            kind = 'Restore' if e['kind'] == 'restore' else 'Edit'
            rows.append({'iid': str(e['id']), 'edit': f'{kind} {e["id"]}', 'when': e['at'].replace('T', ' ')[:16], 'who': e['edited_by'], 'reason': e['reason'].replace('\n', ' ')})
        self.table.set_rows(rows, keep_selection=False)
        self.head_label.setText(f'{self.model or self.spec_file}  ·  {len(self.entries)} documented edit{"s" if len(self.entries) != 1 else ""}')
        self.state_text = eio.state_text(self.state())
        if rows:
            self.select_entry(rows[0]['iid'])
        else:
            self.show_entry()

    def select_entry(self, iid) -> None:
        r = next((x for x in self.table.rows() if x['iid'] == str(iid)), None)
        if r is not None:
            self.table.select_rows([r])
        self.show_entry()

    def selected(self):
        sel = self.table.selected_rows()
        return elog.entry(int(sel[0]['iid']), self.db_path) if sel else None

    def show_entry(self):
        e = self.selected()
        d = self.detail
        _add_marks(d)
        esc = html.escape
        st = self.state()
        hand = st['state'] in ('edited by hand', 'changed outside')
        out = [f'<p class="{"warn" if hand else "muted"}">{esc(eio.state_text(st))}</p>']
        if e is None:
            self.title.setText('No documented edits yet')
            out.append('<p class="muted"><br>This sheet has not been edited with the editor.</p>')
            d.setHtml('<body>' + ''.join(out) + '</body>')
            self.compare_btn.setEnabled(False)
            self.restore_btn.setEnabled(False)
            return
        self.title.setText(f'{"Restore" if e["kind"] == "restore" else "Edit"} {e["id"]}  ·  {e["at"].replace("T", " ")}')
        for key, val, mono in (('Edited by', e['edited_by'], False), ('Reason', e['reason'], False), ('Source', e['source'], False),
                               ('Kind', e['kind'] + (f' (put the file back as it was before edit {e["restored_from"]})' if e['restored_from'] else ''), False),
                               ('Backup file', e['backup_file'] or '(none made)', True), ('SHA-256 before', e['sha_before'], True), ('SHA-256 after', e['sha_after'], True),
                               ('Summary', e['summary'], False)):
            out.append(f'<p style="margin-top:6px; margin-bottom:0"><span class="muted">{esc(key)}:</span> <span class="{"mono" if mono else ""}">{esc(val)}</span></p>')
        for ev in elog.events(e['id'], self.db_path):
            out.append(f'<p style="margin-top:6px; margin-bottom:0"><span class="muted">{esc(ev["event"])}:</span> {esc(ev["detail"])}</p>')
        out.append('<h3>Changes</h3>')
        out.append(_diff_html(e['diff'], 400).replace('... and', '... and'))
        d.setHtml('<body>' + ''.join(out) + '</body>')
        self.compare_btn.setEnabled(True)
        self.restore_btn.setEnabled(bool(elog.before_bytes(e['id'], self.db_path)))

    def compare(self):
        """The file as it was before the selected edit against the file now: everything that changed since (and including) that edit."""
        e = self.selected()
        if e is None:
            return None
        before = elog.before_bytes(e['id'], self.db_path)
        if before is None:
            show_warning(self, 'Compare', 'The earlier file is not stored for this edit.')
            return None
        try:
            now = self.path.read_bytes()
            changes = se.compare_data(json.loads(before.decode('utf-8')), json.loads(now.decode('utf-8')))
        except (OSError, ValueError) as ex:
            show_error(self, 'Compare', f'The current file cannot be read: {ex}')
            return None
        same = se.sha256_bytes(now) == e['sha_after']
        win = QWidget(None, Qt.WindowType.Window)
        win.setWindowTitle(_title(f'Compare: before edit {e["id"]} and the current file'))
        lay = QVBoxLayout(win)
        lay.setContentsMargins(M.lg, M.md, M.lg, M.lg)
        text = ('The current file is exactly what edit %d wrote.' % e['id'] if same else
                'The current file differs from what edit %d wrote (later edits, a restore, or a rebuild by a builder script).' % e['id']) + \
            f'  {len(changes)} difference(s) between the file before edit {e["id"]} and the file now.'
        win.summary = _wrapped(text)
        lay.addWidget(win.summary)
        win.box = _diff_box(changes, 1000)
        lay.addWidget(win.box, 1)
        win.resize(940, 600)
        win.show()
        self.compare_window = win
        return changes

    def restore(self):
        e = self.selected()
        if e is None:
            return None
        return RestoreDialog(self, e)

    def export(self):
        from datetime import datetime
        pdf = eio.pdf_available()
        stem = self.spec_file.rsplit('.', 1)[0]
        dest = ask_save_path(self, 'Export history', f'spec_edit_history_{stem}-{datetime.now():%m-%d-%Y}' + ('.pdf' if pdf else '.csv'), 'PDF (*.pdf)' if pdf else 'CSV (*.csv)')
        if not dest:
            return None
        try:
            n = eio.export_history_pdf(self.spec_file, dest, self.db_path, self.model, eio.state_text(self.state())) if pdf else eio.export_history_csv(self.spec_file, dest, self.db_path)
        except Exception as ex:                      # reportlab / file problems: say so, nothing else is affected
            show_error(self, 'Export history', f'The history could not be exported: {ex}')
            return None
        show_info(self, 'Export history', f'{n} edit(s) exported to {dest}.')
        return dest

    def closeEvent(self, ev):
        if self.compare_window is not None:
            try:
                self.compare_window.close()
            except RuntimeError:
                pass
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(ev)


class RestoreDialog:
    def __init__(self, hist: HistoryWindow, entry):
        self.hist, self.entry = hist, entry
        self.win = self.dlg = ModalDialog(hist, f'Restore the file as it was before edit {entry["id"]}', width=640, modal=True)
        w = self.win
        w.setWindowTitle(_title('Restore the file'))
        w.add_text('The sheet file is replaced by the earlier version (SHA-256 %s...). This is a new documented edit; the log keeps every entry, including this one.'
                   % entry['sha_before'][:12], 'sub')
        w.body.addWidget(_field_label('Reason *'))
        self.reason = _multiline(3)
        w.body.addWidget(self.reason)
        row = QHBoxLayout()
        row.setSpacing(M.md)
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        c1.setSpacing(M.xs)
        c2.setSpacing(M.xs)
        c1.addWidget(_field_label('Source / reference *'))
        c2.addWidget(_field_label('Edited by *'))
        self.source = QLineEdit(f'{eio.RESTORE_SOURCE} {entry["id"]}')
        self.who = QLineEdit(elog.last_editor(hist.db_path) or SaveDialog._login())
        self.who.setMinimumWidth(190)
        c1.addWidget(self.source)
        c2.addWidget(self.who)
        row.addLayout(c1, 1)
        row.addLayout(c2)
        w.body.addLayout(row)
        self.backup_cb = QCheckBox('Save a backup of the file as it is now')
        self.backup_cb.setChecked(True)
        self.rebuild_cb = QCheckBox('Rebuild the standards sheet in the database from the restored file')
        self.rebuild_cb.setChecked(True)
        w.body.addWidget(self.backup_cb)
        w.body.addWidget(self.rebuild_cb)
        self.error_label = _wrapped('')
        _tone(self.error_label, 'bad')
        w.body.addWidget(self.error_label)
        w.add_button('Cancel', cancel=True)
        w.add_button('Restore', role='primary', default=True, close=False, callback=self.restore)
        w.initial_focus = self.reason
        self.result = None
        w.show()

    @property
    def error_text(self) -> str:
        return self.error_label.text()

    def set_texts(self, reason: str, source: str | None = None, who: str | None = None) -> None:
        self.reason.setPlainText(reason)
        if source is not None:
            self.source.setText(source)
        if who is not None:
            self.who.setText(who)

    def restore(self):
        reason, source, who = self.reason.toPlainText().strip(), self.source.text().strip(), self.who.text().strip()
        missing = [n for n, v in (('a reason', reason), ('a source / reference', source), ('your name', who)) if not v]
        if missing:
            self.error_label.setText('Cannot restore yet: ' + ', '.join(missing) + (' is required.' if len(missing) == 1 else ' are required.'))
            return None
        try:
            res = eio.restore_edit(self.entry['id'], spec_dir=self.hist.spec_dir, edited_by=who, reason=reason, source=source, backup=self.backup_cb.isChecked(),
                                   rebuild=self.rebuild_cb.isChecked(), db_path=self.hist.db_path, backup_dir=self.hist.backup_dir)
        except eio.SaveError as e:
            self.win.accept()
            show_error(self.hist, 'Not restored', str(e))
            return None
        self.result = res
        self.win.accept()
        show_info(self.hist, 'Restored', '\n\n'.join(res.messages))
        self.hist.reload()
        ed = self.hist.editor
        if ed is not None:
            d = ed.docs.get(self.hist.spec_file)
            if d is not None:
                try:
                    d.rebase(d.path.read_bytes())
                except (OSError, ValueError):
                    ed.docs.pop(self.hist.spec_file, None)
            ed.refresh()
            ed.saved(res)
        return res


_OPEN: dict = {}


def open_editor(parent, model=None, on_saved=None, spec_dir=None, db_path=None, backup_dir=None):
    """Open (or raise) the editor on the sheet of `model`."""
    ed = _OPEN.get(id(parent))
    if ed is not None:
        try:
            if ed.isVisible():
                ed.raise_()
                ed.activateWindow()
                if model:
                    f = se.sheet_for_model(model, ed.spec_dir)
                    if f:
                        ed.select_sheet(f.name)
                return ed
        except RuntimeError:
            pass
    ed = EditorWindow(parent, model, on_saved=on_saved, spec_dir=spec_dir, db_path=db_path, backup_dir=backup_dir)
    _OPEN[id(parent)] = ed
    ed.show()
    return ed
