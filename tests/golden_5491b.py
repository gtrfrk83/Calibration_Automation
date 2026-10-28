"""Golden-transcript cases for the B&K Precision 5491B driver (drivers/bk_5491b.py).  Not a test module.

Kept out of tests/golden_capture.py like tests/golden_53220a.py (it only registers COVERAGE and driver_cases).  The simulated meter is drivers/simulated_5491b.py.
Nothing here is calibration data.
"""
from __future__ import annotations

from drivers.bk_5491b import BK5491B
from drivers.simulated_5491b import make_5491b_bench

COVERAGE = {
    'BK5491B': dict(
        covered=['connect', 'cleanup', 'identify', 'ensure_run_state', 'session_check', 'configure_point', 'read', 'check_errors', 'reset_to_defaults'],
        no_command=['write', 'query',                                    # raw front ends: every case goes through them
                    'send',                                              # generic registry front end
                    'function_of']),                                     # pure lookup
}

POINTS = [('DCV 5 V', dict(kind='DCV', nominal=4.9, range=5.0)), ('ACV 5 V 1 kHz', dict(kind='ACV', nominal=4.9, range=5.0, frequency=1000.0)),
          ('FREQ 1 kHz', dict(kind='FREQ', nominal=1000.0, range=10000.0, amplitude=1.0)), ('OHM2 5 kOhm', dict(kind='OHM2', nominal=4900.0, range=5000.0)),
          ('DCI 5 mA', dict(kind='DCI', nominal=0.0049, range=0.005)), ('ACI 50 mA', dict(kind='ACI', nominal=0.049, range=0.05, frequency=1000.0)),
          ('CONT', dict(kind='OHM2', function='CONT', nominal=490.0, range=500.0))]


def driver_cases(c):
    for echo in (None, 'line'):
        bench, cal_t, mt = make_5491b_bench('5522A')
        mt.echo = echo
        d = c.inst(BK5491B, mt, opened=False, label='5491B')
        c.run(f'BK5491B.connect[echo {echo}]', d.connect)
        c.run(f'BK5491B.identify[echo {echo}]', d.identify)
        c.run(f'BK5491B.cleanup[echo {echo}]', d.cleanup)
    bench, cal_t, mt = make_5491b_bench('5522A')
    d = c.inst(BK5491B, mt, opened=False, label='5491B')
    c.quiet(d.connect)
    c.run('BK5491B.reset_to_defaults', d.reset_to_defaults)
    c.run('BK5491B.ensure_run_state', d.ensure_run_state)
    c.run('BK5491B.session_check', d.session_check)
    for tag, p in POINTS:
        c.run(f'BK5491B.configure_point[{tag}]', d.configure_point, p)
    c.quiet(d.configure_point, POINTS[0][1])
    c.run('BK5491B.read[no signal]', d.read, POINTS[0][1])
    c.run('BK5491B.check_errors[ok]', d.check_errors, 'ctx')
    mt.errors.extend(['BUS:BAD COMMAND.'])
    c.run('BK5491B.check_errors[one error]', d.check_errors, 'configuring')
