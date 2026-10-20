"""Software stand-ins for the MDO4000C bench (oscilloscope, 96270A, 33220A/32250A, reference meters), linked to the simulated 5560A.

make_mdo_bench() returns the transports IO(...) accepts, so the whole procedure can run end to end with no hardware. The simulated
oscilloscope "measures" what the simulated 5560A / RF sources / generator are outputting, with small deterministic errors.
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, SimFlukeTransport, _SimBase
from .transport import TransportError


class MdoState:
    def __init__(self):
        self.reset()
        self.term = '1M'

    def reset(self):
        self.sel = {1}
        self.ch = {n: dict(term=1e6, bw='FUL', scale=0.1, offset=0.0, pos=0.0) for n in (1, 2, 3, 4)}
        self.acq = 'SAM'; self.avg = 16
        self.meas = {}
        self.hscale = 1e-3; self.delay = 0.0
        self.dvm = dict(mode='DC', src=1)
        self.dth = {d: 0.0 for d in range(16)}
        self.data_src = 'CH1'
        self.rf = dict(center=1e9, span=1e9, start=0.0, stop=6e9, rbw=1e3, ref=None)
        self.afg = dict(fn='SINE', freq=1e3, vpp=1.0, off=0.0, on=False)
        self.edge = 1e-8
        self.esr = 0


class SimRF(_SimBase):
    """96270A."""
    def __init__(self, bench, key):
        super().__init__(bench, 'SIM-96270A')
        self.key = key
        self.st = dict(f=1e6, p=-10.0, on=False)
        setattr(bench, key, self.st)

    def handle(self, cmd):
        u = cmd.upper()
        if u == '*IDN?': return 'FLUKE,96270A,SIM0001,1.0'
        if u == '*CLS': return None
        m = re.match(r'FREQ\w*\s+([-+0-9.eE]+)$', u)
        if m: self.st['f'] = float(m.group(1)); return None
        if u.startswith('FREQ') and u.endswith('?'): return f"{self.st['f']:.9g}"
        m = re.match(r'POW\w*\s+([-+0-9.eE]+)$', u)
        if m: self.st['p'] = float(m.group(1)); return None
        if u.startswith('POW') and u.endswith('?'): return f"{self.st['p']:.4f}"
        if u in ('OUTPUT ON', 'OUTP ON'): self.st['on'] = True; return None
        if u in ('OUTPUT OFF', 'OUTP OFF'): self.st['on'] = False; return None
        if u.startswith('OUTP') and u.endswith('?'): return '1' if self.st['on'] else '0'
        raise TransportError(f'simulated 96270A: unknown command {cmd!r}')

    def query(self, text): self.write(text); return self.read()


class SimGen(_SimBase):
    """33220A / 32250A."""
    def __init__(self, bench, model='32250A'):
        super().__init__(bench, 'SIM-AFG')
        self.model = model
        self.st = bench.gen = dict(f=1e3, v=1.0, fn='SIN', on=False, load=50)

    def handle(self, cmd):
        u = cmd.upper()
        if u == '*IDN?': return f'Agilent Technologies,{self.model},SIM0001,1.0'
        if u == '*CLS': return None
        if u == 'OUTPUT ON': self.st['on'] = True; return None
        if u == 'OUTPUT OFF': self.st['on'] = False; return None
        if u.startswith('OUTPUT:LOAD'): return None
        m = re.match(r'APPLY:(SIN|SQU)\w*\s+([-+0-9.eE]+),([-+0-9.eE]+),([-+0-9.eE]+)$', u)
        if m: self.st.update(fn=m.group(1), f=float(m.group(2)), v=float(m.group(3))); return None
        if u == 'FREQUENCY?': return f"{self.st['f']:.9g}"
        if u == 'VOLTAGE?': return f"{self.st['v']:.9g}"
        if u == 'SYSTEM:ERROR?': return '+0,"No error"'
        raise TransportError(f'simulated generator: unknown command {cmd!r}')

    def query(self, text): self.write(text); return self.read()


class SimMeter(_SimBase):
    """Reference DMM / counter reading the simulated oscilloscope AFG."""
    def __init__(self, bench):
        super().__init__(bench, 'SIM-METER')
        self.mode = 'DC'

    def handle(self, cmd):
        u = cmd.upper()
        afg = self.bench.mdo_state.afg
        if u == '*IDN?': return 'KEYSIGHT,SIM-METER,SIM0001,1.0'
        if u == '*CLS': return None
        if u.startswith('CONF'):
            self.mode = 'AC' if 'AC' in u else 'DC'; return None
        if u.startswith(('VOLT:AC:BAND', 'VOLTAGE:AC:BAND')): return None
        if u == 'MEASURE:FREQUENCY?': return f"{afg['freq'] * 1.0000002:.9e}"
        if u == 'MEASURE:POWER?': return '0.0'
        if u == 'READ?':
            if self.mode == 'AC': return f"{afg['vpp'] / 2 * 1.002:.9e}"
            return f"{afg['off'] * 1.001:.9e}"
        raise TransportError(f'simulated meter: unknown command {cmd!r}')

    def query(self, text): self.write(text); return self.read()


class SimMdo(_SimBase):
    def __init__(self, bench):
        super().__init__(bench, 'SIM-MDO')
        self.s = bench.mdo_state

    # -- what the scope would measure ----------------------------------------------------------------------------------------
    def _input_volts(self):
        f = self.bench.fluke
        return f['volts'] if f['operate'] and f['scope'] == 'VOLT' else 0.0

    def _meas(self, slot):
        s = self.s
        m = s.meas.get(slot, {})
        t, f = m.get('type', 'MEAN'), self.bench.fluke
        ch = int(m.get('src', 'CH1')[-1]) if m.get('src', 'CH1').startswith('CH') else 1
        if t == 'MEAN':
            return self._input_volts() * getattr(self.bench, 'mdo_gain', 1.0004) + (2e-5 if not f['operate'] else 3e-5)
        if t == 'PK2PK':
            if not (f['operate'] and f['scope'] == 'LEVSINE') and not self.bench.gen.get('on'):
                return 0.0
            vpp = f['volts'] if f['scope'] == 'LEVSINE' and f['operate'] else self.bench.gen['v']
            fr = f['freq'] if f['scope'] == 'LEVSINE' and f['operate'] else self.bench.gen['f']
            return vpp * 1.001 / math.sqrt(1 + (fr / 1.5e9) ** 2)
        if t == 'RMS':
            return 6.0e-4 if s.acq == 'SAM' else 3.0e-4
        if t == 'DELAY':
            return 3.0e-11
        if t == 'HIGH':
            return 3.3 if s.ch[1]['term'] > 1e3 else 1.65
        if t == 'LOW':
            return 0.05 if s.ch[1]['term'] > 1e3 else 0.02
        return 0.0

    def _spectrum(self):
        s, rf = self.s, self.s.rf
        n = 401
        if rf['span'] and rf['start'] == 0.0 and rf['stop'] == 6e9:
            lo, hi = rf['center'] - rf['span'] / 2, rf['center'] + rf['span'] / 2
        else:
            lo, hi = rf['start'], rf['stop']
        if getattr(self, '_use_cs', True) and rf.get('mode') == 'cs':
            lo, hi = rf['center'] - rf['span'] / 2, rf['center'] + rf['span'] / 2
        xs = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
        rbw = rf['rbw']
        floor = -162.0 + 10 * math.log10(rbw)
        ys = [floor + 0.6 * math.sin(i * 1.3) for i in range(n)]
        peaks = []
        for key in ('rf1', 'rf2'):
            st = getattr(self.bench, key, None)
            if st and st['on']:
                lvl = st['p'] - 0.2 if rf['ref'] is not None else -85.0     # no reference level set = crosstalk setup: leakage only
                peaks.append((st['f'], lvl))
        r1, r2 = getattr(self.bench, 'rf1', None), getattr(self.bench, 'rf2', None)
        if r1 and r2 and r1['on'] and r2['on']:
            peaks += [(2 * r1['f'] - r2['f'], r1['p'] - 75), (2 * r2['f'] - r1['f'], r1['p'] - 75)]
        for f, lvl in peaks:
            for i, x in enumerate(xs):
                if abs(x - f) <= (hi - lo) / (n - 1):
                    ys[i] = max(ys[i], lvl)
        if lo <= 2.5e9 <= hi and not peaks:
            ys[min(range(n), key=lambda i: abs(xs[i] - 2.5e9))] = -88.0
        return xs, ys

    def handle(self, cmd):
        s = self.s
        u = cmd.upper().strip()
        c = cmd.strip()
        if u == '*IDN?': return 'TEKTRONIX,MDO4104C,SIM0001,CF:91.1CT FV:v1.0'
        if u in ('*CLS', 'HEADER OFF', 'VERBOSE OFF'): return None
        if u == '*OPT?': return 'SA6,AFG,DVM,MDO4TRIG'
        if u == '*OPC?': return '1'
        if u == '*ESR?': return '0'
        if u == 'EVMSG?': return '0,"No events"'
        if u == 'FACTORY': s.reset(); return None
        m = re.match(r'SELECT:CH(\d) (ON|OFF)$', u)
        if m:
            (s.sel.add if m.group(2) == 'ON' else s.sel.discard)(int(m.group(1))); return None
        if re.match(r'SELECT:(D\d+|RF_\w+) ', u): return None
        m = re.match(r'CH(\d):(\w+) ?(.*)$', u)
        if m:
            n, key, val = int(m.group(1)), m.group(2), m.group(3)
            ch = s.ch[n]
            names = {'TERMINATION': 'term', 'BANDWIDTH': 'bw', 'SCALE': 'scale', 'OFFSET': 'offset', 'POSITION': 'pos'}
            if key.endswith('?') or val.endswith('?') or c.endswith('?'):
                k = names[key.rstrip('?')]
                v = ch[k]
                return str(v)
            if key == 'COUPLING': return None
            k = names[key]
            ch[k] = val[:3] if k == 'bw' else float(val)
            if k == 'term': self.bench.mdo['term'] = '1M' if ch['term'] > 1e3 else '50'
            return None
        m = re.match(r'ACQUIRE:MODE (\w+)$', u)
        if m: s.acq = m.group(1)[:3]; return None
        if u.startswith(('ACQUIRE:NUMAVG', 'ACQUIRE:STOPAFTER', 'ACQUIRE:STATE')): return None
        if u.startswith('TRIGGER:'): return None
        m = re.match(r'HORIZONTAL:SCALE ([-+0-9.eE]+)$', u)
        if m: s.hscale = float(m.group(1)); return None
        if u == 'HORIZONTAL:SCALE?': return f'{s.hscale:.9g}'
        if u.startswith('HORIZONTAL:DELAY:MODE'): return None
        m = re.match(r'HORIZONTAL:DELAY:TIME ([-+0-9.eE]+)$', u)
        if m: s.delay = float(m.group(1)); return None
        m = re.match(r'MEASUREMENT:MEAS(\d):([\w:]+\??)(?: (.*))?$', u)
        if m:
            slot, key, val = int(m.group(1)), m.group(2), m.group(3)
            d = s.meas.setdefault(slot, {})
            if key == 'TYPE': d['type'] = val.upper()
            elif key == 'SOURCE1': d['src'] = val.upper()
            elif key in ('MEAN?', 'VALUE?'): return f'{self._meas(slot):.9e}'
            elif key == 'STDDEV?': return f'{self._meas(slot):.9e}'
            return None
        if u.startswith('MEASUREMENT:'): return None
        m = re.match(r'D(\d+):THRESHOLD ([-+0-9.eE]+)$', u)
        if m: s.dth[int(m.group(1))] = float(m.group(2)); return None
        m = re.match(r'D(\d+):THRESHOLD\?$', u)
        if m: return f'{s.dth[int(m.group(1))]:.9g}'
        m = re.match(r'DATA:SOURCE (\w+)$', u)
        if m: s.data_src = m.group(1); return None
        if u.startswith('DATA:'): return None
        if u == 'WFMOUTPRE:NR_PT?': return str(self._npts())
        if u == 'WFMOUTPRE:XINCR?': return f'{self._xinc():.9e}'
        if u == 'WFMOUTPRE:XZERO?': return f'{self._xzero():.12e}'
        if u in ('WFMOUTPRE:YMULT?',): return '1.0'
        if u in ('WFMOUTPRE:YOFF?', 'WFMOUTPRE:YZERO?', 'WFMOUTPRE:PT_OFF?'): return '0.0'
        if u == 'CURVE?': return ','.join(f'{v:.9g}' for v in self._curve())
        m = re.match(r'DVM:MODE (\w+)$', u)
        if m: s.dvm['mode'] = m.group(1)[:3]; return None
        m = re.match(r'DVM:SOURCE CH(\d)$', u)
        if m: s.dvm['src'] = int(m.group(1)); return None
        if u.startswith('DVM:DISPLAYSTYLE'): return None
        if u == 'DVM:MEASUREMENT:VALUE?':
            f = self.bench.fluke
            return f"{(self._input_volts() * 1.001 if s.dvm['mode'] == 'DC' else f['volts'] / 2 * 1.002):.9e}"
        if u == 'DVM:MEASUREMENT:FREQUENCY?':
            f = self.bench.fluke
            fr = f['freq'] if f['operate'] and f['scope'] == 'LEVSINE' else self.bench.gen['f']
            return f'{fr * 1.0000001:.9e}'
        m = re.match(r'AFG:(\w+) (.*)$', u)
        if m:
            k, v = m.group(1), m.group(2)
            a = s.afg
            if k == 'FUNCTION': a['fn'] = v
            elif k == 'FREQUENCY': a['freq'] = float(v)
            elif k == 'AMPLITUDE': a['vpp'] = float(v)
            elif k == 'OFFSET': a['off'] = float(v)
            return None
        if u.startswith('AFG:OUTPUT:STATE'): s.afg['on'] = 'ON' in u; return None
        if u.startswith('AFG:'): return None
        if u in ('DIAG:SELECT:ALL', 'DIAG:LOOP:OPTION ONCE', 'DIAG:STATE EXECUTE', 'CALIBRATE:INTERNAL:START'): return None
        if u == 'DIAG:STATE?' or u == 'CALIBRATE:INTERNAL:STATUS?': return 'DONE'
        if u == 'DIAG:RESULT:FLAG?': return 'PASS'
        if u == 'DIAG:RESULT:LOG?': return '"All tests passed"'
        if u == 'CALIBRATE:RESULTS:SPC?': return 'PASS'
        # RF
        m = re.match(r'RF:(\w+) ([-+0-9.eE]+)$', u)
        if m:
            k, v = m.group(1), float(m.group(2))
            r = s.rf
            if k == 'FREQUENCY': r['center'] = v; r['mode'] = 'cs'
            elif k == 'SPAN': r['span'] = v; r['mode'] = 'cs'
            elif k == 'START': r['start'] = v; r['mode'] = 'ss'
            elif k == 'STOP': r['stop'] = v; r['mode'] = 'ss'
            elif k == 'RBW': r['rbw'] = v
            elif k == 'REFLEVEL': r['ref'] = v
            return None
        if u == 'RF:RBW?': return f"{s.rf['rbw']:.9g}"
        if u.startswith('RF:'): return None
        raise TransportError(f'simulated MDO4000C: unknown command {cmd!r}')

    # -- waveform data --------------------------------------------------------------------------------------------------------------
    def _is_rf(self): return self.s.data_src.startswith('RF_')

    def _npts(self): return 401 if self._is_rf() else 1000

    def _xinc(self):
        if self._is_rf():
            xs, _ = self._spectrum(); return (xs[-1] - xs[0]) / (len(xs) - 1)
        return 2e-9

    def _xzero(self):
        if self._is_rf():
            return self._spectrum()[0][0]
        return self.s.delay - 1e-6

    def _curve(self):
        s = self.s
        if self._is_rf(): return self._spectrum()[1]
        if s.data_src.startswith('D'):
            d = int(s.data_src[1:])
            return [1.0 if self._input_volts() > s.dth[d] + 4e-4 else 0.0] * 50
        edge_at = 1e-6 + s.edge
        return [0.0 if i * 2e-9 < edge_at else 2.0 for i in range(1000)]


def make_mdo_bench(gen_model='32250A'):
    """Returns (bench, transports) for IO(addrs, transports=...). Keys: scope, cal, rf1, rf2, gen, dmm, counter, power."""
    bench = SimBench()
    bench.mdo_state = MdoState()
    bench.mdo = {'term': '1M'}
    t = dict(scope=SimMdo(bench), cal=SimFlukeTransport(bench), rf1=SimRF(bench, 'rf1'), rf2=SimRF(bench, 'rf2'), gen=SimGen(bench, gen_model),
             dmm=SimMeter(bench), counter=SimMeter(bench))
    return bench, t
