"""Keysight 34970A / 34972A data acquisition unit, internal DMM performance verification: the Qt window code (port of the removed Tk view dacq_view_tk.py: same functions, same widgets as
attributes of the App, same texts, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('dacq_view')`, which resolves to `dacq_view_qt` under the Qt port.  Every function takes the engine's App as
`self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    import dacq_verification as E
    B.setup_window(self, f'Keysight {E.MODEL} | Performance Verification' + (' [DEMO]' if self.demo else ''), 1340, 860, 900, 660)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    B.finish_window(self)


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find),
                   [(c, B.idle_state(c)) for c in (self.period_combo, self.module_combo, self.slot_combo, self.ohm2_check, self.ac_check)])


def build_ui(self):
    import dacq_verification as E                      # the engine's module state (configure(model) can rebind it), read at call time
    BAUDS, FLOW, MODEL, PARITY_FORMATS, PERIODS, POINTS, SPEC, list_com_ports = E.BAUDS, E.FLOW, E.MODEL, E.PARITY_FORMATS, E.PERIODS, E.POINTS, E.SPEC, E.list_com_ports
    root = self.root
    sh = self.shell = S.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                              f'Internal DMM tests from the 34970A/34972A Service Guide, pp. 80-87  |  {len(POINTS)} points in the spec  |  '
                              + ('RS-232' if self.rs232 else 'USB'), demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program pauses and shows the hook-up for every new setup and before any high-voltage point. Warm the instrument up for 2 hours with a copper short '
                       'on the multiplexer first. Stay at the bench while a run is in progress.')

    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 20, command=self.on_period))
    mod = H.frame(None, 'h', spacing=0)
    self.module_combo = f.combo(self.module, ['34901A', '34902A'], 8, command=lambda: (self.refresh(), self._save_settings()))
    mod.layout().addWidget(self.module_combo)
    slot_label = H.label_(None, 'slot', 'Muted.TLabel')
    slot_label.setContentsMargins(8, 0, 4, 0)
    mod.layout().addWidget(slot_label)
    self.slot_combo = f.combo(self.slot, ['1', '2', '3'], 3, command=lambda: (self.refresh(), self._save_settings()))
    mod.layout().addWidget(self.slot_combo)
    f.row('Multiplexer module', mod)
    self.ohm2_check = f.wide(H.checkbutton(None, 'Include 2-wire ohms (optional)', self.include_ohm2, self.refresh))
    self.ac_check = f.wide(H.checkbutton(None, 'Include optional AC tests', self.include_ac, self.refresh))
    f.rule()
    if self.rs232:
        self.dmm_entry = f.row('34970A COM port', f.combo(self.dmm_addr, list_com_ports(), 14, state='normal'))
        for text, var, values, width in (('Baud', self.dmm_baud, BAUDS, 9), ('Format', self.dmm_format, list(PARITY_FORMATS), 24), ('Flow control', self.dmm_flow, list(FLOW), 30)):
            f.row(text, f.combo(var, values, width))
        f.note('On the 34970A: Interface > I/O Config, choose RS-232 and set the same baud, parity and flow control. Factory default: 57600, 8 bits no parity, XON/XOFF.')
        find_text = 'Refresh ports'
    else:
        self.dmm_entry = f.row('34972A USB address', f.combo(self.dmm_addr, (), 34, state='normal'), fill=True)
        f.note('Example: USB0::0x0957::0x2007::<serial>::INSTR  (press Find instruments with the USB cable connected)')
        find_text = 'Find instruments'
    calbox = f.row('Calibrator', f.combo(self.cal_model, self.cal_choices(), 14))
    B.calibrator_note(f, self.cal_offer, widgets=(calbox,))
    self.cal_entry = f.row('Calibrator address', f.combo(self.cal_addr, (), 34, state='normal'), fill=True)
    f.row('Calibrator baud', f.combo(self.cal_baud, ['9600', '19200', '4800', '2400', '1200'], 9))
    f.note('COM9, GPIB0::6::INSTR ...', column=1)
    B.find_and_test(sh, self, find_text, self.find_instruments)

    B.action_bar(self, sh, manual=True)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def set_choices(self, which, values):
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry).configure(values=values)
