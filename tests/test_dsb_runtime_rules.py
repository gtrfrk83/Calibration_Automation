"""Run-time rules 6 - 13 of the Datasheet Builder (NOTES.md 'DSB run-time rules implemented'), on the simulated benches.

What runs is the real code (handheld_dmm.App + dsb_runtime.DsbApp, worker threads, drivers, judging, checkpoint, command log, PDF); only the modal dialogs are
scripted (tests/dsb_run_harness.py; no tkinter here, tests/_tk_stub.py stands in).  The real-Tk look of the section control is in tests/real_tk_checks.py.

  rule 6   writes set / read back / compared, never retried; OPER read back; error queue after the output command
  rule 7   start-state check before the first point (driver-declared, read-only), with the 8808A's echo / prompts on the simulated 8808A
  rule 8   settle by stable reading (units of dsb_rules, and a generator sheet read by the simulated 5790B / counter)
  rule 9   standby after each point and on abort / error / window close; one HV question per hook-up group; cable prompts only on a hook-up change;
           dial prompt on every function change
  rule 10  reset once per session, notice for a unit under test
  rule 11  progress after every point, resume match, command log saved before an error dialog (and not twice)
  rule 12  section modes: Automated / Typed by hand / Not tested
  rule 13  per-point manual override (no note on the report)
Run:  python -m unittest tests.test_dsb_runtime_rules
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import dsb_override as ov  # noqa: E402
import dsb_rules as rules  # noqa: E402
import dsb_runtime as rt  # noqa: E402
import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
from tests import _tk_stub as _boot  # noqa: E402  (test-only stand-ins for the removed Tk modules)
_boot.install()  # noqa: E402
import report_dialog  # noqa: E402
import drivers  # noqa: E402
from drivers.fluke_8808a import Fluke8808A  # noqa: E402
from drivers.simulated import make_bench, SimFlukeTransport  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402
from drivers.simulated_fgen import make_fgen_bench  # noqa: E402


def spec_of(ds, plan=True):
    return dsp.export_spec(ds, plan=dm.match_datasheet(ds) if plan else None).spec


def cal_io(scope=False, models=('5560A', '5522A'), extra=()):
    bench, _a, _b = make_bench()
    io = rt.DsbIO({}, transports={m: SimFlukeTransport(bench, m) for m in models}, scope=scope, extra=extra)
    io.bench = bench
    return io


def outs(w):
    return [(i, t) for i, (_inst, t) in enumerate(w) if t.startswith('OUT ') and not t.endswith('?')]


def last_write(w):
    """The last command that is not a query (a read-back of the state follows the STBY)."""
    return [t for _i, t in w if not t.endswith('?')][-1]


def log_file(h):
    f = h.home / '.calibration_suite' / 'command_log.txt'
    return f.read_text(encoding='utf-8') if f.exists() else ''


class Base(unittest.TestCase):
    def setUp(self):
        self.h = H.Harness().start()

    def tearDown(self):
        self.h.stop()

    def pdf_text(self, app):
        out = tempfile.mkdtemp() + '/A-100-test.pdf'
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [{'description': 'bench standard', 'serial': '1', 'due': ''}],
             'procedure': '', 'show_tar_tur': True}
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), \
                mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', lambda **k: out):
            app.export_pdf()
        return subprocess.run(['pdftotext', '-layout', out, '-'], capture_output=True, text=True).stdout

    def dmm(self, io=None, **kw):
        io = io or cal_io()
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), io=io, **kw)
        self.h.default_reading = H.typed_nominal
        return app, io

    def gen(self, models=('5790B', '53132A')):
        """The generator sheet with a simulated 33220A, 5790B and 53132A; the scripted operator sets the generator as each prompt asks."""
        bench, t = make_fgen_bench('33220A')
        trans = {'5790B': t['std'], '53132A': t['counter']}
        io = rt.DsbIO({}, transports={m: trans[m] for m in models})
        app = self.h.make_app(spec_of(fx.generator_33220a_like()), io=io)

        def operator(title, heading, steps, facts):
            run = app._cur['run']
            txt = ' '.join(s if isinstance(s, str) else ' '.join(s) for s in steps).upper()
            f = run['reference_hz'] if 'REFERENCE' in txt else run['frequency']
            amp = run['nominal'] if run['kind'] == 'GEN_AMPL' else (run['amplitude'] or 1.0)
            bench.connected = 'counter' if run['op'] == 'std_freq' else 'std'
            if run['op'] == 'std_flat' and 'REFERENCE' not in txt and title == 'Check the setup':
                return True
            bench.gen.update(on=True, func='SIN', freq=f if f else (run['nominal'] if run['kind'] == 'GEN_FREQ' else 1e3), unit='VPP', load=1e40,
                             amp=(amp * 2 * 2 ** 0.5 if run['kind'] != 'GEN_FREQ' else 1.0))
            if run['kind'] == 'GEN_FREQ':
                bench.gen.update(freq=run['nominal'], amp=1.0)
            return True
        self.h.on_confirm = operator
        self.h.default_reading = H.typed_nominal
        return app, io, bench


# ================================================================================================================== rule 6
class Rule6Writes(Base):
    def test_no_retry_helper_is_used_by_the_runtime_sources(self):
        for name in ('dsb_runtime.py', 'dsb_override.py', 'dsb_rules.py'):
            src = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotIn('query_retry', src, name)
            self.assertNotRegex(src, r'for\s+attempt', name)

    def test_a_failed_output_command_is_sent_once_and_the_run_stops_in_standby(self):
        app, io = self.dmm()
        io.bench.fail_next = 'OUT '                       # the first output command times out on the wire
        self.assertTrue(self.h.run_all())
        w = H.wire(io)
        self.assertEqual(len(outs(w)), 1, 'a write is never sent again')
        self.assertEqual(len(app.found), 0)
        self.assertEqual(last_write(w), 'STBY')
        self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' for d in self.h.dialogs))

    def test_error_queue_is_read_after_the_output_command_and_operate_is_read_back(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        t = [x for _i, x in H.wire(io)]
        i = next(n for n, x in enumerate(t) if x.startswith('OUT ') and not x.endswith('?'))
        after = t[i + 1:i + 8]
        self.assertIn('ERR?', after)
        self.assertLess(after.index('ERR?'), after.index('OPER'))
        self.assertIn('OPER?', after[after.index('OPER'):], 'OPERATE is read back (read-only query)')

    def test_an_output_that_is_not_operating_stops_the_run_without_a_second_try(self):
        app, io = self.dmm()
        for d in io.sources():
            d.t.reject = ('OPER',)                          # the calibrator refuses OPER: OPER? stays 0
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), 0)
        self.assertEqual([x for _i, x in H.wire(io)].count('OPER'), 1, 'OPER is never repeated')
        self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' and 'OPERATE' in str(d[3]) for d in self.h.dialogs))


# ================================================================================================================== rule 7
class DeclaringDriver(drivers.Instrument):
    """A driver that declares a start-state check; `bad` makes it fail.  Counts how often it was probed and writes nothing."""
    MODEL = 'Test meter'
    IDN_MATCH = ()
    RESET_EXEMPT = 'test double: nothing to reset'
    RESET_KNOWN_STATE = 'n/a'

    def __init__(self, log, bad=False, label='TESTMETER'):
        super().__init__(mock.MagicMock(), log, label)
        self.bad, self.probed, self.written = bad, 0, []

    def start_state_checks(self):
        def probe():
            self.probed += 1
            return (not self.bad), ('echo is on' if self.bad else 'echo is off')
        return [rules.Probe('Echo off', probe, 'Turn Echo off in the front-panel serial settings.')]

    def write(self, cmd, log_as=None):
        self.written.append(cmd)

    def close(self):
        pass


class Rule7StartState(Base):
    def test_a_driver_that_declares_nothing_is_not_checked(self):
        app, io = self.dmm()
        self.assertFalse(io.has_start_state_checks())
        self.assertTrue(self.h.run_all())
        self.assertFalse([e for e in io.log.entries if 'start-state' in e[3]])
        self.assertEqual(rules.declared_probes(object()), [])

    def test_probes_are_read_only_never_raise_and_are_logged(self):
        log = drivers.CommandLog()
        d = DeclaringDriver(log, bad=True)
        boom = type('Boom', (), {'start_state_checks': lambda self: [rules.Probe('x', lambda: 1 / 0, 'fix x'), rules.Probe('y', None, note='no query exists')]})()
        res = rules.run_probes([('A', d), ('B', boom)], log)
        self.assertEqual([(r.instrument, r.name, r.ok, r.checked) for r in res], [('A', 'Echo off', False, True), ('B', 'x', False, True), ('B', 'y', True, False)])
        self.assertEqual(d.written, [], 'a probe writes nothing')
        text = '\n'.join(log.lines())
        self.assertIn('NOT AS NEEDED', text)
        self.assertIn('NOT CHECKED', text)
        self.assertIn('fix x', rules.failure_text(res))
        self.assertNotIn('NOT CHECKED', rules.failure_text(res))

    def test_identity_check_is_skipped_for_a_driver_that_cannot_answer_idn(self):
        class NoIdn(drivers.Instrument):
            IDN_MATCH = ('X1',)
            IDN_UNAVAILABLE = True
        self.assertIsNone(rules.identity_probe(NoIdn(mock.MagicMock())))

        class WithIdn(drivers.Instrument):
            IDN_MATCH = ('X1',)
            MODEL = 'X1'

            def identify(self):
                return 'ACME,X2,1,1'
        probe = rules.identity_probe(WithIdn(mock.MagicMock()))
        self.assertFalse(probe.run()[0])

    def test_run_is_refused_before_any_point_then_goes_on_when_the_setting_is_fixed(self):
        d = DeclaringDriver(drivers.CommandLog(), bad=True)
        io = cal_io(extra=[('TESTMETER', d, 'standard')])
        app, _ = self.dmm(io=io)
        self.h.run_all()
        self.assertEqual(outs(H.wire(io)), [], 'no point was output')
        self.assertFalse(app.busy)
        box = [x for x in self.h.dialogs if x[0] == 'box' and x[1] == 'showerror']
        self.assertEqual(len(box), 1)
        self.assertEqual(box[0][2], 'Check the instrument settings')
        self.assertIn('Turn Echo off in the front-panel serial settings.', box[0][3])
        self.assertIn('TESTMETER', box[0][3])
        self.assertIn('start-state', log_file(self.h), 'the command log was saved before the dialog')
        d.bad = False                                       # the operator fixes it
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), len(app.points))
        self.assertEqual(d.probed, 2)
        self.assertEqual([x for _i, x in H.wire(io)].count('*RST'), 2, 'rule 10: the failed first Run reset, the second Run did not reset again')

    def test_8808a_adapter_sees_echo_and_prompts_on_the_simulated_meter(self):
        _bench, _ct, dt = make_8808a_bench()
        log = drivers.CommandLog()
        meter = Fluke8808A(dt, log, label='8808A').connect()
        probes = {p.name: p for p in rules.declared_probes(meter)}
        self.assertEqual(set(probes), {'Echo off, no prompts', 'Identity', 'Remote state'})
        self.assertIsNone(probes['Remote state'].run, 'the 8808A has no remote-state query: listed as not checked')
        self.assertTrue(probes['Echo off, no prompts'].run()[0])
        self.assertTrue(probes['Identity'].run()[0])
        dt.echo = True
        res = rules.run_probes([('8808A', meter)], log)
        bad = rules.failed(res)
        self.assertEqual(bad[0].name, 'Echo off, no prompts')
        self.assertIn('Echo is ON', bad[0].detail)
        self.assertIn('Turn Echo OFF', rules.failure_text(res))
        dt.echo = False
        dt.clear()
        dt.prompts = True                                    # prompts without echo
        res = rules.run_probes([('8808A', meter)], log)
        self.assertTrue(rules.failed(res), 'prompts that follow a reply are counted')
        self.assertNotIn('ESR', ' '.join(t for _t, _i, d, t in log.entries if d == '>>' and 'start' in t))

    def test_run_with_an_8808a_attached_checks_it_and_refuses_when_echo_came_on(self):
        _bench, _ct, dt = make_8808a_bench()
        meter = Fluke8808A(dt, drivers.CommandLog(), label='8808A').connect()
        io = cal_io(extra=[('8808A', meter, 'uut')])
        app, _ = self.dmm(io=io)
        self.assertTrue(self.h.run_all())                    # rule 10 notice (unit under test), reset, probes ok
        self.assertTrue(any(d[0] == 'box' and d[1] == 'askokcancel' for d in self.h.dialogs), 'the unit-under-test notice')
        n = len(outs(H.wire(io)))
        dt.echo = True                                       # somebody turned Echo on between the runs
        self.h.dialogs.clear()
        point = app.points[0]
        app.results.pop(point['id'], None)
        app.found.pop(point['id'], None)
        self.h.run_all()
        self.assertEqual(len(outs(H.wire(io))), n, 'nothing was output')
        box = [x for x in self.h.dialogs if x[0] == 'box' and x[1] == 'showerror']
        self.assertTrue(box)
        self.assertIn('Echo', box[0][3])


# ================================================================================================================== rule 8
class Rule8Units(unittest.TestCase):
    def seq(self, values):
        it = iter(values)
        return lambda: next(it)

    def clock(self, step=1.0):
        t = [0.0]

        def now():
            t[0] += step
            return t[0]
        return now

    def test_stable_after_n_agreeing_readings_and_the_last_reading_is_returned(self):
        v, res = rules.settle_stable(self.seq([1.0, 1.5, 1.2, 1.2004, 1.2008, 9.9]), rules.StableSpec(n=3, band=0.001, timeout_s=100), wait=lambda s, c: None, clock=self.clock())
        self.assertTrue(res.stable)
        self.assertEqual(res.polls, 5)
        self.assertEqual(v, 1.2008, 'exactly what was read last: no averaging')
        self.assertAlmostEqual(res.spread, 0.0008)

    def test_band_is_inclusive_and_a_wider_spread_is_not_stable(self):
        _v, res = rules.settle_stable(self.seq([1.0, 1.001, 1.002]), rules.StableSpec(n=3, band=0.002, timeout_s=100), wait=lambda s, c: None, clock=self.clock())
        self.assertTrue(res.stable)
        _v, res = rules.settle_stable(self.seq([1.0, 1.001, 1.0021, 1.0021, 1.0021]), rules.StableSpec(n=3, band=0.002, timeout_s=100), wait=lambda s, c: None, clock=self.clock())
        self.assertEqual(res.polls, 4, 'the window moves on: 1.0 / 1.001 / 1.0021 disagree, 1.001 / 1.0021 / 1.0021 agree')
        self.assertTrue(res.stable)

    def test_timeout_returns_the_last_reading_and_says_so(self):
        n = [0]

        def noisy():
            n[0] += 1
            return float(n[0] % 2)
        v, res = rules.settle_stable(noisy, rules.StableSpec(n=3, band=0.1, minimum_s=0.0, timeout_s=10.0), wait=lambda s, c: None, clock=self.clock())
        self.assertFalse(res.stable)
        self.assertEqual(v, float(n[0] % 2))
        self.assertIn('NOT stable: timeout', res.text('V'))

    def test_minimum_time_is_waited_first_and_the_cap_is_never_below_it(self):
        waits = []
        v, res = rules.settle_stable(self.seq([2.0, 2.0, 2.0]), rules.StableSpec(n=3, band=0.0, minimum_s=5.0, timeout_s=1.0, poll_s=0.2),
                                     wait=lambda s, c: waits.append(s), clock=self.clock(0.0001))
        self.assertEqual(waits[0], 5.0)
        self.assertTrue(res.stable)

    def test_cancel_reaches_the_wait(self):
        def wait(seconds, cancel):
            if cancel():
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            rules.settle_stable(self.seq([1.0, 2.0, 3.0]), rules.StableSpec(n=3, band=0.0, minimum_s=1.0), cancel=lambda: True, wait=wait)

    def test_default_band_follows_the_resolution_and_never_exceeds_a_tenth_of_the_tolerance(self):
        self.assertAlmostEqual(rules.default_band({'low': '0.9900', 'high': '1.0100'}, 3.0), 0.0003)      # 3 counts of 1e-4
        self.assertAlmostEqual(rules.default_band({'low': '99.99', 'high': '100.01'}, 3.0), 0.01, msg='never below one count')
        self.assertAlmostEqual(rules.default_band({'low': '0.0001', 'high': '0.0002'}, 3.0), 0.0001)
        self.assertAlmostEqual(rules.default_band({'low': '0.900', 'high': '1.100'}, 50.0), 0.02, msg='capped at a tenth of the tolerance width')
        self.assertGreater(rules.default_band({'low': '0', 'high': '1000'}, 3.0), 0)

    def test_tunables_are_registered_flagged_unverified_and_bounded(self):
        for name in ('dsb.stable.n', 'dsb.stable.band_counts', 'dsb.stable.timeout'):
            t = pe.TUNABLES[name]
            self.assertIn('UNVERIFIED estimate', t['label'])
            self.assertEqual(procmods._check_param_value(name, t['default']), [])
            self.assertTrue(procmods._check_param_value(name, t['hi'] * 10))
        for name in ('dsb.point.stable_n', 'dsb.point.stable_band', 'dsb.point.stable_timeout'):
            self.assertTrue(procmods.PARAMS[name]['per_point'])
            self.assertIn('UNVERIFIED estimate', procmods.PARAMS[name]['label'])
        self.assertEqual(procmods.PARAMS['dsb.point.stable_n']['field'], 'stable_n')
        self.assertEqual(pe.defaults_for('dsb')['dsb.stable.n'], 3)


class Rule8Bench(Base):
    def drift(self, bench, values, then=None):
        """The simulated unit under test's level (as the 5790B sees it) follows `values` poll by poll, then `then(poll number)` or the last value."""
        n = [0]
        real = bench.vrms_into
        scale = [None]

        def vrms(r):
            n[0] += 1
            if scale[0] is None:
                scale[0] = real(r)
            k = n[0] - 1
            f = values[k] if k < len(values) else (then(k) if then else values[-1])
            return scale[0] * f
        bench.vrms_into = vrms
        return n

    def amp_points(self, app):
        return [p for p in app.points if p['run']['kind'] == 'GEN_AMPL']

    def test_the_standard_is_polled_until_stable_and_the_last_reading_is_recorded(self):
        app, io, bench = self.gen()
        self.drift(bench, [0.9, 0.97, 1.0, 1.0, 1.0])            # drifts for two polls, then settles at the nominal
        pts = self.amp_points(app)[:1]
        app.execute(pts)
        self.h.pump()
        r = app.found[pts[0]['id']]
        self.assertEqual(r['source'], 'standard')
        w = [t for _i, t in H.wire(io)]
        text = '\n'.join(io.log.lines())
        m = re.search(r'SETTLE\s+--\s+gen_ampl\S+: reading stable after (\d+) poll', text)
        self.assertTrue(m, text[-600:])
        self.assertGreaterEqual(w.count('MEAS?'), int(m.group(1)), 'each poll is a MEAS? (the 5790B driver also re-reads while the instrument reports an invalid reading)')
        self.assertGreaterEqual(int(m.group(1)), 3)
        self.assertAlmostEqual(r['raw']['vrms'], pts[0]['run']['nominal'], places=4, msg='the recorded reading is the last poll (the earlier ones were 10 % and 3 % low), not an average')

    def test_every_poll_is_a_read_only_query(self):
        app, io, bench = self.gen()
        self.drift(bench, [0.9, 0.97, 1.0, 1.0, 1.0])
        app.execute(self.amp_points(app)[:1])
        self.h.pump()
        w = [t for _i, t in H.wire(io)]
        first, last = w.index('MEAS?'), len(w) - 1 - w[::-1].index('MEAS?')
        between = [t for t in w[first:last + 1] if t != 'MEAS?']
        self.assertEqual(between, [], 'nothing but MEAS? between the first and the last poll')

    def test_timeout_is_logged_and_the_last_reading_is_still_judged(self):
        app, io, bench = self.gen()
        t = [0.0]

        def clock():
            t[0] += 2.0
            return t[0]
        io._clock = clock
        self.drift(bench, [0.9], then=lambda k: 1.0 + (0.05 if k % 2 else -0.05))
        pts = self.amp_points(app)[:1]
        app.execute(pts)
        self.h.pump()
        text = '\n'.join(io.log.lines())
        self.assertRegex(text, r'SETTLE\s+!!\s+gen_ampl\S+: reading NOT stable: timeout after \d+ poll')
        self.assertIn(pts[0]['id'], app.found, 'a timeout does not stop the run: the last reading is recorded and judged by the limits')
        self.assertEqual(app.found[pts[0]['id']]['result'], 'PASS' if abs(app.found[pts[0]['id']]['raw']['vrms'] / pts[0]['run']['nominal'] - 1) < 0.06 else 'FAIL')

    def test_settings_come_from_the_tunables_and_from_the_point(self):
        app, io, bench = self.gen()
        mods = mock.MagicMock()
        mods.param = lambda name, default, point=None: {'dsb.stable.n': 4, 'dsb.stable.band_counts': 2.0, 'dsb.stable.timeout': 12.0}.get(name, default)
        io.__dict__['_pm_state'] = mods
        p = self.amp_points(app)[0]
        spec = io.stable_spec(p)
        self.assertEqual((spec.n, spec.timeout_s), (4, 12.0))
        self.assertAlmostEqual(spec.band, rules.default_band(p, 2.0) * p['factor'])
        self.assertEqual(spec.minimum_s, 3.0, 'the point\'s ordinary settle time is the minimum')
        q = dict(p, stable_n=2, stable_band=5.0, stable_timeout=7.0, settle=1.5)
        spec = io.stable_spec(q)
        self.assertEqual((spec.n, spec.timeout_s, spec.minimum_s), (2, 7.0, 1.5))
        self.assertAlmostEqual(spec.band, rules.default_band(p, 5.0) * p['factor'])

    def test_the_edit_procedure_window_lists_the_settle_settings(self):
        app, io, bench = self.gen()
        ctx = app.pm_live_context()
        for name in ('dsb.stable.n', 'dsb.stable.band_counts', 'dsb.stable.timeout'):
            self.assertIn(name, ctx.defaults)

    def test_the_fixed_settle_time_is_the_minimum_before_the_first_poll(self):
        app, io, bench = self.gen()
        calls = []
        with mock.patch.object(rt.hh.IO, '_wait', staticmethod(lambda s, c=None: calls.append(s))):
            app.execute(self.amp_points(app)[:1])
            self.h.pump()
        self.assertEqual(calls[0], 3.0)

    def test_counter_frequency_is_polled_too_and_typed_points_are_not(self):
        app, io, bench = self.gen()
        self.assertTrue(self.h.run_all())
        lines = io.log.lines()
        for p in app.points:
            polled = [l for l in lines if 'SETTLE' in l and p['id'] in l]
            if p['run']['op'] in ('std_freq', 'std_level') and p['_route'].auto and p['id'] in app.found and app.found[p['id']]['source'] == 'standard':
                self.assertTrue(polled, p['id'])
            if p['run']['op'] == 'std_other':
                self.assertFalse(polled, p['id'])

    def test_a_dmm_sheet_never_polls(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        self.assertFalse([e for e in io.log.entries if e[1] == 'SETTLE'])


# ================================================================================================================== rule 9
class Rule9SafeOutputs(Base):
    def test_standby_after_every_point(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        w = H.wire(io)
        o = outs(w)
        for (i, _a), (j, _b) in zip(o, o[1:]):
            self.assertTrue(any(t == 'STBY' for _x, t in w[i + 1:j]))
        self.assertEqual(last_write(w), 'STBY')

    def test_stop_in_the_middle_ends_in_standby(self):
        app, io = self.dmm()
        n = [0]
        base = self.h.default_reading

        def stop_after_three(p):
            n[0] += 1
            if n[0] == 3:
                app.request_stop()
            return base(p)
        self.h.default_reading = stop_after_three
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), 3)
        self.assertEqual(last_write(H.wire(io)), 'STBY')
        data = json.loads(app._checkpoint_path().read_text())
        self.assertEqual(len(data['results']), 3, 'progress saved')

    def test_error_in_the_middle_ends_in_standby(self):
        app, io = self.dmm()
        n = [0]
        base = self.h.default_reading

        def fail_after_two(p):
            n[0] += 1
            if n[0] == 2:
                io.bench.fail_next = 'OUT '
            return base(p)
        self.h.default_reading = fail_after_two
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(app.found), 2)
        self.assertEqual(last_write(H.wire(io)), 'STBY')
        self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' for d in self.h.dialogs))

    def test_closing_the_window_puts_the_calibrators_in_standby(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        io.cal.send('oper.on')                                # something left an output on
        app.on_close()
        self.assertIsNone(app.io)
        self.assertEqual(last_write(H.wire(io)), 'STBY')
        self.assertEqual(io.bench.fluke['operate'], False)

    def test_one_high_voltage_question_per_hook_up_group_and_again_in_the_next_run(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        hv = [d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']
        self.assertEqual(len(hv), 1)
        again = next(p for p in app.points if app._high_voltage(p))
        app.found.pop(again['id'])
        app.execute([again])
        self.h.pump()
        self.assertEqual(len([d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE']), 2, 'a new Run asks again')

    def test_declining_the_high_voltage_question_stops_before_the_output(self):
        app, io = self.dmm()
        self.h.box_answer['askyesno'] = False
        self.assertTrue(self.h.run_all())
        first_hv = next(p for p in app.points if app._high_voltage(p))
        self.assertNotIn(first_hv['id'], app.found)
        self.assertEqual(last_write(H.wire(io)), 'STBY')

    def test_dial_prompt_on_every_function_change(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        changes = []
        last = None
        for p in app.points:
            if p['group'] == 'NONE':
                continue
            if p['switch'] != last:
                changes.append(p['section'])
            last = p['switch']
        shown = [d[2] for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Change the function']
        self.assertEqual(shown, changes)
        self.assertGreater(len(shown), 3)

    def test_cable_prompts_only_when_the_hook_up_changes(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        setups = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Check the setup']
        groups = []
        prev = None
        for p in app.points:
            k = p['id'] if p['group'] == 'NONE' else p['group']
            if k != prev:
                groups.append(p['section'])
            prev = k
        self.assertEqual(len(setups), len(groups))
        self.assertLess(len(setups), len(app.points) / 3)

    def test_generator_connect_step_is_asked_only_when_the_hook_up_changes(self):
        app, io, bench = self.gen()
        self.assertTrue(self.h.run_all())
        dlgs = [d for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Check the setup']
        connect = [next((st for st in d[3] if st.startswith('Connect')), None) for d in dlgs]
        texts = [c for c in connect if c]
        self.assertEqual(len(dlgs), len(app.points))
        self.assertGreaterEqual(len(texts), 2)
        self.assertLess(len(texts), len([p for p in app.points if p['run']['direction'] == 'source']) / 2)
        for a, b in zip(texts, texts[1:]):
            self.assertNotEqual(a, b, 'the same hook-up is never asked for twice running')
        connects = texts
        self.h.dialogs.clear()
        pt = next(p for p in app.points if p['run']['op'] == 'std_level')
        app.found.pop(pt['id'])
        app.execute([pt])
        self.h.pump()
        self.assertEqual(len([d for d in self.h.dialogs if d[0] == 'confirm' and d[1] == 'Check the setup' and any(s.startswith('Connect') for s in d[3])]), 1,
                         'a new Run asks for the cable again')


# ================================================================================================================== rule 10
class Rule10ResetOnce(Base):
    def test_first_run_resets_later_runs_only_check(self):
        app, io = self.dmm()
        pts = app.points
        app.execute(pts[:2])
        self.h.pump()
        w = [t for _i, t in H.wire(io)]
        self.assertEqual(w.count('*RST'), 2)
        app.execute(pts[2:4])
        self.h.pump()
        w = [t for _i, t in H.wire(io)]
        self.assertEqual(w.count('*RST'), 2, 'not reset again in the same session')
        text = '\n'.join(io.log.lines())
        self.assertIn('reset skipped: already reset this session', text)
        self.assertIn('session check: calibrator(s) in STANDBY (read back)', text)
        self.assertEqual(len(app.found), 4)

    def test_a_new_connection_resets_again(self):
        app, io = self.dmm()
        app.execute(app.points[:1])
        self.h.pump()
        io2 = cal_io()
        app.io = io2
        app.execute(app.points[1:2])
        self.h.pump()
        self.assertEqual([t for _i, t in H.wire(io2)].count('*RST'), 2)

    def test_a_failed_skip_check_resets_again_next_time(self):
        app, io = self.dmm()
        app.execute(app.points[:1])
        self.h.pump()
        orig = io.sources()[0].ask
        io.sources()[0].ask = lambda key, *a, **k: '1' if key == 'oper.query' else orig(key, *a, **k)      # a calibrator that will not confirm standby
        self.h.dialogs.clear()
        app.execute(app.points[1:2])
        self.h.pump()
        self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' for d in self.h.dialogs))
        self.assertFalse(app.busy)
        io.sources()[0].ask = orig
        app.execute(app.points[1:2])
        self.h.pump()
        self.assertEqual([t for _i, t in H.wire(io)].count('*RST'), 4, 'after a failed check the next Run resets')

    def test_unit_under_test_notice_is_shown_and_declining_touches_nothing(self):
        _bench, _ct, dt = make_8808a_bench()
        meter = Fluke8808A(dt, drivers.CommandLog(), label='8808A').connect()
        io = cal_io(extra=[('8808A', meter, 'uut')])
        app, _ = self.dmm(io=io)
        self.h.box_answer['askokcancel'] = False
        self.h.run_all()
        note = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'askokcancel']
        self.assertEqual(len(note), 1)
        self.assertIn('Reset instruments', note[0][2])
        self.assertIn('Unit under test that will be reset: 8808A', note[0][3])
        self.assertEqual([t for _i, t in H.wire(io)].count('*RST'), 0)
        self.assertFalse(app.busy)

    def test_demo_and_fast_demo_write_nothing(self):
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), demo=True)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual(log_file(self.h), '')


# ================================================================================================================== rule 11
class Rule11Progress(Base):
    def test_progress_is_saved_after_every_point(self):
        app, io = self.dmm()
        seen = []
        base = self.h.default_reading

        def watch(p):
            path = app._checkpoint_path()
            seen.append(len(json.loads(path.read_text())['results']) if path.exists() else 0)
            return base(p)
        self.h.default_reading = watch
        self.assertTrue(self.h.run_all())
        self.assertEqual(seen[:5], [0, 1, 2, 3, 4], 'the file holds every point read so far, before the next one is asked')
        self.assertEqual(len(json.loads(app._checkpoint_path().read_text())['results']), len(app.points))

    def test_resume_into_another_datasheet_period_or_version_is_refused_and_the_same_one_resumes(self):
        spec = spec_of(fx.dmm_34461a_like())
        app, io = self.dmm()
        app.execute(app.points[:3])
        self.h.pump()
        path = app._checkpoint_path()
        app2 = self.h.make_app(spec, io=cal_io())
        with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertEqual(len(app2.found), 3)
        other = spec_of(fx.generator_33220a_like())
        app3 = self.h.make_app(other, io=cal_io())
        self.h.dialogs.clear()
        with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
            app3.load()
        self.assertEqual(len(app3.found), 0)
        self.assertTrue(any(d[0] == 'box' and d[1] == 'showerror' for d in self.h.dialogs))

    def test_command_log_is_on_disk_before_the_error_dialog_and_not_written_twice(self):
        app, io = self.dmm()
        io.bench.fail_next = 'OUT '
        seen = []
        orig = rt.hh.messagebox.showerror

        def snap(*a, **k):
            seen.append(log_file(self.h))
            return orig(*a, **k)
        with mock.patch.object(rt.hh.messagebox, 'showerror', snap):
            self.assertTrue(self.h.run_all())
        self.assertTrue(seen)
        self.assertIn("OUT -0.1V,0Hz", seen[0], 'the command that failed is in the file when the dialog opens')
        self.assertIn('*RST', seen[0])
        app.disconnect()
        final = log_file(self.h)
        self.assertEqual(final.count('OUT -0.1V,0Hz'), seen[0].count('OUT -0.1V,0Hz'), 'closing later does not repeat the lines')
        self.assertEqual(final.count('>>  *RST'), seen[0].count('>>  *RST'))
        self.assertIn('(continued)', final)

    def test_command_log_is_saved_before_the_measuring_standard_dialog(self):
        app, io, bench = self.gen()
        orig = self.h.on_confirm

        def wrong_input(title, heading, steps, facts):
            r = orig(title, heading, steps, facts)
            if app._cur['run']['op'] == 'std_freq':
                bench.connected = 'std'
            return r
        self.h.on_confirm = wrong_input
        seen = []
        real = self.h._box

        def box(kind, args):
            if args and args[0] == 'Measuring standard':
                seen.append(log_file(self.h))
            return real(kind, args)
        self.h._box = box
        for name in ('askyesno', 'askyesnocancel', 'askokcancel'):
            p = mock.patch.object(rt.hh.messagebox, name, lambda *a, _n=name, **k: box(_n, a))
            p.start()
            self.addCleanup(p.stop)
        self.assertTrue(self.h.run_all())
        self.assertTrue(seen)
        self.assertIn('MEAS', seen[0] + 'READ?')


# ================================================================================================================== rule 12
class Rule12Sections(Base):
    SEC = 'DC volts'

    def ids(self, app, section):
        return [p['id'] for p in app.points if p['section'] == section]

    def test_every_section_starts_automated_and_the_modes_are_listed(self):
        app, io = self.dmm()
        self.assertEqual(set(app.section_mode.values()), {rules.AUTO})
        self.assertEqual(list(app.section_mode), list(dict.fromkeys(p['section'] for p in app.points)))
        self.assertEqual(app.allowed_modes(), rules.MODES)

    def test_not_tested_section_is_not_run_asked_counted_or_failed(self):
        app, io = self.dmm()
        self.assertTrue(app.set_section_mode(self.SEC, rules.SKIP))
        self.assertTrue(self.h.run_all())
        skipped = set(self.ids(app, self.SEC))
        self.assertTrue(skipped)
        self.assertFalse(skipped & set(app.found), 'nothing was run or recorded for it')
        self.assertEqual(len(app.found), len(app.points) - len(skipped))
        self.assertEqual({r['result'] for r in app.found.values()}, {'PASS'})
        self.assertFalse([d for d in self.h.dialogs if d[0] == 'reading' and d[1] in skipped])
        self.assertFalse([d for d in self.h.dialogs if d[0] == 'confirm' and d[2] == 'DC volts'])
        values, tags = app._row(app.by_id[next(iter(skipped))])
        self.assertEqual((values[-1], tags), ('⊘ not tested', ('skipped',)))
        app.update_summary()
        rows = app.shell.set_sections.call_args[0][0]
        row = next(r for r in rows if r[0].startswith(self.SEC))
        self.assertEqual((row[1], row[2], row[3]), (0, 0, 0), 'no pass / fail / pending count for a section that is not tested')
        self.assertIn('(skip)', row[0])
        counts = app.shell.summary.update_counts.call_args[0]
        self.assertEqual(counts[0], len(app.points) - len(skipped))

    def test_report_lists_the_section_as_not_tested_and_prints_no_row_for_it(self):
        app, io = self.dmm()
        app.set_section_mode(self.SEC, rules.SKIP)
        self.assertTrue(self.h.run_all())
        text = self.pdf_text(app)
        n = len(self.ids(app, self.SEC))
        self.assertRegex(text, rf'Not tested:?\s+{self.SEC} \({n} point\(s\)\)')
        self.assertIn('RESULT: PASS', text)
        self.assertNotIn('FAIL', text)
        rows = app.certificate_rows()
        self.assertFalse([r for r in rows if r['Section'] == self.SEC])

    def test_typed_by_hand_section_uses_the_typed_entry_and_drives_nothing(self):
        app, io = self.dmm()
        app.set_section_mode(self.SEC, rules.HAND)
        self.assertTrue(self.h.run_all())
        ids = self.ids(app, self.SEC)
        self.assertTrue(all(app.found[i]['standard'] == 'manual' and app.found[i]['source'] == 'typed' for i in ids))
        self.assertEqual({app.found[i]['result'] for i in ids}, {'PASS'})
        o = outs(H.wire(io))
        self.assertEqual(len(o), len(app.points) - len(ids), 'no output for the hand section')
        self.assertFalse([d for d in self.h.dialogs if d[0] == 'confirm' and d[2] == self.SEC], 'no setup / function prompts for it')
        self.assertEqual(sum(1 for d in self.h.dialogs if d[0] == 'box' and d[2] == 'HIGH VOLTAGE'), 1)
        labels = [d[3] for d in self.h.dialogs if d[0] == 'reading' and d[1] in ids]
        self.assertTrue(labels and set(labels) == {'UNIT UNDER TEST'})
        text = self.pdf_text(app)
        self.assertIn('By hand', text)

    def test_hand_typed_readings_are_padded_and_judged_like_a_manual_calibration(self):
        app, io = self.dmm()
        app.set_section_mode(self.SEC, rules.HAND)
        p = next(q for q in app.points if q['section'] == self.SEC and q['nominal'] == 10.0)
        rec = app.type_reading(p, '10')
        self.assertEqual(rec['entered'], hh_pad(p, '10'))
        self.assertRegex(rec['entered'], r'^10\.0+$')
        self.assertEqual(rec['result'], 'PASS')
        bad = app.type_reading(p, '10.5')
        self.assertEqual(bad['result'], 'FAIL')
        for text, msg in (('', 'Type a reading'), ('abc', 'without the unit'), ('1,5', 'comma'), ('nan', 'Enter a number')):
            with self.assertRaises(ValueError, msg=text):
                app.type_reading(p, text)

    def test_automated_and_not_tested_sections_refuse_the_grid(self):
        app, io = self.dmm()
        a = next(q for q in app.points if q['section'] == self.SEC)
        ok, why = app.grid_allows(a)
        self.assertFalse(ok)
        self.assertIn('Automated', why)
        with self.assertRaises(RuntimeError):
            app.type_reading(a, '1')
        app.set_section_mode(self.SEC, rules.SKIP)
        self.assertIn('Not tested', app.grid_allows(a)[1])
        app.set_section_mode(self.SEC, rules.HAND)
        self.assertTrue(app.grid_allows(a)[0])
        self.assertIsNotNone(app.grid_entry, 'the grid entry is attached to every sheet')

    def test_settings_switch_the_typed_by_hand_sections_off(self):
        import app_settings
        app, io = self.dmm()
        a = next(q for q in app.points if q['section'] == self.SEC)
        app.set_section_mode(self.SEC, rules.HAND)
        self.assertTrue(app.grid_allows(a)[0])
        with mock.patch.object(app_settings, 'get', lambda key, default=None: False if key == app_settings.HAND_SECTIONS else default):
            ok, why = app.grid_allows(a)
            self.assertFalse(ok)
            self.assertIn('File > Settings', why)
            with self.assertRaises(RuntimeError):
                app.type_reading(a, '1')

    def test_changing_the_setting_after_readings_exist_never_discards_points(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        before = json.loads(json.dumps(app.found))
        n = len(before)
        for mode in (rules.HAND, rules.SKIP, rules.AUTO, rules.SKIP):
            self.assertTrue(app.set_section_mode(self.SEC, mode))
            self.assertEqual(app.found, before)
        self.assertEqual(len(app.found), n)
        self.assertEqual(app.not_tested_sections(), [], 'every point of the section has a reading, so none is listed as not tested')
        rows = app.certificate_rows()
        self.assertEqual(len(rows), n, 'the recorded points of a section switched off are still reported')
        text = self.pdf_text(app)
        self.assertNotIn('Not tested', text)
        app.update_summary()
        row = next(r for r in app.shell.set_sections.call_args[0][0] if r[0].startswith(self.SEC))
        self.assertEqual(row[3], len(self.ids(app, self.SEC)))

    def test_partly_recorded_section_switched_off_lists_only_the_rest(self):
        app, io = self.dmm()
        ids = self.ids(app, self.SEC)
        app.execute([app.by_id[i] for i in ids[:4]])
        self.h.pump()
        app.set_section_mode(self.SEC, rules.SKIP)
        self.assertEqual(app.not_tested_sections(), [(self.SEC, len(ids) - 4)])
        self.assertTrue(self.h.run_all())
        self.assertEqual(set(ids) & set(app.found), set(ids[:4]))

    def test_settings_are_saved_in_the_checkpoint_and_restored_on_resume(self):
        app, io = self.dmm()
        app.set_section_mode(self.SEC, rules.SKIP)
        app.set_section_mode('AC volts', rules.HAND)
        app.execute([next(p for p in app.points if p['section'] == 'Capacitance')])
        self.h.pump()
        path = app._checkpoint_path()
        data = json.loads(path.read_text())
        self.assertEqual(data['dsb']['sections'][self.SEC], 'skip')
        self.assertEqual(data['dsb']['sections']['AC volts'], 'hand')
        app2 = self.h.make_app(spec_of(fx.dmm_34461a_like()), io=cal_io())
        self.assertEqual(app2.section_mode[self.SEC], 'auto')
        with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
            app2.load()
        self.assertEqual((app2.section_mode[self.SEC], app2.section_mode['AC volts']), ('skip', 'hand'))
        old = json.loads(path.read_text())
        old['dsb'].pop('sections')
        path.write_text(json.dumps(old))
        app3 = self.h.make_app(spec_of(fx.dmm_34461a_like()), io=cal_io())
        app3.set_section_mode('Frequency', rules.HAND)
        with mock.patch.object(rt.hh.filedialog, 'askopenfilename', lambda **k: str(path)):
            app3.load()
        self.assertEqual(app3.section_mode['Frequency'], 'hand', 'a progress file without settings leaves the window\'s')

    def test_the_setting_cannot_change_during_a_run(self):
        app, io = self.dmm()
        app.busy = True
        self.assertFalse(app.set_section_mode(self.SEC, rules.SKIP))
        self.assertEqual(app.section_mode[self.SEC], 'auto')
        app.busy = False

    def test_run_shown_section_and_rerun_leave_a_not_tested_section_alone(self):
        app, io = self.dmm()
        app.set_section_mode(self.SEC, rules.SKIP)
        app.execute([app.by_id[i] for i in self.ids(app, self.SEC)[:2]])
        self.h.pump()
        self.assertEqual(len(app.found), 0)
        self.assertFalse([d for d in self.h.dialogs if d[0] in ('confirm', 'reading')])

    def test_a_manual_calibration_defaults_to_typed_by_hand_and_cannot_be_automated(self):
        ds = fx.dmm_34461a_like()
        ds.options['manual_entry'] = True
        app = self.h.make_app(spec_of(ds, plan=False))
        self.assertEqual(set(app.section_mode.values()), {rules.HAND})
        self.assertFalse(app.set_section_mode(self.SEC, rules.AUTO))
        self.assertTrue(app.set_section_mode(self.SEC, rules.SKIP))
        self.assertTrue(app.skipped_unrecorded(next(p for p in app.points if p['section'] == self.SEC)))

    def test_label_helpers(self):
        self.assertEqual(rules.normalise_modes({'a': 'skip', 'z': 'hand', 'b': 'bogus'}, ['a', 'b']), {'a': 'skip', 'b': 'auto'})
        self.assertEqual({rules.LABEL_MODE[v] for v in rules.MODE_LABEL.values()}, set(rules.MODES))


def nominal_text(p):
    return f'{p["nominal"] / p["factor"]:.6g}'


def hh_pad(p, text):
    return rt.hh.pad_reading(p, text)


# ================================================================================================================== rule 13
class Rule13Override(Base):
    def typed(self, text):
        return mock.patch.object(ov, 'ask_typed', lambda parent, p, total, **k: ov.parse_typed(p, text))

    def test_parse_uses_the_manual_entry_padding_and_judging(self):
        app, io = self.dmm()
        p = next(q for q in app.points if q['nominal'] == 10.0 and q['section'] == 'DC volts')
        t = ov.parse_typed(p, '10')
        self.assertEqual((t.text, t.result), (hh_pad(p, '10'), 'PASS'))
        self.assertAlmostEqual(t.value, 10.0)
        self.assertEqual(ov.parse_typed(p, '11').result, 'FAIL')
        for bad in ('', 'abc', '1,5', 'nan', 'inf', 'OL', '1e999', '10 V'):
            with self.assertRaises(ValueError, msg=bad):
                ov.parse_typed(p, bad)

    def test_idle_override_replaces_the_reading_and_leaves_the_report_unchanged(self):
        app, io = self.dmm()
        self.assertTrue(self.h.run_all())
        p = next(q for q in app.points if q['nominal'] == 10.0 and q['section'] == 'DC volts')
        old = dict(app.found[p['id']])
        rows_before = json.loads(json.dumps(app.certificate_rows()))
        text_before = self.pdf_text(app)
        same = old['entered']
        with self.typed(same), mock.patch.object(rt.hh.messagebox, 'askyesno', lambda *a, **k: True):
            app.mo_enter_for(p)
        rec = app.found[p['id']]
        self.assertTrue(rec['overridden'])
        self.assertAlmostEqual(rec['auto_reading'], old['reading'])
        self.assertEqual(rec['standard'], old['standard'])
        self.assertEqual(rec['source'], 'typed')
        self.assertEqual(json.loads(json.dumps(app.certificate_rows())), rows_before, 'the report rows are the same with and without the override')
        text_after = self.pdf_text(app)
        self.assertEqual(re.sub(r'\s+', ' ', text_after), re.sub(r'\s+', ' ', text_before))
        for word in ('override', 'Override', 'typed', 'manually'):
            self.assertNotIn(word, text_after)
        line = [e[3] for e in io.log.entries if e[3].startswith('MANUAL OVERRIDE')]
        self.assertEqual(len(line), 1)
        self.assertRegex(line[0], rf'MANUAL OVERRIDE point {re.escape(p["id"])}: auto reading 10 V, entered {re.escape(same)} V = 10 V')
        self.assertIn('MANUAL OVERRIDE', log_file(self.h), 'saved at once')
        self.assertEqual(json.loads(app._checkpoint_path().read_text())['results'][p['id']]['overridden'], True)

    def test_settings_switch_manual_override_off(self):
        import app_settings
        app, io = self.dmm()
        p = app.points[5]
        self.assertTrue(app.mo_state(p)[0])
        with mock.patch.object(app_settings, 'get', lambda key, default=None: False if key == app_settings.MANUAL_OVERRIDE else default):
            self.assertIsNone(app.mo_failed(p, RuntimeError('timeout')), 'a failed automatic reading is not offered a typed one: the run stops as before')
            label, _cmd, enabled, why = app.tree_menu_extras(p['id'])[0]
            self.assertFalse(enabled)
            self.assertIn('File > Settings', why)
            said = []
            with mock.patch.object(ov.port, 'message', lambda *a, **k: said.append(a)), self.typed('10'):
                app.mo_enter_for(p)
            self.assertTrue(said and 'File > Settings' in said[0][2])
            self.assertNotIn(p['id'], app.found)
        self.assertTrue(app.mo_state(p)[0])

    def test_idle_override_of_a_point_not_measured_yet_and_a_failing_value(self):
        app, io = self.dmm()
        p = app.points[5]
        with self.typed('1'), mock.patch.object(rt.hh.messagebox, 'askyesno', lambda *a, **k: True):
            app.mo_enter_for(p)
        rec = app.found[p['id']]
        self.assertEqual(rec['result'], 'FAIL', 'the datasheet\'s limits judge it')
        self.assertTrue(any('auto reading none (point not measured)' in e[3] for e in io.log.entries))
        self.assertEqual(last_write(H.wire(io)), 'STBY', 'standby is made sure of')

    def test_state_refuses_not_tested_sections_yes_no_points_and_other_points_during_a_run(self):
        app, io = self.dmm()
        p = app.points[0]
        self.assertTrue(app.mo_state(p)[0])
        app.set_section_mode(p['section'], rules.SKIP)
        ok, why = app.mo_state(p)
        self.assertFalse(ok)
        self.assertIn('Not tested', why)
        yn = dict(app.points[1], test='visual')
        self.assertIn('Yes / No', app.mo_state(yn)[1])
        app.set_section_mode(p['section'], rules.AUTO)
        app.busy = True
        self.assertFalse(app.mo_state(p)[0])
        app.busy = False
        extras = app.tree_menu_extras(app.points[2]['id'])
        self.assertEqual([e[0] for e in extras], ['Enter reading manually...'])

    def arm_during_the_read(self, app, io, text):
        """Type a reading for the point being read, from inside the read (what the technician does with the right-click menu while the standard is read)."""
        orig = io.measure

        def measure(p, route, refs=None, cancel=None):
            self.assertTrue(app.mo_state(p)[0], 'the point being measured can be entered')
            with self.typed(text), mock.patch.object(rt.hh.messagebox, 'askyesno', lambda *a, **k: True):
                app.mo_enter_for(p)
            return orig(p, route, refs=refs, cancel=cancel)
        io.measure = measure

    def test_typed_while_the_standard_is_read_replaces_the_automatic_reading(self):
        h = self.h
        app = io = bench = None
        bench_models = ('5790B', '53132A')
        app, io, bench = Base.gen(self, bench_models)
        pt = next(p for p in app.points if p['run']['op'] == 'std_level')
        self.arm_during_the_read(app, io, hh_pad(pt, nominal_text(pt)))
        app.execute([pt])
        h.pump()
        rec = app.found[pt['id']]
        self.assertTrue(rec['overridden'])
        self.assertEqual(rec['source'], 'typed')
        self.assertEqual(rec['standard'], '5790B', 'the route is kept: nothing on the report')
        self.assertIsNotNone(rec['auto_reading'])
        self.assertAlmostEqual(rec['auto_reading'], pt['nominal'], delta=pt['nominal'] * 0.01)
        line = [e[3] for e in io.log.entries if e[3].startswith('MANUAL OVERRIDE')]
        self.assertEqual(len(line), 1)
        self.assertIn('auto reading', line[0])

    def test_typed_reading_armed_before_a_failed_read_is_used_instead_of_the_dialog(self):
        app, io, bench = Base.gen(self)
        pt = next(p for p in app.points if p['run']['op'] == 'std_freq')
        orig = self.h.on_confirm

        def wrong(title, heading, steps, facts):
            r = orig(title, heading, steps, facts)
            bench.connected = 'std'                       # the counter sees nothing: its read fails
            return r
        self.h.on_confirm = wrong
        self.arm_during_the_read(app, io, hh_pad(pt, nominal_text(pt)))
        app.execute([pt])
        self.h.pump()
        self.assertTrue(app.found[pt['id']]['overridden'])
        self.assertFalse([d for d in self.h.dialogs if d[0] == 'box' and d[2] == 'Measuring standard'])
        self.assertTrue(any('auto reading none (' in e[3] for e in io.log.entries))

    def test_demo_override_is_synthetic_and_writes_no_log(self):
        app = self.h.make_app(spec_of(fx.dmm_34461a_like()), demo=True)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        p = app.points[3]
        with self.typed(app.found[p['id']]['entered']), mock.patch.object(rt.hh.messagebox, 'askyesno', lambda *a, **k: True):
            app.mo_enter_for(p)
        self.assertTrue(app.found[p['id']]['synthetic'])
        self.assertEqual(app.found[p['id']]['standard'], 'demo')
        self.assertTrue(app.mo_events[0].startswith('MANUAL OVERRIDE point'))
        self.assertTrue(app.mo_events[0].endswith('[As Found, demo]'))
        self.assertEqual(log_file(self.h), '')

    def test_only_the_datasheet_runtime_and_the_8808a_enable_the_override(self):
        """Superseded rule (manual entry on every two-way engine): the datasheet runtime and the 8808A still enable it, and so do the other automatic-reading
        engines. The full list and the exclusions are pinned in test_8808a_manual_override.OnlyThe8808A and test_manual_entry_all_engines.Coverage."""
        hits = sorted(str(p.relative_to(ROOT)).replace('\\', '/') for p in list(ROOT.glob('*.py')) + list((ROOT / 'Procedures').glob('*.py'))
                      if re.search(r'^\s*MANUAL_OVERRIDE\s*=\s*True', p.read_text(encoding='utf-8'), re.M))
        for f in ('dsb_override.py', 'dsb_runtime.py', 'fluke8808a_verification.py'):
            self.assertIn(f, hits)


if __name__ == '__main__':
    unittest.main()
