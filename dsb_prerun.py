"""Datasheet Builder, rule 2 at run time: the PRE-RUN LIST.  A real run of a user-built datasheet may use only commands that have a manual page reference and a
verified flag; every other command it would send is listed here and the operator must accept the list before any real instrument is opened.

    dsb_prerun.accepted(root, spec, accepted_fingerprint='', ask=None)   -> True to go on, False to stop (nothing was opened)
    dsb_prerun.pre_run(spec)                                              -> dict(lines, count, points, fingerprint, dry, error)

The list is worked out by the same dry run the Builder's Sheet check uses (datasheet_builder_rules: the real driver code on the simulated bench), from the
datasheet the runnable spec carries.  `accepted_fingerprint` is the fingerprint of the list the Builder already showed and the operator accepted ('Run on real
instruments' question): the same list is not asked twice.  When the list cannot be worked out the operator is asked that, plainly (fail closed).  Demo runs
never come here (no real instrument is opened).  Nothing in the engine, the drivers, a limit or a safety prompt is changed by this module.
"""
from __future__ import annotations

from ui_port import ui as port          # the list window's toolkit code is dsb_prerun_view_tk / _qt (reached through the UI port)

MAX_SHOWN = 60


def pre_run(spec):
    """The unverified commands of the datasheet in `spec` (a runnable user-built spec).  Never raises: {'error': text} when it cannot be worked out."""
    try:
        import datasheet_builder_rules as rules
        import datasheet_builder_specs as dsp
        if (spec.get('options') or {}).get('manual_entry'):
            return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error='')
        ds = dsp.datasheet_from_spec(spec)
        if ds is None:
            return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error='the spec carries no datasheet to check')
        chk = rules.check(ds, (spec.get('dsb') or {}).get('period'))
        return dict(lines=chk.pre_run_lines(), count=len(chk.unverified), points=len(chk.unverified_points()), fingerprint=chk.fingerprint(), dry=chk.dry.available, error='')
    except Exception as exc:
        return dict(lines=[], count=0, points=0, fingerprint='', dry=False, error=f'{type(exc).__name__}: {exc}')


def intro(info):
    if info.get('intro'):
        return info['intro']
    n, pts = info['count'], info['points']
    return (f'This run would send {n} command{"s" * (n != 1)} that {"are" if n != 1 else "is"} not verified on hardware or not tied to a manual page '
            f'({pts} point{"s" * (pts != 1)} use them). Real instruments run only after you accept the list.')


def list_text(info):
    """The lines of the list as shown (at most MAX_SHOWN, then '... and n more')."""
    shown = info['lines'][:MAX_SHOWN]
    return '\n'.join(f'  {l}' for l in shown) + (f'\n  ... and {len(info["lines"]) - MAX_SHOWN} more' if len(info['lines']) > MAX_SHOWN else '')


def show_list(root, info):
    """The modal list: scrolling text, 'Accept and run' (not the default) and 'Cancel'.  Returns True when accepted."""
    return port.view('dsb_prerun_view').show_list(root, intro(info), list_text(info))


def accepted(root, spec, accepted_fingerprint='', ask=None):
    """True when the run may go on.  `ask(info)` replaces the dialog (tests)."""
    info = pre_run(spec)
    if info['error']:
        info = dict(info, lines=[], count=0, points=0, intro=f'The list of unverified commands could not be worked out ({info["error"]}). '
                    'Real instruments run only after you accept that the commands are unchecked.')
        return bool((ask or (lambda i: show_list(root, i)))(info))
    if not info['count']:
        return True
    if accepted_fingerprint and accepted_fingerprint == info['fingerprint']:
        return True
    return bool((ask or (lambda i: show_list(root, i)))(info))
