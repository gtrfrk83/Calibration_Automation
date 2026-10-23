"""Simulated Fluke 8808A (and a calibrator that enforces a few 5522A output limits), for tests with no hardware.

The 8808A simulator speaks the command strings of drivers/fluke_8808a.py. It "measures" what the simulated calibrator of drivers/simulated.py is
outputting (bench.fluke), but only when the meter is set up the way that signal needs: the function must match the output (volts / amps / ohms,
DC needs an explicit 0 Hz, AC a frequency), the range must hold the value, otherwise it returns the overload reading, as a real meter would.

Simulation choices that are NOT facts about the real meter: the *RST format (2), the settle behaviour, the reading gain errors and the 5522A error text.
Prompt modes (what the manual says: prompts and echo only while Echo is on, pp. 4-3 and 4-6; what a real bench showed: a '=>' after *RST although Echo
had been set off): `sim.echo = True` = Echo ON (every command is echoed on its own line and a prompt follows its reply); `sim.prompts = True` = prompts
without echo; `Sim8808ATransport(..., prompts_after_reset=True)` = Echo OFF, but the *RST turns prompts on (the reset's own prompt, the optional `banner`
and every later command's prompt). A prompt is '=>' (ok), '?>' (command error: unknown command, bad syntax) or '!>' (execution error). `clear()` throws
the unread output away, like a serial input flush. None of this is a statement about when the real meter does it.
Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import re

from .fluke_8808a import OVERLOAD, RANGES
from .simulated import SimBench, SimFlukeTransport, _SimBase
from .transport import TransportError

QYE, DDE, EXE, CME, PON, OPC = 0x04, 0x08, 0x10, 0x20, 0x80, 0x01
FUNC_KIND = {'VDC': 'DCV', 'VAC': 'ACV', 'ADC': 'DCI', 'AAC': 'ACI', 'OHMS': 'OHM2', 'FREQ': 'FREQ'}
GAIN = {'VDC': 1.00002, 'VAC': 1.00004, 'ADC': 1.00003, 'AAC': 1.00005, 'OHMS': 1.00001, 'FREQ': 1.0000002}


class Sim8808ATransport(_SimBase):
    """RS-232 8808A. Default: echo off, no prompts (the manual's factory state). See the module docstring for the prompt modes."""

    def __init__(self, bench, serial='SIM0001', prompts_after_reset=False, banner=None):
        super().__init__(bench, 'SIM-8808A')
        self.serial = serial
        self.esr = PON
        self.remote = False
        self.sent = []
        self.echo = False                    # Echo ON: commands are echoed and prompts follow
        self.prompts = False                 # prompts without echo
        self.prompts_after_reset = prompts_after_reset
        self.banner = banner                 # an extra line the reset sends (None: none)
        self.out = []                        # unread output lines: (kind, text), kind in reply / prompt / echo / stray
        self.cleared = 0
        self._err = None
        self.reset_state(first=True)

    def reset_state(self, first=False):
        self.func, self.wire, self.auto, self.range_no, self.rate, self.trigger = 'VDC', 4, True, 1, 'S', 1
        self.format = 2                      # simulation choice: the real power-up format is not listed in the manual (Table 3-9)
        self.range_no = 1
        if not first:
            self.esr |= PON

    # ---- helpers
    def _table(self):
        kind = 'OHM2' if self.func == 'OHMS' else FUNC_KIND[self.func]
        return RANGES[kind]

    def _signal(self):
        """(value, ok): what the calibrator outputs as this function sees it. ok False -> overload."""
        f = self.bench.fluke
        ext = getattr(self.bench, 'external', None)      # a standard the operator has connected instead of the calibrator: (unit, value, hertz)
        if ext is not None:
            unit, value, freq = ext
        elif not f['operate']:
            return 0.0, True
        else:
            unit, value, freq = f.get('unit', 'V'), f['volts'], f['freq']
        fn = self.func
        if fn in ('VDC', 'ADC'):
            return (value, unit == ('V' if fn == 'VDC' else 'A') and freq == 0)
        if fn in ('VAC', 'AAC'):
            return (value, unit == ('V' if fn == 'VAC' else 'A') and freq > 0)
        if fn == 'OHMS':
            return (value, unit == 'OHM')
        return (freq, unit == 'V' and freq > 0)         # FREQ

    def _reading(self):
        value, ok = self._signal()
        table = self._table()
        rng = table[min(self.range_no, len(table)) - 1]
        if not ok or abs(value) > rng * 1.0:
            return OVERLOAD
        res = rng / (100000.0 if str(rng).lstrip('0.').startswith(('1', '7')) else 200000.0)
        v = value * GAIN[self.func]
        v = round(v / res) * res
        return v + 0.0

    @staticmethod
    def _text(v):
        return f'{v:+.6E}'

    # ---- bus
    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        if any(k == 'reply' for k, _t in self.out):          # a new command line while a reply was pending: query error, the reply is lost
            self.esr |= QYE
            self.out = [(k, t) for k, t in self.out if k != 'reply']
        self._err = None
        reply = self.handle(text.strip())
        if self.echo:
            self.out.append(('echo', text.strip()))
        if reply is not None:
            self.out.append(('reply', reply))
        if self.echo or self.prompts:
            self.out.append(('prompt', self._err or '=>'))

    def read(self):
        if not self.out:
            raise TransportError('simulated read timed out (no pending reply)')
        return self.out.pop(0)[1]

    def clear(self):
        self.out = []
        self.cleared += 1

    @property
    def _reply(self):                        # kept for the older tests: the first unread reply line, if any
        return next((t for k, t in self.out if k == 'reply'), None)

    @_reply.setter
    def _reply(self, value):                 # _SimBase.__init__ sets it; the queue is the state here
        pass

    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        if u == '*IDN?':
            return f'FLUKE, 8808A, {self.serial}, 1.0 D1.0'
        if u == '*CLS':
            self.esr = 0
            return None
        if u == '*RST':
            self.reset_state()
            if self.prompts_after_reset:
                self.prompts = True
                if self.banner:
                    self.out.append(('stray', self.banner))
            return None
        if u == '*OPC?':
            return '1'
        if u == '*ESR?':
            value, self.esr = self.esr, 0
            return str(value)
        if u == '*STB?':
            return '0'
        if u in ('REMS', 'RWLS'):
            self.remote = True
            return None
        if u in ('LOCS', 'LWLS'):
            self.remote = False
            return None
        if u in FUNC_KIND:
            self.func, self.auto, self.range_no = u, True, 1
            return None
        if u in ('WIRE2', 'WIRE4'):
            if self.func != 'OHMS':
                self.esr |= EXE
                self._err = '!>'
                return None
            self.wire = int(u[-1])
            return None
        if u == 'FUNC1?':
            return self.func
        if u == 'FIXED':
            self.auto = False
            return None
        if u == 'AUTO':
            self.auto = True
            return None
        if u == 'AUTO?':
            return '1' if self.auto else '0'
        m = re.fullmatch(r'RANGE\s+(\d+)', u)
        if m:
            n = int(m.group(1))
            if not 1 <= n <= len(self._table()):
                self.esr |= EXE
                self._err = '!>'
                return None
            self.range_no, self.auto = n, False
            return None
        if u == 'RANGE1?':
            return str(self.range_no)
        m = re.fullmatch(r'RATE\s+([SMF])', u)
        if m:
            self.rate = m.group(1)
            return None
        if u == 'RATE?':
            return self.rate
        m = re.fullmatch(r'FORMAT\s+([12])', u)
        if m:
            self.format = int(m.group(1))
            return None
        if u == 'FORMAT?':
            return str(self.format)
        m = re.fullmatch(r'TRIGGER\s+(\d)', u)
        if m:
            self.trigger = int(m.group(1))
            return None
        if u == 'TRIGGER?':
            return str(self.trigger)
        if u == 'SERIAL?':
            return self.serial
        if u in ('MEAS1?', 'VAL1?'):
            if self.format != 1:
                return f'{self._reading():+.4f}'          # not the E notation the driver requires: the driver must set FORMAT 1
            return self._text(self._reading())
        self.esr |= CME                                    # unknown command
        self._err = '?>'
        return None

    def query(self, text):
        self.write(text)
        return self.read()


class Sim5522ALimitsTransport(SimFlukeTransport):
    """A simulated 5522A that refuses the outputs it cannot make (5522A Operators Manual, Detailed Specifications): ac volts above 330 V only up to
    10 kHz, ac current of 3 A and above only from 45 Hz to 5 kHz, ac output above 500 kHz. The refusal is an entry in the error queue (ERR?) and the
    output is not changed, like the rejected command the real calibrator reports."""

    def _handle(self, cmd):
        m = re.match(r'OUT\s+([-+0-9.eE]+)(V|A|OHM)(?:,\s*([0-9.]+)\s*(HZ|KHZ|MHZ))?$', cmd.strip().upper())
        if m and m.group(3):
            value = abs(float(m.group(1)))
            hz = float(m.group(3)) * {'HZ': 1, 'KHZ': 1e3, 'MHZ': 1e6}[m.group(4)]
            unit = m.group(2)
            bad = (hz > 500e3) or (unit == 'V' and value >= 330 and hz > 10e3) or (unit == 'A' and value >= 3 and (hz < 45 or hz > 5e3) and hz > 0)
            if bad:
                self.errors = getattr(self, 'errors', []) + ['-222,"Data out of range"']
                return None
        return super()._handle(cmd)


def make_8808a_bench(cal='5522A', enforce_cal_limits=True):
    """(bench, calibrator transport, 8808A transport)."""
    bench = SimBench()
    if enforce_cal_limits and cal == '5522A':
        cal_t = Sim5522ALimitsTransport(bench, cal)
    elif enforce_cal_limits and cal == '5520A':
        from .simulated_5520a import Sim5520ALimitsTransport          # refuses what the 5520A specification sheet does not publish (calibrator_fit)
        cal_t = Sim5520ALimitsTransport(bench, cal)
    else:
        cal_t = SimFlukeTransport(bench, cal)
    return bench, cal_t, Sim8808ATransport(bench)
