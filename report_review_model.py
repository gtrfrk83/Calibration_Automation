"""Review of the per-point uncertainties before a PDF is generated (Tk-free model; the window is report_review.py).

    spec_rows = specs_for(app)                    # one PointSpec per report row, parallel to app.certificate_rows_and_points()
    model = ReviewModel(spec_rows, default_standard='5560A', asset='A-100')
    model.set_standard(3, '5522A')                # recalculates budget / reported / TUR of row 3 (never below the scope minimum)
    details['uncertainty_review'] = {'version': 1, 'reviews': [model.record()]}

What it does NOT do: it never changes a limit, a pass / fail result, a reading or an instrument command.  A row the person does not touch keeps exactly
the strings the engine built (report_pdf.apply_uncertainty_review only replaces the Uncertainty / TAR / TUR cells of rows listed under 'changes').

Numbers come from the same functions the engines use:
    Uncertainty text   report_pdf.point_uncertainty(point, standard)         (= max(budget, scope CMC) rounded UP to 2 figures, k = 2, never below the CMC)
    TAR / TUR text     tartur.row_fields(point, low, high, standard)
    budget / CMC       uncertainty_budget.build(...)  (.emu, .cmc, .reported)
Frequency rows use the Frequency - Measure CMC alone (no standard): they are shown, never changeable.  Rows with no calibrator (zero offset, a standard
connected by hand, nothing printed today) are locked and keep their printed text.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

FORMAT_VERSION = 1
SOURCE_STANDARDS = ('5560A', '5522A', '5520A')                     # calibrators that SOURCE a point for the multimeter engines (uncertainty_budget direction 'output')
LABELS = {'5560A': 'Fluke 5560A', '5522A': 'Fluke 5522A', '5520A': 'Fluke 5520A'}
LOCKED_FREQUENCY = 'Lab frequency'

AS_BUDGETED, RAISED, NOT_IN_SCOPE, CHANGED, NO_UNC = 'As budgeted', 'Raised to scope', 'Not in scope', 'Standard changed', 'No uncertainty required'
MANUAL = 'Manual (not in scope)'
STATUSES = (AS_BUDGETED, RAISED, NOT_IN_SCOPE, CHANGED, MANUAL)
FILTERS = ('All', 'Needs attention', 'Changed by me')


def label(standard) -> str:
    return LABELS.get(standard, str(standard)) if standard else ''


def key_of(text) -> str:
    """'Fluke 5522A' -> '5522A' (the drop-down shows labels, the model keeps model keys)."""
    t = str(text or '').strip()
    for k, v in LABELS.items():
        if t in (k, v):
            return k
    return t


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass
class PointSpec:
    idx: int                       # position in the report rows (parallel to the engine's rows / points)
    step: str
    section: str
    description: str
    nominal_text: str
    q: dict                        # point dict for report_pdf.point_uncertainty / uncertainty_budget (kind, nominal, unit, frequency, range, source ...)
    q_tar: dict                    # point dict for tartur (the handhelds read the base unit here, not unc_unit)
    low: float | None
    high: float | None
    unit: str
    default_std: str | None
    locked: str = ''               # '' = changeable; else the plain reason
    printed: dict = field(default_factory=dict)      # Uncertainty / TAR / TUR exactly as the engine built them
    has_ratio_cols: bool = False
    calc: object = None            # oscilloscope / generator engines (report_review_adapters): callable(standard) -> Evaluation, instead of the multimeter path
    options: list | None = None    # the standards this row can use (None: worked out from the sheets)
    expects: bool = False          # the point should carry an uncertainty: with no scope entry it is 'Not in scope' (and may take a typed value)
    engine_printed: dict | None = None   # set when the adapter's default is NOT what the engine prints (MDO4000C RF level rows, 96270A): the engine's own Uncertainty / TAR / TUR
    std_label: str = ''            # what the Standard column says for a row with no drop-down ('Scope CMC', 'Fluke 5790B', 'Reference file')


@dataclass
class Evaluation:
    standard: str | None
    budget: float | None           # EMU of the standard's published specification (k = 2), None when no sheet row covers the point
    cmc: float | None              # scope minimum (A2LA CMC), None when the scope does not cover the point
    reported: float | None         # SI, rounded UP, never below cmc
    unc_text: str
    tar: str
    tur: str
    status: str
    unit: str


def scope():
    import report_pdf
    return report_pdf.scope()


def _unit_of(q):
    return 'ohm' if str(q.get('kind', '')).startswith('OHM') else q.get('unit', '')


def evaluate(spec: PointSpec, standard) -> Evaluation:
    """Recalculate one row for `standard` (a model key or None).  Never raises."""
    if spec.calc is not None:
        try:
            return spec.calc(standard)
        except Exception:
            return make_evaluation(spec.unit, standard, '', None, None, None, '', '', spec.expects)
    import report_pdf
    import tartur
    import uncertainty
    import uncertainty_budget as ub
    q = spec.q
    unit = _unit_of(q)
    freq_row = q.get('kind') == 'FREQ'
    std = None if freq_row else standard
    try:
        text = report_pdf.point_uncertainty(q, std)
    except Exception:
        text = ''
    try:
        f = tartur.row_fields(spec.q_tar, spec.low, spec.high, standard=std)
    except Exception:
        f = dict(TAR='', TUR='')
    sc = scope()
    emu = cmc = rep = None
    try:
        if std and sc is not None and q.get('source') != 'none':
            b = ub.build(q['kind'], q['nominal'], unit, standard=std, frequency=q.get('frequency'), scope=sc, range_value=q.get('range'))
            emu, cmc, rep = b.emu, b.cmc, b.reported
        elif sc is not None and q.get('source') != 'none':
            cmc = sc.dmm(q['kind'], q['nominal'], q.get('range'), q.get('frequency'))
            rep = uncertainty.round_up(cmc) if cmc else None
    except Exception:
        pass
    if _finite(cmc) and _finite(rep) and rep < cmc * (1 - 1e-12):          # cannot happen (build rounds UP and floors at the CMC); a belt-and-braces clamp
        rep = uncertainty.round_up(cmc)
    if not text:
        status = NO_UNC
    elif cmc is None:
        status = NOT_IN_SCOPE
    elif emu is not None and emu < cmc * (1 - 1e-9):
        status = RAISED
    else:
        status = AS_BUDGETED
    return Evaluation(std, emu if _finite(emu) else None, cmc if _finite(cmc) else None, rep if _finite(rep) else None, text,
                      f.get('TAR', ''), f.get('TUR', ''), status, unit)


def make_evaluation(unit, standard, text, emu, cmc, rep, tar, tur, expects=False) -> Evaluation:
    """An Evaluation from numbers an adapter already has; the status follows the same rules as evaluate()."""
    text = '' if text in (None, 'N/A') else text
    if not text and not (expects and cmc is None):
        status = NO_UNC
    elif cmc is None:
        status = NOT_IN_SCOPE if (expects or text) else NO_UNC
    elif emu is not None and emu < cmc * (1 - 1e-9):
        status = RAISED
    else:
        status = AS_BUDGETED
    return Evaluation(standard, emu if _finite(emu) else None, cmc if _finite(cmc) else None, rep if _finite(rep) else None, text, tar or '', tur or '',
                      status, unit)


def offered_standards(spec: PointSpec) -> list:
    """Model keys the drop-down offers for this row: calibrators whose published sheet has a row covering the point (the default is always listed)."""
    if spec.options is not None:
        return list(spec.options) if not spec.locked else ([spec.default_std] if spec.default_std else [])
    if spec.locked:
        return [spec.default_std] if spec.default_std else []
    import uncertainty_budget as ub
    out = []
    sc = scope()
    for key in SOURCE_STANDARDS:
        try:
            b = ub.build(spec.q['kind'], spec.q['nominal'], _unit_of(spec.q), standard=key, frequency=spec.q.get('frequency'), scope=sc,
                         range_value=spec.q.get('range'))
            if b.hit is not None or key == spec.default_std:
                out.append(key)
        except Exception:
            if key == spec.default_std:
                out.append(key)
    if spec.default_std and spec.default_std not in out:
        out.insert(0, spec.default_std)
    return out


def fmt(value, unit):
    if not _finite(value):
        return ''
    try:
        import uncertainty
        return uncertainty.format_value(value, unit)
    except Exception:
        return f'{value:.3g}'


def tolerance_text(spec: PointSpec) -> str:
    """'± 1.2 mV' (display-only SI scaling) or '' when there is no two-sided limit."""
    try:
        import tartur
        t = tartur.half_width(spec.low, spec.high)
        if t is not None and spec.unit == 'dB':
            return f'\u00b1 {t:g} dB'
        if t is None or not spec.unit or spec.unit in tartur.NO_UNITS or spec.unit not in _SI_UNITS:
            return f'\u00b1 {t:g} {spec.unit}'.strip() if t is not None else ''
        import report_pdf
        return '± ' + report_pdf._si(t, spec.unit)
    except Exception:
        return ''


# ---- a typed uncertainty for a row the lab scope does not cover
_PREFIX = {'': Decimal(1), 'p': Decimal('1e-12'), 'n': Decimal('1e-9'), 'u': Decimal('1e-6'), 'm': Decimal('1e-3'), 'k': Decimal('1e3'), 'M': Decimal('1e6'),
           'G': Decimal('1e9')}
_UNIT_NAMES = {'s': ('s', 'sec'), 'V': ('v',), 'A': ('a',), 'ohm': ('ohm', 'ohms', '\u03c9'), 'Hz': ('hz',), 'F': ('f',), 'C': ('c', 'degc', '\u00b0c'), 'degC': ('c', 'degc', '\u00b0c'),
               '\u00b0C': ('c', 'degc', '\u00b0c')}
_NUMBER = None
_SI_UNITS = ('V', 'A', 'ohm', 'Hz', 'F', 's', 'C', 'degC', '\u00b0C')


def parse_uncertainty(text, unit, shown_scale=Decimal(1)):
    """(value_SI_float, significant_digits, '') for a typed uncertainty, or (None, 0, message).

    `unit` is the row's natural unit ('V', 'A', 'ohm', 'Hz', 'F', 'C').  '3.5 mV', '3.5mV', '0.0035 V', '1.2e-3 V', '2 uV' / '2 \u00b5V' are read with Decimal; a bare
    number is in the unit the grid shows for the row (`shown_scale`: 1e-3 for mV).  Must be a finite number greater than zero.  Nothing is rounded here."""
    import re
    global _NUMBER
    if _NUMBER is None:
        _NUMBER = re.compile(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d\s].*?)?\s*$')
    m = _NUMBER.match(str(text or '').replace('\u00b5', 'u').replace('\u03bc', 'u').replace(',', '.'))
    if not m:
        return None, 0, 'Enter a number with its unit, for example 3.5 mV.'
    num, tail = m.group(1), (m.group(2) or '').strip()
    names = _UNIT_NAMES.get(unit)
    prefixes = _PREFIX
    if names is None:                                        # dB, dBm, dBc/Hz, div ...: the unit as written, no SI prefix
        names = ((unit or '').lower(),)
        prefixes = {'': Decimal(1)}
        if unit in ('dB',):
            prefixes = _PREFIX
            names = ('db',)
    factor = shown_scale
    if tail:
        factor = None
        for pre, mult in prefixes.items():
            if tail.startswith(pre) and tail[len(pre):].lower() in names:
                factor = mult
                break
        if factor is None:
            return None, 0, f'The unit must be {unit if unit != "ohm" else "ohm"} (with an SI prefix such as m or u).'
    try:
        value = Decimal(num) * factor
    except Exception:
        return None, 0, 'Not a number.'
    if not value.is_finite() or value <= 0:
        return None, 0, 'The uncertainty must be greater than zero.'
    if value > Decimal('1e12'):
        return None, 0, 'That value is not plausible.'
    mant = num.lower().split('e')[0].lstrip('+-').replace('.', '').lstrip('0')
    sig = min(max(len(mant), 1), 6)
    return float(value), sig, ''


def format_manual(value, unit, sig=2):
    """A typed uncertainty printed as entered (`sig` figures, no rounding up), with the same SI scaling and spelling as uncertainty.format_value."""
    import ui_theme as ui
    if unit in ('C', 'degC', '\u00b0C'):
        dp = max(sig - 1 - int(math.floor(math.log10(abs(value)))), 0)
        return f'{value:.{dp}f} \u00b0C'
    if unit not in _SI_UNITS:                                 # dB, dBm, dBc/Hz, div ...: printed with the figures typed, no prefix
        dp = max(sig - 1 - int(math.floor(math.log10(abs(value)))), 0)
        return f'{value:.{dp}f} {unit}'.strip()
    number, symbol = ui.si_one(value, '\u03a9' if unit == 'ohm' else unit, sig=sig)
    return f'{number} {symbol}'.replace('\u03a9', 'Ohm')


def entry_scale(spec, ev):
    """(Decimal scale, symbol) of the unit the grid shows for the row: what a bare typed number means (display-only SI scaling)."""
    try:
        import tartur
        import ui_theme as ui
        ref = ev.reported or tartur.half_width(spec.low, spec.high) or abs(spec.q.get('nominal') or 0) or 1.0
        unit = _unit_of(spec.q)
        if unit in ('C', 'degC', '\u00b0C'):
            return Decimal(1), '\u00b0C'
        if unit not in _SI_UNITS:
            return Decimal(1), unit
        scale, symbol = ui.si_scale(ref, '\u03a9' if unit == 'ohm' else unit)
        return Decimal(str(scale)), symbol.replace('\u03a9', 'ohm')
    except Exception:
        return Decimal(1), _unit_of(spec.q)



class Row:
    def __init__(self, spec: PointSpec, default_std):
        self.spec = spec
        self.manual = None                     # standard chosen for this row by the person (model key), or None
        self.typed = None                      # a typed uncertainty (dict) for a row the lab scope does not cover, or None
        self.base = evaluate(spec, spec.default_std)
        self.cur = self.base
        self.follow(default_std)

    def follow(self, default_std):
        """Re-evaluate for the run default (rows the person set themselves keep their own standard)."""
        std = self.manual if self.manual is not None else (default_std if not self.spec.locked else self.spec.default_std)
        self.cur = self.base if std == self.spec.default_std else evaluate(self.spec, std)

    @property
    def standard(self):
        return self.cur.standard if not self.spec.locked else self.spec.default_std

    @property
    def scope_text(self) -> str:
        """The A2LA scope's own expression for this point (e.g. '8.9 µV/V + 0.8 µV'), '' when the scope does not cover it.  Display only."""
        q = self.spec.q
        if self.spec.calc is not None or not q or q.get('source') == 'none':
            return ''
        try:
            sc = scope()
            return sc.dmm_text(q['kind'], q['nominal'], q.get('range'), q.get('frequency')) if sc is not None else ''
        except Exception:
            return ''

    @property
    def changed(self) -> bool:
        """The person changed this row (a standard, or a typed uncertainty)."""
        return self.typed is not None or self.std_changed

    @property
    def applied(self) -> bool:
        """The default of this row replaces what the engine prints (not a choice of the person): the review must carry it into the report."""
        e = self.spec.engine_printed
        return e is not None and any((e.get(k) or '') != (self.spec.printed.get(k) or '') for k in ('Uncertainty', 'TAR', 'TUR'))

    @property
    def std_changed(self) -> bool:
        return (not self.spec.locked) and self.standard != self.spec.default_std

    @property
    def status(self) -> str:
        if self.typed is not None:
            return MANUAL
        if self.std_changed and self.cur.status != NOT_IN_SCOPE and self.cur.status != NO_UNC:
            return CHANGED
        return self.cur.status

    @property
    def reported_text(self) -> str:
        """What the PDF will print for the Uncertainty cell: the engine's own text for an untouched row."""
        if self.typed is not None:
            return self.typed['display']
        return self.cur.unc_text if self.std_changed else (self.spec.printed.get('Uncertainty', self.cur.unc_text))

    @property
    def tur_text(self) -> str:
        if self.typed is not None:
            return self.typed['tur']
        return self.cur.tur if self.std_changed else (self.spec.printed.get('TUR') or self.cur.tur)

    @property
    def tar_text(self) -> str:
        if self.typed is not None:
            return ''
        return self.cur.tar if self.std_changed else self.spec.printed.get('TAR', self.cur.tar)

    def can_type(self) -> bool:
        """Only a row the scope does not cover takes a typed uncertainty; a row that is in scope uses a standard change (never below the scope minimum)."""
        return self.base.status == NOT_IN_SCOPE and self.cur.cmc is None

    def entry_hint(self) -> str:
        return entry_scale(self.spec, self.cur)[1]

    def set_typed(self, text):
        """(ok, message).  Empty text clears the entry (back to the engine's value)."""
        if not str(text or '').strip():
            self.typed = None
            return True, ''
        if not self.can_type():
            return False, 'This point is covered by the lab scope: change the standard instead.'
        scale, _sym = entry_scale(self.spec, self.cur)
        value, sig, err = parse_uncertainty(text, _unit_of(self.spec.q), scale)
        if err:
            return False, err
        import tartur
        tol = tartur.half_width(self.spec.low, self.spec.high)
        res = tartur.from_values(tol, self.spec.unit, None, None, value, self.cur.unit) if tol else {}
        self.typed = dict(value=value, text=str(text).strip(), display=format_manual(value, _unit_of(self.spec.q), sig), sig=sig,
                          tur=tartur.format_ratio(res.get('tur')) if res else '')
        return True, ''


    @property
    def needs_attention(self) -> bool:
        return self.cur.status == NOT_IN_SCOPE or self.typed is not None


class ReviewModel:
    def __init__(self, specs, default_standard=None, asset='', procedure='', title=''):
        self.asset, self.procedure, self.title = asset, procedure, title
        self.engine_default = default_standard
        self.default_std = default_standard
        self.rows = [Row(s, default_standard) for s in specs]
        self.choices = {}

    # ---- queries
    def counts(self) -> dict:
        c = {k: 0 for k in STATUSES}
        c[NO_UNC] = 0
        for r in self.rows:
            c[r.status] = c.get(r.status, 0) + 1
        c['attention'] = sum(1 for r in self.rows if r.needs_attention)
        c['changed'] = sum(1 for r in self.rows if r.changed)
        c['all'] = len(self.rows)
        return c

    def visible(self, name='All') -> list:
        if name == 'Needs attention':
            return [r for r in self.rows if r.needs_attention]
        if name == 'Changed by me':
            return [r for r in self.rows if r.changed]
        return list(self.rows)

    def options(self, idx) -> list:
        row = self.rows[idx]
        if idx not in self.choices:
            self.choices[idx] = offered_standards(row.spec)
        return self.choices[idx]

    def common_options(self, indexes) -> list:
        """Standards every selected changeable row can use."""
        sets = [set(self.options(i)) for i in indexes if not self.rows[i].spec.locked]
        if not sets:
            return []
        common = set.intersection(*sets)
        return [k for k in SOURCE_STANDARDS if k in common]

    # ---- changes
    def set_standard(self, idx, standard) -> bool:
        """Set one row's standard.  False (nothing changed) for a locked row or a standard the sheets cannot describe at that point."""
        row = self.rows[idx]
        key = key_of(standard)
        if row.spec.locked or key not in self.options(idx):
            return False
        row.manual = key
        row.follow(self.default_std)
        return True

    def set_typed(self, idx, text):
        """Type an uncertainty for a not-in-scope row (empty text clears it).  (ok, message)."""
        return self.rows[idx].set_typed(text)

    def set_standard_many(self, indexes, standard) -> int:
        return sum(1 for i in indexes if self.set_standard(i, standard))

    def set_default(self, standard):
        """The run default: every changeable row without its own choice follows it."""
        key = key_of(standard)
        self.default_std = key or self.engine_default
        for i, r in enumerate(self.rows):
            if r.spec.locked:
                continue
            if r.manual is None and key and key not in self.options(i):       # a default a row's sheet cannot describe leaves that row on the engine's standard
                r.follow(r.spec.default_std)
            else:
                r.follow(self.default_std)

    def reset(self):
        self.default_std = self.engine_default
        for r in self.rows:
            r.manual = None
            r.typed = None
            r.follow(self.default_std)

    # ---- the record stored with the report
    def changes(self, by='', when='') -> list:
        out = []
        for r in self.rows:
            if not (r.changed or r.applied):
                continue
            s, e = r.spec, r.cur
            ch = dict(idx=s.idx, step=s.step, section=s.section, description=s.description, nominal=s.nominal_text,
                      original_standard=(None if (r.applied and not r.changed) else s.default_std), standard=r.standard, uncertainty=r.reported_text, tar=r.tar_text, tur=r.tur_text,
                      budget=e.budget, scope_minimum=e.cmc, reported=e.reported, unit=e.unit, status=r.status, manual=r.typed is not None)
            if r.typed is not None:                                  # a typed uncertainty: the value as entered, who entered it and when
                ch.update(manual_value=r.typed['value'], manual_text=r.typed['text'], entered_by=by, entered_at=when)
                ch['standard'] = s.default_std
            out.append(ch)
        return out

    def table(self) -> list:
        out = []
        for r in self.rows:
            s, e = r.spec, r.cur
            out.append(dict(idx=s.idx, step=s.step, description=s.description, nominal=s.nominal_text, standard=r.standard, default_standard=s.default_std,
                            budget=fmt(e.budget, e.unit), scope_minimum=fmt(e.cmc, e.unit), reported=r.reported_text, tur=r.tur_text,
                            status=r.status, locked=s.locked))
        return out

    def record(self, by='', when='') -> dict:
        return dict(asset=self.asset, procedure=self.procedure, default_standard=self.default_std, engine_default=self.engine_default,
                    changed=sum(1 for r in self.rows if r.changed), manual=sum(1 for r in self.rows if r.typed is not None),
                    changes=self.changes(by, when), table=self.table())


def review_block(models, by='', when='') -> dict:
    """The record that goes into details['uncertainty_review'] (and so into the report snapshot).  `by` = the technician field, `when` = ISO time."""
    if not when:
        from datetime import datetime
        when = datetime.now().isoformat(timespec='seconds')
    return {'version': FORMAT_VERSION, 'reviews': [m.record(by, when) for m in models]}


# ----------------------------------------------------------------------------------------------------------------------------------------- engines
def _clean_text(x):
    return '' if x is None else str(x)


def _default_standard(app, p):
    """The standard the engine itself passes for this point (so an untouched row prints what it always printed)."""
    if hasattr(app, 'standard_for'):
        return app.standard_for(p)
    if hasattr(app, 'cal_key'):
        return app.cal_key
    return '5560A'                                          # Truevolt, 34401A, 8846A: fixed to the 5560A in the engine


def _spec_point_spec(app, i, p, row) -> PointSpec:
    import tartur_wiring
    low, high = tartur_wiring.point_limits(p)
    std = _default_standard(app, p)
    printed = {k: row.get(k, '') for k in ('Uncertainty', 'TAR', 'TUR')}
    locked = ''
    if p.get('zero_offset') or p.get('source') == 'none':
        locked = 'No source for this point'
    elif p.get('kind') == 'FREQ':
        locked = 'Frequency: measured against the lab standard'
    elif not std:
        locked = 'No calibrator applies'
    elif not row.get('Uncertainty'):
        locked = 'No uncertainty is printed for this point'
    return PointSpec(i, _clean_text(p.get('id', p.get('ref', i + 1))), row.get('Section', ''), row.get('Description', ''), row.get('Nominal', ''), p, p,
                     low, high, p['unit'], std, locked, printed)


def _handheld_spec(app, i, p, row) -> PointSpec:
    printed = {k: row.get(k, '') for k in ('Uncertainty', 'TAR', 'TUR')}
    base = dict(step=_clean_text(p.get('id', i + 1)), section=row.get('Section', ''), description=row.get('Description', ''), nominal=row.get('Nominal', ''))
    plain = dict(kind=p.get('kind', ''), nominal=0, unit=p.get('base_unit', ''), frequency=None, range=None, source='none')
    if p.get('test') != 'numeric' or not app.has_uncertainty(p):
        reason = 'Not a numeric point' if p.get('test') != 'numeric' else 'No uncertainty for this point'
        if p.get('test') == 'beeper':
            reason = 'Continuity check: scope CMC only'
        return PointSpec(i, base['step'], base['section'], base['description'], base['nominal'], plain, plain, None, None, plain['unit'], None, reason, printed)
    factor = Decimal(str(p['factor']))
    clean = lambda d: float(f'{float(d * factor):.9g}')                # noqa: E731  (as handheld_dmm.certificate_fields)
    kind = 'OHM2' if p['kind'] == 'OHM' else p['kind']
    a = p['applied']
    q = dict(kind=kind, nominal=a['value'], frequency=a.get('frequency'), unit=p.get('unc_unit') or p['base_unit'], range=None)     # as certificate_row
    q_tar = dict(kind=kind, nominal=a['value'], frequency=a.get('frequency'), unit=p['base_unit'], range=None)                       # as certificate_fields
    locked = ''
    if p.get('unc_kind') == 'FREQ':
        q = dict(kind='FREQ', nominal=a['frequency'], frequency=None, unit='Hz', range=None)
        q_tar = dict(q)
        locked = 'Frequency: measured against the lab standard'
    prev = getattr(app, '_row_std', None)
    try:
        if hasattr(app, 'standard_of') and hasattr(app, '_record_for'):      # user-built datasheet: the standard that did the point
            app._row_std = app.standard_of(p, app._record_for(p))
        std = app.calibrator_model()
    finally:
        app._row_std = prev
    if not locked and not std:
        locked = 'No calibrator applies'
    if not locked and not printed['Uncertainty']:
        locked = 'No uncertainty is printed for this point'
    return PointSpec(i, base['step'], base['section'], base['description'], base['nominal'], q, q_tar, clean(Decimal(p['low'])), clean(Decimal(p['high'])),
                     p['base_unit'], std, locked, printed)


def specs_for(app, kinds=None):
    """(specs, default_standard) for an engine App.  Multimeter engines (certificate_rows_and_points) are built here; the oscilloscope / generator
    engines (certificate_pairs: fgen, MDO4000C, TDS2000C; WaveSurfer: certificate_source_records) by report_review_adapters.
    `kinds` (WaveSurfer only): the result kinds the report will print, when the caller knows them.  Raises TypeError for an engine not covered."""
    if not hasattr(app, 'certificate_rows_and_points'):
        import report_review_adapters as A
        return A.specs_for(app, kinds)
    rows, pts = app.certificate_rows_and_points()
    handheld = hasattr(app, 'has_uncertainty') and hasattr(app, 'calibrator_model')
    out = []
    for i, (row, p) in enumerate(zip(rows, pts)):
        out.append(_handheld_spec(app, i, p, row) if handheld else _spec_point_spec(app, i, p, row))
    return out, first_default(out)


def first_default(specs):
    for s in specs:
        if not s.locked and s.default_std:
            return s.default_std
    return None
