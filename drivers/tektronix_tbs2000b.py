"""Tektronix TBS2000B digital storage oscilloscope (TBS2072B / 2074B / 2102B / 2104B / 2202B / 2204B) over USB (USBTMC / VISA).

Every command is in COMMANDS with the page of the TBS2000B Series Programmer Manual (077-1149-04, May 2024) it was read from; the printed page numbers
equal the PDF page numbers of that manual.  Writes are never retried; every setting that matters is read back and compared, and the event status
register is checked after each group of settings (check_errors), so a rejected command stops the run instead of giving a reading for the wrong set-up.

The method names and arguments are the TDS2000C driver's (drivers/tektronix_tds2000c.py) so tds2000c_verification.Runner's calibrator helpers work
unchanged, but the command set is the TBS2000B's, which differs from the TDS2000C's in several places:
  CH<x>:PRObe is query-only here (probe 1X = CH<x>:PRObe:GAIN 1, p. 60); CH<x>:BANdwidth takes TWEnty / FULl (p. 56); the trigger tree is TRIGger:A (pp. 167-181);
  the horizontal position is a percentage, so the delay is HORizontal:DELay:MODe ON + HORizontal:DELay:TIMe (pp. 114-115); the waveform preamble is
  WFMOutpre (pp. 191-198) and the record length is selectable (HORizontal:RECOrdlength, p. 118); the measurement source is MEASUrement:IMMed:SOUrce1 (p. 131);
  the screen has 15 horizontal divisions (HORizontal:DIVisions?, p. 113).

UNVERIFIED (manual text only, never run on a TBS2000B): the reply formats with HEADer OFF / VERBose OFF (the manual's examples show headers); CH<x>:BANdwidth?
answering FULl rather than a frequency (both accepted); whether *CAL? is the same operation as the front-panel 'Compensate Signal Paths' (p. 52 calls it
self-calibration and points to CALibrate:INTERNal, the SPC); whether the remotely started self test updates DIAg:RESUlt:FLAg?
(p. 82 says power-on or Service-menu diagnostics); ACQuire:NUMACq? counting (p. 42 says RUN does not reset it, p. 44 says it does: wait_acquisitions() waits for `count` MORE acquisitions either way);
the *IDN? model text (the example on p. 121 prints 'TBS2104' without the B); CH<x>:PRObe:GAIN 1 being accepted with no probe attached; how the end of the
remotely started self test is signalled (BUSY? polling, registered verified=False).
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import TransportError

MANUAL = 'TBS2000B Series Programmer Manual 077-1149-04'
MODEL_RE = re.compile(r'TBS\s*(2(?:07|10|20)[24])\s*(B?)', re.I)
MODELS = ('2072B', '2074B', '2102B', '2104B', '2202B', '2204B')
FOUR_CHANNEL = ('2074B', '2104B', '2204B')
OVERFLOW = 9.9e37            # "no valid measurement" (p. 135)
RECORD_POINTS = 2000         # record length used for waveform reads (one of the values p. 118 lists)

_CH = {'ch': Placeholder('str', '', '1')}


def _c(template, name, page, description='', *, kind='set', readback=None, risk='normal', verified=True, placeholders=None):
    return Cmd(template, name, description, placeholders=placeholders or {}, kind=kind, readback=readback, risk=risk, verified=verified,
               ref=f'{MANUAL} p. {page}')


def _q(template, name, page, description='', **kw):
    return _c(template, name, page, description, kind='query', **kw)


def _f(name, fmt='.9g', sample=1.0):
    return {name: Placeholder('float', fmt, sample)}


def _s(name, sample):
    return {name: Placeholder('str', '', sample)}


def _i(name, sample):
    return {name: Placeholder('int', '', sample)}


# Every command the driver sends.  verified=True = the command text is printed in the programmer manual at the page given (not run on hardware).
# Locked: status / error-queue plumbing, the reply format (the code parses header-less replies), FACtory (the reset), the self test result and the signal path
# compensation (*CAL?), the waveform encoding.
COMMANDS = {
    'status.clear': _c('*CLS', 'Clear status', 65, 'Clears the event queue and the status registers (never overridable)', risk='locked'),
    'sys.header.off': _c('HEADer OFF', 'Replies without headers', 107, 'The code parses header-less replies', risk='locked'),
    'sys.verbose.off': _c('VERBose OFF', 'Short keywords in replies', 183, risk='locked'),
    'esr.query': _q('*ESR?', 'Event status register', 89, 'Error check after each group of settings (check_errors)', risk='locked'),
    'evmsg.query': _q('EVMsg?', 'Event message', 90, 'Text of the event that set the error bit', risk='locked'),
    'default.factory': _c('FACtory', 'Factory defaults (Default Setup)', 92, 'Before every test set-up; does not touch calibration data', kind='action', risk='locked'),
    # vertical
    'ch.on': _c('SELect:CH{n} ON', 'Display a channel', 160, placeholders=_i('n', 1)),
    'ch.off': _c('SELect:CH{n} OFF', 'Remove a channel from the display', 160, placeholders=_i('n', 2)),
    'ch.coupling.set': _c('CH{ch}:COUPling {value}', 'Input coupling (AC / DC)', 57, readback='ch.coupling.get', placeholders={**_CH, **_s('value', 'DC')}),
    'ch.coupling.get': _q('CH{ch}:COUPling?', 'Input coupling read-back', 57, placeholders=_CH),
    'ch.bw.set': _c('CH{ch}:BANdwidth {value}', 'Bandwidth limit (TWEnty / FULl)', 56, readback='ch.bw.get', placeholders={**_CH, **_s('value', 'FULl')}),
    'ch.bw.get': _q('CH{ch}:BANdwidth?', 'Bandwidth limit read-back', 56, placeholders=_CH),
    'ch.probe.set': _c('CH{ch}:PRObe:GAIN {value:.9g}', 'Probe gain (1 = 1X)', 60, readback='ch.probe.get', placeholders={**_CH, **_f('value', '.9g', 1.0)}),
    'ch.probe.get': _q('CH{ch}:PRObe:GAIN?', 'Probe gain read-back', 61, placeholders=_CH),
    'ch.scale.set': _c('CH{ch}:SCAle {value:.9g}', 'Vertical scale (V/div)', 63, readback='ch.scale.get', placeholders={**_CH, **_f('value', '.9g', 0.5)}),
    'ch.scale.get': _q('CH{ch}:SCAle?', 'Vertical scale read-back', 63, placeholders=_CH),
    'ch.pos.set': _c('CH{ch}:POSition {value:.9g}', 'Vertical position (div)', 60, readback='ch.pos.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.pos.get': _q('CH{ch}:POSition?', 'Vertical position read-back', 60, placeholders=_CH),
    'ch.offset.set': _c('CH{ch}:OFFSet {value:.9g}', 'Vertical offset (V)', 59, readback='ch.offset.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.offset.get': _q('CH{ch}:OFFSet?', 'Vertical offset read-back', 59, placeholders=_CH),
    # acquisition
    'acq.mode.set': _c('ACQuire:MODe {value}', 'Acquisition mode (SAMple / AVErage)', 42, readback='acq.mode.get', placeholders=_s('value', 'SAMple')),
    'acq.mode.get': _q('ACQuire:MODe?', 'Acquisition mode read-back', 42),
    'acq.numavg.set': _c('ACQuire:NUMAVg {value:.9g}', 'Number of averages (2 to 512, powers of two)', 43, readback='acq.numavg.get', placeholders=_f('value', '.9g', 16.0)),
    'acq.numavg.get': _q('ACQuire:NUMAVg?', 'Number of averages read-back', 43),
    'acq.stopafter': _c('ACQuire:STOPAfter RUNSTop', 'Acquire continuously', 44),
    'acq.run': _c('ACQuire:STATE RUN', 'Start the acquisition', 44),
    'acq.numacq': _q('ACQuire:NUMACq?', 'Acquisitions completed', 42),
    # horizontal
    'hor.scale.set': _c('HORizontal:SCAle {value:.9g}', 'Time base (s/div)', 116, readback='hor.scale.get', placeholders=_f('value', '.9g', 1e-3)),
    'hor.scale.get': _q('HORizontal:SCAle?', 'Time base read-back', 116),
    'hor.reclen.set': _c('HORizontal:RECOrdlength {value:.9g}', 'Record length (points)', 118, readback='hor.reclen.get', placeholders=_f('value', '.9g', 2000.0)),
    'hor.reclen.get': _q('HORizontal:RECOrdlength?', 'Record length read-back', 118),
    'hor.delay.mode.set': _c('HORizontal:DELay:MODe {value}', 'Horizontal delay mode (ON / OFF)', 114, readback='hor.delay.mode.get', placeholders=_s('value', 'ON')),
    'hor.delay.mode.get': _q('HORizontal:DELay:MODe?', 'Horizontal delay mode read-back', 114),
    'hor.delay.time.set': _c('HORizontal:DELay:TIMe {value:.12g}', 'Horizontal delay time (s)', 115, readback='hor.delay.time.get', placeholders=_f('value', '.12g', 1e-3)),
    'hor.delay.time.get': _q('HORizontal:DELay:TIMe?', 'Horizontal delay time read-back', 115),
    # trigger
    'trig.type': _c('TRIGger:A:TYPe EDGe', 'Edge trigger', 180),
    'trig.source.set': _c('TRIGger:A:EDGE:SOUrce {value}', 'Edge trigger source (CH1 ... CH4 / LINE)', 169, readback='trig.source.get', placeholders=_s('value', 'CH1')),
    'trig.source.get': _q('TRIGger:A:EDGE:SOUrce?', 'Edge trigger source read-back', 169),
    'trig.slope.set': _c('TRIGger:A:EDGE:SLOpe {value}', 'Edge trigger slope (RISe / FALL)', 169, readback='trig.slope.get', placeholders=_s('value', 'RISe')),
    'trig.slope.get': _q('TRIGger:A:EDGE:SLOpe?', 'Edge trigger slope read-back', 169),
    'trig.coupling.set': _c('TRIGger:A:EDGE:COUPling {value}', 'Edge trigger coupling (DC / NOISErej ...)', 168, readback='trig.coupling.get',
                            placeholders=_s('value', 'DC')),
    'trig.coupling.get': _q('TRIGger:A:EDGE:COUPling?', 'Edge trigger coupling read-back', 168),
    'trig.mode.set': _c('TRIGger:A:MODe {value}', 'Trigger mode (AUTO / NORMal)', 173, readback='trig.mode.get', placeholders=_s('value', 'AUTO')),
    'trig.mode.get': _q('TRIGger:A:MODe?', 'Trigger mode read-back', 173),
    'trig.setlevel': _c('TRIGger:A SETLevel', 'Trigger level to 50 %', 167),
    'trig.state': _q('TRIGger:STATE?', 'Trigger state', 181),
    # immediate measurement
    'meas.source.set': _c('MEASUrement:IMMed:SOUrce1 {value}', 'Measurement source', 132, readback='meas.source.get', placeholders=_s('value', 'CH1')),
    'meas.source.get': _q('MEASUrement:IMMed:SOUrce1?', 'Measurement source read-back', 132),
    'meas.type.set': _c('MEASUrement:IMMed:TYPe {value}', 'Measurement type (MEAN / PK2Pk)', 133, readback='meas.type.get', placeholders=_s('value', 'MEAN')),
    'meas.type.get': _q('MEASUrement:IMMed:TYPe?', 'Measurement type read-back', 133),
    'meas.value': _q('MEASUrement:IMMed:VALue?', 'Measurement value', 135),
    # waveform transfer
    'data.source': _c('DATa:SOUrce CH{ch}', 'Waveform source', 77, placeholders=_CH),
    'wfm.encdg': _c('WFMOutpre:ENCdg ASCii', 'ASCII waveform encoding', 193, 'The code parses ASCII curve data', risk='locked'),
    'data.width': _c('DATa:WIDth 1', 'One byte per point', 79),
    'data.start': _c('DATa:STARt {n}', 'First point', 78, placeholders=_i('n', 1)),
    'data.stop': _c('DATa:STOP {n}', 'Last point', 78, placeholders=_i('n', RECORD_POINTS)),
    'wfm.nrpt': _q('WFMOutpre:NR_Pt?', 'Points that CURVe? will send', 194),
    'wfm.xincr': _q('WFMOutpre:XINcr?', 'Sample interval', 195),
    'wfm.xzero': _q('WFMOutpre:XZEro?', 'Time of the first point relative to the trigger', 196),
    'wfm.ymult': _q('WFMOutpre:YMUlt?', 'Volts per digitizing level', 197),
    'wfm.yoff': _q('WFMOutpre:YOFf?', 'Vertical position in digitizing levels', 197),
    'wfm.yzero': _q('WFMOutpre:YZEro?', 'Vertical offset (V)', 198),
    'wfm.curve': _q('CURVe?', 'Waveform data', 74),
    # self test result / signal path compensation (never overridable)
    'diag.loop': _c('DIAg:LOOP:OPTion ONCE', 'Self test: one loop', 81, 'Runs the self test sequence once (the manual\'s Loop 1 Times, p. 22)', risk='locked'),
    'diag.select': _c('DIAg:SELect ALL', 'Self test: all diagnostic groups', 83, risk='locked'),
    'diag.run': _c('DIAg:STATE EXECute', 'Self test: start', 84, 'Starts the diagnostics (an action: never retried)', kind='action', risk='locked'),
    'diag.busy': Cmd('BUSY?', 'Busy (self test completion)', 'BUSY? exists (p. 51) but Table 30 (p. 209) does not list DIAg:STATE among the operations it '
                     'tracks: using it to wait for the end of the self test is NOT documented', kind='query', risk='locked', verified=False, ref=''),
    'diag.flag': _q('DIAg:RESUlt:FLAg?', 'Self test result', 82, 'PASS / FAIL of the last diagnostic sequence', risk='locked'),
    'diag.log': _q('DIAg:RESUlt:LOG?', 'Self test log', 83, risk='locked'),
    'spc.run': _q('*CAL?', 'Signal path compensation (runs it; 0 = no errors)', 52, 'An action in query form: never retried', risk='locked'),
    'spc.result': _q('CALibrate:RESults:SPC?', 'Signal path compensation result', 54, risk='locked'),
}
COMMANDS['opc.query'] = cmdreg.opc_cmd(True, f'{MANUAL} p. 149')
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{MANUAL} p. 92 (FACtory)', template='FACtory',
                                     note='FACtory (Default Setup), not *RST; it does not reset calibration data (p. 92); the signal path compensation is never part of the reset')


def _last(reply: str) -> str:
    return reply.strip().replace(';', ' ').split()[-1].strip('"') if reply.strip() else ''


def _last_number(reply: str) -> float:
    """The number at the end of a reply, with or without a header (':CH1:SCALE 1.0E-1')."""
    return float(_last(reply))


def _last_word(reply: str) -> str:
    return _last(reply).upper()


def _same_word(got: str, want: str) -> bool:
    """Enumerated read-back: the reply may be the long or the short form, any case ('NORMAL' / 'NORM' for NORMal; 'ON' / '1')."""
    g, w = got.upper(), want.upper()
    if {g, w} <= {'ON', '1'} or {g, w} <= {'OFF', '0'}:
        return True
    return g.startswith(w[:3]) or w.startswith(g[:3])


class TektronixTBS2000B(Instrument):
    MODEL = 'Tektronix TBS2000B'
    COMMANDS = COMMANDS
    IDN_MATCH = ('TBS2',)
    DEFAULT_TIMEOUT = 15.0
    RESET_OPC_TIMEOUT = 60.0         # FACtory is waited for as default_setup() does
    SELF_CAL_TIMEOUT = 600.0         # "can take several minutes" (p. 52)
    SELF_TEST_TIMEOUT = 900.0        # generous: the manual gives no duration for the self test
    SELF_TEST_SETTLE = 5.0           # wait after DIAg:STATE EXECute before the first completion poll
    SELF_TEST_POLL = 2.0
    SPC_PASS = 'PASS'
    model = ''
    channels = 2

    # ---- connection ---------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self.idn = self.identify()
        self.model = self.model_from_idn(self.idn)
        self.channels = 4 if self.model in FOUR_CHANNEL else 2
        return self

    @staticmethod
    def model_from_idn(idn: str) -> str:
        """'2104B' from 'TEKTRONIX,TBS2104B,C012345,...' or from the manual's example 'TEKTRONIX,TBS2104 ,CU10100,...' (p. 121, no B); '' otherwise.
        A TBS2000 (no B) cannot be told apart by this text: the procedure covers the TBS2000B only (UNVERIFIED on a real scope)."""
        m = MODEL_RE.search(idn or '')
        return (m.group(1) + 'B').upper() if m else ''

    def cleanup(self):
        """The scope has no outputs; nothing to turn off."""

    def _reset_extra(self):
        """FACtory turns the command headers on again (p. 92): put back the header-less, short replies the code parses, then require a clean event status
        register.  No signal path compensation, no *RST."""
        return [('replies without headers (HEADer OFF)', lambda: self.send('sys.header.off')),
                ('short keywords (VERBose OFF)', lambda: self.send('sys.verbose.off')),
                ('event status clean (*ESR?)', lambda: self.check_errors('reset'))]

    # ---- helpers --------------------------------------------------------------------------------------------------------
    def opc(self, timeout=None):
        if timeout:
            self.t.set_timeout(timeout)
        try:
            self.ask('opc.query')
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device / query error since the last check (*ESR? clears it, p. 89)."""
        esr = int(_last_number(self.ask('esr.query')))
        if esr & 0b00111100:
            try:
                detail = self.ask('evmsg.query').strip()
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def set_verified(self, set_key, get_key, value, rel=1e-3, abs_=1e-12, label=None, **vals):
        """Write a numeric setting (registered key pair), read it back, compare. Never retried."""
        self.send(set_key, value=value, **vals)
        got = _last_number(self.ask(get_key, **vals))
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{label or set_key}: set {value:g}, instrument reports {got:g}')
        return got

    def set_enum_verified(self, set_key, get_key, value, label=None, accept=None, **vals):
        """Write an enumerated setting, read it back, compare the first letters (replies are abbreviated or upper case).  `accept(reply)` may allow
        another documented form of the reply."""
        self.send(set_key, value=value, **vals)
        got = _last_word(self.ask(get_key, **vals))
        if not (_same_word(got, value) or (accept is not None and accept(got))):
            raise InstrumentError(f'{label or set_key}: set {value}, instrument reports {got}')
        return got

    # ---- state ----------------------------------------------------------------------------------------------------------
    def default_setup(self):
        """FACtory (p. 92), the front-panel Default Setup. It enables command headers again, so HEADer OFF / VERBose OFF are re-sent."""
        self.send('default.factory')
        self.opc(60)
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self.check_errors('FACtory')

    def run_self_test(self, timeout=None, poll=None, settle=None):
        """Run the self test remotely and return (passed, log text).  DIAg:LOOP:OPTion ONCE (p. 81), DIAg:SELect ALL (p. 83), DIAg:STATE EXECute (p. 84),
        each sent once (never retried); then wait for the end with BUSY? (p. 51) until it answers 0.  The manual does NOT document how the end of the
        self test is signalled (DIAg:STATE has no query form, and Table 30 p. 209 does not list it for *OPC / BUSY?), so the wait is UNVERIFIED: a poll
        that gets no answer is taken as 'still running' (read-only, asked again after a device clear) until `timeout`.  Then DIAg:RESUlt:FLAg? (p. 82)
        and DIAg:RESUlt:LOG? (p. 83): passed = PASS, and the log names no FAIL and no NOT RUN module."""
        timeout = self.SELF_TEST_TIMEOUT if timeout is None else timeout
        poll = self.SELF_TEST_POLL if poll is None else poll
        self.send('diag.loop')
        self.send('diag.select')
        self.send('diag.run')
        time.sleep(self.SELF_TEST_SETTLE if settle is None else settle)
        deadline = time.monotonic() + timeout
        while True:
            try:
                busy = int(_last_number(self.ask('diag.busy')))
            except (TransportError, ValueError):
                busy = 1
                try:
                    self.t.clear()
                except Exception:
                    pass
            if busy == 0:
                break
            if time.monotonic() >= deadline:
                raise InstrumentError(f'The self test did not report completion (BUSY? 0) within {timeout:g} s')
            time.sleep(poll)
        flag = _last_word(self.ask('diag.flag'))
        try:
            log = self.ask('diag.log').strip()
        except Exception:
            log = ''
        bad = 'FAIL' in log.upper() or 'NOT RUN' in log.upper()
        return flag == 'PASS' and not bad, log

    def self_cal(self):
        """Signal path compensation: *CAL? runs it and answers 0 when no errors were found (p. 52); CALibrate:RESults:SPC? must then say PASS (p. 54).
        All inputs must be disconnected first. Not retried (it is an action, not just a query)."""
        self.t.set_timeout(self.SELF_CAL_TIMEOUT)
        try:
            result = int(_last_number(self.ask('spc.run')))
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        status = _last_word(self.ask('spc.result'))
        return result == 0 and status == self.SPC_PASS, f'*CAL? = {result}, CALibrate:RESults:SPC? = {status}'

    # ---- vertical -------------------------------------------------------------------------------------------------------
    def select_only(self, ch):
        """Display channel ch (SELect:CH<x>, p. 160) and remove the others; the wanted channel is switched on first so one is always displayed."""
        self.send('ch.on', n=ch)
        for n in range(1, self.channels + 1):
            if n != ch:
                self.send('ch.off', n=n)

    def channel(self, ch, vscale=None, position=0.0, probe=1, coupling='DC', bw_limit=False, offset=None):
        """Probe 1X, DC coupling, full bandwidth, volts/div, position (divisions) and offset (volts), each read back.  The scale is set before the
        offset because the offset range depends on it (p. 59).  Position / offset read-back tolerance: 0.02 division (resolution not printed; UNVERIFIED)."""
        c = str(ch)
        self.set_enum_verified('ch.coupling.set', 'ch.coupling.get', coupling, label=f'CH{ch}:COUPling', ch=c)
        self.set_enum_verified('ch.bw.set', 'ch.bw.get', 'TWEnty' if bw_limit else 'FULl', label=f'CH{ch}:BANdwidth', ch=c,
                               accept=lambda got: _bandwidth_reply_ok(got, bw_limit))
        self.set_verified('ch.probe.set', 'ch.probe.get', float(probe), rel=1e-6, label=f'CH{ch}:PRObe:GAIN', ch=c)
        if vscale is not None:
            self.set_verified('ch.scale.set', 'ch.scale.get', vscale, rel=1e-3, label=f'CH{ch}:SCAle', ch=c)
        div = 0.02 * (vscale if vscale is not None else 1.0)
        if position is not None:
            self.set_verified('ch.pos.set', 'ch.pos.get', position, abs_=0.02, label=f'CH{ch}:POSition', ch=c)
        if offset is not None:
            self.set_verified('ch.offset.set', 'ch.offset.get', offset, rel=1e-4, abs_=div, label=f'CH{ch}:OFFSet', ch=c)

    def position(self, ch, divisions):
        return self.set_verified('ch.pos.set', 'ch.pos.get', divisions, abs_=0.02, label=f'CH{ch}:POSition', ch=str(ch))

    # ---- acquisition ----------------------------------------------------------------------------------------------------
    def acquire_mode(self, mode, averages=16):
        """SAMple or AVErage (p. 42); averages 2 to 512 in powers of two (p. 43); continuous acquisition, running."""
        self.set_enum_verified('acq.mode.set', 'acq.mode.get', mode, label='ACQuire:MODe')
        if mode.upper().startswith('AVE'):
            self.set_verified('acq.numavg.set', 'acq.numavg.get', float(averages), rel=1e-6, label='ACQuire:NUMAVg')
        self.send('acq.stopafter')
        self.run()

    def run(self):
        """ACQuire:STATE RUN (p. 44)."""
        self.send('acq.run')

    def num_acq(self):
        return int(_last_number(self.query_retry('acq.numacq')))          # p. 42 (read-only, retry allowed)

    def wait_acquisitions(self, count, timeout=30.0, poll=0.1):
        """Restart the acquisition and wait until `count` MORE acquisitions have completed than right after the restart (p. 42 and p. 44 disagree on
        whether RUN resets the counter; counting from the value read after RUN is right either way)."""
        self.run()
        start = self.num_acq()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.num_acq() >= start + count:
                return
            time.sleep(poll)
        raise InstrumentError(f'The oscilloscope completed fewer than {count} acquisitions in {timeout:g} s')

    # ---- horizontal ----------------------------------------------------------------------------------------------------
    def timebase(self, seconds_per_div):
        """HORizontal:SCAle (p. 116)."""
        self.set_verified('hor.scale.set', 'hor.scale.get', seconds_per_div, rel=1e-3, label='HORizontal:SCAle')

    def record_length(self, points=RECORD_POINTS):
        """HORizontal:RECOrdlength (p. 118): 1000, 2000, 20000, 200000, 2000000 or 5000000 points."""
        self.set_verified('hor.reclen.set', 'hor.reclen.get', float(points), rel=1e-9, label='HORizontal:RECOrdlength')

    def delay(self, seconds):
        """Horizontal delay mode on (p. 114) and the delay time from the trigger to the centre of the screen (p. 115). Read back with a 1 ns floor."""
        self.set_enum_verified('hor.delay.mode.set', 'hor.delay.mode.get', 'ON', label='HORizontal:DELay:MODe')
        self.set_verified('hor.delay.time.set', 'hor.delay.time.get', seconds, rel=1e-6, abs_=1e-9, label='HORizontal:DELay:TIMe')

    # ---- trigger --------------------------------------------------------------------------------------------------------
    def trigger_edge(self, source, slope='RISe', mode='AUTO', coupling='NOISErej'):
        """Edge trigger (TRIGger:A:..., pp. 168-180). source CH1..CH4 or LINE; coupling None leaves the default (DC, used with LINE)."""
        self.send('trig.type')
        self.set_enum_verified('trig.source.set', 'trig.source.get', source, label='TRIGger:A:EDGE:SOUrce')
        self.set_enum_verified('trig.slope.set', 'trig.slope.get', slope, label='TRIGger:A:EDGE:SLOpe')
        if coupling:
            self.set_enum_verified('trig.coupling.set', 'trig.coupling.get', coupling, label='TRIGger:A:EDGE:COUPling')
        self.trigger_mode(mode)

    def trigger_mode(self, mode):
        self.set_enum_verified('trig.mode.set', 'trig.mode.get', mode, label='TRIGger:A:MODe')

    def set_level_50(self):
        """Trigger level to 50 %: TRIGger:A SETLevel (p. 167), with the acquisition running."""
        self.run()
        self.send('trig.setlevel')
        self.check_errors('TRIGger:A SETLevel')

    def trigger_state(self):
        """ARMED, AUTO, READY, SAVE or TRIGGER (p. 181)."""
        return _last_word(self.query_retry('trig.state'))

    # ---- measurements ---------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, ch):
        """Immediate measurement source and type (pp. 132, 133): MEAN or PK2Pk."""
        self.set_enum_verified('meas.source.set', 'meas.source.get', f'CH{ch}', label='MEASUrement:IMMed:SOUrce1')
        self.set_enum_verified('meas.type.set', 'meas.type.get', mtype, label='MEASUrement:IMMed:TYPe')

    def meas_value(self):
        """MEASUrement:IMMed:VALue? (p. 135). 9.9E37 means no valid measurement."""
        v = _last_number(self.ask('meas.value'))
        if not math.isfinite(v) or abs(v) >= OVERFLOW:
            raise InstrumentError(f'The oscilloscope returned no valid measurement ({v:g}); check the channel is displayed and the signal is connected')
        return v

    def measure(self, mtype, ch, count=16, timeout=40.0):
        """Set up the measurement, let `count` more acquisitions complete, read one value."""
        self.measure_setup(mtype, ch)
        self.wait_acquisitions(count, timeout=timeout)
        value = self.meas_value()
        self.check_errors(f'{mtype} measurement on CH{ch}')
        return value

    # ---- waveform record ------------------------------------------------------------------------------------------------
    def waveform(self, ch, points=RECORD_POINTS):
        """(times, volts) of the acquired record of CH<ch> (the record length set with record_length()). Times are relative to the trigger:
        t = XZEro + n * XINcr (pp. 195, 196); volts = (level - YOFf) * YMUlt + YZEro (pp. 197, 198). ASCII, one byte per point."""
        self.send('data.source', ch=str(ch))
        self.send('wfm.encdg')
        self.send('data.width')
        self.send('data.start', n=1)
        self.send('data.stop', n=int(points))
        npts = int(_last_number(self.ask('wfm.nrpt')))
        xinc = _last_number(self.ask('wfm.xincr'))
        xzero = _last_number(self.ask('wfm.xzero'))
        ymult = _last_number(self.ask('wfm.ymult'))
        yoff = _last_number(self.ask('wfm.yoff'))
        yzero = _last_number(self.ask('wfm.yzero'))
        raw = self.ask('wfm.curve').strip()
        if raw.upper().startswith(':CURVE'):
            raw = raw[6:]
        elif raw.upper().startswith('CURVE'):
            raw = raw[5:]
        try:
            dl = [float(x) for x in raw.replace(';', ',').split(',') if x.strip()]
        except ValueError:
            raise InstrumentError(f'Unreadable waveform data from CURVe?: {raw[:60]!r}')
        if len(dl) < 100 or xinc <= 0 or ymult == 0 or (npts and abs(len(dl) - npts) > 1):
            raise InstrumentError(f'Waveform record not usable (points {len(dl)} of {npts}, XINcr {xinc:g}, YMUlt {ymult:g})')
        times = [xzero + i * xinc for i in range(len(dl))]
        volts = [(d - yoff) * ymult + yzero for d in dl]
        self.check_errors(f'waveform CH{ch}')
        return times, volts


def _bandwidth_reply_ok(got: str, bw_limit: bool) -> bool:
    """CH<x>:BANdwidth? may answer a frequency instead of TWEnty / FULl (p. 56 allows <NR3>): 20 MHz for the limit, anything above it for full."""
    try:
        hz = float(got)
    except ValueError:
        return False
    return math.isclose(hz, 20e6, rel_tol=0.05) if bw_limit else hz > 25e6
