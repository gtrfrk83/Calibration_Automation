"""Base class for every instrument driver.

Rules the base enforces so individual drivers stay small and consistent:
  * every command that crosses the wire is logged (CommandLog)
  * writes are never retried (their effect is unknown after a failure); read-only queries may be
  * a driver states how to recognise its own model (IDN_MATCH) and refuses to talk to anything else
  * cleanup() puts the instrument in a safe state and is called even after errors
"""
from __future__ import annotations

import time

from .transport import CommandLog, Transport, TransportError


class InstrumentError(RuntimeError):
    """The instrument did not do what was asked (readback mismatch, wrong model, bad reply)."""


class SafetyError(InstrumentError):
    """A safe state could not be confirmed. Operator must check the front panel."""


class Instrument:
    MODEL = ''                # human name, e.g. 'Fluke 5560A'
    IDN_MATCH: tuple = ()     # any of these substrings (case-insensitive) must appear in *IDN?
    DEFAULT_TIMEOUT = 10.0

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

    def query_retry(self, cmd: str, attempts=3, delay=0.5) -> str:
        """Read-only queries only. Writes must never go through here."""
        last = None
        for n in range(attempts):
            try:
                return self.query(cmd)
            except TransportError as exc:
                last = exc
                if n + 1 < attempts:
                    time.sleep(delay * (n + 1))
        raise InstrumentError(f'{cmd!r} failed after {attempts} attempts: {last}') from last

    # ---- helpers for the "set, read back, compare" pattern used throughout calibration work
    @staticmethod
    def close_to(actual, expected, rel=1e-5, abs_=1e-9):
        import math
        return math.isclose(actual, expected, rel_tol=rel, abs_tol=abs_)
