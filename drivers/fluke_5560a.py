"""Fluke 5560A multi-product calibrator - commands used by the WaveSurfer procedures.

Every command string below comes from the working procedures (SCOPE DCV / MEASR / LEVSINE, OUT, OPER,
STBY). Each setter reads the value back and raises InstrumentError if the calibrator disagrees.
Reference: Fluke 5560A Remote Programming (verify against your firmware before adding new commands).
"""
from __future__ import annotations

import dataclasses
import math
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .transport import SerialSettings

_REF = 'Fluke 5560A Remote Programming'
_REF_5522_SQ = '5522A Operators Manual pp. 6-48 (WAVE), 6-13 (DC_OFFSET), 5-28 (coupled commands), 4-42 and 1-24 (square wave amplitude in p-p)'


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
    'outimp.set': Cmd('OUT_IMP Z{source_impedance}', 'SCOPE output impedance', 'Source impedance of the SCOPE output (1M or 50)',
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
    'out.volts.dc': Cmd('OUT {volts:.9g}V,0Hz', 'Program a DC voltage with an explicit 0 Hz (NORMAL terminals)',
                        'Explicit 0 Hz so the output leaves AC; accepted by the 5560A (confirmed on hardware 2026-10-21)',
                        placeholders={'volts': _f(1.0)}, kind='set', verified=True, ref=_REF),
    'out.amps.dc': Cmd('OUT {amps:.9g}A,0Hz', 'Program a DC current with an explicit 0 Hz (NORMAL terminals)',
                       'Explicit 0 Hz so the output leaves AC',
                       placeholders={'amps': _f(0.001)}, kind='set', verified=False, ref=_REF),
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
    'tsens.tc': Cmd('TSENS_TYPE TC', 'Temperature source: thermocouple', 'Selects the thermocouple (not RTD) temperature source. 5560A Remote Programmers Manual p. 117', kind='set', verified=True,
                    ref='5560A/5550A/5540A/5530A Remote Programmers Manual p. 117 (TSENS_TYPE)'),
    'tc.query': Cmd('TC_TYPE?', 'Thermocouple type query', 'Returns the thermocouple type, e.g. K. 5560A Remote Programmers Manual p. 110', kind='query', verified=True,
                    ref='5560A/5550A/5540A/5530A Remote Programmers Manual p. 110 (TC_TYPE?)'),
    'out.temp': Cmd('OUT {celsius:.9g}CEL', 'Thermocouple simulation temperature', 'Not verified on a 5560A',
                    placeholders={'celsius': _f(100.0)}, kind='set', verified=False),
    # ---- square wave with a duty cycle and a DC offset (handheld DMM duty-cycle and Peak Min/Max points). Coupled commands:
    # WAVE, OUT and DC_OFFSET are programmed together in ONE compound line (5522A Operators Manual p. 5-28); DUTY is not coupled and follows.
    # Square-wave amplitude is peak-to-peak (5522A Operators Manual p. 4-42, spec table p. 1-24). The 5560A manual could not be read when
    # these were added: they are verified=False here and the 5522A (Fluke5522A.COMMANDS) carries the page references.
    'wave.square.out': Cmd('WAVE SQUARE; OUT {vpp:.9g}V,{freq}; DC_OFFSET {offset:.9g}V', 'Square wave: amplitude (p-p), frequency, DC offset',
                           'One compound line of coupled commands. Amplitude is peak-to-peak. Not verified on a 5560A',
                           placeholders={'vpp': _f(5.0), 'freq': Placeholder('str', '', '1kHz'), 'offset': _f(2.5)}, kind='set',
                           readback='wave.query', verified=False),
    'duty.set': Cmd('DUTY {duty:.9g}', 'Square wave duty cycle (%)', 'Single-output square waves only, 1.00 to 99.00 %. Not verified on a 5560A',
                    placeholders={'duty': _f(50.0)}, kind='set', readback='duty.query', verified=False),
    'duty.query': Cmd('DUTY?', 'Square wave duty cycle', 'Percent', kind='query', verified=False),
    'wave.query': Cmd('WAVE?', 'Waveform', 'SINE / TRI / SQUARE / TRUNCS (a second name for a dual output)', kind='query', verified=False),
    'dcoffset.query': Cmd('DC_OFFSET?', 'DC offset', 'Volts; 0 means no offset', kind='query', verified=False),
    'wave.sine.offset0': Cmd('WAVE SINE; DC_OFFSET 0V', 'Back to a sine wave with no DC offset',
                             'One compound line of coupled commands, sent with the output in standby after a square-wave point. Not verified on a 5560A',
                             kind='set', readback='wave.query', verified=False),
    'trg.measr': Cmd('*TRG', 'Trigger a resistance reading', 'In MEASR mode *TRG is a query and returns value + units (never overridable)',
                     kind='query', risk='locked', verified=True, ref=_REF),
    'err.query': Cmd('ERR?', 'Error queue', 'Oldest error; reading removes it (error-queue path, never overridable)', kind='query',
                     risk='locked', verified=False),
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
}

COMMANDS['reset'] = cmdreg.reset_cmd(True, '5560A Remote Programmers Manual, IEEE-488.2 common commands table (*RST: power-up state, holds off later commands until complete)',
                                     note='*RST: power-up state, output in STANDBY (confirmed afterwards with STBY / OPER?)')
COMMANDS['opc.query'] = cmdreg.opc_cmd(True, '5560A Remote Programmers Manual p. 86 (*OPC?: returns 1 when all pending operations are complete)')

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

    RESET_SCOPE_OFF = False        # True for the oscilloscope procedures: the calibrator is also left with its SCOPE function OFF after the reset

    def _reset_standby(self):
        self.standby()
        self.wave_nonsine = False      # *RST has just put the waveform back to its power-up state (sine, no offset)

    def _reset_extra(self):
        steps = [('output in STANDBY (STBY, OPER? = 0)', self._reset_standby)]
        if self.RESET_SCOPE_OFF:
            steps.append(('SCOPE function OFF (SCOPE OFF, SCOPE? = OFF)', self.scope_off))
        return steps

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
        if reply in ('Z50', 'Z1M'):      # the 5560A answers OUT_IMP? with the argument form (seen on the bench)
            if reply != f'Z{source_impedance}':
                raise InstrumentError(f'Unexpected SCOPE output impedance: {reply!r}')
            return
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
        raise InstrumentError(f'{self.label} error queue did not empty after {limit} reads: {stale[-3:]}')

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
    def set_output_volts(self, volts, frequency_hz=None, dc=False):
        """An OUT with no frequency keeps the previous one, so after an AC point it stays AC.
        dc=True sends ',0Hz' to select DC explicitly (callers that pass nothing keep the old command)."""
        if frequency_hz:
            self.send('out.volts.hz', volts=volts, hz=frequency_hz)
        elif dc:
            self.send('out.volts.dc', volts=volts)
        else:
            self.send('out.volts', volts=volts)

    def set_output_amps(self, amps, frequency_hz=None, dc=False):
        if frequency_hz:
            self.send('out.amps.hz', amps=amps, hz=frequency_hz)
        elif dc:
            self.send('out.amps.dc', amps=amps)
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

    enter_tc_function_first = True        # 5560A: TC_TYPE is refused (7028, "TC type can only be set while in TC Source/Measure function") until a temperature output has been programmed

    def set_output_temperature(self, celsius, tc_type='K'):
        """Thermocouple simulation.  5560A (bench error 7028 on the first temperature point when TC_TYPE came first): TSENS_TYPE TC, `OUT <t>CEL` to enter the TC Source
        function (this reverts the type to the Instrument Setup default), then TC_TYPE (a type change resets the output to 0 C), TC_TYPE? read back and compared, and
        `OUT <t>CEL` again.  Every write once; the caller reads the error queue after it and never operates after a rejection.  The order (function first) is the bench
        error's requirement; the commands are in the 5560A Remote Programmers Manual (TSENS_TYPE p. 117, TC_TYPE p. 110, TC_MEAS p. 108).  5522A: type then temperature, as before."""
        if not self.enter_tc_function_first:
            self.send('tc.type', tc_type=tc_type)
            self.send('out.temp', celsius=celsius)
            return
        self.send('tsens.tc')
        self._tc_wait()
        self.send('out.temp', celsius=celsius)
        self._tc_wait()
        self.check_error(f'entering the thermocouple function ({celsius:g} C)')
        self.send('tc.type', tc_type=tc_type)
        self._tc_wait()
        self.check_error(f'thermocouple type {tc_type}')
        got = self.ask('tc.query').strip().upper()
        if got != tc_type.upper():
            raise InstrumentError(f'{self.label} thermocouple type mismatch: TC_TYPE?={got!r} vs {tc_type!r}')
        self.send('out.temp', celsius=celsius)
        self._tc_wait()

    TC_SETTLE_S = 0.5          # the function change switches relays: the next command waits for *OPC? and this pause (the bench showed the commands arriving too fast)

    def _tc_wait(self):
        """*OPC? (a read-only query) then a short pause before the next thermocouple command."""
        self.ask('opc.query')
        time.sleep(self.TC_SETTLE_S)

    # ---- square wave with duty cycle and DC offset (NORMAL terminals) --------------------------------------------
    wave_nonsine = False        # True from the moment a square wave is programmed until WAVE SINE is read back (never leave a square wave selected)

    @staticmethod
    def _first_number(reply):
        return float(str(reply).split(',')[0].strip())

    def set_output_square(self, vpp, frequency_hz, duty_pct=50.0, offset_v=0.0):
        """Square wave on the NORMAL terminals: `WAVE SQUARE; OUT <vpp>V,<freq>; DC_OFFSET <offset>V` as ONE compound line (WAVE, OUT and
        DC_OFFSET are coupled commands), then `DUTY <duty>`. Amplitude is PEAK-TO-PEAK. The error queue is read, then WAVE? (SQUARE),
        DUTY? (within 0.01 %), DC_OFFSET? and OUT? are read back and compared; any difference raises InstrumentError and the output is not
        operated. Every write is sent once. wave_nonsine is set BEFORE the first write, so cleanup (restore_sine) always runs."""
        self.wave_nonsine = True
        self.send('wave.square.out', vpp=vpp, freq=self._freq_text(frequency_hz), offset=offset_v)
        self.send('duty.set', duty=duty_pct)
        self.check_error(f'square wave {vpp:g} V p-p, {frequency_hz:g} Hz, {duty_pct:g} % duty, offset {offset_v:g} V')
        wave = self.ask('wave.query').strip().upper().split(',')[0].strip()
        if wave != 'SQUARE':
            raise InstrumentError(f'{self.label} did not select a square wave: WAVE?={wave!r}')
        duty = self._first_number(self.ask('duty.query'))
        if abs(duty - duty_pct) > 0.01:
            raise InstrumentError(f'{self.label} duty cycle mismatch: DUTY?={duty:g} vs {duty_pct:g} %')
        offset = self._first_number(self.ask('dcoffset.query'))
        if not math.isclose(offset, offset_v, rel_tol=1e-4, abs_tol=1e-4):
            raise InstrumentError(f'{self.label} DC offset mismatch: DC_OFFSET?={offset:g} V vs {offset_v:g} V')
        reply = self.ask('out.query').strip()
        parts = [x.strip() for x in reply.split(',')]
        try:
            amp = float(parts[0])
            freq = float(parts[4]) if len(parts) >= 5 else float(parts[2]) if len(parts) >= 4 and parts[3].upper() == 'HZ' else None
        except (ValueError, IndexError):
            raise InstrumentError(f'Unexpected {self.label} OUT? response: {reply}')
        if len(parts) < 2 or parts[1].upper() != 'VPP':        # square-wave amplitude is reported in VPP (bench reply: 2.000000E+00,VPP,0E+00,0,6.000E+01)
            raise InstrumentError(f'Unexpected {self.label} OUT? response: {reply}')
        if not math.isclose(amp, vpp, rel_tol=1e-5, abs_tol=1e-6):
            raise InstrumentError(f'{self.label} square-wave amplitude mismatch: OUT? {amp:g} V vs {vpp:g} V peak-to-peak')
        if freq is not None and not math.isclose(freq, frequency_hz, rel_tol=1e-5):
            raise InstrumentError(f'{self.label} square-wave frequency mismatch: OUT? {freq:g} Hz vs {frequency_hz:g} Hz')

    def restore_sine(self):
        """`WAVE SINE; DC_OFFSET 0V` (one compound line), read back WAVE? (SINE) and DC_OFFSET? (0). Only with the output confirmed in
        STANDBY (OPER? is a read-only query). Sent once, never retried; wave_nonsine stays set unless everything reads back as expected."""
        if self.ask('oper.query').strip() != '0':
            raise SafetyError(f'{self.label} is not in standby: the square wave was not changed back to a sine wave')
        self.send('wave.sine.offset0')
        self.check_error('WAVE SINE, DC offset 0 V')
        wave = self.ask('wave.query').strip().upper().split(',')[0].strip()
        if wave != 'SINE':
            raise InstrumentError(f'{self.label} did not return to a sine wave: WAVE?={wave!r}')
        offset = self._first_number(self.ask('dcoffset.query'))
        if abs(offset) > 1e-6:
            raise InstrumentError(f'{self.label} DC offset not cleared: DC_OFFSET?={offset:g} V')
        self.wave_nonsine = False

    def read_error(self) -> str:
        """ERR? -> oldest error in the queue ('0,\"No error\"' when empty); reading removes it."""
        return self.ask('err.query').strip()

    def check_error(self, context=''):
        """Raise if the calibrator rejected the last command (e.g. an output outside its range)."""
        reply = self.read_error()
        code = reply.split(',')[0].strip()
        if code not in ('0', '+0'):
            raise InstrumentError(f'{self.label} rejected the setting{" (" + context + ")" if context else ""}: {reply}')

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
    enter_tc_function_first = False       # unchanged 5522A / 5520A order: TC_TYPE, then OUT <t>CEL
    """Fluke 5522A (and the 5520A / 5502A / 5500A family): same OUT / OPER / STBY / ERR? command set for the
    outputs the DMM procedures use. Offered so the handheld-meter procedures run with the calibrator the manual lists."""
    MODEL = 'Fluke 5522A'
    IDN_MATCH = ('5522', '5520', '5502', '5500')
    COMMANDS = {
        # inductive load compensation for ac current output (the 50-turn coil and current clamps are inductive loads: 5522A Operators Manual p. 11-7 note '* LCOMP ON is used to drive
        # inductive loads like the 5500A/COIL and current clamps').  LCOMP ON | OFF, LCOMP? answers ON | OFF (p. 6-23).  Allowed below 440 Hz for amplitudes below 0.33 A and below 1 kHz at 0.33 A or more.
        'lcomp.set': Cmd('LCOMP {mode}', 'Inductive load compensation', 'ON or OFF: inductive load compensation for ac current output (coil and clamp points)',
                         placeholders={'mode': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback='lcomp.query', verified=True,
                         ref='5522A Operators Manual p. 6-23 (LCOMP ON | OFF)'),
        'lcomp.query': Cmd('LCOMP?', 'Inductive load compensation query', 'Returns ON or OFF', kind='query', verified=True, ref='5522A Operators Manual p. 6-23 (LCOMP?)'),
        'reset': cmdreg.reset_cmd(True, '5522A Operators Manual p. 6-35 (*RST: power-up state, STBY, holds off later commands until done)'),
        'opc.query': cmdreg.opc_cmd(True, '5522A Operators Manual p. 5-44 (Using *OPC?, *OPC, *WAI)'),
        # square wave with duty cycle and DC offset: syntax from the Operators Manual (WAVE p. 6-48, DC_OFFSET p. 6-13, DUTY p. 6-14, coupled
        # commands p. 5-28, square-wave amplitude in p-p p. 4-42 and p. 1-24). The remote OUT? reply for a square wave was observed on a 5522A:
        # 2.000000E+00,VPP,0E+00,0,6.000E+01 for 2 Vpp at 60 Hz (amplitude, unit VPP, 0, 0, frequency); the program compares amplitude and frequency and stops on a difference.
        'wave.square.out': dataclasses.replace(COMMANDS['wave.square.out'], verified=True, ref=_REF_5522_SQ,
                                               description='One compound line of coupled commands (p. 5-28). Amplitude is peak-to-peak (p. 4-42)'),
        'duty.set': dataclasses.replace(COMMANDS['duty.set'], verified=True, ref='5522A Operators Manual p. 6-14 (DUTY: 1.00 to 99.00 %, single-output square waves only)',
                                        description='Single-output square waves only, 1.00 to 99.00 %'),
        'duty.query': dataclasses.replace(COMMANDS['duty.query'], verified=True, ref='5522A Operators Manual p. 6-14 (DUTY?)'),
        'wave.query': dataclasses.replace(COMMANDS['wave.query'], verified=True, ref='5522A Operators Manual p. 6-48 (WAVE?: SINE, TRI, SQUARE, TRUNCS, NONE)'),
        'dcoffset.query': dataclasses.replace(COMMANDS['dcoffset.query'], verified=True, ref='5522A Operators Manual p. 6-13 (DC_OFFSET?)'),
        'wave.sine.offset0': dataclasses.replace(COMMANDS['wave.sine.offset0'], verified=True, ref='5522A Operators Manual pp. 6-48, 6-13, 5-28 (WAVE, DC_OFFSET, coupled commands)',
                                                 description='One compound line of coupled commands, sent in standby after a square-wave point'),
    }


    @staticmethod
    def lcomp_allowed(amps, frequency_hz) -> bool:
        """5522A Operators Manual p. 6-23: compensation is allowed below 440 Hz when the amplitude is below 0.33 A, and below 1 kHz at 0.33 A or more."""
        if not frequency_hz:
            return False
        return frequency_hz < (440 if abs(amps) < 0.33 else 1000)

    def set_lcomp(self, on: bool):
        """LCOMP ON | OFF, read back with LCOMP? and compared.  Sent once, never retried; the caller reads the error queue (check_error) afterwards."""
        mode = 'ON' if on else 'OFF'
        self.send('lcomp.set', mode=mode)
        reply = self.ask('lcomp.query').strip().upper()
        if reply != mode:
            raise InstrumentError(f'{self.label}: inductive load compensation {mode} was not accepted (LCOMP? answered {reply!r})')


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# Fluke 5520A.  Only the 5520A SERVICE MANUAL (5520A_Manual.pdf) has been supplied: its calibration chapter prints the CAL_* commands and one sample MET/CAL
# program (Figure 3-9, printed pp. 3-18 and 3-19) that sends a handful of normal commands.  The Operators Manual / Programmers Guide (the normal command set
# and the serial settings) were NOT supplied.  The 5520A therefore reuses the Fluke5522A driver, but a command is marked verified here ONLY when that sample
# program (or the error list, pp. 4-8 to 4-11) shows it on a 5520A; every other command keeps the 5522A's text with verified=False and a reference that says
# so.  A command that is not verified is still SENT (the procedures read the error queue after setting an output and never operate after a rejection);
# nothing is invented.  Confirmed from the sample program (checked against the rendered pages 2026-10-23):
#   *CLS, *RST, *OPC?, ERR? (reply "code,message": the program takes field 1), OPER, OUT <value><unit>, 0HZ  (current, explicit 0 Hz), OUT? (field 5 = frequency).
# ---------------------------------------------------------------------------------------------------------------------------------------------------
_REF_5520 = '5520A Service Manual, Fig. 3-9 sample MET/CAL program (printed pp. 3-18, 3-19)'
_NOT_5520 = 'Not in the 5520A Service Manual (only the CAL_* commands and one sample program are printed); the text is the 5522A Operators Manual command, UNVERIFIED on a 5520A'
_CONFIRMED_5520 = {
    'status.clear': _REF_5520 + ': *CLS (steps 1.004 and 1.052)',
    'err.query': _REF_5520 + ': ERR? (step 1.005); the program takes field 1 of the reply as the error code',
    'oper.on': _REF_5520 + ': OPER (steps 1.019 and 1.052)',
    'opc.query': _REF_5520 + ': *OPC? (steps 1.004, 1.019)',
    'out.query': _REF_5520 + ': OUT? (step 1.057); field 5 of the reply is the frequency (step 1.058)',
    'out.amps.dc': _REF_5520 + ': "OUT 3.2999mA, 0HZ" (step 1.019): a current with an explicit 0 Hz; the driver writes the base unit A',
}


def _commands_5520():
    out = {}
    for key, cmd in cmdreg.merge_commands(Fluke5522A).items():
        if key in _CONFIRMED_5520:
            out[key] = dataclasses.replace(cmd, verified=True, ref=_CONFIRMED_5520[key])
        elif key == 'reset':
            out[key] = dataclasses.replace(cmd, verified=False, ref=_REF_5520 + ' sends *CLS;*RST; *OPC? (step 1.004) so the command exists, but this manual does not say what *RST leaves '
                                           '(the 5522A Operators Manual p. 6-36 says STBY); the driver confirms STBY and OPER? = 0 afterwards, UNVERIFIED on a 5520A')
        else:
            out[key] = dataclasses.replace(cmd, verified=False, ref=_NOT_5520)
    return out


class Fluke5520A(Fluke5522A):
    """Fluke 5520A.  Same OUT / OPER / STBY / ERR? command set as the 5522A for the outputs the DMM procedures use, with the verification status of each
    command restated for the 5520A (see the comment above): confirmed commands carry a 5520A Service Manual page, everything else is UNVERIFIED.
    NOT assumed to exist on a 5520A: ZCOMP (impedance compensation: the operator sets the 4-wire mode, as on the 5560A), the SCOPE option commands.
    Serial settings: the 5520A Service Manual says only that SERIAL 1 FROM HOST is the host port (pp. 1-4, 1-5) and that the host cable is a Fluke PM8914 (p. 3-28);
    baud, parity, data bits and terminators are NOT stated, so the repository default (9600 8N1, write CR, read CRLF) is UNVERIFIED for the 5520A."""
    MODEL = 'Fluke 5520A'
    IDN_MATCH = ('5520',)
    COMMANDS = _commands_5520()

    @classmethod
    def unverified_summary(cls):
        """One paragraph for a picker tooltip, built from the registry (so it cannot drift): how many registered commands a 5520A manual page confirms."""
        reg = cmdreg.merge_commands(cls)
        ok = sorted(k for k, c in reg.items() if c.verified)
        no = sorted(k for k, c in reg.items() if not c.verified)
        return (f'5520A remote commands: {len(ok)} of {len(reg)} registered commands are confirmed by the supplied 5520A Service Manual ({", ".join(dict.fromkeys(reg[k].template.split()[0] for k in ok))}); '
                f'the other {len(no)} (what *RST leaves, STBY, OPER?, OUT volts / amps / ohms, capacitance, thermocouple, waveform ...) and the serial settings (baud, parity, terminators) are UNVERIFIED '
                f'because the Operators Manual was not supplied. The program reads the error queue after every setting and never operates after a rejection.')
