"""Fluke 5700A multifunction calibrator (original 5700A, as a source for DMM procedures), IEEE-488 or RS-232.

STATUS: written from the manual only, NOT yet met on a real instrument.  Every COMMANDS entry is verified=False until the bench session of the bench-first workflow
(NOTES.md 'Bench-first driver workflow') has recorded a real reply and driver_verify has passed.

Source: '5700A/5720A Series II Multi-Function Calibrator Remote Programming Reference Guide', PN 601655, May 1996 (10 pages; `ref` below is its printed page number).
THAT GUIDE IS FOR THE SERIES II.  The lab's unit is an ORIGINAL 5700A (owner, 2026-11-03).  The command syntax is expected to be the same for the commands used here
(OUT / OPER / STBY / EXTSENSE / FAULT? ...), but the guide does not say so and no original-5700A remote reference was available: every command is therefore UNVERIFIED for the
original unit, and so is every reply format.  The uncertainty sheet (specs/standards/fluke_5700a_standard.json) is the original 5700A's (Service Manual PN 791996).

What the guide states (and this driver uses):
  * Syntax (p. 3-4): a space between a command and its parameter, commas between parameters ('OUT 1 V, 100 HZ'), units A, V, HZ, OHM, multipliers K, M (milli), MA (mega), U; commands
    may be combined with ';'; the unit sends LF with EOI.  Responses are as described for IEEE-488 and for RS-232 in COMPUTER mode; in RS-232 TERMINAL mode they are descriptive text
    for an operator, so the serial port must be in COMPUTER mode (SP_SET, front panel).  This driver does not send SP_SET (it would change the instrument's serial set-up).
  * OUT <value unit>[, <frequency HZ>] sets the output and a new error-mode reference; 'OUT 100 MV' selects 100 mV dc (p. 4, p. 15); the output stays in standby until OPER (p. 15).
  * OPER / STBY (p. 15, 18); ISR? returns the Instrument Status Register: bit 0 OPER, bit 2 EXSENS (external sense), bit 4 RCOMP (two-wire compensation), bit 12 SETTLED (pp. 14, 24).
  * EXTSENSE ON|OFF (p. 13) opens / closes the internal SENSE-to-OUTPUT connection; RCOMP ON|OFF (p. 16) two-wire compensation; CUR_POST NORMAL|AUX|IB5725 (p. 12).
  * FAULT? returns the most recent fault code from the fault queue (p. 13; the code for an empty queue is not stated: 0 is assumed), EXPLAIN? <code> its text (p. 13).
  * *RST power-up state (p. 16), *CLS (p. 12), *OPC? (p. 15), *IDN? (p. 13): four strings 'Fluke, model, serial, software revisions'.
  * REMOTE / LOCAL (serial only, pp. 14, 16); on IEEE-488 the unit goes remote when addressed.
NOT used: CAL_*, FORMAT, DIAG, SP_SET, CLOCK, RPT_STR, PUD (calibration, memory and configuration commands).  The 5700A has no capacitance and no thermocouple output.
The 5725A amplifier is driven with BTYPE (VB5725 voltage / IB5725 current), CUR_POST IB5725, BOOST and RANGELCK (pp. 10, 12, 16), always with the output in standby; the 5725A has
its own cable to the 5700A and its own power switch (the program cannot see either: BOOST ON is read back from ISR? bit 3).
Writes are sent once, read back where a query exists, and never retried; only read-only queries (FAULT?, ISR?) may be retried.
"""
from __future__ import annotations

import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .transport import bus_of

RG = '5700A/5720A Series II Remote Programming Reference Guide PN 601655 (May 1996)'
ISR_OPER, ISR_EXSENS, ISR_RCOMP, ISR_SETTLED = 0, 2, 4, 12      # bit numbers of the Instrument Status Register (p. 24)
ISR_BOOST, ISR_RLOCK = 3, 5                                     # BOOST (auxiliary amplifier active) and RLOCK (range locked), same register


def _p(page, what=''):
    return f'{RG}, p. {page}' + (f' ({what})' if what else '')


def _f(sample=1.0, fmt='.9g'):
    return Placeholder('float', fmt, sample)


COMMANDS = {
    'oper.stby': Cmd('STBY', 'Output to standby', 'Puts the 5700A in standby (never overridable)', kind='set', readback='isr.query', risk='output', verified=False, ref=_p('18', 'STBY')),
    'oper.on': Cmd('OPER', 'Output to operate', 'Activates the output if it is in standby (never overridable)', kind='set', readback='isr.query', risk='output', verified=False, ref=_p('15', 'OPER')),
    'isr.query': Cmd('ISR?', 'Instrument status register', 'Bit 0 OPER, bit 2 EXSENS, bit 4 RCOMP, bit 12 SETTLED; the guide says the query reads and clears the register. Reply: a decimal integer '
                     '(not stated whether an extra response follows)', kind='query', risk='output', verified=False, ref=_p('14', 'ISR?') + '; bit list p. 24'),
    'out.volts.dc': Cmd('OUT {volts:.9g} V, 0 HZ', 'DC volts', 'Sets a dc voltage; the output stays in standby until OPER. The explicit "0 HZ" follows the suite\'s rule for DC outputs; the guide\'s own '
                        'dc example is "OUT 100 MV" (no frequency), so whether ", 0 HZ" is accepted is UNVERIFIED', placeholders={'volts': _f(1.0)}, kind='set', verified=False, ref=_p('15', 'OUT')),
    'out.volts.ac': Cmd('OUT {volts:.9g} V, {hz:.9g} HZ', 'AC volts', 'Sets an ac voltage (rms) and frequency', placeholders={'volts': _f(1.0), 'hz': _f(1000.0)}, kind='set', verified=False, ref=_p('15', 'OUT')),
    'out.amps.dc': Cmd('OUT {amps:.9g} A, 0 HZ', 'DC current', 'Sets a dc current', placeholders={'amps': _f(0.001)}, kind='set', verified=False, ref=_p('15', 'OUT')),
    'out.amps.ac': Cmd('OUT {amps:.9g} A, {hz:.9g} HZ', 'AC current', 'Sets an ac current (rms) and frequency', placeholders={'amps': _f(0.001), 'hz': _f(1000.0)}, kind='set', verified=False, ref=_p('15', 'OUT')),
    'out.ohms': Cmd('OUT {ohms:.9g} OHM', 'Resistance', 'Selects a resistance value (the 5700A offers fixed values)', placeholders={'ohms': _f(100.0)}, kind='set', verified=False, ref=_p('15', 'OUT')),
    'out.query': Cmd('OUT?', 'Programmed output', 'Returns amplitude, units and frequency', kind='query', verified=False, ref=_p('15', 'OUT?')),
    'extsense': Cmd('EXTSENSE {state}', 'External sense', 'ON = external sense (4-wire resistance and the RTD points), OFF = sense connected internally',
                    placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback='isr.query', verified=False, ref=_p('13', 'EXTSENSE')),
    'rcomp': Cmd('RCOMP {state}', 'Two-wire compensation', 'Activates / deactivates the two-wire compensation circuitry (resistance)', placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))},
                 kind='set', readback='isr.query', verified=False, ref=_p('16', 'RCOMP')),
    'boost': Cmd('BOOST {state}', '5725A amplifier (BOOST)', 'Activates / deactivates the auxiliary amplifier (the 5725A); read back from ISR? bit 3. Used with the output in STANDBY',
                 placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback='isr.query', verified=False, ref=_p('6, 10', 'BOOST')),
    'btype': Cmd('BTYPE {amp}', 'Amplifier type', 'Selects the amplifier type for voltage boost (VB5725) or current boost (IB5725); the other types (VB5205, VB5215, IB5220) are not used',
                 placeholders={'amp': Placeholder('enum', '', 'VB5725', enum=('VB5725', 'IB5725'))}, kind='set', readback='btype.query', verified=False, ref=_p('5, 10', 'BTYPE')),
    'btype.query': Cmd('BTYPE?', 'Amplifier types', 'Returns the voltage-boost and current-boost types (two strings: VB<model>, IB<model>)', kind='query', verified=False, ref=_p('10', 'BTYPE?')),
    'rangelck': Cmd('RANGELCK {state}', 'Range lock', 'ON locks the present range (the DMM6500 manual sets the amplifier range lock ON, pp. 2-46, 2-48); read back from ISR? bit 5',
                    placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set', readback='isr.query', verified=False, ref=_p('6, 16', 'RANGELCK')),
    'curpost': Cmd('CUR_POST {post}', 'Current output terminals', 'NORMAL, AUX or IB5725 (the 5725A current amplifier); which post a current below 2.2 A needs on an original 5700A is UNVERIFIED',
                   placeholders={'post': Placeholder('enum', '', 'AUX', enum=('NORMAL', 'AUX', 'IB5725'))}, kind='set', readback='curpost.query', verified=False, ref=_p('12', 'CUR_POST')),
    'curpost.query': Cmd('CUR_POST?', 'Current output terminals query', 'Returns NORMAL, AUX or IB5725', kind='query', verified=False, ref=_p('12', 'CUR_POST?')),
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers (never overridable)', kind='set', risk='locked', verified=False, ref=_p('12', '*CLS')),
    'err.query': Cmd('FAULT?', 'Fault queue', 'The most recent fault code (an integer; the code of an empty queue is not stated, 0 assumed). Never overridable', kind='query', risk='locked', verified=False,
                     ref=_p('13', 'FAULT?')),
    'explain.query': Cmd('EXPLAIN? {code:d}', 'Fault text', 'A brief description of a fault code', placeholders={'code': Placeholder('int', 'd', 1)}, kind='query', verified=False, ref=_p('13', 'EXPLAIN?')),
    'remote': Cmd('REMOTE', 'Remote state (RS-232 only)', 'Places the 5700A in the remote state; serial only (IEEE-488: remote when addressed)', kind='set', verified=False, ref=_p('14, 20', 'REMOTE')),
    'local': Cmd('LOCAL', 'Local state (RS-232 only)', 'Returns to local; serial only', kind='set', verified=False, ref=_p('14, 20', 'LOCAL')),
}
COMMANDS['reset'] = cmdreg.reset_cmd(False, _p('16', '*RST: resets the calibrator to its default power-up state'), note='*RST; the output is confirmed in STANDBY afterwards (ISR? bit 0)')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, _p('15', '*OPC?: returns 1 when all pending remote operations are complete'))


def _bit(reply, n):
    """Bit n of the first integer of an ISR? reply."""
    token = str(reply).replace(',', ' ').split()[0]
    return bool(int(float(token)) >> n & 1)


class Fluke5700A(Instrument):
    MODEL = 'Fluke 5700A'
    IDN_MATCH = ('5700',)
    DEFAULT_TIMEOUT = 20.0
    COMMANDS = COMMANDS
    CANNOT = ('CAP',)                      # outputs the 5700A does not have (no capacitance): the engines send such a point to the operator's own standard
    standby_confirmed = False
    stale_errors = ()

    @property
    def bus(self) -> str:
        return getattr(self.t, 'bus', None) or bus_of(str(getattr(self.t, 'name', '') or ''))

    def open(self, verify_model=True):
        super().open(verify_model=verify_model)
        if self.bus == 'RS232':
            self.send('remote')                      # serial: enter the remote state (IEEE-488 goes remote when addressed)
        return self

    # ---- output state --------------------------------------------------------------------------------------------
    def isr(self, bit):
        return _bit(self.query_retry('isr.query', attempts=2, delay=0.3), bit)

    def standby(self):
        """STBY and confirm (ISR? bit 0 = 0). Raises SafetyError if the calibrator does not report standby."""
        self.send('oper.stby')
        if self.isr(ISR_OPER):
            raise SafetyError('Fluke 5700A did not confirm standby')

    def operate(self):
        """OPER and confirm (ISR? bit 0 = 1)."""
        self.send('oper.on')
        if not self.isr(ISR_OPER):
            raise InstrumentError('Fluke 5700A did not confirm OPERATE; output not verified')

    def is_operating(self):
        return self.isr(ISR_OPER)

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.send('oper.stby')
            self.standby_confirmed = not self.isr(ISR_OPER)
        except Exception:
            self.standby_confirmed = False

    def _reset_standby(self):
        self.standby()

    def _reset_extra(self):
        return [('output in STANDBY (STBY, ISR? bit 0 = 0)', self._reset_standby)]

    def wait_settled(self, timeout=60.0, poll=0.5):
        """After OPER: wait until the output reports SETTLED (ISR? bit 12) or raise. Read-only polling."""
        end = time.monotonic() + timeout
        while True:
            if self.isr(ISR_SETTLED):
                return
            if time.monotonic() >= end:
                raise InstrumentError(f'{self.label}: the output did not report SETTLED within {timeout:g} s')
            time.sleep(poll)

    # ---- outputs (NORMAL / AUX terminals) ---------------------------------------------------------------------------
    def set_output_volts(self, volts, frequency_hz=None, dc=False):
        if frequency_hz:
            self.send('out.volts.ac', volts=volts, hz=frequency_hz)
        else:
            self.send('out.volts.dc', volts=volts)

    _amp = None                              # 'V' or 'I' while the 5725A is active (set by amplifier_on)
    _locked = False                          # RANGELCK ON was sent (amplifier_lock)
    CURRENT_POST = 'NORMAL'                  # the DMM6500 manual's figures take current from the calibrator OUTPUT HI / LO (p. 2-30, 2-34, 2-37): UNVERIFIED for an original 5700A

    def _post(self, post):
        self.send('curpost', post=post)
        reply = self.ask('curpost.query').strip().upper()
        if not reply.startswith(post[:4]):
            raise InstrumentError(f'{self.label}: the current output post {post} was not accepted (CUR_POST? answered {reply!r})')

    def amplifier_on(self, kind):
        """PREPARE the 5725A, with the output in STANDBY and BEFORE the target output is set: stale faults cleared, BOOST OFF and RANGELCK OFF (a clean slate), BTYPE VB5725 (voltage) or IB5725
        (current, and CUR_POST IB5725). kind 'V' or 'I'. BOOST and the range lock are NOT sent here: both act on the PRESENT output (guide: RANGELCK 'locks the present range'; Operator Guide: an
        amplifier is selected for settings above the calibrator's range, and BOOST is for the others), so amplifier_activate() sends them after the target output is set (bench 2026-11-04:
        fault 860, "Can't Use Amplifier For This Output", at 10 A DC and 740 V / 50 kHz when BOOST ON / the lock came first)."""
        if self.isr(ISR_OPER):
            raise SafetyError(f'{self.label}: the 5725A is only switched in with the output in standby')
        stale = self._drain_faults()
        if stale:
            self.log.add('##', 'faults cleared before the amplifier was switched in: ' + '; '.join(r for r, _ in stale), self.label)
        self.send('boost', state='OFF')              # a clean slate: an earlier failed run can leave BOOST or the range lock ON, and a stale lock pins the wrong range
        self.send('rangelck', state='OFF')
        amp = 'VB5725' if kind == 'V' else 'IB5725'
        self.send('btype', amp=amp)
        if amp not in self.ask('btype.query').strip().upper():
            raise InstrumentError(f'{self.label}: the amplifier type {amp} was not accepted (BTYPE? did not list it)')
        if kind == 'I':
            self._post('IB5725')
        self._amp, self._locked = kind, False

    def amplifier_activate(self):
        """After the TARGET output is set, still in STANDBY: if ISR? bit 3 shows no amplifier active (it is selected by itself for settings above the 5700A's own range, so often it already is),
        BOOST ON; then a fault check. For the 10 A current points RANGELCK ON as well (DMM6500 Calibration Manual pp. 2-46, 2-48; voltage is not locked there), with its own fault check.
        Each fault check names the command that was refused."""
        if self._amp is None:
            return
        if not self.isr(ISR_BOOST):
            self.send('boost', state='ON')
            self.check_error('BOOST ON')
        if self._amp == 'I':
            self.send('rangelck', state='ON')
            self._locked = True
            self.check_error('RANGELCK ON')

    def amplifier_confirm(self):
        """With the amplifier output set (and locked, for the 10 A points) and the output still in STANDBY: ISR? must show BOOST (bit 3) and, when locked, RLOCK (bit 5). On a failure the message gives the raw ISR? value and the fault queue
        (the bit meaning is from the Series II guide, UNVERIFIED for an original 5700A)."""
        reply = str(self.query_retry('isr.query', attempts=2, delay=0.3)).strip()
        token = reply.replace(',', ' ').split()[0]
        value = int(float(token))
        wanted = (('BOOST (bit 3)', ISR_BOOST), ('range lock (bit 5)', ISR_RLOCK)) if self._locked else (('BOOST (bit 3)', ISR_BOOST),)
        missing = [name for name, bit in wanted if not value >> bit & 1]
        if not missing:
            return
        try:
            fault = self.read_error()
        except Exception as e:
            fault = f'unreadable ({e})'
        raise InstrumentError(f'{self.label}: the amplifier is not active: {" and ".join(missing)} is not set in ISR? (answered {reply!r}, binary {value:016b}; FAULT? answered {fault!r}). '
                              'Is the 5725A cabled to the 5700A, powered on and not in standby?')

    def amplifier_off(self):
        """BOOST OFF, RANGELCK OFF and the current post back to NORMAL after a current boost. Call with the output in STANDBY.
        ISR? bits 3 and 5 are NOT required to clear: on the bench (2026-11-04, 740 V at 50 kHz) bit 3 was still 1 after BOOST OFF, because the 5700A selects the amplifier by itself for an output
        above its own range (Operator Guide, 'B' key), so the bit follows the output setting, not the BOOST state. The raw ISR? value is written to the command log for the bench session."""
        kind, self._amp = self._amp, None
        self._locked = False
        self.send('boost', state='OFF')
        self.send('rangelck', state='OFF')           # always: harmless when not locked, and it clears a lock left by a failed step
        if kind == 'I':
            self._post(self.CURRENT_POST)
        value = int(float(str(self.query_retry('isr.query', attempts=2, delay=0.3)).replace(',', ' ').split()[0]))
        self.log.add('##', f'ISR? after the amplifier was taken out: {value} (binary {value:016b}); BOOST bit {value >> ISR_BOOST & 1}, RLOCK bit {value >> ISR_RLOCK & 1} (not required to be 0)', self.label)

    def set_output_amps(self, amps, frequency_hz=None, dc=False):
        if self._amp != 'I':                  # with the 5725A current boost active the post is already IB5725
            self._post(self.CURRENT_POST)
        if frequency_hz:
            self.send('out.amps.ac', amps=amps, hz=frequency_hz)
        else:
            self.send('out.amps.dc', amps=amps)

    def set_output_ohms(self, ohms):
        self.send('out.ohms', ohms=ohms)

    def set_compensation(self, mode: str):
        """The engines' impedance-compensation call. WIRE4 = external sense ON (EXTSENSE ON, read back from ISR? bit 2); NONE = EXTSENSE OFF. Two-wire compensation (RCOMP) is left OFF."""
        on = mode != 'NONE'
        self.send('extsense', state='ON' if on else 'OFF')
        if self.isr(ISR_EXSENS) != on:
            raise InstrumentError(f'{self.label}: external sense {"ON" if on else "OFF"} was not accepted (ISR? bit 2)')
        self.send('rcomp', state='OFF')
        if self.isr(ISR_RCOMP):
            raise InstrumentError(f'{self.label}: two-wire compensation is still on after RCOMP OFF (ISR? bit 4)')

    # ---- faults ---------------------------------------------------------------------------------------------------------
    def read_error(self) -> str:
        return self.ask('err.query').strip()

    def _drain_faults(self, limit=8):
        """Read FAULT? until it answers 0 (at most `limit` reads): [(reply, code), ...]. Read-only."""
        found = []
        for _ in range(limit):
            reply = self.read_error()
            code = self._error_code(reply)
            if code in (0, None):
                break
            found.append((reply, int(code)))
        return found

    def check_error(self, context=''):
        """Raise if the fault queue holds a code (FAULT? answers 0 when empty: UNVERIFIED): every queued fault is read and reported, each with the EXPLAIN? text when the calibrator gives one."""
        faults = self._drain_faults()
        if not faults:
            return
        parts = []
        for reply, code in faults:
            try:
                why = self.ask('explain.query', code=code).strip()
            except Exception:
                why = ''
            parts.append(f'fault {reply}{" - " + why if why else ""}')
        raise InstrumentError(f'{self.label} rejected the setting{" (" + context + ")" if context else ""}: ' + '; '.join(parts) + f'. Last commands: {self._recent()}')

    def _recent(self, n=18):
        """The last n wire lines of this instrument ('>>' sent, '<<' answered), for a fault message: what was sent, in order, when the 5700A refused."""
        lines = [f'{d} {t}' for _, inst, d, t in self.log.entries if inst == self.label and d in ('>>', '<<')]
        return ' | '.join(lines[-n:])

    def clear_status(self):
        self.send('status.clear')

    def operate_unverified(self):
        self.send('oper.on')

    def standby_quiet(self):
        try:
            self.send('oper.stby')
        except Exception:
            pass

    @classmethod
    def unverified_summary(cls):
        reg = cmdreg.merge_commands(cls)
        return (f'5700A remote commands: {sum(1 for c in reg.values() if c.verified)} of {len(reg)} registered commands are verified. They come from the Series II Remote Programming Reference Guide '
                '(PN 601655); the lab unit is an original 5700A, so the syntax and every reply format are UNVERIFIED until a bench session. The program reads the fault queue after every '
                'setting and never operates after a rejection.')
