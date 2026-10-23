"""Simulated Keysight 34410A on the simulated bench (drivers/simulated.py): it "measures" what the simulated calibrator is outputting.

It speaks the command strings drivers/keysight_34410a.py sends, keeps each function's own configuration (range, NPLC / AC filter), starts from the *RST state
(CONFigure resets the integration time to 1 PLC and the AC filter to 20 Hz, so a missed 100 NPLC / 3 Hz write is visible), answers READ? with the calibrator's
output (DC / AC, volts / amps / ohms, with a small gain error and offset), the calibrator's frequency for the frequency function, and the capacitance standard the
operator connects (bench.external_input) for capacitance.  With nothing sourced (zero-offset points: a short or an open input) it reads the small offset.  It reports
+9.9E+37 when the signal does not fit the selected range, and queues errors the way the real meter does (SYST:ERR?).  The reply FORMATS of the query commands are
assumptions (the guides state the queries but not their reply text): they are the same assumptions the driver's tolerant parser is written against.

    bench, cal_t, dmm_t = make_34410a_bench('5522A', bus='GPIB')           # make_34410a_bench('5522A', 'GPIB', model='34411A') answers as a 34411A

Test hooks: dmm_t.gain / dmm_t.offset (per node), dmm_t.terminals ('FRON' / 'REAR'), dmm_t.errors, dmm_t.sent, dmm_t.range_reply, dmm_t.idn_text.
"""
from __future__ import annotations

import re

from .simulated import SimBench, _SimBase
from .simulated_k2000 import SimFlukeComp
from .transport import TransportError

RANGES = {
    'VOLT:DC': ((0.1, 0.12), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (1000.0, 1010.0)),
    'VOLT:AC': ((0.1, 0.12), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (750.0, 757.5)),
    'CURR:DC': ((1e-4, 1.2e-4), (1e-3, 1.2e-3), (0.01, 0.012), (0.1, 0.12), (1.0, 1.2), (3.0, 3.1)),
    'CURR:AC': ((1e-4, 1.2e-4), (1e-3, 1.2e-3), (0.01, 0.012), (0.1, 0.12), (1.0, 1.2), (3.0, 3.1)),
    'RES': tuple((r, r * 1.2) for r in (1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9)),
    'FRES': tuple((r, r * 1.2) for r in (1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
    'CAP': tuple((r, r * 1.2) for r in (1e-9, 1e-8, 1e-7, 1e-6, 1e-5)),
    'FREQ': ((0.1, 0.12), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (750.0, 757.5)),      # the AC input voltage range of the frequency function
}
DEFAULT_RANGE = {n: r[-1][0] for n, r in RANGES.items()}
OVERFLOW_TEXT = '+9.900000E+37'
SOURCE = {'VOLT:DC': ('V', False), 'VOLT:AC': ('V', True), 'CURR:DC': ('A', False), 'CURR:AC': ('A', True), 'RES': ('OHM', None), 'FRES': ('OHM', None),
          'CAP': ('F', None), 'FREQ': ('V', True)}


def _fresh(node):
    return dict(range=DEFAULT_RANGE[node], auto=True, nplc=1.0, band=20.0, aper=0.1)


class Sim34410ATransport(_SimBase):
    """The simulated 34410A (GPIB, USB or LAN)."""
    idn_text = 'Agilent Technologies,34410A,MY00000001,2.35-2.35-0.09-46-09'

    def __init__(self, bench, bus='GPIB', model='34410A'):
        super().__init__(bench, f'SIM-{model}')
        self.bus = bus
        self.model = model
        if model != '34410A':                                      # the 34411A answers the same SCPI (the verification uses nothing it does not share)
            self.idn_text = self.idn_text.replace('34410A', model)
        self.gain = {n: 1.000002 for n in RANGES}                  # +2 ppm everywhere: inside every limit
        self.gain['FREQ'] = 1.0000005
        self.offset = {n: 0.0 for n in RANGES}
        self.offset['VOLT:DC'] = 4e-7                              # 0.4 uV
        self.offset['FRES'] = self.offset['RES'] = 5e-4            # 0.5 mohm
        self.terminals = 'FRON'
        self.errors = []
        self.sent = []
        self.range_reply = lambda r: r
        self._power_up()

    def _power_up(self):
        self.func = 'VOLT:DC'
        self.cfg = {n: _fresh(n) for n in RANGES}

    # ---- the physics
    def _signal(self, node):
        f = self.bench.fluke
        unit, ac = SOURCE[node]
        if unit == 'F':
            ext = self.bench.external_input
            return None if ext is None else float(ext)
        if not f['operate'] or f.get('unit', 'V') != unit:
            return None
        if node == 'FREQ':
            return float(f['freq']) if f['freq'] else None
        if ac is True and not f['freq']:
            return None
        if ac is False and f['freq']:
            return None
        return float(f['volts'])

    def _reading(self):
        node, c = self.func, self.cfg[self.func]
        value = self._signal(node)
        if node == 'FREQ':
            if value is None:
                return '+0.000000E+00'
            amp = float(self.bench.fluke['volts'])
            if abs(amp) > dict(RANGES[node]).get(c['range'], c['range']):
                return OVERFLOW_TEXT
            return f'{value * self.gain[node]:+.9E}'
        unit = SOURCE[node][0]
        if value is None:
            if unit == 'F':
                return '+0.000000E+00'
            value = 0.0                                              # zero-offset point (short or open input): only the offset
        else:
            value = value * self.gain[node]
        if abs(value) > dict(RANGES[node]).get(c['range'], c['range']):
            return OVERFLOW_TEXT
        return f'{value + self.offset[node]:+.9E}'

    def _select_range(self, node, expected):
        for rng, top in RANGES[node]:
            if abs(expected) <= top:
                return rng
        return RANGES[node][-1][0]

    # ---- command handling
    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        if u == '*IDN?':
            return self.idn_text
        if u == '*RST':
            self._power_up(); return None
        if u == '*CLS':
            self.errors = []; return None
        if u == '*OPC?':
            return '1'
        if u == 'SYST:ERR?':
            return self.errors.pop(0) if self.errors else '+0,"No error"'
        if u == 'ROUT:TERM?':
            return self.terminals
        if u == 'SENS:VOLT:DC:ZERO:AUTO?':
            return '1'
        if u == 'READ?':
            return self._reading()
        if u == 'SENS:FUNC?':
            return f'"{self.func}"'
        if u == 'CONF:FREQ DEF,MIN':
            self.func = 'FREQ'; self.cfg['FREQ'] = _fresh('FREQ'); self.cfg['FREQ']['aper'] = 1.0; return None
        m = re.match(r'^CONF:(VOLT:DC|VOLT:AC|CURR:DC|CURR:AC|FRES|RES|CAP)\s+(\S+)$', u)
        if m:
            node = m.group(1)
            self.func = node
            self.cfg[node] = _fresh(node)                            # CONFigure resets the function's other settings to their defaults
            self.cfg[node]['range'] = self._select_range(node, float(m.group(2))); self.cfg[node]['auto'] = False
            return None
        m = re.match(r'^SENS:(VOLT:DC|VOLT:AC|CURR:DC|CURR:AC|FRES|RES|CAP|FREQ:VOLT|FREQ):(.+)$', u)
        if m:
            return self._sense('FREQ' if m.group(1).startswith('FREQ') else m.group(1), m.group(1), m.group(2))
        raise TransportError(f'simulated 34410A: unknown command {cmd!r}')

    def _sense(self, node, head_node, rest):
        c = self.cfg[node]
        head, _, arg = rest.partition(' ')
        ac = node.endswith(':AC')
        if node == 'FREQ':
            if head_node == 'FREQ:VOLT':
                if head == 'RANG':
                    c['range'] = self._select_range('FREQ', float(arg)); return None
                if head == 'RANG?':
                    return f'{self.range_reply(c["range"]):+.6E}'
            else:
                if head == 'APER':
                    c['aper'] = float(arg); return None
                if head == 'APER?':
                    return f'{c["aper"]:+.6E}'
            raise TransportError(f'simulated 34410A: unknown command {rest!r} for FREQ')
        if head == 'RANG':
            c['range'] = self._select_range(node, float(arg)); c['auto'] = False; return None
        if head == 'RANG?':
            return f'{self.range_reply(c["range"]):+.6E}'
        if head == 'RANG:AUTO?':
            return '1' if c['auto'] else '0'
        if head == 'NPLC' and node in ('VOLT:DC', 'CURR:DC', 'RES', 'FRES'):
            c['nplc'] = float(arg); return None
        if head == 'NPLC?' and node in ('VOLT:DC', 'CURR:DC', 'RES', 'FRES'):
            return f'{c["nplc"]:+.6E}'
        if head == 'BAND' and ac:
            c['band'] = float(arg); return None
        if head == 'BAND?' and ac:
            return f'{c["band"]:+.6E}'
        raise TransportError(f'simulated 34410A: unknown command {rest!r} for {node}')

    def query(self, text):
        self.write(text)
        return self.read()


def make_34410a_bench(cal='5522A', bus='GPIB', model='34410A'):
    """(bench, calibrator transport, 34410A / 34411A transport)."""
    bench = SimBench()
    bench.freq_aware = True
    return bench, SimFlukeComp(bench, cal), Sim34410ATransport(bench, bus, model)
