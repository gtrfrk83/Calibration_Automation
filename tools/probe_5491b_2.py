#!/usr/bin/env python3
"""Second raw probe for the B&K 5491B: how the meter answers  TRIG:SOUR?  alone, after a set command, and after *RST, with different waits.  It sends *RST (the meter returns
to its defaults, as the suite's own start does), TRIG:SOUR IMM and the queries TRIG:SOUR? and SYST:ERR?.  Run it with the suite CLOSED:

    python probe_5491b_2.py COM12 > probe2_result.txt

then send probe2_result.txt back.  A diagnostic only, not part of any procedure."""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit('pyserial is not installed:  pip install pyserial')

T0 = time.time()


def listen(ser, seconds):
    got, stamps = bytearray(), []
    end = time.time() + seconds
    while time.time() < end:
        b = ser.read(1)
        if b:
            got += b
            stamps.append(round(time.time() - T0, 2))
            end = max(end, time.time() + 0.8)
    return bytes(got), stamps


def send(ser, text, per_char, label):
    ser.reset_input_buffer()
    got = bytearray()
    t_send = time.time() - T0
    if per_char:
        for ch in text.encode() + b'\n':
            ser.write(bytes([ch]))
            if ch != 10:
                e = ser.read(1)
                got += e
                if e != bytes([ch]):
                    got += b'<echo of %r was %r>' % (bytes([ch]), e)
            else:
                pass
    else:
        ser.write(text.encode() + b'\n')
    rest, stamps = listen(ser, 3.0)
    got += rest
    print(f'[{t_send:6.2f}s] {label:44s} sent {text!r:18} ({"per char" if per_char else "bulk"}) -> {bytes(got)!r}   last byte at {stamps[-1] if stamps else "-"}s')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    ser = serial.Serial(port, baudrate=baud, bytesize=8, parity='N', stopbits=1, timeout=0.2, write_timeout=2)
    ser.dtr = True
    ser.rts = True
    time.sleep(1.0)
    for per_char in (False, True):
        print(f'\n=== {"per character" if per_char else "bulk"}')
        send(ser, 'TRIG:SOUR?', per_char, 'query alone')
        time.sleep(1.0)
        send(ser, '*RST', per_char, 'reset')
        time.sleep(6.0)
        send(ser, 'TRIG:SOUR?', per_char, 'query 6 s after *RST')
        for gap in (0.2, 1.0, 3.0):
            time.sleep(1.0)
            send(ser, 'TRIG:SOUR IMM', per_char, 'set')
            time.sleep(gap)
            send(ser, 'TRIG:SOUR?', per_char, f'query {gap} s after the set')
        time.sleep(1.0)
        send(ser, 'SYST:ERR?', per_char, 'error queue')
    ser.close()


if __name__ == '__main__':
    main()
