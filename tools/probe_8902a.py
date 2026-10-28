"""Raw probe of the HP 8902A frequency measurement (nothing is sent to any other instrument).

BEFORE you run it, on the 6060A front panel set: frequency 111.1111 MHz, level -10 dBm, RF ON, and connect its RF OUTPUT to the 8902A RF INPUT
(through the 11722A sensor module if you normally use it).

Run:   python probe_8902a.py "<8902A VISA address>"          e.g.  python probe_8902a.py GPIB0::14::INSTR
It writes probe_8902a_result.txt next to where you run it; send that file back. It takes about 3 minutes. While it runs, WATCH THE 8902A DISPLAY and
write down what it shows during each numbered test (the script pauses after each test so you can type it in).
"""
import sys
import time

import pyvisa

if len(sys.argv) < 2:
    sys.exit('usage: python probe_8902a.py "<8902A VISA address>"')
out = open('probe_8902a_result.txt', 'w', encoding='utf-8')


def say(text=''):
    print(text)
    out.write(text + '\n')
    out.flush()


rm = pyvisa.ResourceManager()
res = rm.open_resource(sys.argv[1])
res.timeout = 15000
res.write_termination = '\n'
res.read_termination = '\n'


def stb():
    try:
        return res.read_stb()
    except Exception as exc:                                  # noqa: BLE001
        return f'poll failed: {str(exc)[:60]}'


def send(cmd, wait=0.3):
    res.write(cmd)
    say(f'   sent {cmd!r}')
    time.sleep(wait)


def read_one(label):
    t0 = time.time()
    try:
        raw = res.read_raw()
        say(f'   reply after {time.time() - t0:.1f} s: {raw!r}')
    except Exception as exc:                                  # noqa: BLE001
        say(f'   NO REPLY after {time.time() - t0:.1f} s: {str(exc)[:80]}')
    say(f'   status byte now: {stb()}')


def preset():
    res.clear()
    send('IP', 4.0)
    say(f'   status byte after IP: {stb()}  (read twice: {stb()})')


TESTS = [
    ('1  M5, 7.1SP, T1, T3 (what the procedure sends, no tune)', ['M5', '7.1SP', 'T1', 'T3']),
    ('2  AU (automatic tune), M5, 7.1SP, T1, T3', ['AU', 'M5', '7.1SP', 'T1', 'T3']),
    ('3  111.1111MZ, M5, T1, T3 (manual tune, no resolution code)', ['111.1111MZ', 'M5', 'T1', 'T3']),
    ('4  M5, T3 only', ['M5', 'T3']),
    ('5  M5, T0 (free run) then read', ['M5', 'T0']),
    ('6  AU, M5, T2 (trigger without settling)', ['AU', 'M5', 'T2']),
]
say(f'Resource {sys.argv[1]}')
for title, cmds in TESTS:
    say(f'\n=== TEST {title}')
    preset()
    for c in cmds:
        send(c)
    say(f'   status byte before reading: {stb()}')
    read_one(title)
    seen = input(f'TEST {title.split()[0]}: what does the 8902A DISPLAY show now? (type it, Enter) ')
    say(f'   DISPLAY: {seen}')
say('\nDone.')
res.close()
