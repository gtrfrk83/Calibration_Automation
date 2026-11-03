"""BENCH STEP 5 - 96270A power-meter mode with the R&S NRP40T, measuring the 6060A (bench-first driver workflow, NOTES.md).  Owner: "lets do it", 2026-10-29 07:46.

THIS STEP SWITCHES THE 6060A RF OUTPUT ON (120 MHz, -10 dBm then 0 dBm). It is switched OFF again at the end, also if anything fails or you press Ctrl+C,
and the OFF is confirmed by reading the 6060A back.  The 96270A's own output is never switched on (selecting power-meter mode puts it in standby).

What is sent (nothing else; every write is sent once, never repeated):
  96270A (GPIB1::4):  read-only first: *IDN?, PMET1:IDN?, PMET2:IDN?, INST?, OUTP?, SYST:ERR?
                      then INST PMET (power-meter mode), PMET1:FREQ 120E6, PMET1:AVER AUTO, PMET1:TRIG CONT, each read back and SYST:ERR? after;
                      PMET1:ZERO? (sensor zero, with the 6060A RF OFF), PMET1:READ? (readings), UNIT:POW? ; at the end INST SINE (back to how it was), OUTP? (must be 0).
  6060A  (GPIB1::2):  RO0, FR120MZ, AP-10DB (read back), RO1 after you type YES, AP0DB (read back), then RO0.  Read-only: ID, IR, IU, LM99.  NO device clear.
Cable: the NRP40T on the 6060A RF OUTPUT (as for 4A-5), the sensor's cable to the 96270A sensor port.

Run:   python bench_step5_96270a_power_meter.py
It writes bench_step5_result.txt and bench_step5_result.json next to where you run it. Send BOTH back.
"""
import json
import sys
import time

try:
    import pyvisa
except ImportError:
    sys.exit('pyvisa is not installed (pip install pyvisa)')

GEN_ADDR = 'GPIB1::2::INSTR'
PM_ADDR = 'GPIB1::4::INSTR'
FREQ_MHZ = 120

LOG = {'step': 5, 'owner_ok': 'lets do it (2026-10-29 07:46); the script asks for YES before RF on', 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'events': []}
out = open('bench_step5_result.txt', 'w', encoding='utf-8')
T0 = time.time()


def say(text=''):
    print(text)
    out.write(text + '\n')
    out.flush()


def event(who, kind, cmd=None, reply=None, error=None, seconds=None, note=''):
    rec = {'t': round(time.time() - T0, 3), 'who': who, 'kind': kind, 'cmd': cmd, 'reply': reply, 'error': error, 'seconds': seconds, 'note': note}
    LOG['events'].append(rec)
    shown = f'{cmd!r} ' if cmd is not None else ''
    res = (f'-> {reply!r}' if reply is not None else '') + (f' ERROR {error}' if error else '')
    say(f'   {rec["t"]:8.3f}  {who:6} {kind:6} {shown}{res}' + (f'  [{seconds} s]' if seconds is not None else '') + (f'  {note}' if note else ''))
    return rec


def write(res, who, cmd, note=''):
    try:
        res.write(cmd)
        event(who, 'write', cmd, note=note)
        return True
    except Exception as exc:              # noqa: BLE001
        event(who, 'write', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', note=note)
        return False


def query(res, who, cmd, timeout_ms=4000, note=''):
    t = time.time()
    try:
        res.timeout = timeout_ms
        res.write(cmd)
        raw = res.read_raw().decode('latin-1')
        event(who, 'query', cmd, reply=raw, seconds=round(time.time() - t, 3), note=note)
        return raw
    except Exception as exc:              # noqa: BLE001
        event(who, 'query', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', seconds=round(time.time() - t, 3), note=note)
        return None


def learn(text):
    try:
        s = text.strip()
        h = lambda t: int(''.join('0123456789ABCDEF'[ord(c) - 65] for c in t), 16)      # noqa: E731
        amp = h(s[8:12])
        amp = amp - 65536 if amp >= 32768 else amp
        return h(s[24:32]), amp / 10.0
    except Exception:                     # noqa: BLE001
        return None, None


def rf_is_off(iu_reply):
    try:
        return bool(int(iu_reply.strip().split(',')[2], 8) & 0o400)
    except Exception:                     # noqa: BLE001
        return None


def num(text):
    try:
        return float(text.strip().strip('"'))
    except Exception:                     # noqa: BLE001
        return None


def set_level(gen, dbm):
    write(gen, '6060A', f'AP{dbm}DB')
    time.sleep(0.5)
    rej = query(gen, '6060A', 'IR', note='rejected entries (000000,... = none)')
    f_hz, a = learn(query(gen, '6060A', 'LM99', note='read back') or '')
    say(f'   6060A read back: {f_hz} Hz, {a} dBm')
    return f_hz == FREQ_MHZ * 1_000_000 and a == float(dbm) and rej and rej.strip() == '000000,000000,000000'


rm = pyvisa.ResourceManager()
say(f'Bench step 5 (96270A power meter + NRP40T on the 6060A)  {LOG["started"]}')
gen = rm.open_resource(GEN_ADDR)
pm = rm.open_resource(PM_ADDR)
for r in (gen, pm):
    r.write_termination = '\n'
    r.read_termination = '\n'
rf_switched_on = False
pm_mode = False
LOG['readings'] = []
try:
    say('\n-- 96270A: read-only first')
    idn = query(pm, '96270A', '*IDN?')
    if not idn or '96270' not in idn:
        raise SystemExit(f'Not a 96270A at {PM_ADDR}: {idn!r}. Nothing was changed.')
    s1 = query(pm, '96270A', 'PMET1:IDN?', note='sensor 1 (NONE,NONE,NONE,NONE = no sensor)')
    query(pm, '96270A', 'PMET2:IDN?', note='sensor 2')
    query(pm, '96270A', 'INST?')
    query(pm, '96270A', 'OUTP?', note='must be 0')
    query(pm, '96270A', 'SYST:ERR?')
    LOG['sensor1'] = s1
    if not s1 or s1.strip().upper().startswith('NONE'):
        raise SystemExit('The 96270A still sees no sensor on channel 1 (PMET1:IDN? = NONE). Nothing was changed. Check the sensor cable, or tell me which port it is on.')

    say('\n-- 6060A: RF off, 120 MHz, -10 dBm (RF stays OFF for the zero)')
    ident = query(gen, '6060A', 'ID')
    if not ident or '6060A' not in ident:
        raise SystemExit(f'Not a 6060A at {GEN_ADDR}: {ident!r}.')
    query(gen, '6060A', 'IR', note='clear any old rejected entry (read)')
    write(gen, '6060A', 'RO0', 'RF off first')
    write(gen, '6060A', f'FR{FREQ_MHZ}MZ')
    if not set_level(gen, -10):
        raise SystemExit('The 6060A did not take 120 MHz / -10 dBm (see above). RF stays OFF.')

    say('\n-- 96270A: power-meter mode, 120 MHz, zero with the RF off')
    pm_mode = True
    write(pm, '96270A', 'INST PMET')
    time.sleep(1.0)
    query(pm, '96270A', 'INST?', note='expect PMET')
    write(pm, '96270A', f'PMET1:FREQ {FREQ_MHZ}E6')
    query(pm, '96270A', 'PMET1:FREQ?', note=f'expect {FREQ_MHZ}E6')
    write(pm, '96270A', 'PMET1:AVER AUTO')
    query(pm, '96270A', 'PMET1:AVER?')
    write(pm, '96270A', 'PMET1:TRIG CONT')
    query(pm, '96270A', 'PMET1:TRIG?')
    query(pm, '96270A', 'UNIT:POW?', note='the unit of the readings?')
    query(pm, '96270A', 'SYST:ERR?')
    query(pm, '96270A', 'OUTP?', note='must still be 0')
    LOG['zero'] = query(pm, '96270A', 'PMET1:ZERO?', timeout_ms=60000, note='0 = zero done, 1 = failed (RF is OFF now)')
    query(pm, '96270A', 'SYST:ERR?')
    query(pm, '96270A', 'PMET1:READ?', timeout_ms=30000, note='reading with the RF OFF (should be near the noise floor)')

    ok = input('\nIs the NRP40T on the 6060A RF OUTPUT? Type YES to switch the 6060A RF ON (120 MHz, -10 dBm), anything else to stop: ').strip()
    LOG['operator_cable_confirm'] = ok
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before RF ON (as asked).')
    rf_switched_on = True
    write(gen, '6060A', 'RO1', 'RF ON')
    time.sleep(1.0)
    query(gen, '6060A', 'IU', note='UNCAL codes with RF on (all zero = none)')
    for dbm in (-10, 0):
        if dbm != -10 and not set_level(gen, dbm):
            raise SystemExit(f'The 6060A did not take {dbm} dBm.')
        time.sleep(2.0)
        for n in range(1, 4):
            raw = query(pm, '96270A', 'PMET1:READ?', timeout_ms=30000, note=f'{dbm} dBm, reading {n}')
            LOG['readings'].append({'set_dbm': dbm, 'n': n, 'raw': raw, 'value': num(raw) if raw else None})
        query(pm, '96270A', 'SYST:ERR?')
        say(f'   at {dbm} dBm: ' + ', '.join(str(r['value']) for r in LOG['readings'] if r['set_dbm'] == dbm))
    try:
        LOG['display'] = input('\nWhat does the 96270A display show now? (type it, Enter) ').strip()
    except EOFError:
        LOG['display'] = ''
finally:
    if rf_switched_on:
        say('\n-- 6060A: RF OFF')
        write(gen, '6060A', 'RO0', 'RF off at the end')
        time.sleep(0.5)
        iu = query(gen, '6060A', 'IU', note='RF off is confirmed when field 3 has 400')
        off = rf_is_off(iu or '')
        LOG['rf_off_confirmed'] = off
        say(f'   RF OFF confirmed by read-back: {off}' + ('' if off else '   <-- CHECK THE 6060A FRONT PANEL: press RF OUTPUT OFF'))
    if pm_mode:
        say('\n-- 96270A: back to SINE (output stays off)')
        write(pm, '96270A', 'INST SINE')
        time.sleep(1.0)
        query(pm, '96270A', 'INST?', note='expect SINE')
        LOG['pm_output_after'] = query(pm, '96270A', 'OUTP?', note='must be 0')
        query(pm, '96270A', 'SYST:ERR?')
    for r in (gen, pm):
        try:
            r.control_ren(pyvisa.constants.RENLineOperation.address_gtl)
        except Exception:                 # noqa: BLE001
            pass
        r.close()
    LOG['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    with open('bench_step5_result.json', 'w', encoding='utf-8') as f:
        json.dump(LOG, f, indent=1)
    say('\nDone. Send back bench_step5_result.txt and bench_step5_result.json.')
