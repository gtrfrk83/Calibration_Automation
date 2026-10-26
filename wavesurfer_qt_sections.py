"""WaveSurfer 4104HD Qt window: the pages of the notebook (RMS noise, DC voltage, input impedance, offset, bandwidth, time base, trigger level).

Qt twin of `make_ui` / `show_dcv` / `show_impedance` / `show_offset` / `show_bandwidth` / `show_timebase` / `show_trigger` of wavesurfer_view_tk.py: same widgets, same
texts, same button names, same commands, same attribute names on the App (`self.tree`, `self.dc_tree`, `self.imp_tree`, `self.offset_tree`, `self.bw_tree`, `self.tb_tree`,
`self.trig_tree`, the progress bars, `dc_next_button` / `imp_next_button` which the engine keeps for its state handling and the window never shows ...).  As in Tk the
notebook that holds these pages is never shown: the technician works in the single results table of build_unified; the pages hold the settings, the tables the engine
fills and the buttons the engine enables and disables.  Nothing here decides anything about a calibration."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QVBoxLayout

import datamode  # noqa: F401  (kept next to the Tk view's imports: the shared mixins' constants)
import qtui.shell_helpers as H
from ui_port import ui as port

import wavesurfer_qt_common as K


def _tree_page(self, lay, tree, prefix=None):
    lay.addWidget(tree, 1)
    if prefix:
        K.point_menu(self, tree, prefix)       # right-click > Edit (tolerance only here)


def _buttons(items, spacing=8):
    """items = [(text, command)]; returns the row widget and the buttons."""
    bs = [H.button(None, label, command) for label, command in items]
    return K.row(*bs, spacing=spacing), bs


# ---- RMS noise ---------------------------------------------------------------------------------------------------------------------------------------
def make_ui(self):
    pg = self.rms_tab
    lay = QVBoxLayout(pg)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(8)
    self.noise_container = pg
    lay.addWidget(H.label_(None, 'RMS Noise Verification', 'Section.TLabel'))
    lay.addWidget(H.label_(None, 'Teledyne LeCroy WaveSurfer 4104HD  •  USBTMC / PyVISA'))
    connection = QGroupBox('Connection')
    cl = H.frame(None, 'grid', spacing=8)
    grid = cl.layout()
    grid.setColumnStretch(1, 1)
    grid.addWidget(H.label_(None, 'VISA address'), 0, 0)
    self.address_entry = H.entry(None, self.visa_address)
    grid.addWidget(self.address_entry, 0, 1)
    self.connect_button = H.button(None, 'Test Connection', self.test_connection)
    grid.addWidget(self.connect_button, 0, 2)
    grid.addWidget(H.label_(None, '', textvariable=self.status), 1, 1)
    QVBoxLayout(connection).addWidget(cl)
    lay.addWidget(connection)

    self.config_frame = QGroupBox('Test configuration')
    config = H.frame(None, 'grid', spacing=8)
    g = config.layout()
    for i in range(8):
        g.setColumnStretch(i, 1 if i % 2 else 0)
    g.addWidget(H.label_(None, 'Channel'), 0, 0)
    self.channel_select = H.combobox(None, self.channel, ['1', '2', '3', '4'], width=6, state='readonly')
    g.addWidget(self.channel_select, 0, 1)
    g.addWidget(H.checkbutton(None, 'Test all 4 channels', self.all_channels), 4, 0, 1, 3)
    g.addWidget(H.label_(None, 'Settle (s)'), 0, 2)
    g.addWidget(H.entry(None, self.delay, width=7), 0, 3)
    g.addWidget(H.label_(None, 'Samples/range'), 0, 4)
    g.addWidget(H.entry(None, self.samples, width=7), 0, 5)
    g.addWidget(H.label_(None, 'dB factor (div)'), 0, 6)
    g.addWidget(H.entry(None, self.ref_factor, width=8), 0, 7)
    g.addWidget(H.label_(None, 'Min limits (dB), comma-separated, in scale order:'), 1, 0, 1, 4)
    g.addWidget(H.entry(None, self.limit_text), 1, 4, 1, 4)
    g.addWidget(K.text('P1 StdDev and source are set automatically for RMS noise. All channels ON; DC 1 MΩ; full bandwidth; 1 ms/div; external 50 Ω termination.'),
                2, 0, 1, 8)
    g.addWidget(H.Notice(None, 'Formula: 20 log10((factor × V/div)/RMS). User reports Teledyne verification; confirm limits, setup and decision rule before calibration release.',
                         'warn'), 3, 0, 1, 8)
    QVBoxLayout(self.config_frame).addWidget(config)
    lay.addWidget(self.config_frame)
    # Collapse the tall setup panel by default so the results table remains visible even on smaller laptop displays.
    self.show_settings = port.var(False, 'bool')
    lay.addWidget(H.checkbutton(None, 'Show test settings', self.show_settings, self.toggle_settings))
    self.config_frame.hide()

    self.actions = H.frame(None, 'h', spacing=8)
    al = self.actions.layout()
    self.start_button = H.button(None, '▶  Start Test', self.start_test)
    self.stop_button = H.button(None, '■  Stop', self.stop_test, state='disabled')
    self.resume_button = H.button(None, '▶  Resume Test', self.resume_test, state='disabled')
    self.retest_button = H.button(None, 'Rerun Selected Test Point', self.retest_noise)
    for b in (self.start_button, self.stop_button, self.resume_button, self.retest_button, H.button(None, 'Clear Results', self.clear_results)):
        al.addWidget(b)
    al.addStretch(1)
    lay.addWidget(self.actions)
    lay.addWidget(H.label_(None, 'Measurement Results', 'Section.TLabel'))
    columns = ('channel', 'scale', 'rms', 'runit', 'db', 'minimum', 'margin', 'dunit', 'result', 'samples')
    heads = ('Channel', 'Range', 'RMS noise', 'Units', 'Noise level', 'Minimum', 'Margin', 'Units', 'Result', 'Samples')
    widths = (80, 105, 105, 60, 105, 95, 95, 60, 110, 85)
    self.tree = K.section_tree(columns, heads, widths)
    lay.addWidget(self.tree, 1)
    self.progress = K.progress(36)
    lay.addWidget(self.progress)
    self.progress_text = port.var('Ready — 0 of 36 ranges')
    lay.addWidget(H.label_(None, '', textvariable=self.progress_text))
    lay.addWidget(K.text('PASS/FAIL compares measured noise dB against entered limits; no measurement-uncertainty guard band is applied. Verify setup and decision rule before release.'))


# ---- DC voltage --------------------------------------------------------------------------------------------------------------------------------------
def show_dcv(self):
    if K.alive(getattr(self, 'dc_window', None)):
        self.tabs.setCurrentWidget(self.dc_window)
        return
    win, lay = K.page(self, 'DC Voltage', 12)
    self.dc_window = win
    self.tabs.setCurrentWidget(win)
    lay.addWidget(H.label_(None, 'DC Voltage Verification • 80 test points', 'Section.TLabel'))
    lay.addWidget(K.text('Fluke automatic DCV uses the SCOPE output connector (not NORMAL terminals). Scope P1 MEAN, 20 MHz bandwidth and DC 1 MΩ are configured and verified '
                         'automatically. Confirm connections before enabling output.'))
    lay.addWidget(K.row(H.label_(None, 'Calibrator'), H.combobox(None, self.fluke_model, self.CAL_CHOICES, width=14, state='readonly', command=self.on_cal_model), H.label_(None, 'VISA'), H.entry(None, self.fluke_address, width=20), H.label_(None, 'Baud'), H.entry(None, self.fluke_baud, width=8),
                        H.button(None, 'Test calibrator ID', self.test_fluke), spacing=6))
    lay.addWidget(K.row(H.label_(None, 'DCV settle time after OPER (seconds; default 3.0)'), H.entry(None, self.dc_settle, width=8)))
    lay.addWidget(K.text('After the configured settling delay, discard one P1 read, wait 0.5 s, then use one P1 MEAN reading per DCV point. Fluke STBY is verified after each point.'))
    # Manual Next button intentionally not displayed; retained internally for state handling.
    self.dc_next_button = K.hidden_button(win, 'Start / Next DCV Point', self.next_dcv)
    bar, _bs = _buttons([('Run DCV Automatically', self.start_dcv_batch), ('Resume DCV', self.resume_dcv), ('Retest Selected DCV Point', self.retest_selected_dcv),
                         ('Stop After Current Point', self.stop_dcv_batch), ('Clear DCV Results', self.clear_dcv)])
    lay.addWidget(bar)
    lay.addWidget(H.label_(None, '', textvariable=self.dc_status, wraplength=1))
    self.dc_progress = K.progress(80)
    lay.addWidget(self.dc_progress)
    cols = ('channel', 'scale', 'nominal', 'observed', 'low', 'high', 'error', 'units', 'result')
    heads = ('Channel', 'Range', 'Nominal', 'Measured', 'Lower limit', 'Upper limit', 'Error', 'Units', 'Result')
    self.dc_tree = K.section_tree(cols, heads, (80, 100, 105, 110, 105, 105, 105, 70, 90))
    _tree_page(self, lay, self.dc_tree, 'dcv')
    self.refresh_dcv_table()
    self.dc_status.set(f'Restored {len(self.dc_rows)} of 80 DCV test points. Automatic Fluke control is OFF until enabled.')


# ---- input impedance ---------------------------------------------------------------------------------------------------------------------------------
def show_impedance(self):
    if K.alive(getattr(self, 'imp_window', None)):
        self.tabs.setCurrentWidget(self.imp_window)
        return
    win, lay = K.page(self, 'Input Impedance', 14)
    self.imp_window = win
    self.tabs.setCurrentWidget(win)
    lay.addWidget(H.label_(None, 'Input Impedance Verification', 'Section.TLabel'))
    lay.addWidget(K.text('HAZ-OSC-02: 24 channel points + 4 EXT/EXT5 points. Fluke SCOPE BNC resistance measurement, not NORMAL terminals.'))
    lay.addWidget(K.text('For C1–C4: scope coupling and scale are set/read back automatically. EXT/EXT5 mode is selected and confirmed manually.'))
    lay.addWidget(K.row(H.label_(None, 'Settle (s):'), H.entry(None, self.imp_settle, width=7), H.label_(None, 'Readings:'), H.entry(None, self.imp_samples, width=7),
                        H.label_(None, 'Fluke COM / baud inherited from DCV settings'), spacing=8))
    # Manual impedance button intentionally hidden; retained for existing state handling.
    self.imp_next_button = K.hidden_button(win, 'Measure Next Impedance Point', self.next_impedance)
    bar, _bs = _buttons([('Run Impedance Automatically', self.start_impedance_batch), ('Stop After Current Point', self.stop_impedance_batch),
                         ('Rerun Selected Test Point', self.retest_impedance), ('Resume Impedance', self.resume_impedance),
                         ('Clear Impedance Results', self.clear_impedance)])
    lay.addWidget(bar)
    lay.addWidget(H.label_(None, '', textvariable=self.imp_status))
    self.imp_progress = K.progress(28)
    lay.addWidget(self.imp_progress)
    cols = ('point', 'channel', 'coupling', 'scale', 'nominal', 'measured', 'low', 'high', 'units', 'result')
    heads = ('#', 'Input', 'Coupling', 'Range', 'Nominal', 'Measured', 'Lower limit', 'Upper limit', 'Units', 'Result')
    self.imp_tree = K.section_tree(cols, heads, (45, 75, 90, 100, 100, 110, 105, 105, 65, 75))
    _tree_page(self, lay, self.imp_tree, 'impedance')
    self.refresh_impedance_table()
    self.imp_status.set(f'Restored {len(self.imp_rows)} of 28 impedance points.')


# ---- offset ------------------------------------------------------------------------------------------------------------------------------------------
def show_offset(self):
    self.offset_tab, lay = K.page(self, 'Offset / P1 Mean', 14)
    lay.addWidget(H.label_(None, 'Offset-position DC Voltage Verification', 'Section.TLabel'))
    lay.addWidget(K.text('16 points: four channels × ±4.5 V and ±10 V. The Fluke SCOPE DCV output is opposite polarity to the scope vertical offset. '
                         'P1 MEAN is compared with the applied DC voltage. This is NOT an independent measurement of vertical offset centering accuracy.'))
    settle = H.entry(None, self.offset_settle, width=7)
    bar = K.row(H.label_(None, 'Settle (s):'), settle, H.button(None, 'Run Offset Automatically', self.start_offset), H.button(None, 'Resume Offset', self.start_offset),
                H.button(None, 'Rerun Selected Test Point', self.retest_offset), H.button(None, 'Stop After Current Point', self.stop_offset), spacing=8)
    lay.addWidget(bar)
    lay.addWidget(H.label_(None, '', textvariable=self.offset_status))
    self.offset_progress = K.progress(16)
    lay.addWidget(self.offset_progress)
    cols = ('ch', 'scale', 'offset', 'source', 'mean', 'error', 'low', 'high', 'units', 'result')
    heads = ('Channel', 'Range', 'Scope offset', 'Fluke source', 'P1 Mean', 'Error', 'Lower limit', 'Upper limit', 'Units', 'Result')
    self.offset_tree = K.section_tree(cols, heads, (80, 100, 110, 110, 110, 100, 105, 105, 65, 85))
    _tree_page(self, lay, self.offset_tree, 'offset')


# ---- bandwidth ---------------------------------------------------------------------------------------------------------------------------------------
def show_bandwidth(self):
    self.bw_tab, lay = K.page(self, 'Bandwidth / LEVSINE', 14)
    lay.addWidget(H.label_(None, 'Analog Bandwidth — Fluke SCOPE LEVSINE', 'Section.TLabel'))
    lay.addWidget(H.label_(None, '24 points  •  4 channels × 6 scales  •  stimulus 6 divisions Vpp  •  scope DC50, full bandwidth', 'Muted.TLabel'))
    lay.addWidget(K.text('Reference: 50 kHz at 10 µs/div.   High frequency: 1 GHz at 1 ns/div.\n'
                         'Response = 20 log10 (Vpp at 1 GHz ÷ Vpp at 50 kHz), from P1 peak-to-peak.   Limits: −3 to +3 dB.'))
    lay.addWidget(H.Notice(None, 'This release has not been hardware-validated for LEVSINE and P1 PkPk. Check the first point before relying on the results.', 'warn',
                           title='Verify the first point'))
    lay.addWidget(K.row(H.label_(None, 'Settle (s):'), H.entry(None, self.bw_settle, width=7), H.button(None, 'Run / Resume Bandwidth', self.start_bandwidth),
                        H.button(None, 'Rerun Selected Test Point', self.retest_bandwidth), H.button(None, 'Stop After Current Point', self.stop_bandwidth), spacing=8))
    lay.addWidget(H.label_(None, '', textvariable=self.bw_status))
    self.bw_progress = K.progress(24)
    lay.addWidget(self.bw_progress)
    cols = ('channel', 'scale', 'amplitude', 'ref', 'high', 'vunit', 'db', 'dunit', 'result')
    heads = ('Channel', 'Range', 'Stimulus', '50 kHz', '1 GHz', 'Units', 'Response', 'Units', 'Result')
    self.bw_tree = K.section_tree(cols, heads, (85, 100, 105, 105, 105, 70, 100, 60, 90))
    _tree_page(self, lay, self.bw_tree, 'bandwidth')


# ---- time base ---------------------------------------------------------------------------------------------------------------------------------------
def show_timebase(self):
    self.tb_tab, lay = K.page(self, 'Time Base', 14)
    lay.addWidget(H.label_(None, '', textvariable=self.tb_status))
    cols = ('period', 'nominal', 'mean', 'error', 'low', 'high', 'unit', 'result')
    heads = ('Marker', 'Nominal', 'P1 Freq mean', 'Error', 'Lower limit', 'Upper limit', 'Units', 'Result')
    self.tb_tree = K.section_tree(cols, heads, (90, 110, 130, 100, 100, 100, 60, 80), height=2)
    _tree_page(self, lay, self.tb_tree, 'timebase')


# ---- trigger level -----------------------------------------------------------------------------------------------------------------------------------
def show_trigger(self):
    self.trig_tab, lay = K.page(self, 'Trigger Level', 14)
    lay.addWidget(H.label_(None, '', textvariable=self.trig_status))
    cols = ('ch', 'level', 'slope', 'low', 'high', 'outcome', 'result')
    heads = ('Channel', 'Level (mV)', 'Slope', 'Lower (mV)', 'Upper (mV)', 'Outcome', 'Result')
    self.trig_tree = K.section_tree(cols, heads, (80, 100, 90, 100, 100, 170, 80))
    _tree_page(self, lay, self.trig_tree, 'trigger')
