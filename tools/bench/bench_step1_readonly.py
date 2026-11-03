"""BENCH STEP 1 - READ-ONLY pass over the 6060A bench (bench-first driver workflow, NOTES.md).

READ-ONLY: nothing is set, no output / RF is switched, no preset, no reset, NO DEVICE CLEAR (a device clear on the 6060A switches its RF ON).
Every instrument is only asked to identify itself and report its status / settings (queries and serial polls). Talking to an instrument puts it
in REMOTE (the front panel locks); the script sends it back to LOCAL at the end.

Run on the bench PC (the one with Keysight IO and the GPIB adapter), instruments on:
    python bench_step1_readonly.py
Press Enter at each address question to take the default, type a full VISA address (as Keysight Connection Expert shows it), or type - to skip one.
It writes bench_step1_result.txt and bench_step1_result.json next to where you run it. Send BOTH files back.
"""
import json
import platform
import sys
import time

try:
    import pyvisa
except ImportError:
    sys.exit('pyvisa is not installed (pip install pyvisa)')

RESULT = {'step': 1, 'kind': 'read-only', 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'python': platform.python_version(),
          'arch': platform.architecture()[0], 'pyvisa': pyvisa.__version__, 'instruments': {}}
out = open('bench_step1_result.txt', 'w', encoding='utf-8')


def say(text=''):
    print(text)
    out.write(text + '\n')
    out.flush()


# (key, what, default address, queries).  Every query is READ-ONLY.  Notes say what each one reads.
INSTRUMENTS = [
    ('6060A', 'Fluke 6060A signal generator (UUT)', 'GPIB0::2::INSTR', [
        ('ID', 'identity'), ('IV', 'firmware version'), ('IO', 'installed options'), ('II', 'interface modes'), ('IM', 'SRQ mask'),
        ('IU', 'UNCAL codes'), ('IR', 'rejected-entry codes (reading clears them)'), ('LM99', 'learn string: present state (frequency, level, RF on/off ...)'),
        ('XA', 'hardware attenuation setting (0-23)')]),
    ('8902A', 'HP 8902A measuring receiver', 'GPIB0::14::INSTR', [
        (None, 'talk only (no command): whatever the receiver has to send - the present display value'),
        ('ID', 'identify (the manual does not show a reply; it did not answer on 2026-10-28)')]),
    ('8563E', 'HP 8563E spectrum analyzer', 'GPIB0::18::INSTR', [
        ('ID?;', 'model'), ('REV?;', 'firmware date'), ('SER?;', 'serial number'), ('ERR?;', 'error list'), ('DONE?;', 'sweep done'),
        ('CF?;', 'center frequency'), ('SP?;', 'span'), ('RL?;', 'reference level'), ('AT?;', 'input attenuation'), ('RB?;', 'resolution bandwidth'),
        ('VB?;', 'video bandwidth'), ('ST?;', 'sweep time'), ('AUNITS?;', 'amplitude units'), ('TDF?;', 'trace data format')]),
    ('96270A', 'Fluke 96270A + R&S NRP40T (power meter mode)', '', [
        ('*IDN?', 'identity'), ('SYST:ERR?', 'error queue (one entry)'), ('INST?', 'selected function'), ('INST:CAT?', 'functions it has'),
        ('OUTP?', 'output on/off'), ('UNIT:POW?', 'power units'), ('PMET1:IDN?', 'power sensor 1 identity (is the NRP40T seen?)'),
        ('PMET2:IDN?', 'power sensor 2 identity'), ('PMET1:FREQ?', 'sensor 1 measurement frequency'), ('PMET1:AVER?', 'sensor 1 averaging'),
        ('PMET1:TRIG?', 'sensor 1 trigger mode'), ('*OPC?', 'operation complete')]),
    ('LF', 'Keysight 33210A / 33220A / 33250A function generator', '', [
        ('*IDN?', 'identity'), ('SYST:ERR?', 'error queue (one entry)'), ('OUTP?', 'output on/off'), ('APPL?', 'present waveform, frequency, amplitude, offset'),
        ('OUTP:LOAD?', 'output load setting')]),
]


def ask_address(key, what, default):
    shown = default or 'none - type it, or - to skip'
    try:
        typed = input(f'{key}: {what}\n   VISA address [{shown}]: ').strip()
    except EOFError:
        typed = ''
    if typed == '-':
        return ''
    return typed or default


def stb(res):
    try:
        return res.read_stb()
    except Exception as exc:              # noqa: BLE001
        return f'serial poll failed: {str(exc)[:80]}'


def one_query(res, cmd, timeout_ms):
    """Write cmd (None = nothing) and read the raw reply.  Returns a record: raw bytes as text, how the read ended, seconds."""
    rec = {'cmd': cmd, 'reply': None, 'error': None, 'seconds': None}
    t0 = time.time()
    try:
        res.timeout = timeout_ms
        if cmd is not None:
            res.write(cmd)
        raw = res.read_raw()
        rec['reply'] = raw.decode('latin-1')
        rec['ends_with'] = repr(raw[-2:])
    except Exception as exc:              # noqa: BLE001
        rec['error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
    rec['seconds'] = round(time.time() - t0, 3)
    return rec


def go_local(res):
    try:
        res.control_ren(pyvisa.constants.RENLineOperation.address_gtl)
        return 'sent GTL (front panel back to local)'
    except Exception as exc:              # noqa: BLE001
        return f'GTL not sent: {str(exc)[:80]}'


rm = pyvisa.ResourceManager()
say(f'Bench step 1 (READ-ONLY)  {RESULT["started"]}')
say(f'Python {RESULT["python"]} {RESULT["arch"]}, pyvisa {RESULT["pyvisa"]}, VISA library: {rm.visalib}')
try:
    found = list(rm.list_resources('?*'))
except Exception as exc:                  # noqa: BLE001
    found = [f'list failed: {exc}']
RESULT['visa_sees'] = found
say(f'VISA sees: {found}')
say('')
addresses = {key: ask_address(key, what, default) for key, what, default, _q in INSTRUMENTS}
RESULT['addresses'] = addresses

for key, what, _default, queries in INSTRUMENTS:
    address = addresses[key]
    entry = RESULT['instruments'][key] = {'what': what, 'address': address, 'records': []}
    say(f'\n=== {key}  {what}  at {address or "(skipped)"}')
    if not address:
        continue
    try:
        res = rm.open_resource(address)
    except Exception as exc:              # noqa: BLE001
        entry['open_error'] = str(exc)
        say(f'   could not open: {exc}')
        continue
    # line ends: commands end with LF only (no CR); the reply is read RAW so the real terminator (CR LF / LF / EOI only) is recorded
    res.write_termination = '\n'
    res.read_termination = None
    entry['status_byte_before'] = stb(res)
    say(f'   status byte (serial poll) before: {entry["status_byte_before"]}')
    for cmd, note in queries:
        rec = one_query(res, cmd, 4000)
        rec['note'] = note
        entry['records'].append(rec)
        shown = rec['reply'] if rec['error'] is None else 'NO REPLY - ' + rec['error']
        say(f'   {cmd if cmd is not None else "(talk only)":14} {repr(shown)[:150]}   [{rec["seconds"]} s]   {note}')
        time.sleep(0.2)
    entry['status_byte_after'] = stb(res)
    say(f'   status byte (serial poll) after: {entry["status_byte_after"]}')
    entry['local'] = go_local(res)
    say(f'   {entry["local"]}')
    res.close()

RESULT['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
with open('bench_step1_result.json', 'w', encoding='utf-8') as f:
    json.dump(RESULT, f, indent=1)
say('\nDone. Send back bench_step1_result.txt and bench_step1_result.json.')
