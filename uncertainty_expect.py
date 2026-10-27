"""Which report points SHOULD carry an uncertainty, and whether the lab scope covers them.  Toolkit-free; the one definition shared by
tools/readiness_run.py (the readiness check's `uncertainty` finding) and field_uncertainty.py (the 'No uncertainty for this point: Assign' call to action).

Moved unchanged from tools/readiness_run.py (`_should_have`, `_covered`); readiness_run now calls these, so the app and the readiness check can never disagree
about which points are expected to print an uncertainty.
"""
from __future__ import annotations


def should_have(app, p) -> bool:
    """Is this point supposed to print an uncertainty?  The engine's own rule when it has one (handheld has_uncertainty), else the Datasheet
    Builder's: a kind that is in the CMC table, sourced by a calibrator, not a zero-offset / no-source / typed-standard / no_uncertainty point."""
    fn = getattr(app, 'has_uncertainty', None)
    if callable(fn):
        try:
            if p.get('test') not in (None, 'numeric', 'beeper'):       # handheld yes / no checks (VoltAlert, display) print no uncertainty row
                return False
            return bool(fn(p))
        except Exception:
            return False
    import datasheet_builder_rules as dbr
    if p.get('no_uncertainty') or p.get('zero_offset') or p.get('source') in ('none', 'manual') or p.get('manual') or p.get('is_manual'):
        return False
    is_manual = getattr(app, 'is_manual', None)           # 8808A: a point the selected calibrator cannot make is measured against the technician's own standard
    if callable(is_manual):
        try:
            if is_manual(p):
                return False
        except Exception:
            pass
    return p.get('kind') in dbr.SHOULD_HAVE_KINDS


def covered(app, p):
    """Does the lab's scope of accreditation (CMC table) cover this point?  None = cannot tell.  A blank Uncertainty is expected where it does not."""
    try:
        import report_pdf
        sc = report_pdf.scope()
        if sc is None:
            return None
        a = p.get('applied')
        if a:                                           # handheld: the source value is in 'applied'
            kind = 'OHM2' if p.get('kind') == 'OHM' else p.get('kind')
            nominal, freq, rng = a.get('value'), a.get('frequency'), None
        else:
            kind, nominal, freq, rng = p.get('kind'), p.get('nominal'), p.get('frequency'), p.get('range')
        return sc.dmm(kind, nominal, rng, freq) is not None
    except Exception:
        return None
