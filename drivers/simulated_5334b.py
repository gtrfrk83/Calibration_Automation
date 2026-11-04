"""Simulated HP 5334B universal counter (Option 030 C channel) for tests with no hardware: the device commands of drivers/hp_5334b.py.

It counts the simulated Fluke 6060A on the same bench (drivers.simulated_6060a.rf_state): FREQ C reads the RF output (90 to 1300 MHz, RF on, at least -23.5 dBm), FREQ A reads
`input_a_hz` (the 6060A rear 10 MHz output the technician connects; default 10 MHz plus `ref_error_ppm`). Commands: IN ID FN1 FN3 GA<s> WA1 RE TE (several per message,
separated by commas / semicolons / spaces). A reading is 'F  +d.dddddddddE+dd' CR LF (p. 3-84). The status byte comes from read_stb() (serial poll).

Simulation choices that are NOT facts about the real counter: the text of the TE reply ('4.0'), that a reading with no input signal never arrives (the real counter keeps
waiting), the number of digits in a reading, and the size of the errors. Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import math
import re

from .simulated import _SimBase
from .simulated_6060a import rf_state
from .transport import TransportError

_CMD = re.compile(r'([A-Z]{2})([-+]?(?:\d+\.?\d*|\.\d+)(?:E[-+]?\d+)?)?')


class Sim5334BTransport(_SimBase):
    def __init__(self, bench, freq_ppm=0.0002, ref_error_ppm=0.3):
        super().__init__(bench, 'SIM-5334B')
        self.freq_ppm = freq_ppm            # relative error of FREQ C (the time base is the GPS 10 MHz: tiny)
        self.input_a_hz = 10e6 * (1 + ref_error_ppm * 1e-6)
        self.sent = []
        self.cleared = 0
        self.no_oscillator = False          # True: TIME BASE on EXT with nothing connected (status bit 32)
        self.fail_with_error = None         # e.g. '4.0': the next command puts the counter in that error state
        self.write_termination = '\r\n'      # the VISA GPIB default; the driver sets '\n' at connect
        self.read_termination = '\r\n'
        self.cr_is_error = False            # opt-in (owner bench 2026-11-04): a CR after a command gives error 4.2 'alpha character expected' (NOT confirmed as the cause)
        self._reset_state()

    def _reset_state(self):
        self.function, self.gate_s, self.wait_mode = 'FN1', 0.3, False
        self.error = None
        self._result = None

    # ---- bus ------------------------------------------------------------------------------------------------------------------------------------
    def clear(self):
        """Device clear: aborts the measurement and clears errors 1.0 to 4.4 (p. 3-73)."""
        self.cleared += 1
        self.error = None
        self._result = None

    def go_local(self):
        pass

    def read_stb(self) -> int:
        value = 0
        if self._result is not None:
            value |= 1
        if self.error is not None:
            value |= 4
        if self.no_oscillator:
            value |= 32
        return value

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self.sent.append(text.strip())
        self._reply = self.handle(text.strip())
        if self.cr_is_error and '\r' in self.write_termination and self.error is None:
            self.error = '4.2'

    def read(self):
        if self._reply is not None:
            reply, self._reply = self._reply, None
            return reply
        if self._result is None:
            raise TransportError('simulated read timed out (no reading: no input signal?)')
        reply, self._result = self._result, None
        return reply

    def query(self, text):
        self.write(text)
        return self.read()

    # ---- device commands ----------------------------------------------------------------------------------------------------------------------
    def handle(self, text):
        reply = None
        for code, num in _CMD.findall(re.sub(r'[\s,;]+', '', text.upper())):
            if self.fail_with_error and code not in ('IN', 'TE', 'ID'):
                self.error, self.fail_with_error = self.fail_with_error, None
            if self.error is not None and code not in ('IN', 'TE', 'ID'):
                continue                                                 # in an error state only IN, TE and ID are obeyed (p. 3-87)
            if code == 'ID':
                reply = 'HP 5334B\r\n'
            elif code == 'IN':
                self._reset_state()
            elif code in ('FN',):
                self.function = f'FN{int(float(num or 0))}'
            elif code == 'GA':
                self.gate_s = float(num)
            elif code == 'WA':
                self.wait_mode = bool(int(float(num or 0)))
            elif code == 'RE':
                self._result = self._measure()
            elif code == 'TE':
                reply = f'{self.error or "0.0"}\r\n'
            else:
                self.error = '4.0'                                       # mnemonic not recognizable (Table 3-3)
        return reply

    def _measure(self):
        if self.function == 'FN3':
            s = rf_state(self.bench)
            f = s['frequency_hz']
            if not s['rf_on'] or not 90e6 <= f <= 1300e6 or s['amplitude_dbm'] < -23.5:
                return None
            value = f * (1 + self.freq_ppm * 1e-6)
        elif self.function == 'FN1':
            value = self.input_a_hz
        else:
            return None
        res = max(1e-3, 10 ** round(math.log10(4e-9 / self.gate_s * value)))     # LSD = 4 ns / gate x f, rounded to a decade (Table 1-1)
        value = round(value / res) * res
        return f'F  {value:+.9E}\r\n'
