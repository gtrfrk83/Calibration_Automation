"""Fluke 8808A guided adjustment: the Tk window code (layout, button / pill states, point and audit tables, window chrome).

Moved out of Procedures/Fluke_8808A_Adjustment.py unchanged (the bodies are the launcher's former `_build_ui` / `_toggle_log` and the widget statements of its
`on_cal_model` / `_sync` / `_fill_table` / `_audit_row`; only the small table / state helpers are new, each the exact statements the launcher used to make).  The launcher reaches
this module through `ui_port.ui.view('fluke8808a_adjust_view')`, which resolves to `fluke8808a_adjust_view_tk` under Tk; a Qt port provides `fluke8808a_adjust_view_qt` with the
same functions.  Every function takes the launcher's App as `self` and keeps its widgets as attributes of it.  Nothing here decides anything about a calibration.
"""
import sys
import tkinter as tk
from tkinter import ttk

import fluke8808a_adjustment as adj
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
    banner = ui.Banner(root, E.TITLE, 'RS-232 calibration dialog, Calibration Manual (Oct 2008) pp. 3-16 / 3-17, Table 3-9  |  RS-232 only')
    banner.pack(fill='x')
    if self.demo:
        banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
    self.pill_meter = banner.add_pill('8808A: not connected', 'neutral')
    self.pill_run = banner.add_pill('No adjustment record', 'neutral')
    self.pill_cal = banner.add_pill('Calibration mode: closed', 'good')
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

    link = ttk.LabelFrame(top, text='2  Connect: the 8808A and the calibrator', padding=10)
    link.grid(row=0, column=1, sticky='nsew')
    ttk.Label(link, text='8808A COM port').grid(row=0, column=0, sticky='w')
    ttk.Entry(link, textvariable=self.dmm_addr, width=14).grid(row=0, column=1, padx=(6, 12), sticky='w')
    ttk.Label(link, text='Baud', style='Muted.TLabel').grid(row=0, column=2, sticky='w')
    ttk.Combobox(link, textvariable=self.dmm_baud, values=adj.BAUDS, width=7, state='readonly').grid(row=0, column=3, padx=(6, 12), sticky='w')
    ttk.Label(link, text='Format', style='Muted.TLabel').grid(row=0, column=4, sticky='w')
    ttk.Combobox(link, textvariable=self.dmm_fmt, values=list(adj.PARITY_FORMATS), width=24, state='readonly').grid(row=0, column=5, padx=(6, 0), sticky='w')
    ttk.Label(link, text='Calibrator').grid(row=1, column=0, sticky='w', pady=(6, 0))
    cm = ttk.Combobox(link, textvariable=self.cal_model, values=list(adj.CALIBRATORS), width=14, state='readonly')
    cm.grid(row=1, column=1, padx=(6, 12), pady=(6, 0), sticky='w')
    cm.bind('<<ComboboxSelected>>', lambda _e: self.on_cal_model())
    self.cal_combo = cm
    ttk.Label(link, text='Interface').grid(row=1, column=2, sticky='w', pady=(6, 0))
    ci = ttk.Combobox(link, textvariable=self.cal_interface, values=list(adj.CAL_INTERFACES), width=8, state='readonly')
    ci.grid(row=1, column=3, padx=(6, 12), pady=(6, 0), sticky='w')
    ci.bind('<<ComboboxSelected>>', lambda _e: self.cal_addr.set(adj.CAL_PORT_DEFAULT[self.cal_interface.get()]))
    ttk.Label(link, text='Address / port', style='Muted.TLabel').grid(row=1, column=4, sticky='w', pady=(6, 0))
    ttk.Entry(link, textvariable=self.cal_addr, width=18).grid(row=1, column=5, padx=(6, 12), pady=(6, 0), sticky='w')
    ttk.Label(link, text='Baud', style='Muted.TLabel').grid(row=1, column=6, sticky='w', pady=(6, 0))
    ttk.Combobox(link, textvariable=self.cal_baud, values=['9600', '19200', '38400', '4800', '2400'], width=7, state='readonly').grid(row=1, column=7, padx=(6, 0), pady=(6, 0), sticky='w')
    ttk.Label(link, textvariable=self.cal_note, style='Muted.TLabel', wraplength=ui.px(900), justify='left').grid(row=2, column=0, columnspan=8, sticky='w', pady=(6, 0))

    ttk.Checkbutton(link, text='Also send *TER once (UNVERIFIED, off by default: calibration mode is entered at the front panel)', variable=self.use_ter).grid(row=3, column=0, columnspan=8, sticky='w', pady=(4, 0))

    hintrow = ttk.Frame(body)
    hintrow.pack(fill='x', pady=(10, 4))
    ttk.Label(hintrow, text='NEXT', style='MetricCap.TLabel').pack(side='left')
    ttk.Label(hintrow, textvariable=self.next_hint, style='Bold.TLabel', wraplength=ui.px(1100), justify='left').pack(side='left', padx=(12, 0), fill='x', expand=True)

    bar = ttk.Frame(body)
    bar.pack(side='bottom', fill='x', pady=(8, 0))
    self.btn_connect = ttk.Button(bar, text='Connect', command=self.connect)
    self.btn_start = ttk.Button(bar, text='Start adjustment record', command=self.start_record)
    self.btn_enter = ttk.Button(bar, text='Calibration mode entered', command=self.enter_calibration)
    self.btn_run = ttk.Button(bar, text='Run next point', style='Accent.TButton', command=self.run_next)
    self.btn_finish = ttk.Button(bar, text='Finish (EXIT)', command=self.finish)
    self.btn_abort = ttk.Button(bar, text='Abort', style='Danger.TButton', command=self.abort)
    self.btn_close = ttk.Button(bar, text='Disconnect', command=self.disconnect)
    for b_ in (self.btn_connect, self.btn_start, self.btn_enter, self.btn_run, self.btn_finish):
        b_.pack(side='left', padx=(0, 8))
    self.btn_close.pack(side='right')
    self.btn_abort.pack(side='right', padx=(0, 8))
    self.show_log = tk.BooleanVar(value=True)
    ttk.Checkbutton(bar, text='Show audit log', variable=self.show_log, command=self._toggle_log).pack(side='right', padx=(0, 16))
    self._bar = bar

    self.log_box = ttk.LabelFrame(body, text='Audit log (this record; no password exists or is written)', padding=6)
    self.log_table = ui.make_table(self.log_box, ('time', 'step', 'action', 'outcome', 'detail'), ('Time', 'Step', 'Action', 'Outcome', 'Detail'),
                                   (140, 50, 110, 110, 720), anchors={'detail': 'w', 'action': 'w', 'time': 'w', 'step': 'w'}, height=6,
                                   stretch={'time': False, 'step': False, 'action': False, 'outcome': False})
    self.log_table.tag_configure('ok', foreground=ui.C['good'])
    self.log_table.tag_configure('bad', foreground=ui.C['bad'])
    self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
    self.tree = ui.make_table(body, ('id', 'fn', 'step', 'output', 'state'), ('ID', 'Function', 'Point (Table 3-9)', 'Calibrator output', 'Status'),
                              (60, 80, 260, 360, 160), anchors={'step': 'w', 'output': 'w', 'id': 'w', 'fn': 'w'}, height=12, stretch={'id': False, 'fn': False, 'state': False})
    self.tree.tag_configure('done', background=ui.C['good_bg'], foreground=ui.C['good'])
    self.tree.tag_configure('next', background=ui.C['info_bg'])
    self.tree.tag_configure('failed', background=ui.C['bad_bg'], foreground=ui.C['bad'])
    ui.polish(root)


def toggle_log(self):
    if self.show_log.get():
        self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
    else:
        self.log_box.pack_forget()


def cal_tooltip(self, text):
    """The tooltip of the calibrator picker (a statement of the launcher's former on_cal_model)."""
    ui.Tooltip(self.cal_combo, text)


def sync_pills(self, live, open_):
    """The three status pills (the statements of the launcher's former _sync)."""
    self.pill_meter.set(('8808A: DEMO (simulated)' if self.demo else '8808A: connected') if live else '8808A: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
    rid = self.audit.run_id
    self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No adjustment record', 'info' if rid else 'neutral')
    self.pill_cal.set('Calibration mode: OPEN' if open_ else 'Calibration mode: closed', 'bad' if open_ else 'good')


def sync_buttons(self, connect, start, enter, run, finish, abort, close, scope_locked):
    """Button states (the `en(...)` statements of the launcher's former _sync; `connect` ... `close` already include 'not busy', `abort` does not)."""
    def en(btn, cond):
        btn.configure(state='normal' if cond else 'disabled')
    en(self.btn_connect, connect)
    en(self.btn_start, start)
    en(self.btn_enter, enter)
    en(self.btn_run, run)
    en(self.btn_finish, finish)
    self.btn_abort.configure(state='normal' if abort else 'disabled')
    en(self.btn_close, close)
    self.scope_combo.configure(state='disabled' if scope_locked else 'readonly')


def table_clear(self):
    self.tree.delete(*self.tree.get_children())


def table_add(self, iid, values, tags):
    self.tree.insert('', 'end', iid=iid, values=values, tags=tags)


def log_add(self, values, tags):
    self.log_table.insert('', 0, values=values, tags=tags)


def log_clear(self):
    self.log_table.delete(*self.log_table.get_children())
