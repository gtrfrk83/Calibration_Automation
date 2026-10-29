"""Simulated Fluke 96270A in power-meter mode, linked to the simulated 6060A on the same bench, for tests and the procedure-modification dry run. No hardware.

It answers the commands drivers/reference_instruments.py sends for the SINE known state (INST / UNIT:POW / POW:OFFS / FREQ:OFFS / OUTP) and for the added power-meter subset (INST PMET,
UNIT:POW, PMET:TRIG / AVER / FREQ / IDN? / ZERO? / READ?). The reading is the level the simulated 6060A is outputting (drivers.simulated_6060a.rf_state) plus a small fixed, configurable
error; it is the sensor floor when RF is off or when the power meter has not been zeroed at the present frequency.

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
            s['INST'] = 'PMETER' if u.split()[1].startswith('PMET') else 'SINE'
            s['OUTP'] = '0'
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


def make_pm_transport(bench):
    return Sim96270AMeter(bench)
