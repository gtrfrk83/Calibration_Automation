"""Keysight Truevolt (34460A / 34461A / 34465A / 34470A) performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json, which was
extracted from the Keysight Truevolt Series DMM Operating and Service Guide, pp. 501-520 (tables pp. 504-520), using
the table for the model being tested. Default limits: 1 year. Instruments: the DMM (USB, GPIB, LAN or RS-232) and a
Fluke 5560A calibrator as the source. Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations
are required.

    import truevolt_verification
    truevolt_verification.main('34470A')       # what Procedures/Keysight_34470A_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in truevolt_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import procspec
import drivers
import appdata
import datamode
import procmods_engine
import manual_override
import reset_startup
import surprise
import virtualbench
import hookups

MODEL = SPEC_PATH = SPEC = POINTS = None
PERIODS = {'24 hours': '24h', '90 days': '90d', '1 year': '1y', '2 years': '2y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}


def configure(model):
    """Select the model: loads its spec (the model's own tables) and numbers the points."""
    global MODEL, SPEC_PATH, SPEC, POINTS
    MODEL = model
    SPEC_PATH = HERE / 'specs' / f'keysight_{model.lower()}_pv.json'
    SPEC = procspec.load(SPEC_PATH)
    POINTS = procspec.flatten(SPEC)
    procspec.apply_period(POINTS, SPEC['default_period'])


def to_visa(text):
    """'COM9' / '9' -> 'ASRL9::INSTR'; anything that already looks like a VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (USB0::...::INSTR, GPIB0::22::INSTR).')
    return f'ASRL{int(t)}::INSTR'


class IO(manual_override.ReadGuardMixin, reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the DMM under test and the Fluke 5560A, both through the instrument drivers."""
    SETTLE_AC = {3: 9.0, 20: 5.0, 200: 4.0}

    def __init__(self, dmm_address, cal_address, cal_baud=9600, transports=None, mods=None, virtual=False, surprise_handler=None):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        if transports:
            dmm_t, cal_t = transports
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address), timeout=20)
            cal_t = drivers.open_visa(to_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = getattr(drivers, f'Keysight{MODEL}')(dmm_t, self.log, label=MODEL)
        self.cal = drivers.Fluke5560A(cal_t, self.log, label='5560A')
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.dmm.idn
        self.guards = []
        if surprise_handler is not None:
            self.enable_surprise(surprise_handler)

    def enable_surprise(self, handler, force=False):
        """Stop on surprise (surprise.py, opt-in; wired here at the engine level, no driver edited).  handler(Surprise) -> True = Continue; it must have
        been made on the Tk thread (surprise.tk_handler).  A reply that is empty / a prompt character / not a number for READ?, or a query that times
        out twice, is a Stop-only surprise; the DMM's error queue after CONF / NPLC / BAND is a Stop / Continue surprise; the calibrator's error
        queue after an output is a Stop-only surprise (the output is never operated after a refusal).  No write is ever repeated.  A virtual (demo)
        command log is left alone unless force=True (tests), so the simulated bench never prompts."""
        self.guards = [g for g in (surprise.attach_guard(self.dmm, handler, force, expect={'read': 'float'}, stop_only=True),
                                   surprise.attach_guard(self.cal, handler, force, stop_only=True)) if g]
        return self.guards

    def reset_roles(self):
        return [self.cal], [self.dmm]

    def pm_drivers(self):
        return (self.dmm, self.cal)

    def standby(self):
        self.cal.standby_quiet()

    def close(self):
        try: self.standby()
        except Exception: pass
        for obj in (self.dmm, self.cal):
            try: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (a virtual demo session writes nothing)."""
        if virtualbench.log_is_virtual(self.log): return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def check_terminals(self, p):
        if not SPEC.get('front_rear_switch', True):      # 34460A: one set of terminals, no Front/Rear switch
            return
        want = 'REAR' if p['terminal'] == 'REAR' else 'FRONT'
        have = self.dmm.front_rear()
        if have != want:
            raise drivers.InstrumentError(f'The Front/Rear switch is on {have}; this point needs {want}. Move the switch and rerun.')

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['kind'] == 'FREQ': return self.pm_param('truevolt.settle.freq', 3.0)
        if p['kind'] in ('ACV', 'ACI'):
            f = p.get('filter_hz') or 200
            return self.pm_param(f'truevolt.settle.ac_{int(f)}hz', self.SETTLE_AC[f]) if f in self.SETTLE_AC else self.pm_param('truevolt.settle.ac_other', 4.0)
        if p['kind'] in ('OHM2', 'OHM4') and p['range'] >= 1e7: return self.pm_param('truevolt.settle.ohm_high', 4.0)
        return self.pm_param('truevolt.settle.default', 2.0)

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        self.check_terminals(p)
        self.dmm.configure_point(p)
        surprise.checked(self.dmm, self.dmm.check_errors, 'configuring ' + p['description'])       # no guard: exactly dmm.check_errors(...)
        if p['source'] == 'none':          # copper short / open input: the calibrator stays in STANDBY
            time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('truevolt.settle.zero', 1.5), self.virtual))
            return self._read()
        if p['source'] == 'manual':        # e.g. a capacitance standard connected by the technician
            time.sleep(virtualbench.scaled(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('truevolt.settle.manual', 2.0), self.virtual))
            return self._read()
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
        elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
        elif k in ('OHM2', 'OHM4'): self.cal.set_output_ohms(v)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)
        surprise.checked(self.cal, self.cal.check_error, p['description'], stop_only=True)   # the calibrator refuses outputs it cannot make; never operate then (so no Continue)
        self.cal.operate_unverified()
        time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
        reading = self._read()
        self.standby()
        return reading


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # owner request: type a reading instead of the automatic one (manual_override.py)
    WIRING_TEXT = {
        'VOLT': 'Calibrator voltage output to the DMM front HI / LO input terminals.',
        'CURRENT': 'Calibrator current output to the DMM front current (A) input and LO. Check the fuse and current rating first.',
        'RES4': '4-wire: calibrator force and sense leads to the DMM HI/LO and HI/LO SENSE terminals.',
        'RES2': '2-wire: calibrator resistance leads to the DMM HI / LO input terminals.',
    }

    def __init__(self, root, model, demo=False, fast_demo=False):
        configure(model)
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('truevolt', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(MODEL)
        self.asset = port.var(); self.serial = port.var()
        self.dmm_addr = port.var(self.settings.get('dmm_addr', 'USB0::0x2A8D::0x0101::MY00000000::INSTR'))
        self.cal_addr = port.var(self.settings.get('cal_addr', 'COM9'))
        self.cal_baud = port.var(self.settings.get('cal_baud', '9600'))
        self.period = port.var(self.settings.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.test_set = port.var('Full verification')
        self.include_optional = port.var(False, 'bool')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: enter the instrument addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    def active(self, p):
        if p['optional'] and not self.include_optional.get(): return False
        if p.get('skip'): return False                               # a point skipped by a procedure modification
        if self.test_set.get().startswith('Quick') and not p['quick']: return False
        return True

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    VIEW = 'truevolt_view'                               # window code: truevolt_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

    def pm_driver_classes(self): return (getattr(drivers, f'Keysight{MODEL}'), drivers.Fluke5560A)

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated import make_dmm_bench

        def build(mods):
            _bench, ft, dt = make_dmm_bench(MODEL)
            dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'          # the Front/Rear switch the technician would set
            return IO('sim', 'sim', transports=(dt, ft), mods=mods)
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p))

    # ------------------------------------------------------------------ table
    def _visible(self, p):
        if not self.active(p): return False
        res = self.results.get(str(p['id']), {}).get('result', '')
        sec = self.show_section.get(); st = self.show_status.get()
        if sec != 'All sections' and p['section_title'] != sec: return False
        if st == 'Not tested' and res: return False
        if st == 'Passed' and res != 'PASS': return False
        if st == 'Failed (OOT)' and res != 'FAIL': return False
        if not self.status_visible(str(p['id']), st): return False
        return True

    def _row(self, p):
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'])
        return (p['id'], p['description'] + (' ★' if p['quick'] else ''), *cells), tags

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((str(p['id']), *self._row(p)) for p in POINTS if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.ui_view.table_has(self, iid):
            values, tags = self._row(p); self.ui_view.table_update_row(self, iid, values, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections([p for p in POINTS if self.active(p)], lambda p: p['section_title'])

    def on_period(self, save=True):
        self.pm_revert(POINTS)                                       # limits come from the period table: take the modifications off,
        procspec.apply_period(POINTS, PERIODS[self.period.get()])
        self.pm_apply(POINTS)                                        # then put them back (they only apply if they fit this period)
        for records in (self.found, self.left):     # re-judge stored readings (As Found and As Left) against the newly selected limits
            for key, rec in records.items():
                p = POINTS[int(key) - 1]
                rec['result'] = 'PASS' if abs(rec['reading'] - p['nominal']) <= p['error'] else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        typical = '  |  Typical value (range calibrated internally).' if p.get('typical') else ''
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}{typical}{extra}\n'
                        f'Setup: {self.setup_text(p)}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        if p['source'] == 'none':
            return ('Select the %s terminals; leave the input OPEN (no calibrator).' if p['input'] == 'open'
                    else 'Select the %s terminals; install the low-thermal copper short.') % p['terminal'] + ' The calibrator stays in STANDBY.'
        if p['source'] == 'manual': return p['setup']
        key = procspec.wiring_key(p)[2]
        text = self.WIRING_TEXT[key]
        if p['kind'] == 'FREQ': text = 'Calibrator AC voltage output at the stated level and frequency to the DMM HI / LO terminals.'
        if p['terminal'] == 'FRONT_10A': text = 'Calibrator high-current output to the DMM front 10 A terminal and LO.'
        return text

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        self.ui_view.set_choices(self, 'dmm', found); self.ui_view.set_choices(self, 'cal', found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over a simulated DMM and calibrator
                self._vb = virtualbench.dmm_pair(MODEL)
                self.io = IO('virtual', 'virtual', 9600, transports=(self._vb[2], self._vb[1]), mods=self.pm_state, virtual=True)
            else: self.io = IO(self.dmm_addr.get(), self.cal_addr.get(), int(self.cal_baud.get()), mods=self.pm_state, surprise_handler=self._surprise_handler())
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'{MODEL}: {self.io.ident}\nFluke 5560A: {self.io.cal.idn}{tag}\nCalibrator output is not enabled.')

    def _surprise_handler(self):
        """The Stop / Continue dialog for stop-on-surprise, made ON the Tk thread (here: the Test connections / Run handler), once per window.
        None in demo (virtual or fast): the simulated bench never prompts."""
        if self.demo or self.fast_demo: return None
        if getattr(self, '_sp_handler', None) is None: self._sp_handler = port.surprise_handler(self.root)
        return self._sp_handler

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('dmm_addr', self.dmm_addr), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
            self.settings.set(key, var.get())
        self.settings.save()

    # ------------------------------------------------------------------ running
    def request_stop(self): self.stop = True; self.status.set('Stopping after current test point.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])
    def run_section(self): self.run_shown_section()

    def rerun(self):
        selected = self.ui_view.table_selection(self)
        if selected: self.execute([POINTS[int(selected[0]) - 1]])
        else: port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        selected = self.ui_view.table_selection(self)
        if selected: self.execute(self.points_from(POINTS, selected[0]))
        else: port.message('info', 'Selection', 'Select a test point first.')

    def mo_point(self, iid): return POINTS[int(iid) - 1]
    def mo_total(self): return len(POINTS)

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        self.mo_reset_run()
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def _hookup_image(self, p):
        """Drawn hook-up picture for this point's wiring (hookups.bench_image), else the supplied front-panel photo. Picture only: no step changes."""
        try:
            if p['source'] == 'none':
                return hookups.bench_image(MODEL, 'ZERO', terminal=p['terminal'], open_input=(p['input'] == 'open'))
            if p['source'] == 'manual':
                return hookups.panel_image(MODEL)
            group = procspec.wiring_key(p)[2]
            wiring = {'VOLT': 'VOLT', 'CURRENT': 'CURRENT', 'RES2': 'RES2', 'RES4': 'RES4'}[group]
            return hookups.bench_image(MODEL, wiring, terminal=p['terminal'], nominal=p['nominal'], rng=p.get('range'))
        except Exception:
            return hookups.panel_image(MODEL)

    def _prompt_setup(self, p):
        """Confirm the physical setup when the wiring group changes. Returns False if the technician cancels."""
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if p['source'] == 'none':
            self.io.standby()
            instruction = ('Leave the CURRENT input OPEN (nothing connected).' if p['input'] == 'open' else
                           'Install the low-thermal copper four-terminal SHORT across INPUT HI/LO and SENSE HI/LO (34172B or equivalent).')
            return port.operator_prompt('Zero offset — physical setup required', f'Zero-offset setup: {p["terminal"]} terminals',
                ([('Select terminals', f'Set the front-panel FRONT/REAR switch to {p["terminal"]}. The program checks the switch position before measuring.')]
                 if SPEC.get('front_rear_switch', True) else []) + [('Set up the input', instruction)],
                facts=facts, caution='The calibrator stays in STANDBY. Never use it as a zero source.', ok='Set up — measure', image=self._hookup_image(p), parent=self.root)
        if p['source'] == 'manual':
            return port.operator_prompt('Connect the standard', f'Connect for {p["section_title"]}',
                [('Connect', p['setup']), ('Stabilise', 'Allow the standard to settle before continuing.')],
                facts=facts, ok='Connected — measure', image=self._hookup_image(p), parent=self.root)
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {p["section_title"]}',
            [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p)),
             ] + ([('Switch', 'Front/Rear switch on FRONT.' if p['terminal'] != 'REAR' else 'Front/Rear switch on REAR.')] if SPEC.get('front_rear_switch', True) else []),
            facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified — continue', image=self._hookup_image(p), parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = procspec.wiring_key(p)
        if not self.fast_demo and key != previous and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.fast_demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= 500:
            if not port.ask_yes_no('HIGH VOLTAGE', f'This point outputs {p["nominal"]:g} V. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        self.mo_begin(p)                               # the point being measured: 'Enter reading manually' applies to it
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.virtual: virtualbench.operator_sets_up(self._vb, p, terminal=p.get('terminal'), manual=p['source'] == 'manual', nominal=p['nominal'])     # the virtual operator does what the prompt asked
        if self.fast_demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self.mo_finish(p, reading, True, lambda: self._record(p, reading, True)); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    if isinstance(err, manual_override.ReadingUnavailable): port.post(self.root, lambda err=err: self._reading_failed(points, i, p, key, err))     # the automatic reading failed: a typed one may replace it
                    else: port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key):
        self.mo_finish(p, reading, bool(self.demo), lambda: self._record(p, reading, bool(self.demo))); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _reading_failed(self, points, i, p, key, exc):
        """The meter could not be read (timeout, unreadable, overload). The calibrator is already in standby: a typed reading (manual_override) lets the run go on, else stop as before."""
        if not self.mo_recover(p, exc): self._error(exc); return
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.mo_reset_run()
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, extra=None):
        result = 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields(), **(extra or {}))
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(),
                                        **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get())); self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title'] + (' - ' + p['terminal'].title() if p['section'] == 'zero' else '')
    @staticmethod
    def report_mixed(p):
        return p['section'] in ('hi',)
    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]
    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        import report_pdf
        rows=[];pts=[]
        for p in POINTS:
            row=self.found_left_row(p,lambda r:report_pdf.point_row(p,r['reading'],r['result']=='FAIL',section=self.report_section(p),mixed=self.report_mixed(p),standard='5560A'))
            if row:rows.append(row);pts.append(p)
        return rows,pts
    def export_pdf(self):
        rows,pts=self.certificate_rows_and_points()
        if not rows:port.message('info', 'No results','No recorded results to export yet.');return
        try:import report_pdf
        except ImportError as exc:port.message('error', 'Report export',str(exc));return
        details=port.report_details(f'Keysight {MODEL} performance verification', parent=self.root)
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=port.save_file(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows=report_pdf.apply_tar_tur(rows,details.get('show_tar_tur'),[tartur_wiring.point_fields(p,'5560A') for p in pts])
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument',f'Keysight {MODEL}'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Limits applied',self.period.get()),('Source',f'Keysight Truevolt Operating and Service Guide, pp. 501-520 ({MODEL} tables)')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows,'5560A'),snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            port.message('error', 'PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); port.close(self.root)


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, model, demo=demo, fast_demo=fast)
    port.run_app(build)
