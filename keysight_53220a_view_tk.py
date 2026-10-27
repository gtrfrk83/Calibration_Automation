"""Keysight 53210A / 53220A / 53230A performance verification: the Tk window code (layout, button states, results table, window chrome).

The engine reaches this module through `ui_port.ui.view('keysight_53220a_view')`, which resolves to `keysight_53220a_view_tk` under Tk; the Qt port provides
`keysight_53220a_view_qt` with the same functions.  Every function takes the engine's App as `self` and keeps its widgets as attributes of it (`self.tree`, `self.btn_run`, ...
the shared mixins use them too).  Nothing here decides anything about a calibration.
"""
import tkinter as tk
from tkinter import ttk

import datamode
import labregistry
import ui_shell
import ui_theme as ui
import virtualbench


def setup_window(self):
    """Theme, title and size of the main window."""
    import keysight_53220a_verification as E
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title(f'Keysight {E.MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1320, 820, min_w=900, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window."""
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def build_ui(self):
    import keysight_53220a_verification as E                      # the engine's module state (configure(model) rebinds MODEL), read at call time
    INTERFACES, MODEL, PERIODS, POINTS, SPEC = E.INTERFACES, E.MODEL, E.PERIODS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = ui_shell.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                                     f'Test points from the 53210A/53220A/53230A Service Guide, chapter 1  |  {len(POINTS)} points in the spec  |  USB, LAN or GPIB',
                                     demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program asks you to confirm the warm-up and the 10 MHz reference, and the wiring before every new setup. Tests on another standard (pulse, burst, '
                    'low-level microwave) show which standard to connect and what to set. Stay at the bench while a run is in progress.', 'info')

    # settings and connections live in the slide-in drawer
    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    state = {'r': 0}

    def row(text, widget, fill=False):
        r = state['r']; state['r'] += 1
        ttk.Label(d, text=text).grid(row=r, column=0, sticky='w', pady=4)
        widget.grid(row=r, column=1, sticky='ew' if fill else 'w', padx=(10, 0), pady=4)
        return widget

    def wide(widget, pady=(2, 4)):
        r = state['r']; state['r'] += 1
        widget.grid(row=r, column=0, columnspan=2, sticky='w', pady=pady)
        return widget

    def note(text):
        wide(ttk.Label(d, text=text, style='Muted.TLabel', wraplength=ui.px(340), justify='left'), (2, 8))

    def rule():
        r = state['r']; state['r'] += 1
        ttk.Separator(d).grid(row=r, column=0, columnspan=2, sticky='ew', pady=(0, 10))

    def combo(var, values, width, command=None, readonly=True):
        c = ttk.Combobox(d, textvariable=var, values=values, width=width, state='readonly' if readonly else 'normal')
        if command: c.bind('<<ComboboxSelected>>', lambda _e: command())
        return c

    self.period_combo = row('Limits to apply', combo(self.period, list(PERIODS), 20, self.on_period))
    self.set_combo = row('Test set', combo(self.test_set, ['Full verification', 'Quick check (Q points only)'], 26, self.refresh))
    rule()
    note('Options: filled in from *OPT? when you press Test connections; declare them here before that if you want to see the points. Option 201 (rear inputs) is not reported by *OPT?.')
    self.tb_combo = row('Time base', combo(self.tb_opt, list(E.TB_CHOICES), 22, self.on_options))
    self.ch3_combo = row('Microwave channel', combo(self.ch3_opt, list(E.CH3_CHOICES), 22, self.on_options))
    self.pulse_check = wide(ttk.Checkbutton(d, text='Option 150 pulse microwave (53230A)', variable=self.pulse_opt, command=self.on_options))
    self.rear_check = wide(ttk.Checkbutton(d, text='Option 201 rear-panel inputs', variable=self.rear_opt, command=self.on_options))
    rule()
    self.stim_combo = row('Stimulus', combo(self.stim_mode, list(E.STIM_CHOICES), 28, self.refresh))
    self.ref_combo = row('10 MHz reference', combo(self.ref_mode, list(E.REF_CHOICES), 24))
    self.loss_entry = row('Cable loss (dB)', combo(self.loss, ['0', '0.5', '1', '2', '3', '6'], 8, self.refresh, readonly=False))
    self.loss_entry.bind('<FocusOut>', lambda _e: self.refresh())
    self.low_check = wide(ttk.Checkbutton(d, text='96270A has the Extended Low Level option (-100 dBm on the Microwave O/P)', variable=self.ext_low, command=self.refresh))
    note('The cable loss is added to the level the 96270A is set to. The 96270A output route (Leveling Head / Microwave O/P) is chosen on its front panel.')
    rule()
    self.iface_combo = row(f'{MODEL} interface', combo(self.interface, list(INTERFACES), 10, self.on_interface))
    self.ctr_entry = row(f'{MODEL} address / resource', ttk.Combobox(d, textvariable=self.ctr_addr, state='normal', width=38), fill=True)
    note('USB: USB0::<mfgID>::<modelID>::<serial>::INSTR; LAN: TCPIP0::<ip>::inst0::INSTR; GPIB: GPIB0::<address>::INSTR. The examples are not verified for your bench: use Find instruments.')
    self.rf_entry = row('96270A address / resource', ttk.Combobox(d, textvariable=self.rf_addr, state='normal', width=38), fill=True)
    note('Leave the 96270A address empty to use other standards for every test.')
    btns = sh.drawer_footer
    self.btn_find = ttk.Button(btns, text='Find instruments', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
    self.btn_test = ttk.Button(btns, text='Test connections', command=self.test_connections, style='Accent.TButton'); self.btn_test.pack(side='left')

    self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
    self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
    self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
    self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
    sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
    self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
    sh.add_action('Save progress', self.save, side='right', short='Save')
    self.pm_live_attach(sh)                                    # 'Edit procedure': the editor inside this window, usable during a run

    body = sh.content
    info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
    ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
    ttk.Label(info, text=SPEC['source']['note'], style='Small.TLabel', wraplength=1000, justify='left').pack(anchor='w', pady=(4, 0))
    filt = ttk.Frame(body); filt.pack(side='top', fill='x', pady=(0, 6))
    ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
    c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS, width=14, state='readonly'); c2.pack(side='right')
    ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
    c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
    self.tree = ui_shell.results_table(self, body)
    ui_shell.small_window(self, self.tree, filt)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    self.update_shell_sections(POINTS, lambda p: p['section_title'])
    ui.polish(root)


def sync_buttons(self):
    idle = 'disabled' if self._busy else 'normal'
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        b.configure(state=idle)
    self.btn_stop.configure(state='normal' if self._busy else 'disabled')
    for c in (self.period_combo, self.set_combo, self.tb_combo, self.ch3_combo, self.pulse_check, self.rear_check, self.stim_combo, self.ref_combo, self.loss_entry, self.low_check):
        c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) and c is not self.loss_entry else 'normal'))


# ---- results table and address boxes
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    """rows: iterable of (iid, values, tags); keep: the selection before the refresh (the first row of it is selected again if it is still there)."""
    self.tree.delete(*self.tree.get_children())
    for iid, values, tags in rows:
        self.tree.insert('', 'end', iid=iid, values=values, tags=tags)
    if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices(self, which, values):
    """The drop-down values of the counter address ('ctr') or 96270A address ('rf') box."""
    (self.ctr_entry if which == 'ctr' else self.rf_entry).configure(values=values)
