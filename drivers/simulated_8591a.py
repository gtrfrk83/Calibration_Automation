"""Simulated HP 8591A spectrum analyzer and the Fluke 96270A as its source, linked on one SimBench, for tests and the procedure-modification dry run. No hardware.

Sim8591ATransport speaks the statements of drivers/hp_8591a.py (IP, CLS, SNGLS, CONTS, AUNITS, LG, LN, CF / SP / RB / VB / RL / AT / ST (+ the '?' forms), DET, TS, DONE?, MKPK HI, MKD, MKN, MKA?,
MKF?, MKOFF, TDF, TRA?, ID?, STB?; several statements in one write separated by ';'). Sim96270ASource speaks the commands drivers/reference_instruments.py sends for the leveled-sine, AM and
power-meter instruments.

What the analyzer "sees" at its input: when the simulated 96270A output is ON, its signal (frequency, level, AM); otherwise the analyzer's own CAL OUT (300 MHz, -20 dBm: the connection the
CAL OUT checks need). The trace is 401 points; a CW signal shows with a Gaussian response whose -3 dB width is the resolution bandwidth; marker values come from the trace of the LAST TS, so a setting
changed without a new TS shows stale data, as the manual says. Marker frequencies are the NOMINAL axis (start + point x span / 400), as the real analyzer computes them, so a hidden span error
(`span_scale`) or center error (`cf_offset_hz`) shows up only as a peak at the wrong point.

Simulation choices that are NOT facts about the real analyzer or source: every error function (amplitude, scale fidelity, attenuator, reference level, RBW switching and width, frequency response, span,
sweep time), the noise floor, the sweep times of the auto-coupled sweeps, the TEXT of ID? ("HP8591A"), the 96270A reply formats. Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import math
import re

from .hp_8591a import MAX_HZ, TRACE_POINTS
from .simulated import SimBench, _SimBase
from .transport import TransportError

UNIT = {'HZ': 1.0, 'KHZ': 1e3, 'MHZ': 1e6, 'GHZ': 1e9, 'DBM': 1.0, 'DB': 1.0, 'S': 1.0, 'MS': 1e-3, 'US': 1e-6, 'SC': 1.0, 'V': 1.0}
RB_LIST = [1e3, 3e3, 10e3, 30e3, 100e3, 300e3, 1e6, 3e6]
VB_LIST = [30, 100, 300, 1e3, 3e3, 10e3, 30e3, 100e3, 300e3, 1e6, 3e6]
CAL_OUT_HZ, CAL_OUT_DBM = 300e6, -20.0
NOISE_DBM = -115.0


def source_state(bench) -> dict:
    """The 96270A state shared on the bench (created on first use)."""
    if not hasattr(bench, 'src96'):
        bench.src96 = dict(inst='SINE', output=False, freq=1e6, dbm=0.0, am=None, am_on=False, am_depth=30.0, am_rate=1000.0, am_shape='SINE', unit='DBM')
    return bench.src96


def _tri(phase):
    """Triangle wave -1 .. +1 for a phase in cycles."""
    x = phase % 1.0
    return 4 * x - 1 if x < 0.5 else 3 - 4 * x


class Sim96270ASource(_SimBase):
    """The 96270A: leveled sine, AM and power-meter instruments (the power meter reads the analyzer's CAL OUT: `calout_error_db`)."""

    def __init__(self, bench: SimBench, sensor='R&S,NRP40T,SIM100001,1.0', calout_error_db=0.05):
        super().__init__(bench, 'SIM-96270A')
        self.sensor, self.calout_error_db = sensor, calout_error_db
        self.sent, self.errors, self.zeroes, self.zero_with_output_on = [], [], 0, []
        self.pm = {'TRIG': 'CONT', 'AVER': 'AUTO', 'FREQ': '1E6'}
        self.zeroed_at = None
        self.zero_reply = '0'
        source_state(bench)

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self.sent.append(text.strip())
        reply = None
        for part in re.split(r';\s*:', text.strip()):
            out = self.handle(part.strip())
            reply = out if out is not None else reply
        self._reply = reply

    def handle(self, text):
        s = source_state(self.bench)
        u = re.sub(r'^PMET\d:', 'PMET:', text.upper()).lstrip(':')
        if u == '*IDN?':
            return 'Fluke,96270A,SIM0001,1.0'
        if u == '*CLS':
            self.errors = []
            return None
        if u == '*RST':
            s.update(inst='SINE', output=False, am_on=False, unit='DBM')
            return None
        if u == '*OPC?':
            return '1'
        if u == 'SYST:ERR?':
            return self.errors.pop(0) if self.errors else '0,"No error"'
        if u.startswith('INST '):
            name = u.split()[1]
            s['inst'] = 'PMETER' if name.startswith('PMET') else name if name in ('AM', 'FM') else 'SINE'
            s['output'] = False
            s['am_on'] = False
            return None
        if u == 'INST?':
            return s['inst']
        if u.startswith('UNIT:POW '):
            s['unit'] = u.split()[1]
            return None
        if u == 'UNIT:POW?':
            return 'NONE' if s['inst'] == 'PMETER' else s['unit']
        if u in ('POW:OFFS:STAT 0', 'FREQ:OFFS:STAT 0'):
            return None
        if u in ('POW:OFFS:STAT?', 'FREQ:OFFS:STAT?'):
            return '0'
        m = re.fullmatch(r'(FREQ|POW)\s+(\S+)', u)
        if m:
            s['freq' if m.group(1) == 'FREQ' else 'dbm'] = float(m.group(2))
            return None
        if u == 'FREQ?':
            return f'{s["freq"]:.12g}'
        if u == 'POW?':
            return f'{s["dbm"]:.3f}'
        if u == 'OUTP ON':
            s['output'] = True
            return None
        if u == 'OUTP OFF':
            s['output'] = False
            return None
        if u == 'OUTP?':
            return '1' if s['output'] else '0'
        m = re.fullmatch(r'AM:(STAT|DEPT|INT:FREQ|SHAP)\s+(\S+)', u)
        if m:
            if s['inst'] != 'AM':
                self.errors.append('-221,"Settings conflict: AM instrument not selected"')
                return None
            key = {'STAT': 'am_on', 'DEPT': 'am_depth', 'INT:FREQ': 'am_rate', 'SHAP': 'am_shape'}[m.group(1)]
            s[key] = (m.group(2) == '1') if key == 'am_on' else m.group(2) if key == 'am_shape' else float(m.group(2))
            return None
        if u in ('AM:STAT?', 'AM:DEPT?', 'AM:INT:FREQ?', 'AM:SHAP?'):
            key = {'AM:STAT?': 'am_on', 'AM:DEPT?': 'am_depth', 'AM:INT:FREQ?': 'am_rate', 'AM:SHAP?': 'am_shape'}[u]
            return ('1' if s[key] else '0') if key == 'am_on' else str(s[key])
        m = re.fullmatch(r'PMET:(TRIG|AVER|FREQ)\s+(\S+)', u)
        if m:
            self.pm[m.group(1)] = m.group(2)
            if m.group(1) == 'FREQ':
                self.zeroed_at = None
            return None
        if u in ('PMET:TRIG?', 'PMET:AVER?', 'PMET:FREQ?'):
            return self.pm[u[5:-1]]
        if u == 'PMET:IDN?':
            return self.sensor
        if u == 'PMET:ZERO?':
            self.zeroes += 1
            self.zeroed_at = self.pm['FREQ']
            self.zero_with_output_on.append(bool(getattr(self.bench, 'sensor_on_calout', False)))
            return self.zero_reply
        if u == 'PMET:READ?':
            if not getattr(self.bench, 'sensor_on_calout', True):
                return '-9.0E+01'
            level = CAL_OUT_DBM + self.calout_error_db + (0.5 if self.zeroed_at != self.pm['FREQ'] else 0.0)
            return f'{level:+.4E}'
        raise TransportError(f'simulated 96270A: unknown command {text!r}')


class Sim8591ATransport(_SimBase):
    def __init__(self, bench, noise_dbm=NOISE_DBM):
        super().__init__(bench, 'SIM-8591A')
        self.noise_dbm = noise_dbm
        self.sent, self.errors = [], []
        self.cleared = 0
        self.sweeps = 0
        # hidden instrument errors (what the procedure measures); defaults are all well inside the document's limits
        self.span_scale = 1.0              # actual span / displayed span
        self.cf_offset_hz = 0.0            # actual center - displayed center
        self.st_scale = 1.0                # actual sweep time / displayed sweep time
        self.amp_error_db = 0.05           # constant amplitude error
        self.scale_error = lambda dbm: 0.0           # extra display error vs input level (scale fidelity)
        self.atten_error = lambda at: 0.0            # extra error vs input attenuation (dB)
        self.reflevel_error = lambda rl: 0.0         # extra error vs reference level (dBm)
        self.rbw_switch_error = lambda rb: 0.0       # amplitude change vs the 3 kHz filter (dB)
        self.rbw_scale = 1.0                         # actual -3 dB width / nominal
        self.response_error = lambda f: 0.0          # frequency response (dB)
        self.preset()

    def preset(self):
        self.center, self.span = 900e6, 1.8e9
        self.rb, self.vb, self.rl, self.at = 3e6, 3e6, 0.0, 10
        self.st_manual = None
        self.units, self.log_db, self.lin, self.det = 'DBM', 10, False, 'POS'
        self.marker = self.delta = None                  # (index, dB or V) of the active / delta marker
        self.trace = [self.noise_dbm] * TRACE_POINTS
        self.trace_state = (0.0, 0.0)
        self.zero = False

    # ---- bus state used by the driver ------------------------------------------------------------------------------------------------------
    def clear(self):
        self.cleared += 1

    def go_local(self):
        pass

    def read_stb(self) -> int:
        return 32 if self.errors else 0

    def _err(self, code=32):
        if code not in self.errors:
            self.errors.append(code)
        return None

    # ---- the input signal -------------------------------------------------------------------------------------------------------------------
    def inputs(self):
        """[(freq_hz, level_dbm, am)] at the analyzer input; am None or dict(depth, rate, shape)."""
        s = source_state(self.bench)
        if s['output'] and s['inst'] in ('SINE', 'AM'):
            am = dict(depth=s['am_depth'] / 100.0, rate=s['am_rate'], shape=s['am_shape']) if (s['inst'] == 'AM' and s['am_on']) else None
            return [(s['freq'], s['dbm'] + getattr(self.bench, 'source_error_db', lambda f: 0.0)(s['freq']), am)]
        return [(CAL_OUT_HZ, CAL_OUT_DBM, None)]

    def _display_db(self, dbm, freq, scale_ref=True):
        rb_extra = self.rbw_switch_error(self.rb)
        return dbm + self.amp_error_db + self.scale_error(dbm) + self.atten_error(self.at) + self.reflevel_error(self.rl) + rb_extra + self.response_error(freq)

    def _response_db(self, df):
        width = self.rb * self.rbw_scale
        return min(80.0, 3.0103 * (2.0 * df / width) ** 2)

    def _span_actual(self):
        return self.span * self.span_scale

    def _st(self):
        if self.zero:
            return self.st_manual if self.st_manual else 0.02
        return self.st_manual if self.st_manual else max(0.02, 2.0 * self.span / (self.rb ** 2) * 0.4)

    def _sweep(self):
        self.sweeps += 1
        cf = self.center + self.cf_offset_hz
        points = []
        if self.span == 0:                                          # zero span: the time axis; an AM signal shows its envelope
            st = self._st() * self.st_scale
            for i in range(TRACE_POINTS):
                t = st * i / (TRACE_POINTS - 1)
                p_mw = 10 ** (self.noise_dbm / 10)
                for f, a, am in self.inputs():
                    df = f - cf
                    level = a - self._response_db(df)
                    lin = 10 ** (self._display_db(level, f) / 10)
                    if am:
                        wave = _tri(am['rate'] * t) if am['shape'].upper().startswith('TRI') else math.sin(2 * math.pi * am['rate'] * t)
                        lin *= (1.0 + am['depth'] * wave) ** 2
                    p_mw += lin
                points.append(10 * math.log10(p_mw))
        else:
            span = self._span_actual()
            start = cf - span / 2.0
            for i in range(TRACE_POINTS):
                x = start + span * i / (TRACE_POINTS - 1)
                p_mw = 10 ** (self.noise_dbm / 10)
                for f, a, _am in self.inputs():
                    level = a - self._response_db(f - x)
                    p_mw += 10 ** (self._display_db(level, f) / 10)
                points.append(10 * math.log10(p_mw))
        self.trace = points
        self.marker = self.delta = None

    # ---- bus ----------------------------------------------------------------------------------------------------------------------------------
    def handle(self, text):
        self.sent.append(text)
        reply = None
        for stmt in text.split(';'):
            stmt = stmt.strip().upper()
            if not stmt:
                continue
            out = self._statement(stmt)
            if out is not None:
                reply = out
        return reply

    def _amp(self, dbm):
        return math.sqrt(1e-3 * 50.0 * 10 ** (dbm / 10)) if self.units == 'V' else dbm

    def _statement(self, stmt):
        m = re.fullmatch(r'([A-Z]+)(\?)?\s*(.*)', stmt)
        if not m:
            return self._err()
        name, query, arg = m.group(1), bool(m.group(2)), m.group(3).strip()
        num = None
        mm = re.fullmatch(r'([-+]?\d+(?:\.\d*)?(?:E[-+]?\d+)?)\s*([A-Z]*)', arg)
        if mm:
            unit = mm.group(2)
            if unit and unit not in UNIT:
                return self._err()
            num = float(mm.group(1)) * UNIT.get(unit, 1.0)
        if query:
            if name == 'ID':
                return 'HP8591A'
            if name == 'DONE':
                return '1'
            if name == 'STB':
                value = 32 if self.errors else 0
                self.errors = []
                return str(value)
            if name == 'AUNITS':
                return self.units
            if name == 'DET':
                return self.det
            table = {'CF': self.center, 'SP': self.span, 'RB': self.rb, 'VB': self.vb, 'RL': self.rl if self.units == 'DBM' else self._amp(self.rl), 'AT': self.at, 'ST': self._st()}
            if name in table:
                return f'{table[name]:.9g}'
            if name in ('MKA', 'MKF'):
                return self._marker_read(name)
            if name == 'TRA':
                vals = [self._amp(v) for v in self.trace]
                return '\r\n'.join(f'{v:.6g}' for v in vals)
            return self._err()
        if name == 'IP':
            self.preset()
            self.errors = []
        elif name == 'CLS':
            self.errors = []
        elif name in ('SNGLS', 'CONTS', 'TDF'):
            pass
        elif name == 'AUNITS':
            if arg not in ('DBM', 'V'):
                return self._err()
            self.units = arg
        elif name == 'LG':
            self.lin = False
            self.log_db = int(num) if num else 10
        elif name == 'LN':
            self.lin = True
        elif name == 'TS':
            self._sweep()
        elif name == 'CF' and num is not None:
            self.center = num
        elif name == 'SP' and num is not None:
            self.span = num
            self.zero = num == 0
        elif name in ('RB', 'VB') and num is not None:
            table = RB_LIST if name == 'RB' else VB_LIST
            value = min(table, key=lambda x: abs(math.log10(x / num)))
            if name == 'RB':
                self.rb = value
            else:
                self.vb = value
        elif name == 'RL' and num is not None:
            self.rl = num
        elif name == 'AT' and num is not None:
            self.at = min(60, int(math.ceil(num / 10.0) * 10))
        elif name == 'ST' and num is not None:
            self.st_manual = num
        elif name == 'DET':
            if arg not in ('NRM', 'POS', 'NEG', 'SMP'):
                return self._err()
            self.det = arg
        elif name == 'MKPK':
            if arg not in ('HI', ''):
                return self._err()
            i = max(range(TRACE_POINTS), key=lambda k: self.trace[k])
            self.marker = (i, self.trace[i])
        elif name == 'MKD':
            self.delta = self.marker or (TRACE_POINTS // 2, self.trace[TRACE_POINTS // 2])
        elif name == 'MKN' and num is not None:
            lo = self.center - self.span / 2.0
            step = self.span / (TRACE_POINTS - 1)
            i = min(TRACE_POINTS - 1, max(0, round((num - lo) / step))) if step > 0 else 0
            self.marker = (i, self.trace[i])
        elif name == 'MKOFF':
            self.marker = self.delta = None
        else:
            return self._err()
        return None

    def _marker_read(self, name):
        if self.marker is None:
            self.marker = (TRACE_POINTS // 2, self.trace[TRACE_POINTS // 2])
        i, a = self.marker
        step = self.span / (TRACE_POINTS - 1)
        f = self.center - self.span / 2.0 + i * step
        if self.delta is not None:
            di, da = self.delta
            f, a = f - (self.center - self.span / 2.0 + di * step), a - da
            if self.units == 'V':
                a = 10 ** (a / 20.0)
        elif self.units == 'V':
            a = self._amp(a)
        if self.span == 0:
            f = i / (TRACE_POINTS - 1) * self._st()
        return f'{f:.9g}' if name == 'MKF' else f'{a:.4f}'

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self._reply = self.handle(text.strip())


def make_8591a_bench(bench=None, **kw):
    """(bench, 8591A transport, 96270A transport) on one bench."""
    bench = bench or SimBench()
    source_state(bench)
    return bench, Sim8591ATransport(bench, **kw), Sim96270ASource(bench)
