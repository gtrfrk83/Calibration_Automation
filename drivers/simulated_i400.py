"""Simulated bench for the Fluke i400 procedure: the simulated calibrator (any of the three), the simulated reading multimeter (the 34410A / 34411A simulator) and the clamp.

The clamp is not an instrument the program talks to: the multimeter reads its output.  So the simulator is the multimeter's transport with a path switch that the virtual
operator sets after a hook-up prompt (what the technician does with the cables):

    path 'direct'  the calibrator is connected to the multimeter's current input: it reads what the calibrator outputs (the DMM pre-calibration, Table 3 footnote, p. 6)
    path 'clamp'   the calibrator drives `turns` turns through the clamp jaws: the multimeter reads the clamp's 1 mA/A output, `turns` x the calibrator current x 1 mA/A x gain

    bench, cal_t, dmm_t = make_i400_bench('5522A', 'GPIB')
    dmm_t.path, dmm_t.turns, dmm_t.clamp_gain, dmm_t.clamp_offset_a   (test hooks; the clamp's default gain error is +0.5 %, well inside every limit)
"""
from __future__ import annotations

from .simulated import SimBench
from .simulated_34410a import Sim34410ATransport, SOURCE
from .simulated_k2000 import SimFlukeComp

OUTPUT_PER_AMP = 1e-3                   # the clamp's output: 1 mA per ampere (Electrical Specifications, p. 3)


class SimI400Transport(Sim34410ATransport):
    """The reading multimeter on the simulated bench, with the i400 clamp between the calibrator and its AC current input when `path` is 'clamp'."""

    def __init__(self, bench, bus='GPIB', model='34410A'):
        super().__init__(bench, bus, model)
        self.path = 'direct'
        self.turns = 1
        self.clamp_gain = 1.005
        self.clamp_offset_a = 0.0                  # extra clamp output, amps (a test hook)

    def _signal(self, node):
        value = super()._signal(node)
        if value is None or node != 'CURR:AC' or self.path != 'clamp':
            return value
        return float(value) * self.turns * OUTPUT_PER_AMP * self.clamp_gain + self.clamp_offset_a


def make_i400_bench(cal='5522A', bus='GPIB', model='34410A'):
    """(bench, calibrator transport, reading multimeter transport)."""
    bench = SimBench()
    bench.freq_aware = True
    return bench, SimFlukeComp(bench, cal), SimI400Transport(bench, bus, model)


__all__ = ['SimI400Transport', 'make_i400_bench', 'OUTPUT_PER_AMP', 'SOURCE']
