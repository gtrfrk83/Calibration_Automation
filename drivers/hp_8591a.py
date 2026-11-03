"""HP 8591A spectrum analyzer (8590 series, 9 kHz to 1.8 GHz) over GPIB, driven in its own mnemonic language (it is NOT SCPI).

Source: "8590 Series Spectrum Analyzer Programming Manual" (HP part no. 5958-7094, January 1990, 519 PDF pages, image only). Every command below was read on the RENDERED page images (the
manual has no text layer). The page numbers in `ref` are PDF pages (the printed chapter-4 page is the PDF page minus 60: PDF 390 = printed 4-330). What the manual does not print is NOT
guessed: it is verified=False in COMMANDS and listed in the report. The main ones:
    * the TEXT of the ID? reply (the manual says "model number" and options; the driver matches "8591" and never compares exactly),
    * the factory GPIB address (DEFAULT_ADDRESS 18 is carried over from the 8560 series and is only the box's starting value),
    * how the analyzer answers DET? (matched on the first three letters),
    * the exact number format of TRA? replies in the P (parameter) format and that a single read returns one value (the driver reads until it has 401 values),
    * that MKA? / TRA? return volts when AUNITS is V (the TDF page says "P is in the current parameter unit specified by AUNITS"; used for the linear-scale checks),
    * every number used by the helpers (RBW, VBW, reference level, attenuation, span, settle times): chosen by the caller or by the defaults here, not manual limits.
The 8590 language has NO error-list query (no ERR?): errors are read from the status byte (STB?). Bit 5 (value 32) is "illegal analyzer command", bit 3 (value 8) "hardware broken" (RQS, PDF 390
and 391). Reading the status byte is asked once per check and never retried. The marker functions used are MKPK HI, MKD (delta marker at the active marker), MKN <freq> (move the active marker, PDF 289)
and MKA? / MKF?; with a delta marker active MKA? is the amplitude DIFFERENCE (PDF 281 and 282).

Language facts used:
  * Address set from the front panel, given to the constructor / connect(), never fixed in code. Commands end in ';' (units HZ KHZ MHZ GHZ, DB DM, S MS US); a query is the mnemonic + '?'.
  * After CF, SP, RB, ... the marker and trace data are stale until a sweep has finished: take_sweep() sends `TS;DONE?;` (TS starts and completes one sweep before the next command, PDF 478; DONE? answers
    1 when the commands before it are done, PDF 166). The read timeout is raised to the sweep time (ST?) plus a margin because the reply only comes when the sweep is done.
  * Trace data: `TDF P;TRA?;` gives the 401 trace-A points in parameter units (dBm in log, volts in linear scale with AUNITS V; PDF 456, 457, 466, 467).
Writes are sent once, read back (CF? SP? RB? ...) and compared; never retried. Only read-only queries (ID?, ST?, MKA?, MKF?, CF? ...) may be retried. The analyzer has no output: nothing needs a standby step;
cleanup() puts it back to continuous sweep and to the front panel. There is NO calibration command in this driver (the self-calibration of the analyzer is a front-panel step the procedure only prompts for).
"""
from __future__ import annotations

import math
import re
import time
from typing import Any

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .gpib_address import address_of, check_address, retarget
from .transport import TransportError

UM = '8590 Series Spectrum Analyzer Programming Manual'
MAX_HZ = 1.8e9                           # 8591A tuning range 9 kHz to 1.8 GHz (document T.O. 33K3-4-2864-1, Table 1); the analyzer's own end is slightly higher: not used
MAX_ATTEN_DB = 60                        # AT 0 to 60 dB in 10 dB steps (document, Table 1)
MIN_REF_LEVEL_DBM, MAX_REF_LEVEL_DBM = -139.9, 50.0     # RL range of the 8591A, log scale (TRA page, PDF 466: "-139.9 to +50 dBm")
TRACE_POINTS = 401                       # trace A has 401 points (TRA page, PDF 467)
STB_ILLEGAL, STB_HARDWARE = 32, 8        # status byte bits 5 and 3 (RQS page, PDF 390 and 391)
STB_ERRORS = {STB_ILLEGAL: 'illegal analyzer command (SRQ 140)', STB_HARDWARE: 'hardware broken (SRQ 110)'}


def _r(topic, pages):
    return f'{UM}: {topic} (PDF p. {pages})'


def _hz(sample):
    return Placeholder('float', '.10g', sample)


def _num(text):
    """First number in a reply (None when there is none). Read-only helper."""
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(text))
    return float(m.group(0)) if m else None


COMMANDS = {
    'reset': cmdreg.reset_cmd(True, _r('IP', '214 and 215'), template='IP;',
                              note='Presets the analyzer (the 8591A comes up in continuous sweep, log scale, units dBm, couplings on). The 8590 manual does not say how long it takes: the driver waits'),
    'status.clear': Cmd('CLS;', 'Clear status byte', 'Clears all status bits (never overridable)', kind='set', risk='locked', verified=True, ref=_r('CLS', '136')),
    'opc.query': Cmd('DONE?;', 'Commands done', 'Answers 1 when every command before it is complete (never overridable)', kind='query', risk='locked', verified=True, ref=_r('DONE', '166 and 167')),
    'id.query': Cmd('ID?;', 'Identify', 'The model number (and options). The exact text is UNVERIFIED: it is matched on "8591", never exactly (never overridable)',
                    kind='query', risk='locked', verified=False, ref=_r('ID', '207')),
    'stb.query': Cmd('STB?;', 'Status byte', 'The status byte as a decimal number: bit 5 (32) illegal command, bit 3 (8) hardware broken, bit 4 (16) command complete, bit 2 (4) end of sweep (never overridable)',
                     kind='query', risk='locked', verified=True, ref=_r('STB and RQS', '441, 390 and 391')),
    'sweep.done': Cmd('TS;DONE?;', 'Take sweep and wait', 'TS runs one full sweep before the next command; DONE? answers 1 when it has finished. Needed after every change of CF / SP / RB ... before a marker is read',
                      kind='query', verified=True, ref=_r('TS and DONE', '478, 166 and 167')),
    'sngls': Cmd('SNGLS;', 'Single sweep', 'Single sweep mode: a sweep is taken only by TS', kind='set', verified=True, ref=_r('SNGLS', '410')),
    'conts': Cmd('CONTS;', 'Continuous sweep', 'Back to continuous sweep', kind='set', verified=True, ref=_r('CONTS', '148')),
    'aunits.set': Cmd('AUNITS {unit};', 'Amplitude units', 'DBM for the log checks; V for the linear-scale marker readings (volts)',
                      placeholders={'unit': Placeholder('enum', '', 'DBM', enum=('DBM', 'V'))}, kind='set', readback='aunits.query', verified=True, ref=_r('AUNITS', '113 and 114')),
    'aunits.query': Cmd('AUNITS?;', 'Amplitude units', 'The units (reply text UNVERIFIED: matched on its first letters)', kind='query', verified=False, ref=_r('AUNITS', '113 and 114')),
    'lg.set': Cmd('LG {db}DB;', 'Log scale', 'Logarithmic vertical scale, dB per division (1, 2, 5 or 10)', placeholders={'db': Placeholder('int', '', 10)}, kind='set', verified=True, ref=_r('LG', '235 and 236')),
    'ln.set': Cmd('LN;', 'Linear scale', 'Linear vertical scale', kind='set', verified=True, ref=_r('LN', '252')),
    'cf.set': Cmd('CF {hz:.10g}HZ;', 'Center frequency', '0 to 1.8 GHz (8591A)', placeholders={'hz': _hz(1e9)}, kind='set', readback='cf.query', verified=True, ref=_r('CF', '131 and 132')),
    'cf.query': Cmd('CF?;', 'Center frequency', 'Hz', kind='query', verified=True, ref=_r('CF', '131 and 132')),
    'sp.set': Cmd('SP {hz:.10g}HZ;', 'Frequency span', '0 (zero span) to 1.8 GHz', placeholders={'hz': _hz(1e6)}, kind='set', readback='sp.query', verified=True, ref=_r('SP', '411 and 412')),
    'sp.query': Cmd('SP?;', 'Frequency span', 'Hz', kind='query', verified=True, ref=_r('SP', '411 and 412')),
    'rb.set': Cmd('RB {hz:.10g}HZ;', 'Resolution bandwidth', '1 kHz to 3 MHz (8591A); rounded by the analyzer to the nearest bandwidth (1, 3, 10 ... sequence)', placeholders={'hz': _hz(3e3)}, kind='set',
                  readback='rb.query', verified=True, ref=_r('RB', '371 and 372')),
    'rb.query': Cmd('RB?;', 'Resolution bandwidth', 'Hz', kind='query', verified=True, ref=_r('RB', '371 and 372')),
    'vb.set': Cmd('VB {hz:.10g}HZ;', 'Video bandwidth', '30 Hz to 3 MHz (8591A); rounded by the analyzer to the nearest bandwidth', placeholders={'hz': _hz(30.0)}, kind='set', readback='vb.query',
                  verified=True, ref=_r('VB', '494 and 495')),
    'vb.query': Cmd('VB?;', 'Video bandwidth', 'Hz', kind='query', verified=True, ref=_r('VB', '494 and 495')),
    'rl.set': Cmd('RL {dbm:.2f}DBM;', 'Reference level', 'dBm (-139.9 to +50 dBm); set while AUNITS is DBM', placeholders={'dbm': Placeholder('float', '.2f', 0.0)}, kind='set', readback='rl.query', verified=True,
                  ref=_r('RL', '383 and 384')),
    'rl.query': Cmd('RL?;', 'Reference level', 'In the AUNITS units', kind='query', verified=True, ref=_r('RL', '383 and 384')),
    'at.set': Cmd('AT {db}DB;', 'Input attenuation', '0 to 60 dB in 10 dB steps (8591A); setting it turns the attenuator coupling to the reference level off', placeholders={'db': Placeholder('int', '', 10)},
                  kind='set', readback='at.query', verified=True, ref=_r('AT', '111 and 112')),
    'at.query': Cmd('AT?;', 'Input attenuation', 'dB', kind='query', verified=True, ref=_r('AT', '111 and 112')),
    'st.set': Cmd('ST {ms:.6g}MS;', 'Sweep time', '20 ms to 100 s (zero span 15 ms to 100 s, 8591A); the unit MS is the one the manual example uses', placeholders={'ms': Placeholder('float', '.6g', 20.0)},
                  kind='set', readback='st.query', verified=True, ref=_r('ST', '439 and 440')),
    'st.query': Cmd('ST?;', 'Sweep time', 'Seconds', kind='query', verified=True, ref=_r('ST', '439 and 440')),
    'det.set': Cmd('DET {mode};', 'Detector', 'NRM normal, POS positive peak, NEG negative peak, SMP sample. POS is the sensible choice for a CW read (a choice of this driver, not a manual statement)',
                   placeholders={'mode': Placeholder('enum', '', 'POS', enum=('NRM', 'POS', 'NEG', 'SMP'))}, kind='set', readback='det.query', verified=True, ref=_r('DET', '157 and 158')),
    'det.query': Cmd('DET?;', 'Detector', 'Reply text UNVERIFIED: matched on its first three letters', kind='query', verified=False, ref=_r('DET', '157 and 158')),
    'mkpk.hi': Cmd('MKPK HI;', 'Marker to highest peak', 'The active marker goes to the highest point of the trace', kind='set', verified=True, ref=_r('MKPK', '298')),
    'mkd': Cmd('MKD;', 'Delta marker', 'Activates the delta marker at the active marker (MKA? / MKF? then answer the DIFFERENCE, active minus delta)', kind='set', verified=True, ref=_r('MKD', '281 and 282')),
    'mkn.set': Cmd('MKN {hz:.10g}HZ;', 'Marker to frequency', 'Moves the active marker to the frequency (start to stop frequency of the analyzer); an active delta marker stays where it is',
                   placeholders={'hz': _hz(1e6)}, kind='set', verified=True, ref=_r('MKN', '289 and 290')),
    'mka.query': Cmd('MKA?;', 'Marker amplitude', 'The marker amplitude in the AUNITS units; with the delta marker active the difference (dB in log scale, a ratio in linear scale)', kind='query', verified=True,
                     ref=_r('MKA', '274 and 275')),
    'mkf.query': Cmd('MKF?;', 'Marker frequency', 'Hz; with the delta marker active the difference in Hz', kind='query', verified=True, ref=_r('MKF', '283 and 284')),
    'mkoff': Cmd('MKOFF ALL;', 'Markers off', 'All markers off', kind='set', verified=True, ref=_r('MKOFF', '293')),
    'tdf.p': Cmd('TDF P;', 'Trace data format: parameter', 'Trace data are returned in parameter units (dBm / Hz / volts, in the AUNITS units)', kind='set', verified=True, ref=_r('TDF', '456 and 457')),
    'tra.query': Cmd('TRA?;', 'Trace A data', 'The 401 points of trace A in the TDF format (one value per read or comma / line separated: UNVERIFIED, the driver reads until it has 401)', kind='query', verified=True,
                     ref=_r('TRA / TRB / TRC', '466 and 467')),
}


# Bench records (bench-first driver workflow, NOTES.md): none yet for this model; nothing has run on the owner's 8591A.


class HP8591A(Instrument):
    MODEL = 'HP 8591A'
    IDN_MATCH = ('8591',)
    DEFAULT_ADDRESS = 18                 # starting value of the address box (the 8560 series' factory address); UNVERIFIED for the 8591A: it is set from the front panel
    DEFAULT_TIMEOUT = 20.0
    COMMAND_GAP_S = 0.02
    SWEEP_MARGIN_S = 5.0                 # added to the sweep time for the TS;DONE? read (a choice of this driver)
    RESET_SETTLE_S = 1.0                 # after IP, a choice of this driver: the manual gives no time
    COMMANDS = COMMANDS

    def __init__(self, transport, log=None, label=None, address=None):
        super().__init__(transport, log, label)
        self._address = check_address(address) if address is not None else address_of(getattr(transport, 'address', None))

    @property
    def address(self) -> int:
        return self._address if self._address is not None else self.DEFAULT_ADDRESS

    def set_address(self, address):
        if self._open:
            raise InstrumentError(f'{self.MODEL}: close the connection before changing the GPIB address')
        self._address = check_address(address)

    # ---- wire access ---------------------------------------------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        super().write(cmd, log_as)

    def send(self, key, **vals):
        super().send(key, **vals)
        if key == 'reset':
            time.sleep(self.RESET_SETTLE_S)

    def identify(self):
        return self.query_retry('id.query', attempts=2).strip()

    # ---- connection ---------------------------------------------------------------------------------------------------------------------------
    def connect(self, address=None):
        """Re-target the transport to the GPIB address (given here, at construction, or DEFAULT_ADDRESS), open, confirm ID? says 8591, clear the status byte and read it once (anything left over is logged in
        status_at_connect, not an error here). No device clear is sent (the 8590 manual does not describe what it does)."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=False)
        try:
            self.idn = self.identify()
            if not any(m in self.idn.upper() for m in self.IDN_MATCH):
                raise InstrumentError(f'Expected {self.MODEL} at GPIB address {self.address} but ID? answered {self.idn!r}')
            self.status_at_connect = self.read_status()
            if self.status_at_connect & (STB_ILLEGAL | STB_HARDWARE):
                self.log.add('!!', f'status byte at connect: {self.status_at_connect}', self.label)
            self.send('status.clear')
        except Exception:
            self.close()
            raise
        return self

    status_at_connect = 0

    def cleanup(self):
        """Back to continuous sweep and to the front panel. Never raises."""
        try:
            self.send('conts')
        except Exception:
            pass
        try:
            self.t.go_local()
        except Exception:
            pass

    # ---- errors (no ERR? in the 8590 language: the status byte) --------------------------------------------------------------------------------------
    def read_status(self) -> int:
        """STB? ONCE (read-only, never retried here: it may clear bits): the status byte as an int."""
        reply = self.ask('stb.query').strip()
        value = _num(reply)
        if value is None:
            raise InstrumentError(f'{self.MODEL}: unreadable STB? reply {reply!r}')
        return int(value)

    def check_errors(self, context=''):
        """Raise InstrumentError when the status byte reports an illegal command (32) or broken hardware (8)."""
        status = self.read_status()
        bad = [text for bit, text in STB_ERRORS.items() if status & bit]
        if bad:
            raise InstrumentError(f'{self.MODEL} reported {" and ".join(bad)}{" after " + context if context else ""} (status byte {status})')
        return status

    def _reset_drain(self, rep, limit=10):
        status = self.read_status()
        if status & (STB_ILLEGAL | STB_HARDWARE):
            rep.warnings.append(f'status byte after reset: {status}')
            self.log.add('!!', f'status byte after reset: {status}', self.label)
            return f'status byte {status}'
        return 'status byte clear of errors'

    def _reset_extra(self):
        return [('amplitude units dBm (read back)', self.set_units),
                ('sweep after IP (TS;DONE?;)', lambda: self.take_sweep() and 'one sweep done')]

    # ---- setup, each read back --------------------------------------------------------------------------------------------------------------------
    def _set_number(self, set_key, query_key, what, accept, **vals):
        self.send(set_key, **vals)                                        # once, never retried
        reply = self.query_retry(query_key, attempts=2).strip()
        got = _num(reply)
        if got is None or not accept(got):
            raise InstrumentError(f'{self.MODEL}: {what} was not accepted: sent {cmdreg.render(self._registry()[set_key], vals)!r}, read back {reply!r}')
        return got

    @staticmethod
    def _hz_ok(want):
        return lambda got: abs(got - want) <= max(1.0, abs(want) * 1e-7)

    @staticmethod
    def _bw_ok(want):
        return lambda got: got > 0 and 0.5 <= got / want <= 2.0

    @staticmethod
    def _check_hz(hz, what):
        if not 0 <= hz <= MAX_HZ:
            raise InstrumentError(f'{what} {hz:g} Hz is outside 0 to {MAX_HZ:g} Hz (8591A)')

    def preset(self):
        """IP; (instrument preset, p. 214): the measurement state goes back to the power-on defaults (auto-coupled attenuation, DBM, 10 dB/division ...). Not a calibration or adjustment command.
        Nothing is read back here: the settings that follow are read back, and the instrument processes its commands in order."""
        self.send('reset')

    def set_units(self, unit='DBM'):
        """AUNITS DBM or V, read back (reply text UNVERIFIED: the first letter is compared)."""
        self.send('aunits.set', unit=unit)
        reply = self.query_retry('aunits.query', attempts=2).strip().upper()
        if reply[:1] != unit[:1]:
            raise InstrumentError(f'{self.MODEL}: AUNITS {unit} was not accepted: read back {reply!r}')
        return unit

    def set_center_hz(self, hz: float) -> float:
        self._check_hz(hz, 'center frequency')
        return self._set_number('cf.set', 'cf.query', f'center frequency {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_span_hz(self, hz: float) -> float:
        self._check_hz(hz, 'span')
        return self._set_number('sp.set', 'sp.query', f'span {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_rbw_hz(self, hz: float) -> float:
        """Resolution bandwidth; the analyzer rounds to the nearest of its values: the one it chose is returned (it must be within a factor 2 of the request)."""
        return self._set_number('rb.set', 'rb.query', f'resolution bandwidth {hz:g} Hz', self._bw_ok(hz), hz=float(hz))

    def set_vbw_hz(self, hz: float) -> float:
        return self._set_number('vb.set', 'vb.query', f'video bandwidth {hz:g} Hz', self._bw_ok(hz), hz=float(hz))

    def set_reference_level_dbm(self, dbm: float) -> float:
        if not MIN_REF_LEVEL_DBM <= dbm <= MAX_REF_LEVEL_DBM:
            raise InstrumentError(f'reference level {dbm:g} dBm is outside {MIN_REF_LEVEL_DBM:g} to {MAX_REF_LEVEL_DBM:g} dBm (8591A)')
        return self._set_number('rl.set', 'rl.query', f'reference level {dbm:g} dBm', lambda g: abs(g - dbm) <= 0.05, dbm=float(dbm))

    def set_attenuation_db(self, db: int) -> float:
        """Input attenuation 0 to 60 dB in 10 dB steps; read back and compared with the requested value (rounded up to a multiple of 10)."""
        if not 0 <= db <= MAX_ATTEN_DB:
            raise InstrumentError(f'attenuation {db!r} dB is outside 0 to {MAX_ATTEN_DB}')
        want = int(math.ceil(db / 10.0) * 10)
        return self._set_number('at.set', 'at.query', f'attenuation {db} dB', lambda g: abs(g - want) < 0.5, db=int(db))

    def set_sweep_time_s(self, seconds: float) -> float:
        """ST in seconds (sent in ms), read back; the analyzer may round it."""
        return self._set_number('st.set', 'st.query', f'sweep time {seconds:g} s', lambda g: g > 0 and abs(g - seconds) <= max(1e-3, seconds * 0.05), ms=float(seconds) * 1e3)

    def set_detector(self, mode: str = 'POS') -> str:
        self.send('det.set', mode=mode)
        reply = self.query_retry('det.query', attempts=2).strip()
        if reply.upper()[:3] != mode.upper()[:3]:
            raise InstrumentError(f'{self.MODEL}: detector {mode} was not accepted: read back {reply!r}')
        return reply

    def set_scale(self, log_db: int | None = 10):
        """LG <db> DB (log) or LN (linear when log_db is None). The scale itself has no query used here: the status byte is checked after the setup."""
        if log_db is None:
            self.send('ln.set')
        else:
            if log_db not in (1, 2, 5, 10):
                raise InstrumentError(f'log scale {log_db!r} dB per division is not one of 1, 2, 5, 10')
            self.send('lg.set', db=int(log_db))

    def single_sweep(self):
        self.send('sngls')

    # ---- sweeping, markers and the trace ---------------------------------------------------------------------------------------------------------
    def sweep_time_s(self) -> float:
        value = _num(self.query_retry('st.query', attempts=2))
        if value is None or value <= 0:
            raise InstrumentError(f'{self.MODEL}: unreadable sweep time')
        return value

    def take_sweep(self) -> bool:
        """TS;DONE?; and wait for the 1. The read timeout is raised to 1.5 x the sweep time + SWEEP_MARGIN_S. Not retried (a second TS is a second write)."""
        wait = max(self.DEFAULT_TIMEOUT, 1.5 * self.sweep_time_s() + self.SWEEP_MARGIN_S)
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(wait)
        try:
            reply = self.ask('sweep.done').strip()
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        if _num(reply) != 1:
            raise InstrumentError(f'{self.MODEL}: TS;DONE?; answered {reply!r}, not 1')
        return True

    def marker_to_peak(self):
        """MKPK HI then the marker frequency (Hz) and amplitude (AUNITS units): (hz, amplitude). Both reads are read-only."""
        self.send('mkpk.hi')
        hz = _num(self.query_retry('mkf.query', attempts=2))
        amp = _num(self.query_retry('mka.query', attempts=2))
        if hz is None or amp is None:
            raise InstrumentError(f'{self.MODEL}: unreadable marker reply')
        return hz, amp

    def delta_at(self, hz: float) -> float:
        """The amplitude at `hz` relative to the highest peak: MKPK HI, MKD, MKN <hz>, MKA? (the active marker minus the delta marker, in dB). Ends with the markers off."""
        self._check_hz(hz, 'marker frequency')
        self.send('mkpk.hi')
        self.send('mkd')
        self.send('mkn.set', hz=float(hz))
        value = _num(self.query_retry('mka.query', attempts=2))
        self.send('mkoff')
        if value is None:
            raise InstrumentError(f'{self.MODEL}: unreadable delta-marker amplitude')
        return value

    def read_trace(self) -> list:
        """TDF P; TRA?; and the 401 values (parameter units). One query: the values are read until there are 401 (a reply may hold one value per read or several); fewer raises InstrumentError."""
        self.send('tdf.p')
        wire, log_as = self._prepare('tra.query', {}, 'ask')
        self.log.add('>>', log_as or wire, self.label)
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(self.DEFAULT_TIMEOUT, 30.0))
        values: list = []
        try:
            self.t.write(wire)
            for _ in range(TRACE_POINTS + 5):
                text = self.t.read()
                values += [float(x) for x in re.findall(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', text)]
                if len(values) >= TRACE_POINTS:
                    break
        except TransportError as exc:
            raise InstrumentError(f'{self.MODEL}: trace read failed after {len(values)} of {TRACE_POINTS} values: {exc}') from exc
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        self.log.add('<<', f'{len(values)} trace values', self.label)
        if len(values) < TRACE_POINTS:
            raise InstrumentError(f'{self.MODEL}: TRA? gave {len(values)} values, not {TRACE_POINTS}')
        return values[:TRACE_POINTS]
