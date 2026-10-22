"""Simulated Keithley Model 2000 on the simulated bench (drivers/simulated.py): it "measures" what the simulated calibrator is outputting.

It speaks the command strings drivers/keithley_2000.py sends, keeps each function's own configuration the way the real meter does (range, NPLC / bandwidth,
filter, REL), starts from the *RST state, answers :READ? with the calibrator's output (DC / AC, volts / amps / ohms, with a small gain error and a DC
offset so that REL has something to remove), reports an overflow (+9.9E+37) when the output does not fit the selected range or does not suit the function, and
queues errors the way the real meter does (:SYST:ERR?).  The reply FORMATS of the query commands are assumptions (the manual states the queries but not their
reply text): they are the same assumptions the driver's tolerant parser is written against.

    bench, cal_t, dmm_t = make_k2000_bench('5522A', bus='GPIB')

Test hooks: dmm_t.gain / dmm_t.offset (per function), dmm_t.front (INPUTS switch), dmm_t.errors (queue), dmm_t.sent (every command), dmm_t.range_reply (what a range
query returns for a range R: default R itself), bench.fail_next (substring: the next matching command times out).
"""
from __future__ import annotations

import re

from .simulated import SimBench, SimFlukeTransport, _SimBase
from .transport import TransportError

# range tables: (range, overrange limit of the reading)
RANGES = {
    'VOLT:DC': ((0.1, 0.12), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (1000.0, 1010.0)),
    'VOLT:AC': ((0.1, 0.12), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (750.0, 757.5)),
    'CURR:DC': ((0.01, 0.012), (0.1, 0.12), (1.0, 1.2), (3.0, 3.1)),
    'CURR:AC': ((1.0, 1.2), (3.0, 3.1)),
    'RES': tuple((r, r * 1.2) for r in (1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
    'FRES': tuple((r, r * 1.2) for r in (1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
}
DEFAULT_RANGE = {'VOLT:DC': 1000.0, 'VOLT:AC': 750.0, 'CURR:DC': 3.0, 'CURR:AC': 3.0, 'RES': 1e8, 'FRES': 1e8}
OVERFLOW_TEXT = '+9.900000E+37'
# physical effect on each function: (unit the calibrator must be producing, AC or DC)
SOURCE = {'VOLT:DC': ('V', False), 'VOLT:AC': ('V', True), 'CURR:DC': ('A', False), 'CURR:AC': ('A', True), 'RES': ('OHM', None), 'FRES': ('OHM', None)}


def _fresh_config(node):
    return dict(range=DEFAULT_RANGE[node], auto=True, nplc=1.0, band=30.0, tcon='REP', count=10, avg=False, ref=0.0, ref_state=False)


class SimK2000Transport(_SimBase):
    """The simulated Model 2000 (GPIB or RS-232)."""

    def __init__(self, bench, bus='GPIB'):
        super().__init__(bench, 'SIM-2000')
        self.bus = bus
        self.gain = {n: 1.000002 for n in RANGES}                  # +2 ppm everywhere: inside every limit
        self.offset = {n: 0.0 for n in RANGES}
        self.offset['VOLT:DC'] = 2.5e-6                            # a 2.5 uV offset that REL removes
        self.front = True
        self.errors = []
        self.sent = []
        self.remote_state = False
        self.range_reply = lambda r: r
        self._power_up()

    def _power_up(self):
        self.func = 'VOLT:DC'
        self.cfg = {n: _fresh_config(n) for n in RANGES}
        self.init_cont = False
        self.elem = 'READ'
        self.last = None

    # ---- the physics
    def _signal(self, node):
        """What the selected function sees right now: the calibrator output on a matching function, else nothing (0 / open)."""
        f = self.bench.fluke
        unit, ac = SOURCE[node]
        ext = getattr(self.bench, 'external_input', None)         # a standard the technician connected (the 5725A system), independent of the calibrator
        if ext is not None:
            return float(ext) if unit == 'V' and ac is True else None
        if not f['operate'] or f.get('unit', 'V') != unit:
            return None
        if ac is True and not f['freq']:
            return None
        if ac is False and f['freq']:
            return None
        return float(f['volts'])

    def _reading(self):
        node, c = self.func, self.cfg[self.func]
        value = self._signal(node)
        unit = SOURCE[node][0]
        if value is None:
            if unit == 'OHM':
                return OVERFLOW_TEXT                                # nothing connected / a source that is not a resistance
            value = 0.0
        else:
            value = value * self.gain[node]
        top = dict(RANGES[node]).get(c['range'], c['range'])
        if abs(value) > top:
            return OVERFLOW_TEXT
        raw = value + self.offset[node]
        if c['ref_state']:
            raw -= c['ref']
        self.last = raw
        return f'{raw:+.6E}'

    def _push(self, text):
        self.errors.append(text)

    def _select_range(self, node, expected):
        for rng, top in RANGES[node]:
            if abs(expected) <= top:
                return rng
        return RANGES[node][-1][0]

    # ---- command handling
    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        self.remote_state = True
        if u == '*IDN?':
            return 'KEITHLEY INSTRUMENTS INC.,MODEL 2000,0SIM0001,A19  /A02'
        if u == '*RST':
            self._power_up(); return None
        if u == '*CLS':
            self.errors = []; return None
        if u == '*OPC?':
            return '1'
        if u in (':SYST:ERR?', 'SYST:ERR?'):
            return self.errors.pop(0) if self.errors else '0,"No error"'
        if u == ':SYST:FRSW?':
            return '1' if self.front else '0'
        if u == ':SYST:AZER:STAT?':
            return '1'
        if u in (':SYST:REM', ':SYST:LOC'):
            if self.bus != 'RS232':
                self._push('-113,"Undefined header"'); return None
            self.remote_state = u.endswith('REM'); return None
        if u == ':INIT:CONT OFF' or u == ':INIT:CONT ON':
            self.init_cont = u.endswith('ON'); return None
        if u == ':INIT:CONT?':
            return '1' if self.init_cont else '0'
        if u == ':FORM:ELEM READ':
            self.elem = 'READ'; return None
        if u == ':FORM:ELEM?':
            return self.elem
        if u == ':READ?':
            if self.init_cont:
                self._push('-213,"Init ignored"')
            return self._reading()
        if u == ':FETC?':
            if self.last is None:
                self._push('-230,"Data corrupt or stale"'); return '+0.000000E+00'
            return f'{self.last:+.6E}'
        m = re.match(r"^:SENS:FUNC\s+'([A-Z:]+)'$", u)
        if m:
            if m.group(1) not in RANGES:
                self._push('-224,"Illegal parameter value"'); return None
            self.func = m.group(1); self.last = None; return None
        if u == ':SENS:FUNC?':
            return f'"{self.func}"'
        m = re.match(r'^:SENS:(VOLT:DC|VOLT:AC|CURR:DC|CURR:AC|FRES|RES):(.+)$', u)
        if m:
            return self._sense(m.group(1), m.group(2))
        raise TransportError(f'simulated 2000: unknown command {cmd!r}')

    def _sense(self, node, rest):
        c = self.cfg[node]
        head, _, arg = rest.partition(' ')
        ac = node.endswith(':AC')
        if head == 'RANG':
            c['range'] = self._select_range(node, float(arg)); c['auto'] = False; return None
        if head == 'RANG?':
            return f'{self.range_reply(c["range"]):+.6E}'
        if head == 'RANG:AUTO?':
            return '1' if c['auto'] else '0'
        if head == 'NPLC' and not ac:
            c['nplc'] = float(arg); return None
        if head == 'NPLC?' and not ac:
            return f'{c["nplc"]:+.6E}'
        if head == 'DET:BAND' and ac:
            c['band'] = float(arg); return None
        if head == 'DET:BAND?' and ac:
            return f'{c["band"]:+.6E}'
        if head == 'AVER:TCON':
            c['tcon'] = arg; return None
        if head == 'AVER:TCON?':
            return c['tcon']
        if head == 'AVER:COUN':
            c['count'] = int(float(arg)); return None
        if head == 'AVER:COUN?':
            return f'{c["count"]:+d}'
        if head == 'AVER:STAT':
            c['avg'] = arg == 'ON'; return None
        if head == 'AVER:STAT?':
            return '1' if c['avg'] else '0'
        if head == 'REF:STAT':
            c['ref_state'] = arg == 'ON'; return None
        if head == 'REF:STAT?':
            return '1' if c['ref_state'] else '0'
        if head == 'REF:ACQ':
            if node != self.func or self.last is None:                 # "functional only if the instrument is on the specified function" and a reading exists (p. 5-44)
                self._push('-221,"Settings conflict"'); return None
            c['ref'] = self.last; return None
        if head == 'REF?':
            return f'{c["ref"]:+.6E}'
        raise TransportError(f'simulated 2000: unknown command {rest!r} for {node}')

    def query(self, text):
        self.write(text)
        return self.read()


class SimFlukeComp(SimFlukeTransport):
    """The simulated 5522A / 5560A with the ZCOMP (impedance compensation) command the Keithley resistance points use (5522A Operators Manual p. 6-49)."""

    def __init__(self, bench, model='5522A'):
        super().__init__(bench, model)
        self.zcomp = 'NONE'

    def _handle(self, cmd):
        u = cmd.upper()
        if u.startswith('ZCOMP'):
            if self.model == '5560A':
                raise TransportError(f'simulated 5560A: unknown command {cmd!r}')       # the 5560A manual is not in the project: no ZCOMP is assumed
            if u == 'ZCOMP?':
                return self.zcomp
            mode = u.split()[1]
            f = self.bench.fluke
            if mode != 'NONE' and (f.get('unit') != 'OHM' or float(f['volts']) >= 110e3):
                self.errors = getattr(self, 'errors', []) + ['-221,"Can\'t change compensation now"']
                return None
            self.zcomp = mode
            return None
        reply = super()._handle(cmd)
        if re.match(r'OUT\s+[-+0-9.eE]+OHM$', u) and float(self.bench.fluke['volts']) >= 110e3:
            self.zcomp = 'NONE'                                                          # above 110 kohm the compensation is always NONE
        return reply


def make_k2000_bench(cal='5522A', bus='GPIB'):
    """(bench, calibrator transport, Model 2000 transport)."""
    bench = SimBench()
    return bench, SimFlukeComp(bench, cal), SimK2000Transport(bench, bus)
