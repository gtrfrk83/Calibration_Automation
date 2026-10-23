"""Keysight / Agilent 34410A and 34411A 6 1/2-digit multimeter performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_34410a_pv.json, built by specs/build_34410a_spec.py from the
Keysight 34410A/11A/L4411A Service Guide chapter 3 "Verification Tests" (printed pp. 68-87).  The tables print three intervals (24 hour, 90 day, 1 year); the
default is the 1 year limit.  Two-way: the program sets the function, range and speed over GPIB or USB (USBTMC through the project's VISA transport; the 34410A has
no RS-232), sources the point from a Fluke 5560A or 5522A (or a 5520A, when its published specification covers every point), reads the meter back with READ? and judges it.  Hardware I/O is OFF in demo mode.
Never run unattended: wiring confirmations are required.

    import agilent34410a_verification
    agilent34410a_verification.main()           # what Procedures/Agilent_34410A_Verification.py does
    agilent34410a_verification.main(model='34411A')   # what Procedures/Agilent_34411A_Verification.py does

Model family: the 34410A and the 34411A share ONE spec (specs/keysight_34410a_pv.json: the Service Guide verification tables are the same for both, printed on the
same pages "34410A/11A") and one engine.  The spec's models{} block carries the per-model flags; configure(model) selects the model.  The 34410A is the default and
behaves exactly as before.  The 34411A-only features (digitizing, pre-trigger, 1 million reading memory) are not part of the verification and are not used.
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
import calibrator_fit
import procspec
import drivers
import appdata
import datamode
import procmods_engine
import reset_startup
import virtualbench

MODEL = '34410A'
SPEC_PATH = HERE / 'specs' / 'keysight_34410a_pv.json'
SPEC = procspec.load(SPEC_PATH)
POINTS = procspec.flatten(SPEC)
procspec.apply_period(POINTS, SPEC['default_period'])
PERIODS = {'24 hours': '24h', '90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
# The calibrators.  The 5520A uses the existing 5522A-family driver (same OUT / OPER / STBY / ERR? set, its IDN_MATCH includes 5520); the ZCOMP compensation command is the
# 5522A's (Operators Manual p. 6-49) and is NOT assumed to exist on a 5520A, so a 5520A (like the 5560A) is set to 4-wire by the operator.
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522AComp), 'Fluke 5520A': ('5520A', drivers.Fluke5520A)}
INTERFACES = ('GPIB', 'USB')
DEFAULT_ADDR = {'GPIB': 'GPIB0::22::INSTR', 'USB': 'USB0::0x0957::0x0607::MY00000000::INSTR'}      # GPIB factory address 22 (UG p. 90); the USB IDs are an UNVERIFIED example
HV_CONFIRM = 100.0                      # volts: a high-voltage confirmation before any DC / AC volts point of this size or more
ZCOMP_LIMIT = 110e3                     # ohm: 5522A impedance compensation exists only below this (5522A Operators Manual p. 6-49)
GROUP_TITLE = {'ZERO_SHORT': 'zero offset (4-terminal short)', 'ZERO_OPEN': 'zero offset (current input open)', 'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current',
               'ACI': 'AC current', 'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms (100 Mohm)', 'FREQ': 'frequency', 'CAP': 'capacitance'}


def group_of(p):
    """The hook-up group (prompt and diagram key) of a point."""
    if p['source'] == 'none':
        return 'ZERO_OPEN' if p.get('input') == 'open' else 'ZERO_SHORT'
    if p['source'] == 'manual':
        return 'CAP'
    return p['kind']


for _p in POINTS:
    _p['group'] = group_of(_p)


MODELS = tuple(SPEC['models'])           # ('34410A', '34411A'): the per-model flags are in the spec's models{} block


def model_info(model=None):
    """The spec's flags for one model (default: the model selected now)."""
    return SPEC['models'][model or MODEL]


def configure(model=MODEL):
    """Select the model of the family.  The points and limits are the same for every model (one spec); the model decides the title, the *IDN? the driver
    accepts, the settings / checkpoint names and the wording of the prompts and the report."""
    global MODEL
    if model not in SPEC['models']:
        raise ValueError(f'unknown model {model!r}: expected one of {", ".join(SPEC["models"])}')
    MODEL = model
    return MODEL


def dmm_class(model=None):
    """The driver class of a model of the family."""
    return drivers.Keysight34411A if (model or MODEL) == '34411A' else drivers.Keysight34410A


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_34410a_<cal>_<GROUP>.png, then diagrams/hook_34410a_<GROUP>.png (see diagrams/README_34410a.txt).
    The 5520A uses the 5522A picture.  The 34411A looks for its own hook_34411a_ names first (same front panel and terminals: the 34410A pictures serve it)."""
    cal = '5522A' if cal == '5520A' else cal
    names = [f'hook_34410a_{cal}_{group}', f'hook_34410a_{group}']
    if MODEL == '34411A':
        names = [f'hook_34411a_{cal}_{group}', f'hook_34411a_{group}'] + names
    for name in names:
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text, interface='GPIB'):
    """GPIB: '22' -> 'GPIB0::22::INSTR'.  USB: the full USBTMC resource 'USB0::<mfgID>::<modID>::<serial>::INSTR' (UG p. 92: the string is shown on the meter,
    UTILITY MENU > REMOTE I/O > USB > USB ID, and by the VISA tools).  A full VISA resource (GPIB / USB / TCPIP) passes through for either choice."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the GPIB address (0 to 30, factory default 22) or a full VISA address (GPIB0::22::INSTR).')
        return f'GPIB0::{int(t)}::INSTR'
    raise ValueError('Enter the full USB resource, USB0::<mfgID>::<modID>::<serial>::INSTR (press Find instruments to list the ones VISA sees).')


def to_cal_visa(text):
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port such as COM9.')
    return f'ASRL{int(t)}::INSTR'


def judge(p, reading) -> bool:
    """PASS when |reading - nominal| <= the allowed error, in Decimal (the float reading is taken at its shortest exact text)."""
    return abs(Decimal(repr(float(reading))) - Decimal(str(p['nominal']))) <= Decimal(str(p['error']))


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 34410A / 34411A under test and the calibrator, both through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, interface='GPIB', transports=None, mods=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        cal_name, cal_cls = CALIBRATORS[cal_model]
        if transports:
            dmm_t, cal_t = transports
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address, interface), timeout=30)       # GPIB / USB (USBTMC) / LAN: the VISA resource string decides, no serial settings
            cal_t = drivers.open_visa(to_cal_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = dmm_class()(dmm_t, self.log, label=MODEL)
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
        try: self.dmm.cleanup()                     # back to front panel control: GTL on GPIB (USB / LAN: the operator presses Shift / Local)
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
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Keysight {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def check_terminals(self, p):
        """The Front/Rear switch cannot be set remotely: read it (ROUT:TERM?) and stop if it is not where the point needs it."""
        want = 'REAR' if p['terminal'] == 'REAR' else 'FRONT'
        have = self.dmm.front_rear()
        if have != want:
            raise drivers.InstrumentError(f'The Front/Rear switch is on {have}; this point needs {want}. Move the switch and rerun.')

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        k = p['kind']
        if p['source'] == 'none': return self.pm_param('a34410a.settle.zero', 1.5)
        if p['source'] == 'manual': return self.pm_param('a34410a.settle.manual', 2.0)
        if k == 'FREQ': return self.pm_param('a34410a.settle.freq', 3.0)
        if k in ('ACV', 'ACI'): return self.pm_param('a34410a.settle.ac', 9.0)
        if k in ('OHM2', 'OHM4') and p['range'] >= 1e7: return self.pm_param('a34410a.settle.ohm_high', 4.0)
        if k == 'DCI': return self.pm_param('a34410a.settle.dci', 3.0)
        return self.pm_param('a34410a.settle.default', 2.0)

    def meter_point(self, p):
        """The point as the driver wants it: the spec's measurement conditions (100 NPLC, 3 Hz AC filter, 1 s aperture) filled in."""
        m = SPEC['measure']
        return dict(p, plc=p.get('plc') or m['nplc'], ac_bandwidth=p.get('filter_hz') or m['ac_bandwidth'], aperture_s=m['freq_aperture_s'])

    def compensation(self, p):
        """Resistance points: the 5522A impedance compensation (WIRE4 below 110 kohm for the 4-wire points, NONE otherwise), set once and read back.
        The 5560A and 5520A have no such command in the project manuals / drivers: the operator sets the calibrator's own 4-wire mode (the hook-up prompt says so)."""
        if not hasattr(self.cal, 'set_compensation'):
            return
        mode = 'WIRE4' if (p['kind'] == 'OHM4' and p['nominal'] < ZCOMP_LIMIT) else 'NONE'
        self.cal.set_compensation(mode)

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        try:
            self.check_terminals(p)
            self.dmm.configure_point(self.meter_point(p))
            self.dmm.check_errors('configuring ' + p['description'])
            if p['source'] in ('none', 'manual'):      # copper short / open input (the calibrator stays in STANDBY) or a capacitance standard the technician connected
                time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
                reading = self.dmm.read()
            else:
                k, v, f = p['kind'], p['nominal'], p.get('frequency')
                if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
                elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
                elif k in ('OHM2', 'OHM4'):
                    self.cal.set_output_ohms(v)
                    self.compensation(p)
                elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)       # AC volts at the test frequency (the manual's standard is a 33220A generator)
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
        self.pm_init('a34410a', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title(f'Keysight {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1320, 820, min_w=900, min_h=640)
        self.settings = ui.Settings(f'Keysight{MODEL}')
        s = self.settings
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        self.interface = tk.StringVar(value=s.get('interface', 'GPIB') if s.get('interface', 'GPIB') in INTERFACES else 'GPIB')
        # one address per interface, remembered separately: choosing GPIB or USB brings back the address last used with it
        self.addrs = {i: s.get(f'dmm_addr_{i}', DEFAULT_ADDR[i]) for i in INTERFACES}
        self._iface_shown = self.interface.get()
        self.dmm_addr = tk.StringVar(value=self.addrs[self._iface_shown])
        self.cal_offer = calibrator_fit.make_offer('5520A', calibrator_fit.dmm_requests(POINTS), unverified=drivers.Fluke5520A.unverified_summary())
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5560A') if s.get('cal_model', 'Fluke 5560A') in self.cal_choices() else 'Fluke 5560A')
        self.cal_addr = tk.StringVar(value=s.get('cal_addr', 'COM9'))        # calibrators are typically on RS-232
        self.cal_baud = tk.StringVar(value=s.get('cal_baud', '9600'))
        self.period = tk.StringVar(value=s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.test_set = tk.StringVar(value='Full verification')
        self.include_optional = tk.BooleanVar(value=False)
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

    def cal_choices(self):
        """The calibrator picker's values: the 5520A only when its published specification covers every point of the procedure (calibrator_fit).  It does not cover the
        three 300 kHz AC volts points, so it is not offered here (a saved 5520A choice falls back to the 5560A)."""
        return calibrator_fit.picker_values(list(CALIBRATORS), {'Fluke 5520A': self.cal_offer})

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
                                         f'Test points from the 34410A/11A/L4411A Service Guide, pp. 68-87  |  {len(POINTS)} points in the spec  |  GPIB or USB',
                                         demo=self.demo, on_section=self.pick_section, version='spec v1', virtual=self.virtual)
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
        ttk.Label(d, text='Test set').grid(row=1, column=0, sticky='w', pady=4)
        self.set_combo = ttk.Combobox(d, textvariable=self.test_set, values=['Full verification', 'Quick check (Q points only)'], width=26, state='readonly')
        self.set_combo.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=4); self.set_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        self.opt_check = ttk.Checkbutton(d, text='Include the optional tests (extra AC volts, AC current, capacitance)', variable=self.include_optional, command=self.refresh)
        self.opt_check.grid(row=2, column=0, columnspan=2, sticky='w', pady=(2, 10))
        ttk.Separator(d).grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        r = 4
        ttk.Label(d, text=f'{MODEL} interface').grid(row=r, column=0, sticky='w', pady=4)
        self.iface_combo = ttk.Combobox(d, textvariable=self.interface, values=list(INTERFACES), width=10, state='readonly')
        self.iface_combo.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4)
        self.iface_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_interface()); r += 1
        ttk.Label(d, text=f'{MODEL} address / resource').grid(row=r, column=0, sticky='w', pady=4)
        self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, state='normal', width=34)
        self.dmm_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text=f'GPIB: the {MODEL} factory address is 22 (UTILITY MENU > REMOTE I/O > GPIB). USB: nothing to set on the meter; the resource is '
                          'USB0::<mfgID>::<modID>::<serial>::INSTR (UTILITY MENU > REMOTE I/O > USB > USB ID, or Find instruments). ' + f'The {MODEL} has no RS-232. ' +
                          'The IDs in the example are not verified for your bench.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=r, column=0, columnspan=2, sticky='w', pady=(2, 8)); r += 1
        ttk.Label(d, text='Calibrator').grid(row=r, column=0, sticky='w', pady=4)
        calbox = ttk.Combobox(d, textvariable=self.cal_model, values=self.cal_choices(), width=14, state='readonly')
        calbox.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        calibrator_fit.attach_note(d, self.cal_offer, ui, widgets=(calbox,), row=r); r += 1
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

    def on_interface(self):
        """GPIB <-> USB: keep the address typed for the interface just left and show the one remembered for the new one."""
        old, new = self._iface_shown, self.interface.get()
        if new == old: return
        self.addrs[old] = self.dmm_addr.get()
        self.dmm_addr.set(self.addrs[new]); self._iface_shown = new
        self.dmm_entry.configure(values=())
        if not self.demo: self._save_settings()

    def pm_driver_classes(self): return (dmm_class(), *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_34410a import make_34410a_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5560A'

        def build(mods):
            _bench, ft, dt = make_34410a_bench(CALIBRATORS[cal_model][0], self.interface.get(), MODEL)
            dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'          # the Front/Rear switch the technician would set
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
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        flags = ('  |  ' + '; '.join(p['flags'])) if p.get('flags') else ''
        printed = f'  |  Printed in the manual ({self.period.get()}): {p["printed_limits"].get(PERIODS[self.period.get()], "")}' if p.get('printed_limits') else ''
        self.detail.set(f'{p["description"]}\nAcceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}{printed}{flags}{extra}\n'
                        f'Setup: {self.setup_text(p)}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    # ------------------------------------------------------------------ wiring text
    def setup_text(self, p):
        g = p['group']
        five60 = self.cal_key == '5560A'
        out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
        base = 'Shielded twisted-pair PTFE cable, shields to earth ground at one place only. '
        if g == 'ZERO_SHORT':
            return f'Select the {p["terminal"]} terminals; install the 34172B low-thermal 4-terminal short across INPUT HI / LO and SENSE HI / LO. The calibrator stays in STANDBY.'
        if g == 'ZERO_OPEN':
            return f'Select the {p["terminal"]} terminals; leave the current (I) input OPEN, nothing connected. The calibrator stays in STANDBY.'
        if g in ('DCV', 'ACV'):
            return base + f'Calibrator {out} to the {MODEL} front INPUT HI / LO; low-thermal connections for DC volts on the 100 mV and 1 V ranges. Front/Rear switch on FRONT.'
        if g in ('DCI', 'ACI'):
            amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX HI and AUX LO'
            return (f'Calibrator {amps} to the {MODEL} front 3 A (I) terminal and INPUT LO. Check the calibrator range, its fuse and the {MODEL} 3 A, 250 V fuse first. '
                    'Front/Rear switch on FRONT.')
        if g == 'OHM4':
            comp = ('The program sets the calibrator impedance compensation (ZCOMP) to WIRE4 below 110 kohm and NONE from 110 kohm up.' if self.cal_key == '5522A' else
                    f'Set the {self.cal_key}\'s own 4-wire (external sense) mode for the points below 110 kohm; the program sends no compensation command to a {self.cal_key}.')
            return (f'4-wire: calibrator {out} (force) to the {MODEL} INPUT HI / LO and the calibrator SENSE HI / LO to the {MODEL} SENSE (Sense Ohm 4W) HI / LO; '
                    f'calibrator external sense ON. {comp} Front/Rear switch on FRONT.')
        if g == 'OHM2':
            return f'Calibrator {out} to the {MODEL} INPUT HI / LO; calibrator external sense OFF (2-wire output); shielded cable. 2-wire ohms function. Front/Rear switch on FRONT.'
        if g == 'FREQ':
            return (f'Calibrator AC voltage output at the stated level and frequency to the {MODEL} front INPUT HI / LO (the manual\'s standard is a 33220A generator). '
                    'Front/Rear switch on FRONT.')
        return p['setup']

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        want = self.interface.get()
        mine = [r for r in found if r.upper().startswith(want)]
        asrl = [r for r in found if r.upper().startswith('ASRL')]
        self.dmm_entry.configure(values=mine or found); self.cal_entry.configure(values=asrl or found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _new_io(self):
        if self.virtual:          # demo: the real IO / driver code over a simulated 34410A and calibrator
            from drivers.simulated_34410a import make_34410a_bench
            self._vb = make_34410a_bench(self.cal_key, self.interface.get(), MODEL)
            return IO('virtual', 'virtual', self.cal_model.get(), 9600, self.interface.get(), transports=(self._vb[2], self._vb[1]), mods=self.pm_state, virtual=True)
        return IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), self.interface.get(), mods=self.pm_state)

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
        warn = self.io.dmm.firmware_warning()
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.' + (f' WARNING: {warn}.' if warn else ''))
        messagebox.showinfo('Connected' + (' (DEMO)' if self.virtual else ''), f'Keysight {MODEL}: {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}{tag}\n'
                            f'Calibrator output is not enabled.' + (f'\n\nWARNING: {warn}.' if warn else ''))

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        self.addrs[self.interface.get()] = self.dmm_addr.get()
        for i in INTERFACES:
            self.settings.set(f'dmm_addr_{i}', self.addrs[i])
        for key, var in (('interface', self.interface), ('cal_model', self.cal_model), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
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
        """Warm-up and environment (Service Guide p. 67), asked once at the start of a run. Returns False if the technician cancels."""
        return ui.confirm_steps(self.root, 'Before the verification', 'Warm-up and conditions',
            [('Warm-up', f'The {MODEL} must have warmed up for 90 minutes with a copper short connected (Service Guide p. 67). Allow the calibrator its own warm-up time as well.'),
             ('Environment', 'Ambient 18 to 28 C (ideally 23 C +/- 2 C) and relative humidity below 80 % (p. 67).'),
             ('Cables', 'Shielded twisted-pair PTFE cables, as short as possible, shields to earth ground at ONE place (p. 67).'),
             ('Front / Rear', 'The program reads the Front/Rear switch (ROUT:TERM?) before every point and stops if it is wrong; it cannot move the switch. Never move it with signals present.')],
            facts=[('Limits', f'{self.period.get()}, 18 to 28 C'), ('Calibrator', self.cal_model.get()), ('Meter interface', self.interface.get())],
            caution=f'The program restores the {MODEL} factory defaults (*RST) before the first point, then sets function, range, 100 NPLC or the 3 Hz AC filter for every point.',
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
            facts.append(('Diagram', f'not installed (expected diagrams/hook_34410a_{self.cal_key}_{group}.png)'))
        self.io.standby()
        switch = ('Front/Rear switch', f'Set the Front/Rear switch to {p["terminal"]} (with nothing connected to the terminals). The program checks the switch position before measuring.')
        if p['source'] == 'none':
            return ui.confirm_steps(self.root, 'Zero offset - physical setup required', f'Set up for {GROUP_TITLE[group]}, {p["terminal"]} terminals',
                [switch, ('Set up the input', self.setup_text(p))], facts=facts, caution='The calibrator stays in STANDBY. Never use it as a zero source.',
                ok='Set up - measure', image=image)
        if p['source'] == 'manual':
            return ui.confirm_steps(self.root, 'Connect the standard', f'Connect for {GROUP_TITLE[group]}',
                [('Null', f'With the test leads open, press Null on the {MODEL} in the capacitance function (User\'s Guide p. 60: the specification is with Math Null); the program sends no null command.'),
                 ('Connect', p['setup']), ('Stabilise', f'Allow the standard to settle, then continue; the program reads the {MODEL} itself.')],
                facts=facts, caution='The specification is for film capacitors; additional errors may occur for other types (User\'s Guide p. 136).', ok='Standard connected - measure', image=image)
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p)), switch]
        if p['kind'] in ('ACV', 'ACI'):
            steps.append(('Speed', 'Each AC reading takes about 2.5 seconds with the 3 Hz filter plus the settling wait.'))
        return ui.confirm_steps(self.root, 'Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            end = f' The meter is still under remote control: press Shift / Local on the {MODEL} to return to the front panel.' if (self.interface.get() != 'GPIB' and not self.fast_demo) else ''
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.' + end); return
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
        """The hook-up actions no command can do, done on the simulated bench after the prompt: the Front/Rear switch and the capacitance standard."""
        virtualbench.operator_sets_up(self._vb, p, terminal=p.get('terminal'), manual=p['source'] == 'manual', nominal=p['nominal'])

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
        return appdata.progress_path(f'A{MODEL}_{name}_checkpoint.json')

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
        """The standard that applied a point, for the uncertainty / TAR / TUR: the selected 5522A or 5560A.  Not for a zero-offset point (no source), the technician's
        capacitance standard.  The 5520A has its own sheet (specs/standards/fluke_5520a_standard.json)."""
        return None if (p['source'] != 'calibrator' or self.cal_key not in ('5522A', '5560A', '5520A')) else self.cal_key

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
        details = report_dialog.ask_details(self.root, f'Keysight {MODEL} performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [tartur_wiring.point_fields(p, self.standard_for(p)) for p in pts])
            std = self.cal_key if self.cal_key in ('5522A', '5560A', '5520A') else None
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Keysight {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', self.period.get()), ('Source', 'Keysight 34410A/11A/L4411A Service Guide, pp. 68-87 (Verification Tests)')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, std), snapshot_context=report_pdf.context_for(self))
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


def main(argv=None, model=None):
    """model: '34410A' (default) or '34411A'; the launcher of each model passes its own."""
    argv = sys.argv if argv is None else argv
    if model:
        configure(model)
    root = tk.Tk()
    demo, fast = virtualbench.flags(argv)
    App(root, demo=demo, fast_demo=fast)
    root.mainloop()
