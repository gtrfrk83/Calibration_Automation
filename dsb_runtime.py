"""Datasheet Builder, stage C: run a saved user-built datasheet as a procedure.

    python Procedures/User_Datasheet.py --spec <user_specs/....json> [--demo] [--asset ID] [--period 1y]      (the Manager passes --spec)

A saved datasheet is a 'manual-reading' spec with the additive 'dsb' extension (datasheet_builder_specs.export_spec).  This module runs it with the
EXISTING handheld engine (handheld_dmm.App / IO): function prompts, reading padding, direct high voltage, explicit 0 Hz DC, reset-before-tests
(reset_startup), standby after every point, As Found / As Left, checkpoint / resume, procedure modifications and the PDF report with TAR / TUR are the
engine's own code.  What this module adds is only what the stock engine cannot do:

  * ROUTING (route_for): for every point, which standard does the work.  The datasheet assigns one (step.dsb.assignment); the runner uses it when it is
    connected and its driver can do the function (datasheet_builder_match.automation_status: 'ok' / 'unverified').  Otherwise it falls back to the
    calibrator chosen in the engine's own calibrator box, then to any other connected standard that can; when none can, the point degrades to FULLY
    MANUAL (the operator sets the stimulus / reads the standard) and the report says so.  Nothing is guessed.
  * DMM-type points (DCV ACV DCI ACI OHM2 OHM4 CAP FREQ PERIOD TEMP DIODE CONT): the stock engine drives the routed calibrator; the operator types the reading.
  * SCOPE points (gain, offset, bandwidth, time base, trigger): the calibrator's scope option sources the signal exactly as tds2000c_verification
    does it (its Runner methods are imported and used: SCOPE DCV / VOLT + OUT_IMP, DC with an explicit 0 Hz and FUNC? = SDCV, leveled sine, time marker);
    the operator types what the scope shows (trigger: yes / no).
  * GENERATOR points (the unit under test OUTPUTS: amplitude, frequency, offset, flatness): the operator sets the generator (prompted); the routed
    measuring standard reads it automatically when its driver can - a 5790B for amplitude / flatness, a 53131A / 53132A for frequency, using
    fgen_verification's reading code - else the operator types the standard's reading.
  * Every instrument write is the driver's set / read back / compare; nothing is retried; outputs go to standby / off after every point.

Nothing in the datasheet, the matcher, the engine's limit tables or pass / fail logic is changed here.  Demo mode is the engine's demo mode: no commands,
synthetic readings that are labelled as demo everywhere, reports marked as demo data.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import appdata
import drivers
import fgen_verification as fg
import handheld_dmm as hh
import reset_startup
import tds2000c_verification as tds
import ui_theme as ui
import datasheet_builder as db
import datasheet_builder_match as dm
import datasheet_builder_specs as dsp
import procspec

SCOPE_KINDS = ('SCOPE_GAIN', 'SCOPE_OFFSET', 'SCOPE_BW', 'SCOPE_TIMEBASE', 'SCOPE_TRIGGER')
SCOPE_OPS = {'SCOPE_GAIN': 'scope_dc', 'SCOPE_OFFSET': 'scope_dc', 'SCOPE_BW': 'scope_bw', 'SCOPE_TIMEBASE': 'scope_marker', 'SCOPE_TRIGGER': 'scope_trigger'}
LEVEL_KINDS = ('GEN_AMPL', 'ACV')                     # a measuring standard reads an AC level (V rms)
FREQ_KINDS = ('GEN_FREQ', 'FREQ', 'PERIOD')           # ... or a frequency / period
GROUP = {'scope_dc': 'SCOPE_DC', 'scope_bw': 'SCOPE_SINE', 'scope_trigger': 'SCOPE_SINE', 'scope_marker': 'SCOPE_MARKER'}
SOURCE_MODELS = ('5560A', '5522A')
COUNTERS = ('53131A', '53132A')
REF_HZ = {'scope_bw': 50e3, 'std_flat': 1e3}          # default reference frequency (step.dsb.stimulus.settings['ref_frequency'] overrides; the model has no field for it yet)
WIDEBAND_ABOVE_HZ = 1e6                               # 5790B: INPUT1 up to here, the WIDEBAND input above (UNVERIFIED assumption; settings['std_input'] overrides)
COUNTER_GATE_S = 1.0
STD_INPUT_TEXT = {'INPUT1': 'INPUT 1', 'INPUT2': 'INPUT 2', 'WBND': 'WIDEBAND'}


class SpecProblem(ValueError):
    pass


# ============================================================================================================== spec / points
def load_spec(path) -> dict:
    """A user-built spec file: procspec.load (engine schema + dsb extension) and it must carry the dsb header."""
    spec = procspec.load(path)
    if not isinstance(spec.get('dsb'), dict):
        raise SpecProblem(f'{path}: this is not a user-built datasheet (no dsb header).')
    return spec


def with_plan(spec, db_path=None) -> dict:
    """The spec with the standards plan in it.  datasheet_builder.save() exports the runnable spec WITHOUT a matcher plan (only the author's overrides are
    in the steps), so a spec file normally has no 'dsb.plan': the matcher is run here, on the datasheet the spec carries, for the period the spec shows
    (specification rows from lab_registry.sqlite3, read only), and every step gets its assignment (standard, automation status, TAR / TUR / uncertainty).
    A spec that already has a plan is returned unchanged; when the matcher cannot run the spec is returned unchanged and the points fall back to the
    engine's calibrator choice or to manual."""
    head = spec['dsb']
    if head.get('plan'):
        return spec
    ds = dsp.datasheet_from_spec(spec)
    if ds is None:
        return spec
    try:
        res = dm.match_datasheet(ds, period=head.get('period'), db_path=db_path)
    except Exception:
        return spec
    new = copy.deepcopy(spec)
    for step in new['steps']:
        a = res.assignments.get((step.get('dsb') or {}).get('point_id'))
        if a is not None and 'dsb' in step:
            step['dsb']['assignment'] = a.to_dict()
    new['dsb']['plan'] = res.to_dict()
    return new


def spec_for_period(spec, period) -> dict:
    """The same spec with the limits of another time period, re-exported from the datasheet the spec carries (so limits, printed accuracy and the
    tolerance text all agree).  The standards plan and every step's assignment are kept.  Raises SpecProblem when that is not possible."""
    head = spec['dsb']
    if period == head.get('period'):
        return spec
    ds = dsp.datasheet_from_spec(spec)
    if ds is None:
        raise SpecProblem('This spec carries no datasheet, so it cannot be shown for another period.')
    if period not in ds.period_ids():
        raise SpecProblem(f'The datasheet has no period {period!r}.')
    res = dsp.export_spec(ds, period=period, uid=head.get('uid') or None)
    if not res.ok:
        raise SpecProblem('The datasheet cannot be exported for that period: ' + '; '.join(str(p) for p in db.errors(res.problems)[:3]))
    new = res.spec
    old = {s['id']: s['dsb'].get('assignment') for s in spec['steps'] if 'dsb' in s}
    for s in new['steps']:
        if old.get(s['id']):
            s['dsb']['assignment'] = old[s['id']]
    if head.get('plan'):
        new['dsb']['plan'] = head['plan']
    new['dsb']['version'], new['dsb']['uid'] = head.get('version'), head.get('uid')
    return new


def _num(x):
    return None if x in (None, '') else float(x)


def rms_factor(run):
    """Datasheet amplitude -> V rms factor for a generator point (matcher's own table); 1 when the unit is not a level."""
    s = run['settings']
    f = dm._rms_factor(s.get('waveform') or 'SIN', s.get('amp_unit') or 'Vrms')
    return float(f) if f is not None else 1.0


def decorate(p):
    """Add the runtime description of a point (p['run']) and re-shape the hand-set scope / generator steps so the engine can list and run them."""
    d = p['dsb']
    kind, st = d['kind'], d['stimulus']
    run = dict(kind=kind, direction=d['direction'], nominal=_num(st.get('nominal')), frequency=_num(st.get('frequency')),
               amplitude=_num(st.get('amplitude')), settings=dict(st.get('settings') or {}), unit=d.get('unit', ''), op='dmm')
    p['run'] = run
    if d['direction'] == 'source':                                      # the unit under test OUTPUTS: a standard measures
        run['op'] = 'std_level' if kind in LEVEL_KINDS else 'std_freq' if kind in FREQ_KINDS else 'std_flat' if kind == 'GEN_FLAT' else 'std_other'
        run['reference_hz'] = _num(run['settings'].get('ref_frequency')) or REF_HZ['std_flat']
        p.pop('applied', None)
        p['kind'], p['group'] = 'NONE', 'NONE'
        p['no_uncertainty'] = True
        nominal = hh._fmt(run['nominal'], run['unit']) if run['nominal'] is not None else ''
        p['dsb_desc'] = f'{p["section"]}, {p["range"]} range: {nominal}' + (f' @ {hh._fmt(run["frequency"], "Hz")}' if run['frequency'] else '')
        p['dsb_device'] = 'Measuring standard: ' + (_assigned(p) or 'your own standard') + f'\nUnit under test function: {p["switch"]}'
        return p
    if kind in SCOPE_KINDS:
        run['op'] = SCOPE_OPS[kind]
        run['reference_hz'] = _num(run['settings'].get('ref_frequency')) or REF_HZ['scope_bw']
        p['kind'], p['group'] = kind, GROUP[run['op']]
        p['no_uncertainty'] = True
        nom, f, a = run['nominal'], run['frequency'], run['amplitude']
        if run['op'] == 'scope_dc':
            p['applied'] = dict(value=nom, frequency=None)
            p['dsb_out'] = f'{hh._fmt(nom, "V")} DC on the SCOPE output (1 MΩ)'
            p['dsb_desc'] = f'{p["section"]}, {p["range"]} range: {hh._fmt(nom, "V")} DC'
        elif run['op'] == 'scope_marker':
            p['applied'] = dict(value=nom, frequency=None)
            p['dsb_out'] = f'Time marker, period {hh._fmt(nom, "s")}'
            p['dsb_desc'] = f'{p["section"]}, {p["range"]}: {hh._fmt(nom, "s")} marker'
        else:
            p['applied'] = dict(value=a, frequency=f)
            p['dsb_out'] = f'{hh._fmt(a, "V")} p-p leveled sine at {hh._fmt(f, "Hz")}' if a is not None and f else 'leveled sine'
            p['dsb_desc'] = f'{p["section"]}: {hh._fmt(a, "V")} p-p at {hh._fmt(f, "Hz")}' if a is not None and f else p['section']
        p['dsb_device'] = f'Oscilloscope: {p["switch"]}' + (f'\\nRange: {p["range"]}' if p['range'] else '')
        return p
    # DMM-type points: the stock engine drives the routed calibrator
    if kind in ('FREQ', 'PERIOD'):
        p['no_uncertainty'] = True                      # engine kind ACV with the frequency as the nominal: its ACV uncertainty would be for the wrong quantity
        a = p.get('applied') or {}
        p['dsb_desc'] = f'{p["section"]}, {p["range"]} range ({hh._fmt(a.get("value"), "V")} applied)' if a.get('value') is not None else p['section']
    return p


def runtime_points(spec, model=None):
    """The engine's points for the datasheet's model, one whole function (table) after the other in the datasheet's order.  The engine sorts by
    (table_order, step); without a table_order it would interleave the functions (step 1 of every table, then step 2 ...), so the order is set here."""
    model = model or spec['dsb']['model']
    tables = list(dict.fromkeys(s['table'] for s in spec['steps'] if model in s.get('models', ())))
    ordered = dict(spec, options=dict(spec.get('options') or {}, table_order={t: n for n, t in enumerate(tables)}))
    pts = hh.points_for(ordered, model)
    for p in pts:
        if 'dsb' in p:
            decorate(p)
    return pts


def _assigned(p) -> str:
    a = (p.get('dsb') or {}).get('assignment') or {}
    if a.get('mode') in ('manual', 'none') or a.get('status') in ('uncovered', 'manual'):
        return ''
    s = str(a.get('standard') or '')
    return '' if s.upper() in ('', 'MANUAL') else s


# ============================================================================================================== routing
@dataclass
class Route:
    auto: bool = False              # a driver does the work (source: sets the output; measuring standard: reads it)
    standard: str = ''              # model of the standard that is used ('' = the operator's own / by hand)
    assigned: str = ''              # model the datasheet assigned ('' = none)
    status: str = 'manual'          # automation status of the standard used: ok | unverified | manual
    reason: str = ''                # why it differs from the assignment / why it is manual
    note: str = ''                  # the driver table's note (what is unverified)

    @property
    def substituted(self):
        return bool(self.auto and self.assigned and self.standard != self.assigned)

    @property
    def label(self):
        return self.standard if self.auto else 'manual'

    def to_dict(self):
        return dict(auto=self.auto, standard=self.standard, assigned=self.assigned, status=self.status, reason=self.reason)


def limit_problem(p, model):
    """Why this standard's scope output cannot make the point (None when it can)."""
    run = p['run']
    if run['op'] in ('scope_bw', 'scope_trigger') and model in SOURCE_MODELS:
        lim, a, f = tds.SOURCE_LIMITS, run['amplitude'], run['frequency']
        ref = run.get('reference_hz') if run['op'] == 'scope_bw' else None
        if a is None or f is None:
            return 'the point has no amplitude or frequency'
        if a > lim['vpp_max'] or f < lim['f_min'] or (ref is not None and ref < lim['f_min']):
            return (f'{hh._fmt(a, "V")} p-p at {hh._fmt(f, "Hz")}' + (f' (reference {hh._fmt(ref, "Hz")})' if ref else '') +
                    f' is outside the leveled-sine range used here (up to {lim["vpp_max"]:g} V p-p, from {hh._fmt(lim["f_min"], "Hz")})')
    return None


def route_for(p, connected, prefer=()) -> Route:
    """Which standard does point p?  `connected` = models whose driver is open; `prefer` = the engine's own calibrator choice (tried after the assigned one)."""
    run = p['run']
    kind, direction = run['kind'], run['direction']
    want = 'measure' if direction == 'source' else 'source'
    assigned = _assigned(p)
    why = []
    if not assigned:
        a = (p.get('dsb') or {}).get('assignment') or {}
        why.append(a.get('message') or 'the datasheet assigns no standard to this point (the operator\'s own standard)')
    order = ([assigned] if assigned else []) + [m for m in list(prefer) + list(dm.lab_default(kind)) + sorted(connected) if m != assigned]
    seen = []
    for model in order:
        if model in seen:
            continue
        seen.append(model)
        info = dm.DRIVER_TABLE.get(model)
        if info is None or info.role != want:
            continue
        if model not in connected:
            if model == assigned:
                why.append(f'assigned {model} is not connected')
            continue
        cap = dm.automation_status(model, kind, direction)
        if not cap.can_automate:
            why.append(f'{model}: ' + dm.automation_text(cap, kind))
            continue
        problem = limit_problem(p, model)
        if problem:
            why.append(f'{model}: {problem}')
            continue
        route = Route(True, model, assigned, cap.status, '', cap.note)
        if model != assigned:
            route.reason = '; '.join(why) + (f'; using {model}' if why else f'using {model}')
        return route
    return Route(False, '', assigned, 'manual', '; '.join(why) or 'no standard is connected', '')


# ============================================================================================================== bench I/O
class DsbIO(hh.IO, reset_startup.IOResetMixin):
    """The standards of one run: calibrators that source (5560A / 5522A), a 5790B and counters that measure.  Every driver is an open
    drivers.Instrument; settings are written, read back and compared by the drivers; nothing is retried."""

    def __init__(self, addrs, counter_ref='EXT', transports=None, mods=None, scope=False):
        """addrs: {model: {'address': VISA text, 'baud': int}}; transports: {model: transport} (simulated benches)."""
        self.log = drivers.CommandLog()
        self.drivers, self.counter_ref = {}, counter_ref
        self.scope = scope
        self.cal = None
        self._hot = set()
        self.standby_ok = True
        t = transports or {}
        try:
            for model in list(dict.fromkeys(list(t) + list(addrs))):
                self.drivers[model] = self._open(model, addrs.get(model) or {}, t.get(model))
            self.cal = next((self.drivers[m] for m in SOURCE_MODELS if m in self.drivers), None)
            for m in SOURCE_MODELS:
                if m in self.drivers and scope:
                    self.drivers[m].RESET_SCOPE_OFF = True           # the reset leaves the calibrator in standby with SCOPE OFF (the tests select their own mode)
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close()
            raise
        self.ident = ', '.join(f'{m}: {d.idn}' for m, d in self.drivers.items())

    def _open(self, model, addr, transport):
        def tr(timeout, **kw):
            return transport if transport is not None else drivers.open_visa(fg.to_visa(addr['address']), timeout=timeout, **kw)
        if model in SOURCE_MODELS:
            cls = drivers.Fluke5560A if model == '5560A' else (drivers.Fluke5522AScope if self.scope else drivers.Fluke5522A)
            d = cls(tr(20, baud=int(addr.get('baud', 9600))), self.log, label=model)
            self.drivers[model] = d                                  # visible to close() if the open fails
            d.open(verify_model=True)
            d.clear_status()
            return d
        if model == '5790B':
            serial = fg.IO._serial({'std': addr.get('address', ''), 'std_baud': addr.get('baud')}, 'std') if transport is None else {}
            d = drivers.Fluke5790B(tr(30, **serial), self.log, label=model)
            self.drivers[model] = d
            return d.connect()
        if model in COUNTERS:
            d = drivers.Keysight5313x(tr(30), self.log, label=model)
            self.drivers[model] = d
            return d.connect()
        raise drivers.InstrumentError(f'{model}: no driver is known for this standard')

    # ---- bookkeeping ------------------------------------------------------------------------------------------
    def models(self):
        return set(self.drivers)

    def sources(self):
        return [self.drivers[m] for m in SOURCE_MODELS if m in self.drivers]

    def measuring(self):
        return [d for m, d in self.drivers.items() if m not in SOURCE_MODELS]

    def reset_roles(self):
        return self.sources() + self.measuring(), []              # sources first; the unit under test has no remote interface here (typed readings)

    def pm_drivers(self):
        return tuple(self.drivers.values())

    def standby(self):
        """Every source to STANDBY (quiet), then the ones that were operated are read back; an unconfirmed standby is logged and flagged, never raised
        (the engine calls this between points)."""
        for d in self.sources():
            d.standby_quiet()
        self.standby_ok = True
        for d in self.sources():
            if d.label in self._hot:
                try:
                    if d.ask('oper.query').strip() != '0':
                        self.standby_ok = False
                        self.log.add('!!', f'{d.label}: STANDBY not confirmed', 'SAFETY')
                except Exception:
                    self.standby_ok = False
                self._hot.discard(d.label)

    def close(self):
        try:
            self.standby()
        except Exception:
            pass
        for d in self.drivers.values():
            try:
                d.cleanup()
            except Exception:
                pass
            try:
                d.close()
            except Exception:
                pass
        self.save_log()

    # ---- the source side ----------------------------------------------------------------------------------------
    def _runner(self, model):
        """tds2000c_verification.Runner's calibrator methods on this bench (imported, not copied): they only need .io.cal and .io.is_5560."""
        r = tds.Runner.__new__(tds.Runner)
        r.app, r.io, r.cfg = None, SimpleNamespace(cal=self.drivers[model], is_5560=model == '5560A'), None
        r._wired, r._scope_ctx, r._sine, r._start = None, None, None, {}
        return r

    def _settle(self, p):
        return p.get('settle', self.pm_param('handheld.settle.default', 3.0))

    @hh.procmods_engine.point_commands()
    def apply(self, p, cancel=None):
        """Program and enable the output of point p on its routed standard (p['_route']), then wait for it to settle."""
        run, route = p['run'], p['_route']
        model = route.standard
        self.cal = self.drivers[model]
        if run['op'] == 'dmm':
            super().apply(p, cancel)
            self._hot.add(self.cal.label)
            return
        self.standby()
        cal = self.cal
        r = self._runner(model)
        context = hh.describe(p)
        if run['op'] == 'scope_dc':
            r.dc_source()                                         # SCOPE DCV / VOLT + OUT_IMP, confirmed
            cal.set_dc_volts(run['nominal'])                      # set, read back and compare (the 5522A scope driver sends the explicit 0 Hz and checks SDCV)
            cal.check_error(context)
            cal.operate()
        elif run['op'] == 'scope_marker':
            cal.standby_quiet()
            cal.select_scope_marker()
            cal.set_marker_period(run['nominal'])
            cal.operate()
        else:                                                      # scope_bw / scope_trigger: leveled sine at the test frequency
            r.select_levsine()
            r.set_sine(run['amplitude'], run['frequency'], settle=0.0)
        self._hot.add(cal.label)
        self.on_at = time.monotonic()
        self._wait(self._settle(p), cancel)

    def apply_reference(self, p, cancel=None):
        """Bandwidth: the leveled sine at the reference frequency (the operator notes the level before the test frequency is applied)."""
        run, route = p['run'], p['_route']
        self.cal = self.drivers[route.standard]
        self.standby()
        r = self._runner(route.standard)
        r.select_levsine()
        r.set_sine(run['amplitude'], run['reference_hz'], settle=0.0)
        self._hot.add(self.cal.label)
        self._wait(self._settle(p), cancel)

    # ---- the measuring side -------------------------------------------------------------------------------------
    def read_level(self, p, freq, route):
        """V rms of the unit under test's output at `freq` on the 5790B (fgen_verification's _std_volts does the reading and the frequency check)."""
        std = self.drivers[route.standard]
        run = p['run']
        inp = (run['settings'].get('std_input') or ('WBND' if freq > WIDEBAND_ABOVE_HZ else 'INPUT1')).upper()
        if inp == 'WBND':
            std.require_wideband(freq)
        std.select_input(inp)
        std.set_external_trigger(True)
        level = run['nominal'] if run['kind'] in ('GEN_AMPL', 'ACV') else (run['amplitude'] or 1.0)
        expected_rms = abs(level) * rms_factor(run)
        std.set_range_for(expected_rms)
        return fg.IO._std_volts(SimpleNamespace(std=std), freq), dict(input=inp, range_expected_v=expected_rms)

    def read_frequency(self, p, route):
        """Hz on a 53131A / 53132A: channel 1, 50 ohm, AC, 1 s gate, the expected frequency; the timebase selected and checked (same calls as fgen_verification)."""
        c = self.drivers[route.standard]
        run = p['run']
        expected = (1.0 / run['nominal']) if run['kind'] == 'PERIOD' else run['nominal']
        ref_hz = c.set_reference(self.counter_ref)
        c.configure_frequency(channel=1, gate_s=COUNTER_GATE_S, impedance=50, coupling='AC', expected_hz=expected)
        src, _auto = c.reference()
        if src != self.counter_ref:
            raise drivers.InstrumentError(f'Counter timebase is {src}, expected {self.counter_ref}.')
        f = c.frequency()
        raw = dict(counter=(c.idn.split(',')[1].strip() if ',' in (c.idn or '') else c.idn), gate_s=COUNTER_GATE_S,
                   reference=(f'EXT {ref_hz / 1e6:g} MHz (checked)' if self.counter_ref == 'EXT' and ref_hz else 'INT'))
        return f, raw

    def measure(self, p, route, refs=None):
        """(reading in the datasheet's unit, raw dict) for a unit-under-test OUTPUT point read by `route`'s standard.  `refs` = the flatness references taken so far."""
        run = p['run']
        try:
            if run['op'] == 'std_level':
                v, raw = self.read_level(p, run['frequency'] or 1000.0, route)
                return v / rms_factor(run), dict(raw, vrms=v)
            if run['op'] == 'std_freq':
                f, raw = self.read_frequency(p, route)
                return ((1.0 / f) if run['kind'] == 'PERIOD' else f), dict(raw, hz=f)
            if run['op'] == 'std_flat':
                v, raw = self.read_level(p, run['frequency'], route)
                ref = (refs or {}).get(self.flat_key(p))
                if ref is None:
                    raise drivers.InstrumentError('The flatness reference has not been measured.')
                return 20.0 * math.log10(v / ref), dict(raw, v_f=v, v_ref=ref, reference_hz=run['reference_hz'])
            raise drivers.InstrumentError(f'No automatic reading for {run["kind"]}.')
        finally:
            self.release()

    @staticmethod
    def flat_key(p):
        return f'{p["run"]["kind"]}|{p["table"]}|{p["run"]["amplitude"]}|{p["range"]}'

    def read_reference(self, p, route):
        """Flatness: the level at the reference frequency (the unit under test has been set to it by the operator)."""
        try:
            v, raw = self.read_level(dict(p, run=dict(p['run'])), p['run']['reference_hz'], route)
            return v, raw
        finally:
            self.release()

    def release(self):
        """A measuring standard has no output; the 5790B goes back to continuous triggering (its cleanup)."""
        for d in self.measuring():
            try:
                d.cleanup()
            except Exception:
                pass


# ============================================================================================================== the application
class DsbApp(hh.App, reset_startup.AppResetMixin):
    """The handheld engine's window for a user-built datasheet."""

    def __init__(self, root, spec, demo=False, io_factory=None, period=None):
        spec = with_plan(spec)
        self.dsb = spec['dsb']
        self.period = period or self.dsb.get('period')
        if self.period != self.dsb.get('period'):
            spec = spec_for_period(spec, self.period)
        self._cur = None
        self.std_addr = {}
        self.dsb_ref = {}
        self.counter_ref = tk.StringVar(value='EXT')
        self.period_var = tk.StringVar(value=self.period)
        if self.dsb.get('uid'):
            self.pm_proc_key = 'ds:' + str(self.dsb['uid'])      # verified.py: this datasheet's own verified / locked state, not its model's
        super().__init__(root, self.dsb['model'], demo=demo, spec=spec, io_factory=io_factory)
        self.counter_ref.set(self.settings.get('counter_ref', 'EXT'))

    # ---- hooks of the handheld engine -----------------------------------------------------------------------------
    def build_points(self):
        return runtime_points(self.spec, self.model)

    def settings_name(self):
        return 'dsb_' + ''.join(c if c.isalnum() else '_' for c in (self.dsb.get('uid') or self.model))

    def _checkpoint_path(self):
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        uid = ''.join(c for c in str(self.dsb.get('uid') or self.model) if c.isalnum())[:12]
        return appdata.progress_path(f'DSB_{uid}_{asset}_checkpoint.json')

    def save_fields(self):
        d = super().save_fields()
        d['dsb'] = dict(uid=self.dsb.get('uid'), version=self.dsb.get('version'), period=self.period)
        return d

    def checkpoint_problem(self, data):
        c = data.get('dsb')
        if not isinstance(c, dict):
            return 'This progress file was not saved from a user-built datasheet.'
        if c.get('uid') != self.dsb.get('uid'):
            return 'This progress file belongs to a different datasheet.'
        if c.get('version') != self.dsb.get('version'):
            return (f'This progress file was recorded against version {c.get("version")} of the datasheet; the datasheet is now version '
                    f'{self.dsb.get("version")}. Readings judged against other limits are not mixed: start a new run.')
        if c.get('period') != self.period:
            return f'This progress file was recorded for the period {c.get("period")!r}; this run is set to {self.period!r}. Choose the same period first.'
        return None

    def reading_labels(self, p):
        run = p.get('run') or {}
        if run.get('op', 'dmm') == 'dmm':
            return {}
        if run['direction'] == 'source':
            return dict(device='MEASURING STANDARD')
        return dict(device='OSCILLOSCOPE', source='CALIBRATOR SCOPE OUTPUT')

    # ---- window -------------------------------------------------------------------------------------------------------
    def _build_ui(self):
        super()._build_ui()
        d = self.shell.drawer_body
        row = 20
        ttk.Separator(d).grid(row=row, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        ttk.Label(d, text='Standards used by this datasheet', style='Bold.TLabel').grid(row=row + 1, column=0, columnspan=2, sticky='w')
        row += 2
        for model in self.standards_needed():
            info = dm.DRIVER_TABLE.get(model)
            self.std_addr[model] = tk.StringVar(value=self.settings.get('addr_' + model, ''))
            ttk.Label(d, text=f'{model}' + (f' ({info.role})' if info else '')).grid(row=row, column=0, sticky='w', pady=4)
            ttk.Entry(d, textvariable=self.std_addr[model], width=34).grid(row=row, column=1, sticky='ew', padx=(10, 0), pady=4)
            row += 1
        if any(m in COUNTERS for m in self.std_addr):
            ttk.Label(d, text='Counter timebase').grid(row=row, column=0, sticky='w', pady=4)
            ttk.Combobox(d, textvariable=self.counter_ref, values=['EXT', 'INT'], state='readonly', width=9).grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
            row += 1
        periods = [p['id'] for p in self.dsb.get('periods', [])]
        if len(periods) > 1:
            ttk.Label(d, text='Specification period').grid(row=row, column=0, sticky='w', pady=4)
            box = ttk.Combobox(d, textvariable=self.period_var, values=periods, state='readonly', width=9)
            box.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
            box.bind('<<ComboboxSelected>>', lambda _e: self.on_period())
            row += 1
        ttk.Label(d, text='A blank address means that standard is operated by hand: the program tells you what to set or asks for its reading. '
                          'The calibrator box above is the fallback for points whose assigned standard is not connected.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=row, column=0, columnspan=2, sticky='w', pady=(6, 0))
        manual = sum(1 for p in self.points if not _assigned(p))
        self.shell.notice(f'User-built datasheet "{self.dsb.get("title")}", version {self.dsb.get("version")}. Limits are calculated from the specification the '
                          f'author entered; points a connected standard cannot make are done by hand and marked [manual] in the report.'
                          + (f' {manual} point(s) have no assigned standard.' if manual else ''), 'info')

    def on_period(self):
        new = self.period_var.get()
        if new == self.period:
            return
        if self.found or self.left:
            self.period_var.set(self.period)
            messagebox.showinfo('Specification period', 'Readings are already recorded, so the period cannot be changed now. Start a new run to use another period.')
            return
        try:
            self.spec = spec_for_period(self.spec, new)
        except SpecProblem as exc:
            self.period_var.set(self.period)
            messagebox.showerror('Specification period', str(exc))
            return
        self.period = new
        self.points[:] = runtime_points(self.spec, self.model)
        self.by_id = {p['id']: p for p in self.points}
        self.refresh()
        self.status.set(f'Limits now follow the {new} specification.')

    # ---- standards and connection -------------------------------------------------------------------------------------
    def engine_model(self):
        """The calibrator chosen in the engine's own box ('5560A' / '5522A'), None for Manual."""
        text = self.cal_mode.get()
        return None if text.startswith('Manual') else ('5522A' if '5522A' in text else '5560A')

    def standards_needed(self):
        out = []
        for p in self.points:
            m = _assigned(p)
            if m and m not in out:
                out.append(m)
        for m in SOURCE_MODELS:
            if m not in out and any(p['run']['direction'] == 'measure' for p in self.points):
                out.append(m)
        return out

    def has_scope(self):
        return any(p['run']['kind'] in SCOPE_KINDS for p in self.points)

    def addresses(self):
        out = {}
        for model, var in self.std_addr.items():
            a = var.get().strip()
            if a:
                out[model] = dict(address=a, baud=9600)
        eng = self.engine_model()
        if eng:
            out[eng] = dict(address=self._address(), baud=int(self.cal_baud.get()))        # the engine's calibrator box wins for its model
        return out

    def wants_connection(self):
        return bool(self.engine_model()) or any(v.get().strip() for v in self.std_addr.values())

    def connect(self):
        self.disconnect()
        if self.io_factory:
            self.io = self.io_factory()
        else:
            self.io = DsbIO(self.addresses(), counter_ref=self.counter_ref.get(), mods=self.pm_state, scope=self.has_scope())
        self.io.auto_ramp = self._auto_ramp()
        self._set_conn(True)
        self._save_settings()

    def test_connection(self):
        if self.demo:
            messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.')
            return
        if not self.wants_connection():
            messagebox.showinfo('Manual', 'No standard has an address: every point is done by hand. The program will tell you what to set and ask for the readings.')
            return
        self.status.set('Connecting ...')
        self.root.update_idletasks()
        try:
            self.connect()
        except Exception as exc:
            self.disconnect()
            self._set_conn(False)
            self.status.set('Connection error: ' + str(exc))
            messagebox.showerror('Connection error', str(exc))
            return
        self.status.set('Connected: ' + self.io.ident + '. Outputs are NOT enabled.')
        messagebox.showinfo('Connected', f'{self.io.ident}\nOutputs are not enabled.')

    def _save_settings(self):
        super()._save_settings()
        for model, var in self.std_addr.items():
            self.settings.set('addr_' + model, var.get())
        self.settings.set('counter_ref', self.counter_ref.get())
        self.settings.save()

    # ---- routing ---------------------------------------------------------------------------------------------------------
    def route(self, p):
        if self.demo:
            return Route(False, '', _assigned(p), 'manual', 'demo mode')
        connected = self.io.models() if self.io is not None else set()
        eng = self.engine_model()
        return route_for(p, connected, prefer=[eng] if eng else [])

    def pm_plan_point(self, p):
        """The commands DsbIO.apply sends for a SOURCE point of the datasheet (the calibrator sets the stimulus the meter is read against), then
        the STANDBY that follows the reading: a dry run on the simulated bench (procmods_plan).  Points the unit under test sources (the standard
        reads them: 5790B, counters) are not shown: their measuring side has no simulated bench here."""
        import procmods_plan
        from drivers.simulated import make_bench, SimFlukeTransport
        run = p.get('run')
        if not run:
            return super().pm_plan_point(p)
        if run['direction'] != 'source' or run['op'].startswith('std_'):
            return procmods_plan.Plan(error='The commands of a point the unit under test sources (read by the 5790B or a counter) cannot be shown before the run.')
        eng = self.engine_model()
        route = route_for(p, set(self.io.models()) if self.io is not None else set(SOURCE_MODELS), prefer=[eng] if eng else [])
        if not route.auto or route.standard not in SOURCE_MODELS:
            return procmods_plan.Plan(note=(route.reason or 'This point is set by hand: no instrument command is sent.'))
        q = dict(p)
        q['_route'] = route
        scope = self.has_scope()

        def build(mods):
            bench, _a, _b = make_bench()
            mods.alias(q, self.pm_point_key(p))
            return DsbIO({}, transports={route.standard: SimFlukeTransport(bench, route.standard)}, scope=scope, mods=mods)

        def go(io):
            io.apply(q)
            io.standby()
        return procmods_plan.run_plan(self.pm_state, build, go)

    @property
    def manual_cal(self):
        """For the point in progress: True when its source is set by hand (the engine's prompts then tell the operator to set it)."""
        p = self._cur
        if p is not None and p.get('run') and p['run']['direction'] == 'measure':
            r = p.get('_route')
            return not (r is not None and r.auto)
        if p is not None and p.get('run'):
            return self.io is None
        return self.cal_mode.get().startswith('Manual')

    def calibrator_model(self):
        std = getattr(self, '_row_std', None)
        return std if std in SOURCE_MODELS else None

    def _record_for(self, p):
        return self.left.get(p['id']) or self.found.get(p['id']) or {}

    # ---- running -------------------------------------------------------------------------------------------------------------
    def execute(self, points):
        if self.busy or not points:
            return
        if not self.asset.get().strip():
            messagebox.showwarning('Instrument ID', 'Enter an instrument ID.')
            return
        points = self.pm_begin_run(points, self.asset.get().strip())
        if not points:
            self.status.set('Every selected point is skipped by a procedure modification.')
            return
        if not self.confirm_found_overwrite(points):
            return
        if not self.demo and self.wants_connection() and self.io is None:
            self.test_connection()
            if self.io is None:
                return
        self.dsb_ref = {}                                           # references (bandwidth, flatness) are taken again at the start of every run
        if self.io is not None:
            self.io.auto_ramp = self._auto_ramp()                   # the datasheet's option (default: straight to the test value, no ramp)
        self.stop = False
        self.busy = True
        self._last_switch = None
        self.reset_then(lambda: self._next(points, 0, None))      # every run (first, re-run, resume): reset every connected standard first

    def reset_extra_uuts(self):
        return []

    def _next(self, points, i, previous):
        self._cur = points[i] if (i < len(points) and not self.stop) else None
        if self._cur is not None:
            self._cur['_route'] = self.route(self._cur)
            if not self.demo:
                self._note_route(self._cur)
        super()._next(points, i, previous)

    def _note_route(self, p):
        r = p['_route']
        if self.io is not None and r.reason and self.io.log is not None:
            self.io.log.add('--', f'{p["id"]}: ' + (f'using {r.standard}: ' if r.auto else 'done by hand: ') + r.reason, 'ROUTE')

    def _prompt_function(self, p):
        if p.get('run') and p['run']['op'] != 'dmm':
            self._last_switch = p['switch']           # the wiring / set-up prompt of scope and generator points already says what to change
            return True
        return super()._prompt_function(p)

    def _high_voltage(self, p):
        run = p.get('run') or {}
        if run.get('op') == 'scope_dc' and run.get('nominal') is not None:
            return abs(run['nominal']) >= self.spec.get('options', {}).get('hv_threshold_v', 500)
        return super()._high_voltage(p)

    def uut_steps(self, p):
        """What the operator sets on the unit under test for a generator point."""
        run = p['run']
        text = (p.get('setup') or '').split(' Read the measuring standard')[0]
        return text or f'Set the unit under test to output {hh._fmt(run["nominal"], run["unit"])}.'

    def _prompt_setup(self, p):
        run = p.get('run')
        if not run or run['direction'] != 'source':
            return super()._prompt_setup(p)
        r = p.get('_route') or Route()
        facts = [('Next point', f'{p["n"]} of {len(self.points)}'), ('Test', hh.describe(p)), ('Unit under test', p['switch'])]
        steps = []
        if run['op'] != 'std_flat' or not r.auto:
            steps.append(('Unit under test', self.uut_steps(p)))
        if r.auto:
            std = r.standard
            if std == '5790B':
                inp = (run['settings'].get('std_input') or ('WBND' if (run['frequency'] or 0) > WIDEBAND_ABOVE_HZ else 'INPUT1')).upper()
                steps.append(('Connect', f'Unit under test output to the 5790B {STD_INPUT_TEXT.get(inp, inp)} input. The 5790B input impedance is not the generator\'s '
                                         f'load: set the unit under test\'s load / termination as the datasheet says.'))
            else:
                steps.append(('Connect', f'Unit under test output to the {std} channel 1 input (50 Ω, AC coupled). The counter timebase is {self.counter_ref.get()}.'))
            steps.append(('Reading', f'The program reads the {std} itself' + (' (the reference frequency first, then the test frequency)' if run['op'] == 'std_flat' else '') + '.'))
            if r.substituted:
                steps.append(('Standard', f'The datasheet assigns {r.assigned}; {r.standard} is used instead ({r.reason}).'))
        else:
            steps.append(('Reading', 'Read your measuring standard' + (f' (the datasheet assigns the {_assigned(p)})' if _assigned(p) else '') + ' and type its reading' +
                          (' as the level relative to the reference frequency, in dB.' if run['op'] == 'std_flat' else '.') +
                          (f' Done by hand: {r.reason}.' if r.reason else '')))
        steps.append(('Afterwards', 'Switch the unit under test output OFF when the reading has been taken.'))
        return ui.confirm_steps(self.root, 'Check the setup', f'Set up for {p["section"]}', steps, facts=facts, ok='Done - continue')

    def _out_note(self, p, on):
        run = p.get('run')
        if not run or run['op'] == 'dmm' or not p.get('applied'):
            base = super()._out_note(p, on)
            r = p.get('_route')
            who = _assigned(p) or (r.assigned if r else '')
            return base + (f' (assigned standard: {who})' if base and self.manual_cal and who else '')
        if self.manual_cal:
            who = _assigned(p) or 'the calibrator'
            return f'Set this on {who} (scope output) and press OPERATE, then read the oscilloscope.'
        return 'Output is ON - allow the signal to settle, then read the oscilloscope.' if on else 'Output is in STANDBY.'

    # ---- the readings that need more than the engine's dialog ----------------------------------------------------------------
    def _ask(self, points, i, p, key):
        run = p.get('run')
        if run and not self.demo:
            r = p.get('_route')
            if run['op'] == 'scope_bw' and r is not None and r.auto and 'ref' not in self._stage['done'] and self.scope_ref_key(p) not in self.dsb_ref:
                self._scope_reference(points, i, p, key)
                return
            if run['direction'] == 'source' and r is not None and r.auto and not self._stage.get('typed') and run['op'] != 'std_other':
                self._ask_standard(points, i, p, key)
                return
        super()._ask(points, i, p, key)

    def _work(self, fn, then):
        """Run fn() on a worker thread (never a Tk call there); then(out, exc) runs on the main thread."""
        state = {'done': False, 'exc': None, 'out': None}

        def work():
            try:
                state['out'] = fn()
            except BaseException as exc:
                state['exc'] = exc
                try:
                    if self.io is not None:
                        self.io.standby()
                except Exception:
                    pass
            state['done'] = True

        def wait():
            if not state['done']:
                self.root.after(40, wait)
                return
            then(state['out'], state['exc'])
        threading.Thread(target=work, daemon=True).start()
        wait()

    @staticmethod
    def scope_ref_key(p):
        return f'scope_ref|{p["table"]}|{p["run"]["amplitude"]}|{p["run"]["reference_hz"]}'

    def _scope_reference(self, points, i, p, key):
        """Bandwidth: the leveled sine at the reference frequency first; the operator notes the level, then the test frequency is applied."""
        run = p['run']
        self.status.set(f'Point {p["n"]}/{len(self.points)}: reference level at {hh._fmt(run["reference_hz"], "Hz")} ...')

        def done(_out, exc):
            if isinstance(exc, hh.Cancelled):
                self._ask_abort()
                return
            if exc is not None:
                self._error(exc)
                return
            ok = ui.confirm_steps(self.root, 'Reference level', 'Bandwidth reference',
                                  [('Output', f'The calibrator outputs {hh._fmt(run["amplitude"], "V")} p-p at the reference frequency {hh._fmt(run["reference_hz"], "Hz")}.'),
                                   ('Scope', 'Set the vertical scale so the trace is easy to read and note the amplitude (or set the measurement / cursors).'),
                                   ('Next', f'The program then applies {hh._fmt(run["frequency"], "Hz")}; type the response relative to the reference, in dB.')],
                                  facts=[('Point', f'{p["n"]} of {len(self.points)}'), ('Test', hh.describe(p))], ok='Reference noted - continue')
            self._safe_standby()
            if not ok:
                self.busy = False
                self.status.set('Paused at the bandwidth reference.')
                return
            self._stage['done'].add('ref')
            self.dsb_ref[self.scope_ref_key(p)] = True                # one reference per run for the same level and reference frequency
            self._reapply(points, i, p, key)
        self._work(lambda: self.io.apply_reference(p, cancel=lambda: self.stop), done)

    def _ask_standard(self, points, i, p, key):
        """The routed measuring standard reads the unit under test's output; on a problem the operator chooses: type the reading, skip, stop."""
        run, route = p['run'], p['_route']
        self.status.set(f'Point {p["n"]}/{len(self.points)}: reading the {route.standard} ...')

        def finish(out, exc):
            if exc is None:
                reading, raw = out
                self._store_measured(p, reading, raw, route)
                self.root.after(30, lambda: self._next(points, i + 1, key))
                return
            if isinstance(exc, hh.Cancelled):
                self._ask_abort()
                return
            if not isinstance(exc, (drivers.InstrumentError, drivers.TransportError)) and not isinstance(exc, OSError):
                self._error(exc)
                return
            choice = messagebox.askyesnocancel('Measuring standard', f'{route.standard} could not give a reading for this point:\n\n{exc}\n\n'
                                               'Yes = type the standard\'s reading by hand.   No = skip this point.   Cancel = stop the run.')
            if choice is None:
                self.busy = False
                self.stop = True
                self.status.set('Stopped. Progress is saved.')
                self.save()
            elif choice is False:
                self.root.after(30, lambda: self._next(points, i + 1, key))
            else:
                self._stage['typed'] = True
                p['_route'] = Route(False, '', route.assigned, 'manual', f'{route.standard} gave no reading: {exc}')
                self._ask(points, i, p, key)

        def measure():
            if run['op'] == 'std_flat':
                key_ = DsbIO.flat_key(p)
                if key_ not in self.dsb_ref:
                    self._confirm_on_ui(f'Reference frequency', [('Unit under test', f'Set the unit under test to the REFERENCE frequency {hh._fmt(run["reference_hz"], "Hz")} '
                                                                  f'(same level {hh._fmt(run["amplitude"], "V")}).')], p)
                    v, _raw = self.io.read_reference(p, route)
                    self.dsb_ref[key_] = v
                self._confirm_on_ui('Test frequency', [('Unit under test', f'Set the unit under test to {hh._fmt(run["frequency"], "Hz")} (same level).')], p)
            return self.io.measure(p, route, refs=self.dsb_ref)
        self._work(measure, finish)

    def _confirm_on_ui(self, heading, steps, p):
        """A dialog asked from a worker thread: the main thread shows it, the worker waits for the answer (Stopped if declined)."""
        box, ev = [], threading.Event()

        def ask():
            try:
                box.append(ui.confirm_steps(self.root, 'Set the unit under test', heading, steps,
                                            facts=[('Point', f'{p["n"]} of {len(self.points)}'), ('Test', hh.describe(p))], ok='Set - read it'))
            finally:
                ev.set()
        self.root.after(0, ask)
        ev.wait()
        if not box or not box[0]:
            raise hh.Cancelled()

    def _store_measured(self, p, reading, raw, route):
        factor = Decimal(str(p['factor']))
        value = Decimal(repr(float(reading))) / factor
        places = 0
        for k in ('low', 'high'):
            try:
                places = max(places, -Decimal(p[k]).as_tuple().exponent)
            except Exception:
                pass
        text = f'{value:.{min(places + 2, 9)}f}'
        if Decimal(text) == 0:
            text = text.lstrip('-')                                 # no '-0.000'
        text = hh.pad_reading(p, text)
        result, base = hh.judge_numeric(p, text)
        self._store(p, entered=text, reading=base, result=result, source='standard', raw={k: v for k, v in raw.items() if isinstance(v, (int, float, str))})
        if self.io is not None:
            self.io.standby()

    def _reapply(self, points, i, p, key):
        if p.get('applied') and self.io and not self.manual_cal:
            self._work(lambda: self.io.apply(p, cancel=lambda: self.stop), lambda out, exc: self._after_apply(points, i, p, key, exc))
        else:
            self._ask(points, i, p, key)

    def _after_apply(self, points, i, p, key, exc):
        if isinstance(exc, hh.Cancelled):
            self._ask_abort()
        elif exc is not None:
            self._error(exc)
        else:
            self._ask(points, i, p, key)

    # ---- results --------------------------------------------------------------------------------------------------------------
    def _store(self, p, **fields):
        r = p.get('_route')
        if self.demo:
            fields.setdefault('standard', 'demo')
        else:
            fields.setdefault('standard', r.standard if (r is not None and r.auto) else 'manual')
            if r is not None:
                fields.setdefault('route', r.to_dict())
        super()._store(p, **fields)

    # ---- report ---------------------------------------------------------------------------------------------------------------------
    def standard_of(self, p, r=None):
        r = r if r is not None else self._record_for(p)
        return (r or {}).get('standard') or ('demo' if self.demo else 'manual')

    def certificate_row(self, p, r):
        std = self.standard_of(p, r)
        self._row_std = std
        try:
            row = super().certificate_row(p, r)
        finally:
            self._row_std = None
        run = p.get('run') or {}
        if run.get('op', 'dmm') != 'dmm' or run.get('kind') in ('FREQ', 'PERIOD'):
            if run.get('kind') in ('FREQ', 'PERIOD'):
                row['Nominal'] = row['Nominal'].split(' @ ')[0]
            row['Description'] = _ascii(hh.describe(p))
        if p.get('base_unit') == 'dB' and p['test'] == 'numeric':          # decibels are never SI-prefixed (no 'mdB')
            dp = max([len(x.split('.')[1]) if '.' in x else 0 for x in (p['low'], p['high'])] + [1])
            row.update({'Nominal': f'{p["nominal"]:.{dp}f} dB', 'Tolerance -': p['low'], 'Tolerance +': p['high'], 'UOM': 'dB'})
            if r.get('reading') is not None:
                row['As Found'] = r.get('entered', '')
        if not row.get('Uncertainty'):
            a = self.plan_values(p, std)
            if a and a.get('uncertainty'):
                import uncertainty
                row['Uncertainty'] = uncertainty.format_value(a['uncertainty'], run.get('unit') or p.get('base_unit'))
        row['Description'] = f'{row["Description"]}  [{std}]'
        return row

    def plan_values(self, p, std):
        """The matcher's snapshot for the point (uncertainty, TAR, TUR) when the standard that DID the point is the one it was computed for and the limits
        are those of the period it was computed for; None otherwise (no ratio is claimed for a substituted standard or another period)."""
        a = (p.get('dsb') or {}).get('assignment') or {}
        plan_period = (self.dsb.get('plan') or {}).get('period', self.dsb.get('period'))
        if std in ('', 'manual', 'demo') or a.get('standard') != std or self.period != plan_period or a.get('status') not in (None, 'assigned'):
            return None
        return a

    def certificate_fields(self, p):
        r = self._record_for(p)
        std = self.standard_of(p, r)
        self._row_std = std
        try:
            fields = super().certificate_fields(p)
        finally:
            self._row_std = None
        if fields.get('TAR') or fields.get('TUR'):
            return fields
        a = self.plan_values(p, std)
        if not a:
            return dict(TAR='', TUR='')
        import tartur
        return dict(TAR=tartur.format_ratio(a['tar']) if a.get('tar') else '', TUR=tartur.format_ratio(a['tur']) if a.get('tur') else '')

    def used_standards(self):
        """{model: points} of the standards that did the recorded points; 'manual' counts the by-hand points."""
        out = {}
        for rec in list(self.found.values()) + list(self.left.values()):
            s = rec.get('standard') or 'manual'
            out[s] = out.get(s, 0) + 1
        return out

    def report_title(self):
        return f'{self.info["name"]} - {self.dsb.get("title")}'

    def report_header(self, src):
        d = self.dsb
        label = next((x['label'] for x in d.get('periods', []) if x['id'] == self.period), self.period)
        used = self.used_standards()
        shown = '; '.join(f'{m} ({n})' for m, n in sorted(used.items()) if m not in ('manual', 'demo'))
        header = [('Instrument', self.info['name']), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                  ('Datasheet', f'{d.get("title")}, version {d.get("version")}' + (f' ({d["revision"]})' if d.get('revision') else '') + ', user-built'),
                  ('Make / model', f'{d.get("make")} {d.get("model")}'), ('Period', label),
                  ('Limits applied', f'User-built datasheet, {label}'), ('Source', src['document'])]
        if shown:
            header.append(('Standards', shown))
        if used.get('manual'):
            header.append(('By hand', f'{used["manual"]} point(s) set up / read by the operator ([manual])'))
        unverified = sorted({(rec.get('route') or {}).get('standard') for rec in list(self.found.values()) + list(self.left.values())
                             if (rec.get('route') or {}).get('status') == 'unverified'} - {None, ''})
        if unverified:
            header.append(('Unverified', 'Instrument commands not yet confirmed on hardware: ' + ', '.join(unverified)))
        if self.demo:
            header.append(('Mode', 'DEMO - synthetic data, not calibration evidence'))
        return header

    def report_details(self, details):
        """The 'standards used' list gains the standards that actually did the points (their serial numbers and due dates are the technician's)."""
        details = dict(details or {})
        have = list(details.get('standards') or [])
        if not self.demo:
            for model, n in sorted(self.used_standards().items()):
                if model in ('manual', 'demo') or any(model in (s.get('description') or '') for s in have):
                    continue
                info = dm.DRIVER_TABLE.get(model)
                have.append(dict(description=f'{info.label if info else model} (sourced / read {n} point(s))', serial='', due=''))
        details['standards'] = have
        return details


def _ascii(text):
    import report_pdf
    return report_pdf.ascii_unit(text)


# ============================================================================================================== entry point
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='Run a user-built datasheet (Datasheet Builder).')
    ap.add_argument('--spec', help='the datasheet\'s runnable spec file')
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--asset')
    ap.add_argument('--period')
    args, _unknown = ap.parse_known_args(sys.argv[1:] if argv is None else argv)
    path = args.spec
    root = tk.Tk()
    if not path:
        folder = appdata.data_dir() / 'user_specs'
        path = filedialog.askopenfilename(title='Open a user-built datasheet', initialdir=str(folder), filetypes=[('Datasheet spec', '*.json')])
        if not path:
            root.destroy()
            return
    try:
        spec = load_spec(path)
        app = DsbApp(root, spec, demo=args.demo, period=args.period)
    except (procspec.SpecError, SpecProblem, OSError, ValueError, db.DsError) as exc:
        messagebox.showerror('User-built datasheet', f'{path}\n\n{exc}')
        root.destroy()
        return
    if args.asset:
        app.asset.set(args.asset)
    root.mainloop()
