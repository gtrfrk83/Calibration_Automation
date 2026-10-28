"""Shared parts of the Qt engine windows of the bench verification engines (QT-G1a): the pieces the seven `*_view_qt.py` files (truevolt, dacq, k2000, f8808a, a34401a,
f8846a, agilent34410a) have in common, so each of those files only holds what is its own (titles, the connection form, the action bar).

The Tk views repeat these statements verbatim (see truevolt_view_tk.py); every function here is the Qt rendering of exactly those statements:

    setup_window(self, title, w, h, min_w, min_h)     theme + title + size of the main window
    finish_window(self)                               labregistry.attach(...) (asset history hint under the Instrument ID), with a `root` that has after / after_cancel
    set_buttons_state(self, groups...)                the busy / idle button states of sync_buttons
    Form(shell.drawer_body)                           the connection form in the slide-in drawer (label | widget rows, notes, rules)
    build_results(self, sh, note, ...)                filter row ("Test points" ... Show [status]) + results table + detail / source-note lines
    table_selection / table_has / table_select / table_set_rows / table_update_row           the table_* contract of the views

No Tk import here (tests/test_qtui_rules.py).  Nothing here talks to an instrument or decides anything about a calibration.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy

import datamode
import ui_port
from . import shell as S
from . import shell_helpers as H
from . import widgets as W
from .shell_helpers import Combobox

LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
VCENTER = Qt.AlignmentFlag.AlignVCenter
DRAWER_WRAP = 340                       # the width the Tk views wrap the notes of the connection drawer at


# ---------------------------------------------------------------------------------------------------------------------------------------
# window chrome
# ---------------------------------------------------------------------------------------------------------------------------------------
_TRAILING_VERSION = re.compile(r'\s*[|\-]?\s*\bv\d+(\.\d+)*(\s+Beta\s*\d*)?\s*$')


def suite_title(raw: str) -> str:
    """branding.tidy_title: 'Agilent 34401A | Performance Verification v54' -> 'Calibration Suite  |  Agilent 34401A | Performance Verification  |  v70 Beta 2'
    (the same pattern every Tk window gets from branding.dress; a title already in the suite pattern is left alone)."""
    import suite_info
    if not raw or raw.startswith(suite_info.NAME):
        return raw
    return suite_info.window_title(_TRAILING_VERSION.sub('', raw).strip())


def setup_window(self, title, width, height, min_w, min_h):
    """Theme, title and size of the main window (the Tk views' apply_theme / root.title / fit_window; the title takes the suite pattern like branding.dress gives it)."""
    H.apply_theme(self.root)
    self.root.setWindowTitle(suite_title(title))
    H.fit_window(self.root, width, height, min_w=min_w, min_h=min_h)


class _AfterRoot:
    """What labregistry.attach needs of a window (`after(ms, fn)` / `after_cancel(handle)`), on top of the Qt window and the UiPort."""

    def __init__(self, win):
        self.win = win

    def after(self, ms, fn, *args):
        return ui_port.get_ui().after(self.win, ms, fn, *args)

    def after_cancel(self, handle):
        ui_port.get_ui().cancel_after(self.win, handle)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    import labregistry
    labregistry.attach(_AfterRoot(self.root), self.asset, self.serial, self.status.set)
    dress(self.root)


def dress(win):
    """Window dressing every Tk window gets from branding.dress once it is built: the Help menu (About, data folder, import, diagnostic log, Appearance), F1 = About.
    Never breaks the window."""
    try:
        from qtui.screens import help_menu
        help_menu.dress(win)
    except Exception:                                  # noqa: BLE001 - dressing is a convenience
        pass


# ---------------------------------------------------------------------------------------------------------------------------------------
# busy / idle states
# ---------------------------------------------------------------------------------------------------------------------------------------
def set_state(widget, state):
    """Tk's `widget.configure(state=...)` for every widget the views keep ('disabled' | 'normal' | 'readonly'): our buttons / combo boxes have configure(), the
    As Found / As Left segment buttons are plain Qt buttons."""
    if hasattr(widget, 'configure'):
        widget.configure(state=state)
    else:
        widget.setEnabled(state != 'disabled')


def sync_buttons(self, idle_buttons, inputs):
    """The Tk sync_buttons: while busy every action button except Stop and every setting is disabled; Stop is enabled only while busy.
    `idle_buttons`: the buttons that are 'normal' when idle; `inputs`: [(widget, idle_state)] (combo boxes 'readonly', editable boxes and check boxes 'normal')."""
    idle = 'disabled' if self._busy else 'normal'
    if getattr(self, 'btn_rerun_from', None) is not None:      # 'Rerun From Selected' follows 'Rerun Selected'
        idle_buttons = (*idle_buttons, self.btn_rerun_from)
    for b in (*idle_buttons, *self.mode_buttons):
        set_state(b, idle)
    set_state(self.btn_stop, 'normal' if self._busy else 'disabled')
    for w, when_idle in inputs:
        set_state(w, 'disabled' if self._busy else when_idle)


def idle_state(widget):
    """The state a setting widget has when the window is idle: a read-only combo box is 'readonly', everything else (editable boxes, check boxes) 'normal'."""
    return 'readonly' if isinstance(widget, Combobox) and not widget.isEditable() else 'normal'


# ---------------------------------------------------------------------------------------------------------------------------------------
# the connection form in the drawer
# ---------------------------------------------------------------------------------------------------------------------------------------
class _FitHeight(QObject):
    """A wrapped QLabel is laid out with the height of its un-wrapped hint when it sits in a scroll area (the drawer) or under a table that takes the free height (the
    detail text), so a long text is cut off.  This keeps the label's minimum height equal to its height-for-width at the width it actually has (the parent then
    grows by the missing lines); `refit()` is also called when the text changes."""

    def __init__(self, label, var=None):
        super().__init__(label)
        self.label = label
        label.installEventFilter(self)
        if var is not None:
            var.trace_add('write', lambda *_: QTimer.singleShot(0, self.refit))

    def refit(self):
        lab = self.label
        try:
            w = lab.width()
            if w > 20:
                h = lab.heightForWidth(w)
                if h > 0 and h != lab.minimumHeight():
                    lab.setMinimumHeight(h)
        except RuntimeError:
            pass                                                   # the label went away (the window closed before the queued call ran)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self.refit)
        return False


def fit_wrapped(label, var=None):
    """Make a word-wrapped label show all its lines (see _FitHeight); `var` = the variable that feeds its text.  Returns the label."""
    _FitHeight(label, var)
    return label


class DetailBox(QScrollArea):
    """The detail text and the source note under a results table.  A wrapped note of five or six lines used to push the window's minimum height past the size the
    window was given (the fixed 1000 x 640 minimum), and the text then painted over the last table rows.  Here the box asks for the height of its text but can give
    up to what is above three lines (a scroll bar appears), so the table keeps its rows and nothing overlaps."""
    MIN_LINES = 3

    def __init__(self, content):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(content)
        content.installEventFilter(self)
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        self.setBackgroundRole(QPalette.ColorRole.NoRole)
        self.viewport().setBackgroundRole(QPalette.ColorRole.NoRole)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _line(self):
        return self.fontMetrics().lineSpacing()

    def _need(self):
        """The height the text needs at the width it has (a wrapped label's own size hint is that of the un-wrapped text)."""
        c = self.widget()
        lay = c.layout()
        w = max(self.viewport().width(), 300)
        if lay is not None and lay.hasHeightForWidth():
            return lay.totalHeightForWidth(w)
        return c.sizeHint().height()

    def sizeHint(self):
        return QSize(self.widget().sizeHint().width(), self._need() + 2)

    def minimumSizeHint(self):
        return QSize(100, min(self._need(), self.MIN_LINES * self._line() + 8) + 2)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            QTimer.singleShot(0, self._geometry)
        return super().eventFilter(obj, ev)

    def _geometry(self):
        try:
            self.updateGeometry()
        except RuntimeError:
            pass                                                   # the box went away


class ShareColumns(QObject):
    """Keeps a results table readable at every width: in the small window the merged Limits column gets the width its text needs (the Description takes what is
    left), in a wide window the width beyond `base` is shared between the numeric columns instead of one huge Description column (same idea as the Manager list)."""
    NARROW = 900
    WEIGHTS = {'nominal': .16, 'low': .16, 'high': .16, 'limits': .0, 'found': .16, 'error': .14, 'left': .16, 'result': .06}

    def __init__(self, tree, shell, base=None, compact=None):
        super().__init__(tree)
        self.tree, self.shell = tree, shell
        self.base_over = dict(base or {})
        self.compact_widths = {'limits': 220, 'found': 104, 'left': 104}
        self.compact_widths.update(compact or {})
        tree.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        try:
            t = self.tree
            width = t.viewport().width()
            compact = bool(self.shell._compact) or width < self.NARROW           # a narrow table (a window the small-window rule has not folded yet) also gets the merged Limits column
            full, small = getattr(t, '_cols_full', None), getattr(t, '_cols_small', None)
            if full and small:
                t.configure(displaycolumns=small if compact else full)
            keys = [k for k in t._keys if not t.isColumnHidden(t._keys.index(k))]
            if compact:
                for k, w in self.compact_widths.items():
                    t.column(k, width=w)
                return
            base = {'n': 44, 'nominal': 96, 'low': 92, 'high': 92, 'found': 100, 'error': 90, 'left': 100, 'result': 90}
            base.update(self.base_over)
            fixed = sum(base.get(k, 0) for k in keys)
            if width - fixed < 340:                               # a narrow table: the number columns give up width (down to a floor) so the Description keeps ~340 px
                floor = {k: min(base[k], max(40, int(base[k] * .9))) for k in base}
                room = sum(base[k] - floor[k] for k in keys if k in base)
                deficit = min(340 - (width - fixed), room)
                for k in keys:
                    if k in base:
                        t.column(k, width=int(base[k] - deficit * (base[k] - floor[k]) / max(room, 1)))
                return
            extra = max(0, width - fixed - 420)                   # the Description keeps at least 420 px
            share = sum(self.WEIGHTS.get(k, 0) for k in keys if k in base) or 1
            for k in keys:
                if k in base:
                    t.column(k, width=int(base[k] + extra * 0.55 * self.WEIGHTS.get(k, 0) / share))
        except (RuntimeError, ValueError, AttributeError):
            pass                                                   # the table went away


class Form:
    """Rows of the connection drawer (shell.drawer_body, a grid whose column 1 stretches), in the order the Tk view grids them.

        f = Form(sh.drawer_body)
        f.row('Limits to apply', combo)                    label | widget (left aligned at its own width)
        f.row('Address', combo, fill=True)                 label | widget filling the column (Tk sticky='ew')
        f.wide(check_button)                               one widget across both columns
        f.note('muted text')                               wrapped muted note across both columns
        f.note('text', column=1)                           the note under the widget column
        f.rule()                                           thin separator
        f.combo(var, values, width, state='readonly', command=None)         a combo box bound to a variable
    """

    def __init__(self, body):
        self.body = body
        self.grid = body.layout()
        self.r = 0

    def combo(self, var, values=(), width=None, state='readonly', command=None):
        return H.combobox(None, var, values, width=width, state=state, command=command)

    def row(self, text, widget, fill=False, label=None):
        lab = label or H.label_(None, text)
        self.grid.addWidget(lab, self.r, 0, VCENTER | Qt.AlignmentFlag.AlignLeft)
        if fill:
            self.grid.addWidget(widget, self.r, 1)
        else:
            self.grid.addWidget(widget, self.r, 1, LEFT)
        self.r += 1
        return widget

    def wide(self, widget):
        self.grid.addWidget(widget, self.r, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self.r += 1
        return widget

    def note(self, text, column=0):
        lab = fit_wrapped(H.label_(None, text, 'Muted.TLabel', wraplength=DRAWER_WRAP))
        lab.setContentsMargins(0, 2, 0, 4)
        if column == 0:
            self.grid.addWidget(lab, self.r, 0, 1, 2, Qt.AlignmentFlag.AlignTop)
        else:
            self.grid.addWidget(lab, self.r, 1, Qt.AlignmentFlag.AlignTop)
        self.r += 1
        return lab

    def rule(self):
        self.grid.addWidget(W.rule(), self.r, 0, 1, 2)
        self.r += 1


def calibrator_note(form, offer, widgets=()):
    """The calibrator-model note under the picker (calibrator_fit.attach_note, the toolkit's own widget) at the form's next row, wrapped like the other notes."""
    import calibrator_fit
    lab = calibrator_fit.attach_note(form.body, offer, H, widgets=widgets, row=form.r)
    form.r += 1
    return fit_wrapped(lab)


def drawer_footer(sh, *buttons):
    """Tk packed the footer buttons side='left'; the Qt footer has a leading stretch, so they are inserted before it, in order."""
    lay = sh.drawer_footer_layout
    for i, b in enumerate(buttons):
        lay.insertWidget(i, b)
    return buttons


def find_and_test(sh, owner, find_text, find_command):
    """The two drawer buttons every window has: [find_text] and [Test connections] (accent).  Stored as owner.btn_find / owner.btn_test."""
    owner.btn_find = H.button(None, find_text, find_command)
    owner.btn_test = H.button(None, 'Test connections', owner.test_connections, style='Accent.TButton')
    drawer_footer(sh, owner.btn_find, owner.btn_test)
    return owner.btn_find, owner.btn_test


# ---------------------------------------------------------------------------------------------------------------------------------------
# the action bar and the results area
# ---------------------------------------------------------------------------------------------------------------------------------------
def action_bar(self, sh, *, manual=False, excel=False):
    """The action buttons, in the Tk order: Run All Pending, Run Shown Section, Rerun Selected, [Enter reading manually], Stop | Export, [Excel], Load, Save."""
    self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
    self.btn_rerun_from = sh.add_action('Rerun From Selected', self.rerun_from, short='From here')
    if manual:
        self.mo_add_button(sh)                              # 'Enter reading manually' (also on the point list's right-click menu)
    self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
    if excel:
        sh.add_action('Export Excel (.xlsx)', self.export_excel, side='right', short='Excel')
    self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
    sh.add_action('Save progress', self.save, side='right', short='Save')
    self.pm_live_attach(sh)                                 # 'Edit procedure' / 'Edit point': the editor inside this window, usable during a run


def build_results(self, sh, source_note, detail_wrap=1000):
    """The body of the window: `Test points ... Show [status]`, the results table, then the detail text and the source note under it (the Tk `side='bottom'` frame
    is simply added after the table).  Sets self.tree and returns (tree, filter_row)."""
    body = sh.content
    lay = body.layout()
    filt = H.frame(None, 'h', spacing=8)
    fl = filt.layout()
    fl.addWidget(H.label_(None, 'Test points', 'Bold.TLabel'))
    fl.addStretch(1)
    picker = sh.build_section_picker(filt)                  # hidden until the window is small (the sidebar folds into this drop-down)
    fl.addWidget(H.label_(None, 'Show', 'Muted.TLabel'))
    status = H.combobox(None, self.show_status, datamode.STATUS_FILTERS, width=14, state='readonly', command=self.refresh)
    status.setAccessibleName('Show')
    fl.addWidget(status)
    self.status_filter = status
    lay.addWidget(filt)
    lay.addSpacing(6)
    self.tree = S.results_table(self, body)
    S.small_window(self, self.tree, filt, picker=picker)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    # owner 2026-10-27: no detail text and no source note under the table (the setup is in the cable-change dialog, the flags are in the report): the table takes the room.
    # The engine still fills self.detail on a selection; nothing shows it.
    prev = sh.layout_hook

    def hook(compact):
        if prev:
            prev(compact)
        QTimer.singleShot(0, share.apply)
    share = ShareColumns(self.tree, sh)
    sh.layout_hook = hook
    return self.tree, filt


def share_columns(tree, sh, compact=None, **base):
    """Install ShareColumns on a results table and re-apply it whenever the shell switches between the full and the small-window column sets."""
    share = ShareColumns(tree, sh, base, compact)
    prev = sh.layout_hook

    def hook(compact):
        if prev:
            prev(compact)
        QTimer.singleShot(0, share.apply)
    sh.layout_hook = hook
    return share


def notice(sh, self, hardware_text, demo_text=None, demo_title=None):
    """The window's notice: the demo banner in demo mode (self.banner_text() with virtualbench.BANNER_TITLE, or the given text and title), else the hardware note."""
    import virtualbench
    if self.demo:
        sh.notice(demo_text if demo_text is not None else self.banner_text(), 'warn', title=demo_title if demo_title is not None else virtualbench.BANNER_TITLE)
    else:
        sh.notice(hardware_text, 'info')


# ---------------------------------------------------------------------------------------------------------------------------------------
# results table and address boxes: the table_* contract (the exact statements the engines made on self.tree / self.dmm_entry)
# ---------------------------------------------------------------------------------------------------------------------------------------
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
    self.tree.set_all(list(rows), keep=keep[:1] if keep else ())


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)
