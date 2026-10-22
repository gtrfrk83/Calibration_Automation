"""Fluke 5520A / 5522A with the scope option (-SC300 / -SC600): the SCOPE-BNC commands the TDS2000C procedure uses.

What the supplied 5520A Programmers Guide (PN 688744) confirms: SCOPE / SCOPE? (set / read the oscilloscope mode), OUT_IMP / OUT_IMP? (SCOPE BNC
output impedance), TMWAVE (time-marker waveform), OUT / OUT? (OUT? answers: amplitude, unit, second amplitude, second unit, frequency),
OPER / OPER? / STBY, ERR?, *CLS.  It does NOT list the SCOPE mode names or OUT_IMP arguments (they are in the Operators Manual, chapter 8),
so 'SCOPE VOLT', 'SCOPE LEVSINE', 'SCOPE MARKER' and 'OUT_IMP 1M' / '50' are UNVERIFIED here.  Every one is checked through ERR? and read back
with SCOPE? / OUT_IMP?, and the output is never operated after a rejection or an unexpected reply.
"""
from __future__ import annotations

from .base import InstrumentError
from .fluke_5560a import Fluke5522A

SCOPE_VOLT_MODE = 'VOLT'


class Fluke5522AScope(Fluke5522A):
    MODEL = 'Fluke 5520A / 5522A (scope option)'

    def select_scope_dcv(self, source_impedance='1M'):
        """SCOPE VOLT (the 5560A driver's 'SCOPE DCV' is a 5560A word and is not used here), then OUT_IMP, each checked."""
        self.write('SCOPE VOLT')
        self.check_error('SCOPE VOLT')
        mode = self.query('SCOPE?').strip().upper()
        if SCOPE_VOLT_MODE not in mode:
            raise InstrumentError(f'Calibrator SCOPE mode not confirmed: SCOPE?={mode!r} (expected VOLT)')
        self.write(f'OUT_IMP {source_impedance}')
        self.check_error(f'OUT_IMP {source_impedance}')
        reply = self.query('OUT_IMP?').strip().upper()
        want = {'1M': 1e6, '50': 50.0}[source_impedance]
        try:
            value = float(reply.split(',')[0])
        except ValueError:
            raise InstrumentError(f'Unexpected OUT_IMP? reply {reply!r}')
        if abs(value - want) > 0.01 * want:
            raise InstrumentError(f'Unexpected SCOPE output impedance: {reply!r}')
