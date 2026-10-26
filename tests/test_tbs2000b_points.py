"""Tektronix TBS2000B performance verification: spec against the manual, the driver on the simulated bench, the engine run, failures, the reset at start,
report rows, a full virtual (demo) run through the window, the Qt window, the Manager registration and the golden transcripts.
Run:  python -m unittest tests.test_tbs2000b_points     (no tkinter and no hardware needed: tests/_tk_stub.py stands in for tkinter; the Qt checks need PySide6)"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

T = tds = drivers = cmdreg = make_tbs_bench = TektronixTBS2000B = None


def setUpModule():
    global T, tds, drivers, cmdreg, make_tbs_bench, TektronixTBS2000B
    spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    stub.install()
    import cmdreg as _c
    import drivers as _d
    import tbs2000b_verification as _T
    import tds2000c_verification as _tds
    from drivers.simulated_tbs2000b import make_tbs_bench as _m
    from drivers.tektronix_tbs2000b import TektronixTBS2000B as _S
    T, tds, drivers, cmdreg, make_tbs_bench, TektronixTBS2000B = _T, _tds, _d, _c, _m, _S


SPEC_PATH = ROOT / 'specs' / 'tektronix_tbs2000b_pv.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
FOUR_CH = ('2074B', '2104B', '2204B')

# Written out independently of the builder, from the rendered pages of 077-1538-03 Rev D (test record pp. 20-21, procedures pp. 23-26).
OFFSET_ROWS = [(0.2, -5, 0.8, 1.8), (0.2, 5, -0.8, -1.8), (5.0, -5, 20.0, 45.0), (5.0, 5, -20.0, -45.0)]          # V/div, position, offset, source (Table 5)
OFFSET_LIMITS = {1.8: (1.76, 1.84), -1.8: (-1.84, -1.76), 45.0: (44.0, 46.0), -45.0: (-46.0, -44.0)}             # source +/- 0.2 div
BW_FREQ = {'2072B': 70e6, '2074B': 70e6, '2102B': 100e6, '2104B': 100e6, '2202B': 200e6, '2204B': 200e6}         # p. 23 step 16


def silence():
    T.SLEEP_SCALE = 0
    tds.SLEEP_SCALE = 0


def restore():
    T.SLEEP_SCALE = 1.0
    tds.SLEEP_SCALE = 1.0


class FakeApp:
    stop = False

    def __init__(self, io, model, cal='5560A', answer=True):
        self.io, self.cfg, self._cal, self.answer, self.asked = io, T.Config(model), cal, answer, []

    def request(self, kind, payload=None):
        self.asked.append(payload)
        return self.answer

    def post(self, *a, **k):
        pass

    def cal_text(self):
        return 'Fluke ' + self._cal


class Spec(unittest.TestCase):
    def test_structure(self):
        self.assertEqual(SPEC['schema'], 2)
        sections = [s['id'] for s in SPEC['sections']]
        self.assertEqual(sections, ['selftest', 'bw', 'offset', 'timebase', 'dcbal'])               # the order of the procedures pp. 22-26
        self.assertEqual([s['page'] for s in SPEC['sections']], ['22', '23', '24', '25', '26'])
        self.assertEqual([p['id'] for p in SPEC['points']], list(range(1, len(SPEC['points']) + 1)))
        for p in SPEC['points']:
            self.assertIn(p['section'], sections)
            self.assertIn(p['stim'], ('cal', 'none'))
            for m in p.get('models', []):
                self.assertIn(m, SPEC['models'])
            if p.get('passfail'):
                self.assertEqual((p['low'], p['high']), (1, 1))
            elif p['low'] is not None and p['high'] is not None:
                self.assertLess(p['low'], p['high'])
                self.assertTrue(p['low'] <= p['nominal'] <= p['high'], p['desc'])
            self.assertTrue(p.get('ch') in (None, 1, 2, 3, 4))
            if (p.get('ch') or 0) > 2:
                self.assertEqual(p['models'], list(FOUR_CH))

    def test_model_table(self):
        info = SPEC['models_info']
        self.assertEqual(list(info), ['2072B', '2074B', '2102B', '2104B', '2202B', '2204B'])            # p. 10 Model overview
        for m, v in info.items():
            self.assertEqual(v['channels'], 4 if m in FOUR_CH else 2)
            self.assertEqual(v['bw_test_hz'], BW_FREQ[m])
            self.assertEqual(v['bw_mhz'] * 1e6, BW_FREQ[m])

    def test_point_counts_by_model(self):
        for m in SPEC['models']:
            n = len([p for p in SPEC['points'] if T.Config(m).applies(p)])
            nch = 4 if m in FOUR_CH else 2
            self.assertEqual(n, 2 + nch + 4 * nch + 1 + nch, m)                                       # 15 (2-channel) / 27 (4-channel)

    def test_every_kind_has_an_executor(self):
        for p in SPEC['points']:
            self.assertTrue(hasattr(T.Runner, 'do_' + p['kind'].lower()), p['kind'])

    def test_limits_match_the_manual(self):
        bw = [p for p in SPEC['points'] if p['kind'] == 'BW']
        self.assertEqual({(p['low'], p['high'], p['unit']) for p in bw}, {(2.12, None, 'V')})
        self.assertEqual({(p['ref_low'], p['ref_high'], p['vscale'], p['hscale']) for p in bw}, {(2.98, 3.02, 0.5, 10e-9)})
        off = [p for p in SPEC['points'] if p['kind'] == 'OFFSET']
        self.assertEqual(len(off), 16)
        for p in off:
            self.assertIn((p['vscale'], p['position'], p['offset'], p['vsrc']), OFFSET_ROWS)
            self.assertEqual((p['low'], p['high']), OFFSET_LIMITS[p['vsrc']])
            self.assertEqual(p['nominal'], p['vsrc'])
            # the trace is displayed at the centre line (p. 59: input minus offset, at the position)
            self.assertEqual(D(str(p['position'])) + (D(str(p['vsrc'])) - D(str(p['offset']))) / D(str(p['vscale'])), 0)
        tb = [p for p in SPEC['points'] if p['kind'] == 'TIMEBASE']
        self.assertEqual([(p['low'], p['high'], p['unit'], p['period'], p['delay'], p['hscale_meas'], p['hscale_set'], p['vscale']) for p in tb],
                         [(-2.5, 2.5, 'div', 1e-3, 1e-3, 10e-9, 1e-3, 0.5)])
        dcb = [p for p in SPEC['points'] if p['kind'] == 'DCBAL']
        self.assertEqual({(p['low'], p['high'], p['unit'], p['vscale'], p['averages'], p['hscale'], p['stim']) for p in dcb},
                         {(-0.021, 0.021, 'V', 0.2, 16, 1e-3, 'none')})
        for p in SPEC['points']:
            if p['kind'] in ('SELFTEST', 'SPC'):
                self.assertTrue(p['passfail'])

    def test_deviations_are_recorded(self):
        bw = next(p for p in SPEC['points'] if p['kind'] == 'BW')
        self.assertEqual(bw['printed'], dict(ref_hz=1e3, hscale_ref=400e-6))
        self.assertEqual((bw['ref_hz'], bw['hscale_ref']), (50e3, 10e-6))
        self.assertIn('1 kHz', bw['note'])
        self.assertEqual(len(SPEC['source']['deviations']), 4)

    def test_builder_reproduces_the_json(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'build_tbs2000b_spec.py'
            script.write_text((ROOT / 'specs' / 'build_tbs2000b_spec.py').read_text(encoding='utf-8'), encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((Path(d) / 'tektronix_tbs2000b_pv.json').read_text(encoding='utf-8')), SPEC)

    def test_judge(self):
        off = next(p for p in T.POINTS if p['kind'] == 'OFFSET')
        self.assertEqual([T.judge(off, v) for v in (1.8, 1.76, 1.84, 1.7599, 1.8401)], ['PASS', 'PASS', 'PASS', 'FAIL', 'FAIL'])
        bw = next(p for p in T.POINTS if p['kind'] == 'BW')
        self.assertEqual([T.judge(bw, v) for v in (2.12, 2.119, 9.0)], ['PASS', 'FAIL', 'PASS'])
        tb = next(p for p in T.POINTS if p['kind'] == 'TIMEBASE')
        self.assertEqual([T.judge(tb, v) for v in (2.5, -2.5, 2.51)], ['PASS', 'PASS', 'FAIL'])
        dcb = next(p for p in T.POINTS if p['kind'] == 'DCBAL')
        self.assertEqual([T.judge(dcb, v) for v in (0.021, -0.0211)], ['PASS', 'FAIL'])


class Driver(unittest.TestCase):
    def make(self, model='2204B'):
        _bench, t = make_tbs_bench(model)
        log = drivers.CommandLog()
        scope = TektronixTBS2000B(t['scope'], log, label='TBS2000B')
        scope.connect()
        return scope, log

    def test_connect_reads_model_and_channels(self):
        for model, ch in (('2204B', 4), ('2072B', 2), ('2104B', 4), ('2102B', 2)):
            scope, _log = self.make(model)
            self.assertEqual((scope.model, scope.channels), (model, ch))

    def test_model_from_idn(self):
        f = TektronixTBS2000B.model_from_idn
        self.assertEqual(f('TEKTRONIX,TBS2104B,C012345,CF:91.1CT FV:v1.3'), '2104B')
        self.assertEqual(f('TEKTRONIX,TBS2104 ,CU10100,CF:91.1CT FV:v2015-12-10_01-00-59rootfs; FPGA:v1.21;'), '2104B')     # the manual's example, p. 121
        self.assertEqual(f('TEKTRONIX,TDS 2024C,C1,FV:v24'), '')

    def test_every_command_is_registered_with_a_page_and_only_the_self_test_wait_is_unverified(self):
        reg = cmdreg.merge_commands(TektronixTBS2000B)
        self.assertEqual(cmdreg.lint_registry(reg), [])
        self.assertEqual(sorted(k for k, c in reg.items() if not c.verified), ['diag.busy'])     # BUSY? as the self-test completion signal: not documented
        for key, cmd in reg.items():
            if cmd.verified:
                self.assertRegex(cmd.ref, r'TBS2000B Series Programmer Manual 077-1149-04 p\. \d+', key)
        self.assertEqual(reg['reset'].template, 'FACtory')
        self.assertEqual(reg['reset'].risk, 'locked')
        self.assertNotIn('*RST', [c.template for c in reg.values()])

    def test_driver_sends_only_registered_commands(self):
        src = (ROOT / 'drivers' / 'tektronix_tbs2000b.py').read_text(encoding='utf-8')
        self.assertNotRegex(src, r'self\.(write|query)\(')

    def test_every_setting_is_read_back(self):
        scope, log = self.make()
        scope.default_setup()
        scope.channel(1, vscale=0.2, position=-5.0, offset=0.8)
        scope.timebase(1e-3)
        scope.delay(1e-3)
        scope.trigger_edge('CH1')
        sent = [t for _ts, _i, d, t in log.entries if d == '>>']
        for cmd in ('CH1:SCAle', 'CH1:OFFSet', 'CH1:POSition', 'CH1:PRObe:GAIN', 'CH1:BANdwidth', 'HORizontal:SCAle', 'HORizontal:DELay:TIMe',
                    'TRIGger:A:EDGE:SOUrce', 'TRIGger:A:EDGE:SLOpe', 'TRIGger:A:EDGE:COUPling', 'TRIGger:A:MODe'):
            i = next(k for k, t in enumerate(sent) if t.startswith(cmd + ' '))
            self.assertEqual(sent[i + 1], cmd + '?', cmd)
        self.assertLess(sent.index('CH1:SCAle 0.2'), sent.index('CH1:OFFSet 0.8'))          # the offset range depends on the scale (p. 59)
        self.assertNotIn('CH1:PRObe 1', sent)                                                # query-only on the TBS2000B (p. 60)

    def test_a_disagreeing_read_back_raises_and_the_write_is_not_retried(self):
        scope, log = self.make()
        real = scope.query
        scope.query = lambda c, *a, **k: '9.000000E+00' if c == 'CH1:SCAle?' else real(c, *a, **k)
        del log.entries[:]
        with self.assertRaises(drivers.InstrumentError):
            scope.channel(1, vscale=0.25)
        sent = [t for _ts, _i, d, t in log.entries if d == '>>']
        self.assertEqual(sum(1 for t in sent if t.startswith('CH1:SCAle ')), 1)

    def test_a_rejected_offset_is_seen(self):
        scope, _log = self.make()
        scope.channel(1, vscale=0.2, position=0.0)
        with self.assertRaises(drivers.InstrumentError):                                   # +20 V is outside the 200 mV/div offset range: not stored, read back 0
            scope.channel(1, vscale=0.2, offset=20.0)

    def test_self_test_is_started_remotely_once_and_waited_for(self):
        scope, log = self.make()
        del log.entries[:]
        ok, text = scope.run_self_test(poll=0.0, settle=0.0)
        self.assertTrue(ok, text)
        sent = [t for _ts, _i, d, t in log.entries if d == '>>']
        self.assertEqual(sent[:3], ['DIAg:LOOP:OPTion ONCE', 'DIAg:SELect ALL', 'DIAg:STATE EXECute'])
        self.assertEqual(sent.count('DIAg:STATE EXECute'), 1)                               # an action: never retried
        self.assertIn('BUSY?', sent)
        self.assertLess(max(i for i, t in enumerate(sent) if t == 'BUSY?'), sent.index('DIAg:RESUlt:FLAg?'))

    def test_waveform_record(self):
        scope, _log = self.make()
        scope.default_setup()
        scope.record_length()
        times, volts = scope.waveform(1)
        self.assertEqual((len(times), len(volts)), (2000, 2000))


class Engine(unittest.TestCase):
    """The whole procedure against the simulated bench: every point of every model, the calibrator checked in standby after each."""

    def setUp(self):
        silence()
        self.addCleanup(restore)

    def bench(self, model='2204B', cal='5560A'):
        bench, t = make_tbs_bench(model, cal)
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke ' + cal), transports=t)
        self.addCleanup(io.close)
        return bench, io

    def run_model(self, model, cal='5560A', bench_setup=None):
        bench, io = self.bench(model, cal)
        if bench_setup:
            bench_setup(bench)
        app = FakeApp(io, model, cal)
        runner = T.Runner(app)
        out = {}
        for p in T.POINTS:
            if not runner.cfg.applies(p):
                continue
            reading, raw = runner.run_point(p)
            out[p['id']] = (reading, raw, T.judge(p, reading))
            self.assertFalse(bench.fluke['operate'], f'calibrator left operating after {p["desc"]}')
        return out, app, io

    def test_every_model_passes_on_a_good_simulated_scope(self):
        for model in SPEC['models']:
            with self.subTest(model=model):
                out, app, _io = self.run_model(model)
                self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])
                self.assertEqual(len(out), len([p for p in T.POINTS if T.Config(model).applies(p)]))
                bw = [v for i, v in out.items() if T.POINTS[i - 1]['kind'] == 'BW']
                self.assertTrue(all(v[1]['freq'] == BW_FREQ[model] and v[1]['ref_hz'] == 50e3 for v in bw))

    def test_5522a_path(self):
        out, _app, _io = self.run_model('2104B', '5522A')
        self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])

    def test_prompts_reuse_the_tds_texts_and_ask_before_every_cable_change(self):
        _out, app, _io = self.run_model('2204B')
        titles = [a['title'] for a in app.asked]
        self.assertNotIn('HIGH VOLTAGE', titles)                                            # owner: no confirmation before the +/-45 V points
        st = next(a for a in app.asked if a['title'] == 'Self test')
        self.assertIn('Do not touch', [lead for lead, _t in st['steps']])
        self.assertEqual(len([t for t in titles if t.startswith('Vertical offset accuracy')]), 4)
        self.assertEqual(len([t for t in titles if t.startswith('Bandwidth')]), 4)
        self.assertEqual(len([t for t in titles if t.startswith('DC balance')]), 4)
        bw = next(a for a in app.asked if a['title'] == 'Bandwidth - CH1')
        self.assertIn(('Connect', 'Calibrator SCOPE output (leveled sine, 50 Ohm) to CH1 through the 50 Ohm BNC cable and the 50 Ohm feedthrough terminator at the scope input.'),
                      bw['steps'])                                                          # the TDS2000C bandwidth text
        off = next(a for a in app.asked if a['title'] == 'Vertical offset accuracy - CH2')
        self.assertIn(('Connect', 'Calibrator SCOPE output to CH2 with the BNC cable (SCOPE volts, 1 MOhm output impedance). No terminator.'), off['steps'])
        self.assertTrue(all(a['image'] is None for a in app.asked))                         # no hook-up diagrams (none supplied)

    def test_failures_are_reported(self):
        cases = [(lambda b: setattr(b, 'tbs_offset_err_v', 0.05), 'OFFSET', 'FAIL'),
                 (lambda b: setattr(b, 'tbs_bw_scale', 0.8), 'BW', 'FAIL'),
                 (lambda b: setattr(b, 'tbs_ppm', 40.0), 'TIMEBASE', 'FAIL'),
                 (lambda b: setattr(b, 'tbs_dc_balance_v', 0.03), 'DCBAL', 'FAIL'),
                 (lambda b: setattr(b, 'tbs_spc_result', 1), 'SPC', 'FAIL'),
                 (lambda b: setattr(b, 'tbs_diag_pass', False), 'SELFTEST', 'FAIL')]
        for setup, kind, want in cases:
            with self.subTest(kind=kind):
                bench, io = self.bench('2072B')
                setup(bench)
                p = next(p for p in T.POINTS if p['kind'] == kind)
                reading, _raw = T.Runner(FakeApp(io, '2072B')).run_point(p)
                self.assertEqual(T.judge(p, reading), want)
                self.assertFalse(bench.fluke['operate'])

    def test_offset_reading_is_what_the_trace_shows(self):
        bench, io = self.bench('2072B')
        bench.tbs_gain_error = 0.0
        bench.tbs_dc_balance_v = 0.0
        bench.tbs_offset_err_v = 0.02                                                       # 0.1 div at 200 mV/div
        p = next(p for p in T.POINTS if p['kind'] == 'OFFSET' and p['vscale'] == 0.2)
        reading, raw = T.Runner(FakeApp(io, '2072B')).run_point(p)
        self.assertAlmostEqual(reading, p['vsrc'] + 0.02, places=4)
        self.assertAlmostEqual(raw['trace_div'], 0.1, places=3)

    def test_stop_and_a_declined_prompt_end_the_point_in_standby(self):
        for stop, answer in ((True, True), (False, False)):
            bench, io = self.bench()
            app = FakeApp(io, '2204B', answer=answer)
            app.stop = stop
            with self.assertRaises(T.Stopped):
                T.Runner(app).run_point(next(p for p in T.POINTS if p['kind'] == 'OFFSET'))
            self.assertFalse(bench.fluke['operate'])


class ResetAtStart(unittest.TestCase):
    """Stage 7: every run resets the calibrator, then the scope (FACtory, never *RST or the SPC), before any point."""

    def setUp(self):
        silence()
        self.addCleanup(restore)

    def make(self, cal='5560A', ask=True):
        bench, t = make_tbs_bench('2204B', cal)
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke ' + cal), transports=t)
        self.addCleanup(io.close)
        io.log.entries.clear()
        points_run = []

        class App(T.App):
            def __init__(s):
                s.io, s.stop, s.results = io, False, {}
                s.posted, s.shown, s.busy_ = [], [], True
                s.demo = False
                s.status = type('V', (), {'set': lambda self, v: None})()

            mode_label = 'As Found'
            busy = property(lambda s: s.busy_, lambda s, v: setattr(s, 'busy_', v))
            def post(s, kind, payload=None): s.posted.append((kind, payload))
            def reset_ask(s, text): s.shown.append(text); return ask
            def _record_threadsafe(s, p, reading, raw, synthetic): points_run.append(p['id'])
            def save(s, silent=False): pass

        class R:
            def __init__(s, a): pass
            def run_point(s, p):
                points_run.append(p['id']); return 0.0, {}
        orig = T.Runner
        T.Runner = R
        self.addCleanup(setattr, T, 'Runner', orig)
        return bench, io, App(), points_run

    def wire(self, io):
        return [t for _ts, _i, d, t in io.log.entries if d == '>>']

    def test_reset_is_first_on_every_run(self):
        for _run in range(2):
            bench, io, app, pts = self.make()
            bench.fluke.update(operate=True, volts=1.0, scope='VOLT')
            self.assertTrue(app.reset_notice_ok())
            app._worker([T.POINTS[0]])
            w = self.wire(io)
            self.assertEqual(w[:3], ['*RST', '*CLS', '*OPC?'])
            self.assertIn('FACtory', w)
            self.assertLess(w.index('*RST'), w.index('FACtory'))
            self.assertNotIn('*CAL?', w)
            self.assertEqual(bench.fluke['scope'], 'OFF')
            self.assertFalse(bench.fluke['operate'])
            self.assertIn('Instruments reset to default settings at start: 5560A, TBS2000B', [t for _ts, _i, _d, t in io.log.entries])
            self.assertEqual(set(pts), {T.POINTS[0]['id']})                                # the point ran (and was recorded), after the reset

    def test_failed_reset_stops_before_any_point(self):
        bench, io, app, pts = self.make()
        bench.fluke.update(operate=True, volts=1.0)
        bench.fail_next = '*RST'
        app.reset_notice_ok(); app._worker([T.POINTS[0]])
        self.assertEqual(pts, [])
        self.assertEqual(self.wire(io).count('*RST'), 1)
        self.assertNotIn('FACtory', self.wire(io))
        self.assertFalse(bench.fluke['operate'])
        self.assertIn('did not reset', str(app.posted[-1][1]))

    def test_declined_notice_sends_nothing(self):
        bench, io, app, pts = self.make(ask=False)
        self.assertFalse(app.reset_notice_ok())
        self.assertEqual(self.wire(io), [])
        self.assertIn('TBS2000B', app.shown[0])

    def test_the_worker_resets_before_the_first_point(self):
        tree = ast.parse((ROOT / 'tbs2000b_verification.py').read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_worker')
        calls = sorted((n.lineno, n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', '')) for n in ast.walk(fn) if isinstance(n, ast.Call))
        names = [c for _l, c in calls]
        self.assertLess(names.index('reset_run'), names.index('run_point'))


class Report(unittest.TestCase):
    def app(self, demo=False, model='2204B'):
        a = T.App.__new__(T.App)
        a.demo, a.cfg = demo, T.Config(model)
        a._found, a._left = {}, {}
        return a

    def record(self, a, p, reading, synthetic=False):
        raw = dict(reading=reading, applied=p.get('vsrc'))
        a.found[str(p['id'])] = dict(reading=reading, raw=raw, result=T.judge(p, reading), synthetic=synthetic,
                                     uncertainty=T.uncertainty_text(p, raw), timestamp='t', data='As Found')

    def test_rows_and_out_of_tolerance(self):
        a = self.app()
        picks = [next(p for p in T.POINTS if p['kind'] == k) for k in ('SELFTEST', 'BW', 'OFFSET', 'TIMEBASE', 'DCBAL')]
        for p, v in zip(picks, (1.0, 2.5, 1.9, 0.3, 0.0)):
            self.record(a, p, v)
        rows = a.certificate_rows()
        self.assertEqual(len(rows), 5)
        for r in rows:
            for col in ('Section', 'Description', 'Nominal', 'Tolerance -', 'Tolerance +', 'UOM', 'As Found', 'OOT', 'As Left', 'Uncertainty'):
                self.assertIn(col, r)
        self.assertEqual([r['OOT'] for r in rows], ['', '', 'OOT', '', ''])
        self.assertTrue(rows[1]['Nominal'].startswith('>= '))
        self.assertEqual(rows[0]['As Found'], 'Pass')
        self.assertEqual(rows[3]['UOM'], 'div')

    def test_uncertainty_and_tur(self):
        off = next(p for p in T.POINTS if p['kind'] == 'OFFSET' and p['vsrc'] == 45.0)
        import report_pdf
        sc = report_pdf.scope()
        if sc is None:
            self.skipTest('no lab scope file')
        want = sc.oscilloscope('offset', volts=45.0, impedance='1M')[0]
        parts = T.uncertainty_parts(off, {})
        self.assertEqual(parts, (want, 'V', 'si'))
        text = T.uncertainty_text(off, {})
        self.assertTrue(text.endswith('V'), text)
        f = T.tar_tur_fields(off, dict(raw={}, uncertainty=text, result='PASS'))
        self.assertEqual(f['TAR'], '')
        self.assertTrue(f['TUR'], f)
        for kind in ('TIMEBASE', 'DCBAL', 'SPC', 'SELFTEST'):
            p = next(p for p in T.POINTS if p['kind'] == kind)
            self.assertEqual(T.uncertainty_text(p, {}), 'N/A')
            self.assertEqual(T.tar_tur_fields(p, dict(raw={}, result='PASS')), dict(TAR='', TUR=''))

    def test_demo_data_is_always_marked_synthetic(self):
        a = self.app(demo=True)
        for p in T.POINTS:
            if a.cfg.applies(p):
                self.record(a, p, T.demo_reading(p), synthetic=True)
        self.assertTrue(a.any_synthetic())
        self.assertTrue(all(T.judge(p, T.demo_reading(p)) == 'PASS' for p in T.POINTS))

    def test_pdf_only_calibration_data_named_by_asset(self):
        src = (ROOT / 'tbs2000b_verification.py').read_text(encoding='utf-8')
        for word in ('export_csv', 'import csv', '.csv', 'Export CSV'):
            self.assertNotIn(word, src)
        self.assertIn("title='Calibration Data'", src)
        self.assertIn('ui.report_filename(asset)', src)
        self.assertIn('appdata.progress_path', src)
        self.assertIn('import ui_theme_core as ui', src)
        self.assertNotIn('import ui_theme\n', src)


class VirtualRun(unittest.TestCase):
    """The demo through the real App and the Tk view (stubbed): simulated instruments, real driver code, synthetic records, no evidence file."""

    def setUp(self):
        import faulthandler
        import virtual_harness as VH
        self.VH = VH
        faulthandler.dump_traceback_later(240, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.hn = VH.VHarness().start()
        self.addCleanup(self.hn.stop)

    def test_virtual_run_every_point_passes_and_is_demo_data(self):
        app = T.App(self.hn.root, demo=True)
        app.asset.set('A1')
        app.v_model.set('2104B')
        app.on_config(save=False)
        self.hn.app = app
        app.run_all()
        self.assertTrue(self.hn.pump_poll(200))
        self.assertTrue(app.virtual and not app.fast_demo)
        self.assertFalse(self.hn.boxes('showerror'), self.hn.boxes('showerror'))
        self.assertEqual(len(app.results), 27)
        self.assertEqual({r['result'] for r in app.results.values()}, {'PASS'})
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))
        self.assertTrue(app.io.log.virtual)
        self.assertTrue(self.VH.wire(app.io))
        self.assertFalse(list(Path(self.hn.home).rglob('command_log.txt')))

    def test_fast_demo_sends_nothing(self):
        app = T.App(self.hn.root, demo=True, fast_demo=True)
        app.asset.set('A1')
        app.v_model.set('2072B')
        app.on_config(save=False)
        self.hn.app = app
        app.run_all()
        self.assertIsNone(app.io)
        self.assertEqual(len(app.results), 15)
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class QtWindow(unittest.TestCase):
    """The Qt window (tbs2000b_view_qt) on a real offscreen QMainWindow: built, model box, and a whole virtual run through the real Qt port timers."""

    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import qt_genscope_harness as Q
        self.Q = Q
        self.hn = Q.QtHarness().start()
        self.addCleanup(self.hn.stop)

    def test_window_and_virtual_run(self):
        app = T.App(self.hn.root, demo=True)
        self.hn.app = app
        box = app.cfg_widgets[0]
        self.assertEqual([box.itemText(i) for i in range(box.count())], ['TBS' + m for m in SPEC['models']])
        self.assertIn('TBS2000B', self.hn.root.windowTitle())
        box.setCurrentIndex(0)
        box.activated.emit(0)
        self.Q.settle()
        self.assertEqual(app.cfg.model, '2072B')
        app.asset.set('Q1')
        app.run_all()
        self.assertTrue(self.hn.pump(200))
        self.assertEqual(len(app.results), 15)
        self.assertEqual({r['result'] for r in app.results.values()}, {'PASS'})
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))


class FindInstruments(unittest.TestCase):
    def test_the_tbs2000b_is_recognised_and_its_driver_accepts_the_reply(self):
        import instrument_scan as S
        for reply in ('TEKTRONIX,TBS2104 ,CU10100,CF:91.1CT FV:v2015-12-10_01-00-59rootfs; FPGA:v1.21;', 'TEKTRONIX,TBS2072B,C0,CF:91.1CT FV:v1.3',
                      'TEKTRONIX,TBS2204B,SIM0001,CF:91.1CT FV:v1.30'):
            fam = S.match_family(S.parse_identity(reply))
            self.assertEqual(fam.key, 'TBS2000B', reply)
            self.assertIs(getattr(drivers, fam.driver), TektronixTBS2000B)
            self.assertTrue(any(m in reply.upper() for m in TektronixTBS2000B.IDN_MATCH))
            self.assertFalse(fam.serial_ok)
        for other in ('TEKTRONIX,TDS 2024C,C1,FV:v24', 'TEKTRONIX,TBS1102C,C1,FV:v1', 'TEKTRONIX,TBS2105,C1,FV'):
            fam = S.match_family(S.parse_identity(other))
            self.assertTrue(fam is None or fam.key != 'TBS2000B', other)


class ManagerEntry(unittest.TestCase):
    NAME = 'Tektronix TBS2000B Performance Verification'

    def test_launcher_and_sidecar(self):
        import procscan
        launcher = ROOT / 'Procedures' / 'Tektronix_TBS2000B_Verification.py'
        src = launcher.read_text(encoding='utf-8')
        self.assertIn('import tbs2000b_verification', src)
        self.assertIn('tbs2000b_verification.main()', src)
        p = next(p for p in procscan.procs(ROOT) if p.launcher_name == 'Tektronix_TBS2000B_Verification.py')
        self.assertEqual(p.registration, (self.NAME, 'Tektronix', 'TBS2000B', 'Oscilloscope', 'Tektronix_TBS2000B_Verification.py'))
        self.assertFalse(p.seed_verified)                                                   # a new procedure starts 'Not verified'
        self.assertEqual(procscan.classify(p.name, p.category, getattr(p, 'kind', '')), procscan.KIND_VERIFICATION)
        for f in p.fingerprint_code:
            self.assertTrue((ROOT / f).is_file(), f)

    def test_launcher_imports_without_tkinter(self):
        code = ('import sys, importlib.util; sys.path[:0] = [%r, %r]; sys.modules["tkinter"] = None\n'
                'spec = importlib.util.spec_from_file_location("p", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print("OK")'
                % (str(ROOT), str(ROOT / 'Procedures'), str(ROOT / 'Procedures' / 'Tektronix_TBS2000B_Verification.py')))
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])


class Golden(unittest.TestCase):
    """The recorded TBS2000B transcripts match a fresh capture (the whole set is compared by tests/test_golden_commands.py)."""

    def test_tbs2000b_fixtures_match(self):
        from tests import golden_capture as gc
        with gc.pinned():
            c = gc.Case('tektronix_tbs2000b')
            gc.DRIVER_CASES['tektronix_tbs2000b'](c)
        self.assertEqual((gc.GOLDEN / 'tektronix_tbs2000b.json').read_text(encoding='utf-8'), gc.fixture_text('tektronix_tbs2000b', c.entries))
        eng = gc.capture_engine_transcripts(('tbs2000b',))['tbs2000b']
        self.assertEqual((gc.GOLDEN / 'engine_tbs2000b.json').read_text(encoding='utf-8'), gc.fixture_text('engine_tbs2000b', eng))


if __name__ == '__main__':
    unittest.main()
