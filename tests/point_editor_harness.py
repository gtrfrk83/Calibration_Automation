"""Builders for the point-editor tests: each engine's real App on the stubbed Tk, with a throw-away override store and an unlocked developer
session (tests/live_editor_harness.py).  Not a test module."""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402
import dsb_run_harness as DH  # noqa: E402


class Built:
    """app + the harness that keeps it alive; `stop()` releases it."""

    def __init__(self, harness, app, points, env=None):
        self.h, self.app, self.points, self.env = harness, app, points, env or harness.env

    def stop(self):
        self.h.stop()


def _wire(h, app):
    st = app.pm_state
    st.store, st.devmode = h.env.store, h.env.dm
    return app


def truevolt():
    import truevolt_verification as T
    h = H.EngineHarness().start(T)
    app = _wire(h, T.App(h.root, '34470A', demo=False))
    return Built(h, app, T.POINTS)


def dacq(model='34970A'):
    import dacq_verification as D
    h = H.EngineHarness().start(D)
    D.configure(model)
    app = _wire(h, D.App(h.root, model, demo=False))
    return Built(h, app, D.POINTS)


def a34401():
    import Agilent_34401A as A
    h = H.EngineHarness().start(A)
    with mock.patch.object(A.App, 'refresh_ports', lambda self_: None):
        app = _wire(h, A.App(h.root, demo=False))
    return Built(h, app, A.POINTS)


def f8846():
    import Fluke_8846A_Verification as V
    h = H.EngineHarness().start(V)
    with mock.patch.object(V.App, 'refresh_ports', lambda self_: None):
        app = _wire(h, V.App(h.root, demo=False))
    return Built(h, app, V.POINTS)


def fgen():
    import fgen_verification as F
    h = H.EngineHarness().start(F)
    F.configure('33220A')
    app = _wire(h, F.App(h.root, '33220A', demo=False))
    return Built(h, app, F.POINTS)


def mdo():
    import mdo4000c_verification as M
    scale0 = M.SLEEP_SCALE
    M.SLEEP_SCALE = 0
    h = H.EngineHarness().start(M)
    app = _wire(h, M.App(h.root, demo=False))
    app.read_cfg()
    b = Built(h, app, [p for p in M.POINTS if app.cfg.applies(p)])

    def stop():
        M.SLEEP_SCALE = scale0                                   # a module global: never leak it into other tests
        h.stop()
    b.stop = stop
    return b


def handheld(model='115'):
    import handheld_dmm as HH
    h = DH.Harness().start()
    env = H.Env()
    app = HH.App(h.root, model, demo=False)
    st = app.pm_state
    st.store, st.devmode = env.store, env.dm
    app.cal_mode.set(HH.CAL_CHOICES[1])                      # Fluke 5522A, automatic
    b = Built(h, app, app.points, env)
    b.stop = lambda: (h.stop(), env.close())
    return b


def wavesurfer():
    import tempfile
    import WaveSurfer_WS4104HD as W
    env = H.Env()
    home = tempfile.TemporaryDirectory()
    p = mock.patch.dict('os.environ', {'CALSUITE_DATA': home.name, 'HOME': home.name, 'USERPROFILE': home.name})
    p.start()
    app = object.__new__(W.RMSNoiseApp)
    app.tb_period_us = H._tk_stub._Var(value='10')
    app.instrument_id = H._tk_stub._Var(value='WS-1')
    app.pm_init('ws', 'WS4104HD', demo=False, store=env.store, devmode=env.dm)
    for name in ('dc_rows', 'imp_rows', 'offset_rows', 'bw_rows', 'tb_rows', 'trig_rows'):
        setattr(app, name, [])
    for name in ('dc_running', 'imp_running', 'offset_running', 'bw_running', 'tb_running', 'trig_running', 'running'):
        setattr(app, name, False)
    state = {'running': False}
    app._batch_busy = lambda: state['running']
    for var, _n, _d, text in W.PM_VARS:
        setattr(app, var, H._tk_stub._Var(value=text))
    app._pm_ws_last = {v: getattr(app, v).get() for v, *_r in W.PM_VARS}
    app._pm_write_sidecar = lambda: None
    app.root = mock.MagicMock()
    type(app).busy = property(lambda self_: state['running'])

    class B(Built):
        def stop(self):
            p.stop()
            if 'busy' in vars(type(app)):
                delattr(type(app), 'busy')
            env.close()
            home.cleanup()
    b = B(None, app, [], env)
    b.state = state
    return b
