"""Software stand-ins for the TDS2000C / TDS1000C-EDU bench: oscilloscope + the simulated 5560A / 5522A (SCOPE DCV, LEVSINE, MARKER)
+ an optional reference DMM, linked so the whole procedure runs end to end with no hardware.

The simulated oscilloscope speaks the TDS2000C programmer-manual command strings the driver sends, answers with HEADer OFF style replies,
and "measures" what the simulated calibrator outputs.  Fault knobs on the bench let tests prove the procedure FAILS when it should:
    bench.tds_gain_error      DC gain error (fraction)            bench.tds_bw_scale      -3 dB frequency as a multiple of the model bandwidth
    bench.tds_ppm             time base error (ppm)               bench.tds_trig_fault    None | 'nolock' | 'jitter'
    bench.tds_pos_err_v       extra vertical-position error (V per division of position)
The simulator is NOT evidence of anything: it is for exercising the software.
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, SimFlukeTransport, _SimBase
from .transport import TransportError

NPTS = 2500


class TdsState:
    def __init__(self, model='2024C'):
        self.model = model
        self.channels = 4 if model in ('2004C', '2014C', '2024C') else 2
        self.reset()

    def reset(self):
        self.sel = {1}
        self.ch = {n: dict(scale=1.0, pos=0.0, probe=1.0, coup='DC', bw='OFF') for n in (1, 2, 3, 4)}
        self.acq, self.avg = 'SAMPLE', 16
        self.running, self.numacq = True, 0
        self.hscale, self.hpos = 5e-4, 0.0
        self.trig = dict(src='CH1', slope='RISE', mode='AUTO', coup='DC', level=0.0)
        self.meas = dict(src='CH1', type='PK2PK')
        self.data_src = 'CH1'
        self.esr = 0
        self.events = []
        self.calibrated = False


class SimTds(_SimBase):
    def __init__(self, bench, model='2024C'):
        super().__init__(bench, 'SIM-TDS2000C')
        self.s = bench.tds_state = TdsState(model)
        bench.tds_gain_error = getattr(bench, 'tds_gain_error', 0.0004)
        bench.tds_bw_scale = getattr(bench, 'tds_bw_scale', 1.4)
        bench.tds_ppm = getattr(bench, 'tds_ppm', 3.0)
        bench.tds_trig_fault = getattr(bench, 'tds_trig_fault', None)
        bench.tds_pos_err_v = getattr(bench, 'tds_pos_err_v', 0.00012)
        bench.tds_self_cal_result = getattr(bench, 'tds_self_cal_result', 0)
        bench.tds_diag_pass = getattr(bench, 'tds_diag_pass', True)
        self.curve_calls = 0

    # -- the signal at the scope input ------------------------------------------------------------------------------------
    @property
    def bw_hz(self):
        info = {'1001C-EDU': 40, '2001C': 50, '1002C-EDU': 60, '2002C': 70, '2004C': 70}.get(self.s.model, 100 if self.s.model[1:3] in ('01', '12', '14') else 200)
        return info * 1e6 * self.bench.tds_bw_scale

    def _fluke(self):
        return self.bench.fluke

    def _dc_in(self):
        f = self._fluke()
        return f['volts'] if f['operate'] and f['scope'] == 'VOLT' else 0.0

    def _sine_vpp(self):
        """Peak-to-peak seen on the displayed channel."""
        f = self._fluke()
        if not (f['operate'] and f['scope'] == 'LEVSINE'):
            return 0.0, 0.0
        fr = f['freq']
        vpp = f['volts'] / math.sqrt(1 + (fr / self.bw_hz) ** 2)
        if self.s.trig['src'] == 'EXT' or getattr(self.bench, 'tds_splitter', False):
            vpp *= 2.0 / 3.0                      # power splitter (about 200 mV on CH1 for 300 mV in)
        return vpp, fr

    def _meas_value(self):
        s, m = self.s, self.s.meas
        if m['type'] == 'MEAN':
            ch = int(m['src'][-1])
            return self._dc_in() * (1 + self.bench.tds_gain_error) + 2e-5 + self._pos_err(ch)
        if m['type'] == 'PK2PK':
            return self._sine_vpp()[0]
        return 0.0

    def _pos_err(self, ch):
        return self.bench.tds_pos_err_v * self.s.ch[ch]['pos'] / 10.0

    # -- waveform record ------------------------------------------------------------------------------------------------------
    def _xinc(self):
        return 10 * self.s.hscale / NPTS

    def _xzero(self):
        return self.s.hpos - 5 * self.s.hscale

    def _volts_record(self):
        s, f = self.s, self._fluke()
        xs = [self._xzero() + i * self._xinc() for i in range(NPTS)]
        if f['operate'] and f['scope'] == 'MARKER':
            edge = (f.get('period', 0.0) or 0.0) * (1 + self.bench.tds_ppm * 1e-6)
            return [(0.0 if t < edge else 1.0 * math.exp(-(t - edge) / max(s.hscale * 1.5, 1e-9))) for t in xs]
        vpp, fr = self._sine_vpp()
        if vpp > 0 and fr > 0:
            period = 1.0 / fr
            fault = self.bench.tds_trig_fault
            self.curve_calls += 1
            offset = 0.0
            if fault == 'jitter':
                offset = (((self.curve_calls * 0.6180339887) % 1.0) - 0.5) * period
            sign = 1.0 if s.trig['slope'] == 'RISE' else -1.0
            return [sign * 0.5 * vpp * math.sin(2 * math.pi * fr * (t - offset)) for t in xs]
        dc = self._dc_in()
        return [dc * (1 + self.bench.tds_gain_error)] * NPTS

    def _curve(self):
        ch = int(self.s.data_src[-1])
        ch_s = self.s.ch[ch]
        ymult = ch_s['scale'] / 25.0
        yoff = ch_s['pos'] * 25.0
        out = []
        for v in self._volts_record():
            dl = round(v / ymult + yoff)
            out.append(max(-127, min(127, dl)))
        return out

    # -- commands ---------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _e(v):
        return f'{v:.6E}'

    def _bump(self):
        self.s.numacq = 0

    def handle(self, cmd):
        s, c = self.s, cmd.strip()
        u = c.upper()
        if u == '*IDN?': return f'TEKTRONIX,TDS {s.model},SIM0001,CF:91.1CT FV:v24.00'
        if u in ('*CLS', 'HEADER OFF', 'VERBOSE OFF'): s.esr = 0; return None
        if u == '*OPC?': return '1'
        if u == '*ESR?':
            v, s.esr = s.esr, 0
            return str(v)
        if u == 'EVMSG?': return '0,"No events to report - queue empty"' if not s.events else s.events.pop(0)
        if u == 'FACTORY': s.reset(); return None
        if u == '*CAL?': s.calibrated = True; return str(self.bench.tds_self_cal_result)
        if u == 'CALIBRATE:STATUS?': return 'PASS' if self.bench.tds_self_cal_result == 0 else 'FAIL'
        if u == 'DIAG:RESULT:FLAG?': return 'PASS' if self.bench.tds_diag_pass else 'FAIL'
        if u == 'DIAG:RESULT:LOG?': return '"PASS-CPU, PASS-ACQ1, PASS-EXTENSION"'
        m = re.match(r'SELECT:CH(\d) (ON|OFF)$', u)
        if m:
            (s.sel.add if m.group(2) == 'ON' else s.sel.discard)(int(m.group(1)))
            return None
        m = re.match(r'CH(\d):(\w+)(\?)?(?: (\S+))?$', u)
        if m:
            n, key, q, val = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            if n > s.channels:
                s.esr |= 0x20; s.events.append('113,"Undefined header"'); return None
            ch = s.ch[n]
            names = {'COUPLING': 'coup', 'BANDWIDTH': 'bw', 'PROBE': 'probe', 'SCALE': 'scale', 'POSITION': 'pos'}
            k = names[key]
            if q:
                v = ch[k]
                return v if isinstance(v, str) else self._e(v)
            if k in ('coup', 'bw'): ch[k] = val
            elif k == 'pos': ch[k] = round(float(val) / 0.02) * 0.02          # the real position control is coarse
            else: ch[k] = float(val)
            self._bump()
            return None
        m = re.match(r'ACQUIRE:(\w+)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            if key == 'NUMACQ':
                s.numacq += 0 if (self.bench.tds_trig_fault == 'nolock' and s.trig['mode'] == 'NORMAL') else 10
                return str(s.numacq)
            if key == 'MODE':
                if q: return s.acq
                s.acq = val; self._bump(); return None
            if key == 'NUMAVG':
                if q: return str(s.avg)
                s.avg = int(val); return None
            if key == 'STATE':
                if q: return '1' if s.running else '0'
                s.running = val in ('RUN', 'ON', '1'); s.numacq = 0; return None
            if key == 'STOPAFTER': return None
        m = re.match(r'HORIZONTAL:MAIN:(SCALE|POSITION)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            attr = 'hscale' if key == 'SCALE' else 'hpos'
            if q: return self._e(getattr(s, attr))
            setattr(s, attr, float(val)); self._bump(); return None
        if u.startswith('TRIGGER:MAIN:TYPE'): return None
        m = re.match(r'TRIGGER:MAIN:EDGE:(SOURCE|SLOPE|COUPLING)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            attr = {'SOURCE': 'src', 'SLOPE': 'slope', 'COUPLING': 'coup'}[key]
            if q: return s.trig[attr]
            s.trig[attr] = val; self._bump(); return None
        m = re.match(r'TRIGGER:MAIN:MODE(\?)?(?: (\S+))?$', u)
        if m:
            if m.group(1): return s.trig['mode']
            s.trig['mode'] = m.group(2); self._bump(); return None
        if u == 'TRIGGER:MAIN SETLEVEL':
            if not s.running:
                s.esr |= 0x10; s.events.append('221,"Settings conflict"')
            return None
        if u == 'TRIGGER:STATE?':
            if self.bench.tds_trig_fault == 'nolock' and s.trig['mode'] == 'NORMAL': return 'READY'
            return 'TRIGGER' if s.trig['mode'] == 'NORMAL' else 'AUTO'
        m = re.match(r'MEASUREMENT:IMMED:(SOURCE|TYPE)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            attr = 'src' if key == 'SOURCE' else 'type'
            if q: return s.meas[attr]
            s.meas[attr] = val; return None
        if u == 'MEASUREMENT:IMMED:VALUE?': return self._e(self._meas_value())
        m = re.match(r'DATA:SOURCE (\w+)$', u)
        if m: s.data_src = m.group(1); return None
        m = re.match(r'DATA:(START|STOP) (\d+)$', u)
        if m: setattr(s, 'data_' + m.group(1).lower(), int(m.group(2))); return None
        if u.startswith('DATA:'): return None
        ch = s.ch[int(s.data_src[-1])] if s.data_src.startswith('CH') else s.ch[1]
        if u == 'WFMPRE:XINCR?': return self._e(self._xinc())
        if u == 'WFMPRE:XZERO?': return self._e(self._xzero())
        if u == 'WFMPRE:YMULT?': return self._e(ch['scale'] / 25.0)
        if u == 'WFMPRE:YOFF?': return self._e(ch['pos'] * 25.0)
        if u == 'WFMPRE:YZERO?': return self._e(0.0)
        if u == 'CURVE?':
            full = self._curve(); a, b = getattr(s, 'data_start', 1), getattr(s, 'data_stop', len(full))
            return 'CURVE ' + ','.join(str(x) for x in full[a - 1:b])
        raise TransportError(f'simulated TDS2000C: unknown command {cmd!r}')

    def query(self, text):
        self.write(text)
        return self.read()


class SimRefDmm(_SimBase):
    """Reference DMM reading the simulated calibrator's DC output (VPOS reference)."""
    def __init__(self, bench):
        super().__init__(bench, 'SIM-DMM')

    def handle(self, cmd):
        u = cmd.upper()
        if u == '*IDN?': return 'KEYSIGHT,SIM-DMM,SIM0001,1.0'
        if u in ('*CLS',) or u.startswith('CONF'): return None
        if u == 'READ?':
            f = self.bench.fluke
            return f"{(f['volts'] * 1.00003 if f['operate'] else 1e-6):+.9E}"
        raise TransportError(f'simulated DMM: unknown command {cmd!r}')

    def query(self, text):
        self.write(text)
        return self.read()


def make_tds_bench(model='2024C', cal='5560A'):
    """Returns (bench, transports) for tds2000c_verification.IO(addrs, transports=...). Keys: scope, cal, dmm."""
    bench = SimBench()
    t = dict(scope=SimTds(bench, model), cal=SimFlukeTransport(bench, cal), dmm=SimRefDmm(bench))
    return bench, t
