"""Stimulus and reference instruments used with the MDO4000C procedure.

Fluke96270A      RF reference source (RF section: phase noise, amplitude, IMD, crosstalk, TPA functional check)
AgilentAFG       Agilent/Keysight 33220A (20 MHz) and 33250A (80 MHz) function / arbitrary generators
ReferenceMeter   any SCPI DMM or frequency counter (AFG frequency / amplitude / offset checks)

Every setter reads the value back and compares it; none of them is retried. RF and generator outputs are switched OFF at cleanup.
The 96270A command names are in RF_CMD so they can be matched to the remote-programming guide for your firmware in one place.
"""
from __future__ import annotations

import math
import re
import time

from .base import Instrument, InstrumentError

RF_CMD = dict(freq='FREQuency {v:.9g}', freq_q='FREQuency?', level='POWer {v:.4f}', level_q='POWer?', on='OUTPut ON', off='OUTPut OFF', state_q='OUTPut?')


class Fluke96270A(Instrument):
    MODEL = 'Fluke 96270A'
    IDN_MATCH = ('9627', '96270', 'FLUKE', 'WAVETEK')
    DEFAULT_TIMEOUT = 15.0
    MAX_HZ = 6.2e9

    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        return self

    def set_rf(self, frequency_hz, level_dbm):
        if frequency_hz > self.MAX_HZ:
            raise InstrumentError(f'{frequency_hz / 1e9:g} GHz is above the {self.MODEL} range')
        self.write(RF_CMD['freq'].format(v=frequency_hz))
        got = float(self.query(RF_CMD['freq_q']).strip().split()[0])
        if not math.isclose(got, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A frequency set {frequency_hz:g}, reports {got:g}')
        self.write(RF_CMD['level'].format(v=level_dbm))
        lvl = float(self.query(RF_CMD['level_q']).strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A level set {level_dbm:g} dBm, reports {lvl:g} dBm')

    def output(self, on: bool):
        self.write(RF_CMD['on'] if on else RF_CMD['off'])

    def cleanup(self):
        try:
            self.write(RF_CMD['off'])
        except Exception:
            pass


class AgilentAFG(Instrument):
    MODEL = 'Agilent 33220A / 33250A'
    IDN_MATCH = ('33220', '33250')
    DEFAULT_TIMEOUT = 10.0
    MAX_SINE_HZ = {'33220': 20e6, '33250': 80e6}     # sine ranges: 33220A / 33250A Service Guide specifications

    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.idn = self.identify()
        self.kind = '33250' if '33250' in self.idn else '33220'
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
