"""Rohde & Schwarz SMA100B RF and microwave signal generator over GPIB (also LAN / USB through VISA): CW frequency, CW level, RF output on / off.

Source: "R&S SMA100B User Manual" 1178.3834.02 - 14 (SMA100B_UserManual_en_14.pdf on branch 6060a-gidep-uncertainty). The printed page numbers are the PDF page
numbers. Every Cmd below carries its page. NOTHING has been run on a real SMA100B yet (NOTES.md 'Bench-first driver workflow'), so every command is verified=False
until a bench session records its reply and driver_verify passes it.

What the driver is for: a CW RF source (reference standard or unit under test). One frequency, one level, RF on / off, modulation off, nothing else. Sweep, list mode,
modulation set-up, the user correction, the LF generator are left out on purpose.

Manual facts the driver relies on:
  * GPIB address: factory preset 28 (p. 788). The address is given to the constructor / connect(); never fixed in code. The driver never sends SYST:COMM:... (cmdreg forbids it).
  * *RST = SYSTem:PRESet (p. 490 / 491): RF output OFF (OUTP *RST 0, p. 536), FREQ:MODE CW (p. 702), POW:MODE CW (p. 747), level -30 dBm (p. 753), modulation off
    (MOD:ALL:STAT *RST 0, p. 614), UNIT:POW DBM (p. 817), FREQ:OFFS 0 / FREQ:MULT 1 (p. 704), POW:OFFS 0 (p. 752).
  * NOT reset by *RST (factory preset only): the reference oscillator source INT / EXT (p. 756) and the RF level LIMIT (p. 746). The driver reads both at connect() and after a reset
    and reports them; it never changes the limit (it is the lab's protection setting).
  * POW? does NOT show the limit (p. 746): a level above POW:LIM? reads back as asked but is not what comes out. set_level() refuses such a level before sending it.
  * FREQ? and POW? include the downstream offset / multiplier (FREQ? = f_out * MULT + OFFS, p. 704; POW = output level + OFFS, p. 753). The driver confirms OFFS 0 / MULT 1 /
    POW:OFFS 0 so a read-back is the real output.
  * SYST:ERR? returns '0,"No error"' when empty (p. 783) and removes the entry it returns; *TST? returns 0 = no error (p. 492); *OPC? answers 1 when every command before it
    is done (p. 489); *IDN? 'Rohde&Schwarz,SMA100B,<part>/<serial>,<firmware>' (p. 489).
  * FREQ resolution / range and the level range depend on the installed options (p. 703, 753): the driver does not hard-code them. An out-of-range value is caught by the
    error-queue check after the write (and by the read-back).
Reply formats the manual does not print (UNVERIFIED, matched loosely): FREQ:MODE? / POW:MODE? (CW or FIX), UNIT:POW? (DBM), ROSC:SOUR? (INT / EXT), OUTP? and MOD:ALL:STAT?
(0 / 1), the number format of FREQ? / POW?.
Writes are sent once, read back and compared; never retried. Only read-only queries may be retried. cleanup() switches RF OFF (confirmed) and returns the panel to local.
"""
from __future__ import annotations

import math
import re

import cmdreg
from cmdreg import Cmd, Placeholder
from surprise import SurpriseMixin
from .base import Instrument, InstrumentError, SafetyError
from .gpib_address import address_of, check_address, retarget

UM = 'R&S SMA100B User Manual 1178.3834.02-14'
FREQ_TOL_HZ = 0.01                    # read-back tolerance; the manual's increment 'depends on options' (p. 703), the smallest offset increment is 0.01 Hz (p. 704)
LEVEL_TOL_DB = 0.005                  # level increment 0.01 dB (p. 752 / 753)
REF_SOURCES = ('INT', 'EXT')


def _r(topic, page):
    return f'{UM}: {topic} (p. {page})'


def _num(text):
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(text))
    return float(m.group(0)) if m else None


COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set', risk='locked', verified=False,
                        ref=_r('*CLS', '488')),
    'err.query': Cmd('SYST:ERR?', 'Error queue', 'Oldest entry, removed from the queue; 0,"No error" when empty (never overridable)', kind='query', risk='locked',
                     verified=False, ref=_r(':SYSTem:ERRor[:NEXT]?', '783')),
    'idn.query': Cmd('*IDN?', 'Identify', 'Rohde&Schwarz,SMA100B,<part number>/<serial>,<firmware>', kind='query', risk='locked', verified=False, ref=_r('*IDN?', '489')),
    'opt.query': Cmd('*OPT?', 'Installed options', 'Comma-separated option list (frequency and level ranges depend on it)', kind='query', verified=False, ref=_r('*OPT?', '489')),
    'selftest': Cmd('*TST?', 'Self-test', 'Runs the self-tests: 0 = no error, > 0 = error code (never overridable)', kind='query', risk='locked', verified=False,
                    ref=_r('*TST?', '492')),
    'outp.on': Cmd('OUTP ON', 'RF on', 'Switches the RF output on (never overridable)', kind='set', readback='outp.query', risk='output', verified=False,
                   ref=_r(':OUTPut<hw>[:STATe]', '536')),
    'outp.off': Cmd('OUTP OFF', 'RF off', 'Switches the RF output off (never overridable)', kind='set', readback='outp.query', risk='output', verified=False,
                    ref=_r(':OUTPut<hw>[:STATe]', '536')),
    'outp.query': Cmd('OUTP?', 'RF output state', '0 or 1 (reply format UNVERIFIED; never overridable)', kind='query', risk='output', verified=False,
                      ref=_r(':OUTPut<hw>[:STATe]', '536')),
    'mod.off': Cmd('MOD:ALL:STAT 0', 'All modulation off', 'Switches every modulation off', kind='set', readback='mod.query', verified=False,
                   ref=_r('[:SOURce<hw>]:MODulation[:ALL][:STATe]', '614')),
    'mod.query': Cmd('MOD:ALL:STAT?', 'Modulation state', '0 or 1 (reply format UNVERIFIED)', kind='query', verified=False,
                     ref=_r('[:SOURce<hw>]:MODulation[:ALL][:STATe]', '614')),
    'unit.dbm': Cmd('UNIT:POW DBM', 'Level unit dBm', 'Every level command and reply in dBm (the *RST value)', kind='set', readback='unit.query', verified=False,
                    ref=_r(':UNIT:POWer', '817')),
    'unit.query': Cmd('UNIT:POW?', 'Level unit', 'V, DBUV or DBM (reply text UNVERIFIED)', kind='query', verified=False, ref=_r(':UNIT:POWer', '817')),
    'freq.mode.cw': Cmd('FREQ:MODE CW', 'Frequency mode CW', 'Fixed frequency (no sweep / list)', kind='set', readback='freq.mode.query', verified=False,
                        ref=_r('[:SOURce<hw>]:FREQuency:MODE', '701 and 702')),
    'freq.mode.query': Cmd('FREQ:MODE?', 'Frequency mode', 'CW (or FIX, a synonym; reply text UNVERIFIED)', kind='query', verified=False,
                           ref=_r('[:SOURce<hw>]:FREQuency:MODE', '701 and 702')),
    'pow.mode.cw': Cmd('POW:MODE CW', 'Level mode CW', 'Constant level (no level sweep)', kind='set', readback='pow.mode.query', verified=False,
                       ref=_r('[:SOURce<hw>]:POWer:MODE', '747')),
    'pow.mode.query': Cmd('POW:MODE?', 'Level mode', 'CW (or FIX, a synonym; reply text UNVERIFIED)', kind='query', verified=False, ref=_r('[:SOURce<hw>]:POWer:MODE', '747')),
    'freq.set': Cmd('FREQ {hz:.12g}', 'CW frequency', 'Hz; the range depends on the frequency option (p. 703)', placeholders={'hz': Placeholder('float', '.12g', 1e9)},
                    kind='set', readback='freq.query', verified=False, ref=_r('[:SOURce<hw>]:FREQuency[:CW|FIXed]', '702 and 703')),
    'freq.query': Cmd('FREQ?', 'CW frequency', 'Hz (includes FREQ:OFFS / FREQ:MULT, p. 704)', kind='query', verified=False,
                      ref=_r('[:SOURce<hw>]:FREQuency[:CW|FIXed]', '702 and 703')),
    'pow.set': Cmd('POW {dbm:.2f}', 'CW level', 'dBm, 0.01 dB steps; the range depends on the options (p. 753). POW:LIM caps the output without changing POW? (p. 746)',
                   placeholders={'dbm': Placeholder('float', '.2f', -30.0)}, kind='set', readback='pow.query', verified=False,
                   ref=_r('[:SOURce<hw>]:POWer[:LEVel][:IMMediate][:AMPLitude]', '752 and 753')),
    'pow.query': Cmd('POW?', 'CW level', 'dBm (includes POW:OFFS, p. 753)', kind='query', verified=False,
                     ref=_r('[:SOURce<hw>]:POWer[:LEVel][:IMMediate][:AMPLitude]', '752 and 753')),
    'freq.offs.query': Cmd('FREQ:OFFS?', 'Frequency offset', 'Downstream-instrument offset, Hz; must be 0 (the *RST value)', kind='query', verified=False,
                           ref=_r('[:SOURce<hw>]:FREQuency:OFFSet', '704')),
    'freq.mult.query': Cmd('FREQ:MULT?', 'Frequency multiplier', 'Downstream-instrument multiplier; must be 1 (the *RST value)', kind='query', verified=False,
                           ref=_r('[:SOURce<hw>]:FREQuency:MULTiplier', '704')),
    'pow.offs.query': Cmd('POW:OFFS?', 'Level offset', 'Downstream-instrument offset, dB; must be 0 (the *RST value)', kind='query', verified=False,
                          ref=_r('[:SOURce<hw>]:POWer[:LEVel][:IMMediate]:OFFSet', '752')),
    'pow.limit.query': Cmd('POW:LIM?', 'Level limit', 'Maximum RF output level, dBm. Not changed by *RST (factory preset 30); read only, never set by this driver',
                           kind='query', verified=False, ref=_r('[:SOURce<hw>]:POWer:LIMit[:AMPLitude]', '746')),
    'rosc.set': Cmd('ROSC:SOUR {src}', 'Reference oscillator source', 'INT or EXT. Not changed by *RST (factory preset INT)',
                    placeholders={'src': Placeholder('enum', '', 'EXT', enum=REF_SOURCES)}, kind='set', readback='rosc.query', verified=False,
                    ref=_r('[:SOURce]:ROSCillator:SOURce', '756')),
    'rosc.query': Cmd('ROSC:SOUR?', 'Reference oscillator source', 'INT or EXT (reply text UNVERIFIED)', kind='query', verified=False,
                      ref=_r('[:SOURce]:ROSCillator:SOURce', '756')),
}

COMMANDS['reset'] = cmdreg.reset_cmd(False, _r('*RST (equivalent to SYSTem:PRESet)', '490 and 491'),
                                     note='RF output OFF, CW, -30 dBm, modulation off. The reference source and the level limit are NOT reset (p. 746, 756)')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, _r('*OPC?', '489'))


# ---- bench records (bench-first driver workflow, NOTES.md; tools/bench/records/README.md): the real reply each command gave on the owner's unit (serial 124249,
# firmware 5.40.102.30, GPIB1::28).  This does NOT flip `verified` by itself (that also needs a driver_verify pass); it puts the recorded evidence next to the page in `ref`.
def _bench(table):
    import dataclasses
    for key, text in table.items():
        c = COMMANDS[key]
        COMMANDS[key] = dataclasses.replace(c, ref=f'{c.ref}; BENCH {text}')


_B = '2026-11-05 sma100b_bench'
_bench({
    'idn.query': f'{_B} step 1: "Rohde&Schwarz,SMA100B,1419.8888K02/124249,5.40.102.30"',
    'opt.query': f'{_B} step 1: "SMAB-B35,SMAB-B86,SMAB-B93,SMAB-B131,SMAB-B709,SMAB-K720" (no quotes)',
    'err.query': f'{_B} steps 1-3: \'0,"No error"\'; out of range: \'-222,"Data out of range;:SOURce1:FREQuency:CW 1000000000000 (IdPDbFreq,...)"\' (detail after ";")',
    'status.clear': f'{_B} step 2: accepted (queue 0 after)',
    'reset': f'{_B} step 2: *RST accepted; afterwards 1 GHz, -30 dBm, RF 0, CW, DBM, MOD 0, offsets 0 / 1 / 0; ROSC EXT and POW:LIM 20 unchanged (as p. 746 / 756)',
    'opc.query': f'{_B} step 2: "1" at once after *RST / *CLS',
    'selftest': f'{_B} step 2: "0" after 4.4 s',
    'outp.on': f'{_B} step 3: OUTP? 1', 'outp.off': f'{_B} steps 2-3: OUTP? 0', 'outp.query': f'{_B} steps 1-3: "0" / "1"',
    'mod.off': f'{_B} step 2: MOD:ALL:STAT? 0', 'mod.query': f'{_B} steps 1-2: "0"',
    'unit.dbm': f'{_B} step 2: UNIT:POW? DBM', 'unit.query': f'{_B} steps 1-2: "DBM"',
    'freq.mode.cw': f'{_B} step 2: FREQ:MODE? CW', 'freq.mode.query': f'{_B} steps 1-2: "CW"',
    'pow.mode.cw': f'{_B} step 2: POW:MODE? CW', 'pow.mode.query': f'{_B} steps 1-2: "CW"',
    'freq.set': f'{_B} step 2: FREQ 1000000000 -> FREQ? 1000000000; FREQ 1e+12 -> FREQ? unchanged + -222',
    'freq.query': f'{_B} steps 1-3: plain integer Hz ("500013", "1000000000")',
    'pow.set': f'{_B} step 2: POW -30.00 -> POW? -30', 'pow.query': f'{_B} steps 1-3: "-30", "-3.46787486224656" (full float)',
    'freq.offs.query': f'{_B} steps 1-2: "0"', 'freq.mult.query': f'{_B} steps 1-2: "1"', 'pow.offs.query': f'{_B} steps 1-2: "0"',
    'pow.limit.query': f'{_B} steps 1-3: "20" (dBm; survives *RST)',
    'rosc.query': f'{_B} steps 1-3: "EXT" (survives *RST)',
    # rosc.set: NOT sent on the bench (the unit stays on EXT); its driver_verify sample is EXT so a run there does not move the reference.
})

class RSSMA100B(SurpriseMixin, Instrument):
    MODEL = 'R&S SMA100B'
    IDN_MATCH = ('SMA100B',)
    DEFAULT_ADDRESS = 28                  # factory preset (p. 788)
    DEFAULT_TIMEOUT = 10.0
    SELFTEST_TIMEOUT = 120.0              # a choice of this driver: the manual gives no time for *TST?
    RESET_OPC_TIMEOUT = 30.0
    COMMANDS = COMMANDS

    output_off_confirmed = False
    options: tuple = ()
    ref_source = ''
    level_limit_dbm: float | None = None

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

    def identify(self):
        return self.query_retry('idn.query', attempts=2).strip()

    # ---- connection --------------------------------------------------------------------------------------------------------------------------
    def connect(self, address=None):
        """Re-target the transport to the GPIB address (given here, at construction, or 28), open, check *IDN? says SMA100B, *CLS, RF OFF (confirmed), error
        queue empty, then read the state *RST does not touch (reference source, level limit) and the options. Nothing else is changed."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=True)
        try:
            self.send('status.clear')
            self.output(False)
            self.check_errors('connect')
            self.read_fixed_state()
        except Exception:
            self.close()
            raise
        return self

    def read_fixed_state(self):
        """Options, reference source and level limit (read only). Logged so the command log says what the run used."""
        self.options = tuple(o.strip() for o in self.query_retry('opt.query', attempts=2).strip().strip('"').split(',') if o.strip())
        self.ref_source = self.reference_source()
        self.level_limit_dbm = self.level_limit()
        self.log.add('--', f'reference {self.ref_source}, level limit {self.level_limit_dbm:g} dBm, options {",".join(self.options) or "none"}', self.label)
        return self.ref_source, self.level_limit_dbm, self.options

    # ---- error queue -------------------------------------------------------------------------------------------------------------------------
    def check_errors(self, context=''):
        """SYST:ERR? once (it removes the entry it returns, so it is not retried). Raise with the entry when the queue is not empty."""
        reply = self.ask('err.query').strip()
        if not self.ERR_CLEAN(reply):
            raise InstrumentError(f'{self.MODEL} reported an error{" (" + context + ")" if context else ""}: {reply}')

    # ---- RF output ---------------------------------------------------------------------------------------------------------------------------
    def output(self, on: bool):
        """OUTP ON / OFF, confirmed with OUTP?. An unconfirmed OFF is a SafetyError."""
        self.send('outp.on' if on else 'outp.off')
        state = self.ask('outp.query').strip()
        if _num(state) != (1.0 if on else 0.0):
            if on:
                raise InstrumentError(f'{self.MODEL} did not confirm RF ON (OUTP? -> {state!r})')
            raise SafetyError(f'{self.MODEL} did not confirm RF OFF (OUTP? -> {state!r}); check the front panel')
        if not on:
            self.output_off_confirmed = True

    def is_output_on(self) -> bool:
        return _num(self.query_retry('outp.query', attempts=2)) == 1.0

    # ---- known state -------------------------------------------------------------------------------------------------------------------------
    def _set_word(self, key, query, accept, what):
        self.send(key)
        got = self.ask(query).strip().strip('"').upper()
        if not any(got.startswith(a) for a in accept):
            raise InstrumentError(f'{self.MODEL} {what}: reports {got!r}, expected {" or ".join(accept)}')
        return got

    def _set_flag(self, key, query, want, what):
        self.send(key)
        got = self.ask(query).strip()
        if _num(got) != want:
            raise InstrumentError(f'{self.MODEL} {what}: reports {got!r}, expected {want:g}')

    def cw_setup(self):
        """dBm units, CW frequency and level modes, all modulation off, then confirm no downstream offset / multiplier. Every setting read back."""
        self._set_word('unit.dbm', 'unit.query', ('DBM',), 'level unit')
        self._set_word('freq.mode.cw', 'freq.mode.query', ('CW', 'FIX'), 'frequency mode')
        self._set_word('pow.mode.cw', 'pow.mode.query', ('CW', 'FIX'), 'level mode')
        self._set_flag('mod.off', 'mod.query', 0.0, 'modulation')
        self.confirm_no_offsets()
        self.check_errors('CW set-up')

    def confirm_no_offsets(self):
        """FREQ:OFFS? 0, FREQ:MULT? 1, POW:OFFS? 0, so FREQ? / POW? are the real output (p. 704, 752). Raises otherwise (the driver does not change them:
        *RST does)."""
        checks = (('freq.offs.query', 0.0, 'frequency offset'), ('freq.mult.query', 1.0, 'frequency multiplier'), ('pow.offs.query', 0.0, 'level offset'))
        for key, want, what in checks:
            got = _num(self.query_retry(key, attempts=2))
            if got is None or not math.isclose(got, want, abs_tol=1e-9):
                raise InstrumentError(f'{self.MODEL} {what} is {got!r}, must be {want:g}: the displayed value would not be the output. Reset the generator (*RST) first')

    def _reset_extra(self):
        return [('RF OFF confirmed (OUTP OFF, OUTP?)', lambda: self.output(False)),
                ('dBm, CW, modulation off, no offsets', self.cw_setup),
                ('reference source and level limit read', lambda: '{} / {:g} dBm'.format(*self.read_fixed_state()[:2]))]

    # ---- reference oscillator / limit ----------------------------------------------------------------------------------------------------------
    def reference_source(self) -> str:
        got = self.query_retry('rosc.query', attempts=2).strip().strip('"').upper()
        for src in REF_SOURCES:
            if got.startswith(src):
                return src
        raise InstrumentError(f'{self.MODEL} reference source: unexpected reply {got!r}')

    def set_reference(self, source):
        """'INT' or 'EXT' (p. 756), read back. With EXT the error queue shows whether the generator locked (checked here)."""
        src = str(source).strip().upper()[:3]
        if src not in REF_SOURCES:
            raise InstrumentError(f'reference source must be one of {REF_SOURCES}')
        self.send('rosc.set', src=src)
        got = self.reference_source()
        if got != src:
            raise InstrumentError(f'{self.MODEL} reference source: set {src}, reports {got}')
        self.check_errors(f'reference {src}')
        self.ref_source = got
        return got

    def level_limit(self) -> float:
        got = _num(self.query_retry('pow.limit.query', attempts=2))
        if got is None:
            raise InstrumentError(f'{self.MODEL} POW:LIM? gave no number')
        return got

    # ---- frequency / level ---------------------------------------------------------------------------------------------------------------------
    def set_frequency(self, hz):
        """CW frequency in Hz: written once, read back with FREQ?, then the error queue (an out-of-range value is an error there)."""
        hz = float(hz)
        if not math.isfinite(hz) or hz <= 0:
            raise InstrumentError(f'frequency {hz!r} Hz is not a positive number')
        reply = self._set_and_explain('freq.set', hz, 'hz', FREQ_TOL_HZ)
        return _num(reply)

    def set_level(self, dbm):
        """CW level in dBm. Refused BEFORE anything is sent when it is above POW:LIM? (the limit caps the output while POW? still reads the asked level, p. 746)."""
        dbm = round(float(dbm), 2)
        if not math.isfinite(dbm):
            raise InstrumentError(f'level {dbm!r} dBm is not a number')
        limit = self.level_limit()
        self.level_limit_dbm = limit
        if dbm > limit + 1e-9:
            raise InstrumentError(f'{self.MODEL}: {dbm:g} dBm is above the level limit {limit:g} dBm (POW:LIM?): the output would be capped while POW? reads '
                                  f'{dbm:g}. Raise the limit on the front panel only if the set-up allows it')
        reply = self._set_and_explain('pow.set', dbm, 'dbm', LEVEL_TOL_DB)
        return _num(reply)

    def _set_and_explain(self, key, value, name, tol):
        """set_checked; when the read-back does not match, the error queue is read once so the generator's own reason (e.g. -222 Data out of range) is in
        the message and is not left in the queue for a later command."""
        try:
            return self.set_checked(key, value, name=name, tol=tol)
        except InstrumentError as exc:
            try:
                reply = self.ask('err.query').strip()
            except Exception:
                raise exc from None
            if self.ERR_CLEAN(reply):
                raise
            raise InstrumentError(f'{exc} (error queue: {reply})') from exc

    def wait_done(self, timeout=None):
        """*OPC? (read only): every command before it has finished (p. 489)."""
        prev = getattr(self.t, 'timeout', None)
        if timeout:
            self.t.set_timeout(timeout)
        try:
            reply = self.query_retry('opc.query', attempts=2).strip()
        finally:
            if timeout:
                self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        if _num(reply) != 1.0:
            raise InstrumentError(f'{self.MODEL} *OPC? answered {reply!r}')

    def setup(self, hz, dbm):
        """One CW point: frequency, level (limit checked first), wait for completion. The RF state is not changed: switch it with output()."""
        f = self.set_frequency(hz)
        lv = self.set_level(dbm)
        self.wait_done()
        return f, lv

    def read_setting(self):
        """(frequency Hz, level dBm, rf_on) as the generator reports them (read only)."""
        return (_num(self.query_retry('freq.query', attempts=2)), _num(self.query_retry('pow.query', attempts=2)), self.is_output_on())

    # ---- self-test ---------------------------------------------------------------------------------------------------------------------------
    def self_test(self):
        """*TST? -> 0 no error, > 0 error code (p. 492). RF is switched OFF first and confirmed after. Returns (passed, reply)."""
        self.output(False)
        self.t.set_timeout(self.SELFTEST_TIMEOUT)
        try:
            reply = self.ask('selftest').strip()
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        code = _num(reply)
        if code is None:
            raise InstrumentError(f'Unexpected *TST? reply: {reply!r}')
        self.output(False)
        return code == 0, reply

    def cleanup(self):
        """Best effort: RF OFF (confirmed with OUTP?), then the front panel back to local. Never raises."""
        try:
            self.send('outp.off')
            self.output_off_confirmed = _num(self.ask('outp.query')) == 0.0
        except Exception:
            self.output_off_confirmed = False
        try:
            self.t.go_local()
        except Exception:
            pass
