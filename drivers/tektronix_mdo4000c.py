"""Tektronix MDO4000C mixed-domain oscilloscope over USB (USBTMC / VISA).

Command strings follow the MDO4000/B/C Series Programmer Manual. Writes are never retried; every setting that matters is read
back and compared, and the instrument's event queue is checked after each group of settings (check_errors) so a rejected command
stops the run instead of producing a reading for the wrong setup.

The RF (spectrum) commands are the 'rf.*' keys of COMMANDS (RF below lists their texts) so they can be corrected in one place if a
firmware revision words them differently; the spectrum is read as a waveform (RF_NORMal / RF_AVErage) and analysed in software, not through marker commands.
"""
from __future__ import annotations

import math
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import SerialSettings

_REF = 'MDO4000/B/C Series Programmer Manual'
_CH = {'ch': Placeholder('str', '', '1')}                       # analog channel number as text (the caller passes str(ch))
_SLOT = {'slot': Placeholder('int', '', 1)}


def _c(template, name, description='', *, kind='set', readback=None, risk='normal', verified=True, placeholders=None, ref=_REF):
    return Cmd(template, name, description, placeholders=placeholders or {}, kind=kind, readback=readback, risk=risk, verified=verified,
               ref=ref if verified else '')


def _f(name, fmt='.9g', sample=1.0):
    return {name: Placeholder('float', fmt, sample)}


def _s(name, sample):
    return {name: Placeholder('str', '', sample)}


def _q(template, name, description='', **kw):
    return _c(template, name, description, kind='query', **kw)


_RF_NOTE = 'RF / spectrum command: NOT verified on an MDO4000C (the wording may differ by firmware)'

# Every command the driver sends. verified=True follows the module docstring (the strings are from the MDO4000/B/C Programmer Manual;
# no page is cited in the driver, so ref names the manual only); the RF / spectrum commands are NOT verified. Locked: status and
# error-queue plumbing, header / verbose / encoding (the code parses replies in that form), FACtory (reset), the self test and signal-path
# compensation (calibration), the waveform-transfer encoding. Output: the AFG output enable / disable (never overridable).
COMMANDS = {
    # bootstrap / plumbing
    'status.clear': _c('*CLS', 'Clear status', 'Clears the status registers and the event queue', risk='locked'),
    'sys.header.off': _c('HEADer OFF', 'Replies without headers', 'The code parses header-less replies', risk='locked'),
    'sys.verbose.off': _c('VERBose OFF', 'Short command headers in replies', risk='locked'),
    'opt.query': _q('*OPT?', 'Installed options', 'Identification: SA3, SA6, AFG, DVM ...', risk='locked'),
    'opc.query': _q('*OPC?', 'Operation complete', 'Waits for pending operations (error-queue / sync plumbing)', risk='locked'),
    'esr.query': _q('*ESR?', 'Event status register', 'Error-queue plumbing (check_errors)', risk='locked'),
    'evmsg.query': _q('EVMsg?', 'Event message', 'Error-queue plumbing (check_errors)', risk='locked'),
    'default.factory': _c('FACtory', 'Factory defaults', 'Resets the instrument to factory settings (never overridable)', kind='action', risk='locked'),
    # legacy raw-text helpers (set_verified / set_enum_verified called with command text rather than a registered key)
    'generic.set.num': _c('{header} {value:.9g}', 'Numeric setting (raw header)', 'Header text supplied by the caller; use a specific key to edit',
                          risk='locked', placeholders={**_s('header', 'CH1:SCAle'), **_f('value', '.9g', 0.5)}),
    'generic.set.text': _c('{header} {value}', 'Text setting (raw header)', 'Header text supplied by the caller; use a specific key to edit',
                           risk='locked', placeholders={**_s('header', 'CH1:BANdwidth'), **_s('value', 'FULl')}),
    'generic.query': _q('{query}', 'Query (raw text)', 'Query text supplied by the caller; use a specific key to edit', risk='locked',
                        placeholders=_s('query', 'CH1:SCAle?')),
    # channel selection / analog channel
    'ch.on': _c('SELect:CH{n} ON', 'Display analog channel on', placeholders={'n': Placeholder('int', '', 1)}),
    'ch.off': _c('SELect:CH{n} OFF', 'Display analog channel off', placeholders={'n': Placeholder('int', '', 1)}),
    'ch.term.set': _c('CH{ch}:TERmination {value:.9g}', 'Termination (ohm)', readback='ch.term.get', placeholders={**_CH, **_f('value', '.9g', 50.0)}),
    'ch.term.get': _q('CH{ch}:TERmination?', 'Termination read-back', placeholders=_CH),
    'ch.bw.set': _c('CH{ch}:BANdwidth {value}', 'Bandwidth (TWEnty / TWOFifty / FULl)', readback='ch.bw.get', placeholders={**_CH, **_s('value', 'FULl')}),
    'ch.bw.get': _q('CH{ch}:BANdwidth?', 'Bandwidth read-back', placeholders=_CH),
    'ch.coupling.dc': _c('CH{ch}:COUPling DC', 'Coupling DC', placeholders=_CH),
    'ch.scale.set': _c('CH{ch}:SCAle {value:.9g}', 'Vertical scale (V/div)', readback='ch.scale.get', placeholders={**_CH, **_f('value', '.9g', 0.5)}),
    'ch.scale.get': _q('CH{ch}:SCAle?', 'Vertical scale read-back', placeholders=_CH),
    'ch.pos.set': _c('CH{ch}:POSition {value:.9g}', 'Vertical position (div)', readback='ch.pos.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.pos.get': _q('CH{ch}:POSition?', 'Vertical position read-back', placeholders=_CH),
    'ch.offset.set': _c('CH{ch}:OFFSet {value:.9g}', 'Vertical offset (V)', readback='ch.offset.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.offset.get': _q('CH{ch}:OFFSet?', 'Vertical offset read-back', placeholders=_CH),
    # acquisition / horizontal / trigger
    'acq.mode': _c('ACQuire:MODe {mode}', 'Acquisition mode (SAMple / AVErage ...)', placeholders=_s('mode', 'SAMple')),
    'acq.numavg': _c('ACQuire:NUMAVg {averages}', 'Number of averages', placeholders={'averages': Placeholder('int', '', 16)}),
    'acq.stopafter': _c('ACQuire:STOPAfter RUNSTop', 'Acquire until stopped (RUN / STOP button)'),
    'acq.run': _c('ACQuire:STATE RUN', 'Acquisition run'),
    'acq.stop': _c('ACQuire:STATE STOP', 'Acquisition stop'),
    'hor.scale.set': _c('HORizontal:SCAle {value:.9g}', 'Time base (s/div)', readback='hor.scale.get', placeholders=_f('value', '.9g', 1e-3)),
    'hor.scale.get': _q('HORizontal:SCAle?', 'Time base read-back'),
    'hor.delay.on': _c('HORizontal:DELay:MODe ON', 'Horizontal delay mode on'),
    'hor.delay.time': _c('HORizontal:DELay:TIMe {seconds:.12g}', 'Horizontal delay time (s)', placeholders=_f('seconds', '.12g', 1e-3)),
    'trig.type': _c('TRIGger:A:TYPe EDGe', 'Trigger type edge'),
    'trig.source': _c('TRIGger:A:EDGE:SOUrce {source}', 'Edge trigger source (CH1 ... LINE)', placeholders=_s('source', 'CH1')),
    'trig.slope': _c('TRIGger:A:EDGE:SLOpe {slope}', 'Edge trigger slope (RISe / FALL)', placeholders=_s('slope', 'RISe')),
    'trig.mode': _c('TRIGger:A:MODe {mode}', 'Trigger mode (AUTO / NORMal)', placeholders=_s('mode', 'AUTO')),
    'trig.level': _c('TRIGger:A:LEVel {level:.9g}', 'Trigger level (V)', placeholders=_f('level', '.9g', 0.5)),
    # measurements
    'meas.state.off': _c('MEASUrement:MEAS{slot}:STATE OFF', 'Measurement slot off', placeholders=_SLOT),
    'meas.state.on': _c('MEASUrement:MEAS{slot}:STATE ON', 'Measurement slot on', placeholders=_SLOT),
    'meas.type': _c('MEASUrement:MEAS{slot}:TYPe {mtype}', 'Measurement type', placeholders={**_SLOT, **_s('mtype', 'MEAN')}),
    'meas.source1': _c('MEASUrement:MEAS{slot}:SOUrce1 {source}', 'Measurement source 1', placeholders={**_SLOT, **_s('source', 'CH1')}),
    'meas.source2': _c('MEASUrement:MEAS{slot}:SOUrce2 {source}', 'Measurement source 2', placeholders={**_SLOT, **_s('source', 'CH2')}),
    'meas.delay.edge1': _c('MEASUrement:MEAS{slot}:DELay:EDGE1 FALL', 'Delay measurement: edge 1 falling', placeholders=_SLOT),
    'meas.delay.edge2': _c('MEASUrement:MEAS{slot}:DELay:EDGE2 FALL', 'Delay measurement: edge 2 falling', placeholders=_SLOT),
    'meas.delay.direction': _c('MEASUrement:MEAS{slot}:DELay:DIRection BACKWards', 'Delay measurement: search backwards', placeholders=_SLOT),
    'meas.stat.off': _c('MEASUrement:STATIstics:MODe OFF', 'Statistics off'),
    'meas.stat.weighting': _c('MEASUrement:STATIstics:WEIghting {weighting}', 'Statistics weighting (samples)',
                              placeholders={'weighting': Placeholder('int', '', 16)}),
    'meas.stat.all': _c('MEASUrement:STATIstics:MODe ALL', 'Statistics on (all)'),
    'meas.mean': _q('MEASUrement:MEAS{slot}:MEAN?', 'Statistics mean', placeholders=_SLOT),
    'meas.stddev': _q('MEASUrement:MEAS{slot}:STDdev?', 'Statistics standard deviation', placeholders=_SLOT),
    'meas.value': _q('MEASUrement:MEAS{slot}:VALue?', 'Measurement value', placeholders=_SLOT),
    # waveform transfer
    'data.source': _c('DATa:SOUrce {source}', 'Waveform source', placeholders=_s('source', 'CH1')),
    'data.encdg': _c('DATa:ENCdg ASCIi', 'ASCII waveform encoding', 'The code parses ASCII curve data', risk='locked'),
    'data.start': _c('DATa:STARt 1', 'First point'),
    'data.stop.max': _c('DATa:STOP 1000000', 'Last point (maximum, before the record length is known)'),
    'data.stop': _c('DATa:STOP {npts}', 'Last point (record length)', placeholders={'npts': Placeholder('int', '', 1000)}),
    'wfm.nrpt': _q('WFMOutpre:NR_Pt?', 'Points in the record'),
    'wfm.xincr': _q('WFMOutpre:XINcr?', 'X increment'),
    'wfm.xzero': _q('WFMOutpre:XZEro?', 'X zero'),
    'wfm.ymult': _q('WFMOutpre:YMUlt?', 'Y multiplier'),
    'wfm.yoff': _q('WFMOutpre:YOFf?', 'Y offset'),
    'wfm.yzero': _q('WFMOutpre:YZEro?', 'Y zero'),
    'wfm.ptoff': _q('WFMOutpre:PT_Off?', 'Point offset'),
    'wfm.curve': _q('CURVe?', 'Waveform data'),
    # RF / spectrum (NOT verified)
    'rf.on': _c('SELect:RF_NORMal ON', 'RF normal trace on', _RF_NOTE, verified=False),
    'rf.avg_on': _c('SELect:RF_AVErage ON', 'RF average trace on', _RF_NOTE, verified=False),
    'rf.normal_off': _c('SELect:RF_NORMal OFF', 'RF normal trace off', _RF_NOTE, verified=False),
    'rf.center': _c('RF:FREQuency {v:.9g}', 'RF centre frequency (Hz)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', 1e9)),
    'rf.span': _c('RF:SPAN {v:.9g}', 'RF span (Hz)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', 1e6)),
    'rf.start': _c('RF:STARt {v:.9g}', 'RF start frequency (Hz)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', 9e8)),
    'rf.stop': _c('RF:STOP {v:.9g}', 'RF stop frequency (Hz)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', 1.1e9)),
    'rf.rbw_manual': _c('RF:RBW:MODe MANual', 'RF resolution bandwidth manual', _RF_NOTE, verified=False),
    'rf.rbw_auto': _c('RF:RBW:MODe AUTO', 'RF resolution bandwidth auto', _RF_NOTE, verified=False),
    'rf.rbw': _c('RF:RBW {v:.9g}', 'RF resolution bandwidth (Hz)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', 1e3)),
    'rf.rbw_q': _q('RF:RBW?', 'RF resolution bandwidth read', _RF_NOTE, verified=False),
    'rf.ref_level': _c('RF:REFLevel {v:.9g}', 'RF reference level (dBm)', _RF_NOTE, verified=False, placeholders=_f('v', '.9g', -10.0)),
    'rf.avg_count': _c('ACQuire:NUMAVg {n:d}', 'RF trace average count', _RF_NOTE, verified=False, placeholders={'n': Placeholder('int', 'd', 4)}),
    'rf.detect_avg': _c('RF:DETECTIONMethod:RF_AVErage:MODe MANual', 'RF average detection mode manual', _RF_NOTE, verified=False),
    'rf.detect_avg_set': _c('RF:DETECTIONMethod:RF_AVErage:MANual AVErage', 'RF average detection method', _RF_NOTE, verified=False),
    # AFG / DVM
    'afg.function': _c('AFG:FUNCtion {function}', 'AFG waveform', placeholders=_s('function', 'SINusoid')),
    'afg.frequency': _c('AFG:FREQuency {frequency:.9g}', 'AFG frequency (Hz)', placeholders=_f('frequency', '.9g', 1000.0)),
    'afg.amplitude': _c('AFG:AMPLitude {vpp:.9g}', 'AFG amplitude (Vpp)', placeholders=_f('vpp', '.9g', 1.0)),
    'afg.offset': _c('AFG:OFFSet {offset:.9g}', 'AFG offset (V)', placeholders=_f('offset', '.9g', 0.0)),
    'afg.load': _c('AFG:OUTPut:LOAd:IMPedance FIFty', 'AFG output load 50 ohm'),
    'afg.on': _c('AFG:OUTPut:STATe ON', 'AFG output on', 'Enables the AFG output (never overridable)', risk='output'),
    'afg.off': _c('AFG:OUTPut:STATe OFF', 'AFG output off', 'Disables the AFG output (never overridable)', risk='output'),
    'dvm.mode': _c('DVM:MODe {mode}', 'DVM mode', placeholders=_s('mode', 'DC')),
    'dvm.source': _c('DVM:SOUrce CH{ch}', 'DVM source channel', placeholders=_CH),
    'dvm.style': _c('DVM:DISplaystyle MINIMum', 'DVM display style'),
    'dvm.value': _q('DVM:MEASUrement:VALue?', 'DVM reading'),
    'dvm.freq': _q('DVM:MEASUrement:FREQuency?', 'DVM frequency reading'),
    # self test / signal-path compensation (never overridable)
    'diag.select': _c('DIAg:SELect:ALL', 'Self test: select all', risk='locked'),
    'diag.loop': _c('DIAg:LOOP:OPTion ONCE', 'Self test: run once', risk='locked'),
    'diag.run': _c('DIAg:STATE EXECute', 'Self test: execute', kind='action', risk='locked'),
    'diag.state': _q('DIAg:STATE?', 'Self test state', risk='locked'),
    'diag.flag': _q('DIAg:RESUlt:FLAg?', 'Self test result flag', risk='locked'),
    'diag.log': _q('DIAg:RESUlt:LOG?', 'Self test log', risk='locked'),
    'spc.start': _c('CALibrate:INTERNal:STARt', 'Signal path compensation: start', kind='action', risk='locked'),
    'spc.status': _q('CALibrate:INTERNal:STATus?', 'Signal path compensation status', risk='locked'),
    'spc.result': _q('CALibrate:RESults:SPC?', 'Signal path compensation result', risk='locked'),
}
COMMANDS['reset'] = _c('*RST', 'Reset to default settings', 'Returns the oscilloscope to its default setup before a run (never overridable). '
                       'Not verified: MDO4000/B/C Programmer Manual page not checked', risk='locked', verified=False)

# The spectrum-analyser commands by their old short names (rf_cmd('center', v=...) sends the registry key 'rf.center').
RF = {key[3:]: cmd.template for key, cmd in COMMANDS.items() if key.startswith('rf.')}

COUPLING_OK = ('DC',)


class TektronixMDO4000C(Instrument):
    MODEL = 'Tektronix MDO4000C'
    IDN_MATCH = ('MDO4',)
    DEFAULT_TIMEOUT = 30.0
    SERIAL = None            # USB / LAN / GPIB only
    COMMANDS = COMMANDS

    # ---- connection -------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self.idn = self.identify()
        self.model = self._model_from_idn(self.idn)
        return self

    @staticmethod
    def _model_from_idn(idn):
        for part in idn.replace(' ', '').split(','):
            if part.upper().startswith('MDO4'):
                return part.upper().replace('MDO', '')          # '4104C'
        return ''

    RESET_OPC_TIMEOUT = 60.0

    def _reset_extra(self):
        """*RST can put the reply format back: header-less / short replies are what the code parses. The AFG output is forced off."""
        return [('replies without headers (HEADer OFF)', lambda: self.send('sys.header.off')),
                ('short headers (VERBose OFF)', lambda: self.send('sys.verbose.off')),
                ('AFG output off', lambda: self.send('afg.off')),
                ('event status clean (*ESR?)', lambda: self.check_errors('reset'))]

    def installed_options(self):
        """Tokens from *OPT? (e.g. SA3, SA6, AFG, DVM) for pre-selecting the option boxes; the technician can override."""
        try:
            raw = self.ask('opt.query').upper()
        except Exception:
            return set()
        tokens = set()
        for key in ('SA3', 'SA6', 'AFG', 'DVM'):
            if key in raw:
                tokens.add(key)
        return tokens

    def opc(self, timeout=None):
        old = None
        if timeout:
            old = self.t.set_timeout(timeout)
        try:
            self.ask('opc.query')
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device error since the last check."""
        esr = int(float(self.ask('esr.query').strip()))
        if esr & 0b00111100:       # CME, EXE, DDE, QYE
            try:
                detail = self.ask('evmsg.query').strip()
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def cleanup(self):
        try:
            self.send('afg.off')
        except Exception:
            pass

    # ---- helpers ----------------------------------------------------------------------------------------------------
    def _pair(self, cmd_set, cmd_query, generic, label, vals):
        """(set key, set values, query key, query values, label) for a registered key pair or, as before, for raw command text."""
        if cmd_set in self._registry():
            return cmd_set, dict(vals), cmd_query, dict(vals), label or cmd_set
        return generic, dict(vals, header=cmd_set), 'generic.query', {'query': cmd_query}, label or cmd_set

    def set_verified(self, cmd_set, cmd_query, value, rel=1e-3, abs_=1e-9, label=None, **vals):
        """Write a numeric setting, read it back, compare. Never retried. cmd_set / cmd_query are registered keys (with `vals` for
        their placeholders and `label` for the error text) or the raw command texts."""
        set_key, svals, get_key, qvals, name = self._pair(cmd_set, cmd_query, 'generic.set.num', label, vals)
        self.send(set_key, value=value, **svals)
        got = float(self.ask(get_key, **qvals).strip().split()[-1])
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{name}: set {value:g}, instrument reports {got:g}')
        return got

    def set_enum_verified(self, cmd_set, cmd_query, value, label=None, **vals):
        set_key, svals, get_key, qvals, name = self._pair(cmd_set, cmd_query, 'generic.set.text', label, vals)
        self.send(set_key, value=value, **svals)
        got = self.ask(get_key, **qvals).strip().upper()
        if not got.startswith(value.upper()[:3]):
            raise InstrumentError(f'{name}: set {value}, instrument reports {got}')

    # ---- default state ----------------------------------------------------------------------------------------------
    def default_setup(self):
        self.send('default.factory')
        self.opc(60)
        self.send('sys.header.off')
        self.send('sys.verbose.off')

    # ---- analog channel ---------------------------------------------------------------------------------------------
    def select_only(self, ch):
        for n in (1, 2, 3, 4):
            self.send('ch.on' if n == ch else 'ch.off', n=n)

    def channel(self, ch, term=None, bw=None, vscale=None, offset=None, position=0.0):
        """Termination ('50' / '1M'), bandwidth (TWEnty / TWOFifty / FULl), scale, offset, position; each read back."""
        c = str(ch)
        if term:
            ohms = {'50': 50.0, '1M': 1.0e6}[term]
            self.set_verified('ch.term.set', 'ch.term.get', ohms, rel=1e-2, label=f'CH{ch}:TERmination', ch=c)
        if bw:
            self.set_enum_verified('ch.bw.set', 'ch.bw.get', bw, label=f'CH{ch}:BANdwidth', ch=c)
        self.send('ch.coupling.dc', ch=c)
        if vscale is not None:
            self.set_verified('ch.scale.set', 'ch.scale.get', vscale, rel=1e-3, label=f'CH{ch}:SCAle', ch=c)
        if position is not None:
            self.set_verified('ch.pos.set', 'ch.pos.get', position, abs_=1e-6, label=f'CH{ch}:POSition', ch=c)
        if offset is not None:
            self.set_verified('ch.offset.set', 'ch.offset.get', offset, rel=1e-4, abs_=1e-6, label=f'CH{ch}:OFFSet', ch=c)

    # ---- acquisition / horizontal / trigger ------------------------------------------------------------------------
    def acquire_mode(self, mode, averages=16):
        self.send('acq.mode', mode=mode)
        if mode.upper().startswith('AVE'):
            self.send('acq.numavg', averages=averages)
        self.send('acq.stopafter')
        self.send('acq.run')

    def timebase(self, seconds_per_div):
        self.set_verified('hor.scale.set', 'hor.scale.get', seconds_per_div, rel=1e-3, label='HORizontal:SCAle')

    def delay(self, seconds):
        self.send('hor.delay.on')
        self.send('hor.delay.time', seconds=seconds)

    def trigger_line(self):
        self.send('trig.type')
        self.send('trig.source', source='LINE')
        self.send('trig.mode', mode='AUTO')

    def trigger_edge(self, source, level=None, slope='RISe', mode='AUTO'):
        self.send('trig.type')
        self.send('trig.source', source=source)
        self.send('trig.slope', slope=slope)
        self.send('trig.mode', mode=mode)
        if level is not None:
            self.send('trig.level', level=level)

    # ---- measurements -------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, source, slot=1, source2=None):
        self.send('meas.state.off', slot=slot)
        self.send('meas.type', slot=slot, mtype=mtype)
        self.send('meas.source1', slot=slot, source=source)
        if source2:
            self.send('meas.source2', slot=slot, source=source2)
        self.send('meas.state.on', slot=slot)

    def stats_reset(self, weighting=None):
        self.send('meas.stat.off')
        if weighting:
            self.send('meas.stat.weighting', weighting=weighting)
        self.send('meas.stat.all')

    def _num(self, key, **vals):
        v = float(self.ask(key, **vals).strip().split()[-1])
        if not math.isfinite(v) or abs(v) > 1e36:
            raise InstrumentError(f'Invalid reading from {self._prepare(key, vals, "ask")[0]}: {v}')
        return v

    def stat_mean(self, slot=1):
        return self._num('meas.mean', slot=slot)

    def stat_stddev(self, slot=1):
        return self._num('meas.stddev', slot=slot)

    def meas_value(self, slot=1):
        return self._num('meas.value', slot=slot)

    def mean_of(self, ch, averages=16, wait=3.0):
        """Mean of a channel with N-point acquisition averaging (the manual's DC tests)."""
        self.measure_setup('MEAN', f'CH{ch}')
        self.acquire_mode('AVErage', averages)
        self.stats_reset(weighting=16)
        time.sleep(wait)
        return self.stat_mean()

    def delay_stddev(self, ch, samples=100, wait=8.0):
        """Delay (falling edge to falling edge, last occurrence) statistics: returns the standard deviation."""
        self.send('meas.state.off', slot=1)
        self.send('meas.type', slot=1, mtype='DELay')
        self.send('meas.source1', slot=1, source=f'CH{ch}')
        self.send('meas.source2', slot=1, source=f'CH{ch}')
        self.send('meas.delay.edge1', slot=1)
        self.send('meas.delay.edge2', slot=1)
        self.send('meas.delay.direction', slot=1)
        self.send('meas.state.on', slot=1)
        self.stats_reset(weighting=samples)
        time.sleep(wait)
        return self.stat_stddev()

    # ---- waveform transfer ---------------------------------------------------------------------------------------------
    def fetch(self, source):
        """(x_values, y_values) of a waveform source, scaled by WFMOutpre. ASCII encoding keeps the transport simple."""
        self.send('data.source', source=source)
        self.send('data.encdg')
        self.send('data.start')
        self.send('data.stop.max')
        npts = int(float(self.ask('wfm.nrpt').strip()))
        self.send('data.stop', npts=npts)
        xin = float(self.ask('wfm.xincr')); xz = float(self.ask('wfm.xzero'))
        ym = float(self.ask('wfm.ymult')); yo = float(self.ask('wfm.yoff')); yz = float(self.ask('wfm.yzero'))
        po = float(self.ask('wfm.ptoff'))
        raw = [float(s) for s in self.ask('wfm.curve').strip().split(',') if s.strip()]
        xs = [xz + (i - po) * xin for i in range(len(raw))]
        return xs, [yz + ym * (r - yo) for r in raw]

    def edge_time(self, ch, level=None):
        """Time (s, relative to the horizontal reference) of the first rising 50 % crossing in the acquired record."""
        self.send('acq.run')
        time.sleep(1.0)
        self.send('acq.stop')
        xs, ys = self.fetch(f'CH{ch}')
        lo, hi = min(ys), max(ys)
        mid = (lo + hi) / 2 if level is None else level
        for i in range(1, len(ys)):
            if ys[i - 1] < mid <= ys[i]:
                return xs[i - 1] + (mid - ys[i - 1]) / (ys[i] - ys[i - 1]) * (xs[i] - xs[i - 1])
        raise InstrumentError('No rising edge found in the acquired record; check the time-mark signal and trigger.')

    # ---- RF / spectrum -------------------------------------------------------------------------------------------------------
    def rf_cmd(self, key, **fmt):
        self.send('rf.' + key, **fmt)

    def rf_setup(self, center=None, span=None, start=None, stop=None, rbw=None, ref_level=None, averages=None, average_trace=True):
        """Turn on the RF channel and set the frequency window; the event queue is checked afterwards."""
        self.select_only(0)                    # all analog channels off (the RF tests use the RF input only)
        self.rf_cmd('on')
        if average_trace:
            self.rf_cmd('avg_on'); self.rf_cmd('normal_off')
        if averages:
            self.rf_cmd('avg_count', n=averages)
        if start is not None: self.rf_cmd('start', v=start)
        if stop is not None: self.rf_cmd('stop', v=stop)
        if center is not None: self.rf_cmd('center', v=center)
        if span is not None: self.rf_cmd('span', v=span)
        if ref_level is not None: self.rf_cmd('ref_level', v=ref_level)
        if rbw is not None:
            self.rf_cmd('rbw_manual'); self.rf_cmd('rbw', v=rbw)
        self.check_errors('RF setup')

    def rf_rbw(self):
        return self._num('rf.rbw_q')

    def rf_trace(self, average=True):
        """(frequencies Hz, levels dBm) of the spectrum trace currently on screen."""
        xs, ys = self.fetch('RF_AVErage' if average else 'RF_NORMal')
        return xs, ys

    def rf_settle(self, seconds):
        time.sleep(seconds)

    # ---- AFG / DVM ----------------------------------------------------------------------------------------------------------------
    def afg_set(self, function, frequency=None, vpp=None, offset=None):
        self.send('afg.function', function=function)
        if frequency is not None: self.send('afg.frequency', frequency=frequency)
        if vpp is not None: self.send('afg.amplitude', vpp=vpp)
        if offset is not None: self.send('afg.offset', offset=offset)
        self.send('afg.load')
        self.send('afg.on')
        self.check_errors('AFG setup')

    def afg_off(self):
        self.send('afg.off')

    def dvm(self, mode, ch):
        self.send('dvm.mode', mode=mode)
        self.send('dvm.source', ch=str(ch))
        self.send('dvm.style')
        self.check_errors('DVM setup')

    def dvm_value(self, settle=3.0):
        time.sleep(settle)
        return self._num('dvm.value')

    def dvm_frequency(self, settle=3.0):
        time.sleep(settle)
        return self._num('dvm.freq')

    # ---- self test / signal-path compensation ---------------------------------------------------------------------------------
    def run_diagnostics(self, timeout=900):
        """Run the full self test and return (passed, log text)."""
        self.send('diag.select')
        self.send('diag.loop')
        self.send('diag.run')
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(5)
            state = self.ask('diag.state').strip().upper()
            if not state.startswith(('EXE', 'RUN')):
                break
        flag = self.ask('diag.flag').strip().upper()
        log = self.ask('diag.log').strip()
        return flag.startswith('PASS'), log

    def run_spc(self, timeout=1200):
        """Signal path compensation; returns (passed, status)."""
        self.send('spc.start')
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(10)
            st = self.ask('spc.status').strip().upper()
            if 'RUN' not in st and 'PROG' not in st:
                break
        result = self.ask('spc.result').strip().upper()
        return result.startswith('PASS'), result
