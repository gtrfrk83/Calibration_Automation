"""Fluke i400 clamp verification (i400_verification.py, specs/fluke_i400_pv.json, drivers/simulated_i400.py).

Part 1: the spec (3 points, printed limits against 2 % + 0.06 A in Decimal, applied x turns = clamp amps).
Part 2: the engine on the simulated bench with each calibrator: command order, standby after each point, direct pre-calibration, correction maths, judging,
the 8846A / 34401A adapters over a fake transport, report rows with uncertainty, demo marking.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_fluke_i400_points"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

A = VH = PTS = SPEC = None
CAL_KEY = {'Fluke 5522A': '5522A', 'Fluke 5560A': '5560A', 'Fluke 5520A': '5520A'}
PRINTED = {1: ('0.920', '1.080'), 2: ('97.94', '102.06'), 3: ('391.94', '408.06')}


def setUpModule():
    global A, VH, PTS, SPEC
    import _tk_stub
    _tk_stub.install()
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import virtual_harness as _vh
    import i400_verification as _a
    A, VH, PTS, SPEC = _a, _vh, _a.POINTS, _a.SPEC


def bench(cal='5522A'):
    from drivers.simulated_i400 import make_i400_bench
    return make_i400_bench(cal, 'GPIB')


class SpecTests(unittest.TestCase):
    def test_counts_and_limits(self):
        self.assertEqual([len(s['points']) for s in SPEC['sections']], [1, 2])
        self.assertEqual(len(PTS), 3)
        for p in PTS:
            lo, hi = PRINTED[p['step']]
            nominal = D(str(p['nominal'])) * 1000
            half = D(str(p['error'])) * 1000
            self.assertEqual((nominal - half, nominal + half), (D(lo), D(hi)))
            self.assertEqual(D(str(p['applied']['value'])) * p['turns'], D(str(p['clamp_amps'])))
            self.assertEqual(half, (D('0.02') * D(str(p['clamp_amps'])) + D('0.06')))
        self.assertEqual([p['group'] for p in PTS], ['WIRE_1T', 'COIL_AUX', 'COIL_20A'])
        self.assertEqual([p['lcomp'] for p in PTS], ['OFF', 'ON', 'ON'])
        self.assertEqual([p['applied']['frequency'] for p in PTS], [45.0, 400.0, 60.0])

    def test_judge_is_decimal(self):
        p = PTS[0]
        self.assertTrue(A.judge(p, 0.00108)); self.assertFalse(A.judge(p, 0.0010801))
        self.assertTrue(A.judge(p, 0.00092)); self.assertFalse(A.judge(p, 0.0009199))

    def test_diagram_lookup_names(self):
        self.assertIsNone(A.find_diagram('5522A', 'WIRE_1T'))


class Flow(unittest.TestCase):
    def setUp(self):
        self.hn = VH.VHarness().start()
        A.messagebox = VH.hh.messagebox

    def tearDown(self):
        self.hn.stop()

    def app(self, fast=False, cal='Fluke 5560A', **settings):
        a = A.App(self.hn.root, demo=True, fast_demo=fast)
        a.asset.set('A-1'); a.serial.set('S-1'); a.cal_model.set(cal); a.dmm_model.set(settings.pop('dmm_model', 'Keysight 34410A'))
        for k, v in settings.items():
            getattr(a, k).set(v)
        self.hn.app = a
        return a

    def io(self, cal='Fluke 5522A', dmm='Keysight 34410A'):
        b, ft, dt = bench(CAL_KEY[cal])
        io = A.IO('sim', 'sim', cal, 9600, 'GPIB', transports=(dt, ft), dmm_model=dmm)
        io.reset_at_start()
        return io, dt

    def test_virtual_run_every_calibrator(self):
        for cal in ('Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A'):
            a = self.app(cal=cal)
            self.assertTrue(self.hn.run_all(), cal)
            self.assertEqual(len(a.results), 3, cal)
            self.assertTrue(all(r['result'] == 'PASS' and r['synthetic'] for r in a.results.values()), cal)
            self.assertEqual(len(a.dmm_corr), 3, cal)
            self.assertTrue(a.any_synthetic())
            self.assertFalse(self.hn.boxes('showerror'), cal)
            self.hn.stop(); self.hn = VH.VHarness().start(); A.messagebox = VH.hh.messagebox

    def test_precal_off_skips_direct_phase(self):
        a = self.app(cal='Fluke 5522A', precal=False)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(a.dmm_corr, {})
        self.assertTrue(all(not r['precal'] for r in a.results.values()))

    def test_command_order_and_standby(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        cal = [t for d, t in VH.wire(a.io) if d == '5522A']
        self.assertIn('OUT 1A,45Hz', cal); self.assertIn('OUT 2A,400Hz', cal); self.assertIn('OUT 8A,60Hz', cal)
        self.assertIn('OUT 0.001A,45Hz', cal); self.assertIn('OUT 0.4A,60Hz', cal)           # the direct pre-calibration
        for i, t in enumerate(cal):
            if t == 'OPER':
                nxt = next(x for x in cal[i + 1:] if x != 'OPER?')
                self.assertEqual(nxt, 'STBY')
        self.assertEqual(cal[-1], 'STBY')

    def test_clamp_path_reading_and_correction(self):
        io, dt = self.io()
        dt.path = 'direct'
        p = PTS[1]
        direct = io.measure_direct(p)
        self.assertAlmostEqual(direct, p['nominal'], delta=p['nominal'] * 1e-4)
        dt.path, dt.turns = 'clamp', 50
        clamp = io.measure(p)
        self.assertAlmostEqual(clamp, p['nominal'] * 1.005, delta=p['nominal'] * 1e-4)
        self.assertTrue(A.judge(p, clamp))
        dt.clamp_gain = 1.03
        self.assertFalse(A.judge(p, io.measure(p)))

    def test_correction_added_to_reading(self):
        a = self.app(cal='Fluke 5522A')
        p = PTS[1]
        a.dmm_corr[str(p['id'])] = dict(applied=p['nominal'], reading=p['nominal'] * 1.001, correction=-p['nominal'] * 0.001)
        a._done([p], 0, p, p['nominal'] * 1.001, ('calibrator', 'COIL_AUX'))
        r = a.results[str(p['id'])]
        self.assertAlmostEqual(r['reading'], p['nominal'], delta=1e-12)
        self.assertAlmostEqual(r['raw'], p['nominal'] * 1.001, delta=1e-12)

    def test_report_rows_and_uncertainty(self):
        a = self.app(cal='Fluke 5522A')
        self.assertTrue(self.hn.run_all())
        rows, pts = a.certificate_rows_and_points()
        self.assertEqual(len(rows), 3)
        for p in pts:
            fields = a.certificate_fields(p)
            self.assertIn('TAR', fields)
        q, std = a._unc_point(PTS[1])
        self.assertEqual(q['frequency'], 400.0)

    def test_adapters_over_fake_transport(self):
        for cls in (A.Reading8846A, A.Reading34401A):
            sent = []

            class T:
                def write(self, c): sent.append(c)
                def read(self): return '+0,"No error"' if sent[-1].upper().startswith('SYST:ERR') else '+1.0E-03'
                def query(self, c): self.write(c); return self.read()
                def open(self, *a, **k): pass
                def close(self): pass
                def clear(self): pass
            d = cls(T(), A.drivers.CommandLog(), label='x')
            d.configure_point(dict(kind='ACI', range=0.01))
            self.assertIn('CONF:CURR:AC 0.01', sent)
            d.check_errors('test')
            self.assertEqual(d.front_rear(), 'FRONT'); self.assertEqual(d.firmware_warning(), '')


class Manual(Flow):
    """Manual entry: the calibrator is driven, the operator types the reading (mA), no multimeter, no pre-calibration."""
    def test_default_is_manual(self):
        self.assertEqual(A.DEFAULT_DMM, A.MANUAL)

    def test_manual_run_types_readings_and_skips_precal(self):
        a = self.app(cal='Fluke 5522A', dmm_model=A.MANUAL)
        self.assertTrue(a.manual and not a.precal_on)
        self.hn.default_reading = lambda p: {1: '1.010', 2: '100.5', 3: '400.2'}[p['id']]
        self.assertTrue(self.hn.run_all())
        self.assertEqual(a.dmm_corr, {})
        self.assertIsNone(a.io.dmm)
        self.assertEqual({k: v['result'] for k, v in a.results.items()}, {'1': 'PASS', '2': 'PASS', '3': 'PASS'})
        self.assertAlmostEqual(a.results['2']['reading'], 0.1005, places=9)
        cal = [t for d, t in VH.wire(a.io) if d == '5522A']
        self.assertIn('OUT 8A,60Hz', cal)
        self.assertFalse([t for t in cal if t.startswith('OUT 0.')])               # no direct pre-calibration outputs
        for i, t in enumerate(cal):
            if t == 'OPER':
                self.assertEqual(next(x for x in cal[i + 1:] if x != 'OPER?'), 'STBY')
        self.assertEqual(cal[-1], 'STBY')

    def test_typed_out_of_limit_fails(self):
        a = self.app(dmm_model=A.MANUAL)
        self.hn.default_reading = lambda p: {1: '1.090', 2: '100.0', 3: '400.0'}[p['id']]
        self.assertTrue(self.hn.run_all())
        self.assertEqual(a.results['1']['result'], 'FAIL')

    def test_parse(self):
        self.assertAlmostEqual(A.App.parse_typed_ma('100.5'), 0.1005)
        for bad in ('', 'abc', 'nan'):
            with self.assertRaises(ValueError):
                A.App.parse_typed_ma(bad)


class Registration(unittest.TestCase):
    def test_launcher_and_sidecar(self):
        import json
        d = json.loads((ROOT / 'Procedures' / 'Fluke_i400_Verification.procedure.json').read_text())
        self.assertEqual(d['id'], 'Fluke_i400_Verification')
        for f in d['own_files'] + d['fingerprint']['code']:
            self.assertTrue((ROOT / f).exists(), f)


if __name__ == '__main__':
    unittest.main()
