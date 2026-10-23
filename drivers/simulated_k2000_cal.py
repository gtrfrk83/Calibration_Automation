"""Simulated Keithley Model 2000 WITH its calibration interface (:CAL:PROT:...), for the guided adjustment procedure's demo mode and its tests.

It extends the verification simulator (drivers/simulated_k2000.py, unchanged) with what drivers/keithley_2000_cal.py sends:

  * a lock state (locked at power-up and after :LOCK), a code that is SIM_CODE (NOT any real code), :INIT, :COUNt?, :DATE / :NDUE (+ queries),
  * every DC / AC step of the manual (Tables 2-8 to 2-12) with the firmware numbering of Table 3-1's note (firmware 'A20' or 'A19'),
  * a check that the simulated calibrator is in OPERATE and outputting what the step needs (within 10 %): otherwise the step queues the matching Table B-1 error,
  * TEMPORARY constants (written by each step) and SAVED constants (copied by :SAVE only), so a test can prove that an aborted adjustment leaves the saved constants alone;
    `power_cycle()` drops the temporary ones, as a power cycle would on the real meter (UNVERIFIED on the real meter),
  * :SAVE fails with +438 / +439 when the dates were not set (Table B-1).

Reply formats of the calibration queries follow the manual's description ("0 locked, 1 unlocked", "<year>, <month>, <day>"); how the real meter reacts to a wrong code is NOT
stated by the manual: the simulator stays locked and queues nothing.  Test hooks: .fail_steps {step id: error number}, .short_ok (False = the low-thermal short is not
connected), .hang_opc (the next *OPC? never answers), .saved / .temp / .count, .power_cycle().

    bench, cal_t, dmm_t = make_k2000_cal_bench('5522A', bus='GPIB', firmware='A20')
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .simulated import SimBench
from .simulated_k2000 import SimFlukeComp, SimK2000Transport
from .transport import TransportError

SIM_CODE = 'SIMCODE1'                       # the code the SIMULATED meter accepts; not a real instrument code
SPEC = Path(__file__).resolve().parent.parent / 'specs' / 'keithley_2000_adjustment.json'
TOLERANCE = 0.10                            # the calibrator must be within 10 % of the step's nominal (the manual's parameter ranges are +/- 10 %)
UNIT = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'OHM'}
ERROR_FOR = {'D01': 400, 'D02': 411, 'D03': 402, 'D04': 403, 'D05': 404, 'D06': 416, 'D07': 417, 'D08': 418, 'D09': 419, 'D10': 420, 'D11': 423, 'D12': 424, 'D13': 425}


def _steps():
    return json.loads(SPEC.read_text(encoding='utf-8'))['steps']


class SimK2000CalTransport(SimK2000Transport):
    """The simulated 2000 with calibration."""

    def __init__(self, bench, bus='GPIB', firmware='A20'):
        super().__init__(bench, bus)
        self.firmware = firmware
        self.steps = _steps()
        self.errors_text = {int(k): v for k, v in json.loads(SPEC.read_text(encoding='utf-8'))['errors'].items()}
        self.locked = True
        self.initiated = False
        self.code_sent = 0
        self.saved, self.temp = {}, {}
        self.count = 7
        self.date = self.ndue = None
        self.fail_steps = {}
        self.short_ok = True
        self.hang_opc = False
        self.cal_sent = []                   # every :CAL:PROT command received, in order (the code is not recorded)

    def power_cycle(self):
        """The temporary constants are lost (UNVERIFIED on the real meter); the saved ones stay; the lock closes."""
        self.temp = {}
        self.locked, self.initiated = True, False
        self._power_up()

    # ---- helpers
    def _queue(self, number):
        self._push(f'+{number},"{self.errors_text.get(number, "calibration error")}"')

    def _find(self, scope, number):
        for s in self.steps:
            if s['scope'] == scope and (s['a19'] if self.firmware == 'A19' else s['a20']) == number:
                return s
        return None

    def _calibrator_matches(self, s):
        src = s['source']
        f = self.bench.fluke
        if not f['operate']:
            return False
        want = float(src['value'])
        if f.get('unit', 'V') != UNIT[src['kind']]:
            return False
        ac = src['kind'] in ('ACV', 'ACI')
        if ac != bool(f['freq']):
            return False
        if ac and abs(f['freq'] - float(src['frequency'])) > 1e-6 * float(src['frequency']):
            return False
        return abs(float(f['volts']) - want) <= TOLERANCE * abs(want)

    def handle(self, cmd):
        u = cmd.strip().upper()
        if u == '*IDN?':
            return f'KEITHLEY INSTRUMENTS INC.,MODEL 2000,0SIM0001,{self.firmware}  /A02'
        if u == '*OPC?' and self.hang_opc:
            self.hang_opc = False
            raise TransportError('simulated read timed out (no pending reply)')
        if u.startswith(':CAL:PROT:') or u.startswith('CAL:PROT:'):
            self.sent.append(cmd.strip() if 'CODE' not in u else ':CAL:PROT:CODE <masked>')
            return self._cal(cmd.strip())
        return super().handle(cmd)

    # ---- the calibration commands
    def _cal(self, cmd):
        m = re.match(r"^:?CAL:PROT:CODE\s+'(.*)'$", cmd, re.I)
        if m:
            self.code_sent += 1
            if m.group(1) == SIM_CODE:
                self.locked = False
            return None
        u = cmd.upper().lstrip(':')
        node = u[len('CAL:PROT:'):]
        self.cal_sent.append(node)
        if node == 'LOCK?':
            return '0' if self.locked else '1'
        if node == 'COUN?':
            return str(self.count)
        if node == 'DATE?':
            return f'{self.date.year}, {self.date.month}, {self.date.day}' if self.date else '1994, 1, 1'
        if node == 'NDUE?':
            return f'{self.ndue.year}, {self.ndue.month}, {self.ndue.day}' if self.ndue else '1994, 1, 1'
        if self.locked:
            self._push('-203,"Command protected"')
            return None
        if node == 'LOCK':
            self.locked, self.initiated = True, False
            return None
        if node == 'INIT':
            self.initiated = True
            return None
        m = re.match(r'^(DATE|NDUE)\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)$', node)
        if m:
            try:
                d = date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            except ValueError:
                self._push('-222,"Data out of range"')
                return None
            setattr(self, 'date' if m.group(1) == 'DATE' else 'ndue', d)
            return None
        if not self.initiated:
            self._push('-221,"Settings conflict"')
            return None
        if node == 'SAVE':
            if self.date is None:
                self._queue(438)
                return None
            if self.ndue is None:
                self._queue(439)
                return None
            self.saved = dict(self.temp)
            self.count += 1
            return None
        m = re.match(r'^(DC|AC):STEP(\d+)(?:\s+(\S+))?$', node)
        if not m:
            self._push('-113,"Undefined header"')
            return None
        scope, n, arg = m.group(1), int(m.group(2)), m.group(3)
        s = self._find(scope, n)
        if s is None:
            self._push('-113,"Undefined header"')
            return None
        if s['id'] in self.fail_steps:
            self._queue(self.fail_steps[s['id']])
            return None
        if s['source'] is None:                                  # short / open
            if s['id'] == 'D01' and not self.short_ok:
                self._queue(ERROR_FOR['D01'])
                return None
            self.temp[s['id']] = {'param': None}
            return None
        p = s['param']
        if p is not None:
            if arg is None:
                self._push('-109,"Missing parameter"')
                return None
            value = float(arg)
            if not (float(p['lo']) <= value <= float(p['hi'])):
                self._push('-222,"Data out of range"')
                return None
        elif arg is not None:
            self._push('-108,"Parameter not allowed"')
            return None
        if not self._calibrator_matches(s):
            self._queue(ERROR_FOR.get(s['id'], 456))
            return None
        self.temp[s['id']] = {'param': None if arg is None else float(arg)}
        return None


def make_k2000_cal_bench(cal='5522A', bus='GPIB', firmware='A20'):
    """(bench, calibrator transport, Model 2000 transport)."""
    bench = SimBench()
    return bench, SimFlukeComp(bench, cal), SimK2000CalTransport(bench, bus, firmware)
