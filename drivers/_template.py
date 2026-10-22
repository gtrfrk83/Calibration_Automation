"""<Manufacturer Model> - <what the procedures use it for>.

Copy this file to drivers/<maker>_<model>.py, rename the class, fill in the commands from the
programming manual (put the manual page number in each docstring), then export it in __init__.py
and add a simulator to simulated.py so procedures can be tested without hardware.

Every command is declared once in COMMANDS (cmdreg.Cmd: template, name, kind, read-back pairing, risk, verified, manual page) and sent with
self.send(key, ...) / self.ask(key, ...); never build command text with an f-string inside a method (the lint test in
tests/test_golden_commands.py fails on that). Output enables, calibration, reset and error-queue commands are risk 'output' / 'locked'.
"""
from __future__ import annotations

import cmdreg
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

# Stage 7 rule - every driver declares how it is reset to default settings BEFORE a run (locked: a modified procedure can never skip it).
# (Examples: drivers/tektronix_tds2000c.py resets with FACtory, not *RST, because the procedure runs the self calibration itself; drivers/fluke_5522a_scope.py also leaves SCOPE OFF.)
# verified=True only when a manual page backs it (put the page in ref); otherwise leave False and it is listed as unverified in the report.
COMMANDS['reset'] = cmdreg.reset_cmd(verified=False, ref='<manual, page of *RST>')
COMMANDS['opc.query'] = cmdreg.opc_cmd(verified=False, ref='<manual, page of *OPC?>')
# If the model has *CLS / an error queue, also register 'status.clear' and 'err.query' (risk 'locked') so reset_to_defaults() clears and drains them.


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

    # No safe software reset at all (read-only remote protocol, ...)? Instead of COMMANDS['reset'] declare, on the class:
    #   RESET_EXEMPT = 'why there is no reset'          RESET_KNOWN_STATE = 'how its state is established instead'
    def _reset_extra(self):
        """Known-state steps after *RST / *CLS / *OPC? / error-queue drain: [(name, callable)]. Re-enter remote if the instrument leaves it,
        apply again whatever connect() sets, and CONFIRM sources are in standby / output off (raise SafetyError otherwise)."""
        return []

    def cleanup(self):
        """Leave the instrument safe (sources off, standby, local mode). Never raise."""
        try:
            pass
        except Exception:
            pass
