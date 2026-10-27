"""Simulated Keysight 53210A / 53220A / 53230A on the simulated bench (drivers/simulated.py): it "measures" what the simulated 96270A is outputting, or the standard the operator connects.

It speaks the command strings drivers/keysight_53220a.py sends.  What it models (so a wrong sequence is visible on the simulated bench, not only on the real counter):
  * *RST puts the volatile settings back to the Factory state (AC coupling, 1 Mohm, auto-level on ...) but NOT the reference oscillator source / auto / external frequency (non-volatile, PR pp. 361-366)
    and not the error queue (PR p. 443);
  * CONFigure resets the gate, trigger, sample count, auto-level / level and statistics, but not the coupling, impedance, range, filter, noise rejection or probe (PR pp. 117, 204-222);
  * INITiate clears the readings; with TRIG:SOUR BUS the measurement runs on *TRG only (PR pp. 22, 200, 468); statistics are read with CALC:AVER:AVER? / SDEV? / COUN:CURR?;
  * ROSC:SOUR EXT with no 10 MHz on Ext Ref In queues +2009 "No valid external timebase" (bench.ext_ref_present = False);
  * an unknown command queues -113 "Undefined header"; a query with no reply times out (TransportError);
  * the options come from *OPT?; the 53210A has one channel and its microwave input is Channel 2; the pulse / burst functions need Option 150 on a 53230A.
THE REPLY FORMATS ARE ASSUMPTIONS where the Programmer's Reference prints only a shape ("+1.00000000000000E+007", "DC", "0 / 1", the CONF? text): the driver's parser is tolerant of them.

    bench, rf_t, ctr_t = make_53220a_bench('53230A')           # (bench, 96270A transport, counter transport); bench.rf1 is the 96270A state dict

Test hooks: ctr_t.errors, ctr_t.sent, ctr_t.tb_error (internal time base, relative), ctr_t.freq_gain (relative error of a frequency reading), ctr_t.time_offset (s), ctr_t.sd_rel (Std Dev, relative),
ctr_t.sd_time (s), ctr_t.selftest_fail, bench.ext_ref_present, bench.external_signal (the standard the operator connects: {'kind': 'CW' | 'PULSE' | 'BURST', ...}), bench.cable_loss_db.
"""
from __future__ import annotations

import math
import re

from .simulated import SimBench, _SimBase
from .simulated_mdo import SimRF
from .transport import TransportError

OVERFLOW_TEXT = '+9.91000000000000E+37'
DEFAULT_OPTIONS = {'53210A': '0,106,0,0,0', '53220A': '010,115,0,0,400', '53230A': '010,115,150,0,400'}
IDN = {'53210A': 'Agilent Technologies,53210A,MY53000001,3.00-1.19-2.02-5', '53220A': 'Agilent Technologies,53220A,MY53000002,3.00-1.19-2.02-5',
       '53230A': 'Agilent Technologies,53230A,MY53000003,3.00-1.19-2.02-5'}


def _fmt(v):
    return f'{v:+.14E}'


class Sim53220ATransport(_SimBase):
    """The simulated 53210A / 53220A / 53230A."""

    def __init__(self, bench, model='53230A', bus='USB', options=None, rf_key='rf1'):
        super().__init__(bench, f'SIM-{model}')
        self.bus, self.model, self.rf_key = bus, model, rf_key
        self.idn_text = IDN[model]
        self.options = options if options is not None else DEFAULT_OPTIONS[model]
        self.errors = []
        self.sent = []
        self.tb_error = 1.0e-8               # internal time base: +10 ppb (inside the Option 010 limit of +/-50 ppb, and the half limit of 25 ppb)
        self.freq_gain = 1.0e-11             # relative error of a frequency reading
        self.time_offset = 3.0e-11           # seconds: single period, pulse width, time interval
        self.sd_rel = 1.0e-10                # Std Dev of a frequency reading (relative)
        self.sd_time = 5.0e-12               # Std Dev of a time reading (s)
        self.burst_rel = 1.0e-7              # burst frequency error (relative)
        self.sd_burst_rel = 1.0e-6
        self.selftest_fail = False
        self.nv = dict(src='INT', auto=True, ext_freq=10e6)          # non-volatile: survives *RST
        self._factory()

    # ---- state
    def _factory(self):
        self.inp = {1: self._fresh_input(), 2: self._fresh_input()}
        self.func = None
        self.conf = None
        self.gate = dict(src='TIME', time=0.1, mode='AUTO')
        self.samp, self.trig_count, self.trig_delay, self.trig_src = 1, 1, 0.0, 'IMM'
        self.calc, self.aver = False, False
        self.burst = dict(lev=-6.0, narrow=False, auto=True)
        self.armed = False
        self.stats = dict(count=0, mean=0.0, sdev=0.0)

    @staticmethod
    def _fresh_input():
        return dict(coup='AC', imp=1e6, prob=1.0, rang=5.0, filt=False, nrej=False, lev=0.0, auto=True, slop='POS')

    def _conf_reset(self):
        for ch in (1, 2):
            self.inp[ch].update(lev=0.0, auto=True, slop='POS')
        self.gate = dict(src='TIME', time=0.1, mode='AUTO')
        self.samp, self.trig_count, self.trig_delay, self.trig_src = 1, 1, 0.0, 'IMM'
        self.calc = self.aver = False
        self.burst = dict(lev=-6.0, narrow=False, auto=True)
        self.armed = False
        self.stats = dict(count=0, mean=0.0, sdev=0.0)

    def _err(self, text):
        self.errors.append(text)

    # ---- the physics
    def _signal(self):
        """(kind, frequency, level_dbm, extra) of what is at the counter inputs: the 96270A when its output is on, else the standard the operator connected, else None."""
        b = self.bench
        rf = getattr(b, self.rf_key, None)
        loss = getattr(b, 'cable_loss_db', 0.0)
        if rf and rf.get('on'):
            return 'CW', float(rf['f']), float(rf['p']) - loss, {}
        ext = getattr(b, 'external_signal', None)
        if ext:
            return ext.get('kind', 'CW'), float(ext.get('f', 0.0)), float(ext.get('level_dbm', 0.0)) - loss, ext
        return None

    def _timebase_error(self):
        b = self.bench
        if self.nv['src'] == 'EXT' and getattr(b, 'ext_ref_present', True):
            return getattr(b, 'ref_error', 0.0)
        return self.tb_error

    def _channel_ok(self, ch, f):
        """Is there a measurement path on this channel for this frequency?  Channels 1 / 2 (the 53210A: channel 1 only) take up to 350 MHz; the microwave input
        (channel 3, the 53210A: channel 2) needs Option 106 (100 MHz to 6 GHz) or 115 (300 MHz to 15 GHz)."""
        micro = self.MICRO[self.model]
        if ch == micro:
            opt = self.options.split(',')[1].strip() if ',' in self.options else '0'
            if opt == '106':
                return 100e6 <= f <= 6.0e9
            if opt == '115':
                return 300e6 <= f <= 15.0e9
            return False
        if ch == 1 or (ch == 2 and self.model != '53210A'):
            return f <= 350e6
        return False

    def _exists(self, ch):
        return ch == 1 or ch == self.MICRO[self.model] or (ch == 2 and self.model != '53210A')

    MICRO = {'53210A': 2, '53220A': 3, '53230A': 3}

    def _compute(self):
        """Run the configured measurement now: stats for `samp` readings."""
        if self.nv['src'] == 'EXT' and not getattr(self.bench, 'ext_ref_present', True):
            self._err('+2009,"No valid external timebase"')
            return
        sig = self._signal()
        kind = self.func
        n = self.samp
        if sig is None:
            self.stats = dict(count=n, mean=9.91e37, sdev=9.91e37)
            return
        skind, f, level, ext = sig
        e_tb = self._timebase_error()
        ch = self.conf['ch'] if self.conf else 1
        if kind == 'FREQ':
            lo_level = -35.0 if ch == self.MICRO[self.model] else -15.0
            if skind != 'CW' or level < lo_level or not self._channel_ok(ch, f):
                self.stats = dict(count=n, mean=9.91e37, sdev=9.91e37)
                return
            mean = f * (1 + self.freq_gain) * (1 + e_tb)
            self.stats = dict(count=n, mean=mean, sdev=self.sd_rel * f)
        elif kind == 'SPER':
            if skind != 'CW' or level < -15.0 or f <= 0:
                self.stats = dict(count=n, mean=9.91e37, sdev=9.91e37)
                return
            mean = (1.0 / f) * (1 - e_tb) + self.time_offset
            self.stats = dict(count=n, mean=mean, sdev=self.sd_time)
        elif kind in ('PWID', 'TINT'):
            if skind != 'PULSE':
                self.stats = dict(count=n, mean=9.91e37, sdev=9.91e37)
                return
            true = ext['width_s'] if kind == 'PWID' else ext.get('delay_s', 0.0)
            self.stats = dict(count=n, mean=true + self.time_offset, sdev=self.sd_time)
        elif kind == 'BURST':
            width = ext.get('burst_width_s', 0.0) if skind == 'BURST' else 0.0
            if skind != 'BURST' or (width < 1e-6) != self.burst['narrow'] or not self._channel_ok(self.MICRO[self.model], f):      # narrow mode is for bursts under 1 us (the 200 / 400 ns tests)
                self.stats = dict(count=n, mean=9.91e37, sdev=9.91e37)
                return
            self.stats = dict(count=n, mean=f * (1 + self.burst_rel) * (1 + e_tb), sdev=self.sd_burst_rel * f)

    # ---- command handling
    def handle(self, cmd):
        u = cmd.strip().upper()
        self.sent.append(cmd.strip())
        if u == '*IDN?':
            return self.idn_text
        if u == '*OPT?':
            return self.options
        if u == '*RST':
            self._factory(); return None
        if u == '*CLS':
            self.errors = []; return None
        if u == '*OPC?':
            return '1'
        if u in ('SYST:ERR?', 'SYSTEM:ERROR?'):
            return self.errors.pop(0) if self.errors else '+0,"No error"'
        if u == '*TST?':
            fail = self.selftest_fail
            self._factory()
            if fail:
                self._err('+2001,"Self-test failed"')
            return '+1' if fail else '+0'
        if u == '*TRG':
            if self.armed and self.trig_src == 'BUS':
                self.armed = False
                self._compute()
            else:
                self._err('-211,"Trigger ignored"')
            return None
        if u == 'INIT':
            self.stats = dict(count=0, mean=0.0, sdev=0.0)
            if self.conf is None:
                self._err('-221,"Settings conflict"'); return None
            self.armed = True
            if self.trig_src == 'IMM':
                self.armed = False
                self._compute()
            return None
        if u.startswith('CONF'):
            return self._conf(u)
        if u.startswith('SENS:ROSC') or u.startswith('ROSC'):
            return self._rosc(re.sub(r'^SENS:', '', u))
        m = re.match(r'^INP(\d)?:(.+)$', u)
        if m:
            return self._input(int(m.group(1) or 1), m.group(2))
        m = re.match(r'^(?:SENS:)?FREQ:(.+)$', u)
        if m:
            return self._gate(m.group(1))
        m = re.match(r'^(SAMP:COUN|TRIG:COUN|TRIG:DEL|TRIG:SOUR)(\?)?(?:\s+(\S+))?$', u)
        if m:
            return self._trig(m.group(1), bool(m.group(2)), m.group(3))
        m = re.match(r'^CALC(?:1)?:(AVER:STAT|STAT|AVER:AVER\?|AVER:SDEV\?|AVER:COUN:CURR\?)(\?)?(?:\s+(\S+))?$', u)
        if m:
            return self._calc(m.group(1), bool(m.group(2)), m.group(3))
        self._err('-113,"Undefined header"')
        return None

    def _conf(self, u):
        m = re.match(r'^CONF:FREQ:BURS\s+\(@(\d)\)$', u)
        if m:
            if self.model != '53230A' or '150' not in self.options:
                self._err('-241,"Hardware missing"'); return None
            self._set_conf('BURST', int(m.group(1)), None); return None
        m = re.match(r'^CONF:FREQ\s+([-+0-9.eE]+),DEF,\(@(\d)\)$', u)
        if m:
            ch, f = int(m.group(2)), float(m.group(1))
            if not self._exists(ch):
                self._err('-222,"Data out of range"'); return None
            self._set_conf('FREQ', ch, f); return None
        m = re.match(r'^CONF:SPER\s+\(@(\d)\)$', u)
        if m:
            if self.model == '53210A':
                self._err('-113,"Undefined header"'); return None
            self._set_conf('SPER', int(m.group(1)), None); return None
        m = re.match(r'^CONF:PWID\s+([-+0-9.eE]+)V,\(@(\d)\)$', u)
        if m:
            if self.model == '53210A':
                self._err('-113,"Undefined header"'); return None
            self._set_conf('PWID', int(m.group(2)), None)
            for c in (1, 2):
                self.inp[c].update(auto=False, lev=float(m.group(1)))          # a reference level in volts disables auto-level (PR p. 143)
            return None
        if u == 'CONF:TINT (@1),(@2)':
            if self.model == '53210A':
                self._err('-113,"Undefined header"'); return None
            self._set_conf('TINT', 1, None); return None
        if u == 'CONF?':
            if self.conf is None:
                self._err('-221,"Settings conflict"'); return None
            f, ch = self.conf['func'], self.conf['ch']
            if f == 'FREQ':
                return f'"FREQ {_fmt(self.conf["expected"])},{_fmt(1e-3)},(@{ch})"'
            if f == 'TINT':
                return '"TINT (@1),(@2)"'
            if f == 'BURST':
                return f'"FREQ:BURS (@{ch})"'
            return f'"{f} (@{ch})"'
        self._err('-113,"Undefined header"')
        return None

    def _set_conf(self, func, ch, expected):
        self._conf_reset()
        self.func = func
        self.conf = dict(func=func, ch=ch, expected=expected)
        self.stats = dict(count=0, mean=0.0, sdev=0.0)

    def _rosc(self, u):
        m = re.match(r'^ROSC:(SOUR:AUTO|SOUR|EXT:FREQ|EXT:CHEC)(\?)?(?:\s+(\S+))?$', u)
        if not m:
            self._err('-113,"Undefined header"'); return None
        what, q, arg = m.group(1), bool(m.group(2)), m.group(3)
        nv = self.nv
        if what == 'SOUR:AUTO':
            if q:
                return '1' if nv['auto'] else '0'
            nv['auto'] = arg in ('1', 'ON'); return None
        if what == 'SOUR':
            if q:
                if nv['auto']:
                    return 'EXT' if getattr(self.bench, 'ext_ref_present', True) else 'INT'
                return nv['src']
            nv['src'] = 'EXT' if arg.startswith('EXT') else 'INT'; nv['auto'] = False; return None
        if what == 'EXT:FREQ':
            if q:
                return _fmt(nv['ext_freq'])
            nv['ext_freq'] = float(arg); return None
        if what == 'EXT:CHEC':
            if nv['src'] != 'EXT' or nv['auto']:
                self._err('-221,"Settings conflict"'); return None
            if not getattr(self.bench, 'ext_ref_present', True):
                self._err('+2009,"No valid external timebase"')
            return None
        return None

    def _input(self, ch, rest):
        if ch == 3:
            m = re.match(r'^BURS:LEV(\?)?(?:\s+(\S+))?$', rest)
            if m and self.model == '53230A' and '150' in self.options:
                if m.group(1):
                    return _fmt(self.burst['lev'])
                self.burst['lev'] = float(m.group(2)); return None
            self._err('-241,"Hardware missing"'); return None
        if ch not in (1, 2) or (ch == 2 and self.model == '53210A'):
            self._err('-241,"Hardware missing"'); return None
        i = self.inp[ch]
        m = re.match(r'^(COUP|IMP|PROB|RANG|FILT|NREJ|LEV:AUTO|LEV|SLOP)(\?)?(?:\s+(\S+))?$', rest)
        if not m:
            self._err('-113,"Undefined header"'); return None
        what, q, arg = m.group(1), bool(m.group(2)), m.group(3)
        key = {'COUP': 'coup', 'IMP': 'imp', 'PROB': 'prob', 'RANG': 'rang', 'FILT': 'filt', 'NREJ': 'nrej', 'LEV:AUTO': 'auto', 'LEV': 'lev', 'SLOP': 'slop'}[what]
        if q:
            v = i[key]
            if key in ('filt', 'nrej', 'auto'):
                return '1' if v else '0'
            if key in ('coup', 'slop'):
                return v
            return _fmt(v)
        if key in ('filt', 'nrej'):
            i[key] = arg in ('1', 'ON')
        elif key == 'auto':
            i[key] = arg in ('1', 'ON')
        elif key == 'coup':
            i[key] = 'DC' if arg.startswith('DC') else 'AC'
        elif key == 'slop':
            i[key] = 'POS' if arg.startswith('POS') else 'NEG'
        elif key == 'imp':
            i[key] = 50.0 if float(arg) <= 75 else 1e6
        else:
            i[key] = float(arg)
            if key == 'lev':
                i['auto'] = False                 # setting a level disables auto-level (PR p. 213)
        return None

    def _gate(self, rest):
        m = re.match(r'^(GATE:SOUR|GATE:TIME|MODE|BURS:GATE:NARR|BURS:GATE:AUTO)(\?)?(?:\s+(\S+))?$', rest)
        if not m:
            self._err('-113,"Undefined header"'); return None
        what, q, arg = m.group(1), bool(m.group(2)), m.group(3)
        if what.startswith('BURS'):
            if not (self.model == '53230A' and '150' in self.options):
                self._err('-241,"Hardware missing"'); return None
            key = 'narrow' if what.endswith('NARR') else 'auto'
            if q:
                return '1' if self.burst[key] else '0'
            self.burst[key] = arg in ('1', 'ON'); return None
        key = {'GATE:SOUR': 'src', 'GATE:TIME': 'time', 'MODE': 'mode'}[what]
        if q:
            return _fmt(self.gate['time']) if key == 'time' else self.gate[key]
        if key == 'time':
            self.gate['time'] = float(arg)
        else:
            self.gate[key] = arg[:4] if key == 'src' else arg[:4]
            if key == 'src' and arg.startswith('TIME'):
                self.gate['src'] = 'TIME'
        return None

    def _trig(self, what, q, arg):
        attr = {'SAMP:COUN': 'samp', 'TRIG:COUN': 'trig_count', 'TRIG:DEL': 'trig_delay', 'TRIG:SOUR': 'trig_src'}[what]
        if q:
            v = getattr(self, attr)
            return v if attr == 'trig_src' else f'{v:+.0f}' if attr != 'trig_delay' else _fmt(v)
        if attr == 'trig_src':
            self.trig_src = 'BUS' if arg.startswith('BUS') else 'EXT' if arg.startswith('EXT') else 'IMM'
        elif attr == 'trig_delay':
            self.trig_delay = float(arg)
        else:
            setattr(self, attr, int(round(float(arg))))
        return None

    def _calc(self, what, q, arg):
        if what == 'STAT':
            if q:
                return '1' if self.calc else '0'
            self.calc = arg in ('1', 'ON'); return None
        if what == 'AVER:STAT':
            if q:
                return '1' if self.aver else '0'
            self.aver = arg in ('1', 'ON'); self.stats = dict(count=0, mean=0.0, sdev=0.0); return None
        if what == 'AVER:AVER?':
            return _fmt(self.stats['mean']) if self.calc and self.aver else _fmt(0.0)
        if what == 'AVER:SDEV?':
            return _fmt(self.stats['sdev']) if self.calc and self.aver else _fmt(0.0)
        if what == 'AVER:COUN:CURR?':
            return f'{self.stats["count"]:+d}' if self.calc and self.aver else '+0'
        return None

    def query(self, text):
        self.write(text)
        return self.read()


class SimRF27(SimRF):
    """The simulated 96270A of this procedure (the Leveling Head / Microwave O/P route is not modelled: the level range of SimRF applies)."""


def make_53220a_bench(model='53230A', bus='USB', options=None):
    """(bench, 96270A transport, counter transport).  bench.rf1 is the 96270A state, bench.ext_ref_present (default True) the 10 MHz on Ext Ref In, bench.external_signal the standard
    the operator connects (default None), bench.cable_loss_db (default 0)."""
    bench = SimBench()
    bench.ext_ref_present = True
    bench.ref_error = 0.0
    bench.external_signal = None
    bench.cable_loss_db = 0.0
    rf = SimRF27(bench, 'rf1')
    ctr = Sim53220ATransport(bench, model, bus, options)
    return bench, rf, ctr
