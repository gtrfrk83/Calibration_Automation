"""Golden-transcript cases for the Keysight 53210A / 53220A / 53230A driver (drivers/keysight_53220a.py).  Not a test module.

Kept out of tests/golden_capture.py (it only registers COVERAGE and driver_cases, a few additive lines), like tests/golden_tbs2000b.py.  `driver_cases(c)` is
DRIVER_CASES['keysight_53220a'] (cases and resets).  The simulated counter is drivers/simulated_53220a.py.
"""
from __future__ import annotations

from drivers.keysight_53220a import AgilentAFGPulse, Keysight53210A, Keysight53220A, Keysight53230A
from drivers.simulated_fgen import make_fgen_bench
from drivers.simulated_53220a import make_53220a_bench

COVERAGE = {
    'Keysight53220A': dict(
        covered=['connect', 'read_options', 'local', 'cleanup', 'check_errors', 'read_reference', 'set_reference', 'restore_reference', 'configure_inputs',
                 'configure_point', 'measure_stats', 'self_test', 'reset_to_defaults'],
        no_command=['bus']),                                                # property: derives from the transport
    'Keysight53230A': dict(covered=['connect', 'configure_point'], no_command=[]),         # inherited methods, exercised on the subclass (the burst function is the 53230A's)
    'Keysight53210A': dict(covered=['connect', 'configure_point'], no_command=[]),         # inherited methods on the unverified command set; the microwave input is Channel 2
    'AgilentAFGPulse': dict(covered=['connect', 'pulse', 'output', 'cleanup', 'check_errors', 'reset_to_defaults'], no_command=[]),      # the 33250A as the pulse generator (User's Guide pp. 153-168)
    'Fluke96270AWide': dict(covered=[], no_command=[]),                                    # only MAX_HZ differs from Fluke96270A (its own fixture covers the commands)
}


def driver_cases(c):
    from tests.golden_capture import Scripted
    for bus in ('USB', 'GPIB'):
        bench, rf, ct = make_53220a_bench('53220A', bus)
        d = c.inst(Keysight53220A, ct, opened=False, label='53220A')
        c.run(f'Keysight53220A.connect[{bus}]', d.connect)
        c.run(f'Keysight53220A.read_options[{bus}]', d.read_options)
        c.run(f'Keysight53220A.local[{bus}]', d.local)
        c.run(f'Keysight53220A.cleanup[{bus}]', d.cleanup)
    bench, rf, ct = make_53220a_bench('53220A', 'USB')
    d = c.inst(Keysight53220A, ct, opened=False, label='53220A')
    c.quiet(d.connect)
    c.run('Keysight53220A.reset_to_defaults', d.reset_to_defaults)
    c.run('Keysight53220A.read_reference', d.read_reference)
    c.run('Keysight53220A.set_reference[EXT]', d.set_reference, 'EXT')
    c.run('Keysight53220A.set_reference[EXT unchanged]', d.set_reference, 'EXT')
    c.run('Keysight53220A.set_reference[INT]', d.set_reference, 'INT')
    bench.ext_ref_present = False
    c.run('Keysight53220A.set_reference[no 10 MHz]', d.set_reference, 'EXT')
    bench.ext_ref_present = True
    c.quiet(ct.errors.clear)
    c.run('Keysight53220A.restore_reference', d.restore_reference)
    c.run('Keysight53220A.configure_inputs[1 and 2]', d.configure_inputs, [1, 2])
    pts = [('FREQ ch1', dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01)), ('FREQ ch3 microwave', dict(func='FREQ', channel=3, nominal=5.88e9, gate_s=0.01)),
           ('FREQ default gate', dict(func='FREQ', channel=1, nominal=10e6, gate_s=None)), ('SPER', dict(func='SPER', channel=2, nominal=1e-6)),
           ('PWID', dict(func='PWID', channel=1, nominal=5e-9)), ('TINT', dict(func='TINT', channel=12, nominal=49.9e-9))]
    for tag, p in pts:
        c.run(f'Keysight53220A.configure_point[{tag}]', d.configure_point, p)
    c.run('Keysight53220A.configure_point[unknown function]', d.configure_point, dict(func='TEMP', channel=1))
    c.run('Keysight53220A.check_errors[ok]', d.check_errors, 'ctx')
    ct.errors.extend(['-221,"Settings conflict"', '-113,"Undefined header"'])
    c.run('Keysight53220A.check_errors[two errors]', d.check_errors, 'configuring')
    c.quiet(d.configure_point, dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01))
    c.run('Keysight53220A.measure_stats[no signal]', d.measure_stats)
    bench.rf1.update(f=10e6, p=7.0, on=True)
    c.quiet(d.configure_point, dict(func='FREQ', channel=1, nominal=10e6, gate_s=0.01))
    c.run('Keysight53220A.measure_stats[10 MHz]', d.measure_stats)
    c.run('Keysight53220A.measure_stats[50 readings]', d.measure_stats, 50)
    c.run('Keysight53220A.self_test[pass]', d.self_test)
    ct.selftest_fail = True
    c.run('Keysight53220A.self_test[fail]', d.self_test)
    wrong = c.inst(Keysight53220A, Scripted([(r'\*IDN\?', 'Agilent Technologies,53230A,MY1,3.00')]), opened=False, label='53220A')
    c.run('Keysight53220A.connect[wrong model]', wrong.connect)

    bench, rf, ct = make_53220a_bench('53230A', 'USB')
    b = c.inst(Keysight53230A, ct, opened=False, label='53230A')
    c.run('Keysight53230A.connect', b.connect)
    c.run('Keysight53230A.configure_point[BURST narrow]', b.configure_point, dict(func='BURST', channel=3, nominal=6e9, narrow=True, burst_db=-12))
    c.run('Keysight53230A.configure_point[BURST wide]', b.configure_point, dict(func='BURST', channel=3, nominal=6e9, narrow=False, burst_db=-6))

    bench, rf, ct = make_53220a_bench('53210A', 'USB')
    m = c.inst(Keysight53210A, ct, opened=False, label='53210A')
    c.run('Keysight53210A.connect', m.connect)
    c.run('Keysight53210A.configure_point[FREQ microwave Channel 2]', m.configure_point, dict(func='FREQ', channel=3, nominal=5.88e9, gate_s=0.01))

    gbench, gt = make_fgen_bench('33250A')                                                      # the 33250A as a pulse generator, on the simulated twin
    g = c.inst(AgilentAFGPulse, gt['uut'], opened=False, label='33250A')
    c.run('AgilentAFGPulse.connect', g.connect)
    c.run('AgilentAFGPulse.pulse[66.6 ns period, 20 ns wide]', g.pulse, 66.6e-9, 20e-9, 5e-9, 1.0)
    c.run('AgilentAFGPulse.pulse[8 ns minimum width]', g.pulse, 66.6e-9, 8e-9)
    c.run('AgilentAFGPulse.pulse[back to a long period]', g.pulse, 1e-3, 100e-6, 5e-9, 1.0)
    c.run('AgilentAFGPulse.pulse[5 ns refused]', g.pulse, 66.6e-9, 5e-9)
    c.run('AgilentAFGPulse.pulse[High Z]', g.pulse, 1e-6, 200e-9, 5e-9, 2.0, 'INF')
    gbench.gen['errors'].append('-221,"Settings conflict; pulse width decreased due to period"')
    c.run('AgilentAFGPulse.check_errors[error queued]', g.check_errors, 'pulse')
    c.run('AgilentAFGPulse.check_errors[empty]', g.check_errors, 'pulse')
    c.run('AgilentAFGPulse.output[on]', g.output, True)
    c.run('AgilentAFGPulse.output[off]', g.output, False)
    gbench.gen['stuck_on'] = True
    c.run('AgilentAFGPulse.output[off not confirmed]', g.output, True)
    c.run('AgilentAFGPulse.output[off not confirmed 2]', g.output, False)
    c.run('AgilentAFGPulse.cleanup[stuck on]', g.cleanup)
    gbench.gen['stuck_on'] = False
    c.run('AgilentAFGPulse.cleanup', g.cleanup)
    c.run('AgilentAFGPulse.reset_to_defaults', g.reset_to_defaults)
