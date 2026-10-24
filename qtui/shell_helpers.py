"""The Qt equivalents of the ui_theme.py helpers the *_view_tk.py files call, so an engine-window agent can port a view by swapping the imports:

    Tk (ui_theme / ui_shell)                    Qt (qtui.shell_helpers / qtui.shell)
    ui.px(n), ui.SCALE, ui.C[...]               px(n) -> n (Qt px are device independent), SCALE = 1.0, C[...] (live theme tokens, same keys)
    ui.apply_theme(root), ui.polish(root)       apply_theme(win), polish(win)
    ui.fit_window(root, w, h, min_w, min_h)     fit_window(win, w, h, min_w, min_h)
    ui.Pill / ui.Notice / ui.Banner / ui.StatusBar / ui.Summary / ui.Tooltip     the same names (Pill -> Badge, Notice -> Banner strip, ...)
    ui.make_table(parent, columns, ...)         make_table(parent, columns, headings, widths, ...)  -> a ResultsTree (a DataTable with the Treeview calls)
    ui.dialog(parent, title) / ui.center_on     dialog(parent, title) -> ModalDialog / center_on(win, parent)
    ui.themed_menu(parent) / ui.post_menu       themed_menu(parent) / post_menu(menu, x_root, y_root)
    ui.si / si_one / si_row / report_filename / Settings / status_kind / is_dark       toolkit-free: re-exported from ui_theme_core
    ttk.Frame / Label / Button / Entry / Combobox / Checkbutton / Radiobutton + pack / grid       frame() label_() button() entry() combobox() checkbutton() radiobutton() + pack() grid()
    tk.StringVar etc.                                                                  qtui.vars.QtVar (ui_port.var())

Tk's geometry managers become layouts: `pack(parent, widget, side='left', fill=None, expand=False, padx=0, pady=0, anchor=None)` adds `widget` to parent's QHBoxLayout /
QVBoxLayout (side 'left' / 'right' go in a QHBoxLayout, 'top' / 'bottom' in a QVBoxLayout; the layout is created on first use) and `grid(parent, widget, row, column,
columnspan=1, sticky='', padx=0, pady=0)` into a QGridLayout.  A Tk `side='bottom'` frame packed BEFORE the table is simply added after it in the Qt layout.

The widgets keep a `configure(**kw)` (state='disabled' | 'normal' | 'readonly', text=, values=, command=) / `cget` pair, so `sync_buttons`-style code runs unchanged.
No Tk import here (tests/test_qtui_rules.py).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QProgressBar,
                               QPushButton, QRadioButton, QSizePolicy, QVBoxLayout, QWidget)

import ui_theme_core as core
from ui_theme_core import Settings, fmt_num, report_filename, si, si_one, si_row, si_scale, status_kind  # noqa: F401  (toolkit-free, same names as ui_theme)

from . import theme
from . import widgets as W
from .table import Column, DataTable
from .theme import M
from .vars import QtVar, bind

SCALE = 1.0
DEMO_SUFFIX_KEY = 'DEMO_SUFFIX'


def px(n) -> int:
    """Tk's px() scaled 96-dpi units by the display factor; Qt sizes are device independent already."""
    return int(round(n))


class _LiveTokens:
    """`C['bg']` etc.: the live theme tokens (same keys as ui_theme.C)."""

    def __getitem__(self, key):
        return theme.tokens()[key]

    def get(self, key, default=None):
        return theme.tokens().get(key, default)

    def __contains__(self, key):
        return key in theme.tokens()

    def keys(self):
        return theme.tokens().keys()


C = _LiveTokens()


def is_dark() -> bool:
    return theme.is_dark()


def enable_hidpi() -> None:
    from . import app
    app.configure_hidpi()


def apply_theme(win=None):
    """The theme is applied by qtui.app.create_app(); here for symmetry (call it before building widgets)."""
    from . import app
    app.create_app()
    return theme.manager()


def polish(win=None) -> None:
    """Tk used it to re-skin every widget created after apply_theme; the style sheet does that by itself in Qt."""
    return None


def fit_window(win: QWidget, width: int, height: int, min_w: int = 800, min_h: int = 500) -> None:
    """Size a window (logical px), keep it on the screen, centre it, set its minimum size."""
    scr = (win.screen() or QApplication.primaryScreen()).availableGeometry()
    w, h = min(width, scr.width() - 60), min(height, scr.height() - 110)
    win.resize(w, h)
    win.setMinimumSize(min(min_w, w), min(min_h, h))
    win.move(scr.left() + max(0, (scr.width() - w) // 2), scr.top() + max(0, (scr.height() - h) // 3))


def center_on(win: QWidget, parent: QWidget | None) -> None:
    ref = (parent.window() if parent is not None else None) or QApplication.activeWindow()
    if ref is None:
        return
    g = win.frameGeometry()
    g.moveCenter(ref.frameGeometry().center())
    win.move(g.topLeft())


def dialog(parent, title: str, modal: bool = True, **kw):
    """A themed, centred, Esc-closable modal window (ModalDialog; the title carries the demo suffix like ui.dialog)."""
    d = W.ModalDialog(parent if isinstance(parent, QWidget) else None, title + core.DEMO_SUFFIX, modal=modal, **kw)
    return d


def themed_menu(parent=None) -> QMenu:
    return QMenu(parent)


def post_menu(menu: QMenu, x_root: int, y_root: int) -> None:
    menu.exec(QPoint(int(x_root), int(y_root)))


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# status widgets
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class Pill(W.Badge):
    """ui.Pill(parent, text, kind): the small coloured status badge.  `.set(text, kind)`."""

    def __init__(self, parent=None, text: str = '', kind: str = 'neutral'):
        super().__init__(text, kind)
        if isinstance(parent, QWidget):
            self.setParent(parent)


class Notice(W.Banner):
    """ui.Notice(parent, text, kind, textvariable=None, title=None): a coloured call-out strip.  kind 'info' | 'warn' | 'good' | 'bad'."""

    def __init__(self, parent=None, text: str = '', kind: str = 'info', textvariable: QtVar | None = None, title: str | None = None):
        super().__init__(text, 'error' if kind == 'bad' else kind, title=title or '')
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        if isinstance(parent, QWidget):
            self.setParent(parent)
        self.label = self.text_label
        if textvariable is not None:
            bind(self.text_label, textvariable)


class Banner(QFrame):
    """ui.Banner(parent, title, subtitle): the title strip at the top of a window; `.subtitle` is a QtVar, `.add_pill(text, kind)` adds a status pill at the right."""

    def __init__(self, parent=None, title: str = '', subtitle: str = ''):
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.setProperty('surface', 'bar')
        row = QHBoxLayout(self)
        row.setContentsMargins(M.xl, M.md, M.xl, M.md)
        row.setSpacing(M.md)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = W.label(title, 'title')
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.subtitle = QtVar(subtitle)
        self.sub_label = W.label(subtitle, 'sub', wrap=True)
        self.sub_label.setTextFormat(Qt.TextFormat.PlainText)
        bind(self.sub_label, self.subtitle)
        col.addWidget(self.title_label)
        col.addWidget(self.sub_label)
        row.addLayout(col, 1)
        self.right = QWidget()
        self.right_layout = QHBoxLayout(self.right)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(M.sm)
        row.addWidget(self.right, 0, Qt.AlignmentFlag.AlignTop)

    def add_pill(self, text: str, kind: str = 'info') -> Pill:
        p = Pill(None, text, kind)
        self.right_layout.addWidget(p)
        return p


class StatusBar(QFrame):
    """ui.StatusBar(parent, variable, right=''): coloured dot + message (colour follows the wording, ui_theme_core.status_kind), small buttons and the version text at
    the right.  `.var` is the QtVar (also `.set(text)`); `.add_button(text, command)`."""

    def __init__(self, parent=None, variable: QtVar | None = None, right: str = ''):
        super().__init__(parent if isinstance(parent, QWidget) else None)
        self.setProperty('surface', 'barbottom')
        self.var = variable if variable is not None else QtVar('')
        row = QHBoxLayout(self)
        row.setContentsMargins(M.lg, 5, M.lg, 5)
        row.setSpacing(M.sm)
        self.line = W.StatusLine('')
        self.line.setWordWrap(True)
        self.line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.line, 1)
        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(M.sm)
        row.addLayout(self._buttons)
        try:                                           # every window shows the same suite version (a spec / procedure note may come first)
            import suite_info
            right = suite_info.full_version() if (not right or right.startswith('v')) else f'{right}  |  {suite_info.full_version()}'
        except ImportError:
            pass
        self.right = W.label(right, 'hint')
        self.right.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.right)
        self.var.trace_add('write', lambda *_: self._sync())
        self._sync()

    def _sync(self) -> None:
        from . import app
        if app.is_ui_thread() or app._invoker is None:
            self.line.set(str(self.var.get()))
        else:
            app.post(lambda: self.line.set(str(self.var.get())))

    def set(self, text: str) -> None:
        self.var.set(text)

    def add_button(self, text: str, command: Callable, style: str | None = None) -> QPushButton:
        b = button(None, text, command)
        self._buttons.addWidget(b)
        return b


class Summary(QFrame):
    """ui.Summary: 'x of y tested' + a progress bar + pass / fail / remaining pills.  update_counts(total, passed, failed)."""

    def __init__(self, parent=None):
        super().__init__(parent if isinstance(parent, QWidget) else None)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        top = QHBoxLayout()
        self.text = QtVar('Nothing tested yet')
        self._label = W.label('Nothing tested yet', 'section')
        bind(self._label, self.text)
        top.addWidget(self._label, 1)
        self.ok, self.fail, self.rem = Pill(None, '0 pass'), Pill(None, '0 fail'), Pill(None, '0 remaining')
        for p in (self.ok, self.fail, self.rem):
            top.addWidget(p)
        col.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)

    def update_counts(self, total: int, passed: int, failed: int) -> None:
        done = passed + failed
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.text.set(f'{done} of {total} tested')
        self.ok.set(f'{passed} pass', 'good' if passed else 'neutral')
        self.fail.set(f'{failed} fail', 'bad' if failed else 'neutral')
        left = total - done
        self.rem.set('All points tested' if left == 0 and total else f'{left} remaining', 'good' if left == 0 and total and not failed else 'neutral')


class Tooltip(QObject):
    """ui.Tooltip(widget, text | callable): the text may be a function (evaluated when the tip opens)."""

    def __init__(self, widget: QWidget, text):
        super().__init__(widget)
        self.widget, self.text = widget, text
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        self._refresh()

    def _current(self) -> str:
        return str(self.text() if callable(self.text) else self.text or '')

    def _refresh(self) -> None:
        self.widget.setToolTip(self._current())

    def eventFilter(self, obj, ev):
        if obj is self.widget and ev.type() in (QEvent.Type.Enter, QEvent.Type.ToolTip, QEvent.Type.HoverEnter):
            self._refresh()
        return False


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the ttk widgets as factories (+ the Tk-style configure / cget the views use on them), and pack / grid
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class _TkLike:
    """Mixin for Qt widgets standing in for ttk widgets: configure(state=, text=, values=, command=), cget('state' | 'text')."""

    def configure(self, **kw):
        for k, v in kw.items():
            if k == 'state':
                self.setEnabled(v != 'disabled')
                if isinstance(self, QComboBox) and not self.isEditable():
                    pass
                if isinstance(self, QLineEdit):
                    self.setReadOnly(v == 'readonly')
            elif k == 'text':
                self.setText(str(v))
            elif k == 'values' and isinstance(self, QComboBox):
                cur = self.currentText()
                self.blockSignals(True)
                self.clear()
                self.addItems([str(x) for x in v])
                self.setCurrentText(cur) if self.isEditable() else (self.setCurrentIndex(self.findText(cur)) if self.findText(cur) >= 0 else None)
                self.blockSignals(False)
            elif k == 'command' and isinstance(self, QAbstractButton):
                try:
                    self.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self.clicked.connect(lambda _c=False, f=v: f())
            elif k == 'style':
                self._apply_style(v)
            # width / wraplength / padding and other Tk-only geometry options are ignored

    config = configure

    def cget(self, key):
        if key == 'state':
            return 'normal' if self.isEnabled() else 'disabled'
        if key == 'text':
            return self.text()
        raise KeyError(key)

    def _apply_style(self, style):
        s = str(style)
        role = 'primary' if 'Accent' in s else ('danger' if 'Danger' in s else None)
        W.set_prop(self, 'role', role)

    def __setitem__(self, key, value):
        self.configure(**{key: value})


class Button(_TkLike, QPushButton):
    pass


class Combobox(_TkLike, QComboBox):
    @property
    def values(self):
        return [self.itemText(i) for i in range(self.count())]


class Entry(_TkLike, QLineEdit):
    pass


class Checkbutton(_TkLike, QCheckBox):
    pass


class Radiobutton(_TkLike, QRadioButton):
    pass


def frame(parent=None, layout: str = 'v', margins=(0, 0, 0, 0), spacing: int = 0) -> QWidget:
    """A plain container with a layout ('v' | 'h' | 'grid') ready to be filled (ttk.Frame)."""
    f = QWidget(parent if isinstance(parent, QWidget) else None)
    lay = {'v': QVBoxLayout, 'h': QHBoxLayout, 'grid': QGridLayout}[layout](f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f


def label_(parent=None, text: str = '', style: str | None = None, textvariable: QtVar | None = None, wraplength: int | None = None) -> QLabel:
    """ttk.Label: style 'Bold.TLabel' | 'Muted.TLabel' | 'Small.TLabel' | 'Section.TLabel' -> a typography role; always plain text."""
    role = {'Bold': 'section', 'Muted': 'sub', 'Small': 'hint', 'Section': 'h2', 'Banner': 'title'}.get((style or '').split('.')[0].replace('Banner', 'Banner'))
    lab = W.label(text, role, wrap=bool(wraplength))
    lab.setTextFormat(Qt.TextFormat.PlainText)
    if textvariable is not None:
        bind(lab, textvariable)
    if isinstance(parent, QWidget):
        lab.setParent(parent)
    return lab


def button(parent=None, text: str = '', command: Callable | None = None, style: str | None = None, state: str | None = None) -> Button:
    b = Button(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoDefault(False)
    if style:
        b._apply_style(style)
    if command is not None:
        b.clicked.connect(lambda _c=False: command())
    if state:
        b.configure(state=state)
    if isinstance(parent, QWidget):
        b.setParent(parent)
    return b


def entry(parent=None, textvariable: QtVar | None = None, width: int | None = None, show: str | None = None, state: str | None = None) -> Entry:
    e = Entry()
    if show:
        e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setMinimumWidth(90)
    if width:
        e.setProperty('chars', width)                  # a hint (Tk's width=): Shell.build_identity fixes the width, a form lets the entry fill its column
    if textvariable is not None:
        bind(e, textvariable)
    if state:
        e.configure(state=state)
    if isinstance(parent, QWidget):
        e.setParent(parent)
    return e


def combobox(parent=None, textvariable: QtVar | None = None, values: Iterable = (), width: int | None = None, state: str = 'readonly',
             command: Callable | None = None) -> Combobox:
    """ttk.Combobox: state 'readonly' (pick) or 'normal' (editable); `command` is the <<ComboboxSelected>> handler (called with no argument)."""
    c = Combobox()
    c.addItems([str(v) for v in values])
    c.setEditable(state != 'readonly')
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(width or 10)
    c.setMinimumWidth(90)                              # may shrink in a narrow form; `width` (Tk's width=, in characters) is only the preferred size
    if textvariable is not None:
        bind(c, textvariable)
    if command is not None:
        c.activated.connect(lambda _i=0: command())
    if state == 'disabled':
        c.setEnabled(False)
    if isinstance(parent, QWidget):
        c.setParent(parent)
    return c


def checkbutton(parent=None, text: str = '', variable: QtVar | None = None, command: Callable | None = None) -> Checkbutton:
    c = Checkbutton(text)
    if variable is not None:
        bind(c, variable)
    if command is not None:
        c.clicked.connect(lambda _c=False: command())
    if isinstance(parent, QWidget):
        c.setParent(parent)
    return c


def radiobutton(parent=None, text: str = '', value: Any = None, variable: QtVar | None = None, command: Callable | None = None) -> Radiobutton:
    r = Radiobutton(text)
    if variable is not None:
        bind(r, variable, value=value)
    if command is not None:
        r.clicked.connect(lambda _c=False: command())
    if isinstance(parent, QWidget):
        r.setParent(parent)
    return r


def separator(vertical: bool = False) -> QFrame:
    return W.rule(vertical)


_ALIGN = {'n': Qt.AlignmentFlag.AlignTop, 's': Qt.AlignmentFlag.AlignBottom, 'w': Qt.AlignmentFlag.AlignLeft, 'e': Qt.AlignmentFlag.AlignRight}


def _align(sticky: str):
    a = Qt.AlignmentFlag(0)
    h_fill, v_fill = 'w' in sticky and 'e' in sticky, 'n' in sticky and 's' in sticky
    for ch in sticky:
        if ch in 'we' and not h_fill:
            a |= _ALIGN[ch]
        if ch in 'ns' and not v_fill:
            a |= _ALIGN[ch]
    return a


def _pad(v) -> tuple[int, int]:
    return (int(v[0]), int(v[1])) if isinstance(v, (tuple, list)) else (int(v), int(v))


def _wrap_pad(widget: QWidget, padx, pady) -> QWidget:
    (l, r), (t, b) = _pad(padx), _pad(pady)
    if not (l or r or t or b):
        return widget
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(l, t, r, b)
    lay.setSpacing(0)
    lay.addWidget(widget)
    box._inner = widget
    return box


def pack(parent: QWidget, widget: QWidget, side: str = 'top', fill: str | None = None, expand: bool = False, padx=0, pady=0, anchor: str | None = None) -> QWidget:
    """Tk pack(): add `widget` to parent's box layout.  Returns the widget (or the padding wrapper that now holds it)."""
    lay = parent.layout()
    horizontal = side in ('left', 'right')
    if lay is None:
        lay = (QHBoxLayout if horizontal else QVBoxLayout)(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
    host = _wrap_pad(widget, padx, pady)
    align = _align(anchor or '') if anchor else Qt.AlignmentFlag(0)
    if fill in ('x', 'both') and not horizontal:
        align = Qt.AlignmentFlag(0)
    if side in ('right', 'bottom'):
        # Tk packs 'right' items from the right edge inwards: each later one sits further left, i.e. before the right-packed ones already there
        n = int(lay.property('packed_end') or 0)
        lay.insertWidget(lay.count() - n, host, 1 if expand else 0, align)
        lay.setProperty('packed_end', n + 1)
    else:
        lay.insertWidget(lay.count() - int(lay.property('packed_end') or 0), host, 1 if expand else 0, align)
    return host


def grid(parent: QWidget, widget: QWidget, row: int = 0, column: int = 0, rowspan: int = 1, columnspan: int = 1, sticky: str = '', padx=0, pady=0) -> QWidget:
    """Tk grid(): add `widget` to parent's QGridLayout (created on first use).  Column / row weights: grid_weight(parent, column=1, weight=1)."""
    lay = parent.layout()
    if lay is None:
        lay = QGridLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(0)
        lay.setVerticalSpacing(0)
    host = _wrap_pad(widget, padx, pady)
    lay.addWidget(host, row, column, rowspan, columnspan, _align(sticky))
    return host


def grid_weight(parent: QWidget, column: int | None = None, row: int | None = None, weight: int = 1) -> None:
    """Tk columnconfigure / rowconfigure(weight=)."""
    lay = parent.layout()
    if column is not None:
        lay.setColumnStretch(column, weight)
    if row is not None:
        lay.setRowStretch(row, weight)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the results table with the Treeview calls
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class TreeRow:
    __slots__ = ('iid', 'values', 'tags')

    def __init__(self, iid: str, values: Sequence, tags: Sequence[str] = ()):
        self.iid, self.values, self.tags = str(iid), list(values), tuple(tags)


TAG_TONE = {'fail': 'fail', 'error': 'warn', 'next': 'info'}          # a passed row is not tinted (its Result cell is green): 100 green rows would shout


def row_tone(row: TreeRow):
    for t in row.tags:
        if t in TAG_TONE:
            return TAG_TONE[t]
    return None


class ResultsTree(DataTable):
    """A DataTable that answers the ttk.Treeview calls the Tk views make on `self.tree` (insert / delete / get_children / selection / selection_set / see / exists /
    item / heading / column / configure(displaycolumns=) / bind('<<TreeviewSelect>>', fn)), so the views' table_* helpers port by renaming one import.  Rows are TreeRow
    (iid, values, tags); the tags 'pass' / 'fail' / 'error' / 'next' tint the row, 'pending' mutes the text."""

    def __init__(self, columns: Sequence[str], headings: Sequence[str], widths: Sequence[int], anchors: dict | None = None, stretch: dict | None = None,
                 selectmode: str = 'browse', mono: Iterable[str] = ()):
        anchors, stretch = anchors or {}, stretch or {}
        cols = []
        cands = [i for i, c in enumerate(columns) if stretch.get(c, True)]
        stretch_idx = max(cands, key=lambda i: widths[i]) if cands else None            # the widest stretchable column takes the free width (a DataTable has one)
        for i, (key, head, width) in enumerate(zip(columns, headings, widths)):
            want = i == stretch_idx
            align = {'w': 'left', 'e': 'right'}.get(anchors.get(key, 'center'), 'center')
            cols.append(Column(key, head, width=px(width), align=align, stretch=bool(want), mono=key in set(mono), getter=lambda r, _i=i: r.values[_i] if _i < len(r.values) else '',
                               tone=(lambda r, _i=i: 'muted' if 'pending' in r.tags and _i > 1 else None)))
        super().__init__(cols, [], row_tone=row_tone, row_key=lambda r: r.iid, multi=selectmode != 'browse', alternating=False, tone_style='both')
        self._keys = list(columns)
        self._by_iid: dict[str, TreeRow] = {}
        self._select_cb: list[Callable] = []
        self.selectionChangedRows.connect(lambda rows: [cb(None) for cb in list(self._select_cb)])
        self.setMinimumHeight(140)

    # ---- Treeview calls
    def insert(self, parent, index, iid=None, values=(), tags=(), **_kw):
        iid = str(iid if iid is not None else len(self._by_iid))
        row = TreeRow(iid, values, tags if isinstance(tags, (tuple, list)) else (tags,))
        if iid in self._by_iid:
            self.delete(iid)
        self._by_iid[iid] = row
        self.append_rows([row])
        return iid

    def delete(self, *iids):
        if not iids:
            return
        rows = [self._by_iid.pop(str(i)) for i in iids if str(i) in self._by_iid]
        if len(rows) and not self._by_iid:
            self.set_rows([], keep_selection=False)
        elif rows:
            self.source_model.remove_rows(rows)

    def set_all(self, rows: Iterable[tuple], keep: Sequence[str] = ()):
        """Replace every row at once: rows = (iid, values, tags); `keep` = iids to re-select if still present."""
        objs = [TreeRow(i, v, t) for i, v, t in rows]
        self._by_iid = {r.iid: r for r in objs}
        self.set_rows(objs, keep_selection=False)
        if keep:
            self.selection_set(*[k for k in keep if k in self._by_iid][:1])

    def get_children(self, item=''):
        return tuple(r.iid for r in self.rows())

    def exists(self, iid) -> bool:
        return str(iid) in self._by_iid

    def selection(self):
        return tuple(r.iid for r in self.selected_rows())

    def selection_set(self, *iids):
        if len(iids) == 1 and isinstance(iids[0], (list, tuple)):
            iids = tuple(iids[0])
        self.select_rows([self._by_iid[str(i)] for i in iids if str(i) in self._by_iid])

    def selection_remove(self, *iids):
        keep = [r for r in self.selected_rows() if r.iid not in {str(i) for i in iids}]
        self.select_rows(keep)

    def see(self, iid):
        if str(iid) in self._by_iid:
            self.scroll_to_row(self._by_iid[str(iid)])

    def item(self, iid, option=None, **kw):
        row = self._by_iid[str(iid)]
        if not kw:
            data = dict(values=list(row.values), tags=row.tags)
            return data if option is None else data[option]
        if 'values' in kw:
            row.values = list(kw['values'])
        if 'tags' in kw:
            t = kw['tags']
            row.tags = tuple(t) if isinstance(t, (tuple, list)) else (t,)
        self.refresh(row)
        return None

    def heading(self, col, text=None, **_kw):
        i = self._keys.index(col)
        if text is not None:
            self.source_model.columns[i].title = text
            self.source_model.headerDataChanged.emit(Qt.Orientation.Horizontal, i, i)
            self.horizontalHeader().viewport().update()
        return self.source_model.columns[i].title

    def column(self, col, width=None, **_kw):
        i = self._keys.index(col)
        if width is not None:
            self.setColumnWidth(i, px(width))
        return {'width': self.columnWidth(i)}

    def configure(self, **kw):
        if 'displaycolumns' in kw:
            show = set(kw['displaycolumns'])
            for i, key in enumerate(self._keys):
                self.setColumnHidden(i, key not in show)

    config = configure

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def bind(self, sequence, fn, add=None):
        if sequence == '<<TreeviewSelect>>':
            self._select_cb.append(fn)
        elif sequence in ('<Double-1>', '<Return>'):
            self.rowActivated.connect(lambda _r: fn(None))

    def tag_configure(self, *_a, **_k):
        return None

    def focus(self, iid=None):
        self.setFocus()

    @property
    def master(self):
        return self.parentWidget()


def make_table(parent, columns, headings, widths, anchors=None, height=10, selectmode='browse', zebra=False, hscroll=False, stretch=None, pack_=True, mono=()) -> ResultsTree:
    """ui.make_table: the table, added to parent's layout (a QVBoxLayout / QHBoxLayout is created if the parent has none) unless pack_=False."""
    tree = ResultsTree(columns, headings, widths, anchors, stretch, selectmode, mono)
    tree.setMinimumHeight(min(height, 6) * M.row_h // 2 + M.header_h)
    if zebra:
        tree.setAlternatingRowColors(True)
    if pack_ and isinstance(parent, QWidget):
        lay = parent.layout()
        if lay is None:
            lay = QVBoxLayout(parent)
            lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tree, 1) if not isinstance(lay, QGridLayout) else lay.addWidget(tree, lay.rowCount(), 0)
    return tree


def style_result_tags(tree, zebra: bool = False) -> None:
    """Tk coloured the tags; ResultsTree tints rows by tag itself."""
    return None
