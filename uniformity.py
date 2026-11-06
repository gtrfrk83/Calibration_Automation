"""Project-wide values for the uniformity rules (NOTES.md, 'Uniformity rules').  Tk-free; no instrument I/O.

    import uniformity
    uniformity.HV_THRESHOLD_V                      # rule 1: the high-voltage confirmation threshold of every procedure (volts)
    uniformity.within_limits(reading, low, high)   # rule 7: the pass/fail judgement every engine uses (exact decimal, limits inclusive)
    uniformity.handheld_defaults()                 # rule 10: the shared spec options of the handheld_dmm specs (specs/handheld_defaults.json)
    uniformity.FAMILIES                            # rule 12: the allowed sidecar `family` values

Nothing in the suite uses this module yet: engines move onto it one at a time, and tests/test_procedure_conformance.py tracks which ones still
have to (tests/fixtures/conformance_allowlist.json).
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULTS_PATH = HERE / 'specs' / 'handheld_defaults.json'

HV_THRESHOLD_V = 30          # volts, AC or DC: at or above this the operator confirms high voltage, once per hook-up group (owner, 2026-11-05)

FAMILIES = ('handheld-dmm', 'clamp-meter', 'bench-dmm', 'adjustment', 'oscilloscope', 'function-generator', 'frequency-counter', 'rf', 'dacq')


def _dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)                     # the shortest text that round-trips: 100.0091 stays 100.0091, not 100.009099999...
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f'not a number: {value!r}') from exc


def within_limits(reading, low, high) -> bool:
    """True when low <= reading <= high, compared as exact decimals (a reading exactly on a limit passes).  Accepts str, int, float or Decimal;
    floats are taken at their shortest round-trip text, so -100.0091 on a -100.0091 limit passes (in float, abs(-100.0091 + 100) <= 0.0091 is False)."""
    lo, hi = _dec(low), _dec(high)
    if lo > hi:
        lo, hi = hi, lo
    return lo <= _dec(reading) <= hi


def handheld_defaults() -> dict:
    """The shared options of every handheld_dmm spec (rule 10): {option: value}.  A spec that sets a different value names the reason in
    options.option_reasons[option]."""
    data = json.loads(DEFAULTS_PATH.read_text(encoding='utf-8'))
    return dict(data['options'])
