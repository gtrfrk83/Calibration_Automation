"""User-built datasheet runtime (dsb_runtime.DsbApp): the Qt widgets of its window.  The twin of dsb_runtime_view_tk.py with the same functions, taking the engine's DsbApp
as `self`; reached through `ui_port.ui.view('dsb_runtime_view')`:

    build_section_bar(self, labels)       rule 12: the section-mode box next to the Show boxes (self.section_caption / section_mode_var / section_mode_box)
    build_standards(self, rows, counter, periods, help_text)       the 'Standards used by this datasheet' rows of the Connections drawer
    build_manual_drawer(self, stock_start, heading, text)          the 'Manual calibration' text of the drawer, and the stock notice that does not apply removed
    retitle_manual(self, old, new, subtitle)                       'Performance Verification' -> 'Manual Calibration' in the window title and the banner
    attach_grid_entry(self)                                        typed readings straight into the test point grid (qtui.screens.manual_grid.GridEntry)

Nothing here decides anything about a calibration.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from qtui import shell_helpers as H
from qtui.screens import common
from ui_port import ui as port

_W = Qt.AlignmentFlag


def _note(text):
    return H.label_(None, text, 'Muted.TLabel', wraplength=340)         # no maximum width: a grid computes the row height for the cell width (a narrower label is clipped)


def build_section_bar(self, labels):
    """The control of rule 12: in the bar above the test points, next to the Show boxes; acts on the section chosen in the sidebar."""
    picker = self.shell.section_picker
    bar = picker.parentWidget() if picker is not None else None
    if bar is None or bar.layout() is None:
        return False
    box = H.frame(None, 'h', spacing=6)
    self.section_caption = port.var('Section mode: choose a section on the left')
    box.layout().addWidget(H.label_(None, '', 'Muted.TLabel', textvariable=self.section_caption))
    self.section_mode_var = port.var('')
    self.section_mode_box = H.combobox(None, self.section_mode_var, values=list(labels), state='readonly', width=15,
                                       command=lambda: self._on_mode_chosen())
    self.section_mode_box.setAccessibleName('Section mode')
    self.section_mode_box.setCurrentIndex(-1)                                  # blank until a section is chosen (a Tk readonly box holds '')
    self.section_mode_var.set('')
    self.section_mode_var.trace_add('write', lambda *_: common.post_ui(_blank_if_empty, self))
    self.section_mode_box.configure(state='disabled')
    box.layout().addWidget(self.section_mode_box)
    lay = bar.layout()
    lay.insertSpacing(lay.indexOf(picker) + 1, 18)
    lay.insertWidget(lay.indexOf(picker) + 2, box)
    for col in self.tree.source_model.columns:                                 # the 'skipped' tag of Tk (tag_configure foreground muted): the whole row in the muted colour
        old = col.tone
        col.tone = (lambda r, _o=old: 'muted' if 'skipped' in r.tags else (_o(r) if _o else None))
    return True


def _blank_if_empty(self):
    box = getattr(self, 'section_mode_box', None)
    if box is not None and self.section_mode_var.get() == '':
        box.setCurrentIndex(-1)


def build_standards(self, rows, counter, periods, help_text):
    d = self.shell.drawer_body
    row = 20
    H.grid(d, H.separator(), row=row, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    H.grid(d, H.label_(None, 'Standards used by this datasheet', 'Bold.TLabel'), row=row + 1, column=0, columnspan=2, sticky='w')
    row += 2
    for model, label in rows:
        H.grid(d, H.label_(None, label), row=row, column=0, sticky='w', pady=4)
        edit = H.entry(None, self.std_addr[model], width=34)
        edit.setAccessibleName(f'Address of the {model}')
        H.grid(d, edit, row=row, column=1, sticky='ew', padx=(10, 0), pady=4)
        row += 1
    if counter:
        H.grid(d, H.label_(None, 'Counter timebase'), row=row, column=0, sticky='w', pady=4)
        box = H.combobox(None, self.counter_ref, values=['EXT', 'INT'], state='readonly', width=9)
        box.setAccessibleName('Counter timebase')
        H.grid(d, box, row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1
    if periods:
        H.grid(d, H.label_(None, 'Specification period'), row=row, column=0, sticky='w', pady=4)
        box = H.combobox(None, self.period_var, values=list(periods), state='readonly', width=9, command=lambda: self.on_period())
        box.setAccessibleName('Specification period')
        H.grid(d, box, row=row, column=1, sticky='w', padx=(10, 0), pady=4)
        row += 1
    H.grid(d, _note(help_text), row=row, column=0, columnspan=2, sticky='ew', pady=(6, 0))
    d.layout().setColumnStretch(1, 1)


def build_manual_drawer(self, stock_start, heading, text):
    lay = self.shell.notice_layout
    for i in reversed(range(lay.count())):                                       # the stock text ('the calibrator is programmed and enabled ...') does not apply
        w = lay.itemAt(i).widget()
        label = getattr(w, 'label', None)
        try:
            if label is not None and label.text().startswith(stock_start):
                lay.takeAt(i)
                w.setParent(None)
                w.deleteLater()
        except RuntimeError:
            pass
    d = self.shell.drawer_body
    H.grid(d, H.separator(), row=20, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    H.grid(d, H.label_(None, heading, 'Bold.TLabel'), row=21, column=0, columnspan=2, sticky='w')
    H.grid(d, _note(text), row=22, column=0, columnspan=2, sticky='ew', pady=(6, 0))


def retitle_manual(self, old, new, subtitle):
    """The stock banner says 'Performance Verification' and 'the calibrator output is set for you': neither is true of a manual calibration."""
    title = self.root.windowTitle()
    if ' ' + old in title:
        self.root.setWindowTitle(title.replace(' ' + old, ' ' + new))
    head = self.shell.title_label
    if head.text().endswith('  -  ' + old):
        head.setText(head.text().replace(old, new))
    self.shell.subtitle.set(subtitle)


def attach_grid_entry(self):
    from qtui.screens import manual_grid
    self.grid_entry = manual_grid.GridEntry(self, self.tree)
