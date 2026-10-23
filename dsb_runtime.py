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

MANUAL CALIBRATIONS (spec option `manual_entry`, set by the Cal Processor (.MDD) import or by the owner's flag in the Datasheet Builder): nothing is sourced or
read by the program.  The points are the same engine points (typed reading, padding, judge_numeric, As Found / As Left, checkpoint, PDF); no standard is
routed, no calibrator is offered or connected, and the setup / function / high-voltage prompts of a driven run are not shown (nothing is driven).  The test
point grid takes the typed readings directly (manual_grid.py: Enter = save and next point) on top of the ordinary reading window of Run All Pending.  The same
grid entry is offered for a datasheet whose every point the matcher finds no standard for (all hand-set).

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
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import appdata
import calibrator_fit
import drivers
import fgen_verification as fg
import handheld_dmm as hh
import reset_startup
import tds2000c_verification as tds
import virtualbench
import ui_theme as ui
import datasheet_builder as db
import datasheet_builder_match as dm
import datasheet_builder_specs as dsp
import dsb_override
import dsb_rules as rules
import procspec

SCOPE_KINDS = ('SCOPE_GAIN', 'SCOPE_OFFSET', 'SCOPE_BW', 'SCOPE_TIMEBASE', 'SCOPE_TRIGGER')
SCOPE_OPS = {'SCOPE_GAIN': 'scope_dc', 'SCOPE_OFFSET': 'scope_dc', 'SCOPE_BW': 'scope_bw', 'SCOPE_TIMEBASE': 'scope_marker', 'SCOPE_TRIGGER': 'scope_trigger'}
LEVEL_KINDS = ('GEN_AMPL', 'ACV')                     # a measuring standard reads an AC level (V rms)
FREQ_KINDS = ('GEN_FREQ', 'FREQ', 'PERIOD')           # ... or a frequency / period
GROUP = {'scope_dc': 'SCOPE_DC', 'scope_bw': 'SCOPE_SINE', 'scope_trigger': 'SCOPE_SINE', 'scope_marker': 'SCOPE_MARKER'}
SOURCE_MODELS = ('5560A', '5522A', '5520A')      # '5520A': DMM-type points only (its published specification decides which: calibrator_fit); no scope option
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
    if (spec.get('options') or {}).get('manual_entry'):          # a manual calibration: no standard is looked for; every point is typed
        new = copy.deepcopy(spec)
        plan = {}
        for step in new['steps']:
            if 'dsb' in step:
                a = dict(point_id=step['dsb'].get('point_id'), status='manual', mode='manual', standard='', automation='manual',
                         message='manual calibration: the technician types the reading')
                step['dsb']['assignment'] = plan[a['point_id']] = a
        new['dsb']['plan'] = dict(period=head.get('period'), assignments=plan, uncovered=[], summary={}, notes=['manual calibration'])
        return new
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


def _with_rules(spec) -> dict:
    """The spec with the run-time options of the Datasheet Builder rules (a copy; the saved spec file is not touched): one high-voltage question per hook-up group (rule 9)."""
    new = dict(spec)
    new['options'] = dict(spec.get('options') or {}, hv_once_per_group=True)
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
    manual = bool((spec.get('options') or {}).get('manual_entry'))
    for p in pts:
        if 'dsb' in p:
            decorate(p)
            if manual:
                manual_words(p)
    return pts


def nominal_text(p) -> str:
    """The nominal of a point as the technician reads it: the source document's own text when the point carries it (Cal Processor import), else the
    value in its display unit with the frequency.  Display only."""
    d = p.get('dsb') or {}
    label = (d.get('label') or '').strip()
    if label:
        return label
    run = p.get('run') or {}
    if p.get('test') != 'numeric' or run.get('nominal') is None:
        return p.get('title') or p.get('section', '')
    text = hh._fmt(run['nominal'], run.get('unit', ''))
    return text + (f' @ {hh._fmt(run["frequency"], "Hz")}' if run.get('frequency') else '')


def manual_words(p):
    """The wording of a point of a manual calibration: what is to be set (the nominal) and what the unit under test is asked for.  Nothing is sourced."""
    text = nominal_text(p)
    if p.get('test') == 'numeric':
        p['dsb_desc'] = f'{p["section"]}: {text}'
        p['dsb_device'] = f'{p["section"]}' + (f'\nRange: {p["range"]}' if p.get('range') else '')
    return p


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
    """Why this standard's output cannot make the point (None when it can)."""
    run = p['run']
    if model == '5520A':
        if run['op'] != 'dmm':
            return 'the 5520A scope option is not in the imported sheet and its commands are not confirmed: scope and generator points use a 5522A or 5560A'
        for req in calibrator_fit.handheld_requests([p]):
            verdict = calibrator_fit.check('5520A', req)
            if not verdict.ok:
                return verdict.reason
        return None
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

    def __init__(self, addrs, counter_ref='EXT', transports=None, mods=None, scope=False, virtual=False, extra=()):
        """addrs: {model: {'address': VISA text, 'baud': int}}; transports: {model: transport} (simulated benches).
        extra: [(label, driver, role)] drivers that are already open, role 'standard' or 'uut' (an instrument under test the program talks to): they are reset
        with the others (a 'uut' after the operator notice), start-state checked and closed with the run.  None today in a normal run; benches and tests use it."""
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual:
            virtualbench.mark_log(self.log)
        self.drivers, self.counter_ref = {}, counter_ref
        self.extra = [(str(lbl), drv, role) for lbl, drv, role in extra]
        self.scope = scope
        self.cal = None
        self._hot = set()
        self._saved_lines = 0                    # command-log lines already written to disk (save_log appends only the new ones)
        self._clock = time.monotonic             # the stable-reading timeout's clock (tests replace it)
        self.standby_ok = True
        t = transports or {}
        try:
            for model in list(dict.fromkeys(list(t) + list(addrs))):
                self.drivers[model] = self._open(model, addrs.get(model) or {}, t.get(model))
            self.cal = next((self.drivers[m] for m in SOURCE_MODELS if m in self.drivers), None)
            for m in SOURCE_MODELS:
                if m in self.drivers and scope and m != '5520A':        # a 5520A has no scope route here: its reset sends no SCOPE command
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
            cls = (drivers.Fluke5560A if model == '5560A' else drivers.Fluke5520A if model == '5520A' else
                   (drivers.Fluke5522AScope if self.scope else drivers.Fluke5522A))
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
        # sources first; the unit under test has no remote interface here (typed readings) unless a driver for it was attached (extra, role 'uut')
        return (self.sources() + self.measuring() + [d for _l, d, r in self.extra if r != 'uut'],
                [d for _l, d, r in self.extra if r == 'uut'])

    def pm_drivers(self):
        return tuple(self.drivers.values()) + tuple(d for _l, d, _r in self.extra)

    # ---- rule 7: start-state check (read-only) ----------------------------------------------------------------------------
    def start_state_items(self):
        """[(label, driver)] of every open instrument of the run, the unit under test last."""
        items = [(m, d) for m, d in self.drivers.items()] + [(lbl, d) for lbl, d, r in self.extra if r != 'uut'] + [(lbl, d) for lbl, d, r in self.extra if r == 'uut']
        return items

    def has_start_state_checks(self) -> bool:
        return any(rules.declared_probes(d) for _l, d in self.start_state_items())

    def start_state_check(self):
        """Run every declared probe once (read-only) and log it.  Returns [dsb_rules.ProbeResult].  Never writes to an instrument."""
        return rules.run_probes(self.start_state_items(), self.log)

    def session_check(self):
        """A Run that skips the reset (already reset this session): every calibrator is put in STANDBY and the read-back must say so (OPER? = 0), else SafetyError.
        Read-only apart from the STBY itself, which is the standing rule before every point."""
        for d in self.sources():
            d.standby_quiet()
            if d.ask('oper.query').strip() != '0':
                raise drivers.SafetyError(f'{d.label}: STANDBY could not be confirmed (OPER? is not 0). Check the front panel before running.')
        self.log.add('--', 'session check: calibrator(s) in STANDBY (read back)', 'SESSION')

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
        for d in list(self.drivers.values()) + [d for _l, d, _r in self.extra]:
            try:
                d.cleanup()
            except Exception:
                pass
            try:
                d.close()
            except Exception:
                pass
        self.save_log()

    def save_log(self):
        """Append the command-log lines that are not on disk yet (rule 11: the log is saved before an error dialog and again at close; nothing is written twice).
        A virtual (demo) session is never evidence and writes nothing."""
        if virtualbench.log_is_virtual(self.log):
            return
        lines = self.log.lines()
        new = lines[self._saved_lines:]
        if not new:
            return
        try:
            folder = Path.home() / '.calibration_suite'
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  user-built datasheet session' + ('' if self._saved_lines == 0 else ' (continued)') + '\n' + '\n'.join(new) + '\n')
            self._saved_lines = len(lines)
        except OSError:
            pass

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
            if self.cal.ask('oper.query').strip() != '1':        # rule 6: the engine sends OPER without a read-back; a user-built sheet reads it (read-only) and refuses to go on
                raise drivers.InstrumentError(f'{self.cal.label} did not confirm OPERATE for {hh.describe(p)}; the reading would be against no output.')
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
        self._wait(virtualbench.scaled(self._settle(p), self.virtual), cancel)

    def apply_reference(self, p, cancel=None):
        """Bandwidth: the leveled sine at the reference frequency (the operator notes the level before the test frequency is applied)."""
        run, route = p['run'], p['_route']
        self.cal = self.drivers[route.standard]
        self.standby()
        r = self._runner(route.standard)
        r.select_levsine()
        r.set_sine(run['amplitude'], run['reference_hz'], settle=0.0)
        self._hot.add(self.cal.label)
        self._wait(virtualbench.scaled(self._settle(p), self.virtual), cancel)

    # ---- the measuring side -------------------------------------------------------------------------------------
    def read_level(self, p, freq, route, conv=None, cancel=None):
        """V rms of the unit under test's output at `freq` on the 5790B (fgen_verification's _std_volts does the reading and the frequency check).  The settings are
        written, read back and compared ONCE; the reading is then polled until it is stable (rule 8, `stable_read`: every poll is a read-only MEAS?) and the LAST
        reading is returned exactly as read.  conv: how a reading is compared for stability (default: V rms divided by the waveform factor, the datasheet's unit)."""
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
        rf = rms_factor(run)
        volts, _res = self.stable_read(p, lambda: fg.IO._std_volts(SimpleNamespace(std=std), freq), conv or (lambda v: v / rf), cancel=cancel)
        return volts, dict(input=inp, range_expected_v=expected_rms)

    # ---- rule 8: settle by stable reading ----------------------------------------------------------------------------------
    def stable_spec(self, p):
        """The stable-reading settings for point p: tunables 'dsb.stable.*' (procedure modifications, UNVERIFIED estimates), a point may carry its own
        (stable_n / stable_band / stable_timeout); the fixed settle time of the point is the MINIMUM.  The band is in the datasheet's base unit."""
        n = int(p.get('stable_n') or self.pm_param('dsb.stable.n', 3))
        counts = float(p.get('stable_band') or self.pm_param('dsb.stable.band_counts', 3.0))
        timeout = float(p.get('stable_timeout') or self.pm_param('dsb.stable.timeout', 30.0))
        factor = float(p.get('factor') or 1.0)
        return rules.StableSpec(n=n, band=rules.default_band(p, counts) * factor, minimum_s=virtualbench.scaled(self._settle(p), self.virtual),
                                timeout_s=virtualbench.scaled(timeout, self.virtual))

    def stable_read(self, p, read, conv, cancel=None):
        """`read()` = ONE read-only query returning the instrument's raw reading; `conv(raw)` = the value compared (datasheet base unit).  Returns (raw reading of
        the LAST poll, StableResult); the outcome goes to the command log (a timeout as a '!!' line).  No averaging: what is recorded is what was read last."""
        box = {}

        def one():
            box['raw'] = read()
            return conv(box['raw'])
        _value, res = rules.settle_stable(one, self.stable_spec(p), cancel=cancel, wait=self._wait, clock=self._clock)
        unit = hh.SYMBOL.get(p.get('base_unit'), p.get('base_unit') or '')
        self.log.add('--' if res.stable else '!!', f'{p["id"]}: ' + res.text(unit), 'SETTLE')
        return box['raw'], res

    def read_frequency(self, p, route, cancel=None):
        """Hz on a 53131A / 53132A: channel 1, 50 ohm, AC, 1 s gate, the expected frequency; the timebase selected and checked (same calls as fgen_verification)."""
        c = self.drivers[route.standard]
        run = p['run']
        expected = (1.0 / run['nominal']) if run['kind'] == 'PERIOD' else run['nominal']
        ref_hz = c.set_reference(self.counter_ref)
        c.configure_frequency(channel=1, gate_s=COUNTER_GATE_S, impedance=50, coupling='AC', expected_hz=expected)
        src, _auto = c.reference()
        if src != self.counter_ref:
            raise drivers.InstrumentError(f'Counter timebase is {src}, expected {self.counter_ref}.')
        f, _res = self.stable_read(p, c.frequency, lambda hz: (1.0 / hz) if run['kind'] == 'PERIOD' else hz, cancel=cancel)
        raw = dict(counter=(c.idn.split(',')[1].strip() if ',' in (c.idn or '') else c.idn), gate_s=COUNTER_GATE_S,
                   reference=(f'EXT {ref_hz / 1e6:g} MHz (checked)' if self.counter_ref == 'EXT' and ref_hz else 'INT'))
        return f, raw

    def measure(self, p, route, refs=None, cancel=None):
        """(reading in the datasheet's unit, raw dict) for a unit-under-test OUTPUT point read by `route`'s standard.  `refs` = the flatness references taken so far."""
        run = p['run']
        db = lambda v: 20.0 * math.log10(v)
        try:
            if run['op'] == 'std_level':
                v, raw = self.read_level(p, run['frequency'] or 1000.0, route, cancel=cancel)
                return v / rms_factor(run), dict(raw, vrms=v)
            if run['op'] == 'std_freq':
                f, raw = self.read_frequency(p, route, cancel=cancel)
                return ((1.0 / f) if run['kind'] == 'PERIOD' else f), dict(raw, hz=f)
            if run['op'] == 'std_flat':
                v, raw = self.read_level(p, run['frequency'], route, conv=db, cancel=cancel)
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

    def read_reference(self, p, route, cancel=None):
        """Flatness: the level at the reference frequency (the unit under test has been set to it by the operator)."""
        try:
            v, raw = self.read_level(dict(p, run=dict(p['run'])), p['run']['reference_hz'], route, conv=lambda x: 20.0 * math.log10(x), cancel=cancel)
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
class DsbApp(hh.App, reset_startup.AppResetMixin, dsb_override.DsbOverrideMixin):
    """The handheld engine's window for a user-built datasheet.  The run-time rules of the Datasheet Builder (NOTES.md 'DSB run-time rules implemented') are
    added here and in DsbIO; the engine itself (handheld_dmm.py) is not edited."""
    RESET_ONCE_PER_SESSION = True      # rule 10 (reset_startup pattern): the first Run of a session resets; later Runs only check the connection and the start state
    MANUAL_OVERRIDE = True             # rule 13: right-click a point > Enter reading manually (dsb_override.py; the 8808A's mixin)

    def __init__(self, root, spec, demo=False, io_factory=None, period=None, fast_demo=False):
        self.manual_entry = bool((spec.get('options') or {}).get('manual_entry'))      # a manual calibration (see the module docstring)
        self.section_mode = {}                                                          # rule 12: {section: auto | hand | skip}
        spec = _with_rules(with_plan(spec))
        self.dsb = spec['dsb']
        self.grid_entry = None
        self.period = period or self.dsb.get('period')
        if self.period != self.dsb.get('period'):
            spec = _with_rules(spec_for_period(spec, self.period))
        self._cur = None
        self._hookup_seen = None
        self.std_addr = {}
        self.dsb_ref = {}
        self.counter_ref = tk.StringVar(value='EXT')
        self.period_var = tk.StringVar(value=self.period)
        if self.dsb.get('uid'):
            self.pm_proc_key = 'ds:' + str(self.dsb['uid'])      # verified.py: this datasheet's own verified / locked state, not its model's
        super().__init__(root, self.dsb['model'], demo=demo, spec=spec, io_factory=io_factory, fast_demo=fast_demo)
        self.counter_ref.set(self.settings.get('counter_ref', 'EXT'))

    # ---- rule 12: per-section modes (Automated / Typed by hand / Not tested) --------------------------------------------------------
    def allowed_modes(self):
        return (rules.HAND, rules.SKIP) if self.manual_entry else rules.MODES

    def _init_modes(self, pts):
        """The modes for the sections of `pts`, in their order: what was set before is kept, a new section starts Automated (a manual calibration: Typed by hand)."""
        sections = list(dict.fromkeys(p['section'] for p in pts))
        self.section_mode = rules.normalise_modes(self.section_mode, sections, default=rules.HAND if self.manual_entry else rules.AUTO, allowed=self.allowed_modes())

    def mode_of(self, p) -> str:
        return self.section_mode.get(p['section'], rules.HAND if self.manual_entry else rules.AUTO)

    def is_skipped(self, p) -> bool:
        return self.mode_of(p) == rules.SKIP

    def hand_point(self, p) -> bool:
        """True when nothing is sourced or read by the program for p: a manual calibration, or a section set to Typed by hand."""
        return self.manual_entry or self.mode_of(p) == rules.HAND

    def skipped_unrecorded(self, p) -> bool:
        """A point of a Not-tested section with no reading (a reading recorded before the section was switched off stays, and is reported)."""
        return self.is_skipped(p) and not (self.found.get(str(p['id'])) or self.left.get(str(p['id'])))

    def any_auto(self, points) -> bool:
        return any(not self.hand_point(p) and not self.is_skipped(p) for p in points)

    def set_section_mode(self, section, mode, quiet=False) -> bool:
        """Switch one section.  Never discards a recorded point: only what the run does with the section's points changes.  Refused while a run is in progress."""
        if mode not in self.allowed_modes() or section not in self.section_mode:
            return False
        if self.busy:
            self.status.set('Stop the run first: the section setting cannot be changed while points are being run.')
            self._sync_mode_box()
            return False
        if self.section_mode[section] == mode:
            return True
        self.section_mode[section] = mode
        text = f'Section "{section}" is now {rules.MODE_LABEL[mode]}.'
        self._relabel_current(section)
        self.refresh()
        self._sync_mode_box()
        if not quiet:
            self.status.set(text + ' ' + rules.MODE_HINT[mode])
        self._log_note(text)
        if self.asset.get().strip():
            self.save(silent=True)                           # the setting is part of the progress file
        return True

    def _log_note(self, text):
        io = self.io
        if io is not None and not self.demo:
            try:
                io.log.add('--', text, 'OPERATOR')
            except Exception:
                pass

    def section_label(self, section) -> str:
        m = self.section_mode.get(section, rules.AUTO)
        return section if m == rules.AUTO else f'{section}  ({"hand" if m == rules.HAND else "skip"})'

    def _label_map(self):
        return {self.section_label(s): s for s in self.section_mode}

    def _relabel_current(self, section):
        sh = self.shell
        try:
            if self.show_section.get() == section:
                sh.current = self.section_label(section)
        except Exception:
            pass

    def pick_section(self, name):
        """Sidebar / drop-down choice: the shown names carry the mode, the Show filter works on the section itself."""
        self.show_section.set(self._label_map().get(name, name))
        self._sync_mode_box()
        self.refresh()

    def _build_section_bar(self):
        """The control of rule 12: in the bar above the test points, next to the Show boxes; acts on the section chosen in the sidebar."""
        try:
            bar = self.shell.section_picker.master
        except Exception:
            return
        box = ttk.Frame(bar)
        box.pack(side='left', padx=(24, 0))
        self.section_caption = tk.StringVar(value='Section mode: choose a section on the left')
        ttk.Label(box, textvariable=self.section_caption, style='Muted.TLabel').pack(side='left', padx=(0, 6))
        self.section_mode_var = tk.StringVar(value='')
        self.section_mode_box = ttk.Combobox(box, textvariable=self.section_mode_var, values=[rules.MODE_LABEL[m] for m in self.allowed_modes()], state='disabled', width=15)
        self.section_mode_box.pack(side='left')
        self.section_mode_box.bind('<<ComboboxSelected>>', lambda _e: self._on_mode_chosen())
        try:
            self.tree.tag_configure('skipped', foreground=ui.C['muted'])
        except Exception:
            pass
        self._sync_mode_box()

    def _shown_section(self):
        sec = self.show_section.get()
        return sec if sec in self.section_mode else None

    def _sync_mode_box(self):
        box = getattr(self, 'section_mode_box', None)
        if box is None:
            return
        sec = self._shown_section()
        try:
            if sec is None:
                self.section_caption.set('Section mode: choose a section on the left')
                self.section_mode_var.set('')
                box.configure(state='disabled')
            else:
                short = sec if len(sec) <= 26 else sec[:25] + '...'
                self.section_caption.set(f'Mode of "{short}":')
                self.section_mode_var.set(rules.MODE_LABEL[self.section_mode[sec]])
                box.configure(state='disabled' if self.busy else 'readonly')
        except Exception:
            pass

    def _on_mode_chosen(self):
        sec = self._shown_section()
        mode = rules.LABEL_MODE.get(self.section_mode_var.get())
        if sec is not None and mode is not None:
            self.set_section_mode(sec, mode)

    def update_summary(self):
        """Progress ring and sidebar: a Not-tested section never counts as pending or failed (a point recorded before it was switched off still counts)."""
        active = [p for p in self.points if not self.skipped_unrecorded(p)]
        self.update_shell_progress(active)
        order, groups = [], {}
        for p in self.points:
            if self.skipped_unrecorded(p):
                groups.setdefault(p['section'], [])
                if p['section'] not in order:
                    order.append(p['section'])
                continue
            if p['section'] not in groups:
                groups[p['section']] = []
                order.append(p['section'])
            groups[p['section']].append(self.results.get(str(p['id']), {}).get('result', ''))
        self.shell.set_sections([(self.section_label(s), groups[s].count('PASS'), groups[s].count('FAIL'), len(groups[s])) for s in order])

    def not_tested_sections(self):
        """[(section, points without a reading)] for every section set to Not tested (for the report and the notice)."""
        out = []
        for s, m in self.section_mode.items():
            if m == rules.SKIP:
                n = sum(1 for p in self.points if p['section'] == s and self.skipped_unrecorded(p))
                if n:
                    out.append((s, n))
        return out

    def grid_allows(self, p):
        """(allowed, why not) for a reading typed into the test point grid: only where the program reads nothing (rule 12)."""
        if self.manual_entry or self.all_hand_set():
            return (True, '') if not self.is_skipped(p) else (False, f'Section "{p["section"]}" is set to Not tested.')
        m = self.mode_of(p)
        if m == rules.HAND:
            return True, ''
        if m == rules.SKIP:
            return False, f'Section "{p["section"]}" is set to Not tested. Change its mode to type readings.'
        return False, (f'Section "{p["section"]}" is Automated: its readings come from the run. Set the section to Typed by hand to type them here, '
                       f'or right-click the point > Enter reading manually.')

    # ---- hooks of the handheld engine -----------------------------------------------------------------------------
    def build_points(self):
        pts = runtime_points(self.spec, self.model)
        self._init_modes(pts)
        return pts

    def calibrator_offer(self):
        """The 5520A for a user-built datasheet: it is offered, and a DMM-type point it cannot source is routed by hand with the reason (limit_problem); scope and
        generator points never go to it.  The note under the picker counts those points."""
        reqs = [r for p in self.points if (p.get('run') or {}).get('op') == 'dmm' and p['run']['direction'] == 'measure' and p.get('applied')
                for r in calibrator_fit.handheld_requests([p])]
        return calibrator_fit.make_offer('5520A', reqs, per_point_manual=True, unverified=drivers.Fluke5520A.unverified_summary())

    def settings_name(self):
        return 'dsb_' + ''.join(c if c.isalnum() else '_' for c in (self.dsb.get('uid') or self.model))

    def _checkpoint_path(self):
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        uid = ''.join(c for c in str(self.dsb.get('uid') or self.model) if c.isalnum())[:12]
        return appdata.progress_path(f'DSB_{uid}_{asset}_checkpoint.json')

    def save_fields(self):
        d = super().save_fields()
        d['dsb'] = dict(uid=self.dsb.get('uid'), version=self.dsb.get('version'), period=self.period, sections=dict(self.section_mode))
        return d

    def load_results(self, data):
        super().load_results(data)
        saved = (data.get('dsb') or {}).get('sections')
        if isinstance(saved, dict):                              # the section settings of the run that was saved (rule 12); a file without them leaves the window's
            self.section_mode = rules.normalise_modes({**self.section_mode, **saved}, list(self.section_mode), allowed=self.allowed_modes())
            self._sync_mode_box()

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
        if self.hand_point(p):
            return dict(device='UNIT UNDER TEST', source='TEST POINT')
        if run.get('op', 'dmm') == 'dmm':
            return {}
        if run['direction'] == 'source':
            return dict(device='MEASURING STANDARD')
        return dict(device='OSCILLOSCOPE', source='CALIBRATOR SCOPE OUTPUT')

    # ---- window -------------------------------------------------------------------------------------------------------
    def _build_ui(self):
        super()._build_ui()
        self._build_section_bar()
        if self.manual_entry:
            self._build_manual_ui()
            self._attach_grid_entry()
            return
        self._attach_grid_entry()
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

    # ---- manual calibrations: typed readings, the grid entry -------------------------------------------------------------
    def _build_manual_ui(self):
        """Window of a manual calibration: nothing to connect (the calibrator box is shown but switched off), a notice that says how to enter the readings."""
        self.cal_mode.set(hh.CAL_CHOICES[2])
        for name in ('cal_combo', 'cal_entry', 'btn_test', 'btn_find'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state='disabled')
        holder = self.shell.notice_holder
        for child in list(holder.winfo_children()):                 # the stock text ('the calibrator is programmed and enabled ...') does not apply
            label = getattr(child, 'label', None)
            try:
                if label is not None and str(label.cget('text')).startswith('For each point the calibrator is programmed'):
                    child.destroy()
            except Exception:
                pass
        d = self.shell.drawer_body
        ttk.Separator(d).grid(row=20, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        ttk.Label(d, text='Manual calibration', style='Bold.TLabel').grid(row=21, column=0, columnspan=2, sticky='w')
        ttk.Label(d, text='No instrument is connected or driven by this program. You set the stimulus with your own standards and type what the unit under test shows.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=22, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.shell.notice(f'Manual calibration "{self.dsb.get("title")}", version {self.dsb.get("version")}. ' + self.GRID_HELP +
                          ' Limits are those of the source datasheet.', 'info')
        self.tree.heading('nominal', text='Nominal')
        self._retitle_manual()

    def _retitle_manual(self):
        """The stock banner says 'Performance Verification' and 'the calibrator output is set for you': neither is true of a manual calibration."""
        old = ' Performance Verification'
        try:
            title = str(self.root.title())
            if old in title:
                self.root.title(title.replace(old, ' Manual Calibration'))
        except Exception:
            pass

        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        try:
            for w in walk(self.root):
                text = str(w.cget('text')) if 'text' in w.keys() else ''
                if text.endswith('  -  Performance Verification'):
                    w.configure(text=text.replace('Performance Verification', 'Manual Calibration'))
            src = self.spec.get('source', {}).get('document', '')
            self.shell.subtitle.set(f'Manual calibration: you set the stimulus with your own standards and type each reading  |  {len(self.points)} points  |  {src}')
        except Exception:
            pass

    GRID_HELP = ('Click a test point and type the reading (without the unit): Enter saves it and opens the next point, Esc closes the box, '
                 'Up / Down move. Run All Pending asks for each point in its own window instead.')

    def _attach_grid_entry(self):
        """Typed readings straight into the test point grid (manual_grid.py) for a manual calibration, and for any datasheet whose every point is done by hand."""
        import manual_grid                      # always attached: a section can be switched to Typed by hand before Run (grid_allows decides per point)
        self.grid_entry = manual_grid.GridEntry(self, self.tree)

    def all_hand_set(self) -> bool:
        """True when the standards plan has an assignment for every point and none of them can be automated (datasheet_builder_match): all points are hand-set."""
        steps = [s for s in self.spec.get('steps', []) if 'dsb' in s]
        if not steps:
            return False
        for s in steps:
            a = s['dsb'].get('assignment')
            if not a:
                return False
            if a.get('status') == 'assigned' and a.get('automation') in (dm.OK, dm.UNVERIFIED):
                return False
        return True

    def type_reading(self, p, text):
        """Record a reading typed into the grid for point p in the data mode on screen (As Found / As Left): the engine's own steps for a typed reading
        (hh.pad_reading to the point's resolution, hh.judge_numeric, _store), nothing else.  Returns the stored record.  Raises ValueError with the reason
        in words for text that is not a reading (empty, not a number, NaN / infinity, a comma, a unit) and RuntimeError when it cannot be recorded now."""
        if self.busy:
            raise RuntimeError('A run is in progress: finish or stop it before typing readings into the grid.')
        ok, why = self.grid_allows(p)
        if not ok:
            raise RuntimeError(why)
        asset = self.asset.get().strip()
        if not asset:
            raise RuntimeError('Enter the instrument ID first.')
        live = self.pm_begin_run([p], asset)             # the saved procedure modifications of this asset, as at the start of a run
        if not live:
            raise RuntimeError('This point is skipped by a procedure modification.')
        p = live[0]
        raw = (text or '').strip()
        if not raw:
            raise ValueError('Type a reading.')
        if p['test'] == 'numeric':
            if ',' in raw:
                raise ValueError('Use a decimal point, not a comma.')
            entered = hh.pad_reading(p, raw)
            result, base = hh.judge_numeric(p, entered, True)          # ValueError: not a number / NaN / infinity
            self._store(p, entered=entered, reading=base, result=result, annunciator=None, source='typed')
        else:
            word = raw.lower()
            if word in ('y', 'yes', 'p', 'pass'):
                ok = True
            elif word in ('n', 'no', 'f', 'fail'):
                ok = False
            else:
                raise ValueError('Type Y (yes / pass) or N (no / fail).')
            self._store(p, entered=('Pass' if ok else 'Fail') if p['test'] == 'visual' else (f'Beeper {p["expect"]}' if ok else f'Beeper not {p["expect"]}'),
                        reading=None, result='PASS' if ok else 'FAIL', source='typed')
        return self.results[p['id']]

    def _row(self, p):
        values, tags = super()._row(p)
        if self.manual_entry:
            values = list(values)
            values[1] = f'{p["section"]}' + (f'   ({p["range"]})' if p.get('range') else '')
            values[2] = nominal_text(p)
            values = tuple(values)
        if self.skipped_unrecorded(p):                       # rule 12: never shown as pending or failed
            values = tuple(values[:-1]) + ('⊘ not tested',)
            tags = ('skipped',)
        return values, tags

    def on_period(self):
        new = self.period_var.get()
        if new == self.period:
            return
        if self.found or self.left:
            self.period_var.set(self.period)
            messagebox.showinfo('Specification period', 'Readings are already recorded, so the period cannot be changed now. Start a new run to use another period.')
            return
        try:
            self.spec = _with_rules(spec_for_period(self.spec, new))
        except SpecProblem as exc:
            self.period_var.set(self.period)
            messagebox.showerror('Specification period', str(exc))
            return
        self.period = new
        self.points[:] = runtime_points(self.spec, self.model)
        self._init_modes(self.points)
        self.by_id = {p['id']: p for p in self.points}
        self.refresh()
        self.status.set(f'Limits now follow the {new} specification.')

    # ---- standards and connection -------------------------------------------------------------------------------------
    def engine_model(self):
        """The calibrator chosen in the engine's own box ('5560A' / '5522A' / '5520A'), None for Manual."""
        text = self.cal_mode.get()
        if self.manual_entry:
            return None
        return None if text.startswith('Manual') else ('5522A' if '5522A' in text else '5520A' if '5520A' in text else '5560A')

    def standards_needed(self):
        out = []
        if self.manual_entry:
            return out
        for p in self.points:
            m = _assigned(p)
            if m and m not in out:
                out.append(m)
        for m in SOURCE_MODELS:
            if m == '5520A' and not self.cal_offer.offered:
                continue
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
        if self.manual_entry:
            return False
        return bool(self.engine_model()) or any(v.get().strip() for v in self.std_addr.values())

    def connect(self):
        self.disconnect()
        if self.io_factory:
            self.io = self.io_factory()
        elif self.virtual:                  # demo: the calibrator is a virtual 5522A / 5560A; a 5790B / counter has no simulated unit under test, so those points are done by hand
            eng = self.engine_model()
            transports = {eng: virtualbench.calibrator_transport(eng)[1]} if eng else {}
            self.io = DsbIO({}, counter_ref=self.counter_ref.get(), transports=transports, mods=self.pm_state, scope=self.has_scope(), virtual=True)
        else:
            self.io = DsbIO(self.addresses(), counter_ref=self.counter_ref.get(), mods=self.pm_state, scope=self.has_scope())
        self.io.auto_ramp = self._auto_ramp()
        self._set_conn(True)
        if not self.demo:
            self._save_settings()

    def test_connection(self):
        if self.fast_demo:
            messagebox.showinfo('Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.')
            return
        if self.manual_entry:
            messagebox.showinfo('Manual calibration', 'This is a manual calibration: nothing is connected or driven by the program. Type the readings into the grid.')
            return
        if self.virtual and not self.engine_model():
            messagebox.showinfo('Manual', 'The calibrator is set to Manual: every point is done by hand. The program tells you what to set and asks for the readings.')
            return
        if not self.virtual and not self.wants_connection():
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
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Outputs are NOT enabled.')
        messagebox.showinfo('Connected' + (' (DEMO)' if self.virtual else ''), f'{self.io.ident}{tag}\nOutputs are not enabled.')

    def _save_settings(self):
        super()._save_settings()
        for model, var in self.std_addr.items():
            self.settings.set('addr_' + model, var.get())
        self.settings.set('counter_ref', self.counter_ref.get())
        self.settings.save()

    # ---- routing ---------------------------------------------------------------------------------------------------------
    def route(self, p):
        if self.fast_demo:
            return Route(False, '', _assigned(p), 'manual', 'demo mode')
        if self.hand_point(p) and not self.manual_entry:
            return Route(False, '', _assigned(p), 'manual', 'section set to Typed by hand')
        connected = self.io.models() if self.io is not None else set()
        eng = self.engine_model()
        return route_for(p, connected, prefer=[eng] if eng else [])

    def pm_live_context(self):
        """The Edit-procedure window also lists this runtime's own settings (rule 8: the stable-reading settle), not only the handheld engine's."""
        import procmods_engine as pme
        ctx = super().pm_live_context()
        ctx.defaults = {**pme.defaults_for('dsb'), **dict(ctx.defaults or {})}
        return ctx

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
        if self.manual_entry:
            return True
        p = self._cur
        if p is not None and self.hand_point(p):
            return True
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
        asked = len(points)
        points = [p for p in points if not self.is_skipped(p)]                 # rule 12: a Not-tested section is never run
        if not points:
            self.status.set('The selected point(s) are in a section set to Not tested: nothing to run. Change the section\'s mode to run it.')
            return
        if len(points) < asked:
            self.status.set(f'{asked - len(points)} selected point(s) are in sections set to Not tested and are left out.')
        points = self.pm_begin_run(points, self.asset.get().strip())
        if not points:
            self.status.set('Every selected point is skipped by a procedure modification.')
            return
        if not self.confirm_found_overwrite(points):
            return
        if not self.fast_demo and self.any_auto(points) and (self.wants_connection() or (self.virtual and self.engine_model())) and self.io is None:
            self.test_connection()
            if self.io is None:
                return
        self.dsb_ref = {}                                           # references (bandwidth, flatness) are taken again at the start of every run
        self._hookup_seen = None                                    # rule 9: the cables are asked once at the start of a Run and again only when the hook-up changes
        self._hv_ok_key = None
        if self.io is not None:
            self.io.auto_ramp = self._auto_ramp()                   # the datasheet's option (default: straight to the test value, no ramp)
        self.stop = False
        self.busy = True
        self._last_switch = None
        self.reset_then(lambda: self._next(points, 0, None))      # every run (first, re-run, resume): reset every connected standard first

    def reset_extra_uuts(self):
        return []

    # ---- rule 10 (reset once per session) and rule 7 (start-state check before the first point) ------------------------------------
    def reset_skip_run(self):
        """Worker-thread part of a Run that skips the reset: the calibrators are put in standby and the read-back is checked (the start-state check follows)."""
        self.io.session_check()

    def reset_then(self, proceed):
        """The engine's reset (first Run of a session) or its skip, then the start-state check of every instrument that declares one, then the first point."""
        super().reset_then(lambda: self._start_state_then(proceed))

    def _start_state_then(self, proceed):
        io = self.io
        if io is None or self.fast_demo or not getattr(io, 'has_start_state_checks', lambda: False)():
            proceed()
            return
        self.status.set('Checking the instruments\' start state (read-only) ...')

        def done(results, exc):
            if exc is not None:
                self._save_cmd_log()
                self._error(exc)
                return
            if not rules.failed(results):
                proceed()
                return
            self.busy = False
            self.status.set('Start-state check failed - run not started: ' + '; '.join(f'{r.instrument}: {r.name}' for r in rules.failed(results)))
            self._save_cmd_log()
            messagebox.showerror('Check the instrument settings', rules.failure_text(results))
        self._work(io.start_state_check, done)

    def _save_cmd_log(self):
        """Rule 11: the command log goes to disk BEFORE an error dialog (what the instruments were told and answered is the evidence of the failure)."""
        io = self.io
        if io is not None:
            try:
                io.save_log()
            except Exception:
                pass

    def _error(self, exc):
        self._save_cmd_log()
        super()._error(exc)

    def _reset_failed(self, msg, skipped=False):
        self._save_cmd_log()
        super()._reset_failed(msg, skipped)

    def _next(self, points, i, previous):
        self._cur = points[i] if (i < len(points) and not self.stop) else None
        if self._cur is not None:
            self._cur['_route'] = self.route(self._cur)
            if not self.fast_demo:
                self._note_route(self._cur)
        super()._next(points, i, previous)

    def _note_route(self, p):
        r = p['_route']
        if self.io is not None and r.reason and self.io.log is not None:
            self.io.log.add('--', f'{p["id"]}: ' + (f'using {r.standard}: ' if r.auto else 'done by hand: ') + r.reason, 'ROUTE')

    def _prompt_setup(self, p):
        if self.hand_point(p):                      # nothing is rewired or driven: the technician only types readings
            return True
        return self._prompt_setup_driven(p)

    def _prompt_function(self, p):
        if self.hand_point(p):
            return True
        if p.get('run') and p['run']['op'] != 'dmm':
            self._last_switch = p['switch']           # the wiring / set-up prompt of scope and generator points already says what to change
            return True
        return super()._prompt_function(p)

    def _high_voltage(self, p):
        if self.hand_point(p):                      # the program outputs nothing
            return False
        run = p.get('run') or {}
        if run.get('op') == 'scope_dc' and run.get('nominal') is not None:
            return abs(run['nominal']) >= self.spec.get('options', {}).get('hv_threshold_v', 500)
        return super()._high_voltage(p)

    def uut_steps(self, p):
        """What the operator sets on the unit under test for a generator point."""
        run = p['run']
        text = (p.get('setup') or '').split(' Read the measuring standard')[0]
        return text or f'Set the unit under test to output {hh._fmt(run["nominal"], run["unit"])}.'

    def _prompt_setup_driven(self, p):
        run = p.get('run')
        if not run or run['direction'] != 'source':
            return super()._prompt_setup(p)
        r = p.get('_route') or Route()
        facts = [('Next point', f'{p["n"]} of {len(self.points)}'), ('Test', hh.describe(p)), ('Unit under test', p['switch'])]
        steps = []
        if run['op'] != 'std_flat' or not r.auto:
            steps.append(('Unit under test', self.uut_steps(p)))
        hook = None
        if r.auto:
            std = r.standard
            if std == '5790B':
                inp = (run['settings'].get('std_input') or ('WBND' if (run['frequency'] or 0) > WIDEBAND_ABOVE_HZ else 'INPUT1')).upper()
                hook = (std, inp)
                text = (f'Unit under test output to the 5790B {STD_INPUT_TEXT.get(inp, inp)} input. The 5790B input impedance is not the generator\'s '
                        f'load: set the unit under test\'s load / termination as the datasheet says.')
            else:
                hook = (std, self.counter_ref.get())
                text = f'Unit under test output to the {std} channel 1 input (50 Ω, AC coupled). The counter timebase is {self.counter_ref.get()}.'
            if hook != self._hookup_seen:                              # rule 9: the cable prompt only when the hook-up changes (the unit-under-test steps stay: they set the point)
                steps.append(('Connect', text))
            steps.append(('Reading', f'The program reads the {std} itself' + (' (the reference frequency first, then the test frequency)' if run['op'] == 'std_flat' else '') + '.'))
            if r.substituted:
                steps.append(('Standard', f'The datasheet assigns {r.assigned}; {r.standard} is used instead ({r.reason}).'))
        else:
            steps.append(('Reading', 'Read your measuring standard' + (f' (the datasheet assigns the {_assigned(p)})' if _assigned(p) else '') + ' and type its reading' +
                          (' as the level relative to the reference frequency, in dB.' if run['op'] == 'std_flat' else '.') +
                          (f' Done by hand: {r.reason}.' if r.reason else '')))
        steps.append(('Afterwards', 'Switch the unit under test output OFF when the reading has been taken.'))
        ok = ui.confirm_steps(self.root, 'Check the setup', f'Set up for {p["section"]}', steps, facts=facts, ok='Done - continue')
        if ok and hook is not None:
            self._hookup_seen = hook
        return ok

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
        if run and not self.fast_demo:
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
        """The routed measuring standard reads the unit under test's output; on a problem the operator chooses: type the reading, skip, stop.
        Rule 8: the reading is polled until it is stable.  Rule 13: a reading typed (right-click > Enter reading manually) while the point is measured replaces
        the automatic one when it arrives."""
        run, route = p['run'], p['_route']
        self.status.set(f'Point {p["n"]}/{len(self.points)}: reading the {route.standard} (waiting for a stable reading) ...')
        self._mo_current = p

        def finish(out, exc):
            if exc is None:
                reading, raw = out
                typed = self.mo_take_pending(p)
                self._mo_current = None
                if typed is not None:                               # typed by the technician while the standard was being read: the log keeps the automatic reading
                    self.mo_commit(p, typed, auto=float(reading))
                    if self.io is not None:
                        self.io.standby()
                else:
                    self._store_measured(p, reading, raw, route)
                self.root.after(30, lambda: self._next(points, i + 1, key))
                return
            armed = self.mo_take_pending(p) if not isinstance(exc, hh.Cancelled) else None
            self._mo_current = None
            if armed is not None:                                   # the automatic reading failed but a typed one was armed: use it (logged with the reason)
                self.mo_commit(p, armed, auto=None, why=str(exc))
                if self.io is not None:
                    self.io.standby()
                self.root.after(30, lambda: self._next(points, i + 1, key))
                return
            if isinstance(exc, hh.Cancelled):
                self._ask_abort()
                return
            if not isinstance(exc, (drivers.InstrumentError, drivers.TransportError)) and not isinstance(exc, OSError):
                self._error(exc)
                return
            self._save_cmd_log()                                    # rule 11: the log is on disk before the dialog
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
            cancel = lambda: self.stop
            if run['op'] == 'std_flat':
                key_ = DsbIO.flat_key(p)
                if key_ not in self.dsb_ref:
                    self._confirm_on_ui(f'Reference frequency', [('Unit under test', f'Set the unit under test to the REFERENCE frequency {hh._fmt(run["reference_hz"], "Hz")} '
                                                                  f'(same level {hh._fmt(run["amplitude"], "V")}).')], p)
                    v, _raw = self.io.read_reference(p, route, cancel=cancel)
                    self.dsb_ref[key_] = v
                self._confirm_on_ui('Test frequency', [('Unit under test', f'Set the unit under test to {hh._fmt(run["frequency"], "Hz")} (same level).')], p)
            return self.io.measure(p, route, refs=self.dsb_ref, cancel=cancel)
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
        if not (self.manual_entry and std in ('', 'manual')):         # a manual calibration's rows carry no '[manual]' tag (all of it is by hand)
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
        if self.manual_entry:                       # the lab's report name; the datasheet's title and make / model are in the header
            return 'Calibration Data'
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
        if used.get('manual') and not self.manual_entry:
            header.append(('By hand', f'{used["manual"]} point(s) set up / read by the operator ([manual])'))
        skipped = self.not_tested_sections()
        if skipped:                                                    # rule 12: a section switched to Not tested is listed, never printed as failed or pending
            header.append(('Not tested', '; '.join(f'{s} ({n} point(s))' for s, n in skipped)))
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
        details['limit_labels'] = True                      # the two limit columns print as Low Limit / High Limit (their values are the absolute limits, as always)
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
    ap.add_argument('--fast-demo', action='store_true', dest='fast_demo')
    ap.add_argument('--asset')
    ap.add_argument('--period')
    ap.add_argument('--accept-unverified', dest='accept_unverified', default='')      # fingerprint of the unverified-command list the Builder showed (rule 2)
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
        if not (args.demo or args.fast_demo):
            import dsb_prerun                         # rule 2: commands not verified on hardware are listed and must be accepted before real instruments run
            if not dsb_prerun.accepted(root, spec, args.accept_unverified):
                root.destroy()
                return
        app = DsbApp(root, spec, demo=args.demo or args.fast_demo, period=args.period, fast_demo=args.fast_demo)
    except (procspec.SpecError, SpecProblem, OSError, ValueError, db.DsError) as exc:
        messagebox.showerror('User-built datasheet', f'{path}\n\n{exc}')
        root.destroy()
        return
    if args.asset:
        app.asset.set(args.asset)
    root.mainloop()
