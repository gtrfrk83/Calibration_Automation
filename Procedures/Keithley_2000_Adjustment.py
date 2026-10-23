"""Keithley Model 2000 guided ADJUSTMENT (calibration), window.  The logic is keithley2000_adjustment.py (no tkinter), the steps are specs/keithley_2000_adjustment.json.

THIS CHANGES THE CALIBRATION CONSTANTS OF THE INSTRUMENT.  Method: the remote :CAL:PROT commands of the Model 2000 Calibration Manual (2000-905-01 Rev. F, pp. 2-14 to 2-19).
The calibration code is asked when you unlock and is never stored, logged or written to the audit record.  Nothing is stored in the 2000 before the typed SAVE confirmation.
Demo (virtual instruments, nothing persisted):  python Procedures/Keithley_2000_Adjustment.py --demo
"""
import sys
import time
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import adjustment_audit
import calibrator_fit
import drivers
import keithley2000_adjustment as adj
import reset_startup
import ui_theme as ui
import virtualbench

TITLE = 'Keithley 2000  -  Guided Adjustment'
NOTICE = ('The stored constants of the Model 2000 change only when you type the SAVE confirmation at the end; an abort before that leaves them unchanged. Qualified personnel only '
          '(Calibration Manual p. 2-2). Run the As Found performance verification first and the As Left verification afterwards.')
GROUP_TITLE = {'SHORT': 'the low-thermal short', 'OPEN': 'open inputs', 'DCV': 'DC volts', 'OHM4': '4-wire ohms', 'DCI': 'DC current', 'ACV': 'AC volts', 'ACI': 'AC current'}


class App(virtualbench.VirtualMixin):
    def __init__(self, root, demo=False):
        self.init_virtual(demo, False)
        self.root, self.demo = root, demo
        self.io = None
        self.session = None
        self.audit = adjustment_audit.AuditStore(demo=demo)
        self.busy = False
        self._abort_req = False
        self._last_group = None
        ui.apply_theme(root)
        root.title(TITLE.replace('  -  ', ' | ') + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 900, min_w=1000, min_h=680)
        self.settings = ui.Settings('Keithley2000Adjustment')
        s = self.settings
        self.asset, self.serial, self.tech = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.scope = tk.StringVar(value=s.get('scope', next(iter(adj.SCOPES))))
        if self.scope.get() not in adj.SCOPES:
            self.scope.set(next(iter(adj.SCOPES)))
        self.interface = tk.StringVar(value=s.get('interface', 'GPIB'))
        self.dmm_addr = tk.StringVar(value=s.get('dmm_addr', '16'))
        self.dmm_baud = tk.StringVar(value=s.get('dmm_baud', '4800'))
        self.dmm_term = tk.StringVar(value=s.get('dmm_term', 'LF'))
        self.dmm_flow = tk.StringVar(value=s.get('dmm_flow', 'None'))
        self.cal_offer = calibrator_fit.make_offer('5520A', adj.requests(), unverified=drivers.Fluke5520A.unverified_summary())
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5560A'))
        if self.cal_model.get() not in self.cal_choices():
            self.cal_model.set('Fluke 5560A')
        self.cal_interface = tk.StringVar(value=s.get('cal_interface', adj.CAL_INTERFACES[0]))
        if self.cal_interface.get() not in adj.CAL_INTERFACES:
            self.cal_interface.set(adj.CAL_INTERFACES[0])
        self.cal_addr = tk.StringVar(value=s.get('cal_addr', adj.CAL_PORT_DEFAULT[self.cal_interface.get()]))
        self.cal_baud = tk.StringVar(value=s.get('cal_baud', '9600'))
        self.status = tk.StringVar()
        self.next_hint = tk.StringVar()
        self.cal_note = tk.StringVar()
        self._build_ui()
        self._fill_table()
        self.on_cal_model()
        self.status.set('DEMO MODE (virtual instruments): commands go to a simulated Model 2000 and calibrator; nothing is recorded as evidence.' if demo
                        else 'Enter the instrument ID, choose the interfaces and press Connect.')
        self._sync()
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        banner = ui.Banner(root, TITLE, 'Remote :CAL:PROT command calibration, Calibration Manual 2000-905-01 Rev. F, pp. 2-14 to 2-19  |  GPIB or RS-232')
        banner.pack(fill='x')
        if self.demo:
            banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
        self.pill_meter = banner.add_pill('2000: not connected', 'neutral')
        self.pill_run = banner.add_pill('No adjustment record', 'neutral')
        self.pill_lock = banner.add_pill('Calibration LOCKED', 'good')
        ui.StatusBar(root, self.status, right='spec v1').pack(side='bottom', fill='x')
        body = ttk.Frame(root, padding=(18, 12, 18, 8))
        body.pack(fill='both', expand=True)
        ui.Notice(body, NOTICE, 'bad', title='This changes the instrument calibration').pack(fill='x')

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

    def _toggle_log(self):
        if self.show_log.get():
            self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
        else:
            self.log_box.pack_forget()

    def cal_choices(self):
        """The calibrator picker's values: the 5520A only when its published specification covers every output of the adjustment (calibrator_fit)."""
        return [n for n in adj.CALIBRATORS if n not in adj.CAL_OFFERED_ONLY_IF_FIT or self.cal_offer.offered]

    def on_cal_model(self):
        key = adj.CALIBRATORS[self.cal_model.get()][0]
        self.cal_note.set(f'{self.cal_model.get()} against the manual\'s Table 2-1: ' + adj.CAL_NOTES.get(key, '') + (f'  {self.cal_offer.text}' if key == '5520A' else ''))


    # ------------------------------------------------------------------ table / state
    @property
    def scope_t(self):
        return adj.SCOPES[self.scope.get()]

    def fw_class(self):
        return self.io.dmm.fw_class if self.io else None

    def _fill_table(self):
        self.tree.delete(*self.tree.get_children())
        fw = self.fw_class() if self.fw_class() in ('A20+', 'A19-') else 'A20+'
        nxt = self.session.next_step() if self.session else None
        for st in adj.steps_in_scope(self.scope_t):
            n = st['a20'] if fw == 'A20+' else st['a19']
            if n is None:
                continue
            cmd = adj.command_text(st, fw)
            par = ('~' + adj.parameter_text(st, st['param']['nominal'])) if st['param'] else '-'
            rec = self.session.records[st['id']] if self.session else None
            state, tags = 'pending', ()
            if rec is not None:
                if rec.done:
                    state, tags = 'done', ('done',)
                elif rec.indeterminate:
                    state, tags = 'NO COMPLETION', ('failed',)
                elif rec.failed:
                    state, tags = 'FAILED', ('failed',)
                elif nxt is not None and nxt['id'] == st['id']:
                    state, tags = 'next', ('next',)
            self.tree.insert('', 'end', iid=st['id'], values=(st['id'], st['title'], adj.source_text(st), cmd + (' <value>' if st['param'] else ''), par, state), tags=tags)

    def _sync(self):
        s = self.session
        live = self.io is not None
        locked_ui = self.busy
        self.pill_meter.set(('2000: DEMO (simulated)' if self.demo else '2000: connected') if live else '2000: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
        rid = self.audit.run_id
        self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No adjustment record', 'info' if rid else 'neutral')
        unlocked = bool(s and s.unlocked)
        self.pill_lock.set('Calibration UNLOCKED' if unlocked else 'Calibration LOCKED', 'bad' if unlocked else 'good')

        def en(btn, cond):
            btn.configure(state='normal' if (cond and not locked_ui) else 'disabled')
        finished = bool(s and (s.aborted or s.locked_again))
        en(self.btn_connect, not live)
        en(self.btn_start, live and not (s and not finished))
        en(self.btn_unlock, bool(s) and not unlocked and not finished and not s.saved)
        en(self.btn_run, unlocked and not s.all_done() and not s.save_sent)
        en(self.btn_save, unlocked and s.all_done() and not s.save_sent)
        self.btn_abort.configure(state='normal' if (unlocked or (s and not finished and any(r.attempts for r in s.records.values()))) else 'disabled')
        en(self.btn_close, live)
        for w in (self.scope_combo,):
            w.configure(state='disabled' if s and not finished else 'readonly')
        if not live:
            hint = 'Enter the instrument ID, choose the interfaces and press Connect.'
        elif s is None or finished:
            hint = 'Enter instrument ID, serial number and technician, then press "Start adjustment record" (this resets both instruments; the calibration stays locked).'
        elif not unlocked and not s.saved:
            hint = 'Press "Unlock calibration": you confirm warm-up, the As Found verification and your authority, then type the calibration code.'
        elif s.save_sent and not s.saved:
            hint = ':CAL:PROT:SAVE was sent but not confirmed. Do not trust the stored constants: use "Abort and lock", then verify.'
        elif s.all_done():
            hint = 'Every step is done. Press "Dates and SAVE" to set the dates and (after you type the confirmation) store the constants.'
        else:
            nxt = s.next_step()
            hint = f'Calibration is UNLOCKED. Next: {nxt["id"]}  {nxt["title"]}  ({adj.command_text(nxt, s.fw_class)}). Press "Run next step".' if nxt else ''
        self.next_hint.set(hint)

    def _audit_row(self, row, step_id=''):
        t, action, outcome, detail = row
        tag = 'bad' if outcome in ('FAILED', 'ERROR', 'INDETERMINATE', 'NOT CONFIRMED', 'COULD NOT CONFIRM') else 'ok' if outcome in ('OK', 'CONFIRMED', 'SENT', 'DONE') else ''
        self.log_table.insert('', 0, values=(t, step_id, action, outcome, detail), tags=(tag,) if tag else ())

    # ------------------------------------------------------------------ waiting without freezing
    def pump(self, seconds, what):
        end = time.monotonic() + seconds
        while not self._abort_req:
            left = end - time.monotonic()
            if left <= 0:
                break
            self.status.set(f'{what}: {left:.0f} s')
            self.root.update()
            time.sleep(0.05)

    def _begin(self):
        self.busy, self._abort_req = True, False
        self._sync()
        self.root.update_idletasks()

    def _end(self):
        self.busy = False
        self._fill_table()
        self._sync()

    # ------------------------------------------------------------------ connect
    def connect(self):
        if not self.asset.get().strip():
            messagebox.showwarning('Instrument ID', 'Enter the instrument ID first.')
            return
        self.status.set('Connecting ...')
        self.root.update_idletasks()
        try:
            self.io = self._new_io()
        except Exception as exc:
            self.io = None
            self.status.set('Connection error: ' + str(exc).splitlines()[0])
            messagebox.showerror('Connection error', str(exc))
            self._sync()
            return
        if self.io.dmm.fw_class not in ('A20+', 'A19-'):
            a20 = messagebox.askyesno('Firmware revision', f'The 2000 identified itself as:\n{self.io.ident}\n\nThe program could not read the firmware revision from this text. The calibration step numbers differ between '
                                      'firmware A19 and earlier and A20 and later (Calibration Manual Table 3-1 note, p. 3-4).\n\nIs the firmware revision A20 or LATER?  (No = A19 or earlier. Check CONFIG > '
                                      'SNUMBER / the rear-panel label if you are not sure; a wrong answer would send the wrong step.)', icon='warning')
            self.io.dmm.set_firmware_class('A20+' if a20 else 'A19-')
            how = 'chosen by the operator'
        else:
            how = f'read from *IDN? ({self.io.dmm.fw_rev})'
        self._fw_how = how
        if not self.demo:
            self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set(f'Connected: {self.io.ident}{tag}. Firmware numbering {adj.parse_firmware_label(self.io.dmm.fw_class)} ({how}). Calibrator output is NOT enabled; calibration is LOCKED.')
        self._fill_table()
        self._sync()

    def _new_io(self):
        cal_name = adj.CALIBRATORS[self.cal_model.get()][0]
        if self.demo:
            from drivers.simulated_k2000_cal import make_k2000_cal_bench
            _bench, cal_t, dmm_t = make_k2000_cal_bench(cal_name, 'GPIB' if self.interface.get() == 'GPIB' else 'RS232', 'A20')
            return adj.AdjustIO('16', 'COM9', self.cal_model.get(), transports=(dmm_t, cal_t), virtual=True)
        serial = adj.serial_kwargs(self.dmm_baud.get(), self.dmm_term.get(), self.dmm_flow.get()) if self.interface.get() != 'GPIB' else None
        return adj.AdjustIO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), cal_baud=int(self.cal_baud.get()), interface=self.interface.get(),
                            cal_interface=self.cal_interface.get(), serial=serial)

    def _save_settings(self):
        for key, var in (('interface', self.interface), ('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_term', self.dmm_term), ('dmm_flow', self.dmm_flow),
                         ('cal_model', self.cal_model), ('cal_interface', self.cal_interface), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('scope', self.scope)):
            self.settings.set(key, var.get())
        self.settings.save()                            # the calibration code is never part of the settings

    # ------------------------------------------------------------------ record
    def start_record(self):
        if not all([self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip()]):
            messagebox.showwarning('Required information', 'Enter instrument ID, serial number and technician.')
            return
        if self.io is None:
            return
        notes = [('Method', 'The remote :CAL:PROT commands in the order of the manual (Tables 2-8 to 2-12). Both instruments are reset to their defaults first; the 2000 stays LOCKED.'),
                 ('Scope', self.scope.get()), ('Calibrator', f'{self.cal_model.get()}: ' + adj.CAL_NOTES.get(self.io.cal_key, ''))]
        if not ui.confirm_steps(self.root, 'Start adjustment record', 'Start a new adjustment record?', [('Nothing is changed yet', 'Starting resets the instruments and sets DC volts / SLOW; the calibration stays locked until you unlock it.'),
                                ('INPUTS switch', 'Set it to FRONT (button not pressed in). The program reads it and stops if it is on REAR.')],
                                facts=notes, caution='This procedure adjusts the calibration of the Model 2000.', ok='Start record'):
            return
        self._begin()
        try:
            self.audit.start_run(adj.INSTRUMENT, self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip(), uut_idn=self.io.ident,
                                 firmware=adj.parse_firmware_label(self.io.dmm.fw_class), calibrator=self.cal_model.get(), scope='+'.join(self.scope_t))
            wait = (lambda sec: self.pump(sec, 'Settling'))
            self.session = adj.Session(self.io, self.audit, scope=self.scope_t, wait=wait, scale=virtualbench.WAIT_SCALE if self.virtual else 1.0)
            self.session.on_log = self._audit_row
            self.log_table.delete(*self.log_table.get_children())
            self.session.log('RUN_STARTED', 'OK', f'{adj.INSTRUMENT} {self.io.ident}; calibrator {self.cal_model.get()}' + (' [DEMO: nothing saved]' if self.demo else ''))
            self.session.set_firmware_class(self.io.dmm.fw_class, getattr(self, '_fw_how', ''))
            try:
                self.session.reset(confirm=lambda t: messagebox.askokcancel('Reset instruments', t, icon='warning'))
            except reset_startup.ResetDeclined:
                self.session.log('RESET', 'CANCELLED', 'declined by the operator; nothing was touched')
                self.session = None
                self.status.set('Not started: the reset was declined (nothing was touched).')
                return
            except reset_startup.ResetFailed as exc:
                self.session.log('RESET', 'FAILED', 'run not started')
                self.session = None
                self.status.set('Reset failed - not started.')
                messagebox.showerror('Reset failed - not started', exc.report.failure_text() if hasattr(exc.report, 'failure_text') else str(exc))
                return
            self.session.prepare()
        except Exception as exc:
            if self.session:
                self.session.log('START', 'FAILED', str(exc).splitlines()[0])
            self.session = None
            self.status.set('Not started: ' + str(exc).splitlines()[0])
            messagebox.showerror('Not started', str(exc))
            return
        finally:
            self._end()
        self.status.set(f'Adjustment record active ({self.audit.run_id}); calibration is LOCKED and nothing has been changed.')

    # ------------------------------------------------------------------ unlock
    def unlock(self):
        s = self.session
        if s is None or s.unlocked:
            return
        ok = ui.confirm_steps(self.root, 'Before the adjustment', 'Warm-up, conditions and As Found',
            [('Warm-up', 'The 2000 must have been on for at least ONE hour (one more if it was outside 23 C +/- 5 C); allow the calibrator its own warm-up (Cal Manual p. 2-3).'),
             ('Environment', '23 C +/- 5 C, relative humidity below 80 % (p. 2-3).'),
             ('As Found', 'The performance verification (As Found) has been run and its report kept.'),
             ('Direct connection', 'No scanner or switching equipment between the calibrator and the 2000; common-mode voltage under 500 V peak (p. 2-4).')],
            facts=[('Instrument', f'{self.asset.get().strip()}  (serial {self.serial.get().strip()})'), ('Calibrator', self.cal_model.get())],
            caution='Next you confirm your authority and type the calibration code.', ok='All confirmed')
        if not ok:
            self.status.set('Not unlocked: conditions were not confirmed.')
            return
        s.acknowledge('conditions', 'warm-up and environment confirmed')
        s.acknowledge('as_found', 'As Found performance verification done')
        if not messagebox.askyesno('THIS CHANGES THE INSTRUMENT CALIBRATION',
                                   'I am authorised to adjust this instrument and understand that the calibration constants of the Model 2000 will change when I save them.\n\n'
                                   'Nothing is stored until I type the SAVE confirmation at the end. Continue to the calibration code?', icon='warning'):
            self.status.set('Not unlocked.')
            return
        s.acknowledge('authorised', 'operator authorised to adjust')
        s.acknowledge('notice', 'calibration-change notice acknowledged')
        from drivers.simulated_k2000_cal import SIM_CODE
        hint = (f'\n\nDEMO: the simulated meter accepts {SIM_CODE} (not a real code).' if self.demo else '')
        code = simpledialog.askstring('Calibration code', 'Enter the calibration code of the Model 2000 (1 to 8 letters / digits).\nIt is sent once and is NOT stored or logged.' + hint,
                                      show='*', parent=self.root)
        if not code:
            self.status.set('Not unlocked: no code entered.')
            return
        self._begin()
        try:
            s.unlock(code)
        except Exception as exc:
            self.status.set('Unlock failed: ' + str(exc).splitlines()[0])
            messagebox.showerror('Unlock failed', str(exc))
            return
        finally:
            code = None
            self._end()
        self.status.set('Calibration UNLOCKED. Nothing is stored until SAVE. Press "Run next step".')

    # ------------------------------------------------------------------ one step
    def ask_value(self, title, prompt, default):
        win = ui.dialog(self.root, title)
        var, result = tk.StringVar(value=default), {'v': None}
        frame = ttk.Frame(win, padding=16)
        frame.pack()
        ttk.Label(frame, text=prompt, wraplength=ui.px(460), justify='left').pack(anchor='w')
        ent = ttk.Entry(frame, textvariable=var, width=24)
        ent.pack(anchor='w', pady=(10, 0))
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=(14, 0))

        def done(ok):
            result['v'] = var.get() if ok else None
            win.destroy()
        ttk.Button(row, text='Use this value', style='Accent.TButton', command=lambda: done(True)).pack(side='right')
        ttk.Button(row, text='Cancel', command=lambda: done(False)).pack(side='right', padx=(0, 8))
        win.bind('<Return>', lambda _e: done(True))
        ui.center_on(win, self.root)
        ent.focus_set()
        ent.select_range(0, 'end')
        win.wait_window()
        return result['v']

    def _hookup(self, st):
        s = self.session
        group = st['group']
        image = adj.find_diagram(s.cal_key, group)
        facts = [('Step', f'{st["id"]}  {st["title"]}'), ('Calibrator output', adj.source_text(st)), ('Manual page', st['page'])]
        if image is None and st['source']:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_k2000_ADJ_{s.cal_key}_{group}.png)'))
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', adj.hookup_text(st, s.cal_key))]
        if st.get('note'):
            steps.append(('Manual note', st['note']))
        return ui.confirm_steps(self.root, 'Rewire / verify before the step', f'Connect for {GROUP_TITLE.get(group, group)}', steps, facts=facts,
                                caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image)

    def run_next(self):
        s = self.session
        st = s.next_step() if s else None
        if st is None or self.busy:
            return
        rec = s.records[st['id']]
        self._begin()
        try:
            self._run_step(s, st, rec)
        except Exception as exc:
            self.status.set(f'{st["id"]}: ' + str(exc).splitlines()[0])
            messagebox.showerror(f'Step {st["id"]} stopped', f'{exc}\n\nThe command was NOT repeated automatically. Nothing is saved. You can repeat the step after fixing the cause, or abort.')
            self._last_group = None
        finally:
            try:
                if s.source_on is not None:
                    self.io.standby()
                    s.source_on = None
            except Exception:
                messagebox.showerror('Calibrator', 'The calibrator could not be confirmed in STANDBY. Check its front panel before touching any lead.')
            self._end()
        if self._abort_req:
            self._abort_req = False
            self.abort(ask=False)

    def _run_step(self, s, st, rec):
        rerun = False
        if rec.indeterminate:
            idle = messagebox.askyesno('No completion answer', f'{st["id"]} {st["title"]}: the 2000 did not confirm completion of the step.\n\nLook at the 2000 front panel. Is it idle '
                                       '(no CAL / busy annunciator, normal display)?\n\nYes = the program reads the error queue and records the outcome.  No = nothing is decided, wait and ask again.', icon='warning')
            s.confirm_indeterminate(st, idle)
            if idle:
                self.status.set(f'{st["id"]}: completion confirmed by the operator; error queue empty.')
            return
        if rec.failed:
            if not messagebox.askyesno('Repeat a failed step', f'{st["id"]} {st["title"]} failed before ({" | ".join(rec.errors) or "error"}).\n\nRepeat it? The program never repeats a '
                                       'calibration command by itself.', icon='warning'):
                return
            rerun = True
        if self._last_group != st['group'] or rerun or st['group'] in ('SHORT', 'OPEN'):
            self.io.standby()
            if not self._hookup(st):
                self.status.set('Paused for wiring.')
                return
            s.mark_hookup(st)
            self._last_group = st['group']
        if st.get('thermal_wait'):
            self.pump(s.thermal_remaining(st), 'Thermal equilibrium (Cal Manual p. 2-15)')
            if self._abort_req:
                return
        hv_ok = False
        if adj.is_hv(st):
            if not messagebox.askyesno('HIGH VOLTAGE', f'This step outputs {adj.source_text(st)}. Verify CAT-rated leads, connections, clearance and personnel safety. Enable the output?', icon='warning'):
                return
            hv_ok = True
        got = s.program_source(st, hv_ok=hv_ok)
        if self._abort_req:
            return
        parameter = None
        if st['param']:
            default = f'{got:.10g}' if got is not None else st['param']['nominal']
            text = self.ask_value('Calibrator value', f'{st["id"]}  {st["title"]}\n\nEnter the EXACT value the calibrator is outputting (this is the parameter of the command; the manual allows '
                                  f'{adj.si_text(st["param"]["lo"], st["param"]["unit"])} to {adj.si_text(st["param"]["hi"], st["param"]["unit"])}). '
                                  'It is pre-filled with the calibrator\'s own read-back (OUT?); change it only to a value from the calibrator\'s certificate.', default)
            if text is None:
                self.io.standby()
                s.source_on = None
                return
            value, why = adj.validate_parameter(st, text)
            if value is None:
                raise adj.AdjustmentError(why)
            if got is not None and adj.differs(st, value, got) and not messagebox.askyesno(
                    'Value differs from the calibrator', f'You entered {value}, the calibrator read back {got:.10g}.\nIs {value} the value from the calibrator\'s certificate for this output?', icon='warning'):
                self.io.standby()
                s.source_on = None
                return
            parameter = value
        cmd = adj.command_text(st, s.fw_class, parameter)
        if not messagebox.askyesno('Send the calibration step',
                                   f'{st["id"]}  {st["title"]}\n\nCalibrator: {adj.source_text(st)} (in OPERATE, settled).\nCommand: {cmd}\n\nThis changes the VOLATILE calibration constants '
                                   '(nothing is stored until SAVE). The command is sent ONCE.\n\nIs the calibrator output stable? Send the step?', icon='warning'):
            self.io.standby()
            s.source_on = None
            self.status.set(f'{st["id"]}: not sent.')
            return
        self.status.set(f'{st["id"]}: calibrating ... (waiting for the 2000)')
        self.root.update()
        try:
            s.send_step(st, parameter, rerun_ack=rerun)
        except adj.cal_driver.StepIndeterminate as exc:
            messagebox.showwarning('No completion answer', f'{exc}\n\nThe command was NOT sent again. Press "Run next step" to decide from the 2000 front panel.')
            self.status.set(f'{st["id"]}: completion not confirmed.')
            return
        except adj.cal_driver.CalibrationError as exc:
            self._last_group = None
            self.status.set(f'{st["id"]}: the 2000 reported an error.')
            messagebox.showerror('Calibration step failed', f'{exc}\n\nThe command was NOT repeated. Nothing is saved.')
            return
        self.status.set(f'{st["id"]} {st["title"]}: done (temporary constants; nothing saved yet).')

    # ------------------------------------------------------------------ dates, save, lock
    def dates_and_save(self):
        s = self.session
        if s is None or not s.all_done():
            return
        today = date.today()
        ctext = self.ask_value('Calibration date', 'Calibration date (YYYY-MM-DD). Stored in the 2000 with :CAL:PROT:DATE.', today.isoformat())
        if ctext is None:
            return
        dtext = self.ask_value('Next calibration due', 'Next calibration due date (YYYY-MM-DD). Stored with :CAL:PROT:NDUE.', adj.default_due(today).isoformat())
        if dtext is None:
            return
        try:
            cal_d, due_d = date.fromisoformat(ctext.strip()), date.fromisoformat(dtext.strip())
        except ValueError:
            messagebox.showerror('Dates', 'Enter the dates as YYYY-MM-DD.')
            return
        phrase = simpledialog.askstring('SAVE the calibration constants',
                                        'SAVE stores ALL the new calibration constants permanently in the 2000 (EEPROM). The manual has no command to undo it.\n\n'
                                        f'Every step of "{self.scope.get()}" is done. Calibration date {cal_d}, next due {due_d}.\n\nType  {adj.CONFIRM_SAVE}  to store the constants:', parent=self.root)
        if phrase != adj.CONFIRM_SAVE:
            self.status.set('Not saved: the confirmation was not typed. The constants are still temporary.')
            return
        self._begin()
        try:
            s.set_dates(cal_d, due_d)
            s.save(phrase)
        except Exception as exc:
            self.status.set('SAVE problem: ' + str(exc).splitlines()[0])
            messagebox.showerror('Dates / SAVE', f'{exc}\n\nIf :SAVE was sent, do not trust the stored constants: use "Abort and lock", then run the performance verification.')
            return
        finally:
            self._end()
        try:
            s.relock()
            msg = 'The constants are saved and the calibration is locked again.'
        except Exception as exc:
            msg = f'The constants are saved, but locking again could not be confirmed ({str(exc).splitlines()[0]}). Do not leave the instrument unattended; cycle its power.'
        s.audit.set_status('SAVED_NOT_VERIFIED')
        self._end()
        self.status.set(msg + ' Run the As Left performance verification.')
        messagebox.showinfo('Saved' + (' (DEMO)' if self.demo else ''), msg + '\n\nRun the As Left performance verification now and keep its report.' +
                            ('\n\nDEMO: this was a simulated meter; nothing was recorded as evidence.' if self.demo else ''))

    def abort(self, ask=True):
        s = self.session
        if s is None:
            return
        if self.busy and ask:
            self._abort_req = True
            self.status.set('Abort requested: stopping after the current wait.')
            return
        if ask and not messagebox.askyesno('Abort', 'Stop the adjustment? The calibrator goes to STANDBY and the calibration is locked again.', icon='warning'):
            return
        text = s.abort('operator')
        self._last_group = None
        self._end()
        self.status.set('Adjustment stopped.')
        messagebox.showinfo('Adjustment stopped', text)

    def disconnect(self):
        s = self.session
        if s and s.unlocked:
            if not messagebox.askyesno('Calibration is UNLOCKED', 'Abort the adjustment, lock the calibration and disconnect?', icon='warning'):
                return
            self.abort(ask=False)
        if self.io:
            self.io.close()
            self.io = None
        self.session = None
        self._last_group = None
        self._fill_table()
        self._sync()
        self.status.set('Disconnected.')

    def on_close(self):
        s = self.session
        if s and s.unlocked:
            messagebox.showwarning('Lock first', 'Calibration is UNLOCKED. Use "Abort and lock" (or finish and SAVE) before closing.')
            return
        if self.busy:
            return
        if not self.demo:
            self._save_settings()
        try:
            if self.io:
                self.io.close()
        finally:
            self.audit.close()
            self.root.destroy()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    demo, _fast = virtualbench.flags(argv)
    ui.enable_hidpi()
    root = tk.Tk()
    App(root, demo=demo)
    root.mainloop()


if __name__ == '__main__':
    main()
