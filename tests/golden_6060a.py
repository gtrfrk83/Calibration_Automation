"""Golden-transcript cases for the Fluke 6060A, HP 8902A and HP 8563E drivers and the added Fluke 96270A power-meter methods.  Not a test module.

Kept out of tests/golden_capture.py like tests/golden_53220a.py (it only registers COVERAGE and driver_cases).  The simulators are drivers/simulated_6060a.py, simulated_8902a.py,
simulated_8563e.py and simulated_96270a.py, all on one SimBench (the receiver and the analyzer measure what the generator outputs).  The 96270A cases live in this fixture but are
listed under COVERAGE['reference_instruments'] (golden_capture adds them there).  Nothing here is calibration data.
"""
from __future__ import annotations

from drivers.fluke_6060a import Fluke6060A, PRESET_LEARN
from drivers.hp_8563e import HP8563E
from drivers.hp_8902a import HP8902A
from drivers.reference_instruments import Fluke96270A
from drivers.simulated_6060a import make_rf_bench, preset_state, rf_state
from drivers.simulated_96270a import Sim96270AMeter

COVERAGE = {
    'Fluke6060A': dict(
        covered=['connect', 'cleanup', 'identify', 'wait_valid', 'learn', 'read_options', 'rejected_entries', 'check_rejected', 'uncal', 'check_uncal', 'verify', 'set_frequency',
                 'set_level', 'rf', 'end_point', 'am', 'fm', 'mod_off', 'select_section', 'hardware_attenuation', 'set_step', 'step', 'step_frequency', 'step_level',
                 'reset_to_defaults'],
        no_command=['write',                                             # raw front end: every case goes through it
                    'address', 'set_address',                            # the GPIB address of the object (the transport is re-targeted in connect)
                    'compare']),                                         # pure comparison of two dicts
    'HP8902A': dict(
        covered=['connect', 'cleanup', 'identify', 'remote', 'go_local', 'status', 'check_status', 'set_srq_mask', 'measure_frequency_hz', 'read_special', 'time_base_is_external',
                 'tuned_rf_level_dbm', 'calibrate_tuned_level', 'rf_power_dbm', 'zero_power_sensor', 'calibrate_power_sensor', 'enter_reference_cal_factor', 'cal_factor_count',
                 'enter_cal_factor', 'measure_am_percent', 'measure_fm_deviation_hz', 'measure_distortion', 'measure_modulation_rate_hz', 'calibrate_modulation',
                 'reset_to_defaults'],
        no_command=['write', 'send', 'address', 'set_address']),
    'HP8563E': dict(
        covered=['connect', 'cleanup', 'identify', 'read_errors', 'check_errors', 'set_units_dbm', 'set_center_hz', 'set_span_hz', 'set_start_hz', 'set_stop_hz', 'set_rbw_hz',
                 'set_vbw_hz', 'set_reference_level_dbm', 'set_attenuation_db', 'set_detector', 'set_marker_threshold', 'set_marker_excursion', 'single_sweep', 'sweep_time_s',
                 'take_sweep', 'marker_to_peak', 'delta_to_next_peak', 'configure', 'measure_fundamental', 'measure_harmonics', 'scan_spurs', 'reset_to_defaults'],
        no_command=['write', 'send', 'address', 'set_address']),
    'gpib_address': {},
}
COVERAGE.pop('gpib_address')                                             # a helper module with no Instrument class: it only appears in LINT_FILES

PM_COVERED = ['select_power_meter', 'zero', 'read_dbm', 'select_sine']     # added to COVERAGE['reference_instruments']['Fluke96270A']['covered'] by golden_capture


def _source(bench, mhz=250.0, dbm=-10.0, on=True, **extra):
    """Set the simulated 6060A directly (not recorded): what the receiver and the analyzer will see."""
    s = rf_state(bench)
    s.update(frequency_hz=mhz * 1e6, amplitude_dbm=dbm, rf_on=on, **extra)


def cases_6060a(c):
    from tests.golden_capture import Scripted
    from drivers.fluke_6060a import encode_learn
    bench, t6, t8902, t8563 = make_rf_bench()
    g = c.inst(Fluke6060A, t6, opened=False, label='6060A')
    c.run('Fluke6060A.connect', g.connect)
    c.run('Fluke6060A.identify', g.identify)
    c.run('Fluke6060A.read_options', g.read_options)
    c.run('Fluke6060A.learn', g.learn)
    c.run('Fluke6060A.wait_valid', g.wait_valid)
    c.run('Fluke6060A.rejected_entries', g.rejected_entries)
    c.run('Fluke6060A.check_rejected', g.check_rejected, 'ctx')
    c.run('Fluke6060A.uncal', g.uncal)
    c.run('Fluke6060A.check_uncal', g.check_uncal, 'ctx')
    c.run('Fluke6060A.verify[ok]', g.verify, rf_on=False)
    c.run('Fluke6060A.verify[mismatch]', g.verify, rf_on=True)
    c.run('Fluke6060A.set_frequency', g.set_frequency, 111.1111)
    c.run('Fluke6060A.set_frequency[above range]', g.set_frequency, 1200.0)
    c.run('Fluke6060A.set_level', g.set_level, -10.0)
    c.run('Fluke6060A.set_level[above range]', g.set_level, 14.0)
    c.run('Fluke6060A.set_level[uncal allowed]', g.set_level, 15.0, allow_uncal=True)
    c.quiet(g.set_level, 0.0)
    c.run('Fluke6060A.rf[on]', g.rf, 'on')
    c.run('Fluke6060A.rf[off]', g.rf, False)
    c.run('Fluke6060A.rf[bad text]', g.rf, 'maybe')
    c.run('Fluke6060A.end_point', g.end_point)
    c.run('Fluke6060A.am[internal]', g.am, 30, 'int', 400)
    c.run('Fluke6060A.am[external]', g.am, 70, 'ext')
    c.run('Fluke6060A.am[external, no input applied]', g.am, 30, 'ext', input_applied=False)
    c.run('Fluke6060A.am[above 90 percent]', g.am, 95, 'int')
    c.run('Fluke6060A.am[bad rate]', g.am, 30, 'int', 500)
    c.quiet(g.mod_off)                                                   # the refused 95 percent depth stayed set in the unit: clear it so the FM cases below are about FM
    c.run('Fluke6060A.fm[internal]', g.fm, 5.0, 'int', 1000)
    c.run('Fluke6060A.fm[external]', g.fm, 99.9, 'ext')
    c.run('Fluke6060A.fm[above range]', g.fm, 120.0, 'ext')
    c.run('Fluke6060A.mod_off', g.mod_off)
    c.run('Fluke6060A.select_section[3]', g.select_section, 3)
    c.run('Fluke6060A.select_section[5]', g.select_section, 5)
    c.run('Fluke6060A.select_section[5, RF on]', g.select_section, 6, rf_on=True)
    c.run('Fluke6060A.select_section[bad]', g.select_section, 9)
    c.run('Fluke6060A.hardware_attenuation', g.hardware_attenuation)
    c.run('Fluke6060A.set_step[freq]', g.set_step, 'freq', 1.5)
    c.run('Fluke6060A.set_step[level]', g.set_step, 'level', 2.0)
    c.run('Fluke6060A.step[freq up]', g.step, 'freq', 2)
    c.run('Fluke6060A.step[level down]', g.step, 'level', -1)
    c.run('Fluke6060A.step[zero count]', g.step, 'freq', 0)
    c.run('Fluke6060A.step_frequency', g.step_frequency, -1)
    c.run('Fluke6060A.step_level', g.step_level, 1)
    c.run('Fluke6060A.cleanup', g.cleanup)
    # a generator that does not confirm RF OFF: a SafetyError, never a retry
    on = c.inst(Fluke6060A, Scripted([(r'^LM99', encode_learn(preset_state())), (r'^ID', 'FLUKE 6060A')]), label='6060A')
    c.run('Fluke6060A.rf[off not confirmed]', on.rf, False)
    c.run('Fluke6060A.end_point[off not confirmed]', on.end_point)
    c.run('Fluke6060A.cleanup[off not confirmed]', on.cleanup)
    bench2, t62, _a, _b = make_rf_bench()
    g2 = c.inst(Fluke6060A, t62, opened=False, label='6060A')
    c.quiet(g2.connect)
    c.run('Fluke6060A.reset_to_defaults', g2.reset_to_defaults)
    bad = c.inst(Fluke6060A, Scripted([(r'^ID', 'FLUKE 9999')]), opened=False, label='6060A')
    c.run('Fluke6060A.connect[wrong model]', bad.connect)


def cases_8902a(c):
    bench, t6, t8902, t8563 = make_rf_bench()
    gen = Fluke6060A(t6).connect()
    rx = c.inst(HP8902A, t8902, opened=False, label='8902A')
    c.run('HP8902A.connect', rx.connect)
    c.run('HP8902A.identify', rx.identify)
    c.run('HP8902A.remote', rx.remote)
    c.run('HP8902A.status', rx.status)
    c.run('HP8902A.check_status', rx.check_status, 'ctx')
    c.run('HP8902A.set_srq_mask', rx.set_srq_mask, 2)
    c.run('HP8902A.measure_frequency_hz[no signal]', rx.measure_frequency_hz, 250.0)
    gen.set_frequency(250.0)
    gen.set_level(-5.0)
    gen.rf(True)
    c.run('HP8902A.measure_frequency_hz', rx.measure_frequency_hz, 250.0)
    c.run('HP8902A.measure_frequency_hz[100 Hz resolution]', rx.measure_frequency_hz, 250.0, 100)
    c.run('HP8902A.measure_frequency_hz[bad resolution]', rx.measure_frequency_hz, 250.0, 7)
    c.run('HP8902A.time_base_is_external[internal]', rx.time_base_is_external)
    t8902.external_ref = True
    c.run('HP8902A.time_base_is_external[external]', rx.time_base_is_external)
    c.run('HP8902A.read_special', rx.read_special, '42.0')
    c.run('HP8902A.tuned_rf_level_dbm[recal required]', rx.tuned_rf_level_dbm, 250.0)
    c.run('HP8902A.calibrate_tuned_level', rx.calibrate_tuned_level, 250.0)
    c.run('HP8902A.tuned_rf_level_dbm', rx.tuned_rf_level_dbm, 250.0)
    c.run('HP8902A.tuned_rf_level_dbm[bad detector]', rx.tuned_rf_level_dbm, 250.0, 'peak')
    gen.rf(False)
    c.run('HP8902A.zero_power_sensor', rx.zero_power_sensor)
    t8902.sensor_on_calibrator = True
    c.run('HP8902A.calibrate_power_sensor', rx.calibrate_power_sensor)
    t8902.sensor_on_calibrator = False
    c.run('HP8902A.calibrate_power_sensor[sensor not on the calibrator]', rx.calibrate_power_sensor)
    gen.rf(True)
    c.run('HP8902A.rf_power_dbm', rx.rf_power_dbm, 250.0)
    c.run('HP8902A.enter_reference_cal_factor', rx.enter_reference_cal_factor, 98.5)
    c.run('HP8902A.cal_factor_count', rx.cal_factor_count)
    c.run('HP8902A.enter_cal_factor', rx.enter_cal_factor, 250.0, 98.0)
    gen.rf(False)
    gen.set_level(0.0)
    gen.am(30, 'int', 1000)
    gen.rf(True)
    c.run('HP8902A.measure_am_percent', rx.measure_am_percent, 250.0)
    c.run('HP8902A.measure_am_percent[detector 9]', rx.measure_am_percent, 250.0, 9, 1, 2)
    c.run('HP8902A.measure_am_percent[bad detector]', rx.measure_am_percent, 250.0, 12)
    c.run('HP8902A.measure_distortion[1 kHz]', rx.measure_distortion, 250.0, 1000, 'am')
    c.run('HP8902A.measure_distortion[10 kHz refused]', rx.measure_distortion, 250.0, 10000, 'am')
    c.run('HP8902A.measure_modulation_rate_hz', rx.measure_modulation_rate_hz, 250.0, 'am')
    c.run('HP8902A.calibrate_modulation[am]', rx.calibrate_modulation, 'am')
    gen.rf(False)
    gen.mod_off()
    gen.fm(5.0, 'int', 1000)
    gen.rf(True)
    c.run('HP8902A.measure_fm_deviation_hz', rx.measure_fm_deviation_hz, 250.0)
    c.run('HP8902A.measure_fm_deviation_hz[75 us de-emphasis]', rx.measure_fm_deviation_hz, 250.0, 1, 1, 2, 75)
    c.run('HP8902A.calibrate_modulation[fm]', rx.calibrate_modulation, 'fm')
    c.run('HP8902A.calibrate_modulation[bad kind]', rx.calibrate_modulation, 'pm')
    gen.rf(False)
    c.run('HP8902A.go_local', rx.go_local)
    c.run('HP8902A.cleanup', rx.cleanup)
    bench2, _t6, t89, _t85 = make_rf_bench()
    r2 = c.inst(HP8902A, t89, opened=False, label='8902A')
    c.quiet(r2.connect)
    c.run('HP8902A.reset_to_defaults', r2.reset_to_defaults)


def cases_8563e(c):
    bench, t6, t8902, t8563 = make_rf_bench()
    gen = Fluke6060A(t6).connect()
    sa = c.inst(HP8563E, t8563, opened=False, label='8563E')
    c.run('HP8563E.connect', sa.connect)
    c.run('HP8563E.identify', sa.identify)
    c.run('HP8563E.read_errors', sa.read_errors)
    c.run('HP8563E.check_errors', sa.check_errors, 'ctx')
    c.run('HP8563E.set_units_dbm', sa.set_units_dbm)
    c.run('HP8563E.set_center_hz', sa.set_center_hz, 250e6)
    c.run('HP8563E.set_center_hz[above range]', sa.set_center_hz, 30e9)
    c.run('HP8563E.set_span_hz', sa.set_span_hz, 1e6)
    c.run('HP8563E.set_start_hz', sa.set_start_hz, 200e6)
    c.run('HP8563E.set_stop_hz', sa.set_stop_hz, 300e6)
    c.run('HP8563E.set_rbw_hz', sa.set_rbw_hz, 30e3)
    c.run('HP8563E.set_vbw_hz', sa.set_vbw_hz, 30e3)
    c.run('HP8563E.set_reference_level_dbm', sa.set_reference_level_dbm, 10.0)
    c.run('HP8563E.set_attenuation_db', sa.set_attenuation_db, 20)
    c.run('HP8563E.set_attenuation_db[out of range]', sa.set_attenuation_db, 90)
    c.run('HP8563E.set_detector', sa.set_detector, 'POS')
    c.run('HP8563E.set_marker_threshold', sa.set_marker_threshold, -90.0)
    c.run('HP8563E.set_marker_excursion', sa.set_marker_excursion, 6.0)
    c.run('HP8563E.sweep_time_s', sa.sweep_time_s)
    gen.set_frequency(250.0)
    gen.set_level(-10.0)
    gen.rf(True)
    c.run('HP8563E.single_sweep', sa.single_sweep)
    c.run('HP8563E.take_sweep', sa.take_sweep)
    c.run('HP8563E.marker_to_peak', sa.marker_to_peak)
    c.run('HP8563E.delta_to_next_peak', sa.delta_to_next_peak)
    c.run('HP8563E.configure', sa.configure, 250e6, 1e6, 30e3, 30e3, 10.0, 20, 'POS')
    c.run('HP8563E.measure_fundamental', sa.measure_fundamental, 250e6)
    c.run('HP8563E.measure_fundamental[no carrier]', sa.measure_fundamental, 400e6, 1e6)
    c.run('HP8563E.measure_harmonics', sa.measure_harmonics, 250e6, 4)
    c.run('HP8563E.scan_spurs', sa.scan_spurs, 100e6, 900e6, 250e6, 3)
    gen.rf(False)
    c.run('HP8563E.cleanup', sa.cleanup)
    bench2, _t6, _t89, t85 = make_rf_bench()
    s2 = c.inst(HP8563E, t85, opened=False, label='8563E')
    c.quiet(s2.connect)
    c.run('HP8563E.reset_to_defaults', s2.reset_to_defaults)


def cases_pmeter(c):
    from tests.golden_capture import Scripted
    bench, t6, _a, _b = make_rf_bench()
    gen = Fluke6060A(t6).connect()
    t = Sim96270AMeter(bench)
    pm = c.inst(Fluke96270A, t, opened=False, label='96270A')
    c.quiet(pm.connect)
    c.run('Fluke96270A.select_power_meter[single]', pm.select_power_meter, 250e6, 'AUTO', True)
    c.run('Fluke96270A.select_power_meter[continuous, the default]', pm.select_power_meter, 1e9)
    c.run('Fluke96270A.select_power_meter[continuous, 8 averages]', pm.select_power_meter, 1e9, '8', False)
    c.run('Fluke96270A.zero', pm.zero)
    gen.set_frequency(250.0)
    gen.set_level(-10.0)
    gen.rf(True)
    c.run('Fluke96270A.read_dbm', pm.read_dbm)
    gen.rf(False)
    c.run('Fluke96270A.read_dbm[RF off]', pm.read_dbm)
    t.zero_reply = '1'
    c.run('Fluke96270A.zero[failed]', pm.zero)
    c.run('Fluke96270A.select_sine', pm.select_sine)
    nosensor = c.inst(Fluke96270A, Sim96270AMeter(bench, sensor='NONE,NONE,NONE,NONE'), label='96270A')
    c.run('Fluke96270A.select_power_meter[no sensor]', nosensor.select_power_meter, 250e6)
    implausible = c.inst(Fluke96270A, Scripted([(r'^PMET1:READ\?', '9.91E+37')]), label='96270A')
    c.run('Fluke96270A.read_dbm[no reading]', implausible.read_dbm)
    watts = c.inst(Fluke96270A, Scripted([(r'^PMET1:READ\?', '1.0E-4')]), label='96270A')
    c.run('Fluke96270A.read_dbm[not plausible as dBm]', watts.read_dbm)
    watts_big = c.inst(Fluke96270A, Scripted([(r'^PMET1:READ\?', '-300')]), label='96270A')
    c.run('Fluke96270A.read_dbm[below the floor]', watts_big.read_dbm)


def driver_cases(c):
    cases_6060a(c)
    cases_8902a(c)
    cases_8563e(c)
    cases_pmeter(c)
