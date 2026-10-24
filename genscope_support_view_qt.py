"""Building blocks shared by the Qt windows of the function generators and oscilloscopes (fgen_view_qt, mdo4000c_view_qt, tds2000c_view_qt; package QT-G2a).  The name ends in `_view_qt.py` so that it is listed in the
procedures' fingerprints with its views (tests/test_procscan allows exactly the Qt view files as additions); it is not itself a window module.

The three Tk views (fgen_view_tk, mdo4000c_view_tk, tds2000c_view_tk) repeat the same statements; the Qt twins share them here:

  * `AfterRoot`          a Tk-like `after` / `after_cancel` facade over a Qt window (labregistry.attach(root, ...) debounces the Instrument ID with `root.after`)
  * `drawer_row`, `drawer_note`, `drawer_separator`, `drawer_buttons`    the rows of the Connections drawer (the Tk views grid them into `shell.drawer_body`)
  * `action_bar`         the Run / Section / Rerun / Stop buttons and the Export / Load / Save buttons, in the Tk order and with the Tk texts
  * `filter_bar`, `detail_panel`    'Test points ... Show [filter]' above the table and the detail text under it
  * `sync_buttons`       the busy / idle state of the buttons and the configuration boxes
  * `table_*`, `set_choices`  the results-table and address-box calls of the views (exact twins of the Tk statements)

Nothing here decides anything about a calibration, talks to an instrument or imports Tk.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from qtui import shell_helpers as H


class AfterRoot:
    """`after(ms, fn, *args)` / `after_cancel(handle)` for a Qt window: what labregistry.attach(root, ...) needs from a Tk root.  Timers are the port's own."""

    def __init__(self, win):
        self.win = win

    def after(self, ms, fn=None, *args):
        from ui_port import ui as port
        if fn is None:
            return None
        return port.after(self.win, int(ms), fn, *args)

    def after_cancel(self, handle):
        from ui_port import ui as port
        if handle is not None:
            port.cancel_after(self.win, handle)

    def __getattr__(self, name):                       # anything else a caller might ask of a root: the window itself
        return getattr(self.win, name)


def attach_history(self):
    """The last window statement of the engines' former __init__ (labregistry.attach on the window), with a Qt-capable root."""
    import labregistry
    labregistry.attach(AfterRoot(self.root), self.asset, self.serial, self.status.set)


# ---- the Connections drawer (shell.drawer_body is a QGridLayout host, column 1 stretches) -------------------------------------------------
def drawer_row(d: QWidget, row: int, label: str, widget: QWidget, *, left: bool = False):
    """A 'label | widget' row.  left=True keeps a short drop-down at its natural width (Tk: sticky='w')."""
    lay: QGridLayout = d.layout()
    lay.addWidget(H.label_(None, label), row, 0, Qt.AlignmentFlag.AlignVCenter)
    if left:
        lay.addWidget(widget, row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    else:
        lay.addWidget(widget, row, 1)
    return widget


def drawer_separator(d: QWidget, row: int):
    d.layout().addWidget(H.separator(), row, 0, 1, 2)


def drawer_note(d: QWidget, row: int, text: str):
    note = H.label_(None, text, 'Muted.TLabel', wraplength=340)
    d.layout().addWidget(note, row, 0, 1, 2)
    return note


def drawer_check(d: QWidget, row: int, text: str, var, command):
    c = H.checkbutton(None, text, var, command)
    d.layout().addWidget(c, row, 0, 1, 2)
    return c


def drawer_buttons(self, sh):
    """'Find instruments' and 'Test connections' pinned under the drawer form (self.btn_find / self.btn_test)."""
    self.btn_find = H.button(None, 'Find instruments', self.find_instruments)
    self.btn_test = H.button(None, 'Test connections', self.test_connections, style='Accent.TButton')
    sh.drawer_footer_layout.insertWidget(0, self.btn_find)
    sh.drawer_footer_layout.insertWidget(1, self.btn_test)


def address_box(var, width=34):
    """An editable drop-down bound to an address variable (ttk.Combobox state='normal')."""
    return H.combobox(None, var, [], width=width, state='normal')


def action_bar(self, sh):
    """The action bar of the Tk views, same buttons, order, texts and short texts."""
    self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
    self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
    self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
    sh.add_action('Save progress', self.save, side='right', short='Save')


def filter_bar(self, body: QWidget, statuses):
    """'Test points' title on the left, 'Show [status filter]' on the right.  Returns the bar (small_window puts the section drop-down in it)."""
    filt = H.frame(None, 'h', spacing=8)
    row = filt.layout()
    row.addWidget(H.label_(None, 'Test points', 'Bold.TLabel'))
    row.addStretch(1)
    row.addWidget(H.label_(None, 'Show', 'Muted.TLabel'))
    combo = H.combobox(None, self.show_status, list(statuses), width=14, command=self.refresh)
    self.show_combo = combo
    row.addWidget(combo)
    body.layout().addWidget(filt)
    body.layout().addSpacing(6)
    return filt


def detail_panel(self, body: QWidget, note: str | None = None):
    """The detail text under the table (self.detail), and the source note below it when the engine shows one."""
    body.layout().addSpacing(8)
    info = H.frame(None, 'v', spacing=4)
    lay = info.layout()
    lay.addWidget(H.label_(None, '', 'Muted.TLabel', textvariable=self.detail, wraplength=1100))
    if note is not None:
        lay.addWidget(H.label_(None, note, 'Small.TLabel', wraplength=1100))
    body.layout().addWidget(info)
    return info


def follow_prefixed(combo, var, prefix: str) -> None:
    """A model drop-down whose items carry a prefix ('MDO4104C') while the engine keeps the bare model in the variable ('4104C'; on_config strips the prefix).  Tk shows the
    variable's text as it is; a Qt drop-down can only show an item, so it follows the variable to the item with the prefix."""
    def sync(*_):
        want = prefix + str(var.get()).replace(prefix, '')
        i = combo.findText(want)
        if i >= 0 and i != combo.currentIndex():
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
    var.trace_add('write', sync)
    sync()


def widen_columns(tree) -> None:
    """The generators' and scopes' limits and readings carry a unit and up to ten characters ('9.99998 MHz', '+246.373 mdB'): a little wider than the shell's defaults, so they are
    not cut with an ellipsis (the Tk columns were wider in characters as well)."""
    for col, width in (('nominal', 92), ('low', 100), ('high', 100), ('found', 104), ('error', 108), ('left', 104)):
        tree.column(col, width=width)


def enable(widget, on: bool) -> None:
    """Enable or disable any button / box (the mode toggle's buttons are plain QAbstractButtons)."""
    widget.setEnabled(bool(on))


def sync_buttons(self, config_boxes=()):
    idle = not self._busy
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        enable(b, idle)
    enable(self.btn_stop, self._busy)
    for c in config_boxes:
        enable(c, idle)


# ---- results table and address boxes: the exact statements the engine used to make on self.tree / the address boxes ---------------------------
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    """rows: iterable of (iid, values, tags); keep: the selection before the refresh (the first row of it is selected again if it is still there)."""
    self.tree.set_all(rows, keep)


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices_for(boxes, values):
    """The drop-down values of every instrument address box (the text typed in a box stays)."""
    for cb in boxes:
        cb['values'] = values

