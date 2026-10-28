"""The Qt test-window shell ("Mission Control" layout): the twin of ui_shell.Shell, used by every engine window (the *_view_qt.py files).

    +---------------------------------------------------------------------------------------+
    | title / subtitle                              [DEMO] [Connected]        [Connections] |   header (chips: add_chip / set_modified / set_verified / set_devmode)
    | Instrument ID [      ] Serial [      ]  Collecting [As Found|As Left]   x of y  ====   |   strip
    +----------+----------------------------------------------------------------------------+
    | Sections |  content: filter row + results table (full width) + detail text            |   body
    | * Volts  |                                                         +-----------------+|
    | * Ohms   |                                                         | Connections &   ||   drawer (slides over the content; Esc closes it)
    +----------+--------------------------------------------------------------------- ------+
    | [Run All Pending] [Run Shown Section] [Rerun] [Stop]            [Save][Load][Export]  |   action bar
    | status message                                                              v70 Beta 2|   status bar (+ an optional log pane, `shell.log`)
    +---------------------------------------------------------------------------------------+

Same constructor and attributes as ui_shell.Shell, so a view ports by swapping the shell and keeping its layout code:

    sh = self.shell = Shell(root, title, subtitle, demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var                       # a QtVar (ui_port.var): .set(text) from the UI thread; the dot colour follows the wording
    sh.add_chip(text, kind) / sh.build_identity(asset_var, serial_var) / sh.build_progress() -> ProgressPanel / sh.notice(text, kind, title)
    sh.strip          QWidget (QHBoxLayout): the row under the header; parent for the mode segment and the identity fields
    sh.notice_holder  QWidget (QVBoxLayout): notices under the strip
    sh.drawer_body    QWidget (QGridLayout, column 1 stretches): the connection / settings form; sh.drawer_footer QWidget (QHBoxLayout) pinned under it
    sh.content        QWidget (QVBoxLayout): the table area
    sh.add_action(text, command, accent=False, danger=False, side='left'|'right', short=None, state=None) -> button (with Tk-style configure(state=...))
    sh.set_sections([(name, passed, failed, total), ...]) / sh.choose_section(name) / sh.build_section_picker(parent) / sh.layout_hook(compact)
    sh.set_verified(text) / set_modified(n) / set_devmode(on) / open_drawer() / close_drawer() / sh.compact
Additions for the Qt build: sh.add_menu(title) -> QMenu (menu bar of the main window), sh.log_line(text) / sh.show_log(on) (a collapsible log pane under the action bar),
The action buttons are QPushButtons with Tk-style configure(state=...) / cget (or use setEnabled()).

Below ~1100 px wide the sidebar folds into a Section drop-down and the action buttons use their short texts, so the window still works at 900 x 700.
Nothing here talks to an instrument.  `results_table` / `small_window` (bottom of this file) are the twins of ui_shell's.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import shell_helpers as H
from . import theme
from . import widgets as W
from .theme import M
from .vars import QtVar, bind

COMPACT_BELOW = 1180            # window width (logical px) under which the sidebar folds into a drop-down (Tk: 1100; the Qt full table needs ~1170 for a readable Description)
SIDEBAR_W = 224
DRAWER_MAX, DRAWER_MIN = 480, 300


class ProgressPanel(QWidget):
    """Progress ring + headline + badges.  update_counts() as ui.Summary, plus set_rerun() for As Left runs:

        As Found:  (81/135 tested)   81 of 135 tested     [58 pass] [23 fail] [54 remaining]
        As Left:   (  1/1  re-run)   1 of 1 re-run done   [1 now in limits] [0 still out]
    """
    SIZE = 68

    def __init__(self, parent=None):
        super().__init__(parent)
        self._done, self._total, self._big, self._small, self._color = 0, 1, '0/0', 'tested', 'primary'
        self.ring = _Ring(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(M.md)
        row.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addStretch(1)
        self.text = QtVar('Nothing tested yet')
        self._headline = W.label('Nothing tested yet', 'section')
        bind(self._headline, self.text)
        col.addWidget(self._headline)
        self.badges = QWidget()
        bl = QHBoxLayout(self.badges)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.ok, self.fail, self.rem = H.Pill(None, '0 pass'), H.Pill(None, '0 fail'), H.Pill(None, '0 remaining')
        for p in (self.ok, self.fail, self.rem):
            bl.addWidget(p)
        col.addWidget(self.badges)
        col.addStretch(1)
        row.addLayout(col)
        self._draw(0, 1, '0/0', 'tested', 'primary')

    def _draw(self, done, total, big, small, color):
        self.ring.set(done, total, big, small, color)

    def update_counts(self, total, passed, failed):
        done = passed + failed
        left = total - done
        self.text.set(f'{done} of {total} tested')
        self.ok.set(f'{passed} pass', 'good' if passed else 'neutral')
        self.fail.set(f'{failed} fail', 'bad' if failed else 'neutral')
        self.rem.set('All points tested' if left == 0 and total else f'{left} remaining', 'good' if left == 0 and total and not failed else 'neutral')
        self._draw(done, total, f'{done}/{total}', 'tested', 'bad' if failed and not left else 'primary')

    def set_rerun(self, total, done, in_limits, still_out):
        """As Left: the points to re-measure are the ones that failed As Found."""
        self.text.set(f'{done} of {total} re-run done' if total else 'Nothing failed As Found: nothing to re-run')
        self.ok.set(f'{in_limits} now in limits', 'good' if in_limits else 'neutral')
        self.fail.set(f'{still_out} still out', 'bad' if still_out else 'neutral')
        self.rem.set(f'{total - done} to re-run' if total - done else 'All re-run', 'neutral' if total - done else 'good')
        self._draw(done, total, f'{done}/{total}', 're-run', 'warn')


class _Ring(QWidget):
    """The progress ring, painted from the live tokens."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(ProgressPanel.SIZE, ProgressPanel.SIZE)
        self.state = (0, 1, '0/0', 'tested', 'primary')
        theme.manager().changed.connect(self._on_theme)

    def _on_theme(self, *_):
        self.update()

    def set(self, done, total, big, small, color):
        self.state = (done, total, big, small, color)
        self.update()

    def paintEvent(self, ev):
        done, total, big, small, color = self.state
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 6
        box = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        pen = QPen(QColor(t['border_strong']), w)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(box)
        frac = (done / total) if total else 0
        pen = QPen(QColor(t[color]), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap if frac < 0.999 else Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        if frac >= 0.999:
            p.drawEllipse(box)
        elif frac > 0:
            p.drawArc(box, 90 * 16, int(-360 * 16 * frac))
        p.setPen(QColor(t['text']))
        f = p.font()
        f.setBold(True)
        f.setPixelSize(M.font_base + 1)
        inner = self.width() - 4 * w                             # the text must fit inside the ring ('105/105' is wider than '9/9'): shrink it until it does
        while f.pixelSize() > 8 and QFontMetrics(f).horizontalAdvance(big) > inner:
            f.setPixelSize(f.pixelSize() - 1)
        p.setFont(f)
        while f.pixelSize() > 8 and p.fontMetrics().horizontalAdvance(big) > self.width() - 2 * w - 6:          # '496/496' must stay inside the ring
            f.setPixelSize(f.pixelSize() - 1)
            p.setFont(f)
        p.drawText(QRectF(0, 0, self.width(), self.height() / 2 + 6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, big)
        p.setPen(QColor(t['muted']))
        f.setBold(False)
        f.setPixelSize(M.font_tiny - 1)
        p.setFont(f)
        p.drawText(QRectF(0, self.height() / 2 + 6, self.width(), self.height() / 2 - 6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, small)


class _SectionRow(QFrame):
    """One sidebar row: status dot, name (elided), done / total.  Click, Enter or Space chooses it."""

    def __init__(self, name: str, ok: int, bad: int, tot: int, selected: bool, on_choose: Callable[[str], None]):
        super().__init__()
        self.name, self.ok, self.bad, self.tot, self.selected, self._on = name, ok, bad, tot, selected, on_choose
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(34)
        self.setAccessibleName(f'{name}, {ok + bad} of {tot} tested')
        self.setToolTip(name)                              # the full name when it is elided in the sidebar
        self._hover = False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._on(self.name)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._on(self.name)
        else:
            super().keyPressEvent(ev)

    def enterEvent(self, ev):
        self._hover = True
        self.update()

    def leaveEvent(self, ev):
        self._hover = False
        self.update()

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.update()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.update()

    def paintEvent(self, ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self.selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t['select']))
            p.drawRoundedRect(r, M.radius, M.radius)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t['btn_hi']))
            p.drawRoundedRect(r, M.radius, M.radius)
        if self.hasFocus():
            p.setPen(QPen(QColor(t['focus']), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), M.radius, M.radius)
        dot = t['bad_dot'] if self.bad else (t['good_dot'] if self.tot and self.ok == self.tot else (t['info_dot'] if self.ok else t['neutral_dot']))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(18, self.height() / 2), 4.5, 4.5)
        count = f'{self.ok + self.bad}/{self.tot}'
        fm = p.fontMetrics()
        cw = fm.horizontalAdvance(count)
        p.setPen(QColor(t['bad'] if self.bad else t['faint']))
        p.drawText(QRectF(self.width() - cw - 12, 0, cw, self.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count)
        p.setPen(QColor(t['text'] if self.selected else t['muted']))
        room = self.width() - 34 - cw - 22
        p.drawText(QRectF(32, 0, room, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fm.elidedText(self.name, Qt.TextElideMode.ElideRight, int(room)))


class _ShellWidget(QWidget):
    """The shell's root widget: reports its width changes (compact layout) and keeps the drawer glued to the right edge."""

    def __init__(self, shell: 'Shell'):
        super().__init__()
        self.setObjectName('root')
        self.shell = shell

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.shell._on_resize()


class Shell:
    def __init__(self, root, title, subtitle='', demo=False, on_section=None, version='', virtual=False):
        self.root = root
        self.demo = demo
        self.on_section = on_section
        self.sections = []                 # [(name, passed, failed, total)]
        self._action_texts = []
        self.current = 'All sections'
        self._compact = None
        self._rows = {}
        self._drawer_open = False
        self.section_picker = None
        self.layout_hook = None            # called with True/False when the window crosses the small-window width
        self.summary = None
        self.widget = _ShellWidget(self)
        outer = QVBoxLayout(self.widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header -------------------------------------------------------------------------------------
        self.header = QFrame()
        self.header.setProperty('surface', 'bar')
        hrow = QHBoxLayout(self.header)
        hrow.setContentsMargins(M.xl - 4, M.md, M.xl - 4, M.md - 2)
        hrow.setSpacing(M.md)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title_label = W.label(title, 'title', wrap=True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)      # a long title may never force the window wider
        self.subtitle = QtVar(subtitle)
        self._sub = W.label(subtitle, 'sub', wrap=True)
        self._sub.setTextFormat(Qt.TextFormat.PlainText)
        bind(self._sub, self.subtitle)
        left.addWidget(self.title_label)
        left.addWidget(self._sub)
        hrow.addLayout(left, 1)
        right = QHBoxLayout()
        right.setSpacing(M.sm)
        self.chip_frame = QWidget()
        self._chips = QHBoxLayout(self.chip_frame)
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(M.sm)
        right.addWidget(self.chip_frame)
        self.btn_drawer = H.button(None, '⚙  Connections', self.toggle_drawer)
        self.btn_drawer.setToolTip('Connections and settings (Esc closes)')
        right.addWidget(self.btn_drawer)
        hrow.addLayout(right, 0)
        hrow.setAlignment(right, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self.header)
        outer.addWidget(W.rule())
        self.mode_chip = (self.add_chip('DEMO MODE  -  virtual instruments' if virtual else 'DEMO MODE  -  simulated readings', 'warn') if demo
                          else self.add_chip('HARDWARE MODE', 'info'))

        # ---- strip (ID, serial, As Found / As Left, progress) -----------------------------------------------
        self.strip_holder = QWidget()
        sh = QVBoxLayout(self.strip_holder)
        sh.setContentsMargins(M.xl - 4, M.sm, M.xl - 4, M.xs)
        sh.setSpacing(0)
        self.strip = QWidget()
        self.strip_layout = QHBoxLayout(self.strip)
        self.strip_layout.setContentsMargins(0, 0, 0, 0)
        self.strip_layout.setSpacing(M.md)
        sh.addWidget(self.strip)
        self.notice_holder = QWidget()                     # As Left / demo / hardware notices
        self.notice_layout = QVBoxLayout(self.notice_holder)
        self.notice_layout.setContentsMargins(0, 0, 0, 0)
        self.notice_layout.setSpacing(6)
        sh.addWidget(self.notice_holder)
        outer.addWidget(self.strip_holder)

        # ---- body: sidebar | content (the drawer floats over it) ------------------------------------------------
        self.body = QWidget()
        brow = QHBoxLayout(self.body)
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(SIDEBAR_W)
        sbl = QVBoxLayout(self.sidebar)
        sbl.setContentsMargins(0, 0, 0, 0)
        sbl.setSpacing(0)
        self._side_title = W.label('SECTIONS', 'hint')
        self._side_title.setContentsMargins(M.lg, M.md + 2, M.lg, M.sm)
        sbl.addWidget(self._side_title)
        self._side_scroll = QScrollArea()
        self._side_scroll.setWidgetResizable(True)
        self._side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._side_list = QWidget()
        self._side_layout = QVBoxLayout(self._side_list)
        self._side_layout.setContentsMargins(M.sm, 0, M.sm, M.sm)
        self._side_layout.setSpacing(1)
        self._side_layout.addStretch(1)
        self._side_scroll.setWidget(self._side_list)
        self._side_scroll.viewport().setAutoFillBackground(False)
        self._side_list.setAutoFillBackground(False)
        sbl.addWidget(self._side_scroll, 1)
        brow.addWidget(self.sidebar)
        self._side_sep = W.rule(vertical=True)
        brow.addWidget(self._side_sep)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(M.lg, M.sm, M.lg, M.sm)
        self.content_layout.setSpacing(0)
        brow.addWidget(self.content, 1)
        outer.addWidget(self.body, 1)

        # ---- action bar, log pane, status bar -----------------------------------------------------------------
        outer.addWidget(W.rule())
        self.actions = QWidget()
        arow = QHBoxLayout(self.actions)
        arow.setContentsMargins(M.xl - 4, 7, M.xl - 4, 7)
        arow.setSpacing(M.sm)
        self.actions_left = QWidget()
        self._al = QHBoxLayout(self.actions_left)
        self._al.setContentsMargins(0, 0, 0, 0)
        self._al.setSpacing(M.sm)
        self.actions_right = QWidget()
        self._ar = QHBoxLayout(self.actions_right)
        self._ar.setContentsMargins(0, 0, 0, 0)
        self._ar.setSpacing(M.sm)
        self.actions_left.setMinimumWidth(1)               # the bar never holds the window wide: the small-window layout (short texts) is chosen by _apply_layout
        self.actions_right.setMinimumWidth(1)
        self._bar_need = 0                                  # the width the bar needs with the full texts (measured while they are shown)
        arow.addWidget(self.actions_left)
        arow.addStretch(1)
        arow.addWidget(self.actions_right)
        outer.addWidget(self.actions)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty('mono', True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFixedHeight(130)
        self.log.setVisible(False)
        outer.addWidget(self.log)
        self.status_var = QtVar('')
        self.statusbar = H.StatusBar(None, self.status_var, right=version)
        self.btn_log = H.button(None, 'Log', lambda: self.show_log(not self.log.isVisible()))
        self.btn_log.setProperty('role', 'ghost')
        self.btn_log.setVisible(False)
        self.statusbar._buttons.addWidget(self.btn_log)
        outer.addWidget(self.statusbar)

        # ---- drawer ---------------------------------------------------------------------------------------------
        self.drawer = QFrame(self.body)
        self.drawer.setProperty('surface', 'popover')
        self.drawer.hide()
        dl = QVBoxLayout(self.drawer)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(M.lg, M.md, M.lg, M.sm)
        top.addWidget(W.label('Connections & settings', 'h2'), 1)
        self.btn_drawer_close = H.button(None, 'Close', self.close_drawer)
        self.btn_drawer_close.setProperty('role', 'ghost')
        top.addWidget(self.btn_drawer_close)
        dl.addLayout(top)
        dl.addWidget(W.rule())
        self._dscroll = QScrollArea()
        self._dscroll.setWidgetResizable(True)
        self._dscroll.setFrameShape(QFrame.Shape.NoFrame)
        self._dscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)      # a long unwrappable check box text scrolls instead of clipping
        self.drawer_body = QWidget()                       # the connection widgets go in here; it scrolls if the window is short
        self.drawer_layout = QGridLayout(self.drawer_body)
        self.drawer_layout.setContentsMargins(M.lg, M.sm + 2, M.lg, M.sm + 2)
        self.drawer_layout.setHorizontalSpacing(M.md)
        self.drawer_layout.setVerticalSpacing(M.sm)
        self.drawer_layout.setColumnStretch(1, 1)
        self.drawer_layout.setRowStretch(99, 1)
        self._dscroll.setWidget(self.drawer_body)
        self._dscroll.viewport().setAutoFillBackground(False)
        dl.addWidget(self._dscroll, 1)
        dl.addWidget(W.rule())
        self.drawer_footer = QWidget()                     # pinned: Test connections stays in reach however long the form is
        self.drawer_footer_layout = QHBoxLayout(self.drawer_footer)
        self.drawer_footer_layout.setContentsMargins(M.lg, M.sm + 2, M.lg, M.sm + 2)
        self.drawer_footer_layout.setSpacing(M.sm)
        self.drawer_footer_layout.addStretch(1)
        dl.addWidget(self.drawer_footer)
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.widget)
        self._esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._esc.activated.connect(self.close_drawer)
        self._install(root)
        QTimer.singleShot(0, self._apply_layout)

    # ------------------------------------------------------------------ hosting
    def _install(self, root) -> None:
        if isinstance(root, QMainWindow):
            root.setCentralWidget(self.widget)
        elif isinstance(root, QWidget):
            lay = root.layout()
            if lay is None:
                lay = QVBoxLayout(root)
                lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.widget)

    def add_menu(self, title: str):
        """A menu in the main window's menu bar (File / Edit ...).  Returns the QMenu."""
        if isinstance(self.root, QMainWindow):
            return self.root.menuBar().addMenu(title)
        raise RuntimeError('the shell was not given a QMainWindow')

    # ------------------------------------------------------------------ header / strip
    def add_chip(self, text, kind='neutral'):
        pill = H.Pill(None, text, kind)
        self._chips.addWidget(pill)
        return pill

    def _named_chip(self, attr, text, kind):
        chip = getattr(self, attr, None)
        if not text:
            if chip is not None:
                chip.setVisible(False)
            return chip
        if chip is None:
            chip = H.Pill(None, text, kind)
            setattr(self, attr, chip)
            self._chips.addWidget(chip)
        chip.set(text, kind)
        chip.setVisible(True)
        return chip

    def set_modified(self, count):
        """Amber 'MODIFIED (n)' chip in the header while procedure modifications are in effect (nothing when there are none)."""
        return self._named_chip('modified_chip', f'MODIFIED ({int(count)})' if count else '', 'warn')

    def set_verified(self, text):
        """Green chip (e.g. 'VERIFIED ON HARDWARE - LOCKED') while the procedure is verified and locked (verified.py); '' removes it."""
        return self._named_chip('verified_chip', text, 'good')

    def set_devmode(self, on):
        """Amber 'DEVELOPER MODE' chip while the developer-mode session is unlocked."""
        return self._named_chip('devmode_chip', 'DEVELOPER MODE' if on else '', 'warn')

    def build_identity(self, asset_var, serial_var, focus=True):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(M.sm)
        row.addWidget(W.label('Instrument ID *'))
        self.id_entry = H.entry(None, asset_var, width=16)
        self.id_entry.setFixedWidth(130)
        self.id_entry.setAccessibleName('Instrument ID')
        row.addWidget(self.id_entry)
        row.addSpacing(M.sm)
        row.addWidget(W.label('Serial'))
        self.serial_entry = H.entry(None, serial_var, width=14)
        self.serial_entry.setFixedWidth(120)
        self.serial_entry.setAccessibleName('Serial')
        row.addWidget(self.serial_entry)
        self.strip_layout.insertWidget(0, box)
        if focus:
            QTimer.singleShot(0, self.id_entry.setFocus)
        return box

    def build_progress(self):
        self.summary = ProgressPanel()
        self.strip_layout.addStretch(1)
        self.strip_layout.addWidget(self.summary)
        return self.summary

    def notice(self, text, kind='info', title=None):
        n = H.Notice(None, text, kind, title=title)
        self.notice_layout.addWidget(n)
        return n

    # ------------------------------------------------------------------ action bar
    ACTION_ICONS = {'Save progress': 'save', 'Load progress': 'load', 'Export Report (PDF)': 'export', 'Rerun Selected': 'rerun', 'Rerun From Selected': 'rerun_from', 'Edit point': 'edit',
                    'Run Shown Section': 'play'}                    # the buttons whose text carries no glyph of its own get a drawn icon (text unchanged)

    def add_action(self, text, command, accent=False, danger=False, side='left', short=None, state=None, **kw):
        b = H.Button(text)
        glyph = self.ACTION_ICONS.get(text)
        if glyph:
            W.follow_theme(b, lambda b=b, g=glyph, hot=accent: self._set_action_icon(b, g, 'on_primary' if hot else 'text'))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setAutoDefault(False)
        if danger:
            b.setProperty('role', 'danger')
        elif accent:
            b.setProperty('role', 'primary')
        if command is not None:
            b.clicked.connect(lambda _c=False: command())
        (self._ar if side == 'right' else self._al).addWidget(b)
        self._action_texts.append((b, text, short or text))
        if self._compact:
            b.setText(short or text)
        if state:
            b.configure(state=state)
        return b

    @staticmethod
    def _set_action_icon(b, glyph, token):
        t = theme.tokens()
        ic = QIcon()
        ic.addPixmap(theme.pixmap(glyph, t[token], 16), QIcon.Mode.Normal)
        ic.addPixmap(theme.pixmap(glyph, t['disabled_fg'], 16), QIcon.Mode.Disabled)
        b.setIcon(ic)
        b.setIconSize(QSize(16, 16))

    # ------------------------------------------------------------------ sections (sidebar / drop-down)
    def set_sections(self, rows):
        """rows: [(name, passed, failed, total)] for the real sections; 'All sections' is added on top."""
        self.sections = list(rows)
        names = ['All sections'] + [r[0] for r in rows]
        if self.current not in names:                      # the section went away (options changed): fall back to all, and tell the procedure
            self.current = 'All sections'
            if self.on_section:
                QTimer.singleShot(0, lambda: self.on_section('All sections'))
        total, passed, failed = sum(r[3] for r in rows), sum(r[1] for r in rows), sum(r[2] for r in rows)
        entries = [('All sections', passed, failed, total)] + list(rows)
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows = {}
        for i, (name, ok, bad, tot) in enumerate(entries):
            row = _SectionRow(name, ok, bad, tot, name == self.current, self.choose_section)
            self._side_layout.insertWidget(i, row)
            self._rows[name] = row
        if self.section_picker is not None:
            self.section_picker.blockSignals(True)
            self.section_picker.clear()
            self.section_picker.addItems(names)
            self.section_picker.setCurrentText(self.current)
            self.section_picker.blockSignals(False)

    def choose_section(self, name, notify=True):
        self.current = name
        self.set_sections(self.sections)
        if notify and self.on_section:
            self.on_section(name)

    def build_section_picker(self, parent):
        """The drop-down that stands in for the sidebar in a small window.  It is added to `parent`'s layout (hidden until the window is small)."""
        self.section_picker = H.Combobox()
        self.section_picker.addItems(['All sections'] + [r[0] for r in self.sections])
        self.section_picker.setCurrentText(self.current)
        self.section_picker.setMinimumWidth(170)
        self.section_picker.setAccessibleName('Section')
        self.section_picker.activated.connect(lambda _i: self.choose_section(self.section_picker.currentText()))
        lay = parent.layout()
        if lay is not None:
            lay.addWidget(self.section_picker)
        self.section_picker.setVisible(bool(self._compact))
        return self.section_picker

    # ------------------------------------------------------------------ log pane
    def log_line(self, text: str) -> None:
        """Append a line to the log pane (UI thread).  The pane stays hidden until the operator opens it with the 'Log' button."""
        self.log.appendPlainText(str(text))
        self.btn_log.setVisible(True)

    def show_log(self, on: bool = True) -> None:
        self.log.setVisible(bool(on))
        self.btn_log.setVisible(True)

    # ------------------------------------------------------------------ drawer
    def toggle_drawer(self):
        self.close_drawer() if self._drawer_open else self.open_drawer()

    def _place_drawer(self):
        avail = max(DRAWER_MIN, self.body.width() - 40)
        try:                                   # a form wider than the usual drawer (the 6060A's five address boxes, long port lists) widens it instead of scrolling sideways
            need = self.drawer_body.minimumSizeHint().width() + 28          # + the vertical scroll bar
        except Exception:
            need = 0
        width = min(avail, max(DRAWER_MAX, need))
        self.drawer.setGeometry(self.body.width() - width, 0, width, self.body.height())

    def open_drawer(self):
        self._place_drawer()
        self.drawer.show()
        self.drawer.raise_()
        self._drawer_open = True
        for w in self.drawer_body.findChildren(QWidget):
            if w.focusPolicy() & Qt.FocusPolicy.TabFocus and w.isVisibleTo(self.drawer_body):
                w.setFocus()
                break

    def close_drawer(self):
        if self._drawer_open:
            self.drawer.hide()
            self._drawer_open = False
            self.btn_drawer.setFocus()

    # ------------------------------------------------------------------ small window
    def _on_resize(self):
        QTimer.singleShot(0, self._after_resize)

    def _after_resize(self):
        if self._drawer_open:
            self._place_drawer()
        self._apply_layout()

    @property
    def compact(self):
        return bool(self._compact)

    def _apply_layout(self):
        width = self.widget.width()
        if width <= 1:
            return
        if not self._compact:
            self._bar_need = self.actions.sizeHint().width()           # full texts: what the action bar needs (more buttons, wider bar)
        compact = width < max(COMPACT_BELOW, self._bar_need)
        if compact == self._compact:
            return
        self._compact = compact
        self.sidebar.setVisible(not compact)
        self._side_sep.setVisible(not compact)
        for b, full, short in self._action_texts:           # shorter button texts in a small window
            b.setText(short if compact else full)
        if self.summary is not None:                        # the pass / fail / remaining badges give way to the bar
            self.summary.badges.setVisible(not compact)
        if self.section_picker is not None:
            self.section_picker.setVisible(compact)
        if self.layout_hook:
            self.layout_hook(compact)


# ---------------------------------------------------------------------------------------------- results table
FULL_COLUMNS = ('n', 'description', 'nominal', 'low', 'high', 'found', 'error', 'left', 'result')
SMALL_COLUMNS = ('n', 'description', 'nominal', 'limits', 'found', 'left', 'result')


def results_table(app, parent, name_width=300, nominal_title='Nominal', error=True):
    """The full-width results table shared by the procedures (twin of ui_shell.results_table).  Row cells come from DataModeMixin.shell_cells(); the first cell is the
    point number and the second the description:   values = (id, description, *app.shell_cells(...)), tags = (result,)
    Added to `parent`'s layout (add the detail text under it AFTER this call: a Tk side='bottom' frame is simply added after the table).  Wires the small-window layout
    (merged Limits column) and the 'As Found / As Left' headings.  Returns the ResultsTree."""
    cols = ('n', 'description', 'nominal', 'low', 'high', 'limits', 'found', 'error', 'left', 'result')
    heads = ('#', 'Description', nominal_title, 'Low limit', 'High limit', 'Limits', 'As Found', 'Error', 'As Left', 'Result')
    tree = H.make_table(parent, cols, heads, (44, name_width, 96, 92, 92, 170, 100, 90, 100, 90), height=12,
                        anchors={'description': 'w', 'nominal': 'e', 'low': 'e', 'high': 'e', 'limits': 'e', 'found': 'e', 'error': 'e', 'left': 'e'},
                        stretch={c: False for c in cols if c != 'description'}, mono=('nominal', 'low', 'high', 'limits', 'found', 'error', 'left'))
    tree._cols_full = FULL_COLUMNS if error else tuple(c for c in FULL_COLUMNS if c != 'error')
    tree._cols_small = SMALL_COLUMNS
    tree.configure(displaycolumns=tree._cols_full)
    tree._shell_name_width = name_width
    _result_tones(tree)

    def relabel():
        tree.heading('found', text='As Found' if app.is_left else '● As Found')
        tree.heading('left', text='● As Left' if app.is_left else 'As Left')
    app._relabel_reading_column = relabel
    relabel()
    bind_menu = getattr(app, 'pm_bind_tree', None)         # procedures with procedure modifications: right-click a point > Edit
    if bind_menu is not None:
        bind_menu(tree)
    return tree


def _result_tones(tree) -> None:
    """The result column's text takes the pass / fail colour (the row tint comes from the tags)."""
    i = tree._keys.index('result')
    col = tree.source_model.columns[i]
    col.tone = lambda r: 'good' if 'pass' in r.tags else ('bad' if 'fail' in r.tags else ('warn' if 'error' in r.tags else ('muted' if 'pending' in r.tags else None)))
    col.bold = True


def small_window(app, tree, filter_bar, picker=None, extra=None):
    """Hook the small-window behaviour: merged Limits column, section drop-down in filter_bar, then extra(compact) if given."""
    picker = picker or app.shell.build_section_picker(filter_bar)

    def layout(compact):
        tree.configure(displaycolumns=tree._cols_small if compact else tree._cols_full)
        tree.column('description', width=200 if compact else tree._shell_name_width)
        tree.column('limits', width=160)
        for col in ('found', 'left'):
            tree.column(col, width=100 if compact else 110)
        picker.setVisible(compact)
        if extra:
            extra(compact)
    app.shell.layout_hook = layout
    if app.shell._compact is not None:                      # the window was already measured: apply now
        layout(app.shell._compact)
    return picker
