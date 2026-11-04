"""Keithley DMM6500 performance verification: the Qt window code (modelled on k2000_view_qt.py: same functions, same widgets as attributes of the App, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('dmm6500_view')`, which resolves to `dmm6500_view_qt` under the Qt port.  Every function takes the engine's App as
`self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
import math

from PySide6.QtWidgets import QProgressBar

from qtui import bench_view as B
from qtui import shell as S
from qtui.screens import common
from qtui.widgets import ModalDialog, label
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window."""
    B.setup_window(self, 'Keithley DMM6500 | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's __init__)."""
    B.finish_window(self)


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find), [(self.period_combo, 'readonly')])


def build_ui(self):
    import dmm6500_verification as E                           # the engine's module state, read at call time
    CAL_INTERFACES, INTERFACES, PERIODS, POINTS, SPEC, ZERO_CHOICES = E.CAL_INTERFACES, E.INTERFACES, E.PERIODS, E.POINTS, E.SPEC, E.ZERO_CHOICES
    root = self.root
    sh = self.shell = S.Shell(root, 'Keithley DMM6500  -  Performance Verification',
                              f'Test points from the DMM6500 Calibration and Adjustment Manual, section 2 (pp. 2-6 to 2-48)  |  {len(POINTS)} points in the spec  |  '
                              'USB, LAN or GPIB  |  simulated bench only: no command verified on a real meter', demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program asks you to confirm the warm-up and environment, the wiring before every new setup, and the high-voltage hazard once per run. Stay at the bench '
                       'while a run is in progress. No DMM6500 command has been verified on a real meter yet.')

    # settings and connections live in the slide-in drawer
    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 20, command=self.on_period))
    f.row('4-wire short zero checks', f.combo(self.zero_checks, list(ZERO_CHOICES), 10, command=lambda *_: self.refresh()))
    f.rule()
    f.row('DMM6500 interface', f.combo(self.interface, list(INTERFACES), 10))
    self.dmm_entry = f.row('DMM6500 address', f.combo(self.dmm_addr, (), 44, state='normal'), fill=True)
    f.note('USB: pick the resource from Find instruments (USB0::0x05E6::0x6500::<serial>::INSTR). LAN: the IP address or host name. GPIB needs the optional KTTI-GPIB '
           'accessory. The meter must be on the SCPI command set (MENU > System > Settings > Command Set).')
    self.ref_entry = f.row('Reference meter (3458A) GPIB', f.combo(self.ref_addr, (), 34, state='normal'), fill=True)
    f.note('Optional. With a reference meter the 1 ohm / 10 ohm and DC current (10 uA to 10 mA, 10 A) limits are centred on its reading, as the manual describes; without one they are '
           'centred on the calibrator setting. Leave blank for none.')
    calbox = f.row('Calibrator', f.combo(self.cal_model, self.cal_choices(), 14))
    B.calibrator_note(f, self.cal_offer57, widgets=(calbox,))
    f.row('Calibrator interface', f.combo(self.cal_interface, list(CAL_INTERFACES), 10, command=self.on_cal_interface))
    self.cal_entry = f.row('Calibrator port / address', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Calibrator baud (RS-232 only)', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh, manual=True)
    B.build_results(self, sh, SPEC['source']['note'])
    enable_grid_entry(self)
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm'), reference meter ('ref') or calibrator port ('cal') box."""
    {'dmm': self.dmm_entry, 'ref': self.ref_entry, 'cal': self.cal_entry}[which].configure(values=values)


class Countdown(ModalDialog):
    """The settling countdown: the time left in large type, a progress bar and what the program is waiting for. Not modal (the table stays visible), no close button: it closes itself when the wait ends."""

    def __init__(self, parent, what):
        super().__init__(parent, 'Settling', width=520, modal=False, close_button=False)
        self.title_label.hide()
        self.what_label = label(what, 'h2', wrap=True)
        self.time_label = label('', 'title')
        self.time_label.setStyleSheet('font-size: 64px; font-weight: 700;')      # large enough to read from across the bench (the theme's role stylesheet beats a QFont)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.hint_label = label('Do not touch the leads, the calibrator or the meter. The reading is taken automatically when the timer reaches 0:00.', 'hint', wrap=True)
        for w in (self.what_label, self.time_label, self.bar, self.hint_label):
            self.body.addWidget(w)

    def update_time(self, what, total, left):
        self.what_label.setText(what)
        mins, secs = divmod(int(math.ceil(left)), 60)
        self.time_label.setText(f'{mins}:{secs:02d}')
        self.bar.setRange(0, max(int(total), 1))
        self.bar.setValue(int(max(0, total - left)))


def countdown(self, what, total, left):
    """The settling countdown (IO.wait: waits of 30 s or more, the 5-minute ones). UI thread. left <= 0 closes it."""
    dlg = getattr(self, '_countdown', None)
    if left <= 0:
        if dlg is not None and common.alive(dlg):
            dlg.close()
            dlg.deleteLater()
        self._countdown = None
        return
    if dlg is None or not common.alive(dlg):
        dlg = self._countdown = Countdown(common.qparent(self.root), what)
        dlg.show()
    dlg.update_time(what, total, left)


def enable_grid_entry(self):
    """Capacitance readings can be typed straight into the As Found / As Left cell of the table (the cell of the collecting mode): select it and type, or double-click / F2. The engine decides
    (grid_entry_state) and records (grid_enter); every other cell stays read-only."""
    from PySide6.QtWidgets import QAbstractItemView
    tree = self.tree
    model = tree.source_model
    keys = tree._keys
    for key in ('found', 'left'):
        col = model.columns[keys.index(key)]
        col.editable = lambda row, _k=key: self.grid_entry_state(row.iid, _k)[0]
        col.tooltip = lambda row, _k=key: 'Type the capacitance reading here (select the cell and type, or double-click)' if self.grid_entry_state(row.iid, _k)[0] else ''
    tree.set_edit_hook(lambda row, key, old, new: _grid_hook(self, row.iid, key, new))
    tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.AnyKeyPressed)


def _grid_hook(self, iid, key, text):
    """The edit hook of the table: the engine records the reading; this then opens the next capacitance row's cell (Enter = next line) or, for an unusable text, the same cell again.
    Always returns False so the table never keeps the raw typed text: the row is redrawn from the recorded result."""
    from PySide6.QtCore import QTimer
    outcome = self.grid_enter(iid, key, str(text))
    if outcome == 'recorded':
        QTimer.singleShot(0, lambda: open_grid_cell(self, iid, key, after=True))
    elif outcome == 'retry':
        QTimer.singleShot(0, lambda: open_grid_cell(self, iid, key, after=False))
    return False


def open_grid_cell(self, iid, key, after):
    """Select the `key` cell of the next (after=True) or the same point and open it for typing. The next one is the next row in the table's own order (sorted / filtered as shown) that takes typing."""
    tree = self.tree
    rows = tree.rows()
    iids = [r.iid for r in rows]
    if iid not in iids:
        return
    at = iids.index(iid)
    for i in (range(at + 1, len(rows)) if after else (at,)):
        if self.grid_entry_state(rows[i].iid, key)[0]:
            index = tree.proxy.index(i, tree._keys.index(key))
            tree.setCurrentIndex(index)
            tree.scrollTo(index)
            tree.edit(index)
            return
