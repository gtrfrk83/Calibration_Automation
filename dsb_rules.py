"""Run-time rules for automated Datasheet Builder sheets (the owner-approved rules 6 - 13, NOTES.md): the parts that need no Tk and no instrument I/O of their own.

    dsb_runtime.DsbApp / DsbIO use this module; nothing in the handheld engine (handheld_dmm.py) or in any driver is changed by it.

  * SECTION MODES (rule 12).  Every section of a sheet is AUTO (the program drives / reads the standards), HAND (the technician sets the stimulus with
    his own standards and TYPES the reading: the manual-calibration entry, padding and judging) or SKIP (not tested).  The setting lives in the
    progress file and in the run window; it is generic (a dict {section: mode}) so another runner could reuse it.
  * START-STATE CHECK (rule 7).  A driver may declare `start_state_checks()` -> [Probe]: read-only probes of the settings that break a run (echo,
    prompts, identity ...).  A driver that declares nothing is not checked.  `run_probes` never raises and never writes; `failure_text` words what the
    operator has to change.  `ADAPTERS` holds declarations for drivers that must not be edited (the 8808A driver is in the fingerprint of two verified
    procedures): the adapter only calls the driver's own read-only code.
  * STABLE-READING SETTLE (rule 8).  `settle_stable` polls a read-only reading until N consecutive values agree within a band; the value returned is the
    LAST reading (never an average), the outcome says stable-after-k-polls or timeout.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable

# ============================================================================================================== rule 12: section modes
AUTO, HAND, SKIP = 'auto', 'hand', 'skip'
MODES = (AUTO, HAND, SKIP)
MODE_LABEL = {AUTO: 'Automated', HAND: 'Typed by hand', SKIP: 'Not tested'}
LABEL_MODE = {v: k for k, v in MODE_LABEL.items()}
MODE_HINT = {AUTO: 'The program sets and reads the connected standards.',
             HAND: 'You set the stimulus with your own standards and type each reading.',
             SKIP: 'Nothing is run or asked; the report lists the section as not tested.'}


def normalise_modes(modes, sections, default=AUTO, allowed=MODES) -> dict:
    """{section: mode} for exactly `sections` (in order): unknown sections are dropped, a missing or invalid value gets `default`."""
    modes = modes if isinstance(modes, dict) else {}
    out = {}
    for s in sections:
        m = modes.get(s, default)
        out[s] = m if m in allowed else default
    return out


# ============================================================================================================== rule 7: start-state check
@dataclass(frozen=True)
class Probe:
    """One read-only check.  run() -> (ok, detail) and may raise (a raise counts as 'not as needed' with the exception text).
    run=None: the setting cannot be read back from the instrument; it is listed as 'not checked' with `note` (nothing is guessed)."""
    name: str
    run: Callable[[], tuple] | None
    fix: str = ''                 # plain instruction for the operator when the check fails
    note: str = ''                # for run=None: why it cannot be checked


@dataclass
class ProbeResult:
    instrument: str
    name: str
    ok: bool
    detail: str = ''
    fix: str = ''
    checked: bool = True


def declared_probes(driver) -> list:
    """The probes a driver declares: its own `start_state_checks()`, else an adapter for its class (ADAPTERS), else none (additive for drivers that
    declare nothing)."""
    own = getattr(driver, 'start_state_checks', None)
    if callable(own):
        return list(own())
    adapter = ADAPTERS.get(type(driver).__name__)
    return list(adapter(driver)) if adapter else []


def identity_probe(driver) -> Probe | None:
    """The *IDN? check of a driver (read-only).  A driver that cannot answer *IDN? declares `IDN_UNAVAILABLE = True` and the check is skipped (None)."""
    if getattr(driver, 'IDN_UNAVAILABLE', False) or not getattr(driver, 'IDN_MATCH', ()):
        return None

    def run():
        reply = driver.identify()
        ok = any(m.upper() in reply.upper() for m in driver.IDN_MATCH)
        return ok, f'identifies as {reply!r}' if ok else f'identifies as {reply!r}, expected {" / ".join(driver.IDN_MATCH)}'
    return Probe('Identity', run, f'The instrument on this address is not a {driver.MODEL or "/".join(driver.IDN_MATCH)}. Check the address and the cable.')


def run_probes(items, log=None) -> list:
    """items: [(label, driver)].  Runs every declared probe once (read-only; nothing is written, nothing is retried here) and returns [ProbeResult].
    Never raises.  Each outcome is written to the command log."""
    results = []
    for label, driver in items:
        try:
            probes = declared_probes(driver)
        except Exception as exc:                         # a broken declaration must not stop the run: it is reported
            results.append(ProbeResult(label, 'Start-state checks', False, f'could not be declared: {exc}', checked=False))
            probes = []
        for pr in probes:
            if pr.run is None:
                res = ProbeResult(label, pr.name, True, pr.note or 'cannot be read back from the instrument', checked=False)
            else:
                try:
                    ok, detail = pr.run()
                    res = ProbeResult(label, pr.name, bool(ok), str(detail), '' if ok else pr.fix)
                except Exception as exc:
                    res = ProbeResult(label, pr.name, False, str(exc), pr.fix)
            results.append(res)
    if log is not None:
        for r in results:
            if not r.checked:
                log.add('--', f'start-state: {r.name}: NOT CHECKED - {r.detail}', r.instrument)
            else:
                log.add('--' if r.ok else '!!', f'start-state: {r.name}: ' + ('ok' if r.ok else 'NOT AS NEEDED') + (f' - {r.detail}' if r.detail else ''), r.instrument)
    return results


def failed(results) -> list:
    return [r for r in results if r.checked and not r.ok]


def failure_text(results) -> str:
    """What the operator reads when a start-state check failed: which instrument, what is wrong, what to change.  The run has not started."""
    bad = failed(results)
    lines = ['Before the first point the program checked the instruments (read-only: nothing was changed) and found a setting that would spoil the run:', '']
    for r in bad:
        lines.append(f'  {r.instrument}: {r.name}')
        if r.fix:
            lines.append(f'      {r.fix}')
        if r.detail:
            lines.append(f'      (what the instrument said: {r.detail})')
    lines += ['', 'The run was not started and the outputs are in standby. Change the setting, then press Run again.']
    return '\n'.join(lines)


def _adapter_8808a(drv):
    """Fluke 8808A (RS-232).  Reuses the driver's own prompt-tolerant read code (identify / _query_lines) and its counters; read-only.  The things that cannot be
    read back are listed as 'not checked': the remote state has no query (Users Manual: no state query for REMS / LOCS)."""
    def echo():
        p0, e0 = getattr(drv, 'prompts_seen', 0), getattr(drv, 'echo_seen', 0)
        drv.identify()                                       # raises (plain message) when the reply is the echoed command or carries a prompt
        drv.ask('opc.query')                                 # a second read-only query: a prompt that FOLLOWED the first reply is read (and counted) in front of this one
        if getattr(drv, 'prompts_seen', 0) != p0 or getattr(drv, 'echo_seen', 0) != e0:
            return False, drv.PROMPT_WARNING
        return True, 'answers *IDN? with no echo and no prompt'
    out = [Probe('Echo off, no prompts', echo,
                 'Turn Echo OFF in the meter\'s front-panel serial (RS-232) settings (Users Manual Table 4-1, p. 4-4: factory setting off), then press Run again.')]
    idp = identity_probe(drv)
    if idp is not None:
        out.append(idp)
    out.append(Probe('Remote state', None, note='the 8808A has no query for the remote / local state, so it cannot be read back'))
    return out


ADAPTERS = {'Fluke8808A': _adapter_8808a}


# ============================================================================================================== rule 8: stable-reading settle
@dataclass(frozen=True)
class StableSpec:
    n: int = 3                    # consecutive readings that must agree
    band: float = 0.0             # ... within this spread (max - min), in the unit of the readings the caller passes
    minimum_s: float = 0.0        # fixed time before the first poll (the point's ordinary settle time): the MINIMUM
    timeout_s: float = 30.0       # cap on the total time (never below the minimum)
    poll_s: float = 0.2           # pause between two polls (a choice of this program, not a figure from a manual)


@dataclass
class StableResult:
    stable: bool
    polls: int
    value: float | None
    spread: float | None          # max - min of the last n readings (all of them when fewer)
    elapsed_s: float
    n: int
    band: float

    def text(self, unit='') -> str:
        u = f' {unit}' if unit else ''
        if self.stable:
            return f'reading stable after {self.polls} poll(s): {self.n} consecutive within {self.band:g}{u} (spread {self.spread:g}{u}), {self.elapsed_s:.1f} s'
        return (f'reading NOT stable: timeout after {self.polls} poll(s), {self.elapsed_s:.1f} s (last {self.n} spread {self.spread:g}{u}, band {self.band:g}{u}); '
                f'the last reading is used')


def settle_stable(read, spec: StableSpec, *, cancel=None, wait=None, clock=time.monotonic):
    """Wait until `spec.n` consecutive readings agree within `spec.band`.  `read()` is ONE read-only query returning a number.  `wait(seconds, cancel)` sleeps
    (and raises when cancel() is true); the fixed time `spec.minimum_s` is waited first.  The value returned is the last reading, exactly as read (no
    averaging).  On timeout the last reading is returned too, with stable=False; the caller logs it.  Returns (value, StableResult)."""
    wait = wait or _sleep
    start = clock()
    if spec.minimum_s > 0:
        wait(spec.minimum_s, cancel)
    cap = max(float(spec.timeout_s), float(spec.minimum_s))
    values = []
    while True:
        v = float(read())
        values.append(v)
        window = values[-spec.n:]
        spread = max(window) - min(window)
        if len(values) >= spec.n and spread <= spec.band * (1 + 1e-9) + 1e-12:     # tolerance for float noise in max - min
            return v, StableResult(True, len(values), v, spread, clock() - start, spec.n, spec.band)
        if clock() - start >= cap:
            return v, StableResult(False, len(values), v, spread, clock() - start, spec.n, spec.band)
        wait(spec.poll_s, cancel)


def _sleep(seconds, cancel):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel and cancel():
            raise RuntimeError('cancelled')
        time.sleep(min(0.25, max(0.0, end - time.monotonic())))


def decimals(text) -> int:
    try:
        return max(0, -Decimal(str(text)).as_tuple().exponent)
    except (InvalidOperation, TypeError):
        return 0


def default_band(p, counts=3.0) -> float:
    """The agreement band for point p in its DISPLAY unit: `counts` counts of the point's resolution (the decimals of its limits), but never more than a
    tenth of the tolerance width (so 'stable' can never hide a failing reading) and never less than one count."""
    places = max(decimals(p.get('low')), decimals(p.get('high')))
    res = 10.0 ** (-places)
    try:
        span = abs(float(Decimal(str(p['high'])) - Decimal(str(p['low']))))
    except (InvalidOperation, KeyError, TypeError):
        span = 0.0
    band = counts * res
    if span > 0:
        band = min(band, 0.1 * span)
    return max(band, res)
