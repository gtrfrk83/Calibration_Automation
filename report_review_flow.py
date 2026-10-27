"""Toolkit-free part of the review window's entry (shared by the Tk window report_review.py and the Qt window qtui/screens/report_review.py).

    models, demo = build_models(parent, procedure, app=None)      # or UNAVAILABLE: the engine behind `parent` is not covered / cannot be built
    ...the window loop shows one ReviewWindow per model, chained through `details`...
    details['uncertainty_review'] = review_block(models, by=technician)

Moved here unchanged from report_review.py (find_app, hint_kinds, asset_of, is_demo and the model building of ask()); report_review.py re-exports the names.
`parent` is only compared with an object's `.root` (any toolkit's main window object).  Never raises into the engine: errors give UNAVAILABLE.
"""
from __future__ import annotations

import gc
import sys

import report_review_model as M

UNAVAILABLE = object()
COVERED = ('certificate_rows_and_points', 'certificate_pairs', 'certificate_source_records')       # multimeters / fgen, MDO4000C, TDS2000C / WaveSurfer
SHORT = {'As budgeted': 'budgeted', 'Raised to scope': 'raised', 'Not in scope': 'not in scope', 'Standard changed': 'changed', M.MANUAL: 'manual', M.ASSIGNED: 'assigned'}


def find_app(parent):
    """The engine App whose window is `parent`: an object with `.root is parent` and `certificate_rows_and_points`.  None when there is not exactly one."""
    found = []
    for o in gc.get_objects():
        try:
            t = type(o)
            if t.__module__ in ('builtins', 'tkinter', 'tkinter.ttk') or not any(hasattr(t, a) for a in COVERED):
                continue
            if o.__dict__.get('root') is parent:
                found.append(o)
        except Exception:
            continue
    return found[0] if len(found) == 1 else None


def hint_kinds(app):
    """WaveSurfer only: which result kinds the export that opened the dialog will print.  Its per-tab export asks the details BEFORE it builds the report,
    so the kind is only in the caller (`export_calibration_section(kind)`); read it from the stack, read-only, and fall back to every kind with data
    (None) when it cannot be seen.  No other engine needs this."""
    try:
        f = sys._getframe(1)                  # was frame 3 / 6 deep inside report_review.ask; now measured from here so the extra caller frames do not matter
        for _ in range(12):
            if f is None:
                break
            if f.f_code.co_name == 'export_calibration_section' and f.f_locals.get('self') is app and isinstance(f.f_locals.get('kind'), str):
                return [f.f_locals['kind']]
            f = f.f_back
    except Exception:
        pass
    return None


def asset_of(app) -> str:
    """The asset number the technician entered (WaveSurfer calls the field instrument_id)."""
    for name in ('asset', 'instrument_id'):
        var = getattr(app, name, None)
        if var is not None and hasattr(var, 'get'):
            try:
                return str(var.get()).strip()
            except Exception:
                pass
    return ''


def is_demo(app) -> bool:
    try:
        return bool(app.any_synthetic())
    except Exception:
        return bool(getattr(app, 'demo', False))


def build_models(parent, procedure='', app=None):
    """The review models for the engine behind `parent` -> (models, demo), or UNAVAILABLE (use the old popup).  One model per meter of a run queue.
    This is the model-building half of the former report_review.ask(), moved unchanged."""
    try:
        app = app or find_app(parent)
        if app is None:
            return UNAVAILABLE
        meters = [None]
        if app.__dict__.get('_review_all_meters') and hasattr(app, 'queue_wants_run') and app.queue_wants_run():
            meters = list(app.queue.meters)
        keep = app.__dict__.get('_queue_ctx')
        models = []
        try:
            for m in meters:
                if m is not None:
                    app._queue_activate(m)
                specs, default = M.specs_for(app, kinds=hint_kinds(app) if hasattr(app, 'certificate_source_records') else None)
                if not specs:
                    return UNAVAILABLE
                models.append(M.ReviewModel(specs, default, asset=asset_of(app), procedure=procedure))
                _field_annotate(models[-1], app)
        finally:
            if meters != [None] and keep is not None:
                app._queue_activate(keep)
        demo = is_demo(app)
    except Exception as exc:                                      # an engine this phase does not cover, or anything unexpected: the old popup
        print(f'report_review: using the plain report dialog ({type(exc).__name__}: {exc})', file=sys.stderr)
        return UNAVAILABLE
    return models, demo


def _field_annotate(model, app):
    """Mark the model for the 'Assign uncertainty' panel (field_uncertainty.annotate: which rows should carry an uncertainty and print none, and the stored assignment of each).
    Never raises; a model it cannot annotate behaves exactly as before."""
    try:
        import field_uncertainty
        field_uncertainty.annotate(model, app, is_demo(app))
    except Exception:
        pass


def finish(models, details):
    """The last step of the review: the record of every model goes into the details dict (`details['uncertainty_review']`)."""
    details['uncertainty_review'] = M.review_block(models, by=details.get('technician', ''))
    return details
