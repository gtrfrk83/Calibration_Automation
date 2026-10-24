"""Building blocks shared by the three Qt adjustment windows (keithley2000_adjust_view_qt, fluke8808a_adjust_view_qt, fluke8846a_adjust_view_qt).

Nothing here decides anything about a calibration: it is layout only (the page frame, the 'Who and what' / 'Connect' cards, the NEXT line, the step and audit tables,
the button bar and its enabled / disabled helper).  No Tk, no engine, no instrument.  The windows take the launcher's App as `self` and keep their widgets as attributes
of it, exactly like the Tk views (`btn_*`, `pill_*`, `tree`, `log_table`, `log_box`, `scope_combo` ...).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QMainWindow, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from . import shell_helpers as ui
from . import widgets as W
from .theme import M

# ----------------------------------------------------------------------------------------------------------------------------------------------------
# tables
# ----------------------------------------------------------------------------------------------------------------------------------------------------
STEP_TONE = {'done': 'good', 'next': 'info', 'failed': 'bad', 'eligible': 'info'}      # the Tk row tags of the step tables -> a DataTable row tone
LOG_TONE = {'ok': 'good', 'bad': 'bad'}                                                  # the Tk tags of the audit tables (coloured text only)


def _tone_fn(mapping):
    def tone(row):
        for t in row.tags:
            if t in mapping:
                return mapping[t]
        return None
    return tone


class StepTable(ui.ResultsTree):
    """The guided step list.  A modest size hint (the table takes whatever height is free) keeps the whole window within a 900 px screen without a scroll bar."""

    def sizeHint(self):
        return QSize(600, M.header_h + 3 * M.row_h)


def step_table(columns, headings, widths, anchors, stretch, height):
    """The step list.  The order of the steps is the order of the procedure, so the header does NOT sort it (the Tk table did not either)."""
    t = StepTable(columns, headings, widths, anchors, stretch, 'browse', ())
    t.set_row_tone(_tone_fn(STEP_TONE))
    t.source_model.tone_style = 'both'
    _no_sort(t)
    return t


class LogTable(ui.ResultsTree):
    """The audit table: newest row on top (the Tk `insert('', 0, ...)`), a failed / ok outcome coloured as text only."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._n = 0
        self.empty_text = 'No audit entries yet'
        self.set_row_tone(_tone_fn(LOG_TONE))
        self.source_model.tone_style = 'text'
        _no_sort(self)

    def prepend(self, values, tags=()):
        self._n += 1
        row = ui.TreeRow(f'log{self._n}', values, tags)
        self._by_iid[row.iid] = row
        self.set_rows([row] + list(self.rows()), keep_selection=False)

    def clear(self):
        self._by_iid = {}
        self.set_rows([], keep_selection=False)


def log_table(columns, headings, widths, anchors, stretch, height):
    t = LogTable(columns, headings, widths, anchors, stretch, 'browse', ())
    t.setFixedHeight(M.header_h + 3 * M.row_h + 4)         # the log shows its newest rows; the step list gets the free height
    return t


def _no_sort(t):
    hh = t.horizontalHeader()
    hh.setSectionsClickable(False)
    hh.setSortIndicatorShown(False)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# page frame
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def setup_window(root, title, width, height, min_w, min_h):
    """Theme, title and size of the main window (ui.apply_theme / root.title / ui.fit_window of the Tk views)."""
    ui.apply_theme(root)
    root.setWindowTitle(title)
    ui.fit_window(root, width, height, min_w=min_w, min_h=min_h)


def new_page(root, banner, status_bar):
    """The window's central widget: banner on top, status bar at the bottom, and between them the body (in a scroll area: a small window scrolls instead of
    squeezing the controls).  Returns the body's QVBoxLayout."""
    page = QWidget()
    col = QVBoxLayout(page)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(banner)
    body = QWidget()
    body.setObjectName('adjust_body')
    lay = QVBoxLayout(body)
    lay.setContentsMargins(M.xl, M.lg, M.xl, M.md)
    lay.setSpacing(M.md)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(body)
    scroll.viewport().setAutoFillBackground(False)
    col.addWidget(scroll, 1)
    col.addWidget(status_bar)
    if isinstance(root, QMainWindow):
        root.setCentralWidget(page)
    else:
        outer = root.layout() or QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)
    return lay


def notice(text, kind='bad', title=None):
    """The red call-out under the banner.  An explicit minimum height: a wrapped label reports its one-column height as its minimum, which would force a scroll bar."""
    n = ui.Notice(None, text, kind, title=title)
    n.setMinimumHeight(60)
    return n


def link_card(title, max_cols=4):
    """A titled card holding a FieldGrid.  Returns (card, fields)."""
    c = W.Card(title, padding=M.md)
    f = FieldGrid(max_cols)
    c.body.addWidget(f)
    return c, f


def card(title):
    """A titled card (the Tk LabelFrame).  Returns (card, grid): put the controls into the QGridLayout."""
    c = W.Card(title, padding=M.md)
    g = QGridLayout()
    g.setHorizontalSpacing(M.md)
    g.setVerticalSpacing(M.sm)
    c.body.addLayout(g)
    return c, g


def plain(text, muted=False, wrap=False, bold=False):
    lab = ui.label_(None, text, 'Muted.TLabel' if muted else ('Bold.TLabel' if bold else None), wraplength=1 if wrap else None)
    return lab


def entry(var, width):
    """A line edit bound to `var`, about `width` characters wide (Tk's ttk.Entry(width=))."""
    e = ui.entry(None, textvariable=var)
    e.setFixedWidth(e.fontMetrics().averageCharWidth() * width + 28)
    return e


def put(grid, widget, row, column, columnspan=1, left=True):
    grid.addWidget(widget, row, column, 1, columnspan, (Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter)
    return widget


def combo(var, values, width=10, state='readonly', command=None):
    """A combo box bound to `var`, as wide as its longest entry (a name such as 'Fluke 5560A' must never be cut off)."""
    c = ui.combobox(None, var, values, width, state, command=command)
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    fm = c.fontMetrics()
    longest = max([fm.horizontalAdvance(str(v)) for v in values] + [fm.averageCharWidth() * 4])
    c.setFixedWidth(longest + 56)
    return c


class FieldGrid(QWidget):
    """Label + control pairs that flow in reading order into as many columns as fit (the Tk window had one fixed row layout; at the 1000 px minimum width it
    would have cut text, here the pairs wrap instead).  `field(text, control)` adds a pair, `full(widget)` a widget of its own row."""

    def __init__(self, max_cols=4):
        super().__init__()
        self._g = QGridLayout(self)
        self._g.setContentsMargins(0, 0, 0, 0)
        self._g.setHorizontalSpacing(M.lg)
        self._g.setVerticalSpacing(M.sm)
        self._items = []                                   # (widget, full row?)
        self._cols = 0
        self._max = max_cols

    def field(self, text, control, muted=False):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(M.sm)
        row.addWidget(plain(text, muted=muted))
        row.addWidget(control)
        row.addStretch(1)
        self._items.append((box, False))
        self._reflow(force=True)
        return control

    def full(self, widget):
        self._items.append((widget, True))
        self._reflow(force=True)
        return widget

    def _fit(self, cols):
        """Width the pairs need when laid out in `cols` columns (every column as wide as its widest pair)."""
        widths = [0] * cols
        for i, (w, _) in enumerate([it for it in self._items if not it[1]]):
            widths[i % cols] = max(widths[i % cols], w.sizeHint().width())
        return sum(widths) + (cols - 1) * self._g.horizontalSpacing()

    def _reflow(self, force=False):
        avail = self.width()
        cols = self._max
        if avail > 1:
            while cols > 1 and self._fit(cols) > avail:
                cols -= 1
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w, _ in self._items:
            self._g.removeWidget(w)
        r = c = 0
        for w, full in self._items:
            if full:
                if c:
                    r, c = r + 1, 0
                self._g.addWidget(w, r, 0, 1, cols)
                r, c = r + 1, 0
                continue
            self._g.addWidget(w, r, c)
            c += 1
            if c == cols:
                r, c = r + 1, 0
        for i in range(self._g.columnCount()):
            self._g.setColumnStretch(i, 1 if i == cols - 1 else 0)
        self.updateGeometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reflow()

    def minimumSizeHint(self):
        return super().minimumSizeHint().boundedTo(self.sizeHint())


def who_card(self, width=20):
    """'1  Who and what' (Instrument ID / Serial number / Technician); the Keithley and 8808A add a Scope row after it.  Returns (card, grid, next row)."""
    c, g = card('1  Who and what')
    for r, (label, var) in enumerate((('Instrument ID *', self.asset), ('Serial number *', self.serial), ('Technician *', self.tech))):
        put(g, plain(label), r, 0)
        put(g, entry(var, width), r, 1)
    g.setColumnStretch(2, 1)
    return c, g, 3


def hint_row(self):
    """'NEXT' + the bold next-step line (bound to self.next_hint)."""
    row = QHBoxLayout()
    row.setSpacing(M.md)
    cap = ui.label_(None, 'NEXT', None)
    cap.setProperty('role', 'hint')
    row.addWidget(cap, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(ui.label_(None, '', 'Bold.TLabel', textvariable=self.next_hint, wraplength=1), 1)
    return row


def button_bar(left, right, show_log_var, on_toggle):
    """The action buttons: `left` in order from the left; `right` (close first, then abort ...) from the right edge; the 'Show audit log' tick box next to them."""
    bar = QHBoxLayout()
    bar.setSpacing(M.sm)
    for b in left:
        bar.addWidget(b)
    bar.addStretch(1)
    bar.addWidget(ui.checkbutton(None, 'Show audit log', show_log_var, on_toggle))
    for b in reversed(right):
        bar.addWidget(b)
    return bar


def enable(btn, cond):
    btn.configure(state='normal' if cond else 'disabled')


def log_card(title, table, visible):
    c = W.Card(title, padding=M.md)
    c.body.addWidget(table)
    c.setVisible(visible)
    return c


def stretch_table(table):
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return table
