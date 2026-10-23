"""Keithley Model 2000 guided ADJUSTMENT (calibration), logic only: no window, no tkinter.  The window is Procedures/Keithley_2000_Adjustment.py.

THIS CHANGES THE CALIBRATION CONSTANTS OF THE INSTRUMENT.  The method is the manual's SCPI command calibration (Calibration Manual 2000-905-01 Rev. F, pp. 2-14 to 2-19):
the remote :CAL:PROT commands, in the manual's order, with a Fluke calibrator driven by this program and the operator confirming every hook-up and every step.  The steps come
from specs/keithley_2000_adjustment.json (written by specs/build_k2000_adjustment_spec.py from the page images).

What the program does, in order (everything before step 4 leaves the calibration untouched):
  1. connect to the 2000 and the calibrator, check the INPUTS switch, reset both to their defaults (the unit-under-test notice first), select DCV / SLOW (10 PLC), p. 2-14;
  2. the operator confirms warm-up and conditions and that the As Found verification is done;
  3. the operator confirms, then types the calibration code (asked at run time, held only for the one call, NEVER stored, logged or written to the audit record);
  4. :CAL:PROT:CODE (once), :CAL:PROT:LOCK? must read unlocked, :CAL:PROT:INIT (once);
  5. each step in the manual's order: hook-up confirmation, calibrator programmed + read back + operate confirmed + settle, the operator confirms the step, the command is sent ONCE,
     *OPC? waits for it, the error queue is read, the calibrator goes to STANDBY;  a step whose command failed is not repeated automatically;
  6. dates (:DATE, :NDUE, each read back), then :SAVE only after the operator has typed the confirmation phrase, then :LOCK (read back).
Writes are set, read back where a query exists, compared, and never retried.  Only read-only queries retry.

ABORT: before :SAVE the stored constants are not changed (the manual: "only temporary unless the :SAVE command is sent", pp. 2-19 / 3-8); the manual does not say whether :LOCK
discards the temporary ones at once, so the abort text tells the operator to cycle the 2000's power.  After :SAVE nothing can be undone (the manual has no restore command).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import adjustment_audit
import drivers
import reset_startup
from drivers import keithley_2000_cal as cal_driver
from drivers.base import InstrumentError, SafetyError
from drivers.keithley_2000 import _number

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / 'specs' / 'keithley_2000_adjustment.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
STEPS = SPEC['steps']
MODEL = 'Keithley 2000'
INSTRUMENT = 'Keithley Model 2000'

SCOPES = {'Complete: DC, then AC (recommended)': ('DC', 'AC'), 'DC only (DC volts, ohms, DC current)': ('DC',), 'AC only (AC volts, AC current)': ('AC',)}
# The 5522A / 5520A driver has no 'ZCOMP' for the 5560A; the 5520A is not offered: its specification does not meet the manual's Table 2-1 anywhere (specs/k2000_adjustment_standards.md).
CALIBRATORS = {'Fluke 5560A': ('5560A', drivers.Fluke5560A), 'Fluke 5522A': ('5522A', drivers.Fluke5522AComp)}
HV_CONFIRM = 100.0                         # volts: a high-voltage confirmation for every step that outputs this much or more
ZCOMP_LIMIT = 110e3                        # ohm: 5522A impedance compensation exists only below this (5522A Operators Manual p. 6-49)
THERMAL_WAIT_S = float(SPEC['times']['thermal_wait_s'])     # p. 2-15: "Wait at least three minutes" (short; connecting the calibrator for DC volts)
CONFIRM_SAVE = 'SAVE 2000'                 # the phrase typed before :CAL:PROT:SAVE
# Settling of the calibrator output before a step is confirmed: ENGINEERING VALUES, UNVERIFIED (the manual says only "let the source signal settle", p. 2-4); the operator also
# confirms the calibrator has settled before the step is sent.  seconds
SETTLE_S = {'DCV': 8.0, 'ACV': 15.0, 'DCI': 8.0, 'ACI': 15.0, 'OHM': 8.0, 'OHM_HIGH': 15.0}
INTERFACES = ('GPIB', 'RS-232')
CAL_INTERFACES = ('RS-232', 'GPIB')                                      # the calibrator: RS-232 preselected as in the verification procedure
CAL_PORT_DEFAULT = {'RS-232': 'COM9', 'GPIB': 'GPIB0::4::INSTR'}        # editable; the GPIB address is only an example (UNVERIFIED)
FLOW = {'None': 'none', 'XON/XOFF': 'xon_xoff'}
# What the lab should know about each calibrator against the manual's Table 2-1 (specs/k2000_adjustment_standards.md, 24 steps with an output).
CAL_NOTES = {
    '5560A': 'Meets the manual\'s Table 2-1 (Fluke 5700A 90-day ppm) at 4 of the 24 sourced steps; the sheet holds the 1-year column, which is conservative.',
    '5522A': 'Meets the manual\'s Table 2-1 at none of the 24 sourced steps (the 5522A is a less accurate standard than the 5700A). The program allows it; the lab decides if its uncertainty is acceptable for an adjustment.',
}
OUT_REL_TOL = 1e-6                         # the calibrator's OUT? must equal the value programmed


class AdjustmentError(RuntimeError):
    """The procedure refuses the action (order, missing confirmation, wrong state)."""


# ---------------------------------------------------------------------------------------------------------------------- helpers
_PREFIX = ((1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'), (1e-6, '\u00b5'))


def si_text(value, unit):
    """Display-only SI scaling of a base-unit number: 0.01 V -> '10 mV', 1e6 ohm -> '1 M\u03a9'. The numbers the instruments are sent are never scaled."""
    v = float(value)
    sym = {'ohm': '\u03a9'}.get(unit, unit)
    if v == 0:
        return f'0 {sym}'
    for scale, prefix in _PREFIX:
        if abs(v) >= scale * 0.9999999:
            return f'{v / scale:.6g} {prefix}{sym}'
    return f'{v / 1e-6:.6g} \u00b5{sym}'


def steps_in_scope(scope=('DC', 'AC')):
    """The steps of the chosen scope in the manual's order (DC, then AC)."""
    return [s for s in STEPS if s['scope'] in scope]


def step_by_id(step_id):
    return next(s for s in STEPS if s['id'] == step_id)


def available_steps(fw_class, scope=('DC', 'AC')):
    """The steps this firmware has (A19 and earlier have no 10 Mohm step: Table 3-1 note, p. 3-4)."""
    return [s for s in steps_in_scope(scope) if (s['a20'] if fw_class == 'A20+' else s['a19']) is not None]


def command_text(step, fw_class, parameter=None, secret_free=True):
    """The command line as the manual prints it (for the dialogs, the audit record and the tests): ':CAL:PROT:DC:STEP3 10'."""
    n = cal_driver.step_number(step, fw_class)
    text = f':CAL:PROT:{step["scope"]}:STEP{n}'
    if parameter is not None:
        text += f' {float(parameter):.10g}'
    return text


def parameter_text(step, parameter):
    """The parameter as a short text with its unit: '1 kohm' ... (display only)."""
    p = step['param']
    return si_text(parameter, p['unit']) if p else ''


def validate_parameter(step, text):
    """(Decimal, None) or (None, reason): the typed parameter must be a number inside the manual's allowed range (Tables 2-8 to 2-10 / 3-2), in Decimal."""
    p = step['param']
    if p is None:
        return None, 'this step takes no parameter'
    try:
        value = Decimal(str(text).strip().replace(' ', ''))
    except Exception:
        return None, 'enter a number (1E3 or 1000)'
    if not value.is_finite():
        return None, 'enter a number'
    lo, hi = Decimal(p['lo']), Decimal(p['hi'])
    if not (lo <= value <= hi):
        return None, f'the manual allows {lo.normalize():f} to {hi.normalize():f} {p["unit"]} for this step'
    return value, None


def differs(step, value: Decimal, readback: float, rel=1e-4):
    """True when the parameter is not the calibrator's own read-back value (to 0.01 %): the operator must then confirm it came from a certificate / the standard's value."""
    return abs(float(value) - readback) > rel * abs(readback)


def default_due(today: date, years=1) -> date:
    try:
        return today.replace(year=today.year + years)
    except ValueError:                                    # 29 February
        return today.replace(year=today.year + years, day=28)


def parse_firmware_label(fw_class):
    return {'A20+': 'A20 and later', 'A19-': 'A19 and earlier'}.get(fw_class, 'not established')


def source_text(step):
    """What the calibrator must output at a step: '10 V DC', '100 mV AC at 1 kHz' ... (display only)."""
    src = step['source']
    if not src:
        return 'no calibrator output (STANDBY)'
    value = si_text(src['value'], src['unit'])
    kind = src['kind']
    if kind in ('ACV', 'ACI'):
        return f'{value} AC at {si_text(src["frequency"], "Hz")}'
    return value + (' DC' if kind in ('DCV', 'DCI') else '')


def settle_for(step):
    src = step['source']
    if not src:
        return 0.0
    if src['kind'] == 'OHM':
        return SETTLE_S['OHM_HIGH'] if float(src['value']) >= 1e6 else SETTLE_S['OHM']
    return SETTLE_S[src['kind']]


def is_hv(step):
    src = step['source']
    return bool(src) and src['kind'] in ('DCV', 'ACV') and abs(float(src['value'])) >= HV_CONFIRM


def hookup_text(step, cal_key):
    """The physical set-up for a step (Figures 2-1 to 2-4 and the text of pp. 2-8, 2-9, 2-15, 3-11).  Calibrator terminal names follow the verification procedure's wording (UNVERIFIED)."""
    five60 = cal_key == '5560A'
    out = 'OUTPUT V/ohm HI / LO' if five60 else 'NORMAL HI / LO'
    g = step['group']
    if g == 'SHORT':
        return ('Disconnect the calibrator leads. Connect the Keithley 8610 low-thermal shorting plug to the 2000 front INPUT HI / LO and SENSE (S+ / S-) jacks (Figure 2-1). '
                'INPUTS button NOT pressed in (front inputs). Keep drafts away from the low-thermal connections. Wait at least three minutes before the step (p. 2-15).')
    if g == 'OPEN':
        return 'Remove the shorting plug. Disconnect ALL cables and accessories from the front input jacks, the calibrator leads included (p. 3-11).'
    if g == 'DCV':
        return ('Shielded low-thermal cables: calibrator ' + out + ' to the 2000 INPUT HI / LO (Figure 2-2). Calibrator set to DC volts with EXTERNAL SENSE OFF (disconnect the sense '
                'leads if the calibrator cannot switch it) (p. 2-9). Wait three minutes for thermal equilibrium after connecting (p. 2-15).')
    if g == 'OHM4':
        comp = ('The program sets the 5522A impedance compensation (ZCOMP) to WIRE4 below 110 kohm and NONE from 110 kohm up and reads it back.' if not five60 else
                'Set the 5560A\'s own 4-wire (external sense) mode yourself: the program sends no compensation command to a 5560A.')
        return ('4-wire: calibrator ' + out + ' (force) to the 2000 INPUT HI / LO and the calibrator SENSE HI / LO to the 2000 SENSE Ohms 4 WIRE HI / LO (Figure 2-2). '
                'Calibrator external sense ON for ALL resistance steps (p. 2-10). ' + comp)
    if g in ('DCI', 'ACI'):
        amps = 'VI AUX output and OUTPUT LO' if five60 else 'AUX HI and AUX LO'
        return (f'Calibrator {amps} to the 2000 AMPS and INPUT LO jacks (Figure 2-3); calibrator set for normal current output. Check the calibrator range and fuse and the 2000 AMPS fuse first.')
    if g == 'ACV':
        return 'Shielded cable: calibrator ' + out + ' to the 2000 INPUT HI / LO (Figure 2-4). Calibrator AC volts at the stated frequency.'
    return step.get('note', '')


def find_diagram(cal_key, group):
    """diagrams/hook_k2000_ADJ_<cal>_<GROUP>.png, hook_k2000_ADJ_<GROUP>.png, then the verification pictures hook_k2000_<cal>_<GROUP>.png / hook_k2000_<GROUP>.png (see diagrams/README_k2000.txt)."""
    for name in (f'hook_k2000_ADJ_{cal_key}_{group}', f'hook_k2000_ADJ_{group}', f'hook_k2000_{cal_key}_{group}', f'hook_k2000_{group}'):
        path = HERE / 'diagrams' / f'{name}.png'
        if path.exists():
            return path
    return None


def serial_kwargs(baud, term='LF', flow='None'):
    """VISA serial settings of the 2000: 8 data bits, no parity, 1 stop bit (User Manual p. 4-6), CR to end what we send (p. 4-7), TX TERM as chosen on the meter (p. 4-7)."""
    return dict(baud=int(baud), data_bits=8, parity='none', stop_bits=1, write_termination='\r', read_termination=drivers.keithley_2000.TX_TERM[term], flow_control=FLOW[flow])


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


# ---------------------------------------------------------------------------------------------------------------------- the bench
class AdjustIO(reset_startup.IOResetMixin):
    """The 2000 (calibration driver) and the calibrator, both through the instrument drivers."""

    def __init__(self, dmm_address, cal_address, cal_model='Fluke 5560A', cal_baud=9600, interface='GPIB', cal_interface='RS-232', serial=None, transports=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual:
            self.log.virtual = True
        cal_name, cal_cls = CALIBRATORS[cal_model]
        self.cal_key = cal_name
        if transports:
            dmm_t, cal_t = transports
        else:
            kw = (serial or {}) if interface != 'GPIB' else {}
            dmm_t = drivers.open_visa(to_visa(dmm_address, interface), timeout=30, **kw)
            cal_kw = dict(baud=cal_baud) if cal_interface != 'GPIB' else {}
            cal_t = drivers.open_visa(to_visa(cal_address, cal_interface), timeout=20, **cal_kw)
        self.dmm = drivers.Keithley2000Cal(dmm_t, self.log, label=MODEL)
        self.cal = cal_cls(cal_t, self.log, label=cal_name)
        try:
            self.cal.open(verify_model=True)
            self.cal.clear_status()
            self.dmm.connect()
            self.dmm.require_no_errors('connecting')
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

    def close(self):
        try:
            self.cal.cleanup()                       # STBY, never raises
        except Exception:
            pass
        try:
            self.dmm.cleanup()                       # back to front panel control (never sends a CAL command)
        except Exception:
            pass
        for obj in (self.dmm, self.cal):
            try:
                obj.close()
            except Exception:
                pass
        self.save_log()

    def save_log(self):
        """Append the exact commands sent (the calibration code is masked) to ~/.calibration_suite/command_log.txt; a virtual (demo) session writes nothing."""
        self.log.append_default(f'Keithley {MODEL} adjustment session')


# ---------------------------------------------------------------------------------------------------------------------- the session
@dataclass
class StepRecord:
    step_id: str
    attempts: int = 0
    done: bool = False
    failed: bool = False
    indeterminate: bool = False
    number: int | None = None
    parameter: float | None = None
    cal_readback: float | None = None
    command: str = ''
    errors: list = field(default_factory=list)
    at: str = ''


class Session:
    """The state of one adjustment run. Every action the window offers is one method here, so the same code is what the tests exercise on the simulated bench.

    audit: adjustment_audit.AuditStore;  clock: time.monotonic (replaceable in tests);  wait: how long to wait (replaceable: demo mode shortens it, tests do not sleep)."""

    def __init__(self, io: AdjustIO, audit: adjustment_audit.AuditStore, scope=('DC', 'AC'), clock=time.monotonic, wait=time.sleep, scale=1.0, today=None):
        self.io, self.audit, self.scope = io, audit, tuple(scope)
        self.clock, self.wait, self.scale = clock, wait, scale
        self.today = today or date.today()
        self.acks = set()
        self.records = {s['id']: StepRecord(s['id']) for s in STEPS}
        self.unlocked = False
        self.initiated = False
        self.dates_set = False
        self.save_sent = False
        self.saved = False
        self.locked_again = False
        self.aborted = False
        self.count_before = self.count_after = None
        self._hookup_at = {}
        self.source_on = None

    # ---- convenience
    @property
    def fw_class(self):
        return self.io.dmm.fw_class

    @property
    def cal_key(self):
        return self.io.cal_key

    on_log = None                                   # the window sets a callback(row, step_id) to show each audit line

    def log(self, action, outcome='', detail='', step_id=''):
        row = self.audit.log(action, outcome, detail, step_id)
        if row is not None and self.on_log is not None:
            try:
                self.on_log(row, step_id)
            except Exception:
                pass
        return row

    def plan(self):
        """The steps this run will do, in the manual's order, for the chosen scope and the firmware's numbering."""
        if self.fw_class not in ('A20+', 'A19-'):
            return []
        return available_steps(self.fw_class, self.scope)

    def next_step(self):
        for s in self.plan():
            if not self.records[s['id']].done:
                return s
        return None

    def all_done(self):
        return bool(self.plan()) and self.next_step() is None

    # ---- confirmations the operator gives (each is recorded)
    def acknowledge(self, key, text=''):
        self.acks.add(key)
        self.log('CONFIRMED', 'OK', f'{key}: {text}' if text else key)

    def set_firmware_class(self, fw_class, how):
        self.io.dmm.set_firmware_class(fw_class)
        self.log('FIRMWARE', 'OK', f'numbering {parse_firmware_label(fw_class)} ({how}; *IDN? revision {self.io.dmm.fw_rev or "not understood"})')

    # ---- 1. prepare (nothing here touches the calibration)
    def prepare(self):
        """INPUTS switch must be FRONT (cannot be set remotely); DC volts function and SLOW rate (10 PLC) set and read back (p. 2-14 step 3)."""
        dmm = self.io.dmm
        have = dmm.front_rear()
        if have != 'FRONT':
            raise InstrumentError(f'The INPUTS switch is on {have}. Every step uses the FRONT inputs (p. 2-15): move the switch, then try again.')
        nplc = float(SPEC['times']['nplc_slow'])
        dmm.send('func.dcv')                                   # DC volts function, read back (the reply text is UNVERIFIED, the driver accepts VOLT:DC / VOLT)
        reply = dmm.ask('func.query')
        if drivers.keithley_2000._text(reply).replace('"', '') not in drivers.keithley_2000.FUNC_ACCEPT['DCV']:
            raise InstrumentError(f'DC volts was not selected (:SENS:FUNC? answered {reply.strip()!r}).')
        dmm.send('nplc.dcv', nplc=nplc)
        reply = dmm.ask('nplc.query.dcv')
        if abs(_number(reply) - nplc) > 1e-6:
            raise InstrumentError(f'SLOW (10 PLC) was not accepted (:SENS:VOLT:DC:NPLC? answered {reply.strip()!r}).')
        dmm.require_no_errors('selecting DC volts / SLOW')
        self.log('PREPARE', 'OK', 'INPUTS FRONT; DC volts function, 10 PLC (SLOW) set and read back')

    def reset(self, confirm=None):
        """Reset the 2000 (the unit under test, notice asked first via `confirm`) and the calibrator to their defaults BEFORE anything else; the calibration stays locked
        (nothing here sends a CAL command). Raises reset_startup.ResetDeclined / ResetFailed."""
        rep = self.io.reset_at_start(confirm=confirm)
        self.log('RESET', 'OK', 'Instruments reset to default settings: ' + ', '.join(rep.names))
        return rep

    # ---- 2. unlock
    def unlock(self, code):
        """The operator-confirmed unlock. The code is passed straight to the driver and is not kept, logged or written anywhere."""
        for need, why in (('conditions', 'warm-up and conditions'), ('as_found', 'the As Found performance verification'), ('authorised', 'authorisation to adjust'),
                          ('notice', 'the "this changes the instrument calibration" notice')):
            if need not in self.acks:
                raise AdjustmentError(f'Not confirmed yet: {why}.')
        if self.fw_class not in ('A20+', 'A19-'):
            raise AdjustmentError('The firmware numbering (A19 and earlier / A20 and later) has not been established.')
        if self.audit.run_id is None:
            raise AdjustmentError('Start an adjustment record first.')
        dmm = self.io.dmm
        try:
            dmm.unlock(code)
        except Exception as exc:
            self.log('UNLOCK', 'FAILED', str(exc).splitlines()[0])
            raise
        finally:
            code = None
        self.unlocked = True
        self.log('UNLOCK', 'OK', ':CAL:PROT:CODE sent once (code not recorded); :CAL:PROT:LOCK? read 1 (unlocked)')
        try:
            dmm.initiate()
        except Exception as exc:
            self.log('INITIATE', 'FAILED', str(exc).splitlines()[0])
            raise
        self.initiated = True
        self.log('INITIATE', 'OK', ':CAL:PROT:INIT sent once')
        self.audit.set_status('UNLOCKED')

    # ---- 3. one step
    def check_order(self, step):
        nxt = self.next_step()
        if nxt is None or nxt['id'] != step['id']:
            raise AdjustmentError(f'The next step is {nxt["id"] + " " + nxt["title"] if nxt else "none"}; the manual\'s order is kept.')

    def mark_hookup(self, step):
        """The operator says the wiring for this step is done (the thermal wait starts now)."""
        self._hookup_at[step['id']] = self.clock()
        self.log('HOOKUP', 'CONFIRMED', f'{step["title"]}', step['id'])

    def thermal_remaining(self, step):
        if not step.get('thermal_wait'):
            return 0.0
        t0 = self._hookup_at.get(step['id'])
        if t0 is None:
            return THERMAL_WAIT_S * self.scale
        return max(0.0, THERMAL_WAIT_S * self.scale - (self.clock() - t0))

    def program_source(self, step, hv_ok=False):
        """Standby, program the calibrator for the step, read it back and compare, read its error queue, then OPERATE (confirmed) and let it settle.  Returns the calibrator's own
        read-back value (volts / amps / ohms).  A step with no calibrator output leaves it in STANDBY."""
        io, cal = self.io, self.io.cal
        io.standby()
        src = step['source']
        if not src:
            self.source_on = None
            return None
        if is_hv(step) and not hv_ok:
            raise AdjustmentError('High voltage: the operator has not confirmed this step.')
        value = float(src['value'])
        kind = src['kind']
        freq = float(src['frequency']) if src.get('frequency') else None
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
                cal.set_compensation('WIRE4' if value < ZCOMP_LIMIT else 'NONE')
        cal.check_error(step['title'])                     # the calibrator refuses outputs it cannot make; never operate then
        got = _number(cal.ask('out.query'))        # OUT? reply format UNVERIFIED on the 5560A; the first number is the amplitude
        if abs(got - value) > OUT_REL_TOL * abs(value) + 1e-12:
            raise InstrumentError(f'{cal.label} read back {got:g}, not the {value:g} that was programmed: not switching the output on.')
        cal.operate()                                      # OPER, read back
        self.source_on = step['id']
        self.log('SOURCE', 'OK', f'{source_text(step)} programmed, read back {got:.9g}, OPERATE confirmed', step['id'])
        self.wait(settle_for(step) * self.scale)
        return got

    def send_step(self, step, parameter=None, typed_ack=False, rerun_ack=False):
        """Send ONE calibration step (this changes the volatile constants). Needs: unlocked + initiated, the manual's order, the thermal wait over, a parameter inside the manual's
        range for DC steps 3 to 13, the calibrator in operate where one is needed, and `rerun_ack` for a step that failed before.  The calibrator goes to STANDBY afterwards, also on error.
        Returns the StepRecord. Raises CalibrationError / StepIndeterminate (nothing is sent again)."""
        rec = self.records[step['id']]
        if not (self.unlocked and self.initiated):
            raise AdjustmentError('Calibration is not unlocked.')
        if self.save_sent or self.aborted:
            raise AdjustmentError('The adjustment is finished.')
        self.check_order(step)
        if (rec.failed or rec.indeterminate) and not rerun_ack:
            raise AdjustmentError('This step failed before. It is only repeated on a fresh, explicit confirmation of the operator (the program never repeats a command by itself).')
        if step.get('thermal_wait') and self.thermal_remaining(step) > 0:
            raise AdjustmentError(f'Thermal equilibrium: {self.thermal_remaining(step):.0f} s still to wait (p. 2-15).')
        if step['source'] is not None and self.source_on != step['id']:
            raise AdjustmentError('The calibrator has not been programmed and switched on for this step.')
        value = None
        if step['param'] is not None:
            if parameter is None:
                raise AdjustmentError('This step needs the calibrator value as its parameter.')
            value, why = validate_parameter(step, parameter)
            if value is None:
                raise AdjustmentError(why)
        rec.attempts += 1
        rec.parameter = None if value is None else float(value)
        rec.command = command_text(step, self.fw_class, value)
        rec.at = datetime.now().isoformat(timespec='seconds')
        self.log('STEP_SENT' if rec.attempts == 1 else 'STEP_RERUN', 'SENT', rec.command, step['id'])
        try:
            rec.number = self.io.dmm.calibrate_step(step, None if value is None else float(value))
        except cal_driver.StepIndeterminate as exc:
            rec.indeterminate, rec.failed = True, False
            self.log('STEP', 'INDETERMINATE', str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        except cal_driver.CalibrationError as exc:
            rec.failed, rec.indeterminate, rec.errors = True, False, list(exc.errors)
            self.log('STEP', 'FAILED', ' | '.join(exc.errors) or str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        except Exception as exc:
            rec.failed = True
            self.log('STEP', 'ERROR', str(exc).splitlines()[0], step['id'])
            self._standby_after()
            raise
        rec.done, rec.failed, rec.indeterminate, rec.errors = True, False, False, []
        self.log('STEP', 'OK', f'{rec.command}: completed, error queue empty', step['id'])
        self._standby_after()
        return rec

    def confirm_indeterminate(self, step, front_panel_idle: bool):
        """After a step whose *OPC? gave no answer the operator looks at the 2000: CALIBRATING gone -> read the error queue (read-only) and judge; still busy -> nothing is decided."""
        rec = self.records[step['id']]
        if not rec.indeterminate:
            raise AdjustmentError('This step is not waiting for a decision.')
        if not front_panel_idle:
            self.log('STEP', 'STILL BUSY', 'operator: the 2000 is still calibrating', step['id'])
            return None
        errors = self.io.dmm.drain_errors()
        if errors:
            rec.failed, rec.indeterminate, rec.errors = True, False, errors
            self.log('STEP', 'FAILED', ' | '.join(errors), step['id'])
            raise cal_driver.CalibrationError('The 2000 reported: ' + ' | '.join(errors), errors)
        rec.done, rec.indeterminate = True, False
        self.log('STEP', 'OK (operator)', 'completion confirmed by the operator from the front panel; error queue empty', step['id'])
        return rec

    def _standby_after(self):
        try:
            self.io.standby()
            self.source_on = None
        except Exception as exc:
            self.log('STANDBY', 'COULD NOT CONFIRM', str(exc).splitlines()[0])
            raise SafetyError('The calibrator output could not be confirmed in STANDBY: check its front panel before touching any lead.') from None

    # ---- 4. dates, save, lock
    def set_dates(self, calibrated: date | None = None, due: date | None = None):
        if not self.all_done():
            raise AdjustmentError('Not every step of the chosen scope has been completed.')
        calibrated = calibrated or self.today
        due = due or default_due(calibrated, SPEC['times']['date_years'])
        self.io.dmm.set_dates(calibrated, due)
        self.dates_set = True
        self.log('DATES', 'OK', f'calibration date {calibrated.isoformat()}, next due {due.isoformat()}, each read back')
        return calibrated, due

    def save(self, phrase):
        """:CAL:PROT:SAVE: the constants become permanent. Needs every step done, the dates set and the typed phrase."""
        if phrase != CONFIRM_SAVE:
            raise AdjustmentError(f'Type {CONFIRM_SAVE} to store the constants.')
        if not self.all_done():
            raise AdjustmentError('Not every step of the chosen scope has been completed: nothing is saved (a partly adjusted instrument is never stored).')
        if not self.dates_set:
            raise AdjustmentError('Set the calibration dates first (the 2000 refuses to save without them, errors +438 / +439).')
        if self.save_sent:
            raise AdjustmentError(':SAVE was already sent.')
        dmm = self.io.dmm
        try:
            self.count_before = dmm.count()
        except Exception as exc:
            self.count_before = None
            self.log('COUNT', 'UNAVAILABLE', f'before: {str(exc).splitlines()[0]}')
        self.save_sent = True
        self.log('SAVE', 'SENT', ':CAL:PROT:SAVE (permanent; confirmed by the operator)')
        self.audit.set_status('SAVE_SENT')
        try:
            dmm.save()
        except Exception as exc:
            self.log('SAVE', 'NOT CONFIRMED', str(exc).splitlines()[0])
            self.audit.set_status('SAVE_NOT_CONFIRMED')
            raise
        self.saved = True
        try:
            self.count_after = dmm.count()
        except Exception:
            self.count_after = None
        self.log('SAVE', 'OK', f'completion confirmed, error queue empty; calibration count before {self.count_before} after {self.count_after} (not used to judge: whether it changes on save is UNVERIFIED)')
        self.audit.set_status('SAVED_NOT_VERIFIED')

    def relock(self):
        """:CAL:PROT:LOCK and :CAL:PROT:LOCK? must read 0."""
        self.io.dmm.lock()
        self.unlocked = False
        self.locked_again = True
        self.log('LOCK', 'OK', ':CAL:PROT:LOCK sent; :CAL:PROT:LOCK? read 0 (locked)')

    # ---- 5. abort
    def abort(self, reason='operator'):
        """Stop. Calibrator to STANDBY, calibration locked again where possible, and an honest statement of what is and is not changed. Never raises. Returns the text."""
        self.aborted = True
        notes = []
        try:
            self.io.standby()
        except Exception as exc:
            notes.append('The calibrator could not be confirmed in STANDBY (' + str(exc).splitlines()[0] + '): check it before touching any lead.')
        if self.unlocked:
            try:
                self.relock()
            except Exception as exc:
                notes.append('Calibration could NOT be locked again (' + str(exc).splitlines()[0] + '): it may still be open. Do not leave the instrument unattended; cycle its power.')
        if self.save_sent and self.saved:
            what = 'The constants WERE saved (:CAL:PROT:SAVE completed). They cannot be restored by this program (the manual has no restore command); run the performance verification.'
        elif self.save_sent:
            what = (':CAL:PROT:SAVE was sent but its completion was NOT confirmed. Whether the constants were stored is UNKNOWN: read the 2000\'s calibration count and dates, '
                    'and run the performance verification.')
        elif any(r.attempts for r in self.records.values()):
            what = ('The constants were NOT saved: the manual says calculated constants are only temporary until :CAL:PROT:SAVE is sent (pp. 2-19, 3-8), so the stored calibration is '
                    'unchanged. The manual does not say whether :LOCK discards the temporary constants at once: switch the 2000 off and on again before using it, then run the performance verification.')
        else:
            what = 'No calibration step was sent: the calibration is unchanged.'
        text = f'Adjustment stopped ({reason}). ' + what + (' ' + ' '.join(notes) if notes else '')
        self.log('ABORT', 'DONE', text)
        self.audit.set_status('SAVED_NOT_VERIFIED' if self.saved else 'ABORTED')
        return text

    # ---- summary
    def summary_lines(self):
        out = []
        for s in self.plan():
            r = self.records[s['id']]
            out.append(f'{s["id"]}  {s["title"]}: ' + ('done' if r.done else 'FAILED' if r.failed else 'indeterminate' if r.indeterminate else 'pending'))
        return out
