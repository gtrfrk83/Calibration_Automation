"""The dialogs behind QtUiPort (ui_port_qt.py): the Qt versions of what the Tk build shows with messagebox / simpledialog / filedialog / ui_theme.confirm_steps.

Every function here runs on the UI thread, blocks in a modal event loop and returns what the Tk call returned.  Texts and button names are the engines' own and are
never altered.  All labels are PLAIN text (an engine text may contain '<' e.g. 'USB0::<mfgID>::INSTR', which must not be taken for HTML).

    message(parent, kind, title, text)
    question(parent, kind, title, text, buttons, default=None, cancel=None, icon=None) -> key of the pressed button
    ask_text(parent, title, prompt, initial=None, show=None) -> str | None
    ask_number(parent, title, prompt, initial=None, minvalue=None, maxvalue=None, integer=False) -> float | int | None
    ask_value(parent, title, prompt, default) -> str | None
    operator_prompt(parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, layout=None, card=None) -> bool
    open_file / save_file / choose_dir(parent, **tk_options) -> str
"""
from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget)

import ui_theme_core as core
from . import theme
from .theme import M
from .widgets import Banner, MessageDialog, ModalDialog, label

FN_WIDTH = 540                      # content width of the function-change window (the Tk FN_WIDTH, 96-dpi units; Qt px are device independent)
STEP_WRAP = 480


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def plain(lab: QLabel) -> QLabel:
    lab.setTextFormat(Qt.TextFormat.PlainText)
    return lab


def plain_label(text: str = '', role: str | None = None, *, wrap: bool = True) -> QLabel:
    return plain(label(text, role, wrap=wrap))


def _plain_all(dlg: QWidget) -> None:
    for lab in dlg.findChildren(QLabel):
        lab.setTextFormat(Qt.TextFormat.PlainText)


def fit_dialog(dlg: QWidget, width: int | None = None) -> None:
    """Give a dialog with word-wrapped labels the height its text needs at its width (adjustSize alone sizes it for the unwrapped text and clips the last lines)."""
    w = width or dlg.minimumWidth()
    lay = dlg.layout()
    lay.activate()
    h = lay.totalHeightForWidth(w)
    if h > 0:
        dlg.setMinimumHeight(h)
        dlg.resize(w, h)


def resolve_parent(parent) -> QWidget | None:
    """`parent` is the host's window object: a QWidget, or anything with a QWidget in `.root` / `.widget` / `.window`; None / unknown -> the active window."""
    for cand in (parent, getattr(parent, 'root', None), getattr(parent, 'widget', None)):
        if isinstance(cand, QWidget):
            return cand
    return QApplication.activeWindow()


def _title(title: str) -> str:
    return (title or '') + core.DEMO_SUFFIX


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# messages and questions (tkinter.messagebox)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def message(parent, kind: str, title: str, text: str) -> None:
    dlg = MessageDialog(resolve_parent(parent), kind, title, text, buttons=(('OK', 'ok', 'primary'),), cancel_key='ok')
    _plain_all(dlg)
    fit_dialog(dlg)
    dlg.run()


def question(parent, icon_kind: str, title: str, text: str, buttons: Sequence[tuple[str, str]], *, default: str, cancel: str) -> str:
    """buttons = [(text, key)].  `default` = the key preselected (Enter), `cancel` = the key Esc and the window's close button give.  Returns the key pressed."""
    spec = tuple((t, k, 'primary' if k == default else None) for t, k in buttons)
    dlg = MessageDialog(resolve_parent(parent), icon_kind, title, text, buttons=spec, cancel_key=cancel)
    _plain_all(dlg)
    fit_dialog(dlg)
    key = dlg.run()
    return key if key is not None else cancel


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# simpledialog
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def _entry_dialog(parent, title: str, prompt: str, initial, secret: bool, ok_text='OK', width: int | None = None, check=None) -> str | None:
    dlg = ModalDialog(resolve_parent(parent), title, width=width)
    dlg.title_label.hide()
    dlg.body.addWidget(plain_label(prompt))
    entry = QLineEdit()
    if secret:
        entry.setEchoMode(QLineEdit.EchoMode.Password)
    entry.setText('' if initial is None else str(initial))
    dlg.body.addWidget(entry)
    dlg.initial_focus = entry

    def accept_cb():
        return check(entry.text()) if check is not None else True
    dlg.add_button('Cancel', cancel=True)
    dlg.add_button(ok_text, role='primary', result='ok', default=True, callback=accept_cb)
    entry.selectAll()
    fit_dialog(dlg)
    try:
        if dlg.run() == 'ok':
            return entry.text()
        return None
    finally:
        if secret:                                   # a typed password must not stay in a hidden widget of the parent window (QT-G1b)
            entry.clear()
            dlg.deleteLater()


def ask_text(parent, title: str, prompt: str, initial=None, show=None) -> str | None:
    """simpledialog.askstring: the typed text ('' when OK is pressed on an empty box), None = cancelled.  `show` (any value) masks the entry."""
    return _entry_dialog(parent, title, prompt, initial, bool(show))


def ask_number(parent, title: str, prompt: str, initial=None, minvalue=None, maxvalue=None, integer=False):
    """simpledialog.askfloat / askinteger, including its validation: a bad entry shows the same 'Illegal value' / 'Too small' / 'Too large' warning and the
    dialog stays open.  Python's float() is the parser (as in Tk), so 'nan' and '1e3' are accepted exactly as before."""
    host = resolve_parent(parent)
    holder: dict = {}

    def check(text: str) -> bool:
        try:
            value = int(text) if integer else float(text)
        except ValueError:
            message(dlg_ref[0] or host, 'warning', 'Illegal value', ('Not an integer.' if integer else 'Not a floating-point value.') + '\nPlease try again')
            return False
        if minvalue is not None and value < minvalue:
            message(dlg_ref[0] or host, 'warning', 'Too small', f'The allowed minimum value is {minvalue}. Please try again.')
            return False
        if maxvalue is not None and value > maxvalue:
            message(dlg_ref[0] or host, 'warning', 'Too large', f'The allowed maximum value is {maxvalue}. Please try again.')
            return False
        holder['v'] = value
        return True
    dlg_ref: list = [None]
    text = _entry_dialog(host, title, prompt, initial, False, check=check)
    return holder.get('v') if text is not None else None


def ask_value(parent, title: str, prompt: str, default) -> str | None:
    """The adjustment launchers' value-entry window: prompt, one entry pre-filled with `default`, 'Use this value' / 'Cancel', Enter accepts."""
    return _entry_dialog(parent, _title(title), prompt, default, False, ok_text='Use this value', width=520)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# operator prompt (ui_theme.confirm_steps)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
class _NumberDot(QWidget):
    """The numbered step marker: a filled accent square-circle with the number, painted from the live tokens."""

    def __init__(self, n: int, parent=None):
        super().__init__(parent)
        self.n = n
        self.setFixedSize(24, 24)

    def paintEvent(self, ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t['primary']))
        p.drawRoundedRect(QRectF(0, 0, 24, 24), 7, 7)
        p.setPen(QColor(t['on_primary']))
        f = p.font()
        f.setBold(True)
        f.setPixelSize(M.font_small)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 24, 24), Qt.AlignmentFlag.AlignCenter, str(self.n))


class _AccentText(QWidget):
    """Large bold text in the accent colour (the 'n of N' of the function-change strip), painted from the live tokens."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        f = self.font()
        f.setBold(True)
        f.setPixelSize(M.font_h1)
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text) + 2, fm.height())

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setPen(QColor(theme.tokens()['primary']))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text)


class _StepCircle(QWidget):
    """The stepper circle of the function-change window: a green tick when `state` is 'done', else the number; a thin line runs down to the next circle."""

    def __init__(self, n: int, state: str, last: bool, parent=None):
        super().__init__(parent)
        self.n, self.state, self.last = n, state, last
        self.setFixedWidth(32)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(28)

    def paintEvent(self, ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, r = 16.0, 13.0
        if not self.last:
            p.setPen(QPen(QColor(t['border_strong']), 1))
            p.drawLine(QPointF(cx, 2 * r + 2), QPointF(cx, self.height()))
        if self.state == 'done':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t['good_dot']))
            p.drawEllipse(QPointF(cx, r + 1), r, r)
            pen = QPen(QColor(t['on_primary']), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            m = r + 1
            p.drawPolyline([QPointF(cx - r * 0.45, m), QPointF(cx - r * 0.1, m + r * 0.35), QPointF(cx + r * 0.5, m - r * 0.35)])
        else:
            p.setPen(QPen(QColor(t['primary']), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, r + 1), r - 1, r - 1)
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(cx - r, 1, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(self.n))


def _on_white(pix: QPixmap) -> QPixmap:
    out = QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
    out.fill(QColor('#FFFFFF'))
    p = QPainter(out)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


def _facts_card(facts) -> QFrame:
    card = QFrame()
    card.setProperty('surface', 'card')
    grid = QGridLayout(card)
    grid.setContentsMargins(M.md, M.sm, M.md, M.sm)
    grid.setHorizontalSpacing(M.xl)
    grid.setVerticalSpacing(2)
    for i, (k, v) in enumerate(facts):
        grid.addWidget(plain_label(str(k), 'kvkey', wrap=False), i, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(plain_label(str(v), 'kvvalue', wrap=True), i, 1)
    grid.setColumnStretch(1, 1)
    return card


def _step_row(n: int, step) -> QWidget:
    lead, detail = step if isinstance(step, (tuple, list)) else ('', step)
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(M.md)
    h.addWidget(_NumberDot(n), 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    if lead:
        col.addWidget(plain_label(str(lead), 'section'))
    if detail:
        col.addWidget(plain_label(str(detail), 'sub' if lead else None))
    h.addLayout(col, 1)
    return row


class _EnlargeablePicture(QLabel):
    """The hook-up picture of a prompt: a click opens it at full size in its own window (the prompt keeps its place behind it)."""

    def __init__(self, full: QPixmap):
        super().__init__()
        self._full = full
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to enlarge the picture')

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.enlarge()
        super().mousePressEvent(ev)

    def enlarge(self):
        from PySide6.QtWidgets import QScrollArea
        dlg = ModalDialog(self.window(), 'Hook-up picture', width=900)
        dlg.title_label.hide()
        big = QLabel()
        big.setPixmap(_on_white(self._full))
        area = QScrollArea()
        area.setWidget(big)
        area.setMinimumSize(min(self._full.width() + 24, 1100), min(self._full.height() + 24, 760))
        dlg.body.addWidget(area)
        dlg.add_button('Close', cancel=True, result='cancel', default=True)
        fit_dialog(dlg)
        dlg.run()


def operator_prompt(parent, title: str, heading: str, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, layout=None, card=None) -> bool:
    """Confirm-the-hook-up / safety prompt.  True = the OK button (Enter), False = Cancel / Esc / closing the window.  Same content as ui_theme.confirm_steps:
    heading, key facts card, 'Before you continue', numbered steps (bold lead + detail), optional caution banner, optional PNG hook-up picture beside the text."""
    if layout == 'function_change':
        return _function_change(parent, title, card, ok, cancel)
    dlg = ModalDialog(resolve_parent(parent), _title(title), width=560)
    dlg.title_label.hide()
    pix = QPixmap(str(image)) if image else QPixmap()
    text_col = QVBoxLayout()
    text_col.setSpacing(M.sm + 2)
    text_col.addWidget(plain_label(heading, 'h2'))
    if facts:
        text_col.addWidget(_facts_card(facts))
    text_col.addWidget(plain_label('Before you continue', 'sub', wrap=False))
    for n, step in enumerate(steps, 1):
        text_col.addWidget(_step_row(n, step))
    if caution:
        note = Banner(caution, 'warn', title='Caution')
        _plain_all(note)
        note.text_label.setTextFormat(Qt.TextFormat.PlainText)
        text_col.addWidget(note)
    if not pix.isNull():
        row = QHBoxLayout()
        row.setSpacing(M.xl)
        pic = _EnlargeablePicture(pix)
        pic.setObjectName('hookup_picture')
        pic.setPixmap(_on_white(pix.scaledToWidth(min(pix.width(), 460), Qt.TransformationMode.SmoothTransformation)))      # a diagram is drawn on white
        pic.setFixedSize(pic.pixmap().size() / pic.pixmap().devicePixelRatio())
        row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        text_col.addStretch(1)                                  # the text keeps its natural height beside a tall picture instead of being spread over it
        row.addLayout(text_col, 1)
        dlg.body.addLayout(row)
        dlg.setMinimumWidth(1040)
    else:
        dlg.body.addLayout(text_col)
    dlg.add_button(cancel, cancel=True, result='cancel')
    okb = dlg.add_button(ok, role='primary', result='ok', default=True)
    dlg.initial_focus = okb
    fit_dialog(dlg)
    return dlg.run() == 'ok'


def _function_change(parent, title: str, card: dict, ok: str, cancel: str) -> bool:
    """The 'Change the function' window: point strip on top, stepper below (see handheld_dmm.function_change_card).  Enter = OK, Esc / closing = Cancel."""
    dlg = ModalDialog(resolve_parent(parent), _title(title), width=FN_WIDTH + 48)
    dlg.title_label.hide()
    strip = QFrame()
    strip.setProperty('surface', 'card')
    h = QHBoxLayout(strip)
    h.setContentsMargins(M.lg, M.md - 2, M.lg, M.md - 2)
    h.setSpacing(M.lg)
    num = _AccentText(f'{card["n"]} of {card["total"]}')
    h.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    col.addWidget(plain_label(card['test'], 'section'))
    col.addWidget(plain_label(card['meter_line'], 'sub'))
    h.addLayout(col, 1)
    dlg.body.addWidget(strip)
    dlg.body.addSpacing(M.md)
    steps = card['steps']
    for i, (lead, detail, state) in enumerate(steps):
        row = QHBoxLayout()
        row.setSpacing(M.md)
        row.addWidget(_StepCircle(i + 1, state, i == len(steps) - 1))
        c = QVBoxLayout()
        c.setSpacing(1)
        c.addWidget(plain_label(str(lead), 'section'))
        if detail:
            c.addWidget(plain_label(str(detail), 'sub'))
        c.addSpacing(M.md if i < len(steps) - 1 else 0)
        row.addLayout(c, 1)
        dlg.body.addLayout(row)
    dlg.add_button(cancel, cancel=True, result='cancel')
    okb = dlg.add_button(ok, role='primary', result='ok', default=True)
    dlg.initial_focus = okb
    fit_dialog(dlg)
    return dlg.run() == 'ok'


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# file choosers (tkinter.filedialog)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
native_file_dialogs: bool | None = None          # None = native except on the offscreen platform (tests); True / False forces it


def name_filters(filetypes) -> list[str]:
    """Tk filetypes [(label, pattern | (patterns...))] -> Qt name filters ['Label (*.a *.b)']."""
    out = []
    for ft in filetypes or ():
        lab, pats = ft[0], ft[1]
        if isinstance(pats, str):
            pats = pats.split()
        out.append(f'{lab} ({" ".join(pats)})')
    return out


def _file_dialog(parent, opts: dict, *, save: bool, directory: bool = False) -> QFileDialog:
    dlg = QFileDialog(resolve_parent(parent), opts.get('title') or '')
    native = native_file_dialogs
    if native is None:
        native = QApplication.platformName() != 'offscreen'
    if not native:
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if directory:
        dlg.setFileMode(QFileDialog.FileMode.Directory)
        dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    elif save:
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dlg.setFileMode(QFileDialog.FileMode.AnyFile)
    else:
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QFileDialog.FileMode.ExistingFiles if opts.get('multiple') else QFileDialog.FileMode.ExistingFile)
    filters = name_filters(opts.get('filetypes'))
    if filters:
        dlg.setNameFilters(filters)
    ext = opts.get('defaultextension')
    if ext:
        dlg.setDefaultSuffix(str(ext).lstrip('.'))
    initdir = opts.get('initialdir')
    if initdir:
        dlg.setDirectory(str(initdir))
    initfile = opts.get('initialfile')
    if initfile:
        dlg.selectFile(str(initfile))
    return dlg


def _run_file_dialog(dlg: QFileDialog) -> list[str]:
    return list(dlg.selectedFiles()) if dlg.exec() else []


def open_file(parent, **opts):
    """askopenfilename: the path, '' = cancelled (a tuple of paths, () when cancelled, with multiple=True)."""
    files = _run_file_dialog(_file_dialog(parent, opts, save=False))
    if opts.get('multiple'):
        return tuple(files)
    return files[0] if files else ''


def save_file(parent, **opts) -> str:
    files = _run_file_dialog(_file_dialog(parent, opts, save=True))
    return files[0] if files else ''


def choose_dir(parent, **opts) -> str:
    files = _run_file_dialog(_file_dialog(parent, opts, save=False, directory=True))
    return files[0] if files else ''
