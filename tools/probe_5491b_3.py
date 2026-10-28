#!/usr/bin/env python3
"""Third raw probe for the B&K 5491B: how it takes a RANGE setting.  Sends FUNC, autorange OFF, several RANGE values and reads RANGE? and the error queue after each.
It changes the meter's function / range settings only (the suite's own start does the same, and *RST at the end puts the defaults back).  Run it with the suite CLOSED:

    python probe_5491b_3.py COM12 > probe3_result.txt

then send probe3_result.txt back.  A diagnostic only, not part of any procedure."""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit('pyserial is not installed:  pip install pyserial')


def listen(ser, seconds=1.5):
    got = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        b = ser.read(1)
        if b:
            got += b
            end = max(end, time.time() + 0.6)
    return bytes(got)


def cmd(ser, text, wait=0.3):
    """One command, one character at a time (each echo awaited), end character last; returns what came back after the echo."""
    ser.reset_input_buffer()
    bad = ''
    for ch in text.encode():
        ser.write(bytes([ch]))
        e = ser.read(1)
        if e != bytes([ch]):
            bad += f' [echo of {bytes([ch])!r} was {e!r}]'
    ser.write(b'\n')
    echo_end = ser.read(1)
    rest = listen(ser, 1.5)
    time.sleep(wait)
    return (bad + (f' [end echo {echo_end!r}]' if echo_end != b'\n' else '')), rest


def show(ser, text, wait=0.3):
    bad, rest = cmd(ser, text, wait)
    print(f'  {text:28s} -> {rest!r}{bad}')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ser = serial.Serial(sys.argv[1], baudrate=int(sys.argv[2]) if len(sys.argv) > 2 else 9600, bytesize=8, parity='N', stopbits=1, timeout=0.2, write_timeout=2)
    ser.dtr = ser.rts = True
    time.sleep(1.0)
    show(ser, '*IDN?')
    print('\n--- DC volts')
    for t in ('FUNC VOLT:DC', 'FUNC?', 'VOLT:DC:RANG:AUTO OFF', 'VOLT:DC:RANG:AUTO?', 'VOLT:DC:RANG?'):
        show(ser, t)
    for v in ('0.49', '0.5', '5', '4.9', '0.2', '2', '50', '1000'):
        show(ser, f'VOLT:DC:RANG {v}', 0.6)
        show(ser, 'VOLT:DC:RANG?')
        show(ser, 'VOLT:DC:RANG:UPP?')
        show(ser, 'SYST:ERR?')
    print('\n--- DC volts, other spellings')
    for t in ('VOLT:DC:RANG:UPP 5', 'VOLT:DC:RANG?', ':VOLT:DC:RANG 5', 'VOLT:DC:RANG?', 'VOLT:DC:RANG 5.0', 'VOLT:DC:RANG?', 'VOLT:DC:RANG +5E+00', 'VOLT:DC:RANG?', 'SYST:ERR?'):
        show(ser, t, 0.6)
    print('\n--- resistance and DC current')
    for t in ('FUNC RES', 'FUNC?', 'RES:RANG:AUTO OFF', 'RES:RANG 4900', 'RES:RANG?', 'SYST:ERR?', 'FUNC CURR:DC', 'FUNC?', 'CURR:DC:RANG:AUTO OFF', 'CURR:DC:RANG 0.0049', 'CURR:DC:RANG?', 'SYST:ERR?'):
        show(ser, t, 0.6)
    print('\n--- back to defaults')
    show(ser, '*RST', 6.0)
    show(ser, 'FUNC?')
    ser.close()


if __name__ == '__main__':
    main()
