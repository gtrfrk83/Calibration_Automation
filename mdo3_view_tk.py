"""Tektronix 3 Series MDO (MDO32 / MDO34) performance verification: the Tk window code, the twin of mdo3_view_qt.py.

The MDO4000C Tk view (mdo4000c_view_tk.py) with the 3 Series model list, option names and texts (its table / address-box helpers repeated here, so this
procedure's fingerprint does not include the MDO4000C window).  Kept for the Tk toolkit and for the headless harnesses, which resolve '<view>_tk'.  Nothing here decides anything about a
calibration.
"""
import tkinter as tk  # noqa: F401
from tkinter import ttk  # noqa: F401

import datamode  # noqa: F401
import labregistry
import ui_shell
import ui_theme as ui
import virtualbench  # noqa: F401

# the same texts as mdo3_view_qt.py (kept twice: each twin imports only its own toolkit)
TITLE = 'Tektronix 3 Series MDO'
ADDRESS_ROWS = [('scope', '3 Series MDO (USB)'), ('cal', 'Fluke 5560A'), ('rf1', 'Fluke 96270A (RF)'),     # no second RF source: the 3 Series has no IMD test
                ('gen', 'Agilent 33220A / 33250A'), ('dmm', 'Reference DMM (AFG)'), ('counter', 'Counter (AFG freq)'), ('power', 'Power meter (optional)')]
NOTICE = ('The program stops and asks you to confirm every cable, terminator, instrument or front-panel change before the next point. '
          'Stay at the bench: high-voltage DC points (to 100 V) and RF outputs are enabled only after you confirm.')
MODEL_NOTE = ('Model = MDO32 / MDO34 and its bandwidth (3-BW option, MHz). The 1 GHz spectrum analyzer is standard; choose SA3 when 3-SA3 is installed. '
              'Leave an address blank if that instrument is not used. Without a reference DMM / counter the AFG readings are typed in.')


def setup_window(self):
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title(f'{TITLE} | Performance Verification' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1380, 880, min_w=900, min_h=680)


def finish_window(self):
    labregistry.attach(self.root, self.asset, self.serial, self.status.set)


def build_ui(self):
    import mdo3_verification as E
    MODELS, POINTS, SPEC = E.MODELS, E.POINTS, E.SPEC
    root = self.root
    sh = self.shell = ui_shell.Shell(root, f'{TITLE}  -  Performance Verification',
                                     f'MDO32 / MDO34, 100 MHz - 1 GHz  |  {SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                                     demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
    self.status = sh.status_var
    self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
    sh.build_identity(self.asset, self.serial)
    self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
    self.summary = sh.build_progress()
    if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
    else: sh.notice(NOTICE, 'info')

    d = sh.drawer_body; d.columnconfigure(1, weight=1)
    ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
    m = ttk.Combobox(d, textvariable=self.v_model, values=['MDO' + x for x in MODELS], width=12, state='readonly'); m.grid(row=0, column=1, padx=(10, 0), pady=4, sticky='w')
    m.set('MDO' + self.v_model.get().replace('MDO', ''))
    ttk.Label(d, text='Spectrum analyzer').grid(row=1, column=0, sticky='w', pady=4)
    sa = ttk.Combobox(d, textvariable=self.v_sa, values=['None', 'SA3'], width=10, state='readonly'); sa.grid(row=1, column=1, padx=(10, 0), pady=4, sticky='w')
    checks = [ttk.Checkbutton(d, text='AFG (3-AFG)', variable=self.v_afg, command=self.on_config),
              ttk.Checkbutton(d, text='DVM (3-DVM)', variable=self.v_dvm, command=self.on_config),
              ttk.Checkbutton(d, text='TPA-N-PRE attached', variable=self.v_tpa, command=self.on_config)]
    for i, c in enumerate(checks): c.grid(row=2 + i, column=0, columnspan=2, sticky='w', pady=1)
    self.btn_read_opts = ttk.Button(d, text='Read options from scope', command=self.read_options); self.btn_read_opts.grid(row=5, column=0, columnspan=2, sticky='w', pady=(8, 0))
    self.cfg_widgets = [m, sa] + checks
    for w in (m, sa): w.bind('<<ComboboxSelected>>', lambda _e: self.on_config())
    ttk.Separator(d).grid(row=7, column=0, columnspan=2, sticky='ew', pady=(12, 10))
    self.addr_boxes = {}
    for i, (key, label) in enumerate(ADDRESS_ROWS):
        ttk.Label(d, text=label).grid(row=8 + i, column=0, sticky='w', pady=4)
        cb = ttk.Combobox(d, textvariable=self.addr[key], state='normal', width=34); cb.grid(row=8 + i, column=1, sticky='ew', padx=(10, 0), pady=4)
        self.addr_boxes[key] = cb
    row = 8 + len(ADDRESS_ROWS)
    ttk.Label(d, text='5560A baud').grid(row=row, column=0, sticky='w', pady=4)
    ttk.Combobox(d, textvariable=self.addr['cal_baud'], values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
    ttk.Label(d, text=MODEL_NOTE, style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=row + 1, column=0, columnspan=2, sticky='w', pady=(8, 0))
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
    self.pm_live_attach(sh)

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


# ---- results table and address boxes (the same statements as mdo4000c_view_tk.py)
def table_selection(self):
    return self.tree.selection()


def table_has(self, iid):
    return self.tree.exists(iid)


def table_select(self, iid, see=False):
    self.tree.selection_set(iid)
    if see:
        self.tree.see(iid)


def table_set_rows(self, rows, keep):
    self.tree.delete(*self.tree.get_children())
    for iid, values, tags in rows:
        self.tree.insert('', 'end', iid=iid, values=values, tags=tags)
    if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])


def table_update_row(self, iid, values, tags):
    self.tree.item(iid, values=values, tags=tags)


def set_choices(self, values):
    for cb in self.addr_boxes.values(): cb['values'] = values
