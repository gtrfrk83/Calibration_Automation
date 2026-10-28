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
CONFIRM_DELETE = 'confirm_delete'
SHOW_DEMO = 'show_demo'
REPORT_TAR = 'report_tar'
REPORT_TUR = 'report_tur'
REPORT_LAST = 'report_last_choice'
REPORT_FOLDER = 'report_folder'

# (key, group, label, explanation, default)
OPTIONS = (
    (MANUAL_OVERRIDE, 'Manual data entry', 'Allow typing a reading instead of the automatic one',
     "On procedures that read the instrument themselves: 'Enter reading manually' (action button and right-click entry), and the typed reading offered when an automatic "
     'reading fails. Off: the button and the entry stay but say that manual entry is switched off.', True),
    (HAND_SECTIONS, 'Manual data entry', "Allow typing readings in sections set to 'Typed by hand'",
     'Automated datasheets can have sections the author set to Typed by hand. Off: those sections refuse typed readings in the grid. '
     'Manual calibrations (every reading typed) are not affected.', True),
    (CONFIRM_DELETE, 'Manual data entry', 'Ask before deleting a typed reading',
     'Clearing a reading in the test point grid (empty box + Enter, or the Delete key) asks first.', True),
    (REPORT_TAR, 'Reports', 'Show TAR on the report by default',
     'The Report details window starts with TAR ticked or not; it can still be changed for each report. Off by default.', False),
    (REPORT_TUR, 'Reports', 'Show TUR on the report by default',
     'The same for TUR. Off by default.', False),
    (REPORT_LAST, 'Reports', "Start each report from the last report's TAR / TUR choice",
     'Off: every report starts from the two defaults above. On: it starts from what was ticked last time (the older behaviour).', False),
    (SHOW_DEMO, 'Manager', "Show the 'Try in demo mode' buttons",
     'Off hides the demo buttons in the Procedure Manager (a demo can still be started from the command line).', True),
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
            s.set(k, bool(v) if isinstance(DEFAULTS[k], bool) else (str(v).strip() if isinstance(DEFAULTS[k], str) else v))
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
STANDARD_MODELS = ('5560A', '5522A', '5520A', '5790B', '3458A', '34461A', '34465A', '53131A', '53132A', '96270A', '33250A', '8563E', '8902A')
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
    """The calibrator the procedure has chosen (its saved cal_mode / cal_model text).  Not chosen yet: the only calibrator that has a default address, else None
    (two or more calibrator defaults and no choice: the procedure's own default stays, so an address is never sent to the wrong calibrator)."""
    text = ' '.join(str(data.get(k, '')) for k in ('cal_mode', 'cal_model'))
    for m in CALIBRATORS:
        if m[:4] in text:
            return m
    have = [m for m in CALIBRATORS if m in addrs]
    return have[0] if len(have) == 1 else None


COUNTERS = ('53132A', '53131A')                            # a procedure's 'counter' box: the counter that has a default address (the 53132A first)
BAUDS = ('9600', '19200', '38400', '57600', '115200', '4800')
CAL_BAUD = 'cal_baud_default'
DEFAULTS[CAL_BAUD] = ''
DEFAULTS[REPORT_FOLDER] = ''


def address_for(key: str, data: dict, name: str = ''):
    """The default a procedure's settings key `key` should start with, or None.  `data` = what that procedure has saved (it names the chosen calibrator), `name` = the
    procedure's settings store name.  Covered keys (the STANDARDS only; the instrument under test is never touched):
      addr_<model>            every Datasheet Builder procedure
      cal_addr / cal          the calibrator box (the chosen calibrator model picks the address)
      cal_baud                the calibrator's serial baud rate (one default for all calibrators)
      std                     the 5790B of the function generator procedures (fgen_*)
      counter                 the counter box of the function generator / MDO procedures
      rf_addr / rf1 / rf2     the 96270A RF source (53220A, MDO)
      gen_addr / gen          the 33250A function / pulse generator (53220A, MDO)"""
    try:
        if key == 'cal_baud':
            v = str(_store().get(CAL_BAUD, '') or '').strip()
            return v or None
        addrs = addresses()
        if not addrs:
            return None
        if key.startswith('addr_') and key[5:] in STANDARD_MODELS:
            return addrs.get(key[5:])
        if key in ('cal_addr', 'cal'):
            m = _calibrator_model(data, addrs)
            return addrs.get(m) if m else None
        if key == 'std' and name.startswith('fgen_'):
            return addrs.get('5790B')
        if key == 'counter':
            return next((addrs[m] for m in COUNTERS if m in addrs), None)
        if key in ('rf_addr', 'rf1', 'rf2'):
            return addrs.get('96270A')
        if key in ('gen_addr', 'gen'):
            return addrs.get('33250A')
    except Exception:
        pass
    return None


def address_first() -> bool:
    try:
        return bool(_store().get(ADDRESSES_FIRST, False))
    except Exception:
        return False


OFF_TEXT = 'Manual data entry is switched off (File > Settings).'


def report_folder() -> str:
    """The folder a report's Save dialog starts in ('' = the dialog's own choice).  Only a folder that exists is returned."""
    from pathlib import Path
    try:
        v = str(_store().get(REPORT_FOLDER, '') or '').strip()
        return v if v and Path(v).is_dir() else ''
    except Exception:
        return ''
