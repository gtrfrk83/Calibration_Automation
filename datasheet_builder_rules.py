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
    rules.plan_manual_standard(ds, std) / rules.apply_manual_standard(ds, std)   -> a MANUAL sheet's uncertainty from the standard the author chose (.MDD import); the rest waived per point

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
# ---- which readings should carry an uncertainty (rule 5): derived from the laboratory's CMC table, not typed in twice.
# CMC_KIND_MAP says which Datasheet Builder kinds each entry of specs/a2la_1888_03_cmc.json covers (the table's 'entries[].kind' values and the 'oscilloscope'
# sections).  A kind (or section) that is in the table but not in this map is a hole: tests.test_datasheet_builder_rules fails until it is mapped.
CMC_KIND_MAP = {'DCV': ('DCV',), 'DCI': ('DCI',), 'OHM': ('OHM2', 'OHM4'), 'CAP': ('CAP',), 'ACV': ('ACV',), 'ACI': ('ACI',), 'TEMP': ('TEMP',),
                'FREQ': ('FREQ', 'PERIOD', 'GEN_FREQ', 'SCOPE_TIMEBASE'),                      # Time & Frequency
                'oscilloscope.dc': ('SCOPE_GAIN', 'SCOPE_OFFSET', 'GEN_OFFSET'),
                'oscilloscope.flatness': ('SCOPE_BW', 'GEN_FLAT'),
                'oscilloscope.amplitude': ('GEN_AMPL',),
                'ACFLAT': ('GEN_FLAT',)}                                                         # AC Voltage - Measure, AC Flatness relative to 1 kHz (generator flatness)
# Kinds the suite resolves an uncertainty for TODAY: the standards matcher / handheld_dmm.has_uncertainty give a value (TEMP in degC is not in the CMC table but the
# handheld procedures print one, so it stays).  Every other should-have kind is an ERROR until the author waives it ('not_implemented').
RESOLVABLE_KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'TEMP', 'FC', 'LUX', 'LAMBERT', 'UVIRR')
# A MANUAL calibration (.MDD import) also resolves FREQ and PERIOD: the laboratory's 'Frequency - Measure' CMC alone, as the engines report a frequency
# (report_pdf.point_uncertainty), once the chosen standard's sheet covers the frequency (datasheet_builder_match.Matcher.manual_frequency).  An automated sheet keeps
# FREQ / PERIOD waived: the matcher's figure there is the standard's own frequency row, a different method that is not changed here.
MANUAL_RESOLVABLE_KINDS = RESOLVABLE_KINDS + ('FREQ', 'PERIOD')
# Light meters (FC / LUX / LAMBERT / UVIRR): the lab's A2LA scope has a 'Light - Measure' CMC (p. 45), kept as the standards sheet A2LA-LIGHT (the Minolta T-10A working standard is the
# other choice), so these kinds carry an uncertainty from that sheet.  Not in a2la_1888_03_cmc.json, hence listed here.
LIGHT_KINDS = ('FC', 'LUX', 'LAMBERT', 'UVIRR')
EXTRA_SHOULD_HAVE = ('TEMP',) + LIGHT_KINDS


def cmc_table_keys(path=None):
    """The kinds and oscilloscope sections the CMC table carries: {'DCV', 'OHM', ..., 'oscilloscope.dc', ...}."""
    import json
    from pathlib import Path
    f = Path(path) if path else Path(__file__).resolve().parent / 'specs' / 'a2la_1888_03_cmc.json'
    data = json.loads(f.read_text(encoding='utf-8'))
    return {e['kind'] for e in data.get('entries', [])} | {f'oscilloscope.{k}' for k in (data.get('oscilloscope') or {})}


def should_have_kinds(path=None):
    """Datasheet Builder kinds that should carry an uncertainty: every kind the CMC table covers (CMC_KIND_MAP), plus EXTRA_SHOULD_HAVE.  Read from the table each call set-up."""
    out = set(EXTRA_SHOULD_HAVE)
    for key in cmc_table_keys(path):
        out.update(CMC_KIND_MAP.get(key, ()))
    return frozenset(out)


SHOULD_HAVE_KINDS = should_have_kinds()
WAIVER_KEY = 'uncertainty_waivers'                     # ds.options[WAIVER_KEY] = {point id | '*': dict(code, reason, by, at)}: recorded in every saved version of the sheet
WHOLE_SHEET = '*'
WAIVER_REASONS = (('own_standard', 'The operator uses their own standard (entered by hand)'),
                  ('zero_offset', 'Zero / offset check: no uncertainty applies'),
                  ('no_source', 'No standard or source exists for this point'),
                  ('scope', 'The scope of accreditation does not cover this point'),
                  ('functional', 'Functional pass / fail check'),
                  ('manual_calibration', 'Manual calibration: the uncertainty is not sourced by this suite'),
                  ('not_implemented', 'Uncertainty calculation for this kind is not implemented in the suite yet'),
                  ('other', 'Other (typed reason)'))
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
    action: str = ''               # '' | 'manual_entry' | 'make_check' | 'waive' (asks for a reason) | 'unwaive': what 'Apply the fix' does
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
    level: str = 'ok'              # ok | info | warn | error (should have one and has none)
    standard: str = ''
    should_have: bool = False      # a kind that carries an uncertainty (SHOULD_HAVE_KINDS)
    waived: str = ''               # the recorded reason when the author waived it


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
                    dry_run=bool(self.dry.available), fingerprint=self.fingerprint(), missing_uncertainties=missing_count(self.sources),
                    waived_uncertainties=sum(bool(s.waived) for s in self.sources.values()))


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
    st, base, _variant = text_unit_ex(text)
    return st, base


def text_unit_ex(text):
    """text_unit plus a third item: '' when the unit is written the program's own way, else a short note saying which spelling was accepted and why (rule 3 lists them)."""
    text = re.sub(r'^\s*[+-]?(?:\d+[.,]?\d*|[.]\d+)\s+to\s+', '', str(text or ''))        # 'a to b unit' (a printed range): the unit is after b
    m = _QTY.match(text)
    if not m:
        return 'none', '', ''
    word = (m.group('unit') or '').strip()
    if not word:
        return 'bare', '', ''
    cand = [word]
    stripped = re.sub(r'(rms|pp|dc|ac|p)$', '', word, flags=re.I)
    if stripped and stripped != word:
        cand.append(stripped)
    own = {a for a, _b in db._UNIT_ALIASES}
    for w in cand:
        for alias, base in list(db._UNIT_ALIASES) + _EXTRA_ALIASES:
            if w.endswith(alias):
                prefix = w[:-len(alias)].strip()
                note = []
                if prefix == 'K':
                    prefix = 'k'
                    note.append('capital K read as kilo')
                if prefix in db._PREFIXES and (prefix == '' or base not in db._NO_PREFIX):
                    if alias not in own:
                        note.append(f'"{alias}" read as {db.unit_symbol(base)}')
                    if w is not word:
                        note.append(f'trailing "{word[len(w):]}" ignored')
                    return 'ok', base, '; '.join(note)
        try:                                                    # the Cal Processor import's own unit reader (Vpp, Ohm, Ohms ...)
            import mdd_convert
            known = mdd_convert.parse_unit(w)
        except Exception:
            known = None
        if known is not None:
            return 'ok', known[1], f'read by the .MDD import as {db.unit_symbol(known[1])}'
    return 'unknown', word, ''


# ============================================================================================================== rule 3: units and kinds
def unit_findings(ds):
    """Rule 3.  Pure data check of the unit texts a sheet carries: range labels and point labels of multimeter functions, the amplitude unit of generator
    functions, and the absolute units printed in an accuracy statement."""
    out = []
    variants = {}                                          # the label text of every unit spelling accepted although it is not the program's own: listed in one note
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
            st, base, var = text_unit_ex(rng.label)
            if st == 'ok' and var and base == unit:
                variants.setdefault(re.sub(r'^\s*[+-]?[\d.,eE+-]+\s*(to\s+[+-]?[\d.,eE+-]+\s*)?', '', rng.label).strip() or rng.label, var)
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
            st, base, var = text_unit_ex(p.label)
            if st == 'ok' and var and base == unit:
                variants.setdefault(re.sub(r'^\s*[+-]?[\d.,eE+-]+\s*(to\s+[+-]?[\d.,eE+-]+\s*)?', '', p.label).strip() or p.label, var)
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
    if variants:
        out.append(Finding(3, INFO, 'unit_variants', f'{len(variants)} unit spelling{"s" * (len(variants) != 1)} accepted as written, not an error: '
                           + '; '.join(f'"{w}" ({why})' for w, why in sorted(variants.items())), 'Nothing to do. Write the unit the program\'s own way if you prefer.', '', (), 'Whole datasheet', ''))
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


# ============================================================================================================== manual calibrations: the standard of the uncertainty
MANUAL_WAIVER = 'manual_calibration'
STANDARD_KEY = 'manual_standard'                  # ds.options[STANDARD_KEY] = the default standard chosen for a manual sheet ('' = none: the uncertainty is waived)


@dataclass
class ManualStandardPlan:
    """What choosing `standard` for a manual sheet does, point by point (nothing is changed by building it)."""
    standard: str = ''
    sourced: dict = field(default_factory=dict)        # point id -> the matcher Candidate whose uncertainty (the standard's own spec row, k = 2, rounded up) the point carries
    waived: dict = field(default_factory=dict)         # point id -> the reason of its per-point 'manual_calibration' waiver
    by_design: int = 0                                 # points of kinds that carry no uncertainty by design (diode, continuity, CHECK, COND, PCT, TEMPF ...): no waiver needed
    points: int = 0

    def counts(self):
        return dict(points=self.points, sourced=len(self.sourced), waived=len(self.waived), by_design=self.by_design)


class StandardLookup:
    """The candidates of every loaded standard for the points of a sheet, worked out once per point (the .MDD preview asks about several standards in turn).  Read only."""

    def __init__(self, ds, period=None, matcher=None):
        self.ds, self.period, self.matcher = ds, period or ds.default_period, matcher
        self._cache = {}
        self.error = ''

    def candidates(self, fn, p):
        """{standard model: Candidate} for point p ({} when the standards cannot be loaded; `error` says why)."""
        if p.id not in self._cache:
            try:
                if self.matcher is None:
                    import datasheet_builder_match as dm
                    self.matcher = dm.Matcher()
                self._cache[p.id] = {c.standard: c for c in self.matcher.point_candidates(self.ds, fn, p, self.period)}
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
                self._cache[p.id] = {}
        return self._cache[p.id]


def gives_uncertainty(cand):
    """A matcher Candidate whose standard covers the point AND gives a usable (positive) uncertainty - the test of rule 5 (uncertainty_source)."""
    return cand is not None and cand.covered and cand.uncertainty is not None and cand.uncertainty > 0


def plan_manual_standard(ds, standard, period=None, matcher=None, lookup=None):
    """Work out, for each enabled point of `ds`, whether `standard` ('' = none: waive) gives it an uncertainty: the same candidates as an automated sheet (the standard's own
    specification row for the point, k = 2, rounded up, never below the lab CMC).  Points the standard does not cover, kinds the suite has no uncertainty calculation for
    (FREQ, PERIOD ...) and everything when no standard is chosen are WAIVED with the reason; kinds that carry no uncertainty by design are only counted.  Never raises."""
    lookup = lookup or StandardLookup(ds, period, matcher)
    plan = ManualStandardPlan(standard=standard or '')
    for fn, p in ds.all_points():
        if not p.enabled:
            continue
        plan.points += 1
        if _no_uncertainty_kind(fn):
            plan.by_design += 1
            continue
        if not standard:
            plan.waived[p.id] = 'manual calibration: no standard was chosen for the uncertainty (None: waive)'
        elif fn.kind not in MANUAL_RESOLVABLE_KINDS:
            plan.waived[p.id] = f'manual calibration: the suite has no uncertainty calculation for {fn.name} yet'
        else:
            cand = lookup.candidates(fn, p).get(standard)
            if cand is None:
                plan.waived[p.id] = f'manual calibration: {standard} could not be looked up' + (f' ({lookup.error})' if lookup.error else ' (not a known standard)')
            elif gives_uncertainty(cand):
                plan.sourced[p.id] = cand
            else:
                plan.waived[p.id] = (f'manual calibration: {standard} does not cover this point' + (f' ({cand.message})' if cand.message else '')
                                     if not cand.covered else f'manual calibration: the {standard} sheet gives no usable uncertainty here')
    return plan


def apply_manual_standard(ds, standard, who='', period=None, matcher=None, plan=None, lookup=None):
    """Make `standard` the uncertainty standard of the manual sheet `ds` (the owner's design for a .MDD import).  Points it covers get it as the PERSON'S OVERRIDE in
    ds.assignments (so the sheet check, the run window and the report resolve their uncertainty through the matcher like an automated sheet); every other point that should
    carry an uncertainty gets its own recorded waiver 'manual_calibration' with the reason (never a silent blank, never a whole-sheet waiver); ds.options['manual_standard']
    keeps the choice.  An earlier whole-sheet or per-point manual_calibration waiver is replaced.  Returns the ManualStandardPlan."""
    plan = plan or plan_manual_standard(ds, standard, period, matcher, lookup)
    ids = [p.id for _f, p in ds.all_points()]
    old = waivers(ds)
    clear_waiver(ds, [k for k in [WHOLE_SHEET] + ids if (old.get(k) or {}).get('code') == MANUAL_WAIVER])
    for fn, p in ds.all_points():
        ds.assignments[p.id] = plan.standard if p.id in plan.sourced else 'MANUAL'
    by_reason = {}
    for pid, reason in plan.waived.items():
        by_reason.setdefault(reason, []).append(pid)
    for reason, pids in by_reason.items():
        set_waiver(ds, pids, MANUAL_WAIVER, reason, who=who)
    ds.options[STANDARD_KEY] = plan.standard
    return plan


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
        if a.status != 'uncovered' or a.reason == 'no_sensor':          # a temperature point with no sensor chosen is reported by sensor_findings, not as 'no standard covers it'
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


def sensor_findings(ds):
    """Rule 5, temperature: how the temperature is SOURCED (thermocouple type or RTD) decides which specification rows and which scope lines give the uncertainty, so it has to
    be chosen for every enabled temperature point (dsb_sensors).  An ERROR (blocks publishing) per section; the finding goes to the first row.  Nothing is assumed: an old
    point with only settings['tc_type'] has its choice; one with neither is reported here (when the sheet is checked or saved, never at load)."""
    import dsb_sensors as sens
    out = []
    if ds.options.get('manual_entry'):
        return out
    for fn in ds.functions:
        if fn.kind != 'TEMP':
            continue
        miss = [p for p in fn.points if p.enabled and not sens.sensor_of(fn, p)]
        if miss:
            rows = [point_text(fn, p) for p in miss]
            out.append(Finding(5, ERROR, 'sensor_not_chosen', f'{len(miss)} temperature reading{"s" * (len(miss) != 1)} in {fn.name} {"have" if len(miss) != 1 else "has"} no sensor chosen, so '
                               f'no uncertainty can be assigned: ' + _names(rows),
                               sens.NOT_CHOSEN + ': pick it in the row panel (Sourced as), or set it for the whole section at once.',
                               fn.id, tuple(p.id for p in miss), fn.name, rows[0], count=len(miss)))
    return out


def _no_uncertainty_kind(fn):
    """True for a kind that carries no uncertainty by design: not in the CMC table (diode, continuity, trigger, functional checks, conductance ...)."""
    return fn.kind not in SHOULD_HAVE_KINDS


def should_have(fn, p):
    """Rule 5 (owner rule): this reading is supposed to have an uncertainty on the datasheet."""
    return p.enabled and fn.kind in SHOULD_HAVE_KINDS


# ---- waivers: an explicit, recorded reason why a point that should have an uncertainty has none (never silent: in the sheet, the check and the version history)
def waivers(ds):
    w = ds.options.get(WAIVER_KEY)
    return w if isinstance(w, dict) else {}


def waiver_for(ds, point_id):
    w = waivers(ds)
    return w.get(point_id) or w.get(WHOLE_SHEET)


def waiver_text(w):
    who = f' ({w["by"]}, {w["at"][:10]})' if w.get('by') and w.get('at') else (f' ({w["by"]})' if w.get('by') else '')
    return f'{w.get("reason", "")}{who}'


def set_waiver(ds, point_ids, code, reason='', who=''):
    """Record a waiver for each of `point_ids` (WHOLE_SHEET for the whole sheet).  The reason is chosen from WAIVER_REASONS or typed ('other' needs text)."""
    import datetime
    label = dict(WAIVER_REASONS).get(code)
    text = (reason or '').strip()
    if label is None:
        raise db.DsError('waiver', 'Choose a reason from the list, or type one.')
    if code == 'other' and not text:
        raise db.DsError('waiver', 'Type the reason for the waiver.')
    w = dict(waivers(ds))
    for pid in point_ids:
        w[pid] = dict(code=code, reason=text if (code == 'other' or text) else label, by=who or '', at=datetime.datetime.now().isoformat(timespec='seconds'))
    ds.options[WAIVER_KEY] = w
    return len(point_ids)


def clear_waiver(ds, point_ids):
    w = dict(waivers(ds))
    n = sum(w.pop(pid, None) is not None for pid in point_ids)
    if w:
        ds.options[WAIVER_KEY] = w
    else:
        ds.options.pop(WAIVER_KEY, None)
    return n


def waiver_note(ds):
    """A line for the version history of the saved sheet ('' when there are none)."""
    w = waivers(ds)
    if not w:
        return ''
    ids = {p.id for _f, p in ds.all_points()}
    n = sum(k in ids for k in w)
    return f'uncertainty waivers: {n} point{"s" * (n != 1)}' + (' + whole sheet' if WHOLE_SHEET in w else '') if (n or WHOLE_SHEET in w) else ''


def uncertainty_source(ds, fn, p, a, manual_sheet=False, pending=False):
    """Rule 5 for one point from its matcher assignment `a` (None when there is none).  A reading that should have an uncertainty and has none is level
    'error' (blocks publishing) unless the author recorded a waiver for it.  The uncertainty is never shown as zero."""
    if _no_uncertainty_kind(fn):
        return UncertaintySource(p.id, f'none: blank ({fn.name} rows carry no uncertainty in the report)', False, INFO)
    src = None
    cand = None
    if fn.kind not in (MANUAL_RESOLVABLE_KINDS if manual_sheet else RESOLVABLE_KINDS):
        why = 'the suite has no uncertainty calculation for this kind yet'
        a = None
        std = ''
        w = waiver_for(ds, p.id)
        if w:
            return UncertaintySource(p.id, f'none: blank, waived ({waiver_text(w)}; {why})', False, INFO, std, True, waiver_text(w))
        return UncertaintySource(p.id, f'none: blank ({why})', False, ERROR, std, True)
    chosen = ds.assignments.get(p.id) if manual_sheet else None
    if manual_sheet and (a.status == 'manual' if a is not None else chosen in (None, '', 'MANUAL')):      # a manual sheet's point WITHOUT a chosen standard (one with a standard is resolved below, as on an automated sheet)
        why = 'manual calibration: no standard was chosen for this point, so no standard gives an uncertainty'
    elif a is None and pending:                                     # the sheet's own problems come first; they already block publishing
        return UncertaintySource(p.id, 'none: blank (not worked out yet: fix the sheet\'s problems first)', False, INFO, '', True)
    elif a is None:
        why = 'no standard selected: the standards could not be matched'
    elif a.status == 'manual':
        why = 'no standard selected: set by hand, no standards sheet is used'
    elif a.status == 'uncovered':
        named = chosen
        why = (f'{named} does not cover this point' + (f' ({a.message})' if a.message else '')) if named not in (None, '', 'MANUAL') else 'no standards sheet covers this point'
    else:
        cand = next((c for c in a.candidates if c.standard == a.standard and c.covered), None)
        if a.uncertainty is None or not a.uncertainty > 0:
            why = f'{a.standard}: ' + ('it has no specification sheet imported' if cand is not None and not cand.spec_known else 'its sheet gives no usable uncertainty here')
        else:
            row = f' ({cand.row})' if cand is not None and cand.row else ''
            if getattr(a, 'coil', False):                           # a clamp-meter current point driven through the 50-turn coil (dsb_coil): the coil's sheet, or the calibrator's below its range
                import dsb_coil
                if a.unc_standard == dsb_coil.MODEL:
                    return UncertaintySource(p.id, f'{dsb_coil.LABEL} standards sheet ({a.unc_row}) at the effective current, RSS with the clamp / coil interaction; '
                                                   f'{a.standard} sources {a.sourced:.6g} A', True, 'ok', dsb_coil.MODEL, True)
                return UncertaintySource(p.id, f'{a.standard} standards sheet{row} at the sourced {a.sourced:.6g} A, x {a.unc_scale:g} turns (below the coil\'s range: no coil line, no interaction term)',
                                         True, 'ok', a.standard, True)
            return UncertaintySource(p.id, f'{a.standard} standards sheet{row}', True, 'ok', a.standard, True)
    std = a.standard if a is not None and a.status not in ('manual', 'uncovered') else ''
    w = waiver_for(ds, p.id)
    if w:
        return UncertaintySource(p.id, f'none: blank, waived ({waiver_text(w)}; {why})', False, INFO, std, True, waiver_text(w))
    return UncertaintySource(p.id, f'none: blank ({why})', False, ERROR, std, True)


def source_findings(ds, res, manual_sheet, pending=False):
    """Rule 5: (sources {point id: UncertaintySource}, findings).  A point that should have an uncertainty and has none is an ERROR (blocks publishing) until
    the author picks a standard, fixes the point or records a waiver; a waived point is listed (never silent).  Many in one section are one finding."""
    sources, out, none, waived = {}, [], {}, {}
    for fn, p in ds.all_points():
        if not p.enabled:
            continue
        a = res.assignments.get(p.id) if res is not None else None
        s = uncertainty_source(ds, fn, p, a, manual_sheet, pending)
        sources[p.id] = s
        if s.level == ERROR:
            none.setdefault(fn.id, []).append((fn, p, s))
        elif s.waived:
            waived.setdefault(fn.id, []).append((fn, p, s))
    for fid, items in none.items():
        fn = items[0][0]
        rows = [f'{point_text(fn, p)} {s.text[len("none: blank"):].strip()}' for _f, p, s in items]
        out.append(Finding(5, ERROR, 'no_uncertainty', f'{len(items)} reading{"s" * (len(items) != 1)} in {fn.name} should have an uncertainty and {"have" if len(items) != 1 else "has"} none, '
                           f'so the datasheet cannot be published (the report never shows zero): ' + _names(rows),
                           ('The suite cannot calculate an uncertainty for this kind yet: press "Waive..." and choose "Uncertainty calculation for this kind is not implemented in the suite yet" '
                            '(or another reason).' if fn.kind not in (MANUAL_RESOLVABLE_KINDS if manual_sheet else RESOLVABLE_KINDS) else
                            'Pick a standard whose sheet covers the point, fix the point (value, range or frequency), or press "Waive..." and record why it has none.'),
                           fid, tuple(p.id for _f, p, _s in items), fn.name, rows[0], action='waive', count=len(items)))
    for fid, items in waived.items():
        fn = items[0][0]
        rows = [f'{point_text(fn, p)} ({s.waived})' for _f, p, s in items]
        out.append(Finding(5, INFO, 'waived', f'{len(items)} reading{"s" * (len(items) != 1)} in {fn.name} {"have" if len(items) != 1 else "has"} no uncertainty by a recorded waiver: ' + _names(rows),
                           'The waiver is saved with the sheet and listed in its history. "Remove waiver" puts the error back.', fid, tuple(p.id for _f, p, _s in items), fn.name, rows[0],
                           action='unwaive', count=len(items)))
    return sources, out


def missing_count(sources):
    """How many readings should have an uncertainty, have none and have no waiver (the Manager list's 'missing uncertainties: N')."""
    return sum(s.level == ERROR for s in sources.values())


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


# Routine housekeeping that never asks the operator for anything: read-only status / identity queries and *CLS (clears the status registers; no instrument
# configuration or output changes).  ONLY these are left out of the pre-run list (rule 2).  Never add a command that configures, sources or measures, and never
# a write such as '*RST' or '*OPC' (without the question mark): those stay on the list until they are verified and tied to a manual page.
HOUSEKEEPING = frozenset({'*CLS', '*IDN?', '*ESR?', '*STB?', '*OPC?', 'ID?', 'ERR?', 'ERROR?', 'SYST:ERR?', 'SYST:ERR:NEXT?', 'SYSTEM:ERROR?', 'SYSTEM:ERROR:NEXT?', 'SYST:ERR:COUN?'})


def is_housekeeping(wire):
    """True when the command as sent (`wire`) is one of HOUSEKEEPING: compared on its header only, upper-cased ('syst:err?' = 'SYST:ERR?')."""
    head = (wire or '').strip().split(None, 1)[0].upper().lstrip(':') if (wire or '').strip() else ''
    return head in HOUSEKEEPING


def unverified_uses(dry):
    """Rule 2: the commands the dry run recorded whose registry entry is not verified, or has no manual page reference, or is not in the registry."""
    uses = {}
    for pid, pr in dry.points.items():
        for e in pr.commands:
            if is_housekeeping(e.wire):                    # routine status / identity query or *CLS: never asked (see HOUSEKEEPING)
                continue
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
def _match(ds, period, matcher, match, overrides=None):
    if match is not None:
        return match, ''
    try:
        import datasheet_builder_match as dm
        return (matcher or dm.Matcher()).match(ds, period, overrides), ''
    except Exception as exc:
        return None, f'the standards could not be loaded or matched ({type(exc).__name__}: {exc})'


def manual_standards(ds):
    """{point id: standard model} of the enabled points of a MANUAL sheet that name a real standard (anything else - '', 'MANUAL', no entry - is 'the technician's own')."""
    return {p.id: ds.assignments[p.id] for _f, p in ds.all_points() if p.enabled and ds.assignments.get(p.id) not in (None, '', 'MANUAL')}


def match_manual(ds, period, matcher, match):
    """The standards matcher for a manual sheet: ONLY the points that name a standard are looked up there (their value is that standard's own spec row); every other point is
    'MANUAL' (the matcher would otherwise pick the best standard by itself, which a manual calibration never does).  (None, '') when no point names a standard."""
    if match is not None:
        return match, ''
    if not manual_standards(ds):
        return None, ''
    ov = {p.id: (ds.assignments.get(p.id) or 'MANUAL') for _f, p in ds.all_points() if p.enabled}
    return _match(ds, period, matcher, None, overrides=ov)


def manual_figures(a):
    """The figures of a matcher Assignment `a` of a manual sheet's point that names a standard and gets a usable uncertainty from it: dict(unc_standard, uncertainty, tar, tur, tolerance,
    unc_row) - what the run window and the report print.  None otherwise."""
    if a is None or a.status != 'assigned' or not a.uncertainty or not a.uncertainty > 0:
        return None
    cand = next((c for c in a.candidates if c.standard == a.standard and c.covered), None)
    return dict(unc_standard=a.standard, uncertainty=a.uncertainty, tar=a.tar, tur=a.tur, tolerance=a.tolerance, unc_row=cand.row if cand is not None else '')


def manual_choices(ds, fn, p, period=None, matcher=None, lookup=None):
    """[Candidate] of the standards a technician may pick for the uncertainty of point p of the manual sheet `ds`: those whose sheet covers the point AND give a usable uncertainty, by
    model (the same candidates as the import preview and the Sheet check).  [] for a kind the suite has no manual uncertainty for.  Read only."""
    if fn.kind not in MANUAL_RESOLVABLE_KINDS or _no_uncertainty_kind(fn):
        return []
    lookup = lookup or StandardLookup(ds, period, matcher)
    return sorted((c for c in lookup.candidates(fn, p).values() if gives_uncertainty(c)), key=lambda c: c.standard)


def check(ds, period=None, matcher=None, match=None, dry_run_on=True, runner=None):
    """The sheet check (rules 1-5) for `ds`.  Never raises and never changes `ds`."""
    period = period or ds.default_period
    chk = SheetCheck(period=period)
    manual_sheet = bool(ds.options.get('manual_entry'))
    chk.findings += unit_findings(ds)                                                            # 3
    bad = db.errors(db.validate(ds))
    if manual_sheet:                                                                             # nothing is sourced; only the standard the author chose for the uncertainty is looked at
        res, why = (None, 'the sheet has problems to fix first') if bad else match_manual(ds, period, matcher, match)
    else:
        res, why = (None, 'the sheet has problems to fix first') if bad else _match(ds, period, matcher, match)
    if why and not bad:
        chk.notes.append(why)
    chk.findings += coverage_findings(ds, res)                                                   # 1
    chk.sources, src_findings = source_findings(ds, res, manual_sheet, pending=bool(bad))   # 5
    chk.findings += src_findings
    chk.findings += sensor_findings(ds)                                                          # 5 (temperature: how it is sourced)
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
    """For datasheet_builder.save(): (problems, SheetCheck).  `problems` are the error findings as DsProblems.  FAILS CLOSED: a check that crashes returns one error
    ('the sheet check could not run: <error>'), so the sheet is saved as a draft and never published unchecked; the traceback goes to the log."""
    try:
        chk = check(ds, period, matcher=matcher)
    except Exception as exc:
        import logging
        import traceback
        logging.getLogger(__name__).error('The Datasheet Builder sheet check crashed:\n%s', traceback.format_exc())
        return [db.DsProblem('rule_check_failed', f'The sheet check could not run: {type(exc).__name__}: {exc}. The sheet is saved as a draft and is not published until it can be checked.',
                             'error', 'datasheet')], None
    return [f.to_problem() for f in chk.errors()], chk


def point_source(ds, function_id, point_id, matcher=None, period=None):
    """Rule 5 for ONE point (the point inspector): the matcher runs on a one-point copy of the sheet, so it is cheap.  None when the point does not exist."""
    import copy
    fn, p = _find(ds, point_id)
    if p is None:
        return None
    manual_sheet = bool(ds.options.get('manual_entry'))
    if _no_uncertainty_kind(fn) or fn.kind not in (MANUAL_RESOLVABLE_KINDS if manual_sheet else RESOLVABLE_KINDS):
        return uncertainty_source(ds, fn, p, None, manual_sheet)
    if manual_sheet:                                              # a manual sheet's point with a chosen standard is resolved like an automated one
        std = ds.assignments.get(p.id)
        if std in (None, '', 'MANUAL'):
            return uncertainty_source(ds, fn, p, None, True)
        res, _why = _match(_one_point(ds, fn, p), period or ds.default_period, matcher, None, overrides={p.id: std})
        return uncertainty_source(ds, fn, p, res.assignments.get(p.id) if res is not None else None, True)
    res, _why = _match(_one_point(ds, fn, p), period or ds.default_period, matcher, None)
    return uncertainty_source(ds, fn, p, res.assignments.get(p.id) if res is not None else None)


def _one_point(ds, fn, p):
    import copy
    small = copy.copy(ds)
    f2 = copy.copy(fn)
    f2.points = [p]
    small.functions = [f2]
    return small


one_point = _one_point                                            # public name for the run window's one-point match


def list_summary(ds, matcher=None, match=None):
    """What the Manager's list needs without the dry run (fast, no tkinter): dict(points, runnable, unverified, by_hand, uncovered) from the matcher, or None."""
    manual = bool(ds.options.get('manual_entry'))
    if manual:                                                    # nothing is run by the suite; the uncertainty comes from the standard the author chose (if any)
        res, _why = match_manual(ds, ds.default_period, matcher, match)
        n = sum(p.enabled for _f, p in ds.all_points())
        missing = sum(uncertainty_source(ds, fn, p, res.assignments.get(p.id) if res is not None else None, True).level == ERROR for fn, p in ds.all_points() if p.enabled)
        return dict(missing=missing, points=n, runnable=0, unverified=0, by_hand=n, uncovered=0)
    res, _why = _match(ds, ds.default_period, matcher, match)
    if res is None:
        return None
    pts = [a for a in res.assignments.values()]
    missing = sum(uncertainty_source(ds, fn, p, res.assignments.get(p.id), manual).level == ERROR for fn, p in ds.all_points() if p.enabled)
    return dict(missing=missing, points=len(pts), runnable=sum(a.can_automate for a in pts), unverified=sum(a.status == 'assigned' and a.automation == 'unverified' for a in pts),
                by_hand=sum(a.status == 'manual' for a in pts), uncovered=sum(a.status == 'uncovered' for a in pts))
