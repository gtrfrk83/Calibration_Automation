"""Teledyne LeCroy WaveSurfer 4104HD (MAUI) - commands used by the verification procedures.

Settings are written through the VBS automation interface, which is what the working procedures use:
    write:  VBS 'app.Acquisition.C1.VerScale=0.01'
    read:   VBS? "return=app.Acquisition.C1.VerScale"
Every setter reads back and compares. Writes are never retried; read-only queries are.

Timing (v52): MAUI acts on VBS writes in the background, so a query sent right after a coupling or
bandwidth change can arrive while the front-end relays are switching. If that read fails, the USB
session is left out of step even though the scope itself is fine, and a plain retry on the same
session fails the same way. So relay changes get RELAY_SETTLE before the next command, and failed
read-only queries recover the session (device clear, then close/reopen) before retrying.
"""
from __future__ import annotations

import math
import time

from .base import Instrument, InstrumentError
from .transport import TransportError

P1 = 'app.Measure.P1'


class WaveSurfer4104HD(Instrument):
    MODEL = 'LeCroy WaveSurfer 4104HD'
    IDN_MATCH = ('LECROY', 'TELEDYNE')
    DEFAULT_TIMEOUT = 10.0
    RELAY_SETTLE = 0.4      # s after a coupling / bandwidth-limit write (front-end relays switch)

    # ---- VBS primitives ------------------------------------------------------------------------
    @staticmethod
    def _parse(reply: str) -> str:
        return reply.strip().removeprefix('VBS').strip().strip('"\'')

    # ---- read-only retries with USB session recovery ---------------------------------------------
    def _recover_clear(self):
        self.log.add('--', 'read failed: device clear before retry', self.label)
        self.t.clear()

    def _recover_reopen(self):
        self.log.add('--', 'read failed: closing and reopening the USB session before retry', self.label)
        self.t.close()
        time.sleep(1.0)
        self.t.open()
        self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def query_retry(self, cmd: str, attempts=3, delay=0.5) -> str:
        """Read-only queries only (writes never come through here and are never replayed).
        Before the 2nd attempt the session gets a device clear; before the 3rd it is closed and reopened."""
        recoveries = (self._recover_clear, self._recover_reopen)
        last = None
        for n in range(attempts):
            try:
                return self.query(cmd)
            except TransportError as exc:
                last = exc
                if n + 1 < attempts:
                    time.sleep(delay * (n + 1))
                    try:
                        recoveries[min(n, len(recoveries) - 1)]()
                    except TransportError as rexc:
                        last = rexc
        raise InstrumentError(f'{cmd!r} failed after {attempts} attempts '
                              f'(device clear and session reopen tried): {last}') from last

    def vbs_get(self, path: str) -> str:
        return self._parse(self.query_retry(f'VBS? "return={path}"'))

    def vbs_get_float(self, path: str) -> float:
        value = float(self.vbs_get(path))
        if not math.isfinite(value):
            raise InstrumentError(f'{path} returned a non-finite value')
        return value

    def vbs_set_number(self, path: str, value):
        self.write(f"VBS '{path}={value}'")

    def vbs_set_text(self, path: str, text: str):
        self.write(f"""VBS '{path}="{text}" '""")

    def _set_text_verified(self, path, text, settle=0.0):
        self.vbs_set_text(path, text)
        if settle:
            time.sleep(settle)
        got = self.vbs_get(path)
        if got.casefold() != text.casefold():
            raise InstrumentError(f'{path}: set {text!r} but scope reports {got!r}')

    def handshake(self, attempts=2):
        """Read-only USB check; if the session has gone stale, close and reopen once (never replays writes)."""
        probe = f'{self._ch(1)}.VerScale'
        try:
            self._parse(self.query_retry(f'VBS? "return={probe}"', attempts=attempts))
        except InstrumentError:
            self.t.close()
            time.sleep(1.0)
            self.t.open()
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
            self._parse(self.query_retry(f'VBS? "return={probe}"', attempts=attempts))

    # ---- vertical ------------------------------------------------------------------------
    @staticmethod
    def _ch(channel) -> str:
        return f'app.Acquisition.C{channel}'

    def set_vertical_scale(self, channel, volts_per_div, settle=0.35):
        path = f'{self._ch(channel)}.VerScale'
        self.vbs_set_number(path, volts_per_div)
        time.sleep(settle)
        actual = self.vbs_get_float(path)
        if not math.isclose(actual, volts_per_div, rel_tol=0.01, abs_tol=1e-7):
            raise InstrumentError(f'CH{channel} scale: requested {volts_per_div} V/div, scope reports {actual}')
        return actual

    def set_vertical_offset(self, channel, volts, settle=0.4, tolerance=0.001):
        path = f'{self._ch(channel)}.VerOffset'
        self.vbs_set_number(path, volts)
        time.sleep(settle)
        actual = self.vbs_get_float(path)
        if not math.isclose(actual, volts, abs_tol=tolerance):
            raise InstrumentError(f'CH{channel} offset: requested {volts} V, scope reports {actual}')
        return actual

    def ensure_zero_offset(self, channel, tolerance=0.001):
        """Read first; only write when needed (a failed write is never replayed)."""
        path = f'{self._ch(channel)}.VerOffset'
        if abs(self.vbs_get_float(path)) > tolerance:
            self.vbs_set_number(path, 0)
            time.sleep(0.3)
        offset = self.vbs_get_float(path)
        if abs(offset) > tolerance:
            raise InstrumentError(f'CH{channel} offset not zero: {offset}')

    def set_coupling(self, channel, coupling):
        """coupling: DC1M, DC50, AC1M (VBS names)."""
        self._set_text_verified(f'{self._ch(channel)}.Coupling', coupling, settle=self.RELAY_SETTLE)

    def set_bandwidth_limit(self, channel, limit):
        """limit: 'Full', '20MHz', ..."""
        self._set_text_verified(f'{self._ch(channel)}.BandwidthLimit', limit, settle=self.RELAY_SETTLE)

    def set_coupling_legacy(self, channel_name, coupling):
        """Classic remote command, e.g. 'C1:CPL D50' (used by the impedance test; value is D50/D1M/A1M)."""
        self.write(f'{channel_name}:CPL {coupling}')
        reply = self.query(f'{channel_name}:CPL?').strip().upper()
        if reply.split()[-1].strip(',') != coupling:
            raise InstrumentError(f'Coupling readback mismatch: requested {coupling}, returned {reply!r}')

    def configure_dc_input(self, channel):
        """DC 1 MOhm + 20 MHz bandwidth limit - the input state for DCV and offset tests."""
        self.write(f"VBS '{self._ch(channel)}.Coupling=\"DC1M\" '")
        time.sleep(self.RELAY_SETTLE)
        self.write(f"VBS '{self._ch(channel)}.BandwidthLimit=\"20MHz\" '")
        time.sleep(self.RELAY_SETTLE)
        coupling = self.vbs_get(f'{self._ch(channel)}.Coupling')
        bandwidth = self.vbs_get(f'{self._ch(channel)}.BandwidthLimit')
        if coupling.casefold() != 'dc1m' or bandwidth.casefold() != '20mhz':
            raise InstrumentError(f'CH{channel} input setup failed: coupling={coupling!r}, '
                                  f'bandwidth={bandwidth!r}; required DC1M / 20MHz')

    # ---- horizontal / trigger ------------------------------------------------------------------------
    def set_timebase(self, seconds_per_div, settle=0.4):
        path = 'app.Acquisition.Horizontal.HorScale'
        self.vbs_set_number(path, f'{seconds_per_div:.12g}')
        time.sleep(settle)
        actual = self.vbs_get_float(path)
        if not math.isclose(actual, seconds_per_div, rel_tol=0.02, abs_tol=1e-13):
            raise InstrumentError(f'Timebase: requested {seconds_per_div:.12g} s/div, scope reports {actual:.12g}')

    def set_edge_trigger_source(self, channel):
        self.write("VBS 'app.Acquisition.Trigger.Type=\"Edge\"'")
        self.write(f"VBS 'app.Acquisition.Trigger.Edge.Source=\"C{channel}\"'")
        source = self.vbs_get('app.Acquisition.Trigger.Edge.Source')
        if source.strip().upper() != f'C{channel}':
            raise InstrumentError(f'Trigger source {source!r} does not match CH{channel}')

    # ---- measurement P1 ------------------------------------------------------------------------
    def configure_p1(self, channel, engine, show=True):
        """engine: 'Mean', 'StandardDeviation' (RMS noise) or 'PkPk'. Verified by readback."""
        want = engine.casefold()
        current = self.vbs_get(f'{P1}.ParamEngine')
        if current.casefold() != want:
            self.write(f"""VBS '{P1}.ParamEngine="{engine}" ' """)
            time.sleep(0.5)
            current = self.vbs_get(f'{P1}.ParamEngine')
        accepted = {want} | ({'peaktopeak'} if want == 'pkpk' else set())
        if current.casefold() not in accepted:
            raise InstrumentError(f'P1 engine {current!r}, expected {engine}')
        target = f'C{channel}'
        if self.vbs_get(f'{P1}.Source1').upper() != target:
            self.write(f"""VBS '{P1}.Source1="{target}" ' """)
            time.sleep(0.5)
        source = self.vbs_get(f'{P1}.Source1')
        if source.upper() != target:
            raise InstrumentError(f'P1 source {source!r}, expected {target}')
        if show:
            self.write(f"VBS '{P1}.View=True ' ")

    def read_p1(self) -> float:
        """Current P1 value (volts for Mean / StandardDeviation / PkPk)."""
        return self.vbs_get_float(f'{P1}.Out.Result.Value')

    def read_p1_settled(self, settle_s, discard_gap_s=0.5):
        """Wait, discard one possibly stale reading, then return a fresh one."""
        time.sleep(settle_s)
        self.read_p1()
        time.sleep(discard_gap_s)
        return self.read_p1()
