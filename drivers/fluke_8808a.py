"""Fluke 8808A 5-1/2 digit bench multimeter, RS-232 only (no IEEE-488, no USB).

Every command below is taken from the 8808A Users Manual (Chapter 4, "Remote Operation"); each registry entry names the table and page. Facts the
manual does not give are NOT guessed: they are marked verified=False in COMMANDS and listed in the procedure's summary.

    Interface (Users Manual Table 4-1, p. 4-4 and Calibration Manual p. 1-10): RS-232 only. Factory settings 9600 baud, 8 data bits, no parity,
        1 stop bit, echo OFF; they are changed from the front panel only. Output terminator CR LF; input accepts CR, LF or CR LF (p. 4-7).
    Prompts ("=>" no error, "?>" command error, "!>" execution / device-dependent error; pp. 4-6 and 4-8) are, per the manual, sent ONLY while Echo
        is on, one after each command and AFTER its reply. With echo off (the default) nothing tells the controller that a command has finished, so
        this driver (1) leaves COMMAND_GAP_S between commands, (2) uses *OPC? as the "done" signal where it matters, and (3) is prompt-tolerant:
        on a real bench the '=>' prompt was seen after *RST although Echo had been set off before (the log shows it; WHY is not known), so a reply
        line that is only a prompt is skipped (read-only, bounded, logged as skipped) and a '?>' / '!>' prompt is raised as an error of the command it
        follows. Input is flushed after the *RST settle. A reply that is the echoed command text at connect time is refused with a clear message.
    Errors: there is no error queue. Command, execution and device-dependent errors set bits of the standard event status register, read with *ESR?
        (which also clears it). Mask 0x3C: bit 2 query error, 3 device-dependent, 4 execution, 5 command error (Table 4-6, p. 4-12).
        A new command line sent before a pending query was read is a query error (p. 4-12), so every query is read before the next command.
    Reset: *RST "performs power-up reset" (Table 4-8, p. 4-16). Power-up configuration (Table 3-9, p. 3-25): DC volts, autorange, slow rate, trigger 1.
    Measurement: MEAS1? returns the primary display after the next triggered measurement (Table 4-12, p. 4-23); FORMAT 1 gives base units in E notation,
        overload is +/-1.0E+9.

Writes are sent once and never retried (a write's effect is unknown after a failure). Each configuration write is read back and compared where the
meter has a query for it; the exceptions (WIRE2 / WIRE4, REMS) have no query and are flagged. The adjustment (*TER) interface is deliberately absent.
"""
from __future__ import annotations

import math
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import SerialSettings

UM = 'Fluke 8808A Users Manual'

# function -> (mnemonic sent, range table). Range numbers are those of Table 4-11A (p. 4-22); ranges in base units.
FUNC = {'DCV': 'VDC', 'ACV': 'VAC', 'DCI': 'ADC', 'ACI': 'AAC', 'OHM2': 'OHMS', 'OHM4': 'OHMS', 'FREQ': 'FREQ'}
RANGES = {
    'DCV': (0.2, 2.0, 20.0, 200.0, 1000.0),
    'ACV': (0.2, 2.0, 20.0, 200.0, 750.0),
    'OHM2': (200.0, 2e3, 20e3, 200e3, 2e6, 20e6, 100e6),
    'OHM4': (200.0, 2e3, 20e3, 200e3, 2e6, 20e6, 100e6),
    'DCI': (200e-6, 2000e-6, 20e-3, 200e-3, 2.0, 10.0),
    'ACI': (20e-3, 200e-3, 2.0, 10.0),
    'FREQ': (2e3, 20e3, 200e3, 1000e3),
}
OVERLOAD = 1.0e9            # Format 1 overload reading, +/-1.0E+9 (Table 4-12 note, p. 4-23)
ESR_ERRORS = 0x3C           # query, device-dependent, execution, command error bits of *ESR?
ESR_NAMES = {0x04: 'query error', 0x08: 'device-dependent error', 0x10: 'execution error', 0x20: 'command error'}


def range_number(kind: str, range_value: float) -> int:
    """The 1-based range number (Table 4-11A) of a range value in base units."""
    table = RANGES.get(kind)
    if table is None:
        raise InstrumentError(f'Fluke 8808A driver does not support {kind}')
    for n, value in enumerate(table, start=1):
        if math.isclose(value, float(range_value), rel_tol=1e-9):
            return n
    raise InstrumentError(f'The 8808A has no {range_value:g} range for {kind} (Table 4-11A, p. 4-22)')


def _fn(mnemonic, name, page, verified=True, readback='func.query', description=''):
    return Cmd(mnemonic, name, description or f'Select {name.lower()}', kind='set', readback=readback, verified=verified, ref=f'{UM}, Table 4-9, {page}')


COMMANDS = {
    # ---- remote / local (Table 4-17, p. 4-26): there is no query for the remote state ---------------------------------------------------------
    'sys.rem': Cmd('REMS', 'Remote mode', 'Remote, front panel keys still usable (local key returns to local). No query exists for the state',
                   kind='set', verified=True, ref=f'{UM}, Table 4-17, p. 4-26'),
    'sys.loc': Cmd('LOCS', 'Local mode', 'Return to front-panel control', kind='set', verified=True, ref=f'{UM}, Table 4-17, p. 4-26'),
    # ---- function (Table 4-9, pp. 4-17 and 4-18) ---------------------------------------------------------------------------------------------
    'func.vdc': _fn('VDC', 'DC volts', 'p. 4-17'), 'func.vac': _fn('VAC', 'AC volts', 'p. 4-17'),
    'func.adc': _fn('ADC', 'DC current', 'p. 4-17'), 'func.aac': _fn('AAC', 'AC current', 'p. 4-17'),
    'func.ohms': _fn('OHMS', 'Resistance', 'p. 4-17'), 'func.freq': _fn('FREQ', 'Frequency', 'p. 4-17'),
    'func.query': Cmd('FUNC1?', 'Primary function', 'Mnemonic of the primary-display function. The exact reply text is not shown in the manual: compared as text',
                      kind='query', verified=False, ref=f'{UM}, Table 4-9, p. 4-18'),
    'wire.2': Cmd('WIRE2', '2-wire ohms', 'Ohms function only. There is no query: the operator confirms the 2W annunciator',
                  kind='set', verified=True, ref=f'{UM}, Table 4-9, p. 4-18'),
    'wire.4': Cmd('WIRE4', '4-wire ohms', 'Ohms function only. There is no query: the operator confirms the 4W annunciator',
                  kind='set', verified=True, ref=f'{UM}, Table 4-9, p. 4-18'),
    # ---- range and rate (Table 4-11 and 4-11A, pp. 4-21 and 4-22) ----------------------------------------------------------------------------
    'range.fixed': Cmd('FIXED', 'Fixed range', 'Turn autorange off, keeping the present range', kind='set', readback='auto.query', verified=True,
                       ref=f'{UM}, Table 4-11, p. 4-21'),
    'range.set': Cmd('RANGE {range:d}', 'Select range', 'Range NUMBER of Table 4-11A (not a value); fixes the range',
                     placeholders={'range': Placeholder('int', 'd', 1)}, kind='set', readback='range.query', verified=True,
                     ref=f'{UM}, Table 4-11, p. 4-21 and Table 4-11A, p. 4-22'),
    'auto.query': Cmd('AUTO?', 'Autorange state', '1 = autorange on, 0 = fixed range', kind='query', verified=True, ref=f'{UM}, Table 4-11, p. 4-21'),
    'range.query': Cmd('RANGE1?', 'Primary range', 'Range number of the primary display', kind='query', verified=True, ref=f'{UM}, Table 4-11, p. 4-21'),
    'rate.set': Cmd('RATE {rate}', 'Reading rate', 'S slow (5-1/2 digits, the rate the specifications are given in), M medium, F fast',
                    placeholders={'rate': Placeholder('enum', '', 'S', enum=('S', 'M', 'F'))}, kind='set', readback='rate.query', verified=True,
                    ref=f'{UM}, Table 4-11, p. 4-21'),
    'rate.query': Cmd('RATE?', 'Reading rate', 'S, M or F', kind='query', verified=True, ref=f'{UM}, Table 4-11, p. 4-21'),
    # ---- measurement (Table 4-12, p. 4-23) and trigger (Table 4-14, p. 4-24) ----------------------------------------------------------------
    'meas1': Cmd('MEAS1?', 'Take a reading', 'Primary display value after the next triggered measurement. That a reading taken straight after '
                 'a range change is fresh is not stated in the manual: the first is discarded', kind='query', verified=True,
                 ref=f'{UM}, Table 4-12, p. 4-23'),
    'trigger.set': Cmd('TRIGGER {mode:d}', 'Trigger mode', '1 = internal trigger (the power-up trigger)', placeholders={'mode': Placeholder('int', 'd', 1)},
                       kind='set', readback='trigger.query', verified=True, ref=f'{UM}, Table 4-14, p. 4-24'),
    'trigger.query': Cmd('TRIGGER?', 'Trigger mode', 'Present trigger mode', kind='query', verified=True, ref=f'{UM}, Table 4-14, p. 4-24'),
    # ---- misc (Table 4-15, p. 4-25) -------------------------------------------------------------------------------------------------------
    'format.set': Cmd('FORMAT {fmt:d}', 'Reply format', '1 = base units in E notation. The power-up format is not listed in Table 3-9, so it is set explicitly',
                      placeholders={'fmt': Placeholder('int', 'd', 1)}, kind='set', readback='format.query', verified=True, ref=f'{UM}, Table 4-15, p. 4-25'),
    'format.query': Cmd('FORMAT?', 'Reply format', 'Present format', kind='query', verified=True, ref=f'{UM}, Table 4-15, p. 4-25'),
    'serial.query': Cmd('SERIAL?', 'Serial number', 'Serial number of the meter', kind='query', verified=True, ref=f'{UM}, Table 4-15, p. 4-25'),
    # ---- common commands (Table 4-8, pp. 4-16 and 4-17) --------------------------------------------------------------------------------------
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers (never overridable)', kind='set', risk='locked', verified=True,
                        ref=f'{UM}, Table 4-8, p. 4-16'),
    'err.query': Cmd('*ESR?', 'Standard event status', 'There is no error queue: the error bits of the event status register (mask 0x3C). Reading CLEARS '
                     'it, so it is never retried (never overridable)', kind='query', risk='locked', verified=True, ref=f'{UM}, Table 4-8, p. 4-16 and Table 4-6, p. 4-12'),
    'stb.query': Cmd('*STB?', 'Status byte', 'Status byte (not used by the verification)', kind='query', verified=True, ref=f'{UM}, Table 4-8, p. 4-17'),
}
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{UM}, Table 4-8, p. 4-16 (*RST "performs power-up reset")',
                                     note='Whether the reset also leaves remote mode is not stated in the manual: REMS is sent again afterwards')
COMMANDS['opc.query'] = cmdreg.opc_cmd(True, f'{UM}, Table 4-8, p. 4-16')


class Fluke8808A(Instrument):
    MODEL = 'Fluke 8808A'
    IDN_MATCH = ('8808A',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 20.0
    RESET_OPC_TIMEOUT = 30.0
    # Users Manual Table 4-1, p. 4-4: 9600 baud, 8 data bits, no parity, 1 stop bit, echo off. Replies end CR LF; commands may end CR, LF or CR LF.
    SERIAL = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1, write_termination='\n', read_termination='\r\n')
    SUPPORTED = tuple(FUNC)
    # With echo off the meter returns no prompt, so the controller cannot see that a command is finished (p. 4-6 / 4-8 say to wait for the prompt).
    # The gap is a choice of this driver; it is NOT a figure from the manual.
    COMMAND_GAP_S = 0.15
    RESET_SETTLE_S = 3.0         # after *RST (a power-up reset); also a choice of this driver, not a manual figure
    PROMPTS = ('=>', '?>', '!>')
    PROMPT_KIND = {'=>': 'ready', '?>': 'command-error', '!>': 'execution-error'}
    MAX_REPLY_LINES = 5          # lines read while waiting for ONE reply (prompts / echo skipped); a bound, not a manual figure
    PROMPT_WARNING = ('prompts returned: Echo appears to be ON or was restored by *RST - turn Echo off at the front panel '
                      '(Users Manual Table 4-1, p. 4-4)')
    prompts_seen = 0             # prompt lines skipped / raised since this driver object was made
    echo_seen = 0                # echoed command lines skipped
    _since = None                # commands sent since the last reply was read (a prompt that arrives before a reply belongs to one of them)
    _prompt_logged = False

    # ---- wire access: pacing, prompt-tolerant replies ----------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        super().write(cmd, log_as)
        self._since = (self._since or [])[-19:] + [cmd.strip()]

    def query(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        return self._query_lines(cmd, log_as, echo_ok=True)

    def _note_prompts(self):
        if not self._prompt_logged:
            self._prompt_logged = True
            self.log.add('!!', self.PROMPT_WARNING, self.label)

    def _prompt_warning(self) -> str:
        """The warning text for the reset report / summary, or '' when no prompt or echoed line was ever seen."""
        if not (self.prompts_seen or self.echo_seen):
            return ''
        return f'{self.PROMPT_WARNING} ({self.prompts_seen} prompt line(s) and {self.echo_seen} echoed command line(s) skipped)'

    def _query_lines(self, cmd, log_as, echo_ok):
        """Send a query once and read its reply. The FIRST read is the transport's own query (so a timeout gives the same error as before).
        A reply line that is only a prompt is not the reply: a prompt FOLLOWS the command it answers (p. 4-6), so one that arrives before this
        query's reply belongs to an EARLIER command. '=>' (no error) is dropped; '?>' / '!>' is raised as that command's failure, never skipped.
        An echoed copy of the command (Echo on) is skipped unless echo_ok is False. At most MAX_REPLY_LINES lines are read; every raw line read is
        logged, a skipped one is marked. Read-only: nothing is ever written here."""
        earlier = list(self._since or [])
        self.log.add('>>', log_as or cmd, self.label)
        line = self.t.query(cmd)
        limit = self.MAX_REPLY_LINES + 2 * len(earlier)          # a command that was sent before may have left its echo and its prompt in front of the reply
        for n in range(limit):
            text = line.strip()
            if text in self.PROMPTS:
                self.prompts_seen += 1
                if text != '=>':
                    self.log.add('<<', f'{text}  [prompt: {self.PROMPT_KIND[text]}, raised as an error]', self.label)
                    self._note_prompts()
                    self._discard_input('after an error prompt')       # the rest of that exchange must not be paired with a later command
                    raise InstrumentError(self._prompt_error(text, cmd, earlier))
                self.log.add('<<', f'{text}  [prompt, skipped]', self.label)
                self._note_prompts()
            elif self._is_echo(text, cmd, earlier):
                self.echo_seen += 1
                if not echo_ok:
                    self.log.add('<<', f'{text}  [echo of the command, refused]', self.label)
                    self._note_prompts()
                    raise InstrumentError(self._echo_error(cmd))
                self.log.add('<<', f'{text}  [echo of the command, skipped]', self.label)
                self._note_prompts()
            else:
                self.log.add('<<', text, self.label)
                self._since = [cmd.strip()]          # its own prompt may still follow the reply
                return line
            if n + 1 < limit:
                line = self.t.read()                  # a timeout here raises the transport's own error
        self._since = [cmd.strip()]
        raise InstrumentError(f'{self.MODEL}: no reply to {cmd!r} within {limit} lines (only prompts / echoed text were read)')

    def _is_echo(self, text, cmd, earlier) -> bool:
        """Is this line the echoed text of a command (Echo on)? Always for this query's own text. For an EARLIER command's text (its echo is read in
        front of the next reply) only when that text cannot be a reply: it holds a '*', a space, a digit or a '?'. A bare mnemonic (VDC, FIXED, REMS)
        could be the reply of FUNC1?, so it counts as an echo only once an echoed query has been seen (echo_seen > 0). A heuristic, not a manual fact."""
        up = text.upper()
        if not up:
            return False
        if up == cmd.strip().upper():
            return True
        for c in earlier:
            if up == c.upper() and (self.echo_seen > 0 or not up.isalpha()):
                return True
        return False

    def _prompt_error(self, prompt, cmd, earlier):
        what = {'?>': 'a command error (the command was not understood)', '!>': 'an execution or device-dependent error (the command was understood but not executed)'}[prompt]
        prev = earlier[-1] if earlier else None
        since = f' (recent commands, oldest first: {", ".join(repr(c) for c in earlier)})' if len(earlier) > 1 else ''
        owner = (f'A prompt follows the command it answers, so it belongs to the command sent before this query: {prev!r}{since}.' if prev else
                 'A prompt follows the command it answers; no earlier command is on record since the last input flush, so it may be an earlier command or this query itself.')
        return f'{self.MODEL}: the meter returned the prompt {prompt!r} = {what} while {cmd!r} was waiting for its reply. {owner} Read *ESR? for the error bit.'

    def _echo_error(self, cmd):
        return (f'{self.MODEL}: the meter echoed the command text {cmd.strip()!r} instead of replying: Echo is ON. Turn Echo off in the front-panel '
                'serial settings (Users Manual Table 4-1, p. 4-4; factory setting: off) and connect again.')

    def _discard_input(self, why):
        """Throw away whatever the meter has sent that nobody asked for (stray prompts, a banner). Read-only on the instrument."""
        self.t.clear()
        self._since = []
        self.log.add('--', f'input buffer cleared {why}: stray prompts / banner lines are not read as replies', self.label)

    def send(self, key, **vals):
        super().send(key, **vals)
        if key == 'reset':
            time.sleep(self.RESET_SETTLE_S)
            self._discard_input('after the *RST settle')

    def reset_to_defaults(self):
        rep = super().reset_to_defaults()
        warn = self._prompt_warning()
        if warn and not rep.exempt:
            rep.warnings.append(warn)
            self.log.add('!!', warn, self.label)
        return rep

    def identify(self):
        time.sleep(self.COMMAND_GAP_S)
        reply = self._query_lines('*IDN?', None, echo_ok=False).strip()
        if reply.upper().startswith('*IDN?'):                 # command text run into the reply (Echo on, no line end after the echo)
            raise InstrumentError(self._echo_error('*IDN?'))
        if any(p in reply for p in self.PROMPTS):             # a prompt on the SAME line as the reply: the framing is not understood
            raise InstrumentError('The 8808A is replying with prompts: Echo is ON. Turn Echo off in the front-panel serial settings '
                                  '(Users Manual Table 4-1, p. 4-4; factory setting: off) and connect again.')
        return reply

    # ---- connection ---------------------------------------------------------------------------------------------------------------------------
    def connect(self):
        """Open, flush, confirm the model (and that echo is off), enter remote and clear the status registers."""
        self.open(verify_model=False)
        try:
            self.t.clear()
            self.idn = self.identify()
            if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
                raise InstrumentError(f'Unexpected DMM identification: {self.idn}')
            self.remote()
            self.send('status.clear')
        except Exception:
            self.close()
            raise
        return self

    def remote(self):
        self.send('sys.rem')            # no query exists for the remote state: it cannot be read back (flagged)

    def local(self):
        self.send('sys.loc')

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    # ---- set, read back, compare (never retry a write) -----------------------------------------------------------------------------------------
    @staticmethod
    def _int(reply):
        try:
            return int(float(str(reply).strip().strip('=>?! ').split(',')[0]))
        except ValueError:
            return None

    def _set_check(self, key, query_key, expected, what, **vals):
        """Send a set command once, read the paired query back and compare. expected: text (upper-cased compare) or int."""
        self.send(key, **vals)
        reply = self.ask(query_key).strip()
        got = self._int(reply) if isinstance(expected, int) else reply.upper()
        if got != (expected if isinstance(expected, int) else str(expected).upper()):
            sent = cmdreg.render(self._registry()[key], vals)
            raise InstrumentError(f'{self.MODEL}: {what} was not accepted: sent {sent!r}, read back {reply!r}, expected {expected!r}')
        return reply

    def _reset_extra(self):
        """After *RST: remote again, then the settings the readings depend on, each set once and read back."""
        return [('re-enter remote (REMS)', self.remote),
                ('reply format 1 (FORMAT 1, read back)', lambda: self._set_check('format.set', 'format.query', 1, 'FORMAT 1', fmt=1)),
                ('internal trigger (TRIGGER 1, read back)', lambda: self._set_check('trigger.set', 'trigger.query', 1, 'TRIGGER 1', mode=1)),
                ('slow rate (RATE S, read back)', lambda: self._set_check('rate.set', 'rate.query', 'S', 'RATE S', rate='S')),
                ('event status after the reset', lambda: self.check_errors('the reset') or 'no error bits')]

    def _reset_drain(self, rep, limit=10):
        """The 8808A has no error queue: *ESR? is read ONCE (it clears itself, so it is not retried). Power-on (bit 7) and operation-complete (bit 0) are normal
        after a reset; error bits are reported as warnings, like leftover error-queue entries on the other drivers."""
        bits = self._int(self.ask('err.query'))
        if bits is None:
            raise InstrumentError('*ESR? did not return a number')
        flags = [name for bit, name in ESR_NAMES.items() if bits & bit]
        for f in flags:
            rep.warnings.append(f'event status after reset: {f}')
            self.log.add('!!', f'event status after reset: {f}', self.label)
        return f'*ESR? = {bits}' + (f' ({", ".join(flags)})' if flags else '')

    # ---- verification setup --------------------------------------------------------------------------------------------------------------------
    def configure_point(self, point: dict):
        """Function, wire mode (ohms), fixed range, slow rate; each set once and read back where the meter has a query."""
        kind = point['kind']
        if kind not in FUNC:
            raise InstrumentError(f'{self.MODEL} driver does not support {kind}')
        fn = FUNC[kind]
        number = range_number(kind, point['range'])
        self._set_check('func.' + fn.lower(), 'func.query', fn, f'function {fn}')
        if kind == 'OHM4':
            self.send('wire.4')
        elif kind == 'OHM2':
            self.send('wire.2')
        self.send('range.fixed')
        auto = self._int(self.ask('auto.query'))
        if auto != 0:
            raise InstrumentError(f'{self.MODEL}: FIXED was not accepted: AUTO? answered {auto!r}, expected 0')
        self._set_check('range.set', 'range.query', number, f'range {number}', range=number)
        if kind != 'FREQ':          # the frequency reading rate is fixed (Table 4-11, p. 4-21)
            self._set_check('rate.set', 'rate.query', 'S', 'RATE S', rate='S')
        for key, want, what in (('format.query', 1, 'FORMAT'), ('trigger.query', 1, 'TRIGGER')):
            got = self._int(self.ask(key))
            if got != want:
                raise InstrumentError(f'{self.MODEL}: {what} reads back {got!r}, expected {want}')
        self.ask('opc.query')       # *OPC?: the meter has finished the commands above (there is no prompt with echo off)

    def read(self) -> float:
        """MEAS1? twice (the first is discarded: the manual does not say a reading after a range change is fresh); rejects overload."""
        self.ask('meas1')
        raw = self.ask('meas1').strip().split(',')[0].strip().strip('=>?! ')
        try:
            value = float(raw)
        except ValueError:
            raise InstrumentError(f'{self.MODEL}: unreadable reading {raw!r}') from None
        if not math.isfinite(value) or abs(value) >= OVERLOAD:
            raise InstrumentError(f'{self.MODEL}: overload reading {raw} (input not connected, wrong range or wrong function)')
        return value

    def check_errors(self, context: str = ''):
        """Read *ESR? once (never retried: it clears itself) and raise when an error bit is set. Returns None."""
        bits = self._int(self.ask('err.query'))
        if bits is None:
            raise InstrumentError(f'{self.MODEL}: *ESR? did not return a number{" after " + context if context else ""}')
        found = [name for bit, name in ESR_NAMES.items() if bits & bit]
        if found:
            raise InstrumentError(f'{self.MODEL} reported {" and ".join(found)}{" after " + context if context else ""} (*ESR? = {bits})')
