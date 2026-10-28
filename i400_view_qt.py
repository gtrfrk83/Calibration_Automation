"""Fluke i400 clamp performance verification: the Qt window code (port of the removed Tk view i400_view_tk.py: same functions, same widgets as attributes of the App, same
texts, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('i400_view')`, which resolves to `i400_view_qt` under the Qt port.  Every function takes the
engine's App as `self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (the first statements of the engine's former App.__init__)."""
    import i400_verification as E
    B.setup_window(self, f'Fluke {E.MODEL} | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statement of the engine's former App.__init__)."""
    B.finish_window(self)


def build_ui(self):
    import i400_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    INTERFACES, MODEL, PERIODS, POINTS, SPEC = E.INTERFACES, E.MODEL, E.PERIODS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = S.Shell(root, f'Fluke {MODEL}  -  Performance Verification',
                              f'Test points from the i400 Calibration Information, Table 3 (p. 6)  |  {len(POINTS)} points in the spec  |  reading multimeter on GPIB or USB',
                              demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program asks you to confirm the clamp condition, the multimeter pre-calibration wiring and the wiring before every new setup. Up to 8 A flows in the coil: stay at the bench '
                       'while a run is in progress.')

    # settings and connections live in the slide-in drawer
    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 28, command=self.on_period))
    self.dmm_combo = f.row('Reading multimeter', f.combo(self.dmm_model, list(E.DMM_CHOICES), 22, command=self.on_dmm))
    self.precal_check = f.wide(H.checkbutton(None, 'Pre-calibrate the multimeter at each step (Table 3 footnote)', self.precal, lambda *_: None))
    f.rule()
    self.iface_combo = f.row('Multimeter interface', f.combo(self.interface, list(INTERFACES), 10, command=self.on_interface))
    self.dmm_entry = f.row('Multimeter address / resource', f.combo(self.dmm_addr, (), 34, state='normal'), fill=True)
    f.note('GPIB: enter the address (the 34410A factory address is 22) or a full VISA resource. USB: USB0::<mfgID>::<modID>::<serial>::INSTR (or Find instruments). '
           'RS-232 multimeters are not supported. The IDs in the example are not verified for your bench.')
    calbox = f.row('Calibrator', f.combo(self.cal_model, self.cal_choices(), 14))
    B.calibrator_note(f, self.cal_offer, widgets=(calbox,))
    self.cal_entry = f.row('Calibrator port', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Calibrator baud', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh, manual=True)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find),
                   [(c, B.idle_state(c)) for c in (self.period_combo, self.dmm_combo, self.precal_check)])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry).configure(values=values)
