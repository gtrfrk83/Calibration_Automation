"""Keithley DMM6500 performance verification: the Qt window code (modelled on k2000_view_qt.py: same functions, same widgets as attributes of the App, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('dmm6500_view')`, which resolves to `dmm6500_view_qt` under the Qt port.  Every function takes the engine's App as
`self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
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
    B.notice(sh, self, 'The program asks you to confirm the warm-up and environment, the wiring before every new setup and before any high-voltage point. Stay at the bench '
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
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm'), reference meter ('ref') or calibrator port ('cal') box."""
    {'dmm': self.dmm_entry, 'ref': self.ref_entry, 'cal': self.cal_entry}[which].configure(values=values)
