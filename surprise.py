"""Stop on surprise: a procedure runs at full speed and pauses ONLY when the instrument does something unexpected.

Three surprises, nothing else:
  (a) 'reply'     a reply that is not in the expected format (empty, timeout, a prompt character where a value was expected)
  (b) 'readback'  a write whose read-back does not match what was set
  (c) 'errqueue'  a non-empty error queue after a write

ONE dialog (command, reply, what was expected, the last ~20 log lines) offers Stop / Continue.  Stop raises SurpriseStop (an InstrumentError, so the
engine's existing handler puts the instruments in standby / off and shows its error).  Continue is logged and the run goes on.  A clean run never asks
anything.  A WRITE IS NEVER RETRIED here (set, read back, compare, once).  Only a read-only query that timed out is retried once (the standing rule).

Opt-in, no shared file edited: nothing in drivers/base.py or drivers/transport.py changes.  A NEW driver gets it by inheriting SurpriseMixin
(drivers/_template.py does); an existing driver is not touched.  The mixin only adds methods (ask_checked / set_checked / errq_checkpoint) that the
driver calls; plain send() / ask() behave exactly as before.  `attach_guard(instrument, ...)` wraps ONE instrument instance without editing its class,
for an owner who decides to turn it on for an existing engine (see NOTES.md, 'Readiness check and stop-on-surprise': the blast radius of doing that).

Engines that are wired from the engine file (no driver edited) use attach_guard (replies, timeouts) and `checked` (the driver's own error-queue /
read-back exception becomes the dialog).  A surprise can be `stop_only`: the dialog then has no Continue button, and the guard stops whatever the
handler answers (used where going on would use a reply that is not there, or would enable an output after a refusal).

Demo mode: the guard is OFF on a virtual (demo) command log unless force=True (tests), so the simulated bench never pops a dialog.
This module has no Tk import at load; the dialog (tk_handler) imports tkinter when it is first used."""
from __future__ import annotations

import math
import queue
import re
import threading
from dataclasses import dataclass, field

from drivers.base import InstrumentError, SafetyError
from drivers.transport import TransportError

PROMPT_CHARS = ('=>', '?>', '!>')           # Fluke 8808A style prompts (echoed after a command); a reply that IS one of these is a surprise
LOG_TAIL = 20

KINDS = {'reply': 'Unexpected reply', 'readback': 'Read-back does not match', 'errqueue': 'Error queue not empty'}


class SurpriseStop(InstrumentError):
    """The operator chose Stop (or nobody could be asked).  The engine's normal error path then puts the instruments in standby / off."""

    def __init__(self, surprise):
        super().__init__(surprise.headline())
        self.surprise = surprise


@dataclass
class Surprise:
    kind: str                       # 'reply' | 'readback' | 'errqueue'
    instrument: str
    command: str                    # as logged (secrets already masked)
    reply: str
    expected: str
    detail: str = ''
    log_tail: list = field(default_factory=list)
    stop_only: bool = False         # Continue is not offered (the run cannot safely or meaningfully go on from here)

    def headline(self):
        return f'{KINDS.get(self.kind, self.kind)}: {self.instrument} {self.command!r} -> {self.reply!r} (expected {self.expected})'

    def lines(self):
        out = [f'Instrument:  {self.instrument}', f'Command:     {self.command}', f'Reply:       {self.reply!r}', f'Expected:    {self.expected}']
        if self.detail:
            out.append(f'Note:        {self.detail}')
        return out


# ------------------------------------------------------------------------------------------------------------ format checks
def _num(text):
    try:
        return float(str(text).strip().split(',')[0].replace('+', ''))
    except ValueError:
        return None


def check_reply(reply, expect):
    """None when the reply is fine, else a short reason.  expect: 'float' | 'int' | 'text' | 'any' | a compiled regex / pattern string."""
    r = (reply or '').strip()
    if not r:
        return 'empty reply'
    if r in PROMPT_CHARS:
        return f'prompt character {r!r} where a value was expected'
    if expect in (None, 'any', 'text'):
        return None
    if expect == 'float':
        return None if _num(r) is not None else 'not a number'
    if expect == 'int':
        v = _num(r)
        return None if v is not None and float(v).is_integer() else 'not an integer'
    rx = expect if hasattr(expect, 'match') else re.compile(str(expect))
    return None if rx.match(r) else f'does not match {getattr(rx, "pattern", rx)}'


def error_queue_clean(reply):
    """True for the empty-queue replies: '0,"No error"', '+0,"No error"', '0'.  Override per driver (ERR_CLEAN) for other formats."""
    r = (reply or '').strip()
    code = _num(r)
    if code is not None:
        return code == 0
    return 'no error' in r.lower()


# ------------------------------------------------------------------------------------------------------------ the guard
class Guard:
    """The decision point.  handler(Surprise) -> True to continue, False to stop.  No handler: stop (nobody to ask)."""

    def __init__(self, instrument, handler=None, enabled=True, log_lines=LOG_TAIL):
        self.inst = instrument
        self.handler = handler
        self.enabled = enabled
        self.log_lines = log_lines
        self.raised = []                    # every Surprise seen (for the run summary / tests)

    def surprise(self, kind, command, reply, expected, detail='', stop_only=False):
        """Log it, ask once, and either return (Continue) or raise SurpriseStop (Stop).
        stop_only: Continue is not offered (an engine uses it where going on would use a reply that is not there, or would enable an output after a
        refusal); the dialog shows Stop only and whatever the handler answers is Stop."""
        inst = self.inst
        s = Surprise(kind, inst.label, command, reply, expected, detail, log_tail=inst.log.lines()[-self.log_lines:], stop_only=bool(stop_only))
        self.raised.append(s)
        inst.log.add('!!', f'SURPRISE {kind}: {command!r} -> {reply!r} (expected {expected})' + (f' [{detail}]' if detail else ''), inst.label)
        go = False
        if self.handler is not None:
            try:
                go = bool(self.handler(s))
            except Exception:
                go = False
        if stop_only:
            go = False
            inst.log.add('!!', 'SURPRISE: Continue is not offered here; Stop', inst.label)
        else:
            inst.log.add('!!', 'SURPRISE: operator chose ' + ('Continue' if go else 'Stop'), inst.label)
        if not go:
            raise SurpriseStop(s)
        return s


def _display(inst, key, vals):
    """The command as it is logged (a password is masked)."""
    verb = 'ask' if inst._registry()[key].kind == 'query' else 'send'
    wire, log_as = inst._prepare(key, vals, verb)
    return log_as or wire


class SurpriseMixin:
    """Add to a NEW driver:  class MyModel(SurpriseMixin, Instrument).  Off until enable_surprise() (or the engine) turns it on."""
    ERR_CLEAN = staticmethod(error_queue_clean)         # override when the queue's empty reply looks different
    _guard: Guard | None = None

    def enable_surprise(self, handler=None, force=False):
        """Turn stop-on-surprise on for this instrument.  A virtual (demo) log is left alone unless force=True."""
        on = force or not getattr(self.log, 'virtual', False)
        self._guard = Guard(self, handler, enabled=on)
        return self._guard

    def disable_surprise(self):
        self._guard = None

    def _g(self):
        g = self._guard
        return g if g is not None and g.enabled else None

    def _reply_problem(self, key, vals, reply, expect, g):
        why = check_reply(reply, expect)
        if why:
            if g is None:
                raise InstrumentError(f'{self.label}: {_display(self, key, vals)} -> {reply!r}: {why}')
            g.surprise('reply', _display(self, key, vals), reply, f'{expect or "a value"} ({why})')

    def ask_checked(self, key, expect='float', **vals):
        """Query a registered command and check the reply format.  Read-only: a timeout is retried ONCE (query_retry), then it is a surprise."""
        g = self._g()
        try:
            reply = self.ask(key, **vals)
        except TransportError as exc:
            self.log.add('!!', f'{key}: {exc}; read-only query retried once', self.label)
            try:
                reply = self.query_retry(key, attempts=1, delay=0.5, values=vals)
            except InstrumentError as exc2:
                if g is None:
                    raise
                g.surprise('reply', _display(self, key, vals), '', str(expect), f'timeout twice: {exc2}')
                return ''
        self._reply_problem(key, vals, reply, expect, g)
        return reply

    def set_checked(self, key, value, name='value', tol=None, check_errors=True, **vals):
        """Set / read back / compare, ONCE.  The read-back command is the one the registry pairs with `key` (Cmd.readback).
        A numeric value is compared with close_to; anything else compares as text.  No retry of the write.  After the write the error queue is
        read (err.query, read-only) when the driver has one: a non-empty queue is the third surprise."""
        reg = self._registry()
        rb = reg[key].readback
        if not rb:
            raise InstrumentError(f'{key}: no read-back command declared (Cmd.readback) - a write must be read back')
        g = self._g()
        shown = {name: value, **vals}
        self.send(key, **shown)                                       # never retried
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        reply = self.ask_checked(rb, expect='float' if numeric else 'any')
        if numeric:
            got = _num(reply)
            ok = got is not None and (self.close_to(got, float(value)) if tol is None else math.isclose(got, float(value), abs_tol=tol))
        else:
            ok = reply.strip().upper() == str(value).strip().upper()
        if not ok:
            if g is None:
                raise InstrumentError(f'{self.label}: {_display(self, key, shown)}: set {value}, instrument reports {reply.strip()!r}')
            g.surprise('readback', _display(self, key, shown), reply.strip(), f'{value}', f'read back with {rb}')
        if check_errors:
            self.errq_checkpoint(_display(self, key, shown))
        return reply

    def errq_checkpoint(self, after=''):
        """Read the error queue ONCE (read-only).  Empty -> nothing.  Not empty -> surprise (stop, or continue after the operator saw it).
        Without a guard a non-empty queue raises InstrumentError, like the existing drivers.  No err.query command -> nothing to check."""
        if 'err.query' not in self._registry():
            return None
        reply = self.query_retry('err.query', attempts=2, delay=0.5).strip()
        if self.ERR_CLEAN(reply):
            return None
        g = self._g()
        if g is None:
            raise InstrumentError(f'{self.label}: error queue after {after!r}: {reply}')
        g.surprise('errqueue', after or 'err.query', reply, 'empty error queue', 'read with err.query')
        return reply


def attach_guard(instrument, handler=None, force=False, expect=None, stop_only=False, skip=()):
    """Opt-in for an EXISTING driver instance (class untouched): replaces ask() on this one object by a checked ask.  A reply that is empty, is a
    prompt character, or does not fit `expect` (a dict {registry key: 'float' | 'int' | regex}; other keys are only checked for empty / prompt) is a
    surprise.  A query that times out is retried ONCE (read-only, the standing rule), then it is a surprise with an empty reply.  Write / read-back /
    error-queue checks stay in the driver (route them with `checked`).  stop_only: True (every reply surprise offers Stop only) or a collection of
    registry keys.  skip: registry keys whose replies are left exactly as they are (not checked, no retry): used for the replies a driver itself turns
    into a SafetyError (an output state it could not confirm), so the guard never replaces that hard stop.  Returns the Guard (None on a demo log: the
    simulated bench never prompts)."""
    if getattr(instrument.log, 'virtual', False) and not force:
        return None
    g = Guard(instrument, handler)
    plain = instrument.ask
    expect = dict(expect or {})

    def only(key):
        return stop_only is True or (not isinstance(stop_only, bool) and key in (stop_only or ()))

    skipped = frozenset(skip or ())

    def ask(key, **vals):
        if key in skipped:
            return plain(key, **vals)
        want = expect.get(key, 'any')
        try:
            reply = plain(key, **vals)
        except TransportError as exc:
            instrument.log.add('!!', f'{key}: {exc}; read-only query retried once', instrument.label)
            try:
                reply = instrument.query_retry(key, attempts=1, delay=0.5, values=vals)
            except InstrumentError as exc2:
                g.surprise('reply', _display(instrument, key, vals), '', str(want), f'timeout twice: {exc2}', stop_only=only(key))
                return ''
        why = check_reply(reply, want)
        if why:
            g.surprise('reply', _display(instrument, key, vals), reply, f'{want if want != "any" else "a value"} ({why})', stop_only=only(key))
        return reply

    instrument.ask = ask
    instrument._guard = g
    return g


def _last_exchange(inst, since=0):
    """(command, reply) of the instrument's last query as logged.  A driver that drains the error queue in a loop (ERR? until empty) repeats the same
    query: the command is that query and the reply is every non-empty-queue answer of the run of repeats (the final 'No error' is left out)."""
    exchanges = []                                   # [command, reply or None]
    for _t, label, d, txt in inst.log.entries[since:][-60:]:
        if label != inst.label:
            continue
        if d == '>>':
            exchanges.append([txt, None])
        elif d == '<<' and exchanges and exchanges[-1][1] is None:
            exchanges[-1][1] = txt
    if not exchanges:
        return '', ''
    cmd, last = exchanges[-1]
    bad = []
    for i, (c, r) in enumerate(reversed(exchanges)):
        if c != cmd:
            break
        if r is None or error_queue_clean(r):
            if i == 0:
                continue                         # the closing 'No error' of a drain loop
            break                                # an earlier, separate check
        if r.strip():
            bad.append(r)                        # (empty answers are not listed: an all-empty drain leaves the reply '', a bad reply)
    bad.reverse()
    return cmd, ' | '.join(bad) if bad else (last or '')


def checked(instrument, call, *args, kind='errqueue', expected='empty error queue', stop_only=False, classify=None, **kw):
    """Engine-level route for a driver check that raises InstrumentError itself (the error-queue check after a write, or a read-back compare inside a
    driver method).  `call` is the driver's own bound method, e.g. checked(dmm, dmm.check_errors, 'configuring ...').

      * No guard on the instrument (headless, demo): `call(*args, **kw)` exactly as before - same commands, same exception.
      * With a guard: the same call.  SurpriseStop (from a guarded ask) and SafetyError (a safe state not confirmed) pass through untouched; any other
        InstrumentError the check raises is shown as the surprise `kind` with the instrument's last reply, the command and the driver's own message.
        Stop raises SurpriseStop.  Continue (only when stop_only is False) returns None: the check had already read the queue; nothing is sent or
        retried.  Use stop_only=True where the driver call fails part-way (a read-back compare) or where going on would enable an output.
    classify(exc, command, reply) -> None | dict(kind=, expected=, stop_only=): for a driver call that does several things (a setting with its read-back
    compare AND the error-queue check in one method).  The engine says what the failure was from the exchange the call itself made; None re-raises the
    driver's exception untouched (it was not an exchange with the instrument: a range check before anything was sent).
    The driver's pass/fail test is not copied: the driver decides, this only routes its exception."""
    g = getattr(instrument, '_guard', None)
    if g is None or not g.enabled:
        return call(*args, **kw)
    start = len(instrument.log.entries)
    try:
        return call(*args, **kw)
    except (SurpriseStop, SafetyError):
        raise
    except InstrumentError as exc:
        cmd, reply = _last_exchange(instrument, start)           # only what the check itself sent
        if classify is not None:
            how = classify(exc, cmd, reply)
            if how is None:
                raise
            kind, expected, stop_only = how.get('kind', kind), how.get('expected', expected), how.get('stop_only', stop_only)
        if check_reply(reply, 'any'):                            # no usable answer at all (empty, or a prompt character): a bad reply, never Continue
            g.surprise('reply', cmd, reply, f'a reply ({check_reply(reply, "any")})', str(exc), stop_only=True)
        g.surprise(kind, cmd, reply, expected, str(exc), stop_only=stop_only)
        return None


# ------------------------------------------------------------------------------------------------------------ the dialog
class _TkAsker:
    """Shows the dialog on the Tk thread for a worker thread.  The worker never calls Tk: it queues a request and waits; a poller that runs ON the Tk
    thread (root.after, started where the handler is made) shows the dialog and answers.  If nothing picks the request up within START_WAIT seconds
    (no poller running: no mainloop, or the handler was made on a thread that cannot schedule) the answer is Stop, so a run can never hang here."""
    START_WAIT = 5.0
    POLL_MS = 50

    def __init__(self, root, title):
        self.root, self.title = root, title
        self.q = queue.Queue()
        self.alive = True
        try:
            root.after(self.POLL_MS, self._tick)
        except Exception:
            self.alive = False

    def _tick(self):
        try:
            while True:
                req = self.q.get_nowait()
                if req['cancelled']:
                    continue
                req['started'].set()
                try:
                    req['go'] = bool(_dialog(self.root, self.title, req['s']))
                except Exception:
                    req['go'] = False
                req['done'].set()
        except queue.Empty:
            pass
        try:
            self.root.after(self.POLL_MS, self._tick)
        except Exception:
            self.alive = False

    def ask(self, s):
        req = dict(s=s, started=threading.Event(), done=threading.Event(), go=False, cancelled=False)
        if threading.current_thread() is threading.main_thread():       # already on the Tk thread: just show it (modal)
            try:
                return bool(_dialog(self.root, self.title, s))
            except Exception:
                return False
        self.q.put(req)
        if not req['started'].wait(self.START_WAIT):
            req['cancelled'] = True
            return False
        req['done'].wait()
        return req['go']


def tk_handler(root, title='Stop on surprise'):
    """A handler for Guard: ONE Tk dialog, True (Continue) / False (Stop).  Make it on the Tk thread (where the Run button's handler runs) before the
    worker thread starts; the worker's surprise then waits for the operator without touching Tk itself."""
    return _TkAsker(root, title).ask


def _dialog(root, title, s):
    import tkinter as tk
    from tkinter import ttk
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    result = {'go': False}
    body = ttk.Frame(win, padding=12)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text=KINDS.get(s.kind, s.kind), font=('TkDefaultFont', 11, 'bold')).pack(anchor='w')
    ttk.Label(body, text='\n'.join(s.lines()), justify='left').pack(anchor='w', pady=(6, 6))
    if getattr(s, 'stop_only', False):
        ttk.Label(body, text='Continue is not offered here: the run cannot safely go on from this point.').pack(anchor='w', pady=(0, 6))
    ttk.Label(body, text=f'Last {len(s.log_tail)} log lines:').pack(anchor='w')
    box = tk.Text(body, width=100, height=12, wrap='none')
    box.insert('1.0', '\n'.join(s.log_tail))
    box.configure(state='disabled')
    box.pack(fill='both', expand=True)
    row = ttk.Frame(body)
    row.pack(anchor='e', pady=(8, 0))

    def pick(go):
        result['go'] = go
        win.destroy()

    stop = ttk.Button(row, text='Stop', command=lambda: pick(False))
    cont = None if getattr(s, 'stop_only', False) else ttk.Button(row, text='Continue', command=lambda: pick(True))
    stop.pack(side='left', padx=4)
    if cont is not None:
        cont.pack(side='left', padx=4)
    win.protocol('WM_DELETE_WINDOW', lambda: pick(False))      # closing the window is Stop
    win._surprise = dict(stop=stop, cont=cont, text=box)
    stop.focus_set()
    try:
        win.grab_set()
    except tk.TclError:
        pass
    root.wait_window(win)
    return result['go']
