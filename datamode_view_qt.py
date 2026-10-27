"""The As Found / As Left toggle, its notice and the table heading for Qt (port of the removed Tk view datamode_view_tk.py: same function names, same attributes on the App).
Functions whose first parameter is the App (`self`), reached through ui_port.get_ui().view('datamode_view').

The App keeps the attributes datamode.DataModeMixin works with: `mode_var` and `mode_hint` (objects with get() / set() / trace_add(), like a Tk variable),
`mode_buttons` (the two buttons; QAbstractButton, so a caller enables / disables them with setEnabled), `mode_notice_holder`, `mode_notice`.  Setting
`mode_var` from code moves the control WITHOUT calling `_mode_clicked` (as a Tk variable does); a click on the control sets the variable, then calls it.

Layout: `parent` is a QWidget (its layout gets the new widget; one is made when it has none) or a QLayout.  The Tk `**pack` options of build_mode_bar are
accepted and ignored (a Qt layout is not packed)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QRadioButton, QSizePolicy, QVBoxLayout, QWidget

from datamode import FOUND, LEFT, LABEL, HINT_FOUND
from qtui.widgets import Banner, SegmentedFilter, label


class QtVar:
    """get / set / trace_add like a Tk StringVar, for Qt widgets.  `set` calls the traces (mode 'write'), as ui_port's variables do."""

    def __init__(self, value=''):
        self._v, self._cbs = value, []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb('', '', 'write')

    def trace_add(self, mode, callback):
        self._cbs.append(callback)
        return str(len(self._cbs))


def attach(parent, widget):
    """Put `widget` into `parent` (a layout, or a widget: its layout, made when it has none)."""
    if parent is None:
        return
    if isinstance(parent, QLayout):
        parent.addWidget(widget)
        return
    lay = parent.layout()
    if lay is None:
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)


def build_mode_bar(self, parent, **pack):
    """The 'Collecting data' toggle (As Found | As Left).  Returns the frame."""
    self.mode_var = QtVar(self._mode)
    bar = QWidget()
    col = QVBoxLayout(bar)
    col.setContentsMargins(0, 8, 0, 0)
    col.setSpacing(0)
    row = QHBoxLayout()
    row.setSpacing(14)
    cap = label('Collecting data:', 'section')
    row.addWidget(cap)
    self.mode_buttons = []
    radios = {}
    for mode in (FOUND, LEFT):
        b = QRadioButton(LABEL[mode])
        b.setChecked(mode == self._mode)
        b.clicked.connect(lambda _c=False, m=mode: _clicked(self, m))
        row.addWidget(b)
        radios[mode] = b
        self.mode_buttons.append(b)
    self.mode_hint = QtVar(HINT_FOUND)
    hint = label(HINT_FOUND, 'hint', wrap=True)
    hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    row.addWidget(hint, 1)
    col.addLayout(row)

    def mode_changed(*_):
        want = self.mode_var.get()
        for m, b in radios.items():
            b.setChecked(m == want)
    self.mode_var.trace_add('write', mode_changed)
    self.mode_hint.trace_add('write', lambda *_: hint.setText(self.mode_hint.get()))
    holder = QWidget()
    hl = QVBoxLayout(holder)
    hl.setContentsMargins(0, 0, 0, 0)
    col.addWidget(holder)
    self.mode_notice_holder = holder
    self.mode_notice = None
    attach(parent, bar)
    return bar


def build_mode_segment(self, parent, notice_holder=None):
    """The compact  Collecting [ As Found | As Left ]  switch for the shell's top strip.  Same attributes as build_mode_bar; the hint is the tooltip and the
    As Left warning is the one-line amber notice in `notice_holder`."""
    self.mode_var = QtVar(self._mode)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 14, 0)
    row.setSpacing(8)
    row.addWidget(label('Collecting'))
    seg = SegmentedFilter([(FOUND, LABEL[FOUND]), (LEFT, LABEL[LEFT])])
    seg.set_current(self._mode)
    seg.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    row.addWidget(seg)
    self.mode_segment = seg
    self.mode_buttons = [seg._buttons[FOUND], seg._buttons[LEFT]]
    self.mode_hint = QtVar(HINT_FOUND)
    box.setToolTip(HINT_FOUND)
    self.mode_hint.trace_add('write', lambda *_: box.setToolTip(self.mode_hint.get()))     # the Tk tooltip reads the hint when it opens: same text, kept current
    seg.currentChanged.connect(lambda key: _clicked(self, key))
    self.mode_var.trace_add('write', lambda *_: seg.set_current(self.mode_var.get(), emit=False))
    if notice_holder is not None:
        self.mode_notice_holder = notice_holder
    else:                                              # Tk: a frame that is never packed, so the notice is not shown; the same here
        self.mode_notice_holder = QWidget(box)
        self.mode_notice_holder.hide()
    self.mode_notice = None
    self.mode_notice_short = True
    attach(parent, box)
    return box


def _clicked(self, mode):
    """A click on the control: the variable takes the choice first (the Tk radio button does), then the App decides (it may put the old value back)."""
    self.mode_var._v = mode                           # no trace: the control already shows it
    self._mode_clicked()


def show_mode_notice(self):
    holder = getattr(self, 'mode_notice_holder', None)
    if holder is None:
        return
    if self.mode_notice is not None:
        self.mode_notice.hide()
        self.mode_notice.setParent(None)
        self.mode_notice.deleteLater()
        self.mode_notice = None
    if self._mode == LEFT:
        short = getattr(self, 'mode_notice_short', False)
        text = ('Collecting AS LEFT: readings are saved beside the As Found values, which stay locked. Use after an adjustment only.' if short else
                'Readings taken now are saved as AS LEFT. Use this only after the instrument was adjusted. '
                'Switch back to As Found to review the original readings.')
        note = Banner(text, 'warn', title='' if short else 'Collecting As Left data')
        note.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.mode_notice = note
        attach(holder, note)
        note.show()


def relabel_reading_column(self):
    """The reading column heading follows the mode: 'Reading' / 'As Left reading' (the first of reading / found / entered the table has)."""
    tree = getattr(self, 'tree', None)
    if tree is None:
        return
    title = 'As Left reading' if self._mode == LEFT else 'Reading'
    model = getattr(tree, 'source_model', None)                        # qtui.table.DataTable
    if model is None:
        return
    for key in ('reading', 'found', 'entered'):                        # the first of these the table has, in this order (as the Tk heading loop)
        for i, col in enumerate(model.columns):
            if col.key == key:
                col.title = title
                model.headerDataChanged.emit(Qt.Orientation.Horizontal, i, i)
                return
