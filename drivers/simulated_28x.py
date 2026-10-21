"""A simulated Fluke 287 / 289 on the IR cable (ID, QM, QDDA with the two-line CMD_ACK protocol of the remote interface spec).

The test sets bench.meter to what the technician has selected (function, range, modes) and a value function returning the true input
in base units; the simulator adds REL, a small error, optional settling drift and overload, and answers like the meter.
"""
from __future__ import annotations

import itertools

from .simulated import SimBench, _SimBase
from .transport import TransportError


class SimFluke28x(_SimBase):
    def __init__(self, bench: SimBench, model='289'):
        super().__init__(bench, f'SIM-FLUKE{model}')
        self.model = model
        self._lines = []
        self.clock = itertools.count()
        bench.meter = dict(primary='V_DC', secondary='NONE', auto='MANUAL', range_unit='VDC', range=(5, 0), modes=[],
                           readings=[('PRIMARY', 'VDC', 0, 4)], value=lambda: 0.0, rel_ref=0.0, offset=None, drift=[], silent=False,
                           gain=1.00003)

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        if self.bench.meter.get('silent'):
            self._lines = []
            return
        self._lines = self.handle(text.strip())

    def read(self):
        if not self._lines:
            raise TransportError('simulated IR read timed out')
        return self._lines.pop(0)

    def _value(self):
        m = self.bench.meter
        v = m['value']() * m['gain']
        if m['drift']:
            v += m['drift'].pop(0)
        if any(x in ('REL', 'REL_PERCENT') for x in m['modes']):
            v -= m['rel_ref']
        return v

    def press_rel(self):
        """What pressing REL does: take the present reading as the reference."""
        m = self.bench.meter
        if 'REL' in m['modes']:
            m['modes'].remove('REL')
        else:
            m['rel_ref'] = m['value']() * m['gain']
            m['modes'].append('REL')

    def handle(self, cmd):
        m, u = self.bench.meter, cmd.upper()
        if u == 'ID':
            return ['0', f'FLUKE {self.model},V1.10,95081087']
        if u not in ('QM', 'QDDA'):
            return ['1']
        stamp = 1792540000.0 + next(self.clock)
        rows = []
        v = self._value()
        for rid, unit, mult, dec in m['readings']:
            value = v if rid in ('PRIMARY', 'LIVE') or rid == m.get('main', 'PRIMARY') else m.get('secondary_value', 0.0)
            if rid == m.get('main', 'PRIMARY'):
                value = v
            limit = m['range'][0] * 10 ** m['range'][1] * 1.1
            state = 'NORMAL'
            if unit in ('VDC', 'VAC', 'ADC', 'AAC', 'OHM', 'F') and abs(value) > limit:
                value, state = 9.99999999e37, 'OL'
            rows.append((rid, value, unit, mult, dec, state))
        if m.get('offset') is not None:
            rows.append(('TEMP_OFFSET', m['offset'], 'CEL', 0, 1, 'NORMAL'))
        if u == 'QM':
            rid, value, unit, mult, dec, state = next(r for r in rows if r[0] == 'PRIMARY')
            return ['0', f'{value:.6E},{unit},{state},NONE']
        f = [m['primary'], m['secondary'], m['auto'], m['range_unit'], str(m['range'][0]), str(m['range'][1]), 'OFF', '0.000',
             str(len(m['modes']))] + list(m['modes']) + [str(len(rows))]
        for rid, value, unit, mult, dec, state in rows:
            shown = round(value / 10 ** mult, dec) * 10 ** mult if state == 'NORMAL' else value
            f += [rid, f'{shown:.9g}', unit, str(mult), str(dec), '5', state, 'NONE', f'{stamp:.3f}']
        return ['0', ','.join(f)]
