"""Tektronix TBS2000B performance verification: the Tk window code (the twin of tds2000c_view_tk.py with the TBS2000B titles, model list and address label).

The engine (tbs2000b_verification.py) reaches it through `ui_port.ui.view('tbs2000b_view')`; the Qt twin is tbs2000b_view_qt.py.  Same functions, arguments and App
attributes as the TDS2000C view; the results-table and address-box helpers are the TDS2000C view's own functions (imported, not copied).  Nothing here decides
anything about a calibration.
"""
import tkinter as tk  # noqa: F401
from tkinter import ttk  # noqa: F401

import datamode  # noqa: F401
import labregistry
import ui_shell
import ui_theme as ui
import virtualbench  # noqa: F401


def setup_window(self):
    """Theme, title and size of the main window (statements of the engine's former App.__init__)."""
    import tbs2000b_verification as E
    root, demo = self.root, self.demo
    CAL_CHOICES, MODELS, POINTS, SPEC = E.CAL_CHOICES, E.MODELS, E.POINTS, E.SPEC
    ui.apply_theme(root)
    root.title('Tektronix TBS2000B | Performance Verification' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1380, 880, min_w=900, min_h=680)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last window statement of the engine's former App.__init__)."""
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def build_ui(self):
    import tbs2000b_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    CAL_CHOICES, MODELS, POINTS, SPEC = E.CAL_CHOICES, E.MODELS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = ui_shell.Shell(root, 'Tektronix TBS2000B  -  Performance Verification',
                                     f'{SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                                     demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program stops and asks you to confirm every cable, terminator and splitter change before the next point. '
                    'Stay at the bench; the calibrator is returned to STANDBY after every point.', 'info')

    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
    m = ttk.Combobox(d, textvariable=self.v_model, values=['TBS' + x for x in MODELS], width=14, state='readonly'); m.grid(row=0, column=1, padx=(10, 0), pady=4, sticky='w')
    m.set('TBS' + self.v_model.get().replace('TBS', ''))
    self.btn_read_model = ttk.Button(d, text='Read model from scope', command=self.read_model); self.btn_read_model.grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))
    self.cfg_widgets = [m]
    m.bind('<<ComboboxSelected>>', lambda _e: self.on_config())
    ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    self.addr_boxes = {}
    for i, (key, label) in enumerate([('scope', 'TBS2000B (USB)'), ('cal', 'Calibrator (COM or GPIB)')]):
        ttk.Label(d, text=label).grid(row=3 + i, column=0, sticky='w', pady=4)
        cb = ttk.Combobox(d, textvariable=self.addr[key], state='normal', width=34); cb.grid(row=3 + i, column=1, sticky='ew', padx=(10, 0), pady=4)
        self.addr_boxes[key] = cb
    ttk.Label(d, text='Calibrator').grid(row=5, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.addr['cal_model'], values=CAL_CHOICES, width=14, state='readonly').grid(row=5, column=1, sticky='w', padx=(10, 0), pady=4)
    ttk.Label(d, text='Calibrator baud').grid(row=6, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.addr['cal_baud'], values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=6, column=1, sticky='w', padx=(10, 0), pady=4)
    ttk.Label(d, text='The oscilloscope is connected by USB. All outputs (DC volts, leveled sine, time marker) come from the calibrator scope option.',
              style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=7, column=0, columnspan=2, sticky='w', pady=(8, 0))
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

    body = sh.content
    info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
    ttk.Label(info, textvariable=self.detail, wraplength=1100, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
    filt = ttk.Frame(body); filt.pack(side='top', fill='x', pady=(0, 6))
    ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
    c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS + ['Skipped'], width=14, state='readonly'); c2.pack(side='right')
    ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
    c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
    self.tree = ui_shell.results_table(self, body)
    ui_shell.small_window(self, self.tree, filt)
    self.tree.bind('<<TreeviewSelect>>', self.on_select)
    ui.polish(root)


def sync_buttons(self):
    idle = 'disabled' if self._busy else 'normal'
    for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
        b.configure(state=idle)
    self.btn_stop.configure(state='normal' if self._busy else 'disabled')
    for c in self.cfg_widgets:
        c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) else 'normal'))



# ---- results table and address boxes: the TDS2000C view's own statements
from tds2000c_view_tk import table_has, table_select, table_selection, table_set_rows, table_update_row  # noqa: E402,F401
