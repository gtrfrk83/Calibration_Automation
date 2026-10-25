"""Fluke 8808A guided ADJUSTMENT (calibration), window.  The logic is fluke8808a_adjustment.py (no tkinter), the steps are specs/fluke_8808a_adjustment.json.

THIS CHANGES THE CALIBRATION OF THE INSTRUMENT.  Method: the RS-232 calibration dialog of the Fluke 8808A Calibration Manual (Oct 2008), pp. 3-16 / 3-17, Table 3-9 (124 steps).
The manual has no password, save, lock or date command: the points are the whole procedure.  Every function started must be completed; every point is confirmed by you.
Demo (virtual instruments, nothing persisted):  python Procedures/Fluke_8808A_Adjustment.py --demo
"""
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))   # shared modules sit next to the Manager
import adjustment_audit
import calibrator_fit
import drivers
import fluke8808a_adjustment as adj
import reset_startup
import ui_port
import ui_theme as ui                   # only its toolkit-free helpers here (Settings); the window code is in fluke8808a_adjust_view_tk.py
import virtualbench
from ui_port import ui as port          # every dialog, variable and window operation goes through the UI port (ui_port.py)

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
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('Fluke8808AAdjustment')
        s = self.settings
        self.asset, self.serial, self.tech = port.var(), port.var(), port.var()
        self.scope = port.var(s.get('scope', next(iter(adj.SCOPES))))
        if self.scope.get() not in adj.SCOPES:
            self.scope.set(next(iter(adj.SCOPES)))
        self.dmm_addr = port.var(s.get('dmm_addr', 'COM3'))
        self.dmm_baud = port.var(s.get('dmm_baud', '9600'))
        self.dmm_fmt = port.var(s.get('dmm_fmt', next(iter(adj.PARITY_FORMATS))))
        self.offers = {n: calibrator_fit.make_offer(k, adj.requests(), per_point_manual=True, unverified=(cls.unverified_summary() if hasattr(cls, 'unverified_summary') else ''), name=n) for n, (k, cls) in adj.CALIBRATORS.items()}
        self.cal_model = port.var(s.get('cal_model', 'Fluke 5522A'))
        if self.cal_model.get() not in adj.CALIBRATORS:
            self.cal_model.set('Fluke 5522A')
        self.cal_interface = port.var(s.get('cal_interface', adj.CAL_INTERFACES[0]))
        if self.cal_interface.get() not in adj.CAL_INTERFACES:
            self.cal_interface.set(adj.CAL_INTERFACES[0])
        self.cal_addr = port.var(s.get('cal_addr', adj.CAL_PORT_DEFAULT[self.cal_interface.get()]))
        self.cal_baud = port.var(s.get('cal_baud', '9600'))
        self.use_ter = port.var(False, 'bool')         # optional, UNVERIFIED: also send *TER once (off by default)
        self.status = port.var()
        self.next_hint = port.var()
        self.cal_note = port.var()
        self._build_ui()
        self._fill_table()
        self.on_cal_model()
        self.status.set('DEMO MODE (virtual instruments): commands go to a simulated 8808A and calibrator; nothing is recorded as evidence.' if demo
                        else 'Enter the instrument ID, choose the ports and press Connect.')
        self._sync()
        port.on_close(root, self.on_close)

    # ------------------------------------------------------------------ layout
    VIEW = 'fluke8808a_adjust_view'                      # the toolkit's window code: fluke8808a_adjust_view_tk (Tk), later _qt

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    def _toggle_log(self): self.ui_view.toggle_log(self)

    def on_cal_model(self):
        offer = self.offers[self.cal_model.get()]
        self.ui_view.cal_tooltip(self, offer.tooltip)
        self.cal_note.set(offer.text + ('  Own standard needed at: ' + ', '.join(sorted(adj.own_standard_ids(adj.CALIBRATORS[self.cal_model.get()][0]))) + '.'
                                        if adj.own_standard_ids(adj.CALIBRATORS[self.cal_model.get()][0]) else ''))

    # ------------------------------------------------------------------ table / state
    @property
    def scope_t(self):
        return adj.SCOPES[self.scope.get()]

    def _fill_table(self):
        self.ui_view.table_clear(self)
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
            self.ui_view.table_add(self, st['id'], (st['id'], st['function'], st['title'], out, state), tags)

    def _sync(self):
        s = self.session
        live = self.io is not None
        open_ = bool(s and s.cal_mode)
        self.ui_view.sync_pills(self, live, open_)
        finished = bool(s and (s.aborted or s.finished))
        idle = not self.busy
        self.ui_view.sync_buttons(self, not live and idle, live and not (s and not finished) and idle, bool(s) and not open_ and not finished and idle,
                                  open_ and not s.all_done() and idle, open_ and s.all_done() and s.active_function is None and idle,
                                  bool(open_ or (s and not finished and any(r.attempts for r in s.records.values()))), live and idle, bool(s and not finished))
        if not live:
            hint = 'Enter the instrument ID, choose the ports and press Connect.'
        elif s is None or finished:
            hint = 'Enter instrument ID, serial number and technician, then press "Start adjustment record" (this resets both instruments; the calibration is not touched).'
        elif not open_:
            hint = 'Press "Calibration mode entered": you confirm warm-up, the As Found verification and your authority, then enter the calibration mode at the front panel (calibration button) and confirm.'
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
        self.ui_view.log_add(self, (t, step_id, action, outcome, detail), (tag,) if tag else ())

    # ------------------------------------------------------------------ waiting without freezing
    def pump(self, seconds, what):
        end = time.monotonic() + seconds
        while not self._abort_req:
            left = end - time.monotonic()
            if left <= 0:
                break
            self.status.set(f'{what}: {left:.0f} s')
            port.update(self.root)
            time.sleep(0.05)

    def _begin(self):
        self.busy, self._abort_req = True, False
        self._sync()
        port.flush(self.root)

    def _end(self):
        self.busy = False
        self._fill_table()
        self._sync()

    # ------------------------------------------------------------------ connect
    def connect(self):
        if not self.asset.get().strip():
            port.message('warning', 'Instrument ID', 'Enter the instrument ID first.')
            return
        self.status.set('Connecting ...')
        port.flush(self.root)
        try:
            self.io = self._new_io()
        except Exception as exc:
            self.io = None
            self.status.set('Connection error: ' + str(exc).splitlines()[0])
            port.message('error', 'Connection error', str(exc))
            self._sync()
            return
        self.io.dmm.tick = lambda: port.update(self.root)
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
            port.message('warning', 'Required information', 'Enter instrument ID, serial number and technician.')
            return
        if self.io is None:
            return
        notes = [('Method', 'The RS-232 calibration dialog in the order of Table 3-9. Both instruments are reset to their defaults first; the calibration mode stays closed.'),
                 ('Scope', self.scope.get()), ('Calibrator', f'{self.cal_model.get()}: ' + self.offers[self.cal_model.get()].text)]
        if not port.operator_prompt('Start adjustment record', 'Start a new adjustment record?', [('Nothing is changed yet', 'Starting resets the instruments; no calibration command is sent.'),
                                ('Verification', 'This program does not run the performance verification: do the As Found one first, the As Left one afterwards.')],
                                facts=notes, caution='This procedure adjusts the calibration of the 8808A.', ok='Start record', parent=self.root):
            return
        self._begin()
        try:
            self.audit.start_run(adj.INSTRUMENT, self.asset.get().strip(), self.serial.get().strip(), self.tech.get().strip(), uut_idn=self.io.ident,
                                 calibrator=self.cal_model.get(), scope='+'.join(self.scope_t))
            wait = (lambda sec: self.pump(sec, 'Settling'))
            self.session = adj.Session(self.io, self.audit, scope=self.scope_t, wait=wait, scale=virtualbench.WAIT_SCALE if self.virtual else 1.0)
            self.session.on_log = self._audit_row
            self.ui_view.log_clear(self)
            self.session.log('RUN_STARTED', 'OK', f'{adj.INSTRUMENT} {self.io.ident}; calibrator {self.cal_model.get()}' + (' [DEMO: nothing saved]' if self.demo else ''))
            try:
                self.session.reset(confirm=lambda t: port.ask_ok_cancel('Reset instruments', t, icon='warning'))
            except reset_startup.ResetDeclined:
                self.session.log('RESET', 'CANCELLED', 'declined by the operator; nothing was touched')
                self.session = None
                self.status.set('Not started: the reset was declined (nothing was touched).')
                return
            except reset_startup.ResetFailed as exc:
                self.session.log('RESET', 'FAILED', 'run not started')
                self.session = None
                self.status.set('Reset failed - not started.')
                port.message('error', 'Reset failed - not started', exc.report.failure_text() if hasattr(exc.report, 'failure_text') else str(exc))
                return
            self.session.prepare()
        except Exception as exc:
            if self.session:
                self.session.log('START', 'FAILED', str(exc).splitlines()[0])
            self.session = None
            self.status.set('Not started: ' + str(exc).splitlines()[0])
            port.message('error', 'Not started', str(exc))
            return
        finally:
            self._end()
        self.status.set(f'Adjustment record active ({self.audit.run_id}); the calibration mode is closed and nothing has been changed.')

    # ------------------------------------------------------------------ the calibration mode
    def enter_calibration(self):
        s = self.session
        if s is None or s.cal_mode:
            return
        ok = port.operator_prompt('Before the adjustment', 'Warm-up, conditions and As Found',
            [('Warm-up', 'The 8808A must have warmed up for at least one half hour (Calibration Manual p. 1-9); allow the calibrator its own warm-up.'),
             ('Environment', 'Ambient conditions as the manual requires (p. 3-2).'),
             ('As Found', 'The performance verification (As Found) has been run and its report kept.'),
             ('Calibration mode', 'NEXT you enter the calibration mode yourself, at the front panel of the 8808A, with the calibration button. This program does not enter it for you.')],
            facts=[('Instrument', f'{self.asset.get().strip()}  (serial {self.serial.get().strip()})'), ('Calibrator', self.cal_model.get())],
            caution='Next you confirm your authority.', ok='All confirmed', parent=self.root)
        if not ok:
            self.status.set('Not entered: conditions were not confirmed.')
            return
        s.acknowledge('conditions', 'warm-up and environment confirmed')
        s.acknowledge('as_found', 'As Found performance verification done')
        if not port.ask_yes_no('THIS CHANGES THE INSTRUMENT CALIBRATION',
                                   'I am authorised to adjust this instrument and understand that every point I start changes the calibration of the 8808A. There is no SAVE and no way '
                                   'to undo a point; a function that is started must be completed.\n\nContinue?', icon='warning'):
            self.status.set('Not entered.')
            return
        s.acknowledge('authorised', 'operator authorised to adjust')
        s.acknowledge('notice', 'calibration-change notice acknowledged')
        use_ter = bool(self.use_ter.get())
        if not port.operator_prompt('Operator step: enter calibration mode', 'Enter the calibration mode at the front panel',
                                [('Front panel', 'Enter calibration mode on the front panel of the 8808A using the calibration button, then confirm here.'),
                                 ('What the program can check', 'The manual prints no query that shows the calibration mode, so the program cannot verify it before the first function. ' +
                                  'It will send the first function name only after you confirm; if the meter does not answer it with a recommended value, nothing has been changed and you stop.')]
                                + ([('*TER (optional)', '*TER will ALSO be sent once after you confirm (UNVERIFIED: the manual shows it as the RS-232 entry, p. 3-16, but does not say whether it works without the front-panel entry).')] if use_ter else []),
                                facts=[('Instrument', f'{self.asset.get().strip()}  (serial {self.serial.get().strip()})')],
                                caution='Confirm only when the meter is in the calibration mode.', ok='Calibration mode entered - continue', parent=self.root):
            self.status.set('Not entered: the front-panel entry was not confirmed.')
            return
        s.acknowledge('panel', 'operator entered the calibration mode at the front panel (calibration button)')
        if self.virtual:
            self.io.dmm.t.enter_panel()                       # demo only: the simulated meter 'is put' in the calibration mode as the operator would at the panel
        self._begin()
        try:
            s.enter_calibration(use_ter=use_ter)
        except Exception as exc:
            self.status.set('Not entered: ' + str(exc).splitlines()[0])
            port.message('error', 'Calibration mode not entered', str(exc))
            return
        finally:
            self._end()
        self.status.set('Calibration mode confirmed by you (not verifiable by the program until the first function). Press "Run next point".')

    # ------------------------------------------------------------------ one point
    def ask_value(self, title, prompt, default):
        """The value-entry window (a custom dialog of the UI port)."""
        return port.ask_value(title, prompt, default, parent=self.root)

    def _hookup(self, st):
        s = self.session
        group = st['group']
        facts = [('Step', f'{st["id"]}  {st["function"]}  {st["title"]}'), ('Calibrator output', adj.source_text(st)), ('Manual page', st['page'])]
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', adj.hookup_text(st, s.cal_key))]
        return port.operator_prompt('Rewire / verify before the point', f'Connect for {adj.GROUP_TITLE.get(group, group)}', steps, facts=facts,
                                caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', parent=self.root)

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
            shows = port.ask_yes_no('CALREF not confirmed', f'{exc}\n\nDoes the meter display show the value that was sent?', icon='warning')
            try:
                if not s.confirm_calref_display(st, shows):
                    self._abort_req = True
            except Exception as exc2:
                port.message('error', 'Point stopped', str(exc2))
        except adj.cal_driver.CalibrationError as exc:
            if s.entry_failed and not s.entry_verified:
                self._offer_ter(s, exc)
            else:
                self.status.set(f'{st["id"]}: ' + str(exc).splitlines()[0])
                port.message('error', f'Point {st["id"]} stopped', f'{exc}\n\nNothing was repeated automatically. You can repeat the point after fixing the cause, or abort.')
                self._last_group = None
        except Exception as exc:
            self.status.set(f'{st["id"]}: ' + str(exc).splitlines()[0])
            port.message('error', f'Point {st["id"]} stopped', f'{exc}\n\nNothing was repeated automatically. You can repeat the point after fixing the cause, or abort.')
            self._last_group = None
        finally:
            try:
                if s.source_on is not None:
                    self.io.standby()
                    s.source_on = None
            except Exception:
                port.message('error', 'Calibrator', 'The calibrator could not be confirmed in STANDBY. Check its front panel before touching any lead.')
            self._end()
        if self._abort_req:
            self._abort_req = False
            self.abort(ask=False)

    def _offer_ter(self, s, exc):
        """The meter did not answer the first function name with a recommended value. ONE retry is allowed, only on the operator's explicit confirmation: the manual's RS-232 entry command *TER (UNVERIFIED)."""
        if s.ter_attempted or s.must_stop:
            port.message('error', 'Calibration mode not entered', f'{exc}\n\nThe single *TER attempt was already used. Stopping: nothing more is sent. Check the meter and the front-panel entry, then start again.')
            self._abort_req = True
            return
        if not port.ask_yes_no('Meter did not enter calibration mode - try *TER once? (UNVERIFIED)',
                                   f'{exc}\n\nThe 8808A did not answer the function name with a recommended value, so it is probably not in the calibration mode.\n\n'
                                   'You may try ONE entry over RS-232 with the manual\'s command *TER (p. 3-16). This is UNVERIFIED: the manual does not say whether *TER works after, or instead of, the front-panel '
                                   'entry. It is sent ONCE; if it does not work the adjustment stops, and nothing else is sent by the program. The function name is only sent again when you confirm the next '
                                   'function start.\n\nSend *TER once?', icon='warning'):
            self.status.set('*TER not sent: stopping.')
            self._abort_req = True
            return
        try:
            s.retry_entry_with_ter(confirmed=True)
        except Exception as exc2:
            self.status.set('*TER did not enter the calibration mode: stopping.')
            port.message('error', '*TER did not work', f'{exc2}\n\nStopping. Nothing else is sent.')
            self._abort_req = True
            return
        self.status.set('*TER sent once (UNVERIFIED) and the banner came back. Press "Run next point" to start the function again.')

    def _run_step(self, s, st, rec):
        rerun = False
        if rec.indeterminate:
            if port.ask_yes_no('No completion answer', f'{st["id"]} {st["title"]}: the 8808A did not say the point was finished.\n\nRead what the meter has sent since (read-only, nothing is sent)?',
                                   icon='warning'):
                got = s.recheck_indeterminate(st)
                self.status.set(f'{st["id"]}: ' + ('completion arrived late.' if got else 'still no answer: look at the display (flashing star = calibrating) or abort.'))
            return
        if rec.failed:
            if not port.ask_yes_no('Repeat a failed point', f'{st["id"]} {st["title"]} failed before ({" | ".join(rec.errors) or "error"}).\n\nRepeat it with a fresh confirmation? '
                                       'The program never repeats a command by itself.', icon='warning'):
                return
            rerun = True
        if not s.active_function:
            n = len(adj.function_steps(st['function']))
            if not port.ask_yes_no('Start a function', f'Start {st["function"]} ({adj.FUNCTION_BY_ID[st["function"]]["title"]})?\n\nOnce a function is selected ALL its {n} points must be '
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
            port.message('warning', 'Terminal', warn)
        if self._last_group != st['group'] or rerun or st['zero']:
            self.io.standby()
            if not self._hookup(st):
                self.status.set('Paused for wiring (the value is already confirmed; press Run next point to continue).')
                return
            s.mark_hookup(st)
            self._last_group = st['group']
        if st['id'] in adj.own_standard_ids(s.cal_key):
            if st['id'] not in s.own_ack:
                if not port.ask_yes_no('Own standard', f'{st["id"]}: {adj.source_text(st)}\n\nThe {self.cal_model.get()} cannot make this output ({adj.own_standard_reasons(s.cal_key).get(st["id"], "")}).\n'
                                           'Connect your own standard, set it, and confirm it is stable. The meter is not read, so you vouch for the value.', icon='warning'):
                    return
                s.acknowledge_own_standard(st)
        elif adj.is_hv(st, s.records[st['id']].output_value) or adj.is_high_current(st, s.records[st['id']].output_value):
            if s.hv_group != st['group']:
                if not port.ask_yes_no('HIGH VOLTAGE / CURRENT', f'This hook-up group outputs up to {adj.source_text(st)}. Verify CAT-rated leads, connections, clearance and '
                                           'personnel safety, and the fuse of the terminal in use. Enable the output?', icon='warning'):
                    return
                s.acknowledge_hv(st)
        s.program_source(st)
        if self._abort_req:
            return
        value_text = adj.si_text(rec.output_value, st['point']['unit']) if rec.output_value is not None else adj.point_text(st)
        if not port.ask_yes_no('Start the point', f'{st["id"]}  {st["function"]}  {st["title"]}\n\nMeter recommended value: {s.rec.raw if s.rec else ""}\nCalibrator: {adj.source_text(st)} (OPERATE, settled)'
                                   f'{chr(10) + "CALREF " + rec.calref if rec.calref else ""}\n\nStarting the point CHANGES the calibration of the 8808A (no undo, no save step). The Enter key '
                                   'is sent ONCE.\n\nIs the input stable? Start the point?', icon='warning'):
            self.io.standby()
            s.source_on = None
            self.status.set(f'{st["id"]}: not started (the value stays confirmed; press Run next point).')
            return
        self.status.set(f'{st["id"]}: calibrating ... (waiting for the 8808A)')
        port.update(self.root)
        try:
            s.send_point(st, confirmed=True, rerun_ack=rerun)
        except adj.cal_driver.StepIndeterminate as exc:
            port.message('warning', 'No completion answer', f'{exc}\n\nThe Enter key was NOT sent again. Press "Run next point" to decide.')
            self.status.set(f'{st["id"]}: completion not confirmed.')
            return
        except adj.cal_driver.CalibrationError as exc:
            self._last_group = None
            self.status.set(f'{st["id"]}: the 8808A reported an error.')
            port.message('error', 'Calibration point failed', f'{exc}\n\nNothing was repeated.')
            return
        self.status.set(f'{st["id"]} {st["function"]} {value_text}: done.')

    def _decide_value(self, s, st, rec):
        """Compare the meter's recommended value with the manual and confirm it (CALREF where needed, then the first Enter)."""
        info = s.review(st)
        choose, unexpected, characterized, waive = 'meter', False, None, False
        if info['verdict'] == 'list':
            ans = port.ask_yes_no_cancel('Meter and Table 3-9 differ', f'{info["text"]}\n\nYes = follow the METER (calibrate at its recommended value).\nNo = use the Table 3-9 value (CALREF is sent).\n'
                                            'Cancel = stop here.', icon='warning')
            if ans is None:
                self._abort_req = False
                return
            choose = 'meter' if ans else 'table'
        elif info['verdict'] == 'other':
            if not port.ask_yes_no('Unexpected recommended value', f'{info["text"]}\n\nAcknowledge and calibrate at the meter\'s value? (No = stop; use Abort if this is wrong.)', icon='warning'):
                return
            unexpected = True
        if st['characterize']:
            text = self.ask_value('Characterized value', f'{st["id"]}  {st["title"]}\n\nThe manual says this range needs the calibrator characterized (it names an 8508A; this lab uses the Keysight 3458A). Enter the value measured with the 3458A (recorded in the audit log as source "3458A characterised") '
                                  f'(at most 6 significant digits, near {info["meter"]:g}); leave it empty to use the calibrator\'s nominal value.', '')
            if text is None:
                return
            if text.strip():
                characterized = text.strip()
            elif port.ask_yes_no('Waive characterization', 'Use the calibrator\'s nominal value without the characterization?', icon='warning'):
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
            port.message('error', 'EXIT', str(exc))
            return
        finally:
            self._end()
        msg = 'The calibration mode was left (EXIT). If the meter still shows it, press the SHIFT key at the front panel (owner-stated, not from the manual pages read).' + (f' The meter reported: {", ".join(flags)}.' if flags else '')
        self.status.set(msg + ' Run the As Left performance verification.')
        port.message('info', 'Adjustment complete' + (' (DEMO)' if self.demo else ''), msg + '\n\nRun the As Left performance verification now and keep its report.' +
                            ('\n\nDEMO: this was a simulated meter; nothing was recorded as evidence.' if self.demo else ''))

    def abort(self, ask=True):
        s = self.session
        if s is None:
            return
        if self.busy and ask:
            self._abort_req = True
            self.status.set('Abort requested: stopping after the current wait.')
            return
        if ask and not port.ask_yes_no('Abort', 'Stop the adjustment? The calibrator goes to STANDBY and EXIT is sent. A function that is not complete shows CAL ERROR.', icon='warning'):
            return
        text = s.abort('operator')
        self._last_group = None
        self._end()
        self.status.set('Adjustment stopped.')
        port.message('info', 'Adjustment stopped', text)

    def disconnect(self):
        s = self.session
        if s and s.cal_mode:
            if not port.ask_yes_no('Calibration mode is OPEN', 'Abort the adjustment (EXIT is sent) and disconnect?', icon='warning'):
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
            port.message('warning', 'Calibration mode is open', 'Use "Abort" (or finish with EXIT) before closing.')
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
            port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    demo, _fast = virtualbench.flags(argv)
    port.enable_hidpi()
    port.run_app(lambda root: App(root, demo=demo))


if __name__ == '__main__':
    main()
