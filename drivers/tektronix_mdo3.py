"""Tektronix 3 Series MDO (MDO32 / MDO34) mixed-domain oscilloscope over USB (USBTMC / VISA).

Every command is in COMMANDS with the page of the '3 Series MDO Oscilloscopes Programmer Manual' (077-1498-06) where its syntax and arguments
were read.  The method names are the MDO4000C driver's (drivers/tektronix_mdo4000c.py), the names the engine mdo3_verification.py (copied from
the MDO4000C engine) calls; the command texts are the 3 Series'.  Differences from the MDO4000C that matter here (all read in the manual):
  * CH<x>:BANdwidth takes {FULl|<NR3>} (p. 2-199): the 20 MHz / 250 MHz limits are sent as numbers, not TWEnty / TWOFifty
  * the edge trigger level is per channel, TRIGger:A:LEVel:CH<x> (p. 2-778); there is no TRIGger:A:LEVel
  * DIAg:SELect ALL (p. 2-261); DIAg:STATE has no query form (p. 2-262), so the self test is followed with DIAg:RESUlt:FLAg? (p. 2-260)
  * DVM:DISPLAYSTYle (p. 2-272); AFG:OUTPut:LOAd:IMPEDance must be sent before amplitude / offset (p. 2-105 note)
  * there is no AC RMS measurement type (p. 2-405): RMS and MEAN are measured in two slots and the engine computes sqrt(RMS^2 - Mean^2)
  * MEASUrement:GATing {OFF|SCREen|CURSor} (p. 2-388): OFF, not NONE
  * the delta-time test uses the BURst (burst width) measurement statistics (PV manual p. 105; type BURst p. 2-406)
  * the DVM frequency test reads the trigger frequency counter: DISplay:TRIGFrequency (p. 2-270), TRIGger:FREQuency? (p. 2-822)
Writes are never retried.  Channel, time base, AFG, DVM and RF reference-level / RBW settings are read back and compared; the event status
register is checked after each group of settings so a rejected command stops the run.  The RF start / stop / centre / span are coupled by the
instrument (p. 2-514 note) and are not read back one by one.

UNVERIFIED (not stated in the manual; to confirm on a real MDO32 / MDO34): the *IDN? reply form 'TEKTRONIX,MDO34,<serial>,CF:91.1CT FV:<fw>'
(only the ID? form 'TEK/MDO34-3' and a DPO *IDN? example are printed, p. 2-319); the *OPT? option codes for 3-SA3 / 3-AFG / 3-DVM (p. 2-430 prints
'SA:Spectrum analyzer maximum input frequency', 'AFG:...', 'DVM:...'); the CH<x>:BANdwidth? reply after FULl (assumed a number at or above the
model bandwidth); whether the RF commands are accepted without 3-SA3 (the manual marks them 'requires option 3-SA3' although the 1 GHz analyzer is
standard, PV manual p. 11); the reply of TRIGger:FREQuency? while the counter settles (NaN = 99.10E+36 is handled).
"""
from __future__ import annotations

import math
import re
import time

from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError

_REF = '3 Series MDO Programmer Manual 077-1498-06'
_CH = {'ch': Placeholder('str', '', '1')}
_N = {'n': Placeholder('int', '', 1)}
_SLOT = {'slot': Placeholder('int', '', 1)}


def _c(template, name, page, description='', *, kind='set', readback=None, risk='normal', verified=True, placeholders=None):
    return Cmd(template, name, description, placeholders=placeholders or {}, kind=kind, readback=readback, risk=risk, verified=verified,
               ref=f'{_REF} p. {page}' if verified else '')


def _q(template, name, page, description='', **kw):
    return _c(template, name, page, description, kind='query', **kw)


def _f(name, fmt='.9g', sample=1.0):
    return {name: Placeholder('float', fmt, sample)}


def _s(name, sample):
    return {name: Placeholder('str', '', sample)}


# Locked: status / error-queue plumbing, header / verbose / encoding (the code parses replies in that form), FACtory and *RST (reset), the self test
# and signal path compensation.  Output: the AFG output enable / disable (never overridable).
COMMANDS = {
    # bootstrap / plumbing
    'status.clear': _c('*CLS', 'Clear status', '2-214', 'Clears the event queue and the status registers', risk='locked'),
    'sys.header.off': _c('HEADer OFF', 'Replies without headers', '2-313', 'The code parses header-less replies', risk='locked'),
    'sys.verbose.off': _c('VERBose OFF', 'Short keywords in replies', '2-826', risk='locked'),
    'opt.query': _q('*OPT?', 'Installed options', '2-429 / 2-430', '<code>:<description>,...', risk='locked'),
    'opc.query': _q('*OPC?', 'Operation complete', '2-429', risk='locked'),
    'esr.query': _q('*ESR?', 'Event status register', '2-282', 'Error-queue plumbing (check_errors)', risk='locked'),
    'evmsg.query': _q('EVMsg?', 'Event message', '2-291', 'Error-queue plumbing (check_errors)', risk='locked'),
    'default.factory': _c('FACtory', 'Factory default settings (Default Setup)', '2-292 / 2-293', kind='action', risk='locked'),
    'reset': _c('*RST', 'Reset to default settings', '2-550', 'Returns the oscilloscope to its factory default settings before a run (never overridable)',
                risk='locked'),
    # analog channels
    'ch.on': _c('SELect:CH{n} ON', 'Display analog channel on', '2-679', placeholders=_N),
    'ch.off': _c('SELect:CH{n} OFF', 'Display analog channel off', '2-679', placeholders=_N),
    'ch.term.set': _c('CH{ch}:TERmination {value:.9g}', 'Termination (ohm)', '2-212', readback='ch.term.get', placeholders={**_CH, **_f('value', '.9g', 50.0)}),
    'ch.term.get': _q('CH{ch}:TERmination?', 'Termination read-back', '2-212', placeholders=_CH),
    'ch.bw.set': _c('CH{ch}:BANdwidth {value}', 'Bandwidth limit (FULl or a number in Hz)', '2-199', readback='ch.bw.get', placeholders={**_CH, **_s('value', 'FULl')}),
    'ch.bw.get': _q('CH{ch}:BANdwidth?', 'Bandwidth limit read-back', '2-199', placeholders=_CH),
    'ch.coupling.dc': _c('CH{ch}:COUPling DC', 'Coupling DC', '2-199', placeholders=_CH),
    'ch.scale.set': _c('CH{ch}:SCAle {value:.9g}', 'Vertical scale (V/div)', '2-211 / 2-212', readback='ch.scale.get', placeholders={**_CH, **_f('value', '.9g', 0.5)}),
    'ch.scale.get': _q('CH{ch}:SCAle?', 'Vertical scale read-back', '2-212', placeholders=_CH),
    'ch.pos.set': _c('CH{ch}:POSition {value:.9g}', 'Vertical position (div)', '2-202', readback='ch.pos.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.pos.get': _q('CH{ch}:POSition?', 'Vertical position read-back', '2-202 / 2-203', placeholders=_CH),
    'ch.offset.set': _c('CH{ch}:OFFSet {value:.9g}', 'Vertical offset (V)', '2-201 / 2-202', readback='ch.offset.get', placeholders={**_CH, **_f('value', '.9g', 0.0)}),
    'ch.offset.get': _q('CH{ch}:OFFSet?', 'Vertical offset read-back', '2-202', placeholders=_CH),
    # acquisition / horizontal / trigger
    'acq.mode': _c('ACQuire:MODe {mode}', 'Acquisition mode (SAMple / AVErage ...)', '2-100', placeholders=_s('mode', 'SAMple')),
    'acq.numavg': _c('ACQuire:NUMAVg {averages}', 'Number of averages (2 - 512, powers of two)', '2-101', placeholders={'averages': Placeholder('int', '', 16)}),
    'acq.stopafter': _c('ACQuire:STOPAfter RUNSTop', 'Acquire continuously', '2-104'),
    'acq.run': _c('ACQuire:STATE RUN', 'Acquisition run', '2-103 / 2-104'),
    'acq.stop': _c('ACQuire:STATE STOP', 'Acquisition stop', '2-103 / 2-104'),
    'hor.scale.set': _c('HORizontal:SCAle {value:.9g}', 'Time base (s/div)', '2-318', readback='hor.scale.get', placeholders=_f('value', '.9g', 1e-3)),
    'hor.scale.get': _q('HORizontal:SCAle?', 'Time base read-back', '2-318'),
    'hor.delay.on': _c('HORizontal:DELay:MODe ON', 'Horizontal delay mode on', '2-314'),
    'hor.delay.time': _c('HORizontal:DELay:TIMe {seconds:.12g}', 'Horizontal delay time (s)', '2-314 / 2-315', placeholders=_f('seconds', '.12g', 1e-3)),
    'trig.type': _c('TRIGger:A:TYPe EDGe', 'Trigger type edge', '2-808'),
    'trig.source': _c('TRIGger:A:EDGE:SOUrce {source}', 'Edge trigger source (CH<x> / LINE)', '2-776 / 2-777', placeholders=_s('source', 'CH1')),
    'trig.slope': _c('TRIGger:A:EDGE:SLOpe {slope}', 'Edge trigger slope (RISe / FALL)', '2-775 / 2-776', placeholders=_s('slope', 'RISe')),
    'trig.mode': _c('TRIGger:A:MODe {mode}', 'Trigger mode (AUTO / NORMal)', '2-789', placeholders=_s('mode', 'AUTO')),
    'trig.level': _c('TRIGger:A:LEVel:CH{n} {level:.9g}', 'Edge trigger level of an analog channel (V)', '2-778', placeholders={**_N, **_f('level', '.9g', 0.0)}),
    'disp.trigfreq.on': _c('DISplay:TRIGFrequency ON', 'Trigger frequency counter readout on', '2-269 / 2-270', readback='disp.trigfreq.get'),
    'disp.trigfreq.get': _q('DISplay:TRIGFrequency?', 'Trigger frequency counter readout state', '2-270'),
    'trig.freq': _q('TRIGger:FREQuency?', 'Trigger frequency (Hz); 99.10E+36 when not available', '2-822'),
    # measurements
    'meas.state.off': _c('MEASUrement:MEAS{slot}:STATE OFF', 'Measurement slot off', '2-404 / 2-405', placeholders=_SLOT),
    'meas.state.on': _c('MEASUrement:MEAS{slot}:STATE ON', 'Measurement slot on', '2-404 / 2-405', placeholders=_SLOT),
    'meas.type': _c('MEASUrement:MEAS{slot}:TYPe {mtype}', 'Measurement type (MEAN / PK2Pk / RMS / HIGH / LOW / BURst)', '2-405 - 2-408',
                    placeholders={**_SLOT, **_s('mtype', 'MEAN')}),
    'meas.source1': _c('MEASUrement:MEAS{slot}:SOUrce1 {source}', 'Measurement source 1', '2-403 / 2-404', placeholders={**_SLOT, **_s('source', 'CH1')}),
    'meas.gating.off': _c('MEASUrement:GATing OFF', 'Measurement gating off (full record)', '2-388'),
    'meas.stat.off': _c('MEASUrement:STATIstics:MODe OFF', 'Statistics off', '2-418'),
    'meas.stat.weighting': _c('MEASUrement:STATIstics:WEIghting {weighting}', 'Statistics weighting (samples)', '2-418',
                              placeholders={'weighting': Placeholder('int', '', 16)}),
    'meas.stat.all': _c('MEASUrement:STATIstics:MODe ALL', 'Statistics on (all)', '2-418'),
    'meas.mean': _q('MEASUrement:MEAS{slot}:MEAN?', 'Statistics mean', '2-403', placeholders=_SLOT),
    'meas.stddev': _q('MEASUrement:MEAS{slot}:STDdev?', 'Statistics standard deviation', '2-405', placeholders=_SLOT),
    'meas.value': _q('MEASUrement:MEAS{slot}:VALue?', 'Measurement value', '2-411', placeholders=_SLOT),
    # waveform transfer
    'data.source': _c('DATa:SOUrce {source}', 'Waveform source (CH<x> / RF_NORMal / RF_AVErage)', '2-252 / 2-253', placeholders=_s('source', 'CH1')),
    'data.encdg': _c('DATa:ENCdg ASCIi', 'ASCII waveform encoding', '2-250', 'The code parses ASCII curve data', risk='locked'),
    'data.start': _c('DATa:STARt 1', 'First point', '2-253 / 2-254'),
    'data.stop.max': _c('DATa:STOP 1000000', 'Last point (large, before the record length is known)', '2-254'),
    'data.stop': _c('DATa:STOP {npts}', 'Last point (record length)', '2-254', placeholders={'npts': Placeholder('int', '', 1000)}),
    'wfm.nrpt': _q('WFMOutpre:NR_Pt?', 'Points in the record', '2-856'),
    'wfm.xincr': _q('WFMOutpre:XINcr?', 'X increment', '2-861'),
    'wfm.xzero': _q('WFMOutpre:XZEro?', 'X zero', '2-862'),
    'wfm.ymult': _q('WFMOutpre:YMUlt?', 'Y multiplier', '2-862 / 2-863'),
    'wfm.yoff': _q('WFMOutpre:YOFf?', 'Y offset', '2-863'),
    'wfm.yzero': _q('WFMOutpre:YZEro?', 'Y zero', '2-864'),
    'wfm.ptoff': _q('WFMOutpre:PT_Off?', 'Point offset (always 0)', '2-857'),
    'wfm.curve': _q('CURVe?', 'Waveform data', '2-245'),
    # RF / spectrum (the manual marks these 'requires option 3-SA3'; see the module notes)
    'rf.on': _c('SELect:RF_NORMal ON', 'RF normal trace on', '2-684'),
    'rf.avg_on': _c('SELect:RF_AVErage ON', 'RF average trace on', '2-682 / 2-683'),
    'rf.normal_off': _c('SELect:RF_NORMal OFF', 'RF normal trace off', '2-684'),
    'rf.center': _c('RF:FREQuency {v:.9g}', 'RF centre frequency (Hz)', '2-514', placeholders=_f('v', '.9g', 1e9)),
    'rf.span': _c('RF:SPAN {v:.9g}', 'RF span (Hz)', '2-540 / 2-541', placeholders=_f('v', '.9g', 1e6)),
    'rf.start': _c('RF:STARt {v:.9g}', 'RF start frequency (Hz)', '2-545 / 2-546', placeholders=_f('v', '.9g', 9e8)),
    'rf.stop': _c('RF:STOP {v:.9g}', 'RF stop frequency (Hz)', '2-546 / 2-547', placeholders=_f('v', '.9g', 1.1e9)),
    'rf.rbw_manual': _c('RF:RBW:MODe MANual', 'RF resolution bandwidth manual', '2-536'),
    'rf.rbw': _c('RF:RBW {v:.9g}', 'RF resolution bandwidth (Hz)', '2-535 / 2-536', readback='rf.rbw_q', placeholders=_f('v', '.9g', 1e3)),
    'rf.rbw_q': _q('RF:RBW?', 'RF resolution bandwidth read', '2-535'),
    'rf.ref_level': _c('RF:REFLevel {v:.9g}', 'RF reference level (dBm)', '2-536 / 2-537', readback='rf.ref_level_q', placeholders=_f('v', '.9g', -10.0)),
    'rf.ref_level_q': _q('RF:REFLevel?', 'RF reference level read', '2-537'),
    'rf.avg_count': _c('RF:RF_AVErage:NUMAVg {n:d}', 'RF average trace count', '2-539', placeholders={'n': Placeholder('int', 'd', 16)}),
    'rf.detect_manual': _c('RF:DETECTionmethod:MODe MANual', 'RF detection method manual', '2-509 / 2-510'),
    'rf.detect_avg': _c('RF:DETECTionmethod:RF_AVErage {method}', 'RF average-trace detection method (AVErage ...)', '2-510',
                        placeholders=_s('method', 'AVErage')),
    # AFG (option 3-AFG)
    'afg.load': _c('AFG:OUTPut:LOAd:IMPEDance FIFty', 'AFG output load 50 ohm (before amplitude / offset)', '2-119 / 2-120', readback='afg.load_q'),
    'afg.load_q': _q('AFG:OUTPut:LOAd:IMPEDance?', 'AFG output load read', '2-119'),
    'afg.function': _c('AFG:FUNCtion {function}', 'AFG waveform (SINE / SQUare / DC ...)', '2-112 / 2-113', readback='afg.function_q',
                       placeholders=_s('function', 'SINE')),
    'afg.function_q': _q('AFG:FUNCtion?', 'AFG waveform read', '2-112'),
    'afg.frequency': _c('AFG:FREQuency {frequency:.9g}', 'AFG frequency (Hz)', '2-111 / 2-112', readback='afg.frequency_q', placeholders=_f('frequency', '.9g', 1000.0)),
    'afg.frequency_q': _q('AFG:FREQuency?', 'AFG frequency read', '2-112'),
    'afg.amplitude': _c('AFG:AMPLitude {vpp:.9g}', 'AFG amplitude (V p-p)', '2-104 / 2-105', readback='afg.amplitude_q', placeholders=_f('vpp', '.9g', 1.0)),
    'afg.amplitude_q': _q('AFG:AMPLitude?', 'AFG amplitude read', '2-105'),
    'afg.offset': _c('AFG:OFFSet {offset:.9g}', 'AFG offset / DC level (V)', '2-118 / 2-119', readback='afg.offset_q', placeholders=_f('offset', '.9g', 0.0)),
    'afg.offset_q': _q('AFG:OFFSet?', 'AFG offset read', '2-119'),
    'afg.on': _c('AFG:OUTPut:STATE ON', 'AFG output on', '2-120', 'Enables the AFG output (never overridable)', risk='output'),
    'afg.off': _c('AFG:OUTPut:STATE OFF', 'AFG output off', '2-120', 'Disables the AFG output (never overridable)', risk='output'),
    # DVM (option 3-DVM)
    'dvm.mode': _c('DVM:MODe {mode}', 'DVM mode (ACRMS / DC / FREQuency)', '2-275 / 2-276', readback='dvm.mode_q', placeholders=_s('mode', 'DC')),
    'dvm.mode_q': _q('DVM:MODe?', 'DVM mode read', '2-276'),
    'dvm.source': _c('DVM:SOUrce CH{ch}', 'DVM source channel', '2-276', readback='dvm.source_q', placeholders=_CH),
    'dvm.source_q': _q('DVM:SOUrce?', 'DVM source read', '2-276'),
    'dvm.style': _c('DVM:DISPLAYSTYle MINimum', 'DVM display style minimum', '2-272'),
    'dvm.value': _q('DVM:MEASUrement:VALue?', 'DVM reading', '2-275'),
    # self test / signal path compensation (never overridable)
    'diag.select': _c('DIAg:SELect ALL', 'Self test: all groups', '2-261 / 2-262', risk='locked'),
    'diag.loop': _c('DIAg:LOOP:OPTion ONCE', 'Self test: run once', '2-259', risk='locked'),
    'diag.run': _c('DIAg:STATE EXECute', 'Self test: execute', '2-262 / 2-263', kind='action', risk='locked'),
    'diag.flag': _q('DIAg:RESUlt:FLAg?', 'Self test result (PASS / FAIL / IN PROGRESS / NOT RUN)', '2-260', risk='locked'),
    'diag.log': _q('DIAg:RESUlt:LOG?', 'Self test log', '2-261', risk='locked'),
    'spc.start': _c('CALibrate:INTERNal:STARt', 'Signal path compensation: start', '2-190', kind='action', risk='locked'),
    'spc.status': _q('CALibrate:INTERNal:STATus?', 'Signal path compensation status (INIT / PASS / FAIL / RUNNING)', '2-191', risk='locked'),
    'spc.result': _q('CALibrate:RESults:SPC?', 'Signal path compensation result', '2-194 / 2-195', risk='locked'),
}

RF = {key[3:]: cmd.template for key, cmd in COMMANDS.items() if key.startswith('rf.')}
BW_HZ = {'TWEnty': 20e6, 'TWOFifty': 250e6}             # the engine's bandwidth names (MDO4000C enums) as the 3 Series numbers (p. 2-199)
NAN_LIMIT = 9.0e36                                       # 99.10E+36 = 'not available' (p. 2-822)


class TektronixMDO3(Instrument):
    MODEL = 'Tektronix 3 Series MDO'
    IDN_MATCH = ('MDO3',)
    DEFAULT_TIMEOUT = 30.0
    SERIAL = None
    COMMANDS = COMMANDS
    RESET_OPC_TIMEOUT = 60.0
    full_bw_hz = None              # the model's bandwidth (Hz), set by the engine from the chosen model: the FULl read-back is checked against it
    model = ''
    channels = 4
    _opts = None
    _afg_used = False

    # ---- connection -------------------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.model = self._model_from_idn(self.idn)
        if not re.fullmatch(r'3[24]', self.model):
            self.close()
            raise InstrumentError(f'Expected a 3 Series MDO (MDO32 / MDO34) but the instrument identifies as: {self.idn!r}')
        self.channels = int(self.model[1])
        self.send('status.clear')
        self.send('sys.header.off')
        self.send('sys.verbose.off')
        self._opts = None
        self._afg_used = False
        return self

    @staticmethod
    def _model_from_idn(idn):
        for part in idn.replace(' ', '').split(','):
            m = re.fullmatch(r'MDO(3[24])', part.upper())
            if m:
                return m.group(1)          # '34'
        return ''

    def _reset_extra(self):
        steps = [('replies without headers (HEADer OFF)', lambda: self.send('sys.header.off')),
                 ('short keywords (VERBose OFF)', lambda: self.send('sys.verbose.off'))]
        if 'AFG' in self.installed_options():
            steps.append(('AFG output off', lambda: self.send('afg.off')))
        steps.append(('event status clean (*ESR?)', lambda: self.check_errors('reset')))
        return steps

    def installed_options(self):
        """Tokens from *OPT? (SA3, AFG, DVM, MSO) for pre-selecting the option boxes; the technician confirms them against the label.
        The reply is '<code>:<description>,...' (p. 2-430); a bare 'SA' code is NOT taken as 3-SA3 (UNVERIFIED code form)."""
        if self._opts is not None:
            return set(self._opts)
        try:
            raw = self.ask('opt.query').upper()
        except Exception:
            return set()
        codes = [part.split(':', 1)[0].strip().strip('"') for part in raw.split(',')]
        tokens = set()
        for code in codes:
            c = code.replace('3-', '')
            if c in ('SA3', 'AFG', 'DVM', 'MSO'):
                tokens.add(c)
        self._opts = set(tokens)
        return tokens

    def opc(self, timeout=None):
        if timeout:
            self.t.set_timeout(timeout)
        try:
            self.ask('opc.query')
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device / query error since the last check."""
        esr = int(float(self.ask('esr.query').strip()))
        if esr & 0b00111100:
            try:
                detail = self.ask('evmsg.query').strip()
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def cleanup(self):
        try:
            self.afg_off()
        except Exception:
            pass

    # ---- set, read back, compare (never retried) -------------------------------------------------------------------------------
    def _number(self, key, **vals):
        v = float(self.ask(key, **vals).strip().split()[-1])
        if not math.isfinite(v) or abs(v) > NAN_LIMIT:
            raise InstrumentError(f'Invalid reading from {self._prepare(key, vals, "ask")[0]}: {v}')
        return v

    def set_verified(self, set_key, get_key, value, rel=1e-3, abs_=1e-9, label=None, **vals):
        """Registered key pair only ('value' placeholder): write, read back, compare.  Never retried."""
        self.send(set_key, value=value, **vals)
        got = float(self.ask(get_key, **vals).strip().split()[-1])
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{label or set_key}: set {value:g}, instrument reports {got:g}')
        return got

    def _set_number(self, set_key, get_key, field, value, rel=1e-3, abs_=1e-9, label=None):
        self.send(set_key, **{field: value})
        got = float(self.ask(get_key).strip().split()[-1])
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{label or set_key}: set {value:g}, instrument reports {got:g}')
        return got

    def _set_text(self, set_key, get_key, label, expect, **vals):
        self.send(set_key, **vals)
        got = self.ask(get_key).strip().strip('"').upper()
        if not got.startswith(expect.upper()[:3]):
            raise InstrumentError(f'{label}: set {expect}, instrument reports {got}')
        return got

    # ---- default state ----------------------------------------------------------------------------------------------------------
    def default_setup(self):
        self.send('default.factory')
        self.opc(60)
        self.send('sys.header.off')
        self.send('sys.verbose.off')

    # ---- analog channel ---------------------------------------------------------------------------------------------------------
    def select_only(self, ch):
        for n in range(1, getattr(self, 'channels', 4) + 1):
            self.send('ch.on' if n == ch else 'ch.off', n=n)

    def bandwidth(self, ch, bw):
        """bw: 'TWEnty' / 'TWOFifty' (sent as 20E6 / 250E6, read back as numbers) or 'FULl' (read back: a number at or above the model bandwidth)."""
        c = str(ch)
        if bw.upper().startswith('FUL'):
            self.send('ch.bw.set', ch=c, value='FULl')
            reply = self.ask('ch.bw.get', ch=c).strip().upper()
            if reply.startswith('FUL'):
                return reply
            got = float(reply.split()[-1])
            if self.full_bw_hz:
                ok = got >= 0.99 * self.full_bw_hz
            else:                                   # model bandwidth unknown: anything but a bandwidth-limit filter value
                ok = not any(math.isclose(got, v, rel_tol=1e-2) for v in BW_HZ.values()) and got > 30e6
            if not ok:
                raise InstrumentError(f'CH{ch}:BANdwidth: set FULl, instrument reports {got:g}')
            return got
        hz = BW_HZ[bw]
        self.send('ch.bw.set', ch=c, value=f'{hz:.6E}')
        got = float(self.ask('ch.bw.get', ch=c).strip().split()[-1])
        if not math.isclose(got, hz, rel_tol=1e-3):
            raise InstrumentError(f'CH{ch}:BANdwidth: set {hz:g}, instrument reports {got:g}')
        return got

    def channel(self, ch, term=None, bw=None, vscale=None, offset=None, position=0.0):
        """Termination ('50' / '1M'), bandwidth (TWEnty / TWOFifty / FULl), scale, offset, position; each read back."""
        c = str(ch)
        if term:
            ohms = {'50': 50.0, '1M': 1.0e6}[term]
            self.set_verified('ch.term.set', 'ch.term.get', ohms, rel=1e-2, label=f'CH{ch}:TERmination', ch=c)
        if bw:
            self.bandwidth(ch, bw)
        self.send('ch.coupling.dc', ch=c)
        if vscale is not None:
            self.set_verified('ch.scale.set', 'ch.scale.get', vscale, rel=1e-3, label=f'CH{ch}:SCAle', ch=c)
        if position is not None:
            self.set_verified('ch.pos.set', 'ch.pos.get', position, abs_=1e-6, label=f'CH{ch}:POSition', ch=c)
        if offset is not None:
            self.set_verified('ch.offset.set', 'ch.offset.get', offset, rel=1e-4, abs_=1e-6, label=f'CH{ch}:OFFSet', ch=c)

    # ---- acquisition / horizontal / trigger -----------------------------------------------------------------------------------------
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
            m = re.fullmatch(r'CH(\d)', source.upper())
            if not m:
                raise InstrumentError(f'Trigger level: only an analog channel source has a level here, not {source!r}')
            self.send('trig.level', n=int(m.group(1)), level=level)

    def trigger_counter_on(self):
        """The trigger frequency readout (PV manual p. 130 step 11): on, and read back."""
        self.send('disp.trigfreq.on')
        st = self.ask('disp.trigfreq.get').strip().upper()
        if st not in ('1', 'ON'):
            raise InstrumentError(f'DISplay:TRIGFrequency: set ON, instrument reports {st}')

    def trigger_frequency(self, settle=3.0):
        time.sleep(settle)
        return self._number('trig.freq')

    # ---- measurements ------------------------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, source, slot=1, source2=None):
        if source2:
            raise InstrumentError('two-source measurements are not used with the 3 Series MDO')
        self.send('meas.state.off', slot=slot)
        self.send('meas.type', slot=slot, mtype=mtype)
        self.send('meas.source1', slot=slot, source=source)
        self.send('meas.state.on', slot=slot)

    def gating_off(self):
        self.send('meas.gating.off')

    def stats_reset(self, weighting=None):
        self.send('meas.stat.off')
        if weighting:
            self.send('meas.stat.weighting', weighting=weighting)
        self.send('meas.stat.all')

    def stat_mean(self, slot=1):
        return self._number('meas.mean', slot=slot)

    def stat_stddev(self, slot=1):
        return self._number('meas.stddev', slot=slot)

    def meas_value(self, slot=1):
        return self._number('meas.value', slot=slot)

    def mean_of(self, ch, averages=16, wait=3.0):
        """Mean of a channel with N-waveform averaging (the DC tests, PV manual pp. 92, 97, 101)."""
        self.measure_setup('MEAN', f'CH{ch}')
        self.acquire_mode('AVErage', averages)
        self.stats_reset(weighting=16)
        time.sleep(wait)
        return self.stat_mean()

    def delay_stddev(self, ch, samples=100, wait=8.0):
        """Delta-time accuracy (PV manual pp. 105-106): standard deviation of the Burst Width measurement statistics (type BURst, p. 2-406)."""
        self.measure_setup('BURst', f'CH{ch}')
        self.stats_reset(weighting=samples)
        time.sleep(wait)
        return self.stat_stddev()

    # ---- waveform transfer ------------------------------------------------------------------------------------------------------------
    def fetch(self, source):
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
        """Time (s, from the horizontal reference) of the first rising 50 % crossing in the acquired record."""
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

    # ---- RF / spectrum ------------------------------------------------------------------------------------------------------------------
    def rf_cmd(self, key, **fmt):
        self.send('rf.' + key, **fmt)

    def rf_setup(self, center=None, span=None, start=None, stop=None, rbw=None, ref_level=None, averages=None, average_trace=True, detection=None):
        """RF channel on and the frequency window; average trace (and average detection when `detection` is given, PV manual p. 110);
        reference level and a manual RBW are read back; the event queue is checked afterwards."""
        self.select_only(0)                    # all analog channels off: the RF tests use the RF input only
        self.rf_cmd('on')
        if average_trace:
            self.rf_cmd('avg_on'); self.rf_cmd('normal_off')
        if detection:
            self.rf_cmd('detect_manual'); self.rf_cmd('detect_avg', method=detection)
        if averages:
            self.rf_cmd('avg_count', n=averages)
        if start is not None: self.rf_cmd('start', v=start)
        if stop is not None: self.rf_cmd('stop', v=stop)
        if center is not None: self.rf_cmd('center', v=center)
        if span is not None: self.rf_cmd('span', v=span)
        if ref_level is not None:
            self._set_number('rf.ref_level', 'rf.ref_level_q', 'v', ref_level, rel=0, abs_=0.05, label='RF:REFLevel')
        if rbw is not None:
            self.rf_cmd('rbw_manual')
            self._set_number('rf.rbw', 'rf.rbw_q', 'v', rbw, rel=1e-2, label='RF:RBW')
        self.check_errors('RF setup')

    def rf_rbw(self):
        return self._number('rf.rbw_q')

    def rf_trace(self, average=True):
        return self.fetch('RF_AVErage' if average else 'RF_NORMal')

    # ---- AFG / DVM ---------------------------------------------------------------------------------------------------------------------------
    def afg_set(self, function, frequency=None, vpp=None, offset=None):
        """Load impedance first (p. 2-105 note), then waveform, frequency, amplitude, offset - each read back - then the output on."""
        self._afg_used = True
        self._set_text('afg.load', 'afg.load_q', 'AFG:OUTPut:LOAd:IMPEDance', 'FIFty')
        self._set_text('afg.function', 'afg.function_q', 'AFG:FUNCtion', function, function=function)
        if frequency is not None:
            self._set_number('afg.frequency', 'afg.frequency_q', 'frequency', frequency, rel=1e-6, label='AFG:FREQuency')
        if vpp is not None:
            self._set_number('afg.amplitude', 'afg.amplitude_q', 'vpp', vpp, rel=1e-3, abs_=5e-4, label='AFG:AMPLitude')
        if offset is not None:
            self._set_number('afg.offset', 'afg.offset_q', 'offset', offset, rel=1e-3, abs_=5e-4, label='AFG:OFFSet')
        self.send('afg.on')
        self.check_errors('AFG setup')

    def afg_off(self):
        """AFG output off - only on an instrument that has the AFG (option 3-AFG) or once the AFG was used this session, so a scope without
        the option does not collect a command error after every point."""
        if self._afg_used or 'AFG' in self.installed_options():
            self.send('afg.off')

    def dvm(self, mode, ch):
        """DVM mode and source, read back.  The PV manual (pp. 128, 129) switches the DVM source to another channel and back before reading."""
        mode_name = {'FREQuency': 'FREQuency', 'ACRMS': 'ACRMS', 'DC': 'DC'}[mode]
        self._set_text('dvm.mode', 'dvm.mode_q', 'DVM:MODe', mode_name, mode=mode_name)
        other = 2 if int(ch) == 1 else 1
        self.send('dvm.source', ch=str(other))
        self._set_text('dvm.source', 'dvm.source_q', 'DVM:SOUrce', f'CH{ch}', ch=str(ch))
        self.send('dvm.style')
        self.check_errors('DVM setup')

    def dvm_value(self, settle=3.0):
        time.sleep(settle)
        return self._number('dvm.value')

    # ---- self test / signal path compensation ---------------------------------------------------------------------------------------------
    def run_diagnostics(self, timeout=900):
        """All self-test groups once; DIAg:STATE has no query form here, so the result flag is polled until it is no longer IN PROGRESS."""
        self.send('diag.select')
        self.send('diag.loop')
        self.send('diag.run')
        t0 = time.time()
        flag = ''
        while time.time() - t0 < timeout:
            time.sleep(5)
            flag = self.ask('diag.flag').strip().strip('"').upper()
            if 'PROGRESS' not in flag:
                break
        log = self.ask('diag.log').strip()
        return flag.startswith('PASS'), log

    def run_spc(self, timeout=1200):
        """Signal path compensation; returns (passed, result)."""
        self.send('spc.start')
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(10)
            st = self.ask('spc.status').strip().upper()
            if 'RUN' not in st:
                break
        result = self.ask('spc.result').strip().upper()
        return result.startswith('PASS'), result
