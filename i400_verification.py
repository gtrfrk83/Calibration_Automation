"""Fluke i400 AC Current Clamp performance verification (Current Accuracy Tests, Table 3 of the i400 Calibration Information 2414311), automated.

Test points and limits are NOT written in this file: they are loaded from specs/fluke_i400_pv.json, built by specs/build_fluke_i400_spec.py from the rendered page images of
the manual (Table 3, p. 6).  Three steps: 1 A at 45 Hz through a single-turn wire (LCOMP OFF), 2 A at 400 Hz and 8 A at 60 Hz through the 50-turn coil (LCOMP ON), which the
clamp reads as 100 A and 400 A; the clamp's output (1 mA/A) is read by a multimeter.  Two-way: the program sources the point from a Fluke 5560A, 5522A or 5520A (the operator
picks), reads the multimeter (Keysight 34410A / 34411A, Fluke 8846A or Agilent 34401A) over VISA, and judges the reading against the printed limits.  Nothing is typed by
hand.  Hardware I/O is OFF in demo mode.  Never run unattended: wiring confirmations are required.

    import i400_verification
    i400_verification.main()           # what Procedures/Fluke_i400_Verification.py does

The multimeter pre-calibration (Table 3 footnote, p. 6: "To obtain the best TUR, the Fluke 189 is pre-calibrated at each step using the 5520A with LCOMP OFF.  The Fluke 189 error
is then algebraically added to the UUT reading"): with the option ON (default) the program first connects the calibrator straight to the multimeter, applies the clamp's nominal
output (1 mA at 45 Hz, 100 mA at 400 Hz, 400 mA at 60 Hz), and adds (applied - reading) to every clamp reading of that step.  The sign convention is the physically correct one;
the manual says only "algebraically added" (UNVERIFIED reading of that sentence).

The 50-turn coil points use the shared coil rule (coil_rule.py) for their uncertainty, as the 374 / 375 / 376 procedures do.  The reading multimeter's own uncertainty is NOT in
the reported uncertainty (the other procedures report the source's uncertainty only).
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in i400_view_qt.py / i400_view_qt.py
import calibrator_fit
import coil_rule
import procspec
import drivers
import appdata
import datamode
import procmods_engine
import reset_startup
import surprise
import virtualbench
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)

MODEL = 'i400'
TITLE = 'Fluke i400 AC Current Clamp'
SPEC_PATH = HERE / 'specs' / 'fluke_i400_pv.json'
SPEC = procspec.load(SPEC_PATH)
POINTS = procspec.flatten(SPEC)
procspec.apply_period(POINTS, SPEC['default_period'])
PERIODS = {'Limits printed in the manual': 'printed'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
# The calibrators (the owner picks one).  The 5520A uses the 5522A-family driver; the program sets LCOMP ON for the coil steps through the driver (5522A Operators Manual p. 6-23; on the 5520A the command is UNVERIFIED).
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522AComp), 'Fluke 5520A': ('5520A', drivers.Fluke5520A)}
INTERFACES = ('GPIB', 'USB')
DEFAULT_ADDR = {'GPIB': 'GPIB0::22::INSTR', 'USB': 'USB0::0x0957::0x0607::MY00000000::INSTR'}      # GPIB factory address 22 (34410A UG p. 90); the USB IDs are an UNVERIFIED example


# ---- the reading multimeter ------------------------------------------------------------------------------------------------------------------------
class _ScpiReading:
    """What the engine needs of a multimeter that the shared SCPI DMM driver (8846A, 34401A) does not have on its own.  Nothing is sent that the driver does not already send:
    configure_point is the driver's configure('ACI', range), check_errors reads its SYST:ERR? queue.  The AC filter is not set (the point's own range only)."""
    SHORT = ''

    def configure_point(self, point: dict):
        self.configure(point['kind'], float(point['range']))

    def firmware_warning(self) -> str:
        return ''

    def front_rear(self) -> str:
        return 'FRONT'

    def check_errors(self, context: str = ''):
        found = []
        for _ in range(11):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        if found:
            raise drivers.InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))


class Reading8846A(_ScpiReading, drivers.Fluke8846A):
    SHORT = '8846A'


class Reading34401A(_ScpiReading, drivers.Agilent34401A):
    SHORT = '34401A'


DMMS = {'Keysight 34410A': ('34410A', drivers.Keysight34410A), 'Keysight 34411A': ('34411A', drivers.Keysight34411A),
        'Fluke 8846A': ('8846A', Reading8846A), 'Agilent 34401A': ('34401A', Reading34401A)}
MANUAL = 'Manual entry (typed)'                  # no reading multimeter on the bus: the program drives the calibrator and the operator types the reading
DMM_CHOICES = [MANUAL] + list(DMMS)
DEFAULT_DMM = MANUAL
DMM_INPUT = {'34410A': 'the front 3 A (I) terminal and LO', '34411A': 'the front 3 A (I) terminal and LO', '34401A': 'the 3 A input and LO',
             '8846A': 'the 10 A input and LO'}                    # which input carries 408 mA: UNVERIFIED for the 8846A (the mA input is fused for 400 mA)

GROUP_TITLE = {'WIRE_1T': 'the single-turn wire (1 A)', 'COIL_AUX': 'the 50-turn coil on the low-current output (2 A)', 'COIL_20A': 'the 50-turn coil on the 20 A output (8 A)',
               'DMM_REF': 'the multimeter pre-calibration (calibrator straight into the multimeter)'}
SECTION_OF = {'WIRE_1T': 'wire', 'COIL_AUX': 'coil', 'COIL_20A': 'coil'}


def _describe(p):
    turns = f'{p["applied"]["value"]:g} A x {p["turns"]} turn' + ('s' if p['turns'] != 1 else '')
    hz = p['applied']['frequency']
    out_ma = p['nominal'] * 1000
    return f'Clamp {p["clamp_amps"]:g} A ({turns}) @ {hz:g} Hz, output {out_ma:g} mA'


for _p in POINTS:
    _p['description'] = _describe(_p)
    _p['optional'] = False


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_i400_<cal>_<GROUP>.png, then diagrams/hook_i400_<GROUP>.png (see diagrams/README_i400.txt).  The 5520A uses the 5522A picture."""
    cal = '5522A' if cal == '5520A' else cal
    for name in (f'hook_i400_{cal}_{group}', f'hook_i400_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text, interface='GPIB'):
    """GPIB: '22' -> 'GPIB0::22::INSTR'.  USB: the full USBTMC resource.  A full VISA resource (GPIB / USB / TCPIP) passes through for either choice."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the GPIB address (0 to 30) or a full VISA address (GPIB0::22::INSTR).')
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
    """Bench I/O: the reading multimeter and the calibrator, both through the instrument drivers.  The clamp is wired by the operator (no remote interface)."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5522A', cal_baud=9600, interface='GPIB', transports=None, mods=None, virtual=False,
                 surprise_handler=None, dmm_model=DEFAULT_DMM):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        cal_name, cal_cls = CALIBRATORS[cal_model]
        self.manual = dmm_model == MANUAL
        self.dmm_short = '' if self.manual else DMMS[dmm_model][0]
        if self.manual:
            dmm_t = None
            cal_t = transports[1] if transports else drivers.open_visa(to_cal_visa(cal_address), timeout=20, baud=cal_baud)
        elif transports:
            dmm_t, cal_t = transports
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address, interface), timeout=30)
            cal_t = drivers.open_visa(to_cal_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = None if self.manual else DMMS[dmm_model][1](dmm_t, self.log, label=self.dmm_short)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            if self.dmm is not None:
                self.dmm.connect()
                self.dmm.check_errors('connecting')
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = 'manual entry (no multimeter)' if self.manual else self.dmm.idn
        self.guards = []
        if surprise_handler is not None:
            self.enable_surprise(surprise_handler)

    def enable_surprise(self, handler, force=False):
        """Stop on surprise (surprise.py, opt-in), as the other bench engines: a reply that is not a number for READ?, the meter's set-and-read-back that does not match and the
        calibrator's error queue after an output are Stop-only surprises; the meter's error queue is Stop / Continue.  No write is ever repeated.  A virtual command log is left alone."""
        self.guards = [g for g in ((surprise.attach_guard(self.dmm, handler, force, expect={'read': 'float'}, stop_only=True) if self.dmm is not None else None),
                                   surprise.attach_guard(self.cal, handler, force, stop_only=True)) if g]
        return self.guards

    def reset_roles(self):
        return [self.cal], ([] if self.dmm is None else [self.dmm])

    def pm_drivers(self):
        return (self.cal,) if self.dmm is None else (self.dmm, self.cal)

    def standby(self):
        self.cal.standby_quiet()
        self._lcomp_off()

    def _lcomp_off(self):
        """LCOMP OFF after a coil point (set once, read back, never retried; a failure is logged)."""
        if not getattr(self, '_lcomp_on', False): return
        self._lcomp_on = False
        try:
            self.cal.set_lcomp(False)
            self.cal.check_error('LCOMP OFF')
        except Exception as exc:
            self.log.add('!!', f'LCOMP was NOT confirmed OFF: {exc}', self.cal.label)
        self.cal.standby_quiet()                    # the last command is STBY again: the output is left in standby

    def _lcomp_for(self, p, amps, hz):
        """Table 3 'LCOMP ON' (steps 2 and 3, the 50-turn coil): set on a 5522A / 5520A (LCOMP ON, read back with LCOMP?) after the output is programmed and before it is
        operated.  Not set outside what the calibrator allows (5522A Operators Manual p. 6-23) or on a 5560A (no LCOMP command for its own output: the operator's setting)."""
        if p.get('lcomp') != 'ON' or not hasattr(self.cal, 'set_lcomp'): return
        if not self.cal.lcomp_allowed(amps, hz):
            self.log.add('!!', f'LCOMP not set: {hz} Hz at {amps} A is outside what the calibrator allows', self.cal.label); return
        self.cal.set_lcomp(True)
        self._lcomp_on = True
        surprise.checked(self.cal, self.cal.check_error, p['description'], stop_only=True)

    def close(self):
        try: self.standby()
        except Exception: pass
        if self.dmm is not None:
            try: self.dmm.cleanup()                 # back to front panel control
            except Exception: pass
        for obj in ((self.cal,) if self.dmm is None else (self.dmm, self.cal)):
            try: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt (a virtual demo session writes nothing)."""
        if virtualbench.log_is_virtual(self.log): return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  Fluke {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        return self.pm_param('i400.settle.ac', 6.0)

    def meter_point(self, p):
        """The point as the driver wants it: AC current, the point's range, the spec's AC filter."""
        return dict(p, kind='ACI', ac_bandwidth=p.get('filter_hz') or SPEC['measure']['ac_bandwidth'])

    def _output_and_read(self, p, amps, hz, lcomp=True):
        self.standby()
        try:
            surprise.checked(self.dmm, self.dmm.configure_point, self.meter_point(p), kind='readback', expected='the value that was set', stop_only=True)
            surprise.checked(self.dmm, self.dmm.check_errors, 'configuring ' + p['description'])
            self.cal.set_output_amps(amps, hz, dc=False)
            if lcomp: self._lcomp_for(p, amps, hz)
            surprise.checked(self.cal, self.cal.check_error, p['description'], stop_only=True)   # the calibrator refuses outputs it cannot make; never operate then
            self.cal.operate_unverified()
            time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
            reading = self.dmm.read()
            surprise.checked(self.dmm, self.dmm.check_errors, 'reading ' + p['description'])
            return reading
        finally:
            self.standby()

    def source_point(self, p):
        """Manual entry: the calibrator is set, checked and operated at the point's current; the operator reads the clamp output on their meter and types it.
        The output stays ON until `standby()` (the engine puts it in standby right after the reading is typed)."""
        a = p['applied']
        self.standby()
        try:
            self.cal.set_output_amps(a['value'], a['frequency'], dc=False)
            self._lcomp_for(p, a['value'], a['frequency'])
            surprise.checked(self.cal, self.cal.check_error, p['description'], stop_only=True)
            self.cal.operate_unverified()
            time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
        except Exception:
            self.standby(); raise

    @procmods_engine.point_commands()
    def measure(self, p):
        """The clamp's output for the calibrator current of the point (Table 3: 'Output')."""
        a = p['applied']
        return self._output_and_read(p, a['value'], a['frequency'])

    def measure_direct(self, p):
        """The multimeter pre-calibration (Table 3 footnote): the calibrator straight into the multimeter at the clamp's nominal output (1 mA / 100 mA / 400 mA), LCOMP OFF."""
        return self._output_and_read(p, p['nominal'], p['applied']['frequency'], lcomp=False)


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, demo=False, fast_demo=False):
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.dmm_corr = {}                 # str(point id) -> {'applied': A, 'reading': A, 'correction': A}: the multimeter pre-calibration of that step
        self.pm_init('i400', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('FlukeI400')
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        self.interface = port.var(s.get('interface', 'GPIB') if s.get('interface', 'GPIB') in INTERFACES else 'GPIB')
        self.addrs = {i: s.get(f'dmm_addr_{i}', DEFAULT_ADDR[i]) for i in INTERFACES}
        self._iface_shown = self.interface.get()
        self.dmm_addr = port.var(self.addrs[self._iface_shown])
        self.dmm_model = port.var(s.get('dmm_model', DEFAULT_DMM) if s.get('dmm_model', DEFAULT_DMM) in DMM_CHOICES else DEFAULT_DMM)
        self.precal = port.var(s.get('precal', 'yes') != 'no', 'bool')
        self.cal_offer = calibrator_fit.make_offer('5520A', calibrator_fit.dmm_requests(self.cal_requests()), unverified=drivers.Fluke5520A.unverified_summary())
        self.cal_model = port.var(s.get('cal_model', 'Fluke 5522A') if s.get('cal_model', 'Fluke 5522A') in CALIBRATORS else 'Fluke 5522A')
        self.cal_addr = port.var(s.get('cal_addr', 'COM9'))        # calibrators are typically on RS-232
        self.cal_baud = port.var(s.get('cal_baud', '9600'))
        self.period = port.var(s.get('period', PERIOD_LABEL[SPEC['default_period']]) if s.get('period') in PERIODS else PERIOD_LABEL[SPEC['default_period']])
        self.test_set = port.var('Full verification')
        self.include_optional = port.var(False, 'bool')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the multimeter, the calibrator and the addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    VIEW = 'i400_view'                          # window code: i400_view_qt.py

    @property
    def ui_view(self): return port.view(self.VIEW)

    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    @property
    def manual(self): return self.dmm_model.get() == MANUAL

    @property
    def precal_on(self): return bool(self.precal.get()) and not self.manual      # manual entry: no pre-calibration (the operator applies any meter correction)

    @property
    def dmm_short(self): return '' if self.manual else DMMS[self.dmm_model.get()][0]

    def cal_choices(self):
        """All three calibrators are offered (the owner's choice); the 5520A note says whether its published specification covers every sourced current."""
        return list(CALIBRATORS)

    def cal_requests(self):
        """What the calibrator is asked for at every point (the sourced current and frequency), for the 5520A fit note."""
        return [dict(source='calibrator', kind='ACI', nominal=p['applied']['value'], frequency=p['applied']['frequency'], description=p['description'], id=p['id'])
                for p in POINTS]

    def active(self, p):
        if p.get('skip'): return False                               # a point skipped by a procedure modification
        return True

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

    def on_interface(self):
        """GPIB <-> USB: keep the address typed for the interface just left and show the one remembered for the new one."""
        old, new = self._iface_shown, self.interface.get()
        if new == old: return
        self.addrs[old] = self.dmm_addr.get()
        self.dmm_addr.set(self.addrs[new]); self._iface_shown = new
        self.ui_view.set_choices(self, 'dmm', ())
        if not self.demo: self._save_settings()

    def on_dmm(self):
        """A different reading multimeter: the next connection uses it (an open connection is closed first)."""
        if self.io is not None and not self.busy:
            self.disconnect()
        if not self.demo: self._save_settings()
        self.refresh()

    def pm_driver_classes(self): return (*(() if self.manual else (DMMS[self.dmm_model.get()][1],)), *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_i400 import make_i400_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5522A'

        def build(mods):
            _bench, ft, dt = make_i400_bench(CALIBRATORS[cal_model][0], self.interface.get())
            dt.path, dt.turns = 'clamp', p['turns']
            return IO('sim', 'sim', cal_model, 9600, self.interface.get(), transports=(dt, ft), mods=mods, dmm_model='Keysight 34410A')
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
        for records in (self.found, self.left):     # re-judge stored readings (As Found and As Left) against the limits
            for key, rec in records.items():
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        rec = self.results.get(str(p['id']), {})
        corr = ''
        if 'raw' in rec:
            raw_v, _r2, raw_u = ui.si_row([rec['raw'], rec.get('correction', 0.0)], p['unit'])
            corr = f'\nMultimeter reading {raw_v[0]} {raw_u}, pre-calibration correction {raw_v[1]} {raw_u}'
        elif str(p['id']) in self.dmm_corr:
            c = self.dmm_corr[str(p['id'])]
            cv, _r3, cu = ui.si_row([c['correction']], p['unit'])
            corr = f'\nMultimeter pre-calibration correction at this step: {cv[0]} {cu}'
        self.detail.set(f'{p["description"]}\nCalibrator output {p["applied"]["value"]:g} A at {p["applied"]["frequency"]:g} Hz, '
                        f'LCOMP {p["lcomp"]}  |  Manual page 6 ({p["ref"]})\nSetup: {self.setup_text(p)}'
                        + corr + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    # ------------------------------------------------------------------ wiring text
    def _dmm_input(self): return 'your meter\'s AC current input (and COM)' if self.manual else DMM_INPUT[self.dmm_short]

    def _cal_out(self, group):
        """The calibrator terminals of a group (the 376 / 365 texts: 5560A VI AUX / 30A, 5522A and 5520A AUX / 20 A)."""
        k = self.cal_key
        if group == 'COIL_20A':
            return '30A and OUTPUT LO' if k == '5560A' else '20 A and AUX LO'
        return 'VI AUX (HI) and OUTPUT LO' if k == '5560A' else 'AUX HI and AUX LO'

    def setup_text(self, g):
        group = g['group'] if isinstance(g, dict) else g
        cal = self.cal_key
        out = self._cal_out(group)
        meter = f'the multimeter {self._dmm_input()} (AC current, ' + ('range ' + ('10 mA' if group == 'WIRE_1T' else '1 A') + ')')
        if group == 'DMM_REF':
            return (f'Calibrator {self._cal_out("WIRE_1T")} straight to {self._dmm_input()} of the multimeter (no clamp, no wire loop). LCOMP OFF. '
                    'The program applies the clamp\'s nominal output (1 mA at 45 Hz, 100 mA at 400 Hz, 400 mA at 60 Hz) and reads the multimeter.')
        if group == 'WIRE_1T':
            return (f'Calibrator {out} through a single-turn copper wire loop (larger than #14 gauge, about 6 in diameter); close the clamp jaws round the wire, centred (Figure 2, p. 6). '
                    f'Clamp output cable to {self._dmm_input()}. LCOMP OFF. (Calibrator: {cal}.)')
        lcomp = ('The program turns LCOMP ON at the calibrator for this point (and OFF afterwards).' if cal != '5560A'
                 else 'The 5560A has no LCOMP command for its own output: set compensation on the calibrator yourself if your 5560A configuration needs it.')
        return (f'Calibrator {out} through the 50-turn coil (Fluke 5500A/Coil); close the clamp jaws round the coil, centred (Figure 3, p. 7). '
                f'The clamp reads 50 x the calibrator current. Clamp output cable to {self._dmm_input()}. {lcomp}')

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
        self.ui_view.set_choices(self, 'dmm', mine or found); self.ui_view.set_choices(self, 'cal', asrl or found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _new_io(self):
        if self.virtual:          # demo: the real IO / driver code over a simulated reading multimeter, calibrator and clamp
            from drivers.simulated_i400 import make_i400_bench
            self._vb = make_i400_bench(self.cal_key, self.interface.get())
            return IO('virtual', 'virtual', self.cal_model.get(), 9600, self.interface.get(), transports=(self._vb[2], self._vb[1]), mods=self.pm_state, virtual=True,
                      dmm_model=MANUAL if self.manual else 'Keysight 34410A')            # the simulated multimeter answers as a 34410A whatever model is chosen
        return IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), self.interface.get(), mods=self.pm_state,
                  surprise_handler=self._surprise_handler(), dmm_model=self.dmm_model.get())

    def _surprise_handler(self):
        """The Stop / Continue dialog for stop-on-surprise, made ON the UI thread, once per window.  None in demo: the simulated bench never prompts."""
        if self.demo or self.fast_demo: return None
        if getattr(self, '_sp_handler', None) is None: self._sp_handler = port.surprise_handler(self.root)
        return self._sp_handler

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect(); self.io = self._new_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        warn = '' if self.io.dmm is None else self.io.dmm.firmware_warning()
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.' + (f' WARNING: {warn}.' if warn else ''))
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'Reading: {self.dmm_model.get()} - {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}{tag}\n'
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
        for key, var in (('interface', self.interface), ('cal_model', self.cal_model), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period),
                         ('dmm_model', self.dmm_model)):
            self.settings.set(key, var.get())
        self.settings.set('precal', 'yes' if self.precal.get() else 'no')
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

    def _prompt_start(self):
        """Reference conditions (p. 3) and the safety checks, asked once at the start of a run. Returns False if the technician cancels."""
        return port.operator_prompt('Before the verification', 'Conditions and the clamp',
            [('Clamp', 'Inspect the clamp before use (cracks, damaged jaw insulation, output cable). Do not use a damaged clamp (Maintenance, p. 4). Clean the jaw-mating surfaces: a dirty jaw closes badly and gives errors.'),
             ('Conditions', 'Reference conditions (p. 3): 23 +/- 5 C, 20 to 75 % RH, the conductor centred in the jaw opening, no dc component, no adjacent conductor.'),
             ('Warm-up', 'Allow the calibrator and the reading multimeter their own warm-up time (the i400 manual states none).'),
             ('Multimeter', 'Manual entry: you read the clamp output on your own multimeter (AC current, mA range) and type the reading in mA when asked. The program only drives the calibrator.' if self.manual else
                            f'The reading multimeter ({self.dmm_model.get()}) is set by the program: AC current, manual range, AC filter. Its mA/A input is fused: use the input that carries 408 mA.')],
            facts=[('Limits', 'as printed in the manual (Table 3, p. 6)'), ('Calibrator', self.cal_model.get()), ('Reading multimeter', self.dmm_model.get()),
                   ('Multimeter pre-calibration', 'ON' if self.precal_on else 'OFF')],
            caution='The program restores the multimeter and calibrator to their factory defaults before the first point. Stay at the bench: up to 8 A flows through the coil.',
            ok='Conditions met - start', parent=self.root)

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        if not self.fast_demo and not self._prompt_start(): self.status.set('Run not started: conditions were not confirmed.'); return
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._precal_phase(points))     # every run (first, re-run, resume): reset to defaults before the first point

    # ------------------------------------------------------------------ multimeter pre-calibration
    def _need_precal(self, points):
        return [p for p in points if str(p['id']) not in self.dmm_corr] if self.precal_on else []

    def _prompt_precal(self, steps):
        image = find_diagram(self.cal_key, 'DMM_REF')
        facts = [('Steps', ', '.join(f'{p["clamp_amps"]:g} A ({p["nominal"] * 1000:g} mA @ {p["applied"]["frequency"]:g} Hz)' for p in steps)), ('Calibrator', self.cal_model.get())]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_i400_{self.cal_key}_DMM_REF.png)'))
        self.io.standby()
        return port.operator_prompt('Multimeter pre-calibration', 'Calibrator straight into the multimeter',
            [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text('DMM_REF')),
             ('Why', 'Table 3 footnote (p. 6): to obtain the best TUR the multimeter is pre-calibrated at each step with the calibrator, LCOMP OFF, and its error is added to the clamp reading.')],
            facts=facts, caution='Continue only after physically verifying the connections. No clamp is in the circuit.', ok='Connections verified - measure',
            image=image, parent=self.root)

    def _precal_phase(self, points):
        steps = self._need_precal(points)
        if not steps:
            self._next(points, 0, None); return
        if self.fast_demo:
            for p in steps:
                self.dmm_corr[str(p['id'])] = dict(applied=p['nominal'], reading=p['nominal'], correction=0.0)
            self._next(points, 0, None); return
        if not self._prompt_precal(steps):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if self.virtual: self._virtual_path('direct', 1)

        def work():
            try:
                done = {}
                for p in steps:
                    if self.stop: break
                    port.post(self.root, lambda p=p: self.status.set(f'Multimeter pre-calibration: {p["nominal"] * 1000:g} mA @ {p["applied"]["frequency"]:g} Hz'))
                    done[str(p['id'])] = self.io.measure_direct(p)
                port.post(self.root, lambda: self._precal_done(points, steps, done))
            except Exception as exc:
                try: self.io.standby()
                except Exception: pass
                err = exc
                port.post(self.root, lambda err=err: self._error(err))
        threading.Thread(target=work, daemon=True).start()

    def _precal_done(self, points, steps, done):
        for p in steps:
            reading = done.get(str(p['id']))
            if reading is not None:
                self.dmm_corr[str(p['id'])] = dict(applied=p['nominal'], reading=reading, correction=p['nominal'] - reading)
        self.save(silent=True)
        self._next(points, 0, None)

    # ------------------------------------------------------------------ the points
    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Calibrator output', f'{p["applied"]["value"]:g} A at {p["applied"]["frequency"]:g} Hz'),
                 ('LCOMP', p['lcomp']), ('Manual page', 'p. 6 (' + p['ref'] + ')')]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_i400_{self.cal_key}_{group}.png)'))
        self.io.standby()
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p)),
                 ('Clamp', 'Jaws fully closed, the conductor centred in the jaw opening, no other conductor near the clamp.')]
        caution = 'Continue only after physically verifying the connections.'
        if group != 'WIRE_1T':
            caution = f'Up to {p["applied"]["value"]:g} A flows in the coil. Keep the calibrator in STANDBY whenever you touch the coil or the leads. ' + caution
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}', steps, facts=facts, caution=caution,
                                    ok='Connections verified - continue', image=image, parent=self.root)

    def _virtual_path(self, path, turns):
        """What the virtual operator does after a hook-up prompt: wire the calibrator straight into the multimeter or through the clamp (and the turns)."""
        if getattr(self, '_vb', None):
            dmm = self._vb[2]
            dmm.path, dmm.turns = path, turns

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = (p['source'], p['group'])
        if not self.fast_demo and (key != previous or previous == 'direct') and not self._prompt_setup(p):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.virtual: self._virtual_path('clamp', p['turns'])
        if self.fast_demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self._record(p, reading, True, raw=reading); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
        elif self.manual:
            def work():
                try:
                    self.io.source_point(p)
                    port.post(self.root, lambda: self._ask_typed(points, i, p, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.io.standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def parse_typed_ma(text):
        """The typed clamp-output reading in mA -> amps (Decimal-exact text; ValueError if it is not a number)."""
        t = str(text).strip().replace(',', '')
        try:
            value = Decimal(t)
        except Exception:
            raise ValueError(f'"{text}" is not a number. Type the multimeter reading in mA.')
        if not value.is_finite():
            raise ValueError(f'"{text}" is not a number. Type the multimeter reading in mA.')
        return float(value / 1000)

    def _ask_typed(self, points, i, p, key):
        """Manual entry: the calibrator output is ON at the point; the operator types the reading in mA, then the output goes to standby."""
        shim = dict(p, n=p['id'], test='numeric', dsb_desc=p['description'], section=p['section_title'], switch='AC mA  (clamp output cable on the multimeter current input)', range='')
        lo, hi = (p['nominal'] - p['error']) * 1000, (p['nominal'] + p['error']) * 1000
        fill = dict(demo_fill=lambda: virtualbench.plausible_text(f'{lo:.6g}', f'{hi:.6g}', p['id'], self.virtual_failures())) if self.virtual else {}
        try:
            import handheld_dmm
            r = handheld_dmm.ask_reading(self.root, shim, len(POINTS), f'{p["applied"]["value"]:g} A at {p["applied"]["frequency"]:g} Hz through {p["turns"]} turn' + ('s' if p['turns'] != 1 else '')
                                 + f' (LCOMP {p["lcomp"]})', f'Clamp {p["clamp_amps"]:g} A: expect {p["nominal"] * 1000:g} mA', f'{lo:.6g} to {hi:.6g} mA', 'numeric',
                                 unit='mA', validate=self.parse_typed_ma, device='MULTIMETER', source='CLAMP OUTPUT', **fill)
        finally:
            try: self.io.standby()
            except Exception: pass
        if r['action'] == 'stop':
            self.busy = False; self.stop = True; self._next(points, len(points), key); return
        if r['action'] == 'skip':
            port.after(self.root, 30, lambda: self._next(points, i + 1, key)); return
        reading = self.parse_typed_ma(r['text'])
        self._record(p, reading, bool(self.demo), raw=reading)
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _done(self, points, i, p, reading, key):
        corr = self.dmm_corr.get(str(p['id']))
        corrected = reading + corr['correction'] if (corr and self.precal_on) else reading
        self._record(p, corrected, bool(self.demo), raw=reading); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, raw=None):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        corr = self.dmm_corr.get(str(p['id']))
        extra = dict(raw=raw, correction=(corr['correction'] if corr and self.precal_on else 0.0), precal=bool(self.precal_on and corr)) if raw is not None else {}
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()],
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **extra, **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'Fluke{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, period=self.period.get(), dmm_corr=self.dmm_corr,
                                        dmm_model=self.dmm_model.get(), cal_model=self.cal_model.get(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get()) if data.get('period') in PERIODS else self.period.get())
        self.dmm_corr = dict(data.get('dmm_corr') or {})
        self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    @staticmethod
    def report_section(p):
        return p['section_title']

    def standard_for(self, p):
        """The standard that applied a point, for the uncertainty / TAR / TUR: the selected calibrator, or the 50-turn coil's sheet where it covers the point."""
        return self.cal_key if self.cal_key in ('5522A', '5560A', '5520A') else None

    def _unc_point(self, p):
        """(q, standard) the uncertainty of a point is worked out with.  The 1 A wire point is the calibrator at 1 A; a coil point is the coil rule's (the coil's sheet at the
        effective current plus the clamp / coil interaction, or the calibrator's figure at the sourced current scaled x50 below the coil's range)."""
        a = p['applied']
        if p['turns'] == 1:
            return dict(kind='ACI', nominal=a['value'], frequency=a['frequency'], unit='A', range=None), self.standard_for(p)
        nom, std, extra = coil_rule.uncertainty_source('ACI', p['clamp_amps'], a['value'], a['frequency'])
        q = dict(kind='ACI', nominal=nom, frequency=a['frequency'], unit='A', range=None, extra=extra)
        scale = coil_rule.uncertainty_scale('ACI', p['clamp_amps'], a['frequency'])
        if scale != 1.0:
            q['scale'] = scale
        return q, (std or self.standard_for(p))

    def certificate_row(self, p, r):
        import report_pdf
        q, std = self._unc_point(p)
        return report_pdf.cert_row(p['description'], p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'], r['reading'], r['result'] == 'FAIL',
                                   section=self.report_section(p), frequency=p['applied']['frequency'], uncertainty=report_pdf.point_uncertainty(q, std))

    def certificate_fields(self, p):
        """TAR / TUR of a point (tartur.row_fields) in clamp amps: the tolerance is the clamp's own, the uncertainty the standard's at the point."""
        try:
            import tartur
            q, std = self._unc_point(p)
            half = float(f'{p["error"] / 0.001:.9g}')                       # clamp amps: the output is 1 mA/A
            c = p['clamp_amps']
            return tartur.row_fields(q, float(f'{c - half:.9g}'), float(f'{c + half:.9g}'), standard=std)
        except Exception:
            return dict(TAR='', TUR='')

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the spec point each came from (for the optional TAR / TUR fields)."""
        rows, pts = [], []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row: rows.append(row); pts.append(p)
        return rows, pts

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'{TITLE} performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        try:
            if details.get('show_tar_tur'):
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [self.certificate_fields(p) for p in pts])
            std = self.cal_key if self.cal_key in ('5522A', '5560A', '5520A') else None
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', TITLE), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Calibrator', self.cal_model.get()), ('Reading multimeter', (self.dmm_model.get() if self.manual else f'{self.dmm_model.get()} ({self.io.ident if self.io else "not connected"})')),
                                                                 ('Multimeter pre-calibration', 'applied (Table 3 footnote)' if self.precal_on else 'not applied'),
                                                                 ('Limits applied', self.period.get()), ('Source', 'Fluke i400 Calibration Information 2414311, Table 3 (p. 6)')],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, std), snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True
        if not self.demo: self._save_settings()
        self.disconnect(); port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, demo=demo, fast_demo=fast)
    port.run_app(build)
