"""Keithley DMM6500 6.5-digit multimeter performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keithley_dmm6500_pv.json, built by specs/build_dmm6500_spec.py from the Keithley DMM6500
Calibration and Adjustment Manual DMM6500-905-01 Rev. E, section 2 (printed pp. 2-6 to 2-48).  The manual prints one interval (1 year, 18 to 28 C).  Two-way: the program sets the
function and range over USB, LAN or GPIB (SCPI, DMM6500 Reference Manual DMM6500-901-01 Rev. C), sources the point from a Fluke 5560A or a Fluke 5700A (alone or with its 5725A amplifier), reads the meter back with
:READ? (digitize: the average of a captured buffer) and judges it.  Adjustment is NOT part of this program.

STATUS: simulated bench only.  No DMM6500 command has been verified on a real instrument (bench-first workflow, NOTES.md), so every driver command is UNVERIFIED and the
demo runs on drivers/simulated_dmm6500.py, which is hand-written from the manuals.  Hardware I/O is OFF in demo mode.  Never run unattended: wiring confirmations are required.

Reference meter: the manual's resistance (1 ohm, 10 ohm) and DC current (10 uA to 10 mA, 10 A) limits are about a REFERENCE DMM reading.  When a reference meter (a 3458A,
GPIB) is connected, those points are centred on its reading; without one they are centred on the calibrator setting (the 8808A convention) and the report says so.

    import dmm6500_verification
    dmm6500_verification.main()           # what Procedures/Keithley_DMM6500_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, procspec and drivers sit next to the Manager
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, report_filename, Settings); the window code is in dmm6500_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import procspec
import calibrator_fit
import drivers
import appdata
import datamode
import procmods_engine
import manual_override
import reset_startup
import rtd_cvd
import virtualbench

MODEL = 'DMM6500'
SPEC_PATH = HERE / 'specs' / 'keithley_dmm6500_pv.json'
UNITS = dict(procspec.UNITS, DIGV='V', DIGI='A')
NAMES = dict(procspec.NAMES, DIGV='Digitize DC voltage', DIGI='Digitize DC current', TEMP='Temperature')
REPORT_KIND = {'DIGV': 'DCV', 'DIGI': 'DCI'}      # the report / uncertainty tables know the plain function names
PERIODS = {'1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
# Owner decision 2026-11-03: the 5520A and 5522A are NOT offered for this procedure (their accuracy against the DMM6500 limits: TAR below 4:1 at over 100 of 176 points).
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5700A': ('5700A', drivers.Fluke5700A), 'Fluke 5700A + 5725A': ('5700A', drivers.Fluke5700A)}
AMPLIFIER_MODELS = ('Fluke 5700A + 5725A',)  # the 5700A with its 5725A amplifier (BOOST): the points above the 5700A's own range are made through it
FIT_MODELS = {'Fluke 5700A': '5700A', 'Fluke 5700A + 5725A': '5700A'}      # calibrators with a per-point 'your own standard' path: calibrator_fit (their published specification) decides which points they cannot source
INTERFACES = ('USB', 'LAN', 'GPIB')
CAL_INTERFACES = ('RS-232', 'GPIB')
CAL_PORT_DEFAULT = {'RS-232': 'COM9', 'GPIB': 'GPIB0::4::INSTR'}   # editable; the GPIB address is only an example (UNVERIFIED, set the calibrator's real address)
ZERO_CHOICES = ('Include', 'Skip')         # the 4-wire short zero checks are not part of the manufacturer's customer report (p. 2-41)
HV_CONFIRM = 100.0                         # volts: a high-voltage confirmation before any DC / AC volts point of this size or more
# Settling times from OPER to the first reading (seconds). ENGINEERING ESTIMATES except where the manual states one (5 minutes after 0 V on the 100 mV DC range and for the
# thermal offset of the thermocouple cable, p. 2-8 / 2-19; 5 minutes with the 4-wire short fitted, p. 2-42). Tunable through the procedure modifications ('dmm6500.settle.*').
SETTLE = dict(default=3.0, ac=10.0, rel_zero=300.0, tc_offset=300.0, short_first=300.0, short=5.0, dci=5.0, ohm=3.0, ohm_high=5.0, cap=2.0)
GROUP_TITLE = {'DCV': 'DC volts', 'ACV': 'AC volts', 'ACV750': 'AC volts 750 V range', 'FREQ': 'Frequency', 'TC': 'Thermocouple', 'RTD4': '4-wire RTD', 'RTD3': '3-wire RTD',
               'SHORT4': '4-wire short zero checks', 'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms', 'DCI_LOW': 'DC current 10 uA to 10 mA', 'DCI': 'DC current 100 mA to 3 A',
               'DIGI': 'Digitize current', 'ACI': 'AC current', 'REAR10A': 'Rear panel 10 A', 'CAP': 'Capacitance'}


class SpecError(ValueError):
    pass


def load_spec(path=SPEC_PATH):
    """Read and check the spec (schema 1, model DMM6500): every point has a limit for the period, a kind the engine knows, and a group."""
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('model') != MODEL:
        raise SpecError('not a DMM6500 spec')
    if spec['default_period'] not in spec['periods']:
        raise SpecError('default_period is not one of periods')
    seen = set()
    for s in spec['sections']:
        for p in s['points']:
            where = f"{s['id']} {p.get('id', '?')}"
            if p['kind'] not in UNITS:
                raise SpecError(f'{where}: unknown kind {p["kind"]!r}')
            if p['id'] in seen:
                raise SpecError(f'{where}: duplicate id')
            seen.add(p['id'])
            if set(p['limits']) != set(spec['periods']) or any(not v > 0 for v in p['limits'].values()):
                raise SpecError(f'{where}: limits must be positive for every period')
            if p['kind'] in ('ACV', 'ACI', 'FREQ') and not p.get('frequency'):
                raise SpecError(f'{where}: this point needs a frequency')
            if p.get('source', s.get('source')) not in ('calibrator', 'none', 'manual', 'generator'):
                raise SpecError(f'{where}: unknown source')
            if p['group'] not in GROUP_TITLE:
                raise SpecError(f'{where}: unknown group {p["group"]!r}')
    return spec


def flatten(spec):
    """One flat, numbered list of points (ids start at 1) in the spec's run order."""
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = dict(raw)
            p.update(ref=raw['id'], id=len(points) + 1, section=s['id'], section_title=s['title'], section_page=s['page'], setup=s['setup'], optional=bool(s.get('optional')))
            p['print_unit'] = raw.get('unit')
            p['unit'] = UNITS[p['kind']]
            p['source'] = {'generator': 'calibrator'}.get(p.get('source', s.get('source')), p.get('source', s.get('source')))
            p['terminal'] = p.get('terminal') or s.get('terminal') or 'FRONT'
            p['page'] = f"{raw['page']} ({s['title']})"
            if p['group'] in ('RTD4', 'RTD3'):                            # the point is a resistance; the reading and the limits are temperatures
                p['source_ohms'], p['nominal'] = p['nominal'], p['example_temperature']
            if p['kind'] == 'FREQ':
                p['range'] = 10.0                                         # the threshold range (V) the report prints
            # the manual's reference DMM points: 1 ohm and 10 ohm, 10 uA to 10 mA. 10 A DC is NOT included: a 3458A reads 1.2 A at most (a shunt would be needed), so those four
            # points are centred on the calibrator setting.
            p['ref_dmm'] = (p['kind'] == 'OHM4' and p.get('range') and p['range'] <= 10 and p['group'] == 'OHM4') or p['group'] == 'DCI_LOW'
            p['description'] = describe(p)
            points.append(p)
    return points


def describe(p):
    name = NAMES[p['kind']]
    if p['group'] in ('RTD4', 'RTD3'):
        return f"{p['desc']}"
    if p['group'] == 'TC':
        return p['desc']
    if p['source'] == 'none':
        return f"{p['desc']}"
    return f"{name}: {p['desc']}" + (f" @ {procspec._fmt(p['frequency'], 'Hz')}" if p.get('frequency') and p['kind'] != 'FREQ' and '@' not in p['desc'] and ' at ' not in p['desc'] else '')


def fit_requests(points):
    """What each point asks of a calibrator, for calibrator_fit: digitize is plain DC, a thermocouple point is a dc voltage (the table value), an RTD point a resistance. Capacitance is
    left out (calibrator_fit has no row for it here: App.is_manual handles it from the driver's CANNOT list)."""
    out = []
    for p in points:
        if p['source'] != 'calibrator' or p['kind'] == 'CAP':
            continue
        q = dict(p)
        if p['kind'] in ('DIGV', 'DIGI'): q['kind'] = REPORT_KIND[p['kind']]
        elif p['kind'] == 'TEMP' and p['group'] == 'TC': q.update(kind='DCV', nominal=p['source_value'])
        elif p['kind'] == 'TEMP': q.update(kind='OHM4', nominal=p['source_ohms'])
        q.pop('low', None); q.pop('high', None)
        out.append(q)
    return out


def amplifier_points(points):
    """Ids of the points (those the 5700A alone cannot source) that the 5725A amplifier rows of the 5700A's published specification cover (specmanager variant '5725a'): AC volts 75 V to 750 V
    from 30 kHz to 100 kHz, DC current 2.2 A to 11 A, AC current 1 A to 11 A from 40 Hz to 10 kHz. Empty when the sheet is not installed."""
    try:
        import specmanager as sm
        std = sm.for_model('5700A') if hasattr(sm, 'for_model') else None
        if std is None:
            row = next((s for s in sm.standards() if s['model'] == '5700A'), None)
            std = sm.StandardSpec(row['id']) if row else None
    except Exception:
        return set()
    if std is None:
        return set()
    out = set()
    for q in fit_requests(points):
        kind = {'OHM4': 'OHM'}.get(q['kind'], q['kind'])
        if std.lookup(kind, q['nominal'], q.get('frequency'), variant='5725a') is not None:
            out.add(q['id'])
    return out


def apply_period(points, period):
    """Set each point's 'error' (the allowed +/- error about the centre) and the absolute low / high about the nominal, from the chosen period."""
    for p in points:
        p['error'] = float(f"{p['limits'][period]:.9g}")
        p['low'], p['high'] = p['nominal'] - p['error'], p['nominal'] + p['error']


SPEC = load_spec()
POINTS = flatten(SPEC)
apply_period(POINTS, SPEC['default_period'])


def configure(model=MODEL):
    """The engine has one model; kept so the engine matches the shape of the other bench-DMM engines."""
    return MODEL


def effective(p, center=None):
    """The point judged and reported: limits +/- error about `center` (a reference reading, or the temperature of the actual RTD resistance) when there is one, else about
    the nominal. kind is the report's plain function name (digitize -> DC)."""
    c = p['nominal'] if center is None else float(center)
    q = dict(p, nominal=c, low=c - p['error'], high=c + p['error'], kind=REPORT_KIND.get(p['kind'], p['kind']))
    if q['kind'] == 'TEMP':
        q['range'] = None
    return q


def judge(p, reading, center=None) -> bool:
    """PASS when |reading - centre| <= the allowed error, in Decimal (the float reading is taken at its shortest exact text)."""
    c = p['nominal'] if center is None else center
    return abs(Decimal(repr(float(reading))) - Decimal(repr(float(c)))) <= Decimal(str(p['error']))


def find_diagram(cal, group):
    """Hook-up picture for a wiring group: diagrams/hook_dmm6500_<cal>_<GROUP>.png, then diagrams/hook_dmm6500_<GROUP>.png (owner-supplied; none is invented)."""
    for name in (f'hook_dmm6500_{cal}_{group}', f'hook_dmm6500_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def to_visa(text, interface='USB'):
    """USB / GPIB / LAN address to a VISA resource: GPIB '16' -> GPIB0::16::INSTR, LAN '192.168.1.20' -> TCPIP0::192.168.1.20::inst0::INSTR; a full VISA resource (what Find
    instruments lists for USB) passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the GPIB address (0 to 30) or a full VISA address (GPIB0::16::INSTR).')
        return f'GPIB0::{int(t)}::INSTR'
    if interface == 'LAN':
        if not t:
            raise ValueError('Enter the IP address or host name of the DMM6500.')
        return f'TCPIP0::{t}::inst0::INSTR'
    raise ValueError('For USB pick the resource from Find instruments (USB0::0x05E6::0x6500::<serial>::INSTR).')


def to_cal_visa(text, interface='RS-232'):
    """The calibrator's VISA address. RS-232: 'COM9' / '9' -> 'ASRL9::INSTR'. GPIB: '4' -> 'GPIB0::4::INSTR'. A full VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the calibrator GPIB address (0 to 30) or a full VISA address (GPIB0::4::INSTR).')
        return f'GPIB0::{int(t)}::INSTR'
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port such as COM9.')
    return f'ASRL{int(t)}::INSTR'


def to_ref_visa(text):
    """The reference meter's GPIB address ('22' -> GPIB0::22::INSTR) or a full VISA resource; blank = no reference meter."""
    t = text.strip()
    if not t:
        return ''
    if '::' in t or t.upper().startswith(('GPIB', 'USB', 'TCPIP')):
        return t
    if not t.isdigit() or not 0 <= int(t) <= 30:
        raise ValueError('Enter the reference meter GPIB address (0 to 30, 3458A default 22) or a full VISA address.')
    return f'GPIB0::{int(t)}::INSTR'


REF_FUNCTION = {'OHM4': 'OHMF', 'DCI': 'DCI'}


class IO(manual_override.ReadGuardMixin, reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Bench I/O: the DMM6500 under test, the calibrator and, optionally, a 3458A reference meter, all through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, interface='USB', ref_address='', transports=None, mods=None, virtual=False, cal_interface='RS-232'):
        """interface = the DMM6500's (USB / LAN / GPIB); cal_interface = the calibrator's (RS-232 by default, GPIB selectable); ref_address = the reference meter's GPIB address
        (blank: none). transports = (dmm, calibrator[, reference]) for the simulated bench."""
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        cal_name, cal_cls = CALIBRATORS[cal_model]
        ref_t = None
        if transports:
            dmm_t, cal_t, *rest = transports
            ref_t = rest[0] if rest else None
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address, interface), timeout=30)
            cal_kw = dict(baud=cal_baud) if cal_interface != 'GPIB' else {}      # a baud rate only matters on RS-232
            cal_t = drivers.open_visa(to_cal_visa(cal_address, cal_interface), timeout=20, **cal_kw)
            if to_ref_visa(ref_address): ref_t = drivers.open_visa(to_ref_visa(ref_address), timeout=30)
        self.dmm = drivers.KeithleyDMM6500(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        self.ref = drivers.Agilent3458A(ref_t, self.log, label='3458A') if ref_t is not None else None
        self.last_eval = {}
        self.is_manual = lambda p: False        # the App sets this: points measured with a standard the technician connects
        self.uses_amp = lambda p: False         # the App sets this: points made through the 5725A amplifier (5700A + 5725A)
        self._amp = None
        self._tc_offset = None
        self._short_settled = False
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
            self.dmm.check_errors('connecting')
            if self.ref is not None: self.ref.connect()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.dmm.idn

    def reset_roles(self):
        return [self.cal] + ([self.ref] if self.ref is not None else []), [self.dmm]

    def pm_drivers(self):
        return (self.dmm, self.cal) + ((self.ref,) if self.ref is not None else ())

    def standby(self):
        self.cal.standby_quiet()

    def close(self):
        try: self.standby()
        except Exception: pass
        try: self.dmm.cleanup()
        except Exception: pass
        for obj in (self.dmm, self.cal, getattr(self, 'ref', None)):
            try:
                if obj is not None: obj.close()
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

    # ---- one point ----------------------------------------------------------------------------------------------------------
    def check_terminals(self, p):
        """The TERMINALS button cannot be pressed remotely: read it (:ROUT:TERM?) and stop if it is not where the point needs it."""
        if self.virtual and hasattr(self.dmm.t, 'front'):
            self.dmm.t.front = p['terminal'] == 'FRONT'                  # a virtual run: the simulated switch follows the point (the operator prompt does it on a real bench)
        have = self.dmm.front_rear()
        if have != p['terminal']:
            raise drivers.InstrumentError(f'The TERMINALS switch is on {have}; this point needs {p["terminal"]}. Move it and rerun.')

    def settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        k = p['kind']
        if p.get('rel_zero'): return self.pm_param('dmm6500.settle.rel_zero', SETTLE['rel_zero'])
        if p['source'] == 'none':
            first = not self._short_settled
            self._short_settled = True
            return self.pm_param('dmm6500.settle.short_first', SETTLE['short_first']) if first else self.pm_param('dmm6500.settle.short', SETTLE['short'])
        if k in ('ACV', 'ACI'): return self.pm_param('dmm6500.settle.ac', SETTLE['ac'])
        if k in ('OHM2', 'OHM4'):
            return self.pm_param('dmm6500.settle.ohm_high', SETTLE['ohm_high']) if (p.get('range') or 0) >= 1e7 else self.pm_param('dmm6500.settle.ohm', SETTLE['ohm'])
        if k in ('DCI', 'DIGI'): return self.pm_param('dmm6500.settle.dci', SETTLE['dci'])
        if k == 'CAP': return self.pm_param('dmm6500.settle.cap', SETTLE['cap'])
        return self.pm_param('dmm6500.settle.default', SETTLE['default'])

    def meter_point(self, p):
        """The point as the driver wants it. DC volts keeps REL on for the 100 mV range after its zero step (CM p. 2-8 step 12); offset compensation follows the point."""
        extra = {}
        if p['kind'] == 'DCV' and p.get('range') == 0.1 and not p.get('rel_zero') and p['source'] == 'calibrator':
            extra['keep_rel'] = True
        if p['kind'] == 'OHM4' and 'ocomp' not in p:
            extra['ocomp'] = True
        if p['kind'] == 'CAP' and not p.get('rel_acquire'):
            extra['keep_rel'] = True                                   # the cable offset acquired at the cable-only point stays on for the other capacitance points (CM p. 2-39)
        return dict(p, plc=p.get('plc') or 1, **extra)

    def compensation(self, p):
        """Resistance outputs: external sense for the 4-wire points and the RTD points, none for 2-wire; set once and read back (the 5700A: EXTSENSE). The manual selects external
        sense (EX SNS) for the 3-wire RTD points too (p. 2-23 step 11) and for every 4-wire resistance range. The 5560A has no such command in the project manuals: the operator sets
        its own 4-wire / 2-wire mode (the hook-up prompt says so)."""
        if not hasattr(self.cal, 'set_compensation'):
            return
        four = p['kind'] == 'OHM4' or p['group'] in ('RTD4', 'RTD3')
        self.cal.set_compensation('WIRE4' if four else 'NONE')

    def measure_offset(self):
        """Thermocouple cable thermal offset (CM p. 2-19 steps 2-14): DC volts, 100 mV range, input impedance Auto, autozero on, 1 PLC, calibrator at 0 V in operate, settle
        5 minutes, record the offset to 1 uV. Returns volts."""
        zero = self.meter_point(dict(kind='DCV', range=0.1, nominal=0.0, source='calibrator', group='TC', description='TC cable offset'))
        self.dmm.configure_point(zero)
        self.dmm.check_errors('configuring the TC offset')
        self.cal.set_output_volts(0, None, dc=True)
        self.cal.check_error('TC offset')
        self.cal.operate_unverified()
        time.sleep(virtualbench.scaled(self.pm_param('dmm6500.settle.tc_offset', SETTLE['tc_offset']), self.virtual))
        offset = round(self.dmm.read(), 6)
        self.standby()
        self.dmm.check_errors('reading the TC offset')
        return offset

    def source(self, p):
        """Program the calibrator for the point (an output is only enabled afterwards, after the error queue is read)."""
        k, v, f = p['kind'], p['nominal'], p.get('frequency')
        if k in ('DCV', 'DIGV'): self.cal.set_output_volts(v, None, dc=True)
        elif k == 'ACV': self.cal.set_output_volts(v, f, dc=False)
        elif k in ('DCI', 'DIGI'): self.cal.set_output_amps(v, None, dc=True)
        elif k == 'ACI': self.cal.set_output_amps(v, f, dc=False)
        elif k in ('OHM2', 'OHM4'):
            self.cal.set_output_ohms(v)
            self.compensation(p)
        elif k == 'FREQ': self.cal.set_output_volts(p['amplitude'], f, dc=False)
        elif k == 'CAP': self.cal.set_output_capacitance(v)
        elif k == 'TEMP' and p['group'] == 'TC': self.cal.set_output_volts(p['source_value'] - (self._tc_offset or 0.0), None, dc=True)
        elif k == 'TEMP':
            self.cal.set_output_ohms(p['source_ohms'])
            self.compensation(p)

    def reference_reading(self, p):
        """The 3458A reading of the source for a point the manual measures with a reference DMM (None without a reference meter or for other points)."""
        if self.ref is None or not p.get('ref_dmm'):
            return None
        fn = REF_FUNCTION[p['kind']]
        self.ref.configure(fn, abs(p['nominal']) or abs(p['range']), nplc=10)
        return self.ref.read()

    def read_point(self, p):
        if p['kind'] in ('DIGV', 'DIGI'):
            return manual_override.guard_read(lambda: self.dmm.read_digitize()['average'])
        return self._read()

    def virtual_hooks(self, p):
        """A virtual run has no operator to fit a short: the simulated meter is told (a real bench is not touched)."""
        t = self.dmm.t
        if hasattr(t, 'shorted'): t.shorted = p['source'] == 'none'
        if hasattr(t, 'external_value'): t.external_value = p['nominal'] if self.is_manual(p) else None      # a standard the operator connects

    @procmods_engine.point_commands()
    def measure(self, p):
        self.last_eval = {}
        self.standby()
        try:
            self.check_terminals(p)
            if self.virtual: self.virtual_hooks(p)
            manual = self.is_manual(p)
            if p['group'] == 'TC' and not manual:
                if p['ref'] == 'TC.1' or self._tc_offset is None: self._tc_offset = self.measure_offset()
            if p['group'] != 'SHORT4': self._short_settled = False
            self.dmm.configure_point(self.meter_point(p))
            self.dmm.check_errors('configuring ' + p['description'])
            amp = p['source'] == 'calibrator' and not manual and self.uses_amp(p)
            if hasattr(self.cal, 'amplifier_on') and not amp and self._amp is not None:
                self.cal.amplifier_off(); self._amp = None                # a point the 5700A makes by itself: the amplifier is taken out
            if p['source'] == 'calibrator' and not manual:
                if amp and self._amp != ('V' if p['kind'] in ('DCV', 'ACV', 'DIGV') else 'I'):
                    if self._amp is not None: self.cal.amplifier_off()
                    self._amp = 'V' if p['kind'] in ('DCV', 'ACV', 'DIGV') else 'I'
                    self.cal.amplifier_on(self._amp)                       # the output is still in standby here
                if p.get('rel_zero'): self.cal.set_output_volts(0, None, dc=True)
                else: self.source(p)
                self.cal.check_error(p['description'])        # the calibrator refuses outputs it cannot make; never operate then
                if self._amp is not None and hasattr(self.cal, 'amplifier_confirm'): self.cal.amplifier_confirm()      # BOOST / range lock read back with the amplifier output set, still in standby
                self.cal.operate_unverified()
                if hasattr(self.cal, 'wait_settled'): self.cal.wait_settled(self.pm_param('dmm6500.settle.cal_report', 60.0))
            time.sleep(virtualbench.scaled(self.settle(p), self.virtual))
            if p.get('rel_zero'): self.dmm.acquire_reference('DCV')
            ref = self.reference_reading(p)
            reading = self.read_point(p)
            if p.get('rel_acquire'): self.dmm.acquire_reference('CAP')      # the cable capacitance becomes the relative offset for the other capacitance points
            self.dmm.check_errors('reading ' + p['description'])
            if p['group'] in ('RTD4', 'RTD3'):
                self.last_eval = dict(center=rtd_cvd.temperature(ref if ref is not None else p['source_ohms']), reference=ref if ref is not None else p['source_ohms'])
            elif ref is not None and p.get('std_relative'):
                self.last_eval = dict(center=ref, reference=ref)
            return reading
        finally:
            self.standby()
            if self._amp is not None and hasattr(self.cal, 'amplifier_off'):
                try: self.cal.amplifier_off()
                finally: self._amp = None                              # the amplifier is taken out at the end of every point that used it (the output is in standby)


class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin, manual_override.ManualOverrideMixin):
    MANUAL_OVERRIDE = True            # type a reading instead of the automatic one (manual_override.py)

    def __init__(self, root, demo=False, fast_demo=False):
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}
        self.pm_init('dmm6500', MODEL, demo=demo, lists=[POINTS])     # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings('DMM6500')
        s = self.settings
        self.asset = port.var(); self.serial = port.var()
        self.interface = port.var(s.get('interface', 'USB') if s.get('interface', 'USB') in INTERFACES else 'USB')
        self.dmm_addr = port.var(s.get('dmm_addr', ''))
        self.ref_addr = port.var(s.get('ref_addr', ''))
        self.zero_checks = port.var(s.get('zero_checks', ZERO_CHOICES[0]) if s.get('zero_checks', ZERO_CHOICES[0]) in ZERO_CHOICES else ZERO_CHOICES[0])
        self.cal_offer57 = calibrator_fit.make_offer('5700A', calibrator_fit.dmm_requests(fit_requests(POINTS)), per_point_manual=True, unverified=drivers.Fluke5700A.unverified_summary())
        self._fit_manual = {r.key: reason for r, reason in self.cal_offer57.manual}         # point id -> why the 5700A cannot make it (calibrator_fit)
        self._amp_points = amplifier_points([p for p in POINTS if p['id'] in self._fit_manual])     # of those, the ones the 5725A amplifier rows cover
        self._amp_points = amplifier_points([p for p in POINTS if p['id'] in self._fit_manual])     # of those, the ones the 5725A amplifier rows cover
        self._amp_points = amplifier_points([p for p in POINTS if p['id'] in self._fit_manual])     # of those, the ones the 5725A amplifier rows cover
        self.cal_model = port.var(s.get('cal_model', 'Fluke 5560A') if s.get('cal_model', 'Fluke 5560A') in self.cal_choices() else 'Fluke 5560A')
        self.cal_interface = port.var(s.get('cal_interface', CAL_INTERFACES[0]))
        if self.cal_interface.get() not in CAL_INTERFACES: self.cal_interface.set(CAL_INTERFACES[0])
        self.cal_addr = port.var(s.get('cal_addr', CAL_PORT_DEFAULT[self.cal_interface.get()]))
        self._cal_shown, self._cal_ports = self.cal_interface.get(), {}
        self.cal_baud = port.var(s.get('cal_baud', '9600'))
        self.period = port.var(s.get('period', PERIOD_LABEL[SPEC['default_period']]))
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo
                        else 'Step 1: enter the Instrument ID. Step 2: choose the interface and addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    @property
    def cal_key(self): return CALIBRATORS[self.cal_model.get()][0]

    def cal_choices(self):
        """The calibrator picker's values (the 5520A and 5522A are not offered for this procedure)."""
        return list(CALIBRATORS)

    @property
    def amp_selected(self):
        return self.cal_model.get() in AMPLIFIER_MODELS

    def uses_amp(self, p):
        """True when the point is made through the 5725A amplifier: the 5700A + 5725A is selected and the point is above what the 5700A makes alone and inside the 5725A rows."""
        return self.amp_selected and p['id'] in self._amp_points

    def is_manual(self, p):
        """True when the selected calibrator cannot make this point: the technician connects another standard (the meter is still read automatically)."""
        if p['source'] != 'calibrator':
            return False
        if p['kind'] == 'CAP' and 'CAP' in getattr(CALIBRATORS[self.cal_model.get()][1], 'CANNOT', ()):
            return True
        if self.uses_amp(p):
            return False
        if self.uses_amp(p):
            return False
        if self.uses_amp(p):
            return False
        return self.cal_key in FIT_MODELS.values() and p['id'] in self._fit_manual

    def manual_reason(self, p):
        if p['kind'] == 'CAP' and 'CAP' in getattr(CALIBRATORS[self.cal_model.get()][1], 'CANNOT', ()):
            return f'the {self.cal_key} has no capacitance output'
        return self._fit_manual.get(p['id'], '')

    def active(self, p):
        if p.get('skip'): return False                               # a point skipped by a procedure modification
        if p['optional'] and self.zero_checks.get() == 'Skip': return False
        return True

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self._sync_buttons()

    VIEW = 'dmm6500_view'                               # window code: dmm6500_view_qt.py
    @property
    def ui_view(self): return port.view(self.VIEW)

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    def _build_ui(self): self.ui_view.build_ui(self)

    def on_cal_interface(self):
        """Calibrator interface changed: remember the port / address typed for the one just left, show the one for the new interface."""
        new = self.cal_interface.get()
        self._cal_ports[self._cal_shown] = self.cal_addr.get()
        self._cal_shown = new
        self.cal_addr.set(self._cal_ports.get(new, CAL_PORT_DEFAULT[new]))

    def pm_driver_classes(self): return (drivers.KeithleyDMM6500, drivers.Agilent3458A, *[cls for _n, cls in CALIBRATORS.values()])

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan)."""
        import procmods_plan
        from drivers.simulated_dmm6500 import make_dmm6500_bench
        cal_model = self.cal_model.get() if self.cal_model.get() in CALIBRATORS else 'Fluke 5560A'

        def build(mods):
            _bench, ft, dt, rt = make_dmm6500_bench(CALIBRATORS[cal_model][0], reference=True)
            io = IO('sim', 'sim', cal_model, 9600, self.interface.get(), transports=(dt, ft, rt), mods=mods, virtual=True, cal_interface=self.cal_interface.get())
            io.is_manual = self.is_manual
            io.uses_amp = self.uses_amp
            return io
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
        return (p['id'], p['description'] + ('  [your standard]' if self.is_manual(p) else ''), *cells), tags

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
                rec['result'] = 'PASS' if judge(POINTS[int(key) - 1], rec['reading'], rec.get('center')) else 'FAIL'
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'])
        notes = ''.join(f'\n  - {x}' for x in (p.get('flags') or []) if x)
        printed = f'  |  Printed in the manual: {p["printed_limits"]}' if p.get('printed_limits') else ''
        ref = ('\nYour own standard is used for this point: ' + self.manual_reason(p)) if self.is_manual(p) else ''
        if p.get('ref_dmm'): ref = '\nLimits are about the reference DMM reading (3458A) when one is connected, else about the calibrator setting.'
        elif p.get('std_relative'): ref = '\nLimits are about the calibrator setting (the manual centres them on the actual source value).'
        self.detail.set(f'{p["description"]}\nManual page {p["page"]}{printed}{ref}{notes}\n'
                        f'Setup: {self.setup_text(p)}' + (('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''))

    # ------------------------------------------------------------------ wiring text
    def setup_text(self, p):
        g = p['group']
        five60 = self.cal_key == '5560A'
        by_hand = self.cal_key == '5560A'                         # no compensation command is sent: the operator sets the calibrator's own 4-wire / 2-wire mode (the 5700A: EXTSENSE is sent)
        out = {'5560A': 'OUTPUT V/ohm HI / LO', '5700A': 'OUTPUT HI / LO'}.get(self.cal_key, 'NORMAL HI / LO')
        base = 'Shielded cable, shield to the calibrator LO. '
        if g == 'DCV':
            return base + f'Calibrator {out} to the DMM6500 INPUT HI / LO; low-thermal connections for the 100 mV and 1 V ranges (Figure 1).'
        if g in ('ACV', 'ACV750'):
            extra = (' For 740 V at 50 kHz and 100 kHz the manual puts a Fluke 5725A amplifier behind the calibrator: ' + ('the program turns the 5700A BOOST on for those points; connect the 5700A to the 5725A with its amplifier cable and the 5725A output to the DMM6500 INPUT HI / LO (Figure 3).' if self.amp_selected
                     else 'select "Fluke 5700A + 5725A" or use your own standard.')) if g == 'ACV750' else ''
            return base + f'Low-capacitance cable (below 1000 pF; below 150 pF for 750 V). Calibrator {out} to the DMM6500 INPUT HI / LO (Figures 2, 3).' + extra
        if g == 'FREQ':
            return 'The manual uses a Keithley 3390 generator; here the calibrator sources an AC voltage at the test frequency: ' + f'{out} to the DMM6500 INPUT HI / LO (Figure 5).'
        if g == 'TC':
            return ('DC voltage source for the type J table values: ' + f'{out} to the DMM6500 INPUT HI / LO, low-thermal (Figure 6). The program first measures the cable offset '
                    '(100 mV DC range, 0 V, 5 minutes) and subtracts it from each source value.')
        if g in ('RTD4', 'RTD3'):
            comp = ('The program turns the 5700A external sense on (EXTSENSE ON).' if not by_hand
                    else f'Set the {self.cal_key}\'s own external-sense mode ({"4-wire" if g == "RTD4" else "3-wire / 2-wire as the manual shows"}); no compensation command is sent to a {self.cal_key}.')
            wires = ('4-wire: calibrator force HI / LO to INPUT HI / LO and SENSE HI / LO to the DMM6500 SENSE Ohms 4 WIRE HI / LO (Figure 7)' if g == 'RTD4' else
                     '3-wire: INPUT HI / LO and SENSE LO as in Figure 8 (SENSE HI not required; HI-LO lead resistance mismatch below 0.1 ohm, add 0.25 degC per 0.1 ohm)')
            return f'{wires}; calibrator external sense ON. {comp}'
        if g == 'SHORT4':
            return 'Model 8610 / 8620 4-wire short on the front panel in the orientation of Figure 17 (INPUT / SENSE HI and LO). No calibrator output.'
        if g == 'OHM4':
            comp = ('The program turns the 5700A external sense on (EXTSENSE ON).' if not by_hand else
                    f'Set the {self.cal_key}\'s own 4-wire (external sense) mode; no compensation command is sent to a {self.cal_key}.')
            return (f'4-wire, shielded Teflon cable: calibrator {out} (force) to INPUT HI / LO and the calibrator SENSE HI / LO to the DMM6500 SENSE Ohms 4 WIRE HI / LO (Figure 9); '
                    f'calibrator external sense ON. {comp} With a reference meter, it sits in the 4-wire loop for the 1 ohm and 10 ohm points.')
        if g == 'OHM2':
            return (f'2-wire: calibrator {out} to INPUT HI / LO only (Figure 10), no sense leads, calibrator external sense OFF; shielded Teflon cable. '
                    + ('The program turns the 5700A external sense off.' if not by_hand else f'Set the {self.cal_key} to its 2-wire mode.'))
        if g in ('DCI_LOW', 'DCI', 'DIGI', 'ACI'):
            amps = {'5560A': 'VI AUX output and OUTPUT LO', '5700A': 'OUTPUT HI and OUTPUT LO (current post NORMAL: UNVERIFIED for an original 5700A)'}.get(self.cal_key, 'AUX HI and AUX LO')
            ref = ' The reference DMM (3458A, current function) is in series with the DMM6500 (Figure 11).' if g == 'DCI_LOW' else ''
            return f'Calibrator {amps} to the DMM6500 AMPS 3A and INPUT LO jacks (Figures 12 to 14). Check the calibrator range, its fuse and the DMM6500 AMPS fuse (3 A, 250 V) first.' + ref
        if g == 'REAR10A':
            return ('TERMINALS switch to REAR. Heavy short cable from the amplifier output (the manual: a 5725A in BOOST with the range locked; ' + ('the program sets BOOST and the range lock for the 5700A + 5725A' if self.amp_selected else 'select "Fluke 5700A + 5725A" or use your own standard')
                    + ') to the 10A AMPS jack and INPUT LO (Figures 18 to 20); the cable must carry 10 A without significant drop. A 3458A cannot read 10 A, so those points are centred on the calibrator setting.')
        if g == 'CAP':
            return ('The calibrator sources the capacitance (NORMAL terminals): short shielded banana cable from its output to the DMM6500 INPUT HI / LO, as short as possible (cable capacitance up to about 300 pF). '
                    'The first point reads the cable alone with the calibrator in standby; the program then acquires it as the relative offset for the rest.')
        return p['setup']

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        found = []
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        usb = [r for r in found if r.upper().startswith('USB')]
        gpib = [r for r in found if r.upper().startswith('GPIB')]
        asrl = [r for r in found if r.upper().startswith('ASRL')]
        lan = [r for r in found if r.upper().startswith('TCPIP')]
        self.ui_view.set_choices(self, 'dmm', {'USB': usb, 'GPIB': gpib, 'LAN': lan}[self.interface.get()] or found)
        self.ui_view.set_choices(self, 'ref', gpib or found)
        self.ui_view.set_choices(self, 'cal', (gpib if self.cal_interface.get() == 'GPIB' else asrl) or found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _new_io(self):
        if self.virtual:          # demo: the real IO / driver code over a simulated meter, calibrator and reference meter
            from drivers.simulated_dmm6500 import make_dmm6500_bench
            self._vb = make_dmm6500_bench(self.cal_key, self.interface.get(), reference=True)
            io = IO('virtual', 'virtual', self.cal_model.get(), 9600, self.interface.get(), transports=(self._vb[2], self._vb[1], self._vb[3]), mods=self.pm_state, virtual=True,
                    cal_interface=self.cal_interface.get())
        else:
            io = IO(self.dmm_addr.get(), self.cal_addr.get(), self.cal_model.get(), int(self.cal_baud.get()), self.interface.get(), ref_address=self.ref_addr.get(), mods=self.pm_state,
                    cal_interface=self.cal_interface.get())
        io.is_manual = self.is_manual
        io.uses_amp = self.uses_amp
        return io

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
        ref = f'\nReference meter: {self.io.ref.idn}' if self.io.ref is not None else '\nNo reference meter: the limits are centred on the calibrator setting.'
        self.status.set('Connected: ' + self.io.ident + tag + '. Calibrator output is NOT enabled.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'Keithley {MODEL}: {self.io.ident}\n{self.cal_model.get()}: {self.io.cal.idn}{ref}{tag}\nCalibrator output is not enabled.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def connected_io(self) -> IO:
        """The connected instruments (hardware mode); a clear error instead of a crash when they are not connected."""
        if self.io is None:
            raise drivers.InstrumentError('The instruments are not connected. Press Test connections first.')
        return self.io

    def _set_conn(self, ok):
        pill = getattr(self, 'conn_pill', None)
        if pill is not None:
            pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else 'Not connected' if not self.demo else 'Demo - no hardware',
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for key, var in (('interface', self.interface), ('dmm_addr', self.dmm_addr), ('ref_addr', self.ref_addr), ('zero_checks', self.zero_checks), ('cal_model', self.cal_model),
                         ('cal_interface', self.cal_interface), ('cal_addr', self.cal_addr), ('cal_baud', self.cal_baud), ('period', self.period)):
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

    def _prompt_start(self):
        """Warm-up, environment and defaults (CM pp. 2-2, 2-6), asked once at the start of a run. Returns False if the technician cancels."""
        return port.operator_prompt('Before the verification', 'Warm-up and conditions',
            [('Warm-up', 'The DMM6500 must have been on for at least 30 minutes (Cal Manual p. 2-2); more if it was stored 5 C or more outside the calibration temperature. '
                         'Allow the calibrator and any reference meter their own warm-up time.'),
             ('Environment', 'Ambient 18 to 28 C, relative humidity 80 % or less, no direct airflow on the input terminals (p. 2-2).'),
             ('Command set', 'The meter must be on the SCPI command set (MENU > System > Settings > Command Set).'),
             ('Direct connections', 'Connect the calibrator straight to the meter: no scanner, multiplexer or other switching equipment (p. 2-6).')],
            facts=[('Limits', f'{self.period.get()}, 18 to 28 C'), ('Calibrator', self.cal_model.get()),
                   ('Reference meter', 'none: limits about the calibrator setting' if not self.ref_addr.get().strip() and not self.virtual else 'connected')],
            caution='The program resets the DMM6500 (*RST) before the first point, then sets function, range and speed for every point. The manual\'s System Reset is the front-panel '
                    'equivalent. Resetting can erase settings stored on the meter.',
            ok='Conditions met - start', parent=self.root)

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
        if not self.fast_demo and not self._prompt_start(): self.status.set('Run not started: warm-up and conditions were not confirmed.'); return
        self.mo_reset_run()
        self._hv_acked = False                                       # a new run asks the high-voltage question again
        self.stop = False; self.busy = True
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    @staticmethod
    def _is_hv(p, manual):
        """A calibrator volts point of HV_CONFIRM or more (a point made with the technician's own standard has its own prompt)."""
        return p['source'] == 'calibrator' and not manual and p['kind'] in ('DCV', 'ACV', 'DIGV') and abs(p['nominal']) >= HV_CONFIRM

    def _prompt_setup(self, p):
        """Confirm the physical hook-up when the wiring group changes (with the picture, if installed). False if the technician cancels."""
        group = p['group']
        image = find_diagram(self.cal_key, group)
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['description']), ('Manual page', p['page'])]
        if image is None:
            facts.append(('Diagram', f'not installed (expected diagrams/hook_dmm6500_{self.cal_key}_{group}.png)'))
        self.connected_io().standby()
        steps = [('Standby', 'The calibrator is put in STANDBY before you rewire.'), ('Wiring', self.setup_text(p))]
        if self.uses_amp(p):
            steps.append(('5725A amplifier', 'The 5725A is in the circuit for this group: connect it to the 5700A with its amplifier cable and power it on. The program sets BOOST (and the range lock) with the output in standby.'))
        if p['terminal'] == 'REAR':
            steps.append(('Terminals', 'Set the TERMINALS switch to REAR and allow about 60 seconds of thermal settling (adjustment notes, p. 3-4). The program reads the switch.'))
        elif p['terminal'] == 'FRONT':
            steps.append(('Terminals', 'The TERMINALS switch must be on FRONT. The program reads the switch and stops if it is not.'))
        if group == 'DCV':
            steps.append(('REL zero', 'With the calibrator at 0 V the program waits 5 minutes (thermal settling), enables relative offset on the 100 mV range and keeps it for that range (p. 2-8).'))
        if p['kind'] in ('ACV', 'ACI'):
            steps.append(('Speed', f'AC uses detector bandwidth {p.get("ac_bandwidth", 30)} Hz; the program waits {SETTLE["ac"]:g} s (default, tunable) after the output is on.'))
        if group == 'SHORT4':
            steps.append(('Settling', 'With the short fitted the program waits 5 minutes before the first zero reading and does not use relative offset (p. 2-42).'))
        return port.operator_prompt('Rewire / verify before enabling output', f'Connect for {GROUP_TITLE[group]}',
            steps, facts=facts, caution='Continue only after physically verifying the connections.', ok='Connections verified - continue', image=image, parent=self.root)

    def _prompt_manual(self, p):
        """The selected calibrator cannot make this point: the technician connects another standard and applies the stated value."""
        f = f' at {procspec._fmt(p["frequency"], "Hz")}' if p.get('frequency') and p['kind'] != 'FREQ' else ''
        value = (f'{procspec._fmt(p["amplitude"], "V")} rms at {procspec._fmt(p["nominal"], "Hz")}' if p['kind'] == 'FREQ' else f'{procspec._fmt(p["nominal"], p["unit"])}{f}')
        self.connected_io().standby()
        steps = [('Why', self.manual_reason(p)),
                 ('Standard', f'Disconnect the calibrator. Connect your own standard to the meter as for {GROUP_TITLE[p["group"]]} and apply {value} (the manual names a 5725A amplifier for 750 V '
                              'above the calibrator range, and a current amplifier for the 10 A range). Use a standard accurate enough for the limits.'),
                 ('Wiring', self.setup_text(p))]
        return port.operator_prompt('Your own standard is needed', f'Point {p["id"]}: {p["description"]}', steps,
                                    facts=[('Next point', f'{p["id"]} of {len(POINTS)}'), ('Manual page', p['page'])],
                                    caution='The meter is read automatically once you press Continue. Apply the value first and let it settle.',
                                    ok='Standard applied - measure', image=find_diagram(self.cal_key, p['group']), parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        manual = self.is_manual(p)
        key = f'MANUAL{p["id"]}' if manual else (p['source'], p['terminal'], p['group'], self.uses_amp(p))
        if not self.fast_demo and key != previous and not (self._prompt_manual(p) if manual else self._prompt_setup(p)):
            self.busy = False; self.status.set('Paused for wiring or setup'); return
        if not self.fast_demo and self._is_hv(p, manual) and not getattr(self, '_hv_acked', False):
            # asked once per run, at the first high-voltage point (the DAQ procedure's rule, owner 2026-11-02); the question names the highest voltage the run will output
            top = max(abs(q['nominal']) for q in points[i:] if self._is_hv(q, self.is_manual(q)))
            if not port.ask_yes_no('HIGH VOLTAGE', f'This run outputs up to {top:g} V from the calibrator. Verify CAT-rated leads, connections, clearance and personnel safety. Enable output?'):
                self.busy = False; return
            self._hv_acked = True
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["description"]}')
        self.mo_begin(p)                               # the point being measured: 'Enter reading manually' applies to it
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.fast_demo:
            reading = p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38   # deterministic, labelled synthetic
            self.mo_finish(p, reading, True, lambda: self._record(p, reading, True, {'manual': manual, 'amp': self.uses_amp(p)})); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
        else:
            def work():
                try:
                    reading = self.connected_io().measure(p)
                    port.post(self.root, lambda: self._done(points, i, p, reading, key))
                except Exception as exc:
                    try: self.connected_io().standby()
                    except Exception: pass
                    err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                    if isinstance(err, manual_override.ReadingUnavailable): port.post(self.root, lambda err=err: self._reading_failed(points, i, p, key, err))     # the automatic reading failed: a typed one may replace it
                    else: port.post(self.root, lambda err=err: self._error(err))
            threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, key):
        ev = dict(getattr(self.io, 'last_eval', None) or {}) if self.io is not None else {}
        ev['manual'] = self.is_manual(p)
        ev['amp'] = self.uses_amp(p)
        self.mo_finish(p, reading, bool(self.demo), lambda: self._record(p, reading, bool(self.demo), ev)); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _reading_failed(self, points, i, p, key, exc):
        """The meter could not be read (timeout, unreadable, overload). The calibrator is already in standby: a typed reading (manual_override) lets the run go on, else stop as before."""
        if not self.mo_recover(p, exc): self._error(exc); return
        port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.mo_reset_run()
        self.busy = False; self.status.set('Error - run stopped: ' + str(exc)); port.message('error', 'Measurement stopped', str(exc))

    def _record(self, p, reading, synthetic, extra=None):
        center = (extra or {}).get('center')
        result = 'PASS' if judge(p, reading, center) else 'FAIL'
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
        return p['section_title']

    def standard_for(self, p):
        """The standard that applied a point, for the uncertainty / TAR / TUR: the selected calibrator."""
        return self.cal_key

    def certificate_rows(self):
        """Recorded points as 'Calibration Data' rows (display units scaled; limits shown as absolute low/high)."""
        return self.certificate_rows_and_points()[0]

    def certificate_rows_and_points(self):
        """(rows, points): the report rows and, parallel to them, the effective point each came from (limits about the centre actually used)."""
        import report_pdf
        rows, pts = [], []
        for p in POINTS:
            if not self.active(p): continue
            row = self.found_left_row(p, lambda r: report_pdf.point_row(effective(p, r.get('center')), r['reading'], r['result'] == 'FAIL', section=self.report_section(p),
                                                                        standard=None if (r.get('manual') or r.get('amp')) else self.standard_for(p)))
            if row:
                if (self.results.get(str(p['id'])) or {}).get('manual') or (self.results.get(str(p['id'])) or {}).get('amp'): row['Uncertainty'] = ''      # own standard: none applies; amplifier: the budget has no 5725A rows yet
                rows.append(row); pts.append(effective(p, (self.results.get(str(p['id'])) or {}).get('center')))
        return rows, pts

    def export_pdf(self):
        rows, pts = self.certificate_rows_and_points()
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details('Keithley DMM6500 performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        manual_ids = [p['ref'] for p in POINTS if (self.results.get(str(p['id'])) or {}).get('manual')]
        amp_ids = [p['ref'] for p in POINTS if (self.results.get(str(p['id'])) or {}).get('amp')]
        try:
            if details.get('show_tar_tur'):
                import tartur_wiring
                rows = report_pdf.apply_tar_tur(rows, details.get('show_tar_tur'), [dict(TAR='', TUR='') if (p['ref'] in manual_ids or p['ref'] in amp_ids) else tartur_wiring.point_fields(p, self.standard_for(p)) for p in pts])
            ref_note = 'reference meter: 3458A' if (self.io is not None and self.io.ref is not None) else 'no reference meter: limits about the calibrator setting'
            header_extra = ([('Operator-supplied standard', 'Points measured with a standard connected by the technician: ' + ', '.join(manual_ids))] if manual_ids else []) + \
                           ([('5725A amplifier', 'Points made through the 5725A amplifier (uncertainty and TAR not computed here): ' + ', '.join(amp_ids))] if amp_ids else [])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', 'Keithley DMM6500'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Limits applied', self.period.get()), ('Source', 'Keithley DMM6500 Calibration and Adjustment Manual DMM6500-905-01 Rev. E, pp. 2-2 to 2-48; ' + ref_note), *header_extra],
                                             demo=demo, details=details, footer_note=report_pdf.uncertainty_note(rows, self.cal_key), snapshot_context=report_pdf.context_for(self))
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
