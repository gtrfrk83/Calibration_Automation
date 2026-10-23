"""Keithley Model 2000 CALIBRATION (adjustment) interface: the remote :CALibration:PROTected commands.  This is the ONLY place in the suite that sends them.

Everything here CHANGES the calibration constants of the meter.  The performance-verification driver (drivers/keithley_2000.py) never sends a CAL command; this subclass
exists for the guided adjustment procedure (Procedures/Keithley_2000_Adjustment.py, engine keithley2000_adjustment.py) and for nothing else.

Source: Keithley Model 2000 Multimeter Calibration Manual 2000-905-01 Rev. F (CM below), read from rendered page images: SCPI command calibration pp. 2-14 to 2-19, command
summary Tables 3-1 / 3-2 / 3-3 (pp. 3-4, 3-5, 3-10, 3-16), command pages 3-6 to 3-17, error detection pp. 3-19 / 3-20, error list Table B-1 (pp. B-2, B-3).  Every command below is
printed in that manual, so each is `verified=True` for its WRITE form.  What the manual does NOT say is listed in UNVERIFIED below and in the procedure's report.

UNVERIFIED (not stated by the manual; the program is written so that none of these can silently make a wrong calibration):
  * what the 2000 answers to a WRONG :CODE (nothing is stated): the program reads :CAL:PROT:LOCK? afterwards and stops unless it reads 1 (unlocked, p. 3-7).
  * how long a calibration step / :SAVE takes: STEP_TIMEOUT_S / SAVE_TIMEOUT_S are this driver's choices; the manual only says to wait for completion (pp. 3-20: *OPC?).
    A *OPC? that does not answer is NEVER sent again by the driver and the step is reported as 'indeterminate'.
  * whether :CAL:PROT:LOCK or the front panel EXIT discards constants that were calculated but not saved (p. 2-19 / p. 3-8 only say they are "only temporary" until :SAVE).
  * whether :CAL:PROT:COUNt? increases when the constants are saved (it is read before and after and shown, never used to pass or fail).
  * the reply text of :CAL:PROT:DATE? / :NDUE? is printed as "<year>, <month>, <day>" (p. 3-8 / 3-9): the parser accepts any separator.
  * the revision text in *IDN? ("yyyyy/zzzzz", User Manual) for firmware A19 / A20: parsed as a letter and two digits; unparseable -> the operator must say which numbering applies.

Writes are sent once, read back where the manual provides a query (lock state, dates) and compared, and are NEVER retried.  Only read-only queries (:SYST:ERR?, :CAL:PROT:LOCK?, ...)
may be retried.  The calibration code is a secret placeholder: it goes on the wire and appears as ******** in the command log; it is never stored, and an error text that
carries the command is scrubbed before it leaves this module.
"""
from __future__ import annotations

import re
from datetime import date

from cmdreg import Cmd, Placeholder
from .base import InstrumentError
from .keithley_2000 import Keithley2000, _flag, _number
from .transport import TransportError

CM = 'Keithley 2000 Calibration Manual 2000-905-01 Rev. F'
STEP_TIMEOUT_S = 120.0        # transport timeout while waiting for *OPC? after one calibration step (this driver's choice, UNVERIFIED: the manual gives no duration)
SAVE_TIMEOUT_S = 60.0         # the same for :CAL:PROT:SAVE (UNVERIFIED)
CODE_RE = re.compile(r'^[A-Za-z0-9]{1,8}$')       # "Up to an 8-character string including letters and numbers" (p. 3-6)
DATE_YEARS = (1994, 2093)     # p. 3-8 / 3-9: <year> = 1994 to 2093
SECRET = {'code': Placeholder('secret')}


class CalibrationError(InstrumentError):
    """The 2000 reported errors while (or right after) a calibration command, e.g. '+402, "10 vdc full scale error"' (Table B-1)."""

    def __init__(self, message, errors=()):
        super().__init__(message)
        self.errors = list(errors)


class StepIndeterminate(InstrumentError):
    """The completion of a calibration command could not be confirmed (*OPC? gave no answer). Nothing was sent again."""


def _locked_cmd(template, name, description, ref, kind='set', placeholders=None, readback=None):
    return Cmd(template, name, description + ' (changes the calibration; never overridable)' if kind != 'query' else description + ' (never overridable)',
               placeholders=placeholders or {}, kind=kind, readback=readback, risk='locked', verified=True, ref=f'{CM}, {ref}')


def _build_commands():
    c = {}
    c['cal.code'] = Cmd(":CAL:PROT:CODE '{code}'", 'Unlock calibration (code)', 'Sends the calibration code; sent ONCE before the steps (never overridable; the code is masked in the log)',
                        placeholders=SECRET, kind='set', readback='cal.lock.query', risk='locked', verified=True, ref=f'{CM}, p. 2-14 step 5, p. 3-6 (:CODE)')
    c['cal.init'] = _locked_cmd(':CAL:PROT:INIT', 'Initiate calibration', 'Enables calibration; sent ONCE, after :CODE and before any step', 'p. 2-14 step 6, p. 3-7 (:INIT)')
    c['cal.lock'] = _locked_cmd(':CAL:PROT:LOCK', 'Lock calibration', 'Locks out comprehensive calibration again', 'p. 2-19, p. 3-7 (:LOCK)', readback='cal.lock.query')
    c['cal.lock.query'] = _locked_cmd(':CAL:PROT:LOCK?', 'Calibration lock state', '0 = locked, 1 = unlocked', 'p. 3-7 (:LOCK?)', kind='query')
    c['cal.save'] = _locked_cmd(':CAL:PROT:SAVE', 'Save calibration constants', 'Stores the calibration constants in EEROM (permanent)', 'p. 2-19, p. 3-8 (:SAVE)')
    c['cal.count.query'] = _locked_cmd(':CAL:PROT:COUN?', 'Calibration count', 'How many times the 2000 has been calibrated', 'p. 3-6 (:COUNt?)', kind='query')
    ymd = {'year': Placeholder('int', 'd', 2026), 'month': Placeholder('int', 'd', 1), 'day': Placeholder('int', 'd', 1)}
    c['cal.date'] = _locked_cmd(':CAL:PROT:DATE {year:d},{month:d},{day:d}', 'Calibration date', 'Stores the calibration date', 'p. 2-19, p. 3-8 (:DATE)', placeholders=ymd, readback='cal.date.query')
    c['cal.date.query'] = _locked_cmd(':CAL:PROT:DATE?', 'Calibration date query', 'Reply "<year>, <month>, <day>"', 'p. 3-8 (:DATE?)', kind='query')
    c['cal.ndue'] = _locked_cmd(':CAL:PROT:NDUE {year:d},{month:d},{day:d}', 'Next calibration due date', 'Stores the next due date', 'p. 2-19, p. 3-9 (:NDUE)', placeholders=ymd, readback='cal.ndue.query')
    c['cal.ndue.query'] = _locked_cmd(':CAL:PROT:NDUE?', 'Next due date query', 'Reply "<year>, <month>, <day>"', 'p. 3-9 (:NDUE?)', kind='query')
    for n in (1, 2):
        c[f'cal.dc.step{n}'] = _locked_cmd(f':CAL:PROT:DC:STEP{n}', f'DC calibration step {n}', 'Front short circuit' if n == 1 else 'Front open circuit', f'p. 2-15, p. 3-11 (:STEP{n})')
    for n in range(3, 14):
        c[f'cal.dc.step{n}'] = _locked_cmd(f':CAL:PROT:DC:STEP{n} {{value:.10g}}', f'DC calibration step {n}', 'Takes the exact calibrator value (volts, ohms or amps, within the range of Table 3-2)',
                                           'Tables 2-8 to 2-10 (pp. 2-16, 2-17), Table 3-2 (p. 3-10), pp. 3-11 to 3-15', placeholders={'value': Placeholder('float', '.10g', 10.0)})
    for n in range(1, 14):
        c[f'cal.ac.step{n}'] = _locked_cmd(f':CAL:PROT:AC:STEP{n}', f'AC calibration step {n}', 'No parameter: the stated voltage / current AND frequency must be applied',
                                           'Tables 2-11, 2-12 (pp. 2-18, 2-19), Table 3-3 (p. 3-16), p. 3-17')
    return c


CAL_COMMANDS = _build_commands()


def parse_firmware(idn: str):
    """(revision text, 'A20+' | 'A19-' | None) from a *IDN? reply 'KEITHLEY INSTRUMENTS INC.,MODEL 2000,0123456,A19  /A02' (revision of the digital board ROM first).
    The numbering of the DC steps depends on it (Table 3-1 note, p. 3-4).  None = not understood (the operator must choose)."""
    m = re.search(r',\s*([A-Za-z])(\d{2})\s*/\s*[A-Za-z]\d{2}\s*$', str(idn).strip())
    if not m:
        return None, None
    rev = m.group(1).upper() + m.group(2)
    if m.group(1).upper() != 'A':
        return rev, None
    return rev, ('A20+' if int(m.group(2)) >= 20 else 'A19-')


def step_number(step: dict, fw_class: str) -> int:
    """The :STEP<n> number of a spec step for the firmware class. DC only differs (p. 3-4). Raises InstrumentError for a step the firmware does not have."""
    if fw_class not in ('A20+', 'A19-'):
        raise InstrumentError('The firmware numbering (A19 and earlier / A20 and later) has not been established; no calibration step can be sent.')
    n = step['a20'] if fw_class == 'A20+' else step['a19']
    if n is None:
        raise InstrumentError(f'{step["title"]}: this step does not exist on firmware {fw_class} (Table 3-1 note, p. 3-4).')
    return int(n)


def _ints(reply):
    parts = re.findall(r'[-+]?\d+', str(reply))
    if len(parts) != 3:
        raise InstrumentError(f'expected "<year>, <month>, <day>", the 2000 answered {str(reply).strip()!r}')
    return tuple(int(p) for p in parts)


class Keithley2000Cal(Keithley2000):
    """The Model 2000 as the unit under ADJUSTMENT: the verification driver plus the :CAL:PROT commands."""
    COMMANDS = CAL_COMMANDS

    fw_rev = None
    fw_class = None
    _code_sent = False
    _init_sent = False
    _unlocked = False

    # ---- lifecycle ------------------------------------------------------------------------------------------------
    def connect(self):
        super().connect()
        self.fw_rev, self.fw_class = parse_firmware(self.idn)
        return self

    def set_firmware_class(self, fw_class):
        """The operator's choice when *IDN? could not be understood, or a confirmation of what it said."""
        if fw_class not in ('A20+', 'A19-'):
            raise InstrumentError('firmware class must be A20+ or A19-')
        self.fw_class = fw_class

    # ---- unlock / initiate (each sent exactly once) -------------------------------------------------------------------
    def lock_state(self) -> bool:
        """:CAL:PROT:LOCK? -> True when UNLOCKED (1), False when locked (0). A read-only query (may be retried)."""
        return _flag(self.query_retry('cal.lock.query', attempts=3, delay=0.5))

    def unlock(self, code: str):
        """:CAL:PROT:CODE '<code>' once, then :CAL:PROT:LOCK? must read 1 (set, read back, compare; never retried).  The code is never kept here and never logged."""
        if self._code_sent:
            raise InstrumentError('The calibration code was already sent in this session (the manual: send :CODE only once, p. 3-6). Disconnect and start again to try another code.')
        if not isinstance(code, str) or not CODE_RE.match(code):
            raise InstrumentError('The calibration code is 1 to 8 letters and digits (p. 3-6).')
        self._code_sent = True
        problem = None
        try:
            self.send('cal.code', code=code)
        except Exception as exc:                              # TransportError carries the command text (with the code) in its message: scrub it
            problem = str(exc).replace(code, '********')
        if problem is not None:                               # raised outside the except block: no chained exception keeps the original text
            raise InstrumentError('The calibration code could not be sent: ' + problem)
        code = None                                           # drop the only reference held here
        self._unlocked = self.lock_state()
        if not self._unlocked:
            self.drain_errors()
            raise InstrumentError(':CAL:PROT:LOCK? still reports LOCKED after the code was sent: the 2000 did not accept it (the manual does not say what a wrong code does). '
                                  'Nothing was changed. Do not send codes repeatedly: check the code, then disconnect and start again.')
        self.require_no_errors('unlocking')

    def initiate(self):
        """:CAL:PROT:INIT once (after :CODE, before any step). Never retried."""
        if not self._unlocked:
            raise InstrumentError('Calibration is locked: send the code first.')
        if self._init_sent:
            raise InstrumentError(':CAL:PROT:INIT was already sent in this session (the manual: once only, p. 3-7).')
        self._init_sent = True
        self.send('cal.init')
        self.require_no_errors('initiating calibration')

    # ---- errors ---------------------------------------------------------------------------------------------------------
    def drain_errors(self, limit=11) -> list:
        """Read :SYST:ERR? until '0, No error' (the queue holds 10, p. 5-63). Read-only, retried. Returns the error replies found (empty list = clean)."""
        found = []
        for _ in range(limit):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        return found

    def require_no_errors(self, context=''):
        found = self.drain_errors()
        if found:
            raise CalibrationError(f'The 2000 reported an error{" while " + context if context else ""}: ' + ' | '.join(found), found)

    # ---- completion --------------------------------------------------------------------------------------------------------
    def wait_complete(self, timeout_s=STEP_TIMEOUT_S):
        """*OPC? and wait for the '1' (p. 3-20). The transport timeout is raised for the wait and put back. Raises StepIndeterminate when nothing answers; the command is NOT sent again."""
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(float(timeout_s), prev or 0.0))
        try:
            reply = self.ask('opc.query')
        except TransportError as exc:
            raise StepIndeterminate(f'The 2000 did not confirm completion (*OPC? gave no answer within {timeout_s:g} s): {exc}') from None
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        if reply.strip() not in ('1', '+1'):
            raise StepIndeterminate(f'*OPC? answered {reply.strip()!r} instead of 1')

    # ---- one calibration step -----------------------------------------------------------------------------------------------
    def calibrate_step(self, step: dict, parameter=None):
        """Send ONE :CAL:PROT:DC|AC:STEPn [parameter]; wait for completion; read the error queue. Raises CalibrationError (errors reported), StepIndeterminate (no completion).
        Never retried here. Returns the command text number sent (for the audit)."""
        if not (self._unlocked and self._init_sent):
            raise InstrumentError('Calibration is not unlocked and initiated.')
        n = step_number(step, self.fw_class)
        scope = step['scope'].lower()
        key = f'cal.{scope}.step{n}'
        if scope == 'dc' and n >= 3:
            p = step.get('param')
            if p is None or parameter is None:
                raise InstrumentError(f'{step["title"]}: this step needs the calibrator value as its parameter.')
            lo, hi = float(p['lo']), float(p['hi'])
            if not (lo <= float(parameter) <= hi):
                raise InstrumentError(f'{step["title"]}: the parameter {float(parameter):g} is outside the range the manual allows ({lo:g} to {hi:g}).')
            self.send(key, value=float(parameter))
        else:
            if parameter is not None and scope == 'ac':
                raise InstrumentError('AC calibration steps take no parameter.')
            self.send(key)
        self.wait_complete()
        self.require_no_errors(f'calibrating {step["title"]}')
        return n

    # ---- dates, save, lock ------------------------------------------------------------------------------------------------------
    def _set_date(self, key, label, when: date):
        if not (DATE_YEARS[0] <= when.year <= DATE_YEARS[1]):
            raise InstrumentError(f'{label}: the year must be {DATE_YEARS[0]} to {DATE_YEARS[1]} (p. 3-8).')
        self.send(key, year=when.year, month=when.month, day=when.day)
        got = _ints(self.query_retry(f'{key}.query', attempts=3, delay=0.5))
        if got != (when.year, when.month, when.day):
            raise InstrumentError(f'{label} was not accepted: sent {when.isoformat()}, the 2000 answered {got[0]:04d}-{got[1]:02d}-{got[2]:02d}.')
        return got

    def set_dates(self, calibrated: date, due: date):
        """:CAL:PROT:DATE and :NDUE, each read back and compared (never retried). Without them :SAVE fails with +438 / +439 (Table B-1)."""
        if due <= calibrated:
            raise InstrumentError('The next due date must be after the calibration date.')
        self._set_date('cal.date', 'Calibration date', calibrated)
        self._set_date('cal.ndue', 'Next due date', due)
        self.require_no_errors('setting the calibration dates')

    def count(self):
        """:CAL:PROT:COUNt? -> the calibration count (read-only)."""
        return int(_number(self.query_retry('cal.count.query', attempts=3, delay=0.5)))

    def save(self):
        """:CAL:PROT:SAVE (permanent). Wait for completion, read the error queue. Never retried."""
        if not (self._unlocked and self._init_sent):
            raise InstrumentError('Calibration is not unlocked and initiated.')
        self.send('cal.save')
        self.wait_complete(SAVE_TIMEOUT_S)
        self.require_no_errors('saving the calibration constants')

    def lock(self):
        """:CAL:PROT:LOCK, then :CAL:PROT:LOCK? must read 0. Sent once, never retried."""
        self.send('cal.lock')
        state = self.lock_state()
        self._unlocked = state
        if state:
            raise InstrumentError(':CAL:PROT:LOCK? still reports UNLOCKED after :CAL:PROT:LOCK. Calibration may still be open: do not leave the instrument unattended.')

    def cleanup(self):
        """Back to the front panel; never sends a CAL command (the procedure locks explicitly)."""
        super().cleanup()
