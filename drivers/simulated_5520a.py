"""A simulated Fluke 5520A that refuses the outputs the 5520A does not publish.

The refusal is decided by calibrator_fit.check('5520A', ...) over the 5520A specification sheet the suite holds (specs/standards/fluke_5520a_standard.json),
the same rows the calibrator pickers use to decide whether the model is offered.  A refused OUT is an entry in the error queue (ERR?) and the output is not
changed, like the rejected command the real calibrator reports.  So a simulated run of a procedure with the 5520A selected must never see a refusal for a
point the picker offered.

The simulator accepts any command text the other simulated calibrators accept: it cannot say whether a real 5520A takes them (see Fluke5520A.COMMANDS).
"""
from __future__ import annotations

import re

import calibrator_fit

from .simulated import SimFlukeTransport

_OUT = re.compile(r'OUT\s+([-+0-9.eE]+)\s*(V|A|OHM|F|NF|UF|CEL)(?:\s*,\s*([0-9.eE+-]+)\s*(HZ|KHZ|MHZ))?$')
_SCALE = {'HZ': 1.0, 'KHZ': 1e3, 'MHZ': 1e6}


def request_of(cmd, previous_hz=0.0):
    """calibrator_fit.Req of an `OUT ...` command line (None for anything else, and for the scope / square-wave forms)."""
    m = _OUT.match(cmd.strip().upper())
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    hz = float(m.group(3)) * _SCALE[m.group(4)] if m.group(3) else previous_hz
    if unit == 'V':
        return calibrator_fit.Req('ACV' if hz else 'DCV', value, hz or None)
    if unit == 'A':
        return calibrator_fit.Req('ACI' if hz else 'DCI', value, hz or None)
    if unit == 'OHM':
        return calibrator_fit.Req('OHM', value)
    if unit == 'CEL':
        return calibrator_fit.Req('TEMP', value)
    scale = {'F': 1.0, 'NF': 1e-9, 'UF': 1e-6}[unit]
    return calibrator_fit.Req('CAP', value * scale)


class Sim5520ALimitsTransport(SimFlukeTransport):
    def __init__(self, bench, model='5520A'):
        super().__init__(bench, model)
        self.refused = []                                      # [(command, reason)] for the tests

    def _handle(self, cmd):
        f = self.bench.fluke
        req = request_of(cmd, previous_hz=f.get('freq', 0.0) if f.get('unit') in ('V', 'A') else 0.0)
        if req is not None:
            verdict = calibrator_fit.check('5520A', req)
            if not verdict.ok:
                self.errors = getattr(self, 'errors', []) + ['-222,"Data out of range"']
                self.refused.append((cmd, verdict.reason))
                return None
        return super()._handle(cmd)
