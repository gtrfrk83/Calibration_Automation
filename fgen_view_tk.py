"""Function-generator performance verification (33220A / 33250A / 33210A): the Tk window code (layout, button states, results table, window chrome).

Moved out of fgen_verification.py unchanged (the bodies are the engine's former `__init__` window statements, `_build_ui` and the button-state code; only the table and address-box
helpers below are new, each the exact statements the engine used to make on `self.tree` / the address boxes).  The engine reaches this module through
`ui_port.ui.view('fgen_view')`, which resolves to `fgen_view_tk` under Tk; a Qt port provides `fgen_view_qt` with the same functions.  Every function takes the engine's App
as `self` and keeps its widgets as attributes of it (`self.tree`, `self.btn_run`, ... the shared mixins use them too).  Nothing here decides anything about a calibration.
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
    import fgen_verification as E
    root, demo = self.root, self.demo
    MODEL, SPEC, POINTS, PERIODS, STD_INPUTS, COUNTER_REFS, FLAT_METHODS = E.MODEL, E.SPEC, E.POINTS, E.PERIODS, E.STD_INPUTS, E.COUNTER_REFS, E.FLAT_METHODS
    ui.apply_theme(root)
    root.title(f'{SPEC["manufacturer"]} {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1320, 840, min_w=900, min_h=640)


def finish_window(self):
    """Attach the asset-history helpers to the window (the last window statement of the engine's former App.__init__)."""
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def build_ui(self):
    import fgen_verification as E                      # the engine's module state (configure(model) rebinds MODEL / POINTS / SPEC), read at call time
    MODEL, SPEC, POINTS, PERIODS, STD_INPUTS, COUNTER_REFS, FLAT_METHODS = E.MODEL, E.SPEC, E.POINTS, E.PERIODS, E.STD_INPUTS, E.COUNTER_REFS, E.FLAT_METHODS
    root = self.root
    src = SPEC['source']
    sh = self.shell = ui_shell.Shell(root, f'{SPEC["manufacturer"]} {MODEL}  -  Performance Verification',
                                     f'Test points from the {MODEL} Service Guide, {src["chapter"]}, pp. {src["pages"]}  |  {len(POINTS)} points in the spec',
                                     demo=self.demo, on_section=self.pick_section, version='spec v4', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice('The program switches the generator output OFF after every point and asks you to confirm the wiring before every new setup. '
                    'Power-meter flatness: the +20 dB range needs the -20 dB attenuator in front of the sensor.', 'info')

    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
    self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
    self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
    self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
    ttk.Label(d, text='Test set').grid(row=1, column=0, sticky='w', pady=4)
    self.set_combo = ttk.Combobox(d, textvariable=self.test_set, values=['Full verification', 'Quick check (Q points only)'], width=26, state='readonly')
    self.set_combo.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=4); self.set_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
    ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 10))
    self.entries = {}
    rows = (('uut', f'{MODEL} (under test)'), ('std', 'Fluke 5790B'), ('counter', 'Frequency counter'), ('power', 'Power meter'))
    r = 3
    for key, label in rows:
        ttk.Label(d, text=label).grid(row=r, column=0, sticky='w', pady=4)
        cb = ttk.Combobox(d, textvariable=self.addr[key], state='normal', width=34); cb.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4)
        self.entries[key] = cb; r += 1
    ttk.Label(d, text='5790B input').grid(row=r, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.std_input, values=list(STD_INPUTS), width=22, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    ttk.Label(d, text='5790B baud').grid(row=r, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.addr['std_baud'], values=['9600', '19200', '38400', '57600', '115200'], width=9, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
    ttk.Label(d, text='Timebase').grid(row=r, column=0, sticky='w', pady=4)
    self.ref_combo = ttk.Combobox(d, textvariable=self.counter_ref, values=list(COUNTER_REFS), width=24, state='readonly')
    self.ref_combo.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4)
    self.ref_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_counter_ref()); r += 1
    if len(SPEC.get('flatness_methods', ['POWER'])) > 1:
        ttk.Label(d, text='Flatness with').grid(row=r, column=0, sticky='w', pady=4)
        self.method_combo = ttk.Combobox(d, textvariable=self.flat_method, values=[FLAT_METHODS[m] for m in SPEC['flatness_methods']], width=36, state='readonly')
        self.method_combo.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4)
        self.method_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_method()); r += 1
    ttk.Label(d, text='Leave the counter or power meter blank to type its readings. Examples: USB0::0x0957::0x0407::<serial>::INSTR   '
                      'GPIB0::10::INSTR   TCPIP0::192.168.1.20::INSTR   COM9', style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(10, 0))
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
    self.pm_live_attach(sh)                                    # 'Edit point': the point editor for the selected row, usable during a run; right-click > Edit as well, usable during a run

    body = sh.content
    info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
    ttk.Label(info, textvariable=self.detail, wraplength=1100, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
    ttk.Label(info, text=src['note'], style='Small.TLabel', wraplength=1100, justify='left').pack(anchor='w', pady=(4, 0))
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
    for c in (self.period_combo, self.set_combo, self.ref_combo) + ((self.method_combo,) if hasattr(self, 'method_combo') else ()):
        c.configure(state='disabled' if self._busy else 'readonly')



# ---- results table and address boxes: the exact statements the engine used to make on self.tree / the address boxes
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


def set_choices(self, values):
    """The drop-down values of every instrument address box."""
    for cb in self.entries.values(): cb['values'] = values
