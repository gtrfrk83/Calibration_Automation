"""BENCH STEP 3 - why the 8902A does not SEND its frequency reading (bench-first driver workflow, NOTES.md).  Owner OK: "ok step 3", 2026-10-29 07:28.
Step 2 result: the 8902A DISPLAYED 111.11110 MHz but after T1 / T3 nothing came over the bus in 20 s (status byte 0). This step tries seven ways: GET first (owner, 07:33: 'you need the GET command to retrieve the reading').

THIS STEP SWITCHES THE 6060A RF OUTPUT ON (-10 dBm, 111.1111 MHz). It is switched OFF again at the end, also if anything fails or you press Ctrl+C,
and the OFF is confirmed by reading the 6060A back.

What is sent (nothing else; every write is sent once, never repeated):
  6060A (GPIB1::2):  RO0, FR111.1111MZ, AP-10DB, then RO1 after you confirm the cable; at the end RO0.  Read-only: ID, IR, IU, LM99.  NO device clear.
  8902A (GPIB1::14): for each of seven tests: IP (preset), M5 (frequency), 7.1SP or 7.0SP (10 Hz / automatic resolution), and then
                       F  T1 (hold), then GET (the IEEE-488 Group Execute Trigger bus message - the owner's earlier automation used it), read
                       G  GET alone (no T code), read
                       A  22.3SP (SRQ mask: data ready + code error, the 8902A's own setting), T1, T3, serial poll every 0.5 s up to 30 s, read
                       B  T2 (trigger without settling), read
                       C  T0 (free run), read
                       D  7.0SP automatic resolution, T1, T3, read
                       E  T1, T3, read with a 60 s wait
                     Read-only: serial polls and the readings.  It takes about 5 minutes.
Cable: 6060A RF OUTPUT -> 8902A RF INPUT, the way it is connected for test 4A-4.

Run:   python bench_step3_8902a_frequency_ways.py
It writes bench_step3_result.txt and bench_step3_result.json next to where you run it. Send BOTH back.
"""
import json
import sys
import time

try:
    import pyvisa
except ImportError:
    sys.exit('pyvisa is not installed (pip install pyvisa)')

GEN_ADDR = 'GPIB1::2::INSTR'
RX_ADDR = 'GPIB1::14::INSTR'
FREQ_MHZ = '111.1111'
LEVEL_DBM = '-10'

LOG = {'step': 3, 'owner_ok': 'ok step 3 (2026-10-29 07:28)', 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'events': []}
out = open('bench_step3_result.txt', 'w', encoding='utf-8')


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
    """One write, never repeated."""
    try:
        res.write(cmd)
        event(who, 'write', cmd, note=note)
        return True
    except Exception as exc:              # noqa: BLE001
        event(who, 'write', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', note=note)
        return False


def query(res, who, cmd, timeout_ms=4000, note=''):
    """Read-only: write the query (None = nothing), read the raw reply."""
    t = time.time()
    try:
        res.timeout = timeout_ms
        if cmd is not None:
            res.write(cmd)
        raw = res.read_raw().decode('latin-1')
        event(who, 'query', cmd, reply=raw, seconds=round(time.time() - t, 3), note=note)
        return raw
    except Exception as exc:              # noqa: BLE001
        event(who, 'query', cmd, error=f'{type(exc).__name__}: {str(exc)[:140]}', seconds=round(time.time() - t, 3), note=note)
        return None


def poll(res, who, note=''):
    try:
        v = res.read_stb()
        event(who, 'poll', reply=v, note=note)
        return v
    except Exception as exc:              # noqa: BLE001
        event(who, 'poll', error=f'{type(exc).__name__}: {str(exc)[:140]}', note=note)
        return None


def learn(text):
    """6060A LM99 learn string -> (frequency Hz, amplitude dBm): characters 25-32 and 9-12 (letters A-P = hex 0-F, Figure 2-7)."""
    try:
        s = text.strip()
        h = lambda t: int(''.join('0123456789ABCDEF'[ord(c) - 65] for c in t), 16)      # noqa: E731
        amp = h(s[8:12])
        amp = amp - 65536 if amp >= 32768 else amp
        return h(s[24:32]), amp / 10.0
    except Exception:                     # noqa: BLE001
        return None, None


def rf_is_off(iu_reply):
    """IU field 3 has octal 400 set while the RF output is off (UNCAL table, p. 2-25; seen on the bench in step 1)."""
    try:
        return bool(int(iu_reply.strip().split(',')[2], 8) & 0o400)
    except Exception:                     # noqa: BLE001
        return None


def decode_8902(text):
    try:
        t = text.strip()
        v = (-1 if t[0] == '-' else 1) * int(t[1:11]) * 10.0 ** int(t[12:])
        if v > 9e10 + 1:
            return f'ERROR {round((v - 9e10) / 1000)}'
        return f'{v:.1f} Hz'
    except Exception:                     # noqa: BLE001
        return 'unreadable'


T0 = time.time()
rm = pyvisa.ResourceManager()
say(f'Bench step 3 (6060A RF ON, 8902A frequency: five ways)  {LOG["started"]}')
gen = rm.open_resource(GEN_ADDR)
rx = rm.open_resource(RX_ADDR)
for r in (gen, rx):
    r.write_termination = '\n'
    r.read_termination = None
rf_switched_on = False
try:
    say('\n-- 6060A: identify, RF off, set 111.1111 MHz and -10 dBm')
    ident = query(gen, '6060A', 'ID')
    if not ident or '6060A' not in ident:
        raise SystemExit(f'Not a 6060A at {GEN_ADDR}: {ident!r}. Nothing was switched on.')
    query(gen, '6060A', 'IR', note='clear any old rejected entry (read)')
    write(gen, '6060A', 'RO0', 'RF off first')
    write(gen, '6060A', f'FR{FREQ_MHZ}MZ')
    write(gen, '6060A', f'AP{LEVEL_DBM}DB')
    time.sleep(0.5)
    rej = query(gen, '6060A', 'IR', note='rejected entries after the writes (000000,... = none)')
    lm = query(gen, '6060A', 'LM99', note='read back')
    f_hz, a_dbm = learn(lm or '')
    say(f'   read back: frequency {f_hz} Hz, amplitude {a_dbm} dBm')
    LOG['readback_before_rf'] = {'frequency_hz': f_hz, 'amplitude_dbm': a_dbm, 'ir': rej}
    if f_hz != 111111100 or a_dbm != -10.0:
        raise SystemExit('The 6060A did not take 111.1111 MHz / -10 dBm (see above). RF stays OFF. Send the result files back.')

    ok = input('\nIs the 6060A RF OUTPUT cabled to the 8902A RF INPUT? Type YES to switch the 6060A RF ON (-10 dBm), anything else to stop: ').strip()
    LOG['operator_cable_confirm'] = ok
    if ok.upper() != 'YES':
        raise SystemExit('Stopped before RF ON (as asked).')
    rf_switched_on = True                  # from here on the finally block switches it off whatever happens
    write(gen, '6060A', 'RO1', 'RF ON')
    time.sleep(1.0)
    query(gen, '6060A', 'IU', note='UNCAL codes with RF on (000000,000000,000000 = none)')

    TESTS = [
        ('F', 'T1 hold, then GET (Group Execute Trigger), read', '7.1SP', [], ['T1', 'GET'], 'read', 20000),
        ('G', 'GET alone, read', '7.1SP', [], ['GET'], 'read', 20000),
        ('A', 'data-ready SRQ mask, T1 T3, poll up to 30 s, read', '7.1SP', ['22.3SP'], ['T1', 'T3'], 'poll', 30000),
        ('B', 'T2 trigger without settling, read', '7.1SP', [], ['T2'], 'read', 20000),
        ('C', 'T0 free run, read', '7.1SP', [], ['T0'], 'read', 20000),
        ('D', 'automatic resolution 7.0SP, T1 T3, read', '7.0SP', [], ['T1', 'T3'], 'read', 20000),
        ('E', 'T1 T3, read with a 60 s wait', '7.1SP', [], ['T1', 'T3'], 'read', 60000),
    ]
    LOG['tests'] = []
    for name, title, res_code, extra, trig, how, wait_ms in TESTS:
        say(f'\n-- TEST {name}: {title}')
        write(rx, '8902A', 'IP')
        time.sleep(3.0)
        poll(rx, '8902A', 'after IP + 3 s')
        write(rx, '8902A', 'M5')
        write(rx, '8902A', res_code)
        for c in extra:
            write(rx, '8902A', c)
        time.sleep(1.0)
        poll(rx, '8902A', 'after the setup + 1 s')
        for c in trig:
            if c == 'GET':                    # the bus message, not a text: pyvisa assert_trigger() sends GET to this address on GPIB
                try:
                    rx.assert_trigger()
                    event('8902A', 'GET', 'GET (Group Execute Trigger)')
                except Exception as exc:      # noqa: BLE001
                    event('8902A', 'GET', 'GET (Group Execute Trigger)', error=f'{type(exc).__name__}: {str(exc)[:140]}')
            else:
                write(rx, '8902A', c)
        polls = []
        if how == 'poll':
            t_end = time.time() + wait_ms / 1000.0
            while time.time() < t_end:
                try:
                    v = rx.read_stb()
                except Exception as exc:      # noqa: BLE001
                    v = f'poll failed: {str(exc)[:60]}'
                polls.append((round(time.time() - T0, 2), v))
                if isinstance(v, int) and v & 1:
                    break
                time.sleep(0.5)
            event('8902A', 'polls', reply=str(polls[-12:]), note=f'{len(polls)} polls; bit 1 (value 1) = data ready')
            reply = query(rx, '8902A', None, timeout_ms=5000, note='read after the polls')
        else:
            reply = query(rx, '8902A', None, timeout_ms=wait_ms, note=f'read, up to {wait_ms // 1000} s')
        st = poll(rx, '8902A', 'after the read')
        try:
            disp = input(f'TEST {name}: what does the 8902A display show now? (type it, Enter) ').strip()
        except EOFError:
            disp = ''
        rec = {'test': name, 'title': title, 'raw': reply, 'decoded': decode_8902(reply) if reply else None, 'status_after': st,
               'data_ready_seen': any(isinstance(v, int) and v & 1 for _t, v in polls) if polls else None, 'display': disp}
        LOG['tests'].append(rec)
        say(f'   TEST {name} result: {rec["decoded"] or "NO REPLY"}   display: {disp}')
finally:
    if rf_switched_on:
        say('\n-- 6060A: RF OFF')
        write(gen, '6060A', 'RO0', 'RF off at the end')
        time.sleep(0.5)
        iu = query(gen, '6060A', 'IU', note='RF off is confirmed when field 3 has 400')
        off = rf_is_off(iu or '')
        LOG['rf_off_confirmed'] = off
        say(f'   RF OFF confirmed by read-back: {off}' + ('' if off else '   <-- CHECK THE 6060A FRONT PANEL: press RF OUTPUT OFF'))
    for r in (gen, rx):
        try:
            r.control_ren(pyvisa.constants.RENLineOperation.address_gtl)
        except Exception:                 # noqa: BLE001
            pass
        r.close()
    LOG['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    with open('bench_step3_result.json', 'w', encoding='utf-8') as f:
        json.dump(LOG, f, indent=1)
    say('\nDone. Send back bench_step3_result.txt and bench_step3_result.json.')
