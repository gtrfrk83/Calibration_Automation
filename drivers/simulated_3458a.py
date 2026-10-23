"""Simulated Keysight 3458A (HP Multimeter Language over GPIB) for tests and demo runs with no hardware.

It speaks the command strings drivers/agilent_3458a.py sends and "measures" a configurable applied source:

    bench, cal_t, dmm_t = make_3458a_bench('5522A')
    dmm_t.apply('DCI', 1.0e-3)                  # an applied 1 mA DC current (dmm_t.applied = {'DCV': ..., 'ACI': ..., 'OHM': ...} for several at once)

An applied value is looked up for the selected function (DCV ACV ACDCV OHM OHMF DCI ACI ACDCI); if none was applied, the simulated calibrator of the bench is read
(its unit must match the function: V, A or OHM; DC = 0 Hz, AC = a frequency) and with nothing applied the meter reads only its small offset (a short or an open input).
The reading is value x gain + offset (a few ppm of gain, a fixed offset per function), reported as +-1E+38 when it does not fit the selected range's full scale.

What it models of the real meter (from the User's Guide): RESET restores the power-on state (END OFF, OFORMAT ASCII, NPLC 10, TRIG AUTO, DCV autorange) and clears the error
registers; TRIG SYN gives a reading for every bus read, TRIG SGL gives one reading per TRIG SGL, TRIG HOLD gives none (the read times out); MATH NULL loads the OFFSET
register with the next reading; OFORMAT SREAL / DREAL deliver 4 / 8 bytes (most significant first) with no line end; STB? answers the status byte; ACAL blocks the bus
for the guide's duration: a transport timeout shorter than that makes the write time out (enforce_acal_timeout); query replies are always ASCII.

What it does NOT know (simulation choices, listed as UNVERIFIED in NOTES.md): the exact layout of the numeric replies (ranges are reported as the nominal range or the
full scale: `range_reports`), the ERRSTR? numbering (100 + the error bit), the temperature, and anything about timing.  Keep this file out of any evidence: nothing here
is calibration data.

Test hooks: dmm_t.sent, .errors, .gain, .offsets, .applied, .range_reports ('nominal' | 'full'), .drop_readings, .security_code, .acal_runs, .enforce_acal_timeout, .terminals,
.idn_text ('HP3458A' for older firmware), .temperature, .calnum.
"""
from __future__ import annotations

import re

from .agilent_3458a import ACAL_SECONDS, ACAL_TYPES, ENUMS, FUNC_NUM, RANGES, encode_reading, select_range
from .base import InstrumentError
from .simulated import SimBench, _SimBase
from .simulated_k2000 import SimFlukeComp
from .transport import TransportError

SOURCE = {'DCV': ('V', False), 'ACV': ('V', True), 'ACDCV': ('V', None), 'OHM': ('OHM', None), 'OHMF': ('OHM', None),
          'DCI': ('A', False), 'ACI': ('A', True), 'ACDCI': ('A', None)}
NAME_OF = {v: k for k, v in FUNC_NUM.items()}
OVERLOAD = 1.0e38
PON, ERR_BIT, DATA = 8, 32, 128                       # status byte bits that matter here (UG p. 358)


def _num_text(value: float) -> str:
    return f'{value:+.8E}'


class Sim3458ATransport(_SimBase):
    """The simulated 3458A (GPIB)."""
    idn_text = 'Keysight 3458A'
    rev_text = '9,2'

    def __init__(self, bench, strict=True):
        super().__init__(bench, 'SIM-3458A')
        self.bus = 'GPIB'
        self.strict = strict                                       # False: an unknown command is queued as a syntax error instead of raising
        self.sent = []
        self.errors = []                                           # [(code, message)]
        self.applied = {}
        self.gain = {f: 1.000002 for f in FUNC_NUM}
        self.offsets = {'DCV': 4e-7, 'ACV': 0.0, 'ACDCV': 0.0, 'OHM': 5e-4, 'OHMF': 5e-4, 'DCI': 2e-9, 'ACI': 0.0, 'ACDCI': 0.0}
        self.range_reports = 'nominal'
        self.drop_readings = False
        self.enforce_acal_timeout = True
        self.security_code = None
        self.acal_runs = []
        self.temperature = 38.9
        self.calnum = 12
        self.timeout = 10.0
        self.terminals = 'FRONT'
        self.read_termination = None
        self.stb = PON
        self._queue = []                                           # readings waiting on the bus (bytes or text)
        self._power_up()

    # ---- state -------------------------------------------------------------------------------------------------------------------------
    def _power_up(self):
        self.func = 'DCV'
        self.nominal = {f: RANGES[f][-1][0] for f in FUNC_NUM}
        self.auto = 1
        self.nplc, self.aper = 10.0, None
        self.ndig = 7
        self.trig, self.tarm = 'AUTO', 'AUTO'
        self.nrdgs = (1, 'AUTO')
        self.end, self.oformat, self.qformat = 'OFF', 'ASCII', 'NORM'
        self.azero, self.fixedz, self.setacv = 'ON', 'OFF', 'ANA'
        self.lfreq, self.delay = 60.0, -1.0
        self.acband, self.level, self.slope = (20.0, 2e6), (0.0, 'AC'), 'POS'
        self.math, self.offset_reg, self.null_pending = 'OFF', 0.0, False
        self._queue = []

    def apply(self, function, value):
        """Apply `value` (volts, amps or ohms) to the input for `function`."""
        self.applied[function] = float(value)

    # ---- physics -----------------------------------------------------------------------------------------------------------------------
    def _signal(self):
        value = self.applied.get(self.func)
        if value is not None:
            return value
        f = self.bench.fluke
        unit, ac = SOURCE[self.func]
        if not f['operate'] or f.get('unit', 'V') != unit:
            return None
        if ac is True and not f['freq']:
            return None
        if ac is False and f['freq']:
            return None
        return float(f['volts'])

    def _full_scale(self):
        nominal = self.nominal[self.func]
        return next(full for nom, full in RANGES[self.func] if nom == nominal)

    def _select(self, function, max_input):
        try:
            return select_range(function, max_input)[0]
        except InstrumentError:
            return None

    def _take_reading(self):
        if self.drop_readings:
            raise TransportError('simulated read timed out (no reading)')
        value = self._signal()
        value = self.offsets[self.func] if value is None else value * self.gain[self.func] + self.offsets[self.func]
        if abs(value) > self._full_scale():
            return OVERLOAD if value > 0 else -OVERLOAD
        if self.math == 'NULL':
            if self.null_pending:
                self.offset_reg, self.null_pending = value, False
            value = value - self.offset_reg
        self.stb |= DATA
        return value

    def _wire_reading(self):
        value = self._take_reading()
        if self.oformat == 'ASCII':
            return _num_text(value) + '\r\n'
        return encode_reading(value, self.oformat)

    def _pending_reading(self):
        if self._queue:
            return self._queue.pop(0)
        if self.trig in ('SYN', 'AUTO'):
            return self._wire_reading()
        raise TransportError(f'simulated read timed out (TRIG {self.trig}: no reading is available)')

    # ---- bus ---------------------------------------------------------------------------------------------------------------------------
    def set_timeout(self, seconds):
        self.timeout = float(seconds)

    def set_read_termination(self, term):
        self.read_termination = term

    def clear(self):
        self._reply = None
        self._queue = []

    def read(self):
        if self._reply is not None:
            return super().read()
        data = self._pending_reading()
        return data.decode('latin-1') if isinstance(data, bytes) else data.rstrip('\r\n')

    def read_raw(self, count):
        if self._reply is not None:
            raise TransportError('simulated 3458A: a query reply is waiting, not a binary reading')
        data = self._pending_reading()
        if not isinstance(data, bytes):
            raise TransportError('simulated 3458A: the output format is ASCII, not binary')
        if len(data) != int(count):
            raise TransportError(f'simulated 3458A: {len(data)} bytes are waiting, {count} were asked for')
        return data

    # ---- commands ----------------------------------------------------------------------------------------------------------------------
    def _error(self, bit, text):
        self.errors.append((100 + bit, text))
        self.stb |= ERR_BIT

    def _err_register(self):
        return sum(1 << (c - 100) for c, _t in self.errors)

    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        if u == 'ID?':
            return self.idn_text
        if u == 'RESET':
            self._power_up()
            self.errors = []
            self.stb &= PON
            return None
        if u == 'CSB':
            self.stb = 0
            return None
        if u == 'STB?':
            value = self.stb | (ERR_BIT if self.errors else 0)
            self.stb &= ~DATA
            return str(value & ~16)                                # the ready bit (16) is always clear in the reply
        if u == 'ERRSTR?':
            if self.errors:
                code, text = self.errors.pop(0)
                if not self.errors:
                    self.stb &= ~ERR_BIT
                return f'{code},"{text}"'
            return '0,"NO ERROR"'
        if u == 'ERR?':
            value = self._err_register()
            self.errors, self.stb = [], self.stb & ~ERR_BIT
            return str(value)
        if u == 'AUXERR?':
            return '0'
        simple = {'REV?': self.rev_text, 'TEMP?': f'{self.temperature:.2f}', 'LINE?': f'{self.lfreq:.5f}', 'CALNUM?': str(self.calnum), 'OPT?': '0', 'INBUF?': '0',
                  'TERM?': str(ENUMS['term'][self.terminals]), 'FUNC?': None}
        if u in simple and simple[u] is not None:
            return simple[u]
        if u == 'FUNC?':
            nominal = self.nominal[self.func]
            return f'{FUNC_NUM[self.func]},{_num_text(nominal if self.range_reports == "nominal" else self._full_scale())}'
        if u == 'RANGE?':
            return _num_text(self.nominal[self.func] if self.range_reports == 'nominal' else self._full_scale())
        if u == 'ARANGE?':
            return str(ENUMS['arange'][self.auto_name()])
        if u == 'NPLC?':
            return _num_text(self.nplc if self.aper is None else self.aper * self.lfreq)
        if u == 'APER?':
            return _num_text(self.aper if self.aper is not None else self.nplc / self.lfreq)
        if u == 'NDIG?':
            return str(self.ndig)
        if u == 'TRIG?':
            return str(ENUMS['trig'][self.trig])
        if u == 'TARM?':
            return str(ENUMS['tarm'][self.tarm])
        if u == 'NRDGS?':
            return f'{self.nrdgs[0]},{ENUMS["sample"][self.nrdgs[1]]}'
        if u == 'END?':
            return str(ENUMS['end'][self.end])
        if u == 'OFORMAT?':
            return str(ENUMS['oformat'][self.oformat])
        if u == 'QFORMAT?':
            return str(ENUMS['qformat'][self.qformat])
        if u == 'AZERO?':
            return str(ENUMS['azero'][self.azero])
        if u == 'FIXEDZ?':
            return str(ENUMS['onoff'][self.fixedz])
        if u == 'LFREQ?':
            return _num_text(1.0 / (round(1.0 / self.lfreq / 1e-7) * 1e-7))
        if u == 'DELAY?':
            return _num_text(self.delay)
        if u == 'SETACV?':
            return str(ENUMS['setacv'][self.setacv])
        if u == 'ACBAND?':
            return f'{_num_text(self.acband[0])},{_num_text(self.acband[1])}'
        if u == 'LEVEL?':
            return f'{_num_text(self.level[0])},{ENUMS["coupling"][self.level[1]]}'
        if u == 'SLOPE?':
            return str(ENUMS['slope'][self.slope])
        if u == 'MATH?':
            return f'{ENUMS["math"][self.math]},0'
        if u == 'RMATH OFFSET':
            return _num_text(self.offset_reg)
        if u == 'TRIG SGL':
            self._queue.append(self._wire_reading())
            return None
        m = re.match(r'^ACAL\s+(\w+)(?:,(.*))?$', u)
        if m:
            return self._acal(m.group(1), m.group(2), cmd.strip())
        m = re.match(r'^(FUNC)\s+(\w+),(\S+)$', u)
        if m:
            return self._func(m.group(2), m.group(3))
        m = re.match(r'^(RANGE|NPLC|APER|NDIG|AZERO|FIXEDZ|LFREQ|DELAY|SETACV|ARANGE|TRIG|TARM|END|OFORMAT|QFORMAT|SLOPE|MATH)\s+(\S+)$', u)
        if m:
            return self._set_one(m.group(1), m.group(2))
        m = re.match(r'^(ACBAND|LEVEL|NRDGS|SMATH OFFSET)\s*,?\s*(\S+?)\s*,\s*(\S+)$', u) or re.match(r'^(SMATH OFFSET),(\S+)$', u)
        if m:
            return self._set_two(m)
        if u == 'LFREQ LINE':
            return None
        if self.strict:
            raise TransportError(f'simulated 3458A: unknown command {cmd!r}')
        self._error(3, 'SYNTAX ERROR')
        return None

    def auto_name(self):
        return {0: 'OFF', 1: 'ON', 2: 'ONCE'}[self.auto]

    def _func(self, function, max_input):
        if function not in FUNC_NUM:
            self._error(5, 'UNDEFINED PARAMETER RECEIVED')
            return None
        nominal = self._select(function, float(max_input))
        if nominal is None:
            self._error(6, 'PARAMETER OUT OF RANGE')
            return None
        self.func, self.auto = function, 0
        self.nominal[function] = nominal
        return None

    def _set_one(self, head, arg):
        enum = {'AZERO': 'azero', 'ARANGE': 'arange', 'TRIG': 'trig', 'TARM': 'tarm', 'END': 'end', 'OFORMAT': 'oformat', 'QFORMAT': 'qformat', 'SETACV': 'setacv',
                'SLOPE': 'slope', 'MATH': 'math', 'FIXEDZ': 'onoff'}
        if head in enum:
            if arg not in ENUMS[enum[head]]:
                self._error(5, 'UNDEFINED PARAMETER RECEIVED')
                return None
            if head == 'ARANGE':
                self.auto = ENUMS['arange'][arg]
            elif head == 'MATH':
                self.math, self.null_pending = arg, arg == 'NULL'
            else:
                setattr(self, {'AZERO': 'azero', 'TRIG': 'trig', 'TARM': 'tarm', 'END': 'end', 'OFORMAT': 'oformat', 'QFORMAT': 'qformat', 'SETACV': 'setacv',
                               'SLOPE': 'slope', 'FIXEDZ': 'fixedz'}[head], arg)
            return None
        value = float(arg)
        if head == 'RANGE':
            nominal = self._select(self.func, value)
            if nominal is None:
                self._error(6, 'PARAMETER OUT OF RANGE')
            else:
                self.nominal[self.func], self.auto = nominal, 0
        elif head == 'NPLC':
            if not 0 <= value <= 1000:
                self._error(6, 'PARAMETER OUT OF RANGE')
            else:
                self.nplc, self.aper = value, None
        elif head == 'APER':
            self.aper = value if 0 <= value <= 1 else self.aper
        elif head == 'NDIG':
            if not 3 <= value <= 8:
                self._error(6, 'PARAMETER OUT OF RANGE')
            else:
                self.ndig = int(value)
        elif head == 'LFREQ':
            self.lfreq = value
        elif head == 'DELAY':
            self.delay = value
        return None

    def _set_two(self, m):
        head = m.group(1)
        if head == 'SMATH OFFSET':
            self.offset_reg = float(m.group(2))
            self.null_pending = False
        elif head == 'ACBAND':
            self.acband = (float(m.group(2)), float(m.group(3)))
        elif head == 'LEVEL':
            self.level = (float(m.group(2)), m.group(3))
        elif head == 'NRDGS':
            self.nrdgs = (int(float(m.group(2))), m.group(3))
        return None

    def _acal(self, kind, code, raw):
        if kind not in ACAL_TYPES:
            self._error(5, 'UNDEFINED PARAMETER RECEIVED')
            return None
        if self.enforce_acal_timeout and self.timeout < ACAL_SECONDS[kind]:
            raise TransportError(f'simulated timeout: the bus is held for the {kind} autocal ({ACAL_SECONDS[kind]} s), the transport timeout is {self.timeout:g} s')
        if self.security_code is not None and (code or '').strip() != self.security_code.upper():
            self._error(1, 'CALIBRATION ERROR')
            return None
        self.acal_runs.append(kind)
        if self.security_code is not None:
            self.calnum += 1                                       # a secured autocal increments the calibration number (UG p. 246)
        return None


def make_3458a_bench(cal='5522A'):
    """(bench, calibrator transport, 3458A transport)."""
    bench = SimBench()
    bench.freq_aware = True
    return bench, SimFlukeComp(bench, cal), Sim3458ATransport(bench)
