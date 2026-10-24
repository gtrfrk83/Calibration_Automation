"""Engine side of "modify procedures on the fly": the mixin every procedure uses, and the list of what each procedure lets you tune.

Tk-free.  The editing UI is elsewhere; this module only LOADS the saved overrides at the start of a run, applies them, binds the
command overrides to the drivers, and remembers what was applied so a report can list it.  Nothing here edits anything: editing needs
an unlocked developer-mode session and lives in procmods.Store.

Public API (stable)
    ProcModsMixin       mix into an engine's App and into its IO class (both share one ModsState)
        App side   pm_init(engine, model, demo=False, lists=(), on_change=None, store=None, devmode=None, shape=None)
                   pm_load(asset=None)                         resolve + apply to the registered point lists (no run started)
                   pm_begin_run(points=None, asset=None, factory_only=False) -> runnable live points (skipped ones removed), or None
                                                               (the UI's "Run factory" sets app.pm_factory_run = True: used once)
                   pm_revert(points) / pm_apply(points)        take the overrides off / put them on a point list again (period changes)
                   pm_limit_points()                           factory points as the editor must see them (create overrides against these)
                   pm_checkpoint_fields() -> dict              {} when unmodified; else {'overrides': snapshot} for the checkpoint
                   pm_on_checkpoint(data, choose=None)         saved snapshot vs current store: 'saved' (default) or 'current'
                   pm_result_fields() -> dict                  {} when unmodified; else {'ovrev': n} for a result record
                   pm_record_run(run_id, demo=False)           run_overrides row for an issued report (never in demo)
                   pm_runnable(p) / pm_skipped(p)              skip flag helpers
        IO side    pm_attach(state, *drivers)                  bind the command overrides to the drivers (call after connect)
                   pm_param(name, default, point=None)         a tunable: the stored override, else `default` (the SAME object)
    applied_modifications(run) -> [dict]                       THE function for the report: see its docstring
    applied_info(run) -> dict                                  summary + hash + flags (tolerances modified, factory run, rejected ...)
    TUNABLES / tunables_for(engine) / defaults_for(engine)     what each engine exposes (name -> default, bounds), for the UI
    MODEL_IDS                                                  the model string used as the override scope for each engine

Guarantees
  * No override stored (or "Run factory"): every pm_ call returns exactly what the engine had before - same objects, same values, same
    log lines - so command transcripts and results are byte-identical.  tests/test_golden_commands.py is the proof for the I/O.
  * Limits (error / low / high) change only through valid, enabled, HMAC-verified `limit` overrides (procmods.apply_points guards it;
    the guard is re-run here on the real point lists).  A tampered limit row is not applied and is reported (applied_info()['tampered']).
  * An override never raises into a run: a bad value, a stale entry or a rejected command is dropped, logged ('!!' line in the command
    log) and listed in state.warnings.  Safety prompts, output/standby handling and pass/fail logic are not reachable from here.
"""
from __future__ import annotations

import contextlib
import copy
import functools
import threading

import procmods
import procmods_live
import procmods_pointdef as pdef

LiveApplyError = procmods_live.LiveApplyError           # engines catch it as procmods_engine.LiveApplyError

# --------------------------------------------------------------------------------------------------------------------------------
# What each engine is called in the override store (scope 'model' entries use this string; 'asset' entries use the instrument ID)
# --------------------------------------------------------------------------------------------------------------------------------
MODEL_IDS = {
    'truevolt': 'the DMM model, e.g. 34470A',
    'dacq': 'the model, 34970A or 34972A',
    'fgen': 'the model, e.g. 33220A',
    'handheld': 'the spec model key, e.g. 115 or 289',
    'a34401': '34401A',
    'f8846a': '8846A',
    'f8808a': '8808A',
    'mdo': 'MDO4000C',
    'ws': 'WS4104HD',
    'k2000': '2000',
    'a34410a': 'the model, 34410A or 34411A',
    'dsb': 'the user-built datasheet (a Datasheet Builder sheet is run by the handheld engine; these are its own settings)',
}

# --------------------------------------------------------------------------------------------------------------------------------
# Tunables: (engine, key, default, lo, hi, label, unit, type, affects_conditions)
# `default` MUST equal the value the engine uses when no override exists (tests/test_procmods_engines.py compares them with what the
# engines actually ask for).  Bounds are checked when an override is created AND again every time the engine reads it.
# Ranges are not tunable: a point's range is part of its identity and of the manufacturer's limit table.
# --------------------------------------------------------------------------------------------------------------------------------
_T = []


def _t(engine, key, default, lo, hi, label, unit='s', ptype='float', conditions=True):
    _T.append((engine, key, default, lo, hi, label, unit, ptype, conditions))


for _e, _name in (('truevolt', 'Truevolt'), ('dacq', '34970A / 34972A')):
    _t(_e, 'settle.freq', 3.0, 0.2, 120.0, f'{_name}: settle, frequency points')
    _t(_e, 'settle.ohm_high', 4.0, 0.2, 120.0, f'{_name}: settle, resistance ranges of 10 Mohm and above')
    _t(_e, 'settle.zero', 1.5, 0.2, 120.0, f'{_name}: settle before a zero-offset reading')
    _t(_e, 'settle.default', 2.0, 0.2, 120.0, f'{_name}: settle, other points')
_t('truevolt', 'settle.manual', 2.0, 0.2, 120.0, 'Truevolt: settle, manually connected standard')
_t('truevolt', 'settle.ac_3hz', 9.0, 0.2, 120.0, 'Truevolt: settle, AC with the 3 Hz filter')
_t('truevolt', 'settle.ac_20hz', 5.0, 0.2, 120.0, 'Truevolt: settle, AC with the 20 Hz filter')
_t('truevolt', 'settle.ac_200hz', 4.0, 0.2, 120.0, 'Truevolt: settle, AC with the 200 Hz filter')
_t('truevolt', 'settle.ac_other', 4.0, 0.2, 120.0, 'Truevolt: settle, AC with any other filter')
_t('dacq', 'settle.ac_10hz', 6.0, 0.2, 120.0, '34970A / 34972A: settle, AC at 10 Hz')
_t('dacq', 'settle.ac_20hz', 5.0, 0.2, 120.0, '34970A / 34972A: settle, AC at 20 Hz')
_t('dacq', 'settle.ac_other', 4.0, 0.2, 120.0, '34970A / 34972A: settle, AC at other frequencies')
_t('dacq', 'settle.aci', 4.0, 0.2, 120.0, '34970A / 34972A: settle, AC current')
_t('dacq', 'settle.dci_ohm2', 3.0, 0.2, 120.0, '34970A / 34972A: settle, DC current and 2-wire resistance')
for _e, _name in (('a34401', '34401A'), ('f8846a', '8846A')):
    _t(_e, 'settle.zero', 1.5, 0.2, 120.0, f'{_name}: settle before a zero-offset reading')
    _t(_e, 'settle.ac', 3.5, 0.2, 120.0, f'{_name}: settle, AC points')
    _t(_e, 'settle.default', 2.0, 0.2, 120.0, f'{_name}: settle, other points')
for _key, _default, _what in (('zero', 2.0, 'settle before a zero-offset reading'), ('default', 2.0, 'settle, DC, resistance and current points'),
                              ('ac', 4.0, 'settle, AC points'), ('freq', 3.0, 'settle, frequency points'),
                              ('ohm_high', 4.0, 'settle, resistance ranges of 10 Mohm and above')):
    _t('f8808a', 'settle.' + _key, _default, 0.2, 120.0, f'8808A: {_what}')
_t('f8808a', 'settle.dci_10a', 8.0, 0.2, 120.0, '8808A: settle, 10 A DC current range (UNVERIFIED estimate)')
_t('f8808a', 'settle.dci_low', 6.0, 0.2, 120.0, '8808A: settle, 200 uA and 2000 uA DC current ranges (UNVERIFIED estimate)')
_t('k2000', 'settle.default', 2.0, 0.2, 120.0, 'Keithley 2000: settle, DC volts and other points')
_t('k2000', 'settle.ac', 20.0, 0.2, 120.0, 'Keithley 2000: settle, AC volts and AC current (3 Hz detector bandwidth; UNVERIFIED estimate)')
_t('k2000', 'settle.dci', 3.0, 0.2, 120.0, 'Keithley 2000: settle, DC current')
_t('k2000', 'settle.ohm', 3.0, 0.2, 120.0, 'Keithley 2000: settle, resistance below 10 Mohm')
_t('k2000', 'settle.ohm_high', 5.0, 0.2, 120.0, 'Keithley 2000: settle, resistance of 10 Mohm and above')
_t('k2000', 'settle.rel_zero', 5.0, 0.2, 120.0, 'Keithley 2000: settle at 0 mV before the DC volts REL zero')
for _key, _default, _what in (('zero', 1.5, 'settle before a zero-offset reading'), ('default', 2.0, 'settle, DC volts and resistance points'),
                              ('ac', 9.0, 'settle, AC volts and AC current'), ('freq', 3.0, 'settle, frequency points'), ('dci', 3.0, 'settle, DC current'),
                              ('ohm_high', 4.0, 'settle, resistance ranges of 10 Mohm and above'), ('manual', 2.0, 'settle, capacitance standard connected by the technician')):
    _t('a34410a', 'settle.' + _key, _default, 0.2, 120.0, f'Keysight 34410A / 34411A: {_what}')
_t('fgen', 'settle.timebase', 2.0, 0.2, 120.0, 'Function generator: settle, time base')
_t('fgen', 'settle.acamp', 1.0, 0.2, 120.0, 'Function generator: settle, AC amplitude')
_t('fgen', 'settle.lfflat', 1.0, 0.2, 120.0, 'Function generator: settle, low-frequency flatness')
_t('fgen', 'settle.flat', 1.5, 0.2, 120.0, 'Function generator: settle, flatness')
_t('fgen', 'settle.other', 1.0, 0.2, 120.0, 'Function generator: settle, other points')
_t('fgen', 'counter_gate', 1.0, 0.1, 10.0, 'Function generator: frequency counter gate time')
# User-built datasheets (dsb_runtime.py), stable-reading settle for a reading the program takes from a measuring standard: wait until N consecutive readings
# agree within a band; the point's ordinary settle time is the minimum, the timeout is the cap.  The values are choices of this program, not manual figures.
_t('dsb', 'stable.n', 3, 2, 20, 'User-built datasheet: consecutive readings that must agree (UNVERIFIED estimate)', unit='', ptype='int', conditions=True)
_t('dsb', 'stable.band_counts', 3.0, 1.0, 100.0, 'User-built datasheet: agreement band, in counts of the point\'s resolution (UNVERIFIED estimate)', unit='counts', conditions=True)
_t('dsb', 'stable.timeout', 30.0, 1.0, 600.0, 'User-built datasheet: stable-reading timeout, the cap on the wait (UNVERIFIED estimate)', conditions=True)
_t('handheld', 'settle.default', 3.0, 0.5, 120.0, 'Handheld DMM: settle after the output is on (points without their own value)')
_t('handheld', 'ramp_delay', 5.0, 5.0, 60.0, 'Handheld DMM: delay between high-voltage ramp steps (the manual says 5 s: can only be lengthened)')
_t('handheld', 'ir_timeout', 45.0, 5.0, 300.0, 'Handheld DMM: infrared reading timeout (points without their own value)', conditions=False)
_t('mdo', 'pause_scale', 1.0, 0.25, 10.0, "MDO4000C: multiplier on the procedure's settle and sweep waits (not on waits inside the driver)", unit='x')
_t('mdo', 'reconnect_attempts', 36, 1, 120, 'MDO4000C: attempts to reconnect after the power cycle', unit='', ptype='int', conditions=False)
_t('mdo', 'reconnect_wait', 5.0, 1.0, 60.0, 'MDO4000C: wait between reconnect attempts', conditions=False)
_t('mdo', 'delta_wait', 8.0, 1.0, 120.0, 'MDO4000C: wait for the channel-to-channel delay statistics')
_t('ws', 'rms_delay', 3, 0.2, 120.0, 'WaveSurfer: RMS noise settle')
_t('ws', 'rms_samples', 5, 1, 100, 'WaveSurfer: RMS noise samples', unit='', ptype='int', conditions=False)
_t('ws', 'dcv_settle', 3.0, 0.5, 30.0, 'WaveSurfer: DC voltage settle after OPER')
_t('ws', 'imp_settle', 2.0, 0.5, 30.0, 'WaveSurfer: input impedance settle')
_t('ws', 'imp_samples', 3, 1, 20, 'WaveSurfer: input impedance samples', unit='', ptype='int', conditions=False)
_t('ws', 'offset_settle', 3.0, 0.5, 60.0, 'WaveSurfer: offset settle')
_t('ws', 'bw_settle', 3.0, 0.5, 60.0, 'WaveSurfer: bandwidth settle')
_t('ws', 'tb_settle', 3.0, 0.5, 60.0, 'WaveSurfer: time base settle after OPER')
_t('ws', 'tb_samples', 5, 1, 50, 'WaveSurfer: time base samples', unit='', ptype='int', conditions=False)
_t('ws', 'tb_read_gap', 0.5, 0.1, 10.0, 'WaveSurfer: time base gap between readings')
_t('ws', 'trig_settle', 1.0, 0.2, 30.0, 'WaveSurfer: trigger level settle after each step')

# per-point settle (any point can carry its own): written into the point as p[field] and read by the engine before its table
PER_POINT = [('point.settle', 'settle_s', 'Settle time for this point', 0.2, 120.0),
             ('handheld.point.settle', 'settle', 'Settle time for this point (handheld)', 0.5, 120.0),
             ('handheld.point.ir_timeout', 'ir_timeout', 'Infrared reading timeout for this point', 5.0, 300.0)]

# per-point versions of the stable-reading settings (a point can carry its own; written into the point as p[field]): (name, field, type, label, lo, hi, unit)
PER_POINT_DSB = [('dsb.point.stable_n', 'stable_n', 'int', 'Stable reading: consecutive readings that must agree, for this point (UNVERIFIED estimate)', 2, 20, ''),
                 ('dsb.point.stable_band', 'stable_band', 'float', 'Stable reading: agreement band in counts, for this point (UNVERIFIED estimate)', 1.0, 100.0, 'counts'),
                 ('dsb.point.stable_timeout', 'stable_timeout', 'float', 'Stable reading: timeout for this point (UNVERIFIED estimate)', 1.0, 600.0, 's')]

TUNABLES: dict = {}          # full name -> dict(engine, key, default, lo, hi, label, unit, type, affects_conditions)


def _register():
    for engine, key, default, lo, hi, label, unit, ptype, cond in _T:
        name = f'{engine}.{key}'
        TUNABLES[name] = dict(engine=engine, key=key, name=name, default=default, lo=lo, hi=hi, label=label, unit=unit, type=ptype,
                              affects_conditions=cond)
        procmods.register_param(name, ptype, lo, hi, affects_conditions=cond, label=label, unit=unit)
    for name, field, label, lo, hi in PER_POINT:
        procmods.register_param(name, 'float', lo, hi, affects_conditions=True, per_point=True, point_field=field, label=label, unit='s')
    for name, field, ptype, label, lo, hi, unit in PER_POINT_DSB:
        procmods.register_param(name, ptype, lo, hi, affects_conditions=True, per_point=True, point_field=field, label=label, unit=unit)


_register()


def tunables_for(engine) -> list:
    """The tunables of one engine ('truevolt', 'dacq', 'fgen', 'handheld', 'a34401', 'f8846a', 'mdo', 'ws'), registry order."""
    return [dict(t) for t in TUNABLES.values() if t['engine'] == engine]


def defaults_for(engine) -> dict:
    """{full name: factory default} - the `defaults` argument of procmods.setting_rows()."""
    return {t['name']: t['default'] for t in tunables_for(engine)}


# --------------------------------------------------------------------------------------------------------------------------------
# state shared by an engine's App and its IO
# --------------------------------------------------------------------------------------------------------------------------------
_EDIT_KINDS = ('point', 'limit', 'text')


class ModsState:
    """Resolved overrides for one engine / model / asset, plus what was done with them.  One instance per App, shared with its IO."""

    def __init__(self, engine, model, *, demo=False, store=None, devmode=None, shape=None, on_change=None, proc_key=''):
        self.engine, self.model, self.demo = engine, model, bool(demo)
        self.proc_key = proc_key or ''           # verified.py key of the procedure ('ds:<uid>' for a user-built one); '' = lock by model
        self.store, self.devmode = store, devmode
        self.shape = shape                       # 'band' when the engine judges low <= x <= high even though points also carry 'error'
        self.on_change = on_change
        self.asset, self.idn = '', None
        self.factory_only = False
        self.suppressed = 0                      # overrides that "Run factory" switched off
        self.pinned = False                      # True after a progress file's saved snapshot was chosen: load() keeps that set ...
        self.pinned_asset = ''                   # ... for this instrument only
        self.oset = procmods.OverrideSet([], model, '')
        self.snapshot = None
        self.insts: list = []
        self.warnings: list = []
        self.rejected: list = []                 # (driver, key, uid, [problems])
        self.lists: dict = {}                    # id(list) -> [list, originals, limit_idx]
        self.run_entries: list = []              # "this run only" overrides (never written to the store); live edits add to it
        self.run_asset = ''                      # the Instrument ID they were made for
        self.live = procmods_live.LiveState()    # live editing inside a running procedure (procmods_live)
        self.plan_mode = False                   # a private clone used for a dry run (procmods_plan): keeps the REAL instrument's identity
        self._keymap: dict = {}                  # id(current point object) -> (object, factory point key): patched copies keep their key
        self._lock = threading.RLock()

    # ---- resolving ---------------------------------------------------------------------------------------------------------
    def _store(self):
        if self.store is None:
            self.store = procmods.Store(devmode=self.devmode)
        return self.store

    def load(self, asset=None, idn=None, factory_only=None, run_entries=None):
        """Resolve the stored overrides for (model, asset) and put them on the registered point lists.  Never raises."""
        with self._lock:
            if asset is not None:
                if self.pinned and str(asset or '').strip().casefold() != self.pinned_asset.casefold():
                    self.pinned = False                       # another instrument: the saved snapshot of the last one does not apply
                new_asset = str(asset or '').strip()
                if self.run_entries and self.run_asset and new_asset.casefold() != self.run_asset.casefold():
                    self.run_entries.clear()                  # "this run only" edits belong to the instrument they were made for
                    self.run_asset = ''
                    self.live.start_run()
                self.asset = new_asset
            if idn:
                self.idn = idn
            if factory_only is not None:
                self.factory_only = bool(factory_only)
            self.warnings = []
            if run_entries is None:
                run_entries = self.run_entries
            if self.pinned and not self.factory_only and not run_entries:
                if idn:
                    self.oset = self.oset.with_idn(idn)
                self._reapply_all()
                if self.insts:
                    self._bind_commands()
                return self.oset
            try:
                kw = dict(store=self._store(), devmode=self.devmode)
                full = procmods.resolve(self.model, self.asset, run_entries, self.idn, **kw)
                self.suppressed = len(full.active()) if self.factory_only else 0
                self.oset = procmods.resolve(self.model, self.asset, None, self.idn, factory_only=True, **kw) if self.factory_only else full
            except Exception as exc:                                    # an unreadable store must never stop a run
                self.oset = procmods.OverrideSet([], self.model, self.asset)
                self.warnings.append(f'overrides could not be loaded ({type(exc).__name__}); running with factory settings')
            for e in self.oset.tampered():
                self.warnings.append(f'TAMPERED tolerance change {e["uid"]} for {e["target"]} is not applied')
            self._reapply_all()
            if self.insts:
                self._bind_commands()
            return self.oset

    # ---- tunables ----------------------------------------------------------------------------------------------------------
    def param(self, name, default, point_key=None):
        oset = self.oset
        if not oset:
            return default
        try:
            v = oset.param(name, default, point_key)
        except Exception:
            return default
        if v is default or v is None:
            return default
        if procmods._check_param_value(name, v):                       # out of bounds / wrong type: the factory value is used
            self.warnings.append(f'setting {name} = {v!r} is not valid; the factory value {default!r} is used')
            return default
        spec = procmods.PARAMS.get(name) or {}
        try:
            return int(v) if spec.get('type') == 'int' else float(v)
        except (TypeError, ValueError):
            return default

    # ---- drivers -----------------------------------------------------------------------------------------------------------
    def bind(self, *insts):
        """Remember the drivers, take the identity of the first one as the instrument under test (fw_match), install the command
        overrides.  Call after connect(): that is when *IDN? is known."""
        with self._lock:
            self.insts = [i for i in insts if i is not None]
            idn = getattr(self.insts[0], 'idn', '') if self.insts and not self.plan_mode else ''
            if idn and idn != self.idn:
                self.load(idn=idn)                                       # re-resolve with fw_match evaluated (also rebinds)
            else:
                self._bind_commands()

    def bind_one(self, inst):
        """Bind the command overrides to one driver that was opened after the run started (the WaveSurfer creates a fresh pair of
        drivers for every point).  Does not register the driver and does not touch the point lists."""
        with self._lock:
            self._bind_commands([inst], reset=False)

    def clone_for_plan(self):
        """A private ModsState for a dry run (procmods_plan): the SAVED changes resolved afresh (so a change saved but not yet applied at a
        point boundary is in the plan), this run's own entries, no point lists, the real instrument's identity.  Never shares mutable state
        with this one except the read-only point key map."""
        with self._lock:
            c = ModsState(self.engine, self.model, demo=self.demo, store=self._store(), devmode=self.devmode, shape=self.shape,
                          proc_key=self.proc_key)
            c.plan_mode = True
            c.run_entries = list(self.run_entries)
            c.run_asset = self.run_asset
            c.idn, c.asset = self.idn, self.asset
            c.factory_only, c.pinned, c.pinned_asset = self.factory_only, self.pinned, self.pinned_asset
            c._keymap = self._keymap
            if self.pinned:
                c.oset = self.oset
            else:
                c.load(asset=self.asset)
            return c

    def _bind_commands(self, insts=None, reset=True):
        if reset:
            self.rejected = []
        for inst in (self.insts if insts is None else insts):
            try:
                has = bool(self.oset.entries())                           # candidates, even if none is active before the idn is known
                oset = self.oset.with_idn((self.idn if self.plan_mode else getattr(inst, 'idn', '')) or None) if has else self.oset
                names = [c.__name__ for c in type(inst).__mro__]
                templates = oset.commands_for(inst) if has else {}
                uids = {}
                for e in (oset.active('command') if has else []):
                    if '@' in e['target']:
                        continue                                              # typed for one point: bound below
                    name, _, key = e['target'].partition(':')
                    if name in names and templates.get(key) == e['value'].get('template'):
                        uids[key] = e['uid']
                for uid, probs in (oset.rejected_commands(inst) if has else []):
                    self.rejected.append((type(inst).__name__, '', uid, list(probs)))
                    self.warnings.append(f'command override {uid} not applied: ' + '; '.join(map(str, probs)))
                pt_t, pt_u, pt_rej = oset.point_commands_for(inst) if has else ({}, {}, [])
                for uid, probs in pt_rej:
                    self.rejected.append((type(inst).__name__, '', uid, list(probs)))
                    self.warnings.append(f'point command override {uid} not applied: ' + '; '.join(map(str, probs)))
                extras = oset.extras_for(inst) if has else {}
                for key, uid, probs in inst.use_commands(templates, uids, points=pt_t, point_uids=pt_u, extras=extras):
                    self.rejected.append((type(inst).__name__, key, uid, list(probs)))
            except Exception as exc:                                     # never stop a run over an override
                self.warnings.append(f'could not bind command overrides to {type(inst).__name__} ({type(exc).__name__})')

    # ---- points ------------------------------------------------------------------------------------------------------------
    def _active_edits(self):
        return any(e['kind'] in _EDIT_KINDS or (e['kind'] == 'param' and '@' in e['target']) for e in self.oset.active())

    def patch(self, views):
        """(patched copies of `views`, set of indices whose limits were overridden).  procmods.apply_points guards the limit fields."""
        out = procmods.apply_points(views, self.oset)
        return out, {i: set(q.get('limit_fields') or ()) for i, q in enumerate(out) if q.get('limit_modified')}

    def register(self, points, on_change=None):
        self.lists.setdefault(id(points), [points, list(points), set(), on_change])
        self._remap()
        return points

    def _remap(self):
        """Remember the factory key of every point now in the registered lists (a patched copy has other nominal / limits than the factory
        point its key comes from; the per-point commands are selected by that key)."""
        km = {}
        for ent in self.lists.values():
            for cur, key in zip(ent[0], procmods.point_keys(ent[1])):
                km[id(cur)] = (cur, key)
        self._keymap = km

    def key_of(self, p):
        """The factory key (procmods.point_key / point_keys, with '#n' for duplicates) of a point of a registered list; falls back to
        point_key(p) for anything else."""
        al = self.__dict__.get('_alias')
        if al and id(p) in al and al[id(p)][0] is p:
            return al[id(p)][1]
        hit = self._keymap.get(id(p))
        return hit[1] if hit is not None and hit[0] is p else procmods.point_key(p)

    def alias(self, copy, key):
        """A dry-run helper: let `copy` (a throw-away copy of a live point) count as the point with factory key `key`."""
        self.__dict__.setdefault('_alias', {})[id(copy)] = (copy, key)

    def apply(self, points):
        """Put the active overrides on this live list IN PLACE (entries are replaced by patched copies; originals are kept for revert)."""
        with self._lock:
            ent = self.lists.setdefault(id(points), [points, list(points), set(), None])
            self._revert_entry(ent)
            orig = ent[1] = list(points)
            if not (self.oset and self._active_edits()):
                self._remap()
                self._changed(ent)
                return points
            views = [self.view(p) for p in orig]
            patched, lim = self.patch(views)
            fixed = [self._unview(o, q, i in lim) for i, (o, q) in enumerate(zip(orig, patched))]
            procmods.assert_limits_unchanged(orig, fixed, lim)           # the guard again, on the real engine points
            check = procmods.check_points(views, self.oset)
            for uid, key in check['stale'] + check['orphan']:
                self.warnings.append(f'override {uid} for {key} no longer fits the spec and was not applied')
            points[:] = fixed
            ent[2] = lim
            self._remap()
            self._changed(ent)
            return points

    def revert(self, points):
        with self._lock:
            ent = self.lists.get(id(points))
            if ent:
                self._revert_entry(ent)
                self._remap()

    @staticmethod
    def _revert_entry(ent):
        ent[0][:] = ent[1]
        ent[2] = set()

    def _reapply_all(self):
        for ent in list(self.lists.values()):
            self.apply(ent[0])

    def _changed(self, ent):
        cb = ent[3] or self.on_change
        if cb:
            try:
                cb()
            except Exception:
                pass

    def view(self, p):
        """What procmods sees: for an engine that judges low/high, the redundant 'error' is hidden so a tolerance change is made in the
        field the engine really uses (otherwise it would silently have no effect)."""
        if self.shape == 'band' and 'error' in p and 'low' in p and 'high' in p:
            q = dict(p)
            del q['error']
            return q
        return p

    def factory_points(self):
        """The registered lists' points WITHOUT any modification, as procmods sees them (view()).  The editor must create limit / point
        / text overrides against these (keys, factory limits and hashes come from them)."""
        out = []
        for ent in self.lists.values():
            out += [self.view(p) for p in ent[1]]
        return out

    def _unview(self, orig, patched, limited):
        if self.shape == 'band' and 'error' in orig and 'low' in orig and 'high' in orig:
            patched = dict(patched)
            moved = limited and any(patched.get(k) != orig.get(k) for k in ('low', 'high', 'nominal'))     # a description / unit change keeps 'error'
            patched['error'] = (max(abs(patched['high'] - patched['nominal']), abs(patched['nominal'] - patched['low']))
                                if moved else orig['error'])
        return patched

    # ---- the record --------------------------------------------------------------------------------------------------------
    def begin_run(self, asset=None, factory_only=False, run_entries=None):
        with self._lock:
            self.load(asset=asset, factory_only=factory_only, run_entries=run_entries)
            self.snapshot = procmods.build_snapshot(self.oset, self.snapshot) if self.oset else self.snapshot
            return self.oset

    # ---- live editing (procmods_live) --------------------------------------------------------------------------------------
    def lock_reason(self) -> str:
        """The procedure is verified on hardware and locked (verified.py): no editor may change it.  '' = editable.  Never raises."""
        try:
            return self._store().lock_reason(self.model, self.proc_key) or ''
        except Exception:
            return ''

    def live_blocked_reason(self) -> str:
        """Why the editor cannot change this run (empty = it can)."""
        why = self.lock_reason()
        if why:
            return why
        if self.pinned:
            return ('This run continues under the modifications saved in its progress file. Stop the run and press Run again (or load the '
                    'progress file and choose the current settings) before editing.')
        if self.factory_only:
            return 'This run was started as a FACTORY run (stored modifications switched off). Stop it and start a normal run to edit.'
        return ''

    def commit_live(self, *, standby=None, before=None, log=None, asset=None):
        """Apply the edits saved since the last boundary.  Call ONLY between two points.  `standby()` (the engine's own, once, never retried)
        runs first; if it raises nothing is applied and the edits stay pending.  Re-resolves the store + this run's entries, patches the point
        lists, rebinds the command overrides (no instrument reset), appends a revision to the snapshot and records a live_edits event.
        Returns the event (None when the effective set did not change)."""
        with self._lock:
            if not self.live.dirty:
                return None
            if standby is not None:
                standby()
            old = self.oset
            self.load(asset=asset)
            if self.oset or self.snapshot:
                self.snapshot = procmods.build_snapshot(self.oset, self.snapshot)
            ev = procmods_live.make_event(old, self.oset, rev=self.rev() or len((self.snapshot or {}).get('revs') or []), before=before,
                                          demo=self.demo, standby=standby is not None, point_id=self.point_id_of, redo=self.live.redo)
            self.live.dirty, self.live.dirty_at, self.live.pending = False, None, []
            if ev is not None:
                self.live.events.append(ev)
                if log is not None:
                    try:
                        log.add('--', procmods_live.event_line(ev), 'procmods')
                        for line in self.warnings:
                            log.add('!!', 'OVERRIDE ' + line, 'procmods')
                    except Exception:
                        pass
            return ev

    def point_id_of(self, key):
        """The engine's id of the point with this factory key (None if unknown): for the audit record of a per-point change."""
        for ent in self.lists.values():
            for q, k in zip(ent[1], procmods.point_keys(ent[1])):
                if k == key:
                    return procmods_live.point_id(q)
        return None

    def rev(self):
        revs = (self.snapshot or {}).get('revs') or []
        return revs[-1]['rev'] if revs and self.oset else 0

    def banner(self, log):
        """One line at the top of a command log when overrides are in effect (nothing when unmodified)."""
        if log is None:
            return
        try:
            if self.oset:
                log.add('--', f'overrides rev {self.rev() or 1} hash {self.oset.hash[:12]} ({len(self.oset.active())} active)', 'procmods')
            for line in self.warnings:
                log.add('!!', 'OVERRIDE ' + line, 'procmods')
            if self.factory_only and self.suppressed:
                log.add('--', f'FACTORY RUN: {self.suppressed} stored modification(s) switched off for this run', 'procmods')
        except Exception:
            pass


def point_commands(io_of=None):
    """Decorator for an engine's per-point routine (`IO.measure(self, p, ...)`, `IO.apply(self, p, ...)`, `Runner.run_point(self, p)`): while the
    routine runs, the point-specific command overrides of that point apply and its extra command lines are sent (before the routine's own
    commands, and after them when the routine finished without an error).  Nothing is selected or sent when no override is stored, so an
    unmodified run is byte-identical.  `io_of(self)` returns the IO object when the routine is not a method of the IO itself."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, p, *a, **k):
            io = io_of(self) if io_of else self
            scope = getattr(io, 'pm_point_scope', None)
            if scope is None or getattr(io, 'pm_state', None) is None:
                return fn(self, p, *a, **k)
            with scope(p):
                return fn(self, p, *a, **k)
        return wrapper
    return deco


# --------------------------------------------------------------------------------------------------------------------------------
# the mixin
# --------------------------------------------------------------------------------------------------------------------------------
class ProcModsMixin:
    """See the module docstring.  All names start with pm_ so nothing clashes with an engine's own."""

    # ---- state -------------------------------------------------------------------------------------------------------------
    @property
    def pm_state(self):
        return self.__dict__.get('_pm_state')

    def pm_init(self, engine, model, *, demo=False, lists=(), on_change=None, store=None, devmode=None, shape=None, load=True, proc_key=None):
        """App side.  `lists`: the live point lists to patch in place (a module's POINTS, a handheld self.points).  shape='band' for an
        engine that judges low <= reading <= high.  `on_change()` is called after a list was patched (rebuild id lookups)."""
        st = ModsState(engine, model, demo=demo, store=store, devmode=devmode, shape=shape, on_change=on_change,
                       proc_key=proc_key if proc_key is not None else getattr(self, 'pm_proc_key', ''))
        for lst in lists:
            st.register(lst)
        self.__dict__['_pm_state'] = st
        if load:
            st.load('')
        return st

    def pm_load(self, asset=None):
        st = self.pm_state
        return st.load(asset=asset) if st else None

    def pm_begin_run(self, points=None, asset=None, factory_only=False, run_entries=None):
        """Call at the start of every Run (also on resume): resolve for this asset, patch the point lists, rebind the drivers, write the
        banner to the command log.  `points` (the selection about to be run) is returned re-mapped onto the live, patched points by id
        with skipped ones removed; None when nothing is left to run."""
        st = self.pm_state
        if st is None:
            return points
        factory_only = bool(factory_only) or bool(self.__dict__.pop('pm_factory_run', False))   # 'Run factory' is one-shot
        was_dirty, before_set = st.live.dirty, st.oset
        st.begin_run(asset=asset, factory_only=factory_only, run_entries=run_entries)
        st.live.start_run(None)
        io = self.__dict__.get('io')
        if io is not None and getattr(io, 'pm_state', None) is not st and hasattr(io, 'pm_attach'):
            io.pm_attach(st, *getattr(io, 'pm_drivers', lambda: ())())
        if io is not None:
            st.banner(getattr(io, 'log', None))
        if points is None:
            self._pm_begin_event(was_dirty, before_set, factory_only, None)
            return None
        live = {}
        for ent in st.lists.values():
            for p in ent[0]:
                live[p.get('id')] = p
        mapped = [live.get(p.get('id'), p) for p in points]
        out = [p for p in mapped if not p.get('skip')] or None
        st.live.start_run(out)                                       # live editing: this is the list the run walks
        self._pm_begin_event(was_dirty, before_set, factory_only, out[0] if out else None)
        return out

    def _pm_begin_event(self, was_dirty, before_set, factory_only, first):
        """Edits saved during the previous run / a pause are applied by this Run: record that like any other live application."""
        st = self.pm_state
        if not was_dirty or factory_only:
            return
        io = self.__dict__.get('io')
        ev = procmods_live.make_event(before_set, st.oset, rev=st.rev(), before={'id': procmods_live.point_id(first), 'desc': self.pm_point_title(first)}
                                      if first else None, demo=st.demo, standby=False)
        if ev is None:
            return
        st.live.events.append(ev)
        log = getattr(io, 'log', None) if io is not None else None
        if log is not None:
            try:
                log.add('--', procmods_live.event_line(ev), 'procmods')
            except Exception:
                pass

    def pm_limit_points(self):
        """The factory points as the override layer sees them: create limit / point / text overrides against THESE (for an engine that
        judges low <= x <= high the redundant 'error' is hidden, so the tolerance is edited in the field the engine really uses)."""
        st = self.pm_state
        return st.factory_points() if st else []

    def pm_apply(self, points):
        st = self.pm_state
        return st.apply(points) if st else points

    def pm_revert(self, points):
        st = self.pm_state
        if st:
            st.revert(points)

    @staticmethod
    def pm_skipped(p) -> bool:
        return bool(p.get('skip'))

    @staticmethod
    def pm_runnable(p) -> bool:
        return not p.get('skip')

    # ---- IO side -----------------------------------------------------------------------------------------------------------
    def pm_attach(self, state, *drivers):
        """IO side: share the App's state and bind the command overrides to these drivers.  state=None: nothing happens at all."""
        self.__dict__['_pm_state'] = state
        if state is None:
            return
        state.bind(*drivers)
        state.banner(getattr(self, 'log', None))

    def pm_param(self, name, default, point=None):
        """A tunable.  With no override this returns `default` itself (so the sleep / command is exactly what it always was)."""
        st = self.__dict__.get('_pm_state')
        if st is None:
            return default
        return st.param(name, default, point)

    def pm_text(self, name, default, text):
        """A tunable that feeds an entry box: `text` (the box's literal factory text) when nothing is stored, else the stored value as text."""
        v = self.pm_param(name, default)
        if v is default:
            return text
        return str(int(v)) if isinstance(default, int) and float(v).is_integer() else str(float(v))

    def pm_bind_after_open(self, *drivers):
        """For code that creates a fresh driver per point and calls .open() later: the command overrides are bound right after each
        driver's open() (when its *IDN? is known, so an fw_match condition can be judged).  No state: nothing happens."""
        st = self.pm_state
        if st is None:
            return
        for inst in drivers:
            if inst is None:
                continue
            raw_open = inst.open

            def opened(*a, _raw=raw_open, _inst=inst, **k):
                r = _raw(*a, **k)
                st.bind_one(_inst)
                return r
            inst.open = opened
            st.bind_one(inst)

    # ---- one test point: its commands, point-specific overrides, extra lines (procmods_point_model / procmods_point_ui) -----------------
    def pm_point_key(self, p):
        """The factory key of a point of a registered list (stable even when the point was patched), else procmods.point_key(p)."""
        st = self.pm_state
        return st.key_of(p) if st is not None else procmods.point_key(p)

    def pm_scope_drivers(self) -> list:
        """The drivers that take part in a point (the IO's pm_drivers()); [] when there are none."""
        fn = getattr(self, 'pm_drivers', None)
        try:
            return [d for d in (fn() if fn else ()) if d is not None]
        except Exception:
            return []

    @contextlib.contextmanager
    def pm_point_scope(self, p):
        """See point_commands().  Select the point on every driver, send its 'before' lines, run the body, send its 'after' lines (only when the
        body did not raise), and always deselect the point."""
        st = self.pm_state
        drivers = self.pm_scope_drivers()
        if st is None or not drivers or not hasattr(drivers[0], 'set_point'):
            yield
            return
        if self.__dict__.get('_pm_scope_depth'):                  # a point routine called inside another (the user-datasheet apply -> handheld apply)
            yield
            return
        key = st.key_of(p)
        self.__dict__['_pm_scope_depth'] = 1
        for d in drivers:
            d.set_point(key)
        try:
            for d in drivers:
                d.run_extras('before')
            yield
            for d in drivers:
                d.run_extras('after')
        finally:
            for d in drivers:
                d.set_point(None)
            self.__dict__['_pm_scope_depth'] = 0

    def pm_find_point(self, pid):
        """The live point (as the run uses it) with this id, from the registered lists; None if unknown.  The id may be text (a table row id)."""
        st = self.pm_state
        if st is not None:
            for ent in st.lists.values():
                for q in ent[0]:
                    if str(procmods_live.point_id(q)) == str(pid):
                        return q
        return None

    def pm_factory_point(self, pid):
        """The same point as procmods sees it BEFORE any override (the view the override keys, checks and hashes come from), with its key."""
        st = self.pm_state
        if st is not None:
            for ent in st.lists.values():
                keys = procmods.point_keys(ent[1])
                for q, k in zip(ent[1], keys):
                    if str(procmods_live.point_id(q)) == str(pid):
                        return st.view(q), k
        return None, None

    def pm_point_fields(self, view) -> dict:
        """Which fields of a point the developer-mode editor may change, and how: {'nominal' | 'unit' | 'description': {'paths': [...],
        'reason': '' | why it cannot be edited, 'note': text shown beside the field}}.  Engines override where a field is not what it seems
        (the handheld nominal also sets the calibrator output; the generator and oscilloscope nominals are only the value a reading is judged
        against)."""
        out = {}
        out['nominal'] = {'paths': ['nominal'], 'reason': '' if pdef.has_path(view, 'nominal') else 'this point has no nominal value',
                          'note': 'The nominal is the value the calibrator is told to output and the value the reading is judged against. '
                                  'The meter range and the instruments\' own limits are not changed.'}
        out['unit'] = {'paths': ['unit'], 'reason': '' if pdef.has_path(view, 'unit') else 'this point has no unit', 'note': ''}
        dp = next((x for x in ('description', 'desc') if pdef.has_path(view, x)), None)
        out['description'] = {'paths': [dp] if dp else [], 'reason': '' if dp else 'this point has no description', 'note': ''}
        return out

    def pm_plan_point(self, p):
        """procmods_plan.Plan of the commands the engine sends for point `p` (a dry run of its own point routine on the simulated bench with the
        saved changes bound).  Engines that can run their point routine headless override this; the default says it cannot."""
        import procmods_plan
        return procmods_plan.Plan(error='this procedure cannot show the commands of a single point before it is run')

    def pm_point_busy(self, pid) -> str:
        """Why point `pid` cannot be edited right now: it is the point the run is on ('' = it can).  A point is in progress from the moment the
        run reaches it (pm_step) until the run moves to the next one or stops: its commands are being sent and must not change."""
        st = self.pm_state
        if st is None or not self.pm_is_running():
            return ''
        cur = st.live.cursor
        if cur is not None and str(cur[2]) == str(pid):
            return (f'Point {pid} is being measured now: its commands are being sent and cannot change. '
                    'Open it again when the run has moved on to the next point (or stopped).')
        return ''

    def pm_point_has_reading(self, pid) -> bool:
        return str(pid) in self.pm_measured_ids()

    def pm_trees(self) -> list:
        """The point lists (Treeview widgets) of this window that get the right-click 'Edit' menu."""
        t = self.__dict__.get('tree')
        return [t] if t is not None else []

    def pm_bind_tree(self, tree, resolver=None):
        """Called by ui_shell.results_table (and by an engine whose lists are built another way): give the point list its right-click 'Edit'
        menu.  `resolver(iid)` names the point of a row (default: the row id is the point id).  Never breaks the window."""
        try:
            import procmods_point_ui
            procmods_point_ui.attach_tree_menu(self, tree, resolver)
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'the point list menu could not be attached ({type(exc).__name__})')

    # ---- live editing inside a running procedure (procmods_live) --------------------------------------------------------------
    # Engines call pm_step() once per point (new point only) and pm_live_attach(shell) once when the window is built.  They may override
    # pm_driver_classes / pm_refresh_view / pm_standby / pm_measured_ids / pm_point_title / pm_show_note / pm_asset_text.
    def pm_is_running(self) -> bool:
        return bool(getattr(self, 'busy', False))

    def pm_asset_text(self) -> str:
        for name in ('asset', 'instrument_id'):
            v = getattr(self, name, None)
            try:
                if v is not None:
                    return str(v.get()).strip()
            except Exception:
                pass
        st = self.pm_state
        return st.asset if st else ''

    def pm_author(self) -> str:
        """Who is making the edit: the operating-system user, plus the technician name the report dialog remembers (if any)."""
        who = procmods.default_author()
        try:
            import ui_theme
            tech = str(ui_theme.Settings('report_details').get('technician', '') or '').strip()
        except Exception:
            tech = ''
        return f'{who} (technician {tech})' if tech and tech.casefold() != who.casefold() else who

    def pm_driver_classes(self) -> tuple:
        """The driver classes whose command registry the editor lists (engines override)."""
        return ()

    def pm_point_title(self, p) -> str:
        return procmods_live.describe_point(p)

    def pm_refresh_view(self):
        fn = getattr(self, 'refresh', None)
        if callable(fn):
            fn()

    def _pm_view_changed(self):
        try:
            self.pm_refresh_view()
        except Exception:
            pass
        hook = self.__dict__.get('_pm_live_hook')
        if hook is not None:
            try:
                hook.refresh()
            except Exception:
                pass

    def pm_standby(self):
        """Put every output in standby, once (the engine's own call; never retried).  Raises if it fails."""
        io = getattr(self, 'io', None)
        if io is None or getattr(self, 'fast_demo', getattr(self, 'demo', False)):
            return
        for name in ('standby', 'all_off', 'all_outputs_off'):
            fn = getattr(io, name, None)
            if callable(fn):
                fn()
                return

    def pm_measured_ids(self) -> set:
        """ids of the points that have a reading in the data set being collected (As Found or As Left)."""
        res = getattr(self, 'results', None)
        try:
            return {str(k) for k, v in (res or {}).items() if v}
        except Exception:
            return set()

    def _pm_live_lookup(self, pid):
        st = self.pm_state
        if st is not None:
            for ent in st.lists.values():
                for q in ent[0]:
                    if procmods_live.point_id(q) == pid:
                        return q
        return None

    def pm_live_where(self) -> dict:
        """{'running', 'current': {'id', 'desc'} | None, 'next': {...} | None}: which point is in progress and which one a saved change reaches."""
        st = self.pm_state
        running = self.pm_is_running()
        out = {'running': running, 'current': None, 'next': None}
        if st is None or not running:
            return out
        live, run = st.live, st.live.run_points
        if run is None:
            out['generic'] = True                       # an engine without a point list (WaveSurfer): the next point of the running function
            return out
        i = live.index
        if 0 <= i < len(run):
            cur = run[i]
            out['current'] = {'id': procmods_live.point_id(cur), 'desc': self.pm_point_title(cur)}
        for q in run[i + 1:]:
            q = self._pm_live_lookup(procmods_live.point_id(q)) or q
            if not q.get('skip'):
                out['next'] = {'id': procmods_live.point_id(q), 'desc': self.pm_point_title(q)}
                break
        return out

    def pm_live_locked_keys(self) -> set:
        """Point keys that already have a reading, or are in progress: a live edit may not skip them and may change their tolerance only
        together with a redo."""
        st = self.pm_state
        if st is None:
            return set()
        pts = self.pm_context_points()
        measured = self.pm_measured_ids()
        cur = st.live.cursor[2] if (st.live.cursor and self.pm_is_running()) else None
        keys = procmods.point_keys(pts)
        return {k for p, k in zip(pts, keys) if str(procmods_live.point_id(p)) in measured or (cur is not None and procmods_live.point_id(p) == cur)}

    def pm_live_blocked(self) -> str:
        st = self.pm_state
        return st.live_blocked_reason() if st else 'procedure modifications are not available in this procedure'

    def pm_live_saved(self, texts=()):
        """The editor wrote edits (store or this run's entries).  Inside a run they wait for the next point boundary; between runs they take
        effect now."""
        st = self.pm_state
        if st is None:
            return
        st.live.mark_saved('; '.join(texts))
        if st.run_entries:
            st.run_asset = self.pm_asset_text() or st.run_asset
        if not self.pm_is_running():
            try:
                self._pm_commit(None)
            except procmods_live.LiveApplyError:
                pass                                         # stays pending; the message is in st.warnings and the next Run applies it

    def _pm_commit(self, before):
        """Apply the saved edits (called ONLY between two points / between runs).  Raises LiveApplyError when standby cannot be confirmed."""
        st = self.pm_state
        if st is None or not st.live.dirty:
            return None
        io = self.__dict__.get('io')
        log = getattr(io, 'log', None) if io is not None else None
        try:
            ev = st.commit_live(standby=None if getattr(self, 'fast_demo', getattr(self, 'demo', False)) else self.pm_standby, before=before, log=log,
                                asset=self.pm_asset_text() or None)
        except Exception as exc:
            msg = ('The saved edits were NOT applied because the outputs could not be confirmed in standby '
                   f'({type(exc).__name__}: {exc}). Check the instruments; the edits stay saved and apply at the next point / Run.')
            st.warnings.append(msg)
            raise procmods_live.LiveApplyError(msg) from exc
        self._pm_view_changed()
        return ev

    def pm_request_redo(self, keys):
        """Measure these points (factory point keys) again with the settings in effect at the next boundary."""
        st = self.pm_state
        if st is None:
            return
        pts = self.pm_context_points()
        byk = dict(zip(procmods.point_keys(pts), pts))
        ids = [procmods_live.point_id(byk[k]) for k in keys if k in byk]
        st.live.request_redo(ids)

    def pm_show_note(self, p):
        """The technician note of a point, shown once per run when the point is reached (informational; no safety prompt is touched)."""
        try:
            from tkinter import messagebox
            messagebox.showinfo(f'Note for point {procmods_live.point_id(p)}', str(p.get('tech_note')), parent=getattr(self, 'root', None))
        except Exception:
            pass

    def pm_step(self, points, i, previous):
        """Call at the top of every point of a run loop: `p, previous = self.pm_step(points, i, previous)`.

        Returns (p, previous): p is the LIVE point (patched copy) to run; None when a live edit now skips it (go on to i + 1).  Raises
        procmods_live.LiveApplyError when saved edits could not be applied safely (the engine reports it through its normal error path).
        Applies the edits saved since the last point, puts a requested redo in front of the queue (and clears `previous` so the setup prompt
        is shown again), shows a new technician note.  The point that is already in progress (re-entry of the same index) is returned as is."""
        st = self.pm_state
        p = points[i]
        if st is None:
            return p, previous
        live = st.live
        key = (id(points), i, procmods_live.point_id(p))
        if live.cursor == key:
            return p, previous                                    # same point again (a prompt stage): never changed in flight
        live.run_points, live.index, live.cursor = points, i, key
        if live.dirty:
            self._pm_commit({'id': procmods_live.point_id(p), 'desc': self.pm_point_title(p)})
        if live.redo:
            again, live.redo = list(live.redo), []
            redo = []
            for rid in again:
                q = self._pm_live_lookup(rid)
                if q is not None and rid != procmods_live.point_id(p) and not q.get('skip'):
                    redo.append(q)
            if redo:
                points[i:i] = redo
                p, previous = points[i], None
                live.cursor = (id(points), i, procmods_live.point_id(p))
                io = self.__dict__.get('io')
                log = getattr(io, 'log', None) if io is not None else None
                if log is not None:
                    try:
                        log.add('--', 'LIVE EDIT redo: point(s) ' + ', '.join(str(procmods_live.point_id(q)) for q in redo)
                                + ' measured again; the previous reading is replaced when the new one is recorded', 'procmods')
                    except Exception:
                        pass
        q = self._pm_live_lookup(procmods_live.point_id(p))
        if q is not None and q is not p:
            points[i] = p = q
        if p.get('skip'):
            return None, previous
        pid = procmods_live.point_id(p)
        if p.get('tech_note') and pid not in live.noted:
            live.noted.add(pid)
            self.pm_show_note(p)
        return p, previous

    def pm_live_boundary(self, before=None):
        """For an engine without a point list (the WaveSurfer): call between two points.  Applies the saved edits."""
        st = self.pm_state
        if st is not None and st.live.dirty:
            self._pm_commit(before)

    def pm_texts(self, points) -> dict:
        """Factory text items for the editor's Text tab: 'setup:<key>' (where the spec has a setup text) and 'note:<key>' (a technician note)."""
        out = {}
        for p, k in zip(points, procmods.point_keys(points)):
            if isinstance(p.get('setup'), str) and p['setup'].strip():
                out[f'setup:{k}'] = p['setup']
            out[f'note:{k}'] = ''
        return out

    def pm_supports_skip(self) -> bool:
        return True

    def pm_supports_redo(self) -> bool:
        return True

    def pm_context_points(self) -> list:
        """The FACTORY points the editor keys its overrides on (engines whose points are not in registered lists override)."""
        st = self.pm_state
        return st.factory_points() if st else []

    def pm_title(self) -> str:
        st = self.pm_state
        return f'{st.model} procedure' if st else 'procedure'

    def pm_live_context(self):
        """procmods_ui_model.Context for the editor window, built fresh each time it opens (current asset, connection and run state)."""
        import cmdreg
        import procmods_ui_model as M
        st = self.pm_state
        pts = [p if (p.get('description') or p.get('desc')) else dict(p, description=self.pm_point_title(p)) for p in self.pm_context_points()]
        regs = {}
        for cls in self.pm_driver_classes():
            try:
                regs[cls.__name__] = cmdreg.merge_commands(cls)
            except Exception:
                pass
        bridge = procmods_live.LiveBridge(where=self.pm_live_where, locked_keys=self.pm_live_locked_keys, blocked=self.pm_live_blocked,
                                          saved=self.pm_live_saved, redo=self.pm_request_redo, running=self.pm_is_running,
                                          supports_skip=self.pm_supports_skip(), supports_redo=self.pm_supports_redo(), pending=lambda: [x['text'] for x in st.live.pending])
        return M.Context(title=self.pm_title(), model=st.model, asset_id=self.pm_asset_text() or st.asset, demo=bool(getattr(self, 'demo', False)),
                         registries=regs, points=pts, defaults=defaults_for(st.engine), texts=self.pm_texts(pts), store=st._store(),
                         idn=lambda: st.idn, is_running=self.pm_is_running, author=self.pm_author(), run_entries=st.run_entries, live=bridge,
                         proc_key=st.proc_key)

    def pm_live_attach(self, shell=None):
        """Give this procedure window the 'Edit procedure' action (it stays usable during a run).  Never breaks the window."""
        try:
            import procmods_ui
            hook = procmods_ui.attach_live(self, shell if shell is not None else getattr(self, 'shell', None))
            self.__dict__['_pm_live_hook'] = hook
            return hook
        except Exception as exc:
            if self.pm_state is not None:
                self.pm_state.warnings.append(f'the in-run procedure editor could not be attached ({type(exc).__name__})')
            return None

    # ---- checkpoints and results -------------------------------------------------------------------------------------------
    def pm_checkpoint_fields(self) -> dict:
        """Merge into the progress file.  {} when the run is unmodified, so unmodified checkpoints are unchanged."""
        st = self.pm_state
        if st is None:
            return {}
        out = {}
        if (st.oset and st.snapshot) or (st.snapshot and st.live.events):      # live edits that removed the last override stay on record
            out['overrides'] = copy.deepcopy(st.snapshot)
        elif st.factory_only and st.suppressed:
            out['overrides'] = {'revs': [], 'hash': '', 'factory_run': True, 'suppressed': st.suppressed}
        if out and st.live.events:
            out['live_edits'] = copy.deepcopy(st.live.events)
        return out

    def pm_result_fields(self) -> dict:
        st = self.pm_state
        return {'ovrev': st.rev()} if st and st.oset and st.snapshot else {}

    def pm_on_checkpoint(self, data, choose=None):
        """A progress file was loaded.  If it carries an override snapshot that differs from the current store, `choose(diff)` returns
        'saved' (default: the run continues under the modifications it was started with) or 'current'.  Returns
        {'action': 'none'|'same'|'saved'|'current', 'diff': ...}."""
        st = self.pm_state
        snap = (data or {}).get('overrides') if isinstance(data, dict) else None
        if st is not None and isinstance(data, dict) and isinstance(data.get('live_edits'), list):
            st.live.events = [e for e in data['live_edits'] if isinstance(e, dict)]      # the audit trail of edits made during the run
        if st is None or not snap or not snap.get('revs'):
            return {'action': 'none', 'diff': None}
        if not procmods.verify_snapshot(snap):
            st.warnings.append('the saved modification record in this progress file does not verify; the current settings are used')
            return {'action': 'current', 'diff': None}
        diff = procmods.compare_with_current(snap, st.oset)
        if diff['same']:
            st.snapshot = snap
            return {'action': 'same', 'diff': diff}
        use = (choose(diff) if choose else 'saved') or 'saved'
        if use == 'saved':
            asset = str((data or {}).get('asset') or st.asset or '').strip()
            st.oset = procmods.restore_snapshot(snap, idn=st.idn, devmode=st.devmode, model=st.model, asset=asset)
            st.snapshot = snap
            st.pinned, st.pinned_asset = True, asset           # begin_run keeps this set until the asset changes or a factory run
            st._reapply_all()
            if st.insts:
                st._bind_commands()
        else:
            st.snapshot = procmods.build_snapshot(st.oset, snap)
        return {'action': use, 'diff': diff}

    def pm_record_run(self, run_id, demo=None):
        """Store the snapshot of an issued report in run_overrides (procmods.record_run_snapshot: demo and unmodified record nothing)."""
        st = self.pm_state
        if st is None or not st.oset:
            return False
        return procmods.record_run_snapshot(run_id, st.snapshot or st.oset, demo=st.demo if demo is None else demo, store=st._store())

    def pm_modified_count(self) -> int:
        st = self.pm_state
        return len(st.oset.active()) if st and st.oset else 0


# --------------------------------------------------------------------------------------------------------------------------------
# for the report
# --------------------------------------------------------------------------------------------------------------------------------
def _oset_of(run):
    if isinstance(run, procmods.OverrideSet):
        return run
    st = run if isinstance(run, ModsState) else getattr(run, 'pm_state', None)
    if isinstance(st, ModsState):
        return st.oset
    if isinstance(run, dict):
        snap = run.get('overrides', run) if 'revs' not in run else run
        if isinstance(snap, dict) and snap.get('revs') is not None:
            if snap['revs'] and not procmods.verify_snapshot(snap):
                raise ValueError('the modification record does not verify (hash mismatch)')
            return procmods.restore_snapshot(snap, verify=False)
    return None


def applied_modifications(run) -> list:
    """The modifications a run used, for the report's "Procedure modifications" block.  `run` is an engine App (or anything with
    pm_state), a ModsState, an OverrideSet, or a snapshot / progress-file dict (a report re-printed later uses the SNAPSHOT, not the
    store).  Returns [] for an unmodified run, else procmods.modifications_summary(): one dict per active modification with
    text, reason, author, date, unverified, affects_conditions, applies_to, kind, uid, limit, manufacturer_tolerance,
    tolerance_used, tolerances_modified, imported_by.  A tampered or stale override is NOT in the list (it was not applied)."""
    oset = _oset_of(run)
    return procmods.modifications_summary(oset) if oset else []


def applied_info(run) -> dict:
    """{'modifications': applied_modifications(run), 'hash', 'rev', 'tolerances_modified', 'factory_run', 'suppressed', 'tampered': [...],
    'warnings': [...], 'rejected': [...]; plus 'live_edits': [...] only if edits were made during the run} - what a report needs to say about the modifications and about overrides that were not applied."""
    st = run if isinstance(run, ModsState) else getattr(run, 'pm_state', None)
    oset = _oset_of(run)
    info = {'modifications': procmods.modifications_summary(oset) if oset else [], 'hash': oset.hash if oset else '', 'rev': 0,
            'tolerances_modified': bool(oset and procmods.tolerances_modified(oset)), 'factory_run': False, 'suppressed': 0,
            'tampered': [], 'warnings': [], 'rejected': []}
    if isinstance(st, ModsState):
        info.update(rev=st.rev(), factory_run=st.factory_only and bool(st.suppressed), suppressed=st.suppressed,
                    tampered=[(e['uid'], e['target']) for e in st.oset.tampered()], warnings=list(st.warnings), rejected=list(st.rejected))
        if st.live.events:                                  # only when edits were made during the run: otherwise the record is unchanged
            info['live_edits'] = copy.deepcopy(st.live.events)
    return info
