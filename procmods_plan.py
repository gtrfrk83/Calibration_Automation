"""'What will the engine send for this test point?'  A dry run of the engine's OWN point routine on a simulated bench (Tk-free).

The point editor shows the commands that apply to one test point, in the order sent, with this point's values filled in.  They are not
re-derived by a second piece of code (which could drift from the engine): the engine's real per-point routine (Truevolt `IO.measure`,
handheld `IO.apply`, fgen `IO.measure`, MDO4000C `Runner.run_point` ...) is run once on throw-away drivers of the same classes, connected to
the simulated instruments of drivers/simulated*.py, with the saved overrides bound exactly as a run binds them.  Every `send` / `ask` /
`query_retry` (and every raw write / query) that crosses the driver is recorded with its registry key.

Safety of the dry run
  * It never touches a real instrument: the drivers are NEW objects on simulator transports; the running procedure's drivers, log,
    point lists and override state are not used (the override state is a private clone, `ModsState.clone_for_plan`).
  * Waits are skipped for the planning thread only (`dry_clock`): `time.sleep` / `time.monotonic` / `time.time` are wrapped while it runs;
    every other thread gets the original functions, so a procedure running in a worker thread is not affected.
  * The throw-away IO is never `close()`d (that would write the real command-log file); it is simply dropped.
  * A failure of the dry run (the simulator does not model something, a reply is not what the routine expects) is reported as `error`
    together with the commands recorded up to that point; the list is then INCOMPLETE and the window says so.

What a plan is NOT: a prediction of replies.  A real instrument that answers differently (an overload, an error-queue entry) takes the
engine's own error path, which the plan does not show.
"""
from __future__ import annotations

import contextlib
import dataclasses
import threading
import time

import cmdreg

_clock_lock = threading.RLock()
_tl = threading.local()


@contextlib.contextmanager
def dry_clock():
    """Skip the waits of the CALLING thread (sleep returns at once; monotonic / time advance by the skipped seconds)."""
    with _clock_lock:
        prev_sleep, prev_mono, prev_time = time.sleep, time.monotonic, time.time
        _tl.skew = getattr(_tl, 'skew', 0.0)
        _tl.depth = getattr(_tl, 'depth', 0)

        def sleep(seconds=0):
            if getattr(_tl, 'depth', 0) > 0:
                _tl.skew += max(0.0, float(seconds))
                return None
            return prev_sleep(seconds)

        def monotonic():
            return prev_mono() + (getattr(_tl, 'skew', 0.0) if getattr(_tl, 'depth', 0) > 0 else 0.0)

        def wall():
            return prev_time() + (getattr(_tl, 'skew', 0.0) if getattr(_tl, 'depth', 0) > 0 else 0.0)

        time.sleep, time.monotonic, time.time = sleep, monotonic, wall
        _tl.depth += 1
        try:
            yield
        finally:
            _tl.depth -= 1
            time.sleep, time.monotonic, time.time = prev_sleep, prev_mono, prev_time


@dataclasses.dataclass
class PlanEntry:
    seq: int
    driver: str                      # class name of the driver (the name an override target uses)
    label: str                       # the instrument's label in the command log
    op: str                          # 'write' | 'query'
    wire: str                        # text as it goes on the wire
    key: str | None = None           # registry key; None = a raw write / query that is not in the command registry
    how: str | None = None           # 'send' | 'ask' | 'query_retry' | None
    vals: dict = dataclasses.field(default_factory=dict)
    kind: str = ''                   # registry kind: 'set' | 'query' | 'action' ('' = unregistered)
    risk: str = ''                   # 'normal' | 'output' | 'locked' ('' = unregistered)
    verified: bool | None = None
    name: str = ''                   # registry name
    factory_wire: str | None = None  # what the factory template renders to for the same values
    override_uid: str | None = None  # the override that produced `wire` (driver-wide or for this point)
    extra: dict | None = None        # {'phase', 'n', 'uid', 'readback', 'expect'} for an operator-typed extra line

    @property
    def changed(self) -> bool:
        return bool(self.override_uid) or (self.factory_wire is not None and self.factory_wire != self.wire)


@dataclasses.dataclass
class Plan:
    entries: list = dataclasses.field(default_factory=list)
    error: str = ''                  # why the dry run stopped early ('' = it ran to the end)
    note: str = ''

    @property
    def complete(self) -> bool:
        return not self.error


class Recorder:
    """Wrap throw-away driver instances so everything they send is recorded (and still goes to their simulator transport)."""

    def __init__(self):
        self.entries: list = []

    def attach(self, inst):
        orig_prepare, orig_write, orig_query = inst._prepare, inst.write, inst.query
        pending: list = []

        def _prepare(key, vals, how):
            out = orig_prepare(key, vals, how)
            pending.append((key, dict(vals), how, out[0], out[1]))
            return out

        def take(wire):
            if pending and pending[-1][3] == wire:
                return pending.pop()
            return None

        def write(cmd, *a, **k):
            self._add(inst, 'write', cmd, take(cmd), k.get('log_as', a[0] if a else None))
            return orig_write(cmd, *a, **k)

        def query(cmd, *a, **k):
            self._add(inst, 'query', cmd, take(cmd), k.get('log_as', a[0] if a else None))
            return orig_query(cmd, *a, **k)

        def send_extra(x):                       # an operator-typed line: recorded, never sent (the simulator knows nothing about it)
            self._add_extra(inst, x)

        inst._prepare, inst.write, inst.query, inst._send_extra = _prepare, write, query, send_extra
        return inst

    def _add(self, inst, op, wire, meta, log_as):
        reg = inst._registry()
        e = PlanEntry(len(self.entries) + 1, type(inst).__name__, getattr(inst, 'label', type(inst).__name__), op, wire)
        if meta is not None:
            key, vals, how, _wire, tag = meta
            cmd = reg.get(key)
            e.key, e.how, e.vals = key, how, vals
            if cmd is not None:
                e.kind, e.risk, e.verified, e.name = cmd.kind, cmd.risk, cmd.verified, cmd.name or key
                try:
                    e.factory_wire = cmdreg.render(cmd, vals) if not cmd.secret else None
                except cmdreg.CmdError:
                    e.factory_wire = None
            if tag and '[OVERRIDE ' in tag:
                e.override_uid = tag.split('[OVERRIDE ', 1)[1].split(']', 1)[0]
        self.entries.append(e)

    def _add_extra(self, inst, x):
        base = dict(extra={'phase': x.get('phase'), 'n': x.get('n'), 'uid': x.get('uid'), 'readback': x.get('readback', ''),
                           'expect': x.get('expect', '')})
        label = getattr(inst, 'label', type(inst).__name__)
        text = x['template']
        is_query = '?' in text.split(None, 1)[0]
        self.entries.append(PlanEntry(len(self.entries) + 1, type(inst).__name__, label, 'query' if is_query else 'write', text,
                                      kind='query' if is_query else 'set', risk='normal', verified=False, name='Extra command', **base))
        if not is_query:
            self.entries.append(PlanEntry(len(self.entries) + 1, type(inst).__name__, label, 'query', x.get('readback', ''),
                                          kind='query', risk='normal', verified=False, name='Read-back of the extra command', **base))


def run_plan(state, build, run, drivers_of=None) -> Plan:
    """Dry-run one point.  `state` is the engine's ModsState (cloned here, never modified); `build(mods)` returns a throw-away IO on a
    simulated bench with `mods` as its override state; `run(io)` calls the engine's point routine for the point.  Never raises."""
    plan = Plan()
    rec = Recorder()
    try:
        clone = state.clone_for_plan()
    except Exception as exc:
        plan.error = f'the saved changes could not be loaded ({type(exc).__name__}: {exc})'
        return plan
    with dry_clock():
        try:
            io = build(clone)
            drivers = list(drivers_of(io) if drivers_of else io.pm_drivers())
            for d in drivers:
                if d is not None:
                    rec.attach(d)
            run(io)
        except Exception as exc:
            plan.error = f'{type(exc).__name__}: {exc}'
    plan.entries = rec.entries
    return plan
