"""Fluke 8808A guided ADJUSTMENT (calibration), window.  The logic is fluke8808a_adjustment.py (no tkinter), the steps are specs/fluke_8808a_adjustment.json.

THIS CHANGES THE CALIBRATION OF THE INSTRUMENT.  Method: the RS-232 calibration dialog of the Fluke 8808A Calibration Manual (Oct 2008), pp. 3-16 / 3-17, Table 3-9 (124 steps).
The manual has no password, save, lock or date command: the points are the whole procedure.  Every function started must be completed; every point is confirmed by you.
Demo (virtual instruments, nothing persisted):  python Procedures/Fluke_8808A_Adjustment.py --demo
"""
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import adjustment_audit
import calibrator_fit
import drivers
import fluke8808a_adjustment as adj
import reset_startup
import ui_theme as ui
import virtualbench

TITLE = 'Fluke 8808A  -  Guided Adjustment'
NOTICE = ('The 8808A has no SAVE step: each point changes the calibration when it is started, and a function that is started must be completed (an incomplete function shows CAL ERROR, '
          'Calibration Manual p. 3-16). Qualified personnel only. Run the As Found performance verification first and the As Left verification afterwards: this program does not do either.')


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
        self.settings = ui.Settings('Fluke8808AAdjustment')
        s = self.settings
        self.asset, self.serial, self.tech = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.scope = tk.StringVar(value=s.get('scope', next(iter(adj.SCOPES))))
        if self.scope.get() not in adj.SCOPES:
            self.scope.set(next(iter(adj.SCOPES)))
        self.dmm_addr = tk.StringVar(value=s.get('dmm_addr', 'COM3'))
        self.dmm_baud = tk.StringVar(value=s.get('dmm_baud', '9600'))
        self.dmm_fmt = tk.StringVar(value=s.get('dmm_fmt', next(iter(adj.PARITY_FORMATS))))
        self.offers = {n: calibrator_fit.make_offer(k, adj.requests(), per_point_manual=True, unverified=(cls.unverified_summary() if hasattr(cls, 'unverified_summary') else ''), name=n) for n, (k, cls) in adj.CALIBRATORS.items()}
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5522A'))
        if self.cal_model.get() not in adj.CALIBRATORS:
            self.cal_model.set('Fluke 5522A')
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
        self.status.set('DEMO MODE (virtual instruments): commands go to a simulated 8808A and calibrator; nothing is recorded as evidence.' if demo
                        else 'Enter the instrument ID, choose the ports and press Connect.')
        self._sync()
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        banner = ui.Banner(root, TITLE, 'RS-232 calibration dialog, Calibration Manual (Oct 2008) pp. 3-16 / 3-17, Table 3-9  |  RS-232 only')
        banner.pack(fill='x')
        if self.demo:
            banner.add_pill('DEMO MODE  -  virtual instruments, nothing saved', 'warn')
        self.pill_meter = banner.add_pill('8808A: not connected', 'neutral')
        self.pill_run = banner.add_pill('No adjustment record', 'neutral')
        self.pill_cal = banner.add_pill('Calibration mode: closed', 'good')
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

        hintrow = ttk.Frame(body)
        hintrow.pack(fill='x', pady=(10, 4))
        ttk.Label(hintrow, text='NEXT', style='MetricCap.TLabel').pack(side='left')
        ttk.Label(hintrow, textvariable=self.next_hint, style='Bold.TLabel', wraplength=ui.px(1100), justify='left').pack(side='left', padx=(12, 0), fill='x', expand=True)

        bar = ttk.Frame(body)
        bar.pack(side='bottom', fill='x', pady=(8, 0))
        self.btn_connect = ttk.Button(bar, text='Connect', command=self.connect)
        self.btn_start = ttk.Button(bar, text='Start adjustment record', command=self.start_record)
        self.btn_enter = ttk.Button(bar, text='Enter calibration mode', command=self.enter_calibration)
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

    def _toggle_log(self):
        if self.show_log.get():
            self.log_box.pack(side='bottom', fill='x', pady=(8, 0), before=self._bar)
        else:
            self.log_box.pack_forget()

    def on_cal_model(self):
        offer = self.offers[self.cal_model.get()]
        ui.Tooltip(self.cal_combo, offer.tooltip)
        self.cal_note.set(offer.text + ('  Own standard needed at: ' + ', '.join(sorted(adj.own_standard_ids(adj.CALIBRATORS[self.cal_model.get()][0]))) + '.'
                                        if adj.own_standard_ids(adj.CALIBRATORS[self.cal_model.get()][0]) else ''))

    # ------------------------------------------------------------------ table / state
    @property
    def scope_t(self):
        return adj.SCOPES[self.scope.get()]

    def _fill_table(self):
        self.tree.delete(*self.tree.get_children())
        nxt = self.session.next_step() if self.session else None
        own = adj.own_standard_ids(adj.CALIBRATORS[self.cal_model.get()][0])
        for st in adj.steps_in_scope(self.scope_t):
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
            out = adj.source_text(st) + ('  (OWN STANDARD)' if st['id'] in own else '') + ('  (characterize)' if st['characterize'] else '') + ('  [list differs]' if st['conflict'] else '')
            self.tree.insert('', 'end', iid=st['id'], values=(st['id'], st['function'], st['title'], out, state), tags=tags)

    def _sync(self):
        s = self.session
        live = self.io is not None
        self.pill_meter.set(('8808A: DEMO (simulated)' if self.demo else '8808A: connected') if live else '8808A: not connected', 'warn' if (live and self.demo) else 'good' if live else 'neutral')
        rid = self.audit.run_id
        self.pill_run.set(('DEMO record (not saved)' if self.demo else f'Record #{rid}') if rid else 'No adjustment record', 'info' if rid else 'neutral')
        open_ = bool(s and s.cal_mode)
        self.pill_cal.set('Calibration mode: OPEN' if open_ else 'Calibration mode: closed', 'bad' if open_ else 'good')

        def en(btn, cond):
            btn.configure(state='normal' if (cond and not self.busy) else 'disabled')
        finished = bool(s and (s.aborted or s.finished))
        en(self.btn_connect, not live)
        en(self.btn_start, live and not (s and not finished))
        en(self.btn_enter, bool(s) and not open_ and not finished)
        en(self.btn_run, open_ and not s.all_done())
        en(self.btn_finish, open_ and s.all_done() and s.active_function is None)
        self.btn_abort.configure(state='normal' if (open_ or (s and not finished and any(r.attempts for r in s.records.values()))) else 'disabled')
        en(self.btn_close, live)
        self.scope_combo.configure(state='disabled' if s and not finished else 'readonly')
        if not live:
            hint = 'Enter the instrument ID, choose the ports and press Connect.'
        elif s is None or finished:
            hint = 'Enter instrument ID, serial number and technician, then press "Start adjustment record" (this resets both instruments; the calibration is not touched).'
        elif not open_:
            hint = 'Press "Enter calibration mode": you confirm warm-up, the As Found verification and your authority first. *TER is sent once.'
        elif s.all_done():
            hint = 'Every point of the scope is done. Press "Finish (EXIT)", then run the As Left performance verification.'
        else:
            nxt = s.next_step()
            hint = (f'Calibration mode is OPEN. Next: {nxt["id"]}  {nxt["function"]}  {nxt["title"]}  ({adj.source_text(nxt)}). Press "Run next point".' if nxt else '')
            if s.active_function:
                hint += f'  {s.active_function} is in progress: all its points must be completed.'
        self.next_hint.set(hint)

    def _audit_row(self, row, step_id=''):
        t, action, outcome, detail = row
        tag = 'bad' if outcome in ('FAILED', 'ERROR', 'INDETERMINATE', 'NOT CONFIRMED', 'COULD NOT CONFIRM', 'UNCONFIRMED') else 'ok' if outcome in ('OK', 'CONFIRMED', 'SENT', 'DONE', 'COMPLETE') else ''
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
        self.io.dmm.tick = self.root.update
        if not self.demo:
            self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set(f'Connected: {self.io.ident}{tag}. The calibrator output is NOT enabled; the calibration mode is closed.')
        self._fill_table()
        self._sync()

    def _new_io(self):
        cal_key = adj.CALIBRATORS[self.cal_model.get()][0]
        if self.demo:
            from drivers.simulated_8808a_cal import make_8808a_cal_bench
            bench, cal_t, dmm_t = make_8808a_cal_bench(cal_key)
            self._bench = bench
            return adj.AdjustIO('COM3', 'COM9', self.cal_model.get(), transports=(dmm_t, cal_t), virtual=True)
        return adj.AdjustIO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), cal_baud=int(self.cal_baud.get()), cal_interface=self.cal_interface.get(),
                            serial=adj.serial_kwargs(self.dmm_baud.get(), self.dmm_fmt.get()))

    def _save_settings(self):
        for key, var in (('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_fmt', self.dmm_fmt), ('cal_model', self.cal_model), ('cal_interface', self.cal_interface),
                         ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('scope', self.scope)):
            self.settings.set(key, var.get())
        self.settings.save()

    # ------------------------------------------------------------------ record
    def start_record(self):
        if not all([self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip()]):
            messagebox.showwarning('Required information', 'Enter instrument ID, serial number and technician.')
            return
        if self.io is None:
            return
        notes = [('Method', 'The RS-232 calibration dialog in the order of Table 3-9. Both instruments are reset to their defaults first; the calibration mode stays closed.'),
                 ('Scope', self.scope.get()), ('Calibrator', f'{self.cal_model.get()}: ' + self.offers[self.cal_model.get()].text)]
        if not ui.confirm_steps(self.root, 'Start adjustment record', 'Start a new adjustment record?', [('Nothing is changed yet', 'Starting resets the instruments; no calibration command is sent.'),
                                ('Verification', 'This program does not run the performance verification: do the As Found one first, the As Left one afterwards.')],
                                facts=notes, caution='This procedure adjusts the calibration of the 8808A.', ok='Start record'):
            return
        self._begin()
        try:
            self.audit.start_run(adj.INSTRUMENT, self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip(), uut_idn=self.io.ident,
                                 calibrator=self.cal_model.get(), scope='+'.join(self.scope_t))
            wait = (lambda sec: self.pump(sec, 'Settling'))
            self.session = adj.Session(self.io, self.audit, scope=self.scope_t, wait=wait, scale=virtualbench.WAIT_SCALE if self.virtual else 1.0)
            self.session.on_log = self._audit_row
            self.log_table.delete(*self.log_table.get_children())
            self.session.log('RUN_STARTED', 'OK', f'{adj.INSTRUMENT} {self.io.ident}; calibrator {self.cal_model.get()}' + (' [DEMO: nothing saved]' if self.demo else ''))
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
        self.status.set(f'Adjustment record active ({self.audit.run_id}); the calibration mode is closed and nothing has been changed.')

    # ------------------------------------------------------------------ the calibration mode
    def enter_calibration(self):
        s = self.session
        if s is None or s.cal_mode:
            return
        ok = ui.confirm_steps(self.root, 'Before the adjustment', 'Warm-up, conditions and As Found',
            [('Warm-up', 'The 8808A must have warmed up for at least one half hour (Calibration Manual p. 1-9); allow the calibrator its own warm-up.'),
             ('Environment', 'Ambient conditions as the manual requires (p. 3-2).'),
             ('As Found', 'The performance verification (As Found) has been run and its report kept.'),
             ('Calibration enable', 'The manual describes the CAL seal and the Cal Enable button only for the front-panel method (p. 3-11) and does not say whether *TER needs them. '
                                    'Do what your lab procedure requires; if *TER is refused, nothing has been changed.')],
            facts=[('Instrument', f'{self.asset.get().strip()}  (serial {self.serial.get().strip()})'), ('Calibrator', self.cal_model.get())],
            caution='Next you confirm your authority; *TER is then sent once.', ok='All confirmed')
        if not ok:
            self.status.set('Not entered: conditions were not confirmed.')
            return
        s.acknowledge('conditions', 'warm-up and environment confirmed')
        s.acknowledge('as_found', 'As Found performance verification done')
        if not messagebox.askyesno('THIS CHANGES THE INSTRUMENT CALIBRATION',
                                   'I am authorised to adjust this instrument and understand that every point I start changes the calibration of the 8808A. There is no SAVE and no way '
                                   'to undo a point; a function that is started must be completed.\n\nEnter the calibration mode?', icon='warning'):
            self.status.set('Not entered.')
            return
        s.acknowledge('authorised', 'operator authorised to adjust')
        s.acknowledge('notice', 'calibration-change notice acknowledged')
        s.acknowledge('ready', 'meter ready for the calibration mode')
        self._begin()
        try:
            s.enter_calibration()
        except Exception as exc:
            self.status.set('Not entered: ' + str(exc).splitlines()[0])
            messagebox.showerror('Calibration mode not entered', str(exc))
            return
        finally:
            self._end()
        self.status.set('Calibration mode OPEN. Press "Run next point".')

    # ------------------------------------------------------------------ one point
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
        facts = [('Step', f'{st["id"]}  {st["function"]}  {st["title"]}'), ('Calibrator output', adj.source_text(st)), ('Manual page', st['page'])]
        if image is None and st['source']:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_8808A_ADJ_{s.cal_key}_{group}.png)'))
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', adj.hookup_text(st, s.cal_key))]
        return ui.confirm_steps(self.root, 'Rewire / verify before the point', f'Connect for {adj.GROUP_TITLE.get(group, group)}', steps, facts=facts,
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
        except adj.NeedsDisplayConfirmation as exc:
            shows = messagebox.askyesno('CALREF not confirmed', f'{exc}\n\nDoes the meter display show the value that was sent?', icon='warning')
            try:
                if not s.confirm_calref_display(st, shows):
                    self._abort_req = True
            except Exception as exc2:
                messagebox.showerror('Point stopped', str(exc2))
        except Exception as exc:
            self.status.set(f'{st["id"]}: ' + str(exc).splitlines()[0])
            messagebox.showerror(f'Point {st["id"]} stopped', f'{exc}\n\nNothing was repeated automatically. You can repeat the point after fixing the cause, or abort.')
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
            if messagebox.askyesno('No completion answer', f'{st["id"]} {st["title"]}: the 8808A did not say the point was finished.\n\nRead what the meter has sent since (read-only, nothing is sent)?',
                                   icon='warning'):
                got = s.recheck_indeterminate(st)
                self.status.set(f'{st["id"]}: ' + ('completion arrived late.' if got else 'still no answer: look at the display (flashing star = calibrating) or abort.'))
            return
        if rec.failed:
            if not messagebox.askyesno('Repeat a failed point', f'{st["id"]} {st["title"]} failed before ({" | ".join(rec.errors) or "error"}).\n\nRepeat it with a fresh confirmation? '
                                       'The program never repeats a command by itself.', icon='warning'):
                return
            rerun = True
        if not s.active_function:
            n = len(adj.function_steps(st['function']))
            if not messagebox.askyesno('Start a function', f'Start {st["function"]} ({adj.FUNCTION_BY_ID[st["function"]]["title"]})?\n\nOnce a function is selected ALL its {n} points must be '
                                       'calibrated (p. 3-16); leaving earlier shows CAL ERROR and the manual does not say what happens to the points already done.\n\n'
                                       f'The function name is sent once. Continue?', icon='warning'):
                self.status.set('Function not started.')
                return
            s.start_function(confirmed=True)
        if s.dmm.state == 'VALUE':
            self._decide_value(s, st, rec)
            if s.dmm.state == 'VALUE' or self._abort_req:
                return
        if s.dmm.state != 'CONFIRMED':
            return
        warn = s.message_warning(st)
        if warn:
            messagebox.showwarning('Terminal', warn)
        if self._last_group != st['group'] or rerun or st['zero']:
            self.io.standby()
            if not self._hookup(st):
                self.status.set('Paused for wiring (the value is already confirmed; press Run next point to continue).')
                return
            s.mark_hookup(st)
            self._last_group = st['group']
        if st['id'] in adj.own_standard_ids(s.cal_key):
            if st['id'] not in s.own_ack:
                if not messagebox.askyesno('Own standard', f'{st["id"]}: {adj.source_text(st)}\n\nThe {self.cal_model.get()} cannot make this output ({adj.own_standard_reasons(s.cal_key).get(st["id"], "")}).\n'
                                           'Connect your own standard, set it, and confirm it is stable. The meter is not read, so you vouch for the value.', icon='warning'):
                    return
                s.acknowledge_own_standard(st)
        elif adj.is_hv(st, s.records[st['id']].output_value) or adj.is_high_current(st, s.records[st['id']].output_value):
            if s.hv_group != st['group']:
                if not messagebox.askyesno('HIGH VOLTAGE / CURRENT', f'This hook-up group outputs up to {adj.source_text(st)}. Verify CAT-rated leads, connections, clearance and '
                                           'personnel safety, and the fuse of the terminal in use. Enable the output?', icon='warning'):
                    return
                s.acknowledge_hv(st)
        s.program_source(st)
        if self._abort_req:
            return
        value_text = adj.si_text(rec.output_value, st['point']['unit']) if rec.output_value is not None else adj.point_text(st)
        if not messagebox.askyesno('Start the point', f'{st["id"]}  {st["function"]}  {st["title"]}\n\nMeter recommended value: {s.rec.raw if s.rec else ""}\nCalibrator: {adj.source_text(st)} (OPERATE, settled)'
                                   f'{chr(10) + "CALREF " + rec.calref if rec.calref else ""}\n\nStarting the point CHANGES the calibration of the 8808A (no undo, no save step). The Enter key '
                                   'is sent ONCE.\n\nIs the input stable? Start the point?', icon='warning'):
            self.io.standby()
            s.source_on = None
            self.status.set(f'{st["id"]}: not started (the value stays confirmed; press Run next point).')
            return
        self.status.set(f'{st["id"]}: calibrating ... (waiting for the 8808A)')
        self.root.update()
        try:
            s.send_point(st, confirmed=True, rerun_ack=rerun)
        except adj.cal_driver.StepIndeterminate as exc:
            messagebox.showwarning('No completion answer', f'{exc}\n\nThe Enter key was NOT sent again. Press "Run next point" to decide.')
            self.status.set(f'{st["id"]}: completion not confirmed.')
            return
        except adj.cal_driver.CalibrationError as exc:
            self._last_group = None
            self.status.set(f'{st["id"]}: the 8808A reported an error.')
            messagebox.showerror('Calibration point failed', f'{exc}\n\nNothing was repeated.')
            return
        self.status.set(f'{st["id"]} {st["function"]} {value_text}: done.')

    def _decide_value(self, s, st, rec):
        """Compare the meter's recommended value with the manual and confirm it (CALREF where needed, then the first Enter)."""
        info = s.review(st)
        choose, unexpected, characterized, waive = 'meter', False, None, False
        if info['verdict'] == 'list':
            ans = messagebox.askyesnocancel('Meter and Table 3-9 differ', f'{info["text"]}\n\nYes = follow the METER (calibrate at its recommended value).\nNo = use the Table 3-9 value (CALREF is sent).\n'
                                            'Cancel = stop here.', icon='warning')
            if ans is None:
                self._abort_req = False
                return
            choose = 'meter' if ans else 'table'
        elif info['verdict'] == 'other':
            if not messagebox.askyesno('Unexpected recommended value', f'{info["text"]}\n\nAcknowledge and calibrate at the meter\'s value? (No = stop; use Abort if this is wrong.)', icon='warning'):
                return
            unexpected = True
        if st['characterize']:
            text = self.ask_value('Characterized value', f'{st["id"]}  {st["title"]}\n\nThe manual says this range needs the calibrator characterized (8508A). Enter the characterized value '
                                  f'(at most 6 significant digits, near {info["meter"]:g}); leave it empty to use the calibrator\'s nominal value.', '')
            if text is None:
                return
            if text.strip():
                characterized = text.strip()
            elif messagebox.askyesno('Waive characterization', 'Use the calibrator\'s nominal value without the characterization?', icon='warning'):
                waive = True
            else:
                return
        s.set_reference(st, choose=choose, characterized=characterized, waive=waive, unexpected_ack=unexpected)

    # ------------------------------------------------------------------ finish, abort
    def finish(self):
        s = self.session
        if s is None or not s.all_done():
            return
        self._begin()
        try:
            flags = s.finish()
        except Exception as exc:
            self.status.set('EXIT problem: ' + str(exc).splitlines()[0])
            messagebox.showerror('EXIT', str(exc))
            return
        finally:
            self._end()
        msg = 'The calibration mode was left (EXIT).' + (f' The meter reported: {", ".join(flags)}.' if flags else '')
        self.status.set(msg + ' Run the As Left performance verification.')
        messagebox.showinfo('Adjustment complete' + (' (DEMO)' if self.demo else ''), msg + '\n\nRun the As Left performance verification now and keep its report.' +
                            ('\n\nDEMO: this was a simulated meter; nothing was recorded as evidence.' if self.demo else ''))

    def abort(self, ask=True):
        s = self.session
        if s is None:
            return
        if self.busy and ask:
            self._abort_req = True
            self.status.set('Abort requested: stopping after the current wait.')
            return
        if ask and not messagebox.askyesno('Abort', 'Stop the adjustment? The calibrator goes to STANDBY and EXIT is sent. A function that is not complete shows CAL ERROR.', icon='warning'):
            return
        text = s.abort('operator')
        self._last_group = None
        self._end()
        self.status.set('Adjustment stopped.')
        messagebox.showinfo('Adjustment stopped', text)

    def disconnect(self):
        s = self.session
        if s and s.cal_mode:
            if not messagebox.askyesno('Calibration mode is OPEN', 'Abort the adjustment (EXIT is sent) and disconnect?', icon='warning'):
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
        if s and s.cal_mode:
            messagebox.showwarning('Calibration mode is open', 'Use "Abort" (or finish with EXIT) before closing.')
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
