"""Fluke 5560A multi-product calibrator - commands used by the WaveSurfer procedures.

Every command string below comes from the working procedures (SCOPE DCV / MEASR / LEVSINE, OUT, OPER,
STBY). Each setter reads the value back and raises InstrumentError if the calibrator disagrees.
Reference: Fluke 5560A Remote Programming (verify against your firmware before adding new commands).
"""
from __future__ import annotations

import math
import time

from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .transport import SerialSettings

_REF = 'Fluke 5560A Remote Programming'


def _f(sample=1.0, fmt='.9g'):
    return Placeholder('float', fmt, sample)


# Every command the driver sends. Format specs are the ones the old f-strings used. verified=True only for the commands the
# working DCV / MEASR / LEVSINE / DMM procedures have always used; the SQUARE, MARKER, capacitance, thermocouple and error-queue
# paths are NOT yet verified on a 5560A (see the method docstrings). OPER / STBY / OPER? change or confirm the output state
# (risk 'output'); ERR? / *CLS / *TRG are locked (error-queue and bootstrap paths). Output and locked commands cannot be overridden.
COMMANDS = {
    'oper.stby': Cmd('STBY', 'Output to standby', 'Puts the output in standby (never overridable)', kind='set', readback='oper.query',
                     risk='output', verified=True, ref=_REF),
    'oper.on': Cmd('OPER', 'Output to operate', 'Enables the output (never overridable)', kind='set', readback='oper.query',
                   risk='output', verified=True, ref=_REF),
    'oper.query': Cmd('OPER?', 'Output state', 'Confirms standby / operate (never overridable)', kind='query', risk='output',
                      verified=True, ref=_REF),
    'scope.off': Cmd('SCOPE OFF', 'SCOPE function off', kind='set', readback='scope.query', verified=True, ref=_REF),
    'scope.dcv': Cmd('SCOPE DCV', 'SCOPE DC volts', 'DC voltage on the SCOPE BNC', kind='set', readback='func.query', verified=True, ref=_REF),
    'scope.levsine': Cmd('SCOPE LEVSINE', 'SCOPE leveled sine', kind='set', verified=True, ref=_REF),
    'scope.square': Cmd('SCOPE SQUARE', 'SCOPE square wave', 'Voltage edge / square wave (DVM AC test). Not verified on a 5560A',
                        kind='set', verified=False),
    'scope.marker': Cmd('SCOPE MARKER', 'SCOPE time marker', 'Time-marker mode (time base test). Not verified on a 5560A',
                        kind='set', readback='scope.query', verified=False),
    'scope.measr': Cmd('SCOPE MEASR', 'SCOPE resistance measurement', kind='set', readback='scope.query', verified=True, ref=_REF),
    'scope.query': Cmd('SCOPE?', 'SCOPE mode', 'Read back the SCOPE mode', kind='query', verified=True, ref=_REF),
    'func.query': Cmd('FUNC?', 'Function', 'Read back the selected function (SDCV for SCOPE DCV)', kind='query', verified=True, ref=_REF),
    'outimp.set': Cmd('OUT_IMP {source_impedance}', 'SCOPE output impedance', 'Source impedance of the SCOPE output (1M or 50)',
                      placeholders={'source_impedance': Placeholder('str', '', '1M')}, kind='set', readback='outimp.query',
                      verified=True, ref=_REF),
    'outimp.query': Cmd('OUT_IMP?', 'SCOPE output impedance', kind='query', verified=True, ref=_REF),
    'out.dc': Cmd('OUT {volts:.9f}V', 'Program DC level (SCOPE)', 'DC level; the output stays in standby until OPER',
                  placeholders={'volts': _f(1.0, '.9f')}, kind='set', readback='out.query', verified=True, ref=_REF),
    'out.query': Cmd('OUT?', 'Read programmed output', kind='query', verified=True, ref=_REF),
    'out.levsine': Cmd('OUT {vpp:.9g}V,{freq}', 'Leveled sine amplitude and frequency',
                       'Vpp and frequency text (value plus Hz / kHz / MHz / GHz chosen by the driver)',
                       placeholders={'vpp': _f(2.5), 'freq': Placeholder('str', '', '1kHz')}, kind='set', verified=True, ref=_REF),
    'out.square': Cmd('OUT {vpp:.9g}V,{freq}', 'Square wave amplitude and frequency', 'Not verified on a 5560A',
                      placeholders={'vpp': _f(1.0), 'freq': Placeholder('str', '', '1kHz')}, kind='set', verified=False),
    'out.marker': Cmd('OUT {seconds:.9g}S', 'Time-marker period', 'Not verified on a 5560A; OUT? may answer in S or HZ',
                      placeholders={'seconds': _f(0.001)}, kind='set', readback='out.query', verified=False),
    'out.volts': Cmd('OUT {volts:.9g}V', 'Program a voltage (NORMAL terminals)', placeholders={'volts': _f(1.0)}, kind='set',
                     verified=True, ref=_REF),
    'out.volts.hz': Cmd('OUT {volts:.9g}V,{hz:.9g}Hz', 'Program a voltage and frequency (NORMAL terminals)',
                        placeholders={'volts': _f(1.0), 'hz': _f(1000.0)}, kind='set', verified=True, ref=_REF),
    'out.amps': Cmd('OUT {amps:.9g}A', 'Program a current (NORMAL terminals)', placeholders={'amps': _f(0.001)}, kind='set',
                    verified=True, ref=_REF),
    'out.amps.hz': Cmd('OUT {amps:.9g}A,{hz:.9g}Hz', 'Program a current and frequency (NORMAL terminals)',
                       placeholders={'amps': _f(0.001), 'hz': _f(1000.0)}, kind='set', verified=True, ref=_REF),
    'out.ohms': Cmd('OUT {ohms:.9g}OHM', 'Program a resistance (NORMAL terminals)', placeholders={'ohms': _f(1000.0)}, kind='set',
                    verified=True, ref=_REF),
    'out.cap.nf': Cmd('OUT {nf:.9g}NF', 'Program a capacitance (nF)', 'Value in nF; checked through the error queue. Not verified on a 5560A',
                      placeholders={'nf': _f(4.7)}, kind='set', verified=False),
    'out.cap.uf': Cmd('OUT {uf:.9g}UF', 'Program a capacitance (uF)', 'Value in uF; checked through the error queue. Not verified on a 5560A',
                      placeholders={'uf': _f(4.7)}, kind='set', verified=False),
    'out.cap.f': Cmd('OUT {farads:.9g}F', 'Program a capacitance (F)', 'Value in F; checked through the error queue. Not verified on a 5560A',
                     placeholders={'farads': _f(0.01)}, kind='set', verified=False),
    'tc.type': Cmd('TC_TYPE {tc_type}', 'Thermocouple type', 'Not verified on a 5560A',
                   placeholders={'tc_type': Placeholder('str', '', 'K')}, kind='set', verified=False),
    'out.temp': Cmd('OUT {celsius:.9g}CEL', 'Thermocouple simulation temperature', 'Not verified on a 5560A',
                    placeholders={'celsius': _f(100.0)}, kind='set', verified=False),
    'trg.measr': Cmd('*TRG', 'Trigger a resistance reading', 'In MEASR mode *TRG is a query and returns value + units (never overridable)',
                     kind='query', risk='locked', verified=True, ref=_REF),
    'err.query': Cmd('ERR?', 'Error queue', 'Oldest error; reading removes it (error-queue path, never overridable)', kind='query',
                     risk='locked', verified=False),
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
}


# RS-232 defaults for the 5560A; pass different SerialSettings for other baud rates.
SERIAL_DEFAULT = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r', read_termination='\r\n')


class Fluke5560A(Instrument):
    MODEL = 'Fluke 5560A'
    IDN_MATCH = ('5560',)
    DEFAULT_TIMEOUT = 20.0
    COMMANDS = COMMANDS

    # ---- output state ------------------------------------------------------------------------
    def standby(self):
        """STBY and confirm. Raises SafetyError if the calibrator does not report standby."""
        self.send('oper.stby')
        if self.ask('oper.query').strip() != '0':
            raise SafetyError('Fluke did not confirm standby')

    def operate(self):
        """OPER and confirm."""
        self.send('oper.on')
        if self.ask('oper.query').strip() != '1':
            raise InstrumentError('Fluke did not confirm OPERATE; output not verified')

    def is_operating(self):
        return self.ask('oper.query').strip() == '1'

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.send('oper.stby')
            self.standby_confirmed = self.ask('oper.query').strip() == '0'
        except Exception:
            self.standby_confirmed = False

    standby_confirmed = False
    stale_errors = ()

    # ---- SCOPE function ------------------------------------------------------------------------
    def scope_off(self):
        self.send('scope.off')
        mode = self.ask('scope.query').strip().upper()
        if mode != 'OFF':
            raise InstrumentError(f'Fluke did not confirm SCOPE OFF: {mode!r}')

    def select_scope_dcv(self, source_impedance='1M'):
        """SCOPE DCV on the SCOPE BNC. FUNC? reports SDCV and SCOPE? reports VOLT."""
        self.send('scope.dcv')
        function = self.ask('func.query').strip().upper()
        if function != 'SDCV':
            raise InstrumentError(f'Fluke did not select SCOPE DCV: FUNC?={function!r}')
        mode = self.ask('scope.query').strip().upper()
        if mode != 'VOLT':
            raise InstrumentError(f'Fluke SCOPE output not in voltage mode: {mode!r}')
        self.send('outimp.set', source_impedance=source_impedance)
        reply = self.ask('outimp.query').strip().upper()
        try:
            value = float(reply.split(',')[0])
        except ValueError:
            value = None   # some firmware answers with text; do not fail on that alone
        want = {'1M': 1e6, '50': 50.0}[source_impedance]
        if value is not None and not math.isclose(value, want, rel_tol=0.01):
            raise InstrumentError(f'Unexpected SCOPE output impedance: {reply!r}')

    def set_dc_volts(self, volts: float):
        """Program the DC level (output stays in standby until operate())."""
        self.send('out.dc', volts=volts)
        reply = self.ask('out.query').strip()
        parts = [p.strip() for p in reply.split(',')]
        if len(parts) < 2 or parts[1].upper() != 'V':
            raise InstrumentError(f'Unexpected Fluke OUT? response: {reply}')
        programmed = float(parts[0])
        if not math.isclose(programmed, volts, rel_tol=1e-5, abs_tol=1e-6):
            raise InstrumentError(f'Fluke setpoint mismatch: {programmed} V vs {volts} V')
        return programmed

    def select_scope_levsine(self):
        self.send('scope.levsine')

    def set_levsine(self, vpp: float, frequency_hz: float):
        """Leveled sine amplitude (Vpp) and frequency. Frequency is sent in the units the manual uses."""
        self.send('out.levsine', vpp=vpp, freq=self._freq_text(frequency_hz))

    @staticmethod
    def _freq_text(hz):
        for scale, unit in ((1e9, 'GHz'), (1e6, 'MHz'), (1e3, 'kHz')):
            if hz >= scale:
                return f'{hz / scale:.9g}{unit}'
        return f'{hz:.9g}Hz'

    def select_scope_square(self):
        """SCOPE voltage-edge / square-wave function (DVM AC test). NOT yet verified on a 5560A: the mode name is checked through
        the error queue and the output is never enabled after a rejection."""
        self.send('scope.square')

    def set_square(self, vpp: float, frequency_hz: float):
        self.send('out.square', vpp=vpp, freq=self._freq_text(frequency_hz))

    # ---- SCOPE time markers (time base test) -- NOT yet verified on a 5560A ----------------------------
    # 'SCOPE MARKER' and 'OUT <period>S' follow the 5520A/5522A SC-option command set. Each call is checked
    # through the error queue and read back; the output is never enabled after a rejection or an unexpected
    # reply, and the raw reply is put in the error so the command set can be confirmed on the bench.
    def drain_errors(self, limit=20):
        """Read-only: empty the error queue (ERR? removes the oldest each time) and return what was in it, so an error left
        over from an earlier session is never blamed on the next command. Every reply is in the command log."""
        stale = []
        for _ in range(limit):
            reply = self.read_error()
            if reply.split(',')[0].strip() in ('0', '+0'):
                return stale
            stale.append(reply)
        raise InstrumentError(f'5560A error queue did not empty after {limit} reads: {stale[-3:]}')

    def select_scope_marker(self):
        """SCOPE? reports MARKER in time-marker mode (confirmed from the 5560A front panel, 2026-10-21)."""
        self.stale_errors = self.drain_errors()
        self.send('scope.marker')
        self.check_error('SCOPE MARKER')
        mode = self.ask('scope.query').strip().upper()
        if 'MARK' not in mode:
            raise InstrumentError(f'Fluke did not confirm SCOPE MARKER: SCOPE?={mode!r}')

    def set_marker_period(self, seconds: float):
        """Time-marker period. OUT? may report the period (S) or the frequency (HZ); anything else stops the test."""
        self.send('out.marker', seconds=seconds)
        self.check_error(f'marker period {seconds:g} s')
        reply = self.ask('out.query').strip()
        parts = [p.strip().upper() for p in reply.split(',')]
        try:
            value = float(parts[0])
        except (ValueError, IndexError):
            raise InstrumentError(f'Unexpected Fluke OUT? reply in marker mode: {reply!r}')
        unit = parts[1] if len(parts) > 1 else ''
        if unit in ('S', 'SEC'):
            period = value
        elif unit == 'HZ' and value > 0:
            period = 1.0 / value
        else:
            raise InstrumentError(f'Unexpected Fluke OUT? reply in marker mode: {reply!r} (expected a period in S or a frequency in HZ)')
        if not math.isclose(period, seconds, rel_tol=1e-6):
            raise InstrumentError(f'Fluke marker period mismatch: {period:g} s vs {seconds:g} s')
        return period

    def select_scope_measure_resistance(self):
        self.send('scope.measr')
        mode = self.ask('scope.query').strip().upper()
        if mode != 'MEASR':
            raise InstrumentError(f'Fluke resistance mode not confirmed: {mode!r}')

    def measure_scope_resistance(self):
        """One fresh ohms reading in MEASR mode (*TRG is a query there and returns value + units)."""
        reply = self.ask('trg.measr').strip()
        parts = [p.strip().upper() for p in reply.split(',')]
        if len(parts) < 2 or parts[1] != 'OHM':
            raise InstrumentError(f'Fluke resistance reading not valid (expected OHM): {reply!r}')
        value = float(parts[0])
        if not math.isfinite(value) or value <= 0:
            raise InstrumentError(f'Invalid Fluke resistance value: {reply!r}')
        return value

    # ---- NORMAL-terminal outputs (used when the 5560A drives a DMM) -----------------------------
    # These send exactly the commands the DMM verification procedures use. By default OPER / STBY
    # are NOT read back (verify=False) to match those procedures' proven behaviour on RS-232 links;
    # pass verify=True once the readback has been confirmed on your 5560A.
    def set_output_volts(self, volts, frequency_hz=None):
        if frequency_hz:
            self.send('out.volts.hz', volts=volts, hz=frequency_hz)
        else:
            self.send('out.volts', volts=volts)

    def set_output_amps(self, amps, frequency_hz=None):
        if frequency_hz:
            self.send('out.amps.hz', amps=amps, hz=frequency_hz)
        else:
            self.send('out.amps', amps=amps)

    def set_output_ohms(self, ohms):
        self.send('out.ohms', ohms=ohms)

    def set_output_capacitance(self, farads):
        """Capacitance output (NORMAL terminals). The command is checked through the error queue (check_error)."""
        if farads < 1e-6:
            self.send('out.cap.nf', nf=farads * 1e9)
        elif farads < 1e-3:
            self.send('out.cap.uf', uf=farads * 1e6)
        else:
            self.send('out.cap.f', farads=farads)

    def set_output_temperature(self, celsius, tc_type='K'):
        """Thermocouple simulation: select the type, then the temperature in degrees C.
        NOT yet verified on a 5560A - the procedure reads the error queue after it and never operates after a rejection."""
        self.send('tc.type', tc_type=tc_type)
        self.send('out.temp', celsius=celsius)

    def read_error(self) -> str:
        """ERR? -> oldest error in the queue ('0,\"No error\"' when empty); reading removes it."""
        return self.ask('err.query').strip()

    def check_error(self, context=''):
        """Raise if the calibrator rejected the last command (e.g. an output outside its range)."""
        reply = self.read_error()
        code = reply.split(',')[0].strip()
        if code not in ('0', '+0'):
            raise InstrumentError(f'5560A rejected the setting{" (" + context + ")" if context else ""}: {reply}')

    def clear_status(self):
        """*CLS - clears the status registers and the error queue."""
        self.send('status.clear')

    def operate_unverified(self):
        self.send('oper.on')

    def standby_quiet(self):
        """STBY, ignoring communication errors (used before every point as a belt-and-braces step)."""
        try:
            self.send('oper.stby')
        except Exception:
            pass

    # ---- convenience sequences ------------------------------------------------------------------------
    def apply_scope_dc(self, volts: float):
        """Safe sequence used by the DCV/offset tests: STBY -> SCOPE DCV -> 1 M -> level -> OPER."""
        self.standby()
        self.select_scope_dcv('1M')
        self.set_dc_volts(volts)
        self.operate()


class Fluke5522A(Fluke5560A):
    """Fluke 5522A (and the 5520A / 5502A / 5500A family): same OUT / OPER / STBY / ERR? command set for the
    outputs the DMM procedures use. Offered so the handheld-meter procedures run with the calibrator the manual lists."""
    MODEL = 'Fluke 5522A'
    IDN_MATCH = ('5522', '5520', '5502', '5500')
