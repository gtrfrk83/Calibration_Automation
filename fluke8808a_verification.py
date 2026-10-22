"""Fluke 8808A 5-1/2 digit bench multimeter: performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/fluke_8808a_pv.json (built by specs/build_8808a_spec.py from the
8808A Calibration Manual, Tables 3-2 to 3-8, pp. 3-4 to 3-11). Limits are the manual's printed 90-day and 1-year limits (default: 1 year); a point is
good when LOW <= reading <= HIGH (judged in Decimal, so a reading exactly on a limit passes).

Bench: the 8808A over RS-232 (the only remote interface it has) and a Fluke 5522A or 5560A calibrator. The program configures the meter for every point
(function, wire mode, fixed range, slow rate), drives the calibrator and reads the result. It pauses for a hook-up whenever the wiring changes and never
runs unattended. Points the selected calibrator cannot make are measured with a standard the technician connects (the meter is still read
automatically). Hardware I/O is OFF in demo mode. There is no adjustment here: this is verification only.

    import fluke8808a_verification
    fluke8808a_verification.main()         # what Procedures/Fluke_8808A_Verification.py does
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
import appdata
import datamode
import procmods_engine
import reset_startup
import procspec
import drivers
from drivers.fluke_8808a import Fluke8808A, range_number

MODEL = '8808A'
SPEC_PATH = HERE / 'specs' / 'fluke_8808a_pv.json'
SPEC = POINTS = None
PERIODS = {'90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
CALIBRATORS = {'Fluke 5522A': ('5522A', drivers.Fluke5522A), 'Fluke 5560A': ('5560A', drivers.Fluke5560A)}
PARITY_FORMATS = {'8 data bits, no parity': (8, 'none'), '7 data bits, even parity': (7, 'even'), '7 data bits, odd parity': (7, 'odd')}
BAUDS = ['9600', '19200', '4800', '2400', '1200', '600', '300']
GROUP_TITLE = {'ZERO_SHORT': 'Shorted input (zero offset)', 'ZERO_OPEN': 'Open current input (zero offset)', 'VOLT': 'Voltage and frequency inputs',
               'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms', 'IMA': 'Current, mA terminal', 'I2A': 'Current, 10 A terminal (2 A range)',
               'I10A': 'Current, 10 A terminal (10 A range)'}
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'FREQ')
WARM_UP = ('The 8808A needs a half-hour warm-up with the cover on before verification (Calibration Manual, p. 1-9 / chapter 3). The specifications are only '
           'valid in the slow (5-1/2 digit) rate, which the program selects.')


class SpecError(procspec.SpecError):
    pass


def load_spec(path=SPEC_PATH):
    """Read and check the spec (kind 'bench-dmm-band'): every point has a low and a high limit for every period, a range the meter has, and a group."""
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('kind') != 'bench-dmm-band' or spec.get('model') != MODEL:
        raise SpecError("not a 'bench-dmm-band' spec for the 8808A")
    periods = spec['periods']
    if spec['default_period'] not in periods:
        raise SpecError('default_period is not one of periods')
    seen = 0
    for s in spec['sections']:
        for p in s['points']:
            seen += 1
            where = f"{s['id']} point {seen} ({p.get('ref', '?')})"
            if p['kind'] not in KINDS:
                raise SpecError(f'{where}: unknown kind {p["kind"]!r}')
            if set(p['limits']) != set(periods):
                raise SpecError(f'{where}: limits must exist for every period {periods}')
            for period, lim in p['limits'].items():
                if not (isinstance(lim['low'], (int, float)) and isinstance(lim['high'], (int, float)) and lim['low'] < lim['high']):
                    raise SpecError(f'{where}: {period} low must be below high')
                if not lim['low'] <= p['nominal'] <= lim['high']:
                    raise SpecError(f'{where}: {period} limits do not contain the nominal')
            if p['kind'] in ('ACV', 'ACI') and not p.get('frequency'):
                raise SpecError(f'{where}: AC point needs a frequency')
            if p['kind'] == 'FREQ' and not p.get('amplitude'):
                raise SpecError(f'{where}: frequency point needs an amplitude')
            if p['source'] not in ('none', 'calibrator'):
                raise SpecError(f'{where}: source must be none or calibrator')
            try:
                range_number(p['kind'], p['range'])
            except Exception as exc:
                raise SpecError(f'{where}: {exc}') from None
            if p['group'] not in GROUP_TITLE:
                raise SpecError(f'{where}: unknown group {p["group"]!r}')
    return spec


def flatten(spec):
    """One flat, numbered list of points (ids start at 1) in the spec's run order, with plain descriptions."""
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = dict(raw)
            p.update(id=len(points) + 1, section=s['id'], section_title=s['title'], section_page=s['page'], setup=s['setup'])
            p['page'] = f"{raw['page']} (Table {raw['table']}, step {raw['row']})"
            p['optional'] = False
            p['description'] = describe(p)
            points.append(p)
    return points


def describe(p):
    name = procspec.NAMES[p['kind']]
    if p['source'] == 'none':
        what = 'input open' if p.get('input') == 'open' else 'input shorted'
        return f"Zero offset, {name}, {procspec._fmt(p['range'], p['unit'])} range ({what})"
    if p['kind'] == 'FREQ':
        return f"Frequency {procspec._fmt(p['nominal'], 'Hz')} at {procspec._fmt(p['amplitude'], 'V')} rms, {procspec._fmt(p['range'], 'Hz')} range"
    text = f"{name} {procspec._fmt(p['nominal'], p['unit'])}"
    if p.get('frequency'):
        text += f" @ {procspec._fmt(p['frequency'], 'Hz')}"
    return text + f", {procspec._fmt(p['range'], p['unit'])} range"


def apply_period(points, period):
    """Set each point's low / high (absolute limits) and 'error' (the largest distance from nominal) from the chosen period."""
    for p in points:
        lim = p['limits'][period]
        p['low'], p['high'] = lim['low'], lim['high']
        p['error'] = float(f"{max(p['nominal'] - lim['low'], lim['high'] - p['nominal']):.9g}")


def configure(model=MODEL):
    """Load the spec and number the points (the one model of this engine)."""
    global SPEC, POINTS
    SPEC = load_spec()
    POINTS = flatten(SPEC)
    apply_period(POINTS, SPEC['default_period'])


def judge(p, reading):
    """True when LOW <= reading <= HIGH, in Decimal (a reading exactly on a limit passes)."""
    value = Decimal(repr(float(reading)))
    return Decimal(repr(float(p['low']))) <= value <= Decimal(repr(float(p['high'])))


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_8808A_<cal>_<GROUP>.png, then diagrams/hook_8808A_<GROUP>.png."""
    for name in (f'hook_{MODEL}_{cal}_{group}', f'hook_{MODEL}_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text):
    """'COM9' / '9' -> 'ASRL9::INSTR'; anything that already looks like a VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port such as COM9.')
    return f'ASRL{int(t)}::INSTR'


def list_com_ports():
    """Names of the serial ports on this computer (pyserial, else the VISA ASRL resources). [] when neither is installed."""
    try:
        from serial.tools import list_ports
        return sorted((p.device for p in list_ports.comports()), key=lambda s: (len(s), s))
    except Exception:
        pass
    try:
        import pyvisa
        return [r for r in pyvisa.ResourceManager().list_resources() if r.upper().startswith('ASRL')]
    except Exception:
        return []


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 8808A and the calibrator, both through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5522A', cal_baud=9600, dmm_serial=None, transports=None, mods=None):
        self.log = drivers.CommandLog()
        cal_name, cal_cls = CALIBRATORS[cal_model]
        self.is_manual = lambda p: False        # the App sets this: points measured with a standard the technician connects
        if transports:
            dmm_t, cal_t = transports
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address), timeout=30, **(dmm_serial or {}))
            cal_t = drivers.open_visa(to_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = Fluke8808A(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
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
        try: self.dmm.cleanup()
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
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Fluke {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['source'] == 'none': return self.pm_param('f8808a.settle.zero', 2.0)
        if p['kind'] == 'FREQ': return self.pm_param('f8808a.settle.freq', 3.0)
        if p['kind'] in ('ACV', 'ACI'): return self.pm_param('f8808a.settle.ac', 4.0)
        if p['kind'] in ('OHM2', 'OHM4') and p['range'] >= 1e7: return self.pm_param('f8808a.settle.ohm_high', 4.0)
        return self.pm_param('f8808a.settle.default', 2.0)

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        self.dmm.configure_point(p)
        self.dmm.check_errors('configuring ' + p['description'])
        if p['source'] == 'none':          # copper short / open input: the calibrator stays in STANDBY
            time.sleep(self.settle(p))
            reading = self.dmm.read()
            self.dmm.check_errors('reading ' + p['description'])
            return reading
        if self.is_manual(p):              # the technician has connected a standard: the calibrator stays in STANDBY, the meter is read
            time.sleep(self.settle(p))
            reading = self.dmm.read()
            self.dmm.check_errors('reading ' + p['description'])
            return reading
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
        self.dmm.check_errors('reading ' + p['description'])
        return reading


class App(reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, model=MODEL, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('f8808a', MODEL, demo=demo, lists=[POINTS], shape='band')         # procedure modifications: saved overrides for this model
        ui.apply_theme(root)
        root.title(f'Fluke {MODEL} | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1340, 860, min_w=900, min_h=660)
        self.settings = ui.Settings(MODEL)
        s = self.settings
        self.asset = tk.StringVar(); self.serial = tk.StringVar()
        ports = list_com_ports()
        self.dmm_addr = tk.StringVar(value=s.get('dmm_addr', ports[0] if ports else 'COM1'))
        self.dmm_baud = tk.StringVar(value=s.get('dmm_baud', '9600'))
        self.dmm_format = tk.StringVar(value=s.get('dmm_format', '8 data bits, no parity'))
        self.cal_model = tk.StringVar(value=s.get('cal_model', 'Fluke 5522A'))
        self.cal_addr = tk.StringVar(value=s.get('cal_addr', 'COM9'))
        self.cal_baud = tk.StringVar(value=s.get('cal_baud', '9600'))
        self.period = tk.StringVar(value=s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self.warm_confirmed = False
        self._build_ui()
        self.on_period(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the connections and press Test Connections. Step 3: Run All.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def is_manual(self, p):
        """True when the selected calibrator cannot make this point: the technician connects another standard (the meter is still read automatically).
        The spec's `cal_limits` names, per calibrator, the points it cannot make and why (5522A: Operators Manual; 5560A: Product Specifications);
        a calibrator that is not listed for a point drives it."""
        return p['source'] == 'calibrator' and self.cal_key in (p.get('cal_limits') or {})

    def manual_reason(self, p):
        return (p.get('cal_limits') or {}).get(self.cal_key, '')

    def active(self, p):
        return not p.get('skip')                                     # a point skipped by a procedure modification

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
        self.period_combo.configure(state='disabled' if self._busy else 'readonly')

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, f'Fluke {MODEL}  -  Performance Verification',
                                         f'Calibration Manual Tables 3-2 to 3-8, pp. 3-4 to 3-11  |  {len(POINTS)} points in the spec  |  RS-232 only', demo=self.demo,
                                         on_section=self.pick_section, version='spec v1')
        self.status = sh.status_var
        self.conn_pill = sh.add_chip('Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')
        else: sh.notice('The program pauses and shows the hook-up for every new setup and before any high-voltage point. ' + WARM_UP + ' Stay at the bench while a run is in progress.', 'info')

        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Limits to apply').grid(row=0, column=0, sticky='w', pady=4)
        self.period_combo = ttk.Combobox(d, textvariable=self.period, values=list(PERIODS), width=20, state='readonly')
        self.period_combo.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)
        self.period_combo.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
        ttk.Label(d, text='90 days is for an acceptance test after a calibration; the manual recommends a one-year interval.', style='Muted.TLabel',
                  wraplength=ui.px(340), justify='left').grid(row=1, column=0, columnspan=2, sticky='w', pady=(0, 6))
        ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        r = 3
        ttk.Label(d, text='8808A COM port').grid(row=r, column=0, sticky='w', pady=4)
        self.dmm_entry = ttk.Combobox(d, textvariable=self.dmm_addr, values=list_com_ports(), state='normal', width=14)
        self.dmm_entry.grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        for text, var, values, width in (('Baud', self.dmm_baud, BAUDS, 9), ('Format', self.dmm_format, list(PARITY_FORMATS), 24)):
            ttk.Label(d, text=text).grid(row=r, column=0, sticky='w', pady=4)
            ttk.Combobox(d, textvariable=var, values=values, width=width, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Factory settings: 9600 baud, 8 data bits, no parity, 1 stop bit, Echo OFF (Users Manual Table 4-1). They are set from the meter front panel only. '
                          'Echo must stay off. The 8808A has no GPIB or USB port.', style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(
            row=r, column=0, columnspan=2, sticky='w', pady=(2, 6)); r += 1
        ttk.Label(d, text='Calibrator').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_model, values=list(CALIBRATORS), width=14, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator address').grid(row=r, column=0, sticky='w', pady=4)
        self.cal_entry = ttk.Combobox(d, textvariable=self.cal_addr, state='normal', width=34)
        self.cal_entry.grid(row=r, column=1, sticky='ew', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='Calibrator baud').grid(row=r, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.cal_baud, values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=r, column=1, sticky='w', padx=(10, 0), pady=4); r += 1
        ttk.Label(d, text='COM9, GPIB0::6::INSTR ...', style='Muted.TLabel').grid(row=r, column=1, sticky='w', padx=(10, 0)); r += 1
        btns = sh.drawer_footer
        self.btn_find = ttk.Button(btns, text='Refresh ports', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
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
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['low'], p['high'], p['unit'])
        return (p['id'], p['description'] + ('  [your standard]' if self.is_manual(p) else ''), *cells), tags

    def pm_driver_classes(self): return (Fluke8808A, *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_8808a import make_8808a_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5522A'

        def build(mods):
            _bench, ft, dt = make_8808a_bench(CALIBRATORS[cal_model][0])
            io = IO('sim', 'sim', cal_model, 9600, transports=(dt, ft), mods=mods)
            io.is_manual = self.is_manual
            return io
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p))

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
        apply_period(POINTS, PERIODS[self.period.get()])
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
        v, _r, u = ui.si_row([p['low'], p['high']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        manual = ('\nYour own standard is used for this point: ' + self.manual_reason(p)) if self.is_manual(p) else ''
        flags = ('\nPrinted-table correction: ' + ' | '.join(f['why'] for f in p['flags'])) if p.get('flags') else ''
        self.detail.set(f'{p["description"]}\nAcceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}{extra}\n'
                        f'Setup: {self.setup_text(p)}{manual}{flags}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        """Hook-up instruction for a point's wiring group (the calibrator's own terminal names for the one selected)."""
        g = p['group']
        five60 = self.cal_key == '5560A'
        out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
        if g == 'ZERO_SHORT':
            return ('Disconnect the calibrator. Fit the low-thermal 4-wire short (Fluke PN 2653346, Calibration Manual Table 3-1) across INPUT HI / LO and SENSE HI / LO. '
                    'The calibrator stays in STANDBY.')
        if g == 'ZERO_OPEN':
            return 'Leave the current inputs (mA and 10 A terminals) OPEN with nothing connected. The calibrator stays in STANDBY.'
        base = 'Shielded twisted pair, shield to the calibrator LO. '
        if g == 'VOLT':
            return base + f'Calibrator {out} to the meter INPUT HI / LO (Figure 3-1).'
        if g == 'OHM4':
            return (f'4-wire (Figure 3-2): calibrator {out} to INPUT HI / LO and the calibrator SENSE HI / LO to the meter SENSE 4W HI / LO. '
                    "Turn the calibrator's external sense (EX SNS / EXT SENSE) ON at its front panel.")
        if g == 'OHM2':
            return (f'2-wire (Figure 3-3): calibrator {out} to INPUT HI / LO. Calibrator external sense ON and its 2-wire compensation ON, as the manual '
                    'figure shows; the program does not change them.')
        amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX CURRENT HI and LO'
        if g == 'IMA':
            return f'Calibrator current output ({amps}) to the meter mA terminal and COM (Figure 3-4). Check the calibrator range and the fuse first.'
        if g == 'I2A':
            return f'Calibrator current output ({amps}) to the meter 10 A terminal and COM for the 2 A range (Figure 3-4). Check the calibrator range and the fuse first.'
        if g == 'I10A':
            high = 'the calibrator 30A and OUTPUT LO terminals (12 A range)' if five60 else 'the calibrator 20 A output terminals'
            return f'{high[0].upper() + high[1:]} to the meter 10 A terminal and COM (Figure 3-5). Use heavy leads and keep them short.'
        return p['setup']

    # ------------------------------------------------------------------ connection
    def _serial_kwargs(self):
        bits, parity = PARITY_FORMATS[self.dmm_format.get()]
        return dict(baud=int(self.dmm_baud.get()), data_bits=bits, parity=parity, stop_bits=1, write_termination='\n', read_termination='\r\n', flow_control='none')

    def find_instruments(self):
        ports = list_com_ports()
        self.dmm_entry['values'] = ports; self.cal_entry['values'] = ports
        self.status.set(f'{len(ports)} serial port(s) found: ' + (', '.join(ports) if ports else 'none') + '. Pick the 8808A port.' if ports
                        else 'No serial ports found (pip install pyserial, or enter the port name by hand).')

    def _make_io(self):
        io = IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), dmm_serial=self._serial_kwargs(), mods=self.pm_state)
        io.is_manual = self.is_manual
        return io

    def test_connections(self):
        if self.demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect(); self.io = self._make_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        self.status.set('Connected: ' + self.io.ident + '. Calibrator output is NOT enabled.')
        messagebox.showinfo('Connected', f'{MODEL}: {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_format', self.dmm_format), ('cal_model', self.cal_model),
                         ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
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
        if not self.demo and not self.warm_confirmed:
            if not messagebox.askyesno('Warm-up', WARM_UP + '\n\nHas the meter been on for at least half an hour?'): return
            self.warm_confirmed = True
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None: return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_{MODEL}_{self.cal_key}_{group}.png)'))
        self.io.standby()
        if p['source'] == 'none':
            return ui.confirm_steps(self.root, 'Zero offset: physical setup required', f'Setup: {GROUP_TITLE[group]}',
                [('Set up the input', self.setup_text(p))], facts=facts,
                caution='Never use the calibrator as a zero source. The program does not turn its output on for these points.', ok='Set up - measure', image=image)
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if p['kind'] in ('OHM2', 'OHM4'):
            wire = '4W' if p['kind'] == 'OHM4' else '2W'
            try:
                self.io.dmm.configure_point(p)          # the meter has no query for the wire mode: set it now so the operator can see the annunciator
            except Exception as exc:
                self._error(exc); return False
            steps.append(('Annunciator', f'The program has selected the ohms function with {wire}. Confirm the {wire} annunciator is lit on the meter display '
                                         f'(the 8808A cannot report the wire mode over RS-232).'))
        elif p['kind'] in ('ACV', 'ACI', 'FREQ'):
            steps.append(('Rate', 'The program selects the slow reading rate (the specifications apply to it); AC readings take a few seconds.'))
        return ui.confirm_steps(self.root, 'Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image)

    def _prompt_manual(self, p):
        """The selected calibrator cannot make this point: the technician connects another standard and applies the stated value."""
        f = f' at {procspec._fmt(p["frequency"], "Hz")}' if p.get('frequency') else ''
        value = (f'{procspec._fmt(p["amplitude"], "V")} rms at {procspec._fmt(p["nominal"], "Hz")}' if p['kind'] == 'FREQ'
                 else f'{procspec._fmt(p["nominal"], p["unit"])}{f}')
        self.io.standby()
        steps = [('Why', self.manual_reason(p)),
                 ('Standard', f'Disconnect the calibrator. Connect your own standard to the meter as for {GROUP_TITLE[p["group"]]} (Calibration Manual Table 3-1 names a 5725A '
                              f'amplifier for 750 V and a Fluke 271 function generator for frequency) and apply {value}. Use a standard with enough accuracy for the limits.'),
                 ('Wiring', self.setup_text(p))]
        return ui.confirm_steps(self.root, 'Your own standard is needed', f'Point {p["id"]}: {p["description"]}', steps,
                                facts=[('Next point', f'{p["id"]} of {len(POINTS)}'), ('Manual page', p['page'])],
                                caution='The meter is read automatically once you press Continue. Apply the value first and let it settle.',
                                ok='Standard applied - measure', image=find_diagram(self.cal_key, p['group']))

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: self.root.after(30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        manual = self.is_manual(p)
        key = f'MANUAL{p["id"]}' if manual else p['group']
        if not self.demo and key != previous:
            if not (self._prompt_manual(p) if manual else self._prompt_setup(p)):
                self.busy = False; self.status.set('Paused for wiring or setup'); return
        hv = float(SPEC.get('options', {}).get('hv_threshold_v', 100))
        if not self.demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= hv:
            if not messagebox.askyesno('HIGH VOLTAGE', f'This point puts {p["nominal"]:g} V on the meter input. Verify CAT-rated leads, connections, clearance and personnel safety. Continue?'):
                self.busy = False; return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.tree.exists(str(p['id'])): self.tree.selection_set(str(p['id'])); self.tree.see(str(p['id']))
        if self.demo:
            mid, half = (p['low'] + p['high']) / 2, (p['high'] - p['low']) / 2
            reading = mid + half * math.sin(p['id'] * 1.71) * 0.38        # deterministic, labelled synthetic
            self._record(p, reading, True, manual); self.root.after(30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    self.root.after(0, lambda: self._done(points, i, p, reading, key, manual))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    self.root.after(0, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key, manual=False):
        self._record(p, reading, False, manual); self.root.after(30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); messagebox.showerror('Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, manual=False):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()], manual=bool(manual),
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(),
                                        cal_model=self.cal_model.get(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get()))
        if data.get('cal_model') in CALIBRATORS: self.cal_model.set(data['cal_model'])
        self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title']

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        import report_pdf
        rows, pts = [], []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: self.point_row(report_pdf, p, r))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def point_row(self, report_pdf, p, r):
        """One report row. A point measured with the technician's own standard has no calibrator, so its Uncertainty cell is left empty
        (the suite cannot know that standard's uncertainty; the cover sheet from the other software lists it)."""
        row = report_pdf.point_row(p, r['reading'], r['result'] == 'FAIL', section=self.report_section(p), standard=self.cal_key)
        if r.get('manual'):
            row['Uncertainty'] = ''
        return row

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, f'Fluke {MODEL} performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        manual_ids = [p['ref'] for p in pts if (self.left.get(str(p['id'])) or self.found.get(str(p['id'])) or {}).get('manual')]
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'),
                                                [dict(TAR='', TUR='') if p['ref'] in manual_ids else tartur_wiring.point_fields(p, self.cal_key) for p in pts])
            header = [('Instrument', f'Fluke {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()), ('Limits applied', self.period.get()),
                      ('Source', SPEC['source']['cite'])]
            if manual_ids:
                header.append(('Operator-supplied standard', 'Points measured with a standard connected by the technician: ' + ', '.join(manual_ids)))
            report_pdf.write_calibration_pdf(path, rows, header=header, demo=demo, details=details,
                                             footer_note=report_pdf.uncertainty_note(rows, self.cal_key), snapshot_context=report_pdf.context_for(self))
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); self.root.destroy()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, MODEL, demo='--demo' in argv)
    root.mainloop()
