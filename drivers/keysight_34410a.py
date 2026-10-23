"""Keysight / Agilent 34410A 6 1/2-digit multimeter (unit under test) over GPIB, USB (USBTMC) or LAN, SCPI.

Commands come from the 34410A/11A/L4411A User's Guide (UG, printed page numbers) and the Service Guide (SG, printed page numbers).  The Programmer's Reference Help
(the full SCPI reference, on the Product Reference CD) was NOT supplied: a command or a reply text those two guides do not print is verified=False and is listed
in the procedure's final report.  Nothing here uses a CAL: command: the performance verification never adjusts the meter.

Interface facts used (UG chapter 3):
  * GPIB, USB and LAN are all enabled at power on; GPIB factory address 22 (UG p. 90-91).  There is NO RS-232 interface.
  * USB resource string: USB0::<mfgID>::<modID>::<serial#>::INSTR (UG p. 92); nothing to configure on the meter for USB.
  * Remote control is implicit (the Remote annunciator lights on interface activity); there is no SYST:REM.  Local: the front panel Shift / Local key
    (UG p. 38); over GPIB the transport's go_local() sends GTL.  For USB / LAN no command is documented in the guides, so none is sent.
Reset rule: *RST (UG p. 51; also SYSTem:PRESet, not used).  The error queue is NOT cleared by *RST (UG p. 85): the reset sequence drains it.
Writes are sent once, read back and compared; nothing is retried.  Only read-only queries (SYST:ERR? ...) may be retried.

34411A: the Service Guide verification tables, the SCPI commands used here and the specification pages are shared with the 34411A ("34410A/11A/L4411A"), so the 34411A
is the subclass Keysight34411A below (model flag: MODEL text, SHORT, IDN_MATCH): every command and every registry entry is the 34410A's.  The 34411A-only features
(digitizing at up to 50,000 readings per second, pre-trigger, internal level trigger, 1 million readings of memory, NPLC 0.001 / 0.002) are not part of the performance
verification and no command for them is in this driver.  The L4411A (no Front/Rear switch, no front panel) is NOT built.
"""
from __future__ import annotations

import math
import re

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import TransportError, bus_of

UG = "Keysight 34410A/11A/L4411A User's Guide"
SG = 'Keysight 34410A/11A/L4411A Service Guide'
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'FREQ')
NODE = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'OHM4': 'FRES', 'CAP': 'CAP'}
NPLC_KINDS = ('DCV', 'DCI', 'OHM2', 'OHM4')
AC_KINDS = ('ACV', 'ACI')
# What :SENS:FUNC? may answer for each kind (the reply text is UNVERIFIED: tolerant of quotes and case, exact about the function)
FUNC_ACCEPT = {'DCV': ('VOLT', 'VOLT:DC'), 'ACV': ('VOLT:AC',), 'DCI': ('CURR', 'CURR:DC'), 'ACI': ('CURR:AC',), 'OHM2': ('RES',), 'OHM4': ('FRES',),
               'CAP': ('CAP',), 'FREQ': ('FREQ',)}
RANGE_WINDOW = (0.5, 1.25)       # a range query is accepted between 0.5 x and 1.25 x the range asked for (so 757.5 / 1010 / 3.1 style replies pass; a range a decade away never does)
OVERFLOW = 9.0e37                # 9.9E+37 is the SCPI overload value
FIRMWARE_MIN = 2.05              # the specifications are valid for firmware revision 2.05 or later (UG p. 128)

P_NPLC, P_APER, P_BAND, P_RANGE, P_NULL, P_ZERO = 'p. 53', 'p. 56', 'p. 55', 'p. 59', 'p. 60', 'p. 57'


def _per_kind():
    out = {}
    for kind, node in NODE.items():
        k = kind.lower()
        printed = kind in ('ACV', 'ACI', 'OHM4', 'CAP')
        sg = {'ACV': 'p. 78 (CONFigure[:VOLTage]:AC)', 'ACI': 'p. 80 (CONFigure:CURRent:AC)', 'OHM4': 'p. 74 (CONFigure:FRESistance)', 'CAP': 'p. 86 (CONFigure:CAPacitance)'}.get(kind)
        out[f'conf.{k}'] = Cmd(f'CONF:{node} {{range:.9g}}', f'Configure {kind}', f'Selects {kind} with a manual range (CONFigure with a range sets a manual range, UG p. 59)',
                               placeholders={'range': Placeholder('float', '.9g', 1.0)}, kind='set', readback='func.query', verified=printed,
                               ref=(f'{SG}, {sg}; {UG}, p. 59 (a manual range may be set with CONFigure)' if printed else
                                    f'{UG}, p. 59 (CONFigure takes a range); the DC volts / DC current / 2-wire ohms CONFigure names are not printed in either guide'))
        out[f'range.query.{k}'] = Cmd(f'SENS:{node}:RANG?', f'{kind} range query', 'Reads back the range; the reply text is UNVERIFIED (the range upper limit expected)',
                                      kind='query', verified=False, ref=f'{UG}, {P_RANGE} (query stated, reply format not)')
        out[f'auto.query.{k}'] = Cmd(f'SENS:{node}:RANG:AUTO?', f'{kind} autorange query', 'Autorange must be off for every verification point: returns 0 (off) or 1 (on)',
                                     kind='query', verified=True, ref=f'{UG}, {P_RANGE} (RANGe:AUTO? returns "0" or "1")')
        if kind in NPLC_KINDS:
            out[f'nplc.{k}'] = Cmd(f'SENS:{node}:NPLC {{nplc:g}}', f'{kind} integration time (PLC)', '100 NPLC (footnote [1] of every DC, current and resistance table, SG pp. 69-75)',
                                   placeholders={'nplc': Placeholder('float', 'g', 100.0)}, kind='set', readback=f'nplc.query.{k}', verified=True,
                                   ref=f'{UG}, {P_NPLC} ([SENSe:]{node.replace(":", ":")}:NPLC); {SG}, pp. 69-75 "Select 100 NPLC"')
            out[f'nplc.query.{k}'] = Cmd(f'SENS:{node}:NPLC?', f'{kind} PLC query', 'Reads back the integration time (reply format UNVERIFIED)', kind='query', verified=False,
                                         ref=f'{UG}, {P_NPLC} (query stated, reply format not)')
        if kind in AC_KINDS:
            out[f'band.{k}'] = Cmd(f'SENS:{node}:BAND {{hz:g}}', f'{kind} AC filter (bandwidth)', 'The 3 Hz (slow) filter: 3, 20 or 200 Hz',
                                   placeholders={'hz': Placeholder('float', 'g', 3.0)}, kind='set', readback=f'band.query.{k}', verified=True,
                                   ref=f'{UG}, {P_BAND} ([SENSe:]VOLTage:AC:BANDwidth / CURRent:AC:BANDwidth); {SG}, pp. 78, 80')
            out[f'band.query.{k}'] = Cmd(f'SENS:{node}:BAND?', f'{kind} bandwidth query', 'Reads back the filter (reply format UNVERIFIED)', kind='query', verified=False,
                                         ref=f'{UG}, {P_BAND} (query stated, reply format not)')
    return out


COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queues (never overridable)', kind='set', risk='locked', verified=True,
                        ref=f'{UG}, p. 85 (*CLS clears both error queues)'),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest error, FIFO; reading removes it; "+0,"No error"" when empty (never overridable)', kind='query', risk='locked', verified=True,
                     ref=f'{UG}, p. 85 (SYSTem:ERRor[:NEXT]?; up to 20 errors)'),
    'rout.term': Cmd('ROUT:TERM?', 'Front / Rear switch', 'FRON or REAR (the switch cannot be set remotely)', kind='query', verified=True,
                     ref=f'{UG}, p. 50 (ROUTe:TERMinals? returns "FRON" or "REAR")'),
    'read': Cmd('READ?', 'Take a reading', 'One triggered reading (never retried); the immediate trigger source is the default after CONFigure and *RST', kind='query', verified=True,
                ref=f'{UG}, p. 70 (READ? initiates readings); reply text (exponent form) UNVERIFIED'),
    'func.query': Cmd('SENS:FUNC?', 'Function query', 'Reply text UNVERIFIED (the quoted function name, e.g. "VOLT:AC", expected)', kind='query', verified=False,
                      ref='not printed in the User\'s Guide or the Service Guide (Programmer\'s Reference Help not supplied)'),
    'conf.freq': Cmd('CONF:FREQ DEF,MIN', 'Configure frequency', 'Frequency function, default range, minimum resolution = 1 second aperture', kind='set', readback='func.query',
                     verified=True, ref=f'{SG}, p. 76 (CONFigure:FREQuency DEF, MIN)'),
    'freq.aper': Cmd('SENS:FREQ:APER {seconds:g}', 'Frequency gate time', '1 second (the resolution the manual selects: 0.1 ppm)',
                     placeholders={'seconds': Placeholder('float', 'g', 1.0)}, kind='set', readback='freq.aper.query', verified=True,
                     ref=f'{UG}, {P_APER} ([SENSe:]FREQuency:APERture {{<seconds>|MIN|MAX|DEF}}); {SG}, p. 76 (1 second aperture)'),
    'freq.aper.query': Cmd('SENS:FREQ:APER?', 'Frequency gate time query', 'Reads back the gate time (reply format UNVERIFIED)', kind='query', verified=False,
                           ref=f'{UG}, {P_APER} (query stated, reply format not)'),
    'freq.volt.rang': Cmd('SENS:FREQ:VOLT:RANG {range:g}', 'Frequency input voltage range', 'AC input voltage range of the frequency function. UNVERIFIED node name: the User\'s Guide says only that the '
                          'range commands of FREQuency set the AC signal input voltage range (p. 59); the node is taken from the Truevolt driver',
                          placeholders={'range': Placeholder('float', 'g', 1.0)}, kind='set', readback='freq.volt.rang.query', verified=False,
                          ref=f'{UG}, p. 59 (FREQuency / PERiod range commands affect the AC input voltage range); exact SCPI node not printed'),
    'freq.volt.rang.query': Cmd('SENS:FREQ:VOLT:RANG?', 'Frequency input range query', 'Reads back the input range (reply format and node UNVERIFIED)', kind='query', verified=False,
                                ref=f'{UG}, p. 59 (not printed)'),
    'azero.query': Cmd('SENS:VOLT:DC:ZERO:AUTO?', 'DC volts autozero state', 'Autozero must be ON (the *RST default): the specifications assume it. Returns 0 or 1', kind='query', verified=True,
                       ref=f'{UG}, {P_ZERO} (ZERO:AUTO? returns "0" or "1"); p. 87 (autozero On after reset)'),
}
COMMANDS.update(_per_kind())
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{UG}, p. 51 (*RST resets most settings to factory; SYSTem:PRESet is not used); p. 87 (Power-On and Reset State)',
                                     note='The error queue is not cleared by *RST (UG p. 85): it is drained afterwards.')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, 'not printed in the User\'s Guide or the Service Guide (IEEE 488.2 common command; Programmer\'s Reference Help not supplied)')


def _text(reply):
    return str(reply).strip().strip('"\'').strip().upper()


def _number(reply):
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(reply))
    if not m:
        raise InstrumentError(f'no number in the reply {str(reply).strip()!r}')
    return float(m.group(0))


def _flag(reply):
    t = _text(reply)
    if t in ('1', '+1', 'ON'):
        return True
    if t in ('0', '+0', 'OFF'):
        return False
    raise InstrumentError(f'expected 0/1 or ON/OFF, the meter answered {str(reply).strip()!r}')


class Keysight34410A(Instrument):
    MODEL = 'Keysight 34410A'
    SHORT = '34410A'                    # the model name used in messages (the 34411A subclass overrides it)
    IDN_MATCH = ('34410A',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 30.0              # 100 NPLC with autozero takes about 4 s; an AC reading with the 3 Hz filter about 2.5 s plus the settling delay
    DEFAULT_GPIB_ADDRESS = 22           # UG p. 90

    @property
    def bus(self) -> str:
        """'GPIB', 'USB' or 'LAN' from the transport (a simulator may carry a .bus attribute)."""
        return getattr(self.t, 'bus', None) or bus_of(str(getattr(self.t, 'name', '') or ''))

    @property
    def firmware(self) -> str:
        """The firmware revision text of *IDN? (fourth field), '' when it cannot be read."""
        parts = [x.strip() for x in self.idn.split(',')]
        return parts[3] if len(parts) >= 4 else ''

    def firmware_warning(self) -> str:
        """A warning when the revision is below 2.05 (the specifications are valid for 2.05 or later, UG p. 128); '' otherwise or when it cannot be read."""
        m = re.match(r'\s*(\d+)\.(\d+)', self.firmware)
        if m and float(f'{m.group(1)}.{m.group(2)}') < FIRMWARE_MIN:
            return f'firmware {self.firmware}: the published specifications are valid for firmware 2.05 or later (User\'s Guide p. 128)'
        return ''

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    def connect(self):
        """Open, clear the interface and the status registers, confirm the model.  There is no remote command: control is implicit (UG p. 38)."""
        self.open(verify_model=False)
        self.t.clear()                                      # device clear: empties the input buffer and output queue
        self.send('status.clear')
        try:
            self.idn = self.identify()
        except TransportError as exc:
            self.close()
            raise InstrumentError(f'The {self.SHORT} did not answer *IDN? ({exc}). Check the GPIB address (factory 22) or the USB / VISA resource.') from exc
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a {self.SHORT} but the instrument identifies as: {self.idn!r}')
        return self

    def local(self):
        """Back to the front panel: GTL over GPIB (the transport sends it).  USB / LAN: no command is documented; press Shift / Local on the meter (UG p. 38)."""
        if self.bus == 'GPIB':
            self.t.go_local()

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    def _reset_extra(self):
        return [('known measurement state (autozero on)', self._known_state)]

    def _known_state(self):
        """After *RST autozero is ON (UG p. 87); the specifications assume it."""
        if not _flag(self.ask('azero.query')):
            raise InstrumentError('autozero is OFF: the specification (and this verification) assumes autozero ON')
        return 'autozero on'

    # ---- configuration of one test point (set, read back, compare; a write is never retried) ------------------------------
    @staticmethod
    def range_ok(reply, range_value: float) -> bool:
        v = abs(_number(reply))
        return RANGE_WINDOW[0] * range_value <= v <= RANGE_WINDOW[1] * range_value

    def _confirm(self, what, ok, reply):
        if not ok:
            raise InstrumentError(f'{self.label}: {what} was not accepted: the {self.SHORT} answered {str(reply).strip()!r}')

    def configure_point(self, point: dict):
        """Function, manual range, integration time (100 NPLC) or AC filter (3 Hz) for one verification point.  Never autorange.
        point: kind, range (ohm / V / A / F; for FREQ the input voltage range), optional plc (default 100), optional ac_bandwidth / filter_hz (default 3),
        optional aperture_s (FREQ, default 1)."""
        kind, rng = point['kind'], float(point['range'])
        if kind not in KINDS:
            raise InstrumentError(f'{self.label}: no function for kind {kind!r}')
        k = kind.lower()
        if kind == 'FREQ':
            self.send('conf.freq')
            reply = self.ask('func.query')
            self._confirm('the frequency function', _text(reply) in FUNC_ACCEPT['FREQ'], reply)
            ap = float(point.get('aperture_s') or 1)
            self.send('freq.aper', seconds=ap)
            reply = self.ask('freq.aper.query')
            self._confirm(f'gate time {ap:g} s', math.isclose(_number(reply), ap, rel_tol=1e-6), reply)
            self.send('freq.volt.rang', range=rng)
            reply = self.ask('freq.volt.rang.query')
            self._confirm(f'the {rng:g} V input range', self.range_ok(reply, rng), reply)
            return
        self.send(f'conf.{k}', range=rng)
        reply = self.ask('func.query')
        self._confirm(f'function {kind}', _text(reply) in FUNC_ACCEPT[kind], reply)
        reply = self.ask(f'range.query.{k}')
        self._confirm(f'the {rng:g} range', self.range_ok(reply, rng), reply)
        reply = self.ask(f'auto.query.{k}')
        self._confirm('autorange off', not _flag(reply), reply)
        if kind in NPLC_KINDS:
            nplc = float(point.get('plc') or 100)
            self.send(f'nplc.{k}', nplc=nplc)
            reply = self.ask(f'nplc.query.{k}')
            self._confirm(f'{nplc:g} PLC', math.isclose(_number(reply), nplc, rel_tol=1e-6), reply)
        elif kind in AC_KINDS:
            hz = float(point.get('ac_bandwidth') or point.get('filter_hz') or 3)
            self.send(f'band.{k}', hz=hz)
            reply = self.ask(f'band.query.{k}')
            self._confirm(f'AC filter {hz:g} Hz', math.isclose(_number(reply), hz, rel_tol=1e-6), reply)

    # ---- readings ----------------------------------------------------------------------------------------------------------
    @staticmethod
    def _reading(reply, short='34410A') -> float:
        value = _number(reply)
        if not math.isfinite(value) or abs(value) >= OVERFLOW:
            raise InstrumentError(f'The {short} reported an overload / invalid reading ({str(reply).strip()!r}): wrong range or nothing connected.')
        return value

    def read(self) -> float:
        """READ? -> one reading.  Never retried."""
        return self._reading(self.ask('read'), self.SHORT)

    def front_rear(self) -> str:
        """ROUT:TERM? -> 'FRONT' or 'REAR' (the switch cannot be set remotely)."""
        reply = _text(self.ask('rout.term'))
        return 'FRONT' if reply.startswith('FRON') else 'REAR' if reply.startswith('REAR') else reply

    def check_errors(self, context: str = ''):
        """Raise if the error queue holds anything: read until '+0,"No error"' (at most 21 reads: the queue holds 20, UG p. 85)."""
        found = []
        for _ in range(21):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))


class Keysight34411A(Keysight34410A):
    """Keysight / Agilent 34411A: the same SCPI, the same verification tables and the same Front/Rear switch as the 34410A (Service Guide pp. 68-87 are headed
    "34410A/11A"); only the model text the *IDN? must contain and the messages differ.  Digitizing / pre-trigger / reading-memory commands are not used."""
    MODEL = 'Keysight 34411A'
    SHORT = '34411A'
    IDN_MATCH = ('34411A',)
