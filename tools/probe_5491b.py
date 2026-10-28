#!/usr/bin/env python3
"""Raw serial probe for the B&K 5491B: sends *IDN? several ways and prints every byte the meter returns, with times.  Nothing here changes the meter's setup
(*IDN? only).  Run it with the suite CLOSED (the port must be free):

    python tools\\probe_5491b.py COM12            (add a baud rate as the second argument if it is not 9600)

Then copy everything it prints and send it back.  This is a diagnostic, not part of any procedure."""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit('pyserial is not installed:  pip install pyserial')


def listen(ser, seconds, t0):
    got = bytearray()
    end = time.time() + seconds
    last = None
    while time.time() < end:
        b = ser.read(1)
        if b:
            got += b
            last = time.time()
            end = max(end, last + 0.6)             # keep listening while bytes keep coming
    return bytes(got)


def show(label, data, t0):
    print(f'  {label}: {len(data)} byte(s)  {data!r}   hex {data.hex(" ")}')


def run(port, baud, dtr, rts):
    print(f'\n=== {port} {baud} 8N1  DTR={dtr} RTS={rts}')
    ser = serial.Serial(port, baudrate=baud, bytesize=8, parity='N', stopbits=1, timeout=0.2, write_timeout=2)
    ser.dtr = dtr
    ser.rts = rts
    time.sleep(1.0)
    ser.reset_input_buffer()
    t0 = time.time()
    tests = [('bulk  *IDN?<LF>', b'*IDN?\n', False), ('bulk  *IDN?<CR>', b'*IDN?\r', False), ('bulk  *IDN?<CR><LF>', b'*IDN?\r\n', False),
             ('char-by-char *IDN? then <LF>', b'*IDN?\n', True), ('char-by-char *IDN? then <CR>', b'*IDN?\r', True)]
    for label, data, per_char in tests:
        ser.reset_input_buffer()
        time.sleep(0.5)
        print(f'- {label}')
        got = bytearray()
        if per_char:
            for ch in data[:-1]:
                ser.write(bytes([ch]))
                e = ser.read(1)
                got += e
                if e != bytes([ch]):
                    print(f'  echo of {bytes([ch])!r} was {e!r}')
            ser.write(data[-1:])
        else:
            ser.write(data)
        got += listen(ser, 4.0, t0)
        show('received', bytes(got), t0)
        time.sleep(1.0)
    ser.close()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    for dtr, rts in ((True, True), (False, False)):
        try:
            run(port, baud, dtr, rts)
        except Exception as exc:
            print('FAILED:', exc)


if __name__ == '__main__':
    main()
