"""B&K Precision 5491B 5-1/2 digit bench multimeter, RS-232 (and the USB virtual COM port, which behaves like the same serial port).

Every command below is taken from the 2831E / 5491B User Manual (Chapter 5 "Remote Operation" and Chapter 6 "SCPI Command Reference", printed pp. 41 to 64).
Facts the manual does not give are NOT guessed: they are marked verified=False in COMMANDS and listed in the procedure's summary. The main ones:
    * the TEXT of every query reply except the reading format and the error text (FUNC?, RANG?, NPLC?, AUTO?, TRIG:SOUR?, *IDN?),
    * how an overload is reported by FETCh?,
    * whether the continuity function can be read over the bus and what it returns,
    * which of LF / CR the meter wants as the end of a command (menu "TX TERM", Section 4.5.3; the factory setting is not printed),
    * what the meter does with a command that arrives while it is busy (Section 5.2.4 item 3 says the characters are IGNORED and must be sent again).

Interface (Sections 5.1 and 5.2): serial, 8 data bits, 1 stop bit, no parity; baud 600 to 38.4k, factory 9600 (menu "BAUD RAT"); the 5491B has RS-232 and USB (virtual COM).
    Software protocol (Section 5.2.4): every received character is sent back to the controller as a handshake, and a query answers immediately with its reply
    (terminated with the TX TERM character, LF or CR). The menu "RETURN" additionally echoes the command text in the return string (Section 2.4 / 4.5).
    Echo is therefore part of the protocol: this driver is echo-tolerant (read-only, bounded, logged as skipped), and every setting is READ BACK and compared, so a command
    that was lost while the meter was busy (item 3 of Section 5.2.4) shows up as a refused read-back, never as a silent wrong setup.
Errors (Section 6.3.9): `SYSTem:ERRor?` returns "NO ERROR!" or a message such as "BUS:BAD COMMAND." There is no status register.
Reset: `*RST` ("Reset the instrument", Section 6.3.10). There is no *CLS, *OPC? or *ESR? (the manual lists only *RST, *TRG and *IDN?).
Measurement: `FETCh?` returns the last available reading (it does not trigger one); with the default IMMediate trigger the meter measures continuously, so two FETCh? calls are
    made one reading apart and the second one is used. Reading format "SD.DDDDDDESDDD" (Section 5.3).

Writes are sent once and never retried (a write's effect is unknown after a failure). Each configuration write is read back and compared. The adjustment ("ZERO CAL", front panel
only) is deliberately absent.
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import SerialSettings, TransportError

UM = '2831E / 5491B User Manual'

# kind -> SCPI function name as the manual writes it (Section 6.3.2, Table 6-2 and the example "FUNC VOLT:DC" of Section 6.2.3)
FUNC = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'CONT': 'CONT', 'FREQ': 'FREQ'}
# subsystem path of the range / NPLC commands (Tables 6-3 to 6-5)
PATH = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES'}
# 5491B ranges in base units (User Manual Chapter 7, 5491B specifications, printed pp. 68 to 71; read from the rendered pages)
RANGES = {
    'DCV': (0.5, 5.0, 50.0, 500.0, 1000.0),
    'ACV': (0.5, 5.0, 50.0, 500.0, 750.0),
    'DCI': (5e-3, 50e-3, 500e-3, 5.0, 20.0),
    'ACI': (5e-3, 50e-3, 500e-3, 5.0, 20.0),
    'OHM2': (500.0, 5e3, 50e3, 500e3, 5e6, 50e6),
    'CONT': (500.0,),
    'FREQ': (10.0, 100.0, 100e3, 1000e3),          # frequency ranges (Section 7, p. 71): the range is set by the signal, not by a command
}
NPLC_SLOW = 10                  # "Slow = 10" power line cycles (Tables 6-3 to 6-5 footnote); the specifications are for the slow rate (Chapter 7)
OVERLOAD = 9.0e37               # a reading at or above this is taken as an overload (the real overload text is not in the manual: UNVERIFIED)
NO_ERROR = 'NO ERROR'


def range_text(value: float) -> str:
    """A range as the meter takes it: plain decimal digits, no exponent and no trailing .0 (owner probe, 2026-10-28: 5.0 and +5E+00 were refused, 5 and 0.5 accepted)."""
    from decimal import Decimal
    return format(Decimal(repr(float(value))).normalize(), 'f')


def range_value(kind: str, range_v: float) -> float:
    """The 5491B range (base units) a spec range value stands for; raises when the meter has no such range."""
    table = RANGES.get(kind)
    if table is None:
        raise InstrumentError(f'B&K 5491B driver does not support {kind}')
    for value in table:
        if math.isclose(value, float(range_v), rel_tol=1e-9):
            return value
    raise InstrumentError(f'The 5491B has no {range_v:g} range for {kind} (User Manual Chapter 7, pp. 68 to 71)')


def _num(text):
    """First number in a reply (None if there is none): tolerates a unit or quotes around it. Read-only helper."""
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(text))
    return float(m.group(0)) if m else None


def _tokens(text):
    """'VOLTage:DC' / '"VOLT:DC"' / 'volt:dc' -> ['VOL', 'DC'] (the first three letters of each word: short and long forms agree)."""
    words = re.findall(r'[A-Za-z]+', str(text))
    return [w[:3].upper() for w in words]


def _fmt_value(value):
    return f'{float(value):.9g}'


COMMANDS = {
    # ---- reset (Section 6.3.10, p. 64) ------------------------------------------------------------------------------------------------------------
    'func.set': Cmd('FUNC {fn}', 'Measurement function', 'Select the function. The manual writes the names VOLTage:DC, VOLTage:AC, CURRent:DC, CURRent:AC, RESistance, FREQuency, CONTinuity '
                    '(short forms VOLT:DC ... are used; Section 6.2.2 rules and the example of Section 6.2.3)',
                    placeholders={'fn': Placeholder('enum', '', 'VOLT:DC', enum=tuple(FUNC.values()))}, kind='set', readback='func.query', verified=True,
                    ref=f'{UM}, Section 6.3.2, Table 6-2, p. 48 and Section 6.2.3, p. 45'),
    'func.query': Cmd('FUNC?', 'Measurement function', 'Query the function. The text of the reply (long form, short form, quotes) is not shown in the manual: compared by the first three letters '
                      'of each word', kind='query', verified=False, ref=f'{UM}, Section 6.3.2, Table 6-2, p. 48'),
    # ---- trigger (Section 6.3.7, Table 6-8, p. 63) ----------------------------------------------------------------------------------------------------
    'trig.set': Cmd('TRIG:SOUR {src}', 'Trigger source', 'IMMediate = the internal trigger (the power-on default)',
                    placeholders={'src': Placeholder('enum', '', 'IMM', enum=('IMM', 'BUS', 'MAN'))}, kind='set', readback='trig.query', verified=True,
                    ref=f'{UM}, Section 6.3.7, Table 6-8, p. 63'),
    'trig.query': Cmd('TRIG:SOUR?', 'Trigger source', 'Query the trigger source. The reply text is not shown in the manual: compared by its first three letters',
                      kind='query', verified=False, ref=f'{UM}, Section 6.3.7, Table 6-8, p. 63'),
    # ---- measurement (Section 6.3.8, p. 63) -----------------------------------------------------------------------------------------------------------
    'fetch': Cmd('FETC?', 'Last reading', 'Returns the last available reading; it does NOT trigger one (it keeps returning the same value until there is a new reading)',
                 kind='query', verified=True, ref=f'{UM}, Section 6.3.8, p. 63; reading format Section 5.3, p. 42'),
    # ---- errors (Section 6.3.9, p. 64) ----------------------------------------------------------------------------------------------------------------
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Reads one entry of the error queue: "NO ERROR!" or a message such as "BUS:BAD COMMAND." Reading REMOVES the entry, so it is never retried '
                     '(never overridable)', kind='query', risk='locked', verified=True, ref=f'{UM}, Section 6.3.9, p. 64'),
}
for _k, _p in PATH.items():
    _name = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM2': 'resistance'}[_k]
    _pg = {'DCV': 'Table 6-3, p. 49', 'ACV': 'Table 6-3, p. 49', 'DCI': 'Table 6-4, p. 53', 'ACI': 'Table 6-4, p. 53', 'OHM2': 'Table 6-5, p. 57'}[_k]
    COMMANDS[f'range.auto.{_k}'] = Cmd(f'{_p}:RANG:AUTO {{state}}', f'Autorange, {_name}', 'OFF holds the present range. Coupled to RANG <n>: a valid RANG <n> also switches autorange off',
                                       placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback=f'range.auto.query.{_k}', verified=True,
                                       ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}')
    COMMANDS[f'range.auto.query.{_k}'] = Cmd(f'{_p}:RANG:AUTO?', f'Autorange, {_name}', 'Autorange state (0 = off, 1 = on, Section 6.3.3). A reply "ON" / "OFF" is accepted too',
                                             kind='query', verified=True, ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}')
    COMMANDS[f'range.set.{_k}'] = Cmd(f'{_p}:RANG {{range}}', f'Range, {_name}', 'The EXACT range value in base units, written as the meter lists it (0.5, 5, 50 ...). A value that is not one of the ranges, '
                                      'or one written 5.0 / 5E+00, is refused with BUS:ERROR PARAMETER / BAD COMMAND (owner probe, 2026-10-28: 0.49, 4.9, 2 and 0.2 refused; 0.5, 5, 50, 1000 accepted)',
                                      placeholders={'range': Placeholder('enum', '', None, enum=tuple(range_text(v) for v in RANGES[_k]))}, kind='set', readback=f'range.query.{_k}', verified=True,
                                      ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}; owner probe 2026-10-28')
    COMMANDS[f'range.query.{_k}'] = Cmd(f'{_p}:RANG?', f'Range, {_name}', 'Query the range. The reply text is not shown in the manual: the first number in it is compared with the range '
                                        'full scale, tolerance 1 %', kind='query', verified=False, ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}')
    COMMANDS[f'nplc.set.{_k}'] = Cmd(f'{_p}:NPLC {{nplc}}', f'Integration time, {_name}', 'Power line cycles 0.1 (fast), 1 (medium), 10 (slow). The specifications are for the slow rate',
                                     placeholders={'nplc': Placeholder('float', 'g', 10.0)}, kind='set', readback=f'nplc.query.{_k}', verified=True,
                                     ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}')
    COMMANDS[f'nplc.query.{_k}'] = Cmd(f'{_p}:NPLC?', f'Integration time, {_name}', 'Query the NPLC (a number)', kind='query', verified=True,
                                       ref=f'{UM}, Section 6.3.3 to 6.3.5, {_pg}')
COMMANDS['thr.set'] = Cmd('FREQ:THR:VOLT:RANG {volts}', 'Frequency threshold range', 'The expected signal level in volts: the meter selects the threshold range (Section 6.3.6, Table 6-6)',
                          placeholders={'volts': Placeholder('float', '.9g', 0.5)}, kind='set', readback='thr.query', verified=True, ref=f'{UM}, Section 6.3.6, Table 6-6 and p. 61')
COMMANDS['thr.query'] = Cmd('FREQ:THR:VOLT:RANG?', 'Frequency threshold range', 'Query the maximum signal level. The reply text is not shown in the manual: the first number is compared '
                            'with the requested level (the meter may report the range it chose instead: UNVERIFIED)', kind='query', verified=False, ref=f'{UM}, Section 6.3.6, p. 61')
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{UM}, Section 6.3.10, p. 64 (*RST "Reset the instrument")',
                                     note='What *RST leaves (function, range, rate) is not listed for the bus: every setting is sent again afterwards')


class BK5491B(Instrument):
    MODEL = 'B&K 5491B'
    IDN_MATCH = ('5491B',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 20.0
    # Section 5.2.2: 8 data bits, 1 stop bit, no parity; Section 5.2.3: factory 9600 baud. The terminator is the menu "TX TERM" (LF or CR): LF is assumed (UNVERIFIED).
    SERIAL = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1, write_termination='\n', read_termination='\n')
    SUPPORTED = tuple(FUNC)
    # The gap between commands is a choice of this driver, NOT a manual figure: Section 5.2.4 items 3 and 7 say a busy meter ignores characters, and gives no time.
    COMMAND_GAP_S = 0.2
    RESET_NO_OPC = 'The 5491B has no *OPC? (Section 6.3): after *RST the driver waits RESET_SETTLE_S and drains the port instead.'
    RESET_SETTLE_S = 5.0         # after *RST ("the controller should keep waiting", Section 5.2.4 item 7): a choice of this driver, not a manual figure
    READ_GAP_S = 0.6             # between the two FETCh? of a reading: more than one reading period (5 readings per second, slow rate, Chapter 7); a choice, not a manual figure
    READ_GAP_SLOW_S = 2.0        # frequency / period (1 reading per second) and the 50 Mohm range (1.3 per second): Chapter 7 reading rates
    MAX_REPLY_LINES = 6          # lines read while waiting for ONE reply (echoes skipped): a bound, not a manual figure
    echo_seen = 0                # echoed command lines (or command text in front of a reply) skipped since this driver object was made
    _since = None

    # ---- wire access: pacing, echo-tolerant replies -------------------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        self.log.add('>>', log_as or cmd, self.label)
        self._send_text(cmd)
        self._since = (self._since or [])[-19:] + [cmd.strip()]

    def query(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        return self._query_lines(cmd, log_as)

    @staticmethod
    def _is_echo(text, cmd, earlier) -> bool:
        up = text.strip().upper()
        if not up:
            return False
        c = cmd.strip().upper()
        # a whole echoed command, or a left-over piece of one (real meter: a lone '?' line came after the echo of '*IDN?'); a reply is never a piece of its own command
        return up == c or any(up == e.upper() for e in earlier) or (len(up) <= len(c) and up in c)

    def _query_lines(self, cmd, log_as):
        """Send a query once and read its reply. The meter echoes every received character (Section 5.2.4 item 3) and, with the menu RETURN on, the command text on its own
        line: a line equal to this query or to a command sent before it is skipped (counted, logged), and command text run into the front of the reply is cut off. At most
        MAX_REPLY_LINES lines are read. Read-only: nothing is ever written here."""
        earlier = list(self._since or [])
        self.log.add('>>', log_as or cmd, self.label)
        self._send_text(cmd)
        seen = []                                                # every line read for this query (shown in the error when the reply never comes)
        try:
            line = self._read_line()
        except TransportError as exc:
            raise InstrumentError(f'{self.MODEL}: no reply to {cmd!r}: {exc}. Lines received before the silence: {seen or "none"}') from exc
        limit = self.MAX_REPLY_LINES + len(earlier)
        for n in range(limit):
            text = line.strip()
            seen.append(text)
            if self._is_echo(text, cmd, earlier):
                self.echo_seen += 1
                self.log.add('<<', f'{text}  [echo of a command, skipped]', self.label)
            else:
                for c in [cmd.strip()] + earlier:
                    if c and text.upper().startswith(c.upper()) and len(text) > len(c):
                        self.echo_seen += 1
                        text = text[len(c):].strip()          # the command text ran into the reply (no line end after the echo)
                        break
                self.log.add('<<', text, self.label)
                self._since = [cmd.strip()]
                return text
            if n + 1 < limit:
                try:
                    line = self._read_line()
                except TransportError as exc:
                    raise InstrumentError(f'{self.MODEL}: no reply to {cmd!r}: {exc}. Lines received before the silence: {seen}') from exc
        self._since = [cmd.strip()]
        raise InstrumentError(f'{self.MODEL}: no reply to {cmd!r} within {limit} lines (only echoed command text was read)')

    ECHO_WAIT_S = 1.0            # wait for the echo of ONE character (Section 5.2.4 item 3); a choice of this driver, the manual gives no time
    ECHO_RESENDS = 3             # a character whose echo does not come was not received (item 3): that ONE character is sent again, at most this many times

    def _terminator(self) -> str:
        s = getattr(self.t, 'serial', None) or getattr(self.t, 'settings', None)
        return getattr(s, 'write_termination', '\n') if s is not None else '\n'

    def _send_text(self, cmd: str):
        """Send a command the way Section 5.2.4 item 3 requires: ONE character at a time, the next only after the meter has echoed the last (a busy meter ignores characters,
        and it is busy echoing). The end character is sent last and not waited for. A character whose echo does not come was not received (item 3 says to send it again): only
        that character is repeated, at most ECHO_RESENDS times, then the send fails. Transports with no raw access (the simulator) send the whole line."""
        res, ser = getattr(self.t, '_res', None), getattr(self.t, '_ser', None)
        if res is None and ser is None:
            self.t.write(cmd)
            return
        full = getattr(self.t, 'timeout', 10.0)
        self.t.clear()                                           # the echo of the previous command's end character may still be waiting: it would be read as this command's first echo
        try:
            self._set_short(res, ser, self.ECHO_WAIT_S)
            for ch in cmd.strip():
                for attempt in range(self.ECHO_RESENDS + 1):
                    self._raw_write(res, ser, ch.encode('ascii'))
                    echo = self._raw_read1(res, ser)
                    if echo == ch.encode('ascii'):
                        break
                    self.log.add('--', f'echo of {ch!r} was {echo!r}' + ('; sent again' if attempt < self.ECHO_RESENDS else '; giving up'), self.label)
                    self.echo_seen += 1
                else:
                    raise InstrumentError(f'{self.MODEL}: the meter did not echo {ch!r} of {cmd!r} after {self.ECHO_RESENDS + 1} tries (Section 5.2.4 item 3: check the baud rate and the cable)')
            end = self._terminator().encode('ascii')
            self._raw_write(res, ser, end)
            echo = self._raw_read1(res, ser)                     # the meter echoes the end character too (owner's probe): take it here so it is not read as part of the reply
            if echo and echo != end:
                self.log.add('--', f'echo of the end character was {echo!r}', self.label)
        finally:
            self._set_short(res, ser, full)

    @staticmethod
    def _set_short(res, ser, seconds):
        if res is not None:
            res.timeout = int(seconds * 1000)
        elif ser is not None:
            ser.timeout = seconds

    @staticmethod
    def _raw_write(res, ser, data: bytes):
        if res is not None:
            res.write_raw(data)
        else:
            ser.write(data)
            ser.flush()

    @staticmethod
    def _raw_read1(res, ser):
        """One byte, or b'' after the timeout (no exception for silence)."""
        try:
            return bytes(res.read_bytes(1)) if res is not None else ser.read(1)
        except Exception:
            return b''

    IDLE_END_S = 1.5             # a line whose end character never arrives is taken as complete after this much silence (a choice of this driver, not a manual figure)

    def _read_line(self) -> str:
        """One reply line. Over VISA or pyserial the bytes are read one at a time and a line ends at CR or LF (an empty line, the second half of CR LF, is skipped), so it does not
        matter which end character the meter's echo and reply use. A line that stops without an end character is returned after IDLE_END_S of silence; nothing at all raises the
        transport's timeout error WITH the bytes seen so far. Other transports (the simulator) use their own read. Read-only."""
        res = getattr(self.t, '_res', None)
        ser = getattr(self.t, '_ser', None)
        if res is None and ser is None:
            return self.t.read()
        buf = bytearray()
        full_timeout = getattr(self.t, 'timeout', 10.0)
        try:
            while True:
                try:
                    b = bytes(res.read_bytes(1)) if res is not None else ser.read(1)  # pyright: ignore[reportOptionalMemberAccess]  (ser is set when res is None; checked above)
                except Exception as exc:
                    if buf:                                         # silence after some characters: the line is complete
                        self.log.add('--', f'line taken as complete after {self.IDLE_END_S:g} s of silence: {bytes(buf)!r}', self.label)
                        return bytes(buf).decode('ascii', 'replace')
                    raise TransportError(f'read failed: {exc} (no byte at all in {full_timeout:g} s)') from exc
                if ser is not None and not b:
                    if buf:
                        return bytes(buf).decode('ascii', 'replace')
                    raise TransportError(f'read failed: timeout (no byte at all in {full_timeout:g} s)')
                if b in (b'\r', b'\n'):
                    if buf:
                        return bytes(buf).decode('ascii', 'replace')
                    continue                                        # empty: the other half of CR LF
                buf += b
                if len(buf) == 1:                                   # after the first character the rest follows at once: do not wait the whole timeout for a missing end character
                    self._set_short_timeout(res, ser)
        finally:
            self._set_full_timeout(res, ser, full_timeout)

    def _set_short_timeout(self, res, ser):
        if res is not None:
            res.timeout = int(self.IDLE_END_S * 1000)
        elif ser is not None:
            ser.timeout = self.IDLE_END_S

    @staticmethod
    def _set_full_timeout(res, ser, seconds):
        if res is not None:
            res.timeout = int(seconds * 1000)
        elif ser is not None:
            ser.timeout = seconds

    OPEN_SETTLE_S = 1.0          # after opening the port (a USB virtual COM port can reset the meter's interface when it opens): a choice of this driver, not a manual figure

    def _assert_control_lines(self):
        """Assert DTR and RTS (a USB virtual COM port often stays silent until the host does). Best effort; the result is logged. Not a command to the meter."""
        res, ser = getattr(self.t, '_res', None), getattr(self.t, '_ser', None)
        try:
            if res is not None:
                import pyvisa.constants as c
                for attr in (c.ResourceAttribute.asrl_dtr_state, c.ResourceAttribute.asrl_rts_state):
                    res.set_visa_attribute(attr, c.LineState.asserted)
            elif ser is not None:
                ser.dtr = True
                ser.rts = True
            else:
                return
            self.log.add('--', 'DTR and RTS asserted', self.label)
        except Exception as exc:
            self.log.add('--', f'DTR / RTS could not be set ({exc}); continuing', self.label)

    def _discard_input(self, why):
        """Throw away whatever the meter has sent that nobody asked for (echo of earlier characters). Read-only on the instrument."""
        self.t.clear()
        self._since = []
        self.log.add('--', f'input buffer cleared {why}: left-over echo is not read as a reply', self.label)

    def send(self, key, **vals):
        super().send(key, **vals)
        if key == 'reset':
            time.sleep(self.RESET_SETTLE_S)
            self._discard_input('after the *RST settle')

    def identify(self):
        time.sleep(self.COMMAND_GAP_S)
        reply = self._query_lines('*IDN?', None).strip()
        if not reply:
            raise InstrumentError(f'{self.MODEL}: empty *IDN? reply')
        return reply

    # ---- connection ---------------------------------------------------------------------------------------------------------------------------
    def connect(self):
        """Open, flush and confirm the model. There is no remote command (the serial / USB port is always the remote interface, Section 5.1)."""
        self.open(verify_model=False)
        try:
            self._assert_control_lines()
            time.sleep(self.OPEN_SETTLE_S)
            self.t.clear()
            try:
                self.idn = self.identify()
            except InstrumentError as exc:                       # *IDN? is a read-only query: ONE more try is allowed (the first characters may have gone while the port was still settling)
                self.log.add('!!', f'no reply to the first *IDN? ({exc}); one more try (read-only query)', self.label)
                self.t.clear()
                self._since = []
                self.idn = self.identify()
            if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
                raise InstrumentError(f'Unexpected DMM identification: {self.idn}')
        except Exception:
            self.close()
            raise
        return self

    def cleanup(self):
        """Nothing to send: there is no local command (the front-panel LOCAL key returns control, Section 6.3.1 description)."""

    # ---- set, read back, compare (never retry a write) -----------------------------------------------------------------------------------------
    def _set_check(self, key, query_key, accept, what, **vals):
        """Send a set command once, read the paired query back and compare with `accept(reply) -> bool`."""
        self.send(key, **vals)
        reply = self.ask(query_key).strip()
        if not accept(reply):
            sent = cmdreg.render(self._registry()[key], vals)
            raise InstrumentError(f'{self.MODEL}: {what} was not accepted: sent {sent!r}, read back {reply!r}')
        return reply

    @staticmethod
    def _is_number(want, rel=1e-2):
        def ok(reply):
            got = _num(reply)
            return got is not None and math.isclose(got, want, rel_tol=rel, abs_tol=1e-12)
        return ok

    @staticmethod
    def _is_tokens(want):
        want_t = _tokens(want)

        def ok(reply):
            got = _tokens(reply)
            return got[:len(want_t)] == want_t
        return ok

    def _set_trigger(self):
        return self._set_check('trig.set', 'trig.query', self._is_tokens('IMM'), 'trigger source IMMediate', src='IMM')

    def _reset_drain(self, rep, limit=10):
        """The error queue is read until it says NO ERROR (each read removes an entry, so no retry). Entries found are warnings."""
        found = []
        for _ in range(limit):
            reply = self.ask('err.query').strip()
            if NO_ERROR in reply.upper():
                break
            found.append(reply)
        for f in found:
            rep.warnings.append(f'error queue after reset: {f}')
            self.log.add('!!', f'error queue after reset: {f}', self.label)
        return f'{len(found)} entr{"y" if len(found) == 1 else "ies"} drained' if found else 'queue empty (NO ERROR!)'

    def _reset_extra(self):
        """After *RST: the internal trigger, each set once and read back."""
        return [('internal trigger (TRIG:SOUR IMM, read back)', self._set_trigger)]

    def ensure_run_state(self):
        """A Run that skips the reset (once per session): the trigger source is READ first (read-only); set again, read back and compared only when it is not IMMediate."""
        if self._is_tokens('IMM')(self.ask('trig.query').strip()):
            return 'trigger source already IMMediate'
        self._set_trigger()
        return 'trigger source set again (TRIG:SOUR IMM)'

    def session_check(self):
        """Read-only checks for a Run that skips the reset: the meter still answers *IDN? as a 5491B and the error queue is read ONCE (never retried: reading removes the
        entry). A leftover entry is logged and returned, it does not stop the run: the per-point checks follow."""
        reply = self.identify()
        if self.IDN_MATCH and not any(m.upper() in reply.upper() for m in self.IDN_MATCH):
            raise InstrumentError(f'Unexpected DMM identification: {reply}')
        text = self.ask('err.query').strip()
        flags = [] if NO_ERROR in text.upper() else [text]
        for f in flags:
            self.log.add('!!', f'error queue before the run: {f}', self.label)
        return flags

    # ---- verification setup --------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def function_of(point: dict) -> str:
        """The meter function a point needs: the point's own `function` (continuity is stored as a resistance point with function CONT), else its kind."""
        return point.get('function') or point['kind']

    def configure_point(self, point: dict):
        """Function, fixed range (the exact range value, read back), slow rate; each set once and read back."""
        fk = self.function_of(point)
        if fk not in FUNC:
            raise InstrumentError(f'{self.MODEL} driver does not support {fk}')
        fn = FUNC[fk]
        self._set_check('func.set', 'func.query', self._is_tokens(fn), f'function {fn}', fn=fn)
        if fk in PATH:
            full = range_value(point['kind'], point['range'])
            self.send(f'range.auto.{fk}', state='OFF')
            reply = self.ask(f'range.auto.query.{fk}').strip()
            if reply.upper() not in ('0', 'OFF', '+0') and _num(reply) != 0:
                raise InstrumentError(f'{self.MODEL}: autorange OFF was not accepted: read back {reply!r}')
            self._set_check(f'range.set.{fk}', f'range.query.{fk}', self._is_number(full), f'range {full:g}', range=range_text(full))
            self._set_check(f'nplc.set.{fk}', f'nplc.query.{fk}', self._is_number(NPLC_SLOW, 1e-6), f'NPLC {NPLC_SLOW}', nplc=NPLC_SLOW)
        elif fk == 'FREQ':
            level = float(point.get('amplitude') or 0.5)
            self._set_check('thr.set', 'thr.query', lambda r: _num(r) is not None, f'frequency threshold {level:g} V', volts=level)
        self._set_trigger()

    def read(self, point: dict | None = None) -> float:
        """FETC? twice, one reading period apart; the first is discarded. Rejects an overload or an unreadable reply."""
        slow = point is not None and (self.function_of(point) == 'FREQ' or (point['kind'] == 'OHM2' and point.get('range', 0) >= 5e6))
        self.ask('fetch')
        time.sleep(self.READ_GAP_SLOW_S if slow else self.READ_GAP_S)
        raw = self.ask('fetch').strip()
        value = _num(raw)
        if value is None or not re.fullmatch(r'\s*[-+]?[0-9.]+(?:[eE][-+]?\d+)?\s*[A-Za-z]*\s*', raw):
            raise InstrumentError(f'{self.MODEL}: unreadable reading {raw!r} (an overload or an unexpected format; the overload text is not in the manual)')
        if not math.isfinite(value) or abs(value) >= OVERLOAD:
            raise InstrumentError(f'{self.MODEL}: overload reading {raw} (input not connected, wrong range or wrong function)')
        return value

    def check_errors(self, context: str = ''):
        """Read the error queue once (never retried: reading removes the entry) and raise when it holds an entry."""
        text = self.ask('err.query').strip()
        if NO_ERROR not in text.upper():
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: {text}')
