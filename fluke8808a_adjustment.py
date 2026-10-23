"""Fluke 8808A guided ADJUSTMENT (calibration), logic only: no window, no tkinter.  The window is Procedures/Fluke_8808A_Adjustment.py.

THIS CHANGES THE CALIBRATION OF THE INSTRUMENT.  The method is the manual's "RS-232 Calibration (Manual)" (Fluke 8808A Calibration Manual, Oct 2008, pp. 3-16 / 3-17, Table 3-9
on pp. 3-12 to 3-15): *TER, then for each function its name, an optional CALREF, the Enter key to confirm the value and the Enter key to start the point, with a Fluke
calibrator driven by this program and the operator confirming every hook-up and EVERY POINT.  The 124 steps come from specs/fluke_8808a_adjustment.json (written by
specs/build_8808a_adjustment.py from the page images).

What the program does, in order (nothing before step 4 changes the calibration):
  1. connect to the 8808A (RS-232) and the calibrator; reset both to their defaults ONCE per connection (the unit-under-test notice first; later records on the same connection
     run a read-only session check instead), the 8808A's own *RST is the "power-up reset" of the Users Manual;
  2. the operator confirms warm-up and conditions, that the As Found verification is done, the authority to adjust, and that the meter is ready for the calibration mode;
  3. *TER (once); the banner "Select a Function or input EXIT to QUIT!" must come back;
  4. for every function of the chosen scope, in Table 3-9's order: the operator confirms the function start (ALL its points must then be done, p. 3-16); the function name is sent and the
     meter's recommended value is read; for every point: the recommended value is compared with Table 3-9 (and with the pp. 3-17 / 3-18 list: the two differ at 7 points), the optional
     CALREF is sent (characterized value, or the Table 3-9 value when the operator chooses it) and read back, the Enter key confirms the value, the hook-up is confirmed, the calibrator is
     programmed + read back + operated + settled, the operator confirms THIS POINT (a dialog that says what will be changed), the Enter key starts the point (sent ONCE, never repeated),
     the meter's completion is read, the calibrator goes to STANDBY;
  5. EXIT; then the As Left verification.
The 8808A has no save, lock, password or date command in the manual: there is nothing to type or store beyond the points themselves.  Writes are sent once, read back where the meter
shows something to compare, and never retried.  Only read-only queries retry.

ABORT: EXIT is sent; a function that was not completed shows CAL ERROR (p. 3-16).  The manual does not say what the meter does with the points already calibrated in that function,
so the abort text says so and tells the operator to repeat the function completely and run the verification.  Nothing about the stored constants is claimed.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import adjustment_audit
import drivers
import reset_startup
from drivers import fluke_8808a_cal as cal_driver
from drivers.base import InstrumentError, SafetyError

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / 'specs' / 'fluke_8808a_adjustment.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
STEPS = SPEC['steps']
FUNCTIONS = SPEC['functions']
STEP_BY_ID = {s['id']: s for s in STEPS}
FUNCTION_BY_ID = {f['id']: f for f in FUNCTIONS}
MODEL = 'Fluke 8808A'
INSTRUMENT = 'Fluke 8808A'
ALL_FUNCTIONS = tuple(f['id'] for f in FUNCTIONS)

SCOPES = {'Complete: all six functions, 124 steps (recommended)': ALL_FUNCTIONS,
          'Volts DC only (21 steps)': ('VDC',), 'Volts AC only (21 steps)': ('VAC',), 'Frequency only (12 steps)': ('FREQ',), 'Resistance only (28 steps)': ('OHMS',),
          'Current AC only (17 steps)': ('AAC',), 'Current DC only (25 steps)': ('ADC',)}
CALIBRATORS = {'Fluke 5522A': ('5522A', drivers.Fluke5522AComp), 'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5520A': ('5520A', drivers.Fluke5520A)}
BY_HAND_COMP = ('5560A', '5520A')              # no compensation command is sent to these: the operator sets the calibrator's own 4-wire / 2-wire mode
ZCOMP_LIMIT = 110e3                            # ohm: 5522A impedance compensation exists only below this (5522A Operators Manual p. 6-49)
HV_CONFIRM = 100.0                             # volts: a high-voltage confirmation once per hook-up group for the steps that output this much or more
HI_CURRENT = 2.0                               # amps: a high-current confirmation once per hook-up group (the 10 A terminal and its fuse)
SOURCE_3458A = '3458A characterised'            # audit 'source' of a value entered for the four characterized DC current ranges (text only: no 3458A driver or specification)
SOURCE_WAIVED = 'calibrator nominal (characterisation waived)'
CHAR_TOL = 0.01                                # a characterized value must be within 1 % of the meter's recommended value (this program's guard, UNVERIFIED: the manual states none)
MATCH_REL = 1e-3                               # the meter's recommended value matches a printed value when within 0.1 %
OUT_REL_TOL = 1e-6                             # the calibrator's OUT? must equal the value programmed
CONFIRM_FUNCTION = 'the function start'
TIMES = SPEC['times']
SETTLE_S = {k: float(v) for k, v in TIMES['settle_s'].items()}       # ENGINEERING VALUES, UNVERIFIED (the manual says only "a stable input", p. 3-11)
INTERFACE = 'RS-232'
PARITY_FORMATS = {'8 data bits, no parity': (8, 'none'), '7 data bits, even parity': (7, 'even'), '7 data bits, odd parity': (7, 'odd')}
BAUDS = ['9600', '19200', '4800', '2400', '1200', '600', '300']
CAL_INTERFACES = ('RS-232', 'GPIB')
CAL_PORT_DEFAULT = {'RS-232': 'COM9', 'GPIB': 'GPIB0::4::INSTR'}
GROUP_TITLE = {'ZERO_SHORT': 'the 4-wire short (DC volts and ohms zero)', 'VOLT': 'voltage / frequency inputs', 'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms', 'ZERO_OPEN': 'open current inputs (zero)',
               'IMA': 'current, mA terminal', 'I2A': 'current, 10 A terminal (2 A ranges)', 'I10A': 'current, 10 A terminal (10 A ranges)'}


class AdjustmentError(RuntimeError):
    """The procedure refuses the action (order, missing confirmation, wrong state)."""


class NeedsDisplayConfirmation(AdjustmentError):
    """CALREF was sent but the meter did not answer '=>' or '!>': the operator must confirm the value on the meter display."""


# ---------------------------------------------------------------------------------------------------------------------- helpers
_PREFIX = ((1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'), (1e-6, 'µ'))


def si_text(value, unit):
    """Display-only SI scaling of a base-unit number: 0.01 V -> '10 mV', 1e6 ohm -> '1 MΩ'. The numbers the instruments are sent are never scaled."""
    v = float(value)
    sym = {'ohm': 'Ω'}.get(unit, unit)
    if v == 0:
        return f'0 {sym}'
    for scale, prefix in _PREFIX:
        if abs(v) >= scale * 0.9999999:
            return f'{v / scale:.6g} {prefix}{sym}'
    return f'{v / 1e-6:.6g} µ{sym}'


def steps_in_scope(scope=ALL_FUNCTIONS):
    """The steps of the chosen functions in Table 3-9's order."""
    return [s for s in STEPS if s['function'] in scope]


def function_steps(function):
    return [STEP_BY_ID[i] for i in FUNCTION_BY_ID[function]['steps']]


def point_value(step) -> float:
    return float(Decimal(step['point']['value']))


def point_text(step):
    """The point as the manual prints it with a clean SI unit (display only): '-199.9 mV', '1.9 V at 500 Hz' ..."""
    if step['zero']:
        return {'VDC': '0 V (4-wire short)', 'VAC': '0 V (calibrator STANDBY)', 'AAC': '0 A (inputs open)', 'ADC': '0 A (inputs open)', 'OHMS': '0 Ω (4-wire short)'}[step['function']]
    p = step['point']
    return si_text(p['value'], p['unit'])


def source_text(step):
    """What the calibrator must output at a step: '10 V DC', '100 mV AC at 1 kHz', '1.9 V AC at 500 Hz' ... (display only)."""
    src = step['source']
    if not src:
        return 'no calibrator output (STANDBY)'
    value = si_text(src['value'], src['unit'])
    kind = src['kind']
    if kind in ('ACV', 'ACI'):
        return f'{value} AC at {si_text(src["frequency"], "Hz")}'
    return value + (' DC' if kind in ('DCV', 'DCI') else '')


def dialog_text(step, n=None, total=None):
    """The dialog the meter will go through for a step (display only): 'VDC, point 3 of 21'."""
    n = n or step['n']
    return f'{step["function"]}  Table 3-9 step {step["n"]}'


def settle_for(step):
    src = step['source']
    if not src:
        return 0.0
    if step['function'] == 'FREQ':
        return SETTLE_S['FREQ']
    if src['kind'] == 'OHM':
        return SETTLE_S['OHM_HIGH'] if float(src['value']) >= 1e6 else SETTLE_S['OHM']
    return SETTLE_S[src['kind']]


def is_hv(step, value=None):
    src = step['source']
    v = abs(float(value if value is not None else src['value'])) if src else 0.0
    return bool(src) and src['kind'] in ('DCV', 'ACV') and step['function'] != 'FREQ' and v >= HV_CONFIRM


def is_high_current(step, value=None):
    src = step['source']
    v = abs(float(value if value is not None else src['value'])) if src else 0.0
    return bool(src) and src['kind'] in ('DCI', 'ACI') and v >= HI_CURRENT


def match(a, b, rel=MATCH_REL):
    """a equals b within `rel` (a pair of zeros matches)."""
    a, b = float(a), float(b)
    return abs(a - b) <= rel * max(abs(a), abs(b)) + 1e-12


def requests(function_ids=ALL_FUNCTIONS):
    """The outputs the adjustment asks of its calibrator, as calibrator_fit requests (the question every calibrator picker asks).  A frequency step is an AC volts output (1.9 V at f)."""
    import calibrator_fit
    out = []
    for st in steps_in_scope(function_ids):
        src = st['source']
        if src:
            out.append(calibrator_fit.Req(src['kind'], float(src['value']), float(src['frequency']) if src.get('frequency') else None, label=f'{st["id"]}: {st["title"]}', key=st['id']))
    return out


def own_standard_ids(cal_key):
    """The ids of the steps the calibrator `cal_key` cannot source (no row in its published specification: calibrator_fit): the operator connects another standard there."""
    import calibrator_fit
    fit = calibrator_fit.assess(cal_key, requests())
    return {r.key for r, _v in fit.excluded}


def own_standard_reasons(cal_key):
    import calibrator_fit
    fit = calibrator_fit.assess(cal_key, requests())
    return {r.key: v.reason for r, v in fit.excluded}


def hookup_text(step, cal_key):
    text = _hookup_text(step, cal_key)
    if step.get('characterize'):
        text += (' CHARACTERIZED RANGE: the manual says the calibrator must be characterized here; measure its output with the Keysight / Agilent 3458A (the manual names an 8508A) and have the '
                 'value ready: the program asks for it before this point.')
    return text


def _hookup_text(step, cal_key):
    """The physical set-up for a step (Figures 3-1 to 3-5 and the notes of pp. 3-11, 3-16, 3-17).  Calibrator terminal names follow the verification procedure's wording (UNVERIFIED)."""
    five60 = cal_key == '5560A'
    out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
    g = step['group']
    if g == 'ZERO_SHORT':
        return ('Disconnect the calibrator leads. Fit the low thermal 4-wire short (Fluke PN 2653346) across the meter INPUT HI / LO and SENSE HI / LO (Table 3-1; "Volts DC: zero points using '
                'the 4-wire short", p. 3-12). The calibrator stays in STANDBY and no calibrator output is used. ' + ('This is also the ZERO OHM point (lab policy: the 4-wire short, not the calibrator\'s 0 ohm; '
                'the meter shows 4WIRE, p. 3-14). ' if step['function'] == 'OHMS' else '') + 'Keep drafts away from the low-thermal connections.')
    if g == 'ZERO_OPEN':
        return ('Remove ALL test leads from the meter\'s current inputs (mA and 10 A); nothing connected ("Open, no connection", p. 3-14 / 3-15; "if ZERO point is calibrated all test leads shall '
                'be removed", p. 3-16). The calibrator stays in STANDBY. If the meter says "Disconnect Test Leads!" it means exactly this.')
    if g == 'VOLT':
        if step['function'] == 'FREQ':
            return f'Calibrator {out} to the meter INPUT HI / LO (Figure 3-1). Calibrator AC volts at 1.9 V ("Set the calibrator to 1.9 volts for frequency calibration input", p. 3-16).'
        if step['zero']:
            return (f'AC volts zero: "Adjust with 5700A in standby or disconnected" (p. 3-12). Leave the calibrator {out} leads on the meter INPUT HI / LO if you like, but the calibrator must be in STANDBY.')
        return f'Calibrator {out} to the meter INPUT HI / LO (Figure 3-1). AC volts at 1 kHz; DC volts with the calibrator external sense OFF.'
    if g in ('OHM4', 'OHM2'):
        by_hand = cal_key in BY_HAND_COMP
        comp = ('The program sets the 5522A impedance compensation (ZCOMP) to ' + ('WIRE4' if g == 'OHM4' else 'WIRE2 below 110 kohm and NONE from 110 kohm up') + ' and reads it back.' if not by_hand else
                f'Set the {cal_key}\'s own ' + ('4-wire (external sense)' if g == 'OHM4' else '2-wire') + f' mode yourself: the program sends no compensation command to a {cal_key}.')
        if g == 'OHM4':
            return ('4-wire (Figure 3-2): calibrator output to the meter INPUT HI / LO and the calibrator SENSE HI / LO to the meter SENSE 4W HI / LO. The meter shows 4WIRE; the recommended value '
                    'is followed by W4 (p. 3-17). ' + comp)
        return ('2-wire (Figure 3-3): calibrator output to the meter INPUT HI / LO; connect the calibrator sense leads to the unit first. The meter does NOT show 4WIRE. ' + comp)
    if g == 'IMA':
        amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX HI and AUX LO'
        return (f'Calibrator {amps} to the meter mA input terminal and COM (Figure 3-4). Low ranges use the mA terminal (ADC ranges 1 to 4, AAC ranges 1 and 2; p. 3-16). '
                'The meter says "Connect to mA socket!". Check the calibrator range and the meter\'s mA fuse first.')
    if g in ('I2A', 'I10A'):
        amps = '30A and OUTPUT LO' if five60 else '20 A and AUX LO'
        return (f'Calibrator {amps} (high current) to the meter 10 A input terminal and COM (Figure 3-5). High ranges use the 10 A terminal (ADC ranges 5 and 6, AAC ranges 3 and 4; p. 3-16). '
                'The meter says "Connect to 10A socket". Check the leads, the calibrator range and the 10 A fuse first.')
    return step.get('note', '')


def serial_kwargs(baud, fmt='8 data bits, no parity'):
    """VISA serial settings of the 8808A: factory 9600 baud, 8 data bits, no parity, 1 stop bit, Echo off (Users Manual Table 4-1, p. 4-4); commands end LF, replies CR LF (p. 4-7)."""
    bits, parity = PARITY_FORMATS[fmt]
    return dict(baud=int(baud), data_bits=bits, parity=parity, stop_bits=1, write_termination='\n', read_termination='\r\n', flow_control='none')


def to_visa(text, interface='RS-232'):
    """RS-232: 'COM9' / '9' -> 'ASRL9::INSTR'. A full VISA resource passes through. GPIB (calibrator only): '4' -> 'GPIB0::4::INSTR'."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    if interface == 'GPIB':
        if not t.isdigit() or not 0 <= int(t) <= 30:
            raise ValueError('Enter the GPIB address (0 to 30) or a full VISA address (GPIB0::4::INSTR).')
        return f'GPIB0::{int(t)}::INSTR'
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (ASRL9::INSTR).')
    return f'ASRL{int(t)}::INSTR'


def _first_number(reply):
    import re
    m = re.search(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', str(reply))
    if not m:
        raise InstrumentError(f'no number in the reply {str(reply).strip()!r}')
    return float(m.group(0))


def validate_reference(step, text, meter_value):
    """(Decimal, None) or (None, reason): a characterized value typed by the operator: a number of at most six significant digits within CHAR_TOL of the meter's value."""
    try:
        value = Decimal(str(text).strip().replace(' ', ''))
    except Exception:
        return None, 'enter a number (0.19991)'
    if not value.is_finite():
        return None, 'enter a number'
    digits = value.normalize().as_tuple().digits
    if len(digits) > cal_driver.SIGNIFICANT:
        return None, f'the meter takes {cal_driver.SIGNIFICANT} digits (Calibration Manual pp. 3-11 / 3-16): round the value'
    if meter_value and abs(float(value) - meter_value) > CHAR_TOL * abs(meter_value):
        return None, f'the value is more than {CHAR_TOL:.0%} away from the meter\'s recommended {meter_value:g}: check the characterization'
    return value, None


# ---------------------------------------------------------------------------------------------------------------------- the bench
class AdjustIO(reset_startup.IOResetMixin):
    """The 8808A (calibration driver) and the calibrator, both through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5522A', cal_baud=9600, cal_interface='RS-232', serial=None, transports=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual:
            self.log.virtual = True
        cal_name, cal_cls = CALIBRATORS[cal_model]
        self.cal_key = cal_name
        self.reset_done = False
        if transports:
            dmm_t, cal_t = transports
        else:
            dmm_t = drivers.open_visa(to_visa(dmm_address), timeout=30, **(serial or {}))
            cal_kw = dict(baud=cal_baud) if cal_interface != 'GPIB' else {}
            cal_t = drivers.open_visa(to_visa(cal_address, cal_interface), timeout=20, **cal_kw)
        self.dmm = drivers.Fluke8808ACal(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        if self.virtual:
            self.dmm.QUIET_S, self.dmm.COMMAND_GAP_S, self.dmm.RESET_SETTLE_S = 0.02, 0.0, 0.0
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
        except Exception:
            self.close()
            raise
        self.ident = self.dmm.idn

    def reset_roles(self):
        return [self.cal], [self.dmm]

    def standby(self):
        """Calibrator output to STANDBY and confirmed (OPER? = 0). SafetyError when it cannot be confirmed."""
        self.cal.standby()

    def standby_quiet(self):
        self.cal.standby_quiet()

    def session_check(self):
        """A record that skips the reset (once per connection, like the verification): everything the reset did EXCEPT *RST: the calibrator to STANDBY and confirmed, both instruments
        still identify themselves (read-only), the meter's event status read ONCE (never retried).  Returns the summary text."""
        self.cal.standby()
        ident = self.cal.query_retry('*IDN?').strip()
        if self.cal.IDN_MATCH and not any(m.upper() in ident.upper() for m in self.cal.IDN_MATCH):
            raise InstrumentError(f'Unexpected calibrator identification: {ident}')
        flags = self.dmm.session_check()
        text = 'session check: calibrator in STANDBY, both instruments answer' + (('; meter status: ' + ', '.join(flags)) if flags else '')
        self.log.add('--', text, 'RESET')
        return text

    def close(self):
        try:
            self.cal.cleanup()                       # STBY, never raises
        except Exception:
            pass
        try:
            self.dmm.cleanup()                       # EXIT if the calibration mode is still open, then back to the front panel
        except Exception:
            pass
        for obj in (getattr(self, 'dmm', None), getattr(self, 'cal', None)):
            try:
                obj.close()
            except Exception:
                pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent to ~/.calibration_suite/command_log.txt; a virtual (demo) session writes nothing."""
        self.log.append_default(f'Fluke {MODEL} adjustment session')


# ---------------------------------------------------------------------------------------------------------------------- the session
@dataclass
class StepRecord:
    step_id: str
    attempts: int = 0
    done: bool = False
    failed: bool = False
    indeterminate: bool = False
    meter_value: float | None = None          # the recommended value the meter sent
    verdict: str = ''                         # 'table' | 'list' | 'other'
    output_value: float | None = None         # what the calibrator was set to
    calref: str = ''                          # the CALREF argument sent ('' = none)
    calref_status: str = ''                   # 'accepted' | 'unconfirmed' | 'confirmed on display'
    characterized: bool = False
    source: str = ''                          # where the value entered for a characterized range came from (audit 'source')
    waived: bool = False
    own_standard: bool = False
    cal_readback: float | None = None
    messages: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    at: str = ''


class Session:
    """The state of one adjustment run. Every action the window offers is one method here, so the same code is what the tests exercise on the simulated bench.

    audit: adjustment_audit.AuditStore;  clock: time.monotonic (replaceable in tests);  wait: how long to wait (replaceable: demo mode shortens it, tests do not sleep)."""

    def __init__(self, io: AdjustIO, audit: adjustment_audit.AuditStore, scope=ALL_FUNCTIONS, clock=time.monotonic, wait=time.sleep, scale=1.0, today=None):
        self.io, self.audit, self.scope = io, audit, tuple(f for f in ALL_FUNCTIONS if f in scope)
        self.clock, self.wait, self.scale = clock, wait, scale
        self.acks = set()
        self.records = {s['id']: StepRecord(s['id']) for s in STEPS}
        self.cal_mode = False
        self.entry_verified = False
        self.entry_failed = False             # the first function name was not answered with a recommended value
        self.ter_attempted = False            # the ONE operator-approved *TER entry attempt has been used (never more than one)
        self.must_stop = False
        self.active_function = None
        self.function_done = set()
        self.finished = False
        self.aborted = False
        self.exit_flags = []
        self.source_on = None
        self.own_ack = set()
        self.hv_group = None                  # the hook-up group for which the high-voltage / high-current question was answered
        self._hookup_group = None
        self.rec = None                       # the recommended value the meter is waiting with (cal_driver.Recommended)
        self.rec_messages = []
        self.pending_calref = None            # step id whose CALREF was sent but not confirmed by the meter
        self.output_value = None
        self.on_log = None                    # the window sets a callback(row, step_id) to show each audit line
        self.owned = None

    # ---- convenience
    @property
    def cal_key(self):
        return self.io.cal_key

    @property
    def dmm(self):
        return self.io.dmm

    def log(self, action, outcome='', detail='', step_id='', source=''):
        row = self.audit.log(action, outcome, detail, step_id, source)
        if row is not None and self.on_log is not None:
            try:
                self.on_log(row, step_id)
            except Exception:
                pass
        return row

    def plan(self):
        return steps_in_scope(self.scope)

    def next_step(self):
        for s in self.plan():
            if not self.records[s['id']].done:
                return s
        return None

    def all_done(self):
        return bool(self.plan()) and self.next_step() is None

    def own_standard(self, step):
        return bool(step['source']) and step['id'] in own_standard_ids(self.cal_key)

    # ---- confirmations the operator gives (each is recorded)
    def acknowledge(self, key, text=''):
        self.acks.add(key)
        self.log('CONFIRMED', 'OK', f'{key}: {text}' if text else key)

    # ---- 1. prepare (nothing here touches the calibration)
    def reset(self, confirm=None):
        """Reset the 8808A (the unit under test, notice asked first via `confirm`) and the calibrator to their defaults ONCE per connection; a later record on the same connection runs the
        read-only session check instead (the owner's reset-once-per-session rule for the 8808A).  Nothing here sends a calibration command.  Raises reset_startup.ResetDeclined / ResetFailed."""
        if self.io.reset_done:
            text = self.io.session_check()
            self.log('RESET', 'SKIPPED', 'already reset on this connection; ' + text)
            return None
        rep = self.io.reset_at_start(confirm=confirm)
        self.io.reset_done = True
        self.log('RESET', 'OK', 'Instruments reset to default settings: ' + ', '.join(rep.names))
        return rep

    def prepare(self):
        """Read-only: what the meter says about itself, and its event status (read once)."""
        self.dmm.check_errors('connecting')
        self.log('PREPARE', 'OK', f'*IDN? {self.io.ident}; event status clean')

    # ---- 2. the calibration mode
    def enter_calibration(self, use_ter=False):
        """The calibration mode is entered by the OPERATOR at the front panel with the calibration button (owner policy): nothing is sent to enter it. Needs the operator's confirmations
        (the 'panel' one says the button was pressed). The manual prints no query that shows the calibration mode, so it cannot be verified read-only: the first function name must be answered
        with a recommended value (start_function), and until then the mode is only 'entered by the operator'.  use_ter=True (off by default, UNVERIFIED) sends *TER once instead, the RS-232
        entry the manual shows on p. 3-16; the banner must then come back."""
        for need, why in (('conditions', 'warm-up and conditions'), ('as_found', 'the As Found performance verification'), ('authorised', 'authorisation to adjust'),
                          ('notice', 'the "this changes the instrument calibration" notice'), ('panel', 'that you entered the calibration mode at the front panel with the calibration button')):
            if need not in self.acks:
                raise AdjustmentError(f'Not confirmed yet: {why}.')
        if self.audit.run_id is None:
            raise AdjustmentError('Start an adjustment record first.')
        if self.cal_mode:
            raise AdjustmentError('The calibration mode is already open.')
        try:
            if use_ter:
                self.dmm.enter_cal_mode()
            else:
                reply = self.dmm.adopt_manual_entry()
        except Exception as exc:
            self.log('ENTER CAL', 'FAILED', str(exc).splitlines()[0])
            raise
        self.cal_mode = True
        self.entry_verified = False
        if use_ter:
            self.entry_verified = True
            self.ter_attempted = True
            self.log('ENTER CAL', 'OK', '*TER sent once (optional, UNVERIFIED path); the meter answered "Select a Function or input EXIT to QUIT!"')
        else:
            self.log('ENTER CAL', 'OPERATOR', 'entered at the front panel with the calibration button, confirmed by the operator; nothing was sent; ' + (
                'the banner arrived' if reply.idle else 'no banner arrived (the manual does not say whether one should); the mode cannot be verified read-only, the first function name will show it'))
        self.audit.set_status('CAL_MODE')

    def retry_entry_with_ter(self, confirmed=False):
        """The ONE retry the owner allows (UNVERIFIED): after the first function name was not answered with a recommended value, and only on the operator's explicit confirmation, send the manual's
        RS-232 entry command *TER ONCE and read what comes back (the banner). Never more than one attempt per session, never when the entry was already verified, never after a point was sent,
        and nothing else is re-sent: the function name is sent again only by the operator's next, separately confirmed 'start function'. Returns the reply."""
        if not self.cal_mode or self.finished or self.aborted:
            raise AdjustmentError('The calibration mode is not open.')
        if not self.entry_failed or self.entry_verified:
            raise AdjustmentError('A *TER attempt is only offered after the first function name failed.')
        if self.ter_attempted:
            raise AdjustmentError('The single *TER attempt was already used: stop.')
        if any(r.attempts for r in self.records.values()):
            raise AdjustmentError('A point was already sent: *TER is not used now.')
        if not confirmed:
            raise AdjustmentError('The *TER attempt has not been confirmed by the operator.')
        self.ter_attempted = True                   # counted before the write: even a failing attempt is the one attempt
        try:
            reply = self.dmm.enter_cal_mode(retry=True)
        except Exception as exc:
            self.must_stop = True
            self.log('ENTER CAL RETRY', 'FAILED', '*TER sent once (operator-approved, UNVERIFIED): ' + str(exc).splitlines()[0] + '. Stopping: nothing else is sent.')
            raise
        self.entry_failed = False
        self.log('ENTER CAL RETRY', 'OK', '*TER sent once (operator-approved, UNVERIFIED); the meter answered with the banner. The function name is sent again only on your next confirmation.')
        return reply

    # ---- 3. a function
    def start_function(self, confirmed=False):
        """Select the function of the next step. Needs the operator's confirmation: once a function is selected ALL its points must be calibrated (p. 3-16). Sends the function name once."""
        if not self.cal_mode or self.finished or self.aborted:
            raise AdjustmentError('The calibration mode is not open.')
        if self.must_stop:
            raise AdjustmentError('The meter did not enter the calibration mode even after the one *TER attempt: stop (Abort).')
        if self.active_function:
            raise AdjustmentError(f'{self.active_function} is already being calibrated.')
        nxt = self.next_step()
        if nxt is None:
            raise AdjustmentError('Every step of the chosen scope is done.')
        if not confirmed:
            raise AdjustmentError('The start of a function has not been confirmed by the operator (all of its points must then be calibrated).')
        fn = nxt['function']
        self.io.standby()
        self.source_on = None
        try:
            reply = self.dmm.select_function(fn)
        except Exception as exc:
            self.log('FUNCTION', 'FAILED', f'{fn}: {str(exc).splitlines()[0]}')
            if not self.entry_verified:
                self.entry_failed = True
                if self.ter_attempted:
                    self.must_stop = True          # the single *TER attempt was already used: nothing more is offered
            raise
        self.active_function = fn
        if not self.entry_verified:
            self.entry_verified = True
            self.log('ENTER CAL', 'VERIFIED', f'{fn} was answered with a recommended value: the meter is in the calibration mode')
        self.rec, self.rec_messages = reply.recommended, list(reply.messages)
        self.log('FUNCTION', 'STARTED', f'{fn} selected; {len(function_steps(fn))} points must all be calibrated; the meter recommends {self.rec.raw}')
        return reply

    # ---- 4. one point
    def check_order(self, step):
        nxt = self.next_step()
        if nxt is None or nxt['id'] != step['id']:
            raise AdjustmentError(f'The next step is {nxt["id"] + " " + nxt["title"] if nxt else "none"}; the manual\'s order is kept.')
        if self.active_function != step['function']:
            raise AdjustmentError(f'{step["function"]} has not been started.')

    def meter_value_for(self, step):
        """The value the meter's recommendation stands for, in the unit of the step's point (V, A, ohm; Hz for a frequency step)."""
        if self.rec is None:
            raise AdjustmentError('The meter has not sent a recommended value.')
        if step['function'] == 'FREQ':
            return float(self.rec.hz if self.rec.hz is not None else self.rec.value)
        return float(self.rec.value)

    def review(self, step):
        """Compare the meter's recommended value with Table 3-9 and with the p. 3-17 / 3-18 list: a dict with 'verdict' ('table' | 'list' | 'other'), the three values and a sentence."""
        self.check_order(step)
        meter = self.meter_value_for(step)
        table = point_value(step)
        lst = float(Decimal(step['list_value'])) if step.get('list_value') is not None else None
        if match(meter, table):
            verdict = 'table'
        elif lst is not None and match(meter, lst):
            verdict = 'list'
        else:
            verdict = 'other'
        text = {'table': 'The meter recommends the value of Table 3-9.',
                'list': f'The meter recommends the value of the "Calibration Points" list (p. 3-17 / 3-18), NOT the {si_text(table, step["point"]["unit"])} of Table 3-9: the two differ at this step.',
                'other': f'The meter recommends {self.rec.raw}, which is neither the Table 3-9 value ({si_text(table, step["point"]["unit"])}) nor the list value.'}[verdict]
        if step['function'] == 'FREQ':
            text = text.replace('Table 3-9.', 'Table 3-9.')
        rec = self.records[step['id']]
        rec.meter_value, rec.verdict = meter, verdict
        return dict(verdict=verdict, meter=meter, table=table, list=lst, text=text, conflict=bool(step['conflict']), raw=self.rec.raw, w4=self.rec.w4)

    def set_reference(self, step, *, choose='meter', characterized=None, waive=False, unexpected_ack=False):
        """Decide what the calibrator outputs and what the meter is told, then confirm the value with the first Enter.

          choose='meter'  : the calibrator is set to the meter's own recommended value (default). A value that is neither Table 3-9's nor the list's needs `unexpected_ack`.
          choose='table'  : only when the meter recommends the list value: the calibrator is set to Table 3-9's value and CALREF <that value> is sent (set, answer read, never retried).
          characterized   : text of a value measured by the operator's reference (the Keysight 3458A of this lab; the manual's note names an 8508A); CALREF <value> is sent, the calibrator stays at the meter's recommended value.
                            A step flagged `characterize` needs it, or `waive=True` (an explicit operator decision, logged): then no CALREF is sent.
        Returns the value the calibrator must output.  The first Enter (confirm value) is sent last, once."""
        self.check_order(step)
        rec = self.records[step['id']]
        info = self.review(step)
        if self.dmm.state != 'VALUE':
            raise AdjustmentError('The value of this step was already confirmed.')
        if info['verdict'] == 'other' and not unexpected_ack:
            raise AdjustmentError('The meter recommends a value that matches neither Table 3-9 nor the list: the operator must acknowledge it explicitly (or abort).')
        if choose not in ('meter', 'table') or (choose == 'table' and info['verdict'] != 'list'):
            raise AdjustmentError('"table" can only be chosen when the meter recommends the list value.')
        output = info['table'] if choose == 'table' else info['meter']
        calref_value = None
        if choose == 'table':
            calref_value = info['table']
        if step['characterize'] and characterized is None and not waive:
            raise AdjustmentError('This range needs the calibrator characterized (the manual: "need characterize 5520A with 8508A"; this lab characterizes with a Keysight 3458A): enter the value measured with the 3458A, or waive it explicitly.')
        if characterized is not None:
            if choose == 'table':
                raise AdjustmentError('A characterized value cannot be combined with the Table 3-9 choice.')
            value, why = validate_reference(step, characterized, info['meter'])
            if value is None:
                raise AdjustmentError(why)
            calref_value = float(value)
            rec.characterized = True
            rec.source = SOURCE_3458A
        if waive and step['characterize'] and characterized is None:
            rec.waived = True
            rec.source = SOURCE_WAIVED
            self.log('CHARACTERIZATION', 'WAIVED', f'operator waived the characterized value; the calibrator\'s nominal {si_text(output, step["point"]["unit"])} is used as it is', step['id'], source=rec.source)
        if calref_value is not None:
            text = cal_driver.reference_text(calref_value if characterized is None else Decimal(str(characterized).strip()), self.rec)
            try:
                status = self.dmm.set_reference(text)
            except Exception as exc:
                self.log('CALREF', 'FAILED', f'CALREF {text}: {str(exc).splitlines()[0]}', step['id'])
                raise
            rec.calref, rec.calref_status = text, status
            self.log('CALREF', 'SENT' if status == 'accepted' else 'UNCONFIRMED', f'CALREF {text} sent once; meter answer: {"=>" if status == "accepted" else "no prompt"}', step['id'], source=rec.source)
            if status != 'accepted':
                self.pending_calref = step['id']
                raise NeedsDisplayConfirmation('The meter did not answer CALREF with "=>" or "!>". Look at the meter display: if it shows the value the program sent, confirm it; otherwise abort.')
        rec.output_value = output
        self.output_value = output
        self._confirm_value(step)
        return output

    def confirm_calref_display(self, step, shows_value: bool):
        """The operator looked at the meter display after an unanswered CALREF. Yes: the first Enter is sent (once). No: nothing more is sent; the caller aborts."""
        if self.pending_calref != step['id']:
            raise AdjustmentError('No CALREF is waiting for a display confirmation.')
        rec = self.records[step['id']]
        if not shows_value:
            self.log('CALREF', 'NOT CONFIRMED', 'operator: the display does not show the value that was sent', step['id'])
            return False
        rec.calref_status = 'confirmed on display'
        self.pending_calref = None
        self.log('CALREF', 'CONFIRMED (operator)', f'display shows CALREF {rec.calref}', step['id'])
        self._confirm_value(step)
        return True

    def _confirm_value(self, step):
        rec = self.records[step['id']]
        reply = self.dmm.confirm_value()
        rec.messages = list(dict.fromkeys(self.rec_messages + list(reply.messages)))
        self.log('VALUE', 'CONFIRMED', f'first Enter sent: meter recommended {self.rec.raw}' + (f'; calibrator output {si_text(rec.output_value, step["point"]["unit"])}' if rec.output_value is not None else '')
                 + (f'; CALREF {rec.calref}' if rec.calref else '') + (f'; meter says {", ".join(rec.messages)}' if rec.messages else ''), step['id'], source=rec.source)
        return reply

    def mark_hookup(self, step):
        """The operator says the wiring for this step is done. Clears the high-voltage / current answer when the hook-up group changed."""
        if self._hookup_group != step['group']:
            self.hv_group = None
        self._hookup_group = step['group']
        self.log('HOOKUP', 'CONFIRMED', f'{step["title"]}: {GROUP_TITLE.get(step["group"], step["group"])}', step['id'])

    def message_warning(self, step):
        """A sentence when the meter's lead message does not fit the hook-up of the step ('Connect to 10A socket' for an mA-terminal step ...), else ''."""
        rec = self.records[step['id']]
        want = {'ZERO_OPEN': 'DISCONNECT', 'IMA': 'MA', 'I2A': '10A', 'I10A': '10A'}.get(step['group'])
        if step['function'] in ('ADC', 'AAC') and want and rec.messages and want not in rec.messages:
            return f'The meter says {", ".join(rec.messages)} but this step is wired for {GROUP_TITLE.get(step["group"], step["group"])}: check the terminal before going on.'
        return ''

    def acknowledge_hv(self, step):
        """The operator confirmed the high-voltage / high-current question for this hook-up group (asked once per group, not per point)."""
        self.hv_group = step['group']
        self.log('SAFETY', 'CONFIRMED', f'high voltage / current confirmed for the hook-up group {step["group"]}', step['id'])

    def acknowledge_own_standard(self, step, text=''):
        self.own_ack.add(step['id'])
        self.log('OWN STANDARD', 'CONFIRMED', text or f'operator connected their own standard for {source_text(step)}; the calibrator stays in STANDBY', step['id'])

    def program_source(self, step):
        """Standby, program the calibrator to the step's output value, read it back and compare, read its error queue, then OPERATE and let it settle.  A step with no calibrator output (shorts,
        open inputs, AC volts zero) and a step the calibrator cannot make (the operator's own standard) leave it in STANDBY.  Returns the calibrator's own read-back value or None."""
        io, cal = self.io, self.io.cal
        rec = self.records[step['id']]
        io.standby()
        self.source_on = None
        src = step['source']
        if not src:
            return None
        if step['id'] in own_standard_ids(self.cal_key):
            if step['id'] not in self.own_ack:
                raise AdjustmentError('The calibrator cannot make this output: the operator must connect their own standard and confirm it.')
            rec.own_standard = True
            return None
        value = rec.output_value if rec.output_value is not None else float(src['value'])
        if step['function'] == 'FREQ':
            volts, freq = float(src['value']), value                      # 1.9 V at the frequency the meter asked for
            value = volts
        else:
            freq = float(src['frequency']) if src.get('frequency') else None
        if (is_hv(step, value) or is_high_current(step, value)) and self.hv_group != step['group']:
            raise AdjustmentError('High voltage / current: the operator has not confirmed this hook-up group.')
        kind = src['kind']
        if kind == 'DCV':
            cal.set_output_volts(value, None, dc=True)
        elif kind == 'ACV':
            cal.set_output_volts(value, freq)
        elif kind == 'DCI':
            cal.set_output_amps(value, None, dc=True)
        elif kind == 'ACI':
            cal.set_output_amps(value, freq)
        elif kind == 'OHM':
            cal.set_output_ohms(value)
            if hasattr(cal, 'set_compensation'):
                if step['wire'] == 4:
                    cal.set_compensation('WIRE4')
                else:
                    cal.set_compensation('WIRE2' if value < ZCOMP_LIMIT else 'NONE')
        cal.check_error(step['title'])                     # the calibrator refuses outputs it cannot make; never operate then
        got = _first_number(cal.ask('out.query'))          # OUT? reply format UNVERIFIED on the 5560A / 5520A; the first number is the amplitude
        if abs(got - value) > OUT_REL_TOL * abs(value) + 1e-12:
            raise InstrumentError(f'{cal.label} read back {got:g}, not the {value:g} that was programmed: not switching the output on.')
        cal.operate()                                      # OPER, read back
        self.source_on = step['id']
        rec.cal_readback = got
        self.log('SOURCE', 'OK', f'{source_text(step)} programmed, read back {got:.9g}, OPERATE confirmed', step['id'])
        self.wait(settle_for(step) * self.scale)
        return got

    def send_point(self, step, confirmed=False, rerun_ack=False):
        """START the point (the second Enter: this changes the calibration). Needs: the operator's confirmation OF THIS POINT, the calibration mode and function, the manual's order, the
        value confirmed, the output on (or the own standard confirmed, or no output needed), and `rerun_ack` for a point that failed before. The calibrator goes to STANDBY afterwards,
        also on error.  Raises CalibrationError / StepIndeterminate (nothing is sent again).  Returns the StepRecord."""
        rec = self.records[step['id']]
        if not (self.cal_mode and self.active_function):
            raise AdjustmentError('The calibration mode / function is not open.')
        if self.finished or self.aborted:
            raise AdjustmentError('The adjustment is finished.')
        self.check_order(step)
        if not confirmed:
            raise AdjustmentError('This point has not been confirmed by the operator: nothing is sent.')
        if (rec.failed or rec.indeterminate) and not rerun_ack:
            raise AdjustmentError('This point failed before. It is only repeated on a fresh, explicit confirmation of the operator (the program never repeats a command by itself).')
        if self.dmm.state != 'CONFIRMED':
            raise AdjustmentError('The value of this point has not been confirmed with the first Enter.')
        if self.pending_calref == step['id']:
            raise AdjustmentError('The CALREF value has not been confirmed on the meter display.')
        if step['source'] is not None and self.source_on != step['id'] and not (step['id'] in own_standard_ids(self.cal_key) and step['id'] in self.own_ack):
            raise AdjustmentError('The calibrator has not been programmed and switched on for this step.')
        rec.attempts += 1
        rec.at = datetime.now().isoformat(timespec='seconds')
        self.log('POINT_SENT' if rec.attempts == 1 else 'POINT_RERUN', 'SENT', f'{step["function"]} step {step["n"]}: second Enter sent (starts calibrating; this changes the calibration)', step['id'], source=rec.source)
        try:
            reply = self.dmm.start_point()
        except cal_driver.StepIndeterminate as exc:
            rec.indeterminate, rec.failed = True, False
            self.log('POINT', 'INDETERMINATE', str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        except cal_driver.CalibrationError as exc:
            rec.failed, rec.indeterminate, rec.errors = True, False, list(exc.lines)
            self.log('POINT', 'FAILED', ' | '.join(exc.lines) or str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        except Exception as exc:
            rec.failed = True
            self.log('POINT', 'ERROR', str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        self._point_finished(step, rec, reply)
        self._standby_after()
        return rec

    def _point_finished(self, step, rec, reply):
        rec.done, rec.failed, rec.indeterminate, rec.errors = True, False, False, []
        self.log('POINT', 'OK', f'{step["function"]} step {step["n"]}: the meter finished the point' + (' (WAIT... seen)' if reply.wait else ' (no WAIT... line seen)'), step['id'], source=rec.source)
        self.rec, self.rec_messages = reply.recommended, list(reply.messages)
        self.pending_calref = None
        if reply.idle:
            self.function_done.add(step['function'])
            self.active_function = None
            self.log('FUNCTION', 'COMPLETE', f'{step["function"]}: the meter is idle again ("Select a Function or input EXIT to QUIT!")')

    def recheck_indeterminate(self, step):
        """After a point whose completion was not seen: read whatever the meter has sent since (read-only; nothing is written). True when the completion arrived."""
        rec = self.records[step['id']]
        if not rec.indeterminate:
            raise AdjustmentError('This point is not waiting for a decision.')
        reply = self.dmm.read_late(self.dmm.QUIET_S)
        if reply.error_prompt:
            rec.failed, rec.indeterminate, rec.errors = True, False, reply.lines
            self.log('POINT', 'FAILED', ' | '.join(reply.lines), step['id'])
            return False
        if reply.idle or reply.recommended is not None:
            self._point_finished(step, rec, reply)
            self.log('POINT', 'OK (late)', 'the completion arrived after the wait', step['id'])
            return True
        self.log('POINT', 'STILL NO ANSWER', 'nothing new from the meter; look at its display', step['id'])
        return False

    def _standby_after(self):
        try:
            self.io.standby()
            self.source_on = None
        except Exception as exc:
            self.log('STANDBY', 'COULD NOT CONFIRM', str(exc).splitlines()[0])
            raise SafetyError('The calibrator output could not be confirmed in STANDBY: check its front panel before touching any lead.') from None

    # ---- 5. finish and abort
    def finish(self):
        """EXIT after the last point of the chosen scope. Needs every step done."""
        if not self.all_done():
            raise AdjustmentError('Not every step of the chosen scope has been completed.')
        if self.finished:
            raise AdjustmentError('The calibration mode was already left.')
        self.io.standby()
        flags = self.dmm.exit_cal()
        self.exit_flags = flags
        self.cal_mode, self.finished = False, True
        self.log('EXIT', 'OK', 'EXIT sent; calibration mode left' + (f'; event status: {", ".join(flags)}' if flags else '; event status clean') + '. If the meter still shows the calibration mode, press the SHIFT key at the front panel (owner-stated, not from the manual pages read).')
        self.audit.set_status('COMPLETED_NOT_VERIFIED')
        return flags

    def abort(self, reason='operator'):
        """Stop. Calibrator to STANDBY, EXIT sent where the calibration mode is open, and an honest statement of what is and is not known. Never raises. Returns the text."""
        self.aborted = True
        notes = []
        try:
            self.io.standby()
        except Exception as exc:
            notes.append('The calibrator could not be confirmed in STANDBY (' + str(exc).splitlines()[0] + '): check it before touching any lead.')
        in_function = self.active_function
        sent = [r for r in self.records.values() if r.attempts]
        if self.cal_mode or self.dmm.in_cal:
            try:
                self.dmm.exit_cal()
                notes.append('EXIT was sent over RS-232 (the manual\'s way to leave the calibration mode, p. 3-16). Look at the meter: if it still shows the calibration mode, press the SHIFT key at the front panel to leave it '
                             '(owner-stated, not from the manual pages read).')
            except Exception as exc:
                notes.append('EXIT could not be confirmed (' + str(exc).splitlines()[0] + '): the meter may still be in the calibration mode; press the SHIFT key at the front panel to leave it '
                             '(owner-stated, not from the manual pages read).')
            self.cal_mode = False
        done_here = [r for r in sent if STEP_BY_ID[r.step_id]['function'] == in_function and r.done] if in_function else []
        if in_function:
            total = len(function_steps(in_function))
            what = (f'{in_function} was NOT completed ({len(done_here)} of {total} points were calibrated before the stop). The manual: a function that is not completely calibrated shows CAL ERROR (p. 3-16). '
                    'The manual does not say whether the points already calibrated were stored or discarded: repeat the whole function and run the performance verification before using the meter.')
        elif sent:
            what = ('Points were calibrated in complete functions (' + ', '.join(sorted(self.function_done)) + '); the function in progress, if any, is listed above. '
                    'Run the performance verification to see the state of the meter.') if self.function_done else 'A point was sent but no function was completed: run the performance verification.'
        else:
            what = 'No calibration point was started: the calibration is unchanged.'
        text = f'Adjustment stopped ({reason}). ' + what + (' ' + ' '.join(notes) if notes else '')
        self.log('ABORT', 'DONE', text)
        self.audit.set_status('ABORTED_INCOMPLETE_FUNCTION' if in_function and sent else ('ABORTED_AFTER_POINTS' if sent else 'ABORTED'))
        return text

    # ---- summary
    def summary_lines(self):
        out = []
        for s in self.plan():
            r = self.records[s['id']]
            out.append(f'{s["id"]}  {s["title"]}: ' + ('done' if r.done else 'FAILED' if r.failed else 'indeterminate' if r.indeterminate else 'pending'))
        return out
