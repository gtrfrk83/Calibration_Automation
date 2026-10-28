"""Keysight Truevolt (34460A / 34461A / 34465A / 34470A) performance verification: the Qt window code (port of the removed Tk view truevolt_view_tk.py: same functions, same widgets as
attributes of the App, same texts, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('truevolt_view')`, which resolves to `truevolt_view_qt` under the Qt port.  Every function takes the
engine's App as `self`.  The parts the bench windows share (window chrome, the results area, the drawer form, the table_* helpers) are qtui/bench_view.py.
Nothing here decides anything about a calibration.
"""
import virtualbench  # noqa: F401  (the banner text comes from the App)

from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    import truevolt_verification as E
    B.setup_window(self, f'Keysight {E.MODEL} | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    B.finish_window(self)


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find),
                   [(c, B.idle_state(c)) for c in (self.period_combo, self.set_combo, self.opt_check)])


def build_ui(self):
    import truevolt_verification as E                      # the engine's module state (configure(model) can rebind it), read at call time
    MODEL, PERIODS, POINTS, SPEC = E.MODEL, E.PERIODS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = S.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                              f'Test points from the Keysight Truevolt Operating and Service Guide, pp. {SPEC["source"]["pages"].split(" ")[0]}  |  {len(POINTS)} points in the spec',
                              demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.')

    # settings and connections live in the slide-in drawer
    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 20, command=self.on_period))
    self.set_combo = f.row('Test set', f.combo(self.test_set, ['Full verification', 'Quick check (Q points only)'], 26, command=self.refresh))
    self.opt_check = f.wide(H.checkbutton(None, 'Include optional capacitance test', self.include_optional, self.refresh))
    f.rule()
    self.dmm_entry = f.row(f'{MODEL} address', f.combo(self.dmm_addr, (), 34, state='normal'), fill=True)
    self.cal_entry = f.row('Fluke 5560A', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Baud (5560A)', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    f.note('Examples: USB0::0x2A8D::0x0101::<serial>::INSTR   GPIB0::22::INSTR   TCPIP0::192.168.1.20::INSTR   COM9')
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh, manual=True)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry).configure(values=values)
