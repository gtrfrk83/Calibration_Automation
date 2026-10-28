"""Simulated HP 8563E spectrum analyzer (GPIB) for tests with no hardware.

It speaks the statements of drivers/hp_8563e.py: IP, SNGLS, CONTS, AUNITS, CF / SP / FA / FB / RB / VB / RL / AT / ST? (+ '?' forms), DET, TS, DONE?, MKPK HI / NH / NR / NL, MKA?, MKF?,
MKD, MKOFF, MKCF, MKPT, MKPX, ERR?, ID?, STB?, several statements in one write separated by ';'.

It "measures" the simulated Fluke 6060A on the same bench (drivers.simulated_6060a.rf_state(bench)): the carrier at the generator frequency and level, its harmonics at fixed
dBc (`harmonic_dbc`), optional spurs (`spurs`: (ratio of the carrier frequency, dBc)) and a flat noise floor. Marker reads use the trace of the LAST TS, so a setting changed without a
new TS shows stale data, as the manual says. The marker frequency is quantised to the 601 trace points. MKPK NH walks down the list of peaks and stays on the last one at the end
(a simulation choice: the manual shows one use of NH; that is why the driver stops when the marker does not move).

Simulation choices that are NOT facts about the real analyzer (the manual does not say): the TEXT of ID? ("HP8563E"), every sweep time, the harmonic / spur levels, the noise floor, the
fixed amplitude error, the 1 / 3 / 10 RBW list, IP time (none). Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import math
import re

from .hp_8563e import MAX_HZ, PROGRAMMING_ERRORS
from .simulated import SimBench, _SimBase
from .simulated_6060a import rf_state
from .transport import TransportError

UNIT = {'HZ': 1.0, 'KHZ': 1e3, 'MHZ': 1e6, 'GHZ': 1e9, 'DBM': 1.0, 'DB': 1.0, 'S': 1.0, 'MS': 1e-3, 'US': 1e-6, 'SC': 1.0}
RB_LIST = [1, 3, 10, 30, 100, 300, 1e3, 3e3, 10e3, 30e3, 100e3, 300e3, 1e6, 2e6]


class Sim8563ETransport(_SimBase):
    def __init__(self, bench, harmonic_dbc=None, spurs=None, noise_dbm=-110.0, amp_error_db=0.1):
        super().__init__(bench, 'SIM-8563E')
        self.harmonic_dbc = harmonic_dbc if harmonic_dbc is not None else {2: -40.0, 3: -50.0, 4: -60.0, 5: -70.0}
        self.spurs = spurs if spurs is not None else [(0.5, -65.0), (1.5, -72.0)]
        self.noise_dbm = noise_dbm
        self.amp_error_db = amp_error_db
        self.sent = []
        self.cleared = 0
        self.errors = []
        self.sweeps = 0
        self.preset()

    # ---- state ------------------------------------------------------------------------------------------------------------------------------
    def preset(self):
        self.center, self.span = 13.25e9, 26.5e9
        self.fa, self.fb = 0.0, 26.5e9
        self.rb, self.vb, self.rl, self.at = 1e6, 1e6, 0.0, 10
        self.det, self.mkpt, self.mkpx, self.single = 'NRM', -130.0, 6.0, False
        self.marker = None                                  # (freq_hz, amp_dbm) of the active marker, None = off
        self.delta_from = None
        self.peaks, self.peak_idx, self.trace_range = [], -1, (0.0, 26.5e9)
        self.trace_valid = False

    def clear(self):
        self.cleared += 1
        self.preset()
        self.errors = []
        self._reply = None

    def go_local(self):
        pass

    def read_stb(self) -> int:
        return 32 if self.errors else 0

    def query(self, text):
        self.write(text)
        return self.read()

    # ---- the signals ------------------------------------------------------------------------------------------------------------------------
    def signals(self):
        """[(freq_hz, level_dbm)] present at the analyzer input."""
        src = rf_state(self.bench)
        if not src['rf_on']:
            return []
        f0, a0 = float(src['frequency_hz']), float(src['amplitude_dbm'])
        out = [(f0, a0)]
        out += [(n * f0, a0 + dbc) for n, dbc in sorted(self.harmonic_dbc.items())]
        out += [(ratio * f0, a0 + dbc) for ratio, dbc in self.spurs]
        return [(f, a) for f, a in out if 0 < f <= MAX_HZ]

    def _range(self):
        return self.trace_range

    def _sweep(self):
        lo, hi = (self.fa, self.fb) if self.start_stop else (self.center - self.span / 2, self.center + self.span / 2)
        self.trace_range = (lo, hi)
        found = [(f, a + self.amp_error_db) for f, a in self.signals() if lo <= f <= hi and a >= self.mkpt]
        self.peaks = sorted(found, key=lambda p: -p[1])
        self.peak_idx = -1
        self.trace_valid = True
        self.sweeps += 1

    start_stop = False

    def _quant(self, f):
        lo, hi = self.trace_range
        step = (hi - lo) / 600.0
        return lo + round((f - lo) / step) * step if step > 0 else f

    # ---- bus --------------------------------------------------------------------------------------------------------------------------------
    def handle(self, text):
        self.sent.append(text)
        reply = None
        for stmt in text.split(';'):
            stmt = stmt.strip().upper()
            if not stmt:
                continue
            out = self._statement(stmt)
            if out is not None:
                reply = out if reply is None else reply
        return reply

    def _err(self, code):
        if code not in self.errors:
            self.errors.append(code)
        return None

    def _statement(self, stmt):
        m = re.fullmatch(r'([A-Z]+)(\?)?\s*(.*)', stmt)
        if not m:
            return self._err(112)
        name, query, arg = m.group(1), bool(m.group(2)), m.group(3).strip()
        num, unit = None, None
        mm = re.fullmatch(r'([-+]?\d+(?:\.\d*)?(?:E[-+]?\d+)?)\s*([A-Z]*)', arg)
        if mm:
            num, unit = float(mm.group(1)), mm.group(2)
            if unit and unit not in UNIT:
                return self._err(116)
            num *= UNIT.get(unit, 1.0)
            if name in ('CF', 'SP', 'FA', 'FB', 'RB', 'VB') and unit in ('DBM', 'DB', 'S', 'MS', 'US'):
                return self._err(113)
        # ---- queries
        if name == 'ID' and query:
            return 'HP8563E'
        if name == 'ERR' and query:
            codes, self.errors = self.errors, []
            return ','.join(str(c) for c in codes) if codes else '0'
        if name == 'DONE' and query:
            return '1'
        if name == 'STB' and query:
            value, self.errors_seen = (32 if self.errors else 0), None
            return str(value)
        if name == 'AUNITS' and query:
            return 'DBM'
        if query:
            table = {'CF': self.center, 'SP': self.span, 'FA': self.fa, 'FB': self.fb, 'RB': self.rb, 'VB': self.vb, 'RL': self.rl, 'AT': self.at, 'MKPT': self.mkpt,
                     'MKPX': self.mkpx, 'ST': self._sweep_time()}
            if name in table:
                return f'{table[name]:.9g}'
            if name == 'DET':
                return self.det
            if name in ('MKA', 'MKF'):
                return self._marker_read(name)
            return self._err(126)
        # ---- commands
        if name == 'IP':
            self.preset()
        elif name in ('SNGLS', 'CONTS'):
            self.single = name == 'SNGLS'
        elif name == 'AUNITS':
            pass
        elif name == 'TS':
            self._sweep()
        elif name == 'CF' and num is not None:
            self.center, self.start_stop = num, False
            self.fa, self.fb = num - self.span / 2, num + self.span / 2
        elif name == 'SP' and num is not None:
            self.span, self.start_stop = num, False
            self.fa, self.fb = self.center - num / 2, self.center + num / 2
        elif name == 'FA' and num is not None:
            self.fa, self.start_stop = num, True
            self.center, self.span = (self.fa + self.fb) / 2, max(self.fb - self.fa, 0.0)
        elif name == 'FB' and num is not None:
            self.fb, self.start_stop = num, True
            self.center, self.span = (self.fa + self.fb) / 2, max(self.fb - self.fa, 0.0)
        elif name in ('RB', 'VB') and num is not None:
            value = min(RB_LIST, key=lambda x: abs(math.log10(x / num)))
            if name == 'RB':
                self.rb = value
            else:
                self.vb = value
        elif name == 'RL' and num is not None:
            self.rl = num
        elif name == 'AT' and num is not None:
            self.at = min(70, int(math.ceil(num / 10.0) * 10))
        elif name == 'DET':
            self.det = arg if arg in ('NRM', 'POS', 'NEG', 'SMP') else self._bad_det()
        elif name == 'MKPT' and num is not None:
            self.mkpt = num
        elif name == 'MKPX' and num is not None:
            self.mkpx = num
        elif name == 'MKPK':
            self._peak(arg)
        elif name == 'MKD':
            self.delta_from = self.marker or self._center_marker()
        elif name == 'MKOFF':
            self.marker, self.delta_from = None, None
        elif name == 'MKCF':
            if self.marker:
                self.center, self.start_stop = self.marker[0], False
                self.fa, self.fb = self.center - self.span / 2, self.center + self.span / 2
        else:
            return self._err(112)
        return None

    def _bad_det(self):
        self._err(127)
        return self.det

    def _sweep_time(self):
        if self.span == 0:
            return 0.05
        if (self.center, self.span, self.rb) == (13.25e9, 26.5e9, 1e6):
            return 0.53
        return max(0.05, 2.0 * (self.fb - self.fa) / (self.rb ** 2))

    def _center_marker(self):
        lo, hi = self.trace_range
        return ((lo + hi) / 2.0, self.noise_dbm)

    def _peak(self, arg):
        if arg not in ('HI', 'NH', 'NR', 'NL', ''):
            return self._err(128)
        if arg in ('HI', ''):
            self.peak_idx = 0 if self.peaks else -1
        elif arg == 'NH':
            if self.peak_idx + 1 < len(self.peaks):
                self.peak_idx += 1
        else:
            cur = self.marker[0] if self.marker else None
            side = [i for i, (f, _a) in enumerate(self.peaks) if cur is not None and ((f > cur + 1.0) if arg == 'NR' else (f < cur - 1.0))]
            if side:
                self.peak_idx = min(side, key=lambda i: abs(self.peaks[i][0] - cur))
        if 0 <= self.peak_idx < len(self.peaks):
            f, a = self.peaks[self.peak_idx]
            self.marker = (self._quant(f), a)
        else:
            self.marker = self._center_marker()                    # no peak: the marker goes to the center (p. 528)

    def _marker_read(self, name):
        if self.marker is None:
            self.marker = self._center_marker()
        f, a = self.marker
        if self.delta_from is not None:
            f, a = f - self.delta_from[0], a - self.delta_from[1]
        return f'{f:.9g}' if name == 'MKF' else f'{a:.3f}'

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self._reply = self.handle(text.strip())


def make_8563e_bench(bench=None, **kw):
    """(bench, 8563E transport); pass a bench that already has a 6060A to share its output."""
    bench = bench or SimBench()
    return bench, Sim8563ETransport(bench, **kw)
