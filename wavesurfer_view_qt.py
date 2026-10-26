"""WaveSurfer 4104HD verification: the Qt window code (twin of wavesurfer_view_tk.py: same function names, same attributes on the App).

The engine reaches this module through `ui_port.ui.view('wavesurfer_view')`, which resolves to `wavesurfer_view_qt` under the Qt UiPort.  Every function that works on the
window takes the engine's App as `self` and keeps its widgets as attributes of it (`self.tree`, `self.dc_tree`, `self.btn_run`, ... the shared mixins use them too).
Nothing here decides anything about a calibration.

The window is the Qt shell (qtui.shell.Shell: header, Instrument ID / As Found | As Left strip, section sidebar, the single results table, action bar, status bar, the
connections drawer).  As in Tk the notebook of the five measurement sections (+ RMS noise and the two others) is built and kept but never shown: it holds each section's
settings, tables, progress bars and buttons, which the engine fills and enables / disables (wavesurfer_qt_sections.py).  The Test settings dialog is
wavesurfer_qt_settings.py, the shared pieces wavesurfer_qt_common.py (this file stays small so each stays well under 1,500 lines).

Differences from Tk (look only): Qt shell widgets and dark theme; Esc closes the connections drawer; the Test settings form scrolls on a short screen; the formula warning
on the (hidden) RMS page is a warning strip.  Threading: the engine's worker threads still talk to the window only through its own event queue, which `process_events`
(a ui_port.after tick on the UI thread) drains; nothing in this module is called from a worker.
"""
from __future__ import annotations

import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget, QWidget

import datamode
import qtui.shell_helpers as H
import suite_info
from qtui.bench_view import DetailBox, fit_wrapped, share_columns
from qtui.screens import help_menu
from qtui.shell import Shell, results_table, small_window
from ui_port import ui as port

import wavesurfer_qt_common as K
import wavesurfer_qt_sections as S
import wavesurfer_qt_settings as T

_LEFT = Qt.AlignmentFlag.AlignLeft

# the functions the engine calls through the view that are plain re-exports of the helpers
selection, children, row_index, select, select_and_show, set_grid = K.selection, K.children, K.row_index, K.select, K.select_and_show, K.set_grid
make_ui, show_dcv, show_impedance, show_offset, show_bandwidth, show_timebase, show_trigger = (
    S.make_ui, S.show_dcv, S.show_impedance, S.show_offset, S.show_bandwidth, S.show_timebase, S.show_trigger)
show_settings_dialog = T.show_settings_dialog


# ---- the window as a whole -----------------------------------------------------------------------------------------------------------------------------
def window_gone():
    """The exception the periodic ticks stop on: a widget of a closed window (Tk: tk.TclError)."""
    return K.WindowGone


def enable_hidpi():
    """Before the application exists (the statement `port.view(VIEW).enable_hidpi()` of the engine's __main__)."""
    H.enable_hidpi()


def setup_window(self):
    """Theme, title and size of the main window (the first statements of the engine's former App.__init__)."""
    root = self.root
    H.apply_theme(root)
    root.setWindowTitle('WaveSurfer 4104HD | Calibration Verification v56')
    H.fit_window(root, 1300, 880, min_w=900, min_h=640)


def create_shell(self):
    """The shell, the scope chip and the notebook that holds each section (the statements of the engine's former App.__init__)."""
    self.shell = Shell(self.root, 'WaveSurfer 4104HD  -  Calibration Verification',
                       'Teledyne LeCroy  |  USBTMC / PyVISA  |  RMS noise, DC voltage, input impedance, offset, bandwidth, time base and trigger level',
                       demo='--demo' in sys.argv, on_section=self._pick_function, version='v56')
    self.conn_pill = self.shell.add_chip('Scope: not connected', 'neutral')
    # The measurement sections are built inside a notebook that is never shown: it holds each section's settings, checkpoints and workers.  What the technician sees is
    # the single results table (build_unified), filterable by function.
    self.tabs = QTabWidget(self.shell.widget)
    self.tabs.hide()
    self.rms_tab = QWidget()
    self.tabs.addTab(self.rms_tab, 'RMS Noise')


_TRAILING_VERSION = re.compile(r'\s*[|\-]?\s*\bv\d+(\.\d+)*(\s+Beta\s*\d*)?\s*$')          # branding.tidy_title's pattern (branding.py imports Tk)


def polish(self):
    """Window dressing the Tk build gets from ui.apply_theme -> branding.dress: the suite's title pattern ('Calibration Suite  |  <title>  |  <version>') and the Help menu."""
    root = self.root
    H.polish(root)
    title = root.windowTitle()
    if title and not title.startswith(suite_info.NAME):
        root.setWindowTitle(suite_info.window_title(_TRAILING_VERSION.sub('', title).strip()))
    help_menu.dress(root)


# ---- statements the engine makes on its widgets ------------------------------------------------------------------------------------------------------
def set_state(widget, state):
    """`widget.configure(state=state)`: 'disabled' | 'normal' | 'readonly' on a button, check box, radio button, combo box or entry."""
    K.need(widget)
    widget.setEnabled(state != 'disabled')
    if hasattr(widget, 'setReadOnly') and state in ('readonly', 'normal'):
        widget.setReadOnly(state == 'readonly')


def set_value(bar, value):
    K.need(bar).setValue(max(bar.minimum(), min(bar.maximum(), int(round(value)))))


def set_maximum(bar, value):
    K.need(bar).setMaximum(max(1, int(value)))


def tab_open(self, name):
    """`getattr(self, name, None) and self.<name>.winfo_exists()`: the section's tab has been built and still exists."""
    return K.alive(getattr(self, name, None))


def set_tab_text(self, tab, text):
    K.need(self.tabs)
    i = self.tabs.indexOf(K.need(tab))
    if i >= 0 and self.tabs.tabText(i) != text:
        self.tabs.setTabText(i, text)


def set_chip(self, text, kind):
    K.need(self.conn_pill).set(text, kind)


def show_unified(self, items, allp, fmap, lmap, total, passed, failed):
    """Fill the one results table, the progress ring and the section list (the body of the `if force or sig != self._shown` block of refresh_unified)."""
    K.need(self.utree)
    keep = self.utree.selection()
    self.utree.set_all(items, keep=keep)
    if self.is_left:                                    # As Left: progress is about the points that failed As Found
        redo = [k for k, e in fmap.items() if e['result'] == 'FAIL']
        done = [k for k in redo if lmap.get(k) and lmap[k]['done']]
        self.summary.set_rerun(len(redo), len(done), sum(lmap[k]['result'] == 'PASS' for k in done), sum(lmap[k]['result'] == 'FAIL' for k in done))
    else:
        self.summary.update_counts(total, passed, failed)
    rows = []
    for kind, name in self.FUNCS:
        es = [e for e in allp if e['kind'] == kind]
        rows.append((name, sum(e['result'] == 'PASS' for e in es), sum(e['result'] == 'FAIL' for e in es), len(es)))
    self.shell.set_sections(rows)


# ---- the main window ---------------------------------------------------------------------------------------------------------------------------------
class _After:
    """`root.after(ms, fn)` / `after_cancel(handle)` for helpers written for a Tk root (labregistry.attach): the UiPort's timers."""

    def __init__(self, win):
        self.win = win

    def after(self, ms, fn, *args):
        return port.after(self.win, ms, fn, *args)

    def after_cancel(self, handle):
        cancel = getattr(port, 'cancel_after', None)
        if cancel is not None:
            cancel(self.win, handle)


def build_unified(self):
    sh = self.shell
    self.msg = sh.status_var
    self.msg.set('Step 1: enter the Instrument ID. Step 2: check the connections. Step 3: Run Pending.')
    self.show_function = port.var('All functions')
    self.show_status = port.var('All points')
    self.chain = []
    self._idle = 0
    self._shown = None
    self._last_status = {}
    # strip: identity, As Found | As Left, progress ring
    sh.build_identity(self.instrument_id, self.serial)
    for entry in (sh.id_entry,):
        entry.editingFinished.connect(lambda: self.sync_asset())           # leaving the entry or Return (Tk: <FocusOut> and <Return>)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if '--demo' in sys.argv:
        sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')

    # connections drawer
    g = sh.drawer_body.layout()
    g.addWidget(H.label_(None, 'Model'), 0, 0)
    g.addWidget(H.label_(None, 'Teledyne LeCroy WaveSurfer 4104HD', 'Bold.TLabel'), 0, 1)
    g.addWidget(H.separator(), 1, 0, 1, 2)
    g.addWidget(H.label_(None, 'Scope VISA address'), 2, 0)
    visa = H.entry(None, self.visa_address, width=34)
    visa.setCursorPosition(0)                                  # show the start of a long VISA address, not its end
    g.addWidget(visa, 2, 1)
    self.btn_scope = H.button(None, 'Test scope', self.test_connection)
    g.addWidget(self.btn_scope, 3, 1, alignment=_LEFT)
    g.addWidget(H.label_(None, 'Calibrator'), 4, 0)
    g.addWidget(H.combobox(None, self.fluke_model, self.CAL_CHOICES, width=16, state='readonly', command=self.on_cal_model), 4, 1, alignment=_LEFT)
    g.addWidget(H.label_(None, 'Calibrator VISA'), 5, 0)
    g.addWidget(H.entry(None, self.fluke_address, width=34), 5, 1)
    g.addWidget(H.label_(None, 'Calibrator baud'), 6, 0)
    baud = H.entry(None, self.fluke_baud, width=10)
    baud.setFixedWidth(110)
    g.addWidget(baud, 6, 1, alignment=_LEFT)
    g.addWidget(H.button(None, 'Test calibrator', self.test_fluke), 7, 1, alignment=_LEFT)
    g.addWidget(H.separator(), 8, 0, 1, 2)
    g.addWidget(H.button(None, 'Test settings...', self.show_settings_dialog), 9, 0, 1, 2, alignment=_LEFT)
    g.addWidget(H.label_(None, 'Settle times, samples, channels and limits are in Test settings. Calibrator output stays in STANDBY between points.', 'Muted.TLabel', wraplength=340),
                10, 0, 1, 2)

    # action bar
    self.btn_run = sh.add_action('▶  Run All Pending', self.run_pending, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun_selected, short='Rerun')
    self.btn_rerun_from = sh.add_action('Rerun From Selected', self.rerun_from_selected, short='From here')
    self.btn_stop = sh.add_action('■  Stop', self.stop_all, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf_report, side='right', short='PDF')
    sh.add_action('Export Excel (.xlsx)', self.export_professional_excel, side='right', short='Excel')
    self.btn_clear = sh.add_action('Clear function results', self.clear_function, side='right', short='Clear')
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well

    body = sh.content
    bl = body.layout()
    filt = H.frame(None, 'h', spacing=8)
    fl = filt.layout()
    fl.addWidget(H.label_(None, 'Test points', 'Bold.TLabel'))
    fl.addStretch(1)
    fl.addWidget(H.label_(None, 'Show', 'Muted.TLabel'))
    c2 = H.combobox(None, self.show_status, datamode.STATUS_FILTERS, width=14, state='readonly', command=lambda: self.refresh_unified(force=True))
    c2.setAccessibleName('Show')
    fl.addWidget(c2)
    bl.addWidget(filt)
    bl.addSpacing(6)
    self.utree = results_table(self, body, name_width=380, error=False)
    small_window(self, self.utree, filt)
    share_columns(self.utree, sh)
    self.detail = port.var('Select a test point to see its limits and setup.')
    bl.addSpacing(8)
    info = H.frame(None, 'v', spacing=4)
    info.layout().addWidget(fit_wrapped(H.label_(None, '', 'Muted.TLabel', textvariable=self.detail, wraplength=1000), self.detail))
    bl.addWidget(DetailBox(info))
    self.utree.bind('<<TreeviewSelect>>', self.on_unified_select)
    self.refresh_unified(force=True)
    port.after(self.root, 500, self._unified_tick)
    import labregistry
    labregistry.attach(_After(self.root), self.instrument_id, self.serial, self.msg.set)
    self.sync_asset()                       # --asset <ID> from the Manager



def dialog_open(self):
    """Any modal window open over the main window (Tk: a Toplevel child of the root)."""
    if QApplication.activeModalWidget() is not None:
        return True
    return any(isinstance(w, QDialog) and w.isVisible() for w in self.root.findChildren(QDialog))


def toggle_settings(self):
    self.config_frame.setVisible(bool(self.show_settings.get()))
