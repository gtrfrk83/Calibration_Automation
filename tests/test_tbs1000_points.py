"""Tektronix TBS1000 (non-C) performance verification on the shared Tektronix engine: spec against the TBS1000 service manual, the driver (the
TDS2000C driver with TBS identification) against the 077-0444-03 programmer manual, every point of every model on the simulated bench, a virtual
(demo) run, report rows, Manager entry.
Run:  python -m unittest tests.test_tbs1000_points     (no tkinter and no hardware needed: tests/_tk_stub.py stands in for tkinter)"""
import importlib.util
import json
import os
import re
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
from drivers.simulated_tbs import make_tbs1000_bench  # noqa: E402
from drivers.tektronix_tbs1000 import COMMAND_PAGES, TektronixTBS1000  # noqa: E402
import tds2000c_verification as T  # noqa: E402
import tbs1000_verification as B  # noqa: E402

FAM = B.TBS1000_FAMILY
SPEC = json.loads((ROOT / 'specs' / 'tektronix_tbs1000_pv.json').read_text(encoding='utf-8'))
POINTS = SPEC['points']

# Written out independently of the JSON, from the TBS1000 service manual 077-0772-01 Rev D (rendered pages): DC gain table p. 4-4 / test record p. 4-2
GAIN_LIMITS = {0.005: (0.035, 0.0336, 0.0364), 0.2: (1.4, 1.358, 1.442), 2.0: (14.0, 13.58, 14.42)}
# model -> (channels p. 1-1, bandwidth MHz p. 1-4 / 4-5, channel-trigger frequency MHz p. 4-8 step 8)
MODELS = {'1022': (2, 25, 25), '1042': (2, 40, 40), '1062': (2, 60, 60), '1064': (4, 60, 60), '1102': (2, 100, 100), '1104': (4, 100, 100),
          '1152': (2, 150, 100), '1154': (4, 150, 100)}


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
    def test_structure_and_model_table(self):
        self.assertEqual(SPEC['schema'], 2)
        self.assertEqual([p['id'] for p in POINTS], list(range(1, len(POINTS) + 1)))
        for p in POINTS:
            self.assertTrue(hasattr(T.Runner, 'do_' + p['kind'].lower()), p['kind'])
            for m in p.get('models', []):
                self.assertIn(m, SPEC['models'])
        self.assertEqual(set(SPEC['models']), set(MODELS))
        for m, (ch, bw, trig) in MODELS.items():
            v = SPEC['models_info'][m]
            self.assertEqual((v['channels'], v['bw_mhz'], v['bw_test_hz'], v['trig_hz']), (ch, bw, bw * 1e6, trig * 1e6), m)
        self.assertEqual({s['id']: s['page'] for s in SPEC['sections']},
                         {'selftest': '4-3', 'gain': '4-3', 'bw': '4-5', 'timebase': '4-6', 'trig': '4-7', 'exttrig': '4-9'})

    def test_point_counts_by_model(self):
        for m, (ch, _bw, _t) in MODELS.items():
            self.assertEqual(len([p for p in POINTS if T.Config(m, FAM).applies(p)]), 2 + 3 * ch + ch + 1 + ch + 1, m)

    def test_gain_limits_match_the_manual_table(self):
        gains = [p for p in POINTS if p['kind'] == 'GAIN']
        self.assertEqual(len(gains), 12)
        for p in gains:
            self.assertEqual((p['nominal'], p['low'], p['high']), GAIN_LIMITS[p['vscale']], p['desc'])
            self.assertEqual(p.get('models'), ['1064', '1104', '1154'] if p['ch'] > 2 else None)

    def test_bandwidth_time_base_and_trigger(self):
        bw = [p for p in POINTS if p['kind'] == 'BW']
        self.assertEqual({(p['low'], p['high'], p['ref_low'], p['ref_high'], p['hscale']) for p in bw}, {(2.12, None, 2.98, 3.02, 10e-9)})
        tb = next(p for p in POINTS if p['kind'] == 'TIMEBASE')
        self.assertEqual((tb['low'], tb['high'], tb['period'], tb['delay'], tb['hscale_set'], tb['hscale_meas']), (-2.0, 2.0, 10e-3, 10e-3, 1e-3, 250e-9))
        trig = next(p for p in POINTS if p['kind'] == 'TRIG')
        self.assertEqual([(s['freq'], s['meas_vpp'], s['hscale'], s['slope']) for s in trig['stages']],
                         [('10M', 0.5, 25e-9, 'RISe'), ('F', 0.75, 5e-9, 'RISe'), ('150M', 1.0, 5e-9, 'RISe'), ('LAST', 'LAST', 2.5e-9, 'FALL')])
        self.assertEqual(trig['stages'][2]['models'], ['1152', '1154'])
        ext = next(p for p in POINTS if p['kind'] == 'EXTTRIG')
        self.assertEqual([(s['freq'], s['src_vpp'], s['hscale'], s['slope'], s['check']) for s in ext['stages']],
                         [('10M', 0.3, 25e-9, 'RISe', False), ('BW', 'LAST', 5e-9, 'RISe', True), ('LAST', 'LAST', 2.5e-9, 'RISe', True),
                          ('LAST', 'LAST', 2.5e-9, 'FALL', True)])                                 # step 10 misprint (5 ns/div) corrected, owner decision
        self.assertEqual(ext['stages'][2]['printed_hscale'], 5e-9)
        notes = T.report_notes(ext, '1104')
        self.assertEqual(len(notes), 1)
        self.assertIn('prints 5 ns/div', notes[0])
        self.assertIn('corrected to 2.5 ns/div', notes[0])
        self.assertEqual(len(T.report_notes(ext, '1154')), 2)                         # + the stricter-than-spec 150 MHz level
        self.assertIn('stricter than the specification', T.report_notes(ext, '1154')[1])
        self.assertIn('10 ms/div', T.report_notes(bw[0], '1102')[0])
        self.assertNotIn('TBS1052', SPEC['models'])                                      # only in the trigger-source table: nothing to build
        self.assertIn('TBS1052', json.dumps(SPEC['flags']))

    def test_builder_reproduces_the_json(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / 'build_tbs1000_spec.py'
            script.write_text((ROOT / 'specs' / 'build_tbs1000_spec.py').read_text(encoding='utf-8'), encoding='utf-8')
            r = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads((Path(d) / 'tektronix_tbs1000_pv.json').read_text(encoding='utf-8')), SPEC)


class Driver(unittest.TestCase):
    def make(self, model='1104'):
        _bench, t = make_tbs1000_bench(model)
        log = drivers.CommandLog()
        scope = TektronixTBS1000(t['scope'], log, label='TBS1000')
        scope.connect()
        return scope, log

    def test_connect_reads_model_and_channels(self):
        for model, (ch, _bw, _t) in MODELS.items():
            scope, _log = self.make(model)
            self.assertEqual((scope.model, scope.channels), (model, ch))
        self.assertEqual(TektronixTBS1000.model_from_idn('TEKTRONIX,TBS 1154,C010101,CF:91.1CT FV:v4.00'), '1154')
        for other in ('TEKTRONIX,TBS 1102B,C0,CF:91.1CT FV:v1', 'TEKTRONIX,TBS1102C,C0,CF:91.1CT FV:v1', 'TEKTRONIX,TDS 2024C,C0,FV:v1'):
            self.assertEqual(TektronixTBS1000.model_from_idn(other), '', other)

    def test_same_wire_text_as_the_tds2000c_driver(self):
        """The TBS1000 driver adds no method that sends anything: it is the TDS2000C driver (same programmer manual)."""
        own = {n for n, v in vars(TektronixTBS1000).items() if callable(v) or isinstance(v, staticmethod)}
        self.assertEqual(own, {'connect', 'model_from_idn'})
        self.assertTrue(issubclass(TektronixTBS1000, drivers.TektronixTDS2000C))
        reg = cmdreg.merge_commands(TektronixTBS1000)
        self.assertEqual(reg['reset'].template, 'FACtory')
        self.assertTrue(all(c.verified and '077-0444-03' in c.ref for c in reg.values()))
        tds = cmdreg.merge_commands(drivers.TektronixTDS2000C)          # owner-approved: the TDS2000C's reset / *OPC? / *CLS are verified (077-0444-03)
        self.assertEqual({k: (c.template, c.verified) for k, c in tds.items()},
                         {'reset': ('FACtory', True), 'opc.query': ('*OPC?', True), 'status.clear': ('*CLS', True)})
        for key, page in (('reset', 'pp. 2-86 / 2-87'), ('opc.query', 'p. 2-152'), ('status.clear', 'p. 2-58')):
            self.assertIn('077-0444-03', tds[key].ref)
            self.assertIn(page, tds[key].ref)

    def test_every_command_of_a_full_run_has_a_checked_manual_page(self):
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)
        bench, t = make_tbs1000_bench('1154')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t, fam=FAM)
        self.addCleanup(io.close)
        io.reset_at_start()
        runner = T.Runner(fake_app(io, '1154'))
        for p in POINTS:
            if runner.cfg.applies(p):
                runner.run_point(p)
        sent = {t for _ts, label, d, t in io.log.entries if d == '>>' and label == 'TBS1000'}
        heads = []
        for key, (page, ok, _note) in COMMAND_PAGES.items():
            self.assertTrue(ok, key)
            self.assertRegex(page, r'^2-\d+')
            for part in key.split(' / '):
                heads.append(re.compile(re.escape(part.split(' ')[0].rstrip('?')).replace('<x>', r'\d') + r'\??$'))     # the set and its read-back
        for s in sorted(sent):
            self.assertTrue(any(h.match(s.split(' ')[0]) for h in heads), s)
        self.assertIn('TRIGger:MAIn:EDGE:SOUrce EXT', sent)
        self.assertIn('HORizontal:MAIn:POSition 0.01', sent)               # the 10.00 ms delay (p. 4-6 step 8) in seconds


class Engine(unittest.TestCase):
    def setUp(self):
        T.SLEEP_SCALE = 0
        self.addCleanup(setattr, T, 'SLEEP_SCALE', 1.0)

    def run_model(self, model, cal='5560A', bench_setup=None):
        bench, t = make_tbs1000_bench(model, cal)
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
        return out, asked

    def test_every_model_passes_on_a_good_simulated_scope(self):
        for model in MODELS:
            for cal in ('5560A', '5522A', '5520A'):
                with self.subTest(model=model, cal=cal):
                    out, asked = self.run_model(model, cal)
                    self.assertEqual([i for i, v in out.items() if v[2] != 'PASS'], [])
                    self.assertIn('External edge trigger', [a[1]['title'] for a in asked])

    def test_trigger_frequencies_follow_the_manual(self):
        out, _a = self.run_model('1154')
        trig = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'TRIG')
        self.assertEqual([s['freq'] for s in trig[1]['stages']], [10e6, 100e6, 150e6, 150e6])
        ext = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'EXTTRIG')
        self.assertEqual([s['freq'] for s in ext[1]['stages']], [10e6, 150e6, 150e6, 150e6])
        out, _a = self.run_model('1042')
        trig = next(v for i, v in out.items() if POINTS[i - 1]['kind'] == 'TRIG')
        self.assertEqual([s['freq'] for s in trig[1]['stages']], [10e6, 40e6, 40e6])

    def test_faults_are_reported_as_fail(self):
        cases = [('GAIN', lambda b: setattr(b, 'tds_gain_error', 0.05)), ('BW', lambda b: setattr(b, 'tds_bw_scale', 0.9)),
                 ('TIMEBASE', lambda b: setattr(b, 'tds_ppm', 60.0)), ('TRIG', lambda b: setattr(b, 'tds_trig_fault', 'jitter'))]
        for kind, fault in cases:
            with self.subTest(kind=kind):
                out, _a = self.run_model('1102', bench_setup=fault)
                self.assertIn('FAIL', [v[2] for i, v in out.items() if POINTS[i - 1]['kind'] == kind])

    def test_reset_at_start_is_factory_not_rst(self):
        bench, t = make_tbs1000_bench('1104')
        io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=t, fam=FAM)
        self.addCleanup(io.close)
        io.log.entries.clear()
        io.reset_at_start()
        w = wire(io.log)
        self.assertEqual(w[:3], ['*RST', '*CLS', '*OPC?'])
        self.assertIn('FACtory', w)
        self.assertEqual([x for x in w if x.startswith('*RST')], ['*RST'])    # only the calibrator's
        self.assertNotIn('*CAL?', w)
        self.assertFalse(bench.fluke['operate'])


class VirtualRun(unittest.TestCase):
    def test_virtual_demo_run(self):
        import virtual_harness as VH
        hn = VH.VHarness().start()
        self.addCleanup(hn.stop)
        app = B.TBS1000App(hn.root, demo=True)
        app.asset.set('A1')
        app.v_model.set('1154')
        hn.app = app
        app.run_all()
        self.assertTrue(hn.pump_poll(240))
        self.assertTrue(app.virtual and not app.fast_demo)
        self.assertFalse(hn.boxes('showerror'), hn.boxes('showerror'))
        self.assertEqual(len(app.results), 2 + 12 + 4 + 1 + 4 + 1)
        self.assertEqual([k for k, r in app.results.items() if r.get('result') != 'PASS'], [])
        self.assertTrue(all(r.get('synthetic') for r in app.results.values()))
        self.assertTrue(app.io.log.virtual)
        self.assertFalse(list(Path(hn.home).rglob('command_log.txt')))


class Report(unittest.TestCase):
    def test_report_header_names_the_tbs1000(self):
        a = B.TBS1000App.__new__(B.TBS1000App)
        a.demo, a.cfg = False, T.Config('1102', FAM)
        a._found, a._left = {}, {}
        gain = next(p for p in POINTS if p['kind'] == 'GAIN')
        raw = dict(reading=0.0351)
        a.found[str(gain['id'])] = dict(reading=0.0351, raw=raw, result='PASS', synthetic=False, uncertainty=T.uncertainty_text(gain, raw), timestamp='t',
                                        data='As Found')
        a.asset = type('V', (), {'get': lambda s: 'A7'})()
        a.serial = type('V', (), {'get': lambda s: 'S7'})()
        a.status = type('V', (), {'set': lambda s, v: None})()
        a.root = None
        got = {}
        import report_pdf
        with mock.patch.object(T.port, 'report_details', lambda *a_, **k: {}), \
                mock.patch.object(T.port, 'save_file', lambda **k: os.path.join(tempfile.gettempdir(), k['initialfile'])), \
                mock.patch.object(report_pdf, 'write_calibration_pdf', lambda path, rows, **k: got.update(path=path, rows=rows, **k)), \
                mock.patch.object(report_pdf, 'context_for', lambda app: None):
            a.export_pdf()
        self.assertEqual(got['title'], 'Calibration Data')
        self.assertFalse(got['demo'])
        self.assertIn(('Instrument', 'Tektronix TBS1102'), got['header'])
        self.assertIn(('Source', 'TBS1000 Series Service Manual 077-0772-01 Rev D, Chapter 4'), got['header'])
        self.assertEqual(got['rows'][0]['Nominal'], '35.0 mV')
        self.assertNotIn('Notes:', got['footer_note'])                           # only the recorded DC gain point: no note applies                   # display-only SI scaling; the spec keeps 0.035 V
        self.assertEqual(gain['nominal'], 0.035)


class ManagerEntry(unittest.TestCase):
    def test_launcher_and_sidecar(self):
        import procscan
        src = (ROOT / 'Procedures' / 'Tektronix_TBS1000_Verification.py').read_text(encoding='utf-8')
        self.assertIn('tbs1000_verification.main_tbs1000()', src)
        p = next(p for p in procscan.procs(ROOT) if p.id == 'Tektronix_TBS1000_Verification')
        self.assertEqual(p.registration[0], 'Tektronix TBS1000 Performance Verification')
        self.assertFalse(p.seed_verified)
        for f in ('tds2000c_verification.py', 'tbs1000_verification.py', 'drivers/tektronix_tbs1000.py', 'drivers/tektronix_tds2000c.py'):
            self.assertIn(f, p.fingerprint_code)


if __name__ == '__main__':
    unittest.main()
