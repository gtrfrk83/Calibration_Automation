"""HP 8902A: entering the calibration-factor table of a power sensor (11722A or another), logic only (no UI toolkit).

What it does: the reference cal factor (the 50 MHz value from the sensor label) and up to 16 frequency / cal-factor pairs go into the 8902A's non-volatile
Automatic Cal Factor table with the driver's locked, verified commands (37.3SP <pct> CF and 37.3SP <MHz> MZ <pct> CF; Operating and Calibration Manual p. 3-75 to 3-78 / 124 to 127
and 3-87 / 136).  THIS CHANGES THE STORED CAL-FACTOR TABLE OF THE RECEIVER.  The table survives power-off and the manual has no undo.

Entry rules of the manual (rendered p. 3-82 / 131, "Specifications for Cal-Factor Entry"): RF frequency 0 to 42 GHz in 50 kHz steps, cal factor 40 to 120 % in 0.1 % steps, 17 entries
in the first table (the reference + 16 pairs).  The receiver puts the entries in order by itself; entering a frequency again replaces it; 0 % removes it.  So there is no ordering
rule to check, only: range, resolution, no duplicate frequency, at most 16 pairs.  (At least one pair: with the reference alone the receiver still shows Error 15, p. 3-82.)

Sequence (each write is sent ONCE and never repeated; every write is read back and compared; the first mismatch or error stops the run):
  read     M4, 37.4SP (entries incl. the reference), 37.5SP CF (reference), 37.6SP FR / CF per pair   -- reads only; 37.0SP afterwards (automatic cal factors again)
  confirm  the operator types ENTER (nothing is sent to the receiver before it)
  write    reference (read back with 37.5SP CF), then each stale entry NOT in the new table -> 0 % (count must drop by one), then each pair in ascending order (count must grow by
           one, or stay if the frequency was already there)
  verify   the whole table is read back and compared with the plan, pass / fail per entry
The table-clear special functions (37.7 / 37.9) are NEVER sent: stale entries are removed one by one with 0 %.
UNVERIFIED on the real receiver: how the value behind 37.4SP / 37.5SP / 37.6SP is returned over HP-IB (the manual's own example program reads it with ENTER; see drivers/hp_8902a.py:
cf.recall.freq, cf.recall.ref, cf.display are verified=False) and the count convention (37.4SP includes the reference: pairs = count - 1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INSTRUMENT = 'HP 8902A cal factors'
CONFIRM_ENTER = 'ENTER'
MAX_PAIRS = 16
PCT_MIN, PCT_MAX, PCT_STEP = 40.0, 120.0, 0.1
MHZ_MAX, KHZ_STEP = 42000.0, 50
REF_TOL_PCT = 0.05                       # half the 0.1 % resolution
FREQ_TOL_MHZ = 0.0005
NOTICE = ('This CHANGES the cal-factor table stored in the 8902A (non-volatile: it survives power-off, and the manual has no undo). Entries of the table that are not in your list are '
          'removed one by one (entered as 0 %) unless you untick the option; the table-clear functions are never sent. Nothing is sent until you type ENTER.')
SENSOR_CHECKLIST = (('Sensor', 'The power sensor (11722A or other) is connected to the 8902A SENSOR input and its model and serial number are the ones on the cal-factor label you typed from.'),
                    ('Mode', 'The program selects RF POWER (M4) itself. Microwave sensor modules (27.1SP) are not handled by this procedure.'),
                    ('Error 15', 'Error 15 shows until the entries are made and may be disregarded during entry (manual p. 3-82).'))


class CalFactorError(Exception):
    """Anything that stops the procedure; the message is for the operator."""


class ConfirmationRequired(CalFactorError):
    """The typed confirmation is missing or wrong: nothing was sent."""


class EntryStopped(CalFactorError):
    """A write, a read-back or a check failed: the run stopped, the failed write was NOT repeated, the table in the receiver may be partly changed."""


@dataclass
class Table:
    reference: float
    pairs: list = field(default_factory=list)            # [(MHz, %)] ascending

    def keys(self):
        return {khz(f) for f, _ in self.pairs}


@dataclass
class Check:
    kind: str                # 'reference' | 'pair' | 'extra' | 'count'
    mhz: float | None
    entered: float | None
    read: float | None
    ok: bool
    note: str = ''


@dataclass
class Result:
    ok: bool
    checks: list
    existing_after: dict
    status: str
    lines: list = field(default_factory=list)


def khz(mhz) -> int:
    return int(round(float(mhz) * 1000))


# ------------------------------------------------------------------------------------------------------------------------------- parsing and validation
_NUM = re.compile(r'^\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*([A-Za-z%]*)\s*$')


def parse_percent(text):
    m = _NUM.match(str(text).replace(',', '.'))
    if not m or m.group(2) not in ('', '%'):
        raise ValueError(f'{str(text).strip()!r} is not a percentage (type for example 98.5)')
    return float(m.group(1))


def parse_mhz(text):
    """MHz; a GHz / MHz / kHz suffix is accepted and converted (the value is kept in MHz)."""
    m = _NUM.match(str(text).replace(',', '.'))
    unit = (m.group(2).lower() if m else '')
    if not m or unit not in ('', 'mhz', 'ghz', 'khz', 'm', 'g', 'k'):
        raise ValueError(f'{str(text).strip()!r} is not a frequency (type MHz, for example 1000, or 2 GHz)')
    return float(m.group(1)) * {'': 1.0, 'm': 1.0, 'mhz': 1.0, 'g': 1000.0, 'ghz': 1000.0, 'k': 1e-3, 'khz': 1e-3}[unit]


def percent_problem(pct, what):
    if not PCT_MIN <= pct <= PCT_MAX:
        return f'{what}: {pct:g} % is outside {PCT_MIN:g} to {PCT_MAX:g} % (manual p. 3-82)'
    if abs(pct * 10 - round(pct * 10)) > 1e-6:
        return f'{what}: {pct:g} % is finer than the 0.1 % resolution of the entry'
    return None


def frequency_problem(mhz, what):
    if not 0 < mhz <= MHZ_MAX:
        return f'{what}: {mhz:g} MHz is outside 0 to 42 GHz (manual p. 3-82)'
    if abs(mhz * 1000 - round(mhz * 1000)) > 1e-6 or khz(mhz) % KHZ_STEP:
        return f'{what}: {mhz:g} MHz is not on the 50 kHz step of the entry'
    return None


def validate(reference_text, rows):
    """(Table | None, problems).  `rows` are (frequency text, cal-factor text) as typed; a row with both cells empty is skipped.  Nothing is sent anywhere; every problem is listed."""
    problems = []
    ref = None
    try:
        ref = parse_percent(reference_text)
        p = percent_problem(ref, 'Reference cal factor')
        if p:
            problems.append(p)
    except ValueError as exc:
        problems.append(f'Reference cal factor: {exc}')
    pairs, seen = [], {}
    for n, (ftext, ptext) in enumerate(rows, 1):
        if not str(ftext).strip() and not str(ptext).strip():
            continue
        what = f'Row {n}'
        if not str(ftext).strip() or not str(ptext).strip():
            problems.append(f'{what}: both the frequency and the cal factor are needed')
            continue
        try:
            f = parse_mhz(ftext)
            c = parse_percent(ptext)
        except ValueError as exc:
            problems.append(f'{what}: {exc}')
            continue
        bad = [x for x in (frequency_problem(f, what), percent_problem(c, what)) if x]
        problems += bad
        if bad:
            continue
        if khz(f) in seen:
            problems.append(f'{what}: {f:g} MHz is already in row {seen[khz(f)]} (a frequency can be entered once)')
            continue
        seen[khz(f)] = n
        pairs.append((round(f, 6), c))
    if len(pairs) > MAX_PAIRS:
        problems.append(f'{len(pairs)} frequency / cal-factor pairs: the receiver holds {MAX_PAIRS} (plus the reference)')
    if not pairs and not any('Row' in p for p in problems):
        problems.append('Enter at least one frequency / cal-factor pair: with the reference alone the 8902A still shows Error 15')
    if problems:
        return None, problems
    return Table(ref, sorted(pairs)), []


# ------------------------------------------------------------------------------------------------------------------------------------------- session
class Session:
    """One run on one connected HP8902A driver `rx`.  `audit` is an adjustment_audit.AuditStore with a started run.  `on_log(row)` gets every audit row."""

    def __init__(self, rx, audit, on_log=None):
        self.rx, self.audit, self.on_log = rx, audit, on_log
        self.existing = None             # {'count', 'reference', 'pairs'} as read before the entry
        self.entered = False

    def log(self, action, outcome='', detail='', step_id=''):
        row = self.audit.log(action, outcome, detail, step_id)
        if row and self.on_log:
            self.on_log(row, step_id)
        return row

    # ---- free reads
    def read_table(self, action='READ'):
        """Reads the table (and leaves the receiver on automatic cal factors again).  Raises CalFactorError when it cannot be read."""
        rx = self.rx
        try:
            data = rx.recall_cal_factor_table()
        except Exception as exc:
            self.log(action, 'FAILED', str(exc).splitlines()[0])
            self._restore()
            raise CalFactorError(f'The cal-factor table could not be read: {exc}\n\nNothing was written. Without a read-back the entry cannot be checked, so it is not started.') from exc
        self._restore()
        text = (f'{data["count"]} entries incl. the reference; reference {data["reference"]:g} %; ' + ', '.join(f'{f:g} MHz {c:g} %' for f, c in data['pairs'])
                if data['count'] >= 1 else 'table empty')
        self.log(action, 'OK', text)
        return data

    def _restore(self):
        try:
            self.rx.restore_automatic_cal_factors()
        except Exception as exc:                                               # noqa: BLE001 - reported, never repeated
            self.log('AUTO CAL FACTORS', 'COULD NOT CONFIRM', f'37.0SP: {str(exc).splitlines()[0]}; press AUTOMATIC OPERATION on the 8902A')

    def read_existing(self):
        try:
            fw = self.rx.read_special('42.0')
            self.log('FIRMWARE', 'OK', f'date code {fw:g}')
        except Exception as exc:                                               # noqa: BLE001 - information only
            self.log('FIRMWARE', 'NOT READ', str(exc).splitlines()[0])
        self.existing = self.read_table('READ TABLE')
        self.audit.set_status('IN_PROGRESS')
        return self.existing

    # ---- plan
    def plan(self, table, remove_stale=True):
        """(stale frequencies to remove (MHz), entries after the entry).  Raises CalFactorError when the result would not fit (nothing sent)."""
        if self.existing is None:
            raise CalFactorError('Read the table of the 8902A first (Read table).')
        have = {khz(f): f for f, _ in self.existing['pairs']}
        new = table.keys()
        stale = sorted(f for k, f in have.items() if k not in new) if remove_stale else []
        after = (set(have) - {khz(f) for f in stale}) | new
        if len(after) > MAX_PAIRS:
            raise CalFactorError(f'The table would hold {len(after)} pairs (the receiver holds {MAX_PAIRS}): the 8902A already has {len(have)} entries that are not in your list. '
                                 'Tick "Remove entries that are not in my list" or shorten the list.')
        return stale, len(after)

    # ---- the entry
    def enter(self, table, confirm, remove_stale=True):
        """Writes the table.  `confirm` must be exactly CONFIRM_ENTER or nothing at all is sent.  Returns a Result; raises EntryStopped at the first problem."""
        if confirm != CONFIRM_ENTER:
            self.log('CONFIRM', 'NOT CONFIRMED', f'the confirmation {CONFIRM_ENTER} was not typed; nothing was sent')
            raise ConfirmationRequired(f'Type {CONFIRM_ENTER} to confirm. Nothing was sent to the 8902A.')
        stale, after = self.plan(table, remove_stale)
        rx = self.rx
        have = {khz(f) for f, _ in self.existing['pairs']}
        self.log('CONFIRM', 'CONFIRMED', f'{CONFIRM_ENTER} typed; reference {table.reference:g} %, {len(table.pairs)} pairs, {len(stale)} stale entries to remove')
        self.audit.set_status('ENTERING')
        done = 0
        try:
            got = rx.enter_reference_cal_factor(table.reference)
            self.log('REFERENCE', 'OK', f'37.3SP {table.reference:g} CF; read back {got:g} %', 'REF')
            count = rx.cal_factor_count()
            self.log('COUNT', 'OK', f'{count} entries after the reference', 'REF')
            for f in stale:
                new_count = rx.remove_cal_factor(f)
                if new_count != count - 1:
                    raise EntryStopped(f'removing {f:g} MHz: the table has {new_count} entries, expected {count - 1}')
                count = new_count
                have.discard(khz(f))
                done += 1
                self.log('REMOVE', 'OK', f'{f:g} MHz entered as 0 %; {count} entries', f'-{khz(f)}')
            for f, c in table.pairs:
                want = count + (0 if khz(f) in have else 1)
                new_count = rx.enter_cal_factor(f, c)
                if new_count != want:
                    raise EntryStopped(f'entering {f:g} MHz {c:g} %: the table has {new_count} entries, expected {want}')
                count = new_count
                have.add(khz(f))
                done += 1
                self.log('PAIR', 'OK', f'37.3SP {f:g} MZ {c:g} CF; {count} entries', f'{khz(f)}')
        except Exception as exc:
            self.audit.set_status('STOPPED')
            self.log('STOPPED', 'FAILED', f'{str(exc).splitlines()[0]} (after {done} writes after the reference; the failed write was not repeated)')
            self._restore()
            raise EntryStopped(f'{exc}\n\nThe failed write was NOT repeated. The table in the 8902A may be partly changed: use "Read table" to see it. '
                               f'{done} entries were written after the reference.') from exc
        self.entered = True
        return self.verify(table, remove_stale)

    def verify(self, table, remove_stale=True):
        """Final read-back of the whole table against the plan: pass / fail per entry."""
        try:
            data = self.read_table('READ BACK')
        except CalFactorError as exc:
            self.audit.set_status('ENTERED_NOT_VERIFIED')
            self.log('VERIFY', 'FAILED', 'the table could not be read back; the entry is NOT verified')
            raise EntryStopped(str(exc)) from exc
        checks = []
        r = data['reference']
        checks.append(Check('reference', 50.0, table.reference, r, r is not None and abs(r - table.reference) <= REF_TOL_PCT, '' if r is not None else 'no reference read'))
        got = {khz(f): (f, c) for f, c in data['pairs']}
        for f, c in table.pairs:
            hit = got.get(khz(f))
            ok = hit is not None and abs(hit[0] - f) <= FREQ_TOL_MHZ and abs(hit[1] - c) <= REF_TOL_PCT
            checks.append(Check('pair', f, c, hit[1] if hit else None, ok, '' if hit else 'not in the table'))
        for k, (f, c) in sorted(got.items()):
            if k not in table.keys():
                checks.append(Check('extra', f, None, c, not remove_stale, 'other entry kept (not removed by choice)' if not remove_stale else 'UNEXPECTED entry still in the table'))
        want = 1 + len({*table.keys(), *({khz(f) for f, _ in self.existing['pairs']} if not remove_stale else set())})
        checks.append(Check('count', None, float(want), float(data['count']), data['count'] == want, 'entries incl. the reference'))
        ok = all(c.ok for c in checks)
        status = 'ENTERED_VERIFIED' if ok else 'ENTERED_NOT_VERIFIED'
        self.audit.set_status(status)
        lines = []
        for c in checks:
            who = {'reference': 'Reference (50 MHz)', 'pair': f'{c.mhz:g} MHz' if c.mhz is not None else '', 'extra': f'{c.mhz:g} MHz' if c.mhz is not None else '', 'count': 'Entry count'}[c.kind]
            lines.append(f'{"PASS" if c.ok else "FAIL"}  {who}: entered {"-" if c.entered is None else format(c.entered, "g")}, read {"-" if c.read is None else format(c.read, "g")}'
                         + (f'  ({c.note})' if c.note else ''))
            self.log('CHECK', 'OK' if c.ok else 'FAILED', lines[-1])
        self.log('SUMMARY', 'OK' if ok else 'FAILED', f'{sum(c.ok for c in checks)} of {len(checks)} checks passed; status {status}')
        return Result(ok, checks, data, status, lines)

    def abort(self, reason='operator'):
        self.audit.set_status('ABORTED')
        self.log('ABORTED', 'OK', f'stopped by the {reason}; nothing further is sent')
