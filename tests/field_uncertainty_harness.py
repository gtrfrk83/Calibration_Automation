"""Helpers for tests/test_field_uncertainty*.py (not a test module): real engine rows with points the lab scope and the calibrator's sheet do not cover.

    app, T = gap_app()                       # the Truevolt 34470A engine on its simulated bench, plus extra recorded points that print NO uncertainty
    model = review_model(app)                # report_review_model.ReviewModel annotated by field_uncertainty.annotate
    with registry() as path: ...             # a throw-away lab_registry.sqlite3 and the pinned clock (reprint_harness.registry)

The extra points are copies of real Truevolt points moved outside every table (ACV at 2 MHz and 5 MHz: neither the 5560A sheet nor the lab scope has a line), so the engine's own
report row builder (report_pdf.point_row) prints an empty Uncertainty for them, which is the situation a technician meets at a customer site.
"""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402  (installs the tkinter stub)
import test_reprint_review as T  # noqa: E402

registry = R.registry
GAP_IDS = (9001, 9002, 9003)


def gap_app(demo=False, n=14, twin=False):
    app, mod = T.truevolt_app(demo=demo, n=n)
    base = next(p for p in mod.POINTS if p['kind'] == 'ACV' and p.get('frequency') == 1000.0 and p['nominal'] >= 1)
    for pid, f in zip(GAP_IDS, (2e6, 5e6)):
        p = copy.deepcopy(base)
        p.update(id=pid, frequency=f, description=f'AC volts {base["nominal"]:g} V @ {f / 1e6:g} MHz, {base["range"]:g} V range', section_title='AC volts (high frequency)', section='acvhf')
        mod.POINTS.append(p)
        app.found[str(pid)] = dict(reading=base['nominal'] * 1.0001, result='PASS', synthetic=demo, timestamp=R.FIXED.isoformat(timespec='seconds'), data='As Found')
    if twin:                           # a second point under the SAME conditions as 9001 (2 MHz, same level and range), so a typed value may safely be spread over both
        p = copy.deepcopy(mod.POINTS[-2])
        p.update(id=9003, filter_hz=20)       # the report's description names the filter, so this is a different line of the report
        mod.POINTS.append(p)
        app.found['9003'] = dict(app.found['9001'])
    return app, mod


def drop_gap_points(mod):
    mod.POINTS[:] = [p for p in mod.POINTS if p['id'] not in GAP_IDS]


def review_model(app, procedure='Keysight 34470A performance verification', demo=False):
    import field_uncertainty
    import report_review_model as M
    specs, default = M.specs_for(app)
    model = M.ReviewModel(specs, default, asset='A-100', procedure=procedure)
    field_uncertainty.annotate(model, app, demo)
    return model
