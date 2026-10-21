"""Agilent / HP 53131A and 53132A 225 MHz universal counters - frequency measurements for the calibration procedures.

Commands are from the 53131A/132A Universal Counter Programming Guide (part 53131-90044, October 2006):
  *IDN? (p. 4-130)  *TST? (p. 4-142)  :SYSTem:ERRor? (p. 4-116)
  :INPut[1|2]:IMPedance 50 | 1E6, :COUPling AC | DC (pp. 4-48, 4-49)
  [:SENSe]:FUNCtion "FREQ <ch>" and its query reply "FREQ" / "FREQ 2" (pp. 4-89, 4-90)
  [:SENSe]:FREQuency:ARM:STARt:SOURce IMM, :STOP:SOURce TIM, :STOP:TIMer <s> (pp. 4-86, 4-87); gate 1 ms to 1000 s
  [:SENSe]:FREQuency:EXPected[1|2|3] <Hz> - skips the automatic pre-measurement; the signal must be within 10 % (p. 4-88)
  [:SENSe]:ROSCillator:SOURce INT | EXT, :SOURce:AUTO, :EXTernal:CHECk ON | OFF | ONCE, :EXTernal:FREQuency? (pp. 4-92 to 4-94);
  errors +2009 (no valid external timebase) and +2010 (external timebase failed during a measurement), p. 5-10; the 53132A accepts only a 10 MHz
  external reference
  READ? = INIT + FETCH? (pp. 4-52, 4-53; example p. 3-62); no valid result gives Not a Number 9.91E37 and error -230 (p. 4-7)
Every setting is written, read back and compared; the error queue is checked after each configuration. READ? is never retried.
"""
from __future__ import annotations

import math

from .base import Instrument, InstrumentError

NAN_REPLY = 9.9e37            # the counter's Not a Number is 9.91E37


class Keysight5313x(Instrument):
    MODEL = 'Agilent 53131A / 53132A'
    IDN_MATCH = ('53131A', '53132A')
    DEFAULT_TIMEOUT = 20.0
    MAX_HZ = 225e6             # channels 1 and 2 (p. 4-88); channel 3 is an option and is not used here
    SELFTEST_TIMEOUT = 60.0

    gate_s = 0.1

    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.check_errors('connect')
        return self

    # ---- errors / self-test --------------------------------------------------------------------------
    def check_errors(self, context=''):
        """:SYST:ERR? -> '+0,"No error"' when the queue is empty (p. 4-116)."""
        reply = self.query(':SYST:ERR?').strip()
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            failed = int(code) != 0
        except ValueError:
            failed = True
        if failed:
            raise InstrumentError(f'{self.MODEL} reported an error{" (" + context + ")" if context else ""}: {reply}')

    def self_test(self):
        """*TST? -> 0 when no errors were found (p. 4-142). Returns (passed, error text)."""
        self.t.set_timeout(self.SELFTEST_TIMEOUT)
        try:
            reply = self.query('*TST?').strip()
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        passed = reply.lstrip('+') == '0'
        return passed, '' if passed else self.query(':SYST:ERR?').strip()

    # ---- settings (write, read back, compare) --------------------------------------------------------
    def _text(self, cmd, query, want, what):
        self.write(cmd)
        got = self.query(query).strip().strip('"').upper()
        if got != want:
            raise InstrumentError(f'{self.MODEL} {what}: set {cmd!r}, reports {got!r}')

    def _number(self, cmd, query, want, what, rel=1e-6):
        self.write(cmd)
        got = float(self.query(query).strip())
        if not math.isclose(got, want, rel_tol=rel):
            raise InstrumentError(f'{self.MODEL} {what}: set {want:g}, reports {got:g}')

    def configure_frequency(self, channel=1, gate_s=1.0, impedance=50, coupling='AC', expected_hz=None):
        """Frequency on channel 1 or 2 with a timed gate. impedance 50 or 1e6 ohm; expected_hz (optional) must be within 10 %
        of the signal and removes the automatic pre-measurement."""
        if channel not in (1, 2):
            raise InstrumentError('channel must be 1 or 2')
        if not 1e-3 <= gate_s <= 1000:
            raise InstrumentError(f'gate time {gate_s:g} s is outside 1 ms to 1000 s')
        if impedance not in (50, 1e6):
            raise InstrumentError('input impedance must be 50 or 1e6 ohm')
        self._text(f':FUNC "FREQ {channel}"', ':FUNC?', 'FREQ' if channel == 1 else f'FREQ {channel}', 'function')
        self._number(f':INP{channel}:IMP {impedance:g}', f':INP{channel}:IMP?', float(impedance), 'input impedance')
        self._text(f':INP{channel}:COUP {coupling.upper()}', f':INP{channel}:COUP?', coupling.upper(), 'input coupling')
        self._text(':FREQ:ARM:STAR:SOUR IMM', ':FREQ:ARM:STAR:SOUR?', 'IMM', 'start arm')
        self._text(':FREQ:ARM:STOP:SOUR TIM', ':FREQ:ARM:STOP:SOUR?', 'TIM', 'stop arm')
        self._number(f':FREQ:ARM:STOP:TIM {gate_s:g}', ':FREQ:ARM:STOP:TIM?', gate_s, 'gate time', rel=1e-5)
        if expected_hz is not None:
            if not 0.1 <= expected_hz <= self.MAX_HZ:
                raise InstrumentError(f'expected frequency {expected_hz:g} Hz is outside 0.1 Hz to {self.MAX_HZ / 1e6:g} MHz')
            self._number(f':FREQ:EXP{channel} {expected_hz:.12g}', f':FREQ:EXP{channel}?', expected_hz, 'expected frequency', rel=1e-9)
        self.check_errors(f'frequency setup, channel {channel}')
        self.gate_s = gate_s

    def reference(self):
        """('INT' | 'EXT', auto-select on?) - the timebase in use (p. 4-93: the query reports the auto selection too)."""
        src = self.query(':ROSC:SOUR?').strip().upper()
        auto = self.query(':ROSC:SOUR:AUTO?').strip() == '1'
        return src, auto

    EXT_REF_HZ = (1e6, 5e6, 10e6)     # 53131A; the 53132A accepts 10 MHz only (p. 4-92)

    def set_reference(self, source):
        """'INT' or 'EXT'. Explicit selection turns auto-select off (p. 4-94). For EXT: CHECk ONCE tests Ref In now (error +2009
        if there is no valid reference, pp. 4-92, 4-93; errors +2009 / +2010 p. 5-10), then CHECk ON makes the counter re-check the reference at the
        end of every measurement, and ROSC:EXT:FREQ? must report an accepted frequency. Returns the external frequency or None."""
        source = source.upper()
        if source not in ('INT', 'EXT'):
            raise InstrumentError('reference must be INT or EXT')
        self._text(f':ROSC:SOUR {source}', ':ROSC:SOUR?', source, 'reference oscillator')
        if source == 'INT':
            self.check_errors('reference INT')
            return None
        self.write(':ROSC:EXT:CHEC ONCE')
        reply = self.query(':SYST:ERR?').strip()
        if reply.split(',')[0].strip().lstrip('+') != '0':
            if reply.lstrip('+').startswith('2009'):
                raise InstrumentError(f'{self.MODEL}: no valid external timebase at Ref In (+2009). Check the 10 MHz GPS reference '
                                      'cable on the rear panel and that the GPS receiver is locked.')
            raise InstrumentError(f'{self.MODEL} reported an error (external reference check): {reply}')
        self._text(':ROSC:EXT:CHEC ON', ':ROSC:EXT:CHEC?', 'ON', 'external reference checking')
        f = float(self.query(':ROSC:EXT:FREQ?').strip())
        allowed = (10e6,) if '53132A' in (self.idn or '') else self.EXT_REF_HZ
        if f > NAN_REPLY or not any(math.isclose(f, a, rel_tol=1e-3) for a in allowed):
            raise InstrumentError(f'{self.MODEL}: external reference frequency reported as {f:g} Hz; expected '
                                  + ' / '.join(f'{a / 1e6:g} MHz' for a in allowed) + ' at Ref In.')
        self.check_errors('reference EXT')
        return f

    # ---- measurement ---------------------------------------------------------------------------------
    def read_frequency(self):
        """READ? -> Hz. Not a Number (no signal or no valid result) raises. The timeout allows for the gate."""
        self.t.set_timeout(max(self.DEFAULT_TIMEOUT, self.gate_s * 3 + 10))
        try:
            reply = self.query('READ?').strip()
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        value = float(reply.split(',')[0])
        err = self.query(':SYST:ERR?').strip()
        code = err.split(',')[0].strip().lstrip('+')
        if code in ('2009', '2010'):
            raise InstrumentError(f'{self.MODEL}: the external timebase was lost during the measurement ({err}). Check the GPS reference.')
        if not math.isfinite(value) or value > NAN_REPLY:
            raise InstrumentError(f'{self.MODEL}: no valid frequency (READ? -> {reply}); check the signal and the input setup.')
        if code != '0':
            raise InstrumentError(f'{self.MODEL} reported an error (frequency reading): {err}')
        return value

    def frequency(self):
        """Same name as ReferenceMeter.frequency(), so procedures can use either."""
        return self.read_frequency()

    def cleanup(self):
        """Nothing to switch off: the counter has no output. Never raises."""


class Keysight53131A(Keysight5313x):
    MODEL = 'Agilent 53131A'
    IDN_MATCH = ('53131A',)


class Keysight53132A(Keysight5313x):
    MODEL = 'Agilent 53132A'
    IDN_MATCH = ('53132A',)
