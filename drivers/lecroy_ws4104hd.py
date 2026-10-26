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

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import TransportError

P1 = 'app.Measure.P1'


def _vbs(template, name, description='', *, kind='set', readback=None, verified=True, risk='normal', placeholders=None):
    return Cmd(template, name, description, placeholders=placeholders or {}, kind=kind, readback=readback, risk=risk, verified=verified,
               lang='vbs')


def _txt(name, sample):
    return {name: Placeholder('str', '', sample)}


_CH = {'ch': Placeholder('enum', '', '1', enum=('1', '2', '3', '4'))}      # analog channel 1-4 (the driver refuses anything else)
_NUM = Placeholder('float', '', 0.5)                                 # plain {value}: the text the old f-string gave
_UNV = 'Property path NOT verified on a 4104HD'

# Every command the driver sends. VBS commands are lang='vbs': under the cmdreg whitelist only the property path (app.Acquisition /
# Measure / Math ...) and the value of an override can change - never the VBS verb, the quotes or the read / write form.
# verified=True rests on the driver's own basis (the header docstring and the working procedures use these properties); the MAUI
# automation manual is not in the project, so no page is cited. The trigger slope / level / mode paths are NOT verified on a 4104HD
# (see the comment above set_trigger_slope). The three generic vbs.* keys take the whole path from the caller (the public helpers
# vbs_get / vbs_set_number / vbs_set_text); they are locked because a path-only edit of them is meaningless - edit the specific key.
# p1.engine.set / p1.source.set / p1.view.on end with a space after the closing quote: that is the text the procedures have always
# sent and it is kept byte for byte (cmdreg's VBS check therefore cannot accept an edited form of those three).
COMMANDS = {
    'vbs.get': _vbs('VBS? "return={path}"', 'Read any VBS property', 'Generic helper: the whole property path comes from the caller',
                    kind='query', risk='locked', placeholders=_txt('path', 'app.Acquisition.C1.VerScale')),
    'vbs.set.number': _vbs("VBS '{path}={value}'", 'Write any VBS numeric property', 'Generic helper: path and value come from the caller',
                           risk='locked', placeholders={**_txt('path', 'app.Acquisition.C1.VerScale'), **_txt('value', '0.5')}),
    'vbs.set.text': _vbs("VBS '{path}=\"{text}\" '", 'Write any VBS text property', 'Generic helper: path and text come from the caller',
                         risk='locked', placeholders={**_txt('path', 'app.Acquisition.C1.Coupling'), **_txt('text', 'DC1M')}),
    # vertical
    'vert.scale.set': _vbs("VBS 'app.Acquisition.C{ch}.VerScale={value}'", 'Vertical scale (V/div)', readback='vert.scale.get',
                           placeholders={**_CH, 'value': _NUM}),
    'vert.scale.get': _vbs('VBS? "return=app.Acquisition.C{ch}.VerScale"', 'Vertical scale read-back', kind='query', placeholders=_CH),
    'vert.offset.set': _vbs("VBS 'app.Acquisition.C{ch}.VerOffset={value}'", 'Vertical offset (V)', readback='vert.offset.get',
                            placeholders={**_CH, 'value': _NUM}),
    'vert.offset.get': _vbs('VBS? "return=app.Acquisition.C{ch}.VerOffset"', 'Vertical offset read-back', kind='query', placeholders=_CH),
    'coupling.set': _vbs("VBS 'app.Acquisition.C{ch}.Coupling=\"{coupling}\" '", 'Input coupling (DC1M, DC50, AC1M)',
                         'Also used for the DC 1 MOhm state of configure_dc_input', readback='coupling.get',
                         placeholders={**_CH, **_txt('coupling', 'DC1M')}),
    'coupling.get': _vbs('VBS? "return=app.Acquisition.C{ch}.Coupling"', 'Input coupling read-back', kind='query', placeholders=_CH),
    'bandwidth.set': _vbs("VBS 'app.Acquisition.C{ch}.BandwidthLimit=\"{limit}\" '", 'Bandwidth limit (Full, 20MHz ...)',
                          'Also used for the 20 MHz state of configure_dc_input', readback='bandwidth.get',
                          placeholders={**_CH, **_txt('limit', '20MHz')}),
    'bandwidth.get': _vbs('VBS? "return=app.Acquisition.C{ch}.BandwidthLimit"', 'Bandwidth limit read-back', kind='query', placeholders=_CH),
    # channel display (the noise test turns all four channels ON)
    'chan.view.set': _vbs("VBS 'app.Acquisition.C{ch}.View=True'", 'Show (turn ON) a channel', _UNV, readback='chan.view.get', verified=False,
                          placeholders=_CH),
    'chan.view.get': _vbs('VBS? "return=app.Acquisition.C{ch}.View"', 'Channel display read-back', _UNV, kind='query', verified=False, placeholders=_CH),
    'vert.invert.get': _vbs('VBS? "return=app.Acquisition.C{ch}.Invert"', 'Channel invert read-back', _UNV, kind='query', verified=False, placeholders=_CH),
    'vert.invert.off': _vbs("VBS 'app.Acquisition.C{ch}.Invert=False'", 'Turn the channel invert OFF', _UNV, readback='vert.invert.get', verified=False,
                            placeholders=_CH),
    # classic remote command (impedance test)
    'cpl.set': Cmd('{channel_name}:CPL {coupling}', 'Coupling (classic command)', 'Classic remote command, e.g. C1:CPL D50 (D50 / D1M / A1M)',
                   placeholders={**_txt('channel_name', 'C1'), **_txt('coupling', 'D50')}, kind='set', readback='cpl.query', verified=True),
    'cpl.query': Cmd('{channel_name}:CPL?', 'Coupling read-back (classic command)', placeholders=_txt('channel_name', 'C1'), kind='query',
                     verified=True),
    # horizontal / trigger
    'hor.scale.set': _vbs("VBS 'app.Acquisition.Horizontal.HorScale={seconds:.12g}'", 'Time base (s/div)', readback='hor.scale.get',
                          placeholders={'seconds': Placeholder('float', '.12g', 1e-3)}),
    'hor.scale.get': _vbs('VBS? "return=app.Acquisition.Horizontal.HorScale"', 'Time base read-back', kind='query'),
    'trig.type.edge': _vbs("VBS 'app.Acquisition.Trigger.Type=\"Edge\"'", 'Trigger type Edge'),
    'trig.source.set': _vbs("VBS 'app.Acquisition.Trigger.Edge.Source=\"C{channel}\"'", 'Edge trigger source', readback='trig.source.get',
                            placeholders=_txt('channel', '1')),
    'trig.source.get': _vbs('VBS? "return=app.Acquisition.Trigger.Edge.Source"', 'Edge trigger source read-back', kind='query'),
    'trig.slope.set': _vbs("VBS 'app.Acquisition.Trigger.Edge.Slope=\"{slope}\" '", 'Edge trigger slope (Positive / Negative)', _UNV,
                           readback='trig.slope.get', verified=False, placeholders=_txt('slope', 'Positive')),
    'trig.slope.get': _vbs('VBS? "return=app.Acquisition.Trigger.Edge.Slope"', 'Edge trigger slope read-back', _UNV, kind='query',
                           verified=False),
    'trig.level.set': _vbs("VBS 'app.Acquisition.Trigger.Edge.Level={volts:.6g}'", 'Edge trigger level (V)', _UNV,
                           readback='trig.level.get', verified=False, placeholders={'volts': Placeholder('float', '.6g', 0.5)}),
    'trig.level.get': _vbs('VBS? "return=app.Acquisition.Trigger.Edge.Level"', 'Edge trigger level read-back', _UNV, kind='query',
                           verified=False),
    'trig.mode.set': _vbs("VBS 'app.Acquisition.TriggerMode=\"{mode}\" '", 'Trigger mode (Auto / Normal / Single / Stopped)', _UNV,
                          readback='trig.mode.get', verified=False, placeholders=_txt('mode', 'Auto')),
    'trig.mode.get': _vbs('VBS? "return=app.Acquisition.TriggerMode"', 'Trigger mode read-back', _UNV, kind='query', verified=False),
    # measurement P1
    'p1.engine.set': _vbs("VBS 'app.Measure.P1.ParamEngine=\"{engine}\" ' ", 'P1 measurement (Mean, StandardDeviation, PkPk, Freq)',
                          readback='p1.engine.get', placeholders=_txt('engine', 'Mean')),
    'p1.engine.get': _vbs('VBS? "return=app.Measure.P1.ParamEngine"', 'P1 measurement read-back', kind='query'),
    'p1.source.set': _vbs("VBS 'app.Measure.P1.Source1=\"C{channel}\" ' ", 'P1 source channel', readback='p1.source.get',
                          placeholders=_txt('channel', '1')),
    'p1.source.get': _vbs('VBS? "return=app.Measure.P1.Source1"', 'P1 source read-back', kind='query'),
    'p1.view.on': _vbs("VBS 'app.Measure.P1.View=True ' ", 'Show the P1 parameter'),
    'p1.value.get': _vbs('VBS? "return=app.Measure.P1.Out.Result.Value"', 'P1 value', kind='query'),
}


COMMANDS['reset'] = cmdreg.reset_cmd(False, 'WaveSurfer 4000HD remote-control manual not in the session: *RST (IEEE 488.2) unverified',
                                     note='Scale / offset / coupling / timebase are set again by each test')
COMMANDS['status.clear'] = cmdreg.Cmd('*CLS', 'Clear status', 'Clears the status registers (never overridable)', kind='set', risk='locked',
                                      verified=False, ref='WaveSurfer remote-control manual not checked')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, 'WaveSurfer remote-control manual not checked')


class WaveSurfer4104HD(Instrument):
    MODEL = 'LeCroy WaveSurfer 4104HD'
    IDN_MATCH = ('LECROY', 'TELEDYNE')
    DEFAULT_TIMEOUT = 10.0
    RELAY_SETTLE = 0.4      # s after a coupling / bandwidth-limit write (front-end relays switch)
    COMMANDS = COMMANDS

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

    def query_retry(self, cmd: str, attempts=3, delay=0.5, values: dict | None = None) -> str:
        """Read-only queries only (writes never come through here and are never replayed).
        `cmd` is a registered query key (`values` fills its placeholders) or the query text itself.
        Before the 2nd attempt the session gets a device clear; before the 3rd it is closed and reopened."""
        wire, log_as = cmd, None
        if cmd in self._registry():
            wire, log_as = self._prepare(cmd, values or {}, 'query_retry')
        recoveries = (self._recover_clear, self._recover_reopen)
        last = None
        for n in range(attempts):
            try:
                return self.query(wire) if log_as is None else self.query(wire, log_as=log_as)
            except TransportError as exc:
                last = exc
                if n + 1 < attempts:
                    time.sleep(delay * (n + 1))
                    try:
                        recoveries[min(n, len(recoveries) - 1)]()
                    except TransportError as rexc:
                        last = rexc
        raise InstrumentError(f'{wire!r} failed after {attempts} attempts '
                              f'(device clear and session reopen tried): {last}') from last

    def _get(self, key, **vals) -> str:
        return self._parse(self.query_retry(key, values=vals))

    @staticmethod
    def _as_float(path: str, reply: str) -> float:
        try:
            value = float(reply)
        except ValueError:
            # MAUI answers a bad property path with text such as "Object doesn't support this property or method".
            raise InstrumentError(f'{path}: scope did not return a number: {reply!r}') from None
        if not math.isfinite(value):
            raise InstrumentError(f'{path} returned a non-finite value')
        return value

    def _get_float(self, key, path, **vals) -> float:
        return self._as_float(path, self._get(key, **vals))

    def vbs_get(self, path: str) -> str:
        return self._get('vbs.get', path=path)

    def vbs_get_float(self, path: str) -> float:
        return self._as_float(path, self.vbs_get(path))

    def vbs_set_number(self, path: str, value):
        self.send('vbs.set.number', path=path, value=format(value))

    def vbs_set_text(self, path: str, text: str):
        self.send('vbs.set.text', path=path, text=text)

    def _set_text_verified(self, set_key, get_key, path, text, settle=0.0, **vals):
        self.send(set_key, **vals)
        if settle:
            time.sleep(settle)
        got = self._get(get_key, **vals)
        if got.casefold() != text.casefold():
            raise InstrumentError(f'{path}: set {text!r} but scope reports {got!r}')

    def handshake(self, attempts=2):
        """Read-only USB check; if the session has gone stale, close and reopen once (never replays writes)."""
        try:
            self._parse(self.query_retry('vert.scale.get', attempts=attempts, values={'ch': self._chn(1)}))
        except InstrumentError:
            self.t.close()
            time.sleep(1.0)
            self.t.open()
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
            self._parse(self.query_retry('vert.scale.get', attempts=attempts, values={'ch': self._chn(1)}))

    # ---- vertical ------------------------------------------------------------------------
    @staticmethod
    def _chn(channel) -> str:
        """channel: 1-4 (int or digit string) as the digit text. 'C1'-style names are refused so a path can never become 'CC1'."""
        text = str(channel).strip()
        if text not in ('1', '2', '3', '4'):
            raise InstrumentError(f'Channel must be 1-4, got {channel!r}')
        return text

    @classmethod
    def _ch(cls, channel) -> str:
        return f'app.Acquisition.C{cls._chn(channel)}'

    def set_vertical_scale(self, channel, volts_per_div, settle=0.35):
        path = f'{self._ch(channel)}.VerScale'
        ch = self._chn(channel)
        self.send('vert.scale.set', ch=ch, value=volts_per_div)
        time.sleep(settle)
        actual = self._get_float('vert.scale.get', path, ch=ch)
        if not math.isclose(actual, volts_per_div, rel_tol=0.01, abs_tol=1e-7):
            raise InstrumentError(f'CH{channel} scale: requested {volts_per_div} V/div, scope reports {actual}')
        return actual

    def set_vertical_offset(self, channel, volts, settle=0.4, tolerance=0.001):
        path = f'{self._ch(channel)}.VerOffset'
        ch = self._chn(channel)
        self.send('vert.offset.set', ch=ch, value=volts)
        time.sleep(settle)
        actual = self._get_float('vert.offset.get', path, ch=ch)
        if not math.isclose(actual, volts, abs_tol=tolerance):
            raise InstrumentError(f'CH{channel} offset: requested {volts} V, scope reports {actual}')
        return actual

    def ensure_zero_offset(self, channel, tolerance=0.001):
        """Read first; only write when needed (a failed write is never replayed)."""
        path = f'{self._ch(channel)}.VerOffset'
        ch = self._chn(channel)
        if abs(self._get_float('vert.offset.get', path, ch=ch)) > tolerance:
            self.send('vert.offset.set', ch=ch, value=0)
            time.sleep(0.3)
        offset = self._get_float('vert.offset.get', path, ch=ch)
        if abs(offset) > tolerance:
            raise InstrumentError(f'CH{channel} offset not zero: {offset}')

    def set_coupling(self, channel, coupling):
        """coupling: DC1M, DC50, AC1M (VBS names)."""
        self._set_text_verified('coupling.set', 'coupling.get', f'{self._ch(channel)}.Coupling', coupling, settle=self.RELAY_SETTLE,
                                ch=self._chn(channel), coupling=coupling)

    def enable_channel(self, channel):
        """Turn a channel ON (display) and read it back: MAUI answers True / -1 / 1 for ON.  The property path is NOT verified on a 4104HD."""
        ch = self._chn(channel)
        self.send('chan.view.set', ch=ch)
        time.sleep(0.3)
        got = self._get('chan.view.get', ch=ch).strip().casefold()
        if got not in ('true', '-1', '1'):
            raise InstrumentError(f'CH{channel} did not turn ON: View reads {got!r}')

    def ensure_not_inverted(self, channel):
        """A DC reading with the wrong sign is an inverted channel (or a reversed cable): read the channel's Invert property and, only when it is ON, turn it OFF and read it
        back.  Returns True when it had to be turned off.  The property path is NOT verified on a 4104HD: a reply that is not a True / False answer is left alone (returns None)."""
        ch = self._chn(channel)
        got = self._get('vert.invert.get', ch=ch).strip().casefold()
        if got in ('false', '0'):
            return False
        if got not in ('true', '-1', '1'):
            return None
        self.send('vert.invert.off', ch=ch)
        time.sleep(0.3)
        after = self._get('vert.invert.get', ch=ch).strip().casefold()
        if after not in ('false', '0'):
            raise InstrumentError(f'CH{channel} Invert could not be turned OFF: reads {after!r}')
        return True

    def set_bandwidth_limit(self, channel, limit):
        """limit: 'Full', '20MHz', ..."""
        self._set_text_verified('bandwidth.set', 'bandwidth.get', f'{self._ch(channel)}.BandwidthLimit', limit, settle=self.RELAY_SETTLE,
                                ch=self._chn(channel), limit=limit)

    def set_coupling_legacy(self, channel_name, coupling):
        """Classic remote command, e.g. 'C1:CPL D50' (used by the impedance test; value is D50/D1M/A1M)."""
        self.send('cpl.set', channel_name=channel_name, coupling=coupling)
        reply = self.ask('cpl.query', channel_name=channel_name).strip().upper()
        if reply.split()[-1].strip(',') != coupling:
            raise InstrumentError(f'Coupling readback mismatch: requested {coupling}, returned {reply!r}')

    def configure_dc_input(self, channel):
        """DC 1 MOhm + 20 MHz bandwidth limit - the input state for DCV and offset tests."""
        ch = self._chn(channel)
        self.send('coupling.set', ch=ch, coupling='DC1M')
        time.sleep(self.RELAY_SETTLE)
        self.send('bandwidth.set', ch=ch, limit='20MHz')
        time.sleep(self.RELAY_SETTLE)
        coupling = self._get('coupling.get', ch=ch)
        bandwidth = self._get('bandwidth.get', ch=ch)
        if coupling.casefold() != 'dc1m' or bandwidth.casefold() != '20mhz':
            raise InstrumentError(f'CH{channel} input setup failed: coupling={coupling!r}, '
                                  f'bandwidth={bandwidth!r}; required DC1M / 20MHz')

    # ---- horizontal / trigger ------------------------------------------------------------------------
    def set_timebase(self, seconds_per_div, settle=0.4):
        self.send('hor.scale.set', seconds=seconds_per_div)
        time.sleep(settle)
        actual = self._get_float('hor.scale.get', 'app.Acquisition.Horizontal.HorScale')
        if not math.isclose(actual, seconds_per_div, rel_tol=0.02, abs_tol=1e-13):
            raise InstrumentError(f'Timebase: requested {seconds_per_div:.12g} s/div, scope reports {actual:.12g}')

    def set_edge_trigger_source(self, channel):
        self.send('trig.type.edge')
        self.send('trig.source.set', channel=str(channel))
        source = self._get('trig.source.get')
        if source.strip().upper() != f'C{channel}':
            raise InstrumentError(f'Trigger source {source!r} does not match CH{channel}')

    # ---- edge trigger slope / level / mode (trigger level and time base tests) ----------------------------
    # NOT yet verified on a 4104HD: Trigger.Edge.Slope ("Positive"/"Negative"), Trigger.Edge.Level (volts) and
    # Acquisition.TriggerMode ("Auto"/"Normal"/"Single"/"Stopped") are the MAUI automation names. Each is read back.
    TRIGGER = 'app.Acquisition.Trigger'

    def set_trigger_slope(self, slope):
        """slope: 'Positive' or 'Negative'."""
        self._set_text_verified('trig.slope.set', 'trig.slope.get', f'{self.TRIGGER}.Edge.Slope', slope, settle=0.3, slope=slope)

    def set_trigger_level(self, volts, tolerance=0.002):
        """Returns the level the scope reports (it may round to its trigger DAC step)."""
        path = f'{self.TRIGGER}.Edge.Level'
        self.send('trig.level.set', volts=volts)
        time.sleep(0.3)
        actual = self._get_float('trig.level.get', path)
        if not math.isclose(actual, volts, abs_tol=tolerance):
            raise InstrumentError(f'Trigger level: requested {volts:+.4f} V, scope reports {actual:+.4f} V')
        return actual

    def set_trigger_mode(self, mode, accept=None):
        """mode: 'Auto', 'Normal' or 'Single'. After 'Single' the scope may already report 'Stopped' if it
        triggered at once, so the accepted readbacks can be widened with `accept`."""
        self.send('trig.mode.set', mode=mode)
        time.sleep(0.3)
        got = self._get('trig.mode.get')
        allowed = {mode.casefold()} | {a.casefold() for a in (accept or ())}
        if got.casefold() not in allowed:
            raise InstrumentError(f'Trigger mode: set {mode!r} but scope reports {got!r}')
        return got

    def trigger_mode(self) -> str:
        return self._get('trig.mode.get')

    # ---- measurement P1 ------------------------------------------------------------------------
    def configure_p1(self, channel, engine, show=True):
        """engine: 'Mean', 'StandardDeviation' (RMS noise), 'PkPk' or 'Freq' (time base). Verified by readback."""
        want = engine.casefold()
        current = self._get('p1.engine.get')
        if current.casefold() not in {want} | {'pkpk': {'peaktopeak'}, 'freq': {'frequency'}}.get(want, set()):
            self.send('p1.engine.set', engine=engine)
            time.sleep(0.5)
            current = self._get('p1.engine.get')
        # MAUI may report the long engine name after the short one is written (PkPk -> PeakToPeak, Freq -> Frequency,
        # the latter seen on the 4104HD).
        aliases = {'pkpk': {'peaktopeak'}, 'freq': {'frequency'}}
        accepted = {want} | aliases.get(want, set())
        if current.casefold() not in accepted:
            raise InstrumentError(f'P1 engine {current!r}, expected {engine}')
        target = f'C{channel}'
        if self._get('p1.source.get').upper() != target:
            self.send('p1.source.set', channel=str(channel))
            time.sleep(0.5)
        source = self._get('p1.source.get')
        if source.upper() != target:
            raise InstrumentError(f'P1 source {source!r}, expected {target}')
        if show:
            self.send('p1.view.on')

    def read_p1(self) -> float:
        """Current P1 value (volts for Mean / StandardDeviation / PkPk, hertz for Freq)."""
        return self._get_float('p1.value.get', f'{P1}.Out.Result.Value')

    def read_p1_when_ready(self, timeout_s=20.0, interval_s=0.5):
        """P1 as a number once the scope has one: right after a range / channel / trigger change MAUI answers 'No Data Available' until a new acquisition has been
        measured.  Only this read-only query is repeated (never a write); raises the scope's own error when no number arrives within the time."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                return self.read_p1()
            except InstrumentError as exc:
                if 'did not return a number' not in str(exc) or time.monotonic() >= deadline:
                    raise
            time.sleep(interval_s)

    def read_p1_settled(self, settle_s, discard_gap_s=0.5):
        """Wait, discard one possibly stale reading, then return a fresh one."""
        time.sleep(settle_s)
        self.read_p1()
        time.sleep(discard_gap_s)
        return self.read_p1()
