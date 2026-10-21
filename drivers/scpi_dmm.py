"""SCPI bench DMMs: Fluke 8845A/8846A and Agilent/Keysight 34401A.

The two meters share the SCPI subset used for verification (CONF / READ? / SYST:REM), so they share a
base class; each model keeps its own class for identity, serial settings and its quirks.
"""
from __future__ import annotations

import math

from .base import Instrument, InstrumentError
from .transport import SerialSettings

# CONF function names by the procedures' point kinds
FUNCTIONS = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC',
             'OHM2': 'RES', 'OHM4': 'FRES', 'CAP': 'CAP'}


class ScpiDmm(Instrument):
    DEFAULT_TIMEOUT = 20.0
    SERIAL = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                            write_termination='\n', read_termination='\n')
    SUPPORTED = tuple(FUNCTIONS)

    def connect(self):
        """Open, enter remote mode, then confirm the model (this order is what the procedures use)."""
        self.open(verify_model=False)
        self.remote()
        self.idn = self.identify()
        if self.IDN_MATCH and not any(m in self.idn for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Unexpected DMM identification: {self.idn}')
        return self

    def remote(self):
        self.write('SYST:REM')

    def local(self):
        self.write('SYST:LOC')

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    def configure(self, kind: str, range_value: float):
        """CONF:<function> <range>   e.g. configure('DCV', 10) -> CONF:VOLT:DC 10"""
        if kind not in self.SUPPORTED:
            raise InstrumentError(f'{self.MODEL} driver does not support {kind}')
        self.write(f'CONF:{FUNCTIONS[kind]} {range_value:.9g}')

    def configure_frequency(self):
        self.write('CONF:FREQ')

    def check_errors(self, context: str = ''):
        """SYST:ERR? (read-only). Raises if the meter's error queue is not empty, so a rejected command stops the run."""
        reply = self.query('SYST:ERR?').strip()
        if reply.split(',')[0].strip() not in ('0', '+0', '-0'):
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: {reply}')

    def read(self) -> float:
        """READ? -> first field as a float; rejects non-finite or overload (9.9E37) values."""
        raw = self.query('READ?').strip().split(',')[0]
        value = float(raw)
        if not math.isfinite(value) or abs(value) > 1e35:
            raise ValueError(f'Invalid DMM reading: {raw}')
        return value


class Fluke8846A(ScpiDmm):
    MODEL = 'Fluke 8846A'
    IDN_MATCH = ('8846',)


    def configure_frequency_point(self, voltage_range: float):
        """CONF:FREQ, 3 Hz low-frequency limit, 1 s gate, input voltage range (same sequence as the Keysight
        procedures). UNVERIFIED on the 8846A: the commands are the 34401A / Truevolt set; the caller checks
        SYST:ERR? afterwards so a rejection stops the run."""
        self.write('CONF:FREQ')
        self.write('FREQ:RANG:LOW 3')
        self.write('FREQ:APER 1')
        self.write(f'FREQ:VOLT:RANG {voltage_range:g}')

    def set_ac_filter(self, hz: float = 3.0):
        """DET:BAND <hz> (3, 20 or 200), then read it back with DET:BAND? and compare. UNVERIFIED on hardware:
        the command and its reply format come from the 8845A/8846A programming manual, not from a bench run.
        CONF:VOLT:AC resets the filter, so call this after configure(). A write is never retried."""
        if hz not in (3, 20, 200):
            raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
        self.write(f'DET:BAND {hz:g}')
        got = float(self.query('DET:BAND?').strip().split(',')[0])
        if abs(got - hz) > 1e-6 * max(hz, 1):
            raise InstrumentError(f'{self.MODEL} AC filter reads back {got:g} Hz, expected {hz:g} Hz')

    # ---- calibration / adjustment interface (Fluke 8845A/8846A Calibration Manual) ------------------
    # Safety-critical: these change the meter's calibration. Replies are checked exactly as the
    # adjustment procedure does, and the password never appears in the command log.
    @staticmethod
    def _ok(reply):
        return reply.strip() in ('0', '+0')

    def connect_for_adjustment(self):
        """Open without SYST:REM, flush, and refuse anything that is not an 8846A."""
        self.open(verify_model=False)
        self.t.clear()
        ident = self.identify()
        if '8846' not in ident.upper():
            self.close()
            raise InstrumentError('Refusing to adjust unexpected instrument: ' + ident)
        self.idn = ident
        return self

    def unlock_calibration(self, password: str):
        self.write('CAL:SEC:STAT OFF,' + password, log_as='CAL:SEC:STAT OFF,********')
        state = self.query('CAL:SEC:STAT?')
        if state.strip() not in ('0', '+0'):
            raise InstrumentError('Calibration security did not report unlocked: ' + state)

    def lock_calibration(self, password: str):
        self.write('CAL:SEC:STAT ON,' + password, log_as='CAL:SEC:STAT ON,********')
        state = self.query('CAL:SEC:STAT?')
        if state.strip() not in ('1', '+1'):
            raise InstrumentError('Security did not report locked: ' + state)

    def adjust_step(self, mode, value) -> str:
        """CAL:VAL <mode>,<value> then CAL? ON. Returns the meter's reply; raises unless it reports success (0/+0)."""
        self.write(f'CAL:VAL {mode},{value}')
        reply = self.query('CAL? ON')
        if not self._ok(reply):
            raise InstrumentError('Instrument did not report adjustment success: ' + reply)
        return reply

    def record_calibration(self):
        """CAL:REC - writes adjusted coefficients to NONVOLATILE memory."""
        self.write('CAL:REC')


class Agilent34401A(ScpiDmm):
    MODEL = 'Agilent 34401A'
    IDN_MATCH = ('34401',)
    SERIAL = SerialSettings(baud=9600, data_bits=7, parity='even', stop_bits=2,
                            write_termination='\n', read_termination='\n')
    SUPPORTED = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4')

    def set_ac_filter_slow(self):
        """DET:BAND 3 - slow AC filter (3 Hz), for AC measurements."""
        self.write('DET:BAND 3')
