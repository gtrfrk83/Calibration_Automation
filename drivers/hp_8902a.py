"""HP / Agilent 8902A Measuring Receiver over HP-IB (GPIB), driven in its own two-letter code language (it has NO SCPI: no *IDN?, no *RST, no *OPC?).

Source: "8902A Measuring Receiver Operating and Calibration Manual" (part no. 08902-99001, Aug 1987), Section 3 (Operation, HP-IB programming), read from rendered page
images. Page references are "printed / PDF". What the manual does not print is NOT guessed: it is verified=False in COMMANDS and listed in the report. The main ones:
    * the reply to ID (the code exists, the returned text is not in the pages read): connect() keeps the raw reply and only requires that there is one,
    * how the VALUE behind a special-function display (15.1SP external time base, 37.4SP entry count, 42.0SP date code, 38.x / 39.x cal factors) is read over the bus
      (the driver sends the code and reads, no trigger),
    * that an LG tuned-RF-level reading is dBm and an LG reading in M4 is dBm (the manual only prints "dBm" on the display), and that an FM reading is in Hz,
    * how long IP takes, how long T3 settles, and the duration of the AM / FM calibration (the manual gives ~17 s per update and ~20 s to the first value),
    * that the audio distortion / audio frequency functions (S1, S2) see the demodulated signal after M1 / M2 (the manual lists A0 / A1 / A2 inconsistently),
    * the 0.1 Hz frequency resolution (7.4SP, not on firmware date code 234.1985 and older) and every special function marked "not on early firmware".
There is NO read-back for mode, detector, filter, de-emphasis, tuning or resolution codes (no query exists). The checks are therefore: the status byte (serial poll) after each
setup (bit 1 = HP-IB code error, bit 2 = instrument error), the error words the receiver returns as DATA (see decode_reading), and read-back where a special function can
show a value (the SRQ mask, 22.64SP; the cal-factor table).

Language facts used (Section 3):
  * Address: factory 14 (DEFAULT_ADDRESS, p. 3-20 / 70), set on the rear switch; given to the constructor / connect(), never fixed in code. Characters: upper / lower case alike,
    spaces and commas between codes are ignored. Recommended string order: AU - tune (MZ) - measurement (Mx / Sx) - detector Dx - de-emphasis Px - filters Hx Lx - special
    functions - ratio - trigger (T last). This driver sends ONE code (or one code group such as "7.1SP") per write, the trigger last, then reads.
  * A reading is "+0096921346E+01" CR LF in fundamental units (Hz, W, dB, %, V): sign, 10 digits, E, signed exponent (p. 3-18 / 68). An error is returned as DATA: a value above
    9e10 is an error word, error = (value - 9e10) / 1000 (p. 3-286 / 311).
  * Trigger (p. 3-22 to 3-24): T1 hold, T3 trigger with settling (= GET); read the result before sending anything else. A serial poll returns the status byte.
  * IP (= device clear, p. 3-25 / 75, 3-241 / 271) is the locked reset: it keeps the non-volatile calibration data and sets the power-up state (free-run T0, frequency measurement).
Writes are sent once and never retried. Only read-only queries (ID) may be retried. Calibration codes (ZR, C1, SC, cal-factor entry) are locked: they cannot be overridden. The
receiver has no output to switch off; nothing here needs a standby step.
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .gpib_address import address_of, check_address, retarget, serial_poll
from .transport import TransportError

UM = '8902A Operating and Calibration Manual'


def _r(topic, page):
    return f'{UM}: {topic} (p. {page})'


def _enum(*values, sample=None):
    return Placeholder('enum', '', sample if sample is not None else values[0], enum=tuple(values))


ERROR_TEXT = {
    1: 'IF frequency error (retune)', 2: 'input level too high', 3: 'input level too low', 4: 'audio circuits overdriven', 5: 'FM squelched', 6: 'RF input overload',
    7: 'voltmeter / display overload', 8: 'calibrator error', 9: 'option not installed', 10: 'input frequency out of range', 11: 'calculated value out of range',
    12: 'time base oven cold', 13: 'power sensor not connected', 14: 'power sensor cannot zero', 15: 'calibration factor error', 16: 'audio circuits underdriven',
    17: 'selective power measurement', 18: 'RF power will not calibrate', 19: 'tuned RF level circuits underdriven', 20: 'value out of range', 21: 'invalid key sequence',
    22: 'invalid special function prefix', 23: 'invalid special function suffix', 24: 'invalid HP-IB code', 25: 'special function not compatible with the selected measurement',
    26: 'end of RF power cal table', 30: 'manual attenuator / gain set (tuned RF level cal)', 31: 'needs a new power reference', 32: 'calibration not possible',
    33: 'power sensor reference error', 34: 'signal lost', 35: 'level error', 96: 'no input signal sensed (HP-IB only)'}
STATUS_BITS = {1: 'data_ready', 2: 'code_error', 4: 'instrument_error', 8: 'limit_exceeded', 16: 'freq_offset_change', 32: 'recal_or_uncal', 64: 'rqs'}
DETECTORS = {1: 'peak+', 2: 'peak-', 3: 'peak hold', 4: 'average (rms calibrated)', 8: 'true rms', 9: '(peak+ and peak-)/2'}
DEEMPHASIS_US = {25: '2', 50: '3', 75: '4', 750: '5'}              # P2..P5 after P1 (p. 3-187 / 228)
RESOLUTION_SF = {None: '0', 10: '1', 100: '2', 1000: '3', 0.1: '4'}  # 7.xSP (p. 3-277 / 301)
TUNED_DETECTOR_SF = {'sync': '0', 'average': '4'}                     # 4.0SP / 4.4SP (p. 3-99 / 150)
RF_POWER_ZERO_MAX_W = 3.0e-6                                          # residual after ZR, basic check (p. 3-49 / 101)
CAL_POWER_W = (0.999e-3, 1.000e-3)                                    # after SC the display is between 0.999 and 1.000 mW (p. 3-49 / 101)
MAX_VALUE = 9.0e10                                                    # above this a reading is an error word


COMMANDS = {
    'reset': cmdreg.reset_cmd(True, _r('IP = instrument preset (same as DCL)', '3-241 / 271 and 3-25 / 75'), template='IP',
                              note='Power-up settings without the internal checks; the non-volatile calibration data is kept; trigger becomes free-run (T0)'),
    'id': Cmd('ID', 'Identify', 'Identify instrument. The text it returns is NOT in the manual pages read (UNVERIFIED): kept as read, never matched exactly (never overridable)',
              kind='query', risk='locked', verified=False, ref=_r('ID, Table 3-11 and 3-13', '3-38 and 3-41 / 88 and 91')),
    # ---- tuning (p. 3-141 / 188) ----
    'tune.mhz': Cmd('{mhz:.8g}MZ', 'Tune (MHz)', 'Manual tuning to the carrier in MHz (up to 8 digits). Use the source frequency', placeholders={'mhz': Placeholder('float', '.8g', 100.0)},
                    kind='set', verified=True, ref=_r('MZ', '3-141 / 188 and 3-16 / 66')),
    'tune.auto': Cmd('AU', 'Automatic operation', 'Tunes to the strongest signal and resets most special functions (it does not change the measurement, detector, filters)', kind='set', verified=True,
                     ref=_r('AU', '3-237 / 268')),
    # ---- trigger (p. 3-22 to 3-24 / 72 to 74) ----
    'trig.free': Cmd('T0', 'Trigger free-run', 'Continuous readings with no regard for settling', kind='set', verified=True, ref=_r('T0', '3-22 / 72')),
    'trig.hold': Cmd('T1', 'Trigger hold', 'The receiver sets up and waits for a trigger; the data is held', kind='set', verified=True, ref=_r('T1', '3-22 / 72')),
    'trig.settle': Cmd('T3', 'Trigger with settling', 'One measurement after a settling delay (= GET). The result must be read before anything else is sent', kind='set', verified=True,
                       ref=_r('T3', '3-24 / 74')),
    # ---- display units ----
    'units.log': Cmd('LG', 'Log units', 'dB / dBm display and output', kind='set', verified=True, ref=_r('LG', '3-101 / 153 and 3-79 / 128')),
    'units.lin': Cmd('LN', 'Linear units', 'Linear output (percent, volts, watts)', kind='set', verified=True, ref=_r('LN', '3-101 / 153')),
    'units.watt': Cmd('WT', 'Watts', 'Linear power in watts', kind='set', verified=True, ref=_r('WT', '3-79 / 128')),
    # ---- detectors, filters, de-emphasis (p. 3-201 to 3-209, 3-187) ----
    'det.set': Cmd('D{n}', 'Detector', '1 peak+, 2 peak-, 3 peak hold, 4 average (rms calibrated), 8 true rms, 9 (peak+ and peak-)/2', placeholders={'n': _enum('1', '2', '3', '4', '8', '9')},
                   kind='set', verified=True, ref=_r('D1..D9', '3-201 and 3-202 / 240 and 241')),
    'dist.set': Cmd('D{n}', 'Distortion frequency', '5 = 1 kHz, 6 = 400 Hz (the fundamental must be within 5 %)', placeholders={'n': _enum('5', '6')}, kind='set', verified=True,
                    ref=_r('D5 / D6', '3-229 / 262')),
    'hp.set': Cmd('H{n}', 'High-pass filter', '0 off, 1 50 Hz, 2 300 Hz', placeholders={'n': _enum('0', '1', '2')}, kind='set', verified=True, ref=_r('H0..H2', '3-207 / 244')),
    'lp.set': Cmd('L{n}', 'Low-pass filter', '0 off, 1 3 kHz, 2 15 kHz, 3 >20 kHz', placeholders={'n': _enum('0', '1', '2', '3')}, kind='set', verified=True, ref=_r('L0..L3', '3-207 / 244')),
    'deemph.set': Cmd('P{n}', 'Pre-display / de-emphasis', '0 off, 1 pre-display and de-emphasis on, then 2 = 25 us, 3 = 50 us, 4 = 75 us, 5 = 750 us (FM only). True rms (D8) forces pre-display on',
                      placeholders={'n': _enum('0', '1', '2', '3', '4', '5')}, kind='set', verified=True, ref=_r('P0..P5', '3-187 / 228 and 3-17 / 67')),
    # ---- special functions (p. 3-276 to 3-284 / 300 to 308) ----
    'res.set': Cmd('7.{n}SP', 'RF frequency resolution', '0 auto, 1 10 Hz, 2 100 Hz, 3 1 kHz, 4 0.1 Hz below 10.1 MHz / 1 Hz above (about 20 s at 1300 MHz; not on firmware date code 234.1985 and older)',
                   placeholders={'n': _enum('0', '1', '2', '3', '4', sample='1')}, kind='set', verified=True, ref=_r('SF 7', '3-277 / 301')),
    'det.tuned': Cmd('4.{n}SP', 'Tuned RF level detector', '0 synchronous (auto), 1 to 3 synchronous 10 s / 1 s / 0.1 s, 4 IF average (auto), 5 to 7 average 10 s / 1 s / 0.1 s',
                     placeholders={'n': _enum('0', '1', '2', '3', '4', '5', '6', '7')}, kind='set', verified=True, ref=_r('SF 4', '3-276 / 300 and 3-99 / 150')),
    'srq.set': Cmd('22.{mask}SP', 'SRQ mask', 'Sum of the status weights 0 to 63 (bit 1, HP-IB code error, is always on)', placeholders={'mask': Placeholder('int', '', 2)}, kind='set',
                   verified=True, ref=_r('SF 22', '3-30 and 3-31 / 80 and 81')),
    'srq.read': Cmd('22.64SP', 'Show the SRQ mask', 'Displays the present mask; the value is read like a measurement (UNVERIFIED mechanism)', kind='set', verified=False,
                    ref=_r('SF 22.64', '3-30 / 80 and 3-279 / 303')),
    'sf.display': Cmd('{sf}SP', 'Display a special-function value', '15.1 external time base (1 = external), 15.0 oven (0 = warm), 37.4 cal-factor entries, 42.0 firmware date code. How the value is read '
                      'over the bus is UNVERIFIED', placeholders={'sf': _enum('15.1', '15.0', '37.4', '42.0', '38.1', '38.2', '38.3')}, kind='set', verified=False,
                      ref=_r('SF 15, 37, 38, 42', '3-279 / 303, 3-87 / 136, 3-100 / 151')),
    # ---- measurement functions (Table 3-11 / 3-12, p. 3-38 / 88) ----
    'func.am': Cmd('M1', 'Measure AM', 'AM depth in percent', kind='set', verified=True, ref=_r('M1', '3-161 / 207')),
    'func.fm': Cmd('M2', 'Measure FM', 'FM deviation (HP-IB result in Hz: inferred from the output rule, UNVERIFIED)', kind='set', verified=True, ref=_r('M2', '3-177 / 219')),
    'func.power': Cmd('M4', 'Measure RF power', 'RF power with a power sensor module (needs ZR and the 1 mW calibration first)', kind='set', verified=True, ref=_r('M4', '3-75 to 3-80 / 124 to 129')),
    'func.freq': Cmd('M5', 'Measure frequency', 'RF input frequency counter, result in Hz', kind='set', verified=True, ref=_r('M5', '3-137 / 185')),
    'func.audio_freq': Cmd('S1', 'Audio frequency', 'Audio frequency counter, 20 Hz to 250 kHz', kind='set', verified=True, ref=_r('S1', '3-227 / 260')),
    'func.distortion': Cmd('S2', 'Audio distortion', 'Percent with LN, dB with LG', kind='set', verified=True, ref=_r('S2', '3-229 / 262')),
    'func.tuned_level': Cmd('S4', 'Tuned RF level', 'Tuned RF level, 0 to -127 dBm, needs per-frequency calibration (RECAL)', kind='set', verified=True, ref=_r('S4', '3-95 to 3-110 / 144 to 162')),
    'func.freq_error': Cmd('S5', 'Frequency error', 'Frequency error in Hz relative to the tuned frequency', kind='set', verified=True, ref=_r('S5', '3-149 / 196')),
    # ---- calibration of the receiver itself (locked) ----
    'cal.on': Cmd('C1', 'Calibrate on', 'Starts the calibration of the selected function (never overridable)', kind='set', risk='locked', verified=True, ref=_r('C1', '3-167 / 211 and 3-77 / 126')),
    'cal.power': Cmd('C1T3SC', 'Power calibration string', 'The manual\'s own string for the 1 mW power calibration: calibrate on, trigger with settling, save cal; sent as ONE write like the manual does '
                     '(never overridable)', kind='set', risk='locked', verified=True, ref=_r('C1T3SC', '3-77 / 126')),
    'cal.off': Cmd('C0', 'Calibrate off', 'Calibrator off (never overridable)', kind='set', risk='locked', verified=True, ref=_r('C0', '3-181 / 223 and 3-77 / 126')),
    'zero': Cmd('ZR', 'Zero', 'Zeroes the power sensor (about 15 s) (never overridable)', kind='set', risk='locked', verified=True, ref=_r('ZR', '3-77 / 126')),
    'save.cal': Cmd('SC', 'Save cal', 'Saves the 1 mW power calibration (never overridable)', kind='set', risk='locked', verified=True, ref=_r('SC', '3-77 / 126')),
    'cf.display': Cmd('CF', 'Display cal factor', 'Shows the calibration factor in percent (100.00 = no error); how it is read over the bus is UNVERIFIED', kind='set', verified=False,
                      ref=_r('CF', '3-167 / 211 and 3-168 / 212')),
    'cf.ref': Cmd('37.3SP {cf:.5g} CF', 'Reference cal factor', 'Reference (50 MHz) calibration factor in percent for the power sensor (never overridable)',
                  placeholders={'cf': Placeholder('float', '.5g', 98.5)}, kind='set', risk='locked', verified=True, ref=_r('SF 37.3', '3-75 / 124 and 3-78 / 127')),
    'cf.pair': Cmd('37.3SP {mhz:.8g} MZ {cf:.5g} CF', 'Cal factor at a frequency', 'One frequency / cal-factor pair (16 allowed; 0 % removes an entry) (never overridable)',
                   placeholders={'mhz': Placeholder('float', '.8g', 1.0), 'cf': Placeholder('float', '.5g', 99.0)}, kind='set', risk='locked', verified=True, ref=_r('SF 37.3', '3-75 / 124 and 3-78 / 127')),
    'cf.recall.ref': Cmd('37.5SP CF', 'Recall reference cal factor', 'Shows the reference calibration factor (only after M4); how it is read over the bus is UNVERIFIED', kind='set', verified=False,
                         ref=_r('SF 37.5', '3-87 / 136')),
}


def decode_reading(text: str) -> float:
    """'+0096921346E+01' -> 969213460.0. Sign, 10 digits, E, signed 2-digit exponent. An error word (value above 9e10) raises InstrumentError with the error number and text."""
    m = re.fullmatch(r'\s*([+-])(\d{10})E([+-]\d{1,2})\s*', str(text))
    if not m:
        raise InstrumentError(f'8902A: unreadable reading {text!r} (expected a form like +0096921346E+01)')
    value = (-1 if m.group(1) == '-' else 1) * int(m.group(2)) * 10.0 ** int(m.group(3))
    if value > MAX_VALUE + 1.0:
        code = round((value - MAX_VALUE) / 1000.0)
        raise InstrumentError(f'8902A error {code}: {ERROR_TEXT.get(code, "unknown error")} (reading {text.strip()})')
    return value


def encode_reading(value: float, error: int | None = None) -> str:
    """The reading text of a value (the simulator's side of decode_reading): sign, 10-digit mantissa (8 significant digits), E, signed exponent, value = mantissa x 10**exponent.
    error=n gives the error word of error n (value 9e10 + n x 1000)."""
    if error is not None:
        return f'+{int(MAX_VALUE / 10 + error * 100):010d}E+01'
    if value == 0:
        return '+0000000000E+00'
    lead, exp = f'{abs(value):.7E}'.split('E')
    mant = int(lead.replace('.', ''))
    return f'{"-" if value < 0 else "+"}{mant:010d}E{int(exp) - 7:+03d}'


class RecalRequired(InstrumentError):
    """The receiver's RECAL / UNCAL flag (status bit 5) is set after a tuned-RF-level reading: calibrate_tuned_level() at a constant level."""


class HP8902A(Instrument):
    MODEL = 'HP 8902A'
    IDN_MATCH = ()                       # the ID reply is not printed in the manual: kept as read, see connect()
    ID_TIMEOUT_S = 3.0
    ID_WORDS = ('8902', '8901')          # only used to log a warning
    DEFAULT_ADDRESS = 14                 # factory HP-IB address (p. 3-20 / 70); the rear switch can change it
    DEFAULT_TIMEOUT = 40.0               # a tuned-RF-level read can take up to ~10 s at -127 dBm, a 0.1 Hz frequency read ~20 s, a 6-dash search ~20 s (the manual gives no bound): 30 s minimum
    TUNED_TIMEOUT_S = 45.0
    SLOW_FREQ_TIMEOUT_S = 60.0           # 7.4SP
    CAL_WAIT_S = 20.0                    # AM / FM calibration: ~20 s to the first value, ~17 s per update (p. 3-51 / 103, 3-167 / 211)
    ZERO_WAIT_S = 15.0                   # ZR: dashes for ~15 s (p. 3-77 / 126)
    RESET_NO_OPC = 'The 8902A has no *OPC? (code language): after IP the driver waits RESET_SETTLE_S and reads the status byte instead.'
    SETUP_SETTLE_S = 1.0                 # after the mode / tune / resolution codes, before the first status read (a choice of this driver: UNVERIFIED, tune on the bench)
    RESET_SETTLE_S = 3.0                 # after IP: a choice of this driver, the manual gives no figure
    COMMAND_GAP_S = 0.05
    COMMANDS = COMMANDS

    id_reply = ''
    id_matches = False

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

    # ---- wire access ---------------------------------------------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        super().write(cmd, log_as)

    def send(self, key, **vals):
        super().send(key, **vals)
        if key == 'reset':
            time.sleep(self.RESET_SETTLE_S)

    def identify(self):
        return self.ask('id').strip()

    def _read_reading(self, timeout: float | None = None) -> str:
        """ENTER: read the reply that follows a trigger (the receiver holds the bus until the measurement is done). The transport timeout is raised for the read and put back."""
        prev = getattr(self.t, 'timeout', None)
        if timeout:
            self.t.set_timeout(max(timeout, prev or 0.0))
        try:
            raw = self.t.read()
        except TransportError as exc:
            seen = ''
            try:
                seen = f' Status byte after the timeout: {serial_poll(self.t)}.'
            except Exception:                                              # noqa: BLE001 - a diagnostic only
                pass
            raise InstrumentError(f'{self.MODEL}: no reading (timeout {timeout or prev}): {exc}.{seen}') from exc
        finally:
            if timeout:
                self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        self.log.add('<<', raw.strip(), self.label)
        return raw

    # ---- status ---------------------------------------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        """The status byte by serial poll (reading it clears it): {'value', 'data_ready', 'code_error', 'instrument_error', 'limit_exceeded', 'freq_offset_change',
        'recal_or_uncal', 'rqs'}."""
        value = serial_poll(self.t)
        self.log.add('--', f'serial poll -> {value}', self.label)
        out = {name: bool(value & bit) for bit, name in STATUS_BITS.items()}
        out['value'] = value
        return out

    def check_status(self, context=''):
        """Serial poll once: raise on an HP-IB code error (bit 1) or an instrument error (bit 2). Returns the status dict."""
        st = self.status()
        if st['code_error'] or st['instrument_error']:
            what = 'HP-IB code error' if st['code_error'] else 'instrument error'
            raise InstrumentError(f'{self.MODEL} reports an {what}{" after " + context if context else ""} (status byte {st["value"]})')
        return st

    def set_srq_mask(self, mask: int) -> int:
        """22.<mask>SP, then 22.64SP and a read: the mask shown must equal the one sent (bit 1 is always on)."""
        if not 0 <= int(mask) <= 63:
            raise InstrumentError(f'SRQ mask {mask!r} is outside 0 to 63')
        want = int(mask) | 2
        self.send('srq.set', mask=int(mask))
        self.send('srq.read')
        got = int(round(decode_reading(self._read_reading(self.DEFAULT_TIMEOUT))))
        if got != want:
            raise InstrumentError(f'{self.MODEL}: SRQ mask {want} was not accepted: the receiver shows {got}')
        return got

    # ---- connection ---------------------------------------------------------------------------------------------------------------------------
    def connect(self, address=None):
        """Re-target the transport to the HP-IB address (given here, at construction, or DEFAULT_ADDRESS), open, device clear (= IP), ID. The ID reply is stored in id_reply /
        idn; it is only required to be non-empty (its text is not in the manual), and a reply without '8902' / '8901' is logged as a warning (id_matches False)."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=False)
        self._line_ends()
        try:
            self.t.clear()
            time.sleep(self.RESET_SETTLE_S)
            # ID is only a courtesy: the manual shows the code but not any reply (owner bench, 2026-10-28: the 8902A does not answer ID). One short try (read-only, no
            # retries: every miss costs a full timeout); no reply is NOT an error as long as the receiver answers a serial poll (it is there and listening).
            prev = getattr(self.t, 'timeout', None)
            self.t.set_timeout(self.ID_TIMEOUT_S)
            try:
                self.idn = self.id_reply = self.ask('id').strip()
                no_reply = False
            except (InstrumentError, TransportError) as exc:
                self.idn = self.id_reply = ''
                no_reply = True
                self.log.add('!!', f'no reply to ID within {self.ID_TIMEOUT_S:g} s ({exc}); continuing: the receiver is checked with a serial poll instead', self.label)
            finally:
                if prev:
                    self.t.set_timeout(prev)
            if no_reply:
                try:
                    value = serial_poll(self.t)
                except InstrumentError as exc:
                    raise InstrumentError(f'{self.MODEL}: nothing answers at HP-IB address {self.address}: no reply to ID and the serial poll failed ({exc})') from exc
                self.log.add('--', f'serial poll -> {value} (the receiver is present)', self.label)
            elif not self.idn:
                raise InstrumentError(f'{self.MODEL}: empty ID reply (is the receiver at HP-IB address {self.address}?)')
            self.id_matches = any(w in self.idn for w in self.ID_WORDS)
            if self.idn and not self.id_matches:
                self.log.add('!!', f'ID reply {self.idn!r} does not mention 8902 / 8901 (the reply text is not in the manual: UNVERIFIED)', self.label)
            self.status()                                                 # clear anything pending
        except Exception:
            self.close()
            raise
        return self

    def _line_ends(self):
        """HP-IB line ends for a VISA GPIB resource: commands end with LF only (the VISA default CR+LF sends a CR the receiver may not take as a character it ignores) and a reading
        ends at the LF of its CR LF (the end-of-line character) as well as at EOI, so a read does not wait for an EOI the receiver may not send. Transports without these
        attributes (the simulators) are left alone. UNVERIFIED on the bench: the manual states neither."""
        res = getattr(self.t, '_res', None)
        if res is None:
            return
        for attr, value in (('write_termination', '\n'), ('read_termination', '\n')):
            try:
                setattr(res, attr, value)
            except Exception:                                              # noqa: BLE001 - not every resource has them; the defaults then stay
                pass

    def remote(self):
        """Put the receiver in remote: it goes remote when addressed to listen (p. 3-21 / 71); T1 (hold) is the harmless listen. No settings change."""
        self.send('trig.hold')

    def go_local(self):
        """GTL (the transport's go_local); the front panel works again. Never raises."""
        try:
            self.t.go_local()
        except Exception:
            pass

    def cleanup(self):
        """Nothing is switched on by the receiver: back to free-run is not needed. It is handed back to the front panel. Never raises."""
        self.go_local()

    def _reset_drain(self, rep, limit=10):
        st = self.status()
        if st['code_error'] or st['instrument_error']:
            rep.warnings.append(f'status byte after reset: {st["value"]}')
            self.log.add('!!', f'status byte after reset: {st["value"]}', self.label)
            return 'status byte drained'
        return 'status byte clean'

    # ---- measuring ------------------------------------------------------------------------------------------------------------------------------
    def _setup(self, steps, context):
        for key, vals in steps:
            self.send(key, **vals)                                        # each once, never retried
        # Owner bench 2026-10-28: a serial poll straight after the setup read status byte 60 (instrument error, limit, offset, RECAL): the receiver is still tuning / settling and
        # briefly shows an error. Wait, then read (and so clear) the byte; only an HP-IB CODE error (a command it did not understand) is fatal here. A real measurement problem
        # arrives as an error word in the reading itself (decode_reading raises it) and the status byte is checked again after the reading.
        time.sleep(self.SETUP_SETTLE_S)
        st = self.status()
        if st['code_error']:
            raise InstrumentError(f'{self.MODEL} reports an HP-IB code error after {context} (status byte {st["value"]}): a command was not understood')
        if st['instrument_error']:
            self.log.add('!!', f'status byte {st["value"]} after {context}: an error was displayed while the receiver settled; it is read again with the measurement', self.label)

    def _tune(self, carrier_mhz):
        return ('tune.mhz', {'mhz': float(carrier_mhz)}) if carrier_mhz else ('tune.auto', {})

    def _trigger_read(self, timeout=None, context='') -> float:
        self.send('trig.hold')
        self.send('trig.settle')
        text = self._read_reading(timeout or self.DEFAULT_TIMEOUT)
        try:
            return decode_reading(text)
        except InstrumentError:
            try:
                self.status()                                             # an error word also sets the instrument-error bit: read (and so clear) it before the next point
            except Exception:                                             # noqa: BLE001 - the reading error is the one to report
                pass
            raise

    def measure_frequency_hz(self, carrier_mhz: float | None = None, resolution_hz=10) -> float:
        """RF input frequency in Hz (150 kHz to 1300 MHz). Tuned manually to carrier_mhz (the source frequency; None = automatic tuning), resolution 10 / 100 / 1000 Hz, 0.1 (UNVERIFIED on
        old firmware) or None (auto). The accuracy is that of the time base (internal 10 MHz, or the external reference the receiver switches to by itself)."""
        if resolution_hz not in RESOLUTION_SF:
            raise InstrumentError(f'frequency resolution {resolution_hz!r} is not one of {list(RESOLUTION_SF)}')
        steps = [self._tune(carrier_mhz), ('func.freq', {}), ('res.set', {'n': RESOLUTION_SF[resolution_hz]})]
        self._setup(steps, 'frequency setup')
        timeout = self.SLOW_FREQ_TIMEOUT_S if resolution_hz == 0.1 else self.DEFAULT_TIMEOUT
        value = self._trigger_read(timeout)
        self.check_status('frequency reading')
        return value

    def read_special(self, sf: str) -> float:
        """Display a special-function value and read it (UNVERIFIED mechanism): 15.1 -> 1 when an external time base is in use, 42.0 -> firmware date code, 37.4 -> number of cal-factor entries."""
        self.send('sf.display', sf=sf)
        return decode_reading(self._read_reading(self.DEFAULT_TIMEOUT))

    def time_base_is_external(self) -> bool:
        """15.1SP: 1 when the rear-panel 10 MHz reference is in use, 0 for the internal one (there is no command to choose; the receiver switches by itself)."""
        return self.read_special('15.1') >= 0.5     # NOT used by the procedure: on the owner's 8902A (2026-10-28) 15.1SP left the display showing 1 and locked the receiver until a preset

    def tuned_rf_level_dbm(self, carrier_mhz: float, detector: str = 'sync') -> float:
        """Tuned RF level in dBm (0 to -127 dBm): manual tune to the source frequency (within 50 kHz at 10 MHz and above), S4, LG, detector synchronous or average. The value is the LG
        reading taken as dBm (UNVERIFIED). Raises RecalRequired when RECAL / UNCAL (status bit 5) is set: call calibrate_tuned_level() with the level held constant."""
        if detector not in TUNED_DETECTOR_SF:
            raise InstrumentError(f'tuned-level detector {detector!r} is not one of {list(TUNED_DETECTOR_SF)}')
        self._setup([self._tune(carrier_mhz), ('func.tuned_level', {}), ('units.log', {}), ('det.tuned', {'n': TUNED_DETECTOR_SF[detector]})], 'tuned level setup')
        value = self._trigger_read(self.TUNED_TIMEOUT_S)
        st = self.check_status('tuned level reading')
        if st['recal_or_uncal']:
            raise RecalRequired(f'{self.MODEL}: RECAL / UNCAL after the tuned level reading {value:g}: calibrate_tuned_level({carrier_mhz:g}) at this level, then measure again')
        return value

    def calibrate_tuned_level(self, carrier_mhz: float, detector: str = 'sync') -> float:
        """C1 at a constant level (do not change the signal while it runs), T3, read; then C0. Returns the reading taken during the calibration. Locked command, sent once."""
        self._setup([self._tune(carrier_mhz), ('func.tuned_level', {}), ('units.log', {}), ('det.tuned', {'n': TUNED_DETECTOR_SF[detector]})], 'tuned level cal setup')
        try:
            self.send('cal.on')
            value = self._trigger_read(self.TUNED_TIMEOUT_S)
        finally:
            self.send('cal.off')
        self.check_status('tuned level calibration')
        return value

    def rf_power_dbm(self, carrier_mhz: float | None = None) -> float:
        """RF power in dBm with the power sensor module (M4, LG). Needs zero_power_sensor() and calibrate_power_sensor() first."""
        self._setup([self._tune(carrier_mhz), ('func.power', {}), ('units.log', {})], 'RF power setup')
        value = self._trigger_read(self.DEFAULT_TIMEOUT)
        self.check_status('RF power reading')
        return value

    def zero_power_sensor(self) -> float:
        """M4, ZR (about 15 s, no RF at the sensor and the CALIBRATE light off), then LN WT and a reading: the residual in watts (basic check: below 3 uW). Raises when above."""
        self._setup([('func.power', {}), ('units.lin', {}), ('units.watt', {})], 'zero setup')
        self.send('zero')
        value = self._trigger_read(self.DEFAULT_TIMEOUT + self.ZERO_WAIT_S)
        self.check_status('zero')
        if abs(value) > RF_POWER_ZERO_MAX_W:
            raise InstrumentError(f'{self.MODEL}: residual after ZR is {value:g} W (above {RF_POWER_ZERO_MAX_W:g} W, p. 3-49 / 101)')
        return value

    def calibrate_power_sensor(self) -> float:
        """The 1 mW 50 MHz power calibration (sensor on the RF POWER CALIBRATION OUTPUT): C1T3SC as one write (the manual's own string), C0, then a reading in watts: it must be between
        0.999 and 1.000 mW (p. 3-49 / 101). Locked commands, each sent once."""
        self._setup([('func.power', {}), ('units.lin', {}), ('units.watt', {})], 'power cal setup')
        try:
            self.send('cal.power')
        finally:
            self.send('cal.off')
        value = self._trigger_read(self.DEFAULT_TIMEOUT)
        self.check_status('power calibration')
        if not CAL_POWER_W[0] - 1e-9 <= round(value, 7) <= CAL_POWER_W[1] + 1e-9:
            raise InstrumentError(f'{self.MODEL}: after SC the sensor reads {value * 1e3:.4f} mW, not 0.999 to 1.000 mW')
        return value

    def enter_reference_cal_factor(self, percent: float) -> float:
        """Reference (50 MHz) cal factor of the power sensor (37.3SP <pct> CF), read back with 37.5SP CF (UNVERIFIED mechanism); the shown value must equal the entry within 0.05 %."""
        self.send('func.power')
        self.send('cf.ref', cf=float(percent))
        self.check_status('reference cal factor')
        self.send('cf.recall.ref')
        got = decode_reading(self._read_reading(self.DEFAULT_TIMEOUT))
        if abs(got - percent) > 0.05:
            raise InstrumentError(f'{self.MODEL}: reference cal factor {percent:g} % reads back as {got:g} %')
        return got

    def cal_factor_count(self) -> int:
        """37.4SP: the number of cal-factor entries including the reference (UNVERIFIED read mechanism)."""
        self.send('func.power')
        return int(round(self.read_special('37.4')))

    def enter_cal_factor(self, freq_mhz: float, percent: float) -> int:
        """One frequency / cal-factor pair (37.3SP <f> MZ <pct> CF; 16 allowed). Read back: the entry count (37.4SP) must be the old count (the frequency was already there) or one more.
        Returns the count."""
        before = self.cal_factor_count()
        self.send('cf.pair', mhz=float(freq_mhz), cf=float(percent))
        self.check_status('cal factor entry')
        after = self.cal_factor_count()
        if after not in (before, before + 1):
            raise InstrumentError(f'{self.MODEL}: cal-factor table has {after} entries after entering {freq_mhz:g} MHz (was {before}): the entry was not accepted')
        return after

    def _modulation(self, func_key, carrier_mhz, detector, hp, lp, extra=()):
        if detector not in DETECTORS:
            raise InstrumentError(f'detector D{detector!r} is not one of {list(DETECTORS)}')
        if hp not in (0, 1, 2) or lp not in (0, 1, 2, 3):
            raise InstrumentError(f'filters H{hp!r} / L{lp!r} are not H0..H2 / L0..L3')
        steps = [self._tune(carrier_mhz), (func_key, {}), ('det.set', {'n': str(detector)}), *extra, ('hp.set', {'n': str(hp)}), ('lp.set', {'n': str(lp)}), ('units.lin', {})]
        self._setup(steps, f'{func_key} setup')
        value = self._trigger_read(self.DEFAULT_TIMEOUT)
        self.check_status(f'{func_key} reading')
        return value

    def measure_am_percent(self, carrier_mhz: float | None = None, detector: int = 1, hp: int = 1, lp: int = 2) -> float:
        """AM depth in percent: tune, M1, detector (1 peak+ ... 9), high-pass H0..H2, low-pass L0..L3 (default 50 Hz to 15 kHz), T1 T3, read."""
        return self._modulation('func.am', carrier_mhz, detector, hp, lp)

    def measure_fm_deviation_hz(self, carrier_mhz: float | None = None, detector: int = 1, hp: int = 1, lp: int = 2, deemphasis_us: int | None = None) -> float:
        """FM deviation in Hz (the HP-IB result is in fundamental units; UNVERIFIED): as AM with M2, plus de-emphasis None (P0) or 25 / 50 / 75 / 750 us (P1 then P2..P5). True rms (D8)
        forces pre-display on, so no P0 is sent for it."""
        if deemphasis_us is not None and deemphasis_us not in DEEMPHASIS_US:
            raise InstrumentError(f'de-emphasis {deemphasis_us!r} us is not one of {list(DEEMPHASIS_US)} or None')
        if deemphasis_us is None:
            extra = [] if detector == 8 else [('deemph.set', {'n': '0'})]
        else:
            extra = [('deemph.set', {'n': '1'}), ('deemph.set', {'n': DEEMPHASIS_US[deemphasis_us]})]
        return self._modulation('func.fm', carrier_mhz, detector, hp, lp, extra)

    def measure_distortion(self, carrier_mhz: float | None = None, tone_hz: int = 1000, source: str = 'am', in_db: bool = False) -> float:
        """Audio distortion of the demodulated 'am' or 'fm' signal at a 1 kHz or 400 Hz tone, in percent (or dB with in_db). UNVERIFIED that S2 follows M1 / M2 this way."""
        if tone_hz not in (400, 1000) or source not in ('am', 'fm'):
            raise InstrumentError("distortion needs tone_hz 400 or 1000 and source 'am' or 'fm'")
        steps = [self._tune(carrier_mhz), (f'func.{source}', {}), ('func.distortion', {}), ('dist.set', {'n': '5' if tone_hz == 1000 else '6'}), ('units.log' if in_db else 'units.lin', {})]
        self._setup(steps, 'distortion setup')
        value = self._trigger_read(self.DEFAULT_TIMEOUT)
        self.check_status('distortion reading')
        return value

    def measure_modulation_rate_hz(self, carrier_mhz: float | None = None, source: str = 'am') -> float:
        """Audio frequency counter on the demodulated signal (S1 after M1 / M2), in Hz. UNVERIFIED (see the A0 / A1 remark)."""
        self._setup([self._tune(carrier_mhz), (f'func.{source}', {}), ('func.audio_freq', {})], 'audio frequency setup')
        value = self._trigger_read(self.DEFAULT_TIMEOUT)
        self.check_status('audio frequency reading')
        return value

    def calibrate_modulation(self, kind: str, limits=(99.0, 101.0)) -> float:
        """Receiver self-calibration of AM or FM: calibrator output connected to the RF input, M1 / M2, C1, wait CAL_WAIT_S (~20 s to the first factor), CF, read the factor (percent,
        100.00 = no error; UNVERIFIED read mechanism), then C0. The factor must be inside `limits` (99.00 to 101.00 is the AM pass band of the basic check, p. 3-51 / 103; the FM band is
        UNVERIFIED). The receiver should have been on for 30 minutes."""
        if kind not in ('am', 'fm'):
            raise InstrumentError("calibration kind must be 'am' or 'fm'")
        self._setup([(f'func.{kind}', {})], f'{kind} calibration setup')
        try:
            self.send('cal.on')
            time.sleep(self.CAL_WAIT_S)
            self.send('cf.display')
            factor = decode_reading(self._read_reading(self.DEFAULT_TIMEOUT + self.CAL_WAIT_S))
        finally:
            self.send('cal.off')
        self.check_status(f'{kind} calibration')
        if not limits[0] <= factor <= limits[1]:
            raise InstrumentError(f'{self.MODEL}: {kind.upper()} calibration factor {factor:g} % is outside {limits[0]:g} to {limits[1]:g} %')
        return factor
