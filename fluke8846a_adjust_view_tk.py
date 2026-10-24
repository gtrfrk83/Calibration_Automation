"""Fluke 8846A guided adjustment: the Tk window code (layout, button / pill states, step and audit tables, window chrome).

Moved out of Procedures/Fluke_8846A_Adjustment.py unchanged (the bodies are the launcher's former `_build_ui` / `_toggle_log` and the widget statements of its `_set_state` /
`_on_select` / `_sync` / `_audit_row` / `refresh_ports` / `selected`; only the small table / state helpers are new, each the exact statements the launcher used to make).  The
launcher reaches this module through `ui_port.ui.view('fluke8846a_adjust_view')`, which resolves to `fluke8846a_adjust_view_tk` under Tk; a Qt port provides
`fluke8846a_adjust_view_qt` with the same functions.  Every function takes the launcher's App as `self` and keeps its widgets as attributes of it.  Nothing here decides anything
about a calibration.
"""
import sys
import tkinter as tk
from tkinter import ttk

import ui_theme as ui


def _eng(self):
    """The launcher's own module (it may be __main__ when run as a script): STEPS lives there."""
    return sys.modules[type(self).__module__]


def setup_window(self):
    """Theme, title and size of the main window (the statements of the launcher's former App.__init__)."""
    root, demo = self.root, self.demo
    ui.apply_theme(root)
    root.title('Fluke 8846A | Guided Adjustment v57' + (' [DEMO]' if demo else ''))
    ui.fit_window(root, 1280, 860, min_w=1060, min_h=680)


def build_ui(self):
    E = _eng(self)
    root = self.root
    banner = ui.Banner(root, 'Fluke 8846A  -  Guided Adjustment',
                       'Changes calibration coefficients. Authorised technicians only. Every action is written to the audit log.')
    banner.pack(fill='x')
    if self.demo:
        banner.add_pill('DEMO MODE  -  commands simulated', 'warn')
    self.pill_meter = banner.add_pill('Meter: not connected', 'neutral')
    self.pill_run = banner.add_pill('No adjustment record', 'neutral')
    self.pill_lock = banner.add_pill('Calibration LOCKED', 'good')
    ui.StatusBar(root, self.status, right='v57').pack(side='bottom', fill='x')
    body = ttk.Frame(root, padding=(18, 14, 18, 10))
    body.pack(fill='both', expand=True)

    ui.Notice(body, 'Live adjustment can change calibration coefficients and CAL:REC writes them to non-volatile memory. '
                    'Only the validated open steps can be executed in this version; all other stages are guided review.',
              'bad').pack(fill='x')

    top = ttk.Frame(body)
    top.pack(fill='x', pady=(12, 0))
    top.columnconfigure(1, weight=1)
    who = ttk.LabelFrame(top, text='1  Who and what', padding=12)
    who.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
    for r_, (label, var) in enumerate((('Instrument ID *', self.asset), ('Serial number *', self.serial), ('Technician *', self.tech))):
        ttk.Label(who, text=label).grid(row=r_, column=0, sticky='w', pady=3)
        ttk.Entry(who, textvariable=var, width=22).grid(row=r_, column=1, padx=(10, 0), pady=3)
    link = ttk.LabelFrame(top, text='2  Connect to the meter', padding=12)
    link.grid(row=0, column=1, sticky='nsew')
    ttk.Label(link, text='8846A port').grid(row=0, column=0, sticky='w')
    self.port_combo = ttk.Combobox(link, textvariable=self.port, width=10)
    self.port_combo.grid(row=0, column=1, padx=(8, 14))
    for c_, (text, var, values) in enumerate((('Baud', self.baud, ['9600', '19200', '38400', '115200', '4800', '2400']),
                                              ('Parity', self.parity, ['None', 'Even', 'Odd']), ('Bits', self.bits, ['7', '8']))):
        ttk.Label(link, text=text, style='Muted.TLabel').grid(row=0, column=2 + c_ * 2, sticky='w')
        ttk.Combobox(link, textvariable=var, values=values, width=7, state='readonly').grid(row=0, column=3 + c_ * 2, padx=(5, 12))
    row2 = ttk.Frame(link)
    row2.grid(row=1, column=0, columnspan=8, sticky='w', pady=(12, 0))
    ttk.Button(row2, text='Refresh ports', command=self.refresh_ports).pack(side='left')
    self.btn_connect = ttk.Button(row2, text='Connect / verify 8846A', style='Accent.TButton', command=self.connect)
    self.btn_connect.pack(side='left', padx=8)
    self.btn_start = ttk.Button(row2, text='Start new adjustment record', command=self.start)
    self.btn_start.pack(side='left')
    self.btn_resume = ttk.Button(row2, text='Resume existing record', command=self.resume)
    self.btn_resume.pack(side='left', padx=8)

    hintrow = ttk.Frame(body)
    hintrow.pack(fill='x', pady=(12, 6))
    ttk.Label(hintrow, text='NEXT STEP', style='MetricCap.TLabel').pack(side='left')
    ttk.Label(hintrow, textvariable=self.next_hint, style='Bold.TLabel', wraplength=900, justify='left').pack(side='left', padx=(12, 0), fill='x', expand=True)

    # audit log and step detail are packed first so they always stay visible
    log_box = ttk.LabelFrame(body, text='Audit log (this record)', padding=6)
    self.log_box = log_box
    self.log_table = ui.make_table(log_box, ('time', 'action', 'outcome', 'detail'), ('Time', 'Action', 'Outcome', 'Detail'),
                                   (150, 150, 100, 600), anchors={'detail': 'w', 'action': 'w', 'time': 'w'}, height=5,
                                   stretch={'time': False, 'action': False, 'outcome': False})
    self.log_table.tag_configure('ok', foreground=ui.C['good'])
    self.log_table.tag_configure('bad', foreground=ui.C['bad'])
    bar = ttk.Frame(body)
    bar.pack(side='bottom', fill='x', pady=(10, 0))
    self.btn_review = ttk.Button(bar, text='Mark setup reviewed', command=self.mark_reviewed)
    self.btn_unlock = ttk.Button(bar, text='Unlock adjustment (authorised)', command=self.unlock)
    self.btn_exec = ttk.Button(bar, text='Execute selected verified open step', style='Accent.TButton', command=self.execute)
    self.btn_commit = ttk.Button(bar, text='Commit coefficients (CAL:REC)', command=self.commit)
    self.btn_relock = ttk.Button(bar, text='Relock and disconnect', style='Danger.TButton', command=self.disconnect)
    for b_ in (self.btn_review, self.btn_unlock, self.btn_exec, self.btn_commit):
        b_.pack(side='left', padx=(0, 8))
    self.btn_relock.pack(side='right')
    self.show_log = tk.BooleanVar(value=False)
    ttk.Checkbutton(bar, text='Show audit log', variable=self.show_log, command=self._toggle_log).pack(side='right', padx=(0, 16))
    self._bar = bar
    info = ttk.LabelFrame(body, text='Selected step', padding=(12, 6))
    info.pack(side='bottom', fill='x', pady=(10, 0))
    ttk.Label(info, textvariable=self.detail, wraplength=900, justify='left').pack(anchor='w', fill='x')

    self.tree = ui.make_table(body, ('n', 'phase', 'step', 'setup', 'state'), ('#', 'Phase', 'Step', 'Setup', 'Status'),
                              (40, 80, 260, 560, 150), anchors={'step': 'w', 'setup': 'w', 'phase': 'w'}, height=14,
                              stretch={'n': False, 'phase': False, 'step': False, 'state': False})
    self.tree.tag_configure('eligible', background=ui.C['info_bg'])
    self.tree.tag_configure('done', background=ui.C['good_bg'], foreground=ui.C['good'])
    for i, (phase, name, setup, _, _, enabled) in enumerate(E.STEPS):
        self.tree.insert('', 'end', iid=str(i), values=(i + 1, phase, name, setup, 'Open-step eligible' if enabled else 'Guided review'),
                         tags=('eligible',) if enabled else ())
    self.tree.bind('<<TreeviewSelect>>', lambda _e: self._on_select())
    ui.polish(root)


def toggle_log(self):
    if self.show_log.get():
        self.log_box.pack(side='bottom', fill='x', pady=(10, 0), before=self._bar)
    else:
        self.log_box.pack_forget()


def table_set_state(self, idx, text, tags):
    """The status cell and row tags of one step (the statements of the launcher's former _set_state)."""
    self.tree.set(str(idx), 'state', text)
    self.tree.item(str(idx), tags=tags)


def table_selection(self):
    return self.tree.selection()


def set_ports(self, ports):
    """The serial-port picker's values (a statement of the launcher's former refresh_ports)."""
    self.port_combo['values'] = ports


def sync_pills(self, live, unlocked):
    """The status pills (the statements of the launcher's former _sync)."""
    self.pill_meter.set('Meter: DEMO (simulated)' if self.demo else ('Meter: connected' if live else 'Meter: not connected'),
                        'warn' if self.demo else 'good' if live else 'neutral')
    self.pill_run.set(f'Record #{self.run_id}' if self.run_id else 'No adjustment record', 'info' if self.run_id else 'neutral')
    self.pill_lock.set('Calibration UNLOCKED' if unlocked else 'Calibration LOCKED', 'bad' if unlocked else 'good')


def sync_buttons(self, connect, start, resume, review, unlock, execute, commit, relock):
    """Button states (the `en(...)` statements of the launcher's former _sync)."""
    def en(btn, cond):
        btn.configure(state='normal' if cond else 'disabled')
    en(self.btn_connect, connect)
    en(self.btn_start, start)
    en(self.btn_resume, resume)
    en(self.btn_review, review)
    en(self.btn_unlock, unlock)
    en(self.btn_exec, execute)
    en(self.btn_commit, commit)
    en(self.btn_relock, relock)


def log_add(self, values, tags):
    self.log_table.insert('', 0, values=values, tags=tags)


def log_clear(self):
    self.log_table.delete(*self.log_table.get_children())
