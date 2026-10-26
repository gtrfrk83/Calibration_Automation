"""Test Accuracy Ratio (TAR) and Test Uncertainty Ratio (TUR) for one report point.

Shown on a report only when a customer requires it (the switch lives in the report dialog); this module only builds the numbers.
Everything is in the point's own base unit (display-only SI scaling is not involved).

Definitions, exactly:
  T   UUT tolerance = half-width of the UUT's pass/fail limits at the point, (high - low) / 2.
      One-sided limits, zero-width or reversed limits: no tolerance, so no ratios.
  TAR = T / A, where A is the published accuracy of the calibrator model at the point: the specmanager lookup limit (Hit.limit)
      for the 1-year / default period, the same figure uncertainty_budget uses.  A is NOT divided by any coverage divisor.
  TUR = T / U, where U is the reported expanded uncertainty (k = 2) exactly as printed in the Uncertainty column:
      uncertainty_budget Budget.reported (max(budget, scope CMC) rounded UP) when a calibrator model is given, otherwise the scope CMC
      rounded UP (uncertainty.round_up).  The reported U is used as the divisor, so TUR matches the printed uncertainty.
Ratios are shown rounded DOWN to 0.1 (never overstated), e.g. '4.2:1'; above 1000 '>1000:1'.  A ratio that cannot be computed is blank,
never 0 or infinity.  Blank (with a reason) for: zero-offset / no-source points, points the scope of accreditation does not cover,
tolerance and uncertainty in different units (% or dB tolerances are not converted), and any error (this module never raises).
TAR is blank when no calibrator model is given or no specification row covers the point; TUR may still be shown in that case.
Temperature (TEMP, thermocouple simulation, degC): the scope's Type K line is the CMC; with a calibrator model the ratios also use its Type K simulation
specification (uncertainty_budget); without a model, outside its range, or for a degF tolerance they are blank.
"""
from __future__ import annotations

import math

NO_UNITS = ('%', 'dB', 'dBm', 'ppm', 'ppb')        # tolerance not in the unit of the measurand: not converted


def _blank(reason, **kw):
    out = dict(tar=None, tur=None, tolerance=None, accuracy=None, uncertainty=None, reason=reason)
    out.update(kw)
    return out


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _scope(scope):
    if scope is not None:
        return scope
    try:
        import uncertainty
        return uncertainty.load()
    except Exception:
        return None


# The unit the standard's accuracy and the scope CMC are expressed in, per point kind. A tolerance in any other unit (the handheld frequency
# and period points are sourced as ACV but read in Hz) is blank, never divided by an uncertainty in a different unit.
NATURAL_UNITS = {'DCV': {'V'}, 'ACV': {'V'}, 'DCI': {'A'}, 'ACI': {'A'}, 'FREQ': {'Hz'}, 'CAP': {'F'},
                 'TEMP': {'C', 'degC', '\u00b0C'},        # a degF tolerance (or any other unit) on a thermocouple point is never divided by a degC uncertainty
                 'LUX': {'lux'}, 'FC': {'FC'}, 'LAMBERT': {'La'}, 'UVIRR': {'uW/cm2'},   # light (A2LA-LIGHT sheet): each in its own unit, never converted
                 'DUTY': set(), 'SQUARE': set(),          # square-wave sources: no ratio (the reading is not in the unit of the calibrator's uncertainty)
                 'OHM': {'ohm', 'Ohm', '\u03a9'}, 'OHM2': {'ohm', 'Ohm', '\u03a9'}, 'OHM4': {'ohm', 'Ohm', '\u03a9'}}


def compute(p, low, high, standard=None, scope=None):
    """Return dict(tar, tur, tolerance, accuracy, uncertainty, reason).  Numbers are floats in base units or None; never raises."""
    try:
        return _compute(p, low, high, standard, scope)
    except Exception as e:                                           # a report must never fail because of an optional ratio
        return _blank(f'not computed: {type(e).__name__}: {e}')


def _compute(p, low, high, standard, scope):
    import uncertainty
    import uncertainty_budget as ub
    if p.get('zero_offset') or p.get('source') == 'none':
        return _blank('zero-offset point: no source, no ratio')
    kind, unit = p['kind'], p['unit']
    if unit in NO_UNITS:
        return _blank(f'tolerance is in {unit}, not in the unit of the uncertainty: not converted')
    natural = NATURAL_UNITS.get(kind)
    if natural is not None and unit not in natural:           # e.g. an ACV source whose reading is a frequency (handheld Hz points)
        return _blank(f'tolerance is in {unit}, but a {kind} uncertainty is not: not converted')
    if not (_num(low) and _num(high)):
        return _blank('one-sided or missing limits: no tolerance')
    tol = (high - low) / 2.0
    if not tol > 0:
        return _blank('zero-width limits: no tolerance')
    sc = _scope(scope)
    if sc is None:
        return _blank('scope of accreditation not available', tolerance=tol)
    freq = p.get('frequency')
    cmc = sc.dmm(kind, p['nominal'], p.get('range'), freq, source=standard)
    # TEMP (thermocouple simulation, Type K): the scope's Type K line (printed p. 13) is the CMC floor, like every other kind; with a calibrator the ratios also use its own degC specification.  Without a calibrator: blank, as before.
    # Light (LUX / FC / LAMBERT / UVIRR): the scope CMC IS the A2LA-LIGHT sheet (no separate scope entry), so with that standard the ratios come from it alone.
    if cmc is None and not (kind in ('TEMP', 'LUX', 'FC', 'LAMBERT', 'UVIRR') and standard):
        return _blank('point is not covered by the scope of accreditation', tolerance=tol)
    ounit = 'ohm' if kind.startswith('OHM') else unit

    u = acc = None
    reason = ''
    if kind == 'FREQ':
        standard = None             # the uncertainty of a frequency is the lab's Frequency - Measure CMC alone (GPS-referenced); no calibrator accuracy is used, so TAR is blank
    if standard:
        b = None
        try:
            b = ub.build(kind, p['nominal'], ounit, standard=standard, frequency=freq, scope=sc, range_value=p.get('range'))
        except Exception as e:
            reason = f'budget not built ({type(e).__name__}); scope CMC used for the uncertainty'
        if b is not None:
            if b.reported is not None:
                u = b.reported
            if b.hit is not None:
                acc = b.hit.limit
            else:
                reason = 'no specification row of the calibrator covers this point: TAR blank'
    if standard and str(getattr(standard, 'model', standard)) == ub.COIL_MODEL and u is None:
        return _blank("the 5500A/COIL's own lines do not cover this point: no uncertainty, no ratio", tolerance=tol)      # the table's other lines are other equipment
    if u is None and cmc is not None:
        u = uncertainty.round_up(cmc)                              # the printed value when no budget is available
    tur = tol / u if u and u > 0 else None
    tar = tol / acc if acc and acc > 0 else None
    return dict(tar=tar, tur=tur, tolerance=tol, accuracy=acc, uncertainty=u,
                reason=reason or ('' if standard else 'no calibrator model given: TAR blank'))


def format_ratio(x):
    """'4.2:1' (rounded DOWN to 0.1), '>1000:1' above 1000, '<0.1:1' for a positive ratio below 0.1, '' for None / nan / inf / <= 0."""
    try:
        if not _num(x) or x <= 0:
            return ''
        if x > 1000:
            return '>1000:1'
        tenths = math.floor(round(x * 10, 7) + 0.0)                  # round() only absorbs float noise (4.2 stored as 4.1999999)
        if tenths < 1:
            return '<0.1:1'
        return f'{tenths / 10:.1f}:1'
    except Exception:
        return ''


def definition_text():
    return ('TAR (test accuracy ratio) is the unit under test tolerance, taken as half the width of its pass/fail limits at the test point, '
            'divided by the published accuracy specification of the calibrator used (1 year), not divided by any coverage factor. '
            'TUR (test uncertainty ratio) is the same tolerance divided by the reported expanded uncertainty of the measurement (k = 2) '
            'shown in the Uncertainty column. Ratios are rounded down to 0.1 and are left blank where the tolerance is one-sided, '
            'is not in the unit of the measurand, or the point has no source or is not covered by the scope of accreditation.')


def row_fields(p, low, high, standard=None):
    """dict(TAR=str, TUR=str) for a report row; blanks on any problem."""
    try:
        r = compute(p, low, high, standard)
        return dict(TAR=format_ratio(r['tar']), TUR=format_ratio(r['tur']))
    except Exception:
        return dict(TAR='', TUR='')


# ---------------------------------------------------------------------------------------------------------------------------------
# Generic helpers for engines whose uncertainty does not come from report_pdf.point_uncertainty (oscilloscope and function generator
# procedures).  They never convert units: a ratio is produced only when its two quantities are expressed in the same unit string.
# compute / format_ratio / definition_text / row_fields above are unchanged.
# ---------------------------------------------------------------------------------------------------------------------------------
def half_width(low, high):
    """UUT tolerance T = (high - low) / 2, or None for one-sided / missing / zero-width / reversed limits."""
    try:
        if _num(low) and _num(high) and high > low:
            return (high - low) / 2.0
    except Exception:
        pass
    return None


def from_values(tolerance, unit, accuracy=None, accuracy_unit=None, uncertainty=None, uncertainty_unit=None):
    """Same dict as compute(), from numbers the caller already has.  Never raises, never converts units.

    tolerance   half-width T of the UUT limits, in `unit` (see half_width)
    accuracy    published accuracy A of the standard at the point, in `accuracy_unit`; TAR = T / A only when accuracy_unit == unit
    uncertainty the expanded uncertainty exactly as printed in the Uncertainty column (already rounded UP by the caller),
                in `uncertainty_unit`; TUR = T / U only when uncertainty_unit == unit
    A ratio whose inputs are missing, not positive, not finite or in different units is None (blank on the report)."""
    try:
        if not unit or not _num(tolerance) or not tolerance > 0:
            return _blank('no usable tolerance (one-sided, zero-width or no unit)')
        reasons = []
        tur = tar = acc = u = None
        if uncertainty is None:
            reasons.append('no printed uncertainty: TUR blank')
        elif not (_num(uncertainty) and uncertainty > 0):
            reasons.append('uncertainty not usable: TUR blank')
        elif uncertainty_unit != unit:
            reasons.append(f'tolerance in {unit}, uncertainty in {uncertainty_unit}: TUR blank, not converted')
        else:
            u = float(uncertainty)
            tur = tolerance / u
        if accuracy is None:
            reasons.append('no standard specification for this point: TAR blank')
        elif not (_num(accuracy) and accuracy > 0):
            reasons.append('accuracy not usable: TAR blank')
        elif accuracy_unit != unit:
            reasons.append(f'tolerance in {unit}, standard specification in {accuracy_unit}: TAR blank, not converted')
        else:
            acc = float(accuracy)
            tar = tolerance / acc
        return dict(tar=tar, tur=tur, tolerance=float(tolerance), accuracy=acc, uncertainty=u, reason='; '.join(reasons))
    except Exception as e:
        return _blank(f'not computed: {type(e).__name__}: {e}')


def ratio_fields(result):
    """dict(TAR=str, TUR=str) from a compute() / from_values() dict; blanks on any problem (the strings row_fields produces)."""
    try:
        return dict(TAR=format_ratio(result['tar']), TUR=format_ratio(result['tur']))
    except Exception:
        return dict(TAR='', TUR='')


def standard_accuracy(model, kind, value, frequency=None, direction='output'):
    """(limit, unit) of the published specification (specmanager lookup, default period) of calibrator `model` at one point,
    or (None, None) when the model or a covering row is missing.  limit is the absolute +/- figure Hit.limit gives, unit the row's own unit."""
    try:
        import specmanager as sm
        std = sm.standard(model)
        if std is None:
            sm.seed()
            std = sm.standard(model)
        if std is None:
            return None, None
        hit = std.lookup(kind, value, frequency=frequency, direction=direction)
        if hit is None:
            return None, None
        return hit.limit, hit.row['unit']
    except Exception:
        return None, None
