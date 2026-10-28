"""Raw GPIB probe for the 6060A bench (6060A, 8902A, 8563E). Sends ONLY harmless identify commands (ID / ID?). Nothing is set, no RF is switched.

Run on the lab PC:   python tools/probe_gpib_6060.py            (uses the default addresses 2, 14, 18 on every GPIB board it finds)
or                   python tools/probe_gpib_6060.py GPIB0::2::INSTR GPIB0::14::INSTR GPIB0::18::INSTR
It writes probe_gpib_result.txt next to where you run it. Send that file back.
"""
import sys
import time

try:
    import pyvisa
except ImportError:
    sys.exit('pyvisa is not installed (pip install pyvisa)')

out = open('probe_gpib_result.txt', 'w', encoding='utf-8')


def say(text=''):
    print(text)
    out.write(text + '\n')
    out.flush()


rm = pyvisa.ResourceManager()
say('pyvisa ' + pyvisa.__version__ + ', backend: ' + str(rm))
found = list(rm.list_resources('?*'))
say('Resources VISA can see: ' + repr(found))
args = sys.argv[1:]
import platform
say('Python ' + platform.python_version() + ', ' + platform.architecture()[0])
if not any(r.upper().startswith(('GPIB', 'TCPIP', 'USB')) for r in found):
    say('NOTE: this VISA library lists no GPIB / LAN / USB instrument at all, only serial ports. The suite uses the same library, so it cannot see the')
    say('instruments either. In Keysight Connection Expert, right-click each instrument > Copy VISA address, and run this script again with those addresses:')
    say('    python probe_gpib_6060.py "<6060A address>" "<8902A address>" "<8563E address>"')
if not args:
    boards = sorted({r.split('::')[0] for r in found if r.upper().startswith('GPIB')}) or ['GPIB0']
    args = [f'{b}::{a}::INSTR' for b in boards for a in (2, 14, 18)]
ASK = {2: 'ID', 14: 'ID', 18: 'ID?'}
for res_name in args:
    try:
        addr = int(res_name.split('::')[1])
    except Exception:
        addr = 0
    cmd = ASK.get(addr, 'ID?')
    say(f'\n=== {res_name}   asking {cmd!r}')
    try:
        res = rm.open_resource(res_name)
    except Exception as exc:
        say(f'  open failed: {exc}')
        continue
    res.timeout = 4000
    try:
        res.clear()
        say('  device clear sent')
    except Exception as exc:
        say(f'  device clear: {exc}')
    time.sleep(1.0)
    for wt in ('\n', '\r\n', '\r', ''):
        for rt in (None, '\n'):
            res.write_termination = wt
            res.read_termination = rt
            label = f'write_termination={wt!r:6} read_termination={rt!r:5}'
            try:
                res.write(cmd)
                time.sleep(0.2)
                raw = res.read_raw()
                say(f'  {label}: reply {raw!r}')
            except Exception as exc:
                say(f'  {label}: {type(exc).__name__}: {str(exc)[:90]}')
            time.sleep(0.3)
    try:
        say('  serial poll status byte: ' + repr(res.read_stb()))
    except Exception as exc:
        say(f'  serial poll: {str(exc)[:90]}')
    res.close()
say('\nDone.')
