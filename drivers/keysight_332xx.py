"""Keysight / Agilent 33210A, 33220A and 33250A function generators - the instrument under test in the generator procedures.

Commands are the same on all three models (User's Guides, Chapter 3 "Features and Functions" / Chapter 4 reference):
                          33210A   33220A   33250A        (printed page numbers)
  FUNCtion                  71       56       153
  FREQuency                 73       58        52
  VOLTage:OFFSet            76       61        55
  VOLTage:UNIT              77       62        56     dBm is refused while OUTPut:LOAD is INFinity (High Z)
  OUTPut:LOAD               78       63        57     OUTP:LOAD? returns 9.9E+37 for High Z
  VOLTage:RANGe:AUTO        81       66        60
  OUTPut / OUTPut?          82       67        60     OUTP? returns 0 or 1
  *TST?                    141      131       114     returns 0 (pass) or 1 (fail)
APPLy is NOT used: it switches the output ON by itself (33220A User's Guide p. 188, under OUTPut). Each setting is sent on its own with the output OFF,
read back and compared; the output is switched on only by output(True), and every switch is confirmed with OUTP?.
"""
from __future__ import annotations

import math

from .base import Instrument, InstrumentError, SafetyError

HIGH_Z = 9.9e37
UNITS = ('VPP', 'VRMS', 'DBM')
FUNCS = {'SIN': 'SIN', 'SQU': 'SQU'}


class Keysight332xx(Instrument):
    MODEL = 'Keysight 332xx'
    IDN_MATCH = ()
    DEFAULT_TIMEOUT = 15.0
    SELFTEST_TIMEOUT = 90.0
    MAX_SINE_HZ = 0.0

    output_off_confirmed = False

    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.output(False)
        self.check_errors('connect')
        return self

    # ---- error queue ---------------------------------------------------------------------------------
    def check_errors(self, context=''):
        """SYSTem:ERRor? -> '+0,"No error"' when empty. Raise with the first error otherwise."""
        reply = self.query('SYST:ERR?').strip()
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            failed = int(code) != 0
        except ValueError:
            failed = True
        if failed:
            raise InstrumentError(f'{self.MODEL} reported an error{" (" + context + ")" if context else ""}: {reply}')

    # ---- self-test -----------------------------------------------------------------------------------
    def self_test(self):
        """*TST? -> 0 pass / 1 fail. Returns (passed, first error message or ''). The output is left OFF."""
        self.output(False)
        self.t.set_timeout(self.SELFTEST_TIMEOUT)
        try:
            reply = self.query('*TST?').strip()
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        try:
            passed = int(float(reply)) == 0
        except ValueError:
            raise InstrumentError(f'Unexpected *TST? reply: {reply!r}')
        detail = ''
        if not passed:
            detail = self.query('SYST:ERR?').strip()
        else:
            self.check_errors('self-test')
        self.output(False)
        return passed, detail

    # ---- settings (write, read back, compare) --------------------------------------------------------
    def _set_text(self, cmd, query, want, what):
        self.write(cmd)
        got = self.query(query).strip().strip('"').upper()
        if not got.startswith(want):
            raise InstrumentError(f'{self.MODEL} {what}: set {cmd!r}, reports {got!r}')

    def _set_number(self, cmd, query, want, what, rel=1e-6, abs_=1e-9):
        self.write(cmd)
        got = float(self.query(query).strip())
        if not math.isclose(got, want, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{self.MODEL} {what}: set {want:g}, reports {got:g}')
        return got

    def set_load(self, load):
        """'INF' (High Z) or 50 ohms."""
        if str(load).upper().startswith('INF'):
            self.write('OUTP:LOAD INF')
            got = float(self.query('OUTP:LOAD?').strip())
            if got < 1e37:
                raise InstrumentError(f'{self.MODEL} output termination: set High Z, reports {got:g} ohm')
        else:
            self._set_number(f'OUTP:LOAD {float(load):g}', 'OUTP:LOAD?', float(load), 'output termination')

    def setup(self, function, frequency, amplitude, unit, load):
        """Configure a test point with the output OFF: termination, waveform, 0 V offset, autorange on, units,
        frequency and amplitude. Every value is read back; the error queue is checked at the end."""
        unit = unit.upper()
        if unit not in UNITS:
            raise InstrumentError(f'amplitude unit must be one of {UNITS}')
        func = FUNCS[function.upper()[:3]]
        if func == 'SIN' and frequency > self.MAX_SINE_HZ:
            raise InstrumentError(f'{frequency / 1e6:g} MHz is above the {self.MODEL} sine range ({self.MAX_SINE_HZ / 1e6:g} MHz)')
        self.output(False)
        self._set_text('VOLT:UNIT VRMS', 'VOLT:UNIT?', 'VRMS', 'amplitude units')   # dBm is refused at High Z: leave it first
        self.set_load(load)
        self._set_text(f'FUNC {func}', 'FUNC?', func, 'function')
        self._set_number('VOLT:OFFS 0', 'VOLT:OFFS?', 0.0, 'dc offset', abs_=1e-6)
        self._set_text('VOLT:RANG:AUTO ON', 'VOLT:RANG:AUTO?', '1', 'amplitude autorange')
        if unit != 'VRMS':
            self._set_text(f'VOLT:UNIT {unit}', 'VOLT:UNIT?', unit, 'amplitude units')
        self._set_number(f'FREQ {frequency:.12g}', 'FREQ?', frequency, 'frequency', rel=1e-9, abs_=1e-6)
        self._set_number(f'VOLT {amplitude:.6g}', 'VOLT?', amplitude, 'amplitude', rel=1e-4, abs_=5e-3 if unit == 'DBM' else 1e-5)
        self.check_errors(f'{func} {frequency:g} Hz {amplitude:g} {unit}')

    def output(self, on: bool):
        """OUTP ON / OFF, confirmed with OUTP?. An unconfirmed OFF is a SafetyError."""
        self.write('OUTP ON' if on else 'OUTP OFF')
        state = self.query('OUTP?').strip()
        if state != ('1' if on else '0'):
            if on:
                raise InstrumentError(f'{self.MODEL} did not confirm output ON (OUTP? -> {state!r})')
            raise SafetyError(f'{self.MODEL} did not confirm output OFF (OUTP? -> {state!r}); check the front panel')

    def cleanup(self):
        """Best effort: output OFF. Never raises."""
        try:
            self.write('OUTP OFF')
            self.output_off_confirmed = self.query('OUTP?').strip() == '0'
        except Exception:
            self.output_off_confirmed = False


class Keysight33210A(Keysight332xx):
    MODEL = 'Keysight 33210A'
    IDN_MATCH = ('33210A',)
    MAX_SINE_HZ = 10e6


class Keysight33220A(Keysight332xx):
    MODEL = 'Agilent 33220A'
    IDN_MATCH = ('33220A',)
    MAX_SINE_HZ = 20e6


class Keysight33250A(Keysight332xx):
    MODEL = 'Agilent 33250A'
    IDN_MATCH = ('33250A',)
    MAX_SINE_HZ = 80e6
