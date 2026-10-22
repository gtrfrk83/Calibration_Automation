"""Keithley Model 2000 6.5-digit multimeter performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keithley_2000_pv.json, built by specs/build_k2000_spec.py from the
Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F) section 1, Tables 1-2 to 1-6 (pp. 1-7 to 1-13).  The manual prints one interval only
(1 year, 18 to 28 C).  Two-way: the program sets the function and range over GPIB or RS-232 (SCPI, Model 2000 User Manual 2000-900 Rev. J chapters 4 and 5),
sources the point from a Fluke 5560A or 5522A, reads the 2000 back with :READ? and judges it.  Hardware I/O is OFF in demo mode.  Never run unattended:
wiring confirmations are required.

    import keithley2000_verification
    keithley2000_verification.main()           # what Procedures/Keithley_2000_Verification.py does
"""
import json, math, sys, threading, time, tkinter as tk
from datetime import datetime
from decimal import Decimal
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
import virtualbench

MODEL = '2000'
SPEC_PATH = HERE / 'specs' / 'keithley_2000_pv.json'
SPEC = procspec.load(SPEC_PATH)
POINTS = procspec.flatten(SPEC)
procspec.apply_period(POINTS, SPEC['default_period'])
PERIODS = {'1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522AComp)}
INTERFACES = ('GPIB', 'RS-232')
FLOW = {'None': 'none', 'XON/XOFF': 'xon_xoff'}
HV_CONFIRM = 100.0                      # volts: a high-voltage confirmation before any DC / AC volts point of this size or more
ZCOMP_LIMIT = 110e3                     # ohm: 5522A impedance compensation exists only below this (5522A Operators Manual p. 6-49)
GROUP_TITLE = {'DCV': 'DC volts', 'ACV': 'AC volts', 'ACV700': 'AC volts, 700 V at 50 kHz', 'DCI': 'DC current', 'ACI': 'AC current',
               'OHM4': '4-wire ohms', 'OHM100M': '100 Mohm (2-wire output)'}


def configure(model=MODEL):
    """The engine has one model; kept so the engine matches the shape of the other bench-DMM engines."""
    return MODEL


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_k2000_<cal>_<GROUP>.png, then diagrams/hook_k2000_<GROUP>.png (see diagrams/README_k2000.txt)."""
    for name in (f'hook_k2000_{cal}_{group}', f'hook_k2000_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text, interface='GPIB'):
    """GPIB: '16' -> 'GPIB0::16::INSTR'.  RS-232: 'COM9' / '9' -> 'ASRL9::INSTR'.  A full VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the GPIB address (0 to 30, factory default 16) or a full VISA address (GPIB0::16::INSTR).')
        return f'GPIB0::{int(t)}::INSTR'
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (ASRL9::INSTR).')
    return f'ASRL{int(t)}::INSTR'


def to_cal_visa(text):
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port such as COM9.')
    return f'ASRL{int(t)}::INSTR'


def serial_kwargs(baud, term='LF', flow='None'):
    """VISA serial settings of the 2000: 8 data bits, no parity, 1 stop bit (User Manual p. 4-6; the 2000 has no other format), CR to end what we send
    (p. 4-7), TX TERM as chosen on the meter for what it sends back (p. 4-7)."""
    return dict(baud=int(baud), data_bits=8, parity='none', stop_bits=1, write_termination='\r',
                read_termination=drivers.keithley_2000.TX_TERM[term], flow_control=FLOW[flow])


def judge(p, reading) -> bool:
    """PASS when |reading - nominal| <= the allowed error, in Decimal (the float reading is taken at its shortest exact text)."""
    return abs(Decimal(repr(float(reading))) - Decimal(str(p['nominal']))) <= Decimal(str(p['error']))


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the Model 2000 under test and the calibrator, both through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, interface='GPIB', serial=None, transports=None, mods=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        cal_name, cal_cls = CALIBRATORS[cal_model]
        if transports:
            dmm_t, cal_t = transports
        else:
            kw = (serial or {}) if interface != 'GPIB' else {}
            dmm_t = drivers.open_visa(to_visa(dmm_address, interface), timeout=30, **kw)
            cal_t = drivers.open_visa(to_cal_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = drivers.Keithley2000(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
            self.dmm.check_errors('connecting')
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
        try: self.dmm.cleanup()                     # back to front panel control (:SYST:LOC on RS-232, GTL on GPIB)
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
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Keithley {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def check_terminals(self, p):
        """The INPUTS switch cannot be set remotely: read it (:SYST:FRSW?) and stop if it is not on FRONT (CM p. 1-6: front panel inputs)."""
        have = self.dmm.front_rear()
        if have != 'FRONT':
            raise drivers.InstrumentError(f'The INPUTS switch is on {have}; the verification uses the FRONT inputs. Move the switch and rerun.')

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        k = p['kind']
        if p['source'] == 'manual': return self.pm_param('k2000.settle.manual', 2.0)
        if k in ('ACV', 'ACI'): return self.pm_param('k2000.settle.ac', 6.0)
        if k in ('OHM2', 'OHM4'):
            return self.pm_param('k2000.settle.ohm_high', 5.0) if p['range'] >= 1e7 else self.pm_param('k2000.settle.ohm', 3.0)
        if k == 'DCI': return self.pm_param('k2000.settle.dci', 3.0)
        return self.pm_param('k2000.settle.default', 2.0)

    def meter_point(self, p):
        """The point as the driver wants it: the spec's measurement conditions (speed, filter, AC bandwidth) filled in."""
        m = SPEC['measure']
        return dict(p, plc=p.get('plc') or m['nplc'], ac_bandwidth=m['ac_bandwidth'], filter_count=m['filter_count'])

    def rel_zero(self):
        """DC volts REL (CM p. 1-7 steps 2-4): 100 mV range, calibrator at 0.00000 mV DC, let the reading settle, REL on. Done once after each reset."""
        z = SPEC['prep']['dcv_rel_zero']
        zero = self.meter_point(dict(kind='DCV', range=z['range'], nominal=z['nominal'], source='calibrator', description='REL zero'))
        self.dmm.configure_point(zero)
        self.dmm.check_errors('configuring the REL zero')
        self.cal.set_output_volts(0, None, dc=True)                      # OUT 0V,0Hz
        self.cal.check_error('REL zero')
        self.cal.operate_unverified()
        time.sleep(virtualbench.scaled(self.pm_param('k2000.settle.rel_zero', 5.0), self.virtual))
        self.dmm.acquire_reference()
        self.standby()
        self.dmm.check_errors('enabling REL')

    def compensation(self, p):
        """Resistance points: the 5522A impedance compensation (WIRE4 below 110 kohm for the 4-wire points, NONE otherwise), set once and read back.
        The 5560A has no such command in the project manuals: the operator sets its own 4-wire mode (the hook-up prompt says so)."""
        if not hasattr(self.cal, 'set_compensation'):
            return
        mode = 'WIRE4' if (p['group'] == 'OHM4' and p['nominal'] < ZCOMP_LIMIT) else 'NONE'
        self.cal.set_compensation(mode)

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        try:
            self.check_terminals(p)
            if p['kind'] == 'DCV' and p['source'] == 'calibrator' and not self.dmm.rel_is_on('DCV'):
                self.rel_zero()
            self.dmm.configure_point(self.meter_point(p))
            self.dmm.check_errors('configuring ' + p['description'])
            if p['source'] == 'manual':        # 700 V at 50 kHz from a 5725A system set by the technician
                time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
                reading = self.dmm.read()
            else:
                k, v, f = p['kind'], p['nominal'], p.get('frequency')
                if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
                elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
                elif k in ('OHM2', 'OHM4'):
                    self.cal.set_output_ohms(v)
                    self.compensation(p)
                self.cal.check_error(p['description'])   # the calibrator refuses outputs it cannot make; never operate then
                self.cal.operate_unverified()
                time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
                reading = self.dmm.read()
            self.dmm.check_errors('reading ' + p['description'])
            return reading
        finally:
            self.standby()


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, demo=False, fast_demo=False):
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('k2000', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title('Keithley 2000 | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 820, min_w=900, min_h=640)
        self.settings = ui.Settings('Keithley2000')
        s = self.settings
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        self.interface = tk.StringVar(value=s.get('interface', 'GPIB'))
        self.dmm_addr = tk.StringVar(value=s.get('dmm_addr', 'GPIB0::16::INSTR'))
        self.dmm_baud = tk.StringVar(value=s.get('dmm_baud', '4800'))
        self.dmm_term = tk.StringVar(value=s.get('dmm_term', 'LF'))
        self.dmm_flow = tk.StringVar(value=s.get('dmm_flow', 'None'))
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5560A'))
        self.cal_addr = tk.StringVar(value=s.get('cal_addr', 'COM9'))
        self.cal_baud = tk.StringVar(value=s.get('cal_baud', '9600'))
        self.period = tk.StringVar(value=s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.include_700 = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the interface and addresses and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def active(self, p):
        if p['optional'] and not self.include_700.get(): return False
        if p.get('variant') == 'alt219' and self.include_700.get(): return False      # 219 V at 50 kHz stands in for the 700 V step only when no 5725A is used
        if p.get('skip'): return False                               # a point skipped by a procedure modification
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
        for c in (self.period_combo, self.opt_check):
            c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) else 'normal'))

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, 'Keithley 2000  -  Performance Verification',
                                         f'Test points from the Model 2000 Calibration Manual, Tables 1-2 to 1-6 (pp. 1-7 to 1-13)  |  {len(POINTS)} points in the spec  |  '
                                         'GPIB or RS-232', demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
        self.status = sh.status_var
        self.conn_pill = sh.add_chip(self.chip_text() if self.demo else 'Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice(self.banner_text(), 'warn', title=virtualbench.BANNER_TITLE)
        else: sh.notice('The program asks you to confirm the warm-up and environment, the wiring before every new setup and before any high-voltage point. Stay at the bench while a run is in progress.', 'info')

        # settings and connections live in the slide-in drawer
        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
        self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
        self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
        self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
        self.opt_check = ttk.Checkbutton(d, text='Include 700 V at 50 kHz (5725A amplifier, source set by hand)', variable=self.include_700, command=self.refresh)
        self.opt_check.grid(row=1, column=0, columnspan=2, sticky='w', pady=(2, 10))
        ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        r = 3
        ttk.Label(d, text='2000 interface').grid(row=r, column=0, sticky='w', pady=4)
        iface = ttk.Combobox(d, textvariable=self.interface, values=list(INTERFACES), width=10, state='readonly')
        iface.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='2000 address / port').grid(row=r, column=0, sticky='w', pady=4)
        self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, state='normal', width=34)
        self.dmm_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
        for text, var, values, width in (('RS-232 baud', self.dmm_baud, ['19200', '9600', '4800', '2400', '1200', '600', '300'], 9),
                                         ('RS-232 TX TERM', self.dmm_term, list(drivers.keithley_2000.TX_TERM), 9),
                                         ('RS-232 flow control', self.dmm_flow, list(FLOW), 12)):
            ttk.Label(d, text=text).grid(row=r, column=0, sticky='w', pady=4)
            ttk.Combobox(d, textvariable=var, values=values, width=width, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='GPIB: the 2000 factory address is 16 (CONFIG > GPIB). RS-232: set the same baud and TX TERM on the meter (CONFIG > RS-232) and the SCPI '
                          'language (the RS-232 interface supports SCPI only). 8 data bits, no parity, 1 stop bit.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(2, 8)); r += 1
        ttk.Label(d, text='Calibrator').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_model, values=list(CALIBRATORS), width=14, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator port').grid(row=r, column=0, sticky='w', pady=4)
        self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
        self.cal_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator baud').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
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
        self.pm_live_attach(sh)                                    # 'Edit procedure': the editor inside this window, usable during a run

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

    def pm_driver_classes(self): return (drivers.Keithley2000, *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_k2000 import make_k2000_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5560A'
        bus = 'RS232' if self.interface.get() == 'RS-232' else 'GPIB'

        def build(mods):
            _bench, ft, dt = make_k2000_bench(CALIBRATORS[cal_model][0], bus)
            return IO('sim', 'sim', cal_model, 9600, self.interface.get(), transports=(dt, ft), mods=mods)
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
        return (p['id'], p['description'], *cells), tags

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
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        printed = f'  |  Printed in the manual: {p["printed_limits"]}' if p.get('printed_limits') else ''
        self.detail.set(f'{p["description"]}\nAcceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}{printed}{extra}\n'
                        f'Setup: {self.setup_text(p)}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    # ------------------------------------------------------------------ wiring text
    def setup_text(self, p):
        g = p['group']
        five60 = self.cal_key == '5560A'
        out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
        base = 'Shielded cable, shield to the calibrator LO. '
        if g == 'DCV':
            return base + f'Calibrator {out} to the 2000 INPUT HI / LO (Figure 1-1); low-thermal connections for the 100 mV and 1 V ranges.'
        if g == 'ACV':
            return base + f'Calibrator {out} to the 2000 INPUT HI / LO (Figure 1-2).'
        if g in ('DCI', 'ACI'):
            amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX HI and AUX LO'
            return (f'Calibrator {amps} to the 2000 AMPS and INPUT LO jacks (Figure {"1-3" if g == "DCI" else "1-4"}). Check the calibrator range, its fuse and the 2000 AMPS fuse '
                    '(3 A, 250 V) first.')
        if g == 'OHM4':
            comp = ('The program sets the 5522A impedance compensation (ZCOMP) to WIRE4 below 110 kohm and NONE from 110 kohm up.' if not five60 else
                    'Set the 5560A\'s own 4-wire (external sense) mode for the points below 110 kohm; the program sends no compensation command to a 5560A.')
            return (f'4-wire: calibrator {out} (force) to the 2000 INPUT HI / LO and the calibrator SENSE HI / LO to the 2000 SENSE Ohms 4 WIRE HI / LO (Figure 1-5); '
                    f'calibrator external sense ON. {comp}')
        if g == 'OHM100M':
            return f'Calibrator {out} to the 2000 INPUT HI / LO and SENSE jacks as in Figure 1-6; calibrator external sense OFF (2-wire output); shielded cable. The program sets compensation NONE.'
        return p['setup']

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        gpib = [r for r in found if r.upper().startswith('GPIB')]
        asrl = [r for r in found if r.upper().startswith('ASRL')]
        self.dmm_entry['values'] = (gpib if self.interface.get() == 'GPIB' else asrl) or found; self.cal_entry['values'] = asrl or found
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _serial(self):
        return serial_kwargs(self.dmm_baud.get(), self.dmm_term.get(), self.dmm_flow.get())

    def _new_io(self):
        if self.virtual:          # demo: the real IO / driver code over a simulated 2000 and calibrator
            from drivers.simulated_k2000 import make_k2000_bench
            self._vb = make_k2000_bench(self.cal_key, 'RS232' if self.interface.get() == 'RS-232' else 'GPIB')
            return IO('virtual', 'virtual', self.cal_model.get(), 9600, self.interface.get(), transports=(self._vb[2], self._vb[1]), mods=self.pm_state, virtual=True)
        return IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), self.interface.get(), serial=self._serial(), mods=self.pm_state)

    def test_connections(self):
        if self.fast_demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect(); self.io = self._new_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.')
        messagebox.showinfo('Connected' + (' (DEMO)' if self.virtual else ''), f'Keithley {MODEL}: {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}{tag}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('interface', self.interface), ('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_term', self.dmm_term), ('dmm_flow', self.dmm_flow),
                         ('cal_model', self.cal_model), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
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

    def _prompt_start(self):
        """Warm-up and environment (CM p. 1-3 and 1-6), asked once at the start of a run. Returns False if the technician cancels."""
        return ui.confirm_steps(self.root, 'Before the verification', 'Warm-up and conditions',
            [('Warm-up', 'The 2000 must have been on for at least one hour (Cal Manual p. 1-3). Allow the calibrator its own warm-up time as well.'),
             ('Environment', 'Ambient 18 to 28 C and relative humidity below 80 % (p. 1-3).'),
             ('Inputs', 'Set the INPUTS switch to FRONT. The program reads the switch and stops if it is on REAR.'),
             ('Direct connections', 'Connect the calibrator straight to the 2000: no scanner or other switching equipment (p. 1-6).')],
            facts=[('Limits', f'{self.period.get()}, 18 to 28 C'), ('Calibrator', self.cal_model.get())],
            caution='The program restores the 2000 factory defaults (*RST) before the first point, then sets function, range, speed and filter for every point.',
            ok='Conditions met - start')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): messagebox.showwarning('Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        if not self.fast_demo and not self._prompt_start(): self.status.set('Run not started: warm-up and conditions were not confirmed.'); return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_k2000_{self.cal_key}_{group}.png)'))
        self.io.standby()
        if p['source'] == 'manual':
            return ui.confirm_steps(self.root, 'Connect the standard', f'Connect for {GROUP_TITLE[group]}',
                [('Connect', p['setup']), ('Stabilise', 'Put the standard in operate and allow it to settle, then continue; the program reads the 2000 itself.')],
                facts=facts, caution='High voltage: CAT-rated leads, clearance and personnel safety.', ok='Source ready - measure', image=image)
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if group == 'DCV':
            steps.append(('REL zero', 'With the calibrator at 0.00000 mV DC the program enables REL on the 100 mV range and leaves it on for the DC volts points (p. 1-7).'))
        if p['kind'] in ('ACV', 'ACI'):
            steps.append(('Speed', 'Each AC reading takes several seconds (10-reading filter); the program waits for it.'))
        return ui.confirm_steps(self.root, 'Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: self.root.after(30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = (p['source'], p['terminal'], p['group'])
        if not self.fast_demo and key != previous and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.fast_demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= HV_CONFIRM:
            if not messagebox.askyesno('HIGH VOLTAGE', f'This point outputs {p["nominal"]:g} V. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.tree.exists(str(p['id'])): self.tree.selection_set(str(p['id'])); self.tree.see(str(p['id']))
        if self.virtual: self._virtual_operator(p)                       # the virtual operator does what the prompt asked
        if self.fast_demo:
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
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    self.root.after(0, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _virtual_operator(self, p):
        """The one hook-up action no command can do: for the 700 V point the technician sets the 5725A system to 700 V, 50 kHz in operate; on the simulated bench
        that is the external input of the simulated bench."""
        virtualbench.operator_sets_up(self._vb, p, terminal=None, manual=p['source'] == 'manual', nominal=p['nominal'])

    def _done(self, points, i, p, reading, key):
        self._record(p, reading, bool(self.demo)); self.root.after(30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); messagebox.showerror('Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'K{MODEL}_{name}_checkpoint.json')

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
        return p['section_title']

    def standard_for(self, p):
        """The standard that applied a point, for the uncertainty / TAR / TUR: the selected calibrator, but not for the 700 V point (a 5725A system set by hand,
        not one of the calibrators: only the scope CMC applies there)."""
        return None if p['source'] == 'manual' else self.cal_key

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        import report_pdf
        rows, pts = [], []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: report_pdf.point_row(p, r['reading'], r['result'] == 'FAIL', section=self.report_section(p), standard=self.standard_for(p)))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, 'Keithley 2000 performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [tartur_wiring.point_fields(p, self.standard_for(p)) for p in pts])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', 'Keithley Model 2000'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', self.period.get()), ('Source', 'Keithley Model 2000 Calibration Manual 2000-905-01 Rev. F, pp. 1-3 to 1-13')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, self.cal_key), snapshot_context=report_pdf.context_for(self))
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True
        if not self.demo: self._save_settings()
        self.disconnect(); self.root.destroy()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    demo, fast = virtualbench.flags(argv)
    App(root, demo=demo, fast_demo=fast)
    root.mainloop()
