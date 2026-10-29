"""BENCH STEP 6b - 8902A tuned RF level done the manual's way: power-sensor zero + 1 mW calibration first, RECAL made visible, 6 dB steps down to -127 dBm.

Step 6 result (2026-10-29): -10.58, -30.58, -60.85, -91.5 dBm (the error grew as the level fell), then error 96 (no signal) at -120 and -127 dBm.
Two reasons, both in the step: (1) the 11722A power calibration (ZR, then C1 T3 SC on the 1 mW 50 MHz output) was never done; (2) the 8902A's status byte only shows
RECAL (bit value 32) when the SRQ mask lets it through - the preset mask hides it, so the driver never saw a RECAL and never calibrated the lower ranges. The manual
steps down at constant frequency and presses CALIBRATE (C1) at each RECAL with the level held (p. 3-97); 4A-8 steps in 6 dB. This step does exactly that.

THIS STEP SWITCHES THE 6060A RF OUTPUT ON at 120 MHz, from -13 dBm down to -127 dBm in 6 dB steps (20 levels). It is switched OFF again at the end, also if anything
fails or you press Ctrl+C, and the OFF is confirmed by reading the 6060A back.

Run it FROM tools\\bench OF THE SUITE FOLDER (calibration_suite_6060a_k or later):   python bench_step6b_8902a_tuned_level_calibrated.py
You will move the 11722A sensor module once:
  first  11722A input on the 8902A CALIBRATION RF POWER OUTPUT (for the zero and the 1 mW calibration; the 6060A RF stays OFF),
  then   11722A input on the 6060A RF OUTPUT (for the tuned-level readings).

What is sent:
  6060A (GPIB1::2, plain writes, each once): RO0, FR120MZ, AP<level>DB (read back with IR and LM99 each time), RO1 after you type YES, RO0 at the end.  No device clear.
  8902A (GPIB1::14, the suite's driver unless marked):
      connect(): device clear (= IP), ID, serial poll
      22.34SP (SRQ mask: RECAL/UNCAL 32 + code error 2, so RECAL shows in the serial poll) - plain driver write, its effect is checked by watching the polls
      zero_power_sensor():     M4, LN, WT, ZR, T1, T3, read (residual must be below 3 uW)
      calibrate_power_sensor(): M4, LN, WT, C1T3SC, C0, T1, T3, read (must read 0.999 to 1.000 mW)
      rf_power_dbm(120) at -13 dBm (for comparison): 120MZ, M4, LG, T1, T3, read
      at every level: tuned_rf_level_dbm(120): 120MZ, S4, LG, 4.0SP, poll, T1, T3, read, poll; when the poll shows RECAL (32):
          calibrate_tuned_level(120) (C1, T1, T3, read, C0) with the level held, then the reading again - what the procedure does.
It writes bench_step6b_result.txt and bench_step6b_result.json next to where you run it. Send BOTH back.
"""
import time

import benchlib

FREQ_MHZ = 120
LEVELS_DBM = tuple(range(-13, -128, -6))          # -13, -19, ... -121, then -127
if LEVELS_DBM[-1] != -127:
    LEVELS_DBM = LEVELS_DBM + (-127,)

b = benchlib.Bench('6b', '8902A tuned RF level, calibrated, 6 dB steps (6060A at 120 MHz)', 'owner 2026-10-29 08:16: the sensor was not calibrated beforehand; YES typed before RF on')
drivers = b.drivers
rx = None
try:
    if not hasattr(drivers.HP8902A, '_line_ends'):
        raise SystemExit('This suite folder has an old 8902A driver. Use calibration_suite_6060a_k (or later).')
    b.say('\n-- 6060A: RF off, 120 MHz, -13 dBm')
    b.open_gen()
    b.gen_set(FREQ_MHZ, LEVELS_DBM[0])
    b.say('\n-- 8902A: connect, make RECAL visible in the status byte')
    rx = drivers.HP8902A(drivers.open_visa(benchlib.RX_ADDR, timeout=60), b.cmdlog, label='8902A', address=14)
    rx.connect()
    b.result(what='8902A connect', id_reply=rx.id_reply or '(none)')
    rx.write('22.34SP')
    time.sleep(1.0)
    b.result(what='status after 22.34SP', poll=rx.status()['value'])

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
finally:
    if rx is not None:
        try:
            rx.cleanup()
        except Exception:                        # noqa: BLE001
            pass
    b.finish()
