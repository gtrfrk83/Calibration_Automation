"""DataTable: the one table every screen uses (Manager, Asset History, Datasheet Builder, review window, spec editor, run queue).

    cols = [Column('name', 'Procedure', width=360, stretch=True),
            Column('status', 'Status', kind='badge', badge_map={'Ready': 'good', 'Failed': 'bad'}),
            Column('reading', 'Reading', align='right', mono=True, fmt=lambda v: f'{v:.4f}'),
            Column('std', 'Standard', kind='combo', choices=['Fluke 5560A', 'Fluke 5522A'], editable=True),
            Column('pick', '', kind='checkbox', editable=True, width=40),
            Column('done', 'Done', kind='progress')]
    t = DataTable(cols, rows, row_tone=lambda r: 'fail' if r['status'] == 'Failed' else None, row_key=lambda r: r['id'])
    t.selectionChangedRows.connect(on_rows);  t.set_filter_text('5560');  t.sort_by('name');  t.copy_selection()

Rows are any objects: dicts, objects (attributes), tuples / lists (the key may be an int), or whatever `Column.getter(row)` reads.  The table never copies them:
`selected_rows()` hands the same objects back.  Display formatting is done only for the cells painted (and for the search text, lazily, once per row), so
50,000 rows load in milliseconds.  Sorting is done in the model with precomputed keys (a Python key sort), filtering in a QSortFilterProxyModel; see
NOTES.md for the measured numbers.  No instrument or engine import here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, QSortFilterProxyModel, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QHeaderView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView)

from . import theme
from .theme import M

KINDS = ('text', 'badge', 'combo', 'checkbox', 'progress')
TONES = {'pass': 'good', 'fail': 'bad', 'warn': 'warn', 'info': 'info'}        # row tone -> palette kind
ROW_ROLE = Qt.ItemDataRole.UserRole + 1          # a RowRef holding the row object (use DataTable.row_of(index))
KEY_ROLE = Qt.ItemDataRole.UserRole + 2          # the column key
BADGE_ROLE = Qt.ItemDataRole.UserRole + 3        # badge kind of a cell
CHOICES_ROLE = Qt.ItemDataRole.UserRole + 4      # the list a combo cell offers
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 5     # 0.0 .. 1.0
_ALIGN = {'left': Qt.AlignmentFlag.AlignLeft, 'right': Qt.AlignmentFlag.AlignRight, 'center': Qt.AlignmentFlag.AlignHCenter}


@dataclass
class Column:
    key: Any                                   # dict key / attribute name / tuple index
    title: str = ''
    width: int = 120
    align: str = 'left'                        # 'left' | 'right' | 'center'
    fmt: Callable[[Any], str] | None = None    # raw value -> display text
    mono: bool = False                         # fixed-width font (readings, codes)
    bold: bool = False
    kind: str = 'text'                         # 'text' | 'badge' | 'combo' | 'checkbox' | 'progress'
    getter: Callable[[Any], Any] | None = None  # row -> raw value (default: by key)
    setter: Callable[[Any, Any], None] | None = None   # (row, value) -> store (default: by key)
    editable: bool | Callable[[Any], bool] = False     # bool, or row -> bool
    choices: Sequence | Callable[[Any], Sequence] | None = None   # combo: the options (or row -> options)
    badge_map: dict | None = None              # badge: text -> 'good' | 'warn' | 'bad' | 'info' | 'neutral'
    badge: Callable[[Any, Any], str] | None = None     # badge: (value, row) -> kind (overrides badge_map)
    tone: Callable[[Any], str | None] | None = None    # text colour of this cell: row -> 'good' | 'bad' | 'warn' | 'info' | 'muted' | None
    sort_key: Callable[[Any], Any] | None = None       # row -> sort key (default: the value)
    natural: bool = False                      # sort '3-9' before '3-12'
    stretch: bool = False                      # takes the free width (one column per table)
    searchable: bool = True                    # included in the text filter
    tooltip: Callable[[Any], str] | None = None
    min_width: int = 40

    def value(self, row) -> Any:
        if self.getter is not None:
            return self.getter(row)
        k = self.key
        if isinstance(row, dict):
            return row.get(k)
        if isinstance(k, int) and isinstance(row, (list, tuple)):
            return row[k] if -len(row) <= k < len(row) else None
        return getattr(row, k, None) if isinstance(k, str) else None

    def store(self, row, v) -> None:
        if self.setter is not None:
            self.setter(row, v)
        elif isinstance(row, dict) or (isinstance(row, list) and isinstance(self.key, int)):
            row[self.key] = v
        else:
            setattr(row, self.key, v)

    def text(self, row) -> str:
        v = self.value(row)
        if self.fmt is not None:
            try:
                return str(self.fmt(v))
            except Exception:
                return str(v)
        return '' if v is None else str(v)

    def is_editable(self, row) -> bool:
        e = self.editable
        return bool(e(row)) if callable(e) else bool(e)


_NOIDX = QModelIndex()
_NAT = re.compile(r'(\d+)')


def _natural(s: str):
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in _NAT.split(s.casefold()) if p != '']


_F_PLAIN = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
_F_EDIT = _F_PLAIN | Qt.ItemFlag.ItemIsEditable
_F_CHECK = _F_EDIT | Qt.ItemFlag.ItemIsUserCheckable


class RowRef:
    """What ROW_ROLE returns: Qt's variant conversion would copy a dict / list row, so the row object travels inside this holder (`.row`)."""
    __slots__ = ('row',)

    def __init__(self, row):
        self.row = row


class TableModel(QAbstractTableModel):
    """Rows + column specs.  Sorting happens here (`sort_rows`), filtering in the proxy on top."""
    cellEdited = Signal(object, object, object, object)      # row, column key, old value, new value
    editRequested = None                                      # optional hook: callable(row, key, old, new) -> bool; False rejects the edit

    def __init__(self, columns: Sequence[Column], rows: Sequence = (), parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self._rows: list = list(rows)
        self.row_tone: Callable[[Any], str | None] | None = None
        self.tone_style = 'both'
        self.edit_hook: Callable[[Any, Any, Any, Any], bool | None] | None = None
        self._hay: list[str | None] = [None] * len(self._rows)
        self._mono = theme.ui_font(mono=True)
        self._mono_bold = theme.ui_font(mono=True, weight=QFont.Weight.Bold)
        self._bold = None
        self._tint_cache: dict = {}
        theme.manager().changed.connect(self._theme_changed)

    # ---- structure
    def rowCount(self, parent=_NOIDX):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=_NOIDX):
        return 0 if parent.isValid() else len(self.columns)

    def rows(self) -> list:
        return self._rows

    def row_at(self, i: int):
        return self._rows[i]

    def set_rows(self, rows: Sequence) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._hay = [None] * len(self._rows)
        self.endResetModel()

    def set_columns(self, columns: Sequence[Column]) -> None:
        self.beginResetModel()
        self.columns = list(columns)
        self._hay = [None] * len(self._rows)
        self.endResetModel()

    def append_rows(self, rows: Sequence) -> None:
        rows = list(rows)
        if not rows:
            return
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n + len(rows) - 1)
        self._rows.extend(rows)
        self._hay.extend([None] * len(rows))
        self.endInsertRows()

    def remove_rows(self, rows: Iterable) -> None:
        gone = {id(r) for r in rows}
        keep = [r for r in self._rows if id(r) not in gone]
        if len(keep) != len(self._rows):
            self.set_rows(keep)

    def row_changed(self, row) -> None:
        for i, r in enumerate(self._rows):
            if r is row:
                self._hay[i] = None
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(self.columns) - 1))
                return

    def all_changed(self) -> None:
        if self._rows:
            self._hay = [None] * len(self._rows)
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.columns) - 1))

    def _theme_changed(self, *_):
        self._tint_cache.clear()
        self._mono = theme.ui_font(mono=True)
        self._mono_bold = theme.ui_font(mono=True, weight=QFont.Weight.Bold)

    # ---- search text (lazy, cached)
    def haystack(self, i: int) -> str:
        h = self._hay[i]
        if h is None:
            row = self._rows[i]
            h = '\x1f'.join(c.text(row) for c in self.columns if c.searchable and c.kind in ('text', 'badge', 'combo')).casefold()
            self._hay[i] = h
        return h

    # ---- data
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns):
            c = self.columns[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return c.title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(_ALIGN.get(c.align, Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
            if role == KEY_ROLE:
                return c.key
        return None

    def tone_of(self, row) -> str | None:
        if self.row_tone is None:
            return None
        try:
            t = self.row_tone(row)
        except Exception:
            return None
        return TONES.get(t, t if t in theme.KINDS else None)

    def _tint(self, kind: str) -> QColor:
        c = self._tint_cache.get(kind)
        if c is None:
            t = theme.tokens()
            c = self._tint_cache[kind] = QColor(theme.blend(t['table'], t[kind + '_bg'], 0.75))
        return c

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return None if col.kind in ('checkbox', 'progress') else col.text(row)
        if role == Qt.ItemDataRole.EditRole:
            return col.value(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_ALIGN.get(col.align, Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.FontRole:
            if col.mono:
                return self._mono_bold if col.bold else self._mono
            if col.bold:
                f = QFont(QApplication.font())
                f.setBold(True)
                return f
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            t = theme.tokens()
            if col.tone is not None:
                k = col.tone(row)
                if k:
                    return QColor(t['muted'] if k == 'muted' else t.get(k, t['text']))
            tone = self.tone_of(row)
            if tone and self.tone_style in ('text', 'both'):
                if self.tone_style == 'text' or tone in ('bad', 'warn'):
                    return QColor(t['row_' + {'good': 'pass', 'bad': 'fail', 'warn': 'warn'}.get(tone, 'pass') + '_fg'] if tone in ('good', 'bad', 'warn') else t[tone])
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            tone = self.tone_of(row)
            if tone and self.tone_style in ('tint', 'both'):
                return self._tint(tone)
            return None
        if role == Qt.ItemDataRole.CheckStateRole and col.kind == 'checkbox':
            return Qt.CheckState.Checked if col.value(row) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole and col.tooltip is not None:
            return col.tooltip(row)
        if role == ROW_ROLE:
            return RowRef(row)
        if role == KEY_ROLE:
            return col.key
        if role == BADGE_ROLE:
            if col.badge is not None:
                return col.badge(col.value(row), row)
            return (col.badge_map or {}).get(col.text(row), 'neutral')
        if role == CHOICES_ROLE:
            ch = col.choices
            return list(ch(row) if callable(ch) else (ch or ()))
        if role == PROGRESS_ROLE:
            try:
                return max(0.0, min(1.0, float(col.value(row) or 0)))
            except (TypeError, ValueError):
                return 0.0
        return None

    def flags(self, index):
        # hot: Qt calls this for every cell of a big selection, so no enum arithmetic here
        col = self.columns[index.column()]
        if col.editable is False:
            return _F_PLAIN
        if col.is_editable(self._rows[index.row()]):
            return _F_CHECK if col.kind == 'checkbox' else _F_EDIT
        return _F_PLAIN

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.EditRole, Qt.ItemDataRole.CheckStateRole):
            return False
        row = self._rows[index.row()]
        col = self.columns[index.column()]
        if not col.is_editable(row):
            return False
        if role == Qt.ItemDataRole.CheckStateRole:
            value = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        old = col.value(row)
        if old == value:
            return False
        if self.edit_hook is not None and self.edit_hook(row, col.key, old, value) is False:
            return False
        col.store(row, value)
        self._hay[index.row()] = None
        self.dataChanged.emit(index, index)
        self.cellEdited.emit(row, col.key, old, value)
        return True

    # ---- sorting (the model reorders its own list: a key sort in Python is ~10x faster than the proxy's per-compare data() calls)
    def _key_fn(self, col: Column):
        if col.sort_key is not None:
            fn = col.sort_key
        elif col.kind == 'progress' or col.kind == 'checkbox':
            fn = lambda r: float(col.value(r) or 0)           # noqa: E731
        else:
            def fn(r):
                v = col.value(r)
                if v is None or v == '':
                    return None
                if isinstance(v, bool):
                    return (0, float(v))
                if isinstance(v, (int, float)):
                    return (0, float(v))
                s = col.text(r)
                return (1, _natural(s) if col.natural else s.casefold())
        return fn

    def sort_rows(self, column: int, descending: bool = False) -> None:
        if not (0 <= column < len(self.columns)) or not self._rows:
            return
        fn = self._key_fn(self.columns[column])
        keys, none_idx, good = [], [], []
        for i, r in enumerate(self._rows):
            try:
                k = fn(r)
            except Exception:
                k = None
            if k is None or (isinstance(k, tuple) and k and k[-1] is None):
                none_idx.append(i)
            else:
                keys.append(k)
                good.append(i)
        try:
            order = [good[j] for j in sorted(range(len(good)), key=keys.__getitem__, reverse=descending)]
        except TypeError:                                     # mixed types in one column: compare as text
            skeys = [str(k).casefold() for k in keys]
            order = [good[j] for j in sorted(range(len(good)), key=skeys.__getitem__, reverse=descending)]
        order += none_idx                                     # empty values always last
        self._apply_order(order)

    def _apply_order(self, order: list[int]) -> None:
        if order == list(range(len(order))):
            return
        self.layoutAboutToBeChanged.emit()
        old_persist = self.persistentIndexList()
        new_pos = [0] * len(order)
        for new, old in enumerate(order):
            new_pos[old] = new
        rows, hay = self._rows, self._hay
        self._rows = [rows[i] for i in order]
        self._hay = [hay[i] for i in order]
        if old_persist:
            self.changePersistentIndexList(old_persist, [self.index(new_pos[ix.row()], ix.column()) for ix in old_persist])
        self.layoutChanged.emit()


class _Proxy(QSortFilterProxyModel):
    """Filtering only: every whitespace-separated word of the search text must occur (case-insensitive) in the row's searchable cells, and the optional
    predicate must accept the row object."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._words: list[str] = []
        self.predicate: Callable[[Any], bool] | None = None
        self.setDynamicSortFilter(False)

    def set_words(self, text: str) -> None:
        self._words = [w for w in text.casefold().split() if w]

    def active(self) -> bool:
        return bool(self._words) or self.predicate is not None

    def filterAcceptsRow(self, src_row, src_parent):
        m = self.sourceModel()
        if self._words:
            h = m.haystack(src_row)
            for w in self._words:
                if w not in h:
                    return False
        if self.predicate is not None:
            try:
                return bool(self.predicate(m.row_at(src_row)))
            except Exception:
                return True
        return True


class CellDelegate(QStyledItemDelegate):
    """Paints badge / combo / checkbox / progress cells and edits combo cells (opens the list on the first click)."""

    def __init__(self, table: 'DataTable'):
        super().__init__(table)
        self.table = table

    def _kind(self, index) -> str:
        m = self.table.source_model
        return m.columns[index.column()].kind

    # ---- painting
    def _background(self, painter, opt: QStyleOptionViewItem, index):
        o = QStyleOptionViewItem(opt)
        self.initStyleOption(o, index)
        o.text = ''
        o.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        o.state &= ~QStyle.StateFlag.State_HasFocus
        (o.widget.style() if o.widget else QApplication.style()).drawControl(QStyle.ControlElement.CE_ItemViewItem, o, painter, o.widget)

    def paint(self, painter, opt, index):
        kind = self._kind(index)
        t = theme.tokens()
        bg = index.data(Qt.ItemDataRole.BackgroundRole)              # the style sheet ignores BackgroundRole once ::item is styled: the row tone is filled here
        if bg is not None and not (opt.state & QStyle.StateFlag.State_Selected):
            painter.fillRect(opt.rect, bg)
        if kind == 'text':
            o = QStyleOptionViewItem(opt)
            self.initStyleOption(o, index)
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            if fg is not None:
                o.palette.setBrush(o.palette.ColorRole.HighlightedText, fg)       # a selected failing row keeps its red text
            o.state &= ~QStyle.StateFlag.State_HasFocus
            (o.widget.style() if o.widget else QApplication.style()).drawControl(QStyle.ControlElement.CE_ItemViewItem, o, painter, o.widget)
            return
        self._background(painter, opt, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = opt.rect
        if kind == 'badge':
            text = index.data(Qt.ItemDataRole.DisplayRole) or ''
            if text:
                bk = index.data(BADGE_ROLE) or 'neutral'
                bk = bk if bk in theme.KINDS else 'neutral'
                f = QFont(opt.font)
                f.setPixelSize(M.font_small)
                f.setWeight(QFont.Weight.DemiBold)
                painter.setFont(f)
                w = min(r.width() - 12, painter.fontMetrics().horizontalAdvance(text) + 20)
                h = M.badge_h
                al = index.data(Qt.ItemDataRole.TextAlignmentRole) or 0
                x = r.left() + 6 if not (al & Qt.AlignmentFlag.AlignRight) else r.right() - w - 6
                pill = QRect(x, r.center().y() - h // 2 + 1, w, h)
                painter.setPen(Qt.PenStyle.NoPen)
                pill_bg = t[bk + '_bg'] if index.data(Qt.ItemDataRole.BackgroundRole) is None else theme.blend(t[bk + '_bg'], t['text'], 0.14)   # still a pill on a tinted row
                painter.setBrush(QColor(pill_bg))
                painter.drawRoundedRect(pill, h / 2, h / 2)
                painter.setPen(QColor(t[bk]))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, w - 8))
        elif kind == 'checkbox':
            on = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            s = 16
            box = QRectF(r.center().x() - s / 2 + 0.5, r.center().y() - s / 2 + 0.5, s - 1, s - 1)
            if on:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t['primary'] if enabled else t['primary_off']))
                painter.drawRoundedRect(box, 4, 4)
                painter.drawPixmap(box.toRect().adjusted(-1, -1, 1, 1), theme.pixmap('check', t['on_primary'], s + 2))
            else:
                painter.setPen(QPen(QColor(t['border_strong'] if enabled else t['border']), 1))
                painter.setBrush(QColor(t['field'] if enabled else t['disabled_bg']))
                painter.drawRoundedRect(box, 4, 4)
        elif kind == 'progress':
            v = float(index.data(PROGRESS_ROLE) or 0.0)
            pad = 10
            txt_w = 38
            bar = QRectF(r.left() + pad, r.center().y() - 3, max(10, r.width() - 2 * pad - txt_w), 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t['trough']))
            painter.drawRoundedRect(bar, 3, 3)
            if v > 0:
                painter.setBrush(QColor(t['good'] if v >= 1.0 else t['primary']))
                painter.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * v), bar.height()), 3, 3)
            f = QFont(opt.font)
            f.setPixelSize(M.font_small)
            painter.setFont(f)
            painter.setPen(QColor(t['muted']))
            painter.drawText(QRectF(bar.right() + 6, r.top(), txt_w - 4, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), f'{round(v * 100)}%')
        elif kind == 'combo':
            enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
            box = QRectF(r.adjusted(4, 4, -6, -4))
            painter.setPen(QPen(QColor(t['border_strong'] if enabled else t['border']), 1))
            painter.setBrush(QColor(t['field'] if enabled else t['disabled_bg']))
            painter.drawRoundedRect(box, M.radius, M.radius)
            painter.setPen(QColor(t['text'] if enabled else t['disabled_fg']))
            painter.setFont(opt.font)
            text = painter.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole) or '', Qt.TextElideMode.ElideRight, int(box.width() - 34))
            painter.drawText(box.adjusted(10, 0, -24, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
            if enabled:
                painter.drawPixmap(QRect(int(box.right() - 22), int(box.center().y() - 8), 16, 16), theme.pixmap('chevron_down', t['muted'], 16))
        painter.restore()

    def sizeHint(self, opt, index):
        sh = super().sizeHint(opt, index)
        return QSize(sh.width(), M.row_h)

    # ---- editing
    def createEditor(self, parent, opt, index):
        if self._kind(index) == 'combo':
            cb = QComboBox(parent)
            cb.addItems([str(c) for c in (index.data(CHOICES_ROLE) or [])])
            cb.setFrame(False)
            cb.activated.connect(lambda _i, c=cb: self.commitData.emit(c) or self.closeEditor.emit(c))
            QTimer.singleShot(0, cb.showPopup)
            return cb
        return super().createEditor(parent, opt, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            i = editor.findText(str(index.data(Qt.ItemDataRole.EditRole) if index.data(Qt.ItemDataRole.EditRole) is not None else ''))
            editor.setCurrentIndex(max(0, i))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            choices = index.data(CHOICES_ROLE) or []
            i = editor.currentIndex()
            model.setData(index, choices[i] if 0 <= i < len(choices) else editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, opt, index):
        editor.setGeometry(opt.rect.adjusted(3, 3, -5, -3) if isinstance(editor, QComboBox) else opt.rect.adjusted(1, 1, -1, -1))

    def editorEvent(self, event, model, opt, index):
        kind = self._kind(index)
        if kind == 'checkbox' and index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            toggle = False
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and opt.rect.contains(event.position().toPoint()):
                toggle = True
            elif event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select):
                toggle = True
            if toggle:
                on = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
                self.table.toggle_check(index, not on)
                return True
            return event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
        if kind == 'combo' and index.flags() & Qt.ItemFlag.ItemIsEditable:
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton and opt.rect.contains(event.position().toPoint()):
                self.table.edit(index)
                return True
        return super().editorEvent(event, model, opt, index)


class DataTable(QTableView):
    """See the module doc.  Signals: selectionChangedRows(list of row objects), rowActivated(row) on double-click / Enter, cellEdited(row, key, old, new),
    countsChanged(visible, total)."""
    selectionChangedRows = Signal(list)
    rowActivated = Signal(object)
    cellEdited = Signal(object, object, object, object)
    countsChanged = Signal(int, int)

    def __init__(self, columns: Sequence[Column], rows: Sequence = (), *, row_tone: Callable[[Any], str | None] | None = None,
                 row_key: Callable[[Any], Any] | None = None, multi: bool = True, alternating: bool = True, frozen: bool = False,
                 tone_style: str = 'both', empty_text: str = 'No rows', parent=None):
        super().__init__(parent)
        self.source_model = TableModel(columns, rows, self)
        self.source_model.row_tone = row_tone
        self.source_model.tone_style = tone_style
        self.source_model.cellEdited.connect(self.cellEdited)
        self.proxy = _Proxy(self)
        self.proxy.setSourceModel(self.source_model)
        self.row_key = row_key or id
        self.empty_text = empty_text
        self.empty_filtered_text = 'No rows match the filter'
        self._frozen_view: QTableView | None = None
        self._sort = (None, False)                                # (column key, descending)
        self.setModel(self.proxy)
        self.setItemDelegate(CellDelegate(self))
        self.setAlternatingRowColors(alternating)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multi else QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setCornerButtonEnabled(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        vh = self.verticalHeader()
        vh.hide()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)             # uniform heights: no per-row size hints, which is what keeps 50,000 rows fast
        vh.setDefaultSectionSize(M.row_h)
        hh = self.horizontalHeader()
        hh.setFixedHeight(M.header_h)
        hh.setStretchLastSection(False)
        hh.setHighlightSections(False)
        hh.setSectionsClickable(True)
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.sectionClicked.connect(self._header_clicked)
        self._sel_timer = QTimer(self)                              # coalesce a burst of selection changes (drag, select all) into one signal
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(0)
        self._sel_timer.timeout.connect(self._emit_selection)
        self.selectionModel().selectionChanged.connect(lambda *_: self._sel_timer.start())
        self.doubleClicked.connect(lambda ix: self.rowActivated.emit(self.row_of(ix)) if not (self.source_model.flags(self.proxy.mapToSource(ix)) & Qt.ItemFlag.ItemIsEditable) else None)
        for sig in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset, self.proxy.layoutChanged):
            sig.connect(self._counts_changed)
        self._apply_columns()
        if frozen:
            self.enable_frozen_first_column()
        theme.manager().changed.connect(lambda _n: self.viewport().update())

    # ---- columns
    def _apply_columns(self) -> None:
        hh = self.horizontalHeader()
        for i, c in enumerate(self.source_model.columns):
            hh.setMinimumSectionSize(20)
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if c.stretch else QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(i, c.width)
            hh.model().setHeaderData(i, Qt.Orientation.Horizontal, c.align, Qt.ItemDataRole.UserRole)
        self._sort = (None, False)

    def set_columns(self, columns: Sequence[Column]) -> None:
        self.source_model.set_columns(columns)
        self._apply_columns()
        self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def column_index(self, key) -> int:
        for i, c in enumerate(self.source_model.columns):
            if c.key == key:
                return i
        raise KeyError(key)

    # ---- rows
    def set_rows(self, rows: Sequence, *, keep_selection: bool = True) -> None:
        keys = {self.row_key(r) for r in self.selected_rows()} if keep_selection else set()
        self.source_model.set_rows(rows)
        if self._sort[0] is not None:
            self.source_model.sort_rows(self.column_index(self._sort[0]), self._sort[1])
        self.proxy.invalidate() if self.proxy.active() else None
        if keys:
            self.select_rows([r for r in self.source_model.rows() if self.row_key(r) in keys])
        self._counts_changed()

    def rows(self) -> list:
        return self.source_model.rows()

    def append_rows(self, rows: Sequence) -> None:
        self.source_model.append_rows(rows)

    def visible_rows(self) -> list:
        m, p = self.source_model, self.proxy
        return [m.row_at(p.mapToSource(p.index(i, 0)).row()) for i in range(p.rowCount())]

    def row_count(self) -> tuple[int, int]:
        return self.proxy.rowCount(), self.source_model.rowCount()

    def refresh(self, row=None) -> None:
        """Re-read the cells (after the owner changed the row objects)."""
        if row is None:
            self.source_model.all_changed()
        else:
            self.source_model.row_changed(row)

    def set_row_tone(self, fn: Callable[[Any], str | None] | None) -> None:
        self.source_model.row_tone = fn
        self.viewport().update()

    # ---- filter and sort
    def set_filter_text(self, text: str) -> None:
        self.proxy.set_words(text or '')
        self.proxy.invalidateFilter()
        self._counts_changed()

    def set_predicate(self, fn: Callable[[Any], bool] | None) -> None:
        """A programmatic filter (e.g. the SegmentedFilter's 'Needs attention'): row object -> bool.  Combined (AND) with the text filter."""
        self.proxy.predicate = fn
        self.proxy.invalidateFilter()
        self._counts_changed()

    def sort_by(self, key, descending: bool = False) -> None:
        """Sort by a column key; key=None restores no sort indicator (the rows keep their current order)."""
        if key is None:
            self._sort = (None, False)
            self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            return
        i = self.column_index(key)
        self._sort = (key, descending)
        sel = self.selected_rows()
        self.source_model.sort_rows(i, descending)
        for h in self._headers():
            h.blockSignals(True)
            h.setSortIndicator(i, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
            h.blockSignals(False)
        if sel:
            self.select_rows(sel)

    def sort_state(self):
        return self._sort

    def _header_clicked(self, section: int) -> None:
        key = self.source_model.columns[section].key
        desc = (not self._sort[1]) if self._sort[0] == key else False
        self.sort_by(key, desc)

    def _headers(self):
        hs = [self.horizontalHeader()]
        if self._frozen_view is not None:
            hs.append(self._frozen_view.horizontalHeader())
        return hs

    # ---- selection
    def selected_rows(self) -> list:
        """The selected row objects in the order shown.  Built from the selection ranges (selectionModel().selectedRows() is O(n) slow Qt code: 2 s at 50,000)."""
        m, p = self.source_model, self.proxy
        idx = set()
        for rng in self.selectionModel().selection():
            idx.update(range(rng.top(), rng.bottom() + 1))
        return [m.row_at(p.mapToSource(p.index(i, 0)).row()) for i in sorted(idx)]

    def selected_count(self) -> int:
        idx = set()
        for rng in self.selectionModel().selection():
            idx.update(range(rng.top(), rng.bottom() + 1))
        return len(idx)

    def selected_keys(self) -> list:
        return [self.row_key(r) for r in self.selected_rows()]

    def row_of(self, index):
        """The row object behind a (proxy) model index."""
        return self.source_model.row_at(self.proxy.mapToSource(index).row()) if index.isValid() else None

    def current_row(self):
        ix = self.currentIndex()
        return self.source_model.row_at(self.proxy.mapToSource(ix).row()) if ix.isValid() else None

    def select_rows(self, rows: Iterable) -> None:
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        want = {id(r) for r in rows}
        if self.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection:
            want = set(list(want)[:1])
        sel = QItemSelection()
        m, p = self.source_model, self.proxy
        first = None
        for i in range(p.rowCount()):
            src = p.mapToSource(p.index(i, 0)).row()
            if id(m.row_at(src)) in want:
                if first is None:
                    first = p.index(i, 0)
                sel.select(p.index(i, 0), p.index(i, p.columnCount() - 1))
        self.selectionModel().select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if first is not None:
            self.selectionModel().setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)

    def scroll_to_row(self, row) -> None:
        m, p = self.source_model, self.proxy
        for i in range(p.rowCount()):
            if m.row_at(p.mapToSource(p.index(i, 0)).row()) is row:
                self.scrollTo(p.index(i, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _emit_selection(self) -> None:
        self.selectionChangedRows.emit(self.selected_rows())

    def _counts_changed(self, *_) -> None:
        v, t = self.row_count()
        self.countsChanged.emit(v, t)
        self.viewport().update()

    # ---- editing
    def toggle_check(self, index, on: bool) -> None:
        """Set a checkbox cell; with several rows selected and the clicked row among them, all selected rows follow (like a spreadsheet)."""
        sel = set()
        for rng in self.selectionModel().selection():
            sel.update(range(rng.top(), rng.bottom() + 1))
        targets = [index]
        if len(sel) > 1 and index.row() in sel:
            targets = [self.proxy.index(r, index.column()) for r in sorted(sel)]
        for ix in targets:
            self.proxy.setData(ix, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    def set_edit_hook(self, fn: Callable[[Any, Any, Any, Any], bool | None] | None) -> None:
        """fn(row, key, old, new) runs before a cell edit is stored; return False to reject it.  `cellEdited` fires after a stored edit."""
        self.source_model.edit_hook = fn

    # ---- clipboard
    def export_text(self, rows: Sequence | None = None, *, header: bool = False) -> str:
        cols = self.source_model.columns
        rows = self.selected_rows() if rows is None else rows
        out = ['\t'.join(c.title for c in cols)] if header else []
        for r in rows:
            cells = []
            for c in cols:
                if c.kind == 'checkbox':
                    cells.append('1' if c.value(r) else '0')
                elif c.kind == 'progress':
                    cells.append(f'{round(float(c.value(r) or 0) * 100)}%')
                else:
                    cells.append(c.text(r).replace('\t', ' ').replace('\n', ' '))
            out.append('\t'.join(cells))
        return '\n'.join(out)

    def copy_selection(self, header: bool = False) -> str:
        """Selected rows as tab-separated text (opens in Excel) onto the clipboard; returns the text."""
        text = self.export_text(header=header)
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != QAbstractItemView.State.EditingState:
            r = self.current_row()
            if r is not None:
                self.rowActivated.emit(r)
                return
        super().keyPressEvent(ev)

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        n = self.selected_count()
        a1 = menu.addAction('Copy' if n <= 1 else f'Copy {n} rows')
        a2 = menu.addAction('Copy with headers')
        menu.addSeparator()
        a3 = menu.addAction('Select all')
        a1.setEnabled(n > 0)
        a2.setEnabled(n > 0)
        a1.triggered.connect(lambda: self.copy_selection())
        a2.triggered.connect(lambda: self.copy_selection(True))
        a3.triggered.connect(self.selectAll)
        menu.exec(self.viewport().mapToGlobal(pos))

    # ---- empty message
    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.proxy.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(theme.tokens()['muted']))
            text = self.empty_filtered_text if self.source_model.rowCount() else self.empty_text
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, text)

    # ---- frozen first column (the Qt 'frozen column' pattern: a second view over the same model / selection, laid on top)
    def enable_frozen_first_column(self) -> None:
        if self._frozen_view is not None:
            return
        fv = QTableView(self)
        fv.setObjectName('frozen')
        fv.setModel(self.proxy)
        fv.setSelectionModel(self.selectionModel())
        fv.setItemDelegate(self.itemDelegate())
        fv.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fv.verticalHeader().hide()
        fv.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        fv.verticalHeader().setDefaultSectionSize(M.row_h)
        fv.horizontalHeader().setFixedHeight(M.header_h)
        fv.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        fv.horizontalHeader().setSortIndicatorShown(True)
        fv.horizontalHeader().setSectionsClickable(True)
        fv.horizontalHeader().sectionClicked.connect(self._header_clicked)
        fv.setAlternatingRowColors(self.alternatingRowColors())
        fv.setShowGrid(False)
        fv.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        fv.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fv.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fv.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        fv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        fv.setWordWrap(False)
        fv.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        fv.customContextMenuRequested.connect(lambda p: self._context_menu(fv.viewport().mapTo(self.viewport(), p)))
        for c in range(1, self.source_model.columnCount()):
            fv.setColumnHidden(c, True)
        fv.setColumnWidth(0, self.columnWidth(0))
        self.viewport().stackUnder(fv)
        self._frozen_view = fv
        self.horizontalHeader().sectionResized.connect(self._frozen_section_resized)
        self.verticalScrollBar().valueChanged.connect(fv.verticalScrollBar().setValue)
        fv.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        fv.show()
        self._frozen_geometry()

    def _frozen_section_resized(self, index, _old, new):
        if self._frozen_view is not None and index == 0:
            self._frozen_view.setColumnWidth(0, new)
            self._frozen_geometry()

    def _frozen_geometry(self) -> None:
        fv = self._frozen_view
        if fv is None:
            return
        fw = self.frameWidth()
        fv.setGeometry(fw, fw, self.columnWidth(0), self.viewport().height() + self.horizontalHeader().height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._frozen_geometry()

    def moveCursor(self, action, modifiers):
        cur = super().moveCursor(action, modifiers)
        if self._frozen_view is not None and action == QAbstractItemView.CursorAction.MoveLeft and cur.column() > 0:
            if self.visualRect(cur).topLeft().x() < self._frozen_view.columnWidth(0):
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + self.visualRect(cur).topLeft().x() - self._frozen_view.columnWidth(0))
        return cur

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        if index.column() > 0 or self._frozen_view is None:
            super().scrollTo(index, hint)
