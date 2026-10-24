"""Keithley Model 2000 guided adjustment: the Tk window code (layout, button / pill states, step and audit tables, window chrome).

Moved out of Procedures/Keithley_2000_Adjustment.py unchanged (the bodies are the launcher's former `_build_ui` / `_toggle_log` and the widget statements of its
`_sync` / `_fill_table` / `_audit_row`; only the small table / state helpers are new, each the exact statements the launcher used to make).  The launcher reaches this module
through `ui_port.ui.view('keithley2000_adjust_view')`, which resolves to `keithley2000_adjust_view_tk` under Tk; a Qt port provides `keithley2000_adjust_view_qt` with the same
functions.  Every function takes the launcher's App as `self` and keeps its widgets as attributes of it.  Nothing here decides anything about a calibration.
"""
import sys
import tkinter as tk
from tkinter import ttk

import drivers
import keithley2000_adjustment as adj
import ui_theme as ui


def _eng(self):
    """The launcher's own module (it may be __main__ when run as a script): TITLE / NOTICE live there."""
    return sys.modules[type(self).__module__]


def setup_window(self):
    """Theme, title and size of the main window (the statements of the launcher's former App.__init__)."""
    E = _eng(self)
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title(E.TITLE.replace('  -  ', ' | ') + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1320, 900, min_w=1000, min_h=680)


def build_ui(self):
    E = _eng(self)
    root = self.root
    banner = ui.Banner(root, E.TITLE, 'Remote :CAL:PROT command calibration, Calibration Manual 2000-905-01 Rev. F, pp. 2-14 to 2-19  |  GPIB or RS-232')
    banner.pack(fill='x')
    if self.demo:
        banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
    self.pill_meter = banner.add_pill('2000: not connected', 'neutral')
    self.pill_run = banner.add_pill('No adjustment record', 'neutral')
    self.pill_lock = banner.add_pill('Calibration LOCKED', 'good')
    ui.StatusBar(root, self.status, right='spec v1').pack(side='bottom', fill='x')
    body = ttk.Frame(root, padding=(18, 12, 18, 8))
    body.pack(fill='both', expand=True)
    ui.Notice(body, E.NOTICE, 'bad', title='This changes the instrument calibration').pack(fill='x')

    top = ttk.Frame(body)
    top.pack(fill='x', pady=(10, 0))
    top.columnconfigure(1, weight=1)
    who = ttk.LabelFrame(top, text='1  Who and what', padding=10)
    who.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
    for r_, (label, var) in enumerate((('Instrument ID *', self.asset), ('Serial number *', self.serial), ('Technician *', self.tech))):
        ttk.Label(who, text=label).grid(row=r_, column=0, sticky='w', pady=2)
        ttk.Entry(who, textvariable=var, width=20).grid(row=r_, column=1, padx=(8, 0), pady=2)
    ttk.Label(who, text='Scope').grid(row=3, column=0, sticky='w', pady=2)
    self.scope_combo = ttk.Combobox(who, textvariable=self.scope, values=list(adj.SCOPES), state='readonly', width=34)
    self.scope_combo.grid(row=3, column=1, padx=(8, 0), pady=2)
    self.scope_combo.bind('<<ComboboxSelected>>', lambda _e: (self._fill_table(), self._sync()))

    link = ttk.LabelFrame(top, text='2  Connect: the 2000 and the calibrator', padding=10)
    link.grid(row=0, column=1, sticky='nsew')
    ttk.Label(link, text='2000 interface').grid(row=0, column=0, sticky='w')
    ttk.Combobox(link, textvariable=self.interface, values=list(adj.INTERFACES), width=8, state='readonly').grid(row=0, column=1, padx=(6, 12), sticky='w')
    ttk.Label(link, text='GPIB address / COM port').grid(row=0, column=2, sticky='w')
    ttk.Entry(link, textvariable=self.dmm_addr, width=20).grid(row=0, column=3, padx=(6, 12), sticky='w')
    for c_, (text, var, values, w_) in enumerate((('RS-232 baud', self.dmm_baud, ['19200', '9600', '4800', '2400', '1200', '600', '300'], 7),
                                                  ('TX TERM', self.dmm_term, list(drivers.keithley_2000.TX_TERM), 6), ('Flow control', self.dmm_flow, list(adj.FLOW), 10))):
        ttk.Label(link, text=text, style='Muted.TLabel').grid(row=1, column=c_ * 2, sticky='w', pady=(6, 0))
        ttk.Combobox(link, textvariable=var, values=values, width=w_, state='readonly').grid(row=1, column=c_ * 2 + 1, padx=(6, 12), pady=(6, 0), sticky='w')
    ttk.Label(link, text='Calibrator').grid(row=2, column=0, sticky='w', pady=(6, 0))
    cm = ttk.Combobox(link, textvariable=self.cal_model, values=self.cal_choices(), width=14, state='readonly')
    cm.grid(row=2, column=1, padx=(6, 12), pady=(6, 0), sticky='w')
    ui.Tooltip(cm, self.cal_offer.tooltip)
    cm.bind('<<ComboboxSelected>>', lambda _e: self.on_cal_model())
    ttk.Label(link, text='Interface').grid(row=2, column=2, sticky='w', pady=(6, 0))
    ci = ttk.Combobox(link, textvariable=self.cal_interface, values=list(adj.CAL_INTERFACES), width=8, state='readonly')
    ci.grid(row=2, column=3, padx=(6, 12), pady=(6, 0), sticky='w')
    ci.bind('<<ComboboxSelected>>', lambda _e: self.cal_addr.set(adj.CAL_PORT_DEFAULT[self.cal_interface.get()]))
    ttk.Label(link, text='Address / port', style='Muted.TLabel').grid(row=2, column=4, sticky='w', pady=(6, 0))
    ttk.Entry(link, textvariable=self.cal_addr, width=18).grid(row=2, column=5, padx=(6, 12), pady=(6, 0), sticky='w')
    ttk.Label(link, text='Baud', style='Muted.TLabel').grid(row=2, column=6, sticky='w', pady=(6, 0))
    ttk.Combobox(link, textvariable=self.cal_baud, values=['9600', '19200', '38400', '4800', '2400'], width=7, state='readonly').grid(row=2, column=7, padx=(6, 0), pady=(6, 0), sticky='w')
    ttk.Label(link, textvariable=self.cal_note, style='Muted.TLabel', wraplength=ui.px(760), justify='left').grid(row=3, column=0, columnspan=8, sticky='w', pady=(6, 0))

    hintrow = ttk.Frame(body)
    hintrow.pack(fill='x', pady=(10, 4))
    ttk.Label(hintrow, text='NEXT', style='MetricCap.TLabel').pack(side='left')
    ttk.Label(hintrow, textvariable=self.next_hint, style='Bold.TLabel', wraplength=ui.px(1100), justify='left').pack(side='left', padx=(12, 0), fill='x', expand=True)

    bar = ttk.Frame(body)
    bar.pack(side='bottom', fill='x', pady=(8, 0))
    self.btn_connect = ttk.Button(bar, text='Connect', command=self.connect)
    self.btn_start = ttk.Button(bar, text='Start adjustment record', command=self.start_record)
    self.btn_unlock = ttk.Button(bar, text='Unlock calibration', command=self.unlock)
    self.btn_run = ttk.Button(bar, text='Run next step', style='Accent.TButton', command=self.run_next)
    self.btn_save = ttk.Button(bar, text='Dates and SAVE', command=self.dates_and_save)
    self.btn_abort = ttk.Button(bar, text='Abort and lock', style='Danger.TButton', command=self.abort)
    self.btn_close = ttk.Button(bar, text='Lock and disconnect', command=self.disconnect)
    for b_ in (self.btn_connect, self.btn_start, self.btn_unlock, self.btn_run, self.btn_save):
        b_.pack(side='left', padx=(0, 8))
    self.btn_close.pack(side='right')
    self.btn_abort.pack(side='right', padx=(0, 8))
    self.show_log = tk.BooleanVar(value=True)
    ttk.Checkbutton(bar, text='Show audit log', variable=self.show_log, command=self._toggle_log).pack(side='right', padx=(0, 16))
    self._bar = bar

    self.log_box = ttk.LabelFrame(body, text='Audit log (this record; no calibration code is ever written)', padding=6)
    self.log_table = ui.make_table(self.log_box, ('time', 'step', 'action', 'outcome', 'detail'), ('Time', 'Step', 'Action', 'Outcome', 'Detail'),
                                   (140, 50, 110, 110, 720), anchors={'detail': 'w', 'action': 'w', 'time': 'w', 'step': 'w'}, height=6,
                                   stretch={'time': False, 'step': False, 'action': False, 'outcome': False})
    self.log_table.tag_configure('ok', foreground=ui.C['good'])
    self.log_table.tag_configure('bad', foreground=ui.C['bad'])
    self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
    self.tree = ui.make_table(body, ('id', 'step', 'output', 'command', 'param', 'state'), ('ID', 'Step', 'Calibrator output', 'Command', 'Parameter', 'Status'),
                              (50, 230, 250, 230, 110, 150), anchors={'step': 'w', 'output': 'w', 'command': 'w', 'id': 'w', 'param': 'w'}, height=12,
                              stretch={'id': False, 'step': False, 'state': False})
    self.tree.tag_configure('done', background=ui.C['good_bg'], foreground=ui.C['good'])
    self.tree.tag_configure('next', background=ui.C['info_bg'])
    self.tree.tag_configure('failed', background=ui.C['bad_bg'], foreground=ui.C['bad'])
    ui.polish(root)


def toggle_log(self):
    if self.show_log.get():
        self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
    else:
        self.log_box.pack_forget()


def sync_pills(self, live, unlocked):
    """The three status pills (the first statements of the launcher's former _sync)."""
    self.pill_meter.set(('2000: DEMO (simulated)' if self.demo else '2000: connected') if live else '2000: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
    rid = self.audit.run_id
    self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No adjustment record', 'info' if rid else 'neutral')
    self.pill_lock.set('Calibration UNLOCKED' if unlocked else 'Calibration LOCKED', 'bad' if unlocked else 'good')


def sync_buttons(self, connect, start, unlock, run, save, abort, close, scope_locked):
    """Button states (the `en(...)` statements of the launcher's former _sync; `connect` ... `close` already include 'not busy', `abort` does not)."""
    def en(btn, cond):
        btn.configure(state='normal' if cond else 'disabled')
    en(self.btn_connect, connect)
    en(self.btn_start, start)
    en(self.btn_unlock, unlock)
    en(self.btn_run, run)
    en(self.btn_save, save)
    self.btn_abort.configure(state='normal' if abort else 'disabled')
    en(self.btn_close, close)
    for w in (self.scope_combo,):
        w.configure(state='disabled' if scope_locked else 'readonly')


def table_clear(self):
    self.tree.delete(*self.tree.get_children())


def table_add(self, iid, values, tags):
    self.tree.insert('', 'end', iid=iid, values=values, tags=tags)


def log_add(self, values, tags):
    self.log_table.insert('', 0, values=values, tags=tags)


def log_clear(self):
    self.log_table.delete(*self.log_table.get_children())
