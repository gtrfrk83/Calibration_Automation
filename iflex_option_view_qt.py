"""iFlex window option (iflex_option.App): the Qt widgets of the 'iFlex probe supplied' check boxes.  The twin of iflex_option_view_tk.py with the same functions, taking the
engine's App as `self` and keeping the widgets and variables as attributes of it (`_include_vars`, `_include_labels`, `_inc_rows`, ...); reached through
`ui_port.ui.view('iflex_option_view')`.  Nothing here decides anything about a calibration."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from qtui import shell_helpers as H
from qtui.vars import QtVar


def build_include_bar(self):
    defs = self.include_defs()
    self._include_vars, self._include_labels = {}, {}
    bar = H.frame(None, 'h', spacing=12)
    self.include_bar = bar
    content = self.shell.content.layout()
    content.insertWidget(0, bar)                                       # above the filter row and the results table (Tk: packed 'before' the first widget)
    content.insertSpacing(1, 6)
    for d in defs:
        var = QtVar(bool(self._include.get(d['id'], True)), 'bool')
        self._include_vars[d['id']] = var
        box = H.checkbutton(None, d['label'], var, command=lambda k=d['id']: self._on_include_click(k))
        box.setAccessibleName(d['label'])
        bar.layout().addWidget(box)
        text = H.label_(None, self.include_text(d['id'], short=True), 'Muted.TLabel')
        bar.layout().addWidget(text)
        self._include_labels[d['id']] = text
    bar.layout().addStretch(1)


def _clear(box):
    lay = box.layout()
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def build_include_rows(self, d, nxt):
    """The row holder of the Connections drawer, then its per-meter rows (the engine then builds the rows and returns nxt + 1)."""
    grid = d if not isinstance(d, QWidget) else d.layout()
    self._inc_rows = QWidget()
    lay = QVBoxLayout(self._inc_rows)
    lay.setContentsMargins(0, 6, 0, 0)
    lay.setSpacing(0)
    grid.addWidget(self._inc_rows, nxt, 0, 1, 2)
    self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, None


def rebuild_include_rows(self):
    """Update the per-meter boxes in place when the meters are unchanged, else rebuild them."""
    box = getattr(self, '_inc_rows', None)
    if box is None:
        return
    meters, defs = list(self.queue.meters), self.include_defs()
    sig = tuple(m.asset for m in meters)
    if defs and meters and sig == getattr(self, '_inc_rows_sig', None):          # same meters: update the boxes in place (the box being clicked stays)
        for m in meters:
            inc = self._ensure_meter(m)
            self._inc_row_vars[m.asset].set(bool(inc.get(defs[0]['id'], True)))
            self._inc_row_notes[m.asset].setText(self._meter_include_note(m, defs[0]))
        return
    _clear(box)
    self._inc_row_vars, self._inc_row_notes, self._inc_rows_sig = {}, {}, sig
    if not meters or not defs:
        return
    d = defs[0]
    lay = box.layout()
    lay.addWidget(H.label_(None, f'{self._inc_label(None)} probe, per meter', 'Bold.TLabel'))
    for m in meters:
        inc = self._ensure_meter(m)
        var = QtVar(bool(inc.get(d['id'], True)), 'bool')
        self._inc_row_vars[m.asset] = var
        check = H.checkbutton(None, f'{m.asset}: {self._inc_label(None)} supplied', var, command=lambda m=m, v=var: self._on_meter_include_click(m, v))
        check.setAccessibleName(f'{m.asset}: {self._inc_label(None)} supplied')
        lay.addSpacing(4)
        lay.addWidget(check)
        note = H.label_(None, self._meter_include_note(m, d), 'Muted.TLabel', wraplength=320)
        note.setContentsMargins(24, 0, 0, 0)
        note.setMaximumWidth(344)
        lay.addWidget(note)
        self._inc_row_notes[m.asset] = note


def set_include_label(self, key, text):
    self._include_labels[key].setText(text)
