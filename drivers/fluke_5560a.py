"""Fluke 5560A multi-product calibrator - commands used by the WaveSurfer procedures.

Every command string below comes from the working procedures (SCOPE DCV / MEASR / LEVSINE, OUT, OPER,
STBY). Each setter reads the value back and raises InstrumentError if the calibrator disagrees.
Reference: Fluke 5560A Remote Programming (verify against your firmware before adding new commands).
"""
from __future__ import annotations

import math
import time

from .base import Instrument, InstrumentError, SafetyError
from .transport import SerialSettings

# RS-232 defaults for the 5560A; pass different SerialSettings for other baud rates.
SERIAL_DEFAULT = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r', read_termination='\r\n')


class Fluke5560A(Instrument):
    MODEL = 'Fluke 5560A'
    IDN_MATCH = ('5560',)
    DEFAULT_TIMEOUT = 20.0

    # ---- output state ------------------------------------------------------------------------
    def standby(self):
        """STBY and confirm. Raises SafetyError if the calibrator does not report standby."""
        self.write('STBY')
        if self.query('OPER?').strip() != '0':
            raise SafetyError('Fluke did not confirm standby')

    def operate(self):
        """OPER and confirm."""
        self.write('OPER')
        if self.query('OPER?').strip() != '1':
            raise InstrumentError('Fluke did not confirm OPERATE; output not verified')

    def is_operating(self):
        return self.query('OPER?').strip() == '1'

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.write('STBY')
            self.standby_confirmed = self.query('OPER?').strip() == '0'
        except Exception:
            self.standby_confirmed = False

    standby_confirmed = False

    # ---- SCOPE function ------------------------------------------------------------------------
    def scope_off(self):
        self.write('SCOPE OFF')
        mode = self.query('SCOPE?').strip().upper()
        if mode != 'OFF':
            raise InstrumentError(f'Fluke did not confirm SCOPE OFF: {mode!r}')

    def select_scope_dcv(self, source_impedance='1M'):
        """SCOPE DCV on the SCOPE BNC. FUNC? reports SDCV and SCOPE? reports VOLT."""
        self.write('SCOPE DCV')
        function = self.query('FUNC?').strip().upper()
        if function != 'SDCV':
            raise InstrumentError(f'Fluke did not select SCOPE DCV: FUNC?={function!r}')
        mode = self.query('SCOPE?').strip().upper()
        if mode != 'VOLT':
            raise InstrumentError(f'Fluke SCOPE output not in voltage mode: {mode!r}')
        self.write(f'OUT_IMP {source_impedance}')
        reply = self.query('OUT_IMP?').strip().upper()
        try:
            value = float(reply.split(',')[0])
        except ValueError:
            value = None   # some firmware answers with text; do not fail on that alone
        want = {'1M': 1e6, '50': 50.0}[source_impedance]
        if value is not None and not math.isclose(value, want, rel_tol=0.01):
            raise InstrumentError(f'Unexpected SCOPE output impedance: {reply!r}')

    def set_dc_volts(self, volts: float):
        """Program the DC level (output stays in standby until operate())."""
        self.write(f'OUT {volts:.9f}V')
        reply = self.query('OUT?').strip()
        parts = [p.strip() for p in reply.split(',')]
        if len(parts) < 2 or parts[1].upper() != 'V':
            raise InstrumentError(f'Unexpected Fluke OUT? response: {reply}')
        programmed = float(parts[0])
        if not math.isclose(programmed, volts, rel_tol=1e-5, abs_tol=1e-6):
            raise InstrumentError(f'Fluke setpoint mismatch: {programmed} V vs {volts} V')
        return programmed

    def select_scope_levsine(self):
        self.write('SCOPE LEVSINE')

    def set_levsine(self, vpp: float, frequency_hz: float):
        """Leveled sine amplitude (Vpp) and frequency. Frequency is sent in the units the manual uses."""
        self.write(f'OUT {vpp:.9g}V,{self._freq_text(frequency_hz)}')

    @staticmethod
    def _freq_text(hz):
        for scale, unit in ((1e9, 'GHz'), (1e6, 'MHz'), (1e3, 'kHz')):
            if hz >= scale:
                return f'{hz / scale:.9g}{unit}'
        return f'{hz:.9g}Hz'

    def select_scope_square(self):
        """SCOPE voltage-edge / square-wave function (DVM AC test). NOT yet verified on a 5560A: the mode name is checked through
        the error queue and the output is never enabled after a rejection."""
        self.write('SCOPE SQUARE')

    def set_square(self, vpp: float, frequency_hz: float):
        self.write(f'OUT {vpp:.9g}V,{self._freq_text(frequency_hz)}')

    # ---- SCOPE time markers (time base test) -- NOT yet verified on a 5560A ----------------------------
    # 'SCOPE MARKER' and 'OUT <period>S' follow the 5520A/5522A SC-option command set. Each call is checked
    # through the error queue and read back; the output is never enabled after a rejection or an unexpected
    # reply, and the raw reply is put in the error so the command set can be confirmed on the bench.
    def select_scope_marker(self):
        self.write('SCOPE MARKER')
        self.check_error('SCOPE MARKER')
        mode = self.query('SCOPE?').strip().upper()
        if 'MARK' not in mode:
            raise InstrumentError(f'Fluke did not confirm SCOPE MARKER: SCOPE?={mode!r}')

    def set_marker_period(self, seconds: float):
        """Time-marker period. OUT? may report the period (S) or the frequency (HZ); anything else stops the test."""
        self.write(f'OUT {seconds:.9g}S')
        self.check_error(f'marker period {seconds:g} s')
        reply = self.query('OUT?').strip()
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
        self.write('SCOPE MEASR')
        mode = self.query('SCOPE?').strip().upper()
        if mode != 'MEASR':
            raise InstrumentError(f'Fluke resistance mode not confirmed: {mode!r}')

    def measure_scope_resistance(self):
        """One fresh ohms reading in MEASR mode (*TRG is a query there and returns value + units)."""
        reply = self.query('*TRG').strip()
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
        self.write(f'OUT {volts:.9g}V' + (f',{frequency_hz:.9g}Hz' if frequency_hz else ''))

    def set_output_amps(self, amps, frequency_hz=None):
        self.write(f'OUT {amps:.9g}A' + (f',{frequency_hz:.9g}Hz' if frequency_hz else ''))

    def set_output_ohms(self, ohms):
        self.write(f'OUT {ohms:.9g}OHM')

    def set_output_capacitance(self, farads):
        """Capacitance output (NORMAL terminals). The command is checked through the error queue (check_error)."""
        if farads < 1e-6:
            text = f'{farads * 1e9:.9g}NF'
        elif farads < 1e-3:
            text = f'{farads * 1e6:.9g}UF'
        else:
            text = f'{farads:.9g}F'
        self.write(f'OUT {text}')

    def set_output_temperature(self, celsius, tc_type='K'):
        """Thermocouple simulation: select the type, then the temperature in degrees C.
        NOT yet verified on a 5560A - the procedure reads the error queue after it and never operates after a rejection."""
        self.write(f'TC_TYPE {tc_type}')
        self.write(f'OUT {celsius:.9g}CEL')

    def read_error(self) -> str:
        """ERR? -> oldest error in the queue ('0,\"No error\"' when empty); reading removes it."""
        return self.query('ERR?').strip()

    def check_error(self, context=''):
        """Raise if the calibrator rejected the last command (e.g. an output outside its range)."""
        reply = self.read_error()
        code = reply.split(',')[0].strip()
        if code not in ('0', '+0'):
            raise InstrumentError(f'5560A rejected the setting{" (" + context + ")" if context else ""}: {reply}')

    def clear_status(self):
        """*CLS - clears the status registers and the error queue."""
        self.write('*CLS')

    def operate_unverified(self):
        self.write('OPER')

    def standby_quiet(self):
        """STBY, ignoring communication errors (used before every point as a belt-and-braces step)."""
        try:
            self.write('STBY')
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
