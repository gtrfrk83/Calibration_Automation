"""Datasheet Builder: current points driven through the 50-turn coil (Fluke 5500A/COIL / 55XXA/COIL).  No tkinter, no instrument I/O.

A clamp-meter current point (ACI / DCI) can be marked "driven through the 50-turn coil".  The point's NOMINAL is what the clamp reads (the effective current); the calibrator
SOURCES nominal / 50 through the coil (the coil is never commanded).  The uncertainty of such a point follows the owner's rule (NOTES.md, 'STANDING RULE: clamp meters on the
50-turn coil', coil_rule.py): the coil's own sheet A2LA-5500A-COIL at the effective current, RSS with the clamp / coil interaction term; below the coil's range (AC under 20.5 A
effective, e.g. 10 A AC: the sheet has no row) the CALIBRATOR's uncertainty at the sourced current and no interaction term.

Storage: Point.settings['coil'] = '50' (the number of turns; absent = not a coil point).  It travels with the point everywhere settings do: the saved datasheet, undo, duplicate,
the 'make multiple rows' copies and the exported spec (step.dsb.stimulus.settings).  An old sheet has no key and is not a coil sheet.
"""
from __future__ import annotations

from decimal import Decimal as D

import coil_rule

KINDS = ('ACI', 'DCI')                                  # only a current point can be driven through the coil
KEY = 'coil'
LABEL = 'Fluke 5500A/COIL (50 turns)'                   # the same wording as the Report Review (report_review_model)
MODEL = coil_rule.COIL_MODEL
TURNS = coil_rule.TURNS


def offered(fn):
    """True for the sections the 'through the 50-turn coil' choice is offered for: current points that the unit under test MEASURES."""
    return fn is not None and fn.kind in KINDS and fn.direction == 'measure'


def is_coil(fn, p):
    """True when point p of function fn is driven through the 50-turn coil."""
    return offered(fn) and str((getattr(p, 'settings', None) or {}).get(KEY) or '').strip() in (str(TURNS), 'True', 'true', '1')


def sourced(nominal):
    """What the calibrator outputs (A) for a clamp reading of `nominal` (A): nominal / 50, exact."""
    return D(str(nominal)) / TURNS


def sourced_float(nominal):
    return coil_rule.sourced_current(float(nominal))


def covers(fn, p):
    """True when the coil's sheet has a row at this point's EFFECTIVE current (and frequency): the coil gives the uncertainty; False: the calibrator's at the sourced current."""
    f = None if p.frequency is None else float(p.frequency)
    return coil_rule.covers(fn.kind, abs(float(p.nominal)), f)


def set_coil(fn, p, on):
    """Mark / unmark point p (call inside the editor's _do).  Only a current section can have it."""
    if on and not offered(fn):
        raise ValueError('Only a current test (AC or DC current measured by the unit under test) can be driven through the 50-turn coil.')
    if on:
        p.settings[KEY] = str(TURNS)
    else:
        p.settings.pop(KEY, None)


def describe(fn, p):
    """One line for the setup text, the grid tooltip and the report: what the calibrator makes and what the clamp reads."""
    nominal = abs(float(p.nominal))
    return (f'Driven through the 50-turn coil: the calibrator sources {sourced_float(nominal):.6g} A and the meter reads {nominal:.6g} A.')


# ---- the cable-change text of the run: the same wording as the Fluke 374 / 375 / 376 jaw rows (specs/build_fluke_376_spec.py coil_common / GROUPS) -------------------------------
def _common(tool='jaw'):
    return [
        ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
        ('Test leads', f'REMOVE the test leads from the VΩ and COM jacks while the current is measured with the {tool} (general practice; the Calibration Manual does not say).'),
        ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
    ]


GROUP_LOW, GROUP_HIGH = 'COIL_AUX', 'COIL_20A'


def group_for(sourced_a):
    """The hook-up group of a coil point: the calibrator's low-current output below 3 A (the 5522A AUX / 5560A VI AUX terminals), else its high-current output (as the 376 rows)."""
    return GROUP_LOW if abs(float(sourced_a)) < 3 else GROUP_HIGH


def groups():
    """{group: dict(title, summary, steps, caution)} the exported spec carries (spec['groups']) for the engine's cable-change window.  The text is the 376 jaw wording;
    diagram files are the owner's (diagrams/hook_fluke376_COIL_*.png) and are added only when they exist."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    out = {
        GROUP_LOW: dict(
            title='Change the cables: 50-turn coil on the calibrator low-current output',
            summary='Calibrator low-current output (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the meter jaw closed around the coil. '
                    'No test leads in the meter jacks.',
            steps=_common() + [
                ('Coil', 'The wired coil is 50 turns (55XXA/COIL). Connect its two ends to the calibrator: Fluke 5522A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO. '
                         'Use plugs rated for the current.'),
                ('Jaw', 'Close the detachable jaw around the coil, jaw fully closed, the coil centred in the opening, the coil leads kept away from the meter body. The meter then reads '
                        '50 x the calibrator current: 0.2 A reads 10 A. (How the jaw sits on the 55XXA/COIL is not described in either manual: UNVERIFIED.)'),
                ('LCOMP', 'Fluke 5522A: for the AC points switch inductive-load compensation (LCOMP) ON at the calibrator front panel when the coil needs it. The program does not set it: '
                          'UNVERIFIED for this coil.'),
                ('Check', 'Compare your connections with the diagram, then continue.')],
            caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads.'),
        GROUP_HIGH: dict(
            title='Change the cables: 50-turn coil on the calibrator high-current output',
            summary='Calibrator high-current output (5522A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 50-turn coil (55XXA/COIL) -> the meter jaw closed around the coil. '
                    'No test leads in the meter jacks.',
            steps=_common() + [
                ('Coil', 'Move the two ends of the 50-turn coil to the calibrator high-current terminals: Fluke 5522A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil, plugs and '
                         'leads must carry the sourced current (the lab\'s coil and calibrator can do 6 A at 440 Hz and 18 A: owner-confirmed).'),
                ('Jaw', 'The detachable jaw stays closed around the coil (centred, jaw fully closed, leads away from the meter body). The meter reads 50 x the calibrator current: '
                        '10 A reads 500 A, 18 A reads 900 A, 6 A reads 300 A.'),
                ('LCOMP', 'Fluke 5522A: AC points with LCOMP ON when the coil needs it (not set by the program; UNVERIFIED for this coil).'),
                ('Check', 'Compare your connections with the diagram, then continue.')],
            caution='Up to 18 A flows in the coil. Duty cycle: the 5500A/COIL data recorded in NOTES.md allows 11 A continuously and 20 A for 2 minutes (then 8 minutes rest); not confirmed '
                    'for this coil (UNVERIFIED). Keep the calibrator in STANDBY whenever you touch the coil or leads; check that the coil and leads are not warm after a long run.'),
    }
    for name, diagram in ((GROUP_LOW, 'diagrams/hook_fluke376_COIL_AUX.png'), (GROUP_HIGH, 'diagrams/hook_fluke376_COIL_20A.png')):
        if (here / diagram).exists():
            out[name]['diagram'] = diagram
    return out
