"""Keithley Model 2000 6 1/2-digit multimeter (unit under test) over GPIB or RS-232, SCPI language only.

Every command is taken from the Model 2000 User Manual (2000-900 Rev. J, Aug 2010); each COMMANDS entry carries the printed page it comes from
(chapter 4 pages are "4-n", chapter 5 pages "5-n") and a verified flag.  A command or a reply format the manual does not state is verified=False
and is listed in the procedure's final report.  Nothing here uses a calibration (CAL:) command: the performance verification never adjusts the meter.

Interface facts used (User Manual, chapter 4):
  * GPIB is the factory interface, primary address 16 (p. 4-12); RS-232 is selected from the front panel (p. 4-3).  Only one interface at a time.
  * SCPI is the factory language and the only one RS-232 supports; the 196/199 and 8840A/8842A languages are GPIB only (p. 4-4).
  * RS-232: 8 data bits, 1 stop bit, no parity (p. 4-6); baud 19.2k, 9600, 4800, 2400, 1200, 600 or 300, factory 4800 (p. 4-6); flow control NONE or
    XonXoFF, no hardware handshaking (p. 4-7); the meter processes a command after the <CR> (p. 4-7); its own replies end with LF, CR or LFCR as set by
    TX TERM (p. 4-7).  The factory flow control and TX TERM values are not stated (the factory-defaults table says "no effect"): UNVERIFIED defaults below.
  * :SYSTem:REMote / :LOCal / :RWLock exist for RS-232 only (p. 5-67).  On GPIB the meter goes remote when addressed and returns to local on GTL (p. 4-15) or
    the front panel LOCAL key (p. 4-18); the transport's go_local() sends GTL.
Reset rule: *RST (never :SYSTem:PRESet, which turns continuous initiation ON and the filter to MOVing, p. 5-18 / p. 5-16).  After *RST: INIT:CONT is OFF, the
trigger source is IMMediate with count 1 (Table 5-10 note 1 and 2), autozero is ON (Table 5-8), and the digital filter is REPeat type (Table 5-6 note).
Writes are sent once, read back and compared; nothing is retried.  Only read-only queries (:SYST:ERR?, :FETC? ...) may be retried.
"""
from __future__ import annotations

import math
import re

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .fluke_5560a import Fluke5522A
from .transport import SerialSettings, TransportError, bus_of

UM = 'Keithley 2000 User Manual 2000-900 Rev. J'
CM = 'Keithley 2000 Calibration Manual 2000-905-01 Rev. F'
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4')
# SCPI node of each function's configuration subsystem and the name :FUNCtion takes (Table 5-6 p. 5-11 to 5-14, :FUNCtion p. 5-37)
NODE = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'OHM4': 'FRES'}
FUNC_NAME = dict(NODE)
AC_KINDS = ('ACV', 'ACI')
# printed page of each per-function command family
P_FUNC, P_NPLC, P_RANGE, P_AUTO, P_REF, P_REFST, P_AVER_ST, P_AVER_CT, P_BAND = '5-37', '5-40', '5-41', '5-42', '5-43', '5-44', '5-46', '5-47', '5-48'
RANGE_WINDOW = (0.5, 1.25)            # a range query is accepted between 0.5 x and 1.25 x the range asked for (the reply format is UNVERIFIED, see range_ok)
SELECT_FRACTION = 0.9                 # :RANGe <n> takes the EXPECTED reading and picks the most sensitive range that accommodates it (p. 5-41): 90 % of the range
OVERFLOW = 9.0e37                     # "An overflow reading reads as +9.9e37" (p. 5-31)

# What the reply to each read-back query is compared with.  The manual states the queries but not their reply text: every one of these is UNVERIFIED
# until seen on a 2000.  They are tolerant (case, quotes, 0 / OFF, 1 / ON, a number in any exponent form) and strict only about a clearly different value.
FUNC_ACCEPT = {'DCV': ('VOLT:DC', 'VOLT'), 'ACV': ('VOLT:AC',), 'DCI': ('CURR:DC', 'CURR'), 'ACI': ('CURR:AC',), 'OHM2': ('RES',), 'OHM4': ('FRES',)}

SERIAL_DEFAULT = SerialSettings(baud=4800, data_bits=8, parity='none', stop_bits=1, write_termination='\r', read_termination='\n', flow_control='none')
BAUDS = (19200, 9600, 4800, 2400, 1200, 600, 300)        # p. 4-6
TX_TERM = {'LF': '\n', 'CR': '\r', 'LFCR': '\r'}          # p. 4-7: LF, CR or LFCR. LFCR is read up to the last CR; a leading LF of the next reply is stripped (order UNVERIFIED)


def _pages(*pp):
    return f'{UM}, p. ' + ', '.join(pp)


def _per_kind():
    """The function-specific commands, one key per function (the keys are '<name>.<kind lower case>')."""
    out = {}
    for kind in KINDS:
        k, n = kind.lower(), NODE[kind]
        out[f'func.{k}'] = Cmd(f":SENS:FUNC '{FUNC_NAME[kind]}'", f'Select {kind}', f'Selects the {kind} function; the function is read back with :FUNC? (the reply text is UNVERIFIED)',
                               kind='set', readback='func.query', verified=True, ref=_pages(P_FUNC + ' (:FUNCtion)'))
        out[f'range.{k}'] = Cmd(f':SENS:{n}:RANG {{expected:.9g}}', f'{kind} range', 'Takes the EXPECTED reading as an absolute value and selects the most sensitive range that '
                                'accommodates it; a valid :RANGe command also turns autorange off',
                                placeholders={'expected': Placeholder('float', '.9g', 1.0)}, kind='set', readback=f'range.query.{k}', verified=True,
                                ref=_pages(P_RANGE + ' (:RANGe[:UPPer])', P_AUTO + ' (:RANGe:AUTO coupling)'))
        out[f'range.query.{k}'] = Cmd(f':SENS:{n}:RANG?', f'{kind} range query', 'Reads back the range; the reply format (the range upper limit, 0.5 to 1.25 x the range) is UNVERIFIED',
                                      kind='query', verified=False, ref=_pages(P_RANGE + ' (query stated, reply format not)'))
        out[f'auto.query.{k}'] = Cmd(f':SENS:{n}:RANG:AUTO?', f'{kind} autorange query', 'Autorange must be off for every verification point (CM p. 1-6)',
                                     kind='query', verified=True, ref=_pages(P_AUTO + ' (:AUTO?)') + f'; {CM} p. 1-6')
        if kind not in AC_KINDS:
            out[f'nplc.{k}'] = Cmd(f':SENS:{n}:NPLC {{nplc:g}}', f'{kind} integration time (PLC)', 'Medium speed = 1 PLC (CM p. 1-5: "Speed: medium")',
                                   placeholders={'nplc': Placeholder('float', 'g', 1.0)}, kind='set', readback=f'nplc.query.{k}', verified=True,
                                   ref=_pages(P_NPLC + ' (:NPLCycles)') + f'; {CM} p. 1-5')
            out[f'nplc.query.{k}'] = Cmd(f':SENS:{n}:NPLC?', f'{kind} PLC query', 'Reads back the integration time (reply format UNVERIFIED)', kind='query', verified=False,
                                         ref=_pages(P_NPLC + ' (query stated, reply format not)'))
        else:
            out[f'band.{k}'] = Cmd(f':SENS:{n}:DET:BAND {{hz:g}}', f'{kind} detector bandwidth', 'AC rate: 3 (slow), 30 (medium, factory) or 300 (fast); the NPLC setting is '
                                   'valid for AC only at bandwidth 300',
                                   placeholders={'hz': Placeholder('float', 'g', 30.0)}, kind='set', readback=f'band.query.{k}', verified=True,
                                   ref=_pages(P_BAND + ' (:BANDwidth)') + f'; User Manual Table 2-2 (medium = DETector BANDwidth 30)')
            out[f'band.query.{k}'] = Cmd(f':SENS:{n}:DET:BAND?', f'{kind} bandwidth query', 'Reads back the bandwidth (reply format UNVERIFIED)', kind='query', verified=False,
                                         ref=_pages(P_BAND + ' (query stated, reply format not)'))
        out[f'tcon.{k}'] = Cmd(f':SENS:{n}:AVER:TCON REP', f'{kind} filter type', 'REPeat filter: each :READ? is the average of the filter count of fresh conversions '
                               '(Trigger Model device action, p. 4-30). Set before the count and the state ("changing the filter type disables auto filter")',
                               kind='set', readback=f'tcon.query.{k}', verified=True, ref=_pages(P_AVER_ST + ' (:TCONtrol)', '4-30 (device action)'))
        out[f'tcon.query.{k}'] = Cmd(f':SENS:{n}:AVER:TCON?', f'{kind} filter type query', 'Reply format UNVERIFIED (REP / REPEAT)', kind='query', verified=False,
                                     ref=_pages(P_AVER_ST + ' (query stated, reply format not)'))
        out[f'count.{k}'] = Cmd(f':SENS:{n}:AVER:COUN {{count:d}}', f'{kind} filter count', 'Filter of 10 readings (CM p. 1-5: "Filter: 10 readings")',
                                placeholders={'count': Placeholder('int', 'd', 10)}, kind='set', readback=f'count.query.{k}', verified=True,
                                ref=_pages(P_AVER_CT + ' (:COUNt)') + f'; {CM} p. 1-5')
        out[f'count.query.{k}'] = Cmd(f':SENS:{n}:AVER:COUN?', f'{kind} filter count query', 'Reply format UNVERIFIED', kind='query', verified=False,
                                      ref=_pages(P_AVER_CT + ' (query stated, reply format not)'))
        out[f'filter.{k}'] = Cmd(f':SENS:{n}:AVER:STAT ON', f'{kind} filter on', 'Digital filter ON (CM p. 1-12 step 4 for resistance; the specification sheet condition '
                                 '"MED (1 PLC) with filter of 10")', kind='set', readback=f'filter.query.{k}', verified=True,
                                 ref=_pages(P_AVER_ST + ' (:STATe)') + f'; {CM} p. 1-12')
        out[f'filter.query.{k}'] = Cmd(f':SENS:{n}:AVER:STAT?', f'{kind} filter state query', 'Reply format UNVERIFIED (0 / 1 expected)', kind='query', verified=False,
                                       ref=_pages(P_AVER_ST + ' (query stated, reply format not)'))
        out[f'rel.{k}'] = Cmd(f':SENS:{n}:REF:STAT {{state}}', f'{kind} REL (reference) state', 'REL is enabled only for DC volts (CM p. 1-7) and disabled for the AC '
                              'volts tests (CM p. 1-8); the other functions are put OFF',
                              placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback=f'rel.query.{k}', verified=True,
                              ref=_pages(P_REFST + ' (:REFerence:STATe)') + f'; {CM} pp. 1-7, 1-8')
        out[f'rel.query.{k}'] = Cmd(f':SENS:{n}:REF:STAT?', f'{kind} REL state query', 'The manual says "0 or 1" for DC volts; other functions UNVERIFIED', kind='query',
                                    verified=kind == 'DCV', ref=_pages(P_REFST + ' (:STATe?)'))
    out['rel.acq.dcv'] = Cmd(':SENS:VOLT:DC:REF:ACQ', 'Acquire DCV reference (zero)', 'Uses the latest reading as the REL reference. Only works when a reading has been '
                             'triggered and is not overflowed, and only on the selected function (an error otherwise)', kind='action', readback='rel.value.dcv', verified=True,
                             ref=_pages(P_REFST + ' (:ACQuire)'))
    out['rel.value.dcv'] = Cmd(':SENS:VOLT:DC:REF?', 'DCV reference value', 'Reads back the acquired reference (the value of the reading it was taken from)', kind='query',
                               verified=True, ref=_pages(P_REF + ' (:REFerence?: returns the acquired value after :ACQuire)'))
    return out


COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the event registers and the error queue (never overridable)', kind='set', risk='locked', verified=True,
                        ref=f'{UM}, p. 4-40 (*CLS)'),
    'err.query': Cmd(':SYST:ERR?', 'Error queue', 'Oldest error or status message (reading removes it); "0, No error" when empty (never overridable)', kind='query',
                     risk='locked', verified=True, ref=f'{UM}, p. 5-63 (:SYSTem:ERRor?); p. 5-59 (:STATus:QUEue[:NEXT]? is equivalent)'),
    'frsw.query': Cmd(':SYST:FRSW?', 'INPUTS switch', '1 = front panel inputs, 0 = rear (the switch cannot be set remotely)', kind='query', verified=True,
                      ref=f'{UM}, p. 5-62 (:FRSWitch?)'),
    'remote': Cmd(':SYST:REM', 'Remote mode (RS-232 only)', 'Places the 2000 in remote; RS-232 only, the GPIB interface goes remote when addressed', kind='set', verified=True,
                  ref=f'{UM}, p. 5-67 (:REMote)'),
    'local': Cmd(':SYST:LOC', 'Local mode (RS-232 only)', 'Takes the 2000 out of remote and restores the front panel keys; RS-232 only (GPIB: GTL)', kind='set', verified=True,
                 ref=f'{UM}, p. 5-67 (:LOCal)'),
    'azero.query': Cmd(':SYST:AZER:STAT?', 'Autozero state', 'Autozero must be ON (the default): the specification assumes it (autozero off adds error)', kind='query',
                       verified=True, ref=f'{UM}, p. 5-64 (:AZERo:STATe?); specification sheet "Autozero off error"'),
    'init.cont': Cmd(':INIT:CONT OFF', 'Continuous initiation off', ':READ? needs continuous initiation OFF (the *RST default); with it ON the meter answers "Init ignored"',
                     kind='set', readback='init.cont.query', verified=True, ref=f'{UM}, p. 5-70 (:INITiate:CONTinuous); p. 5-5 (:READ?)'),
    'init.cont.query': Cmd(':INIT:CONT?', 'Continuous initiation query', 'Reply format UNVERIFIED (0 / 1 expected)', kind='query', verified=False,
                           ref=f'{UM}, p. 5-70 (query stated, reply format not)'),
    'form.elem': Cmd(':FORM:ELEM READ', 'Reading element only', 'The data string holds the reading alone (no channel, no units); the *RST default', kind='set',
                     readback='form.elem.query', verified=True, ref=f'{UM}, p. 5-31 (:ELEMents); Table 5-4 p. 5-9'),
    'form.elem.query': Cmd(':FORM:ELEM?', 'Data elements query', 'Reply format UNVERIFIED (READ expected)', kind='query', verified=False,
                           ref=f'{UM}, p. 5-31 (query stated, reply format not)'),
    'func.query': Cmd(':SENS:FUNC?', 'Function query', 'Reply text UNVERIFIED (the quoted function name expected)', kind='query', verified=False,
                      ref=f'{UM}, p. 5-37 (query stated, reply format not)'),
    'read': Cmd(':READ?', 'Take a reading', ':ABORt, :INITiate, :FETCh?: one triggered reading, in exponent form (+1.000000E+01); never retried', kind='query', verified=True,
                ref=f'{UM}, p. 5-5 (:READ?); p. 5-38 (reading in exponent form)'),
    'fetch': Cmd(':FETC?', 'Latest reading', 'The latest reading without triggering (it can return the same reading again)', kind='query', verified=True,
                 ref=f'{UM}, p. 5-4 (:FETCh?)'),
}
COMMANDS.update(_per_kind())
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{UM}, p. 4-39 (Table 4-4: *RST returns the 2000 to the *RST default conditions); '
                                     'Tables 5-2 to 5-11 list them (:SYSTem:PRESet is NOT used: it differs, p. 5-61)',
                                     note='Never :SYSTem:PRESet. Remote mode is entered again afterwards on RS-232.')
COMMANDS['opc.query'] = cmdreg.opc_cmd(True, f'{UM}, p. 4-39 (Table 4-4: *OPC? places an ASCII 1 in the output queue when all pending operations are complete)')


def _text(reply):
    return str(reply).strip().strip('"\'').strip().upper()


def _number(reply):
    """The first number in a reply (exponent form, optional units / quotes). InstrumentError when there is none."""
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
    raise InstrumentError(f'expected 0/1 or ON/OFF, the 2000 answered {str(reply).strip()!r}')


class Keithley2000(Instrument):
    MODEL = 'Keithley 2000'
    IDN_MATCH = ('MODEL 2000',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 30.0              # AC readings with the 10-reading filter at the medium rate take about 7 s (specification sheet: 1.4 readings/s)
    SERIAL = SERIAL_DEFAULT
    DEFAULT_GPIB_ADDRESS = 16           # p. 4-12

    # ---- interface -----------------------------------------------------------------------------------------------
    @property
    def bus(self) -> str:
        """'GPIB', 'RS232', ... from the transport (a simulator may carry a .bus attribute)."""
        return getattr(self.t, 'bus', None) or bus_of(str(getattr(self.t, 'name', '') or ''))

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def connect(self):
        """Open, clear the interface and the status registers, confirm the model, enter remote on RS-232."""
        self.open(verify_model=False)
        self.t.clear()                                      # device clear: empties the input buffer and output queue, settings untouched (p. 4-16)
        self.send('status.clear')
        try:
            self.idn = self.identify()
        except TransportError as exc:
            self.close()
            raise InstrumentError(f'The Model 2000 did not answer *IDN? ({exc}). Check the GPIB address / the RS-232 baud rate and TX TERM, and that the language is SCPI '
                                  '(User Manual p. 4-4); RS-232 supports SCPI only.') from exc
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a Keithley Model 2000 but the instrument identifies as: {self.idn!r}')
        self.remote()
        return self

    def remote(self):
        """RS-232: :SYST:REM. GPIB: nothing to send (the meter goes remote when it is addressed)."""
        if self.bus == 'RS232':
            self.send('remote')

    def local(self):
        """Back to front panel control: :SYST:LOC on RS-232, GTL on GPIB (the transport sends it)."""
        if self.bus == 'RS232':
            self.send('local')
        else:
            self.t.go_local()

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    def _reset_extra(self):
        return [('enter remote (RS-232 only)', self._step_remote), ('known measurement state (initiation, data format, autozero)', self._known_state)]

    def _step_remote(self):
        self.remote()
        return 'RS-232: :SYST:REM sent' if self.bus == 'RS232' else 'GPIB: remote when addressed'

    def _known_state(self):
        """After *RST: continuous initiation OFF and the reading-only data format, each set once and read back; autozero must be ON."""
        self.send('init.cont')
        if _flag(self.ask('init.cont.query')):
            raise InstrumentError('continuous initiation is still ON after :INITiate:CONTinuous OFF')
        self.send('form.elem')
        if not _text(self.ask('form.elem.query')).startswith('READ'):
            raise InstrumentError('the data format still holds more than the reading after :FORMat:ELEMents READing')
        if not _flag(self.ask('azero.query')):
            raise InstrumentError('autozero is OFF: the specification (and this verification) assumes autozero ON')
        return 'initiation off, READing only, autozero on'

    # ---- configuration of one test point (set, read back, compare; a write is never retried) --------------------------------
    @staticmethod
    def range_ok(reply, range_value: float) -> bool:
        """True when the range query reply is the range asked for: 0.5 to 1.25 x the nominal range (so 757.5 for the 750 V range, 1010 for 1000 V, 3.1 for 3 A,
        120e6 for 100 Mohm all pass and a neighbouring range - a factor of 10 away - never does). The reply format itself is UNVERIFIED."""
        v = abs(_number(reply))
        return RANGE_WINDOW[0] * range_value <= v <= RANGE_WINDOW[1] * range_value

    def _confirm(self, what, ok, reply):
        if not ok:
            raise InstrumentError(f'{self.label}: {what} was not accepted: the 2000 answered {str(reply).strip()!r}')

    def configure_point(self, point: dict):
        """Function, manual range, speed (PLC / AC bandwidth), filter and REL for one verification point. Never autorange (CM p. 1-6).
        point: kind, range (ohm / V / A), optional plc (default 1), optional ac_bandwidth (default 30), optional filter_count (default 10), optional rel (DCV only:
        leave REL as it is)."""
        kind, rng = point['kind'], float(point['range'])
        if kind not in NODE:
            raise InstrumentError(f'{self.label}: no function for kind {kind!r}')
        k = kind.lower()
        self.send(f'func.{k}')
        reply = self.ask('func.query')
        self._confirm(f'function {FUNC_NAME[kind]}', _text(reply).replace('"', '') in FUNC_ACCEPT[kind], reply)
        self.send(f'range.{k}', expected=rng * SELECT_FRACTION)
        reply = self.ask(f'range.query.{k}')
        self._confirm(f'the {rng:g} range', self.range_ok(reply, rng), reply)
        reply = self.ask(f'auto.query.{k}')
        self._confirm('autorange off', not _flag(reply), reply)
        if kind in AC_KINDS:
            hz = float(point.get('ac_bandwidth', 30))
            self.send(f'band.{k}', hz=hz)
            reply = self.ask(f'band.query.{k}')
            self._confirm(f'AC bandwidth {hz:g}', math.isclose(_number(reply), hz, rel_tol=1e-6), reply)
        else:
            nplc = float(point.get('plc') or 1)
            self.send(f'nplc.{k}', nplc=nplc)
            reply = self.ask(f'nplc.query.{k}')
            self._confirm(f'{nplc:g} PLC', math.isclose(_number(reply), nplc, rel_tol=1e-6), reply)
        self.send(f'tcon.{k}')
        reply = self.ask(f'tcon.query.{k}')
        self._confirm('the REPeat filter', _text(reply).startswith('REP'), reply)
        count = int(point.get('filter_count') or 10)
        self.send(f'count.{k}', count=count)
        reply = self.ask(f'count.query.{k}')
        self._confirm(f'filter count {count}', math.isclose(_number(reply), count, rel_tol=1e-9), reply)
        self.send(f'filter.{k}')
        reply = self.ask(f'filter.query.{k}')
        self._confirm('the filter on', _flag(reply), reply)
        if kind != 'DCV':                                  # REL: on only for DC volts, after its zero step (acquire_reference); off everywhere else
            self.send(f'rel.{k}', state='OFF')
            reply = self.ask(f'rel.query.{k}')
            self._confirm('REL off', not _flag(reply), reply)

    def rel_is_on(self, kind='DCV') -> bool:
        """:SENSe:<function>:REFerence:STATe? for one function (a read-only query)."""
        return _flag(self.ask(f'rel.query.{kind.lower()}'))

    def acquire_reference(self, tolerance_rel=1e-6, tolerance_abs=1e-9) -> float:
        """DC volts REL zero (CM p. 1-7 steps 3-4): take one reading (the calibrator is at 0.00000 mV DC, the meter on its 100 mV range with REL off), use it as the
        reference, enable REL, read both back. The reference must equal the reading it was acquired from. Returns the reference (volts)."""
        raw = self.read()
        self.send('rel.acq.dcv')
        ref = _number(self.ask('rel.value.dcv'))
        self._confirm('the REL reference', math.isclose(ref, raw, rel_tol=tolerance_rel, abs_tol=tolerance_abs), f'{ref!r} (the reading was {raw!r})')
        self.send('rel.dcv', state='ON')
        reply = self.ask('rel.query.dcv')
        self._confirm('REL on', _flag(reply), reply)
        return ref

    # ---- readings ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _reading(reply) -> float:
        value = _number(reply)
        if not math.isfinite(value) or abs(value) >= OVERFLOW:
            raise InstrumentError(f'The 2000 reported an overflow / invalid reading ({str(reply).strip()!r}): wrong range or nothing connected.')
        return value

    def read(self) -> float:
        """:READ? -> one reading (ten fresh conversions averaged by the REPeat filter). Never retried."""
        return self._reading(self.ask('read'))

    def fetch(self) -> float:
        """:FETC? -> the latest reading without triggering. A read-only query: it may be retried."""
        return self._reading(self.query_retry('fetch', attempts=3, delay=0.5))

    def front_rear(self) -> str:
        """:SYST:FRSW? -> 'FRONT' or 'REAR' (the INPUTS switch cannot be set remotely)."""
        reply = _text(self.ask('frsw.query'))
        return 'FRONT' if reply in ('1', '+1') else 'REAR' if reply in ('0', '+0') else reply

    def check_errors(self, context: str = ''):
        """Raise if the error queue holds anything: it is read until '0, No error' (at most 10 entries: the queue size, p. 5-63)."""
        found = []
        for _ in range(11):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))


class Fluke5522AComp(Fluke5522A):
    """Fluke 5522A with the impedance-compensation (4-wire / 2-wire / none) command the Keithley resistance points need.
    ZCOMP: 5522A Operators Manual p. 6-49 (verified in the project manual). Compensation is only allowed for a resistance below 110 kohm; for every other
    value it is NONE and a request for another mode is an error ("Can't change compensation now"). The 5560A has no equivalent command in the project
    manuals: it is left to the operator (the procedure says so)."""
    COMMANDS = {
        'zcomp.set': Cmd('ZCOMP {mode}', 'Impedance compensation', 'NONE, WIRE2 or WIRE4; 4-wire compensation is the calibrator\'s "external sense" for resistance',
                         placeholders={'mode': Placeholder('enum', '', 'NONE', enum=('NONE', 'WIRE2', 'WIRE4'))}, kind='set', readback='zcomp.query', verified=True,
                         ref='5522A Operators Manual p. 6-49 (ZCOMP: NONE, WIRE2, WIRE4; allowed below 110 kohm only)'),
        'zcomp.query': Cmd('ZCOMP?', 'Impedance compensation query', 'Returns NONE, WIRE2 or WIRE4', kind='query', verified=True,
                           ref='5522A Operators Manual p. 6-49 (ZCOMP?)'),
    }

    def set_compensation(self, mode: str):
        """ZCOMP <mode>, read back with ZCOMP?, compared. Sent once; the caller reads the error queue (check_error) afterwards."""
        self.send('zcomp.set', mode=mode)
        reply = self.ask('zcomp.query').strip().upper()
        if reply != mode:
            raise InstrumentError(f'{self.label}: impedance compensation {mode} was not accepted (ZCOMP? answered {reply!r})')
