"""SCPI bench DMMs: Fluke 8845A/8846A and Agilent/Keysight 34401A.

The two meters share the SCPI subset used for verification (CONF / READ? / SYST:REM), so they share a
base class; each model keeps its own class for identity, serial settings and its quirks.
"""
from __future__ import annotations

import math

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import SerialSettings

# CONF function names by the procedures' point kinds
FUNCTIONS = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC',
             'OHM2': 'RES', 'OHM4': 'FRES', 'CAP': 'CAP'}

_REF = 'Fluke 8845A/8846A Users Manual (remote commands)'
_CAL_REF = 'Fluke 8845A/8846A Calibration Manual'
_REF_34401 = 'Agilent 34401A User\'s Guide (SCPI reference)'


def _conf(kind):
    node = FUNCTIONS[kind]
    return Cmd('CONF:' + node + ' {range:.9g}', f'Configure {kind}', f'CONF:{node} with the range. Used for every {kind} verification point',
               placeholders={'range': Placeholder('float', '.9g', 10.0)}, kind='set',
               verified=kind != 'CAP', ref=_REF if kind != 'CAP' else '')    # CAP: not confirmed by the driver or the procedures


# Every command the SCPI bench DMMs send. Format specs are the ones the old f-strings used; the one conditional f-string
# (CONF:<function>) is split into one key per function. SYST:REM / CONF / READ? are what the verification procedures have always used.
COMMANDS = {
    'sys.rem': Cmd('SYST:REM', 'Remote mode', 'Enter remote control', kind='set', verified=True, ref=_REF),
    'sys.loc': Cmd('SYST:LOC', 'Local mode', 'Return to front-panel control', kind='set', verified=True, ref=_REF),
    **{'conf.' + k.lower(): _conf(k) for k in FUNCTIONS},
    'conf.freq': Cmd('CONF:FREQ', 'Configure frequency', 'Frequency function with default range. Not confirmed on a bench DMM', kind='set',
                     verified=False),
    'read': Cmd('READ?', 'Take a reading', 'One reading of the configured function', kind='query', verified=True, ref=_REF),
    # plumbing shared with the Truevolt driver (which redeclares status.clear / err.query verified): locked, not checked against the 8846A / 34401A manuals
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set', risk='locked',
                        verified=False, ref='8845A/8846A and 34401A manuals: *CLS not checked'),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest error; reading removes it (error-queue path, never overridable)', kind='query',
                     risk='locked', verified=False, ref='8845A/8846A and 34401A manuals: SYST:ERR? not checked'),
}
COMMANDS['reset'] = cmdreg.reset_cmd(False, '8845A/8846A Users Manual and 34401A User\'s Guide: *RST not checked (manuals not available to the session that wrote this)',
                                     note='Remote mode is entered again afterwards (SYST:REM)')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, '8845A/8846A and 34401A manuals: *OPC? not checked')



class ScpiDmm(Instrument):
    COMMANDS = COMMANDS
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
        self.send('sys.rem')

    def _reset_extra(self):
        return [('re-enter remote (SYST:REM)', self.remote)]

    def local(self):
        self.send('sys.loc')

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    def configure(self, kind: str, range_value: float):
        """CONF:<function> <range>   e.g. configure('DCV', 10) -> CONF:VOLT:DC 10"""
        if kind not in self.SUPPORTED:
            raise InstrumentError(f'{self.MODEL} driver does not support {kind}')
        self.send('conf.' + kind.lower(), range=range_value)

    def configure_frequency(self):
        self.send('conf.freq')

    def check_errors(self, context: str = ''):
        """SYST:ERR? (read-only). Raises if the meter's error queue is not empty, so a rejected command stops the run."""
        reply = self.ask('err.query').strip()
        if reply.split(',')[0].strip() not in ('0', '+0', '-0'):
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: {reply}')

    def read(self) -> float:
        """READ? -> first field as a float; rejects non-finite or overload (9.9E37) values."""
        raw = self.ask('read').strip().split(',')[0]
        value = float(raw)
        if not math.isfinite(value) or abs(value) > 1e35:
            raise ValueError(f'Invalid DMM reading: {raw}')
        return value


# The CAL:* family changes the meter's calibration: every key is risk 'locked' (never shown editable, never overridable). The password
# placeholder is a secret: it goes on the wire and is shown as ******** in the command log. verified=False: the adjustment stages are
# review-only until the replies are confirmed on a bench 8846A (see Procedures/Fluke_8846A_Adjustment.py).
_PW = {'password': Placeholder('secret')}
CAL_COMMANDS = {
    'cal.unlock': Cmd('CAL:SEC:STAT OFF,{password}', 'Unlock calibration', 'Calibration security off (never overridable; password masked in the log)',
                      placeholders=_PW, kind='set', readback='cal.sec.query', risk='locked', verified=False, ref=_CAL_REF),
    'cal.lock': Cmd('CAL:SEC:STAT ON,{password}', 'Lock calibration', 'Calibration security on (never overridable; password masked in the log)',
                    placeholders=_PW, kind='set', readback='cal.sec.query', risk='locked', verified=False, ref=_CAL_REF),
    'cal.sec.query': Cmd('CAL:SEC:STAT?', 'Calibration security state', 'Read back the security state (never overridable)', kind='query',
                         risk='locked', verified=False, ref=_CAL_REF),
    'cal.val': Cmd('CAL:VAL {mode},{value}', 'Calibration value', 'One adjustment step (never overridable)',
                   placeholders={'mode': Placeholder('str', '', 'ORES'), 'value': Placeholder('str', '', '100000000')}, kind='set',
                   readback='cal.on.query', risk='locked', verified=False, ref=_CAL_REF),
    'cal.on.query': Cmd('CAL? ON', 'Calibration step result', 'Executes the step; 0 / +0 means success (never overridable)', kind='query',
                        risk='locked', verified=False, ref=_CAL_REF),
    'cal.rec': Cmd('CAL:REC', 'Record calibration', 'Writes the adjusted coefficients to NONVOLATILE memory (never overridable)', kind='action',
                   risk='locked', verified=False, ref=_CAL_REF),
}


# Commands the 8846A verification adds for the AC filter, the frequency function and the 2-wire null (owner bench work, Oct 2026).
# All UNVERIFIED: taken from the 8845A/8846A programming manual and the 34401A / Truevolt command sets, not from a recorded 8846A reply.
_VREF = 'Fluke 8845A/8846A programming manual and the 34401A / Truevolt command sets; not confirmed by a recorded 8846A reply'
VERIFY_COMMANDS = {
    'band.set': Cmd('DET:BAND {hz:g}', 'AC filter', 'AC detector bandwidth 3, 20 or 200 Hz (3 Hz = slow filter; CONF:VOLT:AC resets it)',
                    placeholders={'hz': Placeholder('float', 'g', 3.0)}, kind='set', verified=False, ref=_VREF),
    'band.query': Cmd('DET:BAND?', 'AC filter read-back', 'Reads the AC detector bandwidth back', kind='query', verified=False, ref=_VREF),
    'freq.gate': Cmd('FREQ:APER {gate:g}', 'Frequency gate time', 'Gate (aperture) time of the frequency function, seconds',
                     placeholders={'gate': Placeholder('float', 'g', 1.0)}, kind='set', verified=False, ref=_VREF),
    'freq.range': Cmd('FREQ:VOLT:RANG {range:g}', 'Frequency input range', 'Voltage range of the frequency input',
                      placeholders={'range': Placeholder('float', 'g', 10.0)}, kind='set', verified=False, ref=_VREF),
    'null.func': Cmd('CALC:FUNC NULL', 'Math function: null', 'Selects the null (relative) math function', kind='set', verified=False, ref=_VREF),
    'null.offset': Cmd('CALC:NULL:OFFS {offset:.9g}', 'Null offset', 'The value subtracted from the readings while the null is on',
                       placeholders={'offset': Placeholder('float', '.9g', 0.0)}, kind='set', verified=False, ref=_VREF),
    'null.offset.query': Cmd('CALC:NULL:OFFS?', 'Null offset read-back', 'Reads the null offset back', kind='query', verified=False, ref=_VREF),
    'null.on': Cmd('CALC:STAT ON', 'Null on', 'Switches the math function on', kind='set', verified=False, ref=_VREF),
    'null.off': Cmd('CALC:STAT OFF', 'Null off', 'Switches the math function off', kind='set', verified=False, ref=_VREF),
    'null.state.query': Cmd('CALC:STAT?', 'Null state', 'Reads whether the math function is on', kind='query', verified=False, ref=_VREF),
}


class Fluke8846A(ScpiDmm):
    MODEL = 'Fluke 8846A'
    IDN_MATCH = ('8846',)
    COMMANDS = {**CAL_COMMANDS, **VERIFY_COMMANDS}

    def configure_frequency_point(self, voltage_range: float):
        """Frequency function: CONF:FREQ, the 3 Hz filter (sets the lowest frequency; DET:BAND is the command the
        8846A already accepts and reads back for the AC points), 1 s gate, input voltage range.
        UNVERIFIED on the 8846A: FREQ:APER and FREQ:VOLT:RANG come from the 34401A / Truevolt sets. The error
        queue is cleared first and read after EACH command, so a rejection names the exact command. Writes are not retried."""
        self.send('status.clear')
        self.send('conf.freq')
        self.check_errors('CONF:FREQ')
        self.set_ac_filter(3)
        self.check_errors('DET:BAND 3')
        self.send('freq.gate', gate=1)
        self.check_errors('FREQ:APER 1')
        self.send('freq.range', range=voltage_range)
        self.check_errors(f'FREQ:VOLT:RANG {voltage_range:g}')

    def null_on(self, offset: float):
        """Null the present function: CALC:FUNC NULL, CALC:NULL:OFFS <offset>, CALC:STAT ON. The offset and the state are
        read back and compared, and SYST:ERR? is read after each command, so a rejected or ignored command stops the run.
        UNVERIFIED on the 8846A (command set taken from the 34401A / Truevolt family). Writes are not retried."""
        self.send('status.clear')
        self.send('null.func')
        self.check_errors('CALC:FUNC NULL')
        self.send('null.offset', offset=offset)
        self.check_errors('CALC:NULL:OFFS')
        got = float(self.ask('null.offset.query').strip().split(',')[0])
        if abs(got - offset) > 1e-6 * max(abs(offset), 1e-3):
            raise InstrumentError(f'{self.MODEL} null offset reads back {got:.9g}, expected {offset:.9g}')
        self.send('null.on')
        self.check_errors('CALC:STAT ON')
        if self.ask('null.state.query').strip().lstrip('+') not in ('1', '1.0'):
            raise InstrumentError(f'{self.MODEL} did not report the null function on')

    def null_off(self):
        """CALC:STAT OFF, checked with SYST:ERR? and CALC:STAT?, so the null never carries over to another point."""
        self.send('null.off')
        self.check_errors('CALC:STAT OFF')
        if self.ask('null.state.query').strip().lstrip('+') not in ('0', '0.0'):
            raise InstrumentError(f'{self.MODEL} did not report the null function off')

    def set_ac_filter(self, hz: float = 3.0):
        """DET:BAND <hz> (3, 20 or 200), then read it back with DET:BAND? and compare. UNVERIFIED on hardware:
        the command and its reply format come from the 8845A/8846A programming manual, not from a bench run.
        CONF:VOLT:AC resets the filter, so call this after configure(). A write is never retried."""
        if hz not in (3, 20, 200):
            raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
        self.send('band.set', hz=hz)
        got = float(self.ask('band.query').strip().split(',')[0])
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
        self.send('cal.unlock', password=password)
        state = self.ask('cal.sec.query')
        if state.strip() not in ('0', '+0'):
            raise InstrumentError('Calibration security did not report unlocked: ' + state)

    def lock_calibration(self, password: str):
        self.send('cal.lock', password=password)
        state = self.ask('cal.sec.query')
        if state.strip() not in ('1', '+1'):
            raise InstrumentError('Security did not report locked: ' + state)

    def adjust_step(self, mode, value) -> str:
        """CAL:VAL <mode>,<value> then CAL? ON. Returns the meter's reply; raises unless it reports success (0/+0)."""
        self.send('cal.val', mode=str(mode), value=str(value))      # str(): same text the f-string made for int / float / str
        reply = self.ask('cal.on.query')
        if not self._ok(reply):
            raise InstrumentError('Instrument did not report adjustment success: ' + reply)
        return reply

    def record_calibration(self):
        """CAL:REC - writes adjusted coefficients to NONVOLATILE memory."""
        self.send('cal.rec')


class Agilent34401A(ScpiDmm):
    MODEL = 'Agilent 34401A'
    IDN_MATCH = ('34401',)
    SERIAL = SerialSettings(baud=9600, data_bits=7, parity='even', stop_bits=2,
                            write_termination='\n', read_termination='\n')
    SUPPORTED = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4')
    COMMANDS = {
        'det.band.slow': Cmd('DET:BAND 3', 'Slow AC filter', 'Detector bandwidth 3 Hz (slow AC filter) for AC measurements', kind='set',
                             verified=True, ref=_REF_34401),
    }

    def set_ac_filter_slow(self):
        """DET:BAND 3 - slow AC filter (3 Hz), for AC measurements."""
        self.send('det.band.slow')
