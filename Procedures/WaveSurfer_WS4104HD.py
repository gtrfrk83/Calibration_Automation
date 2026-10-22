"""WaveSurfer 4104HD verification GUI — RMS noise, DC voltage, input impedance, offset, bandwidth, time base and trigger level.

Requires: pip install pyvisa; a working VISA backend (e.g. NI-VISA). Instrument commands live in ../drivers.
The 2.75-division normalization is user-reported as verified with Teledyne.
Confirm applicability and test setup before issuing formal calibration results.
"""
import sys
import json
import math
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.append(str(Path(__file__).resolve().parent.parent))  # shared ui_theme.py sits next to the Manager
import ui_theme as ui
import ui_shell
import appdata
import datamode
import drivers
import procmods
import procmods_engine
import reset_startup

DEFAULT_ADDRESS = 'USB0::0x05FF::0x1023::LCRY4903C19426::0::INSTR'
SCALES = [0.002, 0.005, 0.010, 0.020, 0.050, 0.100, 0.200, 0.500, 1.000]
LIMITS = [30, 38, 44, 48, 51, 52, 48, 51, 52]
# Time base and trigger level limits: HAZ-OSC-02 data sheet pages 10-11, read from the rendered page images.
TIMEBASE_LIMIT_HZ = 0.350        # error 0.00 Hz, -0.350 to +0.350 Hz
TB_SCALE = 0.200                 # V/div for the time-marker input (DC 50 Ohm)
TB_TRIGGER_V = 0.100             # trigger level on the marker
TB_READ_GAP_S = 0.5
TRIG_LEVELS = (0.0, 0.300, -0.300)
TRIG_LIMIT_V = 0.020             # +/-20 mV
TRIG_SCALE = 0.100               # 100 mV/div, DC 1 MOhm
TRIG_START_V = 0.100             # the Fluke starts 100 mV before the level
TRIG_HSCALE = 1e-3


class OperatorCancelled(Exception):
    """The technician chose Cancel at a prompt inside a measurement."""


FIELDS=('Description','Nominal','Tolerance -','Tolerance +','UOM','As Found','OOT','As Left','Uncertainty')
SECTIONS=[('RMS NOISE','noise'),('DC VOLTAGE / GAIN','dcv'),('INPUT IMPEDANCE','impedance'),('VERTICAL OFFSET / P1 MEAN','offset'),('ANALOG BANDWIDTH / LEVSINE','bandwidth'),
          ('TIME BASE ACCURACY','timebase'),('TRIGGER LEVEL ACCURACY','trigger')]

def make_report(groups, output_path, synthetic=False, instrument_id=""):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins

    wb = Workbook()
    ws = wb.active
    ws.title = 'Calibration Data'
    ws.sheet_view.showGridLines = False
    widths = [43, 31, 19, 19, 14, 19, 11, 17, 20]
    for idx, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    def band(row, text, bg, fg, size=11, height=27, bold=True):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        for cells in ws.iter_rows(min_row=row, max_row=row, min_col=1, max_col=9):
            for cell in cells:
                cell.fill = PatternFill('solid', fgColor=bg)
        c = ws.cell(row, 1, text)
        c.font = Font(name='Aptos', size=size, bold=bold, color=fg)
        c.alignment = Alignment(vertical='center', indent=1)
        ws.row_dimensions[row].height = height

    band(1, 'OSCILLOSCOPE  |  CALIBRATION DATA', '12253D', 'FFFFFF', 17, 38)
    subtitle = 'WS4104HD  •  RESULTS SUMMARY'
    if synthetic:
        subtitle += '  •  SYNTHETIC DEMONSTRATION — NOT CALIBRATION EVIDENCE'
    band(2, subtitle, '203A58', 'D6E6F5', 10, 27, False)
    band(3, 'INSTRUMENT ID:  ' + (str(instrument_id).strip() or 'NOT ENTERED'),
         'FFFFFF', '18334F', 12, 28)
    total = sum(len(v) for v in groups.values())
    failures = sum(1 for vv in groups.values() for v in vv if str(v.get('OOT', '')).strip())
    band(4, f'TOTAL TEST POINTS: {total}     |     OOT: {failures}     |     SECTIONS: {sum(bool(v) for v in groups.values())}',
         'E9F1F8', '18334F', 10, 28)

    r = 6
    seq = 0
    thin = Side(style='hair', color='DCE4EC')
    for label, key in SECTIONS:
        rows = groups.get(key, [])
        if not rows:
            continue
        band(r, f'{label}   |   {len(rows)} POINTS', '214C71', 'FFFFFF', 12, 28)
        r += 1
        for col, name in enumerate(FIELDS, 1):
            cell = ws.cell(r, col, name)
            cell.fill = PatternFill('solid', fgColor='BFD2E3')
            cell.font = Font(name='Aptos', size=10, bold=True, color='17304A')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            cell.border = Border(bottom=Side(style='thin', color='91A8BB'))
        ws.row_dimensions[r].height = 28
        r += 1
        for i, row in enumerate(rows):
            seq += 1
            for col, field in enumerate(FIELDS, 1):
                val = row.get(field, '')
                cell = ws.cell(r, col, val if val is not None else '')
                cell.font = Font(name='Aptos', size=10, color='24364A')
                cell.fill = PatternFill('solid', fgColor='F0F4F8' if i % 2 == 0 else 'FFFFFF')
                cell.border = Border(bottom=thin)
                cell.alignment = Alignment(vertical='center', wrap_text=(col == 1))
            if str(row.get('OOT', '')).strip():
                cell = ws.cell(r, 7)
                cell.fill = PatternFill('solid', fgColor='FCE1E1')
                cell.font = Font(name='Aptos', size=10, bold=True, color='A32121')
            ws.row_dimensions[r].height = 25
            r += 1
        r += 2

    ws.freeze_panes = 'A5'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True
    ws.page_margins = PageMargins(left=.3, right=.3, top=.5, bottom=.5, header=.2, footer=.2)
    ws.oddFooter.center.text = 'Page &P of &N'
    ws.print_area = f'A1:I{max(4, r-2)}'
    wb.save(str(output_path))
    return seq



# Procedure modifications (procmods_engine): which tolerance fields of each section's points can be overridden.
# section -> (nominal field or None, low field, high field, fields that identify the point besides the section)
PM_SECTIONS = {
    'dcv': ('nominal_v', 'lower_v', 'upper_v', ('channel', 'scale_v_div')),
    'impedance': ('nominal_ohm', 'lower_ohm', 'upper_ohm', ('channel', 'coupling', 'scale_v_div', 'description')),
    'offset': ('nominal_v', 'lower_v', 'upper_v', ('channel', 'scale_v_div', 'scope_offset_v')),
    'bandwidth': (None, 'lower_db', 'upper_db', ('channel', 'scale_v_div')),
    'timebase': (None, 'lower_hz', 'upper_hz', ('channel',)),                      # the limit is an error band around 0 Hz
    'trigger': ('level_v', 'lower_v', 'upper_v', ('channel', 'slope')),
}
# entry-box variable -> (tunable, factory default, factory text).  The text is exactly what the box always started with.
PM_VARS = (('delay', 'ws.rms_delay', 3, '3'), ('samples', 'ws.rms_samples', 5, '5'), ('dc_settle', 'ws.dcv_settle', 3.0, '3.0'),
           ('imp_settle', 'ws.imp_settle', 2.0, '2.0'), ('imp_samples', 'ws.imp_samples', 3, '3'),
           ('offset_settle', 'ws.offset_settle', 3.0, '3.0'), ('bw_settle', 'ws.bw_settle', 3.0, '3.0'),
           ('tb_settle', 'ws.tb_settle', 3.0, '3.0'), ('tb_samples', 'ws.tb_samples', 5, '5'), ('trig_settle', 'ws.trig_settle', 1.0, '1.0'))


class RMSNoiseApp(datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root):
        self.root = root
        self.pm_init('ws', 'WS4104HD', demo='--demo' in sys.argv)      # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title('WaveSurfer 4104HD | Calibration Verification v56')
        ui.fit_window(root, 1300, 880, min_w=900, min_h=640)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False
        self.connected = False
        self.rows = []
        self.run_config = None
        self.checkpoint_path = appdata.progress_path('rms_noise_checkpoint_v5.json')
        self.instrument_id = tk.StringVar(value='')
        self.serial = tk.StringVar(value='')
        self.visa_address = tk.StringVar(value=DEFAULT_ADDRESS)
        self.channel = tk.StringVar(value='1')
        self.all_channels = tk.BooleanVar(value=True)
        self.awaiting_channel = False
        self.ref_factor = tk.StringVar(value='2.75')
        self.delay = tk.StringVar(value=self.pm_text('ws.rms_delay', 3, '3'))
        self.samples = tk.StringVar(value=self.pm_text('ws.rms_samples', 5, '5'))
        self.status = tk.StringVar(value='Disconnected')
        self.reading = tk.StringVar(value='—')
        self.db_reading = tk.StringVar(value='—')
        self.limit_text = tk.StringVar(value=','.join(map(str, LIMITS)))
        self.dc_rows = []
        self.dc_retest_index = None
        self.dc_config = None
        self.noise_retest_index = None
        self.noise_retest_result = None
        self.dc_checkpoint = appdata.progress_path('dcv_checkpoint_v6.json')
        self.fluke_address = tk.StringVar(value='ASRL9::INSTR')
        self.fluke_baud = tk.StringVar(value='9600')
        self.dc_status = tk.StringVar(value='DC voltage verification ready')
        self.dc_reading = tk.StringVar(value='—')
        self.dc_running = False
        self.dc_pending = None
        self.dc_batch = False
        self.dc_batch_channel = None
        self.dc_batch_point_ok = False
        self.dc_p1_mode = tk.BooleanVar(value=True)
        self.dc_auto_fluke = tk.BooleanVar(value=True)
        self.dc_settle = tk.StringVar(value=self.pm_text('ws.dcv_settle', 3.0, '3.0'))
        self.offset_rows = []
        self.offset_running = False
        self.offset_batch = False
        self.offset_ok = False
        self.offset_connected_channel = None
        self.offset_checkpoint = appdata.progress_path('offset_mean_checkpoint_v28.json')
        self.offset_status = tk.StringVar(value='Ready — 0 of 16 offset points')
        self.offset_settle = tk.StringVar(value=self.pm_text('ws.offset_settle', 3.0, '3.0'))
        self.bw_rows = []
        self.bw_running = False
        self.bw_batch = False
        self.bw_ok = False
        self.bw_connected_channel = None
        self.bw_checkpoint = appdata.progress_path('bandwidth_checkpoint_v29.json')
        self.bw_status = tk.StringVar(value='Ready — 0 of 24 bandwidth points')
        self.bw_settle = tk.StringVar(value=self.pm_text('ws.bw_settle', 3.0, '3.0'))
        self.tb_rows = []
        self.tb_running = False
        self.tb_retest_index = None
        self.tb_status = tk.StringVar(value='Ready \u2014 0 of 1 time base point')
        self.tb_settle = tk.StringVar(value=self.pm_text('ws.tb_settle', 3.0, '3.0'))
        self.tb_samples = tk.StringVar(value=self.pm_text('ws.tb_samples', 5, '5'))
        self.tb_period_us = tk.StringVar(value='10')
        self.trig_rows = []
        self.trig_running = False
        self.trig_batch = False
        self.trig_ok = False
        self.trig_retest_index = None
        self.trig_connected_channel = None
        self.trig_status = tk.StringVar(value='Ready \u2014 0 of 24 trigger level points')
        self.trig_settle = tk.StringVar(value=self.pm_text('ws.trig_settle', 1.0, '1.0'))
        self.imp_rows = []
        self.imp_running = False
        self.imp_batch = False
        self.imp_batch_success = False
        self.imp_connection_confirmed = False
        self.imp_connected_input = None
        self.imp_checkpoint = appdata.progress_path('impedance_checkpoint_v11.json')
        self.imp_status = tk.StringVar(value='Ready — 0 of 28 impedance points')
        self.imp_settle = tk.StringVar(value=self.pm_text('ws.imp_settle', 2.0, '2.0'))
        self.imp_samples = tk.StringVar(value=self.pm_text('ws.imp_samples', 3, '3'))
        self._ckpt_key = None
        self._ckpt_id = ''
        self._pm_ws_last = {v: getattr(self, v).get() for v, _n, _d, _t in PM_VARS}   # what each box held when the modifications were applied
        self._set_ckpt_paths('UNASSIGNED')
        # All test views live in one root window. Test dialogs for cable changes
        # and safety confirmations remain modal by design.
        self.shell = ui_shell.Shell(self.root, 'WaveSurfer 4104HD  -  Calibration Verification',
                                    'Teledyne LeCroy  |  USBTMC / PyVISA  |  RMS noise, DC voltage, input impedance, offset, bandwidth, time base and trigger level',
                                    demo='--demo' in sys.argv, on_section=self._pick_function, version='v56')
        self.conn_pill = self.shell.add_chip('Scope: not connected', 'neutral')
        # The five measurement sections are built inside a notebook that is never shown: it holds each section's settings, checkpoints and
        # workers. What the technician sees is the single results table below (build_unified), filterable by function.
        self.tabs = ttk.Notebook(self.root)
        self.rms_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.rms_tab, text='RMS Noise')
        self.make_ui()
        self.make_dcv_ui()
        self.make_impedance_button()
        self.show_dcv()
        self.show_impedance()
        self.show_offset()
        self.load_offset_checkpoint()
        self.show_bandwidth()
        self.load_bandwidth_checkpoint()
        self.show_timebase()
        self.load_timebase_checkpoint()
        self.show_trigger()
        self.load_trigger_checkpoint()
        self.root.after(100, self.process_events)
        self.load_checkpoint()
        self.load_dc_checkpoint()
        self.load_impedance_checkpoint()
        for var in (self.channel, self.all_channels, self.limit_text):
            var.trace_add('write', lambda *_: self._noise_settings_changed())
        self.refresh_noise_grid()
        self.refresh_dcv_table()
        self.refresh_impedance_table()
        self.refresh_offset()
        self.refresh_bandwidth()
        self.refresh_timebase()
        self.refresh_trigger()
        self.dc_status.set(f'{len(self.dc_rows)} of 80 DCV points recorded. Automatic Fluke control is OFF until enabled.')
        self.imp_status.set(f'{len(self.imp_rows)} of 28 impedance points recorded.')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.build_unified()
        ui.polish(self.root)
        self.root.after(500, self.update_tab_titles)
        if '--demo' in sys.argv:
            self.load_demo_data()

    def make_ui(self):
        container = ttk.Frame(self.rms_tab, padding=16)
        container.pack(fill='both', expand=True)
        ttk.Label(container, text='RMS Noise Verification', style='Header.TLabel').pack(anchor='w')
        self.noise_container = container
        ttk.Label(container, text='Teledyne LeCroy WaveSurfer 4104HD  •  USBTMC / PyVISA').pack(anchor='w', pady=(2, 10))
        connection = ttk.LabelFrame(container, text='Connection', padding=10)
        connection.pack(fill='x', pady=(0, 10))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text='VISA address').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.address_entry = ttk.Entry(connection, textvariable=self.visa_address)
        self.address_entry.grid(row=0, column=1, sticky='ew')
        self.connect_button = ttk.Button(connection, text='Test Connection', command=self.test_connection)
        self.connect_button.grid(row=0, column=2, padx=(10, 0))
        ttk.Label(connection, textvariable=self.status).grid(row=1, column=1, sticky='w', pady=(6, 0))
        self.config_frame = ttk.LabelFrame(container, text='Test configuration', padding=10)
        config = self.config_frame
        config.pack(fill='x', pady=(0, 10))
        for i in range(8):
            config.columnconfigure(i, weight=1 if i % 2 else 0)
        ttk.Label(config, text='Channel').grid(row=0, column=0, sticky='w')
        self.channel_select = ttk.Combobox(config, textvariable=self.channel, values=['1', '2', '3', '4'], width=6, state='readonly')
        self.channel_select.grid(row=0, column=1, sticky='w', padx=(6, 18))
        ttk.Checkbutton(config, text='Test all 4 channels', variable=self.all_channels).grid(row=4, column=0, columnspan=3, sticky='w', pady=(8, 0))
        ttk.Label(config, text='Settle (s)').grid(row=0, column=2, sticky='w')
        ttk.Entry(config, textvariable=self.delay, width=7).grid(row=0, column=3, sticky='w', padx=(6, 18))
        ttk.Label(config, text='Samples/range').grid(row=0, column=4, sticky='w')
        ttk.Entry(config, textvariable=self.samples, width=7).grid(row=0, column=5, sticky='w', padx=(6, 18))
        ttk.Label(config, text='dB factor (div)').grid(row=0, column=6, sticky='w')
        ttk.Entry(config, textvariable=self.ref_factor, width=8).grid(row=0, column=7, sticky='w', padx=6)
        ttk.Label(config, text='Min limits (dB), comma-separated, in scale order:').grid(row=1, column=0, columnspan=4, sticky='w', pady=(12, 0))
        ttk.Entry(config, textvariable=self.limit_text).grid(row=1, column=4, columnspan=4, sticky='ew', pady=(12, 0), padx=6)
        ttk.Label(config, text='P1 StdDev and source are set automatically for RMS noise. All channels ON; DC 1 MΩ; full bandwidth; 1 ms/div; external 50 Ω termination.', wraplength=1050).grid(row=2, column=0, columnspan=8, sticky='w', pady=(10, 0))
        ttk.Label(config, text='Formula: 20 log10((factor × V/div)/RMS). User reports Teledyne verification; confirm limits, setup and decision rule before calibration release.', foreground=ui.C['warn'], wraplength=1050).grid(row=3, column=0, columnspan=8, sticky='w', pady=(5, 0))
        # Collapse the tall setup panel by default so the results table
        # remains visible even on smaller laptop displays.
        self.show_settings = tk.BooleanVar(value=False)
        ttk.Checkbutton(container, text='Show test settings', variable=self.show_settings,
                        command=self.toggle_settings).pack(anchor='w', pady=(0, 6))
        config.pack_forget()

        actions = ttk.Frame(container)
        self.actions = actions
        actions.pack(fill='x', pady=(0, 10))
        self.start_button = ttk.Button(actions, text='▶  Start Test', command=self.start_test)
        self.start_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(actions, text='■  Stop', command=self.stop_test, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 8))
        self.resume_button = ttk.Button(actions, text='▶  Resume Test', command=self.resume_test, state='disabled')
        self.resume_button.pack(side='left', padx=(0, 8))
        self.retest_button = ttk.Button(actions, text='Rerun Selected Test Point', command=self.retest_noise)
        self.retest_button.pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='Clear Results', command=self.clear_results).pack(side='left')
        ttk.Label(container, text='Measurement Results', style='Section.TLabel').pack(anchor='w', pady=(5, 4))
        frame = ttk.Frame(container)
        frame.pack(fill='both', expand=True)
        columns = ('channel', 'scale', 'rms', 'runit', 'db', 'minimum', 'margin', 'dunit', 'result', 'samples')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        for col, label, width in [
            ('channel', 'Channel', 80), ('scale', 'Range', 105), ('rms', 'RMS noise', 105),
            ('runit', 'Units', 60), ('db', 'Noise level', 105), ('minimum', 'Minimum', 95),
            ('margin', 'Margin', 95), ('dunit', 'Units', 60), ('result', 'Result', 110), ('samples', 'Samples', 85)
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor='center', stretch=True)
        self.tree.tag_configure('pass', foreground=ui.C['good'])
        self.tree.tag_configure('fail', foreground=ui.C['bad'])
        self.tree.tag_configure('error', foreground=ui.C['warn'])
        self.tree.pack( side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.progress = ttk.Progressbar(container, maximum=36, mode='determinate')
        self.progress.pack(fill='x', pady=(12, 5))
        self.progress_text = tk.StringVar(value='Ready — 0 of 36 ranges')
        ttk.Label(container, textvariable=self.progress_text).pack(anchor='w')
        ttk.Label(container, text='PASS/FAIL compares measured noise dB against entered limits; no measurement-uncertainty guard band is applied. Verify setup and decision rule before release.', wraplength=1050).pack(anchor='w', pady=(7, 0))


    # ======================================================================== one results table, filterable by function
    FUNCS = (('noise', 'RMS noise'), ('dcv', 'DC voltage'), ('impedance', 'Input impedance'),
             ('offset', 'Offset (P1 mean)'), ('bandwidth', 'Bandwidth (LEVSINE)'), ('timebase', 'Time base'), ('trigger', 'Trigger level'))
    FUNC_NAME = dict(FUNCS)
    FUNC_NOTE = {
        'noise': 'RMS noise: external 50 \u03a9 termination on the channel under test; all channels ON, DC 1 M\u03a9, full bandwidth, 1 ms/div. The program sets P1 to StdDev of that channel and compares the noise level (dB) with the minimum limit.',
        'dcv': 'DC voltage: Fluke SCOPE output cable to the channel, DC 1 M\u03a9, 20 MHz BW. The program runs STBY, SCOPE DCV, OUT, OPER, reads scope P1 MEAN and returns the Fluke to STBY after every point.',
        'impedance': 'Input impedance: Fluke SCOPE measurement output (MEASR) to the channel input. The Fluke output is confirmed OFF before cables are moved.',
        'offset': 'Offset: P1 MEAN at the specified vertical offsets with the Fluke SCOPE DC output. This checks the sourced voltage at that offset, not waveform centring accuracy.',
        'bandwidth': 'Bandwidth: Fluke LEVSINE into the scope 50 \u03a9 input (no extra termination). 50 kHz reference against 1 GHz, scope P1 PkPk. The first point is a hardware pilot, then run again to continue.',
        'timebase': 'Time base: Fluke SCOPE time marker (period in Test settings, default 10 \u00b5s) into CH1 with a 50 \u03a9 cable; the program sets DC 50 \u03a9, full bandwidth and P1 Freq, averages the readings and compares the frequency error with \u00b10.350 Hz. The Fluke returns to STBY after the point.',
        'trigger': 'Trigger level: Fluke SCOPE output to the channel, 100 mV/div, DC 1 M\u03a9, 20 MHz BW. The scope is armed in Single at the level; the Fluke steps to 20 mV short of the level (must not trigger) and 20 mV past it (must trigger). You confirm both on screen; STBY after every point.',
    }

    def _rows_of(self, kind):
        return {'noise': self.rows, 'dcv': self.dc_rows, 'impedance': self.imp_rows, 'offset': self.offset_rows, 'bandwidth': self.bw_rows,
                'timebase': self.tb_rows, 'trigger': self.trig_rows}[kind]

    def _planned(self, kind):
        return len(self.noise_plan()) if kind == 'noise' else len(self._plan_points(kind))

    def _plan_points(self, kind):
        return {'dcv': self.dcv_points, 'impedance': self.impedance_points, 'offset': self.offset_points, 'bandwidth': self.bandwidth_points,
                'timebase': self.timebase_points, 'trigger': self.trigger_points}[kind]()

    def _pending(self, kind):
        return len(self._rows_of(kind)) < self._planned(kind)

    def entries(self):
        """Every planned point in every function, with its result when recorded. Display only: stored rows are unchanged."""
        out = []

        def add(kind, i, row, **kw):
            out.append(dict(kind=kind, idx=i, result=row['result'] if row else '', done=row is not None, **kw))
        for i, (ch, scale, limit) in enumerate(self.noise_plan()):
            r = self.rows[i] if i < len(self.rows) else None
            add('noise', i, r, channel=f'CH{ch}', range=self.range_text(scale), test='Noise level (minimum dB)', nominal='',
                low='' if limit is None else f'{limit:.2f}', high='', found=f"{r['db']:.2f}" if r else '', unit='dB')
        for i, p in enumerate(self.dcv_points()):
            r = self.dc_rows[i] if i < len(self.dc_rows) else None
            src = r or p
            (nom, lo, hi), reads, unit = ui.si_row([src['nominal_v'], src['lower_v'], src['upper_v']], 'V', [r['measured_v']] if r else [])
            add('dcv', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']), test='DC gain, 1 M\u03a9',
                nominal=self._signed(nom), low=self._signed(lo), high=self._signed(hi), found=self._signed(reads[0]) if reads else '', unit=unit)
        for i, p in enumerate(self.impedance_points()):
            r = self.imp_rows[i] if i < len(self.imp_rows) else None
            src = r or p
            (nom, lo, hi), reads, unit = ui.si_row([src['nominal_ohm'], src['lower_ohm'], src['upper_ohm']], 'ohm', [r['measured_ohm']] if r else [])
            add('impedance', i, r, channel=str(src['channel']), range=self.range_text(src['scale_v_div']), test=f"{src['description']} ({src['coupling']})",
                nominal=nom, low=lo, high=hi, found=reads[0] if reads else '', unit=unit)
        for i, p in enumerate(self.offset_points()):
            r = self.offset_rows[i] if i < len(self.offset_rows) else None
            src = r or p
            (off, nom, lo, hi), reads, unit = ui.si_row([src['scope_offset_v'], src['nominal_v'], src['lower_v'], src['upper_v']], 'V',
                                                        [r['measured_v']] if r else [], extra=3)
            add('offset', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']), test=f'Offset {self._signed(off)} {unit}',
                nominal=self._signed(nom), low=self._signed(lo), high=self._signed(hi), found=self._signed(reads[0]) if reads else '', unit=unit)
        for i, p in enumerate(self.bandwidth_points()):
            r = self.bw_rows[i] if i < len(self.bw_rows) else None
            src = r or p
            (amp,), _r, vunit = ui.si_row([src['amplitude_vpp']], 'Vpp')
            add('bandwidth', i, r, channel=f"CH{src['channel']}", range=self.range_text(src['scale_v_div']),
                test=f'Full BW, {amp} {vunit} 50 kHz vs 1 GHz', nominal='0', low='-3.000', high='+3.000',
                found=f"{r['response_db']:+.3f}" if r else '', unit='dB')
        for i, p in enumerate(self.timebase_points()):
            r = self.tb_rows[i] if i < len(self.tb_rows) else None
            src = r or p
            add('timebase', i, r, channel='CH1', range=f"{src['marker_period_s']*1e6:g} \u00b5s marker",
                test=f"Frequency error at {src['nominal_hz']/1e3:g} kHz", nominal='0.000', low=f"{src['lower_hz']:+.3f}",
                high=f"{src['upper_hz']:+.3f}", found=f"{r['error_hz']:+.4f}" if r else '', unit='Hz')
        for i, p in enumerate(self.trigger_points()):
            r = self.trig_rows[i] if i < len(self.trig_rows) else None
            add('trigger', i, r, channel=f"CH{p['channel']}", range=self.range_text(p['scale_v_div']),
                test=f"Trigger level, {p['slope'].lower()} slope", nominal=f"{p['level_v']*1000:+.2f}", low=f"{p['lower_v']*1000:+.2f}",
                high=f"{p['upper_v']*1000:+.2f}", found=r['outcome'] if r else '', unit='mV')
        return out

    def _pick_function(self, name):
        self.show_function.set('All functions' if name == 'All sections' else name)
        self.refresh_unified(force=True)

    def build_unified(self):
        root = self.root
        sh = self.shell
        self.msg = sh.status_var
        self.msg.set('Step 1: enter the Instrument ID. Step 2: check the connections. Step 3: Run Pending.')
        self.show_function = tk.StringVar(value='All functions')
        self.show_status = tk.StringVar(value='All points')
        self.chain = []
        self._idle = 0
        self._shown = None
        self._last_status = {}
        # strip: identity, As Found | As Left, progress ring
        box = ttk.Frame(sh.strip)
        box.pack(side='left')
        ttk.Label(box, text='Instrument ID *').pack(side='left')
        e = ttk.Entry(box, textvariable=self.instrument_id, width=16)
        e.pack(side='left', padx=(6, 12))
        e.focus_set()
        e.bind('<FocusOut>', lambda _e: self.sync_asset())
        e.bind('<Return>', lambda _e: self.sync_asset())
        ttk.Label(box, text='Serial').pack(side='left')
        ttk.Entry(box, textvariable=self.serial, width=14).pack(side='left', padx=(6, 14))
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if '--demo' in sys.argv:
            sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')

        # connections drawer
        d = sh.drawer_body
        d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
        ttk.Label(d, text='Teledyne LeCroy WaveSurfer 4104HD', style='Bold.TLabel').grid(row=0, column=1, sticky='w', padx=(10, 0))
        ttk.Separator(d).grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 10))
        ttk.Label(d, text='Scope VISA address').grid(row=2, column=0, sticky='w', pady=4)
        ttk.Entry(d, textvariable=self.visa_address, width=34).grid(row=2, column=1, sticky='ew', padx=(10, 0), pady=4)
        self.btn_scope = ttk.Button(d, text='Test scope', command=self.test_connection)
        self.btn_scope.grid(row=3, column=1, sticky='w', padx=(10, 0), pady=(0, 8))
        ttk.Label(d, text='Fluke 5560A VISA').grid(row=4, column=0, sticky='w', pady=4)
        ttk.Entry(d, textvariable=self.fluke_address, width=34).grid(row=4, column=1, sticky='ew', padx=(10, 0), pady=4)
        ttk.Label(d, text='Fluke baud').grid(row=5, column=0, sticky='w', pady=4)
        ttk.Entry(d, textvariable=self.fluke_baud, width=10).grid(row=5, column=1, sticky='w', padx=(10, 0), pady=4)
        ttk.Button(d, text='Test Fluke', command=self.test_fluke).grid(row=6, column=1, sticky='w', padx=(10, 0), pady=(0, 8))
        ttk.Separator(d).grid(row=7, column=0, columnspan=2, sticky='ew', pady=(4, 10))
        ttk.Button(d, text='Test settings...', command=self.show_settings_dialog).grid(row=8, column=0, columnspan=2, sticky='w')
        ttk.Label(d, text='Settle times, samples, channels and limits are in Test settings. Fluke output stays in STANDBY between points.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=9, column=0, columnspan=2, sticky='w', pady=(8, 0))

        # action bar
        self.btn_run = sh.add_action('\u25b6  Run All Pending', self.run_pending, accent=True, short='\u25b6  Run')
        self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
        self.btn_rerun = sh.add_action('Rerun Selected', self.rerun_selected, short='Rerun')
        self.btn_stop = sh.add_action('\u25a0  Stop', self.stop_all, danger=True, short='\u25a0 Stop', state='disabled')
        sh.add_action('Export Report (PDF)', self.export_pdf_report, side='right', short='PDF')
        sh.add_action('Export Excel (.xlsx)', self.export_professional_excel, side='right', short='Excel')
        self.btn_clear = sh.add_action('Clear function results', self.clear_function, side='right', short='Clear')

        body = sh.content
        info = ttk.Frame(body)
        info.pack(side='bottom', fill='x', pady=(8, 0))
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        filt = ttk.Frame(body)
        filt.pack(side='top', fill='x', pady=(0, 6))
        ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
        c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS, width=14, state='readonly')
        c2.pack(side='right')
        ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
        c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh_unified(force=True))
        self.utree = ui_shell.results_table(self, body, name_width=380, error=False)
        ui_shell.small_window(self, self.utree, filt)
        self.utree.bind('<<TreeviewSelect>>', self.on_unified_select)
        self.refresh_unified(force=True)
        self.root.after(500, self._unified_tick)
        import labregistry
        labregistry.attach(self.root, self.instrument_id, self.serial, self.msg.set)
        self.sync_asset()                       # --asset <ID> from the Manager

    # ======================================================================== As Found / As Left
    _KIND_ATTR = {'noise': 'rows', 'dcv': 'dc_rows', 'impedance': 'imp_rows', 'offset': 'offset_rows', 'bandwidth': 'bw_rows',
                  'timebase': 'tb_rows', 'trigger': 'trig_rows'}
    _SET_ATTRS = ('rows', 'run_config', 'dc_rows', 'imp_rows', 'offset_rows', 'bw_rows', 'tb_rows', 'trig_rows')
    _LEFT_TAG = '_AsLeft'

    @property
    def busy(self):
        return self._batch_busy()

    @property
    def _sets(self):
        if '_mode_sets' not in self.__dict__:
            self._mode_sets = {}
        return self._mode_sets

    def _stored_rows(self, mode, kind):
        """The result rows of one function for As Found or As Left (the other mode's rows are kept in memory while one mode is on screen)."""
        attr = self._KIND_ATTR[kind]
        if mode == self._mode:
            return getattr(self, attr)
        snap = self._sets.get(mode)
        return snap[attr] if snap else []

    def any_synthetic(self):
        return bool(getattr(self, 'demo_mode', False)) or '--demo' in sys.argv

    def _use_checkpoint_paths(self):
        """As Left results are saved in their own files beside the As Found ones (same name + _AsLeft)."""
        if '_found_paths' not in self.__dict__:
            self._found_paths = {a: getattr(self, a) for a in self.CKPT_BASE}
        for attr, p in self._found_paths.items():
            setattr(self, attr, p.with_name(p.stem + self._LEFT_TAG + p.suffix) if self._mode == datamode.LEFT else p)

    def _load_all_checkpoints(self):
        self.load_offset_checkpoint()
        self.load_bandwidth_checkpoint()
        self.load_timebase_checkpoint()
        self.load_trigger_checkpoint()
        self.load_checkpoint()
        self.load_dc_checkpoint()
        self.load_impedance_checkpoint()

    def _refresh_all_results(self):
        if self.run_config is None:
            self.resume_button.configure(state='disabled')
            self.progress['value'] = 0
            self.progress['maximum'] = 36
            self.progress_text.set('Ready \u2014 0 of 36 ranges')
        else:
            self.progress['maximum'] = self.total_ranges()
            self.progress['value'] = len(self.rows)
            self.progress_text.set(f'Completed {len(self.rows)} of {self.total_ranges()} ranges')
        self.refresh_noise_grid()
        self.refresh_dcv_table()
        self.refresh_impedance_table()
        self.refresh_offset()
        self.refresh_bandwidth()
        self.refresh_timebase()
        self.refresh_trigger()
        self.refresh_unified(force=True)

    def set_data_mode(self, mode, from_ui=False):
        if mode not in datamode.LABEL:
            return
        if self._batch_busy():                           # never switch in the middle of a measurement
            if from_ui:
                self.mode_var.set(self._mode)
            return
        if mode == self._mode:
            self._apply_mode_ui()
            return
        if not self.sync_asset():
            if from_ui:
                self.mode_var.set(self._mode)
            return
        self._sets[self._mode] = {a: getattr(self, a) for a in self._SET_ATTRS}
        config = self.run_config
        self._mode = mode
        self._use_checkpoint_paths()
        snap = self._sets.get(mode)
        self.tb_retest_index = self.trig_retest_index = self.dc_retest_index = self.noise_retest_index = self.noise_retest_result = None
        if snap is not None:
            for a, v in snap.items():
                setattr(self, a, v)
        else:
            for a in self._SET_ATTRS:
                setattr(self, a, [])
            self.run_config = json.loads(json.dumps(config)) if config else None     # same channels / limits / settings in both modes
            self._load_all_checkpoints()                                               # earlier session's results for this mode, if any
        self._apply_mode_ui()
        self._refresh_all_results()
        self.msg.set(f'Collecting {self.mode_label} data.' + (' Run the points again after the adjustment.' if mode == datamode.LEFT else ''))

    def run_section(self):
        if self.show_function.get() == 'All functions':
            messagebox.showinfo('Section', 'Choose a function in the Show box first.', parent=self.root)
            return
        self.run_pending()

    def _confirm_found_overwrite(self, kind, what):
        if self._mode != datamode.FOUND or not self._stored_rows(datamode.LEFT, kind):
            return True
        return messagebox.askyesno(
            'Replace the As Found reading?',
            f'{what} already has As Left readings, so the instrument has been adjusted since the As Found run.\n\n'
            'Measuring As Found again now replaces the original As Found reading with a reading from the adjusted instrument.\n\n'
            'To measure after an adjustment, switch to As Left instead.\n\nReplace the As Found reading anyway?', default='no', parent=self.root)

    def _visible_entry(self, e):
        fn, st = self.show_function.get(), self.show_status.get()
        if fn != 'All functions' and self.FUNC_NAME[e['kind']] != fn:
            return False
        if st == 'Not tested' and e['done']:
            return False
        if st == 'Passed' and e['result'] != 'PASS':
            return False
        if st == 'Failed (OOT)' and e['result'] != 'FAIL':
            return False
        if st == 'As Found failed':
            fr = self._stored_rows(datamode.FOUND, e['kind'])
            if not (e['idx'] < len(fr) and fr[e['idx']].get('result') == 'FAIL'):
                return False
        return True

    def _entries_for(self, mode):
        """entries() for As Found or As Left, whichever mode is on screen (the other mode's rows are swapped in for a moment)."""
        if mode == self._mode:
            return self.entries()
        snap = self._sets.get(mode)
        if not snap:
            return []
        saved = {a: getattr(self, a) for a in self._SET_ATTRS}
        try:
            for a, v in snap.items():
                setattr(self, a, v)
            return self.entries()
        finally:
            for a, v in saved.items():
                setattr(self, a, v)

    def refresh_unified(self, force=False):
        allp = self.entries()
        other = self._entries_for(datamode.FOUND if self.is_left else datamode.LEFT)
        found_e, left_e = (other, allp) if self.is_left else (allp, other)
        numbering = {(e['kind'], e['idx']): n for n, e in enumerate(allp, 1)}
        lookup = lambda lst: {(e['kind'], e['idx']): e for e in lst}
        fmap, lmap = lookup(found_e), lookup(left_e)
        with_unit = lambda v, u: f'{v} {u}'.strip() if v not in ('', None) else ''
        shown = [e for e in allp if self._visible_entry(e)]
        all_funcs = self.show_function.get() == 'All functions'
        items = []
        for e in shown:
            key = (e['kind'], e['idx'])
            tag = 'pass' if e['result'] == 'PASS' else 'fail' if e['result'] == 'FAIL' else 'pending'
            mark = {'PASS': '\u2714 PASS', 'FAIL': '\u2716 FAIL'}.get(e['result'], '\u2014')
            u = e['unit']
            low, high = with_unit(e['low'], u), with_unit(e['high'], u)
            limits = f'{low} \u2026 {high}' if e['high'] else (f'\u2265 {low}' if e['low'] else '')
            fe, le = fmap.get(key), lmap.get(key)
            found = with_unit(fe['found'], u) if fe and fe['done'] else ''
            left = with_unit(le['found'], u) if le and le['done'] else ('Same' if (self.is_left and fe and fe['done']) else '')
            name = f"{e['channel']}   {e['range']}   {e['test']}"
            if all_funcs:
                name = f"{self.FUNC_NAME[e['kind']]}  \u00b7  {name}"
            items.append((f"{e['kind']}:{e['idx']}", (numbering[key], name, with_unit(e['nominal'], u), low, high, limits, found, '', left, mark), (tag,)))
        total = len(allp)
        passed = sum(1 for e in allp if e['result'] == 'PASS')
        failed = sum(1 for e in allp if e['result'] == 'FAIL')
        sig = (tuple(items), total, tuple((e['kind'], e['done'], e['result']) for e in other))
        if force or sig != self._shown:
            self._shown = sig
            keep = self.utree.selection()
            self.utree.delete(*self.utree.get_children())
            for iid, values, tags in items:
                self.utree.insert('', 'end', iid=iid, values=values, tags=tags)
            for k in keep:
                if self.utree.exists(k):
                    self.utree.selection_set(k)
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
        self._entries_cache = {f"{e['kind']}:{e['idx']}": e for e in allp}

    def on_unified_select(self, _event=None):
        sel = self.utree.selection()
        if not sel:
            return
        e = self._entries_cache.get(sel[0])
        if not e:
            return
        limits = f"{e['low']} to {e['high']} {e['unit']}" if e['high'] else f"minimum {e['low']} {e['unit']}"
        found = f"  |  {self.mode_label}: {e['found']} {e['unit']}  ({e['result']})" if e['done'] else '  |  Not tested yet'
        self.detail.set(f"{self.FUNC_NAME[e['kind']]}  -  {e['channel']}  {e['range']}  -  {e['test']}\nAccept: {limits}{found}\nSetup: {self.FUNC_NOTE[e['kind']]}")

    # ---- which function is busy
    def _batch_busy(self):
        return any((self.running, self.dc_running, getattr(self, 'dc_batch', False), self.imp_running, getattr(self, 'imp_batch', False),
                    self.offset_running, getattr(self, 'offset_batch', False), self.bw_running, getattr(self, 'bw_batch', False),
                    getattr(self, 'tb_running', False), getattr(self, 'trig_running', False), getattr(self, 'trig_batch', False)))

    def _dialog_open(self):
        return any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children())

    def _selected_kind(self):
        name = self.show_function.get()
        return next((k for k, n in self.FUNCS if n == name), None)

    def _start_function(self, kind):
        if kind == 'noise':
            (self.resume_test if (self.rows or self.run_config) else self.start_test)()
        else:
            {'dcv': self.start_dcv_batch, 'impedance': self.start_impedance_batch, 'offset': self.start_offset, 'bandwidth': self.start_bandwidth,
             'timebase': self.start_timebase, 'trigger': self.start_trigger}[kind]()

    def run_pending(self):
        if self._batch_busy():
            messagebox.showwarning('Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if '--demo' not in sys.argv and not self.instrument_id.get().strip():
            messagebox.showinfo('Instrument ID needed', 'Enter the Instrument ID first. Results are saved separately for each instrument.', parent=self.root)
            return
        if not self.sync_asset():
            return
        only = self._selected_kind()
        kinds = [k for k, _n in self.FUNCS if (only is None or k == only) and self._pending(k)]
        if not kinds:
            messagebox.showinfo('Nothing pending', 'Every point in the selected function is already recorded.', parent=self.root)
            return
        self.chain, self._idle = kinds, 0
        self.msg.set('Running: ' + ', '.join(self.FUNC_NAME[k] for k in kinds))
        self._start_function(kinds[0])

    def stop_all(self):
        self.chain = []
        if self.running:
            self.stop_test()
        if self.dc_running or getattr(self, 'dc_batch', False):
            self.stop_dcv_batch()
        if self.imp_running or getattr(self, 'imp_batch', False):
            self.stop_impedance_batch()
        if self.offset_running or getattr(self, 'offset_batch', False):
            self.stop_offset()
        if self.bw_running or getattr(self, 'bw_batch', False):
            self.stop_bandwidth()
        if self.trig_running or self.trig_batch:
            self.stop_trigger()
        self.msg.set('Stopping after the current point. Completed points are saved.')

    def rerun_selected(self):
        if not self.sync_asset():
            return
        sel = self.utree.selection()
        if len(sel) != 1:
            messagebox.showinfo('Select a result', 'Select one completed test point in the table.', parent=self.root)
            return
        e = self._entries_cache[sel[0]]
        tree = {'noise': self.tree, 'dcv': self.dc_tree, 'impedance': self.imp_tree, 'offset': self.offset_tree, 'bandwidth': self.bw_tree,
                'timebase': self.tb_tree, 'trigger': self.trig_tree}[e['kind']]
        kids = tree.get_children()
        if not e['done'] or e['idx'] >= len(kids):
            messagebox.showinfo('Not tested yet', 'That point has not been measured yet. Use Run Pending, or pick a recorded point to rerun.', parent=self.root)
            return
        if not self._confirm_found_overwrite(e['kind'], 'This function'):
            return
        tree.selection_set(kids[e['idx']])
        {'noise': self.retest_noise, 'dcv': self.retest_selected_dcv, 'impedance': self.retest_impedance,
         'offset': self.retest_offset, 'bandwidth': self.retest_bandwidth, 'timebase': self.retest_timebase, 'trigger': self.retest_trigger}[e['kind']]()

    def clear_function(self):
        kind = self._selected_kind()
        if kind is None:
            messagebox.showinfo('Choose a function', 'Choose one function in the Show list first. Results are cleared one function at a time.', parent=self.root)
            return
        if self._batch_busy() or not self.sync_asset():
            return
        extra = '\n\nAs Left readings for this function are kept.' if self._mode == datamode.FOUND and self._stored_rows(datamode.LEFT, kind) else ''
        if not messagebox.askyesno('Clear results', f'Clear all saved {self.mode_label} {self.FUNC_NAME[kind]} results? This cannot be undone.' + extra, parent=self.root):
            return
        if kind == 'noise':
            self.clear_results()
        elif kind == 'dcv':
            self.clear_dcv()
        elif kind == 'impedance':
            self.clear_impedance()
        elif kind == 'offset':
            self.offset_rows.clear()
            self.offset_checkpoint.unlink(missing_ok=True)
            self.refresh_offset()
        elif kind == 'bandwidth':
            self.bw_rows.clear()
            self.bw_checkpoint.unlink(missing_ok=True)
            self.refresh_bandwidth()
        elif kind == 'timebase':
            self.tb_rows.clear()
            self.tb_checkpoint.unlink(missing_ok=True)
            self.refresh_timebase()
        else:
            self.trig_rows.clear()
            self.trig_checkpoint.unlink(missing_ok=True)
            self.refresh_trigger()
        self.refresh_unified(force=True)

    def _unified_tick(self):
        try:
            busy = self._batch_busy()
            self.refresh_unified()
            self.btn_run.configure(state='disabled' if busy else 'normal')
            self.btn_rerun.configure(state='disabled' if busy else 'normal')
            self.btn_section.configure(state='disabled' if busy else 'normal')
            for b in self.mode_buttons:
                b.configure(state='disabled' if busy else 'normal')
            self.btn_stop.configure(state='normal' if busy else 'disabled')
            self.btn_clear.configure(state='disabled' if busy else 'normal')
            for name in ('status', 'dc_status', 'imp_status', 'offset_status', 'bw_status', 'tb_status', 'trig_status', 'progress_text'):
                var = getattr(self, name, None)
                if var is not None and var.get() != self._last_status.get(name):
                    if name in self._last_status and var.get():
                        self.msg.set(var.get())
                    self._last_status[name] = var.get()
            if self.chain:
                if busy or self._dialog_open():
                    self._idle = 0
                else:
                    self._idle += 1
                    if self._idle >= 2:
                        self._idle = 0
                        if not self._pending(self.chain[0]):
                            self.chain.pop(0)
                            if self.chain:
                                self._start_function(self.chain[0])
                            else:
                                self.msg.set('Run complete. Export the report (PDF) when you are ready.')
                        else:
                            self.chain = []          # stopped, cancelled at a prompt, or an error: leave the rest to the technician
        except tk.TclError:
            return
        self.root.after(500, self._unified_tick)

    def show_settings_dialog(self):
        win = ui.dialog(self.root, 'Test settings')
        win.resizable(False, False)
        outer = ttk.Frame(win, padding=(22, 18, 22, 16))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Test settings', style='Section.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Used by Run Pending. Changing the RMS-noise settings after a run has started requires clearing that function first.',
                  style='Muted.TLabel', wraplength=ui.px(560), justify='left').pack(anchor='w', pady=(2, 10))
        grid = ttk.Frame(outer)
        grid.pack(fill='x')
        rows = (('RMS noise', None, None),
                ('  Channel', self.channel, 'combo'), ('  Test all 4 channels', self.all_channels, 'check'), ('  Settle (s)', self.delay, 'entry'),
                ('  Samples per range', self.samples, 'entry'), ('  dB factor (div)', self.ref_factor, 'entry'), ('  Minimum limits (dB), 9 values', self.limit_text, 'wide'),
                ('DC voltage', None, None),
                ('  Settle after OPER (s)', self.dc_settle, 'entry'), ('  Automatic Fluke output', self.dc_auto_fluke, 'check'), ('  Scope P1 MEAN acquisition', self.dc_p1_mode, 'check'),
                ('Input impedance', None, None), ('  Settle (s)', self.imp_settle, 'entry'), ('  Samples', self.imp_samples, 'entry'),
                ('Offset', None, None), ('  Settle (s)', self.offset_settle, 'entry'),
                ('Bandwidth', None, None), ('  Settle (s)', self.bw_settle, 'entry'),
                ('Time base', None, None), ('  Marker period (\u00b5s)', self.tb_period_us, 'entry'), ('  Settle after OPER (s)', self.tb_settle, 'entry'),
                ('  P1 Freq readings', self.tb_samples, 'entry'),
                ('Trigger level', None, None), ('  Settle after each step (s)', self.trig_settle, 'entry'))
        for r, (label, var, kind) in enumerate(rows):
            if kind is None:
                ttk.Label(grid, text=label, style='Bold.TLabel').grid(row=r, column=0, sticky='w', pady=(10, 2))
                continue
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky='w', pady=2)
            if kind == 'entry':
                ttk.Entry(grid, textvariable=var, width=10).grid(row=r, column=1, sticky='w', padx=(12, 0))
            elif kind == 'wide':
                ttk.Entry(grid, textvariable=var, width=34).grid(row=r, column=1, sticky='w', padx=(12, 0))
            elif kind == 'combo':
                ttk.Combobox(grid, textvariable=var, values=['1', '2', '3', '4'], width=6, state='readonly').grid(row=r, column=1, sticky='w', padx=(12, 0))
            else:
                ttk.Checkbutton(grid, variable=var).grid(row=r, column=1, sticky='w', padx=(12, 0))
        ttk.Label(outer, text='RMS noise: P1 StdDev and source are set automatically. Formula: 20 log10((factor x V/div) / RMS). The 2.75-division factor is user-reported as verified with Teledyne; confirm limits and decision rule before release.',
                  style='Muted.TLabel', wraplength=ui.px(560), justify='left').pack(anchor='w', pady=(12, 0))
        ttk.Button(outer, text='Close', style='Accent.TButton', command=win.destroy).pack(anchor='e', pady=(12, 0))
        win.bind('<Escape>', lambda _e: win.destroy())
        self.root.wait_window(win)


    # ======================================================================== per-asset checkpoints
    CKPT_BASE = {'checkpoint_path': 'rms_noise_checkpoint_v5', 'dc_checkpoint': 'dcv_checkpoint_v6', 'offset_checkpoint': 'offset_mean_checkpoint_v28',
                 'bw_checkpoint': 'bandwidth_checkpoint_v29', 'imp_checkpoint': 'impedance_checkpoint_v11',
                 'tb_checkpoint': 'timebase_checkpoint_v1', 'trig_checkpoint': 'trigger_level_checkpoint_v1'}

    def _asset_key(self):
        return ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.instrument_id.get().strip()) or 'UNASSIGNED'

    def _set_ckpt_paths(self, key):
        """Results are saved per Instrument ID, e.g. dcv_checkpoint_v6_WS-77_A.json, like the other procedures."""
        self._ckpt_key = key
        for attr, base in self.CKPT_BASE.items():
            setattr(self, attr, appdata.progress_path(f'{base}_{key}.json'))
        self.__dict__.pop('_found_paths', None)

    def sync_asset(self):
        """Switch to the saved results of the Instrument ID now in the entry (called when the entry is left, and before every run, rerun,
        clear and export, so a report can never carry another instrument's results). Returns False if it cannot switch right now."""
        self._pm_begin()
        if '--demo' in sys.argv:
            return True
        key = self._asset_key()
        if key == self._ckpt_key:
            return True
        if self._batch_busy():
            self.instrument_id.set(self._ckpt_id)
            messagebox.showwarning('Busy', 'The Instrument ID cannot change while a measurement is running.', parent=self.root)
            return False
        self._mode_sets = {}
        self._mode = datamode.FOUND                 # another instrument starts on As Found
        self._set_ckpt_paths(key)
        self._ckpt_id = self.instrument_id.get().strip()
        self._apply_mode_ui()
        self.rows, self.run_config = [], None
        self.dc_rows, self.imp_rows, self.offset_rows, self.bw_rows = [], [], [], []
        self.tb_rows, self.trig_rows = [], []
        self.tb_retest_index = self.trig_retest_index = None
        self.dc_retest_index = self.noise_retest_index = self.noise_retest_result = None
        if key != 'UNASSIGNED':
            self._adopt_legacy_results(key)
        self._load_all_checkpoints()
        self._refresh_all_results()
        have = sum(len(r) for r in (self.rows, self.dc_rows, self.imp_rows, self.offset_rows, self.bw_rows, self.tb_rows, self.trig_rows))
        self._pm_restore_sidecar(have)
        self.msg.set(f'Instrument {self._ckpt_id or key}: restored {have} saved result(s).' if have else f'Instrument {self._ckpt_id or key}: no saved results yet.')
        return True

    # ======================================================================== procedure modifications (procmods_engine)
    # What can be modified on this procedure: the settle times and sample counts of every section (they are the entry-box defaults, so a
    # technician can still change them for a run), the time base read gap, the command templates of the drivers, and the TOLERANCE of the
    # DCV / impedance / offset / bandwidth / time base / trigger points (developer mode).  Not modifiable here: skipping a point (the
    # sections save their results by position), the RMS-noise minimum limits (already a box on the screen) and every safety prompt.
    def _pm_begin(self):
        """Load the saved modifications for the Instrument ID now in the entry.  Called from sync_asset (before every run); never while a
        measurement is running; never raises."""
        try:
            if self._batch_busy():
                return
            self.pm_begin_run(None, self.instrument_id.get().strip())
            self._pm_defaults()
            self._pm_write_sidecar()
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'procedure modifications could not be loaded ({type(exc).__name__})')

    def _pm_defaults(self):
        """Move each entry box to its (modified) default, but only if the technician has not typed something else there."""
        for var, name, default, text in PM_VARS:
            box = getattr(self, var)
            want = self.pm_text(name, default, text)
            if box.get() == self._pm_ws_last.get(var, text) and want != box.get():
                box.set(want)
            if box.get() == want:
                self._pm_ws_last[var] = want

    def _pm_sidecar(self):
        return appdata.progress_path(f'ws4104hd_overrides_{self._asset_key()}.json')

    def _pm_write_sidecar(self):
        """The five-plus checkpoint files have no room for the modification snapshot, so it is kept next to them (only for modified runs)."""
        st = self.pm_state
        if st is None or not st.oset or not st.snapshot:
            return
        path = self._pm_sidecar()
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'asset': self.instrument_id.get().strip(), 'overrides': st.snapshot}, indent=2), encoding='utf-8')
        tmp.replace(path)

    def _pm_restore_sidecar(self, have):
        """Results exist for this instrument: continue under the modifications they were taken with (the saved snapshot), unless the
        store has changed and pm_choose(diff) says 'current'."""
        try:
            path = self._pm_sidecar()
            if have and path.exists():
                self.pm_on_checkpoint(json.loads(path.read_text(encoding='utf-8')), choose=getattr(self, 'pm_choose', None))
                self._pm_defaults()
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'the saved modification record could not be read ({type(exc).__name__})')

    @staticmethod
    def _pm_view(section, p):
        """The point as procmods sees it (the field names it keys and limits on)."""
        nom, lo, hi, idf = PM_SECTIONS[section]
        unit = {'dcv': 'V', 'impedance': 'ohm', 'offset': 'V', 'bandwidth': 'dB', 'timebase': 'Hz', 'trigger': 'V'}[section]
        rest = [f for f in idf if f not in ('channel', 'scale_v_div', 'description')]
        return dict(section=section, kind=section.upper(), nominal=(p.get(nom) if nom else None), low=p[lo], high=p[hi], unit=unit,
                    ch=p.get('channel'), range=p.get('scale_v_div'), stim='|'.join(str(p[f]) for f in rest) or None,
                    desc=p.get('description'))

    def pm_limit_views(self):
        """{section: [views of the FACTORY points]} - what the tolerance editor must key and check its overrides against."""
        return {sec: [self._pm_view(sec, p) for p in self._pm_factory(sec)] for sec in PM_SECTIONS}

    def _pm_factory(self, section):
        fn = getattr(type(self), PM_POINT_METHODS[section])
        return fn.pm_orig() if fn.pm_static else fn.pm_orig(self)

    def pm_section_points(self, section, pts):
        """`pts` unchanged (the same list) unless a valid, enabled, HMAC-verified limit override is in effect; then copies of the points
        concerned with the new low / high.  Nothing but the low / high of those points can change (procmods' guard is re-run)."""
        st = self.pm_state
        if st is None or not st.oset or not st.oset.has_limits:
            return pts
        try:
            nom, lo, hi, idf = PM_SECTIONS[section]
            views = [self._pm_view(section, p) for p in pts]
            patched, lim = st.patch(views)
            out = []
            for i, (p, q) in enumerate(zip(pts, patched)):
                if i in lim:
                    r = dict(p)
                    r[lo], r[hi] = q['low'], q['high']
                    r['limit_modified'], r['limit_factory'] = True, q['limit_factory']
                    out.append(r)
                else:
                    out.append(p)
            return out
        except Exception as exc:                       # anything wrong: the manufacturer's tolerances, and say so
            st.warnings.append(f'tolerance changes for {section} could not be applied ({type(exc).__name__}); factory tolerances are used')
            return pts

    def _pm_limits_ok(self, row, section, factory):
        """A saved row's tolerance is acceptable when it is the factory one, the current one, or the row says it was a modified one."""
        _n, lo, hi, _i = PM_SECTIONS[section]
        got = (row.get(lo), row.get(hi))
        cur = tuple(factory)
        pts = getattr(self, PM_POINT_METHODS[section])()
        return got == cur or bool(row.get('limit_modified')) or any((p[lo], p[hi]) == got for p in pts)

    def _pm_ckpt_points(self, section, rows):
        """The points a saved result file is compared with.  Identical to the plain points unless a tolerance modification exists or the
        saved rows carry one; then a row's own tolerance is accepted (results taken under a modification stay loadable)."""
        cur = getattr(self, PM_POINT_METHODS[section])()
        _n, lo, hi, _i = PM_SECTIONS[section]
        modified = isinstance(rows, list) and any(isinstance(r, dict) and r.get('limit_modified') for r in rows)
        if not isinstance(rows, list) or not (modified or (self.pm_state is not None and self.pm_state.oset and self.pm_state.oset.has_limits)):
            return cur
        fac = self._pm_factory(section)
        out = []
        for i, c in enumerate(cur):
            r = rows[i] if i < len(rows) and isinstance(rows[i], dict) else None
            if r is not None and r.get(lo) is not None and r.get(hi) is not None \
                    and (bool(r.get('limit_modified')) or (r[lo], r[hi]) in ((fac[i][lo], fac[i][hi]), (c[lo], c[hi]))):
                c = dict(c)
                c[lo], c[hi] = r[lo], r[hi]
            out.append(c)
        return out

    def _adopt_legacy_results(self, key):
        """Older versions saved one set of results for every instrument. Offer to assign that set to this Instrument ID, once."""
        old = {attr: Path(__file__).with_name(f'{base}.json') for attr, base in self.CKPT_BASE.items()}
        legacy = [(a, p) for a, p in old.items() if p.exists() and not getattr(self, a).exists()]
        if not legacy:
            return
        if not messagebox.askyesno('Earlier results found',
                                   f'Results saved by an earlier version (not tied to an instrument) were found.\n\nAssign them to {self._ckpt_id or key}?\n\n'
                                   'Choose No to leave them untouched (they are not deleted).', parent=self.root):
            return
        for attr, path in legacy:
            try:
                path.replace(getattr(self, attr))
            except OSError:
                pass

    def update_tab_titles(self):
        """Show progress on each tab, e.g. 'DC Voltage  12/80', with a tick when complete."""
        try:
            items = ((self.rms_tab, 'RMS Noise', len(self.rows), self.total_ranges()),
                     (self.dc_window, 'DC Voltage', len(self.dc_rows), 80),
                     (self.imp_window, 'Input Impedance', len(self.imp_rows), 28),
                     (self.offset_tab, 'Offset / P1 Mean', len(self.offset_rows), 16),
                     (self.bw_tab, 'Bandwidth / LEVSINE', len(self.bw_rows), 24),
                     (self.tb_tab, 'Time Base', len(self.tb_rows), 1),
                     (self.trig_tab, 'Trigger Level', len(self.trig_rows), 24))
            for tab, name, done, total in items:
                text = f'  {name}  \u2714  ' if done and done >= total else f'  {name}  {done}/{total}  ' if done else f'  {name}  '
                if self.tabs.tab(tab, 'text') != text:
                    self.tabs.tab(tab, text=text)
            if self.connected:
                self.conn_pill.set('Scope: connected', 'good')
            elif 'fail' in self.status.get().lower():
                self.conn_pill.set('Scope: connection failed', 'bad')
        except tk.TclError:
            return
        self.root.after(1000, self.update_tab_titles)

    def make_dcv_ui(self):
        # DC Voltage has its own tab; no duplicate toolbar buttons needed.
        pass

    def toggle_settings(self):
        if self.show_settings.get():
            self.config_frame.pack(fill='x', pady=(0, 10), before=self.actions)
        else:
            self.config_frame.pack_forget()

    def set_running(self, value):
        self.running = value
        self.start_button.configure(state='disabled' if value else 'normal')
        self.stop_button.configure(state='normal' if value else 'disabled')
        self.connect_button.configure(state='disabled' if value else 'normal')
        self.channel_select.configure(state='disabled' if value else 'readonly')
        self.resume_button.configure(state='disabled' if value or self.run_config is None or len(self.rows) >= self.total_ranges() else 'normal')
        if hasattr(self, 'retest_button'):
            self.retest_button.configure(state='disabled' if value else 'normal')

    def test_connection(self):
        if self.running:
            return
        self.status.set('Connecting...')
        address = self.visa_address.get().strip()
        def work():
            scope = None
            try:
                _f, scope = self.open_bench(None, 0, address, drivers.CommandLog())
                scope.open(verify_model=False)
                self.events.put(('connection', True, scope.identify()))
            except Exception as exc:
                self.events.put(('connection', False, str(exc)))
            finally:
                if scope is not None:
                    scope.close()
        threading.Thread(target=work, daemon=True).start()

    def get_config(self):
        delay = float(self.delay.get())
        samples = int(self.samples.get())
        factor = float(self.ref_factor.get())
        limits = [float(x.strip()) for x in self.limit_text.get().split(',')]
        if not math.isfinite(delay) or not 0.2 <= delay <= 120:
            raise ValueError('Settle time must be 0.2 to 120 seconds.')
        if not 1 <= samples <= 100:
            raise ValueError('Samples must be 1 to 100.')
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError('dB reference factor must be positive.')
        if len(limits) != 9 or not all(math.isfinite(x) for x in limits):
            raise ValueError('Enter exactly nine finite minimum dB limits.')
        return dict(address=self.visa_address.get().strip(), channel=int(self.channel.get()),
                    channels=[1, 2, 3, 4] if self.all_channels.get() else [int(self.channel.get())],
                    delay=delay, samples=samples, factor=factor, limits=limits)

    def save_checkpoint(self):
        if self.run_config is None:
            return
        data = {'configuration': self.run_config, 'rows': self.rows}
        temp = self.checkpoint_path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temp.replace(self.checkpoint_path)

    def total_ranges(self):
        return len(self.run_config['channels']) * len(SCALES) if self.run_config else 36

    def load_checkpoint(self):
        if not self.checkpoint_path.exists():
            return
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding='utf-8'))
            config, rows = data['configuration'], data['rows']
            channels = config['channels']
            if not isinstance(rows, list) or len(rows) > 9 * len(channels):
                raise ValueError('Invalid checkpoint length')
            for i, row in enumerate(rows):
                ch, scale = channels[i // 9], SCALES[i % 9]
                if row['channel'] != ch or not math.isclose(row['scale_v_div'], scale, rel_tol=1e-8):
                    raise ValueError('Saved results do not match channel/scale order')
            self.run_config = config
            self.visa_address.set(config['address'])
            self.channel.set(str(config['channel']))
            self.all_channels.set(len(channels) == 4)
            self.delay.set(str(config['delay']))
            self.samples.set(str(config['samples']))
            self.ref_factor.set(str(config['factor']))
            self.limit_text.set(','.join(map(str, config['limits'])))
            for row in rows:
                self.add_result(row)
            self.progress_text.set(f'Restored {len(rows)} of {self.total_ranges()} ranges')
            self.set_running(False)
        except Exception as exc:
            self.status.set(f'Checkpoint could not be loaded: {exc}')

    # ---- grids list every planned test point up front; as-found values fill in as the run goes
    @staticmethod
    def _set_grid(tree, items, active=None):
        """items = [(values, tags), ...]. Updates rows in place, keeps selection, scrolls to `active`."""
        keep = tree.index(tree.selection()[0]) if tree.selection() else None
        ids = list(tree.get_children())
        if len(ids) != len(items):
            tree.delete(*ids)
            ids = [tree.insert('', 'end') for _ in items]
        for iid, (values, tags) in zip(ids, items):
            tree.item(iid, values=values, tags=tags)
        if keep is not None and keep < len(ids):
            tree.selection_set(ids[keep])
        if active is not None and ids:
            tree.see(ids[min(active + 3, len(ids) - 1)])  # keep a few finished rows in view above it
            tree.see(ids[min(active, len(ids) - 1)])
        return ids

    @staticmethod
    def range_text(scale):
        """Vertical scale as a scaled value with its unit, e.g. 0.01 -> '10 mV/div'."""
        if scale is None:
            return 'EXT'
        text, unit = ui.si_one(scale, 'V', sig=3)
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return f'{text} {unit}/div'

    @staticmethod
    def _signed(text):
        return text if not text or text.startswith('-') or text.strip('0.') == '' else '+' + text

    @staticmethod
    def _tag(done, i, result=None):
        if i < done:
            return ('pass' if str(result).upper() == 'PASS' else 'fail',)
        return ('next',) if i == done else ('pending',)

    def noise_plan(self):
        """(channel, V/div, minimum dB) for every range: the saved run if there is one, else the current settings."""
        if self.run_config:
            channels, limits = self.run_config['channels'], self.run_config['limits']
        else:
            try:
                channels = [1, 2, 3, 4] if self.all_channels.get() else [int(self.channel.get())]
            except ValueError:
                channels = [1]
            try:
                limits = [float(x) for x in self.limit_text.get().split(',')]
            except ValueError:
                limits = []
            if len(limits) != 9:
                limits = [None] * 9
        return [(ch, SCALES[i], limits[i]) for ch in channels for i in range(9)]

    def refresh_noise_grid(self):
        plan = self.noise_plan()
        items = []
        for i, (ch, scale, limit) in enumerate(plan):
            if i < len(self.rows):
                row = self.rows[i]
                rms_text, rms_unit = ui.si_one(row['rms_volts'], 'V')
                values = (f"CH{row['channel']}", self.range_text(row['scale_v_div']), rms_text, rms_unit, f"{row['db']:.2f}",
                          f"{row['minimum_db']:.2f}", f"{row['margin_db']:+.2f}", 'dB', row['result'], row['samples'])
                items.append((values, self._tag(len(self.rows), i, row['result'])))
            else:
                values = (f'CH{ch}', self.range_text(scale), '', 'V', '', '' if limit is None else f'{limit:.2f}', '', 'dB', '\u2014', '')
                items.append((values, self._tag(len(self.rows), i)))
        self._set_grid(self.tree, items, active=len(self.rows))
        if not self.run_config and not self.rows:
            self.progress['maximum'] = max(len(plan), 1)
            self.progress['value'] = 0
            self.progress_text.set(f'Ready — 0 of {len(plan)} ranges')

    def _noise_settings_changed(self):
        if not self.running and not self.rows and hasattr(self, 'tree'):
            self.refresh_noise_grid()

    def add_result(self, row):
        self.rows.append(row)
        self.refresh_noise_grid()
        self.progress['maximum'] = self.total_ranges()
        self.progress['value'] = len(self.rows)
        self.progress_text.set(f'Completed {len(self.rows)} of {self.total_ranges()} ranges')

    def confirm_channel(self, channel, scale):
        return ui.confirm_steps(self.root, 'Prepare channel', f'Prepare CH{channel} for the next measurement',
            [('Move the 50 \u03a9 termination', f'Put the external 50 \u03a9 BNC termination on CH{channel}.'),
             ('Check the scope', 'All four channels ON, DC 1 M\u03a9, full bandwidth, 1 ms/div, averaging / ERES off.'),
             ('Automatic', f'The program sets P1 to StdDev of CH{channel} for you.')],
            facts=[('Channel', f'CH{channel}'), ('Range', self.range_text(scale))],
            caution='Cancel keeps all completed results saved so you can Resume.',
            ok='Ready \u2014 start measuring')

    def launch_remaining(self, resume=False):
        if self.running or self.run_config is None or len(self.rows) >= self.total_ranges():
            return
        config = self.run_config
        index = len(self.rows)
        channel = config['channels'][index // 9]
        scale = SCALES[index % 9]
        # Resume without a redundant prompt only when the next point uses
        # the same physical channel as the last completed measurement.
        # A channel transition still requires moving the BNC termination.
        same_channel_resume = (
            resume and bool(self.rows) and self.rows[-1]['channel'] == channel
        )
        if not same_channel_resume and not self.confirm_channel(channel, scale):
            self.progress_text.set(f'Paused — {index} of {self.total_ranges()} ranges saved')
            self.set_running(False)
            return
        self.stop_event.clear()
        self.set_running(True)
        threading.Thread(target=self.worker,
            args=(config['address'], channel, config['delay'], config['samples'],
                  config['factor'], config['limits'], index % 9), daemon=True).start()

    def retest_noise(self):
        idx = self._retest_index(self.tree, self.rows, 'RMS noise', self.rms_tab)
        if idx is None:
            return
        if self.run_config is None:
            messagebox.showinfo('No saved run', 'Start a test first.')
            return
        config = self.run_config
        row = self.rows[idx]
        channel, scale_index = row['channel'], idx % len(SCALES)
        if not self.confirm_channel(channel, SCALES[scale_index]):
            return
        self.noise_retest_index = idx
        self.noise_retest_result = None
        self.stop_event.clear()
        self.set_running(True)
        self.progress_text.set(f'Retesting point {idx+1} of {self.total_ranges()} (CH{channel}, {self.range_text(SCALES[scale_index])})')
        threading.Thread(target=self.worker,
            args=(config['address'], channel, config['delay'], config['samples'],
                  config['factor'], config['limits'], scale_index, scale_index + 1), daemon=True).start()

    def resume_test(self):
        if self.running or self.run_config is None or len(self.rows) >= self.total_ranges():
            return
        try:
            if self.get_config() != self.run_config:
                messagebox.showerror('Settings changed',
                    'Settings differ from the saved run. Restore the original settings before resuming.')
                return
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Invalid configuration', str(exc))
            return
        self.launch_remaining(resume=True)

    def start_test(self):
        if self.running:
            return
        try:
            config = self.get_config()
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Invalid configuration', str(exc))
            return
        chans = ', '.join(f'CH{c}' for c in config['channels'])
        if not ui.confirm_steps(self.root, 'New test', 'Start a new RMS noise test',
            [('Saved results', 'Existing saved noise results will be cleared.'),
             ('Method', 'Confirm the 2.75-division method and the limits are applicable.')],
            facts=[('Channels', chans), ('Ranges', f'{self.total_ranges()} measurements')],
            ok='Clear and start'):
            return
        self.clear_results()
        self.run_config = config
        self.progress['maximum'] = self.total_ranges()
        self.refresh_noise_grid()
        self.save_checkpoint()
        self.launch_remaining()

    def worker(self, address, channel, delay, samples, factor, limits, start_index=0, stop_index=None):
        log = drivers.CommandLog()
        scope = None
        try:
            _f, scope = self.open_bench(None, 0, address, log)
            scope.open()
            self.reset_bench(None, scope, log)       # reset to default settings before the first point
            ident = scope.idn
            self.events.put(('status', f'Connected: {ident}'))
            scope.configure_p1(channel, 'StandardDeviation')
            self.events.put(('status', f'P1 configured: waveform StdDev of CH{channel} (readback verified)'))
            for idx in range(start_index, len(SCALES) if stop_index is None else stop_index):
                scale, limit = SCALES[idx], limits[idx]
                if self.stop_event.is_set():
                    break
                # Set the range and confirm the instrument actually accepted it.
                scope.set_vertical_scale(channel, scale, settle=0.0)
                if self.stop_event.wait(delay):
                    break
                readings = []
                for _ in range(samples):
                    if self.stop_event.is_set():
                        break
                    volts = scope.read_p1()
                    if volts <= 0:
                        raise ValueError(f'Invalid P1 value at {scale} V/div: {volts!r}')
                    readings.append(volts)
                    if self.stop_event.wait(0.3):
                        break
                if len(readings) != samples:
                    break
                avg_rms = sum(readings) / len(readings)
                db = 20 * math.log10(factor * scale / avg_rms)
                row = dict(timestamp=datetime.now().isoformat(timespec='seconds'),
                           instrument=ident, channel=channel, scale_v_div=scale,
                           rms_volts=avg_rms, db=db,
                           minimum_db=limit, margin_db=db-limit,
                           result='PASS' if db >= limit else 'FAIL',
                           samples=samples, reference_factor_div=factor,
                           note='2.75-division method reported verified with Teledyne by user; no guard band')
                self.events.put(('row', row))
            self.events.put(('done', self.stop_event.is_set()))
        except Exception as exc:
            self.events.put(('error', str(exc)))
        finally:
            if scope is not None:
                try:
                    scope.close()
                except Exception:
                    pass
            self.save_command_log(log, f'RMS noise CH{channel}')

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'ask':
                    _k, title, question, reply = event
                    reply.put(messagebox.askyesnocancel(title, question, parent=self.root))
                elif kind == 'tb_result':
                    self.record_timebase(event[1], event[2], event[3] if len(event) > 3 else ())
                elif kind in ('tb_error', 'tb_safety'):
                    self.tb_retest_index = None
                    if kind == 'tb_error':
                        self.tb_status.set('ERROR: ' + event[1])
                    messagebox.showerror('Time base error' if kind == 'tb_error' else 'Fluke output safety', event[1], parent=self.root)
                elif kind == 'tb_idle':
                    self.tb_running = False
                elif kind == 'trig_result':
                    self.record_trigger(event[1], event[2])
                    self.trig_ok = True
                elif kind in ('trig_error', 'trig_safety', 'trig_cancel'):
                    self.trig_retest_index = None
                    self.trig_batch = False
                    self.trig_ok = False
                    if kind == 'trig_cancel':
                        self.trig_status.set(event[1])
                    else:
                        if kind == 'trig_error':
                            self.trig_status.set('ERROR: ' + event[1])
                        messagebox.showerror('Trigger level error' if kind == 'trig_error' else 'Fluke output safety', event[1], parent=self.root)
                elif kind == 'trig_idle':
                    self.trig_running = False
                    if self.trig_batch and self.trig_ok:
                        self.trig_ok = False
                        self.root.after(250, self.next_trigger)
                if kind == 'bw_result':
                    self.record_bandwidth(event[1],event[2],event[3])
                    self.bw_ok = True
                elif kind == 'bw_error':
                    self.bw_retest_index = None
                    self.bw_batch = False
                    self.bw_ok = False
                    self.bw_status.set('ERROR: '+event[1])
                    messagebox.showerror('Bandwidth error',event[1],parent=self.root)
                elif kind == 'bw_safety':
                    self.bw_retest_index = None
                    self.bw_batch = False
                    self.bw_ok = False
                    messagebox.showerror('Fluke output safety',event[1],parent=self.root)
                elif kind == 'bw_idle':
                    self.bw_running = False
                    if self.bw_batch and self.bw_ok:
                        self.bw_ok = False
                        self.root.after(250,self.next_bandwidth)
                if kind == 'offset_result':
                    self.record_offset(event[1], event[2], event[3])
                    self.offset_ok = True
                elif kind == 'offset_error':
                    self.offset_retest_index = None
                    self.offset_batch = False
                    self.offset_ok = False
                    self.offset_status.set('ERROR: ' + event[1])
                    messagebox.showerror('Offset measurement error', event[1], parent=self.root)
                elif kind == 'offset_safety':
                    self.offset_retest_index = None
                    self.offset_batch = False
                    self.offset_ok = False
                    messagebox.showerror('Fluke safety', event[1], parent=self.root)
                elif kind == 'offset_idle':
                    self.offset_running = False
                    if self.offset_batch and self.offset_ok:
                        self.offset_ok = False
                        self.root.after(250, self.next_offset)
                if kind == 'connection':
                    self.connected = event[1]
                    self.status.set(('Connected: ' if event[1] else 'Connection failed: ') + event[2])
                elif kind == 'dc_value':
                    if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
                        self.dc_next_button.configure(state='normal')
                        if messagebox.askyesno('Confirm P1 reading', f'Scope P1 returned {event[2]:+.6f} V.\n\nIs P1 set to MEAN of CH{event[1]["channel"]} and is this reading valid?', parent=self.root):
                            self.record_dcv(event[1],event[2],'scope P1 MEAN (operator confirmed)')
                elif kind == 'dc_auto_value':
                    if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
                        if self.dc_retest_index is not None:
                            idx = self.dc_retest_index
                            self.dc_retest_index = None
                            self.record_dcv(event[1], event[2],
                                'automatic Fluke SCOPE DCV / selected-point retest')
                        elif self.dc_batch:
                            self.record_dcv(event[1], event[2], 'automatic Fluke SCOPE DCV / single P1 MEAN reading')
                            self.dc_batch_point_ok = True
                        elif messagebox.askyesno('Confirm automatic DCV reading',
                            f'Fluke returned to STBY. Scope P1 returned {event[2]:+.6f} V.\n\n'
                            f'Was P1 configured to MEAN of CH{event[1]["channel"]}, and is this result valid?',
                            parent=self.root):
                            self.record_dcv(event[1], event[2], 'automatic Fluke SCOPE DCV / single P1 MEAN reading')
                elif kind == 'dc_idle':
                    self.dc_running = False
                    if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
                        self.dc_next_button.configure(state='normal')
                        if self.dc_batch and self.dc_batch_point_ok:
                            self.dc_batch_point_ok = False
                            self.root.after(200, self.next_dcv)
                elif kind == 'dc_safety':
                    self.dc_retest_index = None
                    self.dc_batch = False
                    messagebox.showerror('OUTPUT SAFETY WARNING', event[1])
                elif kind == 'dc_error':
                    self.dc_retest_index = None
                    self.dc_batch = False
                    if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
                        self.dc_next_button.configure(state='normal')
                    messagebox.showerror('DCV read error', event[1])
                elif kind == 'imp_result':
                    self.record_impedance(event[1], event[2], event[3])
                    self.imp_batch_success = True
                elif kind == 'imp_error':
                    self.imp_retest_index = None
                    self.imp_batch = False
                    self.imp_batch_success = False
                    self.imp_status.set('Impedance measurement error — point not recorded')
                    messagebox.showerror('Impedance measurement error', event[1], parent=getattr(self,'imp_window',self.root))
                elif kind == 'imp_safety':
                    self.imp_retest_index = None
                    self.imp_batch = False
                    self.imp_batch_success = False
                    messagebox.showerror('FLUKE SCOPE MODE', event[1], parent=getattr(self,'imp_window',self.root))
                elif kind == 'imp_idle':
                    self.imp_running = False
                    if getattr(self, 'imp_window', None) and self.imp_window.winfo_exists():
                        self.imp_next_button.configure(state='normal')
                        if self.imp_batch and self.imp_batch_success:
                            self.imp_batch_success = False
                            self.root.after(300, self.next_impedance)
                elif kind == 'fluke':
                    self.status.set(('Fluke connected: ' if event[1] else 'Fluke error: ') + event[2])
                    messagebox.showinfo('Fluke connection', event[2]) if event[1] else messagebox.showerror('Fluke connection', event[2])
                elif kind == 'status':
                    self.status.set(event[1])
                elif kind == 'row' and self.noise_retest_index is not None:
                    idx = self.noise_retest_index
                    self.rows[idx] = event[1]
                    self.refresh_noise_grid()
                    self.save_checkpoint()
                    self.noise_retest_result = f'Point {idx+1} retested — {event[1]["result"]}'
                elif kind == 'row':
                    self.add_result(event[1])
                    self.save_checkpoint()
                elif kind == 'done' and self.noise_retest_index is not None:
                    self.noise_retest_index = None
                    self.set_running(False)
                    self.progress_text.set(self.noise_retest_result or 'Retest stopped — previous result kept')
                elif kind == 'done':
                    self.set_running(False)
                    if event[1]:
                        self.progress_text.set(f'Stopped — {len(self.rows)} of {self.total_ranges()} ranges saved')
                    elif len(self.rows) == self.total_ranges():
                        self.progress_text.set(f'Completed — {len(self.rows)} of {self.total_ranges()} ranges')
                        messagebox.showinfo('Test complete', 'All selected channels are complete. Export the report (PDF) to save it.')
                    else:
                        # Schedule on the Tk event loop so the next channel is
                        # prepared only after the previous VISA session closes.
                        self.root.after(300, self.launch_remaining)
                elif kind == 'error' and self.noise_retest_index is not None:
                    self.noise_retest_index = None
                    self.set_running(False)
                    self.progress_text.set('Retest failed — previous result kept')
                    messagebox.showerror('Measurement error', event[1])
                elif kind == 'error':
                    self.set_running(False)
                    self.status.set('Test error — completed ranges preserved; use Resume Test')
                    self.progress_text.set(f'Interrupted — {len(self.rows)} of {self.total_ranges()} ranges saved')
                    messagebox.showerror('Measurement error', event[1])
        except queue.Empty:
            pass
        self.root.after(100, self.process_events)

    def stop_test(self):
        self.stop_event.set()
        self.progress_text.set('Stopping after current VISA operation... completed ranges will be saved')

    def clear_results(self):
        if self.running:
            return
        self.rows.clear()
        self.run_config = None
        try:
            self.checkpoint_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.resume_button.configure(state='disabled')
        self.progress['value'] = 0
        self.progress['maximum'] = 36
        self.progress_text.set('Ready — 0 of 36 ranges')
        self.refresh_noise_grid()

    def on_close(self):
        if self.tb_running or self.trig_running:
            messagebox.showwarning('Measurement running', 'Finish the current point (answer any trigger question) and wait for Fluke STBY confirmation before closing.')
            return
        if self.bw_running:
            messagebox.showwarning('Bandwidth running',
                'Wait for Fluke STBY confirmation before closing.')
            return
        if self.offset_running:
            messagebox.showwarning('Offset running', 'Wait for Fluke STBY confirmation before closing.')
            return
        if self.imp_running:
            messagebox.showwarning('Impedance in progress', 'Wait for the Fluke SCOPE OFF confirmation before closing.')
            return
        if self.dc_running:
            messagebox.showwarning('DCV in progress', 'Wait until the automatic DCV point completes and Fluke STBY is confirmed before closing.')
            return
        if self.running:
            if not messagebox.askyesno('Test running', 'Stop the test and close the window?'):
                return
            self.stop_event.set()
        self.root.destroy()


    def test_fluke(self):
        """Read-only identity check; never enables output."""
        def work():
            fluke = None
            try:
                fluke, _s = self.open_bench(self.fluke_address.get().strip(), int(self.fluke_baud.get()), None, drivers.CommandLog())
                fluke.DEFAULT_TIMEOUT = 5.0
                fluke.open(verify_model=False)
                self.events.put(('fluke', True, fluke.identify()))
            except Exception as exc:
                self.events.put(('fluke', False, str(exc)))
            finally:
                if fluke is not None:
                    try: fluke.close()
                    except Exception: pass
        threading.Thread(target=work, daemon=True).start()

    def dcv_points(self):
        # Limits transcribed from HAZ-OSC-02 report, pages 4–6.
        # Positive/negative tolerances are symmetrical for each nominal voltage.
        data = [
            (0.002, 0.006, 0.001160), (0.005, 0.015, 0.001400),
            (0.010, 0.030, 0.001800), (0.020, 0.060, 0.002600),
            (0.050, 0.150, 0.005000), (0.100, 0.300, 0.009000),
            (0.200, 0.600, 0.017000), (0.500, 1.500, 0.041000),
            (1.000, 3.000, 0.081000), (2.000, 6.000, 0.161000),
        ]
        return [dict(channel=ch, scale_v_div=s, nominal_v=sign*v,
                     lower_v=sign*v-tol, upper_v=sign*v+tol)
                for ch in range(1,5) for s,v,tol in data for sign in (1,-1)]

    def show_dcv(self):
        if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
            self.tabs.select(self.dc_window)
            return
        win = ttk.Frame(self.tabs)
        self.dc_window = win
        self.tabs.add(win, text='DC Voltage')
        self.tabs.select(win)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='DC Voltage Verification • 80 test points', style='Header.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Fluke automatic DCV uses the SCOPE output connector (not NORMAL terminals). Scope P1 MEAN, 20 MHz bandwidth and DC 1 MΩ are configured and verified automatically. Confirm connections before enabling output.', wraplength=1050).pack(anchor='w', pady=(5,8))
        connection = ttk.Frame(frame)
        connection.pack(fill='x', pady=5)
        ttk.Label(connection, text='Fluke VISA').pack(side='left')
        ttk.Entry(connection, textvariable=self.fluke_address, width=20).pack(side='left', padx=5)
        ttk.Label(connection, text='Baud').pack(side='left')
        ttk.Entry(connection, textvariable=self.fluke_baud, width=8).pack(side='left', padx=5)
        ttk.Button(connection, text='Test Fluke ID', command=self.test_fluke).pack(side='left', padx=5)
        settle_row = ttk.Frame(frame)
        settle_row.pack(anchor='w')
        ttk.Label(settle_row, text='DCV settle time after OPER (seconds; default 3.0)').pack(side='left')
        ttk.Entry(settle_row, textvariable=self.dc_settle, width=8).pack(side='left', padx=8)
        ttk.Label(frame, text='After the configured settling delay, discard one P1 read, wait 0.5 s, then use one P1 MEAN reading per DCV point. Fluke STBY is verified after each point.', wraplength=1050).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=6)
        self.dc_next_button = ttk.Button(buttons, text='Start / Next DCV Point', command=self.next_dcv)
        # Manual Next button intentionally not displayed; retained internally for state handling.
        ttk.Button(buttons, text='Run DCV Automatically', command=self.start_dcv_batch).pack(side='left', padx=7)
        ttk.Button(buttons, text='Resume DCV', command=self.resume_dcv).pack(side='left', padx=7)
        ttk.Button(buttons, text='Retest Selected DCV Point', command=self.retest_selected_dcv).pack(side='left', padx=7)
        ttk.Button(buttons, text='Stop After Current Point', command=self.stop_dcv_batch).pack(side='left', padx=7)
        ttk.Button(buttons, text='Clear DCV Results', command=self.clear_dcv).pack(side='left', padx=7)
        ttk.Label(frame, textvariable=self.dc_status, wraplength=1050).pack(anchor='w', pady=5)
        self.dc_progress = ttk.Progressbar(frame, maximum=80)
        self.dc_progress.pack(fill='x', pady=5)
        holder = ttk.Frame(frame)
        holder.pack(fill='both', expand=True)
        cols=('channel','scale','nominal','observed','low','high','error','units','result')
        self.dc_tree = ttk.Treeview(holder, columns=cols, show='headings')
        for key,label,width in [('channel','Channel',80),('scale','Range',100),('nominal','Nominal',105),('observed','Measured',110),('low','Lower limit',105),('high','Upper limit',105),('error','Error',105),('units','Units',70),('result','Result',90)]:
            self.dc_tree.heading(key, text=label)
            self.dc_tree.column(key, width=width, anchor='center')
        self.dc_tree.tag_configure('pass', foreground=ui.C['good'])
        self.dc_tree.tag_configure('fail', foreground=ui.C['bad'])
        self.dc_tree.pack(side='left', fill='both', expand=True)
        scroll=ttk.Scrollbar(holder, orient='vertical', command=self.dc_tree.yview)
        scroll.pack(side='right', fill='y')
        self.dc_tree.configure(yscrollcommand=scroll.set)
        self.refresh_dcv_table()
        self.dc_status.set(f'Restored {len(self.dc_rows)} of 80 DCV test points. Automatic Fluke control is OFF until enabled.')

    def retest_selected_dcv(self):
        """Retest an existing result without changing sequential checkpoint progress."""
        if self.running or self.dc_running or self.imp_running or self.dc_retest_index is not None:
            messagebox.showwarning('Busy', 'Finish the current measurement first.', parent=self.root)
            return
        selected = self.dc_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo('Select a row', 'Select exactly one completed DCV result in the table.', parent=self.root)
            return
        idx = self.dc_tree.index(selected[0])
        if idx >= len(self.dc_rows):
            messagebox.showinfo('Not tested yet', 'That point has not been measured yet. Use Run DCV Automatically / Resume DCV, or pick a recorded row to retest.', parent=self.root)
            return
        if not (self.dc_auto_fluke.get() and self.dc_p1_mode.get()):
            messagebox.showwarning('Automatic retest',
                'Enable automatic Fluke SCOPE DCV and scope P1 MEAN to retest.', parent=self.root)
            return
        try:
            settle = float(self.dc_settle.get())
            baud = int(self.fluke_baud.get())
            if not math.isfinite(settle) or not 0.5 <= settle <= 30:
                raise ValueError('Settling time must be 0.5–30 seconds')
        except ValueError as exc:
            messagebox.showerror('Settings', str(exc), parent=self.root)
            return
        point = self.dcv_points()[idx]
        ch = point['channel']
        if not ui.confirm_steps(self.root, 'Confirm DCV retest connection', f'Retest DCV point {idx+1} of 80',
            [('Connect the cable', f'Fluke SCOPE output cable to CH{ch}.'),
             ('Remove other sources', 'No external terminators, probes or other sources on the input.'),
             ('Automatic', 'The scope is set to DC 1 M\u03a9 and 20 MHz BW for you.')],
            facts=[('Channel', f'CH{ch}'), ('Test voltage', f'{point["nominal_v"]:+g} V'),
                   ('Range', self.range_text(point["scale_v_div"]))],
            caution='The previous reading is kept in the retest history. A good new reading replaces the displayed result; an error leaves it unchanged.',
            ok='Connected \u2014 retest'):
            return
        self.dc_batch = False
        self.dc_batch_point_ok = False
        self.dc_retest_index = idx
        self.dc_running = True
        self.dc_next_button.configure(state='disabled')
        self.dc_status.set(f'Retesting DCV point {idx+1} — CH{ch} {point["nominal_v"]:+.6f} V')
        threading.Thread(target=self.automatic_dcv_point,
            args=(point, settle, self.fluke_address.get().strip(), baud,
                  self.visa_address.get().strip()), daemon=True).start()

    def resume_dcv(self):
        """Resume at the first unrecorded DCV point using the saved checkpoint."""
        if self.dc_running or self.running or self.imp_running:
            messagebox.showwarning('Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if len(self.dc_rows) >= len(self.dcv_points()):
            messagebox.showinfo('DCV complete', 'All 80 DCV points are recorded.', parent=self.root)
            return
        self.dc_status.set(f'Resuming DCV at point {len(self.dc_rows)+1} of 80.')
        if self.dc_auto_fluke.get() and self.dc_p1_mode.get():
            self.start_dcv_batch()
        else:
            self.next_dcv()

    def start_dcv_batch(self):
        if self.dc_running or self.running or self.imp_running:
            messagebox.showwarning('Busy', 'Wait for the current test point to finish.', parent=self.root)
            return
        if len(self.dc_rows) >= len(self.dcv_points()):
            messagebox.showinfo('Complete', 'All DCV points are complete.', parent=self.root)
            return
        if not (self.dc_auto_fluke.get() and self.dc_p1_mode.get()):
            messagebox.showwarning('Automatic DCV', 'Enable both automatic Fluke output and scope P1 acquisition.', parent=self.root)
            return
        self.dc_batch = True
        self.dc_batch_channel = None
        self.dc_batch_point_ok = False
        self.next_dcv()

    def stop_dcv_batch(self):
        self.dc_batch = False
        self.dc_status.set('Automatic DCV stopped; current point will finish and Fluke will return to STBY.')

    def next_dcv(self):
        if self.running or self.dc_running or self.imp_running:
            messagebox.showwarning('Busy', 'Another measurement is in progress.')
            return
        points = self.dcv_points()
        i = len(self.dc_rows)
        if i >= len(points):
            self.dc_batch = False
            messagebox.showinfo('DCV complete', 'All 80 DCV points completed. Export the report (PDF).')
            return
        point = points[i]
        ch, scale, nominal = point['channel'], point['scale_v_div'], point['nominal_v']
        automatic = self.dc_auto_fluke.get()
        if automatic and not self.dc_p1_mode.get():
            messagebox.showwarning('Automatic mode', 'Enable automatic scope P1 MEAN acquisition to use automatic Fluke output control.')
            return
        if automatic:
            try:
                settle = float(self.dc_settle.get())
                if not math.isfinite(settle) or not 0.5 <= settle <= 30:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('Settle time', 'Settle time must be 0.5 to 30 seconds.')
                return
            msg = dict(heading=f'DCV point {i+1} of 80',
                steps=[('Connect the cable', f'Fluke SCOPE output cable to CH{ch}. Remove any external 50 \u03a9 terminator.'),
                       ('Scope input', 'DC 1 M\u03a9, bandwidth 20 MHz.'),
                       ('Automatic', f'The program sets {scale*1000:g} mV/div, configures and verifies P1 MEAN, then runs STBY \u2192 SCOPE DCV \u2192 OUT \u2192 OPER, reads the scope and returns to STBY.')],
                facts=[('Channel', f'CH{ch}'), ('Output', f'{nominal:+g} V DC'), ('Range', self.range_text(scale))],
                caution='Confirm the physical connection and that the output is safe before continuing.',
                ok='Connected and safe \u2014 continue')
        else:
            msg = dict(heading=f'DCV point {i+1} of 80 (manual output)',
                steps=[('Connect the cable', f'Fluke SCOPE output cable to CH{ch}.'),
                       ('Set the Fluke', f'Manually set the DC output to {nominal:+g} V and enable it.'),
                       ('Scope', 'DC 1 M\u03a9, 20 MHz BW. If scope acquisition is selected, scale and P1 MEAN are set automatically.')],
                facts=[('Channel', f'CH{ch}'), ('Output', f'{nominal:+g} V DC'), ('Range', self.range_text(scale))],
                caution='Manual mode does not control or disable the Fluke output. Click OK only when the output is stable.',
                ok='Output stable \u2014 continue')
        if self.dc_batch:
            if not automatic:
                self.dc_batch = False
                messagebox.showerror('Automatic DCV', 'Fluke automatic output control is required.', parent=self.root)
                return
            if self.dc_batch_channel != ch:
                # A physical cable change is mandatory at every new channel.
                if not ui.confirm_steps(self.root, f'Connect DCV cable \u2014 CH{ch}',
                    f'Connect the Fluke SCOPE output to CH{ch}',
                    [('Connect', f'Fluke SCOPE output cable to CH{ch}.'),
                     ('Remove', 'External terminators, probes and any other sources.'),
                     ('Verify', 'Scope input is DC coupling, 1 M\u03a9, 20 MHz BW.')],
                    facts=[('Channel', f'CH{ch}'), ('Test', 'Every positive and negative DCV voltage for this channel')],
                    caution='The program applies each voltage automatically and verifies Fluke STBY after every point. Press OK only after the cable is connected and safe.',
                    ok='Connected and safe \u2014 start'):
                    self.dc_batch = False
                    self.dc_status.set('Automatic DCV paused at channel connection.')
                    return
                self.dc_batch_channel = ch
        elif not ui.confirm_steps(self.root, 'Confirm DCV test setup', **msg):
            return
        if automatic:
            self.dc_running = True
            self.dc_next_button.configure(state='disabled')
            threading.Thread(target=self.automatic_dcv_point,
                             args=(point, settle, self.fluke_address.get().strip(),
                                   int(self.fluke_baud.get()), self.visa_address.get().strip(),
                                   ),
                             daemon=True).start()
        elif self.dc_p1_mode.get():
            self.dc_next_button.configure(state='disabled')
            threading.Thread(target=self.read_dcv_scope, args=(point,), daemon=True).start()
        else:
            self.enter_dcv_manual(point)

    def open_bench(self, fluke_addr, baud, scope_addr, log, scope_timeout=10):
        """Create the calibrator and scope drivers. (Tests replace this with simulated transports.)
        Either address may be None when that instrument is not needed."""
        fluke = drivers.Fluke5560A(drivers.open_visa(fluke_addr, baud=baud), log) if fluke_addr else None
        scope = (drivers.WaveSurfer4104HD(drivers.open_visa(scope_addr, timeout=scope_timeout), log)
                 if scope_addr else None)
        self._pm_bench(log, fluke, scope)
        return fluke, scope

    def reset_bench(self, fluke, scope, log):
        """Reset the calibrator and the scope (the unit under test) to their default settings before the first point of a test; the
        unit-under-test notice is asked once per session of tests (reset_startup.SessionNotice). Raises ResetDeclined / ResetFailed."""
        notice = getattr(self, '_reset_notice', None)
        if notice is None:
            notice = self._reset_notice = reset_startup.SessionNotice(
                self.root, lambda text: messagebox.askokcancel('Reset instruments', text, icon='warning', parent=self.root))
        reset_startup.reset_all([fluke] if fluke is not None else [], [scope] if scope is not None else [], confirm=notice, log=log)

    def _pm_bench(self, log, *insts):
        """Procedure modifications: the command overrides are bound to each driver as it is opened, and a banner line goes at the top of
        the command log.  Nothing at all happens (no log line, no change) when no modification is stored."""
        st = self.pm_state
        if st is not None and st.oset:
            self.pm_bind_after_open(*insts)
            st.banner(log)

    def finish_bench(self, fluke, scope, log, name):
        """Common cleanup. Returns True when the Fluke is confirmed in standby (or was never opened)."""
        safe = True
        if fluke is not None and fluke._open:
            fluke.cleanup()          # STBY and confirm, never raises
            safe = fluke.standby_confirmed
        for inst in (scope, fluke):
            if inst is not None:
                try: inst.close()
                except Exception: pass
        self.save_command_log(log, name)
        return safe

    def save_command_log(self, log, name):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (evidence for the run)."""
        try:
            folder = Path.home() / '.calibration_suite'
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {name}\n')
                f.write('\n'.join(log.lines()) + '\n')
        except OSError:
            pass

    def automatic_dcv_point(self, point, settle, fluke_addr, baud, scope_addr):
        """One DCV point through the instrument drivers: scope set up first, then calibrator output."""
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log)
            stage = 'Fluke serial open / identity'
            fluke.open()
            stage = 'scope USB open and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log)       # before the first point
            ch, scale, nominal = point['channel'], point['scale_v_div'], point['nominal_v']
            # Configure the scope before energizing the calibrator output.
            stage = 'scope vertical scale write / readback'
            scope.set_vertical_scale(ch, scale)
            stage = 'scope coupling and bandwidth configuration'
            scope.configure_dc_input(ch)
            stage = 'scope P1 MEAN configuration'
            scope.configure_p1(ch, 'Mean', show=False)
            stage = 'Fluke standby, SCOPE DCV, output level and OPER'
            fluke.apply_scope_dc(nominal)
            # The first P1 query is deliberately discarded to avoid a cached reading after the transition.
            stage = 'scope P1 reads'
            value = scope.read_p1_settled(settle)
            stage = 'Fluke standby after measurement'
            fluke.standby()
            self.events.put(('dc_auto_value', point, value))
        except Exception as exc:
            self.events.put(('dc_error', f'DCV communication failed at: {stage}\n{type(exc).__name__}: {exc}\nCheck Fluke STBY on the front panel before touching connections.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'DCV CH{point["channel"]} {point["nominal_v"]:+g} V'):
                self.events.put(('dc_safety', 'Fluke standby was NOT confirmed. Check the front panel and place it in STBY before disconnecting anything.'))
            self.events.put(('dc_idle',))

    def enter_dcv_manual(self, point):
        from tkinter import simpledialog
        value=simpledialog.askfloat('Measured DC voltage',
            f'CH{point["channel"]} | {point["nominal_v"]:+.6f} V applied\n'
            'Enter measured oscilloscope MEAN in VOLTS:', parent=self.root)
        if value is None: return
        self.record_dcv(point,value,'manual')

    def read_dcv_scope(self, point):
        """Scope-only read: the operator has set the Fluke output by hand."""
        log=drivers.CommandLog()
        scope=None
        try:
            _f,scope=self.open_bench(None,0,self.visa_address.get().strip(),log)
            scope.open()
            scope.handshake()
            self.reset_bench(None, scope, log)       # reset to default settings before the first point
            ch=point['channel']
            scope.set_vertical_scale(ch,point['scale_v_div'],settle=0.0)
            scope.configure_dc_input(ch)
            scope.configure_p1(ch,'Mean',show=False)
            time.sleep(1.5)
            self.events.put(('dc_value',point,scope.read_p1()))
        except Exception as exc:
            self.events.put(('dc_error',str(exc)))
        finally:
            if scope:
                try:scope.close()
                except Exception:pass
            self.save_command_log(log,f'DCV scope read CH{point["channel"]}')

    def record_dcv(self,point,value,method,stats=None):
        if not math.isfinite(value):
            messagebox.showerror('Invalid value','Measurement must be finite.')
            return
        row=dict(point, measured_v=value, error_v=value-point['nominal_v'],
                 result='PASS' if point['lower_v'] <= value <= point['upper_v'] else 'FAIL',
                 measurement_method=method,timestamp=datetime.now().isoformat(timespec='seconds'),
                 stimulus=('Fluke 5560A SCOPE DCV / OUT / OPER / STBY' if method.startswith('automatic') else 'Fluke 5560A guided/manual output'),
                 note='Limits from uploaded report; no guard band; scope P1 MEAN and source verified for automatic reads')
        if stats: row.update(stats)
        if method.endswith('selected-point retest'):
            # Match by point identity so sequential progress is never advanced.
            keys = ('channel', 'scale_v_div', 'nominal_v')
            matches = [i for i, old in enumerate(self.dc_rows)
                       if all(old[k] == point[k] for k in keys)]
            if len(matches) != 1:
                raise RuntimeError('Could not uniquely match retest to an existing result')
            idx = matches[0]
            previous = self.dc_rows[idx]
            history = list(previous.get('retest_history', []))
            history.append({k: v for k, v in previous.items() if k != 'retest_history'})
            row['retest_history'] = history
            row['retest_count'] = len(history)
            self.dc_rows[idx] = row
            self.save_dc_checkpoint()
            if getattr(self, 'dc_window', None) and self.dc_window.winfo_exists():
                self.refresh_dcv_table(selected_index=idx)
            self.dc_status.set(f'Retest saved for DCV point {idx+1}: {row["result"]}; '
                               f'{len(history)} previous result(s) retained.')
            return
        self.dc_rows.append(row)
        self.save_dc_checkpoint()
        if getattr(self,'dc_window',None) and self.dc_window.winfo_exists(): self.render_dcv(row)
        self.dc_status.set(f'Completed {len(self.dc_rows)} of 80 DCV points; last result {row["result"]}' +
                           (' — running channel automatically' if self.dc_batch else ''))

    def refresh_dcv_table(self, selected_index=None):
        done = len(self.dc_rows)
        items = []
        for i, p in enumerate(self.dcv_points()):
            if i < done:
                row = self.dc_rows[i]
                (nom, lo, hi), (meas, err), unit = ui.si_row([row["nominal_v"], row["lower_v"], row["upper_v"]], 'V',
                                                            [row["measured_v"], row["error_v"]])
                values = (f'CH{row["channel"]}', self.range_text(row["scale_v_div"]), nom, meas, lo, hi,
                          self._signed(err), unit, row['result'])
                items.append((values, self._tag(done, i, row['result'])))
            else:
                (nom, lo, hi), _r, unit = ui.si_row([p["nominal_v"], p["lower_v"], p["upper_v"]], 'V')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), nom, '', lo, hi, '', unit, '\u2014')
                items.append((values, self._tag(done, i)))
        ids = self._set_grid(self.dc_tree, items, active=done)
        if selected_index is not None and selected_index < len(ids):
            self.dc_tree.selection_set(ids[selected_index])
            self.dc_tree.see(ids[selected_index])
        self.dc_progress['value'] = done

    def render_dcv(self, row):
        # Called after a result is appended: fill in that point's row and move the highlight on.
        self.refresh_dcv_table()

    def save_dc_checkpoint(self):
        tmp=self.dc_checkpoint.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':6,'rows':self.dc_rows},indent=2),encoding='utf-8')
        tmp.replace(self.dc_checkpoint)

    def load_dc_checkpoint(self):
        if not self.dc_checkpoint.exists():return
        try:
            data=json.loads(self.dc_checkpoint.read_text(encoding='utf-8'))
            rows=data['rows']; points=self._pm_ckpt_points('dcv',rows)
            if not isinstance(rows,list) or len(rows)>len(points): raise ValueError('Invalid DCV checkpoint length')
            for idx,row in enumerate(rows):
                for key in ('channel','scale_v_div','nominal_v','lower_v','upper_v'):
                    if row[key]!=points[idx][key]:raise ValueError(f'Checkpoint mismatch at point {idx+1}: {key}')
            self.dc_rows=rows
        except Exception as exc:
            self.dc_status.set(f'Could not load DCV checkpoint: {exc}')

    def clear_dcv(self):
        if not messagebox.askyesno('Clear DCV results','Delete all DCV results and checkpoint?',parent=self.root):return
        self.dc_rows=[]
        self.dc_retest_index = None
        self.dc_checkpoint.unlink(missing_ok=True)
        self.refresh_dcv_table()
        self.dc_progress['value']=0
        self.dc_status.set('DCV results cleared')

    def export_dcv(self):
        self.export_calibration_section('dcv')

    # HAZ-OSC-02 input impedance verification: 6 points per channel, plus 4 EXT points.
    @staticmethod
    def impedance_points():
        points = []
        for ch in range(1, 5):
            for coupling, scale, nominal, low, high, label in (
                ('D50', .020, 50., 49., 51., '50 Ohm @ 20 mV/Div'),
                ('D50', .200, 50., 49., 51., '50 Ohm @ 200 mV/Div'),
                ('D1M', .020, 1e6, 980000., 1020000., '1 MOhm @ 20 mV/Div'),
                ('D1M', .200, 1e6, 980000., 1020000., '1 MOhm @ 200 mV/Div'),
                ('D1M', 2.000, 1e6, 980000., 1020000., '1 MOhm @ 2 V/Div'),
                ('A1M', .020, 1.2e6, 1176000., 1224000., '1.2 MOhm @ 20 mV/AC'),
            ):
                points.append(dict(channel=f'C{ch}', coupling=coupling, scale_v_div=scale,
                                   nominal_ohm=nominal, lower_ohm=low, upper_ohm=high, description=label))
        for name, coupling, nominal, low, high in (
            ('EXT', 'D1M', 1e6, 980000., 1020000.),
            ('EXT5', 'D1M', 1e6, 980000., 1020000.),
            ('EXT', 'D50', 50., 49., 51.),
            ('EXT5', 'D50', 50., 49., 51.),
        ):
            points.append(dict(channel=name, coupling=coupling, scale_v_div=None,
                               nominal_ohm=nominal, lower_ohm=low, upper_ohm=high,
                               description=f'{nominal:g} Ohm @ {name}'))
        return points

    def make_impedance_button(self):
        # Input Impedance has its own tab; no duplicate toolbar button needed.
        pass

    def show_impedance(self):
        if getattr(self, 'imp_window', None) and self.imp_window.winfo_exists():
            self.tabs.select(self.imp_window)
            return
        win = ttk.Frame(self.tabs)
        self.imp_window = win
        self.tabs.add(win, text='Input Impedance')
        self.tabs.select(win)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Input Impedance Verification', style='Header.TLabel').pack(anchor='w')
        ttk.Label(frame, text='HAZ-OSC-02: 24 channel points + 4 EXT/EXT5 points. Fluke SCOPE BNC resistance measurement, not NORMAL terminals.', wraplength=1120).pack(anchor='w', pady=(5, 4))
        ttk.Label(frame, text='For C1–C4: scope coupling and scale are set/read back automatically. EXT/EXT5 mode is selected and confirmed manually.', wraplength=1120).pack(anchor='w', pady=(0, 8))
        opts = ttk.Frame(frame)
        opts.pack(fill='x', pady=5)
        ttk.Label(opts, text='Settle (s):').pack(side='left')
        ttk.Entry(opts, textvariable=self.imp_settle, width=7).pack(side='left', padx=(5, 18))
        ttk.Label(opts, text='Readings:').pack(side='left')
        ttk.Entry(opts, textvariable=self.imp_samples, width=7).pack(side='left', padx=(5, 18))
        ttk.Label(opts, text='Fluke COM / baud inherited from DCV settings').pack(side='left')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=7)
        self.imp_next_button = ttk.Button(buttons, text='Measure Next Impedance Point', command=self.next_impedance)
        # Manual impedance button intentionally hidden; retained for existing state handling.
        ttk.Button(buttons, text='Run Impedance Automatically',
                   command=self.start_impedance_batch).pack(side='left', padx=7)
        ttk.Button(buttons, text='Stop After Current Point',
                   command=self.stop_impedance_batch).pack(side='left', padx=7)
        ttk.Button(buttons, text='Rerun Selected Test Point', command=self.retest_impedance).pack(side='left', padx=7)
        ttk.Button(buttons, text='Resume Impedance', command=self.resume_impedance).pack(side='left', padx=7)
        ttk.Button(buttons, text='Clear Impedance Results', command=self.clear_impedance).pack(side='left', padx=7)
        ttk.Label(frame, textvariable=self.imp_status).pack(anchor='w', pady=4)
        self.imp_progress = ttk.Progressbar(frame, maximum=28, mode='determinate')
        self.imp_progress.pack(fill='x', pady=(0, 7))
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        cols = ('point', 'channel', 'coupling', 'scale', 'nominal', 'measured', 'low', 'high', 'units', 'result')
        self.imp_tree = ttk.Treeview(table, columns=cols, show='headings')
        for key, title, width in (
            ('point', '#', 45), ('channel', 'Input', 75), ('coupling', 'Coupling', 90),
            ('scale', 'Range', 100), ('nominal', 'Nominal', 100), ('measured', 'Measured', 110),
            ('low', 'Lower limit', 105), ('high', 'Upper limit', 105), ('units', 'Units', 65), ('result', 'Result', 75)):
            self.imp_tree.heading(key, text=title)
            self.imp_tree.column(key, width=width, anchor='center', stretch=True)
        self.imp_tree.tag_configure('pass', foreground=ui.C['good'])
        self.imp_tree.tag_configure('fail', foreground=ui.C['bad'])
        self.imp_tree.pack(side='left', fill='both', expand=True)
        bar = ttk.Scrollbar(table, orient='vertical', command=self.imp_tree.yview)
        bar.pack(side='right', fill='y')
        self.imp_tree.configure(yscrollcommand=bar.set)
        self.refresh_impedance_table()
        self.imp_status.set(f'Restored {len(self.imp_rows)} of 28 impedance points.')

    @staticmethod
    def parse_fluke_ohms(reply):
        parts = [part.strip().upper() for part in reply.split(',')]
        if len(parts) < 2 or parts[1] != 'OHM':
            raise ValueError(f'Fluke resistance reading not valid (expected OHM): {reply!r}')
        value = float(parts[0])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid Fluke resistance value: {reply!r}')
        return value

    def resume_impedance(self):
        """Resume at the first unrecorded impedance point."""
        if self.running or self.dc_running or self.imp_running:
            messagebox.showwarning('Busy', 'Wait for the current measurement to finish.', parent=self.root)
            return
        if len(self.imp_rows) >= len(self.impedance_points()):
            messagebox.showinfo('Complete', 'All 28 impedance points are recorded.', parent=self.root)
            return
        self.imp_status.set(f'Resuming impedance at point {len(self.imp_rows)+1} of 28.')
        self.start_impedance_batch()

    def start_impedance_batch(self):
        if self.running or self.dc_running or self.imp_running:
            messagebox.showwarning('Busy', 'Wait for the current test to finish.', parent=self.root)
            return
        if len(self.imp_rows) >= len(self.impedance_points()):
            messagebox.showinfo('Complete', 'All 28 impedance measurements are recorded.', parent=self.root)
            return
        self.imp_batch = True
        self.imp_batch_success = False
        # A new run/resume requires confirmation of the actual cable connection.
        self.imp_connected_input = None
        self.next_impedance()

    def stop_impedance_batch(self):
        self.imp_batch = False
        self.imp_batch_success = False
        self.imp_status.set('Automatic impedance stopped. Current measurement will finish.')

    def next_impedance(self):
        if self.running or self.dc_running or self.imp_running:
            messagebox.showwarning('Busy', 'Wait for the current test to finish.', parent=self.root)
            return
        points = self.impedance_points()
        index = len(self.imp_rows)
        if index >= len(points):
            self.imp_batch = False
            self.imp_batch_success = False
            messagebox.showinfo('Complete', 'All 28 impedance measurements are complete.', parent=self.root)
            return
        point = points[index]
        try:
            settle = float(self.imp_settle.get())
            samples = int(self.imp_samples.get())
            baud = int(self.fluke_baud.get())
            if not math.isfinite(settle) or not .5 <= settle <= 30 or not 1 <= samples <= 20:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Settings', 'Settle: 0.5–30 seconds; readings: 1–20; baud: integer.', parent=self.root)
            return
        # Coupling and vertical scale are configured and verified automatically
        # on channels C1-C4. Only actual cable/input changes need confirmation.
        target = point['channel']
        ext = target.startswith('EXT')
        must_confirm = (self.imp_connected_input != target) if self.imp_batch else (
            not self.imp_connection_confirmed or
            not self.imp_rows or self.imp_rows[-1]['channel'] != target or
            self.imp_rows[-1]['coupling'] != point['coupling'])
        if must_confirm:
            mode = {'D50':'DC 50 Ω', 'D1M':'DC 1 MΩ', 'A1M':'AC 1 MΩ'}[point['coupling']]
            detail = (
                'EXT/EXT5 input selection and impedance are not remotely configured. '
                'Manually select the correct trigger mode and impedance for this point.'
                if ext else
                'The application will set and verify coupling and vertical scale automatically.'
            )
            prompt = dict(heading=f'Impedance point {index+1} of 28',
                steps=[('Output off', 'Verify the Fluke SCOPE MEASR output is OFF before moving the cable.'),
                       ('Connect', f'Fluke 5560A SCOPE measurement cable directly to {target}. Remove other signal sources and external terminators.'),
                       ('Input mode', detail)],
                facts=[('Input', target), ('Test', point['description']), ('Input setting', mode)],
                caution='Click OK only after the cable and input mode are safe.',
                ok='Connected and safe \u2014 continue')
            if not ui.confirm_steps(self.root, 'Confirm impedance connection', **prompt):
                self.imp_batch = False
                self.imp_status.set('Automatic impedance paused for connection.')
                return
            self.imp_connection_confirmed = True
            self.imp_connected_input = target
        elif ext:
            # EXT/EXT5 modes require a manual change even without moving the BNC.
            previous = self.imp_rows[-1] if self.imp_rows else None
            if previous is None or previous['coupling'] != point['coupling']:
                mode = {'D50':'50 Ω', 'D1M':'1 MΩ'}[point['coupling']]
                if not ui.confirm_steps(self.root, 'Confirm external trigger impedance',
                    f'Set {target} trigger input impedance',
                    [('Set the input', f'Trigger input impedance to {mode}.'),
                     ('Confirm', 'Check the setting before the resistance measurement.')],
                    facts=[('Input', target), ('Impedance', mode)], ok='Set \u2014 continue'):
                    self.imp_batch = False
                    return
        self.imp_running = True
        self.imp_next_button.configure(state='disabled')
        self.imp_status.set(f'Measuring {index+1}/28: {point["channel"]} — {point["description"]}')
        threading.Thread(target=self.impedance_worker,
                         args=(point, settle, samples, self.visa_address.get().strip(),
                               self.fluke_address.get().strip(), baud), daemon=True).start()

    def impedance_worker(self, point, settle, samples, scope_address, fluke_address, baud):
        log = drivers.CommandLog()
        fluke = scope = None
        scope_off_confirmed = False
        try:
            fluke, scope = self.open_bench(fluke_address, baud, scope_address, log)
            fluke.open()
            scope.open()
            self.reset_bench(fluke, scope, log)       # reset to default settings before the first point
            # Disable previous scope function before any DUT reconfiguration.
            fluke.scope_off()
            ch = point['channel']
            if ch.startswith('C'):
                scope.set_coupling_legacy(ch, point['coupling'])
                # The point names the channel 'C1'..'C4' (classic command form); the VBS setter takes the number.
                scope.set_vertical_scale(int(ch[1:]), point['scale_v_div'], settle=0.0)
            # For EXT/EXT5, manual setup is required; do not silently treat EXT5 as a separate port.
            fluke.select_scope_measure_resistance()
            time.sleep(settle)
            values = []
            for _ in range(samples):
                values.append(fluke.measure_scope_resistance())
                time.sleep(.2)
            fluke.scope_off()
            scope_off_confirmed = True
            self.events.put(('imp_result', point, sum(values)/len(values), values))
        except Exception as exc:
            self.events.put(('imp_error', str(exc)))
        finally:
            if fluke is not None and fluke._open:
                try:
                    fluke.scope_off()
                    scope_off_confirmed = True
                except Exception:
                    scope_off_confirmed = False
            if not scope_off_confirmed:
                self.events.put(('imp_safety', 'Fluke SCOPE OFF was NOT confirmed. Check the Fluke front panel before changing connections.'))
            for inst in (scope, fluke):
                if inst is not None:
                    try: inst.close()
                    except Exception: pass
            self.save_command_log(log, f'Impedance {point["channel"]} {point["coupling"]}')
            self.events.put(('imp_idle',))

    def _retest_index(self, tree, rows, label, parent):
        if any((self.running, self.dc_running, self.imp_running, self.offset_running, self.bw_running, self.tb_running, self.trig_running)):
            messagebox.showwarning('Busy', 'Finish the current measurement first.', parent=parent)
            return None
        selected = tree.selection()
        if len(selected) != 1:
            messagebox.showinfo('Select a result', f'Select one completed {label} result.', parent=parent)
            return None
        idx = tree.index(selected[0])
        if idx >= len(rows):
            messagebox.showinfo('Not tested yet', 'That point has not been measured yet. Pick a recorded row to retest, or use Run / Resume.', parent=parent)
            return None
        return idx

    def retest_impedance(self):
        idx = self._retest_index(self.imp_tree, self.imp_rows, 'impedance', self.imp_window)
        if idx is None: return
        point = self.impedance_points()[idx]
        if not ui.confirm_steps(self.root, 'Confirm impedance retest', f'Retest impedance point {idx+1} of 28',
            [('Output off', 'Confirm the Fluke SCOPE measurement output is OFF before moving cables.'),
             ('Connection', 'Verify the correct connection and, for EXT inputs, the input impedance.')],
            facts=[('Input', point['channel']), ('Test', point['description'])],
            caution='The prior reading is replaced only after a successful retest.', ok='Ready \u2014 retest'): return
        try:
            settle=float(self.imp_settle.get()); samples=int(self.imp_samples.get()); baud=int(self.fluke_baud.get())
            if not (.5<=settle<=30 and 1<=samples<=20 and baud>0): raise ValueError()
        except ValueError:
            messagebox.showerror('Settings', 'Check settle time, samples, and baud.', parent=self.root); return
        self.imp_batch=False
        self.imp_retest_index=idx
        self.imp_running=True
        self.imp_next_button.configure(state='disabled')
        self.imp_status.set(f'Retesting impedance point {idx+1}/28')
        threading.Thread(target=self.impedance_worker,
            args=(point,settle,samples,self.visa_address.get().strip(),
                  self.fluke_address.get().strip(),baud),daemon=True).start()

    def retest_offset(self):
        idx=self._retest_index(self.offset_tree,self.offset_rows,'offset',self.offset_tab)
        if idx is None:return
        point=self.offset_points()[idx]
        if not ui.confirm_steps(self.root, 'Confirm offset retest', f'Retest offset point {idx+1} of 16',
            [('Connection', 'Confirm the Fluke SCOPE cable is connected to the correct channel.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Scope offset', f'{point["scope_offset_v"]:+g} V')],
            caution='The prior reading is replaced only on success.', ok='Ready \u2014 retest'):return
        try:
            settle=float(self.offset_settle.get());baud=int(self.fluke_baud.get())
            if not (.5<=settle<=60 and baud>0):raise ValueError()
        except ValueError:
            messagebox.showerror('Settings','Check settle time and baud.',parent=self.root);return
        self.offset_batch=False
        self.offset_retest_index=idx
        self.offset_running=True
        self.offset_status.set(f'Retesting offset point {idx+1}/16')
        threading.Thread(target=self.offset_worker,args=(point,settle,
            self.fluke_address.get().strip(),baud,self.visa_address.get().strip()),daemon=True).start()

    def retest_bandwidth(self):
        idx=self._retest_index(self.bw_tree,self.bw_rows,'bandwidth',self.bw_tab)
        if idx is None:return
        point=self.bandwidth_points()[idx]
        if not ui.confirm_steps(self.root, 'Confirm bandwidth retest', f'Retest bandwidth point {idx+1} of 24',
            [('Signal path', 'Verify a rated 50 \u03a9 signal path and the scope DC50 input.'),
             ('Signal', 'The Fluke will generate a 1 GHz sine wave.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Range', self.range_text(point["scale_v_div"]))],
            caution='The prior result is replaced only on success.', ok='Ready \u2014 retest'):return
        try:
            settle=float(self.bw_settle.get());baud=int(self.fluke_baud.get())
            if not (.5<=settle<=60 and baud>0):raise ValueError()
        except ValueError:
            messagebox.showerror('Settings','Check settle time and baud.',parent=self.root);return
        self.bw_batch=False
        self.bw_retest_index=idx
        self.bw_running=True
        self.bw_status.set(f'Retesting bandwidth point {idx+1}/24')
        threading.Thread(target=self.bandwidth_worker,args=(point,settle,
            self.fluke_address.get().strip(),baud,self.visa_address.get().strip()),daemon=True).start()

    def record_impedance(self, point, value, values):
        row = dict(point, measured_ohm=value, error_ohm=value-point['nominal_ohm'],
                   result='PASS' if point['lower_ohm'] <= value <= point['upper_ohm'] else 'FAIL',
                   individual_readings_ohm=';'.join(f'{x:.9g}' for x in values),
                   measurement_method='Fluke 5560A SCOPE MEASR / *TRG',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='HAZ-OSC-02 acceptance limits; no uncertainty guard band')
        retest_idx=getattr(self,'imp_retest_index',None)
        if retest_idx is not None:
            previous=self.imp_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.imp_rows[retest_idx]=row
            self.imp_retest_index=None
        else:
            self.imp_rows.append(row)
        self.save_impedance_checkpoint()
        if getattr(self, 'imp_window', None) and self.imp_window.winfo_exists():
            self.refresh_impedance_table()
        self.imp_status.set(f'{len(self.imp_rows)}/28 complete — last: {value:.8g} Ω ({row["result"]})')

    def refresh_impedance_table(self):
        done = len(self.imp_rows)
        items = []
        for i, p in enumerate(self.impedance_points()):
            row = self.imp_rows[i] if i < done else None
            src = row or p
            scale = src['scale_v_div']
            (nom, lo, hi), reads, unit = ui.si_row([src["nominal_ohm"], src["lower_ohm"], src["upper_ohm"]], 'ohm',
                                                  [row["measured_ohm"]] if row else [])
            values = (i + 1, src['channel'], src['coupling'], self.range_text(scale),
                      nom, reads[0] if reads else '', lo, hi, unit, row['result'] if row else '\u2014')
            items.append((values, self._tag(done, i, row['result'] if row else None)))
        self._set_grid(self.imp_tree, items, active=done)
        self.imp_progress['value'] = done

    def render_impedance(self, index, row):
        self.refresh_impedance_table()

    def save_impedance_checkpoint(self):
        tmp = self.imp_checkpoint.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':11, 'rows':self.imp_rows}, indent=2), encoding='utf-8')
        tmp.replace(self.imp_checkpoint)

    def load_impedance_checkpoint(self):
        if not self.imp_checkpoint.exists():
            return
        try:
            rows = json.loads(self.imp_checkpoint.read_text(encoding='utf-8'))['rows']
            points = self._pm_ckpt_points('impedance', rows)
            if not isinstance(rows, list) or len(rows) > len(points):
                raise ValueError('Invalid impedance checkpoint length')
            for idx, row in enumerate(rows):
                for field in ('channel','coupling','scale_v_div','nominal_ohm','lower_ohm','upper_ohm'):
                    if row[field] != points[idx][field]:
                        raise ValueError(f'Impedance checkpoint mismatch at point {idx+1}: {field}')
            self.imp_rows = rows
        except Exception as exc:
            self.imp_status.set(f'Could not restore impedance checkpoint: {exc}')

    def clear_impedance(self):
        if self.imp_running:
            return
        if not messagebox.askyesno('Clear impedance', 'Delete all impedance results and checkpoint?', parent=self.root):
            return
        self.imp_rows = []
        self.imp_connection_confirmed = False
        self.imp_connected_input = None
        self.imp_batch = False
        self.imp_checkpoint.unlink(missing_ok=True)
        self.refresh_impedance_table()
        self.imp_progress['value'] = 0
        self.imp_status.set('Impedance results cleared')

    def export_impedance(self):
        self.export_calibration_section('impedance')

    # Offset-position DC voltage verification. MEAN measures the sourced voltage,
    # not an independent center-position/offset accuracy measurement.
    @staticmethod
    def offset_points():
        pts = []
        for ch in range(1, 5):
            for scale, offset, tolerance in (
                (.020, -4.5, .050), (.020, 4.5, .050),
                (2.0, -10.0, .261), (2.0, 10.0, .261),
            ):
                stimulus = -offset
                pts.append(dict(channel=ch, scale_v_div=scale, scope_offset_v=offset,
                                nominal_v=stimulus, lower_v=stimulus-tolerance,
                                upper_v=stimulus+tolerance))
        return pts

    def show_offset(self):
        win = ttk.Frame(self.tabs)
        self.offset_tab = win
        self.tabs.add(win, text='Offset / P1 Mean')
        outer = ttk.Frame(win, padding=14)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Offset-position DC Voltage Verification',
                  style='Header.TLabel').pack(anchor='w')
        ttk.Label(outer, wraplength=1100, text=(
            '16 points: four channels × ±4.5 V and ±10 V. '
            'The Fluke SCOPE DCV output is opposite polarity to the scope vertical offset. '
            'P1 MEAN is compared with the applied DC voltage. This is NOT an independent '
            'measurement of vertical offset centering accuracy.'
        )).pack(anchor='w', pady=(5, 12))
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=(0, 10))
        ttk.Label(controls, text='Settle (s):').pack(side='left')
        ttk.Entry(controls, textvariable=self.offset_settle, width=7).pack(side='left', padx=6)
        ttk.Button(controls, text='Run Offset Automatically',
                   command=self.start_offset).pack(side='left', padx=5)
        ttk.Button(controls, text='Resume Offset',
                   command=self.start_offset).pack(side='left', padx=5)
        ttk.Button(controls, text='Rerun Selected Test Point', command=self.retest_offset).pack(side='left', padx=5)
        ttk.Button(controls, text='Stop After Current Point',
                   command=self.stop_offset).pack(side='left', padx=5)
        ttk.Label(outer, textvariable=self.offset_status).pack(anchor='w', pady=5)
        self.offset_progress = ttk.Progressbar(outer, maximum=16)
        self.offset_progress.pack(fill='x', pady=5)
        columns = ('ch','scale','offset','source','mean','error','low','high','units','result')
        self.offset_tree = ttk.Treeview(outer, columns=columns, show='headings')
        for key, title, width in (
            ('ch','Channel',80),('scale','Range',100),('offset','Scope offset',110),
            ('source','Fluke source',110),('mean','P1 Mean',110),
            ('error','Error',100),('low','Lower limit',105),('high','Upper limit',105),('units','Units',65),('result','Result',85)):
            self.offset_tree.heading(key,text=title)
            self.offset_tree.column(key,width=width,anchor='center')
        self.offset_tree.pack(side='left',fill='both',expand=True)
        _sb=ttk.Scrollbar(outer,orient='vertical',command=self.offset_tree.yview);_sb.pack(side='right',fill='y')
        self.offset_tree.configure(yscrollcommand=_sb.set)

    def start_offset(self):
        if self.offset_running or self.dc_running or self.imp_running or self.running:
            messagebox.showwarning('Busy', 'Another instrument operation is running.',
                                   parent=self.root)
            return
        if len(self.offset_rows) >= 16:
            messagebox.showinfo('Complete', 'All 16 offset points are complete.',
                                parent=self.root)
            return
        try:
            settle = float(self.offset_settle.get())
            if not 0.5 <= settle <= 60:
                raise ValueError()
            int(self.fluke_baud.get())
        except ValueError:
            messagebox.showerror('Invalid setup', 'Settle must be 0.5–60 seconds and baud numeric.',
                                 parent=self.root)
            return
        if not ui.confirm_steps(self.root, 'Confirm offset test method', 'Offset-position DCV test',
            [('What this tests', 'P1 MEAN at specified scope vertical offsets. It does not independently verify waveform centering accuracy.'),
             ('Confirm', 'The intended test method, the limits, and the correct Fluke SCOPE BNC connection.')],
            caution='The program will enable and disable the DC voltage output.', ok='Confirmed \u2014 start'):
            return
        self.offset_batch = True
        self.offset_ok = False
        self.offset_connected_channel = None
        self.next_offset()

    def stop_offset(self):
        self.offset_batch = False
        self.offset_ok = False
        self.offset_status.set('Stopped after current point; saved results retained.')

    def next_offset(self):
        if not self.offset_batch or self.offset_running:
            return
        points = self.offset_points()
        idx = len(self.offset_rows)
        if idx >= len(points):
            self.offset_batch = False
            self.offset_status.set('Complete — 16 of 16 offset points')
            messagebox.showinfo('Complete','All 16 offset points recorded.',parent=self.root)
            return
        point = points[idx]
        ch = point['channel']
        if self.offset_connected_channel != ch:
            if not ui.confirm_steps(self.root, 'Offset cable connection',
                f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Confirm the Fluke is in STBY.'),
                 ('Connect', f'Fluke SCOPE output to CH{ch}. Disconnect other sources and terminators.')],
                facts=[('Point', f'{idx+1} of 16'), ('Channel', f'CH{ch}')],
                caution='Press OK only after the connection is safe.', ok='Connected and safe \u2014 continue'):
                self.offset_batch = False
                self.offset_status.set('Paused — awaiting safe cable connection')
                return
            self.offset_connected_channel = ch
        self.offset_running = True
        self.offset_status.set(
            f'Running {idx+1}/16: CH{ch} | offset {point["scope_offset_v"]:+.3f} V | '
            f'Fluke {point["nominal_v"]:+.3f} V')
        args=(point, float(self.offset_settle.get()),self.fluke_address.get().strip(),
              int(self.fluke_baud.get()),self.visa_address.get().strip())
        threading.Thread(target=self.offset_worker,args=args,daemon=True).start()

    def offset_worker(self, point, settle, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log)       # before the first point
            ch = point['channel']
            stage = 'Scope scale'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            stage = 'Scope DC1M and 20 MHz'
            scope.configure_dc_input(ch)
            stage = 'Scope vertical offset'
            scope.set_vertical_offset(ch, point['scope_offset_v'])
            stage = 'P1 MEAN setup'
            scope.configure_p1(ch, 'Mean', show=False)
            stage = 'Fluke SCOPE DCV mode'
            fluke.select_scope_dcv('1M')
            stage = 'Fluke output setting'
            programmed = fluke.set_dc_volts(point['nominal_v'])
            stage = 'Fluke OPER'
            fluke.operate()
            stage = 'Settling, discarding first P1 read, final P1 MEAN'
            value = scope.read_p1_settled(settle)
            stage = 'Fluke standby after point'
            fluke.standby()
            self.events.put(('offset_result', point, value, programmed))
        except Exception as exc:
            self.events.put(('offset_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Offset CH{point["channel"]} {point["scope_offset_v"]:+g} V'):
                self.events.put(('offset_safety',
                    'Fluke standby NOT confirmed. Inspect Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('offset_idle',))

    def record_offset(self,point,measured,programmed):
        row=dict(point,fluke_programmed_v=programmed,measured_v=measured,
                 error_v=measured-point['nominal_v'],
                 result='PASS' if point['lower_v']<=measured<=point['upper_v'] else 'FAIL',
                 method='Fluke 5560A SCOPE DCV / scope P1 MEAN at programmed offset',
                 timestamp=datetime.now().isoformat(timespec='seconds'))
        retest_idx=getattr(self,'offset_retest_index',None)
        if retest_idx is not None:
            previous=self.offset_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.offset_rows[retest_idx]=row
            self.offset_retest_index=None
        else:
            self.offset_rows.append(row)
        self.save_offset_checkpoint()
        self.refresh_offset()

    def refresh_offset(self):
        done = len(self.offset_rows)
        items = []
        for i, p in enumerate(self.offset_points()):
            if i < done:
                row = self.offset_rows[i]
                (off, src, lo, hi), (mean, err), unit = ui.si_row(
                    [row["scope_offset_v"], row["fluke_programmed_v"], row["lower_v"], row["upper_v"]], 'V',
                    [row["measured_v"], row["error_v"]], extra=3)
                values = (f'CH{row["channel"]}', self.range_text(row["scale_v_div"]), self._signed(off), self._signed(src),
                          self._signed(mean), self._signed(err), self._signed(lo), self._signed(hi), unit, row['result'])
                items.append((values, self._tag(done, i, row['result'])))
            else:
                (off, src, lo, hi), _r, unit = ui.si_row(
                    [p["scope_offset_v"], p["nominal_v"], p["lower_v"], p["upper_v"]], 'V')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), self._signed(off), self._signed(src),
                          '', '', self._signed(lo), self._signed(hi), unit, '\u2014')
                items.append((values, self._tag(done, i)))
        self._set_grid(self.offset_tree, items, active=done)
        self.offset_progress['value'] = done
        self.offset_status.set(f'{done} of 16 offset-position DCV points recorded')

    def save_offset_checkpoint(self):
        self.offset_checkpoint.write_text(json.dumps(self.offset_rows,indent=2),
                                          encoding='utf-8')

    def load_offset_checkpoint(self):
        if not self.offset_checkpoint.exists():
            return
        try:
            rows=json.loads(self.offset_checkpoint.read_text(encoding='utf-8'))
            points=self._pm_ckpt_points('offset',rows)
            if not isinstance(rows,list) or len(rows)>16:
                raise ValueError('Invalid checkpoint length')
            for i,row in enumerate(rows):
                if not isinstance(row,dict) or any(
                    row.get(k)!=points[i][k] for k in ('channel','scale_v_div',
                                                         'scope_offset_v','nominal_v')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.offset_rows=rows
            self.refresh_offset()
        except Exception as exc:
            messagebox.showwarning('Offset checkpoint',f'Could not load offset results: {exc}',
                                   parent=self.root)

    def export_offset(self):
        self.export_calibration_section('offset')

    @staticmethod
    def bandwidth_points():
        return [
            dict(channel=ch,scale_v_div=scale,amplitude_vpp=6*scale,
                 reference_hz=50000,high_hz=1000000000,lower_db=-3.0,upper_db=3.0)
            for ch in range(1,5)
            for scale in (.010,.020,.050,.100,.200,.500)
        ]

    def show_bandwidth(self):
        self.bw_tab=ttk.Frame(self.tabs)
        self.tabs.add(self.bw_tab,text='Bandwidth / LEVSINE')
        outer=ttk.Frame(self.bw_tab,padding=14)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Analog Bandwidth — Fluke SCOPE LEVSINE',
                  style='Header.TLabel').pack(anchor='w')
        ttk.Label(outer,text='24 points  \u2022  4 channels \u00d7 6 scales  \u2022  stimulus 6 divisions Vpp  \u2022  scope DC50, full bandwidth',
                  style='Muted.TLabel').pack(anchor='w',pady=(4,2))
        ttk.Label(outer,wraplength=1100,justify='left',text=(
            'Reference: 50 kHz at 10 \u00b5s/div.   High frequency: 1 GHz at 1 ns/div.\n'
            'Response = 20 log10 (Vpp at 1 GHz \u00f7 Vpp at 50 kHz), from P1 peak-to-peak.   Limits: \u22123 to +3 dB.'
        )).pack(anchor='w',pady=(0,8))
        ui.Notice(outer,kind='warn',title='Verify the first point',
                  text='This release has not been hardware-validated for LEVSINE and P1 PkPk. '
                       'Check the first point before relying on the results.').pack(fill='x',pady=(0,10))
        bar=ttk.Frame(outer)
        bar.pack(fill='x',pady=5)
        ttk.Label(bar,text='Settle (s):').pack(side='left')
        ttk.Entry(bar,textvariable=self.bw_settle,width=7).pack(side='left',padx=6)
        ttk.Button(bar,text='Run / Resume Bandwidth',command=self.start_bandwidth).pack(side='left',padx=5)
        ttk.Button(bar,text='Rerun Selected Test Point',command=self.retest_bandwidth).pack(side='left',padx=5)
        ttk.Button(bar,text='Stop After Current Point',command=self.stop_bandwidth).pack(side='left',padx=5)
        ttk.Label(outer,textvariable=self.bw_status).pack(anchor='w',pady=5)
        self.bw_progress=ttk.Progressbar(outer,maximum=24)
        self.bw_progress.pack(fill='x',pady=5)
        cols=('channel','scale','amplitude','ref','high','vunit','db','dunit','result')
        self.bw_tree=ttk.Treeview(outer,columns=cols,show='headings')
        for k,label,w in (
            ('channel','Channel',85),('scale','Range',100),('amplitude','Stimulus',105),
            ('ref','50 kHz',105),('high','1 GHz',105),('vunit','Units',70),
            ('db','Response',100),('dunit','Units',60),('result','Result',90)):
            self.bw_tree.heading(k,text=label)
            self.bw_tree.column(k,width=w,anchor='center')
        self.bw_tree.pack(side='left',fill='both',expand=True)
        _sb=ttk.Scrollbar(outer,orient='vertical',command=self.bw_tree.yview);_sb.pack(side='right',fill='y')
        self.bw_tree.configure(yscrollcommand=_sb.set)

    def start_bandwidth(self):
        if any((self.bw_running,self.dc_running,self.imp_running,self.offset_running,self.running)):
            messagebox.showwarning('Busy','An instrument operation is running.',parent=self.root)
            return
        if len(self.bw_rows)==24:
            messagebox.showinfo('Complete','All 24 bandwidth points are complete.',parent=self.root)
            return
        try:
            settle=float(self.bw_settle.get())
            baud=int(self.fluke_baud.get())
            if not math.isfinite(settle) or not .5<=settle<=60 or baud<=0:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Invalid settings','Settle must be 0.5–60 s; baud must be positive.',
                                 parent=self.root)
            return
        if not ui.confirm_steps(self.root, 'Confirm high-frequency test', 'Bandwidth test \u2014 1 GHz sine',
            [('Signal path', 'Use a rated 50 \u03a9 signal path, the correct Fluke SCOPE output and the scope 50 \u03a9 input.'),
             ('No extra termination', 'Do not use a 1 M\u03a9 input, or a 50 \u03a9 feedthrough in addition to the scope internal termination.'),
             ('Confirm method', 'The Fluke LEVSINE command and the scope P1 PkPk measurement are suitable.')],
            caution='The Fluke will generate a 1 GHz sine signal into the oscilloscope. The first point is a hardware pilot.',
            ok='Confirmed \u2014 start'):
            return
        self.bw_batch=True
        self.bw_ok=False
        self.bw_connected_channel=None
        self.next_bandwidth()

    def stop_bandwidth(self):
        self.bw_batch=False
        self.bw_ok=False
        self.bw_status.set('Paused; completed points retained.')

    def next_bandwidth(self):
        if not self.bw_batch or self.bw_running:
            return
        idx=len(self.bw_rows)
        if idx>=24:
            self.bw_batch=False
            self.bw_status.set('Complete — 24/24 bandwidth points')
            messagebox.showinfo('Bandwidth complete','All 24 points recorded.',parent=self.root)
            return
        point=self.bandwidth_points()[idx]
        ch=point['channel']
        if self.bw_connected_channel!=ch:
            if not ui.confirm_steps(self.root, 'Move 50 \u03a9 signal cable', f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Verify the Fluke output is STBY.'),
                 ('Connect', f'A rated 50 \u03a9 cable from the Fluke SCOPE output to CH{ch}.'),
                 ('Automatic', 'The scope input is set to DC50 for you.')],
                facts=[('Point', f'{idx+1} of 24'), ('Channel', f'CH{ch}')],
                caution='Confirm the connection before the output is enabled.', ok='Connected \u2014 continue'):
                self.bw_batch=False
                self.bw_status.set('Paused — waiting for safe cable connection')
                return
            self.bw_connected_channel=ch
        self.bw_running=True
        self.bw_status.set(f'Running {idx+1}/24: CH{ch} '
                           f'{point["scale_v_div"]*1000:g} mV/div '
                           f'{point["amplitude_vpp"]:g} Vpp')
        args=(point,float(self.bw_settle.get()),self.fluke_address.get().strip(),
              int(self.fluke_baud.get()),self.visa_address.get().strip())
        threading.Thread(target=self.bandwidth_worker,args=args,daemon=True).start()

    @staticmethod
    def read_bandwidth_vpp(scope):
        val=scope.read_p1()
        if val<=0:
            raise RuntimeError(f'Invalid P1 PkPk amplitude {val}')
        return val

    def bandwidth_worker(self,point,settle,fluke_addr,baud,scope_addr):
        log=drivers.CommandLog()
        fluke=scope=None
        stage='opening instruments'
        try:
            fluke,scope=self.open_bench(fluke_addr,baud,scope_addr,log)
            stage='Fluke connection / identity'
            fluke.open()
            stage='Fluke standby'
            fluke.standby()
            stage='Scope connection'
            scope.open()
            stage='reset to default settings'
            self.reset_bench(fluke,scope,log)       # before the first point
            ch=point['channel']
            amplitude=point['amplitude_vpp']
            stage='Scope scale'
            scope.set_vertical_scale(ch,point['scale_v_div'])
            stage='Scope vertical offset'
            scope.ensure_zero_offset(ch)
            stage='Scope 50 Ω coupling'
            scope.set_coupling(ch,'DC50')
            stage='Scope Full bandwidth'
            scope.set_bandwidth_limit(ch,'Full')
            stage='Scope trigger source'
            # Source verification is mandatory: never silently measure the wrong channel.
            scope.set_edge_trigger_source(ch)
            stage='Scope P1 PkPk'
            scope.configure_p1(ch,'PkPk')
            stage='Scope 50 kHz horizontal timebase (10 us/div)'
            scope.set_timebase(10e-6)
            stage='Fluke LEVSINE 50 kHz'
            fluke.select_scope_levsine()
            fluke.set_levsine(amplitude,50e3)
            stage='Fluke output 50 kHz'
            fluke.operate()
            time.sleep(settle)
            self.read_bandwidth_vpp(scope)  # discard settling reading
            time.sleep(.35)
            reference=self.read_bandwidth_vpp(scope)
            # Detect severe clipping or missing signal before moving to 1 GHz.
            if not .4*amplitude<=reference<=1.6*amplitude:
                raise RuntimeError(
                    f'50 kHz measured {reference:.6g} Vpp vs {amplitude:.6g} Vpp '
                    '(possible clipping, wrong signal units, cable or P1 configuration).')
            stage='Fluke standby before frequency change'
            fluke.standby()
            stage='Scope 1 GHz horizontal timebase (1 ns/div)'
            scope.set_timebase(1e-9)
            stage='Fluke LEVSINE 1 GHz'
            fluke.set_levsine(amplitude,1e9)
            stage='Fluke output 1 GHz'
            fluke.operate()
            time.sleep(settle)
            self.read_bandwidth_vpp(scope)
            time.sleep(.35)
            high=self.read_bandwidth_vpp(scope)
            stage='Fluke standby after point'
            fluke.standby()
            self.events.put(('bw_result',point,reference,high))
        except Exception as exc:
            self.events.put(('bw_error',
                f'{stage}: {type(exc).__name__}: {exc}\n'
                'Check Fluke STBY on front panel before handling cables. '
                'For VI_ERROR_IO, close other VISA applications, reconnect scope USB, '
                'and retry after the scope is responsive.'))
        finally:
            if not self.finish_bench(fluke,scope,log,f'Bandwidth CH{point["channel"]} {point["amplitude_vpp"]:g} Vpp'):
                self.events.put(('bw_safety',
                    'Fluke STBY NOT confirmed. Inspect front panel; do not disconnect.'))
            self.events.put(('bw_idle',))

    def record_bandwidth(self,point,reference,high):
        response=20*math.log10(high/reference)
        row=dict(point,reference_measured_vpp=reference,high_measured_vpp=high,
                 response_db=response,
                 result='PASS' if point['lower_db']<=response<=point['upper_db'] else 'FAIL',
                 method='SCOPE LEVSINE; P1 PkPk; DC50; Full BW',
                 timestamp=datetime.now().isoformat(timespec='seconds'))
        retest_idx=getattr(self,'bw_retest_index',None)
        if retest_idx is not None:
            previous=self.bw_rows[retest_idx]
            row['retest_history']=previous.get('retest_history',[])+[{
                'timestamp':previous.get('timestamp'), 'result':previous.get('result'),
                'previous_row':{k:v for k,v in previous.items() if k!='retest_history'}}]
            self.bw_rows[retest_idx]=row
            self.bw_retest_index=None
        else:
            self.bw_rows.append(row)
        self.save_bandwidth_checkpoint()
        self.refresh_bandwidth()
        if len(self.bw_rows)==1 and self.bw_batch:
            self.bw_batch=False
            self.bw_status.set('Pilot point complete — review measured amplitudes and response; click Run / Resume to continue.')
            messagebox.showinfo('First-point validation',
                f'CH1 at 10 mV/div:\n50 kHz: {reference:.6g} Vpp\n'
                f'1 GHz: {high:.6g} Vpp\nResponse: {response:+.3f} dB\n\n'
                'Review the Fluke and scope setup before continuing the remaining 23 points.',
                parent=self.root)

    def refresh_bandwidth(self):
        done = len(self.bw_rows)
        items = []
        for i, p in enumerate(self.bandwidth_points()):
            if i < done:
                r = self.bw_rows[i]
                (amp,), (ref, hi), vunit = ui.si_row([r["amplitude_vpp"]], 'Vpp',
                                                    [r["reference_measured_vpp"], r["high_measured_vpp"]], extra=2)
                values = (f'CH{r["channel"]}', self.range_text(r["scale_v_div"]), amp, ref, hi, vunit,
                          f'{r["response_db"]:+.3f}', 'dB', r['result'])
                items.append((values, self._tag(done, i, r['result'])))
            else:
                (amp,), _r, vunit = ui.si_row([p["amplitude_vpp"]], 'Vpp')
                values = (f'CH{p["channel"]}', self.range_text(p["scale_v_div"]), amp, '', '', vunit, '', 'dB', '\u2014')
                items.append((values, self._tag(done, i)))
        self._set_grid(self.bw_tree, items, active=done)
        self.bw_progress['value'] = done
        self.bw_status.set(f'{done} of 24 bandwidth points recorded')

    def save_bandwidth_checkpoint(self):
        temp=self.bw_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.bw_rows,indent=2),encoding='utf-8')
        temp.replace(self.bw_checkpoint)

    def load_bandwidth_checkpoint(self):
        if not self.bw_checkpoint.exists():
            return
        try:
            rows=json.loads(self.bw_checkpoint.read_text(encoding='utf-8'))
            points=self.bandwidth_points()
            if not isinstance(rows,list) or len(rows)>24:
                raise ValueError('Invalid checkpoint length')
            for i,row in enumerate(rows):
                if not isinstance(row,dict) or any(
                    row.get(k)!=points[i][k] for k in
                    ('channel','scale_v_div','amplitude_vpp','reference_hz','high_hz')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.bw_rows=rows
            self.refresh_bandwidth()
        except Exception as exc:
            messagebox.showwarning('Bandwidth checkpoint',
                f'Could not load saved bandwidth points: {exc}',parent=self.root)

    def export_bandwidth(self):
        self.export_calibration_section('bandwidth')



    # ======================================================================== time base accuracy (one point)
    # Limit from the HAZ-OSC-02 data sheet, page 10 (read from the rendered page image): error 0.00 Hz, -0.350 to +0.350 Hz.
    # The sheet does not state the stimulus. The technician recalled a time marker; the marker period is a Test setting
    # (default 10 us = 100 kHz, where +/-0.35 Hz is +/-3.5 ppm) and is saved with the result and printed on the report.
    def _tb_period(self):
        try:
            us = float(self.tb_period_us.get())
        except ValueError:
            return None
        return us * 1e-6 if math.isfinite(us) and 0.001 <= us <= 1e6 else None

    def timebase_points(self):
        period = self._tb_period() or 10e-6
        return [dict(channel=1, marker_period_s=period, nominal_hz=1.0 / period, scale_v_div=TB_SCALE,
                     lower_hz=-TIMEBASE_LIMIT_HZ, upper_hz=TIMEBASE_LIMIT_HZ)]

    def show_timebase(self):
        self.tb_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.tb_tab, text='Time Base')
        outer = ttk.Frame(self.tb_tab, padding=14)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, textvariable=self.tb_status).pack(anchor='w', pady=5)
        cols = ('period', 'nominal', 'mean', 'error', 'low', 'high', 'unit', 'result')
        self.tb_tree = ttk.Treeview(outer, columns=cols, show='headings', height=2)
        for key, title, width in (('period', 'Marker', 90), ('nominal', 'Nominal', 110), ('mean', 'P1 Freq mean', 130), ('error', 'Error', 100),
                                  ('low', 'Lower limit', 100), ('high', 'Upper limit', 100), ('unit', 'Units', 60), ('result', 'Result', 80)):
            self.tb_tree.heading(key, text=title)
            self.tb_tree.column(key, width=width, anchor='center')
        self.tb_tree.pack(fill='both', expand=True)

    def _tb_settings(self):
        try:
            settle, samples, baud = float(self.tb_settle.get()), int(self.tb_samples.get()), int(self.fluke_baud.get())
            if not (.5 <= settle <= 60 and 1 <= samples <= 50 and baud > 0) or self._tb_period() is None:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Time base settings', 'Settle must be 0.5-60 s, samples 1-50, the marker period a positive number of '
                                 'microseconds and the baud numeric (Test settings).', parent=self.root)
            return None
        return settle, samples, baud

    def _tb_confirm(self, title, heading, point):
        period, nominal = point['marker_period_s'], point['nominal_hz']
        return ui.confirm_steps(self.root, title, heading,
            [('Standby', 'Confirm the Fluke is in STBY.'),
             ('Connect', 'Fluke SCOPE output to CH1 with a 50 Ω cable. Remove other cables and any feedthrough terminator.'),
             ('Automatic', 'The program sets CH1 to DC 50 Ω, full bandwidth and P1 Freq, then outputs the time marker.')],
            facts=[('Marker period', f'{period*1e6:g} µs'), ('Frequency', f'{nominal/1e3:g} kHz'),
                   ('Limit', f'±{TIMEBASE_LIMIT_HZ:.3f} Hz')],
            caution='First hardware run: the 5560A SCOPE MARKER commands are not yet verified. The test stops without enabling the '
                    'output if the calibrator rejects them. Check the marker period against your procedure (Test settings).',
            ok='Connected and safe — run')

    def start_timebase(self):
        if self._batch_busy():
            messagebox.showwarning('Busy', 'Another instrument operation is running.', parent=self.root)
            return
        if self.tb_rows:
            messagebox.showinfo('Complete', 'The time base point is recorded. Use Rerun Selected to measure it again.', parent=self.root)
            return
        cfg = self._tb_settings()
        if cfg is None:
            return
        point = self.timebase_points()[0]
        if not self._tb_confirm('Time base accuracy', 'Connect the Fluke SCOPE output to CH1', point):
            self.tb_status.set('Time base not run - connection not confirmed')
            return
        self._run_timebase(point, cfg)

    def retest_timebase(self):
        idx = self._retest_index(self.tb_tree, self.tb_rows, 'time base', self.tb_tab)
        if idx is None:
            return
        cfg = self._tb_settings()
        if cfg is None:
            return
        point = self.timebase_points()[0]
        if not self._tb_confirm('Confirm time base retest', 'Retest the time base point', point):
            return
        self.tb_retest_index = idx
        self._run_timebase(point, cfg)

    def _run_timebase(self, point, cfg):
        settle, samples, baud = cfg
        self.tb_running = True
        self.tb_status.set(f'Running time base: {point["marker_period_s"]*1e6:g} µs marker on CH1')
        threading.Thread(target=self.timebase_worker, args=(point, settle, samples, self.fluke_address.get().strip(), baud,
                                                            self.visa_address.get().strip()), daemon=True).start()

    def timebase_worker(self, point, settle, samples, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log)       # before the first point
            ch, period = point['channel'], point['marker_period_s']
            stage = 'Scope scale and zero offset'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            scope.ensure_zero_offset(ch)
            stage = 'Scope DC 50 Ω and full bandwidth'
            scope.set_coupling(ch, 'DC50')
            scope.set_bandwidth_limit(ch, 'Full')
            stage = 'Scope edge trigger (CH1, positive, Auto)'
            scope.set_edge_trigger_source(ch)
            scope.set_trigger_slope('Positive')
            scope.set_trigger_level(TB_TRIGGER_V)
            scope.set_trigger_mode('Auto')
            stage = 'Scope horizontal scale (about 100 marker periods on screen)'
            scope.set_timebase(10 * period)
            stage = 'Scope P1 Freq'
            scope.configure_p1(ch, 'Freq', show=False)
            stage = 'Fluke SCOPE MARKER'
            fluke.select_scope_marker()
            stage = 'Fluke marker period'
            fluke.set_marker_period(period)
            stage = 'Fluke OPER'
            fluke.operate()
            stage = 'Settling, discarding first P1 read'
            time.sleep(settle)
            scope.read_p1()
            stage = 'P1 Freq readings'
            readings = []
            for _ in range(samples):
                time.sleep(self.pm_param('ws.tb_read_gap', TB_READ_GAP_S))
                readings.append(scope.read_p1())
            stage = 'Fluke standby after point'
            fluke.standby()
            mean = sum(readings) / len(readings)
            if not 0.99 * point['nominal_hz'] <= mean <= 1.01 * point['nominal_hz']:
                raise RuntimeError(f'P1 Freq averaged {mean:.9g} Hz, more than 1 % away from {point["nominal_hz"]:.9g} Hz '
                                   '(wrong marker period, no signal, cable or P1 setup). No result recorded.')
            self.events.put(('tb_result', point, readings, list(fluke.stale_errors)))
        except Exception as exc:
            self.events.put(('tb_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Time base {point["marker_period_s"]*1e6:g} us marker'):
                self.events.put(('tb_safety', 'Fluke standby NOT confirmed. Inspect the Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('tb_idle',))

    def record_timebase(self, point, readings, stale_errors=()):
        mean = sum(readings) / len(readings)
        error = mean - point['nominal_hz']
        spread = (sum((x - mean) ** 2 for x in readings) / (len(readings) - 1)) ** .5 if len(readings) > 1 else 0.0
        row = dict(point, readings_hz=readings, mean_hz=mean, error_hz=error, stdev_hz=spread,
                   result='PASS' if point['lower_hz'] <= error <= point['upper_hz'] else 'FAIL',
                   method=f'Fluke 5560A SCOPE MARKER {point["marker_period_s"]*1e6:g} us into DC 50 Ohm; scope P1 Freq, mean of {len(readings)}',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='Limits from HAZ-OSC-02 data sheet; no guard band')
        if stale_errors:
            row['fluke_errors_cleared_before_marker'] = list(stale_errors)   # from earlier sessions, read out before SCOPE MARKER
        idx = self.tb_retest_index
        if idx is not None:
            previous = self.tb_rows[idx]
            row['retest_history'] = previous.get('retest_history', []) + [{
                'timestamp': previous.get('timestamp'), 'result': previous.get('result'),
                'previous_row': {k: v for k, v in previous.items() if k != 'retest_history'}}]
            self.tb_rows[idx] = row
            self.tb_retest_index = None
        else:
            self.tb_rows.append(row)
        self.save_timebase_checkpoint()
        self.refresh_timebase()

    def refresh_timebase(self):
        items = []
        for i, p in enumerate(self.timebase_points()):
            r = self.tb_rows[i] if i < len(self.tb_rows) else None
            src = r or p
            values = (f'{src["marker_period_s"]*1e6:g} µs', f'{src["nominal_hz"]:.9g}',
                      f'{r["mean_hz"]:.9g}' if r else '', f'{r["error_hz"]:+.4f}' if r else '',
                      f'{src["lower_hz"]:+.3f}', f'{src["upper_hz"]:+.3f}', 'Hz', r['result'] if r else '—')
            items.append((values, self._tag(len(self.tb_rows), i, r['result'] if r else None)))
        self._set_grid(self.tb_tree, items, active=len(self.tb_rows))
        self.tb_status.set(f'{len(self.tb_rows)} of 1 time base point recorded')

    def save_timebase_checkpoint(self):
        temp = self.tb_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.tb_rows, indent=2), encoding='utf-8')
        temp.replace(self.tb_checkpoint)

    def load_timebase_checkpoint(self):
        if not self.tb_checkpoint.exists():
            return
        try:
            rows = json.loads(self.tb_checkpoint.read_text(encoding='utf-8'))
            if not isinstance(rows, list) or len(rows) > 1:
                raise ValueError('Invalid checkpoint length')
            for row in rows:
                if not isinstance(row, dict) or row.get('channel') != 1 or not row.get('marker_period_s') \
                        or not self._pm_limits_ok(row, 'timebase', (-TIMEBASE_LIMIT_HZ, TIMEBASE_LIMIT_HZ)):
                    raise ValueError('Checkpoint point mismatch')
            self.tb_rows = rows
            self.refresh_timebase()
        except Exception as exc:
            messagebox.showwarning('Time base checkpoint', f'Could not load the saved time base result: {exc}', parent=self.root)

    # ======================================================================== trigger level accuracy (24 points, bracket test)
    # Limits from the HAZ-OSC-02 data sheet, pages 10-11 (rendered page images): CH1-CH4 x 0 / +300 / -300 mV x positive and
    # negative slope, level +/-20 mV. Method agreed with the technician: scope armed in Single at the level, the Fluke steps
    # SCOPE DCV from 100 mV before the level to 20 mV short of it (must NOT trigger), then to 20 mV past it (must trigger).
    # The operator answers both questions. A pass shows the trigger fired within +/-20 mV; no voltage is measured.
    @staticmethod
    def trigger_points():
        return [dict(channel=ch, scale_v_div=TRIG_SCALE, level_v=level, slope=slope,
                     lower_v=round(level - TRIG_LIMIT_V, 6), upper_v=round(level + TRIG_LIMIT_V, 6))
                for ch in range(1, 5) for level in TRIG_LEVELS for slope in ('Positive', 'Negative')]

    @staticmethod
    def trigger_outcome(row):
        if row.get('triggered_short'):
            return 'Triggered 20 mV early'
        if row.get('triggered_past') is False:
            return 'No trigger 20 mV past'
        return 'Within ±20 mV'

    def show_trigger(self):
        self.trig_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.trig_tab, text='Trigger Level')
        outer = ttk.Frame(self.trig_tab, padding=14)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, textvariable=self.trig_status).pack(anchor='w', pady=5)
        cols = ('ch', 'level', 'slope', 'low', 'high', 'outcome', 'result')
        self.trig_tree = ttk.Treeview(outer, columns=cols, show='headings')
        for key, title, width in (('ch', 'Channel', 80), ('level', 'Level (mV)', 100), ('slope', 'Slope', 90), ('low', 'Lower (mV)', 100),
                                  ('high', 'Upper (mV)', 100), ('outcome', 'Outcome', 170), ('result', 'Result', 80)):
            self.trig_tree.heading(key, text=title)
            self.trig_tree.column(key, width=width, anchor='center')
        self.trig_tree.pack(fill='both', expand=True)

    def _trig_settings(self):
        try:
            settle, baud = float(self.trig_settle.get()), int(self.fluke_baud.get())
            if not (.2 <= settle <= 30 and baud > 0):
                raise ValueError()
        except ValueError:
            messagebox.showerror('Trigger level settings', 'Settle must be 0.2-30 s and the baud numeric (Test settings).', parent=self.root)
            return None
        return settle, baud

    def start_trigger(self):
        if self._batch_busy():
            messagebox.showwarning('Busy', 'Another instrument operation is running.', parent=self.root)
            return
        if len(self.trig_rows) >= len(self.trigger_points()):
            messagebox.showinfo('Complete', 'All 24 trigger level points are recorded.', parent=self.root)
            return
        if self._trig_settings() is None:
            return
        if not ui.confirm_steps(self.root, 'Trigger level test method', 'Trigger level accuracy — you confirm each trigger',
            [('Setup', 'The program sets the channel to 100 mV/div, DC 1 MΩ, 20 MHz BW, edge trigger on that channel at the test level, '
                       'and arms a Single acquisition.'),
             ('Step 1', 'The Fluke steps to 20 mV SHORT of the level. You answer whether the scope triggered (it should not).'),
             ('Step 2', 'The Fluke steps to 20 mV PAST the level. You answer whether the scope triggered (it should).'),
             ('Triggered means', 'the trigger status changes from armed/Single to Stopped and a trace is captured.')],
            caution='The Fluke SCOPE DC output is enabled (at most 0.4 V) while you answer, and returns to STBY after every point. '
                    'The scope trigger commands are not yet verified on a 4104HD: check the first point on screen.',
            ok='Understood — start'):
            return
        self.trig_batch = True
        self.trig_ok = False
        self.trig_connected_channel = None
        self.next_trigger()

    def stop_trigger(self):
        self.trig_batch = False
        self.trig_ok = False
        self.trig_status.set('Stopped after the current point; saved results retained.')

    def next_trigger(self):
        if not self.trig_batch or self.trig_running:
            return
        points = self.trigger_points()
        idx = len(self.trig_rows)
        if idx >= len(points):
            self.trig_batch = False
            self.trig_status.set('Complete — 24 of 24 trigger level points')
            messagebox.showinfo('Complete', 'All 24 trigger level points recorded.', parent=self.root)
            return
        point = points[idx]
        ch = point['channel']
        if self.trig_connected_channel != ch:
            if not ui.confirm_steps(self.root, 'Trigger level cable connection', f'Connect the Fluke SCOPE output to CH{ch}',
                [('Standby', 'Confirm the Fluke is in STBY.'),
                 ('Connect', f'Fluke SCOPE output to CH{ch} (1 MΩ input, no terminator). Disconnect other sources.')],
                facts=[('Point', f'{idx+1} of 24'), ('Channel', f'CH{ch}')],
                caution='Press OK only after the connection is safe.', ok='Connected and safe — continue'):
                self.trig_batch = False
                self.trig_status.set('Paused — awaiting safe cable connection')
                return
            self.trig_connected_channel = ch
        self._run_trigger(idx, point)

    def retest_trigger(self):
        idx = self._retest_index(self.trig_tree, self.trig_rows, 'trigger level', self.trig_tab)
        if idx is None:
            return
        if self._trig_settings() is None:
            return
        point = self.trigger_points()[idx]
        if not ui.confirm_steps(self.root, 'Confirm trigger level retest', f'Retest trigger level point {idx+1} of 24',
            [('Connection', f'Confirm the Fluke SCOPE output is connected to CH{point["channel"]}.'),
             ('You confirm', 'You will be asked twice whether the scope triggered.')],
            facts=[('Channel', f'CH{point["channel"]}'), ('Level', f'{point["level_v"]*1000:+.0f} mV'), ('Slope', point['slope'])],
            caution='The prior result is replaced only when the retest completes.', ok='Ready — retest'):
            return
        self.trig_batch = False
        self.trig_retest_index = idx
        self._run_trigger(idx, point)

    def _run_trigger(self, idx, point):
        settle, baud = self._trig_settings()
        self.trig_running = True
        self.trig_status.set(f'Running {idx+1}/24: CH{point["channel"]} | {point["level_v"]*1000:+.0f} mV | {point["slope"]} slope')
        threading.Thread(target=self.trigger_worker, args=(point, settle, self.fluke_address.get().strip(), baud,
                                                           self.visa_address.get().strip()), daemon=True).start()

    def ask_operator(self, title, question):
        """From a worker thread: show a Yes / No / Cancel question on the Tk thread and wait for the answer."""
        reply = queue.Queue()
        self.events.put(('ask', title, question, reply))
        return reply.get()

    def trigger_worker(self, point, settle, fluke_addr, baud, scope_addr):
        log = drivers.CommandLog()
        fluke = scope = None
        stage = 'opening instruments'
        ch, level, slope = point['channel'], point['level_v'], point['slope']
        sign = 1 if slope == 'Positive' else -1
        start, short, past = (round(level - sign * TRIG_START_V, 6), round(level - sign * TRIG_LIMIT_V, 6),
                              round(level + sign * TRIG_LIMIT_V, 6))
        title = f'Trigger level CH{ch} {level*1000:+.0f} mV {slope.lower()} slope'
        try:
            fluke, scope = self.open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=15)
            stage = 'Fluke serial connection / identity'
            fluke.open()
            stage = 'Fluke standby'
            fluke.standby()
            stage = 'Scope USB connection and read-only handshake'
            scope.open()
            scope.handshake()
            stage = 'reset to default settings'
            self.reset_bench(fluke, scope, log)       # before the first point
            stage = 'Scope scale, DC 1 MΩ / 20 MHz and zero offset'
            scope.set_vertical_scale(ch, point['scale_v_div'])
            scope.configure_dc_input(ch)
            scope.ensure_zero_offset(ch)
            scope.set_timebase(TRIG_HSCALE)
            stage = 'Scope edge trigger source, slope and level'
            scope.set_edge_trigger_source(ch)
            scope.set_trigger_slope(slope)
            level_readback = scope.set_trigger_level(level)
            stage = f'Fluke SCOPE DCV {start*1000:+.0f} mV (100 mV before the level) and OPER'
            fluke.apply_scope_dc(start)
            time.sleep(settle)
            stage = 'Scope arm Single'
            armed = scope.set_trigger_mode('Single', accept=('Stopped',))
            if armed.casefold() == 'stopped':
                raise RuntimeError('The scope triggered as soon as it was armed, before the Fluke stepped. No result recorded.')
            time.sleep(0.5)
            stage = f'Fluke step to {short*1000:+.0f} mV (20 mV short of the level)'
            fluke.set_dc_volts(short)
            if not fluke.is_operating():
                raise RuntimeError('The Fluke left OPERATE when the level changed.')
            time.sleep(settle)
            stage = 'Operator: trigger before the level?'
            triggered_short = self.ask_operator(title,
                f'The Fluke now outputs {short*1000:+.0f} mV, 20 mV short of the {level*1000:+.0f} mV trigger level '
                f'({slope.lower()} slope).\n\nDid the scope TRIGGER (status changed to Stopped, trace captured)?\n\n'
                'Yes = it triggered   No = still armed   Cancel = abandon this point')
            triggered_past = None
            if triggered_short is None:
                raise OperatorCancelled()
            if not triggered_short:
                stage = f'Fluke step to {past*1000:+.0f} mV (20 mV past the level)'
                fluke.set_dc_volts(past)
                if not fluke.is_operating():
                    raise RuntimeError('The Fluke left OPERATE when the level changed.')
                time.sleep(settle)
                stage = 'Operator: trigger past the level?'
                triggered_past = self.ask_operator(title,
                    f'The Fluke now outputs {past*1000:+.0f} mV, 20 mV past the {level*1000:+.0f} mV trigger level '
                    f'({slope.lower()} slope).\n\nDid the scope TRIGGER now?\n\n'
                    'Yes = it triggered   No = still armed   Cancel = abandon this point')
                if triggered_past is None:
                    raise OperatorCancelled()
            stage = 'Fluke standby after point'
            fluke.standby()
            self.events.put(('trig_result', point, dict(start_v=start, short_v=short, past_v=past, level_readback_v=level_readback,
                                                        triggered_short=bool(triggered_short), triggered_past=triggered_past)))
        except OperatorCancelled:
            self.events.put(('trig_cancel', 'Point abandoned at the operator prompt. Nothing was recorded.'))
        except Exception as exc:
            self.events.put(('trig_error', f'Failure at {stage}: {type(exc).__name__}: {exc}\n'
                             'Verify Fluke STBY on the front panel before touching cables.'))
        finally:
            if not self.finish_bench(fluke, scope, log, f'Trigger CH{ch} {level*1000:+.0f} mV {slope}'):
                self.events.put(('trig_safety', 'Fluke standby NOT confirmed. Inspect the Fluke front panel; do not disconnect until STBY.'))
            self.events.put(('trig_idle',))

    def record_trigger(self, point, info):
        passed = not info['triggered_short'] and info['triggered_past'] is True
        row = dict(point, **info, result='PASS' if passed else 'FAIL',
                   method='Bracket: Fluke 5560A SCOPE DCV stepped to 20 mV short of and 20 mV past the level; scope Single edge trigger; operator confirmed',
                   timestamp=datetime.now().isoformat(timespec='seconds'),
                   note='Limits from HAZ-OSC-02 data sheet; pass/fail by bracket, no trigger voltage measured')
        row['outcome'] = self.trigger_outcome(row)
        idx = self.trig_retest_index
        if idx is not None:
            previous = self.trig_rows[idx]
            row['retest_history'] = previous.get('retest_history', []) + [{
                'timestamp': previous.get('timestamp'), 'result': previous.get('result'),
                'previous_row': {k: v for k, v in previous.items() if k != 'retest_history'}}]
            self.trig_rows[idx] = row
            self.trig_retest_index = None
        else:
            self.trig_rows.append(row)
        self.save_trigger_checkpoint()
        self.refresh_trigger()

    def refresh_trigger(self):
        done = len(self.trig_rows)
        items = []
        for i, p in enumerate(self.trigger_points()):
            r = self.trig_rows[i] if i < done else None
            values = (f'CH{p["channel"]}', f'{p["level_v"]*1000:+.2f}', p['slope'], f'{p["lower_v"]*1000:+.2f}', f'{p["upper_v"]*1000:+.2f}',
                      r['outcome'] if r else '', r['result'] if r else '—')
            items.append((values, self._tag(done, i, r['result'] if r else None)))
        self._set_grid(self.trig_tree, items, active=done)
        self.trig_status.set(f'{done} of 24 trigger level points recorded')

    def save_trigger_checkpoint(self):
        temp = self.trig_checkpoint.with_suffix('.tmp')
        temp.write_text(json.dumps(self.trig_rows, indent=2), encoding='utf-8')
        temp.replace(self.trig_checkpoint)

    def load_trigger_checkpoint(self):
        if not self.trig_checkpoint.exists():
            return
        try:
            rows = json.loads(self.trig_checkpoint.read_text(encoding='utf-8'))
            points = self._pm_ckpt_points('trigger', rows)
            if not isinstance(rows, list) or len(rows) > len(points):
                raise ValueError('Invalid checkpoint length')
            for i, row in enumerate(rows):
                if not isinstance(row, dict) or any(row.get(k) != points[i][k] for k in ('channel', 'level_v', 'slope', 'lower_v', 'upper_v')):
                    raise ValueError(f'Checkpoint point {i+1} mismatch')
            self.trig_rows = rows
            self.refresh_trigger()
        except Exception as exc:
            messagebox.showwarning('Trigger level checkpoint', f'Could not load saved trigger level results: {exc}', parent=self.root)


    def load_demo_data(self):
        """Synthetic, memory-only export test data; no VISA, no checkpoint writes."""
        if any((self.rows,self.dc_rows,self.imp_rows,self.offset_rows,self.bw_rows,self.tb_rows,self.trig_rows)):
            messagebox.showwarning('Demo data',
                'Existing calibration results are loaded. Demo data will not be mixed with them. '
                'Use a separate empty folder to launch --demo.')
            return
        self.demo_mode=True
        self.root.title('DEMO DATA ONLY — WaveSurfer Calibration Export Tester')
        stamp=datetime.now().isoformat(timespec='seconds')
        channels=list(range(1,5))
        scales=SCALES
        self.run_config=dict(channels=channels,channel=1,address='DEMO — NO INSTRUMENT',
            delay=3,samples=5,factor=2.75,limits=LIMITS)
        for ch in channels:
            for j,scale in enumerate(scales):
                minimum=LIMITS[j]
                db=minimum+2.5+(ch+j)%4*.7
                if ch==2 and j==3: db=minimum-1.1
                rms=(2.75*scale)/(10**(db/20))
                self.add_result(dict(channel=ch,scale_v_div=scale,rms_volts=rms,
                    db=db,minimum_db=minimum,margin_db=db-minimum,
                    result='PASS' if db>=minimum else 'FAIL',samples=5,
                    timestamp=stamp,synthetic=True))
        for i,point in enumerate(self.dcv_points()):
            p=dict(point)
            tolerance=(p['upper_v']-p['lower_v'])/2
            measured=p['nominal_v']+tolerance*(1.12 if i==8 else .14*((i%5)-2))
            p.update(measured_v=measured,error_v=measured-p['nominal_v'],
                result='PASS' if p['lower_v']<=measured<=p['upper_v'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.dc_rows.append(p)
        self.refresh_dcv_table()
        for i,point in enumerate(self.impedance_points()):
            p=dict(point)
            nominal=p['nominal_ohm']
            measured=nominal*(1.025 if i==2 else 1+.001*((i%7)-3))
            p.update(measured_ohm=measured,error_ohm=measured-nominal,
                result='PASS' if p['lower_ohm']<=measured<=p['upper_ohm'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.imp_rows.append(p)
            self.render_impedance(i+1,p)
        self.imp_progress['value']=len(self.imp_rows)
        for i,point in enumerate(self.offset_points()):
            p=dict(point)
            tolerance=(p['upper_v']-p['lower_v'])/2
            measured=p['nominal_v']+tolerance*(1.2 if i==4 else .16*((i%5)-2))
            p.update(fluke_programmed_v=p['nominal_v'],measured_v=measured,
                error_v=measured-p['nominal_v'],
                result='PASS' if p['lower_v']<=measured<=p['upper_v'] else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.offset_rows.append(p)
        self.refresh_offset()
        for i,point in enumerate(self.bandwidth_points()):
            p=dict(point)
            reference=p['amplitude_vpp']*(.995+.001*(i%5))
            response=-1.2-.14*(i%6)
            if i==12: response=-3.4
            high=reference*10**(response/20)
            p.update(reference_measured_vpp=reference,high_measured_vpp=high,
                response_db=response,
                result='PASS' if -3<=response<=3 else 'FAIL',
                synthetic=True,timestamp=stamp)
            self.bw_rows.append(p)
        self.refresh_bandwidth()
        for point in self.timebase_points():
            p=dict(point)
            readings=[p['nominal_hz']*(1+1.1e-7)+.004*((k%3)-1) for k in range(5)]
            mean=sum(readings)/len(readings)
            p.update(readings_hz=readings,mean_hz=mean,error_hz=mean-p['nominal_hz'],stdev_hz=.004,
                result='PASS' if p['lower_hz']<=mean-p['nominal_hz']<=p['upper_hz'] else 'FAIL',synthetic=True,timestamp=stamp)
            self.tb_rows.append(p)
        self.refresh_timebase()
        for i,point in enumerate(self.trigger_points()):
            p=dict(point,triggered_short=(i==9),triggered_past=None if i==9 else True,synthetic=True,timestamp=stamp)
            p['result']='FAIL' if i==9 else 'PASS'
            p['outcome']=self.trigger_outcome(p)
            self.trig_rows.append(p)
        self.refresh_trigger()
        self.status.set('DEMO MODE — Synthetic data only; no instrument measurements')
        self.dc_status.set('DEMO DATA — 80 synthetic DCV points')
        self.imp_status.set('DEMO DATA — 28 synthetic impedance points')
        self.offset_status.set('DEMO DATA — 16 synthetic offset points')
        self.bw_status.set('DEMO DATA — 24 synthetic bandwidth points')
        self.tb_status.set('DEMO DATA — 1 synthetic time base point')
        self.trig_status.set('DEMO DATA — 24 synthetic trigger level points')
        messagebox.showinfo('Demo export ready',
            f'Loaded {sum(len(r) for r in (self.rows,self.dc_rows,self.imp_rows,self.offset_rows,self.bw_rows,self.tb_rows,self.trig_rows))} '
            'SYNTHETIC results in memory across seven functions. '
            'Use Export Report (PDF). '
            'No checkpoint files were written. Do not use as calibration evidence.')


    @staticmethod
    def cert_number(value, decimals=5):
        if value is None:
            return ''
        return f'{float(value):.{decimals}f}'.rstrip('0').rstrip('.') if decimals else str(value)

    @staticmethod
    def cert_scale(scale):
        if scale is None:
            return ''
        if scale < .001:
            return f'{scale*1e6:g}uV/Div'
        if scale < 1:
            return f'{scale*1000:g}mV/Div'
        return f'{scale:g}V/Div'

    def scope_uncertainty_value(self, kind, r):
        """(value, unit) of the scope CMC for one result - the number behind scope_uncertainty - or None when the scope has no entry."""
        sc=__import__('report_pdf').scope()
        if sc is None:
            return None
        try:
            if kind=='dcv':
                value,unit,_=sc.oscilloscope('offset',volts=r['nominal_v'],impedance='1M')   # absolute volts, as the row is in volts
            elif kind=='impedance':
                value,unit,_=sc.oscilloscope('impedance',ohms=r['nominal_ohm'])
            elif kind=='offset':
                value,unit,_=sc.oscilloscope('offset',volts=r['nominal_v'])
            elif kind=='bandwidth':
                value,unit,_=sc.oscilloscope('bandwidth',volts_pp=r['amplitude_vpp'],frequency=r['high_hz'])
            elif kind=='trigger':
                # Based on the DC voltage the Fluke sources for the point: the two bracket steps (20 mV short of and 20 mV past the
                # level) decide pass/fail, so the larger of the two is used (the CMC grows with the level). Absolute volts, 1 MOhm.
                if 'short_v' in r and 'past_v' in r:
                    sourced=max(abs(r['short_v']),abs(r['past_v']))
                else:
                    sourced=abs(r['level_v'])+TRIG_LIMIT_V          # results saved before the sourced steps were recorded
                value,unit,_=sc.oscilloscope('offset',volts=sourced,impedance='1M')
            else:
                return None
        except (KeyError,TypeError,ZeroDivisionError):
            return None
        return (value,unit) if value is not None else None

    def scope_uncertainty(self, kind, r):
        """CMC from the laboratory's A2LA scope for one result ('' when the scope has no entry, e.g. RMS noise)."""
        import uncertainty
        parts=self.scope_uncertainty_value(kind,r)
        return uncertainty.format_value(parts[0],parts[1]) if parts is not None else ''

    # Tolerance (half the width of the limits, in the unit of the row's base values) per kind: (low key, high key, unit)
    _TOL_KEYS={'dcv':('lower_v','upper_v','V'),'impedance':('lower_ohm','upper_ohm','ohm'),'offset':('lower_v','upper_v','V'),
               'bandwidth':('lower_db','upper_db','dB'),'trigger':('lower_v','upper_v','V')}

    def tar_tur_fields(self, kind, r):
        """dict(TAR, TUR) strings for one result record, used only when the report asks for them.
        TUR = tolerance / the scope CMC printed in the Uncertainty column (same value, rounded up), only when both are in the same unit
        (volts, ohm, dB): DC gain, impedance, offset, bandwidth and trigger level.  RMS noise and time base have no printed uncertainty: blank.
        TAR only where the Fluke 5560A sources plain DC volts (DC gain, offset, trigger level): its specmanager DCV row at that voltage,
        in volts.  Impedance (a measurement) and bandwidth (leveled sine, tolerance in dB) have no matching specification row: TAR blank."""
        import tartur, uncertainty
        try:
            keys=self._TOL_KEYS.get(kind)
            if keys is None:
                return dict(TAR='',TUR='')
            parts=self.scope_uncertainty_value(kind,r)
            u=uu=None
            if parts is not None:
                u,uu=uncertainty.round_up(parts[0]),parts[1]
            acc=au=None
            if kind in ('dcv','offset'):
                acc,au=tartur.standard_accuracy('5560A','DCV',abs(r['nominal_v']))
            elif kind=='trigger':
                if 'short_v' in r and 'past_v' in r:
                    sourced=max(abs(r['short_v']),abs(r['past_v']))
                else:
                    sourced=abs(r['level_v'])+TRIG_LIMIT_V
                acc,au=tartur.standard_accuracy('5560A','DCV',sourced)
            tol=tartur.half_width(r[keys[0]],r[keys[1]])
            return tartur.ratio_fields(tartur.from_values(tol,keys[2],acc,au,u,uu))
        except Exception:
            return dict(TAR='',TUR='')

    def certificate_rows(self, kind, with_uncertainty=False):
        """Report rows: the As Found readings, with the As Left reading beside any point that was measured again after an adjustment
        ('Same' is printed by the PDF for the others)."""
        frows = self._cert_records(kind, self._stored_rows(datamode.FOUND, kind), with_uncertainty)
        lrows = self._cert_records(kind, self._stored_rows(datamode.LEFT, kind), with_uncertainty)
        out = []
        for i in range(max(len(frows), len(lrows))):
            f = frows[i] if i < len(frows) else None
            l = lrows[i] if i < len(lrows) else None
            if f is None:                                   # measured only after the adjustment
                row = dict(l, **{'As Found': '', 'OOT': '', 'As Left': l['As Found'], 'As Left OOT': bool(l['OOT'])})
            else:
                row = dict(f)
                if l is not None:
                    row['As Left'] = l['As Found']
                    row['As Left OOT'] = bool(l['OOT'])
            row['Seq.'] = len(out) + 1
            out.append(row)
        return out

    def certificate_source_records(self, kind):
        """The stored result record behind each row of certificate_rows(kind), in the same order (As Found, else the As Left one)."""
        found=self._stored_rows(datamode.FOUND,kind)
        left=self._stored_rows(datamode.LEFT,kind)
        return [found[i] if i < len(found) else left[i] for i in range(max(len(found),len(left)))]

    def _cert_records(self, kind, data, with_uncertainty=False):
        result=[]
        for r in data:
            ch=r.get('channel','')
            channel = str(ch) if str(ch).upper().startswith(('C','EXT')) else f'Ch. {ch}'
            scale=self.cert_scale(r.get('scale_v_div'))
            if kind=='noise':
                desc=f'{channel} RMS Noise {scale}'
                nominal=self.cert_number(r.get('minimum_db'),3)
                lower=self.cert_number(r.get('minimum_db'),3)
                upper=''
                uom='dB'
                measured=self.cert_number(r.get('db'),4)
            elif kind=='dcv':
                desc=f'{channel} 1MOhm DC Gain {scale}'
                factor=1000 if abs(r['nominal_v']) < 1 else 1
                uom='mV' if factor==1000 else 'V'
                nominal=self.cert_number(r['nominal_v']*factor,6)
                lower=self.cert_number(r['lower_v']*factor,6)
                upper=self.cert_number(r['upper_v']*factor,6)
                measured=self.cert_number(r['measured_v']*factor,6)
            elif kind=='impedance':
                desc=f'{channel} Impedance {scale} {r.get("coupling", "")}'.strip()
                # Display the MOhm values in MOhm, the 50-Ohm values in Ohm.
                factor=1e6 if r['nominal_ohm']>=1e5 else 1
                uom='MOhm' if factor>1 else 'Ohm'
                nominal=self.cert_number(r['nominal_ohm']/factor,6)
                lower=self.cert_number(r['lower_ohm']/factor,6)
                upper=self.cert_number(r['upper_ohm']/factor,6)
                measured=self.cert_number(r['measured_ohm']/factor,6)
            elif kind=='offset':
                desc=f'{channel} Offset {r["scope_offset_v"]:+g}V {scale} (P1 Mean)'
                nominal=self.cert_number(r['nominal_v'],6)
                lower=self.cert_number(r['lower_v'],6)
                upper=self.cert_number(r['upper_v'],6)
                uom='V'
                measured=self.cert_number(r['measured_v'],6)
            elif kind=='timebase':
                desc=(f'Time Base Accuracy, {r["marker_period_s"]*1e6:g} us marker '
                      f'({self.cert_number(r["nominal_hz"]/1e3,6)} kHz)')
                nominal='0'
                lower=self.cert_number(r['lower_hz'],3)
                upper=self.cert_number(r['upper_hz'],3)
                uom='Hz'
                measured=self.cert_number(r['error_hz'],4)
            elif kind=='trigger':
                level_mv='0' if r['level_v']==0 else f'{r["level_v"]*1000:+.0f}'
                desc=f'{channel} Trigger Level {level_mv} mV @ {"Pos" if r["slope"]=="Positive" else "Neg"} slope'
                nominal=self.cert_number(r['level_v']*1000,3)
                lower=self.cert_number(r['lower_v']*1000,3)
                upper=self.cert_number(r['upper_v']*1000,3)
                uom='mV'
                measured=r.get('outcome') or self.trigger_outcome(r)
            else:
                desc=f'{channel} FULL BW {scale}'
                amp=r['amplitude_vpp']
                amp_label=(f'{self.cert_number(amp*1000,5)} mVpp' if amp<1
                           else f'{self.cert_number(amp,5)} Vpp')
                nominal=f'0 dB @ {amp_label} @ {r["high_hz"]/1e9:g} GHz' 
                lower=self.cert_number(r['lower_db'],3)
                upper=self.cert_number(r['upper_db'],3)
                uom='dB'
                measured=self.cert_number(r['response_db'],4)
            uncertainty_text=self.scope_uncertainty(kind,r) if with_uncertainty else ''
            result.append({
                'Seq.': len(result)+1,
                'Description': desc,
                'Nominal': nominal,
                'Tolerance -': lower,
                'Tolerance +': upper,
                'UOM': uom,
                'As Found': measured,
                'OOT': 'OOT' if r.get('result')=='FAIL' else '',
                'As Left': '',
                'Uncertainty': uncertainty_text,
            })
        return result

    def export_calibration_section(self,kind):
        if not self.sync_asset():
            return
        rows=self.certificate_rows(kind)
        if not rows:
            messagebox.showinfo('No results',f'No {kind} measurements to export.')
            return
        import report_dialog
        details=report_dialog.ask_details(self.root,'WaveSurfer 4104HD verification')
        if details is None:
            return
        filename=filedialog.asksaveasfilename(
            defaultextension='.pdf',
            initialfile=ui.report_filename(self.instrument_id.get(),'.pdf',kind),
            filetypes=[('PDF report','*.pdf')])
        if not filename:
            return
        self.write_certificate_pdf(filename,[kind],details)

    def write_certificate_pdf(self, filename, sections, details=None):
        """'Calibration Data' PDF: laid out as a printable report."""
        titles={'noise':'RMS Noise','dcv':'DC Gain (1 MOhm)','impedance':'Input Impedance','offset':'DC Offset','bandwidth':'Bandwidth',
                'timebase':'Time Base Accuracy','trigger':'Trigger Level Accuracy'}
        rows=[]
        sources=[]
        for kind in sections:
            for row in self.certificate_rows(kind,with_uncertainty=True):
                row=dict(row)
                if not row.get('As Left'):
                    row['As Left']='Same'
                row['Section']=titles[kind]
                rows.append(row)
            sources.extend((kind,r) for r in self.certificate_source_records(kind))
        if not rows:
            messagebox.showinfo('No results','No recorded calibration data to export.')
            return 0
        try:
            import report_pdf, report_dialog
            if details is None:
                details=report_dialog.ask_details(self.root,'WaveSurfer 4104HD verification')
                if details is None:
                    return 0
            if report_pdf.details_tar_tur(details):
                rows=report_pdf.apply_tar_tur(rows,report_pdf.details_tar_tur(details),[self.tar_tur_fields(k,r) for k,r in sources])
            count=report_pdf.write_calibration_pdf(
                filename,rows,header=[('Instrument','Teledyne LeCroy WaveSurfer 4104HD'),
                                      ('Instrument ID',self.instrument_id.get().strip() or 'NOT ENTERED'),
                                      ('Serial',self.serial.get().strip())],
                demo=self.any_synthetic(),details=details,
                footer_note=report_pdf.uncertainty_note(rows),title='Calibration Data')
        except ImportError:
            messagebox.showerror('PDF export dependency','Install the PDF package with:  py -m pip install reportlab')
            return 0
        except Exception as exc:
            messagebox.showerror('PDF export error',str(exc))
            return 0
        messagebox.showinfo('Report exported',f'Created calibration data report with {count} rows:\n{filename}')
        return count

    def export_pdf_report(self):
        if not self.sync_asset():
            return
        sections=[k for k in ('noise','dcv','impedance','offset','bandwidth','timebase','trigger') if self.certificate_rows(k)]
        if not sections:
            messagebox.showinfo('No results','No recorded calibration data to export.')
            return
        try:
            import report_dialog
        except ImportError as exc:
            messagebox.showerror('Report export',str(exc))
            return
        details=report_dialog.ask_details(self.root,'WaveSurfer 4104HD verification')
        if details is None:
            return
        filename=filedialog.asksaveasfilename(
            defaultextension='.pdf',
            initialfile=ui.report_filename(self.instrument_id.get()),
            filetypes=[('PDF report','*.pdf')])
        if filename:
            self.write_certificate_pdf(filename,sections,details)

    def export_professional_excel(self):
        if not self.sync_asset():
            return
        sections=('noise','dcv','impedance','offset','bandwidth','timebase','trigger')
        groups={k:self.certificate_rows(k) for k in sections}
        if not any(groups.values()):
            messagebox.showinfo('No results','No calibration results to export.')
            return
        filename=filedialog.asksaveasfilename(
            defaultextension='.xlsx',
            initialfile=ui.report_filename(self.instrument_id.get(),'.xlsx'),
            filetypes=[('Excel workbook','*.xlsx')])
        if not filename:
            return
        try:
            count=make_report(groups,filename,synthetic=getattr(self,'demo_mode',False),
                              instrument_id=self.instrument_id.get())
        except ImportError:
            messagebox.showerror('Excel export dependency',
                'Install the Excel formatting package with: py -m pip install openpyxl')
            return
        except Exception as exc:
            messagebox.showerror('Excel export error',str(exc))
            return
        messagebox.showinfo('Report exported',
            f'Created formatted Excel report with {count} test points:\n{filename}')


# Procedure modifications: every section's point list goes through pm_section_points().  The original functions are left exactly as
# they were; these wrappers return THEIR list unchanged (the same object contents) unless a tolerance modification is in effect.
PM_POINT_METHODS = {'dcv': 'dcv_points', 'impedance': 'impedance_points', 'offset': 'offset_points', 'bandwidth': 'bandwidth_points',
                    'timebase': 'timebase_points', 'trigger': 'trigger_points'}


def _pm_wrap_points(section, name):
    raw = RMSNoiseApp.__dict__[name]
    static = isinstance(raw, staticmethod)
    orig = raw.__func__ if static else raw

    def points(self):
        pts = orig() if static else orig(self)
        return self.pm_section_points(section, pts)
    points.__name__, points.__doc__ = name, orig.__doc__
    points.pm_orig, points.pm_static = orig, static
    setattr(RMSNoiseApp, name, points)


for _section, _name in PM_POINT_METHODS.items():
    _pm_wrap_points(_section, _name)


if __name__ == '__main__':
    ui.enable_hidpi()
    root = tk.Tk()
    RMSNoiseApp(root)
    root.mainloop()
