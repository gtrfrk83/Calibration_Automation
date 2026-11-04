"""Simulated Keithley DMM6500 on the simulated bench (drivers/simulated.py): it "measures" what the simulated calibrator is outputting.

NOT A REPLAY OF A REAL METER.  The bench-first workflow (NOTES.md) has not been done for the DMM6500: no reply below was recorded from an instrument.  The command
strings are the ones drivers/keithley_dmm6500.py sends; the reply FORMATS of the query commands are assumptions (the manual states the queries, not their reply text) and
are the ones the driver's tolerant parser is written against.  The behaviour (ranges, overflow, offset compensation limited to 10 kohm, the front / rear switch, the
digitize capture) is written from the Reference and Calibration manuals and is UNVERIFIED.  When a bench session has recorded real replies, replace this with a replay.

    bench, cal_t, dmm_t = make_dmm6500_bench('5560A')                 # 5560A / 5700A (and, for other procedures, 5522A / 5520A) and the meter on one bench
    bench, cal_t, dmm_t, ref_t = make_dmm6500_bench('5560A', reference=True)     # plus a simulated 3458A reading the same source

Test hooks: dmm_t.gain / dmm_t.offset (per function node), dmm_t.front (TERMINALS switch), dmm_t.errors (queue), dmm_t.sent (every command), dmm_t.shorted (4-wire short fitted), dmm_t.noise (digitize), bench.fail_next (substring: the next matching command times out).
"""
from __future__ import annotations

import re

import rtd_cvd
from .simulated import SimBench, _SimBase
from .simulated_k2000 import SimFlukeComp
from .transport import TransportError

OVER = '+9.900000E+37'
RANGES = {
    'VOLT:DC': (0.1, 1.0, 10.0, 100.0, 1000.0), 'VOLT:AC': (0.1, 1.0, 10.0, 100.0, 750.0), 'DIG:VOLT': (0.1, 1.0, 10.0, 100.0, 1000.0),
    'CURR:DC': (1e-5, 1e-4, 1e-3, 1e-2, 0.1, 1.0, 3.0, 10.0), 'CURR:AC': (1e-4, 1e-3, 1e-2, 0.1, 1.0, 3.0, 10.0), 'DIG:CURR': (1e-5, 1e-4, 1e-3, 1e-2, 0.1, 1.0, 3.0, 10.0),
    'RES': (1.0, 10.0, 100.0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8), 'FRES': (1.0, 10.0, 100.0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8), 'CAP': (1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4),
    'FREQ': (10.0,), 'TEMP': (1.0,),
}
FUNC_NODE = {'VOLT:DC': 'VOLT:DC', 'VOLT': 'VOLT:DC', 'VOLT:AC': 'VOLT:AC', 'CURR:DC': 'CURR:DC', 'CURR': 'CURR:DC', 'CURR:AC': 'CURR:AC', 'RES': 'RES', 'FRES': 'FRES',
             'FREQ': 'FREQ', 'CAP': 'CAP', 'TEMP': 'TEMP'}
SOURCE = {'VOLT:DC': ('V', False), 'VOLT:AC': ('V', True), 'DIG:VOLT': ('V', False), 'CURR:DC': ('A', False), 'CURR:AC': ('A', True), 'DIG:CURR': ('A', False), 'RES': ('OHM', None),
          'FRES': ('OHM', None)}
# NIST type J (mV) at the temperatures the verification uses and a few more: piecewise-linear inverse, exact at the three verification points
TYPE_J = ((-210.0, -8.095), (-190.0, -7.659), (0.0, 0.0), (100.0, 5.269), (200.0, 10.779), (300.0, 16.327), (400.0, 21.848), (500.0, 27.393), (600.0, 33.102), (700.0, 39.132),
          (750.0, 42.281), (1200.0, 69.553))


def _j_temperature(volts):
    mv = volts * 1000.0
    for (t0, v0), (t1, v1) in zip(TYPE_J, TYPE_J[1:]):
        if v0 <= mv <= v1:
            return t0 + (t1 - t0) * (mv - v0) / (v1 - v0)
    return TYPE_J[-1][0] if mv > 0 else TYPE_J[0][0]


def _fresh():
    return {n: dict(range=RANGES[n][-1], auto=True) for n in RANGES}


class SimDMM6500Transport(_SimBase):
    """The simulated DMM6500 (USB, LAN or GPIB)."""

    def __init__(self, bench, bus='USB'):
        super().__init__(bench, 'SIM-DMM6500')
        self.bus = bus
        self.gain = {n: 1.000002 for n in RANGES}              # +2 ppm everywhere: inside every limit
        self.offset = {n: 0.0 for n in RANGES}
        self.offset['VOLT:DC'] = 2.5e-6                       # a 2.5 uV offset that REL removes
        self.front = True
        self.errors, self.sent = [], []
        self.noise = 0.0
        self.external_value = None                              # a standard the operator connects (the engine sets it in a virtual run for the points it hands to 'your own standard')
        self.shorted = False                                    # a 4-wire short is on the input (the engine sets it for the zero points of a virtual run)
        self._power_up()

    def _power_up(self):
        self.store, self.cfg = {}, _fresh()
        self.func, self.dig = 'VOLT:DC', None
        self.rel = {}
        self.last = None
        self.count, self.dcount = 1, 10000

    # ---- physics ------------------------------------------------------------------------------------------------------
    def _node(self):
        return self.dig or self.func

    def _signal(self, node):
        f = self.bench.fluke
        unit, ac = SOURCE[node]
        if not f['operate'] or f.get('unit', 'V') != unit:
            return None
        if ac is True and not f['freq']:
            return None
        if ac is False and f['freq']:
            return None
        return float(f['volts'])

    def _value(self):
        """The true value of the selected function from the bench, or None when nothing suitable is connected (an open / overflow reading)."""
        node = self._node()
        f = self.bench.fluke
        if self.external_value is not None:
            return float(self.external_value) + (0.375e-9 if node == 'CAP' else 0.0)      # the operator's capacitance standard sits behind the same cable
        if node == 'FREQ':
            return float(f['freq']) * 1.000001 if f['operate'] and f['freq'] and f.get('unit', 'V') == 'V' else None
        if node == 'CAP':                                       # 0.375 nF of cable plus whatever capacitance the calibrator is sourcing (OUT <n>NF / UF / F)
            scale = {'F': 1.0, 'NF': 1e-9, 'UF': 1e-6}.get(f.get('unit', ''), None)
            source = float(f['volts']) * scale if (f['operate'] and scale) else 0.0
            return 0.375e-9 + source
        if node == 'TEMP':
            tr = self.store.get(':SENS:TEMP:TRAN', 'TC')
            if tr == 'TC':
                v = float(f['volts']) if f['operate'] and f.get('unit', 'V') == 'V' and not f['freq'] else 0.0
                return _j_temperature(v + 0.0)
            ohms = self._signal_ohms()
            return None if ohms is None else rtd_cvd.temperature(ohms)
        v = self._signal(node)
        return v

    def _signal_ohms(self):
        f = self.bench.fluke
        return float(f['volts']) if f['operate'] and f.get('unit') == 'OHM' else None

    def _reading(self):
        node = self._node()
        c = self.cfg[node]
        value = self._value()
        if value is None:
            if node == 'FREQ' or SOURCE.get(node, ('', None))[0] == 'OHM' and not self.shorted or node == 'TEMP':
                return OVER                                     # nothing connected / a source that does not suit the function
            value = 0.0
        elif node != 'TEMP':
            value *= self.gain[node]
        top = c['range'] * 1.2 if node not in ('TEMP', 'FREQ') else 1e9
        if abs(value) > top:
            return OVER
        raw = value + (self.offset[node] if node != 'TEMP' else 0.0)
        if self.store.get(f':SENS:{node}:REL:STAT') == 'ON':
            raw -= self.rel.get(node, 0.0)
        self.last = raw
        return f'{raw:+.6E}'

    def _push(self, text):
        self.errors.append(text)

    # ---- commands -----------------------------------------------------------------------------------------------------
    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        if u == '*IDN?':
            return 'KEITHLEY INSTRUMENTS,MODEL DMM6500,04SIM001,1.7.12b'
        if u == '*RST':
            self._power_up(); return None
        if u == '*CLS':
            return None
        if u == '*OPC?':
            return '1'
        if u == ':SYST:ERR?':
            return self.errors.pop(0) if self.errors else '0,"No error"'
        if u == ':ROUT:TERM?':
            return 'FRON' if self.front else 'REAR'
        if u == ':SYST:LFR?':
            return '50'
        if u == ':SENS:COUN?':
            return str(self.count)
        m = re.match(r'^:SENS:COUN (\d+)$', u)
        if m:
            self.count = int(m.group(1)); return None
        if u == ':SENS:DIG:COUN?':
            return str(self.dcount)
        m = re.match(r'^:SENS:DIG:COUN (\d+)$', u)
        if m:
            self.dcount = int(m.group(1)); return None
        m = re.match(r'^:FORM:ASC:PREC (\d+)$', u)
        if m:
            self.store['PREC'] = m.group(1); return None
        if u == ':FORM:ASC:PREC?':
            return self.store.get('PREC', '0')
        if u == ':TRAC:CLE':
            return None
        if u == ':READ?':
            return self._reading()
        if u == ':READ:DIG?':
            return self._reading()
        m = re.match(r'^:TRAC:DATA\? 1,(\d+),"DEFBUFFER1",READ$', u)
        if m:
            n = int(m.group(1))
            base = float(self._reading())
            if base >= 9e37:
                return ','.join([OVER] * n)
            return ','.join(f'{base + self.noise * ((i % 5) - 2) / 2:+.6E}' for i in range(n))
        m = re.match(r'^:SENS:FUNC "([A-Z:]+)"$', u)
        if m:
            if m.group(1) not in FUNC_NODE:
                self._push('-224,"Illegal parameter value"'); return None
            self.func, self.dig, self.last = FUNC_NODE[m.group(1)], None, None; return None
        if u == ':SENS:FUNC?':
            return 'NONE' if self.dig else {'FREQ': 'FREQ:VOLT'}.get(self.func, self.func)      # BENCH FINDING 2026-11-04: the real meter answers the long form, unquoted: FREQ:VOLT
        m = re.match(r'^:SENS:DIG:FUNC "(VOLT|CURR)"$', u)
        if m:
            self.dig, self.last = f'DIG:{m.group(1)}', None; return None
        if u == ':SENS:DIG:FUNC?':
            return self.dig.split(':')[1] if self.dig else 'NONE'
        m = re.match(r'^:SENS:(VOLT:DC|VOLT:AC|CURR:DC|CURR:AC|FRES|RES|FREQ|CAP|TEMP|DIG:VOLT|DIG:CURR):(.+)$', u)
        if m:
            return self._sense(m.group(1), m.group(2))
        self._push('-113,"Undefined header"')
        return None

    def _select_range(self, node, value):
        for r in RANGES[node]:
            if value <= r * 1.0000001:
                return r
        return RANGES[node][-1]

    def _sense(self, node, rest):
        c = self.cfg[node]
        head, _, arg = rest.partition(' ')
        key = f':SENS:{node}:{head.rstrip("?")}'
        if head == 'RANG' and node in ('FREQ', 'TEMP'):
            self._push('-113,"Undefined header"'); return None
        if head == 'RANG':
            c['range'] = self._select_range(node, abs(float(arg))); return None
        if head == 'RANG?':
            return f'{c["range"]:+.6E}'
        if head.startswith('RANG:AUTO') and node.startswith('DIG:'):   # BENCH FINDING 2026-11-04: a real DMM6500 gives no answer to :SENS:DIG:VOLT:RANG:AUTO? (VI_ERROR_TMO); digitize has no autorange
            self._push('-113,"Undefined header"'); return None
        if head == 'RANG:AUTO':
            c['auto'] = arg == 'ON'; return None
        if head == 'RANG:AUTO?':
            return '1' if c['auto'] else '0'
        if head == 'REL:ACQ':
            if node != self._node():
                self._push('-221,"Settings conflict"'); return None
            self._reading()                                     # the command triggers a new measurement and stores it as the offset (Reference Manual p. 12-113)
            self.rel[node] = self.last if self.last is not None else 0.0; return None
        if head == 'OCOM' and node == 'FRES':
            if arg == 'ON' and c['range'] > 1e5:                # the Calibration Manual's warning text: 'expected value from 1 to 100000' (the Reference Manual p. 12-106 says 10 kohm)
                self._push('1131,"Parameter, measure range, expected value from 1 to 100000"'); return None
        if head.endswith('?'):
            v = self.store.get(key.rstrip('?') if False else key)
            if v is None:
                v = {'NPLC': '1', 'AZER': 'ON', 'DET:BAND': '3', 'REL:STAT': 'OFF', 'OCOM': 'AUTO', 'ODET': 'OFF', 'INP': 'MOHM10', 'TRAN': 'TC', 'TC:TYPE': 'K', 'TC:RJUN:RSEL': 'SIM',
                     'TC:RJUN:SIM': '23', 'UNIT': 'CEL', 'SRAT': '1000000', 'APER': '0.016667', 'THR:RANG': '10'}.get(head[:-1], '0')
            if v in ('ON', 'OFF') and head[:-1] in ('AZER', 'REL:STAT', 'ODET'):
                return '1' if v == 'ON' else '0'
            return v
        if head == 'OCOM':
            self.store[key] = arg; return None
        if arg == '':
            self._push('-113,"Undefined header"'); return None
        self.store[key] = arg.strip()
        return None

    def query(self, text):
        self.write(text)
        return self.read()


def make_dmm6500_bench(cal='5560A', bus='USB', reference=False):
    """(bench, calibrator transport, DMM6500 transport) or, with reference=True, plus a simulated 3458A on the same bench."""
    bench = SimBench()
    bench.freq_aware = True
    if cal == '5700A':
        from .simulated_5700a import SimFluke5700ATransport
        cal_t = SimFluke5700ATransport(bench)
    else:
        cal_t = SimFlukeComp(bench, cal)
    dmm_t = SimDMM6500Transport(bench, bus)
    if not reference:
        return bench, cal_t, dmm_t
    from .simulated_3458a import Sim3458ATransport
    ref_t = Sim3458ATransport(bench)
    ref_t.offsets['OHMF'] = 0.0                      # the 3458A simulator's 0.5 mohm 4-wire offset is larger than the 1 ohm tolerance; a real 3458A is nulled
    return bench, cal_t, dmm_t, ref_t
