"""<Manufacturer Model> - <what the procedures use it for>.

Copy this file to drivers/<maker>_<model>.py, rename the class, fill in the commands from the
programming manual (put the manual page number in each docstring), then export it in __init__.py
and add a simulator to simulated.py so procedures can be tested without hardware.

Every command is declared once in COMMANDS (cmdreg.Cmd: template, name, kind, read-back pairing, risk, verified, manual page) and sent with
self.send(key, ...) / self.ask(key, ...); never build command text with an f-string inside a method (the lint test in
tests/test_golden_commands.py fails on that). Output enables, calibration, reset and error-queue commands are risk 'output' / 'locked'.
"""
from __future__ import annotations

from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .transport import SerialSettings

# RS-232 only: the settings this model needs (leave out for USB / GPIB-only models).
SERIAL_DEFAULT = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r\n', read_termination='\r\n')


# verified=True only for commands confirmed in the manual (put the page in ref) or on the bench; leave False otherwise.
COMMANDS = {
    'something.set': Cmd('SOME:CMD {value:.9g}', 'Set something', placeholders={'value': Placeholder('float', '.9g', 1.0)}, kind='set',
                         readback='something.get', verified=False, ref='<manual, page>'),
    'something.get': Cmd('SOME:CMD?', 'Read something back', kind='query', verified=False, ref='<manual, page>'),
}


class ModelName(Instrument):
    MODEL = 'Maker Model'
    IDN_MATCH = ('MODEL',)          # text that must appear in *IDN? (or override identify() if no *IDN?)
    DEFAULT_TIMEOUT = 10.0
    COMMANDS = COMMANDS

    # Pattern for every setting: write, read back, compare, raise InstrumentError on mismatch.
    def set_something(self, value):
        self.send('something.set', value=value)
        got = float(self.ask('something.get'))
        if not self.close_to(got, value):
            raise InstrumentError(f'SOME:CMD: set {value}, instrument reports {got}')
        return got

    def cleanup(self):
        """Leave the instrument safe (sources off, standby, local mode). Never raise."""
        try:
            pass
        except Exception:
            pass
