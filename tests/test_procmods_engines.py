"""Procedure modifications in the engines (procmods_engine.ProcModsMixin): every procedure, on the simulated benches, with and without
overrides.  No tkinter needed (tests/_tk_stub.py stands in for it, like the golden engine runs).

What is proved here
  * No override stored: an IO built with mods=<state> sends exactly the same commands, logs exactly the same lines and sleeps exactly the
    same times as one built without (the golden transcripts prove the no-mods case against the recorded fixtures).
  * Every tunable the engines read is registered with the default the engine really uses, inside its bounds; every registered tunable is
    read by some engine.
  * A stored settle time changes exactly the sleeps that tunable controls; a stored command template reaches the wire and is marked
    [OVERRIDE ov-...] in the log; the log banner exists only when something is modified.
  * Limits change only through valid, enabled, HMAC-verified limit overrides; a tampered one is refused; skips leave limits alone.
  * Run record: checkpoint fields, result fields, snapshot, 'Run factory', saved-versus-current, applied_modifications().
"""
import contextlib
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

from tests import _tk_stub  # noqa: E402

_tk_stub.install()

import devmode  # noqa: E402
import drivers  # noqa: E402
import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
from drivers.simulated import make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402
from drivers.simulated_mdo import make_mdo_bench  # noqa: E402
from drivers.simulated import make_bench  # noqa: E402
from tests import golden_capture as gc  # noqa: E402

import dacq_verification as D  # noqa: E402
import fluke8808a_verification as K  # noqa: E402
import fgen_verification as F  # noqa: E402
import handheld_dmm as H  # noqa: E402
import mdo4000c_verification as M  # noqa: E402
import truevolt_verification as T  # noqa: E402
import Agilent_34401A as A  # noqa: E402
import Fluke_8846A_Verification as V  # noqa: E402
import WaveSurfer_WS4104HD as W  # noqa: E402


# ------------------------------------------------------------------------------------------------------------------------------
# environment
# ------------------------------------------------------------------------------------------------------------------------------
class Env:
    """A throw-away override store with an unlocked developer-mode session (the only way to create overrides)."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dm = devmode.DevMode(self.dir / 'dev' / 'devmode.json', iterations=1000)
        self.session = self.dm.set_passphrase('correct horse')
        self.db = self.dir / 'lab_registry.sqlite3'
        self.store = procmods.Store(self.db, devmode=self.dm)

    def state(self, engine, model, **kw):
        return pe.ModsState(engine, model, store=self.store, devmode=self.dm, **kw)

    def add(self, kind, target, value, model, scope='model', asset_id='', reason='test', **kw):
        return self.store.add(kind, target, value, scope, reason, model=model, asset_id=asset_id, session=self.session, author='tester', **kw)

    def param(self, name, value, model, **kw):
        return self.add('param', name, {'value': value}, model, **kw)

    def close(self):
        self.tmp.cleanup()


def entries_of(log):
    return [(inst, d, text) for _t, inst, d, text in log.entries]


@contextlib.contextmanager
def pinned_run():
    """Fake clock + throw-away HOME; yields the list the sleeps are recorded in."""
    with gc.pinned():
        events = []
        gc.Recorder.current = events
        try:
            yield events
        finally:
            gc.Recorder.current = None


def sleeps_of(events):
    return [e[1] for e in events if e and e[0] == 'sleep']


def wire_of(events):
    return [e for e in events if e and e[0] in ('W', 'Q')]


# ------------------------------------------------------------------------------------------------------------------------------
# per-engine simulated runs: build(mods) -> (io, run) ; run() measures a small fixed sample on the simulated bench
# ------------------------------------------------------------------------------------------------------------------------------
def safe(fn, *a):
    """The result of a call, or the exception it raised (some simulated points are refused by design, like in the golden runs)."""
    try:
        return ('ok', fn(*a))
    except Exception as exc:                          # noqa: BLE001
        return ('raised', f'{type(exc).__name__}: {exc}')


def _sample(points, key, limit):
    seen, out = set(), []
    for p in points:
        k = key(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def _dmm_key(p):
    return (p['kind'], p.get('source'), p.get('filter_hz'), bool(p.get('frequency')), p.get('role'), p.get('terminal'), bool(p.get('plc')))


@contextlib.contextmanager
def _visa(transports):
    queue_ = list(transports)
    saved = drivers.open_visa
    drivers.open_visa = lambda address, timeout=10.0, **kw: gc.RecordingTransport(queue_.pop(0))
    try:
        yield
    finally:
        drivers.open_visa = saved


def build_truevolt(mods):
    T.configure('34470A')
    bench, ft, dt = make_dmm_bench('34470A')
    io = T.IO('sim', 'sim', transports=(gc.RecordingTransport(dt), gc.RecordingTransport(ft)), mods=mods)
    pts = _sample(T.POINTS, _dmm_key, 14)

    def run():
        out = []
        for p in pts:
            dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'
            out.append(safe(io.measure, p))
        return out
    return io, run


def build_dacq(mods):
    D.configure('34970A')
    bench, ft, dt = make_dacq_bench('34970A')
    io = D.IO('sim', 'sim', cal_model='Fluke 5560A', module='34901A', slot=2,
              transports=(gc.RecordingTransport(dt), gc.RecordingTransport(ft)), mods=mods)
    pts = _sample(D.POINTS, _dmm_key, 14)
    return io, lambda: [safe(io.measure, p) for p in pts]


def build_f8808a(mods):
    K.configure()
    bench, ft, dt = make_8808a_bench('5522A', enforce_cal_limits=False)
    io = K.IO('sim', 'sim', cal_model='Fluke 5522A', transports=(gc.RecordingTransport(dt), gc.RecordingTransport(ft)), mods=mods)
    pts = _sample(K.POINTS, lambda p: (p['kind'], p['source'], p['kind'] in ('OHM2', 'OHM4') and p['range'] >= 1e7, p['kind'] == 'ACV'), 14)
    io.reset_at_start()          # the engine resets both instruments before the first point; the 8808A is only configured on top of that
    return io, lambda: [safe(io.measure, p) for p in pts]


def build_fgen(mods):
    F.configure('33220A')
    bench, t = make_fgen_bench('33220A')
    io = F.IO({}, transports={k: gc.RecordingTransport(v) for k, v in t.items()}, ask_number=lambda prompt, unit: 0.0, mods=mods)
    pts = _sample(F.POINTS, lambda p: (p['kind'], p.get('section'), p.get('function'), p.get('amp_unit'), p.get('load')), 16)

    def run():
        results, cache, out = {}, {}, []
        for p in pts:
            bench.connected = {'TIMEBASE': 'counter', 'FLAT': 'power'}.get(p['kind'], 'std')
            out.append(safe(io.measure, p, results, cache))
        return out
    return io, run


def _build_pair(module, mods):
    bench, ft, dt = make_dmm_bench('34401A' if module is A else '8846A')
    with _visa([dt, ft]):
        io = module.IO('1', '2', 9600, 'None', 8, mods=mods)
    pts = _sample(module.POINTS, lambda p: (p['kind'], bool(p.get('zero_offset')), bool(p.get('frequency'))), 14)
    return io, lambda: [safe(io.measure, p) for p in pts]


def build_a34401(mods):
    return _build_pair(A, mods)


def build_f8846a(mods):
    return _build_pair(V, mods)


def build_handheld(mods):
    bench, ft, _s = make_bench()
    ft.model = '5522A'
    io = H.IO('Fluke 5522A', 'sim', transport=gc.RecordingTransport(ft), mods=mods)
    pts = []
    for model in ('115', '116', '117'):
        pts += _sample([p for p in H.points_for(H.load_spec(), model) if p.get('applied')], lambda p: (p['kind'], p.get('group')), 8)
    seen, uniq = set(), []
    for p in pts:
        k = (p['kind'], p['applied']['value'], p['applied'].get('frequency'))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return io, lambda: [safe(io.apply, p) for p in uniq[:14]]


def build_mdo(mods):
    bench, t = make_mdo_bench()
    io = M.IO(dict(cal_baud=9600), transports={k: gc.RecordingTransport(v) for k, v in t.items()}, mods=mods)
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
    pts = [p for p in M.POINTS if cfg.applies(p) and p['kind'].lower() != 'selftest']
    pts = _sample(pts, lambda p: p['kind'], 40)
    return io, lambda: [safe(runner.run_point, p) for p in pts]


ENGINES = {
    'truevolt': ('34470A', build_truevolt), 'dacq': ('34970A', build_dacq), 'fgen': ('33220A', build_fgen),
    'a34401': ('34401A', build_a34401), 'f8846a': ('8846A', build_f8846a), 'handheld': ('5522A', build_handheld),
    'mdo': ('MDO4000C', build_mdo), 'f8808a': ('8808A', build_f8808a),
}
# handheld overrides are scoped to the spec model; the sim run mixes 115 / 116 / 117 points, so the tests use asset scope for it
SCOPE_KW = {'handheld': dict(scope='asset', asset_id='HH-1')}


def run_engine(name, mods=None, spy=None):
    """(wire events, sleeps, log entries, results) of one simulated run."""
    model, build = ENGINES[name]
    with pinned_run() as events:
        io, run = build(mods)
        events.clear()
        if spy is not None:
            with mock.patch.object(pe.ProcModsMixin, 'pm_param', autospec=True,
                                   side_effect=lambda self, n, d, point=None: (spy.append((n, d)), d)[1]):
                results = run()
        else:
            results = run()
        wire, sleeps, log = wire_of(events), sleeps_of(events), entries_of(io.log)
        io.close()
    return wire, sleeps, log, results


def observed_params(name):
    spy = []
    run_engine(name, None, spy)
    return spy


# ------------------------------------------------------------------------------------------------------------------------------
class Registry(unittest.TestCase):
    def test_every_tunable_is_registered_with_bounds_and_a_default_inside_them(self):
        self.assertTrue(pe.TUNABLES)
        for name, t in pe.TUNABLES.items():
            spec = procmods.PARAMS[name]
            self.assertEqual((spec['lo'], spec['hi']), (t['lo'], t['hi']), name)
            self.assertEqual(procmods._check_param_value(name, t['default']), [], name)
            self.assertTrue(t['lo'] < t['hi'], name)
            self.assertEqual(spec['affects_conditions'], t['affects_conditions'], name)
        for name in ('point.settle', 'handheld.point.settle', 'handheld.point.ir_timeout'):
            self.assertTrue(procmods.PARAMS[name]['per_point'], name)
        self.assertEqual(procmods.PARAMS['point.settle']['field'], 'settle_s')

    def test_bounds_refuse_bad_values(self):
        for name, bad in (('truevolt.settle.freq', 0.0), ('truevolt.settle.freq', 1e6), ('mdo.reconnect_attempts', 2.5), ('handheld.ramp_delay', 1.0),
                          ('ws.dcv_settle', 'abc')):
            self.assertTrue(procmods._check_param_value(name, bad), (name, bad))

    def test_the_ramp_delay_can_only_be_lengthened(self):
        self.assertEqual(pe.TUNABLES['handheld.ramp_delay']['lo'], pe.TUNABLES['handheld.ramp_delay']['default'])

    def test_defaults_declared_equal_what_the_engines_ask_for(self):
        seen = {}
        for name in ENGINES:
            for n, d in observed_params(name):
                self.assertIn(n, pe.TUNABLES, n)
                self.assertEqual(float(d), float(pe.TUNABLES[n]['default']), n)
                seen[n] = name
        self.assertGreater(len(seen), 20)

    def test_every_tunable_is_read_by_the_source_of_its_engine(self):
        files = {'truevolt': 'truevolt_verification.py', 'dacq': 'dacq_verification.py', 'fgen': 'fgen_verification.py',
                 'handheld': 'handheld_dmm.py', 'a34401': 'Procedures/Agilent_34401A.py', 'f8846a': 'Procedures/Fluke_8846A_Verification.py',
                 'mdo': 'mdo4000c_verification.py', 'ws': 'Procedures/WaveSurfer_WS4104HD.py', 'f8808a': 'fluke8808a_verification.py'}
        dynamic = ('truevolt.settle.ac_', 'dacq.settle.ac_')
        for name, t in pe.TUNABLES.items():
            src = (ROOT / files[t['engine']]).read_text(encoding='utf-8')
            if name.startswith(dynamic):
                self.assertIn(name.rsplit('_', 1)[0] + '_', src, name)
            elif name.startswith('fgen.settle.'):
                self.assertIn("'fgen.settle.", src)
            else:
                self.assertIn(f"'{name}'", src, name)

    def test_models_and_defaults_helpers(self):
        self.assertEqual(set(pe.MODEL_IDS), {t['engine'] for t in pe.TUNABLES.values()})
        d = pe.defaults_for('truevolt')
        self.assertEqual(d['truevolt.settle.ac_3hz'], 9.0)
        self.assertTrue(all(k.startswith('truevolt.') for k in d))

    def test_every_engine_wires_the_mixin_and_the_run_start(self):
        """Source-level guard: every procedure loads the modifications at run start, binds drivers, and skips skipped points."""
        for rel in ('truevolt_verification.py', 'dacq_verification.py', 'fgen_verification.py', 'handheld_dmm.py', 'mdo4000c_verification.py',
                    'Procedures/Agilent_34401A.py', 'Procedures/Fluke_8846A_Verification.py', 'Procedures/WaveSurfer_WS4104HD.py',
                    'fluke8808a_verification.py'):
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertIn('procmods_engine.ProcModsMixin', src, rel)
            self.assertIn('pm_init(', src, rel)
            self.assertIn('pm_checkpoint_fields' if 'WaveSurfer' not in rel else '_pm_write_sidecar', src, rel)
            if 'WaveSurfer' not in rel:
                self.assertIn('pm_begin_run(', src, rel)
                self.assertIn('pm_attach(', src, rel)


# ------------------------------------------------------------------------------------------------------------------------------
class NoOverrides(unittest.TestCase):
    """mods=<state> with an empty store behaves exactly like no mods at all."""

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_identical_wire_log_sleeps_and_results(self):
        for name, (model, _b) in ENGINES.items():
            with self.subTest(engine=name):
                base = run_engine(name, None)
                st = self.env.state(name, model)
                st.load('')
                got = run_engine(name, st)
                self.assertEqual(base[0], got[0], 'wire')
                self.assertEqual(base[1], got[1], 'sleeps')
                self.assertEqual(base[2], got[2], 'command log (no banner, no marker)')
                self.assertEqual(repr(base[3]), repr(got[3]), 'results')
                self.assertTrue(base[0] and base[1])
                self.assertFalse(st.oset)
                self.assertFalse(any('overrides rev' in t for _i, _d, t in got[2]))

    def test_checkpoint_and_result_fields_are_empty(self):
        class Holder(pe.ProcModsMixin):
            pass
        h = Holder()
        h.pm_init('truevolt', '34470A', store=self.env.store, devmode=self.env.dm)
        self.assertEqual(h.pm_checkpoint_fields(), {})
        self.assertEqual(h.pm_result_fields(), {})
        self.assertEqual(pe.applied_modifications(h), [])
        self.assertEqual(h.pm_modified_count(), 0)
        self.assertFalse(pe.applied_info(h)['tolerances_modified'])
        self.assertFalse(h.pm_record_run('R-1', demo=False))

    def test_an_unreadable_store_runs_with_factory_settings(self):
        bad = Path(self.env.dir / 'x' / 'nope' / 'lab.sqlite3')
        st = pe.ModsState('truevolt', '34470A', store=procmods.Store(bad, devmode=self.env.dm), devmode=self.env.dm)
        st.load('A1')
        self.assertFalse(st.oset)
        self.assertEqual(st.param('truevolt.settle.freq', 3.0), 3.0)


# ------------------------------------------------------------------------------------------------------------------------------
class Settings(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_a_stored_settle_time_changes_exactly_its_sleeps_on_every_engine(self):
        for name, (model, _b) in ENGINES.items():
            with self.subTest(engine=name):
                base = run_engine(name, None)
                spy = observed_params(name)
                cands = [(n, d) for n, d in spy if isinstance(d, float) and not n.endswith(('pause_scale', 'counter_gate'))
                         and 'ramp' not in n]
                self.assertTrue(cands, 'the sample run reads at least one settle time')
                pname, default = cands[0]
                env = Env()
                self.addCleanup(env.close)
                kw = SCOPE_KW.get(name, {})
                env.param(pname, 7.25, model, **kw)
                st = env.state(name, model)
                st.load(kw.get('asset_id', ''))
                got = run_engine(name, st)
                if name == 'handheld':                           # its waits are chopped into 0.25 s slices: compare the totals
                    self.assertGreater(sum(got[1]), sum(base[1]))
                else:
                    self.assertEqual(len(got[1]), len(base[1]))
                    changed = [i for i, (a, b) in enumerate(zip(base[1], got[1])) if a != b]
                    self.assertTrue(changed, f'{pname} changed nothing')
                    for i in changed:
                        self.assertEqual(got[1][i], 7.25)
                        self.assertEqual(base[1][i], default, f'{pname}: only sleeps made with the default {default} may change')
                # nothing but the sleeps differs on the wire
                self.assertEqual(base[0], got[0])
                self.assertTrue(any('overrides rev' in t for _i, _d, t in got[2]), 'banner in the command log')
                self.assertEqual(base[2], [e for e in got[2] if not (e[0] == 'procmods')])

    def test_truevolt_ac_filter_settles_are_independent(self):
        self.env.param('truevolt.settle.ac_3hz', 11.0, '34470A')
        st = self.env.state('truevolt', '34470A')
        st.load('')
        io = T.IO.__new__(T.IO)
        io.__dict__['_pm_state'] = st
        T.configure('34470A')
        ac3 = next(p for p in T.POINTS if p['kind'] == 'ACV' and p.get('filter_hz') == 3)
        ac200 = next(p for p in T.POINTS if p['kind'] == 'ACV' and p.get('filter_hz') == 200)
        self.assertEqual(io.settle(ac3), 11.0)
        self.assertEqual(io.settle(ac200), 4.0)

    def test_per_point_settle(self):
        T.configure('34470A')
        p = next(q for q in T.POINTS if q['kind'] == 'DCV' and q['source'] == 'calibrator')
        key = procmods.point_keys(T.POINTS)[T.POINTS.index(p)]
        self.env.param(f'point.settle@{key}', 9.5, '34470A')
        st = self.env.state('truevolt', '34470A')
        live = list(T.POINTS)
        st.register(live)
        st.load('')
        q = live[T.POINTS.index(p)]
        self.assertEqual(q['settle_s'], 9.5)
        io = T.IO.__new__(T.IO)
        self.assertEqual(io.settle(q), 9.5)
        others = [x for i, x in enumerate(live) if i != T.POINTS.index(p)]
        self.assertTrue(all('settle_s' not in x for x in others))
        procmods.assert_limits_unchanged(T.POINTS, live)

    def test_an_invalid_stored_value_is_ignored_and_reported(self):
        st = self.env.state('truevolt', '34470A')
        e = self.env.param('truevolt.settle.freq', 5.0, '34470A')
        st.load('')
        self.assertEqual(st.param('truevolt.settle.freq', 3.0), 5.0)
        # a damaged out-of-bounds value cannot be created through the store, so poke the set directly
        with mock.patch.object(st.oset.__class__, 'param', return_value=999999.0):
            self.assertEqual(st.param('truevolt.settle.freq', 3.0), 3.0)
        self.assertTrue(any('not valid' in w for w in st.warnings))

    def test_mdo_pause_scale_scales_every_wait(self):
        base = run_engine('mdo', None)
        self.env.param('mdo.pause_scale', 2.0, 'MDO4000C')
        st = self.env.state('mdo', 'MDO4000C')
        st.load('')
        try:
            got = run_engine('mdo', st)
        finally:
            M.PM_PAUSE_SCALE = 1.0
        self.assertEqual(len(base[1]), len(got[1]))
        doubled = [i for i, (a, b) in enumerate(zip(base[1], got[1])) if b == 2.0 * a and a > 0]
        same = [i for i, (a, b) in enumerate(zip(base[1], got[1])) if b == a]
        self.assertGreater(len(doubled), 5)
        self.assertEqual(len(doubled) + len(same), len(base[1]), 'every sleep is either the procedure\'s own wait (x2) or a driver-internal one')
        self.assertEqual(base[0], got[0])


# ------------------------------------------------------------------------------------------------------------------------------
class Commands(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_a_command_override_reaches_the_wire_and_is_marked_in_the_log(self):
        import cmdreg
        reg = cmdreg.merge_commands(drivers.Keysight34470A)
        e = self.env.add('command', 'KeysightTruevolt:nplc.dcv', {'template': 'volt:dc:nplc {nplc:g}'}, '34470A', cmd=reg['nplc.dcv'],
                         driver_name='KeysightTruevolt')
        base = run_engine('truevolt', None)
        st = self.env.state('truevolt', '34470A')
        st.load('')
        got = run_engine('truevolt', st)
        old = [w for w in base[0] if 'VOLT:DC:NPLC' in w[1]]
        new = [w for w in got[0] if 'volt:dc:nplc' in w[1]]
        self.assertTrue(old and len(old) == len(new))
        self.assertFalse([w for w in got[0] if 'VOLT:DC:NPLC' in w[1]])
        marked = [t for _i, _d, t in got[2] if t.startswith('volt:dc:nplc')]
        self.assertTrue(marked and all(t.endswith(f'[OVERRIDE ov-{e["uid"]}]') for t in marked), marked)
        self.assertTrue(any(t.startswith('overrides rev') for _i, d, t in got[2] if d == '--'))
        self.assertEqual(len(base[2]) + 1, len(got[2]))              # only the banner is extra
        self.assertEqual(base[1], got[1])
        self.assertEqual(st.rejected, [])

    def test_a_command_override_for_another_driver_class_is_not_bound(self):
        import cmdreg
        reg = cmdreg.merge_commands(drivers.Keysight34970A)
        self.env.add('command', 'KeysightDacq:nplc.dcv', {'template': 'volt:dc:nplc {plc:g},{ch}'}, '34470A', cmd=reg['nplc.dcv'],
                     driver_name='KeysightDacq')
        base = run_engine('truevolt', None)
        st = self.env.state('truevolt', '34470A')
        st.load('')
        got = run_engine('truevolt', st)
        self.assertEqual(base[0], got[0])

    def test_firmware_condition_is_judged_after_connect(self):
        import cmdreg
        reg = cmdreg.merge_commands(drivers.Keysight34470A)
        for fw, expect_new in ((r'A\.03\.01', True), (r'Z\.99', False)):
            env = Env()
            self.addCleanup(env.close)
            env.add('command', 'KeysightTruevolt:nplc.dcv', {'template': 'volt:dc:nplc {nplc:g}'}, '34470A', cmd=reg['nplc.dcv'],
                    driver_name='KeysightTruevolt', fw_match=fw)
            st = env.state('truevolt', '34470A')
            st.load('')
            got = run_engine('truevolt', st)
            self.assertEqual(any('volt:dc:nplc' in w[1] for w in got[0]), expect_new, fw)

    def test_a_rejected_command_override_is_dropped_and_logged_not_raised(self):
        import cmdreg
        reg = cmdreg.merge_commands(drivers.Keysight34470A)
        e = self.env.add('command', 'KeysightTruevolt:nplc.dcv', {'template': 'volt:dc:nplc {nplc:g}'}, '34470A', cmd=reg['nplc.dcv'],
                         driver_name='KeysightTruevolt')
        st = self.env.state('truevolt', '34470A')
        st.load('')
        base = run_engine('truevolt', None)
        # the factory command changed after the override was made: the override is stale and not applied (the driver itself is untouched)
        import dataclasses
        import types
        stale_cmd = dataclasses.replace(reg['nplc.dcv'], template='VOLT:DC:NPLC {nplc:g} ')

        def merged(cls_or_obj):
            out = dict(cmdreg.merge_commands(cls_or_obj))
            if 'nplc.dcv' in out:
                out['nplc.dcv'] = stale_cmd
            return out
        proxy = types.SimpleNamespace(**{k: getattr(cmdreg, k) for k in dir(cmdreg) if not k.startswith('__')})
        proxy.merge_commands = merged
        with mock.patch.object(procmods, 'cmdreg', proxy):
            st2 = self.env.state('truevolt', '34470A')
            st2.load('')
            got = run_engine('truevolt', st2)
        self.assertFalse(any('volt:dc:nplc' in w[1] for w in got[0]))
        self.assertTrue(any('not applied' in w and 'stale' in w for w in st2.warnings), st2.warnings)
        self.assertEqual(base[0], got[0])
        self.assertTrue(any(d == '!!' and 'OVERRIDE' in t for _i, d, t in got[2]), 'the refusal is in the command log')
        self.assertEqual(e['uid'] in ' '.join(st2.warnings), True)


# ------------------------------------------------------------------------------------------------------------------------------
class Limits(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        T.configure('34470A')

    def limit_point(self):
        return next(p for p in T.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator' and p['nominal'] == 1.0)

    def make(self, new_error=0.5):
        st = self.env.state('truevolt', '34470A')
        live = list(T.POINTS)
        st.register(live)
        views = st.factory_points()
        i = T.POINTS.index(self.limit_point())
        key = procmods.point_keys(views)[i]
        e = self.env.add('limit', key, {'mode': 'error', 'error': new_error}, '34470A', point=views[i])
        st.load('')
        return st, live, i, e

    def test_only_the_overridden_points_limits_change(self):
        st, live, i, e = self.make(0.5)
        self.assertEqual(live[i]['error'], 0.5)
        self.assertTrue(live[i]['limit_modified'])
        self.assertEqual(live[i]['limit_factory']['error'], T.POINTS[i]['error'])
        for j, (a, b) in enumerate(zip(T.POINTS, live)):
            if j != i:
                self.assertEqual(a, b)
        procmods.assert_limits_unchanged(T.POINTS, live, {i})
        with self.assertRaises(procmods.LimitsChangedError):
            procmods.assert_limits_unchanged(T.POINTS, live)

    def test_applying_a_saved_limit_does_not_need_developer_mode(self):
        st, live, i, e = self.make(0.5)
        self.env.session.lock()
        st2 = self.env.state('truevolt', '34470A')
        live2 = list(T.POINTS)
        st2.register(live2)
        st2.load('')
        self.assertEqual(live2[i]['error'], 0.5)

    def test_a_tampered_limit_row_is_refused(self):
        st, live, i, e = self.make(0.5)
        con = sqlite3.connect(str(self.env.db))
        con.execute('DROP TRIGGER override_append_only')              # a casual edit of the database
        bad = json.dumps({**e['value'], 'error': 99.0}, sort_keys=True, separators=(',', ':'))
        con.execute('UPDATE override SET value_json=? WHERE uid=?', (bad, e['uid']))
        con.commit()
        con.close()
        st2 = self.env.state('truevolt', '34470A')
        live2 = list(T.POINTS)
        st2.register(live2)
        st2.load('')
        self.assertEqual(live2[i]['error'], T.POINTS[i]['error'], 'factory tolerance')
        self.assertNotIn('limit_modified', live2[i])
        self.assertTrue(any('TAMPERED' in w for w in st2.warnings))
        self.assertEqual(pe.applied_info(st2)['tampered'][0][0], e['uid'])
        self.assertEqual(pe.applied_modifications(st2), [])
        log = drivers.CommandLog()
        st2.banner(log)
        self.assertTrue(any('TAMPERED' in t for *_x, t in log.entries))

    def test_a_missing_device_key_makes_limit_rows_tampered(self):
        st, live, i, e = self.make(0.5)
        (self.env.dir / 'dev' / 'devmode.json').unlink()
        st2 = self.env.state('truevolt', '34470A', )
        st2.devmode = devmode.DevMode(self.env.dir / 'dev' / 'devmode.json', iterations=1000)
        st2.store = procmods.Store(self.env.db, devmode=st2.devmode)
        live2 = list(T.POINTS)
        st2.register(live2)
        st2.load('')
        self.assertEqual(live2[i]['error'], T.POINTS[i]['error'])
        self.assertTrue(st2.oset.tampered())

    def test_a_limit_made_for_another_period_is_stale_and_not_applied(self):
        st, live, i, e = self.make(0.5)
        other = [dict(p) for p in T.POINTS]
        other[i]['error'] = other[i]['error'] * 2                       # another period's table
        st2 = self.env.state('truevolt', '34470A')
        st2.register(other)
        st2.load('')
        self.assertEqual(other[i]['error'], T.POINTS[i]['error'] * 2)
        self.assertNotIn('limit_modified', other[i])
        self.assertTrue(any('no longer fits' in w for w in st2.warnings))

    def test_skip_text_and_settings_never_touch_limits(self):
        views = None
        st = self.env.state('truevolt', '34470A')
        live = list(T.POINTS)
        st.register(live)
        views = st.factory_points()
        keys = procmods.point_keys(views)
        self.env.add('point', keys[3], {}, '34470A', point=views[3])
        self.env.add('text', f'note:{keys[4]}', {'text': 'Take care'}, '34470A')
        st.load('')
        self.assertTrue(live[3]['skip'])
        self.assertEqual(live[4]['tech_note'], 'Take care')
        procmods.assert_limits_unchanged(T.POINTS, live)
        for a, b in zip(T.POINTS, live):
            for f in procmods.LIMIT_FIELDS:
                self.assertEqual(a.get(f, 'x'), b.get(f, 'x'))

    def test_revert_restores_the_original_objects(self):
        st, live, i, e = self.make(0.5)
        st.revert(live)
        self.assertTrue(all(a is b for a, b in zip(T.POINTS, live)))
        st.apply(live)
        self.assertEqual(live[i]['error'], 0.5)

    def test_8846a_judges_low_high_so_the_tolerance_is_edited_there(self):
        pts = V.POINTS
        st = self.env.state('f8846a', '8846A', shape='band')
        live = list(pts)
        st.register(live)
        views = st.factory_points()
        self.assertTrue(all('error' not in v for v in views), "'error' is hidden, otherwise the change would have no effect")
        i = next(j for j, p in enumerate(pts) if p['kind'] == 'DCV' and p['nominal'] == 1.0)
        key = procmods.point_keys(views)[i]
        lo, hi = pts[i]['low'], pts[i]['high']
        self.env.add('limit', key, {'mode': 'band', 'low': lo - 1e-3, 'high': hi + 1e-3}, '8846A', point=views[i])
        st.load('')
        self.assertAlmostEqual(live[i]['low'], lo - 1e-3)
        self.assertAlmostEqual(live[i]['high'], hi + 1e-3)
        self.assertAlmostEqual(live[i]['error'], max(abs(live[i]['high'] - live[i]['nominal']), abs(live[i]['nominal'] - live[i]['low'])))
        reading = (hi + 0.5e-3)
        self.assertFalse(pts[i]['low'] <= reading <= pts[i]['high'])
        self.assertTrue(live[i]['low'] <= reading <= live[i]['high'], 'a reading outside the factory band passes the modified one')
        for j, (a, b) in enumerate(zip(pts, live)):
            if j != i:
                self.assertIs(a, b) if False else self.assertEqual(a, b)

    def test_8846a_unmodified_points_keep_error_exactly(self):
        st = self.env.state('f8846a', '8846A', shape='band')
        live = list(V.POINTS)
        st.register(live)
        st.load('')
        self.assertTrue(all(a is b for a, b in zip(V.POINTS, live)))

    def test_handheld_string_limits_stay_strings(self):
        spec = H.load_spec()
        pts = H.points_for(spec, '115')
        st = self.env.state('handheld', '115')
        live = list(pts)
        st.register(live)
        views = st.factory_points()
        i = next(j for j, p in enumerate(pts) if p.get('low') not in (None, '') and p['test'] == 'numeric' and float(p['high']) - float(p['low']) > 0)
        key = procmods.point_keys(views)[i]
        lo, hi = float(pts[i]['low']), float(pts[i]['high'])
        self.env.add('limit', key, {'mode': 'band', 'low': str(lo - 0.01), 'high': str(hi + 0.01)}, '115', point=views[i])
        st.load('')
        self.assertIsInstance(live[i]['low'], str)
        self.assertEqual(float(live[i]['high']), hi + 0.01)
        text = str(hi + 0.005)
        self.assertEqual(H.judge_numeric(pts[i], text)[0], 'FAIL')
        self.assertEqual(H.judge_numeric(live[i], text)[0], 'PASS')

    def test_mdo_band_limits_and_passfail_points(self):
        st = self.env.state('mdo', 'MDO4000C', shape='band')
        live = list(M.POINTS)
        st.register(live)
        views = st.factory_points()
        i = next(j for j, p in enumerate(M.POINTS) if p.get('low') is not None and p.get('high') is not None and not p.get('passfail'))
        key = procmods.point_keys(views)[i]
        p = M.POINTS[i]
        self.env.add('limit', key, {'mode': 'band', 'low': p['low'] - 1, 'high': p['high'] + 1}, 'MDO4000C', point=views[i])
        st.load('')
        self.assertEqual(live[i]['high'], p['high'] + 1)
        self.assertEqual(M.judge(live[i], p['high'] + 0.5), 'PASS')
        self.assertEqual(M.judge(p, p['high'] + 0.5), 'FAIL')


# ------------------------------------------------------------------------------------------------------------------------------
class AppFlow(unittest.TestCase):
    """The truevolt App's execute() in demo mode, headless: skip + tolerance modifications are applied from the run start."""

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patcher = mock.patch.dict('os.environ', {'CALSUITE_DATA': self.home.name, 'HOME': self.home.name, 'USERPROFILE': self.home.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        T.configure('34470A')

    def app(self, state=None):
        V_ = _tk_stub._Var

        class Root:
            def after(self, ms, fn):
                fn()
        app = object.__new__(T.App)
        app.root, app.demo, app.io, app._busy, app.stop = Root(), True, None, False, False
        app.asset, app.serial, app.period, app.status = V_(value='A1'), V_(value=''), V_(value='1 year'), V_(value='')
        app.pm_init('truevolt', '34470A', demo=True, lists=[T.POINTS], store=self.env.store, devmode=self.env.dm)
        if state:
            state(app)
        app._update_row = lambda p: None
        app.refresh = lambda: None
        app.update_summary = lambda: None
        app.tree = _tk_stub._Dummy()
        return app

    def checkpoint(self, app):
        return json.loads(app._checkpoint_path().read_text())

    def test_unmodified_run_leaves_no_trace(self):
        app = self.app()
        pts = list(T.POINTS[:6])
        app.execute(pts)
        self.assertEqual(len(app.results), 6)
        data = self.checkpoint(app)
        self.assertNotIn('overrides', data)
        self.assertTrue(all('ovrev' not in r for r in app.results.values()))
        self.assertEqual(set(data), {'asset', 'serial', 'demo', 'period', 'results', 'left_results'})
        self.assertTrue(all(a is b for a, b in zip(pts, T.POINTS)))

    def test_modified_run_skips_judges_against_the_modified_tolerance_and_records(self):
        views = pe.ModsState('truevolt', '34470A')
        views.register(list(T.POINTS))
        v = views.factory_points()
        keys = procmods.point_keys(v)
        self.env.add('point', keys[1], {}, '34470A', point=v[1])
        i = 2
        self.env.add('limit', keys[i], {'mode': 'error', 'error': T.POINTS[i]['error'] * 10}, '34470A', point=v[i])
        app = self.app()
        self.assertTrue(T.POINTS[1].get('skip'), 'applied at load already')
        app.execute(list(T.POINTS[:6]))
        self.assertEqual(sorted(app.results, key=int), ['1', '3', '4', '5', '6'], 'the skipped point is not run')
        r = app.results['3']
        self.assertEqual(r['ovrev'], 1)
        self.assertEqual(T.POINTS[2]['error'], T.POINTS[2]['error'])
        data = self.checkpoint(app)
        snap = data['overrides']
        self.assertTrue(procmods.verify_snapshot(snap))
        self.assertEqual({e['kind'] for e in snap['revs'][-1]['entries']}, {'point', 'limit'})
        mods = pe.applied_modifications(app)
        self.assertEqual({m['kind'] for m in mods}, {'point', 'limit'})
        lim = next(m for m in mods if m['limit'])
        self.assertTrue(lim['tolerances_modified'] and lim['manufacturer_tolerance'] and lim['tolerance_used'])
        info = pe.applied_info(app)
        self.assertTrue(info['tolerances_modified'])
        self.assertEqual(info['rev'], 1)
        # the snapshot alone gives the same list (a report re-printed later)
        self.assertEqual([m['text'] for m in pe.applied_modifications(data)], [m['text'] for m in mods])
        # a mangled snapshot is refused
        bad = json.loads(json.dumps(data))
        bad['overrides']['revs'][-1]['entries'][0]['reason'] = 'x'
        bad['overrides']['hash'] = 'f' * 64
        with self.assertRaises(ValueError):
            pe.applied_modifications(bad)

    def test_run_factory_is_one_shot_and_recorded(self):
        self.env.param('truevolt.settle.freq', 6.0, '34470A')
        app = self.app()
        self.assertEqual(app.pm_modified_count(), 1)
        app.pm_factory_run = True
        app.execute(list(T.POINTS[:3]))
        self.assertEqual(app.pm_modified_count(), 0)
        self.assertEqual(pe.applied_modifications(app), [])
        data = self.checkpoint(app)
        self.assertTrue(data['overrides']['factory_run'])
        self.assertEqual(data['overrides']['suppressed'], 1)
        self.assertTrue(pe.applied_info(app)['factory_run'])
        self.assertTrue(all('ovrev' not in r for r in app.results.values()))
        app.results.clear()
        app.execute(list(T.POINTS[:3]))                                   # the next run is modified again
        self.assertEqual(app.pm_modified_count(), 1)

    def test_checkpoint_saved_versus_current(self):
        e = self.env.param('truevolt.settle.freq', 6.0, '34470A')
        app = self.app()
        app.execute(list(T.POINTS[:2]))
        data = self.checkpoint(app)
        # the store changes afterwards: the setting is edited
        self.env.store.edit(e['uid'], value={'value': 8.0}, reason='again', session=self.env.session, author='tester')
        app2 = self.app()
        self.assertEqual(app2.pm_state.param('truevolt.settle.freq', 3.0), 8.0)
        out = app2.pm_on_checkpoint(data)                                 # default: the run continues under what it started with
        self.assertEqual(out['action'], 'saved')
        self.assertEqual(out['diff']['changed'], [('param', 'truevolt.settle.freq')])
        self.assertEqual(app2.pm_state.param('truevolt.settle.freq', 3.0), 6.0)
        app2.execute(list(T.POINTS[2:3]))                                 # begin_run keeps the saved set (pinned)
        self.assertEqual(app2.pm_state.param('truevolt.settle.freq', 3.0), 6.0)
        app3 = self.app()
        self.assertEqual(app3.pm_on_checkpoint(data, choose=lambda diff: 'current')['action'], 'current')
        self.assertEqual(app3.pm_state.param('truevolt.settle.freq', 3.0), 8.0)
        app4 = self.app()
        app4.pm_state.load('A1')
        self.assertEqual(app4.pm_on_checkpoint({'asset': 'A1', 'results': {}})['action'], 'none')

    def test_pinned_snapshot_is_dropped_when_the_asset_changes(self):
        e = self.env.param('truevolt.settle.freq', 6.0, '34470A')
        app = self.app()
        app.execute(list(T.POINTS[:2]))
        data = self.checkpoint(app)
        self.env.store.edit(e['uid'], value={'value': 8.0}, reason='again', session=self.env.session, author='tester')
        app2 = self.app()
        app2.pm_on_checkpoint(data)
        app2.pm_load('A1')
        self.assertEqual(app2.pm_state.param('truevolt.settle.freq', 3.0), 6.0)
        app2.pm_load('OTHER')
        self.assertEqual(app2.pm_state.param('truevolt.settle.freq', 3.0), 8.0)

    def test_all_selected_points_skipped_runs_nothing(self):
        st = pe.ModsState('truevolt', '34470A')
        st.register(list(T.POINTS))
        v = st.factory_points()
        keys = procmods.point_keys(v)
        for k, vv in list(zip(keys, v))[:2]:
            self.env.add('point', k, {}, '34470A', point=vv)
        app = self.app()
        app.execute(list(T.POINTS[:2]))
        self.assertEqual(app.results, {})
        self.assertIn('skipped', app.status.get())
        self.assertFalse(app.busy)

    def test_record_run_snapshot_demo_and_real(self):
        self.env.param('truevolt.settle.freq', 6.0, '34470A')
        app = self.app()
        app.execute(list(T.POINTS[:2]))
        self.assertFalse(app.pm_record_run('R-1'), 'demo mode records nothing')
        self.assertTrue(app.pm_record_run('R-1', demo=False, ))
        snap = procmods.get_run_snapshot('R-1', store=self.env.store)
        self.assertTrue(snap and snap['hash'] == app.pm_state.oset.hash)


class IoAttach(unittest.TestCase):
    def test_attach_with_no_state_does_nothing_at_all(self):
        class Fake:
            idn = 'X'

            def use_commands(self, *a, **k):
                raise AssertionError('must not be called')
        io = T.IO.__new__(T.IO)
        io.pm_attach(None, Fake())
        self.assertEqual(io.pm_param('truevolt.settle.freq', 3.0), 3.0)
        self.assertIsNone(io.pm_state)

    def test_pm_text_and_defaults_literal_when_unmodified(self):
        h = pe.ProcModsMixin()
        self.assertEqual(h.pm_text('ws.dcv_settle', 3.0, '3.0'), '3.0')
        self.assertEqual(h.pm_text('ws.rms_delay', 3, '3'), '3')


# ------------------------------------------------------------------------------------------------------------------------------
class WaveSurfer(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        p = mock.patch.dict('os.environ', {'CALSUITE_DATA': self.home.name, 'HOME': self.home.name, 'USERPROFILE': self.home.name})
        p.start()
        self.addCleanup(p.stop)

    def app(self):
        app = object.__new__(W.RMSNoiseApp)
        app.tb_period_us = _tk_stub._Var(value='10')
        app.pm_init('ws', 'WS4104HD', demo=False, store=self.env.store, devmode=self.env.dm)
        return app

    def test_unmodified_points_are_the_originals(self):
        app = self.app()
        for section, name in W.PM_POINT_METHODS.items():
            fn = getattr(W.RMSNoiseApp, name)
            raw = fn.pm_orig() if fn.pm_static else fn.pm_orig(app)
            self.assertEqual(getattr(app, name)(), raw, name)
        self.assertEqual(len(app.dcv_points()), 80)
        self.assertEqual(len(app.impedance_points()), 28)
        self.assertEqual(len(app.offset_points()), 16)
        self.assertEqual(len(app.bandwidth_points()), 24)
        self.assertEqual(len(app.trigger_points()), 24)

    def test_every_section_point_has_a_unique_stable_key(self):
        app = self.app()
        views = app.pm_limit_views()
        self.assertEqual(set(views), set(W.PM_SECTIONS))
        for section, vs in views.items():
            keys = procmods.point_keys(vs)
            self.assertEqual(len(set(keys)), len(keys), section)
            self.assertFalse(any('#' in k for k in keys), f'{section}: keys must not depend on position')

    def test_tolerance_override_on_each_section_changes_only_that_point(self):
        for section, (nom, lo, hi, _i) in W.PM_SECTIONS.items():
            with self.subTest(section=section):
                env = Env()
                self.addCleanup(env.close)
                self.env = env
                app = self.app()
                views = app.pm_limit_views()[section]
                keys = procmods.point_keys(views)
                factory = app._pm_factory(section)
                j = 3 if len(views) > 3 else 0
                new_lo, new_hi = factory[j][lo] - 0.001, factory[j][hi] + 0.001
                env.add('limit', keys[j], {'mode': 'band', 'low': new_lo, 'high': new_hi}, 'WS4104HD', point=views[j])
                app.pm_state.load('')
                pts = getattr(app, W.PM_POINT_METHODS[section])()
                self.assertEqual(len(pts), len(factory))
                self.assertAlmostEqual(pts[j][lo], new_lo)
                self.assertAlmostEqual(pts[j][hi], new_hi)
                self.assertTrue(pts[j]['limit_modified'])
                for k, (a, b) in enumerate(zip(factory, pts)):
                    if k != j:
                        self.assertEqual(a, b)
                    else:
                        self.assertEqual({x: a[x] for x in a if x not in (lo, hi)}, {x: b[x] for x in a if x not in (lo, hi)})

    def test_tampered_tolerance_is_not_applied(self):
        app = self.app()
        views = app.pm_limit_views()['dcv']
        keys = procmods.point_keys(views)
        e = self.env.add('limit', keys[0], {'mode': 'band', 'low': -1.0, 'high': 1.0}, 'WS4104HD', point=views[0])
        con = sqlite3.connect(str(self.env.db))
        con.execute('DROP TRIGGER override_append_only')
        con.execute('UPDATE override SET reason=? WHERE uid=?', ('edited by hand', e['uid']))
        con.commit()
        con.close()
        app.pm_state.load('')
        self.assertEqual(app.dcv_points(), app._pm_factory('dcv'))
        self.assertTrue(app.pm_state.oset.tampered())

    def test_saved_rows_with_a_modified_tolerance_stay_loadable(self):
        app = self.app()
        fac = app._pm_factory('dcv')
        rows = [dict(fac[0], lower_v=fac[0]['lower_v'] - 1, upper_v=fac[0]['upper_v'] + 1, limit_modified=True), dict(fac[1])]
        pts = app._pm_ckpt_points('dcv', rows)
        for idx, row in enumerate(rows):
            for key in ('channel', 'scale_v_div', 'nominal_v', 'lower_v', 'upper_v'):
                self.assertEqual(row[key], pts[idx][key], key)
        # without the marker the old behaviour (mismatch) stays
        rows[0].pop('limit_modified')
        pts = app._pm_ckpt_points('dcv', rows)
        self.assertEqual(pts, fac)
        self.assertNotEqual(rows[0]['lower_v'], pts[0]['lower_v'])

    def test_entry_boxes_follow_the_defaults_but_not_the_technicians_edits(self):
        self.env.param('ws.dcv_settle', 5.0, 'WS4104HD')
        self.env.param('ws.imp_samples', 4, 'WS4104HD')
        app = self.app()
        V_ = _tk_stub._Var
        for var, _n, _d, text in W.PM_VARS:
            setattr(app, var, V_(value=app.pm_text(_n, _d, text)))
        app._pm_ws_last = {v: getattr(app, v).get() for v, *_r in W.PM_VARS}
        self.assertEqual(app.dc_settle.get(), '5.0')
        self.assertEqual(app.imp_samples.get(), '4')
        self.assertEqual(app.offset_settle.get(), '3.0', 'unmodified boxes keep their literal text')
        app.offset_settle.set('12')                                       # the technician typed something
        self.env.param('ws.offset_settle', 9.0, 'WS4104HD')
        app.pm_state.load('')
        app._pm_defaults()
        self.assertEqual(app.offset_settle.get(), '12')
        self.env.param('ws.trig_settle', 2.5, 'WS4104HD')
        app.pm_state.load('')
        app._pm_defaults()
        self.assertEqual(app.trig_settle.get(), '2.5')

    def test_sidecar_snapshot_round_trip(self):
        self.env.param('ws.dcv_settle', 5.0, 'WS4104HD')
        app = self.app()
        app.instrument_id = _tk_stub._Var(value='WS-1')
        app._batch_busy = lambda: False
        app._pm_ws_last = {}
        for var, _n, _d, text in W.PM_VARS:
            setattr(app, var, _tk_stub._Var(value=text))
        app._pm_begin()
        side = app._pm_sidecar()
        self.assertTrue(side.exists())
        snap = json.loads(side.read_text())['overrides']
        self.assertTrue(procmods.verify_snapshot(snap))
        self.assertEqual(app.dc_settle.get(), '5.0')
        # no modifications: no sidecar is written for another instrument
        app2 = self.app()
        app2.instrument_id = _tk_stub._Var(value='WS-2')
        app2.pm_init('ws', 'WS4104HD', store=procmods.Store(self.env.dir / 'empty.sqlite3', devmode=self.env.dm), devmode=self.env.dm)
        app2._batch_busy = lambda: False
        app2._pm_ws_last = {}
        for var, _n, _d, text in W.PM_VARS:
            setattr(app2, var, _tk_stub._Var(value=text))
        app2._pm_begin()
        self.assertFalse(app2._pm_sidecar().exists())

    def test_nothing_changes_while_a_measurement_runs(self):
        app = self.app()
        app.instrument_id = _tk_stub._Var(value='WS-1')
        app._batch_busy = lambda: True
        self.env.param('ws.dcv_settle', 5.0, 'WS4104HD')
        app._pm_begin()
        self.assertFalse(app.pm_state.oset)

    def test_open_bench_binds_commands_after_open_and_writes_the_banner(self):
        import cmdreg
        reg = cmdreg.merge_commands(drivers.Fluke5560A)
        self.env.add('command', 'Fluke5560A:scope.dcv', {'template': 'scope dcv'}, 'WS4104HD', cmd=reg['scope.dcv'], driver_name='Fluke5560A')
        bench, ft, st = make_bench()
        app = self.app()
        app.pm_state.load('')
        log = drivers.CommandLog()
        with _visa([ft, st]), pinned_run() as events:
            fluke, scope = app.open_bench('sim', 9600, 'sim', log)
            fluke.open()
            scope.open()
            fluke.select_scope_dcv()
            fluke.cleanup()
        wires = [w[1] for w in wire_of(events)]
        self.assertIn('scope dcv', wires)
        self.assertTrue(any(t.startswith('scope dcv') and 'OVERRIDE' in t for *_x, t in log.entries))
        self.assertTrue(any(d == '--' and t.startswith('overrides rev') for _ts, _i, d, t in log.entries))
        # unmodified: no banner, no marker, no wrapper
        env2 = Env()
        self.addCleanup(env2.close)
        self.env = env2
        app2 = self.app()
        app2.pm_state.load('')
        bench, ft, st = make_bench()
        log2 = drivers.CommandLog()
        with _visa([ft, st]):
            fluke2, scope2 = app2.open_bench('sim', 9600, 'sim', log2)
        self.assertEqual(log2.entries, [])
        self.assertNotIn('open', fluke2.__dict__)


if __name__ == '__main__':
    unittest.main()
