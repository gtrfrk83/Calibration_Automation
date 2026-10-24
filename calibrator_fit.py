"""Can a calibrator source the points of a procedure?  The one question every calibrator picker asks before it offers a model.

The answer comes from the published specification the suite already holds for that calibrator (specmanager: `specs/standards/fluke_<model>_standard.json`),
the same rows `uncertainty_budget` and `tartur` use for the uncertainty / TAR of a report.  A calibrator can source a point when the model's sheet has a
specification row for that function, amplitude and frequency (`StandardSpec.lookup` / `lookup_temperature`); where there is no row the manufacturer does not
publish that output, and the calibrator picker must not offer the model for that point.  Nothing here is typed per procedure: the lists come from the
procedure's own points.

    fit = calibrator_fit.assess('5520A', calibrator_fit.dmm_requests(points))
    fit.complete          # every sourced point has a specification row
    fit.excluded          # [(Req, reason)] the points the model cannot source, with the sentence the picker shows
    fit.tooltip()         # the picker's explanation (also the UNVERIFIED notes for the model)

Nothing here sends a command, changes a limit or judges a result.  It also does not know about a calibrator option that the sheet does not carry
(the 5520A-SC scope option, non-sine waveforms): such a point is reported as NOT covered, with that reason, never assumed.

Request kinds (what the calibrator is asked to make): DCV ACV DCI ACI OHM CAP TEMP, plus SQUARE / DUTY (a non-sine source: the suite holds no specification
for them on the 5520A, see NOTES.md).  FREQ points of the DMM procedures are an AC volts source at the test frequency (Req kind 'ACV').
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
STANDARDS_DIR = HERE / 'specs' / 'standards'

# What the repository can say about commands on each calibrator (shown in the picker tooltip).  Filled from the driver COMMANDS registry, so it cannot drift.
MODEL_FILES = {'5520A': 'fluke_5520a_standard.json', '5522A': 'fluke_5522a_standard.json', '5560A': 'fluke_5560a_standard.json'}
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'TEMP', 'SQUARE', 'DUTY')
UNIT = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'CAP': 'F', 'TEMP': 'degC', 'SQUARE': 'V', 'DUTY': '%'}
NAME = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM': 'resistance', 'CAP': 'capacitance',
        'TEMP': 'thermocouple simulation', 'SQUARE': 'square wave', 'DUTY': 'duty cycle'}
BASE_UNITS = {'DCV': ('V',), 'ACV': ('V',), 'DCI': ('A',), 'ACI': ('A',), 'OHM': ('ohm',), 'CAP': ('F',), 'TEMP': ('C', 'degC')}
# the sheet function whose `limits` entry explains a missing row (specs/standards/fluke_5520a_standard.json, key 'limits')
LIMIT_FUNCTION = {'DCV': 'DC outputs', 'DCI': 'DC outputs', 'ACV': 'AC voltage, NORMAL', 'ACI': 'AC current, LCOMP off', 'OHM': 'Resistance',
                  'CAP': 'Capacitance', 'TEMP': 'Thermocouple'}


@dataclass
class Req:
    """One output a procedure asks of its calibrator."""
    kind: str                       # DCV ACV DCI ACI OHM CAP TEMP SQUARE DUTY
    value: float                    # SI base units (V, A, ohm, F, degC; SQUARE: V peak-to-peak)
    frequency: float | None = None  # Hz (AC kinds, SQUARE)
    label: str = ''                 # what the picker shows for the point ("2-14: AC volts 10 V @ 300 kHz")
    optional: bool = False          # a point the operator must opt into
    low: float | None = None        # the UUT limits (for TAR); None when not known
    high: float | None = None
    detail: str = ''                # free text added to the reason
    key: object = None              # the procedure's own id of the point (so an engine can find the point again)

    def text(self):
        from ui_theme_core import si_one
        num, sym = si_one(abs(self.value) if self.kind != 'TEMP' else self.value, UNIT[self.kind] if self.kind != 'TEMP' else 'degC')
        s = f'{NAME[self.kind]} {num} {sym}'.replace('  ', ' ')
        if self.frequency not in (None, 0):
            fn, fs = si_one(self.frequency, 'Hz')
            s += f' at {fn} {fs}'
        return s


@dataclass
class Verdict:
    ok: bool
    reason: str = ''
    accuracy: float | None = None       # published 1 year accuracy at the point (SI), when covered
    row: str = ''
    code: str = ''                      # datasheet_builder_match.explain code (out_of_range, frequency_too_high ...) when not covered


@dataclass
class Fit:
    model: str
    total: int = 0
    ok: list = field(default_factory=list)            # [(Req, Verdict)]
    excluded: list = field(default_factory=list)      # [(Req, Verdict)] default-run points the model cannot source
    optional_excluded: list = field(default_factory=list)   # the same for optional points (not run unless the operator opts in)
    notes: list = field(default_factory=list)
    min_tar: float | None = None
    low_tar: list = field(default_factory=list)       # [(Req, tar)] covered points with TAR below 1:1 (the calibrator is less accurate than the UUT limit)

    @property
    def complete(self):
        """Every point the run makes has a specification row of this model."""
        return not self.excluded

    def summary(self):
        n, x = self.total, len(self.excluded)
        if not x:
            tail = f'; {len(self.optional_excluded)} optional point(s) it cannot source' if self.optional_excluded else ''
            return f'{self.model}: all {n} calibrator points are inside its published specification{tail}'
        return f'{self.model}: cannot source {x} of {n} calibrator points'

    def reasons(self, limit=None):
        """[(sentence, [labels])] grouped by reason."""
        groups = {}
        for r, v in self.excluded:
            groups.setdefault(v.reason, []).append(r.label or r.text())
        out = [(why, labels) for why, labels in groups.items()]
        return out[:limit] if limit else out

    def tooltip(self, unverified=''):
        lines = [self.summary()]
        for why, labels in self.reasons():
            shown = ', '.join(labels[:6]) + (f' and {len(labels) - 6} more' if len(labels) > 6 else '')
            lines.append(f'- {why} ({len(labels)}): {shown}')
        kinds = list(dict.fromkeys(r.kind for r, _v in self.excluded))
        for k in kinds:
            lim = limits_text(self.model).get(LIMIT_FUNCTION.get(k, ''))
            if lim:
                lines.append(f'  Published output limits ({NAME[k]}, p. {lim[1]}): {lim[0]}')
        for r, v in self.optional_excluded[:4]:
            lines.append(f'- optional, not run unless ticked: {r.label or r.text()}: {v.reason}')
        if self.low_tar:
            lines.append(f'- TAR below 1:1 at {len(self.low_tar)} point(s) (the calibrator is less accurate than the limit): {", ".join((r.label or r.text()) for r, _t in self.low_tar[:4])}')
        lines += self.notes
        if unverified:
            lines.append(unverified)
        return '\n'.join(lines)


# ----------------------------------------------------------------------------------------------------------------------------------- the standards
_LIMITS_CACHE = {}


def limits_text(model):
    """{sheet function: (limit text, page)} from the shipped sheet's `limits` key (the explanation of the output limits), {} when there is none."""
    if model not in _LIMITS_CACHE:
        out = {}
        try:
            data = json.loads((STANDARDS_DIR / MODEL_FILES[model]).read_text(encoding='utf-8'))
            for e in data.get('limits') or []:
                out[e['function']] = (e['limit'], e.get('page', ''))
        except (OSError, KeyError, ValueError):
            pass
        _LIMITS_CACHE[model] = out
    return _LIMITS_CACHE[model]


def standard(model):
    import specmanager as sm
    s = sm.standard(model)
    if s is None:
        sm.seed()
        s = sm.standard(model)
    return s


def _variant(std, kind):
    """AC current: the driver never switches the coil compensation, so the LCOMP-off rows are the ones that apply (a plain lookup falls back to the
    LCOMP-on rows where LCOMP off has none, which would let a 40 Hz 10 A point through that LCOMP off cannot make)."""
    if kind == 'ACI' and any('lcomp' in (r['variant'] + ' ' + r['function']).lower() for r in std.rows if r['kind'] == 'ACI'):
        return 'lcomp off'
    return ''


def check(model, req, std=None):
    """Verdict for one request on one calibrator model (never raises)."""
    try:
        return _check(model, req, std or standard(model))
    except Exception as exc:                                       # a picker must never fail because of a lookup
        return Verdict(False, f'could not check against the {model} specification: {type(exc).__name__}: {exc}', code='error')


def _stim(req, variant):
    """The Datasheet Builder match's own description of what the standard must source (so its reason sentences are used as they are)."""
    import datasheet_builder_match as dbm
    from decimal import Decimal as D
    k = req.kind
    if k == 'TEMP':
        return dbm.Stim('TEMP', D(repr(abs(req.value))), None, 'output', variant='Type K', unit='degC')
    f = D(repr(req.frequency)) if (req.frequency not in (None, 0) and k in ('ACV', 'ACI')) else None
    return dbm.Stim(k, D(repr(abs(req.value))), f, 'output', variant=variant)


def _check(model, req, std):
    if std is None:
        return Verdict(False, f'no {model} specification sheet is installed', code='no_sheet')
    k = req.kind
    if k in ('SQUARE', 'DUTY'):
        return Verdict(False, f'{model}: a square-wave source. The suite holds no {model} specification for non-sine waveforms (they are not in the sheet), and the WAVE / DUTY / '
                              f'DC_OFFSET commands are not verified for it', code='unsupported_waveform')
    variant = _variant(std, k)
    if k == 'TEMP':
        hit = std.lookup_temperature(req.value)
        variant = 'Type K'
    else:
        hit = std.lookup(k, req.value, frequency=req.frequency if k in ('ACV', 'ACI') else None, variant=variant)
    if hit is not None:
        return Verdict(True, accuracy=hit.limit, row=f"{hit.row['function']} {hit.row['label']}")
    import datasheet_builder_match as dbm
    code, msg = dbm.explain(std, _stim(req, variant))
    if req.detail:
        msg += f' [{req.detail}]'
    return Verdict(False, msg, code=code)


def assess(model, requests, with_tar=True):
    """Fit of `model` to a procedure's requests (see the adapters below).  Never raises."""
    std = standard(model)
    fit = Fit(model)
    tars = []
    for r in requests:
        fit.total += 1
        v = check(model, r, std)
        if v.ok:
            fit.ok.append((r, v))
            if with_tar and r.low is not None and r.high is not None:
                t = _tar(model, r)
                if t is not None:
                    tars.append(t)
                    if t < 1.0:
                        fit.low_tar.append((r, t))
        elif r.optional:
            fit.optional_excluded.append((r, v))
        else:
            fit.excluded.append((r, v))
    fit.min_tar = min(tars) if tars else None
    return fit


def _tar(model, r):
    try:
        import tartur
        p = dict(kind={'OHM': 'OHM4'}.get(r.kind, r.kind), unit=UNIT[r.kind], nominal=r.value, frequency=r.frequency, source='calibrator')
        out = tartur.compute(p, r.low, r.high, standard=model)
        return out.get('tar')
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------------------------------------------- adapters
def dmm_requests(points, label=lambda p: p.get('description') or str(p.get('id', ''))):
    """Requests of the bench-DMM engines (truevolt, dacq, Keithley 2000, 34410A, 8808A): a point with kind DCV ACV DCI ACI OHM2 OHM4 FREQ and source 'calibrator'.
    A FREQ point is an AC volts output of `amplitude` at the test frequency (`nominal` Hz), exactly as the engines program it."""
    out = []
    for p in points:
        if p.get('source') != 'calibrator':
            continue
        k = p['kind']
        opt = bool(p.get('optional') or p.get('opt'))              # procspec section.optional, or the DAQ engine's 'opt' tag (2-wire ohms, extra AC tests)
        if k in ('DCV', 'ACV', 'DCI', 'ACI'):
            req = Req(k, p['nominal'], p.get('frequency') if k in ('ACV', 'ACI') else None)
        elif k in ('OHM2', 'OHM4'):
            req = Req('OHM', p['nominal'])
        elif k == 'FREQ':
            req = Req('ACV', p['amplitude'], p['nominal'])
        else:
            continue
        req.label, req.optional, req.key = label(p), opt, p.get('id')
        if 'low' in p and 'high' in p:
            req.low, req.high = _dec(p['low']), _dec(p['high'])
        elif 'error' in p and p.get('nominal') is not None:
            req.low, req.high = p['nominal'] - p['error'], p['nominal'] + p['error']
        if p['kind'] == 'FREQ':
            req.low = req.high = None                     # the tolerance is in Hz, the source is an AC volts output: no ratio
        out.append(req)
    return out


def _dec(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def handheld_requests(points):
    """Requests of the manual-reading handheld engine: each step with `applied` {value, frequency} and a kind of DCV ACV DCI ACI OHM CAP TEMP SQUARE DUTY.
    Steps with no output (functional checks, visual) are not requests.  The limits (display units x factor) give the TAR."""
    out = []
    for p in points:
        a = p.get('applied')
        k = p.get('kind')
        if not a or k not in KINDS:
            continue
        f = a.get('frequency')
        factor = _dec(p.get('factor')) or 1.0
        lo, hi = _dec(p.get('low')), _dec(p.get('high'))
        low = lo * factor if lo is not None else None
        high = hi * factor if hi is not None else None
        if p.get('base_unit') not in BASE_UNITS.get(k, ()) or p.get('no_uncertainty'):
            low = high = None                                   # tolerance not in the unit of the source (Hz readings of an AC source, nS): no ratio
        req = Req(k, a['value'], f if k in ('ACV', 'ACI', 'SQUARE') else None, f"{p.get('id', p.get('n', ''))}: {p.get('title') or p.get('range', '')}".strip(': '), False,
                  low if k not in ('SQUARE', 'DUTY') else None, high if k not in ('SQUARE', 'DUTY') else None)
        req.key = p.get('id')
        out.append(req)
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- the picker's offer
@dataclass
class Offer:
    """What a calibrator picker shows about one model for one procedure."""
    model: str
    fit: Fit
    offered: bool               # True: the model is in the picker (all points, or the engine handles the others per point)
    manual: list = field(default_factory=list)       # [(Req, reason)] points the engine asks the technician to make with another standard (engines with a per-point manual path)
    text: str = ''              # the line under the picker
    tooltip: str = ''           # the full explanation (hover)


def make_offer(model, requests, per_point_manual=False, unverified='', name=None):
    """Offer for `model`: in the picker when every point has a specification row; with `per_point_manual` (the 8808A engine) also when only some do, and then
    the others are listed as points the technician makes with another standard.  `unverified` is the model's command-status paragraph for the tooltip."""
    fit = assess(model, requests)
    name = name or f'Fluke {model}'
    n = fit.total
    low = (f' TAR is below 1:1 at {len(fit.low_tar)} point(s): the calibrator is less accurate than the limit.' if fit.low_tar else '')
    if fit.complete:
        extra = f' ({len(fit.optional_excluded)} optional point(s) it cannot source)' if fit.optional_excluded else ''
        text = f'{name} is offered: all {n} sourced points are inside its published specification{extra}.{low} Its remote commands are not fully verified (hover).'
        return Offer(model, fit, True, [], text, fit.tooltip(unverified))
    x = len(fit.excluded)
    if per_point_manual:
        text = (f'{name} is offered, but cannot source {x} of {n} points: for those you connect another standard (the meter is still read automatically).{low} '
                f'Its remote commands are not fully verified (hover).')
        return Offer(model, fit, True, [(r, v.reason) for r, v in fit.excluded], text, fit.tooltip(unverified))
    first = fit.reasons(1)[0]
    text = (f'{name} is NOT offered: it cannot source {x} of {n} points of this procedure ({first[1][0]}{" ..." if x > 1 else ""}). Hover for the list.')
    return Offer(model, fit, False, [], text, fit.tooltip(''))


def attach_note(parent, offer, ui, widgets=(), row=None, columnspan=2, wrap=340):
    """A muted label saying whether the model is offered and why not, packed under the picker inside `parent` (or gridded at `row` of a grid); the full
    explanation is the tooltip of the label and of `widgets` (the picker itself).  Returns the label.
    The widget is the toolkit's (calibrator_fit_view_tk.attach_note, via ui_port.view); `ui` is the theme module the caller's view already uses."""
    from ui_port import ui as port
    return port.view('calibrator_fit_view').attach_note(parent, offer, ui, widgets, row, columnspan, wrap)


def picker_values(names, offers):
    """The picker's list: every name, except the models in `offers` ({picker text: Offer}) that are not offered."""
    return [n for n in names if n not in offers or offers[n].offered]
