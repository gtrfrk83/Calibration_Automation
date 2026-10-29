"""Keysight 53210A / 53220A / 53230A universal frequency counter / timer (unit under test) over USB, LAN or GPIB (option 400), SCPI.

Commands come from the Keysight 53220A/53230A Programmer's Reference (PR, 518 pp.; page = PDF page = printed page).  That reference covers the 53220A and the 53230A ONLY:
the 53210A is the subclass Keysight53210A whose registry is the same text with every `verified` flag cleared (its microwave input is Channel 2, Service Guide p. 67),
so every 53210A command is listed as UNVERIFIED in the procedure's report.  Nothing here uses a CAL: command: the performance verification never adjusts the counter.

Facts the driver is written around (each from the Programmer's Reference):
  * CONFigure resets the trigger, sample count, gate, auto-level and level, but NOT the input coupling, impedance, range, low-pass filter, noise rejection or probe (pp. 117,
    204-222).  So the inputs are set first, then CONFigure, then level / slope / gate / trigger / sample count.
  * INITiate clears the readings and the statistics (p. 22, 69); CALC:AVER:STAT ON clears them too (p. 76).  So the sequence is statistics On, TRIG:SOUR BUS, INIT, *TRG, *OPC?, then
    CALC:AVER:AVER? / SDEV? / COUN:CURR? (pp. 69, 71, 75, 200, 468).  The counter's own statistics are the Mean and Std Dev of the manual's "Math / Statistics".
  * The reference oscillator source, its automatic selection and the external reference frequency are stored in NON-VOLATILE memory and survive *RST (pp. 361, 362, 366).  The
    driver records them at connect and puts them back at cleanup (set, read back, compare); a point that needs the internal or the external time base sets it explicitly.
  * There is NO remote / local command: control is implicit.  GPIB: GTL through the transport; USB / LAN: nothing is documented, the operator presses Local.  SYSTem:LOCK:REQuest?
    (p. 453) is NOT used (it would lock the front panel including the Local key).
  * The error queue (SYST:ERR?, p. 443) holds 20 entries, is not cleared by *RST, and is per I/O session.  Error +2009 "No valid external timebase" (p. 362) means the Ext Ref In
    signal is missing when ROSC:SOUR EXT is selected.
Writes are sent once, read back and compared; nothing is retried.  Only read-only queries (SYST:ERR?, readbacks) may be retried.

NOT sent (deliberately): the Gate Out On / polarity steps of the manual's setup (OUTPut:STATe ON, p. 314).  They drive the Gate In/Out BNC only, have no effect on a reading, and
an 'OUTP:STAT ON' would look like a source output left on.  Flagged in the final report.
"""
from __future__ import annotations

import dataclasses
import math
import re
from typing import Any

import cmdreg
from cmdreg import Cmd, Placeholder
from surprise import SurpriseMixin
from .base import Instrument, InstrumentError
from .reference_instruments import AgilentAFG, Fluke96270A
from .transport import TransportError, bus_of

PR = "Keysight 53220A/53230A Programmer's Reference"
SG = 'Keysight 53210A/53220A/53230A Assembly Level Service Guide'
OVERFLOW = 9.0e37                      # 9.91E37 is the "Not a Number" reply (PR pp. 120, 213)
READINGS = 100                          # the manual's 100 readings per trigger
FUNCS = ('FREQ', 'SPER', 'PWID', 'TINT', 'BURST')
CONF_NAMES = {'FREQ': ('FREQ',), 'SPER': ('SPER',), 'PWID': ('PWID',), 'TINT': ('TINT',), 'BURST': ('FREQ:BURS', 'BURS', 'FREQ')}      # CONF? function names (p. 156: short forms)
CH_ENUM = (1, 2, 3)


def _p(page):
    return f'{PR}, p. {page}'


def _ph_ch():
    return Placeholder('int', 'd', 1)


def _setq(key, template, name, page, *, value=None, readback, enum=None, fmt='.9g', verified=True, desc=''):
    """A set command with one value placeholder (and, when the template has {ch}, the channel)."""
    ph = {'value': Placeholder('enum', '', enum[0], enum=tuple(enum)) if enum else Placeholder('float', fmt, 1.0 if value is None else value)}
    if '{ch}' in template:
        ph['ch'] = _ph_ch()
    return Cmd(template, name, desc, placeholders=ph, kind='set', readback=readback, verified=verified, ref=_p(page))


def _query(template, name, page, desc='', verified=True):
    ph = {'ch': _ph_ch()} if '{ch}' in template else {}
    return Cmd(template, name, desc, placeholders=ph, kind='query', verified=verified, ref=_p(page))


COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set', risk='locked', verified=True, ref=_p(181)),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest error, FIFO; reading removes it; +0,"No error" when empty (never overridable)', kind='query', risk='locked', verified=True, ref=_p(443)),
    'opc.query': cmdreg.opc_cmd(True, _p(189)),
    'reset': cmdreg.reset_cmd(True, f'{_p(193)} (*RST: Factory reset; the reference oscillator source / auto / external frequency are NOT reset, pp. 361-366)',
                              note='The reference oscillator settings are stored in non-volatile memory and are restored by the driver at the end of the session'),
    'opt.query': Cmd('*OPT?', 'Installed options', '<timebase 0|010>,<channel 3 0|106|115>,<pulse 0|150>,<battery 0|300>,<GPIB 0|400>', kind='query', verified=True, ref=_p(190)),
    'tst.query': Cmd('*TST?', 'Self-test', 'More than 5 seconds; +0 = passed, +1 = failed; the counter then does a Factory Reset', kind='query', verified=True, ref=_p(201)),
    'trg': Cmd('*TRG', 'Software trigger', 'Only accepted after INIT with TRIG:SOUR BUS', kind='action', verified=True, ref=_p(200)),
    'init': Cmd('INIT', 'Wait for trigger', 'Clears the previous readings and the statistics', kind='action', verified=True, ref=_p(22)),
    # ---- inputs (set before CONFigure: CONFigure does not touch them)
    'inp.coup': _setq('inp.coup', 'INP{ch}:COUP {value}', 'Input coupling', 204, enum=('DC', 'AC'), readback='inp.coup.query'),
    'inp.coup.query': _query('INP{ch}:COUP?', 'Input coupling query', 204),
    'inp.imp': _setq('inp.imp', 'INP{ch}:IMP {value:.9g}', 'Input impedance', 206, value=50.0, readback='inp.imp.query'),
    'inp.imp.query': _query('INP{ch}:IMP?', 'Input impedance query', 206),
    'inp.prob': _setq('inp.prob', 'INP{ch}:PROB {value:.9g}', 'Probe factor', 218, value=1.0, readback='inp.prob.query'),
    'inp.prob.query': _query('INP{ch}:PROB?', 'Probe factor query', 218),
    'inp.rang': _setq('inp.rang', 'INP{ch}:RANG {value:.9g}', 'Input range', 222, value=5.0, readback='inp.rang.query'),
    'inp.rang.query': _query('INP{ch}:RANG?', 'Input range query', 222),
    'inp.filt': _setq('inp.filt', 'INP{ch}:FILT {value}', 'Low-pass filter (bandwidth limit)', 205, enum=('OFF', 'ON'), readback='inp.filt.query'),
    'inp.filt.query': _query('INP{ch}:FILT?', 'Low-pass filter query', 205),
    'inp.nrej': _setq('inp.nrej', 'INP{ch}:NREJ {value}', 'Noise rejection', 217, enum=('OFF', 'ON'), readback='inp.nrej.query'),
    'inp.nrej.query': _query('INP{ch}:NREJ?', 'Noise rejection query', 217),
    # ---- measurement functions (CONFigure sets every other parameter to its default)
    'conf.freq': Cmd('CONF:FREQ {expected:.9g},DEF,(@{ch})', 'Configure frequency', 'Expected frequency, default resolution, channel (the gate is then set explicitly)',
                     placeholders={'expected': Placeholder('float', '.9g', 10e6), 'ch': _ph_ch()}, kind='set', readback='conf.query', verified=True, ref=f'{_p(117)}-118'),
    'conf.burst': Cmd('CONF:FREQ:BURS (@{ch})', 'Configure pulse burst carrier frequency', '53230A with Option 150, channel 3; CONFigure turns narrow burst mode OFF',
                      placeholders={'ch': _ph_ch()}, kind='set', readback='conf.query', verified=True, ref=_p(120)),
    'conf.sper': Cmd('CONF:SPER (@{ch})', 'Configure single period', '53220A / 53230A', placeholders={'ch': _ph_ch()}, kind='set', readback='conf.query', verified=True, ref=_p(148)),
    'conf.pwid': Cmd('CONF:PWID {ref:.9g}V,(@{ch})', 'Configure positive pulse width', 'The reference level in VOLTS (the V suffix) disables auto-level; no suffix would mean percent',
                     placeholders={'ref': Placeholder('float', '.9g', 0.0), 'ch': _ph_ch()}, kind='set', readback='conf.query', verified=True, ref=_p(143)),
    'conf.tint': Cmd('CONF:TINT (@1),(@2)', 'Configure time interval 1 to 2', 'Start Channel 1, stop Channel 2', kind='set', readback='conf.query', verified=True, ref=_p(150)),
    'conf.query': Cmd('CONF?', 'Configured function', 'Reply "FREQ +1.0E+7,+1.0E-3,(@1)" style (the function, the expected value and resolution, the channel)', kind='query', verified=True, ref=_p(156)),
    # ---- level, slope
    'inp.lev.auto': _setq('inp.lev.auto', 'INP{ch}:LEV:AUTO {value}', 'Auto level', 208, enum=('OFF', 'ON'), readback='inp.lev.auto.query'),
    'inp.lev.auto.query': _query('INP{ch}:LEV:AUTO?', 'Auto level query', 208),
    'inp.lev': _setq('inp.lev', 'INP{ch}:LEV {value:.9g}', 'Input threshold voltage', 213, value=0.0, readback='inp.lev.query', desc='Setting a level also turns auto-level off'),
    'inp.lev.query': _query('INP{ch}:LEV?', 'Input threshold query', 213),
    'inp.slop': _setq('inp.slop', 'INP{ch}:SLOP {value}', 'Input slope', 224, enum=('POS', 'NEG'), readback='inp.slop.query'),
    'inp.slop.query': _query('INP{ch}:SLOP?', 'Input slope query', 224),
    # ---- gate, mode, burst
    'gate.src': _setq('gate.src', 'SENS:FREQ:GATE:SOUR {value}', 'Frequency gate source', 324, enum=('TIME', 'EXT', 'INP', 'ADV'), readback='gate.src.query'),
    'gate.src.query': _query('SENS:FREQ:GATE:SOUR?', 'Frequency gate source query', 324),
    'gate.time': _setq('gate.time', 'SENS:FREQ:GATE:TIME {value:.9g}', 'Frequency gate time', 326, value=0.01, readback='gate.time.query'),
    'gate.time.query': _query('SENS:FREQ:GATE:TIME?', 'Frequency gate time query', 326),
    'freq.mode': _setq('freq.mode', 'SENS:FREQ:MODE {value}', 'Frequency measurement mode', 329, enum=('AUTO', 'REC', 'CONT'), readback='freq.mode.query'),
    'freq.mode.query': _query('SENS:FREQ:MODE?', 'Frequency measurement mode query', 329),
    'burst.lev': _setq('burst.lev', 'INP3:BURS:LEV {value:.9g}', 'Burst threshold (dB below the envelope peak)', 225, value=-6.0, readback='burst.lev.query', desc='-6 or -12 dB'),
    'burst.lev.query': Cmd('INP3:BURS:LEV?', 'Burst threshold query', kind='query', verified=True, ref=_p(225)),
    'burst.narrow': _setq('burst.narrow', 'SENS:FREQ:BURS:GATE:NARR {value}', 'Narrow pulse mode', 335, enum=('OFF', 'ON'), readback='burst.narrow.query',
                          desc='On for bursts of 10 us or less, Off for bursts longer than 20 us'),
    'burst.narrow.query': Cmd('SENS:FREQ:BURS:GATE:NARR?', 'Narrow pulse mode query', kind='query', verified=True, ref=_p(335)),
    'burst.auto': _setq('burst.auto', 'SENS:FREQ:BURS:GATE:AUTO {value}', 'Automatic burst gate', 331, enum=('OFF', 'ON'), readback='burst.auto.query'),
    'burst.auto.query': Cmd('SENS:FREQ:BURS:GATE:AUTO?', 'Automatic burst gate query', kind='query', verified=True, ref=_p(331)),
    # ---- trigger, samples, statistics
    'samp.count': _setq('samp.count', 'SAMP:COUN {value:.9g}', 'Readings per trigger', 317, value=100.0, readback='samp.count.query'),
    'samp.count.query': Cmd('SAMP:COUN?', 'Readings per trigger query', kind='query', verified=True, ref=_p(317)),
    'trig.count': _setq('trig.count', 'TRIG:COUN {value:.9g}', 'Triggers accepted', 463, value=1.0, readback='trig.count.query'),
    'trig.count.query': Cmd('TRIG:COUN?', 'Trigger count query', kind='query', verified=True, ref=_p(463)),
    'trig.delay': _setq('trig.delay', 'TRIG:DEL {value:.9g}', 'Trigger delay', 465, value=0.0, readback='trig.delay.query'),
    'trig.delay.query': Cmd('TRIG:DEL?', 'Trigger delay query', kind='query', verified=True, ref=_p(465)),
    'trig.source': _setq('trig.source', 'TRIG:SOUR {value}', 'Trigger source', 468, enum=('IMM', 'EXT', 'BUS'), readback='trig.source.query', desc='BUS = the manual\'s "trigger Manual"'),
    'trig.source.query': Cmd('TRIG:SOUR?', 'Trigger source query', kind='query', verified=True, ref=_p(468)),
    'calc.state': _setq('calc.state', 'CALC:STAT {value}', 'Calculate subsystem', 77, enum=('OFF', 'ON'), readback='calc.state.query'),
    'calc.state.query': Cmd('CALC:STAT?', 'Calculate subsystem query', kind='query', verified=True, ref=_p(77)),
    'calc.aver.state': _setq('calc.aver.state', 'CALC:AVER:STAT {value}', 'Statistics', 76, enum=('OFF', 'ON'), readback='calc.aver.state.query'),
    'calc.aver.state.query': Cmd('CALC:AVER:STAT?', 'Statistics query', kind='query', verified=True, ref=_p(76)),
    'calc.mean': Cmd('CALC:AVER:AVER?', 'Mean of the readings', kind='query', verified=True, ref=_p(69)),
    'calc.sdev': Cmd('CALC:AVER:SDEV?', 'Standard deviation of the readings', kind='query', verified=True, ref=_p(75)),
    'calc.count': Cmd('CALC:AVER:COUN:CURR?', 'Number of readings in the statistics', kind='query', verified=True, ref=_p(71)),
    # ---- reference oscillator (non-volatile: survives *RST)
    'rosc.src': _setq('rosc.src', 'SENS:ROSC:SOUR {value}', 'Reference oscillator source', 362, enum=('INT', 'EXT'), readback='rosc.src.query',
                      desc='Selecting a source turns automatic selection OFF; stored in non-volatile memory'),
    'rosc.src.query': Cmd('SENS:ROSC:SOUR?', 'Reference oscillator source query', kind='query', verified=True, ref=_p(362)),
    'rosc.auto': _setq('rosc.auto', 'SENS:ROSC:SOUR:AUTO {value}', 'Automatic reference selection', 366, enum=('OFF', 'ON'), readback='rosc.auto.query', desc='Stored in non-volatile memory'),
    'rosc.auto.query': Cmd('SENS:ROSC:SOUR:AUTO?', 'Automatic reference selection query', kind='query', verified=True, ref=_p(366)),
    'rosc.ext.freq': _setq('rosc.ext.freq', 'SENS:ROSC:EXT:FREQ {value:.9g}', 'External reference frequency', 361, value=10e6, readback='rosc.ext.freq.query', desc='1, 5 or 10 MHz; stored in non-volatile memory'),
    'rosc.ext.freq.query': Cmd('SENS:ROSC:EXT:FREQ?', 'External reference frequency query', kind='query', verified=True, ref=_p(361)),
    'rosc.ext.check': Cmd('SENS:ROSC:EXT:CHEC ONCE', 'Check for a valid external reference', 'Error +2009 when there is no valid signal on Ext Ref In; needs ROSC:SOUR EXT and AUTO OFF', kind='action',
                          verified=True, ref=_p(360)),
}


def _unverified(registry, note):
    """The same registry with every `verified` flag cleared and the reason added to the page reference (the 53210A: its Programmer's Reference was not supplied)."""
    return {k: dataclasses.replace(c, verified=False, ref=f'{c.ref}  [{note}]') for k, c in registry.items()}


COMMANDS_53210A = _unverified(COMMANDS, '53210A: the supplied Programmer\'s Reference covers the 53220A / 53230A only - UNVERIFIED for the 53210A')


def _num(reply):
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(reply))
    if not m:
        raise InstrumentError(f'no number in the reply {str(reply).strip()!r}')
    return float(m.group(0))


def _text(reply):
    return str(reply).strip().strip('"\'').strip().upper()


def _flag(reply):
    t = _text(reply)
    if t in ('1', '+1', 'ON'):
        return True
    if t in ('0', '+0', 'OFF'):
        return False
    raise InstrumentError(f'expected 0/1 or ON/OFF, the counter answered {str(reply).strip()!r}')


def parse_options(reply):
    """*OPT? -> {'timebase': '010' | 'std', 'ch3': '106' | '115' | None, 'pulse': '150' | None, 'codes': {...}} (PR p. 190).  A field that is not one of the printed codes is kept in 'unknown'."""
    fields = [f.strip().strip('"\'').strip() for f in str(reply).strip().split(',')]
    fields += ['0'] * (5 - len(fields))
    tb, ch3, pulse = fields[0], fields[1], fields[2]
    out: dict[str, Any] = dict(timebase='010' if tb == '010' else 'std', ch3=ch3 if ch3 in ('106', '115') else None, pulse='150' if pulse == '150' else None, unknown=[])
    for name, val, ok in (('timebase', tb, ('0', '010')), ('ch3', ch3, ('0', '106', '115')), ('pulse', pulse, ('0', '150'))):
        if val not in ok:
            out['unknown'].append(f'{name}={val}')
    out['codes'] = {c for c in (('010' if out['timebase'] == '010' else None), out['ch3'], out['pulse']) if c}
    out['raw'] = str(reply).strip()
    return out


class Keysight53220A(SurpriseMixin, Instrument):
    MODEL = 'Keysight 53220A'
    SHORT = '53220A'
    IDN_MATCH = ('53220A',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 20.0
    SELFTEST_TIMEOUT = 60.0             # *TST? takes more than 5 seconds (PR p. 201)
    MICRO_CH = 3                         # the microwave input (the 53210A: Channel 2, Service Guide p. 67)
    TWO_CH = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.options = None
        self.saved_ref = None            # the reference oscillator settings found at connect (restored at cleanup)
        self._ref_now = None             # the source this session last selected (None: not touched yet)
        self._ref_touched = False        # True once this session wrote a reference oscillator setting
        self.gate_s = 0.1

    @property
    def bus(self) -> str:
        return getattr(self.t, 'bus', None) or bus_of(str(getattr(self.t, 'name', '') or getattr(self.t, 'address', '') or ''))

    # ---- lifecycle ---------------------------------------------------------------------------------------------------
    def connect(self):
        """Open, device clear, *CLS, confirm the model, read *OPT? and remember the non-volatile reference settings.  No remote command exists: control is implicit."""
        self.open(verify_model=False)
        self.t.clear()
        self.send('status.clear')
        try:
            self.idn = self.identify()
        except TransportError as exc:
            self.close()
            raise InstrumentError(f'The {self.SHORT} did not answer *IDN? ({exc}). Check the USB / LAN / GPIB resource.') from exc
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a {self.SHORT} but the instrument identifies as: {self.idn!r}')
        self.read_options()
        self.saved_ref = self.read_reference()
        self._ref_now = None
        self._ref_touched = False
        return self

    def read_options(self):
        self.options = parse_options(self.ask('opt.query'))
        return self.options

    def local(self):
        """Back to the front panel: GTL over GPIB.  USB / LAN: no command is documented; the operator presses Local (PR has no SYST:LOC)."""
        if self.bus == 'GPIB':
            self.t.go_local()

    def cleanup(self):
        """Put the reference oscillator settings back as they were at connect, then local.  Never raises."""
        try:
            self.restore_reference()
        except Exception as exc:
            try:
                self.log.add('!!', f'reference oscillator settings were NOT restored: {exc}', self.label)
            except Exception:
                pass
        try:
            self.local()
        except Exception:
            pass

    def _reset_extra(self):
        return [('inputs, level and trigger known (the next point sets them again)', lambda: 'Factory reset state; the reference oscillator is set per test')]

    # ---- set / read back / compare ---------------------------------------------------------------------------------------
    def _same(self, kind, want, reply):
        if kind == 'num':
            return self.close_to(_num(reply), float(want), rel=1e-6, abs_=1e-12)
        if kind == 'bool':
            return _flag(reply) == (str(want).upper() in ('ON', '1'))
        got, w = _text(reply), str(want).upper()
        n = min(3, len(w), len(got))                    # SCPI short forms: POS / POSitive, EXT / EXTernal, TIME
        return n > 0 and got[:n] == w[:n]

    def _set(self, key, value, kind='text', name='value', **vals):
        """ONE write, ONE read back (the query paired with `key` in the registry, same channel), compare.  A mismatch raises InstrumentError, or - with stop-on-surprise on - shows the
        Stop / Continue dialog.  No retry of the write.  The error queue is read at the end of a configuration (errq_checkpoint), not after each write."""
        reg = self._registry()
        rb = reg[key].readback
        if not rb:
            raise InstrumentError(f'{key}: no read-back command declared (Cmd.readback)')
        shown = {name: value, **vals}
        self.send(key, **shown)
        reply = self.ask_checked(rb, expect='float' if kind == 'num' else ('any' if kind == 'text' else 'any'), **vals)
        try:
            ok = self._same(kind, value, reply)
        except InstrumentError:
            ok = False
        if not ok:
            g = self._g()
            if g is None:
                raise InstrumentError(f'{self.label}: {cmdreg.render(reg[key], shown)}: set {value}, the counter reports {str(reply).strip()!r}')
            from surprise import _display
            g.surprise('readback', _display(self, key, shown), str(reply).strip(), f'{value}', f'read back with {rb}')
        return reply

    def check_errors(self, context: str = ''):
        """Raise if the error queue holds anything: read until '+0,"No error"' (at most 21 reads: the queue holds 20, PR p. 443)."""
        found = []
        for _ in range(21):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))

    # ---- reference oscillator ----------------------------------------------------------------------------------------------
    def read_reference(self) -> dict[str, Any]:
        """The three non-volatile settings: source (INT / EXT), automatic selection, external frequency.  Read-only queries."""
        src = _text(self.ask('rosc.src.query'))
        auto = _flag(self.ask('rosc.auto.query'))
        freq = _num(self.ask('rosc.ext.freq.query'))
        return dict(source='EXT' if src.startswith('EXT') else 'INT', auto=auto, ext_freq=freq)

    def set_reference(self, source: str):
        """Select the time base for a test.  INT: the internal oscillator.  EXT: 10 MHz on Ext Ref In, checked once (+2009 'No valid external timebase' when it is missing).
        Both turn automatic selection OFF (PR p. 362).  Sent only when it changes, because the settings live in non-volatile memory."""
        if source not in ('INT', 'EXT'):
            raise InstrumentError(f'unknown time base {source!r}')
        if self._ref_now == source:
            return
        self._ref_touched = True
        if source == 'EXT':
            self._set('rosc.ext.freq', 10e6, 'num')
            self._set('rosc.src', 'EXT')
            self.send('rosc.ext.check')
            try:
                self.errq_checkpoint('SENS:ROSC:EXT:CHEC ONCE')
            except InstrumentError as exc:
                if '2009' in str(exc):
                    raise InstrumentError('The counter reports "No valid external timebase": connect the 10 MHz reference to Ext Ref In (Test 1 is the only test that uses the internal time base). '
                                          f'({exc})') from None
                raise
        else:
            self._set('rosc.src', 'INT')
        self._ref_now = source

    def restore_reference(self):
        """Put the non-volatile reference settings back as found at connect (set, read back, compare).  Called by cleanup(); a mismatch is raised for the caller to log."""
        saved = self.saved_ref
        if not saved or not self._ref_touched:
            return
        cur = self.read_reference()
        if not math.isclose(cur['ext_freq'], saved['ext_freq'], rel_tol=1e-6):
            self._set('rosc.ext.freq', saved['ext_freq'], 'num')
        if saved['auto']:
            self._set('rosc.auto', 'ON', 'bool')
        else:
            self._set('rosc.src', saved['source'])
        self._ref_now = None
        self._ref_touched = False
        self.errq_checkpoint('restoring the reference oscillator settings')

    # ---- one test point -----------------------------------------------------------------------------------------------------
    def _channel(self, ch):
        return self.MICRO_CH if ch == 3 else ch

    def configure_inputs(self, channels):
        """DC coupling, 50 ohm, 1:1 probe, 5 V range, low-pass filter Off, noise rejection Off (the manual's channel setup).  Before CONFigure, which leaves them alone."""
        for ch in channels:
            self._set('inp.coup', 'DC', ch=ch)
            self._set('inp.imp', 50.0, 'num', ch=ch)
            self._set('inp.prob', 1.0, 'num', ch=ch)
            self._set('inp.rang', 5.0, 'num', ch=ch)
            self._set('inp.filt', 'OFF', 'bool', ch=ch)
            self._set('inp.nrej', 'OFF', 'bool', ch=ch)

    def _level_off(self, channels):
        """Auto level Off, level 0.000 V, positive slope (after CONFigure, which turns auto-level on)."""
        for ch in channels:
            self._set('inp.lev.auto', 'OFF', 'bool', ch=ch)
            self._set('inp.lev', 0.0, 'num', ch=ch)
            self._set('inp.slop', 'POS', ch=ch)

    def _confirm_function(self, func, ch):
        reply = _text(self.ask_checked('conf.query', expect='any'))
        fn = reply.split()[0].strip('"') if reply else ''
        names = CONF_NAMES[func]
        if not any(fn == n or (func == 'BURST' and n in fn) for n in names):
            self._mismatch('conf.query', f'function {func}', reply)
        want = '(@1),(@2)' if func == 'TINT' else f'(@{ch})'
        if func != 'BURST' and want.replace(' ', '') not in reply.replace(' ', ''):
            self._mismatch('conf.query', f'channel {want}', reply)

    def _mismatch(self, rb, what, reply):
        g = self._g()
        if g is None:
            raise InstrumentError(f'{self.label}: {what} was not accepted: the counter answered {reply!r}')
        g.surprise('readback', rb, reply, what, f'read back with {rb}')

    def configure_point(self, point: dict):
        """Configure one measurement.  point: func (FREQ / SPER / PWID / TINT / BURST), channel (1, 2, 3 = the microwave channel; 12 = time interval 1 to 2), nominal (expected frequency),
        gate_s (None keeps the CONFigure default gate), narrow, burst_db."""
        func, ch = point['func'], point.get('channel')
        if func not in FUNCS:
            raise InstrumentError(f'{self.label}: no function {func!r}')
        c = self._channel(ch) if ch else 1
        micro = ch == 3
        channels = [1, 2] if func == 'TINT' else ([] if micro else [c])
        self.configure_inputs(channels)
        if func == 'FREQ':
            self.send('conf.freq', expected=float(point['nominal']), ch=c)
        elif func == 'SPER':
            self.send('conf.sper', ch=c)
        elif func == 'PWID':
            self.send('conf.pwid', ref=0.0, ch=c)
        elif func == 'TINT':
            self.send('conf.tint')
        elif func == 'BURST':
            self.send('conf.burst', ch=c)
        self._confirm_function(func, c)
        if func in ('FREQ', 'SPER', 'PWID') and not micro:
            self._level_off([c])
        elif func == 'TINT':
            self._level_off([1, 2])
        if func == 'FREQ':
            self._set('freq.mode', 'AUTO')
            self._set('gate.src', 'TIME')
            if point.get('gate_s'):
                self._set('gate.time', float(point['gate_s']), 'num')
                self.gate_s = float(point['gate_s'])
            else:
                self.gate_s = 0.1                       # the CONFigure default gate (PR p. 326)
        if func == 'BURST':
            self._set('burst.lev', float(point.get('burst_db', -6)), 'num')
            self._set('burst.narrow', 'ON' if point.get('narrow') else 'OFF', 'bool')
            self._set('burst.auto', 'ON', 'bool')
        self.errq_checkpoint('configuring ' + str(point.get('description', func)))

    def measure_stats(self, readings=READINGS):
        """100 readings on one software trigger and the counter's own statistics: Mean, Std Dev and the number of readings.  Never retried.
        Order (PR pp. 22, 76, 200, 468): sample count, trigger count / delay / source BUS, statistics On, INIT, *TRG, *OPC?, then the three queries."""
        self._set('samp.count', float(readings), 'num')
        self._set('trig.count', 1.0, 'num')
        self._set('trig.delay', 0.0, 'num')
        self._set('trig.source', 'BUS')
        self._set('calc.state', 'ON', 'bool')
        self._set('calc.aver.state', 'ON', 'bool')
        self.send('init')
        self.send('trg')
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(self.DEFAULT_TIMEOUT, readings * max(self.gate_s, 0.001) * 1.5 + 15.0))
        try:
            self.ask('opc.query')
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        count = _num(self.ask_checked('calc.count', expect='float'))
        mean = _num(self.ask_checked('calc.mean', expect='float'))
        sdev = _num(self.ask_checked('calc.sdev', expect='float'))
        if abs(mean) >= OVERFLOW or abs(sdev) >= OVERFLOW:
            raise InstrumentError(f'The {self.SHORT} returned "Not a Number" (9.91E37): no usable signal at the input (level, frequency or connection).')
        if int(round(count)) != int(readings):
            raise InstrumentError(f'The {self.SHORT} made {count:g} readings, not {readings}: the statistics are not for a full set.')
        return dict(mean=mean, sdev=sdev, count=int(round(count)))

    def self_test(self):
        """*TST? -> 0 (all tests passed) or 1.  More than 5 seconds; the counter then does a Factory Reset (PR p. 201), so the caller configures again afterwards."""
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(self.SELFTEST_TIMEOUT)
        try:
            reply = self.ask('tst.query')
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        return int(round(_num(reply)))


class Keysight53230A(Keysight53220A):
    MODEL = 'Keysight 53230A'
    SHORT = '53230A'
    IDN_MATCH = ('53230A',)


class Keysight53210A(Keysight53220A):
    """UNVERIFIED: the supplied Programmer's Reference covers the 53220A and 53230A only.  The microwave input is Channel 2 (Service Guide p. 67); there is no Channel 2 input, no time
    interval / pulse width / single period test, no burst test."""
    MODEL = 'Keysight 53210A'
    SHORT = '53210A'
    IDN_MATCH = ('53210A',)
    COMMANDS = COMMANDS_53210A
    MICRO_CH = 2
    TWO_CH = False


class Fluke96270AWide(SurpriseMixin, Fluke96270A):
    """The 96270A for this procedure: the same driver and commands, with the frequency limit of the instrument itself (the Microwave O/P direct output reaches 27 GHz, Operator Manual
    Table 3-1) instead of the 6.2 GHz the MDO4000C tests use.  No command is added: which output connector is used (Leveling Head / Microwave O/P) and the reference in / out are set
    on the front panel by the operator (the remote commands for them are UNVERIFIED: the Remote Programmers Manual is not on file)."""
    MAX_HZ = 27e9


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Agilent 33250A as a PULSE generator (owner 2026-10-27).  Commands and limits are from the Agilent 33250A User's Guide (337 pp. PDF; the page numbers below are the PRINTED
# page numbers = PDF page - 1), the pages read as rendered images.  Not run on hardware.
#   FUNCtion {PULSe}        p. 153        PULSe:PERiod  p. 166 (20 ns to 2000 s)     OUTPut {ON|OFF}  p. 162        VOLTage:UNIT  p. 165
#   PULSe:WIDTh   p. 167 (8 ns to 2000 s) PULSe:TRANsition p. 168 (5 ns to 1 ms)     OUTPut:LOAD      p. 163        VOLTage       p. 156
#   VOLTage:OFFSet p. 158                 SYSTem:ERRor? p. 213                       Specifications   p. 320 (pulse period / width / edge; ONE Output connector + Sync)
# The 33250A has NO PULSe:DCYCle command and no second pulse output with a delay: the Sync output of a pulse waveform is a 50 % duty square wave (p. 62).
PULSE_LIMITS = dict(min_period_s=20e-9, max_period_s=2000.0, min_width_s=8e-9, max_width_s=2000.0, min_edge_s=5e-9, max_edge_s=1e-3, min_vpp=0.01, max_vpp=10.0)
PULSE_PAGES = {'func': 153, 'period': 166, 'width': 167, 'edge': 168, 'output': 162, 'load': 163, 'volt': 156, 'unit': 165, 'offset': 158, 'error': 213, 'specs': 320}
_UG = "Agilent 33250A User's Guide"


def _pg(topic, key):
    return f'{_UG}: {topic} (p. {PULSE_PAGES[key]})'


AFG_PULSE_COMMANDS = {
    'outp.on': Cmd('OUTPut ON', 'Output on', 'Enables the output (never overridable)', kind='set', readback='outp.query', risk='output', verified=True, ref=_pg('OUTPut', 'output')),
    'outp.off': Cmd('OUTPut OFF', 'Output off', 'Disables the output (never overridable)', kind='set', readback='outp.query', risk='output', verified=True, ref=_pg('OUTPut', 'output')),
    'outp.query': Cmd('OUTPut?', 'Output state', 'Returns 0 or 1 (never overridable)', kind='query', risk='output', verified=True, ref=_pg('OUTPut?', 'output')),
    'load.50': Cmd('OUTPut:LOAD 50', 'Output termination 50 ohm', kind='set', readback='load.query', verified=True, ref=_pg('OUTPut:LOAD', 'load')),
    'load.inf': Cmd('OUTPut:LOAD INFinity', 'Output termination High Z', 'OUTP:LOAD? returns 9.9E+37 for high impedance', kind='set', readback='load.query', verified=True,
                    ref=_pg('OUTPut:LOAD', 'load')),
    'load.query': Cmd('OUTPut:LOAD?', 'Output termination', kind='query', verified=True, ref=_pg('OUTPut:LOAD?', 'load')),
    'func.pulse': Cmd('FUNCtion PULSe', 'Pulse function', 'FUNC? returns PULS', kind='set', readback='func.query', verified=True, ref=_pg('FUNCtion', 'func')),
    'func.query': Cmd('FUNCtion?', 'Function', kind='query', verified=True, ref=_pg('FUNCtion?', 'func')),
    'pulse.per': Cmd('PULSe:PERiod {seconds:.9g}', 'Pulse period', 'Seconds, 20 ns to 2000 s; must exceed width + 1.6 x edge time', placeholders={'seconds': Placeholder('float', '.9g', 1e-3)},
                     kind='set', readback='pulse.per.query', verified=True, ref=_pg('PULSe:PERiod', 'period')),
    'pulse.per.query': Cmd('PULSe:PERiod?', 'Pulse period', kind='query', verified=True, ref=_pg('PULSe:PERiod?', 'period')),
    'pulse.wid': Cmd('PULSe:WIDTh {seconds:.9g}', 'Pulse width', 'Seconds, 8 ns to 2000 s; 50 % to 50 % thresholds; at least 1.6 x edge time',
                     placeholders={'seconds': Placeholder('float', '.9g', 100e-6)}, kind='set', readback='pulse.wid.query', verified=True, ref=_pg('PULSe:WIDTh', 'width')),
    'pulse.wid.query': Cmd('PULSe:WIDTh?', 'Pulse width', kind='query', verified=True, ref=_pg('PULSe:WIDTh?', 'width')),
    'pulse.tran': Cmd('PULSe:TRANsition {seconds:.9g}', 'Edge time', 'Seconds, 5 ns to 1 ms, both edges, 10 % to 90 %; below 0.625 x pulse width',
                      placeholders={'seconds': Placeholder('float', '.9g', 5e-9)}, kind='set', readback='pulse.tran.query', verified=True, ref=_pg('PULSe:TRANsition', 'edge')),
    'pulse.tran.query': Cmd('PULSe:TRANsition?', 'Edge time', kind='query', verified=True, ref=_pg('PULSe:TRANsition?', 'edge')),
    'unit.vpp': Cmd('VOLTage:UNIT VPP', 'Amplitude unit Vpp', kind='set', readback='unit.query', verified=True, ref=_pg('VOLTage:UNIT', 'unit')),
    'unit.query': Cmd('VOLTage:UNIT?', 'Amplitude unit', kind='query', verified=True, ref=_pg('VOLTage:UNIT?', 'unit')),
    'volt.set': Cmd('VOLTage {vpp:.6g}', 'Amplitude', 'In the unit set by VOLT:UNIT (Vpp)', placeholders={'vpp': Placeholder('float', '.6g', 1.0)}, kind='set', readback='volt.query',
                    verified=True, ref=_pg('VOLTage', 'volt')),
    'volt.query': Cmd('VOLTage?', 'Amplitude', kind='query', verified=True, ref=_pg('VOLTage?', 'volt')),
    'offs.zero': Cmd('VOLTage:OFFSet 0', 'DC offset 0 V', kind='set', readback='offs.query', verified=True, ref=_pg('VOLTage:OFFSet', 'offset')),
    'offs.query': Cmd('VOLTage:OFFSet?', 'DC offset', kind='query', verified=True, ref=_pg('VOLTage:OFFSet?', 'offset')),
    'err.query': Cmd('SYSTem:ERRor?', 'Error queue', "Oldest error; '+0,\"No error\"' when empty (never overridable)", kind='query', risk='locked', verified=True, ref=_pg('SYSTem:ERRor?', 'error')),
}


def pulse_problems(period_s, width_s, edge_s, vpp, limits=PULSE_LIMITS):
    """Why the 33250A cannot make this pulse (empty list = it can), from the User's Guide limits (pp. 166-168, 320).  Pure arithmetic, nothing is sent."""
    L, out = limits, []
    if not L['min_period_s'] <= period_s <= L['max_period_s']:
        out.append(f'period {period_s:.6g} s is outside {L["min_period_s"]:g} s to {L["max_period_s"]:g} s (p. {PULSE_PAGES["period"]})')
    if not L['min_edge_s'] <= edge_s <= L['max_edge_s']:
        out.append(f'edge time {edge_s:.6g} s is outside {L["min_edge_s"]:g} s to {L["max_edge_s"]:g} s (p. {PULSE_PAGES["edge"]})')
    if not L['min_width_s'] <= width_s <= L['max_width_s']:
        out.append(f'pulse width {width_s:.6g} s is outside {L["min_width_s"]:g} s to {L["max_width_s"]:g} s (p. {PULSE_PAGES["width"]})')
    eps = 1e-12
    if width_s < 1.6 * edge_s * (1 - eps):
        out.append(f'pulse width {width_s:.6g} s must be at least 1.6 x the edge time ({1.6 * edge_s:.6g} s) (p. {PULSE_PAGES["width"]})')
    if period_s <= (width_s + 1.6 * edge_s) * (1 - eps):
        out.append(f'period {period_s:.6g} s must exceed the pulse width + 1.6 x edge time ({width_s + 1.6 * edge_s:.6g} s) (p. {PULSE_PAGES["period"]})')
    if not L['min_vpp'] <= vpp <= L['max_vpp']:
        out.append(f'{vpp:g} Vpp is outside {L["min_vpp"]:g} to {L["max_vpp"]:g} Vpp into 50 ohm (p. {PULSE_PAGES["specs"]})')
    return out


class AgilentAFGPulse(SurpriseMixin, AgilentAFG):
    """The Agilent 33250A as a pulse generator (the AgilentAFG driver plus pulse methods; sine() and square() are unchanged).  Every setting is written once, read back and compared;
    nothing is retried; the error queue is read after the configuration.  The output stays OFF until output(True), which is confirmed with OUTP?."""
    MODEL = 'Agilent 33250A (pulse)'
    IDN_MATCH = ('33250',)
    COMMANDS = AFG_PULSE_COMMANDS

    def _num(self, key, **vals):
        return float(self.ask(key, **vals).strip())

    def _set_num(self, key, query, want, what, rel=1e-6, abs_=0.0, **vals):
        self.send(key, **vals)
        got = self._num(query)
        if not math.isclose(got, want, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{self.MODEL} {what}: set {want:.9g}, reports {got:.9g}')
        return got

    def _set_text(self, key, query, want, what):
        self.send(key)
        got = self.ask(query).strip().strip('"').upper()
        if not got.startswith(want):
            raise InstrumentError(f'{self.MODEL} {what}: set {cmdreg.render(self._registry()[key])!r}, reports {got!r}')

    def check_errors(self, context=''):
        """SYSTem:ERRor? until '+0,"No error"' (the queue holds 20); raise with what was found.  Reads only, so they may be retried."""
        found = []
        for _ in range(21):
            reply = self.ask('err.query').strip()
            code = reply.split(',')[0].strip().lstrip('+')
            try:
                if int(float(code)) == 0:
                    break
            except ValueError:
                pass
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" (" + context + ")" if context else ""}: ' + ' | '.join(found))

    def output(self, on: bool):
        """OUTPut ON / OFF, confirmed with OUTPut?.  An unconfirmed OFF is a SafetyError."""
        self.send('outp.on' if on else 'outp.off')
        state = self.ask('outp.query').strip()
        if state != ('1' if on else '0'):
            if on:
                raise InstrumentError(f'{self.MODEL} did not confirm output ON (OUTP? -> {state!r})')
            from .base import SafetyError
            raise SafetyError(f'{self.MODEL} did not confirm output OFF (OUTP? -> {state!r}); check the front panel')

    def cleanup(self):
        try:
            self.send('outp.off')
            self.output_off_confirmed = self.ask('outp.query').strip() == '0'
        except Exception:
            self.output_off_confirmed = False

    output_off_confirmed = False

    def _pulse_order(self, new):
        """The order in which period / width / edge time are written so that no intermediate state breaks the manual's relations (the generator would adjust the others and
        report 'Settings conflict').  The present values are read (queries); None when no order works."""
        import itertools
        cur = dict(period=self._num('pulse.per.query'), width=self._num('pulse.wid.query'), edge=self._num('pulse.tran.query'))
        for order in itertools.permutations(('period', 'width', 'edge')):
            state, ok = dict(cur), True
            for name in order:
                state[name] = new[name]
                if pulse_problems(state['period'], state['width'], state['edge'], 1.0, dict(PULSE_LIMITS, min_vpp=0.0)):
                    ok = False; break
            if ok:
                return order
        return None

    def pulse(self, period_s, width_s, edge_s=None, vpp=1.0, load='50'):
        """Configure a pulse with the output OFF: 50 ohm (or High Z) termination, PULSe, 0 V offset, Vpp, period, width and edge time (default: the minimum 5 ns), each read back.
        Refuses (before sending anything) what the User's Guide says the 33250A cannot make.  The output stays OFF."""
        edge_s = PULSE_LIMITS['min_edge_s'] if edge_s is None else edge_s
        problems = pulse_problems(period_s, width_s, edge_s, vpp)
        if problems:
            raise InstrumentError(f'{self.MODEL} cannot make this pulse: ' + '; '.join(problems))
        self.output(False)
        if str(load).upper().startswith('INF'):
            self.send('load.inf')
            if self._num('load.query') < 1e37:
                raise InstrumentError(f'{self.MODEL} output termination: set High Z, reports {self._num("load.query"):g} ohm')
        else:
            self._set_num('load.50', 'load.query', 50.0, 'output termination')
        self._set_text('func.pulse', 'func.query', 'PULS', 'function')
        self._set_text('unit.vpp', 'unit.query', 'VPP', 'amplitude unit')
        self._set_num('offs.zero', 'offs.query', 0.0, 'dc offset', abs_=1e-6)
        order = self._pulse_order(dict(period=period_s, width=width_s, edge=edge_s))
        if order is None:
            raise InstrumentError(f'{self.MODEL}: no safe order to write period {period_s:g} s, width {width_s:g} s, edge {edge_s:g} s from the present state')
        keys = dict(period=('pulse.per', 'pulse.per.query', period_s, 'pulse period'), width=('pulse.wid', 'pulse.wid.query', width_s, 'pulse width'),
                    edge=('pulse.tran', 'pulse.tran.query', edge_s, 'edge time'))
        for name in order:
            key, query, want, what = keys[name]
            self._set_num(key, query, want, what, rel=1e-6, abs_=1e-12, seconds=want)
        self._set_num('volt.set', 'volt.query', vpp, 'amplitude', rel=1e-4, abs_=1e-4, vpp=vpp)
        self.check_errors(f'pulse {width_s:g} s wide, period {period_s:g} s, {vpp:g} Vpp')
