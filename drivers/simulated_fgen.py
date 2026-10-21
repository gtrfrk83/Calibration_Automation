"""Software stand-ins for the function-generator bench: a 33210A / 33220A / 33250A, a Fluke 5790B, a frequency counter and
an RF power meter, all speaking the same command strings as the real instruments.

    bench, t = make_fgen_bench('33220A')      # t: dict(uut=, std=, counter=, power=) transports for fgen_verification.IO

The bench links them: the 5790B, counter and power meter "measure" whatever the simulated generator is putting out, with small
deterministic errors, the 5790B input impedance (10 MOhm on 2.2 V and below, 50 kOhm on 7 V and above, as in the 5790B
Operators Manual Table 4-4) and an optional -20 dB attenuator in front of the power sensor.
Wideband: bench.connected = 'wbnd' with the 5790B on WBND (50 ohm); bench.std_option = '0' for a 5790B without the option.
Faults to try: bench.gen['stuck_on'] (output ignores OUTP OFF), bench.gen['selftest_fail'], bench.attenuator = False on the
+20 dB range, bench.std_unsettled (number of MEAS? replies flagged unsettled before a valid one).
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, _SimBase
from .transport import TransportError

GEN_MAX_HZ = {'33210A': 10e6, '33220A': 20e6, '33250A': 80e6}
STD_RANGES = (2.2e-3, 7e-3, 22e-3, 70e-3, 220e-3, 700e-3, 2.2, 7.0, 22.0, 70.0, 220.0, 700.0, 1000.0)


def std_impedance(range_hi):
    return 10e6 if range_hi <= 2.2 else 50e3


class FgenBench(SimBench):
    def __init__(self, model='33220A'):
        super().__init__()
        self.model = model
        self.gen = dict(func='SIN', freq=1e3, amp=0.1, unit='VPP', load=50.0, offs=0.0, auto=True, on=False, errors=[],
                        stuck_on=False, selftest_fail=False)
        self.std = dict(input='INPUT1', extrig=False, range=7.0, auto=True, errors=[], unsettled_left=0)
        self.std_option = 'WBND'        # *OPT? reply: '0' (none), WBND (30 MHz), WBEX / WBAF (50 MHz)
        self.wbaf_on = False
        self.std_unsettled = 2
        self.attenuator = False
        self.connected = 'std'          # which reference the generator output is cabled to: std / wbnd / counter / power
        self.gain = 1.0012              # generator amplitude error
        self.ppm = 1.3e-6               # generator timebase error
        self.ppm_counter = 0.05e-6      # counter internal timebase error
        self.counter_model = '53132A'   # any other name: a generic counter that answers only MEAS:FREQ?

    # ---- the generator's real output -------------------------------------------------------------------
    def flat_db(self, f):
        """Deterministic amplitude roll-off, well inside every model's flatness limit."""
        return -0.02 * (f / 20e6) - 0.004 * math.sin(f / 3.1e6)

    def open_circuit_vrms(self):
        g = self.gen
        if not g['on']:
            return 0.0
        a, unit = g['amp'], g['unit']
        r_load = 1e40 if g['load'] > 1e37 else g['load']
        if unit == 'DBM':
            v_load = math.sqrt(10 ** (a / 10) * 1e-3 * 50.0)            # dBm are defined into 50 ohms
        elif unit == 'VPP':
            v_load = a / (2 * math.sqrt(2)) if g['func'] == 'SIN' else a / 2
        else:
            v_load = a
        v_open = v_load * (r_load + 50.0) / r_load if r_load < 1e39 else v_load
        return v_open * self.gain * 10 ** (self.flat_db(g['freq']) / 20)

    def vrms_into(self, r):
        return self.open_circuit_vrms() * r / (r + 50.0)


class SimGen(_SimBase):
    def __init__(self, bench):
        super().__init__(bench, f'SIM-{bench.model}')

    def handle(self, cmd):
        g, u = self.bench.gen, cmd.upper()
        err = g['errors']
        if u == '*IDN?': return f'Agilent Technologies,{self.bench.model},SIM0001,1.00-1.00'
        if u == '*CLS': err.clear(); return None
        if u in ('SYST:ERR?', 'SYSTEM:ERROR?'): return err.pop(0) if err else '+0,"No error"'
        if u == '*TST?':
            g['on'] = False
            if g['selftest_fail']: err.append('+625,"Self-test failed; I/O processor"'); return '1'
            return '0'
        if u.startswith('APPL'):
            raise TransportError('simulated generator: APPLy must not be used (it enables the output)')
        m = re.match(r'OUTP(?:UT)?\s+(ON|OFF|1|0)$', u)
        if m: g['on'] = (m.group(1) in ('ON', '1')) or g['stuck_on']; return None
        if u in ('OUTP?', 'OUTPUT?'): return '1' if g['on'] else '0'
        m = re.match(r'OUTP(?:UT)?:LOAD\s+(\S+)$', u)
        if m:
            v = m.group(1)
            if v.startswith('INF'):
                if g['unit'] == 'DBM': g['unit'] = 'VPP'
                g['load'] = 9.9e37
            else:
                g['load'] = float(v)
            return None
        if u == 'OUTP:LOAD?': return f"{g['load']:.6E}"
        m = re.match(r'FUNC(?:TION)?\s+(\w+)$', u)
        if m: g['func'] = m.group(1)[:3]; return None
        if u == 'FUNC?': return g['func']
        m = re.match(r'VOLT:OFFS\s+(\S+)$', u)
        if m: g['offs'] = float(m.group(1)); return None
        if u == 'VOLT:OFFS?': return f"{g['offs']:+.6E}"
        m = re.match(r'VOLT:RANG:AUTO\s+(\w+)$', u)
        if m: g['auto'] = m.group(1) in ('ON', '1'); return None
        if u == 'VOLT:RANG:AUTO?': return '1' if g['auto'] else '0'
        m = re.match(r'VOLT:UNIT\s+(\w+)$', u)
        if m:
            if m.group(1) == 'DBM' and g['load'] > 1e37:
                err.append('-221,"Settings conflict; cannot specify dBm when load is High Z"'); return None
            g['unit'] = m.group(1); return None
        if u == 'VOLT:UNIT?': return g['unit']
        m = re.match(r'FREQ\s+(\S+)$', u)
        if m:
            f = float(m.group(1))
            if f > GEN_MAX_HZ[self.bench.model] and g['func'] == 'SIN':
                err.append('-222,"Data out of range; frequency"'); return None
            g['freq'] = f; return None
        if u == 'FREQ?': return f"{g['freq']:+.12E}"
        m = re.match(r'VOLT\s+(\S+)$', u)
        if m: g['amp'] = float(m.group(1)); return None
        if u == 'VOLT?': return f"{g['amp']:+.6E}"
        raise TransportError(f'simulated generator: unknown command {cmd!r}')


class SimStd(_SimBase):
    """Fluke 5790B."""
    def __init__(self, bench):
        super().__init__(bench, 'SIM-5790B')

    def handle(self, cmd):
        b, s, u = self.bench, self.bench.std, cmd.upper()
        if u == '*IDN?': return 'FLUKE,5790B,SIM0001, v1.08+v1.01 FPGAv4'
        if u == '*CLS': s['errors'].clear(); return None
        if u == '*OPT?': return b.std_option
        if u == 'WBAF?': return '1' if b.wbaf_on else '0'
        if u == 'ERR?': return s['errors'].pop(0) if s['errors'] else '0,"No Error"'
        m = re.match(r'INPUT\s+(\w+)$', u)
        if m:
            if m.group(1) == 'WBND' and b.std_option == '0':
                s['errors'].append('303,"Option not installed"'); return None
            s['input'] = m.group(1); return None
        if u == 'INPUT?': return s['input']
        m = re.match(r'EXTRIG\s+(\w+)$', u)
        if m: s['extrig'] = m.group(1) in ('ON', '1'); return None
        if u == 'EXTRIG?': return '1' if s['extrig'] else '0'
        if u == 'RANGE AUTO': s['auto'] = True; return None
        m = re.match(r'RANGE\s+([-+0-9.eE]+)$', u)
        if m:
            v = float(m.group(1))
            s['range'] = next((r for r in STD_RANGES if v <= r), STD_RANGES[-1]); s['auto'] = False
            s['unsettled_left'] = b.std_unsettled; return None
        if u == 'RANGE?':
            i = STD_RANGES.index(s['range'])
            lo = STD_RANGES[i - 1] * 0.95 if i else 0.0
            return f"{s['range']:.6E},{lo:.6E},{s['range'] * 1e-6:.6E},{1 if s['auto'] else 0}"
        if u == 'MEAS?':
            if s['unsettled_left'] > 0:
                s['unsettled_left'] -= 1
                return f'{0.0:.7E},{b.gen["freq"]:.6E},4'
            wide = s['input'] == 'WBND'
            if (b.connected, s['input']) not in (('std', 'INPUT1'), ('wbnd', 'WBND')):
                return f'{1e-6:.7E},{0.0:.6E},1'
            v = b.vrms_into(50.0 if wide else std_impedance(s['range']))
            if wide and s['range'] > 7.0:
                return f'{v:.7E},{b.gen["freq"]:.6E},7'
            if v > s['range'] * 1.01:
                return f'{v:.7E},{b.gen["freq"]:.6E},6'
            if b.gen['freq'] < 10 or v == 0:
                return f'{v:.7E},{0.0:.6E},1'
            return f'{v:.7E},{b.gen["freq"]:.6E},0'
        raise TransportError(f'simulated 5790B: unknown command {cmd!r}')


class SimCounter(_SimBase):
    """53131A / 53132A (bench.counter_model); any other model name answers only the generic MEAS:FREQ? query."""
    def __init__(self, bench):
        super().__init__(bench, 'SIM-COUNTER')
        bench.counter = self.st = dict(func='FREQ', imp=1e6, coup='AC', start='IMM', stop='TIM', gate=0.1, exp=None,
                                       rosc='INT', auto=True, ext_ref=True, ext_lost=False, check='ON', errors=[])

    def _reading(self):
        b, s = self.bench, self.st
        if not b.gen['on'] or b.connected != 'counter' or (s['func'] != 'FREQ'):
            s['errors'].append('-230,"Data corrupt or stale"'); return '+9.91000000000E+37'
        if s['exp'] is not None and abs(b.gen['freq'] / s['exp'] - 1) > 0.1:
            s['errors'].append('-230,"Data corrupt or stale"'); return '+9.91000000000E+37'
        if s['rosc'] == 'EXT' and s['check'] == 'ON' and (s['ext_lost'] or not s['ext_ref']):
            s['errors'].append('+2009,"No valid external timebase"')
        ppm = 0.02e-6 if s['rosc'] == 'EXT' else b.ppm_counter
        return f"{b.gen['freq'] * (1 + b.ppm) * (1 + ppm):+.15E}"

    def handle(self, cmd):
        b, s, u = self.bench, self.st, cmd.upper().lstrip(':')
        if u == '*IDN?': return f'HEWLETT-PACKARD,{b.counter_model},0,4806'
        if u == '*CLS': s['errors'].clear(); return None
        if u in ('MEASURE:FREQUENCY?', 'MEAS:FREQ?'):
            return self._reading()
        if b.counter_model not in ('53131A', '53132A'):
            raise TransportError(f'simulated counter: unknown command {cmd!r}')
        if u == 'SYST:ERR?': return s['errors'].pop(0) if s['errors'] else '+0,"No error"'
        if u == '*TST?': return '+0'
        m = re.match(r'FUNC\s+"FREQ\s*(\d?)"$', u)
        if m: s['func'] = 'FREQ' if m.group(1) in ('', '1') else f'FREQ {m.group(1)}'; return None
        if u == 'FUNC?': return f'"{s["func"]}"'
        m = re.match(r'INP1:IMP\s+(\S+)$', u)
        if m: s['imp'] = float(m.group(1)); return None
        if u == 'INP1:IMP?': return f"{s['imp']:+.5E}"
        m = re.match(r'INP1:COUP\s+(AC|DC)$', u)
        if m: s['coup'] = m.group(1); return None
        if u == 'INP1:COUP?': return s['coup']
        m = re.match(r'FREQ:ARM:STAR:SOUR\s+(\w+)$', u)
        if m: s['start'] = m.group(1)[:3]; return None
        if u == 'FREQ:ARM:STAR:SOUR?': return s['start']
        m = re.match(r'FREQ:ARM:STOP:SOUR\s+(\w+)$', u)
        if m: s['stop'] = m.group(1)[:3]; return None
        if u == 'FREQ:ARM:STOP:SOUR?': return s['stop']
        m = re.match(r'FREQ:ARM:STOP:TIM\s+(\S+)$', u)
        if m: s['gate'] = float(m.group(1)); return None
        if u == 'FREQ:ARM:STOP:TIM?': return f"{s['gate']:+.5E}"
        m = re.match(r'FREQ:EXP1\s+(\S+)$', u)
        if m: s['exp'] = float(m.group(1)); return None
        if u == 'FREQ:EXP1?': return f"{s['exp']:+.14E}" if s['exp'] is not None else '+9.91000000000E+37'
        m = re.match(r'ROSC:SOUR\s+(INT|EXT)$', u)
        if m: s['rosc'] = m.group(1); s['auto'] = False; return None
        if u == 'ROSC:SOUR?': return s['rosc'] if not s['auto'] else ('EXT' if s['ext_ref'] else 'INT')
        if u == 'ROSC:SOUR:AUTO?': return '1' if s['auto'] else '0'
        m = re.match(r'ROSC:EXT:CHEC\s+(ON|OFF|ONCE)$', u)
        if m:
            if m.group(1) == 'ONCE':
                if s['rosc'] != 'EXT': s['errors'].append('-221,"Settings conflict"')
                elif not s['ext_ref']: s['errors'].append('+2009,"No valid external timebase"')
                s['check'] = 'OFF'
            else:
                s['check'] = m.group(1)
            return None
        if u == 'ROSC:EXT:CHEC?': return s['check']
        if u == 'ROSC:EXT:FREQ?': return '+1.00000E+07' if (s['rosc'] == 'EXT' and s['ext_ref']) else '+9.91000E+37'
        if u == 'READ?': return self._reading()
        raise TransportError(f'simulated counter: unknown command {cmd!r}')


class SimPowerMeter(_SimBase):
    def __init__(self, bench):
        super().__init__(bench, 'SIM-POWER')

    def handle(self, cmd):
        b, u = self.bench, cmd.upper()
        if u == '*IDN?': return 'Agilent Technologies,E4418B,SIM0001,A1.08.00'
        if u == '*CLS': return None
        if u in ('MEASURE:POWER?', 'MEAS:POW?'):
            if b.connected != 'power':
                return '-9.9E+37'
            v = b.vrms_into(50.0)
            if v <= 0:
                return '-7.0E+01'
            dbm = 10 * math.log10(v * v / 50.0 / 1e-3) - (20.0 if b.attenuator else 0.0)
            return f'{dbm:+.6E}'
        raise TransportError(f'simulated power meter: unknown command {cmd!r}')


def make_fgen_bench(model='33220A'):
    """Returns (bench, transports) for fgen_verification.IO(..., transports=...). Keys: uut, std, counter, power."""
    bench = FgenBench(model)
    return bench, dict(uut=SimGen(bench), std=SimStd(bench), counter=SimCounter(bench), power=SimPowerMeter(bench))
