"""Datasheet Builder, stage B: the UI-free controller (no tkinter, no instrument I/O).  datasheet_builder_ui.py builds thin Tk widgets on top of it.

    lst = DatasheetList(Storage())                      # the list tab: rows, search, New / Open / Duplicate / Delete / Restore / Export / Import / versions
    ed  = EditorModel(Storage())                        # a new datasheet (or EditorModel.open(storage, uid, version=None))
    ed.set_header(make='Keysight', model='34461A', title='34461A Performance Verification')
    ed.add_function('DCV'); ed.add_range(fid, '10 V', '10 uV'); ed.add_spec_entry(fid, {'1y': '0.004 % of reading + 0.0035 % of range'})
    ed.example(fid, '0.004 % of reading + 0.0035 % of range', range_id='r10')['text']     # 'At 5 V on the 10 V range the low limit is 4.9965 V and the high limit is 5.0035 V.'
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
from datasheet_builder_check_model import CheckMixin      # the Sheet check (build-time rules 1-5), GridModel only

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

# The inspector (right-hand row panel) collapses to its slim rail by itself when the window is narrower than this (96-dpi px): below it the grid would
# drop under about 8 rows or its columns get cramped (the inspector is 290 px under 1250 px).  It opens again when the window grows back.  A choice
# made by hand (Hide > / the rail button / Ctrl+I) sticks for the session and switches this off.
INSPECTOR_COLLAPSE_BELOW = 1150


def inspector_should_be_open(width, below, manual, is_open):
    """Whether the inspector should be open for a window `width` px wide (`below` = the scaled threshold).  `manual` is None until the person
    hides / shows it by hand, then True: a manual choice is never overridden.  Width 1 or less (not on screen yet) changes nothing."""
    if manual or width <= 1:
        return is_open
    return width >= below


# the codes of validate() that belong to a flow step (when `where` does not already say)
_CODE_STEP = {}
for _c in ('no_make', 'no_model', 'no_title', 'no_periods', 'dup_period', 'bad_period', 'default_period', 'limit_rounding'):
    _CODE_STEP[_c] = S_HEADER
for _c in ('no_functions', 'no_test_rows', 'bad_kind', 'bad_direction', 'dup_function'):
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

    def lock_reason(self, uid):
        """'' or the sentence saying this user-built procedure is verified on hardware and locked (verified.py)."""
        return db.lock_reason(uid, db=self.db_path)

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
    def automation_text(row, check=None):
        """What the suite can do with the saved datasheet today, from the runnable spec's engine summary.  `check` = dict(unverified_points, unverified_commands)
        from the sheet check (saved with the spec, or worked out from the standards matcher): points whose commands are not verified on hardware are NOT
        counted as plainly 'run by the suite' (a real run lists their commands first and the operator must accept them)."""
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
        check = check if check is not None else (eng.get('check') or {})
        unv = int(check.get('unverified_points') or 0)
        tail = (f'; {unv} use commands not yet verified on hardware (a real run asks you to accept them)' if unv else '')
        miss = int(check.get('missing_uncertainties') or 0)
        if miss:                                                   # rule 5: readings that should carry an uncertainty and have none (and no waiver)
            tail += f'; missing uncertainties: {miss} (pick a standard or waive them before the next save)'
        if hand == 0:
            return (f'Ready: {n} of {n} points run by the suite' + tail) if tail else f'Ready: all {n} points run by the suite'
        return f'Ready: {run} of {n} points run by the suite, {hand} set by hand' + tail

    def _check_for(self, r):
        """The check summary the Automation column needs: the one saved with the spec, else (a sheet saved before the Sheet check existed) the standards
        matcher's count of points with unverified commands.  None when neither can be had."""
        if r.get('deleted') or not r.get('runnable_version'):
            return None
        eng = _read_engine(r.get('spec_file', ''))
        if eng.get('check') is not None:
            return eng['check']
        key = ('check', r['uid'], r['version'])
        if key not in self._cache:
            try:
                import datasheet_builder_rules as _rules
                ds = self.storage.load(r['uid'], r['version'])
                if ds is None or ds.options.get('manual_entry'):
                    self._cache[key] = {}
                else:
                    if getattr(self, '_matcher', None) is None:
                        self._matcher = self.matcher_factory() if self.matcher_factory else __import__('datasheet_builder_match').Matcher()
                    s = _rules.list_summary(ds, matcher=self._matcher) or {}
                    self._cache[key] = dict(unverified_points=s.get('unverified', 0), missing_uncertainties=s.get('missing', 0))
            except Exception:
                self._cache[key] = {}
        return self._cache[key]

    def rows(self):
        q = self.search.strip().lower()
        out = []
        for r in self._raw:
            funcs, nfun = self._functions_text(r['uid'], r['version'])
            text = ' '.join(str(r.get(k, '')) for k in ('make', 'model', 'title', 'uid')).lower() + ' ' + funcs.lower()
            if q and q not in text:
                continue
            out.append(dict(uid=r['uid'], make=r['make'], model=r['model'], title=r['title'], version=r['version'], functions=funcs, function_count=nfun,
                            points=r['points'], automation=self.automation_text(r, self._check_for(r)), saved=r.get('updated_at', ''), status=r['status'],
                            deleted=bool(r['deleted']), tag=r.get('tag', db.TAG)))
        return out

    def row(self, uid):
        return next((r for r in self.rows() if r['uid'] == uid), None)

    def empty_text(self):
        if self._raw and self.search.strip():
            return 'No datasheet matches the search.'
        return 'No datasheets yet.\nPress "New" to build one, or "Import JSON..." to bring one in.'

    # ---- actions
    def new(self, handheld=False):
        """A blank sheet (the default), or one that starts with the handheld multimeter sections (`handheld=True`)."""
        g = GridModel(self.storage, matcher_factory=self.matcher_factory)
        if handheld:
            g.add_handheld_functions()
        return g

    def open(self, uid, version=None):
        """An EditorModel for the datasheet (latest or the given version), or None with `self.last_error` set.  A procedure that is verified on
        hardware and locked is not opened for editing (`self.refused` is True and last_error says how to unlock or copy it)."""
        self.refused = False
        why = self.storage.lock_reason(uid)
        if why:
            self.refused, self.last_error = True, why
            return None
        ed = GridModel.open(self.storage, uid, version, matcher_factory=self.matcher_factory)
        self.last_error = '' if ed else f'Could not read datasheet {uid}' + (f' version {version}' if version else '') + '.'
        return ed

    last_error = ''
    refused = False

    def duplicate(self, uid, title=None):
        res = self.storage.duplicate(uid, title=title)
        if res is None or not res.ok:
            return Outcome(False, 'Could not duplicate: the source datasheet cannot be read or the copy could not be written.')
        self.refresh()
        return Outcome(True, f'Duplicated as "{res.uid}" (version {res.version}).', res.uid)

    def delete(self, uid):
        """SOFT delete: it leaves the Procedures list, every version stays on disk, and Restore brings it back.  Refused for a procedure that is
        verified on hardware and locked."""
        why = self.storage.lock_reason(uid)
        if why:
            return Outcome(False, why)
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
                    if p.spec is not None:
                        p.spec.exprs.pop(pid, None), p.spec.exprs_minus.pop(pid, None), p.spec.printed.pop(pid, None)
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

    def set_manual_entry(self, on):
        """Flag the datasheet as a MANUAL calibration (every reading is typed into the run window's test point grid; the Manager lists it under Manual Calibrations)."""
        def act():
            self.ds.options['manual_entry'] = bool(on)
        return self._do('manual calibration', act, 'This is a manual calibration: readings are typed into the grid (Manual Calibrations tab).' if on
                        else 'Automation is used where a standard can do the point (Automated Calibrations tab).')

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
        'At 5 V on the 10 V range the low limit is 4.9965 V and the high limit is 5.0035 V.'  (The error of each term, the +/- amount, is in parts[]: it is
        the breakdown of the statement being edited.)  Never raises."""
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
        res['text'] = f'{at} the low limit is {show(low, fn.unit, pre)} and the high limit is {show(high, fn.unit, pre)}.'
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
            rule_errs = [p for p in res.problems if getattr(p, 'level', 'error') == 'error' and str(getattr(p, 'code', '')).startswith('rule')]
            msg = f'Saved version {res.version} as a DRAFT (not runnable): ' + ', '.join(f'{c}' for c in [f"{counts['errors'] + len(rule_errs)} error(s)"]) + '. Any earlier runnable version is unchanged.'
            if rule_errs:
                msg += ' The sheet check found: ' + str(rule_errs[0])
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


# ------------------------------------------------------------------------------------------------------------------------------ the datasheet grid
# One big sheet, one row per test point.  GridModel is an EditorModel (so every undo step, problem, save and standards-matching method is the same
# code the rest of the builder uses) plus the sheet itself: rows, the selected cell, editing a cell, the spec boxes under the sheet, Calc.
GRID_COLUMNS = (
    dict(key='step', title='STEP NUM', width=84, edit=False, align='center'),
    dict(key='function', title='FUNCTION TESTED', width=210, edit=True, align='w'),
    dict(key='nominal', title='NOMINAL VALUE', width=190, edit=True, align='w'),
    dict(key='found', title='AS FOUND', width=120, edit=False, align='center'),
    dict(key='left', title='AS LEFT', width=120, edit=False, align='center'),
    dict(key='oot', title='Out of Tol', width=64, edit=False, align='center'),
    dict(key='low', title='LOW LIMIT', width=125, edit=True, align='w'),
    dict(key='high', title='HIGH LIMIT', width=125, edit=True, align='w'),
)
# GRID_COLUMNS is the PRINTED datasheet (the template still has As Found / As Left / Out of Tol, then LOW LIMIT / HIGH LIMIT).  The on-screen grid shows only VIEW_COLUMNS: the blank
# As Found / As Left / Out of Tol columns are not needed while building (view only; the row dicts still carry them, print_view() still prints them).
VIEW_COLUMNS = (
    dict(key='step', title='STEP NUM', width=90, edit=False, align='center'),
    dict(key='function', title='FUNCTION TESTED', width=270, edit=True, align='w'),
    dict(key='nominal', title='NOMINAL VALUE', width=240, edit=True, align='w'),
    dict(key='low', title='LOW LIMIT', width=160, edit=False, align='w'),
    dict(key='high', title='HIGH LIMIT', width=160, edit=False, align='w'),
)
# The tolerance is shown as the two ABSOLUTE limits (nominal -/+ tolerance, worked out with the same exact Decimal limit maths as ever), never as a +/- error.
# The two limit cells are READ-ONLY displays: the limits are made only by the tolerance calculator (Inspector, section Limits and tolerance: the chips and
# boxes, Asymmetrical tolerance, Calc).  What is stored does not change: a tolerance statement (symmetric, or with a different minus side); an OLD sheet may
# still hold a stored Low / High pair (Point.overrides), which is read, judged and printed as before but can no longer be written from here.
TYPED_LIMITS_NOTE = ('This row has limits that were typed earlier. They are stored as they are, marked "typed" in the sheet, and still used. Press Calc to work the limits out from a tolerance instead (the typed limits are then replaced), or Clear typed limits.')
LIMITS_HINT = 'Limits come from the tolerance calculator: use "Limits and tolerance" in the row panel and press Calc.'
COL_KEYS = tuple(c['key'] for c in VIEW_COLUMNS)
EDIT_COLS = tuple(c['key'] for c in VIEW_COLUMNS if c['edit'])
MIN_ROWS = 16                      # the sheet always shows at least this many rows, so it looks like a blank datasheet
SPARE_ROWS = 2                     # and always at least this many empty ones at the end
MAX_MULTI = 500                    # most rows one "Multiple Test Points" can make at once
SYMBOLS = ('±', '°', 'µ', '¹', '²', '³', '·')
SPEC_ORDER = ('iv', 'fs', 'floor', 'db', 'calc')
SPEC_TYPES = (('iv', '% of I.V. (reading)', 'A percentage of the value being tested (I.V. = input value; the manual may print it as %iV or % rdg).'),
              ('fs', '% of F.S. (range)', 'A percentage of the full scale of the range the value is on.'),
              ('floor', 'Floor (fixed value)', 'A fixed amount added to the tolerance, in the units shown in Units of Measure.'),
              ('db', '± dB (log)', 'A tolerance printed in dB: it is turned into a ratio of the value (20 log for volts and amps, 10 log for power).'),
              ('calc', 'Calculator', 'Type the whole accuracy statement yourself, as the manual prints it, for example 0.05 % of reading + 2 counts.'))
SPEC_LABEL = {k: lab for k, lab, _t in SPEC_TYPES}
MULTI_MODES = (('span', 'Lo to High', 'n points spread evenly from Nominal Value up to High (type how many in n).'),
               ('pct', 'n %', 'A row every n % of the High value, starting at Nominal Value.'),
               ('units', 'n Units', 'A row every n units (in the Units of Measure), starting at Nominal Value.'),
               ('ppm', 'n ppm', 'A row every n ppm of the High value, starting at Nominal Value.'))
UNIT_PREFIXES = {'V': ('µ', 'm', '', 'k'), 'A': ('µ', 'm', ''), 'ohm': ('m', '', 'k', 'M', 'G'), 'F': ('p', 'n', 'µ', 'm', ''), 'Hz': ('', 'k', 'M', 'G'),
                 's': ('n', 'µ', 'm', '')}
LOCK_MODES = (('edit', 'Edit Mode'), ('locked', 'Locked'))
_NUMBER_ONLY = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
_CODE_COL = {'no_spec': 'tol', 'expr_eval': 'tol', 'limit_inverted': 'tol', 'limit_value': 'tol', 'override_inverted': 'tol', 'spec_missing_period': 'tol',
             'one_sided_needs_bound': 'tol', 'nominal_outside_limit': 'tol', 'limit_zero_width': 'tol', 'spec_border': 'tol', 'override_period': 'tol',
             'no_frequency': 'nominal', 'no_amplitude': 'nominal', 'point_outside_range': 'nominal', 'dup_point': 'nominal', 'freq_not_allowed': 'nominal',
             'point_range_unknown': 'nominal', 'dup_point_id': 'nominal', 'limit_open': 'tol'}


def with_units(text, units):
    """'5' + 'mV' -> '5 mV'; a text that already carries a unit is left alone."""
    t = (text or '').strip()
    if t and units and _NUMBER_ONLY.match(t):
        return f'{t} {units}'
    return t


def unit_choices(unit):
    """The unit spellings a person may pick for a function whose SI unit is `unit` ('V' -> µV, mV, V, kV)."""
    sym = db.unit_symbol(unit)
    if not sym:
        return []
    if unit in db._NO_PREFIX or unit not in UNIT_PREFIXES:
        return [sym]
    return [p + sym for p in UNIT_PREFIXES[unit]]


def split_unit_text(text):
    """'5.000 mV' -> ('5.000', 'mV'); a bare number -> (number, '')."""
    m = re.match(r'^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$', text or '')
    return (m.group(1), m.group(2)) if m else ('', (text or '').strip())


def prefix_of_units(units, unit):
    """The SI prefix symbol of a unit spelling ('mV' with base 'V' -> 'm', 'V' -> '', 'kΩ' -> 'k'); '' when it has none or is not understood."""
    sym = db.unit_symbol(unit)
    u = (units or '').strip().replace('u', 'µ') if unit not in ('s', 'Hz') else (units or '').strip()
    if sym and u.endswith(sym) and u[:-len(sym)] in dict(db._PREFIX_ORDER):
        return u[:-len(sym)]
    return ''


def insert_at(text, pos, symbol):
    """Insert `symbol` into `text` at `pos` (None = the end).  Returns (new text, new cursor position)."""
    text = text or ''
    pos = len(text) if pos is None or not 0 <= pos <= len(text) else pos
    return text[:pos] + symbol + text[pos:], pos + len(symbol)


def copy_spec(entry):
    """A separate copy of a SpecEntry (so two rows never share one object)."""
    return db.SpecEntry.from_dict(copy.deepcopy(entry.to_dict())) if entry is not None else None


def _decimals_of(value):
    """Digits after the point of an exact Decimal (0 for whole numbers)."""
    v = db.dec(value).normalize()
    return max(0, -v.as_tuple().exponent)


def _same(a, b):
    return (None if a in (None, '') else db.dec(a)) == (None if b in (None, '') else db.dec(b))


class GridGeometry:
    """Where the cells of the sheet are (pixels, no tkinter): the canvas uses it for drawing, scrolling and for 'which cell was clicked'.
    The heading stays at the top; row r is `row_h` tall and sits at head_h + r * row_h - top (top = how far the rows are scrolled up)."""

    def __init__(self, widths=None, row_h=30, head_h=40, num_w=44):
        self.base = list(widths or [c['width'] for c in VIEW_COLUMNS])
        self.widths = list(self.base)
        self.row_h, self.head_h, self.num_w = row_h, head_h, num_w

    def fit(self, avail, lo=0.6, hi=1.8):
        """Scale the column widths so the sheet fills `avail` pixels (within lo..hi of the design widths)."""
        k = max(lo, min(hi, (avail - self.num_w) / sum(self.base)))
        self.widths = [max(20, int(w * k)) for w in self.base]
        return self.widths

    def col_x(self, c):
        return self.num_w + sum(self.widths[:c])

    @property
    def width(self):
        return self.num_w + sum(self.widths)

    def col_at(self, x):
        """Column index at x, -1 for the row-number strip, None outside the sheet."""
        if x < 0:
            return None
        if x < self.num_w:
            return -1
        x -= self.num_w
        for i, w in enumerate(self.widths):
            if x < w:
                return i
            x -= w
        return None

    def row_at(self, y, nrows, top=0):
        """Row index at screen y, -1 for the heading, None below the last row."""
        if y < 0:
            return None
        if y < self.head_h:
            return -1
        r = int((y - self.head_h + top) // self.row_h)
        return r if 0 <= r < nrows else None

    def box(self, r, c, top=0):
        x = self.col_x(c)
        y = self.head_h + r * self.row_h - top
        return x, y, x + self.widths[c], y + self.row_h

    def visible(self, top, height, nrows):
        """(first, last) row indexes that show in a window `height` tall scrolled `top` pixels (last is exclusive)."""
        first = max(0, int(top // self.row_h))
        last = min(nrows, int((top + height - self.head_h) // self.row_h) + 1)
        return first, max(first, last)

    def max_top(self, nrows, height):
        return max(0, nrows * self.row_h - (height - self.head_h))

    def top_for(self, r, top, height):
        """The scroll position that brings row r fully into view (unchanged when it already is)."""
        room = height - self.head_h
        if r * self.row_h < top:
            return r * self.row_h
        if (r + 1) * self.row_h > top + room:
            return max(0, (r + 1) * self.row_h - room)
        return top


@dataclass
class Resolved:
    """What a typed function name means: a section already in the sheet (fid) or a new one of a kind."""
    fid: str = ''
    kind: str = ''


class GridModel(CheckMixin, EditorModel):
    """The datasheet grid: everything the window needs, with no tkinter.

        g = GridModel(Storage())                      # or GridModel.open(storage, uid)
        g.rows()                                      # [dict(key, n, kind, step, function, nominal, found, left, oot, tol, problem, level, ...)]
        g.select('b:0', 'nominal'); g.commit_cell('5 V')       # type a value in the first empty row
        g.panel_state()                               # what the boxes under the sheet show for the selected row
        g.calc_row(None, form)                        # Calc: apply the boxes to the row and work out its tolerance
        g.undo()                                      # takes back the last edit

    A row is a test point; a section heading is a function; an empty row is not stored until it has a value.  A row's tolerance is its own
    specification (Point.spec) worked out by the same exact Decimal expressions as the rest of the builder; nothing here uses float for a limit.
    """

    def __init__(self, storage=None, ds=None, matcher_factory=None, based_on=None):
        super().__init__(storage, ds, matcher_factory, based_on)
        self.locked = False
        self.sel_col = 'function'
        self._sel_index = 0
        self._rows_cache = None
        self.extra_blank = 0
        self.sel_key = ''
        self.sel_key = self._default_key()

    @classmethod
    def open(cls, storage, uid, version=None, matcher_factory=None):
        ds = storage.load(uid, version)
        if ds is None:
            return None
        g = cls(storage, ds, matcher_factory=matcher_factory)
        g.based_on = f'{uid} v{ds.version}'
        return g

    # ------------------------------------------------------------------------------------------------------------------ the rows
    def _default_key(self):
        rows = self.rows()
        first = next((r for r in rows if r['kind'] == 'point'), None)
        return (first or rows[0])['key']

    def _problem_index(self):
        by_point, by_func = {}, {}
        for p in self.problems():
            if p['point_id']:
                by_point.setdefault(p['point_id'], []).append(p)
            elif p['function_id']:
                by_func.setdefault(p['function_id'], []).append(p)
        return by_point, by_func

    def rows(self):
        """Every row of the sheet, top to bottom: a heading for each section, its test points, an empty row under an empty section, then empty rows
        at the end.  Cached until the datasheet changes."""
        stamp = (self._rev, self.period, self.extra_blank)
        if self._rows_cache and self._rows_cache[0] == stamp:
            return self._rows_cache[1]
        by_point, by_func = self._problem_index()
        out = []

        def add(**kw):
            for k, v in (('found', ''), ('left', ''), ('oot', ''), ('problem', ''), ('level', ''), ('bad', ()), ('enabled', True), ('remark', False),
                         ('step', ''), ('function', ''), ('nominal', ''), ('low', ''), ('high', ''), ('formula', ''), ('limits_from', ''), ('pid', ''), ('fid', '')):
                kw.setdefault(k, v)
            kw['n'] = len(out) + 1
            out.append(kw)

        for fi, fn in enumerate(self.ds.functions, 1):
            add(key=f'h:{fn.id}', kind='header', fid=fn.id, function=fn.name, **self._issue(by_func.get(fn.id, []), fn, None))
            k = 0
            for p in fn.points:
                if p.enabled:
                    k += 1
                rng = fn.range(p.range_id)
                add(key=f'p:{fn.id}:{p.id}', kind='point', fid=fn.id, pid=p.id, step=(f'{fi}-{k}' if p.enabled else '') + (' *' if p.note else ''),
                    function=f'{fn.name}, {self.range_text(fn, rng)} range' if rng is not None and len(fn.ranges) > 1 else fn.name,
                    nominal=self.nominal_text(fn, p), **self.limit_fields(fn, p), enabled=p.enabled, remark=bool(p.note),
                    **self._issue(by_point.get(p.id, []), fn, p))
            if not fn.points:
                add(key=f'e:{fn.id}', kind='blank', fid=fn.id)
        for i in range(max(SPARE_ROWS, MIN_ROWS - len(out)) + self.extra_blank):
            add(key=f'b:{i}', kind='blank')
        self._rows_cache = (stamp, out)
        return out

    def _issue(self, probs, fn, p):
        """The inline problem of a row: the first error, else the first warning, in plain words; plus which cells to mark."""
        if not probs:
            return {}
        probs = sorted(probs, key=lambda d: d['level'] != 'error')
        cols = {_CODE_COL.get(q['code'], 'function' if p is None else 'nominal') for q in probs}
        if 'tol' in cols:                                    # a tolerance problem marks both limit cells
            cols = (cols - {'tol'}) | {'low', 'high'}
        return dict(problem=self.plain_problem(probs[0], fn), level=probs[0]['level'], bad=tuple(sorted(cols)))

    def row(self, key=None):
        key = key or self.sel_key
        return next((r for r in self.rows() if r['key'] == key), None)

    def row_index(self, key=None):
        key = key or self.sel_key
        return next((i for i, r in enumerate(self.rows()) if r['key'] == key), None)

    def point_of(self, key=None):
        """(function, point) of a test-point row, else (function or None, None)."""
        r = self.row(key)
        if r is None:
            return None, None
        fn = self.ds.function(r['fid']) if r['fid'] else None
        return fn, (fn.point(r['pid']) if fn and r['pid'] else None)

    def target_function(self):
        """The section a new row goes into: the one picked, else the selected section, else the last one."""
        fn = self.ds.function(self.fid) if self.fid else None
        return fn or (self.ds.functions[-1] if self.ds.functions else None)

    # ---- display of a point
    def _prefix_for(self, fn, rng, values):
        forced = _prefix_value(rng.display_unit or fn.display_unit) if rng is not None and (rng.display_unit or fn.display_unit) else ''
        return shared_prefix(values, fn.unit, forced)

    def fmt_value(self, fn, rng, value, prefix=None):
        """'5.000 V': display only.  The digits are the exact value's; when the range has a resolution the number is padded with zeros to it."""
        if value is None:
            return ''
        pre = self._prefix_for(fn, rng, [value]) if prefix is None else prefix
        exp = dict(db._PREFIX_ORDER)[pre]
        with db.localcontext() as c:
            c.prec = db.PREC
            need = _decimals_of(db.dec(value) / db.D(10) ** exp) if value != 0 else 0
            res = _decimals_of(rng.resolution / db.D(10) ** exp) if rng is not None and rng.resolution else 0
        return db.format_si(value, fn.unit, prefix=pre, decimals=max(need, res))

    def nominal_text(self, fn, p):
        """The nominal cell: '+5 V', '5 V @ 1 kHz', '1 kHz, level 1 V'.  parse_nominal reads the same grammar back."""
        s = self.fmt_value(fn, fn.range(p.range_id), p.nominal)
        if p.nominal > 0 and fn.unit:
            s = '+' + s
        if p.frequency is not None:
            s += ' @ ' + db.format_si(p.frequency, 'Hz')
        if p.amplitude is not None:
            s += ', level ' + db.format_si(p.amplitude, 'V')
        return s

    def typing_prefix(self, fn, p=None):
        """The SI prefix a bare number typed in the NOMINAL cell is taken in: the prefix the cell itself shows (the range's display unit, else the function's,
        else the one the row's value is shown in; a zero row is shown without a prefix, so it is taken in the base unit), so typing 5 on a row shown in mV gives 5 mV.  A row that does not exist yet has no range: only the
        function's display unit counts (else the base unit, as before).  Display only: the value is stored as an exact SI number either way."""
        if fn is None or not fn.unit or fn.unit in db._NO_PREFIX:
            return ''
        if p is not None:
            return self._prefix_for(fn, fn.range(p.range_id), [p.nominal])
        return _prefix_value(fn.display_unit) if fn.display_unit else ''

    def typing_unit(self, fn, p=None):
        """'mV' for a row shown in mV, 'V' for volts: the unit spelling a bare number typed in the nominal cell (or the Inspector's Units box) is in."""
        return (self.typing_prefix(fn, p) + db.unit_symbol(fn.unit)) if fn is not None else ''

    def bare_unit(self, fn, p=None):
        """typing_unit() when the cell shows a prefixed unit (mV), else '' (a bare number is the base unit, exactly as before)."""
        return self.typing_unit(fn, p) if self.typing_prefix(fn, p) else ''

    def parse_nominal(self, fn, text, bare_unit=''):
        """Read a nominal cell: '<value> [@ <frequency>] [, level <amplitude>]'.  Returns dict(nominal, frequency, amplitude) as text (None when absent).
        A bare number in the value part is taken in `bare_unit` ('mV' = the unit the cell shows) when one is given; an explicit unit ('4950 mV', '5 V') stays as typed."""
        t = (text or '').strip()
        if not t:
            raise db.DsError('nominal', 'Type the value to test, for example 5 V.')
        level = None
        m = re.search(r',\s*(?:level|lvl)?\s*(.+)$', t, re.I)
        if m:
            level, t = m.group(1).strip(), t[:m.start()].strip()
        freq = None
        if '@' in t:
            t, freq = [x.strip() for x in t.split('@', 1)]
            if not freq:
                raise db.DsError('frequency', 'Type the frequency after the @, for example 5 V @ 1 kHz.')
            db.parse_quantity(freq, 'Hz')
        if level is not None:
            db.parse_quantity(level)
        if bare_unit:
            num, unit_part = split_unit_text(t)
            if num and not unit_part:
                t = f'{num} {bare_unit}'
        db.parse_quantity(t, fn.unit or None)
        return dict(nominal=t, frequency=freq, amplitude=level)

    # ---- the limits: LOW and HIGH, absolute (display only; the exact limit maths is Function.limit_for and has not changed)
    def typed_limits(self, p):
        """The typed Low / High pair of a point for the period on show (SI Decimals, None = not typed), or None when the point has none."""
        ov = p.overrides.get(self.period) or {}
        if not any(ov.get(k) not in (None, '') for k in ('low', 'high')):
            return None
        return tuple(db.dec(ov[k]) if ov.get(k) not in (None, '') else None for k in ('low', 'high'))

    def limit_of(self, fn, p):
        """The Limit of the point for the period on show, or None while it has none (no tolerance yet, an error in the statement)."""
        try:
            return fn.limit_for(p, self.period, self.ds)
        except db.DsError:
            return None

    def limit_cells(self, fn, p):
        """(low, high) cell texts: '4.9965 V', '5.0035 V'.  The same exact digits, SI prefix choice, range display unit and zero padding to the range's
        resolution as every other number of the row (fmt_value); a side that is not typed says 'open'; the other side of a one-sided entry ('at least -3 dB',
        a bound the engine needs, not a limit) says 'no limit'.  A pass / fail row says so in the first cell."""
        if fn.info.get('passfail'):
            return ('Pass / fail' if fn.kind != 'CONT' else ('Beeper on' if p.settings.get('expect', 'on') == 'on' else 'Beeper off')), ''
        lim = self.limit_of(fn, p)
        if lim is None:
            return '', ''
        rng = fn.range(p.range_id)
        pre = self._prefix_for(fn, rng, [v for v in (lim.low, lim.high, p.nominal) if v is not None])
        lo = self.fmt_value(fn, rng, lim.low, pre) if lim.low is not None else 'open'
        hi = self.fmt_value(fn, rng, lim.high, pre) if lim.high is not None else 'open'
        if lim.one_sided and lim.bound_used:                 # 'at least -3 dB': the other side is only the bound the engine needs (low <= reading <= high), not a limit
            mode = (fn.governing(p) or [None])[0].mode if fn.governing(p) else ''
            lo, hi = ('no limit' if mode == 'high_only' else lo), ('no limit' if mode == 'low_only' else hi)
        return lo, hi

    def limits_display(self, fn, p):
        """'Low limit 4.9965 V, High limit 5.0035 V' ('' while the row has no limits): the sentence the messages use."""
        lo, hi = self.limit_cells(fn, p)
        return f'Low limit {lo}, High limit {hi}' if lo and hi else ''

    def limit_fields(self, fn, p):
        """The row dict fields of the limits: low, high (cell texts), formula (the statement they are calculated from, '' when typed or none yet)
        and limits_from ('formula' | 'typed' | '' for none)."""
        lo, hi = self.limit_cells(fn, p)
        if fn.info.get('passfail'):
            return dict(low=lo, high=hi, formula='', limits_from='')
        typed = self.typed_limits(p) is not None
        formula = '' if typed else self.formula_text(fn, p)
        return dict(low=lo, high=hi, formula=formula, limits_from='typed' if typed else 'formula' if formula else '')

    def formula_text(self, fn, p):
        """The tolerance STATEMENT that calculates the limits ('0.05 % of reading + 2 counts', with '(minus side: ...)' when the two sides differ), as the
        manual prints it; '' when the row has none.  This is the only place a tolerance is still shown as an error, because it is what is edited."""
        tops = fn.governing(p)
        if tops and self.period in tops[0].exprs:
            e = tops[0]
            text = e.printed.get(self.period) or e.exprs[self.period].printed or e.exprs[self.period].text(fn.unit)
            if self.period in e.exprs_minus:
                text += f'   (minus side: {e.exprs_minus[self.period].printed or e.exprs_minus[self.period].text(fn.unit)})'
            return text
        return ''

    # ---- plain wording for problems
    def plain_problem(self, p, fn=None):
        """One problem of validate() in the words the grid uses (what to do, not which part of the program complained)."""
        code, msg = p['code'], p['message']
        pid = p.get('point_id')
        name = fn.name if fn else 'This section'
        if code == 'no_spec':
            return ('No limits yet: fill in the tolerance boxes in the row panel and press Calc, or type the Low limit and the High limit in the sheet.' if pid
                    else f'{name}: add a test row and give it a tolerance.')
        if code == 'expr_eval':
            low = msg.lower()
            if 'resolution' in low:
                return 'Counts need the resolution: type Meas Res (or Display Decs) in the boxes below and press Calc.'
            if 'full scale' in low:
                return 'A percentage of F.S. needs the range: type the full scale in the F.S. box and press Calc.'
            return msg
        return {
            'no_frequency': 'This function needs a frequency: type it after the value, like 5 V @ 1 kHz.',
            'no_amplitude': 'This function needs the signal level: type it after the value, like 1 kHz, level 1 V.',
            'point_outside_range': 'The value is bigger than the range it is on: type a larger full scale in the F.S. box and press Calc.',
            'nominal_outside_limit': 'The nominal value is outside its own limits: check the tolerance.',
            'dup_point': 'Two rows test exactly the same thing.',
            'limit_open': 'Only one limit is stored for this row (typed earlier): the run needs both. Press Calc to work both limits out from a tolerance, or Clear typed limits.',
            'no_points': f'{name} has no test rows yet (skipped when the sheet runs): click the empty row below it and type a value.',
            'no_make': 'Type the make (manufacturer) in the box at the top.',
            'no_model': 'Type the model in the box at the top.',
            'no_title': 'Type a title in the box at the top (the procedure list shows it).',
            'no_test_rows': 'Nothing to test yet: type a value in the empty row under any section to add its first test row. Sections that stay empty are skipped when the sheet runs.',
            'no_functions': 'Nothing to test yet: click FUNCTION TESTED in the first empty row and choose what the instrument measures or outputs.',
            'no_ranges': f'{name} has no rows yet, so no range either: add a row.',
        }.get(code, msg)

    EMPTY_GROUP_FROM = 2                  # this many empty sections or more: the warnings list shows ONE entry with a count

    def problems(self):
        """validate() as the base class shapes it, minus the 'section has no specification' message of a section whose rows already say so one by one.
        An EMPTY section (no rows yet; a template section nobody filled) has one warning, 'no_points': its 'no ranges' and 'no specification'
        warnings say the same thing and are left out.  They are warnings, never blocking: the run skips an empty section."""
        cached = getattr(self, '_grid_problems', None)
        if cached and cached[0] == self._rev:
            return cached[1]
        out = []
        for p in super().problems():
            fn = self.ds.function(p['function_id']) if p['function_id'] else None
            if p['code'] == 'no_spec' and not p['point_id'] and fn is not None and fn.points:
                continue
            if p['code'] in ('no_spec', 'no_ranges') and p['level'] == 'warn' and fn is not None and not fn.points:
                continue
            out.append(p)
        for fn in self.ds.functions:                         # a row with only one typed limit: the run needs both (the other side is 'open' in the sheet)
            if fn.info.get('passfail'):
                continue
            for pt in fn.points:
                if pt.enabled and any((ov.get('low') in (None, '')) != (ov.get('high') in (None, '')) for ov in pt.overrides.values()):
                    loc = self.locate(pt.id, 'limit_open')
                    out.append(dict(level='error', code='limit_open', message=f'Point {pt.id}: only one limit is stored (typed earlier); use the tolerance calculator (Calc) to give the row both limits.', where=pt.id, step=loc['step'],
                                    function_id=loc['function_id'], range_id=loc['range_id'], point_id=loc['point_id'], spec_index=loc['spec_index'],
                                    location=loc['text']))
        self._grid_problems = (self._rev, out)
        return out

    def empty_section_problems(self):
        """The 'no rows yet' warnings (one per empty section), in sheet order."""
        return [p for p in self.problems() if p['code'] == 'no_points']

    def problem_counts(self):
        """errors / warnings as the pill and the summary count them: all the empty-section warnings together are ONE warning once there are
        EMPTY_GROUP_FROM or more (the same grouping as the warnings list)."""
        ps = self.problems()
        e = sum(p['level'] == 'error' for p in ps)
        w = len(ps) - e
        n = len(self.empty_section_problems())
        if n >= self.EMPTY_GROUP_FROM:
            w -= n - 1
        return dict(errors=e, warnings=w)

    def problem_rows(self):
        """Every problem for the problems window: dict(level, text, row, key, where, code).  Errors first.  The warnings 'section has no rows yet' are
        grouped under ONE entry with a count (it goes to the first empty section) when there are EMPTY_GROUP_FROM or more of them."""
        idx = {r['key']: r['n'] for r in self.rows()}
        out = []
        empties = self.empty_section_problems()
        group = len(empties) >= self.EMPTY_GROUP_FROM
        for p in self.problems():
            fn = self.ds.function(p['function_id']) if p['function_id'] else None
            key = f'p:{fn.id}:{p["point_id"]}' if fn and p['point_id'] and fn.point(p['point_id']) else f'h:{fn.id}' if fn else ''
            if group and p['code'] == 'no_points':
                continue
            out.append(dict(level=p['level'], text=self.plain_problem(p, fn), row=idx.get(key), key=key, where=p['location'] or 'Whole datasheet', code=p['code']))
        if group:
            names = [self.ds.function(p['function_id']).name for p in empties if self.ds.function(p['function_id'])]
            first = f'h:{empties[0]["function_id"]}'
            out.append(dict(level='warn', row=idx.get(first), key=first, where='Empty sections', code='empty_sections',
                            text=f'{len(names)} sections have no test rows yet and are skipped when the sheet runs'
                                 + (': ' + ', '.join(names) + '.' if len(names) <= 4 else f' (first ones: {", ".join(names[:3])}).')))
        out.sort(key=lambda d: d['level'] != 'error')
        return out

    def problem_summary(self):
        c = self.problem_counts()
        if not c['errors'] and not c['warnings']:
            return 'No problems.'
        bits = []
        if c['errors']:
            bits.append(f"{c['errors']} problem{'s' * (c['errors'] != 1)} to fix")
        if c['warnings']:
            bits.append(f"{c['warnings']} warning{'s' * (c['warnings'] != 1)}")
        return ', '.join(bits) + '.'

    # ------------------------------------------------------------------------------------------------------------------ selection and keys
    def select(self, key=None, col=None):
        """Select a cell by row key and column key.  An unknown key keeps the old row; returns the row."""
        rows = self.rows()
        if key is not None and any(r['key'] == key for r in rows):
            self.sel_key = key
        if col in COL_KEYS:
            self.sel_col = col
        i = self.row_index()
        if i is None:                              # the row went away (deleted, undone): stay at the same place on the sheet
            i = min(self._sel_index, len(rows) - 1)
            self.sel_key = rows[i]['key']
        self._sel_index = i
        r = rows[i]
        if r['fid'] and self.ds.function(r['fid']):
            self.fid = r['fid']
        return r

    def select_at(self, r, c):
        """Select by position (what a mouse click gives): row index, column index."""
        rows = self.rows()
        if not 0 <= r < len(rows) or not 0 <= c < len(COL_KEYS):
            return None
        return self.select(rows[r]['key'], COL_KEYS[c])

    def selected_row(self):
        return self.select()

    def _ensure_row(self, i):
        while i >= len(self.rows()):
            self.extra_blank += 1

    def move(self, dr=0, dc=0):
        """Arrow keys.  Moving down from the last row adds an empty row.  Returns the new row."""
        i = max(0, (self.row_index() if self.row_index() is not None else self._sel_index) + dr)
        self._ensure_row(i)
        j = max(0, min(len(COL_KEYS) - 1, COL_KEYS.index(self.sel_col) + dc))
        return self.select(self.rows()[i]['key'], COL_KEYS[j])

    def tab(self, back=False):
        """Tab / Shift+Tab: the next cell you can type in (it skips the As Found, As Left and Out of Tol cells), wrapping to the next row."""
        j = EDIT_COLS.index(self.sel_col) if self.sel_col in EDIT_COLS else (len(EDIT_COLS) - 1 if back else -1)
        if back:
            if j > 0:
                return self.select(col=EDIT_COLS[j - 1])
            if (self.row_index() or 0) > 0:
                self.move(-1)
            return self.select(col=EDIT_COLS[-1])
        if 0 <= j < len(EDIT_COLS) - 1:
            return self.select(col=EDIT_COLS[j + 1])
        if j == -1:                                # from a read-only cell: the first cell you can type in, to its right if there is one
            nxt = next((c for c in EDIT_COLS if COL_KEYS.index(c) > COL_KEYS.index(self.sel_col)), None)
            if nxt:
                return self.select(col=nxt)
        self.move(1)
        return self.select(col=EDIT_COLS[0])

    def nav(self, keysym, shift=False):
        """Keyboard navigation in the sheet.  Returns what the window should do next: 'moved', 'edit' (start editing the cell) or ''."""
        table = {'Up': (-1, 0), 'Down': (1, 0), 'Left': (0, -1), 'Right': (0, 1), 'Prior': (-10, 0), 'Next': (10, 0)}
        if keysym in table:
            self.move(*table[keysym])
            return 'moved'
        if keysym in ('Tab', 'ISO_Left_Tab'):
            self.tab(back=shift or keysym == 'ISO_Left_Tab')
            return 'moved'
        if keysym in ('Home', 'End'):
            self.select(col=COL_KEYS[0] if keysym == 'Home' else COL_KEYS[-1])
            return 'moved'
        if keysym in ('Return', 'KP_Enter', 'F2'):
            return 'edit'
        return ''

    # ------------------------------------------------------------------------------------------------------------------ cells
    def cell_text(self, key=None, col=None):
        """What the Edit Cell bar shows for a cell.  A Low / High limit cell shows its limit (calculated or typed); the tolerance statement that calculates
        it is edited in the row panel and shown by formula_text() / the row's 'formula' field."""
        key, col = key or self.sel_key, col or self.sel_col
        fn, p = self.point_of(key)
        if col == 'function':
            return fn.name if fn else ''
        if col == 'nominal':
            return self.nominal_text(fn, p) if p else ''
        if col in ('low', 'high'):
            if not p or fn.info.get('passfail'):
                return ''
            text = self.limit_cells(fn, p)[col == 'high']
            return '' if text in ('open', 'no limit') else text
        return ''

    def cell_editable(self, key=None, col=None):
        """(ok, why_not) for typing in a cell."""
        key, col = key or self.sel_key, col or self.sel_col
        r = self.row(key)
        if r is None:
            return False, 'No such cell.'
        if col in ('found', 'left', 'oot'):
            return False, 'As Found, As Left and Out of Tol are filled in when the datasheet is used, so they stay blank here.'
        if col == 'step':
            return False, 'Step numbers are worked out from the order of the rows.'
        if col in ('low', 'high'):
            return False, LIMITS_HINT
        if self.locked:
            return False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.'
        if r['kind'] == 'header' and col != 'function':
            return False, 'This is a section heading. Only its name can be changed; click a test row to edit values.'
        return True, ''

    def set_locked(self, locked):
        self.locked = bool(locked)
        return Outcome(True, 'Locked: the sheet cannot be changed.' if self.locked else 'Edit Mode: you can change the sheet.')

    # ---- functions
    def function_choices(self):
        """The list for the 'what does this row test' boxes: the sections already in the sheet, then every kind that can be added as a new section."""
        out = [dict(label=f.name, fid=f.id, kind=f.kind) for f in self.ds.functions]
        out += [dict(label=f'New section: {k["label"]}', fid='', kind=k['kind']) for k in self.kind_choices()]
        return out

    def resolve_function(self, text):
        """What a typed function means: Resolved(fid) for a section already there, Resolved(kind=) for a new one.  DsError says what to type."""
        t = (text or '').strip()
        low = t.lower()
        if not low:
            raise db.DsError('function', 'Choose what this row tests, for example DC volts.')
        for c in self.function_choices():
            if c['label'].lower() == low:
                return Resolved(c['fid'], '' if c['fid'] else c['kind'])
        for f in self.ds.functions:
            if low in (f.name.lower(), f.id.lower()):
                return Resolved(f.id)
        kinds = self.kind_choices()
        for k in kinds:
            if low in (k['kind'].lower(), k['name'].lower(), k['label'].lower()):
                same = next((f for f in self.ds.functions if f.kind == k['kind']), None)
                return Resolved(same.id) if same else Resolved('', k['kind'])
        hits = [f for f in self.ds.functions if low in f.name.lower()]
        khits = [k for k in kinds if low in k['name'].lower()]
        if len(hits) == 1 and not khits or len(hits) == 1 and khits and khits[0]['kind'] == hits[0].kind and len(khits) == 1:
            return Resolved(hits[0].id)
        if not hits and len(khits) == 1:
            return Resolved('', khits[0]['kind'])
        names = [f.name for f in hits] + [k['name'] for k in khits if not any(f.kind == k['kind'] for f in hits)]
        if names:
            raise db.DsError('function', f'"{t}" could mean {", ".join(names[:4])}: type a little more of the name.')
        raise db.DsError('function', f'"{t}" is not something the builder can test. Pick one from the list, for example DC volts, AC volts, 2-wire ohms, Frequency.')

    def _function_for(self, res):
        """The Function for a Resolved (adding a section when it is a new kind).  Call inside _do."""
        if res.fid:
            return self.ds.function(res.fid)
        return self._new_section(res.kind)

    def _new_section(self, kind):
        fn = self.ds.add_function(kind)
        for key, _label, _choices, default in SETTING_FIELDS.get(kind, []):
            fn.settings[key] = default
        fn.switch = fn.info.get('switch', '')
        return fn

    def set_target_function(self, text):
        """The function box under the sheet while an empty row is selected: where the next new row goes."""
        def act():
            fn = self._function_for(self.resolve_function(text))
            self.fid = fn.id
            return f'New rows go under {fn.name}. Type a value in the NOMINAL VALUE cell.'
        return self._do('choose function', act)

    # ---- the cell edit gate
    def commit_cell(self, text, key=None, col=None, move='down'):
        """Enter in the Edit Cell bar: put `text` in the cell.  After a good edit the selection moves on: down (a row you just made in an empty row
        goes to the next empty row), right, or stays.  Returns an Outcome."""
        key, col = key or self.sel_key, col or self.sel_col
        res = self.edit_cell(key, col, text)
        if res.ok:
            self._after_edit(key, col, res, move)
        return res

    def _after_edit(self, key, col, res, move):
        newkey = res.detail if isinstance(res.detail, str) and res.detail[:2] in ('p:', 'h:') and self.row(res.detail) else key
        if self.row(newkey) is None:
            newkey = self.rows()[min(self._sel_index, len(self.rows()) - 1)]['key']
        if move == 'down':
            if key.startswith(('b:', 'e:')):
                nxt = next((r for r in self.rows() if r['kind'] == 'blank'), None)
                self.select(nxt['key'] if nxt else newkey, col)
            else:
                self.select(newkey, col)
                self.move(1, 0)
        elif move == 'right':
            self.select(newkey, col)
            self.tab()
        else:
            self.select(newkey, col)

    def edit_cell(self, key, col, text):
        """Change one cell.  One undo step.  Outcome.detail is the key of the row that was changed or created."""
        ok, why = self.cell_editable(key, col)
        if not ok:
            return Outcome(False, why)
        r = self.row(key)
        text = (text or '').strip()
        fn, p = self.point_of(key)
        if r['kind'] == 'header':
            return self._rename_section(fn, text)
        if r['kind'] == 'blank':
            if not text:
                return Outcome(True, 'Nothing typed.')
            if col == 'function':
                return self.set_target_function(text)
            return self._create_from_text(text)
        if col == 'function':
            return self.move_point(key, text) if text else Outcome(False, 'A row has to test something. Choose a function, or delete the row.')
        if col == 'nominal':
            return self.clear_row(key) if not text else self._edit_nominal(fn, p, text)
        return Outcome(False, 'That cell cannot be edited.')

    def clear_cell(self, key=None, col=None):
        """The Delete key: nominal clears the whole row; the limit cells are read-only (cell_editable says so); function does nothing."""
        key, col = key or self.sel_key, col or self.sel_col
        ok, why = self.cell_editable(key, col)
        if not ok:
            return Outcome(False, why)
        r = self.row(key)
        if r['kind'] == 'blank':
            return Outcome(True, 'Nothing to clear.')
        if r['kind'] == 'header':
            return Outcome(False, 'To remove a whole section use Delete row on its heading (its rows go too; Undo brings them back).')
        if col == 'nominal':
            return self.clear_row(key)
        return Outcome(False, 'The function of a row cannot be cleared: choose another function instead.')

    def _rename_section(self, fn, text):
        if not text:
            return Outcome(False, 'A section needs a name.')
        res = self.set_function(fn.id, name=text)
        if res.ok:
            res.message, res.detail = f'Section renamed to "{text}".', f'h:{fn.id}'
        return res

    # ---- rows
    def _pick_range(self, fn, value, want_fs=None):
        """The range a value goes on: a typed full scale, else the smallest range that holds it, else a new decade range (10 mV, 100 mV, 1 V, 10 V ...).
        Returns (range, 'what was added' or '')."""
        if want_fs is not None:
            rng = next((r for r in fn.ranges if r.full_scale == want_fs), None)
            if rng:
                return rng, ''
            rng = fn.add_range(want_fs)
            return rng, f'The {self.range_text(fn, rng)} range was added.'
        rng = fn.range_for(value)
        if rng is not None:
            return rng, ''
        v = abs(db.dec(value))
        if v == 0:
            fs = db.D(1)
        else:
            e = v.adjusted()
            fs = db.D(10) ** e if v == db.D(10) ** e else db.D(10) ** (e + 1)
        rng = next((r for r in fn.ranges if r.full_scale == fs), None) or fn.add_range(fs)
        return rng, f'The {self.range_text(fn, rng)} range was added for it (change it with the F.S. box).'

    def _find_duplicate(self, fn, value, freq, amp, range_id=None):
        f = db.parse_quantity(freq, 'Hz') if isinstance(freq, str) and freq else freq
        a = db.parse_quantity(amp) if isinstance(amp, str) and amp else amp
        for q in fn.points:
            if q.nominal == db.dec(value) and _same(q.frequency, f) and _same(q.amplitude, a) and (range_id is None or q.range_id == range_id):
                return q
        return None

    def _row_number(self, fn, p):
        r = self.row(f'p:{fn.id}:{p.id}')
        return r['n'] if r else 0

    def _copy_spec_from_neighbour(self, fn, p):
        """A new row starts with the tolerance of the nearest row above it in the section (rows of one function usually share one), else of the first
        row below.  Returns True when it got one."""
        i = fn.points.index(p)
        src = next((q for q in reversed(fn.points[:i]) if q.spec is not None), None) or next((q for q in fn.points[i + 1:] if q.spec is not None), None)
        if src is None:
            return False
        p.spec = copy_spec(src.spec)
        return True

    def _create_point(self, fn, nominal, freq=None, amp=None, want_fs=None, inherit=True):
        """Add a test point to a function.  Call inside _do.  Returns (point, notes[])."""
        value = db.parse_quantity(nominal, fn.unit or None) if isinstance(nominal, str) else db.dec(nominal)
        rng, note = self._pick_range(fn, value, want_fs)
        dup = self._find_duplicate(fn, value, freq, amp, rng.id)
        if dup is not None:
            raise db.DsError('dup_point', f'There is already a row for that: row {self._row_number(fn, dup)}.')
        p = db.add_point(fn, value, rng.id, freq or None, amp or None)
        notes = [note] if note else []
        if inherit and not fn.info.get('passfail') and self._copy_spec_from_neighbour(fn, p):
            notes.append('It starts with the tolerance of the nearest row in this section (change it in the boxes below).')
        return p, notes

    def _create_from_text(self, text):
        box = {}

        def act():
            fn = self.target_function()
            if fn is None:
                raise db.DsError('function', 'Choose what this row tests first: use the function box under the sheet, or type it in FUNCTION TESTED.')
            parts = self.parse_nominal(fn, text, self.bare_unit(fn))
            p, notes = self._create_point(fn, parts['nominal'], parts['frequency'], parts['amplitude'])
            self.fid = fn.id
            box['key'] = f'p:{fn.id}:{p.id}'
            return Outcome(True, f'Row added to {fn.name}. ' + ' '.join(notes), box['key'])
        res = self._do('add row', act)
        res.message = res.message.strip()
        return res

    def _edit_nominal(self, fn, p, text):
        pid = p.id

        def act():
            parts = self.parse_nominal(fn, text, self.bare_unit(fn, fn.point(pid)))
            value = db.parse_quantity(parts['nominal'], fn.unit or None)
            q = self._find_duplicate(fn, value, parts['frequency'], parts['amplitude'])
            if q is not None and q.id != pid:
                raise db.DsError('dup_point', f'There is already a row for that: row {self._row_number(fn, q)}.')
            cur = fn.point(pid)
            rng, note = fn.range(cur.range_id), ''
            if rng is None or not self._holds(fn, rng, value):
                rng, note = self._pick_range(fn, value)
            db.edit_point(fn, pid, nominal=parts['nominal'], frequency=parts['frequency'] or '', amplitude=parts['amplitude'] or '', range_id=rng.id)
            return Outcome(True, ('Value changed.' + (' ' + note if note else '') + (' The tolerance follows the new value.' if cur.spec is not None else '')),
                           f'p:{fn.id}:{pid}')
        return self._do('edit cell', act)

    @staticmethod
    def _holds(fn, rng, value):
        info = fn.info
        if info['unit'] in ('dB', ''):
            return True
        if info.get('value'):
            return 0 < abs(value) <= rng.top
        return rng.holds(value)

    def clear_row(self, key=None):
        """Delete the test point of a row (the Delete key on the NOMINAL VALUE cell, or the Delete row button); on a heading, the whole section."""
        key = key or self.sel_key
        fn, p = self.point_of(key)
        r = self.row(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if r is None or r['kind'] == 'blank':
            return Outcome(False, 'This row is empty already.')
        if r['kind'] == 'header':
            return self.remove_function(fn.id)
        res = self.remove_point(fn.id, p.id)
        if res.ok:
            res.message = 'Row deleted. Undo brings it back.'
        return res

    def move_point(self, key, text):
        """Change the function of a row: it moves to the section you name (a new section when none of that kind is there yet).  Only to a function in
        the same unit, because the value and the tolerance are in that unit."""
        fn, p = self.point_of(key)

        def act():
            target = self._function_for(self.resolve_function(text))
            if target.id == fn.id:
                return Outcome(True, 'It is in that section already.', key)
            if target.unit != fn.unit:
                raise db.DsError('function', f'{target.name} works in {db.unit_symbol(target.unit) or "no unit"} and this row is in {db.unit_symbol(fn.unit) or "no unit"}. '
                                 'Add a new row under that function instead.')
            q, _notes = self._create_point(target, p.nominal, p.frequency, p.amplitude, inherit=False)
            q.spec, q.overrides, q.note, q.label, q.enabled = p.spec, p.overrides, p.note, p.label, p.enabled
            q.settings = dict(p.settings)
            q.edited = True
            if p.id in self.ds.assignments:
                self.ds.assignments[q.id] = self.ds.assignments.pop(p.id)
            db.remove_point(fn, p.id)
            self.fid = target.id
            return Outcome(True, f'Moved to {target.name}.' + (f' {fn.name} has no rows left.' if not fn.points else ''), f'p:{target.id}:{q.id}')
        return self._do('move row', act)

    def add_section(self, text, after_key=None):
        """Ins. Header: a new section (a function) after the selected row's section.  `text` names the function or kind."""
        def act():
            res = self.resolve_function(text)
            kind = self.ds.function(res.fid).kind if res.fid else res.kind          # an existing name again means 'another section like it'
            fn = self._new_section(kind)
            r = self.row(after_key or self.sel_key)
            after = self.ds.function(r['fid']) if r and r['fid'] else None
            if after is not None and after is not fn:
                fs = self.ds.functions
                fs.remove(fn)
                fs.insert(fs.index(after) + 1, fn)
            self.fid = fn.id
            return Outcome(True, f'Section "{fn.name}" added. Click the empty row under it and type a value.', f'h:{fn.id}')
        return self._do('add section', act)

    # ---- handheld multimeter template (a starting set of sections; the sheet itself still starts blank)
    HANDHELD_KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'CONT', 'CAP', 'FREQ', 'TEMP', 'DIODE')

    def handheld_template(self):
        """[dict(kind, name, present)]: the handheld multimeter functions the builder can start a sheet with, and whether the sheet has one already."""
        have = {f.kind for f in self.ds.functions}
        return [dict(kind=k, name=db.KINDS[k]['name'], present=k in have) for k in self.HANDHELD_KINDS]

    def add_handheld_functions(self, kinds=None):
        """Add one empty section per handheld multimeter function (DC / AC volts, DC / AC current, resistance, continuity, capacitance, frequency,
        temperature, diode) that the sheet does not have yet.  Built from the builder's own function catalogue (the same sections 'New section' makes);
        nothing is copied from a vendor spec.  Ranges come with the rows you type (each row finds or makes its range).  One undo step."""
        want = [k for k in (kinds or self.HANDHELD_KINDS) if k in self.HANDHELD_KINDS]
        box = {}

        def act():
            have = {f.kind for f in self.ds.functions}
            made = [self._new_section(k) for k in want if k not in have]
            if not made:
                raise db.DsError('template', 'The sheet already has a section for every handheld function.')
            box['first'] = made[0].id
            return Outcome(True, f'Added {len(made)} section(s): ' + ', '.join(f.name for f in made) + '. Click the empty row under a section and type a value to add its rows.', f'h:{made[0].id}')
        res = self._do('add handheld functions', act)
        if res.ok and box.get('first'):
            self.fid = box['first']
        return res

    # ---- what the suite can automate (for the Run buttons)
    def automation_counts(self, compute=True):
        """dict(points, ok, unverified, by_hand, uncovered) from the standards matcher, or None when it cannot be worked out yet (problems in the sheet, no
        points, standards not loadable).  `compute=False` only reads a match that is already fresh."""
        if not self.match_fresh():
            if not compute or self.problem_counts()['errors']:
                return None
            if not self.run_match().ok:
                return None
        t = self.match_summary()['total']
        if not t['points']:
            return None
        return dict(points=t['points'], ok=t['automatable'] - t['unverified'], unverified=t['unverified'], uncovered=t['uncovered'],
                    by_hand=t['points'] - t['automatable'] - t['uncovered'])

    def automation_line(self, compute=True):
        """One sentence: how many points the suite runs by itself, how many have unverified commands, how many are set by hand."""
        c = self.automation_counts(compute)
        if c is None:
            return 'Automation: not worked out yet (fix the warnings first, or add some rows).'
        parts = [f'{c["ok"]} run automatically']
        if c['unverified']:
            parts.append(f'{c["unverified"]} run automatically but their commands are not yet verified on hardware')
        if c['by_hand']:
            parts.append(f'{c["by_hand"]} set by hand')
        if c['uncovered']:
            parts.append(f'{c["uncovered"]} not covered by any standard')
        return f'Automation, of {c["points"]} points: ' + '; '.join(parts) + '.'

    # ---- limit cells
    def _build_entry(self, fn, p, plus_text, minus_text=''):
        """The point's own SpecEntry with `plus_text` (and `minus_text` for an asymmetric tolerance) for the period on show; periods the point has no
        text for yet get the same text, so a datasheet with several periods stays complete."""
        old = p.spec
        exprs = dict(old.exprs) if old else {}
        minus = dict(old.exprs_minus) if old else {}
        printed = dict(old.printed) if old else {}
        per = self.period
        exprs[per], printed[per] = db.parse_expr(plus_text, fn.unit), plus_text
        if minus_text:
            minus[per] = db.parse_expr(minus_text, fn.unit)
        else:
            minus.pop(per, None)
        for other in self.ds.period_ids():
            if other not in exprs:
                exprs[other], printed[other] = exprs[per], plus_text
                if minus_text:
                    minus[other] = minus[per]
        return db.SpecEntry(exprs, None, None, None, minus, printed, 'both', None)

    def _set_spec(self, fn, p, plus_text, minus_text=''):
        p.spec = self._build_entry(fn, p, plus_text, minus_text)
        p.overrides.pop(self.period, None)                   # typed limits would win over the statement: the new statement replaces them
        p.edited = True

    def clear_typed_limits(self, key=None):
        """Drop the stored Low / High pair of the row for the period on show (an old sheet may still hold one; the Builder no longer writes them).  The
        limits then come from the row's tolerance statement; with none they are empty until the tolerance calculator (Calc) gives the row one.  One undo
        step.  The pairs of the other periods are not touched."""
        key = key or self.sel_key
        fn, p = self.point_of(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if p is None or self.typed_limits(p) is None:
            return Outcome(False, 'This row has no typed limits.')
        pid = p.id

        def act():
            q = fn.point(pid)
            q.overrides.pop(self.period, None)
            q.edited = True
            shown = self.limits_display(fn, q)
            return Outcome(True, 'Typed limits cleared. ' + (f'Now {shown}.' if shown else 'The row has no tolerance yet: use the tolerance calculator and press Calc.'),
                           f'p:{fn.id}:{pid}')
        return self._do('clear typed limits', act)

    # ------------------------------------------------------------------------------------------------------------------ the boxes under the sheet
    @staticmethod
    def blank_side():
        return dict(iv='', iv_ppm=False, fs='', floor='', db='', calc='')

    def blank_form(self, fn=None):
        """What the boxes show for a new row: % of I.V. ticked, symmetric, one test point, Auto Res on."""
        return dict(types=['iv'], plus=self.blank_side(), minus=self.blank_side(), asym=False, operand='+', fs_scale='', nominal='', low='', high='',
                    units=self.typing_unit(fn) if fn else '', freq='', level='', expect='on', multi=False, multi_mode='span', multi_high='', multi_n='5',
                    decs='', res='', auto_res=True, remark='', run=True)

    def _side_from_expr(self, fn, expr):
        """(types, side dict) for an expression the boxes can show (one term of each kind at most), else None."""
        side, types = self.blank_side(), []
        for t in expr.items:
            if isinstance(t, db.Expr):
                return None
            slot = {'pct_reading': 'iv', 'ppm_reading': 'iv', 'pct_range': 'fs', 'abs': 'floor'}.get(t.kind) or ('db' if t.kind == 'db' and t.basis == 'amplitude' else None)
            if slot is None or slot in types:
                return None
            types.append(slot)
            if slot == 'iv':
                side['iv'], side['iv_ppm'] = db.fmt(t.value), t.kind == 'ppm_reading'
            elif slot == 'floor':
                side['floor'] = db.format_si(t.value, fn.unit)
            else:
                side[slot] = db.fmt(t.value)
        return (types, side) if expr.op == 'sum' else None

    def _form_from_spec(self, fn, p, form):
        """Fill the spec part of the boxes from the point's own specification (or the function's table, shown in Calculator)."""
        per = self.period
        e = p.spec
        if e is None:
            tops = fn.governing(p)
            e = tops[0] if tops else None
        if e is None or per not in e.exprs:
            return form
        plus = e.exprs[per]
        minus = e.exprs_minus.get(per)
        ps = self._side_from_expr(fn, plus)
        ms = self._side_from_expr(fn, minus) if minus is not None else None
        if ps is not None and (minus is None or ms is not None):
            form['types'] = [t for t in SPEC_ORDER if t in set(ps[0]) | set(ms[0] if ms else ())]
            form['plus'] = ps[1]
            if ms:
                form['minus'], form['asym'] = ms[1], True
            return form
        form['types'] = ['calc']
        form['plus']['calc'] = (e.printed.get(per) or plus.printed or plus.text(fn.unit)).lstrip('±').strip()
        if minus is not None:
            form['minus']['calc'] = (minus.printed or minus.text(fn.unit)).lstrip('±').strip()
            form['asym'] = True
        return form

    def panel_state(self, key=None):
        """Everything the boxes under the sheet show for a row: the function, the unit choices, which fields apply, and the form filled from the row."""
        key = key or self.sel_key
        r = self.row(key) or self.selected_row()
        fn, p = self.point_of(r['key'])
        if fn is None and r['kind'] == 'blank':
            fn = self.target_function()
        st = dict(key=r['key'], kind=r['kind'], fid=fn.id if fn else '', function=fn.name if fn else '', unit=fn.unit if fn else '', symbol=db.unit_symbol(fn.unit) if fn else '',
                  unit_choices=unit_choices(fn.unit) if fn else [], passfail=bool(fn and fn.info.get('passfail')), note='',
                  fields=dict(frequency=bool(fn and (fn.info.get('ac') or fn.info['family'] == 'generator' or fn.info.get('value'))),
                              amplitude=bool(fn and fn.info.get('amplitude')), expect=bool(fn and fn.kind == 'CONT')),
                  new_row=r['kind'] == 'blank', can_edit=not self.locked and r['kind'] != 'header', typed_limits=False)
        form = self.blank_form(fn)
        if r['kind'] == 'header':
            st['note'] = 'This is a section heading. Click a test row to see and change its tolerance.'
        elif fn is None:
            st['note'] = 'Choose what this row tests (the function box), then type the value to test.'
        if p is not None:
            rng = fn.range(p.range_id)
            num, units = split_unit_text(self.fmt_value(fn, rng, p.nominal))
            form.update(nominal=num, units=units or form['units'], freq=db.format_si(p.frequency, 'Hz') if p.frequency is not None else '',
                        level=db.format_si(p.amplitude, 'V') if p.amplitude is not None else '', expect=p.settings.get('expect', 'on'), remark=p.note, run=p.enabled,
                        fs_scale=self.fmt_value(fn, rng, rng.full_scale) if rng else '')
            if rng is not None and rng.resolution:
                pre = prefix_of_units(form['units'], fn.unit)
                with db.localcontext() as c:
                    c.prec = db.PREC
                    form['decs'] = str(_decimals_of(rng.resolution / db.D(10) ** dict(db._PREFIX_ORDER)[pre]))
                    form['res'] = self.fmt_value(fn, rng, rng.resolution, pre)
            if not st['passfail']:
                self._form_from_spec(fn, p, form)
                lo_t, hi_t = self.limit_cells(fn, p)                      # the Low / High limit boxes: always read-only displays of the calculated limits
                form.update(low='' if lo_t in ('open', 'no limit') else lo_t, high='' if hi_t in ('open', 'no limit') else hi_t)
                st['typed_limits'] = self.typed_limits(p) is not None
                if p.spec is not None and not st['typed_limits'] and self.formula_text(fn, p):
                    st['note'] = f'Limits calculated from: {self.formula_text(fn, p)}. Change it in the row panel and press Calc.'
                if p.spec is None and fn.governing(p):
                    st['note'] = 'This row follows the specification table (More > Specification table). Press Calc to give it a tolerance of its own.'
                if st['typed_limits']:
                    st['note'] = TYPED_LIMITS_NOTE
        elif r['kind'] == 'blank' and fn is not None:
            st['note'] = f'New row in {fn.name}.'
        st['form'] = form
        return st

    # ---- building the tolerance from the boxes
    def side_text(self, fn, side, types, units):
        """The accuracy statement the ticked boxes make: '0.05 % of reading + 0.01 % of range + 20 µV'.  DsError says which box is empty."""
        parts = []
        for t in SPEC_ORDER:
            if t not in types:
                continue
            v = str(side.get(t) or '').strip()
            if not v:
                raise db.DsError('spec_value', f'Type the {SPEC_LABEL[t]} value, or untick it.')
            if t == 'iv':
                parts.append(f'{re.sub(r"%|ppm", "", v, flags=re.I).strip()} {"ppm" if side.get("iv_ppm") else "%"} of reading')
            elif t == 'fs':
                parts.append(f'{v.replace("%", "").strip()} % of range')
            elif t == 'floor':
                parts.append(with_units(v, units))
            elif t == 'db':
                parts.append(f'{re.sub(r"dB", "", v, flags=re.I).strip()} dB')
            else:
                parts.append(v.lstrip('±').strip())
        if not parts:
            raise db.DsError('spec_type', 'Tick at least one tolerance type (% of reading, % of range, Floor, ± dB or Calculator), then fill in its box.')
        return ' + '.join(parts)

    def form_spec_texts(self, fn, form):
        """(plus text, minus text or '') from the form."""
        types = [t for t in form.get('types', []) if t in SPEC_ORDER]
        units = form.get('units') or db.unit_symbol(fn.unit)
        plus = self.side_text(fn, form['plus'], types, units)
        minus = self.side_text(fn, form['minus'], types, units) if form.get('asym') else ''
        return plus, minus

    def _resolution_from_form(self, fn, form, units, nominal_text):
        """The resolution (SI) the Meas Res / Display Decs / Auto Res boxes ask for, or None to leave the range as it is."""
        if form.get('auto_res', True):
            decs = str(form.get('decs') or '').strip()
            if not decs:
                num = split_unit_text(nominal_text)[0]
                decs = str(len(num.split('.')[1])) if '.' in num else ''
            if not decs:
                return None
            if not decs.isdigit():
                raise db.DsError('number', 'Display Decs must be a whole number of decimal places, for example 3.')
            unit_text = split_unit_text(nominal_text)[1] or units
            return resolution_from_decimals(prefix_of_units(unit_text, fn.unit), int(decs))
        text = with_units(str(form.get('res') or ''), units)
        return db.parse_quantity(text, fn.unit or None) if text else None

    def _apply_row(self, fn, p, form, want_fs):
        """Apply the boxes to an existing point: value, range, resolution, tolerance, remark, run flag.  Call inside _do."""
        units = form.get('units') or db.unit_symbol(fn.unit)
        nominal_text = with_units(form.get('nominal', ''), units)
        parts = self.parse_nominal(fn, ' @ '.join(x for x in (nominal_text, with_units(form.get('freq', ''), 'Hz') if str(form.get('freq', '')).strip() else '') if x)
                                   + (f', level {form["level"]}' if str(form.get('level', '')).strip() else ''))
        value = db.parse_quantity(parts['nominal'], fn.unit or None)
        q = self._find_duplicate(fn, value, parts['frequency'], parts['amplitude'])
        if q is not None and q is not p:
            raise db.DsError('dup_point', f'There is already a row for that: row {self._row_number(fn, q)}.')
        rng = fn.range(p.range_id)
        note = ''
        if want_fs is not None and (rng is None or rng.full_scale != want_fs):
            rng, note = self._pick_range(fn, value, want_fs)
        elif rng is None or not self._holds(fn, rng, value):
            rng, note = self._pick_range(fn, value)
        db.edit_point(fn, p.id, nominal=parts['nominal'], frequency=parts['frequency'] or '', amplitude=parts['amplitude'] or '', range_id=rng.id)
        res = self._resolution_from_form(fn, form, units, nominal_text)
        if res is not None:
            rng.resolution = res
        if fn.kind == 'CONT':
            p.settings['expect'] = form.get('expect') or 'on'
        p.note = str(form.get('remark', '')).strip()
        p.enabled = bool(form.get('run', True))
        p.edited = True
        msg = note
        if not fn.info.get('passfail'):
            had_typed = self.typed_limits(p) is not None
            plus, minus = self.form_spec_texts(fn, form)
            self._set_spec(fn, p, plus, minus)                    # the new statement replaces any stored typed Low / High pair of the period
            if had_typed:
                note = ('The typed limits of this row were replaced by the calculated ones. ' + note).strip()
            info = db.point_limits(self.ds, fn, p, self.period)
            if info.get('error'):
                raise db.DsError('tol', info['error'])
            msg = f'{info["accept"]}. {self.limits_display(fn, p)}. {note}'.strip()
        return msg

    @staticmethod
    def _want_fs(fn, form, units):
        if 'fs' not in form.get('types', []) or not str(form.get('fs_scale') or '').strip():
            return None
        return db.parse_quantity(with_units(str(form['fs_scale']), units), fn.unit or None)

    def calc_row(self, key=None, form=None):
        """Calc: apply the boxes under the sheet to the selected row (a row that does not exist yet is created from them) and work out its tolerance.
        One undo step; on any problem nothing changes and the message says what to type."""
        key = key or self.sel_key
        r = self.row(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if r is None or r['kind'] == 'header':
            return Outcome(False, 'Click a test row, or an empty row, first.')
        if form is None:
            form = self.panel_state(key)['form']
        if form.get('multi'):
            return self._calc_multi(key, form)
        box = {}

        def act():
            fn, p = self.point_of(key)
            if r['kind'] == 'blank':
                fn = self.ds.function(r['fid']) if r['fid'] else self.target_function()
                if fn is None:
                    raise db.DsError('function', 'Choose what this row tests first: use the function box above the spec boxes.')
                if not str(form.get('nominal', '')).strip():
                    raise db.DsError('nominal', 'Type the Nominal Value (the value to test) first.')
                units = form.get('units') or db.unit_symbol(fn.unit)
                parts = self.parse_nominal(fn, ' @ '.join(x for x in (with_units(form['nominal'], units), with_units(form.get('freq', ''), 'Hz') if str(form.get('freq', '')).strip() else '') if x)
                                           + (f', level {form["level"]}' if str(form.get('level', '')).strip() else ''))
                p, notes = self._create_point(fn, parts['nominal'], parts['frequency'], parts['amplitude'], self._want_fs(fn, form, units), inherit=False)
                self.fid = fn.id
            units = form.get('units') or db.unit_symbol(fn.unit)
            msg = self._apply_row(fn, p, form, self._want_fs(fn, form, units))
            box['key'] = f'p:{fn.id}:{p.id}'
            return Outcome(True, f'Row calculated: {msg}'.strip() if msg else 'Row saved.', box['key'])
        res = self._do('calc row', act)
        if res.ok:
            self.select(res.detail)
        return res

    # ---- multiple test points
    def multi_values(self, fn, form):
        """The values 'Multiple Test Points' makes, exact Decimals: Nominal Value is the low end; High and n come from the boxes.  DsError when it cannot."""
        units = form.get('units') or db.unit_symbol(fn.unit)
        low = db.parse_quantity(with_units(str(form.get('nominal', '')), units), fn.unit or None)
        high_text = str(form.get('multi_high', '')).strip()
        if not high_text:
            raise db.DsError('multi', 'Type the High value: the last value the rows should reach.')
        high = db.parse_quantity(with_units(high_text, units), fn.unit or None)
        if high <= low:
            raise db.DsError('multi', 'High must be above the Nominal Value.')
        n_text = str(form.get('multi_n', '')).strip()
        mode = form.get('multi_mode', 'span')
        if not n_text:
            raise db.DsError('multi', 'Type n: how many points (Lo to High), or the size of the step.')
        with db.localcontext() as c:
            c.prec = db.PREC
            if mode == 'span':
                if not n_text.isdigit() or int(n_text) < 2:
                    raise db.DsError('multi', 'For Lo to High, n is the number of points: a whole number of 2 or more.')
                if int(n_text) > MAX_MULTI:
                    raise db.DsError('multi', f'That would make {n_text} rows; {MAX_MULTI} is the most at once.')
                values = db._steps_linear(low, high, count=int(n_text))
            else:
                n = db.dec(re.sub(r'[%a-z\s]', '', n_text, flags=re.I) if mode in ('pct', 'ppm') else n_text, 'n')
                if mode == 'units':
                    step = db.parse_quantity(with_units(n_text, units), fn.unit or None)
                elif mode == 'pct':
                    step = high * n / 100
                else:
                    step = high * n / 1000000
                if step <= 0:
                    raise db.DsError('multi', 'n must be above zero.')
                if (high - low) / step > MAX_MULTI:
                    raise db.DsError('multi', f'That step would make more than {MAX_MULTI} rows. Use a bigger step.')
                values = db._steps_linear(low, high, step=step)
        return values

    def _calc_multi(self, key, form):
        def act():
            r = self.row(key)
            fn = self.ds.function(r['fid']) if r['fid'] else self.target_function()
            if fn is None:
                raise db.DsError('function', 'Choose what these rows test first: use the function box above the spec boxes.')
            units = form.get('units') or db.unit_symbol(fn.unit)
            values = self.multi_values(fn, form)
            freq = with_units(form.get('freq', ''), 'Hz') if str(form.get('freq', '')).strip() else None
            level = str(form.get('level', '')).strip() or None
            plus = minus = ''
            if not fn.info.get('passfail'):
                plus, minus = self.form_spec_texts(fn, form)
            want_fs = self._want_fs(fn, form, units)
            made, existed = [], 0
            for v in values:
                try:
                    p, _notes = self._create_point(fn, v, freq, level, want_fs, inherit=False)
                except db.DsError as exc:
                    if exc.code == 'dup_point':
                        existed += 1
                        continue
                    raise
                made.append(p)
            if not made:
                raise db.DsError('multi', 'Every one of those rows is already on the sheet.')
            res = self._resolution_from_form(fn, form, units, with_units(str(form.get('nominal', '')), units))
            for p in made:
                if res is not None:
                    fn.range(p.range_id).resolution = res
                if fn.kind == 'CONT':
                    p.settings['expect'] = form.get('expect') or 'on'
                if plus:
                    self._set_spec(fn, p, plus, minus)
                    info = db.point_limits(self.ds, fn, p, self.period)
                    if info.get('error'):
                        raise db.DsError('tol', info['error'])
            self.fid = fn.id
            first = made[0]
            return Outcome(True, f'{len(made)} rows added to {fn.name}' + (f' ({existed} already on the sheet, left alone)' if existed else '') + '. Each has the tolerance from the boxes.' if plus
                           else f'{len(made)} rows added to {fn.name}.', f'p:{fn.id}:{first.id}')
        res = self._do('add test points', act)
        if res.ok:
            self.select(res.detail)
        return res

    # ---- the other buttons
    def recalc_all(self):
        """Recalc: run the test point calculator rules again and check every row.  Tolerances are always worked out from the row's spec, so they are
        up to date already; this also tells you which rows still have a problem."""
        res = self.recalculate()
        if not res.ok:
            return res
        bad = [r for r in self.rows() if r['kind'] == 'point' and r['level'] == 'error']
        n = sum(1 for r in self.rows() if r['kind'] == 'point')
        text = f'{res.message} Checked {n} row{"s" * (n != 1)}: ' + (f'{len(bad)} still need attention (rows {", ".join(str(r["n"]) for r in bad[:8])}{" ..." if len(bad) > 8 else ""}).' if bad else 'all fine.')
        return Outcome(True, text)

    def copy_tolerance(self, key=None, scope='below'):
        """Copy the tolerance of a row to the rows under it in the same section ('below'), or only to those that have none ('missing')."""
        key = key or self.sel_key
        fn, p = self.point_of(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if p is None:
            return Outcome(False, 'Click a test row that has a tolerance first.')
        if p.spec is None:
            return Outcome(False, 'This row has no tolerance statement of its own to copy (its limits are typed, or it has none). Press Calc first.')

        def act():
            q0 = fn.point(p.id)
            i = fn.points.index(q0)
            n = 0
            for q in fn.points[i + 1:]:
                has = q.spec is not None or fn.spec_for(q.range_id, q.frequency)[1] or any(v not in (None, '') for ov in q.overrides.values() for v in ov.values())
                if scope == 'missing' and has:
                    continue
                q.spec = copy_spec(q0.spec)
                if scope != 'missing':
                    q.overrides.clear()
                q.edited = True
                n += 1
            if not n:
                raise db.DsError('copy', 'There are no rows below this one in the section' + (' without a tolerance.' if scope == 'missing' else '.'))
            return Outcome(True, f'The tolerance was copied to {n} row{"s" * (n != 1)} below.', key)
        return self._do('copy tolerance', act)

    def would_overwrite(self, key=None):
        """How many rows below the selected one already have a tolerance of their own (the window asks before copying over them)."""
        fn, p = self.point_of(key or self.sel_key)
        if p is None:
            return 0
        i = fn.points.index(p)
        return sum(1 for q in fn.points[i + 1:] if q.spec is not None or any(v not in (None, '') for ov in q.overrides.values() for v in ov.values()))

    def set_remark(self, key, text):
        fn, p = self.point_of(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if p is None:
            return Outcome(False, 'Click a test row first.')

        def act():
            q = fn.point(p.id)
            q.note = (text or '').strip()
            q.edited = True
            return 'Remark saved: the operator sees it with this row.' if q.note else 'Remark removed.'
        return self._do('row remark', act)

    def set_run(self, key, run):
        fn, p = self.point_of(key)
        if self.locked:
            return Outcome(False, 'The sheet is locked. Switch Lock Status to Edit Mode to change it.')
        if p is None:
            return Outcome(False, 'Click a test row first.')
        return self.set_point_enabled(fn.id, p.id, run)

    def symbol_text(self, name, key=None):
        """What a symbol button inserts: the symbol itself, or for 'Units' the unit symbol of the selected row's function."""
        if name != 'Units':
            return name
        r = self.row(key)
        fn = self.ds.function(r['fid']) if r and r['fid'] else self.target_function()
        return db.unit_symbol(fn.unit) if fn else ''

    def definition_rows(self, fid=None):
        """The 'Test Point Definitions' list: the calculator rules of the section (each makes rows by itself), as 'label: what it makes'."""
        fid = fid or self.fid
        return [dict(id=r['id'], label=f'{r["label"]}: {r["text"]}' + ('' if r['enabled'] else ' (off)')) for r in self.rule_rows(fid)] if self.ds.function(fid) else []

    # ---- messages in the grid's words
    def add_function(self, kind, name='', direction=None):
        res = super().add_function(kind, name, direction)
        if res.ok:
            res.message = f'Added the section "{self.fn().name}". Click the empty row under it and type a value.'
            self.select(f'e:{res.detail}', 'nominal')      # the cursor goes to the empty row directly under the new heading (it used to stay on a spare row two lines down)
        return res

    def add_rule(self, fid, form, rule_id=None):
        fn = self.ds.function(fid or self.fid)
        if fn is not None and not fn.ranges:
            return Outcome(False, 'This section has no ranges yet. Add a test row first (its range follows from its value), or open More > Ranges.')
        return super().add_rule(fid, form, rule_id)

    def run_match(self, period=None):
        errs = [p for p in self.problems() if p['level'] == 'error']
        if errs:
            first = errs[0]
            fn = self.ds.function(first['function_id']) if first['function_id'] else None
            return Outcome(False, f'Fix the {len(errs)} problem{"s" * (len(errs) != 1)} on the sheet first: the limits must be known before a standard can be chosen. '
                                  f'{self.plain_problem(first, fn)}', errs)
        return super().run_match(period)

    def add_period(self, pid, label=''):
        """A new time period: every row that has its own tolerance gets the same text for it (change it with the Period box)."""
        n = len(self._undo)
        res = super().add_period(pid, label)
        if not res.ok:
            return res
        before = self._undo[-1] if len(self._undo) > n else None

        def act():
            k = 0
            for fn in self.ds.functions:
                for p in fn.points:
                    e = p.spec
                    if e is not None and pid not in e.exprs and self.ds.default_period in e.exprs:
                        e.exprs[pid], e.printed[pid] = e.exprs[self.ds.default_period], e.printed.get(self.ds.default_period, '')
                        if self.ds.default_period in e.exprs_minus:
                            e.exprs_minus[pid] = e.exprs_minus[self.ds.default_period]
                        k += 1
            return f'Period added. {k} row{"s" * (k != 1)} kept the same tolerance for it; change it per period with the Period box.' if k else res.message
        more = self._do('add period', act)
        if before is not None and len(self._undo) == n + 2:         # one Undo takes back both steps
            self._undo[-1] = (before[0], before[1])
            del self._undo[-2]
        return more

    # ---- save
    def save_sheet(self, note='', as_draft=False):
        """Save a new version.  With problems it is refused unless as_draft; the message says how many and what to do."""
        counts = self.problem_counts()
        if counts['errors'] and not as_draft:
            first = next(p for p in self.problems() if p['level'] == 'error')
            fn = self.ds.function(first['function_id']) if first['function_id'] else None
            return Outcome(False, f'{counts["errors"]} problem{"s" * (counts["errors"] != 1)} to fix before this can run as a procedure. First one: {self.plain_problem(first, fn)} '
                                  'You can still save it as a draft.', dict(needs_draft=True))
        return self.save(note, as_draft=as_draft)

    # ------------------------------------------------------------------------------------------------------------------ print / preview
    def print_view(self):
        """The blank datasheet as it would print: dict(title, subtitle, columns, rows).  As Found / As Left / Out of Tol stay empty (it is a template)."""
        ds = self.ds
        cols = [c['title'] for c in GRID_COLUMNS]
        rows = []
        for r in self.rows():
            if r['kind'] == 'header':
                rows.append(dict(kind='header', cells=[r['function']] + [''] * (len(cols) - 1)))
            elif r['kind'] == 'point':
                rows.append(dict(kind='point', cells=[r['step'].replace(' *', ''), r['function'], r['nominal'], '', '', '', r['low'], r['high']]))
        per = next((p.label or p.id for p in ds.periods if p.id == self.period), self.period)
        return dict(title=' '.join(x for x in (ds.make, ds.model) if x) or 'Datasheet', subtitle=f'{ds.title}  |  tolerances for {per}' if ds.title else f'tolerances for {per}',
                    columns=cols, rows=rows, notice='BLANK DATASHEET TEMPLATE. It is not a calibration record: the As Found and As Left columns are empty.')

    def write_sheet_pdf(self, path):
        """Write print_view() as a PDF (reportlab).  Returns an Outcome."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            import report_pdf
        except ImportError:
            return Outcome(False, 'Printing needs the reportlab package (py -m pip install reportlab).')
        view = self.print_view()
        regular, bold, embedded = report_pdf._fonts()

        def txt(s):
            s = str(s)
            return s if embedded else report_pdf.ascii_unit(s).replace('µ', 'u').replace('±', '+/-')
        try:
            doc = SimpleDocTemplate(str(path), pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                                    title=txt(view['title']))
            h1 = ParagraphStyle('h1', fontName=bold, fontSize=15, leading=18)
            small = ParagraphStyle('s', fontName=regular, fontSize=9, leading=11)
            warn = ParagraphStyle('w', fontName=bold, fontSize=9, leading=11, textColor=colors.HexColor('#9A5B00'))
            cell = ParagraphStyle('c', fontName=regular, fontSize=9, leading=11)
            head = ParagraphStyle('hd', fontName=bold, fontSize=8, leading=10, alignment=1)
            data = [[Paragraph(txt(c), head) for c in view['columns']]]
            style = [('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EDEDF2')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]
            for i, row in enumerate(view['rows'], 1):
                data.append([Paragraph(txt(c), ParagraphStyle('b', parent=cell, fontName=bold) if row['kind'] == 'header' else cell) for c in row['cells']])
                if row['kind'] == 'header':
                    style += [('SPAN', (0, i), (-1, i)), ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F5F5F7'))]
            widths = [0.7 * inch, 2.2 * inch, 1.7 * inch, 1.2 * inch, 1.2 * inch, 0.6 * inch, 2.4 * inch]
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle(style))
            doc.build([Paragraph(txt(view['title']), h1), Paragraph(txt(view['subtitle']), small), Paragraph(txt(view['notice']), warn), Spacer(1, 8), table])
        except OSError as exc:
            return Outcome(False, f'The PDF could not be written ({exc}).')
        return Outcome(True, f'Blank datasheet saved to {path}.')
