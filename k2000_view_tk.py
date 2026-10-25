"""Keithley Model 2000 performance verification: the Tk window code (layout, button states, results table, window chrome).

Moved out of keithley2000_verification.py unchanged (the bodies are the engine's former `_build_ui` / `_sync_buttons`; only the table and entry helpers below are new, each the
exact statements the engine used to make on `self.tree` / `self.dmm_entry` / `self.cal_entry`).  The engine reaches this module through `ui_port.ui.view('k2000_view')`, which
resolves to `k2000_view_tk` under Tk; a Qt port provides `k2000_view_qt` with the same functions.  Every function takes the engine's App as `self` and keeps its widgets as
attributes of it (`self.tree`, `self.btn_run`, ... the shared mixins use them too).  Nothing here decides anything about a calibration.
"""
import tkinter as tk
from tkinter import ttk

import calibrator_fit
import datamode
import ui_shell
import ui_theme as ui
import virtualbench


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title('Keithley 2000 | Performance Verification' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1320, 820, min_w=900, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last statements of the engine's former App.__init__)."""
    import labregistry
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def sync_buttons(self):
    idle = 'disabled' if self._busy else 'normal'
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        b.configure(state=idle)
    self.btn_stop.configure(state='normal' if self._busy else 'disabled')
    self.period_combo.configure(state='disabled' if self._busy else 'readonly')


def build_ui(self):
    import keithley2000_verification as E                      # the engine's module state (configure(model) can rebind it), read at call time
    CAL_INTERFACES, FLOW, INTERFACES, PERIODS, POINTS, SPEC, drivers = E.CAL_INTERFACES, E.FLOW, E.INTERFACES, E.PERIODS, E.POINTS, E.SPEC, E.drivers
    root = self.root
    sh = self.shell = ui_shell.Shell(root, 'Keithley 2000  -  Performance Verification',
                                     f'Test points from the Model 2000 Calibration Manual, Tables 1-2 to 1-6 (pp. 1-7 to 1-13)  |  {len(POINTS)} points in the spec  |  '
                                     'GPIB or RS-232', demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program asks you to confirm the warm-up and environment, the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.', 'info')

    # settings and connections live in the slide-in drawer
    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
    self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
    self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
    self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
    ttk.Separator(d).grid(row=1, column=0, columnspan=2, sticky='ew', pady=(2, 10))
    r = 2
    ttk.Label(d, text='2000 interface').grid(row=r, column=0, sticky='w', pady=4)
    iface = ttk.Combobox(d, textvariable=self.interface, values=list(INTERFACES), width=10, state='readonly')
    iface.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    ttk.Label(d, text='2000 address / port').grid(row=r, column=0, sticky='w', pady=4)
    self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, state='normal', width=34)
    self.dmm_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
    for text, var, values, width in (('RS-232 baud', self.dmm_baud, ['19200', '9600', '4800', '2400', '1200', '600', '300'], 9),
                                     ('RS-232 TX TERM', self.dmm_term, list(drivers.keithley_2000.TX_TERM), 9),
                                     ('RS-232 flow control', self.dmm_flow, list(FLOW), 12)):
        ttk.Label(d, text=text).grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=var, values=values, width=width, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    ttk.Label(d, text='GPIB: the 2000 factory address is 16 (CONFIG > GPIB). RS-232: set the same baud and TX TERM on the meter (CONFIG > RS-232) and the SCPI '
                      'language (the RS-232 interface supports SCPI only). 8 data bits, no parity, 1 stop bit.',
              style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(2, 8)); r += 1
    ttk.Label(d, text='Calibrator').grid(row=r, column=0, sticky='w', pady=4)
    calbox = ttk.Combobox(d, textvariable=self.cal_model, values=self.cal_choices(), width=14, state='readonly')
    calbox.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    calibrator_fit.attach_note(d, self.cal_offer, ui, widgets=(calbox,), row=r); r += 1
    ttk.Label(d, text='Calibrator interface').grid(row=r, column=0, sticky='w', pady=4)
    ci = ttk.Combobox(d, textvariable=self.cal_interface, values=list(CAL_INTERFACES), width=10, state='readonly')
    ci.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    ci.bind('<<ComboboxSelected>>', lambda _e: self.on_cal_interface())
    ttk.Label(d, text='Calibrator port / address').grid(row=r, column=0, sticky='w', pady=4)
    self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
    self.cal_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
    ttk.Label(d, text='Calibrator baud (RS-232 only)').grid(row=r, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
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


# ---- results table and address boxes: the exact statements the engine used to make on self.tree / self.dmm_entry / self.cal_entry
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
    """The drop-down values of the DMM address ('dmm') or calibrator port ('cal') box."""
    (self.dmm_entry if which == 'dmm' else self.cal_entry)['values'] = values
