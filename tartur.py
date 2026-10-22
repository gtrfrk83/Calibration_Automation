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
    if not (_num(low) and _num(high)):
        return _blank('one-sided or missing limits: no tolerance')
    tol = (high - low) / 2.0
    if not tol > 0:
        return _blank('zero-width limits: no tolerance')
    sc = _scope(scope)
    if sc is None:
        return _blank('scope of accreditation not available', tolerance=tol)
    freq = p.get('frequency')
    cmc = sc.dmm(kind, p['nominal'], p.get('range'), freq)
    if cmc is None:
        return _blank('point is not covered by the scope of accreditation', tolerance=tol)
    ounit = 'ohm' if kind.startswith('OHM') else unit

    u = acc = None
    reason = ''
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
    if u is None:
        u = uncertainty.round_up(cmc)                                # the printed value when no budget is available
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
