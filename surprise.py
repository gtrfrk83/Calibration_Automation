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

Demo mode: the guard is OFF on a virtual (demo) command log unless force=True (tests), so the simulated bench never pops a dialog.
This module has no Tk import at load; the dialog (tk_handler) imports tkinter when it is first used."""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field

from drivers.base import InstrumentError
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

    def surprise(self, kind, command, reply, expected, detail=''):
        """Log it, ask once, and either return (Continue) or raise SurpriseStop (Stop)."""
        inst = self.inst
        s = Surprise(kind, inst.label, command, reply, expected, detail, log_tail=inst.log.lines()[-self.log_lines:])
        self.raised.append(s)
        inst.log.add('!!', f'SURPRISE {kind}: {command!r} -> {reply!r} (expected {expected})' + (f' [{detail}]' if detail else ''), inst.label)
        go = False
        if self.handler is not None:
            try:
                go = bool(self.handler(s))
            except Exception:
                go = False
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


def attach_guard(instrument, handler=None, force=False):
    """Opt-in for an EXISTING driver instance (class untouched): replaces ask() on this one object by a checked ask (empty reply / prompt
    character -> surprise).  Write / read-back / error-queue checks stay in the driver.  Returns the Guard (None on a demo log)."""
    if getattr(instrument.log, 'virtual', False) and not force:
        return None
    g = Guard(instrument, handler)
    plain = instrument.ask

    def ask(key, **vals):
        reply = plain(key, **vals)
        why = check_reply(reply, 'any')
        if why:
            g.surprise('reply', _display(instrument, key, vals), reply, f'a value ({why})')
        return reply

    instrument.ask = ask
    instrument._guard = g
    return g


# ------------------------------------------------------------------------------------------------------------ the dialog
def tk_handler(root, title='Stop on surprise'):
    """A handler for Guard: shows ONE Tk dialog and returns True (Continue) / False (Stop).  Safe from the worker thread: the dialog is built on
    the Tk thread through root.after and the worker waits for the answer.  Called on the Tk thread itself it just builds the dialog (modal)."""
    def handler(s):
        box = {}
        done = threading.Event()

        def show():
            try:
                box['go'] = _dialog(root, title, s)
            except Exception:
                box['go'] = False
            finally:
                done.set()

        if threading.current_thread() is threading.main_thread():
            show()
        else:
            root.after(0, show)
            done.wait()
        return box.get('go', False)
    return handler


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
    cont = ttk.Button(row, text='Continue', command=lambda: pick(True))
    stop.pack(side='left', padx=4)
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
