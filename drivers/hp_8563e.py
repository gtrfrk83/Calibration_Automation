"""HP / Agilent 8563E spectrum analyzer (8560 E-series, 9 kHz to 26.5 GHz) over GPIB, driven in its own mnemonic language (it is NOT SCPI).

Source: "8560E / EC Series Spectrum Analyzer User's / Programmer's Guide" (printed page = PDF page), syntax diagrams and tables read from rendered page images. Every Cmd below
carries its page. What the manual does not print is NOT guessed: it is verified=False in COMMANDS and listed in the report. The main ones:
    * the NEXT-HIGHEST walk: only one use of `MKPK NH` is in the manual (p. 529: MKPK HI; MKD; MKPK NH). That repeated MKPK NH moves down the list of peaks of the SAME trace
      (what scan_spurs relies on) is an inference. scan_spurs stops when the marker does not move to a new frequency,
    * the text of the ID? / MEAS? replies (model characters, then options), and the number of values in the ERR? reply (parsed as a comma-separated list; 0 = none),
    * how long IP takes (the manual advises IP followed by TS; reset_to_defaults() does IP, DONE?, then a sweep),
    * the Option 103 RBW range, the exact discrete RBW list (1 / 3 / 10 sequence), the sweep time of an auto-coupled sweep (the driver asks ST? and waits for that),
    * every number used by the helpers (RBW, VBW, reference level, attenuation, span): they are chosen by the caller or by the defaults here, they are not manual limits.
There is NO remote harmonic-distortion, spurious-search, peak-table or TOI command in the language: measure_harmonics() and scan_spurs() are built from CF / TS / MKPK / MKA? /
MKF? and software, as the manual's own front-panel procedures (Chapter 2, Example 4, p. 67 to 74) do.

Language facts used:
  * Address: factory 18 (DEFAULT_ADDRESS, p. 676), set from the front panel; given to the constructor / connect(), never fixed in code. The manual's examples write OUTPUT 718.
    Commands end in ';' (LF / CR / space / ',' are accepted too, p. 371); a query is the mnemonic + '?'; every reply ends in LF with EOI. Input and output buffers are 64 characters
    (p. 317), so each write here is one short statement.
  * After CF, SP, RB, ... the marker and trace data are stale until a sweep has finished: take_sweep() sends `TS;DONE?;` and waits for the "1" (p. 459, 642). The read timeout is raised
    to the sweep time (ST?) plus a margin, because the reply only comes when the sweep is done.
  * IP presets without clearing the GPIB buffers (p. 495); the bus device clear (connect()) presets and clears the buffers (p. 297). ERR? returns the GPIB error codes and CLEARS them
    (p. 460): it is asked once per check and never retried.
Writes are sent once, read back (CF? SP? RB? ... ) and compared; never retried. Only read-only queries (ID?, ST?, MKA?, MKF?, CF? ...) may be retried. The analyzer has no output: nothing
needs a standby step; cleanup() puts it back to continuous sweep and to the front panel. There is no calibration command in this driver.
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

UM = '8560E / EC Series Spectrum Analyzer User\'s / Programmer\'s Guide'
MAX_HZ = 26.5e9                          # 8563E tuning range (p. 434, 435)
MAX_ATTEN_DB = 70                        # AT: integer 0 to 70, rounded up to a multiple of 10 (p. 424)
MIN_REF_LEVEL_DBM = -120.0               # Table 7-8, p. 581 (minimum RL, log scale, 0 dB attenuation)
PROGRAMMING_ERRORS = {
    102: 'not enough arguments', 103: 'not enough arguments', 104: 'not enough arguments', 105: 'not enough arguments', 106: 'operation aborted, GPIB parser reset',
    107: 'no GPIB listener (HELLO ??)', 111: 'not enough arguments', 112: 'unrecognized command (??CMD??)', 113: 'command cannot have frequency units', 114: 'command cannot have time units',
    115: 'command cannot have amplitude units', 116: 'unrecognizable units', 117: 'number not allowed', 118: 'enable parameter not allowed', 119: 'UP / DN not valid',
    120: 'ON / OFF not valid', 121: 'AUTO / MAN not valid', 122: 'trace not valid', 126: 'command cannot be queried', 127: 'not a valid peak detector mode', 128: 'not a valid peak search parameter',
    130: 'bad trace data format', 144: 'coupling not valid'}


def _r(topic, page):
    return f'{UM}: {topic} (p. {page})'


def _hz(sample):
    return Placeholder('float', '.10g', sample)


def _num(text):
    """First number in a reply (None when there is none). Read-only helper."""
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(text))
    return float(m.group(0)) if m else None


COMMANDS = {
    'reset': cmdreg.reset_cmd(True, _r('IP', '495 to 497'), template='IP;',
                              note='Presets the analyzer (center 13.25 GHz, span 26.5 GHz, RL 0 dBm, RBW / VBW 1 MHz auto, trace A clear-write, continuous sweep, dBm). It does not clear the GPIB buffers'),
    'opc.query': Cmd('DONE?;', 'Commands done', 'Answers 1 when every command before it is complete (never overridable)', kind='query', risk='locked', verified=True, ref=_r('DONE', '459')),
    'err.query': Cmd('ERR?;', 'Error list', 'The GPIB error codes, comma separated, 0 = none. READING CLEARS THEM, so it is asked once and never retried (never overridable). The number of values '
                     'in the reply is UNVERIFIED', kind='query', risk='locked', verified=False, ref=_r('ERR', '460 and 461')),
    'id.query': Cmd('ID?;', 'Identify', 'Model characters followed by the installed options, e.g. HP8563E. The exact text is UNVERIFIED: it is matched on "8563", never exactly (never overridable)',
                    kind='query', risk='locked', verified=False, ref=_r('ID', '492')),
    'stb.query': Cmd('STB?;', 'Status byte', 'The status byte as a decimal number (bit 5 = 32 error present, bit 4 = 16 command complete, bit 2 = 4 end of sweep); reading clears it', kind='query',
                     verified=True, ref=_r('STB, Table 5-4', '618 and 334')),
    'sweep.done': Cmd('TS;DONE?;', 'Take sweep and wait', 'TS runs one full sweep; DONE? answers 1 when it has finished. Needed after every change of CF / SP / RB ... before a marker is read',
                      kind='query', verified=True, ref=_r('TS and DONE', '642 and 459')),
    'sngls': Cmd('SNGLS;', 'Single sweep', 'Single sweep mode: a sweep is taken only by TS', kind='set', verified=True, ref=_r('SNGLS', '594')),
    'conts': Cmd('CONTS;', 'Continuous sweep', 'Back to continuous sweep', kind='set', verified=True, ref=_r('CONTS', '443')),
    'aunits.set': Cmd('AUNITS DBM;', 'Amplitude units dBm', 'Marker and reference-level values are in dBm', kind='set', readback='aunits.query', verified=True, ref=_r('AUNITS', '426 and 427')),
    'aunits.query': Cmd('AUNITS?;', 'Amplitude units', 'The units (reply text UNVERIFIED: matched on DBM)', kind='query', verified=False, ref=_r('AUNITS', '426')),
    'cf.set': Cmd('CF {hz:.10g}HZ;', 'Center frequency', '0 to 26.5 GHz (8563E)', placeholders={'hz': _hz(1e9)}, kind='set', readback='cf.query', verified=True, ref=_r('CF', '434 and 435')),
    'cf.query': Cmd('CF?;', 'Center frequency', 'Hz', kind='query', verified=True, ref=_r('CF', '434 and 435')),
    'sp.set': Cmd('SP {hz:.10g}HZ;', 'Frequency span', '0 (zero span) to 26.5 GHz', placeholders={'hz': _hz(1e6)}, kind='set', readback='sp.query', verified=True, ref=_r('SP', '595 and 596')),
    'sp.query': Cmd('SP?;', 'Frequency span', 'Hz', kind='query', verified=True, ref=_r('SP', '595')),
    'fa.set': Cmd('FA {hz:.10g}HZ;', 'Start frequency', '0 to 26.5 GHz (selects start / stop mode)', placeholders={'hz': _hz(0.0)}, kind='set', readback='fa.query', verified=True, ref=_r('FA', '464 and 465')),
    'fa.query': Cmd('FA?;', 'Start frequency', 'Hz', kind='query', verified=True, ref=_r('FA', '464')),
    'fb.set': Cmd('FB {hz:.10g}HZ;', 'Stop frequency', '0 to 26.5 GHz', placeholders={'hz': _hz(26.5e9)}, kind='set', readback='fb.query', verified=True, ref=_r('FB', '466 and 467')),
    'fb.query': Cmd('FB?;', 'Stop frequency', 'Hz', kind='query', verified=True, ref=_r('FB', '466')),
    'rb.set': Cmd('RB {hz:.10g}HZ;', 'Resolution bandwidth', 'Rounded by the analyzer to the nearest bandwidth (1, 3, 10 ... sequence)', placeholders={'hz': _hz(30e3)}, kind='set', readback='rb.query',
                  verified=True, ref=_r('RB', '569 and 570')),
    'rb.query': Cmd('RB?;', 'Resolution bandwidth', 'Hz', kind='query', verified=True, ref=_r('RB', '569')),
    'vb.set': Cmd('VB {hz:.10g}HZ;', 'Video bandwidth', 'Rounded by the analyzer to the nearest bandwidth', placeholders={'hz': _hz(30e3)}, kind='set', readback='vb.query', verified=True,
                  ref=_r('VB', '647 and 648')),
    'vb.query': Cmd('VB?;', 'Video bandwidth', 'Hz', kind='query', verified=True, ref=_r('VB', '647')),
    'rl.set': Cmd('RL {dbm:.2f}DBM;', 'Reference level', 'dBm (units follow AUNITS)', placeholders={'dbm': Placeholder('float', '.2f', 0.0)}, kind='set', readback='rl.query', verified=True,
                  ref=_r('RL', '580 to 582')),
    'rl.query': Cmd('RL?;', 'Reference level', 'In the AUNITS units', kind='query', verified=True, ref=_r('RL', '580')),
    'at.set': Cmd('AT {db}DB;', 'Input attenuation', 'Integer 0 to 70, rounded UP to a multiple of 10 (8563E); 0 only by numeric entry', placeholders={'db': Placeholder('int', '', 10)}, kind='set',
                  readback='at.query', verified=True, ref=_r('AT', '424 and 425')),
    'at.query': Cmd('AT?;', 'Input attenuation', 'dB', kind='query', verified=True, ref=_r('AT', '424')),
    'st.query': Cmd('ST?;', 'Sweep time', 'Seconds', kind='query', verified=True, ref=_r('ST', '616 and 617')),
    'det.set': Cmd('DET {mode};', 'Detector', 'NRM normal, POS positive peak, NEG negative peak, SMP sample. POS is the sensible choice for a CW harmonic read (a choice of this driver, not a manual statement)',
                   placeholders={'mode': Placeholder('enum', '', 'POS', enum=('NRM', 'POS', 'NEG', 'SMP'))}, kind='set', readback='det.query', verified=True, ref=_r('DET', '453 and 454')),
    'det.query': Cmd('DET?;', 'Detector', 'Reply text UNVERIFIED: matched on its first three letters', kind='query', verified=False, ref=_r('DET', '453')),
    'mkpk.hi': Cmd('MKPK HI;', 'Marker to highest peak', 'The marker goes to the highest point of the trace (to the center when no peak meets MKPT)', kind='set', verified=True, ref=_r('MKPK', '528 and 529')),
    'mkpk.nh': Cmd('MKPK NH;', 'Marker to next highest peak', 'Next highest peak. That repeated NH keeps walking down the peak list is UNVERIFIED (the manual shows one use)', kind='set', verified=False,
                   ref=_r('MKPK NH', '528 and 529')),
    'mkpk.nr': Cmd('MKPK NR;', 'Marker to next peak right', 'Next peak to the right', kind='set', verified=True, ref=_r('MKPK NR', '528')),
    'mkpk.nl': Cmd('MKPK NL;', 'Marker to next peak left', 'Next peak to the left', kind='set', verified=True, ref=_r('MKPK NL', '528')),
    'mka.query': Cmd('MKA?;', 'Marker amplitude', 'dBm (units follow AUNITS); in delta mode the difference in dB', kind='query', verified=True, ref=_r('MKA', '507')),
    'mkf.query': Cmd('MKF?;', 'Marker frequency', 'Hz; in delta mode the difference in Hz', kind='query', verified=True, ref=_r('MKF', '516 and 517')),
    'mkd': Cmd('MKD;', 'Delta marker', 'Activates delta mode with the second marker at the present marker', kind='set', verified=True, ref=_r('MKD', '511 and 512')),
    'mkoff': Cmd('MKOFF ALL;', 'Markers off', 'All markers off', kind='set', verified=True, ref=_r('MKOFF', '527')),
    'mkcf': Cmd('MKCF;', 'Marker to center', 'Center frequency = marker frequency; take a sweep afterwards', kind='set', verified=True, ref=_r('MKCF', '509')),
    'mkpt.set': Cmd('MKPT {dbm:.1f}DBM;', 'Peak threshold', 'Minimum amplitude a peak must have (-200 to +30 dBm)', placeholders={'dbm': Placeholder('float', '.1f', -90.0)}, kind='set',
                    readback='mkpt.query', verified=True, ref=_r('MKPT', '530 and 531')),
    'mkpt.query': Cmd('MKPT?;', 'Peak threshold', 'dBm', kind='query', verified=True, ref=_r('MKPT', '530')),
    'mkpx.set': Cmd('MKPX {db:.1f}DB;', 'Peak excursion', 'A peak must rise and fall by this much (0 to 30 dB, log)', placeholders={'db': Placeholder('float', '.1f', 6.0)}, kind='set',
                    readback='mkpx.query', verified=True, ref=_r('MKPX', '532 to 534')),
    'mkpx.query': Cmd('MKPX?;', 'Peak excursion', 'dB', kind='query', verified=True, ref=_r('MKPX', '532')),
}


class HP8563E(Instrument):
    MODEL = 'HP 8563E'
    IDN_MATCH = ('8563',)
    DEFAULT_ADDRESS = 18                 # factory GPIB address (p. 676); set from the front panel
    DEFAULT_TIMEOUT = 20.0
    COMMAND_GAP_S = 0.02
    SWEEP_MARGIN_S = 5.0                 # added to the sweep time for the TS;DONE? read (a choice of this driver)
    RESET_SETTLE_S = 1.0                 # after IP, a choice of this driver: the manual gives no time
    COMMANDS = COMMANDS

    errors_at_connect = ()

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
        """Re-target the transport to the GPIB address (given here, at construction, or DEFAULT_ADDRESS), open, device clear (presets and clears the buffers), confirm ID? says 8563,
        read the error list once (anything left over is logged in errors_at_connect, not an error here)."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=False)
        try:
            self.t.clear()
            time.sleep(self.RESET_SETTLE_S)
            self.idn = self.identify()
            if not any(m in self.idn.upper() for m in self.IDN_MATCH):
                raise InstrumentError(f'Expected {self.MODEL} at GPIB address {self.address} but ID? answered {self.idn!r}')
            self.errors_at_connect = tuple(self.read_errors())
            if self.errors_at_connect:
                self.log.add('!!', f'error list at connect: {self.errors_at_connect}', self.label)
        except Exception:
            self.close()
            raise
        return self

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

    # ---- errors ---------------------------------------------------------------------------------------------------------------------------------
    def read_errors(self) -> list:
        """ERR? ONCE (it clears the list: never retried): the non-zero codes, [] when there are none."""
        reply = self.ask('err.query').strip()
        codes = [int(float(x)) for x in re.findall(r'[-+]?\d+(?:\.\d+)?', reply)]
        if not codes and reply:
            raise InstrumentError(f'{self.MODEL}: unreadable ERR? reply {reply!r}')
        return [c for c in codes if c != 0]

    def check_errors(self, context=''):
        """Raise InstrumentError naming each code (and its text when the manual gives one)."""
        codes = self.read_errors()
        if codes:
            text = '; '.join(f'{c} {PROGRAMMING_ERRORS.get(c, "")}'.strip() for c in codes)
            raise InstrumentError(f'{self.MODEL} reported errors{" after " + context if context else ""}: {text}')

    def _reset_drain(self, rep, limit=10):
        codes = self.read_errors()
        if codes:
            rep.warnings.append(f'error list after reset: {codes}')
            self.log.add('!!', f'error list after reset: {codes}', self.label)
            return f'{len(codes)} error(s) drained'
        return 'error list empty'

    def _reset_extra(self):
        return [('sweep after IP (TS;DONE?;)', lambda: self.take_sweep() and 'one sweep done'), ('amplitude units dBm (read back)', self.set_units_dbm)]

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
            raise InstrumentError(f'{what} {hz:g} Hz is outside 0 to {MAX_HZ:g} Hz (8563E)')

    def set_units_dbm(self):
        self.send('aunits.set')
        reply = self.query_retry('aunits.query', attempts=2)
        if 'DBM' not in reply.upper():
            raise InstrumentError(f'{self.MODEL}: AUNITS DBM was not accepted: read back {reply.strip()!r}')
        return 'dBm'

    def set_center_hz(self, hz: float) -> float:
        self._check_hz(hz, 'center frequency')
        return self._set_number('cf.set', 'cf.query', f'center frequency {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_span_hz(self, hz: float) -> float:
        self._check_hz(hz, 'span')
        return self._set_number('sp.set', 'sp.query', f'span {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_start_hz(self, hz: float) -> float:
        self._check_hz(hz, 'start frequency')
        return self._set_number('fa.set', 'fa.query', f'start frequency {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_stop_hz(self, hz: float) -> float:
        self._check_hz(hz, 'stop frequency')
        return self._set_number('fb.set', 'fb.query', f'stop frequency {hz:g} Hz', self._hz_ok(hz), hz=float(hz))

    def set_rbw_hz(self, hz: float) -> float:
        """Resolution bandwidth; the analyzer rounds to the nearest of its values: the one it chose is returned (it must be within a factor 2 of the request)."""
        return self._set_number('rb.set', 'rb.query', f'resolution bandwidth {hz:g} Hz', self._bw_ok(hz), hz=float(hz))

    def set_vbw_hz(self, hz: float) -> float:
        return self._set_number('vb.set', 'vb.query', f'video bandwidth {hz:g} Hz', self._bw_ok(hz), hz=float(hz))

    def set_reference_level_dbm(self, dbm: float) -> float:
        if dbm < MIN_REF_LEVEL_DBM:
            raise InstrumentError(f'reference level {dbm:g} dBm is below the minimum {MIN_REF_LEVEL_DBM:g} dBm (p. 581)')
        return self._set_number('rl.set', 'rl.query', f'reference level {dbm:g} dBm', lambda g: abs(g - dbm) <= 0.05, dbm=float(dbm))

    def set_attenuation_db(self, db: int) -> float:
        """Input attenuation 0 to 70 dB; the analyzer rounds UP to a multiple of 10: the value it holds is returned and compared with that."""
        if not 0 <= db <= MAX_ATTEN_DB:
            raise InstrumentError(f'attenuation {db!r} dB is outside 0 to {MAX_ATTEN_DB}')
        want = int(math.ceil(db / 10.0) * 10)
        return self._set_number('at.set', 'at.query', f'attenuation {db} dB', lambda g: abs(g - want) < 0.5, db=int(db))

    def set_detector(self, mode: str = 'POS') -> str:
        self.send('det.set', mode=mode)
        reply = self.query_retry('det.query', attempts=2).strip()
        if reply.upper()[:3] != mode.upper()[:3]:
            raise InstrumentError(f'{self.MODEL}: detector {mode} was not accepted: read back {reply!r}')
        return reply

    def set_marker_threshold(self, dbm: float) -> float:
        return self._set_number('mkpt.set', 'mkpt.query', f'peak threshold {dbm:g} dBm', lambda g: abs(g - dbm) <= 0.05, dbm=float(dbm))

    def set_marker_excursion(self, db: float) -> float:
        return self._set_number('mkpx.set', 'mkpx.query', f'peak excursion {db:g} dB', lambda g: abs(g - db) <= 0.05, db=float(db))

    def single_sweep(self):
        self.send('sngls')

    # ---- sweeping and markers ---------------------------------------------------------------------------------------------------------------------
    def sweep_time_s(self) -> float:
        value = _num(self.query_retry('st.query', attempts=2))
        if value is None or value <= 0:
            raise InstrumentError(f'{self.MODEL}: unreadable sweep time')
        return value

    def take_sweep(self) -> bool:
        """TS;DONE?; and wait for the 1. The read timeout is raised to 1.5 x the sweep time + SWEEP_MARGIN_S. TS needs its trigger condition (free run unless changed): a sweep that never
        ends raises the transport timeout. Not retried (a second TS is a second write)."""
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

    def marker_to_peak(self, key='mkpk.hi'):
        """MKPK (HI / NH / NR / NL) then the marker frequency (Hz) and amplitude (dBm): (hz, dbm). Both reads are read-only."""
        self.send(key)
        hz = _num(self.query_retry('mkf.query', attempts=2))
        dbm = _num(self.query_retry('mka.query', attempts=2))
        if hz is None or dbm is None:
            raise InstrumentError(f'{self.MODEL}: unreadable marker reply')
        return hz, dbm

    def delta_to_next_peak(self):
        """MKPK HI; MKD; MKPK NH; then the differences MKF? and MKA? (the manual's own sequence, p. 529): (delta_hz, delta_db)."""
        self.send('mkpk.hi')
        self.send('mkd')
        self.send('mkpk.nh')
        df = _num(self.query_retry('mkf.query', attempts=2))
        da = _num(self.query_retry('mka.query', attempts=2))
        self.send('mkoff')
        return df, da

    # ---- measurement helpers --------------------------------------------------------------------------------------------------------------------------
    def configure(self, center_hz=None, span_hz=None, rbw_hz=None, vbw_hz=None, ref_level_dbm=None, atten_db=None, detector=None) -> dict:
        """Set (and read back) whichever of the settings are given, then read the error list once. Returns what the analyzer holds."""
        got = {}
        self.set_units_dbm()
        if center_hz is not None:
            got['center_hz'] = self.set_center_hz(center_hz)
        if span_hz is not None:
            got['span_hz'] = self.set_span_hz(span_hz)
        if ref_level_dbm is not None:
            got['ref_level_dbm'] = self.set_reference_level_dbm(ref_level_dbm)
        if atten_db is not None:
            got['atten_db'] = self.set_attenuation_db(atten_db)
        if rbw_hz is not None:
            got['rbw_hz'] = self.set_rbw_hz(rbw_hz)
        if vbw_hz is not None:
            got['vbw_hz'] = self.set_vbw_hz(vbw_hz)
        if detector is not None:
            self.set_detector(detector)
        self.check_errors('configure')
        return got

    def measure_fundamental(self, center_hz: float, span_hz: float = 1e6, rbw_hz: float = 30e3, vbw_hz: float = 30e3, ref_level_dbm: float = 10.0, atten_db: int = 20,
                            detector: str = 'POS') -> dict:
        """Single sweep at the carrier: configure, TS, MKPK HI, MKCF, TS, MKPK HI again (so the peak sits at the center). {'freq_hz', 'level_dbm', 'settings'}. Raises when the peak is
        farther than half a span from the carrier. The RBW / VBW / RL / AT defaults are this driver's choices, not manual limits."""
        settings = self.configure(center_hz, span_hz, rbw_hz, vbw_hz, ref_level_dbm, atten_db, detector)
        self.single_sweep()
        self.take_sweep()
        f, _a = self.marker_to_peak()
        if abs(f - center_hz) > span_hz / 2.0:
            raise InstrumentError(f'{self.MODEL}: no carrier within {span_hz / 2:g} Hz of {center_hz:g} Hz (highest peak at {f:g} Hz)')
        self.send('mkcf')
        self.take_sweep()
        f, a = self.marker_to_peak()
        self.check_errors('fundamental')
        return {'freq_hz': f, 'level_dbm': a, 'settings': settings}

    def measure_harmonics(self, fundamental_hz: float, n_max: int = 5, span_hz: float = 1e6, rbw_hz: float = 30e3, vbw_hz: float = 30e3, ref_level_dbm: float = 10.0, atten_db: int = 20,
                          detector: str = 'POS', floor_dbm: float | None = None) -> dict:
        """The fundamental, then harmonics 2..n_max by CF = n x (measured fundamental), TS, MKPK HI, MKF? / MKA? (the manual has no harmonic command): a dict with 'fundamental_hz',
        'fundamental_dbm', 'harmonics' (one dict per harmonic: n, target_hz, freq_hz, level_dbm, dbc, found, at_floor) and 'dbc' (the list of dBc values, harmonic minus fundamental, in
        order 2..n_max; None for a harmonic above 26.5 GHz or with no peak within half a span of its target)."""
        if n_max < 2:
            raise InstrumentError('n_max must be 2 or more')
        fund = self.measure_fundamental(fundamental_hz, span_hz, rbw_hz, vbw_hz, ref_level_dbm, atten_db, detector)
        f1, a1 = fund['freq_hz'], fund['level_dbm']
        out = []
        for n in range(2, n_max + 1):
            target = n * f1
            row: dict[str, Any] = dict(n=n, target_hz=target, freq_hz=None, level_dbm=None, dbc=None, found=False, at_floor=False)
            if target > MAX_HZ:
                out.append(row)
                continue
            self.set_center_hz(target)
            self.take_sweep()
            f, a = self.marker_to_peak()
            row.update(freq_hz=f, level_dbm=a, found=abs(f - target) <= span_hz / 2.0)
            if row['found']:
                row['dbc'] = a - a1
                row['at_floor'] = floor_dbm is not None and a <= floor_dbm + 3.0
            out.append(row)
        self.check_errors('harmonics')
        return dict(fundamental_hz=f1, fundamental_dbm=a1, harmonics=out, dbc=[r['dbc'] for r in out])

    def scan_spurs(self, start_hz: float, stop_hz: float, carrier_hz: float | None = None, exclude_harmonics: int = 0, exclude_tol_hz: float | None = None, floor_dbm: float = -90.0,
                   excursion_db: float = 6.0, max_spurs: int = 10, max_peaks: int = 60, rbw_hz: float = 100e3, vbw_hz: float = 100e3, ref_level_dbm: float = 10.0, atten_db: int = 20,
                   detector: str = 'POS') -> dict:
        """One sweep from start to stop, then MKPK HI and repeated MKPK NH (UNVERIFIED that NH walks down the peak list: the walk stops when the marker lands on a frequency it has
        already visited, below floor_dbm, or after max_peaks). Peaks within exclude_tol_hz (default the larger of 2 x RBW and one trace point, span / 600) of n x carrier_hz for n = 1 .. exclude_harmonics (and the carrier itself)
        are not spurs. Returns {'peaks_visited', 'carrier_dbm', 'spurs': [{freq_hz, level_dbm, dbc}], 'stopped': reason}. Values are as the analyzer reports; dbc needs the carrier peak."""
        if stop_hz <= start_hz:
            raise InstrumentError('stop frequency must be above the start frequency')
        tol = exclude_tol_hz if exclude_tol_hz is not None else max(2.0 * rbw_hz, (stop_hz - start_hz) / 600.0)   # the marker sits on one of 601 trace points
        self.configure(None, None, rbw_hz, vbw_hz, ref_level_dbm, atten_db, detector)
        self.set_start_hz(start_hz)
        self.set_stop_hz(stop_hz)
        self.set_marker_threshold(floor_dbm)
        self.set_marker_excursion(excursion_db)
        self.single_sweep()
        self.take_sweep()
        harmonic_list = [carrier_hz * n for n in range(1, max(1, exclude_harmonics) + 1)] if carrier_hz else []
        visited, spurs, carrier_dbm, stopped = [], [], None, 'max_peaks'
        key = 'mkpk.hi'
        for _ in range(max_peaks):
            f, a = self.marker_to_peak(key)
            key = 'mkpk.nh'
            if a < floor_dbm:
                stopped = 'floor'
                break
            if any(abs(f - v) <= max(1.0, rbw_hz / 100.0) for v in visited):
                stopped = 'marker did not move to a new peak'
                break
            visited.append(f)
            if any(abs(f - h) <= tol for h in harmonic_list):
                if carrier_dbm is None and carrier_hz and abs(f - carrier_hz) <= tol:
                    carrier_dbm = a
                continue
            spurs.append(dict(freq_hz=f, level_dbm=a, dbc=None))
            if len(spurs) >= max_spurs:
                stopped = 'max_spurs'
                break
        if carrier_dbm is not None:
            for s in spurs:
                s['dbc'] = s['level_dbm'] - carrier_dbm
        self.send('mkoff')
        self.check_errors('spur scan')
        return dict(peaks_visited=len(visited), carrier_dbm=carrier_dbm, spurs=spurs, stopped=stopped)
