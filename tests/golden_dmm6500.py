"""Golden-transcript cases for the Keithley DMM6500 driver (drivers/keithley_dmm6500.py).  Not a test module.

Kept out of tests/golden_capture.py like tests/golden_5491b.py (it only registers COVERAGE and driver_cases).

THE REPLIES HERE ARE NOT RECORDED FROM A REAL DMM6500.  The bench-first workflow (NOTES.md) has not happened for this meter yet, so `FakeDmm6500` is a tiny stateful fake
that answers a query with what the matching write stored, in the most likely format, only to drive the driver down each branch.  Do not treat any reply format here as a
fact about the instrument; when the bench session has recorded real replies, replace this fake with a simulator that replays them.
"""
from __future__ import annotations

import re

from drivers import Transport, TransportError
from drivers.keithley_dmm6500 import KeithleyDMM6500

COVERAGE = {
    'KeithleyDMM6500': dict(
        covered=['connect', 'cleanup', 'configure_point', 'configure_temperature', 'range_ok', 'rel_is_on', 'acquire_reference', 'read', 'read_digitize', 'front_rear',
                 'check_errors', 'reset_to_defaults'],
        no_command=['bus']),                                            # property: derives from the transport
}


class FakeDmm6500(Transport):
    """Stateful fake: a query ':X:Y?' returns what ':X:Y <value>' stored (ON / OFF as 1 / 0, the function names quoted). UNVERIFIED reply formats."""
    name = 'FAKE::DMM6500'
    bus = 'USB'

    def __init__(self, reading='+1.000000E+00', digitize=(1.0, 1.001, 0.999, 1.0), errors=()):
        self.store, self.reading, self.digitize, self.errors = {}, reading, list(digitize), list(errors)
        self._pending = None
        self.opened = False

    def open(self): self.opened = True
    def close(self): self.opened = False
    def clear(self): pass
    def set_timeout(self, seconds): pass
    def go_local(self): pass

    def write(self, text):
        t = text.strip()
        self._pending = None
        if t == '*IDN?':
            self._pending = 'KEITHLEY INSTRUMENTS,MODEL DMM6500,04000000,1.7.12b'
        elif t == '*OPC?':
            self._pending = '1'
        elif t == ':SYST:ERR?':
            self._pending = self.errors.pop(0) if self.errors else '0,"No error"'
        elif t == ':ROUT:TERM?':
            self._pending = self.store.get('terminals', 'FRON')
        elif t == ':READ?':
            self._pending = self.reading
        elif t == ':READ:DIG?':
            self._pending = '+1.000000E+00'
        elif t.startswith(':TRAC:DATA?'):
            n = int(re.search(r'1,(\d+)', t).group(1))
            self._pending = ','.join(f'{self.digitize[i % len(self.digitize)]:.6E}' for i in range(n))
        elif t.endswith('?'):
            self._pending = self._answer(t[:-1])
        elif t in ('*RST', '*CLS'):
            if t == '*RST':
                self.store = {}
        else:
            key, _, value = t.partition(' ')
            self.store[key.upper()] = value.strip()

    def _answer(self, key):
        key = key.upper()
        value = self.store.get(key)
        if key == ':SENS:FUNC':
            return f'"{value}"' if value else '"VOLT:DC"'
        if key == ':SENS:DIG:FUNC':
            return f'"{value.strip(chr(34))}"' if value else 'NONE'
        if value is None:
            return {'COUN': '1'}.get(key.split(':')[-1], '0')
        if value in ('ON', 'OFF'):
            return '1' if value == 'ON' else '0'
        return value

    def read(self):
        if self._pending is None:
            raise TransportError('fake transport: nothing to read')
        rep, self._pending = self._pending, None
        return rep

    def query(self, text):
        self.write(text)
        return self.read()


def driver_cases(c):
    ft = FakeDmm6500()
    d = c.inst(KeithleyDMM6500, ft, opened=False, label='DMM6500')
    c.run('KeithleyDMM6500.connect', d.connect)
    c.run('KeithleyDMM6500.cleanup', d.cleanup)
    c.run('KeithleyDMM6500.reset_to_defaults', d.reset_to_defaults)
    points = [('DCV 10 V', dict(kind='DCV', range=10.0, plc=1)), ('ACV 1 V 1 kHz', dict(kind='ACV', range=1.0, ac_bandwidth=30)),
              ('DCI 100 mA', dict(kind='DCI', range=0.1, plc=1)), ('ACI 1 A', dict(kind='ACI', range=1.0)),
              ('OHM4 1 kohm ocomp', dict(kind='OHM4', range=1000.0, ocomp=True)), ('OHM4 1 Mohm no ocomp', dict(kind='OHM4', range=1e6, ocomp=False)),
              ('OHM2 100 Mohm', dict(kind='OHM2', range=1e8)), ('CAP 1 nF', dict(kind='CAP', range=1e-9)), ('FREQ', dict(kind='FREQ')),
              ('DIGV 100 mV', dict(kind='DIGV', range=0.1, srate=1000, count=100, aperture=0.001)), ('DIGI 1 A', dict(kind='DIGI', range=1.0, srate=1000, count=100)),
              ('TEMP TC J', dict(kind='TEMP', transducer='TC', tc_type='J')), ('TEMP 4-wire RTD', dict(kind='TEMP', transducer='FRTD', rtd='PT100')),
              ('TEMP 3-wire RTD', dict(kind='TEMP', transducer='TRTD', rtd='PT100'))]
    for tag, p in points:
        c.run(f'KeithleyDMM6500.configure_point[{tag}]', d.configure_point, p)
    c.run('KeithleyDMM6500.configure_point[unknown kind]', d.configure_point, dict(kind='DIODE', range=1.0))
    c.run('KeithleyDMM6500.configure_temperature[TC K]', d.configure_temperature, dict(transducer='TC', tc_type='K'))
    c.run('KeithleyDMM6500.rel_is_on[DCV]', d.rel_is_on, 'DCV')
    c.run('KeithleyDMM6500.acquire_reference[DCV]', d.acquire_reference, 'DCV')
    c.run('KeithleyDMM6500.rel_is_on[after REL]', d.rel_is_on, 'DCV')
    c.run('KeithleyDMM6500.read', d.read)
    ft.reading = '+9.90000E+37'
    c.run('KeithleyDMM6500.read[overflow]', d.read)
    ft.reading = '+1.000000E+00'
    c.run('KeithleyDMM6500.read_digitize', d.read_digitize)
    for tag, reply in (('exact', '1.0E+00'), ('1.2 x', '1.2'), ('10 x', '10')):
        c.run(f'KeithleyDMM6500.range_ok[{tag}]', KeithleyDMM6500.range_ok, reply, 1.0)
    c.run('KeithleyDMM6500.front_rear[FRONT]', d.front_rear)
    ft.store['terminals'] = 'REAR'
    c.run('KeithleyDMM6500.front_rear[REAR]', d.front_rear)
    c.run('KeithleyDMM6500.check_errors[ok]', d.check_errors, 'ctx')
    ft.errors.extend(['-113,"Undefined header"', '1131,"Parameter, measure range, expected value from 1 to 100000"'])
    c.run('KeithleyDMM6500.check_errors[two errors]', d.check_errors, 'configuring')
    wrong = c.inst(KeithleyDMM6500, _Wrong(), opened=False, label='DMM6500')
    c.run('KeithleyDMM6500.connect[wrong model]', wrong.connect)


class _Wrong(FakeDmm6500):
    def write(self, text):
        if text.strip() == '*IDN?':
            self._pending = 'KEYSIGHT,34401A,1,1'
        else:
            super().write(text)
