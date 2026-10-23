"""Datasheet Builder: 'automate' - which imported standard can SOURCE (or MEASURE) each test point, with TAR / TUR, and what today's drivers can drive.

    import datasheet_builder_match as dm
    res = dm.match_datasheet(ds, period=None, db_path=None, overrides=None)      # MatchResult
    res.assignments['dcv.r10.+5']      -> Assignment(status 'assigned'|'uncovered'|'manual', standard '5522A', tur, tar, candidates[...], ...)
    res.uncovered                      -> [Assignment ...] each with .reason (code) and .message
    res.summary()                      -> {function id: {'points', 'assigned', 'uncovered', 'manual', 'automatable', 'unverified'}}
    dm.driver_table()                  -> [dict(model, label, role, driver, scope_driver, imported, functions={kind: {status, via, note}}, notes)]
    dm.automation_status('5522A', 'DCV')  -> Capability(status 'ok' | 'unverified' | 'manual' | 'no', driver, via, note);   dm.automation_text(cap)

What it decides (direction 'measure' = the UUT measures, so a standard must SOURCE the stimulus; 'source' = the UUT outputs, so a standard must MEASURE it):
  * COVERAGE  from the imported standards' specification rows (specmanager StandardSpec.lookup): function, value range, frequency band.  Nothing is guessed:
    a point no row covers is UNCOVERED with a code - no_standard_for_function, out_of_range, frequency_too_high, frequency_too_low, frequency_gap,
    frequency_not_specified, no_spec_row, unsupported_waveform, bad_point - and a message that names the limit that was exceeded.
  * UNCERTAINTY  built like uncertainty_budget: standard accuracy / coverage divisor, calibrator resolution / sqrt(12), expanded k = 2, then
    max(budget, A2LA scope CMC) rounded UP (ub.ceil_sig): a reported uncertainty is never below the lab's CMC.  Kinds the scope does not cover (temperature,
    scope tests, generator tests) have no CMC clamp (cmc is None, noted).
  * TAR = tolerance / standard accuracy; TUR = tolerance / reported uncertainty; tolerance = half the width of the UUT limits for the period.  Units are never
    converted (tartur's rule): a dB tolerance against a volt uncertainty gives no ratio and the candidate is ranked on relative uncertainty instead.
  * RANK  covered candidates: best TUR (compared as printed, rounded down to 0.1) first, then the lab default order for that function (LAB_DEFAULT), then
    smaller relative uncertainty, then model name.  `overrides` ({point id: model} or ds.assignments) replace the automatic choice; an override naming
    a standard that does not cover the point stays visible as an uncovered assignment (reason from that candidate) - never silently changed.
  * AUTOMATION  independent of coverage: DRIVER_TABLE says what the driver of each standard can set / read today.  'ok' = commands used by working
    procedures; 'unverified' = driver exists but the commands are not confirmed on hardware (listed in UNVERIFIED); 'manual' = the standard can do it but no driver
    call exists, so the operator sets it by hand; 'no' = not possible.  Assignment.automation / automation_note / automatable_alternative say it per point.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

import datasheet_builder as db
import specmanager as sm
import tartur
import uncertainty
import uncertainty_budget as ub
from datasheet_builder import D, KINDS

# ============================================================================================================== drivers
OK, UNVERIFIED, MANUAL, NO = 'ok', 'unverified', 'manual', 'no'


@dataclass(frozen=True)
class Capability:
    status: str
    driver: str = ''          # driver class that would do it ('' = none)
    via: str = ''             # method / path in that driver
    note: str = ''

    @property
    def can_automate(self):
        return self.status in (OK, UNVERIFIED)

    def to_dict(self):
        return {'status': self.status, 'driver': self.driver, 'via': self.via, 'note': self.note}


def _c(status, driver, via='', note=''):
    return Capability(status, driver, via, note)


_CAL = 'Fluke5522A'
_5520_NOTE = 'the 5520A remote commands for this output are the 5522A Operators Manual commands; the supplied 5520A Service Manual does not show them (UNVERIFIED on a 5520A)'
_5520_SCOPE_NOTE = 'the 5520A scope option (SC300) is not in the imported sheet and its SCOPE commands are not confirmed; use a 5522A or 5560A'
_UNV_CAP = 'capacitance output is not verified on hardware (NOTES.md: capacitance and thermocouple outputs unverified on the 5560A)'
_UNV_TC = 'thermocouple simulation is not verified on hardware; the error queue is read after it and the output is never enabled after a rejection'


def _calibrator(driver, scope_driver, scope_status, marker_status, scope_note, marker_note):
    return {
        'DCV': _c(OK, driver, 'set_output_volts(v, dc=True)'), 'ACV': _c(OK, driver, 'set_output_volts(v, f)'),
        'DCI': _c(OK, driver, 'set_output_amps(a, dc=True)'), 'ACI': _c(OK, driver, 'set_output_amps(a, f)'),
        'OHM2': _c(OK, driver, 'set_output_ohms(r)'),
        'OHM4': _c(OK, driver, 'set_output_ohms(r)', 'the 4-wire connection / COMP is set by the operator (prompted), the driver sends the same OUT command'),
        'CAP': _c(UNVERIFIED, driver, 'set_output_capacitance(c)', _UNV_CAP),
        'FREQ': _c(OK, driver, 'set_output_volts(amplitude, f)', 'sourced as an AC volts point at the frequency (as the handheld 87V / 110 Hz points)'),
        'PERIOD': _c(OK, driver, 'set_output_volts(amplitude, 1/T)', 'sourced as an AC volts point at 1 / period'),
        'TEMP': _c(UNVERIFIED, driver, 'set_output_temperature(c, tc_type)', _UNV_TC),
        'DIODE': _c(OK, driver, 'set_output_volts(v, dc=True)', 'the calibrator supplies the forward voltage'),
        'CONT': _c(OK, driver, 'set_output_ohms(r)'),
        'SCOPE_GAIN': _c(scope_status, scope_driver, 'select_scope_dcv + set_dc_volts', scope_note),
        'SCOPE_OFFSET': _c(scope_status, scope_driver, 'select_scope_dcv + set_dc_volts', scope_note),
        'SCOPE_BW': _c(scope_status, scope_driver, 'select_scope_levsine + set_levsine(vpp, f)', scope_note),
        'SCOPE_TRIGGER': _c(scope_status, scope_driver, 'select_scope_levsine + set_levsine(vpp, f)', scope_note),
        'SCOPE_TIMEBASE': _c(marker_status, scope_driver, 'select_scope_marker + set_marker_period(s)', marker_note),
    }


def _calibrator_5520A():
    """The 5520A's functions: the 5522A's output calls, every one UNVERIFIED on a 5520A (the supplied Service Manual shows only a few commands), the scope kinds not available."""
    out = {}
    for kind, cap in _calibrator('Fluke5520A', 'Fluke5520A', NO, NO, '', '').items():
        if kind.startswith('SCOPE_'):
            out[kind] = _c(NO, 'Fluke5520A', '', _5520_SCOPE_NOTE)
        else:
            out[kind] = _c(UNVERIFIED, cap.driver, cap.via, cap.note or _5520_NOTE)
    return out


@dataclass
class DriverInfo:
    model: str                     # as in specmanager (and the lab's standards list)
    label: str
    role: str                      # 'source' (sources a stimulus) | 'measure' (measures a UUT output)
    driver: str                    # driver class name in drivers/ ('' = none)
    functions: dict = field(default_factory=dict)
    scope_driver: str = ''
    spec_pending: bool = False     # a driver exists but no specification sheet is imported for it (frequency counters)
    notes: str = ''

    def to_dict(self):
        return {'model': self.model, 'label': self.label, 'role': self.role, 'driver': self.driver, 'scope_driver': self.scope_driver,
                'functions': {k: v.to_dict() for k, v in self.functions.items()}, 'spec_pending': self.spec_pending, 'notes': self.notes}


_5522_SCOPE_NOTE = ('Fluke5522AScope: SCOPE VOLT / LEVSINE / MARKER and the SCOPE? reply text are NOT confirmed (5520A Programmers Guide gives only SCOPE, SCOPE?, '
                    'OUT_IMP, TMWAVE); every setting is read back and the output is never operated after a rejection (NOTES.md TDS2000C items)')
_5560_MARK = 'SCOPE MARKER / OUT <s>S are not verified on a 5560A (the SCOPE? reply was confirmed from the front panel 2026-10-21)'

DRIVER_TABLE = {
    '5522A': DriverInfo('5522A', 'Fluke 5522A multi-product calibrator', 'source', 'Fluke5522A',
                        _calibrator('Fluke5522A', 'Fluke5522AScope', UNVERIFIED, UNVERIFIED, _5522_SCOPE_NOTE, _5522_SCOPE_NOTE),
                        scope_driver='Fluke5522AScope'),
    '5520A': DriverInfo('5520A', 'Fluke 5520A multi-product calibrator', 'source', 'Fluke5520A', _calibrator_5520A(),
                        notes='The driver reuses the 5522A command set; only ERR?, *CLS, *OPC?, OPER, OUT? and the DC-current OUT form are confirmed by the supplied 5520A Service Manual '
                              '(Fluke5520A.unverified_summary()). The scope option (SC300) is not in the imported sheet.'),
    '5560A': DriverInfo('5560A', 'Fluke 5560A multi-product calibrator', 'source', 'Fluke5560A',
                        _calibrator('Fluke5560A', 'Fluke5560A', OK, UNVERIFIED, '', _5560_MARK), scope_driver='Fluke5560A',
                        notes='The imported 5560A sheet has no scope-output rows, so scope bandwidth / time base points cannot be costed on it.'),
    '5790B': DriverInfo('5790B', 'Fluke 5790B AC measurement standard', 'measure', 'Fluke5790B', {
        'GEN_AMPL': _c(UNVERIFIED, 'Fluke5790B', 'select_input + set_range_for + measure()', 'all 5790B commands are from the manual, not run on hardware'),
        'GEN_FLAT': _c(UNVERIFIED, 'Fluke5790B', 'WBND input + require_wideband + measure()', 'wideband option needed; commands not run on hardware'),
        'GEN_OFFSET': _c(NO, 'Fluke5790B', '', 'the driver reads AC (MEAS?) only; there is no DC mode in it'),
        'GEN_FREQ': _c(NO, 'Fluke5790B', '', 'MEAS? also returns a frequency but the sheet gives no frequency accuracy'),
        'ACV': _c(UNVERIFIED, 'Fluke5790B', 'measure()', 'UUT as an AC source')}),
    '53131A': DriverInfo('53131A', 'Agilent 53131A universal counter', 'measure', 'Keysight53131A', {
        'GEN_FREQ': _c(UNVERIFIED, 'Keysight53131A', 'read_frequency()', 'driver written from the Programming Guide, not run on hardware'),
        'FREQ': _c(UNVERIFIED, 'Keysight53131A', 'read_frequency()', 'UUT as a frequency source')}, spec_pending=True,
        notes='No specification sheet could be imported (the Programming Guide has no accuracy tables): coverage is by the driver only, TUR is blank.'),
    '53132A': DriverInfo('53132A', 'Agilent 53132A universal counter', 'measure', 'Keysight53132A', {
        'GEN_FREQ': _c(UNVERIFIED, 'Keysight53132A', 'read_frequency()', 'driver written from the Programming Guide, not run on hardware'),
        'FREQ': _c(UNVERIFIED, 'Keysight53132A', 'read_frequency()', 'UUT as a frequency source')}, spec_pending=True,
        notes='No specification sheet could be imported (the Programming Guide has no accuracy tables): coverage is by the driver only, TUR is blank.'),
    '96270A': DriverInfo('96270A', 'Fluke 96270A RF reference source', 'source', 'Fluke96270A', {},
                         notes='Driver sets RF frequency / level in dBm (set_rf). Its imported sheet rows are RF level accuracy in dB (kind OTHER), which '
                               'cannot be matched to a scope or DMM point yet; no builder function uses it today.'),
    '8563E': DriverInfo('8563E', 'HP 8563E spectrum analyzer', 'measure', '', {}, notes='Imported specification only; there is no driver.'),
    '8902A': DriverInfo('8902A', 'HP 8902A measuring receiver', 'measure', '', {}, notes='Imported specification only; there is no driver.'),
}
UNVERIFIED_ITEMS = sorted({f'{m.model}: {k} - {c.note or c.via}' for m in DRIVER_TABLE.values() for k, c in m.functions.items() if c.status == UNVERIFIED})

LAB_DEFAULT = {   # preferred standard per function when TURs tie: the lab's own habit (handheld / Truevolt use the 5560A, scope procedure the 5522A, generators the 5790B + counter)
    'dmm': ['5560A', '5522A'], 'scope': ['5522A', '5560A'], 'GEN_AMPL': ['5790B'], 'GEN_FLAT': ['5790B'], 'GEN_OFFSET': ['5790B'],
    'GEN_FREQ': ['53132A', '53131A'],
}


def lab_default(kind):
    return LAB_DEFAULT.get(kind) or LAB_DEFAULT.get(KINDS[kind]['family']) or []


def automation_status(model, kind, direction=None):
    """Capability of the driver of `model` for function `kind`.  An unknown model or a function the driver table does not list is 'manual' when
    the model is a known standard without that driver call, 'no' when there is no driver at all."""
    info = DRIVER_TABLE.get(str(model))
    if info is None:
        return Capability(NO, '', '', f'{model}: no driver is known for this model')
    cap = info.functions.get(kind)
    if cap is not None:
        return cap
    if not info.driver:
        return Capability(NO, '', '', f'{model} has no driver in drivers/')
    return Capability(MANUAL, info.driver, '', f'{info.driver} has no call for {kind}; the operator sets it by hand')


def automation_text(cap, kind=''):
    """The sentence for the UI: 'can automate' / 'can automate (commands unverified)' / 'cannot automate (no driver for X)'."""
    if cap.status == OK:
        return 'can automate'
    if cap.status == UNVERIFIED:
        return 'can automate (commands not yet verified on hardware)'
    if cap.status == MANUAL:
        return f'cannot automate (no {cap.driver} call for {kind}: set by hand)' if kind else 'cannot automate (set by hand)'
    return f'cannot automate (no driver for {kind})' if kind else 'cannot automate (no driver)'


def driver_table(db_path=None):
    """[dict] for the UI: every standard the matcher knows (imported or driver-only) with what its driver can do today.  `imported` says whether
    its specification sheet is in lab_registry.sqlite3."""
    imported = {s['model'] for s in _imported(db_path)}
    rows = []
    for model, info in DRIVER_TABLE.items():
        d = info.to_dict()
        d['imported'] = model in imported
        rows.append(d)
    for m in sorted(imported - set(DRIVER_TABLE)):
        rows.append({'model': m, 'label': m, 'role': 'source', 'driver': '', 'scope_driver': '', 'functions': {}, 'spec_pending': False,
                     'notes': 'Imported specification only; there is no driver.', 'imported': True})
    return rows


# ============================================================================================================== standards
def _imported(path=None):
    rows = sm.standards(path)
    if not rows:
        sm.seed(path=path)
        rows = sm.standards(path)
    return rows


@dataclass
class Std:
    model: str
    spec: object                    # specmanager.StandardSpec or None
    info: DriverInfo
    assets: list = field(default_factory=list)


def load_standards(db_path=None, models=None):
    """[Std]: every imported standard, plus driver-only entries (counters) that have no sheet.  `models` limits the list."""
    out, seen = [], set()
    for s in _imported(db_path):
        m = s['model']
        if models and m not in models:
            continue
        spec = sm.standard(s['id'], db_path)
        info = DRIVER_TABLE.get(m) or DriverInfo(m, m, 'source', '', {}, notes='Imported specification only; there is no driver.')
        out.append(Std(m, spec, info, [a for a, _ in sm.assets_of(s['id'], db_path)]))
        seen.add(m)
    for m, info in DRIVER_TABLE.items():
        if info.spec_pending and m not in seen and (not models or m in models):
            out.append(Std(m, None, info))
    return out


# ============================================================================================================== stimulus per function
@dataclass
class Stim:
    kind: str                       # specmanager kind
    value: Decimal                  # value to look up (SI, positive)
    frequency: Decimal = None
    direction: str = 'output'       # specmanager row direction: 'output' (standard sources) | 'input' (standard measures)
    variant: str = ''
    unit: str = ''                  # required row unit ('' = any)
    scale: Decimal = D(1)           # datasheet unit per row unit (Vpp per V rms ...)
    coverage: list = field(default_factory=list)      # further Stim that must also be covered (the amplitude of a frequency point)
    error: tuple = None             # (code, message) when the point cannot be turned into a lookup


def _rms_factor(waveform, amp_unit):
    """Datasheet amplitude -> V rms factor (Decimal) or None when unsupported.  Sine and square only."""
    wave = (waveform or 'SIN').upper()
    with localcontext() as c:
        c.prec = db.PREC
        if amp_unit == 'Vrms':
            return D(1)
        if wave in ('SIN', 'SINE'):
            return D(1) / (D(2) * D(2).sqrt()) if amp_unit == 'Vpp' else D(1) / D(2).sqrt() if amp_unit == 'Vp' else None
        if wave in ('SQU', 'SQUARE'):
            return D(1) / 2 if amp_unit == 'Vpp' else D(1) if amp_unit == 'Vp' else None
    return None


def stimulus(fn, p):
    """What the standard has to source / measure for point p of function fn (a Stim)."""
    k, nom, f = fn.kind, abs(p.nominal), p.frequency
    out_dir = 'output' if fn.direction == 'measure' else 'input'
    s = {**fn.settings, **p.settings}
    if k in ('DCV', 'DIODE', 'SCOPE_GAIN', 'SCOPE_OFFSET'):
        return Stim('DCV', nom, None, out_dir)
    if k == 'DCI':
        return Stim('DCI', nom, None, out_dir)
    if k == 'ACV':
        return Stim('ACV', nom, f, out_dir)
    if k == 'ACI':
        return Stim('ACI', nom, f, out_dir)
    if k in ('OHM2', 'OHM4', 'CONT'):
        return Stim('OHM', nom, None, out_dir, variant={'OHM2': '2-wire', 'OHM4': '4-wire'}.get(k, ''))
    if k == 'CAP':
        return Stim('CAP', nom, None, out_dir)
    if k in ('FREQ', 'PERIOD'):
        freq = nom if k == 'FREQ' else (D(1) / nom)
        cov = [Stim('ACV', p.amplitude, freq, out_dir)] if p.amplitude else []
        return Stim('FREQ', freq, None, out_dir, coverage=cov)
    if k == 'TEMP':
        return Stim('TEMP', nom if p.nominal >= 0 else abs(p.nominal), None, out_dir, variant='Type ' + str(s.get('tc_type', 'K')), unit='degC')
    if k in ('SCOPE_BW', 'SCOPE_TRIGGER'):
        return Stim('FLAT', p.amplitude or D(0), f, out_dir)
    if k == 'SCOPE_TIMEBASE':
        return Stim('TIME', nom, None, out_dir)
    if k == 'GEN_FREQ':
        return Stim('FREQ', nom, None, 'input')
    if k == 'GEN_OFFSET':
        return Stim('DCV', nom, None, 'input')
    if k in ('GEN_AMPL', 'GEN_FLAT'):
        wave, au = s.get('waveform', 'SIN'), s.get('amp_unit', 'Vrms')
        if k == 'GEN_AMPL' and str(wave).upper() == 'DC':
            return Stim('DCV', nom, None, 'input')
        factor = _rms_factor(wave, au)
        if factor is None:
            return Stim(k, nom, f, 'input', error=('unsupported_waveform', f'waveform {wave} with amplitude unit {au}: only SIN / SQU with Vrms, Vpp or Vp can be converted to rms'))
        if k == 'GEN_FLAT':
            level = (p.amplitude or D(0))
            return Stim('FLAT', level * factor, f, 'input')
        rms = nom * factor
        variant = 'non-sine' if (wave or '').upper() in ('SQU', 'SQUARE') else ''
        return Stim('ACV', rms, f, 'input', variant=variant, scale=D(1) / factor if factor else D(1))
    return Stim(k, nom, f, out_dir, error=('bad_point', f'no stimulus rule for {k}'))


# ============================================================================================================== coverage and uncertainty
def _view(spec, unit):
    """A StandardSpec whose rows are filtered to one row unit (so degF rows never answer a degC point)."""
    if not unit:
        return spec
    import copy
    v = copy.copy(spec)
    v.rows = [r for r in spec.rows if r['unit'] == unit]
    return v


def _lookup(spec, st):
    view = _view(spec, st.unit)
    value, freq = float(st.value), (float(st.frequency) if st.frequency is not None else None)
    hit = view.lookup(st.kind, value, frequency=freq, variant=st.variant, direction=st.direction)
    if hit is None and st.variant and st.kind == 'OHM':      # 2-wire / 4-wire: a sheet with one resistance function serves both (never done for a thermocouple type)
        hit = view.lookup(st.kind, value, frequency=freq, variant='', direction=st.direction)
        if hit is not None:
            return hit, view, f'no {st.variant} row on this sheet; the general row is used'
    return hit, view, ''


def _band(r):
    lo, hi = r['amp_lo'], r['amp_hi']
    return sorted((abs(lo), abs(hi))) if lo * hi >= 0 else (0.0, max(abs(lo), abs(hi)))


def explain(spec, st, view=None):
    """(code, message) why the standard has no row for this stimulus."""
    view = view or _view(spec, st.unit)
    value = float(st.value)
    freq = float(st.frequency) if st.frequency is not None else None
    try:
        rows = [r for r in view._eligible(st.kind, st.variant, st.direction) if r['amp_lo'] is not None]
    except Exception:
        rows = [r for r in view.rows if r['kind'] == st.kind and r['direction'] == st.direction and r['amp_lo'] is not None]
    name = f'{spec.model}'
    if not rows and st.variant and st.kind == 'OHM':
        rows = [r for r in view._eligible(st.kind, '', st.direction) if r['amp_lo'] is not None]
    if not rows:
        what = st.kind + (f' ({st.variant})' if st.variant else '')
        return 'no_standard_for_function', f'{name} has no {what} ({"source" if st.direction == "output" else "measure"}) specification on its sheet'
    lo_all, hi_all = min(_band(r)[0] for r in rows), max(_band(r)[1] for r in rows)
    inside = [r for r in rows if _band(r)[0] <= value <= _band(r)[1]]
    unit = rows[0]['unit']
    if not inside:
        side = 'above' if value > hi_all else 'below'
        return 'out_of_range', (f'{name}: {db.format_si(st.value, unit)} is {side} what it covers '
                                f'({db.format_si(D(repr(lo_all)), unit)} to {db.format_si(D(repr(hi_all)), unit)})')
    banded = [r for r in inside if r['freq_lo'] is not None]
    if banded:
        if freq is None:
            return 'frequency_needed', f'{name}: the specification at {db.format_si(st.value, unit)} depends on frequency, and the point has none'
        fmax, fmin = max(r['freq_hi'] for r in banded), min(r['freq_lo'] for r in banded)
        if freq > fmax:
            return 'frequency_too_high', f'{name}: {db.format_si(st.value, unit)} is specified only up to {db.format_si(D(repr(fmax)), "Hz")}, the point needs {db.format_si(st.frequency, "Hz")}'
        if freq < fmin:
            return 'frequency_too_low', f'{name}: {db.format_si(st.value, unit)} is specified only from {db.format_si(D(repr(fmin)), "Hz")}, the point needs {db.format_si(st.frequency, "Hz")}'
        return 'frequency_gap', f'{name}: {db.format_si(st.frequency, "Hz")} falls between its specified frequency bands at {db.format_si(st.value, unit)}'
    if freq not in (None, 0) and st.kind in ('ACV', 'ACI'):
        return 'frequency_not_specified', f'{name}: no frequency band is specified for {st.kind} at {db.format_si(st.value, unit)}'
    return 'no_spec_row', f'{name}: no specification for the standard\'s period at this point'


def budget(spec, hit, kind, nominal, frequency, scope, basis='generate'):
    """ub.Budget for a hit: standard accuracy / divisor, resolution / sqrt(12), CMC clamp.  Same arithmetic as uncertainty_budget.build."""
    cmc_kind = {'OHM2': 'OHM', 'OHM4': 'OHM'}.get(kind, kind)
    b = ub.Budget(cmc_kind, nominal, hit.row['unit'], spec, frequency)
    if scope is not None and cmc_kind in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'FREQ'):
        b.cmc = scope.dmm(cmc_kind, nominal, None, frequency, basis=basis)
    b.hit = hit
    div, why = spec.divisor()
    b.add(f'{spec.model} accuracy', hit.limit / div, 1.0, f'{hit.limit:.6g} / {div:g} ({why})')
    res, src = spec.resolution(hit)
    if res:
        b.add('Resolution', res / math.sqrt(12), 1.0, f'{res:.6g} / sqrt(12) ({src})')
    else:
        b.notes.append('resolution of this range is not recorded: not in the budget')
    if b.emu is not None:
        b.reported = ub.ceil_sig(max(b.emu, b.cmc or 0.0))
    return b


@dataclass
class Candidate:
    standard: str
    covered: bool = False
    reason: str = ''                  # '' when covered, else a code (see module doc)
    message: str = ''
    automation: str = NO              # ok | unverified | manual | no
    automation_note: str = ''
    driver: str = ''
    spec_known: bool = True
    accuracy: float = None            # published +/- accuracy at the point, in the datasheet unit
    uncertainty: float = None         # reported (CMC-clamped, rounded up), datasheet unit
    cmc: float = None
    tolerance: float = None
    tar: float = None
    tur: float = None
    rel_unc: float = None
    row: str = ''                     # the specification row used (function / range label)
    notes: list = field(default_factory=list)
    rank: int = 0

    @property
    def can_automate(self):
        return self.automation in (OK, UNVERIFIED)

    def to_dict(self):
        return {k: getattr(self, k) for k in ('standard', 'covered', 'reason', 'message', 'automation', 'automation_note', 'driver', 'spec_known', 'accuracy',
                                              'uncertainty', 'cmc', 'tolerance', 'tar', 'tur', 'rel_unc', 'row', 'notes', 'rank')}


@dataclass
class Assignment:
    point_id: str
    function_id: str
    kind: str
    direction: str
    status: str = 'uncovered'         # assigned | uncovered | manual
    standard: str = ''
    driver: str = ''
    automation: str = NO
    automation_note: str = ''
    tur: float = None
    tar: float = None
    uncertainty: float = None
    tolerance: float = None
    overridden: bool = False
    reason: str = ''
    message: str = ''
    mode: str = 'auto'                # auto | override | manual | none
    automatable_alternative: str = '' # best covered standard that CAN be automated when the chosen one cannot
    candidates: list = field(default_factory=list)

    @property
    def can_automate(self):
        return self.status == 'assigned' and self.automation in (OK, UNVERIFIED)

    def to_dict(self, candidates=False):
        d = {k: getattr(self, k) for k in ('point_id', 'function_id', 'kind', 'direction', 'status', 'standard', 'driver', 'automation', 'automation_note',
                                           'tur', 'tar', 'uncertainty', 'tolerance', 'overridden', 'reason', 'message', 'mode', 'automatable_alternative')}
        if candidates:
            d['candidates'] = [c.to_dict() for c in self.candidates]
        return d


@dataclass
class MatchResult:
    period: str = ''
    assignments: dict = field(default_factory=dict)
    uncovered: list = field(default_factory=list)
    standards: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def summary(self):
        out = {}
        for a in self.assignments.values():
            s = out.setdefault(a.function_id, dict(points=0, assigned=0, uncovered=0, manual=0, automatable=0, unverified=0))
            s['points'] += 1
            s[{'assigned': 'assigned', 'uncovered': 'uncovered', 'manual': 'manual'}[a.status]] += 1
            if a.can_automate:
                s['automatable'] += 1
                s['unverified'] += a.automation == UNVERIFIED
        return out

    def to_dict(self):
        return {'period': self.period, 'assignments': {k: a.to_dict() for k, a in self.assignments.items()},
                'uncovered': [a.point_id for a in self.uncovered], 'summary': self.summary(), 'notes': list(self.notes)}


def _tur_bucket(c):
    return -1.0 if c.tur is None else math.floor(c.tur * 10 + 1e-7) / 10.0


def _rank(cands, kind):
    default = lab_default(kind)
    cov = [c for c in cands if c.covered]
    # a candidate without a driver (spec-only sheet: 3458A, 8563E, 8902A, light, coils) never outranks one with a driver: the plan must not lose automation
    cov.sort(key=lambda c: (0 if c.driver else 1, -_tur_bucket(c), default.index(c.standard) if c.standard in default else len(default),
                            c.rel_unc if c.rel_unc is not None else math.inf, c.standard))
    for i, c in enumerate(cov, 1):
        c.rank = i
    return cov


class Matcher:
    """Loads the standards once; match() can then be called again and again (e.g. when the person changes an override)."""

    def __init__(self, db_path=None, models=None, scope=None):
        self.db_path = db_path
        self.standards = load_standards(db_path, models)
        if scope is None:
            try:
                scope = uncertainty.load()
            except Exception:
                scope = None
        self.scope = scope

    def candidate(self, std, fn, p, st, lim):
        c = Candidate(std.model, driver=std.info.driver)
        cap = std.info.functions.get(fn.kind)
        if cap is None:
            cap = automation_status(std.model, fn.kind)
        c.automation, c.automation_note = cap.status, (cap.note or cap.via)
        if cap.driver:
            c.driver = cap.driver
        if st.error:
            c.reason, c.message = st.error
            return c
        want_role = 'source' if fn.direction == 'measure' else 'measure'
        tol = lim.tolerance if lim is not None else None
        if std.spec is None:                                      # driver only (counters): coverage by the driver, no numbers
            if std.info.role == want_role and fn.kind in std.info.functions:
                c.covered, c.spec_known = True, False
                c.notes.append('no specification sheet is imported for this instrument: TAR / TUR cannot be computed')
            else:
                c.reason, c.message = 'no_standard_for_function', f'{std.model} cannot {"source" if want_role == "source" else "measure"} {fn.kind}'
            return c
        hit, view, note = _lookup(std.spec, st)
        if hit is None:
            c.reason, c.message = explain(std.spec, st, view)
            return c
        for extra in st.coverage:                                 # e.g. the amplitude at the frequency of a frequency point
            h2, v2, _ = _lookup(std.spec, extra)
            if h2 is None:
                c.reason, c.message = explain(std.spec, extra, v2)
                return c
        c.covered = True
        if note:
            c.notes.append(note)
        c.row = f"{hit.row['function']} / {hit.row['label']}"
        basis = 'generate' if fn.direction == 'measure' else 'measure'
        b = budget(std.spec, hit, st.kind, float(st.value), float(st.frequency) if st.frequency is not None else None, self.scope, basis)
        scale = float(st.scale)
        c.accuracy = hit.limit * scale
        c.cmc = None if b.cmc is None else b.cmc * scale
        c.notes += b.notes
        if b.cmc is None:
            c.notes.append('not covered by the A2LA scope of accreditation: no CMC clamp possible')
        c.uncertainty = None if b.reported is None else b.reported * scale
        same_unit = hit.row['unit'] == fn.unit or (fn.unit == 'ohm' and hit.row['unit'] in ('ohm', 'Ohm'))
        c.tolerance = float(tol) if tol is not None else None
        if tol is None:
            c.notes.append('one-sided or missing limits: no tolerance, no TAR / TUR')
        elif not same_unit:
            c.notes.append(f'tolerance is in {fn.unit or "-"}, the standard is specified in {hit.row["unit"]}: ratios not computed (units are never converted)')
        else:
            res = tartur.from_values(float(tol), fn.unit, c.accuracy, fn.unit, c.uncertainty, fn.unit)
            c.tar, c.tur = res['tar'], res['tur']
        if c.uncertainty and p.nominal != 0:
            c.rel_unc = c.uncertainty / abs(float(p.nominal))
        return c

    def match(self, ds, period=None, overrides=None):
        period = period or ds.default_period
        res = MatchResult(period=period, standards=[s.model for s in self.standards])
        ov = dict(ds.assignments)
        ov.update(overrides or {})
        for fn, p in ds.all_points():
            if not p.enabled:
                continue
            a = Assignment(p.id, fn.id, fn.kind, fn.direction)
            res.assignments[p.id] = a
            try:
                lim = fn.limit_for(p, period, ds) if not KINDS[fn.kind].get('passfail') else None
            except db.DsError:
                lim = None
            try:
                st = stimulus(fn, p)
                if st.error is None and st.kind in ('ACV', 'ACI', 'FLAT') and fn.direction == 'measure' and st.frequency is None and fn.kind in ('ACV', 'ACI'):
                    st.error = ('bad_point', 'AC point without a frequency')
            except Exception as e:                                # never raise on one bad point
                st = Stim(fn.kind, abs(p.nominal), error=('bad_point', f'cannot work out the stimulus: {e}'))
            cands = [self.candidate(s, fn, p, st, lim) for s in self.standards]
            ranked = _rank(cands, fn.kind)
            a.candidates = ranked + [c for c in cands if not c.covered]
            choice, forced = None, ov.get(p.id)
            if forced in ('', 'MANUAL'):
                a.status, a.mode, a.standard, a.message = 'manual', 'manual', '', 'the operator uses a standard of their own choice'
                a.automation = MANUAL
                continue
            if forced:
                a.overridden, a.mode = True, 'override'
                choice = next((c for c in cands if c.standard == forced), None)
                if choice is None:
                    a.status, a.reason, a.message = 'uncovered', 'unknown_standard', f'{forced} is not a known standard'
                    res.uncovered.append(a)
                    continue
            elif ranked:
                choice = ranked[0]
            if choice is None or not choice.covered:
                a.status = 'uncovered'
                a.reason = (choice.reason if choice else '') or _best_reason(cands)
                a.message = (choice.message if choice else '') or _reason_text(cands, a.reason)
                if not cands:
                    a.reason, a.message = 'no_standard_for_function', 'no standard is available'
                res.uncovered.append(a)
                continue
            a.status, a.standard, a.driver = 'assigned', choice.standard, choice.driver
            a.automation, a.automation_note = choice.automation, choice.automation_note
            a.tur, a.tar, a.uncertainty, a.tolerance = choice.tur, choice.tar, choice.uncertainty, choice.tolerance
            if not choice.can_automate:
                alt = next((c for c in ranked if c.can_automate and c.standard != choice.standard), None)
                a.automatable_alternative = alt.standard if alt else ''
        res.notes = [f'unverified: {x}' for x in UNVERIFIED_ITEMS] if any(a.automation == UNVERIFIED for a in res.assignments.values()) else []
        return res


def _best_reason(cands):
    """The most informative reason among candidates: a standard that has the function but not the value beats 'no function'."""
    order = ('frequency_too_high', 'frequency_too_low', 'frequency_gap', 'frequency_needed', 'frequency_not_specified', 'out_of_range', 'no_spec_row',
             'unsupported_waveform', 'bad_point', 'no_standard_for_function')
    reasons = [c.reason for c in cands if c.reason]
    for r in order:
        if r in reasons:
            return r
    return 'no_standard_for_function'


def _reason_text(cands, code):
    msgs = [c.message for c in cands if c.reason == code and c.message]
    return '; '.join(msgs[:3]) if msgs else 'no standard covers this point'


def match_datasheet(ds, period=None, db_path=None, overrides=None, models=None, scope=None, matcher=None):
    """Assign a standard to every enabled point of `ds` for `period` (default ds.default_period).  See the module docstring."""
    m = matcher or Matcher(db_path, models, scope)
    return m.match(ds, period, overrides)
