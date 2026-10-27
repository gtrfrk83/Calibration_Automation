"""Qt-free model of the 'Check an EMU' calculator in the Standards Specs tab (qtui/screens/standards_specs.CheckDialog).

The technician gives a NOMINAL TEST POINT with units (e.g. 250 mV, 1 kHz); the calculator returns the uncertainty that would be REPORTED ON THE CERTIFICATE for
that point with the chosen standard: the budget (the standard's published specification of the sheet row that covers the point, its resolution, any Type A)
expanded with k = 2, compared with the laboratory's scope CMC, the larger one rounded UP to two figures (uncertainty_budget.build -> Budget.reported).
Display-only SI scaling: every number is converted to base SI units here and only the text shows prefixes.  Nothing is written anywhere.

    inputs = Inputs(kind='ACV', nominal='250', nominal_unit='mV', frequency='1', frequency_unit='kHz')
    result = compute(standard, inputs)            # standard: specmanager.StandardSpec, id or model text
    result.cert_text  ->  '31 µV'   result.lines -> the budget lines   result.error -> '' or the plain reason nothing could be computed
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import uncertainty
import uncertainty_budget as ub

KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'FREQ', 'TEMP')
KIND_NAMES = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM': 'Resistance', 'CAP': 'Capacitance', 'IND': 'Inductance',
              'FREQ': 'Frequency', 'TEMP': 'Temperature'}
AC_KINDS = ('ACV', 'ACI')                        # the kinds that take a frequency (FREQ's nominal IS the frequency)
BASE_UNIT = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'CAP': 'F', 'IND': 'H', 'FREQ': 'Hz', 'TEMP': 'degC'}

_PREFIX = (('G', 1e9), ('M', 1e6), ('k', 1e3), ('', 1.0), ('m', 1e-3), ('µ', 1e-6), ('n', 1e-9), ('p', 1e-12))
_SYMBOL = {'V': 'V', 'A': 'A', 'ohm': 'Ω', 'F': 'F', 'H': 'H', 'Hz': 'Hz'}


def _units(base, prefixes):
    return [(p + _SYMBOL[base], f) for p, f in _PREFIX if p in prefixes]


# the unit choices of each input box: (text shown, factor to SI); the first one is the default
NOMINAL_UNITS = {
    'DCV': _units('V', ('', 'm', 'µ', 'k')), 'ACV': _units('V', ('', 'm', 'µ', 'k')),
    'DCI': _units('A', ('', 'm', 'µ')), 'ACI': _units('A', ('', 'm', 'µ')),
    'OHM': _units('ohm', ('', 'k', 'M', 'G', 'm')), 'CAP': _units('F', ('n', 'µ', 'm', 'p', '')), 'IND': _units('H', ('m', 'µ', '')),
    'FREQ': _units('Hz', ('', 'k', 'M', 'G', 'm')), 'TEMP': [('°C', 1.0)],
}
FREQUENCY_UNITS = _units('Hz', ('', 'k', 'M'))
RESOLUTION_UNITS = NOMINAL_UNITS            # resolution of the calibrator at that point: the same unit family as the nominal
TYPE_A_UNITS = NOMINAL_UNITS                # Type A standard uncertainty (k = 1): the same unit family as the nominal


def unit_choices(kind) -> list:
    return list(NOMINAL_UNITS.get(kind) or NOMINAL_UNITS['DCV'])


def factor(choices, text) -> float:
    for name, f in choices:
        if name == text:
            return f
    raise ValueError(f'unknown unit {text!r}')


def default_unit(kind, value_si) -> str:
    """The unit that reads best for an SI value (a range of 0.12 V -> mV): used to prefill from a spec-table row."""
    choices = unit_choices(kind)
    if not value_si:
        return choices[0][0]
    best = choices[0]
    for name, f in sorted(choices, key=lambda c: -c[1]):
        if abs(value_si) >= f * 0.999999:
            best = (name, f)
            break
    else:
        best = min(choices, key=lambda c: c[1])
    return best[0]


def number_text(value_si, kind, which='nominal') -> str:
    """Text of an SI value in the unit default_unit picks (no unit symbol): 0.12 V -> '120'."""
    unit = default_unit(kind, value_si)
    x = value_si / factor(unit_choices(kind), unit)
    return f'{x:.10g}'


@dataclass
class Inputs:
    kind: str = 'DCV'
    nominal: str = ''
    nominal_unit: str = ''
    frequency: str = ''
    frequency_unit: str = 'Hz'
    resolution: str = ''
    resolution_unit: str = ''
    type_a: str = ''
    type_a_unit: str = ''
    reported: str = ''                 # optional: an uncertainty somebody already reported, to be audited against the budget
    reported_unit: str = ''


@dataclass
class Result:
    error: str = ''
    cert_text: str = ''                # what is printed on the certificate, e.g. '31 µV'
    cert_si: float | None = None
    relative: str = ''                 # the same as a fraction of the nominal ('0.012 % of nominal', '120 ppm')
    sheet_row: str = ''                # the specification row of the standard that covers the point
    audit: str = ''
    lines: list = field(default_factory=list)
    budget: object = None

    @property
    def text(self) -> str:
        if self.error:
            return self.error
        return '\n'.join([f'Uncertainty to report on the certificate: ± {self.cert_text}' + (f'   ({self.relative})' if self.relative else ''), ''] + self.lines)


def _to_si(text, units, unit, name, required=False):
    t = (text or '').strip()
    if not t:
        if required:
            raise ValueError(f'Enter the {name}.')
        return None
    try:
        value = float(t.replace(',', ''))
    except ValueError:
        raise ValueError(f'The {name} must be a number (got {t!r}).') from None
    return value * factor(units, unit or units[0][0])


def relative_text(emu, nominal) -> str:
    if not nominal or not emu:
        return ''
    r = abs(emu / nominal)
    if r >= 1e-3:
        return f'{r * 100:.2g} % of nominal'
    return f'{round(r * 1e6, 2 - int(math.floor(math.log10(r * 1e6)))):g} ppm of nominal'


def compute(standard, inp: Inputs, scope=None) -> Result:
    res = Result()
    kind = inp.kind
    if kind not in KINDS:
        res.error = f'Function {kind!r} is not supported by this calculator.'
        return res
    try:
        nominal = _to_si(inp.nominal, unit_choices(kind), inp.nominal_unit, 'nominal test point', required=True)
        freq = _to_si(inp.frequency, FREQUENCY_UNITS, inp.frequency_unit, 'frequency') if kind in AC_KINDS else None
        resolution = _to_si(inp.resolution, unit_choices(kind), inp.resolution_unit, 'calibrator resolution')
        type_a = _to_si(inp.type_a, unit_choices(kind), inp.type_a_unit, 'Type A uncertainty')
        reported = _to_si(inp.reported, unit_choices(kind), inp.reported_unit, 'reported uncertainty')
    except ValueError as exc:
        res.error = str(exc)
        return res
    if kind in AC_KINDS and not freq:
        res.error = 'Enter the frequency (an AC point needs one).'
        return res
    b = ub.build(kind, nominal, BASE_UNIT[kind], standard=standard, frequency=freq, resolution=resolution,
                 type_a=[('Type A', type_a, 1.0)] if type_a else [], scope=scope)
    res.budget = b
    if b.reported is None:
        res.error = ('Nothing can be reported for this point: ' + ('; '.join(b.notes) if b.notes else 'no specification row of the standard and no scope CMC cover it.'))
        return res
    res.cert_si = b.reported
    res.cert_text = ub.reported_text(b)
    res.relative = relative_text(b.reported, nominal)
    if b.hit is not None:
        row = b.hit.row
        res.sheet_row = f'{row["function"]} / {row["label"]} [{b.hit.period}]'
    lines = []
    if res.sheet_row:
        lines.append(f'Sheet row used: {res.sheet_row}')
    for c in b.components:
        lines.append(f'  {c.name:28s} u = {_si(c.u, kind)}   ({c.source})')
    if b.emu is not None:
        lines.append(f'  Expanded uncertainty (k = {b.k:g}): {_si(b.emu, kind)}')
    lines.append(f'  Scope CMC: {_si(b.cmc, kind)}' if b.cmc is not None else '  Scope CMC: not covered by the scope of accreditation')
    lines.append(f'  Reported = the larger of the two, rounded up to 2 figures: {res.cert_text}')
    lines += [f'  Note: {n}' for n in b.notes]
    if reported is not None:
        status, text = ub.audit(reported, b)
        res.audit = f'{status}: {text}'
        lines += ['', res.audit]
    res.lines = lines
    return res


def _si(value, kind) -> str:
    return uncertainty.format_value(value, 'ohm' if kind == 'OHM' else BASE_UNIT[kind])


def prefill_from_row(row: dict) -> dict:
    """Inputs for a spec-table row (a specmanager.rows_of dict): the function, the top of its amplitude range and the lower edge of its frequency band."""
    kind = row.get('kind') or 'DCV'
    if kind not in KINDS:
        kind = 'DCV'
    top = row.get('amp_hi')
    out = {'kind': kind, 'nominal': '', 'nominal_unit': unit_choices(kind)[0][0], 'frequency': '', 'frequency_unit': 'Hz'}
    if top:
        out['nominal_unit'] = default_unit(kind, abs(top))
        out['nominal'] = f'{abs(top) / factor(unit_choices(kind), out["nominal_unit"]):.10g}'
    f = row.get('freq_lo')
    if kind in AC_KINDS and f:
        out['frequency_unit'] = default_unit('FREQ', f) if default_unit('FREQ', f) in dict(FREQUENCY_UNITS) else 'Hz'
        out['frequency'] = f'{f / factor(FREQUENCY_UNITS, out["frequency_unit"]):.10g}'
    return out
