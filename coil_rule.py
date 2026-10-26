"""The 50-turn current coil rule (Fluke 5500A/COIL / 55XXA/COIL), owner decisions 2026-10-26 - pure functions, no GUI, no instrument I/O.

A clamp meter whose current points are driven through the 50-turn coil is calibrated with the coil's current, 1/50 of what the clamp reads:
    effective current  = what the clamp reads (the point's nominal);   sourced current = effective / TURNS (what the calibrator outputs).

Uncertainty of such a point:
    * the coil's own sheet A2LA-5500A-COIL (the lab's A2LA scope lines for the coil) at the EFFECTIVE current, in the coil's range
      (AC 20.5 to 1025 A in 45-65 / 65-440 Hz, DC 2 to 3000 A);
    * RSS with the clamp / coil INTERACTION term of the coil data sheet, +/-(0.50 % of the effective output + 0.5 A) (the larger of the two figures the data sheet
      gives, 0.25 % for toroidal-wound clamps such as the 80i-600 and 0.50 % for the others; the 374 / 375 / 376 jaw is not named, so the larger is used: UNVERIFIED, owner
      to confirm), used as a +/- limit divided by the coverage divisor 2 like every standard's specification;
    * a point whose SOURCED current is below the coil's range (AC under 20.5 A) takes the CALIBRATOR's uncertainty at the sourced current instead, with no interaction term,
      SCALED by the 50 turns (owner, 2026-10-26: the clamp reads 50 times the calibrator's current, so the calibrator's uncertainty - and its TAR accuracy and CMC floor - are
      referred to the effective current: x 50).
The coil's own scope line is the CMC floor (the larger overlapping amplifier / calibrator lines of the CMC table are other equipment).
Used by iflex_option.App (the 374 / 375 / 376 / 376-II procedures) and the Datasheet Builder.  tests/test_coil_uncertainty.py guards the procedures."""
from __future__ import annotations

COIL_MODEL = 'A2LA-5500A-COIL'
TURNS = 50
INTERACTION = {'rel': 0.005, 'abs': 0.5, 'text': '+/-(0.50 % of the effective output + 0.5 A), Fluke 5500A/COIL data sheet (10/2026)'}
DIVISOR = 2.0                                                  # the interaction limit is converted like a standard's specification (k = 2)


def effective_current(sourced):
    return sourced * TURNS


def sourced_current(effective):
    return effective / TURNS


def sheet():
    """The coil's StandardSpec (shipped sheets are loaded on first use), or None."""
    import specmanager as sm
    s = sm.standard(COIL_MODEL)
    if s is None:
        sm.seed()
        s = sm.standard(COIL_MODEL)
    return s


def covers(kind, effective, frequency=None) -> bool:
    """True when the coil's sheet has a row for this current at the EFFECTIVE value (AC needs a frequency)."""
    try:
        s = sheet()
        return s is not None and s.lookup(kind, effective, frequency=frequency, direction='output') is not None
    except Exception:
        return False


def interaction_limit(effective, interaction=None) -> float:
    i = interaction or INTERACTION
    return float(i['rel']) * abs(float(effective)) + float(i['abs'])


def extra_components(effective, interaction=None) -> tuple:
    """The clamp / coil interaction as an uncertainty_budget `extra` entry: (name, u at k = 1, sensitivity)."""
    return (('Clamp / coil interaction', interaction_limit(effective, interaction) / DIVISOR, 1.0),)


def uncertainty_source(kind, effective, sourced, frequency=None, interaction=None):
    """(nominal, standard or None, extra components) the uncertainty of a coil point is worked out with: the coil sheet at the effective current plus the interaction term,
    or, below the coil's range, the sourced current with the caller's calibrator (standard None) and nothing extra."""
    if covers(kind, effective, frequency):
        return effective, COIL_MODEL, extra_components(effective, interaction)
    return sourced, None, ()


def uncertainty_scale(kind, effective, frequency=None) -> float:
    """The factor the calibrator's uncertainty (budget, CMC floor and TAR accuracy) is multiplied by: 1 where the coil's sheet covers the point, TURNS (50) in the
    below-range fallback, where the calibrator's figure at the sourced current is referred to the effective current."""
    return 1.0 if covers(kind, effective, frequency) else float(TURNS)
