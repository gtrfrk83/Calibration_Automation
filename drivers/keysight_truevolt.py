"""Keysight Truevolt DMMs (34460A / 34461A / 34465A / 34470A) over USB, GPIB (option) or LAN.

Commands follow the Truevolt Series Operating and Service Guide, performance verification (pp. 501-520):
every DC/resistance verification point is made with 10 PLC, AC points use the stated input filter,
frequency points use CONFigure:FREQuency DEF,MIN with a 3 Hz filter and 1 s aperture.
"""
from __future__ import annotations

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .scpi_dmm import FUNCTIONS, ScpiDmm
from .transport import SerialSettings

NPLC_NODE = {'DCV': 'VOLT:DC', 'DCI': 'CURR:DC', 'OHM2': 'RES', 'OHM4': 'FRES'}
AC_NODE = {'ACV': 'VOLT:AC', 'ACI': 'CURR:AC'}

_REF = 'Keysight Truevolt Series Operating and Service Guide, performance verification (pp. 501-520)'


def _nplc(kind):
    return Cmd(NPLC_NODE[kind] + ':NPLC {nplc:g}', f'{kind} integration time (PLC)', f'Number of power line cycles for {kind} points (10 PLC per the manual)',
               placeholders={'nplc': Placeholder('float', 'g', 10.0)}, kind='set', verified=True, ref=_REF)


def _band(kind):
    return Cmd(AC_NODE[kind] + ':BAND {hz:g}', f'{kind} detector bandwidth', 'AC input filter: 3, 20 or 200 Hz (the Filter column of the AC tables)',
               placeholders={'hz': Placeholder('float', 'g', 3.0)}, kind='set', verified=True, ref=_REF)


# Every command the Truevolt driver adds to the SCPI DMM set. Format specs are the ones the old f-strings used; the f-strings that
# chose the function node (NPLC / BAND) are split into one key per function. *CLS and SYST:ERR? are status / error-queue plumbing (locked).
COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set', risk='locked',
                        verified=True, ref=_REF),
    **{'nplc.' + k.lower(): _nplc(k) for k in NPLC_NODE},
    **{'band.' + k.lower(): _band(k) for k in AC_NODE},
    'conf.freq.point': Cmd('CONF:FREQ DEF,MIN', 'Configure frequency point', 'Frequency function, default range, minimum resolution', kind='set',
                           verified=True, ref=_REF),
    'freq.rang.low': Cmd('FREQ:RANG:LOW 3', 'Frequency lower limit (3 Hz filter)', 'Slowest frequency filter (3 Hz)', kind='set', verified=True,
                         ref=_REF),
    'freq.aper': Cmd('FREQ:APER 1', 'Frequency gate time', '1 s aperture', kind='set', verified=True, ref=_REF),
    'freq.volt.rang': Cmd('FREQ:VOLT:RANG {range:g}', 'Frequency input voltage range', 'Input voltage range for the frequency function',
                          placeholders={'range': Placeholder('float', 'g', 1.0)}, kind='set', verified=True, ref=_REF),
    'rout.term': Cmd('ROUT:TERM?', 'Terminal switch position', 'FRONT or REAR (the switch cannot be set remotely)', kind='query', verified=True,
                     ref=_REF),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest error; reading removes it (error-queue path, never overridable)', kind='query',
                     risk='locked', verified=True, ref=_REF),
}


class KeysightTruevolt(ScpiDmm):
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 20.0
    SERIAL = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                            write_termination='\n', read_termination='\n')
    SUPPORTED = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP')

    def connect(self):
        """Open, clear status and confirm the model. (Truevolt meters have no SYST:REM; remote control is implicit.)"""
        self.open(verify_model=False)
        self.send('status.clear')
        self.idn = self.identify()
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Unexpected DMM identification: {self.idn}')
        return self

    def _reset_extra(self):
        return []                   # no SYST:REM on the Truevolt meters: remote control is implicit

    def cleanup(self):
        # Truevolt meters return to front-panel control on their own when the remote session ends.
        pass

    # ---- verification setup helpers ---------------------------------------------------------------
    def set_nplc(self, kind: str, nplc: float = 10):
        """'Select 10 PLC' (manual footnote on every DC / resistance table)."""
        self.send('nplc.' + kind.lower(), nplc=nplc)

    def set_ac_filter(self, kind: str, hz: float):
        """Detector bandwidth: 3, 20 or 200 Hz (the Filter column of the AC tables)."""
        if hz not in (3, 20, 200):
            raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
        self.send('band.' + kind.lower(), hz=hz)

    def configure_point(self, point: dict):
        """Configure the meter for one verification point (function, range, NPLC or AC filter)."""
        kind, rng = point['kind'], point['range']
        if kind == 'FREQ':
            self.configure_frequency_point(point['range'])
            return
        self.configure(kind, rng)
        if kind in NPLC_NODE and point.get('plc'):
            self.set_nplc(kind, point['plc'])
        if kind in AC_NODE and point.get('filter_hz'):
            self.set_ac_filter(kind, point['filter_hz'])

    def configure_frequency_point(self, voltage_range: float):
        """CONF:FREQ DEF,MIN; 3 Hz filter; 1 s aperture; input voltage range for the frequency function."""
        self.send('conf.freq.point')
        self.send('freq.rang.low')
        self.send('freq.aper')
        self.send('freq.volt.rang', range=voltage_range)

    def front_rear(self) -> str:
        """ROUT:TERM? -> 'FRONT' or 'REAR' (the switch position, which cannot be set remotely)."""
        reply = self.ask('rout.term').strip().upper()
        return 'FRONT' if reply.startswith('FRON') else 'REAR' if reply.startswith('REAR') else reply

    def check_errors(self, context: str = ''):
        """Raise if the meter's error queue is not empty (SYST:ERR? -> '+0,"No error"')."""
        reply = self.ask('err.query').strip()
        code = reply.split(',')[0].strip()
        if code not in ('0', '+0', '-0'):
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: {reply}')



class Keysight34465A(KeysightTruevolt):
    MODEL = 'Keysight 34465A'
    IDN_MATCH = ('34465A',)


class Keysight34470A(KeysightTruevolt):
    MODEL = 'Keysight 34470A'
    IDN_MATCH = ('34470A',)


class Keysight34461A(KeysightTruevolt):
    MODEL = 'Keysight 34461A'
    IDN_MATCH = ('34461A',)


class Keysight34460A(KeysightTruevolt):
    MODEL = 'Keysight 34460A'
    IDN_MATCH = ('34460A',)
