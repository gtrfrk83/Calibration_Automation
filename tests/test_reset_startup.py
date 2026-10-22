"""Stage 7: every instrument is reset to its default settings before the first test point of a run.

Enforcement (source level, no tkinter needed):
  * every driver class declares a locked, non-overridable `reset` command, or a documented RESET_EXEMPT (with RESET_KNOWN_STATE)
  * every engine / standalone procedure calls the shared startup helper before its first point (AST check on the source)
  * the rule is written down: NOTES.md, drivers/README.txt, drivers/_template.py
Behaviour (simulated benches): the reset order, never retried, failure stops before any point and leaves outputs in standby/off,
declining the unit-under-test notice touches nothing, the success line is logged, demo mode never resets.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
import drivers  # noqa: E402
import reset_startup  # noqa: E402
from drivers import Fluke28x, Fluke5522A, Fluke5560A, Instrument, Keysight33220A, Keysight34470A  # noqa: E402
from drivers.simulated import make_bench, make_dmm_bench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402
from drivers.simulated_28x import SimFluke28x  # noqa: E402
from drivers.simulated import SimBench  # noqa: E402
from drivers.transport import CommandLog, TransportError  # noqa: E402


def all_driver_classes():
    seen = []
    for name in dir(drivers):
        c = getattr(drivers, name)
        if isinstance(c, type) and issubclass(c, Instrument) and c is not Instrument and c not in seen:
            seen.append(c)
    return seen


class DriversDeclareReset(unittest.TestCase):
    def test_every_driver_class_has_a_locked_reset_or_a_documented_exemption(self):
        bad = []
        for cls in all_driver_classes():
            reg = cmdreg.merge_commands(cls)
            if cls.RESET_EXEMPT:
                if len(cls.RESET_EXEMPT) < 30 or len(cls.RESET_KNOWN_STATE) < 20:
                    bad.append(f'{cls.__name__}: exemption needs a reason and a known-state alternative')
                continue
            cmd = reg.get('reset')
            if cmd is None:
                bad.append(f'{cls.__name__}: no COMMANDS["reset"] and no RESET_EXEMPT')
                continue
            if cmd.risk != 'locked' or cmd.kind != 'set':
                bad.append(f'{cls.__name__}: reset must be a locked set command')
            if cmd.verified and not cmd.ref:
                bad.append(f'{cls.__name__}: reset marked verified without a manual reference')
            if 'opc.query' not in reg:
                bad.append(f'{cls.__name__}: no opc.query to wait for the reset')
        self.assertEqual(bad, [])

    def test_reset_cannot_be_overridden(self):
        _b, ft, _s = make_bench()
        cal = Fluke5560A(ft, CommandLog())
        cal.open()
        rejected = cal.use_commands({'reset': '*IDN?'})
        self.assertTrue(rejected and rejected[0][0] == 'reset' and any('not editable' in str(p) for p in rejected[0][2]))
        self.assertFalse(cmdreg.is_overridable(cal._registry()['reset'])[0])
        self.assertEqual(cal.command_overrides_active(), [])

    def test_exempt_models_are_exactly_the_documented_ones(self):
        self.assertEqual(sorted(c.__name__ for c in all_driver_classes() if c.RESET_EXEMPT), ['Fluke28x'])

    def test_tds_drivers_declare_a_reset(self):
        """The TDS scope resets with FACtory (never *RST, never the self calibration) and is flagged unverified; the scope-option calibrator inherits the
        manual-backed 5522A *RST and is left with SCOPE OFF."""
        from drivers import Fluke5522AScope, TektronixTDS2000C
        reg = cmdreg.merge_commands(TektronixTDS2000C)
        self.assertEqual(reg['reset'].template, 'FACtory')
        self.assertEqual((reg['reset'].risk, reg['reset'].kind, reg['reset'].verified), ('locked', 'set', False))
        self.assertNotIn('*CAL', ''.join(c.template for k, c in reg.items() if k in ('reset', 'status.clear', 'opc.query')))
        self.assertIn('opc.query', reg)
        sc = cmdreg.merge_commands(Fluke5522AScope)['reset']
        self.assertEqual((sc.template, sc.risk, sc.verified), ('*RST', 'locked', True))
        self.assertTrue(Fluke5522AScope.RESET_SCOPE_OFF)

    def test_manual_verified_models(self):
        """Only these resets are backed by a manual page; everything else is flagged unverified in the report."""
        ok = sorted(c.__name__ for c in all_driver_classes()
                    if not c.RESET_EXEMPT and cmdreg.merge_commands(c)['reset'].verified)
        self.assertEqual(ok, ['Fluke5522A', 'Fluke5522AScope', 'Fluke5790B', 'Fluke96270A', 'Keysight53131A', 'Keysight53132A', 'Keysight5313x'])


# ------------------------------------------------------------------------------------------------------------------------------
ENGINES = {          # source file -> (function that starts a run, name of the reset call, name of the first-point call)
    'truevolt_verification.py': ('execute', 'reset_then', '_next'),
    'dacq_verification.py': ('execute', 'reset_then', '_next'),
    'fgen_verification.py': ('execute', 'reset_then', '_next'),
    'handheld_dmm.py': ('execute', 'reset_then', '_next'),
    'mdo4000c_verification.py': ('_worker', 'reset_run', 'run_point'),
    'tds2000c_verification.py': ('_worker', 'reset_run', 'run_point'),
    'Procedures/Agilent_34401A.py': ('execute', 'reset_then', '_next'),
    'Procedures/Fluke_8846A_Verification.py': ('execute', 'reset_then', '_next'),
}


def calls_in(fn_node):
    """[(lineno, attribute/name called)] in source order."""
    out = []
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Call):
            f = n.func
            out.append((n.lineno, f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')))
    return sorted(out)


def find_function(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            yield n


class EnginesCallTheStartupHelper(unittest.TestCase):
    def test_engines_reset_before_their_first_point(self):
        for rel, (fname, reset_call, first_call) in ENGINES.items():
            tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
            fns = list(find_function(tree, fname))
            self.assertTrue(fns, f'{rel}: no {fname}()')
            ok = False
            for fn in fns:
                calls = calls_in(fn)
                names = [c for _l, c in calls]
                if reset_call in names:
                    ok = True
                    if first_call in names:
                        first = min(l for l, c in calls if c == first_call)
                        rline = min(l for l, c in calls if c == reset_call)
                        # execute(): the point loop starts inside the callback passed to reset_then, so the reset call comes on the same line or earlier
                        self.assertLessEqual(rline, first, f'{rel}: {first_call} before {reset_call}')
            self.assertTrue(ok, f'{rel}: {fname}() never calls {reset_call}()')

    def test_engine_classes_take_the_reset_mixins(self):
        for rel in ENGINES:
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertIn('reset_startup.IOResetMixin', src, rel)
            self.assertIn('reset_startup.AppResetMixin', src, rel)
            self.assertIn('def reset_roles', src, rel)

    def test_wavesurfer_calls_reset_after_opening_in_every_test_worker(self):
        src = (ROOT / 'Procedures/WaveSurfer_WS4104HD.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        workers = ['worker', 'automatic_dcv_point', 'read_dcv_scope', 'impedance_worker', 'offset_worker', 'bandwidth_worker',
                   'timebase_worker', 'trigger_worker']
        for w in workers:
            fns = list(find_function(tree, w))
            self.assertEqual(len(fns), 1, w)
            calls = calls_in(fns[0])
            names = [c for _l, c in calls]
            self.assertIn('reset_bench', names, f'{w}() does not reset the bench')
            rline = min(l for l, c in calls if c == 'reset_bench')
            for later in ('set_vertical_scale', 'set_coupling_legacy', 'configure_p1', 'configure_dc_input', 'set_timebase', 'scope_off',
                          'apply_scope_dc', 'set_edge_trigger_source'):
                for l, c in calls:
                    if c == later:
                        self.assertLess(rline, l, f'{w}(): {later} before reset_bench')

    def test_adjustment_resets_when_a_record_starts_or_resumes(self):
        src = (ROOT / 'Procedures/Fluke_8846A_Adjustment.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        for fname in ('start', 'connect'):
            fn = next(find_function(tree, fname))
            self.assertIn('reset_meter', [c for _l, c in calls_in(fn)], fname)
        start = next(find_function(tree, 'start'))
        calls = calls_in(start)
        self.assertLess(min(l for l, c in calls if c == 'reset_meter'), min(l for l, c in calls if c == 'execute'))   # before the INSERT of the record

    def test_every_procedure_launcher_uses_a_checked_engine(self):
        engine_mods = {Path(r).stem for r in ENGINES} | {'WaveSurfer_WS4104HD', 'Fluke_8846A_Adjustment'}
        for path in sorted((ROOT / 'Procedures').glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            imported = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imported |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    imported.add(n.module)
            self.assertTrue(path.stem in engine_mods or imported & engine_mods, f'{path.name}: not a checked engine and imports none')


class RuleIsDocumented(unittest.TestCase):
    def test_notes_readme_and_template(self):
        notes = (ROOT / 'NOTES.md').read_text(encoding='utf-8')
        self.assertIn('Reset to default settings', notes)
        self.assertIn('reset_startup', notes)
        readme = (ROOT / 'drivers/README.txt').read_text(encoding='utf-8')
        self.assertIn("COMMANDS['reset']", readme)
        self.assertIn('RESET_EXEMPT', readme)
        tpl = (ROOT / 'drivers/_template.py').read_text(encoding='utf-8')
        for word in ("COMMANDS['reset']", 'opc_cmd', 'RESET_EXEMPT', '_reset_extra'):
            self.assertIn(word, tpl)


# ------------------------------------------------------------------------------------------------------------------------------
def wire(inst):
    return [t for _ts, _i, d, t in inst.log.entries if d == '>>']


class Behaviour(unittest.TestCase):
    def bench(self):
        b, ft, dt = make_dmm_bench('34470A')
        cal = Fluke5560A(ft, CommandLog(), label='5560A'); dmm = Keysight34470A(dt, cal.log, label='34470A')
        cal.open(); dmm.open()
        b.fluke.update(operate=True, volts=5.0)
        cal.log.entries.clear()
        return b, cal, dmm

    def test_order_and_log_line(self):
        b, cal, dmm = self.bench()
        rep = reset_startup.reset_all([cal], [dmm], confirm=lambda t: True, log=cal.log)
        self.assertTrue(rep.ok)
        sent = wire(cal)
        self.assertEqual(sent[:3], ['*RST', '*CLS', '*OPC?'])                 # calibrator first, reset sequence first
        self.assertLess(sent.index('*RST'), sent.index('STBY'))
        self.assertLess(sent.index('*RST', 3), len(sent))                       # the DMM's *RST follows
        self.assertFalse(b.fluke['operate'])                                     # output in standby
        self.assertIn('Instruments reset to default settings at start: 5560A, 34470A', [t for _ts, _i, _d, t in cal.log.entries])

    def test_reset_write_is_never_retried_and_failure_stops_before_the_dmm(self):
        b, cal, dmm = self.bench()
        b.fail_next = '*RST'                                                      # the calibrator's *RST times out
        with self.assertRaises(reset_startup.ResetFailed) as cm:
            reset_startup.reset_all([cal], [dmm], confirm=lambda t: True, log=cal.log)
        self.assertEqual(wire(cal).count('*RST'), 1)                              # not retried; the DMM was never reset
        self.assertEqual(wire(cal).count('*RST'), 1)
        self.assertFalse(b.fluke['operate'])                                      # outputs to standby after the failure
        self.assertIn('did not reset', str(cm.exception))
        self.assertFalse(any('Instruments reset to default settings' in t for _ts, _i, _d, t in cal.log.entries))

    def test_declined_notice_touches_nothing(self):
        b, cal, dmm = self.bench()
        asked = []
        with self.assertRaises(reset_startup.ResetDeclined):
            reset_startup.reset_all([cal], [dmm], confirm=lambda t: asked.append(t) or False, log=cal.log)
        self.assertEqual(wire(cal), [])
        self.assertTrue(b.fluke['operate'])
        self.assertIn('erase', asked[0].lower())
        self.assertIn('34470A', asked[0])

    def test_no_notice_when_no_unit_under_test_is_reset(self):
        _b, cal, _dmm = self.bench()
        asked = []
        reset_startup.reset_all([cal], [], confirm=lambda t: asked.append(t) or False, log=cal.log)
        self.assertEqual(asked, [])
        meter = Fluke28x(SimFluke28x(SimBench(), '289'), CommandLog(), label='289')
        self.assertIsNone(reset_startup.uut_notice([meter]))

    def test_exempt_instrument_is_reported_not_touched(self):
        sim = SimFluke28x(SimBench(), '289')
        meter = Fluke28x(sim, CommandLog(), label='289')
        rep = reset_startup.reset_all([], [meter], log=meter.log)
        self.assertTrue(rep.exempt and rep.exempt[0].exempt)
        self.assertEqual(wire(meter), [])
        self.assertTrue(any('exempt' in t.lower() for _ts, _i, _d, t in meter.log.entries))

    def test_reset_report_has_per_step_results(self):
        _b, cal, _dmm = self.bench()
        rep = cal.reset_to_defaults()
        self.assertTrue(rep.ok and [s.ok for s in rep.steps] == [True] * len(rep.steps))
        self.assertIn('reset (*RST)', rep.steps[0].name)

    def test_leftover_errors_are_warnings(self):
        _b, ft, _ = make_bench()
        cal = Fluke5560A(ft, CommandLog()); cal.open()
        ft.errors = []
        orig = ft._handle

        def seeded(cmd):
            r = orig(cmd)
            if cmd.upper() == '*CLS':
                ft.errors = ['-113,"Undefined header"']
            return r
        ft._handle = seeded
        rep = cal.reset_to_defaults()
        self.assertTrue(rep.ok)
        self.assertTrue(any('-113' in w for w in rep.warnings))

    def test_error_text_names_the_instrument_in_use(self):
        from drivers import Fluke5522AScope
        for cls, label, want, not_want in ((Fluke5522AScope, '5520A/5522A', '5520A/5522A', '5560A'), (Fluke5522A, '5520A/5522A', '5520A/5522A', '5560A'),
                                           (Fluke5560A, '5560A', '5560A', '5520A')):
            sim = SimBench(); sim.fluke['scope'] = 'OFF'
            from drivers.simulated import SimFlukeTransport
            cal = cls(SimFlukeTransport(sim, '5522A' if cls is not Fluke5560A else '5560A'), CommandLog(), label=label); cal.open()
            cal.read_error = lambda: '-117,"Wrong type of parameter(s)"'
            with self.assertRaises(drivers.InstrumentError) as cm:
                cal.check_error('OUT_IMP 1M')
            self.assertIn(want, str(cm.exception)); self.assertNotIn(not_want, str(cm.exception))
            queue = [f'-{n},"x"' for n in range(1, 40)]
            cal.read_error = lambda: queue.pop(0)
            with self.assertRaises(drivers.InstrumentError) as cm:
                cal.drain_errors(limit=3)
            self.assertIn(want, str(cm.exception)); self.assertNotIn(not_want, str(cm.exception))

    def test_missing_reset_command_fails_closed(self):
        bad = Instrument(make_bench()[1], CommandLog(), label='X')
        rep = bad.reset_to_defaults()
        self.assertFalse(rep.ok)

    def test_session_notice_asks_once_per_session(self):
        asked = []
        n = reset_startup.SessionNotice(None, lambda t: asked.append(t) or True, ttl=100.0, clock=lambda: 0.0)
        self.assertTrue(n('x')); self.assertTrue(n('x'))
        self.assertEqual(len(asked), 1)

    def test_generator_output_is_off_after_reset(self):
        b, t = make_fgen_bench('33220A')
        g = Keysight33220A(t['uut'], CommandLog(), label='33220A'); g.open()
        b.gen.update(on=True)
        rep = g.reset_to_defaults()
        self.assertTrue(rep.ok)
        self.assertFalse(b.gen['on'])

    def test_wire_order_of_a_run_start_begins_with_the_reset_sequence(self):
        """The first commands of a run (after connect) are the reset sequence of the first instrument."""
        _b, cal, dmm = self.bench()
        reset_startup.reset_all([cal], [dmm], log=cal.log)
        self.assertEqual(wire(cal)[0], '*RST')


class AppMixin(unittest.TestCase):
    """AppResetMixin with fakes (no Tk): notice on the 'UI', reset in a thread, proceed or stop."""

    class Var:
        def __init__(self): self.v = ''
        def set(self, v): self.v = v

    class Root:
        def after(self, _ms, fn): fn()

    def app(self, demo=False, answer=True, break_cal=False):
        b, ft, dt = make_dmm_bench('34470A')
        cal = Fluke5560A(ft, CommandLog(), label='5560A'); dmm = Keysight34470A(dt, cal.log, label='34470A'); cal.open(); dmm.open()
        cal.log.entries.clear()
        if break_cal:
            b.fail_next = '*RST'

        class IO(reset_startup.IOResetMixin):
            def __init__(s): s.log = cal.log
            def reset_roles(s): return [cal], [dmm]

        class App(reset_startup.AppResetMixin):
            def __init__(s):
                s.demo, s.io, s.root, s.status, s.busy = demo, IO(), AppMixin.Root(), AppMixin.Var(), True
                s.shown, s.errors = [], []
            def reset_ask(s, text): s.shown.append(text); return answer
            def reset_error(s, text): s.errors.append(text)
        a = App()
        a.cal, a.bench = cal, b
        return a

    def run_then(self, a):
        import threading
        called = []
        a.reset_then(lambda: called.append(1))
        for t in threading.enumerate():
            if t is not threading.main_thread() and t.daemon:
                t.join(5)
        return called

    def test_proceeds_after_a_good_reset(self):
        a = self.app()
        self.assertEqual(self.run_then(a), [1])
        self.assertEqual(wire(a.cal)[0], '*RST')
        self.assertEqual(len(a.shown), 1)

    def test_demo_mode_sends_nothing_and_logs_nothing(self):
        a = self.app(demo=True)
        self.assertEqual(self.run_then(a), [1])
        self.assertEqual(a.cal.log.entries, [])

    def test_decline_stops_the_run_before_any_instrument_is_touched(self):
        a = self.app(answer=False)
        self.assertEqual(self.run_then(a), [])
        self.assertFalse(a.busy)
        self.assertEqual(wire(a.cal), [])

    def test_failed_reset_stops_before_the_first_point(self):
        a = self.app(break_cal=True)
        self.assertEqual(self.run_then(a), [])
        self.assertFalse(a.busy)
        self.assertTrue(a.errors and 'did not reset' in a.errors[0])
        self.assertFalse(a.bench.fluke['operate'])


if __name__ == '__main__':
    unittest.main()
