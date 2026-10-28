"""'Enter reading manually' in every two-way (automatic-reading) procedure engine (owner request: 'i need to be able to enter data manually on all procedures').

The shared mixin is manual_override.ManualOverrideMixin (first built for the Fluke 8808A, see tests/test_8808a_manual_override.py).  Here each engine's real App runs on its
simulated bench (the virtual-bench demo: real IO classes and drivers over simulated instruments; the 5491B, which has no virtual bench, on the simulated 5491B bench) and the
same scenarios are checked per engine:

  * armed      a reading typed while the point is being measured replaces the automatic one (the automatic value is kept as `auto_reading`, nothing else in the record changes);
  * failed     the automatic reading failed (timeout / unreadable): the typed one is asked for, the run goes on; 'Stop run' stops as before;
  * idle       a stored point (or a point not measured yet) is replaced; the old record's automatic reading is the one logged;
  * judged     the typed value is judged by the engine's own limit logic (inclusive limits), never by the mixin;
  * standby    outputs go to standby / off after the point, also when a typed reading replaced the automatic one;
  * report     the report rows are identical with and without the override (no annotation); the override fields are read by no report code;
  * demo       a typed reading in demo mode is synthetic and writes nothing to the shared command log;
  * settings   File > Settings 'manual_override' = off: nothing is offered and a failed reading stops the run as it always did.
The point types that carry no number (a pass / fail self-test) are not applicable and say so.  The Qt windows (PySide6 is absent here) are compile-checked and their
wiring (action bar / right-click entries) is checked on the source.
"""
import ast
import re
import sys
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

VH = h = MO = None


def setUpModule():
    global VH, h, MO
    import _tk_stub
    _tk_stub.install()
    import virtual_harness as _vh
    import handheld_dmm as _h
    import manual_override as _mo
    VH, h, MO = _vh, _vh.hh, _mo


# ====================================================================================================== helpers
def text_for(p, base_value):
    """The text a technician types for `base_value` (base units) in the unit the entry window shows for point p."""
    _vals, _unit, scale = MO.entry_scale(p)
    return format(Decimal(repr(float(base_value))) / scale, 'f')


def limits_of(p):
    lo, hi = MO.point_limits(p)
    return float(lo), float(hi)


def inside_outside(p):
    """(a value inside the limits, a value clearly outside them), base units."""
    lo, hi = limits_of(p)
    if p.get('high') is None and p.get('low') is not None:        # a minimum only
        return lo * 1.05 if lo else 1.0, lo * 0.5 if lo else -1.0
    if p.get('low') is None and p.get('high') is not None:        # a maximum only
        return hi * 0.5, hi * 2.0 if hi else 1.0
    mid = (lo + hi) / 2
    span = (hi - lo) or abs(hi) or 1.0
    return mid, hi + span


class Scripted:
    """What the (patched) entry window answers, in order, and what it was asked."""

    def __init__(self, app):
        self.app, self.answers, self.asked = app, [], []
        app.mo_ask = self

    def __call__(self, p, reason='', cancel_text='Cancel', stored=''):
        self.asked.append(dict(id=p['id'], reason=reason, cancel=cancel_text, stored=stored))
        v = self.answers.pop(0) if self.answers else None
        return MO.parse_reading(p, v) if isinstance(v, str) else v


class Engine:
    """One engine.  Subclasses define make(), ids, the hooks below and the names of the expected strings."""
    NAME = ''
    IDS = ()                      # three numeric points that run in the demo
    SETTLE = True

    # ---- to be provided -------------------------------------------------------------------------------------------------------
    def make(self):               # -> app (virtual demo), asset set
        raise NotImplementedError

    def points(self):
        raise NotImplementedError

    def hook_target(self):        # (owner, attribute, index of the point argument): the automatic measurement of one point
        raise NotImplementedError

    def fail_reading(self, app, p):   # make the automatic reading of point p fail once with a plain instrument error (the engine turns it into a failed reading)
        raise NotImplementedError

    def standby_target(self):     # (owner, attribute): the standby / all-off method of the IO
        raise NotImplementedError

    def judge_expected(self, p, value):
        """The engine's own verdict for `value`: True = PASS (the engine's judge function, else its formula)."""
        raise NotImplementedError

    def run_points(self, app, pts):
        app.execute(pts)
        self.assertTrue(self.hn.pump(240) if not self.POLL else self.hn.pump_poll(240), 'the run did not finish')

    POLL = False
    CERT = 'certificate_rows'

    # ---- common ---------------------------------------------------------------------------------------------------------------
    def setUp(self):
        self.hn = VH.VHarness().start()
        self.addCleanup(self.hn.stop)
        self.stack = []
        self.cur = {'id': None}
        self.standby_calls = []

    def start(self):
        self.unskip()
        app = self.app = self.make()
        self.unskip()
        self.hn.app = app
        self.scripted = Scripted(app)
        return app

    def unskip(self):
        """The live-editor tests (test_beta_live_editor_engines) stage a skip on the engines' shared module POINTS dicts and leave it there: remove it."""
        try:
            for p in self.points():
                p.pop('skip', None)
        except Exception:                           # the scope engines need their App for the point list; the second call (after make) covers them
            pass

    def pt(self, pid):
        return next(p for p in self.points() if p['id'] == pid)

    def install(self, on_start=None, fail_pid=None):
        """Patch the engine so that `on_start(p)` runs (on the worker thread) when the automatic measurement of a point starts, the automatic reading of `fail_pid` fails once
        (fail_reading), and every standby / all-off call is counted (with the point being measured)."""
        owner, name, idx = self.hook_target()
        orig = getattr(owner, name)
        state = dict(failed=False)

        def wrapper(*a, **k):
            p = a[idx]
            self.cur['id'] = p['id']
            if on_start is not None:
                on_start(p)
            if fail_pid is not None and p['id'] == fail_pid and not state['failed']:
                state['failed'] = True
                self.fail_reading(self.app, p)                      # arms a one-shot failure of the instrument read, or raises it
            return orig(*a, **k)
        self.patch(owner, name, wrapper)
        so, sn = self.standby_target()
        sorig2 = getattr(so, sn)

        def counted(*a, **k):
            self.standby_calls.append(self.cur['id'])
            return sorig2(*a, **k)
        self.patch(so, sn, counted)

    def patch(self, owner, name, value):
        p = mock.patch.object(owner, name, value)
        p.start()
        self.addCleanup(p.stop)

    def arm_from_main_thread(self, app, pid, text):
        """The technician clicks 'Enter reading manually' on the main thread while the worker is measuring point pid."""
        armed = threading.Event()

        def on_start(p):
            if p['id'] != pid:
                return
            self.scripted.answers.append(text)
            app.root.after(0, lambda: (app.mo_button_clicked(), armed.set()))
            self.assertTrue(armed.wait(20), 'the pump did not deliver the click')
        return on_start

    def select(self, app, pid):
        app.tree.selection = lambda: [str(pid)]

    def rec(self, app, pid):
        return app.results[str(pid)]

    def verdict(self, p, value):
        return 'PASS' if self.judge_expected(p, value) else 'FAIL'

    # ---- scenarios --------------------------------------------------------------------------------------------------------------
    def test_00_the_switch_is_on_and_the_action_and_menu_exist(self):
        app = self.start()
        self.assertTrue(type(app).MANUAL_OVERRIDE)
        extras = app.tree_menu_extras(str(self.IDS[0]))
        self.assertEqual([(e[0], e[2]) for e in extras], [('Enter reading manually...', True)])
        shell = mock.Mock()
        self.assertIsNotNone(app.mo_add_button(shell))
        shell.add_action.assert_called_once()
        self.assertEqual(shell.add_action.call_args[0][0], 'Enter reading manually')

    def test_01_typed_while_measured_replaces_the_automatic_reading(self):
        app = self.start()
        a, b, c = self.IDS
        pb = self.pt(b)
        good, _bad = inside_outside(pb)
        self.install(on_start=self.arm_from_main_thread(app, b, text_for(pb, good)))
        self.run_points(app, [self.pt(a), pb, self.pt(c)])
        r = self.rec(app, b)
        self.assertTrue(r['overridden'])
        self.assertIsNotNone(r['auto_reading'])
        self.assertAlmostEqual(r['reading'], float(f'{good:.9g}'), places=9 if abs(good) < 1e3 else 4)
        self.assertEqual(r['result'], self.verdict(pb, r['reading']))
        self.assertNotIn('overridden', self.rec(app, a))
        self.assertNotIn('overridden', self.rec(app, c))
        self.assertEqual([x['id'] for x in self.scripted.asked], [b])
        self.assertTrue(any(e.startswith(f'MANUAL OVERRIDE point {b}: auto reading ') for e in app.mo_events), app.mo_events)
        self.assertTrue(r['synthetic'], 'a demo result stays synthetic')
        self.assertFalse(app.busy)
        self.assertIn(b, self.standby_calls, 'outputs go to standby at the end of the overridden point')
        self.assertEqual(len(app.mo_events), 1)

    def test_02_typed_after_an_automatic_failure_and_the_run_goes_on(self):
        app = self.start()
        a, b, c = self.IDS
        pb = self.pt(b)
        good, _bad = inside_outside(pb)
        self.scripted.answers.append(text_for(pb, good))
        self.install(fail_pid=b)
        self.run_points(app, [self.pt(a), pb, self.pt(c)])
        self.assertEqual([x['id'] for x in self.scripted.asked], [b])
        self.assertIn('simulated timeout', self.scripted.asked[0]['reason'])
        self.assertEqual(self.scripted.asked[0]['cancel'], 'Stop run')
        r = self.rec(app, b)
        self.assertTrue(r['overridden'])
        self.assertIsNone(r['auto_reading'])
        self.assertEqual(r['result'], self.verdict(pb, r['reading']))
        self.assertIn(str(c), app.results, 'the run went on to the next point')
        self.assertIn('auto reading none (', app.mo_events[0])
        self.assertIn(b, self.standby_calls, 'standby / off after the failed reading')
        self.assertFalse([d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'showerror'])
        self.assertFalse(app.busy)

    def test_03_stop_run_in_the_window_stops_as_before(self):
        app = self.start()
        a, b, c = self.IDS
        self.scripted.answers.append(None)
        self.install(fail_pid=b)
        self.run_points(app, [self.pt(a), self.pt(b), self.pt(c)])
        self.assertNotIn(str(b), app.results)
        self.assertNotIn(str(c), app.results)
        self.assertEqual(app.mo_events, ())
        self.assertFalse(app.busy)
        self.assertIn(b, self.standby_calls)

    def test_04_switch_off_in_settings_offers_nothing_and_the_failure_stops(self):
        import app_settings
        app = self.start()
        a, b, c = self.IDS
        self.install(fail_pid=b)
        with mock.patch.object(app_settings, 'get', lambda key, default=None: False if key == app_settings.MANUAL_OVERRIDE else default):
            extras = app.tree_menu_extras(str(a))
            self.assertFalse(extras[0][2])
            self.run_points(app, [self.pt(a), self.pt(b), self.pt(c)])
        self.assertEqual(self.scripted.asked, [])
        self.assertNotIn(str(b), app.results)
        self.assertTrue([d for d in self.hn.dialogs if d[0] == 'box' and d[1] == 'showerror'])

    def test_05_idle_replace_is_judged_by_the_engines_own_limit_and_goes_to_standby(self):
        app = self.start()
        a, b, c = self.IDS
        self.install()
        self.run_points(app, [self.pt(a)])
        pa = self.pt(a)
        auto = self.rec(app, a)['reading']
        good, bad = inside_outside(pa)
        n = len(self.standby_calls)
        self.scripted.answers.append(text_for(pa, bad))
        self.select(app, a)
        app.mo_button_clicked()
        r = self.rec(app, a)
        self.assertEqual((r['reading'], r['result']), (float(f'{bad:.9g}'), 'FAIL'))
        self.assertEqual(self.verdict(pa, r['reading']), 'FAIL')
        self.assertEqual(r['auto_reading'], auto)
        self.assertTrue(self.scripted.asked[-1]['stored'], 'the window shows the stored reading it replaces')
        self.assertGreater(len(self.standby_calls), n, 'standby / off after a typed replacement')
        self.scripted.answers.append(text_for(pa, good))
        app.mo_button_clicked()
        r = self.rec(app, a)
        self.assertEqual(r['result'], 'PASS')
        self.assertEqual(r['auto_reading'], auto, 'the instrument reading is kept, not the earlier typed one')
        self.assertEqual(len(app.mo_events), 2)
        # a point that was never measured can be entered too
        self.scripted.answers.append(text_for(self.pt(c), inside_outside(self.pt(c))[0]))
        self.select(app, c)
        app.mo_button_clicked()
        self.assertIsNone(self.rec(app, c)['auto_reading'])
        self.assertIn('point not measured', app.mo_events[-1])

    def test_06_limits_are_inclusive_and_the_verdict_is_the_engines(self):
        app = self.start()
        a = self.IDS[0]
        pa = self.pt(a)
        lo, hi = limits_of(pa)
        self.select(app, a)
        for value in (lo, hi, (lo + hi) / 2, hi + (hi - lo) * 0.01 + abs(hi) * 1e-6, lo - (hi - lo) * 0.01 - abs(lo) * 1e-6):
            if not (pa.get('error') is not None or (pa.get('low') is not None and pa.get('high') is not None)):
                continue                                               # a one-sided limit: covered by test_01 / test_05
            self.scripted.answers.append(text_for(pa, value))
            app.mo_button_clicked()
            r = self.rec(app, a)
            self.assertEqual(r['result'], self.verdict(pa, r['reading']), value)
        self.assertGreaterEqual(len(app.mo_events), 1)

    def test_07_cancel_changes_nothing(self):
        app = self.start()
        a = self.IDS[0]
        self.install()
        self.run_points(app, [self.pt(a)])
        before = dict(self.rec(app, a))
        n = len(self.standby_calls)
        self.scripted.answers.append(None)
        self.select(app, a)
        app.mo_button_clicked()
        self.assertEqual(self.rec(app, a), before)
        self.assertEqual(app.mo_events, ())

    def test_08_the_report_is_identical_with_and_without_the_override(self):
        app = self.start()
        a = self.IDS[0]
        pa = self.pt(a)
        self.install()
        self.run_points(app, [pa])
        good, _ = inside_outside(pa)
        self.scripted.answers.append(text_for(pa, good))
        self.select(app, a)
        app.mo_button_clicked()
        rows_override = getattr(app, self.CERT)()
        value = self.rec(app, a)['reading']
        # the same value recorded by the engine's own recording path, with no override fields
        app.results.pop(str(a))
        app.mo_record(pa, value, bool(app.demo), {})
        rows_plain = getattr(app, self.CERT)()
        self.assertNotIn('overridden', self.rec(app, a))
        self.assertEqual(rows_override, rows_plain)
        flat = repr(rows_override).lower()
        for word in ('override', 'manual', 'typed', 'auto_reading'):
            self.assertNotIn(word, flat)

    def test_09_demo_override_is_synthetic_and_writes_no_log(self):
        app = self.start()
        a = self.IDS[0]
        self.install()
        self.run_points(app, [self.pt(a)])
        pa = self.pt(a)
        self.scripted.answers.append(text_for(pa, inside_outside(pa)[0]))
        self.select(app, a)
        with mock.patch('drivers.CommandLog.append_default') as wrote:
            app.mo_button_clicked()
        wrote.assert_not_called()
        self.assertTrue(self.rec(app, a)['synthetic'])
        self.assertTrue(app.any_synthetic())
        self.assertTrue(app.mo_events[0].endswith('demo]'))
        self.assertFalse(list(Path(self.hn.home).rglob('command_log.txt')))

    def test_10_no_asset_and_no_selection(self):
        app = self.start()
        app.tree.selection = lambda: []
        n = len(self.hn.dialogs)
        app.mo_button_clicked()
        self.assertEqual(self.hn.dialogs[n][2], 'Enter reading manually')
        self.select(app, self.IDS[0])
        app.asset.set('')
        app.mo_button_clicked()
        self.assertEqual(self.hn.dialogs[-1][2], 'Instrument ID')
        self.assertEqual(self.scripted.asked, [])


# ====================================================================================================== the engines
def _truth(r):
    """An engine's judge() returns a bool or the text 'PASS' / 'FAIL'."""
    return r == 'PASS' if isinstance(r, str) else bool(r)


from drivers.base import InstrumentError  # noqa: E402


def _fail_dmm_read(app, p):
    """One-shot failure of the multimeter's read() (the driver call the engines guard)."""
    dmm, orig = app.io.dmm, app.io.dmm.read

    def boom(*a, **k):
        dmm.read = orig
        raise InstrumentError('simulated timeout')
    dmm.read = boom


class Dmm(Engine):
    """The engines that read a multimeter: IO.measure -> IO._read -> dmm.read()."""
    MODULE = None
    MODEL = None
    CONFIG = None

    def setUp(self):
        super().setUp()
        self.M = __import__(self.MODULE)
        if self.CONFIG:
            self.M.configure(self.CONFIG)
        self.IDS = self.pick()

    def pick(self):
        return tuple(p['id'] for p in self.M.POINTS if p['kind'] == 'DCV' and not p.get('zero_offset') and p.get('source') not in ('none', 'manual')
                     and p.get('terminal', 'FRONT') == 'FRONT')[:3]

    def new_app(self):
        return self.M.App(self.hn.root, self.MODEL, demo=True) if self.MODEL else self.M.App(self.hn.root, demo=True)

    def make(self):
        with mock.patch.object(self.M.App, 'refresh_ports', lambda s: None, create=True):
            app = self.new_app()
        app.asset.set('A1'); app.serial.set('S1')
        return app

    def points(self): return self.M.POINTS
    def hook_target(self): return self.M.IO, 'measure', 1
    def standby_target(self): return self.M.IO, 'standby'
    def fail_reading(self, app, p): _fail_dmm_read(app, p)
    def judge_expected(self, p, v): return _truth(self.M.judge(p, v))


class Truevolt(Dmm, unittest.TestCase):
    MODULE, MODEL, CONFIG = 'truevolt_verification', '34470A', '34470A'

    def judge_expected(self, p, v): return abs(v - p['nominal']) <= p['error']          # the engine's own formula (floats)


class Dacq(Dmm, unittest.TestCase):
    MODULE, MODEL, CONFIG = 'dacq_verification', '34970A', '34970A'

    def pick(self): return tuple(p['id'] for p in self.M.POINTS if p['kind'] == 'DCV' and p['source'] == 'calibrator')[:3]
    def judge_expected(self, p, v): return abs(v - p['nominal']) <= p['error']


class Agilent34410A(Dmm, unittest.TestCase):
    MODULE, MODEL, CONFIG = 'agilent34410a_verification', None, '34410A'


class Keithley2000(Dmm, unittest.TestCase):
    MODULE = 'keithley2000_verification'

    def pick(self): return tuple(p['id'] for p in self.M.POINTS if p['kind'] == 'DCV')[:3]


class Agilent34401A(Dmm, unittest.TestCase):
    MODULE = 'Agilent_34401A'

    def judge_expected(self, p, v): return abs(v - p['nominal']) <= p['error']          # the engine's own formula (floats)


class Fluke8846A(Dmm, unittest.TestCase):
    MODULE = 'Fluke_8846A_Verification'

    def judge_expected(self, p, v): return p['low'] <= v <= p['high']                    # the engine's own formula (floats)


class FlukeI400(Dmm, unittest.TestCase):
    """The 400 A clamp family with a reading multimeter (the default 'Manual entry (typed)' has its own typing window: see test_manual_mode)."""
    MODULE = 'i400_verification'

    def pick(self): return tuple(p['id'] for p in self.M.POINTS)[:3]

    def make(self):
        app = super().make()
        app.dmm_model.set('Keysight 34410A')
        return app

    def test_manual_mode_keeps_its_own_typing_window(self):
        app = self.start()
        app.dmm_model.set(self.M.MANUAL)
        a, b, _c = self.IDS
        self.install()
        asked_in_window = []
        with mock.patch.object(h, 'ask_reading', lambda parent, p, total, *x, **k: (asked_in_window.append(p['id']), dict(action='record', text=text_for_mA(p), ann=False, yes=None))[1]):
            self.run_points(app, [self.pt(a)])
        self.assertEqual(asked_in_window, [a])
        self.assertTrue(app.mo_applicable(self.pt(a))[0])               # idle: replace the stored point
        app.busy = True
        self.assertFalse(app.mo_state(self.pt(a))[0], 'busy in typed mode: the run asks for the reading in its own window')
        app.busy = False


def text_for_mA(p):
    return format(Decimal(repr(p['nominal'])) * 1000, 'f')


class Keysight53220A(Engine, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import keysight_53220a_verification as A
        self.M = A
        self.IDS = (2, 3, 5)

    def make(self):
        app = self.M.App(self.hn.root, demo=True, fast_demo=False)
        app.asset.set('A1'); app.serial.set('S1')
        return app

    def points(self): return self.M.POINTS
    def hook_target(self): return self.M.IO, 'measure', 1
    def standby_target(self): return self.M.IO, 'standby'
    def judge_expected(self, p, v): return _truth(self.M.judge(p, v))

    def fail_reading(self, app, p):
        ctr, orig = app.io.ctr, app.io.ctr.measure_stats

        def boom(*a, **k):
            ctr.measure_stats = orig
            raise InstrumentError('simulated timeout')
        ctr.measure_stats = boom

    def test_the_self_test_is_not_applicable(self):
        app = self.start()
        st = next(p for p in self.M.POINTS if p.get('stat') == 'pass')
        ok, why = app.mo_state(st)
        self.assertFalse(ok)
        self.assertIn('self-test', why)
        self.assertFalse(app.tree_menu_extras(str(st['id']))[0][2])


class FunctionGenerator(Engine, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import fgen_verification as F
        F.configure('33220A')
        self.M = F
        self.IDS = tuple(p['id'] for p in F.POINTS if p['kind'] == 'ACAMP')[:3]

    def make(self):
        app = self.M.App(self.hn.root, '33220A', demo=True)
        app.asset.set('A1'); app.serial.set('S1')
        return app

    def points(self): return self.M.POINTS
    def hook_target(self): return self.M.IO, 'measure', 1
    def standby_target(self): return self.M.IO, 'all_off'
    def judge_expected(self, p, v): return _truth(self.M.judge(p, v))

    def fail_reading(self, app, p):
        std, orig = app.io.std, app.io.std.measure

        def boom(*a, **k):
            std.measure = orig
            raise InstrumentError('simulated timeout')
        std.measure = boom

    def test_the_self_test_is_not_applicable_and_a_flatness_point_keeps_its_method(self):
        app = self.start()
        st = next(p for p in self.M.POINTS if p['kind'] == 'SELFTEST')
        ok, why = app.mo_state(st)
        self.assertFalse(ok)
        self.assertIn('self-test', why)
        fl = next(p for p in self.M.POINTS if p['kind'] == 'FLAT')
        self.assertTrue(app.mo_state(fl)[0])
        self.select(app, fl['id'])
        self.scripted.answers.append(text_for(fl, inside_outside(fl)[0]))
        app.mo_button_clicked()
        self.assertEqual(self.rec(app, fl['id'])['raw'], {'method': app.method()})


class Scope(Engine):
    """The oscilloscope engines: one worker thread runs the points (Runner.run_point); the dialog is asked on the UI thread."""
    POLL = True
    MODULE = None

    def setUp(self):
        super().setUp()
        self.M = __import__(self.MODULE)

    def make(self):
        app = self.M.App(self.hn.root, demo=True)
        if hasattr(app, 'read_cfg'):
            app.read_cfg()
        app.asset.set('A1'); app.serial.set('S1')
        return app

    def points(self): return self.app.fam.points if hasattr(self.app, 'fam') else self.M.POINTS
    def hook_target(self): return self.M.Runner, 'run_point', 1
    def standby_target(self): return self.M.IO, 'all_outputs_off'
    def judge_expected(self, p, v): return _truth(self.M.judge(p, v))

    def fail_reading(self, app, p):
        """The executor of the point's kind fails once (inside run_point, so its finally clause switches the outputs off, as in a real failure)."""
        name = 'do_' + p['kind'].lower()
        orig = getattr(self.M.Runner, name)
        state = dict(done=False)

        def boom(runner, q):
            if q['id'] == p['id'] and not state['done']:
                state['done'] = True
                raise InstrumentError('simulated timeout')
            return orig(runner, q)
        self.patch(self.M.Runner, name, boom)

    def test_a_pass_fail_check_is_not_applicable(self):
        app = self.start()
        st = next(p for p in self.points() if p.get('passfail'))
        ok, why = app.mo_state(st)
        self.assertFalse(ok)
        self.assertIn('pass / fail', why)
        self.assertFalse(app.tree_menu_extras(str(st['id']))[0][2])

    def test_a_safety_stop_is_never_offered_a_typed_reading(self):
        import drivers
        app = self.start()
        a, b, c = self.IDS
        self.install()
        orig = getattr(self.M.Runner, 'run_point')

        def run_point(runner, p):
            if p['id'] == b:
                raise drivers.SafetyError('output not confirmed off')
            return orig(runner, p)
        self.patch(self.M.Runner, 'run_point', run_point)
        self.run_points(app, [self.pt(a), self.pt(b), self.pt(c)])
        self.assertEqual(self.scripted.asked, [])
        self.assertNotIn(str(b), app.results)


class Mdo3(Scope, unittest.TestCase):
    MODULE = 'mdo3_verification'

    def setUp(self):
        super().setUp()
        self.IDS = (3, 4, 5)


class Mdo4000C(Scope, unittest.TestCase):
    MODULE = 'mdo4000c_verification'

    def setUp(self):
        super().setUp()
        self.IDS = (3, 4, 5)


class Tbs2000B(Scope, unittest.TestCase):
    MODULE = 'tbs2000b_verification'

    def setUp(self):
        super().setUp()
        self.IDS = (7, 8, 9)


class Tds2000C(Scope, unittest.TestCase):
    MODULE = 'tds2000c_verification'

    def setUp(self):
        super().setUp()
        self.IDS = (3, 4, 5)

    def make(self):
        app = super().make()
        app.v_model.set('2024C')
        return app


# ====================================================================================================== B&K 5491B (real IO on the simulated 5491B bench)
class BK5491B(unittest.TestCase):
    """The 5491B has no virtual bench: the App runs with its real IO over drivers/simulated_5491b.py (as tests/test_bk5491b_points.py).  Besides the scenarios above this proves
    the owner's immediate need: when the meter cannot be connected, or a reading fails, the technician types the reading and the run carries on."""

    def setUp(self):
        from tests import live_editor_harness as H
        import bk5491b_verification as E
        from drivers.simulated_5491b import make_5491b_bench
        self.E, self.H, self.mk = E, H, make_5491b_bench
        self.h5 = H.EngineHarness().start(E)
        self.addCleanup(self.h5.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.answers, self.asked = [], []

    def ask(self, p, reason='', cancel_text='Cancel', stored=''):
        self.asked.append(dict(id=p['id'], reason=reason, cancel=cancel_text, stored=stored))
        try:
            self.asked[-1]['cal'] = self.cal_sent()[-1]              # what the calibrator was last told when the window opened
        except Exception:
            self.asked[-1]['cal'] = None
        v = self.answers.pop(0) if self.answers else None
        return MO.parse_reading(p, v) if isinstance(v, str) else v

    def build(self, connected=True):
        E = self.E
        E.configure()
        app = self.app = E.App(self.h5.root, '5491B', demo=False)
        self.h5.app = app
        app.asset.set('A-5491'); app.serial.set('SN')
        app.mo_ask = self.ask
        self.bench, self.ct, self.dt = self.mk('5522A', True)
        st = app.pm_state
        st.store, st.devmode = self.h5.env.store, self.h5.env.dm
        if connected:
            app.io = E.IO('sim', 'sim', 'Fluke 5522A', 9600, transports=(self.dt, self.ct), mods=app.pm_state)
            app.io.is_manual = app.is_manual
        return app

    def pts(self, *ids):
        return [self.E.POINTS[i - 1] for i in ids]

    def go(self, *ids):
        n = len(self.h5.dialogs)
        self.app.execute(self.pts(*ids))
        self.assertTrue(self.h5.pump(60), 'the run did not finish')
        return self.h5.dialogs[n:]

    def log(self):
        return self.app.io.log.lines()

    def cal_sent(self):
        out = []
        for line in self.log():
            parts = line.split(None, 3)
            if len(parts) > 3 and parts[1] == '5522A' and parts[2] == '>>':
                out.append(parts[3])
        return out

    def first_dcv(self, n=3):
        return [p['id'] for p in self.E.POINTS if p['kind'] == 'DCV' and not self.app.is_manual(p)][:n]

    def test_the_switch_is_on_the_button_and_the_menu_exist(self):
        app = self.build()
        self.assertIs(self.E.App.MANUAL_OVERRIDE, True)
        self.assertEqual([(e[0], e[2]) for e in app.tree_menu_extras('1')], [('Enter reading manually...', True)])
        shell = mock.Mock()
        self.assertIsNotNone(app.mo_add_button(shell))

    def test_typed_while_measured_replaces_the_reading_and_the_output_goes_to_standby(self):
        app = self.build()
        a, b, c = self.first_dcv()
        real = app.io.measure
        armed = threading.Event()

        def measure(p):
            if p['id'] == b:
                self.answers.append(text_for(p, p['nominal']))
                app.root.after(0, lambda: (app.mo_button_clicked(), armed.set()))
                self.assertTrue(armed.wait(10))
            return real(p)
        app.io.measure = measure
        self.go(a, b, c)
        r = app.found[str(b)]
        self.assertTrue(r['overridden'])
        self.assertIsNotNone(r['auto_reading'])
        self.assertEqual(r['result'], 'PASS')
        self.assertNotIn('overridden', app.found[str(a)])
        self.assertEqual(self.cal_sent()[-1], 'STBY')
        self.assertTrue([l for l in self.log() if 'MANUAL OVERRIDE point' in l])

    def test_a_failed_reading_is_typed_and_the_run_goes_on(self):
        app = self.build()
        a, b, c = self.first_dcv()
        self.answers.append(text_for(self.E.POINTS[b - 1], self.E.POINTS[b - 1]['nominal']))
        real = app.io.dmm.read
        state = dict(n=0)

        def read(p=None):
            state['n'] += 1
            if p is not None and p['id'] == b and state['n'] < 100 and not state.get('done'):
                state['done'] = True
                raise InstrumentError('B&K 5491B: simulated timeout')
            return real(p)
        app.io.dmm.read = read
        d = self.go(a, b, c)
        self.assertEqual([x for x in d if x[0] == 'box' and x[1] == 'showerror'], [])
        self.assertEqual(self.asked[0]['id'], b)
        self.assertEqual(self.asked[0]['cancel'], 'Stop run')
        self.assertIn('simulated timeout', self.asked[0]['reason'])
        self.assertEqual(app.found[str(b)]['result'], 'PASS')
        self.assertIn(str(c), app.found)
        self.assertEqual(self.cal_sent()[-1], 'STBY')

    def test_idle_replace_is_judged_by_the_engines_own_limit(self):
        app = self.build()
        a = self.first_dcv()[0]
        p = self.E.POINTS[a - 1]
        self.go(a)
        for text, want in ((text_for(p, p['high']), 'PASS'), (text_for(p, p['high'] + (p['high'] - p['low'])), 'FAIL')):
            self.answers.append(text)
            app.tree.selection = lambda: [str(a)]
            app.mo_button_clicked()
            r = app.found[str(a)]
            self.assertEqual(r['result'], want)
            self.assertEqual(r['result'] == 'PASS', self.E.judge(p, r['reading']))
        self.assertEqual(self.cal_sent()[-1], 'STBY')

    # ---- the meter does not connect ---------------------------------------------------------------------------------------------
    def no_meter(self, mode):
        """Patch the port opening so that the 5491B cannot be reached ('open': the COM port does not open, 'idn': it opens but never answers *IDN?)."""
        E = self.E
        self.bench, self.ct, self.dt = self.mk('5522A', True)
        if mode == 'open':
            def opener(address, serial):
                raise InstrumentError(f'could not open {address}')
            p1 = mock.patch.object(E, 'open_meter_port', opener)
        else:
            p1 = mock.patch.object(E, 'open_meter_port', lambda address, serial: self.dt)
            p3 = mock.patch.object(E.BK5491B, 'connect', mock.Mock(side_effect=InstrumentError('B&K 5491B: no reply to *IDN?')))
            p3.start(); self.addCleanup(p3.stop)
        p1.start(); self.addCleanup(p1.stop)
        p2 = mock.patch.object(E.drivers, 'open_visa', lambda *a, **k: self.ct)
        p2.start(); self.addCleanup(p2.stop)

    def run_without_meter(self, mode):
        app = self.build(connected=False)
        self.no_meter(mode)
        a, b, c = self.first_dcv()
        for pid in (a, b, c):
            p = self.E.POINTS[pid - 1]
            self.answers.append(text_for(p, p['nominal']))
        d = self.go(a, b, c)
        return app, d, (a, b, c)

    def check_typed_run(self, app, d, ids):
        a, b, c = ids
        self.assertIsNotNone(app.io)
        self.assertTrue(app.io.dmm_down)
        self.assertEqual([x for x in d if x[0] == 'box' and x[1] == 'showerror' and x[2] != 'Connection error'], [])
        self.assertEqual(sorted(app.found), sorted(str(i) for i in ids))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertTrue(all(r['overridden'] and r['auto_reading'] is None for r in app.found.values()))
        self.assertEqual([x['id'] for x in self.asked], [a, b, c])
        self.assertTrue(all('not connected' in x['reason'] for x in self.asked))
        self.assertEqual(len([l for l in self.log() if 'MANUAL OVERRIDE point' in l]), 3)
        sent = self.cal_sent()
        self.assertEqual(sent[-1], 'STBY')
        # the output is ON while the technician reads the meter display (OPER when the window opens) and OFF again once the reading is typed
        self.assertEqual([x['cal'] for x in self.asked], ['OPER'] * 3)
        opers = [i for i, t in enumerate(sent) if t == 'OPER']
        self.assertEqual(len(opers), 3)
        for k, i in enumerate(opers):
            nxt = opers[k + 1] if k + 1 < len(opers) else len(sent)
            self.assertIn('STBY', sent[i + 1:nxt], 'the output is switched off after the typed reading of every point')
        self.assertFalse(app.busy)
        self.assertTrue([x for x in d if x[0] == 'box' and x[1] == 'askyesno' and x[2] == 'Meter not connected'])

    def test_meter_port_does_not_open_the_technician_types_and_the_run_goes_on(self):
        app, d, ids = self.run_without_meter('open')
        self.check_typed_run(app, d, ids)
        self.assertFalse([l for l in self.log() if '5491B >>' in l], 'no command was sent to a meter that is not there')

    def test_meter_connects_but_does_not_answer_the_technician_types_and_the_run_goes_on(self):
        app, d, ids = self.run_without_meter('idn')
        self.check_typed_run(app, d, ids)

    def test_declining_the_typed_readings_question_stops_before_any_point_as_before(self):
        app = self.build(connected=False)
        self.no_meter('open')
        self.h5.box_answer['askyesno'] = False
        d = self.go(*self.first_dcv(2))
        self.assertIsNone(app.io)
        self.assertEqual(app.found, {})
        self.assertFalse(app.busy)

    def test_switch_off_in_settings_the_meter_failure_stops_as_before(self):
        import app_settings
        app = self.build(connected=False)
        self.no_meter('open')
        with mock.patch.object(app_settings, 'get', lambda key, default=None: False if key == app_settings.MANUAL_OVERRIDE else default):
            d = self.go(*self.first_dcv(2))
        self.assertIsNone(app.io)
        self.assertEqual(self.asked, [])
        self.assertFalse([x for x in d if x[0] == 'box' and x[2] == 'Meter not connected'])

    def test_stopping_in_the_window_with_no_meter_switches_the_output_off(self):
        app = self.build(connected=False)
        self.no_meter('open')
        self.answers.append(None)
        self.go(*self.first_dcv(2))
        self.assertEqual(app.found, {})
        self.assertFalse(app.busy)
        self.assertEqual(self.cal_sent()[-1], 'STBY')

    def test_a_reading_that_is_not_a_number_is_refused_by_the_window_rules(self):
        p = self.E.POINTS[0]
        for bad in ('', 'abc', 'nan', 'inf', 'OL'):
            with self.assertRaises(ValueError):
                MO.parse_reading(p, bad)


# ====================================================================================================== coverage: no engine escapes a decision
FLAGGED = {          # engine file :: class -> sets MANUAL_OVERRIDE = True
    'agilent34410a_verification.py::App', 'bk5491b_verification.py::App', 'dacq_verification.py::App', 'dsb_runtime.py::DsbApp', 'fgen_verification.py::App',
    'fluke8808a_verification.py::App', 'i400_verification.py::App', 'keithley2000_verification.py::App', 'keysight_53220a_verification.py::App',
    'mdo3_verification.py::App', 'mdo4000c_verification.py::App', 'tbs2000b_verification.py::App', 'tds2000c_verification.py::App', 'truevolt_verification.py::App',
    'Procedures/Agilent_34401A.py::App', 'Procedures/Fluke_8846A_Verification.py::App',
}
INHERITS = {         # engine file :: class -> derives from a flagged App and so has the feature
    'tbs1000_verification.py::TBS1000App': 'tds2000c_verification.App (the TBS1000 family)',
    'tbs1000_verification.py::TBS1000CApp': 'tds2000c_verification.App (the TBS1000C family)',
}
EXCLUDED = {         # engine file :: class -> why it has no automatic reading to replace (documented decision)
    'handheld_dmm.py::App': 'the handheld meters are TYPED procedures: the calibrator is driven and the technician reads the meter and types the value in; the 287 / 289 IR '
                            'reading offers "Type the reading" in its own problem window, and "Type the reading" is the mode switch of the procedure',
    'iflex_option.py::App': 'a subclass of handheld_dmm.App (typed readings, see above)',
    'fluke_753_754.py::App': 'a subclass of handheld_dmm.App (typed readings, see above)',
    'Procedures/Fluke_8808A_Adjustment.py::App': 'a guided ADJUSTMENT (writes calibration constants, no verification reading is judged): nothing to type',
    'Procedures/Keithley_2000_Adjustment.py::App': 'a guided ADJUSTMENT (writes calibration constants, no verification reading is judged): nothing to type',
    'Procedures/Fluke_8846A_Adjustment.py::App': 'a guided ADJUSTMENT (writes calibration constants, no verification reading is judged): nothing to type',
    'Procedures/WaveSurfer_WS4104HD.py::RMSNoiseApp': 'NOT DONE (open item): seven section windows with their own row lists and derived results (noise statistics, bandwidth ratio, timebase, '
                                                      'trigger outcome), no point-id record the mixin works on; the DC voltage section already has a typed entry (P1 acquisition off)',
}


def _app_classes():
    """{'file::Class': sets MANUAL_OVERRIDE True?} for every class named App / *App in the engine files (repository root and Procedures/)."""
    found = {}
    for path in sorted(list(ROOT.glob('*.py')) + list((ROOT / 'Procedures').glob('*.py'))):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT)).replace('\\', '/')
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (node.name == 'App' or node.name.endswith('App')):
                flag = any(isinstance(b, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MANUAL_OVERRIDE' for t in b.targets)
                           and isinstance(b.value, ast.Constant) and b.value.value is True for b in node.body)
                found[f'{rel}::{node.name}'] = flag
    return found


class Coverage(unittest.TestCase):
    def test_every_app_class_sets_the_switch_or_is_in_the_documented_lists(self):
        found = _app_classes()
        self.assertEqual(set(found), FLAGGED | set(INHERITS) | set(EXCLUDED),
                         'a new App class (or a renamed one) needs a decision: set MANUAL_OVERRIDE = True or list it with its reason in EXCLUDED')
        for key, flag in found.items():
            self.assertEqual(flag, key in FLAGGED, key)
        for key, why in {**INHERITS, **EXCLUDED}.items():
            self.assertTrue(len(why) > 20, key)

    def test_the_files_that_set_the_switch(self):
        hits = sorted(str(p.relative_to(ROOT)).replace('\\', '/') for p in list(ROOT.glob('*.py')) + list((ROOT / 'Procedures').glob('*.py'))
                      if re.search(r'^\s*MANUAL_OVERRIDE\s*=\s*True', p.read_text(encoding='utf-8'), re.M))
        self.assertEqual(hits, sorted({k.split('::')[0] for k in FLAGGED} | {'dsb_override.py'}))

    def test_inheriting_classes_really_derive_from_a_flagged_engine(self):
        import tbs1000_verification as B
        import tds2000c_verification as T
        self.assertTrue(issubclass(B.TBS1000App, T.App) and issubclass(B.TBS1000CApp, T.App))
        self.assertIs(B.TBS1000App.MANUAL_OVERRIDE, True)
        self.assertIs(B.TBS1000CApp.MANUAL_OVERRIDE, True)

    def test_the_default_is_off(self):
        self.assertIs(MO.ManualOverrideMixin.MANUAL_OVERRIDE, False)

        class Plain(MO.ManualOverrideMixin):
            pass
        shell = mock.Mock()
        self.assertIsNone(Plain().mo_add_button(shell))
        shell.add_action.assert_not_called()
        self.assertEqual(Plain().tree_menu_extras('1'), [])

    def test_no_report_code_reads_the_override_fields(self):
        """The report is built from reading + result only: no engine's certificate code and no report module mentions the override fields."""
        for path in [ROOT / 'report_pdf.py', ROOT / 'report_snapshot.py', ROOT / 'tartur.py', ROOT / 'tartur_wiring.py']:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('overridden', text, path.name)
            self.assertNotIn('auto_reading', text, path.name)
        for key in FLAGGED:
            if key.startswith('dsb'):
                continue
            path = ROOT / key.split('::')[0]
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and (node.name.startswith('certificate') or node.name in ('export_pdf', 'point_row', 'tar_tur_for')):
                    seg = ast.get_source_segment(path.read_text(encoding='utf-8'), node)
                    self.assertNotIn("'overridden'", seg, f'{key} {node.name}')
                    self.assertNotIn("'auto_reading'", seg, f'{key} {node.name}')

    def test_every_view_wires_the_action_button_and_the_right_click_entry(self):
        """PySide6 is absent here, so the Qt views are checked on their source (they compile: python -m py_compile) the way f8808a_view_qt.py is wired:
        the action bar adds 'Enter reading manually' (B.action_bar(..., manual=True) / genscope action_bar(..., manual=True)), the point list's menu comes from
        pm_bind_tree (ProcModsMixin, or the mixin's own for an App without procedure modifications)."""
        import py_compile
        views = {'truevolt_view_qt.py': 'B.action_bar(self, sh, manual=True)', 'agilent34410a_view_qt.py': 'B.action_bar(self, sh, manual=True)',
                 'k2000_view_qt.py': 'B.action_bar(self, sh, manual=True)', 'keysight_53220a_view_qt.py': 'B.action_bar(self, sh, manual=True)',
                 'dacq_view_qt.py': 'B.action_bar(self, sh, manual=True)', 'i400_view_qt.py': 'B.action_bar(self, sh, manual=True)',
                 'a34401a_view_qt.py': 'B.action_bar(self, sh, manual=True)', 'f8846a_view_qt.py': 'B.action_bar(self, sh, excel=True, manual=True)',
                 'f8808a_view_qt.py': 'B.action_bar(self, sh, manual=True)', 'bk5491b_view_qt.py': 'B.action_bar(self, sh, manual=True)',
                 'fgen_view_qt.py': 'action_bar(self, sh, manual=True)', 'mdo3_view_qt.py': 'action_bar(self, sh, manual=True)',
                 'mdo4000c_view_qt.py': 'action_bar(self, sh, manual=True)', 'tbs2000b_view_qt.py': 'action_bar(self, sh, manual=True)',
                 'tds2000c_view_qt.py': 'action_bar(self, sh, manual=True)'}
        for name, call in views.items():
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn(call, text, name)
            py_compile.compile(str(ROOT / name), doraise=True)
        self.assertIn('self.mo_add_button(sh)', (ROOT / 'qtui' / 'bench_view.py').read_text(encoding='utf-8'))
        self.assertIn('self.mo_add_button(sh)', (ROOT / 'genscope_support_view_qt.py').read_text(encoding='utf-8'))
        for name in ('qtui/bench_view.py', 'genscope_support_view_qt.py', 'manual_override_view_qt.py'):
            py_compile.compile(str(ROOT / name), doraise=True)

    def test_an_app_without_procedure_modifications_gets_the_menu_from_the_mixin(self):
        """tbs2000b / tds2000c have no ProcModsMixin: their point list gets the right-click entry through the mixin's pm_bind_tree."""
        import tbs2000b_verification as B
        import tds2000c_verification as T
        for cls in (B.App, T.App):
            self.assertNotIn('ProcModsMixin', [c.__name__ for c in cls.__mro__])
            self.assertIs(cls.pm_bind_tree, MO.ManualOverrideMixin.pm_bind_tree)
        view = mock.Mock()
        with mock.patch.object(MO.port, 'view', return_value=view):
            app = object.__new__(B.App)
            app.pm_bind_tree('TREE', None)
        view.attach_tree_menu.assert_called_once_with(app, 'TREE', None)


if __name__ == '__main__':
    unittest.main()
