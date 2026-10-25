"""Reusable building blocks with the approved look.  Colours and sizes come from qtui.theme (QSS selectors on `role` / `badge` / `surface` / `banner`
properties plus a few painted icons); a widget never hard-codes a colour.  No instrument or engine import here.

    Card, Badge, SegmentedFilter, InfoButton, PrimaryButton / SecondaryButton / DangerButton / GhostButton, SectionHeader, KeyValueStrip, Banner,
    SearchField, Toast, StatusLine, EmptyState, ModalDialog, MessageDialog, ProgressDialog, plus small helpers (label, rule, set_prop, make_tab_bar).
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QFontMetrics, QKeyEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSizePolicy,
                               QTabBar, QVBoxLayout, QWidget)

import ui_theme_core as core
from . import theme
from .theme import M


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def set_prop(w: QWidget, name: str, value) -> None:
    """Set a dynamic property that a QSS selector reads, and re-polish so the style changes now."""
    w.setProperty(name, value)
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


def label(text: str = '', role: str | None = None, *, wrap: bool = False, parent: QWidget | None = None) -> QLabel:
    """A QLabel with a typography role: 'title' | 'h2' | 'section' | 'sub' | 'hint' | 'mono' | 'kvkey' | 'kvvalue' | 'chip'."""
    lab = QLabel(text, parent)
    if role:
        lab.setProperty('role', role)
    lab.setWordWrap(wrap)
    return lab


def rule(vertical: bool = False) -> QFrame:
    f = QFrame()
    f.setProperty('surface', 'vrule' if vertical else 'rule')
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def make_tab_bar(items: Sequence[str], *, sub: bool = False, parent: QWidget | None = None) -> QTabBar:
    """The flat tab strip (a QTabBar; pair it with a QStackedWidget).  sub=True is the denser second-level strip."""
    bar = QTabBar(parent)
    for t in items:
        bar.addTab(t)
    bar.setExpanding(False)
    bar.setDrawBase(False)
    bar.setProperty('sub', sub)
    bar.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return bar


class _StyleFollower(QObject):
    """Re-applies a widget's own style sheet (built from the tokens) after every theme switch; it lives and dies with the widget."""

    def __init__(self, widget: QWidget, build: Callable[[], str]):
        super().__init__(widget)
        self._w, self._build = widget, build
        theme.manager().changed.connect(self.apply)
        self.apply()

    def apply(self, *_):
        try:
            self._w.setStyleSheet(self._build())
        except RuntimeError:
            pass


def follow_tokens(widget: QWidget, build: Callable[[], str]) -> None:
    """`widget.setStyleSheet(build())` now and again after every theme switch (for a style sheet that names token colours).  Calling it again on the same
    widget replaces the earlier `build`."""
    for old in widget.findChildren(_StyleFollower, options=Qt.FindChildOption.FindDirectChildrenOnly):
        old.deleteLater()
        try:
            theme.manager().changed.disconnect(old.apply)
        except (RuntimeError, TypeError):
            pass
    _StyleFollower(widget, build)


def follow_theme(widget: QWidget, apply: Callable[[], None]) -> None:
    """Run `apply()` now and after every theme switch (for a widget that sets a pixmap / icon from the tokens); it lives and dies with the widget."""
    def run(*_):
        try:
            apply()
        except RuntimeError:
            pass
    holder = QObject(widget)
    holder.run = run                                           # keep the callable alive as long as the widget
    theme.manager().changed.connect(run)
    run()
    holder.destroyed.connect(lambda *_: _disconnect(run))


def _disconnect(fn) -> None:
    try:
        theme.manager().changed.disconnect(fn)
    except (RuntimeError, TypeError):
        pass


class _Themed:
    """Mixin for widgets that paint or build icons themselves: `_retheme()` runs at once and after every theme switch."""

    def _watch_theme(self):
        theme.manager().changed.connect(self._retheme)
        self._retheme()

    def _retheme(self, *_):
        pass


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# cards, badges, section headers
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class Card(QFrame):
    """A rounded surface with an optional title.  Put content in `.body` (a QVBoxLayout)."""

    def __init__(self, title: str = '', *, parent: QWidget | None = None, padding: int = M.lg):
        super().__init__(parent)
        self.setProperty('surface', 'card')
        self.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(padding, padding, padding, padding)
        outer.setSpacing(M.md)
        self.title_label = label(title, 'h2')
        self.title_label.setVisible(bool(title))
        self.title_label.setWordWrap(True)
        outer.addWidget(self.title_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(M.sm)
        outer.addLayout(self.body)
        outer.addStretch(1)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)
        self.title_label.setVisible(bool(text))

    def add(self, w: QWidget | None = None, **kw):
        if w is not None:
            self.body.addWidget(w, **kw)
        return w

    def add_rule(self) -> None:
        self.body.addWidget(rule())


class Badge(QLabel):
    """A pill: kind 'good' | 'warn' | 'bad' | 'info' | 'neutral'.  `small=True` for use inside dense rows.  The fixed height keeps it a true pill."""

    def __init__(self, text: str = '', kind: str = 'neutral', *, small: bool = False, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._small = small
        self.setProperty('small', small)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(M.badge_h_sm if small else M.badge_h)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        kind = kind if kind in theme.KINDS else 'neutral'
        self._kind = kind
        set_prop(self, 'badge', kind)

    def kind(self) -> str:
        return self._kind

    def set(self, text: str, kind: str | None = None) -> None:
        self.setText(text)
        if kind is not None:
            self.set_kind(kind)


class SectionHeader(QWidget):
    """Title (+ optional sub line) on the left, any number of trailing widgets (badges, buttons) on the right."""

    def __init__(self, title: str, subtitle: str = '', *, level: str = 'title', trailing: Iterable[QWidget] = (), parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(M.md)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = label(title, level)
        self.sub_label = label(subtitle, 'sub')
        self.sub_label.setVisible(bool(subtitle))
        col.addWidget(self.title_label)
        col.addWidget(self.sub_label)
        row.addLayout(col)
        row.addStretch(1)
        self._trail = QHBoxLayout()
        self._trail.setSpacing(M.sm)
        row.addLayout(self._trail)
        for w in trailing:
            self.add_trailing(w)

    def add_trailing(self, w: QWidget) -> None:
        self._trail.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_subtitle(self, text: str) -> None:
        self.sub_label.setText(text)
        self.sub_label.setVisible(bool(text))


class KeyValueStrip(QFrame):
    """A thin band of 'Key  **value**' pairs (the review window's technician / temperature strip).  Trailing widgets go on the right."""

    def __init__(self, items: Sequence[tuple[str, str]] = (), *, trailing: Iterable[QWidget] = (), margin: int = M.page_margin, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty('surface', 'strip')
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(margin, M.sm, margin, M.sm)
        self._row.setSpacing(M.xl)
        self._values: dict[str, QLabel] = {}
        self._pairs = QHBoxLayout()
        self._pairs.setSpacing(M.xl)
        self._row.addLayout(self._pairs)
        self._row.addStretch(1)
        for k, v in items:
            self.add_item(k, v)
        for w in trailing:
            self._row.addWidget(w)

    def add_item(self, key: str, value: str) -> None:
        box = QHBoxLayout()
        box.setSpacing(M.sm - 2)
        k = label(key, 'kvkey')
        v = label(value, 'kvvalue')
        box.addWidget(k)
        box.addWidget(v)
        self._pairs.addLayout(box)
        self._values[key] = v

    def set_value(self, key: str, value: str) -> None:
        self._values[key].setText(value)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# buttons
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class _Button(QPushButton):
    ROLE: str | None = None

    def __init__(self, text: str = '', *, parent: QWidget | None = None, on_click: Callable | None = None):
        super().__init__(text, parent)
        if self.ROLE:
            self.setProperty('role', self.ROLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoDefault(False)
        if on_click:
            self.clicked.connect(lambda _c=False: on_click())


class PrimaryButton(_Button):
    """The one main action of a screen or dialog."""
    ROLE = 'primary'


class SecondaryButton(_Button):
    ROLE = None


class DangerButton(_Button):
    """A destructive or safety-relevant action (red)."""
    ROLE = 'danger'


class GhostButton(_Button):
    """A text-only button (accent colour, no frame)."""
    ROLE = 'ghost'


class InfoPopover(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None, *, width: int = 320):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setProperty('surface', 'popover')
        v = QVBoxLayout(self)
        v.setContentsMargins(M.md, M.md - 2, M.md, M.md - 2)
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setFixedWidth(width)
        v.addWidget(self.text_label)


class InfoButton(QPushButton):
    """The round 'i': click (or Space / Enter when focused) opens a small popover with the explanation; also its tooltip."""

    def __init__(self, text: str = '', *, parent: QWidget | None = None):
        super().__init__('i', parent)
        self.setProperty('role', 'info')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setAccessibleName('More information')
        self._pop: InfoPopover | None = None
        self.set_text(text)
        self.clicked.connect(self.toggle)

    def set_text(self, text: str) -> None:
        self._text = text
        self.setToolTip(text if len(text) < 120 else text[:117] + '...')
        self.setAccessibleDescription(text)

    def toggle(self, *_):
        if self._pop is not None and self._pop.isVisible():
            self._pop.close()
            return
        self._pop = InfoPopover(self._text, self)
        self._pop.adjustSize()
        pos = self.mapToGlobal(QPoint(self.width() // 2 - self._pop.width() // 2, self.height() + 6))
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        pos.setX(max(scr.left() + 4, min(pos.x(), scr.right() - self._pop.width() - 4)))
        self._pop.move(pos)
        self._pop.show()


class SegmentedFilter(QFrame):
    """A pill-shaped segmented control: items = [(key, 'All', count_or_None), ...].  One Tab stop for the whole control; Left / Right move the choice."""
    currentChanged = Signal(str)

    def __init__(self, items: Sequence[tuple], *, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty('surface', 'segment')
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, str] = {}
        for it in items:
            key, text = it[0], it[1]
            count = it[2] if len(it) > 2 else None
            b = QPushButton()
            b.setProperty('role', 'seg')
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.installEventFilter(self)
            self._group.addButton(b)
            row.addWidget(b)
            self._buttons[key] = b
            self._labels[key] = text
            self.set_count(key, count)
            b.clicked.connect(lambda _c=False, k=key: self._choose(k))
        self._current = items[0][0] if items else ''
        if items:
            self._buttons[self._current].setChecked(True)
        self._rove()

    def _fit_height(self) -> None:
        """Size every segment from the font it is really drawn in (after the style sheet: the chosen one is semi-bold), so no font or Windows scaling can clip the text."""
        try:
            for b in self._buttons.values():
                f = QFont(b.font())
                f.setWeight(QFont.Weight.DemiBold)
                b.setMinimumHeight(QFontMetrics(f).height() + 16)
        except RuntimeError:                  # the window closed before the deferred call ran
            pass

    def showEvent(self, ev):
        self._fit_height()
        super().showEvent(ev)

    def changeEvent(self, ev):
        if ev.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.ApplicationFontChange):
            QTimer.singleShot(0, self._fit_height)
        super().changeEvent(ev)

    def set_count(self, key: str, count: int | None) -> None:
        b = self._buttons[key]
        b.setText(self._labels[key] if count is None else f'{self._labels[key]}  {count}')

    def current(self) -> str:
        return self._current

    def set_current(self, key: str, *, emit: bool = False) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
            self._choose(key, emit=emit)

    def _choose(self, key: str, emit: bool = True) -> None:
        changed = key != self._current
        self._current = key
        self._rove()
        if changed and emit:
            self.currentChanged.emit(key)

    def _rove(self) -> None:
        for k, b in self._buttons.items():
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus if k == self._current else Qt.FocusPolicy.NoFocus)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and isinstance(ev, QKeyEvent) and ev.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            keys = list(self._buttons)
            i = keys.index(self._current)
            step = -1 if ev.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
            nxt = keys[(i + step) % len(keys)]
            self._buttons[nxt].setChecked(True)
            self._choose(nxt)
            self._buttons[nxt].setFocus()
            return True
        return super().eventFilter(obj, ev)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# banner, search, toast, status line, empty state
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class Banner(QFrame, _Themed):
    """An inline message strip: kind 'info' | 'warn' | 'error' | 'good'.  Optional bold title, optional close button."""
    closed = Signal()
    _ICON = {'info': 'info', 'warn': 'warn', 'error': 'error', 'good': 'good'}

    def __init__(self, text: str = '', kind: str = 'info', *, title: str = '', closable: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = kind if kind in self._ICON else 'info'
        self.setProperty('banner', self._kind)
        self.setFrameShape(QFrame.Shape.NoFrame)
        row = QHBoxLayout(self)
        row.setContentsMargins(M.md, M.md - 2, M.md, M.md - 2)
        row.setSpacing(M.md - 2)
        self._icon = QLabel()
        self._icon.setFixedSize(M.icon + 2, M.icon + 2)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setProperty('bannertitle', self._kind)
        self.title_label.setWordWrap(True)
        self.title_label.setVisible(bool(title))
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.title_label)
        col.addWidget(self.text_label)
        row.addLayout(col, 1)
        self.close_button = None
        if closable:
            self.close_button = QPushButton()
            self.close_button.setProperty('role', 'icon')
            self.close_button.setAccessibleName('Dismiss')
            self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.close_button.clicked.connect(self._dismiss)
            row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._watch_theme()

    def _dismiss(self):
        self.hide()
        self.closed.emit()

    def set_text(self, text: str, title: str | None = None) -> None:
        self.text_label.setText(text)
        if title is not None:
            self.title_label.setText(title)
            self.title_label.setVisible(bool(title))

    def set_kind(self, kind: str) -> None:
        self._kind = kind if kind in self._ICON else 'info'
        set_prop(self, 'banner', self._kind)
        set_prop(self.title_label, 'bannertitle', self._kind)
        self._retheme()

    def _retheme(self, *_):
        col = {'info': 'info', 'warn': 'warn', 'error': 'bad', 'good': 'good'}[self._kind]
        self._icon.setPixmap(theme.pixmap(self._ICON[self._kind], theme.tokens()[col], M.icon + 2))
        if self.close_button is not None:
            from PySide6.QtGui import QIcon
            self.close_button.setIcon(theme.icon('close', col))


class SearchField(QLineEdit, _Themed):
    """A search box: magnifier, clear button, Esc clears, and a debounced `queryChanged(text)` for filtering big tables."""
    queryChanged = Signal(str)

    def __init__(self, placeholder: str = 'Search', *, delay_ms: int = 150, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAccessibleName(placeholder)
        self._lead = QAction(self)
        self.addAction(self._lead, QLineEdit.ActionPosition.LeadingPosition)
        self._clear = QAction(self)
        self._clear.setToolTip('Clear')
        self._clear.triggered.connect(self.clear)
        self.addAction(self._clear, QLineEdit.ActionPosition.TrailingPosition)
        self._clear.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(lambda: self.queryChanged.emit(self.text()))
        self.textChanged.connect(self._on_text)
        self._watch_theme()

    def _on_text(self, text: str) -> None:
        self._clear.setVisible(bool(text))
        if self._timer.interval() <= 0:
            self.queryChanged.emit(text)
        else:
            self._timer.start()

    def _retheme(self, *_):
        self._lead.setIcon(theme.icon('search', 'muted'))
        self._clear.setIcon(theme.icon('clear', 'faint'))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def flush(self) -> None:
        """Emit the pending query now (tests, or before reading a filtered table)."""
        if self._timer.isActive():
            self._timer.stop()
            self.queryChanged.emit(self.text())


class Toast(QFrame):
    """A short message that floats at the bottom centre of a window and fades away.  `Toast.notify(window, 'Saved', 'good')`; one at a time per window."""
    _live: dict = {}

    def __init__(self, parent: QWidget, text: str, kind: str = 'info', ms: int = 3500):
        super().__init__(parent)
        self.setProperty('toast', kind)
        row = QHBoxLayout(self)
        row.setContentsMargins(M.lg, M.sm + 2, M.lg, M.sm + 2)
        row.setSpacing(M.sm)
        dot = QLabel('●')
        follow_tokens(dot, lambda: f"color: {theme.tokens().get(kind + '_dot', theme.tokens()['info_dot'])};")
        row.addWidget(dot)
        self.text_label = QLabel(text)
        row.addWidget(self.text_label)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ms = ms
        parent.installEventFilter(self)

    @classmethod
    def notify(cls, window: QWidget, text: str, kind: str = 'info', ms: int = 3500) -> 'Toast':
        old = cls._live.pop(id(window), None)
        if old is not None:
            old.dismiss()
        t = cls(window, text, kind, ms)
        cls._live[id(window)] = t
        t._place()
        t.show()
        t.raise_()
        QTimer.singleShot(ms, t.dismiss)
        return t

    def _place(self) -> None:
        p = self.parentWidget()
        self.adjustSize()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - M.xxl + 8)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self._place()
        return False

    def dismiss(self) -> None:
        p = self.parentWidget()
        if p is not None and Toast._live.get(id(p)) is self:
            Toast._live.pop(id(p), None)
        try:
            self.hide()
            self.deleteLater()
        except RuntimeError:
            pass


class StatusLine(QLabel):
    """The status-bar message: coloured dot + text.  `set('Saved ...')` picks the colour from the wording (ui_theme_core.status_kind), or pass kind."""

    def __init__(self, text: str = '', parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = 'neutral'
        self._text = ''
        self.setTextFormat(Qt.TextFormat.RichText)
        self.set(text)
        theme.manager().changed.connect(self._on_theme)          # a bound slot: Qt drops the connection when the label is destroyed (a lambda would fire on a dead object)

    def set(self, text: str, kind: str | None = None) -> None:
        self._text = text
        self._kind = kind or core.status_kind(text)
        self._render()

    def kind(self) -> str:
        return self._kind

    def _on_theme(self, *_) -> None:
        self._render()

    def _render(self) -> None:
        import html
        t = theme.tokens()
        dot = t[self._kind + '_dot'] if self._kind in theme.KINDS else t['neutral_dot']
        self.setText(f'<span style="color:{dot}">●</span>&nbsp;&nbsp;{html.escape(self._text)}' if self._text else '')


class EmptyState(QFrame, _Themed):
    """'Nothing here yet': a drawn icon, a heading, one explanatory line and an optional action button."""

    def __init__(self, title: str, text: str = '', *, icon_name: str = 'inbox', action: str = '', on_action: Callable | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty('surface', 'empty')
        self._icon_name = icon_name
        col = QVBoxLayout(self)
        col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.setSpacing(M.sm)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = label(title, 'h2')
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label = label(text, 'sub', wrap=True)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setMaximumWidth(380)
        self.text_label.setVisible(bool(text))
        col.addStretch(1)
        col.addWidget(self._icon)
        col.addWidget(self.title_label)
        col.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.button = None
        if action:
            self.button = PrimaryButton(action, on_click=on_action)
            col.addSpacing(M.sm)
            col.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch(1)
        self._watch_theme()

    def _retheme(self, *_):
        self._icon.setPixmap(theme.pixmap(self._icon_name, theme.tokens()['faint'], 40))


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# dialogs
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class ModalDialog(QDialog):
    """Base for every modal window: header (title + optional subtitle), `.body` layout, right-aligned button row, Esc = cancel, Enter = the default button,
    centred on its parent, focus order = reading order (body fields top-left to bottom-right, then the buttons).

        dlg = ModalDialog(parent, 'Delete run?', subtitle='This cannot be undone.')
        dlg.body.addWidget(label('...'))
        dlg.add_button('Cancel', cancel=True)
        dlg.add_button('Delete', role='danger', result='delete', default=True)
        dlg.run()          # -> 'delete' | 'cancel' | None (closed with the window button / Esc when no cancel button)

    `result_key` holds the key of the button that closed the dialog.  A button gets `result` (default: its lower-cased text); cancel=True makes it the Esc button.
    """

    def __init__(self, parent: QWidget | None = None, title: str = '', *, subtitle: str = '', width: int | None = None, modal: bool = True,
                 close_button: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(modal)
        flags = Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint
        if close_button:
            flags |= Qt.WindowType.WindowCloseButtonHint
        self.setWindowFlags(flags)
        self.setSizeGripEnabled(False)
        self.result_key: str | None = None
        self._buttons: dict[str, QPushButton] = {}
        self._cancel_key: str | None = None
        self._auto_tab = True
        self.initial_focus: QWidget | None = None
        self._placed = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(M.xl, M.xl - 4, M.xl, M.lg)
        outer.setSpacing(M.md)
        self.title_label = label(title, 'h2', wrap=True)
        self.sub_label = label(subtitle, 'sub', wrap=True)
        self.sub_label.setVisible(bool(subtitle))
        outer.addWidget(self.title_label)
        outer.addWidget(self.sub_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(M.sm + 2)
        outer.addLayout(self.body)
        outer.addStretch(1)
        outer.addSpacing(M.xs)
        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(M.sm)
        self._button_row.addStretch(1)
        outer.addLayout(self._button_row)
        self.setMinimumWidth(width or M.dialog_w)

    # ---- content
    def set_title(self, text: str) -> None:
        self.setWindowTitle(text)
        self.title_label.setText(text)

    def add_text(self, text: str, role: str | None = None) -> QLabel:
        lab = label(text, role, wrap=True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(lab)
        return lab

    def add_button(self, text: str, *, role: str | None = None, result: str | None = None, default: bool = False, cancel: bool = False,
                   callback: Callable | None = None, close: bool = True) -> QPushButton:
        """role None | 'primary' | 'danger'.  `callback()` runs first; returning False keeps the dialog open (validation).  close=False never closes it."""
        b = QPushButton(text)
        if role:
            b.setProperty('role', role)
        b.setAutoDefault(default)
        b.setDefault(default)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        key = result or text.lower().replace('&', '').replace(' ', '_')
        self._buttons[key] = b
        if cancel:
            self._cancel_key = key

        def clicked(_c=False, k=key):
            if callback is not None and callback() is False:
                return
            if not close:
                return
            self.result_key = k
            if k == self._cancel_key:
                self.reject()
            else:
                self.accept()
        b.clicked.connect(clicked)
        self._button_row.addWidget(b)
        return b

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def set_busy(self, busy: bool) -> None:
        for b in self._buttons.values():
            b.setEnabled(not busy)

    # ---- running
    def run(self) -> str | None:
        """Show modally; returns the key of the button pressed, or None."""
        self.result_key = None
        self.exec()
        return self.result_key

    def reject(self) -> None:
        if self.result_key is None and self._cancel_key:
            self.result_key = self._cancel_key
        super().reject()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._placed:
            self._placed = True
            self.adjustSize()
            self._center()
            if self._auto_tab:
                self._order_focus()

    def _center(self) -> None:
        par = self.parentWidget()
        win = par.window() if par is not None else None
        if win is not None and win.isVisible():
            geo = win.frameGeometry()
        else:
            geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        r = self.frameGeometry()
        r.moveCenter(geo.center())
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(scr.left(), min(r.left(), scr.right() - r.width()))
        y = max(scr.top(), min(r.top(), scr.bottom() - r.height()))
        self.move(x, y)

    def _focusables(self, root: QWidget) -> list[QWidget]:
        out = []
        for w in root.findChildren(QWidget):
            if not w.isVisibleTo(self) or not w.isEnabled():
                continue
            if w.focusPolicy() & Qt.FocusPolicy.TabFocus and w not in self._buttons.values() and w.focusProxy() is None:
                if w.objectName().startswith('qt_'):                 # a scroll area's internals
                    continue
                out.append(w)
        return out

    def _order_focus(self) -> None:
        body = sorted(self._focusables(self), key=lambda w: (round(w.mapTo(self, QPoint(0, 0)).y() / 8), w.mapTo(self, QPoint(0, 0)).x()))
        btns = [b for b in self._buttons.values() if b.isVisibleTo(self)]
        # buttons are right-aligned in creation order = left to right = tab order, so only the body needs sorting
        chain = [w for w in body if w not in btns] + btns
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)
        target = self.initial_focus
        if target is None:
            default = next((b for b in btns if b.isDefault()), None)
            first_body = next((x for x in chain if x not in btns), None)
            target = first_body or default or (chain[0] if chain else None)
        if target is not None:
            target.setFocus()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            fw = self.focusWidget()
            if isinstance(fw, QPushButton) and fw in self._buttons.values():
                fw.click()
                return
            default = next((b for b in self._buttons.values() if b.isDefault() and b.isEnabled()), None)
            if default is not None and not isinstance(fw, (QPushButton,)) and getattr(fw, 'acceptRichText', None) is None:
                default.click()
                return
        super().keyPressEvent(ev)


class MessageDialog(ModalDialog):
    """A message with an icon colour: kind 'info' | 'warning' | 'error' | 'question'.  `buttons` = [(text, key, role)], the first with role 'primary' is default."""

    def __init__(self, parent: QWidget | None, kind: str, title: str, text: str, *, buttons: Sequence[tuple] = (('OK', 'ok', 'primary'),),
                 cancel_key: str | None = None, detail: str = ''):
        super().__init__(parent, title)
        self.title_label.hide()
        banner_kind = {'info': 'info', 'warning': 'warn', 'error': 'error', 'question': 'info'}.get(kind, 'info')
        head = QHBoxLayout()
        head.setSpacing(M.md)
        icon = QLabel()
        icon.setFixedSize(28, 28)
        col = {'info': 'info', 'warn': 'warn', 'error': 'bad'}[banner_kind]
        follow_theme(icon, lambda: icon.setPixmap(theme.pixmap({'info': 'info', 'warn': 'warn', 'error': 'error'}[banner_kind], theme.tokens()[col], 28)))
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        col_l = QVBoxLayout()
        col_l.setSpacing(M.xs)
        col_l.addWidget(label(title, 'h2', wrap=True))
        body = label(text, wrap=True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col_l.addWidget(body)
        col_l.addStretch(1)
        head.addLayout(col_l, 1)
        self.body.addLayout(head)
        self.detail_edit = None
        if detail:
            from PySide6.QtWidgets import QPlainTextEdit
            self.detail_edit = QPlainTextEdit(detail)
            self.detail_edit.setReadOnly(True)
            self.detail_edit.setMinimumHeight(140)
            self.detail_edit.setProperty('mono', True)
            self.detail_edit.setStyleSheet(f"font-family: '{theme.mono_family()}'; font-size: {M.font_mono}px;")
            self.body.addWidget(self.detail_edit)
            self.setMinimumWidth(560)
        for text_, key, role in buttons:
            self.add_button(text_, role=role, result=key, default=role in ('primary', 'danger'), cancel=(key == cancel_key))
        if cancel_key is None and len(buttons) == 1:
            self._cancel_key = buttons[0][1]
        self.initial_focus = next((b for b in self._buttons.values() if b.isDefault()), None)       # a message: Enter / Space answers it, not the detail box


class ProgressDialog(ModalDialog):
    """A progress window: bar + message (+ detail line) and an optional Cancel.  Meant to be updated from the UI thread (from a worker use
    qtui.app.post(dlg.set_progress, ...)).  Cancel only sets `was_cancelled` and emits `cancelled`: the owner stops its work and calls finish()."""
    cancelled = Signal()

    def __init__(self, parent: QWidget | None, title: str, message: str = '', *, maximum: int = 0, cancelable: bool = True, modal: bool = True):
        super().__init__(parent, title, width=420, modal=modal, close_button=False)
        self.was_cancelled = False
        self.message_label = label(message, wrap=True)
        self.body.addWidget(self.message_label)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.body.addWidget(self.bar)
        self.detail_label = label('', 'hint', wrap=True)
        self.detail_label.setVisible(False)
        self.body.addWidget(self.detail_label)
        self.set_maximum(maximum)
        if cancelable:
            self.add_button('Cancel', cancel=True, close=False, callback=self._cancel_clicked)

    def _cancel_clicked(self):
        self.was_cancelled = True
        self.button('cancel').setEnabled(False)
        self.button('cancel').setText('Cancelling...')
        self.cancelled.emit()

    def reject(self):
        if self._cancel_key:
            self._cancel_clicked()          # Esc cancels the work, it does not close a running dialog
        else:
            return

    def set_maximum(self, maximum: int) -> None:
        """0 = indeterminate (a moving bar)."""
        self.bar.setRange(0, maximum if maximum > 0 else 0)

    def set_progress(self, value: int, maximum: int | None = None, message: str | None = None, detail: str | None = None) -> None:
        if maximum is not None:
            self.set_maximum(maximum)
        if self.bar.maximum() > 0:
            self.bar.setValue(max(0, min(int(value), self.bar.maximum())))
        if message is not None:
            self.message_label.setText(message)
        if detail is not None:
            self.detail_label.setText(detail)
            self.detail_label.setVisible(bool(detail))

    def finish(self) -> None:
        """Close the dialog from the owner (success or after a cancel)."""
        self.result_key = 'cancel' if self.was_cancelled else 'done'
        QDialog.accept(self)
