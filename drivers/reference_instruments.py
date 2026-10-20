"""Stimulus and reference instruments used with the MDO4000C procedure.

Fluke96270A      RF reference source (RF section: phase noise, amplitude, IMD, crosstalk, TPA functional check)
AgilentAFG       Agilent/Keysight 33220A (20 MHz) and 32250A (250 MHz) function / arbitrary generators
ReferenceMeter   any SCPI DMM or frequency counter (AFG frequency / amplitude / offset checks)

Every setter reads the value back and compares it; none of them is retried. RF and generator outputs are switched OFF at cleanup.
The 96270A command names are in RF_CMD. They were checked against the 96000 Series Remote Programmers Manual (April 2014 Rev. 2):
INSTrument (p38), OUTPut (p39), POWer (p41), FREQuency (p42), UNIT (p53), SYSTem:ERRor (p55), *IDN? (p57), coupled commands (p60-62).
"""
from __future__ import annotations

import math
import re
import time

from .base import Instrument, InstrumentError, SafetyError

RF_CMD = dict(
    inst='INST SINE', inst_q='INST?',                       # SINE is the leveled-sine logical instrument (p38)
    unit='UNIT:POW DBM', unit_q='UNIT:POW?',                # level commands are in the units set here, not always dBm (p53)
    poffs='POW:OFFS:STAT 0', poffs_q='POW:OFFS:STAT?',      # a front-panel offset would shift the real output (p41)
    foffs='FREQ:OFFS:STAT 0', foffs_q='FREQ:OFFS:STAT?',    # same for frequency (p42)
    freq_level='FREQ {f:.12g};:POW {p:.3f}',                # one message so the source applies its frequency/power coupling (p60-62)
    freq_q='FREQ?', level_q='POW?',
    on='OUTP ON', off='OUTP OFF', state_q='OUTP?',          # OUTP[:STATe] <bool> (p39)
    err_q='SYST:ERR?')                                      # "0" when the queue is empty (p55)


def _bool_reply(reply: str) -> bool:
    r = reply.strip().upper()
    if r in ('1', 'ON'):
        return True
    if r in ('0', 'OFF'):
        return False
    raise InstrumentError(f'unexpected boolean reply {reply!r}')


class Fluke96270A(Instrument):
    MODEL = 'Fluke 96270A'
    IDN_MATCH = ('96270',)          # *IDN? reply is "Fluke,96270A,<serial>,<firmware>" (p57); a plain 'FLUKE' would also accept a 5560A
    DEFAULT_TIMEOUT = 15.0
    MAX_HZ = 6.2e9                  # limit for the MDO4000C RF tests, not the instrument's own range

    output_off_confirmed = False

    def connect(self):
        """Open, clear status, then put the source in a known state: SINE instrument, levels in dBm, no offsets, output off.
        Selecting the instrument also puts the output into standby (p38). Each setting is read back."""
        self.open(verify_model=True)
        self.write('*CLS')
        self._set_and_check(RF_CMD['inst'], RF_CMD['inst_q'], lambda r: r.strip().strip('"').upper() == 'SINE', 'instrument SINE')
        self._set_and_check(RF_CMD['unit'], RF_CMD['unit_q'], lambda r: r.strip().strip('"').upper() == 'DBM', 'power units DBM')
        self._set_and_check(RF_CMD['poffs'], RF_CMD['poffs_q'], lambda r: not _bool_reply(r), 'power offset off')
        self._set_and_check(RF_CMD['foffs'], RF_CMD['foffs_q'], lambda r: not _bool_reply(r), 'frequency offset off')
        self.output(False)
        return self

    def _set_and_check(self, cmd, query, ok, what):
        self.write(cmd)
        reply = self.query(query)
        if not ok(reply):
            raise InstrumentError(f'96270A {what}: set {cmd!r}, reports {reply.strip()!r}')
        self.check_error(what)

    def check_error(self, context=''):
        """Raise if the source rejected a command. SYST:ERR? returns 0 when the queue is empty."""
        reply = self.query(RF_CMD['err_q']).strip()
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            failed = int(float(code)) != 0
        except ValueError:
            failed = True
        if failed:
            raise InstrumentError(f'96270A rejected the setting{" (" + context + ")" if context else ""}: {reply}')

    def set_rf(self, frequency_hz, level_dbm):
        if frequency_hz > self.MAX_HZ:
            raise InstrumentError(f'{frequency_hz / 1e9:g} GHz is above the {self.MODEL} range')
        self.write(RF_CMD['freq_level'].format(f=frequency_hz, p=level_dbm))
        self.check_error(f'{frequency_hz:g} Hz, {level_dbm:g} dBm')
        got = float(self.query(RF_CMD['freq_q']).strip().split()[0])
        if not math.isclose(got, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A frequency set {frequency_hz:g}, reports {got:g}')
        lvl = float(self.query(RF_CMD['level_q']).strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A level set {level_dbm:g} dBm, reports {lvl:g} dBm')

    def output(self, on: bool):
        """OUTP ON/OFF, then read OUTP? and compare. Not confirming OFF is a SafetyError."""
        self.write(RF_CMD['on'] if on else RF_CMD['off'])
        state = _bool_reply(self.query(RF_CMD['state_q']))
        if state != on:
            if on:
                raise InstrumentError('96270A did not confirm output ON')
            raise SafetyError('96270A did not confirm output OFF; check the front panel')

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.write(RF_CMD['off'])
            self.output_off_confirmed = not _bool_reply(self.query(RF_CMD['state_q']))
        except Exception:
            self.output_off_confirmed = False


class AgilentAFG(Instrument):
    MODEL = 'Agilent 33220A / 32250A'
    IDN_MATCH = ('33220', '32250')
    DEFAULT_TIMEOUT = 10.0
    MAX_SINE_HZ = {'33220': 20e6, '32250': 250e6}

    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.idn = self.identify()
        self.kind = '32250' if '32250' in self.idn else '33220'
        return self

    @property
    def max_hz(self):
        return self.MAX_SINE_HZ[self.kind]

    def sine(self, frequency_hz, vpp, load='50'):
        """Sine wave, amplitude in Vpp into the stated load, offset 0 V. Output stays OFF until output(True)."""
        if frequency_hz > self.max_hz:
            raise InstrumentError(f'{frequency_hz / 1e6:g} MHz is above the {self.kind} sine range ({self.max_hz / 1e6:g} MHz)')
        self.write('OUTPut OFF')
        self.write(f'OUTPut:LOAD {50 if load == "50" else "INF"}')
        self.write(f'APPLy:SINusoid {frequency_hz:.9g},{vpp:.9g},0')
        self._verify(frequency_hz, vpp)

    def square(self, frequency_hz, vpp, load='50'):
        self.write('OUTPut OFF')
        self.write(f'OUTPut:LOAD {50 if load == "50" else "INF"}')
        self.write(f'APPLy:SQUare {frequency_hz:.9g},{vpp:.9g},0')
        self._verify(frequency_hz, vpp)

    def _verify(self, frequency_hz, vpp):
        f = float(self.query('FREQuency?').strip())
        a = float(self.query('VOLTage?').strip())
        if not math.isclose(f, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'{self.kind} frequency set {frequency_hz:g}, reports {f:g}')
        if not math.isclose(a, vpp, rel_tol=1e-3, abs_tol=1e-4):
            raise InstrumentError(f'{self.kind} amplitude set {vpp:g} Vpp, reports {a:g}')
        err = self.query('SYSTem:ERRor?').strip()
        if not err.startswith(('+0', '0')):
            raise InstrumentError(f'{self.kind} rejected the setting: {err}')

    def output(self, on: bool):
        self.write('OUTPut ON' if on else 'OUTPut OFF')

    def cleanup(self):
        try:
            self.write('OUTPut OFF')
        except Exception:
            pass


class ReferenceMeter(Instrument):
    """Generic SCPI DMM / counter for the AFG checks."""
    MODEL = 'SCPI reference meter'
    IDN_MATCH = ()
    DEFAULT_TIMEOUT = 20.0

    def connect(self):
        self.open(verify_model=False)
        self.write('*CLS')
        self.idn = self.identify()
        return self

    def _num(self, cmd):
        raw = self.query(cmd).strip().split(',')[0]
        v = float(raw)
        if not math.isfinite(v) or abs(v) > 1e35:
            raise InstrumentError(f'Invalid reading from {cmd}: {raw}')
        return v

    def frequency(self):
        return self._num('MEASure:FREQuency?')

    def ac_rms(self):
        self.write('CONFigure:VOLTage:AC')
        self.write('VOLTage:AC:BANDwidth 200')
        time.sleep(3.0)
        return self._num('READ?')

    def power(self):
        """Power meter reading in dBm."""
        return self._num('MEASure:POWer?')

    def dc(self):
        self.write('CONFigure:VOLTage:DC')
        time.sleep(1.0)
        return self._num('READ?')
