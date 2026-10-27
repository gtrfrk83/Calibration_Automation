"""Keysight 34410A / 34411A performance verification: the Qt window code (port of the removed Tk view agilent34410a_view_tk.py: same functions, same widgets as attributes of the App, same
texts, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('agilent34410a_view')`, which resolves to `agilent34410a_view_qt` under the Qt port.  Every function takes the
engine's App as `self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (the first statements of the engine's former App.__init__)."""
    import agilent34410a_verification as E
    B.setup_window(self, f'Keysight {E.MODEL} | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statement of the engine's former App.__init__)."""
    B.finish_window(self)


def build_ui(self):
    import agilent34410a_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    INTERFACES, MODEL, PERIODS, POINTS, SPEC = E.INTERFACES, E.MODEL, E.PERIODS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = S.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                              f'Test points from the 34410A/11A/L4411A Service Guide, pp. 68-87  |  {len(POINTS)} points in the spec  |  GPIB or USB',
                              demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program asks you to confirm the warm-up and environment, the wiring before every new setup and before any high-voltage point. Stay at the bench '
                       'while a run is in progress.')

    # settings and connections live in the slide-in drawer
    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 20, command=self.on_period))
    self.set_combo = f.row('Test set', f.combo(self.test_set, ['Full verification', 'Quick check (Q points only)'], 26, command=self.refresh))
    self.opt_check = f.wide(H.checkbutton(None, 'Include the optional tests (extra AC volts, AC current, capacitance)', self.include_optional, self.refresh))
    f.rule()
    self.iface_combo = f.row(f'{MODEL} interface', f.combo(self.interface, list(INTERFACES), 10, command=self.on_interface))
    self.dmm_entry = f.row(f'{MODEL} address / resource', f.combo(self.dmm_addr, (), 34, state='normal'), fill=True)
    f.note(f'GPIB: the {MODEL} factory address is 22 (UTILITY MENU > REMOTE I/O > GPIB). USB: nothing to set on the meter; the resource is '
           'USB0::<mfgID>::<modID>::<serial>::INSTR (UTILITY MENU > REMOTE I/O > USB > USB ID, or Find instruments). ' + f'The {MODEL} has no RS-232. '
           + 'The IDs in the example are not verified for your bench.')
    calbox = f.row('Calibrator', f.combo(self.cal_model, self.cal_choices(), 14))
    B.calibrator_note(f, self.cal_offer, widgets=(calbox,))
    self.cal_entry = f.row('Calibrator port', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Calibrator baud', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find),
                   [(c, B.idle_state(c)) for c in (self.period_combo, self.set_combo, self.opt_check)])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry).configure(values=values)
