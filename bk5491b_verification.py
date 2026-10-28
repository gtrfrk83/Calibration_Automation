"""B&K Precision 5491B 5-1/2 digit bench multimeter: performance verification, driven from the lab datasheet and the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/bk_5491b_pv.json (built by specs/build_bk_5491b_spec.py from the lab's datasheet
B_K_Precision_5491B_Digital_Multimeter__365_Days_.MDD, cross-checked against the 2831E / 5491B User Manual, Chapter 7, pp. 67 to 72). Two limit sets are offered: the lab datasheet
(default) and the manufacturer specification; a point is good when LOW <= reading <= HIGH (judged in Decimal, so a reading exactly on a limit passes).

Bench: the 5491B over RS-232 or its USB virtual COM port, and a Fluke 5522A, 5560A or 5520A calibrator. The program configures the meter for every point (function, fixed range,
slow rate), drives the calibrator and reads the result. It pauses for a hook-up whenever the wiring changes and never runs unattended. Points the selected calibrator cannot make are
measured with a standard the technician connects (the meter is still read automatically). Hardware I/O is OFF in demo mode. There is no adjustment here: this is verification only.

    import bk5491b_verification
    bk5491b_verification.main()         # what Procedures/BK_5491B_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in bk5491b_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import calibrator_fit
import datamode
import procmods_engine
import reset_startup
import procspec
import drivers
import manual_override
from drivers.base import InstrumentError, SafetyError
from drivers.bk_5491b import BK5491B, range_value

MODEL = '5491B'
SPEC_PATH = HERE / 'specs' / 'bk_5491b_pv.json'
SPEC = POINTS = None
PERIODS = {'Lab datasheet (MDD)': 'mdd', 'Manufacturer specification': 'mfr'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
CALIBRATORS = {'Fluke 5522A': ('5522A', drivers.Fluke5522A), 'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5520A': ('5520A', drivers.Fluke5520A)}
FIT_MODELS = {'Fluke 5520A': '5520A', 'Fluke 5522A': '5522A', 'Fluke 5560A': '5560A'}     # every calibrator's points are decided by calibrator_fit (its published specification)
TERMINATORS = {'LF (line feed)': '\n', 'CR (carriage return)': '\r'}     # the meter's menu TX TERM (User Manual 4.5.3); the factory setting is not printed: UNVERIFIED
BAUDS = ['9600', '19200', '38400', '4800', '2400', '1200', '600']
GROUP_TITLE = {'VOLT': 'Voltage and frequency inputs (V / ohm and COM)', 'OHM2': '2-wire resistance (V / ohm and COM)', 'IMA': 'Current, 500 mA terminal', 'I20A': 'Current, 20 A terminal'}
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'FREQ')
WARM_UP = ('The 5491B needs a half-hour warm-up before verification (User Manual, Section 2.6.6 and Chapter 7: after 30 minutes warm-up). The specifications are given '
           'for the slow rate (NPLC 10), which the program selects.')


class SpecError(procspec.SpecError):
    pass


def load_spec(path=SPEC_PATH):
    """Read and check the spec (kind 'bench-dmm-band'): every point has a low and a high limit for every period, a range the meter has, and a group."""
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('kind') != 'bench-dmm-band' or spec.get('model') != MODEL:
        raise SpecError("not a 'bench-dmm-band' spec for the 5491B")
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
            if p['source'] != 'calibrator':
                raise SpecError(f'{where}: source must be calibrator')
            try:
                range_value(p['kind'], p['range'])
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
            p['page'] = f"{raw['page']} (datasheet step {raw['row']})"
            p['optional'] = False
            p['description'] = describe(p)
            points.append(p)
    return points


def describe(p):
    name = 'Continuity' if p.get('function') == 'CONT' else 'Resistance' if p['kind'] == 'OHM2' else procspec.NAMES[p['kind']]
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


def prompt_key(p):
    """What decides whether the hook-up prompt is shown again: the wiring group."""
    return p['group']


class ReadingUnavailable(InstrumentError):
    """The automatic reading of a point failed (timeout, unreadable, overload). Same message as the error it wraps; the App offers a typed reading (manual_override)."""


def judge(p, reading):
    """True when LOW <= reading <= HIGH, in Decimal (a reading exactly on a limit passes)."""
    value = Decimal(repr(float(reading)))
    return Decimal(repr(float(p['low']))) <= value <= Decimal(repr(float(p['high'])))


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_5491B_<cal>_<GROUP>.png, then diagrams/hook_5491B_<GROUP>.png."""
    cal = '5522A' if cal == '5520A' else cal             # the 5520A uses the 5522A picture (same NORMAL / AUX terminals; UNVERIFIED)
    for name in (f'hook_{MODEL}_{cal}_{group}', f'hook_{MODEL}_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def open_meter_port(address, dmm_serial):
    """The 5491B's COM port (RS-232 or the USB virtual COM port) is opened with pyserial, NOT through VISA: the meter's character-by-character echo handshake (manual
    5.2.4 item 3) worked at once with pyserial (owner's probe, 2026-10-28) and got no reply through VISA's ASRL driver. A VISA-style resource ('ASRL12::INSTR') is
    turned back into its COM port. Returns an unopened transport."""
    t = address.strip()
    up = t.upper()
    if up.startswith('ASRL') and '::' in up:
        t = 'COM' + up[4:].split('::')[0]
    elif up.isdigit():
        t = 'COM' + up
    if not t.upper().startswith('COM'):
        return drivers.open_visa(to_visa(address), timeout=30, **(dmm_serial or {}))
    from drivers.transport import SerialSettings, SerialTransport
    return SerialTransport(t, SerialSettings(**(dmm_serial or {})), timeout=30)


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


# Settle times from OPER to the first FETC?: ENGINEERING ESTIMATES, NOT from a manual (the manual gives no settling figure). Tune them on the real meter (procedure modifications
# 'bk5491b.settle.*'). The 20 A terminal and the AC functions are the ones most likely to need longer.
DEFAULT_SETTLE_S = 2.0
AC_SETTLE_S = 4.0
FREQ_SETTLE_S = 3.0
OHM_HIGH_SETTLE_S = 4.0
I20A_SETTLE_S = 6.0


class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the 5491B and the calibrator, both through the instrument drivers."""

    dmm_down = ''          # not empty = typed-readings mode: the meter could not be reached at connect time, the calibrator is driven and the technician types each reading

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5522A', cal_baud=9600, dmm_serial=None, transports=None, mods=None, meter_optional=False):
        self.log = drivers.CommandLog()
        cal_name, cal_cls = CALIBRATORS[cal_model]
        self.is_manual = lambda p: False        # the App sets this: points measured with a standard the technician connects
        if transports:
            dmm_t, cal_t = transports
        else:
            try:
                dmm_t = open_meter_port(dmm_address, dmm_serial)
            except Exception as exc:
                if not meter_optional: raise
                dmm_t = None; self.dmm_down = str(exc)
            cal_t = drivers.open_visa(to_visa(cal_address), timeout=20, baud=cal_baud)
        self.dmm = BK5491B(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            if self.dmm_down:
                pass                                  # the port itself could not be opened above: no connect attempt
            elif meter_optional:
                try: self.dmm.connect()
                except Exception as exc: self.dmm_down = str(exc)        # one connect attempt only (connect() already allowed its single read-only *IDN? retry)
            else:
                self.dmm.connect()
            if self.dmm_down:
                self.log.add('!!', f'5491B not connected ({self.dmm_down}); typed-readings mode: the calibrator is driven, the technician types each reading', MODEL)
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.dmm.idn if not self.dmm_down else 'meter not connected'

    def reset_roles(self):
        return [self.cal], ([] if self.dmm_down else [self.dmm])

    def pm_drivers(self):
        return (self.dmm, self.cal)

    def standby(self):
        self.cal.standby_quiet()

    def session_check(self):
        """A Run that skips the reset (once per session): everything the reset did EXCEPT *RST / defaults. Calibrator to STANDBY and confirmed (OPER? = 0, raises
        SafetyError otherwise); both instruments still identify themselves (read-only queries, retried); the meter's trigger source
        are guaranteed again (BK5491B.ensure_run_state); each error status is read once and logged, never retried. Returns the log summary."""
        self.cal.standby()
        ident = self.cal.query_retry('*IDN?').strip()
        if self.cal.IDN_MATCH and not any(m.upper() in ident.upper() for m in self.cal.IDN_MATCH):
            raise InstrumentError(f'Unexpected calibrator identification: {ident}')
        if self.dmm_down:
            self.log.add('--', 'session check: calibrator in STANDBY and answers; meter not connected (typed readings)', 'RESET')
            return 'meter not connected'
        state = self.dmm.ensure_run_state()
        flags = self.dmm.session_check()
        reply = self.cal.read_error()
        code = reply.split(',')[0].strip()
        if code not in ('0', '+0'):
            self.log.add('!!', f'calibrator error queue before the run: {reply}', self.cal.label)
        self.log.add('--', f'session check: calibrator in STANDBY, both instruments answer; {state}' + (('; meter status: ' + ', '.join(flags)) if flags else ''), 'RESET')
        return state

    def close(self):
        try: self.standby()
        except Exception: pass
        try: self.dmm.cleanup()
        except Exception: pass
        for obj in (self.dmm, self.cal):
            try: obj.close()
            except Exception: pass
        self.save_log()

    _logged = 0          # log lines already appended to the shared log (a failed reset saves the log while the window stays open; close() adds only the rest)

    def save_log(self):
        """Append the exact commands sent (not yet saved) to ~/.calibration_suite/command_log.txt."""
        lines = self.log.lines()
        new = lines[self._logged:]
        if not new:
            return
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  B&K {MODEL} session\n' + '\n'.join(new) + '\n')
            self._logged = len(lines)
        except OSError:
            pass

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        if p['kind'] == 'FREQ': return self.pm_param('bk5491b.settle.freq', FREQ_SETTLE_S)
        if p['kind'] in ('ACV', 'ACI'): return self.pm_param('bk5491b.settle.ac', AC_SETTLE_S)
        if p['kind'] == 'OHM2' and p['range'] >= 5e6: return self.pm_param('bk5491b.settle.ohm_high', OHM_HIGH_SETTLE_S)
        if p['kind'] in ('DCI', 'ACI') and p['range'] >= 5.0: return self.pm_param('bk5491b.settle.i20a', I20A_SETTLE_S)      # UNVERIFIED estimate
        return self.pm_param('bk5491b.settle.default', DEFAULT_SETTLE_S)

    def _read(self, p=None):
        """The meter's reading (FETC?, twice, the second used). A failure is re-raised as ReadingUnavailable with the same text, so the window can offer a typed reading."""
        try:
            return self.dmm.read(p)
        except SafetyError:
            raise
        except Exception as exc:
            raise ReadingUnavailable(str(exc)) from exc

    def after_read_failure(self, p, exc):
        """After a failed automatic reading, so the run can go on with a typed one: calibrator to STANDBY, unsolicited meter output thrown away (read-only),
        the meter's error status read ONCE so a leftover bit does not stop the next point (not when the meter did not answer at all; never retried)."""
        self.log.add('!!', f'reading failed ({exc}); a manually entered reading may replace it', MODEL)
        if self.dmm_down: return                           # typed-readings mode: the output stays on until the reading is typed (App._reading_failed), nothing to clear on the meter
        try: self.standby()
        except Exception: pass
        cause = exc.__cause__
        try: self.dmm._discard_input('after a failed reading')
        except Exception: pass
        if isinstance(cause, InstrumentError):
            try: self.dmm.check_errors('the failed reading of ' + p['description'])
            except Exception as err: self.log.add('!!', f'error status after the failed reading: {err}', MODEL)

    def _meter_down_error(self):
        return ReadingUnavailable(f'{MODEL} not connected ({self.dmm_down}): read the meter display and type the reading')

    @procmods_engine.point_commands()
    def measure(self, p):
        self.standby()
        if self.dmm_down and self.is_manual(p):
            raise self._meter_down_error()                     # your own standard is on the meter: nothing for the program to set, the technician reads and types
        if not self.dmm_down:
            self.dmm.configure_point(p)
        if not self.dmm_down:
            self.dmm.check_errors('configuring ' + p['description'])
        if self.is_manual(p):              # the technician has connected a standard: the calibrator stays in STANDBY, the meter is read
            time.sleep(self.settle(p))
            reading = self._read(p)
            self.dmm.check_errors('reading ' + p['description'])
            return reading
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'ACV'): self.cal.set_output_volts(v, f, dc=k == 'DCV')
        elif k in ('DCI', 'ACI'): self.cal.set_output_amps(v, f, dc=k == 'DCI')
        elif k == 'OHM2': self.cal.set_output_ohms(v)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], v)
        self.cal.check_error(p['description'])   # the calibrator refuses outputs it cannot make; never operate then
        self.cal.operate_unverified()
        time.sleep(self.settle(p))
        if self.dmm_down:
            raise self._meter_down_error()                     # the output stays ON for the technician to read the meter; the App sends STANDBY once the reading is typed (or the run is stopped)
        reading = self._read(p)
        self.standby()
        self.dmm.check_errors('reading ' + p['description'])
        return reading


class App(reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # the owner's request: type a reading instead of the automatic one (manual_override.py); the 5491B also carries on with typed readings when the meter will not connect
    _hv_confirmed = None              # the hook-up key for which the high-voltage question was answered Yes in this run

    def __init__(self, root, model=MODEL, demo=False):
        configure(model)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('bk5491b', MODEL, demo=demo, lists=[POINTS], shape='band')         # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(MODEL)
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        ports = list_com_ports()
        self.dmm_addr = port.var(s.get('dmm_addr', ports[0] if ports else 'COM1'))
        self.dmm_baud = port.var(s.get('dmm_baud', '9600'))
        self.dmm_term = port.var(s.get('dmm_term', 'LF (line feed)') if s.get('dmm_term', 'LF (line feed)') in TERMINATORS else 'LF (line feed)')
        self.cal_offers = {name: calibrator_fit.make_offer(key, calibrator_fit.dmm_requests(POINTS), per_point_manual=True, name=name,
                                                           unverified=drivers.Fluke5520A.unverified_summary() if key == '5520A' else '') for name, (key, _cls) in CALIBRATORS.items()}
        self._fit_manual = {key: {r.key: reason for r, reason in self.cal_offers[name].manual} for name, (key, _cls) in CALIBRATORS.items()}   # calibrator -> point id -> why it cannot make it
        self.cal_offer = self._combined_offer()
        self.cal_model = port.var(s.get('cal_model', 'Fluke 5522A') if s.get('cal_model', 'Fluke 5522A') in self.cal_choices() else 'Fluke 5522A')
        self.cal_addr = port.var(s.get('cal_addr', 'COM9'))
        self.cal_baud = port.var(s.get('cal_baud', '9600'))
        self.period = port.var(s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self.warm_confirmed = False
        for var in (self.dmm_addr, self.dmm_baud, self.dmm_term, self.cal_model, self.cal_addr, self.cal_baud):
            var.trace_add('write', self.reset_forget)       # the calibrator / interface changed in the settings: the next Run resets again
        self._build_ui()
        self.on_period(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument. Enter an Instrument ID, then press Run All.' if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the connections and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def _combined_offer(self):
        """One note under the calibrator picker for all three calibrators: how many points each cannot make (calibrator_fit, from its published specification)."""
        parts = []
        for name, offer in self.cal_offers.items():
            n = len(offer.manual)
            parts.append(f'{name}: ' + (f'{n} point(s) need your own standard' if n else 'makes every point'))
        text = ('Calibrator limits (from each calibrator\'s published specification): ' + '; '.join(parts) + '. The meter is still read automatically at those points. '
                'The calibrators\' remote commands are not all verified.')
        first = next(iter(self.cal_offers.values()))
        return calibrator_fit.Offer('all', first.fit, True, [], text, '\n\n'.join(o.tooltip for o in self.cal_offers.values()))

    def cal_choices(self):
        """The calibrator picker's values: every calibrator (the engine has a per-point path for what one cannot make; the note under the picker says how many points)."""
        return list(CALIBRATORS)

    def is_manual(self, p):
        """True when the selected calibrator cannot make this point: the technician connects another standard (the meter is still read automatically).
        calibrator_fit decides from the calibrator's published specification (the spec carries no per-calibrator list)."""
        return p['source'] == 'calibrator' and p['id'] in self._fit_manual[self.cal_key]

    def manual_reason(self, p):
        return self._fit_manual[self.cal_key].get(p['id'], '')

    def active(self, p):
        return not p.get('skip')                                     # a point skipped by a procedure modification

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    VIEW = 'bk5491b_view'                              # window code: bk5491b_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

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

    def mo_point(self, iid): return POINTS[int(iid) - 1]
    def mo_total(self): return len(POINTS)

    def pm_driver_classes(self): return (BK5491B, *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_5491b import make_5491b_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5522A'

        def build(mods):
            _bench, ft, dt = make_5491b_bench(CALIBRATORS[cal_model][0])
            io = IO('sim', 'sim', cal_model, 9600, transports=(dt, ft), mods=mods)
            io.is_manual = self.is_manual
            return io
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p))

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
        apply_period(POINTS, PERIODS[self.period.get()])
        self.pm_apply(POINTS)                                        # then put them back (they only apply if they fit this period)
        for records in (self.found, self.left):     # re-judge stored readings (As Found and As Left) against the newly selected limits
            for key, rec in records.items():
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading']) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['low'], p['high']], p['unit'])
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        manual = ('\nYour own standard is used for this point: ' + self.manual_reason(p)) if self.is_manual(p) else ''
        flags = ('\nDatasheet and manual differ: ' + ' | '.join(f['why'] for f in p['flags'])) if p.get('flags') else ''
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}{extra}\n'
                        f'Setup: {self.setup_text(p)}{manual}{flags}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    def setup_text(self, p):
        """Hook-up instruction for a point's wiring group (the calibrator's own terminal names for the one selected)."""
        g = p['group']
        five60 = self.cal_key == '5560A'
        out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
        base = 'Shielded twisted pair, shield to the calibrator LO. '
        if g == 'VOLT':
            return base + f'Calibrator {out} to the meter V / ohm (input high) and COM terminals (User Manual Figure 3-1; the frequency points use the same terminals, Figure 3-4).'
        if g == 'OHM2':
            return (f'2-wire: calibrator {out} to the meter V / ohm and COM terminals (the 5491B measures resistance 2-wire only). Calibrator external sense OFF and its 2-wire '
                    'compensation ON for resistance as your procedure requires; the program does not change them. Use shielded cable above 100 kohm (User Manual Chapter 7).')
        amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX CURRENT HI and LO'
        if g == 'IMA':
            return (f'Calibrator current output ({amps}) to the meter 500 mA terminal and COM (5 mA to 500 mA ranges; the terminal is fuse protected, 1 A / 250 V; User Manual 3.3.1). '
                    'Check the calibrator range first.')
        if g == 'I20A':
            high = 'the calibrator 30A and OUTPUT LO terminals' if five60 else 'the calibrator 20 A output terminals'
            return (f'{high[0].upper() + high[1:]} to the meter 20 A terminal and COM (5 A and 20 A ranges; above 10 A the meter reads for 20 seconds at most, Chapter 7). '
                    'Use heavy leads and keep them short.')
        return p['setup']

    # ------------------------------------------------------------------ connection
    def _serial_kwargs(self):
        end = TERMINATORS[self.dmm_term.get()]
        return dict(baud=int(self.dmm_baud.get()), data_bits=8, parity='none', stop_bits=1, write_termination=end, read_termination=end, flow_control='none')

    def find_instruments(self):
        ports = list_com_ports()
        self.ui_view.set_choices(self, 'dmm', ports); self.ui_view.set_choices(self, 'cal', ports)
        self.status.set(f'{len(ports)} serial port(s) found: ' + (', '.join(ports) if ports else 'none') + '. Pick the 5491B port.' if ports
                        else 'No serial ports found (pip install pyserial, or enter the port name by hand).')

    def _make_io(self, meter_optional=False):
        io = IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), dmm_serial=self._serial_kwargs(), mods=self.pm_state,
                meter_optional=meter_optional)
        io.is_manual = self.is_manual
        return io

    def _typed_readings_only(self):
        """The meter could not be connected (the error was already shown). When File > Settings allows typed readings, offer to carry on with the calibrator driven and every
        reading typed by the technician; returns True when self.io is now such a connection."""
        import app_settings
        if not (self.MANUAL_OVERRIDE and app_settings.manual_override_on()): return False
        if not port.ask_yes_no('Meter not connected', f'The {MODEL} could not be connected.\n\nContinue with typed readings? The calibrator is still driven (and put in STANDBY after each point); '
                               'the output stays on while you read the meter display, then type the reading. Pass / fail is judged with the same limits.'):
            return False
        try:
            self.io = self._make_io(meter_optional=True)
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return False
        if hasattr(self, 'conn_pill'): self.conn_pill.set('Meter not connected - typed readings', 'neutral')
        self.status.set(f'{MODEL} not connected: the calibrator is driven and you type each reading.')
        return True

    def test_connections(self):
        if self.demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect(); self.io = self._make_io()
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True); self._save_settings()
        self.status.set('Connected: ' + self.io.ident + '. Calibrator output is NOT enabled.')
        port.message('info', 'Connected', f'{MODEL}: {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}\nCalibrator output is not enabled.')

    def _reset_failed(self, msg, skipped=False):
        if self.io is not None:
            try: self.io.save_log()          # the command log of the failed reset is on disk before the dialog (not only when the window closes); close() adds only what is new
            except Exception: pass
        super()._reset_failed(msg, skipped)  # status line + error dialog; the window stays open

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('dmm_addr', self.dmm_addr), ('dmm_baud', self.dmm_baud), ('dmm_term', self.dmm_term), ('cal_model', self.cal_model),
                         ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
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

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.demo and not self.warm_confirmed:
            if not port.ask_yes_no('Warm-up', WARM_UP + '\n\nHas the meter been on for at least half an hour?'): return
            self.warm_confirmed = True
        if not self.demo and self.io is None: self.test_connections()
        if not self.demo and self.io is None and not self._typed_readings_only(): return
        self._mo_pending = None; self._mo_current = None
        self.stop = False; self.busy = True; self._hv_confirmed = None     # every Run (first, re-run, resume after Stop) asks the high-voltage question again
        self.reset_then(lambda: self._next(points, 0, None))     # the first Run of a session resets to defaults; later runs (re-run, resume) skip the *RST but still run session_check

    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Specification', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_{MODEL}_{self.cal_key}_{group}.png)'))
        self.io.standby()
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if p['kind'] in ('ACV', 'ACI', 'FREQ'):
            steps.append(('Rate', 'The program selects the slow reading rate (the specifications apply to it); AC readings take a few seconds.'))
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    def _prompt_manual(self, p):
        """The selected calibrator cannot make this point: the technician connects another standard and applies the stated value."""
        f = f' at {procspec._fmt(p["frequency"], "Hz")}' if p.get('frequency') else ''
        value = (f'{procspec._fmt(p["amplitude"], "V")} rms at {procspec._fmt(p["nominal"], "Hz")}' if p['kind'] == 'FREQ'
                 else f'{procspec._fmt(p["nominal"], p["unit"])}{f}')
        self.io.standby()
        steps = [('Why', self.manual_reason(p)),
                 ('Standard', f'Disconnect the calibrator. Connect your own standard to the meter as for {GROUP_TITLE[p["group"]]} and apply {value}. '
                              'Use a standard with enough accuracy for the limits.'),
                 ('Wiring', self.setup_text(p))]
        return port.operator_prompt('Your own standard is needed', f'Point {p["id"]}: {p["description"]}', steps,
                                facts=[('Next point', f'{p["id"]} of {len(POINTS)}'), ('Specification', p['page'])],
                                caution='The meter is read automatically once you press Continue. Apply the value first and let it settle.',
                                ok='Standard applied - measure', image=find_diagram(self.cal_key, p['group']), parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root,30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        manual = self.is_manual(p)
        key = f'MANUAL{p["id"]}' if manual else prompt_key(p)
        if previous is None or key != previous:
            self._hv_confirmed = None                  # a new hook-up group (or a new run): the high-voltage question is asked again
        if not self.demo and key != previous:
            if not (self._prompt_manual(p) if manual else self._prompt_setup(p)):
                self.busy = False; self.status.set('Paused for wiring or setup'); return
        hv = float(SPEC.get('options', {}).get('hv_threshold_v', 100))
        if not self.demo and p['source'] == 'calibrator' and p['kind'] in ('DCV', 'ACV') and abs(p['nominal']) >= hv and self._hv_confirmed != key:
            if not port.ask_yes_no('HIGH VOLTAGE', f'This point puts {p["nominal"]:g} V on the meter input. Verify CAT-rated leads, connections, clearance and personnel safety. Continue?'):
                self.busy = False; return
            self._hv_confirmed = key                   # owner request: one high-voltage confirmation per hook-up group, not one per point (the text is unchanged)
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        self._mo_current = p                           # the point being measured: 'Enter reading manually' applies to it
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.demo:
            mid, half = (p['low'] + p['high']) / 2, (p['high'] - p['low']) / 2
            reading = mid + half * math.sin(p['id'] * 1.71) * 0.38        # deterministic, labelled synthetic
            self._finish_point(p, reading, True, manual); port.after(self.root,30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.io.measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key, manual))
                except Exception as exc:
                    if not (self.io.dmm_down and isinstance(exc, ReadingUnavailable)):       # typed-readings mode: the output stays on until the reading is typed (App._reading_failed)
                        try: self.io.standby()
                        except Exception: pass
                    if isinstance(exc, ReadingUnavailable):
                        try: self.io.after_read_failure(p, exc)
                        except Exception: pass
                        err = exc
                        port.post(self.root, lambda err=err: self._reading_failed(points, i, p, key, manual, err))
                        return
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key, manual=False):
        self._finish_point(p, reading, False, manual); port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _finish_point(self, p, reading, synthetic, manual=False):
        """The automatic reading of point p arrived: record it, or the reading typed for this point while it was measured (manual_override; logged as the auto reading)."""
        typed = self.mo_take_pending(p)
        self._mo_current = None
        if typed is not None: self.mo_commit(p, typed, auto=reading)
        else: self._record(p, reading, synthetic, manual)

    def _reading_failed(self, points, i, p, key, manual, exc):
        """The meter could not be read (timeout, unreadable, overload). The calibrator is already in standby: ask for the reading and carry on, or stop as before."""
        typed = self.mo_failed(p, exc)
        self._mo_current = None
        if self.io is not None and self.io.dmm_down:
            try: self.io.standby()                          # typed-readings mode: the output was left on for the technician to read the meter; off now (typed, cancelled or stopped)
            except Exception: pass
        if typed is None: self._error(exc); return
        self.mo_commit(p, typed, auto=None, why=str(exc))
        port.after(self.root,30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self._mo_current = None; self._mo_pending = None
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, manual=False, extra=None):
        result = 'PASS' if judge(p, reading) else 'FAIL'
        self.results[str(p['id'])] = dict(reading=reading, result=result, synthetic=synthetic, period=PERIODS[self.period.get()], manual=bool(manual),
                                          timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label, **self.pm_result_fields(), **(extra or {}))
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
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
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
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'B&K {MODEL} performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        manual_ids = [p['ref'] for p in pts if (self.left.get(str(p['id'])) or self.found.get(str(p['id'])) or {}).get('manual')]
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'),
                                                [dict(TAR='', TUR='') if p['ref'] in manual_ids else tartur_wiring.point_fields(p, self.cal_key) for p in pts])
            header = [('Instrument', f'B&K {MODEL}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()), ('Limits applied', self.period.get()),
                      ('Source', SPEC['source']['cite'])]
            if manual_ids:
                header.append(('Operator-supplied standard', 'Points measured with a standard connected by the technician: ' + ', '.join(manual_ids)))
            report_pdf.write_calibration_pdf(path, rows, header=header, demo=demo, details=details,
                                             footer_note=report_pdf.uncertainty_note(rows, self.cal_key), snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        App(root, MODEL, demo='--demo' in argv)
    port.run_app(build)
