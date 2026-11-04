"""Simulated Fluke 96270A in power-meter mode, linked to the simulated 6060A on the same bench, for tests and the procedure-modification dry run. No hardware.

It answers the commands drivers/reference_instruments.py sends for the SINE known state (INST / UNIT:POW / POW:OFFS / FREQ:OFFS / OUTP) and for the added power-meter subset (INST PMET,
UNIT:POW, PMET:TRIG / AVER / FREQ / IDN? / ZERO? / READ?). The reading is the level the simulated 6060A is outputting (drivers.simulated_6060a.rf_state) plus a small fixed, configurable
error; it is the sensor floor when RF is off or when the power meter has not been zeroed at the present frequency.

Frequency counter (added 2026-11-04, owner: the GIDEP frequency points on the 96270A counter): INST FCO, :FCO:RANG, :TRIG:GATE, :INIT:CONT, MEAS?, :ROSC:SOUR? and :ROSC:LOCK?.
Ranges 1 and 2 count the 6060A rear 10 MHz output (`ref_out_hz`), range 3 the 6060A RF output when RF is on and at least -2 dBm (0.5 V pk-pk into 50 ohm); otherwise MEAS? answers 9.91E37.
That the input follows the range is a SIMULATION choice (the real counter counts whatever is cabled to the rear BNC).

Simulation choices that are NOT facts about the real instrument or an R&S NRP40T: the sensor identity text, the floor (-90 dBm), the size of the error, that an un-zeroed sensor reads 0.5 dB
high at the floor. Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import re

from .simulated import SimBench, _SimBase
from .simulated_6060a import rf_state
from .transport import TransportError

FLOOR_DBM = -90.0


class Sim96270AMeter(_SimBase):
    def __init__(self, bench: SimBench, error_db=0.02, sensor='R&S,NRP40T,SIM100001,1.0'):
        super().__init__(bench, 'SIM-96270A')
        self.error_db = error_db
        self.sensor = sensor
        self.zero_reply = '0'               # PMET:ZERO? answer; '1' = failed
        self.sent = []
        self.zeroes = 0
        self.zero_with_rf_on = []           # True for every ZERO? asked while the 6060A output was on (a test failure: the sensor must be zeroed with RF removed)
        self.errors = []
        self.state = {'INST': 'SINE', 'UNIT': 'DBM', 'PMET:TRIG': 'SING', 'PMET:AVER': 'AUTO', 'PMET:FREQ': '1E6', 'OUTP': '0'}
        self.level_offset_db = {}           # frequency (Hz, as set with PMET:FREQ) -> extra error in dB at that frequency
        self.ref_out_hz = 10e6 * (1 + 0.3e-6)  # the 6060A rear 10 MHz IN/OUT (REF INT) the technician cables to the counter
        self.counter_ppm = 0.0002           # relative error of a counter reading (the 96270A is on the GPS 10 MHz)
        self.rosc = 'EXT'                   # ROSC:SOUR? reply; 'INT' = the 96270A on its own reference
        self.rosc_locked = '1'
        self.counter = {'RANG': '1', 'GATE': '2.0', 'CONT': '0'}

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self.sent.append(text.strip())
        self._reply = self.handle(text.strip())

    def handle(self, text):
        u = re.sub(r'^PMET\d:', 'PMET:', text.upper())          # PMET1: (what the driver sends since the bench of 2026-10-29) = PMET: (sensor 1 by default, manual p. 41)
        s = self.state
        if u == '*IDN?':
            return 'Fluke,96270A,SIM0001,1.0'
        if u == '*CLS':
            self.errors = []
            return None
        if u == '*RST':
            s.update({'INST': 'SINE', 'UNIT': 'DBM', 'PMET:TRIG': 'SING', 'PMET:AVER': 'AUTO', 'OUTP': '0'})
            return None
        if u == '*OPC?':
            return '1'
        if u == 'SYST:ERR?':
            return self.errors.pop(0) if self.errors else '0,"No error"'
        if u.startswith('INST '):
            name = u.split()[1]
            s['INST'] = 'PMETER' if name.startswith('PMET') else 'FM' if name == 'FM' else 'FCOUNTER' if name.startswith('FCO') else 'SINE'
            s['OUTP'] = '0'
            return None
        m = re.match(r'(FREQ|POW|FM:STAT|FM:DEV|FM:INT:FREQ)\s+(\S+)$', u)          # the FM instrument (Remote Programmers Manual p. 38 and the example p. 59); values are echoed as sent (Hz, dBm)
        if m:
            if s['INST'] != 'FM':
                self.errors.append('-221,"Settings conflict: FM instrument not selected"')
                return None
            s['FM_' + m.group(1)] = m.group(2)
            return None
        if u in ('FREQ?', 'POW?', 'FM:STAT?', 'FM:DEV?', 'FM:INT:FREQ?') and ('FM_' + u[:-1]) in s:
            return s['FM_' + u[:-1]]
        if u == 'OUTP ON':
            s['OUTP'] = '1'
            return None
        if u == 'INST?':
            return s['INST']
        if u.startswith('UNIT:POW '):
            s['UNIT'] = u.split()[1]
            return None
        if u == 'UNIT:POW?':
            return 'NONE' if s['INST'] == 'PMETER' else s['UNIT']        # bench 2026-10-29 step 5: NONE in power-meter mode
        if u in ('POW:OFFS:STAT 0', 'FREQ:OFFS:STAT 0'):
            return None
        if u in ('POW:OFFS:STAT?', 'FREQ:OFFS:STAT?'):
            return '0'
        if u == 'OUTP OFF':
            s['OUTP'] = '0'
            return None
        if u == 'OUTP?':
            return s['OUTP']
        if u == ':ROSC:SOUR?':
            return self.rosc
        if u == ':ROSC:LOCK?':
            return self.rosc_locked
        m = re.match(r':(FCO:RANG|TRIG:GATE|INIT:CONT)\s+(\S+)$', u)
        if m:
            if s['INST'] != 'FCOUNTER':
                self.errors.append('-221,"Settings conflict: frequency counter not selected"')
                return None
            key = {'FCO:RANG': 'RANG', 'TRIG:GATE': 'GATE', 'INIT:CONT': 'CONT'}[m.group(1)]
            self.counter[key] = m.group(2) if key != 'GATE' else str(min((0.2, 2.0, 20.0, 80.0), key=lambda g: abs(g - float(m.group(2)))))
            return None
        if u in (':FCO:RANG?', ':TRIG:GATE?', ':INIT:CONT?'):
            return self.counter[{':FCO:RANG?': 'RANG', ':TRIG:GATE?': 'GATE', ':INIT:CONT?': 'CONT'}[u]]
        if u == 'MEAS?' and s['INST'] == 'FCOUNTER':
            return self._count()
        m = re.match(r'PMET:(TRIG|AVER|FREQ)\s+(\S+)$', u)
        if m:
            s['PMET:' + m.group(1)] = m.group(2)
            if m.group(1) == 'FREQ':
                self.zeroed_at = None
            return None
        if u in ('PMET:TRIG?', 'PMET:AVER?', 'PMET:FREQ?'):
            return s[u[:-1]]
        if u == 'PMET:IDN?':
            return self.sensor
        if u == 'PMET:ZERO?':
            self.zeroes += 1
            self.zero_with_rf_on.append(bool(rf_state(self.bench)['rf_on']))
            if self.zero_reply == '1':
                self.errors.append('-221,"Settings conflict: sensor not zeroed"')
            else:
                self.zeroed_at = s['PMET:FREQ']
            return self.zero_reply
        if u == 'PMET:READ?':
            src = rf_state(self.bench)
            if not src['rf_on']:
                return f'{FLOOR_DBM:+.4E}'
            hz = float(s['PMET:FREQ'])
            level = src['amplitude_dbm'] + self.error_db + self.level_offset_db.get(hz, 0.0)
            if getattr(self, 'zeroed_at', None) != s['PMET:FREQ']:
                level += 0.5
            return f'{level:+.4E}'
        raise TransportError(f'simulated 96270A: unknown command {text!r}')

    zeroed_at = None

    def _count(self):
        if self.counter['RANG'] in ('1', '2'):
            hz = self.ref_out_hz
        else:
            src = rf_state(self.bench)
            if not src['rf_on'] or src['amplitude_dbm'] < -2.0 or not 50.5e6 < src['frequency_hz'] <= 310e6:
                return '9.91E+37'
            hz = src['frequency_hz']
        gate = float(self.counter['GATE'])
        res = 10 ** round(__import__('math').log10(max(hz / {0.2: 1e7, 2.0: 1e8, 20.0: 1e9, 80.0: 1e10}[gate], 1e-3)))      # about 8 / 9 / 10 / 11 digits (Product Specifications)
        value = round(hz * (1 + self.counter_ppm * 1e-6) / res) * res
        return f'{value:.11E}'


def make_pm_transport(bench):
    return Sim96270AMeter(bench)
