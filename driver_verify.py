"""Instrument driver verification (Tk-free and Qt-free): talk to a real instrument and check every command its driver declares.

    driver_catalog()                      -> [(label, class)]   every driver that declares a COMMANDS table
    build_plan(cls)                       -> [Step]             one step per registered command, in registry order, each with a mode and a default
    Verifier(driver, ...).run(step)       -> Result             sends ONE command (set/action commands once, never retried) and checks the answer
    compare_flags(plan, results)          -> [Finding]          where the bench result disagrees with the driver's own `verified` flag
    save_results(...) / load_runs(...)    lab_registry.sqlite3 table driver_verification (new table; no existing schema is touched)
    write_csv(path, ...)

What "verified" means here, per command kind
    query                   the command is sent (a read-only query may be retried) and must answer; then the instrument's error queue must be empty.
    set / action            sent ONCE.  If the driver declares a read-back query it is asked and compared with what was set; a reply that does
                            not obviously match is 'check' (the person looks at the reply and decides).  Then the error queue must be empty.
    output  (risk)          as a set, but only after a typed confirmation, and the driver's cleanup() (standby / off) runs straight afterwards.
    locked  (reset ...)     only when 'include reset' is ticked and confirmed.
Never sent, whatever is ticked: calibration, security, service, factory commands (cmdreg's forbidden list), commands with a password, commands whose
placeholders have no sample value, VBS lines.  Passwords never reach a log or a record.

A run against a simulated instrument is marked SIMULATED, is never saved as evidence and the CSV says so on every row.
The tool never edits a driver's `verified` flag: it reports where bench and flag disagree and the person decides."""
from __future__ import annotations

import csv
import importlib
import inspect
import pkgutil
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime

import cmdreg

SKIP_MODULES = ('simulated', 'selftest', 'transport', 'base', '_template')
STATUSES = ('pass', 'check', 'fail', 'skipped')
ERR_LIMIT = 8                                                # error-queue entries read per command at most


# ---------------------------------------------------------------------------------------------------------------- catalogue
def driver_catalog() -> list:
    """[(label, class)] sorted by label: every Instrument subclass in drivers/* that has commands of its own or inherited."""
    import drivers
    from drivers.base import Instrument
    found = {}
    for info in pkgutil.iter_modules(drivers.__path__):
        if info.name.startswith(SKIP_MODULES):
            continue
        try:
            mod = importlib.import_module(f'drivers.{info.name}')
        except Exception:                                   # a driver whose optional library is missing is simply not offered
            continue
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and issubclass(obj, Instrument) and obj is not Instrument and obj.__module__ == mod.__name__ and cmdreg.merge_commands(obj):
                found[obj] = (getattr(obj, 'MODEL', '') or name, name)
    out = [(f'{model} ({name})' if model != name else name, cls) for cls, (model, name) in found.items()]
    return sorted(out, key=lambda x: x[0].lower())


# ---------------------------------------------------------------------------------------------------------------- plan
@dataclass
class Step:
    key: str
    cmd: object
    wire: str = ''                                           # the command as it would be sent (sample values filled in); '' when it cannot be sent
    mode: str = 'query'                                      # 'query' | 'set' | 'output' | 'locked'
    default_on: bool = False
    skip_reason: str = ''                                    # non-empty: never sent
    values: dict = field(default_factory=dict)

    @property
    def sendable(self) -> bool:
        return not self.skip_reason


@dataclass
class Result:
    key: str
    wire: str = ''
    status: str = 'skipped'
    reply: str = ''
    readback: str = ''
    error: str = ''
    note: str = ''
    seconds: float = 0.0
    confirmed_by_tester: bool = False                        # a 'check' the person settled by hand (the person's name is in the run record)


@dataclass
class Finding:
    key: str
    level: str                                               # 'bad' | 'good' | 'info'
    text: str


def sample_values(cmd):
    """{placeholder: value} from the declared samples, or None when a required placeholder has no usable sample (or is a secret)."""
    vals = {}
    for name, ph in (cmd.placeholders or {}).items():
        if ph.type == 'secret':
            return None
        sample = ph.sample
        if sample is None:
            if ph.enum:
                sample = ph.enum[0]
            elif not ph.required:
                continue
            else:
                return None
        vals[name] = sample
    return vals


def _mode_of(cmd) -> str:
    if cmd.kind == 'query':
        return 'query'
    if cmd.risk == 'locked':
        return 'locked'
    if cmd.risk == 'output':
        return 'output'
    return 'set'


def build_plan(cls_or_obj) -> list:
    dname = (cls_or_obj if isinstance(cls_or_obj, type) else type(cls_or_obj)).__name__
    steps = []
    for key, cmd in cmdreg.merge_commands(cls_or_obj).items():
        st = Step(key, cmd, mode=_mode_of(cmd))
        if cmd.lang != 'scpi':
            st.skip_reason = 'a VBS line, not a plain command'
        elif cmd.secret:
            st.skip_reason = 'contains a password: never sent from here'
        else:
            vals = sample_values(cmd)
            if vals is None:
                st.skip_reason = 'no sample value for a required field'
            else:
                try:
                    st.wire, st.values = cmdreg.render(cmd, vals), vals
                except cmdreg.CmdError as exc:
                    st.skip_reason = f'cannot be filled in: {exc}'
        if st.wire and st.mode != 'locked':                                    # the registry's own reset is the one locked command allowed through
            bad = cmdreg._forbidden(st.wire, dname)
            if bad or key.lower().startswith(('cal.', 'calibration')):
                st.skip_reason = 'calibration / security / service command: never sent by this tool'
        if not st.skip_reason and st.mode == 'locked' and st.wire.strip().upper() not in ('*RST', '*RST;*CLS') and key != 'reset':
            st.skip_reason = 'locked command other than the reset: not sent by this tool'
        st.default_on = st.sendable and st.mode == 'query'
        steps.append(st)
    return steps


def counts(plan) -> dict:
    out = {'query': 0, 'set': 0, 'output': 0, 'locked': 0, 'skipped': 0}
    for s in plan:
        out['skipped' if s.skip_reason else s.mode] += 1
    return out


# ---------------------------------------------------------------------------------------------------------------- running
_NUM = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')


def _tokens(text):
    return [t for t in re.split(r'[\s,;"\']+', str(text).strip().upper()) if t]


def reply_matches(wire: str, reply: str) -> bool:
    """True when a read-back obviously agrees with the command that was set: the last argument of the command appears in the reply (text or number)."""
    words = wire.strip().split(None, 1)
    if len(words) < 2:
        return False                                        # STBY, *CLS ...: nothing in the text to compare; the person looks at the reply
    arg = words[1].split(',')[-1].strip().upper() if ',' in words[1] else words[1].strip().upper()
    rep = str(reply).strip().upper()
    if not rep:
        return False
    if arg in rep or rep in arg or arg.strip('"\'') in rep:
        return True
    try:
        a = float(_NUM.search(arg).group()) if _NUM.search(arg) else None
        for t in _tokens(rep):
            m = _NUM.fullmatch(t)
            if a is not None and m and abs(float(t) - a) <= 1e-6 * max(1.0, abs(a)):
                return True
    except ValueError:
        pass
    return False


class Verifier:
    """Runs steps against one connected driver.  `confirm(step) -> bool` is asked before every set / output / locked command (the window shows the
    dialog; the typed 'OUTPUT' confirmation for output commands is its job).  `simulated` marks every result as a simulation."""

    def __init__(self, driver, confirm=None, simulated=False):
        self.driver, self.confirm, self.simulated = driver, confirm, simulated
        self.stop = False
        self.reg = cmdreg.merge_commands(driver)

    # ---- error queue (read-only, may be retried)
    def _errors(self) -> list:
        if 'err.query' not in self.reg:
            return []
        found = []
        for _ in range(ERR_LIMIT):
            reply = self.driver.query_retry('err.query', attempts=3, delay=0.3).strip()
            code = self.driver._error_code(reply)
            if code == 0 or not reply:
                break
            found.append(reply)
        return found

    def _drain(self):
        try:
            self._errors()
        except Exception:
            pass

    def run(self, step: Step) -> Result:
        res = Result(step.key, step.wire)
        t0 = time.monotonic()
        try:
            if step.skip_reason:
                res.status, res.note = 'skipped', step.skip_reason
                return res
            if step.mode != 'query' and not (self.confirm and self.confirm(step)):
                res.status, res.note = 'skipped', 'not confirmed'
                return res
            self._drain()
            if step.mode == 'query':
                res.reply = self.driver.query_retry(step.key, values=step.values).strip()
                ok_reply = bool(res.reply)
                errs = self._errors() if step.key != 'err.query' else []
                if not ok_reply:
                    res.status, res.error = 'fail', 'no reply'
                elif errs:
                    res.status, res.error = 'fail', 'error queue: ' + ' | '.join(errs)
                else:
                    res.status = 'pass'
                return res
            self.driver.send(step.key, **step.values)                         # once; never retried
            rb_key = step.cmd.readback
            if rb_key and rb_key in self.reg:
                rb_cmd = self.reg[rb_key]
                res.readback = self.driver.query_retry(rb_key, values=sample_values(rb_cmd) or {}).strip()
            errs = self._errors()
            if errs:
                res.status, res.error = 'fail', 'error queue: ' + ' | '.join(errs)
            elif rb_key and rb_key in self.reg:
                if reply_matches(step.wire, res.readback):
                    res.status = 'pass'
                else:
                    res.status, res.note = 'check', f'read-back {rb_key!r} answered {res.readback!r}: look at it and decide'
            else:
                res.status, res.note = 'pass', 'accepted (error queue empty); no read-back is declared for this command'
            return res
        except Exception as exc:                                              # TransportError, InstrumentError, SafetyError ...
            res.status, res.error = 'fail', f'{type(exc).__name__}: {exc}'
            return res
        finally:
            if step.mode in ('output', 'locked') and not step.skip_reason and res.status != 'skipped':
                try:
                    self.driver.cleanup()                                      # standby / off after every output-changing command
                    res.note = (res.note + '; ' if res.note else '') + 'output put to standby/off afterwards'
                except Exception as exc:
                    res.note = (res.note + '; ' if res.note else '') + f'CLEANUP FAILED: {exc}'
            res.seconds = round(time.monotonic() - t0, 3)

    def run_plan(self, steps, progress=None) -> list:
        out = []
        for i, st in enumerate(steps):
            if self.stop:
                break
            r = self.run(st)
            out.append(r)
            if progress:
                progress(i, st, r)
        return out


# ---------------------------------------------------------------------------------------------------------------- findings
def compare_flags(plan, results) -> list:
    by_key = {s.key: s for s in plan}
    out = []
    for r in results:
        st = by_key.get(r.key)
        if st is None or r.status == 'skipped':
            continue
        flag = bool(st.cmd.verified)
        passed = r.status == 'pass' or (r.status == 'check' and r.confirmed_by_tester)
        if r.status == 'fail' and flag:
            out.append(Finding(r.key, 'bad', f'{r.key}: the driver says VERIFIED but it failed on this instrument ({r.error or r.note})'))
        elif passed and not flag:
            out.append(Finding(r.key, 'good', f'{r.key}: passed on the instrument; the driver still says unverified'))
        elif r.status == 'fail' and not flag:
            out.append(Finding(r.key, 'info', f'{r.key}: unverified in the driver and failed here ({r.error or r.note})'))
    return out


# ---------------------------------------------------------------------------------------------------------------- records
TABLE = '''
CREATE TABLE IF NOT EXISTS driver_verification (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    tested_at TEXT NOT NULL,
    tester TEXT NOT NULL DEFAULT '',
    driver TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    idn TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    wire TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    risk TEXT NOT NULL DEFAULT '',
    flag_verified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    reply TEXT NOT NULL DEFAULT '',
    readback TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    by_tester INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS driver_verification_run ON driver_verification(run_id);
CREATE INDEX IF NOT EXISTS driver_verification_driver ON driver_verification(driver, key);
'''


def _connect(db=None):
    import labregistry
    con = sqlite3.connect(str(db or labregistry.DB), timeout=5)
    con.executescript(TABLE)
    return con


class SimulatedError(RuntimeError):
    """A simulated run cannot be saved as evidence."""


def save_results(plan, results, *, driver_name, model='', idn='', address='', tester='', simulated=False, db=None) -> str:
    """Store one run (skipped commands are not stored).  Returns the run id.  A simulated run is refused: demo results must never look like evidence."""
    if simulated:
        raise SimulatedError('A simulated instrument cannot be saved as a verification record.')
    by_key = {s.key: s for s in plan}
    when = datetime.now().isoformat(timespec='seconds')
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + re.sub(r'\W+', '', driver_name)[:24]
    rows = []
    for r in results:
        st = by_key.get(r.key)
        if st is None or r.status == 'skipped':
            continue
        rows.append((run_id, when, tester, driver_name, model, idn, address, r.key, r.wire, st.cmd.kind, st.cmd.risk, int(bool(st.cmd.verified)), r.status,
                     r.reply, r.readback, r.error, r.note, int(r.confirmed_by_tester)))
    con = _connect(db)
    try:
        with con:
            con.executemany('INSERT INTO driver_verification(run_id,tested_at,tester,driver,model,idn,address,key,wire,kind,risk,flag_verified,status,reply,'
                            'readback,error,note,by_tester) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    finally:
        con.close()
    return run_id


def load_runs(driver_name=None, db=None) -> list:
    """[(run_id, tested_at, tester, driver, model, passed, failed, checks)] newest first."""
    try:
        con = _connect(db)
    except sqlite3.Error:
        return []
    try:
        q = ("SELECT run_id,MAX(tested_at),MAX(tester),MAX(driver),MAX(model),SUM(status='pass'),SUM(status='fail'),SUM(status='check') "
             "FROM driver_verification" + (' WHERE driver=?' if driver_name else '') + ' GROUP BY run_id ORDER BY MAX(tested_at) DESC')
        return con.execute(q, (driver_name,) if driver_name else ()).fetchall()
    finally:
        con.close()


def last_status(driver_name, db=None) -> dict:
    """{key: (status, tested_at)} of the most recent saved result for each command of a driver."""
    try:
        con = _connect(db)
    except sqlite3.Error:
        return {}
    try:
        rows = con.execute('SELECT key,status,tested_at,by_tester FROM driver_verification WHERE driver=? ORDER BY id', (driver_name,)).fetchall()
    finally:
        con.close()
    return {k: (s, t) for k, s, t, _b in rows}


def write_csv(path, plan, results, *, driver_name='', model='', idn='', address='', tester='', simulated=False):
    by_key = {s.key: s for s in plan}
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['SIMULATED - NOT EVIDENCE' if simulated else 'Driver verification', driver_name, model, idn, address, tester,
                    datetime.now().isoformat(timespec='seconds')])
        w.writerow(['key', 'command sent', 'kind', 'risk', 'driver flag', 'result', 'reply', 'read-back', 'error', 'note', 'seconds'])
        for r in results:
            st = by_key.get(r.key)
            w.writerow([r.key, r.wire, st.cmd.kind if st else '', st.cmd.risk if st else '', 'verified' if st and st.cmd.verified else 'unverified',
                        r.status + (' (simulated)' if simulated else '') + (' (settled by tester)' if r.confirmed_by_tester else ''), r.reply, r.readback,
                        r.error, r.note, r.seconds])
