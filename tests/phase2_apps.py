"""Engine Apps for the oscilloscope / generator procedures after a (sampled) run on the simulated benches, without a window (not a test module).

    app = mdo_app() / fgen_app() / tds_app() / wavesurfer_app()          .root is a sentinel object (the review window finds the App by it)

Mirrors tests/tartur_scopes_harness.py (MDO4000C, 33220A, WaveSurfer demo data) and tests/reprint_harness.tds_export (TDS2000C); tkinter must already be
stubbed (reprint_harness installs tests/_tk_stub.py).  Real readings come from the simulated benches (drivers/simulated_*.py); a point the simulated
source cannot make falls back to the engine's own demo_reading."""
import collections
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(ROOT / 'Procedures'), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

STAMP = '2026-01-02T03:04:05'


class Var:
    def __init__(self, v=''):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class Root:
    """A stand-in for the Tk root: identity, and any method (title, after ...) does nothing."""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: None


def _no_sleep():
    import time
    time.sleep = lambda s: None


def mdo_app(per_kind=3):
    import mdo4000c_verification as M
    from drivers.simulated_mdo import make_mdo_bench
    _no_sleep()
    M.SLEEP_SCALE = 0
    bench, t = make_mdo_bench()
    io = M.IO(dict(cal_baud=9600), transports=t)
    cfg = M.Config('4104C', 'SA6', True, True, True)

    class FakeApp:
        stop = False

        def __init__(s):
            s.io, s.cfg = io, cfg

        def request(s, kind, payload=None):
            return payload['p']['nominal'] if kind == 'manual' else True

        def post(s, *a, **k):
            pass
    runner = M.Runner(FakeApp())
    seen, found = collections.Counter(), {}
    for p in M.POINTS:
        if not cfg.applies(p) or seen[p['kind']] >= per_kind:
            continue
        seen[p['kind']] += 1
        try:
            out_ = runner.run_point(p)
            reading, raw = out_ if isinstance(out_, tuple) else (out_, {})
        except Exception:
            reading, raw = M.demo_reading(p), {}
        raw = dict(raw, reading=reading)
        found[str(p['id'])] = dict(reading=reading, raw=raw, result=M.judge(p, reading), synthetic=False, uncertainty=M.uncertainty_text(p, raw),
                                   timestamp=STAMP, data='As Found')
    app = M.App.__new__(M.App)
    app.cfg = cfg
    app._found = found
    app._left = {k: dict(v, reading=v['reading'] * 1.0001 if isinstance(v['reading'], (int, float)) else v['reading']) for k, v in list(found.items())[1:6]}
    app.asset, app.serial, app.status, app.root = Var('A-200'), Var('S1'), Var(), Root()
    app.any_synthetic = lambda: False
    return app, M


def fgen_app(model='33220A'):
    import fgen_verification as F
    from drivers.simulated_fgen import make_fgen_bench
    _no_sleep()
    F.configure(model)
    bench, t = make_fgen_bench(F.MODEL)
    io = F.IO({}, transports=t, ask_number=lambda prompt, unit: 0.0)
    res, cache = {}, {}
    for p in F.POINTS:
        try:
            v, raw = io.measure(p, res, cache)
        except Exception:
            v, raw = F.demo_reading(p)
        res[str(p['id'])] = dict(reading=v, raw=raw, result=F.judge(p, v), synthetic=False, timestamp=STAMP)
    app = F.App.__new__(F.App)
    app._found = res
    app._left = {k: dict(v, reading=v['reading'] * 1.0001) for k, v in list(res.items())[2:9]}
    app.asset, app.serial, app.status, app.root, app.period = Var('A-300'), Var('S1'), Var(), Root(), Var('1 year')
    app.any_synthetic = lambda: False
    return app, F


def tds_app(n=30):
    import golden_engines as ge
    import tds2000c_verification as T
    from drivers.simulated_tds import make_tds_bench
    T.SLEEP_SCALE = 0
    bench, t = make_tds_bench('2024C')
    io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports={k: v for k, v in t.items() if k != 'dmm'})
    cfg = T.Config('2024C')

    class FakeApp:
        stop = False

        def __init__(s):
            s.io, s.cfg = io, cfg

        def request(s, kind, payload=None):
            return True

        def post(s, *a, **k):
            pass

        def cal_text(s):
            return 'Fluke 5560A'
    io.reset_at_start()
    runner = T.Runner(FakeApp())
    app = object.__new__(T.App)
    app.cfg, app.asset, app.serial, app.status, app.root = cfg, Var('A-400'), Var('S2'), Var(), Root()
    pts = [p for p in T.POINTS if cfg.applies(p) and p['kind'] != 'SELFCAL']
    for p in ge.sample(pts, lambda p: p['kind'], n):
        out_ = runner.run_point(p)
        reading, raw = out_ if isinstance(out_, tuple) else (out_, {})
        raw = dict(raw, reading=reading)
        app.found[str(p['id'])] = dict(reading=reading, raw=raw, result=T.judge(p, reading), synthetic=False, uncertainty=T.uncertainty_text(p, raw),
                                       timestamp=STAMP, data='As Found')
    for key in list(app.found)[:2]:
        app.left[key] = dict(app.found[key], data='As Left')
    app.any_synthetic = lambda: False
    return app, T


def wavesurfer_app():
    import _tk_stub as st
    import WaveSurfer_WS4104HD as W
    app = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
    for a in ('rows', 'dc_rows', 'imp_rows', 'offset_rows', 'bw_rows', 'tb_rows', 'trig_rows'):
        setattr(app, a, [])
    app.root = Root()
    app.demo_mode = False
    for n in dir(W.RMSNoiseApp):
        if n.startswith('refresh_') or n.startswith('render_'):
            setattr(app, n, lambda *a, **k: None)
    app.add_result = lambda r: app.rows.append(r)
    app.imp_progress = {}
    for n in ('status', 'dc_status', 'imp_status', 'offset_status', 'bw_status', 'tb_status', 'trig_status', 'instrument_id', 'serial'):
        setattr(app, n, Var('A-500' if n == 'instrument_id' else ''))
    app.sync_asset = lambda: True
    app._mode = W.datamode.FOUND
    app.any_synthetic = lambda: False
    W.RMSNoiseApp.__getattr__ = lambda self, n: (_ for _ in ()).throw(AttributeError(n)) if n.startswith('__') else Var('10')
    try:
        import tkinter.messagebox as tk_messagebox                     # the WaveSurfer prompts through ui_port (TkUiPort -> tkinter.messagebox)
        with mock.patch.object(tk_messagebox, 'showinfo', lambda *a, **k: None, create=True):
            app.load_demo_data()
    finally:
        del W.RMSNoiseApp.__getattr__
    app.demo_mode = False
    W.RMSNoiseApp.any_synthetic = lambda self: False
    attrs = {a: getattr(app, a) for a in W.RMSNoiseApp._SET_ATTRS if a != 'run_config'}
    left = {a: (list(map(dict, v[:3])) if isinstance(v, list) else v) for a, v in attrs.items()}
    for a in left:
        for r in left[a]:
            r.update({k: r[k] * 1.001 for k in ('measured_v', 'measured_ohm', 'response_db', 'error_hz') if k in r})
    left['run_config'] = None
    app._mode_sets = {W.datamode.LEFT: left}
    return app, W
