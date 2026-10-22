"""Short simulated runs of each engine's bench-I/O code, recorded as golden transcripts (see golden_capture.py).

Imported only inside the subprocess started by golden_capture.capture_engine_transcripts(): tkinter is stubbed there (it is not installed
in the CI sandbox) and the clock is pinned. The engines' UI code is never run; what runs is the IO class (or the non-UI run method) that
the engine's worker thread calls, on the simulated benches of drivers/simulated*.py, for a fixed sample of the engine's own test points.

Not covered (cannot run without a Tk main loop, or no headless entry point): the Tk dialogs/threads of every engine, the WaveSurfer
RMS-noise / bandwidth / trigger runs (RMSNoiseApp worker methods are interleaved with Tk state; only the DCV point methods are driven here),
the 8846A adjustment procedure's App (every step is behind a messagebox; its driver calls are covered by the driver fixtures).
"""
from __future__ import annotations

import collections
import json
import queue
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

import drivers  # noqa: E402
from drivers.simulated import SimBench, SimFlukeTransport, make_bench, make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_28x import SimFluke28x  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402
from drivers.simulated_mdo import make_mdo_bench  # noqa: E402
from tests import golden_capture as gc  # noqa: E402


def rec(t):
    return gc.RecordingTransport(t)


def sample(points, key, limit=16):
    """The first point of each distinct key, in spec order (a fixed, small, representative set)."""
    seen, out = set(), []
    for p in points:
        k = key(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def pid(p):
    return f"{p.get('kind')}#{p.get('id', p.get('n', '?'))}"


def _dmm_key(p):
    return (p['kind'], p.get('source'), p.get('filter_hz'), bool(p.get('frequency')), p.get('role'), p.get('terminal'), bool(p.get('plc')))


# --------------------------------------------------------------------------------------------------------------------------------------
class Runner:
    def __init__(self, c):
        self.c = c
        self.obj = None

    def build(self, name, factory):
        holder = {}

        def go():
            holder['o'] = factory()
            return holder['o']
        self.c.run(name, go)
        self.obj = holder.get('o')
        return self.obj


def _measure_all(c, io, points, modname, label=pid):
    for p in points:
        c.run(f'{modname}.IO.measure[{label(p)}]', io.measure, p, _log=io.log)


def run_truevolt():
    import truevolt_verification as T
    T.configure('34470A')
    c = gc.Case('engine_truevolt_34470A')
    bench, ft, dt = make_dmm_bench('34470A')
    r = Runner(c)
    io = r.build('truevolt_verification.IO.__init__', lambda: T.IO('sim', 'sim', transports=(rec(dt), rec(ft))))
    for p in sample(T.POINTS, _dmm_key, 14):
        dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'          # the Front/Rear switch the technician would set
        c.run(f'truevolt_verification.IO.measure[{pid(p)}]', io.measure, p, _log=io.log)
    c.run('truevolt_verification.IO.close', io.close, _log=io.log)
    return c.entries


def run_dacq(model):
    import dacq_verification as D
    D.configure(model)
    c = gc.Case(f'engine_dacq_{model}')
    bench, ft, dt = make_dacq_bench(model)
    r = Runner(c)
    io = r.build('dacq_verification.IO.__init__', lambda: D.IO('sim', 'sim', cal_model='Fluke 5560A', module='34901A', slot=2,
                                                               transports=(rec(dt), rec(ft))))
    _measure_all(c, io, sample(D.POINTS, _dmm_key, 14), 'dacq_verification')
    c.run('dacq_verification.IO.close', io.close, _log=io.log)
    return c.entries


def run_fgen():
    import fgen_verification as F
    F.configure('33220A')
    c = gc.Case('engine_fgen_33220A')
    bench, t = make_fgen_bench('33220A')
    wrapped = {k: rec(v) for k, v in t.items()}
    r = Runner(c)
    io = r.build('fgen_verification.IO.__init__', lambda: F.IO({}, transports=wrapped, ask_number=lambda prompt, unit: 0.0))
    results, cache = {}, {}
    for p in sample(F.POINTS, lambda p: (p['kind'], p.get('section'), p.get('function'), p.get('amp_unit'), p.get('load')), 16):
        bench.connected = {'TIMEBASE': 'counter', 'FLAT': 'power'}.get(p['kind'], 'std')           # which reference the output is cabled to
        c.run(f'fgen_verification.IO.measure[{pid(p)}]', io.measure, p, results, cache, _log=io.log)
    c.run('fgen_verification.IO.close', io.close, _log=io.log)
    return c.entries


def run_mdo():
    import mdo4000c_verification as M
    c = gc.Case('engine_mdo4000c')
    bench, t = make_mdo_bench()
    wrapped = {k: rec(v) for k, v in t.items()}
    r = Runner(c)
    io = r.build('mdo4000c_verification.IO.__init__', lambda: M.IO(dict(cal_baud=9600), transports=wrapped))
    cfg = M.Config('4104C', 'SA6', True, True, True, True)

    class FakeApp:
        stop = False

        def __init__(self):
            self.io, self.cfg = io, cfg

        def request(self, kind, payload=None):
            return payload['p']['nominal'] if kind == 'manual' else True

        def post(self, *a, **k):
            pass

    runner = M.Runner(FakeApp())
    skip_kinds = {'selftest'}                 # needs a power cycle dialog
    pts = [p for p in M.POINTS if cfg.applies(p) and p['kind'].lower() not in skip_kinds]
    for p in sample(pts, lambda p: p['kind'], 40):
        c.run(f'mdo4000c_verification.Runner.run_point[{pid(p)}]', runner.run_point, p, _log=io.log)
    c.run('mdo4000c_verification.IO.close', io.close, _log=io.log)
    return c.entries


def _patch_open_visa(transports):
    """drivers.open_visa returns the next simulated transport (the procedure modules call it with an address)."""
    queue_ = list(transports)
    saved = drivers.open_visa

    def fake(address, timeout=10.0, **kw):
        return rec(queue_.pop(0))
    drivers.open_visa = fake
    return saved


def run_agilent_34401a():
    import Agilent_34401A as A
    c = gc.Case('engine_agilent_34401a')
    bench, ft, dt = make_dmm_bench('34401A')
    saved = _patch_open_visa([dt, ft])
    try:
        r = Runner(c)
        io = r.build('Agilent_34401A.IO.__init__', lambda: A.IO('1', '2', 9600, 'None', 8))
    finally:
        drivers.open_visa = saved
    pts = sample(A.POINTS, lambda p: (p['kind'], bool(p.get('zero_offset')), bool(p.get('frequency'))), 14)
    _measure_all(c, io, pts, 'Agilent_34401A')
    c.run('Agilent_34401A.IO.close', io.close, _log=io.log)
    return c.entries


def run_fluke_8846a():
    import Fluke_8846A_Verification as V
    c = gc.Case('engine_fluke_8846a')
    bench, ft, dt = make_dmm_bench('8846A')
    saved = _patch_open_visa([dt, ft])
    try:
        r = Runner(c)
        io = r.build('Fluke_8846A_Verification.IO.__init__', lambda: V.IO('1', '2', 9600, 'None', 8))
    finally:
        drivers.open_visa = saved
    pts = sample(V.POINTS, lambda p: (p['kind'], bool(p.get('zero_offset')), bool(p.get('frequency'))), 14)
    _measure_all(c, io, pts, 'Fluke_8846A_Verification')
    c.run('Fluke_8846A_Verification.IO.close', io.close, _log=io.log)
    return c.entries


def run_handheld():
    import handheld_dmm as H
    c = gc.Case('engine_handheld_5522a')
    bench, ft, _s = make_bench()
    ft.model = '5522A'
    r = Runner(c)
    io = r.build('handheld_dmm.IO.__init__', lambda: H.IO('Fluke 5522A', 'sim', transport=rec(ft)))
    # steps of the 110-series spec (model 115 / 116 / 117 cover resistance, AC / DC volts, capacitance, currents, temperature)
    done = set()
    for model in ('115', '116', '117'):
        pts = [p for p in H.points_for(H.load_spec(), model) if p.get('applied')]
        for p in sample(pts, lambda p: (p['kind'], p.get('group'), bool(p['applied'].get('frequency'))), 14):
            key = (p['kind'], p.get('group'), p['applied']['value'], p['applied'].get('frequency'))
            if key in done:
                continue
            done.add(key)
            c.run(f'handheld_dmm.IO.apply[{model} {p["kind"]}#{p["n"]}]', io.apply, p, _log=io.log)
    # the 289 / 287 spec: a 120 V point with a ramp, and the IR read path through the Fluke 28x driver
    spec = H.load_spec('fluke_287_289_pv.json')
    p289 = H.points_for(spec, '289')
    for p in sample([p for p in p289 if p.get('applied') and p['kind'] in ('ACV', 'DCI', 'CAP', 'TEMP')], lambda p: (p['kind'], bool(p.get('ramp'))), 6):
        c.run(f'handheld_dmm.IO.apply[289 {p["kind"]}#{p["n"]}]', io.apply, p, _log=io.log)
    c.run('handheld_dmm.IO.close', io.close, _log=io.log)
    # IR reads
    bench2 = SimBench()
    sim = SimFluke28x(bench2, '289')
    meter = gc.Case.inst(c, drivers.Fluke28x, sim, label='Fluke289', opened=False)
    c.run('handheld_dmm.Fluke28x.connect', meter.connect)
    for p in sample([p for p in p289 if p.get('ir') and p.get('applied')], lambda p: (p['ir']['unit'], bool(p['ir'].get('rel'))), 5):
        want = p['ir']
        mult = want['range'][1] if want.get('range') else 0
        bench2.meter.update(primary=(want.get('functions') or ['V_DC'])[0], range_unit=want['unit'],
                            range=tuple(want['range']) if want.get('range') else (5, 0),
                            modes=['REL'] if want.get('rel') else [], readings=[('PRIMARY', want['unit'], mult, 3)],
                            value=(lambda v=p['applied']['value']: v))
        c.run(f'handheld_dmm.ir_read[{p["kind"]}#{p["n"]}]', H.ir_read, meter, p, _log=meter.log)
    return c.entries


def run_wavesurfer():
    import WaveSurfer_WS4104HD as W
    c = gc.Case('engine_wavesurfer_dcv')
    bench, ft, st = make_bench()
    transports = {'fluke': rec(ft), 'scope': rec(st)}

    class FakeApp:
        """Just enough of RMSNoiseApp for the DCV point methods (no Tk): the real open_bench is replaced exactly as its docstring says tests do."""
        def __repr__(self):
            return 'FakeApp'

        def __init__(self):
            self.events = queue.Queue()
            self.visa_address = types.SimpleNamespace(get=lambda: 'sim')

        def open_bench(self, fluke_addr, baud, scope_addr, log, scope_timeout=10):
            fluke = drivers.Fluke5560A(transports['fluke'], log) if fluke_addr else None
            scope = drivers.WaveSurfer4104HD(transports['scope'], log) if scope_addr else None
            return fluke, scope

        finish_bench = W.RMSNoiseApp.finish_bench
        save_command_log = W.RMSNoiseApp.save_command_log

    app = FakeApp()
    point = dict(channel=1, scale_v_div=0.5, nominal_v=1.0, lower_v=0.99, upper_v=1.01)
    log_holder = {}
    orig_cl = drivers.CommandLog

    class HoldLog(orig_cl):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            log_holder['log'] = self

    drivers.CommandLog = HoldLog
    try:
        c.run('WaveSurfer_WS4104HD.automatic_dcv_point', W.RMSNoiseApp.automatic_dcv_point, app, point, 2.0, 'sim', 9600, 'sim', _log=None)
        # the log object is created inside the call; re-run reading it afterwards is not possible, so record it from the holder
        c.entries[-1]['log'] = [f'{i}|{d}|{t}' for _ts, i, d, t in log_holder['log'].entries]
        c.entries[-1]['events'] = [list(map(_plain, app.events.get_nowait())) for _ in range(app.events.qsize())]
        log_holder.clear()
        c.run('WaveSurfer_WS4104HD.read_dcv_scope', W.RMSNoiseApp.read_dcv_scope, app, point, _log=None)
        c.entries[-1]['log'] = [f'{i}|{d}|{t}' for _ts, i, d, t in log_holder['log'].entries]
        c.entries[-1]['events'] = [list(map(_plain, app.events.get_nowait())) for _ in range(app.events.qsize())]
    finally:
        drivers.CommandLog = orig_cl
    return c.entries


def _plain(x):
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, float):
        return round(x, 9)
    return x if isinstance(x, (int, str, bool, type(None))) else repr(x)


RUNS = {
    'truevolt_34470A': run_truevolt,
    'dacq_34970A': lambda: run_dacq('34970A'),
    'dacq_34972A': lambda: run_dacq('34972A'),
    'fgen_33220A': run_fgen,
    'mdo4000c': run_mdo,
    'agilent_34401a': run_agilent_34401a,
    'fluke_8846a': run_fluke_8846a,
    'handheld_5522a': run_handheld,
    'wavesurfer_dcv': run_wavesurfer,
}
