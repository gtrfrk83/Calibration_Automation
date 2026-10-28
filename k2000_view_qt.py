"""Keithley Model 2000 performance verification: the Qt window code (port of the removed Tk view k2000_view_tk.py: same functions, same widgets as attributes of the App, same texts, same
busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('k2000_view')`, which resolves to `k2000_view_qt` under the Qt port.  Every function takes the engine's App as
`self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    B.setup_window(self, 'Keithley 2000 | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    B.finish_window(self)


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find), [(self.period_combo, 'readonly')])


def build_ui(self):
    import keithley2000_verification as E                      # the engine's module state (configure(model) can rebind it), read at call time
    CAL_INTERFACES, FLOW, INTERFACES, PERIODS, POINTS, SPEC, drivers = E.CAL_INTERFACES, E.FLOW, E.INTERFACES, E.PERIODS, E.POINTS, E.SPEC, E.drivers
    root = self.root
    sh = self.shell = S.Shell(root, 'Keithley 2000  -  Performance Verification',
                              f'Test points from the Model 2000 Calibration Manual, Tables 1-2 to 1-6 (pp. 1-7 to 1-13)  |  {len(POINTS)} points in the spec  |  '
                              'GPIB or RS-232', demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
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
    f.rule()
    f.row('2000 interface', f.combo(self.interface, list(INTERFACES), 10))
    self.dmm_entry = f.row('2000 address / port', f.combo(self.dmm_addr, (), 34, state='normal'), fill=True)
    for text, var, values, width in (('RS-232 baud', self.dmm_baud, ['19200', '9600', '4800', '2400', '1200', '600', '300'], 9),
                                     ('RS-232 TX TERM', self.dmm_term, list(drivers.keithley_2000.TX_TERM), 9),
                                     ('RS-232 flow control', self.dmm_flow, list(FLOW), 12)):
        f.row(text, f.combo(var, values, width))
    f.note('GPIB: the 2000 factory address is 16 (CONFIG > GPIB). RS-232: set the same baud and TX TERM on the meter (CONFIG > RS-232) and the SCPI '
           'language (the RS-232 interface supports SCPI only). 8 data bits, no parity, 1 stop bit.')
    calbox = f.row('Calibrator', f.combo(self.cal_model, self.cal_choices(), 14))
    B.calibrator_note(f, self.cal_offer, widgets=(calbox,))
    f.row('Calibrator interface', f.combo(self.cal_interface, list(CAL_INTERFACES), 10, command=self.on_cal_interface))
    self.cal_entry = f.row('Calibrator port / address', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Calibrator baud (RS-232 only)', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh, manual=True)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry).configure(values=values)
