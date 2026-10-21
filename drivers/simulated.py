"""Software stand-ins for the real instruments, speaking the same command strings.

Use them to test a procedure with no hardware, to replay a failure, or to check that a driver sends
what you expect. A SimBench links the instruments: the simulated scope "measures" whatever the
simulated calibrator is outputting, so a whole procedure can run end to end.
"""
from __future__ import annotations

import math
import re

from .transport import Transport, TransportError


class SimBench:
    def __init__(self, gain_error=1.0005, offset_v=0.0001):
        self.fluke = dict(operate=False, func='NONE', scope='OFF', volts=0.0, freq=0.0, imp='1M', ohms=50.02)
        self.scope = {}
        self.gain_error, self.offset_v = gain_error, offset_v
        self.fail_next = None        # set to a substring to make the next matching command time out
        self.timebase_ratio = 1 + 1.2e-7     # simulated scope time base error (frequency reads high by 0.12 ppm)
        self.trigger_error_v = 0.0           # simulated trigger level error (actual threshold = set level + this)

    def output_v(self):
        f = self.fluke
        return f['volts'] if f['operate'] and f['scope'] == 'VOLT' else 0.0

    def output_changed(self, old, new):
        """Edge trigger in Single mode: a crossing of (level + error) in the selected slope stops the acquisition."""
        s = self.scope
        if str(s.get('app.Acquisition.TriggerMode', '')).casefold() != 'single':
            return
        if str(s.get('app.Acquisition.Trigger.Type', 'Edge')).casefold() != 'edge':
            return
        threshold = float(s.get('app.Acquisition.Trigger.Edge.Level', 0.0)) + self.trigger_error_v
        slope = str(s.get('app.Acquisition.Trigger.Edge.Slope', 'Positive')).casefold()
        rising = old < threshold <= new
        falling = old > threshold >= new
        if (slope == 'positive' and rising) or (slope == 'negative' and falling):
            s['app.Acquisition.TriggerMode'] = 'Stopped'

    def p1_value(self):
        f, s = self.fluke, self.scope
        engine = s.get('app.Measure.P1.ParamEngine', 'Mean').lower()
        if engine == 'standarddeviation':
            return 1.38e-4
        if engine in ('freq', 'frequency'):
            if not f['operate'] or f['scope'] != 'MARKER' or not f.get('period'):
                return 0.0
            return self.timebase_ratio / f['period']
        if not f['operate']:
            return 0.0
        if engine == 'mean':
            return f['volts'] * self.gain_error + self.offset_v
        return f['volts'] * (0.93 if f['freq'] > 1e8 else 1.001)      # PkPk


class _SimBase(Transport):
    def __init__(self, bench: SimBench, name):
        self.bench, self.name = bench, name
        self._reply = None
        self.opened = False

    def open(self): self.opened = True
    def close(self): self.opened = False

    def write(self, text):
        if not self.opened:
            raise TransportError('simulated port not open')
        b = self.bench
        if b.fail_next and b.fail_next in text:
            b.fail_next = None
            raise TransportError(f'simulated timeout on {text!r}')
        self._reply = self.handle(text.strip())

    def read(self):
        if self._reply is None:
            raise TransportError('simulated read timed out (no pending reply)')
        reply, self._reply = self._reply, None
        return reply


class SimFlukeTransport(_SimBase):
    def __init__(self, bench, model='5560A'):
        super().__init__(bench, f'SIM-{model}')
        self.model = model

    def handle(self, cmd):
        before = self.bench.output_v()
        reply = self._handle(cmd)
        self.bench.output_changed(before, self.bench.output_v())
        return reply

    def _handle(self, cmd):
        f = self.bench.fluke
        u = cmd.upper()
        if u == '*IDN?': return f'FLUKE,{self.model},SIM0001,1.0'
        if u in getattr(self, 'reject', ()):
            self.errors = getattr(self, 'errors', []) + ['-117,"Wrong type of parameter(s)"']
            return None
        if u == 'SCOPE MARKER': f['scope'], f['func'] = 'MARKER', 'SMARK'; return None
        m = re.match(r'OUT\s+([0-9.eE+-]+)S$', u)
        if m and f['scope'] == 'MARKER':
            f['period'] = float(m.group(1)); return None
        if u == 'OUT?' and f['scope'] == 'MARKER': return f"{f.get('period', 0.0):.9E},S"
        if u == 'STBY': f['operate'] = False; return None
        if u == 'OPER': f['operate'] = True; return None
        if u == 'OPER?': return '1' if f['operate'] else '0'
        if u == 'SCOPE DCV': f['scope'], f['func'] = 'VOLT', 'SDCV'; return None
        if u == 'SCOPE VOLT': f['scope'], f['func'] = 'VOLT', 'SDCV'; return None      # 5520A / 5522A scope option
        if u == 'SCOPE SQUARE': f['scope'], f['func'] = 'SQUARE', 'SSQU'; return None
        if u == 'SCOPE LEVSINE': f['scope'], f['func'] = 'LEVSINE', 'SLEV'; return None
        if u == 'SCOPE MEASR': f['scope'], f['func'] = 'MEASR', 'SMEAS'; return None
        if u == 'SCOPE OFF': f['scope'], f['func'] = 'OFF', 'NONE'; return None
        if u == 'SCOPE?': return f['scope']
        if u == 'FUNC?': return f['func']
        if u.startswith('OUT_IMP '): f['imp'] = cmd.split()[1].upper(); return None
        if u == 'OUT_IMP?': return '1000000,OHM' if f['imp'] == '1M' else '50,OHM'
        if u.startswith('TC_TYPE '): f['tc'] = cmd.split()[1].upper(); return None
        m = re.match(r'OUT\s+([-+0-9.eE]+)(V|A|OHM|F|NF|UF|CEL)(?:,\s*([0-9.]+)\s*(HZ|KHZ|MHZ|GHZ))?$', u)
        if m:
            f['volts'] = float(m.group(1))
            f['unit'] = m.group(2)
            if m.group(3):
                f['freq'] = float(m.group(3)) * {'HZ': 1, 'KHZ': 1e3, 'MHZ': 1e6, 'GHZ': 1e9}[m.group(4)]
            return None
        if u == 'OUT?': return f"{f['volts']:.9f},V,{f['freq']:.1f},HZ"
        if u == '*CLS': self.errors = []; self.next_error = None; return None
        if u == 'ERR?':
            queue = getattr(self, 'errors', [])
            if getattr(self, 'next_error', None):          # older tests set one error directly
                queue.insert(0, self.next_error); self.next_error = None
            self.errors = queue
            return queue.pop(0) if queue else '0,"No error"'

        if u == '*TRG':
            term = getattr(self.bench, 'mdo', {}).get('term')
            ohms = {'1M': 1.0004e6, '250k': 250.2e3, '50': 50.01}.get(term, f['ohms'])
            return f"{ohms:.4f},OHM"
        raise TransportError(f'simulated 5560A: unknown command {cmd!r}')

    def query(self, text):
        self.write(text)
        return self.read()


class SimScopeTransport(_SimBase):
    def __init__(self, bench):
        super().__init__(bench, 'SIM-WS4104HD')
        self.bench.scope.update({'app.Acquisition.Trigger.Type': 'Edge'})

    def handle(self, cmd):
        s = self.bench.scope
        if cmd == '*IDN?': return 'LECROY,WS4104HD,SIM0001,9.9'
        m = re.match(r"""VBS\?\s+"return=(.+)"$""", cmd)
        if m:
            path = m.group(1)
            bad = self.bad_path(path)
            if bad:
                return f"VBS Object doesn't support this property or method: '{bad}'"
            if path == 'app.Measure.P1.Out.Result.Value':
                return f'VBS {self.bench.p1_value():.9g}'
            if re.search(r'\.(VerScale|VerOffset|HorScale|Level)$', path):
                return f'VBS {s.get(path, 0.0)}'
            return f"VBS {s.get(path, 'Mean')}"
        m = re.match(r"""VBS\s+'(\S+?)=(.*?)\s*'$""", cmd)
        if m:
            path, value = m.group(1), m.group(2).strip().strip('"')
            if self.bad_path(path):
                return None          # MAUI ignores a write to a property that does not exist
            if path == 'app.Measure.P1.ParamEngine' and value.casefold() == 'freq':
                value = 'Frequency'  # the 4104HD reports the long engine name (seen on the bench, 2026-10-21)
            try:
                s[path] = float(value)
            except ValueError:
                s[path] = value
            return None
        m = re.match(r'(C\d):CPL\s+(\w+)$', cmd)
        if m: s[m.group(1) + ':CPL'] = m.group(2); return None
        m = re.match(r'(C\d):CPL\?$', cmd)
        if m: return f"{m.group(1)}:CPL {s.get(m.group(1) + ':CPL', 'D1M')}"
        raise TransportError(f'simulated scope: unknown command {cmd!r}')

    @staticmethod
    def bad_path(path):
        """Channel objects are C1..C4 only; return the offending object path (as MAUI names it) or None."""
        m = re.match(r'(app\.Acquisition\.C\w*)\.', path)
        if m and not re.fullmatch(r'app\.Acquisition\.C[1-4]', m.group(1)):
            return m.group(1)
        return None

    def query(self, text):
        self.write(text)
        return self.read()


TRUEVOLT = ('34460A', '34461A', '34465A', '34470A')


class SimDmmTransport(_SimBase):
    """Simulated 8846A / 34401A: READ? returns what the simulated calibrator is outputting."""

    def __init__(self, bench, model='8846A'):
        super().__init__(bench, f'SIM-{model}')
        self.model, self.function, self.remote = model, 'VOLT:DC', False

    def handle(self, cmd):
        u = cmd.upper()
        if u == '*IDN?':
            if self.model in TRUEVOLT:
                return f'Keysight Technologies,{self.model},SIM0001,A.03.01-02.40-03.01-00.52-02-01'
            return {'8846A': 'FLUKE,8846A,SIM0001,1.0'}.get(self.model, 'HEWLETT-PACKARD,34401A,SIM0001,11-5-2')
        if u == '*CLS': return None
        if u == 'SYST:ERR?': return '+0,"No error"'
        if u == 'ROUT:TERM?': return getattr(self, 'terminals', 'FRON')
        if re.match(r'^(VOLT|CURR|RES|FRES)(:DC|:AC)?:(NPLC|BAND) ', u) or re.match(r'^FREQ:(RANG:LOW|APER|VOLT:RANG) ', u):
            return None
        if u == 'SYST:REM': self.remote = True; return None
        if u == 'SYST:LOC': self.remote = False; return None
        if u.startswith('CONF:'): self.function = u[5:].split()[0]; return None
        if u.startswith('DET:BAND'): return None
        m = re.match(r'CAL:SEC:STAT (ON|OFF),(\w+)$', u)
        if m: self.secure = m.group(1) == 'ON'; return None
        if u == 'CAL:SEC:STAT?': return '+1' if getattr(self, 'secure', True) else '+0'
        if u.startswith('CAL:VAL '):
            self._cal_err = getattr(self, 'secure', True)
            return None
        if u == 'CAL? ON': return '+1' if getattr(self, '_cal_err', False) else '+0'
        if u == 'CAL:REC': return None
        if u == 'READ?' and self.model in TRUEVOLT:
            f = self.bench.fluke
            if not f['operate']:
                return '+2.000000000E-12'
            if self.function.startswith('FREQ'):
                return f"{f['freq'] * 1.0000002:+.9E}"
            if self.function.startswith(('RES', 'FRES')):
                return f"{f['volts'] * 1.00001:+.9E}"
            return f"{f['volts'] * 1.000002:+.9E}"
        if u == 'READ?':
            f = self.bench.fluke
            return f"{(f['volts'] * 1.00002 if f['operate'] else 1.2e-7):+.9E}"
        raise TransportError(f'simulated DMM: unknown command {cmd!r}')


class SimDacqTransport(_SimBase):
    """Simulated 34970A / 34972A: READ? returns what the simulated calibrator outputs on the configured function.
    `modules` maps slot -> module name (default: a 34901A in slot 2)."""

    def __init__(self, bench, model='34970A', modules=None):
        super().__init__(bench, f'SIM-{model}')
        self.model, self.function, self.remote, self.scan = model, 'VOLT:DC', False, None
        self.modules = modules or {2: '34901A'}
        self.errors = []
        self.sent = []

    def handle(self, cmd):
        u = cmd.upper()
        self.sent.append(cmd)
        if u == '*IDN?':
            return f'Agilent Technologies,{self.model},SIM0001,1.20-1.20-1.00'
        if u == '*CLS': self.errors = []; return None
        if u == 'SYST:ERR?': return self.errors.pop(0) if self.errors else '+0,"No error"'
        if u == 'SYST:REM': self.remote = True; return None
        if u == 'SYST:LOC': self.remote = False; return None
        m = re.match(r'SYST:CTYP\? (\d+)$', u)
        if m:
            mod = self.modules.get(int(m.group(1)) // 100)
            return f'AGILENT TECHNOLOGIES,{mod},0,1.0' if mod else 'AGILENT TECHNOLOGIES,0,0,0'
        m = re.match(r'CONF:([A-Z:]+) (\S+?),\(@(\d+)\)$', u)
        if m:
            self.function = m.group(1); self.scan = None; return None
        if re.match(r'^(VOLT|CURR|RES|FRES)(:DC|:AC)?:(NPLC|BAND) \S+,\(@\d+\)$', u) or re.match(r'^FREQ:(APER|VOLT:RANG) \S+,\(@\d+\)$', u):
            return None
        m = re.match(r'ROUT:SCAN \(@(\d+)\)$', u)
        if m: self.scan = int(m.group(1)); return None
        if u == 'TRIG:SOUR IMM': return None
        if u == 'READ?':
            if self.scan is None:
                self.errors.append('-221,"Settings conflict"'); return '+9.90000000E+37'
            f = self.bench.fluke
            if not f['operate']:
                return '+2.000000000E-12'
            if self.function.startswith('FREQ'):
                return f"{f['freq'] * 1.0000002:+.9E}"
            if self.function.startswith(('RES', 'FRES')):
                return f"{f['volts'] * 1.00001:+.9E}"
            return f"{f['volts'] * 1.000002:+.9E}"
        self.errors.append('-113,"Undefined header"')
        return None


def make_bench(**kw):
    """Returns (bench, fluke_transport, scope_transport)."""
    bench = SimBench(**kw)
    return bench, SimFlukeTransport(bench), SimScopeTransport(bench)


def make_dmm_bench(model='8846A'):
    """Returns (bench, fluke_transport, dmm_transport) for DMM procedures."""
    bench = SimBench()
    return bench, SimFlukeTransport(bench), SimDmmTransport(bench, model)


def make_dacq_bench(model='34970A', cal='5560A', modules=None):
    """Returns (bench, calibrator_transport, dacq_transport) for the 34970A / 34972A procedures."""
    bench = SimBench()
    return bench, SimFlukeTransport(bench, cal), SimDacqTransport(bench, model, modules)
