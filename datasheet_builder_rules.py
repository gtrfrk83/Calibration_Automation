"""Datasheet Builder: the BUILD-TIME rules (1-5 of 'Two-way datasheet rules', NOTES.md).  Read only; no tkinter at import; the instruments are never touched.

    import datasheet_builder_rules as rules
    chk = rules.check(ds, period=None, matcher=None, match=None, dry_run=True)          # SheetCheck
    chk.findings            -> [Finding(rule, level 'error'|'warn'|'info', code, text, fix, function_id, point_ids, ...)]   errors block 'ready', warnings do not
    chk.errors() / .warnings() / .counts() / .by_rule()
    chk.sources             -> {point id: UncertaintySource(text, has_source, level)}                (rule 5, shown in the point inspector and in the check)
    chk.unverified          -> [UnverifiedUse(standard, key, name, wire, why, ref, point_ids)]      (rule 2: the pre-run list the operator accepts)
    chk.fingerprint()       -> short text that changes when that list changes (the run skips its own question when the Builder passed it)
    rules.blocking_problems(ds) -> [DsProblem ...] the error findings, for datasheet_builder.save(): a sheet with one is saved as a draft, not 'ready'
    rules.make_check_row(ds, function_id, point_id)  -> moves a point whose unit does not fit into a flagged pass / fail section (rule 3 fix)
    rules.manual_entry_for(ds, finding)              -> the rule 1 fix: those points use the operator's own standard (ds.assignments[pid] = 'MANUAL')

THE RULES (what each function does):
  1  COVERAGE      from the standards matcher (datasheet_builder_match): a point no standard sheet covers is a WARNING that offers manual entry; a point the author
                   ASSIGNED to a calibrator that cannot make it is an ERROR (their choice is wrong).  A point the dry run cannot route to its assigned standard
                   (dsb_runtime.limit_problem, e.g. the leveled-sine limits) is a warning too.
  2  UNVERIFIED    every command the run would send, from the dry run of rule 4 (procmods_plan.Recorder on the simulated bench): a command whose registry entry is not
                   `verified` or has no manual page `ref` is listed.  Build time: warnings.  The block is at run time (dsb_runtime.main asks, real runs only).
  3  UNITS / KINDS a unit text (range label, point label, amplitude unit, printed accuracy) that is unknown or does not fit the function is an ERROR (never converted);
                   the fix is to correct it or to make the row a flagged pass / fail check (make_check_row).
  4  DRY RUN       every point is run on the SIMULATED bench with the real driver code (dsb_runtime.DsbIO + drivers/simulated*.py).  A command the simulated driver does
                   not know (or the error queue rejects as a command error) is an ERROR.  Anything else that stops a point (a limit of the simulation) is a warning.
                   Without tkinter (dsb_runtime cannot be imported) the dry run is skipped and the check says so.
  5  UNCERTAINTY   per point: the standards sheet the uncertainty comes from, or 'none: blank'.  Never zero.  Mirrors what the report prints (dsb_runtime.certificate_row).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import datasheet_builder as db
from datasheet_builder import KINDS

RULE_TITLES = {1: 'Calibrator coverage', 2: 'Unverified commands', 3: 'Units and kinds', 4: 'Dry run on the simulated bench', 5: 'Uncertainty source'}
ERROR, WARN, INFO = 'error', 'warn', 'info'
MAX_LISTED = 4                  # points named in a finding's text before it says 'and n more'
SOURCE_MODELS = ('5560A', '5522A', '5520A')
NO_UNCERTAINTY_FAMILIES = ('scope', 'generator')       # dsb_runtime.decorate sets no_uncertainty for these and for FREQ / PERIOD
NO_UNCERTAINTY_KINDS = ('FREQ', 'PERIOD')
UNIT_CHECKED_FAMILIES = ('dmm',)
UNIT_FREE_KINDS = ('FREQ', 'PERIOD')                   # their labels mix a frequency and a level


# ============================================================================================================== results
@dataclass
class Finding:
    rule: int
    level: str
    code: str
    text: str
    fix: str = ''
    function_id: str = ''
    point_ids: tuple = ()
    section: str = ''
    row: str = ''                  # e.g. 'DC volts, 10 V range, 5 V'
    action: str = ''               # '' | 'manual_entry' | 'make_check': what 'Apply the fix' does
    count: int = 1

    @property
    def point_id(self):
        return self.point_ids[0] if self.point_ids else ''

    @property
    def key(self):
        """The grid row key the finding goes to ('p:<function>:<point>', or the section heading 'h:<function>', or '')."""
        if self.function_id and self.point_ids:
            return f'p:{self.function_id}:{self.point_ids[0]}'
        return f'h:{self.function_id}' if self.function_id else ''

    @property
    def title(self):
        return f'Rule {self.rule}: {RULE_TITLES.get(self.rule, "")}'

    def to_problem(self):
        return db.DsProblem(f'rule{self.rule}_{self.code}', f'{self.title}. {self.text}' + (f' {self.fix}' if self.fix else ''),
                            'error' if self.level == ERROR else 'warn', self.point_ids[0] if self.point_ids else self.function_id or 'datasheet')


@dataclass
class UncertaintySource:
    point_id: str
    text: str                      # 'Fluke 5560A standards sheet (DC voltage / 11 V range)' | 'none: blank (...)'
    has_source: bool
    level: str = 'ok'              # ok | info | warn
    standard: str = ''


@dataclass
class UnverifiedUse:
    standard: str                  # the instrument label in the dry run ('5560A', '5790B', ...)
    driver: str
    key: str                       # registry key ('' = a command that is not in the registry)
    name: str
    wire: str                      # one example as sent
    why: str                       # 'not verified on hardware' | 'no manual page reference' | 'not in the command registry'
    ref: str = ''
    point_ids: list = field(default_factory=list)

    def line(self):
        n = len(self.point_ids)
        return f'{self.standard}: {self.name or self.key or "command"} ({self.wire}) - {self.why}; {n} point{"s" * (n != 1)}' if n else \
               f'{self.standard}: {self.name or self.key or "command"} ({self.wire}) - {self.why}'


@dataclass
class PointRun:
    point_id: str
    function_id: str = ''
    standard: str = ''
    status: str = 'ok'             # ok | unsupported | stopped | manual | skipped
    error: str = ''
    reason: str = ''               # why the point is not routed to its assigned standard / set by hand
    commands: list = field(default_factory=list)


@dataclass
class DryRun:
    available: bool = False
    reason: str = ''               # why it did not run
    points: dict = field(default_factory=dict)
    ran: int = 0
    registries: dict = field(default_factory=dict)     # driver class name -> its merged command registry


@dataclass
class SheetCheck:
    findings: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    unverified: list = field(default_factory=list)
    dry: DryRun = field(default_factory=DryRun)
    period: str = ''
    notes: list = field(default_factory=list)

    def errors(self):
        return [f for f in self.findings if f.level == ERROR]

    def warnings(self):
        return [f for f in self.findings if f.level == WARN]

    def counts(self):
        return dict(errors=len(self.errors()), warnings=len(self.warnings()), info=sum(f.level == INFO for f in self.findings))

    @property
    def ok(self):
        return not self.errors()

    def by_rule(self):
        out = {}
        for f in self.findings:
            out.setdefault(f.rule, []).append(f)
        return out

    def unverified_points(self):
        return sorted({pid for u in self.unverified for pid in u.point_ids})

    def fingerprint(self):
        """Changes when the list of unverified commands changes (driver, command key and reason; not the values or the number of points)."""
        text = '|'.join(sorted(f'{u.driver}:{u.key}:{u.why}' for u in self.unverified))
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16] if text else ''

    def summary(self):
        c = self.counts()
        if not c['errors'] and not c['warnings']:
            return 'Sheet check: no problems.'
        bits = []
        if c['errors']:
            bits.append(f"{c['errors']} to fix")
        if c['warnings']:
            bits.append(f"{c['warnings']} warning{'s' * (c['warnings'] != 1)}")
        return 'Sheet check: ' + ', '.join(bits) + '.'

    def pre_run_lines(self):
        return [u.line() for u in self.unverified]

    def save_summary(self):
        """What save() stores in the runnable spec (dsb.engine.check) so the Manager's list can say it without running the check again."""
        c = self.counts()
        return dict(errors=c['errors'], warnings=c['warnings'], unverified_commands=len(self.unverified), unverified_points=len(self.unverified_points()),
                    dry_run=bool(self.dry.available), fingerprint=self.fingerprint())


# ============================================================================================================== helpers
def point_text(fn, p):
    try:
        rng = fn.range(p.range_id)
        where = f'{fn.name}, {rng.label or db.format_si(rng.full_scale, fn.unit)} range, ' if rng else f'{fn.name}, '
        text = where + db.format_si(p.nominal, fn.unit)
        if p.frequency is not None and fn.kind not in ('FREQ', 'PERIOD'):
            text += f' @ {db.format_si(p.frequency, "Hz")}'
        return text
    except Exception:
        return f'{fn.name}, {p.id}'


def _names(rows, limit=MAX_LISTED):
    rows = list(rows)
    return '; '.join(rows[:limit]) + (f'; and {len(rows) - limit} more' if len(rows) > limit else '')


_QTY = re.compile('^\\s*[+-]?(?:\\d+(?:[.,]\\d*)?|[.]\\d+)(?:[eE][+-]?\\d+)?\\s*(?P<unit>[A-Za-z\u00b5\u03bc\u03a9\u2126\u00b0%]+)?')


_EXTRA_ALIASES = [('Ohms', 'ohm'), ('Ohm', 'ohm'), ('OHMS', 'ohm'), ('OHM', 'ohm'), ('Siemens', 'S'), ('mho', 'S')]


def text_unit(text):
    """('none', '') no quantity at the start; ('bare', '') a number with no unit; ('ok', base unit) a unit this program knows; ('unknown', word) a unit it does not.
    A trailing rms / pp / dc / ac on a volt or amp unit is ignored ('Vrms', 'mVpp')."""
    text = re.sub(r'^\s*[+-]?(?:\d+[.,]?\d*|[.]\d+)\s+to\s+', '', str(text or ''))        # 'a to b unit' (a printed range): the unit is after b
    m = _QTY.match(text)
    if not m:
        return 'none', ''
    word = (m.group('unit') or '').strip()
    if not word:
        return 'bare', ''
    cand = [word]
    stripped = re.sub(r'(rms|pp|dc|ac|p)$', '', word, flags=re.I)
    if stripped and stripped != word:
        cand.append(stripped)
    for w in cand:
        for alias, base in list(db._UNIT_ALIASES) + _EXTRA_ALIASES:
            if w.endswith(alias):
                prefix = w[:-len(alias)].strip()
                if prefix == 'K':
                    prefix = 'k'
                if prefix in db._PREFIXES and (prefix == '' or base not in db._NO_PREFIX):
                    return 'ok', base
        try:                                                    # the Cal Processor import's own unit reader (Vpp, Ohm, Ohms ...)
            import mdd_convert
            known = mdd_convert.parse_unit(w)
        except Exception:
            known = None
        if known is not None:
            return 'ok', known[1]
    return 'unknown', word


# ============================================================================================================== rule 3: units and kinds
def unit_findings(ds):
    """Rule 3.  Pure data check of the unit texts a sheet carries: range labels and point labels of multimeter functions, the amplitude unit of generator
    functions, and the absolute units printed in an accuracy statement."""
    out = []
    for fn in ds.functions:
        info = KINDS.get(fn.kind)
        if info is None:
            continue
        unit = info['unit']
        # (a) the amplitude unit of a generator level: the section's, then any point of its own
        if fn.kind in ('GEN_AMPL', 'GEN_FLAT'):
            from datasheet_builder_match import _rms_factor
            owners = [('the section', fn.settings, ())] + [(point_text(fn, p), p.settings, (p.id,)) for p in fn.points if p.settings.get('amp_unit')]
            for where, s, pids in owners:
                au = s.get('amp_unit')
                if au is None:
                    continue
                wave = {**fn.settings, **s}.get('waveform', 'SIN')
                if au not in ('Vrms', 'Vpp', 'Vp'):
                    out.append(Finding(3, ERROR, 'unit_unknown', f'{fn.name}: the amplitude unit {au!r} ({where}) is not one this program knows (Vrms, Vpp, Vp).',
                                       'Pick Vrms, Vpp or Vp for the amplitude; it is never converted by guessing.', fn.id, pids, fn.name, where))
                elif str(wave).upper() != 'DC' and _rms_factor(wave, au) is None:
                    out.append(Finding(3, ERROR, 'unit_mismatch', f'{fn.name}: a {wave} wave with the amplitude in {au} cannot be converted to a level a standard can read.',
                                       'Use a sine or square wave with Vrms, Vpp or Vp, or test this by hand.', fn.id, pids, fn.name, where))
        if info['family'] not in UNIT_CHECKED_FAMILIES or info.get('passfail') or fn.kind in UNIT_FREE_KINDS or not unit:
            continue
        shown = lambda base: db.unit_symbol(base)
        # (b) range labels
        for rng in fn.ranges:
            if not rng.label:
                continue
            st, base = text_unit(rng.label)
            if st == 'unknown':
                out.append(Finding(3, ERROR, 'unit_unknown', f'{fn.name}: the range label "{rng.label}" has a unit ({base}) that is not known.',
                                   f'Write the range with {shown(unit)} (for example "20 {shown(unit)}") or clear the label.', fn.id, (), fn.name, rng.label))
            elif st == 'ok' and base != unit:
                out.append(Finding(3, ERROR, 'unit_mismatch', f'{fn.name}: the range label "{rng.label}" is in {shown(base)} but this section tests {shown(unit)}.',
                                   f'Correct the unit of the label to {shown(unit)}, or move the rows to the right section.', fn.id, (), fn.name, rng.label))
        # (c) point labels (the source document's own text for the nominal)
        bad = []
        for p in fn.points:
            if not p.label or not p.enabled:
                continue
            st, base = text_unit(p.label)
            if st == 'unknown' or (st == 'ok' and base != unit):
                bad.append((p, st, base))
        for p, st, base in bad:
            row = point_text(fn, p)
            what = (f'its label "{p.label}" has a unit ({base}) that is not known' if st == 'unknown' else
                    f'its label "{p.label}" is in {shown(base)} but this section tests {shown(unit)}')
            out.append(Finding(3, ERROR, 'unit_unknown' if st == 'unknown' else 'unit_mismatch', f'{row}: {what}. The value is not converted.',
                               'Correct the unit, or press "Apply the fix" to make this row a flagged pass / fail check that is answered Yes / No.',
                               fn.id, (p.id,), fn.name, row, action='make_check'))
        # (d) absolute units in a printed accuracy statement (warning: the maths uses the typed numbers in the function's unit)
        seen = set()
        for e in fn.spec + [p.spec for p in fn.points if p.spec is not None]:
            for per, text in (e.printed or {}).items():
                for m in re.finditer('(?<![A-Za-z])(\\d[\\d.]*)\\s*([pn\u00b5\u03bcumkKM]?)(V|A|\u03a9|\u2126|ohms?|F|Hz|s|S)(?![A-Za-z])', text or ''):
                    base = {'\u03a9': 'ohm', '\u2126': 'ohm', 'ohms': 'ohm'}.get(m.group(3), m.group(3))
                    if base != unit and (text, base) not in seen:
                        seen.add((text, base))
                        out.append(Finding(3, WARN, 'unit_mismatch', f'{fn.name}: the accuracy statement "{text}" has a fixed term in {shown(base)} but this section tests {shown(unit)}.',
                                           'Check the statement against the manual; a term in another unit is not converted.', fn.id, (), fn.name, text))
    return out


def make_check_row(ds, function_id, point_id):
    """The rule 3 fix: the point leaves its section and becomes a flagged pass / fail check (the Cal Processor import does the same for a point it cannot read).  The
    original text stays on the row, the note says why, no value is converted or kept as a measurement.  Returns the new point."""
    fn = ds.function(function_id)
    p = fn.point(point_id) if fn else None
    if p is None:
        raise db.DsError('no_point', f'No point {point_id}.')
    cid = f'{fn.id}_check'
    target = ds.function(cid)
    if target is None:
        target = ds.add_function('CHECK', f'{fn.name} (unit to check)', id=cid, settings={'source': 'unit-check'})
        target.add_range(1, id='r1', settings={'unspecified': True})
    n = len(target.points) + 1
    q = db.Point(f'{cid}.p{n:04d}', 'r1', 0, label=p.label, origin='rules:unit', note=(p.note + ' ' if p.note else '') + f'Unit not accepted ("{p.label}"); '
                 f'check by hand and answer Yes / No.')
    target.points.append(q)
    fn.points.remove(p)
    if p.id in ds.assignments:
        ds.assignments[q.id] = ds.assignments.pop(p.id)
    ds.assignments[q.id] = 'MANUAL'
    return q


def manual_entry_for(ds, finding):
    """The rule 1 fix: the points of `finding` are set and read by the operator with their own standard.  Returns the number of points changed."""
    n = 0
    for pid in finding.point_ids:
        if ds.assignments.get(pid) != 'MANUAL':
            ds.assignments[pid] = 'MANUAL'
            n += 1
    return n


# ============================================================================================================== rules 1 and 5 (from the matcher)
def _find(ds, pid):
    for fn, p in ds.all_points():
        if p.id == pid:
            return fn, p
    return None, None


def coverage_findings(ds, res):
    """Rule 1."""
    out = []
    if ds.options.get('manual_entry') or res is None:
        return out
    by_fn = {}
    for a in res.assignments.values():
        if a.status != 'uncovered':
            continue
        by_fn.setdefault((a.function_id, a.overridden), []).append(a)
    for (fid, overridden), alist in by_fn.items():
        fn = ds.function(fid)
        name = fn.name if fn else fid
        rows = []
        for a in alist:
            f2, p = _find(ds, a.point_id)
            rows.append(f'{point_text(f2, p) if p else a.point_id} ({a.message or a.reason})')
        who = 'calibrator' if alist[0].direction == 'measure' else 'measuring standard'
        pids = tuple(a.point_id for a in alist)
        if overridden:
            out.append(Finding(1, ERROR, 'chosen_cannot', f'{len(alist)} point{"s" * (len(alist) != 1)} in {name} use a {who} that cannot make {"them" if len(alist) != 1 else "it"}: '
                               + _names(rows), 'Choose another standard for the row in Standards and automation, or press "Apply the fix" to enter it by hand.',
                               fid, pids, name, rows[0], action='manual_entry', count=len(alist)))
        else:
            out.append(Finding(1, WARN, 'not_covered', f'{len(alist)} point{"s" * (len(alist) != 1)} in {name} {"are" if len(alist) != 1 else "is"} outside every {who} range and standards sheet: '
                               + _names(rows), 'Press "Apply the fix" to enter it by hand (the operator uses their own standard), or import a standards sheet that covers it.',
                               fid, pids, name, rows[0], action='manual_entry', count=len(alist)))
    return out


def _no_uncertainty_kind(fn):
    info = KINDS[fn.kind]
    return info['family'] in NO_UNCERTAINTY_FAMILIES or fn.kind in NO_UNCERTAINTY_KINDS


def uncertainty_source(ds, fn, p, a, manual_sheet=False):
    """Rule 5 for one point from its matcher assignment `a` (None when there is none)."""
    if manual_sheet:
        return UncertaintySource(p.id, 'none: blank (manual calibration: nothing is sourced, so no standard gives an uncertainty)', False, INFO)
    if _no_uncertainty_kind(fn):
        return UncertaintySource(p.id, f'none: blank ({fn.name} rows carry no uncertainty in the report)', False, INFO)
    if a is None:
        return UncertaintySource(p.id, 'none: blank (not worked out yet)', False, INFO)
    if a.status == 'manual':
        return UncertaintySource(p.id, 'none: blank (set by hand: no standard sheet is used)', False, WARN)
    if a.status == 'uncovered':
        return UncertaintySource(p.id, 'none: blank (no standards sheet covers this point)', False, WARN)
    cand = next((c for c in a.candidates if c.standard == a.standard and c.covered), None)
    if a.uncertainty is None or not a.uncertainty > 0:
        why = 'it has no specification sheet imported' if cand is not None and not cand.spec_known else 'its sheet gives no usable uncertainty here'
        return UncertaintySource(p.id, f'none: blank ({a.standard}: {why})', False, WARN, a.standard)
    row = f' ({cand.row})' if cand is not None and cand.row else ''
    return UncertaintySource(p.id, f'{a.standard} standards sheet{row}', True, 'ok', a.standard)


def source_findings(ds, res, manual_sheet):
    """Rule 5: (sources {point id: UncertaintySource}, findings).  A point with no source is called out; many in one section are one finding."""
    sources, out, none = {}, [], {}
    for fn, p in ds.all_points():
        if not p.enabled:
            continue
        a = res.assignments.get(p.id) if res is not None else None
        s = uncertainty_source(ds, fn, p, a, manual_sheet)
        sources[p.id] = s
        if s.level == WARN:
            none.setdefault(fn.id, []).append((fn, p, s))
    if manual_sheet and sources:
        out.append(Finding(5, INFO, 'manual_sheet', 'This is a manual calibration: no uncertainty is taken from a standards sheet, the uncertainty column stays blank on every row.', '', '', (), '', ''))
    for fid, items in none.items():
        fn = items[0][0]
        rows = [f'{point_text(fn, p)} {s.text[len("none: blank"):].strip()}' for _f, p, s in items]
        out.append(Finding(5, WARN, 'no_source', f'{len(items)} point{"s" * (len(items) != 1)} in {fn.name} {"have" if len(items) != 1 else "has"} no uncertainty source, so the uncertainty stays blank (never zero): '
                           + _names(rows), 'Pick a standard whose sheet covers the point, or accept that the report leaves the uncertainty blank.',
                           fid, tuple(p.id for _f, p, _s in items), fn.name, rows[0], count=len(items)))
    return sources, out


# ============================================================================================================== rule 4 (and the command list of rule 2): the dry run
def _command_error(exc):
    msg = f'{type(exc).__name__}: {exc}'
    low = msg.lower()
    return 'unknown command' in low or 'undefined header' in low or bool(re.search(r'(^|[^0-9])-1\d\d\s*,', msg))


def _runner_modules():
    """The runtime modules the dry run needs.  They import tkinter: where it is missing (a test environment without it) the dry run is skipped."""
    import dsb_runtime as rt
    import procmods_plan
    from drivers.simulated import SimFlukeTransport, make_bench
    from drivers.simulated_fgen import make_fgen_bench
    return rt, procmods_plan, SimFlukeTransport, make_bench, make_fgen_bench


def dry_run(ds, res, period=None, runner=None):
    """Rule 4: run every enabled point on the simulated bench with the real DsbIO and drivers.  `runner` replaces the module loader (tests).  Never raises."""
    import datasheet_builder_specs as dsp
    out = DryRun()
    if ds.options.get('manual_entry'):
        out.reason = 'manual calibration: nothing is driven'
        return out
    if db.errors(db.validate(ds)):
        out.reason = 'the sheet has problems to fix first'
        return out
    try:
        rt, plan_mod, SimFluke, make_bench, make_fgen = (runner or _runner_modules)()
    except Exception as exc:                                      # no tkinter here, or the runtime cannot be loaded
        out.reason = f'the runtime could not be loaded ({type(exc).__name__}: {exc})'
        return out
    try:
        exp = dsp.export_spec(ds, period=period, plan=res)
        if exp.spec is None:
            out.reason = 'the sheet cannot be exported yet'
            return out
        pts = rt.runtime_points(exp.spec)
    except Exception as exc:
        out.reason = f'the points could not be prepared ({type(exc).__name__}: {exc})'
        return out
    scope = any(p['run']['op'].startswith('scope') for p in pts)
    every = set(SOURCE_MODELS) | {'5790B', '53131A', '53132A'}
    routes = {id(p): rt.route_for(p, every) for p in pts}             # which standard each point would use if all of them were connected
    need = {r.standard for r in routes.values() if r.auto}
    try:
        bench, _a, _b = make_bench()
        fbench, ft = make_fgen('33220A')
        src = rt.DsbIO({}, transports={m: SimFluke(bench, m) for m in SOURCE_MODELS if m in need}, scope=scope) if need & set(SOURCE_MODELS) else None
        std_t = {m: (ft['std'] if m == '5790B' else ft['counter']) for m in need if m in ('5790B', '53131A', '53132A')}
        std = rt.DsbIO({}, transports=std_t) if std_t else None
    except Exception as exc:
        out.reason = f'the simulated bench could not be opened ({type(exc).__name__}: {exc})'
        return out
    rec = plan_mod.Recorder()
    registries = {}
    for io in (src, std):
        for d in (io.pm_drivers() if io is not None else ()):
            rec.attach(d)
            registries[type(d).__name__] = d._registry()
    refs = {}
    out.available = True
    with plan_mod.dry_clock():
        for p in pts:
            run = p['run']
            pid = (p.get('dsb') or {}).get('point_id') or p['id']
            pr = PointRun(pid, (p.get('dsb') or {}).get('function', ''))
            out.points[pid] = pr
            route = routes[id(p)]
            pr.standard = route.standard
            n0 = len(rec.entries)
            if not route.auto:
                pr.status, pr.reason = 'manual', route.reason or 'set by hand'
                continue
            if route.reason:
                pr.reason = route.reason
            q = dict(p)
            q['_route'] = route
            io = src if route.standard in SOURCE_MODELS else std
            try:
                if run['direction'] == 'measure':
                    io.apply(q)
                else:
                    if run['op'] == 'std_flat' and io.flat_key(q) not in refs:
                        _prime_bench(rt, fbench, run, route.standard, run.get('reference_hz'))
                        v, _raw = io.read_reference(dict(q), route)
                        refs[io.flat_key(q)] = v
                    _prime_bench(rt, fbench, run, route.standard)
                    io.measure(q, route, refs)
                pr.status = 'ok'
            except Exception as exc:
                pr.error = f'{type(exc).__name__}: {exc}'
                pr.status = 'unsupported' if _command_error(exc) else 'stopped'
            finally:
                try:
                    if src is not None:
                        src.standby()
                except Exception:
                    pass
            pr.commands = rec.entries[n0:]
            out.ran += 1
    out.registries = registries
    return out


def _prime_bench(rt, fbench, run, model, freq=None):
    """Make the simulated generator put out something the measuring standard can read (the value is not judged here, only the commands)."""
    freq = float(freq or run.get('frequency') or (run.get('nominal') if run['kind'] in ('GEN_FREQ', 'FREQ') else None) or 1000.0)
    level = abs(run.get('amplitude') or run.get('nominal') or 1.0) if run['kind'] in ('GEN_FLAT', 'GEN_AMPL') else 1.0
    try:
        level = level * rt.rms_factor(run)
    except Exception:
        pass
    fbench.gen.update(on=True, func='SIN', freq=freq, amp=max(level, 1e-3), unit='VRMS', load=1e40, offs=0.0)
    fbench.connected = 'counter' if model in ('53131A', '53132A') else ('wbnd' if freq > 1e6 else 'std')
    if model in ('53131A', '53132A'):
        fbench.counter_model = model


def unverified_uses(dry):
    """Rule 2: the commands the dry run recorded whose registry entry is not verified, or has no manual page reference, or is not in the registry."""
    uses = {}
    for pid, pr in dry.points.items():
        for e in pr.commands:
            reg = (getattr(dry, 'registries', {}) or {}).get(e.driver) or {}
            cmd = reg.get(e.key) if e.key else None
            if cmd is not None and cmd.verified and (cmd.ref or '').strip():
                continue
            if e.key is None:
                why = 'not in the command registry'
            elif not e.verified:
                why = 'not verified on hardware'
            else:
                why = 'no manual page reference'
            ident = (e.driver, e.key or e.wire.split()[0])
            u = uses.setdefault(ident, UnverifiedUse(e.label, e.driver, e.key or '', e.name or e.key or e.wire.split()[0], e.wire, why, getattr(cmd, 'ref', '') or ''))
            if pid not in u.point_ids:
                u.point_ids.append(pid)
    return sorted(uses.values(), key=lambda u: (u.standard, u.name))


def capability_uses(ds, res):
    """Rule 2 when there is no dry run: the driver table's coarse 'unverified' (one entry per standard and function, no command text)."""
    uses = {}
    if res is None:
        return []
    for a in res.assignments.values():
        if a.status == 'assigned' and a.automation == 'unverified':
            u = uses.setdefault((a.standard, a.kind), UnverifiedUse(a.standard, a.driver, '', f'{a.kind} output', a.automation_note or '', 'not verified on hardware'))
            u.point_ids.append(a.point_id)
    return sorted(uses.values(), key=lambda u: (u.standard, u.name))


def dry_findings(ds, res, dry):
    out = []
    if not dry.available:
        if dry.reason and dry.reason not in ('manual calibration: nothing is driven',):
            out.append(Finding(4, INFO, 'not_run', f'The dry run on the simulated bench did not run: {dry.reason}.',
                               'It runs when the sheet has no problems and the program can start the simulated instruments.'))
        return out
    bad = {}
    for pid, pr in dry.points.items():
        if pr.status in ('unsupported', 'stopped'):
            bad.setdefault((pr.function_id, pr.status), []).append(pr)
    for (fid, status), prs in bad.items():
        fn = ds.function(fid)
        name = fn.name if fn else fid
        rows = []
        for pr in prs:
            f2, p = _find(ds, pr.point_id)
            rows.append(f'{point_text(f2, p) if p else pr.point_id} ({pr.error.split(": ", 1)[-1][:110]})')
        pids = tuple(pr.point_id for pr in prs)
        if status == 'unsupported':
            out.append(Finding(4, ERROR, 'unsupported_command', f'{len(prs)} point{"s" * (len(prs) != 1)} in {name} send a command the simulated instrument does not support: '
                               + _names(rows), 'The sheet cannot be marked ready. Pick another standard for these rows, set them by hand, or add the command to the simulated driver.',
                               fid, pids, name, rows[0], count=len(prs)))
        else:
            out.append(Finding(4, WARN, 'dry_run_stopped', f'{len(prs)} point{"s" * (len(prs) != 1)} in {name} could not be run to the end on the simulated bench: '
                               + _names(rows), 'The simulation may not model this (it is not a rejected command). Try the sheet in demo and read the messages.',
                               fid, pids, name, rows[0], count=len(prs)))
    # a point that will not use the standard the sheet assigned (rule 1 at run time)
    sub = {}
    for pid, pr in dry.points.items():
        a = res.assignments.get(pid) if res is not None else None
        if a is not None and a.status == 'assigned' and (pr.status == 'manual' or (pr.standard and pr.standard != a.standard)):
            sub.setdefault(pr.function_id, []).append((pr, a))
    for fid, items in sub.items():
        fn = ds.function(fid)
        name = fn.name if fn else fid
        rows = []
        for pr, a in items:
            f2, p = _find(ds, pr.point_id)
            rows.append(f'{point_text(f2, p) if p else pr.point_id} ({pr.reason or a.standard + " is not used"})')
        out.append(Finding(1, WARN, 'not_on_assigned', f'{len(items)} point{"s" * (len(items) != 1)} in {name} will not run on the assigned standard: ' + _names(rows),
                           'Press "Apply the fix" to enter it by hand, or choose a standard that can make the point.', fid, tuple(pr.point_id for pr, _a in items), name, rows[0],
                           action='manual_entry', count=len(items)))
    return out


def unverified_findings(ds, uses, from_dry):
    """One warning per standard (the full list is `SheetCheck.unverified`, shown by 'Commands to accept')."""
    out = []
    by_std = {}
    for u in uses:
        by_std.setdefault(u.standard, []).append(u)
    for std, items in by_std.items():
        pids = sorted({pid for u in items for pid in u.point_ids})
        names = [u.name for u in items]
        fn, p = _find(ds, pids[0]) if pids else (None, None)
        what = f'{len(items)} command{"s" * (len(items) != 1)} {"are" if len(items) != 1 else "is"} not verified on hardware or not tied to a manual page'
        out.append(Finding(2, WARN, 'unverified_command', f'{std}: {what} ({_names(names, 5)}); {len(pids)} point{"s" * (len(pids) != 1)} use{"s" * (len(pids) == 1)} '
                           f'{"them" if len(items) != 1 else "it"}.' if from_dry else
                           f'{std}: the commands for {_names(names, 5)} are not verified on hardware; {len(pids)} point{"s" * (len(pids) != 1)} use them.',
                           'A real run lists them first and the operator must accept the list. To remove the warning, confirm the commands on the instrument and mark them '
                           'verified (with the manual page) in the driver.', fn.id if fn else '', tuple(pids[:1]), fn.name if fn else '', std, count=len(pids)))
    return out


# ============================================================================================================== the whole check
def _match(ds, period, matcher, match):
    if match is not None:
        return match, ''
    try:
        import datasheet_builder_match as dm
        return (matcher or dm.Matcher()).match(ds, period), ''
    except Exception as exc:
        return None, f'the standards could not be loaded or matched ({type(exc).__name__}: {exc})'


def check(ds, period=None, matcher=None, match=None, dry_run_on=True, runner=None):
    """The sheet check (rules 1-5) for `ds`.  Never raises and never changes `ds`."""
    period = period or ds.default_period
    chk = SheetCheck(period=period)
    manual_sheet = bool(ds.options.get('manual_entry'))
    chk.findings += unit_findings(ds)                                                            # 3
    bad = db.errors(db.validate(ds))
    if manual_sheet:                                                                             # nothing is sourced: no standard is looked for
        res, why = None, ''
    else:
        res, why = (None, 'the sheet has problems to fix first') if bad else _match(ds, period, matcher, match)
    if why and not bad:
        chk.notes.append(why)
    chk.findings += coverage_findings(ds, res)                                                   # 1
    chk.sources, src_findings = source_findings(ds, res, manual_sheet)                           # 5
    chk.findings += src_findings
    if dry_run_on and not manual_sheet and res is not None:
        chk.dry = dry_run(ds, res, period, runner)                                               # 4
        chk.findings += dry_findings(ds, res, chk.dry)
    elif dry_run_on and not manual_sheet:
        chk.dry.reason = 'the sheet has problems to fix first' if bad else (why or 'the standards could not be matched')
    if chk.dry.available:
        chk.unverified = unverified_uses(chk.dry)                                                # 2
    elif not manual_sheet:
        chk.unverified = capability_uses(ds, res)
    chk.findings += unverified_findings(ds, chk.unverified, chk.dry.available)
    order = {ERROR: 0, WARN: 1, INFO: 2}
    chk.findings.sort(key=lambda f: (order[f.level], f.rule))
    return chk


def blocking_problems(ds, period=None, matcher=None):
    """For datasheet_builder.save(): (problems, SheetCheck).  `problems` are the error findings as DsProblems; a check that crashes blocks nothing."""
    try:
        chk = check(ds, period, matcher=matcher)
    except Exception as exc:
        return [], None
    return [f.to_problem() for f in chk.errors()], chk


def point_source(ds, function_id, point_id, matcher=None, period=None):
    """Rule 5 for ONE point (the point inspector): the matcher runs on a one-point copy of the sheet, so it is cheap.  None when the point does not exist."""
    import copy
    fn, p = _find(ds, point_id)
    if p is None:
        return None
    manual_sheet = bool(ds.options.get('manual_entry'))
    if manual_sheet or _no_uncertainty_kind(fn):
        return uncertainty_source(ds, fn, p, None, manual_sheet)
    res, _why = _match(_one_point(ds, fn, p), period or ds.default_period, matcher, None)
    return uncertainty_source(ds, fn, p, res.assignments.get(p.id) if res is not None else None)


def _one_point(ds, fn, p):
    import copy
    small = copy.copy(ds)
    f2 = copy.copy(fn)
    f2.points = [p]
    small.functions = [f2]
    return small


def list_summary(ds, matcher=None, match=None):
    """What the Manager's list needs without the dry run (fast, no tkinter): dict(points, runnable, unverified, by_hand, uncovered) from the matcher, or None."""
    res, _why = _match(ds, ds.default_period, matcher, match)
    if res is None:
        return None
    pts = [a for a in res.assignments.values()]
    return dict(points=len(pts), runnable=sum(a.can_automate for a in pts), unverified=sum(a.status == 'assigned' and a.automation == 'unverified' for a in pts),
                by_hand=sum(a.status == 'manual' for a in pts), uncovered=sum(a.status == 'uncovered' for a in pts))
