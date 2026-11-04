"""Golden-transcript cases for the Fluke 5700A driver (drivers/fluke_5700a.py).  Not a test module.

THE REPLIES ARE NOT RECORDED FROM A REAL 5700A: drivers/simulated_5700a.py is hand-written from the Series II Remote Programming Reference Guide (the lab unit is an original 5700A).
Replace with a replay when a bench session has recorded real replies."""
from __future__ import annotations

from drivers.fluke_5700a import Fluke5700A
from drivers.simulated_5700a import make_5700a_bench

COVERAGE = {
    'Fluke5700A': dict(
        covered=['open', 'isr', 'standby', 'operate', 'is_operating', 'cleanup', 'wait_settled', 'set_output_volts', 'set_output_amps', 'set_output_ohms', 'set_compensation',
                 'read_error', 'check_error', 'clear_status', 'operate_unverified', 'standby_quiet', 'reset_to_defaults', 'amplifier_on', 'amplifier_lock', 'amplifier_confirm', 'amplifier_off'],
        no_command=['bus', 'unverified_summary']),
}


def driver_cases(c):
    for bus in ('GPIB', 'RS232'):
        bench, ct = make_5700a_bench(bus)
        d = c.inst(Fluke5700A, ct, opened=False, label='5700A')
        c.run(f'Fluke5700A.open[{bus}]', d.open)
        c.run(f'Fluke5700A.cleanup[{bus}]', d.cleanup)
    bench, ct = make_5700a_bench('GPIB')
    d = c.inst(Fluke5700A, ct, opened=False, label='5700A')
    c.quiet(d.open)
    c.run('Fluke5700A.reset_to_defaults', d.reset_to_defaults)
    c.run('Fluke5700A.clear_status', d.clear_status)
    c.run('Fluke5700A.set_output_volts[dc]', d.set_output_volts, 10.0, None, True)
    c.run('Fluke5700A.set_output_volts[ac]', d.set_output_volts, 1.0, 1000.0)
    c.run('Fluke5700A.set_output_amps[dc]', d.set_output_amps, 0.001, None, True)
    c.run('Fluke5700A.set_output_amps[ac]', d.set_output_amps, 1.0, 4900.0)
    c.run('Fluke5700A.set_output_ohms', d.set_output_ohms, 100000.0)
    c.run('Fluke5700A.set_compensation[WIRE4]', d.set_compensation, 'WIRE4')
    c.run('Fluke5700A.set_compensation[NONE]', d.set_compensation, 'NONE')
    c.run('Fluke5700A.check_error[ok]', d.check_error, 'ctx')
    c.run('Fluke5700A.operate', d.operate)
    c.run('Fluke5700A.isr', d.isr, 0)
    c.run('Fluke5700A.is_operating', d.is_operating)
    c.run('Fluke5700A.wait_settled', d.wait_settled, 5.0, 0.0)
    c.run('Fluke5700A.standby', d.standby)
    c.run('Fluke5700A.operate_unverified', d.operate_unverified)
    c.run('Fluke5700A.standby_quiet', d.standby_quiet)
    c.run('Fluke5700A.amplifier_on[V]', d.amplifier_on, 'V')
    c.run('Fluke5700A.set_output_volts[amplifier]', d.set_output_volts, 740.0, 100000.0)
    c.run('Fluke5700A.amplifier_lock[V]', d.amplifier_lock)
    c.run('Fluke5700A.amplifier_confirm[V]', d.amplifier_confirm)
    c.run('Fluke5700A.amplifier_off[V]', d.amplifier_off)
    c.run('Fluke5700A.amplifier_on[I]', d.amplifier_on, 'I')
    c.run('Fluke5700A.set_output_amps[amplifier]', d.set_output_amps, 10.0, None, True)
    c.run('Fluke5700A.amplifier_lock[I]', d.amplifier_lock)
    c.run('Fluke5700A.amplifier_confirm[I]', d.amplifier_confirm)
    c.run('Fluke5700A.amplifier_off[I]', d.amplifier_off)
    c.run('Fluke5700A.set_output_amps[no amplifier, over range]', d.set_output_amps, 10.0, None, True)
    ct.faults.clear()
    ct.amp_connected = False
    c.run('Fluke5700A.amplifier_on[not connected]', d.amplifier_on, 'I')
    c.quiet(d.set_output_amps, 10.0, None, True)
    c.run('Fluke5700A.amplifier_confirm[not connected]', d.amplifier_confirm)
    ct.amp_connected = True
    d.operate()
    c.run('Fluke5700A.amplifier_on[output operating]', d.amplifier_on, 'V')
    d.standby()
    ct.refuse = 'OUT 1E+30'
    c.run('Fluke5700A.set_output_volts[out of range]', d.set_output_volts, 1e30, None, True)
    c.run('Fluke5700A.read_error[fault]', d.read_error)
    ct.faults.append(540)
    c.run('Fluke5700A.check_error[fault]', d.check_error, 'configuring')
    ct.refuse = None
    c.run('Fluke5700A.read_error[none]', d.read_error)
