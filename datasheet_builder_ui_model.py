"""Datasheet Builder, stage B: the UI-free controller (no tkinter, no instrument I/O).  datasheet_builder_ui.py builds thin Tk widgets on top of it.

    lst = DatasheetList(Storage())                      # the list tab: rows, search, New / Open / Duplicate / Delete / Restore / Export / Import / versions
    ed  = EditorModel(Storage())                        # a new datasheet (or EditorModel.open(storage, uid, version=None))
    ed.set_header(make='Keysight', model='34461A', title='34461A Performance Verification')
    ed.add_function('DCV'); ed.add_range(fid, '10 V', '10 uV'); ed.add_spec_entry(fid, {'1y': '0.004 % of reading + 0.0035 % of range'})
    ed.example(fid, '0.004 % of reading + 0.0035 % of range', range_id='r10')['text']     # 'At 5 V on the 10 V range the limit is ±...'
    ed.add_rule(fid, {'type': 'percent_of_range', 'percents': '10, 50, 100', 'bipolar': True})
    ed.point_rows(fid); ed.run_match(); ed.review(); ed.save()

The guided flow (STEPS): Header -> Functions -> Ranges -> Specification -> Test points -> Automation -> Review & Save.  Every change goes through one
gate (`_do`) which keeps an undo snapshot, never lets a core error escape (the caller gets an `Outcome` with a plain-language message) and puts the
datasheet back as it was when the change fails half way.  All problems come from datasheet_builder.validate (error / warn + where); nothing is
corrected on the person's behalf.  Numbers are SI Decimals inside the datasheet; this module only formats them for display (datasheet_builder.format_si,
the same display-only scaling the Tk side uses).  Nothing here touches calibration_procedures.sqlite3: storage is datasheet_builder.save/load
(user_specs/ files + the lab_registry.sqlite3 tables).
"""
from __future__ import annotations

import copy
import getpass
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import datasheet_builder as db

D = Decimal

# ------------------------------------------------------------------------------------------------------------------------------ the flow
STEPS = (
    dict(key='header', title='Header', help='Say which instrument this datasheet is for and how long the specification is valid. These words appear on '
         'the procedure list and the report.'),
    dict(key='functions', title='Functions', help='Add what the instrument measures or outputs: DC volts, AC volts, resistance, a scope gain test, a '
         'generator amplitude test ... Each function gets its own ranges, specification and test points.'),
    dict(key='ranges', title='Ranges', help='For each function, list the ranges the instrument has: the full scale, and how fine the display reads '
         '(the resolution). The resolution is what "counts" in a specification means.'),
    dict(key='spec', title='Specification', help='Type the manufacturer\'s accuracy statement for each range (and each frequency band for AC). '
         'The example under the box shows the limit it gives at a real reading, so you can check it against the manual.'),
    dict(key='points', title='Test points', help='Choose how the test points are worked out (percent of range, zero and full scale, typed values, steps, '
         'frequencies). The table shows every point with its low and high limit. You can add, edit, switch off or override any point.'),
    dict(key='automation', title='Automation', help='The suite looks through your imported standards and picks one for each point. You see how good the '
         'match is (TAR / TUR), which points no standard covers, and whether the suite has a driver to run it by itself. You can pick another standard per point.'),
    dict(key='review', title='Review & Save', help='Check the summary and every problem. Saving creates a new version and adds the datasheet to the '
         'Procedures list with the "user-built" tag. Older versions are kept.'),
)
STEP_KEYS = tuple(s['key'] for s in STEPS)
S_HEADER, S_FUNCTIONS, S_RANGES, S_SPEC, S_POINTS, S_AUTOMATION, S_REVIEW = range(7)

KIND_GROUPS = (('dmm', 'Multimeter / handheld / calibrator'), ('scope', 'Oscilloscope'), ('generator', 'Signal / function generator'))
SETTING_FIELDS = {
    'TEMP': [('tc_type', 'Thermocouple type', ['K', 'J', 'T', 'E', 'N', 'R', 'S', 'B'], 'K')],
    'GEN_AMPL': [('waveform', 'Waveform', ['SIN', 'SQU', 'DC'], 'SIN'), ('load', 'Load', ['INF', '50'], 'INF'), ('amp_unit', 'Amplitude is in', ['Vrms', 'Vpp', 'Vp'], 'Vrms')],
    'GEN_FLAT': [('waveform', 'Waveform', ['SIN', 'SQU'], 'SIN'), ('amp_unit', 'Amplitude is in', ['Vrms', 'Vpp', 'Vp'], 'Vrms')],
}
PREFIX_CHOICES = (('', 'automatic'), ('p', 'p'), ('n', 'n'), ('µ', 'µ'), ('m', 'm'), ('base', 'none (V, A, Ω ...)'), ('k', 'k'), ('M', 'M'), ('G', 'G'))

# the rule picker: key, label, plain language, db rule type
RULE_TYPES = (
    dict(key='percent_of_range', label='Percent of range', help='Points at given percentages of each range\'s full scale, e.g. 10, 50, 100 %. Optionally also zero and the negative side.'),
    dict(key='zero_and_full', label='Zero and full scale', help='Zero, +full scale and (if bipolar) -full scale of each range.'),
    dict(key='fixed', label='Typed points', help='Values you type, e.g. 1 mV, 5 V, 100 kΩ. Each goes on the smallest range that holds it.'),
    dict(key='linear', label='Linear steps', help='Equal steps between a start and a stop value (give the number of points or the step).'),
    dict(key='log', label='Logarithmic steps', help='Steps that are evenly spread on a log scale (give the number of points or points per decade).'),
    dict(key='decade_125', label='1-2-5 sequence', help='1, 2, 5, 10, 20, 50 ... between a start and a stop value.'),
    dict(key='frequency_sweep', label='One level, many frequencies', help='A single nominal level (often 0 dB or a fixed level) repeated at each frequency, for bandwidth and flatness tests.'),
)
FREQ_CHOICES = (('none', 'No frequency'), ('list', 'Frequency list'), ('bands', 'At the specification band edges / middle'), ('linear', 'Linear steps'), ('log', 'Logarithmic steps'))

# live-help templates: (key, button text, template, plain-language explanation).  {u} = the function's unit symbol.
EXPR_HELPERS = (
    ('pct_reading', '% of reading', '0.01 % of reading', 'A part of the value being measured (the manual often prints this as %iV, "% of input value" or "% rdg").'),
    ('pct_range', '% of range', '0.005 % of range', 'A part of the full scale of the range, the same at every reading.'),
    ('counts', 'counts', '2 counts', 'Counts of the last digit; one count is the resolution you entered for the range.'),
    ('floor', 'floor', 'max(0.01 % of reading, 50 µ{u})', 'The larger of a percentage and a fixed amount, so very small readings never get a tighter limit than the floor.'),
    ('offset', 'offset', '10 µ{u}', 'A fixed amount in the function\'s unit, the same at every reading.'),
    ('ppm', 'ppm', '20 ppm of reading', 'Parts per million of the reading (or write "of range").'),
    ('sum', '+ (add a term)', ' + ', 'Accuracy statements add up: type the next term after the plus sign.'),
)
EXPR_ERROR_HELP = {
    'empty': 'Type the accuracy statement, for example 0.05 % of reading + 0.01 % of range.',
    'syntax': 'This part cannot be read. Each term looks like "0.05 % of reading", "0.01 % of range", "2 counts", "20 ppm of reading" or "10 µV".',
    'ambiguous_basis': 'Say what the percentage is of: write "of reading" or "of range" after it.',
    'ambiguous_unit': 'A fixed amount needs its unit, for example 0.5 mV.',
    'unit': 'The unit does not match this function.',
    'bad_term': 'This term is not understood.',
    'bad_value': 'A tolerance cannot be negative.',
}

# the codes of validate() that belong to a flow step (when `where` does not already say)
_CODE_STEP = {}
for _c in ('no_make', 'no_model', 'no_title', 'no_periods', 'dup_period', 'bad_period', 'default_period', 'limit_rounding'):
    _CODE_STEP[_c] = S_HEADER
for _c in ('no_functions', 'bad_kind', 'bad_direction', 'dup_function'):
    _CODE_STEP[_c] = S_FUNCTIONS
for _c in ('no_ranges', 'dup_range', 'range_value', 'range_order', 'range_resolution'):
    _CODE_STEP[_c] = S_RANGES
for _c in ('no_spec', 'spec_range_unknown', 'spec_band_inverted', 'spec_missing_period', 'spec_period_unknown', 'expr_context', 'one_sided_needs_bound', 'spec_border'):
    _CODE_STEP[_c] = S_SPEC
for _c in ('no_points', 'dup_point_id', 'dup_point', 'point_range_unknown', 'point_outside_range', 'no_frequency', 'no_amplitude', 'expr_eval', 'limit_inverted',
           'nominal_outside_limit', 'limit_zero_width', 'limit_value', 'override_inverted', 'override_period'):
    _CODE_STEP[_c] = S_POINTS
for _c in ('assignment_unknown_point',):
    _CODE_STEP[_c] = S_AUTOMATION
for _c in ('write', 'registry'):
    _CODE_STEP[_c] = S_REVIEW


# ------------------------------------------------------------------------------------------------------------------------------ small helpers
@dataclass
class Outcome:
    """What every action returns: ok, a plain-language message for the status line, and optional detail (a list of lines / a value)."""
    ok: bool
    message: str = ''
    detail: object = None

    def __bool__(self):
        return self.ok


def split_list(text):
    """'10, 50; 100' / lines -> ['10', '50', '100'] (empty pieces dropped)."""
    return [p.strip() for p in re.split(r'[,;\n]+', text or '') if p.strip()]


def plain_error(exc):
    """A message for any core error (DsError / ExprError / ValueError ...), with the hint for an expression error."""
    code = getattr(exc, 'code', '')
    base = str(exc)
    hint = EXPR_ERROR_HELP.get(code, '')
    if hint and hint not in base:
        return f'{base} {hint}'.strip()
    return base


def show(value, unit, prefix=None, decimals=None):
    """Display text of an SI value ('5 V', '100 mV', '20 kΩ'); '' for None.  Display only."""
    if value is None:
        return ''
    try:
        return db.format_si(value, unit, prefix=prefix, decimals=decimals)
    except (db.DsError, KeyError, TypeError, ValueError):
        return str(value)


def shared_prefix(values, unit, forced=''):
    """One SI prefix for a row of related values (so nominal / low / high read alike): `forced` if given, else the prefix of the largest magnitude."""
    if forced == 'base':
        return ''
    if forced:
        return forced
    nums = [abs(db.dec(v)) for v in values if v is not None]
    return db.best_prefix(max(nums), unit)[0] if nums else ''


def _prefix_value(p):
    return '' if p == 'base' else p


def resolution_from_decimals(prefix, decimals):
    """Resolution (SI) of a display that shows `decimals` places after the point when the value is shown in the prefix (e.g. 'm', 4 -> 0.1 mV = 1e-7)."""
    n = int(decimals)
    if n < 0 or n > 15:
        raise db.DsError('number', 'the number of decimals must be 0 to 15')
    return db.D(10) ** (dict(db._PREFIX_ORDER)[prefix or ''] - n)


class Storage:
    """The few storage calls the UI needs, with the folders (and the person's name) held in one place; tests give throw-away folders.
    Nothing here raises: failures come back as None / False / a result with problems (the core functions already behave that way)."""

    def __init__(self, root=None, db_path=None, who=None):
        self.root, self.db_path = root, db_path
        if who is None:
            try:
                who = getpass.getuser()
            except Exception:
                who = ''
        self.who = who

    def kw(self):
        return dict(root=self.root, db=self.db_path)

    def list(self, include_deleted=False):
        return db.list_datasheets(include_deleted=include_deleted, **self.kw())

    def load(self, uid, version=None):
        return db.load(uid, version, **self.kw())

    def versions(self, uid):
        return db.versions(uid, **self.kw())

    def save(self, ds, note=''):
        return db.save(ds, who=self.who, note=note, **self.kw())

    def duplicate(self, uid, title=None):
        return db.duplicate(uid, title=title, who=self.who, **self.kw())

    def delete(self, uid):
        return db.delete(uid, who=self.who, **self.kw())

    def restore(self, uid):
        return db.restore(uid, **self.kw())

    def export_json(self, uid, path, version=None):
        return db.export_json(uid, path, version, **self.kw())

    def import_json(self, path):
        return db.import_json(path, who=self.who, **self.kw())

    def entries(self):
        return db.procedure_entries(**self.kw())


def _read_engine(spec_file):
    """dsb.engine of a runnable spec file ({} when unreadable)."""
    try:
        data = json.loads(Path(spec_file).read_text(encoding='utf-8'))
        return dict(data['dsb']['engine'])
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# ------------------------------------------------------------------------------------------------------------------------------ the list tab
class DatasheetList:
    """Rows for the Datasheet Builder tab and the actions on them.  `refresh()` re-reads the registry (or the files when the registry is damaged)."""

    def __init__(self, storage=None, matcher_factory=None):
        self.storage = storage or Storage()
        self.matcher_factory = matcher_factory
        self.search = ''
        self.show_deleted = False
        self.selected = ''
        self._raw = []
        self._cache = {}

    # ---- rows
    def refresh(self):
        self._raw = self.storage.list(include_deleted=self.show_deleted)
        return self.rows()

    def _functions_text(self, uid, version):
        key = (uid, version)
        if key not in self._cache:
            ds = self.storage.load(uid, version)
            self._cache[key] = (', '.join(f.name for f in ds.functions), len(ds.functions)) if ds else ('(cannot be read)', 0)
        return self._cache[key]

    @staticmethod
    def automation_text(row):
        """What the suite can do with the saved datasheet today, from the runnable spec's engine summary."""
        if row.get('deleted'):
            return 'Deleted (can be restored)'
        if not row.get('runnable_version'):
            return 'Draft: has problems, not runnable yet'
        eng = _read_engine(row.get('spec_file', ''))
        if not eng:
            return 'Ready'
        n, run, hand = eng.get('points', 0), eng.get('runnable', 0), eng.get('hand_set', 0)
        if not n:
            return 'Ready (no points)'
        if hand == 0:
            return f'Ready: all {n} points run by the suite'
        return f'Ready: {run} of {n} points run by the suite, {hand} set by hand'

    def rows(self):
        q = self.search.strip().lower()
        out = []
        for r in self._raw:
            funcs, nfun = self._functions_text(r['uid'], r['version'])
            text = ' '.join(str(r.get(k, '')) for k in ('make', 'model', 'title', 'uid')).lower() + ' ' + funcs.lower()
            if q and q not in text:
                continue
            out.append(dict(uid=r['uid'], make=r['make'], model=r['model'], title=r['title'], version=r['version'], functions=funcs, function_count=nfun,
                            points=r['points'], automation=self.automation_text(r), saved=r.get('updated_at', ''), status=r['status'],
                            deleted=bool(r['deleted']), tag=r.get('tag', db.TAG)))
        return out

    def row(self, uid):
        return next((r for r in self.rows() if r['uid'] == uid), None)

    def empty_text(self):
        if self._raw and self.search.strip():
            return 'No datasheet matches the search.'
        return 'No datasheets yet.\nPress "New" to build one, or "Import JSON..." to bring one in.'

    # ---- actions
    def new(self):
        return EditorModel(self.storage, matcher_factory=self.matcher_factory)

    def open(self, uid, version=None):
        """An EditorModel for the datasheet (latest or the given version), or None with `self.last_error` set."""
        ed = EditorModel.open(self.storage, uid, version, matcher_factory=self.matcher_factory)
        self.last_error = '' if ed else f'Could not read datasheet {uid}' + (f' version {version}' if version else '') + '.'
        return ed

    last_error = ''

    def duplicate(self, uid, title=None):
        res = self.storage.duplicate(uid, title=title)
        if res is None or not res.ok:
            return Outcome(False, 'Could not duplicate: the source datasheet cannot be read or the copy could not be written.')
        self.refresh()
        return Outcome(True, f'Duplicated as "{res.uid}" (version {res.version}).', res.uid)

    def delete(self, uid):
        """SOFT delete: it leaves the Procedures list, every version stays on disk, and Restore brings it back."""
        if not self.storage.delete(uid):
            return Outcome(False, 'Could not delete that datasheet.')
        self.refresh()
        return Outcome(True, f'Deleted "{uid}". It can be restored (tick "Show deleted").')

    def restore(self, uid):
        if not self.storage.restore(uid):
            return Outcome(False, 'Could not restore that datasheet.')
        self.refresh()
        return Outcome(True, f'Restored "{uid}".')

    def export_json(self, uid, path, version=None):
        if not path:
            return Outcome(False, 'No file chosen.')
        if not self.storage.export_json(uid, path, version):
            return Outcome(False, 'Could not export: the datasheet cannot be read or the file cannot be written.')
        return Outcome(True, f'Exported {uid}' + (f' version {version}' if version else '') + f' to {path}.')

    def import_json(self, path):
        """Always a NEW datasheet (an existing one is never overwritten)."""
        if not path:
            return Outcome(False, 'No file chosen.')
        res = self.storage.import_json(path)
        if not res.ok:
            msgs = [str(p) for p in res.problems] or ['The file could not be imported.']
            return Outcome(False, 'Not imported: ' + msgs[0], msgs)
        self.refresh()
        return Outcome(True, f'Imported as "{res.uid}" (version {res.version}).', res.uid)

    def version_rows(self, uid):
        """[{version, saved_at, who, note, status, points, status_text}] newest first, for the history window."""
        out = []
        for v in self.storage.versions(uid):
            out.append(dict(v, status_text={'ready': 'runnable', 'draft': 'draft (had problems)'}.get(v.get('status'), v.get('status') or '')))
        return out


# ------------------------------------------------------------------------------------------------------------------------------ the editor
class EditorModel:
    """The state and the actions of one datasheet being built.  See the module docstring."""

    UNDO_LIMIT = 200

    def __init__(self, storage=None, ds=None, matcher_factory=None, based_on=None):
        self.storage = storage or Storage()
        self.ds = ds if ds is not None else db.Datasheet()
        self.matcher_factory = matcher_factory
        self.based_on = based_on or (f'{ds.uid} v{ds.version}' if ds is not None and ds.uid else '')
        self.step = 0
        self.fid = self.ds.functions[0].id if self.ds.functions else ''
        self.period = self.ds.default_period
        self.reached = {0}
        self._undo, self._redo = [], []
        self._rev = 0
        self._problems = (-1, [])
        self._matcher = None
        self.match_result = None
        self.match_period = ''
        self.match_rev = -1
        self.match_error = ''
        self._saved_json = self.ds.to_json() if ds is not None else self._blank_json()
        self.last_save = None

    def _blank_json(self):
        return db.Datasheet().to_json()

    @classmethod
    def open(cls, storage, uid, version=None, matcher_factory=None):
        ds = storage.load(uid, version)
        if ds is None:
            return None
        ed = cls(storage, ds, matcher_factory=matcher_factory)
        ed.based_on = f'{uid} v{ds.version}'
        return ed

    # ---- the one gate for changes
    def _snapshot(self):
        return self.ds.to_json()

    def _restore(self, text):
        self.ds = db.Datasheet.from_json(text)
        if self.ds.function(self.fid) is None:
            self.fid = self.ds.functions[0].id if self.ds.functions else ''
        if self.period not in self.ds.period_ids():
            self.period = self.ds.default_period

    def _do(self, label, action, ok_message=''):
        """Run `action()` (which changes self.ds).  On a core error the datasheet is put back and the message is returned; otherwise the change
        is one undo step.  `action` may return a string (the success message) or an Outcome."""
        before = self._snapshot()
        try:
            res = action()
        except (db.DsError, ArithmeticError, ValueError, KeyError, TypeError) as exc:
            self._restore(before)
            return Outcome(False, plain_error(exc))
        if isinstance(res, Outcome):
            if not res.ok:
                self._restore(before)
                return res
            msg, detail = res.message or ok_message, res.detail
        else:
            msg, detail = res or ok_message, None
        if self._snapshot() == before:
            return Outcome(True, msg or 'Nothing changed.', detail)
        self._undo.append((label, before))
        del self._undo[:-self.UNDO_LIMIT]
        self._redo.clear()
        self._bump()
        return Outcome(True, msg or label, detail)

    def _bump(self):
        self._rev += 1

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    @property
    def undo_label(self):
        return self._undo[-1][0] if self._undo else ''

    def undo(self):
        if not self._undo:
            return Outcome(False, 'Nothing to undo.')
        label, snap = self._undo.pop()
        self._redo.append((label, self._snapshot()))
        self._restore(snap)
        self._bump()
        return Outcome(True, f'Undid: {label}.')

    def redo(self):
        if not self._redo:
            return Outcome(False, 'Nothing to redo.')
        label, snap = self._redo.pop()
        self._undo.append((label, self._snapshot()))
        self._restore(snap)
        self._bump()
        return Outcome(True, f'Redid: {label}.')

    @property
    def dirty(self):
        return self._snapshot() != self._saved_json

    @property
    def title(self):
        ds = self.ds
        head = ' '.join(x for x in (ds.make, ds.model) if x)
        if head and ds.title:
            return f'{head} - {ds.title}'
        return head or ds.title or 'New datasheet'

    # ---- navigation
    def fn(self, fid=None):
        return self.ds.function(fid or self.fid)

    def select_function(self, fid):
        if self.ds.function(fid):
            self.fid = fid
            return True
        return False

    def can_enter(self, step):
        """(ok, why_not) for moving to a step: later steps need what they work on.  Going back is always allowed."""
        if not 0 <= step < len(STEPS):
            return False, 'No such step.'
        if step <= S_FUNCTIONS or step == S_REVIEW:
            return True, ''
        if not self.ds.functions:
            return False, 'Add at least one function first (step 2).'
        if step == S_RANGES:
            return True, ''
        if not any(f.ranges for f in self.ds.functions):
            return False, 'Add at least one range to a function first (step 3).'
        if step in (S_SPEC, S_POINTS):
            return True, ''
        if not any(f.points for f in self.ds.functions):
            return False, 'Create at least one test point first (step 5).'
        return True, ''

    def go(self, step):
        ok, why = self.can_enter(step)
        if not ok:
            return Outcome(False, why)
        self.step = step
        self.reached.add(step)
        return Outcome(True, STEPS[step]['help'])

    def next(self):
        return self.go(min(self.step + 1, len(STEPS) - 1))

    def back(self):
        return self.go(max(self.step - 1, 0))

    def step_states(self):
        """One dict per step for the step bar: state 'current' | 'error' | 'warn' | 'done' | 'todo', counts, enterable, why_not."""
        probs = self.problems()
        out = []
        for i, st in enumerate(STEPS):
            mine = [p for p in probs if p['step'] == i]
            errs = sum(p['level'] == 'error' for p in mine)
            warns = len(mine) - errs
            ok, why = self.can_enter(i)
            if self._complete(i) and not errs:
                state = 'done' if not warns else 'warn'
            elif errs and i in self.reached:
                state = 'error'
            elif warns and i in self.reached:
                state = 'warn'
            else:
                state = 'todo'
            if i == self.step:
                state = 'current'
            out.append(dict(index=i, key=st['key'], title=st['title'], state=state, errors=errs, warnings=warns, enterable=ok, why_not=why))
        return out

    def _complete(self, i):
        ds = self.ds
        if i == S_HEADER:
            return bool(ds.make.strip() and ds.model.strip() and ds.periods)
        if i == S_FUNCTIONS:
            return bool(ds.functions)
        if i == S_RANGES:
            return bool(ds.functions) and all(f.ranges for f in ds.functions)
        if i == S_SPEC:
            return bool(ds.functions) and all(f.spec or f.info.get('passfail') for f in ds.functions)
        if i == S_POINTS:
            return bool(ds.functions) and all(f.points for f in ds.functions)
        if i == S_AUTOMATION:
            return self.match_fresh()
        return bool(ds.uid) and not self.dirty

    # ---- problems (datasheet_builder.validate, located)
    def locate(self, where, code=''):
        """Where a problem is, in the person's words: dict(step, function_id, range_id, point_id, spec_index, text)."""
        ds = self.ds
        loc = dict(step=_CODE_STEP.get(code, S_POINTS if code.startswith('rule') else S_REVIEW), function_id='', range_id='', point_id='', spec_index=None, text='')
        w = where or ''
        parts = w.split('/') if w else []
        fn = None
        if w == 'datasheet' or not w:
            loc.update(step=_CODE_STEP.get(code, S_HEADER))
            loc['text'] = STEPS[loc['step']]['title']
            return loc
        if parts and ds.function(parts[0]):
            fn = ds.function(parts[0])
        elif '/' not in w:
            for f, p in ds.all_points():                          # a bare point id
                if p.id == w:
                    fn = f
                    parts = [f.id, p.range_id, p.id]
                    break
        if fn is None:
            loc['text'] = w
            return loc
        loc['function_id'] = fn.id
        text = [fn.name]
        if len(parts) == 1:
            loc['step'] = _CODE_STEP.get(code, S_POINTS if code.startswith('rule') else S_FUNCTIONS)
        elif parts[1].startswith('spec') and parts[1][4:].isdigit():
            idx = int(parts[1][4:])
            loc.update(step=S_SPEC, spec_index=idx - 1)
            text.append(f'specification line {idx}')
        elif parts[1] == 'rule':
            loc['step'] = S_POINTS
            text.append(f'rule {parts[2] if len(parts) > 2 else ""}'.strip())
        else:
            loc['range_id'] = parts[1]
            rng = fn.range(parts[1])
            if rng is not None:
                text.append(f'{self.range_text(fn, rng)} range')
            if len(parts) > 2:
                loc.update(step=S_POINTS, point_id=parts[2])
                p = fn.point(parts[2])
                text.append('point ' + (self.point_text(fn, p) if p else parts[2]))
            else:
                loc['step'] = _CODE_STEP.get(code, S_RANGES)
        loc['text'] = ', '.join(t for t in text if t)
        return loc

    def problems(self):
        """validate(ds) shaped for the UI: [dict(level, code, message, where, step, function_id, range_id, point_id, spec_index, location)].  Cached per change."""
        if self._problems[0] == self._rev:
            return self._problems[1]
        out = []
        try:
            found = db.validate(self.ds)
        except Exception as exc:                       # validate is pure and should not raise; never let the window die on it
            found = [db.DsProblem('validate', f'The check itself failed ({type(exc).__name__}: {exc}).')]
        for p in found:
            loc = self.locate(getattr(p, 'where', ''), p.code)
            out.append(dict(level=getattr(p, 'level', 'error'), code=p.code, message=str(p), where=getattr(p, 'where', ''), step=loc['step'],
                            function_id=loc['function_id'], range_id=loc['range_id'], point_id=loc['point_id'], spec_index=loc['spec_index'],
                            location=loc['text']))
        out.sort(key=lambda d: (d['level'] != 'error', d['step']))
        self._problems = (self._rev, out)
        return out

    def problems_for(self, step=None, function_id=None):
        """Problems of a flow step and / or a function (the inline messages)."""
        return [p for p in self.problems() if (step is None or p['step'] == step) and (function_id is None or not p['function_id'] or p['function_id'] == function_id)]

    def problem_counts(self):
        ps = self.problems()
        e = sum(p['level'] == 'error' for p in ps)
        return dict(errors=e, warnings=len(ps) - e)

    def goto_problem(self, problem):
        """Move to the step / function / point a problem is about.  Returns the target dict."""
        if problem.get('function_id'):
            self.select_function(problem['function_id'])
        self.go(problem['step'])
        return dict(step=self.step, function_id=problem.get('function_id', ''), range_id=problem.get('range_id', ''), point_id=problem.get('point_id', ''),
                    spec_index=problem.get('spec_index'))

    # ------------------------------------------------------------------------------------------------------------------ 1. header
    def set_header(self, make=None, model=None, title=None, notes=None, revision=None):
        def act():
            for k, v in (('make', make), ('model', model), ('title', title), ('notes', notes), ('revision', revision)):
                if v is not None:
                    setattr(self.ds, k, v.strip() if k in ('make', 'model', 'title', 'revision') else v)
        return self._do('edit header', act, 'Header updated.')

    def period_rows(self):
        return [dict(id=p.id, label=p.label or p.id, default=p.id == self.ds.default_period) for p in self.ds.periods]

    def period_presets(self):
        return [dict(id=i, label=l, used=i in self.ds.period_ids()) for i, l in db.PERIOD_PRESETS]

    def add_period(self, pid, label=''):
        pid = (pid or '').strip()

        def act():
            if not re.match(r'^[A-Za-z0-9_]+$', pid):
                raise db.DsError('bad_period', 'A period id may only contain letters, digits and _ (for example 90d, 1y).')
            if pid in self.ds.period_ids():
                raise db.DsError('dup_period', f'The period {pid} is already there.')
            self.ds.periods.append(db.Period(pid, label.strip() or dict(db.PERIOD_PRESETS).get(pid, pid)))
            if not self.ds.default_period:
                self.ds.default_period = pid
            n = sum(len(f.spec) for f in self.ds.functions)
            return 'Period added.' + (f' Your {n} specification line(s) have no text for it yet: fill it in at step 4.' if n else '')
        return self._do('add period', act)

    def remove_period(self, pid):
        def act():
            if pid not in self.ds.period_ids():
                raise db.DsError('period', f'No period {pid}.')
            if len(self.ds.periods) == 1:
                raise db.DsError('no_periods', 'A datasheet needs at least one period.')
            self.ds.periods = [p for p in self.ds.periods if p.id != pid]
            if self.ds.default_period == pid:
                self.ds.default_period = self.ds.periods[0].id
            if self.period == pid:
                self.period = self.ds.default_period
            for fn in self.ds.functions:                               # the removed period's texts and typed limits go with it
                for e in fn.spec:
                    e.exprs.pop(pid, None), e.exprs_minus.pop(pid, None), e.printed.pop(pid, None)
                for p in fn.points:
                    p.overrides.pop(pid, None)
            return f'Period {pid} removed together with its specification text.'
        return self._do('remove period', act)

    def set_default_period(self, pid):
        def act():
            if pid not in self.ds.period_ids():
                raise db.DsError('default_period', f'No period {pid}.')
            self.ds.default_period = pid
            self.period = pid
        return self._do('default period', act, f'{pid} is now the default period.')

    def set_period_label(self, pid, label):
        def act():
            p = next((p for p in self.ds.periods if p.id == pid), None)
            if p is None:
                raise db.DsError('period', f'No period {pid}.')
            p.label = label.strip()
        return self._do('rename period', act, 'Period renamed.')

    def set_limit_rounding(self, outward):
        def act():
            self.ds.options['limit_rounding'] = 'outward' if outward else 'exact'
        return self._do('limit rounding', act, 'Limits are rounded outward to the display resolution.' if outward else 'Limits are exact.')

    # ------------------------------------------------------------------------------------------------------------------ 2. functions
    def kind_choices(self):
        """[dict(kind, name, unit, symbol, group, group_label, direction, ac)] grouped for the picker."""
        out = []
        for gkey, glabel in KIND_GROUPS:
            for kind, info in db.KINDS.items():
                if info['family'] == gkey:
                    out.append(dict(kind=kind, name=info['name'], unit=info['unit'], symbol=db.unit_symbol(info['unit']), group=gkey, group_label=glabel,
                                    direction=info['direction'], ac=bool(info.get('ac')), label=f"{info['name']} ({db.unit_symbol(info['unit'])})" if info['unit'] else info['name']))
        return out

    def add_function(self, kind, name='', direction=None):
        box = {}

        def act():
            fn = self.ds.add_function(kind, name.strip(), direction=direction or None)
            for key, _label, _choices, default in SETTING_FIELDS.get(kind, []):
                fn.settings[key] = default
            fn.switch = fn.info.get('switch', '')
            box['id'] = fn.id
            return f'Added {fn.name}. Next, give it ranges (step 3).'
        res = self._do('add function', act)
        if res.ok and box.get('id'):
            self.fid = box['id']
            res.detail = box['id']
        return res

    def remove_function(self, fid):
        def act():
            fn = self.ds.function(fid)
            if fn is None:
                raise db.DsError('no_function', f'No function {fid}.')
            n = len(fn.points)
            self.ds.functions.remove(fn)
            self.ds.assignments = {k: v for k, v in self.ds.assignments.items() if not any(p.id == k for p in fn.points)}
            if self.fid == fid:
                self.fid = self.ds.functions[0].id if self.ds.functions else ''
            return f'Removed {fn.name} with its {len(fn.ranges)} range(s) and {n} point(s). Undo brings it back.'
        return self._do('remove function', act)

    def move_function(self, fid, delta):
        def act():
            fs = self.ds.functions
            i = next((k for k, f in enumerate(fs) if f.id == fid), None)
            if i is None:
                raise db.DsError('no_function', f'No function {fid}.')
            j = i + (1 if delta > 0 else -1)
            if 0 <= j < len(fs):
                fs[i], fs[j] = fs[j], fs[i]
        return self._do('move function', act, 'Function moved.')

    def set_function(self, fid, name=None, direction=None, switch=None, display_unit=None, notes=None, settle=None, optional=None):
        def act():
            fn = self._need(fid)
            if name is not None:
                fn.name = name.strip() or fn.info['name']
            if direction is not None:
                if direction not in db.DIRECTIONS:
                    raise db.DsError('bad_direction', 'The direction must be measure or source.')
                fn.direction = direction
            if switch is not None:
                fn.switch = switch
            if display_unit is not None:
                fn.display_unit = _prefix_value(display_unit)
            if notes is not None:
                fn.notes = notes
            if settle is not None:
                fn.settle = None if str(settle).strip() == '' else float(settle)
            if optional is not None:
                fn.optional = bool(optional)
        return self._do('edit function', act, 'Function updated.')

    def set_function_setting(self, fid, key, value):
        def act():
            fn = self._need(fid)
            if value in (None, ''):
                fn.settings.pop(key, None)
            else:
                fn.settings[key] = value
        return self._do('function setting', act, 'Setting updated.')

    def setting_fields(self, fid):
        fn = self._need(fid)
        return [dict(key=k, label=lab, choices=list(ch), value=fn.settings.get(k, default)) for k, lab, ch, default in SETTING_FIELDS.get(fn.kind, [])]

    def direction_choices(self, fid):
        """(value, label) the person may pick: generators are always 'source', scopes always 'measure', multimeters either (a calibrator can be the UUT)."""
        fn = self._need(fid)
        meas = ('measure', 'The instrument MEASURES what a standard supplies (typical meter / scope)')
        src = ('source', 'The instrument OUTPUTS and a standard measures it (generator, or a calibrator as the UUT)')
        fam = fn.info['family']
        return [src] if fam == 'generator' else [meas] if fam == 'scope' else [meas, src]

    def function_rows(self):
        return [dict(id=f.id, kind=f.kind, name=f.name, unit=db.unit_symbol(f.unit), direction=f.direction, ranges=len(f.ranges), spec=len(f.spec),
                     points=len(f.points), problems=sum(1 for p in self.problems() if p['function_id'] == f.id and p['level'] == 'error'),
                     family=f.info['family'], ac=bool(f.info.get('ac'))) for f in self.ds.functions]

    def _need(self, fid):
        fn = self.ds.function(fid or self.fid)
        if fn is None:
            raise db.DsError('no_function', 'Choose or add a function first.')
        return fn

    # ------------------------------------------------------------------------------------------------------------------ 3. ranges
    def range_text(self, fn, rng):
        """'10 V' / '100 mV' (the label as printed on the instrument when there is one)."""
        if rng.label:
            return rng.label
        return show(rng.full_scale, fn.unit, prefix=_prefix_value(rng.display_unit or fn.display_unit) if (rng.display_unit or fn.display_unit) else None)

    def range_rows(self, fid=None):
        fn = self.fn(fid)
        if fn is None:
            return []
        rows = []
        for r in fn.ranges:
            pre = _prefix_value(r.display_unit or fn.display_unit) if (r.display_unit or fn.display_unit) else None
            rows.append(dict(id=r.id, text=self.range_text(fn, r), full_scale=show(r.full_scale, fn.unit, pre), resolution=show(r.resolution, fn.unit) if r.resolution is not None else '',
                             max_input=show(r.max_input, fn.unit) if r.max_input is not None else '', unipolar=r.unipolar, display_unit=r.display_unit or 'auto',
                             points=sum(1 for p in fn.points if p.range_id == r.id), spec=sum(1 for e in fn.spec if e.range_id == r.id),
                             decimals=self._decimals(r)))
        return rows

    @staticmethod
    def _decimals(r):
        if r.resolution is None:
            return ''
        return str(max(0, -r.resolution.normalize().as_tuple().exponent))

    def parse_amount(self, text, fid=None):
        """A typed amount ('10 V', '100 mV', '5k', '2.5') in the function's unit -> Decimal SI; DsError with the reason otherwise."""
        fn = self._need(fid)
        return db.parse_quantity(text, fn.unit or None)

    def resolution_from_decimals(self, prefix, decimals):
        """Helper for 'the display shows N decimals when the range is shown in <prefix><unit>': the resolution in SI."""
        return resolution_from_decimals(_prefix_value(prefix), decimals)

    def add_range(self, fid, full_scale, resolution='', label='', display_unit='', max_input='', unipolar=False):
        def act():
            fn = self._need(fid)
            fs = db.parse_quantity(full_scale, fn.unit or None)
            res = db.parse_quantity(resolution, fn.unit or None) if str(resolution).strip() else None
            mx = db.parse_quantity(max_input, fn.unit or None) if str(max_input).strip() else None
            rng = fn.add_range(fs, res, label=label.strip(), display_unit=_prefix_value(display_unit), max_input=mx, unipolar=bool(unipolar))
            return f'Added the {self.range_text(fn, rng)} range.'
        return self._do('add range', act)

    def add_ranges(self, fid, text):
        """Several full scales at once ('100 mV, 1 V, 10 V'); resolutions can be set afterwards.  All or none."""
        def act():
            fn = self._need(fid)
            items = split_list(text)
            if not items:
                raise db.DsError('number', 'Type the full scales, separated by commas, for example 100 mV, 1 V, 10 V.')
            for t in items:
                fn.add_range(db.parse_quantity(t, fn.unit or None))
            return f'Added {len(items)} range(s). Set each range\'s resolution so "counts" work.'
        return self._do('add ranges', act)

    def edit_range(self, fid, rid, full_scale=None, resolution=None, label=None, display_unit=None, max_input=None, unipolar=None):
        """Change a range.  Its id stays (points and specification lines refer to it), so a changed full scale keeps the old id."""
        def act():
            fn = self._need(fid)
            r = fn.range(rid)
            if r is None:
                raise db.DsError('range', f'No range {rid}.')
            if full_scale is not None:
                r.full_scale = db.parse_quantity(full_scale, fn.unit or None)
            if resolution is not None:
                r.resolution = db.parse_quantity(resolution, fn.unit or None) if str(resolution).strip() else None
            if max_input is not None:
                r.max_input = db.parse_quantity(max_input, fn.unit or None) if str(max_input).strip() else None
            if label is not None:
                r.label = label.strip()
            if display_unit is not None:
                r.display_unit = _prefix_value(display_unit)
            if unipolar is not None:
                r.unipolar = bool(unipolar)
            fn.ranges.sort(key=lambda x: x.full_scale)
        return self._do('edit range', act, 'Range updated.')

    def range_usage(self, fid, rid):
        fn = self._need(fid)
        return dict(points=sum(1 for p in fn.points if p.range_id == rid), spec=sum(1 for e in fn.spec if e.range_id == rid))

    def remove_range(self, fid, rid, cascade=False):
        def act():
            fn = self._need(fid)
            r = fn.range(rid)
            if r is None:
                raise db.DsError('range', f'No range {rid}.')
            use = self.range_usage(fid, rid)
            if (use['points'] or use['spec']) and not cascade:
                raise db.DsError('range_in_use', f'The range is used by {use["points"]} point(s) and {use["spec"]} specification line(s). Remove it together with them?')
            gone = {p.id for p in fn.points if p.range_id == rid}
            fn.points = [p for p in fn.points if p.range_id != rid]
            fn.spec = [e for e in fn.spec if e.range_id != rid]
            for rule in fn.rules:
                if rule.range_ids and rid in rule.range_ids:
                    rule.range_ids = [x for x in rule.range_ids if x != rid] or None
            self.ds.assignments = {k: v for k, v in self.ds.assignments.items() if k not in gone}
            fn.ranges.remove(r)
            return f'Removed the range and {use["points"]} point(s), {use["spec"]} specification line(s).'
        return self._do('remove range', act)

    # ------------------------------------------------------------------------------------------------------------------ 4. specification
    def helpers(self, fid=None):
        fn = self.fn(fid)
        u = db.unit_symbol(fn.unit) if fn else 'V'
        return [dict(key=k, label=lab, template=tpl.replace('{u}', u), help=h) for k, lab, tpl, h in EXPR_HELPERS]

    def insert_helper(self, text, key, fid=None):
        """New expression text with the helper's term added (joined with ' + ' after existing text).  Unknown key: text unchanged."""
        tpl = next((h['template'] for h in self.helpers(fid) if h['key'] == key), None)
        if tpl is None:
            return text
        text = (text or '').rstrip()
        if key == 'sum':
            return text + ' ' if text.endswith('+') else text + ' + ' if text else text
        return tpl if not text else (text + ' ' + tpl.strip() if text.endswith('+') else f'{text} + {tpl}')

    def spec_scope_text(self, fn, e):
        sc = f'{self.range_text(fn, fn.range(e.range_id))} range' if e.range_id and fn.range(e.range_id) else ('All ranges' if e.range_id is None else f'range {e.range_id} (missing)')
        if e.f_lo is not None or e.f_hi is not None:
            lo = show(e.f_lo, 'Hz') if e.f_lo is not None else 'DC'
            hi = show(e.f_hi, 'Hz') if e.f_hi is not None else 'and up'
            sc += f', {lo} to {hi}'
        return sc

    def spec_rows(self, fid=None):
        fn = self.fn(fid)
        if fn is None:
            return []
        rows = []
        for i, e in enumerate(fn.spec):
            texts = {p: (e.printed.get(p) or (e.exprs[p].printed or e.exprs[p].text(fn.unit) if p in e.exprs else '')) for p in self.ds.period_ids()}
            rows.append(dict(index=i, scope=self.spec_scope_text(fn, e), range_id=e.range_id, f_lo=db.fmt(e.f_lo) if e.f_lo is not None else '',
                             f_hi=db.fmt(e.f_hi) if e.f_hi is not None else '', texts=texts, mode=e.mode, bound=db.fmt(e.bound) if e.bound is not None else '',
                             minus={p: v.printed or v.text(fn.unit) for p, v in e.exprs_minus.items()}, normalised={p: v.text(fn.unit) for p, v in e.exprs.items()}))
        return rows

    def uncovered_ranges(self, fid=None):
        """Ranges for which no specification line applies at all (the message under the specification table)."""
        fn = self.fn(fid)
        if fn is None or fn.info.get('passfail'):
            return []
        return [self.range_text(fn, r) for r in fn.ranges if not any(e.range_id in (None, r.id) for e in fn.spec)]

    def _entry(self, fn, texts, range_id, f_lo, f_hi, mode, bound, minus_texts, default_basis):
        """Build a SpecEntry from form values; ExprError / DsError (with the reason) when something cannot be read."""
        pids = self.ds.period_ids()
        if isinstance(texts, str):
            texts = {p: texts for p in pids}
        exprs, printed = {}, {}
        for p in pids:
            t = (texts or {}).get(p, '')
            if not str(t).strip():
                raise db.DsError('spec_missing_period', f'Type the specification for the period "{p}" too (the same text is fine if it does not change).')
            exprs[p] = db.parse_expr(t, fn.unit, default_basis)
            printed[p] = t.strip()
        minus = {}
        for p, t in (minus_texts or {}).items():
            if str(t).strip() and p in pids:
                minus[p] = db.parse_expr(t, fn.unit, default_basis)
        rid = range_id or None
        if rid is not None and fn.range(rid) is None:
            raise db.DsError('spec_range_unknown', f'No range {rid}.')
        lo = db.parse_quantity(f_lo, 'Hz') if str(f_lo or '').strip() else None
        hi = db.parse_quantity(f_hi, 'Hz') if str(f_hi or '').strip() else None
        bd = db.parse_quantity(bound, fn.unit or None) if str(bound or '').strip() else None
        return db.SpecEntry(exprs, rid, lo, hi, minus, printed, mode, bd)

    def add_spec_entry(self, fid, texts, range_id=None, f_lo='', f_hi='', mode='both', bound='', minus_texts=None, default_basis=None):
        def act():
            fn = self._need(fid)
            fn.spec.append(self._entry(fn, texts, range_id, f_lo, f_hi, mode, bound, minus_texts, default_basis))
            return 'Specification line added.'
        return self._do('add specification', act)

    def edit_spec_entry(self, fid, index, texts, range_id=None, f_lo='', f_hi='', mode='both', bound='', minus_texts=None, default_basis=None):
        def act():
            fn = self._need(fid)
            if not 0 <= index < len(fn.spec):
                raise db.DsError('spec', 'No such specification line.')
            fn.spec[index] = self._entry(fn, texts, range_id, f_lo, f_hi, mode, bound, minus_texts, default_basis)
            return 'Specification line updated.'
        return self._do('edit specification', act)

    def remove_spec_entry(self, fid, index):
        def act():
            fn = self._need(fid)
            if not 0 <= index < len(fn.spec):
                raise db.DsError('spec', 'No such specification line.')
            del fn.spec[index]
            return 'Specification line removed.'
        return self._do('remove specification', act)

    def copy_spec_to_ranges(self, fid, index, range_ids):
        """Copy one specification line to other ranges (the same wording for several ranges is common)."""
        def act():
            fn = self._need(fid)
            e = fn.spec[index]
            n = 0
            for rid in range_ids:
                if fn.range(rid) is None or rid == e.range_id:
                    continue
                c = db.SpecEntry.from_dict(copy.deepcopy(e.to_dict()))
                c.range_id = rid
                fn.spec.append(c)
                n += 1
            return f'Copied to {n} range(s).'
        return self._do('copy specification', act)

    def example_reading(self, fid, range_id=None):
        """The reading used for the worked example: half the range's full scale (so 5 V on the 10 V range)."""
        fn = self._need(fid)
        rng = fn.range(range_id) if range_id else (fn.ranges[len(fn.ranges) // 2] if fn.ranges else None)
        if rng is None:
            return None, None
        return rng.full_scale / 2, rng

    def example_frequency(self, fid, f_lo='', f_hi=''):
        fn = self._need(fid)
        if not (fn.info.get('ac') or fn.info['family'] == 'generator' or fn.info.get('value')):
            return None
        try:
            lo = db.parse_quantity(f_lo, 'Hz') if str(f_lo or '').strip() else None
            hi = db.parse_quantity(f_hi, 'Hz') if str(f_hi or '').strip() else None
        except db.DsError:
            lo = hi = None
        if lo is not None and hi is not None:
            return (lo + hi) / 2
        return lo if lo is not None else hi if hi is not None else (db.D(1000) if fn.info.get('ac') else None)

    def example(self, fid, text, range_id=None, reading='', frequency='', f_lo='', f_hi='', default_basis=None, minus_text=''):
        """Live worked example for the expression being typed.  Returns dict(ok, text, error, normalised, low, high, plus, minus, parts[]).
        'At 5 V on the 10 V range the limit is ±3.5 mV (4.9965 V to 5.0035 V)'.  Never raises."""
        res = dict(ok=False, text='', error='', normalised='', low=None, high=None, plus=None, minus=None, parts=[])
        try:
            fn = self._need(fid)
            expr = db.parse_expr(text, fn.unit, default_basis)
        except (db.DsError, ValueError) as exc:
            res['error'] = plain_error(exc)
            res['text'] = res['error']
            return res
        res['normalised'] = expr.text(fn.unit)
        try:
            rd, rng = self.example_reading(fid, range_id)
            if str(reading).strip():
                rd = db.parse_quantity(reading, fn.unit or None)
            f = db.parse_quantity(frequency, 'Hz') if str(frequency).strip() else self.example_frequency(fid, f_lo, f_hi)
            if rd is None:
                res['text'] = f'{res["normalised"]} is readable. Add a range to see a worked example.'
                res['ok'] = True
                return res
            ctx = db.Ctx(rd, rng.full_scale if rng else None, rng.resolution if rng else None, f)
            tol = expr.evaluate(ctx)
            if str(minus_text).strip():
                mt = db.parse_expr(minus_text, fn.unit, default_basis).evaluate(ctx)
                tol = db.Tol(mt.minus, tol.plus)
        except (db.DsError, ValueError, ArithmeticError) as exc:
            res.update(error=plain_error(exc), text=plain_error(exc))
            return res
        pre = shared_prefix([rd, rd - tol.minus, rd + tol.plus], fn.unit, _prefix_value(rng.display_unit or fn.display_unit) if rng and (rng.display_unit or fn.display_unit) else '')
        low, high = rd - tol.minus, rd + tol.plus
        rname = f'{self.range_text(fn, rng)} range' if rng else 'range'
        at = f'At {show(rd, fn.unit, pre)}' + (f' and {show(f, "Hz")}' if f is not None else '') + (f' on the {rname}' if rng else '')
        if tol.symmetric:
            lim = f'±{show(tol.plus, fn.unit, shared_prefix([tol.plus], fn.unit))}'
        else:
            lim = f'-{show(tol.minus, fn.unit, shared_prefix([tol.minus], fn.unit))} / +{show(tol.plus, fn.unit, shared_prefix([tol.plus], fn.unit))}'
        res['text'] = f'{at} the limit is {lim} ({show(low, fn.unit, pre)} to {show(high, fn.unit, pre)}).'
        parts = []
        for t in expr.terms():
            tv = t.evaluate(ctx)
            parts.append(f'{t.text(fn.unit)} = {show(tv.plus, fn.unit)}')
        res.update(ok=True, low=low, high=high, plus=tol.plus, minus=tol.minus, parts=parts)
        return res

    def example_for_entry(self, fid, index, period=None):
        """The worked example of a saved specification line (for the table)."""
        fn = self._need(fid)
        e = fn.spec[index]
        period = period or self.period
        text = e.printed.get(period) or (e.exprs[period].printed if period in e.exprs else '')
        if not text and period in e.exprs:
            text = e.exprs[period].text(fn.unit)
        return self.example(fid, text, e.range_id, f_lo=db.fmt(e.f_lo) if e.f_lo is not None else '', f_hi=db.fmt(e.f_hi) if e.f_hi is not None else '')

    # ------------------------------------------------------------------------------------------------------------------ 5. test points
    def rule_catalog(self, fid=None):
        """The rule picker: the rule types and the frequency choices that make sense for the function."""
        fn = self.fn(fid)
        needs_f = bool(fn and fn.info.get('ac'))
        freq = [c for c in FREQ_CHOICES if not (needs_f and c[0] == 'none')]
        return dict(rules=list(RULE_TYPES), freq=freq, needs_frequency=needs_f, uses_amplitude=bool(fn and fn.info.get('amplitude')),
                    ranges=[(r.id, self.range_text(fn, r)) for r in fn.ranges] if fn else [])

    def build_rule(self, fn, form, rule_id=None):
        """PointRule from the picker's form dict.  Keys: type, percents ('10, 50, 100'), bipolar, zero, values ('1 mV, 5 V'), start, stop, count, step,
        per_decade, nominal, freq_mode, freq_values, freq_start, freq_stop, freq_count, freq_per_decade, freq_at, range_ids, amplitude."""
        t = form.get('type', '')
        if t not in db.RULE_TYPES:
            raise db.DsError('rule_type', 'Choose a rule type.')
        params = {}
        unit = fn.unit or None
        if t == 'percent_of_range':
            vals = split_list(form.get('percents', ''))
            if not vals:
                raise db.DsError('rule_params', 'Type the percentages, for example 10, 50, 100.')
            params = {'percents': [db.fmt(db.dec(v.replace('%', ''), 'percent')) for v in vals], 'bipolar': bool(form.get('bipolar')), 'zero': bool(form.get('zero'))}
        elif t == 'zero_and_full':
            params = {'bipolar': bool(form.get('bipolar', True))}
        elif t == 'fixed':
            vals = split_list(form.get('values', ''))
            if not vals:
                raise db.DsError('rule_params', 'Type the points, for example 1 mV, 5 V.')
            for v in vals:
                db.parse_quantity(v, unit)
            params = {'values': vals}
        elif t in ('linear', 'log', 'decade_125'):
            params = {'start': self._q_text(form.get('start'), unit, 'start'), 'stop': self._q_text(form.get('stop'), unit, 'stop')}
            if t == 'linear':
                if str(form.get('count', '')).strip():
                    params['count'] = int(form['count'])
                elif str(form.get('step', '')).strip():
                    params['step'] = db.fmt(db.parse_quantity(self._q_text(form['step'], unit, 'step'), unit))      # the core takes the step as a plain SI number
                else:
                    raise db.DsError('rule_params', 'Give the number of points or the step size.')
            elif t == 'log':
                if str(form.get('count', '')).strip():
                    params['count'] = int(form['count'])
                elif str(form.get('per_decade', '')).strip():
                    params['per_decade'] = int(form['per_decade'])
                else:
                    raise db.DsError('rule_params', 'Give the number of points or the points per decade.')
        elif t == 'frequency_sweep':
            params = {'nominal': self._q_text(form.get('nominal', '0') or '0', unit, 'level')}
        freqs = self.build_frequencies(form)
        amp = str(form.get('amplitude') or '').strip() or None
        if amp:
            db.parse_quantity(amp, None)
        rids = form.get('range_ids') or None
        if rids:
            rids = list(rids)
        if rule_id is None:
            n, base = 1, t
            while any(r.id == f'{base}{n}' for r in fn.rules):
                n += 1
            rule_id = f'{base}{n}'
        return db.PointRule(rule_id, t, params, freqs, rids, amp, dict(form.get('settings') or {}))

    @staticmethod
    def _q_text(text, unit, what):
        t = str(text or '').strip()
        if not t:
            raise db.DsError('rule_params', f'Type the {what} value.')
        db.parse_quantity(t, unit)
        return t

    def build_frequencies(self, form):
        mode = form.get('freq_mode', 'none') or 'none'
        if mode == 'none':
            return None
        if mode == 'list':
            vals = split_list(form.get('freq_values', ''))
            if not vals:
                raise db.DsError('rule_params', 'Type the frequencies, for example 100 Hz, 1 kHz, 20 kHz.')
            for v in vals:
                db.parse_quantity(v, 'Hz')
            return {'mode': 'list', 'values': vals}
        if mode == 'bands':
            return {'mode': 'bands', 'at': form.get('freq_at', 'edges') or 'edges'}
        out = {'mode': mode, 'start': self._q_text(form.get('freq_start'), 'Hz', 'start frequency'), 'stop': self._q_text(form.get('freq_stop'), 'Hz', 'stop frequency')}
        if str(form.get('freq_count', '')).strip():
            out['count'] = int(form['freq_count'])
        elif mode == 'log' and str(form.get('freq_per_decade', '')).strip():
            out['per_decade'] = int(form['freq_per_decade'])
        else:
            raise db.DsError('rule_params', 'Give the number of frequencies' + (' or the points per decade.' if mode == 'log' else '.'))
        return out

    def rule_rows(self, fid=None):
        fn = self.fn(fid)
        rows = []
        for r in (fn.rules if fn else []):
            rows.append(dict(id=r.id, type=r.type, label=next((x['label'] for x in RULE_TYPES if x['key'] == r.type), r.type), enabled=r.enabled, text=self.rule_text(fn, r),
                             points=sum(1 for p in fn.points if p.origin == 'rule:' + r.id)))
        return rows

    def rule_text(self, fn, r):
        p = r.params
        if r.type == 'percent_of_range':
            t = ', '.join(p.get('percents', [])) + ' % of range' + (' (+/-)' if p.get('bipolar') else '') + (' plus zero' if p.get('zero') else '')
        elif r.type == 'zero_and_full':
            t = '0, +full scale' + (', -full scale' if p.get('bipolar', True) else '')
        elif r.type == 'fixed':
            t = ', '.join(p.get('values', []))
        elif r.type == 'frequency_sweep':
            t = f'level {p.get("nominal", "0")}'
        else:
            t = f'{p.get("start")} to {p.get("stop")}' + (f', {p["count"]} points' if 'count' in p else f', step {show(p["step"], fn.unit)}' if 'step' in p else f', {p["per_decade"]} per decade' if 'per_decade' in p else '')
        f = r.frequencies
        if f and f.get('mode', 'none') != 'none':
            m = f['mode']
            t += ' at ' + (', '.join(f.get('values', [])) if m == 'list' else f'the band {f.get("at", "edges")}' if m == 'bands' else f'{f.get("start")} to {f.get("stop")} ({m})')
        if r.range_ids:
            t += ' on ' + ', '.join(self.range_text(fn, fn.range(x)) if fn.range(x) else x for x in r.range_ids)
        if r.amplitude:
            t += f', stimulus {r.amplitude}'
        return t

    def _regen_message(self, rep):
        bits = []
        if rep.added:
            bits.append(f'{len(rep.added)} point(s) added')
        if rep.removed:
            bits.append(f'{len(rep.removed)} removed')
        if rep.orphaned:
            bits.append(f'{len(rep.orphaned)} edited point(s) kept as your own')
        if rep.skipped:
            bits.append(f'{len(rep.skipped)} value(s) skipped because no range holds them (' + ', '.join(t for t, _ in rep.skipped[:4]) + (' ...' if len(rep.skipped) > 4 else '') + ')')
        return ', '.join(bits) if bits else 'No point changed.'

    def add_rule(self, fid, form, rule_id=None):
        def act():
            fn = self._need(fid)
            fn.add_rule(self.build_rule(fn, form, rule_id))
            rep = db.regenerate(fn)
            return Outcome(True, 'Rule added: ' + self._regen_message(rep), rep)
        return self._do('add rule', act)

    def update_rule(self, fid, rule_id, form):
        def act():
            fn = self._need(fid)
            i = next((k for k, r in enumerate(fn.rules) if r.id == rule_id), None)
            if i is None:
                raise db.DsError('rule', f'No rule {rule_id}.')
            old = fn.rules[i]
            new = self.build_rule(fn, form, rule_id)
            new.enabled = old.enabled
            fn.rules[i] = new
            rep = db.regenerate(fn)
            return Outcome(True, 'Rule changed: ' + self._regen_message(rep), rep)
        return self._do('edit rule', act)

    def rule_form(self, fid, rule_id):
        """The picker's form dict that would rebuild the rule (to edit it)."""
        fn = self._need(fid)
        r = next((x for x in fn.rules if x.id == rule_id), None)
        if r is None:
            return {}
        p, f = r.params, r.frequencies or {}
        form = dict(type=r.type, percents=', '.join(p.get('percents', [])), bipolar=bool(p.get('bipolar')), zero=bool(p.get('zero')),
                    values=', '.join(p.get('values', [])), start=p.get('start', ''), stop=p.get('stop', ''), count=str(p.get('count', '')), step=p.get('step', ''),
                    per_decade=str(p.get('per_decade', '')), nominal=p.get('nominal', '0'), freq_mode=f.get('mode', 'none'), freq_values=', '.join(f.get('values', [])),
                    freq_start=f.get('start', ''), freq_stop=f.get('stop', ''), freq_count=str(f.get('count', '')), freq_per_decade=str(f.get('per_decade', '')),
                    freq_at=f.get('at', 'edges'), range_ids=list(r.range_ids or []), amplitude=r.amplitude or '', settings=dict(r.settings))
        return form

    def remove_rule(self, fid, rule_id):
        def act():
            fn = self._need(fid)
            n = len(fn.rules)
            fn.rules = [r for r in fn.rules if r.id != rule_id]
            if len(fn.rules) == n:
                raise db.DsError('rule', f'No rule {rule_id}.')
            rep = db.regenerate(fn)
            return Outcome(True, 'Rule removed: ' + self._regen_message(rep), rep)
        return self._do('remove rule', act)

    def set_rule_enabled(self, fid, rule_id, enabled):
        def act():
            fn = self._need(fid)
            r = next((x for x in fn.rules if x.id == rule_id), None)
            if r is None:
                raise db.DsError('rule', f'No rule {rule_id}.')
            r.enabled = bool(enabled)
            rep = db.regenerate(fn)
            return Outcome(True, ('Rule switched on: ' if enabled else 'Rule switched off: ') + self._regen_message(rep), rep)
        return self._do('switch rule', act)

    def recalculate(self, fid=None):
        """Re-apply the rules (after ranges or rules changed).  Edited and hand-made points are never lost.  One function or all."""
        def act():
            fns = [self._need(fid)] if fid else list(self.ds.functions)
            lines, bad = [], []
            for fn in fns:
                if not fn.rules:
                    continue
                try:
                    rep = db.regenerate(fn)
                except db.DsError as exc:
                    bad.append(f'{fn.name}: {plain_error(exc)}')
                    continue
                msg = self._regen_message(rep)
                if msg != 'No point changed.':
                    lines.append(f'{fn.name}: {msg}')
            text = '; '.join(lines) if lines else 'No point changed.'
            if bad:
                text += ' Could not recalculate: ' + ' | '.join(bad)
            return text
        return self._do('recalculate points', act)

    def point_text(self, fn, p):
        """'+5 V', '+5 V @ 1 kHz' (display only)."""
        s = show(p.nominal, fn.unit, shared_prefix([p.nominal], fn.unit)) if p.nominal else show(0, fn.unit)
        if p.nominal > 0 and fn.unit not in ('',):
            s = '+' + s
        if p.frequency is not None:
            s += f' @ {show(p.frequency, "Hz")}'
        return s

    def point_rows(self, fid=None, period=None, only_problems=False):
        """The preview table: one dict per point (display strings; SI values stay in the datasheet)."""
        fn = self.fn(fid)
        if fn is None:
            return []
        period = period or self.period
        bad = {p['point_id'] for p in self.problems() if p['point_id'] and p['level'] == 'error'}
        rows = []
        for p in fn.points:
            rng = fn.range(p.range_id)
            forced = _prefix_value(rng.display_unit or fn.display_unit) if rng and (rng.display_unit or fn.display_unit) else ''
            passfail = bool(fn.info.get('passfail'))
            info = dict(error='')
            low = high = None
            if not passfail:
                info = db.point_limits(self.ds, fn, p, period)
            row = dict(id=p.id, range_id=p.range_id, range=self.range_text(fn, rng) if rng else p.range_id, enabled=p.enabled,
                       frequency=show(p.frequency, 'Hz') if p.frequency is not None else '', amplitude=show(p.amplitude, 'V') if p.amplitude is not None else '',
                       label=p.label, note=p.note, origin=('rule' if p.origin.startswith('rule:') and not p.edited else 'edited' if p.origin.startswith('rule:') else 'manual'),
                       rule=p.origin[5:] if p.origin.startswith('rule:') else '', override=period in p.overrides and any(v not in (None, '') for v in p.overrides[period].values()),
                       overrides=sorted(p.overrides), error=info.get('error', ''), has_error=p.id in bad or bool(info.get('error')), ambiguous=bool(info.get('ambiguous')))
            if passfail or info.get('error'):
                pre = shared_prefix([p.nominal], fn.unit, forced)
                row.update(nominal=show(p.nominal, fn.unit, pre), low='', high='', accept='Pass / fail: the operator answers the question' if passfail else '', tol_text='',
                           source='')
            else:
                vals = [p.nominal, info['low'], info['high']]
                pre = shared_prefix(vals, fn.unit, forced)
                row.update(nominal=show(p.nominal, fn.unit, pre), low=show(info['low'], fn.unit, pre) if info['low'] is not None else 'open',
                           high=show(info['high'], fn.unit, pre) if info['high'] is not None else 'open', accept=info['accept'], tol_text=info['tol_text'], source=info['source'])
            if only_problems and not row['has_error'] and not row['ambiguous']:
                continue
            rows.append(row)
        return rows

    def point_form_fields(self, fid=None):
        fn = self._need(fid)
        return dict(frequency=bool(fn.info.get('ac') or fn.info['family'] == 'generator' or fn.info.get('value')), amplitude=bool(fn.info.get('amplitude')), expect=fn.kind == 'CONT',
                    unit=db.unit_symbol(fn.unit))

    def add_point(self, fid, nominal, range_id=None, frequency='', amplitude='', label='', note='', expect=None):
        def act():
            fn = self._need(fid)
            kw = dict(label=label.strip(), note=note.strip())
            if expect:
                kw['settings'] = {'expect': expect}
            p = db.add_point(fn, nominal, range_id or None, frequency.strip() or None, amplitude.strip() or None, **kw)
            return f'Added point {self.point_text(fn, p)} on the {self.range_text(fn, fn.range(p.range_id))} range.'
        return self._do('add point', act)

    def edit_point(self, fid, pid, nominal=None, frequency=None, amplitude=None, label=None, note=None, range_id=None, expect=None):
        def act():
            fn = self._need(fid)
            ch = {}
            for k, v in (('nominal', nominal), ('frequency', frequency), ('amplitude', amplitude), ('label', label), ('note', note), ('range_id', range_id)):
                if v is not None:
                    ch[k] = v
            if expect is not None:
                p = fn.point(pid)
                if p is not None:
                    ch['settings'] = dict(p.settings, expect=expect)
            db.edit_point(fn, pid, **ch)
            return 'Point changed. It is now yours: recalculating will not overwrite it.'
        return self._do('edit point', act)

    def remove_point(self, fid, pid):
        def act():
            fn = self._need(fid)
            p = fn.point(pid)
            if p is None:
                raise db.DsError('no_point', f'No point {pid}.')
            was_rule = p.origin.startswith('rule:') and not p.edited
            db.remove_point(fn, pid)
            self.ds.assignments.pop(pid, None)
            return 'Point removed.' + (' It comes back if you recalculate; switch it off instead to keep it out.' if was_rule else '')
        return self._do('remove point', act)

    def set_point_enabled(self, fid, pid, enabled):
        def act():
            fn = self._need(fid)
            p = fn.point(pid)
            if p is None:
                raise db.DsError('no_point', f'No point {pid}.')
            p.enabled = bool(enabled)
            p.edited = True
        return self._do('switch point', act, 'Point switched on.' if enabled else 'Point switched off (it stays in the table but is not run).')

    def set_point_override(self, fid, pid, low='', high='', period=None):
        """Type the limits of one point for one period (the spec is bypassed for it).  Both empty = clear."""
        period = period or self.period

        def act():
            fn = self._need(fid)
            if not str(low).strip() and not str(high).strip():
                db.clear_override(fn, pid, period)
                return 'Typed limit cleared: the specification applies again.'
            db.set_override(fn, pid, period, low.strip() or None, high.strip() or None)
            return f'Typed limits set for period {period}.'
        return self._do('override limits', act)

    def clear_point_override(self, fid, pid, period=None):
        return self.set_point_override(fid, pid, '', '', period)

    def point_detail(self, fid, pid, period=None):
        fn = self._need(fid)
        p = fn.point(pid)
        if p is None:
            return {}
        period = period or self.period
        ov = p.overrides.get(period, {})
        return dict(id=pid, nominal=db.fmt(p.nominal), frequency=db.fmt(p.frequency) if p.frequency is not None else '', amplitude=db.fmt(p.amplitude) if p.amplitude is not None else '',
                    label=p.label, note=p.note, range_id=p.range_id, enabled=p.enabled, low=ov.get('low') or '', high=ov.get('high') or '', expect=p.settings.get('expect', ''))

    def set_period(self, pid):
        if pid in self.ds.period_ids():
            self.period = pid
            return True
        return False

    # ------------------------------------------------------------------------------------------------------------------ 6. automation
    def match_fresh(self):
        return self.match_result is not None and self.match_rev == self._rev and self.match_period == self.period

    def _get_matcher(self):
        if self._matcher is None:
            if self.matcher_factory is not None:
                self._matcher = self.matcher_factory()
            else:
                import datasheet_builder_match as dm
                self._matcher = dm.Matcher()
        return self._matcher

    def run_match(self, period=None):
        """Run the standards matcher over the enabled points (it never changes the datasheet).  Returns Outcome(detail=summary text)."""
        self.match_error = ''
        period = period or self.period
        errs = [p for p in self.problems() if p['level'] == 'error' and p['step'] <= S_POINTS]
        if errs:
            return Outcome(False, f'Fix the {len(errs)} problem(s) in steps 1 to 5 first: the limits must be known before a standard can be chosen.', errs)
        try:
            res = self._get_matcher().match(self.ds, period)
        except Exception as exc:                          # standards database missing / damaged: say so, keep the window alive
            self.match_error = f'The standards could not be loaded or matched ({type(exc).__name__}: {exc}).'
            return Outcome(False, self.match_error)
        self.match_result, self.match_rev, self.match_period = res, self._rev, period
        return Outcome(True, self.match_summary_text(), res)

    def _cap_text(self, a):
        import datasheet_builder_match as dm
        if a.status == 'manual':
            return 'set by hand (your own standard)'
        if a.status != 'assigned':
            return 'cannot automate (no standard)'
        cap = dm.automation_status(a.standard, a.kind, a.direction)
        return dm.automation_text(cap, a.kind)

    def match_rows(self, fid=None, filter='all'):
        """One dict per point: standard, mode, TAR / TUR, automation sentence, reason for uncovered ones.  filter: all | uncovered | cannot | unverified."""
        if self.match_result is None:
            return []
        import tartur
        rows = []
        for f, p in self.ds.all_points():
            if fid and f.id != fid:
                continue
            a = self.match_result.assignments.get(p.id)
            if a is None:
                continue
            cap = self._cap_text(a)
            level = 'bad' if a.status == 'uncovered' else 'ok' if a.can_automate else 'warn'
            row = dict(point_id=p.id, function_id=f.id, function=f.name, point=self.point_text(f, p), status=a.status, standard=a.standard or ('MANUAL' if a.status == 'manual' else ''),
                       mode=a.mode, overridden=a.overridden, tar=tartur.format_ratio(a.tar), tur=tartur.format_ratio(a.tur), automation=cap, automation_status=a.automation,
                       can_automate=a.can_automate, reason=a.reason, message=a.message if a.status == 'uncovered' else a.automation_note, alternative=a.automatable_alternative, level=level)
            if filter == 'uncovered' and a.status != 'uncovered':
                continue
            if filter == 'cannot' and (a.status == 'uncovered' or a.can_automate):
                continue
            if filter == 'unverified' and a.automation != 'unverified':
                continue
            rows.append(row)
        return rows

    def match_summary(self):
        """Per function: points, assigned, uncovered, manual, automatable, unverified + totals."""
        if self.match_result is None:
            return dict(functions=[], total=dict(points=0, assigned=0, uncovered=0, manual=0, automatable=0, unverified=0))
        summ = self.match_result.summary()
        total = dict(points=0, assigned=0, uncovered=0, manual=0, automatable=0, unverified=0)
        funcs = []
        for f in self.ds.functions:
            s = summ.get(f.id)
            if not s:
                continue
            funcs.append(dict(s, id=f.id, name=f.name))
            for k in total:
                total[k] += s[k]
        return dict(functions=funcs, total=total)

    def match_summary_text(self):
        t = self.match_summary()['total']
        if not t['points']:
            return 'No enabled points to match.'
        s = f"{t['assigned']} of {t['points']} points have a standard; {t['automatable']} can be run automatically"
        if t['unverified']:
            s += f" ({t['unverified']} with commands not yet verified on hardware)"
        if t['uncovered']:
            s += f"; {t['uncovered']} are not covered by any standard"
        if t['manual']:
            s += f"; {t['manual']} use your own standard"
        return s + '.'

    def candidate_rows(self, pid):
        """The standards that were considered for a point (for the override picker), best first, with why a standard does not cover it."""
        import tartur
        if self.match_result is None or pid not in self.match_result.assignments:
            return []
        import datasheet_builder_match as dm
        a = self.match_result.assignments[pid]
        rows = []
        for c in a.candidates:
            cap = dm.automation_status(c.standard, a.kind, a.direction)
            rows.append(dict(standard=c.standard, covered=c.covered, tur=tartur.format_ratio(c.tur), tar=tartur.format_ratio(c.tar), automation=dm.automation_text(cap, a.kind),
                             can_automate=cap.can_automate, reason=c.reason, message=c.message if not c.covered else '', chosen=c.standard == a.standard,
                             row=c.row))
        return rows

    def override_choices(self, pid):
        """[(value, label)] for the per-point picker: 'automatic', each candidate, and 'MANUAL'."""
        out = [('', 'Automatic (best match)')]
        for c in self.candidate_rows(pid):
            lab = c['standard'] + (f"  TUR {c['tur']}" if c['tur'] else '') + ('' if c['covered'] else '  (does not cover this point)') + ('  [can automate]' if c['can_automate'] and c['covered'] else '')
            out.append((c['standard'], lab))
        out.append(('MANUAL', 'MANUAL: I will use my own standard'))
        return out

    def set_assignment(self, pid, standard):
        """Override the choice for one point ('' = automatic again, 'MANUAL' = the operator's own standard).  Stored in the datasheet (ds.assignments)."""
        def act():
            if not any(p.id == pid for _, p in self.ds.all_points()):
                raise db.DsError('no_point', f'No point {pid}.')
            if standard in (None, ''):
                self.ds.assignments.pop(pid, None)
                return 'Back to the automatic choice.'
            self.ds.assignments[pid] = standard
            return f'This point will use {standard}.'
        res = self._do('choose standard', act)
        if res.ok and self.match_result is not None:
            self.run_match(self.match_period or self.period)           # the same matcher, standards are already loaded
        return res

    def clear_assignments(self):
        def act():
            n = len(self.ds.assignments)
            self.ds.assignments = {}
            return f'{n} override(s) cleared.'
        res = self._do('clear overrides', act)
        if res.ok and self.match_result is not None:
            self.run_match(self.match_period or self.period)
        return res

    def driver_rows(self):
        """What the suite's drivers can do today (so 'cannot automate' is understandable): one dict per standard with the functions it supports."""
        import datasheet_builder_match as dm
        used = {f.kind for f in self.ds.functions}
        out = []
        for r in dm.driver_table():
            fx = {k: v for k, v in r.get('functions', {}).items() if k in used}
            out.append(dict(model=r['model'], label=r.get('label', r['model']), role=r.get('role', ''), driver=r.get('driver', '') or '(no driver)', imported=r.get('imported', False),
                            functions={k: dict(v, text=dm.automation_text(dm.Capability(v['status'], v.get('driver', ''), v.get('via', ''), v.get('note', '')), k)) for k, v in fx.items()},
                            notes=r.get('notes', '')))
        return out

    # ------------------------------------------------------------------------------------------------------------------ 7. review and save
    def review(self):
        """Everything the last page shows: summary lines, problems, counts, whether Save as runnable is allowed and what the buttons should say."""
        ds = self.ds
        counts = self.problem_counts()
        npts = sum(len(f.points) for f in ds.functions)
        lines = [f'{ds.make or "(no make)"} {ds.model or "(no model)"}: {ds.title or "(no title)"}',
                 'Periods: ' + ', '.join(p.label or p.id for p in ds.periods) + f' (default {ds.default_period})']
        funcs = []
        for f in ds.functions:
            funcs.append(dict(id=f.id, name=f.name, ranges=len(f.ranges), spec=len(f.spec), points=len(f.points), enabled=sum(1 for p in f.points if p.enabled)))
            lines.append(f'{f.name}: {len(f.ranges)} range(s), {len(f.spec)} specification line(s), {len(f.points)} point(s)')
        auto = self.match_summary_text() if self.match_fresh() else 'Automation has not been checked for the current datasheet (step 6).'
        if ds.assignments:
            auto += f' {len(ds.assignments)} point(s) have your own standard choice.'
        runnable = counts['errors'] == 0 and bool(ds.functions)
        next_v = (self.last_save.version + 1) if self.last_save else (ds.version + 1)
        return dict(lines=lines, functions=funcs, points=npts, errors=counts['errors'], warnings=counts['warnings'], problems=self.problems(), automation=auto,
                    can_save=runnable, can_save_draft=bool(ds.make.strip() or ds.model.strip() or ds.title.strip() or ds.functions),
                    next_version=next_v, dirty=self.dirty, based_on=self.based_on,
                    save_text=(f'Save version {next_v} and add to the Procedures list' if runnable else
                               f'{counts["errors"]} error(s) must be fixed before this can be a runnable procedure. You can still save version {next_v} as a draft.'))

    def save(self, note='', as_draft=False):
        """Save a NEW version.  With errors: refused unless as_draft=True (stored as a draft; the earlier runnable spec stays).  Without errors it is
        written as the runnable spec and registered as a procedure with the 'user-built' tag.  Returns Outcome(detail=SaveResult)."""
        counts = self.problem_counts()
        if counts['errors'] and not as_draft:
            return Outcome(False, f'Not saved: {counts["errors"]} error(s) must be fixed first (or save it as a draft).')
        if not (self.ds.make.strip() or self.ds.model.strip() or self.ds.title.strip() or self.ds.functions):
            return Outcome(False, 'Not saved: there is nothing in the datasheet yet.')
        res = self.storage.save(self.ds, note=note)
        self.last_save = res
        if not res.ok:
            why = '; '.join(str(p) for p in res.problems if getattr(p, 'level', 'error') == 'error') or 'the files could not be written'
            return Outcome(False, f'Not saved: {why}.', res)
        self._saved_json = self._snapshot()
        self.based_on = f'{res.uid} v{res.version}'
        if res.status == 'ready':
            listed = any(e['uid'] == res.uid for e in self.storage.entries())
            msg = f'Saved version {res.version}: "{res.uid}" is a runnable procedure with the user-built tag' + ('.' if listed else ', but it was not found in the procedure entries: check the data folder.')
        else:
            msg = f'Saved version {res.version} as a DRAFT (not runnable): ' + ', '.join(f'{c}' for c in [f"{counts['errors']} error(s)"]) + '. Any earlier runnable version is unchanged.'
        return Outcome(True, msg, res)

    def version_rows(self):
        if not self.ds.uid:
            return []
        out = []
        for v in self.storage.versions(self.ds.uid):
            out.append(dict(v, status_text={'ready': 'runnable', 'draft': 'draft (had problems)'}.get(v.get('status'), v.get('status') or '')))
        return out

    def load_version(self, version):
        """Replace the editor's content with an older version (the current content is one undo step; saving makes it a NEW version)."""
        def act():
            old = self.storage.load(self.ds.uid, version)
            if old is None:
                raise db.DsError('load', f'Version {version} cannot be read.')
            uid = self.ds.uid
            self.ds = old
            self.ds.uid = uid
            if self.ds.function(self.fid) is None:
                self.fid = self.ds.functions[0].id if self.ds.functions else ''
            self.period = self.ds.default_period
            self.based_on = f'{uid} v{version}'
            return f'Loaded version {version}. Saving it creates a new version; nothing is overwritten.'
        return self._do('load version', act)
