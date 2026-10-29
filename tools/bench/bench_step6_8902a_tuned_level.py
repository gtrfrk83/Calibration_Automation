"""BENCH STEP 6 - 8902A tuned RF level with the suite's own HP8902A driver (used by 4A-6, 4A-7 and 4A-8).  Owner: "lets do them", 2026-10-29 07:57.

THIS STEP SWITCHES THE 6060A RF OUTPUT ON at 120 MHz: -10, -30, -60, -90, -120 and -127 dBm, in that order (highest first). It is switched OFF again at the end,
also if anything fails or you press Ctrl+C, and the OFF is confirmed by reading the 6060A back.

Run it FROM THE SUITE FOLDER of calibration_suite_6060a_j.zip (or later):   python tools\\bench\\bench_step6_8902a_tuned_level.py
Cable: 6060A RF OUTPUT -> the 11722A sensor module -> 8902A (the way it is connected for 4A-8), or straight to the 8902A RF INPUT if that is how you measure tuned level.

What is sent:
  6060A (GPIB1::2, plain writes, each once): RO0, FR120MZ, AP<level>DB (read back with IR and LM99 each time), RO1 after you type YES, RO0 at the end.  No device clear.
  8902A (GPIB1::14, the suite's driver):
      connect(): device clear (= IP preset), ID (one short try), serial poll
      tuned_rf_level_dbm(120): 120MZ, S4, LG, 4.0SP, serial poll, T1, T3, read
      when the receiver asks for a calibration (RECAL / UNCAL, status bit 32): calibrate_tuned_level(120): the same setup, C1, T1, T3, read, C0 - then the reading again.
      This is exactly what the procedure does at each tuned-level point.
It writes bench_step6_result.txt and bench_step6_result.json next to where you run it. Send BOTH back.
"""
import time

import benchlib

LEVELS_DBM = (-10, -30, -60, -90, -120, -127)
FREQ_MHZ = 120

b = benchlib.Bench(6, '8902A tuned RF level with the suite driver (6060A at 120 MHz)', 'lets do them (2026-10-29 07:57); YES typed before RF on')
drivers = b.drivers
try:
    if not hasattr(drivers.HP8902A, '_line_ends'):
        raise SystemExit('This suite folder has an old 8902A driver. Unzip calibration_suite_6060a_j.zip (or later) and run the script from that folder.')
    b.say('\n-- 6060A: RF off, 120 MHz, -10 dBm')
    b.open_gen()
    b.gen_set(FREQ_MHZ, LEVELS_DBM[0])
    b.say('\n-- 8902A: connect with the suite driver')
    rx = drivers.HP8902A(drivers.open_visa(benchlib.RX_ADDR, timeout=45), b.cmdlog, label='8902A', address=14)
    rx.connect()
    b.result(what='8902A connect', id_reply=rx.id_reply or '(none)')
    ok = b.ask_operator('\nIs the 6060A RF OUTPUT connected to the 8902A (sensor module or RF INPUT)? Type YES to switch the 6060A RF ON (120 MHz, -10 dBm): ')
    b.log['operator_cable_confirm'] = ok
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before RF ON (as asked).')
    b.rf(True)
    for lv in LEVELS_DBM:
        b.say(f'\n-- {lv} dBm')
        if lv != LEVELS_DBM[0]:
            b.gen_set(dbm=lv)
        time.sleep(1.0)
        t = time.time()
        recal = False
        try:
            try:
                value = rx.tuned_rf_level_dbm(FREQ_MHZ)
            except drivers.RecalRequired as exc:
                recal = True
                b.say(f'   the receiver asks for a calibration: {exc}')
                cal = rx.calibrate_tuned_level(FREQ_MHZ)
                b.say(f'   calibration reading: {cal}')
                value = rx.tuned_rf_level_dbm(FREQ_MHZ)
            b.result(level_set_dbm=lv, reading_dbm=round(value, 3), error_db=round(value - lv, 3), recal=recal, seconds=round(time.time() - t, 1))
        except Exception as exc:                 # noqa: BLE001 - record and carry on to the next level
            b.result(level_set_dbm=lv, error=f'{type(exc).__name__}: {exc}', recal=recal, seconds=round(time.time() - t, 1))
        disp = b.ask_operator(f'   {lv} dBm: what does the 8902A display show? (Enter to skip) ')
        b.log['results'][-1]['display'] = disp
    try:
        rx.cleanup()
    except Exception:                            # noqa: BLE001
        pass
finally:
    b.finish()
