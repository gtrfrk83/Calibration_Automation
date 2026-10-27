"""Uncertainty budget for a point applied by a calibrator, built from the standard's own published specification (specmanager) and checked
against the laboratory's A2LA scope CMC (uncertainty.Scope).

Same method as the laboratory's uncertainty wizard:
    u(standard)   = published accuracy / coverage divisor        (2.0 when the sheet gives no confidence level or says 95 %)
    u(resolution) = last digit of the calibrator setting / sqrt(12)
    EMU           = k * sqrt(sum((sensitivity * u)^2)),  k = 2
The reported value is never below the scope CMC and is rounded UP, so it can never be reported smaller than the budget.
"""
import math

import specmanager as sm
import uncertainty

K = 2.0
OK, UNDER_CMC, UNDER_BUDGET, NOT_IN_SCOPE, NO_SPEC = 'OK', 'UNDER CMC', 'UNDER BUDGET', 'NOT IN SCOPE', 'NO STANDARD SPEC'


def ceil_sig(value, sig=2):
    """Round UP to `sig` significant figures (never down: a reported uncertainty must not shrink)."""
    if not value or value <= 0:
        return 0.0
    step = 10 ** (math.floor(math.log10(value)) - sig + 1)
    out = round(math.ceil(round(value / step, 9)) * step, 15)
    return out if out >= value else value        # float noise must never put it below the input


class Component:
    def __init__(self, name, u, sensitivity=1.0, source=''):
        self.name, self.u, self.sensitivity, self.source = name, u, sensitivity, source

    @property
    def contribution(self):
        return abs(self.sensitivity) * self.u


class Budget:
    def __init__(self, kind, nominal, unit, standard=None, frequency=None, k=K):
        self.kind, self.nominal, self.unit, self.frequency, self.k = kind, nominal, unit, frequency, k
        self.standard, self.components, self.hit, self.notes = standard, [], None, []
        self.cmc = None
        self.reported = None

    @property
    def combined(self):
        return math.sqrt(sum(c.contribution ** 2 for c in self.components))

    @property
    def emu(self):
        return self.k * self.combined if self.components else None

    @property
    def value(self):
        """The larger of the budget (EMU) and the CMC, UNROUNDED (SI), or None when neither exists.  `reported` is this rounded UP to 2 figures; engines that
        combine several levels (DC gain) or print through uncertainty.format_value use the unrounded value so nothing is rounded twice."""
        if self.emu is None and self.cmc is None:
            return None
        return max(self.emu or 0.0, self.cmc or 0.0)

    def add(self, name, u, sensitivity=1.0, source=''):
        self.components.append(Component(name, u, sensitivity, source))


COIL_MODEL = 'A2LA-5500A-COIL'          # specs/standards/a2la_5500a_coil_standard.json (the Fluke 5500A/COIL, 50 turns): used by the clamp meters on that coil


def build(kind, nominal, unit='', standard=None, frequency=None, resolution=None, type_a=(), extra=(), scope=None, range_value=None,
          direction='output', basis=None, cmc=None, scale=1.0, tc='K', variant=None):
    """Budget for one applied point.  `standard` is a specmanager.StandardSpec (or model text); `resolution` overrides the sheet-derived
    calibrator resolution (SI); `type_a` / `extra` are (name, u_k1, sensitivity) tuples.
    Optional (the defaults are what every multimeter engine has always got):
      direction  row direction of the standard: 'output' (it SOURCES the point, the default) or 'input' (it MEASURES it, e.g. the 5790B reading a generator)
      basis      scope CMC basis ('generate' when None, or 'measure'): a measuring standard is checked against the laboratory's Measure CMC
      scale      factor every component and the CMC floor are multiplied by (default 1): a 50-turn-coil point below the coil's range, where the calibrator's
                 uncertainty at the sourced current is referred to the current the clamp reads (coil_rule.uncertainty_scale)
      cmc        a CMC (SI) the caller already worked out (the oscilloscope DC lines of the scope are not in the DMM tables): used instead of the scope lookup
      tc, variant  kind 'TEMP' only: the sensor of the simulation, as Scope.dmm(tc=) and StandardSpec.lookup_temperature(tc=, variant=) take it (default Type K: every engine so far);
                 the Fluke 753 / 754 RTD points pass tc='Pt385-100', variant='Pt 385, 100 Ohm'"""
    if isinstance(standard, str) or isinstance(standard, int):
        key = standard
        standard = sm.standard(key)
        if standard is None:                      # first use on this machine: load the shipped sheets (specs/standards) into lab_registry.sqlite3
            sm.seed()
            standard = sm.standard(key)
    b = Budget(kind, nominal, unit, standard, frequency)
    if scope is None:
        try:
            scope = uncertainty.load()
        except Exception:
            scope = None
    if cmc is not None:
        b.cmc = cmc
    elif scope is not None:
        sensor = {'tc': tc} if (kind == 'TEMP' and tc != 'K') else {}            # only a non-default sensor changes the call (every other engine calls the scope exactly as before)
        b.cmc = (scope.dmm(kind, nominal, range_value, frequency, source=standard, **sensor) if basis is None else scope.dmm(kind, nominal, range_value, frequency, basis=basis, source=standard, **sensor))
    if standard is not None:
        if kind == 'TEMP':        # thermocouple simulation (Type K): the calibrator's degC specification, never the magnitude lookup
            hit = standard.lookup_temperature(nominal, tc=tc, variant=variant) if (tc != 'K' or variant) else standard.lookup_temperature(nominal)
        else:
            hit = standard.lookup('OHM' if kind in ('OHM2', 'OHM4') else kind, nominal, frequency=frequency, direction=direction)
        b.hit = hit
        if getattr(standard, 'model', '') == COIL_MODEL:       # the 50-turn coil: its own scope lines ARE the floor; the larger overlapping amplifier / calibrator lines of the table are other equipment
            b.cmc = hit.limit if hit is not None else None
        if hit is None:
            b.notes.append(f'{standard.model}: no specification row covers this point')
        else:
            div, why = standard.divisor()
            b.add(f'{standard.model} Calibrator', hit.limit / div, 1.0, f'{sm.spec_text(hit)} / {div:g} ({why})' if hasattr(sm, 'spec_text') else f'{hit.limit:.6g} / {div:g} ({why})')
            res, src = (resolution, 'entered') if resolution else standard.resolution(hit)
            if res:
                b.add('Resolution', res / math.sqrt(12), 1.0, f'{res:.6g} / sqrt(12) ({src})')
            else:
                b.notes.append('calibrator resolution unknown: not included - enter it')
    elif resolution:
        b.add('Resolution', resolution / math.sqrt(12), 1.0, f'{resolution:.6g} / sqrt(12) (entered)')
    for name, u, s in type_a:
        b.add(name, u, s, 'Type A')
    for name, u, s in extra:
        b.add(name, u, s, 'entered')
    if scale and float(scale) != 1.0:
        for c in b.components:
            c.sensitivity *= float(scale)
        if b.cmc is not None:
            b.cmc *= float(scale)
        b.notes.append(f'referred to the current the clamp reads: x {float(scale):g}')
    if b.emu is not None:
        b.reported = ceil_sig(max(b.emu, b.cmc or 0.0))
    elif b.cmc is not None:
        b.reported = ceil_sig(b.cmc)
    return b


def osc_dc(volts, impedance='1M', standard='5560A', scope=None):
    """Budget for a DC level a calibrator applies to an oscilloscope input (DC gain, DC offset, DVM DC, trigger level), or None when the laboratory's
    oscilloscope DC CMC does not cover the level (the point then carries no uncertainty, as before: nothing is extrapolated).
    CMC (floor)  = the scope's oscilloscope DC line for that input impedance, ABSOLUTE volts (Scope.oscilloscope('offset', ...)).
    budget       = the calibrator's published DC voltage specification at the level / its coverage divisor, + resolution when the sheet has one, k = 2.
    Reported     = Budget.value / .reported: the larger of the two, never below the CMC.  If the standard or its sheet row is missing the budget has no
    components and the CMC alone is reported (the engines never lose a report over a missing sheet)."""
    if scope is None:
        scope = uncertainty.load()
    level = abs(volts)
    cmc, _unit, _note = scope.oscilloscope('offset', volts=level, impedance=str(impedance))
    if cmc is None:
        return None
    try:
        return build('DCV', level, 'V', standard=standard, scope=scope, cmc=cmc)
    except Exception:
        b = Budget('DCV', level, 'V')
        b.cmc = cmc
        b.reported = ceil_sig(cmc)
        b.notes.append('budget not built: scope CMC used')
        return b


RF_LEVEL_FLOOR_DBM = -48.0       # the printed RF level accuracy rows read 'down to -48 dBm' (96270A Technical Data p.6, Leveling Head O/P)


def rf_level(level_dbm, frequencies, standard='96270A', scope=None, cmc=None):
    """Budget (dB) for an RF level the Fluke 96270A applies to the MDO4000C RF input (absolute amplitude / level flatness sweep), or None when the standard's
    sheet does not cover EVERY swept frequency at that level (nothing is extrapolated, interpolated or taken from a 'typical' row).
    Uses only the sheet's 'RF Level Accuracy ... [Leveling Head O/P]' rows 'down to -48 dBm' (bands 0-100 kHz, 100 kHz-128 MHz, 4 GHz), in dB as printed.
    A sweep takes the LARGEST limit of the bands it crosses (the larger limit at a border, as everywhere).  u = limit / divisor (sheet level, k = 2 when none
    is printed), + resolution only if the sheet row has one, RSS, k = 2.  `cmc` (dB) is the scope CMC where the lab scope has an entry; there is none for RF
    level today, so the default is no floor: reported = ceil_sig(max(EMU, CMC)) when one is given."""
    if isinstance(standard, (str, int)):
        key = standard
        standard = sm.standard(key)
        if standard is None:
            sm.seed()
            standard = sm.standard(key)
    freqs = [f for f in frequencies]
    if standard is None or not freqs or level_dbm < RF_LEVEL_FLOOR_DBM:
        return None
    rows = [r for r in standard.rows if r['function'].startswith('RF Level Accuracy') and 'Leveling Head O/P' in r['function']
            and 'down to -48 dBm' in r['label'] and r['unit'] == 'dB' and r['direction'] == 'output' and r['freq_lo'] is not None]
    worst = None
    for f in freqs:
        hits = []
        for r in rows:
            if r['freq_lo'] <= f <= r['freq_hi']:
                spec = next((x for x in r['specs'] if x['period'] == standard.period and not x.get('error')), None)
                if spec is not None:
                    hits.append(sm.Hit(r, spec, level_dbm))
        if not hits:
            return None
        h = max(hits, key=lambda x: x.limit)
        if worst is None or h.limit > worst.limit:
            worst = h
    b = Budget('RFLEVEL', level_dbm, 'dB', standard, max(freqs))
    b.hit = worst
    b.cmc = cmc
    div, why = standard.divisor()
    b.add(f'{standard.model} level accuracy', worst.limit / div, 1.0, f'{worst.limit:.6g} dB / {div:g} ({why})')
    res, _src = standard.resolution(worst)
    if res:
        b.add('Resolution', res / math.sqrt(12), 1.0, f'{res:.6g} / sqrt(12)')
    else:
        b.notes.append('level resolution is not recorded on the sheet row: not included')
    b.reported = ceil_sig(max(b.emu, b.cmc or 0.0))
    return b


def rf_level_sweep(p, standard='96270A', scope=None, cmc=None):
    """rf_level() for one MDO4000C absolute amplitude / flatness point (`level_dbm`, `f_start`, `f_step`, `f_stop`): every frequency the engine sets.
    The one place the sweep frequencies are worked out - the engine, the review window and the report all call it."""
    freqs, f = [], p['f_start']
    while f <= p['f_stop'] * (1 + 1e-9):
        freqs.append(f)
        f += p['f_step']
    return rf_level(p['level_dbm'], freqs, standard, scope=scope, cmc=cmc)


def audit(reported, b, tolerance=1e-12):
    """Compare an uncertainty someone reported (SI base units) with the budget `b`.  Returns (status, text).
    UNDER CMC is the accreditation problem: nothing may be reported below the scope CMC."""
    if b.cmc is None:
        return NOT_IN_SCOPE, 'The scope of accreditation does not cover this point.'
    if reported < b.cmc * (1 - tolerance):
        return UNDER_CMC, f'Reported {reported:.4g} {b.unit} is below the scope CMC {b.cmc:.4g} {b.unit}.'
    if b.emu is None:
        return NO_SPEC, 'No standard specification available: only the CMC check could be made.'
    if reported < b.emu * (1 - tolerance):
        return UNDER_BUDGET, f'Reported {reported:.4g} {b.unit} is below the budget {b.emu:.4g} {b.unit} built from the standard\'s specification.'
    return OK, f'Reported {reported:.4g} {b.unit} covers the budget {b.emu:.4g} {b.unit} and the CMC {b.cmc:.4g} {b.unit}.'


def tur(tolerance, b):
    """Test uncertainty ratio: +/- tolerance of the unit under test divided by the reported EMU."""
    return tolerance / b.reported if b.reported else None


def reported_text(b):
    if b.reported is None:
        return ''
    return uncertainty.format_value(b.reported, 'ohm' if b.kind.startswith('OHM') else b.unit)
