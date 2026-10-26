"""Tektronix TBS1000C performance verification on the shared Tektronix engine: spec against the manual, driver commands against the TBS1000C
programmer manual (simulated scope), every point of every model on the simulated bench, a virtual (demo) run, report rows, Manager entry.
Run:  python -m unittest tests.test_tbs1000c_points     (no tkinter and no hardware needed: tests/_tk_stub.py stands in for tkinter)"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import cmdreg  # noqa: E402
import drivers  # noqa: E402
from drivers.simulated_tbs import make_tbs1000c_bench  # noqa: E402
from drivers.tektronix_tbs1000c import COMMANDS, TektronixTBS1000C  # noqa: E402
import tds2000c_verification as T  # noqa: E402
import tbs1000_verification as B  # noqa: E402

FAM = B.TBS1000C_FAMILY
SPEC_PATH = ROOT / 'specs' / 'tektronix_tbs1000c_pv.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
POINTS = SPEC['points']

# Written out independently of the JSON, from the TBS1000C Specification and PV manual 077-1583-03 (rendered pages):
# test record p. 24 / DC gain table p. 25: vscale -> (Vdiff nominal, low, high)
GAIN_LIMITS = {0.005: (0.035, 0.03395, 0.03605), 0.2: (1.4, 1.358, 1.442), 2.0: (14.0, 13.58, 14.42)}
BW_MHZ = {'1052C': 50, '1072C': 70, '1102C': 100, '1202C': 200}            # p. 9 model overview; p. 26 step 7; p. 28 step 8; p. 30 step 7


def fake_app(io, model, cal='5560A', stop=False, answer=True, asked=None):
    class FakeApp:
        def __init__(s):
            s.io, s.cfg, s.stop = io, T.Config(model, FAM), stop

        def request(s, kind, payload=None):
            if asked is not None:
                asked.append((kind, payload))
            return answer

        def post(s, *a, **k):
            pass

        def cal_text(s):
            return 'Fluke ' + cal
    return FakeApp()


def wire(log):
    return [t for _ts, _i, d, t in log.entries if d == '>>']


class Spec(unittest.TestCase):
    def test_structure(self):
        self.assertEqual(SPEC['schema'], 2)
        sections = {s['id'] for s in SPEC['sections']}
        self.assertEqual([p['id'] for p in POINTS], list(range(1, len(POINTS) + 1)))
        for p in POINTS:
            self.assertIn(p['section'], sections)
            self.assertIn(p['stim'], ('cal', 'none'))
            self.assertTrue(hasattr(T.Runner, 'do_' + p['kind'].lower()), p['kind'])
            if p.get('passfail'):
                self.assertEqual((p['low'], p['high']), (1, 1))
            elif p['low'] is not None and p['high'] is not None:
                self.assertTrue(p['low'] <= p['nominal'] <= p['high'], p['desc'])
        self.assertEqual(set(SPEC['models']), set(BW_MHZ))
        self.assertEqual({s['id']: s['page'] for s in SPEC['sections']},
                         {'selftest': '24', 'gain': '25', 'bw': '26', 'timebase': '27', 'trig': '27', 'exttrig': '29'})

    def test_model_table(self):
        for m, v in SPEC['models_info'].items():
            self.assertEqual(v['channels'], 2)
            self.assertEqual(v['bw_mhz'], BW_MHZ[m])
            self.assertEqual(v['bw_test_hz'], BW_MHZ[m] * 1e6)
            self.assertEqual(v['trig_hz'], BW_MHZ[m] * 1e6)

    def test_point_counts(self):
        from collections import Counter
        self.assertEqual(Counter(p['section'] for p in POINTS), {'selftest': 2, 'gain': 6, 'bw': 2, 'timebase': 1, 'trig': 2, 'exttrig': 1})
        for m in SPEC['models']:
            self.assertEqual(len([p for p in POINTS if T.Config(m, FAM).applies(p)]), 14)

    def test_gain_limits_match_the_manual_table(self):
        gains = [p for p in POINTS if p['kind'] == 'GAIN']
        self.assertEqual(sorted({p['ch'] for p in gains}), [1, 2])
        for p in gains:
            self.assertEqual((p['nominal'], p['low'], p['high']), GAIN_LIMITS[p['vscale']], p['desc'])
            self.assertAlmostEqual(p['vdiff'], p['vpos'] - p['vneg'], places=12)
            self.assertEqual((p['vpos'], p['vneg']), (p['nominal'] / 2, -p['nominal'] / 2))

    def test_bandwidth_time_base_and_trigger(self):
        bw = [p for p in POINTS if p['kind'] == 'BW']
        self.assertEqual({(p['low'], p['high'], p['unit'], p['ref_hz'], p['ref_low'], p['ref_high'], p['hscale_ref'], p['hscale']) for p in bw},
                         {(2.12, None, 'V', 50e3, 2.98, 3.02, 10e-6, 10e-9)})
        trig = next(p for p in POINTS if p['kind'] == 'TRIG')
        ext = next(p for p in POINTS if p['kind'] == 'EXTTRIG')
        tb = next(p for p in POINTS if p['kind'] == 'TIMEBASE')
        self.assertEqual((tb['low'], tb['high'], tb['unit'], tb['period'], tb['delay'], tb['hscale_set'], tb['hscale_meas'], tb['vscale']),
                         (-2.0, 2.0, 'div', 1e-3, 1e-3, 1e-3, 10e-9, 0.5))                 # the test record's +/-2 div (owner decision)
        self.assertEqual(tb['printed_step_limits'], [-2.5, 2.5])                         # step 13's printed value is kept in the spec
        self.assertIn('test record', T.report_notes(tb, '1102C')[0])
        self.assertIn('+/-2.5 div', T.report_notes(tb, '1102C')[0])
        for p in (trig, ext):                                                            # stricter-than-spec checks: a note for the TBS1202C only
            self.assertTrue(T.report_notes(p, '1202C'), p['desc'])
            self.assertEqual(T.report_notes(p, '1102C'), [], p['desc'])
            self.assertIn('stricter than the specification', T.report_notes(p, '1202C')[0])
        trig = next(p for p in POINTS if p['kind'] == 'TRIG')
        self.assertEqual([(s['freq'], s['meas_vpp'], s['hscale'], s['slope']) for s in trig['stages']],
                         [('10M', 0.5, 20e-9, 'RISe'), ('F', 0.75, 4e-9, 'RISe'), ('150M', 1.0, 4e-9, 'RISe'), ('LAST', 'LAST', 2e-9, 'FALL')])
        self.assertEqual(trig['stages'][2]['models'], ['1202C'])
        ext = next(p for p in POINTS if p['kind'] == 'EXTTRIG')
        self.assertEqual([(s['freq'], s['src_vpp'], s['hscale'], s['slope'], s['check']) for s in ext['stages']],
                         [('10M', 0.3, 20e-9, 'RISe', False), ('BW', 'LAST', 4e-9, 'RISe', True), ('LAST', 'LAST', 2e-9, 'RISe', True),
                          ('LAST', 'LAST', 2e-9, 'FALL', True)])
        self.assertFalse([p for p in POINTS if 'OFFSET' in p['kind'] or 'POSITION' in p['kind']])     # vertical offset accuracy not built (owner)

    def test_builder_reproduces_the_json(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'build_tbs1000c_spec.py'
            script.write_text((ROOT / 'specs' / 'build_tbs1000c_spec.py').read_text(encoding='utf-8'), encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((Path(d) / 'tektronix_tbs1000c_pv.json').read_text(encoding='utf-8')), SPEC)

    def test_judge_at_the_limits(self):
        gain = next(p for p in POINTS if p['kind'] == 'GAIN' and p['vscale'] == 0.005)
        self.assertEqual([T.judge(gain, v) for v in (0.03395, 0.03605, 0.033949, 0.036051)], ['PASS', 'PASS', 'FAIL', 'FAIL'])
        tb = next(p for p in POINTS if p['kind'] == 'TIMEBASE')
        self.assertEqual([T.judge(tb, v) for v in (2.0, -2.0, 2.01, -2.01, 2.4)], ['PASS', 'PASS', 'FAIL', 'FAIL', 'FAIL'])


class Driver(unittest.TestCase):
    def make(self, model='1202C'):
        bench, t = make_tbs1000c_bench(model)
        log = drivers.CommandLog()
        scope = TektronixTBS1000C(t['scope'], log, label='TBS1000C')
        scope.connect()
        return scope, log, bench

    def test_connect_reads_model(self):
        for model in BW_MHZ:
            scope, _log, _b = self.make(model)
            self.assertEqual((scope.model, scope.channels), (model, 2))
        self.assertEqual(TektronixTBS1000C.model_from_idn('TEKTRONIX,TBS1102C,C010203,CF:91.1CT FV:v1.20'), '1102C')
        self.assertEqual(TektronixTBS1000C.model_from_idn('TEKTRONIX,TBS 1102,C0,CF:91.1CT FV:v4'), '')       # a non-C TBS1000 is not this driver

    def test_registry_every_command_has_a_page_and_lints_clean(self):
        self.assertEqual(cmdreg.lint_registry(cmdreg.merge_commands(TektronixTBS1000C)), [])
        for key, cmd in COMMANDS.items():
            self.assertTrue(cmd.verified, key)
            self.assertRegex(cmd.ref, r'077-1691-02, .*p\. \d', key)
        self.assertEqual(COMMANDS['reset'].template, 'FACtory')
        self.assertEqual(COMMANDS['reset'].risk, 'locked')

    def test_a_full_run_sends_only_registered_tbs1000c_commands(self):
        """Every wire string of a whole run is a registered TBS1000C template; none of the TDS / TBS1000 family headers appear."""
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)
        bench, t = make_tbs1000c_bench('1202C')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t, fam=FAM)
        self.addCleanup(io.close)
        io.reset_at_start()
        runner = T.Runner(fake_app(io, '1202C'))
        for p in POINTS:
            runner.run_point(p)
        sent = [t for _ts, label, d, t in io.log.entries if d == '>>' and label == 'TBS1000C']
        patterns = [_template_regex(cmd.template) for cmd in COMMANDS.values()]
        for s in sent:
            self.assertTrue(s == '*IDN?' or any(rx.fullmatch(s) for rx in patterns), s)        # *IDN? is Instrument.identify (p. 100)
        for bad in ('TRIGger:MAIn', 'WFMPre', 'DATa:ENCdg', 'CALibrate:STATUS', 'MEASUrement:IMMed:SOUrce ', 'CH1:PRObe 1'):
            self.assertFalse([s for s in sent if s.startswith(bad)], bad)
        self.assertIn('TRIGger:A:EDGE:SOUrce AUX', sent)                    # Aux In (p. 148), not EXT
        self.assertIn('HORizontal:MAIn:DELay:TIMe 0.001', sent)              # the 1.0000 ms delay (p. 27 step 12) in seconds
        self.assertNotIn('*CAL?', sent[:sent.index('FACtory') + 1])         # the reset never self-calibrates

    def test_every_setting_is_read_back_and_never_rewritten(self):
        scope, log, _b = self.make()
        scope.default_setup()
        scope.channel(1, vscale=0.5)
        scope.timebase(1e-3)
        scope.trigger_edge('CH1')
        sent = wire(log)
        for cmd in ('CH1:SCAle', 'CH1:PRObe:GAIN', 'CH1:OFFSet', 'CH1:BANdwidth', 'HORizontal:MAIn:SCAle', 'HORizontal:RECOrdlength',
                    'TRIGger:A:EDGE:SOUrce', 'TRIGger:A:EDGE:SLOpe', 'TRIGger:A:EDGE:COUPling', 'TRIGger:A:MODe'):
            i = next(k for k, t in enumerate(sent) if t.startswith(cmd + ' '))
            self.assertEqual(sent[i + 1], cmd + '?', cmd)
        real = scope.query
        scope.query = lambda c, *a, **k: '9.000000E+00' if c == 'CH1:SCAle?' else real(c, *a, **k)
        del log.entries[:]
        with self.assertRaises(drivers.InstrumentError):
            scope.set_num('ch.scale.set', 0.25, ch=1)
        self.assertEqual(sum(1 for t in wire(log) if t.startswith('CH1:SCAle ')), 1)

    def test_default_setup_puts_the_trigger_at_the_centre_of_a_2000_point_record(self):
        scope, log, bench = self.make()
        scope.default_setup()
        st = bench.tds_state
        self.assertEqual((st.reclen, st.delay_mode, st.hpct), (2000, 'OFF', 50.0))
        self.assertEqual((scope.RECORD_POINTS, scope.H_DIVS), (2000, 15))
        scope.channel(1, vscale=0.5)
        times, volts = scope.waveform(1)
        self.assertEqual(len(times), 2000)
        self.assertAlmostEqual(times[1000], 0.0, delta=1e-12)

    def test_a_rejected_command_stops(self):
        scope, log, bench = self.make()
        with self.assertRaises(drivers.InstrumentError):
            scope.trigger_edge('CH3')                                       # a two-channel scope rejects CH3: the read-back disagrees
        self.assertEqual(sum(1 for t in wire(log) if t == 'TRIGger:A:EDGE:SOUrce CH3'), 1)     # never re-sent
        scope.send('trig.source.set', source='CH4')
        with self.assertRaises(drivers.InstrumentError):
            scope.check_errors('test')                                      # *ESR? reports the command error


class Engine(unittest.TestCase):
    def setUp(self):
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)

    def run_model(self, model, cal='5560A', bench_setup=None):
        bench, t = make_tbs1000c_bench(model, cal)
        if bench_setup:
            bench_setup(bench)
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke ' + cal), transports=t, fam=FAM)
        self.addCleanup(io.close)
        asked = []
        runner = T.Runner(fake_app(io, model, cal, asked=asked))
        out = {}
        for p in POINTS:
            if not runner.cfg.applies(p):
                continue
            reading, raw = runner.run_point(p)
            out[p['id']] = (reading, raw, T.judge(p, reading))
            self.assertFalse(bench.fluke['operate'], f'calibrator left operating after {p["desc"]}')
        return out, asked, io

    def test_every_model_passes_on_a_good_simulated_scope(self):
        for model in SPEC['models']:
            for cal in ('5560A', '5522A', '5520A'):
                with self.subTest(model=model, cal=cal):
                    out, asked, io = self.run_model(model, cal)
                    self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])
                    self.assertEqual(len(out), 14)
                    titles = [a[1]['title'] for a in asked]
                    self.assertIn('Aux In edge trigger', titles)
                    tb = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'TIMEBASE')
                    self.assertAlmostEqual(tb[0], 0.3, delta=0.05)          # 3 ppm simulated = 0.3 div at 10 ns/div (1 div = 10 ppm)
                    bw = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'BW')
                    self.assertEqual(bw[1]['freq'], BW_MHZ[model] * 1e6)

    def test_trigger_frequencies_follow_the_manual(self):
        out, _asked, _io = self.run_model('1202C')
        trig = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'TRIG')
        self.assertEqual([s['freq'] for s in trig[1]['stages']], [10e6, 200e6, 150e6, 150e6])
        ext = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'EXTTRIG')
        self.assertEqual([s['freq'] for s in ext[1]['stages']], [10e6, 200e6, 200e6, 200e6])
        out, _asked, _io = self.run_model('1072C')
        trig = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'TRIG')
        self.assertEqual([s['freq'] for s in trig[1]['stages']], [10e6, 70e6, 70e6])

    def test_faults_are_reported_as_fail(self):
        cases = [('GAIN', lambda b: setattr(b, 'tds_gain_error', 0.035)), ('BW', lambda b: setattr(b, 'tds_bw_scale', 0.9)),
                 ('TIMEBASE', lambda b: setattr(b, 'tds_ppm', 30.0)), ('TRIG', lambda b: setattr(b, 'tds_trig_fault', 'jitter'))]
        for kind, fault in cases:
            with self.subTest(kind=kind):
                out, _a, _io = self.run_model('1102C', bench_setup=fault)
                self.assertIn('FAIL', [v[2] for i, v in out.items() if POINTS[i - 1]['kind'] == kind])

    def test_stop_and_declined_prompt_leave_the_calibrator_in_standby(self):
        for stop, answer in ((True, True), (False, False)):
            bench, t = make_tbs1000c_bench('1202C')
            io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t, fam=FAM)
            self.addCleanup(io.close)
            with self.assertRaises(T.Stopped):
                T.Runner(fake_app(io, '1202C', stop=stop, answer=answer)).run_point(next(p for p in POINTS if p['kind'] == 'GAIN'))
            self.assertFalse(bench.fluke['operate'])

    def test_reset_at_start_is_factory_then_the_tbs1000c_known_state(self):
        bench, t = make_tbs1000c_bench('1202C')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t, fam=FAM)
        self.addCleanup(io.close)
        io.log.entries.clear()
        io.reset_at_start()
        w = wire(io.log)
        self.assertEqual(w[:3], ['*RST', '*CLS', '*OPC?'])                # the calibrator first
        i = w.index('FACtory')
        self.assertEqual(w[i:i + 5], ['FACtory', '*CLS', '*OPC?', 'HEADer OFF', 'VERBose OFF'])
        self.assertNotIn('*CAL?', w)
        self.assertEqual(bench.tds_state.reclen, 2000)
        self.assertFalse(bench.fluke['operate'])


class VirtualRun(unittest.TestCase):
    """A demo run with the real window code over the simulated TBS1000C and calibrator: synthetic records, virtual command log, no evidence file."""

    def test_virtual_demo_run(self):
        import virtual_harness as VH
        hn = VH.VHarness().start()
        self.addCleanup(hn.stop)
        app = B.TBS1000CApp(hn.root, demo=True)
        app.asset.set('A1')
        app.v_model.set('1102C')
        hn.app = app
        app.run_all()
        self.assertTrue(hn.pump_poll(240))
        self.assertTrue(app.virtual and not app.fast_demo)
        self.assertFalse(hn.boxes('showerror'), hn.boxes('showerror'))
        self.assertEqual(len(app.results), 14)
        self.assertEqual([k for k, r in app.results.items() if r.get('result') != 'PASS'], [])
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))
        self.assertTrue(app.io.log.virtual)
        self.assertIn(('TBS1000C', 'TRIGger:A:EDGE:SOUrce AUX'), VH.wire(app.io))
        self.assertFalse(list(Path(hn.home).rglob('command_log.txt')))
        self.assertTrue(app._checkpoint_path().name.startswith('TBS1102C_A1'))

    def test_demo_runs_with_each_calibrator_choice(self):
        import virtual_harness as VH
        self.assertEqual(T.CAL_CHOICES, ['Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A'])
        for choice in T.CAL_CHOICES:
            with self.subTest(cal=choice):
                hn = VH.VHarness().start()
                try:
                    app = B.TBS1000CApp(hn.root, demo=True)
                    app.asset.set('A1')
                    app.v_model.set('1052C')
                    app.addr['cal_model'].set(choice)
                    hn.app = app
                    app.run_all()
                    self.assertTrue(hn.pump_poll(240))
                    self.assertIn(choice.split()[-1], app.io.cal.idn)        # the simulated calibrator is the one chosen
                    self.assertEqual(len(app.results), 14)
                    self.assertEqual([k for k, r in app.results.items() if r.get('result') != 'PASS'], [])
                finally:
                    hn.stop()

    def test_fast_demo(self):
        import virtual_harness as VH
        hn = VH.VHarness().start()
        self.addCleanup(hn.stop)
        app = B.TBS1000CApp(hn.root, demo=True, fast_demo=True)
        app.asset.set('A1')
        app.v_model.set('1202C')
        hn.app = app
        app.run_all()
        self.assertTrue(hn.pump_poll(60))
        self.assertIsNone(app.io)
        self.assertEqual(len(app.results), 14)
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))


class QtWindow(unittest.TestCase):
    """The TBS1000C on the real Qt window (tds2000c_view_qt, offscreen) and the Qt port: its own title, model list and address label, and a whole
    virtual run through the window.  Skipped without PySide6."""

    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        try:
            import PySide6.QtWidgets  # noqa: F401
        except ImportError:
            self.skipTest('PySide6 not installed')
        import qt_genscope_harness as Q
        self.Q = Q
        self.hn = Q.QtHarness().start()
        self.addCleanup(self.hn.stop)

    def test_window_and_virtual_run(self):
        from PySide6.QtWidgets import QComboBox, QLabel
        app = B.TBS1000CApp(self.hn.root, demo=True)
        self.hn.app = app
        app.v_model.set('1102C')
        app.on_config()
        app.asset.set('A-1')
        self.Q.settle()
        self.assertTrue(self.hn.root.windowTitle().startswith('Tektronix TBS1000C | Performance Verification'))
        lists = [[c.itemText(i) for i in range(c.count())] for c in self.hn.root.findChildren(QComboBox)]
        self.assertIn(['TBS1052C', 'TBS1072C', 'TBS1102C', 'TBS1202C'], lists)
        self.assertIn('TBS1000C (USB)', {w.text() for w in self.hn.root.findChildren(QLabel)})
        app.run_all()
        self.assertTrue(self.hn.pump(240))
        self.assertEqual(len(app.results), 14)
        self.assertEqual([k for k, r in app.results.items() if r.get('result') != 'PASS'], [])
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))
        self.assertEqual(self.hn.prompts, [])                               # every prompt went through the port


class Report(unittest.TestCase):
    def app(self, demo=False):
        a = B.TBS1000CApp.__new__(B.TBS1000CApp)
        a.demo, a.cfg = demo, T.Config('1202C', FAM)
        a._found, a._left = {}, {}
        return a

    def test_rows_and_report_header_name_the_tbs1000c(self):
        a = self.app(demo=True)
        for p in POINTS:
            raw = dict(reading=T.demo_reading(p))
            a.found[str(p['id'])] = dict(reading=raw['reading'], raw=raw, result=T.judge(p, raw['reading']), synthetic=True,
                                         uncertainty=T.uncertainty_text(p, raw), timestamp='t', data='As Found')
        rows = a.certificate_rows()
        self.assertEqual(len(rows), 14)
        self.assertEqual({r['Section'] for r in rows}, set(FAM.section_title.values()))
        self.assertTrue(a.any_synthetic())
        got = {}
        a.asset = type('V', (), {'get': lambda s: 'A1'})()
        a.serial = type('V', (), {'get': lambda s: 'S1'})()
        a.status = type('V', (), {'set': lambda s, v: None})()
        a.root = None
        import report_pdf
        with mock.patch.object(T.port, 'report_details', lambda *a_, **k: {}), \
                mock.patch.object(T.port, 'save_file', lambda **k: os.path.join(tempfile.gettempdir(), k['initialfile'])), \
                mock.patch.object(report_pdf, 'write_calibration_pdf', lambda path, rows, **k: got.update(path=path, rows=rows, **k)), \
                mock.patch.object(report_pdf, 'context_for', lambda app: None):
            a.export_pdf()
        self.assertEqual(got['title'], 'Calibration Data')
        self.assertTrue(got['demo'])
        self.assertIn(('Instrument', 'Tektronix TBS1202C'), got['header'])
        self.assertIn(('Source', 'TBS1000C Specification and Performance Verification 077-1583-03 Rev A'), got['header'])
        noted = [r['Description'] for r in got['rows'] if r['Description'].endswith('(see note)')]
        self.assertEqual(len(noted), 4)                                     # time base, CH1 / CH2 trigger, Aux In (TBS1202C)
        self.assertIn('Notes: (1) Limit +/-2 div taken from the manual test record', got['footer_note'])
        self.assertIn('TBS1202C: Aux In checked at 200 MHz', got['footer_note'])
        self.assertTrue(os.path.basename(got['path']).startswith('A1-'))


class ManagerEntry(unittest.TestCase):
    NAME = 'Tektronix TBS1000C Performance Verification'

    def test_launcher_and_sidecar(self):
        import procscan
        launcher = ROOT / 'Procedures' / 'Tektronix_TBS1000C_Verification.py'
        src = launcher.read_text(encoding='utf-8')
        self.assertIn('tbs1000_verification.main_tbs1000c()', src)
        p = next(p for p in procscan.procs(ROOT) if p.id == 'Tektronix_TBS1000C_Verification')
        self.assertEqual(p.registration[0], self.NAME)
        self.assertFalse(p.seed_verified)                                    # a new procedure starts 'Not verified'
        for f in ('tds2000c_verification.py', 'tbs1000_verification.py', 'drivers/tektronix_tbs1000c.py', 'surprise.py'):
            self.assertIn(f, p.fingerprint_code)

    def test_launcher_imports_without_tkinter(self):
        code = (f"import sys; sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'Procedures')!r}]; sys.modules['tkinter'] = None\n"
                "import importlib.util\n"
                f"s = importlib.util.spec_from_file_location('l', {str(ROOT / 'Procedures' / 'Tektronix_TBS1000C_Verification.py')!r})\n"
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print('OK')")
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])


def _template_regex(template):
    """A registered template as a regex: each {placeholder} matches one token."""
    import re
    parts = re.split(r'\{[^}]*\}', template)
    return re.compile(r'\S+'.join(re.escape(x) for x in parts))


if __name__ == '__main__':
    unittest.main()
