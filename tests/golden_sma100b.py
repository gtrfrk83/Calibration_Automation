"""Golden-transcript cases for the R&S SMA100B driver (drivers/rs_sma100b.py).  Not a test module.

Kept out of tests/golden_capture.py like tests/golden_8591a.py (it only registers COVERAGE and driver_cases).  The simulator is drivers/simulated_sma100b.py; its replies
are hand-written from the manual, NOT recorded on a real generator.  Nothing here is calibration data.
"""
from __future__ import annotations

from drivers.rs_sma100b import RSSMA100B
from drivers.simulated_sma100b import SimSMA100BTransport

COVERAGE = {
    'RSSMA100B': dict(
        covered=['connect', 'cleanup', 'identify', 'read_fixed_state', 'check_errors', 'output', 'is_output_on', 'cw_setup', 'confirm_no_offsets', 'reference_source',
                 'set_reference', 'level_limit', 'set_frequency', 'set_level', 'wait_done', 'setup', 'read_setting', 'self_test', 'reset_to_defaults'],
        no_command=['address', 'set_address']),
}


def driver_cases(c):
    t = SimSMA100BTransport(level_limit=10.0, max_hz=6e9)
    g = c.inst(RSSMA100B, t, opened=False, label='SMA100B')
    c.run('RSSMA100B.connect', g.connect)
    c.run('RSSMA100B.identify', g.identify)
    c.run('RSSMA100B.read_fixed_state', g.read_fixed_state)
    c.run('RSSMA100B.check_errors', g.check_errors, 'ctx')
    c.run('RSSMA100B.cw_setup', g.cw_setup)
    c.run('RSSMA100B.confirm_no_offsets', g.confirm_no_offsets)
    c.run('RSSMA100B.reference_source', g.reference_source)
    c.run('RSSMA100B.set_reference[EXT]', g.set_reference, 'EXT')
    c.run('RSSMA100B.set_reference[INT]', g.set_reference, 'INT')
    c.run('RSSMA100B.level_limit', g.level_limit)
    c.run('RSSMA100B.set_frequency', g.set_frequency, 1.5e9)
    c.run('RSSMA100B.set_frequency[above range]', g.set_frequency, 7e9)
    c.run('RSSMA100B.set_level', g.set_level, -20.0)
    c.run('RSSMA100B.set_level[above the limit]', g.set_level, 12.0)
    c.run('RSSMA100B.wait_done', g.wait_done)
    c.run('RSSMA100B.setup', g.setup, 100e6, 0.0)
    c.run('RSSMA100B.output[on]', g.output, True)
    c.run('RSSMA100B.is_output_on', g.is_output_on)
    c.run('RSSMA100B.read_setting', g.read_setting)
    c.run('RSSMA100B.output[off]', g.output, False)
    c.run('RSSMA100B.self_test', g.self_test)
    c.quiet(setattr, t, 'pow_offs', 2.0)
    c.run('RSSMA100B.confirm_no_offsets[level offset left on]', g.confirm_no_offsets)
    c.run('RSSMA100B.reset_to_defaults', g.reset_to_defaults)
    c.run('RSSMA100B.cleanup', g.cleanup)
