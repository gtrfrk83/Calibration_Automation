"""Base class for every instrument driver.

Rules the base enforces so individual drivers stay small and consistent:
  * every command that crosses the wire is logged (CommandLog)
  * writes are never retried (their effect is unknown after a failure); read-only queries may be
  * a driver states how to recognise its own model (IDN_MATCH) and refuses to talk to anything else
  * cleanup() puts the instrument in a safe state and is called even after errors
  * commands are declared once, in a class-level COMMANDS table of cmdreg.Cmd (merged along the MRO), and sent with
    send(key, **vals) / ask(key, **vals); an approved override template (procmods) can replace the factory text of a
    'normal' command, in which case the wire gets the override and the command log line carries "  [OVERRIDE ov-<uid>]".
    With no override the wire text and the log line are exactly what the old f-string produced. Output (OPER/STBY/...),
    calibration, error-queue and secret-bearing commands are never overridable.

Command API (stable; every driver follows it):
    COMMANDS = {key: cmdreg.Cmd(...)}              class attribute; keys are dotted lower-case ('out.volts')
    use_commands(templates, uids=None) -> [(key, uid, [problems])]   install override templates; never raises; returns/records the rejected ones
    send(key, **vals)                              set/action command: render, then self.write (no retry, read-back stays in the caller)
    ask(key, **vals) -> str                        query command: render, then self.query
    query_retry(key_or_text, attempts, delay, values=None)   read-only queries; a registered key must be kind 'query'
    describe_commands() -> [dict]                  merged registry for the UI
    command_overrides_active() -> [uid]            overrides in effect (for the report / log banner)
    rejected_commands() -> [(key, uid, [problems])]
    set_point(point_key)                           select the test point whose point-specific overrides apply to the commands that follow
                                                   (None = no point); run_extras(phase) sends the extra command lines typed for that point

Reset to default settings (Stage 7 rule; see drivers/README.txt "Adding a model"):
    COMMANDS['reset']                              a LOCKED command (risk 'locked', never overridable): *RST or the model's equivalent
    reset_to_defaults() -> ResetReport             *RST, *CLS, wait for completion, drain the error queue, then the model's own
                                                   known-state steps (_reset_extra: re-enter remote, restore connect-time settings,
                                                   confirm outputs off / standby). Every write is sent once and never retried; the read-only
                                                   follow-up queries may be. The first failed step ends the sequence (ok=False).
    RESET_EXEMPT = 'why'                           a model with no safe software reset documents the reason here (and RESET_KNOWN_STATE
                                                   says how its state is established instead); the report then says "exempt".
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable

import math

import cmdreg

from .transport import CommandLog, Transport, TransportError


@dataclasses.dataclass
class ResetStep:
    name: str
    ok: bool = True
    detail: str = ''


@dataclasses.dataclass
class ResetReport:
    """Result of Instrument.reset_to_defaults(): per-step ok/error, warnings (e.g. leftover error-queue entries), exemption."""
    instrument: str = ''
    ok: bool = True
    exempt: bool = False
    steps: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)

    @property
    def failed_step(self):
        return next((s for s in self.steps if not s.ok), None)

    def text(self) -> str:
        head = f'{self.instrument}: ' + ('exempt from reset' if self.exempt else 'reset OK' if self.ok else 'RESET FAILED')
        lines = [head] + [f'  {"ok " if s.ok else "ERR"} {s.name}' + (f': {s.detail}' if s.detail else '') for s in self.steps]
        lines += [f'  warning: {w}' for w in self.warnings]
        return '\n'.join(lines)


def cmdreg_isclose(a, b) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


class InstrumentError(RuntimeError):
    """The instrument did not do what was asked (readback mismatch, wrong model, bad reply)."""


class SafetyError(InstrumentError):
    """A safe state could not be confirmed. Operator must check the front panel."""


class Instrument:
    MODEL = ''                # human name, e.g. 'Fluke 5560A'
    IDN_MATCH: tuple = ()     # any of these substrings (case-insensitive) must appear in *IDN?
    DEFAULT_TIMEOUT = 10.0
    COMMANDS: dict = {}       # {key: cmdreg.Cmd}; merged along the MRO by cmdreg.merge_commands
    SECRET_MASK = '********'  # what a secret placeholder shows in the command log
    RESET_EXEMPT = ''         # non-empty: why this model has no software reset (documented exemption, see reset_to_defaults)
    RESET_KNOWN_STATE = ''    # for an exempt model: how its state is established instead
    RESET_OPC_TIMEOUT = 30.0  # transport timeout while waiting for *OPC? after the reset

    def __init__(self, transport: Transport, log: CommandLog | None = None, label: str | None = None):
        self.t = transport
        self.log = log if log is not None else CommandLog()
        self.label = label or self.MODEL or type(self).__name__
        self.idn = ''
        self._open = False

    # ---- lifecycle
    def open(self, verify_model=True):
        self.t.open()
        self._open = True
        self.t.set_timeout(self.DEFAULT_TIMEOUT)
        if verify_model:
            self.idn = self.identify()
            if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
                self.close()
                raise InstrumentError(f'Expected {self.MODEL} but the instrument identifies as: {self.idn!r}')
        return self

    def close(self):
        if self._open:
            self.t.close()
            self._open = False

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        try:
            self.cleanup()
        finally:
            self.close()
        return False

    def identify(self):
        return self.query('*IDN?').strip()

    def cleanup(self):
        """Leave the instrument safe. Drivers override; must not raise."""

    # ---- wire access (always logged)
    def write(self, cmd: str, log_as: str | None = None):
        """log_as: what to record instead of the real command (use it to keep passwords out of logs)."""
        self.log.add('>>', log_as or cmd, self.label)
        self.t.write(cmd)

    def query(self, cmd: str, log_as: str | None = None) -> str:
        self.log.add('>>', log_as or cmd, self.label)
        reply = self.t.query(cmd)
        self.log.add('<<', reply.strip(), self.label)
        return reply

    def query_retry(self, cmd: str, attempts=3, delay=0.5, values: dict | None = None) -> str:
        """Read-only queries only. Writes must never go through here.
        `cmd` is a registered command key (it must be kind 'query'; `values` fills its placeholders) or, for drivers not yet
        converted to the registry, the query text itself."""
        wire, log_as = cmd, None
        if cmd in self._registry():
            wire, log_as = self._prepare(cmd, values or {}, 'query_retry')
        last = None
        for n in range(attempts):
            try:
                return self.query(wire) if log_as is None else self.query(wire, log_as=log_as)
            except TransportError as exc:
                last = exc
                if n + 1 < attempts:
                    time.sleep(delay * (n + 1))
        raise InstrumentError(f'{cmd!r} failed after {attempts} attempts: {last}') from last

    # ---- command registry (COMMANDS) -------------------------------------------------------------------
    _cmd_ov: dict | None = None            # {key: (override text, uid)} - instance state, created by use_commands
    _cmd_rejected: list | None = None      # [(key, uid, [problems])]
    _cmd_pt: dict | None = None            # {point key: {key: (override text, uid)}} - overrides typed for ONE test point
    _extras: dict | None = None            # {point key: [{'phase', 'n', 'template', 'readback', 'expect', 'uid'}]} - extra command lines
    _pt_key: str | None = None             # the test point being measured (set_point); None between points

    def _registry(self) -> dict:
        reg = self.__dict__.get('_reg_cache')
        if reg is None:
            reg = self.__dict__['_reg_cache'] = cmdreg.merge_commands(self)
        return reg

    @staticmethod
    def _uid_text(uid) -> str:
        uid = str(uid or '?')
        return uid if uid.startswith('ov-') else 'ov-' + uid

    def _reject(self, key, uid, problems):
        """Record (and log) an override that was not applied. The text of the override is not logged (it is in the override store)."""
        msgs = [str(p) for p in problems]
        if self._cmd_rejected is None:
            self._cmd_rejected = []
        self._cmd_rejected.append((key, uid, msgs))
        self.log.add('!!', f'OVERRIDE REJECTED {self._uid_text(uid)} {key}: ' + '; '.join(msgs), self.label)

    def use_commands(self, templates: dict | None, uids: dict | None = None, points: dict | None = None, point_uids: dict | None = None,
                     extras: dict | None = None) -> list:
        """Install override templates {key: text}. A value may also be (text, uid) or {'template': text, 'uid': uid}; `uids`
        {key: uid} supplies the uid otherwise. Each one is re-validated against the merged registry (cmdreg.validate); failures are
        dropped, recorded (rejected_commands) and logged as OVERRIDE REJECTED - never raised. Replaces any earlier set.
        `points` {point key: {key: text}} (+ `point_uids`) are the overrides typed for ONE test point: they are checked the same way and
        win over the driver-wide ones while that point is selected (set_point).  `extras` {point key: [extra line, ...]} are the extra
        command lines for a point (run_extras)."""
        self._cmd_ov, self._cmd_rejected = {}, []
        self._cmd_pt, self._extras = {}, {}
        reg = self._registry()
        dname = type(self).__name__

        def check(key, val, uid):
            cmd = reg.get(key)
            ok, why = cmdreg.is_overridable(cmd)
            if cmd is None:
                probs = [cmdreg.Problem('type', 'unknown command')]
            elif not ok:                                        # output / locked / secret: refused even if the text is unchanged
                probs = [cmdreg.Problem('locked', f'{key} is not editable: {why}')]
            else:
                probs = cmdreg.validate(val, cmd, dname)
            if probs:
                self._reject(key, uid, probs)
                return None
            return cmd

        for key, val in dict(templates or {}).items():
            uid = (uids or {}).get(key)
            if isinstance(val, dict):
                uid, val = val.get('uid', uid), val.get('template')
            elif isinstance(val, (tuple, list)) and len(val) == 2:
                val, uid = val
            cmd = check(key, val, uid)
            if cmd is not None and val != cmd.template:         # identical to the factory text: nothing to override
                self._cmd_ov[key] = (val, uid)
        effective = {k: t for k, (t, _u) in self._cmd_ov.items()}
        bundle = cmdreg.validate_bundle(effective, reg) if effective else []
        if bundle:
            for key, (_t, uid) in list(self._cmd_ov.items()):
                self._reject(key, uid, bundle)
            self._cmd_ov = {}
        for pkey, table in dict(points or {}).items():
            for key, val in (dict(table) if isinstance(table, dict) else {}).items():
                uid = ((point_uids or {}).get(pkey) or {}).get(key)
                cmd = check(key, val, uid)
                if cmd is not None and val != cmd.template:
                    self._cmd_pt.setdefault(pkey, {})[key] = (val, uid)
            eff = {**effective, **{k: t for k, (t, _u) in self._cmd_pt.get(pkey, {}).items()}}
            bundle = cmdreg.validate_bundle(eff, reg) if self._cmd_pt.get(pkey) else []
            if bundle:
                for key, (_t, uid) in list(self._cmd_pt[pkey].items()):
                    self._reject(key, uid, bundle)
                del self._cmd_pt[pkey]
        for pkey, lines in dict(extras or {}).items():
            self._extras[pkey] = [dict(x) for x in lines if isinstance(x, dict)] if isinstance(lines, (list, tuple)) else []
        return list(self._cmd_rejected)

    # ---- test point context: point-specific overrides and extra command lines (procmods "Edit point") --------------------
    def set_point(self, point_key):
        """Select the test point whose point-specific overrides apply to the commands that follow (None: none). The engine's point
        routine does this at its start and clears it at its end (procmods_engine.point_commands)."""
        self._pt_key = point_key

    def point_overrides_active(self, point_key=None) -> list:
        """uids of the point-specific command overrides for a point (default: the selected one), in registry order."""
        table = (self._cmd_pt or {}).get(point_key if point_key is not None else self._pt_key) or {}
        return [self._uid_text(table[k][1]) for k in self._registry() if k in table]

    def run_extras(self, phase: str):
        """Send the extra command lines typed for the selected point and `phase` ('before' / 'after'), in order, each ONCE (never retried).
        A write is read back and compared with the reply the line was made with; a mismatch raises InstrumentError.  Every line is logged
        with its uid and 'UNVERIFIED'."""
        for x in (self._extras or {}).get(self._pt_key, []):
            if x.get('phase') == phase:
                self._send_extra(x)

    @staticmethod
    def _extra_same(reply, expect) -> bool:
        a, b = str(reply).strip().strip('"\'').strip().upper(), str(expect).strip().strip('"\'').strip().upper()
        if a == b:
            return True
        try:
            return cmdreg_isclose(float(a), float(b))
        except ValueError:
            return False

    def _send_extra(self, x):
        text, uid = x['template'], self._uid_text(x.get('uid'))
        probs = cmdreg.validate(text, None, type(self).__name__)
        if probs:                                               # re-checked at send time, like every override
            self._reject('extra', x.get('uid'), probs)
            return
        tag = f'  [EXTRA {uid} UNVERIFIED]'
        if '?' in text.split(None, 1)[0]:
            self.query(text, log_as=text + tag)
            return
        self.write(text, log_as=text + tag)
        reply = self.query(x['readback'], log_as=x['readback'] + tag)
        if not self._extra_same(reply, x['expect']):
            raise InstrumentError(f'{self.label}: extra command {text!r} was not confirmed: {x["readback"]!r} answered {reply.strip()!r}, '
                                  f'expected {x["expect"]!r}')

    def rejected_commands(self) -> list:
        return list(self._cmd_rejected or [])

    def command_overrides_active(self) -> list:
        """uids of the command overrides in effect, in registry order (for the report / log banner)."""
        reg = self._registry()
        ov = self._cmd_ov or {}
        return [self._uid_text(ov[k][1]) for k in reg if k in ov]

    def _prepare(self, key, vals, how):
        """(wire text, log_as or None) for a registered command. how: 'send' | 'ask' | 'query_retry'."""
        cmd = self._registry().get(key)
        if cmd is None:
            raise InstrumentError(f'{self.label}: unknown command key {key!r}')
        if how == 'send' and cmd.kind not in ('set', 'action'):
            raise InstrumentError(f'{self.label}: {key!r} is a query; use ask()')
        if how != 'send' and cmd.kind != 'query':
            raise InstrumentError(f'{self.label}: {key!r} is not a query ({cmd.kind}); it cannot be asked or retried')
        table = (self._cmd_pt or {}).get(self._pt_key) if self._pt_key is not None else None
        src = table if table and key in table else self._cmd_ov if self._cmd_ov and key in self._cmd_ov else None     # the point's own first
        ov = src[key] if src is not None else None
        if ov is not None and src is not None:
            text, uid = ov
            ok, why = cmdreg.is_overridable(cmd)
            probs = cmdreg.validate(text, cmd, type(self).__name__) if ok else [cmdreg.Problem('locked', f'{key} is not editable: {why}')]
            if probs:                                           # re-validated at send time: fall back to the factory text
                self._reject(key, uid, probs)
                del src[key]
            else:
                try:
                    wire = cmdreg.render(dataclasses.replace(cmd, template=text), vals)
                    return wire, wire + '  [OVERRIDE ' + self._uid_text(uid) + ']'
                except cmdreg.CmdError as e:
                    self._reject(key, uid, [cmdreg.Problem('placeholder.missing', str(e))])
                    del src[key]
        wire = cmdreg.render(cmd, vals)
        if cmd.secret:                                          # the value goes on the wire, never in the log
            masked = {n: (self.SECRET_MASK if getattr(p, 'type', '') == 'secret' else vals.get(n)) for n, p in cmd.placeholders.items()}
            return wire, cmdreg.render(cmd, masked)
        return wire, None

    def send(self, key: str, **vals):
        """Send a registered set/action command through self.write (read-back/compare stays in the caller). Never retried."""
        wire, log_as = self._prepare(key, vals, 'send')
        self.write(wire) if log_as is None else self.write(wire, log_as=log_as)

    def ask(self, key: str, **vals) -> str:
        """Send a registered query through self.query and return the reply."""
        wire, log_as = self._prepare(key, vals, 'ask')
        return self.query(wire) if log_as is None else self.query(wire, log_as=log_as)

    def describe_commands(self) -> list:
        """The merged registry for the UI: one dict per command."""
        reg = self._registry()
        ov = self._cmd_ov or {}
        owners = cmdreg.command_owners(self)
        out = []
        for key, cmd in reg.items():
            ok, why = cmdreg.is_overridable(cmd)
            cur = ov.get(key)
            out.append(dict(key=key, name=cmd.name, description=cmd.description, factory=cmd.template,
                            current=cur[0] if cur else cmd.template, overridden=bool(cur), uid=self._uid_text(cur[1]) if cur else None,
                            kind=cmd.kind, risk=cmd.risk, readback=cmd.readback, verified=cmd.verified, ref=cmd.ref,
                            overridable=ok, locked_reason=why, editable=ok, owner=owners.get(key, ''),
                            placeholders=sorted(cmd.placeholders)))
        return out

    # ---- reset to default settings (Stage 7) -------------------------------------------------------------
    def reset_to_defaults(self) -> ResetReport:
        """Put the instrument in its default state before any test point. Returns a ResetReport; never raises.
        Order: reset (*RST or equivalent, a locked command), *CLS, wait for completion (*OPC?), drain the error queue (leftovers are
        warnings), then the model's own known-state steps. Writes are sent once and never retried; only the read-only queries
        (*OPC?, error queue) go through query_retry. The first failed step ends the sequence with ok=False."""
        rep = ResetReport(self.label)
        if self.RESET_EXEMPT:
            rep.exempt = True
            rep.steps.append(ResetStep('exempt', True, f'{self.RESET_EXEMPT} Known state: {self.RESET_KNOWN_STATE or "n/a"}'))
            self.log.add('--', f'RESET EXEMPT: {self.RESET_EXEMPT}', self.label)
            return rep
        reg = self._registry()
        if 'reset' not in reg:
            rep.ok = False
            rep.steps.append(ResetStep('reset', False, 'driver declares no reset command and no documented exemption'))
            return rep
        plan: list[tuple[str, Callable[[], Any]]] = [(f'reset ({reg["reset"].template})', lambda: self.send('reset'))]
        if 'status.clear' in reg:
            plan.append((f'clear status ({reg["status.clear"].template})', lambda: self.send('status.clear')))
        if 'opc.query' in reg:
            plan.append(('wait for completion (*OPC?)', self._reset_wait))
        plan.append(('drain error queue', lambda: self._reset_drain(rep)))
        plan += list(self._reset_extra())
        for name, fn in plan:
            try:
                detail = fn()
            except Exception as exc:                                    # includes SafetyError / TransportError
                rep.ok = False
                rep.steps.append(ResetStep(name, False, f'{type(exc).__name__}: {exc}'))
                self.log.add('!!', f'RESET step failed: {name}: {exc}', self.label)
                break
            rep.steps.append(ResetStep(name, True, detail if isinstance(detail, str) else ''))
        return rep

    def _reset_wait(self):
        """*OPC? after the reset (read-only: may be retried). The transport timeout is raised while waiting, then put back as it was."""
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(self.RESET_OPC_TIMEOUT, prev or 0.0))
        try:
            self.query_retry('opc.query', attempts=3, delay=1.0)
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)

    @staticmethod
    def _error_code(reply: str):
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            return int(float(code))
        except ValueError:
            return None

    def _reset_drain(self, rep, limit=10):
        """Read the error queue until empty (read-only). Anything found is logged and reported as a warning, not a failure."""
        if 'err.query' not in self._registry():
            return 'no error-queue command'
        found = []
        for _ in range(limit):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        for f in found:
            rep.warnings.append(f'error queue after reset: {f}')
            self.log.add('!!', f'error queue after reset: {f}', self.label)
        return f'{len(found)} entr{"y" if len(found) == 1 else "ies"} drained' if found else 'queue empty'

    def _reset_extra(self):
        """Model-specific known-state steps after the reset: [(name, callable)]. Override: re-enter remote, restore the settings connect()
        makes, confirm outputs off / standby. A callable raises on failure."""
        return []

    # ---- helpers for the "set, read back, compare" pattern used throughout calibration work
    @staticmethod
    def close_to(actual, expected, rel=1e-5, abs_=1e-9):
        import math
        return math.isclose(actual, expected, rel_tol=rel, abs_tol=abs_)
