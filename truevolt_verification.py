"""Keysight Truevolt (34460A / 34461A / 34465A / 34470A) performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json, which was
extracted from the Keysight Truevolt Series DMM Operating and Service Guide, pp. 501-520 (tables pp. 504-520), using
the table for the model being tested. Default limits: 1 year. Instruments: the DMM (USB, GPIB, LAN or RS-232) and a
Fluke 5560A calibrator as the source. Hardware I/O is OFF in demo mode. Never run unattended: wiring confirmations
are required.

    import truevolt_verification
    truevolt_verification.main('34470A')       # what Procedures/Keysight_34470A_Verification.py does
"""
import json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_theme as ui
import ui_shell
import procspec
import drivers
import appdata
import datamode
import procmods_engine
import reset_startup

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


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the DMM under test and the Fluke 5560A, both through the instrument drivers."""
    SETTLE_AC = {3: 9.0, 20: 5.0, 200: 4.0}

    def __init__(self, dmm_address, cal_address, cal_baud=9600, transports=None, mods=None):
        self.log = drivers.CommandLog()
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
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt."""
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

    def measure(self, p):
        self.standby()
        self.check_terminals(p)
        self.dmm.configure_point(p)
        self.dmm.check_errors('configuring ' + p['description'])
        if p['source'] == 'none':          # copper short / open input: the calibrator stays in STANDBY
            time.sleep(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('truevolt.settle.zero', 1.5))
            return self.dmm.read()
        if p['source'] == 'manual':        # e.g. a capacitance standard connected by the technician
            time.sleep(p['settle_s'] if p.get('settle_s') is not None else self.pm_param('truevolt.settle.manual', 2.0))
            return self.dmm.read()
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
        elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
        elif k in ('OHM2', 'OHM4'): self.cal.set_output_ohms(v)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)
        self.cal.check_error(p['description'])   # the calibrator refuses outputs it cannot make; never operate then
        self.cal.operate_unverified()
        time.sleep(self.settle(p))
        reading = self.dmm.read()
        self.standby()
        return reading


class App(reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    WIRING_TEXT = {
        'VOLT': 'Calibrator voltage output to the DMM front HI / LO input terminals.',
        'CURRENT': 'Calibrator current output to the DMM front current (A) input and LO. Check the fuse and current rating first.',
        'RES4': '4-wire: calibrator force and sense leads to the DMM HI/LO and HI/LO SENSE terminals.',
        'RES2': '2-wire: calibrator resistance leads to the DMM HI / LO input terminals.',
    }

    def __init__(self, root, model, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('truevolt', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title(f'Keysight {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 820, min_w=900, min_h=640)
        self.settings = ui.Settings(MODEL)
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        self.dmm_addr = tk.StringVar(value=self.settings.get('dmm_addr', 'USB0::0x2A8D::0x0101::MY00000000::INSTR'))
        self.cal_addr = tk.StringVar(value=self.settings.get('cal_addr', 'COM9'))
        self.cal_baud = tk.StringVar(value=self.settings.get('cal_baud', '9600'))
        self.period = tk.StringVar(value=self.settings.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.test_set = tk.StringVar(value='Full verification')
        self.include_optional = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: enter the instrument addresses and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

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

    def _sync_buttons(self):
        idle = 'disabled' if self._busy else 'normal'
        for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
            b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in (self.period_combo, self.set_combo, self.opt_check):
            c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) else 'normal'))

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, f'Keysight {MODEL}  -  Performance Verification',
                                         f'Test points from the Keysight Truevolt Operating and Service Guide, pp. {SPEC["source"]["pages"].split(" ")[0]}  |  {len(POINTS)} points in the spec',
                                         demo=self.demo, on_section=self.pick_section, version='spec v1')
        self.status = sh.status_var
        self.conn_pill = sh.add_chip('Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')
        else: sh.notice('The program pauses and asks you to confirm the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.', 'info')

        # settings and connections live in the slide-in drawer
        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
        self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
        self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
        self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
        ttk.Label(d, text='Test set').grid(row=1, column=0, sticky='w', pady=4)
        self.set_combo = ttk.Combobox(d, textvariable=self.test_set, values=['Full verification', 'Quick check (Q points only)'], width=26, state='readonly')
        self.set_combo.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=4); self.set_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        self.opt_check = ttk.Checkbutton(d, text='Include optional capacitance test', variable=self.include_optional, command=self.refresh)
        self.opt_check.grid(row=2, column=0, columnspan=2, sticky='w', pady=(2, 10))
        ttk.Separator(d).grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        ttk.Label(d, text=f'{MODEL} address').grid(row=4, column=0, sticky='w', pady=4)
        self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, state='normal', width=34)
        self.dmm_entry.grid(row=4, column=1, sticky='ew', padx=(10, 0), pady=4)
        ttk.Label(d, text='Fluke 5560A').grid(row=5, column=0, sticky='w', pady=4)
        self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
        self.cal_entry.grid(row=5, column=1, sticky='ew', padx=(10, 0), pady=4)
        ttk.Label(d, text='Baud (5560A)').grid(row=6, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=6, column=1, sticky='w', padx=(10, 0), pady=4)
        btns = sh.drawer_footer
        self.btn_find = ttk.Button(btns, text='Find instruments', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
        self.btn_test = ttk.Button(btns, text='Test connections', command=self.test_connections, style='Accent.TButton'); self.btn_test.pack(side='left')
        ttk.Label(d, text='Examples: USB0::0x2A8D::0x0101::<serial>::INSTR   GPIB0::22::INSTR   TCPIP0::192.168.1.20::INSTR   COM9',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=8, column=0, columnspan=2, sticky='w', pady=(12, 0))

        self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
        self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
        self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
        self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
        sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
        self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
        sh.add_action('Save progress', self.save, side='right', short='Save')

        body = sh.content
        info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Label(info, textvariable=self.detail, wraplength=1000, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        ttk.Label(info, text=SPEC['source']['note'], style='Small.TLabel', wraplength=1000, justify='left').pack(anchor='w', pady=(4, 0))
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
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in POINTS:
            if self._visible(p):
                values, tags = self._row(p); self.tree.insert('', 'end', iid=str(p['id']), values=values, tags=tags)
        if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.tree.exists(iid):
            values, tags = self._row(p); self.tree.item(iid, values=values, tags=tags)
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
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        typical = '  |  Typical value (range calibrated internally).' if p.get('typical') else ''
        self.detail.set(f'{p["description"]}\nAcceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}{typical}{extra}\n'
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
        self.dmm_entry['values'] = found; self.cal_entry['values'] = found
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def test_connections(self):
        if self.demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect(); self.io = IO(self.dmm_addr.get(), self.cal_addr.get(), int(self.cal_baud.get()), mods=self.pm_state)
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        self.status.set('Connected: ' + self.io.ident + '. Calibrator output is NOT enabled.')
        messagebox.showinfo('Connected', f'{MODEL}: {self.io.ident}\nFluke 5560A: {self.io.cal.idn}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
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
        selected = self.tree.selection()
        if selected: self.execute([POINTS[int(selected[0]) - 1]])
        else: messagebox.showinfo('Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): messagebox.showwarning('Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None: return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def _prompt_setup(self, p):
        """Confirm the physical setup when the wiring group changes. Returns False if the technician cancels."""
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if p['source'] == 'none':
            self.io.standby()
            instruction = ('Leave the CURRENT input OPEN (nothing connected).' if p['input'] == 'open' else
                           'Install the low-thermal copper four-terminal SHORT across INPUT HI/LO and SENSE HI/LO (34172B or equivalent).')
            return ui.confirm_steps(self.root, 'Zero offset — physical setup required', f'Zero-offset setup: {p["terminal"]} terminals',
                ([('Select terminals', f'Set the front-panel FRONT/REAR switch to {p["terminal"]}. The program checks the switch position before measuring.')]
                 if SPEC.get('front_rear_switch', True) else []) + [('Set up the input', instruction)],
                facts=facts, caution='The calibrator stays in STANDBY. Never use it as a zero source.', ok='Set up — measure')
        if p['source'] == 'manual':
            return ui.confirm_steps(self.root, 'Connect the standard', f'Connect for {p["section_title"]}',
                [('Connect', p['setup']), ('Stabilise', 'Allow the standard to settle before continuing.')],
                facts=facts, ok='Connected — measure')
        return ui.confirm_steps(self.root, 'Rewire / verify before enabling output', f'Connect for {p["section_title"]}',
            [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p)),
             ] + ([('Switch', 'Front/Rear switch on FRONT.' if p['terminal'] != 'REAR' else 'Front/Rear switch on REAR.')] if SPEC.get('front_rear_switch', True) else []),
            facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified — continue')

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        key = procspec.wiring_key(p)
        if not self.demo and key != previous and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= 500:
            if not messagebox.askyesno('HIGH VOLTAGE', f'This point outputs {p["nominal"]:g} V. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.tree.exists(str(p['id'])): self.tree.selection_set(str(p['id'])); self.tree.see(str(p['id']))
        if self.demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self._record(p, reading, True); self.root.after(30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    self.root.after(0, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    self.root.after(0, lambda: self._error(exc))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key):
        self._record(p, reading, False); self.root.after(30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); messagebox.showerror('Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic):
        result = 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields())
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
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
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
        if not rows:messagebox.showinfo('No results','No recorded results to export yet.');return
        try:import report_pdf,report_dialog
        except ImportError as exc:messagebox.showerror('Report export',str(exc));return
        details=report_dialog.ask_details(self.root,f'Keysight {MODEL} performance verification')
        if details is None:return
        asset=''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path=filedialog.asksaveasfilename(defaultextension='.pdf',filetypes=[('PDF report','*.pdf')],initialfile=ui.report_filename(asset))
        if not path:return
        demo=self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows=report_pdf.apply_tar_tur(rows,details.get('show_tar_tur'),[tartur_wiring.point_fields(p,'5560A') for p in pts])
            report_pdf.write_calibration_pdf(path,rows,header=[('Instrument',f'Keysight {MODEL}'),('Instrument ID',self.asset.get()),('Serial',self.serial.get()),('Limits applied',self.period.get()),('Source',f'Keysight Truevolt Operating and Service Guide, pp. 501-520 ({MODEL} tables)')],demo=demo,details=details,footer_note=report_pdf.uncertainty_note(rows,'5560A'),snapshot_context=report_pdf.context_for(self))
        except ImportError:
            messagebox.showerror('PDF export dependency','Install the PDF package with:  py -m pip install reportlab');return
        except Exception as exc:
            messagebox.showerror('PDF export error',str(exc));return
        self.status.set(f'Exported {len(rows)} rows: {path}')
    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); self.root.destroy()


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, model, demo='--demo' in argv)
    root.mainloop()
