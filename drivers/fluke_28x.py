"""Fluke 287 / 289 over the infrared (IR) serial cable - reads the meter; it cannot set it up.

From the Fluke 289/287 Remote Interface Specification (Fluke technical note, 2007; Fluke states it gives no support for it):
  115200 baud, 8 data bits, no parity, 1 stop bit, no flow control (p. 1); the IR-to-USB cable is a plain COM port.
  Every command ends with <CR>. The meter answers CMD_ACK<CR> - 0 OK, 1 syntax error, 2 execution error, 5 no data (p. 3) -
  and, for a query that returns data, one more line ending in <CR>.
  ID    -> 'FLUKE 289,V1.00,95081087'  (model, software version, serial; p. 4)
  QM    -> READING_VALUE, UNIT, STATE, ATTRIBUTE  - the primary display in base units; overload 9.99999999E+37 (pp. 5-6)
  QDDA  -> the whole display: functions, range, modes (REL, LOW_PASS_FILTER ...) and every reading (pp. 7-11)
The reset commands DS, RI and RMP are not used: this driver only reads, so a run never changes the meter's settings or memory.
Only read-only queries are sent, so a query that times out may be repeated (base.query_retry rule).
"""
from __future__ import annotations

import math
import time

from .base import Instrument, InstrumentError
from .transport import SerialSettings, TransportError

SERIAL_DEFAULT = SerialSettings(baud=115200, data_bits=8, parity='none', stop_bits=1,
                                write_termination='\r', read_termination='\r', flow_control='none')
ACK = {'0': 'OK', '1': 'syntax error', '2': 'execution error', '5': 'no data available'}
OVERLOAD = 9.9e37
MULT = {-9: 'n', -6: 'µ', -3: 'm', 0: '', 3: 'k', 6: 'M'}


class Reading:
    __slots__ = ('id', 'value', 'unit', 'mult', 'decimals', 'digits', 'state', 'attribute', 'time')

    def __init__(self, fields):
        (self.id, value, self.unit, mult, decimals, digits, self.state, self.attribute, stamp) = fields
        self.value, self.mult, self.decimals, self.digits = float(value), int(mult), int(decimals), int(digits)
        self.time = float(stamp)

    @property
    def overload(self):
        return self.state in ('OL', 'OL_MINUS') or abs(self.value) >= OVERLOAD

    @property
    def valid(self):
        return self.state == 'NORMAL' and not self.overload

    def display_text(self):
        """The number as the meter shows it, in the meter's own prefix (e.g. '49.987' with mult -3 = 49.987 mV)."""
        if self.overload:
            return 'OL'
        return f'{self.value / 10 ** self.mult:.{self.decimals}f}'

    def count(self):
        """One display count in base units."""
        return 10 ** (self.mult - self.decimals)


class Display:
    """A parsed QDDA reply."""

    def __init__(self, primary, secondary, auto_range, range_unit, range_number, range_mult, bolt, minmax_start, modes, readings):
        self.primary, self.secondary = primary, secondary
        self.auto_range, self.range_unit, self.range_number, self.range_mult = auto_range, range_unit, range_number, range_mult
        self.bolt, self.minmax_start, self.modes, self.readings = bolt, minmax_start, modes, readings

    @classmethod
    def parse(cls, text):
        f = [x.strip() for x in text.replace('\r', '').replace('\n', '').split(',')]
        try:
            primary, secondary, auto_range, range_unit = f[0], f[1], f[2], f[3]
            range_number, range_mult = int(f[4]), int(f[5])
            bolt, minmax_start = f[6], float(f[7])
            n_modes = int(f[8])
            modes = f[9:9 + n_modes]
            i = 9 + n_modes
            n_read = int(f[i])
            readings = [Reading(f[i + 1 + 9 * k: i + 10 + 9 * k]) for k in range(n_read)]
        except (IndexError, ValueError) as exc:
            raise InstrumentError(f'Could not read the meter display data (QDDA): {text[:120]!r}') from exc
        if len(f) != i + 1 + 9 * n_read:
            raise InstrumentError(f'QDDA reply has {len(f)} fields, expected {i + 1 + 9 * n_read}: {text[:120]!r}')
        return cls(primary, secondary, auto_range, range_unit, range_number, range_mult, bolt, minmax_start, modes, readings)

    def reading(self, rid='PRIMARY'):
        return next((r for r in self.readings if r.id == rid), None)

    def by_unit(self, unit):
        """The PRIMARY or SECONDARY reading in the given unit (e.g. Hz or PCT when frequency is shown with volts)."""
        for rid in ('PRIMARY', 'SECONDARY'):
            r = self.reading(rid)
            if r is not None and r.unit == unit:
                return r
        return None

    def range_text(self):
        unit = {'VDC': 'V', 'VAC': 'V', 'VAC_PLUS_DC': 'V', 'ADC': 'A', 'AAC': 'A', 'AAC_PLUS_DC': 'A', 'OHM': 'Ω', 'F': 'F'}.get(self.range_unit, self.range_unit)
        return f'{self.range_number} {MULT.get(self.range_mult, "?")}{unit} ({self.auto_range.lower()})'

    def summary(self):
        return (f'function {self.primary}' + (f' + {self.secondary}' if self.secondary != 'NONE' else '') +
                f', range {self.range_text()}, modes {", ".join(self.modes) or "none"}')


class Fluke28x(Instrument):
    MODEL = 'Fluke 287 / 289'
    IDN_MATCH = ('FLUKE 287', 'FLUKE 289')
    DEFAULT_TIMEOUT = 3.0

    def connect(self):
        self.open(verify_model=False)
        self.idn = self.identify()
        if not any(m in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a Fluke 287 or 289 on the IR cable, got {self.idn!r}. Check the cable is on the meter\'s IR port '
                                  'and the meter is switched on.')
        return self

    @property
    def model(self):
        return '289' if '289' in self.idn else '287'

    # ---- the two-line protocol --------------------------------------------------------------------
    def _ask(self, cmd, data=True):
        """Send a read-only command; returns the data line (or '' when data=False). A timeout is retried twice."""
        last = None
        for attempt in range(3):
            try:
                self.log.add('>>', cmd, self.label)
                self.t.write(cmd)
                ack = self.t.read().strip()
                self.log.add('<<', ack, self.label)
                if ack != '0':
                    raise InstrumentError(f'{self.MODEL}: {cmd} -> {ack} ({ACK.get(ack, "unknown reply")})')
                if not data:
                    return ''
                line = self.t.read().strip()
                self.log.add('<<', line, self.label)
                return line
            except TransportError as exc:
                last = exc
                time.sleep(0.3 * (attempt + 1))
        raise InstrumentError(f'{self.MODEL}: no reply to {cmd} over the IR cable ({last}). Check the cable is seated on the meter.')

    def identify(self):
        return self._ask('ID')

    def display(self) -> Display:
        return Display.parse(self._ask('QDDA'))

    def primary(self):
        """QM -> (value in base units, unit, state, attribute)."""
        f = [x.strip() for x in self._ask('QM').split(',')]
        if len(f) != 4:
            raise InstrumentError(f'Unexpected QM reply: {",".join(f)}')
        return float(f[0]), f[1], f[2], f[3]

    def stable_reading(self, unit, counts=2, needed=3, timeout=45.0, interval=0.8, cancel=None):
        """Wait until `needed` consecutive readings in `unit` agree within `counts` display counts. Returns (Reading, Display, history).
        Raises InstrumentError on a timeout; the caller decides what to do (the reading is never guessed)."""
        end = time.monotonic() + timeout
        history = []
        while True:
            if cancel and cancel():
                raise InstrumentError('Stopped by the operator.')
            disp = self.display()
            r = disp.by_unit(unit)
            if r is None:
                raise InstrumentError(f'The meter shows no {unit} reading ({disp.summary()}).')
            history.append(r)
            if r.overload:
                return r, disp, history
            recent = history[-needed:]
            if len(recent) == needed and all(x.valid for x in recent) and \
                    max(x.value for x in recent) - min(x.value for x in recent) <= counts * r.count() * (1 + 1e-9):
                return r, disp, history
            if time.monotonic() > end:
                shown = ', '.join(x.display_text() for x in history[-5:])
                raise InstrumentError(f'The reading did not settle within {timeout:g} s (last: {shown}).')
            time.sleep(interval)

    def cleanup(self):
        """Nothing to switch off. Never raises."""


def check_setup(disp: Display, want: dict):
    """Compare the meter display with what the point needs. Returns a list of problems (empty = OK).
    want: unit (reading unit, required), range [number, multiplier] (optional), functions [names] (optional),
    rel True/False, lowpass True/False (optional), offset_zero True (temperature offset must read 0)."""
    problems = []
    if disp.by_unit(want['unit']) is None:
        shown = ', '.join(f'{r.id} {r.unit}' for r in disp.readings if r.id in ('PRIMARY', 'SECONDARY'))
        problems.append(f'no {want["unit"]} reading on the display (it shows {shown})')
    if want.get('functions') and disp.primary not in want['functions']:
        problems.append(f'function is {disp.primary}, expected {" or ".join(want["functions"])}')
    rng = want.get('range')
    if rng and (disp.range_number, disp.range_mult) != tuple(rng):
        exp = f'{rng[0]} {MULT.get(rng[1], "?")}'
        problems.append(f'range is {disp.range_text()}, expected {exp} (press RANGE)')
    if 'rel' in want:
        on = any(m in ('REL', 'REL_PERCENT') for m in disp.modes)
        if want['rel'] and not on:
            problems.append('REL is off - press REL as instructed')
        if not want['rel'] and on:
            problems.append('REL is on - press REL to turn it off')
    if 'lowpass' in want:
        on = 'LOW_PASS_FILTER' in disp.modes
        if want['lowpass'] != on:
            problems.append('the Low Pass filter must be ' + ('ON' if want['lowpass'] else 'OFF'))
    if want.get('offset_zero'):
        off = disp.reading('TEMP_OFFSET')
        if off is not None and not math.isclose(off.value, 0.0, abs_tol=1e-9):
            problems.append(f'temperature offset is {off.value:g}, set it to 000.0')
    return problems
