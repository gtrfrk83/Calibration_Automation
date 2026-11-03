"""BENCH STEP 6c - step 6b again with the FIXED 8902A driver (calibration_suite_6060a_l or later), plus two jump tests that decide how the procedure orders 4A-7.

Driver fixes from step 6b: RECAL is made visible at connect (22.34SP); a setup the receiver already holds is NOT sent again (step 6b re-sent the tune + S4 at every
level, a re-acquisition, and lost the signal at -115 dBm); the 1 mW calibration is checked with the calibrator still on (C1T3SC, T1, T3, read, C0).

THIS STEP SWITCHES THE 6060A RF OUTPUT ON at 120 MHz (-13 dBm down to -127 dBm in 6 dB steps), then -61 and -127 again at 120 MHz, then 244 MHz at -127 dBm.
It is switched OFF again at the end, also if anything fails or you press Ctrl+C, and the OFF is confirmed by reading the 6060A back.

Run it FROM tools\\bench OF calibration_suite_6060a_l (or later):   python bench_step6c_8902a_tuned_level_locked.py
The 11722A moves once, as in 6b: first on the 8902A CALIBRATION RF POWER OUTPUT (zero + 1 mW calibration, 6060A RF off), then on the 6060A RF OUTPUT.

What is sent: as in step 6b (the driver's own sequences), and at the end:
  jump test 1: 6060A AP-61DB, a reading (RECAL handled), then AP-127DB straight away and a reading - can the locked receiver follow a 66 dB jump?
  jump test 2: 6060A FR244MZ at -127 dBm and tuned_rf_level_dbm(244) - can the receiver find a NEW frequency at -127 dBm (what 4A-7 asks today)?
It writes bench_step6c_result.txt and bench_step6c_result.json next to where you run it. Send BOTH back.
"""
import time

import benchlib

FREQ_MHZ = 120
LEVELS_DBM = tuple(range(-13, -128, -6))          # -13, -19, ... -121, then -127
if LEVELS_DBM[-1] != -127:
    LEVELS_DBM = LEVELS_DBM + (-127,)

b = benchlib.Bench('6c', '8902A tuned RF level with the fixed driver, 6 dB steps, jump tests (6060A at 120 / 244 MHz)', 'step 6b follow-up 2026-10-29; YES typed before RF on')
drivers = b.drivers
rx = None
try:
    if not hasattr(drivers.HP8902A, 'show_recal'):
        raise SystemExit('This suite folder has an old 8902A driver. Unzip calibration_suite_6060a_l (or later) and run this from its tools\\bench.')
    b.say('\n-- 6060A: RF off, 120 MHz, -13 dBm')
    b.open_gen()
    b.gen_set(FREQ_MHZ, LEVELS_DBM[0])
    b.say('\n-- 8902A: connect (the driver sends 22.34SP itself now)')
    rx = drivers.HP8902A(drivers.open_visa(benchlib.RX_ADDR, timeout=60), b.cmdlog, label='8902A', address=14)
    rx.connect()
    b.result(what='8902A connect', id_reply=rx.id_reply or '(none)')

    ok = b.ask_operator('\nPut the 11722A sensor module input on the 8902A CALIBRATION RF POWER OUTPUT (6060A RF stays OFF). Type YES when done: ')
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before the zero (as asked).')
    t = time.time()
    try:
        b.result(what='zero_power_sensor', residual_w=rx.zero_power_sensor(), seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='zero_power_sensor', error=f'{type(exc).__name__}: {exc}', seconds=round(time.time() - t, 1))
    t = time.time()
    try:
        b.result(what='calibrate_power_sensor', reading_w=rx.calibrate_power_sensor(), seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='calibrate_power_sensor', error=f'{type(exc).__name__}: {exc}', seconds=round(time.time() - t, 1))
    b.log['results'][-1]['display'] = b.ask_operator('   after the 1 mW calibration, what does the 8902A display show? (Enter to skip) ')

    ok = b.ask_operator('\nNow move the 11722A input to the 6060A RF OUTPUT. Type YES to switch the 6060A RF ON (120 MHz, -13 dBm): ')
    b.log['operator_cable_confirm'] = ok
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before RF ON (as asked).')
    b.rf(True)
    time.sleep(2.0)
    t = time.time()
    try:
        b.result(what='rf_power_dbm at -13 dBm (M4, for comparison)', reading_dbm=round(rx.rf_power_dbm(FREQ_MHZ), 3), seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='rf_power_dbm at -13 dBm', error=f'{type(exc).__name__}: {exc}', seconds=round(time.time() - t, 1))
    for lv in LEVELS_DBM:
        b.say(f'\n-- {lv} dBm')
        if lv != LEVELS_DBM[0]:
            b.gen_set(dbm=lv)
        time.sleep(1.0)
        t = time.time()
        recal = 0
        try:
            while True:
                try:
                    value = rx.tuned_rf_level_dbm(FREQ_MHZ)
                    break
                except drivers.RecalRequired as exc:
                    recal += 1
                    b.say(f'   RECAL #{recal}: {exc}')
                    if recal > 3:
                        raise
                    cal = rx.calibrate_tuned_level(FREQ_MHZ)
                    b.say(f'   calibration reading: {cal}')
            b.result(level_set_dbm=lv, reading_dbm=round(value, 3), error_db=round(value - lv, 3), recal=recal, seconds=round(time.time() - t, 1))
        except Exception as exc:                 # noqa: BLE001 - record and carry on
            b.result(level_set_dbm=lv, error=f'{type(exc).__name__}: {exc}', recal=recal, seconds=round(time.time() - t, 1))
    b.log['display_end'] = b.ask_operator('\nWhat does the 8902A display show now (at -127 dBm)? (Enter to skip) ')
    b.say('\n-- jump test 1: -61 dBm, then straight to -127 dBm (same frequency, setup held)')
    b.gen_set(dbm=-61)
    time.sleep(1.0)

    t = time.time()
    recal = 0
    try:
        while True:
            try:
                value = rx.tuned_rf_level_dbm(FREQ_MHZ)
                break
            except drivers.RecalRequired as exc:
                recal += 1
                b.say(f'   RECAL #{recal}: {exc}')
                if recal > 3:
                    raise
                b.say(f'   calibration reading: {rx.calibrate_tuned_level(FREQ_MHZ)}')
        b.result(what='jump 1: -61 dBm at 120 MHz', reading_dbm=round(value, 3), recal=recal, seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='jump 1: -61 dBm at 120 MHz', error=f'{type(exc).__name__}: {exc}', recal=recal, seconds=round(time.time() - t, 1))
    b.gen_set(dbm=-127)
    time.sleep(1.0)

    t = time.time()
    recal = 0
    try:
        while True:
            try:
                value = rx.tuned_rf_level_dbm(FREQ_MHZ)
                break
            except drivers.RecalRequired as exc:
                recal += 1
                b.say(f'   RECAL #{recal}: {exc}')
                if recal > 3:
                    raise
                b.say(f'   calibration reading: {rx.calibrate_tuned_level(FREQ_MHZ)}')
        b.result(what='jump 1: -127 dBm straight after -61 dBm', reading_dbm=round(value, 3), recal=recal, seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='jump 1: -127 dBm straight after -61 dBm', error=f'{type(exc).__name__}: {exc}', recal=recal, seconds=round(time.time() - t, 1))
    b.say('\n-- jump test 2: a new frequency (244 MHz) at -127 dBm')
    b.gen_set(mhz=244)
    time.sleep(1.0)

    t = time.time()
    recal = 0
    try:
        while True:
            try:
                value = rx.tuned_rf_level_dbm(244)
                break
            except drivers.RecalRequired as exc:
                recal += 1
                b.say(f'   RECAL #{recal}: {exc}')
                if recal > 3:
                    raise
                b.say(f'   calibration reading: {rx.calibrate_tuned_level(244)}')
        b.result(what='jump 2: 244 MHz at -127 dBm (new frequency)', reading_dbm=round(value, 3), recal=recal, seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(what='jump 2: 244 MHz at -127 dBm (new frequency)', error=f'{type(exc).__name__}: {exc}', recal=recal, seconds=round(time.time() - t, 1))
    b.log['display_jumps'] = b.ask_operator('   after the jump tests, what does the 8902A display show? (Enter to skip) ')
finally:
    if rx is not None:
        try:
            rx.cleanup()
        except Exception:                        # noqa: BLE001
            pass
    b.finish()
