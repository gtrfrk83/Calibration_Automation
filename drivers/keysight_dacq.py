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

import cmdreg
from cmdreg import Cmd, Placeholder
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


_REF = 'Keysight 34970A/34972A Service Guide, Chapter 4 (Internal DMM Verification Tests, pp. 80-87)'
_CH = {'ch': Placeholder('str', '', '(@210)')}      # the scan list text, e.g. (@210)


def _conf(kind):
    node = CONF_NODE[kind]
    return Cmd('CONF:' + node + ' {range:.9g},{ch}', f'Configure {kind}', f'CONF:{node} with the range on the channel',
               placeholders={'range': Placeholder('float', '.9g', 10.0), **_CH}, kind='set', verified=True, ref=_REF)


def _nplc(kind):
    node = CONF_NODE[kind]
    return Cmd(node + ':NPLC {plc:g},{ch}', f'{kind} integration time (PLC)', '10 PLC = 6.5 digits',
               placeholders={'plc': Placeholder('float', 'g', 10.0), **_CH}, kind='set', verified=True, ref=_REF)


def _band(kind):
    node = CONF_NODE[kind]
    return Cmd(node + ':BAND {hz:g},{ch}', f'{kind} detector bandwidth', 'AC filter 3, 20 or 200 Hz on the channel. Not verified on a 34970A/34972A',
               placeholders={'hz': Placeholder('float', 'g', 3.0), **_CH}, kind='set', verified=False)


# Every command the 34970A/34972A driver sends. Format specs are the ones the old f-strings used; the f-strings that chose the
# function node are split into one key per function. Unverified per NOTES.md: FREQ:APER, the AC bandwidth on the current channel and the
# ROUT:SCAN + READ? reading path. *CLS and SYST:ERR? are status / error-queue plumbing (locked).
COMMANDS = {
    'sys.rem': Cmd('SYST:REM', 'Remote mode', '34970A over RS-232 is put into remote with SYST:REM', kind='set', verified=True, ref=_REF),
    'sys.loc': Cmd('SYST:LOC', 'Local mode', 'Return to front-panel control', kind='set', verified=True, ref=_REF),
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set', risk='locked',
                        verified=True, ref=_REF),
    'module.type': Cmd('SYST:CTYP? {card}', 'Plug-in module type', 'Card number is slot * 100',
                       placeholders={'card': Placeholder('int', 'd', 100)}, kind='query', verified=True, ref=_REF),
    'conf.freq': Cmd('CONF:FREQ {nominal:.9g},{ch}', 'Configure frequency', 'Expected frequency as the range',
                     placeholders={'nominal': Placeholder('float', '.9g', 1000.0), **_CH}, kind='set', verified=True, ref=_REF),
    'freq.volt.rang': Cmd('FREQ:VOLT:RANG {range:.9g},{ch}', 'Frequency input voltage range', 'Input voltage range for the frequency function',
                          placeholders={'range': Placeholder('float', '.9g', 1.0), **_CH}, kind='set', verified=True, ref=_REF),
    'freq.aper': Cmd('FREQ:APER 1,{ch}', 'Frequency gate time', '1 s gate (6.5 digits). Not verified on a 34970A/34972A', placeholders=dict(_CH),
                     kind='set', verified=False),
    **{'conf.' + k.lower(): _conf(k) for k in CONF_NODE},
    **{'nplc.' + k.lower(): _nplc(k) for k in NPLC_KINDS},
    **{'band.' + k.lower(): _band(k) for k in AC_KINDS},
    'rout.scan': Cmd('ROUT:SCAN {ch}', 'Select the scan channel', 'Single-channel scan. Not verified on a 34970A/34972A', placeholders=dict(_CH),
                     kind='set', verified=False),
    'trig.sour': Cmd('TRIG:SOUR IMM', 'Trigger source', 'Immediate trigger', kind='set', verified=True, ref=_REF),
    'read': Cmd('READ?', 'Take a reading', 'One scan of the selected channel. Not verified on a 34970A/34972A', kind='query', verified=False),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest error; reading removes it (error-queue path, never overridable)', kind='query',
                     risk='locked', verified=True, ref=_REF),
}

COMMANDS['reset'] = cmdreg.reset_cmd(False, '34970A/34972A manual: *RST not checked (manual not available to the session that wrote this)',
                                     note='Channel / scan configuration is set again per point')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, '34970A/34972A manual: *OPC? not checked')


class KeysightDacq(Instrument):
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 30.0          # one AC reading with the 3 Hz filter takes about 7 s
    # 34970A RS-232 factory defaults: 57600 baud, 8 data bits, no parity, 1 stop bit, XON/XOFF; <NL> terminates
    SERIAL = SerialSettings(baud=57600, data_bits=8, parity='none', stop_bits=1,
                            write_termination='\n', read_termination='\n', flow_control='xon_xoff')
    SUPPORTED = tuple(CONF_NODE) + ('FREQ',)
    REMOTE_ON_CONNECT = False       # 34970A over RS-232 is put into remote with SYST:REM

    def _reset_extra(self):
        return [('re-enter remote (SYST:REM)', lambda: self.send('sys.rem'))] if self.REMOTE_ON_CONNECT else []

    def connect(self):
        """Open, (RS-232: SYST:REM), clear status and confirm the model."""
        self.open(verify_model=False)
        try:
            if self.REMOTE_ON_CONNECT:
                self.send('sys.rem')
            self.send('status.clear')
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
                self.send('sys.loc')
            except Exception:
                pass

    # ---- plug-in modules ---------------------------------------------------------------------------
    def module_type(self, slot: int) -> str:
        """SYST:CTYP? <slot*100> -> e.g. 'AGILENT TECHNOLOGIES,34901A,0,1.0' (or 'Keysight ...')."""
        return self.ask('module.type', card=slot * 100).strip()

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
            self.send('conf.freq', nominal=point['nominal'], ch=ch)
            self.send('freq.volt.rang', range=rng, ch=ch)
            self.send('freq.aper', ch=ch)
        elif kind in CONF_NODE:
            self.send('conf.' + kind.lower(), range=rng, ch=ch)
            if kind in NPLC_KINDS:
                self.send('nplc.' + kind.lower(), plc=point.get('plc') or 10, ch=ch)      # 10 PLC = 6.5 digits
            if kind in AC_KINDS:
                hz = point.get('filter_hz') or 3
                if hz not in (3, 20, 200):
                    raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
                self.send('band.' + kind.lower(), hz=hz, ch=ch)                             # 3 Hz slow filter
        else:
            raise InstrumentError(f'{self.MODEL} driver does not support {kind}')
        self.send('rout.scan', ch=ch)
        self.send('trig.sour')

    def read(self) -> float:
        """READ? (one scan of the selected channel) -> first field as a float; rejects overload (9.9E37) and non-finite values."""
        raw = self.ask('read').strip().split(',')[0]
        value = float(raw)
        if not math.isfinite(value) or abs(value) > 1e35:
            raise InstrumentError(f'Invalid DMM reading: {raw} (overload or open channel)')
        return value

    def check_errors(self, context: str = ''):
        """Raise if the error queue holds anything (SYST:ERR? -> '+0,"No error"'); reports up to five entries."""
        found = []
        for _ in range(5):
            reply = self.ask('err.query').strip()
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
