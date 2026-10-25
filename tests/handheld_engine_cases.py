"""The engine-level runs compared between the Tk build and the Qt window (tests/test_qt_views_handheld.py).  Not a test module.

`run_case(make_harness, case)` runs one handheld run on the virtual bench with the harness it is given and returns what the operator sees of it (`snapshot`).  The Tk
reference needs the stubbed tkinter of tests/_tk_stub.py (the Tk-level harness has no display): as a script this module blocks the real tkinter, installs the stub, runs
the case at the Tk level and prints the snapshot as JSON:    python tests/handheld_engine_cases.py <case>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CASES = {
    '117': dict(model='117', spec='fluke_110_series_pv.json'),
    '289': dict(model='289', spec='fluke_287_289_pv.json'),
    '376_iflex_off': dict(model='376', spec='fluke_376_pv.json', engine='iflex', iflex_off=True),
    'mm325': dict(model='MM325', spec='klein_mm325_pv.json'),
    'queue_117': dict(model='117', spec='fluke_110_series_pv.json', queue=[('4412', 'S-4412', 'T 1'), ('4413', 'S-4413', 'T 2')]),
}


def status_text(app):
    """The status line.  The Tk-level harness replaces the shell with a mock, whose status variable keeps its `set` calls: the last one is what the line shows."""
    st = app.status
    if hasattr(st.set, 'call_args'):
        return st.set.call_args[0][0] if st.set.call_args else ''
    return st.get()


def snapshot(app):
    """The table rows (values and tags), the status line, the detail text of three points, the recorded points and the queue's per-meter records."""
    rows = [(p['id'], [str(v) for v in values], list(tags)) for p in app.points for values, tags in [app._row(p)]]
    details = {}
    for p in (app.points[0], app.points[len(app.points) // 2], app.points[-1]):
        app.tree.selection.return_value = (p['id'],)
        app.on_select()
        details[p['id']] = app.detail.get()
    app.tree.selection.return_value = ()
    snap = dict(rows=rows, status=status_text(app), details=details, found=sorted(app.found), left=sorted(app.left),
                results={k: v.get('result') for k, v in app.results.items()})
    q = getattr(app, 'queue', None)
    if q is not None and q.meters:
        snap['queue'] = [(m.asset, sorted(m.found), sorted(m.left), {k: v.get('result') for k, v in m.found.items()}) for m in q.meters]
    return json.loads(json.dumps(snap))


def run_case(make_harness, name):
    import handheld_dmm as hh
    import iflex_option
    case = CASES[name]
    hn = make_harness(None)
    hn.start()
    try:
        mod = iflex_option if case.get('engine') == 'iflex' else hh
        app = mod.App(hn.root, case['model'], demo=True, spec=hh.load_spec(case['spec']), fast_demo=False)
        app.asset.set('A-1')
        app.serial.set('S-1')
        app.demo_failures = None
        app.demo_failures_on = False
        hn.app = app
        hn.fill = True
        if case.get('iflex_off'):
            app.set_include('iflex', False)
        if case.get('queue'):
            app.apply_queue(case['queue'], 'point_by_point')
        assert hn.run_all()
        return snapshot(app)
    finally:
        hn.stop()


def main(argv):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(HERE))
    for name in ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext'):
        sys.modules[name] = None                                  # the real tkinter needs a display: the Tk-level harness runs on the stub
    import _tk_stub
    assert _tk_stub.install()
    import ui_prompt_capture as C
    sys.stdout.write(json.dumps(run_case(lambda answers: C.TkLevelHarness(answers), argv[0])))


if __name__ == '__main__':
    main(sys.argv[1:])
