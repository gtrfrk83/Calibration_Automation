"""HP 5334B universal counter (Option 030 C channel, Option 010 oven time base) over HP-IB, in its own device command language (no SCPI, no *IDN?).

Source: "HP 5334A/B Universal Counters Operating and Programming Manual", part 05334-90047, December 1993 (serial prefix 2937A for the 5334B), read from the RENDERED page
images (owner's copy, 2026-11-03). Printed pages are cited in every Cmd ref. Used by the Fluke 6060A GIDEP procedure for the 10 MHz reference output (FREQ A) and the RF
frequency points of Tables 2 and 3 (FREQ C), on the lab's GPS 10 MHz (rear TIME BASE INT/EXT switch on EXT, a front-panel / rear-panel setting the program cannot set).

Language facts used:
  * Device dependent commands are ASCII, two letters plus a number; upper / lower case alike; spaces, commas and semicolons separate commands (p. 3-78, 3-307). One command per
    write here, so every write is logged on its own.
  * IN initializes: FREQ A, AUTO TRIG on, auto-attenuation on, gate 300 ms, math off (p. 3-80 / 3-81, 3-324 / 3-325). It does NOT clear errors 5.0X to 5.2 or failures.
  * FN1 FREQ A, FN3 FREQ C; GA<num> gate time 0.001 to 99.999 s; WA1 wait-to-be-addressed (one measurement, held until it is read); RE restarts the measurement; TE sends the
    error number; ID sends "HP 5334A/B" (the text printed in 3-323; Example 1 says 'HP 5334A or HP 5334B') (Table 3-12, p. 3-82 / 3-83; 3-80 / 3-81).
  * A reading is 19 characters + CR LF: one alpha character (F = frequency in Hz, O = overflow), spaces, sign, one digit, '.', digits, 'E', sign, two exponent digits
    (p. 3-84 / 3-85). Overflow: 'O+9.99999999999E+99'.
  * Status byte by serial poll (Table 3-11, p. 3-77): 1 data ready, 4 error, 8 failure, 16 local, 32 no oscillator, 64 RQS. In remote, an error or failure is a STATIC state:
    every command except IN, TE and ID is ignored until it is cleared (device clear, IN, RESET/LOCAL), p. 3-87 / 3-88.
  * Factory HP-IB address 03; the 5334B sets it on the rear switch (p. 3-71, 3-284; 3-42, 3-231).
  * Specifications (Table 1-1, pp. 1-2 to 1-6): FREQ A 0.001 Hz to 100 MHz; FREQ C (Option 030) 90 to 1300 MHz, 50 ohm, ac coupled, 15 mV rms to 1000 MHz; LSD = 4 ns / gate
    time x frequency (rounded to the nearest decade); accuracy = resolution + time base error.
NOT printed in the pages read (UNVERIFIED): the text of the TE reply (kept as read), the ID reply of a 5334B (only '5334' is required), how long a reading takes beyond the
gate (READ_MARGIN_S is this driver's choice), and the HP-IB line ends (the VISA defaults are left alone).
"""
from __future__ import annotations

import re
import time
from typing import Any

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .gpib_address import address_of, check_address, retarget, serial_poll
from .transport import TransportError

UM = 'HP 5334A/B Operating and Programming Manual 05334-90047'


def _r(topic, page):
    return f'{UM}: {topic} (p. {page})'


STATUS_BITS = {1: 'data_ready', 4: 'error', 8: 'failure', 16: 'local', 32: 'no_oscillator', 64: 'rqs'}      # Table 3-11 (p. 3-77)
CHANNELS = {'A': 'fn.freq_a', 'C': 'fn.freq_c'}
CHANNEL_RANGE_HZ = {'A': (0.001, 100e6), 'C': (90e6, 1300e6)}                                              # Table 1-1 (pp. 1-2, 1-5, 1-6)
GATE_RANGE_S = (0.001, 99.999)                                                                               # Table 3-12 (p. 3-83)
# Table 3-3 error messages (p. 3-48, read from the rendered page 2026-11-04). Failures (Table 3-4) are hardware faults and are not listed here.
ERROR_TEXT = {
    '0.0': 'no error', '1.0': 'parameter disallowed in present mode', '1.1': 'attenuators controlled by AUTO TRIG', '1.2': '50-ohm B, AC B settings preset by COM A',
    '1.3': 'slope B set by slope A in Rise/Fall mode', '1.4': 'parameter disallowed in High Speed mode', '1.5': 'calibration data unaccessible in present mode',
    '2.0': 'invalid key entry', '2.1': 'data outside valid range', '2.2': 'data exceeds maximum resolution', '2.3': 'mantissa digit buffer full',
    '2.4': 'decimal point previously entered', '3.0': 'multiple key closures', '4.0': 'HP-IB mnemonic not recognizable', '4.1': 'HP-IB numeric syntax error',
    '4.2': 'HP-IB alpha character expected', '4.3': 'HP-IB data exceeds valid range', '4.4': 'attention (ATN) asserted in Talk-Only mode',
}
WRITE_TERMINATION = '\n'   # commands end with LF (and EOI) only: the manual names only spaces, commas and semicolons as separators (3-307), and the VISA default CR LF
                            # was followed by error 4.2 'alpha character expected' at Test connections on the owner's bench (2026-11-04)
READING = re.compile(r'^\s*([A-Za-z])\s*([+-]\d(?:\.\d*)?E[+-]\d{2})\s*$')                                  # p. 3-84

COMMANDS = {
    'reset': cmdreg.reset_cmd(True, _r('IN (initialize)', '3-80 / 3-81, 3-324 / 3-325'), template='IN',
                              note='Power-on initialized state: FREQ A, AUTO TRIG on, gate 300 ms. It does not clear errors 5.0X to 5.2 or failures'),
    'id': Cmd('ID', 'Identify', 'The counter sends "HP 5334A/B" (p. 3-80); only "5334" is required of the reply', kind='query', risk='locked', verified=True,
              ref=_r('ID', '3-80 / 3-323 and Example 1, 3-89 / 3-90')),
    'fn.freq_a': Cmd('FN1', 'Frequency A', 'Function FREQ A (0.001 Hz to 100 MHz)', kind='set', verified=True, ref=_r('FN1, Table 3-12', '3-82')),
    'fn.freq_c': Cmd('FN3', 'Frequency C', 'Function FREQ C (Option 030, 90 to 1300 MHz)', kind='set', verified=True, ref=_r('FN3, Table 3-12', '3-82')),
    'gate.set': Cmd('GA{s:.3f}', 'Gate time', 'Gate time in seconds, 0.001 to 99.999 s in 1 ms steps', placeholders={'s': Placeholder('float', '.3f', 1.0)},
                    kind='set', verified=True, ref=_r('GA, Table 3-12', '3-83; 1 ms entry resolution, error 2.2 example p. 3-49')),
    'wait.on': Cmd('WA1', 'Wait to be addressed on', 'One measurement at a time, held until the controller reads it', kind='set', verified=True,
                   ref=_r('WA1', '3-81 / 3-331')),
    'restart': Cmd('RE', 'Reset (restart measurement)', 'Clears the current measurement and starts a new one (does not clear errors 5.0X to 5.2)', kind='set', verified=True,
                   ref=_r('RE', '3-81 / 3-326')),
    'error.query': Cmd('TE', 'Transmit error', 'The number of the detected error (the reply text is not printed: UNVERIFIED); clears the error bit, not the error state',
                       kind='query', risk='locked', verified=False, ref=_r('TE', '3-81 / 3-330 and 3-88 / 3-355')),
}


class HP5334B(Instrument):
    MODEL = 'HP 5334B'
    IDN_MATCH = ()                       # ID is checked in connect() ('5334' in the reply)
    ID_WORDS = ('5334',)
    DEFAULT_ADDRESS = 3                  # factory HP-IB address 03 (p. 3-71, 3-232)
    DEFAULT_TIMEOUT = 10.0
    READ_MARGIN_S = 5.0                  # a reading arrives within gate + this (a choice of this driver; the manual gives no figure)
    RESET_SETTLE_S = 1.0                 # after IN (a choice of this driver)
    RESET_NO_OPC = 'The 5334B has no *OPC? (device command language): after IN the driver waits RESET_SETTLE_S and reads the status byte instead.'
    COMMANDS = COMMANDS

    id_reply = ''

    def __init__(self, transport, log=None, label=None, address=None):
        super().__init__(transport, log, label)
        self._address = check_address(address) if address is not None else address_of(getattr(transport, 'address', None))

    @property
    def address(self) -> int:
        return self._address if self._address is not None else self.DEFAULT_ADDRESS

    def set_address(self, address):
        if self._open:
            raise InstrumentError(f'{self.MODEL}: close the connection before changing the HP-IB address')
        self._address = check_address(address)

    def send(self, key, **vals):
        super().send(key, **vals)
        if key == 'reset':
            time.sleep(self.RESET_SETTLE_S)

    def identify(self):
        return self.ask('id').strip()

    # ---- status -----------------------------------------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        """The status byte by serial poll (Table 3-11): {'value', 'data_ready', 'error', 'failure', 'local', 'no_oscillator', 'rqs'}."""
        value = serial_poll(self.t)
        self.log.add('--', f'serial poll -> {value}', self.label)
        out: dict[str, Any] = {name: bool(value & bit) for bit, name in STATUS_BITS.items()}
        out['value'] = value
        return out

    def error_number(self) -> str:
        """TE: the counter's error / failure number, as sent (format UNVERIFIED). Read-only; it does not clear the error state (p. 3-88)."""
        return self.ask('error.query').strip()

    @staticmethod
    def error_text(number) -> str:
        """'4.2' -> '4.2 (HP-IB alpha character expected)'; the TE reply is kept as sent when it holds no known number."""
        m = re.search(r'\d\.\d', str(number))
        meaning = ERROR_TEXT.get(m.group(0)) if m else None
        return f'{number} ({meaning})' if meaning else str(number)

    def _line_ends(self):
        """Commands end with LF only, replies are read to the LF of their CR LF (as the 8902A driver does). A VISA resource has these attributes; a simulator may.
        UNVERIFIED on the bench until the owner confirms the 4.2 is gone."""
        target = getattr(self.t, '_res', None) or self.t
        for attr, value in (('write_termination', WRITE_TERMINATION), ('read_termination', '\n')):
            if hasattr(target, attr):
                try:
                    setattr(target, attr, value)
                except Exception:                                          # noqa: BLE001 - the defaults then stay
                    pass

    def check_status(self, context='', oscillator=True):
        """Serial poll once: raise on an error (bit 4, with the TE number), a failure (bit 8) or no oscillator (bit 32: with TIME BASE on EXT, no 10 MHz at the rear
        TIME BASE IN/OUT). Returns the status dict."""
        st = self.status()
        where = f' after {context}' if context else ''
        if st['error'] or st['failure']:
            try:
                number = self.error_number()
            except (InstrumentError, TransportError) as exc:
                number = f'unreadable ({exc})'
            what = 'a failure' if st['failure'] else 'an error'
            raise InstrumentError(f'{self.MODEL} reports {what}{where}: TE {self.error_text(number)} (status byte {st["value"]}; Tables 3-3 / 3-4, p. 3-48 / 3-49). '
                                  'In remote the counter then ignores commands until it is cleared.')
        if oscillator and st['no_oscillator']:
            raise InstrumentError(f'{self.MODEL}: no time base oscillator{where} (status byte {st["value"]}). With the rear TIME BASE switch on EXT the 10 MHz reference '
                                  '(the lab GPS) must be connected to TIME BASE IN/OUT.')
        return st

    # ---- connection -------------------------------------------------------------------------------------------------------------------------------
    def connect(self, address=None):
        """Re-target the transport to the HP-IB address (given here, at construction, or DEFAULT_ADDRESS), open, device clear, ID (must contain '5334'), IN, WA1, status."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=False)
        try:
            self._line_ends()
            self.t.clear()                                                    # also clears errors 1.0 to 4.4 left by anything else (a *IDN? scan gives 4.2)
            self.idn = self.id_reply = self.identify()
            if not any(w in self.idn for w in self.ID_WORDS):
                raise InstrumentError(f'Expected {self.MODEL} at HP-IB address {self.address} but the ID reply is {self.idn!r}')
            self.send('reset')
            self.send('wait.on')
            self.check_status('connect (device clear, ID, IN, WA1)', oscillator=False)   # an error stops the connection with its number (bench 2026-11-04: 4.2 went
                                                                              # unseen); no oscillator is judged per point (the GPS may be connected at the hook-up prompt)
        except Exception:
            self.close()
            raise
        return self

    def _reset_drain(self, rep, limit=10):
        st = self.status()
        if st['error'] or st['failure']:
            rep.warnings.append(f'status byte after reset: {st["value"]}')
            self.log.add('!!', f'status byte after reset: {st["value"]}', self.label)
            return 'status byte drained'
        return 'status byte clean'

    def _reset_extra(self):
        return [('wait to be addressed again (WA1; IN clears it)', lambda: self.send('wait.on'))]

    def go_local(self):
        """GTL (the transport's go_local); the front panel works again. Never raises."""
        try:
            self.t.go_local()
        except Exception:
            pass

    def cleanup(self):
        """The counter has no output to switch off: handed back to the front panel. Never raises."""
        self.go_local()

    # ---- measuring --------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def parse_reading(text: str) -> float:
        """A 19-character reading (p. 3-84) as a frequency in Hz. 'O' (overflow) or anything but an 'F' reading raises InstrumentError."""
        m = READING.match(str(text))
        if not m:
            raise InstrumentError(f'5334B: unreadable reply {text!r} (expected F +d.ddddE+dd, p. 3-84)')
        alpha, number = m.group(1), m.group(2)
        if alpha == 'O':
            raise InstrumentError(f'5334B: overflow reading {text.strip()!r} (p. 3-85): the measurement is incorrect (no or wrong input signal?)')
        if alpha != 'F':
            raise InstrumentError(f'5334B: {alpha!r} reading {text.strip()!r} is not a frequency (F, p. 3-84)')
        return float(number)

    def measure_frequency_hz(self, channel: str = 'C', gate_s: float = 1.0, expect_hz: float | None = None) -> float:
        """FREQ A (FN1) or FREQ C (FN3), gate time GA, RE (a new measurement), read it (WA1 holds it until read), then the status byte. Returns Hz.
        expect_hz (optional) is checked against the channel's printed range before anything is sent."""
        ch = str(channel).upper()
        if ch not in CHANNELS:
            raise InstrumentError(f'5334B channel {channel!r} is not A or C')
        if not GATE_RANGE_S[0] <= float(gate_s) <= GATE_RANGE_S[1]:
            raise InstrumentError(f'5334B gate time {gate_s:g} s is outside {GATE_RANGE_S[0]:g} to {GATE_RANGE_S[1]:g} s')
        if expect_hz is not None and not CHANNEL_RANGE_HZ[ch][0] <= float(expect_hz) <= CHANNEL_RANGE_HZ[ch][1]:
            lo, hi = CHANNEL_RANGE_HZ[ch]
            raise InstrumentError(f'5334B: {expect_hz:g} Hz is outside the FREQ {ch} range {lo:g} to {hi:g} Hz (Table 1-1)')
        self.send(CHANNELS[ch])
        self.send('gate.set', s=float(gate_s))
        self.send('restart')
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(float(gate_s) + self.READ_MARGIN_S, prev or 0.0))
        try:
            raw = self.t.read()
        except TransportError as exc:
            try:
                self.check_status(f'FREQ {ch} (no reading)')               # an error state (the counter then ignores commands), a failure or no oscillator is the real cause
            except InstrumentError as cause:
                raise cause from exc
            raise InstrumentError(f'{self.MODEL}: no FREQ {ch} reading within {float(gate_s) + self.READ_MARGIN_S:g} s: {exc}. Status byte clean: is the signal at INPUT {ch}?') from exc
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        self.log.add('<<', raw.strip(), self.label)
        self.check_status(f'FREQ {ch} reading')
        return self.parse_reading(raw)
