"""Fault injection for the stop-on-surprise wiring tests (tests/test_surprise_wiring.py).  Not a test module.

FaultTransport wraps a simulated transport and changes ONE reply (or raises a timeout) when a rule matches; everything else passes through, so the
rest of the run is the real simulated bench.  A rule can be limited to a query that follows a given write (`after`), which is how "error-queue entry
after a write" is injected.  `Counter` handlers answer the Stop / Continue dialog and count how often it was shown."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]

from drivers.transport import TransportError  # noqa: E402


class Rule:
    def __init__(self, query, reply=None, after=None, nth=1, times=1, timeout=False):
        self.query, self.reply, self.after, self.nth, self.times, self.timeout = query.upper(), reply, (after or '').upper(), nth, times, timeout
        self.seen = 0
        self.fired = 0


class FaultTransport:
    """Same interface as the wrapped transport (everything else is delegated)."""

    def __init__(self, inner, *rules):
        self.inner = inner
        self.rules = list(rules)
        self.last_write = ''
        self.writes = []                      # every write, in order
        self.queries = []                     # every query, in order

    _OWN = ('inner', 'rules', 'last_write', 'writes', 'queries')

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __setattr__(self, name, value):          # state the virtual operator sets (terminals ...) belongs to the simulated instrument
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)

    def add(self, *rules):
        self.rules.extend(rules)
        return self

    def write(self, text):
        self.last_write = text
        self.writes.append(text)
        return self.inner.write(text)

    def query(self, text):
        self.queries.append(text)
        for r in self.rules:
            if not text.upper().startswith(r.query):
                continue
            if r.after and not self.last_write.upper().startswith(r.after):
                continue
            r.seen += 1
            if r.seen >= r.nth and r.fired < r.times:
                r.fired += 1
                if r.timeout:
                    raise TransportError('simulated timeout')
                return r.reply                                      # the real instrument is not asked: the reply is replaced
        return self.inner.query(text)


class Dialog:
    """A handler for Guard: records every Surprise, answers from a list (default Stop)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, s):
        self.seen.append(s)
        return self.answers.pop(0) if self.answers else False

    @property
    def count(self):
        return len(self.seen)
