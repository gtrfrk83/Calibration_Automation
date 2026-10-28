"""Per-user program settings (File > Settings...): a small JSON store (~/.calibration_suite/settings.json, ui_theme_core.Settings) and the list of options the
Settings window shows.  Toolkit-free; never raises.  Only things that change how the program behaves for the person, never an instrument command, a limit, a
pass / fail rule or a safety prompt.

Manual data entry, two switches (both on by default = how the program has always behaved):
  MANUAL_OVERRIDE  'Enter reading manually' on a procedure that reads the instrument itself (button, right-click entry, the typed replacement of a reading that failed).
  HAND_SECTIONS    typing readings into the test point grid of the sections of an automated datasheet that its author set to 'Typed by hand'.
A manual calibration (a sheet whose readings are all typed, e.g. an imported .MDD) is never switched off by these: typing is its whole procedure.
"""
from __future__ import annotations

import ui_theme_core as core

MANUAL_OVERRIDE = 'manual_override'
HAND_SECTIONS = 'hand_sections'

# (key, group, label, explanation, default)
OPTIONS = (
    (MANUAL_OVERRIDE, 'Manual data entry', 'Allow typing a reading instead of the automatic one',
     "On procedures that read the instrument themselves: 'Enter reading manually' (action button and right-click entry), and the typed reading offered when an automatic "
     'reading fails. Off: the button and the entry stay but say that manual entry is switched off.', True),
    (HAND_SECTIONS, 'Manual data entry', "Allow typing readings in sections set to 'Typed by hand'",
     'Automated datasheets can have sections the author set to Typed by hand. Off: those sections refuse typed readings in the grid. '
     'Manual calibrations (every reading typed) are not affected.', True),
)
DEFAULTS = {k: d for k, _g, _l, _e, d in OPTIONS}
NAME = 'settings'


def _store():
    return core.Settings(NAME)


def get(key, default=None):
    """The saved value of a setting (its default when never set or unreadable)."""
    try:
        v = _store().get(key, DEFAULTS.get(key, default))
    except Exception:
        v = DEFAULTS.get(key, default)
    return bool(v) if isinstance(DEFAULTS.get(key), bool) else v


def set_many(values: dict) -> None:
    """Save several settings at once (unknown keys are ignored)."""
    s = _store()
    for k, v in values.items():
        if k in DEFAULTS:
            s.set(k, bool(v) if isinstance(DEFAULTS[k], bool) else v)
    s.save()


def manual_override_on() -> bool:
    return get(MANUAL_OVERRIDE)


def hand_sections_on() -> bool:
    return get(HAND_SECTIONS)


# ---- default addresses of the standards (File > Settings > Instrument addresses) ----------------------------------------------------------------------
# {model: address} saved once, used by every procedure that operates that standard.  A procedure still keeps its own address box; this only decides what it starts with:
#   * never saved by that procedure on this computer -> the address from here (the box shows it, the person can change it for that procedure);
#   * ADDRESSES_FIRST on ("use these every time") -> the address from here even when the procedure remembered another one.
# Only the STANDARDS are covered (calibrators, 5790B, 3458A, counters, DMMs used as standards): the instrument under test keeps its own address in its procedure.
ADDRESSES = 'addresses'
ADDRESSES_FIRST = 'addresses_first'
STANDARD_MODELS = ('5560A', '5522A', '5520A', '5790B', '3458A', '34461A', '34465A', '53131A', '53132A', '96270A', '8563E', '8902A')
CALIBRATORS = ('5560A', '5522A', '5520A')                  # one calibrator box in the procedures: the model chosen there picks which address applies
DEFAULTS[ADDRESSES] = {}
DEFAULTS[ADDRESSES_FIRST] = False


def addresses() -> dict:
    """{model: address} of the non-empty default addresses."""
    try:
        v = _store().get(ADDRESSES, {})
    except Exception:
        v = {}
    return {str(m): str(a).strip() for m, a in (v or {}).items() if str(a or '').strip()} if isinstance(v, dict) else {}


def set_addresses(mapping: dict, first: bool) -> None:
    s = _store()
    s.set(ADDRESSES, {m: str(a).strip() for m, a in mapping.items() if m in STANDARD_MODELS and str(a or '').strip()})
    s.set(ADDRESSES_FIRST, bool(first))
    s.save()


def _calibrator_model(data: dict, addrs: dict):
    """The calibrator the procedure has chosen (its saved cal_mode / cal_model text), else the first calibrator that has a default address."""
    text = ' '.join(str(data.get(k, '')) for k in ('cal_mode', 'cal_model'))
    for m in CALIBRATORS:
        if m[:4] in text:
            return m
    return next((m for m in CALIBRATORS if m in addrs), None)


def address_for(key: str, data: dict):
    """The default address a procedure's settings key `key` should start with, or None.  `data` = what that procedure has saved (it names the chosen calibrator).
    Covered keys: 'addr_<model>' (every Datasheet Builder procedure) and the calibrator box ('cal_addr' / 'cal'); anything else is None."""
    try:
        addrs = addresses()
        if not addrs:
            return None
        if key.startswith('addr_') and key[5:] in STANDARD_MODELS:
            return addrs.get(key[5:])
        if key in ('cal_addr', 'cal'):
            m = _calibrator_model(data, addrs)
            return addrs.get(m) if m else None
    except Exception:
        pass
    return None


def address_first() -> bool:
    try:
        return bool(_store().get(ADDRESSES_FIRST, False))
    except Exception:
        return False


OFF_TEXT = 'Manual data entry is switched off (File > Settings).'
