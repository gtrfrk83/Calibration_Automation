"""Tektronix TBS1000C (TBS1052C / TBS1072C / TBS1102C / TBS1202C) digital oscilloscope over USB (USBTMC / VISA).

Commands from the TBS1000C Series Digital Oscilloscopes Programmer Manual (077-1691-02, May 2024); every COMMANDS entry names its page (printed
page = PDF page in that manual).  The class offers the same methods as drivers/tektronix_tds2000c.py, so the shared Tektronix engine
(tds2000c_verification.py) runs it unchanged; the wire text is the TBS1000C's own, which differs from the TDS2000C / TBS1000 family:
  TRIGger:A:... (not TRIGger:MAIn:...), WFMOutpre:... (not WFMPre:...), WFMOutpre:ENCdg (no DATa:ENCdg), MEASUrement:IMMed:SOUrce1,
  CH<x>:PRObe:GAIN (CH<x>:PRObe is a query only), CH<x>:BANdwidth FULl|TWEnty (not ON|OFF), CALibrate:INTERNal:STATus? (not CALibrate:STATUS?),
  HORizontal:MAIn:POSition in PERCENT of the record (the delay in seconds is HORizontal:MAIn:DELay:TIMe with the delay mode ON), and the Aux In
  trigger source is AUX (not EXT).  The record is 1000 / 2000 / 20000 points over 15 horizontal divisions (HORizontal:DIVisions?, p. 93): the
  driver sets 2000 points (RECORD_POINTS) after every Default Setup and the engine reads that and H_DIVS.

Writes are sent once and never retried; every setting is read back and compared (numbers within a tolerance, keywords by their first letters
because VERBose OFF returns minimum-length keywords, p. 162); the Standard Event Status Register is read after each group of settings
(check_errors: *ESR? p. 70, EVMsg? p. 71) so a rejected command stops the run.  Only read-only queries are retried.

UNVERIFIED (verified=False; no TBS1000C was available): nothing in COMMANDS is unverified in the sense of "not in the manual" - each was read in the
manual - but the reply formats, the HORizontal:MAIn:DELay / XZEro time axis, the 2000-point record at 2 ns/div, ACQuire:NUMACq? counting after
ACQuire:STATE RUN (p. 23 says the count does not reset when acquisitions start; the p. 25 example says RUN resets it: wait_acquisitions counts
from the value read after RUN, so either works) and the self-calibration duration were not seen on an instrument.
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from surprise import SurpriseMixin
from .base import Instrument, InstrumentError

_REF = 'TBS1000C Programmer Manual 077-1691-02'
MODEL_RE = re.compile(r'TBS\s*(1(?:05|07|10|20)2C)', re.I)
OVERFLOW = 9.9e37            # "no valid measurement" (MEASUrement:IMMed:VALue? example, p. 115)
_CH = {'ch': Placeholder('int', '', 1)}


def _c(template, name, page, *, kind='set', readback=None, risk='normal', placeholders=None, description=''):
    return Cmd(template, name, description, placeholders=placeholders or {}, kind=kind, readback=readback, risk=risk, verified=True,
               ref=f'{_REF}, p. {page}')


def _q(template, name, page, **kw):
    return _c(template, name, page, kind='query', **kw)


def _f(name, fmt='.9g', sample=1.0):
    return {name: Placeholder('float', fmt, sample)}


def _s(name, sample):
    return {name: Placeholder('str', '', sample)}


COMMANDS = {
    # status / plumbing (locked: the code parses the replies in this form)
    'status.clear': _c('*CLS', 'Clear status', 46, risk='locked'),
    'sys.header.off': _c('HEADer OFF', 'Replies without headers', 87, risk='locked'),
    'sys.verbose.off': _c('VERBose OFF', 'Short keywords in replies', 162, risk='locked'),
    'opc.query': _q('*OPC?', 'Operation complete', 128, risk='locked'),
    'esr.query': _q('*ESR?', 'Event status register', 70, risk='locked'),
    'evmsg.query': _q('EVMsg?', 'Event message', 71, risk='locked'),
    # self test / signal path calibration (locked: diagnostics and calibration)
    'diag.flag': _q('DIAg:RESUlt:FLAg?', 'Power-on diagnostics result', 63, risk='locked'),
    'diag.log': _q('DIAg:RESUlt:LOG?', 'Power-on diagnostics log', 64, risk='locked'),
    'cal.self': _q('*CAL?', 'Self calibration (Do Self Cal)', 33, risk='locked'),
    'cal.status': _q('CALibrate:INTERNal:STATus?', 'Self calibration status', 34, risk='locked'),
    # vertical
    'ch.on': _c('SELect:CH{ch} ON', 'Display channel on', 139, placeholders=_CH),
    'ch.off': _c('SELect:CH{ch} OFF', 'Display channel off', 139, placeholders=_CH),
    'ch.coupling.set': _c('CH{ch}:COUPling {value}', 'Input coupling (AC / DC)', 38, readback='ch.coupling.get', placeholders={**_CH, **_s('value', 'DC')}),
    'ch.coupling.get': _q('CH{ch}:COUPling?', 'Input coupling read-back', 38, placeholders=_CH),
    'ch.bw.set': _c('CH{ch}:BANdwidth {value}', 'Bandwidth limit (FULl / TWEnty)', 37, readback='ch.bw.get', placeholders={**_CH, **_s('value', 'FULl')}),
    'ch.bw.get': _q('CH{ch}:BANdwidth?', 'Bandwidth limit read-back', 37, placeholders=_CH),
    'ch.probe.set': _c('CH{ch}:PRObe:GAIN {value:.9g}', 'Probe gain (1 = 1X probe)', 41, readback='ch.probe.get', placeholders={**_CH, **_f('value', '.9g', 1.0)}),
    'ch.probe.get': _q('CH{ch}:PRObe:GAIN?', 'Probe gain read-back', 41, placeholders=_CH),
    'ch.scale.set': _c('CH{ch}:SCAle {value:.9g}', 'Vertical scale (V/div)', 44, readback='ch.scale.get', placeholders={**_CH, **_f('value', '.9g', 0.5)}),
    'ch.scale.get': _q('CH{ch}:SCAle?', 'Vertical scale read-back', 44, placeholders=_CH),
    'ch.offset.set': _c('CH{ch}:OFFSet {value:.9g}', 'Vertical offset (V)', 40, readback='ch.offset.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.offset.get': _q('CH{ch}:OFFSet?', 'Vertical offset read-back', 40, placeholders=_CH),
    'ch.pos.set': _c('CH{ch}:POSition {value:.9g}', 'Vertical position (div, +/-5)', '40-41', readback='ch.pos.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.pos.get': _q('CH{ch}:POSition?', 'Vertical position read-back', 41, placeholders=_CH),
    # acquisition
    'acq.mode.set': _c('ACQuire:MODe {mode}', 'Acquisition mode (SAMple / AVErage)', '22-23', readback='acq.mode.get', placeholders=_s('mode', 'SAMple')),
    'acq.mode.get': _q('ACQuire:MODe?', 'Acquisition mode read-back', 23),
    'acq.numavg.set': _c('ACQuire:NUMAVg {averages:d}', 'Number of averages (2 to 512, powers of two)', 24, readback='acq.numavg.get',
                         placeholders={'averages': Placeholder('int', 'd', 16)}),
    'acq.numavg.get': _q('ACQuire:NUMAVg?', 'Number of averages read-back', 24),
    'acq.stopafter': _c('ACQuire:STOPAfter RUNSTop', 'Acquire continuously', 25),
    'acq.run': _c('ACQuire:STATE RUN', 'Start acquisitions', '24-25'),
    'acq.numacq': _q('ACQuire:NUMACq?', 'Acquisitions so far', '23-24'),
    # horizontal
    'hor.scale.set': _c('HORizontal:MAIn:SCAle {value:.9g}', 'Time base (s/div, 1-2-4 sequence)', 96, readback='hor.scale.get', placeholders=_f('value', '.9g', 1e-3)),
    'hor.scale.get': _q('HORizontal:MAIn:SCAle?', 'Time base read-back', 96),
    'hor.reclen.set': _c('HORizontal:RECOrdlength {npts:d}', 'Record length (1000 / 2000 / 20000)', 98, readback='hor.reclen.get',
                         placeholders={'npts': Placeholder('int', 'd', 2000)}),
    'hor.reclen.get': _q('HORizontal:RECOrdlength?', 'Record length read-back', 98),
    'hor.delaymode.set': _c('HORizontal:MAIn:DELay:MODe {state}', 'Horizontal delay mode (ON / OFF)', 94, readback='hor.delaymode.get', placeholders=_s('state', 'OFF')),
    'hor.delaymode.get': _q('HORizontal:MAIn:DELay:MODe?', 'Horizontal delay mode read-back', 94),
    'hor.delay.set': _c('HORizontal:MAIn:DELay:TIMe {seconds:.12g}', 'Horizontal delay time (s)', 95, readback='hor.delay.get', placeholders=_f('seconds', '.12g', 1e-3)),
    'hor.delay.get': _q('HORizontal:MAIn:DELay:TIMe?', 'Horizontal delay time read-back', 95),
    'hor.pos.set': _c('HORizontal:MAIn:POSition {percent:.9g}', 'Horizontal position (% of the record left of centre)', 93, readback='hor.pos.get',
                      placeholders=_f('percent', '.9g', 50.0)),
    'hor.pos.get': _q('HORizontal:MAIn:POSition?', 'Horizontal position read-back', 93),
    # trigger
    'trig.type': _c('TRIGger:A:TYPe EDGE', 'Edge trigger', '158-159'),
    'trig.source.set': _c('TRIGger:A:EDGE:SOUrce {source}', 'Edge trigger source (CH1 / CH2 / LINE / AUX)', '148-149', readback='trig.source.get',
                          placeholders=_s('source', 'CH1')),
    'trig.source.get': _q('TRIGger:A:EDGE:SOUrce?', 'Edge trigger source read-back', 148),
    'trig.slope.set': _c('TRIGger:A:EDGE:SLOpe {slope}', 'Edge trigger slope (RISe / FALL)', 148, readback='trig.slope.get', placeholders=_s('slope', 'RISe')),
    'trig.slope.get': _q('TRIGger:A:EDGE:SLOpe?', 'Edge trigger slope read-back', 148),
    'trig.coupling.set': _c('TRIGger:A:EDGE:COUPling {coupling}', 'Edge trigger coupling (DC / HFRej / LFRej / NOISErej)', '147-148', readback='trig.coupling.get',
                            placeholders=_s('coupling', 'DC')),
    'trig.coupling.get': _q('TRIGger:A:EDGE:COUPling?', 'Edge trigger coupling read-back', 147),
    'trig.mode.set': _c('TRIGger:A:MODe {mode}', 'Trigger mode (AUTO / NORMal)', 152, readback='trig.mode.get', placeholders=_s('mode', 'AUTO')),
    'trig.mode.get': _q('TRIGger:A:MODe?', 'Trigger mode read-back', 152),
    'trig.setlevel': _c('TRIGger:A SETLevel', 'Set trigger level to 50 %', 146),
    'trig.state': _q('TRIGger:STATE?', 'Trigger state', 160),
    # measurements
    'meas.source.set': _c('MEASUrement:IMMed:SOUrce1 CH{ch}', 'Immediate measurement source', '111-112', readback='meas.source.get', placeholders=_CH),
    'meas.source.get': _q('MEASUrement:IMMed:SOUrce1?', 'Immediate measurement source read-back', 112),
    'meas.type.set': _c('MEASUrement:IMMed:TYPe {mtype}', 'Immediate measurement type (MEAN / PK2Pk)', 113, readback='meas.type.get', placeholders=_s('mtype', 'MEAN')),
    'meas.type.get': _q('MEASUrement:IMMed:TYPe?', 'Immediate measurement type read-back', 113),
    'meas.value': _q('MEASUrement:IMMed:VALue?', 'Immediate measurement value', 115),
    # waveform transfer
    'data.source': _c('DATa:SOUrce CH{ch}', 'Waveform source', 58, placeholders=_CH),
    'data.encdg': _c('WFMOutpre:ENCdg ASCii', 'ASCII waveform encoding', 172, risk='locked', description='The code parses ASCII curve data'),
    'data.width': _c('DATa:WIDth 1', 'One byte per point', 60),
    'data.start': _c('DATa:STARt {n:d}', 'First point', '58-59', placeholders={'n': Placeholder('int', 'd', 1)}),
    'data.stop': _c('DATa:STOP {n:d}', 'Last point', '59-60', placeholders={'n': Placeholder('int', 'd', 2000)}),
    'wfm.xincr': _q('WFMOutpre:XINcr?', 'Time between points', '174-175'),
    'wfm.xzero': _q('WFMOutpre:XZEro?', 'Time of the first point relative to the trigger', 175),
    'wfm.ymult': _q('WFMOutpre:YMUlt?', 'Volts per digitizing level', 176),
    'wfm.yoff': _q('WFMOutpre:YOFf?', 'Vertical position in digitizing levels', 176),
    'wfm.yzero': _q('WFMOutpre:YZEro?', 'Vertical offset (V)', 177),
    'wfm.curve': _q('CURVe?', 'Waveform data', '55-56'),
}
# Stage 7: FACtory (Default Setup, p. 73), not *RST and never *CAL?: the procedure runs the self calibration as its own point.
COMMANDS['reset'] = cmdreg.reset_cmd(True, f'{_REF}, FACtory p. 73', template='FACtory',
                                     note='FACtory (Default Setup), not *RST; the self calibration is never part of the reset')


def _last_number(reply: str) -> float:
    """The number at the end of a reply, with or without a header (':CH1:SCALE 1.0000')."""
    return float(reply.strip().replace(';', ' ').split()[-1])


def _last_word(reply: str) -> str:
    return reply.strip().replace(';', ' ').split()[-1].strip('"').upper()


class TektronixTBS1000C(SurpriseMixin, Instrument):
    MODEL = 'Tektronix TBS1000C'
    COMMANDS = COMMANDS
    IDN_MATCH = ('TBS',)
    DEFAULT_TIMEOUT = 15.0
    RESET_OPC_TIMEOUT = 60.0
    SELF_CAL_TIMEOUT = 360.0        # "can take several minutes" (p. 33)
    RECORD_POINTS = 2000            # record length set after every Default Setup (HORizontal:RECOrdlength, p. 98)
    H_DIVS = 15                     # horizontal divisions on screen (HORizontal:DIVisions? "returns 15", p. 93)
    model = ''
    channels = 2

    # ---- connection ---------------------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self.model = self.model_from_idn(self.idn)
        self.channels = 2
        return self

    @staticmethod
    def model_from_idn(idn: str) -> str:
        """'1102C' from 'TEKTRONIX,TBS1102C,C012345,CF:91.1CT FV:v1.20'; '' when the model cannot be read."""
        m = MODEL_RE.search(idn or '')
        return m.group(1).upper() if m else ''

    def cleanup(self):
        """The scope has no outputs; nothing to turn off."""

    def _reset_extra(self):
        """FACtory turns command headers on again (p. 73): put back header-less, short replies, the record length and the trigger at the
        centre, then require a clean event status register. No self calibration, no *RST."""
        return [('replies without headers (HEADer OFF)', lambda: self.send('sys.header.off')),
                ('short keywords (VERBose OFF)', lambda: self.send('sys.verbose.off')),
                ('record length and trigger position', self._horizontal_defaults),
                ('event status clean (*ESR?)', lambda: self.check_errors('reset'))]

    # ---- helpers ------------------------------------------------------------------------------------------------------------------
    def opc(self, timeout=None):
        if timeout:
            self.t.set_timeout(timeout)
        try:
            self.ask('opc.query')
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device / query error since the last check (*ESR? clears it)."""
        esr = int(_last_number(self.ask('esr.query')))
        if esr & 0b00111100:
            try:
                detail = self.ask('evmsg.query').strip()
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def set_num(self, key, value, rel=1e-3, abs_=1e-12, **vals):
        """Write a numeric setting ONCE, read it back with the registry's paired query, compare. Never retried."""
        cmd = self._registry()[key]
        name = next(n for n in cmd.placeholders if n != 'ch')
        self.send(key, **{name: value}, **vals)
        got = _last_number(self.ask(cmd.readback, **vals))
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{cmd.template.split()[0].format(**vals)}: set {value:g}, instrument reports {got:g}')
        return got

    def set_word(self, key, value, **vals):
        """Write a keyword setting ONCE, read it back, compare the first letters (VERBose OFF replies use the shortest keyword)."""
        cmd = self._registry()[key]
        name = next(n for n in cmd.placeholders if n != 'ch')
        self.send(key, **{name: value}, **vals)
        got = _last_word(self.ask(cmd.readback, **vals))
        want = value.upper()
        if not (got.startswith(want[:3]) or want.startswith(got[:3])):
            raise InstrumentError(f'{cmd.template.split()[0].format(**vals)}: set {value}, instrument reports {got}')
        return got

    def _horizontal_defaults(self):
        """Record length 2000 points, delay mode off, trigger at the centre of the record (50 %), each read back."""
        self.set_num('hor.reclen.set', self.RECORD_POINTS, rel=0, abs_=0.5)
        self.set_word('hor.delaymode.set', 'OFF')
        self.set_num('hor.pos.set', 50.0, rel=0, abs_=0.5)

    # ---- state --------------------------------------------------------------------------------------------------------------------
    def default_setup(self):
        """FACtory (p. 73), the Default Setup button; headers are turned off again, then the record length and trigger position are set."""
        self.send('reset')
        self.opc(60)
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self._horizontal_defaults()
        self.check_errors('FACtory')

    def run_self_test(self):
        """Result of the power-on diagnostics: (passed, log text). DIAg:RESUlt:FLAg? (p. 63) and DIAg:RESUlt:LOG? (p. 64)."""
        flag = _last_word(self.ask('diag.flag'))
        try:
            log = self.ask('diag.log').strip()
        except Exception:
            log = ''
        return flag == 'PASS', log

    def self_cal(self):
        """Do Self Cal: *CAL? performs it and returns 0 when no errors were found (p. 33); CALibrate:INTERNal:STATus? must then say PASS
        (p. 34). All signals must be disconnected first. Not retried (it is an action, not just a query)."""
        self.t.set_timeout(self.SELF_CAL_TIMEOUT)
        try:
            result = int(_last_number(self.ask('cal.self')))
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        status = _last_word(self.ask('cal.status'))
        return result == 0 and status == 'PASS', f'*CAL? = {result}, CALibrate:INTERNal:STATus? = {status}'

    # ---- vertical -----------------------------------------------------------------------------------------------------------------
    def select_only(self, ch):
        """Display channel ch (SELect:CH<x>, p. 139) and remove the others; the wanted channel is switched on first."""
        self.send('ch.on', ch=ch)
        for n in range(1, self.channels + 1):
            if n != ch:
                self.send('ch.off', ch=n)

    def channel(self, ch, vscale=None, position=0.0, probe=1, coupling='DC', bw_limit=False):
        """Probe 1X (gain 1), DC coupling, full bandwidth, offset 0, volts/div and position (divisions). Each read back."""
        self.set_word('ch.coupling.set', coupling, ch=ch)
        self.set_word('ch.bw.set', 'TWEnty' if bw_limit else 'FULl', ch=ch)
        self.set_num('ch.probe.set', 1.0 / float(probe), rel=1e-6, ch=ch)
        self.set_num('ch.offset.set', 0.0, abs_=1e-3, ch=ch)
        if vscale is not None:
            self.set_num('ch.scale.set', vscale, rel=1e-3, ch=ch)
        if position is not None:
            self.set_num('ch.pos.set', position, abs_=0.05, ch=ch)

    def position(self, ch, divisions):
        return self.set_num('ch.pos.set', divisions, abs_=0.05, ch=ch)

    # ---- acquisition --------------------------------------------------------------------------------------------------------------
    def acquire_mode(self, mode, averages=16):
        """SAMple or AVErage (pp. 22-23); averages 2 to 512 in powers of two (p. 24)."""
        self.set_word('acq.mode.set', mode)
        if mode.upper().startswith('AVE'):
            self.set_num('acq.numavg.set', int(averages), rel=0, abs_=0.5)
        self.send('acq.stopafter')
        self.run()

    def run(self):
        """ACQuire:STATE RUN starts acquisitions (pp. 24-25)."""
        self.send('acq.run')

    def num_acq(self):
        return int(_last_number(self.query_retry('acq.numacq')))       # read-only: retry allowed

    def wait_acquisitions(self, count, timeout=30.0, poll=0.1):
        """Start acquisitions and wait until `count` more have completed. The count is taken relative to the value read after RUN because the
        manual is not consistent about whether RUN resets ACQuire:NUMACq? (p. 23 versus the p. 25 example)."""
        self.run()
        start = self.num_acq()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.num_acq() - start >= count:
                return
            time.sleep(poll)
        raise InstrumentError(f'The oscilloscope completed fewer than {count} acquisitions in {timeout:g} s')

    # ---- horizontal ---------------------------------------------------------------------------------------------------------------
    def timebase(self, seconds_per_div):
        """HORizontal:MAIn:SCAle (p. 96)."""
        self.set_num('hor.scale.set', seconds_per_div, rel=1e-3)

    def horizontal_position(self, seconds):
        """The trigger-to-centre delay in seconds: delay mode ON (p. 94), then HORizontal:MAIn:DELay:TIMe (p. 95), read back with a 1 ns floor.
        (On this model HORizontal:MAIn:POSition is a percentage of the record, p. 93; the TDS2000C's takes seconds.)"""
        self.set_word('hor.delaymode.set', 'ON')
        self.set_num('hor.delay.set', seconds, rel=1e-6, abs_=1e-9)

    # ---- trigger ------------------------------------------------------------------------------------------------------------------
    def trigger_edge(self, source, slope='RISe', mode='AUTO', coupling='NOISErej'):
        """Edge trigger (TRIGger:A:..., pp. 146 to 159). source CH1, CH2 or AUX (the Aux In input; EXT is accepted as AUX)."""
        source = 'AUX' if source.upper() in ('EXT', 'AUX') else source
        self.send('trig.type')
        self.set_word('trig.source.set', source)
        self.set_word('trig.slope.set', slope)
        self.set_word('trig.coupling.set', coupling)
        self.trigger_mode(mode)

    def trigger_mode(self, mode):
        self.set_word('trig.mode.set', mode)

    def set_level_50(self):
        """Set To 50 %: TRIGger:A SETLevel (p. 146). The acquisition is started first."""
        self.run()
        self.send('trig.setlevel')
        self.check_errors('TRIGger:A SETLevel')

    def trigger_state(self):
        """ARMED, AUTO, READY, SAVE or TRIGGER (p. 160)."""
        return _last_word(self.query_retry('trig.state'))

    # ---- measurements -------------------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, ch):
        """Immediate measurement source and type (pp. 111 to 113): MEAN or PK2Pk."""
        self._meas_source(ch)
        self.set_word('meas.type.set', mtype)

    def _meas_source(self, ch):
        self.send('meas.source.set', ch=ch)
        got = _last_word(self.ask('meas.source.get'))
        if got != f'CH{ch}':
            raise InstrumentError(f'MEASUrement:IMMed:SOUrce1: set CH{ch}, instrument reports {got}')

    def meas_value(self):
        """MEASUrement:IMMed:VALue? (p. 115). 9.9E37 means no valid measurement."""
        v = _last_number(self.ask('meas.value'))
        if not math.isfinite(v) or abs(v) >= OVERFLOW:
            raise InstrumentError(f'The oscilloscope returned no valid measurement ({v:g}); check the channel is displayed and the signal is connected')
        return v

    def measure(self, mtype, ch, count=16, timeout=40.0):
        """Set up the measurement, let `count` acquisitions complete, read one value."""
        self.measure_setup(mtype, ch)
        self.wait_acquisitions(count, timeout=timeout)
        value = self.meas_value()
        self.check_errors(f'{mtype} measurement on CH{ch}')
        return value

    # ---- waveform record ----------------------------------------------------------------------------------------------------------
    def _curve(self):
        raw = self.ask('wfm.curve').strip()
        if raw.upper().startswith(':CURVE'):
            raw = raw[6:]
        elif raw.upper().startswith('CURVE'):
            raw = raw[5:]
        try:
            return [float(x) for x in raw.replace(';', ',').split(',') if x.strip()]
        except ValueError:
            raise InstrumentError(f'Unreadable waveform data from CURVe?: {raw[:60]!r}')

    def _transfer(self, ch, start, stop):
        self.send('data.source', ch=ch)
        self.send('data.encdg')
        self.send('data.width')
        self.send('data.start', n=start)
        self.send('data.stop', n=stop)

    def waveform(self, ch):
        """(times, volts) of the whole record. Times are relative to the trigger: t = XZEro + n * XINcr (pp. 174-175);
        volts = (dl - YOFf) * YMUlt + YZEro (pp. 176-177). ASCII, one byte per point."""
        self._transfer(ch, 1, self.RECORD_POINTS)
        xinc = _last_number(self.ask('wfm.xincr'))
        xzero = _last_number(self.ask('wfm.xzero'))
        ymult = _last_number(self.ask('wfm.ymult'))
        yoff = _last_number(self.ask('wfm.yoff'))
        yzero = _last_number(self.ask('wfm.yzero'))
        dl = self._curve()
        if len(dl) < 100 or xinc <= 0 or ymult == 0:
            raise InstrumentError(f'Waveform record not usable (points {len(dl)}, XINcr {xinc:g}, YMUlt {ymult:g})')
        times = [xzero + i * xinc for i in range(len(dl))]
        volts = [(d - yoff) * ymult + yzero for d in dl]
        self.check_errors(f'waveform CH{ch}')
        return times, volts

    def waveform_burst(self, ch, count, half_points=1000):
        """`count` successive records of CH<ch>, each only the window of 2*half_points points around the middle of the record (the trigger
        point: horizontal position 50 %, delay off). Times are relative to the window centre. Returns [(times, volts), ...]."""
        mid = self.RECORD_POINTS // 2
        half = max(60, min(mid, int(half_points)))
        start, stop = mid + 1 - half, mid + half
        self._transfer(ch, start, stop)
        xinc = _last_number(self.ask('wfm.xincr'))
        ymult = _last_number(self.ask('wfm.ymult'))
        yoff = _last_number(self.ask('wfm.yoff'))
        yzero = _last_number(self.ask('wfm.yzero'))
        if xinc <= 0 or ymult == 0:
            raise InstrumentError(f'Waveform scale not usable (XINcr {xinc:g}, YMUlt {ymult:g})')
        out = []
        for _ in range(count):
            dl = self._curve()
            if len(dl) < 2 * half * 0.9:
                raise InstrumentError(f'Waveform window not usable ({len(dl)} points, expected {2 * half})')
            out.append(([(i - half) * xinc for i in range(len(dl))], [(d - yoff) * ymult + yzero for d in dl]))
        self.check_errors(f'waveform CH{ch}')
        return out
