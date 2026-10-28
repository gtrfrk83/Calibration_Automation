"""Simulated B&K Precision 5491B (and the calibrator simulators of drivers/simulated.py), for tests with no hardware.

The simulator speaks the command strings of drivers/bk_5491b.py. It "measures" what the simulated calibrator is outputting (bench.fluke), but only when the meter is set up the
way that signal needs: the function must match the output (volts / amps / ohms, DC needs an explicit 0 Hz, AC a frequency) and the range must hold the value, otherwise the
reading is the overload value, as a real meter would.

Simulation choices that are NOT facts about the real meter (the manual does not say): the TEXT of every query reply (FUNC?, RANG?, NPLC?, AUTO?, TRIG:SOUR?, the thresholds), the
overload value (+9.9E+37), the reading gain errors, the error text beyond the two the manual gives ("NO ERROR!", "BUS:BAD COMMAND."). Echo modes (what the manual says, Section
5.2.4 item 3: every received character is sent back): `sim.echo = 'line'` echoes each command on its own line before the reply, `sim.echo = 'run'` runs the command text into the front
of the reply with no line end. A command sent while a reply is unread loses that reply (the meter answers a query at once). Keep this file out of any evidence: nothing here is
calibration data.
"""
from __future__ import annotations

import re

from .bk_5491b import FUNC, PATH, RANGES
from .simulated import SimBench, SimFlukeTransport, _SimBase
from .simulated_8808a import Sim5522ALimitsTransport
from .transport import TransportError

FUNC_KIND = {v: k for k, v in FUNC.items()}
GAIN = {'DCV': 1.00002, 'ACV': 1.00004, 'DCI': 1.00003, 'ACI': 1.00005, 'OHM2': 1.00001, 'CONT': 1.00001, 'FREQ': 1.0000002}
OVERLOAD_TEXT = '+9.9E+37'


class Sim5491BTransport(_SimBase):
    """RS-232 5491B. Default: no echo."""

    def __init__(self, bench, serial='SIM0001'):
        super().__init__(bench, 'SIM-5491B')
        self.serial = serial
        self.sent = []
        self.echo = None                     # None | 'line' | 'run'
        self.out = []
        self.cleared = 0
        self.errors = []
        self.reset_state()

    def reset_state(self):
        self.func, self.auto, self.range_no, self.nplc, self.trigger, self.thr = 'DCV', True, 4, 1.0, 'IMM', 0.5
        self.range_no = len(RANGES['DCV'])

    # ---- helpers
    def _table(self):
        return RANGES[self.func]

    def _signal(self):
        """(value, ok): what the calibrator outputs as this function sees it. ok False -> overload."""
        f = self.bench.fluke
        ext = getattr(self.bench, 'external', None)
        if ext is not None:
            unit, value, freq = ext
        elif not f['operate']:
            return 0.0, True
        else:
            unit, value, freq = f.get('unit', 'V'), f['volts'], f['freq']
        fn = self.func
        if fn in ('DCV', 'DCI'):
            return (value, unit == ('V' if fn == 'DCV' else 'A') and freq == 0)
        if fn in ('ACV', 'ACI'):
            return (value, unit == ('V' if fn == 'ACV' else 'A') and freq > 0)
        if fn in ('OHM2', 'CONT'):
            return (value, unit == 'OHM')
        return (freq, unit == 'V' and freq > 0)         # FREQ

    def _reading(self):
        value, ok = self._signal()
        if self.func == 'FREQ':
            return value * GAIN['FREQ'] if ok else None
        rng = self._table()[self.range_no - 1] if self.func != 'CONT' else RANGES['CONT'][0]
        if not ok or abs(value) > rng * 1.02:
            return None
        res = rng / 100000.0
        return round(value * GAIN[self.func] / res) * res + 0.0

    def _pick_range(self, expected):
        for n, r in enumerate(self._table(), start=1):
            if expected <= r * 1.0000001:
                return n
        return len(self._table())

    # ---- bus
    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        reply = self.handle(text.strip())
        if self.echo == 'line':
            self.out.append(text.strip())
            if reply is not None:
                self.out.append(reply)
        elif self.echo == 'run':
            if reply is not None:
                self.out.append(text.strip() + reply)
            else:
                self.out.append(text.strip())
        elif reply is not None:
            self.out.append(reply)

    def read(self):
        if not self.out:
            raise TransportError('simulated read timed out (no pending reply)')
        return self.out.pop(0)

    def clear(self):
        self.out = []
        self.cleared += 1

    @property
    def _reply(self):
        return self.out[0] if self.out else None

    @_reply.setter
    def _reply(self, value):
        pass

    def _error(self, text):
        self.errors.append(text)
        return None

    def handle(self, cmd):
        u = re.sub(r'\s+', ' ', cmd.strip().upper())
        self.sent.append(cmd.strip())
        if u == '*IDN?':
            return f'5491B Multimeter,Ver1.0.SIM,{self.serial}'
        if u == '*RST':
            self.reset_state()
            return None
        if u == 'SYST:ERR?':
            return self.errors.pop(0) if self.errors else 'NO ERROR!'
        m = re.fullmatch(r'FUNC ([A-Z:]+)', u)
        if m:
            kind = FUNC_KIND.get(m.group(1))
            if kind is None:
                return self._error('BUS:BAD COMMAND.')
            self.func, self.auto = kind, True
            self.range_no = len(self._table())
            return None
        if u == 'FUNC?':
            return '"' + FUNC[self.func] + '"'
        m = re.fullmatch(r'TRIG:SOUR (IMM|BUS|MAN)', u)
        if m:
            self.trigger = m.group(1)
            return None
        if u == 'TRIG:SOUR?':
            return self.trigger
        if u == 'FETC?':
            v = self._reading()
            return OVERLOAD_TEXT if v is None else f'{v:+.6E}'
        m = re.fullmatch(r'FREQ:THR:VOLT:RANG ([-+0-9.E]+)', u)
        if m:
            self.thr = float(m.group(1))
            return None
        if u == 'FREQ:THR:VOLT:RANG?':
            return f'{self.thr:.6E}'
        for kind, path in PATH.items():
            if not u.startswith(path + ':'):
                continue
            rest = u[len(path) + 1:]
            if self.func != kind:
                return self._error('BUS:BAD COMMAND.')
            m = re.fullmatch(r'RANG:AUTO (ON|OFF)', rest)
            if m:
                self.auto = m.group(1) == 'ON'
                return None
            if rest == 'RANG:AUTO?':
                return '1' if self.auto else '0'
            m = re.fullmatch(r'RANG ([-+0-9.E]+)', rest)
            if m:
                self.range_no, self.auto = self._pick_range(abs(float(m.group(1)))), False
                return None
            if rest == 'RANG?':
                return f'{self._table()[self.range_no - 1]:.6E}'
            m = re.fullmatch(r'NPLC ([0-9.]+)', rest)
            if m:
                self.nplc = float(m.group(1))
                return None
            if rest == 'NPLC?':
                return f'{self.nplc:g}'
        return self._error('BUS:BAD COMMAND.')

    def query(self, text):
        self.write(text)
        return self.read()


def make_5491b_bench(cal='5522A', enforce_cal_limits=True):
    """(bench, calibrator transport, 5491B transport)."""
    bench = SimBench()
    if enforce_cal_limits and cal == '5522A':
        cal_t = Sim5522ALimitsTransport(bench, cal)
    elif enforce_cal_limits and cal == '5520A':
        from .simulated_5520a import Sim5520ALimitsTransport
        cal_t = Sim5520ALimitsTransport(bench, cal)
    else:
        cal_t = SimFlukeTransport(bench, cal)
    return bench, cal_t, Sim5491BTransport(bench)
