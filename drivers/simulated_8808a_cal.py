"""Simulated Fluke 8808A WITH its RS-232 calibration dialog, for the guided adjustment's demo mode and its tests.

It extends the verification simulator (drivers/simulated_8808a.py, unchanged) with what drivers/fluke_8808a_cal.py sends: *TER, the six function names, CALREF, the Enter key
(an empty line) and EXIT, following the dialog of Calibration Manual pp. 3-16 / 3-17.  The points of every function come from specs/fluke_8808a_adjustment.json (Table 3-9).

SIMULATION CHOICES that are NOT facts about the real meter (the manual does not say):
  * the reply format of the recommended value ("<value> V, <hz> HZ", unit V / A / OHM / HZ-less, W4 after the 4-wire ohms values), the lead messages being sent with the value,
  * '=>' after CALREF / the first Enter (and '!>' for a refusal) while `cal_prompts` is True; with `cal_prompts = False` the simulated meter says NOTHING for an error (the point just
    does not finish: the driver must report 'indeterminate'),
  * the check at the second Enter: the simulated calibrator (or `bench.external`, a standard the operator connected) must be within 1 % of the reference value, otherwise '!>',
  * constants are recorded per point at the second Enter (`constants`); EXIT inside a function sets `cal_error` and lists the function in `incomplete` (the manual only says CAL ERROR).
Simulated meter and calibrator accept ONLY their own strings; nothing here is evidence.

Test hooks: .refuse_ter ('silent' | 'error' | None), .cal_prompts, .use_list_values (recommend the p. 3-17 / 3-18 list values instead of Table 3-9's), .recommend {step id: value},
.fail_points {step id: '!>'}, .hang_points {step id} (no completion is ever sent), .lead_at ('value' | 'confirm'), .events (every calibration line received, in order), .constants,
.cal_error, .incomplete, .completed.

    bench, cal_t, dmm_t = make_8808a_cal_bench('5522A')
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from .simulated import SimBench
from .simulated_8808a import Sim5522ALimitsTransport, Sim8808ATransport
from .simulated_k2000 import SimFlukeComp

SPEC = Path(__file__).resolve().parent.parent / 'specs' / 'fluke_8808a_adjustment.json'
TOL = 0.01                                  # the simulated meter wants the input within 1 % of the reference (a simulation choice)
UNIT_OF = {'VDC': 'V', 'VAC': 'V', 'ADC': 'A', 'AAC': 'A', 'OHMS': 'OHM', 'FREQ': 'V'}
LEADS = {'ZERO_OPEN': 'Disconnect Test Leads!', 'IMA': 'Connect to mA socket!', 'I2A': 'Connect to 10A socket', 'I10A': 'Connect to 10A socket'}


def _spec():
    return json.loads(SPEC.read_text(encoding='utf-8'))


class Sim8808ACalTransport(Sim8808ATransport):
    def __init__(self, bench, serial='SIM0001', **kw):
        super().__init__(bench, serial, **kw)
        spec = _spec()
        self.steps = {s['id']: s for s in spec['steps']}
        self.by_function = {f['id']: [self.steps[i] for i in f['steps']] for f in spec['functions']}
        self.cal_mode = False
        self.cal_func = None                  # the function being calibrated
        self.cal_i = 0                        # index of the point waiting
        self.cal_state = None                 # None | 'VALUE' | 'CONFIRMED'
        self.ref = None                       # CALREF value (base units) or None
        self.constants = {}                   # step id -> {'ref': reference value, 'input': what the meter saw}
        self.completed, self.incomplete = set(), []
        self.cal_error = False
        self.events = []
        self.refuse_ter = None
        self.cal_prompts = True
        self.use_list_values = False
        self.recommend = {}
        self.fail_points = {}
        self.hang_points = set()
        self.lead_at = 'value'

    # ---- helpers
    def _push(self, text, kind='reply'):
        self.out.append((kind, text))

    def _step(self):
        return self.by_function[self.cal_func][self.cal_i]

    def _value(self, s):
        if s['id'] in self.recommend:
            return float(self.recommend[s['id']])
        if self.use_list_values and s.get('list_value') is not None:
            return float(Decimal(s['list_value']))
        return float(Decimal(s['point']['value']))

    def _recommended_line(self, s):
        v = self._value(s)
        if s['function'] == 'FREQ':
            text = f'{1.9:g} V, {v:g} HZ'
        else:
            hz = {'VAC': 1000, 'AAC': 500}.get(s['function'], 0)
            text = f'{v:g} {UNIT_OF[s["function"]]}, {hz} HZ'
        if s.get('wire') == 4:
            text += ' W4'
        return text

    def _announce(self, s, with_leads=True):
        self._push(self._recommended_line(s))
        if with_leads and s['function'] in ('ADC', 'AAC') and self.lead_at == 'value':
            self._push(LEADS['ZERO_OPEN'] if s['zero'] else LEADS[s['group']])

    def _applied(self):
        """(unit, value, hz) of what is connected to the meter, or None when nothing is applied (calibrator in standby, no external standard)."""
        ext = getattr(self.bench, 'external', None)
        if ext is not None:
            return ext
        f = self.bench.fluke
        if not f['operate']:
            return None
        return f.get('unit', 'V'), float(f['volts']), float(f['freq'])

    def _input_ok(self, s, ref):
        applied = self._applied()
        fn = s['function']
        if s['zero']:
            if fn == 'OHMS':                                                        # 0 ohm from the calibrator or a short
                return applied is None or (applied[0] == 'OHM' and abs(applied[1]) < 1e-3)
            return applied is None or abs(applied[1]) < 1e-12                        # standby / open / short, or a 0 output
        if applied is None:
            return False
        unit, value, hz = applied
        if fn == 'FREQ':
            return unit == 'V' and abs(value - 1.9) <= 0.2 and abs(hz - ref) <= 1e-3 * ref
        want_unit = UNIT_OF[fn]
        if unit != want_unit:
            return False
        if fn in ('VDC', 'ADC') and hz != 0:
            return False
        if fn in ('VAC', 'AAC') and hz <= 0:
            return False
        return abs(value - ref) <= TOL * abs(ref) + 1e-12

    def enter_panel(self, banner=False):
        """The operator pressed the calibration button: the meter is in the calibration mode without any *TER. Whether the real meter then sends the banner is unknown (banner=True simulates it)."""
        self.events.append(('PANEL',))
        self.cal_mode, self.cal_func, self.cal_state, self.cal_error = True, None, None, False
        if banner:
            self._push('Select a Function or input EXIT to QUIT!')

    # ---- the dialog
    def handle(self, cmd):
        u = cmd.strip().upper()
        if u == '*TER':
            self.events.append(('TER',))
            if self.refuse_ter == 'silent':
                return None
            if self.refuse_ter == 'error':
                self.esr |= 0x10
                self._push('!>', 'prompt')
                return None
            self.cal_mode, self.cal_func, self.cal_state, self.cal_error = True, None, None, False
            self._push('Select a Function or input EXIT to QUIT!')
            return None
        if not self.cal_mode:
            return super().handle(cmd)
        return self._cal(u)

    def _refuse(self):
        if self.cal_prompts:
            self._push('!>', 'prompt')
        return None

    def _cal(self, u):
        if u == 'EXIT':
            self.events.append(('EXIT',))
            if self.cal_func is not None:
                self.cal_error = True
                self.incomplete.append(self.cal_func)
            self.cal_mode, self.cal_func, self.cal_state = False, None, None
            return None
        if u in self.by_function and self.cal_func is None:
            self.events.append(('FUNC', u))
            self.cal_func, self.cal_i, self.cal_state, self.ref = u, 0, 'VALUE', None
            self._announce(self._step())
            return None
        if u.startswith('CALREF'):
            m = re.fullmatch(r'CALREF\s+(-?\d+(?:\.\d+)?)', u)
            self.events.append(('CALREF', m.group(1) if m else u))
            if not m or self.cal_state != 'VALUE':
                return self._refuse()
            s = self._step()
            wants = [self._value(s), float(Decimal(s['point']['value']))] + ([float(Decimal(s['list_value']))] if s.get('list_value') is not None else [])
            v = float(m.group(1))
            if all(w != 0 and abs(v - w) > 0.05 * abs(w) for w in wants):      # a SIMULATION CHOICE: near the recommended value, Table 3-9's or the list's
                return self._refuse()
            self.ref = v
            if self.cal_prompts:
                self._push('=>', 'prompt')
            return None
        if u == '':
            return self._enter()
        self.esr |= 0x20
        self._push('?>', 'prompt')
        return None

    def _enter(self):
        if self.cal_func is None:
            return None
        s = self._step()
        if self.cal_state == 'VALUE':
            self.events.append(('ENTER', 1, s['id']))
            self.cal_state = 'CONFIRMED'
            if self.lead_at == 'confirm' and s['function'] in ('ADC', 'AAC'):
                self._push(LEADS['ZERO_OPEN'] if s['zero'] else LEADS[s['group']])
            if self.cal_prompts:
                self._push('=>', 'prompt')
            return None
        if self.cal_state != 'CONFIRMED':
            return None
        self.events.append(('ENTER', 2, s['id']))
        ref = self.ref if self.ref is not None else self._value(s)
        if s['id'] in self.fail_points or not self._input_ok(s, ref):
            if s['id'] in self.fail_points and self.fail_points[s['id']] == 'silent':
                return None
            return self._refuse()
        self._push('WAIT...')
        if s['id'] in self.hang_points:
            return None
        self.constants[s['id']] = {'ref': ref, 'input': self._applied()}
        self.cal_i += 1
        self.ref = None
        points = self.by_function[self.cal_func]
        if self.cal_i >= len(points):
            self.completed.add(self.cal_func)
            self.cal_func, self.cal_state = None, None
            self._push('Select a Function or input EXIT to QUIT!')
        else:
            self.cal_state = 'VALUE'
            self._announce(points[self.cal_i])
        return None


class Sim5522ACompLimits(Sim5522ALimitsTransport, SimFlukeComp):
    """The simulated 5522A: ZCOMP (resistance compensation) plus the output limits of the 8808A verification simulator (AC above 500 kHz refused)."""


def make_8808a_cal_bench(cal='5522A', enforce_cal_limits=True, **dmm_kw):
    """(bench, calibrator transport, 8808A transport).  The 5560A has no ZCOMP, like the real driver set; the 5520A refuses what its published specification lacks."""
    bench = SimBench()
    if cal == '5522A':
        cal_t = Sim5522ACompLimits(bench, cal) if enforce_cal_limits else SimFlukeComp(bench, cal)
    elif cal == '5520A' and enforce_cal_limits:
        from .simulated_5520a import Sim5520ALimitsTransport
        cal_t = Sim5520ALimitsTransport(bench, cal)
    else:
        from .simulated import SimFlukeTransport
        cal_t = SimFlukeTransport(bench, cal)
    return bench, cal_t, Sim8808ACalTransport(bench, **dmm_kw)
