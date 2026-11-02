"""Golden-transcript cases for the HP 8591A driver and the added Fluke 96270A AM method (setup_am).  Not a test module.

Kept out of tests/golden_capture.py like tests/golden_6060a.py (it only registers COVERAGE and driver_cases).  The simulator is drivers/simulated_8591a.py (analyzer and 96270A on one SimBench).
The setup_am cases live in this fixture but are listed under COVERAGE['reference_instruments']['Fluke96270A'] (golden_capture adds them there).  Nothing here is calibration data.
"""
from __future__ import annotations

from drivers.hp_8591a import HP8591A
from drivers.reference_instruments import Fluke96270A
from drivers.simulated_8591a import make_8591a_bench, source_state

COVERAGE = {
    'HP8591A': dict(
        covered=['connect', 'cleanup', 'identify', 'read_status', 'check_errors', 'preset', 'set_units', 'set_center_hz', 'set_span_hz', 'set_rbw_hz', 'set_vbw_hz', 'set_reference_level_dbm',
                 'set_attenuation_db', 'set_sweep_time_s', 'set_detector', 'set_scale', 'single_sweep', 'sweep_time_s', 'take_sweep', 'marker_to_peak', 'delta_at', 'read_trace',
                 'reset_to_defaults'],
        no_command=['write', 'send', 'address', 'set_address']),
}
AM_COVERED = ['setup_am']                     # added to COVERAGE['reference_instruments']['Fluke96270A']['covered'] by golden_capture


def cases_8591a(c):
    bench, t_sa, t_src = make_8591a_bench()
    src = Fluke96270A(t_src).connect()
    src.set_rf(250e6, -10.0)
    src.output(True)
    sa = c.inst(HP8591A, t_sa, opened=False, label='8591A')
    c.run('HP8591A.connect', sa.connect)
    c.run('HP8591A.identify', sa.identify)
    c.run('HP8591A.read_status', sa.read_status)
    c.run('HP8591A.check_errors', sa.check_errors, 'ctx')
    c.run('HP8591A.preset', sa.preset)
    c.run('HP8591A.set_units[dBm]', sa.set_units, 'DBM')
    c.run('HP8591A.set_center_hz', sa.set_center_hz, 250e6)
    c.run('HP8591A.set_center_hz[above range]', sa.set_center_hz, 3e9)
    c.run('HP8591A.set_span_hz', sa.set_span_hz, 1e6)
    c.run('HP8591A.set_rbw_hz', sa.set_rbw_hz, 30e3)
    c.run('HP8591A.set_vbw_hz', sa.set_vbw_hz, 30e3)
    c.run('HP8591A.set_reference_level_dbm', sa.set_reference_level_dbm, 0.0)
    c.run('HP8591A.set_reference_level_dbm[out of range]', sa.set_reference_level_dbm, 90.0)
    c.run('HP8591A.set_attenuation_db', sa.set_attenuation_db, 20)
    c.run('HP8591A.set_attenuation_db[out of range]', sa.set_attenuation_db, 90)
    c.run('HP8591A.set_sweep_time_s', sa.set_sweep_time_s, 0.1)
    c.run('HP8591A.set_detector', sa.set_detector, 'POS')
    c.run('HP8591A.set_scale[log 1 dB]', sa.set_scale, 1)
    c.run('HP8591A.set_scale[bad log scale]', sa.set_scale, 3)
    c.run('HP8591A.single_sweep', sa.single_sweep)
    c.run('HP8591A.sweep_time_s', sa.sweep_time_s)
    c.run('HP8591A.take_sweep', sa.take_sweep)
    c.run('HP8591A.marker_to_peak', sa.marker_to_peak)
    c.run('HP8591A.delta_at', sa.delta_at, 250.01e6)
    c.run('HP8591A.read_trace', sa.read_trace)
    c.run('HP8591A.set_units[V]', sa.set_units, 'V')
    c.run('HP8591A.set_scale[linear]', sa.set_scale, None)
    src.output(False)
    c.run('HP8591A.cleanup', sa.cleanup)
    bench2, t_sa2, _t = make_8591a_bench()
    s2 = c.inst(HP8591A, t_sa2, opened=False, label='8591A')
    c.quiet(s2.connect)
    c.run('HP8591A.reset_to_defaults', s2.reset_to_defaults)


def cases_am(c):
    bench, _t_sa, t_src = make_8591a_bench()
    src = c.inst(Fluke96270A, t_src, opened=False, label='96270A')
    c.quiet(src.connect)
    c.run('Fluke96270A.setup_am', src.setup_am, 500e6, -10.0, 80.0, 10.0, 'TRI')
    c.run('Fluke96270A.setup_am[sine, default shape]', src.setup_am, 500e6, -10.0, 50.0, 1000.0, 'SINE')
    c.run('Fluke96270A.setup_am[rate below the 1 Hz minimum]', src.setup_am, 500e6, -10.0, 80.0, 0.5)
    c.run('Fluke96270A.setup_am[depth above 99 %]', src.setup_am, 500e6, -10.0, 100.0, 10.0)
    c.run('Fluke96270A.setup_am[carrier below 50 kHz]', src.setup_am, 10e3, -10.0, 80.0, 10.0)
    c.run('Fluke96270A.select_sine[after AM]', src.select_sine)
    source_state(bench)


def driver_cases(c):
    cases_8591a(c)
    cases_am(c)
