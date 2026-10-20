"""Keysight Truevolt DMMs (34460A / 34461A / 34465A / 34470A) over USB, GPIB (option) or LAN.

Commands follow the Truevolt Series Operating and Service Guide, performance verification (pp. 501-520):
every DC/resistance verification point is made with 10 PLC, AC points use the stated input filter,
frequency points use CONFigure:FREQuency DEF,MIN with a 3 Hz filter and 1 s aperture.
"""
from __future__ import annotations

from .base import Instrument, InstrumentError
from .scpi_dmm import FUNCTIONS, ScpiDmm
from .transport import SerialSettings

NPLC_NODE = {'DCV': 'VOLT:DC', 'DCI': 'CURR:DC', 'OHM2': 'RES', 'OHM4': 'FRES'}
AC_NODE = {'ACV': 'VOLT:AC', 'ACI': 'CURR:AC'}


class KeysightTruevolt(ScpiDmm):
    DEFAULT_TIMEOUT = 20.0
    SERIAL = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                            write_termination='\n', read_termination='\n')
    SUPPORTED = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP')

    def connect(self):
        """Open, clear status and confirm the model. (Truevolt meters have no SYST:REM; remote control is implicit.)"""
        self.open(verify_model=False)
        self.write('*CLS')
        self.idn = self.identify()
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Unexpected DMM identification: {self.idn}')
        return self

    def cleanup(self):
        # Truevolt meters return to front-panel control on their own when the remote session ends.
        pass

    # ---- verification setup helpers ---------------------------------------------------------------
    def set_nplc(self, kind: str, nplc: float = 10):
        """'Select 10 PLC' (manual footnote on every DC / resistance table)."""
        self.write(f'{NPLC_NODE[kind]}:NPLC {nplc:g}')

    def set_ac_filter(self, kind: str, hz: float):
        """Detector bandwidth: 3, 20 or 200 Hz (the Filter column of the AC tables)."""
        if hz not in (3, 20, 200):
            raise InstrumentError(f'AC filter must be 3, 20 or 200 Hz, not {hz}')
        self.write(f'{AC_NODE[kind]}:BAND {hz:g}')

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
        self.write('CONF:FREQ DEF,MIN')
        self.write('FREQ:RANG:LOW 3')
        self.write('FREQ:APER 1')
        self.write(f'FREQ:VOLT:RANG {voltage_range:g}')

    def front_rear(self) -> str:
        """ROUT:TERM? -> 'FRONT' or 'REAR' (the switch position, which cannot be set remotely)."""
        reply = self.query('ROUT:TERM?').strip().upper()
        return 'FRONT' if reply.startswith('FRON') else 'REAR' if reply.startswith('REAR') else reply

    def check_errors(self, context: str = ''):
        """Raise if the meter's error queue is not empty (SYST:ERR? -> '+0,"No error"')."""
        reply = self.query('SYST:ERR?').strip()
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
