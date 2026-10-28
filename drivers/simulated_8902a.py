"""Simulated HP 8902A measuring receiver (HP-IB code language) for tests with no hardware.

It speaks the code strings of drivers/hp_8902a.py: IP ID AU, number+MZ tuning, M1 M2 M4 M5, S1 S2 S4 S5, D1..D9, H0..H2, L0..L3, P0..P5, LG LN WT, 7.nSP 4.nSP 22.nSP,
15.1SP 15.0SP 37.nSP 42.0SP displays, ZR C0 C1 C1T3SC SC CF, T0..T3, several codes in one message (spaces and commas ignored). A reading is returned as "+0096921346E+01"
(drivers.hp_8902a.encode_reading); an error comes back as an error word, like the real receiver.

It "measures" the simulated Fluke 6060A on the same bench (drivers.simulated_6060a.rf_state(bench)): frequency, level, AM depth and FM deviation, each with a small fixed,
configurable error (`errors`), so a whole 6060A verification can run end to end. The status byte is read with read_stb() (serial poll).

Simulation choices that are NOT facts about the real receiver (the manual does not say): the TEXT of the ID reply ("HP8902A"), how long anything takes, the size of the errors, the
levels at which an error word appears (< -50 dBm for AM / FM, outside +/-50 kHz of the tuned frequency for S4), the FM de-emphasis gain of the displayed reading (a single-pole
1 / sqrt(1 + (f / fc)^2) at the modulation rate) and the 100.00 % calibration factors. Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import math
import re

from .hp_8902a import DEEMPHASIS_US, MAX_VALUE, encode_reading
from .simulated import SimBench, _SimBase
from .simulated_6060a import rf_state
from .transport import TransportError

_TOKEN = re.compile(r'(?:([-+]?(?:\d+\.\d*|\.\d+|\d+))(SP|MZ|HZ|CF)|([A-Z][0-9A-Z]))')
RES_HZ = {'0': 10.0, '1': 10.0, '2': 100.0, '3': 1000.0, '4': 0.1}
DEEMPH_FC = {2: 1 / (2 * math.pi * 25e-6), 3: 1 / (2 * math.pi * 50e-6), 4: 1 / (2 * math.pi * 75e-6), 5: 1 / (2 * math.pi * 750e-6)}


class Sim8902ATransport(_SimBase):
    def __init__(self, bench, errors=None):
        super().__init__(bench, 'SIM-8902A')
        self.errors = dict(freq_ppm=0.05, level_db=0.02, am_pct=0.05, fm_rel=0.001, distortion_pct=0.05, residual_w=1e-7, cal_factor_pct=100.02, power_cal_w=0.9995e-3)
        self.errors.update(errors or {})
        self.sent = []
        self.cleared = 0
        self.external_ref = False
        self.sensor_connected = True
        self.sensor_on_calibrator = False
        self.firmware_code = 235.1985
        self.cf_table = {}                  # MHz -> %
        self.cf_ref = 100.0
        self.recal = True                   # tuned RF level needs a range calibration until C1 has run
        self._reset_state()

    # ---- state ------------------------------------------------------------------------------------------------------------------------------
    def _reset_state(self):
        self.func, self.tuned_mhz, self.units, self.det = 'M5', None, 'LG', 1
        self.hp, self.lp, self.deemph, self.pre_display, self.res, self.tuned_det = 0, 0, 0, False, '0', '0'
        self.trig, self.cal_on, self.mask = 0, False, 2
        self.code_error = False
        self.instr_error = False
        self.data_ready = False
        self.zeroed = False
        self.sc_held = False                 # the 1 mW calibration result stays on the display after C0 until the next ZR
        self.pending = None
        self.dist_tone = 1000
        self.last_function = None
        self._cf_mode, self._cf_freq = None, None

    # ---- bus --------------------------------------------------------------------------------------------------------------------------------
    def clear(self):
        """Device clear = IP (p. 3-25): power-up state, calibration data kept."""
        self.cleared += 1
        self._reset_state()

    def go_local(self):
        pass

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self.pending = None                                          # a new message aborts a measurement whose result was not read (p. 3-35)
        self.sent.append(text.strip())
        self._reply = self.handle(text.strip())

    def read(self):
        if self._reply is not None:
            reply, self._reply = self._reply, None
            return reply
        if self.pending is None and self.trig == 0:
            self.pending = self._measure()                          # free-run: a read returns the current reading
        if self.pending is None:
            raise TransportError('simulated read timed out (no reading was triggered)')
        reply, self.pending = self.pending, None
        self.data_ready = False
        return reply

    def read_stb(self) -> int:
        value = 0
        if self.data_ready:
            value |= 1
        if self.code_error:
            value |= 2
        if self.instr_error:
            value |= 4
        if self.func == 'S4' and self.recal and self.last_function == 'S4':
            value |= 32
        if value & (self.mask | 2) & 0x3F:
            value |= 64
        self.code_error = self.instr_error = False                   # reading the status byte clears it
        return value

    def query(self, text):
        self.write(text)
        return self.read()

    # ---- the code language ------------------------------------------------------------------------------------------------------------------
    def handle(self, text):
        msg = re.sub(r'[\s,]+', '', text.upper())
        if msg == 'ID':
            return 'HP8902A'
        pos = 0
        while pos < len(msg):
            m = _TOKEN.match(msg, pos)
            if not m:
                self.code_error = self.instr_error = True            # error 24: invalid HP-IB code (always raises SRQ)
                self.pending = encode_reading(0, error=24)
                return None
            pos = m.end()
            if m.group(3):
                self._code(m.group(3))
            else:
                self._numeric(m.group(1), m.group(2))
        return None

    def _numeric(self, num, suffix):
        if suffix == 'MZ' and self._cf_mode in ('ref', 'pair'):
            self._cf_mode, self._cf_freq = 'pair', float(num)           # 37.3SP <f> MZ <cf> CF: a cal-factor frequency, not a tuning
        elif suffix == 'MZ':
            self.tuned_mhz = float(num)
        elif suffix == 'HZ':
            self.tuned_mhz = float(num) / 1e6
        elif suffix == 'CF':
            self._cf(float(num))
        elif suffix == 'SP':
            sf, _, arg = num.partition('.')
            self._special(int(sf), arg)

    def _cf(self, value):
        if self._cf_mode == 'ref':
            self.cf_ref = value
        elif self._cf_mode == 'pair' and self._cf_freq is not None:
            if value == 0:
                self.cf_table.pop(self._cf_freq, None)
            elif len(self.cf_table) >= 16 and self._cf_freq not in self.cf_table:
                self.code_error = True
            else:
                self.cf_table[self._cf_freq] = value
        self._cf_mode = None

    def _special(self, sf, arg):
        if sf == 37 and arg == '3':
            self._cf_mode, self._cf_freq = 'ref', None
        elif sf == 37 and arg == '9':
            self.cf_table.clear()
        elif sf == 37 and arg == '4':
            self.pending = encode_reading(len(self.cf_table) + 1)
        elif sf == 37 and arg == '5':
            self._cf_mode = 'show'
        elif sf == 22:
            if arg == '64':
                self.pending = encode_reading(self.mask)
            else:
                self.mask = (int(arg or 0) & 63) | 2
        elif sf == 15:
            self.pending = encode_reading(1.0 if (arg == '1' and self.external_ref) else 0.0)
        elif sf == 42:
            self.pending = encode_reading(self.firmware_code)
        elif sf == 7:
            self.res = arg or '0'
        elif sf == 4:
            self.tuned_det = arg or '0'
        else:
            self.code_error = True

    def _code(self, code):
        if code == 'IP':
            self._reset_state()
        elif code == 'AU':
            self.tuned_mhz = None
        elif code in ('M1', 'M2', 'M4', 'M5', 'S1', 'S2', 'S4', 'S5'):
            self.func = code
            self.last_function = code
        elif code in ('D1', 'D2', 'D3', 'D4', 'D8', 'D9'):
            self.det = int(code[1])
        elif code in ('D5', 'D6'):
            self.dist_tone = 1000 if code == 'D5' else 400
        elif code[0] == 'H' and code[1] in '012':
            self.hp = int(code[1])
        elif code[0] == 'L' and code[1] in '0123':
            self.lp = int(code[1])
        elif code[0] == 'P' and code[1] in '012345':
            n = int(code[1])
            if n == 0:
                self.pre_display, self.deemph = False, 0
            elif n == 1:
                self.pre_display = True
            else:
                self.deemph = n
        elif code in ('LG', 'LN'):
            self.units = code
        elif code == 'WT':
            self.units = 'WT'
        elif code[0] == 'T' and code[1] in '0123':
            self.trig = int(code[1])
            if self.trig in (2, 3):
                self.pending = self._measure()
                self.data_ready = True
        elif code == 'C1':
            self.cal_on = True
            if self.func == 'S4':
                self.recal = False
        elif code == 'C0':
            self.cal_on = False
        elif code == 'ZR':
            self.zeroed = True
            self.sc_held = False
        elif code == 'SC':
            if not self.sensor_on_calibrator:
                self.instr_error = True
                self.pending = encode_reading(0, error=18)
            else:
                self.sc_held = True
        elif code == 'CF':
            if self._cf_mode == 'show' or self.func not in ('M1', 'M2'):
                self.pending = encode_reading(self.cf_ref)
                self._cf_mode = None
            else:
                self.pending = encode_reading(self.errors['cal_factor_pct'])
        else:
            self.code_error = True

    # ---- the measurements ---------------------------------------------------------------------------------------------------------------------
    def _error(self, n):
        self.instr_error = True
        return encode_reading(0, error=n)

    def _near(self, f_hz, window_hz):
        return self.tuned_mhz is None or abs(self.tuned_mhz * 1e6 - f_hz) <= window_hz

    def _measure(self):
        src = rf_state(self.bench)
        e = self.errors
        f, level = src['frequency_hz'], src['amplitude_dbm']
        have_signal = src['rf_on']
        fn = self.func
        if fn == 'M5':
            if not have_signal:
                return self._error(96)
            if not self._near(f, 0.5e6):
                return self._error(1)
            res = RES_HZ.get(self.res, 10.0)
            return encode_reading(round(f * (1 + e['freq_ppm'] * 1e-6) / res) * res)
        if fn == 'S4':
            if not have_signal or not self._near(f, 50e3):
                return self._error(96)
            if level < -127.0:
                return self._error(19)
            if level > 0.0:
                return self._error(2)
            return encode_reading(round((level + e['level_db']) * 100) / 100)
        if fn == 'M4':
            if not self.sensor_connected:
                return self._error(13)
            if self.sensor_on_calibrator and (self.cal_on or self.sc_held):         # the calibration output is only on during C1 (the result is held after C0)
                watts = e['power_cal_w']
            elif have_signal:
                watts = 1e-3 * 10 ** (level / 10.0)
            else:
                watts = e['residual_w'] if self.zeroed else 5e-6          # an unzeroed sensor shows an offset
            if self.units == 'LG':
                return encode_reading(10 * math.log10(max(watts, 1e-30) / 1e-3) + e['level_db'])
            return encode_reading(watts)
        if fn in ('M1', 'M2', 'S1', 'S2'):
            if not have_signal or level < -50.0:
                return self._error(3 if have_signal else 96)
            if not self._near(f, 50e3):
                return self._error(96)
            if fn == 'M1':
                on = src['int_am'] or src['ext_am']
                return encode_reading(round((src['am_depth_pct'] + e['am_pct']) * 100) / 100 if on else 0.0)
            if fn == 'M2':
                on = src['int_fm'] or src['ext_fm']
                dev = src['fm_dev_hz'] * (1 + e['fm_rel']) if on else 0.0
                rate = src['mod_rate_hz'] or 1000
                if on and self.pre_display and self.deemph in DEEMPH_FC:
                    dev /= math.sqrt(1 + (rate / DEEMPH_FC[self.deemph]) ** 2)
                return encode_reading(round(dev * 10) / 10)
            rate = src['mod_rate_hz'] or 1000
            if fn == 'S1':
                return encode_reading(float(rate))
            if abs(rate - self.dist_tone) > 0.05 * self.dist_tone:
                return self._error(16)
            return encode_reading(e['distortion_pct'] if self.units == 'LN' else 20 * math.log10(e['distortion_pct'] / 100.0))
        if fn == 'S5':
            return encode_reading(round(f * e['freq_ppm'] * 1e-6, 1))
        return self._error(25)


def make_8902a_bench(errors=None, bench=None):
    """(bench, 8902A transport); pass a bench that already has a 6060A to share its output."""
    bench = bench or SimBench()
    return bench, Sim8902ATransport(bench, errors)
