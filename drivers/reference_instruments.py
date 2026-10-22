"""Stimulus and reference instruments used with the MDO4000C procedure.

Fluke96270A      RF reference source (RF section: phase noise, amplitude, IMD, crosstalk, TPA functional check)
AgilentAFG       Agilent/Keysight 33220A (20 MHz) and 33250A (80 MHz) function / arbitrary generators
ReferenceMeter   any SCPI DMM or frequency counter (AFG frequency / amplitude / offset checks)

Every setter reads the value back and compares it; none of them is retried. RF and generator outputs are switched OFF at cleanup.
The 96270A command names are in RF_COMMANDS. They were checked against the 96000 Series Remote Programmers Manual (April 2014 Rev. 2):
INSTrument (p38), OUTPut (p39), POWer (p41), FREQuency (p42), UNIT (p53), SYSTem:ERRor (p55), *IDN? (p57), coupled commands (p60-62).
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError

_RF = '96000 Series Remote Programmers Manual (April 2014 Rev. 2)'


def _rf(topic, page):
    return f'{_RF}: {topic} (p. {page})'


# Fluke 96270A. The command names were checked against the manual, not run on hardware, so verified=False throughout. OUTP ON / OUTP OFF /
# OUTP? change or confirm the RF output (risk 'output'); *CLS and SYST:ERR? are bootstrap / error-queue plumbing (risk 'locked').
# Neither kind can be overridden.
RF_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'inst.set': Cmd('INST SINE', 'Select the leveled-sine instrument', 'SINE is the leveled-sine logical instrument; selecting it also puts the output into standby',
                    kind='set', readback='inst.query', verified=False, ref=_rf('INSTrument', 38)),
    'inst.query': Cmd('INST?', 'Selected instrument', kind='query', verified=False, ref=_rf('INSTrument?', 38)),
    'unit.set': Cmd('UNIT:POW DBM', 'Power units dBm', 'Level commands are in the units set here, not always dBm', kind='set',
                    readback='unit.query', verified=False, ref=_rf('UNIT', 53)),
    'unit.query': Cmd('UNIT:POW?', 'Power units', kind='query', verified=False, ref=_rf('UNIT', 53)),
    'poffs.set': Cmd('POW:OFFS:STAT 0', 'Power offset off', 'A front-panel offset would shift the real output', kind='set',
                     readback='poffs.query', verified=False, ref=_rf('POWer', 41)),
    'poffs.query': Cmd('POW:OFFS:STAT?', 'Power offset state', kind='query', verified=False, ref=_rf('POWer', 41)),
    'foffs.set': Cmd('FREQ:OFFS:STAT 0', 'Frequency offset off', 'Same for frequency', kind='set', readback='foffs.query', verified=False,
                     ref=_rf('FREQuency', 42)),
    'foffs.query': Cmd('FREQ:OFFS:STAT?', 'Frequency offset state', kind='query', verified=False, ref=_rf('FREQuency', 42)),
    'freq.level': Cmd('FREQ {f:.12g};:POW {p:.3f}', 'Frequency and level', 'One message so the source applies its frequency / power coupling',
                      placeholders={'f': Placeholder('float', '.12g', 1e6), 'p': Placeholder('float', '.3f', 0.0)}, kind='set',
                      readback='freq.query', verified=False, ref=_rf('FREQuency / POWer, coupled commands', '42, 60-62')),
    'freq.query': Cmd('FREQ?', 'Frequency', kind='query', verified=False, ref=_rf('FREQuency', 42)),
    'level.query': Cmd('POW?', 'Level', kind='query', verified=False, ref=_rf('POWer', 41)),
    'outp.on': Cmd('OUTP ON', 'RF output on', 'Enables the RF output (never overridable)', kind='set', readback='outp.query', risk='output',
                   verified=False, ref=_rf('OUTPut', 39)),
    'outp.off': Cmd('OUTP OFF', 'RF output off', 'Disables the RF output (never overridable)', kind='set', readback='outp.query',
                    risk='output', verified=False, ref=_rf('OUTPut', 39)),
    'outp.query': Cmd('OUTP?', 'RF output state', 'Confirms on / off (never overridable)', kind='query', risk='output', verified=False,
                      ref=_rf('OUTPut', 39)),
    'err.query': Cmd('SYST:ERR?', 'Error queue', "'0' when the queue is empty (never overridable)", kind='query', risk='locked',
                     verified=False, ref=_rf('SYSTem:ERRor', 55)),
}

# Agilent 33220A / 33250A as the generator under test in the MDO4000C procedure. Generator commands are unverified (NOTES.md). This driver
# uses APPLy, which switches the output ON on the real generator (33220A User's Guide p. 188), so the two APPLy commands are risk 'output'
# (never overridable) even though the procedure sends OUTPut OFF first; OUTPut ON / OFF are 'output' as well.
AFG_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'outp.on': Cmd('OUTPut ON', 'Output on', 'Enables the output (never overridable)', kind='set', risk='output', verified=False),
    'outp.off': Cmd('OUTPut OFF', 'Output off', 'Disables the output (never overridable)', kind='set', risk='output', verified=False),
    'load.50': Cmd('OUTPut:LOAD 50', 'Output termination 50 ohm', kind='set', verified=False),
    'load.inf': Cmd('OUTPut:LOAD INF', 'Output termination High Z', kind='set', verified=False),
    'apply.sin': Cmd('APPLy:SINusoid {frequency_hz:.9g},{vpp:.9g},0', 'Apply sine', 'Frequency, Vpp, 0 V offset. APPLy switches the output on (never overridable)',
                     placeholders={'frequency_hz': Placeholder('float', '.9g', 1000.0), 'vpp': Placeholder('float', '.9g', 1.0)}, kind='set',
                     risk='output', verified=False),
    'apply.squ': Cmd('APPLy:SQUare {frequency_hz:.9g},{vpp:.9g},0', 'Apply square', 'Frequency, Vpp, 0 V offset. APPLy switches the output on (never overridable)',
                     placeholders={'frequency_hz': Placeholder('float', '.9g', 1000.0), 'vpp': Placeholder('float', '.9g', 1.0)}, kind='set',
                     risk='output', verified=False),
    'freq.query': Cmd('FREQuency?', 'Frequency', kind='query', verified=False),
    'volt.query': Cmd('VOLTage?', 'Amplitude', kind='query', verified=False),
    'err.query': Cmd('SYSTem:ERRor?', 'Error queue', "Oldest error; '+0' when empty (never overridable)", kind='query', risk='locked', verified=False),
}

# Generic SCPI DMM / counter / power meter (no manuals supplied): all unverified.
METER_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'freq.meas': Cmd('MEASure:FREQuency?', 'Measure frequency', kind='query', verified=False),
    'power.meas': Cmd('MEASure:POWer?', 'Measure power (dBm)', 'Power-meter reading; unverified (no manual supplied)', kind='query', verified=False),
    'conf.vac': Cmd('CONFigure:VOLTage:AC', 'Configure AC volts', kind='set', verified=False),
    'vac.band': Cmd('VOLTage:AC:BANDwidth 200', 'AC bandwidth 200 Hz', kind='set', verified=False),
    'conf.vdc': Cmd('CONFigure:VOLTage:DC', 'Configure DC volts', kind='set', verified=False),
    'read': Cmd('READ?', 'Read', kind='query', verified=False),
}

RF_COMMANDS['reset'] = cmdreg.reset_cmd(True, "96270A Operator Manual p. 3-46 (Master Reset is equivalent to the GPIB command *RST); the Remote Programmers Manual page for *RST was not checked",
                                        note='The connect-time known state (SINE, dBm, offsets off, output OFF) is applied again afterwards')
RF_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, '96000 Series Remote Programmers Manual: *OPC? not checked')
AFG_COMMANDS['reset'] = cmdreg.reset_cmd(False, "33220A / 33250A User's Guide: *RST not checked (manuals not available to the session that wrote this)",
                                         note='Output is confirmed OFF afterwards (OUTPut OFF, OUTPut?)')
AFG_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, "33220A / 33250A User's Guide: *OPC? not checked")
AFG_COMMANDS['outp.query'] = Cmd('OUTPut?', 'Output state', 'Confirms on / off after the reset (never overridable)', kind='query', risk='output', verified=False)
METER_COMMANDS['reset'] = cmdreg.reset_cmd(False, 'generic SCPI meter: no manual supplied, *RST is the IEEE 488.2 common command (unverified for the actual model)')
METER_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, 'generic SCPI meter: no manual supplied')


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
    COMMANDS = RF_COMMANDS

    output_off_confirmed = False

    def connect(self):
        """Open, clear status, then put the source in a known state: SINE instrument, levels in dBm, no offsets, output off.
        Selecting the instrument also puts the output into standby (p38). Each setting is read back."""
        self.open(verify_model=True)
        self.send('status.clear')
        self._apply_known_state()
        return self

    def _apply_known_state(self):
        """SINE instrument, levels in dBm, no offsets, output off (each read back). Run at connect and again after a reset."""
        self._set_and_check('inst.set', 'inst.query', lambda r: r.strip().strip('"').upper() == 'SINE', 'instrument SINE')
        self._set_and_check('unit.set', 'unit.query', lambda r: r.strip().strip('"').upper() == 'DBM', 'power units DBM')
        self._set_and_check('poffs.set', 'poffs.query', lambda r: not _bool_reply(r), 'power offset off')
        self._set_and_check('foffs.set', 'foffs.query', lambda r: not _bool_reply(r), 'frequency offset off')
        self.output(False)

    def _reset_extra(self):
        return [('known state again (SINE, dBm, offsets off, output OFF)', self._apply_known_state)]

    def _set_and_check(self, key, query, ok, what):
        self.send(key)
        reply = self.ask(query)
        if not ok(reply):
            raise InstrumentError(f'96270A {what}: set {cmdreg.render(self._registry()[key])!r}, reports {reply.strip()!r}')
        self.check_error(what)

    def check_error(self, context=''):
        """Raise if the source rejected a command. SYST:ERR? returns 0 when the queue is empty."""
        reply = self.ask('err.query').strip()
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
        self.send('freq.level', f=frequency_hz, p=level_dbm)
        self.check_error(f'{frequency_hz:g} Hz, {level_dbm:g} dBm')
        got = float(self.ask('freq.query').strip().split()[0])
        if not math.isclose(got, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A frequency set {frequency_hz:g}, reports {got:g}')
        lvl = float(self.ask('level.query').strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A level set {level_dbm:g} dBm, reports {lvl:g} dBm')

    def output(self, on: bool):
        """OUTP ON/OFF, then read OUTP? and compare. Not confirming OFF is a SafetyError."""
        self.send('outp.on' if on else 'outp.off')
        state = _bool_reply(self.ask('outp.query'))
        if state != on:
            if on:
                raise InstrumentError('96270A did not confirm output ON')
            raise SafetyError('96270A did not confirm output OFF; check the front panel')

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.send('outp.off')
            self.output_off_confirmed = not _bool_reply(self.ask('outp.query'))
        except Exception:
            self.output_off_confirmed = False


class AgilentAFG(Instrument):
    MODEL = 'Agilent 33220A / 33250A'
    IDN_MATCH = ('33220', '33250')
    DEFAULT_TIMEOUT = 10.0
    MAX_SINE_HZ = {'33220': 20e6, '33250': 80e6}     # sine ranges: 33220A / 33250A Service Guide specifications
    COMMANDS = AFG_COMMANDS

    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.idn = self.identify()
        self.kind = '33250' if '33250' in self.idn else '33220'
        return self

    def _reset_extra(self):
        def off():
            self.send('outp.off')
            if _bool_reply(self.ask('outp.query')):
                raise SafetyError('33220A / 33250A did not confirm output OFF after the reset; check the front panel')
        return [('output OFF confirmed (OUTPut OFF, OUTPut?)', off)]

    @property
    def max_hz(self):
        return self.MAX_SINE_HZ[self.kind]

    def sine(self, frequency_hz, vpp, load='50'):
        """Sine wave, amplitude in Vpp into the stated load, offset 0 V. Output stays OFF until output(True)."""
        if frequency_hz > self.max_hz:
            raise InstrumentError(f'{frequency_hz / 1e6:g} MHz is above the {self.kind} sine range ({self.max_hz / 1e6:g} MHz)')
        self.send('outp.off')
        self.send('load.50' if load == '50' else 'load.inf')
        self.send('apply.sin', frequency_hz=frequency_hz, vpp=vpp)
        self._verify(frequency_hz, vpp)

    def square(self, frequency_hz, vpp, load='50'):
        self.send('outp.off')
        self.send('load.50' if load == '50' else 'load.inf')
        self.send('apply.squ', frequency_hz=frequency_hz, vpp=vpp)
        self._verify(frequency_hz, vpp)

    def _verify(self, frequency_hz, vpp):
        f = float(self.ask('freq.query').strip())
        a = float(self.ask('volt.query').strip())
        if not math.isclose(f, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'{self.kind} frequency set {frequency_hz:g}, reports {f:g}')
        if not math.isclose(a, vpp, rel_tol=1e-3, abs_tol=1e-4):
            raise InstrumentError(f'{self.kind} amplitude set {vpp:g} Vpp, reports {a:g}')
        err = self.ask('err.query').strip()
        if not err.startswith(('+0', '0')):
            raise InstrumentError(f'{self.kind} rejected the setting: {err}')

    def output(self, on: bool):
        self.send('outp.on' if on else 'outp.off')

    def cleanup(self):
        try:
            self.send('outp.off')
        except Exception:
            pass


class ReferenceMeter(Instrument):
    """Generic SCPI DMM / counter for the AFG checks."""
    MODEL = 'SCPI reference meter'
    IDN_MATCH = ()
    DEFAULT_TIMEOUT = 20.0
    COMMANDS = METER_COMMANDS

    def connect(self):
        self.open(verify_model=False)
        self.send('status.clear')
        self.idn = self.identify()
        return self

    def _num(self, key):
        raw = self.ask(key).strip().split(',')[0]
        v = float(raw)
        if not math.isfinite(v) or abs(v) > 1e35:
            raise InstrumentError(f'Invalid reading from {cmdreg.render(self._registry()[key])}: {raw}')
        return v

    def frequency(self):
        return self._num('freq.meas')

    def ac_rms(self):
        self.send('conf.vac')
        self.send('vac.band')
        time.sleep(3.0)
        return self._num('read')

    def power(self):
        """Power meter reading in dBm."""
        return self._num('power.meas')

    def dc(self):
        self.send('conf.vdc')
        time.sleep(1.0)
        return self._num('read')
