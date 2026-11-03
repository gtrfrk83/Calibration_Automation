"""Qt-free model of the 'Check an EMU' calculator in the Standards Specs tab (qtui/screens/standards_specs.CheckDialog).

The technician gives a NOMINAL TEST POINT with units (e.g. 250 mV, 1 kHz); the calculator returns the uncertainty that would be REPORTED ON THE CERTIFICATE for
that point with the chosen standard: the budget (the standard's published specification of the sheet row that covers the point, its resolution, any Type A)
expanded with k = 2, compared with the laboratory's scope CMC, the larger one rounded UP to two figures (uncertainty_budget.build -> Budget.reported).
Display-only SI scaling: every number is converted to base SI units here and only the text shows prefixes.  Nothing is written anywhere.

    inputs = Inputs(kind='ACV', nominal='250', nominal_unit='mV', frequency='1', frequency_unit='kHz')
    result = compute(standard, inputs)            # standard: specmanager.StandardSpec, id or model text
    result.cert_text  ->  '31 µV'   result.lines -> the budget lines   result.error -> '' or the plain reason nothing could be computed

What the person can choose (owner request 2026-10-29: 'make sure this is fully fledged out'), all optional, all offered only where the standard's own sheet has them
(`options(standard)` lists them for the window):
    direction   'output' (the standard SOURCES the point: a calibrator) or 'input' (it MEASURES it: a reference meter such as the 3458A / 5790B; the laboratory's
                Measure CMC is then the floor).  Default: the only one the sheet has, else 'output'.
    function    the exact sheet function to use (e.g. 'Voltage, AC [Sinewave]', 'Resistance [2-wire]'); blank = the default the procedures use.
    sensor      TEMP only: the thermocouple type or RTD the calibrator simulates (or measures): Type B ... U, Pt 385 100 / 200 / 500 / 1000 Ω, Pt 3916, Pt 3926,
                Pt 395, PtNi 385 (Ni 120), Cu 427 - as the sheet lists them.  The scope CMC of that sensor is the floor.
    period      the specification interval ('24 hr', '90 day', '1 yr', '2 yr' ...) the sheet prints; blank = the standard's own.
    temperature units  °C, °F or K for the nominal (and the resolution / Type A / reported figures, as temperature DIFFERENCES); the result is in °C with the
                °F figure added when the point was given in °F.
The spec line selected in the table when the window opens fills all of these (`prefill_from_row`): its function, direction, sheet function or sensor,
the top of its amplitude range and the lower edge of its frequency band.
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field

import specmanager as sm
import uncertainty
import uncertainty_budget as ub

KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'COND', 'FREQ', 'TEMP', 'POWDC', 'POWAC', 'PHASE', 'TIME', 'RPM', 'FC', 'LUX', 'LAMBERT', 'UVIRR', 'RFLEVEL')
KIND_NAMES = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM': 'Resistance', 'CAP': 'Capacitance', 'IND': 'Inductance',
              'COND': 'Conductance', 'FREQ': 'Frequency', 'TEMP': 'Temperature', 'POWDC': 'DC power', 'POWAC': 'AC power', 'PHASE': 'Phase angle',
              'TIME': 'Time (time marks)', 'RPM': 'RPM', 'FC': 'Light (foot-candles)', 'LUX': 'Light (lux)', 'LAMBERT': 'Light (lamberts)',
              'UVIRR': 'UV irradiance (365 nm)', 'RFLEVEL': 'RF level (dBm)'}
# kinds the sheets carry that are NOT a value with an uncertainty here: scope-calibrator edge / aberration / flatness checks and the receiver / analyzer specs that are
# relative to a setting (dB re carrier, ratio) - the window says so when such a row is selected
NOT_OFFERED = {'FLAT': 'a flatness specification (relative to a reference frequency)', 'ABER': 'an aberration limit of the scope calibrator edge',
               'RISE': 'a rise-time limit of the scope calibrator edge', 'OTHER': 'a specification this calculator cannot evaluate as a test point (relative, dB re carrier, a ratio or a characteristic)'}
AC_KINDS = ('ACV', 'ACI')                        # the kinds that always take a frequency (FREQ's nominal IS the frequency); others take one when their rows do
BASE_UNIT = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'CAP': 'F', 'IND': 'H', 'COND': 'S', 'FREQ': 'Hz', 'TEMP': 'degC', 'POWDC': 'W',
             'POWAC': 'W', 'PHASE': 'deg', 'TIME': 's', 'RPM': 'rpm', 'FC': 'FC', 'LUX': 'lux', 'LAMBERT': 'La', 'UVIRR': 'uW/cm2', 'RFLEVEL': 'dBm'}
DIRECTION_NAMES = {'output': 'Sources the point (calibrator output)', 'input': 'Measures the point (meter input)'}

_PREFIX = (('G', 1e9), ('M', 1e6), ('k', 1e3), ('', 1.0), ('m', 1e-3), ('µ', 1e-6), ('n', 1e-9), ('p', 1e-12))
_SYMBOL = {'V': 'V', 'Vpp': 'Vpp', 'A': 'A', 'App': 'App', 'ohm': 'Ω', 'F': 'F', 'H': 'H', 'Hz': 'Hz', 'S': 'S', 'W': 'W', 's': 's'}


def _units(base, prefixes):
    return [(p + _SYMBOL[base], f) for p, f in _PREFIX if p in prefixes]


# the unit choices of each input box: (text shown, factor to SI); the first one is the default.  Temperature factors are for DIFFERENCES (°F -> x 5/9);
# the nominal temperature is converted with an offset by `to_celsius`.
NOMINAL_UNITS = {
    'DCV': _units('V', ('', 'm', 'µ', 'k')), 'ACV': _units('V', ('', 'm', 'µ', 'k')),
    'DCI': _units('A', ('', 'm', 'µ')), 'ACI': _units('A', ('', 'm', 'µ')),
    'OHM': _units('ohm', ('', 'k', 'M', 'G', 'm')), 'CAP': _units('F', ('n', 'µ', 'm', 'p', '')), 'IND': _units('H', ('m', 'µ', '')),
    'COND': _units('S', ('n', 'µ', 'm', '')),
    'FREQ': _units('Hz', ('', 'k', 'M', 'G', 'm')), 'TEMP': [('°C', 1.0), ('°F', 5.0 / 9.0), ('K', 1.0)],
    'POWDC': _units('W', ('', 'm', 'µ', 'k')), 'POWAC': _units('W', ('', 'm', 'µ', 'k')),
    'PHASE': [('°', 1.0)], 'TIME': _units('s', ('', 'm', 'µ', 'n')), 'RPM': [('rpm', 1.0)],
    'FC': [('fc', 1.0)], 'LUX': [('lux', 1.0)], 'LAMBERT': [('La', 1.0)], 'UVIRR': [('µW/cm²', 1.0)], 'RFLEVEL': [('dBm', 1.0)],
}
PEAK_UNITS = {'Vpp': _units('Vpp', ('', 'm', 'k')), 'App': _units('App', ('', 'm', 'µ'))}       # a sheet function in peak-to-peak (33250A sine into 50 Ω, 5522A square waves)
DIFF_UNITS = {'RFLEVEL': [('dB', 1.0)]}       # the uncertainty of an RF level is in dB, not dBm
FREQUENCY_UNITS = _units('Hz', ('', 'k', 'M', 'G'))
RESOLUTION_UNITS = NOMINAL_UNITS            # resolution of the calibrator at that point: the same unit family as the nominal
TYPE_A_UNITS = NOMINAL_UNITS                # Type A standard uncertainty (k = 1): the same unit family as the nominal
NO_PREFIX = ('deg', 'rpm', 'FC', 'lux', 'La', 'uW/cm2', 'dB', 'dBm')
_SHOWN = {'deg': '°', 'rpm': 'rpm', 'FC': 'fc', 'lux': 'lux', 'La': 'La', 'uW/cm2': 'µW/cm²', 'dB': 'dB', 'dBm': 'dBm'}


def unit_choices(kind, peak=None) -> list:
    """Unit choices of the nominal box.  peak='Vpp' / 'App': the sheet function is in peak-to-peak."""
    if peak in PEAK_UNITS:
        return list(PEAK_UNITS[peak])
    return list(NOMINAL_UNITS.get(kind) or NOMINAL_UNITS['DCV'])


def diff_unit_choices(kind, peak=None) -> list:
    """Unit choices of the resolution / Type A / reported boxes (an uncertainty: a difference)."""
    return list(DIFF_UNITS.get(kind) or unit_choices(kind, peak))


def factor(choices, text) -> float:
    for name, f in choices:
        if name == text:
            return f
    raise ValueError(f'unknown unit {text!r}')


def default_unit(kind, value_si) -> str:
    """The unit that reads best for an SI value (a range of 0.12 V -> mV): used to prefill from a spec-table row."""
    choices = unit_choices(kind)
    if kind == 'TEMP':
        return '°C'
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


def to_celsius(value, unit) -> float:
    """A temperature READING (not a difference) in °C."""
    if unit == '°F':
        return (value - 32.0) * 5.0 / 9.0
    if unit == 'K':
        return value - 273.15
    return value


# ============================================================================ what a standard's sheet offers
def sensor_of(function_name) -> tuple:
    """(scope sensor key or '', label) of a temperature function: 'Temperature [Thermocouple, Type K Output]' -> ('K', 'Type K thermocouple');
    'Temperature [RTD, Pt 385, 100 Ohm]' -> ('Pt385-100', 'Pt 385, 100 Ω RTD'); 'Temperature [RTD, PtNi 385, 120 Ohm (Ni 120)]' -> ('PtNi385-120', ...)."""
    text = function_name or ''
    m = re.search(r'\b(PtNi|Pt|Cu)\s*(\d+)\s*,\s*(\d+)\s*Ohm', text, re.I)
    if m:
        metal = {'ptni': 'PtNi', 'pt': 'Pt', 'cu': 'Cu'}[m.group(1).lower()]
        return f'{metal}{m.group(2)}-{m.group(3)}', f'{metal} {m.group(2)}, {m.group(3)} Ω RTD'
    m = re.search(r'\bType\s*([A-Z])\b', text)
    if m:
        return m.group(1), f'Type {m.group(1)} thermocouple'
    inner = re.search(r'\[(.*?)\]', text)
    return '', (inner.group(1) if inner else text).strip()


def _clean_function(name) -> str:
    return re.sub(r'\s*\{Notes?:[^}]*\}\s*$', '', name or '').strip()


@dataclass
class Choice:
    value: str           # what goes into Inputs (a function name, a sensor key, a period)
    label: str           # what the drop-down shows


@dataclass
class KindOptions:
    kind: str
    directions: list = field(default_factory=list)                 # ['output', 'input'] as the sheet has them
    functions: dict = field(default_factory=dict)                  # direction -> [Choice] (TEMP: the sensors)
    periods: dict = field(default_factory=dict)                    # (direction, function or '') -> [period]
    frequency: dict = field(default_factory=dict)                  # (direction, function or '') -> 'required' / 'optional' / ''
    peak: dict = field(default_factory=dict)                       # (direction, function or '') -> 'Vpp' / 'App' / None


def _rows_for(standard, kind, direction, function=''):
    rows = [r for r in standard.rows if _kind_of(r) == kind and r['direction'] == direction]
    if kind == 'RFLEVEL':
        rows = [r for r in rows if r['specs']]
    else:
        rows = [r for r in rows if r['amp_lo'] is not None and r['amp_hi'] is not None]
    if function:
        if kind == 'TEMP':
            rows = [r for r in rows if r['unit'] == 'degC' and (sensor_of(r['function'])[0] or _clean_function(r['function'])) == function]
        else:
            rows = [r for r in rows if _clean_function(r['function']) == function]
    elif kind == 'TEMP':
        rows = [r for r in rows if r['unit'] == 'degC']
    return rows


def _kind_of(row) -> str:
    """The calculator's kind of a sheet row (the sheet's own kind; the 96270A 'RF Level Accuracy ... [Leveling Head O/P]' rows are RF level)."""
    if row.get('kind') == 'OTHER' and row['function'].startswith('RF Level Accuracy') and 'Leveling Head O/P' in row['function'] and row.get('unit') == 'dB':
        return 'RFLEVEL'
    return row.get('kind') or 'OTHER'


def options(standard, kinds=None) -> dict:
    """kind -> KindOptions for the kinds this standard's sheet can answer, in KINDS order (`kinds`: only those)."""
    out = {}
    for kind in (kinds or KINDS):
        ko = KindOptions(kind)
        for direction in ('output', 'input'):
            rows = _rows_for(standard, kind, direction)
            if not rows:
                continue
            ko.directions.append(direction)
            seen, choices = set(), []
            for r in rows:
                if kind == 'TEMP':
                    key, label = sensor_of(r['function'])
                    value = key or _clean_function(r['function'])
                else:
                    value = label = _clean_function(r['function'])
                if value not in seen:
                    seen.add(value)
                    choices.append(Choice(value, label))
            if kind == 'TEMP':                  # thermocouples B..U first, then the RTDs, as the scope lists them
                order = {k: i for i, k in enumerate(uncertainty.TC_TYPES + tuple(uncertainty.RTD_LABELS))}
                choices.sort(key=lambda c: (order.get(c.value, 999), c.label))
            ko.functions[direction] = choices
            for fn in [''] + [c.value for c in choices]:
                sel = _rows_for(standard, kind, direction, fn)
                periods = []
                for r in sel:
                    for s in r['specs']:
                        if not s.get('error') and s['period'] not in periods:
                            periods.append(s['period'])
                ko.periods[(direction, fn)] = periods
                with_f = [r for r in sel if r['freq_lo'] is not None]
                ko.frequency[(direction, fn)] = 'required' if (kind in AC_KINDS or kind == 'RFLEVEL' or (with_f and len(with_f) == len(sel))) else ('optional' if with_f else '')
                units = {r['unit'] for r in sel}
                ko.peak[(direction, fn)] = next(iter(units)) if len(units) == 1 and next(iter(units)) in PEAK_UNITS else None
        if ko.directions:
            out[kind] = ko
    return out


# ============================================================================ inputs and result
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
    direction: str = ''                # 'output' / 'input'; blank = the only one the sheet has for the kind, else 'output'
    function: str = ''                 # an exact sheet function (TEMP: a sensor key or label); blank = the default the procedures use
    period: str = ''                   # a specification interval of the sheet; blank = the standard's own


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
    if not math.isfinite(value):
        raise ValueError(f'The {name} must be a number (got {t!r}).')
    return value * factor(units, unit or units[0][0])


def relative_text(emu, nominal) -> str:
    if not nominal or not emu:
        return ''
    r = abs(emu / nominal)
    if r >= 1e-3:
        return f'{r * 100:.2g} % of nominal'
    return f'{round(r * 1e6, 2 - int(math.floor(math.log10(r * 1e6)))):g} ppm of nominal'


class _Restricted(sm.StandardSpec):
    """A copy of a standard limited to the chosen direction / sheet function / period: uncertainty_budget.build then looks only there (nothing shared is changed)."""

    def __init__(self, base, kind, direction, function, period):           # noqa: D401 - never calls StandardSpec.__init__ (no database read)
        self.__dict__.update(copy.copy(base.__dict__))
        self._base, self._kind, self._direction, self._function = base, kind, direction, function
        if period:
            self.period = period
        if function or kind == 'TEMP':
            keep = {id(r) for r in _rows_for(base, kind, direction, function)}
            self.rows = [r for r in base.rows if id(r) in keep or _kind_of(r) != kind]

    def lookup(self, kind, value, frequency=None, variant='', direction='output', period=None, qualifier=None):
        pin = self._function if (self._function and kind == self._kind) else variant
        return super().lookup(kind, value, frequency=frequency, variant=pin, direction=self._direction if kind == self._kind else direction,
                              period=period or self.period, qualifier=qualifier)

    def lookup_temperature(self, celsius, tc='K', direction='output', period=None, variant=None):
        # the rows are already limited to the chosen sensor (or to degC rows of the direction): 'Temperature' matches every one of them
        return super().lookup_temperature(celsius, tc=tc, direction=self._direction, period=period or self.period, variant='Temperature')


def _fmt(value, unit) -> str:
    """A rounded-up 2-figure uncertainty with its unit; no SI prefix on degrees, rpm, light and dB units."""
    if value is None:
        return ''
    if unit in ('degC', '°C', 'C'):
        return uncertainty.format_value(value, 'degC')
    if unit in NO_PREFIX:
        v = uncertainty.round_up(value, 2)
        digits = max(1 - int(math.floor(math.log10(abs(v)))), 0) if v else 0
        return f'{v:.{digits}f}°' if unit == 'deg' else f'{v:.{digits}f} {_SHOWN.get(unit, unit)}'
    return uncertainty.format_value(value, unit)


def _resolve(standard, inp, opts):
    """(kind options, direction, function, period, frequency rule, peak unit) after the defaults are applied; raises ValueError for a choice the sheet does not have."""
    kind = inp.kind
    ko = opts.get(kind)
    if ko is None:
        raise ValueError(f'{getattr(standard, "model", "This standard")} has no {KIND_NAMES.get(kind, kind)} specification on its sheet.')
    direction = inp.direction or ('output' if 'output' in ko.directions else ko.directions[0])
    if direction not in ko.directions:
        raise ValueError(f'{standard.model} does not {"source" if direction == "output" else "measure"} {KIND_NAMES[kind].lower()} on its sheet.')
    function = inp.function or ''
    if kind == 'TEMP' and not function:
        function = 'K' if any(c.value == 'K' for c in ko.functions[direction]) else ko.functions[direction][0].value
    if function and not any(c.value == function or c.label == function for c in ko.functions[direction]):
        raise ValueError(f'{standard.model}: the sheet has no {"sensor" if kind == "TEMP" else "function"} {function!r} for {KIND_NAMES[kind].lower()} '
                         f'({"sourced" if direction == "output" else "measured"}).')
    function = next(c.value for c in ko.functions[direction] if c.value == function or c.label == function) if function else ''
    periods = ko.periods.get((direction, function)) or []
    period = inp.period or (standard.period if standard.period in periods else (periods[0] if periods else standard.period))
    if inp.period and inp.period not in periods:
        raise ValueError(f'{standard.model}: no {inp.period} specification for this function (the sheet has {", ".join(periods) or "none"}).')
    return ko, direction, function, period, ko.frequency.get((direction, function), ''), ko.peak.get((direction, function))


def compute(standard, inp: Inputs, scope=None) -> Result:
    res = Result()
    kind = inp.kind
    if kind not in KINDS:
        why = NOT_OFFERED.get(kind)
        res.error = f'Function {kind!r} is not supported by this calculator' + (f': it is {why}.' if why else '.')
        return res
    if isinstance(standard, (str, int)):
        key = standard
        standard = sm.standard(key)
        if standard is None:
            sm.seed()
            standard = sm.standard(key)
    try:
        ko, direction, function, period, freq_rule, peak = _resolve(standard, inp, options(standard, (kind,)))
        nom_units = unit_choices(kind, peak)
        diff_units = diff_unit_choices(kind, peak)
        if kind == 'TEMP':
            raw = _to_si(inp.nominal, [(n, 1.0) for n, _f in nom_units], inp.nominal_unit, 'nominal test point', required=True)
            nominal = to_celsius(raw, inp.nominal_unit or '°C')
        else:
            nominal = _to_si(inp.nominal, nom_units, inp.nominal_unit, 'nominal test point', required=True)
        freq = _to_si(inp.frequency, FREQUENCY_UNITS, inp.frequency_unit, 'frequency') if freq_rule else None
        resolution = _to_si(inp.resolution, diff_units, inp.resolution_unit, 'calibrator resolution')
        type_a = _to_si(inp.type_a, diff_units, inp.type_a_unit, 'Type A uncertainty')
        reported = _to_si(inp.reported, diff_units, inp.reported_unit, 'reported uncertainty')
    except ValueError as exc:
        res.error = str(exc)
        return res
    if freq_rule == 'required' and not freq:
        res.error = ('Enter the frequency (an AC point needs one).' if kind in AC_KINDS else
                     'Enter the frequency (the sheet specifies this function by frequency band).')
        return res
    std = _Restricted(standard, kind, direction, function, period)
    unit = peak or BASE_UNIT[kind]
    notes = []
    if kind == 'RFLEVEL':
        b = ub.rf_level(nominal, [freq], standard=std, scope=scope)
        if b is None:
            res.error = (f'Nothing can be reported for this point: the {standard.model} sheet\'s RF level rows (leveling head, down to {ub.RF_LEVEL_FLOOR_DBM:g} dBm) '
                         f'do not cover {nominal:g} dBm at that frequency.')
            return res
        if resolution:
            b.components = [c for c in b.components if c.name != 'Resolution']
            b.add('Resolution', resolution / math.sqrt(12), 1.0, f'{resolution:.6g} / sqrt(12) (entered)')
        if type_a:
            b.add('Type A', type_a, 1.0, 'Type A')
        b.reported = ub.ceil_sig(max(b.emu or 0.0, b.cmc or 0.0)) if (b.emu or b.cmc) else None
        b.notes.append('the laboratory scope has no RF level CMC: the budget alone is reported')
        diff_unit = 'dB'
    else:
        tc, variant = 'K', None
        if kind == 'TEMP':
            tc = function if (function in uncertainty.TC_TYPES or function in uncertainty.RTD_LABELS) else 'K'
            variant = 'Temperature'
            if tc == 'K' and function not in ('K', ''):
                notes.append(f'the scope has no CMC line for {function}: no floor')
        basis = 'measure' if direction == 'input' else None
        b = ub.build(kind, nominal, unit, standard=std, frequency=freq, resolution=resolution,
                     type_a=[('Type A', type_a, 1.0)] if type_a else [], scope=scope, direction=direction, basis=basis, tc=tc, variant=variant)
        if kind == 'TEMP' and tc == 'K' and function not in ('K', ''):
            b.cmc = None
            b.reported = ub.ceil_sig(b.emu) if b.emu is not None else None
        if peak:                                  # the scope's AC lines are in rms: they are no floor for a peak-to-peak sheet row
            b.cmc = None
            b.reported = ub.ceil_sig(b.emu) if b.emu is not None else None
            notes.append(f'this sheet function is in {peak}: the scope CMC (rms) is not applied')
        if kind in ('POWDC', 'POWAC') and b.hit is not None:
            notes.append('the voltage and current that make up the power are not entered: the largest specification of the rows that cover this wattage is used')
        diff_unit = unit
    b.notes += notes
    res.budget = b
    if b.reported is None:
        res.error = ('Nothing can be reported for this point: ' + ('; '.join(b.notes) if b.notes else 'no specification row of the standard and no scope CMC cover it.'))
        return res
    res.cert_si = b.reported
    res.cert_text = ub.reported_text(b) if kind in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'FREQ', 'TEMP') and not peak else _fmt(b.reported, diff_unit)
    if kind == 'TEMP' and inp.nominal_unit == '°F':
        res.cert_text += f'  ({_fmt(b.reported * 9.0 / 5.0, "deg").replace("°", "")} °F)'
    res.relative = relative_text(b.reported, nominal) if kind not in ('TEMP', 'RFLEVEL', 'PHASE') else ''
    if b.hit is not None:
        row = b.hit.row
        res.sheet_row = f'{_clean_function(row["function"])} / {row["label"]} [{b.hit.period}]'
    lines = [f'Standard: {standard.model}, {DIRECTION_NAMES[direction].lower()}' + (f', sensor {next((c.label for c in ko.functions[direction] if c.value == function), function)}' if kind == 'TEMP' else
                (f', sheet function {function}' if function else ''))
             + f', specification period {period}']
    if kind == 'TEMP' and inp.nominal_unit in ('°F', 'K'):
        lines.append(f'Test point: {inp.nominal} {inp.nominal_unit} = {nominal:.6g} °C (the sheet and the scope are in °C)')
    if res.sheet_row:
        lines.append(f'Sheet row used: {res.sheet_row}')
    for c in b.components:
        lines.append(f'  {c.name:28s} u = {_show(c.u, kind, diff_unit)}   ({c.source})')
    if b.emu is not None:
        lines.append(f'  Expanded uncertainty (k = {b.k:g}): {_show(b.emu, kind, diff_unit)}')
    lines.append(f'  Scope CMC ({"Measure" if direction == "input" else "Generate"}): {_show(b.cmc, kind, diff_unit)}' if b.cmc is not None
                 else '  Scope CMC: not covered by the scope of accreditation')
    lines.append(f'  Reported = the larger of the two, rounded up to 2 figures: {res.cert_text}')
    lines += [f'  Note: {n}' for n in b.notes]
    if reported is not None:
        status, text = ub.audit(reported, b)
        res.audit = f'{status}: {text}'
        lines += ['', res.audit]
    res.lines = lines
    return res


def _show(value, kind, unit) -> str:
    if value is None:
        return ''
    if kind in ('DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'FREQ', 'TEMP') and unit == BASE_UNIT[kind]:
        return uncertainty.format_value(value, 'ohm' if kind == 'OHM' else BASE_UNIT[kind])
    return _fmt(value, unit)


def _si(value, kind) -> str:
    return uncertainty.format_value(value, 'ohm' if kind == 'OHM' else BASE_UNIT[kind])


def prefill_from_row(row: dict) -> dict:
    """Inputs for a spec-table row (a specmanager.rows_of dict): its function and direction, its exact sheet function (TEMP: its sensor), the top of its amplitude
    range and the lower edge of its frequency band.  A row of a kind the calculator does not evaluate returns kind '' and `why`."""
    kind = _kind_of(row)
    if kind not in KINDS:
        return {'kind': '', 'why': f'The selected row ({_clean_function(row.get("function", ""))}) is {NOT_OFFERED.get(kind, NOT_OFFERED["OTHER"])}: choose a function below.',
                'nominal': '', 'nominal_unit': '', 'frequency': '', 'frequency_unit': 'Hz', 'direction': row.get('direction') or '', 'function': '', 'period': ''}
    function = _clean_function(row.get('function', ''))
    if kind == 'TEMP':
        key, _label = sensor_of(row.get('function', ''))
        function = key or function
    peak = row.get('unit') if row.get('unit') in PEAK_UNITS else None
    out = {'kind': kind, 'nominal': '', 'nominal_unit': unit_choices(kind, peak)[0][0], 'frequency': '', 'frequency_unit': 'Hz',
           'direction': row.get('direction') or '', 'function': function, 'period': '', 'why': ''}
    top = row.get('amp_hi')
    if kind == 'TEMP':
        if top is not None:
            out['nominal_unit'] = '°F' if row.get('unit') == 'degF' else '°C'
            out['nominal'] = f'{top:.10g}'
    elif top:
        choices = unit_choices(kind, peak)
        out['nominal_unit'] = default_unit(kind, abs(top)) if not peak else next((n for n, f in sorted(choices, key=lambda c: -c[1]) if abs(top) >= f * 0.999999), choices[-1][0])
        out['nominal'] = f'{abs(top) / factor(choices, out["nominal_unit"]):.10g}'
    f = row.get('freq_lo')
    if f is not None and kind != 'FREQ':
        unit = default_unit('FREQ', f) if f else 'Hz'
        out['frequency_unit'] = unit if unit in dict(FREQUENCY_UNITS) else 'Hz'
        out['frequency'] = f'{f / factor(FREQUENCY_UNITS, out["frequency_unit"]):.10g}'
    return out
