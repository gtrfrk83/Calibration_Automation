"""Software stand-ins for the Tektronix TBS1000 and TBS1000C benches: the simulated oscilloscope + the simulated 5560A / 5522A (SCOPE DCV,
LEVSINE, MARKER) of drivers/simulated_tds.py, linked so the shared Tektronix procedure runs end to end with no hardware.

  SimTbs1000   the non-C TBS1000: the TDS2000C simulator (same programmer manual, same command strings) with the TBS *IDN? text, the TBS1000
               model list (two or four channels) and its bandwidths.
  SimTbs1000C  the TBS1000C: answers the TBS1000C programmer-manual commands the driver sends (TRIGger:A, WFMOutpre, CH<x>:PRObe:GAIN,
               CH<x>:BANdwidth FULl, CH<x>:OFFSet, HORizontal:RECOrdlength, HORizontal:MAIn:DELay, HORizontal:MAIn:POSition in percent,
               MEASUrement:IMMed:SOUrce1, CALibrate:INTERNal:STATus?) over the same signal model; 15 horizontal divisions, record length 20000
               after FACtory.  Commands of the TDS / TBS1000 family that the TBS1000C does not have (TRIGger:MAIn..., WFMPre..., DATa:ENCdg,
               CALibrate:STATUS?) are rejected here, so a TDS command sent to a TBS1000C fails the tests.
Fault knobs are those of SimTds (bench.tds_gain_error, tds_bw_scale, tds_ppm, tds_trig_fault ...).  Not evidence of anything.
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, SimFlukeTransport
from .simulated_tds import SimRefDmm, SimTds
from .transport import TransportError

TBS1000_BW_MHZ = {'1022': 25, '1042': 40, '1062': 60, '1064': 60, '1102': 100, '1104': 100, '1152': 150, '1154': 150}
TBS1000_FOUR = ('1064', '1104', '1154')
TBS1000C_BW_MHZ = {'1052C': 50, '1072C': 70, '1102C': 100, '1202C': 200}


class SimTbs1000(SimTds):
    def __init__(self, bench, model='1104'):
        super().__init__(bench, model)
        self.name = 'SIM-TBS1000'
        self.s.channels = 4 if model in TBS1000_FOUR else 2

    @property
    def bw_hz(self):
        return TBS1000_BW_MHZ[self.s.model] * 1e6 * self.bench.tds_bw_scale

    def handle(self, cmd):
        if cmd.strip().upper() == '*IDN?':
            return f'TEKTRONIX,TBS {self.s.model},SIM0001,CF:91.1CT FV:v4.00'
        return super().handle(cmd)


class SimTbs1000C(SimTds):
    DIVS = 15

    def __init__(self, bench, model='1202C'):
        super().__init__(bench, model)
        self.name = 'SIM-TBS1000C'
        self.s.channels = 2
        self._c_reset()

    def _c_reset(self):
        s = self.s
        s.reclen, s.delay_mode, s.delay, s.hpct = 20000, 'OFF', 0.0, 50.0
        for n in s.ch:
            s.ch[n]['offset'] = 0.0

    @property
    def bw_hz(self):
        return TBS1000C_BW_MHZ[self.s.model] * 1e6 * self.bench.tds_bw_scale

    # -- record geometry: 15 divisions, trigger at hpct % of the record, or the record centred on the delay time ---------------------------
    def _npts(self):
        return self.s.reclen

    def _xinc(self):
        return self.DIVS * self.s.hscale / self._npts()

    def _xzero(self):
        span = self.DIVS * self.s.hscale
        if self.s.delay_mode == 'ON':
            return self.s.delay - span / 2
        return -span * self.s.hpct / 100.0

    def _volts_record(self):
        s, f = self.s, self._fluke()
        n = self._npts()
        xs = [self._xzero() + i * self._xinc() for i in range(n)]
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
        return [dc * (1 + self.bench.tds_gain_error)] * n

    # -- the TBS1000C command set ----------------------------------------------------------------------------------------------------------
    def _bad(self, cmd):
        raise TransportError(f'simulated TBS1000C: unknown command {cmd!r}')

    def handle(self, cmd):
        s, c = self.s, cmd.strip()
        u = c.upper()
        if u == '*IDN?':
            return f'TEKTRONIX,TBS{s.model},SIM0001,CF:91.1CT FV:v1.20 TBS 1XXXC:v1.00'
        if u == 'FACTORY':
            s.reset(); self._c_reset(); return None
        if u.startswith(('TRIGGER:MAIN', 'WFMPRE', 'DATA:ENCDG', 'CALIBRATE:STATUS')) or re.match(r'CH\d:PROBE( |\?|$)', u) \
                or re.match(r'MEASUREMENT:IMMED:SOURCE( |\?|$)', u):
            self._bad(cmd)
        if u == 'CALIBRATE:INTERNAL:STATUS?':
            return 'PASS' if self.bench.tds_self_cal_result == 0 else 'FAIL'
        m = re.match(r'CH(\d):(PROBE:GAIN|BANDWIDTH|OFFSET)(\?)?(?: (\S+))?$', u)
        if m:
            n, key, q, val = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            if n > s.channels:
                s.esr |= 0x20; s.events.append('113,"Undefined header"'); return None
            ch = s.ch[n]
            if key == 'PROBE:GAIN':
                if q: return self._e(1.0 / ch['probe'])
                ch['probe'] = 1.0 / float(val); self._bump(); return None
            if key == 'BANDWIDTH':
                if q: return 'TWENTY' if ch['bw'] == 'ON' else 'FULL'
                if val not in ('FULL', 'FUL', 'TWENTY', 'TWE'):
                    s.esr |= 0x20; s.events.append('104,"Data type error"'); return None
                ch['bw'] = 'ON' if val.startswith('TWE') else 'OFF'; self._bump(); return None
            if q: return self._e(ch['offset'])
            ch['offset'] = float(val); self._bump(); return None
        m = re.match(r'HORIZONTAL:(RECORDLENGTH|MAIN:DELAY:MODE|MAIN:DELAY:TIME|MAIN:POSITION)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            attr = {'RECORDLENGTH': 'reclen', 'MAIN:DELAY:MODE': 'delay_mode', 'MAIN:DELAY:TIME': 'delay', 'MAIN:POSITION': 'hpct'}[key]
            if q:
                v = getattr(s, attr)
                return v if isinstance(v, str) else (str(v) if attr == 'reclen' else self._e(v))
            if attr == 'reclen':
                if int(val) not in (1000, 2000, 20000):
                    s.esr |= 0x20; s.events.append('222,"Data out of range"'); return None
                s.reclen = int(val)
            elif attr == 'delay_mode':
                s.delay_mode = 'ON' if val in ('ON', '1') else 'OFF'
            else:
                setattr(s, attr, float(val))
            self._bump(); return None
        if u.startswith('TRIGGER:A:TYPE'):
            return None
        if u == 'TRIGGER:A SETLEVEL':
            return super().handle('TRIGGER:MAIN SETLEVEL')
        m = re.match(r'TRIGGER:A:(EDGE:SOURCE|EDGE:SLOPE|EDGE:COUPLING|MODE)(\?)?(?: (\S+))?$', u)
        if m:
            key, q, val = m.group(1), m.group(2), m.group(3)
            if key == 'EDGE:SOURCE':
                if q: return 'AUX' if s.trig['src'] == 'EXT' else s.trig['src']
                if val not in ('CH1', 'CH2', 'AUX', 'LINE'):
                    s.esr |= 0x20; s.events.append('104,"Data type error"'); return None
                val = 'EXT' if val == 'AUX' else val
            return super().handle(f'TRIGGER:MAIN:{key}' + ('?' if q else f' {val}'))
        m = re.match(r'MEASUREMENT:IMMED:SOURCE1(\?)?(?: (\S+))?$', u)
        if m:
            return super().handle('MEASUREMENT:IMMED:SOURCE' + ('?' if m.group(1) else f' {m.group(2)}'))
        if u == 'WFMOUTPRE:ENCDG ASCII':
            return None
        m = re.match(r'WFMOUTPRE:(XINCR|XZERO|YMULT|YOFF|YZERO)\?$', u)
        if m:
            return super().handle(f'WFMPRE:{m.group(1)}?')
        if u == 'CURVE?':
            full = self._curve(); a, b = getattr(s, 'data_start', 1), getattr(s, 'data_stop', len(full))
            return ','.join(str(x) for x in full[a - 1:b])
        return super().handle(cmd)


def make_tbs1000_bench(model='1104', cal='5560A'):
    """Returns (bench, transports) for the TBS1000 family (tbs1000_verification). Keys: scope, cal, dmm."""
    bench = SimBench()
    return bench, dict(scope=SimTbs1000(bench, model), cal=SimFlukeTransport(bench, cal), dmm=SimRefDmm(bench))


def make_tbs1000c_bench(model='1202C', cal='5560A'):
    """Returns (bench, transports) for the TBS1000C family (tbs1000_verification). Keys: scope, cal, dmm."""
    bench = SimBench()
    return bench, dict(scope=SimTbs1000C(bench, model), cal=SimFlukeTransport(bench, cal), dmm=SimRefDmm(bench))
