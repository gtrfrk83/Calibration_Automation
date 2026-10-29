"""BENCH STEP 7 - 8563E harmonics and one spur scan with the suite's own HP8563E driver (used by 4A-11).  Owner: "lets do them", 2026-10-29 07:57.

THIS STEP SWITCHES THE 6060A RF OUTPUT ON at +13 dBm (the 4A-11 level): 50 MHz, then 300 MHz, then 244 MHz. It is switched OFF again at the end, also if anything
fails or you press Ctrl+C, and the OFF is confirmed by reading the 6060A back.  +13 dBm is well inside the 8563E input rating with the driver's 20 dB attenuation.

Run it FROM THE SUITE FOLDER of calibration_suite_6060a_j.zip (or later):   python tools\\bench\\bench_step7_8563e_harmonics.py
Cable: 6060A RF OUTPUT -> 8563E INPUT 50 ohm (the way it is connected for 4A-11).

What is sent:
  6060A (GPIB1::2, plain writes, each once): RO0, FR<f>MZ, AP13DB (read back with IR and LM99 each time), RO1 after you type YES, RO0 at the end.  No device clear.
  8563E (GPIB1::18, the suite's driver):
      connect(): device clear (= IP preset), ID?, ERR?
      measure_harmonics(50 MHz and 300 MHz, n_max 3): CF / SP / RB / VB / RL / AT / DET set and read back, SNGLS, TS;DONE?, MKPK HI, MKF?, MKA?, MKCF, then CF = 2 x and 3 x
          the fundamental with TS;DONE? / MKPK HI / MKF? / MKA? - the harmonics in dBc (limit < -30 dBc)
      scan_spurs(200 to 400 MHz, carrier 244 MHz): one sweep, MKPK HI then repeated MKPK NH (the peak walk that is UNVERIFIED) - the spur at 312 MHz must be < -60 dBc
      cleanup(): continuous sweep, front panel.
It writes bench_step7_result.txt and bench_step7_result.json next to where you run it. Send BOTH back.
"""
import time

import benchlib

b = benchlib.Bench(7, '8563E harmonics and a spur scan with the suite driver (6060A at +13 dBm)', 'lets do them (2026-10-29 07:57); YES typed before RF on')
drivers = b.drivers
sa = None
try:
    b.say('\n-- 6060A: RF off, 50 MHz, +13 dBm')
    b.open_gen()
    b.gen_set(50, 13)
    b.say('\n-- 8563E: connect with the suite driver')
    sa = drivers.HP8563E(drivers.open_visa(benchlib.SA_ADDR, timeout=30), b.cmdlog, label='8563E', address=18)
    sa.connect()
    b.result(what='8563E connect', id=sa.idn, errors_at_connect=list(sa.errors_at_connect))
    ok = b.ask_operator('\nIs the 6060A RF OUTPUT connected to the 8563E INPUT? Type YES to switch the 6060A RF ON (50 MHz, +13 dBm): ')
    b.log['operator_cable_confirm'] = ok
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before RF ON (as asked).')
    b.rf(True)
    for mhz in (50, 300):
        b.say(f'\n-- harmonics of {mhz} MHz at +13 dBm')
        if mhz != 50:
            b.gen_set(mhz=mhz)
        time.sleep(1.0)
        t = time.time()
        try:
            h = sa.measure_harmonics(mhz * 1e6, n_max=3)
            b.result(fundamental_mhz=mhz, fundamental_dbm=round(h['fundamental_dbm'], 2), fundamental_hz=h['fundamental_hz'],
                     harmonics=[(r['n'], r['freq_hz'], None if r['level_dbm'] is None else round(r['level_dbm'], 2), None if r['dbc'] is None else round(r['dbc'], 2),
                                 r['found']) for r in h['harmonics']], seconds=round(time.time() - t, 1))
        except Exception as exc:                 # noqa: BLE001
            b.result(fundamental_mhz=mhz, error=f'{type(exc).__name__}: {exc}', seconds=round(time.time() - t, 1))
        b.log['results'][-1]['display'] = b.ask_operator(f'   {mhz} MHz: anything odd on the 8563E screen? (Enter to skip) ')
    b.say('\n-- spur scan 200 to 400 MHz, carrier 244 MHz at +13 dBm (the 4A-11 spur at 312 MHz)')
    b.gen_set(mhz=244)
    time.sleep(1.0)
    t = time.time()
    try:
        s = sa.scan_spurs(200e6, 400e6, carrier_hz=244e6, exclude_harmonics=1)
        b.result(spur_scan='200-400 MHz', carrier_dbm=s.get('carrier_dbm'), peaks_visited=s.get('peaks_visited'), stopped=s.get('stopped'),
                 spurs=[(round(x['freq_hz']), round(x['level_dbm'], 2), None if x.get('dbc') is None else round(x['dbc'], 2)) for x in s.get('spurs', [])],
                 seconds=round(time.time() - t, 1))
    except Exception as exc:                     # noqa: BLE001
        b.result(spur_scan='200-400 MHz', error=f'{type(exc).__name__}: {exc}', seconds=round(time.time() - t, 1))
    b.log['results'][-1]['display'] = b.ask_operator('   spur scan: did the marker jump from peak to peak on the 8563E screen? (Enter to skip) ')
finally:
    if sa is not None:
        try:
            sa.cleanup()
        except Exception:                        # noqa: BLE001
            pass
    b.finish()
