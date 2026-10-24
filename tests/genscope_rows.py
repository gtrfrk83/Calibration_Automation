"""What the window of a function generator / scope shows after a virtual-bench run, as plain data (no toolkit): the same driver runs the engine behind the Tk window
(tests/record_tk_genscope.py, real Tk 9 under Xvfb: records tests/qt_ref/genscope_rows.json) and behind the Qt window (tests/test_qt_views_genscope.py compares).  Not a test module.

A snapshot holds: the window title, the table rows (id, values as text, tags), the status line and detail text, the section list, the pass / fail counts of the engine's own results,
the rows shown with a status filter and with a section chosen, and the detail text of three selected rows.  Rows come from the engine's `_row`; this only proves that the view hands
them to the table and that the table, the filters, the selection and the variables behave the same."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

REF = Path(__file__).resolve().parent / 'qt_ref' / 'genscope_rows.json'

# key -> (engine, argument, include simulated failures)
SCENARIOS = {
    'fgen_33220A': ('fgen', '33220A', False),
    'fgen_33250A_failures': ('fgen', '33250A', True),
    'fgen_33210A': ('fgen', '33210A', False),
    'mdo4000c': ('mdo', None, False),
    'mdo4000c_failures': ('mdo', None, True),
    'mdo4000c_sa6_rf_rows': ('mdo', 'SA6', False),         # the spectrum analyzer option adds the 96270A RF level / flatness rows
    'tds2000c_2024C': ('tds', '2024C', False),
    'tds2000c_2012C_failures': ('tds', '2012C', True),
}


def build(key, root):
    """The engine App of a scenario on `root` (a window of either toolkit)."""
    engine, arg, failures = SCENARIOS[key]
    if engine == 'fgen':
        import fgen_verification as F
        F.configure(arg)
        app = F.App(root, arg, demo=True)
    elif engine == 'mdo':
        import mdo4000c_verification as M
        app = M.App(root, demo=True)
        if arg:
            app.v_sa.set(arg)
            app.on_config(save=False)
    else:
        import tds2000c_verification as T
        app = T.App(root, demo=True)
        app.v_model.set(arg)
        app.on_config()
    if failures:
        _push_out_of_limits(app)
    app.asset.set('A-1')
    app.serial.set('S-1')
    return app


def _push_out_of_limits(app):
    """The simulated bench measures perfectly: for the 'failures' scenarios every fifth numeric reading is moved outside its limits as it is recorded (the same wrapper in both
    toolkits), so the table, the counts and the filters see FAIL rows."""
    name = '_record_threadsafe' if hasattr(app, '_record_threadsafe') else '_record'          # where the worker's reading is stored
    real = getattr(app, name)

    def record(p, reading, raw, synthetic):
        if isinstance(reading, float) and p['id'] % 5 == 0:
            if 'error' in p:
                reading = p['nominal'] + 3 * p['error']
            elif p.get('low') is not None and p.get('high') is not None:
                reading = p['high'] + (p['high'] - p['low'])
        return real(p, reading, raw, synthetic)
    setattr(app, name, record)


def rows_of(tree):
    return [[iid, [str(v) for v in tree.item(iid)['values']], sorted(str(t) for t in tree.item(iid)['tags'])] for iid in tree.get_children()]


def snapshot(app, title, run, update):
    """Run the whole point list and describe the window.  run(start) calls start() (the Run All button) inside the toolkit's loop and pumps it until the engine is idle, update() lets the toolkit handle pending events."""
    seen = []
    app.status.trace_add('write', lambda *_: seen.append(app.status.get()))
    out = {'title': title, 'rows_before': rows_of(app.tree), 'status_before': app.status.get(), 'detail_before': app.detail.get()}
    if not run(app.run_all):
        raise RuntimeError('the run did not finish')
    update()
    out['rows'] = rows_of(app.tree)
    out['status'] = app.status.get()
    out['status_texts'] = sorted(set(seen))
    out['sections'] = [list(map(str, s)) for s in getattr(app.shell, 'sections', [])]
    res = [str(r.get('result')) for r in app.results.values()]
    out['counts'] = {k: res.count(k) for k in sorted(set(res))}
    out['detail'] = {}
    ids = [r[0] for r in out['rows']]
    pick = [ids[0], ids[len(ids) // 2], ids[-1]]
    fails = [r[0] for r in out['rows'] if 'fail' in r[2]]
    if fails:
        pick.insert(1, fails[0])
    for iid in pick:
        app.tree.selection_set(iid)
        update()
        out['detail'][iid] = app.detail.get()
    out['selected'] = list(app.tree.selection())
    for label in ('Failed (OOT)', 'Passed', 'Not tested'):
        app.show_status.set(label)
        app.refresh()
        update()
        out['filter ' + label] = [r[0] for r in rows_of(app.tree)]
    app.show_status.set('All points')
    sections = out['sections']
    if len(sections) > 1:
        app.pick_section(sections[1][0])
        update()
        out['section ' + sections[1][0]] = [r[0] for r in rows_of(app.tree)]
        app.pick_section('All sections')
    return out
