"""Software stand-in for the TBS2000B bench: a simulated TBS2000B oscilloscope + the simulated 5560A / 5522A (SCOPE DC volts, leveled sine, time marker),
linked so tbs2000b_verification runs end to end with no hardware.

The simulated scope speaks the command strings drivers/tektronix_tbs2000b.py sends (TBS2000B Programmer Manual 077-1149-04), answers in the HEADer OFF
form, and "measures" what the simulated calibrator outputs.  Fault knobs on the bench let tests prove the procedure FAILS when it should:
    bench.tbs_offset_err_v    extra error of the trace (V) at the offset points      bench.tbs_dc_balance_v   trace level (V) with the input terminated
    bench.tbs_bw_scale        -3 dB frequency as a multiple of the model bandwidth   bench.tbs_ppm            time base error (ppm)
    bench.tbs_spc_result      *CAL? reply (0 = pass)                                 bench.tbs_diag_pass      DIAg:RESUlt:FLAg? PASS / FAIL
The simulator is NOT evidence of anything: it exercises the software.  What it answers for replies the manual does not print (e.g. CH<x>:BANdwidth? -> FULL)
is a guess, flagged in the driver.
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, SimFlukeTransport, _SimBase
from .transport import TransportError

BW_MHZ = {'2072B': 70, '2074B': 70, '2102B': 100, '2104B': 100, '2202B': 200, '2204B': 200}
RECORD_LENGTHS = (1000, 2000, 20000, 200000, 2000000, 5000000)


class TbsState:
    def __init__(self, model='2204B'):
        self.model = model
        self.channels = 4 if model.endswith('4B') else 2
        self.reset()

    def reset(self):
        self.sel = {1}
        self.ch = {n: dict(scale=0.1, pos=0.0, offset=0.0, probe=1.0, coup='DC', bw='FULL') for n in (1, 2, 3, 4)}
        self.acq, self.avg = 'SAMPLE', 16
        self.numacq = 0
        self.running = True
        self.hscale, self.reclen = 4e-6, 2000
        self.delay_on, self.delay_t = False, 0.0
        self.trig = dict(src='CH1', slope='RISE', mode='AUTO', coup='DC')
        self.meas = dict(src='CH1', type='MEAN')
        self.data = dict(src='CH1', start=1, stop=2000)
        self.esr = 0
        self.events = []
        self.header = True


class SimTbs(_SimBase):
    def __init__(self, bench, model='2204B'):
        super().__init__(bench, 'SIM-TBS2000B')
        self.s = bench.tbs_state = TbsState(model)
        for k, v in (('tbs_offset_err_v', 0.0), ('tbs_dc_balance_v', 0.0012), ('tbs_bw_scale', 1.4), ('tbs_ppm', 3.0),
                     ('tbs_spc_result', 0), ('tbs_diag_pass', True), ('tbs_gain_error', 0.004)):
            setattr(bench, k, getattr(bench, k, v))

    # -- the signal at the inputs ----------------------------------------------------------------------------------------
    def _fluke(self):
        return self.bench.fluke

    def _vin(self):
        f = self._fluke()
        return f['volts'] if f['operate'] and f['scope'] == 'VOLT' else 0.0

    def _sine(self):
        f = self._fluke()
        if not (f['operate'] and f['scope'] == 'LEVSINE'):
            return 0.0, 0.0
        bw = BW_MHZ[self.s.model] * 1e6 * self.bench.tbs_bw_scale
        return f['volts'] / math.sqrt(1 + (f['freq'] / bw) ** 2), f['freq']

    def _shown(self, ch, volts):
        """What the channel digitizes: the input plus the simulated errors, clipped at the edge of the 10-division acquisition window."""
        c = self.s.ch[ch]
        v = volts * (1 + self.bench.tbs_gain_error) + self.bench.tbs_dc_balance_v
        if c['offset'] or c['pos']:
            v += self.bench.tbs_offset_err_v
        top = c['offset'] + (5.1 - c['pos']) * c['scale']
        bottom = c['offset'] + (-5.1 - c['pos']) * c['scale']
        return min(max(v, bottom), top)

    def _meas_value(self):
        m = self.s.meas
        ch = int(m['src'][-1])
        if m['type'] == 'MEAN':
            return self._shown(ch, self._vin())
        if m['type'] in ('PK2PK', 'PK2'):
            return self._sine()[0]
        return 0.0

    # -- waveform record ---------------------------------------------------------------------------------------------------
    def _xinc(self):
        return max(1e-9, 15 * self.s.hscale / self.s.reclen)

    def _xzero(self):
        span = self.s.reclen * self._xinc()
        return (self.s.delay_t if self.s.delay_on else 0.0) - span / 2

    def _record(self, ch):
        s, f = self.s, self._fluke()
        xs = [self._xzero() + i * self._xinc() for i in range(s.reclen)]
        if f['operate'] and f['scope'] == 'MARKER' and f.get('period'):
            period = f['period'] * (1 + self.bench.tbs_ppm * 1e-6)
            tau = 0.2 * period
            return [self._shown(ch, math.exp(-((t % period) / tau))) for t in xs]
        vpp, fr = self._sine()
        if vpp > 0:
            return [self._shown(ch, 0.5 * vpp * math.sin(2 * math.pi * fr * t)) for t in xs]
        return [self._shown(ch, self._vin())] * s.reclen

    def _levels(self, ch):
        c = self.s.ch[ch]
        ymult = c['scale'] / 25.0
        yoff = c['pos'] * 25.0
        return [max(-128, min(127, round((v - c['offset']) / ymult + yoff))) for v in self._record(ch)]

    # -- commands ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _e(v):
        return f'{v:.4E}'

    def _err(self, code, text, bit=0x20):
        self.s.esr |= bit
        self.s.events.append(f'{code},"{text}"')

    def handle(self, cmd):
        s, c = self.s, cmd.strip()
        u = c.upper()
        if u == '*IDN?': return f'TEKTRONIX,TBS{s.model},SIM0001,CF:91.1CT FV:v1.30'
        if u == '*CLS': s.esr = 0; s.events = []; return None
        if u == 'HEADER OFF': s.header = False; return None
        if u == 'VERBOSE OFF': return None
        if u == '*OPC?': return '1'
        if u == '*ESR?':
            v, s.esr = s.esr, 0
            return str(v)
        if u == 'EVMSG?': return s.events.pop(0) if s.events else '0,"No events to report - queue empty"'
        if u == 'FACTORY': s.reset(); return None
        if u == '*CAL?': return str(self.bench.tbs_spc_result)
        if u == 'CALIBRATE:RESULTS:SPC?': return 'PASS' if self.bench.tbs_spc_result == 0 else 'FAIL'
        if u == 'DIAG:RESULT:FLAG?': return 'PASS' if self.bench.tbs_diag_pass else 'FAIL'
        if u == 'DIAG:RESULT:LOG?': return '"PASS--CPU,PASS--DISPLAY,PASS--FPANEL,PASS--IO,PASS--ACQ,PASS--ROM,PASS--APPKEY"'
        m = re.match(r'SELECT:CH(\d) (ON|OFF)$', u)
        if m:
            n = int(m.group(1))
            if n > s.channels: self._err(102, 'Syntax error'); return None
            (s.sel.add if m.group(2) == 'ON' else s.sel.discard)(n); s.numacq = 0
            return None
        m = re.match(r'CH(\d):(COUPLING|BANDWIDTH|PROBE:GAIN|SCALE|POSITION|OFFSET)(\?)?(?: (\S+))?$', u)
        if m:
            n, key, q, val = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            if n > s.channels: self._err(102, 'Syntax error'); return None
            ch = s.ch[n]
            k = {'COUPLING': 'coup', 'BANDWIDTH': 'bw', 'PROBE:GAIN': 'probe', 'SCALE': 'scale', 'POSITION': 'pos', 'OFFSET': 'offset'}[key]
            if q:
                return ch[k] if isinstance(ch[k], str) else self._e(ch[k])
            if k == 'coup': ch[k] = val
            elif k == 'bw': ch[k] = 'TWENTY' if val.startswith('TWE') else 'FULL'
            elif k == 'pos':
                x = float(val)
                if abs(x) > 5.0: self._err(222, 'Data out of range'); return None
                ch[k] = round(x / 0.01) * 0.01
            elif k == 'offset':
                x = float(val)
                limit = 0.8 if ch['scale'] <= 0.2 else 20.0                       # p. 59
                if abs(x) > limit + 1e-9: self._err(222, 'Data out of range'); return None
                ch[k] = x
            else: ch[k] = float(val)
            s.numacq = 0
            return None
        m = re.match(r'ACQUIRE:(MODE|NUMAVG|NUMACQ|STATE|STOPAFTER)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.groups()
            if key == 'NUMACQ':
                s.numacq += 10 if s.running else 0
                return str(s.numacq)
            if key == 'MODE':
                if q: return s.acq
                s.acq = 'AVERAGE' if val.startswith('AVE') else 'SAMPLE'; return None
            if key == 'NUMAVG':
                if q: return str(s.avg)
                s.avg = int(float(val)); return None
            if key == 'STATE':
                if q: return '1' if s.running else '0'
                s.running = val in ('RUN', 'ON', '1'); return None
            return None
        m = re.match(r'HORIZONTAL:(SCALE|RECORDLENGTH|DELAY:MODE|DELAY:TIME)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.groups()
            if key == 'SCALE':
                if q: return self._e(s.hscale)
                s.hscale = float(val); s.numacq = 0; return None
            if key == 'RECORDLENGTH':
                if q: return str(s.reclen)
                n = int(float(val))
                if n not in RECORD_LENGTHS: self._err(222, 'Data out of range'); return None
                s.reclen = n; return None
            if key == 'DELAY:MODE':
                if q: return '1' if s.delay_on else '0'
                s.delay_on = val in ('ON', '1'); return None
            if q: return self._e(s.delay_t)
            s.delay_t = float(val); return None
        if u == 'TRIGGER:A:TYPE EDGE': return None
        m = re.match(r'TRIGGER:A:(EDGE:SOURCE|EDGE:SLOPE|EDGE:COUPLING|MODE)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.groups()
            attr = {'EDGE:SOURCE': 'src', 'EDGE:SLOPE': 'slope', 'EDGE:COUPLING': 'coup', 'MODE': 'mode'}[key]
            if q: return s.trig[attr]
            s.trig[attr] = {'NORMAL': 'NORMAL', 'NOISEREJ': 'NOISEREJ'}.get(val, val); s.numacq = 0
            return None
        if u == 'TRIGGER:A SETLEVEL':
            if not s.running: self._err(221, 'Settings conflict', 0x10)
            return None
        if u == 'TRIGGER:STATE?': return 'TRIGGER' if s.trig['mode'] == 'NORMAL' else 'AUTO'
        m = re.match(r'MEASUREMENT:IMMED:(SOURCE1|TYPE)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.groups()
            attr = 'src' if key == 'SOURCE1' else 'type'
            if q: return s.meas[attr]
            s.meas[attr] = val; return None
        if u == 'MEASUREMENT:IMMED:VALUE?': return self._e(self._meas_value())
        m = re.match(r'DATA:SOURCE (CH\d)$', u)
        if m: s.data['src'] = m.group(1); return None
        m = re.match(r'DATA:(START|STOP) (\d+)$', u)
        if m: s.data[m.group(1).lower()] = int(m.group(2)); return None
        if u in ('WFMOUTPRE:ENCDG ASCII', 'DATA:WIDTH 1'): return None
        ch_n = int(s.data['src'][-1])
        ch = s.ch[ch_n]
        if u.startswith('WFMOUTPRE:') or u == 'CURVE?':
            if ch_n not in s.sel:
                self._err(2244, 'Waveform requested is not activated', 0x10)
                raise TransportError('simulated TBS2000B: no reply (waveform not displayed)')
        a, b = s.data['start'], min(s.data['stop'], s.reclen)
        if u == 'WFMOUTPRE:NR_PT?': return str(b - a + 1)
        if u == 'WFMOUTPRE:XINCR?': return self._e(self._xinc())
        if u == 'WFMOUTPRE:XZERO?': return f'{self._xzero() + (a - 1) * self._xinc():.9E}'
        if u == 'WFMOUTPRE:YMULT?': return self._e(ch['scale'] / 25.0)
        if u == 'WFMOUTPRE:YOFF?': return self._e(ch['pos'] * 25.0)
        if u == 'WFMOUTPRE:YZERO?': return self._e(ch['offset'])
        if u == 'CURVE?':
            return ','.join(str(x) for x in self._levels(ch_n)[a - 1:b])
        raise TransportError(f'simulated TBS2000B: unknown command {cmd!r}')

    def query(self, text):
        self.write(text)
        return self.read()


def make_tbs_bench(model='2204B', cal='5560A'):
    """Returns (bench, transports) for tbs2000b_verification.IO(addrs, transports=...). Keys: scope, cal."""
    bench = SimBench()
    return bench, dict(scope=SimTbs(bench, model), cal=SimFlukeTransport(bench, cal))
