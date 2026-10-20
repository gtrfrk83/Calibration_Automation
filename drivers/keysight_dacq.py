"""Keysight 34970A / 34972A Data Acquisition / Switch Unit: the internal DMM, measured through a multiplexer channel.

    34970A  RS-232 (selectable COM port; the instrument's interface must be set to RS-232 on its front panel) - or GPIB
    34972A  USB (USBTMC) or LAN

Commands follow the 34970A/34972A Service Guide, Chapter 4 (Internal DMM Verification Tests, pp. 80-87) and the SCPI
reference: CONFigure:<function> <range>,(@<channel>), the function's NPLC / AC bandwidth / frequency aperture, then a
single-channel scan (ROUTe:SCAN) read with READ?.  Every verification reading is a one-channel scan, so no front-panel
Mon key is needed.  Writes are never retried; every command is logged.
"""
from __future__ import annotations

import math

from .base import Instrument, InstrumentError
from .transport import SerialSettings

CONF_NODE = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'OHM4': 'FRES'}
NPLC_KINDS = ('DCV', 'DCI', 'OHM2', 'OHM4')
AC_KINDS = ('ACV', 'ACI')

# Plug-in module channel plan for the verification (Service Guide pp. 69, 76, 80-87)
MODULE_CHANNELS = {
    '34901A': dict(short=9, input=10, current=21, pair_offset=10),     # 4-wire pairs: channel n with n + 10
    '34902A': dict(short=7, input=8, current=None, pair_offset=8),     # 4-wire pairs: channel n with n + 8; no current input
}


def channel_for(module: str, slot: int, role: str) -> int:
    """Channel number (slot*100 + n) for 'short', 'input' or 'current' on the given module and slot (1-3)."""
    plan = MODULE_CHANNELS[module]
    n = plan[role]
    if n is None:
        raise InstrumentError(f'The {module} has no {role} channel.')
    return slot * 100 + n


def pair_channel(module: str, channel: int) -> int:
    """The partner channel used for the sense leads of a 4-wire measurement on `channel`."""
    return channel + MODULE_CHANNELS[module]['pair_offset']


def scan_list(channel: int) -> str:
    return f'(@{channel})'


class KeysightDacq(Instrument):
    DEFAULT_TIMEOUT = 30.0          # one AC reading with the 3 Hz filter takes about 7 s
    # 34970A RS-232 factory defaults: 57600 baud, 8 data bits, no parity, 1 stop bit, XON/XOFF; <NL> terminates
    SERIAL = SerialSettings(baud=57600, data_bits=8, parity='none', stop_bits=1,
                            write_termination='\n', read_termination='\n', flow_control='xon_xoff')
    SUPPORTED = tuple(CONF_NODE) + ('FREQ',)
    REMOTE_ON_CONNECT = False       # 34970A over RS-232 is put into remote with SYST:REM

    def connect(self):
        """Open, (RS-232: SYST:REM), clear status and confirm the model."""
        self.open(verify_model=False)
        try:
            if self.REMOTE_ON_CONNECT:
                self.write('SYST:REM')
            self.write('*CLS')
            self.idn = self.identify()
            if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
                raise InstrumentError(f'Unexpected instrument identification: {self.idn}')
        except Exception:
            self.close()
            raise
        return self

    def cleanup(self):
        if self.REMOTE_ON_CONNECT:
            try:
                self.write('SYST:LOC')
            except Exception:
                pass

    # ---- plug-in modules ---------------------------------------------------------------------------
    def module_type(self, slot: int) -> str:
        """SYST:CTYP? <slot*100> -> e.g. 'AGILENT TECHNOLOGIES,34901A,0,1.0' (or 'Keysight ...')."""
        return self.query(f'SYST:CTYP? {slot * 100}').strip()

    def require_module(self, module: str, slot: int):
        found = self.module_type(slot)
        if module.upper() not in found.upper():
            raise InstrumentError(f'Slot {slot} holds "{found or "no module"}", not a {module}. '
                                  f'Install the {module} in slot {slot} (or choose the module that is installed).')
        return found

    # ---- verification setup --------------------------------------------------------------------------
    def configure_point(self, point: dict, channel: int):
        """Configure the DMM for one verification point on `channel` and select it as the only scan channel."""
        kind, ch = point['kind'], scan_list(channel)
        rng = point['range']
        if kind == 'FREQ':
            # range of the frequency function is the expected frequency; the input voltage range and a 1 s gate (6.5 digits) follow
            self.write(f'CONF:FREQ {point["nominal"]:.9g},{ch}')
            self.write(f'FREQ:VOLT:RANG {rng:.9g},{ch}')
            self.write(f'FREQ:APER 1,{ch}')
        elif kind in CONF_NODE:
            node = CONF_NODE[kind]
            self.write(f'CONF:{node} {rng:.9g},{ch}')
            if kind in NPLC_KINDS:
                self.write(f'{node}:NPLC {point.get("plc") or 10:g},{ch}')      # 10 PLC = 6.5 digits
            if kind in AC_KINDS:
                hz = point.get('filter_hz') or 3
                if hz not in (3, 20, 200):
                    raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
                self.write(f'{node}:BAND {hz:g},{ch}')                             # 3 Hz slow filter
        else:
            raise InstrumentError(f'{self.MODEL} driver does not support {kind}')
        self.write(f'ROUT:SCAN {ch}')
        self.write('TRIG:SOUR IMM')

    def read(self) -> float:
        """READ? (one scan of the selected channel) -> first field as a float; rejects overload (9.9E37) and non-finite values."""
        raw = self.query('READ?').strip().split(',')[0]
        value = float(raw)
        if not math.isfinite(value) or abs(value) > 1e35:
            raise InstrumentError(f'Invalid DMM reading: {raw} (overload or open channel)')
        return value

    def check_errors(self, context: str = ''):
        """Raise if the error queue holds anything (SYST:ERR? -> '+0,"No error"'); reports up to five entries."""
        found = []
        for _ in range(5):
            reply = self.query('SYST:ERR?').strip()
            if reply.split(',')[0].strip() in ('0', '+0', '-0'):
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))


class Keysight34970A(KeysightDacq):
    MODEL = 'Keysight 34970A'
    IDN_MATCH = ('34970A',)
    REMOTE_ON_CONNECT = True


class Keysight34972A(KeysightDacq):
    MODEL = 'Keysight 34972A'
    IDN_MATCH = ('34972A',)
    REMOTE_ON_CONNECT = False       # USB / LAN: remote control is implicit
