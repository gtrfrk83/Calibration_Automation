"""Keysight 53210A / 53220A / 53230A performance verification: the Qt window code (twin of keysight_53220a_view_tk.py: same functions, same widgets as attributes of the App, same
texts, same busy / idle button states).

The engine reaches this module through `ui_port.get_ui().view('keysight_53220a_view')`, which resolves to `keysight_53220a_view_qt` under the Qt port.  Every function takes the
engine's App as `self`.  The parts the bench windows share are qtui/bench_view.py.  Nothing here decides anything about a calibration.
"""
from qtui import bench_view as B
from qtui import shell as S
from qtui import shell_helpers as H
from qtui.bench_view import Form, table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: F401  (the table_* contract of the views)


def setup_window(self):
    """Theme, title and size of the main window."""
    import keysight_53220a_verification as E
    B.setup_window(self, f'Keysight {E.MODEL} | Performance Verification' + (' [DEMO]' if self.demo else ''), 1320, 820, 900, 640)


def finish_window(self):
    """Attach the asset-history helpers to the window."""
    B.finish_window(self)


def build_ui(self):
    import keysight_53220a_verification as E                      # the engine's module state (configure(model) rebinds MODEL), read at call time
    INTERFACES, MODEL, PERIODS, POINTS, SPEC = E.INTERFACES, E.MODEL, E.PERIODS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = S.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                              f'Test points from the 53210A/53220A/53230A Service Guide, chapter 1  |  {len(POINTS)} points in the spec  |  USB, LAN or GPIB',
                              demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    B.notice(sh, self, 'The program asks you to confirm the warm-up and the 10 MHz reference, and the wiring before every new setup. Tests on another standard (pulse, burst, '
                       'low-level microwave) show which standard to connect and what to set. Stay at the bench while a run is in progress.')

    # settings and connections live in the slide-in drawer
    f = Form(sh.drawer_body)
    self.period_combo = f.row('Limits to apply', f.combo(self.period, list(PERIODS), 20, command=self.on_period))
    self.set_combo = f.row('Test set', f.combo(self.test_set, ['Full verification', 'Quick check (Q points only)'], 26, command=self.refresh))
    f.rule()
    f.note('INSTALLED OPTIONS: declare them here BEFORE the run; the point table follows your selection. *OPT? pre-fills them at Test connections (only if you have not set them); a difference is warned and YOUR selection decides. Option 201 (rear inputs) is not reported by *OPT?.')
    self.tb_combo = f.row('Time base', f.combo(self.tb_opt, list(E.TB_CHOICES), 22, command=self.on_options))
    self.ch3_combo = f.row('Microwave channel', f.combo(self.ch3_opt, list(E.CH3_CHOICES), 22, command=self.on_options))
    self.pulse_check = f.wide(H.checkbutton(None, 'Option 150 pulse microwave (53230A only; no effect on other models)', self.pulse_opt, self.on_options))
    self.rear_check = f.wide(H.checkbutton(None, 'Option 201 rear-panel inputs', self.rear_opt, self.on_options))
    f.rule()
    self.stim_combo = f.row('Stimulus', f.combo(self.stim_mode, list(E.STIM_CHOICES), 28, command=self.refresh))
    self.pulse_combo = f.row('Pulse tests 4 and 5', f.combo(self.pulse_gen, list(E.PULSE_GEN_CHOICES), 40, command=self.refresh))
    f.note('The Agilent 33250A cannot make the 5 ns pulse (minimum pulse width) or the two outputs 49.9 ns apart: those points stay on another pulse generator and the prompt says why.')
    self.ref_combo = f.row('10 MHz reference', f.combo(self.ref_mode, list(E.REF_CHOICES), 24))
    self.loss_entry = f.row('Cable loss (dB)', f.combo(self.loss, ['0', '0.5', '1', '2', '3', '6'], 8, state='normal', command=self.refresh))
    self.low_check = f.wide(H.checkbutton(None, '96270A has the Extended Low Level option (the bench 96270A has NOT: leave off)', self.ext_low, self.refresh))
    f.note('The cable loss is added to the level the 96270A is set to. Above 4 GHz the Microwave O/P is used; where it cannot make the level (5.88 GHz at -27 dBm) an external attenuator is called for in the prompt. The output route is chosen on the 96270A front panel.')
    f.rule()
    self.iface_combo = f.row(f'{MODEL} interface', f.combo(self.interface, list(INTERFACES), 10, command=self.on_interface))
    self.ctr_entry = f.row(f'{MODEL} address / resource', f.combo(self.ctr_addr, (), 38, state='normal'), fill=True)
    f.note('USB: USB0::<mfgID>::<modelID>::<serial>::INSTR; LAN: TCPIP0::<ip>::inst0::INSTR; GPIB: GPIB0::<address>::INSTR. The examples are not verified for your bench: use Find instruments.')
    self.rf_entry = f.row('96270A address / resource', f.combo(self.rf_addr, (), 38, state='normal'), fill=True)
    f.note('Leave the 96270A address empty to use other standards for every test.')
    B.find_and_test(sh, self, 'Find instruments', self.find_instruments)

    B.action_bar(self, sh)
    B.build_results(self, sh, SPEC['source']['note'])
    self.update_shell_sections(POINTS, lambda p: p['section_title'])


def sync_buttons(self):
    B.sync_buttons(self, (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find),
                   [(c, B.idle_state(c)) for c in (self.period_combo, self.set_combo, self.tb_combo, self.ch3_combo, self.pulse_check, self.rear_check, self.stim_combo, self.ref_combo,
                                                  self.loss_entry, self.low_check)])


def set_choices(self, which, values):
    """The drop-down values of the counter address ('ctr') or 96270A address ('rf') box."""
    (self.ctr_entry if which == 'ctr' else self.rf_entry).configure(values=values)
