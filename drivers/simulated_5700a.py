"""Simulated Fluke 5700A on the simulated bench (drivers/simulated.py): the output state lives in bench.fluke, so the simulated meters measure what it outputs.

NOT A REPLAY OF A REAL 5700A.  No reply below was recorded from an instrument; the command strings are the ones drivers/fluke_5700a.py sends (from the Series II
Remote Programming Reference Guide) and the reply formats are assumptions: ISR? answers a decimal integer, FAULT? an integer (0 = none).  Behaviour that the guide does not state
(which outputs it refuses) is limited to what the 5700A cannot make at all: capacitance, and an output while a fault condition has been injected.  UNVERIFIED.

    bench, cal_t = make_5700a_bench()
Test hooks: cal_t.faults (queue of codes), cal_t.sent, cal_t.settle_polls (how many ISR? reads before SETTLED, default 1), cal_t.refuse (substring: commands containing it fault).
"""
from __future__ import annotations

import re

from .simulated import SimBench, _SimBase
from .transport import TransportError

UNITS = {'V': 'V', 'MV': 'V', 'A': 'A', 'MA': 'A', 'UA': 'A', 'OHM': 'OHM', 'KOHM': 'OHM', 'MAOHM': 'OHM', 'MOHM': 'OHM'}
SCALE = {'V': 1.0, 'MV': 1e-3, 'A': 1.0, 'MA': 1e-3, 'UA': 1e-6, 'OHM': 1.0, 'KOHM': 1e3, 'MAOHM': 1e6, 'MOHM': 1e6}


class SimFluke5700ATransport(_SimBase):
    def __init__(self, bench, bus='GPIB'):
        super().__init__(bench, 'SIM-5700A')
        self.bus = bus
        self.faults, self.sent, self.refuse = [], [], None
        self.extsense, self.rcomp, self.post = False, False, 'NORMAL'
        self.boost, self.rlock, self.btype = False, False, {'V': 'VB5725', 'I': 'IB5725'}
        self.amp_connected = True                                # a 5725A is on the cable and powered (test hook)
        self.out_since_boost = False
        self.rlock_unit = None
        self.settle_polls = 1
        self._polls = 0

    def _isr(self):
        f = self.bench.fluke
        self._polls += 1
        settled = f['operate'] and self._polls > self.settle_polls
        f_ = self.bench.fluke
        needs = (f_.get('unit') == 'A' and abs(f_['volts']) > 2.2) or (f_.get('unit') == 'V' and f_['freq'] > 1000 and abs(f_['volts']) > 220)      # the amplifier is selected by itself above the 5700A's own range
        active = (self.boost and self.out_since_boost) or needs    # BENCH FINDINGS 2026-11-04: bit 3 read 0 straight after BOOST ON and 1 after BOOST OFF at 740 V / 50 kHz: it follows the output setting (UNVERIFIED model)
        return (int(bool(f['operate'])) | (int(self.extsense) << 2) | (int(active) << 3) | (int(self.rcomp) << 4) | (int(self.rlock) << 5) | (int(settled) << 12))

    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        f = self.bench.fluke
        if self.refuse and self.refuse.upper() in u:
            self.faults.append(540)
            return None
        if u == '*IDN?':
            return 'FLUKE,5700A,SIM00001,1.0+1.0+1.0'
        if u == '*RST':
            f.update(operate=False, volts=0.0, freq=0.0, unit='V')
            self.extsense = self.rcomp = self.boost = self.rlock = False
            self.post = 'NORMAL'
            return None
        if u in ('*CLS', 'REMOTE', 'LOCAL'):
            if u == '*CLS':
                self.faults = []
            return None
        if u == '*OPC?':
            return '1'
        if u == 'FAULT?':
            return str(self.faults.pop(0)) if self.faults else '0'
        m = re.match(r'^EXPLAIN\? (\d+)$', u)
        if m:
            return {'860': "Can't Use Amplifier For This Output"}.get(m.group(1), f'simulated fault {m.group(1)}')
        if u == 'ISR?':
            return str(self._isr())
        if u == 'STBY':
            f['operate'] = False; self._polls = 0; return None
        if u == 'OPER':
            f['operate'] = True; self._polls = 0; return None
        m = re.match(r'^BOOST (ON|OFF)$', u)
        if m:
            self.boost = m.group(1) == 'ON' and self.amp_connected; self.out_since_boost = False; return None
        m = re.match(r'^RANGELCK (ON|OFF)$', u)
        if m:
            self.rlock = m.group(1) == 'ON'
            self.rlock_unit = f.get('unit') if self.rlock else None          # RANGELCK locks the PRESENT range (guide): remembered as the present function
            return None
        m = re.match(r'^BTYPE (VB5725|IB5725)$', u)
        if m:
            self.btype['V' if m.group(1).startswith('VB') else 'I'] = m.group(1); return None
        if u == 'BTYPE?':
            return f"{self.btype['V']},{self.btype['I']}"
        m = re.match(r'^EXTSENSE (ON|OFF)$', u)
        if m:
            self.extsense = m.group(1) == 'ON'; return None
        m = re.match(r'^RCOMP (ON|OFF)$', u)
        if m:
            self.rcomp = m.group(1) == 'ON'; return None
        m = re.match(r'^CUR_POST (NORMAL|AUX|IB5725)$', u)
        if m:
            self.post = m.group(1); return None
        if u == 'CUR_POST?':
            return self.post
        m = re.match(r'^OUT ([-+0-9.E]+) ([A-Z]+)(?:, ([0-9.E+-]+) HZ)?$', u)
        if m:
            unit = m.group(2)
            if unit not in UNITS:
                self.faults.append(536); return None
            if self.rlock and UNITS[unit] != self.rlock_unit:
                self.faults.append(860); return None             # BENCH FINDING 2026-11-04: fault 860 "Can't Use Amplifier For This Output" when the range lock was set in another function (the cause is UNVERIFIED)
            value = float(m.group(1)) * SCALE[unit]
            hz = float(m.group(3)) if m.group(3) else 0.0
            if (UNITS[unit] == 'A' and abs(value) > 2.2 and not self.boost) or (UNITS[unit] == 'V' and hz > 1000 and abs(value) > 220 and not self.boost):
                self.faults.append(540); return None             # above the 5700A's own range: the 5725A (BOOST) is needed (the sheet's ranges; UNVERIFIED)
            f['volts'] = value
            self.out_since_boost = True
            f['unit'] = UNITS[unit]
            f['freq'] = float(m.group(3)) if m.group(3) else 0.0
            return None
        if u == 'OUT?':
            return f"{f['volts']:.9E},{f['unit']},{f['freq']:.1f}"
        self.faults.append(1)                                  # unknown command: a command fault
        return None

    def query(self, text):
        self.write(text)
        return self.read()


def make_5700a_bench(bus='GPIB'):
    """(bench, 5700A transport)."""
    bench = SimBench()
    bench.freq_aware = True
    return bench, SimFluke5700ATransport(bench, bus)
