"""Tektronix TDS2000C / TDS1000C-EDU performance verification: spec, driver on the simulated bench, engine run, report rows, Manager entry.
Run:  python -m unittest tests.test_tds2000c     (no tkinter and no hardware needed: tests/_tk_stub.py stands in for tkinter)"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import drivers  # noqa: E402
from drivers.simulated_tds import make_tds_bench  # noqa: E402
import tds2000c_verification as T  # noqa: E402

SPEC_PATH = ROOT / 'specs' / 'tektronix_tds2000c_pv.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
FOUR_CH = ('2004C', '2014C', '2024C')

# Limits written out independently of the JSON (service manual 077-0446-01 test record, pp. 4-2 / 4-4 / 4-5 / 4-6): vscale -> (Vdiff nominal, low, high)
GAIN_LIMITS = {0.005: (0.035, 0.0336, 0.0364), 0.2: (1.4, 1.358, 1.442), 2.0: (14.0, 13.58, 14.42)}


class Spec(unittest.TestCase):
    def test_structure(self):
        self.assertEqual(SPEC['schema'], 2)
        sections = {s['id'] for s in SPEC['sections']}
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
            else:
                self.assertTrue(p['low'] is not None or p['high'] is not None, p['desc'])
        self.assertEqual(set(SPEC['models']), set(SPEC['models_info']))

    def test_every_kind_has_an_executor(self):
        for p in SPEC['points']:
            self.assertTrue(hasattr(T.Runner, 'do_' + p['kind'].lower()), p['kind'])

    def test_point_counts_by_model(self):
        for m in SPEC['models']:
            n = len([p for p in SPEC['points'] if T.Config(m).applies(p)])
            self.assertEqual(n, 2 + 3 * (4 if m in FOUR_CH else 2) + (4 if m in FOUR_CH else 2) + 1 + (4 if m in FOUR_CH else 2) + 1, m)

    def test_gain_limits_match_the_manual_table(self):
        gains = [p for p in SPEC['points'] if p['kind'] == 'GAIN']
        self.assertEqual(len(gains), 12)
        for p in gains:
            nom, lo, hi = GAIN_LIMITS[p['vscale']]
            self.assertEqual((p['nominal'], p['low'], p['high']), (nom, lo, hi), p['desc'])
            self.assertAlmostEqual(p['vdiff'], p['vpos'] - p['vneg'], places=9)
            self.assertAlmostEqual(p['nominal'], p['vdiff'], places=9)

    def test_bandwidth_time_base_and_trigger_limits(self):
        bw = [p for p in SPEC['points'] if p['kind'] == 'BW']
        self.assertEqual({(p['low'], p['high'], p['unit']) for p in bw}, {(2.12, None, 'V')})
        self.assertEqual((bw[0]['ref_low'], bw[0]['ref_high']), (2.98, 3.02))
        tb = [p for p in SPEC['points'] if p['kind'] == 'TIMEBASE']
        self.assertEqual([(p['low'], p['high'], p['unit']) for p in tb], [(-2.0, 2.0, 'div')])
        for p in SPEC['points']:
            if p['kind'] in ('TRIG', 'EXTTRIG', 'SELFTEST', 'SELFCAL'):
                self.assertTrue(p['passfail'])
        self.assertFalse([p for p in SPEC['points'] if 'POSITION' in p['kind']])            # vertical position accuracy was removed on purpose

    def test_model_table(self):
        info = SPEC['models_info']
        self.assertEqual(len(info), 10)
        for m, v in info.items():
            self.assertEqual(v['channels'], 4 if m in FOUR_CH else 2)
            self.assertEqual(v['bw_test_hz'], v['bw_mhz'] * 1e6)
            self.assertEqual(v['trig_hz'], min(v['bw_mhz'], 100) * 1e6)

    def test_builder_reproduces_the_json(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'build_tds2000c_spec.py'
            script.write_text((ROOT / 'specs' / 'build_tds2000c_spec.py').read_text(encoding='utf-8'), encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((Path(d) / 'tektronix_tds2000c_pv.json').read_text(encoding='utf-8')), SPEC)

    def test_judge_uses_the_limits_and_passfail(self):
        gain = next(p for p in SPEC['points'] if p['kind'] == 'GAIN')
        self.assertEqual(T.judge(gain, 0.035), 'PASS')
        self.assertEqual(T.judge(gain, 0.0336), 'PASS')
        self.assertEqual(T.judge(gain, 0.03359), 'FAIL')
        self.assertEqual(T.judge(gain, 0.0365), 'FAIL')
        bw = next(p for p in SPEC['points'] if p['kind'] == 'BW')
        self.assertEqual(T.judge(bw, 2.12), 'PASS')
        self.assertEqual(T.judge(bw, 2.119), 'FAIL')
        self.assertEqual(T.judge(bw, 99.0), 'PASS')
        pf = next(p for p in SPEC['points'] if p['kind'] == 'TRIG')
        self.assertEqual((T.judge(pf, 1.0), T.judge(pf, 0.0)), ('PASS', 'FAIL'))


class Driver(unittest.TestCase):
    def make(self, model='2024C'):
        _bench, t = make_tds_bench(model)
        log = drivers.CommandLog()
        scope = drivers.TektronixTDS2000C(t['scope'], log, label='TDS2000C')
        scope.connect()
        return scope, log

    def test_connect_reads_model_and_channels(self):
        for model, ch in (('2024C', 4), ('1002C-EDU', 2), ('2012C', 2)):
            scope, _log = self.make(model)
            self.assertEqual((scope.model, scope.channels), (model, ch))

    def test_model_from_idn(self):
        self.assertEqual(drivers.TektronixTDS2000C.model_from_idn('TEKTRONIX,TDS 2024C,C012345,CF:91.1CT FV:v24.18'), '2024C')
        self.assertEqual(drivers.TektronixTDS2000C.model_from_idn('TEKTRONIX,TDS1012C-EDU,C0,FV:v1'), '1012C-EDU')

    def test_every_setting_is_read_back(self):
        scope, log = self.make()
        scope.default_setup()
        scope.channel(1, vscale=0.5)
        scope.timebase(1e-3)
        scope.trigger_edge('CH1')
        sent = [t for _ts, _i, d, t in log.entries if d == '>>']
        for cmd in ('CH1:SCAle', 'HORizontal:MAIn:SCAle', 'TRIGger:MAIn:EDGE:SOUrce', 'TRIGger:MAIn:EDGE:SLOpe', 'TRIGger:MAIn:MODe'):
            i = next(k for k, t in enumerate(sent) if t.startswith(cmd + ' '))
            self.assertEqual(sent[i + 1], cmd + '?', cmd)                 # the query follows the set

    def test_a_disagreeing_read_back_raises_and_the_write_is_not_retried(self):
        scope, log = self.make()
        scope.default_setup()
        real = scope.query
        scope.query = lambda c, *a, **k: '9.000000E+00' if c == 'CH1:SCAle?' else real(c, *a, **k)
        del log.entries[:]
        with self.assertRaises(drivers.InstrumentError):
            scope.set_verified('CH1:SCAle', 'CH1:SCAle?', 0.25)
        sent = [t for _ts, _i, d, t in log.entries if d == '>>']
        self.assertEqual(sum(1 for t in sent if t.startswith('CH1:SCAle ')), 1)

    def test_measure_and_waveform(self):
        scope, _log = self.make()
        scope.default_setup()
        scope.channel(1, vscale=0.5)
        times, volts = scope.waveform(1)
        self.assertEqual(len(times), len(volts))
        self.assertGreater(len(volts), 100)


class Engine(unittest.TestCase):
    """The whole procedure against the simulated bench: every point of every model, with the calibrator checked in standby after each."""

    def setUp(self):
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)

    def run_model(self, model, cal='5560A'):
        bench, t = make_tds_bench(model, cal)
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke ' + cal), transports=t)
        self.addCleanup(io.close)
        asked = []

        class FakeApp:
            stop = False

            def __init__(s):
                s.io, s.cfg = io, T.Config(model)

            def request(s, kind, payload=None):
                asked.append((kind, payload))
                return True

            def post(s, *a, **k):
                pass

            def cal_text(s):
                return 'Fluke ' + cal
        runner = T.Runner(FakeApp())
        out = {}
        for p in T.POINTS:
            if not runner.cfg.applies(p):
                continue
            reading, raw = runner.run_point(p)
            out[p['id']] = (reading, raw, T.judge(p, reading))
            self.assertFalse(bench.fluke['operate'], f'calibrator left operating after {p["desc"]}')
        return out, asked, io

    def test_every_model_passes_on_a_good_simulated_scope(self):
        for model in SPEC['models']:
            with self.subTest(model=model):
                out, asked, _io = self.run_model(model)
                self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])
                self.assertEqual(len(out), len([p for p in T.POINTS if T.Config(model).applies(p)]))
                self.assertTrue(asked)                                  # the technician is asked before cables change

    def test_5522a_path(self):
        out, _asked, _io = self.run_model('2024C', '5522A')
        self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])

    def test_a_bad_gain_is_reported_as_fail(self):
        bench, t = make_tds_bench('2012C')
        bench.tds_gain_error = 0.08
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t)
        self.addCleanup(io.close)

        class FakeApp:
            stop = False
            cfg = T.Config('2012C')

            def __init__(s):
                s.io = io

            def request(s, *a, **k):
                return True

            def post(s, *a, **k):
                pass

            def cal_text(s):
                return 'Fluke 5560A'
        p = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        reading, _raw = T.Runner(FakeApp()).run_point(p)
        self.assertEqual(T.judge(p, reading), 'FAIL')

    def test_stop_ends_the_run_before_any_output(self):
        bench, t = make_tds_bench('2024C')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t)
        self.addCleanup(io.close)

        class FakeApp:
            stop = True
            cfg = T.Config('2024C')

            def __init__(s):
                s.io = io

            def request(s, *a, **k):
                return True

            def post(s, *a, **k):
                pass

            def cal_text(s):
                return 'Fluke 5560A'
        with self.assertRaises(T.Stopped):
            T.Runner(FakeApp()).run_point(next(p for p in T.POINTS if p['kind'] == 'GAIN'))
        self.assertFalse(bench.fluke['operate'])

    def test_a_declined_prompt_stops_the_point(self):
        bench, t = make_tds_bench('2024C')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t)
        self.addCleanup(io.close)

        class FakeApp:
            stop = False
            cfg = T.Config('2024C')

            def __init__(s):
                s.io = io

            def request(s, *a, **k):
                return False

            def post(s, *a, **k):
                pass

            def cal_text(s):
                return 'Fluke 5560A'
        with self.assertRaises(T.Stopped):
            T.Runner(FakeApp()).run_point(next(p for p in T.POINTS if p['kind'] == 'GAIN'))
        self.assertFalse(bench.fluke['operate'])


class ResetAtStart(unittest.TestCase):
    """Stage 7 on the TDS procedure: every run (first, re-run, resume) resets the calibrator then the scope before any point; a failure or a declined
    notice ends the run before a point."""

    def setUp(self):
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)

    def make(self, cal='5560A', ask=True):
        bench, t = make_tds_bench('2024C', cal)
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke ' + cal), transports=t)
        self.addCleanup(io.close)
        io.log.entries.clear()
        points_run = []

        class App(T.App):
            def __init__(s):
                s.io, s.stop, s.results = io, False, {}
                s.posted, s.shown, s.errors, s.busy_ = [], [], [], True
                s.demo = False
                s.status = type('V', (), {'set': lambda self, v: None})()

            mode_label = 'As Found'
            busy = property(lambda s: s.busy_, lambda s, v: setattr(s, 'busy_', v))
            def post(s, kind, payload=None): s.posted.append((kind, payload))
            def reset_ask(s, text): s.shown.append(text); return ask
            def _record_threadsafe(s, p, reading, raw, synthetic): points_run.append(p['id'])
            def save(s, silent=False): pass
        app = App()

        class R:
            def __init__(s, a): pass
            def run_point(s, p):
                points_run.append(p['id']); return 0.0, {}
        self.orig_runner = T.Runner
        T.Runner = R
        self.addCleanup(setattr, T, 'Runner', self.orig_runner)
        return bench, io, app, points_run

    def wire(self, io):
        return [t for _ts, _i, d, t in io.log.entries if d == '>>']

    def test_reset_is_first_on_every_run_5560a(self):
        for run in range(2):                                              # first run, then a re-run / resume
            bench, io, app, pts = self.make('5560A')
            bench.fluke.update(operate=True, volts=1.0, scope='VOLT')
            self.assertTrue(app.reset_notice_ok())
            app._worker([T.POINTS[0]])
            w = self.wire(io)
            self.assertEqual(w[:3], ['*RST', '*CLS', '*OPC?'])
            self.assertIn('FACtory', w); self.assertLess(w.index('*RST'), w.index('FACtory'))
            self.assertNotIn('*CAL?', w)
            self.assertEqual(bench.fluke['scope'], 'OFF')
            self.assertFalse(bench.fluke['operate'])
            self.assertIn('Instruments reset to default settings at start: 5560A, TDS2000C', [t for _ts, _i, _d, t in io.log.entries])
            self.assertEqual(set(pts), {T.POINTS[0]['id']})                    # the point ran, after the reset

    def test_reset_5522a_scope_then_engine_selects_scope_again(self):
        bench, io, app, pts = self.make('5522A')
        bench.fluke.update(operate=True, volts=1.0, scope='VOLT')
        app.reset_notice_ok(); app._worker([T.POINTS[0]])
        w = self.wire(io)
        self.assertEqual(w[0], '*RST')
        self.assertIn('SCOPE OFF', w)
        self.assertEqual(bench.fluke['scope'], 'OFF')
        cal = io.cal
        cal.select_scope_dcv('1M')                                         # the procedure's own selection still works from SCOPE OFF
        self.assertEqual(bench.fluke['scope'], 'VOLT')
        self.assertFalse(bench.fluke['operate'])

    def test_failed_reset_stops_before_any_point(self):
        bench, io, app, pts = self.make('5560A')
        bench.fluke.update(operate=True, volts=1.0)
        bench.fail_next = '*RST'
        app.reset_notice_ok(); app._worker([T.POINTS[0]])
        self.assertEqual(pts, [])
        self.assertEqual(self.wire(io).count('*RST'), 1)                  # never retried
        self.assertNotIn('FACtory', self.wire(io))                        # the scope was not reached
        self.assertFalse(bench.fluke['operate'])                          # standby
        self.assertEqual(app.posted[-1][0], 'done')
        self.assertIn('did not reset', str(app.posted[-1][1]))

    def test_scope_reset_failure_stops_before_any_point(self):
        bench, io, app, pts = self.make('5560A')
        io.scope.t.errors = None
        orig = io.scope.t.query
        io.scope.t.query = lambda text: '16' if text.upper().startswith('*ESR') else orig(text)
        app.reset_notice_ok(); app._worker([T.POINTS[0]])
        self.assertEqual(pts, [])
        self.assertIn('did not reset', str(app.posted[-1][1]))

    def test_declined_notice_sends_nothing(self):
        bench, io, app, pts = self.make('5560A', ask=False)
        bench.fluke.update(operate=True, volts=1.0)
        self.assertFalse(app.reset_notice_ok())
        self.assertEqual(self.wire(io), [])
        self.assertTrue(bench.fluke['operate'])
        self.assertFalse(app.busy)
        self.assertIn('TDS2000C', app.shown[0])


class Helpers(unittest.TestCase):
    def test_display_row_scales_for_display_only(self):
        gain = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        nom, lo, hi, rd, unit = T.display_row(gain, 0.0351)
        self.assertEqual(unit, 'mV')
        self.assertEqual((float(nom), float(lo), float(hi)), (35.0, 33.6, 36.4))
        self.assertTrue(rd.startswith('35.1'))
        self.assertEqual(gain['nominal'], 0.035)                         # the spec value is untouched
        tb = next(p for p in T.POINTS if p['kind'] == 'TIMEBASE')
        self.assertEqual(T.display_row(tb, 0.25)[4], 'div')

    def test_parse_out_reply(self):
        self.assertEqual(T.parse_out_reply('3.000E+00,VPP,0E+00,0,5.0E+04'), (3.0, 5e4))
        self.assertEqual(T.parse_out_reply('3.0,V,0,V,50000'), (3.0, 50000.0))
        with self.assertRaises(drivers.InstrumentError):
            T.parse_out_reply('garbage')

    def test_edge_times(self):
        self.assertEqual(len(T.edge_times([0, 1, 2, 3], [0, 0, 1, 1], 'RISe')), 1)
        self.assertAlmostEqual(T.edge_times([0, 1, 2, 3], [0, 0, 1, 1], 'RISe')[0], 1.5)

    def test_hook_image_falls_back_to_none(self):
        path, names = T.hook_image('DCV', 'Fluke 5560A')
        self.assertTrue(path is None or path.is_file())
        self.assertIn('hook_tds2000c_5560A_DCV.png', names)
        self.assertIn('hook_tds2000c_5522A_DCV.png', T.hook_image('DCV', 'Fluke 5522A')[1])


class Report(unittest.TestCase):
    """Report rows and TAR / TUR without a window: the App methods are called on a bare instance."""

    def app(self, demo=False):
        a = T.App.__new__(T.App)
        a.demo, a.cfg = demo, T.Config('2024C')
        a._found, a._left = {}, {}
        return a

    def record(self, a, p, reading, synthetic=False):
        raw = dict(reading=reading)
        a.found[str(p['id'])] = dict(reading=reading, raw=raw, result=T.judge(p, reading), synthetic=synthetic,
                                     uncertainty=T.uncertainty_text(p, raw), timestamp='t', data='As Found')

    def test_rows_keep_the_column_set_and_mark_out_of_tolerance(self):
        a = self.app()
        gain = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        bw = next(p for p in T.POINTS if p['kind'] == 'BW')
        tb = next(p for p in T.POINTS if p['kind'] == 'TIMEBASE')
        trig = next(p for p in T.POINTS if p['kind'] == 'TRIG')
        self.record(a, gain, 0.0400)
        self.record(a, bw, 2.5)
        self.record(a, tb, 0.3)
        self.record(a, trig, 1.0)
        rows = a.certificate_rows()
        self.assertEqual(len(rows), 4)
        for r in rows:
            for col in ('Section', 'Description', 'Nominal', 'Tolerance -', 'Tolerance +', 'UOM', 'As Found', 'OOT', 'As Left', 'Uncertainty'):
                self.assertIn(col, r)
            self.assertEqual(r['As Left'], 'Same')
        self.assertEqual([r['OOT'] for r in rows], ['OOT', '', '', ''])
        self.assertTrue(rows[1]['Nominal'].startswith('>= '))             # one-sided bandwidth limit
        self.assertEqual(rows[3]['As Found'], 'Pass')

    def test_demo_data_is_always_marked_synthetic(self):
        a = self.app(demo=True)
        for p in T.POINTS:
            if a.cfg.applies(p):
                self.record(a, p, T.demo_reading(p), synthetic=True)
        self.assertTrue(a.any_synthetic())
        self.assertTrue(all(r['synthetic'] for r in a.found.values()))
        self.assertTrue(self.app(demo=True).any_synthetic())              # demo mode alone marks the report, even with no records
        self.assertTrue(all(T.judge(p, T.demo_reading(p)) == 'PASS' for p in T.POINTS if a.cfg.applies(p)))

    def test_as_left_is_stored_beside_as_found(self):
        a = self.app()
        gain = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        self.record(a, gain, 0.040)
        a._left[str(gain['id'])] = dict(reading=0.035, raw={}, result='PASS', synthetic=False, uncertainty='N/A', timestamp='t', data='As Left')
        row = a.certificate_rows()[0]
        self.assertEqual(row['OOT'], 'OOT')                                # the As Found result is kept
        self.assertNotEqual(row['As Left'], 'Same')
        self.assertEqual(float(row['As Left']), 35.0)

    def test_tar_tur_is_blank_without_a_scope_entry_and_never_converts_units(self):
        gain = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        pf = next(p for p in T.POINTS if p['kind'] == 'TRIG')
        bw = next(p for p in T.POINTS if p['kind'] == 'BW')
        for p in (gain, pf, bw):
            f = T.tar_tur_fields(p, dict(raw=dict(reading=p['nominal']), uncertainty='N/A', result='PASS'))
            self.assertEqual(f, dict(TAR='', TUR=''))
        self.assertEqual(T.tar_tur_fields(gain, dict(raw=dict(reading=0.035), uncertainty='999 V', result='PASS'))['TUR'], '')   # stored text from elsewhere
        for p in T.POINTS:
            self.assertEqual(T.tar_tur_fields(p, dict(raw=dict(reading=p['nominal']), result='PASS'))['TAR'], '')

    def test_no_csv_export_and_pdf_only(self):
        src = (ROOT / 'tds2000c_verification.py').read_text(encoding='utf-8')
        self.assertFalse(hasattr(T.App, 'export_csv'))
        for word in ('export_csv', 'import csv', '.csv', 'Export CSV'):
            self.assertNotIn(word, src)
        self.assertIn("title='Calibration Data'", src)
        self.assertIn('ui.report_filename(asset)', src)
        self.assertIn('appdata.progress_path', src)
        self.assertNotIn("HERE / 'Procedures' /", src)                      # checkpoints go to the data folder

    def test_uncertainty_text_has_the_old_wording(self):
        gain = next(p for p in T.POINTS if p['kind'] == 'GAIN')
        trig = next(p for p in T.POINTS if p['kind'] == 'TRIG')
        self.assertEqual(T.uncertainty_text(trig, {}), 'N/A')
        text = T.uncertainty_text(gain, dict(reading=0.035))
        self.assertTrue(text == 'N/A' or text.endswith('V'), text)


class ManagerEntry(unittest.TestCase):
    NAME = 'Tektronix TDS2000C / TDS1000C-EDU Performance Verification'

    def test_launcher_exists_and_imports_the_engine(self):
        launcher = ROOT / 'Procedures' / 'Tektronix_TDS2000C_Verification.py'
        self.assertTrue(launcher.is_file())
        src = launcher.read_text(encoding='utf-8')
        self.assertIn('import tds2000c_verification', src)
        self.assertIn('tds2000c_verification.main()', src)

    def test_manager_registers_the_procedure_as_ready(self):
        import sqlite3
        old = os.environ.get('CALSUITE_DATA')
        with tempfile.TemporaryDirectory() as d:
            os.environ['CALSUITE_DATA'] = d
            self.addCleanup(lambda: os.environ.__setitem__('CALSUITE_DATA', old) if old is not None else os.environ.pop('CALSUITE_DATA', None))
            for name in ('appdata', 'Calibration_Procedure_Manager'):
                sys.modules.pop(name, None)
            try:
                import Calibration_Procedure_Manager as M
            except Exception as exc:                                         # the Manager needs a real tkinter
                self.skipTest(f'Manager not importable here: {exc}')
            self.addCleanup(sys.modules.pop, 'Calibration_Procedure_Manager', None)
            M.init_db()
            with sqlite3.connect(M.DB) as conn:
                row = conn.execute('SELECT script_path, enabled, category FROM procedures WHERE name=?', (self.NAME,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(Path(row[0]).as_posix(), 'Procedures/Tektronix_TDS2000C_Verification.py')
            self.assertEqual((row[1], row[2]), (1, 'Oscilloscope'))
            self.assertTrue(M.script_file(row[0]).is_file())                 # so the table shows Ready, not Missing
            self.assertEqual(M.STABLE[self.NAME], 'Tektronix_TDS2000C_Verification.py')


if __name__ == '__main__':
    unittest.main()
