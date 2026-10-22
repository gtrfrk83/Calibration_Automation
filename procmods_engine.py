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

import copy
import threading

import procmods

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
    'mdo': 'MDO4000C',
    'ws': 'WS4104HD',
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
_t('fgen', 'settle.timebase', 2.0, 0.2, 120.0, 'Function generator: settle, time base')
_t('fgen', 'settle.acamp', 1.0, 0.2, 120.0, 'Function generator: settle, AC amplitude')
_t('fgen', 'settle.lfflat', 1.0, 0.2, 120.0, 'Function generator: settle, low-frequency flatness')
_t('fgen', 'settle.flat', 1.5, 0.2, 120.0, 'Function generator: settle, flatness')
_t('fgen', 'settle.other', 1.0, 0.2, 120.0, 'Function generator: settle, other points')
_t('fgen', 'counter_gate', 1.0, 0.1, 10.0, 'Function generator: frequency counter gate time')
_t('handheld', 'settle.default', 3.0, 0.5, 120.0, 'Handheld DMM: settle after the output is on (points without their own value)')
_t('handheld', 'ramp_delay', 5.0, 5.0, 60.0, 'Handheld DMM: delay between high-voltage ramp steps (the manual says 5 s: can only be lengthened)')
_t('handheld', 'ir_timeout', 45.0, 5.0, 300.0, 'Handheld DMM: infrared reading timeout (points without their own value)', conditions=False)
_t('mdo', 'pause_scale', 1.0, 0.25, 10.0, "MDO4000C: multiplier on the procedure's settle and sweep waits (not on waits inside the driver)", unit='x')
_t('mdo', 'reconnect_attempts', 36, 1, 120, 'MDO4000C: attempts to reconnect after the power cycle', unit='', ptype='int', conditions=False)
_t('mdo', 'reconnect_wait', 5.0, 1.0, 60.0, 'MDO4000C: wait between reconnect attempts', conditions=False)
_t('mdo', 'delta_wait', 8.0, 1.0, 120.0, 'MDO4000C: wait for the channel-to-channel delay statistics')
_t('mdo', 'digital_settle', 3.0, 0.5, 30.0, 'MDO4000C: settle before a digital-channel state read')
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

TUNABLES: dict = {}          # full name -> dict(engine, key, default, lo, hi, label, unit, type, affects_conditions)


def _register():
    for engine, key, default, lo, hi, label, unit, ptype, cond in _T:
        name = f'{engine}.{key}'
        TUNABLES[name] = dict(engine=engine, key=key, name=name, default=default, lo=lo, hi=hi, label=label, unit=unit, type=ptype,
                              affects_conditions=cond)
        procmods.register_param(name, ptype, lo, hi, affects_conditions=cond, label=label, unit=unit)
    for name, field, label, lo, hi in PER_POINT:
        procmods.register_param(name, 'float', lo, hi, affects_conditions=True, per_point=True, point_field=field, label=label, unit='s')


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

    def __init__(self, engine, model, *, demo=False, store=None, devmode=None, shape=None, on_change=None):
        self.engine, self.model, self.demo = engine, model, bool(demo)
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
                self.asset = str(asset or '').strip()
            if idn:
                self.idn = idn
            if factory_only is not None:
                self.factory_only = bool(factory_only)
            self.warnings = []
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
            idn = getattr(self.insts[0], 'idn', '') if self.insts else ''
            if idn and idn != self.idn:
                self.load(idn=idn)                                       # re-resolve with fw_match evaluated (also rebinds)
            else:
                self._bind_commands()

    def bind_one(self, inst):
        """Bind the command overrides to one driver that was opened after the run started (the WaveSurfer creates a fresh pair of
        drivers for every point).  Does not register the driver and does not touch the point lists."""
        with self._lock:
            self._bind_commands([inst], reset=False)

    def _bind_commands(self, insts=None, reset=True):
        if reset:
            self.rejected = []
        for inst in (self.insts if insts is None else insts):
            try:
                has = bool(self.oset.entries())                           # candidates, even if none is active before the idn is known
                oset = self.oset.with_idn(getattr(inst, 'idn', '') or None) if has else self.oset
                names = [c.__name__ for c in type(inst).__mro__]
                templates = oset.commands_for(inst) if has else {}
                uids = {}
                for e in (oset.active('command') if has else []):
                    name, _, key = e['target'].partition(':')
                    if name in names and templates.get(key) == e['value'].get('template'):
                        uids[key] = e['uid']
                for uid, probs in (oset.rejected_commands(inst) if has else []):
                    self.rejected.append((type(inst).__name__, '', uid, list(probs)))
                    self.warnings.append(f'command override {uid} not applied: ' + '; '.join(map(str, probs)))
                for key, uid, probs in inst.use_commands(templates, uids):
                    self.rejected.append((type(inst).__name__, key, uid, list(probs)))
            except Exception as exc:                                     # never stop a run over an override
                self.warnings.append(f'could not bind command overrides to {type(inst).__name__} ({type(exc).__name__})')

    # ---- points ------------------------------------------------------------------------------------------------------------
    def _active_edits(self):
        return any(e['kind'] in _EDIT_KINDS or (e['kind'] == 'param' and '@' in e['target']) for e in self.oset.active())

    def patch(self, views):
        """(patched copies of `views`, set of indices whose limits were overridden).  procmods.apply_points guards the limit fields."""
        out = procmods.apply_points(views, self.oset)
        return out, {i for i, q in enumerate(out) if q.get('limit_modified')}

    def register(self, points, on_change=None):
        self.lists.setdefault(id(points), [points, list(points), set(), on_change])
        return points

    def apply(self, points):
        """Put the active overrides on this live list IN PLACE (entries are replaced by patched copies; originals are kept for revert)."""
        with self._lock:
            ent = self.lists.setdefault(id(points), [points, list(points), set(), None])
            self._revert_entry(ent)
            orig = ent[1] = list(points)
            if not (self.oset and self._active_edits()):
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
            self._changed(ent)
            return points

    def revert(self, points):
        with self._lock:
            ent = self.lists.get(id(points))
            if ent:
                self._revert_entry(ent)

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
            patched['error'] = (max(abs(patched['high'] - patched['nominal']), abs(patched['nominal'] - patched['low']))
                                if limited else orig['error'])
        return patched

    # ---- the record --------------------------------------------------------------------------------------------------------
    def begin_run(self, asset=None, factory_only=False, run_entries=None):
        with self._lock:
            self.load(asset=asset, factory_only=factory_only, run_entries=run_entries)
            self.snapshot = procmods.build_snapshot(self.oset, self.snapshot) if self.oset else self.snapshot
            return self.oset

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


# --------------------------------------------------------------------------------------------------------------------------------
# the mixin
# --------------------------------------------------------------------------------------------------------------------------------
class ProcModsMixin:
    """See the module docstring.  All names start with pm_ so nothing clashes with an engine's own."""

    # ---- state -------------------------------------------------------------------------------------------------------------
    @property
    def pm_state(self):
        return self.__dict__.get('_pm_state')

    def pm_init(self, engine, model, *, demo=False, lists=(), on_change=None, store=None, devmode=None, shape=None, load=True):
        """App side.  `lists`: the live point lists to patch in place (a module's POINTS, a handheld self.points).  shape='band' for an
        engine that judges low <= reading <= high.  `on_change()` is called after a list was patched (rebuild id lookups)."""
        st = ModsState(engine, model, demo=demo, store=store, devmode=devmode, shape=shape, on_change=on_change)
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
        st.begin_run(asset=asset, factory_only=factory_only, run_entries=run_entries)
        io = self.__dict__.get('io')
        if io is not None and getattr(io, 'pm_state', None) is not st and hasattr(io, 'pm_attach'):
            io.pm_attach(st, *getattr(io, 'pm_drivers', lambda: ())())
        if io is not None:
            st.banner(getattr(io, 'log', None))
        if points is None:
            return None
        live = {}
        for ent in st.lists.values():
            for p in ent[0]:
                live[p.get('id')] = p
        mapped = [live.get(p.get('id'), p) for p in points]
        return [p for p in mapped if not p.get('skip')] or None

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

    # ---- checkpoints and results -------------------------------------------------------------------------------------------
    def pm_checkpoint_fields(self) -> dict:
        """Merge into the progress file.  {} when the run is unmodified, so unmodified checkpoints are unchanged."""
        st = self.pm_state
        if st is None:
            return {}
        if st.oset and st.snapshot:
            return {'overrides': copy.deepcopy(st.snapshot)}
        if st.factory_only and st.suppressed:
            return {'overrides': {'revs': [], 'hash': '', 'factory_run': True, 'suppressed': st.suppressed}}
        return {}

    def pm_result_fields(self) -> dict:
        st = self.pm_state
        return {'ovrev': st.rev()} if st and st.oset and st.snapshot else {}

    def pm_on_checkpoint(self, data, choose=None):
        """A progress file was loaded.  If it carries an override snapshot that differs from the current store, `choose(diff)` returns
        'saved' (default: the run continues under the modifications it was started with) or 'current'.  Returns
        {'action': 'none'|'same'|'saved'|'current', 'diff': ...}."""
        st = self.pm_state
        snap = (data or {}).get('overrides') if isinstance(data, dict) else None
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
    'warnings': [...], 'rejected': [...]} - what a report needs to say about the modifications and about overrides that were not applied."""
    st = run if isinstance(run, ModsState) else getattr(run, 'pm_state', None)
    oset = _oset_of(run)
    info = {'modifications': procmods.modifications_summary(oset) if oset else [], 'hash': oset.hash if oset else '', 'rev': 0,
            'tolerances_modified': bool(oset and procmods.tolerances_modified(oset)), 'factory_run': False, 'suppressed': 0,
            'tampered': [], 'warnings': [], 'rejected': []}
    if isinstance(st, ModsState):
        info.update(rev=st.rev(), factory_run=st.factory_only and bool(st.suppressed), suppressed=st.suppressed,
                    tampered=[(e['uid'], e['target']) for e in st.oset.tampered()], warnings=list(st.warnings), rejected=list(st.rejected))
    return info
