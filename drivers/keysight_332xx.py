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

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError

HIGH_Z = 9.9e37
UNITS = ('VPP', 'VRMS', 'DBM')
FUNCS = {'SIN': 'SIN', 'SQU': 'SQU'}

_REF = "33210A/33220A/33250A User's Guide"


def _ref(topic, p210, p220, p250):
    return f"{_REF}: {topic} (pp. {p210} / {p220} / {p250})"


# Every command the driver sends (same text and format specs the old f-strings used). All of them are taken from the User's Guides and
# have NOT been run on hardware (NOTES.md), so verified=False throughout. OUTP ON / OUTP OFF / OUTP? change or confirm the output state
# (risk 'output'); *CLS, SYST:ERR? and *TST? are bootstrap / error-queue / self-test plumbing (risk 'locked'). Neither kind can be overridden.
# APPLy is deliberately absent: it switches the output on by itself.
COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'err.query': Cmd('SYST:ERR?', 'Error queue', "Oldest error; '+0,\"No error\"' when empty (never overridable)", kind='query',
                     risk='locked', verified=False),
    'selftest': Cmd('*TST?', 'Self-test', 'Runs the self-test: 0 pass / 1 fail (never overridable)', kind='query', risk='locked',
                    verified=False, ref=_ref('*TST?', 141, 131, 114)),
    'outp.on': Cmd('OUTP ON', 'Output on', 'Enables the output (never overridable)', kind='set', readback='outp.query', risk='output',
                   verified=False, ref=_ref('OUTPut', 82, 67, 60)),
    'outp.off': Cmd('OUTP OFF', 'Output off', 'Disables the output (never overridable)', kind='set', readback='outp.query', risk='output',
                    verified=False, ref=_ref('OUTPut', 82, 67, 60)),
    'outp.query': Cmd('OUTP?', 'Output state', 'Returns 0 or 1 (never overridable)', kind='query', risk='output', verified=False,
                      ref=_ref('OUTPut?', 82, 67, 60)),
    'load.inf': Cmd('OUTP:LOAD INF', 'Output termination High Z', 'OUTP:LOAD? returns 9.9E+37 for High Z', kind='set',
                    readback='load.query', verified=False, ref=_ref('OUTPut:LOAD', 78, 63, 57)),
    'load.ohms': Cmd('OUTP:LOAD {load:g}', 'Output termination (ohm)', 'Load in ohm (50)',
                     placeholders={'load': Placeholder('float', 'g', 50.0)}, kind='set', readback='load.query', verified=False,
                     ref=_ref('OUTPut:LOAD', 78, 63, 57)),
    'load.query': Cmd('OUTP:LOAD?', 'Output termination', kind='query', verified=False, ref=_ref('OUTPut:LOAD?', 78, 63, 57)),
    'unit.vrms': Cmd('VOLT:UNIT VRMS', 'Amplitude unit Vrms', 'Sent first: dBm is refused while the load is High Z', kind='set',
                     readback='unit.query', verified=False, ref=_ref('VOLTage:UNIT', 77, 62, 56)),
    'unit.set': Cmd('VOLT:UNIT {unit}', 'Amplitude unit', 'VPP, VRMS or DBM (dBm is refused at High Z)',
                    placeholders={'unit': Placeholder('enum', '', 'VPP', enum=UNITS)}, kind='set', readback='unit.query', verified=False,
                    ref=_ref('VOLTage:UNIT', 77, 62, 56)),
    'unit.query': Cmd('VOLT:UNIT?', 'Amplitude unit', kind='query', verified=False, ref=_ref('VOLTage:UNIT?', 77, 62, 56)),
    'func.set': Cmd('FUNC {func}', 'Waveform', 'SIN or SQU', placeholders={'func': Placeholder('enum', '', 'SIN', enum=tuple(FUNCS.values()))},
                    kind='set', readback='func.query', verified=False, ref=_ref('FUNCtion', 71, 56, 153)),
    'func.query': Cmd('FUNC?', 'Waveform', kind='query', verified=False, ref=_ref('FUNCtion?', 71, 56, 153)),
    'offs.zero': Cmd('VOLT:OFFS 0', 'DC offset 0 V', kind='set', readback='offs.query', verified=False, ref=_ref('VOLTage:OFFSet', 76, 61, 55)),
    'offs.query': Cmd('VOLT:OFFS?', 'DC offset', kind='query', verified=False, ref=_ref('VOLTage:OFFSet?', 76, 61, 55)),
    'autorange.on': Cmd('VOLT:RANG:AUTO ON', 'Amplitude autorange on', kind='set', readback='autorange.query', verified=False,
                        ref=_ref('VOLTage:RANGe:AUTO', 81, 66, 60)),
    'autorange.query': Cmd('VOLT:RANG:AUTO?', 'Amplitude autorange', kind='query', verified=False, ref=_ref('VOLTage:RANGe:AUTO?', 81, 66, 60)),
    'freq.set': Cmd('FREQ {frequency:.12g}', 'Frequency', 'Hz', placeholders={'frequency': Placeholder('float', '.12g', 1000.0)}, kind='set',
                    readback='freq.query', verified=False, ref=_ref('FREQuency', 73, 58, 52)),
    'freq.query': Cmd('FREQ?', 'Frequency', kind='query', verified=False, ref=_ref('FREQuency?', 73, 58, 52)),
    'volt.set': Cmd('VOLT {amplitude:.6g}', 'Amplitude', 'In the unit selected with VOLT:UNIT',
                    placeholders={'amplitude': Placeholder('float', '.6g', 1.0)}, kind='set', readback='volt.query', verified=False),
    'volt.query': Cmd('VOLT?', 'Amplitude', kind='query', verified=False),
}


class Keysight332xx(Instrument):
    MODEL = 'Keysight 332xx'
    IDN_MATCH = ()
    DEFAULT_TIMEOUT = 15.0
    SELFTEST_TIMEOUT = 90.0
    MAX_SINE_HZ = 0.0
    COMMANDS = COMMANDS

    output_off_confirmed = False

    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.output(False)
        self.check_errors('connect')
        return self

    # ---- error queue ---------------------------------------------------------------------------------
    def check_errors(self, context=''):
        """SYSTem:ERRor? -> '+0,"No error"' when empty. Raise with the first error otherwise."""
        reply = self.ask('err.query').strip()
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
            reply = self.ask('selftest').strip()
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        try:
            passed = int(float(reply)) == 0
        except ValueError:
            raise InstrumentError(f'Unexpected *TST? reply: {reply!r}')
        detail = ''
        if not passed:
            detail = self.ask('err.query').strip()
        else:
            self.check_errors('self-test')
        self.output(False)
        return passed, detail

    # ---- settings (write, read back, compare) --------------------------------------------------------
    def _wire(self, key, **vals):
        """The factory text of a command with its values filled in (for error messages)."""
        return cmdreg.render(self._registry()[key], vals)

    def _set_text(self, key, query, want, what, **vals):
        self.send(key, **vals)
        got = self.ask(query, **vals).strip().strip('"').upper()
        if not got.startswith(want):
            raise InstrumentError(f'{self.MODEL} {what}: set {self._wire(key, **vals)!r}, reports {got!r}')

    def _set_number(self, key, query, want, what, rel=1e-6, abs_=1e-9, **vals):
        self.send(key, **vals)
        got = float(self.ask(query, **vals).strip())
        if not math.isclose(got, want, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{self.MODEL} {what}: set {want:g}, reports {got:g}')
        return got

    def set_load(self, load):
        """'INF' (High Z) or 50 ohms."""
        if str(load).upper().startswith('INF'):
            self.send('load.inf')
            got = float(self.ask('load.query').strip())
            if got < 1e37:
                raise InstrumentError(f'{self.MODEL} output termination: set High Z, reports {got:g} ohm')
        else:
            self._set_number('load.ohms', 'load.query', float(load), 'output termination', load=float(load))

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
        self._set_text('unit.vrms', 'unit.query', 'VRMS', 'amplitude units')   # dBm is refused at High Z: leave it first
        self.set_load(load)
        self._set_text('func.set', 'func.query', func, 'function', func=func)
        self._set_number('offs.zero', 'offs.query', 0.0, 'dc offset', abs_=1e-6)
        self._set_text('autorange.on', 'autorange.query', '1', 'amplitude autorange')
        if unit != 'VRMS':
            self._set_text('unit.set', 'unit.query', unit, 'amplitude units', unit=unit)
        self._set_number('freq.set', 'freq.query', frequency, 'frequency', rel=1e-9, abs_=1e-6, frequency=frequency)
        self._set_number('volt.set', 'volt.query', amplitude, 'amplitude', rel=1e-4, abs_=5e-3 if unit == 'DBM' else 1e-5, amplitude=amplitude)
        self.check_errors(f'{func} {frequency:g} Hz {amplitude:g} {unit}')

    def output(self, on: bool):
        """OUTP ON / OFF, confirmed with OUTP?. An unconfirmed OFF is a SafetyError."""
        self.send('outp.on' if on else 'outp.off')
        state = self.ask('outp.query').strip()
        if state != ('1' if on else '0'):
            if on:
                raise InstrumentError(f'{self.MODEL} did not confirm output ON (OUTP? -> {state!r})')
            raise SafetyError(f'{self.MODEL} did not confirm output OFF (OUTP? -> {state!r}); check the front panel')

    def cleanup(self):
        """Best effort: output OFF. Never raises."""
        try:
            self.send('outp.off')
            self.output_off_confirmed = self.ask('outp.query').strip() == '0'
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
