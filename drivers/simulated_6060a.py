"""Simulated Fluke 6060A (GPIB, two-letter command language) for tests with no hardware.

The simulator speaks exactly the command strings of drivers/fluke_6060a.py: FR / AP / RO / AI / AE / FI / FE / AM / FM / MR / SP80..SP91 / FS LS PS DS / FU FD LU LD PU PD DU DD /
SU SD / RC98 / CL CE CB / @n / SM / ID IV IO IR IU II IM XA / LM99 LM98, several commands in one message separated by ',' or ';' (a syntax error discards the rest of
the message). The state lives in the bench (`rf_state(bench)`), so the simulated HP 8902A and HP 8563E "measure" what this generator is outputting.

LM99 is built by drivers.fluke_6060a.encode_learn, the same layout decode_learn reads (Fig. 2-7), including the checksum.
IR / IU rejected-entry and UNCAL codes follow Tables 2-6 and 2-5. Simulation choices that are NOT facts about the real generator (the manual does not say): the TEXT layout of
the IR / IU / IO / II / IM replies (`ir_format` = 'groups' gives "001,000,000", 'single' gives "001000000"), the number of serial polls that still say "not valid" after a
change (`valid_after_polls`), a volts suffix on AP being converted to dBm at 50 ohm, the amplitude limits -147.4 .. +19 dBm for a rejected entry. Device clear does what CL does:
preset, RF ON. Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import math
import re

from .fluke_6060a import (ALT_SECTION_CODE, MAX_AM_PCT, MAX_FM_KHZ, MAX_FM_KHZ_651, PRESET_LEARN, UNCAL_MAX_DBM, UNCAL_MIN_DBM, decode_learn, encode_learn)
from .simulated import SimBench, _SimBase
from .transport import TransportError

UNIT_SCALE = {'GZ': 1e9, 'MZ': 1e6, 'KZ': 1e3, 'HZ': 1.0}
_CMD = re.compile(r'^([A-Z]{2})([-+]?(?:\d+\.?\d*|\.\d+)(?:E[-+]?\d+)?)?([A-Z]{1,2})?$')
HEADERS = {'FR', 'AP', 'RO', 'AI', 'AE', 'FI', 'FE', 'AM', 'FM', 'MR', 'SP', 'FS', 'LS', 'PS', 'DS', 'FU', 'FD', 'LU', 'LD', 'PU', 'PD', 'DU', 'DD', 'SU', 'SD', 'RC', 'CL', 'CE', 'CB',
           'SM', 'ID', 'IV', 'IO', 'IR', 'IU', 'II', 'IM', 'XA', 'LM', 'TM', 'RM', 'VM', 'UM', 'EM', 'ST'}


def preset_state() -> dict:
    s = dict(decode_learn(PRESET_LEARN))
    s['rf_on'] = True
    return s


def rf_state(bench) -> dict:
    """The RF source state shared on the bench (created on first use, with the instrument preset and RF ON)."""
    if not hasattr(bench, 'rf_source'):
        bench.rf_source = preset_state()
    return bench.rf_source


def output_dbm(bench):
    """The RF level actually leaving the generator in dBm, or None when RF is off / no source."""
    s = rf_state(bench)
    return s['amplitude_dbm'] if s['rf_on'] else None


class Sim6060ATransport(_SimBase):
    """GPIB 6060A on a SimBench. `sent` lists every message; `rejected` is the accumulated IR status."""

    def __init__(self, bench, serial='SIM6060'):
        super().__init__(bench, 'SIM-6060A')
        self.serial = serial
        self.sent = []
        self.cleared = 0
        self.ir_format = 'bench'            # the owner's 6060A (bench 2026-10-29): three 6-digit octal fields, '000000,000000,000400'
        self.io = (3, 1, 0)                 # first field always 3; second 1 = -570 NV memory (8 would add -651 low-rate FM)
        self.valid_after_polls = 1
        self.ext_level = 'valid'            # level of an external modulation input: 'valid' | 'ext_lo' | 'ext_hi' | 'invalid'
        self.reset_all()

    # ---- state ------------------------------------------------------------------------------------------------------------------------------
    @property
    def s(self) -> dict:
        return rf_state(self.bench)

    def reset_all(self):
        self.bench.rf_source = preset_state()
        self.rejected = [0, 0, 0]
        self.modes = 0
        self.mask = 192
        self.section = None
        self._not_valid = 0
        self.alt_section_active = None

    def _preset(self):
        keep_rf = self.s['rf_on']
        self.bench.rf_source = preset_state()
        self.s['rf_on'] = keep_rf
        self.section = None

    def _changed(self):
        self._not_valid = self.valid_after_polls

    # ---- bus --------------------------------------------------------------------------------------------------------------------------------
    def clear(self):
        """Device clear = CL: preset, RF ON, modes back to their defaults, status cleared (p. 2-53)."""
        self.cleared += 1
        self.reset_all()
        self._reply = None

    def read_stb(self) -> int:
        """Serial poll (not a command): 1 ready, 2 rejected entry, 4 UNCAL, 16 output valid, 64 RQS (any masked reason set)."""
        valid = self._not_valid <= 0
        if self._not_valid > 0:
            self._not_valid -= 1
        value = 1 | (16 if valid else 0) | (2 if any(self.rejected) else 0) | (4 if any(self._uncal()) else 0)
        if value & self.mask & 0x3F:
            value |= 64
        return value

    def go_local(self):
        pass

    def handle(self, text):
        self.sent.append(text)
        if text.startswith('@'):
            return self._modes(text)
        reply = None
        for part in re.split(r'[;,]', re.sub(r'\s+', '', text.upper())):
            if not part:
                continue
            m = _CMD.match(part)
            if m is None or m.group(1) not in HEADERS:
                self.rejected[0] |= 0o020                                    # syntax error: the rest of the message is discarded
                break
            out = self._command(m.group(1), m.group(2), m.group(3))
            if out is not None:
                reply = out
        return reply

    def query(self, text):
        self.write(text)
        return self.read()

    # ---- helpers ----------------------------------------------------------------------------------------------------------------------------
    def _reject(self, field, bit):
        self.rejected[field] |= bit

    def _fmt(self, fields):
        if self.ir_format == 'bench':
            return ','.join(f'{f:06o}' for f in fields)
        return ','.join(f'{f:03o}' for f in fields) if self.ir_format == 'groups' else ''.join(f'{f:03o}' for f in fields)

    def _modes(self, text):
        m = re.fullmatch(r'@(\d+)', text.strip())
        if not m or int(m.group(1)) > 31:
            self._reject(0, 0o020)
            return None
        self.modes = int(m.group(1))
        return None

    def _uncal(self):
        s = self.s
        f1 = f3 = 0
        fm_on = s['int_fm'] or s['ext_fm']
        am_on = s['int_am'] or s['ext_am']
        low = 10.0 if self.io[1] & 8 else 100.0
        if fm_on and s['fm_dev_hz'] < low:
            f1 |= 0o001
        if fm_on and s['fm_dev_hz'] > (s['frequency_hz'] - 100e3) / 3:
            f1 |= 0o002
        if am_on and s['am_depth_pct'] > 90:
            f1 |= 0o020
        if s['amplitude_dbm'] < -137.0:
            f3 |= 0o001
        if s['amplitude_dbm'] + (20 * math.log10(1 + s['am_depth_pct'] / 100.0) if am_on else 0.0) > 13.0:
            f3 |= 0o002
        if not s['rf_on']:
            f3 |= 0o400
        return (f1, 0, f3)

    def _step(self, key, size_key, sign, lo, hi, scale=1.0):
        s = self.s
        new = s[key] + sign * s[size_key]
        if not lo <= new <= hi:
            self._reject(0, 0o200)
            return
        s[key] = round(new * 10) / 10 if key == 'amplitude_dbm' else new
        self._changed()

    def _command(self, head, num, suffix):
        s = self.s
        n = float(num) if num is not None else None
        low_rate = bool(self.io[1] & 8)
        if head == 'ID':
            return '6060A/AN'                     # bench 2026-10-29
        if head == 'IV':
            return 'V1.1'                         # bench 2026-10-29
        if head == 'IO':
            return ','.join(str(x) for x in self.io)
        if head == 'IR':
            fields, self.rejected = tuple(self.rejected), [0, 0, 0]
            return self._fmt(fields)
        if head == 'IU':
            return self._fmt(self._uncal())
        if head == 'II':
            return f'{self.modes:05d}'
        if head == 'IM':
            return f'{self.mask:05d}'             # bench 2026-10-29: '00192'
        if head == 'XA':
            return f"{int(min(23, max(0, round((13.0 - s['amplitude_dbm']) / 6.0)))):05d}"       # bench 2026-10-29: '00023'
        if head == 'LM':
            if n == 99:
                return encode_learn(s)
            if n == 98:
                return PRESET_LEARN
            self._reject(1, 0o040)
            return None
        if head == 'CE':
            self.rejected = [0, 0, 0]
        elif head == 'CB':
            self._reply = None
        elif head == 'CL':
            self.clear()
        elif head == 'RC':
            if n == 98:
                self._preset()
                self._changed()
            else:
                self._reject(1, 0o040)
        elif head == 'SM':
            self.mask = int(n or 0)
        elif head in ('TM', 'RM', 'VM', 'UM', 'EM'):
            bit = {'TM': 1, 'RM': 2, 'VM': 4, 'UM': 8, 'EM': 16}[head]
            self.modes = (self.modes | bit) if n else (self.modes & ~bit)
        elif head == 'FR':
            hz = n * UNIT_SCALE.get(suffix or 'HZ', 1.0)
            if not 0.1e6 <= hz <= 1050e6:
                self._reject(1, 0o001)
            else:
                s['frequency_hz'] = round(hz / 10.0) * 10
                self._changed()
        elif head == 'AP':
            dbm = n if suffix == 'DB' else (20 * math.log10(n * {'V': 1, 'MV': 1e-3, 'UV': 1e-6, 'NV': 1e-9}.get(suffix, 1) / math.sqrt(0.05)) if n else -999)
            if not UNCAL_MIN_DBM <= dbm <= UNCAL_MAX_DBM:
                self._reject(2, 0o001)
            else:
                s['amplitude_dbm'] = round(dbm * 10) / 10
                self.alt_section_active = None                               # any new amplitude entry restores the default attenuators
                self._changed()
        elif head == 'RO':
            s['rf_on'] = bool(n)
            self._changed()
        elif head in ('AI', 'AE', 'FI', 'FE'):
            key = {'AI': 'int_am', 'AE': 'ext_am', 'FI': 'int_fm', 'FE': 'ext_fm'}[head]
            s[key] = bool(n)
            s['ext_mod_level'] = self.ext_level if (s['ext_am'] or s['ext_fm']) else 'invalid'
            self._changed()
        elif head == 'AM':
            if not 0 <= n <= MAX_AM_PCT:
                self._reject(0, 0o004)
            else:
                s['am_depth_pct'] = round(n)
                self._changed()
        elif head == 'FM':
            khz = n * UNIT_SCALE.get(suffix or 'HZ', 1.0) / 1e3
            if not 0 <= khz <= (MAX_FM_KHZ_651 if low_rate else MAX_FM_KHZ) + 1e-9:
                self._reject(0, 0o001)
            else:
                s['fm_res_hz'] = 1.0 if low_rate else 10.0                  # simulation choice: the manual only says -651 gives 0.1 Hz resolution
                s['fm_dev_hz'] = round(khz * 1e3 / s['fm_res_hz']) * s['fm_res_hz']
                self._changed()
        elif head == 'MR':
            s['mod_rate_hz'] = 1000 if n else 400
            self._changed()
        elif head == 'FS':
            hz = n * UNIT_SCALE.get(suffix or 'HZ', 1.0)
            if not 0 <= hz <= 1050e6:
                self._reject(1, 0o004)
            else:
                s['freq_step_hz'] = round(hz / 10.0) * 10
        elif head == 'LS':
            if suffix == 'DB' and 0 <= n <= 166:
                s['amp_step'] = round(n * 10) / 10
            else:
                self._reject(2, 0o020)
        elif head == 'PS':
            if 0 <= n <= 99:
                s['am_step_pct'] = round(n)
            else:
                self._reject(0, 0o010)
        elif head == 'DS':
            khz = n * UNIT_SCALE.get(suffix or 'HZ', 1.0) / 1e3
            if 0 <= khz <= (MAX_FM_KHZ_651 if low_rate else MAX_FM_KHZ):
                s['fm_step_hz'] = round(khz * 1e3 / 100.0) * 100.0
            else:
                self._reject(0, 0o002)
        elif head in ('FU', 'SU') or head in ('FD', 'SD'):
            sign = 1 if head in ('FU', 'SU') else -1
            if head in ('FU', 'FD'):
                s['step_function'] = 'freq'
            if s['step_function'] == 'freq':
                self._step('frequency_hz', 'freq_step_hz', sign, 0.1e6, 1050e6)
            elif s['step_function'] == 'ampl':
                self._step('amplitude_dbm', 'amp_step', sign, UNCAL_MIN_DBM, UNCAL_MAX_DBM)
            else:
                self._step('am_depth_pct', 'am_step_pct', sign, 0, MAX_AM_PCT)
        elif head in ('LU', 'LD'):
            s['step_function'] = 'ampl'
            self._step('amplitude_dbm', 'amp_step', 1 if head == 'LU' else -1, UNCAL_MIN_DBM, UNCAL_MAX_DBM)
        elif head in ('PU', 'PD'):
            s['step_function'] = 'mod'
            self._step('am_depth_pct', 'am_step_pct', 1 if head == 'PU' else -1, 0, MAX_AM_PCT)
        elif head in ('DU', 'DD'):
            s['step_function'] = 'mod'
            self._step('fm_dev_hz', 'fm_step_hz', 1 if head == 'DU' else -1, 0, (MAX_FM_KHZ_651 if low_rate else MAX_FM_KHZ) * 1e3)
        elif head == 'SP':
            self._special(int(n))
        return None

    def _special(self, code):
        s = self.s
        if code in {int(c) for c in ALT_SECTION_CODE.values()}:
            if s['int_am'] or s['ext_am'] or not -17.0 <= s['amplitude_dbm'] <= -11.1:
                self._reject(1, 0o200)
                return
            s.update(int_am=False, ext_am=False, int_fm=False, ext_fm=False, rel_freq=False, rel_amp=False, fixed_range=False, correction='all_on', rf_on=True,
                     ext_mod_level='invalid')
            self.alt_section_active = code
            self._changed()
        elif code in (80, 81, 82):
            s['correction'] = {80: 'all_on', 81: 'all_off', 82: 'attenuator_off'}[code]
        elif code in (90, 91):
            s['fixed_range'] = code == 91
        elif code in (20, 21):
            s['rel_freq'] = code == 21
        elif code in (30, 31):
            s['rel_amp'] = code == 31
        elif code in (2, 7, 8, 10, 11):
            pass
        else:
            self._reject(1, 0o200)


def make_6060a_bench():
    """(bench, 6060A transport)."""
    bench = SimBench()
    return bench, Sim6060ATransport(bench)


def make_rf_bench():
    """(bench, 6060A, 8902A, 8563E transports) on ONE bench: the receiver and the analyzer measure what the generator outputs."""
    from .simulated_8563e import Sim8563ETransport
    from .simulated_8902a import Sim8902ATransport
    bench = SimBench()
    return bench, Sim6060ATransport(bench), Sim8902ATransport(bench), Sim8563ETransport(bench)
