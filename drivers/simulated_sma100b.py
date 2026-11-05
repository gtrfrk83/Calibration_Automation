"""Simulated R&S SMA100B (GPIB) for tests with no hardware.

It speaks the commands of drivers/rs_sma100b.py (short forms, the optional ':SOURce' / ':OUTPut1' prefixes, a leading ':') plus *IDN? *OPT? *RST *CLS *OPC? *TST?,
and keeps an error queue in the manual's format ('0,"No error"' when empty, SCPI -113 / -222 / -224 otherwise, p. 783).

Simulation choices that are NOT facts about the real generator (nothing here has been compared with a real unit): the *IDN? / *OPT? text, the frequency range
(8 kHz to `max_hz`, default 6 GHz: option SMAB-B106), the level range (-145 dBm to +18 dBm), the reply formats of every query (numbers as '%.12g', mode words
'CW', UNIT:POW? 'DBM', ROSC:SOUR? 'INT' / 'EXT', OUTP? '0' / '1'). The reference source and level limit survive *RST as the manual says (p. 746, 756).
Keep this file out of any evidence: nothing here is calibration data.
"""
from __future__ import annotations

import re

from .simulated import SimBench, _SimBase

IDN = 'Rohde&Schwarz,SMA100B,1419.8888K02/100001,5.30.047.40'
_NODE = re.compile(r'^:?(?:SOUR(?:CE)?1?:)?')


class SimSMA100BTransport(_SimBase):
    def __init__(self, bench=None, max_hz=6e9, min_hz=8e3, min_dbm=-145.0, max_dbm=18.0, options='SMAB-B106,SMAB-K720', level_limit=30.0, ref_source='INT',
                 selftest_code=0):
        super().__init__(bench if bench is not None else SimBench(), 'SIM-SMA100B')
        self.max_hz, self.min_hz, self.min_dbm, self.max_dbm = max_hz, min_hz, min_dbm, max_dbm
        self.options = options
        self.level_limit, self.ref_source = float(level_limit), ref_source
        self.selftest_code = selftest_code
        self.errors = []
        self.sent = []
        self.cleared = 0
        self.local = 0
        self.preset()

    def preset(self):
        """*RST / SYST:PRES state (p. 490): RF off, CW, -30 dBm, modulation off, dBm, no offsets. Reference source and level limit untouched."""
        self.rf_on = False
        self.freq_hz, self.level_dbm = 1e9, -30.0
        self.freq_mode = self.pow_mode = 'CW'
        self.mod_on = False
        self.unit = 'DBM'
        self.freq_offs, self.freq_mult, self.pow_offs = 0.0, 1.0, 0.0

    def output_dbm(self):
        """What actually comes out of the RF connector (None with RF off): the level capped at the limit (p. 746)."""
        return min(self.level_dbm - self.pow_offs, self.level_limit) if self.rf_on else None

    # ---- transport extras -----------------------------------------------------------------------------------------------------------------------
    def clear(self):
        self.cleared += 1
        self._reply = None

    def go_local(self):
        self.local += 1

    def query(self, text):
        self.write(text)
        return self.read()

    # ---- parser -----------------------------------------------------------------------------------------------------------------------------------
    def _err(self, code, text):
        self.errors.append(f'{code},"{text}"')

    @staticmethod
    def _bool(arg):
        a = arg.strip().upper()
        if a in ('1', 'ON'):
            return True
        if a in ('0', 'OFF'):
            return False
        return None

    def handle(self, cmd):
        self.sent.append(cmd)
        reply = None
        for seg in cmd.split(';'):
            if seg.strip():
                r = self._one(seg.strip())
                if r is not None:
                    reply = r
        return reply

    def _one(self, seg):
        u = seg.upper()
        head, _, arg = u.partition(' ')
        arg = arg.strip()
        if head == '*IDN?': return IDN
        if head == '*OPT?': return self.options
        if head == '*OPC?': return '1'
        if head == '*TST?': return str(self.selftest_code)
        if head == '*CLS':
            self.errors = []
            return None
        if head in ('*RST', ':SYST:PRES', 'SYST:PRES'):
            self.preset()
            return None
        if head in ('SYST:ERR?', ':SYST:ERR?', 'SYST:ERR:NEXT?'):
            return self.errors.pop(0) if self.errors else '0,"No error"'
        h = re.sub(r'^:?OUTP(?:UT)?1?', 'OUTP', head)
        if h in ('OUTP', 'OUTP:STAT'):
            v = self._bool(arg)
            if v is None:
                self._err(-224, 'Illegal parameter value')
            else:
                self.rf_on = v
            return None
        if h in ('OUTP?', 'OUTP:STAT?'):
            return '1' if self.rf_on else '0'
        h = _NODE.sub('', head)
        if h in ('UNIT:POW', ':UNIT:POW'):
            if arg in ('DBM', 'V', 'DBUV'):
                self.unit = arg
            else:
                self._err(-224, 'Illegal parameter value')
            return None
        if h in ('UNIT:POW?', ':UNIT:POW?'):
            return self.unit
        if h == 'ROSC:SOUR':
            if arg[:3] in ('INT', 'EXT'):
                self.ref_source = arg[:3]
            else:
                self._err(-224, 'Illegal parameter value')
            return None
        if h == 'ROSC:SOUR?':
            return self.ref_source
        if h in ('MOD:ALL:STAT', 'MOD', 'MOD:STAT'):
            v = self._bool(arg)
            if v is None:
                self._err(-224, 'Illegal parameter value')
            else:
                self.mod_on = v
            return None
        if h in ('MOD:ALL:STAT?', 'MOD?', 'MOD:STAT?'):
            return '1' if self.mod_on else '0'
        if h in ('FREQ:MODE', 'POW:MODE'):
            if arg not in ('CW', 'FIX', 'FIXED', 'SWE', 'SWEEP', 'LIST', 'COMB'):
                self._err(-224, 'Illegal parameter value')
            elif h == 'FREQ:MODE':
                self.freq_mode = 'CW' if arg.startswith('FIX') else arg[:4]
            else:
                self.pow_mode = 'CW' if arg.startswith('FIX') else arg[:4]
            return None
        if h == 'FREQ:MODE?': return self.freq_mode
        if h == 'POW:MODE?': return self.pow_mode
        if h in ('FREQ:OFFS?',): return f'{self.freq_offs:.12g}'
        if h in ('FREQ:MULT?',): return f'{self.freq_mult:.12g}'
        if h in ('POW:OFFS?',): return f'{self.pow_offs:.12g}'
        if h in ('POW:LIM?', 'POW:LIM:AMPL?'): return f'{self.level_limit:.12g}'
        if h in ('FREQ', 'FREQ:CW', 'FREQ:FIX'):
            v = self._number(arg)
            if v is None:
                return None
            out = (v - self.freq_offs) / self.freq_mult
            if not self.min_hz <= out <= self.max_hz:
                self._err(-222, 'Data out of range')
            else:
                self.freq_hz = round(v, 3)
            return None
        if h in ('FREQ?', 'FREQ:CW?', 'FREQ:FIX?'):
            return f'{self.freq_hz:.12g}'
        if h in ('POW', 'POW:LEV', 'POW:AMPL', 'POW:LEV:IMM:AMPL'):
            v = self._number(arg)
            if v is None:
                return None
            if not self.min_dbm <= v - self.pow_offs <= self.max_dbm:
                self._err(-222, 'Data out of range')
            else:
                self.level_dbm = round(v, 2)
            return None
        if h in ('POW?', 'POW:LEV?', 'POW:AMPL?'):
            return f'{self.level_dbm:.12g}'
        self._err(-113, 'Undefined header')
        return None

    def _number(self, arg):
        try:
            return float(arg)
        except ValueError:
            self._err(-224, 'Illegal parameter value')
            return None


def make_sma100b(**kw):
    """(transport, log) ready for RSSMA100B(transport, log)."""
    from .transport import CommandLog
    return SimSMA100BTransport(**kw), CommandLog()
