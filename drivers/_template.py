"""<Manufacturer Model> - <what the procedures use it for>.

Copy this file to drivers/<maker>_<model>.py, rename the class, fill in the commands from the
programming manual (put the manual page number in each docstring), then export it in __init__.py
and add a simulator to simulated.py so procedures can be tested without hardware.
"""
from __future__ import annotations

from .base import Instrument, InstrumentError, SafetyError
from .transport import SerialSettings

# RS-232 only: the settings this model needs (leave out for USB / GPIB-only models).
SERIAL_DEFAULT = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r\n', read_termination='\r\n')


class ModelName(Instrument):
    MODEL = 'Maker Model'
    IDN_MATCH = ('MODEL',)          # text that must appear in *IDN? (or override identify() if no *IDN?)
    DEFAULT_TIMEOUT = 10.0

    # Pattern for every setting: write, read back, compare, raise InstrumentError on mismatch.
    def set_something(self, value):
        self.write(f'SOME:CMD {value}')
        got = float(self.query('SOME:CMD?'))
        if not self.close_to(got, value):
            raise InstrumentError(f'SOME:CMD: set {value}, instrument reports {got}')
        return got

    def cleanup(self):
        """Leave the instrument safe (sources off, standby, local mode). Never raise."""
        try:
            pass
        except Exception:
            pass
