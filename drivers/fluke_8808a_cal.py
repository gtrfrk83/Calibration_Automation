"""Fluke 8808A CALIBRATION (adjustment) interface: the RS-232 calibration dialog.  This is the ONLY place in the suite that sends *TER, a calibration function name,
CALREF, the Enter key or EXIT to the 8808A.

Everything here CHANGES the calibration of the meter.  The performance-verification driver (drivers/fluke_8808a.py, unchanged) never sends them (cmdreg's forbidden list for
the 8808A still holds for overrides); this subclass exists for the guided adjustment (Procedures/Fluke_8808A_Adjustment.py, engine fluke8808a_adjustment.py) and for nothing else.

Source: Fluke 8808A Digital Multimeter Calibration Manual, October 2008 (CM below), chapter 3 'Adjustment (Calibration)', read from rendered page images:
  'RS-232 Calibration (Manual)' p. 3-16: enable with "*TER" (the meter returns "Select a Function or input EXIT to QUIT!"); send "VDC", "VAC", "ADC", "AAC", "OHMS" or
  "FREQ" (the meter returns "XXXXXX V, 0 HZ", the recommended calibration value, also shown on the display); "CALREF XXXXXX" overwrites it ("=>" returned when acceptable,
  otherwise "!>"); push the Enter key to confirm the value; with a stable input push the Enter key to start calibrating the point (the meter returns "WAIT..." meanwhile); when
  a point finishes a new recommended value is sent automatically; when the last point of the function finishes the meter goes IDLE and sends "Select a Function or input EXIT
  to QUIT!" again; "EXIT" leaves the calibration mode at any time (a function not completely calibrated then shows CAL ERROR).
  p. 3-17 notes: "W4" after the recommended value = 4-wire compensation enabled; "Disconnect Test Leads!", "Connect to mA socket!", "Connect to 10A socket" (current calibration).

Every command below is printed in that manual, so each is registered with its page; what the manual does NOT say is listed in UNVERIFIED below and in the procedure's report.

UNVERIFIED (not stated by the manual; the program is written so that none of these can silently make a wrong calibration):
  * whether *TER is accepted without the front-panel CAL seal removed / Cal Enable button pressed (the manual describes the button only for the FRONT-PANEL method, p. 3-11); if
    the banner does not come back the program stops and says so; it never presses or assumes anything, and there is NO password: the manual prints none (nothing to mask or log).
  * the reply of the meter to each line it receives beyond the four strings the manual quotes; the unit and prefix of the recommended value ("XXXXXX V, 0 HZ" is printed for
    every function); the number format CALREF takes (the program sends at most six significant digits, in the unit the meter used in its own recommended value);
    the Enter key itself (the manual says "push the Enter key": the program sends an EMPTY LINE with this driver's line end);
  * whether prompts ("=>", "?>", "!>") arrive with Echo off (the manual says prompts are only sent while Echo is on, p. 4-6 of the Users Manual, but describes "=>" / "!>" for CALREF);
    when no prompt comes back after CALREF the acceptance is NOT confirmed by the meter and the operator confirms the value on the display;
  * how long a point takes (POINT_TIMEOUT_S, QUIET_S are choices of this driver, not manual figures); a point whose completion is not seen is reported 'indeterminate', never repeated;
  * whether each point's constants are stored when the point finishes or only when the whole function is complete, whether the meter keeps points calibrated before an EXIT in the
    middle of a function (it only says CAL ERROR), and whether *ESR? still answers inside the dialog (it is read only AFTER EXIT);
  * whether any message other than the quoted ones is sent (an unknown line is shown to the operator and logged; it is never interpreted as success).

Writes are sent once and NEVER retried (a write's effect on the calibration is unknown after a failure).  Only read-only queries may be retried.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import InstrumentError
from .fluke_8808a import Fluke8808A
from .transport import TransportError

CM = 'Fluke 8808A Calibration Manual (Oct 2008)'
FUNCTIONS = ('VDC', 'VAC', 'ADC', 'AAC', 'OHMS', 'FREQ')
QUIET_S = 1.5                  # a burst of replies is over when the meter has been silent this long (this driver's choice, UNVERIFIED: the manual gives no reply timing)
POINT_TIMEOUT_S = 180.0        # the longest this driver waits for a point to finish (UNVERIFIED: the manual gives no duration)
SIGNIFICANT = 6                # the meter takes six digits (front panel S1 to S6, p. 3-11; "CALREF XXXXXX", p. 3-16)

BANNER = 'select a function'
LEAD_MESSAGES = (('disconnect test leads', 'DISCONNECT'), ('connect to ma socket', 'MA'), ('connect to 10a socket', '10A'))
_NUM = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
REC_RE = re.compile(rf'^\s*({_NUM})\s*([A-Za-zµμΩ]*)\s*(?:,\s*({_NUM})\s*([A-Za-z]*))?\s*(W4)?\s*$')
PREFIX = {'m': Decimal('0.001'), 'M': Decimal(1000000), 'u': Decimal('0.000001'), 'µ': Decimal('0.000001'), 'μ': Decimal('0.000001'), 'k': Decimal(1000), 'K': Decimal(1000)}
BASE_UNITS = ('V', 'A', 'OHM', 'OHMS', 'HZ', 'Ω')


class CalibrationError(InstrumentError):
    """The meter refused or reported an error during the calibration dialog ('!>' / '?>' or an unknown message)."""

    def __init__(self, message, lines=()):
        super().__init__(message)
        self.lines = list(lines)


class StepIndeterminate(InstrumentError):
    """The completion of a calibration point could not be confirmed (no 'next value' / 'Select a Function' within the wait). Nothing was sent again."""


@dataclass
class Recommended:
    """The recommended calibration value the meter sent ("XXXXXX V, 0 HZ", optionally followed by W4)."""
    value: float                       # base units (V, A, ohm; Hz for a frequency point)
    unit: str = ''                     # the unit text as sent (upper case, without prefix)
    scale: Decimal = Decimal(1)        # the prefix as sent (mV -> 0.001): CALREF is sent in the same scale
    hz: float | None = None            # the second part "0 HZ"
    w4: bool = False
    raw: str = ''

    def text(self):
        return self.raw


@dataclass
class Reply:
    """What a burst of lines from the meter says."""
    lines: list = field(default_factory=list)
    prompts: list = field(default_factory=list)
    recommended: Recommended | None = None
    messages: list = field(default_factory=list)       # 'DISCONNECT' | 'MA' | '10A'
    wait: bool = False
    idle: bool = False                                  # "Select a Function or input EXIT to QUIT!"
    unknown: list = field(default_factory=list)

    @property
    def error_prompt(self):
        return next((p for p in self.prompts if p in ('?>', '!>')), None)

    @property
    def accepted(self):
        return '=>' in self.prompts and not self.error_prompt


def parse_unit(token: str):
    """(scale, base unit) of a unit token such as 'V', 'mV', 'OHM', 'KOHM', 'HZ' ('' -> (1, ''))."""
    t = token.strip()
    if not t:
        return Decimal(1), ''
    if t.upper() in BASE_UNITS:
        return Decimal(1), t.upper()
    if len(t) > 1 and t[0] in PREFIX and t[1:].upper() in BASE_UNITS:
        if t[0] == 'M' and t[1:].upper() in ('V', 'A'):          # an upper-case 'MV' / 'MA' is milli: the 8808A has no mega-volt or mega-amp range (UNVERIFIED: the reply format is not printed)
            return PREFIX['m'], t[1:].upper()
        return PREFIX[t[0]], t[1:].upper()
    return Decimal(1), t.upper()


def parse_line(line: str, out: Reply):
    text = line.strip()
    low = text.lower()
    if not text:
        return
    if text in ('=>', '?>', '!>'):
        out.prompts.append(text)
        return
    if BANNER in low:
        out.idle = True
        return
    if low.startswith('wait'):
        out.wait = True
        return
    for needle, tag in LEAD_MESSAGES:
        if needle in low:
            out.messages.append(tag)
            return
    m = REC_RE.match(text)
    if m:
        scale, unit = parse_unit(m.group(2))
        value = Decimal(m.group(1)) * scale
        hz = None
        if m.group(3) is not None:
            hz = float(Decimal(m.group(3)) * parse_unit(m.group(4))[0])
        if unit == 'HZ' and hz is None:
            hz = float(value)
        out.recommended = Recommended(value=float(value), unit=unit, scale=scale, hz=hz, w4=bool(m.group(5)), raw=text)
        return
    out.unknown.append(text)


def parse_lines(lines) -> Reply:
    r = Reply(lines=list(lines))
    for line in lines:
        parse_line(line, r)
    return r


def reference_text(value, rec: Recommended | None = None) -> str:
    """The CALREF argument: `value` (base units) in the unit scale the meter used, at most six significant digits, plain notation. Raises InstrumentError when more digits are needed."""
    scale = rec.scale if rec is not None else Decimal(1)
    d = Decimal(str(value)) / scale
    if d == 0:
        return '0'
    digits = d.normalize().as_tuple().digits
    if len(digits) > SIGNIFICANT:
        raise InstrumentError(f'the meter takes {SIGNIFICANT} digits (Calibration Manual p. 3-11 / 3-16): {format(d.normalize(), "f")} needs {len(digits)}. Round the value yourself and enter it again.')
    return format(d.normalize(), 'f')


def _action(template, name, description, ref, verified=True, placeholders=None, kind='action'):
    return Cmd(template, name, description + ' (changes the calibration; never overridable)', placeholders=placeholders or {}, kind=kind, risk='locked', verified=verified, ref=f'{CM}, {ref}')


def _build_commands():
    c = {}
    c['cal.enter'] = _action('*TER', 'Enter calibration mode', 'Enables calibration; the meter returns "Select a Function or input EXIT to QUIT!". Sent ONCE per adjustment. Whether the front-panel '
                             'Cal Enable button is needed is not stated for RS-232 (UNVERIFIED)', 'p. 3-16 (RS-232 Calibration (Manual))')
    for fn in FUNCTIONS:
        c[f'cal.func.{fn.lower()}'] = _action(fn, f'Calibrate {fn}', 'Selects the function to calibrate; the meter returns its recommended calibration value ("XXXXXX V, 0 HZ"). '
                                              'ALL points of the function must be calibrated before leaving the mode (CAL ERROR otherwise)', 'p. 3-16 step 1')
    c['cal.calref'] = _action('CALREF {value}', 'Overwrite the recommended value', '"=>" is returned if the value is acceptable, otherwise "!>". The number format and unit are not '
                              'specified beyond "CALREF XXXXXX" (UNVERIFIED): at most six digits, in the unit the meter used for its own recommended value', 'p. 3-16 note under step 1',
                              verified=False, placeholders={'value': Placeholder('str', '', '0.1999')})
    c['cal.enter_key'] = _action('', 'Enter key', 'The Enter key: first press confirms the calibration value, second press (with a stable input) STARTS calibrating the point ("WAIT..." is returned). '
                                 'Sent as an empty line (UNVERIFIED: the manual says only "push the Enter key")', 'p. 3-16 steps 2 and 3', verified=False)
    c['cal.exit'] = _action('EXIT', 'Exit calibration mode', 'Leaves the calibration mode at any time; a function that was not completely calibrated shows CAL ERROR', 'p. 3-16')
    return c


CAL_COMMANDS = _build_commands()


class Fluke8808ACal(Fluke8808A):
    """The 8808A as the unit under ADJUSTMENT: the verification driver plus the calibration dialog."""
    COMMANDS = CAL_COMMANDS
    QUIET_S = QUIET_S
    POINT_TIMEOUT_S = POINT_TIMEOUT_S
    in_cal = False
    state = None                 # None (not in calibration) | 'IDLE' | 'VALUE' (a recommended value is waiting) | 'CONFIRMED' (the value was confirmed with Enter)
    function = None              # the function being calibrated
    recommended = None
    tick = None                  # an optional callable run while a long wait goes on (the window keeps itself alive with it)
    enter_sent = 0

    # ---- wire access --------------------------------------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        if cmd == '' and log_as is None:
            log_as = '<Enter key: empty line>'
        super().write(cmd, log_as)

    def _read_burst(self, quiet_s=None, total_s=None, until=None) -> Reply:
        """Read every line the meter sends until it has been silent for `quiet_s` (and, when `until` is given, until until(reply) is true or `total_s` has passed).
        Read-only: nothing is written here.  Every raw line is logged."""
        quiet = float(self.QUIET_S if quiet_s is None else quiet_s)
        total = float(quiet if total_s is None else total_s)
        deadline = time.monotonic() + total
        sent = {c.strip().upper() for c in (self._since or []) if c.strip()}
        lines = []
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(quiet, 0.001))
        try:
            while True:
                t0 = time.monotonic()
                try:
                    raw = self.t.read()
                except TransportError:
                    if until is None or until(parse_lines(lines)) or time.monotonic() >= deadline:
                        break
                    spent = time.monotonic() - t0
                    if spent < quiet:
                        time.sleep(quiet - spent)          # a transport that answers 'nothing' at once (or a short read) must not spin
                    if self.tick is not None:
                        self.tick()
                    continue
                text = str(raw).strip()
                if text and text.upper() in sent:          # Echo ON: the meter repeats what it was sent; that is not a reply
                    self.echo_seen += 1
                    self.log.add('<<', f'{text}  [echo of the command, skipped]', self.label)
                elif text:
                    lines.append(text)
                    self.log.add('<<', text, self.label)
                if self.tick is not None:
                    self.tick()
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
            self._since = []
        return parse_lines(lines)

    def _fail_on_error(self, reply: Reply, what: str):
        if reply.error_prompt:
            kind = {'?>': 'did not understand it (command error)', '!>': 'understood it but did not execute it (execution error)'}[reply.error_prompt]
            raise CalibrationError(f'{self.MODEL}: the meter returned {reply.error_prompt!r} after {what}: it {kind}. Nothing was sent again.', reply.lines)
        if reply.unknown:
            self.log.add('!!', f'unrecognised text from the meter after {what}: {" | ".join(reply.unknown)}', self.label)

    # ---- the dialog ---------------------------------------------------------------------------------------------------------------------------
    def enter_cal_mode(self) -> Reply:
        """*TER once; the banner "Select a Function or input EXIT to QUIT!" must come back (p. 3-16). Anything else: nothing was changed, the meter is NOT in calibration."""
        if self.in_cal:
            raise InstrumentError('The calibration mode was already entered in this session (*TER is sent once).')
        self.send('cal.enter')
        reply = self._read_burst()
        self._fail_on_error(reply, '*TER')
        if not reply.idle:
            raise CalibrationError(f'{self.MODEL}: *TER was not answered with "Select a Function or input EXIT to QUIT!" (got: {" | ".join(reply.lines) or "nothing"}). The meter is not in the '
                                   'calibration mode. The manual describes the CAL seal and the Cal Enable button only for the front-panel method (p. 3-11) and does not say whether *TER needs them.',
                                   reply.lines)
        self.in_cal, self.state, self.function, self.recommended = True, 'IDLE', None, None
        return reply

    def select_function(self, function: str) -> Reply:
        """Select the function to calibrate; returns the reply holding the recommended value of its first point."""
        fn = str(function).upper()
        if fn not in FUNCTIONS:
            raise InstrumentError(f'{fn} is not a calibration function of the 8808A ({", ".join(FUNCTIONS)}).')
        if not self.in_cal or self.state != 'IDLE':
            raise InstrumentError('A function can only be selected in the calibration mode while the meter is idle (not inside another function).')
        self.send(f'cal.func.{fn.lower()}')
        reply = self._read_burst(total_s=self.QUIET_S * 2)
        self._fail_on_error(reply, fn)
        if reply.recommended is None:
            raise CalibrationError(f'{self.MODEL}: {fn} was not answered with a recommended calibration value (got: {" | ".join(reply.lines) or "nothing"}). Leave the mode with EXIT.', reply.lines)
        self.function, self.recommended, self.state = fn, reply.recommended, 'VALUE'
        return reply

    def set_reference(self, text: str) -> str:
        """CALREF <text>: returns 'accepted' ('=>' came back) or 'unconfirmed' (no prompt at all). A '!>' / '?>' raises. Sent once, never retried."""
        if self.state != 'VALUE':
            raise InstrumentError('CALREF is only sent while a recommended value is waiting (before the first Enter).')
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', str(text)):
            raise InstrumentError(f'CALREF takes a plain number, not {text!r}.')
        self.send('cal.calref', value=str(text))
        reply = self._read_burst()
        self._fail_on_error(reply, f'CALREF {text}')
        return 'accepted' if reply.accepted else 'unconfirmed'

    def confirm_value(self) -> Reply:
        """The first Enter: confirms the calibration value. Returns the reply (it may carry 'Disconnect Test Leads!' / 'Connect to ... socket' / W4 messages)."""
        if self.state != 'VALUE':
            raise InstrumentError('There is no recommended value to confirm.')
        self.enter_sent += 1
        self.send('cal.enter_key')
        reply = self._read_burst()
        self._fail_on_error(reply, 'the Enter key (confirm value)')
        self.state = 'CONFIRMED'
        return reply

    def start_point(self) -> Reply:
        """The second Enter: STARTS calibrating the point (this changes the calibration). Waits for the next recommended value or the idle banner. Never repeated.
        Raises CalibrationError ('!>' / '?>'), StepIndeterminate (no completion seen)."""
        if self.state != 'CONFIRMED':
            raise InstrumentError('The value must be confirmed (first Enter) before the point is started.')
        self.enter_sent += 1
        self.send('cal.enter_key')
        seen = {'wait': False}

        def finished(r: Reply):
            seen['wait'] = seen['wait'] or r.wait
            return bool(r.error_prompt) or r.idle or r.recommended is not None
        reply = self._read_burst(total_s=self.POINT_TIMEOUT_S, until=finished)
        self._fail_on_error(reply, 'the Enter key (start calibrating)')
        if reply.idle:
            self.state, self.function, self.recommended = 'IDLE', None, None
        elif reply.recommended is not None:
            self.state, self.recommended = 'VALUE', reply.recommended
        else:
            raise StepIndeterminate(f'The meter did not say the point was finished within {self.POINT_TIMEOUT_S:g} s (last text: {" | ".join(reply.lines) or "nothing"}). The Enter key was NOT sent again: '
                                    'look at the meter display (flashing star = still calibrating) before deciding.')
        return reply

    def read_late(self, quiet_s=None) -> Reply:
        """Read-only: whatever the meter has sent since (a completion that arrived late). Writes nothing. Updates the dialog state like start_point does."""
        reply = self._read_burst(quiet_s=quiet_s)
        if reply.idle:
            self.state, self.function, self.recommended = 'IDLE', None, None
        elif reply.recommended is not None and not reply.error_prompt:
            self.state, self.recommended = 'VALUE', reply.recommended
        return reply

    def exit_cal(self) -> list:
        """EXIT (leave the calibration mode) and then read *ESR? ONCE (read-only, never retried) for error bits. Returns the error names found (empty = none)."""
        self.send('cal.exit')
        reply = self._read_burst()
        self.in_cal, self.state, self.function, self.recommended = False, None, None, None
        self._fail_on_error(reply, 'EXIT')
        try:
            bits = self._int(self.ask('err.query'))
        except Exception as exc:
            self.log.add('!!', f'*ESR? after EXIT gave no answer ({str(exc).splitlines()[0]})', self.label)
            return []
        flags = []
        if bits is not None:
            from .fluke_8808a import ESR_NAMES
            flags = [name for bit, name in ESR_NAMES.items() if bits & bit]
        for f in flags:
            self.log.add('!!', f'event status after EXIT: {f}', self.label)
        return flags

    def cleanup(self):
        """Best effort, never raises: leave the calibration mode if it is still open, then back to the front panel."""
        if self.in_cal:
            try:
                self.send('cal.exit')
                self._read_burst(quiet_s=min(0.5, self.QUIET_S))
            except Exception:
                pass
            self.in_cal, self.state = False, None
        super().cleanup()
