"""Uncertainty of the handheld points whose reading is not in the unit of the calibrator output (opt-in per spec step, `step.unc_kind`).

  DUTY          square-wave source, the meter reads the duty cycle (%): the calibrator's duty-cycle specification at the applied frequency
                (sheet function 'Frequency [Duty Cycle]', %DC).
  SQUARE_PEAK   square-wave source with a DC offset, the meter reads the positive or negative peak (V, Peak Min / Max): peak = offset +/- Vpp / 2, so
                u = sqrt((A_pp / 2)^2 + A_offset^2) / divisor, from the calibrator's square-wave amplitude (Vpp) and DC offset specifications.
  CONDUCTANCE   a resistance source read as conductance (S): the resistance budget (calibrator + CMC floor, as any ohms point) carried over as a relative
                uncertainty, U_G = G x U_R / R.
Expanded at k = 2, rounded up to two figures, never combined with a CMC where the lab's scope has no line for the quantity (square waves: owner decision
2026-10-28, calibrator specification alone, no flag).  The value is None when the calibrator's sheet has no row for the point (the report then stays blank).

`step.unc_text` (opt-in) is a fixed Uncertainty text for a point with no standard applied (open-input points: 'N/A (no standard applied)')."""
from __future__ import annotations

import math

KINDS = ('DUTY', 'SQUARE_PEAK', 'CONDUCTANCE')
K = 2.0


def _standard(model):
    import specmanager as sm
    std = sm.standard(model)
    if std is None:
        sm.seed()
        std = sm.standard(model)
    return std


def evaluate(p, model):
    """(expanded uncertainty in the reading's base unit, published accuracy of the standard in the same unit or None, unit) or None."""
    if not model:
        return None
    a = p.get('applied') or {}
    kind = p.get('unc_kind')
    if kind == 'CONDUCTANCE':
        import uncertainty_budget
        r = float(a['value'])
        b = uncertainty_budget.build('OHM2', r, 'ohm', standard=model)
        if b.value is None:
            return None
        g = 1.0 / r
        acc = b.hit.limit / r * g if b.hit is not None else None
        return b.value / r * g, acc, 'S'
    std = _standard(model)
    if std is None:
        return None
    div = std.divisor()[0]
    f = a.get('frequency')
    if kind == 'DUTY':
        hit = std.lookup('FREQ', float(a.get('duty', 50.0)), variant='Duty', qualifier=('Hz', float(f)))
        if hit is None:
            return None
        return K * hit.limit / div, hit.limit, '%'
    if kind == 'SQUARE_PEAK':
        vpp, offset = float(a['value']), float(a.get('offset', 0.0))
        amp = std.lookup('ACV', vpp, frequency=f, variant='Squarewave (Normal')
        off = std.lookup('ACV', offset, frequency=f, variant='Squarewave DC Offset', qualifier=('Vpp', vpp)) if offset else None
        if amp is None or (offset and off is None):
            return None
        limit = math.sqrt((amp.limit / 2) ** 2 + (off.limit if off else 0.0) ** 2)
        return K * limit / div, limit, 'V'
    return None


def text(p, model):
    """The Uncertainty cell for an opt-in point ('' when the sheet has no row)."""
    if p.get('unc_text'):
        return p['unc_text']
    r = evaluate(p, model)
    if r is None:
        return ''
    import uncertainty
    return uncertainty.format_value(r[0], r[2])


def ratios(p, model, low, high):
    """dict(TAR, TUR) for an opt-in point (low / high: the limits in base units); blanks when either part is missing."""
    import tartur
    import uncertainty
    try:
        r = evaluate(p, model)
        if r is None:
            return dict(TAR='', TUR='')
        u, acc, unit = r
        printed = uncertainty.round_up(u, 2)
        out = tartur.from_values(tartur.half_width(low, high), unit, accuracy=acc, accuracy_unit=unit, uncertainty=printed, uncertainty_unit=unit)
        return dict(TAR=tartur.format_ratio(out['tar']), TUR=tartur.format_ratio(out['tur']))
    except Exception:
        return dict(TAR='', TUR='')
