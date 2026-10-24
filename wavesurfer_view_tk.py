"""WaveSurfer 4104HD verification: the Tk window code (layout of the shell, the sections' tabs, the results table, the settings dialog, widget states).

Moved out of Procedures/WaveSurfer_WS4104HD.py unchanged (the bodies of its former make_ui / build_unified / show_settings_dialog / show_dcv / show_impedance / show_offset /
show_bandwidth / show_timebase / show_trigger / _dialog_open / toggle_settings / _set_grid, and the statements the engine made on its widgets, one small function each).  The engine reaches
this module through `ui_port.ui.view('wavesurfer_view')`, which resolves to `wavesurfer_view_tk` under Tk; a Qt port provides `wavesurfer_view_qt` with the same functions.
Every function that works on the window takes the engine's App as `self` and keeps its widgets as attributes of it (`self.tree`, `self.dc_tree`, `self.btn_run`, ... the shared
mixins use them too).  Nothing here decides anything about a calibration.
"""
import sys
import tkinter as tk
from tkinter import ttk

import datamode
import ui_shell
import ui_theme as ui
from ui_port import ui as port


# ---- the window as a whole -----------------------------------------------------------------------------------------------------------------------------
def window_gone():
    """The exception Tk raises for a widget of a destroyed window (the periodic ticks stop on it)."""
    return tk.TclError


def enable_hidpi():
    """Before the root window exists (the statement `ui.enable_hidpi()` of the engine's __main__)."""
    ui.enable_hidpi()


def setup_window(self):
    """Theme, title and size of the main window (the first statements of the engine's former App.__init__)."""
    root = self.root
    ui.apply_theme(root)
    root.title('WaveSurfer 4104HD | Calibration Verification v56')
    ui.fit_window(root, 1300, 880, min_w=900, min_h=640)


def create_shell(self):
    """The shell, the scope chip and the notebook that holds each section (the statements of the engine's former App.__init__)."""
    self.shell = ui_shell.Shell(self.root, 'WaveSurfer 4104HD  -  Calibration Verification',
                                'Teledyne LeCroy  |  USBTMC / PyVISA  |  RMS noise, DC voltage, input impedance, offset, bandwidth, time base and trigger level',
                                demo='--demo' in sys.argv, on_section=self._pick_function, version='v56')
    self.conn_pill = self.shell.add_chip('Scope: not connected', 'neutral')
    # The five measurement sections are built inside a notebook that is never shown: it holds each section's settings, checkpoints and
    # workers. What the technician sees is the single results table below (build_unified), filterable by function.
    self.tabs = ttk.Notebook(self.root)
    self.rms_tab = ttk.Frame(self.tabs)
    self.tabs.add(self.rms_tab, text='RMS Noise')


def polish(self):
    ui.polish(self.root)


# ---- statements the engine makes on its widgets ------------------------------------------------------------------------------------------------------
def set_state(widget, state):
    widget.configure(state=state)


def set_value(bar, value):
    bar['value'] = value


def set_maximum(bar, value):
    bar['maximum'] = value


def tab_open(self, name):
    """`getattr(self, name, None) and self.<name>.winfo_exists()`: the section's tab has been built and still exists."""
    return getattr(self, name, None) and getattr(self, name).winfo_exists()


def set_tab_text(self, tab, text):
    if self.tabs.tab(tab, 'text') != text:
        self.tabs.tab(tab, text=text)


def set_chip(self, text, kind):
    self.conn_pill.set(text, kind)


def selection(tree):
    return tree.selection()


def row_index(tree, iid):
    return tree.index(iid)


def children(tree):
    return tree.get_children()


def select(tree, iid):
    tree.selection_set(iid)


def select_and_show(tree, iid):
    tree.selection_set(iid)
    tree.see(iid)


def show_unified(self, items, allp, fmap, lmap, total, passed, failed):
    """Fill the one results table, the progress ring and the section list (the body of the `if force or sig != self._shown` block of refresh_unified)."""
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



def set_grid(tree, items, active=None):
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


# ---- the windows -------------------------------------------------------------------------------------------------------------------------------------
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
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

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
    port.after(self.root, 500, self._unified_tick)
    import labregistry
    labregistry.attach(self.root, self.instrument_id, self.serial, self.msg.set)
    self.sync_asset()                       # --asset <ID> from the Manager


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
    self.pm_bind_tree(self.dc_tree, lambda iid, t=self.dc_tree: 'dcv:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
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
    self.pm_bind_tree(self.imp_tree, lambda iid, t=self.imp_tree: 'impedance:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
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
    self.pm_bind_tree(self.offset_tree, lambda iid, t=self.offset_tree: 'offset:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
    for key, title, width in (
        ('ch','Channel',80),('scale','Range',100),('offset','Scope offset',110),
        ('source','Fluke source',110),('mean','P1 Mean',110),
        ('error','Error',100),('low','Lower limit',105),('high','Upper limit',105),('units','Units',65),('result','Result',85)):
        self.offset_tree.heading(key,text=title)
        self.offset_tree.column(key,width=width,anchor='center')
    self.offset_tree.pack(side='left',fill='both',expand=True)
    _sb=ttk.Scrollbar(outer,orient='vertical',command=self.offset_tree.yview);_sb.pack(side='right',fill='y')
    self.offset_tree.configure(yscrollcommand=_sb.set)


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
    self.pm_bind_tree(self.bw_tree, lambda iid, t=self.bw_tree: 'bandwidth:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
    for k,label,w in (
        ('channel','Channel',85),('scale','Range',100),('amplitude','Stimulus',105),
        ('ref','50 kHz',105),('high','1 GHz',105),('vunit','Units',70),
        ('db','Response',100),('dunit','Units',60),('result','Result',90)):
        self.bw_tree.heading(k,text=label)
        self.bw_tree.column(k,width=w,anchor='center')
    self.bw_tree.pack(side='left',fill='both',expand=True)
    _sb=ttk.Scrollbar(outer,orient='vertical',command=self.bw_tree.yview);_sb.pack(side='right',fill='y')
    self.bw_tree.configure(yscrollcommand=_sb.set)


def show_timebase(self):
    self.tb_tab = ttk.Frame(self.tabs)
    self.tabs.add(self.tb_tab, text='Time Base')
    outer = ttk.Frame(self.tb_tab, padding=14)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, textvariable=self.tb_status).pack(anchor='w', pady=5)
    cols = ('period', 'nominal', 'mean', 'error', 'low', 'high', 'unit', 'result')
    self.tb_tree = ttk.Treeview(outer, columns=cols, show='headings', height=2)
    self.pm_bind_tree(self.tb_tree, lambda iid, t=self.tb_tree: 'timebase:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
    for key, title, width in (('period', 'Marker', 90), ('nominal', 'Nominal', 110), ('mean', 'P1 Freq mean', 130), ('error', 'Error', 100),
                              ('low', 'Lower limit', 100), ('high', 'Upper limit', 100), ('unit', 'Units', 60), ('result', 'Result', 80)):
        self.tb_tree.heading(key, text=title)
        self.tb_tree.column(key, width=width, anchor='center')
    self.tb_tree.pack(fill='both', expand=True)


def show_trigger(self):
    self.trig_tab = ttk.Frame(self.tabs)
    self.tabs.add(self.trig_tab, text='Trigger Level')
    outer = ttk.Frame(self.trig_tab, padding=14)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, textvariable=self.trig_status).pack(anchor='w', pady=5)
    cols = ('ch', 'level', 'slope', 'low', 'high', 'outcome', 'result')
    self.trig_tree = ttk.Treeview(outer, columns=cols, show='headings')
    self.pm_bind_tree(self.trig_tree, lambda iid, t=self.trig_tree: 'trigger:%d' % t.index(iid))      # right-click > Edit (tolerance only here)
    for key, title, width in (('ch', 'Channel', 80), ('level', 'Level (mV)', 100), ('slope', 'Slope', 90), ('low', 'Lower (mV)', 100),
                              ('high', 'Upper (mV)', 100), ('outcome', 'Outcome', 170), ('result', 'Result', 80)):
        self.trig_tree.heading(key, text=title)
        self.trig_tree.column(key, width=width, anchor='center')
    self.trig_tree.pack(fill='both', expand=True)


def dialog_open(self):
    return any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children())


def toggle_settings(self):
    if self.show_settings.get():
        self.config_frame.pack(fill='x', pady=(0, 10), before=self.actions)
    else:
        self.config_frame.pack_forget()
