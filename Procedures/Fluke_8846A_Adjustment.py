"""Fluke 8846A guided adjustment v57 — controlled initial implementation.

CAUTION: Calibration commands modify volatile adjustment coefficients. CAL:REC
writes nonvolatile calibration memory. Only trained technicians should use live mode.
Source: Fluke 8845A/8846A Calibration Manual, Chapter 3, and Programmer's Manual.
The verified open-step subset is provided; other adjustment stages are intentionally
review-only until the exact revision-specific tables and 5560A commands are validated.
"""
import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

BASE = Path(__file__).resolve().parent
sys.path.append(str(BASE.parent))  # shared ui_theme.py sits next to the Manager
import ui_theme as ui
import drivers
import reset_startup
DB = BASE / 'calibration_procedures.sqlite3'
STEPS = [
    ('PRE', 'As Found verification', 'Run and save the complete independent 8846A performance verification before any adjustment.', '', '', False),
    ('PRE', 'Equipment and safety', 'Verify technician authorization, warm-up, 5560A traceability, required fixtures, firmware and correct 8846A identity.', '', '', False),
    ('OPEN', '100 MΩ open', 'Disconnect all leads from meter inputs. Verify open terminals and correct front/rear selection.', 'ORES', '100000000', True),
    ('OPEN', '1 GΩ open (8846A)', 'Keep all terminals open. This step applies to the 8846A only.', 'ORES', '1000000000', True),
    ('OPEN', '1 nF capacitance open (8846A)', 'Keep terminals open and confirm the capacitance setup specified by the manual.', 'ZCAP', '1.00E-09', True),
    ('ZERO', 'AC voltage short adjustments', 'Install the specified 4-wire low-thermal short. Complete the ACV zero sequence from the revision-matched adjustment table.', '', '', False),
    ('ZERO', 'DC voltage short adjustments', 'With the prescribed low-thermal short, complete the DCV zero sequence from the adjustment table.', '', '', False),
    ('ZERO', 'Resistance and current zero adjustments', 'Use the manual-specific shorts/opens and current terminals; confirm each connection before adjustment.', '', '', False),
    ('REAR', 'Rear-panel zero adjustments', 'Select rear terminals and install the manual-specified low-thermal fixtures; perform all required rear-zero steps.', '', '', False),
    ('GAIN', 'DC gain adjustments', 'Verify Fluke 5560A range, uncertainty, polarity, wiring and each adjustment setpoint from the manual before enabling source automation.', '', '', False),
    ('GAIN', 'AC gain and linearity', 'Follow manual order. AC linearity adjustments must be followed by AC gain adjustment.', '', '', False),
    ('GAIN', 'Resistance, current, frequency, capacitance', 'Perform only with the required standards, cables, guards, and manual-specific setup.', '', '', False),
    ('FINISH', 'Record coefficients', 'After successful complete adjustment and review, explicitly commit changed calibration coefficients.', '', '', False),
    ('FINISH', 'As Left verification', 'Relock calibration and run the independent performance verification again; archive results.', '', '', False),
]


def connect_db():
    con = sqlite3.connect(DB)
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('''CREATE TABLE IF NOT EXISTS adjustment_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id TEXT NOT NULL, serial_number TEXT NOT NULL,
        technician TEXT NOT NULL, meter_idn TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    con.execute('''CREATE TABLE IF NOT EXISTS adjustment_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES adjustment_runs(id),
        event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        step_index INTEGER, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '')''')
    con.commit()
    return con


def open_meter(port, baud, parity, bits):
    """Open the 8846A for adjustment through the instrument driver (RS-232, 1 stop bit, LF terminated)."""
    settings = drivers.SerialSettings(baud=int(baud), data_bits=int(bits), parity=parity.lower(), stop_bits=1,
                                      write_termination='\n', read_termination='\n')
    meter = drivers.Fluke8846A(drivers.SerialTransport(port, settings, timeout=10), drivers.CommandLog(), label='8846A')
    return meter.connect_for_adjustment()


class App:
    def __init__(self, root, demo=False):
        self.root, self.demo = root, demo
        self.meter = None
        self.run_id = None
        self.committed = False
        self.unlocked = False
        self.conn = connect_db()
        ui.apply_theme(root)
        root.title('Fluke 8846A | Guided Adjustment v57' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1280, 860, min_w=1060, min_h=680)
        self.settings = ui.Settings('8846A_adjustment')
        self.asset = tk.StringVar()
        self.serial = tk.StringVar()
        self.tech = tk.StringVar()
        self.port = tk.StringVar(value=self.settings.get('port', 'COM3'))
        self.baud = tk.StringVar(value=self.settings.get('baud', '9600'))
        self.parity = tk.StringVar(value=self.settings.get('parity', 'None'))
        self.bits = tk.StringVar(value=self.settings.get('bits', '8'))
        self.password = tk.StringVar()
        self.status = tk.StringVar(value='DEMO — commands simulated' if demo else 'DISCONNECTED — no adjustment commands enabled')
        self.next_hint = tk.StringVar()
        self.detail = tk.StringVar(value='Select a step to see its setup instructions.')
        self._build_ui()
        self.refresh_ports(quiet=True)
        self._sync()
        root.protocol('WM_DELETE_WINDOW', self.close)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
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
        self.btn_export = ttk.Button(row2, text='Export audit log (CSV)', command=self.export)
        self.btn_export.pack(side='left')

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
        for i, (phase, name, setup, _, _, enabled) in enumerate(STEPS):
            self.tree.insert('', 'end', iid=str(i), values=(i + 1, phase, name, setup, 'Open-step eligible' if enabled else 'Guided review'),
                             tags=('eligible',) if enabled else ())
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self._on_select())
        ui.polish(root)

    # ------------------------------------------------------------------ state display
    def _toggle_log(self):
        if self.show_log.get():
            self.log_box.pack(side='bottom', fill='x', pady=(10, 0), before=self._bar)
        else:
            self.log_box.pack_forget()

    def _set_state(self, idx, text):
        self.tree.set(str(idx), 'state', text)
        self.tree.item(str(idx), tags=('done',) if text in ('Reviewed', 'Adjusted', 'Simulated') else
                       ('eligible',) if STEPS[idx][5] else ())

    def _on_select(self):
        sel = self.tree.selection()
        if sel:
            phase, name, setup, _, _, ok = STEPS[int(sel[0])]
            self.detail.set(f'{name}  ({phase})\n{setup}\n' + ('This step can be executed after you unlock adjustment.' if ok else
                            'Guided review only: perform it on the instrument following the manual; this program will not send commands for it.'))
        self._sync()

    def _sync(self):
        live = self.meter is not None
        ready = live or self.demo
        self.pill_meter.set('Meter: DEMO (simulated)' if self.demo else ('Meter: connected' if live else 'Meter: not connected'),
                            'warn' if self.demo else 'good' if live else 'neutral')
        self.pill_run.set(f'Record #{self.run_id}' if self.run_id else 'No adjustment record', 'info' if self.run_id else 'neutral')
        self.pill_lock.set('Calibration UNLOCKED' if self.unlocked else 'Calibration LOCKED', 'bad' if self.unlocked else 'good')
        sel = self.tree.selection()
        eligible = bool(sel) and STEPS[int(sel[0])][5]
        def en(btn, cond):
            btn.configure(state='normal' if cond else 'disabled')
        en(self.btn_connect, not self.unlocked and not self.demo)
        en(self.btn_start, ready)
        en(self.btn_resume, True)
        en(self.btn_export, self.run_id is not None)
        en(self.btn_review, self.run_id is not None)
        en(self.btn_unlock, self.run_id is not None and ready and not self.unlocked)
        en(self.btn_exec, self.unlocked and self.run_id is not None and eligible)
        en(self.btn_commit, self.unlocked and self.run_id is not None)
        en(self.btn_relock, live or self.unlocked)
        if not ready:
            hint = 'Choose the COM port and press "Connect / verify 8846A".'
        elif self.run_id is None:
            hint = 'Enter Instrument ID, Serial number and Technician, then press "Start new adjustment record".'
        elif self.committed:
            hint = 'Coefficients recorded. Run the independent As Left verification, then press "Relock and disconnect".'
        elif self.unlocked:
            hint = 'Calibration is UNLOCKED. Select an eligible step and execute it, then commit, then relock.'
        else:
            hint = 'Select each step, follow its setup and press "Mark setup reviewed". Unlock only when you are authorised.'
        self.next_hint.set(hint)

    def _audit_row(self, action, detail, outcome):
        tag = 'bad' if outcome in ('ERROR', 'FAILED') else 'ok' if outcome in ('OK', 'CONFIRMED', 'ISSUED', 'DEMO') else ''
        self.log_table.insert('', 0, values=(dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action, outcome, detail), tags=(tag,))

    def refresh_ports(self, quiet=False):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception as e:
            ports = []
            if not quiet:
                messagebox.showerror('COM ports', str(e))
        self.port_combo['values'] = ports
        if not quiet:
            self.status.set('Serial ports found: ' + ', '.join(ports) if ports else 'No serial ports detected - you can still type a port name.')

    def log(self, action, detail='', outcome='', index=None):
        if self.run_id is None: return
        self.conn.execute('INSERT INTO adjustment_events(run_id,step_index,action,detail,outcome) VALUES(?,?,?,?,?)',
                          (self.run_id,index,action,detail,outcome))
        self._audit_row(action, detail, outcome)
        self.conn.execute('UPDATE adjustment_runs SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(self.run_id,))
        self.conn.commit()

    def connect(self):
        if self.demo:
            self.status.set('DEMO — simulated 8846A connection');self._sync();return
        try:
            if self.meter:self.meter.close()
            self.meter=open_meter(self.port.get(),self.baud.get(),self.parity.get(),self.bits.get())
            self.status.set('Connected: '+self.meter.idn)
            self.log('CONNECT',self.meter.idn,'OK')
            if self.run_id is not None and not self.reset_meter():    # resuming a record: reset after reconnecting, before any step
                self.meter.close();self.meter=None;self._sync();return
            self.settings.set('port',self.port.get());self.settings.set('baud',self.baud.get());self.settings.set('parity',self.parity.get());self.settings.set('bits',self.bits.get());self.settings.save()
            self._sync()
        except Exception as e:
            self.meter=None;self._sync()
            self.status.set('Connection error: '+str(e))
            messagebox.showerror('Connection error',str(e))

    def reset_meter(self):
        """Reset the 8846A to its default settings before an adjustment record starts (or resumes after reconnecting). The notice about the
        unit under test is asked first; declining or a failed reset ends the start before any adjustment step. Calibration stays locked
        (nothing here sends a CAL: command). Returns True when the meter is reset (or there is no meter: demo)."""
        if self.demo or not self.meter:
            return True
        try:
            reset_startup.reset_all([], [self.meter], confirm=lambda t: messagebox.askokcancel('Reset instruments', t, icon='warning'),
                                    log=self.meter.log)
        except reset_startup.ResetDeclined as e:
            self.status.set('Not started: the 8846A was not reset (nothing was touched).');self.log('RESET','declined by operator','CANCELLED');return False
        except Exception as e:
            self.status.set('Reset failed - not started: '+str(e).splitlines()[0]);self.log('RESET',str(e).splitlines()[0],'FAILED')
            messagebox.showerror('Reset failed - not started',str(e));return False
        self.log('RESET','Instruments reset to default settings at start: '+self.meter.label,'OK')
        return True

    def start(self):
        if not all([self.asset.get().strip(),self.serial.get().strip(),self.tech.get().strip()]):
            messagebox.showwarning('Required information','Enter instrument ID, serial number and technician.');return
        if not self.demo and not self.meter:
            messagebox.showwarning('Connection required','Connect and identify the 8846A first.');return
        if not messagebox.askyesno('Start new record','Start a new adjustment audit record? This does not unlock the meter.'):
            return
        if not self.reset_meter():return
        cur=self.conn.execute('INSERT INTO adjustment_runs(asset_id,serial_number,technician,meter_idn) VALUES(?,?,?,?)',
                (self.asset.get().strip(),self.serial.get().strip(),self.tech.get().strip(),
                 self.meter.idn if self.meter else 'DEMO'))
        self.run_id=cur.lastrowid;self.conn.commit();self.committed=False;self.log_table.delete(*self.log_table.get_children())
        self.log('RUN_STARTED','Guided adjustment v57','OK')
        self.status.set(f'Adjustment record #{self.run_id} active; no coefficients committed');self._sync()

    def resume(self):
        if not self.asset.get().strip():
            messagebox.showwarning('Instrument ID','Enter instrument ID to find previous records.');return
        row=self.conn.execute('SELECT id,serial_number,technician,status FROM adjustment_runs WHERE asset_id=? ORDER BY id DESC LIMIT 1',
                              (self.asset.get().strip(),)).fetchone()
        if not row:
            messagebox.showinfo('No record','No previous adjustment record found.');return
        if row[3] not in ('IN_PROGRESS','ADJUSTED_NOT_VERIFIED'):
            messagebox.showwarning('Record closed','Most recent record is closed. Start a new record.');return
        if not messagebox.askyesno('Resume',f'Resume run #{row[0]} for serial {row[1]}?'):
            return
        self.run_id=row[0];self.serial.set(row[1]);self.tech.set(row[2]);self.log('RUN_RESUMED','Resumed by operator','OK')
        self.status.set(f'Resumed adjustment record #{self.run_id}; reconnect and unlock explicitly');self._sync()

    def selected(self):
        s=self.tree.selection()
        if not s:
            messagebox.showwarning('Select a step','Select a row first.');return None
        return int(s[0])

    def mark_reviewed(self):
        idx=self.selected()
        if idx is None:return
        if self.run_id is None:
            messagebox.showwarning('Record required','Start or resume an adjustment record first.');return
        if messagebox.askyesno('Review confirmation',f'Confirm you reviewed the setup and manual requirements for:\n{STEPS[idx][1]}'):
            self.log('SETUP_REVIEWED',STEPS[idx][1],'CONFIRMED',idx)
            self._set_state(idx,'Reviewed')

    def unlock(self):
        if self.run_id is None or (not self.demo and not self.meter):
            messagebox.showwarning('Prerequisites','Start a record and connect the identified 8846A first.');return
        if not messagebox.askyesno('Authorized adjustment','I am authorized to adjust this instrument, have reviewed the calibration manual, and understand coefficients may change. Continue?'):
            return
        if self.demo:
            self.unlocked=True;self.log('UNLOCK','Simulated','DEMO');self.status.set('DEMO: unlocked (simulated)');self._sync();return
        from tkinter import simpledialog
        pw=simpledialog.askstring('Calibration password','Enter the instrument calibration password:',show='*',parent=self.root)
        if not pw:return
        if not re.fullmatch(r'[A-Za-z0-9]{1,12}',pw):
            messagebox.showerror('Password','Expected 1–12 alphanumeric characters.');return
        try:
            self.meter.unlock_calibration(pw)
            self.unlocked=True;self.log('UNLOCK','Calibration security verified OFF','OK')
            self.status.set('UNLOCKED — live adjustment enabled for verified open steps only');self._sync()
        except Exception as e:
            self.log('UNLOCK','Unlock failed','ERROR')
            messagebox.showerror('Unlock failed',str(e))

    def execute(self):
        idx=self.selected()
        if idx is None:return
        phase,name,setup,mode,value,eligible=STEPS[idx]
        if not eligible:
            messagebox.showinfo('Not yet validated','This stage is review-only in v56. Exact revision-specific setpoints and 5560A controls require bench validation.');return
        if not self.run_id or not self.unlocked:
            messagebox.showwarning('Prerequisites','Start a record and explicitly unlock adjustment first.');return
        if not messagebox.askyesno('Confirm physical setup',f'{name}\n\n{setup}\n\nConfirm all inputs are OPEN and no source is connected. Execute one calibration step?'):
            return
        if not messagebox.askyesno('Final command confirmation',f'Command: CAL:VAL {mode},{value}\nThen: CAL? ON\n\nThis changes volatile calibration coefficients. Proceed?'):
            return
        try:
            if self.demo:reply='+0'
            else:
                # Driver checks for the +0 success reply (calibration manual example); confirm against your firmware.
                reply=self.meter.adjust_step(mode,value)
            self.log('ADJUST_STEP',f'{mode},{value}; reply={reply}','OK' if not self.demo else 'DEMO',idx)
            self._set_state(idx,'Adjusted' if not self.demo else 'Simulated')
            self.status.set(f'Step {idx} accepted; coefficients NOT committed')
        except Exception as e:
            self.log('ADJUST_STEP',f'{mode},{value}: {e}','FAILED',idx)
            messagebox.showerror('Adjustment step failed',str(e))

    def commit(self):
        if not self.run_id or not self.unlocked:
            messagebox.showwarning('Prerequisites','Active run and unlocked calibration required.');return
        if not messagebox.askyesno('Commit calibration coefficients',
             'CAL:REC writes adjusted coefficients to NONVOLATILE MEMORY.\n\nHave you completed the FULL manual adjustment sequence, validated all steps and checked for errors?'):
            return
        from tkinter import simpledialog
        phrase=simpledialog.askstring('Final confirmation','Type COMMIT 8846A to authorize CAL:REC:',parent=self.root)
        if phrase!='COMMIT 8846A':return
        try:
            if not self.demo:self.meter.record_calibration()
            self.log('CAL_RECORD','CAL:REC issued; independent As Left verification required','DEMO' if self.demo else 'ISSUED')
            self.conn.execute("UPDATE adjustment_runs SET status='ADJUSTED_NOT_VERIFIED' WHERE id=?",(self.run_id,));self.conn.commit()
            self.committed=True;self._sync()
            self.status.set('Coefficients recorded; run independent As Left verification before closing calibration')
            messagebox.showwarning('As Left verification required','Coefficient record command issued. Perform independent As Left verification and save its report.')
        except Exception as e:
            self.log('CAL_RECORD',str(e),'ERROR');messagebox.showerror('Commit failed',str(e))

    def disconnect(self):
        if self.meter:
            try:
                if self.unlocked:
                    from tkinter import simpledialog
                    pw=simpledialog.askstring('Relock calibration','Enter calibration password to relock:',show='*',parent=self.root)
                    if not pw or not re.fullmatch(r'[A-Za-z0-9]{1,12}',pw):
                        messagebox.showwarning('Relock not confirmed','Calibration may remain unlocked. Do not leave the instrument unattended.');return
                    self.meter.lock_calibration(pw)
                    self.log('RELOCK','Security state ON','OK')
                self.meter.log.append_default(f'8846A adjustment {self.asset.get().strip()} run {self.run_id}')
                self.meter.close()
            except Exception as e:
                messagebox.showerror('Relock/close error',f'{e}\nMeter may remain unlocked.');return
        self.meter=None;self.unlocked=False;self.committed=False
        self.status.set('Disconnected / demo lock reset');self._sync()

    def export(self):
        if self.run_id is None:
            messagebox.showwarning('Select record','Start or resume a record first.');return
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],
                initialfile=f'8846A_adjustment_run_{self.run_id}.csv')
        if not path:return
        rows=self.conn.execute('SELECT event_time,step_index,action,detail,outcome FROM adjustment_events WHERE run_id=? ORDER BY id',(self.run_id,)).fetchall()
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f);writer.writerow(['Run ID','Instrument ID','Serial','Technician','Time','Step','Action','Detail','Outcome'])
            for t,idx,action,detail,outcome in rows:
                writer.writerow([self.run_id,self.asset.get(),self.serial.get(),self.tech.get(),t,idx if idx is not None else '',action,detail,outcome])
        messagebox.showinfo('Export',f'Exported {len(rows)} audit events.')

    def close(self):
        if self.meter and self.unlocked:
            messagebox.showwarning('Relock first','Calibration is unlocked. Use Relock and Disconnect before exiting.');return
        try:self.disconnect()
        except Exception:pass
        self.conn.close();self.root.destroy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    ui.enable_hidpi()
    root=tk.Tk();App(root,demo=args.demo);root.mainloop()

if __name__=='__main__':main()
