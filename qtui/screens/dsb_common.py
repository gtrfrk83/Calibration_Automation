"""Datasheet Builder (Qt): small shared helpers.  Everything the screens ask the person (yes / no, a line of text, a file name) goes through the module-level
functions here, so a test can replace them.  No Tk import."""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QWidget)

from qtui import theme, widgets
from qtui.table import Column, DataTable
from qtui.theme import M


# ------------------------------------------------------------------------------------------------------------------------------ values
class Var:
    """A tiny observable string / bool (what the Tk screens hold in a StringVar): get(), set(v), callbacks on every set."""

    def __init__(self, value='', on_change: Callable | None = None):
        self._v = value
        self._cbs = [on_change] if on_change else []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb(v)

    def add(self, cb):
        self._cbs.append(cb)


class Bind:
    """get() / set() over a QLineEdit, an (editable or read-only) QComboBox, a QCheckBox or a QRadioButton, so the code that was written for
    Tk variables reads the same."""

    def __init__(self, w: QWidget):
        self.w = w

    def get(self):
        w = self.w
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, (QCheckBox, QRadioButton)) or hasattr(w, 'isChecked'):
            return w.isChecked()
        return ''

    def set(self, v):
        w = self.w
        if isinstance(w, QLineEdit):
            w.setText('' if v is None else str(v))
        elif isinstance(w, QComboBox):
            v = '' if v is None else str(v)
            i = w.findText(v)
            if i >= 0:
                w.setCurrentIndex(i)
            elif w.isEditable():
                w.setEditText(v)
            else:
                w.setCurrentIndex(-1)
        elif hasattr(w, 'setChecked'):
            w.setChecked(bool(v))


def label_of(pairs, value):
    return next((lab for v, lab in pairs if v == value), pairs[0][1] if pairs else '')


def value_of(pairs, label):
    return next((v for v, lab in pairs if lab == label), pairs[0][0] if pairs else '')


def set_items(box: QComboBox, items: Sequence[str]) -> None:
    """Replace the list of a combo box without losing what an editable one shows."""
    keep = box.currentText() if box.isEditable() else ''
    box.blockSignals(True)
    box.clear()
    box.addItems([str(i) for i in items])
    if box.isEditable():
        box.setEditText(keep)
    else:
        box.setCurrentIndex(-1)
    box.blockSignals(False)


# ------------------------------------------------------------------------------------------------------------------------------ tooltips
class _DynTip(QObject):
    def __init__(self, w, fn):
        super().__init__(w)
        self.w, self.fn = w, fn
        w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.ToolTip:
            try:
                self.w.setToolTip(self.fn())
            except Exception:
                pass
        return False


def tip(w: QWidget, text) -> QWidget:
    """A tooltip (text, or a function that gives the text when it is shown)."""
    if callable(text):
        _DynTip(w, text)
    elif text:
        w.setToolTip(text)
    return w


# ------------------------------------------------------------------------------------------------------------------------------ building blocks
def hint(text: str, wrap: bool = True) -> QLabel:
    return widgets.label(text, 'sub', wrap=wrap)


def small(text: str = '') -> QLabel:
    return widgets.label(text, 'hint', wrap=True)


def button(text: str, on_click: Callable | None = None, role: str | None = None, compact: bool = False, tooltip: str = '') -> QPushButton:
    cls = {'primary': widgets.PrimaryButton, 'danger': widgets.DangerButton}.get(role, widgets.SecondaryButton)
    b = cls(text)
    if on_click is not None:
        b.clicked.connect(lambda _c=False: on_click())
    if compact:
        b.setProperty('compact', True)
        b.setMinimumHeight(M.control_h - 6)
    if tooltip:
        b.setToolTip(tooltip)
    return b


def button_row(*specs) -> tuple[QWidget, dict]:
    """A row of buttons: specs are (text, command) or (text, command, role).  Returns (widget, {text: button})."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(M.sm)
    out = {}
    for spec in specs:
        b = button(spec[0], spec[1], spec[2] if len(spec) > 2 else None)
        lay.addWidget(b)
        out[spec[0]] = b
    lay.addStretch(1)
    return box, out


class Form(QWidget):
    """Label + field pairs in a grid (`columns` pairs per line): form.entry('Full scale') -> QLineEdit, form.combo(label, values) -> QComboBox, form.check(text)."""

    def __init__(self, columns: int = 2, parent=None):
        super().__init__(parent)
        self.lay = QGridLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setHorizontalSpacing(M.sm)
        self.lay.setVerticalSpacing(M.sm - 2)
        self.row = self.col = 0
        self.columns = columns
        for c in range(columns):
            self.lay.setColumnStretch(c * 2 + 1, 1)

    def _next(self):
        self.col += 1
        if self.col >= self.columns:
            self.col, self.row = 0, self.row + 1

    def place(self, label: str, w: QWidget, help_text: str = '') -> QWidget:
        c = self.col * 2
        lab = QLabel(label)
        lab.setBuddy(w)
        self.lay.addWidget(lab, self.row, c)
        self.lay.addWidget(w, self.row, c + 1)
        if help_text:
            tip(w, help_text)
            tip(lab, help_text)
        self._next()
        return w

    def entry(self, label: str, width: int = 0, help_text: str = '') -> QLineEdit:
        e = QLineEdit()
        if width:
            e.setMinimumWidth(min(width * 7, 420))
        return self.place(label, e, help_text)

    def combo(self, label: str, values: Sequence[str] = (), width: int = 0, help_text: str = '', editable: bool = False) -> QComboBox:
        b = QComboBox()
        b.setEditable(editable)
        b.addItems(list(values))
        if width:
            b.setMinimumWidth(min(width * 7, 420))
        return self.place(label, b, help_text)

    def check(self, text: str, help_text: str = '') -> QCheckBox:
        cb = QCheckBox(text)
        self.lay.addWidget(cb, self.row, self.col * 2, 1, 2)
        if help_text:
            tip(cb, help_text)
        self._next()
        return cb

    def newline(self):
        if self.col:
            self.col, self.row = 0, self.row + 1


def group(title: str) -> tuple[QFrame, 'QVBoxLayout']:
    """A titled box (a Card with a small title) for a block of fields."""
    from PySide6.QtWidgets import QVBoxLayout
    card = widgets.Card(title, padding=M.md)
    card.title_label.setProperty('role', 'section')
    return card, card.body


# ------------------------------------------------------------------------------------------------------------------------------ tables
class ShareWidth(QObject):
    """Keeps a list readable in a wide window: the width beyond the columns' own widths is shared, half to the stretching column and half between the others in
    proportion to their width, instead of one huge text column with the other columns pushed to the far right (the idea of the Manager list).  Narrower than the
    columns' own widths the stretching column gives way first, as a stretching column does."""

    def __init__(self, table, columns):
        super().__init__(table)
        self.table = table
        self.base = [c.width for c in columns]
        self.grow = next((i for i, c in enumerate(columns) if c.stretch), None)
        hh = table.horizontalHeader()
        if self.grow is not None:
            hh.setSectionResizeMode(self.grow, hh.ResizeMode.Interactive)
        table.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        try:
            hh = self.table.horizontalHeader()
            vp = self.table.viewport().width() - 2
            base, g = self.base, self.grow
            total = sum(base)
            extra = max(0, vp - total)
            others = total - base[g]
            for i, w in enumerate(base):
                if i == g:
                    hh.resizeSection(i, int(w + extra * 0.5))
                else:
                    hh.resizeSection(i, int(w + extra * 0.5 * w / max(others, 1)))
            if vp < total:
                hh.resizeSection(g, max(120, vp - others))
        except RuntimeError:
            pass                                              # the table went away


def table(columns: Sequence[Column], *, row_tone=None, multi: bool = False, key='id', empty: str = '', sortable: bool = False) -> DataTable:
    """A read-only list table (the Tk make_table): single selection, rows are dicts with an `id`.  Header sorting only when `sortable` (a table whose row
    order means something, like the function list, keeps the model's order)."""
    t = DataTable(list(columns), row_tone=row_tone, row_key=lambda r: r[key] if isinstance(r, dict) else id(r), multi=multi, alternating=True, empty_text=empty or 'No rows')
    if not sortable:
        t.horizontalHeader().setSectionsClickable(False)
        t.horizontalHeader().setSortIndicatorShown(False)
    if any(c.stretch for c in columns):
        t._share_width = ShareWidth(t, list(columns))
    return t


def selected_ids(t: DataTable, key='id') -> tuple:
    """The ids of the selected rows (empty when nothing is selected)."""
    try:
        return tuple(str(r[key]) for r in t.selected_rows())
    except Exception:
        return ()


def fill(t: DataTable, rows: list, key: str = 'id') -> None:
    t.set_rows(rows, keep_selection=True)


def select_id(t: DataTable, ident) -> bool:
    for r in t.rows():
        if str(r.get('id')) == str(ident):
            t.select_rows([r])
            return True
    return False


# ------------------------------------------------------------------------------------------------------------------------------ questions (replaceable in tests)
def ask_yes_no(parent, title: str, text: str, *, default: str = 'yes', kind: str = 'question') -> bool:
    """A Yes / No question.  default='no' makes No the button Enter presses (the real-run question)."""
    buttons = (('Yes', 'yes', 'primary' if default == 'yes' else None), ('No', 'no', 'primary' if default != 'yes' else None))
    dlg = widgets.MessageDialog(parent, kind, title, text, buttons=buttons, cancel_key='no')
    return dlg.run() == 'yes'


def ask_string(parent, title: str, prompt: str, initial: str = '') -> str | None:
    """One line of text; None when cancelled."""
    dlg = widgets.ModalDialog(parent, title)
    dlg.title_label.hide()
    dlg.add_text(prompt)
    e = QLineEdit(initial)
    dlg.body.addWidget(e)
    dlg.initial_focus = e
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button('OK', role='primary', result='ok', default=True)
    e.selectAll()
    return e.text() if dlg.run() == 'ok' else None


def ask_save_path(parent, title: str, initial: str = '', filters: str = 'All files (*.*)') -> str:
    path, _f = QFileDialog.getSaveFileName(parent, title, initial, filters)
    return path or ''


def ask_open_path(parent, title: str, filters: str = 'All files (*.*)') -> str:
    path, _f = QFileDialog.getOpenFileName(parent, title, '', filters)
    return path or ''


# ------------------------------------------------------------------------------------------------------------------------------ layout helpers
from PySide6.QtCore import QMargins, QPoint, QRect, QSize                       # noqa: E402
from PySide6.QtWidgets import QLayout, QSizePolicy                              # noqa: E402


class FlowLayout(QLayout):
    """Small widgets left to right, wrapping to a new line when the next one does not fit (the Tk `flow`)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items = []
        self._gap = gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            sz = it.sizeHint()
            if x + sz.width() > r.right() + 1 and line_h > 0:
                x, y, line_h = r.x(), y + line_h + self._gap, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._gap
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y() + m.bottom()


class ToneLabel(QLabel):
    """A wrapped text label whose colour follows a tone: 'ok' (normal text), 'info' (muted), 'warn', 'bad'.  Colours come from the theme tokens and follow a theme switch."""

    def __init__(self, text: str = '', tone: str = 'ok', parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._tone = tone
        theme.manager().changed.connect(self._on_theme)
        self._apply()

    def _on_theme(self, _n=None) -> None:
        try:
            self._apply()
        except RuntimeError:                       # the label is gone with its window
            try:
                theme.manager().changed.disconnect(self._on_theme)
            except (RuntimeError, TypeError):
                pass

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._apply()

    def tone(self) -> str:
        return self._tone

    def _apply(self) -> None:
        t = theme.tokens()
        col = {'warn': t['warn'], 'bad': t['bad'], 'info': t['muted']}.get(self._tone, t['text'])
        self.setStyleSheet(f'color: {col};')


class Clickable(QObject):
    """Calls fn when `w` is clicked with the left mouse button (for a Badge used as a link)."""

    def __init__(self, w: QWidget, fn: Callable):
        super().__init__(w)
        self.fn = fn
        w.installEventFilter(self)
        w.setCursor(Qt.CursorShape.PointingHandCursor)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            self.fn()
            return True
        return False
