"""Fluke 5790B AC Measurement Standard - the AC voltage reference for the function-generator procedures.

Commands are from the 5790B Operators Manual (June 2015), Chapter 6 Remote Commands:
  *IDN? (p. 6-19)  ERR? (p. 6-46)  EXTRIG / EXTRIG? (pp. 6-46, 6-47)  INPUT / INPUT? (p. 6-49)
  MEAS? (p. 6-53)  RANGE / RANGE? (pp. 6-54, 6-55)  *CLS (p. 6-11)  *OPT? (p. 6-21)
Wideband (options /3, /5, /AF): WBND input, 50 ohm, 600 uV to 7 V, 10 Hz to 30 or 50 MHz (pp. 4-31, 4-32), 10 V rms maximum
non-destructive input; flatness is specified relative to 1 kHz (Absolute Wideband Specifications, pp. 1-20 to 1-22).
Input impedance (Table 4-4, p. 4-9): INPUT 1 / INPUT 2 are 10 MOhm on the 2.2 V range and below, 50 kOhm on the
7 V to 220 V ranges. RS-232 defaults (pp. 5-5, 5-6): 9600 baud, 8 data bits, 1 stop bit, no parity, XON/XOFF, CR LF;
set Remote IF to Computer (Setup Menu > System Settings > Remote Port > RS-232 Setup), not the default Terminal, and make
RS-232 the Active Remote Port. GPIB and USB need no port settings.

Every setting is written, read back and compared. MEAS? is a query; it is repeated only while the 5790B reports the
reading as not yet settled (codes 3 and 4), never after a communication error.
"""
from __future__ import annotations

import time

from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import SerialSettings

SERIAL_DEFAULT = SerialSettings(baud=9600, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r\n', read_termination='\r\n', flow_control='xon_xoff')

INPUTS = ('INPUT1', 'INPUT2', 'AUX', 'WBND')

# MEAS? third field (p. 6-53). Only the highest-numbered condition that is true is reported.
MEAS_CODES = {0: 'valid', 1: 'frequency underrange', 2: 'frequency overrange', 3: 'settled, digital filter not full',
              4: 'unsettled', 5: 'value underrange', 6: 'value overrange', 7: 'value invalid'}
WAIT_CODES = (3, 4)

_REF = '5790B Operators Manual (June 2015), Chapter 6'

# Every command the driver sends (same text and format specs the old f-strings used). All of them are taken from the manual and have NOT
# been run on hardware (NOTES.md), so verified=False throughout. The 5790B is a measuring instrument with no output to enable.
# *CLS and ERR? are bootstrap / error-queue plumbing (risk 'locked', never overridable).
COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False, ref=_REF + ' p. 6-11'),
    'err.query': Cmd('ERR?', 'Error queue', "Oldest error; '0,\"No Error\"' when empty (never overridable)", kind='query', risk='locked',
                     verified=False, ref=_REF + ' p. 6-46'),
    'input.set': Cmd('INPUT {name}', 'Select input', 'INPUT1, INPUT2, AUX or WBND',
                     placeholders={'name': Placeholder('enum', '', 'INPUT1', enum=INPUTS)}, kind='set', readback='input.query',
                     verified=False, ref=_REF + ' p. 6-49'),
    'input.query': Cmd('INPUT?', 'Selected input', kind='query', verified=False, ref=_REF + ' p. 6-49'),
    'extrig.on': Cmd('EXTRIG ON', 'External trigger on', 'Each MEAS? starts a fresh measurement', kind='set', readback='extrig.query',
                     verified=False, ref=_REF + ' pp. 6-46, 6-47'),
    'extrig.off': Cmd('EXTRIG OFF', 'External trigger off', 'Continuous triggering (also sent at cleanup)', kind='set',
                      readback='extrig.query', verified=False, ref=_REF + ' pp. 6-46, 6-47'),
    'extrig.query': Cmd('EXTRIG?', 'External trigger mode', kind='query', verified=False, ref=_REF + ' pp. 6-46, 6-47'),
    'range.query': Cmd('RANGE?', 'Range', 'Range max, range min, resolution, autoranging', kind='query', verified=False,
                       ref=_REF + ' p. 6-55'),
    'range.set': Cmd('RANGE {volts:.6g}', 'Select and lock a range', 'The range that measures this many volts',
                     placeholders={'volts': Placeholder('float', '.6g', 1.0)}, kind='set', readback='range.query', verified=False,
                     ref=_REF + ' p. 6-54'),
    'range.auto': Cmd('RANGE AUTO', 'Autorange', kind='set', readback='range.query', verified=False, ref=_REF + ' p. 6-54'),
    'opt.query': Cmd('*OPT?', 'Installed options', 'WBND / WBEX / WBAF for the wideband module', kind='query', verified=False,
                     ref=_REF + ' p. 6-21'),
    'wbaf.query': Cmd('WBAF?', '50 MHz cable correction', 'Reply format undocumented in the manual (summary p. 6-14, no detail page)',
                      kind='query', verified=False, ref=_REF + ' p. 6-14'),
    'meas.query': Cmd('MEAS?', 'Measurement', 'Volts, Hz, status code; repeated only while the code says not yet settled', kind='query',
                      verified=False, ref=_REF + ' p. 6-53'),
}


class Fluke5790B(Instrument):
    MODEL = 'Fluke 5790B'
    IDN_MATCH = ('5790B',)
    DEFAULT_TIMEOUT = 30.0
    COMMANDS = COMMANDS
    last_input = ''

    def connect(self):
        """Open, check the model (a 5790B set to emulate a 5790A identifies as a 5790A), clear status."""
        self.open(verify_model=False)
        self.idn = self.identify()
        up = self.idn.upper()
        if '5790B' not in up:
            self.close()
            if '5790A' in up:
                raise InstrumentError('The 5790B identifies as a 5790A: 5790A emulation is on. Turn it off '
                                      '(Setup Menu > System Settings, Emulate 5790A) and connect again.')
            raise InstrumentError(f'Expected a Fluke 5790B but the instrument identifies as: {self.idn!r}')
        self.send('status.clear')
        self.check_error('clear status')
        return self

    # ---- error queue ---------------------------------------------------------------------------------
    def check_error(self, context=''):
        """ERR? returns '0,"No Error"' when the queue is empty (p. 6-46). Raise on anything else."""
        reply = self.ask('err.query').strip()
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            failed = int(code) != 0
        except ValueError:
            failed = True
        if failed:
            raise InstrumentError(f'5790B reported an error{" (" + context + ")" if context else ""}: {reply}')

    # ---- settings (write, read back, compare) --------------------------------------------------------
    def select_input(self, name='INPUT1'):
        name = name.upper()
        if name not in INPUTS:
            raise InstrumentError(f'5790B input must be one of {INPUTS}, not {name!r}')
        self.send('input.set', name=name)
        got = self.ask('input.query').strip().upper()
        if got != name:
            raise InstrumentError(f'5790B input set {name}, reports {got}')
        self.check_error(f'input {name}')
        self.last_input = name

    def set_external_trigger(self, on=True):
        """EXTRIG ON: each MEAS? starts a fresh measurement (p. 6-46)."""
        self.send('extrig.on' if on else 'extrig.off')
        got = self.ask('extrig.query').strip()
        if got != ('1' if on else '0'):
            raise InstrumentError(f'5790B EXTRIG set {"ON" if on else "OFF"}, reports {got}')
        self.check_error('trigger mode')

    def range_info(self):
        """RANGE? -> (range max, range min, resolution, autoranging) (p. 6-55)."""
        parts = [x.strip() for x in self.ask('range.query').strip().split(',')]
        if len(parts) < 4:
            raise InstrumentError(f'Unexpected RANGE? reply: {",".join(parts)}')
        return float(parts[0]), float(parts[1]), float(parts[2]), parts[3] == '1'

    def set_range_for(self, volts):
        """RANGE <value> selects and locks the range that measures `volts` (p. 6-54); checked with RANGE?."""
        self.send('range.set', volts=abs(volts))
        hi, lo, _res, auto = self.range_info()
        if auto or not (lo <= abs(volts) <= hi * 1.01):
            raise InstrumentError(f'5790B range for {volts:g} V: RANGE? reports {lo:g} to {hi:g} V, autorange {"on" if auto else "off"}')
        self.check_error(f'range for {volts:g} V')
        return hi

    def set_autorange(self):
        self.send('range.auto')
        if not self.range_info()[3]:
            raise InstrumentError('5790B did not confirm autoranging')
        self.check_error('autorange')

    # ---- wideband option ------------------------------------------------------------------------------
    WIDEBAND_MAX_HZ = {'WBND': 30e6, 'WBEX': 50e6, 'WBAF': 50e6}   # *OPT? replies (p. 6-21); 0 = no wideband

    def wideband_option(self):
        """*OPT? -> 'WBND' (30 MHz), 'WBEX' / 'WBAF' (50 MHz), or '' when no wideband module is installed."""
        reply = self.ask('opt.query').strip().strip('"').upper()
        return next((o for o in self.WIDEBAND_MAX_HZ if o in reply), '')

    def require_wideband(self, max_hz):
        """Raise unless a wideband module covering max_hz is installed and the /AF 50 MHz cable correction is off.
        The correction (WBAF, summary p. 6-14; no detail page in the manual) is only read, never set."""
        opt = self.wideband_option()
        if not opt:
            raise InstrumentError('This 5790B has no wideband option (*OPT? reports none). Use the power-meter method for flatness.')
        if self.WIDEBAND_MAX_HZ[opt] < max_hz:
            raise InstrumentError(f'The 5790B wideband option ({opt}) covers {self.WIDEBAND_MAX_HZ[opt] / 1e6:g} MHz; '
                                  f'the flatness test needs {max_hz / 1e6:g} MHz.')
        if opt == 'WBAF':
            state = self.ask('wbaf.query').strip().upper()
            if state not in ('0', 'OFF'):
                raise InstrumentError(f'The 5790B 50 MHz cable correction is on (WBAF? -> {state}). It applies only to the 50 MHz '
                                      'spot calibration; turn it off (wideband menu, 50 MHz Cable Correction) and continue.')
        return opt

    # ---- measurement ---------------------------------------------------------------------------------
    def measure(self, timeout=60.0, poll=1.0):
        """MEAS? until the reading is valid (code 0). Returns (volts rms, frequency Hz).
        Codes 3 / 4 (filter not full, unsettled) are waited out; 1, 2, 5, 6, 7 raise."""
        deadline = time.monotonic() + timeout
        last = None
        while True:
            parts = [x.strip() for x in self.ask('meas.query').strip().split(',')]
            if len(parts) < 3:
                raise InstrumentError(f'Unexpected MEAS? reply: {",".join(parts)}')
            volts, freq, code = float(parts[0]), float(parts[1]), int(float(parts[2]))
            if code == 0:
                return volts, freq
            last = code
            if code not in WAIT_CODES:
                raise InstrumentError(f'5790B measurement not valid: {MEAS_CODES.get(code, code)} (reading {volts:g} V at {freq:g} Hz)')
            if time.monotonic() > deadline:
                raise InstrumentError(f'5790B reading did not settle within {timeout:g} s (last status: {MEAS_CODES.get(last, last)})')
            time.sleep(poll)

    def cleanup(self):
        """Return to continuous triggering so the front panel shows live readings. Never raises."""
        try:
            self.send('extrig.off')
        except Exception:
            pass
